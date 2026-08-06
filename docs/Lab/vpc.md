# Module 04 — Amazon VPC (Virtual Private Cloud) with Floci

> **Course:** Cloud Computing & AWS for Software Engineers (Year 4)
> **Delivery:** CLI-only. No AWS Management Console.
> **Emulator:** Floci CLI (local AWS emulator, endpoint `http://localhost:4566`)
> **Certification alignment:** AWS Certified Solutions Architect – Associate (SAA-C03), Domain 1 (Secure Architectures) and Domain 2 (Resilient Architectures)
> **Prerequisite modules:** `docs/iam.md` (Module 01). This module reuses the `guard()` function, the probe-harness pattern and the Druk National Bank scenario established there.

---

## 0. Before You Begin

### 0.1 Why VPC is the hardest module to teach on an emulator — read this first

Every other AWS service you will study is a **control plane with an API**. You call `CreateBucket`, an object appears, and `GetObject` proves it works. VPC is different. VPC is a **control plane that programs a data plane you cannot see**. The API calls you make (`CreateRouteTable`, `AuthorizeSecurityGroupIngress`) are not the product — they are *configuration instructions to a distributed software-defined network* that then decides, packet by packet, whether a frame is forwarded or silently dropped.

This has one enormous consequence for this module:

!!! danger "An emulator can store your network configuration. It almost certainly cannot route your packets."
    Floci speaks the EC2 wire protocol and will happily accept `CreateVpc`, `CreateSubnet`, `CreateRoute`, `CreateNetworkAclEntry` and `AuthorizeSecurityGroupIngress`. It will store those objects and return them from `Describe*` calls. That does **not** mean:

    * that a packet from one emulated instance to another is subjected to longest-prefix route matching;
    * that a security group actually filters anything;
    * that a network ACL rule number ordering is evaluated;
    * that the absence of an internet gateway route prevents egress.

    Real AWS enforces all of that in the Nitro/hypervisor data plane. An emulator that ran on a single Docker network almost by definition does not.

Therefore this module is deliberately built on **three tracks**, always side by side:

| Track | Question it answers | How you validate it |
|---|---|---|
| **A — Modelling & topology** | Does the object exist, associate, and describe correctly? Can I *express* the intended design in the API? | Verifiable in Floci with `describe-*` + `jq` |
| **B — Data-plane semantics** | Would a packet actually flow in real AWS, and why? | Reasoned, then **computed** by the reachability evaluator you build in §0.6 |
| **C — Divergence** | Where does my emulator's behaviour differ from AWS, and what does that mean for my mental model? | The probe harnesses in §0.5, recorded as findings |

!!! warning "The reporting rule for this module"
    Never write in a lab report *"the security group blocked my traffic."* Unless you observed a timeout or `RequestTimeout` yourself, write:

    > *"AWS would drop this packet because the app-tier security group has no inbound rule matching TCP/5432 from `sg-web`; my Floci build accepted the connection, which is a data-plane divergence recorded in `out/divergence-log.md`."*

This discipline is not academic pedantry. Engineers who learned networking on emulators and never made this distinction are the same engineers who open `0.0.0.0/0` on port 22 "because it worked locally".

### 0.2 Prerequisites

| Requirement | Minimum | Verify with |
|---|---|---|
| Floci CLI | installed and on `PATH` | `floci --version` |
| Docker Engine | running | `docker info \| head -n 3` |
| AWS CLI | v2.x | `aws --version` |
| `jq` | 1.6+ | `jq --version` |
| Python | 3.9+ (for the reachability evaluator) | `python3 --version` |
| `ipcalc` **or** Python `ipaddress` | either | `python3 -c "import ipaddress; print('ok')"` |
| Completed | Module 01 (IAM) | you should have `~/iam-lab/out/support-matrix.tsv` |
| Concepts | IPv4 addressing, CIDR notation, subnet masks, TCP/UDP ports, stateful vs stateless firewalls, default gateways, NAT, DNS resolution | — |

!!! warning "Install `jq` and confirm Python 3 now"
    Every verification step pipes JSON through `jq`, and §0.6 builds a Python evaluator.
    Debian/Ubuntu: `sudo apt-get install -y jq python3`. macOS: `brew install jq python3`.

!!! note "Refresh your CIDR maths before Lab 2"
    If you cannot answer *"how many usable host addresses are in a `/20`, and what is the broadcast address of `10.20.32.0/20`?"* in under thirty seconds, spend fifteen minutes with `ipcalc` before starting. Lab 2 is unforgiving about this, and so is the SAA-C03 exam.

### 0.3 Starting the Floci environment

```bash
# 1. Start the emulator. --persist keeps state across restarts so your topology survives a reboot.
floci start --persist ./floci-state --detach

# 2. Block until the emulator is accepting requests (max 2 minutes)
floci wait --timeout 2m

# 3. Export AWS_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
eval "$(floci env)"

# 4. Confirm the shell is now pointed at Floci, not real AWS
echo "$AWS_ENDPOINT_URL"

# 5. Confirm the EC2 API is answering at all
aws ec2 describe-availability-zones --query 'AvailabilityZones[].ZoneName' --output text
```

**Parameter explanation**

| Flag | Meaning | Why we use it |
|---|---|---|
| `--persist ./floci-state` | Bind-mounts a host directory for emulator state | Your VPC, subnets and route tables survive `floci stop` — essential because these labs are cumulative |
| `--detach` | Returns immediately instead of streaming logs | Frees your terminal for lab work |
| `--timeout 2m` on `wait` | Readiness poll ceiling | First start pulls the image; the 30 s default is often too short |

Expected output of steps 4 and 5:

```
http://localhost.floci.io:4566
us-east-1a	us-east-1b	us-east-1c	us-east-1d	us-east-1e	us-east-1f
```

!!! note "If step 5 returns fewer AZs, or an error"
    Some builds synthesise only two or three availability zones. That is fine — this module needs exactly **two**. Record which two your build offers and substitute them consistently for `us-east-1a` and `us-east-1b` throughout. If the call fails with `InvalidAction`, your build did not start the EC2 service; try `floci start --services ec2,iam,s3,logs,sts`.

!!! danger "The single most important safety habit in this module"
    `AWS_ENDPOINT_URL` is what keeps your commands inside the emulator. If that variable is empty, **the exact same commands will hit real AWS** using whatever credentials sit in `~/.aws/credentials`. In the IAM module the worst case was a stray user. In this module the worst case is a **billable NAT gateway** (~USD 32/month per gateway, plus data processing) and **Elastic IPs**, which are charged when idle. Run this guard at the top of every lab session:

    ```bash
    guard() {
      case "${AWS_ENDPOINT_URL:-}" in
        *localhost*|*127.0.0.1*|*floci*) echo "OK: targeting Floci at $AWS_ENDPOINT_URL" ;;
        *) echo "REFUSING TO RUN: AWS_ENDPOINT_URL is '${AWS_ENDPOINT_URL:-<empty>}'" >&2; return 1 ;;
      esac
    }
    guard || eval "$(floci env)"
    ```

    Put `guard` in `~/.bashrc` if you have not already. Then make a habit of typing `guard` before every destructive or billable command in this module — `create-nat-gateway` and `allocate-address` above all.

### 0.4 Lab conventions used throughout this module

We continue the single fictional organisation from Module 01 (see §6): **Druk National Bank (DNB)**.

```
<org>-<environment>-<function>[-<qualifier>]
 dnb  -  dev       - vpc
 dnb  -  dev       - subnet     - public-1a
 dnb  -  dev       - rtb        - private-1a
 dnb  -  dev       - sg         - app
```

| Convention | Value | Rationale |
|---|---|---|
| Org prefix | `dnb-` | Namespaces every resource; makes bulk cleanup safe |
| Region | `us-east-1` | Consistent with Module 01 |
| Availability zones | `us-east-1a`, `us-east-1b` | Two AZs is the minimum for a resilient design and the minimum an ALB requires |
| VPC CIDR | `10.20.0.0/16` | RFC 1918; the `10.20.` prefix is DNB's allocation for `dev` |
| Subnet size | `/20` (4 096 addresses, 4 091 usable) | Generous enough for ECS/EKS pod density; leaves room for growth |
| Scratch directory | `~/vpc-lab` with `policies/`, `out/`, `bin/` | All JSON, scripts and captured output live here |
| Mandatory tags | `Project=CoreBanking`, `Environment=dev`, `Owner`, `CostCenter=CC-4400`, `ManagedBy=floci-lab` | Cost allocation + attribute-based access control |
| Tier tag | `Tier=public\|app\|data` | Drives the reachability matrix and NACL assignment |

```bash
mkdir -p ~/vpc-lab/policies ~/vpc-lab/out ~/vpc-lab/bin && cd ~/vpc-lab
```

We will also keep a **resource id ledger** so that every lab can reference earlier resources without you re-typing ids:

```bash
cat > ~/vpc-lab/bin/ids.sh <<'SH'
# ~/vpc-lab/bin/ids.sh — a tiny key/value store for resource ids.
# Source this file (do not execute it) so the functions land in your shell.
LEDGER="$HOME/vpc-lab/out/ids.env"
mkdir -p "$HOME/vpc-lab/out"
touch "$LEDGER"

setid() {  # setid VPC_ID vpc-0abc...
  local k="$1" v="$2"
  # remove any previous value, then append
  grep -v "^export ${k}=" "$LEDGER" > "${LEDGER}.tmp" 2>/dev/null || true
  mv "${LEDGER}.tmp" "$LEDGER"
  printf 'export %s=%s\n' "$k" "$v" >> "$LEDGER"
  export "$k=$v"
  printf 'ledger: %s=%s\n' "$k" "$v"
}

loadids() { set -a; . "$LEDGER"; set +a; }
SH
echo "ledger helper written to ~/vpc-lab/bin/ids.sh"
```

```bash
# Load it into every new shell (source, do not run):
. ~/vpc-lab/bin/ids.sh
loadids
```

!!! tip "Why a ledger and not shell history"
    A VPC build produces roughly thirty interdependent opaque ids (`vpc-…`, `subnet-…`, `rtb-…`, `igw-…`, `nat-…`, `acl-…`, `sg-…`, `eni-…`, `vpce-…`). Losing them mid-lab is the single most common reason students cannot finish. The ledger is also your audit trail: `cat ~/vpc-lab/out/ids.env` is the first thing you paste into a lab report.

!!! note "For the instructor: MkDocs configuration"
    This document uses admonitions (`!!! note`) and collapsible blocks (`??? note`, used for the hints in §12). Enable both in `mkdocs.yml`:

    ```yaml
    theme:
      name: material
    markdown_extensions:
      - admonition
      - pymdownx.details        # required for the ??? collapsible hints
      - pymdownx.superfences
      - attr_list
      - tables
      - toc:
          permalink: true
    ```

    Without `pymdownx.details` the `??? note` hint blocks in §12 render as plain text and the answers become visible immediately.

### 0.5 Floci support tiers — and how to verify them yourself

At the time of writing, Floci's published EC2 coverage includes the following VPC-relevant operation families:

* **VPC:** `CreateVpc`, `DescribeVpcs`, `DeleteVpc`, `ModifyVpcAttribute`, `DescribeVpcAttribute`, `CreateDefaultVpc`, `AssociateVpcCidrBlock`, `DisassociateVpcCidrBlock`
* **Subnets:** `CreateSubnet`, `DescribeSubnets`, `DeleteSubnet`, `ModifySubnetAttribute`
* **Route tables:** `CreateRouteTable`, `DescribeRouteTables`, `DeleteRouteTable`, `AssociateRouteTable`, `DisassociateRouteTable`, `CreateRoute`, `DeleteRoute`
* **Internet gateways:** `CreateInternetGateway`, `DescribeInternetGateways`, `DeleteInternetGateway`, `AttachInternetGateway`, `DetachInternetGateway`
* **NAT gateways:** `CreateNatGateway`, `DescribeNatGateways`, `DeleteNatGateway`
* **Elastic IPs:** `AllocateAddress`, `DescribeAddresses`, `DescribeAddressesAttribute`, `AssociateAddress`, `DisassociateAddress`, `ReleaseAddress`
* **Security groups:** `CreateSecurityGroup`, `DescribeSecurityGroups`, `DeleteSecurityGroup`, `AuthorizeSecurityGroupIngress`, `AuthorizeSecurityGroupEgress`, `RevokeSecurityGroupIngress`, `RevokeSecurityGroupEgress`, `DescribeSecurityGroupRules`, `ModifySecurityGroupRules`, `UpdateSecurityGroupRuleDescriptionsIngress/Egress`
* **Network ACLs:** `CreateNetworkAcl`, `DescribeNetworkAcls`, `DeleteNetworkAcl`, `CreateNetworkAclEntry`, `ReplaceNetworkAclEntry`, `DeleteNetworkAclEntry`, `ReplaceNetworkAclAssociation`
* **Endpoints:** `CreateVpcEndpoint`, `DescribeVpcEndpoints`, `DeleteVpcEndpoints`, `DescribeVpcEndpointServices`
* **Also listed:** network interfaces, prefix lists, key pairs, AMIs, tags, launch templates, volumes, instance types, availability zones

Conspicuously **absent** from the published list: VPC peering, flow logs, DHCP option sets, transit gateways, egress-only internet gateways, IPAM, Reachability Analyzer, Network Firewall, Traffic Mirroring, Site-to-Site VPN, Direct Connect.

| Tier | Symbol | Meaning | How you must treat it |
|---|---|---|---|
| Fully supported | ✅ | Operation exists and the stored object behaves like AWS | Build, verify and break it locally |
| Partially supported | ⚠️ | Operation accepts the call and stores the object, but the *packet-level consequence* is not enforced | Verify the object; compute the AWS verdict with the evaluator (§0.6) |
| Not supported | ❌ | Operation errors or is absent | Conceptual discussion + closest local approximation, clearly labelled |

!!! danger "For VPC, ⚠️ is the default, not the exception"
    In the IAM module, most operations were ✅ for structure and ⚠️ only for enforcement. In VPC, **every single filtering and routing component is ⚠️ by nature**, because the emulator has no packet forwarding plane. Route tables, security groups and NACLs are all "stored faithfully, enforced not at all" until your own probe proves otherwise.

    Restating the critical rule from Module 01, adapted: **a `describe-route-tables` that shows your `0.0.0.0/0 → igw-…` route proves only that the row exists.** It does not prove that an instance in that subnet can reach the internet, nor that one in a private subnet cannot.

#### 0.5.1 The VPC support-probe harness

You already built `classify()` in `~/iam-lab/probe-support.sh` (Module 01 §0.5.1). The classification logic is identical here; only the operation list and the "routed-and-validated" error codes change, because EC2 uses `Invalid*.NotFound` / `InvalidParameterValue` / `MissingParameter` rather than IAM's `NoSuchEntity`.

Save as `~/vpc-lab/bin/probe-vpc-support.sh`:

```bash
#!/usr/bin/env bash
# probe-vpc-support.sh — discover which EC2/VPC operations this Floci build implements.
# Strategy: call each operation with read-only or deliberately bogus arguments and
# classify by the ERROR CODE, not by success alone.
set -uo pipefail

OUT=~/vpc-lab/out/support-matrix.tsv
: > "$OUT"

classify() {
  local name="$1"; shift
  local stderr rc
  stderr="$("$@" 2>&1 >/dev/null)"; rc=$?
  if [ $rc -eq 0 ]; then
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED" "-" >> "$OUT"
  elif grep -qiE 'InvalidAction|not implemented|NotImplemented|UnknownOperation|InternalFailure|501|Unknown operation' <<<"$stderr"; then
    printf '%s\t%s\t%s\n' "$name" "UNSUPPORTED" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  elif grep -qiE 'NotFound|InvalidParameterValue|MissingParameter|InvalidParameterCombination|ValidationError|Malformed|AlreadyExists|InvalidVpcID|InvalidSubnetID|InvalidGroup|InvalidRouteTableID|InvalidNetworkAclID|InvalidAllocationID|InvalidAddress' <<<"$stderr"; then
    # Routed to a real handler which then rejected our fake input -> the operation exists.
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED(validated)" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  else
    printf '%s\t%s\t%s\n' "$name" "UNKNOWN" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  fi
}

# --- Read-only describes: safe on any account ---
for op in describe-vpcs describe-subnets describe-route-tables describe-internet-gateways \
          describe-nat-gateways describe-security-groups describe-network-acls \
          describe-addresses describe-network-interfaces describe-vpc-endpoints \
          describe-prefix-lists describe-managed-prefix-lists describe-availability-zones \
          describe-vpc-peering-connections describe-flow-logs describe-dhcp-options \
          describe-egress-only-internet-gateways describe-transit-gateways \
          describe-vpc-endpoint-services describe-instances describe-key-pairs; do
  classify "ec2:$op" aws ec2 "$op"
done

# --- Operations probed with a deliberately non-existent resource id ---
# A NotFound/InvalidParameterValue proves the operation is routed & implemented.
classify "ec2:describe-vpc-attribute"        aws ec2 describe-vpc-attribute --vpc-id vpc-00000000000000000 --attribute enableDnsSupport
classify "ec2:modify-vpc-attribute"          aws ec2 modify-vpc-attribute --vpc-id vpc-00000000000000000 --enable-dns-hostnames
classify "ec2:modify-subnet-attribute"       aws ec2 modify-subnet-attribute --subnet-id subnet-00000000000000000 --map-public-ip-on-launch
classify "ec2:create-subnet"                 aws ec2 create-subnet --vpc-id vpc-00000000000000000 --cidr-block 10.99.0.0/24
classify "ec2:create-route"                  aws ec2 create-route --route-table-id rtb-00000000000000000 --destination-cidr-block 0.0.0.0/0 --gateway-id igw-00000000000000000
classify "ec2:associate-route-table"         aws ec2 associate-route-table --route-table-id rtb-00000000000000000 --subnet-id subnet-00000000000000000
classify "ec2:attach-internet-gateway"       aws ec2 attach-internet-gateway --internet-gateway-id igw-00000000000000000 --vpc-id vpc-00000000000000000
classify "ec2:create-nat-gateway"            aws ec2 create-nat-gateway --subnet-id subnet-00000000000000000 --allocation-id eipalloc-00000000000000000
classify "ec2:authorize-security-group-ingress" aws ec2 authorize-security-group-ingress --group-id sg-00000000000000000 --protocol tcp --port 443 --cidr 10.0.0.0/8
classify "ec2:create-network-acl-entry"      aws ec2 create-network-acl-entry --network-acl-id acl-00000000000000000 --ingress --rule-number 100 --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow
classify "ec2:replace-network-acl-association" aws ec2 replace-network-acl-association --association-id aclassoc-00000000000000000 --network-acl-id acl-00000000000000000
classify "ec2:create-vpc-endpoint"           aws ec2 create-vpc-endpoint --vpc-id vpc-00000000000000000 --service-name com.amazonaws.us-east-1.s3
classify "ec2:associate-vpc-cidr-block"      aws ec2 associate-vpc-cidr-block --vpc-id vpc-00000000000000000 --cidr-block 100.64.0.0/16
classify "ec2:create-vpc-peering-connection" aws ec2 create-vpc-peering-connection --vpc-id vpc-00000000000000000 --peer-vpc-id vpc-11111111111111111
classify "ec2:create-flow-logs"              aws ec2 create-flow-logs --resource-type VPC --resource-ids vpc-00000000000000000 --traffic-type ALL --log-group-name x --deliver-logs-permission-arn arn:aws:iam::000000000000:role/x
classify "ec2:create-dhcp-options"           aws ec2 create-dhcp-options --dhcp-configurations 'Key=domain-name,Values=[probe.invalid]'
classify "ec2:create-egress-only-internet-gateway" aws ec2 create-egress-only-internet-gateway --vpc-id vpc-00000000000000000
classify "ec2:create-managed-prefix-list"    aws ec2 create-managed-prefix-list --prefix-list-name __probe__ --max-entries 1 --address-family IPv4
classify "ec2:create-transit-gateway"        aws ec2 create-transit-gateway
classify "ec2:start-network-insights-analysis" aws ec2 start-network-insights-analysis --network-insights-path-id nip-00000000000000000
classify "ec2:describe-vpcs(filtered)"       aws ec2 describe-vpcs --filters Name=tag:Project,Values=CoreBanking

column -t -s $'\t' "$OUT"
echo
echo "SUMMARY:"; awk -F'\t' '{c[$2]++} END{for(k in c) printf "  %-22s %d\n", k, c[k]}' "$OUT"
```

Run it once and keep the output — you will cite this file in every lab report:

```bash
chmod +x ~/vpc-lab/bin/probe-vpc-support.sh
~/vpc-lab/bin/probe-vpc-support.sh | tee ~/vpc-lab/out/support-report.txt
```

Expected output *shape* (your values will differ — that is the entire point):

```
ec2:describe-vpcs                     SUPPORTED             -
ec2:describe-subnets                  SUPPORTED             -
ec2:describe-route-tables             SUPPORTED             -
ec2:describe-flow-logs                UNSUPPORTED           InvalidAction: ...
ec2:create-vpc-peering-connection     UNSUPPORTED           InvalidAction: ...
ec2:create-subnet                     SUPPORTED(validated)  InvalidVpcID.NotFound: ...
ec2:create-nat-gateway                SUPPORTED(validated)  InvalidSubnetID.NotFound: ...
ec2:start-network-insights-analysis   UNSUPPORTED           InvalidAction: ...
...
SUMMARY:
  SUPPORTED              18
  SUPPORTED(validated)   14
  UNSUPPORTED             7
  UNKNOWN                 2
```

!!! tip "How to read the probe results"
    * `SUPPORTED` — the call succeeded outright.
    * `SUPPORTED(validated)` — the call was *routed to a real handler* which then rejected your fake input (`InvalidVpcID.NotFound`, `InvalidParameterValue`). Strong evidence the operation exists.
    * `UNSUPPORTED` — the emulator does not know this action (`InvalidAction`, `NotImplemented`).
    * `UNKNOWN` — inspect the message by hand and reclassify.

    Two known traps: `describe-flow-logs` and `describe-vpc-peering-connections` may return an **empty list** rather than an error even when the *create* operation is unimplemented. An empty successful `Describe` is therefore **not** proof of support — that is exactly why every mutating operation is probed separately above.

    Clean up the one artefact this probe may create, if `create-managed-prefix-list` happened to succeed:

    ```bash
    pl=$(aws ec2 describe-managed-prefix-lists \
           --filters Name=prefix-list-name,Values=__probe__ \
           --query 'PrefixLists[0].PrefixListId' --output text 2>/dev/null || echo None)
    [ "$pl" != "None" ] && [ -n "$pl" ] && aws ec2 delete-managed-prefix-list --prefix-list-id "$pl"
    ```

#### 0.5.2 The data-plane probe harness — does this emulator route anything?

This harness is unique to the VPC module and answers the question the support matrix cannot: *is there a data plane at all?* Save as `~/vpc-lab/bin/probe-dataplane.sh`. Run it **after Lab 8**, when you have instances.

```bash
#!/usr/bin/env bash
# probe-dataplane.sh — establish whether this Floci build has any VPC data plane.
# Answers three questions:
#   1. Do emulated instances receive addresses from the subnet CIDR we defined?
#   2. Does the emulator report an instance as reachable/running?
#   3. Is there any evidence of packet-level filtering?
set -uo pipefail
loadids 2>/dev/null || { set -a; . ~/vpc-lab/out/ids.env; set +a; }

echo "=== 1. Address assignment fidelity ==="
aws ec2 describe-instances \
  --filters Name=tag:Project,Values=CoreBanking \
  --query 'Reservations[].Instances[].{Id:InstanceId,Subnet:SubnetId,Priv:PrivateIpAddress,State:State.Name}' \
  --output table

echo
echo "=== 2. Does the reported private IP fall inside the subnet CIDR we asked for? ==="
python3 - <<'PY'
import ipaddress, json, subprocess, sys
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True,text=True).stdout or "{}")
subs = {s["SubnetId"]: s["CidrBlock"] for s in aws("describe-subnets").get("Subnets",[])}
bad = ok = 0
for r in aws("describe-instances").get("Reservations",[]):
    for i in r.get("Instances",[]):
        sid, ip = i.get("SubnetId"), i.get("PrivateIpAddress")
        if not sid or not ip or sid not in subs:
            continue
        if ipaddress.ip_address(ip) in ipaddress.ip_network(subs[sid]):
            ok += 1
            print(f"  OK       {i['InstanceId']} {ip} in {subs[sid]}")
        else:
            bad += 1
            print(f"  DIVERGES {i['InstanceId']} {ip} NOT in {subs[sid]}")
print(f"\n  in-CIDR={ok}  out-of-CIDR={bad}")
if bad:
    print("  FINDING: the emulator does not allocate from the subnet CIDR ->")
    print("           it has no IP address manager, therefore no data plane.")
PY

echo
echo "=== 3. Filtering evidence ==="
echo "Ask yourself, and record the answer in out/divergence-log.md:"
cat <<'TXT'
  - Did any Describe call report an ENI attached to the instance?
  - Does the emulator expose a container network you could exec into?
  - Did any command you ran ever return RequestTimeout / connection refused
    as a *consequence of a security group*, rather than of the API being down?
If the answer to the last question is "no", then for this build:
  Route tables  = metadata only
  Security groups = metadata only
  Network ACLs  = metadata only
and Track B verdicts in this module MUST come from the evaluator in Section 0.6,
never from observation.
TXT
```

```bash
chmod +x ~/vpc-lab/bin/probe-dataplane.sh
```

!!! note "`DIVERGES-FROM-AWS` is a finding, not a bug to fix"
    As in Module 01: divergence tells you which parts of your mental model the emulator cannot validate for you, and therefore which parts you must reason about carefully before you touch a real account. Keep a running `~/vpc-lab/out/divergence-log.md`. It is a graded deliverable (§17.4).

```bash
cat > ~/vpc-lab/out/divergence-log.md <<'MD'
# Floci divergence log — VPC module

| # | Lab | Operation / behaviour | AWS-correct behaviour | Observed in Floci | Impact on my mental model |
|---|-----|----------------------|-----------------------|-------------------|---------------------------|
| 1 |     |                      |                       |                   |                           |
MD
```

### 0.6 The reachability evaluator — making Track B executable

Because the emulator will not route packets for you, you are going to build the router yourself. `reach.py` reads your **actual** VPC configuration out of Floci and then applies **AWS's real evaluation algorithm** to decide whether a flow would be permitted. It is the single most valuable artefact you will produce in this module, and it forces you to encode the rules precisely rather than hand-wave them.

The algorithm it implements, in AWS's true order for a TCP connection from a source ENI to a destination:

```
                       ┌──────────────────────────────────────────┐
  packet leaves        │ 1. Source security group EGRESS rules    │  stateful
  source ENI  ───────► │    (allow-only; implicit deny)           │  (return traffic
                       └──────────────────┬───────────────────────┘   auto-permitted)
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 2. Source subnet NACL EGRESS rules       │  stateless
                       │    (numbered, first match wins, then *)  │  (return traffic
                       └──────────────────┬───────────────────────┘   NOT auto-permitted)
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 3. Source subnet ROUTE TABLE             │  longest-prefix
                       │    longest-prefix match -> target        │  match
                       └──────────────────┬───────────────────────┘
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 4. Destination subnet NACL INGRESS rules │  stateless
                       └──────────────────┬───────────────────────┘
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 5. Destination security group INGRESS    │  stateful
                       └──────────────────┬───────────────────────┘
                                          ▼
                                   DELIVERED
        and then, for the RETURN packet, steps 4 and 2 must be
        satisfied AGAIN by the NACLs on the EPHEMERAL port range,
        because NACLs are stateless. This asymmetry is the #1
        source of "my security group is right but it still hangs".
```

Save as `~/vpc-lab/bin/reach.py`:

```python
#!/usr/bin/env python3
"""reach.py — evaluate whether AWS would permit a flow, using the live Floci config.

Usage:
  reach.py --from-subnet subnet-aaa --to-ip 10.20.64.10 --to-subnet subnet-bbb \
           --port 5432 --proto tcp --src-sg sg-web --dst-sg sg-db

Exit status: 0 if the flow (and its return traffic) would be permitted, 1 otherwise.
This is a TEACHING model of AWS's evaluation order. It deliberately omits
route propagation, prefix lists and endpoint policies; see the LIMITATIONS note.
"""
import argparse
import ipaddress
import json
import subprocess
import sys

EPHEMERAL = (1024, 65535)  # Linux/ELB range used by AWS docs for NACL return rules


def aws(*args):
    """Call the AWS CLI against whatever endpoint the environment points at."""
    proc = subprocess.run(["aws", "ec2", *args, "--output", "json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(2)
    return json.loads(proc.stdout or "{}")


# ---------------------------------------------------------------- config loading
def route_table_for(subnet_id, vpc_id):
    """AWS rule: an explicitly associated table wins; otherwise the VPC main table."""
    tables = aws("describe-route-tables", "--filters",
                 f"Name=vpc-id,Values={vpc_id}").get("RouteTables", [])
    for t in tables:
        for a in t.get("Associations", []):
            if a.get("SubnetId") == subnet_id:
                return t, "explicit"
    for t in tables:
        for a in t.get("Associations", []):
            if a.get("Main"):
                return t, "main (implicit)"
    return None, "none"


def nacl_for(subnet_id, vpc_id):
    acls = aws("describe-network-acls", "--filters",
               f"Name=vpc-id,Values={vpc_id}").get("NetworkAcls", [])
    for a in acls:
        for assoc in a.get("Associations", []):
            if assoc.get("SubnetId") == subnet_id:
                return a
    for a in acls:
        if a.get("IsDefault"):
            return a
    return None


def subnet(subnet_id):
    got = aws("describe-subnets", "--subnet-ids", subnet_id).get("Subnets", [])
    if not got:
        sys.exit(f"no such subnet: {subnet_id}")
    return got[0]


def sg(group_id):
    got = aws("describe-security-groups", "--group-ids", group_id).get("SecurityGroups", [])
    if not got:
        sys.exit(f"no such security group: {group_id}")
    return got[0]


# ---------------------------------------------------------------- evaluation
def port_in(perm, port, proto):
    p = str(perm.get("IpProtocol"))
    if p == "-1":
        return True
    if p.lower() != proto.lower():
        return False
    lo, hi = perm.get("FromPort"), perm.get("ToPort")
    if lo is None:
        return True
    return lo <= port <= hi


def sg_permits(group, direction, peer_ip, peer_group_ids, port, proto):
    """Security groups are allow-only and stateful. Returns (bool, reason)."""
    perms = group["IpPermissions"] if direction == "ingress" else group.get("IpPermissionsEgress", [])
    for perm in perms:
        if not port_in(perm, port, proto):
            continue
        for r in perm.get("IpRanges", []):
            if peer_ip and ipaddress.ip_address(peer_ip) in ipaddress.ip_network(r["CidrIp"]):
                return True, f"{direction} rule {perm.get('IpProtocol')}:{perm.get('FromPort')} cidr {r['CidrIp']}"
        for pair in perm.get("UserIdGroupPairs", []):
            if pair.get("GroupId") in peer_group_ids:
                return True, f"{direction} rule {perm.get('IpProtocol')}:{perm.get('FromPort')} sg {pair['GroupId']}"
    return False, f"no matching {direction} rule -> IMPLICIT DENY"


def nacl_decision(acl, direction, peer_cidr_ip, port, proto):
    """NACLs are numbered, stateless, first-match-wins. Returns (allow, reason)."""
    egress = (direction == "egress")
    entries = sorted((e for e in acl["Entries"] if e["Egress"] == egress),
                     key=lambda e: e["RuleNumber"])
    for e in entries:
        cidr = e.get("CidrBlock")
        if not cidr:
            continue                      # ignore IPv6-only entries in this model
        if ipaddress.ip_address(peer_cidr_ip) not in ipaddress.ip_network(cidr):
            continue
        p = str(e["Protocol"])
        if p != "-1":
            want = {"tcp": "6", "udp": "17", "icmp": "1"}.get(proto.lower(), proto)
            if p != want:
                continue
            pr = e.get("PortRange")
            if pr and not (pr["From"] <= port <= pr["To"]):
                continue
        allow = e["RuleAction"] == "allow"
        return allow, f"rule {e['RuleNumber']} {e['RuleAction']} {cidr} proto={p}"
    return False, "fell through to rule * -> DENY"


def longest_prefix(table, dest_ip):
    best, best_len = None, -1
    for r in table.get("Routes", []):
        cidr = r.get("DestinationCidrBlock")
        if not cidr:
            continue
        net = ipaddress.ip_network(cidr)
        if ipaddress.ip_address(dest_ip) in net and net.prefixlen > best_len:
            best, best_len = r, net.prefixlen
    return best


def target_of(route):
    for k in ("GatewayId", "NatGatewayId", "TransitGatewayId", "VpcPeeringConnectionId",
              "NetworkInterfaceId", "InstanceId", "EgressOnlyInternetGatewayId"):
        if route.get(k):
            return f"{k}={route[k]}"
    return "unknown target"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-subnet", required=True)
    ap.add_argument("--to-ip", required=True)
    ap.add_argument("--to-subnet", help="omit for destinations outside the VPC")
    ap.add_argument("--from-ip", help="source private IP; defaults to first host in source subnet")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--proto", default="tcp")
    ap.add_argument("--src-sg", required=True)
    ap.add_argument("--dst-sg", help="omit for destinations outside the VPC")
    a = ap.parse_args()

    src = subnet(a.from_subnet)
    vpc_id = src["VpcId"]
    src_ip = a.from_ip or str(next(ipaddress.ip_network(src["CidrBlock"]).hosts()))
    src_sg = sg(a.src_sg)
    dst_sg = sg(a.dst_sg) if a.dst_sg else None

    verdict, steps = True, []

    def step(n, name, ok, reason):
        nonlocal verdict
        steps.append((n, name, "ALLOW" if ok else "DENY", reason))
        if not ok:
            verdict = False

    # 1. source SG egress (stateful)
    ok, why = sg_permits(src_sg, "egress", a.to_ip,
                         [a.dst_sg] if a.dst_sg else [], a.port, a.proto)
    step(1, f"src SG egress ({a.src_sg})", ok, why)

    # 2. source NACL egress (stateless)
    src_acl = nacl_for(a.from_subnet, vpc_id)
    ok, why = nacl_decision(src_acl, "egress", a.to_ip, a.port, a.proto)
    step(2, f"src NACL egress ({src_acl['NetworkAclId']})", ok, why)

    # 3. routing
    rt, how = route_table_for(a.from_subnet, vpc_id)
    if rt is None:
        step(3, "route table", False, "no route table resolvable")
    else:
        r = longest_prefix(rt, a.to_ip)
        if r is None:
            step(3, f"route table {rt['RouteTableId']} [{how}]", False,
                 f"no route matches {a.to_ip} -> BLACKHOLE")
        elif r.get("State") == "blackhole":
            step(3, f"route table {rt['RouteTableId']} [{how}]", False,
                 f"{r['DestinationCidrBlock']} -> {target_of(r)} is BLACKHOLE")
        else:
            step(3, f"route table {rt['RouteTableId']} [{how}]", True,
                 f"{r['DestinationCidrBlock']} -> {target_of(r)}")

    # 4 & 5. destination side, only if the destination is inside the VPC
    if a.to_subnet:
        dst_acl = nacl_for(a.to_subnet, vpc_id)
        ok, why = nacl_decision(dst_acl, "ingress", src_ip, a.port, a.proto)
        step(4, f"dst NACL ingress ({dst_acl['NetworkAclId']})", ok, why)

        ok, why = sg_permits(dst_sg, "ingress", src_ip, [a.src_sg], a.port, a.proto)
        step(5, f"dst SG ingress ({a.dst_sg})", ok, why)

        # 6 & 7. the RETURN packet: NACLs are stateless, ephemeral ports apply
        ok, why = nacl_decision(dst_acl, "egress", src_ip, EPHEMERAL[0], a.proto)
        step(6, f"dst NACL egress (return, ephemeral {EPHEMERAL[0]}-{EPHEMERAL[1]})", ok, why)

        ok, why = nacl_decision(src_acl, "ingress", a.to_ip, EPHEMERAL[0], a.proto)
        step(7, f"src NACL ingress (return, ephemeral {EPHEMERAL[0]}-{EPHEMERAL[1]})", ok, why)

    print(f"\nFLOW  {src_ip} ({a.from_subnet}/{a.src_sg})"
          f"  ->  {a.to_ip}:{a.port}/{a.proto}"
          f" ({a.to_subnet or 'outside VPC'}/{a.dst_sg or '-'})\n")
    for n, name, d, reason in steps:
        print(f"  {n}. {d:5}  {name:52}  {reason}")
    print(f"\nAWS VERDICT: {'PERMITTED' if verdict else 'BLOCKED'}")
    print("NOTE: this is the verdict *real AWS* would reach for the configuration "
          "currently stored in Floci. It is NOT an observation of emulator behaviour.")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
```

```bash
chmod +x ~/vpc-lab/bin/reach.py
python3 -c "import ipaddress, json, subprocess, argparse; print('reach.py deps OK')"
```

!!! warning "LIMITATIONS of `reach.py` — state them in your report"
    The evaluator models the five-plus-two step pipeline for IPv4 TCP/UDP/ICMP unicast flows. It deliberately does **not** model: route propagation from a virtual private gateway or transit gateway; managed prefix lists as route destinations; VPC endpoint policies; Gateway Load Balancer insertion; Network Firewall; `local` route precedence subtleties for secondary CIDRs; IPv6; asymmetric ephemeral ranges for Windows (`49152–65535`) or NAT gateways (`1024–65535`); and the fact that a NAT gateway rewrites the source address, so the destination side actually sees the NAT gateway's private IP, not the instance's. Extending it to handle the NAT source-rewrite is **Mini Challenge 7** (§11).

### 0.7 Recap of §0

* VPC is a control plane that programs an invisible data plane; an emulator gives you the former and not the latter.
* You will work on three tracks: model it (A), reason/compute what AWS would do (B), record where the emulator disagrees (C).
* You have four tools: `guard()`, `probe-vpc-support.sh`, `probe-dataplane.sh`, and `reach.py`.
* Every claim about traffic being allowed or blocked must cite either an observation or `reach.py`, and must say which.

---

## 1. Learning Outcomes

After completing this module, you will be able to:

**Design**

1. Translate a business and regulatory requirement into an IPv4 addressing plan, choosing a VPC CIDR and a subnet layout that leaves room for growth, avoids overlap with on-premises ranges, and spans at least two availability zones.
2. Explain and apply the tier model (public / private-app / private-data) and justify which resources belong in which tier.
3. Calculate usable host counts, accounting for the five addresses AWS reserves in every subnet.

**Build (CLI only)**

4. Create and tag a VPC, enable DNS support and DNS hostnames, and explain what each attribute changes.
5. Create subnets across multiple availability zones and control public IP auto-assignment.
6. Attach an internet gateway and build a public route table; build per-AZ private route tables behind NAT gateways.
7. Configure security groups using security-group references rather than CIDR literals, and explain why this is the correct default.
8. Configure network ACLs with correct rule numbering and correct ephemeral-port return rules.
9. Create gateway and interface VPC endpoints and explain how each changes the path taken by AWS API traffic.
10. Launch instances and additional elastic network interfaces into the topology and associate Elastic IPs.
11. Extend a VPC with a secondary IPv4 CIDR and an IPv6 CIDR.

**Verify and reason**

12. Verify every component with `describe-*` plus `jq`, and interpret `AvailableIpAddressCount`, route `State`, NAT gateway `State`, and NACL entry ordering.
13. Determine, from configuration alone, whether AWS would permit a given flow — including the stateless return path — and justify the answer step by step.
14. Distinguish security group behaviour from network ACL behaviour precisely enough to answer SAA-C03 scenario questions.

**Operate and secure**

15. Diagnose the standard VPC failure modes: `DependencyViolation`, `InvalidSubnet.Conflict`, `InvalidParameterValue` on CIDR, blackhole routes, missing route table associations, NAT in the wrong subnet, exhausted subnets, `AddressLimitExceeded`.
16. Apply least-privilege network design, tagging discipline, and IAM condition keys that constrain who may create or modify network resources.
17. Explain the security and cost consequences of NAT gateways, public subnets, and internet-bound AWS API traffic, and mitigate them with endpoints.

**Automate and integrate**

18. Write an idempotent shell script that builds the whole topology from nothing and emits a machine-readable topology document.
19. Explain how EC2, ELB, RDS, Lambda, ECS, S3, CloudWatch and Route 53 consume VPC constructs.
20. Tear the environment down in dependency order, leaving no orphaned resources.

**Meta**

21. State, for any VPC feature, whether it is verifiable in Floci, and if not, what the closest faithful local approximation is.

---

## 2. Service Overview

### 2.1 What Amazon VPC is

A **Virtual Private Cloud** is a logically isolated section of the AWS network in which you define your own IP address range, subnets, routing, and firewalling. Every network-attached AWS resource that has an IP address — an EC2 instance, an RDS database, an ELB node, a Lambda function configured for VPC access, an ECS task in `awsvpc` mode — is attached to a VPC through an **elastic network interface (ENI)**.

VPC is not a product you run; it is the **network substrate** on which nearly everything else runs. It is also free of charge in itself: you pay for the *things inside it* (NAT gateways, endpoint hours, data processing, Elastic IPs when idle, cross-AZ traffic), never for the VPC, subnets, route tables, security groups or NACLs.

Three properties define it:

| Property | What it means | Consequence |
|---|---|---|
| **Regional** | A VPC lives in exactly one region and spans all AZs in that region | You cannot stretch a VPC across regions; you connect regions with peering or transit gateway |
| **Software-defined** | There are no cables, switches or routers you administer; the "network" is a distributed mapping service | Changes are API calls, take effect in seconds, and are versionless — there is no "commit" or "rollback" |
| **Default-deny at the edge** | Nothing reaches the internet without an explicit gateway *and* an explicit route | Security is expressed by the *absence* of configuration as much as by its presence |

### 2.2 Why it exists — the problem it solves

Before VPC, EC2 ran in what is now called **EC2-Classic**: a flat, shared network where every instance received a public IP from a common pool and isolation was provided only by security groups. That model failed for four reasons, each of which maps directly to a VPC feature:

| Problem with a flat shared network | VPC feature that solves it |
|---|---|
| You could not choose your own address space, so you could not integrate with an existing on-premises network without NAT gymnastics | Customer-chosen VPC CIDR, secondary CIDRs, and VPN/Direct Connect |
| Everything had a public IP whether it needed one or not | Private subnets, NAT gateways, no-public-IP-by-default |
| Broadcast-domain-level isolation between tenants was not expressible | Subnets, network ACLs, and per-ENI security groups |
| Traffic to AWS APIs (S3, DynamoDB, KMS) always traversed the public internet | VPC endpoints / AWS PrivateLink |

### 2.3 Problems VPC solves, stated as engineering requirements

* **Network isolation.** Two VPCs are as isolated as two datacentres, even in the same account and region. They cannot communicate at all until you explicitly peer or transit them.
* **Address autonomy.** You pick the CIDR, so you can align with corporate IPAM and avoid overlap with branch offices.
* **Tiering and blast-radius reduction.** A compromised web server should not be able to reach the database on an arbitrary port. Subnet-level and ENI-level controls make that expressible.
* **Availability-zone-aware placement.** Subnets are AZ-scoped, so "deploy across two AZs" becomes a concrete, verifiable statement about which subnets you used.
* **Controlled egress.** NAT gateways give private instances outbound-only internet access for patching, with no inbound path.
* **Private access to AWS services.** Endpoints keep S3, DynamoDB, KMS, Secrets Manager and STS traffic off the public internet — usually a hard regulatory requirement in finance and health.
* **Observability of network flows.** Flow logs turn "something is talking to something" into queryable data.

### 2.4 Typical use cases

| Use case | Shape of the VPC |
|---|---|
| Three-tier web application | 2 AZs × (public + private-app + private-data); ALB in public, ASG in app, RDS in data |
| Batch / data processing | No public subnets at all; egress via NAT or endpoints only; large subnets for burst capacity |
| Hybrid enterprise | Non-overlapping CIDR aligned to corporate IPAM; VGW or Direct Connect; DNS forwarding via Route 53 Resolver |
| Multi-account landing zone | One VPC per account per environment, all attached to a central transit gateway; inspection VPC for egress |
| Serverless-first | Often *no* VPC at all, until a Lambda needs to reach RDS or an internal service; then VPC-attached Lambda + interface endpoints |
| SaaS provider | PrivateLink endpoint service so customers consume your app from their own VPCs without peering |

### 2.5 Industry examples

* **Retail banking (our scenario).** Regulators typically require that card-holder and account data never sit in a subnet with a route to an internet gateway, and that access to AWS control-plane APIs be private. This produces the classic pattern: data subnets with route tables containing only `local` plus endpoint prefix lists.
* **Healthcare.** HIPAA-driven designs use dedicated VPCs per environment and gateway endpoints for S3 so that PHI object traffic never leaves the AWS network.
* **Media streaming.** Very large public subnets fronting CDN origins, with per-AZ NAT to avoid cross-AZ data charges on egress-heavy workloads.
* **Government / regulated telco.** Inspection VPCs with Gateway Load Balancer and third-party firewalls in the path, achieved purely through route table manipulation.

### 2.6 Recap of §2

VPC is the regional, software-defined, default-deny network layer that every other AWS service plugs into. It exists because a flat shared network cannot express address autonomy, tiering, controlled egress, or private service access — and those four things are exactly what a regulated enterprise must be able to demonstrate to an auditor.

---

## 3. Internal Architecture

### 3.1 The object model

Read this diagram as a containment and reference graph. Solid nesting means "contained in"; arrows mean "references".

```
AWS Account
│
└── Region (us-east-1)                                     VPCs are REGIONAL
    │
    ├── VPC  vpc-…  10.20.0.0/16                           ← you choose the CIDR
    │   │    attributes: enableDnsSupport, enableDnsHostnames
    │   │    associations: primary CIDR + up to 4 secondary IPv4 CIDRs
    │   │                  + IPv6 /56
    │   │
    │   ├── implicit ROUTER (the "VPC router")             ← not an API object!
    │   │       always present, owns the `local` route,
    │   │       reachable at base+1 of every subnet
    │   │
    │   ├── DEFAULT objects created with the VPC (cannot be deleted):
    │   │      • main Route Table      rtb-…   (local only)
    │   │      • default Network ACL   acl-…   (allow all in + out)
    │   │      • default Security Group sg-…   (self-referencing in, all out)
    │   │
    │   ├── Subnet  subnet-…  10.20.0.0/20   AZ us-east-1a  ← AZ-SCOPED
    │   │      attributes: MapPublicIpOnLaunch, AssignIpv6AddressOnCreation
    │   │      5 addresses reserved by AWS
    │   │      ├── associated with exactly ONE Route Table  (explicit or main)
    │   │      ├── associated with exactly ONE Network ACL  (explicit or default)
    │   │      └── contains ENIs
    │   │            └── ENI eni-…  private IP(s), optional public IP / EIP
    │   │                  └── 1..5 Security Groups           ← SGs attach to ENIs,
    │   │                                                       NOT to instances
    │   ├── Subnet  subnet-…  10.20.16.0/20  AZ us-east-1b
    │   │
    │   ├── Route Table  rtb-…
    │   │      Routes:  10.20.0.0/16 -> local           (implicit, unremovable)
    │   │               0.0.0.0/0    -> igw-… | nat-… | pcx-… | tgw-… | eni-…
    │   │               pl-…         -> vpce-…          (gateway endpoint)
    │   │      Associations: 0..n subnets, or "main"
    │   │
    │   ├── Network ACL  acl-…
    │   │      Entries: numbered 1..32766 + implicit `*` DENY
    │   │      separate ingress and egress lists,  STATELESS
    │   │
    │   ├── Security Group  sg-…
    │   │      IpPermissions (ingress) + IpPermissionsEgress
    │   │      ALLOW-ONLY, STATEFUL, may reference other SGs
    │   │
    │   ├── Gateways & attachments
    │   │      • Internet Gateway    igw-…   1 per VPC, VPC-scoped, HA by AWS
    │   │      • NAT Gateway         nat-…   AZ-scoped, lives IN a public subnet,
    │   │                                    needs an Elastic IP (public type)
    │   │      • Egress-only IGW     eoigw-… IPv6 outbound only
    │   │      • Virtual Private GW   vgw-…   VPN / Direct Connect attachment
    │   │      • VPC Endpoint        vpce-…   Gateway (route entry) or
    │   │                                    Interface (ENI in a subnet)
    │   │      • Peering connection  pcx-…   1:1, non-transitive
    │   │
    │   └── DHCP option set  dopt-…   domain-name, domain-name-servers, NTP
    │
    └── other VPCs … completely isolated unless explicitly connected
```

### 3.2 The DNB reference topology you will build

```
                              ┌──────────────┐
                              │   Internet   │
                              └──────┬───────┘
                                     │
                              ┌──────┴───────┐
                              │ igw-dnb-dev  │  Internet Gateway (VPC-scoped)
                              └──────┬───────┘
                                     │
  ╔══════════════════════════════════╪════════════════════════════════════════╗
  ║ VPC  dnb-dev-vpc   10.20.0.0/16  │            (secondary: 100.64.0.0/16)  ║
  ║                                  │                                        ║
  ║   AZ us-east-1a                  │              AZ us-east-1b             ║
  ║  ┌──────────────────────────┐    │    ┌──────────────────────────┐        ║
  ║  │ PUBLIC  10.20.0.0/20     │◄───┴───►│ PUBLIC  10.20.16.0/20    │        ║
  ║  │ subnet-public-1a         │         │ subnet-public-1b         │        ║
  ║  │  • ALB node              │         │  • ALB node              │        ║
  ║  │  • nat-1a  (EIP)         │         │  • nat-1b  (EIP)         │        ║
  ║  │  rtb-public  0.0.0.0/0→igw         │  rtb-public (shared)     │        ║
  ║  │  acl: default (allow all)│         │  acl: default            │        ║
  ║  └───────────┬──────────────┘         └───────────┬──────────────┘        ║
  ║              │ 0.0.0.0/0 → nat-1a                 │ 0.0.0.0/0 → nat-1b    ║
  ║  ┌───────────┴──────────────┐         ┌───────────┴──────────────┐        ║
  ║  │ APP     10.20.32.0/20    │         │ APP     10.20.48.0/20    │        ║
  ║  │ subnet-app-1a            │         │ subnet-app-1b            │        ║
  ║  │  • statement workers     │         │  • statement workers     │        ║
  ║  │  sg-app: 8080 from sg-web│         │  rtb-private-1b          │        ║
  ║  │  rtb-private-1a          │         │                          │        ║
  ║  └───────────┬──────────────┘         └───────────┬──────────────┘        ║
  ║              │ local only                         │ local only            ║
  ║  ┌───────────┴──────────────┐         ┌───────────┴──────────────┐        ║
  ║  │ DATA    10.20.64.0/20    │         │ DATA    10.20.80.0/20    │        ║
  ║  │ subnet-data-1a           │         │ subnet-data-1b           │        ║
  ║  │  • RDS primary           │         │  • RDS standby           │        ║
  ║  │  sg-db: 5432 from sg-app │         │  sg-db (shared)          │        ║
  ║  │  rtb-data   NO 0.0.0.0/0 │         │  rtb-data (shared)       │        ║
  ║  │  acl-data: explicit deny │         │  acl-data (shared)       │        ║
  ║  └──────────────────────────┘         └──────────────────────────┘        ║
  ║                                                                            ║
  ║   VPC endpoints (keep AWS API traffic off the internet):                   ║
  ║     vpce-s3   Gateway   → route entry pl-… in rtb-private-1a/1b, rtb-data  ║
  ║     vpce-sts  Interface → ENI in app-1a + app-1b, sg-vpce allows 443       ║
  ║                                                                            ║
  ║   Reserved for growth:  10.20.96.0/19 , 10.20.128.0/17                     ║
  ╚════════════════════════════════════════════════════════════════════════════╝
```

### 3.3 Relationships that students most often get wrong

| Misconception | Reality |
|---|---|
| "Security groups are attached to instances" | They are attached to **ENIs**. A multi-homed instance can have different SGs per interface. |
| "A subnet is public because I named it public" | A subnet is public **iff** its associated route table has a route to an internet gateway. Nothing else makes it public. |
| "A NAT gateway makes a subnet private" | A NAT gateway must itself live in a **public** subnet. It makes *other* subnets' outbound traffic possible. |
| "One NAT gateway is enough" | It is AZ-scoped. If AZ-a dies, private subnets routed through `nat-1a` lose egress. One per AZ is the resilient pattern (and avoids cross-AZ data charges). |
| "Route tables belong to subnets" | Route tables belong to the **VPC**; subnets *associate* with one. An unassociated subnet silently uses the **main** route table — the most common cause of "why is my instance not reachable". |
| "NACLs and SGs are two ways to do the same thing" | SGs are stateful, allow-only, ENI-scoped. NACLs are stateless, allow+deny, subnet-scoped, numbered. Because NACLs are stateless you must open the ephemeral range for return traffic. |
| "The VPC router is something I configure" | It is implicit. You never see it as an object; you only edit its routing tables. It occupies base+1 of every subnet. |
| "Deleting the `local` route isolates a subnet" | You cannot delete or modify the `local` route. Intra-VPC reachability is always routable; you restrict it with SGs and NACLs. |
| "An internet gateway is a NAT device" | For instances with a **public IPv4 address**, the IGW performs 1:1 NAT between the private and public address. It does **not** provide many-to-one NAT; that is the NAT gateway's job. |
| "Public IP == Elastic IP" | An auto-assigned public IP changes on stop/start and is released on termination. An EIP is an account-owned, static address you must release explicitly, and is billed when not associated. |

### 3.4 Recap of §3

A VPC is a container for an implicit router plus four kinds of configuration object: address containers (subnets), routing policy (route tables), stateless subnet firewalls (NACLs), and stateful interface firewalls (security groups) — plus edge devices (IGW, NAT, endpoints, peering, VGW) that routes can point at. The three defaults created with every VPC (main route table, default NACL, default SG) are permissive-by-design conveniences, and production designs replace all three.

---
## 4. Component-by-Component Deep Dive

Each component below carries a **Floci tier badge**. Confirm every badge against your own `out/support-matrix.tsv` — do not take these on trust, that is the whole method of this course.

### 4.1 The VPC object

**Floci tier: ✅ structure / ⚠️ behaviour** — `CreateVpc`, `DescribeVpcs`, `DeleteVpc`, `ModifyVpcAttribute`, `DescribeVpcAttribute` are implemented.

**Purpose.** The VPC is the isolation boundary and the address-space container. It owns the implicit router, and every subnet, route table, NACL, security group and gateway attachment is scoped to exactly one VPC.

**Configuration.**

| Field | Values | Notes |
|---|---|---|
| `CidrBlock` | `/16` … `/28`, RFC 1918 recommended | Cannot be changed after creation. **Choose carefully.** |
| `InstanceTenancy` | `default` \| `dedicated` | `dedicated` forces every instance onto single-tenant hardware and cannot be relaxed per-instance downward |
| `enableDnsSupport` | `true` (default) | Enables the Amazon-provided DNS resolver at VPC base+2 |
| `enableDnsHostnames` | `false` (default for non-default VPCs) | Instances with public IPs get public DNS names |
| `Ipv6CidrBlock` | Amazon-provided `/56` or BYOIP | Optional; dual-stack |
| `Tags` | key/value | Set `Name` at creation via `--tag-specifications` |

**Lifecycle.**

```
CreateVpc ──► state: pending ──► available
              │
              └─ AWS simultaneously creates, atomically:
                   main route table  (local route only)
                   default NACL      (allow all ingress + egress)
                   default SG        (self-ref ingress, allow-all egress)
                 These three CANNOT be deleted while the VPC exists.

DeleteVpc  requires that you have first deleted/detached:
             subnets, custom route tables, custom NACLs, custom SGs,
             IGW (detach), NAT gateways, endpoints, peering connections, ENIs
           otherwise: DependencyViolation
```

**Relationships.** VPC → subnets (1:n), → route tables (1:n), → NACLs (1:n), → security groups (1:n), → IGW (1:1 attachment), → endpoints (1:n), → peering connections (1:n), → DHCP option set (n:1).

**Security.** The VPC boundary is absolute by default: two VPCs cannot exchange a single packet until you create a peering connection, transit gateway attachment or PrivateLink endpoint **and** add routes. Guard the VPC itself with IAM: `ec2:CreateVpc`, `ec2:DeleteVpc` and `ec2:ModifyVpcAttribute` should be restricted to the platform team, never granted to application developers.

**Limitations / quotas (AWS defaults).**

| Quota | Default | Adjustable |
|---|---|---|
| VPCs per Region | 5 | Yes |
| IPv4 CIDR blocks per VPC | 5 | Yes (to 50) |
| IPv6 CIDR blocks per VPC | 5 | Yes |
| Internet gateways per Region | 5 | Yes |

**Best practices.**

* Size the primary CIDR for the *whole lifetime* of the environment, then some. Resizing means adding secondary CIDRs, which cannot overlap and complicate routing.
* Never use `172.17.0.0/16` — that is Docker's default bridge network and will break containers on your instances.
* Keep a per-organisation IPAM spreadsheet (or AWS IPAM) so `dev`, `staging` and `prod` never overlap; you will eventually want to peer or transit them.
* Turn `enableDnsHostnames` on deliberately, not reflexively — it is required for RDS endpoints and for private hosted zones to resolve as expected.
* Delete the **default VPC** in every account you control (see §4.23).

**Naming convention.** `dnb-<env>-vpc` → `dnb-dev-vpc`.

**Common mistakes.** Choosing `10.0.0.0/16` for everything, then discovering three environments cannot be peered. Choosing a `/24` VPC "because we only need 50 servers", then finding an EKS cluster needs thousands of pod IPs.

---

### 4.2 CIDR blocks and IPv4 address planning

**Floci tier: ✅ structure** — `AssociateVpcCidrBlock` / `DisassociateVpcCidrBlock` implemented. ❌ **IPAM** (`ec2:CreateIpam*`) is not in the published list.

**The rules AWS enforces.**

| Rule | Detail |
|---|---|
| VPC IPv4 prefix length | between `/16` (65 536 addresses) and `/28` (16 addresses) |
| Subnet IPv4 prefix length | between `/16` and `/28`, and must be **inside** a VPC CIDR |
| Reserved per subnet | **5 addresses**, always |
| Secondary CIDRs | must not overlap the primary or each other; restricted ranges apply (e.g. you may add from `100.64.0.0/10`) |
| IPv6 | VPC gets a fixed `/56`; every subnet must be a `/64` |
| Immutability | you can **add** CIDRs; you cannot resize or remove the primary |

**The five reserved addresses.** For `10.20.32.0/20` (range `10.20.32.0` – `10.20.47.255`):

| Address | Reserved for |
|---|---|
| `10.20.32.0` | Network address |
| `10.20.32.1` | VPC router (your default gateway) |
| `10.20.32.2` | Amazon-provided DNS resolver (always VPC-base+2; also answers at base+2 of the VPC, i.e. `10.20.0.2`) |
| `10.20.32.3` | Reserved by AWS for future use |
| `10.20.47.255` | Network broadcast address — reserved even though VPC does not support broadcast |

So a `/20` gives `4096 − 5 = 4091` usable addresses, and the smallest permitted subnet, a `/28`, gives `16 − 5 = 11`.

```
Usable(prefix) = 2^(32 − prefix) − 5

  /28 →    11        /24 →   251        /20 →  4 091
  /27 →    27        /23 →   507        /19 →  8 187
  /26 →    59        /22 → 1 019        /18 → 16 379
  /25 →   123        /21 → 2 043        /16 → 65 531
```

**The DNB plan you will build.** Notice that we consume less than half of the `/16` and document the reservation. This is what a real allocation record looks like:

| CIDR | Purpose | AZ | Usable | Status |
|---|---|---|---|---|
| `10.20.0.0/20` | public / edge | us-east-1a | 4 091 | Lab 2 |
| `10.20.16.0/20` | public / edge | us-east-1b | 4 091 | Lab 2 |
| `10.20.32.0/20` | app tier | us-east-1a | 4 091 | Lab 2 |
| `10.20.48.0/20` | app tier | us-east-1b | 4 091 | Lab 2 |
| `10.20.64.0/20` | data tier | us-east-1a | 4 091 | Lab 2 |
| `10.20.80.0/20` | data tier | us-east-1b | 4 091 | Lab 2 |
| `10.20.96.0/20` | *reserved* — third AZ public+app | us-east-1c | — | reserved |
| `10.20.112.0/20` | *reserved* — third AZ data | us-east-1c | — | reserved |
| `10.20.128.0/17` | *reserved* — future expansion / EKS pods | — | — | reserved |
| `100.64.0.0/16` | secondary CIDR — container overflow | both | — | Lab 9 |
| `10.20.200.0/28` | tiny probe subnet (exhaustion demo) | us-east-1a | 11 | Lab 8 |

!!! tip "Plan by AZ-major or tier-major, and be consistent"
    We use **tier-major** blocks (`0.0/20`, `16.0/20` = public; `32.0/20`, `48.0/20` = app; …). The alternative, **AZ-major** (`10.20.0.0/18` = everything in AZ-a), makes it easy to summarise a whole AZ in one route or firewall rule, which matters for on-premises firewalls. Either is defensible. Mixing them is not.

**Verification helper** — add to `~/vpc-lab/bin/ids.sh` or run standalone:

```bash
cidrinfo() {  # cidrinfo 10.20.32.0/20
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1])
print(f"network      {n.network_address}")
print(f"broadcast    {n.broadcast_address}")
print(f"total        {n.num_addresses}")
print(f"aws usable   {n.num_addresses - 5}")
print(f"reserved     {n.network_address}, {n.network_address+1}, "
      f"{n.network_address+2}, {n.network_address+3}, {n.broadcast_address}")
print(f"first usable {n.network_address+4}")
print(f"last usable  {n.broadcast_address-1}")
PY
}
cidrinfo 10.20.32.0/20
```

Expected output:

```
network      10.20.32.0
broadcast    10.20.47.255
total        4096
aws usable   4091
reserved     10.20.32.0, 10.20.32.1, 10.20.32.2, 10.20.32.3, 10.20.47.255
first usable 10.20.32.4
last usable  10.20.47.254
```

**Best practices.** Reserve at least half the VPC on day one. Align subnet boundaries to nibble boundaries (`/20`, `/24`) so humans can read them. Record every allocation in version control. For containers, assume you will need an order of magnitude more IPs than you think.

---

### 4.3 Subnets

**Floci tier: ✅ structure** — `CreateSubnet`, `DescribeSubnets`, `DeleteSubnet`, `ModifySubnetAttribute`. ❌ `CreateSubnetCidrReservation` not published.

**Purpose.** A subnet is (a) a slice of the VPC address space and (b) a **binding to exactly one availability zone**. That second property is what makes subnets the unit of high-availability design: "run in two AZs" is implemented as "put ENIs in subnets in two different AZs".

**The three kinds of subnet — a definitional table you should memorise.**

| Kind | Route table contains | Outbound internet? | Inbound from internet? |
|---|---|---|---|
| **Public** | `0.0.0.0/0 → igw-…` | Yes, if the ENI has a public IPv4 or EIP | Yes (subject to SG/NACL) |
| **Private** | `0.0.0.0/0 → nat-…` | Yes, source-NATed | No |
| **Isolated** | no default route at all (`local` + endpoint prefix lists only) | No | No |

Our data tier is **isolated**, not merely private — that is the regulatory requirement in §6.

**Configuration.**

| Field | Notes |
|---|---|
| `VpcId`, `CidrBlock`, `AvailabilityZone` | AZ is fixed for life |
| `AvailabilityZoneId` | e.g. `use1-az4`; **AZ *names* are randomised per account**, AZ ids are not. Use ids when coordinating across accounts. |
| `MapPublicIpOnLaunch` | default `false` for subnets you create; `true` for default-VPC subnets |
| `AssignIpv6AddressOnCreation` | dual-stack |
| `EnableDns64`, `PrivateDnsNameOptionsOnLaunch` | advanced; NAT64 / hostname format |

**Lifecycle.** `CreateSubnet` → `pending` → `available`. `DeleteSubnet` fails with `DependencyViolation` while any ENI (including an RDS instance's, a NAT gateway's or an interface endpoint's) still lives in it.

**Relationships.** Subnet → 1 route table (explicit association, else the VPC main table). Subnet → 1 NACL (explicit, else the VPC default NACL). Subnet ← n ENIs. Subnet ← RDS DB subnet groups, ELB subnet mappings, Lambda VPC config, ECS `awsvpc` task placement, interface endpoints.

**Security.** The subnet is the boundary at which NACLs apply, so it is your **blast-radius** control. Put resources with the same trust level and the same internet exposure in the same subnet; never mix a public load balancer and a database in one subnet, even if security groups would technically protect the database.

**Limitations / quotas.**

| Quota | Default |
|---|---|
| Subnets per VPC | 200 |
| Prefix length | `/16` … `/28` |
| Reserved addresses per subnet | 5 |

**Best practices.**

* Two AZs minimum, three for production. ALBs require subnets in ≥2 AZs; RDS Multi-AZ requires a DB subnet group spanning ≥2 AZs.
* One subnet per tier per AZ. Do not create a "misc" subnet.
* Tag `Tier` and `Name` at creation; automation and the reachability matrix depend on it.
* Keep public subnets small — they should hold only load balancers and NAT gateways.
* Symmetric sizing across AZs makes capacity planning and IP maths trivial.

**Naming convention.** `dnb-<env>-subnet-<tier>-<az-suffix>` → `dnb-dev-subnet-app-1a`.

**Common mistakes.** Creating all subnets in one AZ and discovering it at ALB-creation time. Forgetting `--availability-zone`, letting AWS choose, then having two "different-AZ" subnets in the same AZ.

---

### 4.4 The implicit router and route tables

**Floci tier: ✅ structure / ❌ enforcement** — `CreateRouteTable`, `DeleteRouteTable`, `AssociateRouteTable`, `DisassociateRouteTable`, `CreateRoute`, `DeleteRoute`, `DescribeRouteTables` are implemented; forwarding is not.

**Purpose.** Every VPC has an implicit router that you never see as an API object. Route tables are the *policy* you hand that router: "for destination X, send the packet to target Y." Because the router is per-VPC but tables are per-subnet-association, **routing in AWS is decided by the source subnet**, not by the instance.

**The `local` route.** Every table always contains `<vpc-cidr> → local`, and it cannot be deleted or overridden. Consequence: **all subnets in a VPC can always route to each other.** Intra-VPC isolation is achieved with security groups and NACLs, never by removing routes. (If you add a secondary CIDR, a second `local` route appears for it.)

**Route targets.**

| Target | Attribute in the API | Used for |
|---|---|---|
| `local` | — | intra-VPC (implicit) |
| Internet gateway | `GatewayId=igw-…` | public subnet default route |
| NAT gateway | `NatGatewayId=nat-…` | private subnet default route |
| Egress-only IGW | `EgressOnlyInternetGatewayId=eigw-…` | IPv6 outbound-only |
| Virtual private gateway | `GatewayId=vgw-…` | VPN / Direct Connect |
| Transit gateway | `TransitGatewayId=tgw-…` | hub-and-spoke |
| Peering connection | `VpcPeeringConnectionId=pcx-…` | VPC-to-VPC |
| Network interface | `NetworkInterfaceId=eni-…` | NAT instance, firewall appliance |
| Gateway endpoint | `GatewayId=vpce-…` with a **prefix list** destination | private S3 / DynamoDB |
| Gateway Load Balancer endpoint | `VpcEndpointId=vpce-…` | inline inspection |

**Evaluation algorithm — longest prefix match.** Given routes `0.0.0.0/0 → nat-1a`, `10.20.0.0/16 → local`, `10.20.64.0/20 → eni-fw`, a packet to `10.20.64.10` matches all three and takes the **`/20`** because it is the most specific. Static routes beat propagated routes at equal specificity; among static routes to the same prefix, AWS prefers, in order: `local`, then more specific, then by target type (IGW/VGW/DX/TGW/peering, in a documented order).

```
  destination 10.20.64.10
  ├── 0.0.0.0/0       (prefix 0)  ── candidate
  ├── 10.20.0.0/16    (prefix 16) ── candidate
  └── 10.20.64.0/20   (prefix 20) ── WINNER (longest)
```

**Main vs custom tables — the single most consequential subtlety.**

```
  Subnet created ─┬─► you associate a custom table  ──► that table applies
                  │
                  └─► you do nothing                ──► the VPC MAIN table applies
                                                          (implicit association)
```

If the main table happens to contain `0.0.0.0/0 → igw`, every subnet you forget to associate becomes **public**. Therefore: **keep the main route table minimal (`local` only) and never add a default route to it.** Associate every subnet explicitly.

**Lifecycle.**

```
CreateRouteTable ──► available
  AssociateRouteTable(subnet)      ──► rtbassoc-… (explicit)
  ReplaceRouteTableAssociation     ──► move a subnet between tables atomically
  DisassociateRouteTable           ──► subnet silently falls back to MAIN
  CreateRoute / ReplaceRoute / DeleteRoute
DeleteRouteTable  ──► fails with DependencyViolation while associations exist;
                      the main table can never be deleted
```

**Blackhole routes.** If a route's target is deleted (a NAT gateway, peering connection or ENI), the route remains in the table with `State: blackhole` and silently drops matching traffic. `reach.py` treats blackholes as DENY — check for them first when diagnosing "it worked yesterday".

```bash
aws ec2 describe-route-tables \
  --query 'RouteTables[].Routes[?State==`blackhole`].[DestinationCidrBlock,State]' \
  --output text
```

**Security.** Route tables are the *most dangerous* VPC object, because adding one route to a data-tier table can expose a database to the internet with no other change. Restrict `ec2:CreateRoute` / `ec2:ReplaceRoute` tightly, alarm on `CreateRoute` in CloudTrail, and consider an SCP that denies `ec2:CreateRoute` with `GatewayId` starting `igw-` on production data-tier tables.

**Limitations / quotas.** 200 route tables per VPC; 500 non-propagated routes per table (raised from 50 in 2025); 100 propagated routes.

**Best practices.**

* One private route table **per AZ** — otherwise you cannot point AZ-a at `nat-1a` and AZ-b at `nat-1b`, and you pay cross-AZ data charges plus lose AZ independence.
* A separate isolated table for the data tier with no default route.
* Name every table for the subnets it serves.
* Review `blackhole` routes as part of routine ops.

**Naming convention.** `dnb-dev-rtb-public`, `dnb-dev-rtb-private-1a`, `dnb-dev-rtb-data`.

---

### 4.5 Internet gateway

**Floci tier: ✅ structure** — `CreateInternetGateway`, `AttachInternetGateway`, `DetachInternetGateway`, `DeleteInternetGateway`, `DescribeInternetGateways`.

**Purpose.** Two jobs, and students conflate them:

1. It is the **routing target** that makes a subnet public.
2. It performs **1:1 network address translation** between an instance's private IPv4 address and its public IPv4 address / Elastic IP. This is why an instance never sees its own public IP in `ip addr` — the translation happens at the gateway.

For IPv6 the IGW is a pure router; no translation occurs, because IPv6 addresses on ENIs are globally routable.

**Configuration.** Almost none: create it, tag it, attach it to one VPC. It is horizontally scaled and highly available by AWS; there is no bandwidth setting and no charge.

**Lifecycle.**

```
CreateInternetGateway ──► detached
  AttachInternetGateway(vpc)  ──► available   (1 IGW per VPC, 1 VPC per IGW)
  DetachInternetGateway       ──► fails while any ENI in the VPC has a public
                                  IPv4 address or EIP associated
DeleteInternetGateway         ──► must be detached first
```

**Relationships.** IGW ← route table entries. IGW ↔ VPC (1:1). An EIP association depends on the IGW existing.

**The four conditions for internet reachability.** All four must hold; students usually satisfy two and are puzzled.

```
  1. An internet gateway attached to the VPC
  2. A route  0.0.0.0/0 → igw-…  in the route table associated with
     the instance's subnet
  3. A public IPv4 address or EIP on the instance's ENI
  4. Security group egress + NACL egress/ingress permitting the flow
     (and for inbound, SG ingress too)
```

**Security.** The presence of an IGW route is the definition of "exposed". Audit for it:

```bash
aws ec2 describe-route-tables \
  --query 'RouteTables[?Routes[?GatewayId!=null && starts_with(GatewayId, `igw-`)]].{Table:RouteTableId,Subnets:Associations[].SubnetId}' \
  --output json
```

**Limitations.** One IGW per VPC; 5 per Region by default. No throttling, no logging of its own (use flow logs).

**Best practices.** Attach exactly one; never attach an IGW to a VPC that has no public subnets; treat "which route tables reference the IGW" as a config-drift check.

**Naming convention.** `dnb-dev-igw`.

---

### 4.6 NAT gateway (and NAT instances, conceptually)

**Floci tier: ✅ structure / ❌ translation** — `CreateNatGateway`, `DescribeNatGateways`, `DeleteNatGateway`. No packets are translated locally.

**Purpose.** Many-to-one source NAT so that instances **without** public addresses can initiate outbound IPv4 connections (OS patches, package registries, external APIs) while remaining unreachable from the internet.

**The asymmetry that defines it:** outbound connections succeed; inbound connections are impossible because there is no port-forwarding configuration. That is precisely the security property you want for an application tier.

**Configuration.**

| Field | Values | Notes |
|---|---|---|
| `SubnetId` | must be a **public** subnet | the NAT gateway's own ENI needs an IGW route |
| `AllocationId` | an Elastic IP | required for `connectivity-type=public` |
| `ConnectivityType` | `public` (default) \| `private` | `private` gives no EIP; used to reach on-premises via TGW/VGW while hiding source IPs |
| `Tags` | — | tag it or you will not know which AZ it serves |

**Lifecycle.**

```
CreateNatGateway ──► pending ──► available          (takes ~1-2 min in real AWS)
                        │
                        └──► failed  (e.g. subnet has no IGW route, EIP in use)
DeleteNatGateway ──► deleting ──► deleted
   the EIP is NOT released; you must ReleaseAddress separately
   any route pointing at it becomes State: blackhole
```

**Relationships.** NAT GW → 1 subnet (AZ-scoped) → 1 EIP → referenced by `0.0.0.0/0` routes in *other* subnets' tables.

```
   ┌──────────────── AZ us-east-1a ─────────────────┐
   │  PUBLIC subnet   rtb-public: 0.0.0.0/0 → igw   │
   │     ┌─────────────┐                            │
   │     │  nat-1a     │◄── EIP 52.x.x.x            │
   │     └──────▲──────┘                            │
   │            │                                   │
   │  PRIVATE subnet  rtb-private-1a:               │
   │            └──── 0.0.0.0/0 → nat-1a            │
   └────────────────────────────────────────────────┘
   Cross-AZ variant (BAD): private-1b → nat-1a
     • pays cross-AZ data transfer on every byte
     • loses egress entirely if AZ-a fails
```

**Security.** A NAT gateway has **no security group** — you cannot filter at the NAT. Egress filtering must happen at the instance's own security group, at the NACL, or with a proxy / AWS Network Firewall. This surprises people who expect to control outbound destinations at the NAT.

**Limitations / quotas / cost.**

| Property | Value |
|---|---|
| NAT gateways per AZ | 5 (default) |
| Bandwidth | scales to 100 Gbps |
| Simultaneous connections to a single destination endpoint | 55 000 per unique destination tuple; beyond that, `ErrorPortAllocation` |
| Supports IPv6 | no (use an egress-only IGW) |
| Cannot be used as a route target for | traffic originating in the same subnet it lives in (that traffic would loop) |
| Cost | hourly charge + per-GB processing (roughly USD 32–33/month/gateway in `us-east-1` before data) |

!!! danger "This is the component that generates surprise bills"
    Three NAT gateways left running in a sandbox account for a month is around USD 100, plus data processing on every byte your instances pull from the internet — including from S3, unless you add a gateway endpoint. **A gateway endpoint for S3 is free and removes S3 traffic from the NAT entirely.** That single change is the most common AWS cost optimisation in the wild.

**NAT instance (conceptual, legacy).** Before NAT gateways, you ran a Linux instance with `net.ipv4.ip_forward=1`, an iptables MASQUERADE rule, **source/destination checking disabled** (`ec2:ModifyInstanceAttribute --no-source-dest-check`), and a route `0.0.0.0/0 → eni-…`. Differences worth knowing for the exam:

| | NAT gateway | NAT instance |
|---|---|---|
| Managed | Yes | No, you patch it |
| HA | Within its AZ, automatically | You build it (ASG + route swap) |
| Security group | None | Yes — so you *can* filter egress |
| Port forwarding / bastion use | No | Yes |
| Cost | Hourly + per GB | EC2 instance cost |

**Best practices.** One NAT gateway per AZ, each referenced only by that AZ's private route table. Add gateway endpoints for S3 and DynamoDB *before* worrying about NAT bandwidth. Alarm on NAT `BytesOutToDestination` for cost, and on `ErrorPortAllocation` for exhaustion.

**Naming convention.** `dnb-dev-nat-1a`, `dnb-dev-nat-1b`.

---

### 4.7 Egress-only internet gateway (IPv6)

**Floci tier: ❌ likely not supported** — `CreateEgressOnlyInternetGateway` is absent from the published operation list. Probe it; if unsupported, model it as JSON only (Lab 9).

**Purpose.** The IPv6 equivalent of a NAT gateway's *security* property, without NAT. Because IPv6 addresses are globally routable there is nothing to translate; the EIGW is simply a **stateful** gateway that permits outbound-initiated IPv6 flows and blocks inbound-initiated ones.

**Configuration.** `CreateEgressOnlyInternetGateway --vpc-id`; then a route `::/0 → eigw-…` in the private subnets' tables. No EIP, no charge, no AZ affinity, horizontally scaled.

**Contrast to memorise:**

| Need | IPv4 | IPv6 |
|---|---|---|
| Inbound + outbound | IGW + public IP | IGW |
| Outbound only | NAT gateway (in a public subnet, EIP, hourly + GB) | **Egress-only IGW** (free, no subnet) |

**Common mistake.** Adding `::/0 → igw-…` to a private subnet "to give it IPv6 egress", which also makes every instance in it globally reachable, since there is no NAT hiding it.

---

### 4.8 Public IPv4 addresses and Elastic IPs

**Floci tier: ✅ structure** — `AllocateAddress`, `AssociateAddress`, `DisassociateAddress`, `ReleaseAddress`, `DescribeAddresses`, `DescribeAddressesAttribute`.

**Three distinct things students merge into one:**

| | Private IPv4 | Auto-assigned public IPv4 | Elastic IP |
|---|---|---|---|
| Source | subnet CIDR | AWS pool | AWS pool, allocated to *your account* |
| Persistence | for the life of the ENI | lost on stop/start and on termination | until you `ReleaseAddress` |
| Visible inside the OS | yes | **no** (IGW does the 1:1 NAT) | **no** |
| Controlled by | `--private-ip-address` | subnet `MapPublicIpOnLaunch` or `--associate-public-ip-address` | explicit association |
| Charged | no | yes, per hour (all public IPv4 has been charged since Feb 2024) | yes, per hour — **including while unassociated** |
| Remappable | no | no | yes — the basis of blue/green failover |

**Configuration.**

```
AllocateAddress --domain vpc              ──► eipalloc-…  + public IP
AssociateAddress --allocation-id eipalloc-… --instance-id i-…
AssociateAddress --allocation-id eipalloc-… --network-interface-id eni-… \
                 [--private-ip-address 10.20.0.10]   # for multi-IP ENIs
DisassociateAddress --association-id eipassoc-…
ReleaseAddress --allocation-id eipalloc-…
```

**Lifecycle trap.** `DeleteNatGateway` does **not** release the NAT's EIP, and terminating an instance does not release an associated EIP. Orphaned EIPs are billed indefinitely. Every cleanup script in this course ends with an EIP sweep.

**Security.** An EIP is a stable, scannable, internet-facing identity. Attach EIPs only to things that genuinely need a fixed public address (NAT gateways, occasionally a bastion). For application front-ends, use an ALB/NLB DNS name instead so the addresses can change.

**Limitations / quotas.** 5 EIPs per Region by default (adjustable). `AddressLimitExceeded` when exceeded. EIPs are region-scoped and cannot move between regions.

**Best practices.** Tag every EIP with its purpose and owner. Alarm on unassociated EIPs. Prefer `--domain vpc`. In production, request the quota increase deliberately rather than reactively.

**Naming convention.** `dnb-dev-eip-nat-1a`.

---

### 4.9 Elastic network interfaces (ENIs)

**Floci tier: ⚠️ partially** — network interfaces appear in the published coverage; the exact operation set varies by build. Probe `create-network-interface`, `attach-network-interface`, `assign-private-ip-addresses`.

**Purpose.** The ENI is the *real* atom of VPC networking. It is a virtual network card with: a MAC address, one primary and optional secondary private IPv4 addresses, optional public IPv4 / EIP, optional IPv6 addresses, a source/destination check flag, and **1–5 security groups**. Instances, RDS databases, ELB nodes, interface endpoints, NAT gateways, VPC-attached Lambdas and ECS `awsvpc` tasks are *all* just things that own ENIs.

Understanding this collapses many mysteries: *"why can't I delete my subnet?"* — because an RDS instance's ENI is in it. *"why does my security group say it is in use?"* — because an ENI references it.

**Configuration.**

| Field | Notes |
|---|---|
| `SubnetId` | fixed for life; an ENI cannot move between subnets or AZs |
| `Groups` | 1–5 security groups (quota, adjustable to 16) |
| `PrivateIpAddresses` | 1 primary + n secondary, count capped by instance type |
| `SourceDestCheck` | `true` by default; set `false` for NAT instances, routers, some CNIs |
| `InterfaceType` | `interface`, `efa`, `trunk`, `branch` |
| `Description`, `Tags` | AWS-managed ENIs are self-describing — read the description to find the owner |

**Lifecycle.**

```
CreateNetworkInterface ──► available
  AttachNetworkInterface(instance, deviceIndex) ──► in-use
     deviceIndex 0 = primary/eth0: created and destroyed WITH the instance
     deviceIndex >0 = secondary:   survives instance termination unless
                                   DeleteOnTermination is set
  DetachNetworkInterface ──► available
DeleteNetworkInterface ──► only when available
```

**Relationships.** ENI → 1 subnet → 1 AZ; ENI → 1–5 SGs; ENI ← 1 instance/service; ENI ↔ EIP.

**Security.** Because SGs bind to ENIs, a dual-homed instance can genuinely straddle two trust zones — powerful and dangerous. Prefer separate instances over dual-homing unless you are building an appliance.

**Best practices.** Use secondary ENIs for stable MAC/IP licensing needs and for management-plane separation. Always read `Description` before deleting an ENI you did not create — deleting a load balancer's or RDS's ENI is not something AWS will let you do, but deleting a stale Lambda ENI is a common cleanup step.

**Diagnostic recipe.** "Which resources block my subnet deletion?"

```bash
aws ec2 describe-network-interfaces \
  --filters Name=subnet-id,Values="$SUBNET_APP_1A" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Desc:Description,Status:Status,Type:InterfaceType,Owner:RequesterId}' \
  --output table
```

---

### 4.10 Security groups

**Floci tier: ✅ structure / ❌ enforcement** — the full create/authorize/revoke/describe/modify set is implemented; packet filtering is not.

**Purpose.** A stateful, allow-only, ENI-scoped virtual firewall. This is your primary and most precise network control in AWS.

**The five properties that define behaviour** (memorise these; SAA-C03 tests them repeatedly):

1. **Allow-only.** There is no deny rule. Anything not explicitly allowed is denied.
2. **Stateful.** If a request is allowed out, the response is automatically allowed back in, regardless of inbound rules — and vice versa. You never write ephemeral-port rules for security groups.
3. **Attached to ENIs**, not subnets or instances. Up to 5 per ENI (adjustable to 16); all rules across all attached groups are **unioned**.
4. **Evaluated as a whole.** Rule order is irrelevant; there is no "first match".
5. **Can reference other security groups**, including themselves, and referencing works across peered VPCs in the same region.

**Defaults.**

| Group | Inbound | Outbound |
|---|---|---|
| **Default SG** (created with the VPC, undeletable) | allow all traffic **from itself** (self-referencing) | allow all |
| A group **you** create | *empty* — nothing allowed in | allow all `0.0.0.0/0` |

!!! warning "The single most-tested nuance"
    A **new** security group starts with **no inbound rules and an allow-all outbound rule**. The **default** security group starts with a **self-referencing inbound rule**. These are not the same thing, and exam questions exploit the difference.

**Configuration.**

```
CreateSecurityGroup --group-name --description (mandatory!) --vpc-id
AuthorizeSecurityGroupIngress --group-id --protocol tcp --port 443 --cidr 1.2.3.4/32
AuthorizeSecurityGroupIngress --group-id sg-app \
    --ip-permissions 'IpProtocol=tcp,FromPort=8080,ToPort=8080,
        UserIdGroupPairs=[{GroupId=sg-web,Description=alb to app}]'
RevokeSecurityGroupEgress --group-id --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
```

**Security-group referencing — why it is the correct default.**

```
   BAD:  sg-db  inbound 5432 from 10.20.32.0/20, 10.20.48.0/20
         • breaks when you add an AZ or a secondary CIDR
         • allows ANY host in those subnets, including a compromised
           sidecar or a future unrelated workload

   GOOD: sg-db  inbound 5432 from sg-app
         • identity-based, not location-based
         • auto-scales: new app instances inherit access by getting sg-app
         • auto-shrinks: removing sg-app from an instance revokes access
         • survives re-addressing and new subnets
```

**Lifecycle.** `CreateSecurityGroup` → immediately usable. `DeleteSecurityGroup` fails with `DependencyViolation` while any ENI references it **or** while another security group's rule references it. The default SG can never be deleted.

**Limitations / quotas.**

| Quota | Default |
|---|---|
| Security groups per Region | 2 500 |
| Inbound rules per SG | 60 |
| Outbound rules per SG | 60 |
| SGs per ENI | 5 (adjustable to 16) |
| Rules per ENI (SGs × rules) | 1 000 |

A rule that lists one CIDR and one port counts as **one** rule; a rule with 10 CIDRs counts as 10. Use **managed prefix lists** to stay under the limit (§4.20).

**Security best practices.**

* Never `0.0.0.0/0` on 22 (SSH) or 3389 (RDP). Use SSM Session Manager instead — no inbound rule at all.
* Reference security groups, not CIDRs, for intra-VPC traffic.
* Restrict egress deliberately for the data tier. The default allow-all egress is a data-exfiltration path.
* Give every rule a `Description` — a rule without one is un-auditable a year later.
* One security group per role (`sg-web`, `sg-app`, `sg-db`, `sg-vpce`), not one per instance.

**Naming convention.** `dnb-dev-sg-<role>` → `dnb-dev-sg-app`. Note that `GroupName` must be unique per VPC and cannot be changed after creation.

---

### 4.11 Network ACLs

**Floci tier: ✅ structure / ❌ enforcement** — full entry create/replace/delete/associate set is implemented; evaluation is not.

**Purpose.** A **stateless**, numbered, subnet-scoped packet filter that supports both allow **and deny**. It is a coarse, second layer — useful for blanket blocks that must not depend on anyone's security group hygiene.

**The four properties that define behaviour:**

1. **Stateless.** Return traffic is *not* automatically permitted. You must explicitly allow the **ephemeral port range** in the reverse direction.
2. **Numbered, first-match-wins.** Rules are evaluated in ascending rule number; the first match decides and evaluation stops. There is an unremovable final rule `*` that denies everything.
3. **Subnet-scoped.** Every subnet is associated with exactly one NACL — the VPC default if you do not choose.
4. **Supports DENY.** This is the only place in VPC where you can write an explicit deny for a CIDR.

**Defaults.**

| NACL | Ingress | Egress |
|---|---|---|
| **Default NACL** (created with the VPC) | rule 100 ALLOW all, then `*` DENY | rule 100 ALLOW all, then `*` DENY |
| A NACL **you** create | only `*` DENY — **blocks everything** | only `*` DENY — **blocks everything** |

!!! danger "Creating a NACL and associating it will black-hole your subnet"
    A brand-new NACL denies all traffic in both directions. Add your rules **before** you associate it, or you will lock yourself out. This is Debugging Challenge 3 in §12.

**The ephemeral port problem, drawn.**

```
  Client 203.0.113.9:51000  ──── TCP SYN → 10.20.0.10:443 ────►  Server
       │                                                            │
       │  NACL ingress on server's subnet must allow TCP 443        │
       │                                                            │
       ◄──── TCP SYN/ACK from 10.20.0.10:443 → 203.0.113.9:51000 ───┘
              NACL EGRESS on server's subnet must allow
              TCP 1024-65535 to 203.0.113.9  ◄── the rule everyone forgets

  Security group equivalent: NOTHING. Stateful, so the response is free.
```

Ephemeral ranges you should know: Linux `32768–60999`; Windows Server 2008+ `49152–65535`; NLB and NAT gateway `1024–65535`; Lambda `1024–65535`. AWS documentation recommends allowing **`1024–65535`** to cover all clients.

**Configuration.**

```
CreateNetworkAcl --vpc-id
CreateNetworkAclEntry --network-acl-id --ingress --rule-number 100 \
    --protocol tcp --port-range From=443,To=443 \
    --cidr-block 0.0.0.0/0 --rule-action allow
ReplaceNetworkAclEntry   # edit in place, same rule number
DeleteNetworkAclEntry --network-acl-id --rule-number 100 --ingress
ReplaceNetworkAclAssociation --association-id aclassoc-… --network-acl-id acl-…
```

Protocol numbers: `-1` all, `6` tcp, `17` udp, `1` icmp. The CLI accepts names for tcp/udp/icmp.

**Rule numbering convention.** Leave gaps so you can insert later:

| Range | Use |
|---|---|
| `1–99` | emergency explicit denies (block a scanning source) |
| `100–199` | intra-VPC allows |
| `200–299` | ephemeral / return traffic |
| `300–399` | specific external allows |
| `32766` | catch-all deny you write explicitly, so it appears in audits |
| `*` | implicit final deny (always present, always last) |

**Lifecycle.** `CreateNetworkAcl` → `available`. Associations are *replaced*, never removed: `ReplaceNetworkAclAssociation` swaps a subnet from one NACL to another. To "detach" a custom NACL, replace the association back to the default NACL. `DeleteNetworkAcl` fails while associated; the default NACL cannot be deleted.

**Limitations / quotas.** 200 NACLs per VPC; **20 rules per NACL** by default (adjustable to 40, but AWS warns of a network-performance impact). That 20-rule budget is small — another reason NACLs are for coarse policy only.

**Security best practices.**

* Use NACLs for policies that must hold regardless of security groups: "no subnet in the data tier may talk to the internet", "block this known-bad /24".
* Always add the ephemeral return rule at the same time as the forward rule.
* Prefer allow-lists ending in an explicit numbered deny, so intent is visible.
* Do not attempt fine-grained per-application policy in NACLs; you will exhaust the rule budget and create an unmaintainable artefact.

**Naming convention.** `dnb-dev-acl-<tier>` → `dnb-dev-acl-data`.

---

### 4.12 Security groups vs network ACLs — the comparison table to memorise

| Dimension | Security group | Network ACL |
|---|---|---|
| Scope | ENI (interface) | Subnet |
| Statefulness | **Stateful** | **Stateless** |
| Rule types | ALLOW only | ALLOW and DENY |
| Evaluation | All rules unioned; order irrelevant | Ascending rule number; **first match wins** |
| Default (object you create) | no inbound, all outbound | deny all in and out |
| Default (created with VPC) | self-ref inbound, all outbound | allow all in and out |
| Return traffic | automatic | must be explicitly allowed (ephemeral ports) |
| Can reference other SGs | **yes** | no — CIDR only |
| Applies to traffic between two ENIs in the same subnet | **yes** | **no** — NACLs only see traffic crossing the subnet boundary |
| Quota | 60 in + 60 out per group, 5 groups per ENI | 20 rules per direction |
| Typical use | precise application-level policy | coarse blast-radius policy, IP blocklists |
| Logging | none directly (use flow logs) | none directly (use flow logs) |

!!! tip "The exam heuristic"
    If a question involves **"block a specific IP address"** → NACL (SGs cannot deny).
    If it involves **"allow the app tier to reach the database without hard-coding IPs"** → SG referencing.
    If a connection **half-works or hangs** → suspect a stateless NACL missing the ephemeral return rule.
    If traffic **between two instances in the same subnet** is being filtered → it must be a security group; NACLs are not in that path.

---

### 4.13 VPC endpoints (AWS PrivateLink)

**Floci tier: ⚠️ partially** — `CreateVpcEndpoint`, `DescribeVpcEndpoints`, `DeleteVpcEndpoints`, `DescribeVpcEndpointServices` are implemented, so you can create and inspect endpoints. Whether traffic to `s3.amazonaws.com` from an emulated instance actually traverses them is not testable locally. ❌ endpoint *services* you publish (`CreateVpcEndpointServiceConfiguration`) are likely unsupported.

**Purpose.** Reach AWS services (or a partner's / your own service) **without traversing the internet** — no IGW, no NAT, no public IP. In regulated environments this is usually mandatory, and it is also a major cost saving because it removes NAT data-processing charges.

**Three types.**

| Type | Mechanism | Services | Charged | DNS |
|---|---|---|---|---|
| **Gateway endpoint** | A **route table entry** whose destination is a *prefix list* and whose target is the `vpce-…` | **S3 and DynamoDB only** | Free | Uses the normal public DNS name; routing does the work |
| **Interface endpoint** | An **ENI with a private IP** in your subnet(s), with security groups | ~most AWS services, partner services, your own NLB-backed services | Hourly per ENI + per GB | Optional **private DNS** overrides the public name to resolve to the ENI |
| **Gateway Load Balancer endpoint** | Route target that hands traffic to a GWLB for inspection | third-party appliances | Hourly + GB | n/a |

```
  GATEWAY ENDPOINT (S3)                   INTERFACE ENDPOINT (STS)
  ─────────────────────                   ────────────────────────
  rtb-data                                subnet-app-1a
   10.20.0.0/16 → local                    ┌───────────────────┐
   pl-63a5400a  → vpce-s3   ◄── prefix     │ eni 10.20.32.87   │◄── vpce ENI
   (no 0.0.0.0/0 at all)        list       │ sg-vpce: 443 from │
                                           │          sg-app   │
  Instance calls s3.amazonaws.com          └───────────────────┘
  → DNS returns a public IP                Private DNS ON:
  → route table matches the prefix list    sts.us-east-1.amazonaws.com
  → traffic exits via the endpoint,        resolves to 10.20.32.87
    never the IGW/NAT                      → traffic goes to the ENI
```

**Configuration.**

```
# Gateway
CreateVpcEndpoint --vpc-id --vpc-endpoint-type Gateway \
    --service-name com.amazonaws.us-east-1.s3 \
    --route-table-ids rtb-… rtb-… \
    [--policy-document file://endpoint-policy.json]

# Interface
CreateVpcEndpoint --vpc-id --vpc-endpoint-type Interface \
    --service-name com.amazonaws.us-east-1.sts \
    --subnet-ids subnet-… subnet-… \
    --security-group-ids sg-vpce \
    --private-dns-enabled
```

**Endpoint policies.** A resource policy on the endpoint that constrains what may pass through it. This is the mechanism for *"from this VPC, you may only reach our own buckets"* — a genuine data-exfiltration control that IAM alone cannot express:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOnlyDnbBuckets",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*",
        "arn:aws:s3:::dnb-audit-logs-dev",
        "arn:aws:s3:::dnb-audit-logs-dev/*"
      ]
    }
  ]
}
```

The mirror-image control lives on the bucket policy and uses the `aws:SourceVpce` / `aws:SourceVpc` condition keys — *"this bucket may only be read from our VPC"*:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnlessFromDnbVpc",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:SourceVpc": "vpc-REPLACE-ME"
        }
      }
    }
  ]
}
```

**Lifecycle.** `CreateVpcEndpoint` → `pending` → `available`. Interface endpoints create one ENI per specified subnet, which then blocks subnet deletion. Gateway endpoints add and remove route table entries automatically as you modify `--route-table-ids`.

**Security.** Interface endpoints have security groups — and a brand-new SG has no inbound rules, so **you must allow TCP 443 from your client security groups or the endpoint silently times out**. This is Debugging Challenge 4.

**Limitations / quotas.**

| Quota | Default |
|---|---|
| Interface + GWLB endpoints per VPC | 50 |
| Gateway endpoints per Region | 20 (up to 255 per VPC) |
| Endpoint policy size | 20 480 characters |
| MTU on an endpoint | 8 500 bytes; PMTUD not supported |

**Best practices.** Add S3 and DynamoDB gateway endpoints to every VPC on day one — free, and they cut NAT costs. Add interface endpoints for the services your workload actually calls (`sts`, `secretsmanager`, `kms`, `logs`, `ssm`, `ssmmessages`, `ec2messages`, `ecr.api`, `ecr.dkr`) — note that SSM Session Manager needs the last three plus `ssm`, and that this is how you get shell access with **no** inbound SSH rule and **no** NAT. Attach a restrictive endpoint policy. Enable private DNS unless you have a specific reason not to.

**Naming convention.** `dnb-dev-vpce-s3`, `dnb-dev-vpce-sts`.

---

### 4.14 VPC peering

**Floci tier: ❌ likely not supported** — absent from the published list. Probe it; if `create-vpc-peering-connection` returns `InvalidAction`, model it as JSON (Lab 11).

**Purpose.** A direct, private, 1:1 route between two VPCs — same or different account, same or different region. Traffic stays on the AWS backbone; no gateway, no bandwidth bottleneck, no single point of failure.

**The three rules that generate almost every exam question.**

1. **CIDRs must not overlap.** Ever. There is no NAT in a peering connection.
2. **Peering is not transitive.** If A↔B and B↔C, A cannot reach C. You need A↔C, or a transit gateway.
3. **Routes are required on both sides**, and security groups must also permit the traffic. Creating and accepting the peering does nothing by itself.

```
      VPC-A 10.20.0.0/16          VPC-B 10.30.0.0/16          VPC-C 10.40.0.0/16
          │                              │                            │
          └────────── pcx-ab ────────────┴────────── pcx-bc ──────────┘

   A → B  ✔  (route 10.30.0.0/16 → pcx-ab  in A;  10.20.0.0/16 → pcx-ab in B)
   B → C  ✔
   A → C  ✘  NOT TRANSITIVE.  Add pcx-ac, or use a Transit Gateway.
```

**Also not supported over peering:** using the peer's internet gateway, its NAT gateway, its VPC endpoints, or (until you enable it) DNS resolution of the peer's private hostnames. Edge-to-edge routing is prohibited.

**Lifecycle.**

```
CreateVpcPeeringConnection ──► initiating-request ──► pending-acceptance
   (request expires after 7 days if not accepted)
AcceptVpcPeeringConnection ──► provisioning ──► active
   then: add routes on BOTH sides; optionally
   ModifyVpcPeeringConnectionOptions --allow-dns-resolution-from-remote-vpc
DeleteVpcPeeringConnection ──► deleted; routes on both sides become BLACKHOLE
```

**Security.** Security groups can reference a peer VPC's security group **in the same region**, which is the clean way to express cross-VPC access. Cross-region peering requires CIDR-based rules.

**Quotas.** 50 active peering connections per VPC (adjustable to 125); 25 outstanding requests.

**Naming convention.** `dnb-dev-pcx-to-shared-services`.

---

### 4.15 Transit gateway (conceptual)

**Floci tier: ❌ not supported.** Discuss and diagram only.

**Purpose.** A regional, managed **hub router**. Instead of `n(n−1)/2` peering connections, every VPC, VPN and Direct Connect gateway attaches once to the TGW, which owns its own route tables and *is* transitive.

```
   Peering mesh (5 VPCs) = 10 connections      Transit gateway = 5 attachments
        A───B                                        A   B   C
        │╲ ╱│                                         ╲  │  ╱
        │ ╳ │                                          ╲ │ ╱
        │╱ ╲│                                        ┌───┴───┐
        C───D ── E …                                 │  TGW  │── VPN → on-prem
                                                     └───┬───┘
                                                       D   E
```

**Key concepts for SAA-C03.** Attachments (VPC, VPN, DX gateway, peering, Connect); TGW **route tables** with association and propagation, which is how you build isolated routing domains (e.g. spokes may reach a shared-services VPC but not each other); appliance mode for stateful inspection with symmetric flows; per-attachment hourly plus per-GB charges; cross-region TGW peering.

**When to choose what:**

| Requirement | Answer |
|---|---|
| Two VPCs, low cost, no transitivity needed | VPC peering |
| Many VPCs, hybrid, central inspection, transitivity | Transit gateway |
| Expose one service to many consumers, overlapping CIDRs are fine, one-way | PrivateLink endpoint service |

---

### 4.16 Hybrid connectivity: VGW, Site-to-Site VPN, Direct Connect (conceptual)

**Floci tier: ❌ not supported.**

| Option | Path | Bandwidth | Latency consistency | Set-up time | Encryption |
|---|---|---|---|---|---|
| Site-to-Site VPN | over the public internet, IPSec | up to ~1.25 Gbps per tunnel | variable | minutes | yes, native |
| Direct Connect | dedicated private circuit via a partner | 50 Mbps – 100 Gbps | consistent | weeks–months | **no** (add MACsec or a VPN over it) |
| DX + VPN backup | both | — | — | — | yes on the backup |

**Virtual private gateway (`vgw-…`)** is the VPC-side attachment point for a VPN or a DX private virtual interface. Routes to on-premises prefixes point at the VGW, or are learned dynamically via BGP when you enable **route propagation** on a route table. A VPN connection provides **two tunnels** to two AWS endpoints for redundancy; a properly configured customer gateway uses both.

**Common exam trap.** "Encrypted, private, consistent latency, and quick to set up" is contradictory — DX is not quick, VPN is not consistent. The usual answer is DX for the primary path with a VPN as backup.

---

### 4.17 DHCP option sets

**Floci tier: ❌ likely not supported** — absent from the published list.

**Purpose.** Controls what the VPC's DHCP server tells instances: `domain-name`, `domain-name-servers`, `ntp-servers`, `netbios-name-servers`, `netbios-node-type`, and `ipv6-address-preferred-lease-time`.

**Default behaviour.** Every VPC is associated with a default option set specifying `domain-name-servers=AmazonProvidedDNS` and a region-appropriate `domain-name` (`ec2.internal` in `us-east-1`, `<region>.compute.internal` elsewhere).

**Key facts.** Option sets are **immutable** — you cannot edit one; you create a new set and re-associate the VPC. Changes propagate to instances on DHCP lease renewal, so a reboot may be needed. A VPC has exactly one option set. Specifying custom `domain-name-servers` replaces the Amazon resolver — which breaks private hosted zones and endpoint private DNS unless your servers forward to `169.254.169.253` or the VPC base+2 address.

**Best practice.** Prefer **Route 53 Resolver rules and inbound/outbound endpoints** over custom DHCP DNS servers for hybrid DNS. That keeps AmazonProvidedDNS in the path so endpoint private DNS and private hosted zones keep working.

---

### 4.18 DNS inside a VPC

**Floci tier: ⚠️ attributes are settable; resolution behaviour is not testable locally.**

Two VPC attributes, and their interaction is a classic exam item:

| `enableDnsSupport` | `enableDnsHostnames` | Result |
|---|---|---|
| `true` | `true` | Amazon resolver works; instances with public IPs get public DNS names; private DNS names resolve |
| `true` | `false` | Resolver works; **no public DNS hostnames** |
| `false` | `false` | No Amazon DNS at all — instances must use their own resolvers; RDS endpoints, private hosted zones and endpoint private DNS all break |
| `false` | `true` | **Invalid** — AWS rejects this combination |

**The resolver.** Reachable at **VPC CIDR base + 2** (`10.20.0.2` for us) and also at the link-local address `169.254.169.253`. It answers for: public DNS, Amazon-internal names, private hosted zones associated with the VPC, interface-endpoint private DNS, and EC2 instance private/public names.

**Route 53 in a VPC context** (full treatment in the Route 53 module):

* **Private hosted zone** — a zone associated with one or more VPCs; requires both DNS attributes `true`.
* **Resolver inbound endpoint** — lets on-premises resolvers query AWS private zones.
* **Resolver outbound endpoint + forwarding rules** — lets VPC instances resolve on-premises zones.
* **Resolver DNS Firewall** — block queries to known-bad domains; a genuine exfiltration control.
* **Resolver query logging** — the DNS analogue of flow logs.

---

### 4.19 VPC Flow Logs

**Floci tier: ❌ likely not supported** — `CreateFlowLogs` is absent from the published list. Probe it; treat as conceptual and build the *query* skills instead (Lab 10).

**Purpose.** Capture metadata (not payloads) about IP traffic to and from ENIs. This is your primary network forensics and troubleshooting tool, and typically an audit requirement.

**Configuration.**

| Field | Values |
|---|---|
| `ResourceType` | `VPC` \| `Subnet` \| `NetworkInterface` (VPC-level covers all current and future ENIs) |
| `TrafficType` | `ACCEPT` \| `REJECT` \| `ALL` |
| Destination | CloudWatch Logs, S3, or Firehose |
| `MaxAggregationInterval` | 60 s or 600 s |
| Custom format | choose from ~30 fields |

**Default format fields, in order:**

```
version account-id interface-id srcaddr dstaddr srcport dstport
protocol packets bytes start end action log-status
```

A recommended custom format for troubleshooting adds the fields that answer *"which rule dropped this?"*:

```
${version} ${vpc-id} ${subnet-id} ${instance-id} ${interface-id}
${srcaddr} ${srcport} ${dstaddr} ${dstport} ${protocol} ${packets} ${bytes}
${action} ${flow-direction} ${traffic-path} ${pkt-src-aws-service} ${pkt-dst-aws-service}
${tcp-flags} ${log-status}
```

**Reading a record.** `action=REJECT` with `tcp-flags=2` (SYN only) and no corresponding ACCEPT means the SYN was dropped — a security group or NACL denied it. `action=ACCEPT` outbound with **no** matching inbound ACCEPT for the return flow is the fingerprint of a **stateless NACL missing its ephemeral rule**. That single diagnostic pattern is why flow logs matter.

**What flow logs do NOT capture:** traffic to the Amazon DNS resolver (base+2), Windows licence activation, instance metadata (`169.254.169.254`), DHCP, the reserved AWS addresses, and traffic between an ENI and a Network Load Balancer's own interfaces.

**A CloudWatch Logs Insights query you should know:**

```
fields @timestamp, srcAddr, dstAddr, dstPort, protocol, action
| filter action = "REJECT" and dstPort = 5432
| stats count(*) as attempts by srcAddr, dstAddr
| sort attempts desc
| limit 20
```

**Best practices.** Enable at the **VPC** level with `TrafficType=ALL` so new ENIs are covered automatically. Send to S3 with Parquet + Hive partitioning for cheap Athena querying at scale; send to CloudWatch Logs when you want metric filters and alarms. Never use flow logs as a security control — they are observation only, and the 60 s aggregation means they are not real-time.

**Cross-module hook.** In the CloudWatch module you will build a metric filter and alarm on `REJECT` spikes; in the S3 module you will point flow logs at `dnb-audit-logs-dev` and query them with Athena.

---

### 4.20 Managed prefix lists

**Floci tier: ⚠️ prefix lists appear in the published coverage** — probe `create-managed-prefix-list` and `describe-managed-prefix-lists` separately from `describe-prefix-lists`.

**Purpose.** A named, versioned set of CIDR blocks you can reference in security group rules and route tables instead of repeating CIDRs. Change the list once; every rule that references it updates.

**Two kinds.**

| Kind | Example | Notes |
|---|---|---|
| **AWS-managed** | `com.amazonaws.us-east-1.s3` (`pl-63a5400a`) | Read-only; used as the destination of a gateway-endpoint route; also `cloudfront.origin-facing`, `ground-station` |
| **Customer-managed** | `dnb-dev-pl-branch-offices` | You own entries and `MaxEntries`, which is fixed at creation and counts against SG rule quotas |

**Rule-count arithmetic that catches people.** A security group rule referencing a prefix list counts as **`MaxEntries`** rules, not as the number of entries currently in it. A prefix list with `MaxEntries=60` referenced once consumes your entire 60-rule inbound budget. Size `MaxEntries` tightly.

**Best practices.** Use a customer-managed prefix list for branch-office ranges, VPN pools, and partner IPs — then a single SG rule covers them all and updating one list updates every environment. Version-control the list contents and use `ModifyManagedPrefixList` with `--current-version` for optimistic locking.

---

### 4.21 Inspection and analysis services (conceptual)

**Floci tier: ❌ none of these are supported.** Know what each is for; the exam asks you to choose between them.

| Service | What it does | Choose it when |
|---|---|---|
| **Reachability Analyzer** | Static configuration analysis: "can ENI A reach ENI B on port 443?" Returns the *blocking component*. No packets sent. | You want to prove a path is open or find which SG/NACL/route blocks it — exactly what `reach.py` imitates |
| **Network Access Analyzer** | Finds unintended network access across your accounts against declared scopes | Compliance: "prove nothing in the data tier has an internet path" |
| **AWS Network Firewall** | Managed stateful IDS/IPS with Suricata rules, inserted via route table changes into a dedicated firewall subnet | You need domain-name filtering, deep packet inspection, or centralised egress control |
| **Gateway Load Balancer** | Transparently inserts third-party appliances into the path, preserving source IP | You must use a vendor's firewall |
| **Traffic Mirroring** | Copies actual packets from an ENI to a monitoring target | Full-packet capture for forensics/IDS |
| **Resolver DNS Firewall** | Blocks DNS queries by domain | DNS-based exfiltration control |
| **VPC IPAM** | Plans, allocates and monitors CIDRs across accounts and regions | You have more than a handful of VPCs |

!!! tip "`reach.py` is your local Reachability Analyzer"
    When you present Lab 10, say exactly that: *"Floci does not implement Reachability Analyzer, so I implemented its evaluation model in 200 lines of Python and validated my topology against it."* That is a stronger demonstration of understanding than clicking the real service.

---

### 4.22 The default VPC

**Floci tier: ✅** — `CreateDefaultVpc` is implemented.

Every AWS account gets, in every region, a default VPC with: CIDR `172.31.0.0/16`, a `/20` default subnet in each AZ with `MapPublicIpOnLaunch=true`, an attached internet gateway, a main route table containing `0.0.0.0/0 → igw`, and `enableDnsHostnames=true`.

**Why this matters.** Every subnet in the default VPC is **public**, and every instance launched without an explicit subnet lands there with a public IP. It exists so that `aws ec2 run-instances --image-id … --instance-type …` works with no networking arguments — convenient for tutorials, wrong for production.

**Best practice.** Delete the default VPC in every account, or at minimum remove the `0.0.0.0/0 → igw` route from its main route table, so that an accidental launch cannot become internet-exposed. `CreateDefaultVpc` recreates it if you need it back.

---

### 4.23 Recap of §4

| Component | Scope | Stateful? | Floci structure | Floci behaviour |
|---|---|---|---|---|
| VPC | Region | — | ✅ | ⚠️ |
| Subnet | AZ | — | ✅ | ⚠️ |
| Route table | VPC (assoc. per subnet) | — | ✅ | ❌ |
| Internet gateway | VPC | — | ✅ | ❌ |
| NAT gateway | AZ / subnet | stateful NAT | ✅ | ❌ |
| Egress-only IGW | VPC | stateful | ❌ | ❌ |
| Elastic IP | Region | — | ✅ | ⚠️ |
| ENI | Subnet | — | ⚠️ | ⚠️ |
| Security group | ENI | **yes** | ✅ | ❌ |
| Network ACL | Subnet | **no** | ✅ | ❌ |
| Gateway endpoint | route tables | — | ⚠️ | ❌ |
| Interface endpoint | subnet (ENI) | — | ⚠️ | ❌ |
| Peering | VPC pair | — | ❌ | ❌ |
| Transit gateway | Region | — | ❌ | ❌ |
| Flow logs | VPC/subnet/ENI | — | ❌ | ❌ |
| DHCP options | VPC | — | ❌ | ❌ |
| Prefix list | Region | — | ⚠️ | ❌ |

Confirm every cell against your own `out/support-matrix.tsv` before submitting.

---
## 5. Hands-on Labs

**How to work through these labs.**

* The labs are **cumulative**. Lab 6 depends on Lab 5's security groups; Lab 10 evaluates everything built in Labs 1–9. Do **not** clean up between labs — cleanup happens once, in §16.
* Start every session with:

  ```bash
  eval "$(floci env)"
  guard
  cd ~/vpc-lab
  . ~/vpc-lab/bin/ids.sh
  loadids
  ```

* Every lab ends with **Break it** and **Fix it**. These are not optional. The AWS-correct verdict is always stated first; your job is then to test whether your Floci build agrees and record any divergence.
* Capture output as you go: `command | tee out/lab03-routes.json`. Your lab report is graded on evidence, not assertion.

### Lab 1 — Create and interrogate the VPC skeleton

**Objective.** Create `dnb-dev-vpc`, set its DNS attributes, and discover the three default objects AWS creates alongside it. Learn why the main route table must stay minimal.

**Prerequisites.** §0 complete; `guard` passes; ledger sourced.

**Architecture after this lab.**

```
  ╔═══════════════════════════════════════════════════╗
  ║ VPC dnb-dev-vpc  10.20.0.0/16   (available)       ║
  ║   enableDnsSupport   = true                       ║
  ║   enableDnsHostnames = true                       ║
  ║                                                   ║
  ║   ┌─ main route table  rtb-…                      ║
  ║   │    10.20.0.0/16 → local          (only)       ║
  ║   ├─ default network ACL  acl-…                   ║
  ║   │    100 ALLOW all in / 100 ALLOW all out       ║
  ║   └─ default security group  sg-…                 ║
  ║        ingress: all from itself                   ║
  ║        egress:  all to 0.0.0.0/0                  ║
  ║                                                   ║
  ║   no subnets, no gateways yet                     ║
  ╚═══════════════════════════════════════════════════╝
```

#### 1.1 Implementation

```bash
VPC_ID=$(aws ec2 create-vpc \
  --cidr-block 10.20.0.0/16 \
  --instance-tenancy default \
  --tag-specifications 'ResourceType=vpc,Tags=[
      {Key=Name,Value=dnb-dev-vpc},
      {Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},
      {Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},
      {Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=network}]' \
  --query 'Vpc.VpcId' --output text)
setid VPC_ID "$VPC_ID"
```

**Parameter explanation**

| Parameter | Meaning | Why this value |
|---|---|---|
| `--cidr-block 10.20.0.0/16` | Primary IPv4 range, immutable | RFC 1918; DNB's `dev` allocation; `/16` leaves room for three AZs plus growth |
| `--instance-tenancy default` | Instances share hardware | `dedicated` would force single-tenant hardware on *every* instance and cannot be relaxed per instance |
| `--tag-specifications 'ResourceType=vpc,Tags=[…]'` | Tags applied **atomically at creation** | A separate `create-tags` call can fail, leaving an untagged resource that your cleanup sweep will miss |
| `--query 'Vpc.VpcId' --output text` | Extract just the id | Feeds the ledger; avoids copy-paste errors |

!!! tip "Always tag at creation, never afterwards"
    `--tag-specifications` is atomic with the create. `create-tags` is a second API call that can fail or be forgotten. Since our cleanup script finds resources **by tag**, an untagged resource is an orphan that costs money.

Now the two DNS attributes. Note that `modify-vpc-attribute` accepts **only one attribute per call** — a genuine API constraint, not a CLI quirk:

```bash
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames
```

| Attribute | Effect when `true` | Needed for |
|---|---|---|
| `enableDnsSupport` | The Amazon resolver at `10.20.0.2` answers queries | RDS endpoints, private hosted zones, endpoint private DNS, any public DNS lookup |
| `enableDnsHostnames` | Instances with public IPs receive public DNS names; instances receive `ip-10-20-32-4.ec2.internal` style private names | Public-facing hosts, and required alongside `enableDnsSupport` for private hosted zones |

!!! note "The CLI's boolean shorthand"
    `--enable-dns-support` is shorthand for `--enable-dns-support Value=true`; the negative form is `--no-enable-dns-support`. If your build rejects the bare flag, use the explicit structure: `--enable-dns-support '{"Value":true}'`.

#### 1.2 Expected output

```bash
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --output json
```

```json
{
  "Vpcs": [
    {
      "OwnerId": "000000000000",
      "InstanceTenancy": "default",
      "CidrBlockAssociationSet": [
        {
          "AssociationId": "vpc-cidr-assoc-0a1b2c3d4e5f6a7b8",
          "CidrBlock": "10.20.0.0/16",
          "CidrBlockState": { "State": "associated" }
        }
      ],
      "IsDefault": false,
      "Tags": [
        { "Key": "Name", "Value": "dnb-dev-vpc" },
        { "Key": "Project", "Value": "CoreBanking" },
        { "Key": "Environment", "Value": "dev" },
        { "Key": "Owner", "Value": "platform-team" },
        { "Key": "CostCenter", "Value": "CC-4400" },
        { "Key": "ManagedBy", "Value": "floci-lab" },
        { "Key": "Tier", "Value": "network" }
      ],
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "State": "available",
      "CidrBlock": "10.20.0.0/16",
      "DhcpOptionsId": "dopt-0123456789abcdef0"
    }
  ]
}
```

!!! note "`OwnerId` is `000000000000` in Floci"
    Real AWS returns your 12-digit account id. Floci commonly uses all zeros. Record this in your divergence log — it matters when you write ARNs or resource policies by hand, because `arn:aws:s3:::…` policies containing a real account id will not match locally.

#### 1.3 Verification

```bash
# a) DNS attributes actually took effect
for attr in enableDnsSupport enableDnsHostnames; do
  printf '%-20s ' "$attr"
  aws ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute "$attr" \
    --query "${attr^}.Value" --output text 2>/dev/null \
    || aws ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute "$attr" --output json
done
```

```bash
# b) Discover the three objects AWS created for you, unasked
echo "--- main route table ---"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Id:RouteTableId,Main:Associations[0].Main,Routes:Routes[].[DestinationCidrBlock,GatewayId]}' \
  --output json | tee out/lab01-main-rtb.json

echo "--- default network ACL ---"
aws ec2 describe-network-acls --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkAcls[].{Id:NetworkAclId,Default:IsDefault,Entries:Entries[].[RuleNumber,Egress,RuleAction,CidrBlock,Protocol]}' \
  --output json | tee out/lab01-default-acl.json

echo "--- default security group ---"
aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[].{Id:GroupId,Name:GroupName,In:IpPermissions,Out:IpPermissionsEgress}' \
  --output json | tee out/lab01-default-sg.json
```

Record the ids — you need the main route table id in Lab 3 and the default SG id in §16:

```bash
setid RTB_MAIN "$(aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=association.main,Values=true" \
  --query 'RouteTables[0].RouteTableId' --output text)"

setid ACL_DEFAULT "$(aws ec2 describe-network-acls \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=default,Values=true" \
  --query 'NetworkAcls[0].NetworkAclId' --output text)"

setid SG_DEFAULT "$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
  --query 'SecurityGroups[0].GroupId' --output text)"

cat "$LEDGER"
```

**What you should observe, and what it means**

| Observation | Interpretation |
|---|---|
| The main route table has exactly one route, `10.20.0.0/16 → local` | The `local` route is implicit and unremovable — all subnets in this VPC will always be able to route to each other |
| The default NACL has ingress rule `100 ALLOW 0.0.0.0/0` and egress rule `100 ALLOW 0.0.0.0/0`, plus `*` DENY | The default NACL is fully permissive; it is a convenience, not a control |
| The default SG has one ingress rule whose `UserIdGroupPairs` references **itself**, and egress `0.0.0.0/0` all | Anything sharing the default SG can talk to anything else sharing it — which is why you must never use the default SG for real workloads |

!!! warning "Why we will never use the default security group"
    Its self-referencing rule means every resource that lands in it can reach every other resource in it on every port. In a three-tier app that silently defeats tiering. In §9 you will *lock down* the default SG by revoking its rules, so that anything accidentally launched into it is isolated.

#### 1.4 Break it

**Break 1 — an out-of-range CIDR.**

*AWS-correct verdict:* rejected. VPC prefix length must be between `/16` and `/28`.

```bash
aws ec2 create-vpc --cidr-block 10.0.0.0/8 2>&1 | head -3
```

Expected AWS error:

```
An error occurred (InvalidVpc.Range) when calling the CreateVpc operation:
The CIDR '10.0.0.0/8' is invalid.
```

**Break 2 — delete the default security group.**

*AWS-correct verdict:* rejected. The default SG cannot be deleted while the VPC exists.

```bash
aws ec2 delete-security-group --group-id "$SG_DEFAULT" 2>&1 | head -3
```

Expected AWS error:

```
An error occurred (CannotDelete) when calling the DeleteSecurityGroup operation:
the specified group: "default" name is reserved and cannot be deleted.
```

**Break 3 — delete the main route table.**

*AWS-correct verdict:* rejected.

```bash
aws ec2 delete-route-table --route-table-id "$RTB_MAIN" 2>&1 | head -3
```

Expected AWS error:

```
An error occurred (DependencyViolation) when calling the DeleteRouteTable operation:
The routeTable 'rtb-…' has dependencies and cannot be deleted.
```

**Break 4 — delete the `local` route.**

*AWS-correct verdict:* rejected. `local` is not a route you own.

```bash
aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 10.20.0.0/16 2>&1 | head -3
```

Expected AWS error:

```
An error occurred (InvalidParameterValue) when calling the DeleteRoute operation:
cannot remove local route 10.20.0.0/16 in route table rtb-….
```

#### 1.5 Fix it — and record divergences

For each of the four breaks, record in `out/divergence-log.md`:

| Break | AWS verdict | If Floci returned the same error | If Floci **allowed** it |
|---|---|---|---|
| `/8` VPC | reject | ✅ validation implemented | ⚠️ record: my build does not validate CIDR range. **Never rely on the API to catch a bad CIDR.** |
| delete default SG | reject | ✅ | ⚠️ record: default-object protection not implemented |
| delete main RTB | reject | ✅ | ⚠️ record: dependency checking not implemented — cleanup order will differ |
| delete `local` route | reject | ✅ | 🚨 **serious divergence**: if the local route can be deleted, your build's route model is decorative. Note it prominently; it invalidates every Track-A routing conclusion. |

```bash
cat >> out/divergence-log.md <<'MD'
| 2 | 1 | create-vpc --cidr-block 10.0.0.0/8 | InvalidVpc.Range | (fill in) | (fill in) |
| 3 | 1 | delete-security-group (default) | CannotDelete | (fill in) | (fill in) |
| 4 | 1 | delete-route-table (main) | DependencyViolation | (fill in) | (fill in) |
| 5 | 1 | delete-route (local) | InvalidParameterValue | (fill in) | (fill in) |
MD
```

#### 1.6 Recap of Lab 1

* A VPC is created with three undeletable defaults; all three are permissive and none belong in a production design.
* The `local` route guarantees intra-VPC routability — isolation is a firewall concern, not a routing concern.
* `modify-vpc-attribute` takes one attribute per call, and `enableDnsSupport=false` with `enableDnsHostnames=true` is an invalid combination.
* Tag at creation, atomically, or your cleanup will leak resources.

---

### Lab 2 — Subnetting across two availability zones

**Objective.** Create six subnets implementing the tier-major plan from §4.2, set `MapPublicIpOnLaunch` correctly per tier, and prove the five-reserved-address rule empirically.

**Prerequisites.** Lab 1. Confirm your build's AZ names.

**Architecture after this lab.**

```
  VPC 10.20.0.0/16
  ├── us-east-1a                          ├── us-east-1b
  │   ├── public  10.20.0.0/20   map=ON   │   ├── public  10.20.16.0/20  map=ON
  │   ├── app     10.20.32.0/20  map=OFF  │   ├── app     10.20.48.0/20  map=OFF
  │   └── data    10.20.64.0/20  map=OFF  │   └── data    10.20.80.0/20  map=OFF
  │
  └── all six implicitly associated with the MAIN route table (local only)
      and with the DEFAULT network ACL  ← we fix routing in Lab 3
```

#### 2.1 Implementation

```bash
# Confirm the two AZs your build offers, and pin them
AZ_A=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[0].ZoneName' --output text)
AZ_B=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[1].ZoneName' --output text)
setid AZ_A "$AZ_A"
setid AZ_B "$AZ_B"
echo "using AZs: $AZ_A and $AZ_B"
```

The subnet plan as data, so the build is a loop rather than six near-identical commands:

```bash
cat > out/subnet-plan.tsv <<PLAN
SUBNET_PUBLIC_1A	dnb-dev-subnet-public-1a	10.20.0.0/20	$AZ_A	public
SUBNET_PUBLIC_1B	dnb-dev-subnet-public-1b	10.20.16.0/20	$AZ_B	public
SUBNET_APP_1A	dnb-dev-subnet-app-1a	10.20.32.0/20	$AZ_A	app
SUBNET_APP_1B	dnb-dev-subnet-app-1b	10.20.48.0/20	$AZ_B	app
SUBNET_DATA_1A	dnb-dev-subnet-data-1a	10.20.64.0/20	$AZ_A	data
SUBNET_DATA_1B	dnb-dev-subnet-data-1b	10.20.80.0/20	$AZ_B	data
PLAN
column -t -s $'\t' out/subnet-plan.tsv
```

```bash
while IFS=$'\t' read -r key name cidr az tier; do
  [ -z "${key:-}" ] && continue
  sid=$(aws ec2 create-subnet \
    --vpc-id "$VPC_ID" \
    --cidr-block "$cidr" \
    --availability-zone "$az" \
    --tag-specifications "ResourceType=subnet,Tags=[
        {Key=Name,Value=$name},
        {Key=Project,Value=CoreBanking},
        {Key=Environment,Value=dev},
        {Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},
        {Key=ManagedBy,Value=floci-lab},
        {Key=Tier,Value=$tier}]" \
    --query 'Subnet.SubnetId' --output text)
  setid "$key" "$sid"
  if [ "$tier" = "public" ]; then
    aws ec2 modify-subnet-attribute --subnet-id "$sid" --map-public-ip-on-launch
    echo "  -> $name map-public-ip-on-launch = true"
  else
    aws ec2 modify-subnet-attribute --subnet-id "$sid" --no-map-public-ip-on-launch
    echo "  -> $name map-public-ip-on-launch = false (explicit)"
  fi
done < out/subnet-plan.tsv
```

!!! note "Why a `while read` loop and not a pipe"
    The loop reads from a **file redirect**, not from `cat … |`. A piped loop runs in a subshell, so `setid`'s `export` would be discarded and the ledger variables would not exist in your shell afterwards. This is convention gate 7 from the course standards, and it bites students in every module.

**Parameter explanation**

| Parameter | Meaning | Notes |
|---|---|---|
| `--vpc-id` | Parent VPC | The subnet CIDR must be inside a VPC CIDR |
| `--cidr-block` | Subnet range | `/16`…`/28`; must not overlap an existing subnet |
| `--availability-zone` | AZ binding | **Fixed for life.** Omitting it lets AWS choose, which silently breaks multi-AZ assumptions |
| `--tag-specifications` | Atomic tags | `Tier` drives our route table and NACL assignment and the Lab 10 matrix |
| `--map-public-ip-on-launch` | Auto-assign public IPv4 | Only for subnets that are genuinely public. Setting it `false` **explicitly** documents intent |

!!! tip "Prefer `--availability-zone-id` when working across accounts"
    AZ *names* (`us-east-1a`) are randomised per AWS account: your `us-east-1a` and a colleague's may be different physical zones. AZ *ids* (`use1-az4`) are stable across accounts. For a single-account lab, names are fine; for a multi-account landing zone, always use ids.

#### 2.2 Expected output

```bash
aws ec2 describe-subnets --subnet-ids "$SUBNET_APP_1A" --output json
```

```json
{
  "Subnets": [
    {
      "AvailabilityZone": "us-east-1a",
      "AvailabilityZoneId": "use1-az4",
      "AvailableIpAddressCount": 4091,
      "CidrBlock": "10.20.32.0/20",
      "DefaultForAz": false,
      "MapPublicIpOnLaunch": false,
      "MapCustomerOwnedIpOnLaunch": false,
      "State": "available",
      "SubnetId": "subnet-0b1c2d3e4f5a6b7c8",
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "OwnerId": "000000000000",
      "AssignIpv6AddressOnCreation": false,
      "Ipv6CidrBlockAssociationSet": [],
      "Tags": [
        { "Key": "Name", "Value": "dnb-dev-subnet-app-1a" },
        { "Key": "Tier", "Value": "app" }
      ],
      "SubnetArn": "arn:aws:ec2:us-east-1:000000000000:subnet/subnet-0b1c2d3e4f5a6b7c8",
      "EnableDns64": false,
      "PrivateDnsNameOptionsOnLaunch": {
        "HostnameType": "ip-name",
        "EnableResourceNameDnsARecord": false,
        "EnableResourceNameDnsAAAARecord": false
      }
    }
  ]
}
```

**`AvailableIpAddressCount: 4091`** is the whole point: `4096 − 5 = 4091`. If your build reports `4096`, it has not implemented the reserved-address rule — a divergence worth logging, because it means the emulator will let you place 4 096 ENIs where AWS would fail at 4 091.

#### 2.3 Verification

```bash
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets, &CidrBlock)[].{
      Name:Tags[?Key==`Name`]|[0].Value,
      Tier:Tags[?Key==`Tier`]|[0].Value,
      CIDR:CidrBlock, AZ:AvailabilityZone,
      Free:AvailableIpAddressCount, PubIP:MapPublicIpOnLaunch}' \
  --output table | tee out/lab02-subnets.txt
```

```
-------------------------------------------------------------------------------------------
|                                     DescribeSubnets                                     |
+-------+-----------+-------+---------------------------+--------+--------------+---------+
|  AZ   |   CIDR    | Free  |           Name            | PubIP  |    Tier      |         |
+-------+-----------+-------+---------------------------+--------+--------------+---------+
| us-east-1a | 10.20.0.0/20  | 4091 | dnb-dev-subnet-public-1a | True  | public |    |
| us-east-1b | 10.20.16.0/20 | 4091 | dnb-dev-subnet-public-1b | True  | public |    |
| us-east-1a | 10.20.32.0/20 | 4091 | dnb-dev-subnet-app-1a    | False | app    |    |
| us-east-1b | 10.20.48.0/20 | 4091 | dnb-dev-subnet-app-1b    | False | app    |    |
| us-east-1a | 10.20.64.0/20 | 4091 | dnb-dev-subnet-data-1a   | False | data   |    |
| us-east-1b | 10.20.80.0/20 | 4091 | dnb-dev-subnet-data-1b   | False | data   |    |
+-------+-----------+-------+---------------------------+--------+--------------+---------+
```

**Automated assertions** — a verification script rather than eyeballing:

```bash
cat > bin/verify-lab02.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?load the ledger first}"
fail=0
check() { if [ "$2" = "$3" ]; then printf '  PASS %s\n' "$1"; else printf '  FAIL %s (want %s, got %s)\n' "$1" "$3" "$2"; fail=1; fi; }

n=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
      --query 'length(Subnets)' --output text)
check "six subnets exist" "$n" "6"

azs=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
        --query 'Subnets[].AvailabilityZone' --output text | tr '\t' '\n' | sort -u | wc -l | tr -d ' ')
check "spread over two AZs" "$azs" "2"

pub=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
        "Name=tag:Tier,Values=public" \
        --query 'length(Subnets[?MapPublicIpOnLaunch==`true`])' --output text)
check "both public subnets auto-assign" "$pub" "2"

priv=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
         --query 'length(Subnets[?MapPublicIpOnLaunch==`true`])' --output text)
check "exactly two subnets auto-assign in total" "$priv" "2"

free=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
         --query 'Subnets[0].AvailableIpAddressCount' --output text)
check "reserved-5 rule applied (/20 -> 4091)" "$free" "4091"

exit $fail
SH
chmod +x bin/verify-lab02.sh
./bin/verify-lab02.sh
```

#### 2.4 Break it

**Break 1 — overlapping subnet CIDR.**

*AWS-correct verdict:* rejected with `InvalidSubnet.Conflict`.

```bash
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.8.0/21 \
  --availability-zone "$AZ_A" 2>&1 | head -3
```

```
An error occurred (InvalidSubnet.Conflict) when calling the CreateSubnet operation:
The CIDR '10.20.8.0/21' conflicts with another subnet
```

`10.20.8.0/21` covers `10.20.8.0`–`10.20.15.255`, which sits inside the existing `10.20.0.0/20`. Overlap is overlap even when the new block is smaller.

**Break 2 — subnet outside the VPC range.**

*AWS-correct verdict:* rejected with `InvalidParameterValue`.

```bash
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.99.0.0/24 \
  --availability-zone "$AZ_A" 2>&1 | head -3
```

**Break 3 — a subnet smaller than `/28`.**

*AWS-correct verdict:* rejected. `/29` is below the minimum.

```bash
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.240.0/29 \
  --availability-zone "$AZ_A" 2>&1 | head -3
```

**Break 4 — the AZ mistake that produces a fake multi-AZ design.**

*AWS-correct verdict:* accepted! This one **succeeds**, which is precisely why it is dangerous. Omitting `--availability-zone` lets AWS choose, and it may choose the same AZ you already used.

```bash
BAD_SUBNET=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.240.0/24 \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=dnb-dev-subnet-oops},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'Subnet.SubnetId' --output text)
setid BAD_SUBNET "$BAD_SUBNET"
aws ec2 describe-subnets --subnet-ids "$BAD_SUBNET" \
  --query 'Subnets[0].[SubnetId,CidrBlock,AvailabilityZone]' --output text
```

Now ask the question that matters: *if I built a "multi-AZ" ALB across `dnb-dev-subnet-public-1a` and this subnet, would I actually have AZ redundancy?* Only if the AZ differs. There is no API error to save you — the failure surfaces during an AZ outage.

#### 2.5 Fix it

```bash
# Remove the accidental subnet; explicit AZ from now on, always.
aws ec2 delete-subnet --subnet-id "$BAD_SUBNET"
grep -v '^export BAD_SUBNET=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset BAD_SUBNET
./bin/verify-lab02.sh
```

Add a guard to your own automation so the class of error cannot recur:

```bash
require_two_azs() {
  local n
  n=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Tier,Values=$1" \
        --query 'Subnets[].AvailabilityZone' --output text | tr '\t' '\n' | sort -u | wc -l | tr -d ' ')
  if [ "$n" -lt 2 ]; then
    echo "FAIL: tier '$1' spans only $n AZ(s)" >&2; return 1
  fi
  echo "OK: tier '$1' spans $n AZs"
}
for t in public app data; do require_two_azs "$t"; done
```

#### 2.6 Recap of Lab 2

* Subnets are AZ-scoped and the AZ is immutable; always pass `--availability-zone` explicitly.
* `AvailableIpAddressCount` = total − 5. Memorise the five reserved addresses and what each does.
* Overlap is checked; range and prefix length are checked; **AZ *distribution* is not** — that is your responsibility.
* Set `MapPublicIpOnLaunch` explicitly in both directions so the intent is recorded in the API, not just in your head.

---

### Lab 3 — Internet gateway and public routing

**Objective.** Make the public subnets genuinely public, keep the main route table minimal, and demonstrate the implicit-association trap.

**Prerequisites.** Labs 1–2.

**Architecture after this lab.**

```
                     ┌──────────┐
                     │ Internet │
                     └────┬─────┘
                          │
                    ┌─────┴──────┐
                    │ dnb-dev-igw│  attached to vpc
                    └─────┬──────┘
                          │
  ┌───────────────────────┼─────────────────────────────────────┐
  │ rtb-public                                                  │
  │   10.20.0.0/16 → local                                      │
  │   0.0.0.0/0    → igw-…                                      │
  │   associations: subnet-public-1a , subnet-public-1b          │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │ rtb-main  (unchanged, local only) ← app/data subnets still  │
  │                                     implicitly attached     │
  └─────────────────────────────────────────────────────────────┘
```

#### 3.1 Implementation

```bash
IGW_ID=$(aws ec2 create-internet-gateway \
  --tag-specifications 'ResourceType=internet-gateway,Tags=[
      {Key=Name,Value=dnb-dev-igw},
      {Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},
      {Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},
      {Key=ManagedBy,Value=floci-lab}]' \
  --query 'InternetGateway.InternetGatewayId' --output text)
setid IGW_ID "$IGW_ID"

aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
```

```bash
RTB_PUBLIC=$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=route-table,Tags=[
      {Key=Name,Value=dnb-dev-rtb-public},
      {Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},
      {Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},
      {Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=public}]' \
  --query 'RouteTable.RouteTableId' --output text)
setid RTB_PUBLIC "$RTB_PUBLIC"

aws ec2 create-route \
  --route-table-id "$RTB_PUBLIC" \
  --destination-cidr-block 0.0.0.0/0 \
  --gateway-id "$IGW_ID"

for s in "$SUBNET_PUBLIC_1A" "$SUBNET_PUBLIC_1B"; do
  assoc=$(aws ec2 associate-route-table --route-table-id "$RTB_PUBLIC" --subnet-id "$s" \
            --query 'AssociationId' --output text)
  echo "associated $s -> $RTB_PUBLIC as $assoc"
done
```

**Parameter explanation**

| Command / parameter | Meaning | Notes |
|---|---|---|
| `create-internet-gateway` | Creates a detached IGW | Free; no configuration; HA by AWS |
| `attach-internet-gateway --vpc-id` | Binds IGW to VPC | 1:1 both ways; a second attach fails with `Resource.AlreadyAssociated` |
| `create-route --destination-cidr-block 0.0.0.0/0` | Default route | For IPv6 you would use `--destination-ipv6-cidr-block ::/0` |
| `--gateway-id` | Target | Used for IGW, VGW **and** gateway endpoints; NAT gateways use `--nat-gateway-id` instead |
| `associate-route-table --subnet-id` | Explicit association | Returns `rtbassoc-…`; **without this the subnet uses the main table** |

#### 3.2 Expected output

```bash
aws ec2 describe-route-tables --route-table-ids "$RTB_PUBLIC" --output json
```

```json
{
  "RouteTables": [
    {
      "Associations": [
        {
          "Main": false,
          "RouteTableAssociationId": "rtbassoc-0aa1122334455667f",
          "RouteTableId": "rtb-0cc9988776655443a",
          "SubnetId": "subnet-0d1e2f3a4b5c6d7e8",
          "AssociationState": { "State": "associated" }
        },
        {
          "Main": false,
          "RouteTableAssociationId": "rtbassoc-0bb2233445566778a",
          "RouteTableId": "rtb-0cc9988776655443a",
          "SubnetId": "subnet-0e2f3a4b5c6d7e8f9",
          "AssociationState": { "State": "associated" }
        }
      ],
      "RouteTableId": "rtb-0cc9988776655443a",
      "Routes": [
        {
          "DestinationCidrBlock": "10.20.0.0/16",
          "GatewayId": "local",
          "Origin": "CreateRouteTable",
          "State": "active"
        },
        {
          "DestinationCidrBlock": "0.0.0.0/0",
          "GatewayId": "igw-0ff8877665544332b",
          "Origin": "CreateRoute",
          "State": "active"
        }
      ],
      "Tags": [ { "Key": "Name", "Value": "dnb-dev-rtb-public" } ],
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "OwnerId": "000000000000"
    }
  ]
}
```

Two fields to read carefully:

* `Origin` — `CreateRouteTable` marks the implicit `local` route; `CreateRoute` marks routes you added; `EnableVgwRoutePropagation` marks BGP-learned routes.
* `State` — `active` or `blackhole`. A blackhole route silently drops traffic and is the first thing to check when connectivity breaks after a deletion.

#### 3.3 Verification

```bash
# Which subnets are now genuinely public? Defined as: associated with a table
# that has a 0.0.0.0/0 route whose target is an internet gateway.
cat > bin/public-subnets.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?}"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" --output json \
| python3 -c '
import json, sys
d = json.load(sys.stdin)
for t in d["RouteTables"]:
    igw = [r for r in t["Routes"]
           if r.get("DestinationCidrBlock") == "0.0.0.0/0"
           and str(r.get("GatewayId", "")).startswith("igw-")]
    if not igw:
        continue
    name = next((x["Value"] for x in t.get("Tags", []) if x["Key"] == "Name"), t["RouteTableId"])
    subs = [a.get("SubnetId") for a in t.get("Associations", []) if a.get("SubnetId")]
    main = any(a.get("Main") for a in t.get("Associations", []))
    print(f"PUBLIC via {name}: explicit={subs or None} main_table={main}")
    if main:
        print("  *** WARNING: this is the MAIN table. Every unassociated subnet is PUBLIC. ***")
'
SH
chmod +x bin/public-subnets.sh
./bin/public-subnets.sh | tee out/lab03-public.txt
```

Expected:

```
PUBLIC via dnb-dev-rtb-public: explicit=['subnet-0d1e…', 'subnet-0e2f…'] main_table=False
```

```bash
# Confirm the app/data subnets are still on the MAIN table (implicit association)
aws ec2 describe-route-tables --route-table-ids "$RTB_MAIN" \
  --query 'RouteTables[0].{Main:Associations[?Main==`true`].Main,Explicit:Associations[?SubnetId!=null].SubnetId,Routes:Routes[].[DestinationCidrBlock,GatewayId,State]}' \
  --output json
```

You will see **no** explicit subnet associations and only the `local` route. That is correct and intentional: the four private subnets have no internet path at all right now.

#### 3.4 Break it

**Break 1 — put a default route on the main route table.**

*AWS-correct verdict:* **accepted**, and catastrophic. Every subnet that is not explicitly associated becomes public — including your data tier.

```bash
aws ec2 create-route --route-table-id "$RTB_MAIN" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"

./bin/public-subnets.sh
```

Now you should see the warning line fire. Reason about it with the evaluator once you have security groups (Lab 10) — but the routing conclusion is already unambiguous: `subnet-data-1a` has a path to the internet gateway.

**Break 2 — detach the IGW while it is referenced.**

*AWS-correct verdict:* the detach itself is permitted while no ENI has a public IP, but any `0.0.0.0/0 → igw` route becomes `blackhole`.

```bash
aws ec2 detach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>&1 | head -3
aws ec2 describe-route-tables --route-table-ids "$RTB_PUBLIC" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId,State]' --output text
```

Look for `State` becoming `blackhole` on the `0.0.0.0/0` row. If your build leaves it `active`, log the divergence — it means your build will never show you a blackhole, so you must reason about deletions manually.

**Break 3 — a second internet gateway.**

*AWS-correct verdict:* rejected; one IGW per VPC.

```bash
IGW2=$(aws ec2 create-internet-gateway --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW2" --vpc-id "$VPC_ID" 2>&1 | head -3
aws ec2 delete-internet-gateway --internet-gateway-id "$IGW2"
```

Expected AWS error: `Resource.AlreadyAssociated: … already has an internet gateway attached`.

#### 3.5 Fix it

```bash
# 1. Undo Break 1 — the main table must contain nothing but `local`
aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 0.0.0.0/0
aws ec2 describe-route-tables --route-table-ids "$RTB_MAIN" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId]' --output text

# 2. Undo Break 2 — re-attach the IGW and confirm the route returns to active
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>/dev/null \
  || echo "already attached"
aws ec2 describe-route-tables --route-table-ids "$RTB_PUBLIC" \
  --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].[GatewayId,State]' --output text

# 3. Verify no subnet is implicitly public
./bin/public-subnets.sh
```

**The permanent fix** — a drift check you should run in CI:

```bash
cat > bin/assert-main-rtb-minimal.sh <<'SH'
#!/usr/bin/env bash
# Fails if the VPC main route table contains anything other than local routes.
set -uo pipefail
: "${VPC_ID:?}"
extra=$(aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=association.main,Values=true" \
  --query 'RouteTables[0].Routes[?GatewayId!=`local`].DestinationCidrBlock' --output text)
if [ -n "$extra" ] && [ "$extra" != "None" ]; then
  echo "DRIFT: main route table has non-local routes: $extra" >&2
  exit 1
fi
echo "OK: main route table contains only local routes"
SH
chmod +x bin/assert-main-rtb-minimal.sh
./bin/assert-main-rtb-minimal.sh
```

#### 3.6 Recap of Lab 3

* "Public subnet" has a precise definition: its route table has `0.0.0.0/0` pointing at an internet gateway. Names and tags mean nothing.
* Keep the main route table `local`-only, and associate every subnet explicitly. Otherwise a single `create-route` exposes everything you forgot.
* Deleting a route target leaves a **blackhole** route, not an error.
* One IGW per VPC; detaching it breaks every route that references it.

---

### Lab 4 — NAT gateways and per-AZ private egress

**Objective.** Give the app tier outbound-only internet access, with per-AZ NAT gateways and per-AZ private route tables. Understand why the data tier gets neither.

**Prerequisites.** Labs 1–3. `guard` — **this lab allocates Elastic IPs, which are billable in real AWS.**

**Architecture after this lab.**

```
                       ┌──────────┐
                       │ Internet │
                       └────┬─────┘
                            │ igw
        ┌───────────────────┴───────────────────┐
        │                                       │
  ┌─────┴────── AZ-a ──────┐            ┌───────┴───── AZ-b ─────┐
  │ public-1a              │            │ public-1b              │
  │   nat-1a  ◄─ eip-1a    │            │   nat-1b  ◄─ eip-1b    │
  │   rtb-public: 0/0→igw  │            │   rtb-public (shared)  │
  └─────┬──────────────────┘            └───────┬────────────────┘
        │                                       │
  ┌─────┴──────────────────┐            ┌───────┴────────────────┐
  │ app-1a                 │            │ app-1b                 │
  │  rtb-private-1a:       │            │  rtb-private-1b:       │
  │    0.0.0.0/0 → nat-1a  │            │    0.0.0.0/0 → nat-1b  │
  └────────────────────────┘            └────────────────────────┘
  ┌────────────────────────┐            ┌────────────────────────┐
  │ data-1a                │            │ data-1b                │
  │  rtb-data: local ONLY  │◄── shared ─┤  rtb-data              │
  │  (isolated tier)       │            │                        │
  └────────────────────────┘            └────────────────────────┘
```

#### 4.1 Implementation

```bash
guard || return 1

# One Elastic IP per NAT gateway
EIP_1A=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[
      {Key=Name,Value=dnb-dev-eip-nat-1a},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'AllocationId' --output text)
setid EIP_1A "$EIP_1A"

EIP_1B=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[
      {Key=Name,Value=dnb-dev-eip-nat-1b},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'AllocationId' --output text)
setid EIP_1B "$EIP_1B"

aws ec2 describe-addresses --allocation-ids "$EIP_1A" "$EIP_1B" \
  --query 'Addresses[].[AllocationId,PublicIp,Domain,AssociationId]' --output table
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--domain vpc` | VPC-scoped EIP | The only valid value in modern AWS; `standard` was EC2-Classic |
| `--tag-specifications ResourceType=elastic-ip` | Atomic tagging | EIPs are the #1 orphaned billable resource; untagged EIPs are invisible to cleanup |
| `AssociationId: null` | Not yet attached | **AWS bills an unassociated EIP.** Never allocate one you are not about to use |

```bash
# NAT gateway per AZ, each in that AZ's PUBLIC subnet
NAT_1A=$(aws ec2 create-nat-gateway \
  --subnet-id "$SUBNET_PUBLIC_1A" \
  --allocation-id "$EIP_1A" \
  --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[
      {Key=Name,Value=dnb-dev-nat-1a},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1A "$NAT_1A"

NAT_1B=$(aws ec2 create-nat-gateway \
  --subnet-id "$SUBNET_PUBLIC_1B" \
  --allocation-id "$EIP_1B" \
  --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[
      {Key=Name,Value=dnb-dev-nat-1b},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1B "$NAT_1B"
```

!!! warning "In real AWS, `create-nat-gateway` returns immediately with `State: pending`"
    Provisioning takes one to two minutes. Any `create-route` pointing at a pending NAT gateway succeeds, but traffic fails until it is `available`. Always wait:

    ```bash
    aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_1A" "$NAT_1B" 2>/dev/null \
      || echo "note: this build may not implement the nat-gateway-available waiter"
    aws ec2 describe-nat-gateways --nat-gateway-ids "$NAT_1A" "$NAT_1B" \
      --query 'NatGateways[].[NatGatewayId,State,SubnetId,NatGatewayAddresses[0].PublicIp]' --output table
    ```

Now the private route tables — **one per AZ**, which is the entire point:

```bash
make_private_rtb() {   # make_private_rtb <ledger-key> <name> <nat-id> <subnet-id>
  local key="$1" name="$2" nat="$3" subnet="$4" rtb
  rtb=$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
    --tag-specifications "ResourceType=route-table,Tags=[
        {Key=Name,Value=$name},{Key=Project,Value=CoreBanking},
        {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
        {Key=Tier,Value=app}]" \
    --query 'RouteTable.RouteTableId' --output text)
  aws ec2 create-route --route-table-id "$rtb" \
    --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$nat" >/dev/null
  aws ec2 associate-route-table --route-table-id "$rtb" --subnet-id "$subnet" >/dev/null
  setid "$key" "$rtb"
}

make_private_rtb RTB_PRIVATE_1A dnb-dev-rtb-private-1a "$NAT_1A" "$SUBNET_APP_1A"
make_private_rtb RTB_PRIVATE_1B dnb-dev-rtb-private-1b "$NAT_1B" "$SUBNET_APP_1B"
```

And the **isolated** data-tier table — shared by both data subnets, with no default route whatsoever:

```bash
RTB_DATA=$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=route-table,Tags=[
      {Key=Name,Value=dnb-dev-rtb-data},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=data}]' \
  --query 'RouteTable.RouteTableId' --output text)
setid RTB_DATA "$RTB_DATA"

for s in "$SUBNET_DATA_1A" "$SUBNET_DATA_1B"; do
  aws ec2 associate-route-table --route-table-id "$RTB_DATA" --subnet-id "$s" >/dev/null
done
echo "data tier associated with $RTB_DATA (local route only — no egress by design)"
```

!!! note "Why the data table is shared but the app tables are not"
    The app tables differ **because each points at a different NAT gateway**. The data table has no AZ-specific target — only `local` — so a single shared table is correct and simpler. In Lab 7 we will add an S3 gateway-endpoint route to it, which is also AZ-agnostic.

#### 4.2 Expected output

```bash
aws ec2 describe-nat-gateways --nat-gateway-ids "$NAT_1A" --output json
```

```json
{
  "NatGateways": [
    {
      "CreateTime": "2026-08-06T04:12:31.000Z",
      "NatGatewayAddresses": [
        {
          "AllocationId": "eipalloc-0a1b2c3d4e5f6a7b8",
          "NetworkInterfaceId": "eni-09f8e7d6c5b4a3210",
          "PrivateIp": "10.20.0.42",
          "PublicIp": "52.203.11.7",
          "AssociationId": "eipassoc-0123456789abcdef0",
          "IsPrimary": true,
          "Status": "succeeded"
        }
      ],
      "NatGatewayId": "nat-0abcdef1234567890",
      "State": "available",
      "SubnetId": "subnet-0d1e2f3a4b5c6d7e8",
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "ConnectivityType": "public",
      "Tags": [ { "Key": "Name", "Value": "dnb-dev-nat-1a" } ]
    }
  ]
}
```

Note the NAT gateway's **own ENI** with a private IP from the public subnet (`10.20.0.42`). That ENI is why you cannot delete the public subnet until the NAT gateway is gone.

#### 4.3 Verification

```bash
cat > bin/routing-report.sh <<'SH'
#!/usr/bin/env bash
# For every subnet: which route table applies (explicit or main), and what is the
# default route target? This is THE report to paste into a lab report.
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True, text=True).stdout or "{}")
def name(o):
    return next((t["Value"] for t in o.get("Tags",[]) if t["Key"]=="Name"), "-")

subs = aws("describe-subnets","--filters",f"Name=vpc-id,Values={vpc}")["Subnets"]
rts  = aws("describe-route-tables","--filters",f"Name=vpc-id,Values={vpc}")["RouteTables"]
explicit = {a["SubnetId"]: t for t in rts for a in t.get("Associations",[]) if a.get("SubnetId")}
main = next((t for t in rts for a in t.get("Associations",[]) if a.get("Main")), None)

def default_route(t):
    for r in t.get("Routes", []):
        if r.get("DestinationCidrBlock") == "0.0.0.0/0":
            tgt = (r.get("GatewayId") or r.get("NatGatewayId")
                   or r.get("TransitGatewayId") or r.get("VpcPeeringConnectionId")
                   or r.get("NetworkInterfaceId") or "?")
            return f"{tgt} [{r.get('State','?')}]"
    return "NONE (isolated)"

def classify(t):
    for r in t.get("Routes", []):
        if r.get("DestinationCidrBlock") != "0.0.0.0/0":
            continue
        g = str(r.get("GatewayId") or "")
        if g.startswith("igw-"): return "PUBLIC"
        if r.get("NatGatewayId"): return "PRIVATE (NAT egress)"
        return "ROUTED (other)"
    return "ISOLATED"

print(f"{'subnet':28} {'tier':7} {'az':12} {'route table':26} {'assoc':9} {'default route':28} class")
print("-"*140)
for s in sorted(subs, key=lambda x: x["CidrBlock"]):
    t = explicit.get(s["SubnetId"], main)
    how = "explicit" if s["SubnetId"] in explicit else "MAIN!"
    tier = next((x["Value"] for x in s.get("Tags",[]) if x["Key"]=="Tier"), "-")
    print(f"{name(s):28} {tier:7} {s['AvailabilityZone']:12} "
          f"{name(t):26} {how:9} {default_route(t):28} {classify(t)}")
PY
SH
chmod +x bin/routing-report.sh
./bin/routing-report.sh | tee out/lab04-routing.txt
```

Expected:

```
subnet                       tier    az           route table                assoc     default route                class
--------------------------------------------------------------------------------------------------------------------------
dnb-dev-subnet-public-1a     public  us-east-1a   dnb-dev-rtb-public         explicit  igw-0ff8… [active]           PUBLIC
dnb-dev-subnet-public-1b     public  us-east-1b   dnb-dev-rtb-public         explicit  igw-0ff8… [active]           PUBLIC
dnb-dev-subnet-app-1a        app     us-east-1a   dnb-dev-rtb-private-1a     explicit  nat-0abc… [active]           PRIVATE (NAT egress)
dnb-dev-subnet-app-1b        app     us-east-1b   dnb-dev-rtb-private-1b     explicit  nat-0def… [active]           PRIVATE (NAT egress)
dnb-dev-subnet-data-1a       data    us-east-1a   dnb-dev-rtb-data           explicit  NONE (isolated)              ISOLATED
dnb-dev-subnet-data-1b       data    us-east-1b   dnb-dev-rtb-data           explicit  NONE (isolated)              ISOLATED
```

Every subnet shows `explicit` and no subnet shows `MAIN!`. That single column is the difference between a design and an accident.

**AZ-affinity assertion** — prove that each private table points at a NAT gateway in its *own* AZ:

```bash
cat > bin/assert-nat-az-affinity.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True, text=True).stdout or "{}")
subs = {s["SubnetId"]: s for s in aws("describe-subnets","--filters",f"Name=vpc-id,Values={vpc}")["Subnets"]}
nats = {n["NatGatewayId"]: n for n in aws("describe-nat-gateways")["NatGateways"]}
rts  = aws("describe-route-tables","--filters",f"Name=vpc-id,Values={vpc}")["RouteTables"]
bad = 0
for t in rts:
    nat = next((r["NatGatewayId"] for r in t.get("Routes",[])
                if r.get("DestinationCidrBlock")=="0.0.0.0/0" and r.get("NatGatewayId")), None)
    if not nat:
        continue
    nat_az = subs.get(nats.get(nat,{}).get("SubnetId",""),{}).get("AvailabilityZone","?")
    for a in t.get("Associations",[]):
        sid = a.get("SubnetId")
        if not sid:
            continue
        s_az = subs[sid]["AvailabilityZone"]
        ok = (s_az == nat_az)
        bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'} {sid} ({s_az}) -> {nat} (in {nat_az})")
print("\nAZ affinity:", "OK" if bad==0 else f"{bad} cross-AZ route(s) — costs money and breaks AZ isolation")
sys.exit(1 if bad else 0)
PY
SH
chmod +x bin/assert-nat-az-affinity.sh
./bin/assert-nat-az-affinity.sh
```

#### 4.4 Break it

**Break 1 — NAT gateway in a private subnet.**

*AWS-correct verdict:* the create **succeeds** and then the gateway transitions to `State: failed` with `FailureCode: Gateway.NotAttached`, because its subnet has no route to an internet gateway. This is the classic "why is my NAT broken" incident.

```bash
BAD_EIP=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=dnb-dev-eip-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'AllocationId' --output text)
setid BAD_EIP "$BAD_EIP"

BAD_NAT=$(aws ec2 create-nat-gateway \
  --subnet-id "$SUBNET_DATA_1A" --allocation-id "$BAD_EIP" \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=dnb-dev-nat-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid BAD_NAT "$BAD_NAT"

sleep 5
aws ec2 describe-nat-gateways --nat-gateway-ids "$BAD_NAT" \
  --query 'NatGateways[0].[NatGatewayId,State,FailureCode,FailureMessage]' --output text
```

Real AWS output:

```
nat-0badbadbadbadbad0	failed	Gateway.NotAttached	Network vpc-… has no Internet gateway attached
```

**Break 2 — cross-AZ NAT routing.**

*AWS-correct verdict:* **accepted**, works, and is wrong. Traffic from `app-1b` crosses to AZ-a, incurring cross-AZ data transfer on every byte and creating an AZ-a dependency for an AZ-b workload.

```bash
aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1B" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1A"
./bin/assert-nat-az-affinity.sh || echo "^ the assertion caught it"
```

**Break 3 — delete a NAT gateway that routes reference.**

*AWS-correct verdict:* accepted; the route becomes `blackhole`; the EIP is **not** released.

```bash
aws ec2 delete-nat-gateway --nat-gateway-id "$BAD_NAT"
aws ec2 describe-addresses --allocation-ids "$BAD_EIP" \
  --query 'Addresses[0].[AllocationId,PublicIp,AssociationId]' --output text
echo "^ AssociationId should now be None — and AWS is still billing for this EIP"
```

#### 4.5 Fix it

```bash
# 1. Restore AZ affinity
aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1B" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1B"
./bin/assert-nat-az-affinity.sh

# 2. Release the orphaned probe EIP (the habit that saves real money)
aws ec2 release-address --allocation-id "$BAD_EIP" 2>&1 | head -2 \
  || echo "note: EIP may still be reserved while the NAT gateway finishes deleting; retry"
grep -v -e '^export BAD_EIP=' -e '^export BAD_NAT=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset BAD_EIP BAD_NAT

# 3. Standing check for orphaned EIPs — run this at the end of every session
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp,Tags[?Key==`Name`]|[0].Value]' \
  --output table
```

#### 4.6 Recap of Lab 4

* A NAT gateway lives in a **public** subnet, needs an EIP, is **AZ-scoped**, and has **no security group**.
* One NAT gateway and one private route table **per AZ** — otherwise you pay cross-AZ charges and lose AZ independence.
* The data tier is *isolated*, not merely private: its route table contains only `local`.
* Deleting a NAT gateway leaves a blackhole route and a billed, orphaned Elastic IP. Always sweep for unassociated EIPs.
* `create-nat-gateway` can succeed and then fail asynchronously — always check `State` and `FailureCode`.

---
### Lab 5 — Security groups: identity-based network policy

**Objective.** Build a four-group chain (`web → app → db`, plus `vpce`) using **security-group references** rather than CIDR literals, restrict egress deliberately, and prove that security groups are allow-only and order-independent.

**Prerequisites.** Labs 1–4.

**Architecture after this lab.**

```
   Internet
      │  443, 80
      ▼
  ┌──────────────┐   8080     ┌──────────────┐   5432    ┌──────────────┐
  │  sg-web      │───────────►│   sg-app     │──────────►│   sg-db      │
  │  (ALB nodes) │            │  (workers)   │           │  (RDS)       │
  │ in: 80,443   │            │ in: 8080 from│           │ in: 5432 from│
  │     0.0.0.0/0│            │     sg-web   │           │     sg-app   │
  │ out: 8080 to │            │ out: 5432→db │           │ out: NOTHING │
  │      sg-app  │            │      443→any │           │              │
  └──────────────┘            └──────┬───────┘           └──────────────┘
                                     │ 443
                                     ▼
                              ┌──────────────┐
                              │  sg-vpce     │  in: 443 from sg-app, sg-web
                              │ (endpoint    │  out: nothing needed
                              │  ENIs)       │
                              └──────────────┘

  Note: NO CIDR literals anywhere inside the VPC. Only sg-web's
  internet-facing ingress uses 0.0.0.0/0, because that is genuinely public.
```

#### 5.1 Implementation

```bash
mksg() {   # mksg <ledger-key> <name> <description>
  local key="$1" name="$2" desc="$3" id
  id=$(aws ec2 create-security-group \
    --group-name "$name" \
    --description "$desc" \
    --vpc-id "$VPC_ID" \
    --tag-specifications "ResourceType=security-group,Tags=[
        {Key=Name,Value=$name},{Key=Project,Value=CoreBanking},
        {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]" \
    --query 'GroupId' --output text)
  setid "$key" "$id"
}

mksg SG_WEB  dnb-dev-sg-web  "Public ALB nodes: terminates TLS from the internet"
mksg SG_APP  dnb-dev-sg-app  "Statement generation workers: private app tier"
mksg SG_DB   dnb-dev-sg-db   "PostgreSQL data tier: isolated, no egress"
mksg SG_VPCE dnb-dev-sg-vpce "Interface VPC endpoint ENIs: HTTPS from app tiers"
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--group-name` | Friendly name, unique **within the VPC** | Immutable after creation; `GroupName` is what appears in `DependencyViolation` errors |
| `--description` | **Mandatory** | AWS refuses to create a group without one. Write what the group *is*, not what it allows |
| `--vpc-id` | Parent VPC | Omit it and (in an account with a default VPC) the group lands in the default VPC — a classic confusing failure |

Now the rules. Note the total absence of intra-VPC CIDRs:

```bash
# --- sg-web: genuinely internet-facing ingress -------------------------------
aws ec2 authorize-security-group-ingress --group-id "$SG_WEB" \
  --ip-permissions '[
    {"IpProtocol":"tcp","FromPort":443,"ToPort":443,
     "IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTPS"}]},
    {"IpProtocol":"tcp","FromPort":80,"ToPort":80,
     "IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTP, redirects to 443"}]}
  ]' >/dev/null

# --- sg-app: only the ALB may reach the app port -----------------------------
aws ec2 authorize-security-group-ingress --group-id "$SG_APP" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_WEB\",\"Description\":\"ALB to app tier\"}]}
  ]" >/dev/null

# --- sg-db: only the app tier may reach PostgreSQL ---------------------------
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":5432,\"ToPort\":5432,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"app tier to postgres\"}]}
  ]" >/dev/null

# --- sg-vpce: HTTPS from the tiers that call AWS APIs ------------------------
aws ec2 authorize-security-group-ingress --group-id "$SG_VPCE" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"UserIdGroupPairs\":[
        {\"GroupId\":\"$SG_APP\",\"Description\":\"app tier to interface endpoints\"},
        {\"GroupId\":\"$SG_WEB\",\"Description\":\"web tier to interface endpoints\"}]}
  ]" >/dev/null
```

!!! tip "`--ip-permissions` vs the short flags"
    `--protocol tcp --port 443 --cidr 0.0.0.0/0` is convenient but can express only *one* CIDR rule and **cannot express a security-group reference or a description**. Learn `--ip-permissions` properly — it is the only form that covers everything, and it is what the SDKs and CloudFormation use.

Now the part almost every tutorial skips: **egress**. Every new security group starts with allow-all egress to `0.0.0.0/0`. For the data tier that is a data-exfiltration path.

```bash
# --- Replace allow-all egress with least-privilege egress --------------------

# sg-web may only talk to the app tier
aws ec2 revoke-security-group-egress --group-id "$SG_WEB" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
aws ec2 authorize-security-group-egress --group-id "$SG_WEB" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"ALB to app tier\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_VPCE\",\"Description\":\"AWS API via endpoints\"}]}
  ]" >/dev/null

# sg-app may reach the DB, the endpoints, and HTTPS for OS patching via NAT
aws ec2 revoke-security-group-egress --group-id "$SG_APP" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
aws ec2 authorize-security-group-egress --group-id "$SG_APP" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":5432,\"ToPort\":5432,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_DB\",\"Description\":\"app tier to postgres\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_VPCE\",\"Description\":\"AWS API via endpoints\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\",\"Description\":\"OS and package updates via NAT\"}]}
  ]" >/dev/null

# sg-db gets NO egress at all. A database has no business initiating connections.
aws ec2 revoke-security-group-egress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null

# sg-vpce: endpoint ENIs do not initiate; strip egress too
aws ec2 revoke-security-group-egress --group-id "$SG_VPCE" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
```

!!! note "Why `sg-db` with zero egress still works"
    Security groups are **stateful**. A client connects in on 5432, and the response leaves automatically regardless of egress rules. Egress rules only govern connections the database itself *initiates* — replication to an external target, an outbound webhook, an attacker's exfiltration channel. Removing them costs nothing and closes a real hole.

    Contrast this with a network ACL, where removing egress would break every response. That contrast is Lab 6.

#### 5.2 Expected output

```bash
aws ec2 describe-security-groups --group-ids "$SG_DB" --output json
```

```json
{
  "SecurityGroups": [
    {
      "Description": "PostgreSQL data tier: isolated, no egress",
      "GroupName": "dnb-dev-sg-db",
      "IpPermissions": [
        {
          "IpProtocol": "tcp",
          "FromPort": 5432,
          "ToPort": 5432,
          "IpRanges": [],
          "Ipv6Ranges": [],
          "PrefixListIds": [],
          "UserIdGroupPairs": [
            {
              "GroupId": "sg-0app0app0app0app0",
              "UserId": "000000000000",
              "Description": "app tier to postgres"
            }
          ]
        }
      ],
      "IpPermissionsEgress": [],
      "OwnerId": "000000000000",
      "GroupId": "sg-0db0db0db0db0db00",
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "Tags": [ { "Key": "Name", "Value": "dnb-dev-sg-db" } ]
    }
  ]
}
```

`"IpPermissionsEgress": []` is the goal. `"IpRanges": []` with a populated `UserIdGroupPairs` is the fingerprint of a correctly written, identity-based rule.

#### 5.3 Verification

```bash
cat > bin/sg-report.sh <<'SH'
#!/usr/bin/env bash
# Human-readable security group matrix + hygiene findings.
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
out = subprocess.run(["aws","ec2","describe-security-groups","--filters",
                      f"Name=vpc-id,Values={vpc}","--output","json"],
                     capture_output=True, text=True).stdout
sgs = json.loads(out or "{}").get("SecurityGroups", [])
byid = {g["GroupId"]: g["GroupName"] for g in sgs}
findings = []

def render(perms):
    rows = []
    for p in perms:
        proto = p.get("IpProtocol")
        proto = "ALL" if proto == "-1" else proto
        lo, hi = p.get("FromPort"), p.get("ToPort")
        port = "ALL" if lo is None else (str(lo) if lo == hi else f"{lo}-{hi}")
        srcs = [r["CidrIp"] for r in p.get("IpRanges", [])]
        srcs += [f"sg:{byid.get(u['GroupId'], u['GroupId'])}" for u in p.get("UserIdGroupPairs", [])]
        srcs += [f"pl:{x['PrefixListId']}" for x in p.get("PrefixListIds", [])]
        rows.append(f"{proto}/{port} <- {', '.join(srcs) or '(none)'}")
    return rows or ["(none)"]

for g in sorted(sgs, key=lambda x: x["GroupName"]):
    print(f"\n{g['GroupName']}  ({g['GroupId']})")
    print(f"  desc: {g['Description']}")
    for r in render(g["IpPermissions"]):
        print(f"  IN   {r}")
    for r in render(g.get("IpPermissionsEgress", [])):
        print(f"  OUT  {r}")

    for p in g["IpPermissions"]:
        for r in p.get("IpRanges", []):
            if r["CidrIp"] == "0.0.0.0/0":
                lo, hi = p.get("FromPort"), p.get("ToPort")
                if lo is None:
                    findings.append(f"{g['GroupName']}: ALL ports open to 0.0.0.0/0")
                elif any(lo <= q <= hi for q in (22, 3389)):
                    findings.append(f"{g['GroupName']}: SSH/RDP ({lo}-{hi}) open to 0.0.0.0/0")
        if not p.get("IpRanges") and not p.get("UserIdGroupPairs") and not p.get("PrefixListIds"):
            findings.append(f"{g['GroupName']}: rule with no source")
    for p in g["IpPermissions"] + g.get("IpPermissionsEgress", []):
        for coll in ("IpRanges", "UserIdGroupPairs"):
            for item in p.get(coll, []):
                if not item.get("Description"):
                    findings.append(f"{g['GroupName']}: undescribed rule ({coll})")

print("\n--- hygiene findings ---")
for f in sorted(set(findings)):
    print("  !", f)
if not findings:
    print("  none")
PY
SH
chmod +x bin/sg-report.sh
./bin/sg-report.sh | tee out/lab05-sg.txt
```

Expected (abridged):

```
dnb-dev-sg-app  (sg-0app…)
  desc: Statement generation workers: private app tier
  IN   tcp/8080 <- sg:dnb-dev-sg-web
  OUT  tcp/5432 <- sg:dnb-dev-sg-db
  OUT  tcp/443 <- sg:dnb-dev-sg-vpce
  OUT  tcp/443 <- 0.0.0.0/0

dnb-dev-sg-db  (sg-0db0…)
  desc: PostgreSQL data tier: isolated, no egress
  IN   tcp/5432 <- sg:dnb-dev-sg-app
  OUT  (none)

--- hygiene findings ---
  ! default: rule with no source            ← the default SG's self-reference has no description
```

#### 5.4 Break it

**Break 1 — try to write a deny rule.**

*AWS-correct verdict:* impossible. Security groups have no deny construct; there is no API for it.

```bash
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.32.7/32","Description":"deny this host"}]}]' >/dev/null
aws ec2 describe-security-groups --group-ids "$SG_DB" \
  --query 'SecurityGroups[0].IpPermissions[].[FromPort,IpRanges[].CidrIp,UserIdGroupPairs[].GroupId]' --output json
```

You have just **widened** access — the "deny this host" rule is an *allow*. Read the output and confirm. This is why "block a single IP" always means NACL, never security group.

```bash
# undo the accidental widening
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.32.7/32"}]}]' >/dev/null
```

**Break 2 — circular reference.**

*AWS-correct verdict:* **allowed and useful.** Two groups may reference each other; there is no ordering problem because security groups have no evaluation order.

```bash
aws ec2 authorize-security-group-ingress --group-id "$SG_APP" \
  --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":7946,\"ToPort\":7946,
    \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"cluster gossip between app nodes\"}]}]" >/dev/null
aws ec2 describe-security-groups --group-ids "$SG_APP" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`7946`]' --output json
```

A **self-referencing** group is the correct idiom for cluster peer traffic (Consul, Cassandra, Elasticsearch, Redis cluster bus). Keep this rule; it is legitimate.

**Break 3 — delete a security group that is referenced.**

*AWS-correct verdict:* rejected with `DependencyViolation`, because `sg-db`'s rule references `sg-app`.

```bash
aws ec2 delete-security-group --group-id "$SG_APP" 2>&1 | head -3
```

```
An error occurred (DependencyViolation) when calling the DeleteSecurityGroup operation:
resource sg-0app… has a dependent object
```

This is why §16's cleanup **revokes all rules first, then deletes groups**.

**Break 4 — exceed the rule budget (conceptual maths).**

*AWS-correct verdict:* rejected with `RulesPerSecurityGroupLimitExceeded` past 60 rules. Compute the cost of a badly written rule:

```bash
python3 - <<'PY'
branches = [f"203.0.113.{i}/32" for i in range(1, 41)]
print(f"CIDR-literal approach: {len(branches)} rules of your 60-rule inbound budget")
print("Prefix-list approach : 1 rule, but it consumes MaxEntries rules —")
print("                       so size MaxEntries to 45, not 200.")
PY
```

#### 5.5 Fix it

```bash
# Confirm the intended matrix survived the breaks
./bin/sg-report.sh | sed -n '1,40p'

# Assert the invariants that matter for the DNB design
cat > bin/assert-sg-invariants.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
sgs = json.loads(subprocess.run(
    ["aws","ec2","describe-security-groups","--filters",
     f"Name=vpc-id,Values={vpc}","--output","json"],
    capture_output=True, text=True).stdout or "{}").get("SecurityGroups", [])
by = {g["GroupName"]: g for g in sgs}
fail = 0
def check(label, cond):
    global fail
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond: fail = 1

db = by.get("dnb-dev-sg-db")
app = by.get("dnb-dev-sg-app")
web = by.get("dnb-dev-sg-web")
check("sg-db exists", db is not None)
if db:
    check("sg-db has NO egress rules", db.get("IpPermissionsEgress") == [])
    check("sg-db ingress uses only SG references (no CIDRs)",
          all(not p.get("IpRanges") for p in db["IpPermissions"]))
    check("sg-db allows exactly one ingress rule", len(db["IpPermissions"]) == 1)
if app:
    check("sg-app ingress uses only SG references",
          all(not p.get("IpRanges") for p in app["IpPermissions"]))
if web:
    open_admin = [p for p in web["IpPermissions"]
                  for r in p.get("IpRanges", [])
                  if r["CidrIp"] == "0.0.0.0/0"
                  and p.get("FromPort") is not None
                  and any(p["FromPort"] <= q <= p["ToPort"] for q in (22, 3389))]
    check("sg-web does not expose SSH/RDP to the internet", not open_admin)
sys.exit(fail)
PY
SH
chmod +x bin/assert-sg-invariants.sh
./bin/assert-sg-invariants.sh
```

#### 5.6 Recap of Lab 5

* Security groups are **allow-only, stateful, ENI-scoped, order-independent**, and can reference other groups.
* Reference security groups, not CIDRs, for all intra-VPC traffic — it scales, it self-documents, and it survives re-addressing.
* A new group has **no ingress** and **allow-all egress**. Replace that egress deliberately; a data tier needs none.
* You cannot express "deny" in a security group. Widening a rule to "block" a host does the opposite.
* Self-references are legitimate and are the idiom for cluster peer traffic.
* Referenced groups cannot be deleted — revoke rules before deleting.

---

### Lab 6 — Network ACLs: stateless filtering and the ephemeral-port trap

**Objective.** Build an explicit NACL for the data tier, learn correct rule numbering, and *prove* — using `reach.py` — that omitting the ephemeral return rule breaks the connection even though the security groups are perfect.

**Prerequisites.** Labs 1–5, and `bin/reach.py` from §0.6.

**Architecture after this lab.**

```
  ┌───────────────── acl-data (associated with data-1a and data-1b) ────────────────┐
  │ INGRESS                                                                         │
  │   100  ALLOW  tcp 5432        from 10.20.32.0/20  (app-1a)                       │
  │   110  ALLOW  tcp 5432        from 10.20.48.0/20  (app-1b)                       │
  │ 32766  DENY   all             from 0.0.0.0/0      (explicit, for auditability)   │
  │     *  DENY   all             (implicit, always last)                            │
  │                                                                                  │
  │ EGRESS                                                                           │
  │   100  ALLOW  tcp 1024-65535  to   10.20.32.0/20  ← RETURN traffic for app-1a    │
  │   110  ALLOW  tcp 1024-65535  to   10.20.48.0/20  ← RETURN traffic for app-1b    │
  │ 32766  DENY   all             to   0.0.0.0/0                                     │
  │     *  DENY   all                                                                │
  └──────────────────────────────────────────────────────────────────────────────────┘

  Note: NACLs cannot reference security groups. CIDRs are unavoidable here —
  which is exactly why NACLs are coarse policy and SGs are fine policy.
```

#### 6.1 Implementation

!!! danger "Create the rules BEFORE associating the NACL"
    A brand-new NACL denies everything in both directions. If you associate it first, the subnet is black-holed until you finish typing. Build, then associate.

```bash
ACL_DATA=$(aws ec2 create-network-acl --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=network-acl,Tags=[
      {Key=Name,Value=dnb-dev-acl-data},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=data}]' \
  --query 'NetworkAcl.NetworkAclId' --output text)
setid ACL_DATA "$ACL_DATA"

# Confirm a fresh NACL is deny-all
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries[].[RuleNumber,Egress,RuleAction,CidrBlock,Protocol]' --output text
```

Expected — only the two implicit `*` rules, both DENY:

```
32767	False	deny	0.0.0.0/0	-1
32767	True	deny	0.0.0.0/0	-1
```

!!! note "The `*` rule shows as rule number 32767"
    The console renders the final catch-all as `*`; the API reports `RuleNumber: 32767`. You cannot create, modify or delete it. The highest rule number **you** may use is `32766`.

```bash
CIDR_APP_1A=10.20.32.0/20
CIDR_APP_1B=10.20.48.0/20

# --- INGRESS: only PostgreSQL, only from the app subnets --------------------
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 100 --protocol tcp --port-range From=5432,To=5432 \
  --cidr-block "$CIDR_APP_1A" --rule-action allow

aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 110 --protocol tcp --port-range From=5432,To=5432 \
  --cidr-block "$CIDR_APP_1B" --rule-action allow

aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 32766 --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny

# --- EGRESS: the RETURN path, on ephemeral ports ---------------------------
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block "$CIDR_APP_1A" --rule-action allow

aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 110 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block "$CIDR_APP_1B" --rule-action allow

aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 32766 --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny
```

**Parameter explanation**

| Parameter | Meaning | Notes |
|---|---|---|
| `--ingress` / `--egress` | Which direction list the entry joins | Mutually exclusive; the same rule number may exist once in each direction |
| `--rule-number` | 1–32766; evaluation order | **First match wins, then evaluation stops.** Leave gaps (100, 110, 120) so you can insert later |
| `--protocol` | `-1` all, `tcp`, `udp`, `icmp`, or an IANA number | With `-1`, port ranges are ignored — all ports |
| `--port-range From=,To=` | Destination port for ingress; **source** port for egress | For the return path you match the *client's ephemeral* port, not 5432 |
| `--cidr-block` | Peer CIDR | NACLs cannot reference security groups |
| `--rule-action` | `allow` \| `deny` | The only place in VPC where `deny` exists |

!!! danger "The egress rule is about the CLIENT'S port, not the server's"
    Egress rule 100 allows TCP **1024–65535** to the app subnet — not TCP 5432. The database replies *from* 5432 *to* the client's ephemeral port, so the egress rule must match the **destination port of the reply**, which is the client's ephemeral port. Getting this backwards produces a connection that opens and then hangs, and it is the single most common NACL bug in production.

Associate the NACL — `ReplaceNetworkAclAssociation` swaps the subnet from the default NACL to ours:

```bash
for s in "$SUBNET_DATA_1A" "$SUBNET_DATA_1B"; do
  assoc=$(aws ec2 describe-network-acls \
    --filters "Name=association.subnet-id,Values=$s" \
    --query "NetworkAcls[0].Associations[?SubnetId=='$s'].NetworkAclAssociationId | [0]" \
    --output text)
  echo "subnet $s currently associated as $assoc"
  aws ec2 replace-network-acl-association \
    --association-id "$assoc" --network-acl-id "$ACL_DATA" \
    --query 'NewAssociationId' --output text
done
```

!!! note "There is no `disassociate-network-acl`"
    Every subnet must be associated with exactly one NACL, so associations are only ever **replaced**. To "remove" a custom NACL, replace the association back to the VPC's default NACL — which is exactly what §16's cleanup does before deleting `acl-data`.

#### 6.2 Expected output

```bash
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" --output json
```

```json
{
  "NetworkAcls": [
    {
      "Associations": [
        {
          "NetworkAclAssociationId": "aclassoc-0aa11bb22cc33dd44",
          "NetworkAclId": "acl-0abc123def4567890",
          "SubnetId": "subnet-0da7a0da7a0da7a00"
        },
        {
          "NetworkAclAssociationId": "aclassoc-0bb22cc33dd44ee55",
          "NetworkAclId": "acl-0abc123def4567890",
          "SubnetId": "subnet-0da7b0da7b0da7b00"
        }
      ],
      "Entries": [
        { "CidrBlock": "10.20.32.0/20", "Egress": false, "PortRange": {"From": 5432, "To": 5432},
          "Protocol": "6", "RuleAction": "allow", "RuleNumber": 100 },
        { "CidrBlock": "10.20.48.0/20", "Egress": false, "PortRange": {"From": 5432, "To": 5432},
          "Protocol": "6", "RuleAction": "allow", "RuleNumber": 110 },
        { "CidrBlock": "0.0.0.0/0", "Egress": false, "Protocol": "-1",
          "RuleAction": "deny", "RuleNumber": 32766 },
        { "CidrBlock": "0.0.0.0/0", "Egress": false, "Protocol": "-1",
          "RuleAction": "deny", "RuleNumber": 32767 },
        { "CidrBlock": "10.20.32.0/20", "Egress": true, "PortRange": {"From": 1024, "To": 65535},
          "Protocol": "6", "RuleAction": "allow", "RuleNumber": 100 },
        { "CidrBlock": "10.20.48.0/20", "Egress": true, "PortRange": {"From": 1024, "To": 65535},
          "Protocol": "6", "RuleAction": "allow", "RuleNumber": 110 },
        { "CidrBlock": "0.0.0.0/0", "Egress": true, "Protocol": "-1",
          "RuleAction": "deny", "RuleNumber": 32766 },
        { "CidrBlock": "0.0.0.0/0", "Egress": true, "Protocol": "-1",
          "RuleAction": "deny", "RuleNumber": 32767 }
      ],
      "IsDefault": false,
      "NetworkAclId": "acl-0abc123def4567890",
      "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
      "Tags": [ { "Key": "Name", "Value": "dnb-dev-acl-data" } ]
    }
  ]
}
```

`"Protocol": "6"` is TCP — the API returns IANA numbers even when you supplied `tcp`.

#### 6.3 Verification — with the reachability evaluator

This is the moment the evaluator earns its keep. Ask: *would AWS permit the app tier to reach the database?*

```bash
python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A"  --to-ip 10.20.64.10 \
  --port 5432 --proto tcp \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tee out/lab06-reach-app-to-db.txt
```

Expected:

```
FLOW  10.20.32.50 (subnet-0app…/sg-0app…)  ->  10.20.64.10:5432/tcp (subnet-0dat…/sg-0db0…)

  1. ALLOW  src SG egress (sg-0app…)                              egress rule tcp:5432 sg sg-0db0…
  2. ALLOW  src NACL egress (acl-0default…)                       rule 100 allow 0.0.0.0/0 proto=-1
  3. ALLOW  route table rtb-0priv1a… [explicit]                   10.20.0.0/16 -> GatewayId=local
  4. ALLOW  dst NACL ingress (acl-0abc123…)                       rule 100 allow 10.20.32.0/20 proto=6
  5. ALLOW  dst SG ingress (sg-0db0…)                             ingress rule tcp:5432 sg sg-0app…
  6. ALLOW  dst NACL egress (return, ephemeral 1024-65535)        rule 100 allow 10.20.32.0/20 proto=6
  7. ALLOW  src NACL ingress (return, ephemeral 1024-65535)       rule 100 allow 0.0.0.0/0 proto=-1

AWS VERDICT: PERMITTED
```

Read step 3 carefully: the route chosen is `10.20.0.0/16 → local`, not the `0.0.0.0/0 → nat` route, because `local` is more specific. That is longest-prefix match doing its job, and it is why intra-VPC traffic never touches the NAT gateway.

Now prove the design is actually restrictive. Every one of these should be **BLOCKED**:

```bash
echo "=== negative tests: all of these MUST be blocked ==="

# a) web tier straight to the database, skipping the app tier
python3 bin/reach.py --from-subnet "$SUBNET_PUBLIC_1A" --from-ip 10.20.0.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 5432 \
  --src-sg "$SG_WEB" --dst-sg "$SG_DB" | tail -4

# b) app tier to the database on the wrong port
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 22 \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tail -4

# c) database initiating an outbound connection to the internet (exfiltration)
python3 bin/reach.py --from-subnet "$SUBNET_DATA_1A" --from-ip 10.20.64.10 \
  --to-ip 203.0.113.9 --port 443 \
  --src-sg "$SG_DB" | tail -4
```

Test (c) is the important one. It should fail at **two** independent steps — `sg-db` has no egress rule, and `rtb-data` has no route to `203.0.113.9`. Defence in depth means either failure alone would suffice.

#### 6.4 Break it

**Break 1 — delete the ephemeral egress rule.**

*AWS-correct verdict:* the TCP handshake completes outbound but the reply is dropped, so the client hangs and eventually times out. Security groups are unchanged and perfect; the NACL is the culprit.

```bash
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 100

python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A"  --to-ip 10.20.64.10 \
  --port 5432 --src-sg "$SG_APP" --dst-sg "$SG_DB"
```

Expected: steps 1–5 still ALLOW; **step 6 DENY**; verdict `BLOCKED`.

```
  6. DENY   dst NACL egress (return, ephemeral 1024-65535)   rule 32766 deny 0.0.0.0/0 proto=-1

AWS VERDICT: BLOCKED
```

!!! tip "This is the signature you must learn to recognise"
    In production this presents as: *"telnet to port 5432 hangs"*, *"the connection pool fills with connections stuck in SYN_SENT"*, or in flow logs as an outbound `ACCEPT` with a matching `REJECT` on the return flow. If the security groups look right and traffic is one-directional, it is a stateless NACL missing its ephemeral rule — almost every time.

**Break 2 — rule ordering: a deny in front of an allow.**

*AWS-correct verdict:* first match wins, so a broad deny at rule 50 defeats the allow at rule 100 entirely.

```bash
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 50 --protocol -1 --cidr-block 10.20.32.0/20 --rule-action deny

python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A"  --to-ip 10.20.64.10 \
  --port 5432 --src-sg "$SG_APP" --dst-sg "$SG_DB" | sed -n '4,6p'
```

Expected: `4. DENY  dst NACL ingress … rule 50 deny 10.20.32.0/20`. Rule 100 is never evaluated. Contrast with security groups, where adding a rule can only ever *widen* access.

**Break 3 — associate a fresh, empty NACL.**

*AWS-correct verdict:* total blackout in both directions.

```bash
ACL_EMPTY=$(aws ec2 create-network-acl --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=network-acl,Tags=[{Key=Name,Value=dnb-dev-acl-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'NetworkAcl.NetworkAclId' --output text)
setid ACL_EMPTY "$ACL_EMPTY"

ASSOC_1B=$(aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=$SUBNET_DATA_1B" \
  --query "NetworkAcls[0].Associations[?SubnetId=='$SUBNET_DATA_1B'].NetworkAclAssociationId | [0]" \
  --output text)
setid ASSOC_1B "$ASSOC_1B"

aws ec2 replace-network-acl-association --association-id "$ASSOC_1B" --network-acl-id "$ACL_EMPTY" \
  --query 'NewAssociationId' --output text

python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1B" --from-ip 10.20.48.50 \
  --to-subnet "$SUBNET_DATA_1B"  --to-ip 10.20.80.10 \
  --port 5432 --src-sg "$SG_APP" --dst-sg "$SG_DB" | tail -5
```

**Break 4 — exceed the rule budget.**

*AWS-correct verdict:* rejected at 20 rules per direction with `NetworkAclEntryLimitExceeded`.

```bash
i=0
for n in $(seq 200 10 480); do
  aws ec2 create-network-acl-entry --network-acl-id "$ACL_EMPTY" --ingress \
    --rule-number "$n" --protocol tcp --port-range From=443,To=443 \
    --cidr-block "198.51.100.$((n % 250))/32" --rule-action allow 2>&1 | head -1
  i=$((i+1))
done
echo "attempted $i additional rules"
aws ec2 describe-network-acls --network-acl-ids "$ACL_EMPTY" \
  --query 'length(NetworkAcls[0].Entries[?Egress==`false`])' --output text
```

In real AWS this fails once you reach 20 ingress entries. Note how quickly a 20-rule budget disappears — proof that NACLs cannot carry fine-grained policy.

#### 6.5 Fix it

```bash
# 1. Restore the ephemeral egress rule
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block 10.20.32.0/20 --rule-action allow

# 2. Remove the misordered deny
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --ingress --rule-number 50

# 3. Put data-1b back on the correct NACL and destroy the probe NACL
aws ec2 replace-network-acl-association --association-id "$ASSOC_1B" --network-acl-id "$ACL_DATA" \
  --query 'NewAssociationId' --output text
aws ec2 delete-network-acl --network-acl-id "$ACL_EMPTY"
grep -v -e '^export ACL_EMPTY=' -e '^export ASSOC_1B=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset ACL_EMPTY ASSOC_1B

# 4. Re-run the full positive and negative suite
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 5432 \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tail -3
python3 bin/reach.py --from-subnet "$SUBNET_APP_1B" --from-ip 10.20.48.50 \
  --to-subnet "$SUBNET_DATA_1B" --to-ip 10.20.80.10 --port 5432 \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tail -3
```

**Permanent fix — a NACL linter.** Every allow rule in one direction should have a matching ephemeral rule in the other:

```bash
cat > bin/lint-nacl.sh <<'SH'
#!/usr/bin/env bash
# Warn about ingress allows with no plausible ephemeral egress counterpart.
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys, ipaddress
vpc = sys.argv[1]
acls = json.loads(subprocess.run(
    ["aws","ec2","describe-network-acls","--filters",
     f"Name=vpc-id,Values={vpc}","--output","json"],
    capture_output=True, text=True).stdout or "{}").get("NetworkAcls", [])
warn = 0
for a in acls:
    name = next((t["Value"] for t in a.get("Tags",[]) if t["Key"]=="Name"), a["NetworkAclId"])
    ing = [e for e in a["Entries"] if not e["Egress"] and e["RuleAction"]=="allow"
           and e["RuleNumber"] < 32767]
    egr = [e for e in a["Entries"] if e["Egress"] and e["RuleAction"]=="allow"
           and e["RuleNumber"] < 32767]
    for e in ing:
        peer = e.get("CidrBlock")
        if not peer:
            continue
        covered = False
        for g in egr:
            gc = g.get("CidrBlock")
            if not gc:
                continue
            try:
                overlap = (ipaddress.ip_network(peer).overlaps(ipaddress.ip_network(gc)))
            except ValueError:
                continue
            pr = g.get("PortRange")
            eph = (g["Protocol"] == "-1") or (pr and pr["From"] <= 1024 and pr["To"] >= 65535)
            if overlap and eph:
                covered = True
                break
        if not covered:
            warn += 1
            print(f"  WARN {name}: ingress allow rule {e['RuleNumber']} from {peer} "
                  f"has no ephemeral egress counterpart -> return traffic will be DROPPED")
print("  no findings" if warn == 0 else f"\n  {warn} finding(s)")
PY
SH
chmod +x bin/lint-nacl.sh
./bin/lint-nacl.sh
```

#### 6.6 Recap of Lab 6

* NACLs are **stateless, numbered, first-match-wins, subnet-scoped**, and are the only place `deny` exists.
* A new NACL denies everything. Write rules before associating.
* For every allow in one direction you need an **ephemeral-range allow in the other**. AWS recommends `1024–65535`.
* Egress rules for return traffic match the **client's ephemeral port**, not the server's service port.
* Rule 32767 (`*`) is implicit and immutable; the highest number you may use is 32766. Add an explicit `32766 deny all` so your intent appears in audits.
* The 20-rule budget forces NACLs to remain coarse policy. Fine policy belongs in security groups.

---

### Lab 7 — VPC endpoints: keeping AWS API traffic off the internet

**Objective.** Add an S3 **gateway** endpoint to the private and data route tables and an STS **interface** endpoint in the app subnets, apply a restrictive endpoint policy, and explain how each changes the traffic path.

**Prerequisites.** Labs 1–6.

**Architecture after this lab.**

```
  ┌──────────── rtb-data (isolated) ───────────────┐
  │ 10.20.0.0/16 → local                           │
  │ pl-…(com.amazonaws.us-east-1.s3) → vpce-s3     │  ← added by the gateway endpoint
  │ NO 0.0.0.0/0                                   │
  └────────────────────────────────────────────────┘
  Result: the data tier can reach S3 — and nothing else. No IGW, no NAT.

  ┌──────────── subnet-app-1a / app-1b ────────────┐
  │  eni 10.20.32.x   ◄── vpce-sts interface ENI   │
  │  sg-vpce: allow 443 from sg-app, sg-web        │
  │  private DNS: sts.us-east-1.amazonaws.com      │
  │               resolves to 10.20.32.x           │
  └────────────────────────────────────────────────┘
```

#### 7.1 Implementation — the gateway endpoint (S3)

```bash
# Which endpoint services does this build advertise?
aws ec2 describe-vpc-endpoint-services \
  --query 'ServiceDetails[].{Service:ServiceName,Types:ServiceType[].ServiceType}' \
  --output table 2>/dev/null | head -30 \
  || echo "note: describe-vpc-endpoint-services may be unimplemented; continue anyway"
```

```bash
cat > policies/vpce-s3-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOnlyDnbBuckets",
      "Effect": "Allow",
      "Principal": "*",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*",
        "arn:aws:s3:::dnb-audit-logs-dev",
        "arn:aws:s3:::dnb-audit-logs-dev/*"
      ]
    }
  ]
}
JSON
python3 -c "import json;json.load(open('policies/vpce-s3-policy.json'));print('policy parses OK')"
```

```bash
VPCE_S3=$(aws ec2 create-vpc-endpoint \
  --vpc-id "$VPC_ID" \
  --vpc-endpoint-type Gateway \
  --service-name "com.amazonaws.${AWS_DEFAULT_REGION:-us-east-1}.s3" \
  --route-table-ids "$RTB_PRIVATE_1A" "$RTB_PRIVATE_1B" "$RTB_DATA" \
  --policy-document file://policies/vpce-s3-policy.json \
  --tag-specifications 'ResourceType=vpc-endpoint,Tags=[
      {Key=Name,Value=dnb-dev-vpce-s3},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'VpcEndpoint.VpcEndpointId' --output text)
setid VPCE_S3 "$VPCE_S3"
```

**Parameter explanation**

| Parameter | Meaning | Notes |
|---|---|---|
| `--vpc-endpoint-type Gateway` | Route-table-based endpoint | **Only S3 and DynamoDB** support this type. Free of charge |
| `--service-name com.amazonaws.<region>.s3` | Service to reach | Region-specific. Getting the region wrong yields `InvalidServiceName` |
| `--route-table-ids` | Tables that receive the prefix-list route | This is the *entire mechanism*. Forgetting a table means those subnets do not use the endpoint |
| `--policy-document` | Endpoint policy | Constrains what may pass. Omit it and the default is `"Action":"*"` on `"Resource":"*"` |

Confirm that the prefix-list route appeared **automatically** in all three tables:

```bash
for rtb in "$RTB_PRIVATE_1A" "$RTB_PRIVATE_1B" "$RTB_DATA"; do
  echo "--- $rtb ---"
  aws ec2 describe-route-tables --route-table-ids "$rtb" \
    --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,State]' \
    --output text
done
```

Expected for `rtb-data` — note the destination is a **prefix list**, not a CIDR:

```
--- rtb-0data… ---
10.20.0.0/16	None	local	active
None	pl-63a5400a	vpce-0abc123…	active
```

!!! note "The gateway endpoint route is managed for you"
    You did not call `create-route`. Adding or removing a route table id on the endpoint adds or removes the prefix-list route automatically. Do not hand-edit it.

#### 7.2 Implementation — the interface endpoint (STS)

```bash
VPCE_STS=$(aws ec2 create-vpc-endpoint \
  --vpc-id "$VPC_ID" \
  --vpc-endpoint-type Interface \
  --service-name "com.amazonaws.${AWS_DEFAULT_REGION:-us-east-1}.sts" \
  --subnet-ids "$SUBNET_APP_1A" "$SUBNET_APP_1B" \
  --security-group-ids "$SG_VPCE" \
  --private-dns-enabled \
  --tag-specifications 'ResourceType=vpc-endpoint,Tags=[
      {Key=Name,Value=dnb-dev-vpce-sts},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'VpcEndpoint.VpcEndpointId' --output text)
setid VPCE_STS "$VPCE_STS"
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--vpc-endpoint-type Interface` | ENI-based (AWS PrivateLink) | Charged per ENI-hour plus per GB |
| `--subnet-ids` | One ENI created per subnet | Choose one subnet **per AZ** for resilience; these ENIs block subnet deletion |
| `--security-group-ids` | Firewall on the endpoint ENIs | **Must allow inbound 443 from clients** or the endpoint silently times out |
| `--private-dns-enabled` | Overrides `sts.<region>.amazonaws.com` inside the VPC to resolve to the ENI IPs | Requires `enableDnsSupport` **and** `enableDnsHostnames` on the VPC — which we set in Lab 1 |

```bash
aws ec2 describe-vpc-endpoints --vpc-endpoint-ids "$VPCE_STS" \
  --query 'VpcEndpoints[0].{Id:VpcEndpointId,Type:VpcEndpointType,State:State,
           PrivateDns:PrivateDnsEnabled,Subnets:SubnetIds,SGs:Groups[].GroupId,
           ENIs:NetworkInterfaceIds,DnsNames:DnsEntries[].DnsName}' --output json \
  | tee out/lab07-vpce-sts.json
```

Expected (abridged):

```json
{
  "Id": "vpce-0sts123456789abcd",
  "Type": "Interface",
  "State": "available",
  "PrivateDns": true,
  "Subnets": ["subnet-0app1a…", "subnet-0app1b…"],
  "SGs": ["sg-0vpce…"],
  "ENIs": ["eni-0aaa…", "eni-0bbb…"],
  "DnsNames": [
    "vpce-0sts123456789abcd-xxxxxxxx.sts.us-east-1.vpce.amazonaws.com",
    "sts.us-east-1.amazonaws.com"
  ]
}
```

The presence of `sts.us-east-1.amazonaws.com` in `DnsEntries` is what private DNS means: existing SDK code needs **no change** to start using the endpoint.

#### 7.3 Verification

```bash
cat > bin/endpoint-report.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?}"
echo "=== endpoints in this VPC ==="
aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[].{Name:Tags[?Key==`Name`]|[0].Value,Type:VpcEndpointType,
           Service:ServiceName,State:State,RouteTables:RouteTableIds,Subnets:SubnetIds}' \
  --output table

echo
echo "=== which route tables carry a prefix-list (gateway endpoint) route? ==="
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Table:Tags[?Key==`Name`]|[0].Value,
           PrefixRoutes:Routes[?DestinationPrefixListId!=null].[DestinationPrefixListId,GatewayId]}' \
  --output json

echo
echo "=== does the data tier now have ANY non-local reachability? ==="
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Tier,Values=data" \
  --query 'RouteTables[].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,State]' \
  --output text
SH
chmod +x bin/endpoint-report.sh
./bin/endpoint-report.sh | tee out/lab07-endpoints.txt
```

**Reason about the path change explicitly.** Fill this table in your lab report:

| Caller | Target | Before endpoints | After endpoints |
|---|---|---|---|
| app-1a instance | `dnb-statements-dev` (S3) | app subnet → `0.0.0.0/0` → NAT-1a → IGW → public S3 endpoint. **Billed NAT data processing.** | app subnet → prefix-list route → `vpce-s3`. No NAT, no IGW, **free** |
| data-1a instance | `dnb-statements-dev` (S3) | **impossible** — `rtb-data` has no default route | prefix-list route → `vpce-s3`. Works, and only for our two buckets |
| app-1a instance | `sts.us-east-1.amazonaws.com` | NAT → IGW → public STS | private DNS → endpoint ENI in the same subnet |
| data-1a instance | `sts.us-east-1.amazonaws.com` | impossible | still impossible — we did **not** put an STS endpoint in the data subnets. Add one if the DB needs IAM authentication |

That last row is a design decision, not an oversight. State it as such.

#### 7.4 Break it

**Break 1 — an interface endpoint whose security group blocks 443.**

*AWS-correct verdict:* the endpoint reaches `available`, DNS resolves, and every API call **times out**. No error tells you why. This is the highest-frustration failure mode in PrivateLink.

```bash
SG_BROKEN=$(aws ec2 create-security-group \
  --group-name dnb-dev-sg-vpce-broken \
  --description "Probe: endpoint SG with no ingress" \
  --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=dnb-dev-sg-vpce-broken},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'GroupId' --output text)
setid SG_BROKEN "$SG_BROKEN"

aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_STS" \
  --add-security-group-ids "$SG_BROKEN" --remove-security-group-ids "$SG_VPCE" 2>&1 | head -3

# Reason about it: a new SG has NO ingress rules.
python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_APP_1A"   --to-ip 10.20.32.200 \
  --port 443 --src-sg "$SG_APP" --dst-sg "$SG_BROKEN" | tail -5
```

Expected: `5. DENY  dst SG ingress … no matching ingress rule -> IMPLICIT DENY`.

**Break 2 — an endpoint policy that is too narrow.**

*AWS-correct verdict:* the API call is refused with `AccessDenied` mentioning the VPC endpoint, even though the caller's IAM policy allows it.

```bash
cat > policies/vpce-s3-toonarrow.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OnlyOneBucketOnly",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::dnb-audit-logs-dev/*"
    }
  ]
}
JSON
python3 -c "import json;json.load(open('policies/vpce-s3-toonarrow.json'));print('parses OK')"

aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" \
  --policy-document file://policies/vpce-s3-toonarrow.json 2>&1 | head -3
```

*Track B reasoning:* a `PutObject` to `dnb-statements-dev` from a private subnet now fails. Where does the failure appear? Not in the IAM policy, not in the bucket policy, but in the **endpoint** policy — a fourth place to look that most engineers forget. Write in your report the full list of places an S3 `AccessDenied` can originate: identity policy, permissions boundary, SCP, bucket policy, bucket ACL, **VPC endpoint policy**, KMS key policy, Block Public Access.

**Break 3 — remove a route table from the gateway endpoint.**

*AWS-correct verdict:* the prefix-list route vanishes from that table, and the data tier loses S3 access entirely — with no error anywhere.

```bash
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" \
  --remove-route-table-ids "$RTB_DATA" 2>&1 | head -3
aws ec2 describe-route-tables --route-table-ids "$RTB_DATA" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId]' --output text
```

#### 7.5 Fix it

```bash
# 1. Restore the correct endpoint security group and delete the probe group
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_STS" \
  --add-security-group-ids "$SG_VPCE" --remove-security-group-ids "$SG_BROKEN" 2>&1 | head -2
aws ec2 delete-security-group --group-id "$SG_BROKEN" 2>&1 | head -2
grep -v '^export SG_BROKEN=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset SG_BROKEN

# 2. Restore the correct endpoint policy
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" \
  --policy-document file://policies/vpce-s3-policy.json 2>&1 | head -2

# 3. Restore the data tier's route table on the endpoint
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" \
  --add-route-table-ids "$RTB_DATA" 2>&1 | head -2

# 4. Verify
./bin/endpoint-report.sh | tail -12
```

#### 7.6 Recap of Lab 7

* A **gateway** endpoint is a route-table entry with a **prefix-list** destination; S3 and DynamoDB only; free; add one to every VPC on day one.
* An **interface** endpoint is an ENI with security groups; a new SG has no ingress, so **you must allow 443** or calls time out silently.
* `--private-dns-enabled` makes existing SDK code use the endpoint with no changes, and requires both VPC DNS attributes.
* Endpoint policies are a distinct, easily forgotten place an `AccessDenied` can come from — and a genuine anti-exfiltration control when paired with `aws:SourceVpc` on the bucket policy.
* Endpoints let an **isolated** subnet reach exactly the AWS services you choose, and nothing else. That is how regulated data tiers are built.

---

### Lab 8 — ENIs, instances, and subnet IP exhaustion

**Objective.** Place real ENIs into the topology, observe `AvailableIpAddressCount` decrease, attach a secondary ENI, associate an Elastic IP, and hit a subnet-exhaustion error deliberately.

**Prerequisites.** Labs 1–7. Probe `run-instances` and `create-network-interface` support first.

```bash
grep -E 'run-instances|network-interface' out/support-matrix.tsv || \
  echo "note: not probed; run bin/probe-vpc-support.sh again if unsure"
```

**Architecture after this lab.**

```
  subnet-app-1a  10.20.32.0/20     free: 4091 → 4088
   ├── i-app1  eni0 10.20.32.10  sg-app          (primary, DeleteOnTermination)
   │            eni1 10.20.32.11  sg-app         (secondary, survives termination)
   └── (interface endpoint ENIs from Lab 7 also live here)

  subnet-public-1a 10.20.0.0/20
   └── i-bastionless  eni0 10.20.0.10  sg-web  + EIP 52.x.x.x
       (we do NOT open SSH; §9 explains the SSM alternative)

  subnet-probe   10.20.200.0/28    free: 11 → 0  → RunInstances FAILS
```

#### 8.1 Implementation

```bash
# A key pair, so the pattern is complete — we will not actually SSH in
aws ec2 create-key-pair --key-name dnb-dev-key \
  --tag-specifications 'ResourceType=key-pair,Tags=[{Key=Name,Value=dnb-dev-key},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'KeyMaterial' --output text > ~/vpc-lab/out/dnb-dev-key.pem 2>/dev/null \
  && chmod 400 ~/vpc-lab/out/dnb-dev-key.pem \
  && echo "key pair created" \
  || echo "note: create-key-pair may be unsupported or the key may already exist"

# Find any AMI this build offers
AMI_ID=$(aws ec2 describe-images --query 'Images[0].ImageId' --output text 2>/dev/null)
[ -z "$AMI_ID" ] || [ "$AMI_ID" = "None" ] && AMI_ID="ami-12345678"
setid AMI_ID "$AMI_ID"
echo "using AMI $AMI_ID"
```

!!! note "AMI ids in an emulator are fictional"
    Floci does not host real machine images. `describe-images` may return a synthetic entry or nothing. Any id is accepted, and no operating system boots. Everything in this lab is therefore **Track A**: we are validating *ENI placement and address accounting*, not compute.

```bash
cat > out/userdata.sh <<'UD'
#!/bin/bash
# DNB statement worker bootstrap (illustrative; nothing boots in Floci)
set -euo pipefail
dnf install -y postgresql16 awscli-2 || true
cat >/etc/dnb/worker.env <<CONF
DB_HOST=dnb-statements.cluster-xxxx.us-east-1.rds.amazonaws.com
DB_PORT=5432
S3_BUCKET=dnb-statements-dev
AWS_STS_REGIONAL_ENDPOINTS=regional
CONF
systemctl enable --now dnb-statement-worker
UD

INST_APP=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t3.micro \
  --subnet-id "$SUBNET_APP_1A" \
  --security-group-ids "$SG_APP" \
  --private-ip-address 10.20.32.10 \
  --key-name dnb-dev-key \
  --user-data file://out/userdata.sh \
  --tag-specifications 'ResourceType=instance,Tags=[
      {Key=Name,Value=dnb-dev-app-1},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=app}]' \
  --query 'Instances[0].InstanceId' --output text)
setid INST_APP "$INST_APP"
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--subnet-id` | Placement, and therefore AZ | Determines which route table and NACL apply |
| `--security-group-ids` | SGs for the primary ENI | Ids, not names, when the instance is in a non-default VPC |
| `--private-ip-address 10.20.32.10` | Pin the primary IP | Must be free and inside the subnet; the 5 reserved addresses are rejected |
| `--user-data file://…` | Bootstrap script | Base64-encoded by the CLI; readable via instance metadata, so **never put secrets here** |
| `--key-name` | SSH public key installed by cloud-init | We create it for completeness; §9 argues for SSM instead |

A secondary ENI, to make the ENI-as-atom point concrete:

```bash
ENI_SECOND=$(aws ec2 create-network-interface \
  --subnet-id "$SUBNET_APP_1A" \
  --groups "$SG_APP" \
  --private-ip-address 10.20.32.11 \
  --description "dnb-dev-app-1 management interface" \
  --tag-specifications 'ResourceType=network-interface,Tags=[
      {Key=Name,Value=dnb-dev-eni-app-1-mgmt},{Key=Project,Value=CoreBanking},
      {Key=ManagedBy,Value=floci-lab},{Key=Owner,Value=platform-team}]' \
  --query 'NetworkInterface.NetworkInterfaceId' --output text)
setid ENI_SECOND "$ENI_SECOND"

aws ec2 attach-network-interface \
  --network-interface-id "$ENI_SECOND" \
  --instance-id "$INST_APP" \
  --device-index 1 2>&1 | head -3
```

An instance in the public subnet, with an Elastic IP:

```bash
INST_WEB=$(aws ec2 run-instances \
  --image-id "$AMI_ID" --instance-type t3.micro \
  --subnet-id "$SUBNET_PUBLIC_1A" --security-group-ids "$SG_WEB" \
  --private-ip-address 10.20.0.10 \
  --tag-specifications 'ResourceType=instance,Tags=[
      {Key=Name,Value=dnb-dev-web-1},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=public}]' \
  --query 'Instances[0].InstanceId' --output text)
setid INST_WEB "$INST_WEB"

EIP_WEB=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=dnb-dev-eip-web-1},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'AllocationId' --output text)
setid EIP_WEB "$EIP_WEB"

aws ec2 associate-address --allocation-id "$EIP_WEB" --instance-id "$INST_WEB" \
  --query 'AssociationId' --output text
```

#### 8.2 Expected output

```bash
aws ec2 describe-instances --instance-ids "$INST_APP" \
  --query 'Reservations[0].Instances[0].{Id:InstanceId,State:State.Name,Subnet:SubnetId,
           AZ:Placement.AvailabilityZone,Priv:PrivateIpAddress,Pub:PublicIpAddress,
           SGs:SecurityGroups[].GroupName,
           ENIs:NetworkInterfaces[].{Eni:NetworkInterfaceId,Idx:Attachment.DeviceIndex,Ip:PrivateIpAddress,DoT:Attachment.DeleteOnTermination}}' \
  --output json
```

```json
{
  "Id": "i-0123456789abcdef0",
  "State": "running",
  "Subnet": "subnet-0app1a00000000000",
  "AZ": "us-east-1a",
  "Priv": "10.20.32.10",
  "Pub": null,
  "SGs": ["dnb-dev-sg-app"],
  "ENIs": [
    { "Eni": "eni-0aaa000000000000a", "Idx": 0, "Ip": "10.20.32.10", "DoT": true },
    { "Eni": "eni-0bbb000000000000b", "Idx": 1, "Ip": "10.20.32.11", "DoT": false }
  ]
}
```

Two things to notice. `Pub: null` — correct, because `MapPublicIpOnLaunch` is `false` on app subnets. And `DoT` differs between device index 0 and 1: the primary ENI dies with the instance, the secondary survives and must be deleted explicitly (a classic leak).

#### 8.3 Verification

```bash
# Address accounting: how many addresses has each subnet actually consumed?
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets,&CidrBlock)[].{Name:Tags[?Key==`Name`]|[0].Value,
           CIDR:CidrBlock,Free:AvailableIpAddressCount}' --output table

# Who exactly is consuming them?
aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Subnet:SubnetId,
           Ip:PrivateIpAddress,Status:Status,Desc:Description,
           SGs:Groups[].GroupName}' --output table | tee out/lab08-enis.txt
```

Compute expected consumption yourself before you look:

```bash
python3 - <<'PY'
total = 4096
reserved = 5
used = {
    "instance i-app1 primary eni": 1,
    "secondary eni (mgmt)": 1,
    "interface endpoint eni (vpce-sts in app-1a)": 1,
}
print(f"/20 total          {total}")
print(f"aws reserved       -{reserved}")
for k, v in used.items():
    print(f"{k:45} -{v}")
print(f"expected Free      {total - reserved - sum(used.values())}")
PY
```

Expected `Free = 4088` for `subnet-app-1a`. If your build reports something else, reconcile it against `describe-network-interfaces` — the discrepancy is either an unaccounted ENI or an unimplemented reservation rule. Log it.

```bash
# Now the data-plane probe from Section 0.5.2 — this is the moment to run it
./bin/probe-dataplane.sh | tee out/lab08-dataplane.txt
```

#### 8.4 Break it

**Break 1 — exhaust a subnet.**

*AWS-correct verdict:* `InsufficientFreeAddressesInSubnet` once the 11 usable addresses of a `/28` are consumed.

```bash
SUBNET_PROBE=$(aws ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 10.20.200.0/28 --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[
      {Key=Name,Value=dnb-dev-subnet-probe},{Key=Project,Value=CoreBanking},
      {Key=ManagedBy,Value=floci-lab},{Key=Tier,Value=probe}]' \
  --query 'Subnet.SubnetId' --output text)
setid SUBNET_PROBE "$SUBNET_PROBE"

aws ec2 describe-subnets --subnet-ids "$SUBNET_PROBE" \
  --query 'Subnets[0].[CidrBlock,AvailableIpAddressCount]' --output text
# expect: 10.20.200.0/28   11
```

```bash
made=0
while [ "$made" -lt 14 ]; do
  eni=$(aws ec2 create-network-interface --subnet-id "$SUBNET_PROBE" \
          --groups "$SG_APP" --description "exhaustion probe $made" \
          --tag-specifications 'ResourceType=network-interface,Tags=[{Key=Name,Value=dnb-dev-eni-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
          --query 'NetworkInterface.NetworkInterfaceId' --output text 2>&1) || true
  case "$eni" in
    eni-*) made=$((made+1)); printf 'created %2d: %s\n' "$made" "$eni" ;;
    *)     printf 'FAILED after %d ENIs: %s\n' "$made" "$(head -c 160 <<<"$eni")"; break ;;
  esac
done

aws ec2 describe-subnets --subnet-ids "$SUBNET_PROBE" \
  --query 'Subnets[0].AvailableIpAddressCount' --output text
```

Real AWS stops at **11** with:

```
An error occurred (InsufficientFreeAddressesInSubnet) when calling the
CreateNetworkInterface operation: The specified subnet does not have enough
free addresses to satisfy the request.
```

If your build reaches 14, it has no address manager — log it, and remember that a `/28` in real AWS holds 11 ENIs, not 16.

!!! tip "This is the number-one production capacity incident in EKS clusters"
    Each pod in `awsvpc`/VPC-CNI mode consumes a subnet IP, and the CNI *pre-allocates* a warm pool. A `/24` per subnet feels generous until 200 pods per node try to schedule. Size for pods, not for nodes.

**Break 2 — pin a reserved address.**

*AWS-correct verdict:* rejected; `10.20.32.1` is the VPC router.

```bash
aws ec2 create-network-interface --subnet-id "$SUBNET_APP_1A" --groups "$SG_APP" \
  --private-ip-address 10.20.32.1 --description "probe: reserved address" 2>&1 | head -3
```

**Break 3 — attach a sixth security group.**

*AWS-correct verdict:* rejected at 6; the default quota is 5 SGs per ENI.

```bash
SG_LIST="$SG_APP $SG_WEB $SG_DB $SG_VPCE $SG_DEFAULT"
extra=""
for n in 1 2; do
  id=$(aws ec2 create-security-group --group-name "dnb-dev-sg-filler-$n" \
        --description "probe filler $n" --vpc-id "$VPC_ID" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=dnb-dev-sg-filler-$n},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]" \
        --query 'GroupId' --output text)
  extra="$extra $id"
done
setid SG_FILLERS "$(echo "$extra" | tr -s ' ')"

# 5 groups: expected to succeed
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups $SG_LIST 2>&1 | head -2
# 7 groups: expected to fail with SecurityGroupsPerInterfaceLimitExceeded
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups $SG_LIST $extra 2>&1 | head -3
```

**Break 4 — delete a subnet that still contains ENIs.**

*AWS-correct verdict:* `DependencyViolation`.

```bash
aws ec2 delete-subnet --subnet-id "$SUBNET_PROBE" 2>&1 | head -3
```

Then diagnose it properly, which is the skill that matters:

```bash
aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET_PROBE" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Desc:Description,Status:Status,Attached:Attachment.InstanceId}' \
  --output table
```

#### 8.5 Fix it

```bash
# 1. Restore the correct SG set on the secondary ENI, and delete the fillers
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups "$SG_APP" 2>&1 | head -2
for id in $SG_FILLERS; do aws ec2 delete-security-group --group-id "$id" 2>&1 | head -1; done
grep -v '^export SG_FILLERS=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset SG_FILLERS

# 2. Drain and delete the probe subnet, in dependency order
while read -r eni; do
  [ -z "$eni" ] && continue
  aws ec2 delete-network-interface --network-interface-id "$eni" 2>&1 | head -1
done < <(aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET_PROBE" \
           --query 'NetworkInterfaces[].NetworkInterfaceId' --output text | tr '\t' '\n')

aws ec2 delete-subnet --subnet-id "$SUBNET_PROBE" 2>&1 | head -2
grep -v '^export SUBNET_PROBE=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset SUBNET_PROBE

# 3. Confirm the main topology is intact
./bin/routing-report.sh
./bin/verify-lab02.sh
```

!!! note "Why `while read … done < <(…)` and not a pipe"
    Process substitution keeps the loop in the current shell, so any variable it sets survives. A pipe would run the loop in a subshell. This is convention gate 7 again, and it is the reason the deletion loop is written this way rather than as `… | while read`.

#### 8.6 Recap of Lab 8

* The **ENI** is the real unit of VPC networking; instances, endpoints, NAT gateways and RDS all own ENIs.
* Device index 0 dies with the instance; secondary ENIs do not and are a common leak.
* `AvailableIpAddressCount` is your capacity gauge: total − 5 − ENIs. Reconcile it against `describe-network-interfaces` when it surprises you.
* A `/28` holds 11 ENIs. Container platforms consume subnet IPs per pod — size accordingly.
* `DependencyViolation` on subnet deletion always means "find the ENI". Learn the one-line diagnostic.

---
### Lab 9 — Growing the VPC: secondary IPv4 CIDR and IPv6

**Objective.** Add a secondary IPv4 CIDR from the shared-address space, create a subnet in it, request an Amazon-provided IPv6 `/56` and carve a `/64`, and model the egress-only internet gateway if your build cannot create one.

**Prerequisites.** Labs 1–8.

**Architecture after this lab.**

```
  VPC dnb-dev-vpc
    primary   10.20.0.0/16      ──► local route
    secondary 100.64.0.0/16     ──► SECOND local route appears automatically
    ipv6      2600:1f18:abcd::/56   (Amazon-provided)

    subnet-overflow-1a   100.64.0.0/20   AZ-a   ← container overflow capacity
    subnet-app-1a        …/20 + 2600:1f18:abcd:0100::/64  ← dual-stack

    rtb-private-1a:
      10.20.0.0/16   → local
      100.64.0.0/16  → local        ← added automatically by the association
      0.0.0.0/0      → nat-1a
      ::/0           → eigw-…       ← IPv6 outbound-only  (conceptual if unsupported)
```

#### 9.1 Implementation — secondary IPv4 CIDR

```bash
aws ec2 associate-vpc-cidr-block --vpc-id "$VPC_ID" --cidr-block 100.64.0.0/16 \
  --query 'CidrBlockAssociation.[AssociationId,CidrBlock,CidrBlockState.State]' --output text
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--cidr-block 100.64.0.0/16` | Additional IPv4 range | Must not overlap the primary or any other secondary, nor any route in the table pointing elsewhere. AWS permits ranges from RFC 1918 plus `100.64.0.0/10` (RFC 6598 shared address space) |
| — | You cannot **resize** the primary | Adding secondaries is the only growth path; up to 5 by default, 50 on request |

!!! tip "Why `100.64.0.0/10` for container overflow"
    RFC 6598 shared address space is not RFC 1918, so it rarely collides with a corporate network — which makes it the standard choice for "IPs that only ever exist inside the VPC", such as EKS pod subnets. AWS explicitly permits it as a secondary CIDR. Routing it to on-premises is usually neither needed nor desirable.

```bash
SUBNET_OVERFLOW_1A=$(aws ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 100.64.0.0/20 --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[
      {Key=Name,Value=dnb-dev-subnet-overflow-1a},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=app}]' \
  --query 'Subnet.SubnetId' --output text)
setid SUBNET_OVERFLOW_1A "$SUBNET_OVERFLOW_1A"

aws ec2 associate-route-table --route-table-id "$RTB_PRIVATE_1A" \
  --subnet-id "$SUBNET_OVERFLOW_1A" --query 'AssociationId' --output text
```

Now inspect the route table. A **second `local` route** should have appeared, unasked:

```bash
aws ec2 describe-route-tables --route-table-ids "$RTB_PRIVATE_1A" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId,NatGatewayId,State,Origin]' \
  --output text
```

Expected:

```
10.20.0.0/16	local	None	active	CreateRouteTable
100.64.0.0/16	local	None	active	CreateRouteTable
0.0.0.0/0	None	nat-0abc…	active	CreateRoute
```

!!! note "The second `local` route is why secondary CIDRs interact with routing"
    Every route table in the VPC gains a `local` route for the new CIDR automatically. Consequence: if a **peered** VPC or an on-premises network already uses `100.64.0.0/16`, that traffic will now be swallowed by the more specific `local` route and never reach the peer. Adding a secondary CIDR can therefore break existing connectivity — check for overlap with every peer and every VPN prefix **before** you associate.

#### 9.2 Implementation — IPv6

```bash
aws ec2 associate-vpc-cidr-block --vpc-id "$VPC_ID" --amazon-provided-ipv6-cidr-block \
  --query 'Ipv6CidrBlockAssociation.[AssociationId,Ipv6CidrBlock,Ipv6CidrBlockState.State]' \
  --output text 2>&1 | head -3

VPC_IPV6=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].Ipv6CidrBlockAssociationSet[0].Ipv6CidrBlock' --output text 2>/dev/null)
setid VPC_IPV6 "$VPC_IPV6"
echo "VPC IPv6 block: $VPC_IPV6"
```

AWS always hands out a **`/56`**, and every subnet must be a **`/64`** — so you have 256 possible subnets and no subnetting arithmetic to do beyond choosing the two hex digits:

```bash
if [ -n "${VPC_IPV6:-}" ] && [ "$VPC_IPV6" != "None" ]; then
  SUBNET_IPV6=$(python3 - "$VPC_IPV6" <<'PY'
import ipaddress, sys
net = ipaddress.ip_network(sys.argv[1])
# take the 0x0100'th /64 so it is visually distinct from the 0th
subs = list(net.subnets(new_prefix=64))
print(subs[0x0100] if len(subs) > 0x0100 else subs[1])
PY
)
  setid SUBNET_IPV6 "$SUBNET_IPV6"
  echo "assigning $SUBNET_IPV6 to app-1a"
  aws ec2 associate-subnet-cidr-block --subnet-id "$SUBNET_APP_1A" \
    --ipv6-cidr-block "$SUBNET_IPV6" 2>&1 | head -3
  aws ec2 modify-subnet-attribute --subnet-id "$SUBNET_APP_1A" \
    --assign-ipv6-address-on-creation 2>&1 | head -2
else
  echo "SKIP: this build did not return an IPv6 CIDR; treat 9.2 as conceptual"
fi
```

**The IPv6 facts to memorise:**

| Fact | Detail |
|---|---|
| VPC block size | always `/56` (Amazon-provided) or a BYOIP range |
| Subnet block size | always `/64`, no exceptions |
| Are IPv6 addresses public? | **Yes** — every one is globally routable. There is no "private IPv6" in AWS |
| Outbound-only | requires an **egress-only internet gateway**, not a NAT gateway |
| Dual-stack | a subnet can carry both an IPv4 CIDR and an IPv6 CIDR; ENIs get both |
| Route syntax | `--destination-ipv6-cidr-block ::/0` |
| Cost | IPv6 addresses are not charged the way public IPv4 addresses are |

#### 9.3 Egress-only internet gateway — build it, or model it

```bash
if EIGW=$(aws ec2 create-egress-only-internet-gateway --vpc-id "$VPC_ID" \
            --tag-specifications 'ResourceType=egress-only-internet-gateway,Tags=[{Key=Name,Value=dnb-dev-eigw},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
            --query 'EgressOnlyInternetGateway.EgressOnlyInternetGatewayId' \
            --output text 2>/dev/null) && [ -n "$EIGW" ] && [ "$EIGW" != "None" ]; then
  setid EIGW "$EIGW"
  echo "SUPPORTED: created $EIGW"
  aws ec2 create-route --route-table-id "$RTB_PRIVATE_1A" \
    --destination-ipv6-cidr-block ::/0 --egress-only-internet-gateway-id "$EIGW" 2>&1 | head -2
else
  echo "NOT SUPPORTED in this build — recording the intended configuration as a model."
fi
```

If unsupported, write the model down. A design you cannot build is still a design you must be able to specify:

```bash
cat > out/model-eigw.json <<'JSON'
{
  "_comment": "AWS-only feature, not creatable in this Floci build. This is the intended configuration.",
  "EgressOnlyInternetGateway": {
    "VpcId": "REPLACE_VPC_ID",
    "Attachments": [{ "State": "attached", "VpcId": "REPLACE_VPC_ID" }],
    "Tags": [{ "Key": "Name", "Value": "dnb-dev-eigw" }]
  },
  "IntendedRoutes": [
    {
      "RouteTableId": "REPLACE_RTB_PRIVATE_1A",
      "DestinationIpv6CidrBlock": "::/0",
      "EgressOnlyInternetGatewayId": "REPLACE_EIGW_ID",
      "Rationale": "IPv6 outbound-only egress for the app tier. NOT an internet gateway: an IGW would make every instance globally reachable, because IPv6 has no NAT."
    }
  ],
  "WhyNotANatGateway": "NAT gateways do not support IPv6. The egress-only IGW provides the same stateful outbound-only property at no charge and with no subnet placement."
}
JSON
python3 -c "import json;json.load(open('out/model-eigw.json'));print('model parses OK')"
```

#### 9.4 Verification

```bash
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].{Primary:CidrBlock,
           IPv4:CidrBlockAssociationSet[].[CidrBlock,CidrBlockState.State],
           IPv6:Ipv6CidrBlockAssociationSet[].[Ipv6CidrBlock,Ipv6CidrBlockState.State]}' \
  --output json | tee out/lab09-cidrs.json

aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets,&CidrBlock)[].{Name:Tags[?Key==`Name`]|[0].Value,
           v4:CidrBlock,v6:Ipv6CidrBlockAssociationSet[0].Ipv6CidrBlock,
           Free:AvailableIpAddressCount}' --output table
```

```bash
# Overlap assertion — the check you must run BEFORE adding any CIDR
cat > bin/assert-no-cidr-overlap.sh <<'SH'
#!/usr/bin/env bash
# Verify no two subnets overlap, and every subnet sits inside a VPC CIDR.
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import ipaddress, json, subprocess, sys
vpc = sys.argv[1]
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True, text=True).stdout or "{}")
v = aws("describe-vpcs","--vpc-ids",vpc)["Vpcs"][0]
vpc_nets = [ipaddress.ip_network(a["CidrBlock"]) for a in v["CidrBlockAssociationSet"]
            if a["CidrBlockState"]["State"] == "associated"]
subs = aws("describe-subnets","--filters",f"Name=vpc-id,Values={vpc}")["Subnets"]
nets = [(s["SubnetId"], ipaddress.ip_network(s["CidrBlock"])) for s in subs]
fail = 0
print("VPC CIDRs:", ", ".join(str(n) for n in vpc_nets))
for sid, n in nets:
    if not any(n.subnet_of(p) for p in vpc_nets):
        print(f"  FAIL {sid} {n} is not inside any VPC CIDR"); fail = 1
for i in range(len(nets)):
    for j in range(i+1, len(nets)):
        if nets[i][1].overlaps(nets[j][1]):
            print(f"  FAIL {nets[i][0]} {nets[i][1]} overlaps {nets[j][0]} {nets[j][1]}"); fail = 1
print("  no overlaps, all subnets in range" if not fail else "")
sys.exit(fail)
PY
SH
chmod +x bin/assert-no-cidr-overlap.sh
./bin/assert-no-cidr-overlap.sh
```

#### 9.5 Break it

**Break 1 — an overlapping secondary CIDR.**

*AWS-correct verdict:* rejected with `InvalidVpcRange` / `CidrConflict`.

```bash
aws ec2 associate-vpc-cidr-block --vpc-id "$VPC_ID" --cidr-block 10.20.128.0/17 2>&1 | head -3
```

**Break 2 — a secondary CIDR from a disallowed range.**

*AWS-correct verdict:* rejected. Publicly routable space (other than your own BYOIP) is not permitted.

```bash
aws ec2 associate-vpc-cidr-block --vpc-id "$VPC_ID" --cidr-block 8.8.8.0/24 2>&1 | head -3
```

**Break 3 — an IPv6 subnet that is not a `/64`.**

*AWS-correct verdict:* rejected; `/64` is mandatory.

```bash
if [ -n "${VPC_IPV6:-}" ] && [ "$VPC_IPV6" != "None" ]; then
  bad=$(python3 - "$VPC_IPV6" <<'PY'
import ipaddress, sys
print(list(ipaddress.ip_network(sys.argv[1]).subnets(new_prefix=60))[2])
PY
)
  aws ec2 associate-subnet-cidr-block --subnet-id "$SUBNET_APP_1B" \
    --ipv6-cidr-block "$bad" 2>&1 | head -3
else
  echo "skipped (no IPv6 block on this build)"
fi
```

**Break 4 — disassociate the primary CIDR.**

*AWS-correct verdict:* rejected. The primary is immutable.

```bash
PRIMARY_ASSOC=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query "Vpcs[0].CidrBlockAssociationSet[?CidrBlock=='10.20.0.0/16'].AssociationId | [0]" \
  --output text)
aws ec2 disassociate-vpc-cidr-block --association-id "$PRIMARY_ASSOC" 2>&1 | head -3
```

#### 9.6 Fix it

```bash
./bin/assert-no-cidr-overlap.sh
./bin/routing-report.sh
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].CidrBlockAssociationSet[].[CidrBlock,CidrBlockState.State]' --output text
```

Reserve future ranges in documentation, not in the API — there is no "reservation" object for VPC CIDRs:

```bash
cat > out/ipam-record.md <<'MD'
# DNB IPv4 allocation record — dev environment

| CIDR | Purpose | Status | Owner |
|---|---|---|---|
| 10.20.0.0/20   | public 1a            | in use   | platform |
| 10.20.16.0/20  | public 1b            | in use   | platform |
| 10.20.32.0/20  | app 1a               | in use   | platform |
| 10.20.48.0/20  | app 1b               | in use   | platform |
| 10.20.64.0/20  | data 1a              | in use   | platform |
| 10.20.80.0/20  | data 1b              | in use   | platform |
| 10.20.96.0/20  | third AZ public+app  | RESERVED | platform |
| 10.20.112.0/20 | third AZ data        | RESERVED | platform |
| 10.20.128.0/17 | future expansion     | RESERVED | platform |
| 100.64.0.0/20  | container overflow 1a| in use   | platform |
| 100.64.16.0/20 | container overflow 1b| RESERVED | platform |

Do NOT allocate outside this record. Check against the staging (10.21.0.0/16)
and prod (10.22.0.0/16) records before any change, because these VPCs are
expected to be peered or attached to a transit gateway.
MD
echo "allocation record written to out/ipam-record.md"
```

#### 9.7 Recap of Lab 9

* The primary CIDR is immutable; growth means **secondary CIDRs**, which cannot overlap and which add a second `local` route to every table.
* Adding a secondary CIDR can silently break peering or VPN reachability for that range — check overlap against every peer first.
* `100.64.0.0/10` is the conventional choice for VPC-internal-only capacity.
* IPv6: VPC `/56`, subnet `/64`, always globally routable, outbound-only requires an **egress-only IGW**, and NAT gateways do not support it.
* When a feature is unsupported locally, write the intended configuration down as a model and say so explicitly.

---

### Lab 10 — The reachability matrix, and flow logs you cannot create

**Objective.** Produce a full N×N reachability matrix for the DNB topology, diff it against the intended design, and build the flow-log analysis skills even though the emulator cannot generate flow logs.

**Prerequisites.** Labs 1–9, `bin/reach.py`.

#### 10.1 Implementation — the intended matrix, written down first

Design before verification. Write the intent, then test it:

```bash
cat > out/intended-matrix.tsv <<'M'
src_tier	dst_tier	port	expected
public	app	8080	PERMITTED
public	data	5432	BLOCKED
app	data	5432	PERMITTED
app	public	8080	BLOCKED
data	app	8080	BLOCKED
data	internet	443	BLOCKED
app	internet	443	PERMITTED
public	internet	443	BLOCKED
M
column -t -s $'\t' out/intended-matrix.tsv
```

!!! note "Why `public → internet 443` is expected BLOCKED"
    We revoked allow-all egress from `sg-web` in Lab 5 and allowed only 8080 to `sg-app` and 443 to `sg-vpce`. An ALB does not need to originate arbitrary internet connections. If you *want* it permitted, that is a deliberate change to `sg-web` — not an oversight to be patched at test time.

#### 10.2 The matrix runner

```bash
cat > bin/reach-matrix.sh <<'SH'
#!/usr/bin/env bash
# Run reach.py for every row of out/intended-matrix.tsv and diff against intent.
set -uo pipefail
: "${VPC_ID:?load the ledger first}"

subnet_of() { case "$1" in
  public)   echo "$SUBNET_PUBLIC_1A" ;;
  app)      echo "$SUBNET_APP_1A" ;;
  data)     echo "$SUBNET_DATA_1A" ;;
  *)        echo "" ;;
esac; }
sg_of() { case "$1" in
  public)   echo "$SG_WEB" ;;
  app)      echo "$SG_APP" ;;
  data)     echo "$SG_DB" ;;
  *)        echo "" ;;
esac; }
ip_of() { case "$1" in
  public)   echo "10.20.0.50" ;;
  app)      echo "10.20.32.50" ;;
  data)     echo "10.20.64.10" ;;
  internet) echo "203.0.113.9" ;;
  *)        echo "" ;;
esac; }

pass=0; fail=0
printf '%-8s %-9s %-6s %-11s %-11s %s\n' SRC DST PORT EXPECTED ACTUAL RESULT
printf '%s\n' "----------------------------------------------------------------------"
while IFS=$'\t' read -r src dst port expected; do
  [ "$src" = "src_tier" ] && continue
  [ -z "${src:-}" ] && continue
  args=( --from-subnet "$(subnet_of "$src")" --from-ip "$(ip_of "$src")"
         --to-ip "$(ip_of "$dst")" --port "$port" --src-sg "$(sg_of "$src")" )
  if [ "$dst" != "internet" ]; then
    args+=( --to-subnet "$(subnet_of "$dst")" --dst-sg "$(sg_of "$dst")" )
  fi
  out=$(python3 ~/vpc-lab/bin/reach.py "${args[@]}" 2>&1) || true
  actual=$(grep -o 'AWS VERDICT: [A-Z]*' <<<"$out" | awk '{print $3}')
  actual=${actual:-ERROR}
  if [ "$actual" = "$expected" ]; then
    res=PASS; pass=$((pass+1))
  else
    res=FAIL; fail=$((fail+1))
    printf '%s\n' "$out" > "$HOME/vpc-lab/out/reach-fail-${src}-${dst}-${port}.txt"
  fi
  printf '%-8s %-9s %-6s %-11s %-11s %s\n' "$src" "$dst" "$port" "$expected" "$actual" "$res"
done < "$HOME/vpc-lab/out/intended-matrix.tsv"
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
SH
chmod +x bin/reach-matrix.sh
./bin/reach-matrix.sh | tee out/lab10-matrix.txt
```

Expected:

```
SRC      DST       PORT   EXPECTED    ACTUAL      RESULT
----------------------------------------------------------------------
public   app       8080   PERMITTED   PERMITTED   PASS
public   data      5432   BLOCKED     BLOCKED     PASS
app      data      5432   PERMITTED   PERMITTED   PASS
app      public    8080   BLOCKED     BLOCKED     PASS
data     app       8080   BLOCKED     BLOCKED     PASS
data     internet  443    BLOCKED     BLOCKED     PASS
app      internet  443    PERMITTED   PERMITTED   PASS
public   internet  443    BLOCKED     BLOCKED     PASS

8 passed, 0 failed
```

Any `FAIL` writes the full step-by-step trace to `out/reach-fail-*.txt`, which tells you *which of the seven steps* disagreed with your intent. That file is what you attach to the lab report — not a screenshot.

!!! tip "This is the deliverable that demonstrates understanding"
    A student who shows a green matrix plus the `reach.py` source has proved they can reason about AWS's evaluation pipeline. A student who shows `describe-security-groups` output has proved only that they can type. Aim for the former.

#### 10.3 Flow logs — the analysis skill without the service

```bash
grep -E 'create-flow-logs|describe-flow-logs' out/support-matrix.tsv || true

FLOWLOG_SUPPORTED=no
if aws ec2 create-flow-logs --resource-type VPC --resource-ids "$VPC_ID" \
     --traffic-type ALL --log-destination-type cloud-watch-logs \
     --log-group-name /dnb/dev/vpc/flowlogs \
     --deliver-logs-permission-arn "arn:aws:iam::000000000000:role/dnb-dev-flowlogs-role" \
     >/dev/null 2>&1; then
  FLOWLOG_SUPPORTED=yes
  echo "SUPPORTED: flow logs created"
  aws ec2 describe-flow-logs --query 'FlowLogs[].[FlowLogId,ResourceId,TrafficType,FlowLogStatus]' --output text
else
  echo "NOT SUPPORTED: flow logs cannot be created in this build. Proceeding conceptually."
fi
setid FLOWLOG_SUPPORTED "$FLOWLOG_SUPPORTED"
```

Whether or not it worked, the skill you are graded on is **reading** flow log records. Here is a synthetic capture of the DNB topology, including two real incidents:

```bash
cat > out/synthetic-flowlogs.txt <<'FL'
2 000000000000 eni-0app1 10.20.32.10 10.20.64.10 51222 5432 6 12 1842 1780000000 1780000060 ACCEPT OK
2 000000000000 eni-0db1  10.20.64.10 10.20.32.10 5432 51222 6 10 4210 1780000000 1780000060 ACCEPT OK
2 000000000000 eni-0app1 10.20.32.10 10.20.64.10 51555 5432 6 3 180 1780000120 1780000180 ACCEPT OK
2 000000000000 eni-0db1  10.20.64.10 10.20.32.10 5432 51555 6 3 180 1780000120 1780000180 REJECT OK
2 000000000000 eni-0web1 10.20.0.10 10.20.64.10 44210 5432 6 2 120 1780000240 1780000300 REJECT OK
2 000000000000 eni-0web1 10.20.0.10 10.20.32.10 44300 8080 6 40 21000 1780000240 1780000300 ACCEPT OK
2 000000000000 eni-0app1 10.20.32.10 52.94.5.1 39001 443 6 22 9000 1780000360 1780000420 ACCEPT OK
2 000000000000 eni-0db1  10.20.64.10 198.51.100.7 40122 443 6 1 60 1780000480 1780000540 REJECT OK
2 000000000000 eni-0app1 10.20.32.10 10.20.64.10 51999 22 6 1 60 1780000600 1780000660 REJECT OK
FL
column -t out/synthetic-flowlogs.txt
```

Now interpret it. Answer each of these in your lab report:

```bash
cat > out/flowlog-questions.md <<'MD'
# Flow log interpretation exercise

Field order (default format):
version account-id interface-id srcaddr dstaddr srcport dstport
protocol packets bytes start end action log-status

1. Lines 1-2 are a healthy flow. Which is the request and which is the reply?
   How can you tell from the ports alone?

2. Lines 3-4 are the SAME connection as lines 1-2 in shape, but line 4 is a
   REJECT on the RETURN path. Which VPC component can produce an ACCEPT
   outbound and a REJECT on the return, and why is it impossible for a
   security group to cause this?

3. Line 5 is a REJECT from the web tier to the database. Name the TWO
   independent controls in our design that would each block it on their own.

4. Line 7 shows the app tier reaching 52.94.5.1:443 (an AWS-owned address).
   If we had NOT built the S3 gateway endpoint, which resource would this
   traffic traverse, and what would it cost per GB?

5. Line 8 is a REJECT from the DATA tier outbound to the internet on 443.
   Assuming an attacker had shell on the database host, list every control
   in our design that stopped this, in the order AWS evaluates them.

6. Line 9 is a REJECT to port 22 inside the VPC. Which control denied it?
   Is there any route-level reason it would also fail?

7. Write the CloudWatch Logs Insights query that would find, for any hour,
   all source addresses that generated more than 10 REJECTs.

8. Which of these flows would NOT appear in real flow logs at all, and why?
   (Hint: consider traffic to 10.20.0.2 and 169.254.169.254.)
MD
echo "questions written to out/flowlog-questions.md"
```

**Model answers to 2, 5 and 7** — study these, then answer the rest yourself:

* **(2)** Only a **network ACL** can do this. NACLs are stateless, so the outbound request and the inbound reply are evaluated independently; an egress allow with no matching ingress ephemeral allow yields exactly this ACCEPT/REJECT pair. A security group is stateful — if it permitted the request, the reply is permitted automatically and cannot be rejected.
* **(5)** In order: (1) `sg-db` egress — empty, so implicit deny; (2) `acl-data` egress rule 32766 `deny all`; (3) `rtb-data` has no `0.0.0.0/0` route, so the packet has nowhere to go even if filtering passed; (4) the `vpce-s3` endpoint policy would deny anything but our two buckets even for S3. Four independent layers — that is what "defence in depth" means concretely.
* **(7)**

  ```
  fields @timestamp, srcAddr, dstAddr, dstPort, action
  | filter action = "REJECT"
  | stats count(*) as rejects by srcAddr
  | filter rejects > 10
  | sort rejects desc
  ```

#### 10.4 Verification

```bash
./bin/reach-matrix.sh
./bin/lint-nacl.sh
./bin/assert-sg-invariants.sh
./bin/assert-nat-az-affinity.sh
./bin/assert-main-rtb-minimal.sh
./bin/assert-no-cidr-overlap.sh
```

All six should pass. Bundle them:

```bash
cat > bin/verify-all.sh <<'SH'
#!/usr/bin/env bash
# Full topology verification. Run before submitting any lab report.
set -uo pipefail
cd "$HOME/vpc-lab"
: "${VPC_ID:?load the ledger first: . bin/ids.sh && loadids}"
fail=0
for s in assert-main-rtb-minimal assert-no-cidr-overlap assert-nat-az-affinity \
         assert-sg-invariants lint-nacl reach-matrix verify-lab02; do
  printf '\n===== %s =====\n' "$s"
  if [ -x "bin/$s.sh" ]; then
    ./bin/"$s".sh || { echo "  ^^ $s FAILED"; fail=1; }
  else
    echo "  (missing bin/$s.sh — skipped)"
  fi
done
printf '\n%s\n' "$([ $fail -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
exit $fail
SH
chmod +x bin/verify-all.sh
./bin/verify-all.sh | tee out/lab10-verify-all.txt
```

#### 10.5 Break it

Break the design in a way the matrix will catch, and confirm that it does:

```bash
# Someone "temporarily" opens the database to the whole app subnet by CIDR
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.0.0/16","Description":"temporary debugging - REMOVE"}]}]' >/dev/null

./bin/reach-matrix.sh || echo "^ the matrix caught the regression"
cat out/reach-fail-public-data-5432.txt 2>/dev/null | tail -6
```

Expected: `public → data 5432` flips from `BLOCKED` to `PERMITTED` and the row fails. A CIDR rule that "just allows the app subnet" also allows the **public** subnet, because `10.20.0.0/16` contains it. This is exactly the failure mode that security-group referencing prevents.

#### 10.6 Fix it

```bash
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.0.0/16"}]}]' >/dev/null
rm -f out/reach-fail-*.txt
./bin/verify-all.sh | tail -5
```

#### 10.7 Recap of Lab 10

* Write the intended reachability matrix **before** testing. Verification without stated intent is just description.
* `reach.py` gives you a local Reachability Analyzer and makes Track B executable and repeatable.
* A failing matrix row plus a seven-step trace localises the fault to a specific control — that is a real debugging workflow.
* Flow logs are unavailable locally, but reading them is the examinable skill: an outbound `ACCEPT` with a return `REJECT` is the unmistakable signature of a stateless NACL.
* Broad CIDR rules leak. `10.20.0.0/16` "for the app tier" also grants the public tier.

---

### Lab 11 — Peering and hybrid connectivity: probe, then model

**Objective.** Determine empirically whether your build supports VPC peering. If it does, build a spoke VPC and peer it. If not, produce a complete, reviewable design document plus the exact CLI sequence — and be explicit that it is a model.

**Prerequisites.** Labs 1–10.

#### 11.1 Probe first

```bash
PEERING_SUPPORTED=no
probe=$(aws ec2 create-vpc-peering-connection \
          --vpc-id "$VPC_ID" --peer-vpc-id vpc-11111111111111111 2>&1) || true
case "$probe" in
  *InvalidAction*|*NotImplemented*|*UnknownOperation*)
      echo "UNSUPPORTED: $(head -c 140 <<<"$probe")" ;;
  *InvalidVpcID*|*NotFound*|*InvalidParameter*)
      PEERING_SUPPORTED=yes
      echo "SUPPORTED (validated): the operation exists and rejected the fake peer id" ;;
  *pcx-*)
      PEERING_SUPPORTED=yes
      echo "SUPPORTED: it actually created something — clean it up"
      pcx=$(grep -o 'pcx-[0-9a-f]*' <<<"$probe" | head -1)
      [ -n "$pcx" ] && aws ec2 delete-vpc-peering-connection --vpc-peering-connection-id "$pcx" ;;
  *)  echo "UNKNOWN: $(head -c 140 <<<"$probe")" ;;
esac
setid PEERING_SUPPORTED "$PEERING_SUPPORTED"
```

#### 11.2 Path A — peering is supported: build the shared-services spoke

```bash
if [ "$PEERING_SUPPORTED" = "yes" ]; then
  VPC_SHARED=$(aws ec2 create-vpc --cidr-block 10.30.0.0/16 \
    --tag-specifications 'ResourceType=vpc,Tags=[
        {Key=Name,Value=dnb-shared-vpc},{Key=Project,Value=CoreBanking},
        {Key=Environment,Value=shared},{Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
    --query 'Vpc.VpcId' --output text)
  setid VPC_SHARED "$VPC_SHARED"

  SUBNET_SHARED=$(aws ec2 create-subnet --vpc-id "$VPC_SHARED" \
    --cidr-block 10.30.0.0/24 --availability-zone "$AZ_A" \
    --tag-specifications 'ResourceType=subnet,Tags=[
        {Key=Name,Value=dnb-shared-subnet-svc-1a},{Key=ManagedBy,Value=floci-lab},
        {Key=Project,Value=CoreBanking},{Key=Tier,Value=app}]' \
    --query 'Subnet.SubnetId' --output text)
  setid SUBNET_SHARED "$SUBNET_SHARED"

  PCX=$(aws ec2 create-vpc-peering-connection \
    --vpc-id "$VPC_ID" --peer-vpc-id "$VPC_SHARED" \
    --tag-specifications 'ResourceType=vpc-peering-connection,Tags=[
        {Key=Name,Value=dnb-dev-pcx-to-shared},{Key=ManagedBy,Value=floci-lab},
        {Key=Project,Value=CoreBanking}]' \
    --query 'VpcPeeringConnection.VpcPeeringConnectionId' --output text)
  setid PCX "$PCX"

  aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id "$PCX" \
    --query 'VpcPeeringConnection.Status.Code' --output text

  # Routes on BOTH sides — the peering alone carries nothing
  aws ec2 create-route --route-table-id "$RTB_PRIVATE_1A" \
    --destination-cidr-block 10.30.0.0/16 --vpc-peering-connection-id "$PCX"

  RTB_SHARED=$(aws ec2 describe-route-tables \
    --filters "Name=vpc-id,Values=$VPC_SHARED" "Name=association.main,Values=true" \
    --query 'RouteTables[0].RouteTableId' --output text)
  setid RTB_SHARED "$RTB_SHARED"
  aws ec2 create-route --route-table-id "$RTB_SHARED" \
    --destination-cidr-block 10.20.0.0/16 --vpc-peering-connection-id "$PCX"

  aws ec2 describe-vpc-peering-connections --vpc-peering-connection-ids "$PCX" \
    --query 'VpcPeeringConnections[0].{Id:VpcPeeringConnectionId,Status:Status.Code,
             Requester:RequesterVpcInfo.CidrBlock,Accepter:AccepterVpcInfo.CidrBlock}' \
    --output json | tee out/lab11-pcx.json
else
  echo "skipping Path A — peering unsupported in this build"
fi
```

#### 11.3 Path B — peering is unsupported: produce the model

````bash
if [ "$PEERING_SUPPORTED" != "yes" ]; then
cat > out/model-peering.md <<'MD'
# MODEL ONLY — VPC peering design for DNB (not creatable in this Floci build)

## Requirement
The `dnb-dev` VPC (10.20.0.0/16) must reach a shared-services VPC
`dnb-shared` (10.30.0.0/16) that hosts Active Directory, an artifact
repository and a logging aggregator. The shared VPC must NOT be able to
initiate connections to the DNB data tier.

## Why peering and not a transit gateway
Only two VPCs are involved and no transitivity is required. Peering has no
hourly attachment charge and no per-GB processing charge, so it is the correct
choice at this scale. If a third and fourth VPC appear, migrate to a transit
gateway: 4 VPCs need 6 peerings, 8 VPCs need 28.

## CIDR check (must be done BEFORE anything else)
| VPC | CIDR | Overlaps 10.20.0.0/16? |
|---|---|---|
| dnb-dev     | 10.20.0.0/16  | -   |
| dnb-shared  | 10.30.0.0/16  | no  |
| dnb-staging | 10.21.0.0/16  | no  |
| dnb-prod    | 10.22.0.0/16  | no  |
| dev secondary | 100.64.0.0/16 | must also not overlap the peer |

Overlapping CIDRs make peering impossible. There is no NAT in a peering
connection.

## CLI sequence (to run against real AWS)
```bash
PCX=$(aws ec2 create-vpc-peering-connection \
        --vpc-id "$DEV_VPC" --peer-vpc-id "$SHARED_VPC" \
        --query 'VpcPeeringConnection.VpcPeeringConnectionId' --output text)

# Cross-account variant adds:  --peer-owner-id 222222222222 --peer-region us-east-1
aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id "$PCX"

# Routes on BOTH sides. Note we advertise ONLY the app subnets to the peer,
# not the whole VPC, so the shared VPC has no route to the data tier.
aws ec2 create-route --route-table-id "$RTB_PRIVATE_1A" \
  --destination-cidr-block 10.30.0.0/16 --vpc-peering-connection-id "$PCX"
aws ec2 create-route --route-table-id "$RTB_SHARED" \
  --destination-cidr-block 10.20.32.0/20 --vpc-peering-connection-id "$PCX"
aws ec2 create-route --route-table-id "$RTB_SHARED" \
  --destination-cidr-block 10.20.48.0/20 --vpc-peering-connection-id "$PCX"

# Same-region peering allows SG referencing across the peer:
aws ec2 authorize-security-group-ingress --group-id "$SG_APP" \
  --ip-permissions 'IpProtocol=tcp,FromPort=636,ToPort=636,
     UserIdGroupPairs=[{GroupId=sg-shared-ad,VpcId=vpc-shared,Description=LDAPS to AD}]'

# DNS resolution across the peer (both directions must be enabled separately):
aws ec2 modify-vpc-peering-connection-options \
  --vpc-peering-connection-id "$PCX" \
  --requester-peering-connection-options AllowDnsResolutionFromRemoteVpc=true
```

## What peering does NOT give us
| Not available over peering | Consequence for this design |
|---|---|
| Transitive routing | dnb-staging cannot reach dnb-shared via dnb-dev |
| Use of the peer's internet gateway | the shared VPC needs its own egress |
| Use of the peer's NAT gateway | same |
| Use of the peer's VPC endpoints | each VPC needs its own S3 gateway endpoint |
| Overlapping CIDRs | hard blocker; re-address one side or use PrivateLink |
| Edge-to-edge routing via VGW/IGW | the shared VPC cannot reach on-premises through dnb-dev |

## Data-tier protection
We advertise only 10.20.32.0/20 and 10.20.48.0/20 to the peer. Even so, the
`local` route inside dnb-dev means a compromised host in the app tier could
still reach the data tier — which is why `sg-db` restricts ingress to `sg-app`
and `acl-data` denies everything else. Routing is not a security control.

## Cost
No hourly charge. Data transfer across a peering connection within the same
AZ is free; across AZs it is charged at the standard cross-AZ rate in both
directions. Placing the shared services in the same AZ as their heaviest
consumer is therefore a real optimisation.
MD
echo "model written to out/model-peering.md"
fi
````

#### 11.4 Hybrid connectivity — always conceptual

```bash
cat > out/model-hybrid.md <<'MD'
# MODEL ONLY — hybrid connectivity for DNB (no Floci support)

## Requirement
The bank's on-premises core banking system at its Thimphu head office
(172.16.0.0/16) must exchange batch files with the app tier. The Royal
Monetary Authority requires that this traffic never traverse the public
internet unencrypted.

## Option analysis
| Option | Meets "not over the internet"? | Encrypted? | Latency | Lead time | Monthly cost order |
|---|---|---|---|---|---|
| Site-to-Site VPN | no (rides the internet) | yes, IPSec | variable | hours | low |
| Direct Connect (1 Gbps hosted) | yes | **no** by default | consistent | weeks-months | high |
| DX + VPN over it | yes | yes | consistent | weeks-months | high |
| DX primary + VPN backup | yes / degraded on failover | yes on backup | mostly consistent | weeks-months | high |

Recommendation: Direct Connect with a MACsec or IPSec overlay for encryption,
plus a Site-to-Site VPN as the backup path. This is the standard regulated
financial-services pattern.

## VPC-side configuration
1. Create a virtual private gateway and attach it to the VPC:
   `aws ec2 create-vpn-gateway --type ipsec.1`
   `aws ec2 attach-vpn-gateway --vpn-gateway-id vgw-... --vpc-id vpc-...`
2. Either add static routes, or enable propagation so BGP-learned prefixes
   appear automatically in the chosen route tables:
   `aws ec2 enable-vgw-route-propagation --route-table-id rtb-... --gateway-id vgw-...`
   Propagated routes show `Origin: EnableVgwRoutePropagation` and are LESS
   preferred than an identical static route.
3. Customer gateway + VPN connection, using BOTH tunnels:
   `aws ec2 create-customer-gateway --type ipsec.1 --public-ip 203.0.113.10 --bgp-asn 65000`
   `aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id cgw-... \
       --vpn-gateway-id vgw-... --options TunnelOptions=[{},{}]`
4. Do NOT advertise 100.64.0.0/16 to on-premises. It is VPC-internal capacity
   and advertising it invites collisions with the branch network.

## Route preference, most to least specific then by type
local  >  longest prefix  >  static route  >  propagated (BGP) route
Within BGP: longest AS_PATH is less preferred; AWS also prefers DX over VPN
for the same prefix.

## DNS
On-premises resolvers must resolve AWS private names and vice versa. Use
Route 53 Resolver inbound and outbound endpoints with forwarding rules.
Do NOT replace domain-name-servers in a DHCP option set — that breaks
interface-endpoint private DNS and private hosted zones.
MD
echo "model written to out/model-hybrid.md"
```

#### 11.5 Verification

```bash
ls -la out/model-*.md out/model-*.json 2>/dev/null
if [ "$PEERING_SUPPORTED" = "yes" ]; then
  aws ec2 describe-route-tables --route-table-ids "$RTB_PRIVATE_1A" \
    --query 'RouteTables[0].Routes[].[DestinationCidrBlock,VpcPeeringConnectionId,GatewayId,NatGatewayId,State]' \
    --output text
fi
```

#### 11.6 Break it

**Break 1 — overlapping CIDR peering.** *AWS-correct verdict:* rejected outright.

```bash
if [ "$PEERING_SUPPORTED" = "yes" ]; then
  VPC_OVERLAP=$(aws ec2 create-vpc --cidr-block 10.20.0.0/16 \
    --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=dnb-overlap-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
    --query 'Vpc.VpcId' --output text)
  setid VPC_OVERLAP "$VPC_OVERLAP"
  aws ec2 create-vpc-peering-connection --vpc-id "$VPC_ID" --peer-vpc-id "$VPC_OVERLAP" 2>&1 | head -3
  aws ec2 delete-vpc --vpc-id "$VPC_OVERLAP" 2>&1 | head -2
  grep -v '^export VPC_OVERLAP=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
  unset VPC_OVERLAP
else
  echo "Track B: AWS rejects this with InvalidVpcPeeringConnection / overlapping CIDR."
fi
```

Expected AWS behaviour: `VpcPeeringConnection failed` with `Status.Message` mentioning overlapping CIDR blocks.

**Break 2 — peering without routes.** *AWS-correct verdict:* the connection is `active` and **no traffic flows**. Reason it through: with no route entry, the longest-prefix match for `10.30.0.0/16` in `rtb-private-1a` falls through to `0.0.0.0/0 → nat-1a`, so the packet is source-NATed and sent to the internet, where it is dropped. Not "blocked by a firewall" — misrouted.

**Break 3 — transitivity.** *AWS-correct verdict:* impossible by design. Write the three-VPC diagram in your report and state which routes exist and which packet is dropped where.

#### 11.7 Recap of Lab 11

* Peering: **non-overlapping CIDRs, non-transitive, routes required on both sides**, and no borrowing of the peer's IGW, NAT or endpoints.
* Same-region peering permits security-group referencing across the peer; cross-region does not.
* Advertise the minimum prefix set to a peer, but remember routing is not a security control — the `local` route always exists inside your own VPC.
* Transit gateway replaces peering when you have many VPCs or need transitivity, at the cost of per-attachment and per-GB charges.
* For hybrid: VPN is quick but rides the internet; Direct Connect is private and consistent but slow to provision and **unencrypted by default**.
* When a feature is unavailable, a rigorous model with the exact CLI sequence, the option analysis and the failure modes is the deliverable.

---

### Lab 12 — Automate the whole build

**Objective.** Replace twelve labs of manual commands with one idempotent script that builds the topology from nothing, emits a machine-readable `topology.json`, and verifies itself.

**Prerequisites.** Labs 1–11.

#### 12.1 Why idempotence matters

An AWS build script is run repeatedly: after a failure halfway through, after a review comment, on a second environment. "Create it" is the wrong verb; "ensure it exists" is the right one. Every function below follows the same shape: **look it up by tag; create only if absent; return the id either way.**

```bash
cat > bin/build-vpc.sh <<'SH'
#!/usr/bin/env bash
# build-vpc.sh — idempotently build the DNB dev VPC topology.
# Safe to re-run. Emits out/topology.json.
set -uo pipefail

: "${AWS_ENDPOINT_URL:?refusing to run without AWS_ENDPOINT_URL (see guard())}"
case "$AWS_ENDPOINT_URL" in
  *localhost*|*127.0.0.1*|*floci*) : ;;
  *) echo "REFUSING: endpoint '$AWS_ENDPOINT_URL' is not a local emulator" >&2; exit 1 ;;
esac

ORG=dnb; ENV=dev
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
VPC_CIDR=10.20.0.0/16
TAGS_COMMON="{Key=Project,Value=CoreBanking},{Key=Environment,Value=$ENV},{Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}"
LEDGER="$HOME/vpc-lab/out/ids.env"
mkdir -p "$HOME/vpc-lab/out" "$HOME/vpc-lab/policies"
touch "$LEDGER"

log()  { printf '[%s] %s\n' "$(printf '%(%H:%M:%S)T' -1 2>/dev/null || echo '--:--:--')" "$*"; }
setid() {
  local k="$1" v="$2"
  grep -v "^export ${k}=" "$LEDGER" > "${LEDGER}.tmp" 2>/dev/null || true
  mv "${LEDGER}.tmp" "$LEDGER"
  printf 'export %s=%s\n' "$k" "$v" >> "$LEDGER"
  export "$k=$v"
}

# ---------- idempotent lookups -------------------------------------------------
find_by_name() {   # find_by_name <describe-verb> <json-key> <query-path> <name>
  aws ec2 "$1" --filters "Name=tag:Name,Values=$4" \
    --query "$3" --output text 2>/dev/null | awk 'NR==1{print $1}'
}

ensure_vpc() {
  local name="$ORG-$ENV-vpc" id
  id=$(find_by_name describe-vpcs Vpcs 'Vpcs[].VpcId' "$name")
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-vpc --cidr-block "$VPC_CIDR" \
          --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=$name},$TAGS_COMMON]" \
          --query 'Vpc.VpcId' --output text)
    aws ec2 modify-vpc-attribute --vpc-id "$id" --enable-dns-support
    aws ec2 modify-vpc-attribute --vpc-id "$id" --enable-dns-hostnames
    log "created VPC $id ($name)"
  else
    log "reusing VPC $id ($name)"
  fi
  setid VPC_ID "$id"
}

ensure_subnet() {  # ensure_subnet <key> <name> <cidr> <az> <tier> <public:yes|no>
  local key="$1" name="$2" cidr="$3" az="$4" tier="$5" pub="$6" id
  id=$(find_by_name describe-subnets Subnets 'Subnets[].SubnetId' "$name")
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$cidr" \
          --availability-zone "$az" \
          --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$name},{Key=Tier,Value=$tier},$TAGS_COMMON]" \
          --query 'Subnet.SubnetId' --output text)
    log "created subnet $id ($name $cidr $az)"
  else
    log "reusing subnet $id ($name)"
  fi
  if [ "$pub" = "yes" ]; then
    aws ec2 modify-subnet-attribute --subnet-id "$id" --map-public-ip-on-launch
  else
    aws ec2 modify-subnet-attribute --subnet-id "$id" --no-map-public-ip-on-launch
  fi
  setid "$key" "$id"
}

ensure_igw() {
  local name="$ORG-$ENV-igw" id
  id=$(find_by_name describe-internet-gateways InternetGateways \
         'InternetGateways[].InternetGatewayId' "$name")
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-internet-gateway \
          --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=$name},$TAGS_COMMON]" \
          --query 'InternetGateway.InternetGatewayId' --output text)
    log "created IGW $id"
  else
    log "reusing IGW $id"
  fi
  aws ec2 attach-internet-gateway --internet-gateway-id "$id" --vpc-id "$VPC_ID" >/dev/null 2>&1 \
    && log "attached IGW $id" || log "IGW $id already attached"
  setid IGW_ID "$id"
}

ensure_rtb() {     # ensure_rtb <key> <name> <tier>
  local key="$1" name="$2" tier="$3" id
  id=$(find_by_name describe-route-tables RouteTables 'RouteTables[].RouteTableId' "$name")
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
          --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=$name},{Key=Tier,Value=$tier},$TAGS_COMMON]" \
          --query 'RouteTable.RouteTableId' --output text)
    log "created route table $id ($name)"
  else
    log "reusing route table $id ($name)"
  fi
  setid "$key" "$id"
}

ensure_route() {   # ensure_route <rtb> <cidr> <flag> <target>
  aws ec2 create-route --route-table-id "$1" --destination-cidr-block "$2" "$3" "$4" >/dev/null 2>&1 \
    && log "route $2 -> $4 in $1" \
    || aws ec2 replace-route --route-table-id "$1" --destination-cidr-block "$2" "$3" "$4" >/dev/null 2>&1 \
    && log "route $2 -> $4 in $1 (replaced)"
}

ensure_assoc() {   # ensure_assoc <rtb> <subnet>
  local existing
  existing=$(aws ec2 describe-route-tables --route-table-ids "$1" \
    --query "RouteTables[0].Associations[?SubnetId=='$2'].RouteTableAssociationId | [0]" \
    --output text 2>/dev/null)
  if [ -n "$existing" ] && [ "$existing" != "None" ]; then
    log "assoc $2 -> $1 already present"
  else
    aws ec2 associate-route-table --route-table-id "$1" --subnet-id "$2" >/dev/null \
      && log "associated $2 -> $1"
  fi
}

ensure_eip() {     # ensure_eip <key> <name>
  local key="$1" name="$2" id
  id=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$name" \
        --query 'Addresses[0].AllocationId' --output text 2>/dev/null)
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 allocate-address --domain vpc \
          --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$name},$TAGS_COMMON]" \
          --query 'AllocationId' --output text)
    log "allocated EIP $id ($name)"
  else
    log "reusing EIP $id ($name)"
  fi
  setid "$key" "$id"
}

ensure_nat() {     # ensure_nat <key> <name> <subnet> <eip>
  local key="$1" name="$2" subnet="$3" eip="$4" id
  id=$(aws ec2 describe-nat-gateways \
        --filter "Name=tag:Name,Values=$name" "Name=state,Values=available,pending" \
        --query 'NatGateways[0].NatGatewayId' --output text 2>/dev/null)
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-nat-gateway --subnet-id "$subnet" --allocation-id "$eip" \
          --connectivity-type public \
          --tag-specifications "ResourceType=natgateway,Tags=[{Key=Name,Value=$name},$TAGS_COMMON]" \
          --query 'NatGateway.NatGatewayId' --output text)
    log "created NAT gateway $id ($name) — waiting"
    aws ec2 wait nat-gateway-available --nat-gateway-ids "$id" 2>/dev/null || true
  else
    log "reusing NAT gateway $id ($name)"
  fi
  setid "$key" "$id"
}

ensure_sg() {      # ensure_sg <key> <name> <description>
  local key="$1" name="$2" desc="$3" id
  id=$(aws ec2 describe-security-groups \
        --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=$name" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
  if [ -z "$id" ] || [ "$id" = "None" ]; then
    id=$(aws ec2 create-security-group --group-name "$name" --description "$desc" \
          --vpc-id "$VPC_ID" \
          --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$name},$TAGS_COMMON]" \
          --query 'GroupId' --output text)
    log "created SG $id ($name)"
  else
    log "reusing SG $id ($name)"
  fi
  setid "$key" "$id"
}

allow() {          # allow <ingress|egress> <group> <json-ip-permissions>
  aws ec2 "authorize-security-group-$1" --group-id "$2" --ip-permissions "$3" >/dev/null 2>&1 \
    && log "$1 rule added to $2" || log "$1 rule already present on $2"
}

# ---------- build ------------------------------------------------------------
log "=== phase 1: VPC ==="
ensure_vpc

AZ_A=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[0].ZoneName' --output text)
AZ_B=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[1].ZoneName' --output text)
setid AZ_A "$AZ_A"; setid AZ_B "$AZ_B"

log "=== phase 2: subnets ==="
ensure_subnet SUBNET_PUBLIC_1A "$ORG-$ENV-subnet-public-1a" 10.20.0.0/20  "$AZ_A" public yes
ensure_subnet SUBNET_PUBLIC_1B "$ORG-$ENV-subnet-public-1b" 10.20.16.0/20 "$AZ_B" public yes
ensure_subnet SUBNET_APP_1A    "$ORG-$ENV-subnet-app-1a"    10.20.32.0/20 "$AZ_A" app    no
ensure_subnet SUBNET_APP_1B    "$ORG-$ENV-subnet-app-1b"    10.20.48.0/20 "$AZ_B" app    no
ensure_subnet SUBNET_DATA_1A   "$ORG-$ENV-subnet-data-1a"   10.20.64.0/20 "$AZ_A" data   no
ensure_subnet SUBNET_DATA_1B   "$ORG-$ENV-subnet-data-1b"   10.20.80.0/20 "$AZ_B" data   no

log "=== phase 3: internet gateway + public routing ==="
ensure_igw
ensure_rtb RTB_PUBLIC "$ORG-$ENV-rtb-public" public
ensure_route "$RTB_PUBLIC" 0.0.0.0/0 --gateway-id "$IGW_ID"
ensure_assoc "$RTB_PUBLIC" "$SUBNET_PUBLIC_1A"
ensure_assoc "$RTB_PUBLIC" "$SUBNET_PUBLIC_1B"

log "=== phase 4: NAT gateways + private routing (per AZ) ==="
ensure_eip EIP_1A "$ORG-$ENV-eip-nat-1a"
ensure_eip EIP_1B "$ORG-$ENV-eip-nat-1b"
ensure_nat NAT_1A "$ORG-$ENV-nat-1a" "$SUBNET_PUBLIC_1A" "$EIP_1A"
ensure_nat NAT_1B "$ORG-$ENV-nat-1b" "$SUBNET_PUBLIC_1B" "$EIP_1B"
ensure_rtb RTB_PRIVATE_1A "$ORG-$ENV-rtb-private-1a" app
ensure_rtb RTB_PRIVATE_1B "$ORG-$ENV-rtb-private-1b" app
ensure_route "$RTB_PRIVATE_1A" 0.0.0.0/0 --nat-gateway-id "$NAT_1A"
ensure_route "$RTB_PRIVATE_1B" 0.0.0.0/0 --nat-gateway-id "$NAT_1B"
ensure_assoc "$RTB_PRIVATE_1A" "$SUBNET_APP_1A"
ensure_assoc "$RTB_PRIVATE_1B" "$SUBNET_APP_1B"

log "=== phase 5: isolated data tier ==="
ensure_rtb RTB_DATA "$ORG-$ENV-rtb-data" data
ensure_assoc "$RTB_DATA" "$SUBNET_DATA_1A"
ensure_assoc "$RTB_DATA" "$SUBNET_DATA_1B"

log "=== phase 6: security groups ==="
ensure_sg SG_WEB  "$ORG-$ENV-sg-web"  "Public ALB nodes: terminates TLS from the internet"
ensure_sg SG_APP  "$ORG-$ENV-sg-app"  "Statement generation workers: private app tier"
ensure_sg SG_DB   "$ORG-$ENV-sg-db"   "PostgreSQL data tier: isolated, no egress"
ensure_sg SG_VPCE "$ORG-$ENV-sg-vpce" "Interface VPC endpoint ENIs: HTTPS from app tiers"

allow ingress "$SG_WEB" '[{"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTPS"}]},{"IpProtocol":"tcp","FromPort":80,"ToPort":80,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTP"}]}]'
allow ingress "$SG_APP" "[{\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_WEB\",\"Description\":\"ALB to app\"}]}]"
allow ingress "$SG_DB"  "[{\"IpProtocol\":\"tcp\",\"FromPort\":5432,\"ToPort\":5432,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"app to postgres\"}]}]"
allow ingress "$SG_VPCE" "[{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"app to endpoints\"},{\"GroupId\":\"$SG_WEB\",\"Description\":\"web to endpoints\"}]}]"

for g in "$SG_WEB" "$SG_APP" "$SG_DB" "$SG_VPCE"; do
  aws ec2 revoke-security-group-egress --group-id "$g" \
    --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null 2>&1 \
    && log "removed allow-all egress from $g" || true
done
allow egress "$SG_WEB" "[{\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"ALB to app\"}]},{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_VPCE\",\"Description\":\"AWS API\"}]}]"
allow egress "$SG_APP" "[{\"IpProtocol\":\"tcp\",\"FromPort\":5432,\"ToPort\":5432,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_DB\",\"Description\":\"app to postgres\"}]},{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_VPCE\",\"Description\":\"AWS API\"}]},{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\",\"Description\":\"OS updates via NAT\"}]}]"

log "=== phase 7: gateway endpoint for S3 ==="
VPCE_S3=$(aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$VPC_ID" \
  "Name=service-name,Values=com.amazonaws.$REGION.s3" \
  --query 'VpcEndpoints[0].VpcEndpointId' --output text 2>/dev/null)
if [ -z "$VPCE_S3" ] || [ "$VPCE_S3" = "None" ]; then
  VPCE_S3=$(aws ec2 create-vpc-endpoint --vpc-id "$VPC_ID" --vpc-endpoint-type Gateway \
    --service-name "com.amazonaws.$REGION.s3" \
    --route-table-ids "$RTB_PRIVATE_1A" "$RTB_PRIVATE_1B" "$RTB_DATA" \
    --tag-specifications "ResourceType=vpc-endpoint,Tags=[{Key=Name,Value=$ORG-$ENV-vpce-s3},$TAGS_COMMON]" \
    --query 'VpcEndpoint.VpcEndpointId' --output text) \
    && log "created S3 gateway endpoint $VPCE_S3" \
    || log "S3 gateway endpoint not supported by this build"
else
  log "reusing S3 gateway endpoint $VPCE_S3"
fi
[ -n "$VPCE_S3" ] && [ "$VPCE_S3" != "None" ] && setid VPCE_S3 "$VPCE_S3"

log "=== phase 8: emit topology.json ==="
python3 - "$VPC_ID" > "$HOME/vpc-lab/out/topology.json" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True, text=True).stdout or "{}")
def nm(o):
    return next((t["Value"] for t in o.get("Tags",[]) if t["Key"]=="Name"), None)
f = ["--filters", f"Name=vpc-id,Values={vpc}"]
doc = {
  "vpc": {k: v for k, v in aws("describe-vpcs","--vpc-ids",vpc)["Vpcs"][0].items()
          if k in ("VpcId","CidrBlock","State","CidrBlockAssociationSet",
                   "Ipv6CidrBlockAssociationSet")},
  "subnets": [{"Name": nm(s), "SubnetId": s["SubnetId"], "Cidr": s["CidrBlock"],
               "Az": s["AvailabilityZone"], "Free": s["AvailableIpAddressCount"],
               "MapPublicIp": s["MapPublicIpOnLaunch"],
               "Tier": next((t["Value"] for t in s.get("Tags",[]) if t["Key"]=="Tier"), None)}
              for s in sorted(aws("describe-subnets",*f)["Subnets"], key=lambda x: x["CidrBlock"])],
  "routeTables": [{"Name": nm(t), "RouteTableId": t["RouteTableId"],
                   "Main": any(a.get("Main") for a in t.get("Associations",[])),
                   "Subnets": [a["SubnetId"] for a in t.get("Associations",[]) if a.get("SubnetId")],
                   "Routes": [{k: r[k] for k in r
                               if k in ("DestinationCidrBlock","DestinationPrefixListId",
                                        "GatewayId","NatGatewayId","VpcPeeringConnectionId","State")}
                              for r in t.get("Routes",[])]}
                  for t in aws("describe-route-tables",*f)["RouteTables"]],
  "securityGroups": [{"Name": g["GroupName"], "GroupId": g["GroupId"],
                      "Ingress": g["IpPermissions"], "Egress": g.get("IpPermissionsEgress",[])}
                     for g in aws("describe-security-groups",*f)["SecurityGroups"]],
  "networkAcls": [{"Name": nm(a), "NetworkAclId": a["NetworkAclId"],
                   "IsDefault": a["IsDefault"],
                   "Subnets": [x["SubnetId"] for x in a.get("Associations",[])],
                   "Entries": a["Entries"]}
                  for a in aws("describe-network-acls",*f)["NetworkAcls"]],
  "natGateways": [{"Name": nm(n), "NatGatewayId": n["NatGatewayId"], "State": n["State"],
                   "SubnetId": n.get("SubnetId")}
                  for n in aws("describe-nat-gateways")["NatGateways"]
                  if n.get("VpcId") == vpc],
  "endpoints": [{"Name": nm(e), "VpcEndpointId": e["VpcEndpointId"],
                 "Type": e["VpcEndpointType"], "Service": e["ServiceName"],
                 "State": e["State"], "RouteTables": e.get("RouteTableIds",[]),
                 "Subnets": e.get("SubnetIds",[])}
                for e in aws("describe-vpc-endpoints",*f)["VpcEndpoints"]],
}
json.dump(doc, sys.stdout, indent=2, default=str)
PY
log "wrote out/topology.json ($(wc -c < "$HOME/vpc-lab/out/topology.json") bytes)"
log "=== build complete ==="
SH
chmod +x bin/build-vpc.sh
bash -n bin/build-vpc.sh && echo "syntax OK"
```

#### 12.2 Run it — twice

```bash
./bin/build-vpc.sh 2>&1 | tee out/lab12-build-run1.txt
echo "=================== SECOND RUN ==================="
./bin/build-vpc.sh 2>&1 | tee out/lab12-build-run2.txt
```

The second run must show **"reusing"** for every resource and **create nothing**:

```bash
grep -c 'created' out/lab12-build-run2.txt || echo "0 creations on re-run — idempotent"
grep -c 'reusing' out/lab12-build-run2.txt
```

!!! tip "This is what 'idempotent' means operationally"
    Not "the script does not crash on re-run", but "the second run makes zero changes". Prove it by counting. Anything that reports `created` twice is a bug — usually a lookup filtering on the wrong tag.

#### 12.3 Verification

```bash
. ~/vpc-lab/bin/ids.sh; loadids
python3 -c "import json;d=json.load(open('out/topology.json'));print(f\"vpc={d['vpc']['VpcId']} subnets={len(d['subnets'])} rtbs={len(d['routeTables'])} sgs={len(d['securityGroups'])} nacls={len(d['networkAcls'])} nats={len(d['natGateways'])} vpces={len(d['endpoints'])}\")"
./bin/verify-all.sh | tail -12
```

**Drift detection** — the operational payoff of `topology.json`:

```bash
cp out/topology.json out/topology.baseline.json
# make an unauthorised change
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"oops"}]}]' >/dev/null
./bin/build-vpc.sh >/dev/null 2>&1
diff <(python3 -m json.tool out/topology.baseline.json) \
     <(python3 -m json.tool out/topology.json) | head -25 \
  || echo "no drift"
```

```bash
# revert
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
./bin/build-vpc.sh >/dev/null 2>&1
./bin/verify-all.sh | tail -3
```

#### 12.4 Break it

**Break 1 — run the script with `AWS_ENDPOINT_URL` unset.**

*Correct behaviour:* it must refuse. Prove your safety rail works:

```bash
( unset AWS_ENDPOINT_URL; ./bin/build-vpc.sh 2>&1 | head -3 )
echo "exit status above should be non-zero and nothing should have been created"
```

**Break 2 — make the lookup non-idempotent.**

Change `ensure_sg` to filter on the wrong attribute and observe duplicates. Reason about it rather than doing it destructively: if `ensure_sg` looked up by `tag:Name` instead of `group-name`, and a previous run created the group but the tag call failed, the second run would try to create a group with a duplicate `GroupName` and fail with `InvalidGroup.Duplicate`. The lesson: **look up by the attribute AWS itself enforces as unique**, not by a tag you set separately.

#### 12.5 Fix it — the cross-module hook

Everything you have just written by hand is what CloudFormation, Terraform and CDK exist to do. In the **CloudFormation module** you will:

1. express this exact topology as a template with `AWS::EC2::VPC`, `Subnet`, `RouteTable`, `Route`, `SubnetRouteTableAssociation`, `InternetGateway`, `VPCGatewayAttachment`, `NatGateway`, `EIP`, `SecurityGroup`, `SecurityGroupIngress`, `NetworkAcl`, `NetworkAclEntry`, `SubnetNetworkAclAssociation` and `VPCEndpoint`;
2. deploy it into a fresh Floci instance;
3. diff the resulting `topology.json` against the one this script produced;
4. explain every difference — and in particular explain why CloudFormation's dependency graph makes `ensure_*` functions unnecessary, and where `DependsOn` is still required (hint: the `0.0.0.0/0 → igw` route needs the `VPCGatewayAttachment` to exist first, and CloudFormation cannot infer that).

```bash
cat > out/cfn-hook.md <<'MD'
# Carry-forward into the CloudFormation module

Deliverable: `dnb-dev-vpc.yaml` that reproduces out/topology.json exactly.

Resource-type mapping from this module's CLI calls:
| CLI call | CloudFormation resource |
|---|---|
| create-vpc | AWS::EC2::VPC |
| modify-vpc-attribute (dns) | EnableDnsSupport / EnableDnsHostnames properties |
| create-subnet | AWS::EC2::Subnet |
| modify-subnet-attribute --map-public-ip-on-launch | MapPublicIpOnLaunch property |
| create-internet-gateway + attach | AWS::EC2::InternetGateway + AWS::EC2::VPCGatewayAttachment |
| create-route-table | AWS::EC2::RouteTable |
| create-route | AWS::EC2::Route |
| associate-route-table | AWS::EC2::SubnetRouteTableAssociation |
| allocate-address | AWS::EC2::EIP |
| create-nat-gateway | AWS::EC2::NatGateway |
| create-security-group | AWS::EC2::SecurityGroup |
| authorize-security-group-ingress | SecurityGroupIngress property, or AWS::EC2::SecurityGroupIngress for circular refs |
| create-network-acl | AWS::EC2::NetworkAcl |
| create-network-acl-entry | AWS::EC2::NetworkAclEntry |
| replace-network-acl-association | AWS::EC2::SubnetNetworkAclAssociation |
| associate-vpc-cidr-block | AWS::EC2::VPCCidrBlock |
| create-vpc-endpoint | AWS::EC2::VPCEndpoint |

Two things to explain in that module:
1. Why mutually-referencing security groups need the standalone
   AWS::EC2::SecurityGroupIngress resource type instead of inline rules.
2. Why the default route needs DependsOn the VPCGatewayAttachment even
   though it references the InternetGateway.
MD
echo "hook written to out/cfn-hook.md"
```

#### 12.6 Recap of Lab 12

* Idempotence means the second run changes nothing — measure it, do not assume it.
* Look resources up by the attribute AWS enforces as unique, not by a tag applied in a separate call.
* Emitting `topology.json` gives you drift detection for free: build, diff, investigate.
* Bake the endpoint safety rail into the script itself, not only into your shell habits.
* Hand-rolled orchestration is a good teacher and a poor production tool — hence CloudFormation next.

---
## 6. Enterprise Scenario — Druk National Bank

### 6.1 The organisation

**Druk National Bank (DNB)** is a Bhutanese retail bank with 41 branches. It is migrating its **monthly statement generation platform** to AWS. The platform reads transaction data from a PostgreSQL database, renders PDF statements, writes them to S3, and serves them through a customer portal.

DNB is regulated by the **Royal Monetary Authority (RMA)**, and is audited annually by **KPMG Bhutan** (a separate AWS account, `333333333333`, established in Module 01).

Stakeholders, carried forward from Module 01:

| Name | Role | Network-relevant needs |
|---|---|---|
| Alice | backend developer | deploys statement workers; needs egress for package installs |
| Bob | team lead / delegated admin | approves network changes; owns the `dnb-dev` VPC |
| Carol | internal auditor | must be able to *prove* the data tier has no internet path |
| Dana | new graduate hire | read-only network access; must not be able to add routes |
| KPMG Bhutan | external auditor | receives flow log exports; never gets network access |

### 6.2 The requirements, as an auditor would write them

| # | Requirement | Source | How our design satisfies it |
|---|---|---|---|
| R1 | Customer account data must not reside in any subnet with a route to an internet gateway | RMA circular on data localisation | `rtb-data` contains `local` + the S3 prefix list only; asserted by `bin/assert-main-rtb-minimal.sh` and `bin/routing-report.sh` |
| R2 | All access to AWS service APIs from the data tier must be private | RMA | S3 gateway endpoint attached to `rtb-data`; endpoint policy restricted to two buckets |
| R3 | The platform must survive the loss of one availability zone | Board resilience policy | two AZs; per-AZ NAT gateway and per-AZ private route table; asserted by `bin/assert-nat-az-affinity.sh` |
| R4 | Database access must be restricted to the application tier, by identity not by address | RMA + internal standard | `sg-db` ingress references `sg-app`; zero CIDR literals; asserted by `bin/assert-sg-invariants.sh` |
| R5 | The database must not be able to initiate outbound connections | anti-exfiltration control | `sg-db` egress empty; `acl-data` egress rule 32766 deny; `rtb-data` has no default route |
| R6 | No administrative port may be reachable from the internet | RMA | no SSH/RDP rules anywhere; SSM Session Manager via interface endpoints is the access path |
| R7 | Every network resource must be attributable to a cost centre and an owner | Finance | five mandatory tags applied atomically at creation |
| R8 | Network flow metadata must be retained for 400 days | RMA audit trail | VPC flow logs to `dnb-audit-logs-dev` (conceptual in Floci; §4.19) |
| R9 | Only the platform team may create or modify routes | change control | IAM policy in §9.5 restricting `ec2:CreateRoute` and `ec2:ReplaceRoute` |
| R10 | The address plan must not collide with the branch network or with staging/production | hybrid roadmap | `out/ipam-record.md`; `dev`=10.20/16, `staging`=10.21/16, `prod`=10.22/16, branches=172.16/16 |

### 6.3 The architecture, annotated against the requirements

```
                     ┌──────────────────┐
   Customers ────────►│  Route 53 + ALB  │  (public DNS; ALB nodes in public subnets)
                      └────────┬─────────┘
                               │ R6: only 443/80 inbound; no admin ports
  ╔════════════════════════════╪══════════════════════════════════════════════════╗
  ║ dnb-dev-vpc  10.20.0.0/16  │           +100.64.0.0/16 (container overflow)     ║
  ║                            │                                                  ║
  ║  ┌── public-1a ───────┐    │    ┌── public-1b ───────┐                         ║
  ║  │ ALB node, nat-1a   │◄───┴───►│ ALB node, nat-1b   │   R3: one NAT per AZ    ║
  ║  │ sg-web             │         │ sg-web             │                         ║
  ║  └─────────┬──────────┘         └─────────┬──────────┘                         ║
  ║            │ 8080 (sg-web → sg-app)       │                                    ║
  ║  ┌─────────┴──────────┐         ┌─────────┴──────────┐                         ║
  ║  │ app-1a             │         │ app-1b             │   R4: SG referencing    ║
  ║  │ statement workers  │         │ statement workers  │                         ║
  ║  │ sg-app             │         │ sg-app             │                         ║
  ║  │ rtb-private-1a     │         │ rtb-private-1b     │                         ║
  ║  │  0/0 → nat-1a      │         │  0/0 → nat-1b      │                         ║
  ║  │  pl-s3 → vpce-s3   │         │  pl-s3 → vpce-s3   │   R2                    ║
  ║  │  vpce-sts ENI      │         │  vpce-sts ENI      │   R6: SSM path          ║
  ║  └─────────┬──────────┘         └─────────┬──────────┘                         ║
  ║            │ 5432 (sg-app → sg-db)        │                                    ║
  ║  ┌─────────┴──────────┐         ┌─────────┴──────────┐                         ║
  ║  │ data-1a            │         │ data-1b            │   R1: ISOLATED          ║
  ║  │ RDS primary        │         │ RDS standby        │   R5: no egress at all  ║
  ║  │ sg-db (no egress)  │         │ sg-db              │                         ║
  ║  │ acl-data           │◄─shared─┤ acl-data           │                         ║
  ║  │ rtb-data:          │         │ rtb-data           │                         ║
  ║  │   local            │         │                    │                         ║
  ║  │   pl-s3 → vpce-s3  │         │                    │   R2                    ║
  ║  │   NO 0.0.0.0/0     │         │                    │   R1                    ║
  ║  └────────────────────┘         └────────────────────┘                         ║
  ║                                                                                ║
  ║  Flow logs (VPC-level, TrafficType=ALL) ──► s3://dnb-audit-logs-dev/vpc/  R8    ║
  ╚════════════════════════════════════════════════════════════════════════════════╝
```

### 6.4 Carol's audit question, and how you answer it

Carol asks: *"Prove to me that a compromised database host cannot exfiltrate customer data to the internet."*

A weak answer describes the security group. A strong answer enumerates every independent control and shows the evidence:

```bash
cat > out/audit-response-R5.md <<'MD'
# Audit response: R5 — the data tier cannot initiate outbound connections

## Claim
A process with full control of a host in subnet `dnb-dev-subnet-data-1a`
cannot open a TCP connection to an arbitrary internet address.

## Independent controls, in AWS evaluation order

| # | Control | Configuration | Evidence |
|---|---------|---------------|----------|
| 1 | Security group egress | `dnb-dev-sg-db` has `IpPermissionsEgress: []` | out/lab05-sg.txt |
| 2 | Network ACL egress | `dnb-dev-acl-data` egress rule 32766 `deny 0.0.0.0/0`, then implicit `*` deny | out/lab06-*.txt |
| 3 | Routing | `dnb-dev-rtb-data` has no `0.0.0.0/0` route; only `local` and the S3 prefix list | out/lab04-routing.txt |
| 4 | Endpoint policy | `dnb-dev-vpce-s3` permits only the two DNB buckets | policies/vpce-s3-policy.json |
| 5 | No public address | data subnets have `MapPublicIpOnLaunch=false`; no EIP is associated to any data-tier ENI | out/lab02-subnets.txt |

Any ONE of controls 1, 2 or 3 is sufficient. All three are present, so this is
defence in depth rather than a single point of failure.

## Verification method
`bin/reach.py --from-subnet <data-1a> --to-ip 203.0.113.9 --port 443 --src-sg <sg-db>`
returns `AWS VERDICT: BLOCKED`, failing at steps 1, 2 and 3 independently.
Reproduced in `bin/reach-matrix.sh` as row `data internet 443 BLOCKED`.

## Residual risk (stated honestly)
1. The S3 gateway endpoint is a legitimate egress channel. A compromised host
   could write customer data to `dnb-statements-dev` — a bucket it is already
   authorised to use. Mitigation belongs to S3 and KMS, not to VPC: object
   ownership, bucket policies with `aws:SourceVpce`, and CloudTrail data events.
2. DNS exfiltration via the Amazon resolver at 10.20.0.2 is NOT blocked by any
   of the five controls, because DNS queries to the resolver do not traverse the
   route table and are not captured by flow logs. Mitigation: Route 53 Resolver
   DNS Firewall (AWS-only; not available in Floci).
3. Controls 1-4 are verified from CONFIGURATION, not from observed packet drops,
   because the emulator has no data plane. On real AWS the same claim should be
   re-verified with VPC Reachability Analyzer and with flow log evidence.
MD
echo "audit response written to out/audit-response-R5.md"
```

!!! tip "Point 2 above is what distinguishes a good answer from an excellent one"
    Naming the residual risk you have **not** closed — and saying which service closes it — is what a senior engineer does. Both of the residual risks listed are real and are commonly missed.

### 6.5 Recap of §6

The DNB scenario turns ten regulatory sentences into a specific set of API objects, and every requirement maps to an assertion script you can re-run. That mapping — requirement → configuration → automated evidence — is the deliverable a regulated employer actually wants from you.

---

## 7. Verification

Verification in VPC has three distinct levels. Confusing them is the most common error in student reports.

| Level | Question | Tool | Available in Floci? |
|---|---|---|---|
| **L1 Existence** | does the object exist with the properties I intended? | `describe-*` + `jq` / `--query` | ✅ yes |
| **L2 Intent** | does the *configuration as a whole* express the policy I designed? | `reach.py`, the assertion scripts, `topology.json` diffs | ✅ yes (computed) |
| **L3 Observation** | do packets actually behave that way? | Reachability Analyzer, flow logs, `curl`/`nc` from an instance | ❌ no — AWS only |

**Always state which level your evidence is.** "Verified at L2 by `reach.py`" is precise and honest. "Verified" is not.

### 7.1 The L1 command catalogue

```bash
# --- VPC ---
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].{Cidr:CidrBlock,State:State,Default:IsDefault,
           AllCidrs:CidrBlockAssociationSet[].CidrBlock,Dhcp:DhcpOptionsId}'
aws ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute enableDnsHostnames
aws ec2 describe-vpc-attribute --vpc-id "$VPC_ID" --attribute enableDnsSupport

# --- Subnets, with free-address accounting ---
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets,&CidrBlock)[].{Name:Tags[?Key==`Name`]|[0].Value,
           Cidr:CidrBlock,Az:AvailabilityZone,AzId:AvailabilityZoneId,
           Free:AvailableIpAddressCount,PubIp:MapPublicIpOnLaunch}' --output table

# --- Routing: the single most useful query in the module ---
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Name:Tags[?Key==`Name`]|[0].Value,
           Main:Associations[?Main==`true`]|[0].Main,
           Subnets:Associations[?SubnetId!=null].SubnetId,
           Routes:Routes[].[DestinationCidrBlock,DestinationPrefixListId,
                            GatewayId,NatGatewayId,VpcPeeringConnectionId,State]}' \
  --output json

# --- Blackholes: check this FIRST when something broke ---
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Table:RouteTableId,
           Dead:Routes[?State==`blackhole`].[DestinationCidrBlock,GatewayId,NatGatewayId]}' \
  --output json

# --- Security groups, in rule form ---
aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$SG_DB" \
  --query 'SecurityGroupRules[].{Id:SecurityGroupRuleId,Egress:IsEgress,
           Proto:IpProtocol,From:FromPort,To:ToPort,Cidr:CidrIpv4,
           RefSg:ReferencedGroupInfo.GroupId,Desc:Description}' --output table

# --- Network ACLs, in evaluation order ---
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries | sort_by(@, &RuleNumber)[].[RuleNumber,Egress,
           RuleAction,Protocol,CidrBlock,PortRange.From,PortRange.To]' --output text

# --- Gateways, NAT and endpoints ---
aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
  --query 'InternetGateways[].{Id:InternetGatewayId,Attachments:Attachments[].[VpcId,State]}'
aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$VPC_ID" \
  --query 'NatGateways[].{Id:NatGatewayId,State:State,Subnet:SubnetId,
           Ip:NatGatewayAddresses[0].PublicIp,Fail:FailureCode}' --output table
aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[].{Id:VpcEndpointId,Type:VpcEndpointType,Svc:ServiceName,
           State:State,Rtbs:RouteTableIds,Subnets:SubnetIds}' --output table

# --- ENIs: who is consuming addresses, and what blocks deletion ---
aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Subnet:SubnetId,
           Ip:PrivateIpAddress,Status:Status,Desc:Description,
           Owner:RequesterId,Sgs:Groups[].GroupName}' --output table

# --- Elastic IPs, including the billable orphans ---
aws ec2 describe-addresses \
  --query 'Addresses[].{Alloc:AllocationId,Ip:PublicIp,Assoc:AssociationId,
           Name:Tags[?Key==`Name`]|[0].Value}' --output table
```

### 7.2 Reading the output — the fields that actually matter

| Field | Where | What to conclude |
|---|---|---|
| `AvailableIpAddressCount` | subnet | total − 5 − ENIs. A surprising value means an unaccounted ENI |
| `MapPublicIpOnLaunch` | subnet | `true` on anything other than a genuine public subnet is a finding |
| `Associations[].Main` | route table | `true` plus a `0.0.0.0/0` route = every unassociated subnet is exposed |
| `Associations[].SubnetId` absent for a subnet | route table | that subnet uses the **main** table — usually a bug |
| `Route.State` | route | `blackhole` means the target is gone; traffic is silently dropped |
| `Route.Origin` | route | `CreateRouteTable` = implicit `local`; `CreateRoute` = yours; `EnableVgwRoutePropagation` = BGP |
| `DestinationPrefixListId` | route | a gateway endpoint route; do not hand-edit |
| `IpPermissions[].UserIdGroupPairs` | SG | identity-based rule — good |
| `IpPermissions[].IpRanges[].CidrIp == 0.0.0.0/0` | SG | acceptable only on genuinely public ports |
| `IpPermissionsEgress: []` | SG | intentional lockdown, not a bug |
| `Entries[].RuleNumber == 32767` | NACL | the implicit `*` deny; you cannot change it |
| `NatGateway.FailureCode` | NAT | `Gateway.NotAttached` = NAT is in a subnet with no IGW route |
| `VpcEndpoint.State` | endpoint | `available` ≠ reachable; check the endpoint's security group |
| `NetworkInterface.Description` | ENI | tells you which AWS service owns it — read before deleting |
| `Address.AssociationId == null` | EIP | billable orphan |

### 7.3 One command to produce the whole report

````bash
cat > bin/full-report.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
cd "$HOME/vpc-lab"
: "${VPC_ID:?}"
{
  echo "# VPC verification report"
  echo
  echo "Generated for VPC: $VPC_ID"
  echo
  echo "## L1 — existence"
  echo '```'
  ./bin/routing-report.sh
  echo '```'
  echo '```'
  aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'sort_by(Subnets,&CidrBlock)[].{Name:Tags[?Key==`Name`]|[0].Value,
             Cidr:CidrBlock,Az:AvailabilityZone,Free:AvailableIpAddressCount}' --output table
  echo '```'
  echo
  echo "## L1 — security groups"
  echo '```'
  ./bin/sg-report.sh
  echo '```'
  echo
  echo "## L2 — intent"
  echo '```'
  ./bin/reach-matrix.sh || true
  echo '```'
  echo '```'
  ./bin/verify-all.sh || true
  echo '```'
  echo
  echo "## L3 — observation"
  echo
  echo "NOT AVAILABLE. This build has no VPC data plane (see out/lab08-dataplane.txt)."
  echo "On real AWS, L3 evidence would come from VPC Reachability Analyzer and flow logs."
} > out/verification-report.md
echo "wrote out/verification-report.md"
SH
chmod +x bin/full-report.sh
./bin/full-report.sh
````

### 7.4 Recap of §7

Separate **existence** from **intent** from **observation**, name the level of every claim, and never let an emulator's silence pass for a passing test.

---

## 8. Troubleshooting

### 8.1 Error-to-cause reference

| Error code | Typical operation | Cause | Fix |
|---|---|---|---|
| `InvalidVpc.Range` | `create-vpc` | prefix outside `/16`–`/28` | choose a valid prefix; the primary cannot be resized later |
| `InvalidSubnet.Conflict` | `create-subnet` | CIDR overlaps an existing subnet | pick a free block; run `bin/assert-no-cidr-overlap.sh` first |
| `InvalidParameterValue` (subnet CIDR) | `create-subnet` | CIDR is not inside any VPC CIDR, or prefix > `/28` | fix the block, or add a secondary VPC CIDR first |
| `InvalidSubnetID.NotFound` | many | wrong id, wrong region, or resource in another VPC | check `AWS_DEFAULT_REGION` and the ledger |
| `InsufficientFreeAddressesInSubnet` | `run-instances`, `create-network-interface`, RDS/ELB creation | subnet exhausted (remember: −5) | delete stale ENIs, or add a larger subnet / secondary CIDR |
| `Resource.AlreadyAssociated` | `attach-internet-gateway` | the VPC already has an IGW, or the IGW is attached elsewhere | one IGW per VPC; detach first |
| `DependencyViolation` | `delete-subnet` | an ENI still lives in it (instance, RDS, NAT, endpoint, Lambda) | `describe-network-interfaces --filters Name=subnet-id,…` then remove the owner |
| `DependencyViolation` | `delete-security-group` | an ENI uses it, or another SG's rule references it | revoke referencing rules first; §16 does this |
| `DependencyViolation` | `delete-route-table` | explicit subnet associations remain, or it is the main table | disassociate, or accept that main tables are undeletable |
| `DependencyViolation` | `detach-internet-gateway` | an ENI in the VPC has a public IP or EIP | disassociate/release EIPs first |
| `DependencyViolation` | `delete-vpc` | anything at all remains | follow §16's order exactly |
| `CannotDelete` | `delete-security-group` | it is the default SG | you cannot; lock it down instead (§9.2) |
| `RouteAlreadyExists` | `create-route` | a route for that exact destination exists | use `replace-route` |
| `InvalidRoute.NotFound` | `delete-route` / `replace-route` | no route for that destination, or you targeted `local` | list routes first; `local` is immutable |
| `NetworkAclEntryAlreadyExists` | `create-network-acl-entry` | that rule number already exists in that direction | use `replace-network-acl-entry` |
| `NetworkAclEntryLimitExceeded` | `create-network-acl-entry` | 20 rules per direction reached | consolidate, or request a quota increase (max 40) |
| `RulesPerSecurityGroupLimitExceeded` | `authorize-*` | 60 rules reached; remember a multi-CIDR rule counts per CIDR, and a prefix-list rule counts as `MaxEntries` | use prefix lists sized tightly, or split groups |
| `SecurityGroupsPerInterfaceLimitExceeded` | `modify-network-interface-attribute` | more than 5 SGs on one ENI | consolidate rules into fewer groups |
| `AddressLimitExceeded` | `allocate-address` | 5 EIPs per Region reached | release orphans (`AssociationId == null`) or request an increase |
| `InvalidAllocationID.NotFound` | `associate-address` | wrong allocation id, or EIP in another region | EIPs are region-scoped |
| `Gateway.NotAttached` (NAT `FailureCode`) | `create-nat-gateway` | the NAT's subnet has no `0.0.0.0/0 → igw` route | put the NAT in a **public** subnet |
| `ErrorPortAllocation` (CloudWatch metric) | runtime | >55 000 simultaneous connections to one destination tuple through one NAT | add NAT gateways, or spread destinations |
| `InvalidServiceName` | `create-vpc-endpoint` | wrong region in `com.amazonaws.<region>.<svc>` | match the endpoint's region |
| `InvalidParameterCombination` | `create-vpc-endpoint` | `Gateway` type with `--subnet-ids`, or `Interface` with `--route-table-ids` | gateway takes route tables; interface takes subnets and SGs |
| `AccessDenied` mentioning `vpce-` | any S3/API call | the **endpoint policy** denies it | check the endpoint policy as well as IAM and the bucket policy |
| `InvalidVpcPeeringConnectionID` / peering `failed` | `create-vpc-peering-connection` | overlapping CIDRs, or request expired after 7 days | re-address one side, or use PrivateLink |
| `InvalidAction` | anything | the operation is not implemented by this emulator | check `out/support-matrix.tsv`; treat conceptually |

### 8.2 The six-question diagnostic ladder

When "it cannot connect", ask these in order. Each is a single command, and the order matters — routing before firewalls, because a misrouted packet never reaches a firewall.

```bash
cat > bin/diagnose.sh <<'SH'
#!/usr/bin/env bash
# diagnose.sh <source-subnet-id> <destination-ip>
# Walks the six-question ladder in AWS-evaluation order and prints findings.
set -uo pipefail
SRC_SUBNET="${1:?usage: diagnose.sh <src-subnet-id> <dst-ip>}"
DST_IP="${2:?usage: diagnose.sh <src-subnet-id> <dst-ip>}"

VPC=$(aws ec2 describe-subnets --subnet-ids "$SRC_SUBNET" \
        --query 'Subnets[0].VpcId' --output text)

echo "### Q1. Is the source subnet associated with the route table I think it is?"
assoc=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query "RouteTables[?Associations[?SubnetId=='$SRC_SUBNET']].RouteTableId" --output text)
if [ -z "$assoc" ] || [ "$assoc" = "None" ]; then
  echo "  FINDING: no explicit association -> this subnet uses the VPC MAIN table."
  assoc=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
    "Name=association.main,Values=true" --query 'RouteTables[0].RouteTableId' --output text)
fi
echo "  route table in effect: $assoc"

echo
echo "### Q2. Is there a route that matches the destination, and is it alive?"
aws ec2 describe-route-tables --route-table-ids "$assoc" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,NatGatewayId,State]' \
  --output text
echo "  (longest-prefix match wins; State=blackhole means the target was deleted)"

echo
echo "### Q3. Any blackhole routes anywhere in this VPC?"
bh=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query 'RouteTables[].Routes[?State==`blackhole`].DestinationCidrBlock' --output text)
[ -n "$bh" ] && [ "$bh" != "None" ] && echo "  FINDING: blackholes: $bh" || echo "  none"

echo
echo "### Q4. Which NACL applies to the source subnet, and what does it say?"
acl=$(aws ec2 describe-network-acls --filters "Name=association.subnet-id,Values=$SRC_SUBNET" \
  --query 'NetworkAcls[0].NetworkAclId' --output text)
echo "  NACL: $acl"
aws ec2 describe-network-acls --network-acl-ids "$acl" \
  --query 'NetworkAcls[0].Entries | sort_by(@,&RuleNumber)[].[RuleNumber,Egress,RuleAction,Protocol,CidrBlock,PortRange.From,PortRange.To]' \
  --output text
echo "  (STATELESS: check BOTH directions, and the ephemeral range 1024-65535 on the return path)"

echo
echo "### Q5. Are the security groups allow-only rules present in BOTH directions?"
echo "  run: aws ec2 describe-security-group-rules --filters Name=group-id,Values=<sg>"
echo "  (STATEFUL: return traffic is automatic; only the initiating direction needs a rule)"

echo
echo "### Q6. Does the destination even have a free address / is the ENI healthy?"
aws ec2 describe-network-interfaces --filters "Name=addresses.private-ip-address,Values=$DST_IP" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Subnet:SubnetId,Status:Status,Sgs:Groups[].GroupName}' \
  --output json

echo
echo "### Now compute the AWS verdict:"
echo "  python3 bin/reach.py --from-subnet $SRC_SUBNET --to-ip $DST_IP --port <port> \\"
echo "      --src-sg <sg> [--to-subnet <subnet> --dst-sg <sg>]"
SH
chmod +x bin/diagnose.sh
./bin/diagnose.sh "$SUBNET_APP_1A" 10.20.64.10 | head -40
```

### 8.3 Symptom-to-cause table — what production actually looks like

| Symptom | Most likely cause | First command |
|---|---|---|
| Connection **refused** immediately | the service is not listening; **not** a network problem | check the application, not the VPC |
| Connection **hangs / times out** | a firewall is dropping (not rejecting) — SG or NACL | `reach.py`; then check the NACL ephemeral rule |
| Works one way, hangs the other | **stateless NACL** missing the ephemeral return rule | `bin/lint-nacl.sh` |
| Worked yesterday, broken today, nothing changed in the app | **blackhole route** — someone deleted a NAT gateway or peering | `describe-route-tables … State==blackhole` |
| Some instances work, others do not | subnets on **different route tables**, or one subnet implicitly on the main table | `bin/routing-report.sh` |
| Works in AZ-a, fails in AZ-b | cross-AZ NAT, or a missing per-AZ route table / endpoint ENI | `bin/assert-nat-az-affinity.sh` |
| Instance cannot reach the internet despite `0.0.0.0/0 → igw` | it has **no public IP** — the fourth condition of §4.5 | `describe-instances … PublicIpAddress` |
| AWS API calls hang from a private subnet | interface endpoint SG blocks 443, or private DNS resolves to an unreachable ENI | `describe-vpc-endpoints`, then the SG |
| `AccessDenied` on S3 from a private subnet only | **endpoint policy** | `describe-vpc-endpoints --query '…PolicyDocument'` |
| RDS endpoint does not resolve | `enableDnsSupport` or `enableDnsHostnames` is `false` | `describe-vpc-attribute` |
| New pods/tasks stop scheduling | subnet IP exhaustion | `AvailableIpAddressCount` |
| Cannot delete anything | `DependencyViolation`, always an ENI or an association | `describe-network-interfaces` |
| Surprise bill | NAT gateway data processing, unassociated EIPs, cross-AZ transfer | S3/DynamoDB gateway endpoints; EIP sweep |

### 8.4 Recap of §8

Diagnose **routing before firewalls**, because a packet with no route never reaches a rule. `DependencyViolation` always means "find the ENI or the association". A hang means a drop (firewall); a refusal means the application. And check for blackholes first when something that worked stops working.

---

## 9. Security Best Practices

### 9.1 Least privilege at the network layer

| Principle | Concretely | Anti-pattern |
|---|---|---|
| Reference identity, not location | `sg-db` ingress from `sg-app` | ingress from `10.20.0.0/16` |
| Public only what must be public | ALB and NAT in public subnets; nothing else | app servers with public IPs "for debugging" |
| Isolate, do not merely privatise | data tier route table has **no** default route | data tier behind NAT "because patching" |
| Restrict egress | `sg-db` egress empty; `sg-app` egress enumerated | leaving the default allow-all egress everywhere |
| No administrative ingress | zero SSH/RDP rules; SSM Session Manager instead | `0.0.0.0/0` on 22 "temporarily" |
| Coarse policy in NACLs, fine policy in SGs | `acl-data` blanket-denies non-app traffic | 20 application-specific NACL rules |
| Keep the main route table empty | `local` only; every subnet associated explicitly | a default route on the main table |

### 9.2 Lock down the default security group and default NACL

Anything accidentally launched without an explicit security group lands in the default SG. Make that harmless:

```bash
# Strip the default SG's self-referencing ingress and allow-all egress
aws ec2 revoke-security-group-ingress --group-id "$SG_DEFAULT" \
  --ip-permissions "[{\"IpProtocol\":\"-1\",\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_DEFAULT\"}]}]" \
  2>&1 | head -2
aws ec2 revoke-security-group-egress --group-id "$SG_DEFAULT" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' 2>&1 | head -2

aws ec2 describe-security-groups --group-ids "$SG_DEFAULT" \
  --query 'SecurityGroups[0].{In:IpPermissions,Out:IpPermissionsEgress}' --output json
```

Expected: both lists empty. Anything landing in the default SG is now fully isolated, which converts a silent misconfiguration into a loud failure.

!!! tip "Loud failures beat silent exposure"
    This is a general principle worth internalising. An empty default SG means a forgotten `--security-group-ids` produces an immediate, obvious connectivity failure instead of a working-but-overexposed resource nobody notices for a year.

### 9.3 Secure configuration checklist

```bash
cat > bin/security-audit.sh <<'SH'
#!/usr/bin/env bash
# VPC security audit. Every finding is something an auditor would raise.
set -uo pipefail
: "${VPC_ID:?}"
python3 - "$VPC_ID" <<'PY'
import json, subprocess, sys
vpc = sys.argv[1]
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True,text=True).stdout or "{}")
def nm(o, d="-"):
    return next((t["Value"] for t in o.get("Tags",[]) if t["Key"]=="Name"), d)
F = ["--filters", f"Name=vpc-id,Values={vpc}"]
findings = []
def add(sev, msg): findings.append((sev, msg))

# 1. admin ports open to the world
for g in aws("describe-security-groups",*F)["SecurityGroups"]:
    for p in g["IpPermissions"]:
        lo, hi = p.get("FromPort"), p.get("ToPort")
        for r in p.get("IpRanges",[]) + p.get("Ipv6Ranges",[]):
            cidr = r.get("CidrIp") or r.get("CidrIpv6")
            if cidr not in ("0.0.0.0/0","::/0"):
                continue
            if lo is None:
                add("CRITICAL", f"SG {g['GroupName']}: ALL ports open to {cidr}")
            elif any(lo <= q <= hi for q in (22,3389,5432,3306,1433,27017,6379,9200,2049)):
                add("CRITICAL", f"SG {g['GroupName']}: sensitive port {lo}-{hi} open to {cidr}")

# 2. the main route table must be minimal
for t in aws("describe-route-tables",*F)["RouteTables"]:
    is_main = any(a.get("Main") for a in t.get("Associations",[]))
    has_igw = any(str(r.get("GatewayId","")).startswith("igw-") for r in t.get("Routes",[]))
    if is_main and has_igw:
        add("CRITICAL", f"main route table {t['RouteTableId']} has an IGW route: "
                        "every unassociated subnet is internet-exposed")
    if any(r.get("State")=="blackhole" for r in t.get("Routes",[])):
        add("HIGH", f"route table {nm(t,t['RouteTableId'])} has blackhole route(s)")

# 3. data-tier subnets must not be public
subs = aws("describe-subnets",*F)["Subnets"]
rts  = aws("describe-route-tables",*F)["RouteTables"]
expl = {a["SubnetId"]: t for t in rts for a in t.get("Associations",[]) if a.get("SubnetId")}
main = next((t for t in rts for a in t.get("Associations",[]) if a.get("Main")), None)
for s in subs:
    tier = next((t["Value"] for t in s.get("Tags",[]) if t["Key"]=="Tier"), None)
    t = expl.get(s["SubnetId"], main)
    public = t and any(r.get("DestinationCidrBlock")=="0.0.0.0/0"
                       and str(r.get("GatewayId","")).startswith("igw-") for r in t.get("Routes",[]))
    if tier == "data" and public:
        add("CRITICAL", f"data subnet {nm(s)} has an internet path")
    if s["SubnetId"] not in expl:
        add("MEDIUM", f"subnet {nm(s)} has no explicit route table association")
    if s["MapPublicIpOnLaunch"] and tier not in ("public", None):
        add("HIGH", f"non-public subnet {nm(s)} auto-assigns public IPs")

# 4. tagging discipline
REQUIRED = {"Project","Environment","Owner","CostCenter","ManagedBy"}
for kind, items, key in (("subnet", subs, "SubnetId"),
                         ("route-table", rts, "RouteTableId")):
    for o in items:
        have = {t["Key"] for t in o.get("Tags",[])}
        missing = REQUIRED - have
        if missing and not any(a.get("Main") for a in o.get("Associations",[])):
            add("LOW", f"{kind} {o[key]} missing tags: {','.join(sorted(missing))}")

# 5. orphaned Elastic IPs
for a in aws("describe-addresses").get("Addresses",[]):
    if not a.get("AssociationId"):
        add("MEDIUM", f"unassociated Elastic IP {a.get('PublicIp')} "
                      f"({a.get('AllocationId')}) — billed while idle")

# 6. default security group should be empty
for g in aws("describe-security-groups",*F)["SecurityGroups"]:
    if g["GroupName"] == "default" and (g["IpPermissions"] or g.get("IpPermissionsEgress")):
        add("MEDIUM", "default security group still has rules — lock it down (Section 9.2)")

# 7. NACL statelessness hazards
for a in aws("describe-network-acls",*F)["NetworkAcls"]:
    if a["IsDefault"]:
        continue
    eg = [e for e in a["Entries"] if e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"]<32767]
    ing = [e for e in a["Entries"] if not e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"]<32767]
    if ing and not eg:
        add("HIGH", f"NACL {nm(a,a['NetworkAclId'])} allows ingress but has no egress allows: "
                    "all return traffic will be dropped")

order = {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3}
print(f"{len(findings)} finding(s)\n")
for sev, msg in sorted(findings, key=lambda x: order[x[0]]):
    print(f"  [{sev:8}] {msg}")
sys.exit(1 if any(s in ("CRITICAL","HIGH") for s,_ in findings) else 0)
PY
SH
chmod +x bin/security-audit.sh
./bin/security-audit.sh | tee out/security-audit.txt
```

### 9.4 Credential and access management for network resources

* **Never** put credentials or connection strings in `--user-data`. User data is readable from the instance metadata service by any process on the host, and by anything that can reach `169.254.169.254`. Use Secrets Manager via an interface endpoint plus an instance profile.
* **Enforce IMDSv2** on every instance: `--metadata-options HttpTokens=required,HttpPutResponseHopLimit=1`. This is the mitigation for the SSRF-to-credential-theft attack chain, and the hop limit stops a container from reaching the host's metadata.
* **Use SSM Session Manager instead of SSH.** It requires interface endpoints for `ssm`, `ssmmessages` and `ec2messages`, an instance profile with `AmazonSSMManagedInstanceCore`, and **no inbound rule of any kind**. Every session is logged to CloudTrail and optionally to S3. This is the single best security improvement available to most VPCs.
* **Do not create key pairs you do not need.** Lab 8 created one to complete the pattern; a production build with SSM does not need one.

### 9.5 IAM controls over the network layer (R9)

Network changes are the highest-blast-radius changes in a VPC. Constrain them:

```bash
cat > policies/network-change-control.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadEverythingNetwork",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:GetManagedPrefixListEntries",
        "ec2:SearchTransitGatewayRoutes"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyInternetExposingRoutes",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:DeleteRoute"
      ],
      "Resource": "arn:aws:ec2:us-east-1:000000000000:route-table/*",
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalTag/Team": "platform"
        }
      }
    },
    {
      "Sid": "DenyTouchingTheDataTier",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:AssociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:DeleteNetworkAclEntry",
        "ec2:ReplaceNetworkAclEntry",
        "ec2:ReplaceNetworkAclAssociation"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "ec2:ResourceTag/Tier": "data"
        },
        "StringNotEquals": {
          "aws:PrincipalTag/Team": "platform"
        }
      }
    },
    {
      "Sid": "DenyCreatingUntaggedNetworkResources",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateVpc",
        "ec2:CreateSubnet",
        "ec2:CreateRouteTable",
        "ec2:CreateSecurityGroup",
        "ec2:CreateNetworkAcl",
        "ec2:CreateNatGateway",
        "ec2:AllocateAddress"
      ],
      "Resource": "*",
      "Condition": {
        "Null": {
          "aws:RequestTag/CostCenter": "true"
        }
      }
    },
    {
      "Sid": "DenyDeletingTheVpcItself",
      "Effect": "Deny",
      "Action": [
        "ec2:DeleteVpc",
        "ec2:DeleteInternetGateway",
        "ec2:DetachInternetGateway"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalTag/Team": "platform"
        }
      }
    }
  ]
}
JSON
python3 -c "import json;json.load(open('policies/network-change-control.json'));print('policy parses OK')"
```

**The VPC-relevant IAM condition keys worth knowing:**

| Condition key | Applies to | Use |
|---|---|---|
| `ec2:Vpc` | subnet, SG, route table operations | restrict a principal to one VPC: `"ec2:Vpc": "arn:aws:ec2:…:vpc/vpc-abc"` |
| `ec2:ResourceTag/Tier` | tagged resources | protect the data tier, as above |
| `aws:RequestTag/*`, `aws:TagKeys` | create operations | enforce mandatory tags at creation |
| `ec2:AvailabilityZone` | subnet/instance creation | confine a team to specific AZs |
| `ec2:InstanceType` | `RunInstances` | cost control |
| `aws:SourceVpc`, `aws:SourceVpce` | **resource** policies (S3, KMS, Secrets Manager) | "this bucket is readable only from our VPC / through our endpoint" |
| `aws:PrincipalTag/*` | any | ABAC, as used above for `Team=platform` |

!!! note "`aws:SourceVpc` belongs on the resource policy, not the identity policy"
    It is populated only when the request arrives through a VPC endpoint. That makes it a control the **data owner** applies (bucket policy), not one the caller applies — which is exactly what you want for an anti-exfiltration guarantee.

### 9.6 Encryption, logging and auditing

| Concern | Control | Notes |
|---|---|---|
| Data in transit inside the VPC | TLS at the application layer | VPC traffic between instances is *not* encrypted by AWS by default; Nitro instances encrypt some inter-instance traffic transparently, but do not rely on it |
| Data in transit to AWS services | TLS, kept private with endpoints | endpoints do not add encryption; they change the **path** |
| Hybrid links | IPSec (VPN) or MACsec / IPSec over Direct Connect | DX alone is private but **unencrypted** |
| Network flow audit | VPC flow logs, VPC-level, `TrafficType=ALL`, to S3 with Parquet + Hive partitioning | 400-day retention for R8; query with Athena |
| DNS audit | Route 53 Resolver query logging | catches DNS-based exfiltration that flow logs miss |
| Control-plane audit | CloudTrail; alarm on `CreateRoute`, `AuthorizeSecurityGroupIngress`, `DeleteNetworkAclEntry`, `AttachInternetGateway`, `CreateVpcPeeringConnection` | these five events are the ones that change your exposure |
| Continuous compliance | AWS Config rules: `vpc-sg-open-only-to-authorized-ports`, `vpc-default-security-group-closed`, `vpc-flow-logs-enabled`, `subnet-auto-assign-public-ip-disabled`, `restricted-ssh` | the managed-rule equivalents of `bin/security-audit.sh` |

### 9.7 Tagging strategy

| Tag | Values | Purpose |
|---|---|---|
| `Name` | `dnb-dev-<kind>-<qualifier>` | human identification; drives cleanup |
| `Project` | `CoreBanking` | cost allocation |
| `Environment` | `dev` \| `staging` \| `prod` | prevents cross-environment mistakes; usable in IAM conditions |
| `Owner` | `platform-team` | escalation path |
| `CostCenter` | `CC-4400` | chargeback; enforced at creation by the policy in §9.5 |
| `ManagedBy` | `floci-lab` \| `cloudformation` | tells you whether hand-editing is safe |
| `Tier` | `public` \| `app` \| `data` | drives the reachability matrix, NACL assignment and the IAM data-tier guard |

Apply tags with `--tag-specifications` at creation, atomically. Verify:

```bash
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[?!not_null(Tags[?Key==`CostCenter`])].SubnetId' --output text
# should print nothing
```

### 9.8 Cost as a security concern

An unbounded bill is an availability incident. The VPC-specific cost levers:

| Lever | Saving | Action |
|---|---|---|
| S3 / DynamoDB gateway endpoints | removes NAT data-processing charges on the largest traffic source | free; add on day one |
| Right-sized NAT gateway count | one per AZ, not one per subnet | check `describe-nat-gateways` |
| Per-AZ routing | removes cross-AZ data transfer | `bin/assert-nat-az-affinity.sh` |
| EIP hygiene | unassociated EIPs are billed | sweep for `AssociationId == null` |
| Public IPv4 addresses | all public IPv4 has been charged hourly since Feb 2024 | remove public IPs from anything that does not need one |
| Interface endpoints | charged per ENI-hour per AZ | create only the services you actually call |
| Delete the default VPC | its IGW is free, but accidental launches into it are not | §4.22 |

### 9.9 Recap of §9

Least privilege at the network layer means identity-based security groups, isolated data tiers, explicitly enumerated egress, no administrative ingress, and a locked-down default security group so mistakes fail loudly. Wrap all of it in IAM change control over `CreateRoute` and friends, and in flow logs plus CloudTrail alarms so exposure changes are visible.

---

## 10. Service Integration

### 10.1 How other services consume VPC constructs

| Service | What it needs from the VPC | Gotcha | Floci |
|---|---|---|---|
| **EC2** | subnet + security groups; optional public IP | SGs attach to ENIs, not instances; a `t3.micro` supports far fewer secondary IPs than a `m5.24xlarge` | ⚠️ metadata only |
| **Auto Scaling** | a list of subnets, ideally one per AZ | ASG balances across the subnets you list; list only one and you have no AZ redundancy | ⚠️ |
| **ALB / NLB** | **≥2 subnets in ≥2 AZs**, at least a `/28` each with 8 free IPs | ALB needs 8+ free IPs per subnet and scales by consuming more; NLB gives one static IP per AZ and preserves the client source IP, so **security groups on targets must allow the client CIDR**, not the NLB | ❌ ELB not covered here |
| **RDS** | a **DB subnet group** spanning ≥2 AZs, normally private/isolated subnets | the subnet group is created once and is hard to change later; Multi-AZ requires two AZs; the RDS ENI blocks subnet deletion | ⚠️ RDS runs as a container in Floci |
| **Lambda (VPC-attached)** | subnets + security groups | AWS creates **Hyperplane ENIs** shared across executions; a VPC-attached Lambda has **no internet access** unless you route through a NAT gateway; it needs interface endpoints for AWS APIs. Attaching to a VPC only to reach RDS is a common but costly reflex | ⚠️ |
| **ECS (`awsvpc` mode)** | a subnet + SGs **per task** | each task consumes a subnet IP; ENI-per-task density is capped per instance type; Fargate tasks in private subnets need a NAT or endpoints to pull from ECR | ⚠️ |
| **EKS** | subnets tagged for the cluster; the VPC CNI assigns **a subnet IP per pod** | this is the #1 cause of IP exhaustion; secondary CIDRs from `100.64.0.0/10` and prefix delegation are the standard mitigations | ⚠️ |
| **S3** | nothing — unless you want the traffic private | gateway endpoint (free) plus a bucket policy with `aws:SourceVpc`; note a gateway endpoint only affects traffic **from within the VPC** | ✅ endpoint object |
| **DynamoDB** | same as S3 | gateway endpoint only; there is no interface endpoint for the classic DynamoDB API | ⚠️ |
| **CloudWatch Logs** | reachability to the `logs` endpoint | a private subnet with no NAT and no `logs` interface endpoint means the CloudWatch agent silently fails | ⚠️ |
| **Route 53** | private hosted zones associated with the VPC; both DNS attributes `true` | a custom DHCP `domain-name-servers` breaks this | ⚠️ |
| **Secrets Manager / KMS / STS** | interface endpoints for private access | if the endpoint SG blocks 443, every SDK call hangs with no useful error | ⚠️ |
| **CloudFormation** | expresses every object in this module | the `0.0.0.0/0 → igw` route needs `DependsOn` the `VPCGatewayAttachment` | ⚠️ |
| **IAM** | `ec2:Vpc`, `ec2:ResourceTag/*`, `aws:SourceVpc`, `aws:SourceVpce` | `aws:SourceVpc` only appears on requests that came through an endpoint | ✅ |

### 10.2 The integration you should actually build: private access to S3

This is the concrete link back to the S3 module, and it demonstrates the full pattern.

```bash
# 1. The buckets from the S3/IAM modules
aws s3api create-bucket --bucket dnb-statements-dev 2>/dev/null \
  && echo "created dnb-statements-dev" || echo "dnb-statements-dev already exists (or S3 unsupported)"
aws s3api create-bucket --bucket dnb-audit-logs-dev 2>/dev/null \
  && echo "created dnb-audit-logs-dev" || echo "dnb-audit-logs-dev already exists (or S3 unsupported)"

# 2. The bucket policy that closes the loop: readable ONLY through our endpoint
cat > policies/bucket-sourcevpce.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnlessThroughDnbEndpoint",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:SourceVpce": "${VPCE_S3:-vpce-REPLACE-ME}"
        }
      }
    }
  ]
}
JSON
python3 -c "import json;json.load(open('policies/bucket-sourcevpce.json'));print('bucket policy parses OK')"

aws s3api put-bucket-policy --bucket dnb-statements-dev \
  --policy file://policies/bucket-sourcevpce.json 2>&1 | head -2 \
  || echo "note: put-bucket-policy may be unsupported; the policy is still the deliverable"
```

!!! danger "Think before you apply `aws:SourceVpce` in production"
    This policy denies **everything** that does not arrive through that one endpoint — including your own laptop, CloudFormation, the console, and any cross-region replication. Deploy it with a carve-out for a break-glass role, and test it in `dev` first. A bucket you have locked yourself out of is recoverable only by the account root user.

### 10.3 The two-question test for "should this be in a VPC?"

Students over-apply VPC attachment. Use this:

```
  Does the resource need to reach something that ONLY exists inside a VPC
  (an RDS instance in a private subnet, an internal NLB, an on-prem system)?
        │
        ├── no ──► do NOT attach it. A VPC-attached Lambda costs you cold-start
        │          ENI setup, NAT charges for internet access, and endpoint
        │          hours for AWS API access — for nothing.
        │
        └── yes ─► attach it, and then:
                    • put it in PRIVATE subnets, one per AZ
                    • give it its OWN security group (never a shared one)
                    • add interface endpoints for every AWS API it calls
                    • add a NAT route only if it must reach the public internet
```

### 10.4 Recap of §10

Every service that has an IP address is a consumer of subnets and security groups, so almost every "why can't service X reach Y" question is a VPC question. The two patterns to internalise: **ELB and RDS need ≥2 AZs**, and **anything in a private subnet needs either a NAT route or an interface endpoint for every AWS API it calls** — with the endpoint's security group allowing 443.

---
## 11. Mini Challenges

Complete these **without guidance**. Each one is independent of the others but assumes the Lab 1–12 topology exists. Difficulty increases. For every challenge submit: the commands you ran, the verification output, and — where the challenge concerns traffic — the `reach.py` verdict with its seven-step trace.

!!! warning "Clean up after each challenge"
    Every resource you create here must be tagged `Project=CoreBanking` and `ManagedBy=floci-lab` with a `Name` starting `dnb-`, so that §16's sweep finds it. An untagged resource you forget is a real bill in a real account.

### Challenge 1 — A third availability zone (⭐)

Extend the topology into `us-east-1c` (or your build's third AZ): one public, one app and one data subnet, drawn from the reserved `10.20.96.0/20` and `10.20.112.0/20` blocks; a third NAT gateway; a third private route table; correct associations.

**Acceptance:** `bin/routing-report.sh` shows nine subnets, all `explicit`; `bin/assert-nat-az-affinity.sh` passes; `bin/assert-no-cidr-overlap.sh` passes. You must fit both new tiers inside the reserved blocks without overlapping anything, and you must not exceed the reserved space.

### Challenge 2 — A bastion-free administrative path (⭐)

Add the four interface endpoints SSM Session Manager requires (`ssm`, `ssmmessages`, `ec2messages`, and `kms` for encrypted sessions) in both app subnets, sharing `sg-vpce`. Then write, in `out/challenge2.md`, the complete list of what a private instance needs for Session Manager to work: the endpoints, the instance profile policy, the agent, and — critically — **which inbound security group rules are required** (the answer is none).

**Acceptance:** endpoints `available`; a short written argument for why this is more secure than a bastion host with a `0.0.0.0/0` rule on port 22, covering audit trail, credential handling and attack surface.

### Challenge 3 — A managed prefix list for the branch network (⭐⭐)

DNB has 41 branches, each with a static `/32`. Create a customer-managed prefix list `dnb-dev-pl-branches` containing five representative `/32`s from `203.0.113.0/24`, sized so it does not consume your whole security-group rule budget. Reference it from a single `sg-web` ingress rule on TCP 443. Then compute and document: how many of `sg-web`'s 60 inbound rules the reference consumes, and what happens if you set `MaxEntries` to 200.

**Acceptance:** one SG rule with a `PrefixListIds` entry; a written calculation of the rule-budget cost; a statement of what breaks at `MaxEntries=200`.

### Challenge 4 — Prove the data tier cannot be reached from the internet (⭐⭐)

Without changing any configuration, produce a **written proof** with evidence that an attacker on the public internet cannot open a TCP connection to `10.20.64.10:5432`. Enumerate every control in AWS evaluation order and state, for each, whether it is *necessary*, *sufficient*, or *neither*. Include `reach.py` output for at least three distinct attack paths — direct, via the public subnet, and via the app tier.

**Acceptance:** the argument distinguishes necessary from sufficient controls correctly and identifies at least one control that is *neither* (i.e. removing it alone would not enable the attack).

### Challenge 5 — Extend `reach.py` to model the NAT source rewrite (⭐⭐⭐)

Currently the evaluator checks the destination side using the *source instance's* IP. That is wrong for traffic traversing a NAT gateway: the destination sees the **NAT gateway's** address, not the instance's. Modify `reach.py` so that when step 3 selects a `NatGatewayId` target, subsequent destination-side checks use the NAT gateway's public IP (from `describe-nat-gateways`) and the return-path ephemeral range becomes `1024–65535`.

**Acceptance:** `bin/reach-matrix.sh` still passes all eight rows; add a new matrix row proving that a host on the internet cannot reply to an app-tier instance on an unsolicited port; a short note on why this matters for NACLs on public subnets.

### Challenge 6 — Isolate the overflow subnet with an explicit NACL (⭐⭐⭐)

The `100.64.0.0/20` overflow subnet from Lab 9 will host container workloads. Build `dnb-dev-acl-overflow` allowing: inbound 8080 from both app subnets, inbound ephemeral return traffic from the S3 prefix range, outbound 443 to anywhere, and outbound ephemeral to the app subnets — and denying everything else, with a visible `32766 deny`. Stay within the 20-rule-per-direction budget and document your rule numbering scheme.

**Acceptance:** `bin/lint-nacl.sh` reports no findings for the new NACL; the rule count per direction is ≤20; the numbering leaves insertion gaps.

### Challenge 7 — Design for 50 000 pods (⭐⭐⭐⭐)

DNB's platform team wants to run EKS with the VPC CNI, where **every pod consumes a subnet IP**. Write `out/challenge7.md` containing: an addressing plan for 50 000 pods across three AZs; a justification of why `10.20.0.0/16` alone cannot do it; the secondary-CIDR strategy; the interaction with the 200-subnets-per-VPC and 5-CIDRs-per-VPC quotas; and the two AWS mitigations (secondary CIDR from `100.64.0.0/10`, and prefix delegation) with the trade-offs of each. Then *implement* the secondary-CIDR portion for one AZ.

**Acceptance:** the arithmetic is correct and shown; the plan does not exceed any quota without saying which increase it requires; the implemented subnet passes `bin/assert-no-cidr-overlap.sh`.

### Challenge 8 — Centralised egress inspection (⭐⭐⭐⭐)

Design (do not build — most of it is unsupported) a centralised egress architecture: a separate inspection VPC containing AWS Network Firewall, a transit gateway with two route tables (spoke and inspection), and appliance mode enabled. Produce an ASCII diagram, the TGW route table associations and propagations, and the packet walk for a request from `dnb-dev-subnet-app-1a` to `https://example.com` and back. Explain what breaks without appliance mode.

**Acceptance:** the packet walk is complete in both directions and names the route table consulted at each hop; the appliance-mode explanation correctly identifies flow asymmetry across AZs as the failure.

### Challenge 9 — A migration you cannot roll back (⭐⭐⭐⭐⭐)

DNB acquires a competitor whose VPC also uses `10.20.0.0/16`. The two networks must exchange traffic on exactly one service (TCP 8443 on three hosts). Peering is impossible. Write `out/challenge9.md` presenting: why peering fails; **three** viable alternatives (PrivateLink endpoint service, re-addressing one side, and a proxy/NAT tier) with a comparison table covering effort, downtime, cost, blast radius and reversibility; your recommendation with justification; and the migration plan for the recommended option including the rollback step at each stage.

**Acceptance:** all three alternatives are technically correct; PrivateLink is correctly identified as the option that tolerates overlapping CIDRs; each migration stage has an explicit rollback.

---

## 12. Debugging Challenges

Each scenario below **breaks the working topology deliberately**. Apply the break, then diagnose it using only `describe-*`, `bin/diagnose.sh` and `reach.py` — do not read the hint until you have written down your diagnosis. Then fix it and confirm `bin/verify-all.sh` passes.

Snapshot first, so you can always recover:

```bash
cp out/topology.json out/topology.pre-debug.json
echo "snapshot saved"
```

### Scenario 1 — "The app tier lost internet access this morning"

```bash
aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_1A"
sleep 5
```

**Symptom.** `yum update` on instances in `app-1a` times out. Instances in `app-1b` are fine. Nobody changed a security group.

??? note "Hint 1"
    Compare the two private route tables. What does the `State` field of the default route say?

??? note "Hint 2"
    `aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" --query 'RouteTables[].Routes[?State==`blackhole`]'`

??? note "Diagnosis and fix"
    **Diagnosis.** Deleting a NAT gateway does not delete routes that reference it. The route `0.0.0.0/0 → nat-1a` in `rtb-private-1a` is now `State: blackhole`, so matching packets are silently dropped. `app-1b` is unaffected because it uses its own table and its own NAT gateway — which is exactly the resilience benefit of per-AZ tables.

    Note also that the Elastic IP `EIP_1A` is now **unassociated and still billed**.

    **Fix.**

    ```bash
    aws ec2 create-nat-gateway --subnet-id "$SUBNET_PUBLIC_1A" --allocation-id "$EIP_1A" \
      --connectivity-type public \
      --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=dnb-dev-nat-1a},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev},{Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
      --query 'NatGateway.NatGatewayId' --output text > out/new-nat.txt
    setid NAT_1A "$(cat out/new-nat.txt)"
    aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_1A" 2>/dev/null || true
    aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1A" \
      --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1A"
    ./bin/assert-nat-az-affinity.sh
    ```

    **Lesson.** Check for blackhole routes *first* when something that worked stops working. A deleted route target leaves the route behind.

### Scenario 2 — "New subnets are mysteriously public"

```bash
aws ec2 create-route --route-table-id "$RTB_MAIN" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"
SUBNET_ORPHAN=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.144.0/24 \
  --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=dnb-dev-subnet-orphan},{Key=Project,Value=CoreBanking},{Key=ManagedBy,Value=floci-lab},{Key=Tier,Value=app}]' \
  --query 'Subnet.SubnetId' --output text)
setid SUBNET_ORPHAN "$SUBNET_ORPHAN"
```

**Symptom.** Carol's audit script reports that a newly created subnet intended for internal batch jobs has a route to the internet, even though nobody associated it with the public route table.

??? note "Hint"
    Which route table applies to a subnet that has no explicit association?

??? note "Diagnosis and fix"
    **Diagnosis.** The new subnet has no explicit route table association, so it **implicitly uses the VPC main route table** — and someone added `0.0.0.0/0 → igw` to that table. Every unassociated subnet in the VPC is therefore public. `bin/routing-report.sh` shows `MAIN!` in the `assoc` column, and `bin/public-subnets.sh` prints the warning banner.

    **Fix.**

    ```bash
    aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 0.0.0.0/0
    aws ec2 associate-route-table --route-table-id "$RTB_PRIVATE_1A" --subnet-id "$SUBNET_ORPHAN" >/dev/null
    ./bin/assert-main-rtb-minimal.sh
    ./bin/routing-report.sh
    ```

    **Lesson.** Keep the main route table `local`-only, forever, and associate every subnet explicitly. This is a **preventive** control, not a corrective one: with an empty main table, forgetting an association fails closed instead of open.

### Scenario 3 — "The database connection opens and then hangs"

```bash
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 100
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 110
```

**Symptom.** Alice reports that the statement worker's connection pool fills with connections that never become usable. `telnet 10.20.64.10 5432` appears to connect and then produces nothing. The security groups have not changed, and she has verified `sg-db` allows 5432 from `sg-app`.

??? note "Hint 1"
    Which of the two VPC firewalls is stateless?

??? note "Hint 2"
    `python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 5432 --src-sg "$SG_APP" --dst-sg "$SG_DB"` — read step 6.

??? note "Diagnosis and fix"
    **Diagnosis.** `acl-data` has ingress allows for 5432 but no egress allows at all, so it falls through to `32766 deny`. Because NACLs are **stateless**, the database's reply — sourced from port 5432, destined for the client's ephemeral port — is evaluated against the egress list and dropped. Alice is right that the security groups are correct; security groups are stateful and would have permitted the reply automatically. `bin/lint-nacl.sh` flags exactly this.

    In real AWS this appears in flow logs as an inbound `ACCEPT` with a matching outbound `REJECT`.

    **Fix.**

    ```bash
    aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
      --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
      --cidr-block 10.20.32.0/20 --rule-action allow
    aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
      --rule-number 110 --protocol tcp --port-range From=1024,To=65535 \
      --cidr-block 10.20.48.0/20 --rule-action allow
    ./bin/lint-nacl.sh
    ```

    **Lesson.** A hang in one direction only, with correct security groups, is a stateless NACL missing its ephemeral return rule. Almost every time.

### Scenario 4 — "Every AWS SDK call from the app tier times out"

```bash
aws ec2 revoke-security-group-ingress --group-id "$SG_VPCE" \
  --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
    \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\"}]}]" >/dev/null
```

**Symptom.** `aws sts get-caller-identity` from an app-tier instance hangs for 60 seconds and then fails with a connection timeout. DNS resolves `sts.us-east-1.amazonaws.com` to `10.20.32.x`, which looks correct. The instance can still reach the internet on 443 through the NAT gateway.

??? note "Hint"
    Private DNS is working perfectly — that is the problem. Where does the traffic go now, and what guards that destination?

??? note "Diagnosis and fix"
    **Diagnosis.** Private DNS makes the public service name resolve to the interface endpoint's ENI inside the VPC. Traffic therefore no longer goes to the NAT gateway at all — it goes to `10.20.32.x`, which is guarded by `sg-vpce`. With the ingress rule revoked, `sg-vpce` has no rule matching TCP 443 from `sg-app`, so the packet is dropped and the client hangs. The fact that general internet access on 443 still works is the diagnostic clue: only *this* destination is broken, and it is a destination inside the VPC.

    **Fix.**

    ```bash
    aws ec2 authorize-security-group-ingress --group-id "$SG_VPCE" \
      --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
        \"UserIdGroupPairs\":[
           {\"GroupId\":\"$SG_APP\",\"Description\":\"app tier to interface endpoints\"},
           {\"GroupId\":\"$SG_WEB\",\"Description\":\"web tier to interface endpoints\"}]}]" >/dev/null
    aws ec2 describe-security-groups --group-ids "$SG_VPCE" \
      --query 'SecurityGroups[0].IpPermissions' --output json
    ```

    **Lesson.** Enabling private DNS moves a destination *into* your VPC, where your own security groups now apply. An interface endpoint whose security group blocks 443 is `available`, resolvable and completely unusable — and nothing in the API tells you so.

### Scenario 5 — "This policy will not apply" (a malformed document)

The following endpoint policy has been handed to you by a colleague. It is **deliberately broken** — do not expect it to parse.

```json
{
  "Version": "2012-10-17"
  "Statement": [
    {
      "Sid": "AllowStatements",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject" "s3:PutObject"],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*",
      "Condition": {
        "StringEquals": { "aws:SourceVpc": "vpc-0a1b2c3d4e5f6a7b8" },
      }
    }
  ],
}
```

**Task.** Find every syntactic error, then find the two *semantic* problems that would remain even after the syntax is fixed.

??? note "Diagnosis and fix"
    **Syntactic errors — four of them:**

    1. Missing comma after `"Version": "2012-10-17"`.
    2. Missing comma between `"s3:GetObject"` and `"s3:PutObject"` in the `Action` array.
    3. Trailing comma after the `StringEquals` object inside `Condition`.
    4. Trailing comma after the `Statement` array's closing bracket.

    **Semantic problems — two of them:**

    1. **`ListBucket` is missing, and its resource is different.** `s3:ListBucket` acts on the *bucket* ARN (`arn:aws:s3:::dnb-statements-dev`), not the object ARN (`…/*`). Any SDK call that lists objects — including most `aws s3 cp` and `sync` operations — will fail with `AccessDenied`.
    2. **The `aws:SourceVpc` condition is redundant here and dangerous elsewhere.** In an *endpoint* policy, every request already arrives through that endpoint in that VPC, so the condition adds nothing. The correct home for `aws:SourceVpc` / `aws:SourceVpce` is the **bucket policy**, where it constrains *all* callers. Putting it in the endpoint policy suggests a misunderstanding of which side enforces what.

    **Corrected version:**

    ```json
    {
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "AllowStatements",
          "Effect": "Allow",
          "Principal": "*",
          "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
          "Resource": [
            "arn:aws:s3:::dnb-statements-dev",
            "arn:aws:s3:::dnb-statements-dev/*"
          ]
        }
      ]
    }
    ```

    **Lesson.** Validate every policy document before submitting it — `python3 -c "import json;json.load(open('f.json'))"` costs one second. And know which policy type each condition key belongs in.

### Scenario 6 — "Nothing can be deleted"

```bash
aws ec2 delete-subnet --subnet-id "$SUBNET_APP_1A" 2>&1 | head -3
aws ec2 delete-security-group --group-id "$SG_APP" 2>&1 | head -3
aws ec2 delete-vpc --vpc-id "$VPC_ID" 2>&1 | head -3
```

**Symptom.** Three `DependencyViolation` errors, none of which says what the dependency is.

??? note "Diagnosis and fix"
    **Diagnosis.** Three different dependencies, all invisible in the error message:

    * `delete-subnet` fails because ENIs live in it — the instance from Lab 8, its secondary ENI, and the `vpce-sts` interface endpoint's ENI.
    * `delete-security-group` fails because ENIs reference it **and** because `sg-db`'s ingress rule references it.
    * `delete-vpc` fails because everything else still exists.

    The diagnostic commands:

    ```bash
    aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET_APP_1A" \
      --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Desc:Description,Owner:RequesterId}' --output table
    aws ec2 describe-network-interfaces --filters "Name=group-id,Values=$SG_APP" \
      --query 'NetworkInterfaces[].NetworkInterfaceId' --output text
    aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" \
      --query "SecurityGroups[?IpPermissions[?UserIdGroupPairs[?GroupId=='$SG_APP']]].GroupId" --output text
    ```

    **Fix.** Do not fix it here — this *is* §16. Deletion must follow dependency order: instances → ENIs → endpoints → NAT gateways → EIPs → IGW → NACL associations → SG rules → SGs → route table associations → route tables → subnets → CIDR associations → VPC.

    **Lesson.** `DependencyViolation` is never about the resource named in the error; it is about something that references it. Learn the three lookup commands above.

### 12.7 Restore and verify

```bash
# Remove the orphan subnet from Scenario 2
aws ec2 delete-subnet --subnet-id "$SUBNET_ORPHAN" 2>&1 | head -2
grep -v '^export SUBNET_ORPHAN=' "$LEDGER" > "${LEDGER}.tmp" && mv "${LEDGER}.tmp" "$LEDGER"
unset SUBNET_ORPHAN

./bin/build-vpc.sh >/dev/null 2>&1
./bin/verify-all.sh | tail -5
./bin/security-audit.sh | tail -10
diff <(python3 -m json.tool out/topology.pre-debug.json) \
     <(python3 -m json.tool out/topology.json) > out/debug-drift.txt 2>&1 \
  && echo "topology fully restored" \
  || { echo "residual differences (review out/debug-drift.txt):"; head -20 out/debug-drift.txt; }
```

---

## 13. Interview Questions

### 13.1 Conceptual

1. A VPC is described as "software-defined". What physical devices are you actually configuring, and what does that imply about how quickly a route change takes effect and whether it can be rolled back atomically?
2. Why can you not delete or override the `local` route? What does that tell you about how intra-VPC isolation must be achieved?
3. Explain precisely what makes a subnet "public". Give two configurations that look public but are not.
4. Why does AWS reserve five addresses in every subnet? Name each one and its function.
5. An internet gateway is sometimes described as performing NAT. For which address family is that true, and what exactly does it translate?
6. Security groups are stateful; network ACLs are stateless. Explain the concrete consequence for a client connecting to a web server on port 443, in terms of the rules you must write in each.
7. Why can a security group rule reference another security group, while a network ACL rule cannot? What design benefit does that reference give you?
8. Explain longest-prefix match. Given `0.0.0.0/0 → nat`, `10.20.0.0/16 → local` and `10.20.64.0/20 → eni-fw`, which route applies to `10.20.64.5`, and which to `10.20.100.5`?
9. What is a blackhole route, how is one created, and why is it more dangerous than an error?
10. Contrast a gateway VPC endpoint with an interface VPC endpoint across mechanism, supported services, cost, DNS behaviour and security controls.
11. Why is VPC peering not transitive, and what specifically cannot you do over a peering connection?
12. Why is `100.64.0.0/10` a popular choice for a secondary VPC CIDR?
13. Why does a NAT gateway not support IPv6, and what replaces it?
14. What does "one NAT gateway per AZ" buy you? Give both the availability and the cost argument.
15. Why does a VPC-attached Lambda function lose internet access, and what are your two options for restoring it?

### 13.2 Scenario-based

16. A developer says: *"I added an inbound rule allowing 5432 from `10.20.0.0/16` so the app tier can reach the database."* Identify the flaw and give the correct rule.
17. An instance in a public subnet with `0.0.0.0/0 → igw` cannot reach the internet. The security group allows all egress and the NACL is the default. What is the most likely cause, and which single field would confirm it?
18. Your ALB fails to create with an error about subnets. List three distinct causes.
19. Statement generation worked in `us-east-1a` and failed in `us-east-1b` after an AZ-a incident. What is the most likely architectural error?
20. Adding a secondary CIDR `172.16.0.0/16` broke connectivity to the on-premises network. Explain exactly why, referencing route evaluation.
21. Athena queries against flow logs in S3 have become prohibitively slow and expensive. Name three changes to the flow log configuration that would help.
22. Your monthly bill shows a large "NAT gateway data processing" line. The workload mostly reads from S3. What is the fix, and what does it cost?
23. A pen-test report says a database is reachable from the internet. `describe-security-groups` shows `sg-db` allows 5432 only from `sg-app`. Give two ways the finding could still be true.
24. An EKS cluster stops scheduling pods with "insufficient IP addresses", but nodes have spare capacity. Explain the mechanism and give two mitigations.
25. You must allow a partner to call one internal API. Their VPC CIDR overlaps yours. Peering is impossible. What do you propose, and why does it tolerate the overlap?
26. A team asks for `0.0.0.0/0` on port 22 "just for a week". Give the alternative you would implement instead, and enumerate what it needs.
27. `aws s3 ls` works from your laptop but fails with `AccessDenied` from an EC2 instance in a private subnet, using a role with `s3:*`. Name three places the denial could originate.
28. After you enabled private DNS on an interface endpoint, all SDK calls from that subnet started timing out. What did you forget?
29. A route table has both `0.0.0.0/0 → igw-…` and `0.0.0.0/0 → nat-…` proposed by two engineers. What actually happens when you try to create the second one?
30. Traffic between two instances **in the same subnet** is being dropped. Which of security groups and NACLs can possibly be responsible, and why?

### 13.3 SAA-C03 certification style

31. A company needs instances in a private subnet to download OS patches from the internet but must prevent any inbound connections from the internet. Which is the MOST appropriate?
    **(A)** Internet gateway with a `0.0.0.0/0` route in the private subnet
    **(B)** NAT gateway in a public subnet, with `0.0.0.0/0 → nat` in the private subnet's route table
    **(C)** NAT gateway in the private subnet, with `0.0.0.0/0 → igw`
    **(D)** VPC endpoint for the package repository

32. A solutions architect must block a single malicious IP address from reaching any resource in a subnet. Which achieves this with the LEAST operational effort?
    **(A)** A deny rule in the security group
    **(B)** A NACL rule with a low rule number and action `deny`
    **(C)** Remove the `0.0.0.0/0` route
    **(D)** A NACL rule numbered 32767

33. An application in a private subnet writes large volumes of objects to S3. Costs for NAT gateway data processing are excessive. What is the MOST cost-effective fix?
    **(A)** An interface endpoint for S3
    **(B)** A gateway endpoint for S3, added to the private subnets' route tables
    **(C)** Move the application to a public subnet
    **(D)** A second NAT gateway

34. A company has four VPCs that must all communicate with each other and with an on-premises datacentre. Which minimises operational overhead?
    **(A)** Six VPC peering connections plus a VPN per VPC
    **(B)** A transit gateway with VPC and VPN attachments
    **(C)** A NAT gateway in each VPC
    **(D)** PrivateLink endpoint services between each pair

35. Instances in a subnet can initiate connections to a database in another subnet, but the connections hang before completing. Security groups on both sides are verified correct. What should the architect check NEXT?
    **(A)** The route table's `local` route
    **(B)** The network ACL's outbound rules for the ephemeral port range
    **(C)** Whether the instances have public IPs
    **(D)** Whether DNS hostnames are enabled

36. A regulated workload must access Secrets Manager without any traffic traversing the internet, from a subnet with no NAT gateway. Which combination is required? (Choose TWO)
    **(A)** An interface endpoint for `secretsmanager` in the subnet
    **(B)** A gateway endpoint for `secretsmanager`
    **(C)** A security group on the endpoint allowing inbound 443 from the client security group
    **(D)** An internet gateway attached to the VPC
    **(E)** `enableDnsHostnames` set to `false`

37. An architect creates a new network ACL and associates it with a subnet. All connectivity to the subnet immediately fails. What is the cause?
    **(A)** NACLs take up to an hour to propagate
    **(B)** A new NACL denies all inbound and outbound traffic until rules are added
    **(C)** The subnet lost its route table association
    **(D)** The default NACL cannot be replaced

38. A company's VPC uses `10.0.0.0/16`. It acquires a company whose VPC also uses `10.0.0.0/16`. They must share one internal service. What should the architect recommend?
    **(A)** VPC peering with route table entries on both sides
    **(B)** A transit gateway attachment for each VPC
    **(C)** An AWS PrivateLink endpoint service in the provider VPC and an interface endpoint in the consumer VPC
    **(D)** Re-address both VPCs

39. An EC2 instance in a public subnet has an auto-assigned public IPv4 address. After a stop and start, external clients can no longer reach it at the previous address. What is the MOST likely reason?
    **(A)** The security group was reset
    **(B)** Auto-assigned public IPv4 addresses are released on stop and a new one is assigned on start
    **(C)** The route table association was lost
    **(D)** The internet gateway detached

40. Which statement about VPC flow logs is correct?
    **(A)** They capture packet payloads for forensic analysis
    **(B)** They capture traffic to the Amazon DNS resolver
    **(C)** They can be enabled at VPC, subnet or network-interface level and record metadata only
    **(D)** They are real-time with sub-second delivery

??? note "Answer key for §13.3"
    31 **B** — a NAT gateway must live in a public subnet; the private subnet routes to it. (A) exposes the subnet; (C) is the classic `Gateway.NotAttached` error; (D) does not exist for arbitrary repositories.

    32 **B** — only NACLs support `deny`, and a low rule number is evaluated first. (D) fails because 32767 is the immutable implicit rule; the highest usable number is 32766.

    33 **B** — the S3 gateway endpoint is free and removes the traffic from the NAT entirely. (A) is not available for S3 in the classic sense and would still be charged per GB.

    34 **B** — transit gateway; four VPCs would need six peerings plus per-VPC VPNs, and peering is not transitive.

    35 **B** — the hang-with-correct-SGs signature is a stateless NACL missing the ephemeral return rule.

    36 **A and C** — interface endpoint plus a security group permitting 443. (B) is wrong: only S3 and DynamoDB have gateway endpoints. (E) would break private DNS.

    37 **B** — a new NACL contains only the implicit `*` deny in both directions.

    38 **C** — PrivateLink is the only option that tolerates overlapping CIDRs, because the consumer reaches an ENI in its own address space.

    39 **B** — auto-assigned public IPv4 addresses are not persistent; an Elastic IP is the fix.

    40 **C** — metadata only, three levels, and DNS-resolver traffic is explicitly excluded.

### 13.4 Hands-on practical (whiteboard or terminal)

41. Write the CLI command that creates a route sending `0.0.0.0/0` to a NAT gateway, and explain why `--gateway-id` would be wrong here.
42. Write a single `describe-route-tables` invocation that lists every route table in a VPC having a route to an internet gateway, with its associated subnets.
43. Write the `authorize-security-group-ingress` command that allows PostgreSQL from `sg-app` to `sg-db` **with a description**, using `--ip-permissions`.
44. Write the two `create-network-acl-entry` commands needed for a subnet to serve HTTPS to the internet.
45. Given `AvailableIpAddressCount: 4085` on a `/20`, how many ENIs exist in the subnet? Show your working.
46. Write a one-liner that finds every unassociated Elastic IP in the account with its `Name` tag.
47. You must delete a VPC. Write the deletion order as a numbered list, with the reason each step must precede the next.
48. Write the `jq` or `--query` expression that extracts, for one security group, every rule that references another security group.
49. Explain what `bin/reach.py` step 6 checks and why it exists.
50. Given only `describe-subnets` and `describe-route-tables` output, write pseudocode that classifies each subnet as public, private or isolated.

---

## 14. Viva Questions

For a 10–15 minute oral examination. The examiner should probe for *reasoning*, not recall — every question has a follow-up.

| # | Question | Follow-up the examiner should ask |
|---|---|---|
| 1 | Draw the DNB topology from memory and label every route table's default route. | "Now delete `nat-1a`. What breaks, and what does `describe-route-tables` show?" |
| 2 | Why is your data tier "isolated" rather than "private"? | "So how does it reach S3? Draw the path." |
| 3 | Show me a security group rule you wrote and explain why it references a group rather than a CIDR. | "What happens when we add a third AZ? Which approach needs changing?" |
| 4 | A connection hangs. Walk me through your diagnosis. | "You checked the security groups and they are correct. Now what?" |
| 5 | Explain the five reserved addresses. | "Why does that make a `/28` hold 11 hosts and not 14?" |
| 6 | What is in your VPC's main route table, and why? | "What would happen if I added a default route to it right now?" |
| 7 | Explain statefulness with reference to a rule you actually wrote. | "Which of your NACL rules exists *only* because NACLs are stateless?" |
| 8 | Show me `reach.py` and explain step 3. | "Which route wins for `10.20.64.5`, and why not the default route?" |
| 9 | You created an interface endpoint and calls time out. Diagnose it. | "The endpoint says `available`. Does that mean anything?" |
| 10 | Which parts of this module could you not verify in Floci, and how did you compensate? | "Give me one conclusion you would refuse to state without real AWS." |
| 11 | Justify one NAT gateway per AZ to a manager who wants to save money. | "How much does the second one cost, and what is the alternative saving?" |
| 12 | How would you prove to an auditor that the data tier has no internet path? | "Which single control, if removed, would still leave the claim true?" |
| 13 | Explain why peering is not transitive, using three VPCs. | "Which packet is dropped, and where?" |
| 14 | What is the difference between an auto-assigned public IP and an Elastic IP? | "Which one is billed when nothing is attached, and why does that matter?" |
| 15 | Your build script is idempotent. Prove it. | "What would make it non-idempotent if you looked resources up by tag instead of by name?" |
| 16 | Describe a divergence you recorded between Floci and AWS, and its consequence. | "Which of your lab conclusions is invalidated by it?" |

---

## 15. Reflection Questions

Answer these in `out/reflection.md`, in prose, in your own words. This section is graded on honesty and insight, not length.

**On what you built**

1. Describe the topology you built in five sentences, without using the words "then I created". Describe the *design*, not the sequence.
2. Which single design decision would be hardest to reverse six months from now, and why?
3. If you had to rebuild it for a workload ten times larger, what would you change on day one?

**On what you learned**

4. Before this module, what did you believe made a subnet "public"? What do you believe now?
5. Which of the three components — route tables, security groups, network ACLs — did you find hardest to reason about, and what finally made it click?
6. `reach.py` forced you to encode AWS's evaluation order precisely. Which step surprised you when you implemented it?

**On mistakes**

7. Name a mistake you made during these labs that produced **no error message**. How did you eventually notice it? What check would have caught it earlier?
8. Which of the Break-it steps produced an outcome you predicted incorrectly? What was your incorrect mental model?
9. `DependencyViolation` appears repeatedly. What single sentence would you now write in a runbook to explain it to Dana?

**On security**

10. Your design has five independent controls preventing data-tier exfiltration. Rank them by how likely each is to be accidentally removed by a well-meaning engineer, and justify the ranking.
11. Section 6.4 names two residual risks the VPC design does not close. In your own words, why is a VPC not sufficient for data-exfiltration prevention?
12. You revoked allow-all egress from every security group. Argue the *counter*-case: when is restricting egress not worth the operational cost?

**On the emulator**

13. List three conclusions in this module that you can support only by reasoning, never by observation, and state what evidence you would need from real AWS to confirm each.
14. Did working on an emulator make you understand VPC better or worse than a real account would have? Argue both sides, then take a position.

**On architecture**

15. Where does VPC sit relative to IAM in your mental model of AWS security? Which one would you rather get right if you could only get one right, and why?
16. A colleague proposes running the whole platform serverless, with no VPC at all. Under what conditions is that the better architecture, and what do you lose?

---

## 16. Cleanup

!!! danger "Read this before you run anything"
    Deletion order matters. Every step below exists because the one after it would otherwise fail with `DependencyViolation`. Run the script top to bottom; do not reorder it. In real AWS, the two steps that stop the bill are **deleting NAT gateways** and **releasing Elastic IPs** — do those first if you are in a hurry.

### 16.1 The dependency order, and why

```
  1. Terminate instances                 ENIs at device index 0 die with them
  2. Delete secondary/detached ENIs      device index >0 survive termination
  3. Delete VPC endpoints                interface endpoints own ENIs in subnets
  4. Delete NAT gateways                 own ENIs; their routes become blackholes
  5. Release Elastic IPs                 not released by NAT/instance deletion — BILLED
  6. Delete peering connections          routes referencing them go blackhole
  7. Detach + delete the internet gateway  detach fails while any public IP exists
  8. Restore NACL associations, delete custom NACLs   no disassociate exists
  9. Revoke ALL security group rules, then delete groups   cross-references block deletion
 10. Disassociate + delete route tables  main table cannot be deleted
 11. Delete subnets                      fail while ANY ENI remains
 12. Disassociate secondary CIDRs        primary cannot be disassociated
 13. Delete key pairs                    independent, but tidy
 14. Delete the VPC                      succeeds only when all of the above are done
 15. Sweep by tag                        catch anything created in challenges
```

### 16.2 The cleanup script

```bash
cat > bin/cleanup.sh <<'SH'
#!/usr/bin/env bash
# cleanup.sh — delete every resource created by this module, in dependency order.
# Idempotent: safe to run repeatedly. Sweeps by tag so challenge resources are caught.
set -uo pipefail

case "${AWS_ENDPOINT_URL:-}" in
  *localhost*|*127.0.0.1*|*floci*) : ;;
  *) echo "REFUSING: AWS_ENDPOINT_URL is '${AWS_ENDPOINT_URL:-<empty>}'" >&2; exit 1 ;;
esac

LEDGER="$HOME/vpc-lab/out/ids.env"
[ -f "$LEDGER" ] && { set -a; . "$LEDGER"; set +a; }

TAGFILTER=(--filters "Name=tag:ManagedBy,Values=floci-lab")
step() { printf '\n=== %s ===\n' "$*"; }
try()  { "$@" 2>&1 | head -2; }

# Discover every VPC this module may have created, not just $VPC_ID
VPCS=$(aws ec2 describe-vpcs "${TAGFILTER[@]}" --query 'Vpcs[].VpcId' --output text 2>/dev/null)
[ -z "$VPCS" ] && VPCS="${VPC_ID:-}"
echo "VPCs in scope: ${VPCS:-<none>}"

step "1. terminate instances"
INSTS=$(aws ec2 describe-instances "${TAGFILTER[@]}" \
  --query 'Reservations[].Instances[?State.Name!=`terminated`].InstanceId' --output text 2>/dev/null)
if [ -n "$INSTS" ] && [ "$INSTS" != "None" ]; then
  try aws ec2 terminate-instances --instance-ids $INSTS
  aws ec2 wait instance-terminated --instance-ids $INSTS 2>/dev/null || sleep 5
else
  echo "  none"
fi

step "2. delete detached / secondary ENIs"
for vpc in $VPCS; do
  while read -r eni; do
    [ -z "$eni" ] && continue
    try aws ec2 delete-network-interface --network-interface-id "$eni"
  done < <(aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$vpc" \
             --query 'NetworkInterfaces[?Status==`available`].NetworkInterfaceId' \
             --output text 2>/dev/null | tr '\t' '\n')
done

step "3. delete VPC endpoints"
for vpc in $VPCS; do
  EPS=$(aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$vpc" \
          --query 'VpcEndpoints[].VpcEndpointId' --output text 2>/dev/null)
  [ -n "$EPS" ] && [ "$EPS" != "None" ] && try aws ec2 delete-vpc-endpoints --vpc-endpoint-ids $EPS || echo "  none in $vpc"
done

step "4. delete NAT gateways  (stops the hourly charge)"
for vpc in $VPCS; do
  while read -r nat; do
    [ -z "$nat" ] && continue
    try aws ec2 delete-nat-gateway --nat-gateway-id "$nat"
    aws ec2 wait nat-gateway-deleted --nat-gateway-ids "$nat" 2>/dev/null || sleep 5
  done < <(aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$vpc" \
             --query 'NatGateways[?State!=`deleted`].NatGatewayId' --output text 2>/dev/null | tr '\t' '\n')
done

step "5. release Elastic IPs  (stops the idle-address charge)"
while read -r alloc assoc; do
  [ -z "$alloc" ] && continue
  [ "$assoc" != "None" ] && [ -n "$assoc" ] && try aws ec2 disassociate-address --association-id "$assoc"
  try aws ec2 release-address --allocation-id "$alloc"
done < <(aws ec2 describe-addresses --filters "Name=tag:ManagedBy,Values=floci-lab" \
           --query 'Addresses[].[AllocationId,AssociationId]' --output text 2>/dev/null)
# Belt and braces: any remaining unassociated EIP is a live charge
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' --output text 2>/dev/null

step "6. delete VPC peering connections"
while read -r pcx; do
  [ -z "$pcx" ] && continue
  try aws ec2 delete-vpc-peering-connection --vpc-peering-connection-id "$pcx"
done < <(aws ec2 describe-vpc-peering-connections \
           --query 'VpcPeeringConnections[?Status.Code!=`deleted`].VpcPeeringConnectionId' \
           --output text 2>/dev/null | tr '\t' '\n')

step "7. detach and delete internet gateways / egress-only IGWs"
for vpc in $VPCS; do
  while read -r igw; do
    [ -z "$igw" ] && continue
    try aws ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc"
    try aws ec2 delete-internet-gateway --internet-gateway-id "$igw"
  done < <(aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$vpc" \
             --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null | tr '\t' '\n')
done
while read -r eigw; do
  [ -z "$eigw" ] && continue
  try aws ec2 delete-egress-only-internet-gateway --egress-only-internet-gateway-id "$eigw"
done < <(aws ec2 describe-egress-only-internet-gateways \
           --query 'EgressOnlyInternetGateways[].EgressOnlyInternetGatewayId' \
           --output text 2>/dev/null | tr '\t' '\n')

step "8. restore default NACL associations, then delete custom NACLs"
for vpc in $VPCS; do
  DEF=$(aws ec2 describe-network-acls --filters "Name=vpc-id,Values=$vpc" "Name=default,Values=true" \
          --query 'NetworkAcls[0].NetworkAclId' --output text 2>/dev/null)
  while read -r acl; do
    [ -z "$acl" ] && continue
    while read -r assoc; do
      [ -z "$assoc" ] && continue
      try aws ec2 replace-network-acl-association --association-id "$assoc" --network-acl-id "$DEF"
    done < <(aws ec2 describe-network-acls --network-acl-ids "$acl" \
               --query 'NetworkAcls[0].Associations[].NetworkAclAssociationId' \
               --output text 2>/dev/null | tr '\t' '\n')
    try aws ec2 delete-network-acl --network-acl-id "$acl"
  done < <(aws ec2 describe-network-acls --filters "Name=vpc-id,Values=$vpc" \
             --query 'NetworkAcls[?IsDefault==`false`].NetworkAclId' --output text 2>/dev/null | tr '\t' '\n')
done

step "9. revoke ALL security group rules, then delete non-default groups"
for vpc in $VPCS; do
  # Pass 1: strip every rule so cross-references cannot block deletion.
  while read -r sg; do
    [ -z "$sg" ] && continue
    ing=$(aws ec2 describe-security-groups --group-ids "$sg" \
            --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null)
    egr=$(aws ec2 describe-security-groups --group-ids "$sg" \
            --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null)
    [ "$ing" != "[]" ] && [ -n "$ing" ] && \
      aws ec2 revoke-security-group-ingress --group-id "$sg" --ip-permissions "$ing" >/dev/null 2>&1
    [ "$egr" != "[]" ] && [ -n "$egr" ] && \
      aws ec2 revoke-security-group-egress --group-id "$sg" --ip-permissions "$egr" >/dev/null 2>&1
    echo "  stripped rules from $sg"
  done < <(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" \
             --query 'SecurityGroups[].GroupId' --output text 2>/dev/null | tr '\t' '\n')
  # Pass 2: delete everything except the undeletable default group.
  while read -r sg; do
    [ -z "$sg" ] && continue
    try aws ec2 delete-security-group --group-id "$sg"
  done < <(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" \
             --query 'SecurityGroups[?GroupName!=`default`].GroupId' --output text 2>/dev/null | tr '\t' '\n')
done

step "10. disassociate and delete non-main route tables"
for vpc in $VPCS; do
  while read -r rtb; do
    [ -z "$rtb" ] && continue
    while read -r assoc; do
      [ -z "$assoc" ] && continue
      try aws ec2 disassociate-route-table --association-id "$assoc"
    done < <(aws ec2 describe-route-tables --route-table-ids "$rtb" \
               --query 'RouteTables[0].Associations[?Main!=`true`].RouteTableAssociationId' \
               --output text 2>/dev/null | tr '\t' '\n')
    try aws ec2 delete-route-table --route-table-id "$rtb"
  done < <(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$vpc" \
             --query 'RouteTables[?!(Associations[?Main==`true`])].RouteTableId' \
             --output text 2>/dev/null | tr '\t' '\n')
done

step "11. delete subnets"
for vpc in $VPCS; do
  while read -r sn; do
    [ -z "$sn" ] && continue
    try aws ec2 delete-subnet --subnet-id "$sn"
  done < <(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" \
             --query 'Subnets[].SubnetId' --output text 2>/dev/null | tr '\t' '\n')
done

step "12. disassociate secondary CIDR blocks"
for vpc in $VPCS; do
  primary=$(aws ec2 describe-vpcs --vpc-ids "$vpc" --query 'Vpcs[0].CidrBlock' --output text 2>/dev/null)
  while read -r assoc cidr; do
    [ -z "$assoc" ] && continue
    [ "$cidr" = "$primary" ] && continue
    try aws ec2 disassociate-vpc-cidr-block --association-id "$assoc"
  done < <(aws ec2 describe-vpcs --vpc-ids "$vpc" \
             --query 'Vpcs[0].CidrBlockAssociationSet[].[AssociationId,CidrBlock]' \
             --output text 2>/dev/null)
  while read -r assoc; do
    [ -z "$assoc" ] && continue
    try aws ec2 disassociate-vpc-cidr-block --association-id "$assoc"
  done < <(aws ec2 describe-vpcs --vpc-ids "$vpc" \
             --query 'Vpcs[0].Ipv6CidrBlockAssociationSet[].AssociationId' \
             --output text 2>/dev/null | tr '\t' '\n')
done

step "13. delete key pairs and prefix lists"
try aws ec2 delete-key-pair --key-name dnb-dev-key
rm -f "$HOME/vpc-lab/out/dnb-dev-key.pem"
while read -r pl; do
  [ -z "$pl" ] && continue
  try aws ec2 delete-managed-prefix-list --prefix-list-id "$pl"
done < <(aws ec2 describe-managed-prefix-lists \
           --query 'PrefixLists[?starts_with(PrefixListName, `dnb-`) || PrefixListName==`__probe__`].PrefixListId' \
           --output text 2>/dev/null | tr '\t' '\n')

step "14. delete VPCs"
for vpc in $VPCS; do
  try aws ec2 delete-vpc --vpc-id "$vpc"
done

step "15. final sweep — anything left tagged Project=CoreBanking or named dnb-*"
for verb in describe-vpcs describe-subnets describe-route-tables describe-security-groups \
            describe-network-acls describe-internet-gateways describe-nat-gateways \
            describe-network-interfaces describe-vpc-endpoints describe-addresses; do
  n=$(aws ec2 "$verb" --filters "Name=tag:Project,Values=CoreBanking" --output json 2>/dev/null \
        | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0); raise SystemExit
k = next((x for x in d if isinstance(d[x], list)), None)
print(len(d[k]) if k else 0)')
  printf '  %-34s remaining: %s\n' "$verb" "${n:-?}"
done

step "done"
echo "If any count above is non-zero, re-run this script: deletions can need two passes"
echo "while asynchronous NAT gateway and endpoint teardown completes."
SH
chmod +x bin/cleanup.sh
bash -n bin/cleanup.sh && echo "syntax OK"
```

### 16.3 Run it, twice

```bash
./bin/cleanup.sh 2>&1 | tee out/cleanup-run1.txt
echo "=================== SECOND PASS ==================="
./bin/cleanup.sh 2>&1 | tee out/cleanup-run2.txt
```

### 16.4 Verify the environment is clean

```bash
echo "--- VPCs remaining (a default VPC may legitimately exist) ---"
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,IsDefault,Tags[?Key==`Name`]|[0].Value]' --output table

echo "--- Elastic IPs remaining (MUST be empty: these are billed) ---"
aws ec2 describe-addresses --query 'Addresses[].[AllocationId,PublicIp,AssociationId]' --output table

echo "--- NAT gateways remaining (MUST be empty or deleted: these are billed) ---"
aws ec2 describe-nat-gateways --query 'NatGateways[?State!=`deleted`].[NatGatewayId,State]' --output table

echo "--- anything still tagged floci-lab ---"
for verb in describe-vpcs describe-subnets describe-security-groups describe-route-tables \
            describe-network-acls describe-nat-gateways describe-vpc-endpoints; do
  printf '%-32s ' "$verb"
  aws ec2 "$verb" --filters "Name=tag:ManagedBy,Values=floci-lab" --output json 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("?"); raise SystemExit
k = next((x for x in d if isinstance(d[x], list)), None)
print(len(d[k]) if k else 0)'
done
```

Finally, archive your evidence and reset local state:

```bash
tar czf ~/vpc-lab-submission.tar.gz -C ~ vpc-lab/out vpc-lab/bin vpc-lab/policies
ls -la ~/vpc-lab-submission.tar.gz

# Optional: stop the emulator entirely
# floci stop
```

!!! danger "In a real AWS account, verify the bill, not just the API"
    `describe-addresses` returning empty is necessary but not sufficient. Check Cost Explorer for the `EC2-Other` usage type the day after teardown — NAT gateway hours, `PublicIPv4:InUseAddress` and endpoint hours are the three lines that keep accruing when a teardown is incomplete.

### 16.5 Recap of §16

Deletion order is dictated by ENIs and associations. Strip security group rules before deleting groups; replace NACL associations rather than removing them; release Elastic IPs explicitly because nothing else does it; and sweep by tag so that challenge resources are caught. Run the script twice — asynchronous teardown means a single pass often leaves work behind.

---

## 17. Summary

### 17.1 Key concepts, in one page

* A **VPC** is a regional, software-defined, default-deny network. It contains an **implicit router** you never see, and four kinds of configuration object: subnets (address containers, AZ-scoped), route tables (routing policy, associated per subnet), network ACLs (stateless subnet firewalls) and security groups (stateful ENI firewalls). Edge devices — IGW, NAT gateway, endpoints, peering, VGW — exist to be pointed at by routes.
* Every VPC is born with three **undeletable, permissive defaults**: the main route table, the default NACL and the default security group. Production designs replace all three, and lock the default SG down to nothing.
* The **`local` route** is immutable, so all subnets in a VPC can always route to each other. Intra-VPC isolation is a **firewall** concern, never a routing concern.
* A subnet is **public** if and only if its route table has `0.0.0.0/0` pointing at an internet gateway. **Private** means the default route points at a NAT gateway. **Isolated** means there is no default route at all. Names and tags mean nothing.
* AWS reserves **five addresses per subnet**: network, router (base+1), DNS (base+2), future (base+3), broadcast (last). So `usable = 2^(32−prefix) − 5`.
* **Security groups**: allow-only, **stateful**, ENI-scoped, order-independent, can reference other groups. New groups have no ingress and allow-all egress.
* **Network ACLs**: allow **and deny**, **stateless**, subnet-scoped, numbered, **first match wins**, implicit `*` deny. Statelessness means you must allow the **ephemeral range** for return traffic.
* **Longest-prefix match** decides routing. A deleted target leaves a **blackhole** route that drops traffic silently.
* **Endpoints** change the *path* of AWS API traffic, not its encryption. Gateway = route-table entry with a prefix list, S3 and DynamoDB only, free. Interface = an ENI with security groups, most services, charged, optional private DNS.
* **Peering** requires non-overlapping CIDRs, is **not transitive**, needs routes on both sides, and cannot borrow the peer's IGW, NAT or endpoints. **Transit gateway** solves scale and transitivity; **PrivateLink** solves overlapping CIDRs.
* An emulator gives you the control plane and not the data plane. Verify **existence** with `describe-*`, verify **intent** by computing AWS's verdict, and never claim **observation** you did not make.

### 17.2 Command reference

| Task | Command |
|---|---|
| Create VPC | `aws ec2 create-vpc --cidr-block 10.20.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=x}]'` |
| Enable DNS | `aws ec2 modify-vpc-attribute --vpc-id V --enable-dns-hostnames` (one attribute per call) |
| Add secondary CIDR | `aws ec2 associate-vpc-cidr-block --vpc-id V --cidr-block 100.64.0.0/16` |
| Add IPv6 | `aws ec2 associate-vpc-cidr-block --vpc-id V --amazon-provided-ipv6-cidr-block` |
| Create subnet | `aws ec2 create-subnet --vpc-id V --cidr-block 10.20.0.0/20 --availability-zone us-east-1a` |
| Auto-assign public IP | `aws ec2 modify-subnet-attribute --subnet-id S --map-public-ip-on-launch` |
| Create + attach IGW | `aws ec2 create-internet-gateway` ; `aws ec2 attach-internet-gateway --internet-gateway-id I --vpc-id V` |
| Create route table | `aws ec2 create-route-table --vpc-id V` |
| Default route to IGW | `aws ec2 create-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --gateway-id I` |
| Default route to NAT | `aws ec2 create-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --nat-gateway-id N` |
| Change a route | `aws ec2 replace-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --nat-gateway-id N2` |
| Associate route table | `aws ec2 associate-route-table --route-table-id R --subnet-id S` |
| Move a subnet's table | `aws ec2 replace-route-table-association --association-id A --route-table-id R2` |
| Allocate EIP | `aws ec2 allocate-address --domain vpc` |
| Create NAT gateway | `aws ec2 create-nat-gateway --subnet-id S_public --allocation-id E --connectivity-type public` |
| Create security group | `aws ec2 create-security-group --group-name G --description D --vpc-id V` |
| SG rule from another SG | `aws ec2 authorize-security-group-ingress --group-id G --ip-permissions 'IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=G2,Description=d}]'` |
| Remove allow-all egress | `aws ec2 revoke-security-group-egress --group-id G --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'` |
| Create NACL | `aws ec2 create-network-acl --vpc-id V` |
| NACL rule | `aws ec2 create-network-acl-entry --network-acl-id A --ingress --rule-number 100 --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow` |
| Associate NACL | `aws ec2 replace-network-acl-association --association-id AS --network-acl-id A` |
| Gateway endpoint | `aws ec2 create-vpc-endpoint --vpc-id V --vpc-endpoint-type Gateway --service-name com.amazonaws.us-east-1.s3 --route-table-ids R1 R2` |
| Interface endpoint | `aws ec2 create-vpc-endpoint --vpc-id V --vpc-endpoint-type Interface --service-name com.amazonaws.us-east-1.sts --subnet-ids S1 S2 --security-group-ids G --private-dns-enabled` |
| Create ENI | `aws ec2 create-network-interface --subnet-id S --groups G --private-ip-address 10.20.32.11` |
| Launch instance | `aws ec2 run-instances --image-id A --instance-type t3.micro --subnet-id S --security-group-ids G` |
| Peering | `aws ec2 create-vpc-peering-connection --vpc-id V1 --peer-vpc-id V2` ; `accept-vpc-peering-connection` |
| Flow logs | `aws ec2 create-flow-logs --resource-type VPC --resource-ids V --traffic-type ALL --log-destination-type s3 --log-destination arn:aws:s3:::b/prefix/` |
| Find blackholes | `aws ec2 describe-route-tables --query 'RouteTables[].Routes[?State==\`blackhole\`]'` |
| Find orphan EIPs | `aws ec2 describe-addresses --query 'Addresses[?AssociationId==null]'` |
| Find what blocks a delete | `aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=S` |

### 17.3 Security and operational practices, condensed

| Do | Do not |
|---|---|
| Reference security groups for intra-VPC traffic | Use CIDR literals inside the VPC |
| Keep the main route table `local`-only | Add a default route to the main table |
| Associate every subnet explicitly | Rely on implicit main-table association |
| One NAT gateway and one private route table per AZ | Share one NAT across AZs |
| Isolate the data tier (no default route) | "Privatise" it behind NAT and call it done |
| Revoke allow-all egress deliberately | Leave every group with `0.0.0.0/0` egress |
| Use SSM Session Manager | Open 22/3389, even "temporarily" |
| Add S3 and DynamoDB gateway endpoints on day one | Pay NAT data processing for S3 traffic |
| Allow 443 on interface-endpoint security groups | Wonder why SDK calls hang |
| Write ephemeral return rules with every NACL allow | Debug a hang for two hours |
| Tag atomically at creation | Plan to tag later |
| Lock down the default security group to nothing | Let mistakes fail open |
| Release Elastic IPs explicitly | Assume deleting the NAT releases them |
| Check for blackholes first when something breaks | Start with security groups |
| State whether evidence is existence, intent or observation | Say "verified" |

### 17.4 Assessment — the submission bundle

Submit `~/vpc-lab-submission.tar.gz` plus a report addressing the following. Weightings total 100.

| # | Deliverable | Evidence file(s) | Weight |
|---|---|---|---|
| 1 | Support matrix and how you classified each operation | `out/support-matrix.tsv`, `out/support-report.txt` | 5 |
| 2 | Addressing plan with the maths shown, and the allocation record | `out/ipam-record.md`, `out/subnet-plan.tsv` | 8 |
| 3 | Working topology: 6+ subnets, 2 AZs, IGW, per-AZ NAT, isolated data tier | `out/topology.json`, `out/lab04-routing.txt` | 12 |
| 4 | Security groups using references only, with egress restricted | `out/lab05-sg.txt`, `bin/assert-sg-invariants.sh` output | 10 |
| 5 | Network ACL with correct ephemeral return rules, plus the linter output | `out/lab06-*.txt`, `bin/lint-nacl.sh` output | 10 |
| 6 | VPC endpoints, with the before/after path analysis table | `out/lab07-endpoints.txt`, `policies/vpce-s3-policy.json` | 8 |
| 7 | `reach.py` and the passing reachability matrix with stated intent | `bin/reach.py`, `out/intended-matrix.tsv`, `out/lab10-matrix.txt` | 15 |
| 8 | Divergence log: every place Floci differed from AWS, and the consequence | `out/divergence-log.md` | 8 |
| 9 | Idempotent build script, proven idempotent by counting | `bin/build-vpc.sh`, `out/lab12-build-run2.txt` | 8 |
| 10 | Audit response for R5 including residual risks | `out/audit-response-R5.md` | 6 |
| 11 | Two mini challenges (one ⭐⭐⭐ or above) | as specified per challenge | 6 |
| 12 | Clean environment, verified | `out/cleanup-run2.txt` and the §16.4 output | 4 |

**Automatic deductions**

| Issue | Deduction |
|---|---|
| Any claim of observed traffic behaviour without evidence | −10 |
| A CIDR literal used for intra-VPC security group rules without justification | −5 |
| Any resource left running at submission (especially NAT gateways or EIPs) | −5 |
| An untagged resource | −3 |
| A security group rule without a description | −2 |

### 17.5 What comes next

| Module | The VPC thread it picks up |
|---|---|
| **EC2** | instance types and ENI/IP density limits; placement groups; source/destination checks |
| **ELB** | why ALBs need ≥2 AZs and 8 free IPs per subnet; NLB source-IP preservation and its effect on security groups |
| **RDS** | DB subnet groups; why Multi-AZ needs two AZs; the RDS ENI that blocks subnet deletion |
| **Lambda** | Hyperplane ENIs; why a VPC-attached function loses internet access; when not to attach |
| **ECS / EKS** | `awsvpc` mode; one IP per task/pod; secondary CIDRs and prefix delegation |
| **S3** | Block Public Access, `aws:SourceVpc` bucket policies, gateway endpoint economics |
| **CloudWatch** | flow logs to Logs Insights; metric filters and alarms on `REJECT` spikes |
| **Route 53** | private hosted zones, Resolver endpoints and rules, DNS Firewall |
| **CloudFormation** | rebuild this exact topology as a template and diff `topology.json` — see `out/cfn-hook.md` |
| **KMS** | encryption of data at rest for the isolated data tier; key policies are authoritative over IAM |
| **Organizations** | SCPs that deny `ec2:CreateRoute` to an IGW in production accounts |

---

## Appendix A — CIDR and address quick reference

| Prefix | Total addresses | AWS usable | Typical use |
|---|---|---|---|
| `/16` | 65 536 | 65 531 | whole VPC |
| `/17` | 32 768 | 32 763 | large reserved block |
| `/18` | 16 384 | 16 379 | AZ-major allocation |
| `/19` | 8 192 | 8 187 | large tier |
| `/20` | 4 096 | 4 091 | **our subnet size** |
| `/21` | 2 048 | 2 043 | medium tier |
| `/22` | 1 024 | 1 019 | small tier |
| `/23` | 512 | 507 | app subnet |
| `/24` | 256 | 251 | small subnet |
| `/26` | 64 | 59 | ALB subnet (minimum practical) |
| `/27` | 32 | 27 | endpoint-only subnet |
| `/28` | 16 | **11** | AWS minimum |

**The five reserved addresses**, for `10.20.32.0/20`:

| Address | Purpose |
|---|---|
| `10.20.32.0` | network address |
| `10.20.32.1` | VPC router / default gateway |
| `10.20.32.2` | Amazon DNS resolver (VPC base+2 also answers: `10.20.0.2`; link-local `169.254.169.253`) |
| `10.20.32.3` | reserved for future AWS use |
| `10.20.47.255` | broadcast address (reserved though VPC has no broadcast) |

**Protocol numbers for NACL entries:** `-1` all, `1` ICMP, `6` TCP, `17` UDP, `58` ICMPv6.

**Ephemeral port ranges:** Linux `32768–60999`; Windows Server 2008+ `49152–65535`; NLB and NAT gateway `1024–65535`; Lambda `1024–65535`. **Allow `1024–65535`** in NACLs to cover all clients.

**Other addresses to know:** `169.254.169.254` instance metadata (IMDS); `169.254.169.253` VPC DNS; `169.254.169.123` Amazon Time Sync; `172.31.0.0/16` default VPC; `172.17.0.0/16` Docker's default bridge — never use it for a VPC.

---

## Appendix B — Reusable JSON and CLI templates

**Security group rule referencing another group**

```json
[
  {
    "IpProtocol": "tcp",
    "FromPort": 5432,
    "ToPort": 5432,
    "UserIdGroupPairs": [
      { "GroupId": "sg-REPLACE", "Description": "app tier to postgres" }
    ]
  }
]
```

**Security group rule using a managed prefix list**

```json
[
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "PrefixListIds": [
      { "PrefixListId": "pl-REPLACE", "Description": "DNB branch offices" }
    ]
  }
]
```

**Gateway endpoint policy restricting S3 access to named buckets**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowNamedBucketsOnly",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": [
        "arn:aws:s3:::REPLACE-BUCKET",
        "arn:aws:s3:::REPLACE-BUCKET/*"
      ]
    }
  ]
}
```

**Bucket policy admitting only traffic from one VPC endpoint**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnlessThroughEndpoint",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::REPLACE-BUCKET",
        "arn:aws:s3:::REPLACE-BUCKET/*"
      ],
      "Condition": {
        "StringNotEquals": { "aws:SourceVpce": "vpce-REPLACE" }
      }
    }
  ]
}
```

**Flow log role trust policy (for the CloudWatch Logs destination)**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "vpc-flow-logs.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Standard NACL pair for a public web subnet**

```bash
# ingress
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --ingress --rule-number 100 \
  --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --ingress --rule-number 110 \
  --protocol tcp --port-range From=80,To=80 --cidr-block 0.0.0.0/0 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --ingress --rule-number 200 \
  --protocol tcp --port-range From=1024,To=65535 --cidr-block 0.0.0.0/0 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --ingress --rule-number 32766 \
  --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny
# egress
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --egress --rule-number 100 \
  --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --egress --rule-number 200 \
  --protocol tcp --port-range From=1024,To=65535 --cidr-block 0.0.0.0/0 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL" --egress --rule-number 32766 \
  --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny
```

**Interface endpoints commonly needed by a private subnet**

```bash
for svc in ssm ssmmessages ec2messages secretsmanager kms logs sts monitoring \
           ecr.api ecr.dkr; do
  aws ec2 create-vpc-endpoint --vpc-id "$VPC_ID" --vpc-endpoint-type Interface \
    --service-name "com.amazonaws.${AWS_DEFAULT_REGION:-us-east-1}.$svc" \
    --subnet-ids "$SUBNET_APP_1A" "$SUBNET_APP_1B" \
    --security-group-ids "$SG_VPCE" --private-dns-enabled \
    --tag-specifications "ResourceType=vpc-endpoint,Tags=[{Key=Name,Value=dnb-dev-vpce-$svc},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]" \
    --query 'VpcEndpoint.VpcEndpointId' --output text 2>&1 | head -1
done
```

---

## Appendix C — Quotas reference (AWS defaults)

| Resource | Default | Adjustable |
|---|---|---|
| VPCs per Region | 5 | yes |
| IPv4 CIDR blocks per VPC | 5 | yes (to 50) |
| IPv6 CIDR blocks per VPC | 5 | yes |
| Subnets per VPC | 200 | yes |
| Subnet prefix length | `/16` – `/28` | no |
| Reserved addresses per subnet | 5 | no |
| Route tables per VPC | 200 | yes |
| Routes per route table (non-propagated) | 500 | yes |
| Propagated routes per route table | 100 | no |
| Network ACLs per VPC | 200 | yes |
| Rules per network ACL (per direction) | 20 | yes (to 40) |
| Security groups per Region | 2 500 | yes |
| Inbound rules per security group | 60 | yes |
| Outbound rules per security group | 60 | yes |
| Security groups per network interface | 5 | yes (to 16) |
| Rules per network interface (SGs × rules) | 1 000 | no |
| Internet gateways per Region | 5 | yes |
| Internet gateways per VPC | 1 | no |
| NAT gateways per Availability Zone | 5 | yes |
| Elastic IP addresses per Region | 5 | yes |
| Active VPC peering connections per VPC | 50 | yes (to 125) |
| Outstanding VPC peering requests | 25 | yes |
| Peering request expiry | 7 days | no |
| Interface + GWLB endpoints per VPC | 50 | yes |
| Gateway endpoints per Region | 20 | yes (up to 255 per VPC) |
| VPC endpoint policy size | 20 480 characters | no |
| VPC endpoint MTU | 8 500 bytes (PMTUD unsupported) | no |
| NAT gateway simultaneous connections per unique destination | 55 000 | no |

Always confirm current values with `aws service-quotas list-service-quotas --service-code vpc` in a real account, and against the linked AWS documentation below.

---

## Appendix D — Floci support summary for this module

| Feature area | Tier | Notes |
|---|---|---|
| VPC create/describe/delete/attributes | ✅ | including `CreateDefaultVpc`, `Associate/DisassociateVpcCidrBlock` |
| Subnets | ✅ | `ModifySubnetAttribute` supported; subnet CIDR reservations not published |
| Route tables and routes | ✅ structure / ❌ forwarding | objects stored; no packet routing |
| Internet gateway | ✅ structure / ❌ NAT function | |
| NAT gateway | ✅ structure / ❌ translation | |
| Egress-only IGW | ❌ | not in the published operation list |
| Elastic IPs | ✅ | full allocate/associate/release set |
| Network interfaces | ⚠️ | listed; probe the exact operation set |
| Security groups | ✅ structure / ❌ filtering | full rule API including `ModifySecurityGroupRules` |
| Network ACLs | ✅ structure / ❌ evaluation | full entry and association API |
| VPC endpoints (gateway + interface) | ⚠️ | create/describe/delete supported; traffic path not observable |
| Endpoint services you publish | ❌ | `CreateVpcEndpointServiceConfiguration` not published |
| Prefix lists | ⚠️ | listed; probe `create-managed-prefix-list` separately |
| VPC peering | ❌ | absent from the published list |
| Transit gateway | ❌ | |
| Flow logs | ❌ | |
| DHCP option sets | ❌ | |
| Reachability Analyzer / Network Access Analyzer | ❌ | replaced by `bin/reach.py` |
| Network Firewall / GWLB / Traffic Mirroring | ❌ | conceptual only |
| IPAM | ❌ | replaced by `out/ipam-record.md` |

**Reminder:** this table reflects Floci's published coverage at the time of writing. Your build is the authority. Regenerate `out/support-matrix.tsv` and correct anything that differs — and say so in your report.

---

## Sources

Floci documentation and project:

- [EC2 — Floci (supported operations)](https://floci.io/floci/services/ec2/)
- [Services Overview — Floci](https://floci.io/floci/services/)
- [floci — Fast, Free AWS Emulator](https://floci.io/aws/)
- [Floci — Local Cloud Emulators](https://floci.io/)
- [floci-io/floci on GitHub](https://github.com/floci-io/floci)
- [floci-io/floci-cli on GitHub](https://github.com/floci-io/floci-cli)
- [Floci: The Lightweight Local AWS Emulator (Gerardo Ocampos)](https://blog-ocampoge.medium.com/floci-the-lightweight-local-aws-emulator-360d0030f504)
- [Introducing Floci: The Fast, Free, and Open-Source AWS Emulator (Hector Ventura)](https://hectorvent.dev/posts/introducing-floci/)
- [Floci — Local AWS Emulator (docs mirror)](https://fredpena-floci.mintlify.app/introduction)

AWS documentation:

- [Amazon VPC quotas](https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html)
- [Amazon VPC endpoints and quotas (AWS General Reference)](https://docs.aws.amazon.com/general/latest/gr/vpc-service.html)
- [VPC peering connection quotas](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-connection-quotas.html)
- [AWS PrivateLink quotas](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-limits-endpoints.html)
- [Subnet CIDR blocks and sizing](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html)
- [Amazon VPC FAQs](https://aws.amazon.com/vpc/faqs/)
- [Amazon VPC raises default Route Table capacity (2025)](https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-vpc-raises-default-route-table-capacity/)
- [amazon-vpc-user-guide source on GitHub](https://github.com/awsdocs/amazon-vpc-user-guide/blob/master/doc_source/amazon-vpc-limits.md)

Supplementary references consulted for quota and addressing cross-checks:

- [AWS Amazon VPC Service Limits (AWS Fundamentals)](https://awsfundamentals.com/limits/vpc)
- [AWS Service Limits — VPC and Subnets (Netgate)](https://docs.netgate.com/pfsense/en/latest/solutions/aws-vpn-appliance/aws-service-limits.html)
- [AWS Reserved IP Addresses Explained](https://subnettool.com/learn/aws/)
- [AWS VPC Subnetting Best Practices: Reserved IPs and CIDR Planning](https://www.subnetcalculator.dev/blog/aws-vpc-subnetting-best-practices/)
- [AWS Networking: VPC, Subnets, Security Groups Explained](https://dasroot.net/posts/2026/01/aws-vpc-subnets-security-groups/)
- [How to Fix 'The maximum number of VPCs has been reached'](https://oneuptime.com/blog/post/2026-02-12-fix-maximum-number-vpcs-reached-error/view)
- [How to Configure VPC Subnet CIDR Reservations](https://oneuptime.com/blog/post/2026-02-12-configure-vpc-subnet-cidr-reservations/view)

---

## End-of-module exercises

Complete all five. These integrate the whole module and are the bridge to the next one.

1. **The one-page design review.** Produce a single page (diagram plus at most 300 words) that a senior architect could approve or reject. It must state the addressing plan, the tier model, the egress strategy, the endpoint strategy, and the three assertions you would put in CI.

2. **The regression suite.** Extend `bin/verify-all.sh` with three new assertions of your own that would have caught three of the six debugging scenarios in §12 *before* they caused an incident. Justify each choice.

3. **The cost model.** Build a spreadsheet or script estimating the monthly cost of this topology in `us-east-1` at three traffic levels (10 GB, 1 TB, 50 TB egress per month), itemising NAT gateway hours, NAT data processing, public IPv4 addresses, interface endpoint hours, and cross-AZ transfer. State which single change gives the largest saving at each level.

4. **The divergence report.** Write a two-page report titled *"What I could not learn from an emulator"*. For each item: the AWS behaviour, why Floci cannot reproduce it, the compensating method you used, and the residual uncertainty. This is the most professionally useful artefact in the module — a senior engineer's core skill is knowing the limits of their evidence.

5. **The handover.** Write the runbook you would give Dana on her first day: how to find which route table governs a subnet, how to diagnose a hang, how to add a new subnet safely, what she must never do without Bob's approval, and how to tear down a test VPC completely. Maximum two pages, written for someone who has never seen this VPC.
# Lab 04 — Build a Production-Shaped VPC and Launch EC2 Into It

> **Course:** Cloud Computing & AWS for Software Engineers (Year 4)
> **Format:** Follow-along. Type every command in order. Do not skip steps — later steps depend on IDs saved by earlier ones.
> **Environment:** Floci CLI (local AWS emulator, `http://localhost:4566`). CLI only, no Console.
> **Time:** ~4 hours for Parts 0–5, plus 1–3 hours for the challenges.
> **Aligns with:** AWS Certified Solutions Architect – Associate (SAA-C03), Domains 1 and 2.

---

## What you will have built

By the end of Part 3 you will have, entirely from the command line:

```
                              ┌──────────────┐
                              │   Internet   │
                              └──────┬───────┘
                              ┌──────┴───────┐
                              │ dnb-dev-igw  │
                              └──────┬───────┘
  ╔══════════════════════════════════╪══════════════════════════════════════╗
  ║ VPC dnb-dev-vpc   10.20.0.0/16   │                                      ║
  ║   AZ #1                          │              AZ #2                   ║
  ║  ┌──────────────────────────┐    │    ┌──────────────────────────┐      ║
  ║  │ PUBLIC 10.20.0.0/20      │◄───┴───►│ PUBLIC 10.20.16.0/20      │      ║
  ║  │  • i-web-1  (EIP)        │         │  • nat-1b (EIP)           │      ║
  ║  │  • nat-1a  (EIP)         │         │  rtb-public (shared)      │      ║
  ║  │  rtb-public 0/0→igw      │         │                           │      ║
  ║  └───────────┬──────────────┘         └───────────┬──────────────┘      ║
  ║              │ 0/0 → nat-1a                       │ 0/0 → nat-1b        ║
  ║  ┌───────────┴──────────────┐         ┌───────────┴──────────────┐      ║
  ║  │ APP 10.20.32.0/20        │         │ APP 10.20.48.0/20        │      ║
  ║  │  • i-app-1 (eth0 + eth1) │         │  • vpce-sts ENI          │      ║
  ║  │  • vpce-sts ENI          │         │  rtb-private-1b          │      ║
  ║  │  sg-app: 8080 from sg-web│         │                          │      ║
  ║  └───────────┬──────────────┘         └───────────┬──────────────┘      ║
  ║              │ local only                         │ local only          ║
  ║  ┌───────────┴──────────────┐         ┌───────────┴──────────────┐      ║
  ║  │ DATA 10.20.64.0/20       │         │ DATA 10.20.80.0/20       │      ║
  ║  │  sg-db: 5432 from sg-app │         │  rtb-data (shared)       │      ║
  ║  │  acl-data (explicit)     │         │  NO 0.0.0.0/0 ROUTE      │      ║
  ║  └──────────────────────────┘         └──────────────────────────┘      ║
  ║   vpce-s3  (Gateway)   → prefix-list route in private + data tables      ║
  ║   vpce-sts (Interface) → ENIs in both app subnets, sg-vpce allows 443    ║
  ╚═════════════════════════════════════════════════════════════════════════╝
```

Plus a set of scripts you will write yourself:

| Script | What it does |
| --- | --- |
| `bin/ids.sh` | Key/value ledger so resource IDs survive between shells |
| `bin/probe-vpc-support.sh` | Discovers which EC2/VPC operations your Floci build implements |
| `bin/reach.py` | Applies AWS's real packet-evaluation algorithm to your live config |
| `bin/routing-report.sh` | Classifies every subnet as public / private / isolated |
| `bin/verify-all.sh` | One command that asserts the whole design is intact |
| `bin/cleanup.sh` | Dependency-ordered teardown |

---

## The rule that governs this entire lab

An emulator can **store** your network configuration. It almost certainly cannot **route your packets**.

Floci speaks the EC2 wire protocol and will happily accept `CreateRouteTable`, `AuthorizeSecurityGroupIngress` and `CreateNetworkAclEntry`. It stores those objects and returns them from `Describe*`. That does **not** mean a security group filters anything, that NACL rule numbers are evaluated, or that the absence of an internet-gateway route prevents egress. Real AWS enforces all of that in the Nitro/hypervisor data plane; a single-Docker-network emulator by definition does not.

So every claim you make in this lab must be labelled with its evidence level:

| Level | Question it answers | Tool | Available here? |
| --- | --- | --- | --- |
| **L1 Existence** | Does the object exist with the properties I intended? | `describe-*` + `--query` | ✅ yes |
| **L2 Intent** | Does the configuration as a whole express the policy I designed? | `bin/reach.py`, assertion scripts | ✅ yes (computed) |
| **L3 Observation** | Do packets actually behave that way? | Reachability Analyzer, flow logs, `nc` from an instance | ❌ AWS only |

**Never write** *"the security group blocked my traffic."* Write:

> *"AWS would drop this packet because `sg-db` has no inbound rule matching TCP/5432 from `sg-web`; verified at L2 by `reach.py`. My Floci build accepted the call, which is a data-plane divergence recorded in `out/divergence-log.md`."*

Engineers who learned networking on emulators and never made this distinction are the same engineers who open `0.0.0.0/0` on port 22 "because it worked locally".

---

## The scenario

**Druk National Bank (DNB)**, a Bhutanese retail bank with 41 branches, is migrating its monthly statement-generation platform to AWS. It reads transactions from PostgreSQL, renders PDFs, writes them to S3, and serves them through a customer portal. DNB is regulated by the Royal Monetary Authority (RMA).

Ten requirements drive every decision you will make:

| # | Requirement | Satisfied by |
| --- | --- | --- |
| R1 | Customer data must not sit in a subnet with a route to an internet gateway | Step 4 — isolated `rtb-data` |
| R2 | Data-tier access to AWS APIs must be private | Step 7 — S3 gateway endpoint |
| R3 | Must survive the loss of one AZ | Step 2, 4 — two AZs, per-AZ NAT + route table |
| R4 | DB access restricted to the app tier **by identity, not address** | Step 5 — SG referencing |
| R5 | The database must not initiate outbound connections | Steps 4, 5, 6 — no egress, no route, NACL deny |
| R6 | No administrative port reachable from the internet | Steps 5, 8 — no SSH rules, SSM path |
| R7 | Every resource attributable to a cost centre and owner | All steps — five mandatory tags at creation |
| R8 | Network flow metadata retained 400 days | Conceptual (flow logs unsupported locally) |
| R9 | Only the platform team may change routes | Challenge 5 |
| R10 | Addressing must not collide with branches or staging/prod | Step 0.4 — allocation record |

---

## Conventions used throughout

| Convention | Value |
| --- | --- |
| Naming | `<org>-<env>-<function>[-<qualifier>]` → `dnb-dev-subnet-app-1a` |
| Region | `us-east-1` |
| VPC CIDR | `10.20.0.0/16` (RFC 1918; DNB's `dev` allocation) |
| Subnet size | `/20` = 4 096 addresses, **4 091 usable** (AWS reserves 5) |
| Workspace | `~/vpc-lab` with `bin/`, `out/`, `policies/` |
| Mandatory tags | `Project=CoreBanking`, `Environment=dev`, `Owner=platform-team`, `CostCenter=CC-4400`, `ManagedBy=floci-lab` |
| Tier tag | `Tier=public|app|data` — drives routing, NACLs and the reachability matrix |

---
---

# PART 0 — Set up your workspace and safety rails

Everything in Part 0 is done once. It takes about 25 minutes and it is the part students most often skip and most often regret skipping.

## Step 0.1 — Check your prerequisites

**Do this:**

```bash
floci --version
docker info | head -n 3
aws --version
jq --version
python3 --version
python3 -c "import ipaddress; print('ipaddress ok')"
```

**You should see** a version string from each. If `jq` or `python3` are missing:

```bash
# Debian / Ubuntu
sudo apt-get install -y jq python3
# macOS
brew install jq python3
```

**Checkpoint:** all six commands print a version and none print "command not found".

> **Before you continue — refresh your CIDR maths.** If you cannot answer *"how many usable host addresses are in a `/20`, and what is the broadcast address of `10.20.32.0/20`?"* in under thirty seconds, spend fifteen minutes with `ipcalc` now. Step 2 is unforgiving about this, and so is the SAA-C03 exam.

---

## Step 0.2 — Start Floci and install the safety guard

**Do this:**

```bash
# 1. Start the emulator. --persist keeps state across restarts, which matters
#    because this lab is cumulative.
floci start --persist ./floci-state --detach

# 2. Block until it is accepting requests
floci wait --timeout 2m

# 3. Export AWS_ENDPOINT_URL, credentials and region into this shell
eval "$(floci env)"

# 4. Confirm your shell is pointed at Floci and NOT at real AWS
echo "$AWS_ENDPOINT_URL"

# 5. Confirm the EC2 API answers at all
aws ec2 describe-availability-zones --query 'AvailabilityZones[].ZoneName' --output text
```

**You should see:**

```
http://localhost.floci.io:4566
us-east-1a	us-east-1b	us-east-1c	us-east-1d	us-east-1e	us-east-1f
```

Some builds synthesise only two or three AZs. That is fine — this lab needs exactly **two**. Note which two your build offers; you will pin them in Step 2. If step 5 fails with `InvalidAction`, your build did not start the EC2 service; retry with `floci start --services ec2,iam,s3,logs,sts`.

**Now install the guard.** `AWS_ENDPOINT_URL` is the only thing keeping your commands inside the emulator. If it is empty, the *exact same commands* hit real AWS with whatever credentials sit in `~/.aws/credentials`. In this lab the worst case is a **billable NAT gateway** (~USD 32/month each, plus data processing) and **Elastic IPs**, which are charged even while idle.

```bash
cat >> ~/.bashrc <<'RC'

guard() {
  case "${AWS_ENDPOINT_URL:-}" in
    *localhost*|*127.0.0.1*|*floci*) echo "OK: targeting Floci at $AWS_ENDPOINT_URL" ;;
    *) echo "REFUSING TO RUN: AWS_ENDPOINT_URL is '${AWS_ENDPOINT_URL:-<empty>}'" >&2; return 1 ;;
  esac
}
RC
source ~/.bashrc
guard
```

**Checkpoint:** `guard` prints `OK: targeting Floci at http://...`.

> **Habit to build now:** type `guard` before every command in this lab that creates something billable — `allocate-address` and `create-nat-gateway` above all. It costs you one second and it has saved real students real money.

---

## Step 0.3 — Create the workspace and the ID ledger

A VPC build produces roughly thirty interdependent opaque IDs (`vpc-…`, `subnet-…`, `rtb-…`, `igw-…`, `nat-…`, `acl-…`, `sg-…`, `eni-…`, `vpce-…`, `i-…`). Losing them mid-lab is the single most common reason students cannot finish.

**Do this:**

```bash
mkdir -p ~/vpc-lab/{bin,out,policies} && cd ~/vpc-lab

cat > ~/vpc-lab/bin/ids.sh <<'SH'
# ~/vpc-lab/bin/ids.sh — tiny key/value store for resource IDs.
# SOURCE this file (do not execute it) so the functions land in your shell.
LEDGER="$HOME/vpc-lab/out/ids.env"
mkdir -p "$HOME/vpc-lab/out"
touch "$LEDGER"

setid() {  # setid VPC_ID vpc-0abc...
  local k="$1" v="$2"
  grep -v "^export ${k}=" "$LEDGER" > "${LEDGER}.tmp" 2>/dev/null || true
  mv "${LEDGER}.tmp" "$LEDGER"
  printf 'export %s=%s\n' "$k" "$v" >> "$LEDGER"
  export "$k=$v"
  printf 'ledger: %s=%s\n' "$k" "$v"
}

unsetid() {  # unsetid BAD_SUBNET
  grep -v "^export ${1}=" "$LEDGER" > "${LEDGER}.tmp" 2>/dev/null || true
  mv "${LEDGER}.tmp" "$LEDGER"
  unset "$1"
  printf 'ledger: removed %s\n' "$1"
}

loadids() { set -a; . "$LEDGER"; set +a; }
SH

. ~/vpc-lab/bin/ids.sh
loadids
echo "ledger ready at $LEDGER"
```

**Checkpoint:** `type setid` reports it is a shell function.

> **Start every future lab session with exactly this block:**
> ```bash
> eval "$(floci env)"; guard; cd ~/vpc-lab; . bin/ids.sh; loadids
> ```
> Write it on a sticky note. You will type it a dozen times.

---

## Step 0.4 — Write down the addressing plan before you build anything

There is no "CIDR reservation" object in AWS. Reservations live in documentation, and a team that does not keep one eventually discovers that `dev`, `staging` and `prod` all chose `10.0.0.0/16` and can never be peered.

**Do this:**

```bash
cat > out/ipam-record.md <<'MD'
# DNB IPv4 allocation record — dev environment

| CIDR | Purpose | AZ | Usable | Status |
|---|---|---|---|---|
| 10.20.0.0/20   | public / edge         | AZ-1 | 4 091 | Step 2 |
| 10.20.16.0/20  | public / edge         | AZ-2 | 4 091 | Step 2 |
| 10.20.32.0/20  | app tier              | AZ-1 | 4 091 | Step 2 |
| 10.20.48.0/20  | app tier              | AZ-2 | 4 091 | Step 2 |
| 10.20.64.0/20  | data tier             | AZ-1 | 4 091 | Step 2 |
| 10.20.80.0/20  | data tier             | AZ-2 | 4 091 | Step 2 |
| 10.20.96.0/20  | third AZ public+app   | AZ-3 | —     | RESERVED (Challenge 1) |
| 10.20.112.0/20 | third AZ data         | AZ-3 | —     | RESERVED (Challenge 1) |
| 10.20.128.0/17 | future expansion      | —    | —     | RESERVED |

Neighbouring allocations — DO NOT OVERLAP:
  dnb-staging   10.21.0.0/16
  dnb-prod      10.22.0.0/16
  branch offices (on-premises, via future VPN)  172.16.0.0/16

Never use 172.17.0.0/16 — that is Docker's default bridge network and it
will break containers running on your instances.
MD

# A helper you will use repeatedly. Add it to your shell.
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

> **Tip:** paste the `cidrinfo` function into `bin/ids.sh` as well, so it comes back every time you `. bin/ids.sh`. Shell functions defined at the prompt vanish when you close the terminal; you will want this one in Step 2 and again in Challenge 1.

**You should see:**

```
network      10.20.32.0
broadcast    10.20.47.255
total        4096
aws usable   4091
reserved     10.20.32.0, 10.20.32.1, 10.20.32.2, 10.20.32.3, 10.20.47.255
first usable 10.20.32.4
last usable  10.20.47.254
```

**Why five addresses are reserved in *every* subnet:**

| Address | Reserved for |
| --- | --- |
| `.0` | Network address |
| `.1` | The VPC router — your default gateway |
| `.2` | Amazon-provided DNS resolver (also answers at VPC base+2, i.e. `10.20.0.2`) |
| `.3` | Reserved by AWS for future use |
| last | Broadcast address — reserved even though VPC does not support broadcast |

So `usable = 2^(32−prefix) − 5`. A `/28` — the smallest subnet AWS permits — holds **11** hosts, not 16.

**Checkpoint:** `out/ipam-record.md` exists and `cidrinfo 10.20.64.0/20` prints `aws usable 4091`.

---

## Step 0.5 — Discover what your Floci build actually implements

Do not trust any support table, including the one in this document. Probe it yourself. The trick is to classify by the **error code**, not by success alone: an operation that rejects a deliberately fake resource ID with `InvalidVpcID.NotFound` has clearly been routed to a real handler, which proves it exists.

**Do this:**

```bash
cat > bin/probe-vpc-support.sh <<'SH'
#!/usr/bin/env bash
# Discover which EC2/VPC operations this Floci build implements.
set -uo pipefail
OUT=~/vpc-lab/out/support-matrix.tsv
: > "$OUT"

classify() {
  local name="$1"; shift
  local stderr rc
  stderr="$("$@" 2>&1 >/dev/null)"; rc=$?
  if [ $rc -eq 0 ]; then
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED" "-" >> "$OUT"
  elif grep -qiE 'InvalidAction|not implemented|NotImplemented|UnknownOperation|InternalFailure|501' <<<"$stderr"; then
    printf '%s\t%s\t%s\n' "$name" "UNSUPPORTED" "$(head -c 110 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  elif grep -qiE 'NotFound|InvalidParameterValue|MissingParameter|InvalidParameterCombination|ValidationError|Malformed|AlreadyExists|InvalidVpcID|InvalidSubnetID|InvalidGroup|InvalidRouteTableID|InvalidNetworkAclID|InvalidAllocationID|InvalidAMIID' <<<"$stderr"; then
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED(validated)" "$(head -c 110 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  else
    printf '%s\t%s\t%s\n' "$name" "UNKNOWN" "$(head -c 110 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  fi
}

# --- Read-only describes: safe anywhere ---
for op in describe-vpcs describe-subnets describe-route-tables describe-internet-gateways \
          describe-nat-gateways describe-security-groups describe-network-acls \
          describe-addresses describe-network-interfaces describe-vpc-endpoints \
          describe-availability-zones describe-instances describe-images \
          describe-key-pairs describe-instance-types \
          describe-vpc-peering-connections describe-flow-logs describe-dhcp-options; do
  classify "ec2:$op" aws ec2 "$op"
done

# --- Mutating operations probed with deliberately non-existent IDs ---
classify "ec2:modify-vpc-attribute"     aws ec2 modify-vpc-attribute --vpc-id vpc-00000000000000000 --enable-dns-hostnames
classify "ec2:modify-subnet-attribute"  aws ec2 modify-subnet-attribute --subnet-id subnet-00000000000000000 --map-public-ip-on-launch
classify "ec2:create-subnet"            aws ec2 create-subnet --vpc-id vpc-00000000000000000 --cidr-block 10.99.0.0/24
classify "ec2:create-route"             aws ec2 create-route --route-table-id rtb-00000000000000000 --destination-cidr-block 0.0.0.0/0 --gateway-id igw-00000000000000000
classify "ec2:associate-route-table"    aws ec2 associate-route-table --route-table-id rtb-00000000000000000 --subnet-id subnet-00000000000000000
classify "ec2:attach-internet-gateway"  aws ec2 attach-internet-gateway --internet-gateway-id igw-00000000000000000 --vpc-id vpc-00000000000000000
classify "ec2:create-nat-gateway"       aws ec2 create-nat-gateway --subnet-id subnet-00000000000000000 --allocation-id eipalloc-00000000000000000
classify "ec2:authorize-sg-ingress"     aws ec2 authorize-security-group-ingress --group-id sg-00000000000000000 --protocol tcp --port 443 --cidr 10.0.0.0/8
classify "ec2:create-network-acl-entry" aws ec2 create-network-acl-entry --network-acl-id acl-00000000000000000 --ingress --rule-number 100 --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow
classify "ec2:create-vpc-endpoint"      aws ec2 create-vpc-endpoint --vpc-id vpc-00000000000000000 --service-name com.amazonaws.us-east-1.s3
classify "ec2:run-instances"            aws ec2 run-instances --image-id ami-00000000000000000 --instance-type t3.micro --subnet-id subnet-00000000000000000
classify "ec2:create-network-interface" aws ec2 create-network-interface --subnet-id subnet-00000000000000000
classify "ec2:attach-network-interface" aws ec2 attach-network-interface --network-interface-id eni-00000000000000000 --instance-id i-00000000000000000 --device-index 1
classify "ec2:create-key-pair"          aws ec2 create-key-pair --key-name __probe__
classify "ec2:associate-address"        aws ec2 associate-address --allocation-id eipalloc-00000000000000000 --instance-id i-00000000000000000
classify "ec2:create-flow-logs"         aws ec2 create-flow-logs --resource-type VPC --resource-ids vpc-00000000000000000 --traffic-type ALL --log-group-name x --deliver-logs-permission-arn arn:aws:iam::000000000000:role/x
classify "ec2:create-vpc-peering"       aws ec2 create-vpc-peering-connection --vpc-id vpc-00000000000000000 --peer-vpc-id vpc-11111111111111111

column -t -s $'\t' "$OUT"
echo
echo "SUMMARY:"; awk -F'\t' '{c[$2]++} END{for(k in c) printf "  %-22s %d\n", k, c[k]}' "$OUT"

# Clean up the one artefact this probe can create
aws ec2 delete-key-pair --key-name __probe__ >/dev/null 2>&1 || true
SH

chmod +x bin/probe-vpc-support.sh
./bin/probe-vpc-support.sh | tee out/support-report.txt
```

**You should see** something shaped like this — **your values will differ, and that is the entire point**:

```
ec2:describe-vpcs                  SUPPORTED             -
ec2:describe-route-tables          SUPPORTED             -
ec2:create-subnet                  SUPPORTED(validated)  InvalidVpcID.NotFound: ...
ec2:create-nat-gateway             SUPPORTED(validated)  InvalidSubnetID.NotFound: ...
ec2:run-instances                  SUPPORTED(validated)  InvalidAMIID.NotFound: ...
ec2:create-flow-logs               UNSUPPORTED           InvalidAction: ...
ec2:create-vpc-peering             UNSUPPORTED           InvalidAction: ...
...
SUMMARY:
  SUPPORTED              15
  SUPPORTED(validated)   14
  UNSUPPORTED             4
  UNKNOWN                 2
```

**How to read it:**

- `SUPPORTED` — the call succeeded outright.
- `SUPPORTED(validated)` — the call was routed to a real handler which then rejected your fake input. Strong evidence the operation exists.
- `UNSUPPORTED` — the emulator does not know this action.
- `UNKNOWN` — read the message by hand and reclassify it.

> **Trap:** `describe-flow-logs` and `describe-vpc-peering-connections` often return an **empty list** rather than an error even when the corresponding *create* is unimplemented. An empty successful `Describe` is **not** proof of support. That is exactly why every mutating operation is probed separately above.

**Checkpoint:** `wc -l out/support-matrix.tsv` reports 35 or so lines, and you can name at least two operations your build does not implement.

---

## Step 0.6 — Open the divergence log

Divergence between Floci and AWS is a **finding**, not a bug to fix. It tells you which parts of your mental model the emulator cannot validate for you, and therefore which parts you must reason about carefully before you touch a real account. This file is a graded deliverable.

**Do this:**

```bash
cat > out/divergence-log.md <<'MD'
# Floci divergence log — VPC + EC2 lab

| # | Step | Operation / behaviour | AWS-correct behaviour | Observed in Floci | Impact on my mental model |
|---|------|----------------------|-----------------------|-------------------|---------------------------|
MD
echo "divergence log opened"
```

You will add rows to this file at eight marked points during the lab. Each one takes ten seconds. Do not batch them up at the end — you will not remember.

**Checkpoint:** `out/divergence-log.md` exists.

---
---

# PART 1 — Build the network

Seven steps. Do not clean up between them; teardown happens once, in Part 5.

## Step 1 — Create the VPC and meet its three hidden defaults

**Goal.** Create `dnb-dev-vpc`, turn on both DNS attributes, and discover the three objects AWS creates alongside it that you did not ask for.

### 1a. Create it

```bash
guard || return 1

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

| Parameter | Meaning | Why this value |
| --- | --- | --- |
| `--cidr-block 10.20.0.0/16` | Primary IPv4 range, **immutable for life** | RFC 1918; DNB's `dev` allocation; `/16` leaves room for three AZs plus growth |
| `--instance-tenancy default` | Instances share hardware | `dedicated` forces every instance onto single-tenant hardware and cannot be relaxed per instance |
| `--tag-specifications` | Tags applied **atomically with the create** | A separate `create-tags` call can fail, leaving an untagged resource your cleanup sweep will miss |

> **Always tag at creation, never afterwards.** Our cleanup script finds resources *by tag*. An untagged resource is an orphan that costs money.

### 1b. Turn on DNS

`modify-vpc-attribute` accepts **one attribute per call**. That is a genuine API constraint, not a CLI quirk.

```bash
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames
```

| Attribute | Effect when `true` | Required for |
| --- | --- | --- |
| `enableDnsSupport` | The Amazon resolver at `10.20.0.2` answers queries | RDS endpoints, private hosted zones, endpoint private DNS, any public lookup |
| `enableDnsHostnames` | Instances get DNS names like `ip-10-20-32-4.ec2.internal`, and public names if they have public IPs | Public-facing hosts; also required alongside `enableDnsSupport` for interface-endpoint private DNS in Step 7 |

`enableDnsSupport=false` with `enableDnsHostnames=true` is an **invalid combination** and AWS rejects it.

### 1c. Look at what you got

```bash
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --output json
```

**You should see** (abridged):

```json
{
  "Vpcs": [{
    "OwnerId": "000000000000",
    "InstanceTenancy": "default",
    "CidrBlockAssociationSet": [{
      "CidrBlock": "10.20.0.0/16",
      "CidrBlockState": { "State": "associated" }
    }],
    "IsDefault": false,
    "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
    "State": "available",
    "CidrBlock": "10.20.0.0/16",
    "DhcpOptionsId": "dopt-0123456789abcdef0"
  }]
}
```

> 📓 **Divergence log entry #1.** Real AWS returns your 12-digit account ID in `OwnerId`. Floci commonly returns `000000000000`. Record it — it matters when you hand-write ARNs or resource policies, because a policy containing a real account ID will not match locally.

### 1d. Discover the three defaults

AWS created three objects atomically with your VPC. None of them can be deleted while the VPC exists, and **all three are permissive by design**.

```bash
echo "--- main route table ---"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Id:RouteTableId,Main:Associations[0].Main,Routes:Routes[].[DestinationCidrBlock,GatewayId]}' \
  --output json | tee out/step01-main-rtb.json

echo "--- default network ACL ---"
aws ec2 describe-network-acls --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkAcls[].{Id:NetworkAclId,Default:IsDefault,Entries:Entries[].[RuleNumber,Egress,RuleAction,CidrBlock,Protocol]}' \
  --output json | tee out/step01-default-acl.json

echo "--- default security group ---"
aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[].{Id:GroupId,Name:GroupName,In:IpPermissions,Out:IpPermissionsEgress}' \
  --output json | tee out/step01-default-sg.json
```

**What you should observe, and what it means:**

| Observation | Interpretation |
| --- | --- |
| Main route table has exactly one route, `10.20.0.0/16 → local` | The `local` route is implicit and **unremovable**. All subnets in this VPC will always be able to route to each other. Intra-VPC isolation is a *firewall* concern, never a routing concern. |
| Default NACL: ingress `100 ALLOW 0.0.0.0/0`, egress `100 ALLOW 0.0.0.0/0`, then `*` DENY | Fully permissive. It is a convenience, not a control. |
| Default SG: one ingress rule whose `UserIdGroupPairs` references **itself**; egress allow-all | Anything sharing the default SG can reach anything else sharing it, on every port. In a three-tier app that silently defeats tiering. |

### 1e. Save the IDs

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

### 1f. Break it — four ways

Each break states the **AWS-correct verdict first**. Your job is to test whether your Floci build agrees, and log any divergence.

```bash
# Break 1 — an out-of-range CIDR. AWS: rejected, /16..../28 only.
aws ec2 create-vpc --cidr-block 10.0.0.0/8 2>&1 | head -3

# Break 2 — delete the default SG. AWS: rejected, it is reserved.
aws ec2 delete-security-group --group-id "$SG_DEFAULT" 2>&1 | head -3

# Break 3 — delete the main route table. AWS: DependencyViolation.
aws ec2 delete-route-table --route-table-id "$RTB_MAIN" 2>&1 | head -3

# Break 4 — delete the local route. AWS: rejected, local is not yours.
aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 10.20.0.0/16 2>&1 | head -3
```

**Expected AWS errors:**

```
InvalidVpc.Range: The CIDR '10.0.0.0/8' is invalid.
CannotDelete: the specified group: "default" name is reserved and cannot be deleted.
DependencyViolation: The routeTable 'rtb-…' has dependencies and cannot be deleted.
InvalidParameterValue: cannot remove local route 10.20.0.0/16 in route table rtb-….
```

> 📓 **Divergence log entries #2–#5.** For each break, record whether Floci returned the same error. If Break 4 **succeeded** — if the `local` route can be deleted — flag it prominently: your build's route model is decorative, and every Track-A routing conclusion in this lab is invalidated for that build.

```bash
cat >> out/divergence-log.md <<'MD'
| 2 | 1 | create-vpc --cidr-block 10.0.0.0/8 | InvalidVpc.Range | (fill in) | (fill in) |
| 3 | 1 | delete-security-group (default) | CannotDelete | (fill in) | (fill in) |
| 4 | 1 | delete-route-table (main) | DependencyViolation | (fill in) | (fill in) |
| 5 | 1 | delete-route (local) | InvalidParameterValue | (fill in) | (fill in) |
MD
```

### ✅ Checkpoint 1

```bash
[ -n "${VPC_ID:-}" ] && [ -n "${RTB_MAIN:-}" ] && [ -n "${SG_DEFAULT:-}" ] \
  && aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --query 'Vpcs[0].State' --output text \
  && echo "STEP 1 PASS"
```

Expect `available` then `STEP 1 PASS`.

---

## Step 2 — Carve six subnets across two availability zones

**Goal.** Implement the tier-major plan from Step 0.4, set `MapPublicIpOnLaunch` explicitly in both directions, and prove the five-reserved-address rule empirically.

### 2a. Pin your two AZs

```bash
AZ_A=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[0].ZoneName' --output text)
AZ_B=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[1].ZoneName' --output text)
setid AZ_A "$AZ_A"
setid AZ_B "$AZ_B"
echo "using AZs: $AZ_A and $AZ_B"
```

> **In a multi-account world, prefer `--availability-zone-id`.** AZ *names* (`us-east-1a`) are randomised per AWS account — your `us-east-1a` and a colleague's may be different physical zones. AZ *IDs* (`use1-az4`) are stable across accounts. For a single-account lab, names are fine.

### 2b. Express the plan as data, then loop

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
    echo "  -> $name map-public-ip-on-launch = TRUE"
  else
    aws ec2 modify-subnet-attribute --subnet-id "$sid" --no-map-public-ip-on-launch
    echo "  -> $name map-public-ip-on-launch = false (explicit)"
  fi
done < out/subnet-plan.tsv
```

> **Why `while read … done < file` and not `cat file | while read`?** A piped loop runs in a **subshell**, so `setid`'s `export` would be discarded and none of the ledger variables would exist in your shell afterwards. This bites students in every module. Remember it.

### 2c. Inspect one subnet closely

```bash
aws ec2 describe-subnets --subnet-ids "$SUBNET_APP_1A" --output json
```

**You should see:**

```json
{
  "Subnets": [{
    "AvailabilityZone": "us-east-1a",
    "AvailabilityZoneId": "use1-az4",
    "AvailableIpAddressCount": 4091,
    "CidrBlock": "10.20.32.0/20",
    "MapPublicIpOnLaunch": false,
    "State": "available",
    "SubnetId": "subnet-0b1c2d3e4f5a6b7c8",
    "VpcId": "vpc-0a1b2c3d4e5f6a7b8",
    "Tags": [
      { "Key": "Name", "Value": "dnb-dev-subnet-app-1a" },
      { "Key": "Tier", "Value": "app" }
    ]
  }]
}
```

**`AvailableIpAddressCount: 4091`** is the whole point: `4096 − 5`.

> 📓 **Divergence log entry #6.** If your build reports `4096`, it has not implemented the reserved-address rule. That means it will let you place 4 096 ENIs where AWS fails at 4 091 — so your local capacity maths will be wrong by five per subnet, and Step 9's exhaustion exercise will behave differently.

### 2d. See the whole plan at once

```bash
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets, &CidrBlock)[].{
      Name:Tags[?Key==`Name`]|[0].Value,
      Tier:Tags[?Key==`Tier`]|[0].Value,
      CIDR:CidrBlock, AZ:AvailabilityZone,
      Free:AvailableIpAddressCount, PubIP:MapPublicIpOnLaunch}' \
  --output table | tee out/step02-subnets.txt
```

### 2e. Write your first assertion script

Eyeballing a table is not verification. Assert it.

```bash
cat > bin/verify-subnets.sh <<'SH'
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
        --query 'length(Subnets[?MapPublicIpOnLaunch==`true`])' --output text)
check "exactly two subnets auto-assign public IPs" "$pub" "2"

free=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
         --query 'Subnets[0].AvailableIpAddressCount' --output text)
check "reserved-5 rule applied (/20 -> 4091)" "$free" "4091"

for t in public app data; do
  c=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Tier,Values=$t" \
        --query 'Subnets[].AvailabilityZone' --output text | tr '\t' '\n' | sort -u | wc -l | tr -d ' ')
  check "tier '$t' spans two AZs" "$c" "2"
done
exit $fail
SH
chmod +x bin/verify-subnets.sh
./bin/verify-subnets.sh
```

### 2f. Break it

```bash
# Break 1 — overlapping CIDR. AWS: InvalidSubnet.Conflict.
#   10.20.8.0/21 sits INSIDE the existing 10.20.0.0/20. Overlap is overlap
#   even when the new block is smaller.
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.8.0/21 \
  --availability-zone "$AZ_A" 2>&1 | head -3

# Break 2 — outside the VPC range. AWS: InvalidParameterValue.
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.99.0.0/24 \
  --availability-zone "$AZ_A" 2>&1 | head -3

# Break 3 — smaller than /28. AWS: rejected.
aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.240.0/29 \
  --availability-zone "$AZ_A" 2>&1 | head -3
```

**Break 4 is the dangerous one, because it SUCCEEDS.** Omitting `--availability-zone` lets AWS choose, and it may choose the AZ you already used:

```bash
BAD_SUBNET=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.240.0/24 \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=dnb-dev-subnet-oops},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'Subnet.SubnetId' --output text)
setid BAD_SUBNET "$BAD_SUBNET"
aws ec2 describe-subnets --subnet-ids "$BAD_SUBNET" \
  --query 'Subnets[0].[SubnetId,CidrBlock,AvailabilityZone]' --output text
```

Now ask the question that matters: *if I built a "multi-AZ" load balancer across `dnb-dev-subnet-public-1a` and this subnet, would I actually have AZ redundancy?* Only if the AZ differs. **There is no API error to save you** — the failure surfaces during an AZ outage at 3 a.m.

### 2g. Fix it

```bash
aws ec2 delete-subnet --subnet-id "$BAD_SUBNET"
unsetid BAD_SUBNET
./bin/verify-subnets.sh
```

### ✅ Checkpoint 2

`./bin/verify-subnets.sh` prints nine `PASS` lines and exits 0.

---

## Step 3 — Attach an internet gateway and build public routing

**Goal.** Make the public subnets genuinely public, keep the main route table minimal, and see the implicit-association trap with your own eyes.

### 3a. Create and attach the IGW

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

An internet gateway does **two** jobs, and students conflate them:

1. It is the **routing target** that makes a subnet public.
2. It performs **1:1 NAT** between an instance's private IPv4 address and its public IPv4/EIP. That is why an instance never sees its own public IP in `ip addr` — the translation happens at the gateway. (For IPv6 it is a pure router; no translation, because IPv6 addresses on ENIs are globally routable.)

It is free, horizontally scaled, highly available, and has no configuration beyond "attach to one VPC".

### 3b. Public route table

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

| Parameter | Note |
| --- | --- |
| `--destination-cidr-block 0.0.0.0/0` | For IPv6 you would use `--destination-ipv6-cidr-block ::/0` |
| `--gateway-id` | Used for IGW, VGW **and** gateway endpoints. NAT gateways use `--nat-gateway-id` instead — a common mix-up |
| `associate-route-table` | Returns `rtbassoc-…`. **Without this, the subnet silently uses the main route table.** |

### 3c. Verify — with a definition, not a vibe

A subnet is public **if and only if** its associated route table has a `0.0.0.0/0` route whose target is an internet gateway. Names and tags mean nothing. Encode that:

```bash
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
./bin/public-subnets.sh | tee out/step03-public.txt
```

**You should see:**

```
PUBLIC via dnb-dev-rtb-public: explicit=['subnet-0d1e…', 'subnet-0e2f…'] main_table=False
```

Now confirm the other four subnets are still on the main table with only the `local` route:

```bash
aws ec2 describe-route-tables --route-table-ids "$RTB_MAIN" \
  --query 'RouteTables[0].{Explicit:Associations[?SubnetId!=null].SubnetId,Routes:Routes[].[DestinationCidrBlock,GatewayId,State]}' \
  --output json
```

Empty `Explicit`, one `local` route. Correct and intentional — the four private subnets currently have no internet path at all.

### 3d. Break it — the single most consequential VPC mistake

```bash
# Break 1 — put a default route on the MAIN table. AWS: ACCEPTED, and catastrophic.
aws ec2 create-route --route-table-id "$RTB_MAIN" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"

./bin/public-subnets.sh
```

The warning line should now fire. Every subnet you forgot to associate — including your data tier — has a path to the internet gateway. No error, no alarm, nothing.

```bash
# Break 2 — detach the IGW while routes reference it.
#   AWS: detach is permitted if no ENI has a public IP; the route goes BLACKHOLE.
aws ec2 detach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>&1 | head -3
aws ec2 describe-route-tables --route-table-ids "$RTB_PUBLIC" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId,State]' --output text

# Break 3 — a second internet gateway. AWS: Resource.AlreadyAssociated.
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>/dev/null
IGW2=$(aws ec2 create-internet-gateway --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW2" --vpc-id "$VPC_ID" 2>&1 | head -3
aws ec2 delete-internet-gateway --internet-gateway-id "$IGW2"
```

> 📓 **Divergence log entry #7.** In Break 2, look for `State` becoming `blackhole` on the `0.0.0.0/0` row. If your build leaves it `active`, log it — it means Floci will **never** show you a blackhole, so you must reason about deleted route targets manually for the rest of this lab.

### 3e. Fix it, permanently

```bash
# Undo Break 1 — the main table must contain nothing but `local`
aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 0.0.0.0/0

# Undo Break 2 — reattach and confirm the route returns to active
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>/dev/null \
  || echo "already attached"
aws ec2 describe-route-tables --route-table-ids "$RTB_PUBLIC" \
  --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].[GatewayId,State]' --output text
```

Now write the drift check that stops this class of error forever:

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

> **The permanent lesson.** Keep the main route table `local`-only forever, and associate every subnet explicitly. With an empty main table, forgetting an association **fails closed** instead of open. That is a preventive control, not a corrective one — and preventive controls are what senior engineers build.

### ✅ Checkpoint 3

`./bin/assert-main-rtb-minimal.sh` passes, and `./bin/public-subnets.sh` lists exactly two explicit subnets with `main_table=False`.

---

## Step 4 — NAT gateways, per-AZ private routing, and an isolated data tier

**Goal.** Give the app tier outbound-only internet access with **one NAT gateway per AZ**, and give the data tier no default route at all.

> ⚠️ **This step allocates Elastic IPs and NAT gateways.** In real AWS these are the two resources that generate surprise bills. Run `guard` first, every time.

### 4a. Two Elastic IPs

```bash
guard || return 1

for az in 1A 1B; do
  low=$(echo "$az" | tr 'A-Z' 'a-z')
  id=$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[
        {Key=Name,Value=dnb-dev-eip-nat-$low},{Key=Project,Value=CoreBanking},
        {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]" \
    --query 'AllocationId' --output text)
  setid "EIP_$az" "$id"
done

aws ec2 describe-addresses --allocation-ids "$EIP_1A" "$EIP_1B" \
  --query 'Addresses[].[AllocationId,PublicIp,Domain,AssociationId]' --output table
```

`AssociationId: None` means not yet attached — and **AWS bills an unassociated EIP**. Never allocate one you are not about to use.

### 4b. One NAT gateway per AZ, each in that AZ's *public* subnet

```bash
NAT_1A=$(aws ec2 create-nat-gateway \
  --subnet-id "$SUBNET_PUBLIC_1A" --allocation-id "$EIP_1A" --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[
      {Key=Name,Value=dnb-dev-nat-1a},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1A "$NAT_1A"

NAT_1B=$(aws ec2 create-nat-gateway \
  --subnet-id "$SUBNET_PUBLIC_1B" --allocation-id "$EIP_1B" --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[
      {Key=Name,Value=dnb-dev-nat-1b},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1B "$NAT_1B"

aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_1A" "$NAT_1B" 2>/dev/null \
  || echo "note: this build may not implement the nat-gateway-available waiter"

aws ec2 describe-nat-gateways --nat-gateway-ids "$NAT_1A" "$NAT_1B" \
  --query 'NatGateways[].[NatGatewayId,State,SubnetId,NatGatewayAddresses[0].PublicIp]' --output table
```

**The three facts about NAT gateways that exams and incidents test:**

1. It must live in a **public** subnet — its own ENI needs an IGW route. Putting it in a private subnet produces `State: failed` with `FailureCode: Gateway.NotAttached`, *asynchronously*, after the create call has already returned success.
2. It is **AZ-scoped**. One NAT for both AZs means AZ-b's traffic crosses to AZ-a: you pay cross-AZ data transfer on every byte and you lose AZ independence.
3. It has **no security group**. You cannot filter at the NAT. Egress filtering must happen at the instance's SG, at the NACL, or with a proxy / Network Firewall.

### 4c. One private route table per AZ

This is the entire reason we made two NAT gateways.

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

### 4d. The isolated data-tier route table

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
echo "data tier -> $RTB_DATA (local route only, no egress by design) [satisfies R1]"
```

**Three kinds of subnet — memorise this table:**

| Kind | Route table contains | Outbound internet? | Inbound from internet? |
| --- | --- | --- | --- |
| **Public** | `0.0.0.0/0 → igw-…` | Yes, if the ENI has a public IPv4/EIP | Yes (subject to SG/NACL) |
| **Private** | `0.0.0.0/0 → nat-…` | Yes, source-NATed | No |
| **Isolated** | no default route (`local` + endpoint prefix lists only) | **No** | No |

Our data tier is **isolated**, not merely private. That is what R1 demands.

> **Why the data table is shared but the app tables are not.** The app tables differ *because each points at a different NAT gateway*. The data table has no AZ-specific target — only `local` — so one shared table is correct and simpler. In Step 7 we add an S3 endpoint route, which is also AZ-agnostic.

### 4e. The report you will paste into every lab report

```bash
cat > bin/routing-report.sh <<'SH'
#!/usr/bin/env bash
# For every subnet: which route table applies (explicit or main), and the default route target.
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
        if str(r.get("GatewayId") or "").startswith("igw-"): return "PUBLIC"
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
./bin/routing-report.sh | tee out/step04-routing.txt
```

**You should see:**

```
subnet                       tier    az           route table                assoc     default route                class
------------------------------------------------------------------------------------------------------------------------
dnb-dev-subnet-public-1a     public  us-east-1a   dnb-dev-rtb-public         explicit  igw-0ff8… [active]           PUBLIC
dnb-dev-subnet-public-1b     public  us-east-1b   dnb-dev-rtb-public         explicit  igw-0ff8… [active]           PUBLIC
dnb-dev-subnet-app-1a        app     us-east-1a   dnb-dev-rtb-private-1a     explicit  nat-0abc… [active]           PRIVATE (NAT egress)
dnb-dev-subnet-app-1b        app     us-east-1b   dnb-dev-rtb-private-1b     explicit  nat-0def… [active]           PRIVATE (NAT egress)
dnb-dev-subnet-data-1a       data    us-east-1a   dnb-dev-rtb-data           explicit  NONE (isolated)              ISOLATED
dnb-dev-subnet-data-1b       data    us-east-1b   dnb-dev-rtb-data           explicit  NONE (isolated)              ISOLATED
```

**Every row says `explicit`. No row says `MAIN!`.** That single column is the difference between a design and an accident.

### 4f. Assert AZ affinity

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
nats = {n["NatGatewayId"]: n for n in aws("describe-nat-gateways").get("NatGateways",[])}
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
        ok = subs[sid]["AvailabilityZone"] == nat_az
        bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'} {sid} ({subs[sid]['AvailabilityZone']}) -> {nat} (in {nat_az})")
print("\nAZ affinity:", "OK" if bad==0 else f"{bad} cross-AZ route(s) — costs money and breaks AZ isolation")
sys.exit(1 if bad else 0)
PY
SH
chmod +x bin/assert-nat-az-affinity.sh
./bin/assert-nat-az-affinity.sh
```

### 4g. Break it

```bash
# Break 1 — NAT gateway in a PRIVATE subnet.
#   AWS: create SUCCEEDS, then State goes to `failed` asynchronously.
BAD_EIP=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=dnb-dev-eip-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'AllocationId' --output text)
setid BAD_EIP "$BAD_EIP"

BAD_NAT=$(aws ec2 create-nat-gateway --subnet-id "$SUBNET_DATA_1A" --allocation-id "$BAD_EIP" \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=dnb-dev-nat-probe},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid BAD_NAT "$BAD_NAT"
sleep 5
aws ec2 describe-nat-gateways --nat-gateway-ids "$BAD_NAT" \
  --query 'NatGateways[0].[NatGatewayId,State,FailureCode,FailureMessage]' --output text
```

Real AWS prints: `nat-0bad…  failed  Gateway.NotAttached  Network vpc-… has no Internet gateway attached`.

```bash
# Break 2 — cross-AZ NAT routing. AWS: ACCEPTED, works, and is wrong.
aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1B" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1A"
./bin/assert-nat-az-affinity.sh || echo "^ the assertion caught it"

# Break 3 — delete a NAT that routes reference. The EIP is NOT released.
aws ec2 delete-nat-gateway --nat-gateway-id "$BAD_NAT"
aws ec2 describe-addresses --allocation-ids "$BAD_EIP" \
  --query 'Addresses[0].[AllocationId,PublicIp,AssociationId]' --output text
echo "^ AssociationId is now None — and AWS is still billing for this EIP"
```

### 4h. Fix it, and build the habit that saves money

```bash
# Restore AZ affinity
aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1B" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1B"
./bin/assert-nat-az-affinity.sh

# Release the orphaned probe EIP
aws ec2 release-address --allocation-id "$BAD_EIP" 2>&1 | head -2 \
  || echo "EIP may still be held while the NAT finishes deleting; retry in a minute"
unsetid BAD_EIP; unsetid BAD_NAT

# THE STANDING CHECK. Run this at the end of every session, forever.
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp,Tags[?Key==`Name`]|[0].Value]' \
  --output table
```

### ✅ Checkpoint 4

`./bin/routing-report.sh` shows six subnets, all `explicit`, classified PUBLIC ×2 / PRIVATE ×2 / ISOLATED ×2, and `./bin/assert-nat-az-affinity.sh` exits 0.

---

## Step 5 — Security groups: identity-based network policy

**Goal.** Build a four-group chain using **security-group references, not CIDR literals**, and restrict egress deliberately.

```
   Internet
      │  443, 80
      ▼
  ┌──────────────┐   8080     ┌──────────────┐   5432    ┌──────────────┐
  │  sg-web      │───────────►│   sg-app     │──────────►│   sg-db      │
  │ in: 80,443   │            │ in: 8080 from│           │ in: 5432 from│
  │     0.0.0.0/0│            │     sg-web   │           │     sg-app   │
  │ out: →sg-app │            │ out: →sg-db, │           │ out: NOTHING │
  │      →sg-vpce│            │   →sg-vpce,  │           │              │
  └──────────────┘            │   443 for OS │           └──────────────┘
                              └──────┬───────┘
                                     │ 443
                                     ▼
                              ┌──────────────┐
                              │  sg-vpce     │ in: 443 from sg-app, sg-web
                              └──────────────┘
```

### 5a. Create the four groups

```bash
mksg() {   # mksg <ledger-key> <name> <description>
  local key="$1" name="$2" desc="$3" id
  id=$(aws ec2 create-security-group \
    --group-name "$name" --description "$desc" --vpc-id "$VPC_ID" \
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

`--description` is **mandatory** — AWS refuses to create a group without one. `--group-name` must be unique within the VPC and is immutable after creation.

### 5b. Ingress rules — zero intra-VPC CIDRs

```bash
# sg-web: genuinely internet-facing
aws ec2 authorize-security-group-ingress --group-id "$SG_WEB" \
  --ip-permissions '[
    {"IpProtocol":"tcp","FromPort":443,"ToPort":443,
     "IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTPS"}]},
    {"IpProtocol":"tcp","FromPort":80,"ToPort":80,
     "IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"public HTTP, redirects to 443"}]}
  ]' >/dev/null

# sg-app: only the ALB may reach the app port
aws ec2 authorize-security-group-ingress --group-id "$SG_APP" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_WEB\",\"Description\":\"ALB to app tier\"}]}
  ]" >/dev/null

# sg-db: only the app tier may reach PostgreSQL   [satisfies R4]
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":5432,\"ToPort\":5432,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"app tier to postgres\"}]}
  ]" >/dev/null

# sg-vpce: HTTPS from the tiers that call AWS APIs
aws ec2 authorize-security-group-ingress --group-id "$SG_VPCE" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"UserIdGroupPairs\":[
        {\"GroupId\":\"$SG_APP\",\"Description\":\"app tier to interface endpoints\"},
        {\"GroupId\":\"$SG_WEB\",\"Description\":\"web tier to interface endpoints\"}]}
  ]" >/dev/null
```

> **Learn `--ip-permissions` properly.** The short form `--protocol tcp --port 443 --cidr 0.0.0.0/0` can express only one CIDR rule and **cannot express a security-group reference or a description**. `--ip-permissions` is the only form that covers everything, and it is what the SDKs and CloudFormation use.

**Why reference groups instead of CIDRs:**

```
  BAD:  sg-db inbound 5432 from 10.20.32.0/20, 10.20.48.0/20
        • breaks when you add an AZ or a secondary CIDR
        • allows ANY host in those subnets, including a compromised
          sidecar or a future unrelated workload

  GOOD: sg-db inbound 5432 from sg-app
        • identity-based, not location-based
        • auto-scales:  new app instances inherit access by getting sg-app
        • auto-shrinks: removing sg-app from an instance revokes access
        • survives re-addressing and new subnets
```

### 5c. Egress — the part every tutorial skips

Every new security group starts with **allow-all egress to `0.0.0.0/0`**. For a data tier that is a data-exfiltration path.

```bash
# sg-web may only talk to the app tier and the endpoints
aws ec2 revoke-security-group-egress --group-id "$SG_WEB" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
aws ec2 authorize-security-group-egress --group-id "$SG_WEB" \
  --ip-permissions "[
    {\"IpProtocol\":\"tcp\",\"FromPort\":8080,\"ToPort\":8080,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"ALB to app tier\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,
     \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_VPCE\",\"Description\":\"AWS API via endpoints\"}]}
  ]" >/dev/null

# sg-app: DB, endpoints, and HTTPS out for OS patching via NAT
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

# sg-db gets NO egress at all.  [satisfies R5]
aws ec2 revoke-security-group-egress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null

# sg-vpce: endpoint ENIs do not initiate connections
aws ec2 revoke-security-group-egress --group-id "$SG_VPCE" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
```

> **Why `sg-db` with zero egress still works.** Security groups are **stateful**. A client connects in on 5432 and the response leaves automatically, regardless of egress rules. Egress rules only govern connections the database *itself initiates* — replication to an external target, an outbound webhook, an attacker's exfiltration channel. Removing them costs nothing and closes a real hole.
>
> Contrast this with a network ACL, where removing egress would break every response. That contrast is Step 6.

### 5d. Verify

```bash
aws ec2 describe-security-groups --group-ids "$SG_DB" --output json
```

`"IpPermissionsEgress": []` is the goal. `"IpRanges": []` with a populated `UserIdGroupPairs` is the fingerprint of a correctly written identity-based rule.

Now build a reporting script with a built-in hygiene linter:

```bash
cat > bin/sg-report.sh <<'SH'
#!/usr/bin/env bash
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
        proto = p.get("IpProtocol"); proto = "ALL" if proto == "-1" else proto
        lo, hi = p.get("FromPort"), p.get("ToPort")
        port = "ALL" if lo is None else (str(lo) if lo == hi else f"{lo}-{hi}")
        srcs  = [r["CidrIp"] for r in p.get("IpRanges", [])]
        srcs += [f"sg:{byid.get(u['GroupId'], u['GroupId'])}" for u in p.get("UserIdGroupPairs", [])]
        srcs += [f"pl:{x['PrefixListId']}" for x in p.get("PrefixListIds", [])]
        rows.append(f"{proto}/{port} <- {', '.join(srcs) or '(none)'}")
    return rows or ["(none)"]

for g in sorted(sgs, key=lambda x: x["GroupName"]):
    print(f"\n{g['GroupName']}  ({g['GroupId']})")
    print(f"  desc: {g['Description']}")
    for r in render(g["IpPermissions"]):            print(f"  IN   {r}")
    for r in render(g.get("IpPermissionsEgress", [])): print(f"  OUT  {r}")

    for p in g["IpPermissions"]:
        for r in p.get("IpRanges", []):
            if r["CidrIp"] == "0.0.0.0/0":
                lo, hi = p.get("FromPort"), p.get("ToPort")
                if lo is None:
                    findings.append(f"{g['GroupName']}: ALL ports open to 0.0.0.0/0")
                elif any(lo <= q <= hi for q in (22, 3389)):
                    findings.append(f"{g['GroupName']}: SSH/RDP ({lo}-{hi}) open to 0.0.0.0/0")
    for p in g["IpPermissions"] + g.get("IpPermissionsEgress", []):
        for coll in ("IpRanges", "UserIdGroupPairs"):
            for item in p.get(coll, []):
                if not item.get("Description"):
                    findings.append(f"{g['GroupName']}: undescribed rule ({coll})")

print("\n--- hygiene findings ---")
for f in sorted(set(findings)): print("  !", f)
if not findings: print("  none")
PY
SH
chmod +x bin/sg-report.sh
./bin/sg-report.sh | tee out/step05-sg.txt
```

### 5e. Break it

```bash
# Break 1 — try to write a DENY rule. AWS: impossible; there is no such API.
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.32.7/32","Description":"deny this host"}]}]' >/dev/null
aws ec2 describe-security-groups --group-ids "$SG_DB" \
  --query 'SecurityGroups[0].IpPermissions[].[FromPort,IpRanges[].CidrIp,UserIdGroupPairs[].GroupId]' \
  --output json
```

Read that output. You have just **widened** access — the "deny this host" rule is an *allow*. This is why "block a single IP" always means NACL, never security group.

```bash
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.32.7/32"}]}]' >/dev/null

# Break 2 — a self-reference. AWS: ALLOWED and useful.
#   This is the correct idiom for cluster peer traffic (Consul, Cassandra, Redis cluster bus).
aws ec2 authorize-security-group-ingress --group-id "$SG_APP" \
  --ip-permissions "[{\"IpProtocol\":\"tcp\",\"FromPort\":7946,\"ToPort\":7946,
    \"UserIdGroupPairs\":[{\"GroupId\":\"$SG_APP\",\"Description\":\"cluster gossip between app nodes\"}]}]" >/dev/null

# Break 3 — delete a referenced group. AWS: DependencyViolation.
aws ec2 delete-security-group --group-id "$SG_APP" 2>&1 | head -3
```

Break 3 is why Part 5's cleanup **revokes all rules first, then deletes groups**.

### 5f. Assert the invariants

```bash
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

db, app, web = by.get("dnb-dev-sg-db"), by.get("dnb-dev-sg-app"), by.get("dnb-dev-sg-web")
check("sg-db exists", db is not None)
if db:
    check("sg-db has NO egress rules  [R5]", db.get("IpPermissionsEgress") == [])
    check("sg-db ingress uses only SG references  [R4]",
          all(not p.get("IpRanges") for p in db["IpPermissions"]))
    check("sg-db allows exactly one ingress rule", len(db["IpPermissions"]) == 1)
if app:
    check("sg-app ingress uses only SG references",
          all(not p.get("IpRanges") for p in app["IpPermissions"]))
if web:
    open_admin = [p for p in web["IpPermissions"]
                  for r in p.get("IpRanges", [])
                  if r["CidrIp"] == "0.0.0.0/0" and p.get("FromPort") is not None
                  and any(p["FromPort"] <= q <= p["ToPort"] for q in (22, 3389))]
    check("sg-web does not expose SSH/RDP to the internet  [R6]", not open_admin)
sys.exit(fail)
PY
SH
chmod +x bin/assert-sg-invariants.sh
./bin/assert-sg-invariants.sh
```

### ✅ Checkpoint 5

`./bin/assert-sg-invariants.sh` exits 0, and `./bin/sg-report.sh` shows `dnb-dev-sg-db` with `OUT (none)`.

---

## Step 6 — Network ACLs and the ephemeral-port trap

**Goal.** Build an explicit NACL for the data tier with correct rule numbering, and understand *exactly* why the return rule exists.

```
  ┌──────── acl-data (associated with data-1a and data-1b) ────────────────┐
  │ INGRESS                                                                │
  │   100  ALLOW  tcp 5432        from 10.20.32.0/20  (app-1a)             │
  │   110  ALLOW  tcp 5432        from 10.20.48.0/20  (app-1b)             │
  │ 32766  DENY   all             from 0.0.0.0/0   (explicit, auditable)   │
  │     *  DENY   all             (implicit, always last, immutable)       │
  │ EGRESS                                                                 │
  │   100  ALLOW  tcp 1024-65535  to   10.20.32.0/20  ← RETURN traffic     │
  │   110  ALLOW  tcp 1024-65535  to   10.20.48.0/20  ← RETURN traffic     │
  │ 32766  DENY   all             to   0.0.0.0/0                           │
  │     *  DENY   all                                                      │
  └────────────────────────────────────────────────────────────────────────┘
  NACLs cannot reference security groups. CIDRs are unavoidable here —
  which is exactly why NACLs are coarse policy and SGs are fine policy.
```

> ⚠️ **Create the rules BEFORE associating the NACL.** A brand-new NACL denies everything in both directions. Associate first and you black-hole the subnet until you finish typing.

### 6a. Create it and prove it starts deny-all

```bash
ACL_DATA=$(aws ec2 create-network-acl --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=network-acl,Tags=[
      {Key=Name,Value=dnb-dev-acl-data},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=data}]' \
  --query 'NetworkAcl.NetworkAclId' --output text)
setid ACL_DATA "$ACL_DATA"

aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries[].[RuleNumber,Egress,RuleAction,CidrBlock,Protocol]' --output text
```

**You should see only two rules, both DENY:**

```
32767	False	deny	0.0.0.0/0	-1
32767	True	deny	0.0.0.0/0	-1
```

The console renders that final catch-all as `*`; the API reports `RuleNumber: 32767`. You cannot create, modify or delete it. The highest number **you** may use is `32766`.

### 6b. Write the rules

```bash
CIDR_APP_1A=10.20.32.0/20
CIDR_APP_1B=10.20.48.0/20

# INGRESS — only PostgreSQL, only from the app subnets
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 100 --protocol tcp --port-range From=5432,To=5432 \
  --cidr-block "$CIDR_APP_1A" --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 110 --protocol tcp --port-range From=5432,To=5432 \
  --cidr-block "$CIDR_APP_1B" --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 32766 --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny

# EGRESS — the RETURN path, on EPHEMERAL ports
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block "$CIDR_APP_1A" --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 110 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block "$CIDR_APP_1B" --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 32766 --protocol -1 --cidr-block 0.0.0.0/0 --rule-action deny
```

> ⚠️ **The egress rule is about the CLIENT's port, not the server's.**
>
> Egress rule 100 allows TCP **1024–65535** to the app subnet — *not* TCP 5432. The database replies *from* 5432 *to* the client's ephemeral port, so the egress rule must match the **destination port of the reply**, which is the client's ephemeral port. Getting this backwards produces a connection that opens and then hangs, and it is the single most common NACL bug in production.

```
  Client 10.20.32.50:51222  ── TCP SYN → 10.20.64.10:5432 ──►  Database
       │                                                          │
       │  NACL ingress on data subnet must allow TCP 5432         │
       ◄── SYN/ACK from 10.20.64.10:5432 → 10.20.32.50:51222 ─────┘
              NACL EGRESS on data subnet must allow
              TCP 1024-65535 to 10.20.32.0/20  ◄── the rule everyone forgets

  Security-group equivalent: NOTHING. Stateful, so the response is free.
```

Ephemeral ranges worth knowing: Linux `32768–60999`; Windows Server 2008+ `49152–65535`; NLB and NAT gateway `1024–65535`; Lambda `1024–65535`. AWS documentation recommends allowing **`1024–65535`** to cover all clients.

**Rule numbering convention** — leave gaps so you can insert later:

| Range | Use |
| --- | --- |
| `1–99` | Emergency explicit denies (block a scanning source) |
| `100–199` | Intra-VPC allows |
| `200–299` | Ephemeral / return traffic |
| `300–399` | Specific external allows |
| `32766` | Catch-all deny **you** write, so it appears in audits |
| `*` (32767) | Implicit final deny, always present, always last |

### 6c. Associate it

There is no `disassociate-network-acl`. Every subnet must be associated with exactly one NACL, so associations are only ever **replaced**.

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

### 6d. Verify and lint

```bash
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries | sort_by(@, &RuleNumber)[].[RuleNumber,Egress,RuleAction,Protocol,CidrBlock,PortRange.From,PortRange.To]' \
  --output text | tee out/step06-acl.txt
```

`Protocol: 6` is TCP — the API returns IANA numbers even when you supplied `tcp`.

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
    ing = [e for e in a["Entries"] if not e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"] < 32767]
    egr = [e for e in a["Entries"] if e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"] < 32767]
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
                overlap = ipaddress.ip_network(peer).overlaps(ipaddress.ip_network(gc))
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

### 6e. Break it

```bash
# Break 1 — delete the ephemeral egress rule.
#   AWS: handshake goes out, reply is dropped, client HANGS. SGs untouched.
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 100
./bin/lint-nacl.sh   # should now warn

# Break 2 — a broad DENY at a LOW rule number defeats the allow above it.
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
  --rule-number 50 --protocol -1 --cidr-block 10.20.32.0/20 --rule-action deny
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries[?Egress==`false`] | sort_by(@,&RuleNumber)[].[RuleNumber,RuleAction,CidrBlock]' \
  --output text
```

Rule 50 matches first and evaluation **stops** — rule 100 is never reached. Contrast with security groups, where adding a rule can only ever *widen* access.

```bash
# Break 3 — exceed the rule budget. AWS: NetworkAclEntryLimitExceeded at 20 per direction.
for n in $(seq 200 10 480); do
  aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --ingress \
    --rule-number "$n" --protocol tcp --port-range From=443,To=443 \
    --cidr-block "198.51.100.$((n % 250))/32" --rule-action allow 2>&1 | head -1
done
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'length(NetworkAcls[0].Entries[?Egress==`false`])' --output text
```

Note how fast a 20-rule budget disappears. That is proof NACLs cannot carry fine-grained policy.

> 📓 **Divergence log entry #8.** Did your build enforce the 20-rule limit? If it accepted 29 ingress entries, log it — your local NACL will accept designs real AWS rejects.

### 6f. Fix it

```bash
# Restore the ephemeral egress rule
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block 10.20.32.0/20 --rule-action allow

# Remove the misordered deny
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --ingress --rule-number 50

# Remove the budget-probe rules
for n in $(seq 200 10 480); do
  aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --ingress --rule-number "$n" 2>/dev/null
done

./bin/lint-nacl.sh
aws ec2 describe-network-acls --network-acl-ids "$ACL_DATA" \
  --query 'NetworkAcls[0].Entries | sort_by(@,&RuleNumber)[].[RuleNumber,Egress,RuleAction,CidrBlock]' \
  --output text
```

### Security groups vs NACLs — the table to memorise

| Dimension | Security group | Network ACL |
| --- | --- | --- |
| Scope | ENI (interface) | Subnet |
| Statefulness | **Stateful** | **Stateless** |
| Rule types | ALLOW only | ALLOW and **DENY** |
| Evaluation | All rules unioned; order irrelevant | Ascending rule number; **first match wins** |
| Default (object *you* create) | no inbound, all outbound | deny all in and out |
| Default (created with VPC) | self-ref inbound, all outbound | allow all in and out |
| Return traffic | Automatic | Must be explicitly allowed (ephemeral ports) |
| Can reference other SGs | **Yes** | No — CIDR only |
| Traffic between two ENIs in the **same subnet** | **Yes**, applies | **No** — NACLs only see traffic crossing the subnet boundary |
| Quota | 60 in + 60 out per group, 5 groups per ENI | 20 rules per direction |

**Exam heuristics:** "block a specific IP" → NACL. "allow app tier to reach DB without hard-coding IPs" → SG referencing. A connection that **half-works or hangs** → stateless NACL missing its ephemeral return rule. Filtering between two instances in the same subnet → must be a security group.

### ✅ Checkpoint 6

`./bin/lint-nacl.sh` reports `no findings`, and `acl-data` has exactly three ingress and three egress entries plus the two implicit `*` rules.

---

## Step 7 — VPC endpoints: keep AWS API traffic off the internet

**Goal.** Add an S3 **gateway** endpoint to the private and data route tables, and an STS **interface** endpoint in the app subnets. Satisfies R2.

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
    never the IGW/NAT
```

| | Gateway endpoint | Interface endpoint |
| --- | --- | --- |
| Mechanism | A **route-table entry** whose destination is a *prefix list* | An **ENI with a private IP** in your subnets |
| Services | **S3 and DynamoDB only** | Most AWS services, partner services, your own NLB-backed services |
| Cost | **Free** | Hourly per ENI + per GB |
| Security control | Endpoint policy | Endpoint policy **+ security groups** |
| DNS | Uses the normal public name; routing does the work | Optional **private DNS** overrides the public name |

### 7a. The S3 gateway endpoint, with a restrictive policy

```bash
cat > policies/vpce-s3-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOnlyDnbBuckets",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"],
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

Confirm the prefix-list route appeared **automatically** — you did not call `create-route`:

```bash
for rtb in "$RTB_PRIVATE_1A" "$RTB_PRIVATE_1B" "$RTB_DATA"; do
  echo "--- $rtb ---"
  aws ec2 describe-route-tables --route-table-ids "$rtb" \
    --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,State]' \
    --output text
done
```

**Expected for `rtb-data`** — note the destination is a **prefix list**, not a CIDR:

```
10.20.0.0/16	None	local	active
None	pl-63a5400a	vpce-0abc123…	active
```

Adding or removing a route-table ID on the endpoint adds or removes that route automatically. **Do not hand-edit it.**

### 7b. The STS interface endpoint

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

aws ec2 describe-vpc-endpoints --vpc-endpoint-ids "$VPCE_STS" \
  --query 'VpcEndpoints[0].{Id:VpcEndpointId,Type:VpcEndpointType,State:State,
           PrivateDns:PrivateDnsEnabled,Subnets:SubnetIds,SGs:Groups[].GroupId,
           ENIs:NetworkInterfaceIds,DnsNames:DnsEntries[].DnsName}' --output json \
  | tee out/step07-vpce-sts.json
```

The presence of `sts.us-east-1.amazonaws.com` in `DnsEntries` is what private DNS means: **existing SDK code needs no change** to start using the endpoint.

| Parameter | Note |
| --- | --- |
| `--subnet-ids` | One ENI per subnet. Choose one per AZ for resilience. These ENIs will block subnet deletion. |
| `--security-group-ids` | **Must allow inbound 443 from clients** or the endpoint times out silently. |
| `--private-dns-enabled` | Requires both `enableDnsSupport` **and** `enableDnsHostnames` — which you set in Step 1. |

### 7c. Reason about what changed

Fill this table in your report. It is the point of the whole step.

| Caller | Target | Before endpoints | After endpoints |
| --- | --- | --- | --- |
| app-1a instance | `dnb-statements-dev` (S3) | app subnet → `0.0.0.0/0` → NAT-1a → IGW → public S3. **Billed NAT data processing.** | prefix-list route → `vpce-s3`. No NAT, no IGW, **free** |
| data-1a instance | `dnb-statements-dev` (S3) | **impossible** — `rtb-data` has no default route | prefix-list route → `vpce-s3`. Works, and only for our two buckets |
| app-1a instance | `sts.<region>.amazonaws.com` | NAT → IGW → public STS | private DNS → endpoint ENI in the same subnet |
| data-1a instance | `sts.<region>.amazonaws.com` | impossible | **still impossible** — we did not put an STS endpoint in the data subnets |

That last row is a **design decision, not an oversight**. State it as such in your report.

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
echo "=== route tables carrying a prefix-list (gateway endpoint) route ==="
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].{Table:Tags[?Key==`Name`]|[0].Value,
           PrefixRoutes:Routes[?DestinationPrefixListId!=null].[DestinationPrefixListId,GatewayId]}' \
  --output json
echo
echo "=== data tier reachability (should be local + prefix list ONLY) ==="
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Tier,Values=data" \
  --query 'RouteTables[].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,State]' \
  --output text
SH
chmod +x bin/endpoint-report.sh
./bin/endpoint-report.sh | tee out/step07-endpoints.txt
```

### 7d. Break it — the highest-frustration failure in PrivateLink

```bash
# Break 1 — an endpoint SG with no ingress. AWS: endpoint reaches `available`,
#   DNS resolves, and every API call TIMES OUT. Nothing tells you why.
SG_BROKEN=$(aws ec2 create-security-group \
  --group-name dnb-dev-sg-vpce-broken --description "Probe: endpoint SG with no ingress" \
  --vpc-id "$VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=dnb-dev-sg-vpce-broken},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'GroupId' --output text)
setid SG_BROKEN "$SG_BROKEN"

aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_STS" \
  --add-security-group-ids "$SG_BROKEN" --remove-security-group-ids "$SG_VPCE" 2>&1 | head -3

aws ec2 describe-vpc-endpoints --vpc-endpoint-ids "$VPCE_STS" \
  --query 'VpcEndpoints[0].[State,Groups[].GroupId]' --output text
```

`State: available`. **`available` does not mean reachable.** You will prove this at L2 in Step 10.

```bash
# Break 2 — remove a route table from the gateway endpoint.
#   The prefix-list route vanishes and the data tier loses S3 entirely — no error anywhere.
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" --remove-route-table-ids "$RTB_DATA" 2>&1 | head -3
aws ec2 describe-route-tables --route-table-ids "$RTB_DATA" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId]' --output text
```

### 7e. Fix it

```bash
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_STS" \
  --add-security-group-ids "$SG_VPCE" --remove-security-group-ids "$SG_BROKEN" 2>&1 | head -2
aws ec2 delete-security-group --group-id "$SG_BROKEN" 2>&1 | head -2
unsetid SG_BROKEN

aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3" --add-route-table-ids "$RTB_DATA" 2>&1 | head -2
./bin/endpoint-report.sh | tail -12
```

> **Remember for the exam and for real life:** an `AccessDenied` on S3 can originate in **eight** places — identity policy, permissions boundary, SCP, bucket policy, bucket ACL, **VPC endpoint policy**, KMS key policy, and Block Public Access. Most engineers check two of them.

### ✅ Checkpoint 7

`./bin/endpoint-report.sh` shows two endpoints in `available` state, and `rtb-data` shows exactly two routes: `local` and a prefix-list route.

---
---

# PART 2 — Put compute inside the network

You have built a network. Now you will configure EC2 into it — which is where abstractions become concrete, and where `AvailableIpAddressCount` starts to move.

> **A note on what "configuring EC2" means here.** Floci does not host real machine images — no operating system boots, and no packet leaves any container. Everything in Part 2 is therefore **L1 (existence)**: you are validating *ENI placement, security-group binding, address accounting and instance attributes*, not compute. That is still the majority of what goes wrong with EC2 in a VPC, and it is exactly the part an emulator can teach you.

## Step 8 — Launch and configure an EC2 instance in the app tier

**Goal.** Create a key pair, find an AMI, launch a properly configured private instance, and understand every parameter you pass.

### 8a. Confirm your build supports the EC2 calls

```bash
grep -E 'run-instances|network-interface|key-pair|describe-images' out/support-matrix.tsv
```

If `run-instances` shows `UNSUPPORTED`, skip to Step 8f and treat the rest of Part 2 as a modelling exercise — write the commands into `out/model-ec2.md` with a note saying why they could not be run.

### 8b. Key pair and AMI

```bash
guard || return 1

aws ec2 create-key-pair --key-name dnb-dev-key \
  --tag-specifications 'ResourceType=key-pair,Tags=[{Key=Name,Value=dnb-dev-key},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]' \
  --query 'KeyMaterial' --output text > out/dnb-dev-key.pem 2>/dev/null \
  && chmod 400 out/dnb-dev-key.pem && echo "key pair created" \
  || echo "note: create-key-pair unsupported, or the key already exists"

AMI_ID=$(aws ec2 describe-images --query 'Images[0].ImageId' --output text 2>/dev/null)
if [ -z "$AMI_ID" ] || [ "$AMI_ID" = "None" ]; then AMI_ID="ami-12345678"; fi
setid AMI_ID "$AMI_ID"
echo "using AMI $AMI_ID"
```

> **We create the key pair to complete the pattern, and then we will never use it.** R6 says no administrative port may be reachable from the internet. The correct answer in modern AWS is **SSM Session Manager**, which needs interface endpoints for `ssm`, `ssmmessages` and `ec2messages`, an instance profile with `AmazonSSMManagedInstanceCore`, and **no inbound security-group rule of any kind**. Every session is logged to CloudTrail. Challenge 2 builds it.

### 8c. Write the bootstrap script

```bash
cat > out/userdata.sh <<'UD'
#!/bin/bash
# DNB statement worker bootstrap (illustrative; nothing boots in Floci)
set -euo pipefail
dnf install -y postgresql16 awscli-2 || true
mkdir -p /etc/dnb
cat >/etc/dnb/worker.env <<CONF
DB_HOST=dnb-statements.cluster-xxxx.us-east-1.rds.amazonaws.com
DB_PORT=5432
S3_BUCKET=dnb-statements-dev
AWS_STS_REGIONAL_ENDPOINTS=regional
CONF
systemctl enable --now dnb-statement-worker
UD
echo "user-data written"
```

> 🔒 **Never put credentials or connection strings with secrets in user-data.** User data is readable from the instance metadata service by *any* process on the host, and by anything that can reach `169.254.169.254`. Use Secrets Manager through an interface endpoint plus an instance profile. Notice that the file above contains a hostname and a bucket name — configuration, not secrets. That distinction is the whole point.

### 8d. Launch the app instance

```bash
INST_APP=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t3.micro \
  --subnet-id "$SUBNET_APP_1A" \
  --security-group-ids "$SG_APP" \
  --private-ip-address 10.20.32.10 \
  --key-name dnb-dev-key \
  --user-data file://out/userdata.sh \
  --metadata-options 'HttpTokens=required,HttpPutResponseHopLimit=1,HttpEndpoint=enabled' \
  --tag-specifications 'ResourceType=instance,Tags=[
      {Key=Name,Value=dnb-dev-app-1},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=app}]' \
  --query 'Instances[0].InstanceId' --output text)
setid INST_APP "$INST_APP"
```

**Every parameter, and why:**

| Parameter | Meaning | Why this value |
| --- | --- | --- |
| `--image-id` | The AMI | Fictional in Floci; in AWS, pin by SSM parameter, never by hard-coded ID |
| `--instance-type t3.micro` | Hardware profile | Also caps how many ENIs and secondary IPs the instance may have |
| `--subnet-id` | Placement — and therefore **AZ, route table and NACL** | `app-1a` is private with NAT egress |
| `--security-group-ids` | SGs for the **primary ENI** | Use IDs, not names, in a non-default VPC |
| `--private-ip-address 10.20.32.10` | Pin the primary IP | Must be free and inside the subnet; the five reserved addresses are rejected |
| `--key-name` | SSH public key installed by cloud-init | Included for completeness; we open no SSH port |
| `--user-data file://…` | Bootstrap script, base64-encoded by the CLI | Readable via IMDS — **no secrets** |
| `--metadata-options HttpTokens=required` | **Forces IMDSv2** | The mitigation for the SSRF → credential-theft attack chain |
| `HttpPutResponseHopLimit=1` | Metadata responses die after one hop | Stops a container on the host from reaching the host's credentials |

Notice what you did **not** pass: `--associate-public-ip-address`. The app subnet has `MapPublicIpOnLaunch=false`, so this instance gets no public IP. That is R1 and R6 working together.

### 8e. Inspect it

```bash
aws ec2 describe-instances --instance-ids "$INST_APP" \
  --query 'Reservations[0].Instances[0].{Id:InstanceId,State:State.Name,Subnet:SubnetId,
           AZ:Placement.AvailabilityZone,Priv:PrivateIpAddress,Pub:PublicIpAddress,
           SGs:SecurityGroups[].GroupName,Imds:MetadataOptions.HttpTokens,
           ENIs:NetworkInterfaces[].{Eni:NetworkInterfaceId,Idx:Attachment.DeviceIndex,
                                     Ip:PrivateIpAddress,DoT:Attachment.DeleteOnTermination}}' \
  --output json | tee out/step08-instance.json
```

**You should see:**

```json
{
  "Id": "i-0123456789abcdef0",
  "State": "running",
  "Subnet": "subnet-0app1a00000000000",
  "AZ": "us-east-1a",
  "Priv": "10.20.32.10",
  "Pub": null,
  "SGs": ["dnb-dev-sg-app"],
  "Imds": "required",
  "ENIs": [
    { "Eni": "eni-0aaa000000000000a", "Idx": 0, "Ip": "10.20.32.10", "DoT": true }
  ]
}
```

Three things to read carefully:

- **`Pub: null`** — correct. `MapPublicIpOnLaunch` is false on app subnets.
- **`Imds: required`** — IMDSv2 enforced.
- **`DoT: true` on device index 0** — the primary ENI dies with the instance. Secondary ENIs do not, which is Step 9's leak.

### 8f. The four conditions for internet reachability

Students usually satisfy two of these and are puzzled. Write them in your notes:

```
  1. An internet gateway attached to the VPC
  2. A route  0.0.0.0/0 → igw-…  in the route table associated with
     the instance's subnet
  3. A public IPv4 address or EIP on the instance's ENI
  4. Security group + NACL rules permitting the flow in both directions
```

Your app instance satisfies **none** of 1–3 for inbound (its route table points at a NAT, and it has no public IP). It satisfies outbound through the NAT because condition 2 is met by `0.0.0.0/0 → nat-1a`. That asymmetry — outbound yes, inbound impossible — is precisely the security property a private tier needs.

### ✅ Checkpoint 8

```bash
aws ec2 describe-instances --instance-ids "$INST_APP" \
  --query 'Reservations[0].Instances[0].[State.Name,PrivateIpAddress,PublicIpAddress,MetadataOptions.HttpTokens]' \
  --output text
```

Expect `running  10.20.32.10  None  required`.

---

## Step 9 — Secondary ENIs, Elastic IPs, and subnet exhaustion

**Goal.** Understand that the **ENI**, not the instance, is the real atom of VPC networking — then watch a subnet run out of addresses.

### 9a. Attach a second ENI

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

**The ENI is a virtual network card** with a MAC address, one primary plus optional secondary private IPv4s, optional public IPv4/EIP, optional IPv6, a source/destination check flag, and **1–5 security groups**. Instances, RDS databases, ELB nodes, interface endpoints, NAT gateways, VPC-attached Lambdas and ECS `awsvpc` tasks are *all* just things that own ENIs.

Understanding this collapses several mysteries at once:

- *"Why can't I delete my subnet?"* → an RDS instance's ENI is in it.
- *"Why does my security group say it is in use?"* → an ENI references it.
- *"Why do SGs attach to instances?"* → they don't. They attach to **ENIs**. A multi-homed instance can have different SGs per interface.

An ENI cannot move between subnets or AZs. Device index 0 is created and destroyed with the instance; index > 0 survives termination unless `DeleteOnTermination` is set.

### 9b. Launch a public instance and give it an Elastic IP

```bash
INST_WEB=$(aws ec2 run-instances \
  --image-id "$AMI_ID" --instance-type t3.micro \
  --subnet-id "$SUBNET_PUBLIC_1A" --security-group-ids "$SG_WEB" \
  --private-ip-address 10.20.0.10 \
  --metadata-options 'HttpTokens=required,HttpPutResponseHopLimit=1' \
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

**Three different things students merge into one:**

| | Private IPv4 | Auto-assigned public IPv4 | Elastic IP |
| --- | --- | --- | --- |
| Source | Subnet CIDR | AWS pool | AWS pool, allocated to **your account** |
| Persistence | Life of the ENI | **Lost on stop/start** and on termination | Until you `ReleaseAddress` |
| Visible inside the OS | Yes | **No** (IGW does 1:1 NAT) | **No** |
| Charged | No | Yes, hourly (all public IPv4 since Feb 2024) | Yes, hourly — **including while unassociated** |
| Remappable | No | No | **Yes** — the basis of blue/green failover |

### 9c. Address accounting — predict before you look

```bash
python3 - <<'PY'
total, reserved = 4096, 5
used = {
    "i-app-1 primary ENI (eth0)": 1,
    "secondary management ENI (eth1)": 1,
    "vpce-sts interface endpoint ENI": 1,
}
print(f"/20 total          {total}")
print(f"aws reserved       -{reserved}")
for k, v in used.items():
    print(f"{k:45} -{v}")
print(f"EXPECTED Free      {total - reserved - sum(used.values())}")
PY

aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'sort_by(Subnets,&CidrBlock)[].{Name:Tags[?Key==`Name`]|[0].Value,
           CIDR:CidrBlock,Free:AvailableIpAddressCount}' --output table
```

Expected `Free = 4088` for `dnb-dev-subnet-app-1a`. If your number differs, reconcile it:

```bash
aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Subnet:SubnetId,
           Ip:PrivateIpAddress,Status:Status,Desc:Description,
           SGs:Groups[].GroupName}' --output table | tee out/step09-enis.txt
```

> **`Description` is your friend.** AWS-managed ENIs are self-describing — read the description before deleting an ENI you did not create. `AvailableIpAddressCount` = total − 5 − ENIs. Any discrepancy is either an unaccounted ENI or an unimplemented reservation rule.

> 📓 **Divergence log entry #9.** Record whether `AvailableIpAddressCount` decreased by exactly the number of ENIs you created.

### 9d. Is there a data plane at all?

This is the moment to answer the question the support matrix cannot.

```bash
cat > bin/probe-dataplane.sh <<'SH'
#!/usr/bin/env bash
# Establish whether this Floci build has any VPC data plane.
set -uo pipefail

echo "=== 1. Instances and their reported addresses ==="
aws ec2 describe-instances --filters Name=tag:Project,Values=CoreBanking \
  --query 'Reservations[].Instances[].{Id:InstanceId,Subnet:SubnetId,Priv:PrivateIpAddress,State:State.Name}' \
  --output table

echo
echo "=== 2. Does each private IP fall inside its subnet's CIDR? ==="
python3 - <<'PY'
import ipaddress, json, subprocess
def aws(*a):
    return json.loads(subprocess.run(["aws","ec2",*a,"--output","json"],
                                     capture_output=True, text=True).stdout or "{}")
subs = {s["SubnetId"]: s["CidrBlock"] for s in aws("describe-subnets").get("Subnets",[])}
bad = ok = 0
for r in aws("describe-instances").get("Reservations",[]):
    for i in r.get("Instances",[]):
        sid, ip = i.get("SubnetId"), i.get("PrivateIpAddress")
        if not sid or not ip or sid not in subs:
            continue
        if ipaddress.ip_address(ip) in ipaddress.ip_network(subs[sid]):
            ok += 1;  print(f"  OK       {i['InstanceId']} {ip} in {subs[sid]}")
        else:
            bad += 1; print(f"  DIVERGES {i['InstanceId']} {ip} NOT in {subs[sid]}")
print(f"\n  in-CIDR={ok}  out-of-CIDR={bad}")
if bad:
    print("  FINDING: the emulator does not allocate from the subnet CIDR ->")
    print("           it has no IP address manager, therefore no data plane.")
PY

echo
echo "=== 3. Filtering evidence — answer these in out/divergence-log.md ==="
cat <<'TXT'
  - Did any Describe call report an ENI attached to the instance?
  - Does the emulator expose a container network you could exec into?
  - Did any command ever return RequestTimeout / connection refused as a
    CONSEQUENCE OF A SECURITY GROUP, rather than of the API being down?

If the answer to the last question is "no", then for this build:
    Route tables    = metadata only
    Security groups = metadata only
    Network ACLs    = metadata only
and every Track-B verdict in this lab MUST come from bin/reach.py,
never from observation.
TXT
SH
chmod +x bin/probe-dataplane.sh
./bin/probe-dataplane.sh | tee out/step09-dataplane.txt
```

> 📓 **Divergence log entry #10 — the most important one in the lab.** Whatever this probe tells you determines how you must phrase every conclusion for the rest of the module.

### 9e. Break it — exhaust a subnet

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
# expect:  10.20.200.0/28   11
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

**Real AWS stops at 11** with:

```
InsufficientFreeAddressesInSubnet: The specified subnet does not have enough
free addresses to satisfy the request.
```

If your build reaches 14, it has no address manager. Log it — and remember that a `/28` in real AWS holds **11** ENIs, not 16.

> **This is the number-one production capacity incident in EKS clusters.** Each pod in `awsvpc` / VPC-CNI mode consumes a subnet IP, and the CNI *pre-allocates* a warm pool on top. A `/24` per subnet feels generous until 200 pods per node try to schedule. **Size for pods, not for nodes.**

```bash
# Break 2 — pin a reserved address. AWS: rejected; 10.20.32.1 is the VPC router.
aws ec2 create-network-interface --subnet-id "$SUBNET_APP_1A" --groups "$SG_APP" \
  --private-ip-address 10.20.32.1 --description "probe: reserved address" 2>&1 | head -3

# Break 3 — attach a sixth security group. AWS: rejected at 6 (quota is 5 per ENI).
extra=""
for n in 1 2; do
  id=$(aws ec2 create-security-group --group-name "dnb-dev-sg-filler-$n" \
        --description "probe filler $n" --vpc-id "$VPC_ID" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=dnb-dev-sg-filler-$n},{Key=ManagedBy,Value=floci-lab},{Key=Project,Value=CoreBanking}]" \
        --query 'GroupId' --output text)
  extra="$extra $id"
done
setid SG_FILLERS "$(echo "$extra" | tr -s ' ')"

echo "-- 5 groups (should succeed) --"
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups $SG_APP $SG_WEB $SG_DB $SG_VPCE $SG_DEFAULT 2>&1 | head -2
echo "-- 7 groups (should fail) --"
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups $SG_APP $SG_WEB $SG_DB $SG_VPCE $SG_DEFAULT $extra 2>&1 | head -3

# Break 4 — delete a subnet that still contains ENIs. AWS: DependencyViolation.
aws ec2 delete-subnet --subnet-id "$SUBNET_PROBE" 2>&1 | head -3
```

Now **diagnose** Break 4 properly — this is the skill that matters, because the error never names the dependency:

```bash
aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET_PROBE" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Desc:Description,Status:Status,Attached:Attachment.InstanceId}' \
  --output table
```

### 9f. Fix it

```bash
# Restore the correct SG set and delete the fillers
aws ec2 modify-network-interface-attribute --network-interface-id "$ENI_SECOND" \
  --groups "$SG_APP" 2>&1 | head -2
for id in $SG_FILLERS; do aws ec2 delete-security-group --group-id "$id" 2>&1 | head -1; done
unsetid SG_FILLERS

# Drain and delete the probe subnet, in dependency order
while read -r eni; do
  [ -z "$eni" ] && continue
  aws ec2 delete-network-interface --network-interface-id "$eni" 2>&1 | head -1
done < <(aws ec2 describe-network-interfaces --filters "Name=subnet-id,Values=$SUBNET_PROBE" \
           --query 'NetworkInterfaces[].NetworkInterfaceId' --output text | tr '\t' '\n')

aws ec2 delete-subnet --subnet-id "$SUBNET_PROBE" 2>&1 | head -2
unsetid SUBNET_PROBE

./bin/routing-report.sh
./bin/verify-subnets.sh
```

> **`while read … done < <(…)` again.** Process substitution keeps the loop in the current shell so variables survive. A pipe would run it in a subshell. Same trap as Step 2.

### ✅ Checkpoint 9

Two instances `running`, `dnb-dev-subnet-app-1a` reports `Free: 4088`, `./bin/verify-subnets.sh` still passes, and `out/step09-dataplane.txt` exists with your data-plane verdict recorded.

---
---

# PART 3 — Verify what you built

You now have thirty-odd objects. Verification means three different things, and confusing them is the most common failure in student reports:

| Level | Question | Tool | Here? |
| --- | --- | --- | --- |
| **L1 Existence** | Does the object exist as intended? | `describe-*` | ✅ |
| **L2 Intent** | Does the configuration *as a whole* express my policy? | `bin/reach.py` + assertions | ✅ |
| **L3 Observation** | Do packets actually behave that way? | Reachability Analyzer, flow logs | ❌ AWS only |

Always state which level your evidence is. *"Verified at L2 by `reach.py`"* is precise and honest. *"Verified"* is not.

## Step 10 — Build your own Reachability Analyzer

**Goal.** Because the emulator will not route packets for you, you are going to write the router yourself. `reach.py` reads your **actual** configuration out of Floci and applies **AWS's real evaluation algorithm**.

### 10a. The algorithm you are implementing

```
                       ┌──────────────────────────────────────────┐
  packet leaves        │ 1. Source security group EGRESS rules    │  stateful
  source ENI  ───────► │    (allow-only; implicit deny)           │  (return traffic
                       └──────────────────┬───────────────────────┘   auto-permitted)
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 2. Source subnet NACL EGRESS rules       │  stateless
                       │    (numbered, first match wins, then *)  │
                       └──────────────────┬───────────────────────┘
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 3. Source subnet ROUTE TABLE             │  longest-prefix
                       │    longest-prefix match -> target        │  match
                       └──────────────────┬───────────────────────┘
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 4. Destination subnet NACL INGRESS       │  stateless
                       └──────────────────┬───────────────────────┘
                                          ▼
                       ┌──────────────────────────────────────────┐
                       │ 5. Destination security group INGRESS    │  stateful
                       └──────────────────┬───────────────────────┘
                                          ▼
                                   DELIVERED
        and then, for the RETURN packet, steps 4 and 2 must be satisfied
        AGAIN by the NACLs on the EPHEMERAL port range, because NACLs are
        stateless. This asymmetry is the #1 source of
        "my security group is right but it still hangs".
```

### 10b. Write it

```bash
cat > bin/reach.py <<'PY'
#!/usr/bin/env python3
"""reach.py — evaluate whether AWS would permit a flow, using the live Floci config.

Usage:
  reach.py --from-subnet subnet-aaa --from-ip 10.20.32.50 \
           --to-subnet subnet-bbb --to-ip 10.20.64.10 \
           --port 5432 --proto tcp --src-sg sg-app --dst-sg sg-db

Exit status: 0 if the flow AND its return traffic would be permitted, 1 otherwise.
This is a TEACHING model of AWS's evaluation order. See LIMITATIONS in the docs.
"""
import argparse
import ipaddress
import json
import subprocess
import sys

EPHEMERAL = (1024, 65535)   # range AWS docs recommend allowing in NACLs


def aws(*args):
    proc = subprocess.run(["aws", "ec2", *args, "--output", "json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(2)
    return json.loads(proc.stdout or "{}")


# ------------------------------------------------------------- config loading
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


# ------------------------------------------------------------- evaluation
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
    perms = group["IpPermissions"] if direction == "ingress" \
        else group.get("IpPermissionsEgress", [])
    for perm in perms:
        if not port_in(perm, port, proto):
            continue
        for r in perm.get("IpRanges", []):
            if peer_ip and ipaddress.ip_address(peer_ip) in ipaddress.ip_network(r["CidrIp"]):
                return True, (f"{direction} rule {perm.get('IpProtocol')}:"
                              f"{perm.get('FromPort')} cidr {r['CidrIp']}")
        for pair in perm.get("UserIdGroupPairs", []):
            if pair.get("GroupId") in peer_group_ids:
                return True, (f"{direction} rule {perm.get('IpProtocol')}:"
                              f"{perm.get('FromPort')} sg {pair['GroupId']}")
    return False, f"no matching {direction} rule -> IMPLICIT DENY"


def nacl_decision(acl, direction, peer_ip, port, proto):
    """NACLs are numbered, stateless, first-match-wins. Returns (allow, reason)."""
    egress = (direction == "egress")
    entries = sorted((e for e in acl["Entries"] if e["Egress"] == egress),
                     key=lambda e: e["RuleNumber"])
    for e in entries:
        cidr = e.get("CidrBlock")
        if not cidr:
            continue                       # ignore IPv6-only entries in this model
        if ipaddress.ip_address(peer_ip) not in ipaddress.ip_network(cidr):
            continue
        p = str(e["Protocol"])
        if p != "-1":
            want = {"tcp": "6", "udp": "17", "icmp": "1"}.get(proto.lower(), proto)
            if p != want:
                continue
            pr = e.get("PortRange")
            if pr and not (pr["From"] <= port <= pr["To"]):
                continue
        return e["RuleAction"] == "allow", \
            f"rule {e['RuleNumber']} {e['RuleAction']} {cidr} proto={p}"
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
    for k in ("GatewayId", "NatGatewayId", "TransitGatewayId",
              "VpcPeeringConnectionId", "NetworkInterfaceId", "InstanceId",
              "EgressOnlyInternetGatewayId"):
        if route.get(k):
            return f"{k}={route[k]}"
    return "unknown target"


# ------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-subnet", required=True)
    ap.add_argument("--to-ip", required=True)
    ap.add_argument("--to-subnet", help="omit for destinations outside the VPC")
    ap.add_argument("--from-ip", help="source private IP; defaults to first host in subnet")
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
        step(6, f"dst NACL egress (return, eph {EPHEMERAL[0]}-{EPHEMERAL[1]})", ok, why)

        ok, why = nacl_decision(src_acl, "ingress", a.to_ip, EPHEMERAL[0], a.proto)
        step(7, f"src NACL ingress (return, eph {EPHEMERAL[0]}-{EPHEMERAL[1]})", ok, why)

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
PY

chmod +x bin/reach.py
python3 -m py_compile bin/reach.py && echo "reach.py compiles"
```

> **LIMITATIONS you must state in your report.** This models IPv4 TCP/UDP/ICMP unicast flows. It deliberately does **not** model: route propagation from a VGW or TGW; managed prefix lists as route destinations; VPC endpoint policies; Gateway Load Balancer insertion; Network Firewall; `local`-route precedence subtleties for secondary CIDRs; IPv6; Windows ephemeral ranges (`49152–65535`); and — importantly — the fact that a **NAT gateway rewrites the source address**, so the destination actually sees the NAT's IP, not the instance's. Extending it to model the NAT rewrite is **Challenge 4**.

### 10c. Run it on the happy path

```bash
python3 bin/reach.py \
  --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A"  --to-ip 10.20.64.10 \
  --port 5432 --proto tcp \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tee out/step10-app-to-db.txt
```

**You should see:**

```
FLOW  10.20.32.50 (subnet-0app…/sg-0app…)  ->  10.20.64.10:5432/tcp (subnet-0dat…/sg-0db0…)

  1. ALLOW  src SG egress (sg-0app…)                     egress rule tcp:5432 sg sg-0db0…
  2. ALLOW  src NACL egress (acl-0default…)              rule 100 allow 0.0.0.0/0 proto=-1
  3. ALLOW  route table rtb-0priv1a… [explicit]          10.20.0.0/16 -> GatewayId=local
  4. ALLOW  dst NACL ingress (acl-0abc123…)              rule 100 allow 10.20.32.0/20 proto=6
  5. ALLOW  dst SG ingress (sg-0db0…)                    ingress rule tcp:5432 sg sg-0app…
  6. ALLOW  dst NACL egress (return, eph 1024-65535)     rule 100 allow 10.20.32.0/20 proto=6
  7. ALLOW  src NACL ingress (return, eph 1024-65535)    rule 100 allow 0.0.0.0/0 proto=-1

AWS VERDICT: PERMITTED
```

**Read step 3 carefully.** The route chosen is `10.20.0.0/16 → local`, *not* the `0.0.0.0/0 → nat` route, because `local` is more specific. That is **longest-prefix match** doing its job, and it is why intra-VPC traffic never touches the NAT gateway.

### 10d. Now prove the design is actually restrictive

Every one of these must be **BLOCKED**:

```bash
echo "=== negative tests ==="

# a) web tier straight to the database, skipping the app tier
python3 bin/reach.py --from-subnet "$SUBNET_PUBLIC_1A" --from-ip 10.20.0.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 5432 \
  --src-sg "$SG_WEB" --dst-sg "$SG_DB" | tail -4

# b) app tier to the database on the wrong port
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 22 \
  --src-sg "$SG_APP" --dst-sg "$SG_DB" | tail -4

# c) database initiating outbound to the internet (exfiltration)  [R5]
python3 bin/reach.py --from-subnet "$SUBNET_DATA_1A" --from-ip 10.20.64.10 \
  --to-ip 203.0.113.9 --port 443 --src-sg "$SG_DB" | tail -6

# d) the broken endpoint SG from Step 7d, re-created as a thought experiment
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_APP_1A" --to-ip 10.20.32.200 --port 443 \
  --src-sg "$SG_APP" --dst-sg "$SG_VPCE" | tail -4
```

Test **(c)** is the one to study. It should fail at **two independent steps** — `sg-db` has no egress rule *and* `rtb-data` has no route to `203.0.113.9`. Defence in depth means either failure alone would suffice.

Test **(d)** should be PERMITTED with the correct `sg-vpce`. Swap in a group with no ingress and step 5 flips to `no matching ingress rule -> IMPLICIT DENY` — which is exactly why an interface endpoint can be `available` and completely unusable.

### ✅ Checkpoint 10

`python3 -m py_compile bin/reach.py` succeeds, the app→db flow returns `PERMITTED`, and all three negative tests return `BLOCKED`.

---

## Step 11 — The reachability matrix, drift detection and the security audit

**Goal.** Turn ad-hoc `reach.py` calls into a repeatable regression suite, then audit the whole build.

### 11a. Write down the intent FIRST

Design before verification. Verification without stated intent is just description.

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

> **Why `public → internet 443` is expected BLOCKED.** You revoked allow-all egress from `sg-web` in Step 5 and allowed only 8080 to `sg-app` and 443 to `sg-vpce`. A load balancer does not need to originate arbitrary internet connections. If you *want* it permitted, that is a deliberate change to `sg-web` — not an oversight to be patched at test time.

### 11b. The matrix runner

```bash
cat > bin/reach-matrix.sh <<'SH'
#!/usr/bin/env bash
# Run reach.py for every row of out/intended-matrix.tsv and diff against intent.
set -uo pipefail
: "${VPC_ID:?load the ledger first}"

subnet_of() { case "$1" in
  public) echo "$SUBNET_PUBLIC_1A" ;; app) echo "$SUBNET_APP_1A" ;;
  data)   echo "$SUBNET_DATA_1A"   ;; *) echo "" ;; esac; }
sg_of() { case "$1" in
  public) echo "$SG_WEB" ;; app) echo "$SG_APP" ;; data) echo "$SG_DB" ;; *) echo "" ;; esac; }
ip_of() { case "$1" in
  public) echo "10.20.0.50" ;; app) echo "10.20.32.50" ;;
  data)   echo "10.20.64.10" ;; internet) echo "203.0.113.9" ;; *) echo "" ;; esac; }

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
  out=$(python3 "$HOME/vpc-lab/bin/reach.py" "${args[@]}" 2>&1) || true
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
./bin/reach-matrix.sh | tee out/step11-matrix.txt
```

**You should see:**

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

Any `FAIL` writes the full seven-step trace to `out/reach-fail-*.txt`, telling you **which step** disagreed with your intent. That file is what you attach to a lab report — not a screenshot.

### 11c. Watch the matrix catch a real regression

```bash
# Someone "temporarily" opens the database to the whole app subnet by CIDR
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.0.0/16","Description":"temporary debugging - REMOVE"}]}]' >/dev/null

./bin/reach-matrix.sh || echo "^ the matrix caught the regression"
tail -6 out/reach-fail-public-data-5432.txt 2>/dev/null
```

`public → data 5432` flips from `BLOCKED` to `PERMITTED`. A CIDR rule that "just allows the app tier" also allows the **public** tier, because `10.20.0.0/16` contains it. **This is exactly the failure mode security-group referencing prevents.**

```bash
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":5432,"ToPort":5432,
    "IpRanges":[{"CidrIp":"10.20.0.0/16"}]}]' >/dev/null
rm -f out/reach-fail-*.txt
./bin/reach-matrix.sh | tail -3
```

### 11d. Emit a machine-readable topology, for drift detection

```bash
cat > bin/emit-topology.sh <<'SH'
#!/usr/bin/env bash
set -uo pipefail
: "${VPC_ID:?}"
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
          if k in ("VpcId","CidrBlock","State","CidrBlockAssociationSet")},
  "subnets": [{"Name": nm(s), "SubnetId": s["SubnetId"], "Cidr": s["CidrBlock"],
               "Az": s["AvailabilityZone"], "Free": s["AvailableIpAddressCount"],
               "MapPublicIp": s["MapPublicIpOnLaunch"],
               "Tier": next((t["Value"] for t in s.get("Tags",[]) if t["Key"]=="Tier"), None)}
              for s in sorted(aws("describe-subnets",*f)["Subnets"], key=lambda x: x["CidrBlock"])],
  "routeTables": [{"Name": nm(t), "RouteTableId": t["RouteTableId"],
                   "Main": any(a.get("Main") for a in t.get("Associations",[])),
                   "Subnets": sorted(a["SubnetId"] for a in t.get("Associations",[]) if a.get("SubnetId")),
                   "Routes": [{k: r[k] for k in r
                               if k in ("DestinationCidrBlock","DestinationPrefixListId",
                                        "GatewayId","NatGatewayId","State")}
                              for r in t.get("Routes",[])]}
                  for t in aws("describe-route-tables",*f)["RouteTables"]],
  "securityGroups": [{"Name": g["GroupName"], "GroupId": g["GroupId"],
                      "Ingress": g["IpPermissions"], "Egress": g.get("IpPermissionsEgress",[])}
                     for g in sorted(aws("describe-security-groups",*f)["SecurityGroups"],
                                     key=lambda x: x["GroupName"])],
  "networkAcls": [{"Name": nm(a), "NetworkAclId": a["NetworkAclId"],
                   "IsDefault": a["IsDefault"],
                   "Subnets": sorted(x["SubnetId"] for x in a.get("Associations",[])),
                   "Entries": a["Entries"]}
                  for a in aws("describe-network-acls",*f)["NetworkAcls"]],
  "natGateways": [{"Name": nm(n), "NatGatewayId": n["NatGatewayId"], "State": n["State"],
                   "SubnetId": n.get("SubnetId")}
                  for n in aws("describe-nat-gateways").get("NatGateways",[])
                  if n.get("VpcId") == vpc],
  "endpoints": [{"Name": nm(e), "VpcEndpointId": e["VpcEndpointId"],
                 "Type": e["VpcEndpointType"], "Service": e["ServiceName"],
                 "State": e["State"], "RouteTables": sorted(e.get("RouteTableIds",[])),
                 "Subnets": sorted(e.get("SubnetIds",[]))}
                for e in aws("describe-vpc-endpoints",*f)["VpcEndpoints"]],
  "instances": [{"Name": nm(i), "InstanceId": i["InstanceId"], "State": i["State"]["Name"],
                 "Subnet": i.get("SubnetId"), "PrivateIp": i.get("PrivateIpAddress"),
                 "PublicIp": i.get("PublicIpAddress"),
                 "Sgs": sorted(g["GroupName"] for g in i.get("SecurityGroups",[]))}
                for r in aws("describe-instances",*f).get("Reservations",[])
                for i in r.get("Instances",[]) if i["State"]["Name"] != "terminated"],
}
json.dump(doc, sys.stdout, indent=2, default=str)
PY
echo "wrote out/topology.json ($(wc -c < "$HOME/vpc-lab/out/topology.json") bytes)"
SH
chmod +x bin/emit-topology.sh
./bin/emit-topology.sh
cp out/topology.json out/topology.baseline.json
```

Now you have drift detection for free:

```bash
# make an unauthorised change
aws ec2 authorize-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"oops"}]}]' >/dev/null

./bin/emit-topology.sh
diff <(python3 -m json.tool out/topology.baseline.json) \
     <(python3 -m json.tool out/topology.json) | head -20 || echo "no drift"

# revert
aws ec2 revoke-security-group-ingress --group-id "$SG_DB" \
  --ip-permissions '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
./bin/emit-topology.sh
```

### 11e. The security audit

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

# 1. sensitive ports open to the world
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

# 2. main route table must be minimal
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
        add("CRITICAL", f"data subnet {nm(s)} has an internet path  [violates R1]")
    if s["SubnetId"] not in expl:
        add("MEDIUM", f"subnet {nm(s)} has no explicit route table association")
    if s["MapPublicIpOnLaunch"] and tier not in ("public", None):
        add("HIGH", f"non-public subnet {nm(s)} auto-assigns public IPs")

# 4. tagging discipline  [R7]
REQUIRED = {"Project","Environment","Owner","CostCenter","ManagedBy"}
for kind, items, key in (("subnet", subs, "SubnetId"), ("route-table", rts, "RouteTableId")):
    for o in items:
        missing = REQUIRED - {t["Key"] for t in o.get("Tags",[])}
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
        add("MEDIUM", "default security group still has rules — lock it down")

# 7. NACL statelessness hazards
for a in aws("describe-network-acls",*F)["NetworkAcls"]:
    if a["IsDefault"]:
        continue
    eg  = [e for e in a["Entries"] if e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"]<32767]
    ing = [e for e in a["Entries"] if not e["Egress"] and e["RuleAction"]=="allow" and e["RuleNumber"]<32767]
    if ing and not eg:
        add("HIGH", f"NACL {nm(a,a['NetworkAclId'])} allows ingress but has no egress allows: "
                    "all return traffic will be dropped")

# 8. IMDSv1 still permitted
#    Only flag when the build actually reports MetadataOptions; an emulator that
#    omits the field entirely is a divergence, not an insecure instance.
for r in aws("describe-instances",*F).get("Reservations",[]):
    for i in r.get("Instances",[]):
        if i["State"]["Name"] == "terminated":
            continue
        mo = i.get("MetadataOptions")
        if mo is None:
            add("LOW", f"instance {i['InstanceId']}: build does not report MetadataOptions "
                       "-> cannot verify IMDSv2 locally (log this as a divergence)")
        elif mo.get("HttpTokens") != "required":
            add("HIGH", f"instance {i['InstanceId']} allows IMDSv1 (HttpTokens != required)")

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

You will likely see one `MEDIUM` about the **default security group**. Fix it now — this is the "fail loudly" principle:

```bash
aws ec2 revoke-security-group-ingress --group-id "$SG_DEFAULT" \
  --ip-permissions "[{\"IpProtocol\":\"-1\",\"UserIdGroupPairs\":[{\"GroupId\":\"$SG_DEFAULT\"}]}]" 2>&1 | head -2
aws ec2 revoke-security-group-egress --group-id "$SG_DEFAULT" \
  --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' 2>&1 | head -2

aws ec2 describe-security-groups --group-ids "$SG_DEFAULT" \
  --query 'SecurityGroups[0].{In:IpPermissions,Out:IpPermissionsEgress}' --output json
```

Both lists empty. Anything accidentally launched without an explicit security group is now **fully isolated** — a forgotten `--security-group-ids` produces an immediate, obvious connectivity failure instead of a working-but-overexposed resource nobody notices for a year.

### 11f. One command to rule them all

```bash
cat > bin/verify-all.sh <<'SH'
#!/usr/bin/env bash
# Full topology verification. Run before submitting any lab report.
set -uo pipefail
cd "$HOME/vpc-lab"
: "${VPC_ID:?load the ledger first: . bin/ids.sh && loadids}"
fail=0
for s in assert-main-rtb-minimal assert-nat-az-affinity assert-sg-invariants \
         lint-nacl verify-subnets reach-matrix security-audit; do
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
./bin/verify-all.sh | tee out/verify-all.txt
```

### 11g. Answer the auditor

Carol, DNB's internal auditor, asks: *"Prove to me that a compromised database host cannot exfiltrate customer data to the internet."*

A weak answer describes the security group. A strong answer enumerates every independent control **and names the residual risks you have not closed**.

```bash
cat > out/audit-response-R5.md <<'MD'
# Audit response: R5 — the data tier cannot initiate outbound connections

## Claim
A process with full control of a host in `dnb-dev-subnet-data-1a` cannot open a
TCP connection to an arbitrary internet address.

## Independent controls, in AWS evaluation order

| # | Control | Configuration | Evidence file |
|---|---------|---------------|---------------|
| 1 | Security group egress | `dnb-dev-sg-db` has `IpPermissionsEgress: []` | out/step05-sg.txt |
| 2 | Network ACL egress | `dnb-dev-acl-data` egress rule 32766 deny 0.0.0.0/0, then implicit `*` deny | out/step06-acl.txt |
| 3 | Routing | `dnb-dev-rtb-data` has no `0.0.0.0/0` route; only `local` + S3 prefix list | out/step04-routing.txt |
| 4 | Endpoint policy | `dnb-dev-vpce-s3` permits only the two DNB buckets | policies/vpce-s3-policy.json |
| 5 | No public address | data subnets have MapPublicIpOnLaunch=false; no EIP on any data ENI | out/step02-subnets.txt |

Any ONE of controls 1, 2 or 3 is sufficient. All three are present, so this is
defence in depth rather than a single point of failure.

## Verification method (L2, computed — not observed)
    bin/reach.py --from-subnet <data-1a> --to-ip 203.0.113.9 --port 443 --src-sg <sg-db>
returns `AWS VERDICT: BLOCKED`, failing independently at steps 1, 2 and 3.
Reproduced as matrix row `data internet 443 BLOCKED` in out/step11-matrix.txt.

## Residual risk — stated honestly
1. The S3 gateway endpoint is a LEGITIMATE egress channel. A compromised host
   could write customer data to `dnb-statements-dev`, a bucket it is already
   authorised to use. Mitigation belongs to S3 and KMS, not to VPC: object
   ownership, bucket policies with aws:SourceVpce, CloudTrail data events.
2. DNS exfiltration via the Amazon resolver at 10.20.0.2 is NOT blocked by any
   of the five controls: resolver queries do not traverse the route table and
   are not captured by flow logs. Mitigation: Route 53 Resolver DNS Firewall.
3. Controls 1-4 are verified from CONFIGURATION, not from observed packet drops,
   because this emulator has no data plane (see out/step09-dataplane.txt).
   On real AWS the same claim must be re-verified with VPC Reachability
   Analyzer and with flow-log evidence.
MD
echo "audit response written"
```

> **Point 2 is what separates a good answer from an excellent one.** Naming the residual risk you have *not* closed — and saying which service closes it — is what a senior engineer does. Both listed risks are real and commonly missed.

### ✅ Checkpoint 11

`./bin/verify-all.sh` ends with `ALL CHECKS PASSED`.

---
---

# PART 4 — Diagnose it when it breaks

Before you tear down, learn the diagnostic ladder. When someone says *"it can't connect"*, ask these six questions **in this order** — routing before firewalls, because a misrouted packet never reaches a firewall.

```bash
cat > bin/diagnose.sh <<'SH'
#!/usr/bin/env bash
# diagnose.sh <source-subnet-id> <destination-ip>
set -uo pipefail
SRC_SUBNET="${1:?usage: diagnose.sh <src-subnet-id> <dst-ip>}"
DST_IP="${2:?usage: diagnose.sh <src-subnet-id> <dst-ip>}"
VPC=$(aws ec2 describe-subnets --subnet-ids "$SRC_SUBNET" --query 'Subnets[0].VpcId' --output text)

echo "### Q1. Is the source subnet associated with the route table I think it is?"
assoc=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query "RouteTables[?Associations[?SubnetId=='$SRC_SUBNET']].RouteTableId" --output text)
if [ -z "$assoc" ] || [ "$assoc" = "None" ]; then
  echo "  FINDING: no explicit association -> this subnet uses the VPC MAIN table."
  assoc=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
    "Name=association.main,Values=true" --query 'RouteTables[0].RouteTableId' --output text)
fi
echo "  route table in effect: $assoc"

echo; echo "### Q2. Is there a route matching the destination, and is it alive?"
aws ec2 describe-route-tables --route-table-ids "$assoc" \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,DestinationPrefixListId,GatewayId,NatGatewayId,State]' \
  --output text
echo "  (longest-prefix match wins; State=blackhole means the target was deleted)"

echo; echo "### Q3. Any blackhole routes anywhere in this VPC?"
bh=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" \
  --query 'RouteTables[].Routes[?State==`blackhole`].DestinationCidrBlock' --output text)
{ [ -n "$bh" ] && [ "$bh" != "None" ] && echo "  FINDING: blackholes: $bh"; } || echo "  none"

echo; echo "### Q4. Which NACL applies to the source subnet, and what does it say?"
acl=$(aws ec2 describe-network-acls --filters "Name=association.subnet-id,Values=$SRC_SUBNET" \
  --query 'NetworkAcls[0].NetworkAclId' --output text)
echo "  NACL: $acl"
aws ec2 describe-network-acls --network-acl-ids "$acl" \
  --query 'NetworkAcls[0].Entries | sort_by(@,&RuleNumber)[].[RuleNumber,Egress,RuleAction,Protocol,CidrBlock,PortRange.From,PortRange.To]' \
  --output text
echo "  (STATELESS: check BOTH directions, and 1024-65535 on the return path)"

echo; echo "### Q5. Security groups — rules present in the INITIATING direction?"
echo "  aws ec2 describe-security-group-rules --filters Name=group-id,Values=<sg>"
echo "  (STATEFUL: return traffic is automatic; only the initiating direction needs a rule)"

echo; echo "### Q6. Does the destination ENI exist and is it healthy?"
aws ec2 describe-network-interfaces --filters "Name=addresses.private-ip-address,Values=$DST_IP" \
  --query 'NetworkInterfaces[].{Eni:NetworkInterfaceId,Subnet:SubnetId,Status:Status,Sgs:Groups[].GroupName}' \
  --output json

echo; echo "### Now compute the AWS verdict:"
echo "  python3 bin/reach.py --from-subnet $SRC_SUBNET --to-ip $DST_IP --port <port> \\"
echo "      --src-sg <sg> [--to-subnet <subnet> --dst-sg <sg>]"
SH
chmod +x bin/diagnose.sh
./bin/diagnose.sh "$SUBNET_APP_1A" 10.20.64.10 | head -40
```

### Symptom → cause, the table to keep on your desk

| Symptom | Most likely cause | First command |
| --- | --- | --- |
| Connection **refused** immediately | The service is not listening. **Not a network problem.** | Check the application |
| Connection **hangs / times out** | A firewall is dropping (not rejecting) — SG or NACL | `reach.py`, then check the NACL ephemeral rule |
| Works one way, hangs the other | **Stateless NACL** missing the ephemeral return rule | `bin/lint-nacl.sh` |
| Worked yesterday, nothing changed | **Blackhole route** — someone deleted a NAT gateway or peering | `describe-route-tables … State==blackhole` |
| Some instances work, others do not | Different route tables, or one subnet implicitly on the main table | `bin/routing-report.sh` |
| Works in AZ-a, fails in AZ-b | Cross-AZ NAT, or a missing per-AZ endpoint ENI | `bin/assert-nat-az-affinity.sh` |
| No internet despite `0.0.0.0/0 → igw` | The instance has **no public IP** — condition 3 of the four | `describe-instances … PublicIpAddress` |
| AWS SDK calls hang from a private subnet | Interface endpoint SG blocks 443 | `describe-vpc-endpoints`, then the SG |
| `AccessDenied` on S3 **only** from a private subnet | **Endpoint policy** | `describe-vpc-endpoints --query '…PolicyDocument'` |
| RDS endpoint will not resolve | `enableDnsSupport`/`enableDnsHostnames` false | `describe-vpc-attribute` |
| New pods/tasks stop scheduling | Subnet IP exhaustion | `AvailableIpAddressCount` |
| Cannot delete anything | `DependencyViolation` — always an ENI or an association | `describe-network-interfaces` |
| Surprise bill | NAT data processing, unassociated EIPs, cross-AZ transfer | Add gateway endpoints; sweep EIPs |

### Error code → cause reference

| Error | Cause | Fix |
| --- | --- | --- |
| `InvalidVpc.Range` | Prefix outside `/16`–`/28` | Choose a valid prefix; the primary cannot be resized later |
| `InvalidSubnet.Conflict` | CIDR overlaps an existing subnet | Pick a free block |
| `InsufficientFreeAddressesInSubnet` | Subnet exhausted (remember −5) | Delete stale ENIs, or add a larger subnet / secondary CIDR |
| `Resource.AlreadyAssociated` | The VPC already has an IGW | One IGW per VPC |
| `DependencyViolation` (subnet) | An ENI still lives in it | `describe-network-interfaces --filters Name=subnet-id,…` |
| `DependencyViolation` (SG) | An ENI uses it, or another SG references it | Revoke referencing rules first |
| `DependencyViolation` (route table) | Explicit associations remain, or it is the main table | Disassociate; main tables are undeletable |
| `CannotDelete` | It is the default security group | You cannot; lock it down instead |
| `RouteAlreadyExists` | A route for that exact destination exists | Use `replace-route` |
| `NetworkAclEntryLimitExceeded` | 20 rules per direction reached | Consolidate, or request an increase (max 40) |
| `RulesPerSecurityGroupLimitExceeded` | 60 rules reached (a 10-CIDR rule counts as 10) | Use prefix lists sized tightly |
| `SecurityGroupsPerInterfaceLimitExceeded` | More than 5 SGs on one ENI | Consolidate rules |
| `AddressLimitExceeded` | 5 EIPs per Region reached | Release orphans |
| `Gateway.NotAttached` (NAT `FailureCode`) | NAT's subnet has no IGW route | Put the NAT in a **public** subnet |
| `InvalidParameterCombination` (endpoint) | `Gateway` type with `--subnet-ids`, or `Interface` with `--route-table-ids` | Gateway takes route tables; Interface takes subnets + SGs |
| `AccessDenied` mentioning `vpce-` | The **endpoint policy** denies it | Check it alongside IAM and the bucket policy |

---
---

# PART 5 — Tear it down

> ⚠️ **Deletion order matters.** Every step exists because the one after it would otherwise fail with `DependencyViolation`. In real AWS the two steps that stop the bill are **deleting NAT gateways** and **releasing Elastic IPs** — do those first if you are in a hurry.

```
  1. Terminate instances                ENIs at device index 0 die with them
  2. Delete secondary / detached ENIs   device index >0 survive termination
  3. Delete VPC endpoints               interface endpoints own ENIs in subnets
  4. Delete NAT gateways                own ENIs; their routes become blackholes
  5. Release Elastic IPs                NOT released by NAT/instance deletion — BILLED
  6. Detach + delete the internet gateway
  7. Restore NACL associations, delete custom NACLs   (no disassociate exists)
  8. Revoke ALL SG rules, then delete groups          (cross-refs block deletion)
  9. Disassociate + delete route tables               (main table is undeletable)
 10. Delete subnets                     fail while ANY ENI remains
 11. Delete key pairs
 12. Delete the VPC
 13. Sweep by tag                       catch anything from the challenges
```

```bash
cat > bin/cleanup.sh <<'SH'
#!/usr/bin/env bash
# Delete every resource created by this lab, in dependency order.
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
  if [ -n "$EPS" ] && [ "$EPS" != "None" ]; then
    try aws ec2 delete-vpc-endpoints --vpc-endpoint-ids $EPS
  else
    echo "  none in $vpc"
  fi
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
  { [ "$assoc" != "None" ] && [ -n "$assoc" ] && try aws ec2 disassociate-address --association-id "$assoc"; } || true
  try aws ec2 release-address --allocation-id "$alloc"
done < <(aws ec2 describe-addresses --filters "Name=tag:ManagedBy,Values=floci-lab" \
           --query 'Addresses[].[AllocationId,AssociationId]' --output text 2>/dev/null)
echo "  -- any EIP still listed below is a LIVE CHARGE --"
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' --output text 2>/dev/null

step "6. detach and delete internet gateways"
for vpc in $VPCS; do
  while read -r igw; do
    [ -z "$igw" ] && continue
    try aws ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc"
    try aws ec2 delete-internet-gateway --internet-gateway-id "$igw"
  done < <(aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$vpc" \
             --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null | tr '\t' '\n')
done

step "7. restore default NACL associations, then delete custom NACLs"
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

step "8. revoke ALL security group rules, then delete non-default groups"
for vpc in $VPCS; do
  while read -r sg; do
    [ -z "$sg" ] && continue
    ing=$(aws ec2 describe-security-groups --group-ids "$sg" \
            --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null)
    egr=$(aws ec2 describe-security-groups --group-ids "$sg" \
            --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null)
    { [ "$ing" != "[]" ] && [ -n "$ing" ] && \
      aws ec2 revoke-security-group-ingress --group-id "$sg" --ip-permissions "$ing" >/dev/null 2>&1; } || true
    { [ "$egr" != "[]" ] && [ -n "$egr" ] && \
      aws ec2 revoke-security-group-egress --group-id "$sg" --ip-permissions "$egr" >/dev/null 2>&1; } || true
    echo "  stripped rules from $sg"
  done < <(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" \
             --query 'SecurityGroups[].GroupId' --output text 2>/dev/null | tr '\t' '\n')
  while read -r sg; do
    [ -z "$sg" ] && continue
    try aws ec2 delete-security-group --group-id "$sg"
  done < <(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$vpc" \
             --query 'SecurityGroups[?GroupName!=`default`].GroupId' --output text 2>/dev/null | tr '\t' '\n')
done

step "9. disassociate and delete non-main route tables"
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

step "10. delete subnets"
for vpc in $VPCS; do
  while read -r sn; do
    [ -z "$sn" ] && continue
    try aws ec2 delete-subnet --subnet-id "$sn"
  done < <(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" \
             --query 'Subnets[].SubnetId' --output text 2>/dev/null | tr '\t' '\n')
done

step "11. delete key pairs"
try aws ec2 delete-key-pair --key-name dnb-dev-key
rm -f "$HOME/vpc-lab/out/dnb-dev-key.pem"

step "12. delete VPCs"
for vpc in $VPCS; do
  try aws ec2 delete-vpc --vpc-id "$vpc"
done

step "13. final sweep — anything still tagged Project=CoreBanking"
for verb in describe-vpcs describe-subnets describe-route-tables describe-security-groups \
            describe-network-acls describe-internet-gateways describe-nat-gateways \
            describe-network-interfaces describe-vpc-endpoints describe-addresses \
            describe-instances; do
  n=$(aws ec2 "$verb" --filters "Name=tag:Project,Values=CoreBanking" --output json 2>/dev/null \
        | python3 -c '
import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0); raise SystemExit
k = next((x for x in d if isinstance(d[x], list)), None)
print(len(d[k]) if k else 0)')
  printf '  %-34s remaining: %s\n' "$verb" "${n:-?}"
done

step "done"
echo "If any count above is non-zero, RE-RUN this script: asynchronous NAT and"
echo "endpoint teardown often means a single pass leaves work behind."
SH
chmod +x bin/cleanup.sh
bash -n bin/cleanup.sh && echo "syntax OK"
```

**Run it twice.** The second pass catches whatever the first pass could not delete while asynchronous teardown was still in flight.

```bash
./bin/cleanup.sh 2>&1 | tee out/cleanup-run1.txt
echo "=================== SECOND PASS ==================="
./bin/cleanup.sh 2>&1 | tee out/cleanup-run2.txt
```

### Verify the environment is clean

```bash
echo "--- VPCs remaining (a default VPC may legitimately exist) ---"
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,IsDefault,Tags[?Key==`Name`]|[0].Value]' --output table

echo "--- Elastic IPs (MUST be empty — these are billed) ---"
aws ec2 describe-addresses --query 'Addresses[].[AllocationId,PublicIp,AssociationId]' --output table

echo "--- NAT gateways (MUST be empty or deleted — these are billed) ---"
aws ec2 describe-nat-gateways --query 'NatGateways[?State!=`deleted`].[NatGatewayId,State]' --output table
```

### Archive your submission

```bash
tar czf ~/vpc-lab-submission.tar.gz -C ~ vpc-lab/out vpc-lab/bin vpc-lab/policies
ls -la ~/vpc-lab-submission.tar.gz

# Optional: stop the emulator
# floci stop
```

> ⚠️ **In a real AWS account, verify the bill — not just the API.** `describe-addresses` returning empty is necessary but not sufficient. Check Cost Explorer for the `EC2-Other` usage type the day after teardown. NAT gateway hours, `PublicIPv4:InUseAddress` and endpoint hours are the three lines that keep accruing when a teardown is incomplete.

### ✅ Checkpoint 12

Zero NAT gateways, zero Elastic IPs, and the sweep in step 13 reports `0` for every resource type.

---
---

# PART 6 — Graded challenges

> 🛑 **Do these BEFORE running Part 5's cleanup.** Every challenge assumes the Steps 1–11 topology is live. If you have already torn down, re-run Steps 1–9 (about 20 minutes with your ledger and scripts).

**Rules for all challenges.**

- Work without step-by-step guidance. The solutions are collapsed — open them only after you have written down your own answer.
- Every resource you create must carry `Project=CoreBanking`, `ManagedBy=floci-lab` and a `Name` starting `dnb-`, so `bin/cleanup.sh` finds it.
- For any challenge that concerns traffic, submit the `reach.py` verdict **with its seven-step trace**, and state whether your evidence is L1, L2 or L3.
- Re-run `./bin/verify-all.sh` after each challenge. It must still pass.

| # | Challenge | Type | Difficulty | Marks |
| --- | --- | --- | --- | --- |
| 1 | Extend to a third availability zone | Build | ⭐ | 15 |
| 2 | A bastion-free administrative path | Build + written | ⭐⭐ | 20 |
| 3 | Diagnose three broken topologies | Break-fix | ⭐⭐ | 20 |
| 4 | Teach `reach.py` about NAT source rewriting | Code | ⭐⭐⭐ | 20 |
| 5 | Design review: 50 000 pods and network change control | Written / design | ⭐⭐⭐⭐ | 25 |

---

## Challenge 1 — Extend the topology to a third availability zone ⭐

**Marks: 15**

Your build currently spans two AZs. The board's resilience policy has been upgraded: production must tolerate the loss of an AZ *while still running at capacity*, which means three AZs.

**Your task.** Extend the topology into a third AZ using **only** the blocks reserved in `out/ipam-record.md` (`10.20.96.0/20` and `10.20.112.0/20`):

1. One public, one app and one data subnet in AZ-3.
2. A third NAT gateway with its own Elastic IP.
3. A third private route table with correct AZ affinity.
4. Correct associations for all three new subnets — public onto the shared public table, app onto the new private table, data onto the shared data table.
5. The new app subnet must also get the S3 gateway endpoint route and an STS interface-endpoint ENI.

**Constraint:** you must fit *both* the public and app tiers of AZ-3 inside `10.20.96.0/20`, and the data tier inside `10.20.112.0/20`. Do the subnetting arithmetic before you type anything.

**Acceptance criteria.**

- `./bin/routing-report.sh` shows **nine** subnets, every one marked `explicit`.
- `./bin/assert-nat-az-affinity.sh` exits 0.
- `./bin/verify-all.sh` still passes (you will need to relax the "six subnets" assertion in `bin/verify-subnets.sh` — do that deliberately and say why).
- Your report shows the CIDR arithmetic: for each new subnet, the network address, broadcast address and usable count.

<details>
<summary><strong>💡 Hint 1</strong> — how do I split a /20 into two tiers?</summary>

`10.20.96.0/20` covers `10.20.96.0`–`10.20.111.255`. Splitting it into two `/21`s gives you `10.20.96.0/21` (2 043 usable) and `10.20.104.0/21` (2 043 usable). Ask yourself which tier deserves the bigger half — remember from Step 4 that public subnets should hold only load balancers and NAT gateways, so they can be small. Consider `/22` for public and `/21` (or a bigger split) for app.

Verify any candidate with `cidrinfo 10.20.96.0/22`, and check for overlap with `./bin/assert-no-cidr-overlap.sh` if you wrote it, or by inspection.
</details>

<details>
<summary><strong>💡 Hint 2</strong> — which route table does each new subnet join?</summary>

Three different answers, and getting them wrong is the whole point of the exercise:

- **public-1c** → the *existing shared* `rtb-public`. There is nothing AZ-specific about a route to an internet gateway.
- **app-1c** → a *brand-new* `rtb-private-1c` pointing at `nat-1c`. This is AZ-specific, which is why it cannot share.
- **data-1c** → the *existing shared* `rtb-data`. Its only routes are `local` and the S3 prefix list, both AZ-agnostic.

If you find yourself creating a third public route table, stop and ask what would be different about it.
</details>

<details>
<summary><strong>✅ Model solution</strong></summary>

```bash
# --- arithmetic first ---
cidrinfo 10.20.96.0/22    # public-1c : 10.20.96.0  - 10.20.99.255,  1019 usable
cidrinfo 10.20.100.0/22   # app-1c    : 10.20.100.0 - 10.20.103.255, 1019 usable
cidrinfo 10.20.112.0/22   # data-1c   : 10.20.112.0 - 10.20.115.255, 1019 usable
# 10.20.104.0/21 and 10.20.116.0/22 remain reserved inside the AZ-3 blocks.

AZ_C=$(aws ec2 describe-availability-zones --query 'AvailabilityZones[2].ZoneName' --output text)
setid AZ_C "$AZ_C"

mk_subnet() {  # mk_subnet <key> <name> <cidr> <az> <tier> <public:yes|no>
  local id
  id=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$3" --availability-zone "$4" \
    --tag-specifications "ResourceType=subnet,Tags=[
        {Key=Name,Value=$2},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev},
        {Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},
        {Key=ManagedBy,Value=floci-lab},{Key=Tier,Value=$5}]" \
    --query 'Subnet.SubnetId' --output text)
  if [ "$6" = "yes" ]; then
    aws ec2 modify-subnet-attribute --subnet-id "$id" --map-public-ip-on-launch
  else
    aws ec2 modify-subnet-attribute --subnet-id "$id" --no-map-public-ip-on-launch
  fi
  setid "$1" "$id"
}

mk_subnet SUBNET_PUBLIC_1C dnb-dev-subnet-public-1c 10.20.96.0/22  "$AZ_C" public yes
mk_subnet SUBNET_APP_1C    dnb-dev-subnet-app-1c    10.20.100.0/22 "$AZ_C" app    no
mk_subnet SUBNET_DATA_1C   dnb-dev-subnet-data-1c   10.20.112.0/22 "$AZ_C" data   no

# --- NAT gateway for AZ-3 ---
EIP_1C=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=dnb-dev-eip-nat-1c},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev},{Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'AllocationId' --output text)
setid EIP_1C "$EIP_1C"

NAT_1C=$(aws ec2 create-nat-gateway --subnet-id "$SUBNET_PUBLIC_1C" --allocation-id "$EIP_1C" \
  --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=dnb-dev-nat-1c},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev},{Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1C "$NAT_1C"
aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_1C" 2>/dev/null || true

# --- routing: ONE new table, TWO reuses ---
# make_private_rtb is the shell function from Step 4c. If you have opened a new
# terminal since then, re-paste it (or better: move it into bin/ids.sh).
make_private_rtb RTB_PRIVATE_1C dnb-dev-rtb-private-1c "$NAT_1C" "$SUBNET_APP_1C"
aws ec2 associate-route-table --route-table-id "$RTB_PUBLIC" --subnet-id "$SUBNET_PUBLIC_1C" >/dev/null
aws ec2 associate-route-table --route-table-id "$RTB_DATA"   --subnet-id "$SUBNET_DATA_1C"   >/dev/null

# --- endpoints must learn about AZ-3 too ---
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_S3"  --add-route-table-ids "$RTB_PRIVATE_1C"
aws ec2 modify-vpc-endpoint --vpc-endpoint-id "$VPCE_STS" --add-subnet-ids "$SUBNET_APP_1C"

# --- verify ---
./bin/routing-report.sh
./bin/assert-nat-az-affinity.sh
```

Then relax the subnet-count assertion, deliberately:

```bash
sed -i 's/check "six subnets exist" "\$n" "6"/check "nine subnets exist" "$n" "9"/' bin/verify-subnets.sh
sed -i 's/check "spread over two AZs" "\$azs" "2"/check "spread over three AZs" "$azs" "3"/' bin/verify-subnets.sh
sed -i 's/check "exactly two subnets auto-assign public IPs" "\$pub" "2"/check "exactly three subnets auto-assign public IPs" "$pub" "3"/' bin/verify-subnets.sh
sed -i "s/check \"tier '\$t' spans two AZs\" \"\$c\" \"2\"/check \"tier '\$t' spans three AZs\" \"\$c\" \"3\"/" bin/verify-subnets.sh
sed -i 's/reserved-5 rule applied (\/20 -> 4091)" "\$free" "4091"/reserved-5 rule applied" "$free" "4091"/' bin/verify-subnets.sh
./bin/verify-all.sh | tail -5
```

**The two mistakes this challenge is designed to catch:**

1. Creating a third *public* route table. There is nothing AZ-specific about `0.0.0.0/0 → igw`, so the public table is shared. Only the NAT-pointing tables must be per-AZ.
2. Forgetting to add `rtb-private-1c` to the S3 endpoint and `subnet-app-1c` to the STS endpoint. AZ-3 would then silently route S3 traffic through its NAT gateway (costing money) and have no local STS ENI (adding cross-AZ latency and charges). The topology would look correct in `routing-report.sh` and be quietly wrong.
</details>

---

## Challenge 2 — A bastion-free administrative path ⭐⭐

**Marks: 20**

R6 says no administrative port may be reachable from the internet. Your build currently satisfies that by having no SSH rules at all — which also means nobody can administer the app instances. Fix it properly.

**Your task.**

1. Create interface endpoints for the four services SSM Session Manager requires — `ssm`, `ssmmessages`, `ec2messages`, and `kms` (for encrypted session logging) — in **both** app subnets, sharing `sg-vpce`.
2. Write `out/challenge2.md` documenting the *complete* list of what a private instance needs for Session Manager to work: the endpoints, the instance-profile policy, the agent, the route/DNS requirements, and — critically — **which inbound security-group rules are required**.
3. Argue, in no more than 300 words, why this is more secure than a bastion host with a `0.0.0.0/0` rule on port 22. Cover three dimensions: audit trail, credential handling, and attack surface.
4. Prove at L2 that an app instance can reach the endpoints and that nothing on the internet can reach the app instance on port 22.

**Acceptance criteria.**

- Four endpoints in `available` state, each with ENIs in both app subnets.
- `out/challenge2.md` correctly states that **zero** inbound security-group rules are needed on the instance.
- Two `reach.py` traces attached.
- `./bin/security-audit.sh` reports no new CRITICAL or HIGH findings.

<details>
<summary><strong>💡 Hint 1</strong> — why four endpoints, not one?</summary>

Session Manager is not a single API. `ssm` carries the control-plane calls (registration, document execution). `ssmmessages` carries the **session data channel** — the actual keystrokes and terminal output over a WebSocket. `ec2messages` carries the legacy Run Command channel that the agent still uses. `kms` is needed only if you enable session encryption, which you should.

Omit `ssmmessages` and the instance registers fine, appears "Online" in the console, and then every session attempt hangs. That is the classic misconfiguration.
</details>

<details>
<summary><strong>💡 Hint 2</strong> — what direction does the connection go?</summary>

This is the crux of the security argument. The SSM **agent on the instance** makes an *outbound* HTTPS connection to the endpoint ENI. Nothing ever connects *inbound* to the instance.

So: the instance's security group needs an **egress** rule to `sg-vpce` on 443 (you already have one from Step 5), the endpoint's security group needs an **ingress** rule on 443 from `sg-app` (also already there), and the instance needs **no ingress rules whatsoever**. There is no port to scan, no key to steal, and no listening service to exploit.
</details>

<details>
<summary><strong>✅ Model solution</strong></summary>

```bash
for svc in ssm ssmmessages ec2messages kms; do
  id=$(aws ec2 create-vpc-endpoint --vpc-id "$VPC_ID" --vpc-endpoint-type Interface \
    --service-name "com.amazonaws.${AWS_DEFAULT_REGION:-us-east-1}.$svc" \
    --subnet-ids "$SUBNET_APP_1A" "$SUBNET_APP_1B" \
    --security-group-ids "$SG_VPCE" --private-dns-enabled \
    --tag-specifications "ResourceType=vpc-endpoint,Tags=[
        {Key=Name,Value=dnb-dev-vpce-$svc},{Key=Project,Value=CoreBanking},
        {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
        {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]" \
    --query 'VpcEndpoint.VpcEndpointId' --output text 2>&1 | head -1)
  echo "$svc -> $id"
  case "$id" in vpce-*) setid "VPCE_$(echo "$svc" | tr 'a-z.' 'A-Z_')" "$id" ;; esac
done

./bin/endpoint-report.sh | head -20

# L2 proof 1: app instance CAN reach an endpoint ENI on 443
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.10 \
  --to-subnet "$SUBNET_APP_1A" --to-ip 10.20.32.200 --port 443 \
  --src-sg "$SG_APP" --dst-sg "$SG_VPCE" | tee out/challenge2-reach-endpoint.txt

# L2 proof 2: nothing from outside can reach the app instance on 22
python3 bin/reach.py --from-subnet "$SUBNET_PUBLIC_1A" --from-ip 10.20.0.50 \
  --to-subnet "$SUBNET_APP_1A" --to-ip 10.20.32.10 --port 22 \
  --src-sg "$SG_WEB" --dst-sg "$SG_APP" | tee out/challenge2-reach-ssh.txt
```

`out/challenge2.md` should contain:

```markdown
# Session Manager requirements for a private instance — complete list

## Network
1. Interface endpoints, one ENI per AZ, for: ssm, ssmmessages, ec2messages, kms
2. Endpoint security group (sg-vpce) allows inbound TCP 443 from sg-app
3. Instance security group (sg-app) allows outbound TCP 443 to sg-vpce
4. INBOUND RULES REQUIRED ON THE INSTANCE: **NONE**
5. VPC attributes enableDnsSupport AND enableDnsHostnames both true,
   so --private-dns-enabled resolves the public service names to the ENIs
6. No internet gateway, NAT gateway or public IP required at all

## Identity
7. An instance profile whose role has the AWS-managed policy
   AmazonSSMManagedInstanceCore
8. For encrypted sessions and S3/CloudWatch session logging, kms:Decrypt and
   kms:GenerateDataKey on the session key, plus write access to the log target

## Host
9. amazon-ssm-agent installed and running (pre-installed on Amazon Linux 2023,
   recent Ubuntu LTS and Windows Server AMIs)
10. IMDSv2 reachable so the agent can obtain role credentials
    (our instances set HttpTokens=required, HttpPutResponseHopLimit=1)

## Why this beats a bastion with 0.0.0.0/0 on 22

**Audit trail.** Every Session Manager session is an API call recorded in
CloudTrail with the IAM principal, and the full terminal stream can be
streamed to S3 or CloudWatch Logs. An SSH session through a bastion produces
one TCP connection in a flow log and whatever the host's own auditd happens
to capture; the identity is a key, not a principal.

**Credential handling.** There is no long-lived private key to distribute,
rotate, revoke or leak. Access is granted and removed by editing an IAM
policy, takes effect immediately, and is centrally visible. A bastion's
authorized_keys file is a distributed secret with no expiry and no inventory.

**Attack surface.** The bastion is a permanently internet-reachable host
running a network service that must be patched, hardened and monitored, and
its security group is a standing 0.0.0.0/0 rule that every scanner on the
internet finds within minutes. With Session Manager there is no listening
port, no inbound rule, and no host to compromise as a stepping stone: the
connection is outbound-only from the instance to an ENI inside our own VPC.
The bastion also concentrates risk — compromising it yields lateral access
to everything it can reach, which is exactly the blast radius R6 exists to
prevent.
```

**Marking note.** The single most important sentence is item 4: *no inbound rules are required*. A student who writes "allow 22 from the bastion's security group" has not understood the model.
</details>

---

## Challenge 3 — Diagnose three broken topologies ⭐⭐

**Marks: 20**

Snapshot first so you can always recover:

```bash
./bin/emit-topology.sh
cp out/topology.json out/topology.pre-challenge3.json
```

Apply each break, then **write your diagnosis before opening the solution**. For each scenario submit: the symptom you would expect a user to report, the single command that localised the fault, the root cause in one sentence, and the fix.

Use only `describe-*`, `bin/diagnose.sh` and `bin/reach.py`. Do not look at the break commands again after running them.

### Scenario A

```bash
aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_1A"
sleep 5
```

*Reported symptom:* "`dnf update` on instances in app-1a times out. app-1b is fine. Nobody changed a security group."

### Scenario B

```bash
aws ec2 create-route --route-table-id "$RTB_MAIN" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID"
SUBNET_ORPHAN=$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block 10.20.144.0/24 \
  --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=dnb-dev-subnet-orphan},{Key=Project,Value=CoreBanking},{Key=ManagedBy,Value=floci-lab},{Key=Tier,Value=app}]' \
  --query 'Subnet.SubnetId' --output text)
setid SUBNET_ORPHAN "$SUBNET_ORPHAN"
```

*Reported symptom:* "Carol's audit script says a brand-new subnet intended for internal batch jobs has a route to the internet. Nobody associated it with the public route table."

### Scenario C

```bash
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 100
aws ec2 delete-network-acl-entry --network-acl-id "$ACL_DATA" --egress --rule-number 110
```

*Reported symptom:* "Alice says the statement worker's connection pool fills with connections that never become usable. `telnet 10.20.64.10 5432` appears to connect and then produces nothing. She has verified that `sg-db` allows 5432 from `sg-app`, and she is right."

<details>
<summary><strong>💡 Hint for A</strong></summary>

Compare the two private route tables. Look at the `State` field of the default route, not just the target. Then ask what else the deletion left behind that costs money.
</details>

<details>
<summary><strong>💡 Hint for B</strong></summary>

Which route table applies to a subnet that has no explicit association? Run `./bin/routing-report.sh` and read the `assoc` column.
</details>

<details>
<summary><strong>💡 Hint for C</strong></summary>

Which of the two VPC firewalls is stateless? Run `reach.py` for app→db and read **step 6**, not step 5.
</details>

<details>
<summary><strong>✅ Model solutions</strong></summary>

**Scenario A — blackhole route.**

*Diagnosis.* Deleting a NAT gateway does **not** delete routes that reference it. `0.0.0.0/0 → nat-1a` in `rtb-private-1a` is now `State: blackhole`, so matching packets are silently dropped — no error, no ICMP unreachable, just a hang. `app-1b` is unaffected because it has its own table and its own NAT gateway, which is precisely the resilience benefit of per-AZ tables. Secondary finding: `EIP_1A` is now unassociated and **still billed**.

*Localising command:*
```bash
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'RouteTables[].Routes[?State==`blackhole`].[DestinationCidrBlock,NatGatewayId]' --output text
```

*Fix:*
```bash
NAT_1A=$(aws ec2 create-nat-gateway --subnet-id "$SUBNET_PUBLIC_1A" --allocation-id "$EIP_1A" \
  --connectivity-type public \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=dnb-dev-nat-1a},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev},{Key=Owner,Value=platform-team},{Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab}]' \
  --query 'NatGateway.NatGatewayId' --output text)
setid NAT_1A "$NAT_1A"
aws ec2 wait nat-gateway-available --nat-gateway-ids "$NAT_1A" 2>/dev/null || true
aws ec2 replace-route --route-table-id "$RTB_PRIVATE_1A" \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id "$NAT_1A"
./bin/assert-nat-az-affinity.sh
```

*Lesson.* **Check for blackhole routes first** when something that worked stops working. A deleted route target leaves the route behind.

---

**Scenario B — implicit main-table association.**

*Diagnosis.* The new subnet has no explicit route-table association, so it **implicitly uses the VPC main route table** — and someone added `0.0.0.0/0 → igw` to that table. Every unassociated subnet in the VPC is therefore public. The subnet's tags say `Tier=app`; the routing says otherwise, and routing wins.

*Localising command:*
```bash
./bin/routing-report.sh          # look for MAIN! in the assoc column
./bin/assert-main-rtb-minimal.sh # fails with DRIFT
```

*Fix:*
```bash
aws ec2 delete-route --route-table-id "$RTB_MAIN" --destination-cidr-block 0.0.0.0/0
aws ec2 associate-route-table --route-table-id "$RTB_PRIVATE_1A" --subnet-id "$SUBNET_ORPHAN" >/dev/null
./bin/assert-main-rtb-minimal.sh
./bin/routing-report.sh
```

*Lesson.* Keep the main route table `local`-only and associate every subnet explicitly. With an empty main table, forgetting an association **fails closed** instead of open. That is a **preventive** control, not a corrective one — and it is why `bin/assert-main-rtb-minimal.sh` belongs in CI.

---

**Scenario C — stateless NACL missing the ephemeral return rule.**

*Diagnosis.* `acl-data` has ingress allows for 5432 but now has no egress allows at all, so egress falls through to rule 32766 `deny`. Because NACLs are **stateless**, the database's reply — sourced from port 5432, destined for the client's *ephemeral* port — is evaluated against the egress list and dropped. Alice is right that the security groups are correct: security groups are stateful and would have permitted the reply automatically.

*Localising command:*
```bash
./bin/lint-nacl.sh
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.50 \
  --to-subnet "$SUBNET_DATA_1A" --to-ip 10.20.64.10 --port 5432 \
  --src-sg "$SG_APP" --dst-sg "$SG_DB"
# steps 1-5 ALLOW, step 6 DENY -> AWS VERDICT: BLOCKED
```

*Fix:*
```bash
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 100 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block 10.20.32.0/20 --rule-action allow
aws ec2 create-network-acl-entry --network-acl-id "$ACL_DATA" --egress \
  --rule-number 110 --protocol tcp --port-range From=1024,To=65535 \
  --cidr-block 10.20.48.0/20 --rule-action allow
./bin/lint-nacl.sh
```

*Lesson.* A connection that **half-works or hangs**, with security groups that are demonstrably correct, is a stateless NACL missing its ephemeral return rule — almost every time. In real AWS this appears in flow logs as an inbound `ACCEPT` with a matching outbound `REJECT` on the same five-tuple reversed. That single diagnostic pattern is the main reason flow logs are worth enabling.
</details>

**Restore afterwards:**

```bash
aws ec2 delete-subnet --subnet-id "$SUBNET_ORPHAN" 2>&1 | head -2
unsetid SUBNET_ORPHAN
./bin/verify-all.sh | tail -5
./bin/emit-topology.sh
diff <(python3 -m json.tool out/topology.pre-challenge3.json) \
     <(python3 -m json.tool out/topology.json) > out/challenge3-drift.txt 2>&1 \
  && echo "topology fully restored" \
  || { echo "residual differences (expect only NAT/EIP IDs):"; head -20 out/challenge3-drift.txt; }
```

---

## Challenge 4 — Teach `reach.py` about NAT source rewriting ⭐⭐⭐

**Marks: 20**

`reach.py` has a bug you were told about in Step 10b. When step 3 selects a **NAT gateway** as the route target, the destination no longer sees the source instance's private IP — it sees the **NAT gateway's public IP**. Yet steps 4–7 still evaluate the destination side using `src_ip`.

For flows that stay inside the VPC this never matters, because `local` always wins the longest-prefix match. For flows leaving through the NAT it matters a great deal, and it changes the correct NACL rules on your **public** subnets.

**Your task.**

1. Modify `bin/reach.py` so that when the selected route's target is a `NatGatewayId`:
   - the effective source address for all downstream evaluation becomes the NAT gateway's public IP (read it from `describe-nat-gateways`);
   - the return-path ephemeral range used in steps 6 and 7 becomes `1024–65535` (the NAT gateway's range, which your `EPHEMERAL` constant already matches — say so explicitly in a comment rather than relying on coincidence);
   - the trace prints an explicit line showing the rewrite, e.g. `3b. NAT source rewrite: 10.20.32.50 -> 52.203.11.7`.
2. Add a new row to `out/intended-matrix.tsv` proving that a host on the internet **cannot** reach an app-tier instance on an unsolicited port, and make it pass.
3. Write a short note (≤200 words) in `out/challenge4.md` explaining why this matters for NACLs on **public** subnets specifically.

**Acceptance criteria.**

- `python3 -m py_compile bin/reach.py` succeeds.
- `./bin/reach-matrix.sh` passes all rows, including your new one.
- The `app → internet 443` trace visibly shows the rewrite.
- Your note correctly identifies that return traffic from the internet arrives at the **NAT gateway's** subnet, not the app subnet.

<details>
<summary><strong>💡 Hint 1</strong> — where exactly does the rewrite belong?</summary>

Right after step 3 decides the route, and before steps 4–7 run. Keep a variable — call it `effective_src` — initialised to `src_ip` and reassigned only when the winning route has a `NatGatewayId`. Then replace every downstream use of `src_ip` with `effective_src`.

You need `describe-nat-gateways --nat-gateway-ids <id>` and the field `NatGateways[0].NatGatewayAddresses[0].PublicIp`. Guard against it being absent — a `private` connectivity-type NAT gateway has no public IP, in which case use `PrivateIp`.
</details>

<details>
<summary><strong>💡 Hint 2</strong> — why does the destination-side check still not apply?</summary>

For a flow to the internet you pass no `--to-subnet`, so steps 4–7 are skipped entirely and the rewrite appears to do nothing. That is correct behaviour and it is *not* the point of the exercise.

The point is the **new matrix row**: a flow *from* the internet *to* the app tier. There, the source is a public IP and the destination is a private subnet — and the honest answer is that there is no route back, no public IP on the target, and no security-group rule. Model that as BLOCKED and make sure your code reaches that verdict for the right reason, not by accident.
</details>

<details>
<summary><strong>✅ Model solution</strong></summary>

The patch, in three parts.

**1. A helper to look up the NAT gateway's address:**

```python
def nat_public_ip(nat_id):
    """Return the address a destination will actually see for NAT'd traffic."""
    got = aws("describe-nat-gateways", "--nat-gateway-ids", nat_id).get("NatGateways", [])
    if not got:
        return None
    for addr in got[0].get("NatGatewayAddresses", []):
        # connectivity-type=public gives PublicIp; connectivity-type=private does not
        ip = addr.get("PublicIp") or addr.get("PrivateIp")
        if ip:
            return ip
    return None
```

**2. Inside `main()`, replace the step-3 success branch:**

```python
    effective_src = src_ip          # the address the DESTINATION will see
    ...
        else:
            step(3, f"route table {rt['RouteTableId']} [{how}]", True,
                 f"{r['DestinationCidrBlock']} -> {target_of(r)}")
            if r.get("NatGatewayId"):
                nat_ip = nat_public_ip(r["NatGatewayId"])
                if nat_ip:
                    steps.append(("3b", "NAT source rewrite", "INFO",
                                  f"{src_ip} -> {nat_ip} ({r['NatGatewayId']}); "
                                  f"ephemeral return range for a NAT gateway is 1024-65535"))
                    effective_src = nat_ip
```

**3. Replace every downstream `src_ip` with `effective_src`** in steps 4, 6 and 7, and widen the trace printer to accept a string step number:

```python
        ok, why = nacl_decision(dst_acl, "ingress", effective_src, a.port, a.proto)
        ...
        ok, why = sg_permits(dst_sg, "ingress", effective_src, [a.src_sg], a.port, a.proto)
        ...
        ok, why = nacl_decision(dst_acl, "egress", effective_src, EPHEMERAL[0], a.proto)
```

```python
    for n, name, d, reason in steps:
        print(f"  {str(n):>2}. {d:5}  {name:52}  {reason}")
```

Note that step 5 now uses `effective_src` too — a security-group rule referencing `sg-app` will **not** match NAT'd traffic, because the source is no longer an ENI carrying that group. That is real AWS behaviour and catching it is worth full marks on its own.

**The new matrix row:**

```bash
printf 'internet\tapp\t8080\tBLOCKED\n' >> out/intended-matrix.tsv
```

and extend the runner's helpers so `internet` has a subnet-less source. The simplest correct approach is to treat `internet → *` as a flow with no source subnet in the VPC — which `reach.py` cannot model directly — so instead assert it the honest way: an unsolicited inbound flow to a private subnet has **no return route**. Add it as a data-tier-style check:

```bash
# an unsolicited packet from the internet to the app tier: model the RETURN path,
# which is the direction AWS actually evaluates from inside the VPC
python3 bin/reach.py --from-subnet "$SUBNET_APP_1A" --from-ip 10.20.32.10 \
  --to-ip 203.0.113.9 --port 8080 --src-sg "$SG_APP" | tail -6
# sg-app egress permits only 5432->sg-db, 443->sg-vpce and 443->0.0.0.0/0,
# so port 8080 outbound is DENIED at step 1 -> no session can be established
# in either direction.
```

**`out/challenge4.md`:**

```markdown
# Why NAT source rewriting matters for PUBLIC-subnet NACLs

Traffic from an app-tier instance to the internet leaves the VPC through the
NAT gateway, which lives in a PUBLIC subnet. The reply from the internet
therefore arrives at the public subnet's NACL, addressed to the NAT gateway's
Elastic IP on an ephemeral port — NOT at the app subnet's NACL, and not to the
instance's private address.

Two consequences that surprise people:

1. If you write a restrictive NACL on your public subnets, it must allow
   inbound TCP 1024-65535 from 0.0.0.0/0, or every outbound connection your
   PRIVATE instances make will hang. The rule lives on a subnet that contains
   none of the instances it is protecting.

2. A security-group rule that references sg-app cannot match NAT'd traffic,
   because once the source address is rewritten the packet is no longer
   associated with an ENI carrying that group. Security-group referencing
   works inside the VPC; beyond the NAT you are back to CIDRs.

The NAT gateway uses the ephemeral range 1024-65535 regardless of the guest
operating system, which is why AWS documentation recommends allowing that
full range in NACLs rather than the narrower Linux range 32768-60999.
```
</details>

---

## Challenge 5 — Design review: 50 000 pods and network change control ⭐⭐⭐⭐

**Marks: 25**

This challenge is mostly written. It is worth the most marks because design judgement is what distinguishes an engineer from a command-typist.

### Part A — Address a 50 000-pod EKS cluster (15 marks)

DNB's platform team wants to run EKS with the VPC CNI, where **every pod consumes a subnet IP address**. Produce `out/challenge5a.md` containing:

1. An addressing plan for 50 000 pods across three AZs, with the arithmetic shown.
2. A justification of why `10.20.0.0/16` alone cannot do it — with numbers, not assertions.
3. Your secondary-CIDR strategy, including which range you would use and why.
4. The interaction with the quotas: 200 subnets per VPC, 5 IPv4 CIDR blocks per VPC (adjustable to 50), 5 usable addresses lost per subnet.
5. The **two** AWS mitigations — a secondary CIDR from `100.64.0.0/10`, and VPC-CNI **prefix delegation** — with the trade-offs of each.
6. Then *implement* the secondary-CIDR portion for one AZ and verify it.

### Part B — Network change control (10 marks)

R9 says only the platform team may create or modify routes. Write `policies/network-change-control.json` — an IAM policy that:

1. Allows all `ec2:Describe*` on network resources to everyone.
2. Denies `ec2:CreateRoute`, `ec2:ReplaceRoute` and `ec2:DeleteRoute` unless the principal carries `Team=platform`.
3. Denies any route-table or NACL modification touching a resource tagged `Tier=data`, regardless of team.
4. Denies creation of any network resource that does not carry a `CostCenter` tag.
5. Denies `ec2:DeleteVpc`, `ec2:DeleteInternetGateway` and `ec2:DetachInternetGateway` to non-platform principals.

Then explain, in ≤150 words, why an IAM policy is **not sufficient** on its own and what two other controls you would pair it with.

**Acceptance criteria.**

- All arithmetic in Part A is correct and shown.
- The plan does not exceed any quota without naming the specific increase required.
- The implemented secondary CIDR passes an overlap check.
- The policy in Part B parses as valid JSON and uses the correct condition keys.
- The ≤150-word answer names CloudTrail alarms and Service Control Policies (or equivalent) and explains *why* IAM alone is insufficient.

<details>
<summary><strong>💡 Hint for Part A</strong></summary>

Start with the raw requirement: 50 000 pods, plus nodes, plus the CNI's warm pool, plus ENIs for load balancers and endpoints. Budget at least 1.4× the pod count.

A `/16` is 65 536 addresses **total**, and you have already consumed six `/20`s (24 576 addresses) on the base topology. Subtract, then subtract 5 per subnet, then compare with your budget.

For prefix delegation: the VPC CNI can assign a `/28` **prefix** to an ENI instead of individual secondary IPs, so one ENI slot covers 16 pod addresses. Ask what that does to the *number of ENIs* required versus the *number of addresses* required — they are different constraints, and prefix delegation only relieves one of them.
</details>

<details>
<summary><strong>💡 Hint for Part B</strong></summary>

The condition keys you need are `aws:PrincipalTag/Team`, `ec2:ResourceTag/Tier` and the `Null` operator on `aws:RequestTag/CostCenter`.

For the ≤150-word answer: think about who can *change the IAM policy itself*, and about the fact that an IAM deny tells you nothing until someone tries. What gives you detection rather than prevention, and what puts a ceiling above the account administrator?
</details>

<details>
<summary><strong>✅ Model solution — Part A</strong></summary>

```markdown
# Addressing plan: 50 000 pods on EKS with the VPC CNI

## 1. The real requirement
| Item | Count |
|---|---|
| Pods | 50 000 |
| Nodes (≈50 pods/node) | 1 000 |
| CNI warm pool (≈1 spare ENI-worth per node) | ~15 000 |
| ELB / interface-endpoint / NAT ENIs | ~200 |
| **Budget (≈1.35×)** | **~67 000 addresses** |

## 2. Why 10.20.0.0/16 cannot do it
A /16 is 65 536 addresses TOTAL. The base topology already consumes six /20s
= 6 × 4 096 = 24 576, leaving 40 960 raw. Subtract 5 per subnet for whatever
subnets we carve, and the ceiling is under 41 000 — well short of 67 000, and
that assumes we spend the ENTIRE remaining VPC on pods with nothing left for
the reserved third-AZ blocks or future growth. The primary CIDR is immutable,
so we cannot resize it.

## 3. Secondary CIDR strategy
Associate 100.64.0.0/16 (RFC 6598 shared address space) as a secondary CIDR,
and carve pod subnets exclusively from it:

| CIDR | AZ | Total | Usable | Purpose |
|---|---|---|---|---|
| 100.64.0.0/18   | AZ-1 | 16 384 | 16 379 | pods |
| 100.64.64.0/18  | AZ-2 | 16 384 | 16 379 | pods |
| 100.64.128.0/18 | AZ-3 | 16 384 | 16 379 | pods |
| 100.64.192.0/18 | —    | 16 384 | —      | RESERVED for growth |

3 × 16 379 = 49 137 usable. That covers the 50 000 pods only if the warm pool
is disabled, so add a second secondary CIDR — 100.65.0.0/16 — carved the same
way, giving ~98 000 usable and comfortable headroom.

RFC 6598 is chosen because it is NOT RFC 1918: it rarely collides with a
corporate network, which matters because DNB's branches use 172.16.0.0/16 and
staging/prod use 10.21/10.22. We do NOT advertise 100.64.0.0/10 to on-premises
over the future VPN — it is VPC-internal capacity only.

## 4. Quota interaction
| Quota | Default | Our usage | Action |
|---|---|---|---|
| IPv4 CIDR blocks per VPC | 5 | 3 (primary + 2 secondary) | within default |
| Subnets per VPC | 200 | 9 base + 8 pod = 17 | within default |
| Addresses lost to reservation | 5/subnet | 8 pod subnets × 5 = 40 | negligible at this size |
| NAT gateways per AZ | 5 | 1 | within default |

No increase required — but note that adding a THIRD secondary CIDR would hit
the 5-block limit, which is adjustable to 50 on request.

## 5. The two mitigations, and their trade-offs

**(a) Secondary CIDR from 100.64.0.0/10.**
+ Solves the ADDRESS shortage outright; no node-level changes; works with any
  instance type and any CNI version.
− Adds a second `local` route to every route table in the VPC, which will
  swallow any peer or VPN prefix that overlaps 100.64/16. Must be checked
  against every peer BEFORE association.
− Does nothing about the ENI/IP-per-ENI limits, so pod density per node is
  unchanged.

**(b) VPC CNI prefix delegation (ENABLE_PREFIX_DELEGATION=true).**
+ Assigns a /28 prefix per ENI instead of individual secondary IPs, so one ENI
  slot covers 16 pod addresses. Raises pod density per node dramatically and
  cuts EC2 API calls, which removes a real throttling failure mode at scale.
− CONSUMES MORE ADDRESSES, not fewer: a /28 is allocated whole even for one
  pod, so fragmentation can waste up to 15 addresses per ENI. It relieves the
  ENI-slot constraint and worsens the address constraint.
− Requires nitro instance types and CNI ≥ 1.9.0.

**Conclusion: they are complementary, not alternatives.** Prefix delegation
raises density; the secondary CIDR pays for the addresses that density
consumes. Use both, and size the secondary CIDR assuming prefix-delegation
fragmentation — which is why the plan above allocates ~98 000 usable addresses
for a 50 000-pod requirement rather than ~55 000.
```

**Implementation for one AZ:**

```bash
aws ec2 associate-vpc-cidr-block --vpc-id "$VPC_ID" --cidr-block 100.64.0.0/16 \
  --query 'CidrBlockAssociation.[AssociationId,CidrBlock,CidrBlockState.State]' --output text

SUBNET_PODS_1A=$(aws ec2 create-subnet --vpc-id "$VPC_ID" \
  --cidr-block 100.64.0.0/18 --availability-zone "$AZ_A" \
  --tag-specifications 'ResourceType=subnet,Tags=[
      {Key=Name,Value=dnb-dev-subnet-pods-1a},{Key=Project,Value=CoreBanking},
      {Key=Environment,Value=dev},{Key=Owner,Value=platform-team},
      {Key=CostCenter,Value=CC-4400},{Key=ManagedBy,Value=floci-lab},
      {Key=Tier,Value=app}]' \
  --query 'Subnet.SubnetId' --output text)
setid SUBNET_PODS_1A "$SUBNET_PODS_1A"

aws ec2 associate-route-table --route-table-id "$RTB_PRIVATE_1A" \
  --subnet-id "$SUBNET_PODS_1A" >/dev/null

# The second `local` route should have appeared AUTOMATICALLY:
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

That second `local` route is the danger the plan warns about: if a peered VPC or an on-premises network already used `100.64.0.0/16`, that traffic would now be swallowed by the more specific `local` route and never reach the peer. **Adding a secondary CIDR can break existing connectivity.** Check overlap against every peer and every VPN prefix before you associate.

Overlap check:

```bash
cat > bin/assert-no-cidr-overlap.sh <<'SH'
#!/usr/bin/env bash
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
if not fail:
    print("  no overlaps, all subnets inside a VPC CIDR")
sys.exit(fail)
PY
SH
chmod +x bin/assert-no-cidr-overlap.sh
./bin/assert-no-cidr-overlap.sh
```
</details>

<details>
<summary><strong>✅ Model solution — Part B</strong></summary>

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
      "Sid": "OnlyPlatformMayChangeRoutes",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:DeleteRoute"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": { "aws:PrincipalTag/Team": "platform" }
      }
    },
    {
      "Sid": "NobodyTouchesTheDataTierNetworking",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:DeleteRoute",
        "ec2:AssociateRouteTable",
        "ec2:DisassociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateNetworkAclEntry",
        "ec2:DeleteNetworkAclEntry",
        "ec2:ReplaceNetworkAclEntry",
        "ec2:ReplaceNetworkAclAssociation"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": { "ec2:ResourceTag/Tier": "data" }
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
        "ec2:CreateVpcEndpoint",
        "ec2:AllocateAddress"
      ],
      "Resource": "*",
      "Condition": {
        "Null": { "aws:RequestTag/CostCenter": "true" }
      }
    },
    {
      "Sid": "DenyDestroyingTheVpcEdge",
      "Effect": "Deny",
      "Action": [
        "ec2:DeleteVpc",
        "ec2:DeleteInternetGateway",
        "ec2:DetachInternetGateway"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": { "aws:PrincipalTag/Team": "platform" }
      }
    }
  ]
}
JSON
python3 -c "import json;json.load(open('policies/network-change-control.json'));print('policy parses OK')"
```

**Why IAM alone is not sufficient (≤150 words):**

> An identity policy is evaluated only when someone makes an API call, and it is
> attached by the same administrators it is meant to constrain — anyone who can
> edit IAM can edit this policy, so it bounds mistakes rather than intent.
> It also produces no signal: a denied `CreateRoute` is invisible unless
> something is watching.
>
> Pair it with two controls. First, a **Service Control Policy** at the
> Organizations level, which no account administrator can override, denying
> `ec2:CreateRoute` with an `igw-` target on production data-tier route tables.
> That puts a ceiling above the account itself. Second, a **CloudTrail metric
> filter and alarm** on `CreateRoute`, `AuthorizeSecurityGroupIngress`,
> `AttachInternetGateway` and `DeleteNetworkAclEntry` — the five events that
> change the account's exposure — so that a *successful* change by an authorised
> principal is still detected and reviewed. Prevention bounds the blast radius;
> detection catches the legitimate-but-wrong change that prevention permits.
</details>

---
---

# Assessment

Submit `~/vpc-lab-submission.tar.gz` plus a written report addressing the following.

## Marks for the follow-along (100)

| # | Deliverable | Evidence file(s) | Marks |
| --- | --- | --- | --- |
| 1 | Support matrix, and how you classified each operation | `out/support-matrix.tsv`, `out/support-report.txt` | 6 |
| 2 | Addressing plan with the arithmetic shown | `out/ipam-record.md`, `out/subnet-plan.tsv` | 8 |
| 3 | Working topology: 6 subnets, 2 AZs, IGW, per-AZ NAT, isolated data tier | `out/topology.json`, `out/step04-routing.txt` | 14 |
| 4 | Security groups using references only, egress restricted | `out/step05-sg.txt`, `assert-sg-invariants` output | 10 |
| 5 | NACL with correct ephemeral return rules, plus linter output | `out/step06-acl.txt`, `lint-nacl` output | 10 |
| 6 | VPC endpoints with the before/after path analysis table | `out/step07-endpoints.txt`, `policies/vpce-s3-policy.json` | 8 |
| 7 | EC2 configured correctly: private instance, IMDSv2, no public IP, secondary ENI, EIP on the public instance | `out/step08-instance.json`, `out/step09-enis.txt` | 10 |
| 8 | Address accounting reconciled against `describe-network-interfaces` | `out/step09-dataplane.txt` | 5 |
| 9 | `reach.py` and a passing matrix **with stated intent** | `bin/reach.py`, `out/intended-matrix.tsv`, `out/step11-matrix.txt` | 15 |
| 10 | Divergence log: every place Floci differed from AWS, with consequences | `out/divergence-log.md` | 8 |
| 11 | Audit response for R5 including residual risks | `out/audit-response-R5.md` | 6 |

## Automatic deductions

| Issue | Deduction |
| --- | --- |
| Any claim of *observed* traffic behaviour without L3 evidence | −10 |
| A CIDR literal used for intra-VPC security-group rules without justification | −5 |
| Any resource left running at submission (especially NAT gateways or EIPs) | −5 |
| An untagged resource | −3 |
| A security-group rule without a `Description` | −2 |

## Reflection questions — answer in `out/reflection.md`

Prose, your own words, graded on honesty and insight rather than length.

1. Before this lab, what did you believe made a subnet "public"? What do you believe now?
2. Name a mistake you made that produced **no error message**. How did you eventually notice it? What check would have caught it earlier?
3. Which Break-it step produced an outcome you predicted **incorrectly**? What was your wrong mental model?
4. Your design has five independent controls preventing data-tier exfiltration. Rank them by how likely each is to be accidentally removed by a well-meaning engineer, and justify the ranking.
5. You revoked allow-all egress from every security group. Argue the *counter*-case: when is restricting egress not worth the operational cost?
6. List three conclusions in this lab that you can support only by reasoning, never by observation. State what evidence you would need from real AWS to confirm each.
7. Did working on an emulator make you understand VPC better or worse than a real account would have? Argue both sides, then take a position.

---

# Appendix A — Quick reference

## CIDR and address maths

| Prefix | Total | AWS usable | Typical use |
| --- | --- | --- | --- |
| `/16` | 65 536 | 65 531 | Whole VPC |
| `/18` | 16 384 | 16 379 | EKS pod subnet |
| `/20` | 4 096 | **4 091** | **Our subnet size** |
| `/22` | 1 024 | 1 019 | Tier in a third AZ |
| `/24` | 256 | 251 | Small subnet |
| `/26` | 64 | 59 | ALB subnet (minimum practical) |
| `/28` | 16 | **11** | AWS minimum |

`usable = 2^(32 − prefix) − 5`

**The five reserved addresses**, for `10.20.32.0/20`: `.0` network, `.1` VPC router, `.2` Amazon DNS resolver, `.3` reserved by AWS, `10.20.47.255` broadcast.

**Protocol numbers for NACL entries:** `-1` all, `1` ICMP, `6` TCP, `17` UDP, `58` ICMPv6.

**Ephemeral ranges:** Linux `32768–60999`; Windows 2008+ `49152–65535`; NLB and NAT gateway `1024–65535`; Lambda `1024–65535`. **Allow `1024–65535`** in NACLs to cover all clients.

**Special addresses:** `169.254.169.254` instance metadata (IMDS); `169.254.169.253` VPC DNS; `169.254.169.123` Amazon Time Sync; `172.31.0.0/16` default VPC; `172.17.0.0/16` Docker bridge — **never** use it for a VPC.

## Command cheat sheet

| Task | Command |
| --- | --- |
| Create VPC | `aws ec2 create-vpc --cidr-block 10.20.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=x}]'` |
| Enable DNS | `aws ec2 modify-vpc-attribute --vpc-id V --enable-dns-hostnames` (one attribute per call) |
| Create subnet | `aws ec2 create-subnet --vpc-id V --cidr-block 10.20.0.0/20 --availability-zone us-east-1a` |
| Auto-assign public IP | `aws ec2 modify-subnet-attribute --subnet-id S --map-public-ip-on-launch` |
| Attach IGW | `aws ec2 attach-internet-gateway --internet-gateway-id I --vpc-id V` |
| Default route → IGW | `aws ec2 create-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --gateway-id I` |
| Default route → NAT | `aws ec2 create-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --nat-gateway-id N` |
| Change a route | `aws ec2 replace-route --route-table-id R --destination-cidr-block 0.0.0.0/0 --nat-gateway-id N2` |
| Associate route table | `aws ec2 associate-route-table --route-table-id R --subnet-id S` |
| Allocate EIP | `aws ec2 allocate-address --domain vpc` |
| Create NAT gateway | `aws ec2 create-nat-gateway --subnet-id S_public --allocation-id E --connectivity-type public` |
| SG rule from another SG | `aws ec2 authorize-security-group-ingress --group-id G --ip-permissions 'IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=G2,Description=d}]'` |
| Remove allow-all egress | `aws ec2 revoke-security-group-egress --group-id G --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'` |
| NACL rule | `aws ec2 create-network-acl-entry --network-acl-id A --ingress --rule-number 100 --protocol tcp --port-range From=443,To=443 --cidr-block 0.0.0.0/0 --rule-action allow` |
| Associate NACL | `aws ec2 replace-network-acl-association --association-id AS --network-acl-id A` |
| Gateway endpoint | `aws ec2 create-vpc-endpoint --vpc-id V --vpc-endpoint-type Gateway --service-name com.amazonaws.us-east-1.s3 --route-table-ids R1 R2` |
| Interface endpoint | `aws ec2 create-vpc-endpoint --vpc-id V --vpc-endpoint-type Interface --service-name com.amazonaws.us-east-1.sts --subnet-ids S1 S2 --security-group-ids G --private-dns-enabled` |
| Launch instance | `aws ec2 run-instances --image-id A --instance-type t3.micro --subnet-id S --security-group-ids G --metadata-options HttpTokens=required` |
| Create ENI | `aws ec2 create-network-interface --subnet-id S --groups G --private-ip-address 10.20.32.11` |
| Find blackholes | `aws ec2 describe-route-tables --query 'RouteTables[].Routes[?State==\`blackhole\`]'` |
| Find orphan EIPs | `aws ec2 describe-addresses --query 'Addresses[?AssociationId==null]'` |
| Find what blocks a delete | `aws ec2 describe-network-interfaces --filters Name=subnet-id,Values=S` |

## Quotas (AWS defaults)

| Resource | Default | Adjustable |
| --- | --- | --- |
| VPCs per Region | 5 | Yes |
| IPv4 CIDR blocks per VPC | 5 | Yes (to 50) |
| Subnets per VPC | 200 | Yes |
| Subnet prefix length | `/16`–`/28` | No |
| Reserved addresses per subnet | 5 | **No** |
| Route tables per VPC | 200 | Yes |
| Routes per route table | 500 | Yes |
| Network ACLs per VPC | 200 | Yes |
| Rules per NACL, per direction | 20 | Yes (to 40) |
| Security groups per Region | 2 500 | Yes |
| Inbound / outbound rules per SG | 60 / 60 | Yes |
| Security groups per ENI | 5 | Yes (to 16) |
| Internet gateways per VPC | 1 | **No** |
| NAT gateways per AZ | 5 | Yes |
| Elastic IPs per Region | 5 | Yes |
| Interface endpoints per VPC | 50 | Yes |
| Gateway endpoints per Region | 20 | Yes |
| NAT simultaneous connections per destination | 55 000 | **No** |

## Do / Do not

| Do | Do not |
| --- | --- |
| Reference security groups for intra-VPC traffic | Use CIDR literals inside the VPC |
| Keep the main route table `local`-only | Add a default route to the main table |
| Associate every subnet explicitly | Rely on implicit main-table association |
| One NAT gateway and one private route table per AZ | Share one NAT across AZs |
| Isolate the data tier (no default route) | "Privatise" it behind NAT and call it done |
| Revoke allow-all egress deliberately | Leave every group with `0.0.0.0/0` egress |
| Use SSM Session Manager | Open 22/3389, even "temporarily" |
| Add S3 / DynamoDB gateway endpoints on day one | Pay NAT data processing for S3 traffic |
| Allow 443 on interface-endpoint security groups | Wonder why SDK calls hang |
| Write ephemeral return rules with every NACL allow | Debug a hang for two hours |
| Enforce IMDSv2 with `HttpTokens=required` | Leave IMDSv1 enabled |
| Tag atomically at creation | Plan to tag later |
| Lock down the default security group to nothing | Let mistakes fail open |
| Release Elastic IPs explicitly | Assume deleting the NAT releases them |
| Check for blackholes first when something breaks | Start with security groups |
| State whether evidence is L1, L2 or L3 | Say "verified" |

---

# Appendix B — Session restart card

Tape this to your monitor.

```bash
# Start of every session
eval "$(floci env)"
guard
cd ~/vpc-lab
. bin/ids.sh
loadids
cat "$LEDGER"          # confirm your IDs are loaded

# End of every session
./bin/verify-all.sh
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[AllocationId,PublicIp]' --output table
#   ^ anything listed here is a live charge in a real account
```

---

# Appendix C — Floci support summary

Confirm every row against **your own** `out/support-matrix.tsv`. Your build is the authority; this table is a starting hypothesis.

| Feature area | Structure | Behaviour | Notes |
| --- | --- | --- | --- |
| VPC create/describe/delete/attributes | ✅ | ⚠️ | Including `CreateDefaultVpc`, `AssociateVpcCidrBlock` |
| Subnets | ✅ | ⚠️ | `ModifySubnetAttribute` supported |
| Route tables and routes | ✅ | ❌ | Objects stored; **no packet routing** |
| Internet gateway | ✅ | ❌ | No 1:1 NAT function |
| NAT gateway | ✅ | ❌ | No translation |
| Elastic IPs | ✅ | ⚠️ | Full allocate/associate/release set |
| Network interfaces | ⚠️ | ⚠️ | Probe the exact operation set |
| EC2 instances | ⚠️ | ❌ | Metadata only; no OS boots |
| Security groups | ✅ | ❌ | Full rule API; **no filtering** |
| Network ACLs | ✅ | ❌ | Full entry API; **no evaluation** |
| VPC endpoints (gateway + interface) | ⚠️ | ❌ | Create/describe/delete; traffic path not observable |
| Prefix lists | ⚠️ | ❌ | Probe `create-managed-prefix-list` separately |
| VPC peering | ❌ | ❌ | Usually absent |
| Transit gateway | ❌ | ❌ | Conceptual only |
| Flow logs | ❌ | ❌ | Conceptual only |
| DHCP option sets | ❌ | ❌ | Conceptual only |
| Reachability Analyzer | ❌ | ❌ | **Replaced by `bin/reach.py`** |
| IPAM | ❌ | ❌ | Replaced by `out/ipam-record.md` |

> When you present this work, say exactly this: *"Floci does not implement Reachability Analyzer, so I implemented its evaluation model in 250 lines of Python and validated my topology against it."* That is a stronger demonstration of understanding than clicking the real service.

---

# What comes next

| Module | The thread this lab hands over |
| --- | --- |
| **EC2 (deep dive)** | Instance types and ENI/IP density limits; placement groups; source/destination checks for NAT instances |
| **ELB** | Why ALBs need ≥2 AZs and 8 free IPs per subnet; NLB source-IP preservation and its effect on target security groups |
| **RDS** | DB subnet groups; why Multi-AZ needs two AZs; the RDS ENI that blocks subnet deletion |
| **Lambda** | Hyperplane ENIs; why a VPC-attached function loses internet access; when *not* to attach |
| **ECS / EKS** | `awsvpc` mode; one IP per task/pod; Challenge 5's secondary CIDRs and prefix delegation, for real |
| **S3** | Block Public Access, `aws:SourceVpce` bucket policies, gateway-endpoint economics |
| **CloudWatch** | Flow logs to Logs Insights; metric filters and alarms on `REJECT` spikes |
| **Route 53** | Private hosted zones, Resolver endpoints and rules, DNS Firewall |
| **CloudFormation** | Rebuild this exact topology as a template and diff `topology.json` against it. Two things to explain: why mutually-referencing security groups need the standalone `AWS::EC2::SecurityGroupIngress` resource, and why the default route needs `DependsOn` the `VPCGatewayAttachment` |
| **Organizations** | SCPs that deny `ec2:CreateRoute` to an IGW in production accounts — Challenge 5 Part B, enforced above the account |
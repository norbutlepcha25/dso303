# Lab 05 - Putting the ECS Service Behind an Application Load Balancer

## 1. Objectives

- Give Lab 04's `usms-enrolment-svc` a stable name: an internet-facing Application Load Balancer in Lab 2's two public subnets, with its own security group.
- Create a target group (`--target-type ip`) with a deliberate health check and deregistration delay, a listener with a default action, and one listener rule.
- Attach the existing service to the target group so ECS registers and deregisters its own tasks, then cut over so the load balancer is the only thing that can reach the tasks.
- Watch a deployment drain targets, prove the whole stack survives a restart, and save its ARNs to `configs/lab-05.env` for Lab 06.

The lab closes with an **in-class assessment** (Section 13.1), done individually at the machine and marked from your repository. **Time:** roughly 3 hours for Sections 7 and 8, plus 75 minutes for the assessment.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [load balancers in the request path](../unit1/topic6.md#load-balancers-and-cloudfront-in-the-request-path) ·
    [ALB vs NLB, target types, the two health checks, draining](../unit2/topic2.md#north-south-getting-traffic-in) ·
    [how the ALB reaches a task](../unit2/topic2.md#how-the-alb-reaches-a-task) ·
    [task network modes](../unit2/topic2.md#task-network-modes) ·
    [service load balancing options](../unit2/topic2.md#service-networking-and-load-balancing) ·
    [target health](../unit7/topic1.md#elastic-load-balancing-target-health) ·
    [ECS container health checks plus load balancer health](../unit7/topic1.md#amazon-ecs-container-health-checks-plus-load-balancer-health) ·
    [security group referencing](../unit1/topic6.md#security-group-referencing-the-cloud-native-idiom)

!!! warning "This lab deliberately changes one thing Lab 04 built, and Lab 04's script will notice"
    Step 13 removes the rule that let `usms-web-01` reach the enrolment tasks directly. Afterwards `scripts/utilities/verify-lab-04.sh` reports **exactly one** failure:

    ```text
      FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
    ```

    That is not a mistake in your work: the script encodes an architecture that has since changed. Section 10 says what to do; Exercise 2 fixes it properly. From Step 13 onward, `verify-lab-05.sh` is the script of record.

Auto scaling is **Lab 06**, and it comes after this lab on purpose: its best signal, `ALBRequestCountPerTarget`, needs a target group. Exercise 5 builds the `ResourceLabel` that unlocks it. This lab writes `configs/lab-05.env`; Lab 06 sources it alongside `lab-04.env`.

---

## 2. Prerequisites

- Lab 04 complete: `./scripts/utilities/verify-lab-04.sh` reports `FAIL=0` **now**, before you start (not after Step 13).
- Lab 2 Step 11 "Your turn" complete, so `usms-public-subnet-b` exists. An ALB refuses to be created without subnets in two Availability Zones; this is the prerequisite most often missing.
- Lab 2 Exercise 5 complete (`usms-private-subnet-b`; Lab 04's service already needs it).
- Lab 3 complete: `usms-web-01` running with `usms-app-sg` (Step 17 resolves it).
- Errata 01 applied: `echo "$AWS_PROFILE"` in a new terminal must print `floci`.
- Floci under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`; `jq`, `python3` and `curl` installed.

```bash
cd ~/aws-floci-course
for t in jq python3 docker curl; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
./scripts/utilities/floci-storage-check.sh
```

> Example output - your versions and paths will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
curl       /usr/bin/curl
aws-cli/2.17.42 Python/3.11.9 Darwin/23.5.0 exe/x86_64
...
PASS=16  FAIL=0
```

You want four tools found and `PASS=16  FAIL=0`. A failure in the storage check's `shell and profile` block is the real problem; fix it first. If `curl` is missing, Step 12 also gives a `wget` form, and neither is essential to passing.

---

## 3. What This Lab Reuses

From Lab 2:

- `usms-public-subnet-a` and `-b`: the load balancer's nodes (Step 5).
- `usms-igw` and `usms-public-rt`: why an internet-facing ALB is reachable (Steps 5, 12).
- `usms-vpc`: the target group belongs to it permanently (Step 6).
- `usms-app-sg`: removed as a source (Step 13), resolved back to `usms-web-01` (Step 17).

From Lab 3:

- `usms-web-01`: still the caller, now via a name (Step 17).

From Lab 04:

- `usms-enrolment-svc`: attached to the target group; no new service is created (Step 10).
- `usms-enrolment:2`: `containerName` `enrolment-api` and `containerPort` `80` must match (Step 10). No new revision is registered.
- `usms-enrolment-sg`: ingress changes from the web tier to the load balancer (Steps 9, 13). The tasks stay private.
- `usms-ecs-cluster`: named by every `ecs` call.

```text
Created in this lab:
- usms-alb-sg                   security group for the load balancer: tcp/80 from the internet
- usms-enrolment-alb            internet-facing Application Load Balancer, public subnets a and b
- usms-enrolment-tg             target group, target-type ip, HTTP/80, health check on /
- usms-enrolment-listener       listener on tcp/80, default action forwards to the target group
- usms-enrolment-health-rule    listener rule, priority 10, fixed-response 200 on /alb-health
- an ingress rule on usms-enrolment-sg admitting tcp/80 from usms-alb-sg
- the REMOVAL of usms-enrolment-sg's direct rule from usms-app-sg   (Step 13, deliberate)
- loadBalancers and healthCheckGracePeriodSeconds on usms-enrolment-svc
- policies/usms-alb-sg-ingress.json, policies/usms-enrolment-sg-ingress-alb.json
- templates/lab-05-listener-default-actions.json, templates/lab-05-rule-conditions.json,
  templates/lab-05-rule-actions.json, templates/lab-05-service-load-balancers.json
- configs/lab-05.env
- scripts/utilities/verify-lab-05.sh
- scripts/cleanup/lab-05-cleanup.sh

Required for future labs:
- usms-enrolment-tg             -> Lab 06's ALBRequestCountPerTarget metric names this target group
- USMS_ALB_RESOURCE_LABEL       -> Lab 06 Exercise material; built in this lab's Exercise 5
- usms-enrolment-alb            -> the CloudFormation lab re-declares this whole stack
- usms-enrolment-svc            -> Lab 06 scales it; it is now load balanced, which changes the metric
- usms-alb-sg                   -> the HTTPS/ACM material, whenever this course reaches it
- configs/lab-05.env           -> Lab 06 sources it alongside lab-01/02/03/04
```

---

## 4. What We Are Building

Lab 04's tasks have private, temporary addresses and no name. This lab puts a stable name in front of them: an internet-facing ALB in the public subnets forwarding to a target group that the **ECS service** keeps populated. The tasks stay private; the only path from the internet to a task passes through a listener and a security group you wrote. The old direct path is removed only after the new one is proven (Steps 9, 12, 13): a migration, not an outage.

```text
scheme               internet-facing    nodes in public subnets a and b, with public addresses
type                 application        HTTP-aware; layer 7; rules can match paths and headers
listener             HTTP : 80          one default action, plus one rule at priority 10
target group type    ip                 mandatory for awsvpc; the only value Fargate accepts
target group port    HTTP : 80          matches enrolment-api's containerPort from Lab 04
health check         GET /  every 30s   timeout 5s, healthy 2, unhealthy 2, matcher 200
deregistration delay 30 seconds         in-flight requests get 30 seconds before the task dies
grace period         60 seconds         ECS ignores target health for the first 60s of a task's life
task inbound         tcp/80 from usms-alb-sg ONLY
```

The in-class assessment asks you to defend three of these.

---

## 5. Architecture

```text
                              Internet
                                  |
                                  |  http://<usms-enrolment-alb DNS name>/
                                  v
                        +---------+---------+
                        |     usms-igw      |
                        +---------+---------+
                                  |
  ================================|=========================================
  ||  usms-vpc  10.0.0.0/16       |                                       ||
  ||   usms-public-rt  0.0.0.0/0 -+                                       ||
  ||        |                                                             ||
  ||   +----+------------------------+   +------------------------------+ ||
  ||   | usms-public-subnet-a        |   | usms-public-subnet-b         | ||
  ||   | 10.0.1.0/24   us-east-1a    |   | 10.0.2.0/24   us-east-1b     | ||
  ||   |                             |   |                              | ||
  ||   |  [ ALB node ] usms-alb-sg   |   |  [ ALB node ] usms-alb-sg    | ||
  ||   |  [ usms-web-01 ] app-sg     |   |                              | ||
  ||   |  [ usms-nat    ] EIP        |   |                              | ||
  ||   +----+------------------------+   +---------------+--------------+ ||
  ||        |                                            |                ||
  ||        |   usms-enrolment-alb  (internet-facing, type application)   ||
  ||        |     listener  HTTP:80                                       ||
  ||        |       rule  priority 10   path /alb-health -> fixed 200     ||
  ||        |       default action                       -> forward       ||
  ||        |                                                |            ||
  ||        |                              usms-enrolment-tg |            ||
  ||        |                                target-type ip  |            ||
  ||        |                                health check GET /           ||
  ||        v                                                v            ||
  ||   tcp/80, source = usms-alb-sg   (Step 9 adds, Step 13 makes it the only one)
  ||        |                                                |            ||
  ||   +----+------------------------+   +------------------+-----------+ ||
  ||   | usms-private-subnet-a       |   | usms-private-subnet-b        | ||
  ||   | 10.0.3.0/24   us-east-1a    |   | 10.0.4.0/24   us-east-1b     | ||
  ||   |                             |   |                              | ||
  ||   |  [ task 1 ] ENI  10.0.3.x   |   |  [ task 2 ] ENI  10.0.4.x    | ||
  ||   |    usms-enrolment-sg        |   |    usms-enrolment-sg         | ||
  ||   |  [ usms-db-01 ]             |   |                              | ||
  ||   +-----------------------------+   +------------------------------+ ||
  ||        |                                                             ||
  ||   usms-private-rt   0.0.0.0/0 -> usms-nat        (image pull, Lab 04)||
  ||                     pl-...    -> usms-s3-endpoint                     ||
  ||                                                                       ||
  ||   ECS control plane                                                   ||
  ||     usms-ecs-cluster                                                  ||
  ||       usms-enrolment-svc     desiredCount 2                           ||
  ||         loadBalancers[0]     targetGroupArn = usms-enrolment-tg       ||
  ||                              containerName  = enrolment-api           ||
  ||                              containerPort  = 80                      ||
  ||         healthCheckGracePeriodSeconds  60                             ||
  ||         >>> the SERVICE registers and deregisters the targets <<<     ||
  =========================================================================

  Lab 06 adds, against the same service and this lab's target group:
  +---------------------------------------------------------------------+
  | scaling policy   ALBRequestCountPerTarget                            |
  |   ResourceLabel  app/usms-enrolment-alb/<id>/targetgroup/usms-...    |
  +---------------------------------------------------------------------+
```

Read the three capitalised words in the ECS box before you start. **The service registers the
targets.** Not you. The most common way to waste an hour in this lab is to notice that the target group
is empty and reach for `aws elbv2 register-targets`, which will appear to work and will be undone by
the service within minutes.

---

## 6. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-05-ecs-alb/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 12 and Section 13.1
├── policies/
│   ├── usms-alb-sg-ingress.json                       # NEW - the load balancer's inbound rule
│   └── usms-enrolment-sg-ingress-alb.json             # NEW - the tasks' new inbound rule
├── templates/
│   ├── lab-05-listener-default-actions.json          # NEW - create-listener --default-actions
│   ├── lab-05-rule-conditions.json                   # NEW - create-rule --conditions
│   ├── lab-05-rule-actions.json                      # NEW - create-rule --actions
│   └── lab-05-service-load-balancers.json            # NEW - update-service --load-balancers
├── configs/
│   └── lab-05.env                                    # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-05.sh                          # NEW - Section 8
│   └── cleanup/
│       └── lab-05-cleanup.sh                         # NEW - end of course only
└── outputs/
    └── lab-05-*.json / *.txt                         # command output, git-ignored
```

The same split as Lab 04, for the same reason. The two security group documents **grant** something, so
they live in `policies/`. The four load balancer documents are **API request bodies**, so they live in
`templates/`. A reviewer opening `policies/` should be looking at your security posture and nothing
else.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-05-ecs-alb
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs-fargate  labs/lab-05-ecs-alb
```

---

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths (`configs/...`, `policies/...`, `templates/...`, `scripts/...`) are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    This lab captures six ARNs. Elastic Load Balancing is ARN-first (only the read-only calls take `--names`), so capture every one with `$(...)`, `--query` and `--output text`. Step 18 writes them to `configs/lab-05.env`.

### Step 1 - Resume the environment and load five env files

Bring Floci up and load what the previous labs recorded. The public subnets are the values most likely to be missing.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04.env

./scripts/utilities/whoami.sh

printf '%-26s %s\n' \
  "vpc"                 "$USMS_VPC_ID" \
  "public subnet a"     "$USMS_PUBLIC_SUBNET_A" \
  "public subnet b"     "$USMS_PUBLIC_SUBNET_B" \
  "private subnet a"    "$USMS_PRIVATE_SUBNET_A" \
  "private subnet b"    "$USMS_PRIVATE_SUBNET_B" \
  "app security group"  "$USMS_APP_SG" \
  "enrolment sg"        "$USMS_ENROLMENT_SG" \
  "web instance"        "$USMS_WEB_INSTANCE" \
  "cluster"             "$USMS_ECS_CLUSTER" \
  "service"             "$USMS_ENROLMENT_SERVICE" \
  "container"           "$USMS_ENROLMENT_CONTAINER" \
  "region"              "$AWS_REGION_COURSE"
```

The env files are additive and define no variable twice, so source order does not matter.

**Expected result**

```text
[floci-up] container 'floci' already running (compose project: floci-course)

Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Profile  : floci

vpc                        vpc-0a1b2c3d4e5f67890
public subnet a            subnet-01234abcd5678ef90
public subnet b            subnet-0fedcba9876543210
private subnet a           subnet-09876fedcba543210
private subnet b           subnet-0aabbccdd11223344
app security group         sg-0123456789abcdef0
enrolment sg               sg-0aa11bb22cc33dd44
web instance               i-0123456789abcdef0
cluster                    usms-ecs-cluster
service                    usms-enrolment-svc
container                  enrolment-api
region                     us-east-1
```

> Example output - your IDs will differ.

**Verify:** twelve non-empty values. Two empty values stop the lab:

- **`public subnet b` empty**: Lab 2 Step 11 "Your turn" was skipped. Do it now with Lab 2's own CIDR and AZ (not the same AZ as subnet a; `create-load-balancer` checks zones, not count). Otherwise Step 5 fails with `ValidationError: At least two subnets in two different Availability Zones must be specified`.
- **`enrolment sg` empty**: `configs/lab-04.env` is missing or incomplete. Re-run Lab 04 Step 20.

---

### Step 2 - Confirm Labs 2, 3 and 04 are still intact

This lab changes Lab 04's security group and service. Confirm they are intact first, so the expected failure after Step 13 is clearly yours and deliberate.

```bash
./scripts/utilities/verify-lab-02.sh | tail -3
./scripts/utilities/verify-lab-03.sh | tail -3
./scripts/utilities/verify-lab-04.sh | tee outputs/lab-05-pre-verify-04.txt | tail -3
```

The third result is saved to `outputs/` as the "before" to compare with after Step 13. If a count is wrong, re-run without `| tail -3`.

**Expected result**

```text
PASS=33  FAIL=0
PASS=36  FAIL=0
PASS=49  FAIL=0
```

> Example output - the counts are the ones those labs stated.

**Verify:** `FAIL=0` three times. If Lab 04's is not `FAIL=0`, **do not start this lab**; fix Lab 04 first. A failure under `== Environment ==` is the real problem; fix it with `./scripts/utilities/floci-storage-check.sh`.

---

### Step 3 - Probe what this Floci build supports for Elastic Load Balancing

ELBv2 is the least reliably emulated service in this course. Find out now which parts your build implements, not at Step 10 with a half-built load balancer.

```bash
probe() {
  printf '%-48s ' "$1"
  if eval "$2" >/dev/null 2>&1; then echo "SUPPORTED"; else echo "not available"; fi
}

echo "== Elastic Load Balancing v2 =="
probe "elbv2 describe-load-balancers"        "aws elbv2 describe-load-balancers"
probe "elbv2 create-load-balancer (skeleton)" "aws elbv2 create-load-balancer --generate-cli-skeleton"
probe "elbv2 describe-target-groups"          "aws elbv2 describe-target-groups"
probe "elbv2 create-target-group (skeleton)"  "aws elbv2 create-target-group --generate-cli-skeleton"
probe "elbv2 describe-listeners (bad arn)"    "aws elbv2 describe-listeners --load-balancer-arn probe"
probe "elbv2 describe-account-limits"         "aws elbv2 describe-account-limits"

echo "== ECS integration =="
probe "ecs update-service (skeleton)"         "aws ecs update-service --generate-cli-skeleton"
probe "ecs describe-services"                 "aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE"

echo "== Already used in Labs 1 to 4A =="
probe "ec2 describe-security-groups"          "aws ec2 describe-security-groups --max-items 1"
probe "ec2 describe-subnets"                  "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_A"
```

- Read each result as "the service answered", not "the call succeeded". `describe-listeners --load-balancer-arn probe` passes a non-ARN on purpose: a `ValidationError` about the ARN means ELBv2 is present. An unsupported service gives a connection error or `InvalidAction`.
- `describe-account-limits` shows the per-region caps on load balancers, target groups, listeners and rules.

**Expected result**

```text
== Elastic Load Balancing v2 ==
elbv2 describe-load-balancers                    SUPPORTED
elbv2 create-load-balancer (skeleton)            SUPPORTED
elbv2 describe-target-groups                     SUPPORTED
elbv2 create-target-group (skeleton)             SUPPORTED
elbv2 describe-listeners (bad arn)               SUPPORTED
elbv2 describe-account-limits                    SUPPORTED
== ECS integration ==
ecs update-service (skeleton)                    SUPPORTED
ecs describe-services                            SUPPORTED
== Already used in Labs 1 to 4A ==
ec2 describe-security-groups                     SUPPORTED
ec2 describe-subnets                             SUPPORTED
```

> Example output - this is the best case. Yours may well differ, and that is exactly why the probe
> exists.

**Verify:** decide which path you are on and write it at the top of `notes/lab-05-notes.md`; the lab report and the assessment both ask for it.

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | `describe-load-balancers` and both skeletons answer, and Step 5 later returns an ARN | Do every step as written |
| **B - control plane only** | Objects are created and describable, but targets never become `healthy` and Step 12's `curl` does not connect | Everything in this lab still works. Every proof here is built on control-plane fields, not on a served request. Record where target health stayed `initial` or `unused` and continue |
| **C - no ELBv2** | `describe-load-balancers` does not answer, or `create-load-balancer` fails with `InvalidAction` | Stop and tell your instructor. Do the concept reading in Section 1, Exercise 4 and Section 13.1 Task C, which need no emulator, and record the whole lab as conceptual |

!!! note "Floci Limitation - Elastic Load Balancing is the least reliably emulated service in this course"
    Depending on the build, ELBv2 is fully modelled, a control plane with no data path (the most likely case, and the one this lab is written for), or absent.

    Real AWS provisions nodes in each subnet in two to four minutes, publishes a resolving DNS name, health checks each target and forwards real requests.

    Nothing this lab asks you to prove depends on a served request: every object, the service's `loadBalancers` entry and the security group chain are observable control-plane facts. Step 12 tries the data path and gives a control-plane proof to record instead.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01 + lab-02 + lab-03 + lab-04 sourced
 ├── verify-lab-02.sh, verify-lab-03.sh and verify-lab-04.sh all FAIL=0
 ├── outputs/lab-05-pre-verify-04.txt captured, for comparison after Step 13
 ├── BOTH public subnets present, in TWO different Availability Zones
 └── support path recorded: A (full) / B (control plane only) / C (no ELBv2)
```

---

!!! info "Four objects, two health checks - read before Step 4"
    See [north-south traffic in 2.2](../unit2/topic2.md#north-south-getting-traffic-in) for the full explanation. The facts the next steps rely on:

    - **Load balancer** (DNS name, subnets, security group) → **listener** (one port and protocol, exactly one **default action**) → **rules** (condition + action, lowest priority number wins, first match) → **target group** (targets plus the **health check** - the health check lives here, not on the load balancer).
    - An ALB is layer 7 and has security groups; it terminates the connection, so the target sees the load balancer's address (hence `X-Forwarded-For`).
    - Fargate tasks use `awsvpc` and have no instance ID, so the target group **must** be `--target-type ip`. `instance` is accepted at creation and fails only at Step 10.
    - The container health check (Lab 04 revision 2, run inside the task) and the target group health check (run by the load balancer over the network) can disagree. ECS `HEALTHY` plus target `unhealthy` means the application is fine and the network path (usually Step 9's rule) is not.

    ```text
    usms-enrolment-alb                     the DNS name, the subnets, the security group
      └── listener  HTTP:80                the port a client connects to
            ├── rule priority 10           path /alb-health  -> fixed-response 200
            └── DEFAULT ACTION             -> forward to usms-enrolment-tg
                                                 |
                            usms-enrolment-tg    |    the health check lives HERE
                              target-type ip     |
                              HTTP:80            |
                              GET / every 30s    |
                                targets:  10.0.3.x:80   <- registered BY THE ECS SERVICE
                                          10.0.4.x:80   <- deregistered BY THE ECS SERVICE
    ```

---

### Step 4 - Create the load balancer's security group

The load balancer is its own tier, so it gets its own group: the only thing the internet may reach and the only thing that may reach the tasks. One group per tier, each sourced from the tier above.

**Command - part 1, the group**

```bash
ALB_SG=$(aws ec2 create-security-group \
  --group-name usms-alb-sg \
  --description "USMS enrolment load balancer: HTTP from the internet; forwards to usms-enrolment-sg" \
  --vpc-id "$USMS_VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=usms-alb-sg},{Key=Project,Value=USMS},{Key=Tier,Value=edge},{Key=Lab,Value=05}]' \
  --query 'GroupId' \
  --output text)

echo "ALB_SG = $ALB_SG"
```

**Command - part 2, the ingress rule**

```bash
cat > policies/usms-alb-sg-ingress.json << 'EOF'
[
  {
    "IpProtocol": "tcp",
    "FromPort": 80,
    "ToPort": 80,
    "IpRanges": [
      {
        "CidrIp": "0.0.0.0/0",
        "Description": "HTTP from the internet - this is an internet-facing load balancer and this rule is the reason it works"
      }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-alb-sg-ingress.json > /dev/null && echo "valid JSON"

aws ec2 authorize-security-group-ingress \
  --group-id "$ALB_SG" \
  --ip-permissions file://policies/usms-alb-sg-ingress.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' \
  --output text
```

- Quoted `<< 'EOF'`: this document has no variables. Step 9's document contains `$ALB_SG` and must use unquoted `<< EOF`. Ask: expand now, or never?
- `Tier=edge` separates internet-exposed resources from the `Tier=app` cluster in cost and security reviews.

!!! warning "This is the only `0.0.0.0/0` ingress rule in the whole course, and it is deliberate"
    An internet-facing load balancer that admits only a named group is useless. It is acceptable because of what is behind it: the load balancer terminates connections and forwards only to your target group, and the tasks admit only this group.

    On a real account, narrow it where you can (CDN ranges, campus network) and add HTTPS on 443.

**Expected result**

```text
ALB_SG = sg-0bb22cc33dd44ee55
valid JSON
sgr-0aabb11223344cc55
```

> Example output - your IDs will differ.

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$ALB_SG" \
  --query 'SecurityGroups[0].{Name:GroupName,VPC:VpcId,Inbound:IpPermissions[].{Port:FromPort,CIDR:IpRanges[0].CidrIp,FromGroup:UserIdGroupPairs[0].GroupId},OutboundRules:length(IpPermissionsEgress)}' \
  --output json
```

Exactly one inbound rule on port 80 with `CIDR` `0.0.0.0/0` and `FromGroup` `null`. `OutboundRules` is `1`: the default allow-all egress that lets the load balancer connect to targets.

✏️ **Your turn**

Add a second inbound rule to `usms-alb-sg` for tcp/443 from `0.0.0.0/0`, using a JSON document in
`policies/` rather than the shorthand form.

```text
Expected result:
usms-alb-sg has two inbound rules, on ports 80 and 443, both from 0.0.0.0/0.

Then answer in two sentences in notes/lab-05-notes.md:
The load balancer still will not serve a single HTTPS request. Name the TWO things
that are missing, and say which of the two AWS can give you for free and which one
you have to obtain from somewhere.
```

Hint: a security group rule opens a port; it does not make anything listen on it. Think about what an HTTPS listener needs that an HTTP one does not.

---

### Step 5 - Create the Application Load Balancer

The stable name. AWS places a **node** in each subnet you name and publishes one DNS name resolving to all of them. `internet-facing` gives the nodes public addresses, so the subnets need Lab 2's internet gateway route; two AZs is a hard requirement. (`internal` is the alternative; Exercise 4 argues for it.)

**Command - part 1, create it**

```bash
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name usms-enrolment-alb \
  --type application \
  --scheme internet-facing \
  --ip-address-type ipv4 \
  --subnets "$USMS_PUBLIC_SUBNET_A" "$USMS_PUBLIC_SUBNET_B" \
  --security-groups "$ALB_SG" \
  --tags Key=Name,Value=usms-enrolment-alb Key=Project,Value=USMS Key=Tier,Value=edge Key=Lab,Value=05 \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)

echo "ALB_ARN = $ALB_ARN"

ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].DNSName' --output text)

echo "ALB_DNS = $ALB_DNS"
```

```text
aws
 └── elbv2                        the SERVICE - Elastic Load Balancing, API version 2
      └── create-load-balancer    the OPERATION
           ├── --name             1 to 32 characters, alphanumeric and hyphens, no leading or
           │                      trailing hyphen. It becomes part of the ARN and part of the DNS name
           ├── --type             application | network | gateway
           ├── --scheme           internet-facing | internal
           ├── --ip-address-type  ipv4 | dualstack
           ├── --subnets          ONE PER AVAILABILITY ZONE, at least two, space separated
           ├── --security-groups  ALB only. A network load balancer takes none
           └── --tags             Key= / Value= with CAPITALS - the fourth convention in two labs
```

- `--tags` uses capitalised `Key=`/`Value=` (unlike ECS's `key=`/`value=` and EC2's `--tag-specifications`). Check with `aws elbv2 create-load-balancer help`.
- `--subnets` is space-separated, not comma-separated; `--generate-cli-skeleton` shows a parameter's shape.

**Expected result**

```text
ALB_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
ALB_DNS = usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com
```

> Example output - your ARN suffix and DNS name will differ, and on Floci the DNS name may take a
> different form entirely, such as one ending in `elb.localhost.localstack.cloud`. Record whichever you
> get.

The ARN suffix after `loadbalancer/` is `app/usms-enrolment-alb/<id>`. Exercise 5 needs it verbatim for Lab 06's `ResourceLabel`.

**Command - part 2, wait for it, then read it back**

```bash
aws elbv2 wait load-balancer-available --load-balancer-arns "$ALB_ARN" \
  && echo "load balancer available" \
  || echo "waiter did not complete - poll manually below (expected on some builds)"

for i in $(seq 1 10); do
  STATE=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
    --query 'LoadBalancers[0].State.Code' --output text)
  printf 'poll %2d  state=%s\n' "$i" "$STATE"
  [ "$STATE" = "active" ] && break
  sleep 10
done
```

A waiter polls until `State.Code` is `active`. Real AWS takes two to four minutes (`provisioning` to `active`); Floci is usually instant. If the waiter hangs over a minute, press ++ctrl+c++ and use the loop.

**Verify**

```bash
aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].{Name:LoadBalancerName,State:State.Code,Type:Type,Scheme:Scheme,VPC:VpcId,DNS:DNSName,IPType:IpAddressType,AZs:AvailabilityZones[].{Zone:ZoneName,Subnet:SubnetId},SGs:SecurityGroups}' \
  --output json
```

Check, in order:

1. `AZs` has **two** entries in **two different** zones. Same zone twice means real AWS would have refused; record it as a limitation and fix the subnets.
2. `Scheme` is `internet-facing`, `Type` is `application`. Neither can change after creation.
3. `SGs` contains `$ALB_SG` (changeable later with `set-security-groups`).
4. `State` is `active` (`provisioning` resolves; `failed` means check `State.Reason`).

**Command - part 3, a load balancer attribute worth setting deliberately**

```bash
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$ALB_ARN" \
  --attributes \
      Key=idle_timeout.timeout_seconds,Value=60 \
      Key=routing.http.drop_invalid_header_fields.enabled,Value=true \
  --query 'Attributes[?Key==`idle_timeout.timeout_seconds` || Key==`routing.http.drop_invalid_header_fields.enabled`]' \
  --output table \
  || echo "attribute modification not supported on this build - record it and continue"
```

- `idle_timeout.timeout_seconds`: how long an idle connection stays open. Responses slower than this get a `504`; keep the target's keep-alive **longer** than this or you get intermittent `502`s.
- `routing.http.drop_invalid_header_fields.enabled`: drops headers with invalid names; defaults to `false`, should be `true` on anything new.

**Checkpoint 2**

```text
usms-enrolment-alb   active
 ├── type            application   (layer 7; cannot be changed after creation)
 ├── scheme          internet-facing  (cannot be changed after creation)
 ├── nodes           usms-public-subnet-a (us-east-1a) + usms-public-subnet-b (us-east-1b)
 ├── security group  usms-alb-sg   in: tcp/80 from 0.0.0.0/0   out: allow all
 ├── DNS name        recorded in your notes
 ├── attributes      idle_timeout 60, drop_invalid_header_fields true
 └── listeners       NONE YET - this load balancer currently answers nothing
```

No listener yet means every connection is refused. Step 8 fixes it.

---

### Step 6 - Create the target group

The targets and the health check that decides which receive traffic. Lab 06's scaling policy names this object.

The five health check numbers all answer *how long does a broken task keep receiving traffic?*

| Field | Value here | What it means |
| --- | --- | --- |
| `--health-check-interval-seconds` | 30 | How often the load balancer probes each target |
| `--health-check-timeout-seconds` | 5 | How long it waits for a response before calling that probe a failure |
| `--unhealthy-threshold-count` | 2 | How many consecutive failed probes before the target is taken out |
| `--healthy-threshold-count` | 2 | How many consecutive successful probes before it is put back |
| `--matcher HttpCode=200` | 200 | Which response codes count as success |

Interval times unhealthy threshold: **a dead task keeps receiving requests for up to 60 seconds.** Faster checks remove broken targets sooner but risk removing healthy ones during a blip. `HttpCode=200` treats a redirect (`301`) as unhealthy; `200-399` is the deliberate widening. See [target group health settings](../unit7/topic1.md#target-group-health-settings).

```bash
TG_ARN=$(aws elbv2 create-target-group \
  --name usms-enrolment-tg \
  --protocol HTTP \
  --port 80 \
  --vpc-id "$USMS_VPC_ID" \
  --target-type ip \
  --health-check-protocol HTTP \
  --health-check-path / \
  --health-check-port traffic-port \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 2 \
  --matcher HttpCode=200 \
  --tags Key=Name,Value=usms-enrolment-tg Key=Project,Value=USMS Key=Tier,Value=app Key=Lab,Value=05 \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)

echo "TG_ARN = $TG_ARN"
```

- `--target-type ip`: mandatory for `awsvpc` tasks. The most important flag here.
- `--vpc-id`: binds the target group to `usms-vpc` permanently.
- `--port 80 --protocol HTTP`: how the load balancer talks to a **target**, independent of the listener's port.
- `--health-check-port traffic-port`: a literal keyword meaning "the port the target is registered on".

**Expected result**

```text
TG_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
```

> Example output - your ARN suffix will differ.

The suffix `targetgroup/usms-enrolment-tg/<id>` is the second half of Exercise 5's `ResourceLabel`.

**Verify**

```bash
aws elbv2 describe-target-groups --target-group-arns "$TG_ARN" \
  --query 'TargetGroups[0].{Name:TargetGroupName,Type:TargetType,Proto:Protocol,Port:Port,VPC:VpcId,HCProto:HealthCheckProtocol,HCPath:HealthCheckPath,HCPort:HealthCheckPort,Interval:HealthCheckIntervalSeconds,Timeout:HealthCheckTimeoutSeconds,Healthy:HealthyThresholdCount,Unhealthy:UnhealthyThresholdCount,Matcher:Matcher.HttpCode,LBs:length(LoadBalancerArns)}' \
  --output json
```

**Expected result**

```json
{
    "Name": "usms-enrolment-tg",
    "Type": "ip",
    "Proto": "HTTP",
    "Port": 80,
    "VPC": "vpc-0a1b2c3d4e5f67890",
    "HCProto": "HTTP",
    "HCPath": "/",
    "HCPort": "traffic-port",
    "Interval": 30,
    "Timeout": 5,
    "Healthy": 2,
    "Unhealthy": 2,
    "Matcher": "200",
    "LBs": 0
}
```

> Example output.

`Type` must be `ip` (it cannot change later). `LBs` is `0` until Step 8.

Confirm the target group is empty, which it should be and will remain until Step 10:

```bash
aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
  --query 'TargetHealthDescriptions' --output json
```

`[]` is correct. **Do not populate it by hand** with `register-targets`: the ECS service will deregister anything you add.

✏️ **Your turn**

Widen the health check so that redirects count as success, read it back, then put it exactly as it was.

```text
Expected result:
describe-target-groups shows Matcher 200-399 after the change and 200 after you
restore it. Both changes take effect immediately and neither requires recreating
anything.

Then answer in one sentence each in notes/lab-05-notes.md:
(a) Name one realistic application for which the strict 200 matcher would report a
    perfectly working service as unhealthy forever.
(b) Section 8's verification script asserts the matcher is 200. If you had left it at
    200-399, would that failure be a bug in your work or a bug in the script? Justify
    your answer in terms of what a verification script is FOR.
```

Hint: `aws elbv2 modify-target-group help` lists what can change after creation; compare it with `create-target-group`'s flags.

---

### Step 7 - Set the target group attribute that governs how a task dies

`deregistration_delay.timeout_seconds` decides what happens to in-flight requests when ECS stops a task. It is the load balancer half of a sequence whose ECS half you set in Lab 04:

```text
1. ECS decides to stop task T
2. ECS DEREGISTERS T from usms-enrolment-tg
3. The load balancer marks T as `draining`
     - it sends T no NEW requests
     - it lets requests ALREADY IN FLIGHT finish
     - it waits at most deregistration_delay.timeout_seconds        <- this step
4. When the delay expires (or all connections close), T is fully deregistered
5. ECS sends SIGTERM to the container
6. ECS waits stopTimeout seconds                                     <- Lab 04
7. ECS sends SIGKILL
```

| Timer | Where it is set | What it protects |
| --- | --- | --- |
| `deregistration_delay.timeout_seconds` | The target group, here | Requests already in flight from the load balancer |
| `stopTimeout` | The task definition, Lab 04 | The container's own graceful shutdown |
| `minimumHealthyPercent` | The service, Lab 04 Step 13 | Total capacity during a deployment |

The default is 300 seconds, far too long for a millisecond API. Set it slightly longer than the slowest legitimate request: 30 seconds here.

```bash
aws elbv2 modify-target-group-attributes \
  --target-group-arn "$TG_ARN" \
  --attributes \
      Key=deregistration_delay.timeout_seconds,Value=30 \
      Key=load_balancing.algorithm.type,Value=least_outstanding_requests \
  --query 'Attributes[?Key==`deregistration_delay.timeout_seconds` || Key==`load_balancing.algorithm.type`].[Key,Value]' \
  --output text

aws elbv2 describe-target-group-attributes --target-group-arn "$TG_ARN" \
  --query 'Attributes[].[Key,Value]' --output table
```

| Value | Behaviour | Suits |
| --- | --- | --- |
| `round_robin` | Each target in turn, regardless of what it is doing | Uniform, short requests. The default |
| `least_outstanding_requests` | The target with fewest requests currently open | Variable request durations, and any service where one slow request should not attract more |

- `least_outstanding_requests` routes around a slow-but-healthy target; round robin keeps feeding it.
- The first `--query` uses `||` (boolean or) inside a filter, with attribute names as backtick literals (Appendix).

**Expected result**

```text
deregistration_delay.timeout_seconds    30
load_balancing.algorithm.type   least_outstanding_requests
---------------------------------------------------------------------------
|                    DescribeTargetGroupAttributes                        |
+---------------------------------------------+---------------------------+
|  deregistration_delay.timeout_seconds        |  30                       |
|  stickiness.enabled                          |  false                    |
|  load_balancing.algorithm.type               |  least_outstanding_requests|
|  slow_start.duration_seconds                 |  0                        |
|  ...                                         |  ...                      |
+---------------------------------------------+---------------------------+
```

> Example output - the full attribute list is longer and varies by build.

**Verify:** `deregistration_delay.timeout_seconds` is `30`. If the call is rejected, record it as a limitation and continue; Section 8's script lists it among the known benign failures. `stickiness.enabled` `false` is correct for a stateless API; `slow_start.duration_seconds` `0` means a newly healthy target gets full traffic at once.

---

### Step 8 - Create the listener

The port clients connect to, and its default action. This turns a silent load balancer into one that answers.

**Command - part 1, the default action, as a document**

```bash
cat > templates/lab-05-listener-default-actions.json << EOF
[
  {
    "Type": "forward",
    "TargetGroupArn": "$TG_ARN"
  }
]
EOF

python3 -m json.tool templates/lab-05-listener-default-actions.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-05-listener-default-actions.json
```

Unquoted `<< EOF` so `$TG_ARN` expands at write time. `grep -c '\$'` must print **`0`**; anything else means an empty variable or a quoted heredoc.

**Command - part 2, create the listener**

```bash
LISTENER_ARN=$(aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTP \
  --port 80 \
  --default-actions file://templates/lab-05-listener-default-actions.json \
  --tags Key=Name,Value=usms-enrolment-listener Key=Project,Value=USMS Key=Lab,Value=05 \
  --query 'Listeners[0].ListenerArn' \
  --output text)

echo "LISTENER_ARN = $LISTENER_ARN"
```

`--default-actions` is a list of structures, so it is passed with `file://`; nested actions (Step 15) are unreadable as shorthand. A listener has exactly **one** default action.

**Expected result**

```text
valid JSON
0
LISTENER_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:listener/app/usms-enrolment-alb/50dc6c495c0c9188/f2f7dc8efc522ab2
```

> Example output. Notice that the listener ARN contains the load balancer's ARN suffix inside it -
> `app/usms-enrolment-alb/50dc...` followed by the listener's own identifier. ELBv2 ARNs nest, and that
> is occasionally useful for working out what belongs to what by eye.

**Verify**

```bash
aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[].{Port:Port,Proto:Protocol,DefaultActionType:DefaultActions[0].Type,Forwards:DefaultActions[0].TargetGroupArn,SSL:SslPolicy}' \
  --output json

aws elbv2 describe-target-groups --target-group-arns "$TG_ARN" \
  --query 'TargetGroups[0].{Name:TargetGroupName,AttachedToLoadBalancers:length(LoadBalancerArns)}' \
  --output json
```

Port `80`, `HTTP`, default action `forward` to `$TG_ARN`, `SSL` `null` (only HTTPS listeners have a TLS policy). `AttachedToLoadBalancers` is now **`1`**; on real AWS health checking starts here.

**Checkpoint 3**

```text
usms-enrolment-alb   active, internet-facing, application, 2 AZs
 ├── usms-alb-sg                     in: tcp/80 from 0.0.0.0/0
 └── listener  HTTP:80
      └── default action  forward -> usms-enrolment-tg
                                      ├── target-type   ip
                                      ├── HTTP:80, health check GET / every 30s, matcher 200
                                      ├── deregistration delay 30s
                                      ├── algorithm     least_outstanding_requests
                                      ├── attached to   1 load balancer
                                      └── targets       NONE YET  <- Step 10
```

Still missing: the tasks' firewall does not admit the load balancer (Step 9), and the service registers nothing yet (Step 10).

---

### Step 9 - Let the load balancer reach the tasks

`usms-enrolment-sg` admits tcp/80 only from `usms-app-sg`. Without this rule every target fails its health check with a timeout while looking healthy to ECS.

```bash
cat > policies/usms-enrolment-sg-ingress-alb.json << EOF
[
  {
    "IpProtocol": "tcp",
    "FromPort": 80,
    "ToPort": 80,
    "UserIdGroupPairs": [
      {
        "GroupId": "$ALB_SG",
        "Description": "HTTP from usms-alb-sg - the load balancer is the only client of the enrolment tasks"
      }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-enrolment-sg-ingress-alb.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-enrolment-sg-ingress-alb.json

aws ec2 authorize-security-group-ingress \
  --group-id "$USMS_ENROLMENT_SG" \
  --ip-permissions file://policies/usms-enrolment-sg-ingress-alb.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' \
  --output text
```

- Unquoted `<< EOF` because `$ALB_SG` must expand (contrast Step 4's quoted heredoc). `grep -c '\$'` must print `0`.
- Group-referenced because AWS chooses and changes the load balancer's node addresses.

**Expected result**

```text
valid JSON
0
sgr-0cc33dd44ee55ff66
```

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,Sources:UserIdGroupPairs[].GroupId,CIDRs:IpRanges[].CidrIp}' \
  --output json
```

**Expected result**

```json
[
    {
        "Port": 80,
        "Sources": [
            "sg-0123456789abcdef0",
            "sg-0bb22cc33dd44ee55"
        ],
        "CIDRs": []
    }
]
```

> Example output - your IDs will differ, and the two sources may appear in either order.

**Two** source groups on port 80 (`usms-app-sg` and `usms-alb-sg`), empty `CIDRs`. AWS merges them into one `IpPermission`, so Lab 04's check reading `UserIdGroupPairs[0]` now reads whichever comes first; Step 13 returns to this. Both paths coexisting is intended: build the new path, prove it, then remove the old one.

---

### Step 10 - Attach the existing service to the target group

From now on `usms-enrolment-svc` registers every task it starts and deregisters every task it stops. The `loadBalancers` entry has three fields:

```text
targetGroupArn   which target group to register into
containerName    WHICH CONTAINER in the task definition receives the traffic
containerPort    WHICH PORT on that container
```

`containerName` and `containerPort` are matched **by string** against a real `portMappings` entry in `usms-enrolment:2` (`enrolment-api`, `80`). A mismatch gives `InvalidParameterException` saying the container is not in the task definition.

**Command - part 1, the document**

```bash
cat > templates/lab-05-service-load-balancers.json << EOF
[
  {
    "targetGroupArn": "$TG_ARN",
    "containerName": "$USMS_ENROLMENT_CONTAINER",
    "containerPort": 80
  }
]
EOF

python3 -m json.tool templates/lab-05-service-load-balancers.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-05-service-load-balancers.json
cat templates/lab-05-service-load-balancers.json
```

`0` dollar signs, and `containerName` reads `enrolment-api` (not `usms-enrolment`, which is the task definition family).

**Command - part 2, attach it**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --load-balancers file://templates/lab-05-service-load-balancers.json \
  --health-check-grace-period-seconds 60 \
  --query 'service.{Name:serviceName,LB:loadBalancers,Grace:healthCheckGracePeriodSeconds,Deployments:length(deployments),TaskDef:taskDefinition}' \
  --output json
```

- `--load-balancers` triggers a new deployment: existing tasks cannot be registered retroactively, so they are replaced.
- `--health-check-grace-period-seconds 60` makes ECS ignore target health for each task's first 60 seconds. Without it, a slow-starting task is marked unhealthy and replaced, forever:

```text
task starts -> application takes 25 seconds to be ready
            -> load balancer probes at 30s intervals, gets no answer, marks it unhealthy
            -> ECS sees an unhealthy target and replaces the task
            -> the new task takes 25 seconds to be ready
            -> ...
```

Set it longer than the slowest cold start. The flag is only valid on a service with a load balancer.

!!! warning "If your build rejects `--load-balancers` on `update-service`"
    In-place load balancer updates are supported for the rolling (`ECS`) deployment controller Lab 04 Step 13 created, but some emulator builds lack them.

    If the call fails with `InvalidParameterException` or `UnsupportedFeatureException`, use the destructive recreate path below.

    ??? danger "Fallback only - recreate the service with the load balancer attached"
        !!! danger "Read before running any delete command"
            **What will be deleted:** the ECS service `usms-enrolment-svc` and its two running tasks.
            The task definition family, the cluster, both roles, the security group and the log group
            are untouched.

            **What depends on it:** Lab 06 registers a scalable target against a service **of this
            name**. Recreating it with the same name, same cluster, same task definition and same
            desired count preserves everything downstream. Recreating it with a different name breaks
            Lab 06, `configs/lab-04.env` and `verify-lab-04.sh` simultaneously.

            **Reversible?** The service object is not recoverable, but an identical one is three
            commands away, and every input to those commands is in `configs/lab-04.env`.

            **Effect on later labs:** none, **provided** the name, cluster, task definition and desired
            count are identical to Lab 04's.

        ```bash
        aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
          --desired-count 0 >/dev/null
        aws ecs wait services-stable --cluster "$USMS_ECS_CLUSTER" \
          --services "$USMS_ENROLMENT_SERVICE" || sleep 15
        aws ecs delete-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
          --force >/dev/null

        aws ecs create-service \
          --cluster "$USMS_ECS_CLUSTER" \
          --service-name "$USMS_ENROLMENT_SERVICE" \
          --task-definition usms-enrolment:2 \
          --desired-count "$USMS_ECS_DESIRED_BASELINE" \
          --launch-type FARGATE \
          --deployment-configuration file://templates/lab-04-deployment-config.json \
          --load-balancers file://templates/lab-05-service-load-balancers.json \
          --health-check-grace-period-seconds 60 \
          --network-configuration "awsvpcConfiguration={subnets=[$USMS_PRIVATE_SUBNET_A,$USMS_PRIVATE_SUBNET_B],securityGroups=[$USMS_ENROLMENT_SG],assignPublicIp=DISABLED}" \
          --enable-ecs-managed-tags \
          --propagate-tags SERVICE \
          --tags key=Name,value=usms-enrolment-svc key=Project,value=USMS key=Tier,value=app key=Lab,value=04 \
          --query 'service.serviceArn' --output text
        ```

        Every value comes from Lab 04 or `configs/lab-04.env`; nothing is renamed. Record that you took the fallback. `Lab=04` stays on the tag: the service is still Lab 04's object.

**Expected result**

```json
{
    "Name": "usms-enrolment-svc",
    "LB": [
        {
            "targetGroupArn": "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067",
            "containerName": "enrolment-api",
            "containerPort": 80
        }
    ],
    "Grace": 60,
    "Deployments": 2,
    "TaskDef": "arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:2"
}
```

> Example output - `Deployments: 2` means the roll has started. On a build that starts no containers it
> may be `1` immediately.

`LB` has one entry, `Grace` is `60`, and `TaskDef` is **unchanged** at `usms-enrolment:2`: where traffic comes from is a property of the service, not the blueprint.

---

### Step 11 - Watch the targets register, and read target health

The target group fills itself here, proving the service, not you, owns its contents.

| State | Meaning | Typical cause when unexpected |
| --- | --- | --- |
| `initial` | Registered; the load balancer has not completed enough health checks to decide | Perfectly normal for the first `interval x healthy_threshold` seconds |
| `healthy` | Passing its health check; receiving traffic | - |
| `unhealthy` | Failing its health check | The security group, the health check path, the matcher, or a genuinely broken application. In that order of likelihood |
| `draining` | Deregistering; finishing in-flight requests only | A deployment or a scale-in, in progress |
| `unused` | Registered, but nothing can send it traffic | No listener forwards to this target group, or the target group is not attached to a load balancer |

For `unused`, check the target group's `LoadBalancerArns` first. `Target.Id` for an `ip` target group is the task ENI's **address** (as in Lab 04 Step 12), not an instance ID or task ARN.

**Command - part 1, watch it fill**

```bash
for i in $(seq 1 12); do
  echo "--- poll $i ---"
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'TargetHealthDescriptions[].{Target:Target.Id,Port:Target.Port,AZ:Target.AvailabilityZone,State:TargetHealth.State,Reason:TargetHealth.Reason,Desc:TargetHealth.Description}' \
    --output table
  N=$(aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
        --query 'length(TargetHealthDescriptions)' --output text)
  [ "$N" -ge 2 ] && break
  sleep 10
done
```

**Expected result**

```text
--- poll 1 ---
-------------------------------------------------------------------------------------------
|                                  DescribeTargetHealth                                    |
+-------------+------+-------------+-----------+------------------+-----------------------+
|   Target    | Port |     AZ      |   State   |      Reason      |         Desc          |
+-------------+------+-------------+-----------+------------------+-----------------------+
|  10.0.3.117 |  80  | us-east-1a  |  initial  | Elb.Registration | Target registration...|
|  10.0.4.203 |  80  | us-east-1b  |  initial  | Elb.Registration | Target registration...|
+-------------+------+-------------+-----------+------------------+-----------------------+
--- poll 2 ---
...
|  10.0.3.117 |  80  | us-east-1a  |  healthy  |                  |                       |
|  10.0.4.203 |  80  | us-east-1b  |  healthy  |                  |                       |
+-------------+------+-------------+-----------+------------------+-----------------------+
```

> Example output - your addresses will differ, and on many builds the state will stay `initial` or the
> list will remain empty. Record what you see.

Two targets, **one per AZ**, with addresses in `10.0.3.0/24` and `10.0.4.0/24`: the public load balancer reaching tasks in the private subnets.

**Command - part 2, the service's own account of it**

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments),Rollout:deployments[0].rolloutState,LB:loadBalancers[0].targetGroupArn}' \
  --output json

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].events[0:6].[createdAt,message]' --output text
```

On real AWS the events read `registered 1 targets in target-group usms-enrolment-tg`, `has begun draining connections on 1 tasks`, then `has reached a steady state` (deployment finished). On Floci the list is shorter or empty; record which.

**Command - part 3, the two health opinions, side by side**

```bash
for t in $(aws ecs list-tasks --cluster "$USMS_ECS_CLUSTER" --service-name "$USMS_ENROLMENT_SERVICE" \
             --query 'taskArns[]' --output text); do
  aws ecs describe-tasks --cluster "$USMS_ECS_CLUSTER" --tasks "$t" \
    --query 'tasks[0].{Task:taskArn,ECSHealth:healthStatus,Last:lastStatus,IP:attachments[].details[?name==`privateIPv4Address`].value|[]|[0]}' \
    --output text
done

aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
  --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State]' --output text
```

Line up ECS's opinion of each task with the load balancer's opinion of each address:

| ECS `healthStatus` | Target health | Diagnosis |
| --- | --- | --- |
| `HEALTHY` | `healthy` | Working |
| `HEALTHY` | `unhealthy` | **The network path is broken.** Security group, subnet, or the health check path returning the wrong code |
| `UNHEALTHY` | `unhealthy` | The application is broken. Read the container logs |
| `UNKNOWN` | `healthy` | Not a fault. The task definition has no container health check |
| anything | `unused` | Nothing forwards to this target group |

Copy this table into `notes/lab-05-notes.md`: it is Review Question 4 and assessment Task C.

✏️ **Your turn**

Raise the service's desired count to 3, watch the target group, then put it back to 2.

```text
Expected result:
describe-target-health shows three targets and then two again, without you running
register-targets or deregister-targets even once. The third address is in whichever
private subnet keeps the AZ balance.

Then answer in one sentence in notes/lab-05-notes.md:
Lab 06 will move desiredCount automatically. Name the ONE thing you would have had
to do by hand after every single scaling event if the service did not register its
own targets.
```

Hint: Lab 04 Step 16 has the desired-count command.

**Checkpoint 4**

```text
usms-enrolment-svc   attached to the load balancer
 ├── loadBalancers[0]  targetGroupArn = usms-enrolment-tg
 │                     containerName  = enrolment-api   (matches usms-enrolment:2)
 │                     containerPort  = 80
 ├── healthCheckGracePeriodSeconds  60
 ├── taskDefinition   usms-enrolment:2  - UNCHANGED, no new revision registered
 └── usms-enrolment-tg
      ├── 10.0.3.x:80  us-east-1a   registered by the SERVICE
      ├── 10.0.4.x:80  us-east-1b   registered by the SERVICE
      └── state        healthy / initial / (empty, on builds with no data path)
```

---

### Step 12 - Prove the path, and be honest about which proof you got

A command that appears to succeed is not proof. Try the real request first; if your build has no data path, record the control-plane proof instead.

**Command - part 1, the data path**

```bash
echo "ALB DNS name: $ALB_DNS"

getent hosts "$ALB_DNS" 2>/dev/null || python3 -c "
import socket,sys
try:
    print(socket.gethostbyname_ex(sys.argv[1]))
except Exception as e:
    print('does not resolve:', e)
" "$ALB_DNS"

curl -s -o /dev/null -w 'http_code=%{http_code}  time_total=%{time_total}s\n' \
     --max-time 10 "http://$ALB_DNS/" \
  || echo "curl could not connect - expected on many builds; see part 2"
```

- Name resolution uses `getent`, falling back to Python's `socket` (portable across macOS and Linux).
- `curl -w` prints `%{http_code}` and `%{time_total}`; `--max-time 10` stops a hang. No `curl`? Use `wget -q -O /dev/null -T 10 "http://$ALB_DNS/" && echo ok`.

**Expected result, on a build with a working data path**

```text
ALB DNS name: usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com
('usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com', [], ['127.0.0.1'])
http_code=200  time_total=0.043s
```

> Example output. A `200` means a request travelled from your shell, through the listener, to a task in
> a private subnet, and back. That is the whole architecture, proven in one line.

**Expected result, on a build without one**

```text
ALB DNS name: usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com
does not resolve: [Errno -2] Name or service not known
curl could not connect - expected on many builds; see part 2
```

> Also example output, and also a perfectly acceptable result for this lab.

!!! note "Floci Limitation - the load balancer's data path"
    Floci runs no public DNS, and the course's compose file publishes only port `4566`. Some builds serve load balancers through `4566` under a `localhost.localstack.cloud` name; many serve no data path. The environment contract lists **no port range for Elastic Load Balancing**: do not invent or publish extra ports.

    Real AWS resolves the DNS name to the nodes' public addresses and forwards to a healthy target in milliseconds.

    Part 2 proves the same wiring from the control plane. Record which proof you obtained; claiming a `200` you did not see is worth negative marks.

**Command - part 2, the control-plane proof, which always works**

```bash
{
  echo "== 1. The listener a client would connect to =="
  aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
    --query 'Listeners[].[Protocol,Port,DefaultActions[0].Type,DefaultActions[0].TargetGroupArn]' \
    --output text

  echo
  echo "== 2. The target group that listener forwards to =="
  aws elbv2 describe-target-groups --target-group-arns "$TG_ARN" \
    --query 'TargetGroups[0].[TargetGroupName,TargetType,Protocol,Port,HealthCheckPath,VpcId]' \
    --output text

  echo
  echo "== 3. The targets in it, and which subnet each address belongs to =="
  for ip in $(aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
                --query 'TargetHealthDescriptions[].Target.Id' --output text); do
    printf '%-16s ' "$ip"
    case "$ip" in
      10.0.3.*) echo "usms-private-subnet-a  (us-east-1a)" ;;
      10.0.4.*) echo "usms-private-subnet-b  (us-east-1b)" ;;
      *)        echo "NOT in a Lab 02 private subnet - investigate" ;;
    esac
  done

  echo
  echo "== 4. The service that put them there =="
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[serviceName,loadBalancers[0].targetGroupArn,loadBalancers[0].containerName,loadBalancers[0].containerPort,healthCheckGracePeriodSeconds]' \
    --output text

  echo
  echo "== 5. The firewall that lets step 1 reach step 3 =="
  aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
    --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text
  echo "   (usms-alb-sg is $ALB_SG)"
} | tee outputs/lab-05-path-proof.txt
```

**Verify:** read the five blocks as one chain, each link naming the next:

```text
client -> listener HTTP:80        (block 1)
       -> forward action names    usms-enrolment-tg          (block 1 -> 2)
       -> target group holds      10.0.3.x:80, 10.0.4.x:80   (block 3)
       -> those addresses are in  Lab 02's private subnets   (block 3)
       -> they got there because  usms-enrolment-svc registers them (block 4)
       -> and are reachable because usms-enrolment-sg admits usms-alb-sg (block 5)
```

Empty block 3 means your build started no containers; the chain still holds from blocks 1, 2, 4 and 5, and you say so. Block 5 without `$ALB_SG` is a real fault: go back to Step 9. Keep `outputs/lab-05-path-proof.txt` for the report and Section 13.1 Task D.

---

### Step 13 - The cutover: remove the direct path

Having proved the load-balanced path, remove the direct one. A migration that leaves the old path in place is a system with two behaviours, one untested.

!!! danger "Read before running any delete command"
    **What will be deleted:** one inbound rule on `usms-enrolment-sg` - the tcp/80 rule sourced from
    `usms-app-sg`, written in Lab 04 Step 9. Not the group, not any rule you wrote today, and not any
    task.

    **What depends on it:** anything calling the enrolment tasks by address rather than through the load
    balancer. In this architecture that is nothing, because Step 12 proved the load-balanced path first.
    On a real system it would be whatever you had not finished migrating, which is why the order of
    Steps 9, 12 and 13 is the whole lesson.

    **Reversible?** Yes, completely. `policies/usms-enrolment-sg-ingress.json` from Lab 04 is still in
    your repository and one `authorize-security-group-ingress` call puts the rule back.

    **Effect on later labs:** `scripts/utilities/verify-lab-04.sh` will report exactly one failure
    afterwards - `usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)` - because that check
    encodes the pre-load-balancer architecture. That is expected and is discussed below. Lab 06 is
    unaffected: it never reads that rule.

**Command - part 1, find the exact rule, and confirm it before removing it**

```bash
aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$USMS_ENROLMENT_SG" \
  --query 'SecurityGroupRules[].{Id:SecurityGroupRuleId,Egress:IsEgress,Port:FromPort,CIDR:CidrIpv4,FromGroup:ReferencedGroupInfo.GroupId,Desc:Description}' \
  --output table

OLD_RULE_ID=$(aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$USMS_ENROLMENT_SG" \
  --query "SecurityGroupRules[?IsEgress==\`false\` && ReferencedGroupInfo.GroupId=='$USMS_APP_SG'].SecurityGroupRuleId | [0]" \
  --output text)

echo "rule to remove: $OLD_RULE_ID"
```

- `describe-security-group-rules` gives each rule its own ID, the only view where the two port-80 sources are separable.
- The filter joins two conditions with `&&`: JSON literals (`false`) in backticks, raw strings in single quotes. The query is double-quoted so `$USMS_APP_SG` expands, so the backticks are escaped as `` \` ``.

`OLD_RULE_ID` must be a real `sgr-` ID, **not** `None`. `None` means the rule is already gone or `$USMS_APP_SG` is empty in this terminal; check the variable first.

**Command - part 2, remove it**

```bash
aws ec2 revoke-security-group-ingress \
  --group-id "$USMS_ENROLMENT_SG" \
  --security-group-rule-ids "$OLD_RULE_ID" \
  --query 'Return' --output text
```

**Expected result**

```text
True
```

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,Sources:UserIdGroupPairs[].GroupId,CIDRs:IpRanges[].CidrIp}' \
  --output json

echo "usms-alb-sg = $ALB_SG"
echo "usms-app-sg = $USMS_APP_SG   (must NOT appear above)"
```

Exactly **one** source on port 80, `$ALB_SG`; no `$USMS_APP_SG`; empty `CIDRs`. Now *the only thing that can open a connection to an enrolment task is the load balancer*.

**Command - part 3, look at what this did to Lab 04's script**

```bash
./scripts/utilities/verify-lab-04.sh | tee outputs/lab-05-post-verify-04.txt | tail -5

echo "== what changed =="
diff outputs/lab-05-pre-verify-04.txt outputs/lab-05-post-verify-04.txt
```

**Expected result**

```text
  ok   usms-enrolment-sg exists
  FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
  ok   usms-enrolment-sg admits NOTHING from 0.0.0.0/0

PASS=48  FAIL=1
== what changed ==
<   ok   usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
---
>   FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
< PASS=49  FAIL=0
---
> PASS=48  FAIL=1
```

> Example output.

The `diff` shows **exactly one** check changing state, `49/0` to `48/1`. Any other changed line is an accident; investigate. The script failed correctly: the architecture legitimately changed. The assessment expects you to name all three responses:

| Response | When it is right |
| --- | --- |
| Leave it, and document the expected failure | Now. Lab 04's script is a record of what Lab 04 built, and rewriting history to make a script green is a bad habit |
| Update the check to assert the new source group | Exercise 2. This is what you would do on a real system, in the same commit as the change |
| Delete the check | Almost never. The property still matters; only the expected value changed |

From here, `verify-lab-05.sh` (Section 8) is the script of record; it asserts the load balancer's group is a source and the web tier's is not.

---

### Step 14 - Deploy behind a load balancer, and watch a target drain

With a target group in front, a deployment gains two states and one timer:

```text
minimumHealthyPercent 100, maximumPercent 200, desiredCount 2, deregistration delay 30

  step 0  [ :2 A healthy ] [ :2 B healthy ]                       2 healthy targets
  step 1  [ A ] [ B ] [ C starting ]                              C is registered -> `initial`
  step 2  [ A ] [ B ] [ C ]                                       grace period; ECS ignores C's health
  step 3  [ A ] [ B ] [ C healthy ]                               C passes 2 checks -> receiving traffic
  step 4  [ A draining ] [ B ] [ C ]                              A deregistered; NO NEW requests to A
  step 5  [ A draining ] [ B ] [ C ]                              up to 30 seconds for A's in-flight work
  step 6          [ B ] [ C ] [ D starting ]                      A gets SIGTERM, then stops
  step 7          [ B draining ] [ C ] [ D healthy ]
  step 8                  [ C ] [ D ]                             done
```

The health check becomes a deployment gate (no traffic until healthy), and old tasks drain before being killed. That is why a load-balanced deployment can be zero-downtime.

**Command - part 1, record the state before**

```bash
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[taskDefinition,desiredCount,runningCount]' --output text
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'sort(TargetHealthDescriptions[].Target.Id)' --output text
} > outputs/lab-05-pre-deploy.txt

cat outputs/lab-05-pre-deploy.txt
```

**Command - part 2, force a deployment with no change at all**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --force-new-deployment \
  --query 'service.{TaskDef:taskDefinition,Deployments:length(deployments)}' \
  --output json
```

`--force-new-deployment` replaces every task with an identical one from the same revision, isolating the deployment mechanism. Real uses: a moved image tag, a rotated secret, cycling drifted tasks.

**Command - part 3, watch both sides at once**

```bash
for i in $(seq 1 15); do
  echo "--- poll $i ---"
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].deployments[].{Status:status,Desired:desiredCount,Running:runningCount,Pending:pendingCount,Rollout:rolloutState}' \
    --output text
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State]' --output text
  N=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
        --query 'length(deployments)' --output text)
  [ "$N" = "1" ] && break
  sleep 8
done
```

**Expected result**

```text
--- poll 1 ---
PRIMARY 2   1   1   IN_PROGRESS
ACTIVE  2   2   0   COMPLETED
10.0.3.117      healthy
10.0.4.203      healthy
10.0.3.244      initial
--- poll 2 ---
PRIMARY 2   2   0   IN_PROGRESS
ACTIVE  2   1   0   COMPLETED
10.0.3.117      draining
10.0.4.203      healthy
10.0.3.244      healthy
--- poll 3 ---
PRIMARY 2   2   0   COMPLETED
10.0.4.203      healthy
10.0.3.244      healthy
```

> Example output - the exact interleave depends on when you polled, and on a build with no data path
> the target list may not change at all. A single frame containing `draining` next to `healthy` is the
> thing worth screenshotting.

Look for `initial`, `healthy` and `draining` across the polls.

**Command - part 4, confirm**

```bash
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[taskDefinition,desiredCount,runningCount]' --output text
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'sort(TargetHealthDescriptions[].Target.Id)' --output text
} > outputs/lab-05-post-deploy.txt

paste outputs/lab-05-pre-deploy.txt outputs/lab-05-post-deploy.txt
```

Same task definition and counts on both sides, **different addresses**. If your build never changes the target list, check that task ARNs changed with `aws ecs list-tasks` and record that instead.

**Checkpoint 5**

```text
Deployment behind a load balancer, observed
 ├── --force-new-deployment      same revision, new tasks
 ├── target states seen          initial -> healthy -> draining
 ├── deregistration delay        30s, so in-flight requests survive the swap
 ├── grace period                60s, so a slow start is not mistaken for a failure
 └── pre/post address lists      different addresses, identical configuration
```

---

### Step 15 - Add a listener rule

Anything beyond "send it all to one place" is a rule. This one has a non-forward action, so the mechanism is clear before you need it.

```text
request arrives on listener HTTP:80
  |
  +-- rule priority 10   condition matches?  -> run its action, STOP
  +-- rule priority 20   condition matches?  -> run its action, STOP
  +-- rule priority 30   ...
  |
  +-- no rule matched    -> run the listener's DEFAULT ACTION
```

Lowest number first, first match wins; priorities are unique per listener, 1 to 50000. Leave gaps (10, 20, 30) so you can insert rules later. The default action is not a rule and always runs last.

| Type | What it does | Typical use |
| --- | --- | --- |
| `forward` | Send to one target group, or several with weights | Normal routing; weighted forwarding is how blue/green and canary releases are done |
| `redirect` | Return a 301 or 302 with a rewritten URL | The HTTP-to-HTTPS redirect that every public site needs |
| `fixed-response` | Return a status code and body without contacting any target | Health endpoints, maintenance pages, and blocking a path outright |
| `authenticate-oidc` / `authenticate-cognito` | Require a login before forwarding | Putting an identity provider in front of an app that has none |

A `fixed-response` proves the mechanism with no second target group: if `/alb-health` returns 200 while `/` reaches a task, the rule fired.

**Command - part 1, the condition and the action**

```bash
cat > templates/lab-05-rule-conditions.json << 'EOF'
[
  {
    "Field": "path-pattern",
    "PathPatternConfig": {
      "Values": ["/alb-health", "/alb-health/*"]
    }
  }
]
EOF

cat > templates/lab-05-rule-actions.json << 'EOF'
[
  {
    "Type": "fixed-response",
    "FixedResponseConfig": {
      "StatusCode": "200",
      "ContentType": "text/plain",
      "MessageBody": "usms-enrolment-alb ok\n"
    }
  }
]
EOF

python3 -m json.tool templates/lab-05-rule-conditions.json > /dev/null && echo "conditions valid"
python3 -m json.tool templates/lab-05-rule-actions.json    > /dev/null && echo "actions valid"
```

- Both heredocs are quoted `<< 'EOF'`: no variables.
- `StatusCode` is a **string** `"200"` (like Lab 04's `"cpu": "256"`).
- Two patterns, because `/alb-health*` would also match `/alb-healthcheck-internal`.

**Command - part 2, create the rule**

```bash
RULE_ARN=$(aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority 10 \
  --conditions file://templates/lab-05-rule-conditions.json \
  --actions file://templates/lab-05-rule-actions.json \
  --tags Key=Name,Value=usms-enrolment-health-rule Key=Project,Value=USMS Key=Lab,Value=05 \
  --query 'Rules[0].RuleArn' \
  --output text)

echo "RULE_ARN = $RULE_ARN"
```

**Expected result**

```text
conditions valid
actions valid
RULE_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:listener-rule/app/usms-enrolment-alb/50dc6c495c0c9188/f2f7dc8efc522ab2/9683b2d02a6cba8d
```

> Example output. Four identifiers nested in one ARN: the load balancer, its listener, and the rule.

**Verify**

```bash
aws elbv2 describe-rules --listener-arn "$LISTENER_ARN" \
  --query 'Rules[].{Priority:Priority,Default:IsDefault,Condition:Conditions[0].Field,Values:Conditions[0].Values,Action:Actions[0].Type,Status:Actions[0].FixedResponseConfig.StatusCode,TargetGroup:Actions[0].TargetGroupArn}' \
  --output json
```

**Expected result**

```json
[
    {
        "Priority": "10",
        "Default": false,
        "Condition": "path-pattern",
        "Values": [ "/alb-health", "/alb-health/*" ],
        "Action": "fixed-response",
        "Status": "200",
        "TargetGroup": null
    },
    {
        "Priority": "default",
        "Default": true,
        "Condition": null,
        "Values": null,
        "Action": "forward",
        "Status": null,
        "TargetGroup": "arn:aws:elasticloadbalancing:...:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067"
    }
]
```

> Example output.

Two entries: your rule (`Default` false, priority `10`) and the default action, listed with `Priority` `"default"` and `IsDefault` true so one call shows the whole decision table.

**Command - part 3, test it if you have a data path**

```bash
curl -s -o /dev/null -w '/            -> %{http_code}\n' --max-time 10 "http://$ALB_DNS/" || true
curl -s -w '/alb-health  -> %{http_code}  body: %{size_download} bytes\n' --max-time 10 \
     "http://$ALB_DNS/alb-health" || true
```

If both answer, the second returned without any task: the rule fired first. If neither answers, the `describe-rules` output is your evidence.

**Checkpoint 6**

```text
usms-enrolment-alb
 └── listener  HTTP:80
      ├── rule priority 10   path-pattern /alb-health, /alb-health/*
      │                       -> fixed-response 200 text/plain, no target involved
      └── default action      -> forward to usms-enrolment-tg
                                  └── 2 targets, registered by usms-enrolment-svc
```

---

### Step 16 - Prove the whole thing survives a restart

The create, perturb, read-back proof (as in Lab 04 Step 18), across ELBv2, ECS and EC2. A build that persisted two of the three would leave the service naming a target group that no longer exists.

**Command - part 1, record the truth**

```bash
{
  aws elbv2 describe-load-balancers --names usms-enrolment-alb \
    --query 'LoadBalancers[0].[LoadBalancerName,Scheme,Type,State.Code,length(AvailabilityZones),length(SecurityGroups)]' --output text
  aws elbv2 describe-target-groups --names usms-enrolment-tg \
    --query 'TargetGroups[0].[TargetGroupName,TargetType,Protocol,Port,HealthCheckPath,Matcher.HttpCode,HealthCheckIntervalSeconds,UnhealthyThresholdCount]' --output text
  aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
    --query 'sort_by(Listeners,&Port)[].[Port,Protocol,DefaultActions[0].Type]' --output text
  aws elbv2 describe-rules --listener-arn "$LISTENER_ARN" \
    --query 'sort_by(Rules,&Priority)[].[Priority,Actions[0].Type]' --output text
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[serviceName,status,desiredCount,loadBalancers[0].containerName,loadBalancers[0].containerPort,healthCheckGracePeriodSeconds]' --output text
  aws ec2 describe-security-groups --group-ids "$ALB_SG" \
    --query 'SecurityGroups[0].[GroupName,IpPermissions[0].FromPort,IpPermissions[0].IpRanges[0].CidrIp]' --output text
  aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
    --query 'SecurityGroups[0].[GroupName,length(IpPermissions[0].UserIdGroupPairs)]' --output text
} > outputs/lab-05-pre-restart.txt

cat outputs/lab-05-pre-restart.txt
```

**Command - part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
source configs/lab-02.env
source configs/lab-04.env
```

`floci-down.sh` is `docker compose stop`: state is kept. Never `docker compose down -v`.

**Command - part 3, read it back, deriving every ARN from the API**

```bash
ALB_ARN=$(aws elbv2 describe-load-balancers --names usms-enrolment-alb \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
TG_ARN=$(aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text)
ALB_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-alb-sg" \
  --query 'SecurityGroups[0].GroupId' --output text)

echo "re-derived:"
printf '  %s\n' "$ALB_ARN" "$TG_ARN" "$LISTENER_ARN" "$ALB_SG"

{
  aws elbv2 describe-load-balancers --names usms-enrolment-alb \
    --query 'LoadBalancers[0].[LoadBalancerName,Scheme,Type,State.Code,length(AvailabilityZones),length(SecurityGroups)]' --output text
  aws elbv2 describe-target-groups --names usms-enrolment-tg \
    --query 'TargetGroups[0].[TargetGroupName,TargetType,Protocol,Port,HealthCheckPath,Matcher.HttpCode,HealthCheckIntervalSeconds,UnhealthyThresholdCount]' --output text
  aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" \
    --query 'sort_by(Listeners,&Port)[].[Port,Protocol,DefaultActions[0].Type]' --output text
  aws elbv2 describe-rules --listener-arn "$LISTENER_ARN" \
    --query 'sort_by(Rules,&Priority)[].[Priority,Actions[0].Type]' --output text
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[serviceName,status,desiredCount,loadBalancers[0].containerName,loadBalancers[0].containerPort,healthCheckGracePeriodSeconds]' --output text
  aws ec2 describe-security-groups --group-ids "$ALB_SG" \
    --query 'SecurityGroups[0].[GroupName,IpPermissions[0].FromPort,IpPermissions[0].IpRanges[0].CidrIp]' --output text
  aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
    --query 'SecurityGroups[0].[GroupName,length(IpPermissions[0].UserIdGroupPairs)]' --output text
} > outputs/lab-05-post-restart.txt

diff outputs/lab-05-pre-restart.txt outputs/lab-05-post-restart.txt \
  && echo "PERSISTENCE PROVEN: the load balancer, its two Availability Zones, its security group, the target group with its full health check configuration, the listener, the rule, the service's loadBalancers entry and the grace period are all unchanged" \
  || echo "PERSISTENCE FAILED: read the diff above, then run ./scripts/utilities/floci-storage-check.sh"
```

- Every ARN is **re-derived from the API**; reusing shell variables would only prove Bash remembers strings (Lab 1 Step 14).
- `--names` on the two read-only calls is the way back in; listeners have no name, so they are found by walking down from the load balancer and filtering by port.
- `sort_by(Listeners,&Port)`: `&` makes an expression reference; sorting avoids a false `diff` from reordering.
- `runningCount` is deliberately excluded: it may legitimately move. Compare configuration, not the weather.

**Expected result**

```text
re-derived:
  arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
  arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
  arn:aws:elasticloadbalancing:us-east-1:000000000000:listener/app/usms-enrolment-alb/50dc6c495c0c9188/f2f7dc8efc522ab2
  sg-0bb22cc33dd44ee55
PERSISTENCE PROVEN: the load balancer, its two Availability Zones, its security group, the target group with its full health check configuration, the listener, the rule, the service's loadBalancers entry and the grace period are all unchanged
```

On `PERSISTENCE FAILED`, read the `diff` first (it names which of the seven facts was lost), then run `./scripts/utilities/floci-storage-check.sh`.

**Checkpoint 7**

```text
Persistence proven for Lab 05
 ├── every ARN re-derived from the API by name or by walking down from a parent
 ├── load balancer: scheme, type, 2 AZs, 1 security group - unchanged
 ├── target group: type ip, health check path, matcher, interval, threshold - unchanged
 ├── listener and its rule - unchanged, in priority order
 ├── service loadBalancers entry and grace period - unchanged
 └── both security groups - unchanged, including the Step 13 cutover
```

---

### Step 17 - Close the loop, and audit what this lab created

Resolve both ends of the new chain to real objects, so the security posture is demonstrated, not asserted.

```bash
source configs/lab-03.env

echo "== 1. Who can reach the load balancer? =="
aws ec2 describe-security-groups --group-ids "$ALB_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,FromCIDR:IpRanges[].CidrIp,FromGroup:UserIdGroupPairs[].GroupId}' \
  --output json

echo
echo "== 2. Who can reach the tasks? =="
TASK_SOURCE=$(aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[0].UserIdGroupPairs[0].GroupId' --output text)
echo "source group: $TASK_SOURCE"

if [ "$TASK_SOURCE" = "$ALB_SG" ]; then
  echo "CUTOVER CONFIRMED: the ONLY thing that may open a connection to an enrolment task is usms-alb-sg"
else
  echo "MISMATCH: expected $ALB_SG (usms-alb-sg), found $TASK_SOURCE - re-read Steps 9 and 13"
fi

echo
echo "== 3. And who is the client of the load balancer, in the story? =="
aws ec2 describe-instances \
  --filters "Name=instance.group-id,Values=$USMS_APP_SG" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value,Id:InstanceId,Subnet:SubnetId}' \
  --output table

CARRIER=$(aws ec2 describe-instances \
  --filters "Name=instance.group-id,Values=$USMS_APP_SG" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

if [ "$CARRIER" = "$USMS_WEB_INSTANCE" ]; then
  echo "LOOP CLOSED: usms-web-01 ($CARRIER) still carries usms-app-sg, but now calls $ALB_DNS instead of a task address"
else
  echo "NOTE: usms-app-sg is carried by $CARRIER; lab-03.env records $USMS_WEB_INSTANCE"
fi

echo
echo "== 4. Audit: everything this lab tagged Lab=05 =="
aws ec2 describe-security-groups --filters "Name=tag:Lab,Values=05" \
  --query 'SecurityGroups[].[GroupName,GroupId]' --output text
aws elbv2 describe-tags --resource-arns "$ALB_ARN" "$TG_ARN" \
  --query 'TagDescriptions[].{Resource:ResourceArn,Tags:Tags[?Key==`Lab`].Value|[0]}' \
  --output table \
  || echo "elbv2 describe-tags not supported on this build - record it and continue"
```

- Block 2 is an equality test: "only the load balancer can reach the tasks" is printed as true or false.
- Block 3: `usms-web-01` still carries `usms-app-sg`, which no longer grants anything on the tasks. A security group is a name other rules refer to, not a property of the instance.
- `elbv2 describe-tags --resource-arns` takes several ARNs in one call: the bulk way to audit ELBv2 tags.

**Expected result**

```text
== 1. Who can reach the load balancer? ==
[
    {
        "Port": 80,
        "FromCIDR": [ "0.0.0.0/0" ],
        "FromGroup": []
    }
]

== 2. Who can reach the tasks? ==
source group: sg-0bb22cc33dd44ee55
CUTOVER CONFIRMED: the ONLY thing that may open a connection to an enrolment task is usms-alb-sg

== 3. And who is the client of the load balancer, in the story? ==
------------------------------------------------------------------------
|                          DescribeInstances                           |
+---------------+----------------------+-------------------------------+
|      Id       |         Name         |            Subnet             |
+---------------+----------------------+-------------------------------+
| i-0123456...  |  usms-web-01         |  subnet-01234abcd5678ef90     |
+---------------+----------------------+-------------------------------+
LOOP CLOSED: usms-web-01 (i-0123456789abcdef0) still carries usms-app-sg, but now calls usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com instead of a task address

== 4. Audit: everything this lab tagged Lab=05 ==
usms-alb-sg     sg-0bb22cc33dd44ee55
------------------------------------------------------------
|                       DescribeTags                       |
+-------------------------------------------+-------------+
|                 Resource                  |    Tags     |
+-------------------------------------------+-------------+
|  arn:aws:elasticloadbalancing:...alb/...  |  05        |
|  arn:aws:elasticloadbalancing:...tg/...   |  05        |
+-------------------------------------------+-------------+
```

> Example output - your IDs will differ.

You want `CUTOVER CONFIRMED` and `LOOP CLOSED`. `MISMATCH` is a real fault. A `NOTE` usually means Lab 3's instance was relaunched, or Lab 3 Step 18's "Your turn" left two instances with `usms-app-sg` and `[0]` picked the other (benign); say which in your report. If an ELBv2 resource shows no tags, add them with `aws elbv2 add-tags --resource-arns ... --tags Key=Lab,Value=05` and record it.

---

### Step 18 - Write `configs/lab-05.env`

Lab 06 needs three of this lab's ARNs. Record them **by lookup, not from variables**, so a populated value proves the resource exists.

```bash
cat > configs/lab-05.env << EOF
# Lab 05 - ECS service behind an Application Load Balancer
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs and ARNs only. NO SECRETS. Safe to commit.
#
# Sourced alongside lab-01/02/03/04. Lab 06 sources this
# file for the target group its ALBRequestCountPerTarget policy names.

export USMS_ALB_NAME=usms-enrolment-alb
export USMS_ALB_ARN=$(aws elbv2 describe-load-balancers --names usms-enrolment-alb \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
export USMS_ALB_DNS=$(aws elbv2 describe-load-balancers --names usms-enrolment-alb \
  --query 'LoadBalancers[0].DNSName' --output text)
export USMS_ALB_SCHEME=$(aws elbv2 describe-load-balancers --names usms-enrolment-alb \
  --query 'LoadBalancers[0].Scheme' --output text)
export USMS_ALB_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-alb-sg" \
  --query 'SecurityGroups[0].GroupId' --output text)

export USMS_TG_NAME=usms-enrolment-tg
export USMS_TG_ARN=$(aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
export USMS_TG_TARGET_TYPE=$(aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].TargetType' --output text)
export USMS_TG_HEALTH_PATH=$(aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].HealthCheckPath' --output text)

export USMS_ALB_LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn "$(aws elbv2 describe-load-balancers --names usms-enrolment-alb \
     --query 'LoadBalancers[0].LoadBalancerArn' --output text)" \
  --query 'Listeners[?Port==\`80\`].ListenerArn | [0]' --output text)

export USMS_ALB_LISTENER_PORT=80
export USMS_ALB_HEALTH_RULE_PATH=/alb-health

export USMS_SVC_LB_CONTAINER=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].loadBalancers[0].containerName' --output text)
export USMS_SVC_LB_PORT=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].loadBalancers[0].containerPort' --output text)
export USMS_SVC_GRACE_PERIOD=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].healthCheckGracePeriodSeconds' --output text)
EOF

grep -n 'export .*=$\|None' configs/lab-05.env || echo "all values populated"
```

- Unquoted `<< EOF` so every `$(...)` runs now; quoted, the file would re-run thirteen API calls in every new terminal (contrast the quoted policy heredocs).
- The listener line nests a command substitution (no `describe-listeners --names`), and escapes the JMESPath backticks as ``\` ``; unescaped, the shell runs `80` as a command and the variable is empty.
- `USMS_SVC_GRACE_PERIOD` is read back, not hard-coded, so a failed attachment shows as `None`.

**Verify**

```bash
source configs/lab-05.env

printf '%-26s %s\n' \
  "alb name"        "$USMS_ALB_NAME" \
  "alb scheme"      "$USMS_ALB_SCHEME" \
  "alb dns"         "$USMS_ALB_DNS" \
  "alb sg"          "$USMS_ALB_SG" \
  "target group"    "$USMS_TG_NAME" \
  "target type"     "$USMS_TG_TARGET_TYPE" \
  "health path"     "$USMS_TG_HEALTH_PATH" \
  "listener"        "$USMS_ALB_LISTENER_ARN" \
  "lb container"    "$USMS_SVC_LB_CONTAINER" \
  "lb port"         "$USMS_SVC_LB_PORT" \
  "grace period"    "$USMS_SVC_GRACE_PERIOD"

grep -c '^export' configs/lab-05.env
```

You want `all values populated`, eleven non-empty lines and **15** exports; `target type` `ip`, `lb container` `enrolment-api`, `grace period` `60`. A `None` means a resource is missing or a step did not take; find it now.

---

### Step 19 - Commit

Look first, stage explicitly, then commit.

**Command - part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-05-path-proof.txt
git ls-files outputs/
```

Before typing anything else:

- Nothing under `outputs/` and no root `.env` in `git status --short`; `configs/lab-05.env` **does** appear (no secrets).
- `git check-ignore -v` names the rule and line. **Silence means the file is not ignored**: fix `.gitignore` before committing anything.
- `git ls-files outputs/` lists only `outputs/.gitkeep`.

**Expected result**

```text
.gitignore:7:outputs/*  outputs/lab-05-path-proof.txt
outputs/.gitkeep
```

> Example output - your line number may differ.

The rule must be `outputs/*` with `!outputs/.gitkeep`, never `outputs/` (Git cannot re-include a file under an excluded directory).

**Command - part 2, commit**

```bash
git add labs/lab-05-ecs-alb/ \
        configs/lab-05.env \
        policies/usms-alb-sg-ingress.json \
        policies/usms-enrolment-sg-ingress-alb.json \
        templates/lab-05-listener-default-actions.json \
        templates/lab-05-rule-conditions.json \
        templates/lab-05-rule-actions.json \
        templates/lab-05-service-load-balancers.json \
        scripts/utilities/verify-lab-05.sh \
        scripts/cleanup/lab-05-cleanup.sh

git status --short

git commit -m "Lab 05: USMS enrolment service behind an Application Load Balancer - ALB, target group, listener, rule, service attachment and the security cutover"

git log --oneline -6
```

Name paths explicitly; `git add -A` is how an un-ignored secret reaches a remote. The two script paths exist only after Section 8; if you commit first, drop them and add them in a second commit.

**Expected result**

```text
[main 3b71f04] Lab 05: USMS enrolment service behind an Application Load Balancer - ALB, target group, listener, rule, service attachment and the security cutover
 10 files changed, 312 insertions(+)
```

> Example output - your hash and counts will differ.

**Checkpoint 8**

```text
Lab 05 recorded
 ├── configs/lab-05.env       committed, 15 exports, fully populated
 ├── policies/                 two security group documents, opposite heredoc quoting
 ├── templates/                listener default action, rule conditions, rule actions,
 │                             service load balancers
 ├── scripts/                  verify-lab-05.sh and lab-05-cleanup.sh
 ├── outputs/                  nothing staged; check-ignore names the rule that protected you
 └── git log shows Lab 01, 02, 03, 04 and 05 commits
```

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-05.sh`

Beyond existence, the script checks the properties that fail silently: target type `ip`, public subnets in two different AZs, the Step 13 cutover (`usms-app-sg` no longer a source), `containerName` `enrolment-api`, a non-zero grace period, exactly one deployment (nothing stuck mid-roll), and no unexpanded `$` in any template. The environment block comes first, as in every lab.

{% raw %}```bash
cat > scripts/utilities/verify-lab-05.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 05 artefact exists and is configured correctly.
# Read-only: this script inspects and changes nothing. Safe to run at any time.
# Exit 0 if every check passes, 1 otherwise.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-04.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-05.env" 2>/dev/null || true

# Defaults so that set -u cannot abort the script before it has told you anything.
: "${USMS_VPC_ID:=none}"
: "${USMS_PUBLIC_SUBNET_A:=none}"
: "${USMS_PUBLIC_SUBNET_B:=none}"
: "${USMS_PRIVATE_SUBNET_A:=none}"
: "${USMS_PRIVATE_SUBNET_B:=none}"
: "${USMS_APP_SG:=none}"
: "${USMS_ENROLMENT_SG:=none}"
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ENROLMENT_CONTAINER:=enrolment-api}"
: "${USMS_ALB_NAME:=usms-enrolment-alb}"
: "${USMS_ALB_SG:=none}"
: "${USMS_TG_NAME:=usms-enrolment-tg}"
: "${USMS_TG_ARN:=none}"
: "${USMS_ALB_LISTENER_ARN:=}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# One field from the load balancer, the target group, a target group attribute, or the service.
lbq()    { aws elbv2 describe-load-balancers --names "$USMS_ALB_NAME" \
             --query "LoadBalancers[0].$1" --output text; }
tgq()    { aws elbv2 describe-target-groups --names "$USMS_TG_NAME" \
             --query "TargetGroups[0].$1" --output text; }
tgattr() { aws elbv2 describe-target-group-attributes --target-group-arn "$(tgq TargetGroupArn)" \
             --query "Attributes[?Key=='$1'].Value | [0]" --output text; }
svcq()   { aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
             --services "$USMS_ENROLMENT_SERVICE" --query "services[0].$1" --output text; }
sgsrc()  { aws ec2 describe-security-groups --group-ids "$1" \
             --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text; }
az()     { aws ec2 describe-subnets --subnet-ids "$1" \
             --query 'Subnets[0].AvailabilityZone' --output text 2>/dev/null; }

# Listeners and rules have no names, so walk down from the load balancer.
LARN="${USMS_ALB_LISTENER_ARN}"
if [ -z "$LARN" ] || [ "$LARN" = "None" ]; then
  LARN=$(aws elbv2 describe-listeners --load-balancer-arn "$(lbq LoadBalancerArn)" \
           --query 'Listeners[?Port==`80`].ListenerArn | [0]' --output text 2>/dev/null || echo none)
fi

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Lab 02 to 04 dependencies =="
check "usms-vpc exists" "aws ec2 describe-vpcs --vpc-ids $USMS_VPC_ID"
check "usms-public-subnet-a exists" "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_A"
check "usms-public-subnet-b exists" "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_B"
check "the two public subnets are in TWO different AZs" \
  "test -n \"\$(az $USMS_PUBLIC_SUBNET_A)\" && test \"\$(az $USMS_PUBLIC_SUBNET_A)\" != \"\$(az $USMS_PUBLIC_SUBNET_B)\""
check "usms-app-sg still exists" "aws ec2 describe-security-groups --group-ids $USMS_APP_SG"
check "cluster $USMS_ECS_CLUSTER is ACTIVE" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "service $USMS_ENROLMENT_SERVICE is ACTIVE" "test \"\$(svcq status)\" = ACTIVE"

echo "== Lab 05 security groups =="
check "usms-alb-sg exists" "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG"
check "usms-alb-sg admits tcp/80 from 0.0.0.0/0" \
  "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG --query 'SecurityGroups[0].IpPermissions[?FromPort==\`80\`].IpRanges[].CidrIp' --output text | grep -q '0.0.0.0/0'"
check "usms-enrolment-sg admits tcp/80 from usms-alb-sg" \
  "sgsrc $USMS_ENROLMENT_SG | grep -qw $USMS_ALB_SG"
check "cutover done: usms-enrolment-sg no longer admits usms-app-sg" \
  "! sgsrc $USMS_ENROLMENT_SG | grep -qw $USMS_APP_SG"

echo "== Lab 05 load balancer =="
check "load balancer $USMS_ALB_NAME exists" "aws elbv2 describe-load-balancers --names $USMS_ALB_NAME"
check "load balancer state is active"        "test \"\$(lbq 'State.Code')\" = active"
check "scheme is internet-facing"            "test \"\$(lbq Scheme)\" = internet-facing"
check "type is application"                  "test \"\$(lbq Type)\" = application"
check "spans TWO availability zones"         "test \"\$(lbq 'length(AvailabilityZones)')\" = 2"
check "carries usms-alb-sg" \
  "aws elbv2 describe-load-balancers --names $USMS_ALB_NAME --query 'LoadBalancers[0].SecurityGroups' --output text | grep -qw $USMS_ALB_SG"

echo "== Lab 05 target group =="
check "target group $USMS_TG_NAME exists" "aws elbv2 describe-target-groups --names $USMS_TG_NAME"
check "target type is ip (mandatory for awsvpc)" "test \"\$(tgq TargetType)\" = ip"
check "protocol HTTP on port 80" \
  "test \"\$(tgq Protocol)\" = HTTP && test \"\$(tgq Port)\" = 80"
check "target group lives in usms-vpc" "test \"\$(tgq VpcId)\" = $USMS_VPC_ID"
check "health check is GET / with matcher 200" \
  "test \"\$(tgq HealthCheckPath)\" = / && test \"\$(tgq 'Matcher.HttpCode')\" = 200"
check "deregistration delay is 30 seconds" \
  "test \"\$(tgattr deregistration_delay.timeout_seconds)\" = 30"

echo "== Lab 05 listener and rule =="
check "a listener exists on port 80" "test \"\$LARN\" != none && test -n \"\$LARN\""
check "listener default action forwards to $USMS_TG_NAME" \
  "aws elbv2 describe-listeners --listener-arns \"\$LARN\" --query 'Listeners[0].DefaultActions[0].TargetGroupArn' --output text | grep -q ':targetgroup/$USMS_TG_NAME/'"
check "at least one non-default rule exists" \
  "test \"\$(aws elbv2 describe-rules --listener-arn \"\$LARN\" --query 'length(Rules[?IsDefault==\`false\`])' --output text)\" -ge 1"
check "the non-default rule returns a fixed-response 200" \
  "aws elbv2 describe-rules --listener-arn \"\$LARN\" --query 'Rules[?IsDefault==\`false\`].Actions[0].FixedResponseConfig.StatusCode' --output text | grep -q 200"

echo "== Lab 05 service wiring =="
check "service has exactly ONE loadBalancers entry" "test \"\$(svcq 'length(loadBalancers)')\" = 1"
check "it names $USMS_TG_NAME" \
  "svcq 'loadBalancers[0].targetGroupArn' | grep -q ':targetgroup/$USMS_TG_NAME/'"
check "containerName is $USMS_ENROLMENT_CONTAINER" \
  "test \"\$(svcq 'loadBalancers[0].containerName')\" = $USMS_ENROLMENT_CONTAINER"
check "containerPort is 80" "test \"\$(svcq 'loadBalancers[0].containerPort')\" = 80"
check "healthCheckGracePeriodSeconds is set (not None, not 0)" \
  "test \"\$(svcq healthCheckGracePeriodSeconds)\" != None && test \"\$(svcq healthCheckGracePeriodSeconds)\" -gt 0"
check "service still spans two private subnets" \
  "test \"\$(svcq 'length(networkConfiguration.awsvpcConfiguration.subnets)')\" = 2"
check "service still assigns NO public IP" \
  "test \"\$(svcq 'networkConfiguration.awsvpcConfiguration.assignPublicIp')\" = DISABLED"
check "exactly ONE deployment (nothing stuck mid-roll)" \
  "test \"\$(svcq 'length(deployments)')\" = 1"

echo "== Files and Git hygiene =="
check "configs/lab-05.env exists" "test -f configs/lab-05.env"
check "configs/lab-05.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=\$|=None\$' configs/lab-05.env"
check "policies/usms-alb-sg-ingress.json is valid JSON" \
  "python3 -m json.tool policies/usms-alb-sg-ingress.json"
check "policies/usms-enrolment-sg-ingress-alb.json is valid JSON" \
  "python3 -m json.tool policies/usms-enrolment-sg-ingress-alb.json"
check "templates/lab-05-listener-default-actions.json is valid JSON" \
  "python3 -m json.tool templates/lab-05-listener-default-actions.json"
check "templates/lab-05-rule-conditions.json is valid JSON" \
  "python3 -m json.tool templates/lab-05-rule-conditions.json"
check "templates/lab-05-rule-actions.json is valid JSON" \
  "python3 -m json.tool templates/lab-05-rule-actions.json"
check "templates/lab-05-service-load-balancers.json is valid JSON" \
  "python3 -m json.tool templates/lab-05-service-load-balancers.json"
check "no Lab 05 document contains an unexpanded variable" \
  "! grep -q '[\$]' templates/lab-05-listener-default-actions.json templates/lab-05-service-load-balancers.json policies/usms-enrolment-sg-ingress-alb.json"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"

if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

A failure under "== Environment ==" is the real problem, and most failures below it are
a consequence. Fix that block first:
  ./scripts/utilities/floci-storage-check.sh

A failure under "== Lab 02 to 04 dependencies ==" means an earlier lab's resource is
gone. Run verify-lab-02.sh, verify-lab-03.sh and verify-lab-04.sh before re-reading
anything here. Remember that verify-lab-04.sh is EXPECTED to report exactly one
failure after Step 13, on the usms-app-sg source check.
REMEDY
fi

[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-05.sh
bash -n scripts/utilities/verify-lab-05.sh && echo "syntax OK"
./scripts/utilities/verify-lab-05.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Lab 02 to 04 dependencies ==
  ok   usms-vpc exists
  ok   usms-public-subnet-a exists
  ok   usms-public-subnet-b exists
  ok   the two public subnets are in TWO different AZs
  ...
== Lab 05 target group ==
  ok   target type is ip (mandatory for awsvpc)
  ...
== Lab 05 service wiring ==
  ok   containerName is enrolment-api
  ok   healthCheckGracePeriodSeconds is set (not None, not 0)
  ...
== Files and Git hygiene ==
  ok   no Lab 05 document contains an unexpanded variable
  ok   no secret is tracked by git

PASS=49  FAIL=0
```

> Example output - the middle is abbreviated; you will see all 49.

**The expected count is `PASS=49  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `deregistration delay is 30 seconds` | Some builds do not implement `modify-target-group-attributes`. Confirm with `describe-target-group-attributes` and record it |
| `load balancer state is active` | Some builds leave the state at `provisioning` indefinitely. Confirm with `describe-load-balancers --query 'LoadBalancers[0].State'` and record it |
| `the non-default rule returns a fixed-response 200` | Some builds do not implement `create-rule`. If Step 15 failed outright, record it; the listener's default action still works |
| `healthCheckGracePeriodSeconds is set` | Some builds accept the flag on `update-service` and do not store it. Confirm with `describe-services --output json` and record it |
| `the two public subnets are in TWO different AZs` | Lab 2's Step 11 "Your turn" was skipped, or both subnets were made in one zone. This one is **not** benign - the load balancer is a single point of failure, and Section 13.1 Task D marks it as a fault |
| `cutover done: usms-enrolment-sg no longer admits usms-app-sg` | Step 13 was skipped. Also **not** benign - go and do it |
| `exactly ONE deployment` | Some builds report zero deployments rather than one. Check with `--query 'services[0].deployments'` and record which it is |

Everything else failing is a real problem with your work.

### 8.2 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** the ECS service `usms-enrolment-svc`, the listener rule, the listener, the
    load balancer `usms-enrolment-alb`, the target group `usms-enrolment-tg` and the security group
    `usms-alb-sg`.

    **What depends on it:** Lab 06 registers a scalable target against `usms-enrolment-svc` and may name
    `usms-enrolment-tg` in a request-count scaling policy. The CloudFormation lab re-declares this whole
    stack as a template and compares it with what you built by hand.

    **Reversible?** No. You would repeat this laboratory from Step 4, and Lab 04's Step 13 as well,
    because this script deletes the service.

    **Effect on later labs:** total. Run it only at the end of the course, and run the cleanup scripts in
    this order:

    ```text
    scripts/cleanup/lab-04-cleanup.sh    (Lab 06 - scaling configuration)
    scripts/cleanup/lab-05-cleanup.sh   (this one - load balancer and the service)
    scripts/cleanup/lab-04-cleanup.sh   (cluster, task definitions, roles, log group)
    scripts/cleanup/lab-03-cleanup.sh
    scripts/cleanup/lab-02-cleanup.sh
    ```

    Inside-out, every time. The script refuses to run while a scalable target still exists, and requires you to type `DELETE USMS LOAD BALANCER` in full.

````bash
cat > scripts/cleanup/lab-05-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 05, dependencies first.
# Order: service -> rules -> listener -> load balancer -> target group -> security group.
# Run AFTER scripts/cleanup/lab-04-cleanup.sh and BEFORE scripts/cleanup/lab-04-cleanup.sh.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04.env"
source "$REPO_ROOT/configs/lab-05.env"

cat <<'WARN'
============================================================
  This deletes the USMS enrolment SERVICE, the Application
  Load Balancer usms-enrolment-alb, its listener and rule,
  the target group usms-enrolment-tg and the security group
  usms-alb-sg.

  Lab 06, Lab 09 and the CloudFormation lab depend on parts
  of it. None of this is reversible.

  Run AFTER  lab-04-cleanup.sh
  Run BEFORE lab-04-cleanup.sh
============================================================
WARN

# Refuse while Lab 06's scaling configuration still points at this service.
RID="service/${USMS_ECS_CLUSTER}/${USMS_ENROLMENT_SERVICE}"
TARGETS=$(aws application-autoscaling describe-scalable-targets \
            --service-namespace ecs --resource-ids "$RID" \
            --query 'length(ScalableTargets)' --output text 2>/dev/null || echo 0)
if [ "$TARGETS" != "0" ] && [ "$TARGETS" != "None" ]; then
  echo "REFUSING: a scalable target still exists for $RID"
  echo "Run scripts/cleanup/lab-04-cleanup.sh first."
  exit 1
fi

read -r -p 'Type exactly: DELETE USMS LOAD BALANCER  > ' answer
[ "$answer" = "DELETE USMS LOAD BALANCER" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }

say "service: scale to zero, wait, then delete (this frees the targets)"
aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --desired-count 0 >/dev/null || true
aws ecs wait services-stable --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" || sleep 20
aws ecs delete-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --force >/dev/null || true

say "listener rules (deleting the listener would take them anyway; explicit is clearer)"
LARN=$(aws elbv2 describe-listeners --load-balancer-arn "$USMS_ALB_ARN" \
         --query 'Listeners[0].ListenerArn' --output text 2>/dev/null || echo None)
if [ "$LARN" != "None" ] && [ -n "$LARN" ]; then
  for r in $(aws elbv2 describe-rules --listener-arn "$LARN" \
               --query 'Rules[?IsDefault==`false`].RuleArn' --output text); do
    aws elbv2 delete-rule --rule-arn "$r" >/dev/null || true
  done
  say "listener"
  aws elbv2 delete-listener --listener-arn "$LARN" >/dev/null || true
fi

say "load balancer (must go before the target group it forwarded to)"
aws elbv2 delete-load-balancer --load-balancer-arn "$USMS_ALB_ARN" >/dev/null || true
aws elbv2 wait load-balancers-deleted --load-balancer-arns "$USMS_ALB_ARN" 2>/dev/null || sleep 20

say "target group"
aws elbv2 delete-target-group --target-group-arn "$USMS_TG_ARN" >/dev/null || true

say "security group (only after the load balancer's interfaces are gone)"
aws ec2 delete-security-group --group-id "$USMS_ALB_SG" || \
  echo "  still in use - wait for the load balancer's ENIs to be released, then retry"

echo
echo "Lab 05 teardown complete. scripts/cleanup/lab-04-cleanup.sh may now run."
EOF

chmod +x scripts/cleanup/lab-05-cleanup.sh
bash -n scripts/cleanup/lab-05-cleanup.sh && echo "syntax OK - do NOT run it"
````

You want `syntax OK - do NOT run it`; `bash -n` parses without executing. The order follows the API's dependencies:

1. **Service first**: while it exists it keeps registering targets.
2. **Rules, then listener**: explicit, so the output shows what went away.
3. **Load balancer before target group**: `delete-target-group` fails with `ResourceInUseException` while a listener forwards to it.
4. **Wait for the load balancer before the security group**: its ENIs hold the group briefly, giving `DependencyViolation`.

---

## 9. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, five env files sourced, `verify-lab-02.sh`, `verify-lab-03.sh` and `verify-lab-04.sh` all `FAIL=0`, both public subnets present in two different AZs, and your support path (A, B or C) recorded in `notes/lab-05-notes.md` |
| 2 | Step 5 | `usms-enrolment-alb` exists, `active`, `internet-facing`, type `application`, one node in each of two Availability Zones, carrying `usms-alb-sg`, with no listener yet |
| 3 | Step 8 | `usms-enrolment-tg` created with `--target-type ip`, health check `GET /` every 30 seconds, matcher `200`, deregistration delay 30; a listener on HTTP:80 whose default action forwards to it; the target group reporting one attached load balancer and zero targets |
| 4 | Step 11 | The service carrying one `loadBalancers` entry naming `enrolment-api` on port 80, a 60-second grace period, an unchanged task definition, and two targets registered **by the service** - one address in each private subnet |
| 5 | Step 14 | A forced deployment observed, with target states `initial`, `healthy` and `draining` all seen, and pre and post address lists that differ while the configuration does not |
| 6 | Step 15 | A rule at priority 10 matching `/alb-health` with a `fixed-response` action, listed above the default action in `describe-rules` |
| 7 | Step 16 | `PERSISTENCE PROVEN` after a Floci stop and start, with every ARN **re-derived from the API** and seven facts compared across three services |
| 8 | Step 19 | `configs/lab-05.env` populated with 15 exports and committed; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, the ECS service does not retain its load-balancer attachment. Diagnose first, then use the alternative in [Known Issues - Lab 05](known-issues.md#lab-05-alb). It states what the alternative does and does not prove.

??? danger "`ValidationError: At least two subnets in two different Availability Zones must be specified`"
    The most common failure in this lab, at Step 5.

    ```bash
    aws ec2 describe-subnets --subnet-ids "$USMS_PUBLIC_SUBNET_A" "$USMS_PUBLIC_SUBNET_B" \
      --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock}' --output table
    ```

    You need two rows with **different** `AZ` values. One row: `$USMS_PUBLIC_SUBNET_B` is empty (Lab 2 Step 11 "Your turn" skipped). Same AZ twice: wrong zone. Fix it in Lab 2 (`us-east-1b`, Lab 2's CIDR), regenerate `configs/lab-02.env` with Lab 2 Step 24, and restart this lab from Step 1.

??? danger "`ValidationError` about the subnet having no internet gateway route, on create-load-balancer"
    You passed private subnets to an `internet-facing` load balancer; it needs subnets with a default route to an internet gateway.

    ```bash
    aws ec2 describe-route-tables --filters "Name=association.subnet-id,Values=$USMS_PUBLIC_SUBNET_A" \
      --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId]' --output text
    ```

    You want `0.0.0.0/0` with an `igw-` ID. `nat-` means you are looking at `usms-private-rt` and the subnet variable is wrong.

??? danger "`InvalidParameterException: The container enrolment-api does not exist in the task definition`"
    Step 10's `containerName` does not match a container in `usms-enrolment:2`:

    ```bash
    aws ecs describe-task-definition --task-definition usms-enrolment \
      --query 'taskDefinition.containerDefinitions[].{Name:name,Ports:portMappings[].containerPort}' \
      --output table
    ```

    `containerName` must equal the `Name` column, not the family `usms-enrolment`, the service name or the image. A wrong port gives a port error; the same table answers it.

??? danger "`InvalidParameterException` mentioning the network mode, when attaching the service"
    The target group is `instance`, and `awsvpc` tasks have no instance to register.

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].TargetType' --output text
    ```

    `TargetType` cannot change. Recreate the target group with `--target-type ip`, then redo Steps 7, 8 and 10 (update the listener's default action with `aws elbv2 modify-listener`, or recreate the listener).

??? danger "Targets stay `initial` forever, or go straight to `unhealthy`"
    Check these four in order:

    1. **The security group.** Does `usms-enrolment-sg` admit tcp/80 from `usms-alb-sg`?

        ```bash
        aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
          --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text
        echo "usms-alb-sg = $USMS_ALB_SG"
        ```

    2. **The health check path.** Does `/` return `200`? A redirect to `/login` returns `302` and fails.
    3. **The port.** Target group `Port`, `containerPort` and the application's port must agree.
    4. **The reason field**:

        ```bash
        aws elbv2 describe-target-health --target-group-arn "$USMS_TG_ARN" \
          --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State,TargetHealth.Reason,TargetHealth.Description]' \
          --output text
        ```

    `Target.FailedHealthChecks`: the probe ran and failed (application or matcher). `Target.Timeout`: no answer (security group or port). `Elb.InitialHealthChecking`: wait.

    On Floci support path B, targets that never leave `initial` are expected. Record it and continue.

??? danger "Target health says `unused`"
    Nothing forwards to this target group.

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].LoadBalancerArns' --output text
    ```

    Empty means Step 8 did not run or the listener names another target group. Check with `describe-listeners`; fix with `modify-listener`.

??? danger "The service will not stabilise: tasks start and stop in a loop"
    A missing or too-short grace period: still-starting tasks are marked unhealthy and replaced.

    ```bash
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].{Grace:healthCheckGracePeriodSeconds,Events:events[0:5].message}' --output json
    ```

    If `Grace` is `null` or `0`, set it:

    ```bash
    aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
      --health-check-grace-period-seconds 60 --query 'service.healthCheckGracePeriodSeconds' --output text
    ```

    If it is 60 and the loop continues, raise the grace period rather than loosening the health check.

??? danger "`verify-lab-04.sh` reports a failure after Step 13"
    Expected: exactly one check, `usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)`, because Step 13 replaced that source.

    ```bash
    ./scripts/utilities/verify-lab-04.sh | grep FAIL
    ```

    One line plus `PASS=48  FAIL=1`; anything else needs investigating. Do **not** put the old rule back: document the failure, or do Exercise 2. `verify-lab-05.sh` is the script of record from Step 13.

??? danger "`ResourceInUseException` on `delete-target-group`"
    A listener still forwards to it; delete it or repoint its default action:

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].LoadBalancerArns' --output text
    ```

    Order: service, rules, listener, load balancer, target group (as `scripts/cleanup/lab-05-cleanup.sh` does).

??? danger "`DependencyViolation` on `delete-security-group` for usms-alb-sg"
    The load balancer's ENIs still hold the group; `aws elbv2 wait load-balancers-deleted` waits for release. If that does not help:

    ```bash
    aws ec2 describe-network-interfaces --filters "Name=group-id,Values=$USMS_ALB_SG" \
      --query 'NetworkInterfaces[].{Id:NetworkInterfaceId,Desc:Description,Status:Status}' --output table
    ```

    An interface described `ELB app/usms-enrolment-alb/...` belongs to the load balancer. Wait; do not delete it.

??? danger "`aws elbv2 wait load-balancer-available` never returns"
    The build leaves the load balancer in `provisioning`. Press ++ctrl+c++, use the polling loop in Step 5 part 2, and record the state. Nothing later requires `active`; Section 8's script lists it as benign.

??? danger "`curl` returns 503 Service Temporarily Unavailable from the load balancer"
    The listener worked and there were **no healthy targets**. Work through the `Targets stay initial forever` entry.

    `502 Bad Gateway` means a target was chosen and gave an invalid response; connection refused or timeout means nothing listens on the load balancer (Checkpoint 2's last line).

??? danger "`An error occurred (NoCredentials)` or a suggestion to run `aws login`"
    Do **not** run `aws login`: it signs in to **real AWS**.

    ```bash
    cd ~/aws-floci-course && source configs/course.env && ./scripts/utilities/whoami.sh
    ```

    Permanently: apply Errata 01 (the loader belongs in your **login** shell's startup file).

??? danger "Everything is gone after a restart"
    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    `FLOCI_STORAGE_MODE=memory` means a stray `floci start` replaced the Compose container. Restore from your end-of-Lab-04 snapshot and confirm the storage check before rebuilding.

---

## 11. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `elbv2 create-load-balancer`, `describe-load-balancers` | Full | Object stored and returned on most builds | Implemented in Floci |
| Load balancer nodes, one per Availability Zone | Real, with real addresses | No nodes exist | Conceptual / Real AWS |
| `provisioning` to `active` transition, 2 to 4 minutes | Real, and slow | Usually instant, or stuck at `provisioning` | Floci Limitation |
| Publicly resolvable `DNSName` | Yes, resolves to the nodes | No public DNS; some builds serve a `localhost.localstack.cloud` name via 4566 | Floci Limitation |
| `modify-load-balancer-attributes` (idle timeout, header handling) | Enforced on every connection | Stored at best; never enforced | Floci Limitation |
| `elbv2 create-target-group`, `--target-type ip` | Full, and validated against the network mode | Generally implemented | Implemented in Floci |
| Target group health checks actually executed | Every `interval` seconds, from each node | Rarely executed | Floci Limitation |
| `describe-target-health` states and reasons | Real, and the `Reason` field is diagnostic | Fields present; usually `initial` or empty | Floci Limitation |
| `modify-target-group-attributes` (deregistration delay, algorithm) | Enforced | Build-dependent; stored at best | Floci Limitation |
| `elbv2 create-listener`, default actions | Full | Generally implemented | Implemented in Floci |
| `elbv2 create-rule`, priority ordering, path conditions | Evaluated on every request | Stored; never evaluated | Floci Limitation |
| `fixed-response`, `redirect`, weighted `forward` actions | Full | Stored; no data path to exercise them | Floci Limitation |
| `authenticate-oidc` and `authenticate-cognito` actions | Full | Not available | Conceptual / Real AWS |
| HTTPS listeners, ACM certificates, TLS policies | Full | No certificate authority; not available | Conceptual / Real AWS |
| ECS service registering and deregistering its own targets | Automatic, on every task change | Modelled on some builds; may leave the target group empty | Floci Limitation |
| `update-service --load-balancers` in place | Supported for the `ECS` deployment controller | Build-dependent; the recreate fallback exists for this reason | Floci Limitation |
| `--health-check-grace-period-seconds` | Enforced; ECS ignores target health for that long | Stored at best | Floci Limitation |
| Connection draining on deregistration | Real; in-flight requests finish | No connections to drain | Floci Limitation |
| Cross-zone load balancing (always on for an ALB) | Real | Nothing to balance | Conceptual / Real AWS |
| `X-Forwarded-For` and the other forwarded headers | Added to every request | No requests | Conceptual / Real AWS |
| Access logs to S3 | Full | Not available, and there is no bucket until Lab 10 | Conceptual / Real AWS |
| `AWS/ApplicationELB` CloudWatch metrics (`RequestCount`, `TargetResponseTime`, `HTTPCode_Target_5XX_Count`) | Published every minute | Not published | Conceptual / Real AWS |
| `ALBRequestCountPerTarget` scaling metric | Full, using a `ResourceLabel` | Not available; Lab 06 uses CPU instead | Conceptual / Real AWS |
| Security group enforcement on load balancer or task traffic | Every packet | Not enforced | Floci Limitation |
| Cost - per load balancer hour plus per LCU hour | Real, and a load balancer costs money while idle | Free | Conceptual / Real AWS |
| Service quotas (load balancers, target groups, rules per listener) | Enforced, and rules per listener bites first | Not enforced | Conceptual / Real AWS |

**Observed versus reasoned about.** Every object, the 0 to 1 attachment count, service-registered targets in the private CIDRs, the forced deployment, the rule ordering, the cutover and the restart proof are observable on any build. A served request, real health probes, draining, rule evaluation and HTTPS are conceptual unless you were on support path A. Say in your report which items you actually observed; claiming to have observed something you reasoned about is worth negative marks (Section 13.1 Task D checks it).

**Where Floci is nicer than reality (traps on real AWS):** load balancers appear instantly (real ones take 2 to 4 minutes, so they are created by infrastructure code, never per deployment); health checks never run, so nothing is ever `unhealthy` and the four causes in Section 10 must be learned from the table; no cost (an idle ALB bills hourly plus LCUs); no quotas (`TooManyRulesException` on rules per listener bites first); security groups are not enforced, which is why Section 8's script asserts Step 9's rule rather than testing it.

This lab is not auto scaling: `desiredCount` still moves only when you type it. What it adds is the signal: a target group makes `ALBRequestCountPerTarget` possible, and Exercise 5 builds the `ResourceLabel` it needs.

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-05-ecs-alb/exercises.md`; screenshots go in `screenshots/`.

### Exercise 1 - Basic: a second path through the same load balancer

**Requirements:** the USMS results service will be a separate ECS service sharing enrolment's hostname. Route `/results` to it:

1. Create `usms-results-tg` with the same target type, protocol and port as `usms-enrolment-tg`, a
   health check path of `/`, a matcher of `200-399`, and a deregistration delay of 15 seconds.
2. Create a listener rule at priority 20 on the existing listener, matching the path patterns `/results`
   and `/results/*`, forwarding to `usms-results-tg`.
3. Read the listener's rules back and confirm the ordering.

**Constraints**

- Every ARN captured with `$(...)` and `--query`.
- Tag both objects `Project=USMS`, `Tier=app`, `Lab=05`, `Service=results`.
- Conditions and actions as JSON documents in `templates/`, as in Step 15; no inline shorthand.
- Do **not** create a second ECS service or register any target; an empty target group is correct here.
- Do **not** record either object in `configs/lab-05.env`; Exercise 4 removes them.

**Expected outcome:** `describe-rules` shows three entries: priority 20, priority 10 (`/alb-health`) and the default. `describe-target-health` on `usms-results-tg` is empty, and it is attached to one load balancer.

**Hints:** Steps 6 and 15. `describe-rules` may not return priority order, and `Priority` is a string (Step 16 used `sort_by`). Say in one sentence what a request to `/results` would receive with no targets, and which status code from Section 10's `curl` entry it would be.

### Exercise 2 - Intermediate: repair the verification script you broke

**Requirements:** Step 13 left `verify-lab-04.sh` asserting something no longer true. Fix it properly.

1. Read the failing check in `scripts/utilities/verify-lab-04.sh` and write down, in one sentence, the
   property it was asserting. Not the command: the property.
2. Change it so that it asserts the equivalent property in the current architecture: that
   `usms-enrolment-sg` is sourced from a **group** and not a CIDR, and that the group is
   `usms-alb-sg`.
3. Add a second check, immediately after it, asserting that `usms-app-sg` is **no longer** a source. A
   check that only confirms the new state would still pass if both rules existed.
4. Make both checks read `usms-alb-sg`'s ID from `configs/lab-05.env` rather than hard-coding it, and
   make the script tolerate that file not existing - a student who has done Lab 04 and not this lab must
   still be able to run it.
5. Run `verify-lab-04.sh` and `verify-lab-05.sh` and get `FAIL=0` from both.
6. Commit the change with a message that explains **why** the assertion changed, not what line moved.

**Constraints**

- Keep the `${BASH_SOURCE[0]}` resolution; it must work from any directory.
- Under `set -u`, a missing `USMS_ALB_SG` must give a readable failed check, not an unbound-variable abort.
- State the new `PASS` count in a comment at the top and in `exercises.md`, and say why an undocumented count is worse than none.
- Do not delete the original check; change what it asserts.

**Expected outcome:** both scripts `FAIL=0`, a commit message explaining an architectural change, and two sentences in `exercises.md` on when updating a verification script is right and when it hides a regression.

**Hints:** point 1 is the whole exercise: write the check against the property ("accepts traffic only from a named group"), not one expression of it. For point 4, Lab 04's script already uses `: "${VAR:=default}"`.

### Exercise 3 - Problem solving: a load balancer report tool

**Requirements:** write `scripts/utilities/usms-lb-report.sh`. With no arguments, it walks every ALB whose name starts with `usms-` and prints its decision table:

```text
usms-enrolment-alb   internet-facing  application  active  AZs=2  SGs=1
  HTTP:80
    prio  10       path-pattern  /alb-health,/alb-health/*   -> fixed-response 200
    prio  20       path-pattern  /results,/results/*         -> usms-results-tg    (0 targets, 0 healthy)
    prio  default  -                                          -> usms-enrolment-tg (2 targets, 2 healthy)
```

**Constraints**

- Runs from any directory (resolve `configs/` from `${BASH_SOURCE[0]}`, as Section 8's script does).
- No arguments; no hard-coded ARN or name beyond the `usms-` prefix.
- Handles a load balancer with no listeners, a listener with no non-default rules, and an empty target group without crashing or blank rows.
- Rules in evaluation order, default last. `Priority` is a string and the default's is `default`; handle it and comment how.
- Non-forward actions print their own summary.
- `set -uo pipefail`; justify your `-e` decision in a comment.
- Also write `outputs/lab-05-lb-report.json`.

**Expected outcome:** identical output from `~` and from `~/aws-floci-course/labs/lab-05-ecs-alb/`; correct before and after Exercise 1, and with the `/alb-health` rule temporarily deleted.

**Hints:** four levels of calls (load balancers via `starts_with`, listeners, rules, target health); decide where to switch to `python3`. Healthy count: `length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])`.

### Exercise 4 - Challenge: the exposure review

**Requirements:** the university's information security officer writes:

> I have been told the student enrolment API is now on the public internet. Two weeks ago I was told it
> was internal and only reachable from the portal. Please explain what changed, tell me whether I should
> be worried, and give me a written recommendation with costs.
>
> Specifically: why is this internet-facing rather than internal? What can reach the tasks now that
> could not before, and what can reach them that could before and now cannot? What does this cost us per
> month, idle and under load? And what would it take to put HTTPS in front of it, because I am not
> signing off on a plaintext login flow.
>
> Also, somebody has left two practice objects in the account from an exercise. Please tidy them up.

Write in `labs/lab-05-ecs-alb/exercises.md`:

- **What changed, in exactly two sentences**: one for the network path, one for the security groups.
- **Internal versus internet-facing.** Make the case for `--scheme internal`: what changes in Step 5's command and the DNS name, what does not, and which you recommend given the portal is the only client. Then argue the other side in two sentences.
- **The exposure delta, as a table**: before and after; rows for what can reach the load balancer, the tasks, and the tasks *directly*.
- **A monthly cost estimate with a citation**: ALB hourly charge, LCU charge, and the two Fargate tasks for comparison, with explicit "under load" assumptions and the idle figure.
- **The HTTPS plan**: every object needed, in order, which AWS provides free and which needs something outside AWS, with documentation citations, plus the port-80 rule you would add and its action type.
- **The tidy-up**: exact commands in dependency order, each preceded by the four-line danger admonition, for `usms-results-tg` and the priority-20 rule from Exercise 1.

Then execute only the deletions and confirm `./scripts/utilities/verify-lab-05.sh` reports `FAIL=0`.

**Constraints**

- Delete nothing in Section 15's KEEP column, in particular not the `/alb-health` rule (Section 8's script asserts it).
- Every number needs a source or derivation ("730 hours at the published rate plus N LCU-hours from this assumption").
- The HTTPS plan must separate what makes the port *open* from what makes something *listen* on it.

**Expected outcome:** an analysis a security officer could act on and a finance team could check; practice objects gone; verification passes.

**Hints:** the pricing page bills LCUs on the largest of four dimensions; say which dominates for a low-traffic API (not the one most people guess). For HTTPS, search the AWS docs for requesting a public certificate: one new service, one DNS record, and a surprising fact about the certificate's price.

### Exercise 5 - Integration: the ResourceLabel hand-off to Lab 06

**Requirements:** Lab 06 scales on CPU because, when written, the course had no load balancer. Build the string that unlocks `ALBRequestCountPerTarget`. Its `ResourceLabel` concatenates two ARN fragments:

```text
<load-balancer-arn-suffix>/<target-group-arn-suffix>

app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
|                                     | |                                            |
+-- from the load balancer's ARN ------+ +-- from the target group's ARN -------------+
```

1. Write `scripts/utilities/usms-resource-label.sh`, which derives that string **from the API** - never
   from a hard-coded identifier - and prints it. It takes a load balancer name and a target group name as
   arguments, defaulting to this lab's two, and validates that it got a plausible result before printing
   it.
2. Append `USMS_ALB_RESOURCE_LABEL` to `configs/lab-05.env` with that value, derived rather than typed.
   Re-run the empty-value check and state the new export count.
3. Write `outputs/lab-05-lab04c-readiness.txt` containing, each on its own labelled line: the resource
   label; the target group ARN; the load balancer ARN; the composite scalable resource ID
   `service/<cluster>/<service>` from Lab 04; the scalable dimension `ecs:service:DesiredCount`; the
   service's current desired count; and one sentence naming which of Lab 06's three predefined metrics
   you would now recommend and why.
4. **Take a measurement only you can take.** Record a UTC timestamp, force a new deployment, poll until
   the service reports exactly one deployment and its target list is stable, record the timestamp again,
   and write the elapsed seconds to the readiness file. That number is how long a full replacement of
   capacity takes in your environment, and Lab 06's cooldown choices are sized against it. If your
   build makes the measurement meaningless, say so and cite the figure AWS documents for Fargate task
   start-up instead.
5. Verify the label the only way you can without an auto scaling policy: assert that it contains both
   names, has exactly six slash-separated segments, and that its first segment is the literal `app`.
   Explain in one sentence why `app` is there and what it would be for a Network Load Balancer.

**Constraints**

- Works from any directory; must **not** read `configs/lab-05.env` for the ARNs.
- Use shell parameter expansion (not `awk`) for at least one suffix, and comment why the two suffixes need different treatment.
- Timestamps via `python3`, not `date -d` or `date -v`.
- No script may contain, read or reference an access key.

**Expected outcome:** a committed script Lab 06 and the CloudFormation lab can call unchanged, a readiness file from which a reader could write Lab 06's `put-scaling-policy` call, and a measured capacity-replacement time.

**Lab 06 uses this:** its Step 14 table has an empty third row; this exercise fills it in.

**Hints:** the load balancer suffix starts after `:loadbalancer/`; the target group suffix **includes** `targetgroup` (see the `ResourceLabel` description in the `PredefinedMetricSpecification` reference). Lab 04's `"${TASK_ARN##*/}"` is from the right family; you want a different member. Six segments: `app`, LB name, LB id, `targetgroup`, TG name, TG id.

---

## 13. Lab Assessment Checklist

### 13.1 In-class assessment

**Format:** individual, at the machine, **75 minutes**, out of 100, marked from your repository and `exercises.md`.

**When:** after Sections 7 and 8, with `verify-lab-05.sh` at `FAIL=0`. On support path C, tell your instructor beforehand: Tasks A and B become written equivalents.

**Permitted:** AWS documentation, this document, Lab 04, your `notes/` and `exercises.md`, `aws <service> <operation> help`, your shell history. **Not permitted:** messaging, shared terminals, another student's repository, AI assistants.

**Hand in** (created during the session; git-ignored, collected directly, do not commit):

```text
outputs/lab-05-assessment-a.txt     Task A - commands and their output
outputs/lab-05-assessment-b.txt     Task B - your diagnosis, in the format below
outputs/lab-05-assessment-c.md      Task C - four written answers
```

#### Task A - Build from requirements (30 marks, about 30 minutes)

No commands are given. The USMS transcripts API needs its own path through the existing load balancer. Build:

1. A target group named `usms-transcripts-tg`, in `usms-vpc`, serving HTTP on port 8080, registering
   targets **by address**, with a health check on `/transcripts/health` every 15 seconds, a 4-second
   timeout, 2 consecutive successes to become healthy, 3 consecutive failures to become unhealthy, and
   accepting any 2xx or 3xx response as success.
2. A deregistration delay of 20 seconds on it.
3. A listener rule on the existing HTTP:80 listener, at priority 30, matching `/transcripts` and
   everything below it, forwarding to that target group.
4. A second listener rule at priority 5, matching `/admin` and everything below it, returning a
   fixed `503` with the plain-text body `usms admin api is not exposed publicly` and contacting no
   target at all.
5. Written into `outputs/lab-05-assessment-a.txt`: the commands you ran, their output, and a
   `describe-rules` listing that shows all four rules plus the default in evaluation order.

| | Marks |
| --- | --- |
| Target group created with the correct target type, port, VPC and all five health check values | 10 |
| Deregistration delay set correctly, by attribute rather than by recreation | 3 |
| Priority-30 rule with correct path patterns, forwarding correctly | 6 |
| Priority-5 rule with a correct `fixed-response` action, and placed so it is evaluated **first** | 6 |
| Every ARN captured with `$(...)` and `--query`; nothing copied by hand | 3 |
| Output file complete and legible | 2 |

**One deliberate trap:** "evaluated first" is a property of the priority number, not of creation order. If you want to renumber an existing rule, re-read Step 15 first.

#### Task B - Diagnose (25 marks, about 20 minutes)

Your instructor injects **one** reversible fault: a single change to a single object, not in Task A's objects. Find it and write into `outputs/lab-05-assessment-b.txt`, in this order:

```text
SYMPTOM     what you observed, and the exact command that showed it to you
HYPOTHESES  at least three plausible causes, ranked, before you tested any of them
TEST        the ONE API call that distinguished the real cause from the others
CAUSE       the object, the field, the wrong value and the right value
FIX         the command you ran
PROOF       the command and output showing the configuration is correct again
```

| | Marks |
| --- | --- |
| Symptom stated precisely, with the command that revealed it | 4 |
| Three or more plausible hypotheses, ranked, written **before** testing | 8 |
| A single discriminating test rather than a sequence of guesses | 6 |
| Correct cause identified, naming the object and the field | 4 |
| Fix applied and proven | 3 |

14 of 25 marks are for the method, 7 for being right: a lucky find with nothing written scores lower than good reasoning that misses. Section 10 and `verify-lab-05.sh` are permitted.

#### Task C - Explain (25 marks, about 15 minutes)

Answer in `outputs/lab-05-assessment-c.md`, in prose, two to four sentences each.

1. **(7 marks)** A colleague says the target group is empty and asks whether they should run
   `aws elbv2 register-targets` with the tasks' addresses. Explain why not, and say what would happen if
   they did it anyway. Name the object that is responsible for the contents of that target group.
2. **(7 marks)** A task reports `healthStatus` of `HEALTHY` to ECS and its address reports `unhealthy` in
   the target group. State what this combination means, name the two most likely causes in order, and
   give the single command you would run first.
3. **(6 marks)** Explain what `--health-check-grace-period-seconds` does and describe, in sequence, the
   failure that occurs without it on a service whose application takes 45 seconds to start behind a
   health check with a 30-second interval and an unhealthy threshold of 2.
4. **(5 marks)** The target group's `--target-type` is `ip`. Say why that is not a preference, what the
   alternative would have been, and at what point in the lab the wrong choice would first have produced
   an error.

#### Task D - Evidence and hygiene (20 marks, about 10 minutes)

| | Marks |
| --- | --- |
| `./scripts/utilities/verify-lab-05.sh` reports `FAIL=0`, or its failures are each named and explained as benign in `notes/lab-05-notes.md` | 6 |
| `configs/lab-05.env` exists, is committed, has 15 exports (16 after Exercise 5), and contains no empty value and no `None` | 4 |
| `git status --short` shows nothing under `outputs/` and no root `.env`; `git check-ignore -v` demonstrated on one assessment output file | 4 |
| Your Step 3 support path is stated at the top of `notes/lab-05-notes.md`, and Section 11's observed-versus-reasoned split is annotated for **your** build | 4 |
| A commit exists for this session, with a message that describes the change rather than the files | 2 |

**Negative marking applies to one thing only:** claiming to have observed something your build did not do. A recorded limitation earns full marks; an invented `200` is minus five.

#### Marking bands

| Band | Marks | What it looks like |
| --- | --- | --- |
| Distinction | 80+ | Task A correct first time; Task B's hypotheses show a mental model of the whole chain; Task C's answers would be useful to a colleague |
| Merit | 65–79 | Everything works; the reasoning in B and C is sound but thin in places |
| Pass | 50–64 | The build works, possibly after several attempts; the written answers are correct but describe rather than explain |
| Fail | below 50 | The build does not work and the written work does not show why |

### 13.2 Submission checklist

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` appears in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-05-notes.md`

**Resources**

- [ ] `usms-alb-sg` exists, admitting tcp/80 from `0.0.0.0/0`
- [ ] `usms-enrolment-alb` exists: `internet-facing`, type `application`, two Availability Zones, one
      security group
- [ ] `usms-enrolment-tg` exists with `--target-type ip`, HTTP on 80, in `usms-vpc`, health check `GET /`
      with matcher `200`, deregistration delay 30
- [ ] A listener on HTTP:80 whose default action forwards to `usms-enrolment-tg`
- [ ] A rule at priority 10 matching `/alb-health` with a `fixed-response` 200
- [ ] `usms-enrolment-svc` has exactly one `loadBalancers` entry, naming `enrolment-api` on port 80
- [ ] `healthCheckGracePeriodSeconds` is 60
- [ ] `usms-enrolment-sg` admits tcp/80 from `usms-alb-sg` and from nothing else
- [ ] The service still spans two private subnets with `assignPublicIp` `DISABLED`
- [ ] The task definition is still `usms-enrolment:2` - no new revision was registered

**Evidence**

- [ ] Step 11's target list showing one address in each private subnet
- [ ] Step 11 part 3's side-by-side ECS health and target health output
- [ ] Step 12's proof, either the `200` **or** `outputs/lab-05-path-proof.txt` with the reason the data
      path was unavailable
- [ ] Step 13's `diff` showing exactly one check changing state in `verify-lab-04.sh`
- [ ] Step 14's poll output showing `draining` alongside `healthy`, or the reason it was not observable
- [ ] Step 16's `PERSISTENCE PROVEN` line
- [ ] Step 17's `CUTOVER CONFIRMED` and `LOOP CLOSED` lines
- [ ] `outputs/lab-05-pre-deploy.txt` and `outputs/lab-05-post-deploy.txt` present
- [ ] Screenshots in `screenshots/` for Checkpoints 4, 5 and 7

**Hygiene and written work**

- [ ] `configs/lab-05.env` exists, is committed, has 15 exports (16 after Exercise 5) and no empty values
      or `None`
- [ ] `scripts/utilities/verify-lab-05.sh` exists and reports `PASS=49  FAIL=0`, or its documented benign
      failures, each explained
- [ ] `scripts/cleanup/lab-05-cleanup.sh` exists, passes `bash -n`, and has **not** been run
- [ ] `verify-lab-04.sh` reports `PASS=48  FAIL=1` with the failure explained, **or** `FAIL=0` because
      you did Exercise 2
- [ ] `git status --short` shows nothing under `outputs/`
- [ ] `notes/lab-05-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-05-ecs-alb/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding**

- [ ] I can name the four Elastic Load Balancing objects and say which one holds the health check
- [ ] I can say why a Fargate target group must be `ip` and what breaks if it is not
- [ ] I can name the object responsible for the contents of the target group, and it is not me
- [ ] I can describe a state in which ECS and the load balancer disagree about a task's health, and what
      it means
- [ ] I can explain, in order, what happens to a request in flight when its task is deregistered

---

## 14. Review Questions

Answer in prose in `notes/lab-05-notes.md`.

1. Lab 04 sourced a security group rule from a group because the tasks have no stable addresses; this lab put a load balancer in front of them for arguably the same reason. In a paragraph, say what the two have in common, what general problem both solve, and name a third solution to it elsewhere in computing.
2. "The load balancer's health check says the task is unhealthy, so the application is broken." Why is that unsound? Which two states can the target group health check not distinguish, which field does, and what diagnostic sequence would you follow?
3. There is no `update-target-group-target-type`. What does that say about a target group's *configuration* versus its *identity*? Connect it to Lab 04's immutable task definition revisions, name two other fields in this lab that behave the same way, and one that looks like it should but does not.
4. A request arrives at the exact moment ECS decides to stop the task that would serve it. Name every timer involved and where it is configured, and say whether the request succeeds. What changes if `deregistration_delay.timeout_seconds` were left at 300?
5. Step 13 made Lab 04's verification script fail. Argue for updating it immediately, then for leaving it failing and documented. Which would you do with four other engineers on the system, and why might one engineer change the answer?
6. The load balancer is `internet-facing` and the tasks have no public address. Explain how both are true, naming every Lab 2 resource involved. What could an attacker who compromised the load balancer's configuration reach, and what would differ had the tasks had public addresses?
7. Why is requests per target a better scaling signal than CPU for a web API? Name the one situation where CPU is better, and what would have to be true of the enrolment application for `ALBRequestCountPerTarget` to scale it badly.

---

## 15. KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ════════════════════════╗    ╔═════════════ CLEAN UP ══════════════╗
║ usms-alb-sg               the edge firewall         ║    ║ usms-results-tg                     ║
║ usms-enrolment-alb        the stable name           ║    ║   - Exercise 1 practice;            ║
║ usms-enrolment-tg         Lab 06's metric names it ║    ║   removed in Exercise 4             ║
║ the HTTP:80 listener      and its default action    ║    ║                                     ║
║ the /alb-health rule      Section 8 asserts it      ║    ║ the priority-20 listener rule       ║
║ usms-enrolment-svc        now load balanced         ║    ║   - same exercise, same removal     ║
║ usms-enrolment-sg         cut over to usms-alb-sg   ║    ║                                     ║
║ configs/lab-05.env       Lab 06 sources it        ║    ║ outputs/lab-05-pre/post-*.txt      ║
║ templates/lab-05-*.json  the reviewable artefacts  ║    ║   - evidence; keep until            ║
║ policies/usms-alb-sg-ingress.json and the ALB one   ║    ║   submitted, then remove            ║
║ scripts/utilities/verify-lab-05.sh                 ║    ║                                     ║
║ everything from Labs 01, 02, 03 and 04             ║    ║ outputs/lab-05-assessment-*.*      ║
║                                                     ║    ║   - after your instructor has       ║
║                                                     ║    ║   collected them                    ║
╚═════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Once your report is submitted and the assessment collected:

```bash
rm -f outputs/lab-05-pre-restart.txt  outputs/lab-05-post-restart.txt
rm -f outputs/lab-05-pre-deploy.txt   outputs/lab-05-post-deploy.txt
rm -f outputs/lab-05-pre-verify-04.txt outputs/lab-05-post-verify-04.txt
git status --short
./scripts/utilities/verify-lab-05.sh | tail -2
```

Do **not** run `scripts/cleanup/lab-05-cleanup.sh`, `lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`; they are for the end of the course, in the order given in Section 8.2.

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and Lab 04
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 10
  USMSStudentDataReadWrite ............. on TWO roles, naming a bucket that still does not exist

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
                 ^ the load balancer's two nodes live here, and REQUIRED both subnets
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                                                            -> usms-s3-endpoint
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg, usms-private-nacl

Lab 03  COMPUTE - instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
                  ^ still carries usms-app-sg, which no longer opens anything on the tasks
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> the EC2 Auto Scaling material

Lab 04 COMPUTE - containers you operate
  usms-ecs-cluster
    usms-enrolment-svc     desired 2, both private subnets, no public IP
      usms-enrolment:2     awsvpc, FARGATE, 256/1024, container health check
        executionRoleArn   usms-ecs-exec-role
        taskRoleArn        usms-ecs-task-role -> USMSStudentDataReadWrite
  /usms/ecs/enrolment      retention 7 days

Lab 05 TRAFFIC - the front door                            <-- you are here
  usms-alb-sg              in: tcp/80 from 0.0.0.0/0
  usms-enrolment-alb       internet-facing, application, public subnets a + b
    listener HTTP:80
      rule prio 10         /alb-health -> fixed-response 200
      default              -> usms-enrolment-tg
  usms-enrolment-tg        target-type ip, GET / every 30s, matcher 200,
                           deregistration delay 30, least_outstanding_requests
    targets                registered and deregistered BY usms-enrolment-svc
  usms-enrolment-svc       loadBalancers[0] -> usms-enrolment-tg / enrolment-api / 80
                           healthCheckGracePeriodSeconds 60
  usms-enrolment-sg        in: tcp/80 from usms-alb-sg ONLY   (cutover, Step 13)

Lab 06 SCALING (next)
  scalable target  service/usms-ecs-cluster/usms-enrolment-svc   min 2 max 10
    target tracking on CPU today; ALBRequestCountPerTarget is now possible

Lab 10  Lambda
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for BOTH roles at once.
                        Lambda creates it inline; there is no separate storage lab
```

---

## 16. Preparation for the Next Lab

Lab 06 hands this service's `desiredCount` to Application Auto Scaling. It creates no new compute and renames nothing.

| From `configs/lab-05.env` | Lab 06 uses it for |
| --- | --- |
| `USMS_TG_ARN` and `USMS_TG_NAME` | The target group its request-count policy would name |
| `USMS_ALB_ARN` | The other half of the `ResourceLabel` composite string |
| `USMS_ALB_RESOURCE_LABEL` (Exercise 5) | The `ResourceLabel` field, verbatim, if you did Exercise 5 |
| `USMS_SVC_GRACE_PERIOD` | Understanding why a scaled-out task is not counted as capacity for 60 seconds |

| From earlier labs | Lab 06 uses it for |
| --- | --- |
| Lab 04 `USMS_ECS_CLUSTER`, `USMS_ENROLMENT_SERVICE` | The composite resource ID `service/<cluster>/<service>` |
| Lab 04 `USMS_ECS_DESIRED_BASELINE` | The scalable target's minimum capacity of 2 |
| Lab 02 `usms-private-subnet-a` and `-b` | Where new tasks appear when a policy scales out |
| Lab 05 `usms-enrolment-tg` | Where those new tasks are registered, automatically, with no scaling policy involved |

When Lab 06 raises `desiredCount` from 2 to 5, three tasks start and are registered into this target group with nothing else configured: **auto scaling only writes one integer.**

**Before the next session, confirm all five of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-04.sh | tail -2
./scripts/utilities/verify-lab-05.sh | tail -2
grep -c '^export' configs/lab-05.env
aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].[desiredCount,runningCount,length(loadBalancers),length(deployments)]' --output text
aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].[TargetType,length(LoadBalancerArns)]' --output text
```

You want: `FAIL=1` from the first (the one expected failure) or `FAIL=0` after Exercise 2; `FAIL=0` from the second; **15** (or 16 after Exercise 5); desired count **2** with **1** load balancer entry and **1** deployment; and `ip` with **1** attached load balancer. Lab 06 Step 12 sets a minimum of 2, so arrive at the baseline.

Take a snapshot so a Lab 06 mistake is recoverable:

```bash
floci snapshot save lab-05-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-05.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-05.tar.gz
```

---

## Appendix - New CLI and JMESPath patterns

Labs 1 to 04 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `starts_with()`, `@`, slices, flattening with `[]`, `--filters`,
`--generate-cli-skeleton`, `--cli-input-json`, `--max-items`, waiters and nested CLI shorthand. This lab
adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `Attributes[?Key=='x'].Value` then `\| [0]` | A raw string literal in single quotes inside a filter - the counterpart to the backtick form for JSON literals | Step 7, Section 8 |
| A filter with `\|\|` | Boolean **or** inside a filter expression, to select two named attributes in one call | Step 7 |
| A filter with `&&` | Boolean **and**, combining a boolean literal in backticks with a string in single quotes | Step 13 |
| `sort_by(Listeners,&Port)` | An **expression reference** with `&`, telling `sort_by` which field to order on | Step 16 |
| `Listeners[?Port==` + backtick + `80` + backtick + `]` then `\| [0]` | A numeric JSON literal in backticks, which must be escaped as a backslash-backtick inside an unquoted heredoc or a double-quoted shell string | Steps 16, 18, Section 8 |
| `describe-tags --resource-arns A B` | Several ARNs in one call, returning a `TagDescriptions` list - unusual for an AWS `describe-tags` | Step 17 |
| `--subnets a b` | A space-separated list of strings, which is a **third** CLI list convention alongside `--tags Key=,Value=` and `awsvpcConfiguration={subnets=[a,b]}` | Step 5 |
| `--attributes Key=k,Value=v Key=k2,Value=v2` | A list of key-value structures, repeated, space separated | Steps 5, 7 |
| `--default-actions file://...` and `--conditions file://...` | Nested structures passed as documents. The only sane form once an action has a config block | Steps 8, 15 |
| `--security-group-rule-ids sgr-...` | Revoke one specific rule by its own ID rather than by restating the whole permission | Step 13 |
| A nested command substitution inside an unquoted heredoc | Finding a listener requires its load balancer's ARN, and there is no `describe-listeners --names` | Step 18 |
| `getent hosts` with a `python3 socket` fallback | Resolving a name portably, because `getent`, `host` and `dig` are not all present on macOS and Linux | Step 12 |
| `curl -w '%{http_code} %{time_total}'` | Print selected transfer variables after a request | Steps 12, 15 |
| `case "$ip" in 10.0.3.*)` | Classifying an address against a known CIDR in pure shell, with no tooling | Step 12 |

ELBv2 is **ARN-first**: only `describe-load-balancers --names` and `describe-target-groups --names` accept a name, and listeners and rules have no name at all. That is why Step 16 re-derives by name and walks down to the listener, and why `configs/lab-05.env` records ARNs.

```text
ECS control-plane calls     --cluster usms-ecs-cluster --service usms-enrolment-svc
ECS tagging calls           --resource-arn arn:aws:ecs:...:service/usms-ecs-cluster/usms-enrolment-svc
Application Auto Scaling    --resource-id service/usms-ecs-cluster/usms-enrolment-svc
ELB request-count metric    ResourceLabel app/<lb-name>/<lb-id>/targetgroup/<tg-name>/<tg-id>
```

Four identifier styles for one architecture; the last (Exercise 5) is built from fragments of two ARNs.

---

## Sources

- [What is an Application Load Balancer?](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/introduction.html)
- [Application Load Balancer listeners](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html)
- [Listener rules for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-update-rules.html)
- [Target groups for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html)
- [Target group health checks](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html)
- [Register IP addresses as targets](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-register-targets.html)
- [Deregistration delay and connection draining](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-target-group-attributes.html)
- [Application Load Balancer troubleshooting, including the HTTP error codes](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html)
- [Security groups for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-update-security-groups.html)
- [Using a load balancer with an Amazon ECS service](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html)
- [Amazon ECS service definition parameters, including healthCheckGracePeriodSeconds](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service_definition_parameters.html)
- [Amazon ECS deployment types and the rolling update](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html)
- [Fargate task networking with awsvpc mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
- [Application Auto Scaling PredefinedMetricSpecification, including ResourceLabel](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_PredefinedMetricSpecification.html)
- [CloudWatch metrics for your Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html)
- [Elastic Load Balancing quotas](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-limits.html)
- [Elastic Load Balancing pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- [AWS Certificate Manager - requesting a public certificate](https://docs.aws.amazon.com/acm/latest/userguide/gs-acm-request-public.html)
- [`aws elbv2` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/elbv2/)
- [`aws ecs` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/)
- [JMESPath specification](https://jmespath.org/specification.html)

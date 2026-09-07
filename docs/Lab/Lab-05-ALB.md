# Lab 04B — Putting the ECS Service Behind an Application Load Balancer

*Practical 2, Part B — giving the USMS enrolment service a front door, and assessing what you have built*

---

## 1. Lab Overview

Part A left you with a service that works and that nothing can reach.

`usms-enrolment-svc` runs two Fargate tasks in private subnets. Each task has its own elastic network
interface, its own private address, and a security group that admits the web tier. And every one of
those addresses is temporary: a task that stops takes its address with it, and a task that starts
invents a new one. There is no name, no fixed address, and nothing that survives a deployment. The
service is real, and there is no sentence you can write in a client's configuration file that points at
it.

This laboratory fixes that, and the fix is the single most common piece of AWS architecture in
existence: an **Application Load Balancer** in front of a **target group**, with an **ECS service**
registering and deregistering its own tasks as targets.

The word to hold on to for the next four hours is **indirection**. The load balancer is a stable name
in front of an unstable set of addresses. Nothing about the tasks becomes more permanent; instead,
something permanent is placed in front of them, and the job of keeping that thing's idea of reality up
to date is given to the ECS service. You will never type a task's address into a target group. If you
find yourself about to, something has gone wrong, and Step 10 explains what.

Four objects, exactly as Part A had four:

```text
load balancer   a DNS name, in two or more Availability Zones, holding security groups
listener        one port and protocol on that load balancer, with ONE default action
rule            a condition and an action, evaluated in priority order before the default
target group    a set of targets plus a health check that decides which of them get traffic
```

Part A's warning applies again, in a new costume. Students who keep those four apart find load
balancing obvious. Students who conflate them spend an afternoon looking for the health check on the
load balancer, where it has never been.

The lab closes with an **in-class assessment**, in Section 14. It is done at the machine, in the
session, individually, and it is marked from your own repository. Section 14.1 gives you the tasks, the
timing and the marking rubric in full, so that nothing about it is a surprise except the fault your
instructor injects for Task B.

**Time:** roughly 3 hours for Sections 8 and 9, plus 75 minutes for the assessment.

**Where this sits in the course**

```text
Lab 01   IAM ................. roles, policies, instance profile
Lab 02   VPC ................. subnets, NAT, route tables, security groups
Lab 03   EC2 ................. usms-web-01 and usms-db-01 in that network
Lab 04A  ECS + Fargate ....... the cluster, the blueprint, the service, and how to operate them
Lab 04B  ECS + ALB ........... THIS LAB — the front door, and the in-class assessment
Lab 04C  Service Auto Scaling  the same service, made elastic  (lab-04-ecs-autoscaling.md)
Lab 05   S3 .................. the bucket that two IAM policies already name
Lab 06   Lambda .............. functions triggered from that bucket
```

!!! info "Where auto scaling went, and why it comes after this lab"
    `lab-04-ecs-autoscaling.md` is **Lab 04C**, and you will do it in the session after this one. Part A
    hands off to this document; this document hands off to that one.

    The ordering is not administrative. Read this table from the auto scaling lab's own Step 14:

    | Predefined metric | Needs |
    | --- | --- |
    | `ECSServiceAverageCPUUtilization` | Container Insights |
    | `ECSServiceAverageMemoryUtilization` | Container Insights |
    | `ALBRequestCountPerTarget` | A load balancer, which that lab says the course has not built |

    The third row is the best scaling signal a web service has, and that lab is forced to use CPU and
    to say so, because when it was written there was no target group in the architecture. After this
    laboratory there is one. Exercise 5 builds the exact `ResourceLabel` string that unlocks it, and
    the auto scaling lab is a better lab for having a load balancer underneath it.

    Nothing in this document renames or deletes anything that document uses. It writes
    `configs/lab-04b.env`; Part A wrote `configs/lab-04a.env`; the auto scaling lab writes
    `configs/lab-04.env`. All three files are meant to coexist, and Lab 04C sources the first two.

!!! warning "This lab deliberately changes one thing Part A built, and Part A's script will notice"
    Step 13 removes the rule that let `usms-web-01` talk to the enrolment tasks directly, because after
    this lab it talks to them through the load balancer instead. That is the correct outcome, and it
    means `scripts/utilities/verify-lab-04a.sh` will afterwards report **exactly one** failure:

    ```text
      FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
    ```

    That failure is not a mistake in your work. It is a verification script that encodes an
    architecture which has since changed — which is itself worth noticing, because it happens
    constantly on real systems. Section 11 says what to do about it, and Exercise 2 asks you to fix it
    properly. From Step 13 onward, `verify-lab-04b.sh` is the script of record.

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. Explain why a set of Fargate tasks cannot be addressed directly, and what a load balancer adds that
   a DNS record alone would not.
2. Name the four Elastic Load Balancing objects, say which one holds the health check, which one holds
   the security group, and which one holds the port a client connects to.
3. Choose between an Application, Network and Gateway Load Balancer for a stated requirement, and
   justify the choice in one sentence.
4. Explain why a target group serving Fargate tasks must have `--target-type ip`, and what would happen
   with `instance`.
5. Create an internet-facing Application Load Balancer across two Availability Zones, in Lab 2's public
   subnets, with its own security group.
6. Create a target group with a deliberate health check configuration, and explain each of its five
   numbers in terms of how long a broken task keeps receiving traffic.
7. Distinguish the **container** health check from Part A's revision 2 from the **target group** health
   check created here, and describe a state in which one says healthy and the other says unhealthy.
8. Create a listener with a default action, add a rule with a condition and a non-forward action, and
   explain how priority ordering decides which one fires.
9. Attach an existing ECS service to a target group, and explain why you never call `register-targets`
   yourself for a Fargate service.
10. Explain what `--health-check-grace-period-seconds` prevents, and describe the failure loop that
    occurs without it.
11. Read `describe-target-health` and interpret `initial`, `healthy`, `unhealthy`, `draining` and
    `unused`.
12. Perform the security cutover from a direct client to a load-balanced one, and prove from the
    security group alone that the load balancer is now the only thing that can reach the tasks.
13. Explain how `deregistration_delay.timeout_seconds`, ECS `minimumHealthyPercent` and the container's
    `stopTimeout` interact during a deployment, and what a request in flight experiences.
14. Prove that the load balancer, its listener, its rule, its target group and the service's attachment
    to it all survive a restart of the emulator, deriving every ARN from the API.

---

## 3. Prerequisites

- **Lab 04A complete**, with `./scripts/utilities/verify-lab-04a.sh` reporting `FAIL=0` **before you
  start this lab**. Run it now, not after Step 13.
- **Lab 2 complete including its Step 11 "Your turn"**, so that `usms-public-subnet-b` exists. An
  Application Load Balancer requires at least two subnets in two different Availability Zones and
  refuses to be created with one. This is the hardest prerequisite in the lab and the one most often
  missing.
- **Lab 2 Exercise 5 complete**, so that `usms-private-subnet-b` exists — Part A's service already needs
  it.
- **Lab 3 complete**, with `usms-web-01` running and carrying `usms-app-sg`. Step 17 resolves a group
  reference back to it.
- **Errata 01 applied.** If `echo "$AWS_PROFILE"` in a brand-new terminal prints nothing, stop and apply
  Errata 01 first.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq` and `python3` available. `python3` is used for timestamps and JSON, because GNU `date` and BSD
  `date` disagree about every flag that matters.

Check all of that in one go:

```bash
cd ~/aws-floci-course
for t in jq python3 docker curl; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
./scripts/utilities/floci-storage-check.sh
```

> Example output — your versions and paths will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
curl       /usr/bin/curl
aws-cli/2.17.42 Python/3.11.9 Darwin/23.5.0 exe/x86_64
...
PASS=16  FAIL=0
```

**What to look for:** four tools found, and `PASS=16  FAIL=0` from the storage check. A failure in that
script's `shell and profile` block is the real problem and everything below it is a consequence — fix
that block before starting.

`curl` is listed for the first time in this course because Step 12 tries to reach the load balancer over
HTTP. If it is missing, install it or use `wget`; Step 12 gives both, and neither is essential to
passing the lab.

---

## 4. Connection to Previous Labs

### 4.1 Current Environment

```text
Created in previous labs:
- Lab 01: Floci under Compose, hybrid storage, persistence proven
- Lab 01: groups usms-admins / usms-developers / usms-auditors; three users
- Lab 01: roles  usms-ec2-app-role, usms-lambda-exec-role, usms-developer-role
- Lab 01: policies USMSDeveloperBase (v2), USMSStudentDataReadWrite, USMSAssumeAppRoles,
                   USMSLambdaBasic, USMSSelfManageCredentials (inline)
- Lab 01: instance profile usms-ec2-app-profile
- Lab 01: configs/course.env, configs/lab-01.env
- Lab 02: usms-vpc 10.0.0.0/16, DNS support and hostnames enabled
- Lab 02: usms-public-subnet-a / -b, usms-private-subnet-a / -b
- Lab 02: usms-igw, usms-nat (+ Elastic IP), usms-public-rt, usms-private-rt
- Lab 02: usms-app-sg, usms-db-sg, usms-private-nacl, usms-s3-endpoint
- Lab 02: configs/lab-02.env, scripts/utilities/verify-lab-02.sh
- Lab 03: usms-web-01 (public subnet a, usms-app-sg, usms-ec2-app-profile, usms-web-eip)
- Lab 03: usms-db-01 (private subnet a, usms-db-sg, no public address)
- Lab 03: usms-web-data-vol, usms-web-golden, usms-app-key
- Lab 03: configs/lab-03.env, scripts/utilities/verify-lab-03.sh
- Lab 04A: usms-ecs-cluster, Container Insights enabled
- Lab 04A: /usms/ecs/enrolment log group, retention 7 days
- Lab 04A: usms-ecs-exec-role (+ USMSECSTaskExecution), usms-ecs-task-role (+ Lab 01's S3 policy)
- Lab 04A: usms-enrolment-sg, admitting tcp/80 from usms-app-sg
- Lab 04A: usms-enrolment:1 and usms-enrolment:2, two immutable revisions
- Lab 04A: usms-enrolment-svc, desired 2, both private subnets, no public address
- Lab 04A: configs/lab-04a.env, scripts/utilities/verify-lab-04a.sh

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
- templates/lab-04b-listener-default-actions.json, templates/lab-04b-rule-conditions.json,
  templates/lab-04b-rule-actions.json, templates/lab-04b-service-load-balancers.json
- configs/lab-04b.env
- scripts/utilities/verify-lab-04b.sh
- scripts/cleanup/lab-04b-cleanup.sh

Required for future labs:
- usms-enrolment-tg             -> Lab 04C's ALBRequestCountPerTarget metric names this target group
- USMS_ALB_RESOURCE_LABEL       -> Lab 04C Exercise material; built in this lab's Exercise 5
- usms-enrolment-alb            -> the CloudFormation lab re-declares this whole stack
- usms-enrolment-svc            -> Lab 04C scales it; it is now load balanced, which changes the metric
- usms-alb-sg                   -> the HTTPS/ACM material, whenever this course reaches it
- configs/lab-04b.env           -> Lab 04C sources it alongside lab-01/02/03/04a
```

### 4.2 What this lab genuinely reuses

Not mentions — uses.

| From | Used here how |
| --- | --- |
| Lab 2 `usms-public-subnet-a` and `-b` | Step 5 places the load balancer's nodes in both, by ID from `configs/lab-02.env`. This is the first thing in the course that has *required* two public subnets |
| Lab 2 `usms-igw` and `usms-public-rt` | Step 5 explains, and Step 12 tests, that this is the only reason an internet-facing load balancer is reachable at all |
| Lab 2 `usms-vpc` | Step 6 creates the target group inside it. A target group belongs to exactly one VPC, forever |
| Lab 2 `usms-app-sg` | Step 13 removes it as a source, having replaced it with the load balancer's group. Step 17 resolves it back to `usms-web-01` |
| Lab 3 `usms-web-01` | Step 17 closes the loop: the portal is still the caller, but now it calls a name instead of a set of addresses |
| Lab 04A `usms-enrolment-svc` | Step 10 attaches the existing service to the target group. No new service is created |
| Lab 04A `usms-enrolment:2` | Step 10's `containerName` and `containerPort` must match this revision's `enrolment-api` and `80` exactly |
| Lab 04A `usms-enrolment-sg` | Steps 9 and 13 change its ingress from the web tier to the load balancer |
| Lab 04A `usms-ecs-cluster` | Every `ecs` call in this lab names it |
| `configs/course.env` names | `$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT` used, never redeclared |

### 4.3 The sentence that makes this lab worth doing

Part A ended with an architecture in which the enrolment tasks had no name. Everything about them was
correct and nothing about them was reachable.

The reason that matters is not aesthetic. Part A's Step 9 wrote a security group rule sourced from a
*group* rather than an address, and gave a reason: **the tasks have no stable addresses**, so any rule
written against one of them is wrong before you finish typing it. That was true of the firewall, and it
is equally true of every client, every configuration file, every monitoring probe and every DNS record
anyone might want to write.

A load balancer is the general answer to that problem, and the security group rule was a special case
of it. When you reach Step 10 and the ECS service starts registering its own tasks into the target
group, notice that you are watching exactly the same idea at a different layer: **something else keeps
the list of addresses up to date, so that you never have to.**

Say that out loud before you continue. It is Review Question 1.

### 4.4 What changes, and what deliberately does not

| | Before this lab | After this lab |
| --- | --- | --- |
| Client of the enrolment API | `usms-web-01` directly, by address | `usms-web-01` via `usms-enrolment-alb`, by name |
| `usms-enrolment-sg` ingress | tcp/80 from `usms-app-sg` | tcp/80 from `usms-alb-sg` |
| Tasks' subnets | private a and b | unchanged |
| Tasks' public address | none | still none — this is the point |
| Service `desiredCount` | 2 | unchanged |
| Task definition | `usms-enrolment:2` | unchanged. No new revision is registered |
| Service `loadBalancers` | empty | one entry |
| Health checking | container health check only | container health check **and** target group health check |

Note the last two rows of the middle column. The tasks do not become public, and no new blueprint is
built. This lab adds a front door to a building that is otherwise unchanged.

---

## 5. What We Are Building

An internet-facing Application Load Balancer, in the public subnets, forwarding to the private Fargate
tasks that Part A created.

Five decisions justify the shape of what follows, and each is defensible in one sentence.

**The load balancer is internet-facing; the tasks are not.** This is the canonical pattern and the
reason a public subnet exists at all. The load balancer's nodes have public addresses; the tasks keep
their private ones; the only path between the internet and a task passes through a listener you
configured and a security group you wrote. Exercise 4 asks you to argue for `--scheme internal`
instead, and there is a real case for it here.

**The target group is `--target-type ip`.** A Fargate task has no instance ID, so it cannot be
registered by one. `ip` is not a preference; it is the only value that works, and choosing `instance`
produces an error at attachment time rather than at creation time, which is much later than you would
like.

**The health check is on the target group, and it is not the same health check as Part A's.** Part A's
revision 2 added a container health check that runs *inside* the task. This lab adds a health check
that the load balancer runs *from outside*. They can disagree, and Step 11 shows what that looks like.

**Two Availability Zones, because the load balancer insists.** An ALB places a node in each subnet you
give it and returns all of them from DNS. With one subnet it is a single point of failure, and the API
refuses. That constraint is why Lab 2's second public subnet — an optional "Your turn" at the time —
becomes mandatory today.

**The direct path is removed at the end, not the beginning.** Step 9 adds the load balancer's access
while the web tier still has its own, Step 12 proves the new path, and only then does Step 13 take the
old one away. Cutting over in that order is the difference between a migration and an outage, and it is
worth doing deliberately once so that the habit is there when it matters.

### 5.1 The configuration baseline this lab establishes

```text
scheme               internet-facing    nodes in public subnets a and b, with public addresses
type                 application        HTTP-aware; layer 7; rules can match paths and headers
listener             HTTP : 80          one default action, plus one rule at priority 10
target group type    ip                 mandatory for awsvpc; the only value Fargate accepts
target group port    HTTP : 80          matches enrolment-api's containerPort from Lab 04A
health check         GET /  every 30s   timeout 5s, healthy 2, unhealthy 2, matcher 200
deregistration delay 30 seconds         in-flight requests get 30 seconds before the task dies
grace period         60 seconds         ECS ignores target health for the first 60s of a task's life
task inbound         tcp/80 from usms-alb-sg ONLY
```

Every one of those is a decision with a reason, and the in-class assessment asks you to defend three of
them.

---

## 6. Architecture

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
  ||   usms-private-rt   0.0.0.0/0 -> usms-nat        (image pull, Lab 04A)||
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

  Lab 04C adds, against the same service and this lab's target group:
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

## 7. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-04b-ecs-alb/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 13 and Section 14.1
├── policies/
│   ├── usms-alb-sg-ingress.json                       # NEW — the load balancer's inbound rule
│   └── usms-enrolment-sg-ingress-alb.json             # NEW — the tasks' new inbound rule
├── templates/
│   ├── lab-04b-listener-default-actions.json          # NEW — create-listener --default-actions
│   ├── lab-04b-rule-conditions.json                   # NEW — create-rule --conditions
│   ├── lab-04b-rule-actions.json                      # NEW — create-rule --actions
│   └── lab-04b-service-load-balancers.json            # NEW — update-service --load-balancers
├── configs/
│   └── lab-04b.env                                    # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-04b.sh                          # NEW — Section 9
│   └── cleanup/
│       └── lab-04b-cleanup.sh                         # NEW — end of course only
└── outputs/
    └── lab-04b-*.json / *.txt                         # command output, git-ignored
```

The same split as Part A, for the same reason. The two security group documents **grant** something, so
they live in `policies/`. The four load balancer documents are **API request bodies**, so they live in
`templates/`. A reviewer opening `policies/` should be looking at your security posture and nothing
else.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-04b-ecs-alb
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04a-ecs-fargate  labs/lab-04b-ecs-alb
```

---

## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Every path below (`configs/...`, `policies/...`, `templates/...`, `scripts/...`) is relative to that
    directory. If a command reports `No such file or directory`, check `pwd` first.

    This lab captures **six ARNs**, and Elastic Load Balancing is an ARN-first API: almost nothing in it
    takes a bare name, and the two calls that do take `--names` are read-only. Capture every one with
    `$(...)`, `--query` and `--output text`. Shell variables die with the terminal, which is why Step 18
    writes them all to `configs/lab-04b.env`.

### Step 1 — Resume the environment and load five env files

**Purpose**

Bring Floci up and load everything the previous four labs recorded. This lab reads eight values from
`configs/lab-02.env`, `lab-03.env` and `lab-04a.env`, and two of them — the public subnets — are the
ones most likely to be missing.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04a.env

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

**What the command does**

`floci-up.sh` is idempotent: it starts the container if it is stopped, says so if it is already running,
and refuses to adopt a container that Compose did not create. `whoami.sh` exits 1 if the account is not
`000000000000`, which is the guard that stops a course command reaching a real AWS account.

Five env files is now the standard opening. They are additive and independent: sourcing them in any
order gives the same result, because no two of them define the same variable.

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

> Example output — your IDs will differ.

**Verify**

Twelve non-empty values. Two failures matter more than the rest, and both stop this lab dead:

- **`public subnet b` empty** means Lab 2's Step 11 "Your turn" was skipped. Go and do it now. An
  Application Load Balancer requires subnets in at least two Availability Zones and
  `create-load-balancer` will refuse with `ValidationError: At least two subnets in two different
  Availability Zones must be specified`. There is no workaround, and no other step in this lab can
  proceed without it.
- **`enrolment sg` empty** means `configs/lab-04a.env` was never written or is incomplete. Re-run Part A
  Step 20 before continuing.

If `public subnet b` is missing, the shortest correct fix is Lab 2's own command, with Lab 2's CIDR and
Availability Zone. Do not invent a new one, and do not put it in the same AZ as subnet a — that would
satisfy `describe-subnets` and still fail `create-load-balancer`, which checks the zones and not the
count.

---

### Step 2 — Confirm Labs 2, 3 and 04A are still intact

**Purpose**

This lab modifies a security group that Part A created and attaches a load balancer to a service Part A
created. Confirm both are exactly as Part A left them **before** you change anything, because after
Step 13 one of these scripts is expected to fail and you need to know that the failure is yours and
deliberate rather than pre-existing.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
./scripts/utilities/verify-lab-02.sh | tail -3
./scripts/utilities/verify-lab-03.sh | tail -3
./scripts/utilities/verify-lab-04a.sh | tee outputs/lab-04b-pre-verify-04a.txt | tail -3
```

**What the command does**

Each script checks its own lab's resources and, first, the shared environment. All three were written in
their own labs; you are only running them. `tail -3` keeps the output readable — if a count is wrong,
re-run the script without the pipe and read all of it.

The third one is captured into `outputs/` on purpose. After Step 13 you will run it again, and having
the "before" alongside the "after" is what turns a failing check into evidence rather than a worry.

**Expected result**

```text
PASS=33  FAIL=0
PASS=36  FAIL=0
PASS=49  FAIL=0
```

> Example output — the counts are the ones those labs stated.

**Verify**

`FAIL=0` three times. If the third one is not `FAIL=0`, **do not start this lab**: fix Part A first,
because every check that fails now will fail again at the end and you will not be able to tell which
failures you caused.

If a failure appears under `== Environment ==` in any of the three, that is the real problem and the
resource failures below it are usually consequences. Fix the environment first with
`./scripts/utilities/floci-storage-check.sh`.

---

### Step 3 — Probe what this Floci build supports for Elastic Load Balancing

**Purpose**

Find out now which parts of ELBv2 your build implements, rather than at Step 10 with a load balancer
half-built. This is the same principle as Part A's Step 3 and Lab 1's storage check: **name the
limitation before it costs you an hour.**

Elastic Load Balancing is the least reliably emulated service this course has touched. Take this step
seriously.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`probe` runs a harmless read, or generates a request skeleton, and reports whether the CLI got an answer
at all. Read the result as "the service responded to me", not "the call succeeded" — one of these is
*expected* to fail on its argument. `describe-listeners --load-balancer-arn probe` passes a string that
is not an ARN, and a `ValidationError` about the ARN format means ELBv2 is very much present. A
completely unsupported service produces a connection error or `InvalidAction`, which is a different
failure and reads differently.

`describe-account-limits` is worth one look on a real account: it is where the per-region caps on load
balancers, target groups, listeners and rules live, and running out of listener rules is a real and
annoying production limit.

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

> Example output — this is the best case. Yours may well differ, and that is exactly why the probe
> exists.

**Verify**

Work out which path you are on and write it at the top of `notes/lab-04b-notes.md`, because your lab
report and the in-class assessment both require you to state it.

| Path | If | What changes |
| --- | --- | --- |
| **A — full** | `describe-load-balancers` and both skeletons answer, and Step 5 later returns an ARN | Do every step as written |
| **B — control plane only** | Objects are created and describable, but targets never become `healthy` and Step 12's `curl` does not connect | Everything in this lab still works. Every proof here is built on control-plane fields, not on a served request. Record where target health stayed `initial` or `unused` and continue |
| **C — no ELBv2** | `describe-load-balancers` does not answer, or `create-load-balancer` fails with `InvalidAction` | Stop and tell your instructor. Do Section 8's interludes, Exercise 4 and Section 14.1 Task C, which need no emulator, and record the whole lab as conceptual |

!!! note "Floci Limitation — Elastic Load Balancing is the least reliably emulated service in this course"
    Depending on your build, ELBv2 may be fully modelled, modelled as a control plane with no data
    path, or absent entirely. A load balancer that exists as an object but forwards no packets is the
    most likely outcome, and it is the one this lab is written for.

    Real AWS provisions load balancer nodes in each subnet within two to four minutes, publishes a DNS
    name that resolves to their addresses, begins health checking each registered target on the
    interval you set, and forwards real requests to the targets that pass.

    Take this away regardless: nothing this lab asks you to prove depends on a request being served.
    The load balancer, its listener, its rule, its target group, its health check configuration, the
    service's `loadBalancers` entry and the security group chain are all control-plane facts, and every
    one of them is observable. Step 12 tries the data path, tells you honestly that it may not work,
    and gives you the control-plane proof to record instead.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01 + lab-02 + lab-03 + lab-04a sourced
 ├── verify-lab-02.sh, verify-lab-03.sh and verify-lab-04a.sh all FAIL=0
 ├── outputs/lab-04b-pre-verify-04a.txt captured, for comparison after Step 13
 ├── BOTH public subnets present, in TWO different Availability Zones
 └── support path recorded: A (full) / B (control plane only) / C (no ELBv2)
```

---

### Interlude — what a load balancer actually is, in four objects

Four nouns again. Keeping them apart makes the rest of this lab easy, and conflating them is what makes
Elastic Load Balancing feel like it has too many ARNs.

**A load balancer** is the thing with a DNS name. It has a scheme (`internet-facing` or `internal`), a
type (`application`, `network` or `gateway`), a list of subnets — one node per subnet — and, for an ALB,
a list of security groups. It has no idea what your application is. It listens for nothing until you
give it a listener.

**A listener** is one port and one protocol on that load balancer: HTTP on 80, HTTPS on 443. A listener
has exactly **one default action**, which is what happens to a request that matches no rule. Most
listeners have exactly one action and no rules, and that is a perfectly good configuration.

**A rule** is a condition plus an action, attached to a listener, with a numeric **priority**. Rules are
evaluated in priority order, lowest number first, and the first match wins; if none match, the
listener's default action runs. Conditions match on path, host header, HTTP method, query string, source
IP or an arbitrary header. Actions forward to a target group, redirect, return a fixed response, or
authenticate. This is what "layer 7" means in practice: the load balancer can read the request before
deciding where it goes.

**A target group** is a set of targets plus a health check. It has a protocol, a port, a VPC and a
target type. Crucially, **the health check lives here** — not on the load balancer, not on the listener.
One target group can be used by several listeners and several load balancers, and it keeps one opinion
about whether each of its targets is healthy.

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

That last line is the one to hold on to. Every other target group you will ever meet is populated by
something: an EC2 Auto Scaling group, an ECS service, or a human running `register-targets`. For a
Fargate service it is the service, and it does it every time a task starts, stops, or is replaced during
a deployment. You supply the target group; the service supplies the targets.

### Interlude — three load balancer types, and how to choose in one sentence

| Type | Layer | Chooses on | Use when |
| --- | --- | --- | --- |
| **Application** (`application`) | 7 — HTTP | Path, host, header, method, query, source IP | The traffic is HTTP or HTTPS and you want to route on its content. This is almost always the answer for a web API |
| **Network** (`network`) | 4 — TCP/UDP/TLS | Nothing about the payload; flow hashing only | You need raw TCP or UDP, extreme throughput, static IP addresses per zone, or protocols an ALB cannot parse |
| **Gateway** (`gateway`) | 3 — IP | Nothing; it transparently inserts appliances | You are inserting a firewall or inspection appliance into the packet path |

The USMS enrolment API speaks HTTP and will eventually want to route `/enrolment` and `/transcripts` to
different services from one hostname. That is an ALB, and it is the type this lab builds.

Two differences from a Network Load Balancer are worth remembering because they change your design:

- An ALB **has security groups**; a classic NLB configuration does not, which means the target's own
  security group must admit the client's address range rather than a group.
- An ALB **terminates the connection** and opens a new one to the target. The target therefore sees the
  load balancer's private address as the source, not the client's — which is why
  `X-Forwarded-For` exists and why "my access logs show one IP address" is a question rather than a bug.

### Interlude — target types, and why Fargate has no choice

| `--target-type` | A target is identified by | Works with |
| --- | --- | --- |
| `instance` | An EC2 instance ID and a port | EC2 instances; ECS tasks in `bridge` or `host` network mode |
| `ip` | An IP address and a port, inside the VPC or a peered range | `awsvpc` tasks, including **every Fargate task**; on-premises servers reached over Direct Connect |
| `lambda` | A Lambda function ARN | A function invoked directly by the load balancer |
| `alb` | Another Application Load Balancer | An NLB fronting an ALB |

Part A's task definition set `networkMode` to `awsvpc`, because Fargate requires it. An `awsvpc` task
has **no instance ID** — there is no instance. It has an elastic network interface with an address, and
an address is what `ip` registers.

Getting this wrong is a slow failure rather than a fast one, which is why it is worth stating plainly:
`create-target-group --target-type instance` succeeds. The target group is created and looks fine. The
error arrives at Step 10, when `update-service` refuses the attachment, and the message names the
network mode rather than the target type. Choose `ip`.

### Interlude — the two health checks, which are not the same health check

This is the most-confused pair in this lab, exactly as the two IAM roles were in Part A. Learn the
distinction here rather than at Step 11.

| | Container health check | Target group health check |
| --- | --- | --- |
| Added in | Lab 04A Step 11, revision 2 | This lab, Step 6 |
| Configured in | The task definition's `healthCheck` block | The target group |
| Run by | The container runtime, **inside** the task | The load balancer, **from outside**, across the network |
| Command or request | A shell command in the container (`wget ... \|\| exit 1`) | An HTTP request to a path (`GET /`) |
| Reports into | `healthStatus` on the task: `HEALTHY`, `UNHEALTHY`, `UNKNOWN` | Target health: `initial`, `healthy`, `unhealthy`, `draining`, `unused` |
| Consequence of failing | ECS stops and replaces the task | The load balancer stops sending it requests; ECS also replaces it, after the grace period |
| Sees | Whether the process is alive and answering itself | Whether the process is reachable **through the security group and the network** |

The last row is the one that earns its place. A task can be `HEALTHY` to ECS and `unhealthy` to the load
balancer at the same time, and the combination has exactly one meaning: **the application is fine and
the network path is not.** In this lab that would mean Step 9's security group rule is missing or wrong.
On a real account it is one of the two or three most common production incidents, and being able to read
those two fields together is what shortens it from an hour to a minute.

The reverse combination — `UNKNOWN` to ECS and `healthy` to the load balancer — is not a fault at all.
It is simply a task definition with no container health check, which is what Part A's revision 1 was.

---

### Step 4 — Create the load balancer's security group

**Purpose**

An Application Load Balancer has its own security group, separate from anything else in the
architecture. It is the boundary between the internet and everything you built in Part A, and it is the
only object in this course that will deliberately admit `0.0.0.0/0`.

**Run from**

```text
aws-floci-course/
```

**Concept first — why the load balancer needs a group of its own**

You could, in principle, put the load balancer in `usms-app-sg` and save yourself an object. Do not. A
security group is the unit in which you express "who may talk to this tier", and the load balancer is
its own tier: the only thing in the architecture that the internet may reach, and the only thing that
may reach the enrolment tasks. Sharing a group with the web instance would mean that any rule you ever
add for one silently applies to the other, and that the reverse lookup in Step 17 would give an
ambiguous answer.

One group per tier. Three tiers, three groups, and each group's ingress names the group above it —
which is the pattern Lab 2 started with `usms-db-sg` and this lab completes.

**Command — part 1, the group**

```bash
ALB_SG=$(aws ec2 create-security-group \
  --group-name usms-alb-sg \
  --description "USMS enrolment load balancer: HTTP from the internet; forwards to usms-enrolment-sg" \
  --vpc-id "$USMS_VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=usms-alb-sg},{Key=Project,Value=USMS},{Key=Tier,Value=edge},{Key=Lab,Value=04B}]' \
  --query 'GroupId' \
  --output text)

echo "ALB_SG = $ALB_SG"
```

**Command — part 2, the ingress rule**

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

**What the command does**

This heredoc is `<< 'EOF'`, **quoted**, because the document contains no variables and must reach disk
exactly as written. Compare it with Step 9's document three steps from now, which contains
`$ALB_SG` and therefore **must** use the unquoted `<< EOF`. Two nearly identical files, opposite
quoting, for opposite reasons — and this is the third lab in a row in which that distinction has been
the most common silent bug. The rule is always the same question: *do I want this expanded now, or
later?*

`Tier=edge` is a new tag value. Part A used `Tier=app` for everything in the cluster; the load balancer
is not part of the application tier, it is in front of it, and tagging it accordingly is how a cost
report or a security review can separate "things exposed to the internet" from "things that are not".

!!! warning "This is the only `0.0.0.0/0` ingress rule in the whole course, and it is deliberate"
    Every other security group in this architecture is sourced from another group. This one is not,
    because an internet-facing load balancer that only admits a named group is a load balancer nobody
    can use.

    What makes it acceptable is everything *behind* it: the load balancer terminates the connection,
    only forwards to the one target group you configured, and the tasks themselves admit nothing but
    this group. The blast radius of `0.0.0.0/0` here is "somebody can send an HTTP request to a
    listener", not "somebody can reach a task".

    On a real account you would narrow it anyway where you can — to a CDN's published address ranges,
    or to your campus network for an internal tool — and you would put HTTPS on 443 in front of it. The
    "Your turn" below is the first half of that.

**Expected result**

```text
ALB_SG = sg-0bb22cc33dd44ee55
valid JSON
sgr-0aabb11223344cc55
```

> Example output — your IDs will differ.

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$ALB_SG" \
  --query 'SecurityGroups[0].{Name:GroupName,VPC:VpcId,Inbound:IpPermissions[].{Port:FromPort,CIDR:IpRanges[0].CidrIp,FromGroup:UserIdGroupPairs[0].GroupId},OutboundRules:length(IpPermissionsEgress)}' \
  --output json
```

**What to look for:** exactly one inbound rule, on port 80, whose `CIDR` is `0.0.0.0/0` and whose
`FromGroup` is `null`. This is the one place in this course where those two values are the right way
round; everywhere else the reverse is true.

`OutboundRules` is `1` — the allow-all egress rule AWS created for you and you never wrote. That is what
lets the load balancer open connections *to* the targets, and Step 9 is the other half of the same
conversation.

✏️ **Your turn**

Add a second inbound rule to `usms-alb-sg` for tcp/443 from `0.0.0.0/0`, using a JSON document in
`policies/` rather than the shorthand form.

```text
Expected result:
usms-alb-sg has two inbound rules, on ports 80 and 443, both from 0.0.0.0/0.

Then answer in two sentences in notes/lab-04b-notes.md:
The load balancer still will not serve a single HTTPS request. Name the TWO things
that are missing, and say which of the two AWS can give you for free and which one
you have to obtain from somewhere.
```

Hint: a security group rule opens a port on the firewall; it does not make anything listen on it.
Re-read the interlude's description of a listener, and then think about what an HTTPS listener needs
that an HTTP one does not. The AWS Certificate Manager documentation answers the second half in its
first paragraph.

---

### Step 5 — Create the Application Load Balancer

**Purpose**

The stable name. Everything after this step either points at it or is pointed at by it.

**Run from**

```text
aws-floci-course/
```

**Concept first — what "internet-facing" and "two subnets" actually mean**

A load balancer is not one machine. AWS places a **node** in each subnet you name, gives each node an
address, and publishes a DNS name that resolves to all of them. A client resolves the name, gets several
addresses, picks one, and connects to that node; the node then chooses a target and opens a second
connection to it.

Two consequences follow, and both matter:

- **`--scheme internet-facing` means the nodes get public addresses**, which requires the subnets you
  name to have a route to an internet gateway. Lab 2's `usms-public-rt` is that route. Naming a private
  subnet here produces an error about the subnet not having an internet gateway route, which is one of
  the clearer AWS error messages.
- **Two Availability Zones is a hard requirement**, not a recommendation. A single-zone load balancer
  would be a single point of failure in front of a multi-zone service, which is worse than useless.

`--scheme internal` is the alternative: nodes with private addresses only, in private subnets, resolving
to a name only things inside the VPC can reach. It is the right answer for a service that genuinely has
no external clients, and Exercise 4 asks you to argue that USMS enrolment is such a service.

**Command — part 1, create it**

```bash
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name usms-enrolment-alb \
  --type application \
  --scheme internet-facing \
  --ip-address-type ipv4 \
  --subnets "$USMS_PUBLIC_SUBNET_A" "$USMS_PUBLIC_SUBNET_B" \
  --security-groups "$ALB_SG" \
  --tags Key=Name,Value=usms-enrolment-alb Key=Project,Value=USMS Key=Tier,Value=edge Key=Lab,Value=04B \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)

echo "ALB_ARN = $ALB_ARN"

ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].DNSName' --output text)

echo "ALB_DNS = $ALB_DNS"
```

**What the command does**

```text
aws
 └── elbv2                        the SERVICE — Elastic Load Balancing, API version 2
      └── create-load-balancer    the OPERATION
           ├── --name             1 to 32 characters, alphanumeric and hyphens, no leading or
           │                      trailing hyphen. It becomes part of the ARN and part of the DNS name
           ├── --type             application | network | gateway
           ├── --scheme           internet-facing | internal
           ├── --ip-address-type  ipv4 | dualstack
           ├── --subnets          ONE PER AVAILABILITY ZONE, at least two, space separated
           ├── --security-groups  ALB only. A network load balancer takes none
           └── --tags             Key= / Value= with CAPITALS — the fourth convention in two labs
```

**The tag syntax is capitalised here**, like IAM, unlike ECS's lower-case `key=`/`value=`, unlike EC2's
`--tag-specifications` wrapper, unlike CloudWatch Logs' plain map. Part A promised there was no rule
connecting them and this is the fourth data point. Run `aws elbv2 create-load-balancer help` and read
the `--tags` synopsis; that habit is more durable than memorising any of the four.

Note that `--subnets` is a **space-separated list**, not comma-separated, and not the `awsvpcConfiguration=
{subnets=[a,b]}` shorthand you fought with in Part A. The AWS CLI has at least three ways of expressing a
list of strings and which one applies depends on the parameter's shape in the service model. When in
doubt, `--generate-cli-skeleton` shows you.

`--name` has a real 32-character limit and this course's naming convention gets close to it.
`usms-enrolment-alb` is 18 characters. `usms-enrolment-application-load-balancer` would be rejected, and
the error names the constraint clearly, which is more than can be said for many.

**Expected result**

```text
ALB_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
ALB_DNS = usms-enrolment-alb-1234567890.us-east-1.elb.amazonaws.com
```

> Example output — your ARN suffix and DNS name will differ, and on Floci the DNS name may take a
> different form entirely, such as one ending in `elb.localhost.localstack.cloud`. Record whichever you
> get.

Look hard at the shape of that ARN. The part after `loadbalancer/` is `app/usms-enrolment-alb/<id>` —
the type, the name and a generated identifier. That three-part suffix is not decoration: Exercise 5
needs it verbatim to build the `ResourceLabel` string that Lab 04C's request-count scaling policy
consumes. This is the same lesson as Part A's `service/<cluster>/<service>` composite: AWS builds
resource identifiers out of ARN fragments in more than one place, and knowing where the fragments come
from is the difference between constructing one and guessing at one.

**Command — part 2, wait for it, then read it back**

```bash
aws elbv2 wait load-balancer-available --load-balancer-arns "$ALB_ARN" \
  && echo "load balancer available" \
  || echo "waiter did not complete — poll manually below (expected on some builds)"

for i in $(seq 1 10); do
  STATE=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
    --query 'LoadBalancers[0].State.Code' --output text)
  printf 'poll %2d  state=%s\n' "$i" "$STATE"
  [ "$STATE" = "active" ] && break
  sleep 10
done
```

**What the command does**

`aws elbv2 wait load-balancer-available` is a **waiter**, the same mechanism as Lab 3's `aws ec2 wait`
and Part A's `aws ecs wait`. It polls until `State.Code` is `active` or it gives up.

On real AWS a load balancer moves from `provisioning` to `active` in two to four minutes, which is
genuinely slow and worth knowing: it is far slower than anything else in this architecture, and it is
why nobody creates a load balancer as part of a deployment. On Floci it is usually instant, or the state
is `active` from the moment of creation.

If the waiter hangs for more than a minute, interrupt it with ++ctrl+c++ and use the manual loop.

**Verify**

```bash
aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" \
  --query 'LoadBalancers[0].{Name:LoadBalancerName,State:State.Code,Type:Type,Scheme:Scheme,VPC:VpcId,DNS:DNSName,IPType:IpAddressType,AZs:AvailabilityZones[].{Zone:ZoneName,Subnet:SubnetId},SGs:SecurityGroups}' \
  --output json
```

**What to look for:** four things, in this order of importance.

1. `AZs` has **two** entries, with **two different** `Zone` values. If both say `us-east-1a`, you named
   two subnets in the same zone and the load balancer is not fault tolerant. On real AWS the API would
   have refused; if your build accepted it, record it as a limitation and fix the subnets.
2. `Scheme` is `internet-facing` and `Type` is `application`. Neither can be changed after creation —
   both would require deleting and recreating the load balancer, which is why they are worth checking
   now.
3. `SGs` contains your `$ALB_SG`. This one *can* be changed later, with `set-security-groups`.
4. `State` is `active`. `provisioning` is fine and will resolve; `failed` means something about the
   subnets is wrong and the `State.Reason` field says what.

**Command — part 3, a load balancer attribute worth setting deliberately**

```bash
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$ALB_ARN" \
  --attributes \
      Key=idle_timeout.timeout_seconds,Value=60 \
      Key=routing.http.drop_invalid_header_fields.enabled,Value=true \
  --query 'Attributes[?Key==`idle_timeout.timeout_seconds` || Key==`routing.http.drop_invalid_header_fields.enabled`]' \
  --output table \
  || echo "attribute modification not supported on this build — record it and continue"
```

**What the command does**

`idle_timeout.timeout_seconds` is how long the load balancer holds a connection open with no data
flowing before closing it. The default is 60 seconds and that is usually right. It matters when it is
wrong in either direction: an application whose responses take longer than the idle timeout returns a
`504` from the load balancer even though the target was working, and a client that keeps connections
open longer than the target's own keep-alive gets intermittent `502`s. The rule of thumb worth
remembering is that **the target's keep-alive timeout should be longer than the load balancer's idle
timeout**, and getting that backwards is the cause of a famous class of intermittent 502 errors.

`routing.http.drop_invalid_header_fields.enabled` discards headers whose names are not valid HTTP. It
defaults to `false` for backward compatibility and should be `true` on anything new; leaving it off is
the kind of default that shows up in a security review.

**Checkpoint 2**

```text
usms-enrolment-alb   active
 ├── type            application   (layer 7; cannot be changed after creation)
 ├── scheme          internet-facing  (cannot be changed after creation)
 ├── nodes           usms-public-subnet-a (us-east-1a) + usms-public-subnet-b (us-east-1b)
 ├── security group  usms-alb-sg   in: tcp/80 from 0.0.0.0/0   out: allow all
 ├── DNS name        recorded in your notes
 ├── attributes      idle_timeout 60, drop_invalid_header_fields true
 └── listeners       NONE YET — this load balancer currently answers nothing
```

That last line is not a mistake. A load balancer with no listener is reachable and silent: the DNS name
resolves, the nodes are up, and every connection is refused because nothing is listening on any port.
Step 8 fixes it.

---

### Step 6 — Create the target group

**Purpose**

The set of things traffic goes to, and the health check that decides which of them are eligible. This is
the object Lab 04C's request-count scaling policy will eventually name, so its configuration outlives
this lab.

**Run from**

```text
aws-floci-course/
```

**Concept first — the five health check numbers, in the only terms that matter**

A target group health check has five numbers, and every one of them is really an answer to the question
*how long does a broken task keep receiving traffic?*

| Field | Value here | What it means |
| --- | --- | --- |
| `--health-check-interval-seconds` | 30 | How often the load balancer probes each target |
| `--health-check-timeout-seconds` | 5 | How long it waits for a response before calling that probe a failure |
| `--unhealthy-threshold-count` | 2 | How many consecutive failed probes before the target is taken out |
| `--healthy-threshold-count` | 2 | How many consecutive successful probes before it is put back |
| `--matcher HttpCode=200` | 200 | Which response codes count as success |

Multiply the first and third: **a task that dies keeps receiving requests for up to 60 seconds.** That
is the number you actually care about, and it is the number to quote when somebody asks why the outage
lasted a minute after the process died.

You can make it faster — interval 10, unhealthy threshold 2, and a broken target is out in 20 seconds —
and the cost is more probe traffic and a much higher chance of taking out a healthy target during a
transient blip. Aggressive health checks cause outages of their own. This is a genuine trade-off with no
correct answer, which is why the in-class assessment asks you to justify a different set of numbers for
a different service.

The `matcher` is worth one sentence on its own. `HttpCode=200` means *only* 200 is healthy. A target
returning `301` or `403` on the health check path is unhealthy, which is usually what you want and
occasionally infuriating — an application that redirects `/` to `/login` will fail this check forever
while working perfectly. `HttpCode=200-399` is the pragmatic widening, and choosing it deliberately is
different from choosing it because the strict one failed.

**Command**

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
  --tags Key=Name,Value=usms-enrolment-tg Key=Project,Value=USMS Key=Tier,Value=app Key=Lab,Value=04B \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)

echo "TG_ARN = $TG_ARN"
```

**What the command does**

Four of those flags are decisions rather than boilerplate.

**`--target-type ip`** is mandatory, for the reason the interlude gave: an `awsvpc` task has no instance
ID. This is the single most important flag in the command.

**`--vpc-id`** binds the target group to `usms-vpc` permanently. A target group cannot be moved between
VPCs, and `ip` targets must be addresses inside that VPC or a range reachable from it. Passing the wrong
VPC here produces an error at Step 10 rather than now.

**`--port 80` and `--protocol HTTP`** describe how the load balancer talks to a **target**, not how a
client talks to the load balancer. Those are two different conversations and they do not have to use the
same port. Here they both happen to be 80, because Part A's container listens on 80 and the listener in
Step 8 will also be on 80 — but a listener on 443 forwarding to a target group on 8080 is an entirely
ordinary configuration.

**`--health-check-port traffic-port`** is a literal keyword, not a placeholder, and it means "use
whatever port this target is registered on". The alternative is a fixed number, for an application that
serves its health endpoint on a separate management port. `traffic-port` is right here and is the
default; stating it makes the intent explicit.

**Expected result**

```text
TG_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
```

> Example output — your ARN suffix will differ.

That suffix, `targetgroup/usms-enrolment-tg/73e2d6bc24d8a067`, is the second half of Exercise 5's
`ResourceLabel`. Two ARNs, two suffixes, one composite string.

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

**What to look for:** `Type` is `ip` — check this one before anything else, because it is the flag that
cannot be changed later and the one whose error arrives four steps away. `LBs` is `0`, because no
listener forwards to this target group yet; Step 8 makes it `1`.

Confirm the target group is empty, which it should be and will remain until Step 10:

```bash
aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
  --query 'TargetHealthDescriptions' --output json
```

An empty list, `[]`, is correct. **Do not populate it by hand.** If you are tempted to run
`register-targets` with a task's address, re-read the last paragraph of the first interlude: the ECS
service does this, and anything you register manually will be deregistered by the service the next time
it reconciles.

✏️ **Your turn**

Widen the health check so that redirects count as success, read it back, then put it exactly as it was.

```text
Expected result:
describe-target-groups shows Matcher 200-399 after the change and 200 after you
restore it. Both changes take effect immediately and neither requires recreating
anything.

Then answer in one sentence each in notes/lab-04b-notes.md:
(a) Name one realistic application for which the strict 200 matcher would report a
    perfectly working service as unhealthy forever.
(b) Section 9's verification script asserts the matcher is 200. If you had left it at
    200-399, would that failure be a bug in your work or a bug in the script? Justify
    your answer in terms of what a verification script is FOR.
```

Hint: `aws elbv2 modify-target-group help` lists everything about a target group that can be changed
after creation. The list is short, and comparing it with `create-target-group`'s list of flags tells you
exactly which decisions in this step were permanent — which is a more useful thing to know than the
answer to (a).

---

### Step 7 — Set the target group attribute that governs how a task dies

**Purpose**

`deregistration_delay.timeout_seconds` is the number that decides what happens to a request already in
flight when ECS decides to stop a task. It is the load balancer half of a conversation whose ECS half
you configured in Part A, and the two halves are usually set by different people who have never spoken.

**Run from**

```text
aws-floci-course/
```

**Concept first — the sequence when a task goes away**

Whether the cause is a deployment, a scale-in or a failed health check, the sequence is the same:

```text
1. ECS decides to stop task T
2. ECS DEREGISTERS T from usms-enrolment-tg
3. The load balancer marks T as `draining`
     - it sends T no NEW requests
     - it lets requests ALREADY IN FLIGHT finish
     - it waits at most deregistration_delay.timeout_seconds        <- this step
4. When the delay expires (or all connections close), T is fully deregistered
5. ECS sends SIGTERM to the container
6. ECS waits stopTimeout seconds                                     <- Lab 04A
7. ECS sends SIGKILL
```

Three separate timers, in three different places, describing one event:

| Timer | Where it is set | What it protects |
| --- | --- | --- |
| `deregistration_delay.timeout_seconds` | The target group, here | Requests already in flight from the load balancer |
| `stopTimeout` | The task definition, Lab 04A | The container's own graceful shutdown |
| `minimumHealthyPercent` | The service, Lab 04A Step 13 | Total capacity during a deployment |

The default deregistration delay is **300 seconds**, and it is far too long for most web services. Five
minutes per task, times two tasks, is a ten-minute deployment for an application whose requests finish in
milliseconds. Shortening it is one of the highest-value changes you can make to a slow deployment
pipeline, and the correct value is *slightly longer than your slowest legitimate request*.

Thirty seconds is right for this service. A file upload endpoint might justify 300. A WebSocket service
justifies a conversation about whether draining is the right model at all.

**Command**

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

**What the command does**

`load_balancing.algorithm.type` chooses how the load balancer picks a target for each request:

| Value | Behaviour | Suits |
| --- | --- | --- |
| `round_robin` | Each target in turn, regardless of what it is doing | Uniform, short requests. The default |
| `least_outstanding_requests` | The target with fewest requests currently open | Variable request durations, and any service where one slow request should not attract more |

`least_outstanding_requests` is the better default for almost any real API and is chosen here
deliberately. Round robin has one specific pathology worth knowing: a target that is slow but not
unhealthy keeps receiving its full share of traffic and accumulates a queue, because round robin has no
idea it is struggling. Least-outstanding-requests routes around it automatically.

Note the JMESPath in that first query. It uses `||` as a boolean **or** inside a filter expression, so
that one call selects two named attributes, and each attribute name is written as a JMESPath literal —
which is the form that needs backticks around it. That is a new pattern and it is in Appendix B.

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

> Example output — the full attribute list is longer and varies by build.

**Verify**

`deregistration_delay.timeout_seconds` is `30`. If the whole call is rejected, record it as a limitation
and continue: Section 9's script checks this attribute and lists its absence among the known benign
failures.

Two other attributes in that table are worth a moment even though this lab does not change them.
`stickiness.enabled` being `false` means consecutive requests from one client may land on different
tasks, which is correct for a stateless API and wrong for one that keeps session state in memory —
and "we turned on stickiness" is usually a sign that an application should have been storing sessions
elsewhere. `slow_start.duration_seconds` being `0` means a newly healthy target immediately receives its
full share of traffic, which is fine for nginx and unkind to an application with a cold cache or a JIT
compiler.

---

### Step 8 — Create the listener

**Purpose**

The port clients actually connect to, and the action that decides what happens to a request that
arrives on it. This is the step that turns a silent load balancer into one that answers.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, the default action, as a document**

```bash
cat > templates/lab-04b-listener-default-actions.json << EOF
[
  {
    "Type": "forward",
    "TargetGroupArn": "$TG_ARN"
  }
]
EOF

python3 -m json.tool templates/lab-04b-listener-default-actions.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-04b-listener-default-actions.json
```

**What the command does**

Unquoted heredoc — `<< EOF` — because `$TG_ARN` must become a real ARN as the file is written. The
`grep -c '\$'` must print **`0`**; any other number means the variable was empty or the heredoc was
quoted, and you are about to create a listener that forwards to the literal string `$TG_ARN`.

That is the third time in two labs that this check has appeared, in its third context. It costs one line
and it catches the most expensive silent bug in the course.

**Command — part 2, create the listener**

```bash
LISTENER_ARN=$(aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTP \
  --port 80 \
  --default-actions file://templates/lab-04b-listener-default-actions.json \
  --tags Key=Name,Value=usms-enrolment-listener Key=Project,Value=USMS Key=Lab,Value=04B \
  --query 'Listeners[0].ListenerArn' \
  --output text)

echo "LISTENER_ARN = $LISTENER_ARN"
```

**What the command does**

`--default-actions` is a list of structures, so it is passed as a document with `file://` rather than as
shorthand. You could write it inline as
`Type=forward,TargetGroupArn=$TG_ARN` and for this simple case it would work — but actions get nested
quickly (a weighted forward to two target groups, a redirect with a status code and a host, a
fixed-response with a body and a content type), and the shorthand for those is close to unreadable. Step
15 writes an action that genuinely cannot be expressed comfortably any other way.

A listener has exactly **one** default action. Not zero, not two. It is what happens when no rule
matches, and a listener without one would have nothing to do with most requests.

**Expected result**

```text
valid JSON
0
LISTENER_ARN = arn:aws:elasticloadbalancing:us-east-1:000000000000:listener/app/usms-enrolment-alb/50dc6c495c0c9188/f2f7dc8efc522ab2
```

> Example output. Notice that the listener ARN contains the load balancer's ARN suffix inside it —
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

**What to look for:** the listener is on port `80`, protocol `HTTP`, its default action `Type` is
`forward`, and `Forwards` is your `$TG_ARN`. `SSL` is `null`, because an HTTP listener has no TLS policy
— that field is populated only on an HTTPS listener, which is what the Step 4 "Your turn" was pointing
at.

Then the second call: `AttachedToLoadBalancers` has gone from `0` to **`1`**. That is the target group
noticing that something now forwards to it, and it is the first evidence that these two objects are
connected. It is also, on real AWS, the moment health checking begins — the load balancer starts probing
the target group's targets as soon as a listener uses it, and there are none yet.

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

Two things are still missing, and they are the next two steps: the tasks do not admit the load balancer
through their firewall, and the service has not been told to register anything.

---

### Step 9 — Let the load balancer reach the tasks

**Purpose**

The load balancer opens a connection *to* each target. Part A's `usms-enrolment-sg` admits tcp/80 from
`usms-app-sg` and from nothing else, which does not include the load balancer. Without this step every
target would fail its health check with a timeout, and the symptom would be a service that looks
perfectly healthy to ECS and receives no traffic — the exact combination the health check interlude
described.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`<< EOF`, **unquoted**, because `$ALB_SG` must become a real group ID. Contrast it with Step 4's
`policies/usms-alb-sg-ingress.json`, five steps earlier, which used `<< 'EOF'` because it contained no
variables. Two files in the same directory, opposite quoting, and if you open one and see the literal
text `$ALB_SG` you used the wrong one. The `grep -c '\$'` printing `0` is the check.

The rule is group-referenced for the same reason every other rule in this architecture is, and now for a
third reason on top of the two Part A gave: **the load balancer's node addresses are not yours to
know.** AWS chooses them, from within your subnets, and changes them when it scales the load balancer.
Writing this rule against an address would produce a firewall that works today and fails silently on a
day AWS decides to add a node.

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

> Example output — your IDs will differ, and the two sources may appear in either order.

**What to look for:** **two** source groups on port 80 — `usms-app-sg` from Part A and `usms-alb-sg`
from this step — and an empty `CIDRs` list. Note how they are presented: AWS has merged them into a
single `IpPermission` entry, because they share a protocol and port range, with two entries in
`UserIdGroupPairs`. That merging is why Part A's verification check, which reads
`IpPermissions[0].UserIdGroupPairs[0].GroupId`, is now reading whichever of the two happens to be first
in an unordered list. Hold that thought until Step 13.

Both rules coexisting is the intended state right now. The web tier can still reach the tasks directly,
*and* the load balancer can reach them. That overlap is what makes the next three steps a migration
rather than an outage: build the new path, prove it, then remove the old one.

---

### Step 10 — Attach the existing service to the target group

**Purpose**

Tell `usms-enrolment-svc` that its tasks are targets. From this moment the service registers every task
it starts and deregisters every task it stops, for the rest of the service's life, without anybody
asking it to.

**Run from**

```text
aws-floci-course/
```

**Concept first — the three fields, and why two of them must match exactly**

The service's `loadBalancers` entry has three fields:

```text
targetGroupArn   which target group to register into
containerName    WHICH CONTAINER in the task definition receives the traffic
containerPort    WHICH PORT on that container
```

The last two are matched against the task definition **by string**, and both must correspond to a real
`portMappings` entry on a real container. Part A's `usms-enrolment:2` defines one container named
`enrolment-api` with a `containerPort` of `80`, which is why those are the values below.

Getting either wrong produces `InvalidParameterException` with a message about the container not being
found in the task definition — which is clear, once you know that "container" here means the `name`
field and not the image, the task, or anything you might reasonably call a container in conversation.
This is also why a multi-container task needs you to say which one; Part A Exercise 2's
`enrolment-metrics` sidecar is exactly the case where the answer is not obvious.

**Command — part 1, the document**

```bash
cat > templates/lab-04b-service-load-balancers.json << EOF
[
  {
    "targetGroupArn": "$TG_ARN",
    "containerName": "$USMS_ENROLMENT_CONTAINER",
    "containerPort": 80
  }
]
EOF

python3 -m json.tool templates/lab-04b-service-load-balancers.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-04b-service-load-balancers.json
cat templates/lab-04b-service-load-balancers.json
```

**What to look for:** `0` remaining dollar signs, and `containerName` reading `enrolment-api` — not
`$USMS_ENROLMENT_CONTAINER`, and not `usms-enrolment` (which is the task definition **family**, a
different string that looks similar enough to cause an hour of confusion).

**Command — part 2, attach it**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --load-balancers file://templates/lab-04b-service-load-balancers.json \
  --health-check-grace-period-seconds 60 \
  --query 'service.{Name:serviceName,LB:loadBalancers,Grace:healthCheckGracePeriodSeconds,Deployments:length(deployments),TaskDef:taskDefinition}' \
  --output json
```

**What the command does**

Two flags, and the second one prevents a failure mode that is worth describing in full.

**`--load-balancers`** changes the service's load balancer configuration in place. This triggers a new
deployment, because every existing task has to be replaced by one the service has registered as a
target — a task that was running before the attachment is not in the target group and cannot be added
to it retroactively.

**`--health-check-grace-period-seconds 60`** tells ECS to **ignore target group health results for the
first 60 seconds of each task's life.** Without it, the loop is:

```text
task starts -> application takes 25 seconds to be ready
            -> load balancer probes at 30s intervals, gets no answer, marks it unhealthy
            -> ECS sees an unhealthy target and replaces the task
            -> the new task takes 25 seconds to be ready
            -> ...
```

The service never stabilises, `runningCount` oscillates, and the events list fills with tasks being
started and stopped. It is one of the most common ECS support cases and the fix is always this flag. The
grace period should be comfortably longer than your application's slowest cold start.

Note that the flag is **only valid on a service that uses a load balancer.** Passing it before this step
would have been rejected, which is a small piece of API design worth appreciating: the parameter cannot
be set in a state where it would be meaningless.

!!! warning "If your build rejects `--load-balancers` on `update-service`"
    Updating a service's load balancer configuration in place is supported for services using the
    rolling (`ECS`) deployment controller, which is what Part A Step 13 created. Some emulator builds
    have not implemented it.

    If the call fails with `InvalidParameterException` or `UnsupportedFeatureException`, use the
    recreate path below. It is destructive and it is the reason this warning exists.

    ??? danger "Fallback only — recreate the service with the load balancer attached"
        !!! danger "Read before running any delete command"
            **What will be deleted:** the ECS service `usms-enrolment-svc` and its two running tasks.
            The task definition family, the cluster, both roles, the security group and the log group
            are untouched.

            **What depends on it:** Lab 04C registers a scalable target against a service **of this
            name**. Recreating it with the same name, same cluster, same task definition and same
            desired count preserves everything downstream. Recreating it with a different name breaks
            Lab 04C, `configs/lab-04a.env` and `verify-lab-04a.sh` simultaneously.

            **Reversible?** The service object is not recoverable, but an identical one is three
            commands away, and every input to those commands is in `configs/lab-04a.env`.

            **Effect on later labs:** none, **provided** the name, cluster, task definition and desired
            count are identical to Part A's.

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
          --deployment-configuration file://templates/lab-04a-deployment-config.json \
          --load-balancers file://templates/lab-04b-service-load-balancers.json \
          --health-check-grace-period-seconds 60 \
          --network-configuration "awsvpcConfiguration={subnets=[$USMS_PRIVATE_SUBNET_A,$USMS_PRIVATE_SUBNET_B],securityGroups=[$USMS_ENROLMENT_SG],assignPublicIp=DISABLED}" \
          --enable-ecs-managed-tags \
          --propagate-tags SERVICE \
          --tags key=Name,value=usms-enrolment-svc key=Project,value=USMS key=Tier,value=app key=Lab,value=04A \
          --query 'service.serviceArn' --output text
        ```

        Every value in that command comes from Part A or from `configs/lab-04a.env`. Nothing is invented
        and nothing is renamed. Record in your notes that you took the fallback path, and note that
        `Lab=04A` is deliberately preserved on the tag: the service is still Part A's object.

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

> Example output — `Deployments: 2` means the roll has started. On a build that starts no containers it
> may be `1` immediately.

**What to look for:** `LB` has exactly one entry, `Grace` is `60`, and `TaskDef` is **unchanged** at
`usms-enrolment:2`. That last one is the point worth pausing on: attaching a load balancer did not
register a new task definition revision, because where traffic comes from is a property of the
**service**, not of the blueprint. Part A's four objects are still doing exactly the jobs Part A gave
them.

---

### Step 11 — Watch the targets register, and read target health

**Purpose**

The target group was empty at Step 6 and you were told not to fill it. This is where it fills itself.
Watching it happen is the only way to believe that the ECS service, and not you, is responsible for the
contents of a target group.

**Run from**

```text
aws-floci-course/
```

**Concept first — the five target health states**

| State | Meaning | Typical cause when unexpected |
| --- | --- | --- |
| `initial` | Registered; the load balancer has not completed enough health checks to decide | Perfectly normal for the first `interval x healthy_threshold` seconds |
| `healthy` | Passing its health check; receiving traffic | — |
| `unhealthy` | Failing its health check | The security group, the health check path, the matcher, or a genuinely broken application. In that order of likelihood |
| `draining` | Deregistering; finishing in-flight requests only | A deployment or a scale-in, in progress |
| `unused` | Registered, but nothing can send it traffic | No listener forwards to this target group, or the target group is not attached to a load balancer |

`unused` is the one that confuses people, because it looks like a fault and usually is not. If you see
it, check `LoadBalancerArns` on the target group before checking anything else.

`Target.Id` for an `ip` target group is an **address**, not an instance ID and not a task ARN. That is
the concrete evidence that a Fargate task is registered by the address its elastic network interface
holds inside your subnet — the same address Part A dug out of `attachments` in its Step 12.

**Command — part 1, watch it fill**

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

> Example output — your addresses will differ, and on many builds the state will stay `initial` or the
> list will remain empty. Record what you see.

**What to look for:** two targets, **one in each Availability Zone**, with addresses inside
`10.0.3.0/24` and `10.0.4.0/24`. Read those addresses against Lab 2's plan. They are your private
subnets, which is the concrete proof that the load balancer in the public subnets is reaching tasks in
the private ones — the whole architecture, in two rows of a table.

**Command — part 2, the service's own account of it**

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments),Rollout:deployments[0].rolloutState,LB:loadBalancers[0].targetGroupArn}' \
  --output json

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].events[0:6].[createdAt,message]' --output text
```

**What to look for:** on real AWS the events list narrates the whole thing —
`registered 1 targets in target-group usms-enrolment-tg`, then `has begun draining connections on 1
tasks`, then `has reached a steady state`. That last sentence is the one that means the deployment
finished. On Floci the list is usually shorter and may be empty; record which.

**Command — part 3, the two health opinions, side by side**

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

**What the command does**

The first block asks ECS what it thinks of each task; the second asks the load balancer what it thinks
of each address. Line them up by address. This is the practical form of the health check interlude, and
it is the diagnostic you will reach for whenever a load-balanced service misbehaves:

| ECS `healthStatus` | Target health | Diagnosis |
| --- | --- | --- |
| `HEALTHY` | `healthy` | Working |
| `HEALTHY` | `unhealthy` | **The network path is broken.** Security group, subnet, or the health check path returning the wrong code |
| `UNHEALTHY` | `unhealthy` | The application is broken. Read the container logs |
| `UNKNOWN` | `healthy` | Not a fault. The task definition has no container health check |
| anything | `unused` | Nothing forwards to this target group |

Write that table into `notes/lab-04b-notes.md`. It is Review Question 4 and it is Task C of the in-class
assessment.

✏️ **Your turn**

Raise the service's desired count to 3, watch the target group, then put it back to 2.

```text
Expected result:
describe-target-health shows three targets and then two again, without you running
register-targets or deregister-targets even once. The third address is in whichever
private subnet keeps the AZ balance.

Then answer in one sentence in notes/lab-04b-notes.md:
Lab 04C will move desiredCount automatically. Name the ONE thing you would have had
to do by hand after every single scaling event if the service did not register its
own targets.
```

Hint: Part A Step 16 has the command for changing the desired count. Nothing else in this task requires
a command you have not already run.

**Checkpoint 4**

```text
usms-enrolment-svc   attached to the load balancer
 ├── loadBalancers[0]  targetGroupArn = usms-enrolment-tg
 │                     containerName  = enrolment-api   (matches usms-enrolment:2)
 │                     containerPort  = 80
 ├── healthCheckGracePeriodSeconds  60
 ├── taskDefinition   usms-enrolment:2  — UNCHANGED, no new revision registered
 └── usms-enrolment-tg
      ├── 10.0.3.x:80  us-east-1a   registered by the SERVICE
      ├── 10.0.4.x:80  us-east-1b   registered by the SERVICE
      └── state        healthy / initial / (empty, on builds with no data path)
```

---

### Step 12 — Prove the path, and be honest about which proof you got

**Purpose**

Everything so far has been configuration that reported success. Part A's principle applies: **a command
that appears to succeed is not evidence that it did what you meant.** This step tries the real thing
first, and gives you a control-plane proof to record when the real thing is not available.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, the data path**

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
  || echo "curl could not connect — expected on many builds; see part 2"
```

**What the command does**

Three probes of increasing ambition: does the name resolve, does something answer, and what does it say.
`getent hosts` is not available everywhere, so a three-line Python fallback follows it —
`socket.gethostbyname_ex` is in the standard library and behaves the same on macOS and Linux, which
`getent`, `host` and `dig` do not.

`curl -w` prints selected transfer variables after the request. `%{http_code}` and `%{time_total}` are
the two worth knowing; `--max-time 10` stops a hanging connection from stalling the lab.

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
curl could not connect — expected on many builds; see part 2
```

> Also example output, and also a perfectly acceptable result for this lab.

!!! note "Floci Limitation — the load balancer's data path"
    An internet-facing load balancer's DNS name is a public name that AWS publishes and resolves. Floci
    does not run public DNS, and the course's `docker-compose.yml` publishes only port `4566`. Some
    builds serve load balancers through the `4566` gateway under a `localhost.localstack.cloud` name;
    many serve no data path at all.

    §5.5 of this course's environment contract lists the port ranges that may be uncommented for
    sidecar services, and **there is no range listed for Elastic Load Balancing**. Do not invent one and
    do not publish extra ports hoping it will help — publishing ranges you do not need makes Docker
    Desktop crawl and causes collisions on shared machines, which is exactly why they are commented out.

    Real AWS resolves the DNS name to the public addresses of the load balancer's nodes, in the two
    Availability Zones you chose, and forwards to a healthy target within milliseconds.

    Take this away regardless: part 2 below proves the same wiring from the control plane, end to end,
    without a single packet reaching a container. Record which of the two proofs you obtained. Claiming
    a `200` you did not see is worth negative marks.

**Command — part 2, the control-plane proof, which always works**

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
      *)        echo "NOT in a Lab 02 private subnet — investigate" ;;
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
} | tee outputs/lab-04b-path-proof.txt
```

**Verify**

Read the five blocks as one chain and satisfy yourself that each link names the next:

```text
client -> listener HTTP:80        (block 1)
       -> forward action names    usms-enrolment-tg          (block 1 -> 2)
       -> target group holds      10.0.3.x:80, 10.0.4.x:80   (block 3)
       -> those addresses are in  Lab 02's private subnets   (block 3)
       -> they got there because  usms-enrolment-svc registers them (block 4)
       -> and are reachable because usms-enrolment-sg admits usms-alb-sg (block 5)
```

If block 3 is empty, your build did not start containers; the chain is still proven from blocks 1, 2, 4
and 5, and you say so. If block 5 does not contain `$ALB_SG`, go back to Step 9 — that is a real fault
and the only one in this list that would break the architecture on real AWS.

`outputs/lab-04b-path-proof.txt` is evidence for your lab report and for Section 14.1 Task D. Keep it.

---

### Step 13 — The cutover: remove the direct path

**Purpose**

The web tier now has two ways to reach the enrolment tasks: through the load balancer, and directly, on
the rule Part A wrote. Having proved the first, remove the second. A migration that leaves the old path
in place is not finished; it is a system with two behaviours, one of which nobody is testing.

**Run from**

```text
aws-floci-course/
```

!!! danger "Read before running any delete command"
    **What will be deleted:** one inbound rule on `usms-enrolment-sg` — the tcp/80 rule sourced from
    `usms-app-sg`, written in Lab 04A Step 9. Not the group, not any rule you wrote today, and not any
    task.

    **What depends on it:** anything calling the enrolment tasks by address rather than through the load
    balancer. In this architecture that is nothing, because Step 12 proved the load-balanced path first.
    On a real system it would be whatever you had not finished migrating, which is why the order of
    Steps 9, 12 and 13 is the whole lesson.

    **Reversible?** Yes, completely. `policies/usms-enrolment-sg-ingress.json` from Lab 04A is still in
    your repository and one `authorize-security-group-ingress` call puts the rule back.

    **Effect on later labs:** `scripts/utilities/verify-lab-04a.sh` will report exactly one failure
    afterwards — `usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)` — because that check
    encodes the pre-load-balancer architecture. That is expected and is discussed below. Lab 04C is
    unaffected: it never reads that rule.

**Command — part 1, find the exact rule, and confirm it before removing it**

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

**What the command does**

`describe-security-group-rules` returns each rule as its own object with its own ID, which is the only
view in which the two sources on port 80 are separable — `describe-security-groups` merges them, as you
saw at Step 9.

The JMESPath filter combines two conditions with `&&`, compares a boolean literal in backticks, and
compares a string in single quotes. Those three quoting rules in one expression are worth reading
carefully: JMESPath wants backticks around JSON literals such as `false` and `80`, and single quotes
around raw strings. Getting them the wrong way round is the most common JMESPath error after forgetting
`| [0]`.

The shell escaping is doing work too. The whole query is in double quotes so that `$USMS_APP_SG`
expands, which means the backticks around `false` must be escaped as `\`` or the shell would treat them
as command substitution.

**What to look for before you go on:** `OLD_RULE_ID` is a real `sgr-` identifier and **not** `None`. If
it is `None`, either the rule was already removed or `$USMS_APP_SG` is empty in this terminal. Check the
variable before assuming the rule is gone.

**Command — part 2, remove it**

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

**What to look for:** exactly **one** source group on port 80, and it is `$ALB_SG`. `$USMS_APP_SG` does
not appear. `CIDRs` is empty.

The architecture now says something precise, and you should be able to say it in one sentence: *the only
thing in this account that can open a connection to an enrolment task is the load balancer.* Not the
internet, not the web instance, not the database instance. That sentence is what a security review is
actually asking for, and it is now true by construction rather than by assertion.

**Command — part 3, look at what this did to Part A's script**

```bash
./scripts/utilities/verify-lab-04a.sh | tee outputs/lab-04b-post-verify-04a.txt | tail -5

echo "== what changed =="
diff outputs/lab-04b-pre-verify-04a.txt outputs/lab-04b-post-verify-04a.txt
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

**What to look for:** the `diff` shows **exactly one** check changing state, and the totals moving from
`49/0` to `48/1`. Any other line in that diff is something you broke by accident and should investigate
before continuing.

That single line is worth more attention than it looks. A verification script is a written-down
statement of what an architecture is supposed to be. When the architecture legitimately changes, the
script becomes wrong — and it says so loudly, which is the behaviour you want. It has done its job
correctly by failing.

You have three defensible responses, and the assessment expects you to be able to name all three:

| Response | When it is right |
| --- | --- |
| Leave it, and document the expected failure | Now. Part A's script is a record of what Part A built, and rewriting history to make a script green is a bad habit |
| Update the check to assert the new source group | Exercise 2. This is what you would do on a real system, in the same commit as the change |
| Delete the check | Almost never. The property still matters; only the expected value changed |

From this point on, `verify-lab-04b.sh` from Section 9 is the script of record for this architecture. It
asserts both halves: that the load balancer's group is a source, and that the web tier's group is not.

---

### Step 14 — Deploy behind a load balancer, and watch a target drain

**Purpose**

Part A taught deployments with no load balancer, so a task simply stopped. With a target group in front,
the same deployment acquires two extra states and one extra timer, and this is the step where
`deregistration_delay` stops being a number in a table.

**Run from**

```text
aws-floci-course/
```

**Concept first — what a rolling deployment looks like now**

Part A's sequence, with the load balancer's part written in:

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

Two things are new and both are improvements. A new task does not receive a single request until the
load balancer has independently agreed it is healthy — the health check has become a *deployment gate*,
not merely a monitor. And an old task is not killed the instant it is replaced; it is drained first, so
a request in flight at step 4 gets up to thirty seconds to finish.

That second property is why a load-balanced deployment can be genuinely zero-downtime and an
unbalanced one cannot. Part A's deployment stopped tasks that might have been mid-request, and nothing
in the architecture could have known.

**Command — part 1, record the state before**

```bash
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[taskDefinition,desiredCount,runningCount]' --output text
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'sort(TargetHealthDescriptions[].Target.Id)' --output text
} > outputs/lab-04b-pre-deploy.txt

cat outputs/lab-04b-pre-deploy.txt
```

**Command — part 2, force a deployment with no change at all**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --force-new-deployment \
  --query 'service.{TaskDef:taskDefinition,Deployments:length(deployments)}' \
  --output json
```

**What the command does**

`--force-new-deployment` replaces every task with an identical one, from the same task definition
revision. Part A mentioned the flag; this is the step that uses it, and the reason to use it here is that
it isolates exactly one variable. Nothing about the blueprint changes, so anything you observe is caused
by the deployment mechanism itself and not by a difference between two revisions.

On a real system there are three routine reasons to force a deployment: the image tag now points at a
different image, a secret has been rotated, or you want to cycle tasks that have been running long
enough to have drifted. All three are "nothing in the configuration changed and I want new tasks
anyway".

**Command — part 3, watch both sides at once**

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

> Example output — the exact interleave depends on when you polled, and on a build with no data path
> the target list may not change at all. A single frame containing `draining` next to `healthy` is the
> thing worth screenshotting.

**What to look for:** three states visible across the polls — `initial` for a target that has just been
registered, `healthy` once it has passed its checks, and `draining` for one on its way out. Catching all
three is the evidence that the sequence in the concept block above is real.

**Command — part 4, confirm**

```bash
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[taskDefinition,desiredCount,runningCount]' --output text
  aws elbv2 describe-target-health --target-group-arn "$TG_ARN" \
    --query 'sort(TargetHealthDescriptions[].Target.Id)' --output text
} > outputs/lab-04b-post-deploy.txt

paste outputs/lab-04b-pre-deploy.txt outputs/lab-04b-post-deploy.txt
```

**What to look for:** the task definition is identical on both sides — this was a forced deployment, not
a revision change — the counts are identical, and the **addresses are different**. Same blueprint, same
capacity, different tasks. That is the whole meaning of `--force-new-deployment` in three lines of
output.

If your build never changes the target list, the task ARNs will still have changed; check with
`aws ecs list-tasks` and record that as the evidence instead.

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

### Step 15 — Add a listener rule

**Purpose**

A listener has one default action, and everything more interesting than "send it all to one place" is a
rule. This step adds one, with a condition and an action that is not a forward, so that the mechanism is
clear before you need it for something that matters.

**Run from**

```text
aws-floci-course/
```

**Concept first — priority, and the order things are evaluated**

```text
request arrives on listener HTTP:80
  |
  +-- rule priority 10   condition matches?  -> run its action, STOP
  +-- rule priority 20   condition matches?  -> run its action, STOP
  +-- rule priority 30   ...
  |
  +-- no rule matched    -> run the listener's DEFAULT ACTION
```

Lowest priority number is evaluated first, and the first match wins. Priorities must be unique within a
listener and are in the range 1 to 50000. Leaving gaps — 10, 20, 30 rather than 1, 2, 3 — is a
convention worth adopting for the same reason it was worth adopting in BASIC: inserting a rule between
two existing ones then needs no renumbering.

The default action is not a rule and has no priority. It is the fallback, and it always runs last.

**Actions** you can attach to a rule:

| Type | What it does | Typical use |
| --- | --- | --- |
| `forward` | Send to one target group, or several with weights | Normal routing; weighted forwarding is how blue/green and canary releases are done |
| `redirect` | Return a 301 or 302 with a rewritten URL | The HTTP-to-HTTPS redirect that every public site needs |
| `fixed-response` | Return a status code and body without contacting any target | Health endpoints, maintenance pages, and blocking a path outright |
| `authenticate-oidc` / `authenticate-cognito` | Require a login before forwarding | Putting an identity provider in front of an app that has none |

This step builds a `fixed-response`, because it is the one that proves the mechanism with no second
target group and no second service: if `/alb-health` returns 200 while `/` reaches a task, the rule
fired and the default action did not.

**Command — part 1, the condition and the action**

```bash
cat > templates/lab-04b-rule-conditions.json << 'EOF'
[
  {
    "Field": "path-pattern",
    "PathPatternConfig": {
      "Values": ["/alb-health", "/alb-health/*"]
    }
  }
]
EOF

cat > templates/lab-04b-rule-actions.json << 'EOF'
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

python3 -m json.tool templates/lab-04b-rule-conditions.json > /dev/null && echo "conditions valid"
python3 -m json.tool templates/lab-04b-rule-actions.json    > /dev/null && echo "actions valid"
```

**What the command does**

Both heredocs are `<< 'EOF'`, **quoted**, because neither document contains a variable. The action
document also contains a literal `\n`, which must reach the file as two characters and would survive
either form — but the habit of quoting anything with no variables in it is what keeps you from having to
think about cases like that.

`StatusCode` is a **string**, `"200"`, not the number `200`. This is the same class of trap as Part A's
`"cpu": "256"`, in a different service, and the error message names a type rather than a field.

The condition matches two patterns because `/alb-health` and `/alb-health/*` are different: path
patterns are matched literally with `*` and `?` wildcards, and a pattern of `/alb-health*` would also
match `/alb-healthcheck-internal`, which you probably did not mean. Being precise about this is the
difference between a rule that does what you said and one that does what you typed.

**Command — part 2, create the rule**

```bash
RULE_ARN=$(aws elbv2 create-rule \
  --listener-arn "$LISTENER_ARN" \
  --priority 10 \
  --conditions file://templates/lab-04b-rule-conditions.json \
  --actions file://templates/lab-04b-rule-actions.json \
  --tags Key=Name,Value=usms-enrolment-health-rule Key=Project,Value=USMS Key=Lab,Value=04B \
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

**What to look for:** two entries. The rule you made, with `Default` false and a numeric priority, and
the default action, which appears in this list with `Priority` of the literal string `"default"` and
`IsDefault` true. That is a small piece of API design worth noticing: the default action is presented as
a rule so that one call shows you the whole decision table, even though it is not a rule you created and
cannot delete.

**Command — part 3, test it if you have a data path**

```bash
curl -s -o /dev/null -w '/            -> %{http_code}\n' --max-time 10 "http://$ALB_DNS/" || true
curl -s -w '/alb-health  -> %{http_code}  body: %{size_download} bytes\n' --max-time 10 \
     "http://$ALB_DNS/alb-health" || true
```

If both answer, the second one returned without any task being involved at all — that is the rule firing
ahead of the default action. If neither answers, the `describe-rules` output above is your evidence and
the point still stands.

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

### Step 16 — Prove the whole thing survives a restart

**Purpose**

The same proof as Lab 2 Step 23, Lab 3 Step 19 and Lab 04A Step 18, applied to this lab's work. This
lab's state spans three services — ELBv2, ECS and EC2 — and a build that persists two of them but not
the third would leave you with a service whose `loadBalancers` entry names a target group that no longer
exists. That failure is invisible until the next deployment.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, record the truth**

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
} > outputs/lab-04b-pre-restart.txt

cat outputs/lab-04b-pre-restart.txt
```

**Command — part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
source configs/lab-02.env
source configs/lab-04a.env
```

`floci-down.sh` is `docker compose stop`. It stops the container and keeps the state. It is not
`docker compose down`, and it is emphatically not `docker compose down -v`, which would delete the
volumes and with them the entire course.

**Command — part 3, read it back, deriving every ARN from the API**

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
} > outputs/lab-04b-post-restart.txt

diff outputs/lab-04b-pre-restart.txt outputs/lab-04b-post-restart.txt \
  && echo "PERSISTENCE PROVEN: the load balancer, its two Availability Zones, its security group, the target group with its full health check configuration, the listener, the rule, the service's loadBalancers entry and the grace period are all unchanged" \
  || echo "PERSISTENCE FAILED: read the diff above, then run ./scripts/utilities/floci-storage-check.sh"
```

**What the command does**

Part 3's first four lines are the entire point of the step. Every ARN is **re-derived from the API**
rather than reused from the shell variables. Reusing the variables would have proved only that Bash
remembers strings — which is exactly the mistake that made an earlier edition of this course's
persistence test worthless, described in Lab 1 Step 14.

Note how the derivation works, because it is the practical reason ELBv2 gives you `--names` on two
read-only calls in an otherwise ARN-only API: `describe-load-balancers --names` and
`describe-target-groups --names` are the front door back into a system whose identifiers you have lost.
Listeners and rules have no name at all, so they are found by walking down from the load balancer's ARN
— which is why the third line filters listeners by port.

`sort_by(Listeners,&Port)` is a new JMESPath form. The `&` makes an **expression reference** — a little
function passed to `sort_by` telling it which field to sort on. Sorting matters here because the
comparison is a `diff`, and a list that comes back in a different order on the second run would produce
a false failure.

Seven facts across three services are compared, not one. `runningCount` is deliberately **not** in the
list, for the same reason Part A left it out: tasks are allowed to be restarted by the service after a
restart of the emulator, and comparing a number that is legitimately allowed to move would make this
check fail for the wrong reason. **Compare the configuration, not the weather.**

**Expected result**

```text
re-derived:
  arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
  arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
  arn:aws:elasticloadbalancing:us-east-1:000000000000:listener/app/usms-enrolment-alb/50dc6c495c0c9188/f2f7dc8efc522ab2
  sg-0bb22cc33dd44ee55
PERSISTENCE PROVEN: the load balancer, its two Availability Zones, its security group, the target group with its full health check configuration, the listener, the rule, the service's loadBalancers entry and the grace period are all unchanged
```

**What to look for:** exactly that line. If you see `PERSISTENCE FAILED`, read the `diff` output **before
doing anything else** — it names *which* of the seven facts did not survive, which is a far more useful
finding than a general failure. Then run `./scripts/utilities/floci-storage-check.sh`.

**Checkpoint 7**

```text
Persistence proven for Lab 04B
 ├── every ARN re-derived from the API by name or by walking down from a parent
 ├── load balancer: scheme, type, 2 AZs, 1 security group — unchanged
 ├── target group: type ip, health check path, matcher, interval, threshold — unchanged
 ├── listener and its rule — unchanged, in priority order
 ├── service loadBalancers entry and grace period — unchanged
 └── both security groups — unchanged, including the Step 13 cutover
```

---

### Step 17 — Close the loop, and audit what this lab created

**Purpose**

Step 13 changed who may call the enrolment tasks. This step resolves both ends of the new chain back to
real objects, so that the security posture is something you have *demonstrated* rather than something
you have *asserted*.

**Run from**

```text
aws-floci-course/
```

**Command**

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
  echo "MISMATCH: expected $ALB_SG (usms-alb-sg), found $TASK_SOURCE — re-read Steps 9 and 13"
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
echo "== 4. Audit: everything this lab tagged Lab=04B =="
aws ec2 describe-security-groups --filters "Name=tag:Lab,Values=04B" \
  --query 'SecurityGroups[].[GroupName,GroupId]' --output text
aws elbv2 describe-tags --resource-arns "$ALB_ARN" "$TG_ARN" \
  --query 'TagDescriptions[].{Resource:ResourceArn,Tags:Tags[?Key==`Lab`].Value|[0]}' \
  --output table \
  || echo "elbv2 describe-tags not supported on this build — record it and continue"
```

**What the command does**

Block 2 is the important one, and it is deliberately written as an equality test rather than a
description. The claim "only the load balancer can reach the tasks" is either true or false, and this
prints which.

Block 3 is the piece that would be easy to skip and should not be. `usms-web-01` still carries
`usms-app-sg`, and that group no longer grants it anything on the enrolment tasks. Nothing about the
instance changed and everything about what it can reach did — which is the clearest possible illustration
of what a security group actually is. It is not a property of the instance. It is a name that other
people's rules refer to.

`aws elbv2 describe-tags --resource-arns` takes **several ARNs in one call** and returns a
`TagDescriptions` list, one entry per resource. That plural form is unusual — most `describe-tags`
operations in AWS take filters instead — and it is worth knowing because it is the only way to audit
ELBv2 tags in bulk.

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

== 4. Audit: everything this lab tagged Lab=04B ==
usms-alb-sg     sg-0bb22cc33dd44ee55
------------------------------------------------------------
|                       DescribeTags                       |
+-------------------------------------------+-------------+
|                 Resource                  |    Tags     |
+-------------------------------------------+-------------+
|  arn:aws:elasticloadbalancing:...alb/...  |  04B        |
|  arn:aws:elasticloadbalancing:...tg/...   |  04B        |
+-------------------------------------------+-------------+
```

> Example output — your IDs will differ.

**What to look for:** `CUTOVER CONFIRMED` and `LOOP CLOSED`. A `MISMATCH` in block 2 is a real fault; a
`NOTE` in block 3 usually means Lab 3's instance was terminated and relaunched, or you did Lab 3 Step
18's "Your turn" and there are now two instances carrying `usms-app-sg`, in which case `[0]` picked the
other one and the mismatch is benign. Say which, in one sentence, in your report.

If any ELBv2 resource shows no tags, note it: some builds accept `--tags` on create and do not store
them. Add them afterwards with `aws elbv2 add-tags --resource-arns ... --tags Key=Lab,Value=04B` and
record the rest.

---

### Step 18 — Write `configs/lab-04b.env`

**Purpose**

Every shell variable in this terminal dies when you close it, and this lab created six things whose ARNs
matter. Lab 04C needs three of them. Record them **by lookup, not from the variables**, so that a
populated value in the file is evidence the resource actually exists.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-04b.env << EOF
# Lab 04B — ECS service behind an Application Load Balancer
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs and ARNs only. NO SECRETS. Safe to commit.
#
# Sourced alongside lab-01/02/03/04a. Lab 04C (lab-04-ecs-autoscaling) sources this
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

grep -n 'export .*=$\|None' configs/lab-04b.env || echo "all values populated"
```

**What the command does**

Unquoted heredoc — `<< EOF`, not `<< 'EOF'` — for the same reason as Lab 2 Step 24, Lab 3 Step 22 and
Lab 04A Step 20: every `$(...)` must run **now** and the resulting value must land on disk. Had this
been quoted, the file would contain the text of thirteen API calls, and `source configs/lab-04b.env`
would re-run all of them in every new terminal you ever open.

The listener line is the awkward one and repays a close look. Two things are happening:

- It contains a **nested** command substitution, because there is no `describe-listeners --names`: you
  can only find a listener by walking down from its load balancer's ARN.
- The backticks around `80` inside the JMESPath filter are escaped as ``\` ``, because the whole heredoc
  is unquoted and an unescaped backtick would be read by the shell as command substitution. Get this
  wrong and the shell tries to run `80` as a command, which produces `80: command not found` and an
  empty variable — a genuinely confusing failure whose message names neither JMESPath nor the listener.

`USMS_SVC_GRACE_PERIOD` is read back from the service rather than hard-coded as `60`, so that if the
attachment silently failed the file records `None` and the check below catches it.

**Verify**

```bash
source configs/lab-04b.env

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

grep -c '^export' configs/lab-04b.env
```

**What to look for:** `all values populated`, eleven non-empty lines, and a count of **15** exported
variables. `target type` must read `ip`; `lb container` must read `enrolment-api`; `grace period` must
read `60`.

A `None` anywhere means a resource does not exist or a step did not take. Find which, because catching it
here is worth ten troubleshooting entries in Lab 04C.

---

### Step 19 — Commit

**Purpose**

Same discipline as every lab: look first, stage explicitly, then commit.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-04b-path-proof.txt
git ls-files outputs/
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears in `git status --short`.
- No `.env` at the repository root appears.
- `configs/lab-04b.env` **does** appear. It holds names, ARNs and a DNS name — no secrets.
- `git check-ignore -v` names the file, the rule and the line number. **Silence there means the file is
  not ignored** — stop and fix `.gitignore` before committing anything at all.
- `git ls-files outputs/` lists `outputs/.gitkeep` and nothing else.

**Expected result**

```text
.gitignore:7:outputs/*  outputs/lab-04b-path-proof.txt
outputs/.gitkeep
```

> Example output — your line number may differ.

If `check-ignore` prints nothing, the rule is wrong. It must be `outputs/*` with `!outputs/.gitkeep`,
never `outputs/` with `!outputs/.gitkeep` — Git cannot re-include a file whose parent directory is
excluded, so the negation silently does nothing.

**Command — part 2, commit**

```bash
git add labs/lab-04b-ecs-alb/ \
        configs/lab-04b.env \
        policies/usms-alb-sg-ingress.json \
        policies/usms-enrolment-sg-ingress-alb.json \
        templates/lab-04b-listener-default-actions.json \
        templates/lab-04b-rule-conditions.json \
        templates/lab-04b-rule-actions.json \
        templates/lab-04b-service-load-balancers.json \
        scripts/utilities/verify-lab-04b.sh \
        scripts/cleanup/lab-04b-cleanup.sh

git status --short

git commit -m "Lab 04B: USMS enrolment service behind an Application Load Balancer — ALB, target group, listener, rule, service attachment and the security cutover"

git log --oneline -6
```

The `git add` names paths explicitly rather than using `git add -A`. That is not fussiness: `git add -A`
stages whatever happens to be in the working tree, which is exactly how an un-ignored secret reaches a
commit and, from there, a remote.

The two script paths only exist after Section 9. If you commit before building them, drop those two
lines and add them in a second commit.

**Expected result**

```text
[main 3b71f04] Lab 04B: USMS enrolment service behind an Application Load Balancer — ALB, target group, listener, rule, service attachment and the security cutover
 10 files changed, 312 insertions(+)
```

> Example output — your hash and counts will differ.

**Checkpoint 8**

```text
Lab 04B recorded
 ├── configs/lab-04b.env       committed, 15 exports, fully populated
 ├── policies/                 two security group documents, opposite heredoc quoting
 ├── templates/                listener default action, rule conditions, rule actions,
 │                             service load balancers
 ├── scripts/                  verify-lab-04b.sh and lab-04b-cleanup.sh
 ├── outputs/                  nothing staged; check-ignore names the rule that protected you
 └── git log shows Lab 01, 02, 03, 04A and 04B commits
```

---

## 9. Verification

### 9.1 What this script checks that a naive one would not

Seven of the checks below are the ones worth having, and they are why "does the load balancer exist" is
not enough:

- **`target type is ip`** — the flag that cannot be changed after creation and whose error surfaces four
  steps away, in a message about network modes rather than about target types.
- **`the two public subnets are in TWO different AZs`** — a single-zone load balancer in front of a
  two-zone service is a fault that no amount of testing in one zone will reveal.
- **`usms-enrolment-sg no longer admits usms-app-sg`** — this asserts that the Step 13 cutover actually
  happened. Without it, a student who skipped Step 13 has a working system with two paths, one of which
  is undocumented, which is strictly worse than either alternative.
- **`containerName is enrolment-api`** — catches the single most common attachment error, and catches it
  as a string comparison rather than as a support case three weeks later.
- **`healthCheckGracePeriodSeconds is set`** — catches the restart loop described in Step 10, which
  presents as "my service will not stabilise" and has nothing to do with the application.
- **`exactly ONE deployment`** — a service with two deployments has one stuck mid-roll. Nothing else in
  the script would notice, and it will still be stuck next week.
- **`no template contains an unexpanded variable`** — catches a quoted heredoc where an unquoted one was
  needed, which is the most common silent bug in this course and has now had four opportunities to
  appear in two labs.

And, as in every lab, the environment block comes first: a script that verifies only its own resources
passes right up until the restart that deletes them.

### 9.2 Build `scripts/utilities/verify-lab-04b.sh`

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-04b.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 04B artefact exists and is configured correctly.
# Read-only: this script inspects and changes nothing. Safe to run at any time.
# Exit 0 if every check passes, 1 otherwise.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-04a.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-04b.env" 2>/dev/null || true

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

echo "== Lab 02 to 04A dependencies =="
check "usms-vpc exists" "aws ec2 describe-vpcs --vpc-ids $USMS_VPC_ID"
check "usms-public-subnet-a exists" "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_A"
check "usms-public-subnet-b exists" "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_B"
check "the two public subnets are in TWO different AZs" \
  "test -n \"\$(az $USMS_PUBLIC_SUBNET_A)\" && test \"\$(az $USMS_PUBLIC_SUBNET_A)\" != \"\$(az $USMS_PUBLIC_SUBNET_B)\""
check "usms-app-sg still exists" "aws ec2 describe-security-groups --group-ids $USMS_APP_SG"
check "cluster $USMS_ECS_CLUSTER is ACTIVE" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "service $USMS_ENROLMENT_SERVICE is ACTIVE" "test \"\$(svcq status)\" = ACTIVE"

echo "== Lab 04B security groups =="
check "usms-alb-sg exists" "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG"
check "usms-alb-sg admits tcp/80 from 0.0.0.0/0" \
  "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG --query 'SecurityGroups[0].IpPermissions[?FromPort==\`80\`].IpRanges[].CidrIp' --output text | grep -q '0.0.0.0/0'"
check "usms-enrolment-sg admits tcp/80 from usms-alb-sg" \
  "sgsrc $USMS_ENROLMENT_SG | grep -qw $USMS_ALB_SG"
check "cutover done: usms-enrolment-sg no longer admits usms-app-sg" \
  "! sgsrc $USMS_ENROLMENT_SG | grep -qw $USMS_APP_SG"

echo "== Lab 04B load balancer =="
check "load balancer $USMS_ALB_NAME exists" "aws elbv2 describe-load-balancers --names $USMS_ALB_NAME"
check "load balancer state is active"        "test \"\$(lbq 'State.Code')\" = active"
check "scheme is internet-facing"            "test \"\$(lbq Scheme)\" = internet-facing"
check "type is application"                  "test \"\$(lbq Type)\" = application"
check "spans TWO availability zones"         "test \"\$(lbq 'length(AvailabilityZones)')\" = 2"
check "carries usms-alb-sg" \
  "aws elbv2 describe-load-balancers --names $USMS_ALB_NAME --query 'LoadBalancers[0].SecurityGroups' --output text | grep -qw $USMS_ALB_SG"

echo "== Lab 04B target group =="
check "target group $USMS_TG_NAME exists" "aws elbv2 describe-target-groups --names $USMS_TG_NAME"
check "target type is ip (mandatory for awsvpc)" "test \"\$(tgq TargetType)\" = ip"
check "protocol HTTP on port 80" \
  "test \"\$(tgq Protocol)\" = HTTP && test \"\$(tgq Port)\" = 80"
check "target group lives in usms-vpc" "test \"\$(tgq VpcId)\" = $USMS_VPC_ID"
check "health check is GET / with matcher 200" \
  "test \"\$(tgq HealthCheckPath)\" = / && test \"\$(tgq 'Matcher.HttpCode')\" = 200"
check "deregistration delay is 30 seconds" \
  "test \"\$(tgattr deregistration_delay.timeout_seconds)\" = 30"

echo "== Lab 04B listener and rule =="
check "a listener exists on port 80" "test \"\$LARN\" != none && test -n \"\$LARN\""
check "listener default action forwards to $USMS_TG_NAME" \
  "aws elbv2 describe-listeners --listener-arns \"\$LARN\" --query 'Listeners[0].DefaultActions[0].TargetGroupArn' --output text | grep -q ':targetgroup/$USMS_TG_NAME/'"
check "at least one non-default rule exists" \
  "test \"\$(aws elbv2 describe-rules --listener-arn \"\$LARN\" --query 'length(Rules[?IsDefault==\`false\`])' --output text)\" -ge 1"
check "the non-default rule returns a fixed-response 200" \
  "aws elbv2 describe-rules --listener-arn \"\$LARN\" --query 'Rules[?IsDefault==\`false\`].Actions[0].FixedResponseConfig.StatusCode' --output text | grep -q 200"

echo "== Lab 04B service wiring =="
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
check "configs/lab-04b.env exists" "test -f configs/lab-04b.env"
check "configs/lab-04b.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=\$|=None\$' configs/lab-04b.env"
check "policies/usms-alb-sg-ingress.json is valid JSON" \
  "python3 -m json.tool policies/usms-alb-sg-ingress.json"
check "policies/usms-enrolment-sg-ingress-alb.json is valid JSON" \
  "python3 -m json.tool policies/usms-enrolment-sg-ingress-alb.json"
check "templates/lab-04b-listener-default-actions.json is valid JSON" \
  "python3 -m json.tool templates/lab-04b-listener-default-actions.json"
check "templates/lab-04b-rule-conditions.json is valid JSON" \
  "python3 -m json.tool templates/lab-04b-rule-conditions.json"
check "templates/lab-04b-rule-actions.json is valid JSON" \
  "python3 -m json.tool templates/lab-04b-rule-actions.json"
check "templates/lab-04b-service-load-balancers.json is valid JSON" \
  "python3 -m json.tool templates/lab-04b-service-load-balancers.json"
check "no Lab 04B document contains an unexpanded variable" \
  "! grep -q '[\$]' templates/lab-04b-listener-default-actions.json templates/lab-04b-service-load-balancers.json policies/usms-enrolment-sg-ingress-alb.json"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"

if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

A failure under "== Environment ==" is the real problem, and most failures below it are
a consequence. Fix that block first:
  ./scripts/utilities/floci-storage-check.sh

A failure under "== Lab 02 to 04A dependencies ==" means an earlier lab's resource is
gone. Run verify-lab-02.sh, verify-lab-03.sh and verify-lab-04a.sh before re-reading
anything here. Remember that verify-lab-04a.sh is EXPECTED to report exactly one
failure after Step 13, on the usms-app-sg source check.
REMEDY
fi

[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-04b.sh
bash -n scripts/utilities/verify-lab-04b.sh && echo "syntax OK"
./scripts/utilities/verify-lab-04b.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Lab 02 to 04A dependencies ==
  ok   usms-vpc exists
  ok   usms-public-subnet-a exists
  ok   usms-public-subnet-b exists
  ok   the two public subnets are in TWO different AZs
  ...
== Lab 04B target group ==
  ok   target type is ip (mandatory for awsvpc)
  ...
== Lab 04B service wiring ==
  ok   containerName is enrolment-api
  ok   healthCheckGracePeriodSeconds is set (not None, not 0)
  ...
== Files and Git hygiene ==
  ok   no Lab 04B document contains an unexpanded variable
  ok   no secret is tracked by git

PASS=49  FAIL=0
```

> Example output — the middle is abbreviated; you will see all 49.

**The expected count is `PASS=49  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `deregistration delay is 30 seconds` | Some builds do not implement `modify-target-group-attributes`. Confirm with `describe-target-group-attributes` and record it |
| `load balancer state is active` | Some builds leave the state at `provisioning` indefinitely. Confirm with `describe-load-balancers --query 'LoadBalancers[0].State'` and record it |
| `the non-default rule returns a fixed-response 200` | Some builds do not implement `create-rule`. If Step 15 failed outright, record it; the listener's default action still works |
| `healthCheckGracePeriodSeconds is set` | Some builds accept the flag on `update-service` and do not store it. Confirm with `describe-services --output json` and record it |
| `the two public subnets are in TWO different AZs` | Lab 2's Step 11 "Your turn" was skipped, or both subnets were made in one zone. This one is **not** benign — the load balancer is a single point of failure, and Section 14.1 Task D marks it as a fault |
| `cutover done: usms-enrolment-sg no longer admits usms-app-sg` | Step 13 was skipped. Also **not** benign — go and do it |
| `exactly ONE deployment` | Some builds report zero deployments rather than one. Check with `--query 'services[0].deployments'` and record which it is |

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** the ECS service `usms-enrolment-svc`, the listener rule, the listener, the
    load balancer `usms-enrolment-alb`, the target group `usms-enrolment-tg` and the security group
    `usms-alb-sg`.

    **What depends on it:** Lab 04C registers a scalable target against `usms-enrolment-svc` and may name
    `usms-enrolment-tg` in a request-count scaling policy. The CloudFormation lab re-declares this whole
    stack as a template and compares it with what you built by hand.

    **Reversible?** No. You would repeat this laboratory from Step 4, and Part A's Step 13 as well,
    because this script deletes the service.

    **Effect on later labs:** total. Run it only at the end of the course, and run the cleanup scripts in
    this order:

    ```text
    scripts/cleanup/lab-04-cleanup.sh    (Lab 04C — scaling configuration)
    scripts/cleanup/lab-04b-cleanup.sh   (this one — load balancer and the service)
    scripts/cleanup/lab-04a-cleanup.sh   (cluster, task definitions, roles, log group)
    scripts/cleanup/lab-03-cleanup.sh
    scripts/cleanup/lab-02-cleanup.sh
    ```

    Inside-out, every time. This script refuses to run while a scalable target still exists, because
    deleting the service out from under one leaves an orphan that is easy to forget and impossible to
    explain later.

    It requires you to type `DELETE USMS LOAD BALANCER` in full before it does anything.

**Run from**

```text
aws-floci-course/
```

````bash
cat > scripts/cleanup/lab-04b-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 04B, dependencies first.
# Order: service -> rules -> listener -> load balancer -> target group -> security group.
# Run AFTER scripts/cleanup/lab-04-cleanup.sh and BEFORE scripts/cleanup/lab-04a-cleanup.sh.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04a.env"
source "$REPO_ROOT/configs/lab-04b.env"

cat <<'WARN'
============================================================
  This deletes the USMS enrolment SERVICE, the Application
  Load Balancer usms-enrolment-alb, its listener and rule,
  the target group usms-enrolment-tg and the security group
  usms-alb-sg.

  Lab 04C, Lab 05 and the CloudFormation lab depend on parts
  of it. None of this is reversible.

  Run AFTER  lab-04-cleanup.sh
  Run BEFORE lab-04a-cleanup.sh
============================================================
WARN

# Refuse while Lab 04C's scaling configuration still points at this service.
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
echo "Lab 04B teardown complete. scripts/cleanup/lab-04a-cleanup.sh may now run."
EOF

chmod +x scripts/cleanup/lab-04b-cleanup.sh
bash -n scripts/cleanup/lab-04b-cleanup.sh && echo "syntax OK — do NOT run it"
````

**What to look for:** the words `syntax OK — do NOT run it`. `bash -n` parses a script without executing
a single command, and it is the only safe way to check a destructive one.

The order is the lesson, and every step of it is a dependency the APIs enforce:

1. **The service first.** While it exists it keeps registering targets, and a target group with
   registered targets is a target group something is using.
2. **Rules before the listener.** Deleting a listener removes its rules anyway, but doing it explicitly
   means the script's output tells you what went away.
3. **The listener before the load balancer.** Same reasoning, same enforcement.
4. **The load balancer before the target group.** `delete-target-group` fails with
   `ResourceInUseException` while any listener forwards to it, and the error names the listener rather
   than explaining the dependency.
5. **Wait for the load balancer to be gone before the security group.** An ALB's elastic network
   interfaces hold its security group for a short while after the load balancer object disappears, and
   `delete-security-group` fails with `DependencyViolation` until they are released — an error that does
   not tell you which interface is holding it.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, five env files sourced, `verify-lab-02.sh`, `verify-lab-03.sh` and `verify-lab-04a.sh` all `FAIL=0`, both public subnets present in two different AZs, and your support path (A, B or C) recorded in `notes/lab-04b-notes.md` |
| 2 | Step 5 | `usms-enrolment-alb` exists, `active`, `internet-facing`, type `application`, one node in each of two Availability Zones, carrying `usms-alb-sg`, with no listener yet |
| 3 | Step 8 | `usms-enrolment-tg` created with `--target-type ip`, health check `GET /` every 30 seconds, matcher `200`, deregistration delay 30; a listener on HTTP:80 whose default action forwards to it; the target group reporting one attached load balancer and zero targets |
| 4 | Step 11 | The service carrying one `loadBalancers` entry naming `enrolment-api` on port 80, a 60-second grace period, an unchanged task definition, and two targets registered **by the service** — one address in each private subnet |
| 5 | Step 14 | A forced deployment observed, with target states `initial`, `healthy` and `draining` all seen, and pre and post address lists that differ while the configuration does not |
| 6 | Step 15 | A rule at priority 10 matching `/alb-health` with a `fixed-response` action, listed above the default action in `describe-rules` |
| 7 | Step 16 | `PERSISTENCE PROVEN` after a Floci stop and start, with every ARN **re-derived from the API** and seven facts compared across three services |
| 8 | Step 19 | `configs/lab-04b.env` populated with 15 exports and committed; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 11. Troubleshooting

??? danger "`ValidationError: At least two subnets in two different Availability Zones must be specified`"
    The single most common failure in this lab, and it happens at Step 5 before anything else exists.

    ```bash
    aws ec2 describe-subnets --subnet-ids "$USMS_PUBLIC_SUBNET_A" "$USMS_PUBLIC_SUBNET_B" \
      --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,CIDR:CidrBlock}' --output table
    ```

    Two rows with **two different** `AZ` values is what you need. One row means
    `$USMS_PUBLIC_SUBNET_B` is empty and Lab 2's Step 11 "Your turn" was skipped. Two rows with the same
    AZ means the second subnet was created in the wrong zone.

    Neither is fixable from this lab. Go back to Lab 2, create the subnet in `us-east-1b` with Lab 2's
    CIDR, regenerate `configs/lab-02.env` with Lab 2 Step 24, and start this lab again from Step 1.

??? danger "`ValidationError` about the subnet having no internet gateway route, on create-load-balancer"
    You passed private subnets to an `internet-facing` load balancer. The scheme and the subnets have to
    agree: `internet-facing` needs subnets whose route table has a default route to an internet gateway,
    and `internal` needs the opposite.

    ```bash
    aws ec2 describe-route-tables --filters "Name=association.subnet-id,Values=$USMS_PUBLIC_SUBNET_A" \
      --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId]' --output text
    ```

    You want a line reading `0.0.0.0/0` and an `igw-` identifier. If it says `nat-` instead, you are
    looking at `usms-private-rt` and the subnet variable is wrong.

??? danger "`InvalidParameterException: The container enrolment-api does not exist in the task definition`"
    Step 10's `containerName` does not match a container in `usms-enrolment:2`. Ask the task definition
    what its containers are actually called:

    ```bash
    aws ecs describe-task-definition --task-definition usms-enrolment \
      --query 'taskDefinition.containerDefinitions[].{Name:name,Ports:portMappings[].containerPort}' \
      --output table
    ```

    The `Name` column is what `containerName` must equal. Common confusions, in order of frequency: the
    task definition **family** `usms-enrolment`, the service name `usms-enrolment-svc`, and the image
    name. None of those is the container name.

    If the container is right and the port is wrong, the error names the port instead, and the same
    table answers it.

??? danger "`InvalidParameterException` mentioning the network mode, when attaching the service"
    The target group's `TargetType` is `instance`, and Fargate tasks use `awsvpc`, which has no instance
    to register.

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].TargetType' --output text
    ```

    `TargetType` cannot be changed after creation. Delete the target group and create it again with
    `--target-type ip`, then redo Steps 7, 8 and 10 — the listener's default action names the old ARN and
    has to be updated with `aws elbv2 modify-listener`, or the listener recreated.

    This is the reason Step 6's **Verify** tells you to check `Type` before anything else.

??? danger "Targets stay `initial` forever, or go straight to `unhealthy`"
    Work through these four in order. They account for almost every case.

    1. **The security group.** Does `usms-enrolment-sg` admit tcp/80 from `usms-alb-sg`?

        ```bash
        aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
          --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text
        echo "usms-alb-sg = $USMS_ALB_SG"
        ```

    2. **The health check path.** Does the application actually serve `/` with a `200`? An app that
       redirects `/` to `/login` returns `302` and fails a matcher of `200`.
    3. **The port.** The target group's `Port`, the container's `containerPort` and the port the
       application listens on must all agree.
    4. **The reason field**, which usually names the answer:

        ```bash
        aws elbv2 describe-target-health --target-group-arn "$USMS_TG_ARN" \
          --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State,TargetHealth.Reason,TargetHealth.Description]' \
          --output text
        ```

    `Target.FailedHealthChecks` means the probe ran and failed — the application or the matcher.
    `Target.Timeout` means the probe got no answer at all — the security group or the port.
    `Elb.InitialHealthChecking` means it has not finished deciding and you should wait.

    On Floci, targets that never leave `initial` are the expected behaviour on support path B. Record it
    and continue.

??? danger "Target health says `unused`"
    Nothing forwards to this target group. It is registered and reachable and no traffic can be sent to
    it.

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].LoadBalancerArns' --output text
    ```

    An empty result means Step 8 did not run, or the listener's default action names a different target
    group. Check with `describe-listeners` and fix with `modify-listener` rather than recreating
    anything.

??? danger "The service will not stabilise: tasks start and stop in a loop"
    The classic symptom of a missing or too-short health check grace period. The load balancer marks a
    still-starting task unhealthy, ECS replaces it, and the replacement suffers the same fate.

    ```bash
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].{Grace:healthCheckGracePeriodSeconds,Events:events[0:5].message}' --output json
    ```

    If `Grace` is `null` or `0`, set it:

    ```bash
    aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
      --health-check-grace-period-seconds 60 --query 'service.healthCheckGracePeriodSeconds' --output text
    ```

    If it is already 60 and the loop continues, the application genuinely takes longer than 60 seconds to
    start, and the grace period should be raised rather than the health check loosened.

??? danger "`verify-lab-04a.sh` reports a failure after Step 13"
    Expected. Exactly one check fails —
    `usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)` — because Step 13 deliberately replaced
    that source with `usms-alb-sg`.

    Confirm that it is the only one:

    ```bash
    ./scripts/utilities/verify-lab-04a.sh | grep FAIL
    ```

    One line, plus the `PASS=48  FAIL=1` summary. Any other failing line is something else and should be
    investigated.

    Do **not** silence it by putting the old rule back. Either document the expected failure, or do
    Exercise 2 and update the check to assert the new source group. `verify-lab-04b.sh` is the script of
    record from Step 13 onwards.

??? danger "`ResourceInUseException` on `delete-target-group`"
    A listener still forwards to it. Find the listener, and either delete it or point its default action
    somewhere else:

    ```bash
    aws elbv2 describe-target-groups --names usms-enrolment-tg \
      --query 'TargetGroups[0].LoadBalancerArns' --output text
    ```

    The dependency chain is always service, then rules, then listener, then load balancer, then target
    group — which is exactly the order `scripts/cleanup/lab-04b-cleanup.sh` uses.

??? danger "`DependencyViolation` on `delete-security-group` for usms-alb-sg"
    The load balancer's elastic network interfaces still hold the group. They are released a short while
    after the load balancer is deleted, and `aws elbv2 wait load-balancers-deleted` is the polite way to
    wait for it. Find what is holding the group if the wait does not help:

    ```bash
    aws ec2 describe-network-interfaces --filters "Name=group-id,Values=$USMS_ALB_SG" \
      --query 'NetworkInterfaces[].{Id:NetworkInterfaceId,Desc:Description,Status:Status}' --output table
    ```

    An interface described as `ELB app/usms-enrolment-alb/...` is the load balancer's. Wait; do not try
    to delete it.

??? danger "`aws elbv2 wait load-balancer-available` never returns"
    The waiter polls until `State.Code` is `active`. On a build that leaves load balancers in
    `provisioning`, that never happens.

    Interrupt it with ++ctrl+c++ and use the manual polling loop in Step 5 part 2. Record the state you
    observed. Nothing later in this lab requires the state to be `active`; Section 9's script checks it
    and lists the failure among the known benign ones.

??? danger "`curl` returns 503 Service Temporarily Unavailable from the load balancer"
    A `503` from an ALB means the listener worked and there were **no healthy targets** to send the
    request to. This is a good error: it tells you the load balancer, the listener and the rule are all
    fine, and the problem is entirely on the target side.

    Go to the `Targets stay initial forever` entry above and work through its four causes.

    Distinguish it from `502 Bad Gateway`, which means a target *was* chosen and gave an invalid
    response, and from a connection refused or timeout, which means nothing was listening on the load
    balancer at all — the Step 5 Checkpoint's last line.

??? danger "`An error occurred (NoCredentials)` or a suggestion to run `aws login`"
    Do **not** run `aws login`. It begins an interactive sign-in to **real AWS**, and this course's
    entire safety model rests on never touching a real account.

    In this terminal, right now:

    ```bash
    cd ~/aws-floci-course && source configs/course.env && ./scripts/utilities/whoami.sh
    ```

    Permanently: this is Errata 01, and the loader belongs in the startup file your **login** shell
    reads.

??? danger "Everything is gone after a restart"
    Storage mode, as always.

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    If it reports `FLOCI_STORAGE_MODE=memory`, a stray `floci start` has replaced the Compose container.
    The work is not recoverable — restore from the snapshot you took at the end of Part A, and this time
    confirm the storage check before building anything.

---

## 12. Floci vs Real AWS

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
| Access logs to S3 | Full | Not available, and there is no bucket until Lab 05 | Conceptual / Real AWS |
| `AWS/ApplicationELB` CloudWatch metrics (`RequestCount`, `TargetResponseTime`, `HTTPCode_Target_5XX_Count`) | Published every minute | Not published | Conceptual / Real AWS |
| `ALBRequestCountPerTarget` scaling metric | Full, using a `ResourceLabel` | Not available; Lab 04C uses CPU instead | Conceptual / Real AWS |
| Security group enforcement on load balancer or task traffic | Every packet | Not enforced | Floci Limitation |
| Cost — per load balancer hour plus per LCU hour | Real, and a load balancer costs money while idle | Free | Conceptual / Real AWS |
| Service quotas (load balancers, target groups, rules per listener) | Enforced, and rules per listener bites first | Not enforced | Conceptual / Real AWS |

### 12.1 What you actually observed in this lab

```text
OBSERVABLE — you saw this happen
  a security group created that deliberately admits 0.0.0.0/0, and nothing behind it that does
  a load balancer created across two subnets in two Availability Zones
  a load balancer with no listener, answering nothing
  a target group created with target-type ip, and refusing to be anything else afterwards
  a target group attached to a listener, its LoadBalancerArns count going 0 -> 1
  an ECS service attached to a target group without registering a single target by hand
  target addresses that are inside Lab 02's private subnet CIDRs
  a forced deployment producing new addresses and an unchanged configuration
  a listener rule ordered ahead of a default action
  a security cutover, and the exact moment Part A's verification script became wrong
  all of it surviving a container restart, with every ARN re-derived from the API

CONCEPTUAL — you reasoned about it, and may not have seen it
  a request travelling from a client to a task and back      (unless you got a 200 at Step 12)
  a health check probe actually being sent
  a target moving from initial to healthy because it passed two checks
  a target draining while requests already in flight completed
  the load balancer choosing least_outstanding_requests over round robin
  a rule's path condition being evaluated against a real URL
  the 2-to-4-minute provisioning time that stops anyone creating a load balancer per deployment
  HTTPS, certificates, and everything the Step 4 "Your turn" pointed at
  the cost of any of it
```

If your build put you on support path A, several lines move from the second list to the first. Say in
your report which list each item ended up in **for you**. Claiming to have observed something you
reasoned about is worth negative marks, and Section 14.1 Task D checks it.

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **The load balancer appears instantly.** Real provisioning takes two to four minutes, which is why load
  balancers are created by infrastructure code long before a deployment and never as part of one.
- **Health checks always pass, because they never run.** On real AWS the health check is the most common
  reason a correct deployment fails, and the four causes in Section 11 are the four you will actually
  meet.
- **No cost.** An Application Load Balancer bills per hour whether or not anything uses it, plus a
  capacity-unit charge for traffic. An idle load balancer left running is one of the classic
  surprise line items on an AWS bill, and Exercise 4 asks you to quote the current figure with a
  citation.
- **No quotas.** Rules per listener is the one that bites first on a real account, and the failure is a
  `TooManyRulesException` in the middle of a deployment rather than at design time.
- **Security groups are not enforced.** Step 9's rule is what makes the health check work on real AWS.
  Here you could delete it and nothing would change, which is exactly why Section 9's script asserts it
  rather than testing it.
- **Nothing is ever `unhealthy`.** So the most valuable diagnostic in this lab — comparing ECS
  `healthStatus` with target health — is one you have to learn from the table in Step 11 rather than
  from experience.

### 12.3 One thing this lab is *not*

Nothing in this lab is auto scaling. The service's `desiredCount` is still 2 and still moves only when
you type a number.

What changed is that the *signal* for moving it is now available. `AWS/ApplicationELB` publishes
`RequestCount` and `TargetResponseTime` per target group, and Application Auto Scaling has a predefined
metric, `ALBRequestCountPerTarget`, that reads exactly that. Lab 04C was written before this target group
existed and therefore scales on CPU while explaining why requests would be the better signal. Exercise 5
builds the string that closes that gap.

If you can state, in one sentence, why requests per target is a better scaling signal than CPU for a web
API, you are ready for Lab 04C.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-04b-ecs-alb/exercises.md`. Take screenshots into `screenshots/`
where an exercise asks for evidence.

### Exercise 1 — Basic: a second path through the same load balancer

**Requirements**

The USMS results service publishes exam results. It is a separate concern from enrolment and will
eventually be a separate ECS service, but it will share one hostname with enrolment because students
should not have to remember two.

Add a second target group and a listener rule that sends `/results` and everything under it to it:

1. Create `usms-results-tg` with the same target type, protocol and port as `usms-enrolment-tg`, a
   health check path of `/`, a matcher of `200-399`, and a deregistration delay of 15 seconds.
2. Create a listener rule at priority 20 on the existing listener, matching the path patterns `/results`
   and `/results/*`, forwarding to `usms-results-tg`.
3. Read the listener's rules back and confirm the ordering.

**Constraints**

- Every ARN captured with `$(...)` and `--query`. Nothing copied by hand.
- Tag both objects `Project=USMS`, `Tier=app`, `Lab=04B`, `Service=results`.
- Use JSON documents in `templates/` for the rule's conditions and actions, as Step 15 did. Do not use
  the inline shorthand.
- Do **not** create a second ECS service, and do **not** register any target. The target group will be
  empty, and that is the correct state for a target group whose service does not exist yet.
- Do **not** record either object in `configs/lab-04b.env`. Exercise 4 removes them.

**Expected outcome**

`describe-rules` on the listener shows three entries: your new rule at priority 20, the `/alb-health`
rule at priority 10, and the default action. `describe-target-health` on `usms-results-tg` returns an
empty list, and `describe-target-groups` shows it attached to one load balancer.

**Hints**

Steps 6 and 15 contain every command you need; the only question is which values change. For the
ordering, note that `describe-rules` does not necessarily return rules in priority order — Step 16 used
`sort_by` with an expression reference for exactly this reason, and `Priority` is a string, which makes
sorting it interesting.

An empty target group attached to a listener will report its targets as neither healthy nor unhealthy,
because there are none. Say in one sentence what a request to `/results` would receive in that state, and
which of the status codes in Section 11's `curl` entry it would be.

---

### Exercise 2 — Intermediate: repair the verification script you broke

**Requirements**

Step 13 left `verify-lab-04a.sh` asserting something that is no longer true. Fix it properly — which
means understanding what the check was for before changing what it says.

1. Read the failing check in `scripts/utilities/verify-lab-04a.sh` and write down, in one sentence, the
   property it was asserting. Not the command: the property.
2. Change it so that it asserts the equivalent property in the current architecture: that
   `usms-enrolment-sg` is sourced from a **group** and not a CIDR, and that the group is
   `usms-alb-sg`.
3. Add a second check, immediately after it, asserting that `usms-app-sg` is **no longer** a source. A
   check that only confirms the new state would still pass if both rules existed.
4. Make both checks read `usms-alb-sg`'s ID from `configs/lab-04b.env` rather than hard-coding it, and
   make the script tolerate that file not existing — a student who has done Part A and not Part B must
   still be able to run it.
5. Run `verify-lab-04a.sh` and `verify-lab-04b.sh` and get `FAIL=0` from both.
6. Commit the change with a message that explains **why** the assertion changed, not what line moved.

**Constraints**

- The script must keep working from any directory. Do not break its `${BASH_SOURCE[0]}` resolution.
- `set -u` is in force. A missing `USMS_ALB_SG` must produce a failed check with a readable name, not an
  unbound-variable abort before any output.
- The `PASS` count changes. State the new expected count in a comment at the top of the script and in
  your `exercises.md`, and say why an undocumented count is worse than no count.
- Do not delete the original check. Change what it asserts.

**Expected outcome**

Both verification scripts reporting `FAIL=0`, a commit whose message explains an architectural change,
and a two-sentence note in `exercises.md` on when it is right to update a verification script and when
updating one is how you hide a regression.

**Hints**

The distinction in point 1 is the whole exercise. "The enrolment tasks accept traffic only from a named
group, never from an address range" is a property; `IpPermissions[0].UserIdGroupPairs[0].GroupId equals
$USMS_APP_SG` was one expression of it, tied to one architecture. Write the check against the property
and it will survive the next change too.

For point 4, Part A's script already uses the `: "${VAR:=default}"` idiom near the top. That is the
pattern.

---

### Exercise 3 — Problem solving: a load balancer report tool

**Requirements**

Write `scripts/utilities/usms-lb-report.sh`. Given no arguments, it walks every Application Load Balancer
in the account whose name starts with `usms-` and prints its complete decision table, one line per
routing outcome:

```text
usms-enrolment-alb   internet-facing  application  active  AZs=2  SGs=1
  HTTP:80
    prio  10       path-pattern  /alb-health,/alb-health/*   -> fixed-response 200
    prio  20       path-pattern  /results,/results/*         -> usms-results-tg    (0 targets, 0 healthy)
    prio  default  -                                          -> usms-enrolment-tg (2 targets, 2 healthy)
```

**Constraints**

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as Section 9's script
  does.
- Takes no arguments and hard-codes no ARN, no listener, no target group and no load balancer name
  beyond the `usms-` prefix. Everything is discovered.
- Must handle a load balancer with no listeners, a listener with no non-default rules, and a target group
  with no targets, without crashing or printing an empty line where a row should be.
- Rules must be printed in evaluation order, with the default action last. `Priority` is a string, and
  the default action's priority is the literal word `default`, so a naive sort puts it in the wrong
  place. Handle it and say in a comment how.
- An action that is not a `forward` must print its own summary rather than an empty target group column.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- Also write the machine-readable form to `outputs/lab-04b-lb-report.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-04b-ecs-alb/`. Correct output
before and after Exercise 1 adds a second target group, and correct output if you temporarily delete the
`/alb-health` rule.

**Hints**

`describe-load-balancers` with a `--query` filter using `starts_with` finds the load balancers;
`describe-listeners` needs one call per load balancer; `describe-rules` needs one call per listener;
`describe-target-health` needs one call per target group. That is four levels of nesting, and the
interesting design question is where to stop shelling out and start processing JSON in `python3`.

The healthy-target count is `length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])`, which is
a filter, a comparison against a raw string, and a `length()` in one expression.

---

### Exercise 4 — Challenge: the exposure review

**Requirements**

The university's information security officer writes:

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

Produce a written analysis in `labs/lab-04b-ecs-alb/exercises.md` covering:

- **What changed, in exactly two sentences**, one for the network path and one for the security groups.
  An answer longer than two sentences has not been thought about enough.
- **The internal-versus-internet-facing recommendation.** Make the case for `--scheme internal`
  properly: what would change in Step 5's command, what would change about the DNS name, what would
  *not* change at all, and which of the two you would actually recommend for USMS enrolment given that
  the portal is the only known client. Then argue the other side in two sentences, because there is a
  real case for either.
- **The exposure delta, as a table.** Two columns: before this lab and after it. Three rows: what can
  reach the load balancer, what can reach the tasks, and what can reach the tasks *directly*. The third
  row is the one the security officer actually asked about.
- **A monthly cost estimate**, **with a citation**, covering: the Application Load Balancer's hourly
  charge, its capacity-unit charge, and — for comparison — the cost of the two Fargate tasks it fronts.
  State the assumptions for "under load" explicitly. An idle load balancer's monthly cost is a specific
  number and you should quote it.
- **The HTTPS plan.** Name every object that would have to exist, in order, and say which of them AWS
  provides at no charge and which requires something from outside AWS. You have not been taught any of
  this — name each service, say what it provides, and cite the documentation page. Include the listener
  rule you would add on port 80 and what its action type would be.
- **The tidy-up**, with exact commands in the correct dependency order, each preceded by the four-line
  danger admonition used throughout this lab: the `usms-results-tg` target group and the priority-20
  rule from Exercise 1.

Then execute only the deletions, and confirm `./scripts/utilities/verify-lab-04b.sh` reports `FAIL=0`
afterwards.

**Constraints**

- Do not delete anything in Section 16's KEEP column. In particular, do not delete the `/alb-health`
  rule: Section 9's script asserts it.
- Every number must have a source or a derivation. "A few dollars" earns nothing; "an ALB at the
  published per-hour rate for 730 hours, plus N LCU-hours derived from the following assumption" earns
  full marks.
- The HTTPS plan must distinguish between what makes the port *open* and what makes something *listen*
  on it. The Step 4 "Your turn" is the first half of that answer and is not the whole of it.

**Expected outcome**

An analysis a security officer could act on and a finance team could check, plus a repository in which
the practice objects are gone and the verification still passes.

**Hints**

For the cost bullet, the Elastic Load Balancing pricing page defines a Load Balancer Capacity Unit in
terms of four dimensions and bills on the largest; you need to say which one dominates for a low-traffic
internal API, and it is not the one most people guess.

For the HTTPS plan, search the AWS documentation for requesting a public certificate. The answer
involves one service you have not met, one DNS record you would have to create, and a fact about the
price of the certificate that surprises people.

---

### Exercise 5 — Integration: the ResourceLabel hand-off to Lab 04C

**Requirements**

Lab 04C scales this service on CPU, and its own Step 14 explains that requests per target would be the
better signal and that it cannot use one because the course has no load balancer. It does now. Build the
string that unlocks it.

Application Auto Scaling's `ALBRequestCountPerTarget` predefined metric requires a `ResourceLabel`: a
single string identifying one target group behind one load balancer, built by concatenating two ARN
fragments:

```text
<load-balancer-arn-suffix>/<target-group-arn-suffix>

app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
|                                     | |                                            |
+-- from the load balancer's ARN ------+ +-- from the target group's ARN -------------+
```

1. Write `scripts/utilities/usms-resource-label.sh`, which derives that string **from the API** — never
   from a hard-coded identifier — and prints it. It takes a load balancer name and a target group name as
   arguments, defaulting to this lab's two, and validates that it got a plausible result before printing
   it.
2. Append `USMS_ALB_RESOURCE_LABEL` to `configs/lab-04b.env` with that value, derived rather than typed.
   Re-run the empty-value check and state the new export count.
3. Write `outputs/lab-04b-lab04c-readiness.txt` containing, each on its own labelled line: the resource
   label; the target group ARN; the load balancer ARN; the composite scalable resource ID
   `service/<cluster>/<service>` from Part A; the scalable dimension `ecs:service:DesiredCount`; the
   service's current desired count; and one sentence naming which of Lab 04C's three predefined metrics
   you would now recommend and why.
4. **Take a measurement only you can take.** Record a UTC timestamp, force a new deployment, poll until
   the service reports exactly one deployment and its target list is stable, record the timestamp again,
   and write the elapsed seconds to the readiness file. That number is how long a full replacement of
   capacity takes in your environment, and Lab 04C's cooldown choices are sized against it. If your
   build makes the measurement meaningless, say so and cite the figure AWS documents for Fargate task
   start-up instead.
5. Verify the label the only way you can without an auto scaling policy: assert that it contains both
   names, has exactly six slash-separated segments, and that its first segment is the literal `app`.
   Explain in one sentence why `app` is there and what it would be for a Network Load Balancer.

**Constraints**

- The script must work from any directory and must not read `configs/lab-04b.env` for the ARNs — the
  point is deriving them, and a script that reads the answer from a file it helped write is proving
  nothing.
- Use shell parameter expansion, not `awk`, for at least one of the two suffixes, and say in a comment
  why the two suffixes need slightly different treatment. They do, and the difference is instructive.
- The elapsed-time measurement must use `python3` for timestamps, not `date -d` or `date -v`, for the
  reason given in the Prerequisites.
- No script you write here may contain, read or reference an access key.

**Expected outcome**

A committed script Lab 04C and the CloudFormation lab can both call unchanged, a readiness file from
which a Lab 04C reader could write the `put-scaling-policy` call without opening this document, and a
measured figure for how long a capacity replacement takes in your environment.

**This is what Lab 04C will use.** Its Step 14 table has an empty third row; Exercise 5 fills it in.

**Hints**

Both ARNs end with the fragment you want, but they start differently: the load balancer's suffix begins
after `:loadbalancer/` and the target group's suffix **includes** the word `targetgroup`. That asymmetry
is not a mistake in the AWS documentation — read the `ResourceLabel` description in the Application Auto
Scaling `PredefinedMetricSpecification` reference and you will see it is exactly as specified. Part A's
`"${TASK_ARN##*/}"` is the parameter-expansion form; you want a different one from the same family.

For point 5, six segments: `app`, the load balancer name, its id, `targetgroup`, the target group name,
its id.

---

## 14. Lab Assessment Checklist

### 14.1 In-class assessment

**Format.** Individual, at the machine, in the laboratory session. **75 minutes.** Marked out of 100,
from your own repository and your own `exercises.md`.

**When.** After you have completed Sections 8 and 9 and `verify-lab-04b.sh` reports `FAIL=0`. If your
build put you on support path C, tell your instructor before the session starts: Tasks A and B will be
replaced by written equivalents.

**Permitted:** the AWS documentation, this laboratory document, Lab 04A, your own `notes/` and
`exercises.md`, `aws <service> <operation> help`, and the shell history in your own terminal.

**Not permitted:** messaging of any kind, shared terminals, another student's repository, and AI
assistants. The tasks are designed so that the documentation is genuinely enough; two of them are
faster with `help` than with a search engine.

**What to hand in.** Everything is read from your repository, plus these three files, which you create
during the session:

```text
outputs/lab-04b-assessment-a.txt     Task A — commands and their output
outputs/lab-04b-assessment-b.txt     Task B — your diagnosis, in the format below
outputs/lab-04b-assessment-c.md      Task C — four written answers
```

Those files are git-ignored, as everything under `outputs/` is. Your instructor collects them directly;
do not attempt to commit them.

---

#### Task A — Build from requirements (30 marks, about 30 minutes)

No commands are given. The requirements are the specification.

The USMS transcripts API needs its own path through the existing load balancer. Build:

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
5. Written into `outputs/lab-04b-assessment-a.txt`: the commands you ran, their output, and a
   `describe-rules` listing that shows all four rules plus the default in evaluation order.

**Marks**

| | Marks |
| --- | --- |
| Target group created with the correct target type, port, VPC and all five health check values | 10 |
| Deregistration delay set correctly, by attribute rather than by recreation | 3 |
| Priority-30 rule with correct path patterns, forwarding correctly | 6 |
| Priority-5 rule with a correct `fixed-response` action, and placed so it is evaluated **first** | 6 |
| Every ARN captured with `$(...)` and `--query`; nothing copied by hand | 3 |
| Output file complete and legible | 2 |

**One deliberate trap, stated openly:** requirement 4 says the `/admin` rule must be evaluated before
everything else. Getting a rule to be evaluated first is a property of its priority number, and priority
numbers do not have to be assigned in the order you create rules. If you find yourself wanting to
renumber an existing rule, read Step 15's concept block again before you do.

---

#### Task B — Diagnose (25 marks, about 20 minutes)

Before the session your instructor injects **one** fault into your Lab 04B configuration. It is a single
change to a single object, it is reversible, and it is not in Task A's objects. You are not told what it
is or which service it is in.

Find it, and write into `outputs/lab-04b-assessment-b.txt`, in this order:

```text
SYMPTOM     what you observed, and the exact command that showed it to you
HYPOTHESES  at least three plausible causes, ranked, before you tested any of them
TEST        the ONE API call that distinguished the real cause from the others
CAUSE       the object, the field, the wrong value and the right value
FIX         the command you ran
PROOF       the command and output showing the configuration is correct again
```

**Marks**

| | Marks |
| --- | --- |
| Symptom stated precisely, with the command that revealed it | 4 |
| Three or more plausible hypotheses, ranked, written **before** testing | 8 |
| A single discriminating test rather than a sequence of guesses | 6 |
| Correct cause identified, naming the object and the field | 4 |
| Fix applied and proven | 3 |

**Read the mark distribution.** Eight marks for hypotheses you wrote before you knew the answer and six
for choosing one test is 14 of 25 for the *method*, and only 7 for being right. A student who finds the
fault in ninety seconds by luck and writes nothing down scores lower than one who does not find it at
all but reasons well. That is deliberate: on a real system you will not recognise the fault, and the
method is the only thing that transfers.

Section 11 is permitted and is designed for exactly this. So is `verify-lab-04b.sh`, which will point at
a region of the configuration without telling you the value.

---

#### Task C — Explain (25 marks, about 15 minutes)

Answer in `outputs/lab-04b-assessment-c.md`. Prose, no command output. Two to four sentences each; a
long answer is not a better one.

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

---

#### Task D — Evidence and hygiene (20 marks, about 10 minutes)

| | Marks |
| --- | --- |
| `./scripts/utilities/verify-lab-04b.sh` reports `FAIL=0`, or its failures are each named and explained as benign in `notes/lab-04b-notes.md` | 6 |
| `configs/lab-04b.env` exists, is committed, has 15 exports (16 after Exercise 5), and contains no empty value and no `None` | 4 |
| `git status --short` shows nothing under `outputs/` and no root `.env`; `git check-ignore -v` demonstrated on one assessment output file | 4 |
| Your Step 3 support path is stated at the top of `notes/lab-04b-notes.md`, and Section 12.1's observable-versus-conceptual split is annotated for **your** build | 4 |
| A commit exists for this session, with a message that describes the change rather than the files | 2 |

**Negative marking applies to one thing only:** claiming to have observed something your build did not
do. A recorded limitation is worth full marks; an invented `200` is worth minus five.

---

#### Marking bands

| Band | Marks | What it looks like |
| --- | --- | --- |
| Distinction | 80+ | Task A correct first time; Task B's hypotheses show a mental model of the whole chain; Task C's answers would be useful to a colleague |
| Merit | 65–79 | Everything works; the reasoning in B and C is sound but thin in places |
| Pass | 50–64 | The build works, possibly after several attempts; the written answers are correct but describe rather than explain |
| Fail | below 50 | The build does not work and the written work does not show why |

---

### 14.2 Submission checklist

Tick these off before you submit. Every one is checkable from your own repository.

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` appears in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-04b-notes.md`

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
- [ ] The task definition is still `usms-enrolment:2` — no new revision was registered

**Evidence**

- [ ] Step 11's target list showing one address in each private subnet
- [ ] Step 11 part 3's side-by-side ECS health and target health output
- [ ] Step 12's proof, either the `200` **or** `outputs/lab-04b-path-proof.txt` with the reason the data
      path was unavailable
- [ ] Step 13's `diff` showing exactly one check changing state in `verify-lab-04a.sh`
- [ ] Step 14's poll output showing `draining` alongside `healthy`, or the reason it was not observable
- [ ] Step 16's `PERSISTENCE PROVEN` line
- [ ] Step 17's `CUTOVER CONFIRMED` and `LOOP CLOSED` lines
- [ ] `outputs/lab-04b-pre-deploy.txt` and `outputs/lab-04b-post-deploy.txt` present
- [ ] Screenshots in `screenshots/` for Checkpoints 4, 5 and 7

**Hygiene and written work**

- [ ] `configs/lab-04b.env` exists, is committed, has 15 exports (16 after Exercise 5) and no empty values
      or `None`
- [ ] `scripts/utilities/verify-lab-04b.sh` exists and reports `PASS=49  FAIL=0`, or its documented benign
      failures, each explained
- [ ] `scripts/cleanup/lab-04b-cleanup.sh` exists, passes `bash -n`, and has **not** been run
- [ ] `verify-lab-04a.sh` reports `PASS=48  FAIL=1` with the failure explained, **or** `FAIL=0` because
      you did Exercise 2
- [ ] `git status --short` shows nothing under `outputs/`
- [ ] `notes/lab-04b-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-04b-ecs-alb/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding — answer these out loud before you submit**

- [ ] I can name the four Elastic Load Balancing objects and say which one holds the health check
- [ ] I can say why a Fargate target group must be `ip` and what breaks if it is not
- [ ] I can name the object responsible for the contents of the target group, and it is not me
- [ ] I can describe a state in which ECS and the load balancer disagree about a task's health, and what
      it means
- [ ] I can explain, in order, what happens to a request in flight when its task is deregistered

---

## 15. Review Questions

Answer in prose, in your own words, in `notes/lab-04b-notes.md`. No command output — these ask whether
you understood, not whether you typed.

1. Lab 04A wrote a security group rule sourced from a group rather than an address, and gave as its
   reason that the tasks have no stable addresses. This lab put a load balancer in front of them for what
   is arguably the same reason. Explain, in a full paragraph, what these two things have in common, what
   general problem they are both solutions to, and name a third solution to the same problem that appears
   elsewhere in computing.

2. A colleague says "the load balancer's health check says the task is unhealthy, so the application is
   broken". Explain why that inference is unsound. Describe the two states the target group health check
   cannot distinguish between, name which other field distinguishes them, and give the diagnostic
   sequence you would follow.

3. There is no `update-target-group-target-type`. Explain what that tells you about how AWS thinks about
   the difference between a target group's *configuration* and its *identity*, and connect it to Lab
   04A's claim that a task definition revision is immutable. Then name two other fields in this lab that
   behave the same way, and one that looks like it should and does not.

4. Walk through what happens to a single HTTP request that arrives at the load balancer at the exact
   moment ECS decides to stop the task that would have served it. Name every timer involved, where each
   one is configured, and state whether the request succeeds. Then say what would change if
   `deregistration_delay.timeout_seconds` were left at its default of 300.

5. Step 13 removed a rule and Part A's verification script began to fail. Argue both sides: make the case
   that the script should be updated immediately, and the case that it should be left failing and
   documented. Say which you would do on a system with four other engineers on it, and why the answer
   might be different on a system with one.

6. This lab's load balancer is `internet-facing`, and the tasks it forwards to have no public address at
   all. Explain how both of those can be true at once, naming every Lab 2 resource that makes it work.
   Then explain what an attacker who compromised the load balancer's configuration could and could not
   reach, and what would have been different had the tasks been given public addresses instead.

7. Lab 04C scales this service on CPU utilisation and its own text says requests per target would be
   better. Explain why requests per target is a better scaling signal for a web API, name the one
   situation in which CPU is the better of the two, and say what would have to be true about the
   enrolment application for `ALBRequestCountPerTarget` to scale it badly.

---

## 16. What We Built

### 16.1 Reflection

Part A built something correct that nothing could reach. This lab put a name in front of it, and almost
everything interesting about the lab follows from the fact that the name is stable and the things behind
it are not.

The idea to keep is **indirection with an owner**. A target group is a list of addresses, and a list of
addresses is worthless unless something keeps it true. The whole design rests on giving that job to the
ECS service, which already knows every time a task starts or stops because it is the thing starting and
stopping them. You never registered a target; you attached a service, and the service has been
maintaining the list ever since, through a forced deployment, a scale to three and back, and a restart of
the emulator. Ask yourself what you would have had to do at each of those moments if it had not.

The second idea is that **health is a distributed opinion**. Part A's container health check asks the
process whether it is alive. This lab's target group health check asks the network whether the process is
reachable. They are different questions with different answers, and the most valuable table in this
document is the four-row one in Step 11 that says what each combination means. Systems that only ask one
of those two questions are systems that will one day be entirely healthy and entirely unreachable.

The third is an operational habit rather than an idea. Steps 9, 12 and 13 are a cutover, in that order:
add the new path, prove the new path, remove the old one. It would have been shorter to revoke the old
rule at Step 9 and add the new one in the same breath, and the lab would have worked. It would also have
been a change with a window during which nothing was reachable, made without evidence that the
replacement worked. The order is the whole lesson, and it costs one extra step.

And a smaller thing worth noticing. Every command in Steps 4 to 15 reported success, and almost none of
that was evidence. Step 6 proved the target group was empty and told you not to fill it. Step 11 proved
something else had filled it. Step 12 proved the chain link by link when the data path could not be
tested. Step 14 proved a deployment by catching a `draining` target next to a `healthy` one. Step 16
proved persistence by re-deriving every ARN after a restart. **A command that appears to succeed is still
not evidence that it did what you meant** — three labs in, that sentence should be starting to feel less
like a rule and more like a reflex.

### 16.2 KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ════════════════════════╗    ╔═════════════ CLEAN UP ══════════════╗
║ usms-alb-sg               the edge firewall         ║    ║ usms-results-tg                     ║
║ usms-enrolment-alb        the stable name           ║    ║   — Exercise 1 practice;            ║
║ usms-enrolment-tg         Lab 04C's metric names it ║    ║   removed in Exercise 4             ║
║ the HTTP:80 listener      and its default action    ║    ║                                     ║
║ the /alb-health rule      Section 9 asserts it      ║    ║ the priority-20 listener rule       ║
║ usms-enrolment-svc        now load balanced         ║    ║   — same exercise, same removal     ║
║ usms-enrolment-sg         cut over to usms-alb-sg   ║    ║                                     ║
║ configs/lab-04b.env       Lab 04C sources it        ║    ║ outputs/lab-04b-pre/post-*.txt      ║
║ templates/lab-04b-*.json  the reviewable artefacts  ║    ║   — evidence; keep until            ║
║ policies/usms-alb-sg-ingress.json and the ALB one   ║    ║   submitted, then remove            ║
║ scripts/utilities/verify-lab-04b.sh                 ║    ║                                     ║
║ everything from Labs 01, 02, 03 and 04A             ║    ║ outputs/lab-04b-assessment-*.*      ║
║                                                     ║    ║   — after your instructor has       ║
║                                                     ║    ║   collected them                    ║
╚═════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted and your assessment has been collected:

```bash
rm -f outputs/lab-04b-pre-restart.txt  outputs/lab-04b-post-restart.txt
rm -f outputs/lab-04b-pre-deploy.txt   outputs/lab-04b-post-deploy.txt
rm -f outputs/lab-04b-pre-verify-04a.txt outputs/lab-04b-post-verify-04a.txt
git status --short
./scripts/utilities/verify-lab-04b.sh | tail -2
```

Do **not** run `scripts/cleanup/lab-04b-cleanup.sh`, `lab-04a-cleanup.sh`, `lab-03-cleanup.sh` or
`lab-02-cleanup.sh`. They are for the end of the course, in the order given in Section 9.3.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and Lab 04A
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 06
  USMSStudentDataReadWrite ............. on TWO roles, naming a bucket that still does not exist

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
                 ^ the load balancer's two nodes live here, and REQUIRED both subnets
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                                                            -> usms-s3-endpoint
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg, usms-private-nacl

Lab 03  COMPUTE — instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
                  ^ still carries usms-app-sg, which no longer opens anything on the tasks
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> the EC2 Auto Scaling material

Lab 04A COMPUTE — containers you operate
  usms-ecs-cluster
    usms-enrolment-svc     desired 2, both private subnets, no public IP
      usms-enrolment:2     awsvpc, FARGATE, 256/1024, container health check
        executionRoleArn   usms-ecs-exec-role
        taskRoleArn        usms-ecs-task-role -> USMSStudentDataReadWrite
  /usms/ecs/enrolment      retention 7 days

Lab 04B TRAFFIC — the front door                            <-- you are here
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

Lab 04C SCALING (next)
  scalable target  service/usms-ecs-cluster/usms-enrolment-svc   min 2 max 10
    target tracking on CPU today; ALBRequestCountPerTarget is now possible

Lab 05  STORAGE
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for BOTH roles at once
```

---

## 17. Preparation for the Next Lab

Lab 04C — `lab-04-ecs-autoscaling.md`, the document Part A called Part B — takes the service you just put
behind a load balancer and hands its `desiredCount` to Application Auto Scaling. It creates no new
compute, renames nothing, and is unaffected by everything in this lab except that it now has a better
metric available to it.

| From `configs/lab-04b.env` | Lab 04C uses it for |
| --- | --- |
| `USMS_TG_ARN` and `USMS_TG_NAME` | The target group its request-count policy would name |
| `USMS_ALB_ARN` | The other half of the `ResourceLabel` composite string |
| `USMS_ALB_RESOURCE_LABEL` (Exercise 5) | The `ResourceLabel` field, verbatim, if you did Exercise 5 |
| `USMS_SVC_GRACE_PERIOD` | Understanding why a scaled-out task is not counted as capacity for 60 seconds |

| From earlier labs | Lab 04C uses it for |
| --- | --- |
| Lab 04A `USMS_ECS_CLUSTER`, `USMS_ENROLMENT_SERVICE` | The composite resource ID `service/<cluster>/<service>` |
| Lab 04A `USMS_ECS_DESIRED_BASELINE` | The scalable target's minimum capacity of 2 |
| Lab 02 `usms-private-subnet-a` and `-b` | Where new tasks appear when a policy scales out |
| Lab 04B `usms-enrolment-tg` | Where those new tasks are registered, automatically, with no scaling policy involved |

That last row is the connection worth stating out loud before the next session. When Lab 04C's policy
raises `desiredCount` from 2 to 5, three things happen that nobody configures: three tasks start, three
elastic network interfaces appear in the private subnets, and three addresses are registered into this
lab's target group and begin receiving traffic once they pass their health checks. **Auto scaling still
only writes one integer.** Everything else is machinery you have already built.

**Before the next session, confirm all five of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-04a.sh | tail -2
./scripts/utilities/verify-lab-04b.sh | tail -2
grep -c '^export' configs/lab-04b.env
aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].[desiredCount,runningCount,length(loadBalancers),length(deployments)]' --output text
aws elbv2 describe-target-groups --names usms-enrolment-tg \
  --query 'TargetGroups[0].[TargetType,length(LoadBalancerArns)]' --output text
```

You want: `FAIL=1` from the first (with the one expected failure) or `FAIL=0` if you did Exercise 2;
`FAIL=0` from the second; a count of **15** (or 16 after Exercise 5); a desired count of **2** with
exactly **1** load balancer entry and **1** deployment; and `ip` with **1** attached load balancer.

Lab 04C's Step 12 registers a scalable target with a minimum of 2 and will raise the capacity immediately
if it finds the service below that, so arriving at the baseline is not cosmetic.

**Read ahead, five minutes:** find out what a *scalable target* is in Application Auto Scaling, and why
its resource ID for ECS is a constructed string rather than an ARN. You have now built two such
constructed strings — `service/<cluster>/<service>` in Part A and the `ResourceLabel` in Exercise 5 — so
the third will be familiar.

Finally, take a snapshot so that a mistake in Lab 04C is recoverable:

```bash
floci snapshot save lab-04b-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback. Stop Floci first —
archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-04b.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-04b.tar.gz
```

The archive lives in your home directory, **outside** the repository, so it is never a commit candidate.

---

## Appendix A — Command Reference

Every command this lab used, grouped by service.

### Elastic Load Balancing v2 — load balancers

| Command | What it does |
| --- | --- |
| `aws elbv2 create-load-balancer` | Create one. `--type`, `--scheme`, `--subnets` (space separated, two minimum), `--security-groups`, `--ip-address-type` |
| `aws elbv2 describe-load-balancers` | Read them. `--names` or `--load-balancer-arns`. One of only two ELBv2 reads that accept a name |
| `aws elbv2 modify-load-balancer-attributes` | Idle timeout, header handling, access logs, deletion protection |
| `aws elbv2 set-security-groups` | Change an ALB's security groups after creation |
| `aws elbv2 delete-load-balancer` | Delete one. Its listeners and rules go with it |
| `aws elbv2 wait load-balancer-available` | Block until `State.Code` is `active` |
| `aws elbv2 wait load-balancers-deleted` | Block until it is gone, which the security group deletion depends on |
| `aws elbv2 describe-account-limits` | Per-region caps on load balancers, target groups, listeners and rules |

### Elastic Load Balancing v2 — target groups

| Command | What it does |
| --- | --- |
| `aws elbv2 create-target-group` | Create one. `--target-type`, `--protocol`, `--port`, `--vpc-id`, and the five health check flags |
| `aws elbv2 describe-target-groups` | Read them. `--names`, `--target-group-arns`, or `--load-balancer-arn` for everything one balancer uses |
| `aws elbv2 modify-target-group` | Change the health check after creation. **Cannot** change the target type, port protocol or VPC |
| `aws elbv2 describe-target-group-attributes` | Deregistration delay, stickiness, algorithm, slow start |
| `aws elbv2 modify-target-group-attributes` | Set any of those |
| `aws elbv2 describe-target-health` | The targets and their states. The most-used call in this lab |
| `aws elbv2 register-targets` / `deregister-targets` | Manual registration. **Not used in this lab**, and not to be used for an ECS service |
| `aws elbv2 delete-target-group` | Delete one. Fails while a listener forwards to it |

### Elastic Load Balancing v2 — listeners, rules and tags

| Command | What it does |
| --- | --- |
| `aws elbv2 create-listener` | `--protocol`, `--port`, `--default-actions`. Exactly one default action |
| `aws elbv2 describe-listeners` | By `--load-balancer-arn` or `--listener-arns`. Listeners have no names |
| `aws elbv2 modify-listener` | Change the default action, port, protocol or certificate |
| `aws elbv2 delete-listener` | Delete one, and its rules with it |
| `aws elbv2 create-rule` | `--priority`, `--conditions`, `--actions`. Lowest priority is evaluated first |
| `aws elbv2 describe-rules` | By `--listener-arn`. Includes the default action, shown with priority `default` |
| `aws elbv2 modify-rule` / `set-rule-priorities` | Change a rule's conditions and actions, or renumber several at once |
| `aws elbv2 delete-rule` | Delete one non-default rule |
| `aws elbv2 add-tags` / `remove-tags` / `describe-tags` | `--resource-arns` takes **several** ARNs in one call |

### Amazon ECS used in this lab

| Command | What it does |
| --- | --- |
| `aws ecs update-service --load-balancers` | Attach or change the target group a service registers into. Triggers a deployment |
| `aws ecs update-service --health-check-grace-period-seconds` | Ignore target health for the first N seconds of a task's life. Valid only on a load-balanced service |
| `aws ecs update-service --force-new-deployment` | Replace every task with an identical one, from the same revision |
| `aws ecs describe-services` | `loadBalancers`, `healthCheckGracePeriodSeconds`, `deployments`, `events` |
| `aws ecs describe-tasks` | `healthStatus`, and the private address in `attachments` |
| `aws ecs delete-service --force` | Only in the cleanup script, and only after scaling to zero |

### Amazon EC2 used in this lab

| Command | What it does |
| --- | --- |
| `aws ec2 create-security-group` | The load balancer's own group |
| `aws ec2 authorize-security-group-ingress` | `--ip-permissions file://...` for both a CIDR rule and a group-referenced one |
| `aws ec2 describe-security-group-rules` | One object per rule, with its own ID. The only view in which merged rules are separable |
| `aws ec2 revoke-security-group-ingress --security-group-rule-ids` | Remove one specific rule by ID, not by re-describing the permission |
| `aws ec2 describe-instances --filters Name=instance.group-id` | Reverse lookup: which instances carry this group |
| `aws ec2 describe-network-interfaces --filters Name=group-id` | Which interfaces hold a group, when a deletion is refused |

**Five tag conventions now, across five services, and no rule connects them:**

| Service | Syntax |
| --- | --- |
| EC2 | `--tag-specifications 'ResourceType=x,Tags=[{Key=K,Value=V}]'` |
| ECS | `--tags key=K,value=V` (lower case) |
| IAM | `--tags Key=K,Value=V` (capitals, no `ResourceType`) |
| CloudWatch Logs | `--tags K=V` (a plain map) |
| Elastic Load Balancing | `--tags Key=K,Value=V` (capitals, like IAM) |

Run `aws <service> <operation> help` and read the `--tags` synopsis. That habit is more durable than
memorising any of the five.

---

## Appendix B — New JMESPath and CLI patterns introduced

Labs 1 to 04A taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `starts_with()`, `@`, slices, flattening with `[]`, `--filters`,
`--generate-cli-skeleton`, `--cli-input-json`, `--max-items`, waiters and nested CLI shorthand. This lab
adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `Attributes[?Key=='x'].Value` then `\| [0]` | A raw string literal in single quotes inside a filter — the counterpart to the backtick form for JSON literals | Step 7, Section 9 |
| A filter with `\|\|` | Boolean **or** inside a filter expression, to select two named attributes in one call | Step 7 |
| A filter with `&&` | Boolean **and**, combining a boolean literal in backticks with a string in single quotes | Step 13 |
| `sort_by(Listeners,&Port)` | An **expression reference** with `&`, telling `sort_by` which field to order on | Step 16 |
| `Listeners[?Port==` + backtick + `80` + backtick + `]` then `\| [0]` | A numeric JSON literal in backticks, which must be escaped as a backslash-backtick inside an unquoted heredoc or a double-quoted shell string | Steps 16, 18, Section 9 |
| `describe-tags --resource-arns A B` | Several ARNs in one call, returning a `TagDescriptions` list — unusual for an AWS `describe-tags` | Step 17 |
| `--subnets a b` | A space-separated list of strings, which is a **third** CLI list convention alongside `--tags Key=,Value=` and `awsvpcConfiguration={subnets=[a,b]}` | Step 5 |
| `--attributes Key=k,Value=v Key=k2,Value=v2` | A list of key-value structures, repeated, space separated | Steps 5, 7 |
| `--default-actions file://...` and `--conditions file://...` | Nested structures passed as documents. The only sane form once an action has a config block | Steps 8, 15 |
| `--security-group-rule-ids sgr-...` | Revoke one specific rule by its own ID rather than by restating the whole permission | Step 13 |
| A nested command substitution inside an unquoted heredoc | Finding a listener requires its load balancer's ARN, and there is no `describe-listeners --names` | Step 18 |
| `getent hosts` with a `python3 socket` fallback | Resolving a name portably, because `getent`, `host` and `dig` are not all present on macOS and Linux | Step 12 |
| `curl -w '%{http_code} %{time_total}'` | Print selected transfer variables after a request | Steps 12, 15 |
| `case "$ip" in 10.0.3.*)` | Classifying an address against a known CIDR in pure shell, with no tooling | Step 12 |

### The distinction to keep straight

Elastic Load Balancing is an **ARN-first API**, and it has exactly two doors that accept a name:

```text
describe-load-balancers --names usms-enrolment-alb      <- accepts a name
describe-target-groups  --names usms-enrolment-tg       <- accepts a name
everything else                                          <- ARN only
listeners and rules                                      <- have no name at all
```

That is why Step 16's persistence proof re-derives the load balancer and the target group **by name** and
then walks **down** to the listener and the rule. It is also why `configs/lab-04b.env` records four ARNs
rather than four names: a name you cannot pass to the call you need is not an identifier.

Compare with the three identifier styles you have now met for one ECS service:

```text
ECS control-plane calls     --cluster usms-ecs-cluster --service usms-enrolment-svc
ECS tagging calls           --resource-arn arn:aws:ecs:...:service/usms-ecs-cluster/usms-enrolment-svc
Application Auto Scaling    --resource-id service/usms-ecs-cluster/usms-enrolment-svc
ELB request-count metric    ResourceLabel app/<lb-name>/<lb-id>/targetgroup/<tg-name>/<tg-id>
```

Four ways of naming things that all live in the same architecture. The fourth is Exercise 5, and it is
the only one built from fragments of two different ARNs.

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
- [AWS Certificate Manager — requesting a public certificate](https://docs.aws.amazon.com/acm/latest/userguide/gs-acm-request-public.html)
- [`aws elbv2` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/elbv2/)
- [`aws ecs` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/)
- [JMESPath specification](https://jmespath.org/specification.html)

---

*Lab 04B complete. Lab 04C — `lab-04-ecs-autoscaling.md`, the document Part A referred to as Part B —
hands this service's `desiredCount` to Application Auto Scaling and changes nothing else about what you
have built. Start at its Step 1, do its Step 3 probe, and skip to its Step 12: Steps 4 to 11 are Part A,
which you have already finished. When you reach its Step 14, look at the third row of the predefined
metric table, and then look at what Exercise 5 left in `configs/lab-04b.env`.*
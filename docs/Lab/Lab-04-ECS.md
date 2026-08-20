# Lab 04 — Amazon ECS and Service Auto Scaling

*Practical 2 — running the USMS enrolment service on containers, and making it grow and shrink on its own*

---

## 1. Lab Overview

Lab 3 gave USMS two servers. They are exactly the size you made them and they will stay that size
until somebody logs in and changes them. That is fine for a portal that serves a steady trickle of
requests. It is not fine for **enrolment week**, when four thousand students try to register for
modules in the first twenty minutes of a Monday morning and then nothing happens for six days.

This laboratory builds the layer that solves that. You will containerise the USMS enrolment service
onto **Amazon ECS**, running on **Fargate**, inside the private subnets Lab 2 built. Then you will put
it under the control of **Application Auto Scaling** three different ways — reactively on CPU,
reactively on a metric you invent yourself, and proactively on a clock — and you will make the
service's task count move without touching it.

The single most important idea in this lab is that **auto scaling is not a property of your service.**
It is a separate object — a *scalable target* — that points at your service, plus one or more
*policies* that point at the target. The service does not know it is being scaled. Understanding that
separation is what makes the API make sense, and it is why the resource ID you register is a string
you construct by hand rather than an ARN you look up.

**Time:** roughly 4 hours, including the exercises.

**Where this sits in the course**

```text
Lab 01  IAM ..................... roles, policies, instance profile
Lab 02  VPC ..................... the network: subnets, NAT, route tables, security groups
Lab 03  EC2 .................... usms-web-01 and usms-db-01 in that network
Lab 04  ECS + Auto Scaling ..... THIS LAB — containers that scale themselves
Lab 05  S3 ...................... the bucket both usms-ec2-app-role and usms-ecs-task-role name
Lab 06  Lambda .................. functions triggered from that bucket
```

!!! info "A note on the numbering"
    Lab 3 closed by pointing at "Lab 04 — S3". This lab takes the 04 slot instead, because ECS
    depends on nothing that S3 or Lambda would have built — it needs Lab 1's IAM and Lab 2's network,
    and both exist. S3 becomes Lab 05 and Lambda Lab 06. Nothing already created changes name, and
    no file already committed is rewritten.

    Two forward references from Lab 3 now land here rather than where they said they would: the
    "golden AMI in a launch template" promise (Lab 3 Step 20) belongs to **EC2** Auto Scaling, which
    is a different service from the one in this lab, and is still ahead of you. Section 12.3 explains
    the difference so that you do not conflate them.

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. Explain what a cluster, a task definition, a task and a service are in ECS, and say which of the
   four is the thing that gets scaled.
2. Explain what Fargate removes from the EC2 model, and what it does not remove.
3. Write and register a task definition, including `awsvpc` network mode, CPU and memory sizing, an
   execution role, a task role and an `awslogs` log configuration.
4. Distinguish an ECS **task execution role** from an ECS **task role**, and say which one pulls the
   image and which one the application code uses.
5. Create a service in a private subnet and explain, from Lab 2's route table, how it pulls its
   container image at all.
6. Register a scalable target, and construct the composite resource ID `service/<cluster>/<service>`
   correctly.
7. Create a **target tracking** policy, and find the CloudWatch alarms that AWS created and now
   manages on your behalf.
8. Publish a custom CloudWatch metric, alarm on it, and drive a **step scaling** policy from that
   alarm — including reading step adjustment bounds correctly, which are relative to the threshold
   and not absolute.
9. Create a **scheduled** scaling action with a cron expression and a named time zone, and say when
   scheduled scaling is the right answer and reactive scaling is not.
10. Suspend and resume individual scaling behaviours, and explain when you would want to.
11. Prove that a scaling decision actually changed the service's desired count, rather than assuming
    it because the policy was created without error.

---

## 3. Prerequisites

- **Lab 1 complete.** `usms-developer-role`, `USMSStudentDataReadWrite` and the rest of the IAM
  foundation.
- **Lab 2 complete**, including Exercise 5, so that both private subnets exist. This lab puts tasks
  in two Availability Zones.
- **Lab 3 complete.** `usms-app-sg` must be attached to a running `usms-web-01`, because Step 8's
  security group rule references that group and Step 23 checks the reference resolves.
- `./scripts/utilities/verify-lab-02.sh` and `./scripts/utilities/verify-lab-03.sh` both report
  `FAIL=0`.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq` and `python3` available. `python3` is used for timestamp arithmetic, because `date` differs
  between GNU and BSD and this lab needs UTC timestamps in two places.

Check all of that in one go:

```bash
cd ~/aws-floci-course
for t in jq python3 docker; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
```

> Example output — your versions will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
aws-cli/2.17.42 Python/3.11.9 Linux/6.5.0 exe/x86_64.ubuntu.22
```

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

Created in this lab:
- usms-ecs-cluster              ECS cluster, Container Insights requested
- /usms/ecs/enrolment           CloudWatch Logs log group, 7-day retention
- usms-ecs-exec-role            task EXECUTION role; pulls the image, writes the log stream
- usms-ecs-task-role            task role; the application's own identity
- USMSECSTaskExecution          customer managed policy for the execution role
- usms-enrolment-sg             security group: tcp/80 from usms-app-sg only
- usms-enrolment (family)       task definition, awsvpc, FARGATE, 256 CPU / 512 MiB
- usms-enrolment-svc            ECS service, desired count 2, across both private subnets
- scalable target               service/usms-ecs-cluster/usms-enrolment-svc  min 2 max 10
- usms-enrolment-cpu-target     TargetTrackingScaling policy on CPU at 60 percent
- usms-enrolment-backlog-high   CloudWatch alarm on USMS/Enrolment EnrolmentQueueDepth
- usms-enrolment-queue-step     StepScaling policy driven by that alarm
- usms-enrolment-window-open    scheduled action, 07:45 Asia/Thimphu, raises the floor
- usms-enrolment-window-close   scheduled action, 18:00 Asia/Thimphu, lowers it again
- policies/trust-ecs-tasks.json, policies/usms-ecs-task-execution-policy.json
- templates/lab-04-taskdef.json, templates/lab-04-target-tracking.json,
  templates/lab-04-step-scaling.json
- configs/lab-04.env
- scripts/utilities/verify-lab-04.sh
- scripts/utilities/usms-publish-queue-depth.sh   (Exercise 5)
- scripts/cleanup/lab-04-cleanup.sh

Required for future labs:
- usms-ecs-task-role            -> Lab 05 creates the bucket its policy already names
- USMS/Enrolment metric namespace -> the CloudWatch lab builds a dashboard from it
- usms-ecs-cluster              -> the CloudFormation lab re-declares this service as a template
- usms-enrolment-svc            -> the SNS/SQS lab replaces the invented queue-depth metric with a
                                   real SQS ApproximateNumberOfMessagesVisible metric
```

### 4.2 What this lab genuinely reuses

Not mentions — uses.

| From | Used here how |
| --- | --- |
| Lab 2 `usms-private-subnet-a` and `-b` | Step 10 places the service's tasks in both, by ID from `configs/lab-02.env` |
| Lab 2 `usms-nat` and `usms-private-rt` | Step 10 explains, and Step 11 verifies, that this is the only reason a task in a private subnet can pull a container image |
| Lab 2 `usms-s3-endpoint` | Step 10 names it: container image layers are stored in S3, so the endpoint is on the path too |
| Lab 2 `usms-app-sg` | Step 8 makes it the *source* of the enrolment service's only inbound rule — the web tier is the only thing allowed to call the enrolment API |
| Lab 3 `usms-web-01` | Step 23 resolves the group reference from Step 8 back to the instance that carries it, closing the loop |
| Lab 1 `USMSStudentDataReadWrite` | Step 7 attaches it to `usms-ecs-task-role`, so the container gets the same bucket permissions the EC2 instance has |
| Lab 1 `usms-developer-role` | Step 4 creates the cluster while holding it, then restores your normal identity |
| `configs/course.env` names | `$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT` used, never redeclared |

### 4.3 The moment three labs meet

Lab 1 wrote `USMSStudentDataReadWrite` describing a bucket that does not exist. Lab 3 attached it to
an EC2 instance and traced the chain. This lab attaches **the same policy** to a completely different
kind of compute — a container task — and the chain is the same shape: task → task role → policy →
bucket ARN.

That is the point worth pausing on when you reach Step 7. The instance profile in Lab 3 and the task
role here are two different mechanisms for delivering the same thing: **temporary credentials to code
that never sees a key.** When Lab 5 finally runs `create-bucket`, *both* of them start working at the
same moment, and neither one needed to be changed.

Say that out loud before you continue. It is a review question, and it is the single most useful
sentence about IAM in the whole course.

---

## 5. What We Are Building

The USMS enrolment service. It is the endpoint the student portal calls when somebody clicks
"Register for this module". Its load profile is the reason this lab exists:

| Time | Load | What the service needs |
| --- | --- | --- |
| Enrolment Monday, 08:00–08:20 | 4,000 students, 200 requests/second | 8 to 10 tasks, *already running* before the first request |
| Enrolment week, rest | 300 requests/minute | 3 or 4 tasks |
| Ordinary term time | 20 requests/minute | 2 tasks, which is the floor for availability, not for load |
| 02:00 any night | nothing | still 2 tasks, because one AZ can fail at 02:00 |

Read the first and third rows together. They are the whole argument of this lab: a system sized for
row one wastes money for fifty-one weeks, and a system sized for row three fails on the one morning
that matters. Auto scaling is how you have both, and the three mechanisms in this lab map onto the
three rows.

### 5.1 The three mechanisms, and which row each one answers

**Target tracking** — you name a metric and a number you want it to sit at, and AWS works out the
capacity. "Keep average CPU at 60 percent." It creates and manages its own CloudWatch alarms. This is
the default answer and it handles row two.

**Step scaling** — you own the alarm, and you say how much capacity to add for how far past the
threshold the metric has gone. More work, more control. Use it when the metric is not proportional to
capacity in the way target tracking assumes — a queue backlog, for example, where being 500 messages
behind needs a much bigger response than being 20 behind. This handles the spiky part of row one.

**Scheduled scaling** — you raise the floor at a time you choose. It is the only mechanism that can
have capacity ready **before** the load arrives, because the other two are reactive by definition and
a Fargate task takes tens of seconds to start. This is the honest answer to row one's first minute.

The trap the whole industry falls into is reaching for the reactive mechanisms alone. A reactive
policy cannot scale out before a spike it has not seen yet. If you know when enrolment opens — and a
university does know — scheduled scaling is not a fallback, it is the correct primary control, with
the reactive policies underneath it as a safety net.

### 5.2 The capacity plan

```text
minimum capacity     2 tasks     one per Availability Zone; survives losing one AZ
maximum capacity    10 tasks     the ceiling; a bug that loops must not cost 400 tasks
target CPU          60 percent   headroom for a burst while a new task starts
scale-out cooldown  60 seconds   short: reacting late is worse than reacting twice
scale-in cooldown  300 seconds   long: shrinking eagerly causes flapping
enrolment window     6 to 12     the scheduled floor and ceiling, 07:45 to 18:00
```

Every one of those six numbers is a decision with a reason, and Exercise 4 asks you to defend a
different set. There is no universally correct answer; there is only an answer with the trade-off
stated.

---

## 6. Architecture

```text
                                Internet
                                    |
                          +---------+---------+
                          |     usms-igw      |
                          +---------+---------+
                                    |
  ==================================|=========================================
  ||  usms-vpc  10.0.0.0/16         |                                       ||
  ||   usms-public-rt  0.0.0.0/0 ---+                                        ||
  ||        |                                                               ||
  ||   +----+--------------------------------------------------------+       ||
  ||   | usms-public-subnet-a  10.0.1.0/24  us-east-1a               |       ||
  ||   |   [ usms-web-01 ]  usms-app-sg    <- Lab 03                 |       ||
  ||   |   [ usms-nat    ]  Elastic IP     <- Lab 02                 |       ||
  ||   +----+---------------------------------------------------+----+       ||
  ||        |  tcp/80, source = usms-app-sg                     |            ||
  ||        v                                                   |  outbound  ||
  ||   +------------------------------------------------+       |  image     ||
  ||   |  usms-enrolment-sg   in: tcp/80 from usms-app-sg |       |  pull      ||
  ||   +------------------------------------------------+       |            ||
  ||        |                          |                        v            ||
  ||   +----+-----------------+   +----+-----------------+  usms-private-rt  ||
  ||   | usms-private-        |   | usms-private-        |  0.0.0.0/0        ||
  ||   |   subnet-a           |   |   subnet-b           |    -> usms-nat    ||
  ||   | 10.0.3.0/24  AZ a    |   | 10.0.4.0/24  AZ b    |  pl-... -> S3     ||
  ||   |                      |   |                      |     endpoint      ||
  ||   |  [ task 1 ]          |   |  [ task 2 ]          |                   ||
  ||   |  [ usms-db-01 ]      |   |                      |                   ||
  ||   +----------------------+   +----------------------+                   ||
  ||                                                                        ||
  ||   ECS control plane                                                    ||
  ||     usms-ecs-cluster                                                   ||
  ||       usms-enrolment-svc      desiredCount  <---- THE THING THAT SCALES ||
  ||         task definition usms-enrolment:1                               ||
  ||           execution role usms-ecs-exec-role  -> pull image, write logs ||
  ||           task role      usms-ecs-task-role  -> USMSStudentDataReadWrite||
  ==========================================================================

  Application Auto Scaling                     CloudWatch
  +--------------------------------------+     +---------------------------------+
  | scalable target                      |     | TargetTracking alarms (managed) |
  |   service/usms-ecs-cluster/          |<----|   AlarmHigh / AlarmLow          |
  |     usms-enrolment-svc               |     |                                 |
  |   ecs:service:DesiredCount           |     | usms-enrolment-backlog-high     |
  |   min 2   max 10                     |<----|   USMS/Enrolment                |
  |                                      |     |   EnrolmentQueueDepth > 100     |
  |  policy usms-enrolment-cpu-target    |     +---------------------------------+
  |  policy usms-enrolment-queue-step    |
  |  action usms-enrolment-window-open   |  cron(45 7 * * ? *)  Asia/Thimphu
  |  action usms-enrolment-window-close  |  cron(0 18 * * ? *)  Asia/Thimphu
  +--------------------------------------+
```

Read the bottom-left box again at the end of the lab. Notice that the scalable target names the
service by *string*, and that nothing in the ECS boxes points back at it. The dependency runs one
way, and that is deliberate.

---

## 7. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-04-ecs-autoscaling/
│       ├── README.md                              # this document
│       └── exercises.md                           # Section 13
├── policies/
│   ├── trust-ecs-tasks.json                       # NEW — trust policy for both ECS roles
│   └── usms-ecs-task-execution-policy.json        # NEW — USMSECSTaskExecution document
├── templates/
│   ├── lab-04-taskdef.json                        # NEW — register-task-definition input
│   ├── lab-04-target-tracking.json                # NEW — target tracking configuration
│   └── lab-04-step-scaling.json                   # NEW — step scaling configuration
├── configs/
│   └── lab-04.env                                 # NEW
├── scripts/
│   ├── utilities/
│   │   ├── verify-lab-04.sh                       # NEW — Section 9
│   │   └── usms-publish-queue-depth.sh            # NEW — Exercise 5
│   └── cleanup/
│       └── lab-04-cleanup.sh                      # NEW — end of course only
└── outputs/
    └── lab-04-*.json / *.txt                      # command output, git-ignored
```

Note where the three JSON scaling documents live. They go in `templates/`, not `policies/`, because
they are **API request bodies**, not IAM policy documents. `policies/` in this course means "a
document that grants or denies something". Keeping the two apart matters more than it looks: a
reviewer scanning `policies/` should be looking at your security posture and nothing else.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-04-ecs-autoscaling
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs-autoscaling
```

---
## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Every path below (`configs/...`, `policies/...`, `templates/...`, `scripts/...`) is relative to
    that directory. If a command reports `No such file or directory`, check `pwd` first.

### Step 1 — Resume the environment and load three env files

**Purpose**

Bring Floci up and load everything the previous three labs recorded. This lab reads eight values from
`configs/lab-02.env` and `configs/lab-03.env`; loading them is the standard opening from here on.

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

./scripts/utilities/whoami.sh

printf '%-26s %s\n' \
  "private subnet a"    "$USMS_PRIVATE_SUBNET_A" \
  "private subnet b"    "$USMS_PRIVATE_SUBNET_B" \
  "app security group"  "$USMS_APP_SG" \
  "vpc"                 "$USMS_VPC_ID" \
  "nat gateway"         "$USMS_NAT_GW" \
  "web instance"        "$USMS_WEB_INSTANCE" \
  "region"              "$AWS_REGION_COURSE" \
  "account"             "$ACCOUNT_ID"
```

**What the command does**

`floci-up.sh` is idempotent — it starts the container if it is stopped, says so if it is already
running, and refuses to adopt a container that Compose did not create. `whoami.sh` exits 1 if the
account is not `000000000000`, which is the guard that stops a course command reaching a real account.

**Expected result**

```text
[floci-up] container 'floci' already running (compose project: floci-course)

Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Profile  : floci

private subnet a           subnet-09876fedcba543210
private subnet b           subnet-0aabbccdd11223344
app security group         sg-0123456789abcdef0
vpc                        vpc-0a1b2c3d4e5f67890
nat gateway                nat-0abcdef1234567890
web instance               i-0123456789abcdef0
region                     us-east-1
account                    000000000000
```

> Example output — your IDs will differ.

**Verify**

Eight non-empty values. `private subnet b` empty means Lab 2 Exercise 5 was skipped — go and do it,
because Step 10 places tasks across two Availability Zones and a service with one subnet cannot
survive an AZ failure, which is half of why the minimum capacity in this lab is 2.

---

### Step 2 — Confirm Labs 2 and 3 are still intact

**Purpose**

A week may have passed. This lab builds on top of nine resources from two previous labs; check they
are there and still configured correctly before adding anything.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
./scripts/utilities/verify-lab-02.sh
./scripts/utilities/verify-lab-03.sh
```

**Expected result**

```text
...
PASS=33  FAIL=0
...
PASS=36  FAIL=0
```

**Verify**

`FAIL=0` twice. Anything else stops this lab, and the order matters: failures under the
`== Environment ==` heading are the real problem, and every resource failure below them is a
consequence. Fix the environment first.

Two specific failures would ruin this lab silently rather than loudly:

- **`private rt has NO route to an internet gateway`** failing would mean the private subnets are not
  private, and Step 10's whole argument collapses.
- **`usms-web-01 carries usms-app-sg`** failing would mean Step 8's group reference points at a group
  nothing uses, and Step 23's loop-closing check would be meaningless.

---

### Step 3 — Probe what this Floci build actually supports

**Purpose**

This is the only lab in the course whose central service — Application Auto Scaling — may be absent
from your build entirely. Rather than discovering that at Step 12, find out now, and find out which of
three paths you are on. This is the same principle as Lab 1's storage check: name the limitation before
it costs you an hour, not afterwards.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
probe() {
  printf '%-46s ' "$1"
  if eval "$2" >/dev/null 2>&1; then echo "SUPPORTED"; else echo "not available"; fi
}

echo "== ECS =="
probe "ecs list-clusters"                "aws ecs list-clusters"
probe "ecs register-task-definition"     "aws ecs register-task-definition --generate-cli-skeleton"
probe "ecs describe-services"            "aws ecs describe-services --cluster probe --services probe"

echo "== Application Auto Scaling =="
probe "describe-scalable-targets"        "aws application-autoscaling describe-scalable-targets --service-namespace ecs"
probe "describe-scaling-policies"        "aws application-autoscaling describe-scaling-policies --service-namespace ecs"
probe "describe-scheduled-actions"       "aws application-autoscaling describe-scheduled-actions --service-namespace ecs"

echo "== CloudWatch =="
probe "cloudwatch put-metric-data"       "aws cloudwatch put-metric-data --namespace USMS/Probe --metric-name Probe --value 1"
probe "cloudwatch describe-alarms"       "aws cloudwatch describe-alarms"
probe "cloudwatch set-alarm-state"       "aws cloudwatch describe-alarms --max-items 1"

echo "== CloudWatch Logs =="
probe "logs describe-log-groups"         "aws logs describe-log-groups"
```

**What the command does**

`probe` runs a harmless read or a skeleton generation and reports whether the CLI got an answer.
Two of the commands are expected to fail on their *arguments* rather than on support —
`describe-services --cluster probe` names a cluster that does not exist — so read the result as
"the service answered me at all", not "the call succeeded". A completely unsupported service returns
a connection or `InvalidAction` error, which is a different failure from `ClusterNotFoundException`.

`--max-items 1` is new here. It is the AWS CLI's client-side pagination control: the CLI keeps calling
the API until it has that many items and then stops, returning a `NextToken` you can pass back as
`--starting-token`. On a real account with 4,000 alarms this is the difference between a two-second
command and a two-minute one.

**Expected result**

```text
== ECS ==
ecs list-clusters                              SUPPORTED
ecs register-task-definition                   SUPPORTED
ecs describe-services                          SUPPORTED
== Application Auto Scaling ==
describe-scalable-targets                      SUPPORTED
describe-scaling-policies                      SUPPORTED
describe-scheduled-actions                     SUPPORTED
== CloudWatch ==
cloudwatch put-metric-data                     SUPPORTED
cloudwatch describe-alarms                     SUPPORTED
cloudwatch set-alarm-state                     SUPPORTED
== CloudWatch Logs ==
logs describe-log-groups                       SUPPORTED
```

> Example output — this is the best case. Yours may differ, and that is the point of running it.

**Verify**

Work out which path you are on and write it at the top of `notes/lab-04-notes.md`, because your lab
report needs to say so:

| Path | If | What changes |
| --- | --- | --- |
| **A — full** | ECS and Application Auto Scaling both supported | Do every step as written |
| **B — ECS only** | ECS supported, Application Auto Scaling not | Steps 1 to 11 and 23 to 25 as written. For Steps 12 to 22, write every JSON document and every command, run them, record the exact error, and answer each step's **Verify** question by reading your own document and justifying it in prose. Then use `aws ecs update-service --desired-count` to make the capacity change by hand, so you can see the effect a policy would have had |
| **C — neither** | ECS not supported | Stop and tell your instructor. Do the paper design in Exercise 4 instead, which is the part of this lab that does not need an emulator |

!!! note "Floci Limitation — Application Auto Scaling support is build-dependent"
    Some Floci builds implement the ECS API but not `application-autoscaling`, and some implement
    `register-scalable-target` but never actually evaluate a policy — the objects are stored and
    returned correctly, and nothing ever changes a desired count.

    Real AWS runs Application Auto Scaling as a continuously evaluating control loop: alarms are
    assessed every period, policies fire, and `describe-scaling-activities` accumulates a genuine
    audit trail of every capacity change with its cause.

    Take this away regardless: the **shape** of the configuration is what you are being assessed on,
    and the shape is fully observable. A policy you can read and defend is worth more than a policy
    that happened to fire once. Step 18 gives you a primary path that proves a real capacity change
    and a fallback that proves the configuration; both are acceptable evidence, provided you say which
    one you used.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01.env + lab-02.env + lab-03.env sourced
 ├── verify-lab-02.sh FAIL=0 and verify-lab-03.sh FAIL=0
 └── support path recorded: A (full) / B (ECS only) / C (neither)
```

---

### Interlude — what ECS actually is, in four objects

Four nouns, and keeping them apart makes the rest of the lab easy. Students who conflate them get
stuck at Step 12 asking why they cannot scale a task definition.

**A cluster** is a namespace. That is very nearly all it is. On Fargate it holds no servers, has no
capacity of its own, and costs nothing. It exists so that services and tasks have somewhere to be
grouped, and so that IAM policies and metrics can be scoped to a group. A cluster is not a machine.

**A task definition** is a versioned, immutable blueprint: which container images to run, how much CPU
and memory to give them, which ports they expose, which roles they assume, where their logs go. It is
registered as a **family** with **revisions** — `usms-enrolment:1`, `usms-enrolment:2` — and you can
never edit a revision, only register a new one. It is the direct analogue of an AMI in Lab 3: a
template, not a running thing.

**A task** is one running instantiation of a task definition. It has an ID, a status, an elastic
network interface with a private address from your subnet, and a lifetime. If it exits, it is gone —
nothing brings it back.

**A service** is the thing that brings it back. A service is a controller with one job: keep
`runningCount` equal to `desiredCount`. If a task dies, the service starts another. If you change
`desiredCount`, the service starts or stops tasks until reality matches.

That last sentence is the whole reason this lab exists. **Auto scaling changes `desiredCount`. It does
nothing else.** It does not start tasks, it does not talk to containers, it does not know what your
application does. It moves one integer, and the service does the rest.

```text
task definition   usms-enrolment:1        the blueprint      (immutable, versioned)
       |
       | service instantiates it N times
       v
service  usms-enrolment-svc               the controller
       |   desiredCount = 2   <---------- auto scaling writes HERE, and nowhere else
       |   runningCount = 2   <---------- the service makes this catch up
       v
tasks    a1b2c3...  d4e5f6...             the running containers
```

### Fargate, and what it does and does not remove

The other launch type is `EC2`, where you run a fleet of EC2 instances with the ECS agent on them and
ECS places tasks onto whichever instance has room. That is a real and common choice, and it means you
patch, scale and pay for those instances.

`FARGATE` removes the instances. You state CPU and memory per task, AWS finds somewhere to run it, and
you pay per task per second. What Fargate **does not** remove is everything in Lab 2: a Fargate task
in `awsvpc` mode gets its own elastic network interface, in your subnet, with your security group, and
it obeys your route tables exactly as an EC2 instance does. That is why this lab needs Lab 2 and
cannot skip it.

The valid Fargate CPU and memory combinations are constrained, not arbitrary:

| CPU | Valid memory |
| --- | --- |
| 256 (.25 vCPU) | 512, 1024, 2048 MiB |
| 512 (.5 vCPU) | 1024 to 4096 MiB, in 1024 steps |
| 1024 (1 vCPU) | 2048 to 8192 MiB, in 1024 steps |
| 2048 (2 vCPU) | 4096 to 16384 MiB, in 1024 steps |
| 4096 (4 vCPU) | 8192 to 30720 MiB, in 1024 steps |

We use `256`/`512`, the smallest, because a scaling lab wants many small tasks rather than a few large
ones. Note that the values are **strings** in the task definition JSON, not numbers. Passing `256`
unquoted is a validation error that names a type rather than the field, and it is a five-minute
mistake to find.

---

### Step 4 — Create the ECS cluster, as the developer role

**Purpose**

Create the namespace everything else in this lab lives in. We do it while holding
`usms-developer-role`, exactly as Lab 2 Step 3 did, because doing the first build action of a lab as
the least-privileged identity is the habit this course wants you to leave with.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, assume the role**

```bash
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${USMS_ROLE_DEVELOPER}"

aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "lab04-ecs-build" \
  --profile usms-dev \
  > outputs/lab-04-assumed-role.json

chmod 600 outputs/lab-04-assumed-role.json

export AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId'     outputs/lab-04-assumed-role.json)
export AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' outputs/lab-04-assumed-role.json)
export AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken'    outputs/lab-04-assumed-role.json)

aws sts get-caller-identity --no-cli-pager
```

!!! warning "These three variables now outrank your profile"
    Environment credentials sit above named profiles in the AWS CLI's resolution order. Until part 3
    unsets them, every `aws` command in this terminal runs as the assumed role whatever `--profile`
    you pass — and the role's session is one hour, so leaving them set means `ExpiredToken` errors
    around Step 15 that look nothing like their cause.

**Expected result**

```text
{
    "UserId": "AROAEXAMPLEID:lab04-ecs-build",
    "Account": "000000000000",
    "Arn": "arn:aws:sts::000000000000:assumed-role/usms-developer-role/lab04-ecs-build"
}
```

> Example output — your `UserId` will differ. The `Arn` saying `assumed-role` is the point.

**Command — part 2, create the cluster**

```bash
CLUSTER_NAME="usms-ecs-cluster"

CLUSTER_ARN=$(aws ecs create-cluster \
  --cluster-name "$CLUSTER_NAME" \
  --settings name=containerInsights,value=enabled \
  --tags key=Name,value=usms-ecs-cluster key=Project,value=USMS key=Tier,value=app \
  --query 'cluster.clusterArn' \
  --output text)

echo "CLUSTER_ARN = $CLUSTER_ARN"
```

**What the command does**

```text
aws
 └── ecs                     the SERVICE — Elastic Container Service
      └── create-cluster     the OPERATION
           ├── --cluster-name   the name; also the last part of the cluster's ARN
           ├── --settings       account-or-cluster level switches; containerInsights is the one
           │                    that matters, because it produces the CPU metric this lab scales on
           └── --tags           NOTE THE CASE
```

**Read `--tags` carefully, because ECS is inconsistent with EC2.** Every EC2 call in Labs 2 and 3
used `Key=Name,Value=x` with capitals. ECS uses `key=Name,value=x` in lower case. CloudWatch Logs uses
a plain map, `Project=USMS`. Application Auto Scaling uses a map too. There is no rule to derive; the
services were built by different teams at different times. The lesson is not to memorise four
conventions — it is to run `aws <service> <operation> help` and read the `--tags` synopsis whenever you
tag something in a service you have not tagged before.

`containerInsights` is what makes ECS publish per-service CPU and memory utilisation into the
`AWS/ECS` CloudWatch namespace. Step 14's target tracking policy consumes exactly that metric, so
turning it on is not decoration — the policy has nothing to read without it.

**Expected result**

```text
CLUSTER_ARN = arn:aws:ecs:us-east-1:000000000000:cluster/usms-ecs-cluster
```

> Example output — the account is fixed by the course, so yours should match this closely.

**Command — part 3, restore your normal identity**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
```

**Verify**

```bash
aws ecs describe-clusters \
  --clusters "$CLUSTER_NAME" \
  --include SETTINGS \
  --query 'clusters[0].{Name:clusterName,Status:status,Services:activeServicesCount,Tasks:runningTasksCount,Settings:settings}' \
  --output json
```

**What to look for:** `Status` is `ACTIVE`, `Services` and `Tasks` are both `0`, and `Settings`
contains `containerInsights` with value `enabled`. If `Settings` is empty or absent, note it as a
limitation — Step 14 will then have no CPU metric to track, and Step 16's custom metric becomes your
only working scaling signal, which is a genuinely useful thing to have discovered.

---

### Step 5 — Create the log group the tasks will write to

**Purpose**

A container's stdout goes nowhere unless you tell it where. The `awslogs` driver in Step 9's task
definition names a log group, and **the group must exist first** — ECS does not create it for you, and
a task whose log group is missing fails to start with a message about the log driver rather than about
the group. Creating it now avoids that.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
LOG_GROUP="/usms/ecs/enrolment"

aws logs create-log-group \
  --log-group-name "$LOG_GROUP" \
  --tags Project=USMS,Name=usms-enrolment-logs,Tier=app

aws logs put-retention-policy \
  --log-group-name "$LOG_GROUP" \
  --retention-in-days 7

aws logs describe-log-groups \
  --log-group-name-prefix /usms \
  --query 'logGroups[].{Name:logGroupName,Retention:retentionInDays,Bytes:storedBytes}' \
  --output table
```

**What the command does**

Log group names conventionally start with a slash and use slashes as a hierarchy —
`/usms/ecs/enrolment`, `/aws/lambda/<function>`. It is only a convention, but every tool that groups
log groups relies on it, so follow it.

`put-retention-policy` is a separate call because `create-log-group` has no retention parameter. **A
log group with no retention policy keeps its data forever and bills forever.** On real AWS this is the
most common quiet cost in an account: nobody notices ten years of debug logs. Seven days is right for
a course; production values are usually 30 to 90 for application logs and much longer for audit logs.

`--tags` here is a **map**, comma-separated `key=value` pairs with no `Key=`/`Value=` wrappers. Third
convention, third service, as promised in Step 4.

**Expected result**

```text
---------------------------------------------------------------------
|                        DescribeLogGroups                          |
+---------------------------+--------------+------------------------+
|           Name            |  Retention   |         Bytes          |
+---------------------------+--------------+------------------------+
|  /usms/ecs/enrolment      |  7           |  0                     |
+---------------------------+--------------+------------------------+
```

> Example output — `Bytes` is 0 because nothing has logged yet.

**Verify**

One row, `Retention` exactly `7`. If `Retention` is `None`, `put-retention-policy` did not take —
re-run it. A `None` here is not fatal for the lab but it is a finding for your report, because the
lesson of this step is that the retention is a separate decision that is easy to forget.

---

### Interlude — two ECS roles, and which is which

This is the single most-confused pair of objects in ECS, and getting them backwards produces errors
that point at the wrong thing. Learn the distinction here rather than at Step 9.

| | Task **execution** role | Task role |
| --- | --- | --- |
| Assumed by | The ECS agent / Fargate infrastructure, **before** your container starts | Your application code, **inside** the running container |
| Used for | Pulling the container image, writing the log stream, reading secrets named in the task definition | Whatever the application does: S3, DynamoDB, SQS |
| Trust principal | `ecs-tasks.amazonaws.com` | `ecs-tasks.amazonaws.com` — the same |
| Field in the task definition | `executionRoleArn` | `taskRoleArn` |
| Failure symptom if missing or wrong | The task **never starts**; `stoppedReason` mentions the image pull or the logs | The task starts fine and the application gets `AccessDenied` at runtime |

The trust policy is identical for both, which is exactly why they get conflated. The difference is
not who may assume them — it is *who does* and *when*.

The failure-symptom row is the practical value of the table. "My task will not start" points at the
execution role. "My task started and then my code got AccessDenied" points at the task role. Being
able to say which one from the symptom alone saves you half an hour every time.

---

### Step 6 — Create the task execution role

**Purpose**

Fargate needs an identity to pull the image and open the log stream before your code exists. This is
that identity.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, the trust policy**

```bash
cat > policies/trust-ecs-tasks.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEcsTasksToAssumeThisRole",
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

python3 -m json.tool policies/trust-ecs-tasks.json > /dev/null && echo "valid JSON"
```

!!! warning "Heredoc quoting — the rule restated because this is where it matters"
    This heredoc is `<< 'EOF'`, **quoted**, because the document must reach disk exactly as written.
    Nothing in it should be expanded by your shell. Every policy document in this course is written
    this way.

    Contrast Step 9, where the task definition **must** be written with an unquoted `<< EOF` because
    it contains `$EXEC_ROLE_ARN` and three other variables that have to become real values at write
    time.

    The rule is always the same question: *do I want this expanded now, or later?* Getting it
    backwards fails silently in one direction and loudly in the other, which is why the loud direction
    is the safer mistake.

**Command — part 2, create the role**

```bash
EXEC_ROLE_NAME="usms-ecs-exec-role"

EXEC_ROLE_ARN=$(aws iam create-role \
  --role-name "$EXEC_ROLE_NAME" \
  --assume-role-policy-document file://policies/trust-ecs-tasks.json \
  --description "ECS task execution role: pulls images and writes log streams for USMS tasks" \
  --tags Key=Name,Value=usms-ecs-exec-role Key=Project,Value=USMS Key=Tier,Value=app \
  --query 'Role.Arn' \
  --output text)

echo "EXEC_ROLE_ARN = $EXEC_ROLE_ARN"
```

**Command — part 3, the permissions it needs, written as least privilege**

```bash
cat > policies/usms-ecs-task-execution-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PullContainerImages",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "WriteTaskLogsToItsOwnGroupOnly",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:000000000000:log-group:/usms/ecs/enrolment:*"
    }
  ]
}
EOF

python3 -m json.tool policies/usms-ecs-task-execution-policy.json > /dev/null && echo "valid JSON"

EXEC_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSECSTaskExecution \
  --policy-document file://policies/usms-ecs-task-execution-policy.json \
  --description "Least-privilege ECS execution role permissions for the USMS enrolment service" \
  --query 'Policy.Arn' \
  --output text)

aws iam attach-role-policy \
  --role-name "$EXEC_ROLE_NAME" \
  --policy-arn "$EXEC_POLICY_ARN"

echo "EXEC_POLICY_ARN = $EXEC_POLICY_ARN"
```

**What the command does**

Two things in that document are worth arguing about, and you should be able to argue both.

`ecr:GetAuthorizationToken` has `"Resource": "*"` because it genuinely takes no resource — it is an
account-level call that returns a registry credential. Some actions are like this, and writing a
narrower ARN for them produces a policy that denies everything with no error message. Check the
service authorization reference before assuming an action is resource-scoped.

The `logs` statement, by contrast, is scoped to **exactly one log group**, with a trailing `:*` to
cover the log streams inside it. AWS's own managed
`AmazonECSTaskExecutionRolePolicy` uses `"Resource": "*"` for logs — which means any task using it can
write into any log group in the account, including one holding audit data. Writing it out yourself
costs four lines and is the correct choice. The `us-east-1` and `000000000000` in the ARN are hard
coded here because a quoted heredoc cannot expand variables; both values are fixed by
`configs/course.env` for the whole course, and Exercise 3 asks you to build the same document with the
variables substituted properly.

**Expected result**

```text
valid JSON
EXEC_ROLE_ARN = arn:aws:iam::000000000000:role/usms-ecs-exec-role
valid JSON
EXEC_POLICY_ARN = arn:aws:iam::000000000000:policy/USMSECSTaskExecution
```

**Verify**

```bash
aws iam get-role --role-name "$EXEC_ROLE_NAME" \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal' --output json

aws iam list-attached-role-policies --role-name "$EXEC_ROLE_NAME" \
  --query 'AttachedPolicies[].PolicyName' --output text
```

**What to look for:** the principal is `{"Service": "ecs-tasks.amazonaws.com"}` — not
`ecs.amazonaws.com`, which is a different service principal for a different purpose and is the single
most common typo in ECS. The attached policy list contains `USMSECSTaskExecution`.

---

### Step 7 — Create the task role, and reuse Lab 1's policy on it

**Purpose**

This is the container's own identity — the one the application code uses. And it is the moment the
policy Lab 1 wrote for an EC2 instance turns out to work, unchanged, for a completely different kind
of compute.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
TASK_ROLE_NAME="usms-ecs-task-role"

TASK_ROLE_ARN=$(aws iam create-role \
  --role-name "$TASK_ROLE_NAME" \
  --assume-role-policy-document file://policies/trust-ecs-tasks.json \
  --description "USMS enrolment container identity: reads and writes student transcripts in S3" \
  --tags Key=Name,Value=usms-ecs-task-role Key=Project,Value=USMS Key=Tier,Value=app \
  --query 'Role.Arn' \
  --output text)

echo "TASK_ROLE_ARN = $TASK_ROLE_ARN"

aws iam attach-role-policy \
  --role-name "$TASK_ROLE_NAME" \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${USMS_POLICY_S3_RW}"

aws iam list-attached-role-policies --role-name "$TASK_ROLE_NAME" \
  --query 'AttachedPolicies[].{Policy:PolicyName,Arn:PolicyArn}' --output table
```

**What the command does**

`$USMS_POLICY_S3_RW` comes from `configs/lab-01.env` and holds `USMSStudentDataReadWrite`. The same
trust policy file is reused from Step 6, because both ECS roles are assumed by the same service
principal — that is not laziness, it is the correct document for both.

**Expected result**

```text
TASK_ROLE_ARN = arn:aws:iam::000000000000:role/usms-ecs-task-role
--------------------------------------------------------------------------
|                       ListAttachedRolePolicies                         |
+----------------------------------------------+-------------------------+
|                     Arn                      |         Policy          |
+----------------------------------------------+-------------------------+
| arn:aws:iam::000000000000:policy/USMSStude... | USMSStudentDataReadWrite|
+----------------------------------------------+-------------------------+
```

**Verify — and read the policy, because this is the teaching moment**

```bash
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${USMS_POLICY_S3_RW}"
DEFAULT_VERSION=$(aws iam get-policy --policy-arn "$POLICY_ARN" \
  --query 'Policy.DefaultVersionId' --output text)

aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$DEFAULT_VERSION" \
  --query 'PolicyVersion.Document' --output json | tee outputs/lab-04-task-role-policy.json
```

Now compare that with what Lab 3 Step 11 printed. It is the same document. It grants `s3:GetObject`,
`s3:PutObject` and `s3:ListBucket` on `arn:aws:s3:::usms-student-data` and its objects, and denies
`s3:DeleteBucket`.

Two entirely different compute services — an EC2 instance and a Fargate task — now hold the same
permission, delivered by two different mechanisms:

```text
Lab 03   usms-web-01 ── instance profile ── usms-ec2-app-role ──┐
                                                                ├── USMSStudentDataReadWrite
Lab 04   task         ── taskRoleArn      ── usms-ecs-task-role ─┘
                                                                     |
                                                          arn:aws:s3:::usms-student-data
                                                              (does not exist yet — Lab 05)
```

Neither of them has a key on disk. Neither of them needed the policy changed. Both of them start
working at the same instant Lab 5 runs `create-bucket`. Write that into `notes/lab-04-notes.md` now —
it is Review Question 2.

!!! note "Floci Limitation — the container cannot fetch its own credentials"
    On real AWS, a Fargate task gets temporary credentials from a link-local endpoint whose address is
    injected into the container as `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`. Every AWS SDK looks for
    that variable with no configuration at all, which is the container equivalent of Lab 3's instance
    metadata service. Credentials rotate automatically.

    Floci does not serve that endpoint to task containers, so application code inside a task would not
    find credentials.

    The association you just built is nonetheless real and is what you are assessed on: the task
    definition names the role, the role trusts the ECS service principal, and the role holds the
    policy. That chain is fully observable through `describe-task-definition` and `iam get-role`.

**Checkpoint 2**

```text
usms-ecs-cluster  (ACTIVE, 0 services, 0 tasks)
 ├── /usms/ecs/enrolment           log group, 7-day retention
 ├── usms-ecs-exec-role            trusts ecs-tasks.amazonaws.com
 │    └── USMSECSTaskExecution     ecr pull + logs write to ONE group
 └── usms-ecs-task-role            trusts ecs-tasks.amazonaws.com
      └── USMSStudentDataReadWrite  <- Lab 01's policy, unchanged, reused
```

---

### Step 8 — Create the enrolment security group, sourced from the web tier's group

**Purpose**

A Fargate task in `awsvpc` mode has its own network interface and its own security group, exactly like
an EC2 instance. The enrolment API must accept calls from the student portal and from nothing else —
not from the internet, and not even from the rest of the VPC.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
ENROLMENT_SG=$(aws ec2 create-security-group \
  --group-name usms-enrolment-sg \
  --description "USMS enrolment service tasks: HTTP from the web tier security group only" \
  --vpc-id "$USMS_VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=usms-enrolment-sg},{Key=Project,Value=USMS},{Key=Tier,Value=app}]' \
  --query 'GroupId' \
  --output text)

echo "ENROLMENT_SG = $ENROLMENT_SG"

cat > policies/usms-enrolment-sg-ingress.json << EOF
[
  {
    "IpProtocol": "tcp",
    "FromPort": 80,
    "ToPort": 80,
    "UserIdGroupPairs": [
      {
        "GroupId": "$USMS_APP_SG",
        "Description": "HTTP from the USMS web tier (usms-app-sg) — the only caller of the enrolment API"
      }
    ]
  }
]
EOF

aws ec2 authorize-security-group-ingress \
  --group-id "$ENROLMENT_SG" \
  --ip-permissions file://policies/usms-enrolment-sg-ingress.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' \
  --output text
```

**What the command does**

`<< EOF`, unquoted, because `$USMS_APP_SG` must become a real group ID as the file is written. If you
see the literal text `$USMS_APP_SG` in the file, you used the wrong form and the API will reject it
with a message about an invalid group ID that says nothing about quoting.

The rule names `usms-app-sg` as the source rather than `10.0.1.0/24`, for the reasons Lab 2 Step 15
gave — and here there is a second reason that did not apply then. **The tasks have no stable
addresses.** Auto scaling will create and destroy network interfaces in two subnets throughout this
lab, so a CIDR-based rule on the *caller* side would have to be rewritten every time capacity changed.
A group reference is the only expression of this requirement that survives scaling at all.

That is worth stating plainly: group-referenced security group rules are not merely tidier in an
auto-scaling system, they are close to mandatory.

**Expected result**

```text
ENROLMENT_SG = sg-0aa11bb22cc33dd44
sgr-0777888999aaabbbc
```

> Example output — your IDs will differ.

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$ENROLMENT_SG" \
  --query 'SecurityGroups[0].{Name:GroupName,Inbound:IpPermissions[].{Port:FromPort,FromGroup:UserIdGroupPairs[0].GroupId,FromCIDR:IpRanges[0].CidrIp},OutboundRules:length(IpPermissionsEgress)}' \
  --output json
```

**What to look for:** one inbound rule on port 80 whose `FromGroup` is your `$USMS_APP_SG` and whose
`FromCIDR` is `null`. If `FromCIDR` has a value you wrote an address-based rule and the point of the
step was missed. `OutboundRules` is `1` — the allow-all-outbound rule you never wrote, and which is
about to matter a great deal in Step 10.

---

### Step 9 — Write and register the task definition

**Purpose**

The blueprint. Everything the two previous steps produced gets referenced here, and this is the
document a code reviewer would actually read to understand what the enrolment service is.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, write the document**

```bash
cat > templates/lab-04-taskdef.json << EOF
{
  "family": "usms-enrolment",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "$EXEC_ROLE_ARN",
  "taskRoleArn": "$TASK_ROLE_ARN",
  "containerDefinitions": [
    {
      "name": "enrolment-api",
      "image": "public.ecr.aws/nginx/nginx:stable-alpine",
      "essential": true,
      "portMappings": [
        { "containerPort": 80, "protocol": "tcp" }
      ],
      "environment": [
        { "name": "USMS_SERVICE",  "value": "enrolment" },
        { "name": "USMS_BUCKET",   "value": "usms-student-data" },
        { "name": "AWS_REGION",    "value": "$AWS_REGION_COURSE" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "$LOG_GROUP",
          "awslogs-region": "$AWS_REGION_COURSE",
          "awslogs-stream-prefix": "enrolment"
        }
      }
    }
  ],
  "tags": [
    { "key": "Name",    "value": "usms-enrolment" },
    { "key": "Project", "value": "USMS" },
    { "key": "Tier",    "value": "app" },
    { "key": "Lab",     "value": "04" }
  ]
}
EOF

python3 -m json.tool templates/lab-04-taskdef.json > /dev/null \
  && echo "valid JSON" || echo "INVALID JSON — fix it before registering"

grep -c '\$' templates/lab-04-taskdef.json
```

**What the command does**

Unquoted heredoc, five variables substituted. The `grep -c '\$'` at the end counts remaining dollar
signs and **must print `0`**. Any other number means a variable was empty or the heredoc was quoted,
and you are about to register a task definition that names a role ARN of `$EXEC_ROLE_ARN`.

Field by field, because most of these are decisions:

| Field | Why this value |
| --- | --- |
| `family` | The name without a revision. Registering again produces `usms-enrolment:2`, and revision 1 remains readable forever |
| `networkMode` | `awsvpc` is **required** for Fargate. It gives the task its own ENI, private address, and security group — which is what lets Step 8's rule apply to it at all |
| `requiresCompatibilities` | Declares the launch types this definition is valid for. Getting it wrong produces a validation error at registration, which is the right time |
| `cpu` / `memory` | **Strings, not numbers.** One of the valid Fargate pairs from the interlude |
| `executionRoleArn` | Step 6's role. Pulls the image, opens the log stream |
| `taskRoleArn` | Step 7's role. What the application code is |
| `image` | A public registry reference. See the note below |
| `essential` | `true` means: if this container exits, stop the whole task. With one container it is always `true`; with a sidecar, the sidecar is usually `false` |
| `logConfiguration` | `awslogs` sends stdout and stderr to the group from Step 5. `awslogs-stream-prefix` is what makes each task's stream identifiable |
| `tags` | Lower-case `key`/`value`, because this is the ECS API — the third convention from Step 4 |

!!! note "Floci Limitation — the container image is a stand-in"
    The real USMS enrolment service would be your own application, built into an image and pushed to
    a private ECR repository — which would mean uncommenting the `5100-5104` port range in
    `docker-compose.yml` and re-running `floci-up.sh`. This lab deliberately does not, because
    publishing ports you do not need makes Docker Desktop crawl and this lab is about scaling, not
    about registries.

    `public.ecr.aws/nginx/nginx:stable-alpine` is therefore a placeholder: a real, small, public image
    that a real Fargate task could genuinely pull. What it serves is irrelevant — nothing in this lab
    sends it a request.

    Depending on your Floci build, the image may be pulled and run as a Docker container, or the task
    may never leave `PROVISIONING`. Both are fine. Every proof in this lab is built on
    `desiredCount`, which is a control-plane number, so nothing here depends on a container actually
    running.

**Command — part 2, register it**

```bash
TASK_DEF_ARN=$(aws ecs register-task-definition \
  --cli-input-json file://templates/lab-04-taskdef.json \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

TASK_DEF_REVISION=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment \
  --query 'taskDefinition.revision' \
  --output text)

echo "TASK_DEF_ARN      = $TASK_DEF_ARN"
echo "TASK_DEF_REVISION = $TASK_DEF_REVISION"
```

**Expected result**

```text
valid JSON
0
TASK_DEF_ARN      = arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:1
TASK_DEF_REVISION = 1
```

> Example output — if your revision is higher than 1 you have registered before, which is harmless.

**Verify**

```bash
aws ecs describe-task-definition --task-definition usms-enrolment \
  --query 'taskDefinition.{Family:family,Revision:revision,Status:status,Network:networkMode,CPU:cpu,Memory:memory,Compat:requiresCompatibilities,Exec:executionRoleArn,Task:taskRoleArn,Container:containerDefinitions[0].name,Image:containerDefinitions[0].image,LogGroup:containerDefinitions[0].logConfiguration.options."awslogs-group"}' \
  --output json
```

**What to look for:** `Status` is `ACTIVE`, `Network` is `awsvpc`, and `Exec` and `Task` are two
**different** ARNs. If they are the same, you assigned one role to both fields — the task would start
(the execution role's permissions cover the pull) and then the application would get `AccessDenied` on
S3, which is precisely the failure the interlude's table predicts.

Note the quoting in that query: `options."awslogs-group"` needs double quotes inside the JMESPath
expression because the key contains a hyphen, which JMESPath would otherwise read as subtraction. That
is a genuinely new pattern and it appears in Appendix B.

**Checkpoint 3**

```text
usms-enrolment:1   ACTIVE
 ├── FARGATE, awsvpc, 256 CPU / 512 MiB
 ├── container enrolment-api  ->  public.ecr.aws/nginx/nginx:stable-alpine  :80
 ├── executionRoleArn  usms-ecs-exec-role
 ├── taskRoleArn       usms-ecs-task-role
 └── logs -> /usms/ecs/enrolment, stream prefix "enrolment"
```

---

### Step 10 — Create the service in Lab 2's private subnets

**Purpose**

The service is the controller that keeps `runningCount` matching `desiredCount`, and `desiredCount` is
the only thing auto scaling will ever touch. Creating it is also the moment Lab 2's NAT gateway stops
being an object and becomes load-bearing.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
SERVICE_NAME="usms-enrolment-svc"

SERVICE_ARN=$(aws ecs create-service \
  --cluster "$CLUSTER_NAME" \
  --service-name "$SERVICE_NAME" \
  --task-definition usms-enrolment \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$USMS_PRIVATE_SUBNET_A,$USMS_PRIVATE_SUBNET_B],securityGroups=[$ENROLMENT_SG],assignPublicIp=DISABLED}" \
  --enable-ecs-managed-tags \
  --propagate-tags SERVICE \
  --tags key=Name,value=usms-enrolment-svc key=Project,value=USMS key=Tier,value=app key=Lab,value=04 \
  --query 'service.serviceArn' \
  --output text)

echo "SERVICE_ARN = $SERVICE_ARN"
```

**What the command does**

`--network-configuration` is the awkward part. It is shorthand for a nested structure, and the shape
is unforgiving:

```text
awsvpcConfiguration={subnets=[<id>,<id>],securityGroups=[<id>],assignPublicIp=DISABLED}
```

No spaces anywhere. Square brackets for the lists, and **no quotes around the individual IDs** —
adding them is a parse error. If it fights you, generate the skeleton and use a document instead:

```bash
aws ecs create-service --generate-cli-skeleton > outputs/lab-04-create-service-skeleton.json
```

`assignPublicIp=DISABLED` is the correct value for a private subnet, and it is also the default. State
it explicitly anyway: this is a security-relevant setting, and a reader should not have to know the
default to know what you meant. Setting it to `ENABLED` in a private subnet gives the task a public
address it cannot use, and on real AWS bills you for it.

`--enable-ecs-managed-tags --propagate-tags SERVICE` makes ECS copy the service's tags onto every
task it launches. Without it, tasks created by auto scaling are untagged — and untagged resources that
appear and disappear on their own are exactly the ones you most want tagged, because they are the ones
nobody created by hand.

**Now the part worth stopping on.** The tasks are in `usms-private-subnet-a` and
`usms-private-subnet-b`. Those subnets have no route to `usms-igw`. The task must nonetheless reach
`public.ecr.aws` to pull its image. How?

```text
Fargate task in usms-private-subnet-a
  -> the task's ENI, security group usms-enrolment-sg (allow-all EGRESS, unwritten by you)
  -> usms-private-rt
       0.0.0.0/0  -> usms-nat        (Lab 02 Step 19 and 20)   <- the registry API and image layers
       pl-...     -> usms-s3-endpoint (Lab 02 Step 21)          <- some layer data comes from S3
  -> usms-nat, in usms-public-subnet-a, holding an Elastic IP
  -> usms-igw
  -> public.ecr.aws
```

Three Lab 2 resources are on that path, and the lab that created them could not demonstrate that any
of them mattered. This is where they matter. If Lab 2's NAT gateway did not exist, or the private route
table's default route pointed nowhere, this service would create successfully and every task would fail
to start with an image-pull timeout — a failure whose cause is four steps and one lab away from its
symptom.

That is also the practical answer to "why would anyone use a VPC endpoint": the alternative on real AWS
is paying NAT data-processing charges to pull the same image layers on every scale-out event, for the
lifetime of the service.

**Expected result**

```text
SERVICE_ARN = arn:aws:ecs:us-east-1:000000000000:service/usms-ecs-cluster/usms-enrolment-svc
```

> Example output. Look at the shape of that ARN — `service/<cluster>/<service>`. Step 12 needs
> exactly that suffix, and now you know where it comes from.

**Command — wait for it**

```bash
aws ecs wait services-stable --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  && echo "service stable" \
  || echo "waiter did not complete — check the state manually below (expected on some builds)"
```

If the waiter hangs for more than a minute, interrupt with ++ctrl+c++ and poll manually:

```bash
for i in $(seq 1 12); do
  read -r d r p <<< "$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
    --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text)"
  echo "attempt $i: desired=$d running=$r pending=$p"
  [ "$d" = "$r" ] && break
  sleep 5
done
```

`services-stable` polls until `runningCount` equals `desiredCount` and no deployment is in progress.
On real AWS that is 40 seconds or so for two small Fargate tasks. On Floci it is immediate, or never —
if `runningCount` stays at 0 while `desiredCount` is 2, that is the "no containers behind the API"
limitation and it does not block anything in this lab.

---

### Step 11 — Read the service back, and learn the four numbers

**Purpose**

Four fields on a service tell you everything about its health, and knowing which is which is how you
read a scaling event later. Learn them now, while they are all equal and boring.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws ecs describe-services \
  --cluster "$CLUSTER_NAME" \
  --services "$SERVICE_NAME" \
  --query 'services[0].{
      Name:serviceName,
      Status:status,
      Desired:desiredCount,
      Running:runningCount,
      Pending:pendingCount,
      TaskDef:taskDefinition,
      Launch:launchType,
      Subnets:networkConfiguration.awsvpcConfiguration.subnets,
      SG:networkConfiguration.awsvpcConfiguration.securityGroups,
      PublicIP:networkConfiguration.awsvpcConfiguration.assignPublicIp
    }' \
  --output json
```

**What the command does**

The four numbers, and what each one being wrong means:

| Field | Meaning | If it is not what you expect |
| --- | --- | --- |
| `desiredCount` | What you (or auto scaling) asked for | This is the **only** field auto scaling writes. If it is not moving, the policy is not firing |
| `runningCount` | How many tasks are actually up | Lower than desired for a long time means tasks are failing to start — look at `stoppedReason` on a stopped task |
| `pendingCount` | Tasks starting right now | Stuck above 0 means capacity or networking trouble; on real AWS, usually the image pull or the subnet's addresses |
| `status` | `ACTIVE`, `DRAINING` or `INACTIVE` | `INACTIVE` means the service is deleted; it stays visible for a while afterwards |

**Expected result**

```json
{
    "Name": "usms-enrolment-svc",
    "Status": "ACTIVE",
    "Desired": 2,
    "Running": 2,
    "Pending": 0,
    "TaskDef": "arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:1",
    "Launch": "FARGATE",
    "Subnets": [
        "subnet-09876fedcba543210",
        "subnet-0aabbccdd11223344"
    ],
    "SG": [
        "sg-0aa11bb22cc33dd44"
    ],
    "PublicIP": "DISABLED"
}
```

> Example output — your IDs will differ, and `Running` may be `0` on builds that do not start
> containers.

**Verify**

```bash
aws ecs list-tasks --cluster "$CLUSTER_NAME" --service-name "$SERVICE_NAME" \
  --query 'length(taskArns)' --output text

aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].events[0:3].[createdAt,message]' --output text
```

**What to look for:** `Subnets` contains **two** subnet IDs, both private, and they match
`$USMS_PRIVATE_SUBNET_A` and `$USMS_PRIVATE_SUBNET_B`. `PublicIP` is `DISABLED`. The `events` list is
the service's own narration of what it has been doing, and it is the first place to look when
`runningCount` will not rise — on real AWS the message names the reason directly.

If `length(taskArns)` is 0 while `Desired` is 2, record it as the container limitation and continue.

✏️ **Your turn**

Before any auto scaling exists, change the capacity by hand. Set the service's desired count to 3 with
`aws ecs update-service`, wait for it to settle, then set it back to 2.

```text
Expected result:
desiredCount moves to 3, then back to 2. The service's events list gains entries.
Nothing you do here involves Application Auto Scaling at all — and that is the point:
you have just done by hand exactly what a scaling policy will do for you, so you know
what to look for when it happens on its own.
```

Hint: `aws ecs update-service help` and look for `--desired-count`. The cluster and service must be
named on every ECS call; there is no default cluster in this course's configuration.

**Checkpoint 4**

```text
usms-ecs-cluster
 └── usms-enrolment-svc          ACTIVE   FARGATE
      ├── task definition        usms-enrolment:1
      ├── desired 2 / running 2 / pending 0
      ├── subnets                usms-private-subnet-a, usms-private-subnet-b
      ├── security group         usms-enrolment-sg  (in: 80 from usms-app-sg)
      ├── assignPublicIp         DISABLED
      └── image pulled via       usms-private-rt -> usms-nat -> usms-igw
```

---
### Interlude — what a scalable target actually is

Application Auto Scaling is a **separate service** from ECS. It scales ECS services, DynamoDB tables,
Aurora replicas, Lambda provisioned concurrency, SageMaker endpoints and about a dozen other things,
using one API for all of them. That generality is why its vocabulary feels indirect at first, and once
you see the shape it stops being confusing.

Three objects:

**A scalable target** is a registration that says "this specific dimension of this specific resource is
under my control, and it must stay between these two numbers." It is identified by three values
together — never one:

```text
--service-namespace     ecs                                        WHICH SERVICE'S RESOURCES
--resource-id           service/usms-ecs-cluster/usms-enrolment-svc WHICH RESOURCE
--scalable-dimension    ecs:service:DesiredCount                    WHICH NUMBER ON IT
```

All three are required on nearly every call in this API, including the read-only ones. That is not
verbosity for its own sake: `dynamodb:table:ReadCapacityUnits` and
`dynamodb:table:WriteCapacityUnits` are two different scalable targets on one table, so the dimension
genuinely is part of the identity.

**The resource ID is a string you construct, not an ARN you look up.** For ECS it is literally
`service/<cluster-name>/<service-name>`. Not the service ARN. Not the service name alone. If you pass
the ARN, most calls fail with a validation message about the format; some accept it and then silently
never match your service, which is worse. Step 13 makes you look at this deliberately.

**A scaling policy** points at a scalable target and describes *how* to move the number. You can attach
several to one target.

**A scheduled action** also points at a scalable target, and changes the min, the max, or the capacity
directly at a time you choose.

```text
Application Auto Scaling
  scalable target ....... service/usms-ecs-cluster/usms-enrolment-svc
                          ecs:service:DesiredCount     min 2   max 10
        ^         ^                 ^
        |         |                 |
   policy A   policy B      scheduled action
  (CPU target) (queue step)  (enrolment window)

ECS                    knows nothing about any of the above.
                       It just sees desiredCount change.
```

### The service-linked role

On real AWS, the first `register-scalable-target` call for a namespace creates a **service-linked
role** in your account — for ECS it is called `AWSServiceRoleForApplicationAutoScaling_ECSService`.
That role is what grants Application Auto Scaling permission to call `ecs:UpdateService` on your
behalf. You do not create it, you cannot meaningfully edit it, and it is why there is no `--role-arn`
you need to pass. (There *is* a deprecated `--role-arn` parameter; do not use it.)

That is worth knowing because it answers a question the architecture raises: if auto scaling changes
your service, under whose permissions does it do so? Not yours, and not the task role's. Its own.

!!! note "Floci Limitation — service-linked roles"
    Floci may or may not create the service-linked role, and does not enforce it either way. Check
    after Step 12 with:

    ```bash
    aws iam list-roles --path-prefix /aws-service-role/ \
      --query 'Roles[].RoleName' --output text
    ```

    Real AWS creates it on the first registration and lists it there. If yours is empty, note it; it
    changes nothing about the configuration you are building.

---

### Step 12 — Register the scalable target

**Purpose**

Hand `usms-enrolment-svc`'s desired count over to Application Auto Scaling, with a floor of 2 for
availability and a ceiling of 10 to bound the damage a runaway metric can do.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
SCALABLE_RESOURCE_ID="service/${CLUSTER_NAME}/${SERVICE_NAME}"
SCALABLE_DIMENSION="ecs:service:DesiredCount"

echo "resource id = $SCALABLE_RESOURCE_ID"

aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --min-capacity 2 \
  --max-capacity 10 \
  --tags Project=USMS,Name=usms-enrolment-scalable-target,Lab=04
```

**What the command does**

```text
aws
 └── application-autoscaling         the SERVICE — one API for many scalable resources
      └── register-scalable-target   the OPERATION — bring a dimension under control
           ├── --service-namespace   ecs
           ├── --resource-id         service/<cluster>/<service>   a CONSTRUCTED string
           ├── --scalable-dimension  ecs:service:DesiredCount
           ├── --min-capacity        the floor. NOT a suggestion — see below
           ├── --max-capacity        the ceiling
           └── --tags                a MAP (Key=Value pairs), the fourth convention in this lab
```

`--min-capacity 2` is a floor that is actively enforced, not a starting point. If the current desired
count is below it when you register, real AWS raises the capacity to the minimum immediately. If a
scale-in policy tries to go below it, the request is clipped. And if you later register the same target
again with a higher minimum, that too takes effect at once — Step 20 uses exactly that behaviour.

`register-scalable-target` is **idempotent by identity**: calling it again with the same three
identifying values updates the existing registration rather than creating a second one. There is no
`update-scalable-target`; this call is both.

If your CLI version rejects `--tags` here, drop it and tag nothing — Application Auto Scaling tagging
was added later than the rest of the API, and the target works identically without tags. Record the
version difference in your report.

**Expected result**

No output. `register-scalable-target` prints nothing on success, which is exactly why the verify below
is not optional.

```text
resource id = service/usms-ecs-cluster/usms-enrolment-svc
```

**Verify**

```bash
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --resource-ids "$SCALABLE_RESOURCE_ID" \
  --query 'ScalableTargets[].{Resource:ResourceId,Dim:ScalableDimension,Min:MinCapacity,Max:MaxCapacity,Role:RoleARN,Suspended:SuspendedState}' \
  --output json
```

**Expected result**

```json
[
    {
        "Resource": "service/usms-ecs-cluster/usms-enrolment-svc",
        "Dim": "ecs:service:DesiredCount",
        "Min": 2,
        "Max": 10,
        "Role": "arn:aws:iam::000000000000:role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService",
        "Suspended": {
            "DynamicScalingInSuspended": false,
            "DynamicScalingOutSuspended": false,
            "ScheduledScalingSuspended": false
        }
    }
]
```

> Example output — `Role` may be absent or different on Floci, and `Suspended` may be omitted entirely.

**What to look for:** exactly **one** target, with `Min` 2 and `Max` 10. If you get an empty list, the
registration did not take — the most likely cause is a resource ID that does not match. If you get
*two* targets, you registered with two different resource ID spellings, and Step 13 is about to show
you how.

---

### Step 13 — Look at what happens when the resource ID is wrong

**Purpose**

The composite resource ID is the single most common failure in this API, and the failure modes are
asymmetric: one spelling errors loudly, another registers a target that will never do anything. Seeing
both now is cheaper than debugging one later.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
echo "== correct: the constructed composite string =="
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "service/${CLUSTER_NAME}/${SERVICE_NAME}" \
  --query 'length(ScalableTargets)' --output text

echo "== wrong 1: the service ARN =="
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$SERVICE_ARN" \
  --query 'length(ScalableTargets)' --output text 2>&1 | tail -2

echo "== wrong 2: the service name alone =="
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$SERVICE_NAME" \
  --query 'length(ScalableTargets)' --output text 2>&1 | tail -2

echo "== wrong 3: right shape, cluster and service swapped =="
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "service/${SERVICE_NAME}/${CLUSTER_NAME}" \
  --query 'length(ScalableTargets)' --output text 2>&1 | tail -2
```

**What the command does**

Four reads, one correct and three wrong in different ways. `2>&1 | tail -2` captures the error text
rather than letting it scroll, because the errors are the output of this step.

**Expected result on real AWS**

```text
== correct: the constructed composite string ==
1
== wrong 1: the service ARN ==
0
== wrong 2: the service name alone ==
0
== wrong 3: right shape, cluster and service swapped ==
0
```

> Example output. The exact behaviour of each wrong form varies between the read and write calls, and
> between AWS and Floci: a `describe` with an unmatched ID returns an empty list, while a
> `register-scalable-target` with wrong form 2 or 3 may **succeed**, creating a target that points at
> nothing.

**Verify — and this is the important part**

```bash
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --query 'ScalableTargets[].ResourceId' --output text
```

**What to look for:** exactly one resource ID, and it must read
`service/usms-ecs-cluster/usms-enrolment-svc`. If more than one appears, you have created a phantom
target during Step 12 or during this step. Remove the wrong ones now, before any policy attaches to
them:

!!! danger "Read before running any delete command"
    **What will be deleted:** a scalable target registration — not the ECS service, and not any task.

    **What depends on it:** any scaling policy or scheduled action attached to that exact target. If it
    is a phantom target, nothing.

    **Reversible?** Yes. `register-scalable-target` recreates it in one call.

    **Effect on later labs:** none, provided you only remove targets whose resource ID is **not**
    `service/usms-ecs-cluster/usms-enrolment-svc`. Deleting the correct one means repeating Steps 12
    through 19.

    ```bash
    aws application-autoscaling deregister-scalable-target \
      --service-namespace ecs \
      --resource-id "<the WRONG resource id>" \
      --scalable-dimension ecs:service:DesiredCount
    ```

Write one sentence in `notes/lab-04-notes.md` naming which of the three wrong forms would be hardest to
diagnose in production, and why. It is a review question.

---

### Step 14 — Create the target tracking scaling policy

**Purpose**

The default scaling mechanism, and the one to reach for first. You name a metric and the value you want
it to hold; AWS computes the capacity that achieves it, scales out when the metric rises, scales in when
it falls, and manages the alarms itself.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, the configuration document**

```bash
cat > templates/lab-04-target-tracking.json << 'EOF'
{
  "TargetValue": 60.0,
  "PredefinedMetricSpecification": {
    "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
  },
  "ScaleOutCooldown": 60,
  "ScaleInCooldown": 300,
  "DisableScaleIn": false
}
EOF

python3 -m json.tool templates/lab-04-target-tracking.json > /dev/null && echo "valid JSON"
```

Quoted heredoc — there is nothing to expand, so nothing should be.

**Command — part 2, create the policy**

```bash
CPU_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --policy-name usms-enrolment-cpu-target \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://templates/lab-04-target-tracking.json \
  --query 'PolicyARN' \
  --output text)

echo "CPU_POLICY_ARN = $CPU_POLICY_ARN"
```

**What the command does**

Each field in that document is a decision:

**`TargetValue: 60.0`** — the average CPU utilisation across all tasks that AWS will try to hold. Why
not 80? Because a new Fargate task takes tens of seconds to start, and during those seconds the
existing tasks absorb the whole increase. At a target of 80 percent you have 20 percent of headroom to
survive the start-up window; at 60 you have 40. Lower targets cost more and break less. This number is
the single most consequential one in the lab, and Exercise 4 asks you to justify a different value.

**`PredefinedMetricType: ECSServiceAverageCPUUtilization`** — one of three predefined ECS metrics:

| Predefined metric | What it reads | Needs |
| --- | --- | --- |
| `ECSServiceAverageCPUUtilization` | `AWS/ECS` CPUUtilization for this service | Container Insights, from Step 4 |
| `ECSServiceAverageMemoryUtilization` | `AWS/ECS` MemoryUtilization | The same |
| `ALBRequestCountPerTarget` | Requests per target on an ALB target group | A load balancer, which this lab does not build |

The third is often the best signal for a web service, because requests are what actually arrive — CPU is
a *consequence* of requests, one step removed. We use CPU because there is no load balancer in the USMS
architecture yet. Note that using `ALBRequestCountPerTarget` requires a `ResourceLabel` field naming the
target group, which is another awkward composite string.

**`ScaleOutCooldown: 60` and `ScaleInCooldown: 300`** — and note that they are deliberately
**asymmetric**. After scaling out, wait 60 seconds before scaling out again: short, because being
under-provisioned during enrolment is a real failure. After scaling in, wait 300 seconds: long, because
shrinking too eagerly means you scale out again a minute later, and that oscillation — flapping — is
worse than simply running one extra task. The rule of thumb: **scale out fast, scale in slow.**

**`DisableScaleIn: false`** — set it to `true` and the policy only ever adds capacity. That sounds
absurd until you have a service where scale-in is genuinely dangerous, and you want a *different*
mechanism (a scheduled action, or a human) to bring capacity down.

**Expected result**

```text
valid JSON
CPU_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:abcd1234-...:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-cpu-target
```

> Example output — the UUID in the middle will differ. Look at the tail of that ARN: it contains the
> namespace, the resource ID and the policy name, which is why policy ARNs are so long.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'ScalingPolicies[].{Name:PolicyName,Type:PolicyType,Target:TargetTrackingScalingPolicyConfiguration.TargetValue,Metric:TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType,Out:TargetTrackingScalingPolicyConfiguration.ScaleOutCooldown,In:TargetTrackingScalingPolicyConfiguration.ScaleInCooldown,Alarms:Alarms[].AlarmName}' \
  --output json
```

**What to look for:** one policy, type `TargetTrackingScaling`, target `60.0`, and — the interesting
field — an `Alarms` list containing **two** alarm names you did not create. That is Step 15.

---

### Step 15 — Find the alarms that target tracking created for you

**Purpose**

Target tracking is not magic. It is a pair of CloudWatch alarms plus a control loop, and AWS built them
when you created the policy. Looking at them is how target tracking stops being a black box, and it is
how you would debug a policy that is not behaving.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'ScalingPolicies[?PolicyName==`usms-enrolment-cpu-target`].Alarms[].AlarmName' \
  --output text | tee outputs/lab-04-managed-alarms.txt

echo
echo "== the alarms themselves =="
for a in $(cat outputs/lab-04-managed-alarms.txt); do
  aws cloudwatch describe-alarms --alarm-names "$a" \
    --query 'MetricAlarms[0].{Name:AlarmName,Metric:MetricName,Namespace:Namespace,Stat:Statistic,Op:ComparisonOperator,Threshold:Threshold,Periods:EvaluationPeriods,Period:Period,State:StateValue}' \
    --output json
done
```

**What the command does**

The first call reads the alarm names out of the policy. The second loops over them and asks CloudWatch
what they are.

**Expected result on real AWS**

```json
{
    "Name": "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmHigh-1a2b3c4d",
    "Metric": "CPUUtilization",
    "Namespace": "AWS/ECS",
    "Stat": "Average",
    "Op": "GreaterThanThreshold",
    "Threshold": 60.0,
    "Periods": 3,
    "Period": 60,
    "State": "INSUFFICIENT_DATA"
}
{
    "Name": "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmLow-5e6f7a8b",
    "Metric": "CPUUtilization",
    "Namespace": "AWS/ECS",
    "Stat": "Average",
    "Op": "LessThanThreshold",
    "Threshold": 54.0,
    "Periods": 15,
    "State": "INSUFFICIENT_DATA"
}
```

> Example output — the suffixes are random and the exact thresholds and period counts are AWS's
> implementation detail, not a contract.

**What to look for, and there is a lot in this output:**

- **Two** alarms, `AlarmHigh` and `AlarmLow`. You created one policy and got two alarms, because
  scaling out and scaling in are different decisions with different urgency.
- `AlarmHigh` fires above your target; `AlarmLow` fires **below** it, at a lower threshold. The gap
  between the two is deliberate hysteresis — if both triggered at exactly 60, the service would
  oscillate around the boundary forever.
- The **evaluation periods differ sharply**: 3 minutes to scale out, 15 to scale in. That is the same
  "out fast, in slow" principle as the cooldowns, applied at the alarm level rather than the policy
  level. Target tracking gives you both, which is one reason to prefer it.
- `State` is `INSUFFICIENT_DATA` because no CPU metric has been published yet. That is normal for a new
  alarm and is not a failure.

**Do not edit or delete these alarms.** They are managed: AWS recreates them if you delete them, and
overwrites your changes. If you need different thresholds, change the policy's `TargetValue`, or use
step scaling and own the alarm yourself — which is Steps 16 and 17.

!!! note "Floci Limitation — managed alarms may not be created"
    Floci may accept the target tracking policy and store it faithfully while creating no alarms at
    all, in which case `Alarms` is empty and the loop above prints nothing.

    Real AWS always creates the pair, names them with the `TargetTracking-` prefix, and manages them
    for the life of the policy.

    If yours is empty, answer the step's question from the documentation instead and say so in your
    report: *what two alarms would exist, what would each one compare, and why are their evaluation
    periods different?* That reasoning is what the assessment asks for; the alarm objects are only
    evidence for it.

✏️ **Your turn**

Memory can exhaust before CPU does — a service that leaks is at 95 percent memory and 20 percent CPU,
and a CPU policy will never notice. Add a **second** target tracking policy,
`usms-enrolment-memory-target`, on `ECSServiceAverageMemoryUtilization` with a target of 70 percent,
using its own configuration document.

Then answer, in one paragraph in `notes/lab-04-notes.md`: with two target tracking policies on one
scalable target, and the CPU policy asking for 4 tasks while the memory policy asks for 6, what does
Application Auto Scaling do?

```text
Expected result:
describe-scaling-policies returns two policies on the same scalable target, and
(on real AWS) four managed alarms. Your paragraph should name the rule AWS applies
when two policies disagree — and you should be able to say why that rule is the safe
one rather than merely the documented one.
```

Hint: copy `templates/lab-04-target-tracking.json` to a second file and change two fields. The
disagreement rule is in the Application Auto Scaling target tracking documentation, in a section about
multiple policies; the phrase to look for concerns which capacity is chosen when policies conflict.

**Checkpoint 5**

```text
scalable target  service/usms-ecs-cluster/usms-enrolment-svc  ecs:service:DesiredCount
 ├── min 2  max 10
 └── policy usms-enrolment-cpu-target        TargetTrackingScaling, CPU at 60%
      ├── ScaleOutCooldown  60s
      ├── ScaleInCooldown  300s
      └── managed alarms:  AlarmHigh (>60, 3 periods)   AlarmLow (<54, 15 periods)
```

---

### Step 16 — Publish a custom metric, and alarm on it

**Purpose**

CPU is a proxy. The thing that actually predicts whether enrolment is failing is **how many enrolment
requests are waiting** — a queue depth. No AWS service knows that number; only your application does.
This step invents the metric, publishes it, and puts an alarm on it that Step 17's policy will consume.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, publish some data**

```bash
METRIC_NS="USMS/Enrolment"
METRIC_NAME="EnrolmentQueueDepth"

for v in 4 6 5 7; do
  aws cloudwatch put-metric-data \
    --namespace "$METRIC_NS" \
    --metric-name "$METRIC_NAME" \
    --dimensions ServiceName="$SERVICE_NAME" \
    --unit Count \
    --value "$v"
  echo "published $v"
  sleep 1
done
```

**What the command does**

```text
aws
 └── cloudwatch
      └── put-metric-data
           ├── --namespace   USMS/Enrolment    YOUR namespace. Must not start with "AWS/"
           ├── --metric-name EnrolmentQueueDepth
           ├── --dimensions  ServiceName=usms-enrolment-svc
           ├── --unit        Count
           └── --value       a single data point, timestamped now
```

Three things about custom metrics that are not obvious:

**The namespace is yours, and `AWS/` is reserved.** `USMS/Enrolment` groups every metric this project
publishes. Anything beginning `AWS/` is rejected.

**Dimensions are part of the metric's identity, not labels on it.** `EnrolmentQueueDepth` with
`ServiceName=usms-enrolment-svc` and `EnrolmentQueueDepth` with `ServiceName=usms-results-svc` are two
*different* metrics that happen to share a name. This catches everyone once: an alarm that specifies no
dimensions will never match data published *with* dimensions, and the alarm sits in
`INSUFFICIENT_DATA` forever while the data is plainly visible in the console. The alarm below therefore
specifies exactly the same dimension.

**Publishing costs money on real AWS** — per metric per month, plus per API call, with a free tier.
Publishing one data point per second per task per metric is how a monitoring bill becomes larger than
the compute bill it is monitoring.

**Command — part 2, read it back**

```bash
START=$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"))')
END=$(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')

echo "window: $START -> $END"

aws cloudwatch get-metric-statistics \
  --namespace "$METRIC_NS" \
  --metric-name "$METRIC_NAME" \
  --dimensions Name=ServiceName,Value="$SERVICE_NAME" \
  --start-time "$START" \
  --end-time "$END" \
  --period 60 \
  --statistics Average Maximum \
  --query 'sort_by(Datapoints, &Timestamp)[].{Time:Timestamp,Avg:Average,Max:Maximum}' \
  --output table
```

Note `python3` rather than `date` for the timestamps. `date -u -d '-15 minutes'` is GNU; the BSD `date`
on macOS needs `date -u -v-15M`. A lab script that uses either one works for half the class, so this
course uses `python3`, which behaves identically everywhere. This is the same portability problem as
`base64 -d` versus `-D` in Lab 3 Step 12.

Also note the **dimension syntax changes between calls**: `put-metric-data` takes
`--dimensions ServiceName=usms-enrolment-svc`, while `get-metric-statistics` and `put-metric-alarm`
take `--dimensions Name=ServiceName,Value=usms-enrolment-svc`. Same concept, two shapes, one service.
Read the help for each.

**Expected result**

```text
window: 2026-08-19T05:14:02Z -> 2026-08-19T05:29:02Z
------------------------------------------------------
|                GetMetricStatistics                 |
+-------+-------+------------------------------------+
|  Avg  |  Max  |               Time                 |
+-------+-------+------------------------------------+
|  5.5  |  7.0  |  2026-08-19T05:28:00Z              |
+-------+-------+------------------------------------+
```

> Example output — your timestamps and the grouping will differ. Four points published inside one
> 60-second period are aggregated into one row, which is what `--period` means.

**Command — part 3, the alarm**

```bash
ALARM_NAME="usms-enrolment-backlog-high"

aws cloudwatch put-metric-alarm \
  --alarm-name "$ALARM_NAME" \
  --alarm-description "USMS enrolment backlog above 100 waiting requests for 2 consecutive minutes" \
  --namespace "$METRIC_NS" \
  --metric-name "$METRIC_NAME" \
  --dimensions Name=ServiceName,Value="$SERVICE_NAME" \
  --statistic Average \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --tags Key=Project,Value=USMS Key=Name,Value=usms-enrolment-backlog-high

aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].{Name:AlarmName,State:StateValue,Threshold:Threshold,Op:ComparisonOperator,Periods:EvaluationPeriods,Period:Period,Missing:TreatMissingData,Actions:AlarmActions}' \
  --output json
```

**What the command does**

`--evaluation-periods 2 --period 60` means: the average over each 60-second window must exceed 100 for
two consecutive windows. That is a two-minute delay before the alarm fires, and it exists to stop a
single spike from triggering a scale-out. Shorter is twitchier; longer is slower. Two minutes for a
scale-out decision that takes another 40 seconds to have any effect is already a long time, and that
tension is exactly why Step 19's scheduled action exists.

`--treat-missing-data notBreaching` is the important one and it has four possible values:

| Value | A period with no data is treated as | Use when |
| --- | --- | --- |
| `notBreaching` | Below the threshold | The metric is only published when there is something to report — our case |
| `breaching` | Above the threshold | Missing data means the thing that publishes it has died, and that is bad |
| `ignore` | The alarm keeps its current state | You want the last known state to persist |
| `missing` | The default: `INSUFFICIENT_DATA` | You want to see gaps rather than guess |

Choosing `breaching` for a scale-out alarm on a metric your own application publishes is a way to scale
to the maximum every time your metric publisher crashes. Choosing `notBreaching` for a *liveness* alarm
is a way to never find out that something died. The choice is about what the absence of data means, and
it is worth two minutes of thought each time.

`Actions` is empty for now. Step 17 fills it.

**Expected result**

```json
{
    "Name": "usms-enrolment-backlog-high",
    "State": "OK",
    "Threshold": 100.0,
    "Op": "GreaterThanThreshold",
    "Periods": 2,
    "Period": 60,
    "Missing": "notBreaching",
    "Actions": []
}
```

> Example output — `State` may be `INSUFFICIENT_DATA` briefly before the first evaluation.

**Verify**

`State` is `OK` or `INSUFFICIENT_DATA`, and `Threshold` is `100.0`. If `State` is `ALARM` with the data
you published, check the dimension: an alarm with no dimensions matches a *different* metric and can
behave unexpectedly.

---

### Step 17 — Create the step scaling policy and wire the alarm to it

**Purpose**

Target tracking cannot express "if the backlog is 20 requests add one task, but if it is 500 add
three". Step scaling can, because you write the steps. This is where you own the alarm and the response.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, the configuration document**

```bash
cat > templates/lab-04-step-scaling.json << 'EOF'
{
  "AdjustmentType": "ChangeInCapacity",
  "MetricAggregationType": "Average",
  "Cooldown": 120,
  "StepAdjustments": [
    {
      "MetricIntervalLowerBound": 0,
      "MetricIntervalUpperBound": 100,
      "ScalingAdjustment": 1
    },
    {
      "MetricIntervalLowerBound": 100,
      "MetricIntervalUpperBound": 400,
      "ScalingAdjustment": 3
    },
    {
      "MetricIntervalLowerBound": 400,
      "ScalingAdjustment": 5
    }
  ]
}
EOF

python3 -m json.tool templates/lab-04-step-scaling.json > /dev/null && echo "valid JSON"
```

**What the command does — and read this table twice, because the bounds are the thing everyone gets
wrong**

`MetricIntervalLowerBound` and `MetricIntervalUpperBound` are **offsets from the alarm's threshold**,
not absolute metric values. The alarm threshold is 100. So:

| Step | Bounds (relative) | Actual backlog | Add |
| --- | --- | --- | --- |
| 1 | 0 to 100 | 100 to 200 | 1 task |
| 2 | 100 to 400 | 200 to 500 | 3 tasks |
| 3 | 400 and above | 500 and above | 5 tasks |

Read the third column, not the second, when you are reasoning about behaviour — and write the second,
because that is what the API takes. If you write `"MetricIntervalLowerBound": 200` intending "at 200
requests", you have actually said "at 300 requests", and the policy will look correct in every review
and behave wrongly in production. Nothing in the API will tell you.

The other fields:

**`AdjustmentType`** has three values:

| Value | `ScalingAdjustment: 3` means |
| --- | --- |
| `ChangeInCapacity` | Add 3 tasks to the current count |
| `PercentChangeInCapacity` | Add 3 percent of the current count, rounded away from zero |
| `ExactCapacity` | Set the count to exactly 3 |

`ChangeInCapacity` is almost always what you want. `PercentChangeInCapacity` has the appealing property
of scaling proportionally to your current size, and the unappealing one of adding almost nothing when
you are small — 3 percent of 2 tasks is 0.06, which rounds to 1 only because AWS rounds away from zero.
`ExactCapacity` in a step policy is unusual and mostly a sign that a scheduled action was the right
tool.

**`Cooldown: 120`** — after this policy acts, ignore it for two minutes so the new tasks can start and
affect the metric. Step scaling has one cooldown, not two: unlike target tracking, the same number
applies whichever direction you moved. That is one of several reasons target tracking is less work.

**The steps must not overlap and must not leave gaps**, or the API rejects the policy. The first step's
lower bound of 0 and the last step's absent upper bound are how you say "from the threshold" and "to
infinity".

**Command — part 2, create the policy**

```bash
STEP_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --policy-name usms-enrolment-queue-step \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --policy-type StepScaling \
  --step-scaling-policy-configuration file://templates/lab-04-step-scaling.json \
  --query 'PolicyARN' \
  --output text)

echo "STEP_POLICY_ARN = $STEP_POLICY_ARN"
```

**Command — part 3, point the alarm at the policy**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "$ALARM_NAME" \
  --alarm-description "USMS enrolment backlog above 100 waiting requests for 2 consecutive minutes" \
  --namespace "$METRIC_NS" \
  --metric-name "$METRIC_NAME" \
  --dimensions Name=ServiceName,Value="$SERVICE_NAME" \
  --statistic Average \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$STEP_POLICY_ARN"

aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].{Name:AlarmName,State:StateValue,Actions:AlarmActions}' \
  --output json
```

**What the command does**

`put-metric-alarm` is an **upsert**: calling it again with the same `--alarm-name` replaces the whole
alarm. Every parameter you do not repeat is *lost*, which is why the entire alarm definition is
repeated here with `--alarm-actions` added. Omitting `--treat-missing-data` in this second call would
have silently reset it to `missing`. There is no partial update for a CloudWatch alarm.

That is worth saying plainly, because it is a real operational hazard: an alarm edited by a script that
knows about three parameters will quietly drop the fourth that somebody added by hand last year.

**Expected result**

```json
{
    "Name": "usms-enrolment-backlog-high",
    "State": "OK",
    "Actions": [
        "arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:...:policyName/usms-enrolment-queue-step"
    ]
}
```

> Example output — the policy ARN's UUID will differ.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'ScalingPolicies[].{Name:PolicyName,Type:PolicyType,Steps:StepScalingPolicyConfiguration.StepAdjustments,Cooldown:StepScalingPolicyConfiguration.Cooldown}' \
  --output json
```

**What to look for:** two policies on the target now — one `TargetTrackingScaling` and one
`StepScaling` — and the step policy's three adjustments with the bounds you wrote. `Actions` on the
alarm is non-empty and contains the step policy's ARN. If it is empty, the alarm exists but nothing
happens when it fires, which is a configuration that looks complete and does nothing.

✏️ **Your turn**

The policy above only ever adds tasks. Write a **second** step scaling policy,
`usms-enrolment-queue-step-in`, that removes one task when the backlog is well below the threshold, and
a second alarm `usms-enrolment-backlog-low` to drive it.

```text
Expected result:
A policy whose single StepAdjustment has a negative ScalingAdjustment and an
UpperBound of 0, and a LessThanThreshold alarm wired to it. describe-scaling-policies
shows three policies on the one scalable target.

Then answer in one sentence: given that the CPU target tracking policy from Step 14
already scales in, is this second policy a good idea?
```

Hint: for a scale-in step policy the bounds run the other way — `MetricIntervalUpperBound: 0` with no
lower bound means "from the threshold downwards". The one-sentence answer is the more valuable half of
this task, and "no" is a defensible answer if you can say why.

---

### Step 18 — Prove that scaling actually changes the desired count

**Purpose**

Every command in the last six steps reported success. None of that is evidence that anything will ever
scale. This step forces the alarm into `ALARM` and then reads the service's desired count back — the
create-perturb-read-back pattern from Lab 1 Step 14, applied to a control loop instead of a resource.

This is the most important step in the lab.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, record the truth before**

```bash
aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].[desiredCount,runningCount]' --output text > outputs/lab-04-pre-scale.txt

cat outputs/lab-04-pre-scale.txt

aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'length(ScalingActivities)' --output text
```

**Command — part 2, perturb, by two different routes**

```bash
echo "== route 1: publish real breaching data =="
for i in $(seq 1 3); do
  aws cloudwatch put-metric-data \
    --namespace "$METRIC_NS" --metric-name "$METRIC_NAME" \
    --dimensions ServiceName="$SERVICE_NAME" --unit Count --value 250
  echo "published 250 (sample $i)"
  sleep 20
done

aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason}' --output json
```

```bash
echo "== route 2: force the alarm state directly =="
aws cloudwatch set-alarm-state \
  --alarm-name "$ALARM_NAME" \
  --state-value ALARM \
  --state-reason "Lab 04 Step 18: forcing the alarm to prove the step policy is wired to it"

sleep 15

aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason,Updated:StateUpdatedTimestamp}' \
  --output json
```

**What the command does**

Route 1 is honest: it publishes 250 against a threshold of 100, three times over a minute, and waits for
CloudWatch to evaluate two consecutive periods and change the alarm's state on its own.

Route 2 is the operational trick worth knowing. **`aws cloudwatch set-alarm-state` sets an alarm's state
by hand**, and everything downstream of the alarm reacts as though the metric had genuinely breached.
On real AWS this is how you test an alarm's *actions* — a scaling policy, an SNS notification, a
runbook — without waiting for or manufacturing real load. The state you force is temporary: the next
metric evaluation overwrites it. It is a test tool, not a control.

Both routes are given because either may fail on Floci for different reasons, and because the
difference between them is itself the lesson: one tests the metric *and* the alarm *and* the policy;
the other tests only the alarm's actions.

**Command — part 3, read the result back**

```bash
echo "== scaling activities: did anything actually happen? =="
aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'sort_by(ScalingActivities, &StartTime)[].{Start:StartTime,Status:StatusCode,Cause:Cause,Desc:Description}' \
  --output json | tee outputs/lab-04-scaling-activities.json

echo
echo "== the number that matters =="
aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].[desiredCount,runningCount]' --output text > outputs/lab-04-post-scale.txt

paste outputs/lab-04-pre-scale.txt outputs/lab-04-post-scale.txt

PRE=$(cut -f1 outputs/lab-04-pre-scale.txt)
POST=$(cut -f1 outputs/lab-04-post-scale.txt)

if [ "$POST" -gt "$PRE" ] 2>/dev/null; then
  echo "SCALING PROVEN: desiredCount rose from $PRE to $POST without anyone touching the service"
else
  echo "NOT OBSERVED: desiredCount is still $POST — see the fallback below"
fi
```

**Expected result on real AWS**

```text
== scaling activities: did anything actually happen? ==
[
    {
        "Start": "2026-08-19T05:41:12.334000+00:00",
        "Status": "Successful",
        "Cause": "monitor alarm usms-enrolment-backlog-high in state ALARM triggered policy usms-enrolment-queue-step",
        "Desc": "Setting desired count to 5."
    }
]

== the number that matters ==
2	2	5	5
SCALING PROVEN: desiredCount rose from 2 to 5 without anyone touching the service
```

> Example output — your timestamps will differ, and the new count depends on which step matched. A
> backlog of 250 is 150 past the threshold, which falls in step 2 (100 to 400 relative), so the
> adjustment is +3: from 2 to 5.

**Check the arithmetic yourself.** 250 published, threshold 100, so the breach is 150. Step 2 covers
100 to 400 relative and adds 3. Starting from 2 tasks, the new desired count is 5. If your output says
3, the first step matched, which means the metric CloudWatch used was not 250 — look at
`get-metric-statistics` over the last five minutes and find out what the average actually was. That
discrepancy is more instructive than the success would have been.

**Read the `Cause` field.** It names the alarm, its state, and the policy. That string is the audit
trail: on a real system, "why did we suddenly have 40 tasks at 3am" is answered entirely by
`describe-scaling-activities`, and it is the first command to run when a bill is surprising.

**Fallback — if `NOT OBSERVED`**

Do all three of these and record the results:

```bash
# 1. Did the target ever register, and is scaling suspended?
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$SCALABLE_RESOURCE_ID" \
  --query 'ScalableTargets[0].{Min:MinCapacity,Max:MaxCapacity,Suspended:SuspendedState}' --output json

# 2. Is the alarm actually pointing at the policy?
aws cloudwatch describe-alarms --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].{State:StateValue,Actions:AlarmActions}' --output json

# 3. Do the arithmetic by hand and make the change the policy would have made.
aws ecs update-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
  --desired-count 5 --query 'service.desiredCount' --output text
aws ecs update-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
  --desired-count 2 --query 'service.desiredCount' --output text
```

Then write, in `notes/lab-04-notes.md`: the metric value you published, the threshold, the breach
amount, which step adjustment that lands in, the resulting desired count, and the arithmetic. That
paragraph is worth the same marks as the successful output would have been, because it is the same
understanding — and it is what Section 12's rule about judging configuration by reading it, rather than
by whether a command succeeded, means in practice.

**Command — part 4, put it back**

```bash
aws cloudwatch set-alarm-state \
  --alarm-name "$ALARM_NAME" \
  --state-value OK \
  --state-reason "Lab 04 Step 18 complete: releasing the forced state"

aws ecs update-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
  --desired-count 2 --query 'service.desiredCount' --output text
```

Setting the desired count back to 2 by hand is safe and correct here: it is inside the min-max range,
so Application Auto Scaling has no objection, and the next policy evaluation will move it again if the
metric warrants it. This is worth noticing — **manual and automatic capacity changes coexist.** Auto
scaling does not lock the service; it simply reacts.

**Checkpoint 6**

```text
Scaling proven (or reasoned) for usms-enrolment-svc
 ├── custom metric   USMS/Enrolment / EnrolmentQueueDepth (ServiceName dimension)
 ├── alarm           usms-enrolment-backlog-high  >100 for 2x60s, notBreaching
 ├── action          -> usms-enrolment-queue-step
 ├── breach of 150   -> step 2 (100..400) -> +3 tasks
 └── desiredCount    2 -> 5 -> 2
```

---

### Step 19 — Scheduled scaling for the enrolment window

**Purpose**

Reactive scaling cannot be ready for a spike it has not seen. Enrolment opens at 08:00 on a Monday and
the university knows that. This step raises the floor before the load arrives and lowers it afterwards
— the only mechanism in this lab that is proactive rather than reactive.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws application-autoscaling put-scheduled-action \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --scheduled-action-name usms-enrolment-window-open \
  --schedule "cron(45 7 * * ? *)" \
  --timezone "Asia/Thimphu" \
  --scalable-target-action MinCapacity=6,MaxCapacity=12

aws application-autoscaling describe-scheduled-actions \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'ScheduledActions[].{Name:ScheduledActionName,Schedule:Schedule,TZ:Timezone,Min:ScalableTargetAction.MinCapacity,Max:ScalableTargetAction.MaxCapacity}' \
  --output table
```

**What the command does**

**The cron expression has six fields, not five.** AWS uses
`minute hour day-of-month month day-of-week year`, and it is not the Unix five-field format:

```text
cron(45 7 * * ? *)
      |  | | | | |
      |  | | | | +-- year:          * = every year
      |  | | | +---- day-of-week:   ? = no specific value
      |  | | +------ month:         * = every month
      |  | +-------- day-of-month:  * = every day
      |  +---------- hour:          7
      +------------- minute:        45
```

The `?` is the field that surprises people. In AWS cron, **day-of-month and day-of-week cannot both be
specified**; one of them must be `?`, meaning "no specific value". `cron(45 7 * * * *)` is rejected.
For "every weekday", you would write `cron(45 7 ? * MON-FRI *)` — note the `?` moves to day-of-month.

The other two schedule forms are `at(2026-08-24T02:00:00)` for a single occurrence and
`rate(30 minutes)` for a repeating interval.

**`--timezone "Asia/Thimphu"`** is the parameter that makes this maintainable. Without it, the schedule
is interpreted in **UTC**, and 07:45 Bhutan time is 01:45 UTC — a conversion you would have to redo by
hand for every action, and get wrong for any region that observes daylight saving. Naming the time zone
means the university's operations team reads the schedule in the time they actually work in, and AWS
handles the arithmetic. Use it every time.

**`--scalable-target-action MinCapacity=6,MaxCapacity=12`** raises the **bounds**, not the current
capacity. Because the minimum is enforced, raising it to 6 forces the desired count up to at least 6
immediately; the reactive policies then work within the new 6-to-12 range. That is the right shape for
this problem: you are not overriding the reactive policies, you are giving them a higher floor for a
few hours.

You can also set `MinCapacity` alone, or `MaxCapacity` alone. Setting a *desired capacity* directly is
not available here, and that is deliberate — a scheduled action that fought the reactive policies for
control of the exact number would flap.

**Expected result**

```text
------------------------------------------------------------------------------------
|                            DescribeScheduledActions                              |
+-----------------------------+----------------------+---------------+------+-------+
|            Name             |       Schedule       |      TZ       | Min  | Max   |
+-----------------------------+----------------------+---------------+------+-------+
| usms-enrolment-window-open  | cron(45 7 * * ? *)   | Asia/Thimphu  | 6    | 12    |
+-----------------------------+----------------------+---------------+------+-------+
```

> Example output.

**Verify**

One row, and the `TZ` column is populated. If `TZ` is `None`, your CLI or Floci build ignored
`--timezone` and the schedule is being read as UTC — which means it fires at 13:45 local, six hours
late. Record that, and note in your report what the UTC-equivalent expression would be:
`cron(45 1 * * ? *)`.

✏️ **Your turn**

An action that raises the floor and never lowers it is a bill, not a plan. Create
`usms-enrolment-window-close`, at 18:00 `Asia/Thimphu`, returning the bounds to min 2 and max 10.

```text
Expected result:
describe-scheduled-actions returns two actions on the one scalable target. Then answer
in one sentence: if the close action failed to run one evening, what would it cost, and
which of the three mechanisms in this lab would notice?
```

Hint: the same command with a different name, a different cron minute and hour, and different capacity
values. The one-sentence answer should mention which mechanism watches capacity versus which watches
load.

---

### Step 20 — Prove a scheduled action can move capacity on its own

**Purpose**

Step 18 proved the reactive path. This proves the scheduled path — and it is a different proof, because
nothing about a metric or an alarm is involved. We schedule a one-off action a few minutes out and watch
it fire.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, schedule it three minutes from now**

```bash
AT_TIME=$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%S"))')
echo "will fire at $AT_TIME UTC"

aws application-autoscaling put-scheduled-action \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --scheduled-action-name usms-enrolment-proof \
  --schedule "at($AT_TIME)" \
  --scalable-target-action MinCapacity=4,MaxCapacity=10

aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].desiredCount' --output text
```

Note there is no `--timezone` on this one. `at()` expressions are UTC unless you say otherwise, and the
timestamp came from `python3` in UTC, so they agree. Mixing a local-time `at()` with no `--timezone` is
a three-minute wait that produces nothing and a confusing six hours of debugging.

**Command — part 2, wait and watch**

```bash
for i in $(seq 1 10); do
  d=$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
        --query 'services[0].desiredCount' --output text)
  m=$(aws application-autoscaling describe-scalable-targets \
        --service-namespace ecs --resource-ids "$SCALABLE_RESOURCE_ID" \
        --query 'ScalableTargets[0].MinCapacity' --output text)
  printf 'poll %2d  min=%s  desired=%s\n' "$i" "$m" "$d"
  [ "$m" = "4" ] && break
  sleep 30
done
```

**Command — part 3, read the activity record**

```bash
aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'sort_by(ScalingActivities, &StartTime)[-3:].{Start:StartTime,Status:StatusCode,Cause:Cause,Desc:Description}' \
  --output json
```

**Expected result on real AWS**

```text
will fire at 2026-08-19T06:02:14 UTC
2
poll  1  min=2  desired=2
poll  2  min=2  desired=2
poll  3  min=2  desired=2
poll  4  min=4  desired=4
```

```json
[
    {
        "Start": "2026-08-19T06:02:19.881000+00:00",
        "Status": "Successful",
        "Cause": "scheduled action name usms-enrolment-proof was triggered",
        "Desc": "Setting min capacity to 4 and setting desired count to 4."
    }
]
```

> Example output — your timestamps will differ.

**What to look for:** `min` changes from 2 to 4, and `desired` follows it **without any policy or alarm
being involved**. The `Description` says both things it did: it raised the minimum, and then it raised
the desired count *because* the minimum is enforced. That second clause is the mechanism this lab has
been claiming since Step 12, stated by AWS itself.

`[-3:]` in that query is a JMESPath **slice** — the last three elements. Slices work like Python's:
`[0:2]`, `[:5]`, `[-1]`. This is the first slice in the course and it is in Appendix B.

**Fallback — if the minimum never changes**

Floci may store scheduled actions without ever evaluating them. In that case, prove the *mechanism* the
action relies on instead, which is the enforced minimum:

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --min-capacity 4 --max-capacity 10

sleep 10

aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  --query 'services[0].desiredCount' --output text
```

If the desired count rises to 4, you have proven the enforced-minimum behaviour that a scheduled action
uses, and only the scheduler itself is unproven. If it does not, record that too, and say in one
sentence what real AWS would have done. Either way, put it back:

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --min-capacity 2 --max-capacity 10
```

**Command — part 4, clean up the proof action**

!!! danger "Read before running any delete command"
    **What will be deleted:** the one-off scheduled action `usms-enrolment-proof`.

    **What depends on it:** nothing. It has already fired, or it never will.

    **Reversible?** Yes, trivially — it is one `put-scheduled-action` call.

    **Effect on later labs:** none. Do **not** delete `usms-enrolment-window-open` or
    `usms-enrolment-window-close`; those two are recorded in `configs/lab-04.env` and checked by the
    verification script.

```bash
aws application-autoscaling delete-scheduled-action \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --scheduled-action-name usms-enrolment-proof

aws application-autoscaling describe-scheduled-actions \
  --service-namespace ecs --resource-id "$SCALABLE_RESOURCE_ID" \
  --query 'ScheduledActions[].ScheduledActionName' --output text
```

**What to look for:** two names remain — `usms-enrolment-window-open` and
`usms-enrolment-window-close`. `usms-enrolment-proof` is gone.

---

### Step 21 — Suspend and resume scaling behaviours

**Purpose**

There are times you want the target registered and the policies intact but nothing acting: during a
deployment, during an incident, or while you investigate why the service scaled to 40 tasks overnight.
Deleting the policies to achieve that is destructive and hard to undo correctly. Suspension is the right
tool, and almost nobody knows it exists.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, suspend scale-in only**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --suspended-state '{"DynamicScalingInSuspended":true,"DynamicScalingOutSuspended":false,"ScheduledScalingSuspended":false}'

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$SCALABLE_RESOURCE_ID" \
  --query 'ScalableTargets[0].SuspendedState' --output json
```

**What the command does**

The same `register-scalable-target` call, because there is no separate update operation. Three
independent switches:

| Switch | Suspends |
| --- | --- |
| `DynamicScalingInSuspended` | Policies removing capacity |
| `DynamicScalingOutSuspended` | Policies adding capacity |
| `ScheduledScalingSuspended` | Scheduled actions, both directions |

Suspending scale-in alone is the most useful of the three and is worth remembering as a specific
operational move. During an incident you want the service to keep growing if it needs to and never
shrink while you are still working out what is happening — because a scale-in that removes the task you
were about to look at is a genuinely bad afternoon. Note that the minimum and maximum are still
enforced while scaling is suspended: suspension stops the *policies*, not the bounds.

Note the JSON is passed **inline in single quotes**, not from a file. Both work; single quotes stop the
shell touching the braces and colons.

**Expected result**

```json
{
    "DynamicScalingInSuspended": true,
    "DynamicScalingOutSuspended": false,
    "ScheduledScalingSuspended": false
}
```

**Command — part 2, resume, because this lab leaves the environment working**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$SCALABLE_RESOURCE_ID" \
  --scalable-dimension "$SCALABLE_DIMENSION" \
  --suspended-state '{"DynamicScalingInSuspended":false,"DynamicScalingOutSuspended":false,"ScheduledScalingSuspended":false}'

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$SCALABLE_RESOURCE_ID" \
  --query 'ScalableTargets[0].{Min:MinCapacity,Max:MaxCapacity,Suspended:SuspendedState}' --output json
```

**Verify**

All three switches are `false`, and the minimum and maximum are still 2 and 10. If you leave scale-in
suspended, the verification script in Section 9 fails on purpose — a suspended target is a real
configuration and the script asserts that this lab left it unsuspended.

**Checkpoint 7**

```text
scalable target  service/usms-ecs-cluster/usms-enrolment-svc
 ├── min 2  max 10   suspended: none
 ├── policy  usms-enrolment-cpu-target     TargetTrackingScaling   CPU 60%
 ├── policy  usms-enrolment-queue-step     StepScaling  <- usms-enrolment-backlog-high
 ├── action  usms-enrolment-window-open    cron(45 7 * * ? *)  Asia/Thimphu  min 6 max 12
 └── action  usms-enrolment-window-close   cron(0 18 * * ? *)  Asia/Thimphu  min 2 max 10
```

---

### Step 22 — Prove the whole scaling configuration survives a restart

**Purpose**

The same proof as Lab 2 Step 23 and Lab 3 Step 19, applied to this lab's work. The scaling
configuration is spread across three services — ECS, Application Auto Scaling and CloudWatch — and a
build that persists one and not the others would leave you with a service that quietly stops scaling.
That failure would be invisible until a Monday morning.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, record the truth**

```bash
{
  aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
    --query 'services[0].[serviceName,status,desiredCount]' --output text
  aws application-autoscaling describe-scalable-targets --service-namespace ecs \
    --query 'sort_by(ScalableTargets, &ResourceId)[].[ResourceId,MinCapacity,MaxCapacity]' --output text
  aws application-autoscaling describe-scaling-policies --service-namespace ecs \
    --query 'sort_by(ScalingPolicies, &PolicyName)[].[PolicyName,PolicyType]' --output text
  aws application-autoscaling describe-scheduled-actions --service-namespace ecs \
    --query 'sort_by(ScheduledActions, &ScheduledActionName)[].[ScheduledActionName,Schedule]' --output text
  aws cloudwatch describe-alarms --alarm-name-prefix usms- \
    --query 'sort_by(MetricAlarms, &AlarmName)[].[AlarmName,Threshold]' --output text
} > outputs/lab-04-pre-restart.txt

cat outputs/lab-04-pre-restart.txt
```

**Command — part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
```

**Command — part 3, read it back, deriving nothing from shell variables**

```bash
CLUSTER_NAME=$(aws ecs list-clusters \
  --query 'clusterArns[?contains(@, `usms-ecs-cluster`)] | [0]' --output text | awk -F/ '{print $NF}')
SERVICE_NAME=$(aws ecs list-services --cluster "$CLUSTER_NAME" \
  --query 'serviceArns[?contains(@, `usms-enrolment-svc`)] | [0]' --output text | awk -F/ '{print $NF}')
SCALABLE_RESOURCE_ID="service/${CLUSTER_NAME}/${SERVICE_NAME}"

echo "re-derived: $SCALABLE_RESOURCE_ID"

{
  aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
    --query 'services[0].[serviceName,status,desiredCount]' --output text
  aws application-autoscaling describe-scalable-targets --service-namespace ecs \
    --query 'sort_by(ScalableTargets, &ResourceId)[].[ResourceId,MinCapacity,MaxCapacity]' --output text
  aws application-autoscaling describe-scaling-policies --service-namespace ecs \
    --query 'sort_by(ScalingPolicies, &PolicyName)[].[PolicyName,PolicyType]' --output text
  aws application-autoscaling describe-scheduled-actions --service-namespace ecs \
    --query 'sort_by(ScheduledActions, &ScheduledActionName)[].[ScheduledActionName,Schedule]' --output text
  aws cloudwatch describe-alarms --alarm-name-prefix usms- \
    --query 'sort_by(MetricAlarms, &AlarmName)[].[AlarmName,Threshold]' --output text
} > outputs/lab-04-post-restart.txt

diff outputs/lab-04-pre-restart.txt outputs/lab-04-post-restart.txt \
  && echo "PERSISTENCE PROVEN: service, scalable target, both policies, both scheduled actions and every alarm unchanged" \
  || echo "PERSISTENCE FAILED: run ./scripts/utilities/floci-storage-check.sh"
```

**What the command does**

Part 3's first three lines are the whole point. The cluster name and service name are **re-derived from
the API** rather than reused from the variables, and the composite resource ID is rebuilt from them.
Reusing `$SCALABLE_RESOURCE_ID` would have proved only that Bash remembers strings — the exact mistake
that made an earlier edition of this course's persistence test worthless, described in Lab 1 Step 14.

The `contains(@, ...)` expression in that first query filters the ARN list down to the one containing
our cluster name, and `| [0]` takes the first result. `awk -F/ '{print $NF}'` takes the last slash-separated field of the ARN,
which is the bare name. There is no `describe-clusters --filters` in ECS, so filtering client-side is
the only option — and note the contrast with EC2's server-side `--filters` from Lab 2 Step 9. Not every
service offers it.

Five separate services' state is compared, not one. A build that keeps the ECS service but loses the
scaling policies would pass a naive check and fail on the morning it mattered.

**Expected result**

```text
re-derived: service/usms-ecs-cluster/usms-enrolment-svc
PERSISTENCE PROVEN: service, scalable target, both policies, both scheduled actions and every alarm unchanged
```

**What to look for:** exactly that line. If you see `PERSISTENCE FAILED`, look at the `diff` output
before doing anything else — it names *which* of the five things did not survive, and that is a much
more useful finding than a general failure. Then run `./scripts/utilities/floci-storage-check.sh`.

If only the CloudWatch alarms are missing, that is a build limitation worth recording rather than a
storage failure: some builds persist ECS and Application Auto Scaling but hold CloudWatch alarms in
memory. Say so, and note that the alarms are one `put-metric-alarm` call away from being rebuilt, which
is exactly why Step 17's command is in `templates/` and this document rather than only in your
scrollback.

**Checkpoint 8**

```text
Persistence proven for Lab 04
 ├── cluster and service re-derived from the API by name, not from a variable
 ├── scalable target: min 2 max 10 unchanged
 ├── two scaling policies unchanged
 ├── two scheduled actions unchanged
 └── alarms unchanged (or the discrepancy recorded)
```

---
### Step 23 — Close the loop back to Lab 3

**Purpose**

Step 8 wrote a security group rule whose source is a *group*, not an address. This step resolves that
group reference back to the instance that carries it — which is the only way to show that the rule
grants access to something real rather than to a group nobody uses.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
echo "== 1. What does usms-enrolment-sg admit, and from which group? =="
SOURCE_GROUP=$(aws ec2 describe-security-groups --group-ids "$ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[0].UserIdGroupPairs[0].GroupId' --output text)
echo "source group: $SOURCE_GROUP"

echo
echo "== 2. Which instances carry that group? =="
aws ec2 describe-instances \
  --filters "Name=instance.group-id,Values=$SOURCE_GROUP" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value,Id:InstanceId,Subnet:SubnetId}' \
  --output table

echo "== 3. Is that the instance Lab 03 recorded? =="
CARRIER=$(aws ec2 describe-instances \
  --filters "Name=instance.group-id,Values=$SOURCE_GROUP" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

if [ "$CARRIER" = "$USMS_WEB_INSTANCE" ]; then
  echo "LOOP CLOSED: usms-enrolment-sg admits tcp/80 from $SOURCE_GROUP, which is carried by $CARRIER (usms-web-01 from Lab 03)"
else
  echo "MISMATCH: the group is carried by $CARRIER but lab-03.env records $USMS_WEB_INSTANCE"
fi

echo
echo "== 4. Audit: everything this lab tagged Project=USMS =="
aws ecs list-tags-for-resource --resource-arn "$CLUSTER_ARN" \
  --query 'tags[].[key,value]' --output text
aws ecs list-tags-for-resource --resource-arn "$SERVICE_ARN" \
  --query 'tags[].[key,value]' --output text
```

**What the command does**

`--filters "Name=instance.group-id,Values=..."` is a new filter and a genuinely useful one: it asks EC2
for every instance carrying a given security group. It is the reverse lookup you want when you are about
to change or delete a group and need to know what would be affected.

`ecs list-tags-for-resource` takes an **ARN**, not a name — unlike almost every other ECS call in this
lab, which take `--cluster` and `--service` names. That inconsistency is why both ARNs are captured into
variables in Steps 4 and 10 and recorded in `configs/lab-04.env`.

**Expected result**

```text
== 1. What does usms-enrolment-sg admit, and from which group? ==
source group: sg-0123456789abcdef0

== 2. Which instances carry that group? ==
------------------------------------------------------------------------
|                          DescribeInstances                           |
+---------------+----------------------+-------------------------------+
|      Id       |         Name         |            Subnet             |
+---------------+----------------------+-------------------------------+
| i-0123456...  |  usms-web-01         |  subnet-01234abcd5678ef90     |
+---------------+----------------------+-------------------------------+
== 3. Is that the instance Lab 03 recorded? ==
LOOP CLOSED: usms-enrolment-sg admits tcp/80 from sg-0123456789abcdef0, which is carried by i-0123456789abcdef0 (usms-web-01 from Lab 03)

== 4. Audit: everything this lab tagged Project=USMS ==
Name	usms-ecs-cluster
Project	USMS
Tier	app
Name	usms-enrolment-svc
Project	USMS
Tier	app
Lab	04
```

> Example output — your IDs will differ.

**What to look for:** the `LOOP CLOSED` line. If you get `MISMATCH`, either Lab 3's instance was
terminated and relaunched (in which case regenerate `configs/lab-03.env`) or you did the Step 18 "Your
turn" task in Lab 3 and there are now two instances carrying `usms-app-sg`, in which case `[0]` picked
the other one and the mismatch is benign — say so.

If any ECS resource shows no tags at all, note it: some Floci builds accept `--tags` on `create-cluster`
and `create-service` and do not store them. Fix what you can with `aws ecs tag-resource --resource-arn
<arn> --tags key=Project,value=USMS` and record the rest.

---

### Step 24 — Write `configs/lab-04.env`

**Purpose**

Every shell variable in this terminal dies when you close it, and this lab created twenty things worth
naming. Later labs need eight of them. Record them by lookup, not from variables, so that a value in the
file is evidence the resource exists.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-04.env << EOF
# Lab 04 — ECS and Application Auto Scaling outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs and ARNs only. NO SECRETS. Safe to commit.

export USMS_ECS_CLUSTER=usms-ecs-cluster
export USMS_ECS_CLUSTER_ARN=$(aws ecs describe-clusters --clusters usms-ecs-cluster \
  --query 'clusters[0].clusterArn' --output text)

export USMS_ENROLMENT_SERVICE=usms-enrolment-svc
export USMS_ENROLMENT_SERVICE_ARN=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].serviceArn' --output text)

export USMS_ENROLMENT_TASK_FAMILY=usms-enrolment
export USMS_ENROLMENT_TASK_REVISION=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment --query 'taskDefinition.revision' --output text)

export USMS_ENROLMENT_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-enrolment-sg" \
  --query 'SecurityGroups[0].GroupId' --output text)

export USMS_ECS_EXEC_ROLE=usms-ecs-exec-role
export USMS_ECS_EXEC_ROLE_ARN=$(aws iam get-role --role-name usms-ecs-exec-role \
  --query 'Role.Arn' --output text)
export USMS_ECS_TASK_ROLE=usms-ecs-task-role
export USMS_ECS_TASK_ROLE_ARN=$(aws iam get-role --role-name usms-ecs-task-role \
  --query 'Role.Arn' --output text)
export USMS_POLICY_ECS_EXEC=USMSECSTaskExecution

export USMS_LOG_GROUP_ENROLMENT=/usms/ecs/enrolment

# The composite resource id. Every application-autoscaling call needs all three of these.
export USMS_SCALABLE_RESOURCE_ID=service/usms-ecs-cluster/usms-enrolment-svc
export USMS_SCALABLE_DIMENSION=ecs:service:DesiredCount
export USMS_SCALABLE_NAMESPACE=ecs
export USMS_SCALE_MIN=$(aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids service/usms-ecs-cluster/usms-enrolment-svc \
  --query 'ScalableTargets[0].MinCapacity' --output text)
export USMS_SCALE_MAX=$(aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids service/usms-ecs-cluster/usms-enrolment-svc \
  --query 'ScalableTargets[0].MaxCapacity' --output text)

export USMS_POLICY_CPU_TARGET=usms-enrolment-cpu-target
export USMS_POLICY_QUEUE_STEP=usms-enrolment-queue-step
export USMS_ALARM_BACKLOG_HIGH=usms-enrolment-backlog-high
export USMS_SCHEDULE_OPEN=usms-enrolment-window-open
export USMS_SCHEDULE_CLOSE=usms-enrolment-window-close

export USMS_METRIC_NAMESPACE=USMS/Enrolment
export USMS_METRIC_QUEUE_DEPTH=EnrolmentQueueDepth
export USMS_METRIC_DIMENSION_NAME=ServiceName
EOF

grep -n 'export .*=$\|None' configs/lab-04.env || echo "all values populated"
```

**What the command does**

Unquoted heredoc — `<< EOF`, not `<< 'EOF'` — for the same reason as Lab 2 Step 24 and Lab 3 Step 22:
every `$(...)` must run **now** and the resulting value must land on disk. Had this been quoted, the
file would contain the text of eleven API calls and `source configs/lab-04.env` would re-run all of them
in every new terminal.

Look at `USMS_SCALABLE_RESOURCE_ID`. It is written as a **literal string**, not built from the two name
variables. That is deliberate: this exact string is the identity of the scalable target, three later
commands depend on it character for character, and a file that is the single source of truth for it is
better than one that reconstructs it and might reconstruct it differently.

**Verify**

```bash
source configs/lab-04.env

printf '%-30s %s\n' \
  "cluster"       "$USMS_ECS_CLUSTER" \
  "service"       "$USMS_ENROLMENT_SERVICE" \
  "task revision" "$USMS_ENROLMENT_TASK_REVISION" \
  "resource id"   "$USMS_SCALABLE_RESOURCE_ID" \
  "min / max"     "$USMS_SCALE_MIN / $USMS_SCALE_MAX" \
  "task role"     "$USMS_ECS_TASK_ROLE_ARN" \
  "metric"        "$USMS_METRIC_NAMESPACE/$USMS_METRIC_QUEUE_DEPTH"

grep -c '^export' configs/lab-04.env
```

**What to look for:** `all values populated`, seven non-empty lines, and a count of **26** exported
variables. A `None` in `USMS_SCALE_MIN` or `USMS_SCALE_MAX` means the scalable target does not exist and
Steps 12 onward did not take — if you are on support path B from Step 3, that is expected, and you should
replace those two lines with the literal values `2` and `10` and note in your report that they are your
intended configuration rather than a read-back.

---

### Step 25 — Commit

**Purpose**

Same discipline as every lab: look first, stage explicitly, then commit.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-04-assumed-role.json
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears in `git status --short`.
- No `.env` at the repository root appears.
- `configs/lab-04.env` **does** appear. It holds names and ARNs, not secrets.
- `git check-ignore -v` names the file, the rule and the line number. Silence there means the file is
  **not** ignored — stop and fix `.gitignore` before committing anything.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-04-assumed-role.json
```

> Example output — your line number may differ.

**Command — part 2, commit**

```bash
git add labs/lab-04-ecs-autoscaling/ configs/lab-04.env \
        policies/trust-ecs-tasks.json \
        policies/usms-ecs-task-execution-policy.json \
        policies/usms-enrolment-sg-ingress.json \
        templates/lab-04-taskdef.json \
        templates/lab-04-target-tracking.json \
        templates/lab-04-step-scaling.json \
        scripts/utilities/verify-lab-04.sh \
        scripts/cleanup/lab-04-cleanup.sh

git status --short

git commit -m "Lab 04: USMS enrolment service on ECS Fargate with target tracking, step and scheduled scaling"

git log --oneline -5
```

The `git add` names paths explicitly rather than using `git add -A`. That is not fussiness: `git add -A`
stages whatever happens to be in the working tree, which is exactly how an un-ignored secret reaches a
commit.

The two script paths only exist after Section 9. If you commit before that, drop them from the
`git add` line and add them in a second commit.

**Expected result**

```text
[main a71f3c2] Lab 04: USMS enrolment service on ECS Fargate with target tracking, step and scheduled scaling
 10 files changed, 431 insertions(+)
```

> Example output — your hash and counts will differ.

**Checkpoint 9**

```text
Lab 04 recorded
 ├── configs/lab-04.env         committed, 26 exports, fully populated
 ├── policies/                  trust document + least-privilege execution policy + sg ingress
 ├── templates/                 task definition + both scaling configurations under version control
 ├── outputs/                   nothing staged, and check-ignore proves the rule
 └── git log shows Lab 01, 02, 03 and 04 commits
```

---

## 9. Verification

### 9.1 What this script checks that a naive one would not

Five of the checks below are the ones worth having, and they are the reason a "does the service exist"
script is not enough:

- **`exec role and task role are DIFFERENT`** — the failure this catches produces a task that starts
  correctly and then gets `AccessDenied` at runtime, hours later.
- **`scalable target min is 2, not 0 or 1`** — a target registered with a minimum of 1 looks fine and
  quietly abandons multi-AZ availability.
- **`no scaling behaviour is suspended`** — a suspended target has every policy intact and does nothing.
  Nothing else in the script would notice.
- **`the backlog alarm has at least one action`** — an alarm with no actions is a configuration that
  looks complete and has no effect.
- **`exactly one scalable target exists for this namespace`** — catches the phantom target from Step 13,
  which is otherwise invisible.

And, as in every lab, the environment block comes first: a script that verifies only its own resources
passes right up until the restart that deletes them.

### 9.2 Build `scripts/utilities/verify-lab-04.sh`

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-04.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 04 artefact exists and is configured correctly.
# Exit 1 if anything is missing. Read-only; safe to run at any time.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-04.env" 2>/dev/null || true

: "${USMS_APP_SG:=none}"
: "${USMS_PRIVATE_SUBNET_A:=none}"
: "${USMS_PRIVATE_SUBNET_B:=none}"
: "${USMS_WEB_INSTANCE:=none}"
: "${USMS_ECS_CLUSTER:=none}"
: "${USMS_ECS_CLUSTER_ARN:=none}"
: "${USMS_ENROLMENT_SERVICE:=none}"
: "${USMS_ENROLMENT_TASK_FAMILY:=none}"
: "${USMS_ENROLMENT_SG:=none}"
: "${USMS_ECS_EXEC_ROLE:=none}"
: "${USMS_ECS_TASK_ROLE:=none}"
: "${USMS_LOG_GROUP_ENROLMENT:=none}"
: "${USMS_SCALABLE_RESOURCE_ID:=none}"
: "${USMS_SCALABLE_DIMENSION:=ecs:service:DesiredCount}"
: "${USMS_POLICY_CPU_TARGET:=none}"
: "${USMS_POLICY_QUEUE_STEP:=none}"
: "${USMS_ALARM_BACKLOG_HIGH:=none}"
: "${USMS_SCHEDULE_OPEN:=none}"
: "${USMS_SCHEDULE_CLOSE:=none}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# svc <jmespath>  -> one field from the ECS service
svc() { aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
          --services "$USMS_ENROLMENT_SERVICE" --query "services[0].$1" --output text; }
# tgt <jmespath>  -> one field from the scalable target
tgt() { aws application-autoscaling describe-scalable-targets --service-namespace ecs \
          --resource-ids "$USMS_SCALABLE_RESOURCE_ID" --query "ScalableTargets[0].$1" --output text; }

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Lab 01 to 03 dependencies =="
check "usms-app-sg still exists"        "aws ec2 describe-security-groups --group-ids $USMS_APP_SG"
check "usms-private-subnet-a exists"    "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_A"
check "usms-private-subnet-b exists"    "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_B"
check "private rt still has NO igw route" \
  "! aws ec2 describe-route-tables --route-table-ids ${USMS_PRIVATE_RT:-none} --query 'RouteTables[0].Routes[].GatewayId' --output text | grep -q 'igw-'"
check "USMSStudentDataReadWrite policy exists" \
  "aws iam get-policy --policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/USMSStudentDataReadWrite"

echo "== Lab 04 IAM =="
check "usms-ecs-exec-role exists"       "aws iam get-role --role-name $USMS_ECS_EXEC_ROLE"
check "usms-ecs-task-role exists"       "aws iam get-role --role-name $USMS_ECS_TASK_ROLE"
check "exec role trusts ecs-tasks.amazonaws.com" \
  "aws iam get-role --role-name $USMS_ECS_EXEC_ROLE --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text | grep -q '^ecs-tasks.amazonaws.com$'"
check "task role trusts ecs-tasks.amazonaws.com" \
  "aws iam get-role --role-name $USMS_ECS_TASK_ROLE --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text | grep -q '^ecs-tasks.amazonaws.com$'"
check "exec role carries USMSECSTaskExecution" \
  "aws iam list-attached-role-policies --role-name $USMS_ECS_EXEC_ROLE --query 'AttachedPolicies[].PolicyName' --output text | grep -q USMSECSTaskExecution"
check "task role REUSES Lab 01's USMSStudentDataReadWrite" \
  "aws iam list-attached-role-policies --role-name $USMS_ECS_TASK_ROLE --query 'AttachedPolicies[].PolicyName' --output text | grep -q USMSStudentDataReadWrite"

echo "== Lab 04 logging =="
check "log group $USMS_LOG_GROUP_ENROLMENT exists" \
  "aws logs describe-log-groups --log-group-name-prefix $USMS_LOG_GROUP_ENROLMENT --query 'length(logGroups)' --output text | grep -q '^1$'"
check "log group has a retention policy set" \
  "test \"\$(aws logs describe-log-groups --log-group-name-prefix $USMS_LOG_GROUP_ENROLMENT --query 'logGroups[0].retentionInDays' --output text)\" != None"

echo "== Lab 04 ECS =="
check "cluster $USMS_ECS_CLUSTER is ACTIVE" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "task definition family $USMS_ENROLMENT_TASK_FAMILY is registered" \
  "aws ecs describe-task-definition --task-definition $USMS_ENROLMENT_TASK_FAMILY"
check "task definition uses awsvpc network mode" \
  "test \"\$(aws ecs describe-task-definition --task-definition $USMS_ENROLMENT_TASK_FAMILY --query 'taskDefinition.networkMode' --output text)\" = awsvpc"
check "task definition is FARGATE compatible" \
  "aws ecs describe-task-definition --task-definition $USMS_ENROLMENT_TASK_FAMILY --query 'taskDefinition.requiresCompatibilities' --output text | grep -q FARGATE"
check "exec role and task role are DIFFERENT" \
  "test \"\$(aws ecs describe-task-definition --task-definition $USMS_ENROLMENT_TASK_FAMILY --query 'taskDefinition.executionRoleArn' --output text)\" != \"\$(aws ecs describe-task-definition --task-definition $USMS_ENROLMENT_TASK_FAMILY --query 'taskDefinition.taskRoleArn' --output text)\""
check "service $USMS_ENROLMENT_SERVICE is ACTIVE" "test \"\$(svc status)\" = ACTIVE"
check "service launch type is FARGATE"            "test \"\$(svc launchType)\" = FARGATE"
check "service spans TWO subnets" \
  "test \"\$(aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE --query 'length(services[0].networkConfiguration.awsvpcConfiguration.subnets)' --output text)\" = 2"
check "service does NOT assign a public IP" \
  "test \"\$(svc 'networkConfiguration.awsvpcConfiguration.assignPublicIp')\" = DISABLED"
check "service carries usms-enrolment-sg" \
  "svc 'networkConfiguration.awsvpcConfiguration.securityGroups[0]' | grep -q $USMS_ENROLMENT_SG"

echo "== Lab 04 networking =="
check "usms-enrolment-sg exists"  "aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG"
check "usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)" \
  "test \"\$(aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'SecurityGroups[0].IpPermissions[0].UserIdGroupPairs[0].GroupId' --output text)\" = $USMS_APP_SG"
check "usms-enrolment-sg admits NOTHING from 0.0.0.0/0" \
  "! aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'SecurityGroups[0].IpPermissions[].IpRanges[].CidrIp' --output text | grep -q '0.0.0.0/0'"

echo "== Lab 04 auto scaling =="
check "exactly one scalable target for the ecs namespace" \
  "test \"\$(aws application-autoscaling describe-scalable-targets --service-namespace ecs --query 'length(ScalableTargets)' --output text)\" = 1"
check "scalable target resource id is the composite string" \
  "test \"\$(tgt ResourceId)\" = $USMS_SCALABLE_RESOURCE_ID"
check "scalable dimension is ecs:service:DesiredCount" \
  "test \"\$(tgt ScalableDimension)\" = ecs:service:DesiredCount"
check "minimum capacity is 2 (multi-AZ floor, not 0 or 1)" "test \"\$(tgt MinCapacity)\" = 2"
check "maximum capacity is 10 (a ceiling exists at all)"   "test \"\$(tgt MaxCapacity)\" = 10"
check "no scaling behaviour is suspended" \
  "! aws application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids $USMS_SCALABLE_RESOURCE_ID --query 'ScalableTargets[0].SuspendedState' --output text | grep -qi true"
check "target tracking policy $USMS_POLICY_CPU_TARGET exists" \
  "aws application-autoscaling describe-scaling-policies --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query 'ScalingPolicies[].PolicyName' --output text | grep -q $USMS_POLICY_CPU_TARGET"
check "that policy is of type TargetTrackingScaling" \
  "aws application-autoscaling describe-scaling-policies --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query \"ScalingPolicies[?PolicyName=='$USMS_POLICY_CPU_TARGET'].PolicyType\" --output text | grep -q TargetTrackingScaling"
check "step scaling policy $USMS_POLICY_QUEUE_STEP exists" \
  "aws application-autoscaling describe-scaling-policies --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query 'ScalingPolicies[].PolicyName' --output text | grep -q $USMS_POLICY_QUEUE_STEP"
check "step policy has three step adjustments" \
  "test \"\$(aws application-autoscaling describe-scaling-policies --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query \"length(ScalingPolicies[?PolicyName=='$USMS_POLICY_QUEUE_STEP'].StepScalingPolicyConfiguration.StepAdjustments[])\" --output text)\" = 3"
check "scheduled action $USMS_SCHEDULE_OPEN exists" \
  "aws application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query 'ScheduledActions[].ScheduledActionName' --output text | grep -q $USMS_SCHEDULE_OPEN"
check "scheduled action $USMS_SCHEDULE_CLOSE exists" \
  "aws application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id $USMS_SCALABLE_RESOURCE_ID --query 'ScheduledActions[].ScheduledActionName' --output text | grep -q $USMS_SCHEDULE_CLOSE"

echo "== Lab 04 CloudWatch =="
check "alarm $USMS_ALARM_BACKLOG_HIGH exists" \
  "aws cloudwatch describe-alarms --alarm-names $USMS_ALARM_BACKLOG_HIGH --query 'length(MetricAlarms)' --output text | grep -q '^1$'"
check "that alarm has at least one action wired to it" \
  "test \"\$(aws cloudwatch describe-alarms --alarm-names $USMS_ALARM_BACKLOG_HIGH --query 'length(MetricAlarms[0].AlarmActions)' --output text)\" -ge 1"
check "that alarm treats missing data as notBreaching" \
  "test \"\$(aws cloudwatch describe-alarms --alarm-names $USMS_ALARM_BACKLOG_HIGH --query 'MetricAlarms[0].TreatMissingData' --output text)\" = notBreaching"

echo "== Files and Git hygiene =="
check "configs/lab-04.env exists"        "test -f configs/lab-04.env"
check "configs/lab-04.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=$|=None$' configs/lab-04.env"
check "task definition document is valid JSON" \
  "python3 -m json.tool templates/lab-04-taskdef.json"
check "target tracking document is valid JSON" \
  "python3 -m json.tool templates/lab-04-target-tracking.json"
check "step scaling document is valid JSON" \
  "python3 -m json.tool templates/lab-04-step-scaling.json"
check "trust policy is valid JSON" \
  "python3 -m json.tool policies/trust-ecs-tasks.json"
check "execution policy is valid JSON" \
  "python3 -m json.tool policies/usms-ecs-task-execution-policy.json"
check "no task definition document contains an unexpanded variable" \
  "! grep -q '[$]' templates/lab-04-taskdef.json"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-04.sh
bash -n scripts/utilities/verify-lab-04.sh && echo "syntax OK"
./scripts/utilities/verify-lab-04.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Lab 01 to 03 dependencies ==
  ok   usms-app-sg still exists
  ...
== Lab 04 auto scaling ==
  ok   exactly one scalable target for the ecs namespace
  ok   scalable target resource id is the composite string
  ok   minimum capacity is 2 (multi-AZ floor, not 0 or 1)
  ...
== Files and Git hygiene ==
  ok   configs/lab-04.env exists
  ok   no secret is tracked by git

PASS=54  FAIL=0
```

> Example output — the middle is abbreviated; you will see all 54.

**The expected count is `PASS=54  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| Anything in `== Lab 04 auto scaling ==` | Support path B from Step 3 — Application Auto Scaling absent. All 12 checks in that block fail. Note the path in your report and state the expected count as `PASS=42  FAIL=12` (or `PASS=41  FAIL=13` if the alarm's action check fails too, because there is no policy ARN to wire to it) |
| `that alarm has at least one action` | Some builds do not store `AlarmActions`. Confirm with `describe-alarms --output json` and say so |
| `log group has a retention policy set` | Some builds ignore `put-retention-policy`. Confirm and record |
| `service spans TWO subnets` | Lab 2 Exercise 5 was skipped, so `usms-private-subnet-b` does not exist. This one is **not** benign — go and do it |

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** the ECS service, the cluster, every task definition revision in the
    `usms-enrolment` family, the scalable target, both scaling policies, both scheduled actions, the
    backlog alarm, the enrolment security group, both ECS roles, the `USMSECSTaskExecution` policy and
    the log group.

    **What depends on it:** Lab 5 uses `usms-ecs-task-role` to show that the bucket it creates resolves
    two permission chains at once. The CloudWatch lab builds a dashboard from the `USMS/Enrolment`
    metric namespace this lab established. The CloudFormation lab re-declares this service as a
    template and compares it with what you built by hand.

    **Reversible?** No. You would repeat this laboratory from Step 4.

    **Effect on later labs:** total. Run this only at the end of the course, and run it **before**
    `lab-02-cleanup.sh`, because a VPC with a security group in use cannot be deleted.

    It requires you to type `DELETE USMS ECS` in full before it does anything.

**Run from**

```text
aws-floci-course/
```

````bash
cat > scripts/cleanup/lab-04-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 04, dependencies first.
# Order: scaling config -> alarm -> service (scaled to 0) -> task definitions ->
#        cluster -> security group -> IAM -> log group.
# Run this BEFORE scripts/cleanup/lab-02-cleanup.sh.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04.env"

cat <<'WARN'
============================================================
  This deletes the USMS enrolment service, its ECS cluster,
  its scaling configuration, its alarm, its security group,
  both ECS IAM roles and its log group.

  Lab 05, the CloudWatch lab and the CloudFormation lab all
  depend on parts of it. None of this is reversible.
  Run this BEFORE lab-02-cleanup.sh.
============================================================
WARN

read -r -p 'Type exactly: DELETE USMS ECS  > ' answer
[ "$answer" = "DELETE USMS ECS" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }
NS=ecs
RID="$USMS_SCALABLE_RESOURCE_ID"
DIM="$USMS_SCALABLE_DIMENSION"

say "scheduled actions"
for a in "${USMS_SCHEDULE_OPEN:-}" "${USMS_SCHEDULE_CLOSE:-}"; do
  [ -n "$a" ] || continue
  aws application-autoscaling delete-scheduled-action \
    --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" \
    --scheduled-action-name "$a" || true
done

say "scaling policies"
for p in "${USMS_POLICY_CPU_TARGET:-}" "${USMS_POLICY_QUEUE_STEP:-}"; do
  [ -n "$p" ] || continue
  aws application-autoscaling delete-scaling-policy \
    --policy-name "$p" --service-namespace "$NS" \
    --resource-id "$RID" --scalable-dimension "$DIM" || true
done

say "scalable target"
aws application-autoscaling deregister-scalable-target \
  --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" || true

say "cloudwatch alarm"
[ -n "${USMS_ALARM_BACKLOG_HIGH:-}" ] && \
  aws cloudwatch delete-alarms --alarm-names "$USMS_ALARM_BACKLOG_HIGH" || true

say "service: scale to zero first, then delete"
aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --desired-count 0 >/dev/null || true
aws ecs wait services-stable --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" || sleep 20
aws ecs delete-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --force >/dev/null || true

say "task definition revisions"
for arn in $(aws ecs list-task-definitions --family-prefix "$USMS_ENROLMENT_TASK_FAMILY" \
               --query 'taskDefinitionArns[]' --output text); do
  aws ecs deregister-task-definition --task-definition "$arn" >/dev/null || true
done

say "cluster"
aws ecs delete-cluster --cluster "$USMS_ECS_CLUSTER" >/dev/null || true

say "security group (nothing may still reference it)"
[ -n "${USMS_ENROLMENT_SG:-}" ] && \
  aws ec2 delete-security-group --group-id "$USMS_ENROLMENT_SG" || true

say "IAM: detach before delete"
aws iam detach-role-policy --role-name "$USMS_ECS_EXEC_ROLE" \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${USMS_POLICY_ECS_EXEC}" || true
aws iam detach-role-policy --role-name "$USMS_ECS_TASK_ROLE" \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/USMSStudentDataReadWrite" || true
aws iam delete-role --role-name "$USMS_ECS_EXEC_ROLE" || true
aws iam delete-role --role-name "$USMS_ECS_TASK_ROLE" || true
aws iam delete-policy \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${USMS_POLICY_ECS_EXEC}" || true

say "log group"
[ -n "${USMS_LOG_GROUP_ENROLMENT:-}" ] && \
  aws logs delete-log-group --log-group-name "$USMS_LOG_GROUP_ENROLMENT" || true

echo; echo "Lab 04 teardown complete. lab-03-cleanup.sh and lab-02-cleanup.sh may now run, in that order."
EOF

chmod +x scripts/cleanup/lab-04-cleanup.sh
bash -n scripts/cleanup/lab-04-cleanup.sh && echo "syntax OK — do NOT run it"
````

**What to look for:** the words `syntax OK — do NOT run it`. `bash -n` parses the script without
executing a single command, which is the only safe way to check a destructive one.

The order is the lesson, and it is different from Labs 2 and 3 because the dependencies are different:

1. **Scheduled actions and policies before the target.** Deregistering a scalable target with policies
   attached deletes them silently, which is convenient and means you never see what was there.
2. **The target before the service.** A scalable target pointing at a deleted service is an orphan that
   is easy to leave behind and impossible to explain later.
3. **`--desired-count 0` before `delete-service`.** ECS refuses to delete a service with running tasks
   unless you pass `--force`, and `--force` kills tasks without draining them. Scaling to zero and
   waiting is the graceful version, and it is what you would do in production.
4. **Task definitions before the cluster.** Deregistering leaves them in `INACTIVE` state; they are
   never truly deleted, and that is by design so that a service referencing an old revision can still
   be described.
5. **IAM detach before delete.** `delete-role` fails with `DeleteConflict` while a policy is attached,
   and the error does not name the policy.
6. **The security group after the service.** A group in use by a task's network interface cannot be
   deleted, and `DependencyViolation` does not say which interface is holding it.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, four env files sourced, `verify-lab-02.sh` and `verify-lab-03.sh` both `FAIL=0`, and your support path (A, B or C) recorded |
| 2 | Step 7 | `usms-ecs-cluster` ACTIVE; `/usms/ecs/enrolment` with 7-day retention; `usms-ecs-exec-role` with `USMSECSTaskExecution`; `usms-ecs-task-role` with Lab 1's `USMSStudentDataReadWrite` |
| 3 | Step 9 | `usms-enrolment:1` ACTIVE, `awsvpc`, FARGATE, 256/512, and two **different** role ARNs in `executionRoleArn` and `taskRoleArn` |
| 4 | Step 11 | Service ACTIVE, desired 2, spanning both private subnets, `assignPublicIp` DISABLED, carrying `usms-enrolment-sg` |
| 5 | Step 15 | Scalable target min 2 max 10; `usms-enrolment-cpu-target` at 60 percent CPU; two managed alarms found, or their absence recorded with the reasoning written out |
| 6 | Step 18 | `desiredCount` observed rising from 2 without anyone touching the service — or the step arithmetic written out in prose with the breach amount, the matched step and the resulting count |
| 7 | Step 21 | Two policies and two scheduled actions on one target, and all three suspension switches back to `false` |
| 8 | Step 22 | Service, target, both policies, both actions and every alarm identical after a Floci stop/start, with the resource ID **re-derived from the API** |
| 9 | Step 25 | `configs/lab-04.env` populated with 26 exports and committed; nothing under `outputs/` staged; `git check-ignore -v` names the rule |

---
## 11. Troubleshooting

??? danger "`ClusterNotFoundException` on a call that names a cluster you can see"
    ECS has no default cluster in this course's configuration, and the name is case-sensitive. Confirm
    what actually exists:

    ```bash
    aws ecs list-clusters --query 'clusterArns[]' --output text
    ```

    If the cluster is there, the usual cause is that `$CLUSTER_NAME` is empty in this terminal. Source
    the env file:

    ```bash
    source configs/lab-04.env
    echo "$USMS_ECS_CLUSTER"
    ```

??? danger "`InvalidParameterException: Task definition does not support launch type FARGATE`"
    `requiresCompatibilities` in `templates/lab-04-taskdef.json` does not list `FARGATE`, or
    `networkMode` is not `awsvpc`. Both are required together, and Fargate rejects `bridge` and `host`.

    ```bash
    aws ecs describe-task-definition --task-definition usms-enrolment \
      --query 'taskDefinition.{Net:networkMode,Compat:requiresCompatibilities}' --output json
    ```

    Fix the document and register again. You cannot edit revision 1 — you register revision 2, then
    update the service to use it with
    `aws ecs update-service --cluster ... --service ... --task-definition usms-enrolment:2`.

??? danger "`ClientException: Invalid 'cpu' setting for task`"
    `cpu` and `memory` must be one of the valid Fargate pairs from the interlude before Step 4, and
    both must be **strings** in the JSON. `"cpu": 256` with no quotes, or `"cpu": "256"` with
    `"memory": "768"`, are both rejected. 256 CPU allows only 512, 1024 or 2048 MiB.

??? danger "The service is created but `runningCount` stays at 0"
    On real AWS this is nearly always the image pull or the network path. Look at what the service
    itself says, which is the first thing to check and the thing most people skip:

    ```bash
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].events[0:5].[createdAt,message]' --output text

    aws ecs describe-tasks --cluster "$USMS_ECS_CLUSTER" \
      --tasks $(aws ecs list-tasks --cluster "$USMS_ECS_CLUSTER" --desired-status STOPPED \
                  --query 'taskArns[0]' --output text) \
      --query 'tasks[0].{Stopped:stoppedReason,Containers:containers[].reason}' --output json
    ```

    `stoppedReason` naming the image or the registry means the execution role or the route to the
    internet. `stoppedReason` naming the log driver means the log group from Step 5 does not exist.

    On Floci, `runningCount` of 0 is expected on builds that do not start containers, and nothing in
    this lab depends on it. Record it and continue.

??? danger "`ValidationException: Unsupported service namespace, resource type or scalable dimension`"
    One of the three identifying values is wrong. All three must be supplied on nearly every
    `application-autoscaling` call, and they must match exactly:

    ```text
    --service-namespace   ecs
    --resource-id         service/<cluster>/<service>
    --scalable-dimension  ecs:service:DesiredCount
    ```

    The dimension is case-sensitive and the colons matter. `ecs:service:desiredCount` is rejected.

??? danger "`describe-scalable-targets` returns an empty list right after a successful registration"
    The resource ID you registered and the one you are reading differ. Look at every target with no
    filter at all:

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --query 'ScalableTargets[].ResourceId' --output text
    ```

    Compare what comes back with `service/usms-ecs-cluster/usms-enrolment-svc`, character by character.
    Step 13 covers the three wrong forms. A trailing space from a copied variable is a fourth.

??? danger "The alarm goes to ALARM but the desired count never changes"
    Four things, in this order:

    ```bash
    # 1. Is the alarm's action actually the policy?
    aws cloudwatch describe-alarms --alarm-names "$USMS_ALARM_BACKLOG_HIGH" \
      --query 'MetricAlarms[0].AlarmActions' --output json

    # 2. Is dynamic scale-out suspended?
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --resource-ids "$USMS_SCALABLE_RESOURCE_ID" \
      --query 'ScalableTargets[0].SuspendedState' --output json

    # 3. Is the desired count already at the maximum?
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].desiredCount' --output text

    # 4. Did anything get recorded at all?
    aws application-autoscaling describe-scaling-activities --service-namespace ecs \
      --resource-id "$USMS_SCALABLE_RESOURCE_ID" --query 'ScalingActivities[0]' --output json
    ```

    A cooldown is the fifth possibility: if the policy acted less than `Cooldown` seconds ago it will
    decline to act again, and `describe-scaling-activities` says so in `StatusMessage`.

??? danger "An alarm sits in `INSUFFICIENT_DATA` forever while your data is clearly being published"
    The dimensions do not match. A metric published **with** `ServiceName=usms-enrolment-svc` and an
    alarm defined **without** dimensions are looking at two different metrics. Compare them:

    ```bash
    aws cloudwatch list-metrics --namespace USMS/Enrolment \
      --query 'Metrics[].{Name:MetricName,Dims:Dimensions}' --output json

    aws cloudwatch describe-alarms --alarm-names "$USMS_ALARM_BACKLOG_HIGH" \
      --query 'MetricAlarms[0].Dimensions' --output json
    ```

    The two `Dims` structures must be identical, including order-independent equality of every name and
    value.

??? danger "A scheduled action never fires"
    Three causes, in order of likelihood:

    1. **The time zone.** With no `--timezone`, a `cron()` schedule is UTC. 07:45 in `Asia/Thimphu` is
       01:45 UTC, so an action written as `cron(45 7 ...)` with no time zone fires six hours late.
    2. **The cron field count.** AWS cron has **six** fields and day-of-month and day-of-week cannot
       both be specified — one must be `?`.
    3. **`ScheduledScalingSuspended`** is `true` on the target.

    ```bash
    aws application-autoscaling describe-scheduled-actions --service-namespace ecs \
      --resource-id "$USMS_SCALABLE_RESOURCE_ID" \
      --query 'ScheduledActions[].{Name:ScheduledActionName,Schedule:Schedule,TZ:Timezone}' --output json
    ```

??? danger "`ResourceInUseException` when deleting the service or the cluster"
    A service with running tasks cannot be deleted without `--force`, and a cluster with an active
    service cannot be deleted at all. The graceful order is in `scripts/cleanup/lab-04-cleanup.sh`:
    scale to zero, wait for stable, delete the service, then the cluster.

??? danger "`DeleteConflict` when deleting one of the ECS roles"
    A role with an attached managed policy cannot be deleted, and the error does not name the policy.
    List and detach first:

    ```bash
    aws iam list-attached-role-policies --role-name usms-ecs-task-role \
      --query 'AttachedPolicies[].PolicyArn' --output text
    ```

??? danger "`date: illegal option -- d` in Step 16 or 20"
    You are on macOS with BSD `date`. This lab deliberately uses `python3` for every timestamp for
    exactly that reason — if you substituted a `date` command of your own, put the `python3` form back:

    ```bash
    python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
    ```

??? danger "`Could not connect to the endpoint URL` / exit code 255"
    Floci is not running, or not listening on 4566.

    ```bash
    docker compose ps
    ./scripts/setup/floci-up.sh
    curl -s http://localhost:4566/_localstack/health | head -c 300
    ```

    The health output also tells you which services this build has started, which is a faster second
    opinion on Step 3's probe than re-running the probe.

??? danger "Everything is gone after a restart"
    Storage mode, as always. `./scripts/utilities/floci-storage-check.sh`. If it reports
    `FLOCI_STORAGE_MODE=memory`, a stray `floci start` replaced the Compose container. The work is not
    recoverable — restore from the snapshot you took at the end of Practical 1, and this time confirm
    the storage check before building.

---

## 12. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `ecs create-cluster`, `describe-clusters` | Full | Cluster object stored and returned | Implemented in Floci |
| `register-task-definition`, families and revisions | Full | Full, including immutable revisions | Implemented in Floci |
| `create-service`, `describe-services`, the four counts | Full | `desiredCount` modelled correctly | Implemented in Floci |
| `update-service --desired-count` | Real tasks start and stop | The number changes | Implemented in Floci |
| ECS tags, `list-tags-for-resource` | Full | Build-dependent | Floci Limitation |
| **Fargate actually running a container** | Yes, a real task on real hardware | Some builds run a Docker container; many leave the task in `PROVISIONING` | Floci Limitation |
| Container Insights CPU and memory metrics | Published to `AWS/ECS` every minute | Usually not published at all | Floci Limitation |
| `application-autoscaling register-scalable-target` | Full | Build-dependent — see Step 3 | Floci Limitation |
| Target tracking control loop | Continuous evaluation, capacity computed for you | Policy stored; usually not evaluated | Floci Limitation |
| Managed `AlarmHigh` / `AlarmLow` alarms | Created and maintained by AWS | Usually not created | Floci Limitation |
| Step scaling driven by an alarm action | Full | Build-dependent | Floci Limitation |
| Scheduled actions, `cron()` / `at()` / `rate()` | Evaluated by a real scheduler | Stored; often never evaluated | Floci Limitation |
| `--timezone` on a scheduled action | Full, including daylight saving | Often ignored | Floci Limitation |
| `describe-scaling-activities` audit trail | Every capacity change with its cause | Empty unless scaling ran | Floci Limitation |
| `cloudwatch put-metric-data`, custom namespaces | Full | Generally implemented | Implemented in Floci |
| `cloudwatch put-metric-alarm`, state evaluation | Evaluated every period | Stored; evaluation build-dependent | Floci Limitation |
| `cloudwatch set-alarm-state` | Forces state, triggers actions, then reverts | Sets the field; may trigger nothing | Floci Limitation |
| CloudWatch Logs groups and retention | Full | Groups yes, retention build-dependent | Floci Limitation |
| Task credentials via `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` | Yes, rotated automatically | Not served to containers | Floci Limitation |
| Security group enforcement on task traffic | Every packet | Not enforced | Floci Limitation |
| Service-linked role creation on first registration | Automatic | Build-dependent, never enforced | Floci Limitation |
| Fargate task start latency | 20 to 60 seconds, and it shapes every cooldown you choose | Instant or never | Floci Limitation |
| Cost — per vCPU-second and GB-second, per metric, per alarm | Real | Free | Conceptual / Real AWS |
| Service quotas (tasks per service, alarms per account) | Enforced | Not enforced | Conceptual / Real AWS |
| Capacity providers, Fargate Spot, capacity provider strategies | Full | Not available | Conceptual / Real AWS |
| ALB target groups and `ALBRequestCountPerTarget` | Full | Requires ELBv2, not built in this course yet | Conceptual / Real AWS |
| Predictive scaling (EC2 Auto Scaling only) | Machine-learned forecasts | Not available, and not applicable to ECS | Conceptual / Real AWS |

### 12.1 What you actually observed in this lab

```text
OBSERVABLE — you saw this happen
  a cluster, a task definition family with an immutable revision, and a service
  a service placed in two private subnets with a security group and no public IP
  two ECS roles with the same trust policy and different attached permissions
  Lab 01's USMSStudentDataReadWrite attached to a second, different kind of compute
  a group-referenced security group rule, and its reverse lookup to usms-web-01
  a scalable target with a composite resource ID, a floor and a ceiling
  three wrong spellings of that resource ID, and how each one fails (Step 13)
  a target tracking policy stored with its cooldowns and target value
  a custom metric published and read back with get-metric-statistics
  an alarm with an explicit treat-missing-data choice and a wired action
  a step scaling policy with three adjustments and threshold-relative bounds
  suspension switches toggled and read back
  all of it surviving a container restart (Step 22)

CONCEPTUAL — you reasoned about it, you may not have seen it
  a container actually running, serving, or logging
  CPU utilisation existing as a number at all
  the control loop deciding a capacity and acting on it
  the two managed alarms target tracking maintains
  a scheduled action firing on a clock
  the 20-to-60-second task start latency that every cooldown in this lab is sized around
  the cost of any of it
```

If your build put you on support path A, several lines move from the second list to the first —
including the most important one, Step 18's desired count changing on its own. Say in your report which
list each item ended up in for you. Being precise about that is worth marks; claiming to have observed
something you reasoned about is worth negative marks.

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **Tasks start instantly, or not at all.** A real Fargate task takes 20 to 60 seconds from
  `desiredCount` changing to serving traffic. Every cooldown and evaluation period in this lab is sized
  around that latency, and a system tuned on an emulator where capacity appears instantly will be tuned
  wrongly.
- **No cost.** Two `256`/`512` Fargate tasks running continuously are roughly USD 15 per month at
  us-east-1 list prices; ten of them are roughly USD 75. A custom metric is a few cents per month and an
  alarm a few more — cheap individually, and the reason a mature account has a monitoring bill. Check
  current numbers on the AWS pricing pages before quoting any of this; Exercise 4 requires you to cite a
  source.
- **No quotas.** Real accounts have limits on tasks per service, services per cluster, and alarms per
  account, and a scaling policy that hits one fails in a way that looks like the policy is broken.
- **No throttling.** `put-metric-data` has a request rate limit. A metric publisher inside every task,
  publishing every second, hits it — and the symptom is missing data points, which your
  `treat-missing-data` choice then interprets for you.
- **Scaling appears instant when it appears at all.** On real AWS, `describe-scaling-activities` shows a
  gap of seconds to minutes between the alarm and the capacity change, and then more before the metric
  responds. That total delay is the thing a scaling design actually has to accommodate.

### 12.3 ECS Service Auto Scaling is not EC2 Auto Scaling

These are two different services with similar names, and conflating them is the most common confusion in
this area. Lab 3 Step 20 built `usms-web-golden` for the *other* one.

| | **Application Auto Scaling** (this lab) | **EC2 Auto Scaling** |
| --- | --- | --- |
| Scales | ECS services, DynamoDB, Aurora, Lambda concurrency, and more | EC2 instances, and nothing else |
| The unit | A task, or a capacity unit | An instance |
| Configuration object | A scalable target plus policies | An Auto Scaling group plus policies |
| Needs a launch template or AMI | No — a task definition | Yes |
| CLI command family | `aws application-autoscaling` | `aws autoscaling` |
| Health checks and instance replacement | Handled by the ECS service | Handled by the Auto Scaling group |
| Predictive scaling | Not available | Available |
| The ECS `EC2` launch type | Scales the **tasks** | Scales the **instances the tasks land on** |

The last row is the one worth remembering, because on ECS with the `EC2` launch type you need **both**:
Application Auto Scaling to add tasks, and EC2 Auto Scaling (or a capacity provider) to add the
instances for them to run on. Fargate removes the second problem entirely, which is a large part of why
this lab uses it.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-04-ecs-autoscaling/exercises.md`. Take screenshots into
`screenshots/` where an exercise asks for evidence.

### Exercise 1 — Basic: a second service, scaled

**Requirements**

The USMS results service publishes exam results. It has the same shape as the enrolment service but a
lower floor. Create `usms-results-svc` in `usms-ecs-cluster` from the existing `usms-enrolment` task
definition family, with a desired count of 1, in both private subnets, carrying `usms-enrolment-sg`.
Then register a scalable target for it with a minimum of 1 and a maximum of 4, and attach a target
tracking policy `usms-results-cpu-target` holding CPU at 70 percent.

**Constraints**

- Every ID captured with `$(...)` and `--query`. Nothing copied by hand.
- Tag the service `Project=USMS`, `Tier=app`, `Lab=04`, `Service=results`.
- The scalable target's resource ID must be constructed, not copied and edited — show the line that
  builds it.
- Do **not** record it in `configs/lab-04.env`. Exercise 4 removes it.

**Expected outcome**

`describe-scalable-targets --service-namespace ecs` returns **two** targets, with different resource
IDs, different minima and different maxima. `describe-scaling-policies` for the new resource ID returns
one policy at 70 percent.

**Hints**

Steps 10, 12 and 14 between them contain every command. The only interesting question is which values
change and which must not — and note that the verification script from Section 9 asserts that exactly
one target exists, so it will fail while this exercise's target is present. Say so in your write-up
rather than editing the script to hide it.

---

### Exercise 2 — Intermediate: scale on a metric nobody publishes yet

**Requirements**

Enrolment failures matter more than enrolment volume: a rising failure rate means the service is
struggling in a way CPU will not show. Build the whole chain for a new metric:

1. Publish `USMS/Enrolment` / `EnrolmentFailureRate` with dimension
   `ServiceName=usms-enrolment-svc`, unit `Percent`, at several values across a five-minute window.
2. Read it back with `get-metric-statistics` using both `Average` and `Maximum`, and explain in one
   sentence why the two differ and which one an alarm should use here.
3. Create alarm `usms-enrolment-failures-high`: above 5 percent, for 3 consecutive 60-second periods,
   with a `treat-missing-data` value you can justify in one sentence.
4. Create a step scaling policy `usms-enrolment-failure-step` with **two** adjustments, and wire the
   alarm to it.
5. Force the alarm with `set-alarm-state` and capture `describe-scaling-activities`.

**Constraints**

- The `treat-missing-data` justification must say what the *absence* of the metric would mean for this
  particular metric — and it is not the same answer as for queue depth. Argue it.
- Your two step adjustments must not overlap and must not leave a gap. State, for each, the actual
  failure-rate range it covers, not the relative bounds.
- If `set-alarm-state` produces no scaling activity, do the arithmetic in prose instead and say which
  step would have matched.

**Expected outcome**

A complete chain from `put-metric-data` to a recorded scaling activity, or to a written derivation of
one, plus two paragraphs of justification that a colleague could disagree with substantively.

**Hints**

Steps 16, 17 and 18 are the template. The genuinely new thinking is in points 2 and the
`treat-missing-data` justification: a failure *rate* that stops being published means something quite
different from a queue depth that stops being published, and the right answer follows from which.

---

### Exercise 3 — Problem solving: a scaling posture report

**Requirements**

Write `scripts/utilities/lab-04-scaling-report.sh`. For every scalable target in the `ecs` namespace, it
prints one line:

```text
usms-enrolment-svc   min=2  max=10  desired=2  running=2  policies=2  sched=2  ELASTIC
usms-results-svc     min=1  max=4   desired=1  running=1  policies=1  sched=0  ELASTIC
usms-batch-svc       min=3  max=3   desired=3  running=3  policies=0  sched=0  FIXED
usms-legacy-svc      min=2  max=8   desired=8  running=8  policies=2  sched=0  AT-CEILING
usms-frozen-svc      min=2  max=10  desired=4  running=4  policies=2  sched=1  SUSPENDED
```

The verdict must be **computed**, never taken from a name or a tag:

| Verdict | When |
| --- | --- |
| `FIXED` | Minimum equals maximum, or there are no policies and no scheduled actions |
| `SUSPENDED` | Any of the three suspension switches is true |
| `AT-CEILING` | Desired count equals the maximum |
| `ELASTIC` | None of the above |

**Constraints**

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as the Section 9
  script does.
- No hard-coded resource ID, cluster name or service name anywhere. Derive the cluster and service from
  each target's resource ID — which means splitting the composite string, and that is the point of the
  exercise.
- Must not crash when a field is absent. A target with no policies must print `policies=0`, not an
  error.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- Also write the same data as JSON to `outputs/lab-04-scaling-posture.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-04-ecs-autoscaling/`,
correctly classifying every target including the one Exercise 1 created. `AT-CEILING` must be
reachable — demonstrate it by temporarily setting a desired count to the maximum, and put it back.

**Hints**

`cut -d/ -f2` and `-f3` split the resource ID. The awkward part is not the shell, it is deciding the
precedence of the verdicts: a target that is both suspended and at its ceiling gets one label, and you
must choose which, and say why in a comment. `AT-CEILING` deserves to be loud, because a service pinned
at its maximum is a service that has stopped protecting you.

---

### Exercise 4 — Challenge: the enrolment week capacity plan

**Requirements**

The USMS project lead writes:

> Enrolment opens Monday 08:00 and the first twenty minutes are 90 percent of the week's traffic. Last
> year the service fell over for eleven minutes at 08:03 and the Registrar noticed. Finance has also
> noticed that we run the same capacity at 3am on a Sunday in July.
>
> Tell me what capacity we should run, when, and what it costs. I want to know specifically: why the
> reactive scaling we already have did not save us last year, what you would change, and what happens if
> your new plan is wrong in each direction. Also tell me what to switch off.

Produce a written analysis in `labs/lab-04-ecs-autoscaling/exercises.md` covering:

- **Why reactive scaling failed at 08:03.** Add up the actual delay: metric publication interval, alarm
  evaluation periods, the scaling activity, and Fargate task start latency. Give a number in seconds and
  show the arithmetic. This is the core of the exercise.
- **A revised plan** with concrete numbers for the minimum, the maximum, the target value, both
  cooldowns, and the schedule — and for each number, one sentence saying what it costs you if it is too
  high and what it costs you if it is too low.
- **A monthly cost comparison** of at least three options: fixed at peak capacity, your scheduled plan,
  and reactive-only. Use current Fargate per-vCPU-hour and per-GB-hour prices, and **cite where you got
  them**. Include the CloudWatch cost of your custom metrics and alarms, which most people forget.
- **The failure modes of your own plan**, in both directions: what happens if the scheduled action fires
  and the load does not arrive, and what happens if the load arrives and the action did not fire. Say
  which of the two you would rather have and why.
- **What to switch off**, with the exact commands in the correct dependency order, each preceded by the
  four-line danger admonition used throughout this lab: the Exercise 1 results service and its scalable
  target, and any policy or alarm from the "Your turn" tasks that you decided was a bad idea.

Then execute only the deletions, and confirm `./scripts/utilities/verify-lab-04.sh` reports `FAIL=0`
afterwards.

**Constraints**

- Do not delete anything in Section 16's KEEP column.
- Every number must have a source or a derivation. "About 10 tasks" earns nothing; "10 tasks, because
  200 requests per second at 25 requests per task per second plus one task of headroom" earns full marks.
- The delay arithmetic must be a total in seconds, broken down by component.

**Expected outcome**

An analysis a project lead could act on and a finance team could check, plus a repository in which the
practice resources are gone and the verification still passes.

**Hints**

The delay arithmetic is where the marks are, and the answer is uncomfortably large: a 60-second metric
period, two evaluation periods, some seconds for the policy to act, and 20 to 60 seconds of task start
time. Add it up before you write a word of the plan, because the number is the argument for scheduled
scaling and you will not make that argument convincingly without it.

---

### Exercise 5 — Integration: the metric publisher the next labs consume

**Requirements**

Right now `EnrolmentQueueDepth` is a number you typed. The SNS/SQS lab will replace it with a real queue
depth, and the CloudWatch lab will build a dashboard from it. Both need a publisher that exists as a
committed, reusable script rather than as a `for` loop in your scrollback.

1. Write `scripts/utilities/usms-publish-queue-depth.sh`, taking one argument — the depth — and
   publishing it to `USMS/Enrolment` / `EnrolmentQueueDepth` with the `ServiceName` dimension read from
   `configs/lab-04.env`. It must validate its argument, work from any directory, and contain no
   credentials of any kind.
2. Use it to drive a **full cycle**: publish values that breach the alarm, capture the scale-out,
   publish values well below it, and capture the scale-in. Save the whole activity history to
   `outputs/lab-04-scaling-history.json`.
3. Confirm the Lab 3 hand-off is still intact: resolve `usms-enrolment-sg`'s source group to the
   instance carrying it, exactly as Step 23 does, and record the result in
   `outputs/lab-04-lab03-linkage.txt`. State in one sentence what would break in this lab if Lab 3's
   web server were terminated and relaunched.
4. Prepare the Lab 5 hand-off. Write `outputs/lab-04-s3-readiness.txt` containing: the task role name
   and ARN, the attached policy name, the exact bucket ARN named in that policy, the equivalent chain
   for Lab 3's EC2 instance, and the result of `aws s3api head-bucket --bucket usms-student-data` —
   which will fail, and whose failure is the point. Capture the exit code, do not hide it.
5. Add `USMS_BUCKET_NAME` to `configs/lab-04.env` if `configs/lab-01.env` does not already carry it, so
   that Lab 5 can source the intended name rather than retyping it.

**Constraints**

- `usms-publish-queue-depth.sh` must exit non-zero with a usable message if its argument is missing or
  not a non-negative integer.
- It must not contain, read or reference an access key. If it does, the exercise is failed regardless of
  whether it works.
- The `head-bucket` failure must be captured with its exit code, not suppressed. `|| true` and then
  recording `$?` is the pattern; a bare failure under `set -e` aborts the script.
- The scale-in half of point 2 is the harder half. If your build never scales in, record the arithmetic
  and the alarm states you observed, and say what real AWS would have done and how long it would have
  taken.

**Expected outcome**

A committed publisher script the next two labs can call unchanged, a full scaling history as evidence,
and a readiness file from which a Lab 5 reader could predict — before running a single command — exactly
what changes for **both** compute services the moment the bucket exists.

**This is what Lab 5 will use.** Lab 5 creates `usms-student-data` and re-runs your `head-bucket` check;
the difference between the two results, and the fact that it resolves two independent permission chains
at once, is the whole lesson of that step.

**Hints**

Step 23 does point 3 for one instance. Lab 3 Step 11 traced the EC2 half of point 4 and Step 7 of this
lab traced the ECS half — the readiness file is those two traces side by side, which is why it is worth
writing down. For the publisher script, the header pattern that makes it directory-independent is at the
top of the Section 9 verification script.

---

## 14. Lab Assessment Checklist

Tick these off before you submit. Every one is checkable from your own repository.

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` appears in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-04-notes.md`

**Resources**

- [ ] `usms-ecs-cluster` is `ACTIVE`
- [ ] `/usms/ecs/enrolment` exists with a retention policy set
- [ ] `usms-ecs-exec-role` and `usms-ecs-task-role` both exist and both trust `ecs-tasks.amazonaws.com`
- [ ] `usms-ecs-task-role` carries Lab 1's `USMSStudentDataReadWrite`, not a new copy of it
- [ ] `usms-enrolment:1` is registered, `awsvpc`, FARGATE, with **two different** role ARNs
- [ ] `usms-enrolment-svc` is `ACTIVE`, spans two private subnets, `assignPublicIp` `DISABLED`
- [ ] `usms-enrolment-sg` admits tcp/80 from `usms-app-sg` by group reference and nothing from
      `0.0.0.0/0`
- [ ] Exactly one scalable target, resource ID `service/usms-ecs-cluster/usms-enrolment-svc`, min 2
      max 10, nothing suspended
- [ ] `usms-enrolment-cpu-target` and `usms-enrolment-queue-step` both exist, of the right two types
- [ ] `usms-enrolment-backlog-high` exists with at least one action and `notBreaching`
- [ ] `usms-enrolment-window-open` and `usms-enrolment-window-close` both exist with a time zone

**Evidence**

- [ ] Step 18's `SCALING PROVEN` line, **or** the written step arithmetic if it was not observable
- [ ] Step 20's scheduled-action activity record, **or** the enforced-minimum fallback with its result
- [ ] Step 22's `PERSISTENCE PROVEN` line
- [ ] Step 23's `LOOP CLOSED` line
- [ ] `outputs/lab-04-scaling-activities.json` present
- [ ] Screenshots in `screenshots/` for Checkpoints 5, 6 and 8

**Hygiene and written work**

- [ ] `configs/lab-04.env` exists, is committed, has 26 exports and no empty values or `None`
- [ ] `scripts/utilities/verify-lab-04.sh` exists and reports `FAIL=0` (or its documented benign
      failures, each explained)
- [ ] `scripts/cleanup/lab-04-cleanup.sh` exists, passes `bash -n`, and has not been run
- [ ] `git status --short` shows nothing under `outputs/`
- [ ] `git check-ignore -v outputs/lab-04-assumed-role.json` names the rule and line
- [ ] `notes/lab-04-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-04-ecs-autoscaling/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding — answer these out loud before you submit**

- [ ] I can say what auto scaling actually changes, in one short sentence, without using the word
      "scale"
- [ ] I can explain why the resource ID is a constructed string and not an ARN
- [ ] I can say why my step adjustment bounds are relative to 100 and not to 0
- [ ] I can explain why reactive scaling alone cannot solve the 08:00 problem

---

## 15. Review Questions

Answer in prose, in your own words, in `notes/lab-04-notes.md`. No command output — these ask whether
you understood, not whether you typed.

1. A colleague says "I put auto scaling on the task definition". Explain, in three or four sentences,
   every way that sentence is wrong: name what auto scaling is actually attached to, what it actually
   modifies, and which of ECS's four objects does the work of making reality match. Then say what
   observable consequence follows from the fact that ECS knows nothing about the scalable target.

2. Lab 1 wrote `USMSStudentDataReadWrite` for a bucket that did not exist. Lab 3 attached it to an EC2
   instance via an instance profile. This lab attached the same policy, unchanged, to a Fargate task via
   a task role. Explain in a full paragraph what each of the two delivery mechanisms actually does at
   runtime, why neither needs a key on disk, and precisely what changes for **both** at the moment
   Lab 5 runs `create-bucket`. This is the most important connection in the course; answer it properly.

3. Target tracking and step scaling are routinely confused. Give a requirement that target tracking
   expresses well and step scaling expresses badly, and a requirement where it is the other way round.
   Then explain why target tracking creates *two* alarms with sharply different evaluation periods, and
   what would go wrong with one alarm at a single threshold.

4. Your step policy's first adjustment has `MetricIntervalLowerBound: 0` and the alarm threshold is 100.
   A colleague reads the policy document alone, with the alarm in another file, and concludes it fires
   at a backlog of zero. Explain why they are wrong, why the API was designed this way rather than using
   absolute values, and describe one review practice that would catch this class of misreading.

5. Add up the total delay between enrolment traffic arriving and a new task serving requests, given a
   60-second metric period, an alarm with 2 evaluation periods, and Fargate task start latency of
   roughly 40 seconds. Then explain why that number, and not any opinion about elegance, is the argument
   for the scheduled action in Step 19. Finish by naming one thing that could reduce the delay and one
   thing that cannot.

6. `treat-missing-data` has four values. For the queue depth metric in Step 16 and for a hypothetical
   "is the service alive" heartbeat metric, choose a value for each and justify both — they should not be
   the same. Then describe the specific failure that the *wrong* choice would cause for each, and say
   which of the two failures you would notice sooner.

7. Step 22 re-derived the cluster name, the service name and the composite resource ID from the API
   rather than reusing the shell variables. State precisely what would **not** have been proven had the
   variables been reused, connect it to the persistence bug described in Lab 1 Step 14, and then name
   one thing Step 22 still does not prove even as written.

---

## 16. What We Built

### 16.1 Reflection

Three labs built things of a fixed size. This one built something whose size is a consequence of
demand — and the interesting part is how little of the work was about containers.

The idea to keep is the indirection. Auto scaling does not manage your service; it writes one integer
and the service reacts. Everything that seemed awkward about the API follows from that one design
choice: the scalable target exists because the integer needs an owner, the composite resource ID exists
because one API scales a dozen unrelated services, the three suspension switches exist because
sometimes you want the owner to stop writing. Once the indirection is clear, `application-autoscaling`
stops being a wall of vocabulary and becomes three objects with obvious jobs.

The second idea is that the three mechanisms are not alternatives ranked by sophistication. They answer
different questions. Target tracking answers "hold this steady", step scaling answers "respond
proportionally to how bad it is", and scheduled scaling answers "be ready before it happens" — and only
the third can win a race against a spike, because the other two must observe before they act. Exercise 4
makes you add the observation delay up, and the number is bigger than anyone expects.

The third is a discipline this course keeps returning to. Every command in Steps 12 to 21 reported
success, and none of that was evidence of anything. Step 18 proved a capacity change, Step 20 proved a
different one by a different route, and Step 22 proved the whole configuration survives a restart. Where
your build could not prove it, the lab asked you to write the arithmetic out instead — which is the same
understanding, honestly labelled. **A command that appears to succeed is still not evidence that it did
what you meant.**

And one connection worth naming out loud. Lab 2 built a NAT gateway and could not demonstrate that it
mattered. This lab put tasks in a private subnet and needed it — three Lab 2 resources sit on the path
between a Fargate task and the container registry, and had any of them been wrong, the failure would
have surfaced here, two labs and a fortnight away from its cause.

### 16.2 KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ══════════════════════════╗    ╔════════════ CLEAN UP ═══════════════╗
║ usms-ecs-cluster            the namespace              ║    ║ outputs/lab-04-assumed-role.json    ║
║ usms-enrolment (family)     the blueprint              ║    ║   — expired after 1 hour;           ║
║ usms-enrolment-svc          Lab 05 and CloudWatch      ║    ║   delete it, it is dead weight      ║
║ usms-enrolment-sg           references usms-app-sg     ║    ║                                     ║
║ usms-ecs-exec-role          + USMSECSTaskExecution     ║    ║ usms-results-svc + its target        ║
║ usms-ecs-task-role          Lab 05 resolves its policy ║    ║   — Exercise 1 practice;            ║
║ /usms/ecs/enrolment         the log group              ║    ║   remove it in Exercise 4           ║
║ the scalable target         min 2 max 10               ║    ║                                     ║
║ usms-enrolment-cpu-target   target tracking            ║    ║ usms-enrolment-proof                ║
║ usms-enrolment-queue-step   step scaling               ║    ║   — one-off action; Step 20 part 4  ║
║ usms-enrolment-backlog-high the alarm                  ║    ║   already deleted it                ║
║ usms-enrolment-window-open  / -close                   ║    ║                                     ║
║ USMS/Enrolment namespace    CloudWatch lab needs it    ║    ║ outputs/lab-04-pre/post-restart.txt ║
║ configs/lab-04.env          Lab 05 sources it          ║    ║ outputs/lab-04-pre/post-scale.txt   ║
║ templates/lab-04-*.json     the reviewable artefacts   ║    ║   — evidence; keep until submitted, ║
║ scripts/utilities/verify-lab-04.sh                     ║    ║   then remove                       ║
║ everything from Labs 01, 02 and 03                     ║    ║                                     ║
║                                                        ║    ║ AWS_ACCESS_KEY_ID and friends       ║
║                                                        ║    ║   — unset them; Step 4 part 3 did   ║
╚════════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted:

```bash
rm -f outputs/lab-04-assumed-role.json
rm -f outputs/lab-04-pre-restart.txt outputs/lab-04-post-restart.txt
rm -f outputs/lab-04-pre-scale.txt outputs/lab-04-post-scale.txt
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
git status --short
```

Do **not** run `scripts/cleanup/lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are
for the end of the course, and in that order.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and in Lab 04 Step 4
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 06
  USMSStudentDataReadWrite ............. now on TWO roles, naming a bucket that still does not exist

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b   -> usms-public-rt  -> usms-igw
    private : usms-private-subnet-a / -b  -> usms-private-rt -> usms-nat
                                                             -> usms-s3-endpoint
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-private-nacl

Lab 03  COMPUTE — fixed size
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> the EC2 Auto Scaling lab, which is NOT this lab (see 12.3)

Lab 04  COMPUTE — elastic                              <-- you are here
  usms-ecs-cluster
    usms-enrolment-svc   2..10 tasks, both private subnets, usms-enrolment-sg
      usms-enrolment:1   exec role + task role
    Application Auto Scaling
      target tracking (CPU 60%)  ·  step scaling (queue depth)  ·  schedule (07:45 / 18:00)
    CloudWatch
      USMS/Enrolment / EnrolmentQueueDepth  ·  usms-enrolment-backlog-high

Lab 05  STORAGE (next)
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for BOTH roles at once
```

---

## 17. Preparation for the Next Lab

Lab 5 is S3, and it is the lab where a policy written in Lab 1 finally resolves — for two entirely
different compute services simultaneously.

| From `configs/lab-04.env` | Lab 5 uses it for |
| --- | --- |
| `USMS_ECS_TASK_ROLE` / `_ARN` | The second principal in the bucket policy, alongside Lab 3's EC2 role |
| `USMS_ENROLMENT_SERVICE` | Showing that the container's access appears without the service being touched |
| `USMS_METRIC_NAMESPACE` | The CloudWatch lab's dashboard, later in the course |

| From earlier labs | Lab 5 uses it for |
| --- | --- |
| Lab 1 `USMSStudentDataReadWrite` | Lab 5 Step 3 creates the bucket at the ARN this policy names |
| Lab 1 `usms-ec2-app-role` | The first principal in the bucket policy |
| Lab 2 `usms-s3-endpoint` | Explaining why both a private instance and a private task reach S3 without a NAT hop |
| Lab 3 `usms-web-01` | Uploading a transcript using the instance's identity |

**Before the next session, confirm all four of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-03.sh
./scripts/utilities/verify-lab-04.sh
grep -c '^export' configs/lab-04.env
aws s3api head-bucket --bucket usms-student-data ; echo "exit code: $?"
```

You want `FAIL=0` twice, a count of **26**, and a **non-zero** exit code from `head-bucket` — probably
254, with a `404` or `NoSuchBucket` message. Save that output. Lab 5 runs the same command after
creating the bucket, and the difference between the two results is the point of the step.

**Read ahead, five minutes:** find out what makes an S3 bucket name globally unique, and what the
difference is between the `aws s3` and `aws s3api` command sets. Lab 5 uses both, deliberately.

Finally, take a snapshot so that a mistake in Lab 5 is recoverable:

```bash
floci snapshot save lab-04-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback. Stop Floci first —
archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-04.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-04.tar.gz
```

The archive lives in your home directory, outside the repository, so it is never a commit candidate.

---

## Appendix A — Command Reference

Every command this lab used, grouped by service.

### Amazon ECS

| Command | What it does |
| --- | --- |
| `aws ecs create-cluster` | Create a cluster; `--settings name=containerInsights,value=enabled` |
| `aws ecs describe-clusters` | Read clusters; `--include SETTINGS` to see the settings |
| `aws ecs list-clusters` | List cluster ARNs; there is no server-side filter, so filter with `--query` |
| `aws ecs delete-cluster` | Delete a cluster; refuses while an active service exists |
| `aws ecs register-task-definition` | Register a new revision of a family |
| `aws ecs describe-task-definition` | Read a revision, or the latest in a family |
| `aws ecs list-task-definitions` | List revisions; `--family-prefix` narrows it |
| `aws ecs deregister-task-definition` | Move a revision to `INACTIVE`; it is never fully deleted |
| `aws ecs create-service` | Create a service; `--network-configuration` for `awsvpc` |
| `aws ecs describe-services` | Read a service, its four counts and its `events` list |
| `aws ecs list-services` | List service ARNs in a cluster |
| `aws ecs update-service` | Change `--desired-count`, `--task-definition` and more |
| `aws ecs delete-service` | Delete a service; needs `--force` if tasks are running |
| `aws ecs wait services-stable` | Block until `runningCount` equals `desiredCount` |
| `aws ecs list-tasks` | List task ARNs; `--service-name`, `--desired-status STOPPED` |
| `aws ecs describe-tasks` | Read tasks, including `stoppedReason` — the first place to look |
| `aws ecs list-tags-for-resource` | Read tags; takes an **ARN**, not a name |
| `aws ecs tag-resource` | Add tags to an existing ECS resource |

### Application Auto Scaling

| Command | What it does |
| --- | --- |
| `aws application-autoscaling register-scalable-target` | Register or **update** a target; also sets `--suspended-state` |
| `aws application-autoscaling describe-scalable-targets` | Read targets; `--resource-ids` filters |
| `aws application-autoscaling deregister-scalable-target` | Remove a target and, silently, its policies |
| `aws application-autoscaling put-scaling-policy` | Create or replace a policy; returns `PolicyARN` and `Alarms` |
| `aws application-autoscaling describe-scaling-policies` | Read policies and their full configuration |
| `aws application-autoscaling delete-scaling-policy` | Delete one policy |
| `aws application-autoscaling put-scheduled-action` | Create or replace a scheduled action; `--timezone` |
| `aws application-autoscaling describe-scheduled-actions` | Read scheduled actions |
| `aws application-autoscaling delete-scheduled-action` | Delete one scheduled action |
| `aws application-autoscaling describe-scaling-activities` | **The audit trail.** Every capacity change with its cause |

### Amazon CloudWatch and CloudWatch Logs

| Command | What it does |
| --- | --- |
| `aws cloudwatch put-metric-data` | Publish a custom metric data point; `--dimensions K=V` |
| `aws cloudwatch get-metric-statistics` | Read aggregated data; `--dimensions Name=K,Value=V` |
| `aws cloudwatch list-metrics` | Discover which metrics and dimension sets exist |
| `aws cloudwatch put-metric-alarm` | Create or **fully replace** an alarm — no partial update |
| `aws cloudwatch describe-alarms` | Read alarms, their state and their actions |
| `aws cloudwatch set-alarm-state` | Force a state to test the alarm's actions; temporary |
| `aws cloudwatch delete-alarms` | Delete alarms by name |
| `aws logs create-log-group` | Create a log group; `--tags` is a **map** |
| `aws logs put-retention-policy` | Set retention; a separate call, and easy to forget |
| `aws logs describe-log-groups` | Read log groups; `--log-group-name-prefix` |
| `aws logs delete-log-group` | Delete a group and everything in it |

### IAM and EC2 used in this lab

| Command | What it does |
| --- | --- |
| `aws iam create-role` | Create a role from a trust policy document |
| `aws iam create-policy` | Create a customer managed policy |
| `aws iam attach-role-policy` / `detach-role-policy` | Attach and detach; detach before `delete-role` |
| `aws iam list-attached-role-policies` | What a role actually carries |
| `aws iam list-roles --path-prefix /aws-service-role/` | Find service-linked roles |
| `aws ec2 create-security-group` | Create the task security group |
| `aws ec2 authorize-security-group-ingress` | `--ip-permissions file://...` for a group-referenced rule |
| `aws ec2 describe-instances --filters Name=instance.group-id` | Reverse lookup: who carries this group |

**Four tag conventions in one lab, and no rule connects them:**

| Service | Syntax |
| --- | --- |
| EC2 | `--tag-specifications 'ResourceType=x,Tags=[{Key=K,Value=V}]'` |
| ECS | `--tags key=K,value=V` (lower case) |
| IAM | `--tags Key=K,Value=V` (capitals, no `ResourceType`) |
| CloudWatch Logs, Application Auto Scaling | `--tags K=V` (a plain map) |
| CloudWatch alarms | `--tags Key=K,Value=V` |

Run `aws <service> <operation> help` and read the `--tags` synopsis. That habit is more durable than any
of the five.

---

## Appendix B — New JMESPath and CLI patterns introduced

Labs 1 to 3 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `Tags[?Key==...]|[0].Value`, `--filters`, `--generate-cli-skeleton`, `--cli-input-json`
and `aws <service> wait`. This lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `options."awslogs-group"` | Double quotes inside a JMESPath expression, for a key containing a hyphen — otherwise read as subtraction | Step 9 |
| `[-3:]` | A **slice**: the last three elements. Works like Python — `[0:2]`, `[:5]`, `[-1]` | Step 20 |
| `[?PolicyName=='name'].Field` | Single quotes for a string literal in JMESPath, usable where backticks fight the shell | Section 9 script |
| `clusterArns[?contains(@, 'x')] \| [0]` | Client-side filtering where the service offers no `--filters` | Step 22 |
| `--max-items N` | Client-side pagination: stop after N items and return a `NextToken` | Step 3 |
| `--starting-token` | Resume a paginated call from a previous `NextToken` | Step 3 note |
| `--filters "Name=instance.group-id,Values=..."` | EC2 reverse lookup: which instances carry a security group | Step 23 |
| `--suspended-state '{...}'` | Inline JSON as a parameter value, single-quoted against the shell | Step 21 |
| `--scalable-target-action MinCapacity=6,MaxCapacity=12` | CLI shorthand for a small nested structure | Step 19 |
| `awsvpcConfiguration={subnets=[a,b],securityGroups=[c],assignPublicIp=DISABLED}` | Nested shorthand: no spaces, no quotes around the IDs | Step 10 |
| `python3 -c` for UTC timestamps | Portable across GNU and BSD, unlike `date -d` versus `date -v` | Steps 16, 20 |
| `paste file1 file2` | Compare two captured values side by side | Step 18 |
| `awk -F/ '{print $NF}'` | Take the bare name from the end of an ARN | Step 22 |

### The distinction to keep straight

Three services in this lab identify their resources three different ways, and mixing them is the single
biggest source of wasted time:

```text
ECS                        by NAME, with the cluster named separately
                             --cluster usms-ecs-cluster --service usms-enrolment-svc
ECS tagging                by ARN
                             --resource-arn arn:aws:ecs:...:service/usms-ecs-cluster/usms-enrolment-svc
Application Auto Scaling   by a CONSTRUCTED COMPOSITE STRING, plus a namespace and a dimension
                             --resource-id service/usms-ecs-cluster/usms-enrolment-svc
```

The third looks like the tail of the second, and it is — which is exactly why passing the whole ARN
seems reasonable and is wrong.

---

## Sources

- [What is Amazon Elastic Container Service?](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html)
- [Amazon ECS task definitions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html)
- [Task definition parameters, including CPU and memory for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html)
- [Amazon ECS task execution IAM role](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html)
- [Amazon ECS task IAM role](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [Amazon ECS services](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_services.html)
- [Fargate task networking with awsvpc mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
- [Using the awslogs log driver](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_awslogs.html)
- [Amazon ECS Service Auto Scaling](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-auto-scaling.html)
- [What is Application Auto Scaling?](https://docs.aws.amazon.com/autoscaling/application/userguide/what-is-application-auto-scaling.html)
- [Target tracking scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-target-tracking.html)
- [Step scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-step-scaling-policies.html)
- [Scheduled scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/examples-scheduled-actions.html)
- [Suspending and resuming scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-suspend-resume-scaling.html)
- [Service-linked roles for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/security_iam_service-with-iam.html)
- [Publish custom metrics to Amazon CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/publishingMetrics.html)
- [Using Amazon CloudWatch alarms, including missing data treatment](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html)
- [Amazon ECS CloudWatch Container Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights.html)
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [`aws ecs` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/)
- [`aws application-autoscaling` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/application-autoscaling/)
- [JMESPath specification](https://jmespath.org/specification.html)

---

*Lab 04 complete. Lab 05 — S3 — creates the bucket that has been named in an IAM policy since Lab 1,
and both `usms-web-01` and the enrolment tasks will reach it with no credentials on disk.*
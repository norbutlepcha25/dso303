# Lab 04 - Amazon ECS

## 1. Lab Overview

Lab 3 gave USMS two servers. They are exactly the size you made them and they will stay that size
until somebody logs in and changes them. That is fine for a portal that serves a steady trickle of
requests. It is not fine for **enrolment week**, when four thousand students try to register for
modules in the first twenty minutes of a Monday morning and then nothing happens for six days.

This laboratory builds the layer that solves that. You will containerise the USMS enrolment service
onto **Amazon ECS**, running on **Fargate**, inside the private subnets Lab 2 built: a cluster, a task
definition with the two IAM roles a task actually needs, a security group sourced from the web tier's
own group, and a service that keeps the right number of tasks running across two Availability Zones.

The single most important idea in this lab is the separation between the four ECS objects - **cluster,
task definition, task, and service** - and the fact that only the service's `desiredCount` is a moving
target at all. That separation is also what makes the next two labs possible: Lab 05 puts this service
behind a load balancer, and Lab 06 hands `desiredCount` over to Application Auto Scaling so the service
grows and shrinks on its own. Neither of those is this lab's job - this lab's job is to get a correctly
built, correctly networked, correctly permissioned service standing still.

**Time:** roughly 2.5 hours, including the exercises.

**Where this sits in the course**

```text
Lab 01  IAM ..................... roles, policies, instance profile
Lab 02  VPC ..................... the network: subnets, NAT, route tables, security groups
Lab 03  EC2 .................... usms-web-01 and usms-db-01 in that network
Lab 04  ECS ..................... THIS LAB - the enrolment service, deployed and standing still
Lab 05  ALB ..................... the same service, reachable through a load balancer
Lab 06  Autoscaling ............. the same service, growing and shrinking on its own

```

!!! info "A note on the numbering"
    An earlier roadmap pointed Lab 3 at "S3" next. This lab takes the Lab 04 slot instead, because
    ECS depends on nothing that S3 or Lambda would have built - it needs Lab 1's IAM and Lab 2's
    network, and both exist. Lambda is Lab 10; the S3 configuration lab was never written as its own
    document. Nothing already created changes name, and no file already committed is rewritten.

    Two forward references from Lab 3 now land here rather than where they said they would: the
    "golden AMI in a launch template" promise (Lab 3 Step 20) belongs to **EC2** Auto Scaling, which
    is a different service from the one in this lab, and is still ahead of you. Section 12.3 explains
    the difference so that you do not conflate them.

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. Explain what a cluster, a task definition, a task and a service are in ECS, and say which of the
   four is the thing that, in a later lab, gets scaled.
2. Explain what Fargate removes from the EC2 model, and what it does not remove.
3. Write and register a task definition, including `awsvpc` network mode, CPU and memory sizing, an
   execution role, a task role and an `awslogs` log configuration.
4. Distinguish an ECS **task execution role** from an ECS **task role**, and say which one pulls the
   image and which one the application code uses.
5. Create a service in a private subnet and explain, from Lab 2's route table, how it pulls its
   container image at all.
6. Read the four numbers that describe a service's health - `desiredCount`, `runningCount`,
   `pendingCount` and `status` - and say what a mismatch between the first two means.
7. Record every ARN and name this lab created into `configs/lab-04.env`, and explain why it is looked
   up from the API rather than copied from a shell variable.

!!! info "Auto scaling is not this lab"
    Registering a scalable target, target tracking, step scaling, scheduled actions and the
    persistence proof for all of it are **Lab 06's** learning objectives, not this lab's. This lab
    hands Lab 06 a service that stands still at a fixed `desiredCount` of 2; Lab 06 is the one that
    makes that number move on its own.

---

## 3. Prerequisites

- **Lab 1 complete.** `usms-developer-role`, `USMSStudentDataReadWrite` and the rest of the IAM
  foundation.
- **Lab 2 complete**, including Exercise 5, so that both private subnets exist. This lab puts tasks
  in two Availability Zones.
- **Lab 3 complete.** `usms-app-sg` must be attached to a running `usms-web-01`, because Step 8's
  security group rule references that group by ID.
- `./scripts/utilities/verify-lab-02.sh` and `./scripts/utilities/verify-lab-03.sh` both report
  `FAIL=0`.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq` and `python3` available. `jq` parses the JSON several commands return; `python3` validates
  every policy and template document this lab writes with `python3 -m json.tool`.

Check all of that in one go:

```bash
cd ~/aws-floci-course
for t in jq python3 docker; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
```

> Example output - your versions will differ.

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
- policies/trust-ecs-tasks.json, policies/usms-ecs-task-execution-policy.json
- templates/lab-04-taskdef.json
- configs/lab-04.env
- scripts/utilities/verify-lab-04.sh
- scripts/cleanup/lab-04-cleanup.sh

Required for future labs:
- usms-ecs-cluster              -> Lab 05 puts a load balancer in front of usms-enrolment-svc; the
                                   CloudFormation lab re-declares this service as a template
- usms-enrolment-svc            -> Lab 06 registers it as a scalable target and puts it under
                                   Application Auto Scaling; Lab 05 attaches it to a target group first
- usms-ecs-task-role            -> Lab 10 creates the bucket its policy already names
```

### 4.2 What this lab genuinely reuses

Not mentions - uses.

| From | Used here how |
| --- | --- |
| Lab 2 `usms-private-subnet-a` and `-b` | Step 10 places the service's tasks in both, by ID from `configs/lab-02.env` |
| Lab 2 `usms-nat` and `usms-private-rt` | Step 10 explains, and Step 11 verifies, that this is the only reason a task in a private subnet can pull a container image |
| Lab 2 `usms-s3-endpoint` | Step 10 names it: container image layers are stored in S3, so the endpoint is on the path too |
| Lab 2 `usms-app-sg` | Step 8 makes it the *source* of the enrolment service's only inbound rule - the web tier is the only thing allowed to call the enrolment API |
| Lab 3 `usms-web-01` | Exercise 5 resolves the group reference from Step 8 back to the instance that carries it, closing the loop |
| Lab 1 `USMSStudentDataReadWrite` | Step 7 attaches it to `usms-ecs-task-role`, so the container gets the same bucket permissions the EC2 instance has |
| Lab 1 `usms-developer-role` | Step 4 creates the cluster while holding it, then restores your normal identity |
| `configs/course.env` names | `$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT` used, never redeclared |

### 4.3 The moment three labs meet

Lab 1 wrote `USMSStudentDataReadWrite` describing a bucket that does not exist. Lab 3 attached it to
an EC2 instance and traced the chain. This lab attaches **the same policy** to a completely different
kind of compute - a container task - and the chain is the same shape: task → task role → policy →
bucket ARN.

That is the point worth pausing on when you reach Step 7. The instance profile in Lab 3 and the task
role here are two different mechanisms for delivering the same thing: **temporary credentials to code
that never sees a key.** When Lab 10 finally runs `create-bucket`, *both* of them start working at the
same moment, and neither one needed to be changed.

Say that out loud before you continue. It is a review question, and it is the single most useful
sentence about IAM in the whole course.

---

## 5. What We Are Building

The USMS enrolment service. It is the endpoint the student portal calls when somebody clicks
"Register for this module". Today it runs as a single EC2 instance with no failover and no way to
add capacity except by hand. This lab moves it onto Amazon ECS: an immutable task definition, a
service controller whose entire job is to keep `runningCount` equal to `desiredCount`, and a cluster
that can restart a failed task without you noticing at 3am.

### 5.1 Why ECS instead of another EC2 instance

An EC2 instance is a pet. If it dies, someone has to notice, log in, and fix it. A task in an ECS
service is cattle: the service controller notices before you do and replaces it. The task definition
is versioned and immutable, so a bad deploy is a `describe-task-definition` away from a rollback, not
an SSH session and a guess.

None of that requires scaling. Capacity planning - how many tasks, and how that number changes with
load - is a separate concern, and Lab 06 owns it once this lab has given it a `desiredCount` to move.
This lab's job is narrower: get the service running correctly, behind the right IAM roles, in the
right subnets, with its logs going somewhere.

### 5.2 What this lab deliberately does not do

No scalable target, no target tracking, no step scaling, no scheduled scaling. `desiredCount` is set
once, by hand, and stays fixed for the rest of this lab. That is not an oversight; teaching capacity
planning properly needs its own document, and Lab 06 is that document. Trying to do both here would
mean either rushing scaling or padding out a deploy lab that should be able to stand on its own.

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
  ||       usms-enrolment-svc      desiredCount  <---- fixed by hand here   ||
  ||         task definition usms-enrolment:1                               ||
  ||           execution role usms-ecs-exec-role  -> pull image, write logs ||
  ||           task role      usms-ecs-task-role  -> USMSStudentDataReadWrite||
  ==========================================================================
```

`desiredCount` is set once in Step 10 and does not move again in this lab. Lab 06 is the one that
puts a scalable target on top of this exact service and gives that number a reason to change on its
own.

---

## 7. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-04-ecs/
│       ├── README.md                              # this document
│       └── exercises.md                           # Section 13
├── policies/
│   ├── trust-ecs-tasks.json                       # NEW - trust policy for both ECS roles
│   └── usms-ecs-task-execution-policy.json        # NEW - USMSECSTaskExecution document
├── templates/
│   └── lab-04-taskdef.json                        # NEW - register-task-definition input
├── configs/
│   └── lab-04.env                                 # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-04.sh                       # NEW - Section 9
│   └── cleanup/
│       └── lab-04-cleanup.sh                      # NEW - end of course only
└── outputs/
    └── lab-04-*.json / *.txt                      # command output, git-ignored
```

`lab-04-taskdef.json` goes in `templates/`, not `policies/`, because it is an **API request body**,
not an IAM policy document. `policies/` in this course means "a document that grants or denies
something". Keeping the two apart matters more than it looks: a reviewer scanning `policies/` should
be looking at your security posture and nothing else.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-04-ecs
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs
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

### Step 1 - Resume the environment and load three env files

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

`floci-up.sh` is idempotent - it starts the container if it is stopped, says so if it is already
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

> Example output - your IDs will differ.

**Verify**

Eight non-empty values. `private subnet b` empty means Lab 2 Exercise 5 was skipped - go and do it,
because Step 10 places tasks across two Availability Zones and a service with one subnet cannot
survive an AZ failure, which is half of why the minimum capacity in this lab is 2.

---

### Step 2 - Confirm Labs 2 and 3 are still intact

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
  nothing uses, and Exercise 5's loop-closing check would be meaningless.

---

### Step 3 - Probe what this Floci build actually supports

**Purpose**

Application Auto Scaling - the service Lab 06 puts this service under - may be absent from your build
entirely. Rather than discovering that in Lab 06, find out now, and find out which of three paths you
are on. This is the same principle as Lab 1's storage check: name the limitation before it costs you an
hour, not afterwards.

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
Two of the commands are expected to fail on their *arguments* rather than on support -
`describe-services --cluster probe` names a cluster that does not exist - so read the result as
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

> Example output - this is the best case. Yours may differ, and that is the point of running it.

**Verify**

Work out which path you are on and write it at the top of `notes/lab-04-notes.md`, because your lab
report needs to say so:

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | ECS and Application Auto Scaling both supported | Do every step in this lab as written; Lab 06 will also have full support for its scaling policies |
| **B - ECS only** | ECS supported, Application Auto Scaling not | Every step in this lab is ECS-only and is unaffected - the limitation does not surface until Lab 06. Record it here anyway, because Lab 06 reads this exact recording and gives you a documented fallback for exactly this situation |
| **C - neither** | ECS not supported | Stop and tell your instructor. Do the paper capacity-plan design in Exercise 4 instead, which is the part of this lab that does not need an emulator |

!!! note "Floci Limitation - Application Auto Scaling support is build-dependent"
    Some Floci builds implement the ECS API but not `application-autoscaling`, and some implement
    `register-scalable-target` but never actually evaluate a policy - the objects are stored and
    returned correctly, and nothing ever changes a desired count.

    Real AWS runs Application Auto Scaling as a continuously evaluating control loop: alarms are
    assessed every period, policies fire, and `describe-scaling-activities` accumulates a genuine
    audit trail of every capacity change with its cause.

    Take this away regardless, and carry it into Lab 06: the **shape** of a scaling configuration is
    what you are being assessed on there, and the shape is fully observable even when a policy never
    fires. A policy you can read and defend is worth more than a policy that happened to fire once.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01.env + lab-02.env + lab-03.env sourced
 ├── verify-lab-02.sh FAIL=0 and verify-lab-03.sh FAIL=0
 └── support path recorded: A (full) / B (ECS only) / C (neither)
```

---

### Interlude - what ECS actually is, in four objects

Four nouns, and keeping them apart makes the rest of this lab, and Lab 06 after it, easy. Students who
conflate them get stuck in Lab 06 asking why they cannot scale a task definition.

**A cluster** is a namespace. That is very nearly all it is. On Fargate it holds no servers, has no
capacity of its own, and costs nothing. It exists so that services and tasks have somewhere to be
grouped, and so that IAM policies and metrics can be scoped to a group. A cluster is not a machine.

**A task definition** is a versioned, immutable blueprint: which container images to run, how much CPU
and memory to give them, which ports they expose, which roles they assume, where their logs go. It is
registered as a **family** with **revisions** - `usms-enrolment:1`, `usms-enrolment:2` - and you can
never edit a revision, only register a new one. It is the direct analogue of an AMI in Lab 3: a
template, not a running thing.

**A task** is one running instantiation of a task definition. It has an ID, a status, an elastic
network interface with a private address from your subnet, and a lifetime. If it exits, it is gone -
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

### Step 4 - Create the ECS cluster, as the developer role

**Purpose**

Create the namespace everything else in this lab lives in. We do it while holding
`usms-developer-role`, exactly as Lab 2 Step 3 did, because doing the first build action of a lab as
the least-privileged identity is the habit this course wants you to leave with.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, assume the role**

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
    you pass - and the role's session is one hour, so leaving them set means `ExpiredToken` errors
    later in this session that look nothing like their cause.

**Expected result**

```text
{
    "UserId": "AROAEXAMPLEID:lab04-ecs-build",
    "Account": "000000000000",
    "Arn": "arn:aws:sts::000000000000:assumed-role/usms-developer-role/lab04-ecs-build"
}
```

> Example output - your `UserId` will differ. The `Arn` saying `assumed-role` is the point.

**Command - part 2, create the cluster**

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
 └── ecs                     the SERVICE - Elastic Container Service
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
conventions - it is to run `aws <service> <operation> help` and read the `--tags` synopsis whenever you
tag something in a service you have not tagged before.

`containerInsights` is what makes ECS publish per-service CPU and memory utilisation into the
`AWS/ECS` CloudWatch namespace. Lab 06's target tracking policy consumes exactly that metric, so
turning it on now is not decoration - that later policy has nothing to read without it.

**Expected result**

```text
CLUSTER_ARN = arn:aws:ecs:us-east-1:000000000000:cluster/usms-ecs-cluster
```

> Example output - the account is fixed by the course, so yours should match this closely.

**Command - part 3, restore your normal identity**

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
limitation - Lab 06's target tracking policy will then have no CPU metric to track, and a custom
metric becomes the only working scaling signal, which is a genuinely useful thing to have discovered.

---

### Step 5 - Create the log group the tasks will write to

**Purpose**

A container's stdout goes nowhere unless you tell it where. The `awslogs` driver in Step 9's task
definition names a log group, and **the group must exist first** - ECS does not create it for you, and
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

Log group names conventionally start with a slash and use slashes as a hierarchy -
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

> Example output - `Bytes` is 0 because nothing has logged yet.

**Verify**

One row, `Retention` exactly `7`. If `Retention` is `None`, `put-retention-policy` did not take -
re-run it. A `None` here is not fatal for the lab but it is a finding for your report, because the
lesson of this step is that the retention is a separate decision that is easy to forget.

---

### Interlude - two ECS roles, and which is which

This is the single most-confused pair of objects in ECS, and getting them backwards produces errors
that point at the wrong thing. Learn the distinction here rather than at Step 9.

| | Task **execution** role | Task role |
| --- | --- | --- |
| Assumed by | The ECS agent / Fargate infrastructure, **before** your container starts | Your application code, **inside** the running container |
| Used for | Pulling the container image, writing the log stream, reading secrets named in the task definition | Whatever the application does: S3, DynamoDB, SQS |
| Trust principal | `ecs-tasks.amazonaws.com` | `ecs-tasks.amazonaws.com` - the same |
| Field in the task definition | `executionRoleArn` | `taskRoleArn` |
| Failure symptom if missing or wrong | The task **never starts**; `stoppedReason` mentions the image pull or the logs | The task starts fine and the application gets `AccessDenied` at runtime |

The trust policy is identical for both, which is exactly why they get conflated. The difference is
not who may assume them - it is *who does* and *when*.

The failure-symptom row is the practical value of the table. "My task will not start" points at the
execution role. "My task started and then my code got AccessDenied" points at the task role. Being
able to say which one from the symptom alone saves you half an hour every time.

---

### Step 6 - Create the task execution role

**Purpose**

Fargate needs an identity to pull the image and open the log stream before your code exists. This is
that identity.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the trust policy**

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

!!! warning "Heredoc quoting - the rule restated because this is where it matters"
    This heredoc is `<< 'EOF'`, **quoted**, because the document must reach disk exactly as written.
    Nothing in it should be expanded by your shell. Every policy document in this course is written
    this way.

    Contrast Step 9, where the task definition **must** be written with an unquoted `<< EOF` because
    it contains `$EXEC_ROLE_ARN` and three other variables that have to become real values at write
    time.

    The rule is always the same question: *do I want this expanded now, or later?* Getting it
    backwards fails silently in one direction and loudly in the other, which is why the loud direction
    is the safer mistake.

**Command - part 2, create the role**

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

**Command - part 3, the permissions it needs, written as least privilege**

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

`ecr:GetAuthorizationToken` has `"Resource": "*"` because it genuinely takes no resource - it is an
account-level call that returns a registry credential. Some actions are like this, and writing a
narrower ARN for them produces a policy that denies everything with no error message. Check the
service authorization reference before assuming an action is resource-scoped.

The `logs` statement, by contrast, is scoped to **exactly one log group**, with a trailing `:*` to
cover the log streams inside it. AWS's own managed
`AmazonECSTaskExecutionRolePolicy` uses `"Resource": "*"` for logs - which means any task using it can
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

**What to look for:** the principal is `{"Service": "ecs-tasks.amazonaws.com"}` - not
`ecs.amazonaws.com`, which is a different service principal for a different purpose and is the single
most common typo in ECS. The attached policy list contains `USMSECSTaskExecution`.

---

### Step 7 - Create the task role, and reuse Lab 1's policy on it

**Purpose**

This is the container's own identity - the one the application code uses. And it is the moment the
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
principal - that is not laziness, it is the correct document for both.

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

**Verify - and read the policy, because this is the teaching moment**

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

Two entirely different compute services - an EC2 instance and a Fargate task - now hold the same
permission, delivered by two different mechanisms:

```text
Lab 03   usms-web-01 ── instance profile ── usms-ec2-app-role ──┐
                                                                ├── USMSStudentDataReadWrite
Lab 04   task         ── taskRoleArn      ── usms-ecs-task-role ─┘
                                                                     |
                                                          arn:aws:s3:::usms-student-data
                                                              (does not exist yet - Lab 09)
```

Neither of them has a key on disk. Neither of them needed the policy changed. Both of them start
working at the same instant Lab 10 runs `create-bucket`. Write that into `notes/lab-04-notes.md` now -
it is Review Question 2.

!!! note "Floci Limitation - the container cannot fetch its own credentials"
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

### Step 8 - Create the enrolment security group, sourced from the web tier's group

**Purpose**

A Fargate task in `awsvpc` mode has its own network interface and its own security group, exactly like
an EC2 instance. The enrolment API must accept calls from the student portal and from nothing else -
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
        "Description": "HTTP from the USMS web tier (usms-app-sg) - the only caller of the enrolment API"
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
gave - and here there is a second reason that did not apply then. **The tasks have no stable
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

> Example output - your IDs will differ.

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$ENROLMENT_SG" \
  --query 'SecurityGroups[0].{Name:GroupName,Inbound:IpPermissions[].{Port:FromPort,FromGroup:UserIdGroupPairs[0].GroupId,FromCIDR:IpRanges[0].CidrIp},OutboundRules:length(IpPermissionsEgress)}' \
  --output json
```

**What to look for:** one inbound rule on port 80 whose `FromGroup` is your `$USMS_APP_SG` and whose
`FromCIDR` is `null`. If `FromCIDR` has a value you wrote an address-based rule and the point of the
step was missed. `OutboundRules` is `1` - the allow-all-outbound rule you never wrote, and which is
about to matter a great deal in Step 10.

---

### Step 9 - Write and register the task definition

**Purpose**

The blueprint. Everything the two previous steps produced gets referenced here, and this is the
document a code reviewer would actually read to understand what the enrolment service is.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write the document**

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
  && echo "valid JSON" || echo "INVALID JSON - fix it before registering"

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
| `networkMode` | `awsvpc` is **required** for Fargate. It gives the task its own ENI, private address, and security group - which is what lets Step 8's rule apply to it at all |
| `requiresCompatibilities` | Declares the launch types this definition is valid for. Getting it wrong produces a validation error at registration, which is the right time |
| `cpu` / `memory` | **Strings, not numbers.** One of the valid Fargate pairs from the interlude |
| `executionRoleArn` | Step 6's role. Pulls the image, opens the log stream |
| `taskRoleArn` | Step 7's role. What the application code is |
| `image` | A public registry reference. See the note below |
| `essential` | `true` means: if this container exits, stop the whole task. With one container it is always `true`; with a sidecar, the sidecar is usually `false` |
| `logConfiguration` | `awslogs` sends stdout and stderr to the group from Step 5. `awslogs-stream-prefix` is what makes each task's stream identifiable |
| `tags` | Lower-case `key`/`value`, because this is the ECS API - the third convention from Step 4 |

!!! note "Floci Limitation - the container image is a stand-in"
    The real USMS enrolment service would be your own application, built into an image and pushed to
    a private ECR repository - which would mean uncommenting the `5100-5104` port range in
    `docker-compose.yml` and re-running `floci-up.sh`. This lab deliberately does not, because
    publishing ports you do not need makes Docker Desktop crawl and this lab is about scaling, not
    about registries.

    `public.ecr.aws/nginx/nginx:stable-alpine` is therefore a placeholder: a real, small, public image
    that a real Fargate task could genuinely pull. What it serves is irrelevant - nothing in this lab
    sends it a request.

    Depending on your Floci build, the image may be pulled and run as a Docker container, or the task
    may never leave `PROVISIONING`. Both are fine. Every proof in this lab is built on
    `desiredCount`, which is a control-plane number, so nothing here depends on a container actually
    running.

**Command - part 2, register it**

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

> Example output - if your revision is higher than 1 you have registered before, which is harmless.

**Verify**

```bash
aws ecs describe-task-definition --task-definition usms-enrolment \
  --query 'taskDefinition.{Family:family,Revision:revision,Status:status,Network:networkMode,CPU:cpu,Memory:memory,Compat:requiresCompatibilities,Exec:executionRoleArn,Task:taskRoleArn,Container:containerDefinitions[0].name,Image:containerDefinitions[0].image,LogGroup:containerDefinitions[0].logConfiguration.options."awslogs-group"}' \
  --output json
```

**What to look for:** `Status` is `ACTIVE`, `Network` is `awsvpc`, and `Exec` and `Task` are two
**different** ARNs. If they are the same, you assigned one role to both fields - the task would start
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

### Step 10 - Create the service in Lab 2's private subnets

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

No spaces anywhere. Square brackets for the lists, and **no quotes around the individual IDs** -
adding them is a parse error. If it fights you, generate the skeleton and use a document instead:

```bash
aws ecs create-service --generate-cli-skeleton > outputs/lab-04-create-service-skeleton.json
```

`assignPublicIp=DISABLED` is the correct value for a private subnet, and it is also the default. State
it explicitly anyway: this is a security-relevant setting, and a reader should not have to know the
default to know what you meant. Setting it to `ENABLED` in a private subnet gives the task a public
address it cannot use, and on real AWS bills you for it.

`--enable-ecs-managed-tags --propagate-tags SERVICE` makes ECS copy the service's tags onto every
task it launches. Without it, tasks created by auto scaling are untagged - and untagged resources that
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
to start with an image-pull timeout - a failure whose cause is four steps and one lab away from its
symptom.

That is also the practical answer to "why would anyone use a VPC endpoint": the alternative on real AWS
is paying NAT data-processing charges to pull the same image layers on every scale-out event, for the
lifetime of the service.

**Expected result**

```text
SERVICE_ARN = arn:aws:ecs:us-east-1:000000000000:service/usms-ecs-cluster/usms-enrolment-svc
```

> Example output. Look at the shape of that ARN - `service/<cluster>/<service>`. Lab 06's scalable
> target registration needs exactly that suffix, and now you know where it comes from.

**Command - wait for it**

```bash
aws ecs wait services-stable --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
  && echo "service stable" \
  || echo "waiter did not complete - check the state manually below (expected on some builds)"
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
On real AWS that is 40 seconds or so for two small Fargate tasks. On Floci it is immediate, or never -
if `runningCount` stays at 0 while `desiredCount` is 2, that is the "no containers behind the API"
limitation and it does not block anything in this lab.

---

### Step 11 - Read the service back, and learn the four numbers

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
| `runningCount` | How many tasks are actually up | Lower than desired for a long time means tasks are failing to start - look at `stoppedReason` on a stopped task |
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

> Example output - your IDs will differ, and `Running` may be `0` on builds that do not start
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
`runningCount` will not rise - on real AWS the message names the reason directly.

If `length(taskArns)` is 0 while `Desired` is 2, record it as the container limitation and continue.

✏️ **Your turn**

Before any auto scaling exists, change the capacity by hand. Set the service's desired count to 3 with
`aws ecs update-service`, wait for it to settle, then set it back to 2.

```text
Expected result:
desiredCount moves to 3, then back to 2. The service's events list gains entries.
Nothing you do here involves Application Auto Scaling at all - and that is the point:
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

### Step 12 - Write `configs/lab-04.env`

**Purpose**

Every shell variable in this terminal dies when you close it, and this lab created eleven things worth
naming. Lab 05 needs the cluster, the service, the enrolment security group and the container name to
attach a load balancer; Lab 06 needs the baseline desired count as the floor for the scalable target it
registers; a later lab needs the task role to add a second principal to the bucket policy Lab 1 already
wrote. Record all of it by lookup, not from the shell variables above, so that a populated value in the
file is evidence the resource actually exists.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-04.env << EOF
# Lab 04 - ECS cluster, task definition, roles and service outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs and ARNs only. NO SECRETS. Safe to commit.
#
# Lab 05 attaches a load balancer to the service recorded here. Lab 06 registers
# this service as a scalable target, using the baseline desired count as its floor.

export USMS_ECS_CLUSTER=usms-ecs-cluster
export USMS_ECS_CLUSTER_ARN=$(aws ecs describe-clusters --clusters usms-ecs-cluster \
  --query 'clusters[0].clusterArn' --output text)

export USMS_ENROLMENT_SERVICE=usms-enrolment-svc
export USMS_ENROLMENT_SERVICE_ARN=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].serviceArn' --output text)
export USMS_ECS_DESIRED_BASELINE=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].desiredCount' --output text)

export USMS_ENROLMENT_TASK_FAMILY=usms-enrolment
export USMS_ENROLMENT_TASK_REVISION=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment --query 'taskDefinition.revision' --output text)
export USMS_ENROLMENT_CONTAINER=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment \
  --query 'taskDefinition.containerDefinitions[0].name' --output text)
export USMS_ECS_TASK_CPU=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment --query 'taskDefinition.cpu' --output text)
export USMS_ECS_TASK_MEMORY=$(aws ecs describe-task-definition \
  --task-definition usms-enrolment --query 'taskDefinition.memory' --output text)

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
EOF

grep -n 'export .*=$\|None' configs/lab-04.env || echo "all values populated"
```

**What the command does**

Unquoted heredoc - `<< EOF`, not `<< 'EOF'` - for the same reason as Lab 2 Step 24 and Lab 3 Step 22:
every `$(...)` must run **now** and the resulting value must land on disk. Had this been quoted, the
file would contain the text of nine API calls, and `source configs/lab-04.env` would re-run all of them
in every new terminal you open.

`USMS_ECS_DESIRED_BASELINE` is read back from the service rather than hard-coded as `2`, for the same
reason Lab 05 reads back `USMS_SVC_GRACE_PERIOD` instead of hard-coding it: if Step 10 or the Step 11
"Your turn" task left the count somewhere other than 2, the file records what is actually true rather
than what the lab intended, and Lab 06 reads this exact value as the floor for the scalable target it
registers.

**Verify**

```bash
source configs/lab-04.env

printf '%-26s %s\n' \
  "cluster"           "$USMS_ECS_CLUSTER" \
  "service"           "$USMS_ENROLMENT_SERVICE" \
  "baseline desired"  "$USMS_ECS_DESIRED_BASELINE" \
  "task revision"     "$USMS_ENROLMENT_TASK_REVISION" \
  "container"         "$USMS_ENROLMENT_CONTAINER" \
  "task cpu / memory" "$USMS_ECS_TASK_CPU / $USMS_ECS_TASK_MEMORY" \
  "enrolment sg"      "$USMS_ENROLMENT_SG" \
  "task role"         "$USMS_ECS_TASK_ROLE_ARN"

grep -c '^export' configs/lab-04.env
```

**What to look for:** `all values populated`, eight non-empty lines, and a count of **17** exported
variables. `baseline desired` must read `2` - anything else means the Step 11 "Your turn" task left the
count somewhere it should not have, and Lab 06 would then inherit the wrong floor. A `None` anywhere
means a resource does not exist or a step did not take; find which, because catching it here is worth
ten troubleshooting entries in Lab 05.

---

### Step 13 - Commit

**Purpose**

Same discipline as every lab: look first, stage explicitly, then commit.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-04-assumed-role.json
git ls-files outputs/
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears in `git status --short`.
- No `.env` at the repository root appears.
- `configs/lab-04.env` **does** appear. It holds names and ARNs, not secrets.
- `git check-ignore -v` names the file, the rule and the line number. **Silence there means the file is
  not ignored** - stop and fix `.gitignore` before committing anything.
- `git ls-files outputs/` lists `outputs/.gitkeep` and nothing else.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-04-assumed-role.json
outputs/.gitkeep
```

> Example output - your line number may differ.

**Command - part 2, commit**

```bash
git add labs/lab-04-ecs/ \
        configs/lab-04.env \
        policies/trust-ecs-tasks.json \
        policies/usms-ecs-task-execution-policy.json \
        policies/usms-enrolment-sg-ingress.json \
        templates/lab-04-taskdef.json \
        scripts/utilities/verify-lab-04.sh \
        scripts/cleanup/lab-04-cleanup.sh

git status --short

git commit -m "Lab 04: USMS enrolment service deployed on ECS Fargate - cluster, task definition, both IAM roles, security group and service"

git log --oneline -5
```

The `git add` names paths explicitly rather than using `git add -A`. That is not fussiness: `git add -A`
stages whatever happens to be in the working tree, which is exactly how an un-ignored secret reaches a
commit.

The two script paths only exist after Section 9. If you commit before that, drop them from the
`git add` line and add them in a second commit.

**Expected result**

```text
[main a71f3c2] Lab 04: USMS enrolment service deployed on ECS Fargate - cluster, task definition, both IAM roles, security group and service
 8 files changed, 210 insertions(+)
```

> Example output - your hash and counts will differ.

**Checkpoint 5**

```text
Lab 04 recorded
 ├── configs/lab-04.env         committed, 17 exports, fully populated
 ├── policies/                  trust document + least-privilege execution policy + sg ingress
 ├── templates/                 task definition under version control
 ├── outputs/                   nothing staged, and check-ignore proves the rule
 └── git log shows Lab 01, 02, 03 and 04 commits
```

---

## 9. Verification

### 9.1 What this script checks that a naive one would not

Four of the checks below are the ones worth having, and they are the reason a "does the service exist"
script is not enough:

- **`exec role and task role are DIFFERENT`** - the failure this catches produces a task that starts
  correctly and then gets `AccessDenied` at runtime, hours later.
- **`service spans TWO subnets`** - a service quietly narrowed to one subnet looks identical to a
  healthy one until the Availability Zone it lives in has a bad day.
- **`usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)`** - a rule rewritten as a CIDR block
  during a rushed fix would still pass a "does traffic flow" test and would already be wrong the moment
  Lab 06 lets the task count change.
- **`log group has a retention policy set`** - a log group with no retention policy looks identical to
  one with a sensible policy until it has been running for a year.

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
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ENROLMENT_TASK_FAMILY:=usms-enrolment}"
: "${USMS_ECS_DESIRED_BASELINE:=2}"
: "${USMS_ENROLMENT_SG:=none}"
: "${USMS_ECS_EXEC_ROLE:=usms-ecs-exec-role}"
: "${USMS_ECS_TASK_ROLE:=usms-ecs-task-role}"
: "${USMS_LOG_GROUP_ENROLMENT:=/usms/ecs/enrolment}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# svc <jmespath>  -> one field from the ECS service
svc() { aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
          --services "$USMS_ENROLMENT_SERVICE" --query "services[0].$1" --output text; }

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
check "service desiredCount is 2 (one task per Availability Zone)" \
  "test \"\$(svc desiredCount)\" = $USMS_ECS_DESIRED_BASELINE"

echo "== Lab 04 networking =="
check "usms-enrolment-sg exists"  "aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG"
check "usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)" \
  "test \"\$(aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'SecurityGroups[0].IpPermissions[0].UserIdGroupPairs[0].GroupId' --output text)\" = $USMS_APP_SG"
check "usms-enrolment-sg admits NOTHING from 0.0.0.0/0" \
  "! aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'SecurityGroups[0].IpPermissions[].IpRanges[].CidrIp' --output text | grep -q '0.0.0.0/0'"

echo "== Files and Git hygiene =="
check "configs/lab-04.env exists"        "test -f configs/lab-04.env"
check "configs/lab-04.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=$|=None$' configs/lab-04.env"
check "task definition document is valid JSON" \
  "python3 -m json.tool templates/lab-04-taskdef.json"
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
== Lab 04 ECS ==
  ok   cluster usms-ecs-cluster is ACTIVE
  ok   exec role and task role are DIFFERENT
  ...
== Files and Git hygiene ==
  ok   configs/lab-04.env exists
  ok   no secret is tracked by git

PASS=38  FAIL=0
```

> Example output - the middle is abbreviated; you will see all 38.

**The expected count is `PASS=38  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `service $USMS_ENROLMENT_SERVICE is ACTIVE` / any Lab 04 ECS check with `Running` at 0 | Some Floci builds never start a Fargate container; `runningCount` stays 0 while `desiredCount` is correct. Confirm with `describe-services --output json` and record it - it does not affect any check above, all of which read `desiredCount` or static configuration |
| `log group has a retention policy set` | Some builds ignore `put-retention-policy`. Confirm and record |
| `service spans TWO subnets` | Lab 2 Exercise 5 was skipped, so `usms-private-subnet-b` does not exist. This one is **not** benign - go and do it |

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** the ECS service, the cluster, every task definition revision in the
    `usms-enrolment` family, the enrolment security group, both ECS roles, the `USMSECSTaskExecution`
    policy and the log group.

    **What depends on it:** Lab 05 attaches a load balancer to this service. Lab 06 registers this
    service as a scalable target and builds its own scaling policies on top of it - and ships its own
    `lab-06-cleanup.sh` for that configuration, which must run **before** this script. A later lab uses
    `usms-ecs-task-role` to show that the bucket it creates resolves two permission chains at once.

    **Reversible?** No. You would repeat this laboratory from Step 4.

    **Effect on later labs:** total. Run this only at the end of the course, after `lab-06-cleanup.sh`
    and `lab-05-cleanup.sh`, and run it **before** `lab-02-cleanup.sh`, because a VPC with a security
    group in use cannot be deleted.

    It requires you to type `DELETE USMS ECS` in full before it does anything.

**Run from**

```text
aws-floci-course/
```

````bash
cat > scripts/cleanup/lab-04-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 04, dependencies first.
# Order: service (scaled to 0) -> task definitions -> cluster -> security group -> IAM -> log group.
# Run this AFTER scripts/cleanup/lab-06-cleanup.sh and scripts/cleanup/lab-05-cleanup.sh,
# and BEFORE scripts/cleanup/lab-02-cleanup.sh.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04.env"

cat <<'WARN'
============================================================
  This deletes the USMS enrolment service, its ECS cluster,
  its security group, both ECS IAM roles and its log group.

  Lab 05, Lab 06 and a later storage lab all depend on parts
  of it. None of this is reversible.
  Run this AFTER lab-06-cleanup.sh and lab-05-cleanup.sh,
  and BEFORE lab-02-cleanup.sh.
============================================================
WARN

read -r -p 'Type exactly: DELETE USMS ECS  > ' answer
[ "$answer" = "DELETE USMS ECS" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }

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
bash -n scripts/cleanup/lab-04-cleanup.sh && echo "syntax OK - do NOT run it"
````

**What to look for:** the words `syntax OK - do NOT run it`. `bash -n` parses the script without
executing a single command, which is the only safe way to check a destructive one.

The order is the lesson, and it is different from Labs 2 and 3 because the dependencies are different:

1. **`--desired-count 0` before `delete-service`.** ECS refuses to delete a service with running tasks
   unless you pass `--force`, and `--force` kills tasks without draining them. Scaling to zero and
   waiting is the graceful version, and it is what you would do in production.
2. **Task definitions before the cluster.** Deregistering leaves them in `INACTIVE` state; they are
   never truly deleted, and that is by design so that a service referencing an old revision can still
   be described.
3. **IAM detach before delete.** `delete-role` fails with `DeleteConflict` while a policy is attached,
   and the error does not name the policy.
4. **The security group after the service.** A group in use by a task's network interface cannot be
   deleted, and `DependencyViolation` does not say which interface is holding it.
5. **This script after Lab 06's and Lab 05's own cleanup scripts.** Lab 06 registered a scalable target
   against this service and Lab 05 attached a load balancer to it; both must be torn down first, or
   their delete calls fail against a service that no longer exists.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, four env files sourced, `verify-lab-02.sh` and `verify-lab-03.sh` both `FAIL=0`, and your support path (A, B or C) recorded |
| 2 | Step 7 | `usms-ecs-cluster` ACTIVE; `/usms/ecs/enrolment` with 7-day retention; `usms-ecs-exec-role` with `USMSECSTaskExecution`; `usms-ecs-task-role` with Lab 1's `USMSStudentDataReadWrite` |
| 3 | Step 9 | `usms-enrolment:1` ACTIVE, `awsvpc`, FARGATE, 256/512, and two **different** role ARNs in `executionRoleArn` and `taskRoleArn` |
| 4 | Step 11 | Service ACTIVE, desired 2, spanning both private subnets, `assignPublicIp` DISABLED, carrying `usms-enrolment-sg` |
| 5 | Step 13 | `configs/lab-04.env` populated with 17 exports and committed; nothing under `outputs/` staged; `git check-ignore -v` names the rule |

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

    Fix the document and register again. You cannot edit revision 1 - you register revision 2, then
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
    recoverable - restore from the snapshot you took at the end of Practical 1, and this time confirm
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
| CloudWatch Logs groups and retention | Full | Groups yes, retention build-dependent | Floci Limitation |
| Task credentials via `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` | Yes, rotated automatically | Not served to containers | Floci Limitation |
| Security group enforcement on task traffic | Every packet | Not enforced | Floci Limitation |
| Fargate task start latency | 20 to 60 seconds - the delay Lab 06's cooldowns are sized around | Instant or never | Floci Limitation |
| Cost - per vCPU-second and GB-second | Real | Free | Conceptual / Real AWS |
| Service quotas (tasks per service, services per cluster) | Enforced | Not enforced | Conceptual / Real AWS |
| Capacity providers, Fargate Spot, capacity provider strategies | Full | Not available | Conceptual / Real AWS |

### 12.1 What you actually observed in this lab

```text
OBSERVABLE - you saw this happen
  a cluster, a task definition family with an immutable revision, and a service
  a service placed in two private subnets with a security group and no public IP
  two ECS roles with the same trust policy and different attached permissions
  Lab 01's USMSStudentDataReadWrite attached to a second, different kind of compute
  a group-referenced security group rule
  desiredCount changed by hand with update-service, and the service's events narrating it

CONCEPTUAL - you reasoned about it, you may not have seen it
  a container actually running, serving, or logging
  Container Insights CPU utilisation existing as a number at all
  the 20-to-60-second task start latency that Lab 06's cooldowns are sized around
  the cost of running this service continuously
```

If your build put you on support path A from Step 3, several lines may move from the second list to
the first. Say in your report which list each item ended up in for you. Being precise about that is
worth marks; claiming to have observed something you reasoned about is worth negative marks.

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **Tasks start instantly, or not at all.** A real Fargate task takes 20 to 60 seconds from
  `desiredCount` changing to serving traffic. Lab 06's cooldowns are sized around that latency, and a
  system tuned on an emulator where capacity appears instantly will be tuned wrongly.
- **No cost.** Two `256`/`512` Fargate tasks running continuously are roughly USD 15 per month at
  us-east-1 list prices. Check current numbers on the AWS pricing pages before quoting any of this;
  Exercise 4 asks you to cite a source.
- **No quotas.** Real accounts have limits on tasks per service and services per cluster, and hitting
  one fails in a way that looks like something else is broken.

### 12.3 ECS Service Auto Scaling is not EC2 Auto Scaling

These are two different services with similar names, and conflating them is the most common confusion in
this area. Lab 3 Step 20 built `usms-web-golden` for the *other* one, and Lab 06 is where this lab's
service meets the first of the two.

| | **Application Auto Scaling** (Lab 06) | **EC2 Auto Scaling** |
| --- | --- | --- |
| Scales | ECS services, DynamoDB, Aurora, Lambda concurrency, and more | EC2 instances, and nothing else |
| The unit | A task, or a capacity unit | An instance |
| Configuration object | A scalable target plus policies | An Auto Scaling group plus policies |
| Needs a launch template or AMI | No - a task definition, which this lab registered | Yes |
| CLI command family | `aws application-autoscaling` | `aws autoscaling` |
| Health checks and instance replacement | Handled by the ECS service, which this lab created | Handled by the Auto Scaling group |
| Predictive scaling | Not available | Available |
| The ECS `EC2` launch type | Scales the **tasks** | Scales the **instances the tasks land on** |

The last row is the one worth remembering, because on ECS with the `EC2` launch type you need **both**:
Application Auto Scaling to add tasks, and EC2 Auto Scaling (or a capacity provider) to add the
instances for them to run on. Fargate removes the second problem entirely, which is a large part of why
this lab uses it.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-04-ecs/exercises.md`. Take screenshots into
`screenshots/` where an exercise asks for evidence.

### Exercise 1 - Basic: a second service, deployed

**Requirements**

The USMS results service publishes exam results. It has the same blueprint as the enrolment service but
a lower floor. Create `usms-results-svc` in `usms-ecs-cluster` from the existing `usms-enrolment` task
definition family, with a desired count of 1, in both private subnets, carrying `usms-enrolment-sg`.

**Constraints**

- Every ID captured with `$(...)` and `--query`. Nothing copied by hand.
- Tag the service `Project=USMS`, `Tier=app`, `Lab=04`, `Service=results`.
- Do **not** record it in `configs/lab-04.env`. Exercise 4 removes it.

**Expected outcome**

`aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc usms-results-svc`
returns **two** `ACTIVE` services, with different names and different desired counts.

**Hints**

Step 10 contains every command. The only interesting question is which values change and which must
not - and note that the verification script from Section 9 does not check for the *absence* of extra
services, so this exercise will not make it fail.

---

### Exercise 2 - Intermediate: a new revision, and a deployment that does not drop traffic

**Requirements**

The enrolment service needs more headroom per task before Lab 06 puts it under load-based scaling.
Register `usms-enrolment:2` from a copy of `templates/lab-04-taskdef.json` with `memory` raised from
`512` to `1024` MiB (still a valid pair for `cpu: 256`) and a new environment variable
`USMS_LOG_LEVEL=info` added to the container. Update `usms-enrolment-svc` to run the new revision, wait
for it to stabilise, and confirm revision 1 is still describable even though nothing is running it.

**Constraints**

- Do not edit `templates/lab-04-taskdef.json` in place without keeping a copy of the version that
  produced revision 1 - task definitions are immutable for a reason, and your own template file should
  behave the same way.
- Use `aws ecs wait services-stable` or the manual polling loop from Step 10, not a fixed `sleep`.
- State, in one sentence, what `taskDefinition` field on the service changes and what does not.

**Expected outcome**

`describe-services` shows `taskDefinition` ending in `:2`; `describe-task-definition --task-definition
usms-enrolment:1` still succeeds and still reports `ACTIVE`, because deregistering is a separate action
this exercise does not take.

**Hints**

Step 9 is the template for writing and registering a revision. The service update itself is one call:
`aws ecs update-service --cluster ... --service ... --task-definition usms-enrolment:2`. The genuinely
new thinking is in the one-sentence answer: a task definition revision is immutable, but a service's
*pointer* to one is not.

---

### Exercise 3 - Problem solving: an ECS configuration drift report

**Requirements**

Write `scripts/utilities/lab-04-ecs-inventory.sh`. For every service in `usms-ecs-cluster`, it prints
one line:

```text
usms-enrolment-svc   desired=2  running=2  taskdef=usms-enrolment:2  roles=SEPARATE  publicip=OK
usms-results-svc     desired=1  running=1  taskdef=usms-enrolment:2  roles=SEPARATE  publicip=OK
usms-legacy-svc      desired=3  running=3  taskdef=usms-legacy:1     roles=SAME      publicip=RISK
```

The verdicts must be **computed**, never taken from a name or a tag:

| Column | Verdict | When |
| --- | --- | --- |
| `roles` | `SAME` | `executionRoleArn` equals `taskRoleArn` |
| `roles` | `SEPARATE` | They differ |
| `publicip` | `RISK` | `assignPublicIp` is `ENABLED` |
| `publicip` | `OK` | `assignPublicIp` is `DISABLED` |

**Constraints**

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as the Section 9
  script does.
- No hard-coded service name anywhere - list services from the cluster, then describe each one.
- Must not crash when a service has no `networkConfiguration` (an `EC2` launch type service, for
  example). Print `publicip=N/A` rather than an error.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- Also write the same data as JSON to `outputs/lab-04-ecs-inventory.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-04-ecs/`,
correctly classifying `usms-enrolment-svc` and every service created by earlier exercises.

**Hints**

`aws ecs list-services --cluster ... --query 'serviceArns[]'` gives you the list to iterate. The awkward
part is not the shell, it is deciding what "no data" means for each column and printing something
explicit rather than an empty field - an inventory that silently omits a risky service is worse than
one that never ran.

---

### Exercise 4 - Challenge: the enrolment week capacity plan

**Requirements**

The USMS project lead writes:

> Enrolment opens Monday 08:00 and the first twenty minutes are 90 percent of the week's traffic. Last
> year the service fell over for eleven minutes at 08:03 and the Registrar noticed. Finance has also
> noticed that we run the same fixed capacity at 3am on a Sunday in July.
>
> I know we are putting this under auto scaling next session, but before you touch a single API call I
> want your plan on paper: what capacity should we run, when, what should trigger a change, and what
> does it cost. Tell me specifically why a service that never changes its desired count cannot answer
> this, and what you would tell the team building the scaling policies to aim for.

Produce a written analysis in `labs/lab-04-ecs/exercises.md` covering:

- **Why a fixed `desiredCount` of 2 cannot answer the 08:03 problem**, in terms of what this lab
  actually built: `usms-enrolment-svc` has no mechanism that reads a metric or a clock, so the only way
  its capacity ever changes is a human running `update-service`.
- **A proposed plan** with concrete numbers for a minimum, a maximum, and a rough shape for a scheduled
  floor around the enrolment window - and for each number, one sentence saying what it costs you if it
  is too high and what it costs you if it is too low. You are not implementing any of this; you are
  handing it to whoever does Lab 06.
- **A monthly cost comparison** of at least two options: fixed at your proposed peak capacity, versus
  fixed at today's 2. Use current Fargate per-vCPU-hour and per-GB-hour prices, and **cite where you got
  them**.
- **What to switch off**, with the exact commands in the correct dependency order, each preceded by the
  four-line danger admonition used throughout this lab: the Exercise 1 results service.

Then execute only the deletion, and confirm `./scripts/utilities/verify-lab-04.sh` reports `FAIL=0`
afterwards.

**Constraints**

- Do not delete anything in Section 16's KEEP column.
- Every number must have a source or a derivation. "About 10 tasks" earns nothing; "10 tasks, because
  200 requests per second at 25 requests per task per second plus one task of headroom" earns full marks.

**Expected outcome**

An analysis a project lead could act on and a finance team could check, plus a repository in which the
Exercise 1 practice resource is gone and the verification still passes.

**Hints**

You will not have a policy or a scalable target to point at, and that is deliberate - the exercise asks
for the reasoning Lab 06 will later encode into numbers, not for the encoding itself. Section 5.2's
capacity plan and Section 12.2's cost figures are your starting point.

---

### Exercise 5 - Integration: close the loop back to Lab 3, and hand Lab 05 what it needs

**Requirements**

Step 8 wrote a security group rule whose source is a *group*, not an address. This exercise resolves
that group reference back to the instance that carries it - the only way to show that the rule grants
access to something real rather than to a group nobody uses - and records the result somewhere Lab 05
can read it, because Lab 05's cutover step removes this exact rule and should not do so blind.

1. Resolve `usms-enrolment-sg`'s only inbound source group back to the running instance that carries it,
   the same reverse lookup Lab 3 Step 11 and this lab's own security groups depend on:
   `aws ec2 describe-instances --filters "Name=instance.group-id,Values=<group>"
   "Name=instance-state-name,Values=running"`.
2. Confirm that instance matches `$USMS_WEB_INSTANCE` from `configs/lab-03.env`. If it does not, work
   out why (a relaunch, or a second instance carrying the group from an earlier "Your turn" task) and say
   so rather than treating a mismatch as success.
3. Write `outputs/lab-04-lab03-linkage.txt` containing: the source group ID, the instance it resolves to,
   the `LOOP CLOSED` or `MISMATCH` verdict, and one sentence stating that this rule is temporary - Lab 05
   removes it once the load balancer becomes the only caller.
4. Audit everything this lab tagged `Project=USMS`, using `aws ecs list-tags-for-resource` against the
   cluster ARN and the service ARN from `configs/lab-04.env`, and append the result to the same file.

**Constraints**

- `aws ecs list-tags-for-resource` takes an **ARN**, not a name - unlike almost every other ECS call in
  this lab, which take `--cluster` and `--service` names.
- If any ECS resource shows no tags at all, note it: some Floci builds accept `--tags` on
  `create-cluster` and `create-service` and do not store them. Fix what you can with
  `aws ecs tag-resource --resource-arn <arn> --tags key=Project,value=USMS` and record the rest.

**Expected outcome**

A committed file that a reader of Lab 05 could open before running Lab 05's cutover step and know
exactly what is about to change and why it is safe to change it.

**Hints**

`--filters "Name=instance.group-id,Values=..."` is a reverse lookup you will use again whenever you are
about to change or delete a group and need to know what would be affected. The whole point of this
exercise is that Lab 05 is about to delete the very rule you are documenting here - read Lab 05's
Section 1 before you start, and you will see why this file matters to someone other than you.

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
- [ ] `usms-enrolment-svc` is `ACTIVE`, spans two private subnets, `assignPublicIp` `DISABLED`, desired
      count 2
- [ ] `usms-enrolment-sg` admits tcp/80 from `usms-app-sg` by group reference and nothing from
      `0.0.0.0/0`

**Evidence**

- [ ] Step 11's "Your turn" task recorded: `desiredCount` moved to 3 and back to 2, with the service's
      `events` list as evidence
- [ ] Exercise 5's `outputs/lab-04-lab03-linkage.txt`, with a `LOOP CLOSED` verdict or an explained
      mismatch
- [ ] Screenshots in `screenshots/` for Checkpoints 2, 3 and 4

**Hygiene and written work**

- [ ] `configs/lab-04.env` exists, is committed, has 17 exports and no empty values or `None`
- [ ] `scripts/utilities/verify-lab-04.sh` exists and reports `FAIL=0` (or its documented benign
      failures, each explained)
- [ ] `scripts/cleanup/lab-04-cleanup.sh` exists, passes `bash -n`, and has not been run
- [ ] `git status --short` shows nothing under `outputs/`
- [ ] `git check-ignore -v outputs/lab-04-assumed-role.json` names the rule and line
- [ ] `notes/lab-04-notes.md` answers all review questions in prose
- [ ] `labs/lab-04-ecs/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding - answer these out loud before you submit**

- [ ] I can name ECS's four objects and say which one a scaling policy will change, without this lab
      having built a scaling policy
- [ ] I can say, from the interlude before Step 6, which failure symptom points at the execution role
      and which points at the task role
- [ ] I can explain why the enrolment security group's rule names a group and not a CIDR block, and why
      that choice matters even before Lab 06 exists
- [ ] I can say what Fargate removed from the EC2 model in Lab 3, and what it did not remove

---

## 15. Review Questions

Answer in prose, in your own words, in `notes/lab-04-notes.md`. No command output - these ask whether
you understood, not whether you typed.

1. A colleague says "I put auto scaling on the task definition." Explain, in three or four sentences,
   every way that sentence is wrong: name what auto scaling will actually be attached to in Lab 06, what
   it actually modifies, and which of ECS's four objects does the work of making reality match. Then say
   what observable consequence follows from the fact that ECS itself will know nothing about the
   scalable target.

2. Lab 1 wrote `USMSStudentDataReadWrite` for a bucket that did not exist. Lab 3 attached it to an EC2
   instance via an instance profile. This lab attached the same policy, unchanged, to a Fargate task via
   a task role. Explain in a full paragraph what each of the two delivery mechanisms actually does at
   runtime, why neither needs a key on disk, and precisely what changes for **both** the moment a bucket
   finally exists at that ARN. This is the most important connection in the course; answer it properly.

3. The interlude before Step 6 distinguishes the task **execution** role from the task **role**. Give a
   one-sentence failure symptom for each that a colleague could use to tell them apart without reading
   any documentation, and explain why both roles share an identical trust policy despite doing
   completely different jobs.

4. Step 8 sources the enrolment security group's only inbound rule from `usms-app-sg`, not from a CIDR
   block. Explain why this choice would still be correct even if this service's task count never
   changed, and then explain the additional reason it becomes close to mandatory once Lab 06 lets the
   task count change on its own.

5. Explain what Fargate removes from the EC2 model this course used in Lab 3, and what it explicitly does
   not remove. Use the fact that a Fargate task in `awsvpc` mode still has its own security group and
   still obeys Lab 2's route tables to make the second half of the answer concrete.

6. Lab 1 Step 14 proved that "the account identity is unchanged after a restart" is not evidence of
   persistence, because the root ARN is a constant regardless of storage mode. Apply the same scepticism
   here: name one command against this lab's own resources that would look identical whether Floci is
   running in `memory` mode or `hybrid` mode, and one command that would not, and explain the difference.

---

## 16. What We Built

### 16.1 Reflection

Three labs built things of a fixed size. This one built the first thing whose size is a *number a
service tracks* rather than a fact about a machine - and the interesting part is how little of the work
was about containers.

The idea to keep is the separation between ECS's four objects. A cluster is a namespace. A task
definition is an immutable blueprint. A task is one running instance of that blueprint. A service is the
controller that keeps a count of tasks matching `desiredCount`. Every later scaling mechanism in this
course, starting with Lab 06, does exactly one thing to exactly one of those four objects: it writes a
number into the service. Nothing about that indirection needed a scaling policy to exist in order to be
true, which is why it belongs in this lab and not the next one.

The second idea is the IAM chain that keeps reappearing. Lab 1 wrote a policy for a bucket that did not
exist. Lab 3 attached it to an EC2 instance. This lab attached the same policy, unchanged, to a Fargate
task through a completely different mechanism - a task role instead of an instance profile - and neither
mechanism needed a key on disk. The chain is the lesson, not the bucket.

The third is a discipline this course keeps returning to. Every command in this lab reported success,
and success alone was never the evidence that mattered: Step 9's verify step distinguished a task
definition with two different role ARNs from one that accidentally reused the same role for both, and
Step 11 taught you to read `desiredCount`, `runningCount` and `pendingCount` as three separate facts
rather than one. **A command that appears to succeed is still not evidence that it did what you meant.**

And one connection worth naming out loud. Lab 2 built a NAT gateway and could not demonstrate that it
mattered. This lab put tasks in a private subnet and needed it - three Lab 2 resources sit on the path
between a Fargate task and the container registry, and had any of them been wrong, the failure would
have surfaced here, a lab and a fortnight away from its cause.

### 16.2 KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ══════════════════════════╗    ╔════════════ CLEAN UP ═══════════════╗
║ usms-ecs-cluster            the namespace              ║    ║ outputs/lab-04-assumed-role.json    ║
║ usms-enrolment (family)     the blueprint              ║    ║   - expired after 1 hour;           ║
║ usms-enrolment-svc          Lab 05 and Lab 06 need it  ║    ║   delete it, it is dead weight      ║
║ usms-enrolment-sg           references usms-app-sg     ║    ║                                     ║
║ usms-ecs-exec-role          + USMSECSTaskExecution     ║    ║ usms-results-svc                    ║
║ usms-ecs-task-role          a later lab resolves it    ║    ║   - Exercise 1 practice;            ║
║ /usms/ecs/enrolment         the log group              ║    ║   remove it in Exercise 4           ║
║ configs/lab-04.env          Lab 05 and Lab 06 source it║    ║                                     ║
║ templates/lab-04-taskdef.json  the reviewable artefact ║    ║ AWS_ACCESS_KEY_ID and friends       ║
║ scripts/utilities/verify-lab-04.sh                     ║    ║   - unset them; Step 4 part 3 did   ║
║ everything from Labs 01, 02 and 03                     ║    ║                                     ║
╚════════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted:

```bash
rm -f outputs/lab-04-assumed-role.json
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
git status --short
```

Do **not** run `scripts/cleanup/lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are
for the end of the course, and in reverse dependency order.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and in Lab 04 Step 4
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for a later lab
  USMSStudentDataReadWrite ............. now on TWO roles, naming a bucket that still does not exist

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b   -> usms-public-rt  -> usms-igw
    private : usms-private-subnet-a / -b  -> usms-private-rt -> usms-nat
                                                             -> usms-s3-endpoint
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-private-nacl

Lab 03  COMPUTE - fixed size
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> the EC2 Auto Scaling lab, which is NOT this lab (see 12.3)

Lab 04  COMPUTE - deployed, standing still                       <-- you are here
  usms-ecs-cluster
    usms-enrolment-svc   desired 2, both private subnets, usms-enrolment-sg
      usms-enrolment:1   exec role + task role

Lab 05  (next)  a load balancer in front of usms-enrolment-svc
Lab 06  (after that)  Application Auto Scaling on usms-enrolment-svc
```

---

## 17. Preparation for the Next Lab

Lab 05 is next, and it is the lab where `usms-enrolment-svc` stops being unreachable. Right now the
service runs two tasks with no stable address and no name a client could ever be given; Lab 05 puts an
Application Load Balancer and a target group in front of it, and the ECS service itself keeps that
target group's membership up to date as tasks come and go. Lab 06, immediately after, is the one that
finally lets `desiredCount` move on its own.

| From `configs/lab-04.env` | Lab 05 uses it for |
| --- | --- |
| `USMS_ECS_CLUSTER` / `USMS_ENROLMENT_SERVICE` | Attaching the existing service to a new target group, rather than creating a second service |
| `USMS_ENROLMENT_SG` | The security group Lab 05's cutover step edits, once the load balancer is the only caller |
| `USMS_ENROLMENT_CONTAINER` | Naming which container in the task definition receives traffic from the load balancer |

| From `configs/lab-04.env` | Lab 06 uses it for |
| --- | --- |
| `USMS_ECS_DESIRED_BASELINE` | The floor of the scalable target Lab 06 registers - see Section 12.3 |
| `USMS_ECS_TASK_CPU` / `USMS_ECS_TASK_MEMORY` | Sizing the arithmetic behind Lab 06's target tracking policy |

| From earlier labs | Lab 05 uses it for |
| --- | --- |
| Lab 2 `usms-public-subnet-a` / `-b` | The two Availability Zones an internet-facing load balancer requires |
| Lab 2 `usms-app-sg` | Explaining, by contrast, why the load balancer gets its own security group rather than reusing the web tier's |
| Lab 3 `usms-web-01` | The instance Exercise 5 of this lab resolved `usms-enrolment-sg`'s source group to |

**Before the next session, confirm all three of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-04.sh
grep -c '^export' configs/lab-04.env
aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].{Desired:desiredCount,Running:runningCount}' --output json
```

You want `FAIL=0`, a count of **17**, and `Desired` equal to `Running` (or the container-start
limitation from Section 12, recorded rather than fought).

**Read ahead, five minutes:** find out what an Application Load Balancer's *target type* means for a
Fargate service, and why it cannot be `instance`. Lab 05 Step 6 explains it in full; knowing the shape
of the answer before you get there will save you re-reading the step twice.

Finally, take a snapshot so that a mistake in Lab 05 is recoverable:

```bash
floci snapshot save lab-04-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback. Stop Floci first -
archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-04.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-04.tar.gz
```

The archive lives in your home directory, outside the repository, so it is never a commit candidate.

---

## Appendix A - Command Reference

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
| `aws ecs describe-tasks` | Read tasks, including `stoppedReason` - the first place to look |
| `aws ecs list-tags-for-resource` | Read tags; takes an **ARN**, not a name |
| `aws ecs tag-resource` | Add tags to an existing ECS resource |

### Amazon CloudWatch Logs

| Command | What it does |
| --- | --- |
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
| `aws ec2 create-security-group` | Create the task security group |
| `aws ec2 authorize-security-group-ingress` | `--ip-permissions file://...` for a group-referenced rule |
| `aws ec2 describe-instances --filters Name=instance.group-id` | Reverse lookup: who carries this group |

**Three tag conventions in one lab, and no rule connects them:**

| Service | Syntax |
| --- | --- |
| EC2 | `--tag-specifications 'ResourceType=x,Tags=[{Key=K,Value=V}]'` |
| ECS | `--tags key=K,value=V` (lower case) |
| IAM | `--tags Key=K,Value=V` (capitals, no `ResourceType`) |
| CloudWatch Logs | `--tags K=V` (a plain map) |

Run `aws <service> <operation> help` and read the `--tags` synopsis. That habit is more durable than any
of the four.

---

## Appendix B - New JMESPath and CLI patterns introduced

Labs 1 to 3 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `Tags[?Key==...]|[0].Value`, `--filters`, `--generate-cli-skeleton`, `--cli-input-json`
and `aws <service> wait`. This lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `options."awslogs-group"` | Double quotes inside a JMESPath expression, for a key containing a hyphen - otherwise read as subtraction | Step 9 |
| `--max-items N` | Client-side pagination: stop after N items and return a `NextToken` | Step 3 |
| `--starting-token` | Resume a paginated call from a previous `NextToken` | Step 3 note |
| `--filters "Name=instance.group-id,Values=..."` | EC2 reverse lookup: which instances carry a security group | Exercise 5 |
| `awsvpcConfiguration={subnets=[a,b],securityGroups=[c],assignPublicIp=DISABLED}` | Nested shorthand: no spaces, no quotes around the IDs | Step 10 |

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
- [Amazon ECS CloudWatch Container Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights.html)
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [`aws ecs` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/)
- [JMESPath specification](https://jmespath.org/specification.html)

---

*Lab 04 complete. Lab 05 puts `usms-enrolment-svc` behind an Application Load Balancer; Lab 06, right
after it, hands `desiredCount` over to Application Auto Scaling.*


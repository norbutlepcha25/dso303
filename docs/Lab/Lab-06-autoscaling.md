# Lab 04C — Implementing Auto Scaling for an ECS-Based Application

*Practical 3 — handing the enrolment service's capacity to Application Auto Scaling, and proving that
something other than you moved it*

---

## 1. Lab Overview

Practical 2 built a container platform and gave it a front door. At the end of Part B you had an ECS
service running two Fargate tasks in private subnets, an Application Load Balancer in front of them,
and a target group that the service keeps up to date without being asked.

One number in that architecture has never moved on its own: `desiredCount`. In Lab 04A Step 16 you
typed `4`, watched `pendingCount` lag behind, and typed `2` again. In Lab 04B Step 11's "Your turn"
you typed `3` and then `2`. Both times the capacity changed because a human decided it should.

This laboratory replaces the human. **Application Auto Scaling** — a separate AWS service from ECS,
with its own API, its own vocabulary and its own IAM identity — will watch a metric, decide that the
enrolment service needs more or fewer tasks, and write `desiredCount` for you.

The single most important idea to leave with is how little that involves:

```text
Application Auto Scaling writes ONE INTEGER.

It does not start tasks. It does not talk to containers. It does not know what your
application does, whether it is healthy, or that a load balancer exists. It reads a
metric, compares it with a target, and writes desiredCount.

Everything after that is machinery you have already built:
  ECS starts a task -> the task gets an ENI in a Lab 02 subnet
                    -> the service registers its address in Lab 04B's target group
                    -> the load balancer health-checks it
                    -> it receives traffic
```

Students who hold on to that sentence find auto scaling almost anticlimactic, which is the correct
reaction. Students who imagine it as a mysterious orchestrator spend an afternoon looking for the part
of it that starts containers, and there isn't one.

The emphasis of this lab is in its title: **implementing**. Registering a scalable target is one
command. What takes four hours is choosing a metric that means something, choosing a target value you
can defend, understanding the two CloudWatch alarms a target tracking policy creates behind your back,
writing a step scaling policy for the cases target tracking cannot express, adding scheduled scaling
for the spike you already know about, suspending all of it during an incident, and — the part that
matters most — **proving that something other than you moved the number.**

**Time:** roughly 4 hours, including the exercises.

**Where this sits in the course**

```text
Lab 01   IAM ................. roles, policies, instance profile
Lab 02   VPC ................. subnets, NAT, route tables, security groups
Lab 03   EC2 ................. usms-web-01 and usms-db-01 in that network
Lab 04A  ECS + Fargate ....... the cluster, the blueprint, the service, and how to operate them
Lab 04B  ECS + ALB ........... the front door, and Practical 2's in-class assessment
Lab 04C  Service Auto Scaling  THIS LAB — the same service, made elastic
Lab 05   S3 .................. the bucket that two IAM policies already name
Lab 06   Lambda .............. functions triggered from that bucket
```

!!! info "This document supersedes `lab-04-ecs-autoscaling.md`, and three cross-references have moved"
    An earlier edition of this material was a single document, `lab-04-ecs-autoscaling.md`, written
    before Practical 2 was split into Parts A and B. In that edition, Steps 4 to 11 built the ECS
    cluster, the task definition and the service — work that now belongs to Lab 04A — and the scaling
    began at its Step 12.

    This document builds only the scaling. Its steps therefore run from 1, as §8's numbering rule
    requires, and three sentences in the earlier documents no longer resolve:

    | Where | What it says | What is true now |
    | --- | --- | --- |
    | Lab 04B, end of §17 | "skip to its Step 12: Steps 4 to 11 are Part A" | Start at Step 1 and do every step. Nothing here repeats Part A |
    | Lab 04B, §17 | "Lab 04C's Step 12 registers a scalable target with a minimum of 2" | That is **Step 5** of this document |
    | Lab 04A §1 and Lab 04B §1 | "Lab 04C ... `lab-04-ecs-autoscaling.md`" | This file is `lab-04c-ecs-autoscaling.md`, matching the `04a` and `04b` naming |

    One consequence reaches into your repository, and Step 17 deals with it: the cleanup scripts Labs
    04A and 04B already shipped print a message telling you to run `scripts/cleanup/lab-04-cleanup.sh`
    first. This lab ships `scripts/cleanup/lab-04c-cleanup.sh`. Neither of those scripts *executes* the
    name it prints, so nothing is broken — but a printed instruction that names a file which does not
    exist is a defect, and §11 has the one-line repair.

    Read that table once and forget it. Everything else in Labs 04A and 04B is accurate.

!!! info "The row Lab 04B unlocked"
    The earlier edition of this lab scaled on CPU utilisation and said, in its own text, that requests
    per target would be a better signal for a web API and that it could not use one because the course
    had no load balancer.

    Lab 04B built one. Step 9 of this lab creates the request-count policy that was previously
    impossible, using the `ResourceLabel` string Lab 04B's Exercise 5 asked you to derive. If you
    skipped that exercise, Step 9 derives it for you and explains what it is made of.

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. Explain what Application Auto Scaling is, name the one thing it changes on an ECS service, and list
   three things it does **not** do.
2. Distinguish **ECS service auto scaling** from **ECS cluster auto scaling** and from **EC2 Auto
   Scaling groups**, and say which of the three the golden AMI from Lab 3 belongs to.
3. Construct the three-part address of a scalable target — service namespace, resource ID and scalable
   dimension — and explain why the resource ID is a constructed string rather than an ARN.
4. Register a scalable target with a minimum and maximum capacity, and predict what registering it does
   to a service that is currently below the minimum.
5. Explain what the service-linked role `AWSServiceRoleForApplicationAutoScaling_ECSService` is for, and
   why you never write its trust policy yourself.
6. Create a **target tracking** scaling policy, choose a target value you can defend, and explain what
   `ScaleOutCooldown` and `ScaleInCooldown` each protect against.
7. Find the two CloudWatch alarms a target tracking policy created on your behalf, read them, and say
   why you must not edit or delete them by hand.
8. Explain why `ALBRequestCountPerTarget` is a better scaling signal than CPU for a web API, name the one
   case where CPU is better, and build the `ResourceLabel` string it requires.
9. Create a **step scaling** policy with more than one step adjustment, and describe a requirement that
   target tracking cannot express.
10. Attach a CloudWatch alarm to a scaling policy, and read the alarm's `AlarmActions` to prove the
    attachment.
11. Create **scheduled** scaling actions with a `cron` schedule expression, and explain the difference
    between the schedule's time zone and the resources' region.
12. Fire an alarm deliberately and read `describe-scaling-activities` to prove that something other than
    you changed `desiredCount`.
13. Suspend and resume dynamic and scheduled scaling independently, and say why leaving one suspended is
    a silent fault.
14. Explain why reactive scaling can never fully absorb a spike, and quantify the gap using a figure you
    measured yourself in Lab 04A or Lab 04B.
15. Prove that the scalable target, all three policies, both scheduled actions and the custom alarm
    survive a restart of the emulator, deriving every identifier from the API.

---

## 3. Prerequisites

- **Lab 04A complete**, with `usms-ecs-cluster`, the `usms-enrolment` family and `usms-enrolment-svc` as
  Part A left them.
- **Lab 04B complete**, with `./scripts/utilities/verify-lab-04b.sh` reporting `FAIL=0` **before you
  start this lab**. Run it now, not at the end.
- **`verify-lab-04a.sh` reporting either `FAIL=0` or exactly the one documented failure** on the
  `usms-app-sg` source check. Lab 04B Step 13 caused that failure deliberately and Lab 04B's Exercise 2
  repairs it; either state is acceptable here, and any *other* failure is not.
- **The service at its baseline**: `desiredCount` of 2, exactly one deployment. Step 5 registers a
  scalable target with a minimum of 2 and will raise the capacity immediately if it finds the service
  below that, which is a confusing way to discover you left it at 1.
- **Errata 01 applied.** If `echo "$AWS_PROFILE"` in a brand-new terminal prints nothing, stop and apply
  Errata 01 first — every command in this lab would otherwise fail with a credentials error that names
  the wrong cause.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq` and `python3` available. `python3` is used for every timestamp in this lab, because GNU `date` and
  BSD `date` disagree about every flag that matters and half this class is on macOS.

Check all of that in one go:

```bash
cd ~/aws-floci-course
for t in jq python3 docker; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
./scripts/utilities/floci-storage-check.sh
```

> Example output — your versions and paths will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
aws-cli/2.17.42 Python/3.11.9 Darwin/23.5.0 exe/x86_64
...
PASS=16  FAIL=0
```

**What to look for:** three tools found, and `PASS=16  FAIL=0` from the storage check. A failure in that
script's `shell and profile` block is the real problem and everything below it is a consequence — fix
that block before starting.

!!! tip "One number from an earlier lab that this lab will keep asking you for"
    Lab 04A Exercise 5 asked you to measure how long a scale-out actually takes in your environment, and
    Lab 04B Exercise 5 asked you to measure how long a full capacity replacement takes. Have those two
    figures — or the AWS-documented Fargate start-up figure you cited instead — to hand.

    Every cooldown in this lab is chosen relative to them. A `ScaleOutCooldown` shorter than the time it
    takes a task to become useful is a policy that scales out twice for one event, and the only way to
    know whether yours is is to know that number.

    ```bash
    cat outputs/lab-04a-scale-latency.txt 2>/dev/null || echo "not measured — use the cited figure"
    cat outputs/lab-04b-lab04c-readiness.txt 2>/dev/null | grep -i elapsed || true
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
- Lab 04A: usms-ecs-cluster, Container Insights enabled
- Lab 04A: /usms/ecs/enrolment log group, retention 7 days
- Lab 04A: usms-ecs-exec-role (+ USMSECSTaskExecution), usms-ecs-task-role (+ Lab 01's S3 policy)
- Lab 04A: usms-enrolment:1 and usms-enrolment:2, two immutable revisions
- Lab 04A: usms-enrolment-svc, desired 2, both private subnets, no public address
- Lab 04A: configs/lab-04a.env, scripts/utilities/verify-lab-04a.sh
- Lab 04B: usms-alb-sg, usms-enrolment-alb (internet-facing, public subnets a + b)
- Lab 04B: usms-enrolment-tg (target-type ip), the HTTP:80 listener, the /alb-health rule
- Lab 04B: usms-enrolment-svc attached to the target group; grace period 60s
- Lab 04B: usms-enrolment-sg cut over to usms-alb-sg only
- Lab 04B: configs/lab-04b.env, scripts/utilities/verify-lab-04b.sh

Created in this lab:
- AWSServiceRoleForApplicationAutoScaling_ECSService   the identity that writes desiredCount
- a SCALABLE TARGET   service/usms-ecs-cluster/usms-enrolment-svc
                      dimension ecs:service:DesiredCount, min 2, max 10
- usms-enrolment-cpu-target-tracking        target tracking, ECSServiceAverageCPUUtilization, 50
- usms-enrolment-requests-target-tracking   target tracking, ALBRequestCountPerTarget, 1000
- usms-enrolment-queue-step-out             step scaling, two step adjustments
- usms-enrolment-queue-high                 CloudWatch alarm on a custom metric, driving that policy
- usms-enrolment-morning-scale-out          scheduled action, weekday mornings
- usms-enrolment-evening-scale-in           scheduled action, weekday evenings
- USMS/Enrolment EnrolmentQueueDepth        a custom CloudWatch metric, published by hand
- templates/lab-04c-target-tracking-cpu.json, templates/lab-04c-target-tracking-requests.json,
  templates/lab-04c-step-scaling-out.json, templates/lab-04c-suspended-state.json
- configs/lab-04c.env
- scripts/utilities/verify-lab-04c.sh
- scripts/cleanup/lab-04c-cleanup.sh

Required for future labs:
- the scalable target      -> the CloudWatch lab reads its scaling activities and its managed alarms
- usms-enrolment-queue-high -> the CloudWatch lab replaces set-alarm-state with a real alarm action
- USMS/Enrolment metric    -> the CloudWatch lab graphs it and builds a dashboard from it
- configs/lab-04c.env      -> the CloudFormation lab re-declares every object in it as a template
- outputs/lab-04c-scaling-history.json (Exercise 5) -> Lab 05's first put-object needs a real file
- usms-ecs-task-role       -> Lab 05 creates the bucket its attached policy already names
```

### 4.2 What this lab genuinely reuses

Not mentions — uses.

| From | Used here how |
| --- | --- |
| Lab 04A `usms-ecs-cluster` and `usms-enrolment-svc` | Step 5 builds the scalable target's resource ID out of these two names, derived from the service's own ARN |
| Lab 04A `USMS_ECS_DESIRED_BASELINE` | Step 5 uses it as the scalable target's `MinCapacity`. The floor is 2 because Lab 04A Step 13 argued for one task per Availability Zone |
| Lab 04A Container Insights | Step 7's CPU policy reads a metric that exists only because Lab 04A Step 4 turned that setting on. If it is off, Step 7 says what you get instead |
| Lab 04A `usms-enrolment:2` | Untouched. This lab registers no revision and changes no blueprint. Step 15 says so out loud |
| Lab 04B `usms-enrolment-tg` and `usms-enrolment-alb` | Step 9's `ResourceLabel` is built from fragments of **both** their ARNs |
| Lab 04B `USMS_ALB_RESOURCE_LABEL` | Step 9 uses it directly if Lab 04B's Exercise 5 produced it, and derives it if not |
| Lab 04B `healthCheckGracePeriodSeconds` | Step 12 explains why a task that ASA just created is not useful capacity for another 60 seconds |
| Lab 02 `usms-private-subnet-a` and `-b` | Step 15 traces where a task created by a scaling policy actually appears, and Exercise 4 works out how many will fit |
| `configs/course.env` names | `$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT` used, never redeclared |

### 4.3 The sentence that makes this lab worth doing

Lab 04A Step 16 had you change `desiredCount` by hand and watch `pendingCount` sit at a number for a
while before `runningCount` caught up. The lab asked you to hold on to that feeling.

This is what it was for. **A reactive scaling policy cannot make capacity appear before it observes the
load.** By the time a metric has been published, aggregated over a period, compared with a threshold,
and turned into an alarm state change, and by the time ECS has started a task and the load balancer has
health-checked it, the better part of two or three minutes has gone — and every second of that is
served by the capacity you already had.

That is not a flaw in the implementation. It is arithmetic, and it has three consequences that shape
every decision in this lab:

- **Your minimum capacity is not a cost decision, it is a latency decision.** Whatever you set as the
  floor is what absorbs the first two minutes of any spike.
- **Scale-out should be eager and scale-in reluctant.** That asymmetry is why `ScaleOutCooldown` is 60
  seconds in this lab and `ScaleInCooldown` is 300.
- **For a spike you already know about, reactive scaling is the wrong tool.** Enrolment week starts at a
  time printed in the university calendar. Step 11 is the answer to that, and it is the one form of
  scaling that can have capacity ready *before* the load arrives.

Say the first sentence out loud before you continue. It is Review Question 5.

### 4.4 What changes, and what deliberately does not

| | Before this lab | After this lab |
| --- | --- | --- |
| Who writes `desiredCount` | You, with `update-service` | Application Auto Scaling, or you |
| `desiredCount` baseline | 2 | 2, with a floor of 2 and a ceiling of 10 |
| Task definition | `usms-enrolment:2` | unchanged. No new revision is registered |
| Service `loadBalancers` | one entry | unchanged |
| Tasks' subnets | private a and b | unchanged |
| Tasks' public address | none | still none |
| `usms-enrolment-sg` ingress | tcp/80 from `usms-alb-sg` | unchanged |
| Target group membership | maintained by the service | unchanged, and now it changes more often |
| CloudWatch alarms in the account | none of yours | two per target tracking policy, created by AWS, plus one you wrote |

Read the third row and the last row together. This lab adds a great deal of behaviour and changes
almost nothing about the objects that behaviour acts on. That is the shape of a well-separated system,
and it is worth noticing while you can still see the seams.

---

## 5. What We Are Building

Three kinds of scaling on one service, plus the ability to switch all of them off without deleting any
of them.

Five decisions justify the shape of what follows, and each is defensible in one sentence.

**The floor is 2 and the ceiling is 10.** The floor comes from Lab 04A: one task per Availability Zone,
so that losing a zone costs half the capacity rather than all of it. The ceiling is a guard against a
runaway policy, a metric that has gone mad, and a bill nobody authorised — and Exercise 4 asks you to
check it against how many addresses Lab 02's private subnets actually have.

**CPU is the policy we start with and requests is the policy we prefer.** CPU is available from
Container Insights, which Lab 04A enabled, and it is the metric almost every tutorial uses. Requests per
target measures the thing the service is actually for. Step 9 adds it, and Review Question 7 asks you to
say when CPU is nonetheless the better of the two.

**Scale out fast, scale in slowly.** `ScaleOutCooldown` of 60 seconds against `ScaleInCooldown` of 300.
Scaling out too eagerly costs money; scaling in too eagerly costs availability, and the second mistake is
the expensive one. Note that this is an asymmetry you have to choose: the AWS default for both is 300
seconds.

**Step scaling exists for the requirement target tracking cannot express.** Target tracking answers "keep
this metric near this number". It cannot answer "if the backlog is a bit high add one task, and if it is
enormous add three", because that is a function rather than a set point. Step 10 builds exactly that, on
a custom metric, and the custom metric is also what makes the scaling *observable* on an emulator.

**Scheduled scaling is the only one that can be early.** Enrolment opens at 08:00. A reactive policy
learns about it at 08:02. A scheduled action raises the floor at 07:45 and the first student to click
"Register" finds the capacity already there.

### 5.1 The scaling baseline this lab establishes

```text
scalable target      service/usms-ecs-cluster/usms-enrolment-svc
                     ecs:service:DesiredCount     min 2   max 10
target tracking 1    ECSServiceAverageCPUUtilization    target 50    out 60s  in 300s
target tracking 2    ALBRequestCountPerTarget           target 1000  out 60s  in 300s
step scaling         USMS/Enrolment EnrolmentQueueDepth
                       backlog  100 to 200  -> +1 task
                       backlog  200 and up  -> +3 tasks
                     cooldown 60s, ChangeInCapacity, Average
scheduled            weekday 07:45 Asia/Thimphu   min 4   max 10
                     weekday 20:00 Asia/Thimphu   min 2   max 10
suspension           all three switchable independently, none left suspended
```

Every one of those is a decision with a reason, and Exercise 4 asks you to defend a completely different
set for a three-week enrolment window.

---

## 6. Architecture

```text
                              Internet
                                  |
                                  v
  ================================|=========================================
  ||  usms-vpc  10.0.0.0/16       |                                       ||
  ||   +--------------------------+--------------------------------+      ||
  ||   | usms-public-subnet-a / -b    usms-enrolment-alb           |      ||
  ||   |   usms-alb-sg   listener HTTP:80                          |      ||
  ||   |     rule 10  /alb-health -> fixed 200                     |      ||
  ||   |     default              -> usms-enrolment-tg             |      ||
  ||   +--------------------------+--------------------------------+      ||
  ||                              |                                      ||
  ||        tcp/80 from usms-alb-sg ONLY                                  ||
  ||                              v                                      ||
  ||   +----------------------+   +----------------------+               ||
  ||   | usms-private-        |   | usms-private-        |               ||
  ||   |   subnet-a  AZ a     |   |   subnet-b  AZ b     |               ||
  ||   | [ task ] [ task ]    |   | [ task ] [ task ]    |  <- 2 .. 10   ||
  ||   +----------------------+   +----------------------+               ||
  ||                              ^                                      ||
  ||   ECS control plane          | ECS starts and stops tasks to make    ||
  ||     usms-ecs-cluster         | runningCount match desiredCount       ||
  ||       usms-enrolment-svc     |                                       ||
  ||         desiredCount  <------+------------------------------+        ||
  ||         loadBalancers[0] -> usms-enrolment-tg               |        ||
  ||         healthCheckGracePeriodSeconds 60                    |        ||
  =============================================================|==========
                                                               |
                          THE ONLY THING THIS LAB ADDS         | writes ONE integer
                                                               |
  Application Auto Scaling                                     |
  +------------------------------------------------------------|--------+
  | scalable target                                            |        |
  |   namespace          ecs                                   |        |
  |   resource id        service/usms-ecs-cluster/usms-enrolment-svc     |
  |   dimension          ecs:service:DesiredCount  -------------+        |
  |   min 2   max 10                                                    |
  |                                                                     |
  |   usms-enrolment-cpu-target-tracking       TargetTrackingScaling    |
  |     AWS/ECS CPUUtilization -> target 50                             |
  |     +-- TargetTracking-...-AlarmHigh   created FOR you              |
  |     +-- TargetTracking-...-AlarmLow    created FOR you              |
  |                                                                     |
  |   usms-enrolment-requests-target-tracking  TargetTrackingScaling    |
  |     AWS/ApplicationELB RequestCountPerTarget -> target 1000          |
  |     ResourceLabel app/usms-enrolment-alb/<id>/targetgroup/...        |
  |                                                                     |
  |   usms-enrolment-queue-step-out            StepScaling              |
  |     driven by an alarm YOU wrote:                                   |
  |       usms-enrolment-queue-high                                     |
  |         USMS/Enrolment EnrolmentQueueDepth >= 100                   |
  |         AlarmActions -> this policy's ARN                           |
  |                                                                     |
  |   usms-enrolment-morning-scale-out   cron weekdays 07:45  min 4     |
  |   usms-enrolment-evening-scale-in    cron weekdays 20:00  min 2     |
  |                                                                     |
  |   suspended state   DynamicScalingIn / DynamicScalingOut /          |
  |                     ScheduledScaling   — three independent switches |
  +---------------------------------------------------------------------+

  Identity
  +---------------------------------------------------------------------+
  | AWSServiceRoleForApplicationAutoScaling_ECSService                  |
  |   a SERVICE-LINKED role. You create it by NAME and never write its  |
  |   trust policy. It is what holds ecs:UpdateService on your behalf.  |
  +---------------------------------------------------------------------+
```

Read the arrow labelled "writes ONE integer" once more before you start. Every box in the Application
Auto Scaling panel exists to decide what that integer should be. Not one of them touches a container.

---

## 7. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-04c-ecs-autoscaling/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 13
├── templates/
│   ├── lab-04c-target-tracking-cpu.json               # NEW — put-scaling-policy config
│   ├── lab-04c-target-tracking-requests.json          # NEW — the ALB metric config
│   ├── lab-04c-step-scaling-out.json                  # NEW — step adjustments
│   └── lab-04c-suspended-state.json                   # NEW — register-scalable-target config
├── configs/
│   └── lab-04c.env                                    # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-04c.sh                          # NEW — Section 9
│   └── cleanup/
│       └── lab-04c-cleanup.sh                         # NEW — end of course only
└── outputs/
    └── lab-04c-*.json / *.txt                         # command output, git-ignored
```

Note what is **not** here: no new file under `policies/`. Every document this lab writes is an **API
request body** — a scaling policy configuration, a suspended-state structure — and none of them grants
or denies anything. The one identity this lab needs is a service-linked role whose policy AWS writes and
owns, which is the whole point of a service-linked role and is Step 4's subject.

That distinction is worth keeping sharp. A reviewer opening `policies/` should be looking at your
security posture and nothing else, and a scaling policy is not a security policy despite sharing a word
with one.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-04c-ecs-autoscaling
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04a-ecs-fargate
labs/lab-04b-ecs-alb  labs/lab-04c-ecs-autoscaling
```

---

## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Every path below (`configs/...`, `templates/...`, `scripts/...`) is relative to that directory. If a
    command reports `No such file or directory`, check `pwd` first.

    One habit, restated because this lab's central identifier is a string you build rather than an ID you
    are given: **capture every identifier with `$(...)`, `--query` and `--output text`, and never type
    one by hand.** Shell variables die with the terminal, which is why Step 16 writes them all to
    `configs/lab-04c.env`.

### Step 1 — Resume the environment and load six env files

**Purpose**

Bring Floci up and load everything the previous five labs recorded. This lab reads nine values from
`configs/lab-04a.env` and `configs/lab-04b.env`, and two of them — the load balancer ARN and the target
group ARN — are the halves of a composite string Step 9 cannot build without them.

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
source configs/lab-04b.env

./scripts/utilities/whoami.sh

printf '%-28s %s\n' \
  "cluster"              "$USMS_ECS_CLUSTER" \
  "service"              "$USMS_ENROLMENT_SERVICE" \
  "baseline desired"     "$USMS_ECS_DESIRED_BASELINE" \
  "container"            "$USMS_ENROLMENT_CONTAINER" \
  "task cpu / memory"    "$USMS_ECS_TASK_CPU / $USMS_ECS_TASK_MEMORY" \
  "private subnet a"     "$USMS_PRIVATE_SUBNET_A" \
  "private subnet b"     "$USMS_PRIVATE_SUBNET_B" \
  "load balancer"        "$USMS_ALB_NAME" \
  "load balancer arn"    "$USMS_ALB_ARN" \
  "target group"         "$USMS_TG_NAME" \
  "target group arn"     "$USMS_TG_ARN" \
  "grace period"         "$USMS_SVC_GRACE_PERIOD" \
  "region"               "$AWS_REGION_COURSE" \
  "account"              "$ACCOUNT_ID"
```

**What the command does**

`floci-up.sh` is idempotent: it starts the container if it is stopped, says so if it is already running,
and refuses to adopt a container that Compose did not create. `whoami.sh` exits 1 if the account is not
`000000000000`, which is the guard that stops a course command reaching a real AWS account.

Six env files is the standard opening from here on. They are additive and independent: sourcing them in
any order gives the same result, because no two of them define the same variable.

The `printf` is not decoration. Five of those values are consumed by commands later in this lab, and an
empty one produces an API error whose message names a malformed parameter rather than a missing variable.

**Expected result**

```text
[floci-up] container 'floci' already running (compose project: floci-course)

Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Profile  : floci

cluster                      usms-ecs-cluster
service                      usms-enrolment-svc
baseline desired             2
container                    enrolment-api
task cpu / memory            256 / 1024
private subnet a             subnet-09876fedcba543210
private subnet b             subnet-0aabbccdd11223344
load balancer                usms-enrolment-alb
load balancer arn            arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
target group                 usms-enrolment-tg
target group arn             arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
grace period                 60
region                       us-east-1
account                      000000000000
```

> Example output — your IDs and ARN suffixes will differ.

**Verify**

Fourteen non-empty values. Three specific failures matter more than the rest:

- **`baseline desired` empty or not `2`** means `configs/lab-04a.env` recorded something other than the
  baseline. Step 5 uses this value as the scalable target's minimum, and a minimum of 4 recorded by
  accident is a decision you did not make.
- **`target group arn` empty** means `configs/lab-04b.env` was never written or is incomplete. Re-run
  Lab 04B Step 18 before continuing; Step 9 cannot proceed without it.
- **`grace period` empty or `None`** means Lab 04B's Step 10 attachment did not fully take. It changes
  nothing in Steps 1 to 11, and it changes Step 12's arithmetic, which is where it would confuse you.

---

### Step 2 — Confirm Labs 02, 03, 04A and 04B are still intact

**Purpose**

A week may have passed since Practical 2. This lab attaches scaling to a service whose configuration it
never modifies, which means every fault in that service will present itself as a fault in the scaling.
Confirm the foundation before adding anything on top of it.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
./scripts/utilities/verify-lab-02.sh  | tail -3
./scripts/utilities/verify-lab-03.sh  | tail -3
./scripts/utilities/verify-lab-04a.sh | tail -3
./scripts/utilities/verify-lab-04b.sh | tee outputs/lab-04c-pre-verify-04b.txt | tail -3

echo "== the one failure that is allowed, and only this one =="
./scripts/utilities/verify-lab-04a.sh | grep FAIL || echo "no failures in 04A"
```

**What the command does**

Each script checks its own lab's resources and, first, the shared environment. All four were written in
their own labs; you are only running them.

The fourth is captured into `outputs/` on purpose. Nothing in this lab modifies Lab 04B's objects, so a
`verify-lab-04b.sh` run at the end must produce the same result as this one — and having the "before" on
disk turns that from an opinion into a `diff`.

**Expected result**

```text
PASS=33  FAIL=0
PASS=36  FAIL=0
PASS=48  FAIL=1
PASS=49  FAIL=0
== the one failure that is allowed, and only this one ==
  FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
```

> Example output. If you completed Lab 04B's Exercise 2, the third line reads `PASS=50  FAIL=0` — the
> count changed because that exercise added a check — and the last block prints `no failures in 04A`.
> Both are correct.

**Verify**

`FAIL=0` from Labs 02, 03 and 04B, and from Lab 04A either `FAIL=0` or exactly the single documented
failure on the `usms-app-sg` source check. That failure is Lab 04B Step 13 doing its job; anything else
failing is a real problem and this lab will make it harder to see, not easier.

A failure under `== Environment ==` in any of the four is the real problem and the resource failures
below it are usually consequences. Fix the environment first with
`./scripts/utilities/floci-storage-check.sh`.

Now confirm the one piece of *state*, rather than configuration, that Step 5 depends on:

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments),LBs:length(loadBalancers)}' \
  --output json
```

**What to look for:** `Desired` is `2`, `Deployments` is `1`, `LBs` is `1`. If `Desired` is anything else,
put it back with `aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service
"$USMS_ENROLMENT_SERVICE" --desired-count 2` before going on. Registering a scalable target against a
service that is not at its intended baseline is how you spend twenty minutes wondering which of the two
things changed the number.

---

### Step 3 — Probe what this Floci build supports

**Purpose**

Find out now which parts of Application Auto Scaling and CloudWatch your build implements, rather than
discovering it at Step 12 with three policies built and nothing to show. This is the same principle as
Lab 04A Step 3 and Lab 04B Step 3: **name the limitation before it costs you an hour.**

Application Auto Scaling is a small API — nine operations matter — but it depends on CloudWatch for
everything it decides, so this probe covers both.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
probe() {
  printf '%-52s ' "$1"
  if eval "$2" >/dev/null 2>&1; then echo "SUPPORTED"; else echo "not available"; fi
}

echo "== Application Auto Scaling =="
probe "describe-scalable-targets"                 "aws application-autoscaling describe-scalable-targets --service-namespace ecs"
probe "register-scalable-target (skeleton)"       "aws application-autoscaling register-scalable-target --generate-cli-skeleton"
probe "describe-scaling-policies"                 "aws application-autoscaling describe-scaling-policies --service-namespace ecs"
probe "put-scaling-policy (skeleton)"             "aws application-autoscaling put-scaling-policy --generate-cli-skeleton"
probe "describe-scheduled-actions"                "aws application-autoscaling describe-scheduled-actions --service-namespace ecs"
probe "describe-scaling-activities"               "aws application-autoscaling describe-scaling-activities --service-namespace ecs"

echo "== CloudWatch, which is where every decision comes from =="
probe "cloudwatch describe-alarms"                "aws cloudwatch describe-alarms --max-items 1"
probe "cloudwatch put-metric-alarm (skeleton)"    "aws cloudwatch put-metric-alarm --generate-cli-skeleton"
probe "cloudwatch put-metric-data (skeleton)"     "aws cloudwatch put-metric-data --generate-cli-skeleton"
probe "cloudwatch set-alarm-state (skeleton)"     "aws cloudwatch set-alarm-state --generate-cli-skeleton"
probe "cloudwatch list-metrics"                   "aws cloudwatch list-metrics --max-items 1"

echo "== IAM and ECS, already used in Labs 1 to 4B =="
probe "iam create-service-linked-role (skeleton)" "aws iam create-service-linked-role --generate-cli-skeleton"
probe "ecs describe-services"                     "aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE"
probe "elbv2 describe-target-groups"              "aws elbv2 describe-target-groups --names $USMS_TG_NAME"
```

**What the command does**

`probe` runs a harmless read, or generates a request skeleton, and reports whether the CLI got an answer
at all. Read the result as "the service responded to me", not "the call succeeded". A completely
unsupported service produces a connection error or `InvalidAction`, which reads differently from a
validation error about an argument.

Note that `describe-scalable-targets --service-namespace ecs` with no other argument is a legitimate
call that returns an empty list right now. An empty list is a *successful* answer and is exactly what
you should see: nothing is registered yet.

`--generate-cli-skeleton` is used four times here, and it is the right probe for a write operation you
do not want to perform yet. It is answered by the CLI's own service model, so a `SUPPORTED` on a skeleton
means "your CLI knows this operation exists", not "the emulator implements it" — which is why the read
operations are probed as well.

**Expected result**

```text
== Application Auto Scaling ==
describe-scalable-targets                            SUPPORTED
register-scalable-target (skeleton)                  SUPPORTED
describe-scaling-policies                            SUPPORTED
put-scaling-policy (skeleton)                        SUPPORTED
describe-scheduled-actions                           SUPPORTED
describe-scaling-activities                          SUPPORTED
== CloudWatch, which is where every decision comes from ==
cloudwatch describe-alarms                           SUPPORTED
cloudwatch put-metric-alarm (skeleton)               SUPPORTED
cloudwatch put-metric-data (skeleton)                SUPPORTED
cloudwatch set-alarm-state (skeleton)                SUPPORTED
cloudwatch list-metrics                              SUPPORTED
== IAM and ECS, already used in Labs 1 to 4B ==
iam create-service-linked-role (skeleton)            SUPPORTED
ecs describe-services                                SUPPORTED
elbv2 describe-target-groups                         SUPPORTED
```

> Example output — this is the best case. Yours may differ, and that is exactly why the probe exists.

**Verify**

Work out which path you are on and write it at the top of `notes/lab-04c-notes.md`, because your lab
report has to say so.

| Path | If | What changes |
| --- | --- | --- |
| **A — full** | Every Application Auto Scaling call answers, and `set-alarm-state` at Step 12 actually moves `desiredCount` | Do every step as written. You will see auto scaling work end to end |
| **B — control plane only** | The objects are created and describable, but `describe-scaling-activities` stays empty and `desiredCount` never moves on its own | Everything in this lab still works. Every proof except Step 12's is built on control-plane fields. Step 12 has a documented fallback that proves the *wiring* instead, and you record which one you got |
| **C — no Application Auto Scaling** | `describe-scalable-targets` does not answer, or `register-scalable-target` fails with `InvalidAction` | Stop and tell your instructor. Do Section 8's interludes, Exercises 4 and 5, and Section 15 — Exercise 4 is the part of this lab that needs no emulator at all, and it is the part a real employer would care most about |

!!! note "Floci Limitation — the scaling loop may be modelled without being closed"
    Application Auto Scaling on real AWS is a control loop: CloudWatch aggregates a metric, an alarm
    changes state, the alarm invokes a scaling policy, the policy calls `ecs:UpdateService`, and a
    scaling *activity* is recorded. Five services have to cooperate.

    Floci builds may implement the objects — targets, policies, scheduled actions — without running the
    loop that connects them. The most likely outcome is that everything you create is stored and
    describable, no alarm ever fires by itself, and `describe-scaling-activities` returns an empty list.
    Some builds do honour `set-alarm-state` and will move the number for you.

    Real AWS evaluates every alarm once a minute, invokes the policy within seconds of a state change,
    and records an activity with a cause string that names the alarm.

    Take this away regardless: **nothing this lab asks you to prove requires the loop to run**, with the
    single exception of Step 12, which tries it, tells you honestly when it did not work, and gives you a
    control-plane proof of the same wiring. Claiming a scaling activity you did not observe is worth
    negative marks.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01 + lab-02 + lab-03 + lab-04a + lab-04b sourced
 ├── verify-lab-02/03/04b all FAIL=0; verify-lab-04a FAIL=0 or the ONE documented failure
 ├── outputs/lab-04c-pre-verify-04b.txt captured, for comparison at the end
 ├── service at its baseline: desired 2, one deployment, one load balancer
 └── support path recorded: A (full) / B (control plane only) / C (no ASA)
```

---

### Interlude — what Application Auto Scaling is, in three objects

Three nouns. Lab 04A had four for ECS and Lab 04B had four for load balancing; this service is smaller,
which is a good sign about how much it does.

**A scalable target** is the thing that can be scaled, and it is not the ECS service. It is a
*registration*: a statement that says "this particular dimension of this particular resource in this
particular service namespace may be moved, and only between these two numbers". Registering it changes
nothing about the resource except that it now has a floor and a ceiling. Deregistering it changes nothing
except that it does not.

**A scaling policy** is a rule for deciding what the number should be. There are two kinds in
Application Auto Scaling — target tracking and step scaling — and they answer different questions. A
policy is attached to exactly one scalable target, and one target can have several policies.

**A scheduled action** is a change to the floor, the ceiling, or both, at a stated time. It is not a
policy: it does not read a metric and it does not decide anything. It is a calendar entry.

```text
scalable target      service/usms-ecs-cluster/usms-enrolment-svc
                     ecs:service:DesiredCount        min 2 .. max 10
       |
       +-- scaling policy   usms-enrolment-cpu-target-tracking
       |       reads a metric, computes a desired capacity, writes it
       |
       +-- scaling policy   usms-enrolment-queue-step-out
       |       is INVOKED BY AN ALARM, applies a step adjustment
       |
       +-- scheduled action usms-enrolment-morning-scale-out
               at 07:45 on weekdays, raise MinCapacity to 4
```

And one object that is not in that list and does most of the work: **a CloudWatch alarm**. Every
reactive decision in Application Auto Scaling is made by an alarm. For step scaling you write the alarm
yourself and attach the policy to it. For target tracking AWS writes two alarms on your behalf and
attaches them for you — which is convenient right up until the day you find them in the console, do not
recognise them, and delete them. Step 8 exists so that day never comes.

### Interlude — the three-part address of a scalable target, and why it is not an ARN

To name a scalable target you need three strings, and none of them is an ARN.

| Part | Value here | What it is |
| --- | --- | --- |
| **Service namespace** | `ecs` | Which AWS service owns the resource. Also `dynamodb`, `lambda`, `rds`, `elasticache`, `sagemaker`, `appstream`, `comprehend`, `kafka`, `neptune`, `cassandra`, `custom-resource` |
| **Resource ID** | `service/usms-ecs-cluster/usms-enrolment-svc` | A *constructed* string whose shape is defined per namespace |
| **Scalable dimension** | `ecs:service:DesiredCount` | Which property of that resource may be moved |

The resource ID is the part that surprises people, and it is worth understanding rather than memorising.
Application Auto Scaling scales things in nine different services, whose resources are named in nine
different ways: a DynamoDB table, a Lambda function alias, an Aurora replica, a SageMaker endpoint
variant. A single generic API cannot take "an ARN" and know what to do with it, so instead each namespace
defines a small path-shaped grammar:

```text
ecs         service/<cluster-name>/<service-name>
dynamodb    table/<table-name>   or  table/<table-name>/index/<index-name>
lambda      function:<function-name>:<alias-name>
rds         cluster:<cluster-name>
```

The ECS form is, deliberately, **exactly the suffix of the service's ARN**:

```text
arn:aws:ecs:us-east-1:000000000000:service/usms-ecs-cluster/usms-enrolment-svc
                                   |-------------------------------------------|
                                   this part, and nothing else, is the resource ID
```

That is why Lab 04A Step 13 told you to look hard at the shape of the service ARN it printed. It is also
why passing the *whole* ARN to `--resource-id` seems reasonable and is wrong: the call is rejected with a
validation error about the resource ID's format, and the message does not tell you that you gave it too
much.

The scalable dimension is the third part and the easiest to get wrong by being nearly right.
`ecs:service:DesiredCount` is the only dimension ECS offers, and it is case-sensitive in a way that looks
like a typo when you get it wrong: `ecs:service:desiredCount` is rejected.

You have now met four constructed identifiers in this architecture, and this is the fourth:

```text
ECS control-plane calls     --cluster usms-ecs-cluster --service usms-enrolment-svc
ECS tagging calls           --resource-arn arn:aws:ecs:...:service/usms-ecs-cluster/usms-enrolment-svc
ELB request-count metric    ResourceLabel  app/<lb-name>/<lb-id>/targetgroup/<tg-name>/<tg-id>
Application Auto Scaling    --resource-id  service/usms-ecs-cluster/usms-enrolment-svc
```

Four ways of naming things that all live in one architecture. Being able to build each one from the
right ARN, rather than guessing, is a genuinely useful skill and is Review Question 2.

### Interlude — three policy types here, and a fourth that is somewhere else

| Mechanism | Answers | You supply | AWS supplies |
| --- | --- | --- | --- |
| **Target tracking** | "Keep this metric near this number" | A metric and a target value | Two alarms, the arithmetic, and the capacity |
| **Step scaling** | "When this alarm fires, apply this adjustment — and a bigger one if it is worse" | An alarm and a table of steps | The invocation |
| **Scheduled** | "At this time, change the floor and the ceiling" | A schedule and new bounds | The clock |
| **Predictive** | "Look at the last two weeks and have capacity ready before the pattern repeats" | A metric | A forecast — **but not for ECS** |

The fourth row is the one worth being precise about, because it is a common interview trap. Predictive
scaling exists in the **EC2 Auto Scaling** service, for Auto Scaling groups of instances. Application
Auto Scaling — the service in this lab — does not offer it for ECS services. If you want anticipatory
capacity for a container service, the tool is a scheduled action, and Step 11 is where you get one.

Choosing between the first two is not a matter of taste:

- **Target tracking** is right when your metric has a natural set point. "Average CPU near 50 per cent",
  "1000 requests per task". You cannot express a non-linear response with it, and you should not try.
- **Step scaling** is right when the response is a function of how bad things are, or when the signal is
  not a utilisation at all — a queue depth, a backlog, an error rate. It is also the only one of the two
  in which *you* own the alarm, which matters when the alarm has to do something else as well, such as
  notify a human.

Use target tracking by default. Reach for step scaling when you can say, in one sentence, what target
tracking cannot express about your requirement. Step 10 has such a sentence.

---

### Step 4 — Create the service-linked role that writes `desiredCount`

**Purpose**

Application Auto Scaling calls `ecs:UpdateService` on your behalf. Like every AWS service that acts on
your resources, it needs an identity to do it with — and this is the one case in the whole course where
you create a role without writing a trust policy, without writing a permissions policy, and without
choosing its name.

**Run from**

```text
aws-floci-course/
```

**Concept first — what a service-linked role is, and why it is not like Lab 1's roles**

Lab 1 created three roles and you wrote every part of each one: the trust policy naming a service
principal, and an attached permissions policy you had argued about. Lab 04A created two more the same
way.

A **service-linked role** is different in four ways, and each difference is deliberate:

| | A role you write (Labs 1 and 04A) | A service-linked role |
| --- | --- | --- |
| Name | Yours | Fixed by AWS: `AWSServiceRoleForApplicationAutoScaling_ECSService` |
| Trust policy | You write it | AWS writes it, and you cannot change it |
| Permissions | You attach a policy you wrote | An AWS-managed policy AWS owns and updates |
| Created by | `aws iam create-role` with `--assume-role-policy-document` | `aws iam create-service-linked-role --aws-service-name <the service>` |

The reason is worth understanding, because "AWS writes the policy" sounds like a loss of control and is
mostly the opposite. The permissions Application Auto Scaling needs on ECS are not a matter of opinion:
it needs `ecs:DescribeServices` and `ecs:UpdateService` on your services, plus a handful of CloudWatch
calls to manage the alarms it creates. Every account that uses ECS service auto scaling needs exactly
that set. Letting every customer write it by hand produces thousands of subtly wrong versions, and — the
part that actually bites — means that when the service gains a feature requiring one more permission,
every one of those thousands of policies is now out of date and the feature silently does not work.

The trade you are making is explicit: you give up the ability to write the policy, and in exchange you
give up the ability to get it wrong.

**Command — part 1, create it**

```bash
ASA_SLR="AWSServiceRoleForApplicationAutoScaling_ECSService"

aws iam create-service-linked-role \
  --aws-service-name ecs.application-autoscaling.amazonaws.com \
  --description "Allows Application Auto Scaling to change the desired count of USMS ECS services" \
  --query 'Role.[RoleName,Arn]' \
  --output text \
  || echo "not created — see the note below; this is often already present, and sometimes unsupported"
```

**What the command does**

```text
aws
 └── iam
      └── create-service-linked-role
           ├── --aws-service-name   the SERVICE PRINCIPAL, not a role name
           └── --description        the only field you get to choose
```

`--aws-service-name` takes a service principal — `ecs.application-autoscaling.amazonaws.com` — and note
what it is *not*. It is not `ecs.amazonaws.com`, which is ECS itself, and it is not
`application-autoscaling.amazonaws.com`, which is the generic form used by other namespaces. The
principal encodes *which* Application Auto Scaling integration you want, because the ECS one and the
DynamoDB one need different permissions and therefore get different roles. Getting this wrong produces
`InvalidInput: Service role name ... has been taken in this account` or a message about an unknown
service name, neither of which explains the distinction.

Two harmless failures are likely here and neither is a problem:

- **`InvalidInput` saying the role already exists.** Something created it earlier — possibly you, on a
  previous run. Service-linked roles are one per account per service, so this is idempotent by nature.
- **The whole operation being unsupported.** Some Floci builds do not implement
  `create-service-linked-role`. Since the same builds also do not enforce IAM, the absence changes
  nothing about whether the rest of this lab works.

**Command — part 2, read it back**

```bash
aws iam get-role --role-name "$ASA_SLR" \
  --query 'Role.{Name:RoleName,Arn:Arn,Path:Path,Trust:AssumeRolePolicyDocument.Statement[0].Principal.Service}' \
  --output json \
  || echo "role not present on this build — record it as a limitation and continue"

aws iam list-attached-role-policies --role-name "$ASA_SLR" \
  --query 'AttachedPolicies[].PolicyName' --output text 2>/dev/null || true
```

**Expected result**

```text
{
    "Name": "AWSServiceRoleForApplicationAutoScaling_ECSService",
    "Arn": "arn:aws:iam::000000000000:role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService",
    "Path": "/aws-service-role/ecs.application-autoscaling.amazonaws.com/",
    "Trust": "ecs.application-autoscaling.amazonaws.com"
}
AWSApplicationAutoscalingECSServicePolicy
```

> Example output — the attached policy name may differ or be absent on this build.

**Verify**

**What to look for:** the `Path`. Every role you have created in this course so far has been at `/`, the
account root path. This one is under `/aws-service-role/<service principal>/`, and that path is not
cosmetic — it is how IAM marks a role as belonging to a service rather than to you, and it is why
`aws iam delete-role` on it behaves differently from `delete-role` on `usms-ecs-task-role`. The correct
way to remove one is `aws iam delete-service-linked-role`, which asks the owning service whether it is
still in use first.

If the role is absent, write one sentence in `notes/lab-04c-notes.md` recording it, and continue. On real
AWS its absence would produce a very specific failure at Step 5 — `register-scalable-target` returning an
error about being unable to assume the service-linked role — and knowing that symptom is worth as much as
having the role.

!!! note "Floci Limitation — the role exists as a record, and nothing assumes it"
    On real AWS this role is what Application Auto Scaling actually uses. Every `UpdateService` call the
    service makes on your behalf is made with credentials from this role, and it appears in CloudTrail
    with the role's ARN as the invoker — which is how you answer "who scaled my service at 3am".

    Floci accepts any non-empty credentials and by default does not authorize requests against your IAM
    policies, so nothing here is assumed and nothing is enforced.

    Take this away regardless: when someone asks how an AWS service is allowed to modify your resources,
    the answer is always a role, and for most modern integrations it is a service-linked role whose name
    begins `AWSServiceRoleFor`. Being able to find it, read its path, and say who trusts it is the point
    of this step.

---

### Step 5 — Register the scalable target

**Purpose**

The registration. This is the object every policy and every scheduled action in the rest of the lab
attaches to, and it is where the floor of 2 and the ceiling of 10 live.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, build the resource ID from the API, not by hand**

```bash
SVC_ARN=$(aws ecs describe-services \
  --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].serviceArn' --output text)

echo "service arn : $SVC_ARN"

# The resource ID is exactly the ARN's final colon-separated field.
RID="${SVC_ARN##*:}"
echo "resource id : $RID"

# Validate it before using it. Three slash-separated segments, the first literally "service".
SEGMENTS=$(printf '%s' "$RID" | awk -F/ '{print NF}')
FIRST=$(printf '%s' "$RID" | cut -d/ -f1)

if [ "$SEGMENTS" = "3" ] && [ "$FIRST" = "service" ]; then
  echo "OK: 3 segments, first segment 'service'"
else
  echo "UNEXPECTED SHAPE ($SEGMENTS segments, first '$FIRST') — falling back to constructing it"
  RID="service/${USMS_ECS_CLUSTER}/${USMS_ENROLMENT_SERVICE}"
  echo "resource id : $RID"
fi

SDIM="ecs:service:DesiredCount"
```

**What the command does**

`"${SVC_ARN##*:}"` is shell parameter expansion: strip the **longest** prefix matching `*:`, leaving
everything after the final colon. You met the `##*/` form in Lab 04A Step 12 for pulling a task ID out
of an ARN; this is the same operator with a different delimiter, and choosing the delimiter correctly is
the whole trick. `#` would strip the *shortest* prefix and give you the wrong thing, and using `awk -F:`
would give the wrong thing too, because you want the last field and not a numbered one.

The validation is not defensive padding. ECS has two ARN formats: the modern long format,
`...:service/<cluster>/<service>`, and a legacy short format, `...:service/<service>`, which some
accounts and some emulator builds still emit. Only the long format's suffix is a valid Application Auto
Scaling resource ID. A short-format ARN would give you `service/usms-enrolment-svc`, two segments, which
`register-scalable-target` rejects with a validation error about the resource ID — and the error does not
mention ARN formats, so you would be looking in the wrong place. Checking the segment count costs one
line and turns a confusing failure into a message that names the cause.

!!! tip "If Lab 04A's Exercise 5 recorded this already, cross-check it"
    Lab 04A Exercise 5 point 4 asked you to add `USMS_SCALABLE_RESOURCE_ID` to `configs/lab-04a.env`,
    derived from the API. If you did that exercise, the two must agree:

    ```bash
    echo "derived here  : $RID"
    echo "from lab-04a  : ${USMS_SCALABLE_RESOURCE_ID:-<not recorded>}"
    ```

    Two identical strings is a nice moment: you derived the same value twice, a session apart, from the
    same source. A disagreement means the service was deleted and recreated in between — Lab 04B's
    Step 10 fallback path does exactly that — and the value derived *now* is the correct one.

**Command — part 2, register it**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --min-capacity "$USMS_ECS_DESIRED_BASELINE" \
  --max-capacity 10 \
  --tags Project=USMS,Name=usms-enrolment-scalable-target,Tier=app,Lab=04C \
  --query 'ScalableTargetARN' \
  --output text \
  || aws application-autoscaling register-scalable-target \
       --service-namespace ecs \
       --resource-id "$RID" \
       --scalable-dimension "$SDIM" \
       --min-capacity "$USMS_ECS_DESIRED_BASELINE" \
       --max-capacity 10
```

**What the command does**

```text
aws
 └── application-autoscaling            the SERVICE — note the hyphen, not "autoscaling"
      └── register-scalable-target      the OPERATION
           ├── --service-namespace      ecs
           ├── --resource-id            the constructed string from part 1
           ├── --scalable-dimension     ecs:service:DesiredCount
           ├── --min-capacity           the FLOOR. Nothing may take desiredCount below this
           ├── --max-capacity           the CEILING. Nothing may take it above this
           └── --tags                   a plain MAP — the sixth tag convention in three labs
```

Three things in that command deserve a sentence each.

**`aws application-autoscaling`, not `aws autoscaling`.** Those are two different services with two
different APIs. `aws autoscaling` is **EC2** Auto Scaling — launch templates, Auto Scaling groups,
instance refresh, and the predictive scaling from the interlude's fourth row. `aws application-autoscaling`
is the generic one that scales ECS services, DynamoDB tables and seven other things. Typing the wrong one
gives you a real command that does something else, which is a worse failure than a typo, and §12.3 is
about exactly this confusion.

**`--min-capacity` is not a suggestion.** It is enforced by Application Auto Scaling against everything
it does, and — this is the part worth remembering — **registering the target immediately raises
`desiredCount` if the service is below the floor.** A registration is not a passive declaration. Part 3
checks for exactly that.

**`--tags` is a plain map.** `Project=USMS,Name=...` with no `Key=`/`Value=` wrappers, like CloudWatch
Logs in Lab 04A Step 6 and unlike ECS, IAM, EC2 and Elastic Load Balancing. That is the sixth convention
across six services in three laboratories, and there is still no rule connecting them. The `||` fallback
in the command above exists because tag support on `register-scalable-target` is relatively recent: an
older CLI, or a build that has not implemented it, rejects the flag, and the second invocation registers
the target without tags. Run `aws application-autoscaling register-scalable-target help` and read the
`--tags` synopsis if you want to know which you have.

**Expected result**

```text
arn:aws:application-autoscaling:us-east-1:000000000000:scalable-target/0a1b2c3d4e5f6789
```

> Example output. On builds that do not return `ScalableTargetARN` the command prints nothing at all and
> exits 0, which is also fine — a successful registration has no required output, and Step 6 is where you
> confirm it rather than here.

**Verify**

```bash
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --resource-ids "$RID" \
  --query 'ScalableTargets[0].{Namespace:ServiceNamespace,Resource:ResourceId,Dimension:ScalableDimension,Min:MinCapacity,Max:MaxCapacity,Role:RoleARN,Created:CreationTime,Suspended:SuspendedState}' \
  --output json
```

**Expected result**

```json
{
    "Namespace": "ecs",
    "Resource": "service/usms-ecs-cluster/usms-enrolment-svc",
    "Dimension": "ecs:service:DesiredCount",
    "Min": 2,
    "Max": 10,
    "Role": "arn:aws:iam::000000000000:role/aws-service-role/ecs.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_ECSService",
    "Created": "2026-09-03T04:11:52.418000+00:00",
    "Suspended": {
        "DynamicScalingInSuspended": false,
        "DynamicScalingOutSuspended": false,
        "ScheduledScalingSuspended": false
    }
}
```

> Example output — your creation time will differ, and `Role` may be absent or empty on a build with no
> service-linked role.

**What to look for:** four things.

`Min` is `2` and `Max` is `10`. `Dimension` is exactly `ecs:service:DesiredCount`. `Role` names the
service-linked role from Step 4 — **you did not pass a role ARN**, and Application Auto Scaling filled it
in for you, which is the concrete payoff of Step 4 and the reason `--role-arn` is not in the command
above. And `Suspended` has three fields, all `false`, which is the object Step 13 manipulates and the
reason the verification script in Section 9 asserts that none of them was left `true`.

**Command — part 3, find out what registering it did to the service**

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments)}' \
  --output json
```

**What to look for:** `Desired` is still `2`. Registration is a no-op on a service that is already inside
its new bounds, and that is worth confirming rather than assuming — the claim "registering a scalable
target does not change your capacity" is only true when the service was already above the floor.

If you had left the service at 1, this is the command that would have shown you `Desired` jumping to 2
with `Pending` at 1, with no policy involved and no alarm having fired. That is Review Question 3, and
Step 2's insistence on the baseline was so that you would meet it as a fact rather than as a surprise.

---

### Step 6 — Change the bounds, and learn what a re-registration is

**Purpose**

Registering a scalable target is one command. *Managing* one means knowing that there is no
`update-scalable-target`, and that the way you change the bounds is to register again — which is a
different change model from anything you have met so far and worth one deliberate look.

**Run from**

```text
aws-floci-course/
```

**Concept first — three change models in three labs**

| Object | To change it you | Because |
| --- | --- | --- |
| A task definition (Lab 04A) | Register a **new revision**; the old one is untouched forever | It is a versioned blueprint, and rollback must be a pointer change |
| A target group's health check (Lab 04B) | `modify-target-group` — an in-place update, with some fields refused | Some of its configuration is identity and some is behaviour |
| A scalable target (here) | `register-scalable-target` again, with the new numbers | It is a *registration*, not a resource. There is only ever one per address, and re-registering replaces its contents |

The third is the one to think about. The target's identity is its three-part address — namespace,
resource ID, dimension — and that address is not something you can change; it names something else
entirely if you alter it. Everything that is *not* the address is content, and content is replaced
wholesale. So a second `register-scalable-target` on the same address is an update, and one on a
different address is a new target.

Two consequences follow, and both are practical:

- **Re-registering does not disturb your policies.** They attach to the address, and the address did not
  change. You can raise a ceiling in the middle of an incident without deleting anything.
- **Omitting a parameter does not clear it.** `register-scalable-target` with only `--max-capacity`
  leaves the minimum as it was. That is unusual — most replace-the-whole-thing APIs would null the field
  — and it is documented behaviour rather than something to rely on by accident.

**Command — part 1, raise the ceiling, then read it back**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --max-capacity 12 \
  >/dev/null

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].[MinCapacity,MaxCapacity]' --output text
```

**Expected result**

```text
2	12
```

> Example output.

**What to look for:** the minimum is still `2`. You passed only `--max-capacity`, and the floor survived.
That is the "omitting a parameter does not clear it" behaviour, observed rather than trusted.

**Command — part 2, put it back**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --min-capacity 2 \
  --max-capacity 10 \
  >/dev/null

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[].{Resource:ResourceId,Min:MinCapacity,Max:MaxCapacity}' \
  --output table
```

**Expected result**

```text
-------------------------------------------------------------------------------
|                          DescribeScalableTargets                            |
+-------+-------+-------------------------------------------------------------+
|  Max  |  Min  |                          Resource                           |
+-------+-------+-------------------------------------------------------------+
|  10   |  2    |  service/usms-ecs-cluster/usms-enrolment-svc                 |
+-------+-------+-------------------------------------------------------------+
```

> Example output.

**Verify**

Exactly **one** row, with `Min` 2 and `Max` 10. More than one row means you have registered a second
target at a slightly different address — almost always a typo in the dimension or a resource ID built by
hand — and the extra one will quietly do nothing while you wonder why your policies are not firing.

```bash
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'length(ScalableTargets)' --output text
```

That must print `1`. If it prints `2`, list them and deregister the wrong one — the danger admonition and
the exact commands are the last entry in Section 11.

✏️ **Your turn**

Work out, without running anything, what would happen if you re-registered this target with
`--min-capacity 5` while the service is running two tasks. Then do it, observe, and put it back to 2.

```text
Expected result:
desiredCount moves to 5 within seconds of the registration, with no scaling policy
involved and no alarm having fired. describe-scaling-activities may or may not record
it — find out which, on your build, and say so.

Then answer in one sentence each in notes/lab-04c-notes.md:
(a) Which object made that change: the scalable target, a scaling policy, or ECS?
(b) You are on call. A colleague raises MinCapacity to 5 to ride out an incident and
    goes to bed without telling anyone. What is the cost of that, and which single
    API call would have told you it had happened?
```

Hint: part 3 of Step 5 already showed you the shape of the answer to (a). For (b), one of the two
commands you have already run in this step returns the value a monitoring system would compare against
what it expected, and `CreationTime` is not the field you want.

**Checkpoint 2**

```text
Application Auto Scaling
 └── scalable target
      ├── namespace          ecs
      ├── resource id        service/usms-ecs-cluster/usms-enrolment-svc   (derived from the ARN)
      ├── dimension          ecs:service:DesiredCount
      ├── min 2  /  max 10   raised to 12 and put back, to see the change model
      ├── role               AWSServiceRoleForApplicationAutoScaling_ECSService, filled in for you
      ├── suspended state    three switches, all false
      └── policies           NONE YET — this target can be scaled and nothing decides to
```

That last line is not a mistake. A scalable target with no policies and no scheduled actions enforces its
bounds and nothing else. It is the load balancer with no listener from Lab 04B Step 5, in a different
service.

---

### Interlude — what target tracking actually does

Target tracking is described everywhere as "like a thermostat", which is accurate and not very useful.
Here is what it does mechanically, because the mechanics are what you will debug.

You give it one metric and one number. It then, on your behalf and without telling you:

1. **Creates two CloudWatch alarms.** A high alarm that fires when the metric is above the target, and a
   low alarm that fires when it is far enough below. Their names begin `TargetTracking-` followed by your
   resource ID.
2. **Attaches itself to both** as an alarm action, so the alarms invoke the policy.
3. **Computes a capacity, not an adjustment.** When the high alarm fires, it does not add a fixed number
   of tasks. It calculates how many tasks would be needed to bring the metric to the target, assuming the
   metric scales roughly linearly with capacity, and writes that number.

Point 3 is the one that distinguishes it from step scaling and the one that makes it feel intelligent.
With 4 tasks averaging 80 per cent CPU and a target of 50, the arithmetic is roughly
`4 x 80 / 50 = 6.4`, rounded up: 7 tasks. It got there in one move, where a step policy adding one task
at a time would have taken three evaluation cycles.

Three properties follow from that arithmetic and all three matter:

- **It only works on a metric that falls as capacity rises.** CPU per task, requests per target, memory
  per task: all fine. Total request count across the service is **not** — adding tasks does not reduce it,
  so the arithmetic runs away and the policy scales to the ceiling and stays there. That failure mode is
  the single most common target tracking mistake, and it is why the predefined metric is called
  `ALBRequestCountPerTarget` and not `ALBRequestCount`.
- **It never scales in past the point where the metric would exceed the target.** Scale-in is
  deliberately conservative: the policy only removes capacity when doing so still leaves the metric
  below target, which is why services under target tracking often sit slightly over-provisioned. That is
  the correct bias.
- **It respects the floor and the ceiling absolutely.** A computed capacity of 14 against a maximum of 10
  gives you 10, and the policy will keep saying 14 in its alarms while the target stays at 10 — which
  looks like the policy is broken and is in fact the ceiling doing its job. Section 11 has the diagnosis.

The two cooldowns are the last piece:

| Field | Value here | Protects against |
| --- | --- | --- |
| `ScaleOutCooldown` | 60 | Scaling out twice for one event, because the first new task has not started serving yet and the metric has not moved |
| `ScaleInCooldown` | 300 | Removing capacity you are about to need, on a metric that dipped for one minute |

Note what a cooldown is *not*: it is not a delay before acting. The policy acts immediately; the cooldown
governs how soon it may act **again in the same direction**. And note the asymmetry — the AWS default is
300 for both, and this lab deliberately makes scale-out five times more eager than scale-in, for the
reason given in §4.3.

The number to size `ScaleOutCooldown` against is the one you measured in Lab 04A Exercise 5: how long a
task takes to exist, plus Lab 04B's 60-second grace period before it counts as capacity. A cooldown
shorter than that sum is a policy that will scale out twice for one spike, every time.

---

### Step 7 — Create the CPU target tracking policy

**Purpose**

The first policy. It reads the metric Lab 04A's Container Insights setting publishes, and it is the one
almost every real ECS service starts with.

**Run from**

```text
aws-floci-course/
```

**Concept first — which metric, and where it comes from**

Application Auto Scaling offers three **predefined** metrics for the `ecs` namespace, and this is the
table Lab 04B promised you would come back to with its third row filled in:

| Predefined metric | CloudWatch source | Needs | Available to you? |
| --- | --- | --- | --- |
| `ECSServiceAverageCPUUtilization` | `AWS/ECS` `CPUUtilization` | Container Insights, per service | **Yes** — Lab 04A Step 4 enabled it |
| `ECSServiceAverageMemoryUtilization` | `AWS/ECS` `MemoryUtilization` | The same | **Yes** — and Exercise 1 uses it |
| `ALBRequestCountPerTarget` | `AWS/ApplicationELB` `RequestCountPerTarget` | A load balancer and a target group | **Yes, now** — Lab 04B built both. Step 9 |

"Predefined" means you name the metric type and AWS knows the namespace, the metric name, the dimensions
and the statistic. The alternative is a **customized** metric specification, in which you supply all five
yourself — namespace, metric name, dimensions, statistic and unit — and that is what Exercise 2's
extension explores.

The percentage in `CPUUtilization` for a Fargate task is worth being precise about, because it is not
what people assume. It is the task's CPU consumption as a percentage of the CPU it **reserved** in the
task definition, not of a physical core. Lab 04A's revision 2 reserves `256` CPU units, a quarter of a
vCPU. So 80 per cent CPU on one of these tasks means 80 per cent of a quarter of a vCPU — and if you had
sized the task at `1024` instead, the same real workload would report 20 per cent and no policy would
fire. **A CPU target is only meaningful relative to a reservation**, which is one of the two reasons the
next step's metric is better.

**Command — part 1, write the policy configuration**

```bash
cat > templates/lab-04c-target-tracking-cpu.json << 'EOF'
{
  "TargetValue": 50.0,
  "PredefinedMetricSpecification": {
    "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
  },
  "ScaleOutCooldown": 60,
  "ScaleInCooldown": 300,
  "DisableScaleIn": false
}
EOF

python3 -m json.tool templates/lab-04c-target-tracking-cpu.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-04c-target-tracking-cpu.json
```

**What the command does**

This heredoc is `<< 'EOF'`, **quoted**, because the document contains no variables and must reach disk
exactly as written. Contrast it with Step 9's document two steps from now, which contains a
`$RESOURCE_LABEL` and therefore **must** use the unquoted `<< EOF`. Two nearly identical files in the
same directory, opposite quoting, for opposite reasons — the fifth appearance of this contrast in three
laboratories, and still the most common silent bug in the course. The `grep -c '\$'` printing `0` is the
check, and here it must print `0` because there was nothing to expand.

Four fields, and each is a decision:

| Field | Value | Why |
| --- | --- | --- |
| `TargetValue` | `50.0` | Half the reservation. Room for a spike to be absorbed while the policy reacts, without paying for idle capacity. `70` would be defensible for a workload that scales gently; `30` for one that spikes violently |
| `PredefinedMetricType` | `ECSServiceAverageCPUUtilization` | The one metric that exists without extra work |
| `ScaleOutCooldown` | `60` | Slightly longer than one task's start-up plus the grace period, so one spike produces one scale-out |
| `ScaleInCooldown` | `300` | Five minutes. Removing capacity is the expensive mistake |
| `DisableScaleIn` | `false` | Stated explicitly although it is the default, because it is the field that turns this from a scaling policy into a scale-out-only policy, and a reader should not have to know the default to know what you meant |

`TargetValue` is a **float** in the JSON — `50.0`, not `"50"` and not `50`. An integer is accepted and
coerced, but a *string* is rejected with a message naming a type rather than a field. That is the same
class of trap as Lab 04A's `"cpu": "256"` and Lab 04B's `"StatusCode": "200"`, and note that the three
of them do not agree with each other: ECS wants strings where you expect numbers, ELBv2 wants a string
status code, and Application Auto Scaling wants a real number. There is no rule. Read the skeleton.

**Command — part 2, create the policy**

```bash
CPU_POLICY="usms-enrolment-cpu-target-tracking"

CPU_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$CPU_POLICY" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://templates/lab-04c-target-tracking-cpu.json \
  --query 'PolicyARN' \
  --output text)

echo "CPU_POLICY_ARN = $CPU_POLICY_ARN"
```

**What the command does**

```text
aws
 └── application-autoscaling
      └── put-scaling-policy
           ├── --service-namespace / --resource-id / --scalable-dimension   the TARGET's address
           ├── --policy-name        yours; unique per target
           ├── --policy-type        TargetTrackingScaling | StepScaling
           └── --target-tracking-scaling-policy-configuration  file://...
```

`put-scaling-policy` is a **create-or-replace**: running it again with the same name and a different
configuration updates the policy in place, and it neither versions nor complains. That makes tuning a
target value a one-command operation, and it makes an accidental overwrite completely silent — which is
why the configuration lives in a file in `templates/` that Git can show you the history of, rather than
in your shell history.

The four address parameters are repeated on every policy call, every scheduled action call, and every
delete. There is no "current target" and no shorthand. Application Auto Scaling is a stateless API over
a composite key, and this is what that feels like to use.

Note that the policy type and the configuration flag must agree. Passing
`--step-scaling-policy-configuration` with `--policy-type TargetTrackingScaling` is rejected, and the
message names the configuration rather than the type, so read it carefully when it happens.

**Expected result**

```text
valid JSON
0
CPU_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:0a1b2c3d-4e5f-6789-abcd-ef0123456789:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-cpu-target-tracking
```

> Example output — your UUID will differ.

Look hard at that ARN, because it is the strangest one in the course and it is about to be useful. It
contains, in order: the service (`autoscaling`, not `application-autoscaling` — the ARN namespace and the
CLI command name genuinely differ), a UUID, then `resource/ecs/` followed by **the whole resource ID**,
then `policyName/` and the name. The scalable target's three-part address is embedded in its policies'
ARNs, which is how CloudWatch can attach an alarm to a policy without knowing anything about ECS. Step 10
puts that ARN into an alarm and Step 12 reads it back out.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs \
  --resource-id "$RID" \
  --policy-names "$CPU_POLICY" \
  --query 'ScalingPolicies[0].{Name:PolicyName,Type:PolicyType,Metric:TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType,Target:TargetTrackingScalingPolicyConfiguration.TargetValue,Out:TargetTrackingScalingPolicyConfiguration.ScaleOutCooldown,In:TargetTrackingScalingPolicyConfiguration.ScaleInCooldown,NoScaleIn:TargetTrackingScalingPolicyConfiguration.DisableScaleIn,Alarms:Alarms[].AlarmName}' \
  --output json
```

**Expected result**

```json
{
    "Name": "usms-enrolment-cpu-target-tracking",
    "Type": "TargetTrackingScaling",
    "Metric": "ECSServiceAverageCPUUtilization",
    "Target": 50.0,
    "Out": 60,
    "In": 300,
    "NoScaleIn": false,
    "Alarms": [
        "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmHigh-1a2b3c4d-5e6f-7890-abcd-ef1234567890",
        "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmLow-9f8e7d6c-5b4a-3928-1706-abcdef012345"
    ]
}
```

> Example output — your alarm UUIDs will differ, and on some builds `Alarms` is an empty list.

**What to look for:** the `Alarms` list. **You did not create those.** They appeared as a side effect of
`put-scaling-policy`, they are named after your resource ID, and they are how this policy will ever hear
about anything. That list is the single most surprising output in this lab, and Step 8 is about it.

If `Alarms` is empty, record it as a limitation and continue. It changes nothing in Steps 9 to 11 and it
changes what Step 8 can show you, which Step 8 says.

---

### Step 8 — Read the two alarms that target tracking created for you

**Purpose**

Two CloudWatch alarms now exist in your account that you did not write. Find them, read them, and
understand them — because the alternative is finding them in six months, not recognising them, and
deleting them.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, find them**

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'MetricAlarms[].{Name:AlarmName,Metric:MetricName,Namespace:Namespace,Stat:Statistic,Period:Period,Evals:EvaluationPeriods,Op:ComparisonOperator,Threshold:Threshold,Actions:length(AlarmActions),State:StateValue}' \
  --output json
```

**Expected result**

```json
[
    {
        "Name": "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmHigh-1a2b3c4d-...",
        "Metric": "CPUUtilization",
        "Namespace": "AWS/ECS",
        "Stat": "Average",
        "Period": 60,
        "Evals": 3,
        "Op": "GreaterThanThreshold",
        "Threshold": 50.0,
        "Actions": 1,
        "State": "INSUFFICIENT_DATA"
    },
    {
        "Name": "TargetTracking-service/usms-ecs-cluster/usms-enrolment-svc-AlarmLow-9f8e7d6c-...",
        "Metric": "CPUUtilization",
        "Namespace": "AWS/ECS",
        "Stat": "Average",
        "Period": 60,
        "Evals": 15,
        "Op": "LessThanThreshold",
        "Threshold": 45.0,
        "Actions": 1,
        "State": "INSUFFICIENT_DATA"
    }
]
```

> Example output — the exact thresholds, periods and evaluation counts are AWS's to choose and have
> changed between versions. On a build that creates no managed alarms this returns an empty list.

**What the command does, and what to read in it**

Six things in that output are worth a sentence, and together they are the whole behaviour of a target
tracking policy.

**`Namespace` is `AWS/ECS` and `Metric` is `CPUUtilization`.** That is what "predefined" bought you: you
wrote `ECSServiceAverageCPUUtilization` and AWS resolved it into a namespace, a metric name, a statistic
and — not shown in this projection — the two dimensions `ClusterName` and `ServiceName`. Add
`Dimensions:Dimensions[].[Name,Value]` to the query and look at them; they are your cluster and your
service, which is how the alarm knows which of the account's ECS services it is about.

**`Evals` is 3 on the high alarm and 15 on the low one**, at a `Period` of 60. Multiply: the high alarm
needs the metric above target for **3 minutes** before it fires; the low alarm needs it below for
**15 minutes**. That asymmetry is baked into target tracking itself, on top of the cooldowns you chose —
so the real reluctance to scale in is 15 minutes of evaluation plus a 300-second cooldown, and the real
eagerness to scale out is 3 minutes plus 60. Nobody chose those two numbers; AWS did, and knowing them is
how you answer "why did it take so long to scale".

**The two thresholds differ** — 50 and 45 in the example. The low alarm's threshold sits below the
target to create a dead band, so that a metric hovering exactly at the target does not cause the policy
to scale out and in repeatedly. Without a dead band, every thermostat oscillates.

**`Actions` is 1 on each.** That one action is the policy ARN from Step 7. Confirm it:

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'MetricAlarms[].AlarmActions[]' --output text | tr '\t' '\n'
```

Every line should be your `$CPU_POLICY_ARN`. That is the link that closes the loop: metric to alarm to
policy to `desiredCount`.

**`State` is `INSUFFICIENT_DATA`.** On real AWS an alarm sits in that state until the metric has enough
datapoints, and a brand-new alarm on a brand-new policy will show it for a few minutes. It is not an
error and it does not need fixing. It *is* worth knowing that an alarm in `INSUFFICIENT_DATA` takes no
action at all — so a service whose metric has stopped being published is a service that will never scale,
in either direction, silently.

!!! warning "Do not edit or delete these alarms"
    They belong to the policy. Application Auto Scaling recreates them when the policy changes and
    deletes them when the policy is deleted, and it does not reconcile changes you make in between.

    Editing one gets you an alarm that will be overwritten without warning at the next
    `put-scaling-policy`. Deleting one gets you a policy that no longer scales in one direction, with no
    error anywhere and nothing in `describe-scaling-policies` to show that anything is wrong — the
    `Alarms` list still names the alarm, because that list records what the policy asked for rather than
    what exists.

    If you want different thresholds, change `TargetValue` or the cooldowns and let the policy rebuild
    them. If you want your own alarm with your own thresholds, that is step scaling, and it is Step 10.

    The one thing you *should* do with them is recognise them. An account with fifteen services under
    target tracking has thirty of these, and a colleague who does not know what `TargetTracking-` means
    will eventually try to tidy them up.

**Command — part 2, prove the naming is derivable**

```bash
echo "resource id            : $RID"
echo "managed alarm prefix   : TargetTracking-$RID"
aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'length(MetricAlarms)' --output text
```

**What to look for:** `2` — one high, one low, for one policy. After Step 9 adds a second target tracking
policy this becomes `4`, and after Exercise 1 adds a third it becomes `6`. Two alarms per target tracking
policy, always, and their names are derivable from a string you built in Step 5. That derivation is the
answer if the alarms are not returned on your build: write it out in `notes/lab-04c-notes.md` and say what
each of the two would have contained.

✏️ **Your turn**

Using only the numbers in the `describe-alarms` output above, work out on paper how long the enrolment
service would run at 100 per cent CPU before a third task started serving traffic. Then check your
arithmetic against the lab.

```text
Expected result:
A number of seconds, built from four separate delays, at least two of which are not in
this lab's own configuration. Write the four terms out.

Then answer in one sentence in notes/lab-04c-notes.md:
Which ONE of the four terms would you change first if that total were unacceptable, and
what would it cost you?
```

Hint: the first term is in the high alarm's `Period` and `EvaluationPeriods`. The second is the policy
invocation, which is seconds and can be treated as zero. The third is in Lab 04A Exercise 5's
measurement. The fourth is a field of the ECS service that Lab 04B Step 10 set, and the reason it exists
is that without it the task would be killed instead of counted.

---

### Step 9 — Create the request-count policy, the row Lab 04B unlocked

**Purpose**

`ALBRequestCountPerTarget` is the better scaling signal for a web API, and until Lab 04B there was no
target group to point it at. This step creates the policy that was previously impossible, and building
its `ResourceLabel` is the fourth constructed identifier in this architecture.

**Run from**

```text
aws-floci-course/
```

**Concept first — why requests beat CPU for this service**

CPU utilisation is a **symptom**. Requests per target is the **cause**. Three consequences:

- **CPU is relative to a reservation you chose arbitrarily.** Step 7 made this point: the same workload
  reports 80 per cent on a `256`-CPU task and 20 per cent on a `1024`-CPU one. Re-sizing the task
  silently re-tunes every CPU policy you own. Requests per target means the same thing regardless of task
  size.
- **CPU lags.** A request arrives, is queued, is processed, and *then* consumes CPU. Request count moves
  the instant the load does; CPU moves once the work has started, and for an I/O-bound service it may
  barely move at all. An enrolment API that spends its time waiting on a database can be completely
  saturated at 15 per cent CPU, and a CPU policy will watch it fall over.
- **Requests per target is a number the business already has.** "We expect 1200 concurrent registrations"
  translates into a target value. "We expect 55 per cent CPU" does not translate into anything.

The one case where CPU is the better of the two is a genuinely CPU-bound workload with variable cost per
request — a transcript PDF renderer, say, where one request might cost a hundred times another. There,
request count is a poor proxy for load and CPU is measuring the thing that actually runs out. That is
Review Question 7.

**Concept first — the `ResourceLabel`, and what it is made of**

`ALBRequestCountPerTarget` is published per target group per load balancer, so the metric specification
needs to say *which*. It does that with a single string built from fragments of two ARNs:

```text
app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
|-------------- from the ALB's ARN ----| |----------- from the target group's ARN -----|

arn:aws:elasticloadbalancing:...:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
                                             |------ take everything after this ------|

arn:aws:elasticloadbalancing:...:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
                                |--- and prefix it with the word "targetgroup/" ---|
```

The asymmetry is real and is not a documentation error: the load balancer's fragment already begins with
its type (`app`), while the target group's fragment does not include the word `targetgroup`, so you have
to put it back. Lab 04B's Exercise 5 asked you to notice exactly that and to handle the two suffixes with
two different parameter expansions.

**Command — part 1, get the label, from Lab 04B if it recorded one and from the API if not**

```bash
if [ -n "${USMS_ALB_RESOURCE_LABEL:-}" ]; then
  RESOURCE_LABEL="$USMS_ALB_RESOURCE_LABEL"
  echo "using the label Lab 04B Exercise 5 recorded"
else
  echo "no recorded label — deriving it from the API"
  ALB_ARN_NOW=$(aws elbv2 describe-load-balancers --names "$USMS_ALB_NAME" \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)
  TG_ARN_NOW=$(aws elbv2 describe-target-groups --names "$USMS_TG_NAME" \
    --query 'TargetGroups[0].TargetGroupArn' --output text)

  # The ALB suffix is everything AFTER ":loadbalancer/", and already starts with "app/".
  ALB_SUFFIX="${ALB_ARN_NOW#*:loadbalancer/}"
  # The target group suffix is everything after the LAST colon, and already starts with "targetgroup/".
  TG_SUFFIX="${TG_ARN_NOW##*:}"

  RESOURCE_LABEL="${ALB_SUFFIX}/${TG_SUFFIX}"
fi

echo "RESOURCE_LABEL = $RESOURCE_LABEL"

# Validate before use: six slash-separated segments, first "app", fourth "targetgroup".
printf '%s' "$RESOURCE_LABEL" | awk -F/ '{
  printf "segments=%d first=%s fourth=%s\n", NF, $1, $4
  if (NF==6 && $1=="app" && $4=="targetgroup") print "OK"; else print "UNEXPECTED SHAPE"
}'
```

**What the command does**

Two different parameter expansions, because the two ARNs need different treatment:

- `"${ALB_ARN_NOW#*:loadbalancer/}"` uses `#` — strip the **shortest** prefix matching
  `*:loadbalancer/`. The delimiter is a whole word rather than a single character, which is why `##*:`
  would be wrong here: the load balancer's ARN has no colon after `loadbalancer/`, so `##*:` happens to
  work, but it stops working the moment you try the same trick on the listener ARN. Say what you mean.
- `"${TG_ARN_NOW##*:}"` uses `##*:` — strip everything up to the last colon — which is the same
  expansion Step 5 used on the service ARN, and it works because the target group's ARN ends in exactly
  the fragment you want, `targetgroup/<name>/<id>`.

The validation counts six segments and checks two of them by name. That first segment, `app`, is the load
balancer *type*: it would be `net` for a Network Load Balancer, whose metric would be a different one
entirely. Checking it is how you catch a label built from the wrong load balancer.

**Command — part 2, the policy configuration**

```bash
cat > templates/lab-04c-target-tracking-requests.json << EOF
{
  "TargetValue": 1000.0,
  "PredefinedMetricSpecification": {
    "PredefinedMetricType": "ALBRequestCountPerTarget",
    "ResourceLabel": "$RESOURCE_LABEL"
  },
  "ScaleOutCooldown": 60,
  "ScaleInCooldown": 300,
  "DisableScaleIn": false
}
EOF

python3 -m json.tool templates/lab-04c-target-tracking-requests.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-04c-target-tracking-requests.json
grep ResourceLabel templates/lab-04c-target-tracking-requests.json
```

**What the command does**

`<< EOF`, **unquoted**, because `$RESOURCE_LABEL` must become a real string as the file is written. This
is the opposite of Step 7's document, two steps earlier, and the check is the same: `grep -c '\$'` must
print **`0`**. If it prints `1`, you used the quoted form and the file contains the literal text
`$RESOURCE_LABEL`, which `put-scaling-policy` will reject with a message about the resource label's
format that says nothing whatever about quoting.

`TargetValue` of `1000.0` means **1000 requests per target per minute**, which is the unit
`RequestCountPerTarget` is published in — a `Sum` over a one-minute period, per target. Not per second.
Getting that wrong by a factor of sixty is the most common mistake with this metric, and the symptom is a
policy that appears never to fire (target set too high) or one that pins the service to the ceiling
(target set too low).

Is 1000 a defensible number for the USMS enrolment API? Only if you can say what one task can serve. Two
tasks at 1000 requests per minute each is about 33 requests per second in total, which is a plausible load
for a student portal at registration time and a plausible capacity for a small container. The honest
answer is that the number comes from a load test nobody has run yet, and Exercise 4 asks you to say so and
propose how to get a real one.

**Command — part 3, create it**

```bash
REQ_POLICY="usms-enrolment-requests-target-tracking"

REQ_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$REQ_POLICY" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://templates/lab-04c-target-tracking-requests.json \
  --query 'PolicyARN' \
  --output text) \
  && echo "REQ_POLICY_ARN = $REQ_POLICY_ARN" \
  || echo "ALBRequestCountPerTarget not supported on this build — record it and continue; Step 10 does not depend on it"
```

**Expected result**

```text
valid JSON
0
    "ResourceLabel": "app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067"
REQ_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:1b2c3d4e-...:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-requests-target-tracking
```

> Example output — your suffixes and UUID will differ.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$RID" \
  --query 'ScalingPolicies[].{Name:PolicyName,Type:PolicyType,Metric:TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType,Target:TargetTrackingScalingPolicyConfiguration.TargetValue,Alarms:length(Alarms)}' \
  --output table
```

**Expected result**

```text
------------------------------------------------------------------------------------------------------------------
|                                          DescribeScalingPolicies                                               |
+---------+-----------------------------------------+--------------------------------------+---------+-----------+
| Alarms  |                  Metric                 |                 Name                 | Target  |   Type    |
+---------+-----------------------------------------+--------------------------------------+---------+-----------+
|  2      |  ECSServiceAverageCPUUtilization        |  usms-enrolment-cpu-target-tracking  |  50.0   | TargetT.. |
|  2      |  ALBRequestCountPerTarget               |  usms-enrolment-requests-target-t..  |  1000.0 | TargetT.. |
+---------+-----------------------------------------+--------------------------------------+---------+-----------+
```

> Example output.

**What to look for:** two policies on one target, each with two alarms — four managed alarms now, and
Step 8's count command will say so. Which raises the question the next paragraph answers.

**Two target tracking policies on one target: what happens when they disagree?**

They will disagree. CPU will say four tasks and requests will say six, and there is exactly one rule:

```text
SCALE OUT  -> the LARGEST capacity any policy asks for wins
SCALE IN   -> only when EVERY policy agrees that scaling in is safe
```

That is the correct bias and it is worth stating as a design principle rather than as trivia: with
several signals, the safe reading of "should I have more capacity?" is *any yes*, and the safe reading of
"can I have less?" is *all yes*. The practical consequence is that adding a second target tracking policy
can only ever make your service larger or leave it the same, never smaller — so a second policy is a safe
thing to add to a running system and an unsafe thing to add to a cost estimate.

What you must **not** do is put two target tracking policies on the **same** metric with different
targets. They are then two thermostats in one room, each undoing the other's work, and the service
oscillates. Different metrics: fine, and this is the normal arrangement. Same metric: a fault. Exercise 2
asks you to explain why the same reasoning makes target tracking and step scaling on one metric a bad
idea, which is the subtler version of the same mistake.

**Checkpoint 3**

```text
scalable target   service/usms-ecs-cluster/usms-enrolment-svc   min 2 max 10
 ├── usms-enrolment-cpu-target-tracking        AWS/ECS CPUUtilization -> 50.0
 │    ├── TargetTracking-...-AlarmHigh   period 60, 3 evaluations, > 50
 │    └── TargetTracking-...-AlarmLow    period 60, 15 evaluations, < 45
 ├── usms-enrolment-requests-target-tracking   AWS/ApplicationELB RequestCountPerTarget -> 1000.0
 │    ├── ResourceLabel  app/<alb>/<id>/targetgroup/<tg>/<id>   (six segments, validated)
 │    ├── TargetTracking-...-AlarmHigh
 │    └── TargetTracking-...-AlarmLow
 ├── scale out on the LARGEST request from any policy
 ├── scale in only when EVERY policy agrees
 └── nothing has fired, because no metric has moved
```

---

### Step 10 — Create a step scaling policy, and the alarm that drives it

**Purpose**

Target tracking answers "keep this number near that number". This step builds the thing it cannot
express, and — because you own the alarm — it is also what makes scaling **observable** on a build where
no metric moves by itself.

**Run from**

```text
aws-floci-course/
```

**Concept first — the requirement target tracking cannot express**

Here is the requirement, in one sentence, from the USMS project lead:

> The enrolment service writes each registration onto an internal work queue before confirming it. If the
> queue is a hundred deep we are slightly behind and one more task will catch up; if it is two hundred
> deep something is badly wrong and I would rather over-provision than explain it to the registrar.

Target tracking cannot say that. It computes capacity from a ratio, so it can hold a queue near a set
point, but "one task if it is a bit bad and three if it is very bad" is a **piecewise** response and
there is no set point in it at all. That is a step function, and step scaling is how you write one.

There is a second reason to reach for step scaling here and it is more practical: the metric is not a
utilisation. Queue depth does not fall predictably as capacity rises — it falls as the *rate of drain*
exceeds the *rate of arrival*, which is a different relationship — so the target tracking arithmetic from
the interlude does not apply and would misbehave if you forced it.

**Concept first — how step adjustments are expressed, and the part everyone gets wrong**

A step scaling policy is a table of adjustments, and the bounds in that table are **relative to the
alarm's threshold, not absolute metric values.** That single fact is the source of nearly every step
scaling misconfiguration.

```text
alarm threshold = 100

  MetricIntervalLowerBound   MetricIntervalUpperBound   ScalingAdjustment
            0                          100                    +1
           100                       (none)                   +3
            |                           |
            +-- metric 100 to 200 ------+                 breach of 0 to 100
                metric 200 and above                      breach of 100 and above
```

Read it as: *how far past the threshold are we?* A metric of 150 against a threshold of 100 is a breach
of 50, which falls in the first interval, so the adjustment is +1. A metric of 260 is a breach of 160,
which falls in the second, so +3.

Three rules govern the table, and all three are validated at creation time:

- The intervals must not overlap and must not leave a gap.
- Exactly one interval may omit its upper bound (the open-ended top) and exactly one may omit its lower
  bound (the open-ended bottom).
- For a scale-out policy the bounds are non-negative; for a scale-in policy they are non-positive, and
  the adjustments are negative. Exercise 2 builds the scale-in half.

And two more fields:

| Field | Value here | Meaning |
| --- | --- | --- |
| `AdjustmentType` | `ChangeInCapacity` | The adjustment is a number of tasks to add. Also `ExactCapacity` (set it to this) and `PercentChangeInCapacity` (add this percentage, with `MinAdjustmentMagnitude` to stop a 10 per cent increase on 2 tasks rounding to nothing) |
| `MetricAggregationType` | `Average` | How the metric is aggregated over the alarm's period when deciding which step applies. Also `Minimum` and `Maximum` |
| `Cooldown` | `60` | As before: how soon this policy may act again. Step scaling has one cooldown, not two, because a step policy is invoked by an alarm rather than deciding a direction for itself |

**Command — part 1, publish the metric, so that it exists**

```bash
METRIC_NS="USMS/Enrolment"
METRIC_NAME="EnrolmentQueueDepth"
METRIC_DIM="Service=enrolment"

for v in 3 5 4; do
  aws cloudwatch put-metric-data \
    --namespace "$METRIC_NS" \
    --metric-name "$METRIC_NAME" \
    --value "$v" \
    --unit Count \
    --dimensions "$METRIC_DIM"
done

aws cloudwatch list-metrics --namespace "$METRIC_NS" \
  --query 'Metrics[].{Name:MetricName,Dimensions:Dimensions[].[Name,Value]}' \
  --output json
```

**What the command does**

`put-metric-data` publishes a **custom metric** — a namespace you invented, a metric name you invented,
and dimensions you invented. That is all a custom metric is: CloudWatch will store any
namespace-plus-name-plus-dimensions triple you send it, and there is no registration step. The convention
is `Company/Application` or, here, `USMS/Enrolment`; a namespace beginning `AWS/` is reserved and will be
rejected.

Three values are published so that the metric exists with more than one datapoint. On a real system these
would come from the application itself, or from a small agent, and the interesting engineering question is
not how to publish them but how often: CloudWatch charges per metric and per API call, and a service
publishing a custom metric per task per second is a line item somebody will notice.

**Note the `--dimensions` syntax, and note that it is not the same as the next command's.**
`put-metric-data` takes `Service=enrolment`, a plain map. `put-metric-alarm`, in part 3, takes
`Name=Service,Value=enrolment`. **Two operations in the same service, on the same concept, with different
shorthand.** That is not a mistake in this lab and it is not a mistake in the CLI; it is two different
parameter shapes in the service model, given the same flag name. Run
`aws cloudwatch put-metric-data help` and `aws cloudwatch put-metric-alarm help` and read both synopses
if you want to see it for yourself. It is the seventh tag-or-dimension convention this course has met, and
the habit remains the same: read the synopsis, do not guess.

**Command — part 2, the step configuration**

```bash
cat > templates/lab-04c-step-scaling-out.json << 'EOF'
{
  "AdjustmentType": "ChangeInCapacity",
  "MetricAggregationType": "Average",
  "Cooldown": 60,
  "StepAdjustments": [
    {
      "MetricIntervalLowerBound": 0,
      "MetricIntervalUpperBound": 100,
      "ScalingAdjustment": 1
    },
    {
      "MetricIntervalLowerBound": 100,
      "ScalingAdjustment": 3
    }
  ]
}
EOF

python3 -m json.tool templates/lab-04c-step-scaling-out.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-04c-step-scaling-out.json
```

Quoted heredoc again — no variables, nothing to expand, `grep -c '\$'` prints `0`.

**Command — part 3, create the policy, then the alarm that drives it**

```bash
STEP_POLICY="usms-enrolment-queue-step-out"

STEP_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$STEP_POLICY" \
  --policy-type StepScaling \
  --step-scaling-policy-configuration file://templates/lab-04c-step-scaling-out.json \
  --query 'PolicyARN' \
  --output text)

echo "STEP_POLICY_ARN = $STEP_POLICY_ARN"

QUEUE_ALARM="usms-enrolment-queue-high"

aws cloudwatch put-metric-alarm \
  --alarm-name "$QUEUE_ALARM" \
  --alarm-description "USMS enrolment work queue is backing up; invokes the step scaling policy" \
  --namespace "$METRIC_NS" \
  --metric-name "$METRIC_NAME" \
  --dimensions Name=Service,Value=enrolment \
  --statistic Average \
  --period 60 \
  --evaluation-periods 1 \
  --threshold 100 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$STEP_POLICY_ARN" \
  --tags Key=Name,Value=usms-enrolment-queue-high Key=Project,Value=USMS Key=Lab,Value=04C

aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
  --query 'MetricAlarms[0].{Name:AlarmName,Namespace:Namespace,Metric:MetricName,Stat:Statistic,Period:Period,Evals:EvaluationPeriods,Op:ComparisonOperator,Threshold:Threshold,Missing:TreatMissingData,Actions:AlarmActions,State:StateValue}' \
  --output json
```

**What the command does**

**The order matters.** The policy is created first, because the alarm needs the policy's ARN as an alarm
action and an alarm action that names a policy which does not exist is rejected. Reverse the order and
you get `ValidationError: Invalid metrics or alarm actions`, which does not point at the ordering.

**`--alarm-actions "$STEP_POLICY_ARN"` is the whole point of the step.** This is the link that target
tracking made for you in Step 7 and that you make for yourself here. An alarm action can be a scaling
policy ARN, an SNS topic ARN, an EC2 action, or a Systems Manager action — and the fact that they share
one field is why you can have one alarm that both scales the service and wakes somebody up. That is
something target tracking's managed alarms cannot do for you, and it is the third reason to prefer step
scaling for a signal that matters.

**`--treat-missing-data notBreaching`** decides what the alarm does when no datapoint arrives for a
period. The four choices are `notBreaching` (treat it as good), `breaching` (treat it as bad),
`ignore` (keep the current state) and `missing` (go to `INSUFFICIENT_DATA`, the default). For a queue
depth published by the application, a missing datapoint most likely means the application is not
publishing — which is a *problem*, not "queue is empty" — so `breaching` has a real argument in its
favour. `notBreaching` is chosen here because this lab publishes datapoints by hand and does not want the
alarm firing every time you stop. Say in one sentence in your notes which you would choose on a real
system, and why. It is Review Question 4.

**`--evaluation-periods 1` at a `--period 60`** means the alarm fires after one minute above the
threshold. Compare with the 3 minutes the managed high alarm from Step 8 uses. This one is deliberately
more twitchy, because a backlog is a *worse* signal than a utilisation and waiting three minutes to react
to it is three minutes of students seeing a spinner.

**Expected result**

```text
valid JSON
0
STEP_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:2c3d4e5f-...:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-queue-step-out
{
    "Name": "usms-enrolment-queue-high",
    "Namespace": "USMS/Enrolment",
    "Metric": "EnrolmentQueueDepth",
    "Stat": "Average",
    "Period": 60,
    "Evals": 1,
    "Op": "GreaterThanOrEqualToThreshold",
    "Threshold": 100.0,
    "Missing": "notBreaching",
    "Actions": [
        "arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:2c3d4e5f-...:policyName/usms-enrolment-queue-step-out"
    ],
    "State": "OK"
}
```

> Example output — your UUID will differ, and `State` may be `INSUFFICIENT_DATA` rather than `OK`
> depending on whether your build evaluated the three datapoints you published.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$RID" --policy-names "$STEP_POLICY" \
  --query 'ScalingPolicies[0].{Name:PolicyName,Type:PolicyType,Adjust:StepScalingPolicyConfiguration.AdjustmentType,Agg:StepScalingPolicyConfiguration.MetricAggregationType,Cooldown:StepScalingPolicyConfiguration.Cooldown,Steps:StepScalingPolicyConfiguration.StepAdjustments,Alarms:Alarms[].AlarmName}' \
  --output json
```

**What to look for:** three things.

`Type` is `StepScaling` and `Steps` has **two** entries, the second with no `MetricIntervalUpperBound`.
An open-ended top step is what makes the policy able to respond to a metric value you did not anticipate.

`Alarms` contains `usms-enrolment-queue-high` — and this is worth pausing on, because **you never told
the policy about the alarm.** You told the alarm about the policy, in `--alarm-actions`, and Application
Auto Scaling discovered the association from the other end. The relationship is stored once and readable
from both directions, which is convenient and is also why deleting the alarm leaves a policy that still
claims to have one.

`Adjust` is `ChangeInCapacity`. If it says `ExactCapacity`, you have a policy that sets the count to 1 or
3 tasks rather than adding them, which at a floor of 2 would be a scale-*in* dressed as a scale-out.

---

### Step 11 — Create two scheduled actions

**Purpose**

Everything so far is reactive and therefore late. Enrolment opens at a time printed in the university
calendar, and this is the only mechanism in Application Auto Scaling that can have the capacity ready
before the first student arrives.

**Run from**

```text
aws-floci-course/
```

**Concept first — a scheduled action changes the bounds, not the count**

This is the detail that makes scheduled scaling compose properly with the policies you have already
built, and it is easy to miss.

A scheduled action sets `MinCapacity`, `MaxCapacity`, or both. It does not set `desiredCount`. So a
morning action raising the floor to 4 does two things at once:

```text
07:44   min 2  max 10   desired 2      the reactive policies own the range 2..10
07:45   min 4  max 10   desired 4      the floor moved, so the target had to
                                       -> desiredCount raised BY THE FLOOR, not by a policy
                                       -> the reactive policies now own the range 4..10
20:00   min 2  max 10   desired 4      the floor moved down; nothing forces the count down
                                       -> the CPU and request policies may now scale in to 2
```

Read the last two lines carefully. Lowering the floor at 20:00 does **not** remove capacity. It gives
permission for capacity to be removed, and the reactive policies do the removing when their metrics say
it is safe. That is a much better arrangement than a scheduled action that sets an exact count, because
it cannot drop you below what the traffic actually needs — if students are still enrolling at 20:00, CPU
and requests will keep the tasks alive and the floor will simply be irrelevant.

The general principle is worth stating: **scheduled scaling should move the boundaries and let the
reactive policies move the count.** A scheduled action that sets both min and max to the same value is a
scheduled action that has switched off your reactive scaling for that window, and people do it by
accident.

**Concept first — schedule expressions, and time zones versus regions**

Three forms:

| Form | Example | Fires |
| --- | --- | --- |
| `at(...)` | `at(2026-09-14T02:00:00)` | Once, at that moment. The action stays behind afterwards and must be deleted |
| `rate(...)` | `rate(1 hour)` | Repeatedly, at that interval, starting when you create it |
| `cron(...)` | `cron(45 7 ? * MON-FRI *)` | On a recurring calendar schedule |

The `cron` form has **six** fields, not five:

```text
cron(minutes hours day-of-month month day-of-week year)
     45      7     ?             *     MON-FRI     *
```

The sixth field, year, is the one that surprises anybody who has written a Unix crontab. And there is a
second difference: `day-of-month` and `day-of-week` cannot both be specified, so one of them must be `?`
— "no particular value". Writing `*` in both is rejected, and the error message is about the fields
rather than about the rule.

**Now the part that matters more than the syntax.** Every resource in this course is in `us-east-1`, and
the university is in Bhutan. Those are different facts about different things, and the schedule is about
the second one:

- **The region** decides where the tasks run. It is `us-east-1` because `configs/course.env` says so, and
  it has nothing to do with when anybody enrols.
- **The time zone** decides what "07:45" means. Application Auto Scaling defaults to **UTC** and accepts
  `--timezone` with an IANA name.

A schedule of `cron(45 7 ? * MON-FRI *)` with no `--timezone` fires at 07:45 UTC, which is 13:45 in
Thimphu — six hours after the students arrived. Passing `--timezone Asia/Thimphu` fires it at 07:45 local,
which is what the requirement said. Being explicit also survives daylight saving in regions that have it,
because AWS resolves the IANA zone at each firing rather than storing a fixed offset. Bhutan has no
daylight saving, which makes this a good place to learn the habit without being punished for missing it.

**Command — part 1, the morning scale-out**

```bash
SCHED_OUT="usms-enrolment-morning-scale-out"

aws application-autoscaling put-scheduled-action \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --scheduled-action-name "$SCHED_OUT" \
  --schedule "cron(45 7 ? * MON-FRI *)" \
  --timezone "Asia/Thimphu" \
  --scalable-target-action MinCapacity=4,MaxCapacity=10 \
  && echo "created $SCHED_OUT" \
  || echo "--timezone may be unsupported on this build; retrying in UTC below"
```

If that failed on `--timezone`, the UTC equivalent of 07:45 in Thimphu (UTC+6) is 01:45:

```bash
aws application-autoscaling put-scheduled-action \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --scheduled-action-name "$SCHED_OUT" \
  --schedule "cron(45 1 ? * MON-FRI *)" \
  --scalable-target-action MinCapacity=4,MaxCapacity=10 \
  && echo "created $SCHED_OUT in UTC — record that you did the conversion by hand"
```

**Command — part 2, the evening scale-in**

```bash
SCHED_IN="usms-enrolment-evening-scale-in"

aws application-autoscaling put-scheduled-action \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --scheduled-action-name "$SCHED_IN" \
  --schedule "cron(0 20 ? * MON-FRI *)" \
  --timezone "Asia/Thimphu" \
  --scalable-target-action MinCapacity=2,MaxCapacity=10 \
  || aws application-autoscaling put-scheduled-action \
       --service-namespace ecs \
       --resource-id "$RID" \
       --scalable-dimension "$SDIM" \
       --scheduled-action-name "$SCHED_IN" \
       --schedule "cron(0 14 ? * MON-FRI *)" \
       --scalable-target-action MinCapacity=2,MaxCapacity=10
```

**What the command does**

`--scalable-target-action MinCapacity=4,MaxCapacity=10` is the new bounds, as a single structure in
shorthand. Note that **both** are given on both actions even though only the minimum changes. Omitting
`MaxCapacity` leaves it as it was, exactly like `register-scalable-target` in Step 6 — but writing it out
means the pair of actions reads as a complete statement of the two states rather than as a pair of
deltas, and somebody reading it in six months does not have to reconstruct the ceiling from another call.

`put-scheduled-action` is a create-or-replace, like `put-scaling-policy`. The same name is the same
action.

**Expected result**

```text
created usms-enrolment-morning-scale-out
```

> Example output — a successful `put-scheduled-action` prints nothing of its own, so the `echo` is the
> evidence.

**Verify**

```bash
aws application-autoscaling describe-scheduled-actions \
  --service-namespace ecs \
  --resource-id "$RID" \
  --query 'ScheduledActions[].{Name:ScheduledActionName,Schedule:Schedule,TZ:Timezone,Min:ScalableTargetAction.MinCapacity,Max:ScalableTargetAction.MaxCapacity,Created:CreationTime}' \
  --output table
```

**Expected result**

```text
--------------------------------------------------------------------------------------------------------
|                                      DescribeScheduledActions                                        |
+------+------+---------------------------------------+----------------------------+-------------------+
| Max  | Min  |                 Name                  |          Schedule          |        TZ         |
+------+------+---------------------------------------+----------------------------+-------------------+
|  10  |  4   |  usms-enrolment-morning-scale-out     |  cron(45 7 ? * MON-FRI *)  |  Asia/Thimphu     |
|  10  |  2   |  usms-enrolment-evening-scale-in      |  cron(0 20 ? * MON-FRI *)  |  Asia/Thimphu     |
+------+------+---------------------------------------+----------------------------+-------------------+
```

> Example output — the `Created` column is omitted here for width; yours will show it.

**What to look for:** two rows. The morning action's `Min` is `4` and the evening action's is `2`, and
both `Max` values are `10`. If `TZ` is empty or `UTC`, you took the fallback path — that is fine, and
write one sentence in `notes/lab-04c-notes.md` recording that you converted the times by hand and what
would break if the university moved to a zone with daylight saving.

Note that neither action has fired and neither will during this session unless you happen to be at your
machine at 07:45 on a weekday. That is the nature of scheduled scaling and it is why the "Your turn"
below exists.

✏️ **Your turn**

Exam results are published one night a semester and the load is enormous for about two hours. Create a
**one-off** scheduled action, `usms-enrolment-results-night`, using the `at()` form, that raises the floor
to 6 at a specific moment ten minutes from now, and watch what happens.

```text
Expected result:
describe-scheduled-actions shows three actions. Ten minutes later, IF your build runs
the scheduler, desiredCount is 6 and the scalable target's MinCapacity is 6 — with no
alarm having fired and no policy involved. If your build does not run the scheduler,
nothing happens, and the correct thing to record is that the action exists and the
mechanism was not observable.

Then answer in two sentences in notes/lab-04c-notes.md:
An at() action does not remove itself after firing. Say what is left behind, why that
matters six months later, and which command you would put in the same runbook page as
the one that created it.
```

Hint: `python3 -c "import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S'))"` gives you a correctly formatted timestamp on both
macOS and Linux, which `date -d` and `date -v` do not. The `at()` form takes no time zone offset in the
string — the `--timezone` flag is how you say what it means.

When you have finished looking at it, remove it — and read this first.

!!! danger "Read before running any delete command"
    **What will be deleted:** one scheduled action, `usms-enrolment-results-night`, which you created in
    the "Your turn" above.

    **What depends on it:** nothing. It is a calendar entry. Deleting it does not change the scalable
    target's current bounds, so if it has already fired and raised `MinCapacity` to 6, **that floor stays
    at 6 after the action is gone.** Deleting the thing that made a change does not undo the change.

    **Reversible?** Yes. One `put-scheduled-action` recreates it.

    **Effect on later labs:** none, **provided** you also put the floor back to 2. Section 9's script
    asserts `MinCapacity` is 2, and this is the most likely reason for it to fail.

```bash
aws application-autoscaling delete-scheduled-action \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --scheduled-action-name usms-enrolment-results-night

aws application-autoscaling register-scalable-target \
  --service-namespace ecs --resource-id "$RID" --scalable-dimension "$SDIM" \
  --min-capacity 2 --max-capacity 10 >/dev/null

aws application-autoscaling describe-scheduled-actions --service-namespace ecs --resource-id "$RID" \
  --query 'length(ScheduledActions)' --output text
aws application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].[MinCapacity,MaxCapacity]' --output text
```

**What to look for:** `2` scheduled actions remaining, and `2	10` for the bounds. That second line is the
point of the admonition: the floor had to be put back by hand.

**Checkpoint 4**

```text
scalable target   min 2  max 10
 ├── usms-enrolment-cpu-target-tracking        target tracking, managed alarms
 ├── usms-enrolment-requests-target-tracking   target tracking, managed alarms
 ├── usms-enrolment-queue-step-out             STEP scaling
 │    ├── ChangeInCapacity, Average, cooldown 60
 │    ├── breach   0 to 100  -> +1 task
 │    ├── breach 100 and up  -> +3 tasks
 │    └── invoked by  usms-enrolment-queue-high
 │         ├── USMS/Enrolment EnrolmentQueueDepth, dimension Service=enrolment
 │         ├── Average, period 60, 1 evaluation, >= 100
 │         ├── missing data treated as notBreaching
 │         └── AlarmActions -> the step policy ARN   (the link YOU made)
 ├── usms-enrolment-morning-scale-out   cron(45 7 ? * MON-FRI *)  Asia/Thimphu  min 4  max 10
 └── usms-enrolment-evening-scale-in    cron(0 20 ? * MON-FRI *)  Asia/Thimphu  min 2  max 10
      (a scheduled action moves the BOUNDS; the reactive policies move the count)
```

---

### Step 12 — Fire the alarm, and prove that something other than you moved the number

**Purpose**

Everything so far has been configuration that reported success. This is the step that tries to close the
loop. It is the one place in this lab where you can watch `desiredCount` change without typing a number,
and — following the course's own rule — it is written so that you **prove the property** rather than
observe a proxy for it.

**Run from**

```text
aws-floci-course/
```

**Concept first — create, perturb, read back, applied to a control loop**

The property this lab depends on is: *a metric breach causes capacity to change.* The proof pattern is
the same shape as Lab 1 Step 14's persistence proof and Lab 04A Step 18's.

```text
CREATE    a policy, an alarm, and the link between them          Steps 10
PERTURB   push the metric past the threshold, or force the
          alarm into ALARM state                                 this step, parts 2 and 3
READ BACK desiredCount, and describe-scaling-activities          this step, part 4
```

What would **not** be a proof: observing that `put-scaling-policy` returned an ARN, or that
`describe-alarms` shows `State: OK`. Both of those were true before anything was connected. The proof has
to be a number that moved, and a record saying who moved it.

**Command — part 1, record the truth before**

```bash
python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" \
  > outputs/lab-04c-pre-scale.txt

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text \
  >> outputs/lab-04c-pre-scale.txt

aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs --resource-id "$RID" \
  --query 'length(ScalingActivities)' --output text \
  >> outputs/lab-04c-pre-scale.txt

cat outputs/lab-04c-pre-scale.txt
```

**Expected result**

```text
2026-09-03T04:31:07Z
2	2	0
0
```

> Example output. The last line is the number of scaling activities recorded so far, and it should be
> `0`: nothing has scaled anything yet. If it is `None`, your build does not implement
> `describe-scaling-activities` and part 4 has a fallback.

**Command — part 2, push the metric past the threshold the honest way**

```bash
for i in 1 2 3; do
  aws cloudwatch put-metric-data \
    --namespace "$METRIC_NS" \
    --metric-name "$METRIC_NAME" \
    --value 260 \
    --unit Count \
    --dimensions "$METRIC_DIM"
  sleep 5
done

START=$(python3 -c "import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
END=$(python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")

aws cloudwatch get-metric-statistics \
  --namespace "$METRIC_NS" \
  --metric-name "$METRIC_NAME" \
  --dimensions Name=Service,Value=enrolment \
  --start-time "$START" --end-time "$END" \
  --period 60 \
  --statistics Average Maximum \
  --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Average,Maximum]' \
  --output table
```

**What the command does**

A value of `260` against a threshold of `100` is a breach of `160`, which falls in the step policy's
second interval — `MetricIntervalLowerBound: 100` with no upper bound — so the adjustment that *should*
be applied is **+3 tasks**, taking `desiredCount` from 2 to 5. Predict that before you look, and write
the prediction down; the value of the exercise is in having predicted it.

`get-metric-statistics` needs an explicit time window and its timestamps are computed with `python3`
rather than `date`, for the reason the Prerequisites gave. Note the shape of the query: `sort_by` with an
expression reference, `&Timestamp`, which you met in Lab 04B Step 16 — datapoints come back unordered and
a table of unordered timestamps is unreadable.

On real AWS you now wait up to a minute for the alarm to evaluate. Watch it:

```bash
for i in $(seq 1 8); do
  read -r state reason <<< "$(aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].[StateValue,StateReason]' --output text)"
  printf 'poll %d  state=%-18s %s\n' "$i" "$state" "$reason"
  [ "$state" = "ALARM" ] && break
  sleep 15
done
```

**Command — part 3, if the alarm will not fire by itself, fire it deliberately**

Very likely on Floci, and it is not a failure of your work.

```bash
aws cloudwatch set-alarm-state \
  --alarm-name "$QUEUE_ALARM" \
  --state-value ALARM \
  --state-reason "Lab 04C Step 12: forcing the alarm state to prove the alarm-to-policy link" \
  && echo "alarm state forced to ALARM" \
  || echo "set-alarm-state not supported on this build — go to part 5"
```

**What the command does**

`set-alarm-state` writes an alarm's state directly, and **it invokes the alarm's actions exactly as a
real state change would.** That is not a testing back door bolted on for emulators; it is a documented
CloudWatch operation whose entire purpose is letting you test an alarm's actions without waiting for the
condition, and it is how you would verify a production runbook on real AWS without breaking anything.

Two things to know about it. The state you set is temporary: at the alarm's next evaluation, real
CloudWatch recomputes the state from the metric and overwrites yours — so on real AWS the alarm will fall
back to `OK` within a minute or two, having already fired its action once. And it is genuinely
privileged: `cloudwatch:SetAlarmState` on a production alarm is the ability to trigger anything that
alarm does, which is why it belongs in a policy you have thought about rather than in a wildcard.

**Command — part 4, read back the number and the record**

```bash
for i in $(seq 1 10); do
  read -r d r p <<< "$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
    --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text)"
  printf 'poll %2d  desired=%s running=%s pending=%s\n' "$i" "$d" "$r" "$p"
  [ "$d" != "2" ] && break
  sleep 10
done

echo
echo "== who moved it? =="
aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs \
  --resource-id "$RID" \
  --max-items 5 \
  --query 'ScalingActivities[].{Start:StartTime,Status:StatusCode,Cause:Cause,Detail:StatusMessage,Description:Description}' \
  --output json
```

**Expected result — on a build where the loop runs**

```text
poll  1  desired=2 running=2 pending=0
poll  2  desired=5 running=2 pending=3

== who moved it? ==
[
    {
        "Start": "2026-09-03T04:33:11.204000+00:00",
        "Status": "Successful",
        "Cause": "monitor alarm usms-enrolment-queue-high in state ALARM triggered policy usms-enrolment-queue-step-out",
        "Detail": "Successfully set desired count to 5. Change successfully fulfilled by ecs.",
        "Description": "Setting desired count to 5."
    }
]
```

> Example output — your timestamps and UUIDs will differ.

**What to look for, and this is the whole lab in one field:** the `Cause` string. It names the alarm, it
names the policy, and it says which state change triggered it. That sentence is the evidence that
`desiredCount` was changed by something other than you, and it is the single most valuable output in this
document. Screenshot it.

`Status` of `Successful` means Application Auto Scaling's `UpdateService` call was accepted. Note what it
does **not** mean: it does not mean three tasks are running. `pending=3` in the poll above is ECS still
starting them, and Lab 04B's 60-second grace period means they will not receive a request for another
minute after that. The scaling activity completes long before the capacity exists — which is §4.3's point,
now visible as two numbers in one line of output.

Other `Status` values worth recognising:

| `StatusCode` | Meaning |
| --- | --- |
| `Pending` / `InProgress` | The call has been made and ECS has not confirmed |
| `Successful` | ECS accepted the new desired count |
| `Overridden` | A later activity superseded this one before it completed |
| `Unfulfilled` | The change could not be applied — on real AWS, usually the ceiling, a quota, or no addresses left in the subnet |
| `Failed` | The `UpdateService` call itself was rejected. Read `StatusMessage`; on real AWS this is where a service-linked role problem surfaces |

**Command — part 5, the fallback proof, which always works**

If `desiredCount` did not move, prove the wiring instead. Record which of the two proofs you obtained.

```bash
{
  echo "== 1. The alarm, and what it watches =="
  aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].[AlarmName,Namespace,MetricName,ComparisonOperator,Threshold,StateValue]' \
    --output text

  echo
  echo "== 2. What the alarm invokes =="
  aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].AlarmActions[]' --output text

  echo
  echo "== 3. That ARN belongs to this policy, on this target =="
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" --policy-names "$STEP_POLICY" \
    --query 'ScalingPolicies[0].[PolicyName,PolicyARN,ResourceId,ScalableDimension]' --output text

  echo
  echo "== 4. The step the breach of 160 would select =="
  python3 - << 'PY'
import json
cfg = json.load(open('templates/lab-04c-step-scaling-out.json'))
breach = 260 - 100
for s in cfg['StepAdjustments']:
    lo = s.get('MetricIntervalLowerBound')
    hi = s.get('MetricIntervalUpperBound')
    lo_ok = lo is None or breach >= lo
    hi_ok = hi is None or breach < hi
    if lo_ok and hi_ok:
        print(f"breach {breach} selects ScalingAdjustment {s['ScalingAdjustment']:+d}")
PY

  echo
  echo "== 5. The bounds that would clamp the result =="
  aws application-autoscaling describe-scalable-targets \
    --service-namespace ecs --resource-ids "$RID" \
    --query 'ScalableTargets[0].[MinCapacity,MaxCapacity]' --output text

  echo
  echo "== 6. The current desired count =="
  aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
    --query 'services[0].desiredCount' --output text
} | tee outputs/lab-04c-scaling-proof.txt
```

**Verify**

Read the six blocks as one chain and satisfy yourself that each link names the next:

```text
metric USMS/Enrolment EnrolmentQueueDepth      (block 1)
  -> alarm usms-enrolment-queue-high >= 100    (block 1)
  -> AlarmActions names a scalingPolicy ARN    (block 2)
  -> that ARN is usms-enrolment-queue-step-out (block 3)
        on resource service/usms-ecs-cluster/usms-enrolment-svc
        dimension ecs:service:DesiredCount
  -> a breach of 160 selects +3                (block 4)
  -> clamped to at most 10                     (block 5)
  -> so desiredCount should become 5           (block 6, if the loop ran)
```

If block 6 says `2`, the chain is proven and the loop did not run; say that, in one sentence, and name
which of the five services in it your build did not connect. If it says `5`, you have both proofs and the
`Cause` string from part 4 is your evidence.

`outputs/lab-04c-scaling-proof.txt` is evidence for your lab report. Keep it until you have submitted.

**Command — part 6, return to the baseline**

```bash
aws cloudwatch set-alarm-state --alarm-name "$QUEUE_ALARM" --state-value OK \
  --state-reason "Lab 04C Step 12 complete" 2>/dev/null || true

for v in 4 3 2; do
  aws cloudwatch put-metric-data --namespace "$METRIC_NS" --metric-name "$METRIC_NAME" \
    --value "$v" --unit Count --dimensions "$METRIC_DIM"
done

aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --desired-count 2 \
  --query 'service.desiredCount' --output text

python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" \
  > outputs/lab-04c-post-scale.txt
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text \
  >> outputs/lab-04c-post-scale.txt

paste outputs/lab-04c-pre-scale.txt outputs/lab-04c-post-scale.txt
```

**What the command does, and one thing worth arguing about**

Setting the desired count back to 2 with `update-service` is a manual override of a scaled value, and it
is worth being clear about what that means: **the scaling policies are still there and still watching.**
If the metric were genuinely above the threshold, the next evaluation would scale out again, and you would
have a fight between a human and a policy that the policy always wins. That is why part 6 pushes the
metric back down *before* setting the count.

On a real system, "I set the count by hand and it went back up" is a support case that arrives weekly, and
the answer is always the same: a service under a scaling policy has no manual capacity. If you need the
count held, the tool is Step 13's suspension, or a `MinCapacity` and `MaxCapacity` set to the same number
— not `update-service`.

**What to look for:** `Desired` back to `2`, and the `paste` showing the two timestamps. The elapsed time
between them is roughly how long a full scale-out and manual reset took in your environment, and Exercise
5 asks you to measure a cleaner version of it.

**Checkpoint 5**

```text
Scaling observed (path A) or wiring proven (path B)
 ├── metric pushed to 260 against a threshold of 100  -> breach 160  -> step +3
 ├── alarm usms-enrolment-queue-high  ALARM (evaluated, or forced with set-alarm-state)
 ├── describe-scaling-activities Cause names BOTH the alarm and the policy
 │    (or outputs/lab-04c-scaling-proof.txt records the six-block chain instead)
 ├── desiredCount 2 -> 5, pendingCount 3, and NO capacity for another 60+ seconds
 └── back to the baseline: metric down first, THEN the count
```

---

### Step 13 — Suspend and resume scaling

**Purpose**

There is a day when you want the scaling to stop and the policies to stay. A deployment you want to
observe, an incident whose cause you suspect is the scaling itself, a load test whose whole point is to
see what happens at a fixed size. This step is the switch, and it is three switches rather than one.

**Run from**

```text
aws-floci-course/
```

**Concept first — three independent switches, and why they are separate**

The `SuspendedState` structure you saw in Step 5's verify has three booleans:

| Field | When `true`, this stops | Leaves working |
| --- | --- | --- |
| `DynamicScalingInSuspended` | Scale-**in** by any policy | Scale-out, and scheduled actions |
| `DynamicScalingOutSuspended` | Scale-**out** by any policy | Scale-in, and scheduled actions |
| `ScheduledScalingSuspended` | Scheduled actions | Both directions of dynamic scaling |

The separation is not bureaucracy. Each combination has a real use:

- **Scale-in only, suspended.** The commonest one. You are deploying, or you are in an incident, and you
  want capacity to be able to grow but never to shrink until you understand what is happening. This is
  the safe suspension and the one to reach for when in doubt.
- **Scale-out only, suspended.** A cost freeze, or a runaway policy you have not yet fixed. Note that
  this is the *dangerous* one: it caps you at your current size while leaving scale-in free, so a quiet
  hour can shrink you to the floor and you cannot grow back.
- **Scheduled only, suspended.** A public holiday, or an exam period that has moved. The reactive
  policies keep working; the calendar stops.

Two properties make this the right tool rather than deleting things:

- **The policies still exist.** `describe-scaling-policies` returns them unchanged, so nothing about your
  configuration is lost and nothing has to be rebuilt from a runbook at three in the morning.
- **Suspension is part of the scalable target, not of the policies.** One call suspends everything on
  that target, which is what you want in an incident — you are not trying to remember which of three
  policies is the dangerous one.

And one property that makes it dangerous:

!!! warning "A suspension is invisible unless you go and look for it"
    Nothing about a suspended target announces itself. `describe-scaling-policies` looks normal, the
    alarms still change state, and the CloudWatch console still draws the graph. The only place the
    suspension appears is the `SuspendedState` field of the scalable target.

    A target left with `DynamicScalingOutSuspended: true` after an incident is a service that will not
    scale out during the next one, and nothing will tell you. That is why Section 9's verification script
    asserts all three switches are `false`, and why the last command in this step is not optional.

    On a real team, the rule that works is: a suspension is always paired with a reminder to remove it,
    and the pairing is written down at the moment you suspend, not afterwards.

**Command — part 1, suspend scale-in only**

```bash
cat > templates/lab-04c-suspended-state.json << 'EOF'
{
  "DynamicScalingInSuspended": true,
  "DynamicScalingOutSuspended": false,
  "ScheduledScalingSuspended": false
}
EOF

python3 -m json.tool templates/lab-04c-suspended-state.json > /dev/null && echo "valid JSON"

aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --suspended-state file://templates/lab-04c-suspended-state.json \
  >/dev/null

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].{Min:MinCapacity,Max:MaxCapacity,Suspended:SuspendedState}' \
  --output json
```

**What the command does**

Note the operation: **`register-scalable-target` again.** There is no `suspend-scaling` call. Suspension
is content of the registration, and Step 6's change model applies — the address is unchanged, the content
is updated, and the two capacity parameters you did not pass survive untouched. That is the third time
this lab has used a re-registration to change something, and by now it should feel unremarkable.

Passing the state as a document with `file://` rather than as shorthand is a choice, and this is the one
place in this lab where the shorthand is genuinely fine:
`--suspended-state DynamicScalingInSuspended=true` is readable and unambiguous. The document is used
anyway for two reasons: it makes the *other two* switches explicit rather than implied, and it puts the
suspension into `templates/` where Git will show you when it was turned on and by which commit. For a
setting whose defining hazard is being forgotten, both of those are worth more than the keystrokes.

**Expected result**

```json
{
    "Min": 2,
    "Max": 10,
    "Suspended": {
        "DynamicScalingInSuspended": true,
        "DynamicScalingOutSuspended": false,
        "ScheduledScalingSuspended": false
    }
}
```

> Example output.

**What to look for:** one `true`, two `false`, and the bounds unchanged at 2 and 10. If all three went
`true`, you passed a document with the wrong values and you have just switched off every form of scaling
on this service.

**Command — part 2, observe that the policies are untouched**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$RID" \
  --query 'ScalingPolicies[].[PolicyName,PolicyType]' --output text

aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'length(MetricAlarms)' --output text
```

**What to look for:** all three policies still listed, and the managed alarm count unchanged. **Nothing
about the configuration changed** — which is the entire argument for suspending rather than deleting, and
is worth seeing rather than being told.

**Command — part 3, resume, and prove it**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --suspended-state DynamicScalingInSuspended=false,DynamicScalingOutSuspended=false,ScheduledScalingSuspended=false \
  >/dev/null

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].SuspendedState' --output json

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].SuspendedState.*' --output text | grep -ci true
```

**Expected result**

```json
{
    "DynamicScalingInSuspended": false,
    "DynamicScalingOutSuspended": false,
    "ScheduledScalingSuspended": false
}
0
```

> Example output.

**What to look for:** the `0` on the last line. `SuspendedState.*` is a JMESPath **object projection** —
the `*` after a dot projects every value of a hash, discarding the keys — so it yields three booleans, and
`grep -ci true` reports whether any of them is set. One number that must be zero is a better check than
three fields you have to read, and it is exactly the expression Section 9's script uses. Note that
`--output text` puts a flat list of scalars on **one** tab-separated line, so what you are counting is
matching lines rather than matching values — which is why the test is "is it zero" and not "is it three".

The `-i` on that `grep` is not decoration and it is worth one sentence, because getting it wrong produces
a check that can only pass. `--output text` renders a JSON boolean the way Python does, as **`True`** and
**`False`** with a capital letter. A case-sensitive `grep -c true` would count zero on a target whose
scale-out is genuinely suspended, report success, and tell you nothing — the same trap as the persistence
test described in Lab 1 Step 14, in one letter. Confirm it for yourself:

```bash
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --resource-ids "$RID" --query 'ScalableTargets[0].SuspendedState.*' --output text
```

Three words, each beginning with a capital letter.

Note that part 3 uses the shorthand rather than the document, deliberately, so that the file left in
`templates/` records the *suspended* configuration rather than the resumed one. A template that shows the
default state teaches nobody anything; a template that shows the intervention is a runbook page.

**Checkpoint 6**

```text
Suspension exercised and cleared
 ├── register-scalable-target --suspended-state   (there is no suspend-scaling call)
 ├── scale-in suspended, scale-out and scheduled left alone
 ├── all three policies and all four managed alarms UNCHANGED while suspended
 ├── resumed, and SuspendedState.* piped to grep -ci true returns 0
 └── templates/lab-04c-suspended-state.json committed as the runbook artefact
```

---

### Step 14 — Prove the whole scaling configuration survives a restart

**Purpose**

The same proof as Lab 2 Step 23, Lab 3 Step 19, Lab 04A Step 18 and Lab 04B Step 16, applied to this
lab's work. This lab's state spans four services — Application Auto Scaling, CloudWatch, ECS and IAM — and
a build that persists three of them but not the fourth leaves you with policies attached to a target that
no longer exists, or an alarm pointing at a policy ARN that has been reissued. Both failures are invisible
until something needs to scale.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, record the truth**

```bash
{
  aws application-autoscaling describe-scalable-targets \
    --service-namespace ecs --resource-ids "$RID" \
    --query 'ScalableTargets[0].[ServiceNamespace,ResourceId,ScalableDimension,MinCapacity,MaxCapacity]' \
    --output text
  aws application-autoscaling describe-scalable-targets \
    --service-namespace ecs --resource-ids "$RID" \
    --query 'ScalableTargets[0].SuspendedState.*' --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" \
    --query 'sort_by(ScalingPolicies,&PolicyName)[].[PolicyName,PolicyType]' --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" --policy-names "$CPU_POLICY" \
    --query 'ScalingPolicies[0].TargetTrackingScalingPolicyConfiguration.[TargetValue,ScaleOutCooldown,ScaleInCooldown,DisableScaleIn,PredefinedMetricSpecification.PredefinedMetricType]' \
    --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" --policy-names "$STEP_POLICY" \
    --query 'ScalingPolicies[0].StepScalingPolicyConfiguration.[AdjustmentType,MetricAggregationType,Cooldown,length(StepAdjustments)]' \
    --output text
  aws application-autoscaling describe-scheduled-actions \
    --service-namespace ecs --resource-id "$RID" \
    --query 'sort_by(ScheduledActions,&ScheduledActionName)[].[ScheduledActionName,Schedule,ScalableTargetAction.MinCapacity,ScalableTargetAction.MaxCapacity]' \
    --output text
  aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].[AlarmName,Namespace,MetricName,Threshold,ComparisonOperator,EvaluationPeriods,TreatMissingData,length(AlarmActions)]' \
    --output text
} > outputs/lab-04c-pre-restart.txt

cat outputs/lab-04c-pre-restart.txt
```

**Command — part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
source configs/lab-04a.env
source configs/lab-04b.env
```

`floci-down.sh` is `docker compose stop`. It stops the container and keeps the state. It is not
`docker compose down`, and it is emphatically not `docker compose down -v`, which would delete the volumes
and with them the entire course.

Note that the six shell variables this lab has been carrying — `RID`, `SDIM`, `CPU_POLICY`,
`REQ_POLICY`, `STEP_POLICY`, `QUEUE_ALARM` — survived, because the terminal did. That is precisely why
part 3 does not use them.

**Command — part 3, read it back, deriving the resource ID from the API again**

```bash
SVC_ARN=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].serviceArn' --output text)
RID=$(printf '%s' "${SVC_ARN##*:}")
SDIM=$(aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query "ScalableTargets[?ResourceId=='$RID'].ScalableDimension | [0]" --output text)
CPU_POLICY=$(aws application-autoscaling describe-scaling-policies --service-namespace ecs \
  --query "ScalingPolicies[?contains(PolicyName, 'cpu-target-tracking')].PolicyName | [0]" --output text)
STEP_POLICY=$(aws application-autoscaling describe-scaling-policies --service-namespace ecs \
  --query "ScalingPolicies[?PolicyType=='StepScaling'].PolicyName | [0]" --output text)
QUEUE_ALARM=$(aws cloudwatch describe-alarms --alarm-name-prefix usms-enrolment-queue \
  --query 'MetricAlarms[0].AlarmName' --output text)

echo "re-derived:"
printf '  %-16s %s\n' \
  "resource id" "$RID" \
  "dimension"   "$SDIM" \
  "cpu policy"  "$CPU_POLICY" \
  "step policy" "$STEP_POLICY" \
  "queue alarm" "$QUEUE_ALARM"

{
  aws application-autoscaling describe-scalable-targets \
    --service-namespace ecs --resource-ids "$RID" \
    --query 'ScalableTargets[0].[ServiceNamespace,ResourceId,ScalableDimension,MinCapacity,MaxCapacity]' \
    --output text
  aws application-autoscaling describe-scalable-targets \
    --service-namespace ecs --resource-ids "$RID" \
    --query 'ScalableTargets[0].SuspendedState.*' --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" \
    --query 'sort_by(ScalingPolicies,&PolicyName)[].[PolicyName,PolicyType]' --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" --policy-names "$CPU_POLICY" \
    --query 'ScalingPolicies[0].TargetTrackingScalingPolicyConfiguration.[TargetValue,ScaleOutCooldown,ScaleInCooldown,DisableScaleIn,PredefinedMetricSpecification.PredefinedMetricType]' \
    --output text
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs --resource-id "$RID" --policy-names "$STEP_POLICY" \
    --query 'ScalingPolicies[0].StepScalingPolicyConfiguration.[AdjustmentType,MetricAggregationType,Cooldown,length(StepAdjustments)]' \
    --output text
  aws application-autoscaling describe-scheduled-actions \
    --service-namespace ecs --resource-id "$RID" \
    --query 'sort_by(ScheduledActions,&ScheduledActionName)[].[ScheduledActionName,Schedule,ScalableTargetAction.MinCapacity,ScalableTargetAction.MaxCapacity]' \
    --output text
  aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].[AlarmName,Namespace,MetricName,Threshold,ComparisonOperator,EvaluationPeriods,TreatMissingData,length(AlarmActions)]' \
    --output text
} > outputs/lab-04c-post-restart.txt

diff outputs/lab-04c-pre-restart.txt outputs/lab-04c-post-restart.txt \
  && echo "PERSISTENCE PROVEN: the scalable target with its bounds and its three suspension switches, all three scaling policies with their full configurations, both scheduled actions with their schedules and bounds, and the custom alarm with its threshold, its missing-data treatment and its one action are all unchanged" \
  || echo "PERSISTENCE FAILED: read the diff above, then run ./scripts/utilities/floci-storage-check.sh"
```

**What the command does**

Part 3's first five lines are the entire point of the step. **Every identifier is re-derived from the
API** rather than reused from the shell variables — which are still sitting there, correct, and would have
proved only that Bash remembers strings. That is exactly the mistake that made an earlier edition of this
course's persistence test worthless, described in Lab 1 Step 14.

Three of those derivations are worth reading:

- The resource ID comes from the service ARN by the same parameter expansion Step 5 used. It is derived
  from ECS, not from Application Auto Scaling, so a build that lost the scalable target entirely would
  still produce a correct `RID` and then fail loudly on the next call — which is the failure you want.
- `SDIM` is found by filtering the target list on the resource ID with `?ResourceId=='$RID'` and taking
  `| [0]`. A raw string literal in single quotes inside a JMESPath filter, in a double-quoted shell
  string so that `$RID` expands: the pattern from Lab 04B Step 7, in a new place.
- The policy names are found by *property* rather than by name: the step policy by
  `?PolicyType=='StepScaling'`, the CPU one by a `contains()` on its name. Finding an object by what it
  *is* rather than by what you called it is a better test, because it would still work if somebody had
  renamed it — and it would fail if somebody had changed its type, which is a thing you want to hear about.

**Seven facts across four services** are compared, not one. Note what is deliberately **not** in the
list: `runningCount`, `pendingCount`, the alarm's `StateValue`, and the scaling activity list. All four
are legitimately allowed to move across a restart — tasks may be restarted, alarms re-evaluate, and an
activity list is a log. Comparing a value that is allowed to change would make this check fail for the
wrong reason. **Compare the configuration, not the weather.**

**Expected result**

```text
re-derived:
  resource id      service/usms-ecs-cluster/usms-enrolment-svc
  dimension        ecs:service:DesiredCount
  cpu policy       usms-enrolment-cpu-target-tracking
  step policy      usms-enrolment-queue-step-out
  queue alarm      usms-enrolment-queue-high
PERSISTENCE PROVEN: the scalable target with its bounds and its three suspension switches, all three scaling policies with their full configurations, both scheduled actions with their schedules and bounds, and the custom alarm with its threshold, its missing-data treatment and its one action are all unchanged
```

**What to look for:** exactly that line. If you see `PERSISTENCE FAILED`, read the `diff` **before doing
anything else** — it names *which* of the seven facts did not survive, which is far more useful than a
general failure. Then run `./scripts/utilities/floci-storage-check.sh`.

One diff that is benign and worth knowing about in advance: on some builds the managed target tracking
alarms are recreated after a restart with **new UUIDs**. Those alarm names are not in the comparison, on
purpose, for exactly that reason — but if you added them, this is why it would fail.

**Checkpoint 7**

```text
Persistence proven for Lab 04C
 ├── resource ID re-derived from the ECS service's ARN, not read from a variable
 ├── policy names re-derived by TYPE and by name fragment, not read from variables
 ├── scalable target: bounds and all three suspension switches unchanged
 ├── three policies: names, types, target value, cooldowns, adjustment type, step count
 ├── two scheduled actions: names, schedules, and both bounds each
 └── the custom alarm: threshold, operator, evaluations, missing-data treatment, one action
```

---

### Step 15 — Close the loop: from one request to one new task

**Purpose**

Five laboratories have each built one layer, and this is the first step in the course from which the
whole thing is visible at once. Trace it, name every object on the path, and — the part that matters —
say which of them this lab created. The answer is going to be "one".

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
echo "== 1. The metric that would start it =="
aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'MetricAlarms[?contains(AlarmName, `AlarmHigh`)].[Namespace,MetricName,Threshold,ComparisonOperator]' \
  --output text
aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
  --query 'MetricAlarms[0].[Namespace,MetricName,Threshold,ComparisonOperator]' --output text

echo
echo "== 2. The policies those alarms invoke =="
aws application-autoscaling describe-scaling-policies --service-namespace ecs --resource-id "$RID" \
  --query 'ScalingPolicies[].[PolicyName,PolicyType]' --output text

echo
echo "== 3. The one integer they write, and its bounds =="
aws application-autoscaling describe-scalable-targets --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].[ResourceId,ScalableDimension,MinCapacity,MaxCapacity]' --output text

echo
echo "== 4. The service that reads it, and how long a new task takes to count =="
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[serviceName,desiredCount,runningCount,taskDefinition,healthCheckGracePeriodSeconds]' \
  --output text

echo
echo "== 5. Where a new task appears =="
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].networkConfiguration.awsvpcConfiguration.[subnets,securityGroups,assignPublicIp]' \
  --output text

echo
echo "== 6. Who registers it as a target, and where =="
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].loadBalancers[0].[targetGroupArn,containerName,containerPort]' --output text
aws elbv2 describe-target-health --target-group-arn "$USMS_TG_ARN" \
  --query 'TargetHealthDescriptions[].[Target.Id,Target.AvailabilityZone,TargetHealth.State]' --output text

echo
echo "== 7. And what this lab actually changed about any of that =="
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[taskDefinition,length(loadBalancers),length(deployments)]' --output text
```

**What the command does**

Seven blocks, one chain, and the seventh is the interesting one.

Blocks 1 to 3 are this lab. Blocks 4 to 6 are Labs 04A and 04B, unchanged. Block 7 prints the task
definition, the load balancer count and the deployment count — and every one of those three values is
exactly what Lab 04B left behind. **This lab registered no task definition revision, created no service,
attached no target group and started no deployment.** It added a control loop over an integer, and the
architecture underneath it did not notice.

That is worth saying out loud because it is the shape of the answer to a question interviewers ask: what
does auto scaling change about my application? Nothing. It changes how many copies of it there are.

**Expected result**

```text
== 1. The metric that would start it ==
AWS/ECS	CPUUtilization	50.0	GreaterThanThreshold
USMS/Enrolment	EnrolmentQueueDepth	100.0	GreaterThanOrEqualToThreshold

== 2. The policies those alarms invoke ==
usms-enrolment-cpu-target-tracking	TargetTrackingScaling
usms-enrolment-requests-target-tracking	TargetTrackingScaling
usms-enrolment-queue-step-out	StepScaling

== 3. The one integer they write, and its bounds ==
service/usms-ecs-cluster/usms-enrolment-svc	ecs:service:DesiredCount	2	10

== 4. The service that reads it, and how long a new task takes to count ==
usms-enrolment-svc	2	2	arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:2	60

== 5. Where a new task appears ==
subnet-09876fedcba543210	subnet-0aabbccdd11223344
sg-0aa11bb22cc33dd44
DISABLED

== 6. Who registers it as a target, and where ==
arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067	enrolment-api	80
10.0.3.117	us-east-1a	healthy
10.0.4.203	us-east-1b	healthy

== 7. And what this lab actually changed about any of that ==
arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:2	1	1
```

> Example output — your IDs will differ, and blocks 5 and 6 may be shorter on builds that do not start
> containers.

**Verify**

Read it as one sentence and check that every noun in it appears somewhere above:

```text
A student clicks Register.
  Requests per target rises past 1000, or the work queue passes 100.        (block 1)
  An alarm fires and invokes a policy.                                      (blocks 1, 2)
  The policy writes desiredCount, clamped to 2..10.                         (block 3)
  ECS starts a task from usms-enrolment:2.                                  (block 4)
  The task gets an ENI in usms-private-subnet-a or -b, no public address.   (block 5)
  usms-enrolment-sg admits tcp/80 from usms-alb-sg only.                    (Lab 04B)
  The SERVICE registers its address in usms-enrolment-tg.                   (block 6)
  The load balancer health-checks it; after 60s of grace it takes traffic.  (blocks 4, 6)
  Nothing about the blueprint, the service or the load balancer changed.    (block 7)
```

Nine lines. **This laboratory is responsible for three of them.** Write that sentence in
`notes/lab-04c-notes.md`; it is Review Question 1 and it is the most useful thing in this document.

If block 6 is empty, your build does not start containers and the chain is proven from the control-plane
blocks; say so. If block 7's task definition does not end `:2` or the deployment count is not `1`,
something in this lab disturbed Lab 04B's work and you should find out what before Section 9 tells you.

---

### Step 16 — Write `configs/lab-04c.env`

**Purpose**

Every shell variable in this terminal dies when you close it, and this lab created eight things whose
names and ARNs matter. The CloudWatch lab reads three of them and the CloudFormation lab re-declares all
of them. Record them **by lookup, not from the variables**, so that a populated value in the file is
evidence the resource actually exists.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-04c.env << EOF
# Lab 04C — ECS service auto scaling outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs, ARNs and numbers only. NO SECRETS. Safe to commit.
#
# Sourced alongside lab-01/02/03/04a/04b. The CloudWatch lab reads the alarm and the
# custom metric; the CloudFormation lab re-declares every object named here.

export USMS_SCALABLE_NAMESPACE=ecs
export USMS_SCALABLE_RESOURCE_ID=$(aws ecs describe-services \
  --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].serviceArn' --output text | awk -F: '{print \$NF}')
export USMS_SCALABLE_DIMENSION=ecs:service:DesiredCount
export USMS_SCALE_MIN=$(aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --query 'ScalableTargets[0].MinCapacity' --output text)
export USMS_SCALE_MAX=$(aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --query 'ScalableTargets[0].MaxCapacity' --output text)

export USMS_POLICY_CPU_TT=usms-enrolment-cpu-target-tracking
export USMS_POLICY_CPU_TT_ARN=$(aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --policy-names usms-enrolment-cpu-target-tracking \
  --query 'ScalingPolicies[0].PolicyARN' --output text | grep -E '^arn:' || echo not-created)
export USMS_SCALE_TARGET_CPU=50
export USMS_POLICY_REQ_TT=usms-enrolment-requests-target-tracking
export USMS_POLICY_REQ_TT_ARN=$(aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --policy-names usms-enrolment-requests-target-tracking \
  --query 'ScalingPolicies[0].PolicyARN' --output text | grep -E '^arn:' || echo not-created)
export USMS_SCALE_TARGET_REQUESTS=1000
export USMS_POLICY_STEP_OUT=usms-enrolment-queue-step-out
export USMS_POLICY_STEP_OUT_ARN=$(aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --policy-names usms-enrolment-queue-step-out \
  --query 'ScalingPolicies[0].PolicyARN' --output text | grep -E '^arn:' || echo not-created)

export USMS_SCALE_OUT_COOLDOWN=60
export USMS_SCALE_IN_COOLDOWN=300

export USMS_ALARM_QUEUE_HIGH=usms-enrolment-queue-high
export USMS_METRIC_NAMESPACE=USMS/Enrolment
export USMS_METRIC_NAME=EnrolmentQueueDepth
export USMS_METRIC_DIMENSION=Service=enrolment

export USMS_SCHEDULED_OUT=usms-enrolment-morning-scale-out
export USMS_SCHEDULED_IN=usms-enrolment-evening-scale-in

export USMS_ASA_SLR=AWSServiceRoleForApplicationAutoScaling_ECSService
EOF

grep -n 'export .*=$\|=None$' configs/lab-04c.env || echo "all values populated"
```

**What the command does**

Unquoted heredoc — `<< EOF`, not `<< 'EOF'` — for the same reason as Lab 2 Step 24, Lab 3 Step 22, Lab
04A Step 20 and Lab 04B Step 18: every `$(...)` must run **now** and the resulting value must land on
disk. Had this been quoted, the file would contain the text of six API calls, and
`source configs/lab-04c.env` would re-run all of them in every new terminal you ever open. That is the
sixth appearance of this rule in five laboratories, in its sixth context, and it is deliberate: it
remains the most common silent bug in the whole course.

Three lines in there repay a close look.

**`awk -F: '{print \$NF}'` has an escaped dollar.** The heredoc is unquoted, so `$NF` would be expanded by
the shell — to nothing, since it is not a shell variable — and `awk` would receive `{print }` and print
the whole line. Escaping it as `\$NF` passes a literal dollar through to `awk`. This is the one place in
the course where you *want* a dollar sign to survive an unquoted heredoc, and it is why the check below
counts differently from Lab 04A's.

**`| grep -E '^arn:' || echo not-created` is a deliberate fallback, not a swallowed error.** If the
request-count policy could not be created because your build does not implement
`ALBRequestCountPerTarget`, `describe-scaling-policies` returns an empty list, `--output text` prints
`None`, and `grep -E '^arn:'` rejects it — so the file records the string `not-created` rather than
`None`. That matters because the empty-value check greps for `None` and would otherwise flag a limitation
you have already recorded as though it were a mistake. A file that says `not-created` is telling you
something true; a file that says `None` is ambiguous between "unsupported" and "you skipped a step".

**`USMS_SCALE_MIN` and `USMS_SCALE_MAX` are read back rather than hard-coded as 2 and 10.** If the
"Your turn" in Step 11 fired and left the floor at 6, this file says 6 and Section 9's script disagrees
with it visibly. A file that quietly claims what you intended rather than what exists is worse than no
file.

**Verify**

```bash
source configs/lab-04c.env

printf '%-30s %s\n' \
  "resource id"        "$USMS_SCALABLE_RESOURCE_ID" \
  "dimension"          "$USMS_SCALABLE_DIMENSION" \
  "bounds"             "$USMS_SCALE_MIN .. $USMS_SCALE_MAX" \
  "cpu policy"         "$USMS_POLICY_CPU_TT" \
  "cpu policy arn"     "$USMS_POLICY_CPU_TT_ARN" \
  "requests policy"    "$USMS_POLICY_REQ_TT" \
  "requests policy arn" "$USMS_POLICY_REQ_TT_ARN" \
  "step policy"        "$USMS_POLICY_STEP_OUT" \
  "alarm"              "$USMS_ALARM_QUEUE_HIGH" \
  "custom metric"      "$USMS_METRIC_NAMESPACE / $USMS_METRIC_NAME" \
  "scheduled out / in" "$USMS_SCHEDULED_OUT / $USMS_SCHEDULED_IN" \
  "service-linked role" "$USMS_ASA_SLR"

grep -c '^export' configs/lab-04c.env

echo "-- the resource id must match what the API says, right now --"
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[0].ResourceId' --output text
```

**What to look for:** `all values populated`, twelve non-empty lines, and a count of **22** exported
variables. `bounds` must read `2 .. 10`. `resource id` must be identical to the last line of output —
three segments beginning `service/` — because a file whose central identifier disagrees with the API is a
file that will produce a confusing failure in the CloudWatch lab rather than here.

`requests policy arn` reading `not-created` is acceptable and is the documented limitation from Step 9.
Any other value that is not an ARN beginning `arn:aws:autoscaling:` is not acceptable — find out which
step did not take.

---

### Step 17 — Commit, and repair two stale strings

**Purpose**

Same discipline as every lab: look first, stage explicitly, then commit. And one extra piece of
housekeeping, because §1 promised it: the cleanup scripts Labs 04A and 04B shipped name a file this lab
does not create.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, repair the two hint strings**

```bash
grep -n 'lab-04-cleanup.sh' scripts/cleanup/lab-04a-cleanup.sh scripts/cleanup/lab-04b-cleanup.sh \
  || echo "nothing to repair — your copies already say lab-04c-cleanup.sh"
```

**What the command does**

Both scripts print a message telling the student to run `scripts/cleanup/lab-04-cleanup.sh` before
running themselves. Neither script *executes* that name — they only print it — so nothing is broken today.
But a printed instruction that names a file which does not exist is a defect, and it will be read at the
end of the course by somebody in a hurry.

If the `grep` found lines, fix them, and note that the fix is a text substitution in a script whose
behaviour does not change:

```bash
for f in scripts/cleanup/lab-04a-cleanup.sh scripts/cleanup/lab-04b-cleanup.sh; do
  cp "$f" "$f.bak-$(date +%Y%m%d%H%M%S)"
  python3 - "$f" << 'PY'
import sys
p = sys.argv[1]
s = open(p).read()
n = s.count('lab-04-cleanup.sh')
s = s.replace('lab-04-cleanup.sh', 'lab-04c-cleanup.sh')
open(p, 'w').write(s)
print(f"{p}: {n} occurrence(s) updated")
PY
  bash -n "$f" && echo "  $f still parses"
done

grep -n 'lab-04c-cleanup.sh' scripts/cleanup/lab-04a-cleanup.sh scripts/cleanup/lab-04b-cleanup.sh
```

`python3` does the substitution rather than `sed -i`, for the reason the course has given twice already:
GNU `sed` and BSD `sed` disagree about whether `-i` takes an argument, and a `sed -i` that works on Linux
appends a file called `-e` on macOS. Every file is backed up first, and `bash -n` confirms the script
still parses — because a text substitution inside a destructive script is exactly the kind of change that
deserves a syntax check.

Add the two backups to your cleanup list; they are working files, not artefacts.

**Command — part 2, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-04c-scaling-proof.txt
git ls-files outputs/
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears in `git status --short`.
- No `.env` at the repository root appears.
- No `.bak-*` file appears — if one does, it is because `scripts/` is tracked and your backups are inside
  it. Delete them once you are satisfied, or add `*.bak-*` to `.gitignore` and prove it with
  `git check-ignore -v`.
- `configs/lab-04c.env` **does** appear. It holds names, ARNs and numbers — no secrets.
- `git check-ignore -v` names the file, the rule and the line number. **Silence there means the file is
  not ignored** — stop and fix `.gitignore` before committing anything at all.
- `git ls-files outputs/` lists `outputs/.gitkeep` and nothing else.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-04c-scaling-proof.txt
outputs/.gitkeep
```

> Example output — your line number may differ.

If `check-ignore` prints nothing, the rule is wrong. It must be `outputs/*` with `!outputs/.gitkeep`,
never `outputs/` with `!outputs/.gitkeep` — Git cannot re-include a file whose parent directory is
excluded, so the negation silently does nothing and your `.gitkeep` disappears from the repository while
your secrets stay ignored for the wrong reason.

**Command — part 3, commit**

```bash
git add labs/lab-04c-ecs-autoscaling/ \
        configs/lab-04c.env \
        templates/lab-04c-target-tracking-cpu.json \
        templates/lab-04c-target-tracking-requests.json \
        templates/lab-04c-step-scaling-out.json \
        templates/lab-04c-suspended-state.json \
        scripts/utilities/verify-lab-04c.sh \
        scripts/cleanup/lab-04c-cleanup.sh \
        scripts/cleanup/lab-04a-cleanup.sh \
        scripts/cleanup/lab-04b-cleanup.sh

git status --short

git commit -m "Lab 04C: auto scaling for usms-enrolment-svc — scalable target, two target tracking policies, a step policy with its alarm, and two scheduled actions

Also corrects the cleanup-order hint in the Lab 04A and 04B cleanup scripts, which
named lab-04-cleanup.sh; this lab ships lab-04c-cleanup.sh."

git log --oneline -7
```

The `git add` names paths explicitly rather than using `git add -A`. That is not fussiness: `git add -A`
stages whatever happens to be in the working tree, which is exactly how an un-ignored secret — or a
`.bak-*` file — reaches a commit and, from there, a remote.

The commit message has a body, and the body explains **why** two files this lab did not create are in the
commit. A reviewer seeing `lab-04a-cleanup.sh` in a Lab 04C commit will ask; answering in the message is
cheaper than answering in a comment thread three days later.

The two script paths in `scripts/` only exist after Section 9. If you commit before building them, drop
those two lines and add them in a second commit.

**Expected result**

```text
[main 7d29a51] Lab 04C: auto scaling for usms-enrolment-svc — scalable target, two target tracking policies, a step policy with its alarm, and two scheduled actions
 10 files changed, 291 insertions(+), 2 deletions(-)
```

> Example output — your hash and counts will differ. The two deletions are the two hint strings.

**Checkpoint 8**

```text
Lab 04C recorded
 ├── configs/lab-04c.env       committed, 22 exports, fully populated
 ├── templates/               two target tracking configs, one step config, one suspended state
 ├── scripts/                 verify-lab-04c.sh and lab-04c-cleanup.sh
 ├── scripts/cleanup/04a,04b  hint strings corrected, backed up, and still parsing
 ├── outputs/                 nothing staged; check-ignore names the rule that protected you
 └── git log shows Lab 01, 02, 03, 04A, 04B and 04C commits
```

---

## 9. Verification

### 9.1 What this script checks that a naive one would not

Eight of the checks below are the ones worth having, and they are why "does a scaling policy exist" is
not enough:

- **`no suspension switch was left true`** — a target left with scale-out suspended after an incident is
  a service that will not grow during the next one, and nothing anywhere else in the account will
  mention it. This is the single most valuable check in the script.
- **`the resource ID is service/<cluster>/<service>`** — a target registered at a resource ID built by
  hand, with a typo, is a perfectly valid object that will never do anything. It passes every existence
  check.
- **`exactly ONE scalable target`** — the same fault seen from the other side. Two targets means one of
  them is silently inert.
- **`the alarm invokes the step policy`** — the link *you* made, as opposed to the two AWS made. If it is
  broken the policy still exists, still describes correctly, and never fires.
- **`the step policy has an open-ended top interval`** — a step table whose last interval has an upper
  bound has a metric range in which nothing happens at all, and the range in question is "worse than we
  planned for".
- **`desiredCount is inside the bounds`** — catches a manual `update-service` above the ceiling, which
  ECS accepts and Application Auto Scaling will silently correct at its next evaluation.
- **`desiredCount is at the baseline`** — catches a Step 11 or Step 12 experiment that was never undone.
- **`no document contains an unexpanded variable`** — catches a quoted heredoc where an unquoted one was
  needed, which has now had six opportunities to appear across five laboratories.

And, as in every lab, the environment block comes first: a script that verifies only its own resources
passes right up until the restart that deletes them.

!!! info "One check deliberately reads a value it did not set"
    `MinCapacity is 2` asserts a number that came from `configs/lab-04a.env` rather than from this lab.
    That is on purpose. The floor of 2 is Lab 04A's architectural decision — one task per Availability
    Zone — and this lab merely enforces it. A check that asserted "the minimum is whatever this lab put
    there" would pass no matter what you put there, which is not a check.

### 9.2 Build `scripts/utilities/verify-lab-04c.sh`

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-04c.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 04C artefact exists and is configured correctly.
# Read-only: this script inspects and changes nothing. Safe to run at any time.
# Exit 0 if every check passes, 1 otherwise.
#
# EXPECTED: PASS=42  FAIL=0
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-04a.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-04b.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-04c.env" 2>/dev/null || true

# Defaults so that set -u cannot abort the script before it has told you anything.
: "${USMS_PRIVATE_SUBNET_A:=none}"
: "${USMS_PRIVATE_SUBNET_B:=none}"
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ECS_DESIRED_BASELINE:=2}"
: "${USMS_TG_NAME:=usms-enrolment-tg}"
: "${USMS_SCALABLE_DIMENSION:=ecs:service:DesiredCount}"
: "${USMS_POLICY_CPU_TT:=usms-enrolment-cpu-target-tracking}"
: "${USMS_POLICY_REQ_TT:=usms-enrolment-requests-target-tracking}"
: "${USMS_POLICY_STEP_OUT:=usms-enrolment-queue-step-out}"
: "${USMS_ALARM_QUEUE_HIGH:=usms-enrolment-queue-high}"
: "${USMS_METRIC_NAMESPACE:=USMS/Enrolment}"
: "${USMS_METRIC_NAME:=EnrolmentQueueDepth}"
: "${USMS_SCHEDULED_OUT:=usms-enrolment-morning-scale-out}"
: "${USMS_SCHEDULED_IN:=usms-enrolment-evening-scale-in}"
: "${USMS_SCALE_MIN:=2}"
: "${USMS_SCALE_MAX:=10}"

# The resource ID is derived, never trusted from the env file, for the reason Step 14 gives.
RID="${USMS_SCALABLE_RESOURCE_ID:-}"
if [ -z "$RID" ] || [ "$RID" = "None" ]; then
  SVC_ARN=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
              --services "$USMS_ENROLMENT_SERVICE" \
              --query 'services[0].serviceArn' --output text 2>/dev/null || echo "")
  RID="${SVC_ARN##*:}"
fi
[ -n "$RID" ] || RID="service/${USMS_ECS_CLUSTER}/${USMS_ENROLMENT_SERVICE}"
EXPECTED_RID="service/${USMS_ECS_CLUSTER}/${USMS_ENROLMENT_SERVICE}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# tgt <jmespath>            -> one field from the scalable target
tgt()  { aws application-autoscaling describe-scalable-targets --service-namespace ecs \
           --resource-ids "$RID" --query "ScalableTargets[0].$1" --output text; }
# pol <policy-name> <jmespath> -> one field from a scaling policy
pol()  { aws application-autoscaling describe-scaling-policies --service-namespace ecs \
           --resource-id "$RID" --policy-names "$1" --query "ScalingPolicies[0].$2" --output text; }
# sch <action-name> <jmespath> -> one field from a scheduled action
sch()  { aws application-autoscaling describe-scheduled-actions --service-namespace ecs \
           --resource-id "$RID" --scheduled-action-names "$1" \
           --query "ScheduledActions[0].$2" --output text; }
# svcq <jmespath>           -> one field from the ECS service
svcq() { aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
           --services "$USMS_ENROLMENT_SERVICE" --query "services[0].$1" --output text; }
# alm <jmespath>            -> one field from the custom alarm
alm()  { aws cloudwatch describe-alarms --alarm-names "$USMS_ALARM_QUEUE_HIGH" \
           --query "MetricAlarms[0].$1" --output text; }

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Lab 02 to 04B dependencies =="
check "usms-private-subnet-a exists" "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_A"
check "usms-private-subnet-b exists" "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_B"
check "cluster $USMS_ECS_CLUSTER is ACTIVE" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "service $USMS_ENROLMENT_SERVICE is ACTIVE" "test \"\$(svcq status)\" = ACTIVE"
check "service still has exactly ONE loadBalancers entry" \
  "test \"\$(svcq 'length(loadBalancers)')\" = 1"
check "target group $USMS_TG_NAME still has target type ip" \
  "test \"\$(aws elbv2 describe-target-groups --names $USMS_TG_NAME --query 'TargetGroups[0].TargetType' --output text)\" = ip"

echo "== Lab 04C scalable target =="
check "exactly ONE scalable target in the ecs namespace" \
  "test \"\$(aws application-autoscaling describe-scalable-targets --service-namespace ecs --query 'length(ScalableTargets)' --output text)\" = 1"
check "the resource ID is $EXPECTED_RID" "test \"\$(tgt ResourceId)\" = \"$EXPECTED_RID\""
check "the scalable dimension is ecs:service:DesiredCount" \
  "test \"\$(tgt ScalableDimension)\" = ecs:service:DesiredCount"
check "MinCapacity is the Lab 04A baseline of $USMS_ECS_DESIRED_BASELINE" \
  "test \"\$(tgt MinCapacity)\" = $USMS_ECS_DESIRED_BASELINE"
check "MaxCapacity is 10" "test \"\$(tgt MaxCapacity)\" = 10"
check "NO suspension switch was left true" \
  "test \"\$(tgt 'SuspendedState.*' | grep -ci true)\" = 0"

echo "== Lab 04C scaling policies =="
check "CPU target tracking policy $USMS_POLICY_CPU_TT exists" \
  "pol $USMS_POLICY_CPU_TT PolicyName | grep -qx $USMS_POLICY_CPU_TT"
check "its policy type is TargetTrackingScaling" \
  "test \"\$(pol $USMS_POLICY_CPU_TT PolicyType)\" = TargetTrackingScaling"
check "its predefined metric is ECSServiceAverageCPUUtilization" \
  "test \"\$(pol $USMS_POLICY_CPU_TT 'TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType')\" = ECSServiceAverageCPUUtilization"
check "its target value is 50" \
  "test \"\$(pol $USMS_POLICY_CPU_TT 'TargetTrackingScalingPolicyConfiguration.TargetValue' | cut -d. -f1)\" = 50"
check "scale-out cooldown 60 and scale-in cooldown 300 (deliberately asymmetric)" \
  "test \"\$(pol $USMS_POLICY_CPU_TT 'TargetTrackingScalingPolicyConfiguration.ScaleOutCooldown')\" = 60 && test \"\$(pol $USMS_POLICY_CPU_TT 'TargetTrackingScalingPolicyConfiguration.ScaleInCooldown')\" = 300"
check "step scaling policy $USMS_POLICY_STEP_OUT exists with type StepScaling" \
  "test \"\$(pol $USMS_POLICY_STEP_OUT PolicyType)\" = StepScaling"
check "the step policy has 2+ adjustments and an OPEN-ENDED top interval" \
  "test \"\$(pol $USMS_POLICY_STEP_OUT 'length(StepScalingPolicyConfiguration.StepAdjustments)')\" -ge 2 && test \"\$(pol $USMS_POLICY_STEP_OUT 'StepScalingPolicyConfiguration.StepAdjustments[-1].MetricIntervalUpperBound')\" = None"

echo "== Lab 04C alarms =="
check "custom alarm $USMS_ALARM_QUEUE_HIGH exists" "alm AlarmName | grep -qx $USMS_ALARM_QUEUE_HIGH"
check "it watches $USMS_METRIC_NAMESPACE $USMS_METRIC_NAME" \
  "test \"\$(alm Namespace)\" = '$USMS_METRIC_NAMESPACE' && test \"\$(alm MetricName)\" = '$USMS_METRIC_NAME'"
check "it INVOKES the step policy (the link you made yourself)" \
  "alm 'AlarmActions[]' | grep -q 'policyName/$USMS_POLICY_STEP_OUT'"
check "target tracking created 2+ managed alarms for you" \
  "test \"\$(aws cloudwatch describe-alarms --alarm-name-prefix 'TargetTracking-$RID' --query 'length(MetricAlarms)' --output text)\" -ge 2"

echo "== Lab 04C scheduled actions =="
check "morning action $USMS_SCHEDULED_OUT exists" \
  "sch $USMS_SCHEDULED_OUT ScheduledActionName | grep -qx $USMS_SCHEDULED_OUT"
check "evening action $USMS_SCHEDULED_IN exists" \
  "sch $USMS_SCHEDULED_IN ScheduledActionName | grep -qx $USMS_SCHEDULED_IN"
check "the morning action raises the floor ABOVE the evening action's" \
  "test \"\$(sch $USMS_SCHEDULED_OUT 'ScalableTargetAction.MinCapacity')\" -gt \"\$(sch $USMS_SCHEDULED_IN 'ScalableTargetAction.MinCapacity')\""

echo "== Lab 04C service state =="
check "desiredCount is INSIDE the scalable target's bounds" \
  "test \"\$(svcq desiredCount)\" -ge \"\$(tgt MinCapacity)\" && test \"\$(svcq desiredCount)\" -le \"\$(tgt MaxCapacity)\""
check "desiredCount is back at the baseline of $USMS_ECS_DESIRED_BASELINE" \
  "test \"\$(svcq desiredCount)\" = $USMS_ECS_DESIRED_BASELINE"
check "exactly ONE deployment (nothing stuck mid-roll)" \
  "test \"\$(svcq 'length(deployments)')\" = 1"

echo "== Lab 04C custom metric =="
check "the $USMS_METRIC_NAMESPACE namespace has at least one metric" \
  "test \"\$(aws cloudwatch list-metrics --namespace '$USMS_METRIC_NAMESPACE' --query 'length(Metrics)' --output text)\" -ge 1"

echo "== Files and Git hygiene =="
check "configs/lab-04c.env exists" "test -f configs/lab-04c.env"
check "configs/lab-04c.env has no empty values and no None" \
  "! grep -qE 'export [A-Z_]+=\$|=None\$' configs/lab-04c.env"
check "target tracking (cpu) document is valid JSON" \
  "python3 -m json.tool templates/lab-04c-target-tracking-cpu.json"
check "target tracking (requests) document is valid JSON, or absent" \
  "! test -f templates/lab-04c-target-tracking-requests.json || python3 -m json.tool templates/lab-04c-target-tracking-requests.json"
check "step scaling document is valid JSON" \
  "python3 -m json.tool templates/lab-04c-step-scaling-out.json"
check "suspended-state document is valid JSON and does NOT suspend scale-out" \
  "python3 -c \"import json,sys;d=json.load(open('templates/lab-04c-suspended-state.json'));sys.exit(0 if d.get('DynamicScalingOutSuspended') is False else 1)\""
check "no Lab 04C document contains an unexpanded variable" \
  "! grep -l '[\$]' templates/lab-04c-*.json"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"

if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

A failure under "== Environment ==" is the real problem, and most failures below it are
a consequence. Fix that block first:
  ./scripts/utilities/floci-storage-check.sh

A failure under "== Lab 02 to 04B dependencies ==" means an earlier lab's resource is
gone or has been changed. Run verify-lab-04a.sh and verify-lab-04b.sh before re-reading
anything here. Remember that verify-lab-04a.sh is EXPECTED to report exactly one
failure, on the usms-app-sg source check, unless you did Lab 04B's Exercise 2.

Two failures are worth reading twice because they are silent in production:
  "NO suspension switch was left true"  -- a suspended target does not scale and does
                                           not say so. Step 13 part 3 clears it.
  "desiredCount is back at the baseline" -- a Step 11 or Step 12 experiment was not
                                           undone. Push the metric down FIRST, then set
                                           the count; see Step 12 part 6.
REMEDY
fi

[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-04c.sh
bash -n scripts/utilities/verify-lab-04c.sh && echo "syntax OK"
./scripts/utilities/verify-lab-04c.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Lab 02 to 04B dependencies ==
  ok   usms-private-subnet-a exists
  ...
== Lab 04C scalable target ==
  ok   exactly ONE scalable target in the ecs namespace
  ok   the resource ID is service/usms-ecs-cluster/usms-enrolment-svc
  ok   MinCapacity is the Lab 04A baseline of 2
  ok   NO suspension switch was left true
== Lab 04C scaling policies ==
  ok   its target value is 50
  ok   scale-out cooldown 60 and scale-in cooldown 300 (deliberately asymmetric)
  ok   the step policy has 2+ adjustments and an OPEN-ENDED top interval
== Lab 04C alarms ==
  ok   it INVOKES the step policy (the link you made yourself)
  ok   target tracking created 2+ managed alarms for you
  ...
== Files and Git hygiene ==
  ok   no Lab 04C document contains an unexpanded variable
  ok   no secret is tracked by git

PASS=42  FAIL=0
```

> Example output — the middle is abbreviated; you will see all 42.

**The expected count is `PASS=42  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `target tracking created 2+ managed alarms for you` | Some builds do not create the managed alarms. Confirm with `describe-scaling-policies --query 'ScalingPolicies[].Alarms'` and record it; nothing in this lab depends on them existing, only on your understanding of them |
| `it INVOKES the step policy` | Some builds accept `--alarm-actions` and do not store it. Confirm with `describe-alarms --output json` and record it. On real AWS this failing would mean the policy can never fire |
| `the $USMS_METRIC_NAMESPACE namespace has at least one metric` | Some builds accept `put-metric-data` and do not index the metric for `list-metrics`. Confirm with `get-metric-statistics` and record which |
| `the morning action raises the floor ABOVE the evening action's` | Only if `describe-scheduled-actions` is unimplemented, in which case both sides of the comparison are empty and the test aborts. Check whether Step 11's actions exist at all |
| `exactly ONE deployment` | Some builds report zero deployments rather than one. Check with `--query 'services[0].deployments'` and record which it is |
| `NO suspension switch was left true` | **Not benign.** Step 13 part 3 did not run, or ran with the wrong document. Fix it — this is the check that exists to catch a real production hazard |
| `desiredCount is back at the baseline` | **Not benign.** An experiment was not undone. Step 12 part 6 has the correct order: metric down first, then the count |
| `MinCapacity is the Lab 04A baseline of 2` | **Not benign.** Either Step 11's "Your turn" left the floor raised, or `USMS_ECS_DESIRED_BASELINE` in `configs/lab-04a.env` is not 2 and you have a disagreement between two labs to resolve |

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** both scheduled actions, all three scaling policies (and, as a side effect,
    the four CloudWatch alarms target tracking created), the custom alarm `usms-enrolment-queue-high`,
    and the scalable target's registration.

    **What depends on it:** nothing later in the course *requires* the scaling to exist — but the
    CloudWatch lab reads this lab's custom alarm and its scaling activities, and the CloudFormation lab
    re-declares every object in `configs/lab-04c.env` as a template and compares it with what you built
    by hand. Deleting the scaling early means both of those labs lose their subject.

    **Reversible?** Yes, more easily than anything else in this course. Every object is created by one
    idempotent command from a document in `templates/`, and `configs/lab-04c.env` holds every name. You
    would repeat Steps 5 to 11, which is about fifteen minutes.

    **Effect on later labs:** the CloudWatch and CloudFormation labs lose material. Nothing breaks.

    Run it only at the end of the course, and run the cleanup scripts in this order:

    ```text
    scripts/cleanup/lab-04c-cleanup.sh   (this one — scaling configuration ONLY)
    scripts/cleanup/lab-04b-cleanup.sh   (load balancer, and the service)
    scripts/cleanup/lab-04a-cleanup.sh   (cluster, task definitions, roles, log group)
    scripts/cleanup/lab-03-cleanup.sh
    scripts/cleanup/lab-02-cleanup.sh
    ```

    **This one goes first**, and both of the next two enforce it: each of them refuses to run while a
    scalable target still exists for `service/usms-ecs-cluster/usms-enrolment-svc`, because deleting the
    service out from under a scalable target leaves an orphaned registration that is easy to forget and
    impossible to explain later. Those two scripts print the name `lab-04c-cleanup.sh` only if you did
    Step 17 part 1; if you skipped it they still say `lab-04-cleanup.sh`, which is the file that does not
    exist.

    It requires you to type `DELETE USMS SCALING` in full before it does anything.

**Run from**

```text
aws-floci-course/
```

````bash
cat > scripts/cleanup/lab-04c-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 04C, dependencies first.
# Order: scheduled actions -> scaling policies -> the custom alarm -> deregister the target.
# Run FIRST of the 04 cleanups: lab-04b-cleanup.sh and lab-04a-cleanup.sh both REFUSE
# while a scalable target still exists for this service.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04a.env"
source "$REPO_ROOT/configs/lab-04c.env"

cat <<'WARN'
============================================================
  This deletes the USMS enrolment service's SCALING only:
    - both scheduled actions
    - all three scaling policies, and with them the four
      CloudWatch alarms target tracking created for you
    - the custom alarm usms-enrolment-queue-high
    - the scalable target registration

  It does NOT touch the ECS service, the task definition,
  the cluster, the load balancer or the target group. After
  this runs, usms-enrolment-svc stays exactly as it is at
  desiredCount 2 -- it simply has nothing deciding to
  change that number.

  The CloudWatch lab and the CloudFormation lab use parts
  of this. None of it is reversible from here, but all of
  it is rebuildable from templates/ in about 15 minutes.

  Run FIRST of the 04 cleanups, then lab-04b, then lab-04a.
============================================================
WARN

read -r -p 'Type exactly: DELETE USMS SCALING  > ' answer
[ "$answer" = "DELETE USMS SCALING" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }

NS="$USMS_SCALABLE_NAMESPACE"
RID="$USMS_SCALABLE_RESOURCE_ID"
DIM="$USMS_SCALABLE_DIMENSION"

say "scheduled actions first: a calendar entry that fires after the target is gone is an error nobody sees"
for a in "$USMS_SCHEDULED_OUT" "$USMS_SCHEDULED_IN"; do
  aws application-autoscaling delete-scheduled-action \
    --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" \
    --scheduled-action-name "$a" >/dev/null 2>&1 \
    && echo "   deleted $a" || echo "   $a already gone"
done

say "any OTHER scheduled action left behind by an exercise or a Your turn"
for a in $(aws application-autoscaling describe-scheduled-actions \
             --service-namespace "$NS" --resource-id "$RID" \
             --query 'ScheduledActions[].ScheduledActionName' --output text 2>/dev/null || true); do
  aws application-autoscaling delete-scheduled-action \
    --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" \
    --scheduled-action-name "$a" >/dev/null 2>&1 && echo "   deleted $a" || true
done

say "scaling policies: deleting a target tracking policy also deletes ITS managed alarms"
for p in $(aws application-autoscaling describe-scaling-policies \
             --service-namespace "$NS" --resource-id "$RID" \
             --query 'ScalingPolicies[].PolicyName' --output text 2>/dev/null || true); do
  aws application-autoscaling delete-scaling-policy \
    --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" \
    --policy-name "$p" >/dev/null 2>&1 \
    && echo "   deleted $p" || echo "   $p already gone"
done

say "the alarm YOU wrote: nothing deletes this for you, because nothing created it for you"
aws cloudwatch delete-alarms --alarm-names "$USMS_ALARM_QUEUE_HIGH" >/dev/null 2>&1 \
  && echo "   deleted $USMS_ALARM_QUEUE_HIGH" || echo "   already gone"

say "any managed alarm the policy deletions did not take with them"
LEFT=$(aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-$RID" \
         --query 'MetricAlarms[].AlarmName' --output text 2>/dev/null || true)
if [ -n "$LEFT" ] && [ "$LEFT" != "None" ]; then
  # shellcheck disable=SC2086
  aws cloudwatch delete-alarms --alarm-names $LEFT >/dev/null 2>&1 \
    && echo "   deleted orphaned managed alarms" || true
else
  echo "   none left"
fi

say "deregister the scalable target LAST: it would take the policies with it, which hides what happened"
aws application-autoscaling deregister-scalable-target \
  --service-namespace "$NS" --resource-id "$RID" --scalable-dimension "$DIM" >/dev/null 2>&1 \
  && echo "   deregistered $RID" || echo "   already deregistered"

say "what is deliberately NOT deleted"
cat <<'KEPT'
   AWSServiceRoleForApplicationAutoScaling_ECSService
     One per account, shared by every ECS service that ever scales. Removing it
     is `aws iam delete-service-linked-role`, and it is the account owner's
     decision rather than a lab's.

   The USMS/Enrolment custom metric
     CloudWatch metrics CANNOT be deleted. They stop being published, and the
     datapoints expire on CloudWatch's own retention schedule. If you were
     expecting a delete-metric call, there is not one, and that is worth
     remembering before you invent a metric name you will regret.

   usms-enrolment-svc, its task definition, its cluster, its load balancer
     Untouched. lab-04b-cleanup.sh and lab-04a-cleanup.sh own those, in that
     order, and they will now agree to run.
KEPT

echo
echo "Lab 04C teardown complete. scripts/cleanup/lab-04b-cleanup.sh may now run."
EOF

chmod +x scripts/cleanup/lab-04c-cleanup.sh
bash -n scripts/cleanup/lab-04c-cleanup.sh && echo "syntax OK — do NOT run it"
````

**What to look for:** the words `syntax OK — do NOT run it`. `bash -n` parses a script without executing a
single command, and it is the only safe way to check a destructive one.

The order is the lesson, and it is a different lesson from Labs 04A and 04B — because here almost none of
it is enforced by the API, and the reasons are about *observability* rather than about dependencies:

1. **Scheduled actions first.** A scheduled action outliving its target is a calendar entry that will
   fire, fail, and log the failure somewhere nobody reads. Nothing prevents you leaving one behind, which
   is exactly why the script deletes them first and then sweeps for any others.
2. **Then the policies, one at a time and by name.** Deleting a target tracking policy takes its two
   managed alarms with it, which is the tidy behaviour you want and is also the reason the script does
   not delete the alarms first: it would be deleting objects that were about to be deleted anyway, and
   the output would not tell you which.
3. **Then the alarm you wrote.** Nothing deletes it for you, because nothing created it for you. That
   symmetry is worth noticing: in this service, the things AWS made on your behalf are cleaned up on your
   behalf, and the things you made are yours to clean up.
4. **Deregister the target last.** This is the important one. `deregister-scalable-target` **also deletes
   every policy and scheduled action attached to the target** — so a one-line teardown is possible and
   the script deliberately does not use it. Deleting things one at a time, with a line of output each,
   turns a teardown into a record of what was there. A single call that silently removes six objects is
   faster and tells you nothing.
5. **Do not delete the service-linked role, and do not try to delete the metric.** The first is an
   account-wide resource shared by every ECS service that scales. The second is not possible: CloudWatch
   has no `delete-metric` operation at all, which surprises everybody once and is worth knowing before
   you publish a custom metric with a name you would be embarrassed by.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, six env files sourced, `verify-lab-02/03/04b` all `FAIL=0` and `verify-lab-04a` at `FAIL=0` or its one documented failure, the service at desired 2 with one deployment, and your support path (A, B or C) recorded in `notes/lab-04c-notes.md` |
| 2 | Step 6 | Exactly one scalable target, at `service/usms-ecs-cluster/usms-enrolment-svc` with dimension `ecs:service:DesiredCount`, min 2 and max 10, its `RoleARN` filled in by AWS, all three suspension switches `false`, and no policies attached |
| 3 | Step 9 | Two target tracking policies on that target — CPU at 50.0 and requests at 1000.0 — each reporting two managed alarms, and the `ResourceLabel` validated at six segments beginning `app` with `targetgroup` fourth |
| 4 | Step 11 | A `StepScaling` policy with two adjustments and an open-ended top interval; `usms-enrolment-queue-high` watching `USMS/Enrolment` and naming the step policy in `AlarmActions`; two scheduled actions with a floor of 4 in the morning and 2 in the evening |
| 5 | Step 12 | Either a scaling activity whose `Cause` names both the alarm and the policy, **or** `outputs/lab-04c-scaling-proof.txt` recording the six-block chain and the reason the loop did not run; and the service back at desired 2 with the metric pushed down first |
| 6 | Step 13 | Suspension exercised with `register-scalable-target --suspended-state`, all three policies untouched while suspended, and `SuspendedState.*` piped to `grep -ci true` returning `0` |
| 7 | Step 14 | `PERSISTENCE PROVEN` after a Floci stop and start, with the resource ID and both policy names **re-derived from the API** and seven facts compared across four services |
| 8 | Step 17 | `configs/lab-04c.env` populated with 22 exports and committed; the two stale hint strings repaired, backed up and still parsing; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 11. Troubleshooting

??? danger "`ValidationException: Resource ID ... is not valid` on register-scalable-target"
    Almost always one of three things, in this order of frequency.

    **You passed the whole ARN.** `--resource-id` wants the suffix only:

    ```bash
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].serviceArn' --output text
    ```

    Take everything after the last colon. Step 5 part 1 does it with `"${SVC_ARN##*:}"`.

    **The ARN was in the legacy short format**, so the suffix has two segments rather than three. Count
    them:

    ```bash
    printf '%s' "${SVC_ARN##*:}" | awk -F/ '{print NF, $0}'
    ```

    `3 service/usms-ecs-cluster/usms-enrolment-svc` is right. `2 service/usms-enrolment-svc` means you
    must construct the ID from the two names instead, which is Step 5's fallback branch.

    **The cluster name is missing because a variable was empty.** `service//usms-enrolment-svc` has three
    segments and an empty middle one, and it is accepted by nothing. `echo "[$USMS_ECS_CLUSTER]"` and look
    for empty brackets.

??? danger "`ValidationException` naming the scalable dimension"
    `ecs:service:DesiredCount` is the only value ECS accepts and it is case-sensitive in a way that reads
    like a typo. `ecs:service:desiredCount` and `ecs:services:DesiredCount` are both rejected.

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --query 'ScalableTargets[].[ResourceId,ScalableDimension]' --output text
    ```

    If that returns two rows for what should be one service, you have registered a second target at a
    misspelled dimension. The last entry in this section removes it.

??? danger "The policy exists, the alarm goes to ALARM, and desiredCount does not move"
    Work through these five in order. On real AWS they account for almost every case.

    1. **The target is suspended.** The first thing to check and the most easily missed:

        ```bash
        aws application-autoscaling describe-scalable-targets --service-namespace ecs \
          --resource-ids "$RID" --query 'ScalableTargets[0].SuspendedState' --output json
        ```

    2. **The service is already at the ceiling.** A policy asking for 14 against a maximum of 10 does
       nothing, repeatedly, and reports success:

        ```bash
        aws application-autoscaling describe-scalable-targets --service-namespace ecs \
          --resource-ids "$RID" --query 'ScalableTargets[0].[MinCapacity,MaxCapacity]' --output text
        aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
          --query 'services[0].desiredCount' --output text
        ```

    3. **A cooldown is still in force.** A policy that scaled out 40 seconds ago will not scale out
       again for another 20, and nothing reports "in cooldown" as a state. The evidence is the previous
       activity's timestamp:

        ```bash
        aws application-autoscaling describe-scaling-activities --service-namespace ecs \
          --resource-id "$RID" --max-items 3 \
          --query 'ScalingActivities[].[StartTime,StatusCode,Cause]' --output text
        ```

    4. **The alarm does not actually name the policy.** Read the action rather than assuming it:

        ```bash
        aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
          --query 'MetricAlarms[0].AlarmActions' --output text
        ```

    5. **`--include-not-scaled-activities` is where the answer usually is.** Application Auto Scaling
       records the times it decided *not* to scale, with a reason, and that list is not returned by
       default:

        ```bash
        aws application-autoscaling describe-scaling-activities --service-namespace ecs \
          --resource-id "$RID" --include-not-scaled-activities \
          --query 'ScalingActivities[].[StartTime,StatusCode,NotScaledReasons]' --output json
        ```

    On Floci, `desiredCount` not moving is the expected behaviour on support path B. Record it and use
    Step 12 part 5's control-plane proof.

??? danger "The service scales to the maximum and stays there"
    Three causes, and the first is by far the most common.

    **A target tracking policy on a metric that does not fall as capacity rises.** Adding tasks does not
    reduce total request count, or queue arrival rate, or the number of items in a database. The
    arithmetic in the target tracking interlude divides by a number that never improves, so the computed
    capacity climbs until it hits the ceiling. Check which metric the policy is on:

    ```bash
    aws application-autoscaling describe-scaling-policies --service-namespace ecs \
      --resource-id "$RID" \
      --query 'ScalingPolicies[].[PolicyName,TargetTrackingScalingPolicyConfiguration.PredefinedMetricSpecification.PredefinedMetricType,TargetTrackingScalingPolicyConfiguration.TargetValue]' \
      --output text
    ```

    If it is a per-target or per-task metric, this is not your cause. If it is a total, the policy is
    wrong and no amount of tuning the target value will fix it.

    **A target value in the wrong unit.** `RequestCountPerTarget` is a per-minute sum. A target of 10,
    meant as 10 requests per second, is 600 times too aggressive and pins the service at the ceiling
    permanently.

    **A `MinCapacity` somebody raised and forgot.** Step 11's "Your turn" and Step 6's do this
    deliberately, and an incident at three in the morning does it accidentally.

??? danger "`ObjectNotFoundException` on put-scaling-policy"
    There is no scalable target at the address you named. The policy call takes the same three-part
    address as the registration, and all three parts must match exactly.

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --query 'ScalableTargets[].[ServiceNamespace,ResourceId,ScalableDimension]' --output text
    echo "you passed: ecs  $RID  $SDIM"
    ```

    A difference of one character in the resource ID is the usual answer. Note that Application Auto
    Scaling will not create a target implicitly, which is a good design: a policy attached to a target
    that does not exist would be a silent no-op.

??? danger "`ValidationError: Invalid metrics or alarm actions` on put-metric-alarm"
    You created the alarm before the policy, so the ARN in `--alarm-actions` names nothing. The order in
    Step 10 part 3 is policy first, then alarm, for exactly this reason.

    ```bash
    aws application-autoscaling describe-scaling-policies --service-namespace ecs \
      --resource-id "$RID" --policy-names "$STEP_POLICY" \
      --query 'ScalingPolicies[0].PolicyARN' --output text
    ```

    An `arn:aws:autoscaling:...` string means the policy exists; re-run `put-metric-alarm` with it. `None`
    means the policy does not, and you should re-run part 3's first command.

??? danger "`ValidationException` about overlapping or gapped step adjustments"
    The intervals in a step table must tile the range with no overlaps and no gaps, relative to the
    alarm threshold. These are the three mistakes:

    ```text
    lower 0  upper 100  |  lower 100 upper 200   -> a GAP above 200. Nothing happens there
    lower 0  upper 100  |  lower  50 (no upper)  -> an OVERLAP between 50 and 100
    lower 0  upper 100  |  lower 100 (no upper)  -> correct
    ```

    Read the table out loud as "how far past the threshold", and remember that a lower bound is
    inclusive and an upper bound is exclusive.

??? danger "A scheduled action never fires"
    Four causes, and the first two are the same mistake in two costumes.

    **The cron expression has five fields.** Application Auto Scaling wants **six** — the last is the
    year. `cron(45 7 ? * MON-FRI)` is rejected; `cron(45 7 ? * MON-FRI *)` is not.

    **Both day fields are specified.** One of `day-of-month` and `day-of-week` must be `?`.

    **The time zone is UTC and you meant local.** Check what was stored:

    ```bash
    aws application-autoscaling describe-scheduled-actions --service-namespace ecs \
      --resource-id "$RID" --query 'ScheduledActions[].[ScheduledActionName,Schedule,Timezone]' \
      --output text
    ```

    An empty or `UTC` time zone with a schedule you wrote in local time fires six hours late in Bhutan.

    **Scheduled scaling is suspended.** Check `SuspendedState.ScheduledScalingSuspended`.

??? danger "I have two scalable targets and one of them does nothing"
    This happens after a mistyped dimension or a hand-built resource ID. List them, decide which is
    wrong, and remove only that one.

    !!! danger "Read before running any delete command"
        **What will be deleted:** one scalable target registration, **and every scaling policy and
        scheduled action attached to it.** `deregister-scalable-target` cascades, which is convenient
        here and dangerous if you pick the wrong row.

        **What depends on it:** nothing, if it is the inert duplicate. Everything in this lab, if it is
        the real one.

        **Reversible?** The registration is one command. The policies and actions attached to it are not
        recovered by re-registering — you would repeat Steps 7 to 11 from `templates/`.

        **Effect on later labs:** none if you removed the duplicate. Total if you removed the real one,
        and the way to be sure is to check which one has policies attached before you touch either.

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --query 'ScalableTargets[].[ResourceId,ScalableDimension,MinCapacity,MaxCapacity]' --output text

    for r in $(aws application-autoscaling describe-scalable-targets --service-namespace ecs \
                 --query 'ScalableTargets[].ResourceId' --output text); do
      printf '%-60s policies=%s\n' "$r" \
        "$(aws application-autoscaling describe-scaling-policies --service-namespace ecs \
             --resource-id "$r" --query 'length(ScalingPolicies)' --output text)"
    done
    ```

    The row with `policies=0` is the duplicate. Deregister **that** one:

    ```bash
    aws application-autoscaling deregister-scalable-target \
      --service-namespace ecs \
      --resource-id "<the resource id with zero policies>" \
      --scalable-dimension "<its dimension, copied from the listing>"
    ```

    Then re-run `./scripts/utilities/verify-lab-04c.sh` and confirm the count is back to one.

??? danger "`AccessDeniedException` mentioning the service-linked role, on real AWS"
    You will not see this on Floci, and you should recognise it. It means Application Auto Scaling could
    not assume `AWSServiceRoleForApplicationAutoScaling_ECSService`, either because it does not exist or
    because an SCP or permissions boundary blocks `iam:CreateServiceLinkedRole`.

    ```bash
    aws iam get-role --role-name AWSServiceRoleForApplicationAutoScaling_ECSService \
      --query 'Role.[RoleName,Path]' --output text
    ```

    If it is missing, Step 4's command creates it. If creating it is refused, that is an
    organisation-level control and the answer is a conversation rather than a command.

??? danger "`verify-lab-04c.sh` fails on `NO suspension switch was left true`"
    Step 13 part 3 did not run, or ran with a document that had the wrong values. This is the check that
    exists to catch a genuine production hazard, so read the state rather than just clearing it:

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --resource-ids "$RID" --query 'ScalableTargets[0].SuspendedState' --output json
    ```

    Then clear it with the shorthand form from Step 13 part 3, and re-run the script.

??? danger "`verify-lab-04a.sh` or `verify-lab-04b.sh` fails after this lab"
    This lab modifies nothing either of them checks, with one exception: if `desiredCount` is not back at
    2, `verify-lab-04a.sh`'s baseline check and `verify-lab-04b.sh`'s deployment check can both fail.

    Compare against the run you captured in Step 2:

    ```bash
    ./scripts/utilities/verify-lab-04b.sh > outputs/lab-04c-post-verify-04b.txt
    diff outputs/lab-04c-pre-verify-04b.txt outputs/lab-04c-post-verify-04b.txt \
      && echo "Lab 04B is exactly as this lab found it"
    ```

    An empty diff is the result you want, and it is a stronger statement than `FAIL=0`: it says this lab
    changed nothing, rather than that nothing is broken.

??? danger "`An error occurred (NoCredentials)` or a suggestion to run `aws login`"
    Do **not** run `aws login`. It begins an interactive sign-in to **real AWS**, and this course's entire
    safety model rests on never touching a real account.

    In this terminal, right now:

    ```bash
    cd ~/aws-floci-course && source configs/course.env && ./scripts/utilities/whoami.sh
    ```

    Permanently: this is Errata 01, and the loader belongs in the startup file your **login** shell
    reads. `./scripts/utilities/floci-storage-check.sh` decides the question for you.

??? danger "`Could not connect to the endpoint URL`, or exit code 255"
    Floci is not running, or not listening on 4566.

    ```bash
    docker compose ps
    ./scripts/setup/floci-up.sh
    curl -s http://localhost:4566/_localstack/health | head -c 300
    ```

    That health output also lists which services this build has started, which is a faster second opinion
    than re-running Step 3's probe — look for the application auto scaling and CloudWatch entries.

??? danger "Everything is gone after a restart"
    Storage mode, as always.

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    If it reports `FLOCI_STORAGE_MODE=memory`, a stray `floci start` has replaced the Compose container.
    The work is not recoverable — restore from the snapshot you took at the end of Lab 04B, and this time
    confirm the storage check before building anything.

---

## 12. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `application-autoscaling register-scalable-target` | Full, including tags and suspended state | Object stored and returned on most builds | Implemented in Floci |
| `describe-scalable-targets`, including `RoleARN` and `SuspendedState` | Full | Generally implemented; `RoleARN` may be absent | Implemented in Floci |
| Registration raising `desiredCount` to `MinCapacity` | Immediate | Build-dependent; the bound may be stored without being enforced | Floci Limitation |
| `MinCapacity` and `MaxCapacity` enforced against every scaling decision | Every decision | Stored; not enforced when the loop does not run | Floci Limitation |
| `put-scaling-policy`, `TargetTrackingScaling` | Full | Generally implemented | Implemented in Floci |
| Two managed CloudWatch alarms created per target tracking policy | Created, attached and maintained automatically | Build-dependent; often absent | Floci Limitation |
| The target tracking capacity calculation | Real arithmetic on real datapoints | Not performed | Conceptual / Real AWS |
| `ScaleOutCooldown` and `ScaleInCooldown` | Enforced | Stored; not enforced | Floci Limitation |
| `DisableScaleIn` | Enforced | Stored | Floci Limitation |
| `ALBRequestCountPerTarget` and its `ResourceLabel` | Full, reading `AWS/ApplicationELB` metrics | Often unsupported; the label is validated at best | Floci Limitation |
| `AWS/ECS` `CPUUtilization` and `MemoryUtilization` metrics | Published every minute with Container Insights | Rarely published | Floci Limitation |
| `AWS/ApplicationELB` `RequestCountPerTarget` | Published every minute | Not published — Lab 04B said so | Conceptual / Real AWS |
| `put-scaling-policy`, `StepScaling` | Full, with interval validation | Generally implemented | Implemented in Floci |
| Step adjustment selection from the breach magnitude | Real, per evaluation | Not performed | Conceptual / Real AWS |
| `put-scheduled-action` with `cron`, `rate` and `at` | Full, with `--timezone` and IANA zones | Stored; the scheduler may not run. `--timezone` may be rejected | Floci Limitation |
| A scheduled action actually firing | Real, to the minute | Build-dependent, and usually not | Floci Limitation |
| `describe-scaling-activities` and its `Cause` string | Full, and the `Cause` names the alarm and the policy | Often an empty list | Floci Limitation |
| `--include-not-scaled-activities` and `NotScaledReasons` | Full, and it is the best diagnostic in the service | Rarely implemented | Conceptual / Real AWS |
| `cloudwatch put-metric-data` for a custom metric | Full | Generally implemented | Implemented in Floci |
| `cloudwatch put-metric-alarm` with a scaling policy as an alarm action | Full | Generally implemented; the action may be stored without being invoked | Floci Limitation |
| Alarm evaluation on a schedule | Once per period, continuously | Build-dependent | Floci Limitation |
| `cloudwatch set-alarm-state` invoking the alarm's actions | Full, and the state reverts at the next evaluation | Build-dependent; this is the one call that may close the loop for you | Floci Limitation |
| `TreatMissingData` behaviour | Enforced per period | Stored | Floci Limitation |
| `iam create-service-linked-role` | Full, and the role is genuinely assumed | Build-dependent; nothing is assumed | Floci Limitation |
| IAM authorization of any of these calls | Evaluated on every request | Not enforced by default | Floci Limitation |
| Suspension actually preventing a scaling action | Enforced | Stored | Floci Limitation |
| Fargate task start latency, 20 to 60 seconds | Real, and it is why cooldowns exist | Instant, or never | Floci Limitation |
| `healthCheckGracePeriodSeconds` delaying when new capacity counts | Enforced | Stored — Lab 04B said so | Floci Limitation |
| Cost — per task-second, plus CloudWatch per alarm and per custom metric | Real, and an idle alarm is not free | Free | Conceptual / Real AWS |
| Service quotas: scalable targets, policies per target, step adjustments per policy | Enforced | Not enforced | Conceptual / Real AWS |
| Subnet address exhaustion capping a scale-out | Real, and it presents as `Unfulfilled` | Not enforced | Conceptual / Real AWS |
| Predictive scaling | **Not available for ECS in any account.** EC2 Auto Scaling only | Not available | Conceptual / Real AWS |
| `CloudTrail` recording which role changed your capacity | Full, with the service-linked role as the invoker | Not available | Conceptual / Real AWS |

### 12.1 What you actually observed in this lab

```text
OBSERVABLE — you saw this happen
  a service-linked role, at a path no role you wrote has ever had
  a resource ID derived from a service ARN by parameter expansion, and validated
  a scalable target registered, and re-registered twice to change its content
  MinCapacity surviving a call that passed only MaxCapacity
  two target tracking policies on one target, on two different metrics
  a policy ARN with a whole resource ID embedded in the middle of it
  TWO CloudWatch alarms that appeared without you writing them, named after your resource ID
  their asymmetric evaluation periods -- 3 for the high alarm, 15 for the low one
  a ResourceLabel built from fragments of two different ARNs, validated at six segments
  a step scaling table whose bounds are relative to a threshold, not absolute
  an alarm whose AlarmActions you populated yourself with a policy ARN
  a custom metric published into a namespace you invented
  two scheduled actions, with a cron expression that has six fields and a time zone
  suspension turned on and off, with every policy left untouched
  all of it surviving a container restart, with every identifier re-derived from the API
  the whole nine-line chain from a request to a serving task, in Step 15

CONCEPTUAL — you reasoned about it, and may not have seen it
  an alarm changing state because a metric moved            (unless you got it at Step 12)
  a scaling activity, and its Cause naming the alarm         (unless you got it at Step 12)
  the target tracking capacity calculation
  a cooldown suppressing a second scale-out
  DisableScaleIn preventing a scale-in
  the 15-minute reluctance of a target tracking scale-in, observed
  a scheduled action firing at 07:45 and raising the floor
  suspension actually preventing anything
  the 20-to-60-second Fargate start latency that every cooldown here is sized against
  the 60-second grace period delaying when new capacity counts
  the cost of two extra tasks, four alarms and one custom metric
```

If your build put you on support path A, several lines move from the second list to the first. Say in your
report which list each item ended up in **for you**. Being precise about that is worth marks; claiming to
have observed something you reasoned about is worth negative marks.

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **Capacity appears instantly, or never.** Every cooldown in this lab is sized against a real Fargate
  task's 20-to-60-second start plus Lab 04B's 60-second grace period. On an emulator where a task starts
  in no time, a 60-second scale-out cooldown looks generous and is in fact barely adequate. A system
  tuned on an emulator where capacity is free and instant is tuned wrongly in both directions.
- **Nothing is ever unfulfilled.** On real AWS a scale-out to 10 tasks can fail because the subnet has
  no addresses left — every `awsvpc` task consumes one — or because a service quota bites. It presents as
  a scaling activity with `StatusCode: Unfulfilled` and a service that is quietly smaller than the policy
  asked for. Exercise 4 asks you to work out whether Lab 02's subnets could actually hold your ceiling.
- **Alarms never flap.** A real metric hovering at the target crosses it repeatedly, which is why target
  tracking has a dead band and why an aggressive step policy with a one-minute evaluation can scale out
  and in and out again within ten minutes. That oscillation is the most common complaint about auto
  scaling and you cannot experience it here.
- **No cost.** Two extra tasks are the obvious item and the smaller one. CloudWatch charges per alarm per
  month and per custom metric per month, and this lab created five alarms and one metric. A team that
  adds target tracking to forty services has added eighty alarms, and somebody eventually asks why the
  CloudWatch line grew.
- **Suspension has no effect, so its hazard is invisible.** The most dangerous thing in this lab — a
  target left with scale-out suspended — cannot hurt you here. That is exactly why Section 9's script
  asserts it rather than trusting you to notice.
- **`set-alarm-state` is a testing convenience here and a real privilege there.** On a production account
  `cloudwatch:SetAlarmState` lets the holder trigger anything any alarm does, including paging a human at
  three in the morning. Treat the ease of it in this lab as a fact about the lab.

### 12.3 Three different things called auto scaling, and the one Lab 3 promised

This is the confusion the course has been walking towards since Lab 3 Step 20, and it is worth getting
right because the three services have different APIs, different vocabularies and different jobs.

| | **ECS service auto scaling** | **ECS cluster auto scaling** | **EC2 Auto Scaling** |
| --- | --- | --- | --- |
| What it scales | The number of **tasks** in a service | The number of **container instances** behind a capacity provider | The number of **EC2 instances** in an Auto Scaling group |
| The service | Application Auto Scaling (`aws application-autoscaling`) | ECS capacity providers, which use an Auto Scaling group underneath | EC2 Auto Scaling (`aws autoscaling`) |
| The object | A scalable target with `ecs:service:DesiredCount` | A capacity provider with a managed scaling configuration | An Auto Scaling group with a launch template |
| Needs | Nothing but an ECS service | An EC2-backed cluster. **Meaningless on Fargate** | An AMI and a launch template |
| Predictive scaling | No | No | **Yes** |
| Health checks and instance replacement | Not its job — ECS does that | Not its job | **Yes**, including replacing an unhealthy instance |
| This course | **This laboratory** | Not covered. Fargate removes the need | Not covered by Practical 2 or 3 |

**Which one did Lab 3 promise?** Lab 3 Step 20 built `usms-web-golden`, an AMI, and said it would be used
in a launch template. A launch template is an **EC2 Auto Scaling** object. So that promise belongs to the
third column, and it is not this lab — which is exactly what Lab 04A said in its §1 and is repeated here
because it is the single most common misunderstanding about where this material sits.

The three are not alternatives; they compose. A real EC2-backed ECS platform runs all three at once: EC2
Auto Scaling keeps the instances alive, cluster auto scaling adds instances when tasks cannot be placed,
and service auto scaling adds tasks when the application is busy. **Fargate deletes the middle two
columns**, which is the largest single simplification Fargate buys you and a good answer to "why would I
pay the Fargate premium".

One vocabulary trap to keep straight, because it will cost you time exactly once:

```text
aws autoscaling                 EC2 Auto Scaling — groups, launch templates, instance refresh
aws application-autoscaling     THIS SERVICE — scalable targets in nine namespaces
arn:aws:autoscaling:...         the ARN namespace used by BOTH of them
```

The third line is the one that makes it genuinely confusing rather than merely inconvenient: a scaling
policy created by `aws application-autoscaling` has an ARN in the `autoscaling` namespace. Step 7's ARN
is the evidence. Look at it again and note that nothing in it says `application`.

### 12.4 One thing this lab is *not*

Nothing in this lab is **load testing**, and every number in it is therefore a guess.

A target of 50 per cent CPU, a target of 1000 requests per target per minute, a queue threshold of 100,
a ceiling of 10 — every one of those is a plausible number chosen to teach a mechanism, and not one of
them was derived from measuring the enrolment application. On a real system the order of work is the
reverse of this laboratory's: you load-test first, find out what one task can actually serve and where it
falls over, and *then* choose target values that keep you comfortably below that point.

The honest version of the sentence to put in your report is: *the mechanism is correct and the numbers
are provisional.* Exercise 4 asks you to say how you would get real ones, and it is the part of this lab
that most resembles the actual job.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-04c-ecs-autoscaling/exercises.md`. Take screenshots into
`screenshots/` where an exercise asks for evidence.

### Exercise 1 — Basic: a memory policy, and a scale-out-only policy

**Requirements**

Memory pressure and CPU pressure are different failure modes, and a container that is running out of
memory does not necessarily look busy. Add a third target tracking policy, and make it deliberately
one-directional.

1. Create `usms-enrolment-memory-target-tracking` on the same scalable target, using the predefined
   metric `ECSServiceAverageMemoryUtilization`, with a target value of 70, a scale-out cooldown of 60 and
   a scale-in cooldown of 600.
2. Set `DisableScaleIn` to `true` on it.
3. Read back the managed alarm count for the whole target and confirm it went from four to five rather
   than to six.
4. Write the configuration to `templates/lab-04c-target-tracking-memory.json`, as a document, following
   this lab's heredoc quoting rule for a file with no variables in it.

**Constraints**

- Every identifier captured with `$(...)` and `--query`. Nothing copied by hand.
- Do **not** record the policy in `configs/lab-04c.env`. Exercise 4 removes it.
- Do **not** change the scalable target's bounds.
- Section 9's script must still report `FAIL=0` afterwards. Work out before you start whether it will,
  and say why.

**Expected outcome**

Three target tracking policies and one step policy on one scalable target. `describe-scaling-policies`
shows the new policy with `DisableScaleIn` true, and the managed alarm count for the target is **five**.

**Then answer, in one sentence each:**

- Why five and not six? Name the alarm that was not created and say what its absence means operationally.
- A memory target of 70 against a CPU target of 50: which of the two will scale this service out first,
  and what would you need to know about the application to answer that properly rather than by guessing?
- `DisableScaleIn` true means this policy can only ever grow the service. Given the rule from Step 9 about
  how several target tracking policies interact, does adding it change the *scale-in* behaviour of the
  other two policies at all? Justify your answer.

**Hints**

Step 7 contains every command you need; the only questions are which values change and which field turns
scale-in off. For the alarm count, re-read the target tracking interlude on what the low alarm is *for* —
and then think about what a policy that never scales in would do with one.

---

### Exercise 2 — Intermediate: the scale-in half of step scaling, and a fight to avoid

**Requirements**

Step 10 built a step policy that only grows. Real step scaling comes in pairs, and building the other
half is where the sign conventions bite.

1. Create `usms-enrolment-queue-step-in`: a `StepScaling` policy on the same target, `ChangeInCapacity`,
   `Average`, cooldown 300, with two adjustments — a mild one and a stronger one — that **remove**
   capacity as the metric falls further below a threshold.
2. Create `usms-enrolment-queue-low`, a CloudWatch alarm on the same custom metric, firing when the
   average is **below** 20 for 3 evaluation periods of 60 seconds, whose only action is that policy.
3. Write the step configuration to `templates/lab-04c-step-scaling-in.json`, and state in a comment in
   `exercises.md` what the sign of every bound and every adjustment is and why.
4. Publish enough datapoints to take the metric to 5, force the low alarm into `ALARM` with
   `set-alarm-state`, and record what happened — including "nothing", if that is the answer on your build.
5. Then delete both objects, in the correct order, each preceded by the four-line danger admonition this
   lab uses.

**Constraints**

- The bounds on a scale-in step table are **non-positive** and the adjustments are **negative**. Getting
  either sign wrong produces a policy that is accepted and does the opposite of what you meant; say in
  one sentence what `MetricIntervalUpperBound: 0` with `ScalingAdjustment: -1` actually means.
- The cooldown must be longer than the scale-out policy's, and you must say why in one sentence.
- The floor of 2 must make one of your two adjustments unreachable in practice. Identify which and say
  so — a step you can prove will never fire is a finding, not a bug.
- Section 9's script must report `FAIL=0` at the end, which means point 5 is not optional.

**Expected outcome**

A matched pair of step policies observed on one target, then removed cleanly, with the sign conventions
written out and the unreachable step identified.

**Then answer, in a short paragraph:**

You now have, or have had, a CPU **target tracking** policy and a queue **step scaling** policy on one
service. Suppose somebody added a step scaling policy on **CPU** as well, driven by their own alarm at 60
per cent. Explain what would go wrong, using the target tracking interlude's description of how it
computes capacity. Then say which of the two policies you would keep and why — and note that the answer
is not "whichever fires first".

**Hints**

`aws application-autoscaling put-scaling-policy help` shows the exact shape of `StepAdjustments`. For the
signs, write the interval table out with the threshold at the centre and the breach as a signed number:
a metric of 5 against a threshold of 20 is a breach of **-15**, and that tells you immediately which
bounds it can fall between. For the unreachable step, the arithmetic is `2 + (your larger negative
adjustment)` compared with `MinCapacity`.

---

### Exercise 3 — Problem solving: a scaling report tool

**Requirements**

Write `scripts/utilities/usms-scaling-report.sh`. Given no arguments, it discovers every scalable target
in the `ecs` namespace whose resource ID names a cluster beginning `usms-` and prints its complete
decision table with a computed verdict:

```text
service/usms-ecs-cluster/usms-enrolment-svc   ecs:service:DesiredCount
  bounds       min=2  max=10   desired=2   running=2   ELASTIC
  suspended    none
  target-track usms-enrolment-cpu-target-tracking        CPU/50.0        out=60  in=300
                 alarms  AlarmHigh=OK  AlarmLow=INSUFFICIENT_DATA
  target-track usms-enrolment-requests-target-tracking   ALBReq/1000.0   out=60  in=300
                 alarms  AlarmHigh=OK  AlarmLow=OK
  step         usms-enrolment-queue-step-out             +1 / +3         cooldown=60
                 alarm   usms-enrolment-queue-high = OK  (USMS/Enrolment EnrolmentQueueDepth >= 100)
  scheduled    usms-enrolment-morning-scale-out  cron(45 7 ? * MON-FRI *)  Asia/Thimphu  min=4
  scheduled    usms-enrolment-evening-scale-in   cron(0 20 ? * MON-FRI *)  Asia/Thimphu  min=2
  last activity  none recorded
```

The verdict on the `bounds` line must be **computed** from the target's own fields, never from a name or
a tag:

| Verdict | When |
| --- | --- |
| `PINNED` | `MinCapacity` equals `MaxCapacity` — the service cannot scale at all |
| `FROZEN` | Any suspension switch is `true` |
| `AT-CEILING` | `desiredCount` equals `MaxCapacity` |
| `AT-FLOOR` | `desiredCount` equals `MinCapacity` and more than one policy exists |
| `ELASTIC` | None of the above |

The five rules are ordered and more than one can be true at once. Evaluate them top to bottom and say in
a comment why that order is the right one — in particular, why `FROZEN` outranks `AT-CEILING`.

**Constraints**

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as Section 9's script
  does.
- Takes no arguments and hard-codes no resource ID, no policy name, no alarm name and no cluster name
  beyond the `usms-` prefix. Everything is discovered.
- Must handle a target with no policies, a target with no scheduled actions, a target tracking policy
  whose `Alarms` list is empty, and a build where `describe-scaling-activities` is unimplemented — without
  crashing and without printing a blank line where a row should be.
- A step policy's adjustments must be summarised as a signed list (`+1 / +3`), derived from the
  configuration rather than restated from this document.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- Also write the machine-readable form to `outputs/lab-04c-scaling-report.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-04c-ecs-autoscaling/`. Correct
output before and after Exercise 1 adds a third policy, correct output while the target is suspended, and
correct output if you temporarily set `MinCapacity` and `MaxCapacity` both to 3.

**Hints**

Four levels of discovery — targets, then policies per target, then alarms per policy, then scheduled
actions per target — plus one more call for the ECS service's current counts. The interesting design
question is where to stop shelling out and start processing JSON in `python3`, and the answer is probably
"after the first `describe-scalable-targets`".

The alarm states are the fiddly part: a target tracking policy's `Alarms` list gives you names, and you
need one `describe-alarms` call to turn names into states. Batch it — `describe-alarms --alarm-names`
takes several — rather than calling it once per alarm.

---

### Exercise 4 — Challenge: the enrolment-week capacity plan

**Requirements**

The USMS project lead writes:

> Enrolment opens on the 14th and runs for three weeks. Last year the portal fell over in the first
> twenty minutes and we spent the afternoon on the phone to the registrar. Analytics says we had about
> forty times normal traffic in the first hour of each of the three days when a new cohort became
> eligible, and roughly double normal traffic for the rest of the three weeks.
>
> I am told we now have auto scaling, so presumably this is solved. Tell me whether it is, what it will
> cost, and what you need from me.
>
> Also, somebody has left some practice policies on the service from an exercise. Tidy them up.

Produce a written analysis in `labs/lab-04c-ecs-autoscaling/exercises.md` covering:

- **Whether it is solved, in exactly three sentences.** One for what reactive scaling will do well, one
  for what it will do badly, and one for the first twenty minutes specifically. An answer longer than
  three sentences has not been thought about enough.
- **Why forty times traffic is not a scaling problem.** Work out, from this lab's own numbers, how long a
  reactive policy takes to go from 2 tasks to 10 — including every alarm evaluation, every cooldown, and
  every task start plus grace period. Show the arithmetic. Then say what the ceiling of 10 implies about
  whether 40 times traffic is servable at all, given the target value in Step 9.
- **The ceiling, checked against Lab 02.** Every `awsvpc` task consumes one address in its subnet. Work
  out how many usable addresses `10.0.3.0/24` and `10.0.4.0/24` actually offer, remembering what AWS
  reserves in every subnet, and what else is already in them. State the largest ceiling those subnets
  could support and cite the documentation for the reservation.
- **A capacity plan**, concretely: the scheduled actions you would add for the three cohort days and for
  the three-week window, with their exact `cron` expressions and time zone; the bounds each would set;
  the target values you would change and to what; and what you would do about the ceiling. Say which of
  your changes are reversible in one command and which are not.
- **A monthly cost estimate**, **with a citation**: the additional Fargate cost of your plan against the
  baseline, using current per-vCPU-hour and per-GB-hour prices for the task size in
  `configs/lab-04a.env`; plus the CloudWatch cost of the alarms and custom metrics your plan implies,
  which most people forget. State every assumption explicitly.
- **What you need from the project lead.** Name three things, and be specific. One of them must be a
  measurement nobody has taken; §12.4 says which.
- **The tidy-up**, with exact commands in the correct dependency order, each preceded by the four-line
  danger admonition used throughout this lab: `usms-enrolment-memory-target-tracking` from Exercise 1,
  and anything left over from Exercise 2.

Then execute only the deletions, and confirm `./scripts/utilities/verify-lab-04c.sh` reports `FAIL=0`
afterwards.

**Constraints**

- Do not delete anything in Section 16's KEEP column.
- Every number must have a source or a derivation. "It will scale up" earns nothing; "from a floor of 2,
  the first scale-out cannot complete before T+N seconds, where N is the following four terms" earns full
  marks.
- The address arithmetic must state the number AWS reserves per subnet and cite where that is documented.
- Your answer must distinguish clearly between **capacity** and **throughput**. A ceiling of 10 tasks at
  1000 requests per target per minute is a specific number of requests per second, and you should say what
  it is.

**Expected outcome**

An analysis a project lead could act on and a finance team could check, plus a repository in which the
practice policies are gone and the verification still passes.

**Hints**

The first bullet's third sentence is the whole exercise, and §4.3 is where it comes from. For the
arithmetic, Step 8's "Your turn" already built you one of the four terms and Lab 04A Exercise 5 measured
another. For the address reservation, search the AWS VPC documentation for the subnet sizing rules — the
number is small, constant, and not what people guess. For the measurement you need from the project lead,
§12.4 names it in its second paragraph.

---

### Exercise 5 — Integration: the hand-off to Lab 05

**Requirements**

Lab 05 creates `usms-student-data`, the S3 bucket that Lab 01's `USMSStudentDataReadWrite` policy has
named since the first day of this course and that Lab 04A attached to `usms-ecs-task-role`. Its first
`put-object` needs a real file, and a scaling history is a real file that a real operations team would
genuinely archive.

1. Write `scripts/utilities/usms-scaling-history.sh`, which exports this service's complete scaling
   configuration and history as one JSON document to `outputs/lab-04c-scaling-history.json`: the scalable
   target with its bounds and suspension state, every scaling policy with its full configuration, every
   scheduled action, every alarm involved with its current state, and every scaling activity
   `describe-scaling-activities` will return, including the not-scaled ones. Every identifier must be
   discovered, not typed.
2. Add a top-level `"generated"` field with a UTC timestamp produced by `python3`, and a `"resourceId"`
   field derived from the ECS service's ARN. Validate the result with `python3 -m json.tool` and record
   its size in bytes.
3. **Measure the one number Lab 05 cannot measure and this lab can.** Record a UTC timestamp, raise
   `MinCapacity` to 4 by re-registering the target, poll until `runningCount` equals `desiredCount`,
   record the timestamp again, and write the elapsed seconds to
   `outputs/lab-04c-scale-latency.txt` with both timestamps and the two capacities. Then put the floor
   back to 2 and confirm the bounds. If your build never starts tasks, say so and record the figure AWS
   documents for Fargate task start-up instead, cited.
4. Append two variables to `configs/lab-04c.env`, derived rather than typed:
   `USMS_SCALING_HISTORY_FILE` holding the path from point 1, and `USMS_SCALE_LATENCY_SECONDS` holding
   the measurement from point 3. Re-run the empty-value check and state the new export count.
5. Write `outputs/lab-04c-lab05-readiness.txt` containing, each on its own labelled line: the scaling
   history file's path and byte size; the measured or cited scale-out latency; the task role ARN from
   `configs/lab-04a.env`; the exact bucket ARN that role's attached policy names, **read from the policy
   document rather than typed**; and one sentence naming which of Lab 01's permissions that policy grants
   on that bucket.
6. Run `aws s3api head-bucket --bucket usms-student-data` and capture **both** its output and its exit
   code into the same file. It will fail. Lab 04A Exercise 5 captured the same failure; capture it again,
   and add one sentence saying what will be different about the same command after Lab 05's Step 1 — and
   what will be different about `usms-ecs-task-role` at the same instant.

**Constraints**

- `usms-scaling-history.sh` must work from any directory and must contain no hard-coded resource ID,
  policy name or alarm name.
- Point 5's bucket ARN must be **read from the IAM policy document**, with `get-policy-version`, not
  typed. A value you typed proves nothing about what the policy actually says.
- The `head-bucket` failure must be captured **with** its exit code, not suppressed. `|| true` followed by
  recording `$?` is the pattern; a bare failure under `set -e` aborts the script and loses the evidence.
- The latency measurement must use `python3` for timestamps, not `date -d` or `date -v`.
- Point 3 must restore `MinCapacity` to 2. Section 9's script asserts it, and leaving it at 4 is the
  single most likely way to fail this lab's verification.
- No script you write here may contain, read or reference an access key. If one does, the exercise is
  failed regardless of whether it works.

**Expected outcome**

A committed export script the CloudWatch and CloudFormation labs can both call unchanged; a real JSON
artefact for Lab 05's first `put-object`; a measured or honestly cited figure for how long capacity takes
to appear when a bound moves; and a readiness file from which a Lab 05 reader could predict exactly what
`create-bucket` is about to make true.

**This is what Lab 05 will use.** Its first object needs content, and its most valuable sentence is the
one about two IAM policies becoming real at the same instant. Point 6 is the setup for that sentence.

**Hints**

Step 14 already derives every identifier from the API; the export script is that logic plus
`--output json` and a `python3` step to assemble one document. For point 3, Step 12 part 1's timestamp
pattern is the skeleton and Step 6 has the re-registration. For point 5, Lab 04A Step 8's **Verify**
block already reads the policy document with `get-policy` and `get-policy-version` — the bucket ARN is in
the statement's `Resource`, and note that there are two of them, one for the bucket and one for its
objects. Say which you recorded and why.

---

## 14. Lab Assessment Checklist

Tick these off before you submit. Every one is checkable from your own repository.

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` appears in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-04c-notes.md`

**Resources**

- [ ] Exactly **one** scalable target exists in the `ecs` namespace
- [ ] Its resource ID is `service/usms-ecs-cluster/usms-enrolment-svc`, with three segments
- [ ] Its scalable dimension is `ecs:service:DesiredCount`
- [ ] `MinCapacity` is 2 and `MaxCapacity` is 10
- [ ] All three suspension switches are `false`
- [ ] `usms-enrolment-cpu-target-tracking` exists: CPU, target 50, out 60, in 300, `DisableScaleIn` false
- [ ] `usms-enrolment-requests-target-tracking` exists with a six-segment `ResourceLabel`, **or** its
      absence is recorded as a Step 9 limitation
- [ ] `usms-enrolment-queue-step-out` exists: `StepScaling`, `ChangeInCapacity`, two adjustments, the top
      one open-ended
- [ ] `usms-enrolment-queue-high` exists, watches `USMS/Enrolment EnrolmentQueueDepth`, and names the step
      policy in `AlarmActions`
- [ ] Two scheduled actions exist, with a floor of 4 in the morning and 2 in the evening
- [ ] `desiredCount` is back at 2 with exactly one deployment
- [ ] The task definition is still `usms-enrolment:2` and the service still has exactly one
      `loadBalancers` entry — this lab changed neither

**Evidence**

- [ ] Step 5's `describe-scalable-targets` output showing `RoleARN` filled in by AWS
- [ ] Step 8's two managed alarms, with their asymmetric evaluation periods
- [ ] Step 8's "Your turn" arithmetic, with all four terms written out
- [ ] Step 9's validated `ResourceLabel`, six segments, `app` first and `targetgroup` fourth
- [ ] Step 12's scaling activity with its `Cause` string, **or** `outputs/lab-04c-scaling-proof.txt` and
      the reason the loop did not run
- [ ] Step 13's `SuspendedState` output, both while suspended and after resuming
- [ ] Step 14's `PERSISTENCE PROVEN` line
- [ ] Step 15's seven blocks, and the nine-line chain written out in your notes
- [ ] `outputs/lab-04c-pre-restart.txt` and `outputs/lab-04c-post-restart.txt` present
- [ ] Screenshots in `screenshots/` for Checkpoints 3, 5 and 7

**Hygiene and written work**

- [ ] `configs/lab-04c.env` exists, is committed, has 22 exports (24 after Exercise 5) and no empty values
      or `None`
- [ ] `scripts/utilities/verify-lab-04c.sh` exists and reports `PASS=42  FAIL=0`, or its documented benign
      failures, each explained
- [ ] `scripts/cleanup/lab-04c-cleanup.sh` exists, passes `bash -n`, and has **not** been run
- [ ] The two hint strings in `lab-04a-cleanup.sh` and `lab-04b-cleanup.sh` are repaired, and both scripts
      still pass `bash -n`
- [ ] `verify-lab-04b.sh` produces the same output as the run captured in Step 2 — an empty `diff`
- [ ] `git status --short` shows nothing under `outputs/` and no `.bak-*` file
- [ ] `git check-ignore -v` demonstrated on one `outputs/` file from this lab
- [ ] `notes/lab-04c-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-04c-ecs-autoscaling/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding — answer these out loud before you submit**

- [ ] I can name the one thing Application Auto Scaling changes on an ECS service, and three things it
      does not do
- [ ] I can build the scalable target's three-part address from the service's ARN, without looking it up
- [ ] I can say which two CloudWatch alarms I did not create, why they exist, and what happens if I
      delete one
- [ ] I can explain why `ALBRequestCountPerTarget` is a better signal than CPU, and name the case where
      it is not
- [ ] I can say what target tracking cannot express, and give the requirement that needs step scaling
- [ ] I can explain why reactive scaling cannot absorb the first two minutes of a spike, and what does
- [ ] I can name the three suspension switches and say which one is dangerous to leave on
- [ ] I can distinguish `aws autoscaling` from `aws application-autoscaling` and say which one Lab 3's
      golden AMI belongs to

---

## 15. Review Questions

Answer in prose, in your own words, in `notes/lab-04c-notes.md`. No command output — these ask whether you
understood, not whether you typed.

1. Step 15 traced nine lines from a student clicking Register to a task serving the request, and said this
   laboratory is responsible for three of them. Write out all nine, name which three are this lab's, and
   then explain in a full paragraph why the other six needed no modification at all. Finish with the one
   sentence you would use to answer "what does auto scaling change about my application?"

2. A colleague passes the ECS service's full ARN to `--resource-id` and gets a validation error. Explain
   what the resource ID actually is, why Application Auto Scaling uses a constructed string rather than an
   ARN, and how the shape of that string differs between the `ecs`, `dynamodb` and `lambda` namespaces.
   Then name the other three constructed identifiers this architecture uses and say which ARN each is
   built from.

3. Registering a scalable target with a minimum of 2 against a service running one task raises the count
   to 2 immediately. Explain which object made that change and how it differs from a scaling policy making
   the same change. Then describe a plausible three-in-the-morning incident in which somebody uses that
   behaviour deliberately, and say what evidence would be left behind for the person who takes over at
   eight.

4. Target tracking created two CloudWatch alarms without telling you; you created a third yourself for the
   step policy. Explain the practical differences between the two situations — who owns each alarm, what
   happens when the policy changes, what happens if the alarm is deleted, and what one of them can do that
   the other cannot. Then argue for `breaching` rather than `notBreaching` as the `TreatMissingData` value
   for the queue-depth alarm, and say what would go wrong if you were right.

5. §4.3 claims that a reactive scaling policy can never absorb the first minutes of a spike, and calls
   that arithmetic rather than a flaw. Reconstruct the arithmetic, naming every delay and where each one
   is configured. Then explain the three consequences the section draws from it, and say which of this
   lab's five configuration decisions each consequence justifies.

6. You have a CPU target tracking policy at 50 and a request-count target tracking policy at 1000 on one
   service. Explain what happens when they disagree, in both directions, and why the rule is asymmetric.
   Then explain why two target tracking policies on the **same** metric is a fault rather than a
   redundancy, and connect that to why a step scaling policy and a target tracking policy on one metric is
   the same mistake wearing different clothes.

7. `ALBRequestCountPerTarget` is a better scaling signal than CPU for the enrolment API, and this lab says
   so three times. State the three reasons in your own words. Then name the one class of workload for
   which CPU is the better of the two and explain why. Finally, describe what would have to be true about
   the enrolment application for `ALBRequestCountPerTarget` to scale it **badly** — and say which
   CloudWatch metric would have shown you that before you chose it.

---

## 16. What We Built

### 16.1 Reflection

Five laboratories built a system. This one added a control loop over a single integer in it, and the most
useful thing to take away is how thoroughly that integer is the whole interface.

The idea to keep is **separation of the decision from the mechanism**. Application Auto Scaling decides;
ECS acts; the ECS service maintains the target group; the load balancer routes. Four systems, four jobs,
and the only thing passing between the first two is a number between 2 and 10. That is why Step 15's
seventh block matters: the task definition, the load balancer count and the deployment count were exactly
what Lab 04B left, because a well-separated system does not require you to modify the mechanism in order
to change the decision. If you ever find yourself editing a task definition in order to change how a
service scales, something has gone wrong with the design and not with the tool.

The second idea is that **the interesting part of a scaling configuration is the delays, not the
thresholds.** Everybody argues about whether the CPU target should be 50 or 70. Almost nobody notices that
the managed high alarm needs three minutes of breach, the low alarm needs fifteen, the scale-out cooldown
adds sixty seconds, a Fargate task takes another twenty to sixty to exist, and Lab 04B's grace period
withholds it from service for sixty more. Step 8's "Your turn" made you add those up, and the number is
uncomfortable. A team that knows that number designs a minimum capacity; a team that does not argues about
target values and is surprised every enrolment week.

The third is a distinction worth carrying out of this course. **Reactive scaling is for load you did not
predict; scheduled scaling is for load you did.** Enrolment week is in the calendar. Exam results night is
in the calendar. A reactive policy meeting a known event two minutes late is a system apologising for a
failure of planning, and the fix is a `cron` expression rather than a lower threshold. That is why Step 11
is in this lab and not in an appendix, and it is the part of this material a real operations team would
recognise most quickly.

And the discipline the course keeps returning to, one more time. Every command in Steps 4 to 11 reported
success and almost none of it was evidence. Step 5 proved the resource ID's shape by counting its segments
before using it. Step 6 proved the change model by omitting a parameter and reading back the one it did
not touch. Step 8 proved the alarms existed by finding objects nobody had told you about. Step 12 proved
the loop by pushing a metric and reading a `Cause` string — or, where the loop does not run, by walking
six blocks of configuration and saying honestly which proof it got. Step 14 proved persistence by
re-deriving every identifier from the API after a restart. **A command that appears to succeed is still
not evidence that it did what you meant** — five laboratories in, that should now be a reflex rather than
a rule.

One connection worth naming out loud, because it closes something Lab 04B opened. Lab 04B built a target
group and, in its §12.3, said its own successor scaled on CPU because there had been no load balancer when
that document was written. Step 9 of this lab filled in the third row of that table. The `ResourceLabel`
you built there is made of fragments of two ARNs from a laboratory you finished a week ago, and it did not
require changing a single thing either of them created. That is what a cumulative course is supposed to
feel like.

### 16.2 KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ════════════════════════╗    ╔═════════════ CLEAN UP ══════════════╗
║ the scalable target       min 2 max 10, suspension  ║    ║ usms-enrolment-memory-target-       ║
║                           switches all false        ║    ║   tracking                          ║
║ usms-enrolment-cpu-target-tracking                  ║    ║   — Exercise 1 practice;            ║
║ usms-enrolment-requests-target-tracking             ║    ║   removed in Exercise 4             ║
║ usms-enrolment-queue-step-out                       ║    ║                                     ║
║ usms-enrolment-queue-high  the CloudWatch lab       ║    ║ usms-enrolment-queue-step-in and    ║
║                            replaces set-alarm-state ║    ║ usms-enrolment-queue-low            ║
║ USMS/Enrolment metric      the CloudWatch lab       ║    ║   — Exercise 2 practice; its own    ║
║                            graphs it                ║    ║   point 5 removes them              ║
║ both scheduled actions     the CloudFormation lab   ║    ║                                     ║
║                            re-declares them         ║    ║ usms-enrolment-results-night        ║
║ the four managed alarms    AWS owns them; leave     ║    ║   — Step 11's Your turn; deleted    ║
║                            them alone entirely      ║    ║   there, WITH the floor put back    ║
║ AWSServiceRoleForApplicationAutoScaling_ECSService  ║    ║                                     ║
║ configs/lab-04c.env        two later labs source it ║    ║ outputs/lab-04c-pre/post-*.txt      ║
║ templates/lab-04c-*.json   incl. the suspended      ║    ║   — evidence; keep until            ║
║                            state, as a runbook page ║    ║   submitted, then remove            ║
║ scripts/utilities/verify-lab-04c.sh                 ║    ║                                     ║
║ outputs/lab-04c-scaling-history.json  (Exercise 5)  ║    ║ scripts/cleanup/*.bak-*             ║
║   Lab 05's first put-object needs it                ║    ║   — Step 17's backups; remove       ║
║ everything from Labs 01, 02, 03, 04A and 04B        ║    ║   once you are satisfied            ║
╚═════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted:

```bash
rm -f outputs/lab-04c-pre-restart.txt  outputs/lab-04c-post-restart.txt
rm -f outputs/lab-04c-pre-scale.txt    outputs/lab-04c-post-scale.txt
rm -f outputs/lab-04c-pre-verify-04b.txt outputs/lab-04c-post-verify-04b.txt
rm -f scripts/cleanup/*.bak-*
git status --short
./scripts/utilities/verify-lab-04c.sh | tail -2
```

Keep `outputs/lab-04c-scaling-proof.txt` and `outputs/lab-04c-scaling-history.json` until Lab 05 has
consumed the second one.

Note that `templates/lab-04c-suspended-state.json` is in the KEEP column even though the suspension it
describes has been cleared. Keep the document: it is how you would suspend scale-in again in an incident,
and a runbook page that exists in the repository is worth more than one somebody has to remember to write
at three in the morning.

Do **not** run `scripts/cleanup/lab-04c-cleanup.sh`, `lab-04b-cleanup.sh`, `lab-04a-cleanup.sh`,
`lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are for the end of the course, in the order given in
Section 9.3.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and Lab 04A
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 06
  USMSStudentDataReadWrite ............. on TWO roles, naming a bucket that STILL does not exist
  AWSServiceRoleForApplicationAutoScaling_ECSService   <- NEW: AWS wrote this one

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
                 ^ the load balancer's two nodes
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                                                            -> usms-s3-endpoint
                 ^ where a task created by a scaling policy APPEARS, and where its
                   addresses will eventually run out — Exercise 4 works out when
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg, usms-private-nacl

Lab 03  COMPUTE — instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> EC2 Auto Scaling, which is §12.3's THIRD column and not this lab

Lab 04A COMPUTE — containers you operate
  usms-ecs-cluster                      Container Insights enabled -> the CPU metric exists
    usms-enrolment-svc                  desired 2, both private subnets, no public IP
      usms-enrolment:2                  awsvpc, FARGATE, 256/1024, container health check
        executionRoleArn                usms-ecs-exec-role
        taskRoleArn                     usms-ecs-task-role -> USMSStudentDataReadWrite
  /usms/ecs/enrolment                   retention 7 days

Lab 04B TRAFFIC — the front door
  usms-alb-sg / usms-enrolment-alb / listener HTTP:80 / rule 10 /alb-health
  usms-enrolment-tg                     target-type ip, GET / every 30s, matcher 200
    targets                             registered and deregistered BY the service
  usms-enrolment-svc                    loadBalancers[0], grace period 60
  usms-enrolment-sg                     in: tcp/80 from usms-alb-sg ONLY

Lab 04C SCALING — the control loop                          <-- you are here
  scalable target   service/usms-ecs-cluster/usms-enrolment-svc
                    ecs:service:DesiredCount    min 2   max 10
                    suspension: DynamicScalingIn / Out / Scheduled, all false
    usms-enrolment-cpu-target-tracking        AWS/ECS CPUUtilization -> 50.0
      + 2 managed alarms, high 3x60s, low 15x60s
    usms-enrolment-requests-target-tracking   ALBRequestCountPerTarget -> 1000.0
      ResourceLabel app/<alb-name>/<alb-id>/targetgroup/<tg-name>/<tg-id>
      + 2 managed alarms
    usms-enrolment-queue-step-out             StepScaling, +1 then +3, cooldown 60
      driven by usms-enrolment-queue-high on USMS/Enrolment EnrolmentQueueDepth >= 100
    usms-enrolment-morning-scale-out  cron(45 7 ? * MON-FRI *)  Asia/Thimphu  min 4
    usms-enrolment-evening-scale-in   cron(0 20 ? * MON-FRI *)  Asia/Thimphu  min 2
  and NOTHING ELSE CHANGED: same revision, same service, same target group, same rules

Lab 05  STORAGE (next)
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for BOTH
                        roles at once, and whose first object is this lab's Exercise 5

Lab 06  Lambda, then DynamoDB · RDS · SNS/SQS · CloudWatch · CloudFormation
  the CloudWatch lab reads /usms/ecs/enrolment, USMS/Enrolment and this lab's alarms
  the CloudFormation lab re-declares all of Practical 2 and Practical 3 as one template
```

---

## 17. Preparation for the Next Lab

Lab 05 — S3 — creates `usms-student-data`, and it is the moment two IAM policies written in the first
laboratory of this course stop being hypothetical. It needs nothing from the scaling configuration you
just built, and it needs two things from your repository.

| From this lab | Lab 05 uses it for |
| --- | --- |
| `outputs/lab-04c-scaling-history.json` (Exercise 5) | Its first `put-object` needs a real file with real content. This is one |
| `outputs/lab-04c-lab05-readiness.txt` (Exercise 5) | The exact bucket ARN, read from Lab 01's policy document rather than typed, and the task role that carries it |

| From earlier labs | Lab 05 uses it for |
| --- | --- |
| Lab 01 `USMSStudentDataReadWrite` | The policy whose `Resource` names the bucket. Lab 05 creates the bucket the policy already describes, in that order, deliberately |
| Lab 01 `usms-ec2-app-role` | One of the two roles that starts working the instant the bucket exists |
| Lab 04A `usms-ecs-task-role` | The other one. **This is the sentence Lab 05 is built around** |
| Lab 02 `usms-s3-endpoint` | The gateway endpoint that has been on the private route table since Lab 2 and has had nothing to reach |
| Lab 04A `USMSECSTaskExecution` | Its `logs` statement is scoped to one log group; Lab 05's equivalent scoping decision is about a bucket, and the comparison is worth making |

**The connection to state out loud before the next session.** Lab 01 wrote a policy for a bucket that did
not exist. Lab 03 attached it to an EC2 instance through an instance profile. Lab 04A attached the same
policy, unchanged, to a Fargate task through a task role. Lab 02 built a VPC endpoint whose only purpose
is to reach S3 privately. **Four laboratories have prepared for one `create-bucket` call**, and when Lab
05 runs it, three separate chains resolve at the same instant and not one of them has to be modified.

That is worth more than any single command in this course. Lab 04A Step 8 asked you to write it down; Lab
05 is where you find out it was true.

**Before the next session, confirm all six of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-04b.sh | tail -2
./scripts/utilities/verify-lab-04c.sh | tail -2
grep -c '^export' configs/lab-04c.env
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[].[ResourceId,MinCapacity,MaxCapacity]' --output text
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[0].SuspendedState.*' --output text | grep -ci true
aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].[desiredCount,length(deployments),taskDefinition]' --output text
```

You want: `FAIL=0` twice; a count of **22** (or 24 after Exercise 5); **one** scalable target line reading
`service/usms-ecs-cluster/usms-enrolment-svc	2	10`; a `0` from the suspension count; and a desired count
of **2** with **1** deployment on a task definition ending `:2`.

That fourth line is the one that will actually stop you in a later lab. A scalable target left with a
raised floor is a service that costs more than it should and disagrees with `configs/lab-04a.env`, and the
CloudFormation lab will produce a template that bakes the wrong number in.

**Read ahead, five minutes:** find out why an S3 bucket name has to be globally unique across every AWS
account in the world, and what that means for a course in which every student is creating a bucket called
`usms-student-data` on their own emulator. Then find out what a **gateway** VPC endpoint is and how it
differs from an **interface** endpoint — Lab 02 built the first kind, and Lab 05 is where it finally
carries traffic.

Finally, take a snapshot so that a mistake in Lab 05 is recoverable:

```bash
floci snapshot save lab-04c-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback. Stop Floci first —
archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-04c.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-04c.tar.gz
```

The archive lives in your home directory, **outside** the repository, so it is never a commit candidate.

---

## Appendix A — Command Reference

Every command this lab used, grouped by service.

### Application Auto Scaling — scalable targets

| Command | What it does |
| --- | --- |
| `aws application-autoscaling register-scalable-target` | Create **or update** a registration. `--service-namespace`, `--resource-id`, `--scalable-dimension`, `--min-capacity`, `--max-capacity`, `--suspended-state`, `--tags`. There is no `update-scalable-target` |
| `aws application-autoscaling describe-scalable-targets` | Read them. `--resource-ids` filters; omit it to list the whole namespace. Returns `RoleARN`, `SuspendedState` and `CreationTime` |
| `aws application-autoscaling deregister-scalable-target` | Remove a registration — **and every policy and scheduled action attached to it** |
| `aws application-autoscaling list-tags-for-resource` / `tag-resource` / `untag-resource` | Tags on a scalable target, addressed by its `ScalableTargetARN` |

### Application Auto Scaling — policies, schedules and history

| Command | What it does |
| --- | --- |
| `aws application-autoscaling put-scaling-policy` | Create or replace a policy. `--policy-type TargetTrackingScaling` with `--target-tracking-scaling-policy-configuration`, or `StepScaling` with `--step-scaling-policy-configuration` |
| `aws application-autoscaling describe-scaling-policies` | Read them. `--policy-names` filters; the `Alarms` list names every alarm involved, managed or yours |
| `aws application-autoscaling delete-scaling-policy` | Delete one. A target tracking policy takes its two managed alarms with it |
| `aws application-autoscaling put-scheduled-action` | Create or replace a scheduled action. `--schedule` with `cron(...)`, `rate(...)` or `at(...)`; `--timezone`; `--scalable-target-action MinCapacity=,MaxCapacity=` |
| `aws application-autoscaling describe-scheduled-actions` | Read them, with their schedules and time zones |
| `aws application-autoscaling delete-scheduled-action` | Delete one. **Does not undo a bound it already changed** |
| `aws application-autoscaling describe-scaling-activities` | The history. `Cause` names the alarm and the policy; `--include-not-scaled-activities` adds the decisions *not* to scale, with `NotScaledReasons` |

### CloudWatch

| Command | What it does |
| --- | --- |
| `aws cloudwatch put-metric-data` | Publish a custom metric. `--namespace`, `--metric-name`, `--value`, `--unit`, `--dimensions Name=Value` (a plain map) |
| `aws cloudwatch list-metrics` | Discover metrics. `--namespace` filters |
| `aws cloudwatch get-metric-statistics` | Read datapoints. Needs `--start-time`, `--end-time`, `--period`, `--statistics` |
| `aws cloudwatch put-metric-alarm` | Create or replace an alarm. `--dimensions Name=X,Value=Y` (**not** the same shorthand as `put-metric-data`), `--alarm-actions`, `--treat-missing-data` |
| `aws cloudwatch describe-alarms` | Read alarms. `--alarm-names` or `--alarm-name-prefix`; `AlarmActions` is the field that proves a link |
| `aws cloudwatch set-alarm-state` | Force a state **and invoke its actions**. A documented testing operation, and a real privilege |
| `aws cloudwatch delete-alarms` | Delete one or more. Takes several names in one call |
| — | **There is no `delete-metric`.** Metrics cannot be deleted; they expire |

### IAM, ECS and ELBv2 used in this lab

| Command | What it does |
| --- | --- |
| `aws iam create-service-linked-role --aws-service-name ecs.application-autoscaling.amazonaws.com` | Create the role Application Auto Scaling uses. You choose neither its name nor its policies |
| `aws iam get-role` | Read it. Note the `/aws-service-role/...` path |
| `aws iam delete-service-linked-role` | The correct removal. Not `delete-role` |
| `aws iam get-policy` / `get-policy-version` | Read a customer managed policy document — Exercise 5 point 5 |
| `aws ecs describe-services` | `serviceArn` for the resource ID; `desiredCount` for everything else |
| `aws ecs update-service --desired-count` | A manual override, which a policy will undo. Step 12 part 6 says why |
| `aws elbv2 describe-load-balancers` / `describe-target-groups` | The two ARNs the `ResourceLabel` is built from |
| `aws elbv2 describe-target-health` | Where a task created by a scaling policy ends up — Step 15 block 6 |

**Six tag and dimension conventions now, across six services, and no rule connects them:**

| Service | Syntax |
| --- | --- |
| EC2 | `--tag-specifications 'ResourceType=x,Tags=[{Key=K,Value=V}]'` |
| ECS | `--tags key=K,value=V` (lower case) |
| IAM | `--tags Key=K,Value=V` (capitals) |
| CloudWatch Logs | `--tags K=V` (a plain map) |
| Elastic Load Balancing | `--tags Key=K,Value=V` (capitals, like IAM) |
| Application Auto Scaling | `--tags K=V` (a plain map, like CloudWatch Logs) |

And, inside one service, two shapes for the same concept:

| Operation | `--dimensions` syntax |
| --- | --- |
| `cloudwatch put-metric-data` | `Service=enrolment` |
| `cloudwatch put-metric-alarm` | `Name=Service,Value=enrolment` |

Run `aws <service> <operation> help` and read the synopsis. That habit is more durable than memorising any
of the eight.

---

## Appendix B — New JMESPath and CLI patterns introduced

Labs 1 to 04B taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()` with `&`,
`length()`, `contains()`, `starts_with()`, `@`, slices, flattening with `[]`, backtick literals, single-
quoted string literals, `&&` and `||` inside filters, `--filters`, `--generate-cli-skeleton`,
`--cli-input-json`, `--max-items`, waiters and three kinds of CLI list shorthand. This lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `SuspendedState.*` | An **object projection**: `*` after a dot yields every *value* of a hash, discarding the keys. Three booleans out of one field | Steps 13, 14, Section 9 |
| `SuspendedState.* \| grep -ci true` | One number that must be zero, instead of three fields you have to read. `-i` because `--output text` renders a JSON boolean as `True` with a capital letter | Steps 13, 17, Section 9 |
| `StepAdjustments[-1].MetricIntervalUpperBound` | A **negative index** — JMESPath counts from the end. An absent field reads as `None` under `--output text`, which is how you assert that the top step is open-ended | Section 9 |
| `ScalableTargets[?ResourceId=='$RID'].ScalableDimension \| [0]` | A raw string literal in single quotes, inside a double-quoted shell string so the variable expands, then a first-match take | Step 14 |
| `ScalingPolicies[?PolicyType=='StepScaling'].PolicyName \| [0]` | Finding an object by **what it is** rather than by what it was called. A better persistence check than a name lookup | Step 14 |
| `MetricAlarms[?contains(AlarmName, ` + backtick + `AlarmHigh` + backtick + `)]` | `contains()` with a backtick literal, to pick one of two managed alarms whose names contain a UUID | Step 15 |
| `--alarm-name-prefix "TargetTracking-$RID"` | A server-side prefix filter whose value you constructed. The managed alarm names are derivable, which is the whole point of Step 8 | Steps 8, 13, 15, Section 9 |
| `--include-not-scaled-activities` | Application Auto Scaling's best diagnostic: the decisions **not** to scale, with reasons, omitted by default | Section 11 |
| `--scalable-target-action MinCapacity=4,MaxCapacity=10` | A single nested structure in shorthand, on a flag that takes exactly one | Step 11 |
| `--suspended-state A=true,B=false,C=false` and `file://...` | The same structure two ways, and a reason to prefer the file for a setting whose hazard is being forgotten | Step 13 |
| `"${SVC_ARN##*:}"` | Strip the longest `*:` prefix — the last colon-separated field of an ARN. The resource ID, in one expansion | Steps 5, 14, Section 9 |
| `"${ALB_ARN#*:loadbalancer/}"` | Strip the **shortest** prefix matching a multi-character delimiter. Half of the `ResourceLabel` | Step 9 |
| `printf '%s' "$X" \| awk -F/ '{print NF}'` | Counting path segments, to validate a constructed identifier before using it | Steps 5, 9 |
| `awk -F: '{print \$NF}'` inside an **unquoted** heredoc | The one place in the course where a dollar sign must be escaped to survive an unquoted heredoc | Step 16 |
| `... --output text \| grep -E '^arn:' \|\| echo not-created` | Turning `None` into a meaningful token, so an empty-value check can tell "unsupported" from "you skipped a step" | Step 16 |
| `python3 -c "import datetime;print(...)"` for every timestamp | GNU `date` and BSD `date` disagree about every flag that matters | Steps 11, 12 |
| `python3 - "$f" << 'PY'` for an in-place edit | `sed -i` is not portable between GNU and BSD; a backed-up Python read-modify-write is | Step 17 |
| `cut -d. -f1` on a float from `--output text` | `50.0` compared as `50`, because `--output text` renders a JSON number and `test` compares strings | Section 9 |

### The distinction to keep straight

**Two AWS services whose names are nearly the same, and one ARN namespace shared between them:**

```text
aws autoscaling                 EC2 Auto Scaling. Groups, launch templates, predictive scaling
aws application-autoscaling     THIS SERVICE. Scalable targets in nine namespaces, no predictive
arn:aws:autoscaling:...         used by BOTH — a policy created by the second has an ARN
                                in the first's namespace, and nothing in it says "application"
```

**And the four constructed identifiers this architecture now uses, all for the same service:**

```text
ECS control-plane calls     --cluster usms-ecs-cluster --service usms-enrolment-svc
ECS tagging calls           --resource-arn arn:aws:ecs:...:service/usms-ecs-cluster/usms-enrolment-svc
Application Auto Scaling    --resource-id  service/usms-ecs-cluster/usms-enrolment-svc
ELB request-count metric    ResourceLabel  app/<lb-name>/<lb-id>/targetgroup/<tg-name>/<tg-id>
```

The third is the suffix of the second. The fourth is built from fragments of two entirely different ARNs.
Being able to construct each one from the right source, rather than guessing, is Review Question 2 — and
it is the skill that separates reading AWS documentation from using it.

---

## Sources

- [What is Application Auto Scaling?](https://docs.aws.amazon.com/autoscaling/application/userguide/what-is-application-auto-scaling.html)
- [Application Auto Scaling — services that you can use with it, and their resource ID formats](https://docs.aws.amazon.com/autoscaling/application/userguide/integrated-services-list.html)
- [Register a scalable target](https://docs.aws.amazon.com/autoscaling/application/userguide/services-that-can-integrate.html)
- [Target tracking scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-target-tracking.html)
- [Step scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-step-scaling-policies.html)
- [Scheduled scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/scheduled-scaling.html)
- [Suspend and resume scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-suspend-resume-scaling.html)
- [`PredefinedMetricSpecification`, including `ResourceLabel`](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_PredefinedMetricSpecification.html)
- [`StepAdjustment` — metric interval bounds](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_StepAdjustment.html)
- [`SuspendedState`](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_SuspendedState.html)
- [Service-linked roles for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/security_iam_service-with-iam.html)
- [Automatically scale your Amazon ECS service](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-auto-scaling.html)
- [Amazon ECS cluster auto scaling — the different mechanism §12.3 contrasts](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cluster-auto-scaling.html)
- [Amazon ECS CloudWatch metrics, including CPUUtilization and MemoryUtilization](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-metrics.html)
- [CloudWatch metrics for your Application Load Balancer, including RequestCountPerTarget](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html)
- [Using Amazon CloudWatch alarms, including TreatMissingData](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html)
- [Publish custom metrics to CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/publishingMetrics.html)
- [`SetAlarmState` — testing an alarm's actions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)
- [Schedule expressions for rules — the six-field cron form](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-scheduled-rule-pattern.html)
- [Predictive scaling — an EC2 Auto Scaling feature, for contrast](https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-predictive-scaling.html)
- [Amazon VPC subnet sizing and the addresses AWS reserves — Exercise 4](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html)
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Application Auto Scaling service quotas](https://docs.aws.amazon.com/general/latest/gr/as-app.html)
- [`aws application-autoscaling` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/application-autoscaling/)
- [`aws cloudwatch` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/cloudwatch/)
- [JMESPath specification](https://jmespath.org/specification.html)

---

*Lab 04C complete, and with it Practical 3. The USMS enrolment service now has an identity, a network, a
blueprint, a controller, a front door and a control loop — and the only thing this laboratory added to the
architecture underneath it was a floor, a ceiling, and five objects that argue about one integer between
them. Lab 05 finally creates `usms-student-data`, the bucket two IAM policies and one VPC endpoint have
been waiting four laboratories for. Before you start it, run `verify-lab-04c.sh` one more time, confirm
that no suspension switch is set, and check that `describe-scalable-targets` still reports a floor of 2.*
# Lab 06 - Implementing Auto Scaling for an ECS-Based Application

## 1. Objectives

- Register `usms-enrolment-svc` as a scalable target (min 2, max 10) and read the service-linked role that writes `desiredCount` for you.
- Add two target tracking policies (CPU and `ALBRequestCountPerTarget`), a step scaling policy driven by your own CloudWatch alarm, and two scheduled actions.
- Fire the alarm and prove that something other than you moved `desiredCount`; suspend and resume scaling.
- Prove the scaling configuration survives a restart and save its names to `configs/lab-06.env`.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [Application Auto Scaling on ECS](../unit2/topic3.md#application-auto-scaling-on-ecs) ·
    [why the signal matters](../unit2/topic3.md#why-auto-scaling-exists-and-why-the-signal-matters-more-than-the-mechanism) ·
    [choosing the scaling metric](../unit2/topic3.md#choosing-the-scaling-metric) ·
    [the two scaling layers](../unit2/topic3.md#the-two-scaling-layers-revisited) ·
    [Application Auto Scaling vs EC2 Auto Scaling](../unit7/topic1.md#application-auto-scaling-and-ec2-auto-scaling) ·
    [custom metrics](../unit7/topic1.md#custom-metrics-and-the-four-ways-to-publish-them) ·
    [how an alarm evaluates data](../unit7/topic3.md#how-an-alarm-evaluates-data) ·
    [missing-data treatment](../unit7/topic3.md#missing-data-treatment) ·
    [alarm actions](../unit7/topic3.md#alarm-actions) ·
    [service-linked roles](../unit8/topic1.md#service-roles-instance-profiles-and-service-linked-roles)

---

## 2. Prerequisites

- Lab 04 complete: `usms-ecs-cluster`, the `usms-enrolment` family and `usms-enrolment-svc` as Lab 04 left them.
- Lab 05 complete: `./scripts/utilities/verify-lab-05.sh` reports `FAIL=0` **before you start**.
- `verify-lab-04.sh` reports `FAIL=0` or exactly the one documented failure on the `usms-app-sg` source check (caused by Lab 05 Step 13, repaired by Lab 05 Exercise 2). Any other failure is not acceptable.
- The service at its baseline: `desiredCount` 2, one deployment. Step 5 raises the count immediately if the service is below the new minimum.
- Errata 01 applied: `echo "$AWS_PROFILE"` in a brand-new terminal must print `floci`.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`.
- `jq` and `python3` installed. `python3` produces every timestamp, because GNU and BSD `date` disagree.

```bash
cd ~/aws-floci-course
for t in jq python3 docker; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
./scripts/utilities/floci-storage-check.sh
```

> Example output - your versions and paths will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
aws-cli/2.17.42 Python/3.11.9 Darwin/23.5.0 exe/x86_64
...
PASS=16  FAIL=0
```

Three tools found and `PASS=16  FAIL=0`. A failure in the storage check's `shell and profile` block is the real problem; fix it first.

!!! tip "Have your measured scale-out latency to hand"
    Lab 04 Exercise 5 and Lab 05 Exercise 5 measured how long a scale-out and a capacity replacement take. Every cooldown in this lab is sized against those figures (or the cited Fargate start-up figure).

    ```bash
    cat outputs/lab-04-scale-latency.txt 2>/dev/null || echo "not measured - use the cited figure"
    cat outputs/lab-05-lab06-readiness.txt 2>/dev/null | grep -i elapsed || true
    ```

---

## 3. What This Lab Reuses

From Lab 04:

- `usms-ecs-cluster` and `usms-enrolment-svc`: Step 5 builds the scalable target's resource ID from the service's ARN.
- `USMS_ECS_DESIRED_BASELINE` (2): Step 5 uses it as `MinCapacity`, one task per Availability Zone.
- Container Insights: Step 7's CPU metric exists only because Lab 04 Step 4 enabled it.
- `usms-enrolment:2`: untouched; this lab registers no revision (Step 15 checks).

From Lab 05:

- `usms-enrolment-alb` and `usms-enrolment-tg`: Step 9 builds the `ResourceLabel` from both ARNs (or uses `USMS_ALB_RESOURCE_LABEL` from Lab 05 Exercise 5).
- `healthCheckGracePeriodSeconds` (60): Step 12 explains why a new task is not useful capacity for another minute.

From Lab 02: `usms-private-subnet-a` and `-b`, where scaled tasks appear (Step 15, Exercise 4).

```text
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
- templates/lab-06-target-tracking-cpu.json, templates/lab-06-target-tracking-requests.json,
  templates/lab-06-step-scaling-out.json, templates/lab-06-suspended-state.json
- configs/lab-06.env
- scripts/utilities/verify-lab-06.sh
- scripts/cleanup/lab-06-cleanup.sh

Required for future labs:
- the scalable target      -> the CloudWatch lab reads its scaling activities and its managed alarms
- usms-enrolment-queue-high -> the CloudWatch lab replaces set-alarm-state with a real alarm action
- USMS/Enrolment metric    -> the CloudWatch lab graphs it and builds a dashboard from it
- configs/lab-06.env      -> the CloudFormation lab re-declares every object in it as a template
- outputs/lab-06-scaling-history.json (Exercise 5) -> Lab 10's first put-object needs a real file
- usms-ecs-task-role       -> Lab 10 creates the bucket its attached policy already names
```
```

---

## 4. What We Are Building

Three kinds of scaling on one service, plus the ability to switch all of them off without deleting any of them. Application Auto Scaling writes **one integer**, `desiredCount`; ECS, the target group and the load balancer you already built do everything after that.

!!! info "Why reactive scaling is always late"
    A metric must be published, aggregated, compared and turned into an alarm state; then ECS starts a task and the load balancer health-checks it. Two to three minutes pass, served by the capacity you already had. Three consequences shape this lab:

    - **The minimum capacity is a latency decision**, not a cost decision: the floor absorbs the first minutes of any spike.
    - **Scale out eagerly, scale in reluctantly**: `ScaleOutCooldown` 60 against `ScaleInCooldown` 300 (the AWS default is 300 for both).
    - **For a spike you know about, use scheduled scaling** (Step 11); it is the only form that can be early.

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

The floor of 2 is one task per AZ; the ceiling of 10 guards against a runaway policy (Exercise 4 checks it against Lab 02's subnet sizes). Step scaling exists for the piecewise requirement target tracking cannot express (Step 10).

---

## 5. Architecture

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
  |                     ScheduledScaling   - three independent switches |
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

## 6. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-06-ecs-autoscaling/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 12
├── templates/
│   ├── lab-06-target-tracking-cpu.json               # NEW - put-scaling-policy config
│   ├── lab-06-target-tracking-requests.json          # NEW - the ALB metric config
│   ├── lab-06-step-scaling-out.json                  # NEW - step adjustments
│   └── lab-06-suspended-state.json                   # NEW - register-scalable-target config
├── configs/
│   └── lab-06.env                                    # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-06.sh                          # NEW - Section 8
│   └── cleanup/
│       └── lab-06-cleanup.sh                         # NEW - end of course only
└── outputs/
    └── lab-06-*.json / *.txt                         # command output, git-ignored
```

There is no new file under `policies/`: every document this lab writes is an API request body, not a permissions policy.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-06-ecs-autoscaling
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs-fargate
labs/lab-05-ecs-alb  labs/lab-06-ecs-autoscaling
```

---

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Capture every identifier with `$(...)`, `--query` and `--output text`; never type one. Step 16 writes them to `configs/lab-06.env`.

### Step 1 - Resume the environment and load six env files

Bring Floci up and load what Labs 01 to 05 recorded. Step 9 cannot build its composite string without the load balancer and target group ARNs.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04.env
source configs/lab-05.env

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

`whoami.sh` exits 1 if the account is not `000000000000`. The six env files define no variable twice, so order does not matter.

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

> Example output - your IDs and ARN suffixes will differ.

**Verify:** fourteen non-empty values. In particular:

- `baseline desired` must be `2`; Step 5 uses it as the minimum.
- `target group arn` empty means `configs/lab-05.env` is incomplete; re-run Lab 05 Step 18.
- `grace period` empty or `None` means Lab 05 Step 10's attachment did not take; it changes Step 12's arithmetic.

---

### Step 2 - Confirm Labs 02, 03, 04 and 05 are still intact

Every fault in the service will present itself as a fault in the scaling, so confirm the foundation first.

```bash
./scripts/utilities/verify-lab-02.sh  | tail -3
./scripts/utilities/verify-lab-03.sh  | tail -3
./scripts/utilities/verify-lab-04.sh | tail -3
./scripts/utilities/verify-lab-05.sh | tee outputs/lab-06-pre-verify-05.txt | tail -3

echo "== the one failure that is allowed, and only this one =="
./scripts/utilities/verify-lab-04.sh | grep FAIL || echo "no failures in 04"
```

The Lab 05 run is saved to `outputs/` so you can `diff` it against a run at the end: this lab must not change Lab 05's objects.

**Expected result**

```text
PASS=33  FAIL=0
PASS=36  FAIL=0
PASS=48  FAIL=1
PASS=49  FAIL=0
== the one failure that is allowed, and only this one ==
  FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)
```

> Example output. If you completed Lab 05's Exercise 2, the third line reads `PASS=50  FAIL=0` - the
> count changed because that exercise added a check - and the last block prints `no failures in 04`.
> Both are correct.

**Verify:** `FAIL=0` from Labs 02, 03 and 05; Lab 04 at `FAIL=0` or the single documented failure. A failure under `== Environment ==` is the real problem; fix it with `./scripts/utilities/floci-storage-check.sh`.

Now confirm the service state Step 5 depends on:

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments),LBs:length(loadBalancers)}' \
  --output json
```

`Desired` is `2`, `Deployments` is `1`, `LBs` is `1`. If `Desired` is anything else, reset it with `aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" --desired-count 2` before going on.

---

### Step 3 - Probe what this Floci build supports

Find out now which parts of Application Auto Scaling and CloudWatch your build implements, rather than at Step 12.

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

- An empty list from `describe-scalable-targets` is a successful answer: nothing is registered yet.
- `SUPPORTED` on a `--generate-cli-skeleton` probe means your CLI knows the operation, not that the emulator implements it; that is why the reads are probed too.

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

> Example output - this is the best case. Yours may differ, and that is exactly why the probe exists.

**Verify:** record your path at the top of `notes/lab-06-notes.md`.

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | Every call answers, and `set-alarm-state` at Step 12 moves `desiredCount` | Do every step as written |
| **B - control plane only** | Objects are created and describable, but `describe-scaling-activities` stays empty and `desiredCount` never moves on its own | Everything still works; Step 12 uses its control-plane fallback proof |
| **C - no Application Auto Scaling** | `describe-scalable-targets` does not answer, or `register-scalable-target` fails with `InvalidAction` | Tell your instructor. Do Exercises 4 and 5 and Section 14 |

!!! note "Floci Limitation - the scaling loop may be modelled without being closed"
    Floci may store targets, policies and scheduled actions without running the loop: no alarm fires by itself and `describe-scaling-activities` stays empty. Some builds honour `set-alarm-state`.

    Real AWS evaluates every alarm each minute, invokes the policy within seconds and records an activity whose cause names the alarm.

    Nothing this lab asks you to prove requires the loop, except Step 12, which has a control-plane fallback. Claiming an activity you did not observe is worth negative marks.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01 + lab-02 + lab-03 + lab-04 + lab-05 sourced
 ├── verify-lab-02/03/05 all FAIL=0; verify-lab-04 FAIL=0 or the ONE documented failure
 ├── outputs/lab-06-pre-verify-05.txt captured, for comparison at the end
 ├── service at its baseline: desired 2, one deployment, one load balancer
 └── support path recorded: A (full) / B (control plane only) / C (no ASA)
```

---

!!! info "Application Auto Scaling in brief"
    A **scalable target** is a registration: "this dimension of this resource may move between these two numbers". **Scaling policies** (target tracking or step) decide the number; **scheduled actions** change the floor and ceiling at a time. Every reactive decision is made by a **CloudWatch alarm**. The target's address has three parts, none of them an ARN: namespace `ecs`, resource ID `service/<cluster>/<service>` (exactly the suffix of the service ARN), and dimension `ecs:service:DesiredCount` (case-sensitive). Predictive scaling exists only in EC2 Auto Scaling, not for ECS services. See [Application Auto Scaling on ECS](../unit2/topic3.md#application-auto-scaling-on-ecs).

### Step 4 - Create the service-linked role that writes `desiredCount`

Application Auto Scaling calls `ecs:UpdateService` on your behalf through a **service-linked role**: AWS fixes its name, writes its trust policy and owns its permissions policy. You only create it. See [service-linked roles](../unit8/topic1.md#service-roles-instance-profiles-and-service-linked-roles).

**Command - part 1, create it**

```bash
ASA_SLR="AWSServiceRoleForApplicationAutoScaling_ECSService"

aws iam create-service-linked-role \
  --aws-service-name ecs.application-autoscaling.amazonaws.com \
  --description "Allows Application Auto Scaling to change the desired count of USMS ECS services" \
  --query 'Role.[RoleName,Arn]' \
  --output text \
  || echo "not created - see the note below; this is often already present, and sometimes unsupported"
```

- `--aws-service-name` is the service principal `ecs.application-autoscaling.amazonaws.com`, not `ecs.amazonaws.com` and not the generic `application-autoscaling.amazonaws.com`.
- `InvalidInput` saying the role already exists is fine (one per account). The operation being unsupported on your build is also fine.

**Command - part 2, read it back**

```bash
aws iam get-role --role-name "$ASA_SLR" \
  --query 'Role.{Name:RoleName,Arn:Arn,Path:Path,Trust:AssumeRolePolicyDocument.Statement[0].Principal.Service}' \
  --output json \
  || echo "role not present on this build - record it as a limitation and continue"

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

> Example output - the attached policy name may differ or be absent on this build.

**Verify:** the `Path` is `/aws-service-role/<service principal>/`, not `/`. That marks it as owned by a service; remove one with `aws iam delete-service-linked-role`, not `delete-role`. If the role is absent, record it in `notes/lab-06-notes.md` and continue (on real AWS, Step 5 would fail being unable to assume it).

!!! note "Floci Limitation - the role exists as a record, and nothing assumes it"
    Floci does not assume the role or authorize requests against IAM policies.

    On real AWS every `UpdateService` call the service makes uses this role, and CloudTrail records it as the invoker.

    When an AWS service modifies your resources, the answer is always a role, usually one named `AWSServiceRoleFor...`.

---

### Step 5 - Register the scalable target

The object every policy and scheduled action attaches to, holding the floor of 2 and ceiling of 10.

**Command - part 1, build the resource ID from the API, not by hand**

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
  echo "UNEXPECTED SHAPE ($SEGMENTS segments, first '$FIRST') - falling back to constructing it"
  RID="service/${USMS_ECS_CLUSTER}/${USMS_ENROLMENT_SERVICE}"
  echo "resource id : $RID"
fi

SDIM="ecs:service:DesiredCount"
```

- `"${SVC_ARN##*:}"` strips the longest prefix ending in `:`, leaving everything after the last colon.
- The segment check catches the legacy short ARN format (`service/<service>`, two segments), which `register-scalable-target` rejects with an error that does not mention ARN formats.

!!! tip "If Lab 04's Exercise 5 recorded this already, cross-check it"
    The two values must agree. A disagreement means the service was recreated; the value derived now is correct.

    ```bash
    echo "derived here  : $RID"
    echo "from lab-04  : ${USMS_SCALABLE_RESOURCE_ID:-<not recorded>}"
    ```

**Command - part 2, register it**

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --min-capacity "$USMS_ECS_DESIRED_BASELINE" \
  --max-capacity 10 \
  --tags Project=USMS,Name=usms-enrolment-scalable-target,Tier=app,Lab=06 \
  --query 'ScalableTargetARN' \
  --output text \
  || aws application-autoscaling register-scalable-target \
       --service-namespace ecs \
       --resource-id "$RID" \
       --scalable-dimension "$SDIM" \
       --min-capacity "$USMS_ECS_DESIRED_BASELINE" \
       --max-capacity 10
```

- `aws application-autoscaling`, not `aws autoscaling` (EC2 Auto Scaling, a different service).
- `--min-capacity` is enforced: registering raises `desiredCount` immediately if the service is below the floor. Part 3 checks.
- `--tags` is a plain map (`K=V`). The `||` fallback registers without tags on builds or CLIs that reject the flag.

**Expected result**

```text
arn:aws:application-autoscaling:us-east-1:000000000000:scalable-target/0a1b2c3d4e5f6789
```

> Example output. On builds that do not return `ScalableTargetARN` the command prints nothing at all and
> exits 0, which is also fine - a successful registration has no required output, and Step 6 is where you
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

> Example output - your creation time will differ, and `Role` may be absent or empty on a build with no
> service-linked role.

`Min` 2, `Max` 10, `Dimension` exactly `ecs:service:DesiredCount`. `Role` names Step 4's role although you passed no `--role-arn`. `Suspended` has three fields, all `false` (Step 13 changes them; Section 8 asserts them).

**Command - part 3, find out what registering it did to the service**

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,Pending:pendingCount,Deployments:length(deployments)}' \
  --output json
```

`Desired` is still `2`: registration is a no-op when the service is already inside the bounds. Had it been at 1, this would show `Desired` 2 with no policy involved (Review Question 3).

---

### Step 6 - Change the bounds, and learn what a re-registration is

There is no `update-scalable-target`. To change the bounds you register again at the same address (namespace, resource ID, dimension): the content is replaced, attached policies are not disturbed, and a parameter you omit is left as it was.

**Command - part 1, raise the ceiling, then read it back**

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

The minimum is still `2` although you passed only `--max-capacity`.

**Command - part 2, put it back**

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

**Verify:** exactly **one** row with `Min` 2 and `Max` 10. A second row is a target at a slightly different address (a typo), and it will silently do nothing.

```bash
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'length(ScalableTargets)' --output text
```

That must print `1`. If it prints `2`, the last entry in Section 10 removes the wrong one.

✏️ **Your turn**

Work out, without running anything, what would happen if you re-registered this target with
`--min-capacity 5` while the service is running two tasks. Then do it, observe, and put it back to 2.

```text
Expected result:
desiredCount moves to 5 within seconds of the registration, with no scaling policy
involved and no alarm having fired. describe-scaling-activities may or may not record
it - find out which, on your build, and say so.

Then answer in one sentence each in notes/lab-06-notes.md:
(a) Which object made that change: the scalable target, a scaling policy, or ECS?
(b) You are on call. A colleague raises MinCapacity to 5 to ride out an incident and
    goes to bed without telling anyone. What is the cost of that, and which single
    API call would have told you it had happened?
```

Hint: Step 5 part 3 shows the shape of (a); for (b), one command in this step returns the value a monitor would compare.

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
      └── policies           NONE YET - this target can be scaled and nothing decides to
```

A target with no policies enforces its bounds and nothing else.

---

!!! info "What target tracking does"
    You give it one metric and one target value. It creates **two CloudWatch alarms** (high and low, named `TargetTracking-<resource id>-...`), attaches itself to both, and **computes a capacity** rather than adding a fixed step: 4 tasks at 80 per cent CPU with a target of 50 gives `4 x 80 / 50 = 6.4`, so 7 tasks. The metric must fall as capacity rises (a per-target or per-task metric, never a total), scale-in is deliberately conservative, and the floor and ceiling always win. `ScaleOutCooldown` (60) and `ScaleInCooldown` (300) govern how soon the policy may act **again in the same direction**; size `ScaleOutCooldown` against task start-up plus the 60-second grace period. See [Application Auto Scaling on ECS](../unit2/topic3.md#application-auto-scaling-on-ecs).

### Step 7 - Create the CPU target tracking policy

The first policy, on the metric Lab 04's Container Insights setting publishes. ECS offers three predefined metrics: `ECSServiceAverageCPUUtilization` (here), `ECSServiceAverageMemoryUtilization` (Exercise 1) and `ALBRequestCountPerTarget` (Step 9). Fargate CPU is a percentage of the CPU the task **reserved** (256 units here), so a CPU target is only meaningful relative to that reservation.

**Command - part 1, write the policy configuration**

```bash
cat > templates/lab-06-target-tracking-cpu.json << 'EOF'
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

python3 -m json.tool templates/lab-06-target-tracking-cpu.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-06-target-tracking-cpu.json
```

!!! warning "Quoted heredoc"
    `<< 'EOF'` because this document has no variables. Step 9's document has one and must use `<< EOF`. `grep -c '\$'` must print `0` in both cases.

- `TargetValue` `50.0` is half the reservation, leaving room to absorb a spike while the policy reacts. It is a float; a string is rejected.
- `DisableScaleIn` `false` is the default, stated so a reader does not have to know it.

**Command - part 2, create the policy**

```bash
CPU_POLICY="usms-enrolment-cpu-target-tracking"

CPU_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$CPU_POLICY" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://templates/lab-06-target-tracking-cpu.json \
  --query 'PolicyARN' \
  --output text)

echo "CPU_POLICY_ARN = $CPU_POLICY_ARN"
```

`put-scaling-policy` is create-or-replace: the same name with a new configuration silently updates the policy. `--policy-type` and the configuration flag must agree. The four address parameters are repeated on every call.

**Expected result**

```text
valid JSON
0
CPU_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:0a1b2c3d-4e5f-6789-abcd-ef0123456789:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-cpu-target-tracking
```

> Example output - your UUID will differ.

The ARN uses the `autoscaling` namespace (not `application-autoscaling`) and embeds the whole resource ID. Step 10 puts such an ARN into an alarm.

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

> Example output - your alarm UUIDs will differ, and on some builds `Alarms` is an empty list.

**You did not create the `Alarms`.** They appeared as a side effect of `put-scaling-policy`. If the list is empty on your build, record it and continue.

---

### Step 8 - Read the two alarms that target tracking created for you

Two alarms you did not write now exist. Recognise them, so nobody deletes them later.

**Command - part 1, find them**

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

> Example output - the exact thresholds, periods and evaluation counts are AWS's to choose and have
> changed between versions. On a build that creates no managed alarms this returns an empty list.

- `Namespace` `AWS/ECS` and `Metric` `CPUUtilization`: the predefined metric resolved for you (add `Dimensions:Dimensions[].[Name,Value]` to see your cluster and service).
- `Evals` 3 on the high alarm and 15 on the low one at `Period` 60: three minutes to scale out, fifteen to scale in, on top of your cooldowns. AWS chose those numbers.
- The thresholds differ (50 and 45): a dead band, so a metric at the target does not oscillate.
- `State` `INSUFFICIENT_DATA` takes no action, so a metric that stops being published means a service that never scales.
- `Actions` is 1 on each. Confirm it is the Step 7 policy:

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'MetricAlarms[].AlarmActions[]' --output text | tr '\t' '\n'
```

Every line must be your `$CPU_POLICY_ARN`.

!!! warning "Do not edit or delete these alarms"
    They belong to the policy: Application Auto Scaling recreates them when the policy changes and deletes them with it. An edited alarm is overwritten at the next `put-scaling-policy`; a deleted one leaves a policy that no longer scales in one direction, while `describe-scaling-policies` still lists the alarm. To change thresholds, change `TargetValue` or the cooldowns. For your own alarm, use step scaling (Step 10).

**Command - part 2, prove the naming is derivable**

```bash
echo "resource id            : $RID"
echo "managed alarm prefix   : TargetTracking-$RID"
aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'length(MetricAlarms)' --output text
```

`2`: two alarms per target tracking policy (4 after Step 9, 6 after Exercise 1). If your build returns none, write out in your notes what the two would have contained.

✏️ **Your turn**

Using only the numbers in the `describe-alarms` output above, work out on paper how long the enrolment
service would run at 100 per cent CPU before a third task started serving traffic. Then check your
arithmetic against the lab.

```text
Expected result:
A number of seconds, built from four separate delays, at least two of which are not in
this lab's own configuration. Write the four terms out.

Then answer in one sentence in notes/lab-06-notes.md:
Which ONE of the four terms would you change first if that total were unacceptable, and
what would it cost you?
```

Hint: the four terms are the high alarm's `Period` x `EvaluationPeriods`, policy invocation (about zero), Lab 04 Exercise 5's task start-up, and Lab 05 Step 10's grace period.

---

### Step 9 - Create the request-count policy, the row Lab 05 unlocked

`ALBRequestCountPerTarget` is the better signal for a web API: it measures the cause (requests) rather than a symptom (CPU), it does not depend on the task's CPU reservation, and it moves the instant load does. CPU is better only for CPU-bound work with variable cost per request (Review Question 7). See [choosing the scaling metric](../unit2/topic3.md#choosing-the-scaling-metric).

The metric needs a `ResourceLabel` built from fragments of two ARNs:

```text
app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
|-------------- from the ALB's ARN ----| |----------- from the target group's ARN -----|

arn:aws:elasticloadbalancing:...:loadbalancer/app/usms-enrolment-alb/50dc6c495c0c9188
                                             |------ take everything after this ------|

arn:aws:elasticloadbalancing:...:targetgroup/usms-enrolment-tg/73e2d6bc24d8a067
                                |--- and prefix it with the word "targetgroup/" ---|
```

**Command - part 1, get the label, from Lab 05 if it recorded one and from the API if not**

```bash
if [ -n "${USMS_ALB_RESOURCE_LABEL:-}" ]; then
  RESOURCE_LABEL="$USMS_ALB_RESOURCE_LABEL"
  echo "using the label Lab 05 Exercise 5 recorded"
else
  echo "no recorded label - deriving it from the API"
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

- `#*:loadbalancer/` strips the shortest prefix up to a multi-character delimiter; `##*:` strips up to the last colon.
- The check requires six segments, `app` first (an NLB would be `net`) and `targetgroup` fourth.

**Command - part 2, the policy configuration**

```bash
cat > templates/lab-06-target-tracking-requests.json << EOF
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

python3 -m json.tool templates/lab-06-target-tracking-requests.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-06-target-tracking-requests.json
grep ResourceLabel templates/lab-06-target-tracking-requests.json
```

!!! warning "Unquoted heredoc"
    `<< EOF` so `$RESOURCE_LABEL` expands as the file is written. `grep -c '\$'` must print `0`; `1` means the literal text `$RESOURCE_LABEL` reached the file.

`TargetValue` `1000.0` is **1000 requests per target per minute** (a one-minute `Sum`), not per second. It is a provisional number until a load test measures what one task can serve (Exercise 4).

**Command - part 3, create it**

```bash
REQ_POLICY="usms-enrolment-requests-target-tracking"

REQ_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$REQ_POLICY" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://templates/lab-06-target-tracking-requests.json \
  --query 'PolicyARN' \
  --output text) \
  && echo "REQ_POLICY_ARN = $REQ_POLICY_ARN" \
  || echo "ALBRequestCountPerTarget not supported on this build - record it and continue; Step 10 does not depend on it"
```

**Expected result**

```text
valid JSON
0
    "ResourceLabel": "app/usms-enrolment-alb/50dc6c495c0c9188/targetgroup/usms-enrolment-tg/73e2d6bc24d8a067"
REQ_POLICY_ARN = arn:aws:autoscaling:us-east-1:000000000000:scalingPolicy:1b2c3d4e-...:resource/ecs/service/usms-ecs-cluster/usms-enrolment-svc:policyName/usms-enrolment-requests-target-tracking
```

> Example output - your suffixes and UUID will differ.

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

Two policies, each with two alarms. When they disagree:

```text
SCALE OUT  -> the LARGEST capacity any policy asks for wins
SCALE IN   -> only when EVERY policy agrees that scaling in is safe
```

So a second policy on a **different** metric can only make the service larger. Two target tracking policies on the **same** metric with different targets fight each other and oscillate.

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

### Step 10 - Create a step scaling policy, and the alarm that drives it

Requirement: if the work queue is 100 deep add one task; if it is 200 deep add three. That is a piecewise response with no set point, so target tracking cannot express it, and queue depth does not fall predictably as capacity rises. Because you own the alarm, this is also what makes scaling observable on an emulator.

Step bounds are **relative to the alarm threshold**, not absolute values:

```text
alarm threshold = 100

  MetricIntervalLowerBound   MetricIntervalUpperBound   ScalingAdjustment
            0                          100                    +1
           100                       (none)                   +3
            |                           |
            +-- metric 100 to 200 ------+                 breach of 0 to 100
                metric 200 and above                      breach of 100 and above
```

Intervals must not overlap or leave a gap; one may omit its upper bound and one its lower. Scale-out bounds are non-negative; scale-in bounds are non-positive with negative adjustments (Exercise 2). `AdjustmentType` `ChangeInCapacity` adds tasks; `MetricAggregationType` `Average`; one `Cooldown` of 60.

**Command - part 1, publish the metric, so that it exists**

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

- A custom metric needs no registration; namespaces beginning `AWS/` are reserved. See [custom metrics](../unit7/topic1.md#custom-metrics-and-the-four-ways-to-publish-them).
- `put-metric-data --dimensions` takes `Service=enrolment`; `put-metric-alarm` in part 3 takes `Name=Service,Value=enrolment`. Same service, different shorthand: read the synopsis.

**Command - part 2, the step configuration**

```bash
cat > templates/lab-06-step-scaling-out.json << 'EOF'
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

python3 -m json.tool templates/lab-06-step-scaling-out.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-06-step-scaling-out.json
```

Quoted heredoc again; `grep -c '\$'` prints `0`.

**Command - part 3, create the policy, then the alarm that drives it**

```bash
STEP_POLICY="usms-enrolment-queue-step-out"

STEP_POLICY_ARN=$(aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --policy-name "$STEP_POLICY" \
  --policy-type StepScaling \
  --step-scaling-policy-configuration file://templates/lab-06-step-scaling-out.json \
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
  --tags Key=Name,Value=usms-enrolment-queue-high Key=Project,Value=USMS Key=Lab,Value=06

aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
  --query 'MetricAlarms[0].{Name:AlarmName,Namespace:Namespace,Metric:MetricName,Stat:Statistic,Period:Period,Evals:EvaluationPeriods,Op:ComparisonOperator,Threshold:Threshold,Missing:TreatMissingData,Actions:AlarmActions,State:StateValue}' \
  --output json
```

- **Policy first**: the alarm needs its ARN. Reversed, you get `ValidationError: Invalid metrics or alarm actions`.
- `--alarm-actions "$STEP_POLICY_ARN"` is the link target tracking made for you in Step 7. One alarm can also notify an SNS topic, which managed alarms cannot.
- `--treat-missing-data notBreaching` suits hand-published data; on a real system `breaching` has a strong argument (Review Question 4). See [missing-data treatment](../unit7/topic3.md#missing-data-treatment).
- `--evaluation-periods 1` at `--period 60` fires after one minute, more eagerly than the managed three.

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

> Example output - your UUID will differ, and `State` may be `INSUFFICIENT_DATA` rather than `OK`
> depending on whether your build evaluated the three datapoints you published.

**Verify**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$RID" --policy-names "$STEP_POLICY" \
  --query 'ScalingPolicies[0].{Name:PolicyName,Type:PolicyType,Adjust:StepScalingPolicyConfiguration.AdjustmentType,Agg:StepScalingPolicyConfiguration.MetricAggregationType,Cooldown:StepScalingPolicyConfiguration.Cooldown,Steps:StepScalingPolicyConfiguration.StepAdjustments,Alarms:Alarms[].AlarmName}' \
  --output json
```

- `Type` `StepScaling`, two `Steps`, the second with no `MetricIntervalUpperBound` (open-ended top).
- `Alarms` contains `usms-enrolment-queue-high`, although you only told the alarm about the policy.
- `Adjust` `ChangeInCapacity`. `ExactCapacity` would set the count to 1 or 3, a scale-in in disguise.

---

### Step 11 - Create two scheduled actions

The only mechanism that can have capacity ready before enrolment opens.

- A scheduled action sets `MinCapacity` and/or `MaxCapacity`, never `desiredCount`. Raising the floor to 4 at 07:45 pulls the count up; lowering it at 20:00 only **permits** the reactive policies to scale in. Setting min and max equal switches reactive scaling off for that window.
- Schedule forms: `at(...)` once (stays behind afterwards), `rate(...)`, and `cron(...)` with **six** fields (the last is the year), where one of day-of-month and day-of-week must be `?`.
- The Region (`us-east-1`) decides where tasks run; the time zone decides what 07:45 means. The default is **UTC**; pass `--timezone Asia/Thimphu`.

**Command - part 1, the morning scale-out**

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
  && echo "created $SCHED_OUT in UTC - record that you did the conversion by hand"
```

**Command - part 2, the evening scale-in**

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

Both actions state both bounds so they read as complete states. `put-scheduled-action` is create-or-replace.

**Expected result**

```text
created usms-enrolment-morning-scale-out
```

> Example output - a successful `put-scheduled-action` prints nothing of its own, so the `echo` is the
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

> Example output - the `Created` column is omitted here for width; yours will show it.

Two rows: morning `Min` 4, evening `Min` 2, both `Max` 10. An empty or `UTC` `TZ` means you took the fallback; note it, and what daylight saving would break.

✏️ **Your turn**

Exam results are published one night a semester and the load is enormous for about two hours. Create a
**one-off** scheduled action, `usms-enrolment-results-night`, using the `at()` form, that raises the floor
to 6 at a specific moment ten minutes from now, and watch what happens.

```text
Expected result:
describe-scheduled-actions shows three actions. Ten minutes later, IF your build runs
the scheduler, desiredCount is 6 and the scalable target's MinCapacity is 6 - with no
alarm having fired and no policy involved. If your build does not run the scheduler,
nothing happens, and the correct thing to record is that the action exists and the
mechanism was not observable.

Then answer in two sentences in notes/lab-06-notes.md:
An at() action does not remove itself after firing. Say what is left behind, why that
matters six months later, and which command you would put in the same runbook page as
the one that created it.
```

Hint: `python3 -c "import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S'))"` gives the timestamp on macOS and Linux; `at()` takes no offset, `--timezone` says what it means.

When you have finished looking at it, remove it - and read this first.

!!! danger "Read before running any delete command"
    **What will be deleted:** one scheduled action, `usms-enrolment-results-night`, which you created in
    the "Your turn" above.

    **What depends on it:** nothing. It is a calendar entry. Deleting it does not change the scalable
    target's current bounds, so if it has already fired and raised `MinCapacity` to 6, **that floor stays
    at 6 after the action is gone.** Deleting the thing that made a change does not undo the change.

    **Reversible?** Yes. One `put-scheduled-action` recreates it.

    **Effect on later labs:** none, **provided** you also put the floor back to 2. Section 8's script
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

`2` scheduled actions remaining, and `2	10` for the bounds: the floor had to be put back by hand.

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

### Step 12 - Fire the alarm, and prove that something other than you moved the number

The one step where `desiredCount` can change without you typing a number. The proof is create (Step 10), perturb (parts 2 and 3), read back (part 4): a number that moved and a record of who moved it. An ARN returned or `State: OK` proves nothing.

**Command - part 1, record the truth before**

```bash
python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" \
  > outputs/lab-06-pre-scale.txt

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text \
  >> outputs/lab-06-pre-scale.txt

aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs --resource-id "$RID" \
  --query 'length(ScalingActivities)' --output text \
  >> outputs/lab-06-pre-scale.txt

cat outputs/lab-06-pre-scale.txt
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

**Command - part 2, push the metric past the threshold the honest way**

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

`260` against `100` is a breach of `160`, which falls in the open-ended second interval: **+3 tasks**, from 2 to 5. Write the prediction down before you look. Datapoints come back unordered, hence `sort_by(...,&Timestamp)`.

On real AWS the alarm takes up to a minute to evaluate. Watch it:

```bash
for i in $(seq 1 8); do
  read -r state reason <<< "$(aws cloudwatch describe-alarms --alarm-names "$QUEUE_ALARM" \
    --query 'MetricAlarms[0].[StateValue,StateReason]' --output text)"
  printf 'poll %d  state=%-18s %s\n' "$i" "$state" "$reason"
  [ "$state" = "ALARM" ] && break
  sleep 15
done
```

**Command - part 3, if the alarm will not fire by itself, fire it deliberately**

Very likely on Floci, and it is not a failure of your work.

```bash
aws cloudwatch set-alarm-state \
  --alarm-name "$QUEUE_ALARM" \
  --state-value ALARM \
  --state-reason "Lab 06 Step 12: forcing the alarm state to prove the alarm-to-policy link" \
  && echo "alarm state forced to ALARM" \
  || echo "set-alarm-state not supported on this build - go to part 5"
```

`set-alarm-state` **invokes the alarm's actions** exactly as a real state change would; it is the documented way to test an alarm. Real CloudWatch overwrites the state at the next evaluation. `cloudwatch:SetAlarmState` on a production alarm is a real privilege.

**Command - part 4, read back the number and the record**

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

**Expected result - on a build where the loop runs**

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

> Example output - your timestamps and UUIDs will differ.

The `Cause` string names the alarm, the policy and the state change: the evidence that something other than you changed `desiredCount`. Screenshot it. `Successful` means ECS accepted the count, not that tasks are serving; `pending=3` plus the 60-second grace period is Section 4's lateness, visible.

| `StatusCode` | Meaning |
| --- | --- |
| `Pending` / `InProgress` | The call has been made and ECS has not confirmed |
| `Successful` | ECS accepted the new desired count |
| `Overridden` | A later activity superseded this one before it completed |
| `Unfulfilled` | The change could not be applied - on real AWS, usually the ceiling, a quota, or no addresses left in the subnet |
| `Failed` | The `UpdateService` call itself was rejected. Read `StatusMessage`; on real AWS this is where a service-linked role problem surfaces |

**Command - part 5, the fallback proof, which always works**

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
cfg = json.load(open('templates/lab-06-step-scaling-out.json'))
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
} | tee outputs/lab-06-scaling-proof.txt
```

**Verify:** each block names the next.

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

If block 6 says `2`, the chain is proven and the loop did not run; say so and name the link your build did not connect. If it says `5`, you have both proofs. Keep `outputs/lab-06-scaling-proof.txt` until you have submitted.

**Command - part 6, return to the baseline**

```bash
aws cloudwatch set-alarm-state --alarm-name "$QUEUE_ALARM" --state-value OK \
  --state-reason "Lab 06 Step 12 complete" 2>/dev/null || true

for v in 4 3 2; do
  aws cloudwatch put-metric-data --namespace "$METRIC_NS" --metric-name "$METRIC_NAME" \
    --value "$v" --unit Count --dimensions "$METRIC_DIM"
done

aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --desired-count 2 \
  --query 'service.desiredCount' --output text

python3 -c "import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" \
  > outputs/lab-06-post-scale.txt
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].[desiredCount,runningCount,pendingCount]' --output text \
  >> outputs/lab-06-post-scale.txt

paste outputs/lab-06-pre-scale.txt outputs/lab-06-post-scale.txt
```

The policies are still watching: if the metric stayed high, the next evaluation would scale out again. So push the metric down **first**, then set the count. A service under a scaling policy has no manual capacity; to hold a count, suspend (Step 13) or set min and max equal.

`Desired` back to `2`; the `paste` shows both timestamps.

**Checkpoint 5**

```text
Scaling observed (path A) or wiring proven (path B)
 ├── metric pushed to 260 against a threshold of 100  -> breach 160  -> step +3
 ├── alarm usms-enrolment-queue-high  ALARM (evaluated, or forced with set-alarm-state)
 ├── describe-scaling-activities Cause names BOTH the alarm and the policy
 │    (or outputs/lab-06-scaling-proof.txt records the six-block chain instead)
 ├── desiredCount 2 -> 5, pendingCount 3, and NO capacity for another 60+ seconds
 └── back to the baseline: metric down first, THEN the count
```

---

### Step 13 - Suspend and resume scaling

Stop the scaling and keep the policies: during a deployment, an incident, or a fixed-size load test.

| Field | When `true`, this stops | Leaves working |
| --- | --- | --- |
| `DynamicScalingInSuspended` | Scale-**in** by any policy | Scale-out, and scheduled actions |
| `DynamicScalingOutSuspended` | Scale-**out** by any policy | Scale-in, and scheduled actions |
| `ScheduledScalingSuspended` | Scheduled actions | Both directions of dynamic scaling |

Scale-in suspended is the safe choice when in doubt. Scale-out suspended is the dangerous one: a quiet hour can shrink you to the floor and you cannot grow back. Suspension belongs to the scalable target, so one call covers every policy.

!!! warning "A suspension is invisible unless you go and look for it"
    Policies, alarms and graphs all look normal. Only the target's `SuspendedState` shows it. A target left with `DynamicScalingOutSuspended: true` will not scale out in the next incident, which is why Section 8 asserts all three switches are `false` and why part 3 is not optional.

**Command - part 1, suspend scale-in only**

```bash
cat > templates/lab-06-suspended-state.json << 'EOF'
{
  "DynamicScalingInSuspended": true,
  "DynamicScalingOutSuspended": false,
  "ScheduledScalingSuspended": false
}
EOF

python3 -m json.tool templates/lab-06-suspended-state.json > /dev/null && echo "valid JSON"

aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id "$RID" \
  --scalable-dimension "$SDIM" \
  --suspended-state file://templates/lab-06-suspended-state.json \
  >/dev/null

aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs --resource-ids "$RID" \
  --query 'ScalableTargets[0].{Min:MinCapacity,Max:MaxCapacity,Suspended:SuspendedState}' \
  --output json
```

There is no `suspend-scaling` call: suspension is content of the registration (Step 6's change model), so the bounds survive. The document makes all three switches explicit and keeps the intervention in Git as a runbook page.

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

One `true`, two `false`, bounds unchanged. Three `true` means every form of scaling is off.

**Command - part 2, observe that the policies are untouched**

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs --resource-id "$RID" \
  --query 'ScalingPolicies[].[PolicyName,PolicyType]' --output text

aws cloudwatch describe-alarms --alarm-name-prefix "TargetTracking-${RID}" \
  --query 'length(MetricAlarms)' --output text
```

All three policies listed and the managed alarm count unchanged: suspending changes no configuration.

**Command - part 3, resume, and prove it**

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

The last line must be `0`. `SuspendedState.*` is an object projection (every value, keys discarded). `--output text` prints the three values on **one** line as `True`/`False`, so `grep -ci` counts matching lines and `-i` is essential: a case-sensitive `grep -c true` would always print `0`. Confirm the capitals:

```bash
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --resource-ids "$RID" --query 'ScalableTargets[0].SuspendedState.*' --output text
```

Part 3 uses shorthand so that `templates/lab-06-suspended-state.json` keeps the suspended configuration as the runbook artefact.

**Checkpoint 6**

```text
Suspension exercised and cleared
 ├── register-scalable-target --suspended-state   (there is no suspend-scaling call)
 ├── scale-in suspended, scale-out and scheduled left alone
 ├── all three policies and all four managed alarms UNCHANGED while suspended
 ├── resumed, and SuspendedState.* piped to grep -ci true returns 0
 └── templates/lab-06-suspended-state.json committed as the runbook artefact
```

---

### Step 14 - Prove the whole scaling configuration survives a restart

The state spans Application Auto Scaling, CloudWatch, ECS and IAM. A build that persists three of them leaves policies on a missing target or an alarm pointing at a reissued ARN, invisible until something needs to scale.

**Command - part 1, record the truth**

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
} > outputs/lab-06-pre-restart.txt

cat outputs/lab-06-pre-restart.txt
```

**Command - part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
source configs/lab-04.env
source configs/lab-05.env
```

`floci-down.sh` is `docker compose stop`: state kept. Never `docker compose down -v`. The shell variables survived because the terminal did, which is why part 3 does not use them.

**Command - part 3, read it back, deriving the resource ID from the API again**

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
} > outputs/lab-06-post-restart.txt

diff outputs/lab-06-pre-restart.txt outputs/lab-06-post-restart.txt \
  && echo "PERSISTENCE PROVEN: the scalable target with its bounds and its three suspension switches, all three scaling policies with their full configurations, both scheduled actions with their schedules and bounds, and the custom alarm with its threshold, its missing-data treatment and its one action are all unchanged" \
  || echo "PERSISTENCE FAILED: read the diff above, then run ./scripts/utilities/floci-storage-check.sh"
```

- Every identifier is re-derived from the API; reusing the variables would only prove Bash remembers strings (Lab 1 Step 14).
- Policies are found by property (`PolicyType=='StepScaling'`, `contains()`), so a changed type would fail the check.
- Only configuration is compared: `runningCount`, alarm state and the activity log may legitimately change.

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

On `PERSISTENCE FAILED`, read the `diff` first; it names which fact did not survive. Then run `./scripts/utilities/floci-storage-check.sh`. Managed alarm names are left out on purpose: some builds recreate them with new UUIDs.

**Checkpoint 7**

```text
Persistence proven for Lab 06
 ├── resource ID re-derived from the ECS service's ARN, not read from a variable
 ├── policy names re-derived by TYPE and by name fragment, not read from variables
 ├── scalable target: bounds and all three suspension switches unchanged
 ├── three policies: names, types, target value, cooldowns, adjustment type, step count
 ├── two scheduled actions: names, schedules, and both bounds each
 └── the custom alarm: threshold, operator, evaluations, missing-data treatment, one action
```

---

### Step 15 - Close the loop: from one request to one new task

Trace the whole path from metric to serving task and see how little of it this lab created.

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

Blocks 1 to 3 are this lab; blocks 4 to 6 are Labs 04 and 05, unchanged. Block 7 shows the revision, load balancer count and deployment count are exactly what Lab 05 left.

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

> Example output - your IDs will differ, and blocks 5 and 6 may be shorter on builds that do not start
> containers.

**Verify:** check every line has its evidence above.

```text
A student clicks Register.
  Requests per target rises past 1000, or the work queue passes 100.        (block 1)
  An alarm fires and invokes a policy.                                      (blocks 1, 2)
  The policy writes desiredCount, clamped to 2..10.                         (block 3)
  ECS starts a task from usms-enrolment:2.                                  (block 4)
  The task gets an ENI in usms-private-subnet-a or -b, no public address.   (block 5)
  usms-enrolment-sg admits tcp/80 from usms-alb-sg only.                    (Lab 05)
  The SERVICE registers its address in usms-enrolment-tg.                   (block 6)
  The load balancer health-checks it; after 60s of grace it takes traffic.  (blocks 4, 6)
  Nothing about the blueprint, the service or the load balancer changed.    (block 7)
```

This lab is responsible for three of the nine lines; write that in `notes/lab-06-notes.md` (Review Question 1). If block 6 is empty, your build does not start containers; say so. If block 7 does not show `:2` and `1` deployment, find out what this lab disturbed before Section 8 does.

---

### Step 16 - Write `configs/lab-06.env`

Record every name and ARN **by lookup**, so a populated value is evidence the resource exists.

```bash
cat > configs/lab-06.env << EOF
# Lab 06 - ECS service auto scaling outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, IDs, ARNs and numbers only. NO SECRETS. Safe to commit.
#
# Sourced alongside lab-01/02/03/04/05. The CloudWatch lab reads the alarm and the
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

grep -n 'export .*=$\|=None$' configs/lab-06.env || echo "all values populated"
```

!!! warning "Unquoted heredoc"
    `<< EOF` so every `$(...)` runs now. Quoted, the file would contain six API calls that re-run in every new terminal.

- `awk -F: '{print \$NF}'`: the dollar is escaped so it reaches `awk` instead of being expanded by the shell.
- `| grep -E '^arn:' || echo not-created` records `not-created` rather than `None` when a policy is unsupported, so the empty-value check does not flag a recorded limitation.
- `USMS_SCALE_MIN` and `USMS_SCALE_MAX` are read back, so a floor left at 6 shows up here.

**Verify**

```bash
source configs/lab-06.env

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

grep -c '^export' configs/lab-06.env

echo "-- the resource id must match what the API says, right now --"
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[0].ResourceId' --output text
```

`all values populated`, twelve non-empty lines, **22** exports, `bounds` `2 .. 10`, and `resource id` identical to the last line. `requests policy arn` may read `not-created` (Step 9's limitation); anything else that is not an `arn:aws:autoscaling:` ARN means a step did not take.

---

### Step 17 - Commit, and repair two stale strings

Look first, stage explicitly, then commit. Also fix the cleanup-order hint in Labs 04 and 05's cleanup scripts, which names a file this lab does not create.

**Command - part 1, repair the two hint strings**

```bash
grep -n 'lab-04-cleanup.sh' scripts/cleanup/lab-04-cleanup.sh scripts/cleanup/lab-05-cleanup.sh \
  || echo "nothing to repair - your copies already say lab-06-cleanup.sh"
```

Both scripts only **print** `lab-04-cleanup.sh`; nothing is broken, but the instruction is wrong. If the `grep` found lines, fix them:

```bash
for f in scripts/cleanup/lab-04-cleanup.sh scripts/cleanup/lab-05-cleanup.sh; do
  cp "$f" "$f.bak-$(date +%Y%m%d%H%M%S)"
  python3 - "$f" << 'PY'
import sys
p = sys.argv[1]
s = open(p).read()
n = s.count('lab-04-cleanup.sh')
s = s.replace('lab-04-cleanup.sh', 'lab-06-cleanup.sh')
open(p, 'w').write(s)
print(f"{p}: {n} occurrence(s) updated")
PY
  bash -n "$f" && echo "  $f still parses"
done

grep -n 'lab-06-cleanup.sh' scripts/cleanup/lab-04-cleanup.sh scripts/cleanup/lab-05-cleanup.sh
```

`python3` instead of `sed -i` (GNU and BSD disagree). Each file is backed up and re-checked with `bash -n`. Delete the backups once satisfied.

**Command - part 2, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-06-scaling-proof.txt
git ls-files outputs/
```

- No path under `outputs/`, no root `.env` and no `.bak-*` file in `git status --short`.
- `configs/lab-06.env` **does** appear; it holds no secrets.
- `git check-ignore -v` names the file, rule and line. Silence means it is not ignored: fix `.gitignore` first.
- `git ls-files outputs/` lists only `outputs/.gitkeep`.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-06-scaling-proof.txt
outputs/.gitkeep
```

> Example output - your line number may differ.

The rule must be `outputs/*` with `!outputs/.gitkeep`, never `outputs/` with `!outputs/.gitkeep`: Git cannot re-include a file under an excluded directory.

**Command - part 3, commit**

```bash
git add labs/lab-06-ecs-autoscaling/ \
        configs/lab-06.env \
        templates/lab-06-target-tracking-cpu.json \
        templates/lab-06-target-tracking-requests.json \
        templates/lab-06-step-scaling-out.json \
        templates/lab-06-suspended-state.json \
        scripts/utilities/verify-lab-06.sh \
        scripts/cleanup/lab-06-cleanup.sh \
        scripts/cleanup/lab-04-cleanup.sh \
        scripts/cleanup/lab-05-cleanup.sh

git status --short

git commit -m "Lab 06: auto scaling for usms-enrolment-svc - scalable target, two target tracking policies, a step policy with its alarm, and two scheduled actions

Also corrects the cleanup-order hint in the Lab 04 and 05 cleanup scripts, which
named lab-04-cleanup.sh; this lab ships lab-06-cleanup.sh."

git log --oneline -7
```

Explicit paths, never `git add -A`. The body explains why two Lab 04 and 05 files are in a Lab 06 commit. The two `scripts/` paths exist only after Section 8; if you commit first, drop them and commit them later.

**Expected result**

```text
[main 7d29a51] Lab 06: auto scaling for usms-enrolment-svc - scalable target, two target tracking policies, a step policy with its alarm, and two scheduled actions
 10 files changed, 291 insertions(+), 2 deletions(-)
```

> Example output - your hash and counts will differ. The two deletions are the two hint strings.

**Checkpoint 8**

```text
Lab 06 recorded
 ├── configs/lab-06.env       committed, 22 exports, fully populated
 ├── templates/               two target tracking configs, one step config, one suspended state
 ├── scripts/                 verify-lab-06.sh and lab-06-cleanup.sh
 ├── scripts/cleanup/lab-04,lab-05  hint strings corrected, backed up, and still parsing
 ├── outputs/                 nothing staged; check-ignore names the rule that protected you
 └── git log shows Lab 01, 02, 03, 04, 05 and 06 commits
```

---

## 8. Verification

The checks that matter most go beyond existence: no suspension switch left `true`, exactly one scalable target at the expected resource ID, the alarm invoking the step policy, an open-ended top step, `desiredCount` inside the bounds and at the baseline, and no document with an unexpanded variable. `MinCapacity is 2` asserts Lab 04's decision, not a value this lab set. The environment block comes first, as always.

### 8.1 Build `scripts/utilities/verify-lab-06.sh`

{% raw %}```bash
cat > scripts/utilities/verify-lab-06.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 06 artefact exists and is configured correctly.
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
source "$REPO_ROOT/configs/lab-04.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-05.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-06.env" 2>/dev/null || true

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

echo "== Lab 02 to 05 dependencies =="
check "usms-private-subnet-a exists" "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_A"
check "usms-private-subnet-b exists" "aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_B"
check "cluster $USMS_ECS_CLUSTER is ACTIVE" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "service $USMS_ENROLMENT_SERVICE is ACTIVE" "test \"\$(svcq status)\" = ACTIVE"
check "service still has exactly ONE loadBalancers entry" \
  "test \"\$(svcq 'length(loadBalancers)')\" = 1"
check "target group $USMS_TG_NAME still has target type ip" \
  "test \"\$(aws elbv2 describe-target-groups --names $USMS_TG_NAME --query 'TargetGroups[0].TargetType' --output text)\" = ip"

echo "== Lab 06 scalable target =="
check "exactly ONE scalable target in the ecs namespace" \
  "test \"\$(aws application-autoscaling describe-scalable-targets --service-namespace ecs --query 'length(ScalableTargets)' --output text)\" = 1"
check "the resource ID is $EXPECTED_RID" "test \"\$(tgt ResourceId)\" = \"$EXPECTED_RID\""
check "the scalable dimension is ecs:service:DesiredCount" \
  "test \"\$(tgt ScalableDimension)\" = ecs:service:DesiredCount"
check "MinCapacity is the Lab 04 baseline of $USMS_ECS_DESIRED_BASELINE" \
  "test \"\$(tgt MinCapacity)\" = $USMS_ECS_DESIRED_BASELINE"
check "MaxCapacity is 10" "test \"\$(tgt MaxCapacity)\" = 10"
check "NO suspension switch was left true" \
  "test \"\$(tgt 'SuspendedState.*' | grep -ci true)\" = 0"

echo "== Lab 06 scaling policies =="
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

echo "== Lab 06 alarms =="
check "custom alarm $USMS_ALARM_QUEUE_HIGH exists" "alm AlarmName | grep -qx $USMS_ALARM_QUEUE_HIGH"
check "it watches $USMS_METRIC_NAMESPACE $USMS_METRIC_NAME" \
  "test \"\$(alm Namespace)\" = '$USMS_METRIC_NAMESPACE' && test \"\$(alm MetricName)\" = '$USMS_METRIC_NAME'"
check "it INVOKES the step policy (the link you made yourself)" \
  "alm 'AlarmActions[]' | grep -q 'policyName/$USMS_POLICY_STEP_OUT'"
check "target tracking created 2+ managed alarms for you" \
  "test \"\$(aws cloudwatch describe-alarms --alarm-name-prefix 'TargetTracking-$RID' --query 'length(MetricAlarms)' --output text)\" -ge 2"

echo "== Lab 06 scheduled actions =="
check "morning action $USMS_SCHEDULED_OUT exists" \
  "sch $USMS_SCHEDULED_OUT ScheduledActionName | grep -qx $USMS_SCHEDULED_OUT"
check "evening action $USMS_SCHEDULED_IN exists" \
  "sch $USMS_SCHEDULED_IN ScheduledActionName | grep -qx $USMS_SCHEDULED_IN"
check "the morning action raises the floor ABOVE the evening action's" \
  "test \"\$(sch $USMS_SCHEDULED_OUT 'ScalableTargetAction.MinCapacity')\" -gt \"\$(sch $USMS_SCHEDULED_IN 'ScalableTargetAction.MinCapacity')\""

echo "== Lab 06 service state =="
check "desiredCount is INSIDE the scalable target's bounds" \
  "test \"\$(svcq desiredCount)\" -ge \"\$(tgt MinCapacity)\" && test \"\$(svcq desiredCount)\" -le \"\$(tgt MaxCapacity)\""
check "desiredCount is back at the baseline of $USMS_ECS_DESIRED_BASELINE" \
  "test \"\$(svcq desiredCount)\" = $USMS_ECS_DESIRED_BASELINE"
check "exactly ONE deployment (nothing stuck mid-roll)" \
  "test \"\$(svcq 'length(deployments)')\" = 1"

echo "== Lab 06 custom metric =="
check "the $USMS_METRIC_NAMESPACE namespace has at least one metric" \
  "test \"\$(aws cloudwatch list-metrics --namespace '$USMS_METRIC_NAMESPACE' --query 'length(Metrics)' --output text)\" -ge 1"

echo "== Files and Git hygiene =="
check "configs/lab-06.env exists" "test -f configs/lab-06.env"
check "configs/lab-06.env has no empty values and no None" \
  "! grep -qE 'export [A-Z_]+=\$|=None\$' configs/lab-06.env"
check "target tracking (cpu) document is valid JSON" \
  "python3 -m json.tool templates/lab-06-target-tracking-cpu.json"
check "target tracking (requests) document is valid JSON, or absent" \
  "! test -f templates/lab-06-target-tracking-requests.json || python3 -m json.tool templates/lab-06-target-tracking-requests.json"
check "step scaling document is valid JSON" \
  "python3 -m json.tool templates/lab-06-step-scaling-out.json"
check "suspended-state document is valid JSON and does NOT suspend scale-out" \
  "python3 -c \"import json,sys;d=json.load(open('templates/lab-06-suspended-state.json'));sys.exit(0 if d.get('DynamicScalingOutSuspended') is False else 1)\""
check "no Lab 06 document contains an unexpanded variable" \
  "! grep -l '[\$]' templates/lab-06-*.json"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"

if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

A failure under "== Environment ==" is the real problem, and most failures below it are
a consequence. Fix that block first:
  ./scripts/utilities/floci-storage-check.sh

A failure under "== Lab 02 to 05 dependencies ==" means an earlier lab's resource is
gone or has been changed. Run verify-lab-04.sh and verify-lab-05.sh before re-reading
anything here. Remember that verify-lab-04.sh is EXPECTED to report exactly one
failure, on the usms-app-sg source check, unless you did Lab 05's Exercise 2.

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

chmod +x scripts/utilities/verify-lab-06.sh
bash -n scripts/utilities/verify-lab-06.sh && echo "syntax OK"
./scripts/utilities/verify-lab-06.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Lab 02 to 05 dependencies ==
  ok   usms-private-subnet-a exists
  ...
== Lab 06 scalable target ==
  ok   exactly ONE scalable target in the ecs namespace
  ok   the resource ID is service/usms-ecs-cluster/usms-enrolment-svc
  ok   MinCapacity is the Lab 04 baseline of 2
  ok   NO suspension switch was left true
== Lab 06 scaling policies ==
  ok   its target value is 50
  ok   scale-out cooldown 60 and scale-in cooldown 300 (deliberately asymmetric)
  ok   the step policy has 2+ adjustments and an OPEN-ENDED top interval
== Lab 06 alarms ==
  ok   it INVOKES the step policy (the link you made yourself)
  ok   target tracking created 2+ managed alarms for you
  ...
== Files and Git hygiene ==
  ok   no Lab 06 document contains an unexpanded variable
  ok   no secret is tracked by git

PASS=42  FAIL=0
```

> Example output - the middle is abbreviated; you will see all 42.

**The expected count is `PASS=42  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `target tracking created 2+ managed alarms for you` | Some builds do not create the managed alarms. Confirm with `describe-scaling-policies --query 'ScalingPolicies[].Alarms'` and record it; nothing in this lab depends on them existing, only on your understanding of them |
| `it INVOKES the step policy` | Some builds accept `--alarm-actions` and do not store it. Confirm with `describe-alarms --output json` and record it. On real AWS this failing would mean the policy can never fire |
| `the $USMS_METRIC_NAMESPACE namespace has at least one metric` | Some builds accept `put-metric-data` and do not index the metric for `list-metrics`. Confirm with `get-metric-statistics` and record which |
| `the morning action raises the floor ABOVE the evening action's` | Only if `describe-scheduled-actions` is unimplemented, in which case both sides of the comparison are empty and the test aborts. Check whether Step 11's actions exist at all |
| `exactly ONE deployment` | Some builds report zero deployments rather than one. Check with `--query 'services[0].deployments'` and record which it is |
| `NO suspension switch was left true` | **Not benign.** Step 13 part 3 did not run, or ran with the wrong document. Fix it - this is the check that exists to catch a real production hazard |
| `desiredCount is back at the baseline` | **Not benign.** An experiment was not undone. Step 12 part 6 has the correct order: metric down first, then the count |
| `MinCapacity is the Lab 04 baseline of 2` | **Not benign.** Either Step 11's "Your turn" left the floor raised, or `USMS_ECS_DESIRED_BASELINE` in `configs/lab-04.env` is not 2 and you have a disagreement between two labs to resolve |

Everything else failing is a real problem with your work.

### 8.2 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** both scheduled actions, all three scaling policies (and, as a side effect,
    the four CloudWatch alarms target tracking created), the custom alarm `usms-enrolment-queue-high`,
    and the scalable target's registration.

    **What depends on it:** nothing later in the course *requires* the scaling to exist - but the
    CloudWatch lab reads this lab's custom alarm and its scaling activities, and the CloudFormation lab
    re-declares every object in `configs/lab-06.env` as a template and compares it with what you built
    by hand. Deleting the scaling early means both of those labs lose their subject.

    **Reversible?** Yes, more easily than anything else in this course. Every object is created by one
    idempotent command from a document in `templates/`, and `configs/lab-06.env` holds every name. You
    would repeat Steps 5 to 11, which is about fifteen minutes.

    **Effect on later labs:** the CloudWatch and CloudFormation labs lose material. Nothing breaks.

    Run it only at the end of the course, and run the cleanup scripts in this order:

    ```text
    scripts/cleanup/lab-06-cleanup.sh   (this one - scaling configuration ONLY)
    scripts/cleanup/lab-05-cleanup.sh   (load balancer, and the service)
    scripts/cleanup/lab-04-cleanup.sh   (cluster, task definitions, roles, log group)
    scripts/cleanup/lab-03-cleanup.sh
    scripts/cleanup/lab-02-cleanup.sh
    ```

    **This one goes first**, and both of the next two enforce it: each of them refuses to run while a
    scalable target still exists for `service/usms-ecs-cluster/usms-enrolment-svc`, because deleting the
    service out from under a scalable target leaves an orphaned registration that is easy to forget and
    impossible to explain later. Those two scripts print the name `lab-06-cleanup.sh` only if you did
    Step 17 part 1; if you skipped it they still say `lab-04-cleanup.sh`, which is the file that does not
    exist.

    It requires you to type `DELETE USMS SCALING` in full before it does anything.

````bash
cat > scripts/cleanup/lab-06-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes Lab 06, dependencies first.
# Order: scheduled actions -> scaling policies -> the custom alarm -> deregister the target.
# Run FIRST of the 04 cleanups: lab-05-cleanup.sh and lab-04-cleanup.sh both REFUSE
# while a scalable target still exists for this service.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-04.env"
source "$REPO_ROOT/configs/lab-06.env"

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

  Run FIRST of the 04 cleanups, then lab-05, then lab-04.
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
     Untouched. lab-05-cleanup.sh and lab-04-cleanup.sh own those, in that
     order, and they will now agree to run.
KEPT

echo
echo "Lab 06 teardown complete. scripts/cleanup/lab-05-cleanup.sh may now run."
EOF

chmod +x scripts/cleanup/lab-06-cleanup.sh
bash -n scripts/cleanup/lab-06-cleanup.sh && echo "syntax OK - do NOT run it"
````

**What to look for:** `syntax OK - do NOT run it`. `bash -n` parses without executing.

The order: scheduled actions first (a calendar entry outliving its target fails silently); then the policies one at a time (target tracking takes its managed alarms with it); then the alarm you wrote (nothing deletes it for you); deregister the target **last** (it cascades to every policy and action, which would hide what was there). The service-linked role is account-wide and kept; CloudWatch has no `delete-metric`.

---

## 9. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, six env files sourced, `verify-lab-02/03/05` all `FAIL=0` and `verify-lab-04` at `FAIL=0` or its one documented failure, the service at desired 2 with one deployment, and your support path (A, B or C) recorded in `notes/lab-06-notes.md` |
| 2 | Step 6 | Exactly one scalable target, at `service/usms-ecs-cluster/usms-enrolment-svc` with dimension `ecs:service:DesiredCount`, min 2 and max 10, its `RoleARN` filled in by AWS, all three suspension switches `false`, and no policies attached |
| 3 | Step 9 | Two target tracking policies on that target - CPU at 50.0 and requests at 1000.0 - each reporting two managed alarms, and the `ResourceLabel` validated at six segments beginning `app` with `targetgroup` fourth |
| 4 | Step 11 | A `StepScaling` policy with two adjustments and an open-ended top interval; `usms-enrolment-queue-high` watching `USMS/Enrolment` and naming the step policy in `AlarmActions`; two scheduled actions with a floor of 4 in the morning and 2 in the evening |
| 5 | Step 12 | Either a scaling activity whose `Cause` names both the alarm and the policy, **or** `outputs/lab-06-scaling-proof.txt` recording the six-block chain and the reason the loop did not run; and the service back at desired 2 with the metric pushed down first |
| 6 | Step 13 | Suspension exercised with `register-scalable-target --suspended-state`, all three policies untouched while suspended, and `SuspendedState.*` piped to `grep -ci true` returning `0` |
| 7 | Step 14 | `PERSISTENCE PROVEN` after a Floci stop and start, with the resource ID and both policy names **re-derived from the API** and seven facts compared across four services |
| 8 | Step 17 | `configs/lab-06.env` populated with 22 exports and committed; the two stale hint strings repaired, backed up and still parsing; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, scheduled actions are unsupported and alarms do not scale the ECS service. Diagnose first, then use the alternative in [Known Issues - Lab 06](known-issues.md#lab-06-auto-scaling). It states what the alternative does and does not prove.

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
    arithmetic in the target tracking info box before Step 7 divides by a number that never improves, so the computed
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

    **The cron expression has five fields.** Application Auto Scaling wants **six** - the last is the
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
        recovered by re-registering - you would repeat Steps 7 to 11 from `templates/`.

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

    Then re-run `./scripts/utilities/verify-lab-06.sh` and confirm the count is back to one.

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

??? danger "`verify-lab-06.sh` fails on `NO suspension switch was left true`"
    Step 13 part 3 did not run, or ran with a document that had the wrong values. This is the check that
    exists to catch a genuine production hazard, so read the state rather than just clearing it:

    ```bash
    aws application-autoscaling describe-scalable-targets --service-namespace ecs \
      --resource-ids "$RID" --query 'ScalableTargets[0].SuspendedState' --output json
    ```

    Then clear it with the shorthand form from Step 13 part 3, and re-run the script.

??? danger "`verify-lab-04.sh` or `verify-lab-05.sh` fails after this lab"
    This lab modifies nothing either of them checks, with one exception: if `desiredCount` is not back at
    2, `verify-lab-04.sh`'s baseline check and `verify-lab-05.sh`'s deployment check can both fail.

    Compare against the run you captured in Step 2:

    ```bash
    ./scripts/utilities/verify-lab-05.sh > outputs/lab-06-post-verify-05.txt
    diff outputs/lab-06-pre-verify-05.txt outputs/lab-06-post-verify-05.txt \
      && echo "Lab 05 is exactly as this lab found it"
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
    than re-running Step 3's probe - look for the application auto scaling and CloudWatch entries.

??? danger "Everything is gone after a restart"
    Storage mode, as always.

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    If it reports `FLOCI_STORAGE_MODE=memory`, a stray `floci start` has replaced the Compose container.
    The work is not recoverable - restore from the snapshot you took at the end of Lab 05, and this time
    confirm the storage check before building anything.

---

## 11. Floci vs Real AWS

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
| `AWS/ApplicationELB` `RequestCountPerTarget` | Published every minute | Not published - Lab 05 said so | Conceptual / Real AWS |
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
| `healthCheckGracePeriodSeconds` delaying when new capacity counts | Enforced | Stored - Lab 05 said so | Floci Limitation |
| Cost - per task-second, plus CloudWatch per alarm and per custom metric | Real, and an idle alarm is not free | Free | Conceptual / Real AWS |
| Service quotas: scalable targets, policies per target, step adjustments per policy | Enforced | Not enforced | Conceptual / Real AWS |
| Subnet address exhaustion capping a scale-out | Real, and it presents as `Unfulfilled` | Not enforced | Conceptual / Real AWS |
| Predictive scaling | **Not available for ECS in any account.** EC2 Auto Scaling only | Not available | Conceptual / Real AWS |
| `CloudTrail` recording which role changed your capacity | Full, with the service-linked role as the invoker | Not available | Conceptual / Real AWS |

Observable here: the role, target, policies, managed alarms, `ResourceLabel`, step table, custom alarm, scheduled actions, suspension and persistence. Conceptual unless you reached path A: alarm evaluation, scaling activities, the capacity calculation, cooldowns, scheduled firing, and Fargate start latency. Say in your report which list each item ended up in for you.

**Where Floci is nicer than reality (traps on real AWS):** capacity appears instantly or never (real Fargate tasks take 20 to 60 seconds plus the grace period); nothing is ever `Unfulfilled` (real scale-outs hit subnet address exhaustion and quotas); alarms never flap; nothing costs money (CloudWatch charges per alarm and per custom metric); suspension has no effect, so its hazard is invisible; and `set-alarm-state` is a real privilege on a production account.

!!! info "Three things called auto scaling"
    **ECS service auto scaling** (this lab) changes the task count via Application Auto Scaling. **ECS cluster auto scaling** changes container instances behind a capacity provider and is meaningless on Fargate. **EC2 Auto Scaling** manages Auto Scaling groups from launch templates, which is where Lab 3's golden AMI belongs, and is the only one with predictive scaling. See [Application Auto Scaling and EC2 Auto Scaling](../unit7/topic1.md#application-auto-scaling-and-ec2-auto-scaling) and [the two scaling layers](../unit2/topic3.md#the-two-scaling-layers-revisited).

```text
aws autoscaling                 EC2 Auto Scaling - groups, launch templates, instance refresh
aws application-autoscaling     THIS SERVICE - scalable targets in nine namespaces
arn:aws:autoscaling:...         the ARN namespace used by BOTH of them
```

No step in this lab is load testing, so every number in it (target 50, 1000 requests, threshold 100, ceiling 10) is provisional: on a real system you load-test first to find what one task can serve. The mechanism is correct and the numbers are provisional.

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-06-ecs-autoscaling/exercises.md`; screenshots go in `screenshots/`.

### Exercise 1 - Basic: a memory policy, and a scale-out-only policy

**Requirements**

1. Create `usms-enrolment-memory-target-tracking` on the same target: `ECSServiceAverageMemoryUtilization`, target 70, scale-out cooldown 60, scale-in cooldown 600.
2. Set `DisableScaleIn` to `true`.
3. Confirm the target's managed alarm count went from four to five, not six.
4. Write the configuration to `templates/lab-06-target-tracking-memory.json`, using the right heredoc quoting for a file with no variables.

**Constraints**

- Every identifier captured with `$(...)` and `--query`.
- Do **not** record the policy in `configs/lab-06.env`; Exercise 4 removes it.
- Do **not** change the scalable target's bounds.
- Section 8's script must still report `FAIL=0`; predict whether it will, and why.

**Expected outcome:** three target tracking policies and one step policy on one target; the new policy shows `DisableScaleIn` true; **five** managed alarms.

**Then answer, in one sentence each:**

- Why five and not six? Which alarm was not created, and what does its absence mean?
- Memory target 70 against CPU target 50: which scales out first, and what would you need to know to answer properly?
- Does a scale-out-only policy change the *scale-in* behaviour of the other two? Use Step 9's rule.

**Hints:** Step 7 has every command. For the alarm count, think about what the low alarm is for.

### Exercise 2 - Intermediate: the scale-in half of step scaling, and a fight to avoid

**Requirements**

1. Create `usms-enrolment-queue-step-in`: `StepScaling`, `ChangeInCapacity`, `Average`, cooldown 300, with a mild and a stronger adjustment that **remove** capacity as the metric falls further below a threshold.
2. Create `usms-enrolment-queue-low` on the same custom metric, firing when the average is **below** 20 for 3 periods of 60 seconds, whose only action is that policy.
3. Write the step configuration to `templates/lab-06-step-scaling-in.json`, and note in `exercises.md` the sign of every bound and adjustment, and why.
4. Publish datapoints taking the metric to 5, force the low alarm to `ALARM` with `set-alarm-state`, and record what happened (including "nothing").
5. Delete both objects in the correct order, each preceded by the four-line danger admonition.

**Constraints**

- Scale-in bounds are **non-positive** and adjustments **negative**. Say what `MetricIntervalUpperBound: 0` with `ScalingAdjustment: -1` means.
- The cooldown must be longer than the scale-out policy's; say why.
- The floor of 2 makes one adjustment unreachable; identify it.
- Section 8's script must report `FAIL=0` at the end, so point 5 is not optional.

**Expected outcome:** a matched pair of step policies observed and cleanly removed, with signs written out and the unreachable step identified.

**Then answer, in a short paragraph:** someone adds a step scaling policy on **CPU** with their own alarm at 60 per cent, alongside the CPU target tracking policy. Explain what goes wrong, using how target tracking computes capacity, and which policy you would keep (not "whichever fires first").

**Hints:** `aws application-autoscaling put-scaling-policy help` shows `StepAdjustments`. A metric of 5 against a threshold of 20 is a breach of **-15**. For the unreachable step, compare `2 + (your larger negative adjustment)` with `MinCapacity`.

### Exercise 3 - Problem solving: a scaling report tool

**Requirements:** write `scripts/utilities/usms-scaling-report.sh`. With no arguments it discovers every scalable target in the `ecs` namespace whose resource ID names a cluster beginning `usms-`, and prints its decision table with a computed verdict:

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

The verdict must be **computed** from the target's own fields:

| Verdict | When |
| --- | --- |
| `PINNED` | `MinCapacity` equals `MaxCapacity` - the service cannot scale at all |
| `FROZEN` | Any suspension switch is `true` |
| `AT-CEILING` | `desiredCount` equals `MaxCapacity` |
| `AT-FLOOR` | `desiredCount` equals `MinCapacity` and more than one policy exists |
| `ELASTIC` | None of the above |

Evaluate the rules top to bottom and explain in a comment why that order is right, in particular why `FROZEN` outranks `AT-CEILING`.

**Constraints**

- Runs correctly from any directory; resolve `configs/` from `${BASH_SOURCE[0]}`.
- No arguments; no hard-coded resource ID, policy, alarm or cluster name beyond the `usms-` prefix.
- Handles a target with no policies or no scheduled actions, a target tracking policy with an empty `Alarms` list, and an unimplemented `describe-scaling-activities`, without crashing or printing blank rows.
- Step adjustments summarised as a signed list (`+1 / +3`), derived from the configuration.
- `set -uo pipefail`; decide about `-e` and justify it in a comment.
- Also writes `outputs/lab-06-scaling-report.json`.

**Expected outcome:** identical output from `~` and from `~/aws-floci-course/labs/lab-06-ecs-autoscaling/`; correct before and after Exercise 1, while suspended, and with min and max both set to 3.

**Hints:** four levels of discovery (targets, policies, alarms, scheduled actions) plus one ECS call. Process JSON in `python3` after the first `describe-scalable-targets`. Batch alarm lookups: `describe-alarms --alarm-names` takes several names.

### Exercise 4 - Challenge: the enrolment-week capacity plan

**Requirements:** the USMS project lead writes:

> Enrolment opens on the 14th and runs for three weeks. Last year the portal fell over in the first
> twenty minutes and we spent the afternoon on the phone to the registrar. Analytics says we had about
> forty times normal traffic in the first hour of each of the three days when a new cohort became
> eligible, and roughly double normal traffic for the rest of the three weeks.
>
> I am told we now have auto scaling, so presumably this is solved. Tell me whether it is, what it will
> cost, and what you need from me.
>
> Also, somebody has left some practice policies on the service from an exercise. Tidy them up.

Write an analysis in `labs/lab-06-ecs-autoscaling/exercises.md` covering:

- **Whether it is solved, in exactly three sentences:** what reactive scaling does well, what it does badly, and the first twenty minutes.
- **Why forty times traffic is not a scaling problem:** from this lab's numbers, how long a reactive policy takes from 2 tasks to 10 (alarm evaluations, cooldowns, task starts, grace periods), with the arithmetic; then what the ceiling of 10 implies at Step 9's target value.
- **The ceiling, checked against Lab 02:** usable addresses in `10.0.3.0/24` and `10.0.4.0/24` after AWS's reservation and existing occupants; the largest supportable ceiling, with a citation.
- **A capacity plan:** the scheduled actions for the three cohort days and the three-week window (exact `cron` and time zone), their bounds, target value changes, and what you would do about the ceiling. Say which changes are reversible in one command.
- **A monthly cost estimate, with a citation:** additional Fargate cost at current prices for the task size in `configs/lab-04.env`, plus CloudWatch alarm and custom metric cost. State every assumption.
- **What you need from the project lead:** three specific things, one of them a measurement nobody has taken (Section 11 says which).
- **The tidy-up:** exact commands in dependency order, each with the four-line danger admonition, for `usms-enrolment-memory-target-tracking` (Exercise 1) and anything left from Exercise 2.

Then execute only the deletions and confirm `./scripts/utilities/verify-lab-06.sh` reports `FAIL=0`.

**Constraints**

- Do not delete anything in Section 15's KEEP column.
- Every number has a source or a derivation.
- The address arithmetic states AWS's per-subnet reservation and cites it.
- Distinguish **capacity** from **throughput**: say how many requests per second 10 tasks at 1000 requests per target per minute is.

**Expected outcome:** an analysis a project lead could act on and a finance team could check, the practice policies gone, and verification passing.

**Hints:** Section 4 explains the first twenty minutes. Step 8's "Your turn" built one delay term and Lab 04 Exercise 5 measured another. Search the VPC documentation for subnet sizing.

### Exercise 5 - Integration: the hand-off to Lab 10

**Requirements:** Lab 10 creates `usms-student-data`, the bucket Lab 01's `USMSStudentDataReadWrite` has named since day one and Lab 04 attached to `usms-ecs-task-role`. Its first `put-object` needs a real file.

1. Write `scripts/utilities/usms-scaling-history.sh`, exporting the service's complete scaling configuration and history as one JSON document to `outputs/lab-06-scaling-history.json`: the target with bounds and suspension state, every policy with its configuration, every scheduled action, every alarm involved with its state, and every scaling activity including not-scaled ones. Every identifier discovered.
2. Add a top-level `"generated"` UTC timestamp (from `python3`) and a `"resourceId"` derived from the service ARN. Validate with `python3 -m json.tool` and record the size in bytes.
3. **Measure scale-out latency:** record a UTC timestamp, raise `MinCapacity` to 4 by re-registering, poll until `runningCount` equals `desiredCount`, record again, and write the elapsed seconds, both timestamps and both capacities to `outputs/lab-06-scale-latency.txt`. Put the floor back to 2. If tasks never start, cite AWS's Fargate start-up figure instead.
4. Append `USMS_SCALING_HISTORY_FILE` and `USMS_SCALE_LATENCY_SECONDS` to `configs/lab-06.env`, derived rather than typed. Re-run the empty-value check and state the new export count.
5. Write `outputs/lab-06-lab10-readiness.txt` with labelled lines: the history file's path and size; the latency; the task role ARN from `configs/lab-04.env`; the bucket ARN that role's policy names, **read from the policy document**; and one sentence naming which Lab 01 permissions it grants on that bucket.
6. Run `aws s3api head-bucket --bucket usms-student-data` and capture its output **and** exit code into the same file. It will fail. Add one sentence on what changes after Lab 10's Step 1, for the command and for `usms-ecs-task-role`.

**Constraints**

- `usms-scaling-history.sh` works from any directory with no hard-coded resource ID, policy or alarm name.
- Point 5's bucket ARN is read with `get-policy-version`, not typed.
- Capture the `head-bucket` failure with its exit code (`|| true`, then record `$?`); do not let `set -e` abort.
- Timestamps from `python3`, not `date -d` or `date -v`.
- Point 3 restores `MinCapacity` to 2; Section 8 asserts it.
- No script may contain, read or reference an access key.

**Expected outcome:** a committed export script later labs can call unchanged, a real JSON artefact for Lab 10, a measured or cited latency figure, and a readiness file predicting what `create-bucket` will make true.

**Lab 10 uses this:** its first object, and its key point about two IAM policies becoming real at the same instant.

**Hints:** Step 14 already derives every identifier; add `--output json` and a `python3` assembly step. Step 12 part 1 has the timestamp pattern; Step 6 the re-registration. Lab 04 Step 8's Verify block reads the policy with `get-policy` and `get-policy-version`; there are two `Resource` entries (bucket and objects): say which you recorded.

---

## 13. Lab Assessment Checklist

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` appears in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-06-notes.md`

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
      `loadBalancers` entry - this lab changed neither

**Evidence**

- [ ] Step 5's `describe-scalable-targets` output showing `RoleARN` filled in by AWS
- [ ] Step 8's two managed alarms, with their asymmetric evaluation periods
- [ ] Step 8's "Your turn" arithmetic, with all four terms written out
- [ ] Step 9's validated `ResourceLabel`, six segments, `app` first and `targetgroup` fourth
- [ ] Step 12's scaling activity with its `Cause` string, **or** `outputs/lab-06-scaling-proof.txt` and
      the reason the loop did not run
- [ ] Step 13's `SuspendedState` output, both while suspended and after resuming
- [ ] Step 14's `PERSISTENCE PROVEN` line
- [ ] Step 15's seven blocks, and the nine-line chain written out in your notes
- [ ] `outputs/lab-06-pre-restart.txt` and `outputs/lab-06-post-restart.txt` present
- [ ] Screenshots in `screenshots/` for Checkpoints 3, 5 and 7

**Hygiene and written work**

- [ ] `configs/lab-06.env` exists, is committed, has 22 exports (24 after Exercise 5) and no empty values
      or `None`
- [ ] `scripts/utilities/verify-lab-06.sh` exists and reports `PASS=42  FAIL=0`, or its documented benign
      failures, each explained
- [ ] `scripts/cleanup/lab-06-cleanup.sh` exists, passes `bash -n`, and has **not** been run
- [ ] The two hint strings in `lab-04-cleanup.sh` and `lab-05-cleanup.sh` are repaired, and both scripts
      still pass `bash -n`
- [ ] `verify-lab-05.sh` produces the same output as the run captured in Step 2 - an empty `diff`
- [ ] `git status --short` shows nothing under `outputs/` and no `.bak-*` file
- [ ] `git check-ignore -v` demonstrated on one `outputs/` file from this lab
- [ ] `notes/lab-06-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-06-ecs-autoscaling/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding - answer these out loud before you submit**

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

## 14. Review Questions

Answer in prose in `notes/lab-06-notes.md`.

1. Step 15 traced nine lines from a student clicking Register to a task serving the request. Write all nine, name the three this lab owns, and explain why the other six needed no change. Finish with your one-sentence answer to "what does auto scaling change about my application?"
2. A colleague passes the service's full ARN to `--resource-id` and gets a validation error. Explain what the resource ID is, why Application Auto Scaling uses a constructed string, and how it differs between the `ecs`, `dynamodb` and `lambda` namespaces. Name the other constructed identifiers this architecture uses and the ARN each comes from.
3. Registering a target with minimum 2 against a service running one task raises the count to 2 immediately. Which object made that change, and how does it differ from a policy making it? Describe a 3 a.m. incident where someone uses this deliberately, and the evidence left for the person who takes over at 8.
4. Target tracking created two alarms; you created a third for the step policy. Compare them: who owns each, what happens when the policy changes or the alarm is deleted, and what one can do that the other cannot. Then argue for `breaching` as the queue alarm's `TreatMissingData`, and say what would go wrong if you were right.
5. Section 4 says reactive scaling can never absorb the first minutes of a spike. Reconstruct the arithmetic, naming every delay and where it is configured, then explain the three consequences and which of this lab's configuration choices each justifies.
6. A CPU policy at 50 and a request policy at 1000 disagree. What happens in each direction, and why is the rule asymmetric? Why are two target tracking policies on the **same** metric a fault, and why is a step and a target tracking policy on one metric the same mistake?
7. Give the three reasons `ALBRequestCountPerTarget` beats CPU for the enrolment API, the workload class where CPU is better, and what would have to be true for `ALBRequestCountPerTarget` to scale this service **badly**, with the metric that would have warned you.

---

## 15. KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ════════════════════════╗    ╔═════════════ CLEAN UP ══════════════╗
║ the scalable target       min 2 max 10, suspension  ║    ║ usms-enrolment-memory-target-       ║
║                           switches all false        ║    ║   tracking                          ║
║ usms-enrolment-cpu-target-tracking                  ║    ║   - Exercise 1 practice;            ║
║ usms-enrolment-requests-target-tracking             ║    ║   removed in Exercise 4             ║
║ usms-enrolment-queue-step-out                       ║    ║                                     ║
║ usms-enrolment-queue-high  the CloudWatch lab       ║    ║ usms-enrolment-queue-step-in and    ║
║                            replaces set-alarm-state ║    ║ usms-enrolment-queue-low            ║
║ USMS/Enrolment metric      the CloudWatch lab       ║    ║   - Exercise 2 practice; its own    ║
║                            graphs it                ║    ║   point 5 removes them              ║
║ both scheduled actions     the CloudFormation lab   ║    ║                                     ║
║                            re-declares them         ║    ║ usms-enrolment-results-night        ║
║ the four managed alarms    AWS owns them; leave     ║    ║   - Step 11's Your turn; deleted    ║
║                            them alone entirely      ║    ║   there, WITH the floor put back    ║
║ AWSServiceRoleForApplicationAutoScaling_ECSService  ║    ║                                     ║
║ configs/lab-06.env        two later labs source it ║    ║ outputs/lab-06-pre/post-*.txt      ║
║ templates/lab-06-*.json   incl. the suspended      ║    ║   - evidence; keep until            ║
║                            state, as a runbook page ║    ║   submitted, then remove            ║
║ scripts/utilities/verify-lab-06.sh                 ║    ║                                     ║
║ outputs/lab-06-scaling-history.json  (Exercise 5)  ║    ║ scripts/cleanup/*.bak-*             ║
║   Lab 10's first put-object needs it                ║    ║   - Step 17's backups; remove       ║
║ everything from Labs 01, 02, 03, 04 and 05        ║    ║   once you are satisfied            ║
╚═════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted:

```bash
rm -f outputs/lab-06-pre-restart.txt  outputs/lab-06-post-restart.txt
rm -f outputs/lab-06-pre-scale.txt    outputs/lab-06-post-scale.txt
rm -f outputs/lab-06-pre-verify-05.txt outputs/lab-06-post-verify-05.txt
rm -f scripts/cleanup/*.bak-*
git status --short
./scripts/utilities/verify-lab-06.sh | tail -2
```

Keep `outputs/lab-06-scaling-proof.txt` and `outputs/lab-06-scaling-history.json` until Lab 10 has consumed the second one. Keep `templates/lab-06-suspended-state.json`: it is the runbook for suspending scale-in in an incident.

Do **not** run `scripts/cleanup/lab-06-cleanup.sh`, `lab-05-cleanup.sh`, `lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are for the end of the course, in the order given in Section 8.2.

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02 and Lab 04
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 10
  USMSStudentDataReadWrite ............. on TWO roles, naming a bucket that STILL does not exist
  AWSServiceRoleForApplicationAutoScaling_ECSService   <- NEW: AWS wrote this one

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
                 ^ the load balancer's two nodes
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                                                            -> usms-s3-endpoint
                 ^ where a task created by a scaling policy APPEARS, and where its
                   addresses will eventually run out - Exercise 4 works out when
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg, usms-private-nacl

Lab 03  COMPUTE - instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI -> EC2 Auto Scaling, which is Section 11's THIRD column and not this lab

Lab 04 COMPUTE - containers you operate
  usms-ecs-cluster                      Container Insights enabled -> the CPU metric exists
    usms-enrolment-svc                  desired 2, both private subnets, no public IP
      usms-enrolment:2                  awsvpc, FARGATE, 256/1024, container health check
        executionRoleArn                usms-ecs-exec-role
        taskRoleArn                     usms-ecs-task-role -> USMSStudentDataReadWrite
  /usms/ecs/enrolment                   retention 7 days

Lab 05 TRAFFIC - the front door
  usms-alb-sg / usms-enrolment-alb / listener HTTP:80 / rule 10 /alb-health
  usms-enrolment-tg                     target-type ip, GET / every 30s, matcher 200
    targets                             registered and deregistered BY the service
  usms-enrolment-svc                    loadBalancers[0], grace period 60
  usms-enrolment-sg                     in: tcp/80 from usms-alb-sg ONLY

Lab 06 SCALING - the control loop                          <-- you are here
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

Lab 10  Lambda
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for BOTH
                        roles at once, and whose first object is this lab's Exercise 5.
                        Lambda creates it inline; there is no separate storage lab.
  then DynamoDB · RDS · SNS/SQS · CloudWatch · CloudFormation
  the CloudWatch lab reads /usms/ecs/enrolment, USMS/Enrolment and this lab's alarms
  the CloudFormation lab re-declares all of Practical 2 and Practical 3 as one template
```

---

## 16. Preparation for the Next Lab

Lab 07 rebuilds the USMS application on Amazon EKS. It does not source `configs/lab-06.env`; the link is conceptual. Its Step 12 expresses the same three numbers (`minReplicas`/`maxReplicas`, target CPU, scale-up/scale-down windows) as a `HorizontalPodAutoscaler`, so keep this lab's CPU target tracking policy and its two managed alarms for that comparison.

Lab 10 (Lambda) creates `usms-student-data` and needs two things from this repository:

| From this lab | Lab 10 uses it for |
| --- | --- |
| `outputs/lab-06-scaling-history.json` (Exercise 5) | Its first `put-object` needs a real file with real content. This is one |
| `outputs/lab-06-lab10-readiness.txt` (Exercise 5) | The exact bucket ARN, read from Lab 01's policy document rather than typed, and the task role that carries it |

| From earlier labs | Lab 10 uses it for |
| --- | --- |
| Lab 01 `USMSStudentDataReadWrite` | The policy whose `Resource` names the bucket. Lab 10 creates the bucket the policy already describes, in that order, deliberately |
| Lab 01 `usms-ec2-app-role` | One of the two roles that starts working the instant the bucket exists |
| Lab 04 `usms-ecs-task-role` | The other one. **This is the sentence Lab 10 is built around** |
| Lab 02 `usms-s3-endpoint` | The gateway endpoint that has been on the private route table since Lab 2 and has had nothing to reach |
| Lab 04 `USMSECSTaskExecution` | Its `logs` statement is scoped to one log group; Lab 10's equivalent scoping decision is about a bucket, and the comparison is worth making |

- Four labs have prepared for one `create-bucket` call: Lab 01's policy, Lab 03's instance profile, Lab 04's task role and Lab 02's S3 endpoint all resolve at once, unmodified.

Before the next session:

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-05.sh | tail -2
./scripts/utilities/verify-lab-06.sh | tail -2
grep -c '^export' configs/lab-06.env
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
raised floor is a service that costs more than it should and disagrees with `configs/lab-04.env`, and the
CloudFormation lab will produce a template that bakes the wrong number in.

Take a snapshot so a mistake in Lab 07 or Lab 10 is recoverable:

```bash
floci snapshot save lab-06-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-06.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-06.tar.gz
```

---

## Appendix - New CLI and JMESPath patterns

Labs 1 to 05 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()` with `&`, `length()`, `contains()`, `starts_with()`, `@`, slices, flattening, literals, `--filters`, `--generate-cli-skeleton`, `--cli-input-json`, `--max-items` and waiters. This lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `SuspendedState.*` | An **object projection**: `*` after a dot yields every *value* of a hash, discarding the keys. Three booleans out of one field | Steps 13, 14, Section 8 |
| `SuspendedState.* \| grep -ci true` | One number that must be zero, instead of three fields you have to read. `-i` because `--output text` renders a JSON boolean as `True` with a capital letter | Steps 13, 17, Section 8 |
| `StepAdjustments[-1].MetricIntervalUpperBound` | A **negative index** - JMESPath counts from the end. An absent field reads as `None` under `--output text`, which is how you assert that the top step is open-ended | Section 8 |
| `ScalableTargets[?ResourceId=='$RID'].ScalableDimension \| [0]` | A raw string literal in single quotes, inside a double-quoted shell string so the variable expands, then a first-match take | Step 14 |
| `ScalingPolicies[?PolicyType=='StepScaling'].PolicyName \| [0]` | Finding an object by **what it is** rather than by what it was called. A better persistence check than a name lookup | Step 14 |
| `MetricAlarms[?contains(AlarmName, ` + backtick + `AlarmHigh` + backtick + `)]` | `contains()` with a backtick literal, to pick one of two managed alarms whose names contain a UUID | Step 15 |
| `--alarm-name-prefix "TargetTracking-$RID"` | A server-side prefix filter whose value you constructed. The managed alarm names are derivable, which is the whole point of Step 8 | Steps 8, 13, 15, Section 8 |
| `--include-not-scaled-activities` | Application Auto Scaling's best diagnostic: the decisions **not** to scale, with reasons, omitted by default | Section 10 |
| `--scalable-target-action MinCapacity=4,MaxCapacity=10` | A single nested structure in shorthand, on a flag that takes exactly one | Step 11 |
| `--suspended-state A=true,B=false,C=false` and `file://...` | The same structure two ways, and a reason to prefer the file for a setting whose hazard is being forgotten | Step 13 |
| `"${SVC_ARN##*:}"` | Strip the longest `*:` prefix - the last colon-separated field of an ARN. The resource ID, in one expansion | Steps 5, 14, Section 8 |
| `"${ALB_ARN#*:loadbalancer/}"` | Strip the **shortest** prefix matching a multi-character delimiter. Half of the `ResourceLabel` | Step 9 |
| `printf '%s' "$X" \| awk -F/ '{print NF}'` | Counting path segments, to validate a constructed identifier before using it | Steps 5, 9 |
| `awk -F: '{print \$NF}'` inside an **unquoted** heredoc | The one place in the course where a dollar sign must be escaped to survive an unquoted heredoc | Step 16 |
| `... --output text \| grep -E '^arn:' \|\| echo not-created` | Turning `None` into a meaningful token, so an empty-value check can tell "unsupported" from "you skipped a step" | Step 16 |
| `python3 -c "import datetime;print(...)"` for every timestamp | GNU `date` and BSD `date` disagree about every flag that matters | Steps 11, 12 |
| `python3 - "$f" << 'PY'` for an in-place edit | `sed -i` is not portable between GNU and BSD; a backed-up Python read-modify-write is | Step 17 |
| `cut -d. -f1` on a float from `--output text` | `50.0` compared as `50`, because `--output text` renders a JSON number and `test` compares strings | Section 8 |

Tag and dimension shorthand differs between services, and even between `put-metric-data` (`Service=enrolment`) and `put-metric-alarm` (`Name=Service,Value=enrolment`). Read the synopsis with `aws <service> <operation> help`.

---

## Sources

- [What is Application Auto Scaling?](https://docs.aws.amazon.com/autoscaling/application/userguide/what-is-application-auto-scaling.html)
- [Application Auto Scaling - services that you can use with it, and their resource ID formats](https://docs.aws.amazon.com/autoscaling/application/userguide/integrated-services-list.html)
- [Register a scalable target](https://docs.aws.amazon.com/autoscaling/application/userguide/services-that-can-integrate.html)
- [Target tracking scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-target-tracking.html)
- [Step scaling policies for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-step-scaling-policies.html)
- [Scheduled scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/scheduled-scaling.html)
- [Suspend and resume scaling for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-suspend-resume-scaling.html)
- [`PredefinedMetricSpecification`, including `ResourceLabel`](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_PredefinedMetricSpecification.html)
- [`StepAdjustment` - metric interval bounds](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_StepAdjustment.html)
- [`SuspendedState`](https://docs.aws.amazon.com/autoscaling/application/APIReference/API_SuspendedState.html)
- [Service-linked roles for Application Auto Scaling](https://docs.aws.amazon.com/autoscaling/application/userguide/security_iam_service-with-iam.html)
- [Automatically scale your Amazon ECS service](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-auto-scaling.html)
- [Amazon ECS cluster auto scaling - the different mechanism Section 11 contrasts](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cluster-auto-scaling.html)
- [Amazon ECS CloudWatch metrics, including CPUUtilization and MemoryUtilization](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-metrics.html)
- [CloudWatch metrics for your Application Load Balancer, including RequestCountPerTarget](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html)
- [Using Amazon CloudWatch alarms, including TreatMissingData](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html)
- [Publish custom metrics to CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/publishingMetrics.html)
- [`SetAlarmState` - testing an alarm's actions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_SetAlarmState.html)
- [Schedule expressions for rules - the six-field cron form](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-scheduled-rule-pattern.html)
- [Predictive scaling - an EC2 Auto Scaling feature, for contrast](https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-predictive-scaling.html)
- [Amazon VPC subnet sizing and the addresses AWS reserves - Exercise 4](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html)
- [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)
- [Amazon CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- [Application Auto Scaling service quotas](https://docs.aws.amazon.com/general/latest/gr/as-app.html)
- [`aws application-autoscaling` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/application-autoscaling/)
- [`aws cloudwatch` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/cloudwatch/)
- [JMESPath specification](https://jmespath.org/specification.html)

# Lab 04 - Amazon ECS

## 1. Objectives

- Containerise the USMS enrolment service onto Amazon ECS on Fargate, inside Lab 2's private subnets.
- Build a cluster, a log group, a task definition and a service that holds a fixed `desiredCount` of 2 across two Availability Zones.
- Separate the task **execution** role (pulls the image, writes logs) from the task **role** (the application's identity), and reuse Lab 1's `USMSStudentDataReadWrite` on the task role.
- Source the service's security group from the web tier's `usms-app-sg`, and explain how a private-subnet task pulls its image.
- Record every name and ARN in `configs/lab-04.env` for Labs 05 and 06.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [clusters](../unit2/topic2.md#the-cluster) ·
    [task definitions](../unit2/topic1.md#ecs-task-definitions) ·
    [tasks, services and the reconciliation loop](../unit2/topic2.md#tasks-services-and-the-reconciliation-loop) ·
    [Fargate](../unit2/topic2.md#aws-fargate) ·
    [task network modes](../unit2/topic2.md#task-network-modes) ·
    [ECS roles](../unit2/topic2.md#security-considerations) ·
    [service roles](../unit8/topic1.md#service-roles-instance-profiles-and-service-linked-roles) ·
    [security group referencing](../unit1/topic6.md#security-group-referencing-the-cloud-native-idiom) ·
    [NAT gateway](../unit1/topic6.md#nat-gateway) ·
    [log retention](../unit7/topic2.md#retention)

!!! info "Auto scaling is not this lab"
    Scalable targets, target tracking, step and scheduled scaling are Lab 06. This lab hands Lab 06 a service that stands still at `desiredCount` 2.

---

## 2. Prerequisites

- Labs 1, 2 and 3 complete, including Lab 2 Exercise 5 (both private subnets must exist).
- `usms-app-sg` attached to a running `usms-web-01` (Step 8 references that group by ID).
- `./scripts/utilities/verify-lab-02.sh` and `./scripts/utilities/verify-lab-03.sh` both report `FAIL=0`.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`.
- `jq` and `python3` installed (`python3 -m json.tool` validates every JSON document this lab writes).

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

If any tool prints `MISSING`, install it before starting.

---

## 3. What This Lab Reuses

From Lab 1:

- `usms-developer-role`: Step 4 creates the cluster while holding it, then restores your identity.
- `USMSStudentDataReadWrite`: Step 7 attaches it to `usms-ecs-task-role`, the same policy Lab 3's instance uses.
- `configs/course.env` names (`$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT`): used, never redeclared.

From Lab 2:

- `usms-private-subnet-a` and `-b`: Step 10 places the tasks in both, by ID from `configs/lab-02.env`.
- `usms-nat` and `usms-private-rt`: the only reason a private-subnet task can pull its image (Steps 10 and 11).
- `usms-s3-endpoint`: image layers are stored in S3, so the endpoint is on the pull path (Step 10).
- `usms-app-sg`: Step 8 makes it the only source of the enrolment service's inbound rule.

From Lab 3:

- `usms-web-01`: Exercise 5 resolves Step 8's group reference back to this instance.

```text
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

- **The moment three labs meet:** Lab 3 delivered `USMSStudentDataReadWrite` to an EC2 instance through an instance profile; Step 7 delivers the same policy to a container through a task role. Both are temporary credentials to code that never sees a key, and both start working the moment Lab 10 creates the bucket.

---

## 4. What We Are Building

The USMS enrolment service: the endpoint the student portal calls when someone clicks "Register for this module". This lab moves it from a single hand-managed EC2 instance onto Amazon ECS: an immutable task definition, a service controller that keeps `runningCount` equal to `desiredCount`, and a cluster that replaces a failed task without anyone logging in. `desiredCount` is set once, by hand, and stays fixed; Lab 05 adds a load balancer and Lab 06 makes the count move.

---

## 5. Architecture

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

## 6. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-04-ecs/
│       ├── README.md                              # this document
│       └── exercises.md                           # Section 12
├── policies/
│   ├── trust-ecs-tasks.json                       # NEW - trust policy for both ECS roles
│   └── usms-ecs-task-execution-policy.json        # NEW - USMSECSTaskExecution document
├── templates/
│   └── lab-04-taskdef.json                        # NEW - register-task-definition input
├── configs/
│   └── lab-04.env                                 # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-04.sh                       # NEW - Section 8
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

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths (`configs/...`, `policies/...`, `templates/...`, `scripts/...`) are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Every name and ARN below is captured into a variable. Step 12 writes them to `configs/lab-04.env` so Labs 05 and 06 can use them.

### Step 1 - Resume the environment and load three env files

Bring Floci up and load what the previous three labs recorded; this lab reads eight values from them.

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

Eight non-empty values. An empty `private subnet b` means Lab 2 Exercise 5 was skipped; do it first, because Step 10 places tasks across two Availability Zones.

---

### Step 2 - Confirm Labs 2 and 3 are still intact

This lab builds on resources from two previous labs; check they still exist and are configured correctly.

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

`FAIL=0` twice. Fix failures under `== Environment ==` first; resource failures below them are usually a consequence. Two failures would break this lab silently:

- **`private rt has NO route to an internet gateway`**: the private subnets would not be private, and Step 10's argument collapses.
- **`usms-web-01 carries usms-app-sg`**: Step 8's group reference would point at a group nothing uses.

---

### Step 3 - Probe what this Floci build actually supports

Find out now, not in Lab 06, whether your build supports ECS and Application Auto Scaling.

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

- `probe` runs a harmless read and reports whether the service answered at all. `describe-services --cluster probe` names a cluster that does not exist; `ClusterNotFoundException` still counts as "answered". An unsupported service returns a connection or `InvalidAction` error.
- `--max-items 1` is new: client-side pagination. The CLI stops after that many items and returns a `NextToken` you can pass back as `--starting-token`.

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

Write your path at the top of `notes/lab-04-notes.md`:

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | ECS and Application Auto Scaling both supported | Do every step as written; Lab 06 has full support too |
| **B - ECS only** | ECS supported, Application Auto Scaling not | Nothing in this lab changes. Record it anyway: Lab 06 reads this recording and gives a documented fallback |
| **C - neither** | ECS not supported | Stop and tell your instructor. Do the paper capacity plan in Exercise 4 instead |

!!! note "Floci Limitation - Application Auto Scaling support is build-dependent"
    Some Floci builds implement ECS but not `application-autoscaling`, or store scaling objects without ever evaluating a policy.

    Real AWS runs Application Auto Scaling as a continuously evaluating control loop, with an audit trail in `describe-scaling-activities`.

    Carry this into Lab 06: the **shape** of a scaling configuration is what you are assessed on, and it is observable even when a policy never fires.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running under Compose, storage mode hybrid
 ├── course.env + lab-01.env + lab-02.env + lab-03.env sourced
 ├── verify-lab-02.sh FAIL=0 and verify-lab-03.sh FAIL=0
 └── support path recorded: A (full) / B (ECS only) / C (neither)
```

---

!!! info "ECS in four objects, and Fargate sizing"
    A **cluster** is a namespace, not a machine. A **task definition** is an immutable, versioned blueprint (`usms-enrolment:1`, `:2`); you never edit a revision, you register a new one. A **task** is one running copy of it. A **service** keeps `runningCount` equal to `desiredCount`. **Auto scaling only ever changes `desiredCount`**; the service does the rest. See [tasks, services and the reconciliation loop](../unit2/topic2.md#tasks-services-and-the-reconciliation-loop) and [Fargate](../unit2/topic2.md#aws-fargate).

    Fargate removes the instances, not the network: an `awsvpc` task gets its own network interface in your subnet, with your security group, obeying your route tables. CPU and memory must be a valid pair, written as **strings** in the JSON:

    | CPU | Valid memory |
    | --- | --- |
    | 256 (.25 vCPU) | 512, 1024, 2048 MiB |
    | 512 (.5 vCPU) | 1024 to 4096 MiB, in 1024 steps |
    | 1024 (1 vCPU) | 2048 to 8192 MiB, in 1024 steps |
    | 2048 (2 vCPU) | 4096 to 16384 MiB, in 1024 steps |
    | 4096 (4 vCPU) | 8192 to 30720 MiB, in 1024 steps |

    This lab uses `256`/`512`, the smallest pair.

### Step 4 - Create the ECS cluster, as the developer role

Create the namespace everything else lives in, while holding `usms-developer-role` as Lab 2 Step 3 did.

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
    Environment credentials sit above named profiles in the CLI's resolution order. Until part 3 unsets them, every `aws` command runs as the assumed role, and after the one-hour session you get `ExpiredToken` errors that look nothing like their cause.

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

- `--settings name=containerInsights,value=enabled` publishes per-service CPU and memory to the `AWS/ECS` namespace; Lab 06's target tracking policy reads that metric.
- `--tags` is **lower case** (`key=`, `value=`) in ECS, unlike EC2's `Key=`/`Value=`. Services differ; when tagging in a new service, read the `--tags` synopsis in `aws <service> <operation> help`.

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

`Status` is `ACTIVE`, `Services` and `Tasks` are `0`, and `Settings` contains `containerInsights` = `enabled`. If `Settings` is empty, record it as a limitation: Lab 06 would then need a custom metric.

---

### Step 5 - Create the log group the tasks will write to

The `awslogs` driver in Step 9 names a log group, and ECS does not create it: a missing group makes the task fail to start with a log-driver error.

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

- Log group names use slashes as a hierarchy by convention (`/usms/ecs/enrolment`).
- `put-retention-policy` is a separate call; without it a group keeps (and bills for) data forever. See [retention](../unit7/topic2.md#retention).
- CloudWatch Logs `--tags` is a plain map (`Project=USMS`), a third tag convention.

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

One row, `Retention` exactly `7`. If it is `None`, re-run `put-retention-policy`; if it still shows `None`, record it as a finding.

---

!!! info "Two ECS roles, and which is which"
    Both trust `ecs-tasks.amazonaws.com`; the difference is who uses them and when.

    | | Task **execution** role (`executionRoleArn`) | Task role (`taskRoleArn`) |
    | --- | --- | --- |
    | Used by | ECS/Fargate, **before** your container starts: image pull, log stream, secrets | Your application code, **inside** the container: S3, DynamoDB, SQS |
    | Symptom if wrong | The task **never starts**; `stoppedReason` mentions the image pull or logs | The task starts, then the code gets `AccessDenied` |

    See [ECS security considerations](../unit2/topic2.md#security-considerations).

### Step 6 - Create the task execution role

Fargate needs an identity to pull the image and open the log stream before your code exists.

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

!!! warning "Heredoc quoting"
    `<< 'EOF'` (quoted) writes the policy exactly as shown, with no expansion. Step 9's task definition uses unquoted `<< EOF` because its variables must become real values at write time. Ask: *do I want this expanded now, or later?*

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

- `ecr:GetAuthorizationToken` takes no resource, so `"Resource": "*"` is correct for it; a narrower ARN would silently deny.
- The `logs` statement is scoped to **one log group** (`:*` covers its streams). AWS's managed `AmazonECSTaskExecutionRolePolicy` allows writing to any log group.
- Region and account are hard-coded because a quoted heredoc cannot expand variables; Exercise 3 asks you to build it with variables.

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

The principal is `{"Service": "ecs-tasks.amazonaws.com"}` (not `ecs.amazonaws.com`, the most common ECS typo), and the attached list contains `USMSECSTaskExecution`.

---

### Step 7 - Create the task role, and reuse Lab 1's policy on it

The container's own identity, holding the policy Lab 1 wrote for an EC2 instance, unchanged.

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

`$USMS_POLICY_S3_RW` comes from `configs/lab-01.env` (`USMSStudentDataReadWrite`). The trust file from Step 6 is reused because both roles trust the same principal.

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

**Verify - and read the policy**

```bash
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${USMS_POLICY_S3_RW}"
DEFAULT_VERSION=$(aws iam get-policy --policy-arn "$POLICY_ARN" \
  --query 'Policy.DefaultVersionId' --output text)

aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$DEFAULT_VERSION" \
  --query 'PolicyVersion.Document' --output json | tee outputs/lab-04-task-role-policy.json
```

It is the same document Lab 3 Step 11 printed: `s3:GetObject`, `s3:PutObject` and `s3:ListBucket` on `arn:aws:s3:::usms-student-data` and its objects, and a deny on `s3:DeleteBucket`. Two kinds of compute now hold it through two mechanisms:

```text
Lab 03   usms-web-01 ── instance profile ── usms-ec2-app-role ──┐
                                                                ├── USMSStudentDataReadWrite
Lab 04   task         ── taskRoleArn      ── usms-ecs-task-role ─┘
                                                                     |
                                                          arn:aws:s3:::usms-student-data
                                                              (does not exist yet - Lab 09)
```

Neither has a key on disk, and both start working when Lab 10 runs `create-bucket`. Write that in `notes/lab-04-notes.md`; it is Review Question 2.

!!! note "Floci Limitation - the container cannot fetch its own credentials"
    On real AWS a Fargate task gets rotating temporary credentials from an endpoint named in `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`, which every SDK finds automatically. Floci does not serve that endpoint to containers.

    The association is still real and is what you are assessed on: the task definition names the role, the role trusts the ECS principal, and the role holds the policy, all visible through `describe-task-definition` and `iam get-role`.

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

An `awsvpc` task has its own security group. The enrolment API accepts calls from the web tier only.

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

- `<< EOF`, unquoted, so `$USMS_APP_SG` becomes a real ID. A literal `$USMS_APP_SG` in the file means the wrong form; the API then reports an invalid group ID.
- The source is a group, not `10.0.1.0/24` (Lab 2 Step 15), and tasks have no stable addresses, so group references are close to mandatory once task counts change. See [security group referencing](../unit1/topic6.md#security-group-referencing-the-cloud-native-idiom).

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

One inbound rule on port 80, `FromGroup` = `$USMS_APP_SG`, `FromCIDR` = `null`. `OutboundRules` is `1`: the default allow-all egress, which Step 10 relies on.

---

### Step 9 - Write and register the task definition

The blueprint that references everything Steps 5 to 8 produced.

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

Unquoted heredoc, so the variables are substituted. `grep -c '\$'` **must print `0`**; anything else means a variable was empty or the heredoc was quoted.

| Field | Why this value |
| --- | --- |
| `family` | The name without a revision. Registering again produces `usms-enrolment:2`; revision 1 stays readable |
| `networkMode` | `awsvpc` is **required** for Fargate: own ENI, private address and security group (Step 8) |
| `requiresCompatibilities` | Launch types this definition is valid for; wrong values fail at registration |
| `cpu` / `memory` | **Strings, not numbers.** A valid Fargate pair from the box before Step 4 |
| `executionRoleArn` | Step 6's role. Pulls the image, opens the log stream |
| `taskRoleArn` | Step 7's role. What the application code is |
| `image` | A public registry reference. See the note below |
| `essential` | `true`: if this container exits, the whole task stops |
| `logConfiguration` | `awslogs` sends stdout and stderr to Step 5's group; `awslogs-stream-prefix` identifies each task's stream |
| `tags` | Lower-case `key`/`value`, because this is the ECS API |

!!! note "Floci Limitation - the container image is a stand-in"
    The real service would be your own image in a private ECR repository, which would need the `5100-5104` port range uncommented. This lab does not need it, so `public.ecr.aws/nginx/nginx:stable-alpine` is a small real placeholder; nothing sends it a request.

    Depending on your build, the task may run as a Docker container or never leave `PROVISIONING`. Both are fine: every proof here uses `desiredCount`, a control-plane number.

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

`Status` is `ACTIVE`, `Network` is `awsvpc`, and `Exec` and `Task` are two **different** ARNs (the same ARN in both means the code would get `AccessDenied` on S3). `options."awslogs-group"` needs double quotes because a hyphen would otherwise be read as subtraction (see the Appendix).

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

The service keeps `runningCount` matching `desiredCount`, and its tasks make Lab 2's NAT gateway load-bearing.

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

`--network-configuration` is shorthand for a nested structure: no spaces, square brackets for lists, **no quotes around IDs**:

```text
awsvpcConfiguration={subnets=[<id>,<id>],securityGroups=[<id>],assignPublicIp=DISABLED}
```

If it fights you, generate a skeleton and use a document instead:

```bash
aws ecs create-service --generate-cli-skeleton > outputs/lab-04-create-service-skeleton.json
```

- `assignPublicIp=DISABLED` is the default, stated explicitly because it is security-relevant.
- `--enable-ecs-managed-tags --propagate-tags SERVICE` copies the service's tags onto every task it launches, including tasks created later by auto scaling.

The tasks are in private subnets with no route to `usms-igw`, yet must reach `public.ecr.aws`:

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

Without the NAT gateway or the private default route, the service would create successfully and every task would fail with an image-pull timeout. The S3 endpoint also avoids NAT data charges on layer pulls. See [NAT gateway](../unit1/topic6.md#nat-gateway) and [VPC endpoints](../unit1/topic6.md#vpc-endpoints).

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

`services-stable` waits until `runningCount` equals `desiredCount` with no deployment in progress (about 40 seconds on real AWS). On Floci it is immediate or never; `runningCount` stuck at 0 is the container limitation and does not block this lab.

---

### Step 11 - Read the service back, and learn the four numbers

Four fields describe a service's health; learn them while they are all equal.

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

| Field | Meaning | If it is not what you expect |
| --- | --- | --- |
| `desiredCount` | What you (or auto scaling) asked for | The **only** field auto scaling writes. Not moving means the policy is not firing |
| `runningCount` | Tasks actually up | Low for a long time means tasks fail to start; read `stoppedReason` |
| `pendingCount` | Tasks starting now | Stuck above 0 means capacity or networking trouble (image pull, subnet addresses) |
| `status` | `ACTIVE`, `DRAINING` or `INACTIVE` | `INACTIVE` means deleted; it stays visible for a while |

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

`Subnets` lists **two** private subnet IDs matching `$USMS_PRIVATE_SUBNET_A` and `$USMS_PRIVATE_SUBNET_B`, and `PublicIP` is `DISABLED`. The `events` list is the service's own narration and the first place to look when `runningCount` will not rise. If `length(taskArns)` is 0 while `Desired` is 2, record the container limitation and continue.

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

Hint: `aws ecs update-service help` and look for `--desired-count`; name the cluster and service on every call.

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

Record every name and ARN by lookup, not from shell variables, so a populated value is evidence the resource exists. Lab 05 and Lab 06 source this file.

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

- Unquoted `<< EOF` so every `$(...)` runs now and the value lands on disk; quoted, `source` would re-run nine API calls in every new terminal.
- `USMS_ECS_DESIRED_BASELINE` is read back, not hard-coded, so the file records what is true; Lab 06 uses it as the scalable target's floor.

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

`all values populated`, eight non-empty lines, and **17** exports. `baseline desired` must read `2`; anything else means the Step 11 "Your turn" left the count wrong. A `None` means a resource does not exist; find which before continuing.

---

### Step 13 - Commit

Look first, stage explicitly, then commit.

**Command - part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/lab-04-assumed-role.json
git ls-files outputs/
```

Before typing anything else:

- No path under `outputs/` and no root `.env` appears in `git status --short`.
- `configs/lab-04.env` **does** appear (names and ARNs, not secrets).
- `git check-ignore -v` names the file, rule and line. **Silence means the file is not ignored**; fix `.gitignore` first.
- `git ls-files outputs/` lists only `outputs/.gitkeep`.

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

Name paths explicitly rather than `git add -A`, which stages whatever is in the tree, including an un-ignored secret. The two script paths only exist after Section 8; if you commit before that, drop them and add them in a second commit.

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

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-04.sh`

Beyond existence, the script checks the configuration that matters: exec and task roles are **different**, the service spans **two** subnets, the enrolment group is sourced from `usms-app-sg` (not a CIDR), and the log group has retention. The environment block comes first, because a script that checks only its own resources passes right up until the restart that deletes them.

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
| `service $USMS_ENROLMENT_SERVICE is ACTIVE` / any Lab 04 ECS check with `Running` at 0 | Some Floci builds never start a Fargate container; `runningCount` stays 0 while `desiredCount` is correct. Confirm with `describe-services --output json` and record it |
| `log group has a retention policy set` | Some builds ignore `put-retention-policy`. Confirm and record |
| `service spans TWO subnets` | Lab 2 Exercise 5 was skipped, so `usms-private-subnet-b` does not exist. This one is **not** benign - go and do it |

Everything else failing is a real problem with your work.

### 8.2 Build the end-of-course cleanup script

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

You should see `syntax OK - do NOT run it`; `bash -n` parses without executing. The order matters:

1. **`--desired-count 0` before `delete-service`**: `--force` alone kills tasks without draining.
2. **Task definitions before the cluster**: deregistered revisions stay `INACTIVE`, never fully deleted.
3. **IAM detach before delete**: `delete-role` fails with `DeleteConflict` without naming the policy.
4. **The security group after the service**: a group on a task's interface gives `DependencyViolation`.
5. **After Lab 06's and Lab 05's cleanup scripts**: their scalable target and load balancer depend on this service.

---

## 9. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 3 | Floci running under Compose, four env files sourced, `verify-lab-02.sh` and `verify-lab-03.sh` both `FAIL=0`, and your support path (A, B or C) recorded |
| 2 | Step 7 | `usms-ecs-cluster` ACTIVE; `/usms/ecs/enrolment` with 7-day retention; `usms-ecs-exec-role` with `USMSECSTaskExecution`; `usms-ecs-task-role` with Lab 1's `USMSStudentDataReadWrite` |
| 3 | Step 9 | `usms-enrolment:1` ACTIVE, `awsvpc`, FARGATE, 256/512, and two **different** role ARNs in `executionRoleArn` and `taskRoleArn` |
| 4 | Step 11 | Service ACTIVE, desired 2, spanning both private subnets, `assignPublicIp` DISABLED, carrying `usms-enrolment-sg` |
| 5 | Step 13 | `configs/lab-04.env` populated with 17 exports and committed; nothing under `outputs/` staged; `git check-ignore -v` names the rule |

---

## 10. Troubleshooting

??? danger "`ClusterNotFoundException` on a call that names a cluster you can see"
    ECS has no default cluster in this course, and names are case-sensitive. Confirm what exists:

    ```bash
    aws ecs list-clusters --query 'clusterArns[]' --output text
    ```

    If the cluster is there, `$CLUSTER_NAME` is probably empty in this terminal. Source the env file:

    ```bash
    source configs/lab-04.env
    echo "$USMS_ECS_CLUSTER"
    ```

??? danger "`InvalidParameterException: Task definition does not support launch type FARGATE`"
    `requiresCompatibilities` does not list `FARGATE`, or `networkMode` is not `awsvpc`. Fargate needs both, and rejects `bridge` and `host`.

    ```bash
    aws ecs describe-task-definition --task-definition usms-enrolment \
      --query 'taskDefinition.{Net:networkMode,Compat:requiresCompatibilities}' --output json
    ```

    Fix the document and register revision 2 (revision 1 cannot be edited), then
    `aws ecs update-service --cluster ... --service ... --task-definition usms-enrolment:2`.

??? danger "`ClientException: Invalid 'cpu' setting for task`"
    `cpu` and `memory` must be a valid Fargate pair (the box before Step 4), both as **strings**. `"cpu": 256` unquoted, or `"cpu": "256"` with `"memory": "768"`, are both rejected. 256 CPU allows only 512, 1024 or 2048 MiB.

??? danger "The service is created but `runningCount` stays at 0"
    On real AWS this is nearly always the image pull or the network path. Read what the service says first:

    ```bash
    aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
      --query 'services[0].events[0:5].[createdAt,message]' --output text

    aws ecs describe-tasks --cluster "$USMS_ECS_CLUSTER" \
      --tasks $(aws ecs list-tasks --cluster "$USMS_ECS_CLUSTER" --desired-status STOPPED \
                  --query 'taskArns[0]' --output text) \
      --query 'tasks[0].{Stopped:stoppedReason,Containers:containers[].reason}' --output json
    ```

    `stoppedReason` naming the image or registry points at the execution role or the route out. Naming the log driver means Step 5's log group is missing.

    On Floci, `runningCount` 0 is expected on builds that do not start containers. Record it and continue.

??? danger "`ResourceInUseException` when deleting the service or the cluster"
    A service with running tasks needs `--force`, and a cluster with an active service cannot be deleted. The graceful order is in `scripts/cleanup/lab-04-cleanup.sh`: scale to zero, wait, delete the service, then the cluster.

??? danger "`DeleteConflict` when deleting one of the ECS roles"
    A role with an attached managed policy cannot be deleted, and the error does not name the policy. List and detach first:

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

    The health output also lists which services this build started, a quick second opinion on Step 3's probe.

??? danger "Everything is gone after a restart"
    Run `./scripts/utilities/floci-storage-check.sh`. `FLOCI_STORAGE_MODE=memory` means a stray `floci start` replaced the Compose container. The work is not recoverable; restore from the snapshot you took at the end of Practical 1 and confirm the storage check before building.

---

## 11. Floci vs Real AWS

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

In your report, say which items you observed (cluster, task definition revision, service placement, both roles, the group-referenced rule, `desiredCount` changed by hand) and which you only reasoned about (a running container, Container Insights metrics, start latency, cost). Path A builds may move items into the first list.

**Where Floci is nicer than reality (traps on real AWS):** tasks start instantly or never (real Fargate takes 20 to 60 seconds, which Lab 06's cooldowns are sized around); no cost (two `256`/`512` tasks are roughly USD 15 per month at us-east-1 list prices; check the pricing page, Exercise 4 asks you to cite it); no quotas on tasks per service or services per cluster.

!!! info "ECS Service Auto Scaling is not EC2 Auto Scaling"
    Lab 06 uses **Application Auto Scaling** (`aws application-autoscaling`), which changes a service's `desiredCount` and needs only the task definition. **EC2 Auto Scaling** (`aws autoscaling`) scales instances from a launch template, which is what Lab 3 Step 20's `usms-web-golden` AMI is for. With the ECS `EC2` launch type you need both (tasks and the instances they land on); Fargate removes the second. See [the two scaling layers](../unit2/topic3.md#the-two-scaling-layers-revisited).

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-04-ecs/exercises.md`, with screenshots in `screenshots/` where asked.

### Exercise 1 - Basic: a second service, deployed

**Requirements**

Create `usms-results-svc` (the exam results service) in `usms-ecs-cluster` from the existing `usms-enrolment` task definition family, with a desired count of 1, in both private subnets, carrying `usms-enrolment-sg`.

**Constraints**

- Every ID captured with `$(...)` and `--query`. Nothing copied by hand.
- Tag the service `Project=USMS`, `Tier=app`, `Lab=04`, `Service=results`.
- Do **not** record it in `configs/lab-04.env`. Exercise 4 removes it.

**Expected outcome**

`aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc usms-results-svc`
returns **two** `ACTIVE` services, with different names and different desired counts.

**Hints**

Step 10 contains every command; decide which values change. The Section 8 script does not check for extra services, so this will not make it fail.

---

### Exercise 2 - Intermediate: a new revision, and a deployment that does not drop traffic

**Requirements**

Register `usms-enrolment:2` from a copy of `templates/lab-04-taskdef.json` with `memory` raised from `512` to `1024` MiB (still valid for `cpu: 256`) and a new environment variable `USMS_LOG_LEVEL=info`. Update `usms-enrolment-svc` to run it, wait for it to stabilise, and confirm revision 1 is still describable.

**Constraints**

- Keep a copy of the template that produced revision 1; do not edit it in place.
- Use `aws ecs wait services-stable` or the manual polling loop from Step 10, not a fixed `sleep`.
- State, in one sentence, what `taskDefinition` field on the service changes and what does not.

**Expected outcome**

`describe-services` shows `taskDefinition` ending in `:2`; `describe-task-definition --task-definition
usms-enrolment:1` still succeeds and still reports `ACTIVE`, because deregistering is a separate action
this exercise does not take.

**Hints**

Step 9 shows how to write and register a revision. The update is one call:
`aws ecs update-service --cluster ... --service ... --task-definition usms-enrolment:2`. A revision is immutable; the service's *pointer* to one is not.

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

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as the Section 8 script does.
- No hard-coded service name anywhere - list services from the cluster, then describe each one.
- Must not crash when a service has no `networkConfiguration` (an `EC2` launch type service, for example). Print `publicip=N/A` rather than an error.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- Also write the same data as JSON to `outputs/lab-04-ecs-inventory.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-04-ecs/`, correctly classifying `usms-enrolment-svc` and every service created by earlier exercises.

**Hints**

`aws ecs list-services --cluster ... --query 'serviceArns[]'` gives the list to iterate. Decide what "no data" means for each column and print something explicit, never an empty field.

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

- **Why a fixed `desiredCount` of 2 cannot answer the 08:03 problem**: `usms-enrolment-svc` reads no metric or clock, so only a human running `update-service` changes its capacity.
- **A proposed plan** with concrete numbers for a minimum, a maximum and a scheduled floor around the enrolment window, each with one sentence on the cost of too high and too low. You are handing this to Lab 06, not implementing it.
- **A monthly cost comparison** of at least two options: fixed at your proposed peak, versus fixed at today's 2. Use current Fargate per-vCPU-hour and per-GB-hour prices, and **cite where you got them**.
- **What to switch off**, with the exact commands in dependency order, each preceded by the four-line danger admonition: the Exercise 1 results service.

Then execute only the deletion, and confirm `./scripts/utilities/verify-lab-04.sh` reports `FAIL=0`
afterwards.

**Constraints**

- Do not delete anything in Section 15's KEEP column.
- Every number must have a source or a derivation. "About 10 tasks" earns nothing; "10 tasks, because
  200 requests per second at 25 requests per task per second plus one task of headroom" earns full marks.

**Expected outcome**

An analysis a project lead could act on and a finance team could check, plus a repository in which the
Exercise 1 practice resource is gone and the verification still passes.

**Hints**

There is no policy to point at; the exercise asks for the reasoning Lab 06 will encode. Section 11's cost figures are your starting point.

---

### Exercise 5 - Integration: close the loop back to Lab 3, and hand Lab 05 what it needs

**Requirements**

Resolve Step 8's group reference back to the instance that carries it, and record the result for Lab 05, whose cutover step removes this rule.

1. Resolve `usms-enrolment-sg`'s only inbound source group back to the running instance that carries it:
   `aws ec2 describe-instances --filters "Name=instance.group-id,Values=<group>"
   "Name=instance-state-name,Values=running"`.
2. Confirm that instance matches `$USMS_WEB_INSTANCE` from `configs/lab-03.env`. If not, explain why (a relaunch, or a second instance carrying the group) rather than treating a mismatch as success.
3. Write `outputs/lab-04-lab03-linkage.txt` containing: the source group ID, the instance it resolves to, the `LOOP CLOSED` or `MISMATCH` verdict, and one sentence stating that this rule is temporary - Lab 05 removes it once the load balancer becomes the only caller.
4. Audit everything this lab tagged `Project=USMS`, using `aws ecs list-tags-for-resource` against the cluster ARN and the service ARN from `configs/lab-04.env`, and append the result to the same file.

**Constraints**

- `aws ecs list-tags-for-resource` takes an **ARN**, not a name, unlike most ECS calls in this lab.
- If any ECS resource shows no tags, note it (some builds accept `--tags` without storing them). Fix what you can with `aws ecs tag-resource --resource-arn <arn> --tags key=Project,value=USMS` and record the rest.

**Expected outcome**

A committed file that a reader of Lab 05 could open before running Lab 05's cutover step and know
exactly what is about to change and why it is safe to change it.

**Hints**

`--filters "Name=instance.group-id,Values=..."` is the reverse lookup to run before changing or deleting any group. Read Lab 05's Section 1 to see why this file matters.

---

## 13. Lab Assessment Checklist

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
- [ ] I can say, from the box before Step 6, which failure symptom points at the execution role
      and which points at the task role
- [ ] I can explain why the enrolment security group's rule names a group and not a CIDR block, and why
      that choice matters even before Lab 06 exists
- [ ] I can say what Fargate removed from the EC2 model in Lab 3, and what it did not remove

---

## 14. Review Questions

Answer in prose, in your own words, in `notes/lab-04-notes.md`.

1. A colleague says "I put auto scaling on the task definition." Explain every way that is wrong: what auto scaling will be attached to in Lab 06, what it modifies, and which ECS object makes reality match. What observable consequence follows from ECS itself knowing nothing about the scalable target?

2. Lab 1 wrote `USMSStudentDataReadWrite` for a bucket that did not exist; Lab 3 attached it to an EC2 instance via an instance profile; this lab attached it, unchanged, to a Fargate task via a task role. In a full paragraph, explain what each delivery mechanism does at runtime, why neither needs a key on disk, and what changes for **both** the moment the bucket exists.

3. Give a one-sentence failure symptom for the task **execution** role and for the task **role** that a colleague could use to tell them apart, and explain why both share an identical trust policy despite doing different jobs.

4. Step 8 sources the enrolment group's only inbound rule from `usms-app-sg`, not a CIDR block. Explain why this is correct even if the task count never changed, and the additional reason it becomes close to mandatory once Lab 06 lets the count change.

5. What does Fargate remove from Lab 3's EC2 model, and what does it not remove? Use the fact that an `awsvpc` task still has its own security group and obeys Lab 2's route tables.

6. Lab 1 Step 14 showed that an unchanged account identity after a restart is not evidence of persistence. Name one command against this lab's resources that would look identical in `memory` and `hybrid` mode, one that would not, and explain the difference.

---

## 15. KEEP vs CLEAN UP

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

**The architecture you now have**

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
  usms-web-golden  AMI -> the EC2 Auto Scaling lab, which is NOT this lab (see Section 11)

Lab 04  COMPUTE - deployed, standing still                       <-- you are here
  usms-ecs-cluster
    usms-enrolment-svc   desired 2, both private subnets, usms-enrolment-sg
      usms-enrolment:1   exec role + task role

Lab 05  (next)  a load balancer in front of usms-enrolment-svc
Lab 06  (after that)  Application Auto Scaling on usms-enrolment-svc
```

---

## 16. Preparation for the Next Lab

Lab 05 puts an Application Load Balancer and target group in front of `usms-enrolment-svc`, and the service keeps the target group's membership current as tasks come and go. Lab 06 then lets `desiredCount` move on its own.

| From `configs/lab-04.env` | Lab 05 uses it for |
| --- | --- |
| `USMS_ECS_CLUSTER` / `USMS_ENROLMENT_SERVICE` | Attaching the existing service to a new target group, rather than creating a second service |
| `USMS_ENROLMENT_SG` | The security group Lab 05's cutover step edits, once the load balancer is the only caller |
| `USMS_ENROLMENT_CONTAINER` | Naming which container in the task definition receives traffic from the load balancer |

| From `configs/lab-04.env` | Lab 06 uses it for |
| --- | --- |
| `USMS_ECS_DESIRED_BASELINE` | The floor of the scalable target Lab 06 registers - see Section 11 |
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
limitation from Section 11, recorded rather than fought).

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

## Appendix - New CLI and JMESPath patterns

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

**Tag syntax differs by service:**

| Service | Syntax |
| --- | --- |
| EC2 | `--tag-specifications 'ResourceType=x,Tags=[{Key=K,Value=V}]'` |
| ECS | `--tags key=K,value=V` (lower case) |
| IAM | `--tags Key=K,Value=V` (capitals, no `ResourceType`) |
| CloudWatch Logs | `--tags K=V` (a plain map) |

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

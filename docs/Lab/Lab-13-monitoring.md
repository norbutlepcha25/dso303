# Lab 13 - Centralized Logging and Monitoring with CloudWatch and X-Ray

*Practical 8 in the delivery schedule, Practical 6 in the module descriptor.*

---

## 1. Lab Overview

Every laboratory so far has built something and then checked that it existed. This one is about the
difference between checking that something exists and knowing what it is doing.

You already have a system. Three IAM roles, a VPC with four subnets, two EC2 instances, an ECS
service behind a load balancer, a Kubernetes cluster, three Lambda functions, a
bucket, and a notification wired between two of them. Seven laboratories of infrastructure, and if
a student's transcript failed to appear tomorrow morning you would have no way to find out where it
stopped.

That is what this lab fixes, and it does it with two services that answer two different questions.

**Amazon CloudWatch** answers *what happened, and how often*. It holds three distinct kinds of
thing, and conflating them is the single most common reason people find CloudWatch confusing:
**logs** are lines of text your code emitted, **metrics** are time-ordered numbers, and **alarms**
are rules that watch a metric and change state. A metric filter is the bridge between the first two,
and it is the most useful object in the service.

**AWS X-Ray** answers *where did this one request spend its time, and which hop failed*. A log line
tells you that a function ran. A trace tells you that the function ran, called S3, waited 900
milliseconds for it, and then returned - and it tells you that about **one specific request**, by id,
across every service that request touched.

You need both, and the reason you need both is the reason this lab exists: a metric tells you
something is wrong, a log tells you what the error said, and a trace tells you which of your eleven
components said it.

There is also something to admit at the start. You have been using CloudWatch since Lab 06 without
being taught it. That lab created an alarm called `usms-enrolment-queue-high` and two target-tracking
scaling policies, and every one of those is a CloudWatch alarm underneath. Lab 04 created the log
group `/usms/ecs/enrolment`. Lab 10 created `/aws/lambda/usms-transcript-notifier` by doing nothing
at all except invoking a function. Step 5 of this lab goes and looks at all of it, because the honest
starting point for a monitoring lab is an inventory of the monitoring you already have and did not
know about.

**Time:** roughly four hours. **Assessment:** Section 14. **Project checkpoint:** Appendix C.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. Distinguish CloudWatch **logs**, **metrics**, **alarms** and **dashboards**, and say which
   question each answers.
2. Explain the log group / log stream / log event hierarchy, and choose a retention period
   deliberately rather than accepting the default of never.
3. Write log events with `aws logs put-log-events`, including getting the timestamp units right,
   and read them back with `filter-log-events`.
4. Test a CloudWatch Logs **filter pattern** against sample messages before deploying it, and then
   deploy it as a **metric filter** that turns matching log lines into a metric.
5. Publish **custom metrics** with `put-metric-data`, and explain why a dimension is part of a
   metric's identity rather than a label on it.
6. Read a metric back with `get-metric-statistics`, choosing period, statistic and time window
   deliberately.
7. Create an **alarm** with `put-metric-alarm`, choose a `--treat-missing-data` policy and justify
   it, and prove the alarm works by driving it through a state transition with `set-alarm-state`.
8. Build a **composite alarm** whose rule combines other alarms, and say what problem that solves.
9. Create a **dashboard** from a JSON document and read back the validation messages that tell you
   whether a widget will render.
10. Explain the X-Ray data model - **trace**, **segment**, **subsegment**, **annotation**,
    **metadata** - and construct a valid segment document by hand.
11. Send segments with `put-trace-segments`, retrieve them with `get-trace-summaries` and
    `batch-get-traces`, and read a **service graph**.
12. Distinguish an **annotation** from **metadata** by what you can search on, and configure a
    **sampling rule** that decides which requests are traced at all.
13. Enable **active tracing** on a Lambda function and name the permissions it requires.
14. State precisely which of the above you observed working in Floci and which you recorded without
    being able to observe.

---

## 3. Prerequisites

Before starting, you need:

- Labs 01 through 12 complete, and their `configs/lab-NN.env` files present. Step 2 checks this and
  tolerates the absence of the S3 configuration lab, which was never delivered - see Section 4. This
  lab does not require anything specific from Lab 11 or Lab 12's own artefacts - it observes whatever
  is running in `usms-ecs-cluster`, however it got there - but by this point in the course that
  service has been redeployed at least once through Lab 12's pipeline.
- Floci running under Docker Compose, with `FLOCI_STORAGE_MODE` set to `hybrid`.
- A terminal in which a **new window** already has `AWS_PROFILE` and `COURSE_ROOT` set. If that is
  not true, you have the defect described in Errata 01 and you should fix it now rather than at
  Step 13.
- `python3` on your path. This lab leans on it harder than any previous one, for millisecond
  timestamps, hex identifiers and JSON construction - all three of which differ between macOS and
  Linux if you try to do them in the shell.
- `usms-transcript-notifier` from Lab 10, with its alias `live`. Step 13 publishes a new version of
  it and repoints that alias, which is the first time in this course an alias has actually been used
  for the thing aliases are for.

Run this before anything else:

```bash
cd ~/aws-floci-course
./scripts/utilities/floci-storage-check.sh
./scripts/utilities/verify-lab-10.sh | tail -2
```

You want `PASS=16  FAIL=0` from the first and `PASS=51  FAIL=0` from the second. A failure in the
first block of the storage check means a new terminal cannot find the course, and the AWS CLI will
tell you that your *credentials* are wrong, which they are not.

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 will suggest `aws login`. That begins a sign-in to
    **real AWS**. The answer in this course is always `source configs/course.env` or a missing
    `floci` profile - never a sign-in. See Errata 01 Section 3.

---

## 4. Connection to Previous Labs

### 4.1 A note on the roadmap, and the gap this lab steps over

An earlier roadmap called for a dedicated S3 configuration lab next, to configure
`usms-student-data` properly and apply the bucket policy Lab 09 drafted. That lab was never written,
and centralized logging and monitoring sits here instead.

That is not a problem, and it is worth saying why rather than leaving you to wonder. The unwritten
S3 lab's subject matter is bucket **configuration** - versioning, encryption, lifecycle, the bucket
policy. Nothing in this lab reads any of that. What this lab needs from S3 is a bucket that exists
with objects in it and a notification pointing at a Lambda function, and **Lab 10 Step 5 and Step 20
already built exactly that**.

So this lab does not depend on that S3 lab existing at all. Step 2 sources every `configs/lab-NN.env`
file that is present and reports `absent` for any that are not, and an absent one is treated as
information, not a failure. Where an artefact from the S3 lab would have been convenient, the step
says so and uses a Lab 10 artefact instead.

One consequence to keep in your head: if that S3 lab is ever written, it will add an SNS destination
to the bucket notification, and `put-bucket-notification-configuration` replaces the whole document.
The dashboard and alarms you build today do not depend on that document, so they would survive it -
but the metric filter you build in Step 9 depends on the notifier still being invoked, and that would
not.

### 4.2 Current Environment

```text
Created in previous labs:
- Lab 01: IAM foundation - 3 groups, 3 users, 3 roles, 5 policies, 1 instance profile
- Lab 01: usms-lambda-exec-role + USMSLambdaBasic  (logs write + s3:GetObject)
- Lab 02: usms-vpc 10.0.0.0/16, 4 subnets, IGW, NAT, route tables, usms-s3-endpoint
- Lab 03: usms-web-01, usms-db-01, usms-web-golden AMI
- Lab 04: usms-ecs-cluster, usms-enrolment-svc, AND THE LOG GROUP /usms/ecs/enrolment
- Lab 05: usms-enrolment-alb, usms-enrolment-tg, usms-alb-sg
- Lab 06: usms-enrolment-queue-high - AN ALARM. You have been using CloudWatch since Practical 4
- Lab 09 (security): USMSStudentDataReadOnly, usms-deploy-role
- Lab 07/08 (EKS deployment target): usms-eks-cluster, usms-eks-nodes, usms-enrolment-hpa
- Lab 10: usms-student-data + transcripts/evidence/*
- Lab 10: usms-edge-viewer-request:1, usms-edge-origin-response:1
- Lab 10: usms-transcript-notifier, alias live -> 1, AND /aws/lambda/usms-transcript-notifier
- Lab 11: usms-enrolment-pipeline (Source -> Build), usms-enrolment-build, usms-pipeline-artifacts
- Lab 12: usms-enrolment ECR repository, usms-enrolment:3, the pipeline's Deploy stage
- Lab 12: usms-ecs-cluster / usms-enrolment-svc, now running the image the pipeline pushed
- S3 configuration lab: NOT DELIVERED. Nothing here depends on it

Created in this lab:
- /usms/central/application ....... the central log group, retention set
- retention policies .............. on every USMS log group, replacing "never expire"
- usms-notify-count ............... metric filter on the notifier's log group
- usms-central-errors ............. metric filter on the central log group
- USMS/Application ................ custom metric namespace, 3 metrics, 2 dimensions
- USMSObservabilityWrite .......... new customer managed policy: logs + metrics + traces
- usms-transcript-notifier v2 ..... instrumented; alias live REPOINTED from 1 to 2
- active tracing .................. TracingConfig Mode=Active on the notifier
- usms-transcripts-sampling ....... X-Ray sampling rule
- usms-transcript-lag-high ........ metric alarm, proven by a forced state transition
- usms-notify-silence ............. metric alarm on an absence, treat-missing-data breaching
- usms-transcript-pipeline-down ... COMPOSITE alarm over the two above
- usms-overview ................... dashboard, 5 widgets
- scripts/utilities/usms-emit-telemetry.sh ... one log line, one metric, one trace, together

Required for future labs:
- USMS_ALARM_LAG_HIGH, USMS_ALARM_NOTIFY_SILENCE -> a future alerting lab (not yet written) attaches SNS actions to these
- outputs/lab-13-alarm-actions-draft.json        -> that same future lab applies it
- USMS/Application namespace                     -> every later lab publishes into it
- USMSObservabilityWrite                         -> attached to any new role that emits telemetry
- usms-overview dashboard                        -> later labs add widgets rather than new dashboards
```

### 4.3 What this lab genuinely reuses

Not "mentions". Uses.

| From | Resource | How this lab actually uses it |
| --- | --- | --- |
| Lab 04 | `/usms/ecs/enrolment` | Step 6 sets a retention policy on it. It has been keeping logs forever since Practical 2, and since Lab 12 those logs come from the container the pipeline built and pushed, not the one Lab 04 first registered |
| Lab 06 | `usms-enrolment-queue-high` | Step 5 reads it back as the proof that you have been an unwitting CloudWatch user for four laboratories, and Step 21's composite alarm is contrasted against it |
| Lab 10 | `/aws/lambda/usms-transcript-notifier` | The log group Step 9 attaches a metric filter to. It exists because Lambda created it, not because anybody asked |
| Lab 10 | the `USMS_NOTIFY` marker string | Written into the handler in Lab 10 Step 17 purely so `grep` could find it. Step 9 turns that same string into a metric filter pattern, and the marker stops being a debugging convenience and becomes an interface |
| Lab 10 | `usms-transcript-notifier` alias `live` | Step 13 publishes version 2 and repoints the alias. Lab 10 explained what an alias was for; this is the lab that uses one |
| Lab 10 | `usms-lambda-exec-role` | Step 12 attaches the new observability policy to it, alongside `USMSLambdaBasic` |
| Lab 10 | `usms-student-data`, `transcripts/evidence/*` | Step 10 uploads an object to make the notifier run, which is what the metric filter is supposed to count |
| Lab 10 | `templates/lab-10-s3-event.json` | The synthetic event Step 10 falls back to when your build does not deliver S3 notifications |
| Lab 01 | `usms-ec2-app-role` | Also gets `USMSObservabilityWrite`, because the CloudWatch agent on an instance needs exactly these permissions |
| Lab 02 | `usms-vpc` | Named as a dashboard dimension and discussed in Section 12 as the thing you cannot get metrics from locally |

---

## 5. What We Are Building

One telemetry pipeline, in three layers, over the system you already have.

**The log layer.** A central log group that anything in USMS can write to, with a retention policy,
sitting alongside the two log groups the course created by accident. Structured lines, not prose,
because a log line that a machine can parse is worth ten that only a human can read.

**The metric layer.** Two metric filters that watch log groups and produce numbers, plus three custom
metrics published directly from code. Then alarms over those numbers: one that fires when transcript
processing falls behind, one that fires when the pipeline goes *silent* - which is the harder and
more important of the two - and a composite alarm that combines them so that one incident produces
one page instead of two.

**The trace layer.** X-Ray segments describing a transcript upload as it moves from S3 to the
notifier and on to the bucket read, with annotations you can search by and metadata you cannot, and
a sampling rule that decides how much of it you keep.

And on top, one dashboard, because the point of all of this is that a person can look at one page and
know whether the university's transcript system is working.

---

## 6. Architecture

```text
                         THE SYSTEM YOU ALREADY HAVE
   +-------------+   +------------------+   +-----------------+   +----------------+
   | usms-web-01 |   | usms-enrolment   |   | usms-student-   |   | usms-transcript|
   | usms-db-01  |   | -svc  (ECS)      |   | data (S3)       |   | -notifier:live |
   +------+------+   +---------+--------+   +--------+--------+   +--------+-------+
          |                    |                     |                     |
          | (conceptual:       | /usms/ecs/          | ObjectCreated       | print()
          |  CW agent)         |  enrolment          |                     |  stdout
          v                    v                     v                     v
   ==========================================================================
   ||                        LOG LAYER  (CloudWatch Logs)                  ||
   ||                                                                      ||
   ||  /usms/central/application     retention 30d   <-- NEW in this lab   ||
   ||  /usms/ecs/enrolment           retention 30d   <-- Lab 04, fixed    ||
   ||  /aws/lambda/usms-transcript-notifier  ret 14d <-- Lab 10, fixed     ||
   ==========================================================================
          |                                        |
          | metric filter                          | metric filter
          | usms-central-errors                    | usms-notify-count
          | pattern: ERROR                         | pattern: USMS_NOTIFY
          v                                        v
   ==========================================================================
   ||                    METRIC LAYER  (CloudWatch Metrics)                ||
   ||                                                                      ||
   ||  namespace USMS/Application                                          ||
   ||    CentralErrorCount      (from a filter)                            ||
   ||    NotifyCount            (from a filter)                            ||
   ||    TranscriptsProcessed   (put-metric-data)  dims: Faculty, Stage    ||
   ||    TranscriptLagSeconds   (put-metric-data)  dims: Stage             ||
   ||    EdgeDenyCount          (put-metric-data)  dims: Stage             ||
   ==========================================================================
          |                          |                         |
          v                          v                         v
   +--------------------+  +------------------------+  +--------------------+
   | usms-transcript-   |  | usms-notify-silence    |  |   usms-overview    |
   | lag-high           |  | missing data=breaching |  |   dashboard        |
   +---------+----------+  +-----------+------------+  +--------------------+
             |                         |
             +-----------+-------------+
                         v
            +---------------------------------+
            | usms-transcript-pipeline-down   |   COMPOSITE
            | rule: ALARM(a) OR ALARM(b)      |   one incident, one page
            +---------------------------------+
                         |
                         | (a future alerting lab attaches an SNS action here)
                         v
                    outputs/lab-13-alarm-actions-draft.json


                 THE TRACE LAYER, which is a different shape entirely

   trace_id 1-68ca4f31-1f2c3d4e5f60718293a4b5c6
     |
     +-- segment   usms-transcript-notifier        120 ms   annotations: faculty, stage
     |     |
     |     +-- subsegment  s3-head-object            18 ms   namespace: aws
     |     |
     |     +-- subsegment  render-pdf                74 ms   namespace: remote
     |
     +-- segment   usms-student-data                 18 ms   origin: AWS::S3::Bucket

   A metric says "eleven transcripts were slow".
   A trace says "THIS transcript was slow, and 74 of its 120 milliseconds were in render-pdf".
```

---

## 7. Directory Structure

What this lab adds. Nothing is restructured.

```text
aws-floci-course/
├── labs/lab-13-cloudwatch-xray/          # NEW
│   ├── README.md                         # this document
│   ├── exercises.md                      # Section 13
│   └── transcript-notifier-v2/
│       └── notifier.py                   # Step 13 - the instrumented handler
│
├── policies/
│   └── usms-observability-write-policy.json   # NEW - Step 12
│
├── templates/
│   ├── lab-13-metric-data.json           # Step 11
│   ├── lab-13-segment-parent.json        # Step 15
│   ├── lab-13-segment-subsegments.json   # Step 16
│   ├── lab-13-segment-downstream.json    # Step 16
│   ├── lab-13-sampling-rule.json         # Step 18
│   └── lab-13-dashboard.json             # Step 22
│
├── configs/
│   └── lab-13.env                        # Step 25
│
├── scripts/
│   ├── utilities/
│   │   ├── usms-emit-telemetry.sh        # Step 17
│   │   └── verify-lab-13.sh              # Section 9
│   └── cleanup/
│       └── lab-13-cleanup.sh             # Section 16 - DO NOT RUN NOW
│
├── project/                              # NEW TOP-LEVEL - see Appendix C
│   └── checkpoint-01/
│
└── outputs/                              # git-ignored
    ├── lab-13-support-probe.txt          ├── lab-13-trace-summaries.json
    ├── lab-13-telemetry-inventory.txt    ├── lab-13-service-graph.json
    ├── lab-13-filter-test.json           ├── lab-13-alarm-history.json
    ├── lab-13-metric-readback.json       ├── lab-13-alarm-actions-draft.json
    ├── lab-13-notifier-v2.zip            ├── lab-13-pre-restart.txt
    ├── lab-13-trace-ids.txt              ├── lab-13-post-restart.txt
    └── lab-13-alerting-readiness.txt        └── lab-13-assessment-c.md / -d.txt
```

One new **top-level** directory, `project/`, and it needs the one-sentence justification the course
contract asks for: the individual project assessed at Appendix C is a student deliverable rather than
a course artefact, and mixing it into `labs/` would put work that is marked individually inside a
tree that is identical for everyone.

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-13-cloudwatch-xray/transcript-notifier-v2 project/checkpoint-01
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs
labs/lab-09-eks  labs/lab-10-lambda-edge  labs/lab-13-cloudwatch-xray
```

> Your own `labs/` listing will include one directory per lab completed so far. The last entry is
> the one that matters here - this lab's own directory.

---
## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

### Step 1 - Start the environment and prove a new terminal can find it

**Purpose**

Everything after this assumes Floci is running with persistent storage and that your shell knows
where the course is. This lab writes time-stamped data - log events, metric data points, trace
segments - and time-stamped data is the kind that is most confusing to debug when the underlying
problem is that nothing is being stored at all.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/floci-storage-check.sh
```

**What the command does**

`floci-up.sh` starts the Compose project if it is not running and adopts it if it is. It is
idempotent. It refuses to adopt a container that was not started by Compose, which is the guard
against a stray `floci start` from a previous term.

`floci-storage-check.sh` is read-only. Its first block answers "can a new terminal find the course",
its second answers "will today's work survive tonight".

**Expected result**

```text
PASS=16  FAIL=0
```

> Example output - the lines above the total name your own paths and login shell.

**Verify**

Any failure in the first block is the real problem, and most failures below it are a consequence of
it. Fix the shell integration before continuing: Errata 01 Patch 1 is the step that installs it
properly.

---

### Step 2 - Source every lab environment file that exists, and confirm your identity

**Purpose**

This lab needs `USMS_BUCKET_NAME` and `USMS_ROLE_LAMBDA` from Lab 01, the notifier names from Lab 10,
and the ECS log group name from Lab 04. A loop that sources whatever is present and **reports what
it found** is more honest than a fixed list that assumes every earlier file exists and fails
opaquely the moment one does not.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
source configs/course.env

for f in configs/lab-01.env configs/lab-02.env configs/lab-03.env \
         configs/lab-04.env configs/lab-05.env configs/lab-06.env \
         configs/lab-07.env configs/lab-08.env configs/lab-09.env \
         configs/lab-10.env configs/lab-11.env configs/lab-12.env; do
  if [ -f "$f" ]; then
    # shellcheck disable=SC1090
    source "$f"
    printf '  sourced  %s\n' "$f"
  else
    printf '  absent   %s\n' "$f"
  fi
done

./scripts/utilities/whoami.sh
```

**What the command does**

The `for` loop is deliberately not `source configs/lab-*.env`. A glob would silently source a file
you did not intend and would give you no report of what it did. Naming the files makes the output a
statement about the state of your repository, and if you skipped or have not yet completed an earlier
lab, the honest `absent` line tells you so instead of failing opaquely.

**Expected result**

```text
  sourced  configs/lab-01.env
  sourced  configs/lab-02.env
  sourced  configs/lab-03.env
  sourced  configs/lab-04.env
  sourced  configs/lab-05.env
  sourced  configs/lab-06.env
  sourced  configs/lab-07.env
  sourced  configs/lab-08.env
  sourced  configs/lab-09.env
  sourced  configs/lab-10.env
  sourced  configs/lab-11.env
  sourced  configs/lab-12.env

Account : 000000000000
Identity: arn:aws:iam::000000000000:root
Endpoint: http://localhost:4566
```

> Example output - which files are actually present depends on how far through the course you are.
> There is no `configs/lab-NN.env` for the S3 configuration lab, because it has never been written.

**Verify**

```bash
printf 'bucket       : %s\n' "${USMS_BUCKET_NAME:-<UNSET>}"
printf 'notifier     : %s\n' "${USMS_LAMBDA_NOTIFIER_FN:-<UNSET>}"
printf 'notifier log : %s\n' "${USMS_LOG_GROUP_NOTIFIER:-<UNSET>}"
printf 'lambda role  : %s\n' "${USMS_ROLE_LAMBDA:-<UNSET>}"
printf 'account id   : %s\n' "${USMS_ACCOUNT_ID:-<UNSET>}"
```

**What to look for:** five populated values - `usms-student-data`, `usms-transcript-notifier`,
`/aws/lambda/usms-transcript-notifier`, `usms-lambda-exec-role` and `000000000000`. If
`USMS_LOG_GROUP_NOTIFIER` is unset, your `configs/lab-10.env` is incomplete; set it now with
`export USMS_LOG_GROUP_NOTIFIER=/aws/lambda/usms-transcript-notifier` and add the line to that file,
because Step 6 and Step 9 both read it.

---

### Step 3 - Create this lab's directories and confirm the repository shape

**Purpose**

One directory for the instrumented handler's source, one for the project checkpoint. Creating them
in one deliberate step means no later step fails on a missing parent directory, which is failure
mode number one from the course's teaching philosophy.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
mkdir -p labs/lab-13-cloudwatch-xray/transcript-notifier-v2 \
         project/checkpoint-01

ls -d labs/lab-13-cloudwatch-xray/*/ project/*/
```

**What the command does**

`mkdir -p` creates parents as needed and does not complain if the directory already exists, so this
step is safe to re-run.

`project/` is the one new top-level directory this lab adds, and Section 7 justified it. It is also
the only directory in this repository whose contents differ between students, which is worth
remembering when you read someone else's error message.

**Expected result**

```text
labs/lab-13-cloudwatch-xray/transcript-notifier-v2/
project/checkpoint-01/
```

**Verify**

```bash
test -d labs/lab-13-cloudwatch-xray/transcript-notifier-v2 && echo "source tree ready"
```

---

### Step 4 - Find out what this Floci build actually supports

**Purpose**

This lab depends on four API surfaces and they are supported to very different degrees. CloudWatch
Logs is usually good. CloudWatch metrics and alarms are usually stored but not *evaluated*. Logs
Insights is frequently absent. X-Ray varies more than any of them. Establishing which you have, in
writing, before you depend on it, is the rule this course is built on applied to a whole laboratory.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
probe() {   # $1 = label, $2 = command to try
  if eval "$2" >/dev/null 2>&1; then
    printf '  SUPPORTED    %s\n' "$1"
  else
    printf '  UNSUPPORTED  %s\n' "$1"
  fi
}

{
  printf 'Floci support probe for Lab 13 - %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  probe "logs       (describe-log-groups)"    "aws logs describe-log-groups --limit 1"
  probe "logs       (put-metric-filter API)"  "aws logs describe-metric-filters --limit 1"
  probe "logs       (Insights start-query)"   "aws logs describe-queries --max-results 1"
  probe "cloudwatch (list-metrics)"           "aws cloudwatch list-metrics --namespace AWS/Lambda"
  probe "cloudwatch (describe-alarms)"        "aws cloudwatch describe-alarms --max-records 1"
  probe "cloudwatch (list-dashboards)"        "aws cloudwatch list-dashboards"
  probe "xray       (get-sampling-rules)"     "aws xray get-sampling-rules"
  probe "xray       (get-service-graph)"      "aws xray get-service-graph --start-time $(date -u -d '-5 minutes' +%s 2>/dev/null || date -u -v-5M +%s) --end-time $(date -u +%s)"
  probe "lambda     (get-function-config)"    "aws lambda get-function-configuration --function-name ${USMS_LAMBDA_NOTIFIER_FN:-usms-transcript-notifier}"
} | tee outputs/lab-13-support-probe.txt
```

**What the command does**

`probe` runs a harmless read-only call and reports only whether it returned zero. It deliberately
does not print the error, because the errors differ between builds and the only decision this output
drives is which path a later step takes.

The X-Ray service-graph probe contains the lab's first portability problem, and it is worth reading
rather than copying. `date -u -d '-5 minutes' +%s` is GNU; `date -u -v-5M +%s` is BSD, which is what
macOS ships. Neither works on the other. The `||` between them picks whichever succeeds. From Step 7
onwards this lab stops doing arithmetic in `date` altogether and uses `python3`, for exactly this
reason.

**Expected result**

```text
Floci support probe for Lab 13 - 2026-09-17T03:41:22Z

  SUPPORTED    logs       (describe-log-groups)
  SUPPORTED    logs       (put-metric-filter API)
  UNSUPPORTED  logs       (Insights start-query)
  SUPPORTED    cloudwatch (list-metrics)
  SUPPORTED    cloudwatch (describe-alarms)
  SUPPORTED    cloudwatch (list-dashboards)
  SUPPORTED    xray       (get-sampling-rules)
  SUPPORTED    xray       (get-service-graph)
  SUPPORTED    lambda     (get-function-config)
```

> Example output - your Insights and X-Ray lines may differ. Both answers are normal and the lab
> handles both.

**What to look for:** the first two lines and the `cloudwatch` lines must say `SUPPORTED`. If
`describe-log-groups` says `UNSUPPORTED`, stop and read Section 11 - the rest of this lab cannot
proceed, and the cause is almost always that Floci is still starting.

The other two lines each decide a path:

| Probe | Consequence |
| --- | --- |
| Insights `UNSUPPORTED` | Step 23 takes the `filter-log-events` path instead of `start-query` |
| X-Ray `UNSUPPORTED` | Steps 15 to 18 validate segment documents structurally and record them, instead of sending them |

Either way nobody is left without a result, and in both cases the thing you are actually being
assessed on - the document you constructed and the reasoning behind it - is produced.

---

### Step 5 - Inventory the monitoring you already have and did not know about

**Purpose**

Before adding telemetry, look at what seven laboratories have already produced. This is not a warm-up:
two of the three log groups in your account were created by services rather than by you, and the
alarm Lab 06 created has been sitting there for two practicals. A monitoring lab that begins by
creating a log group teaches you that monitoring is something you add. It is mostly something you
*discover* and then organise.

**Run from**

```text
aws-floci-course/
```

**Concept first - the three things CloudWatch holds, and why they get confused**

| Object | What it is | Identified by | Created by |
| --- | --- | --- | --- |
| Log group | a named container of streams, with one retention policy | its name, e.g. `/aws/lambda/usms-transcript-notifier` | you, or the service, on first write |
| Log stream | an ordered sequence of events from one source | group + stream name | usually the service, per container or per instance |
| Log event | one timestamped message | nothing - it is data | your code |
| Metric | a named time series of numbers | namespace + name + **the full set of dimensions** | `put-metric-data`, a metric filter, or an AWS service |
| Alarm | a rule watching one metric (or several) and a state | its name | you |
| Dashboard | a JSON document describing widgets | its name | you |

The confusion that costs people hours is between the third row and the fourth. **Logs are text and
metrics are numbers, and nothing turns one into the other automatically.** A log line saying
`processed 14 transcripts` does not produce a metric of 14. Something has to extract it, and that
something is a metric filter, which is Step 9.

**Command**

```bash
{
  printf 'USMS telemetry inventory - %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  printf '== log groups ==\n'
  aws logs describe-log-groups \
    --query 'sort_by(logGroups, &logGroupName)[].[logGroupName,retentionInDays,storedBytes]' \
    --output text

  printf '\n== alarms ==\n'
  aws cloudwatch describe-alarms \
    --query 'MetricAlarms[].[AlarmName,Namespace,MetricName,StateValue]' \
    --output text

  printf '\n== metric namespaces already present ==\n'
  aws cloudwatch list-metrics \
    --query 'sort_by(Metrics, &Namespace)[].Namespace' --output text \
    | tr '\t' '\n' | sort -u

  printf '\n== dashboards ==\n'
  aws cloudwatch list-dashboards --query 'DashboardEntries[].DashboardName' --output text
} | tee outputs/lab-13-telemetry-inventory.txt
```

**What the command does**

`sort_by(logGroups, &logGroupName)` is the JMESPath sort you met in Lab 10 Step 22, applied here so
that two students comparing output see the same order.

`retentionInDays` is the field this step exists for. It is **absent** when no retention policy is
set, and `--output text` prints an absent field as `None`. That `None` is not a formatting quirk -
it is the finding.

`tr '\t' '\n' | sort -u` collapses the namespace list, because `list-metrics` returns one row per
metric and you want the set of namespaces, not the list.

**Expected result**

```text
USMS telemetry inventory - 2026-09-17T03:45:10Z

== log groups ==
/aws/lambda/usms-edge-origin-response	None	412
/aws/lambda/usms-edge-viewer-request	None	1043
/aws/lambda/usms-transcript-notifier	None	2871
/usms/ecs/enrolment	None	15204

== alarms ==
usms-enrolment-queue-high	USMS/Enrolment	QueueDepth	INSUFFICIENT_DATA

== metric namespaces already present ==
USMS/Enrolment

== dashboards ==

```

> Example output - your stored byte counts, and whether the edge function log groups exist at all,
> depend on whether your build delivered logs in Lab 10.

**What to look for**, in order of how much it should bother you:

1. **Every `retentionInDays` is `None`.** The default retention for a log group is *never expire*.
   On real AWS that is a bill that grows forever for data nobody will ever read, and it is the single
   most common avoidable CloudWatch cost. Step 6 fixes it.
2. **You have log groups you never created.** Lambda created three of them, by writing to them. The
   ECS one came from Lab 04's task definition.
3. **There is already an alarm**, from Lab 06, and its state is probably `INSUFFICIENT_DATA` -
   which is a state, not an error, and Step 19 explains why it is the state that matters most.
4. **There are no dashboards.** Nobody has ever had to look at this system.

!!! note "Floci Limitation - AWS-published metrics mostly do not exist here"
    On real AWS your account would already contain thousands of metrics in namespaces like
    `AWS/Lambda`, `AWS/ApplicationELB`, `AWS/ECS` and `AWS/EC2`, published by the services
    themselves at no charge and with no configuration.

    Floci publishes few or none of them. The namespace list above shows only what this course put
    there.

    The consequence shapes the whole lab: **every metric you alarm on here is one you publish
    yourself.** That is why Step 11 exists, and it is also why the technique is worth learning - a
    custom metric is the only kind that can measure something specific to your application, and
    `TranscriptsProcessed` is not a metric AWS could ever have published for you.

**Checkpoint 1**

```text
inventory taken
 ├── 4 log groups, none with a retention policy       ← Step 6 fixes this
 ├── 1 alarm, from Lab 06, INSUFFICIENT_DATA
 ├── 1 metric namespace, USMS/Enrolment
 └── 0 dashboards
outputs/lab-13-telemetry-inventory.txt                 ← keep; Appendix C asks for it
```

---

### Step 6 - Create the central log group and set retention on everything

**Purpose**

Give USMS one log group that application code can write to regardless of what is running it, and
then fix the finding from Step 5 on every group in the account.

**Run from**

```text
aws-floci-course/
```

**Concept first - how many log groups should a system have**

The two wrong answers are one and hundreds.

One log group for everything makes every query a search problem and forces one retention policy on
data with very different value. Hundreds - one per component - makes a cross-component question
require a query per component, and you will not run eleven queries at three in the morning.

The rule that works: **a log group is a unit of retention and access control, not a unit of
component.** Group together the things you would keep for the same length of time and let the same
people read. Within a group, distinguish sources by log **stream** and by a field inside the message.

For USMS that gives three:

| Log group | Holds | Retention | Why that number |
| --- | --- | --- | --- |
| `/usms/central/application` | application events from any compute tier | 30 days | long enough for "what happened last month", short enough to be cheap |
| `/usms/ecs/enrolment` | the enrolment service's container output | 30 days | same class of data, same answer |
| `/aws/lambda/usms-transcript-notifier` | one function's runtime output | 14 days | debugging data; if nobody looked in two weeks, nobody will |

A real university would add a fourth with a much longer retention for anything auditable - who read
which transcript - and would keep it under a separate policy so that developers can read the first
three and not the fourth. Exercise 4 asks you to design that.

**Command - part 1, create the central group**

```bash
CENTRAL_LOG_GROUP=/usms/central/application

aws logs describe-log-groups --log-group-name-prefix "$CENTRAL_LOG_GROUP" \
  --query 'length(logGroups)' --output text | grep -q '^0$' \
  && aws logs create-log-group --log-group-name "$CENTRAL_LOG_GROUP" \
  || echo "log group already exists - skipping create"

aws logs put-retention-policy \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --retention-in-days 30
```

**What the command does**

```text
aws
 └── logs                        the SERVICE - CloudWatch Logs, separate from `cloudwatch`
      ├── create-log-group       the OPERATION
      └── put-retention-policy   sets how long events in the group are kept
```

The first thing to notice is that `aws logs` and `aws cloudwatch` are **two different services** in
the CLI. Logs, log groups, metric filters and Insights queries are `aws logs`. Metrics, alarms and
dashboards are `aws cloudwatch`. They are presented as one product in the console and they are two
APIs underneath, and knowing that saves you searching the wrong help text.

The existence probe uses `length(logGroups)` and `grep -q` rather than `create-log-group ... || true`,
because a swallowed error hides real failures as readily as duplicate ones. `describe-log-groups`
with `--log-group-name-prefix` is a prefix match, not an exact one, which matters here only because
no other group starts with this string.

`--retention-in-days` accepts a fixed set of values - 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365,
400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653 - and rejects anything else. There is no 45.
The set looks arbitrary until you notice it is days, weeks, months, quarters and years.

**Command - part 2, fix every USMS log group**

```bash
NOTIFIER_LOG_GROUP="${USMS_LOG_GROUP_NOTIFIER:-/aws/lambda/usms-transcript-notifier}"

set_retention() {   # $1 = log group name, $2 = days
  if aws logs describe-log-groups --log-group-name-prefix "$1" \
       --query "logGroups[?logGroupName=='$1'] | length(@)" --output text | grep -q '^1$'; then
    aws logs put-retention-policy --log-group-name "$1" --retention-in-days "$2"
    printf '  set %4s days on %s\n' "$2" "$1"
  else
    printf '  absent, skipped   %s\n' "$1"
  fi
}

set_retention "$CENTRAL_LOG_GROUP"                 30
set_retention /usms/ecs/enrolment                  30
set_retention "$NOTIFIER_LOG_GROUP"                14
set_retention /aws/lambda/usms-edge-viewer-request 14
set_retention /aws/lambda/usms-edge-origin-response 14
```

**What the command does**

`logGroups[?logGroupName=='$1'] | length(@)` converts the prefix match into an exact one. The
`| length(@)` pipe applies `length` to the filtered result - you met the pipe in Lab 1 as
`... | [0]`, and this is the same operator with a function on the right.

`set_retention` is a function rather than five repeated command pairs because two of those five
groups may not exist on your build, and a loop that aborts on the first missing one would leave the
rest unset. Reporting `absent, skipped` is a result; a silent `|| true` is not.

**Expected result**

```text
  set   30 days on /usms/central/application
  set   30 days on /usms/ecs/enrolment
  set   14 days on /aws/lambda/usms-transcript-notifier
  set   14 days on /aws/lambda/usms-edge-viewer-request
  absent, skipped   /aws/lambda/usms-edge-origin-response
```

> Example output - which edge log groups exist depends on whether your build delivered Lambda logs
> in Lab 10.

**Verify**

```bash
aws logs describe-log-groups \
  --query 'sort_by(logGroups, &logGroupName)[].{Group:logGroupName,Days:retentionInDays}' \
  --output table
```

**What to look for:** no row shows `None` in the `Days` column for a group whose name starts
`/usms/` or `/aws/lambda/usms-`. A `None` on some other group is somebody else's problem; a `None`
on one of yours means `put-retention-policy` did not apply and Step 25's env file will record a
value you do not have.

!!! tip "Tagging a log group, if your build supports it"
    The course tags everything `Project=USMS`, and log groups are the one resource type where the
    call has changed. `aws logs tag-log-group` is deprecated in favour of `aws logs tag-resource`,
    which takes a log group **ARN**. Builds differ in which they implement, so probe rather than
    assume:

    ```bash
    LG_ARN=$(aws logs describe-log-groups --log-group-name-prefix "$CENTRAL_LOG_GROUP" \
      --query "logGroups[?logGroupName=='$CENTRAL_LOG_GROUP'].arn | [0]" --output text)

    aws logs tag-resource --resource-arn "$LG_ARN" --tags Project=USMS,Lab=08 2>/dev/null \
      || aws logs tag-log-group --log-group-name "$CENTRAL_LOG_GROUP" --tags Project=USMS,Lab=08 2>/dev/null \
      || echo "neither tagging call is available on this build - record it in the support probe"
    ```

    Nothing later in this lab depends on the tag. If both fail, append a line saying so to
    `outputs/lab-13-support-probe.txt` and move on.

**Checkpoint 2**

```text
LOG LAYER
 ├── /usms/central/application ................. NEW, retention 30d
 ├── /usms/ecs/enrolment ....................... Lab 04, retention 30d  (was never)
 ├── /aws/lambda/usms-transcript-notifier ...... Lab 10,  retention 14d  (was never)
 └── /aws/lambda/usms-edge-* ................... Lab 10,  retention 14d  (if present)
```

---

### Step 7 - Write log events, and get the timestamp units right

**Purpose**

A log group with no events in it cannot be searched, filtered or turned into a metric. This step puts
real events into the central group, and does it with the API call your application code would make -
which exists mainly so that you meet the two things about it that catch everyone.

**Run from**

```text
aws-floci-course/
```

**Concept first - structured logs, and why a marker string is an interface**

Two ways to log the same fact:

```text
Processed transcript for student 417 in the Science faculty, took 0.42 seconds
```

```text
USMS_EVENT {"event":"transcript.processed","student":"stu-00417","faculty":"science","seconds":0.42}
```

The first is nicer to read once. The second can be filtered on `faculty`, counted, averaged, alarmed
on and graphed, and it is still perfectly readable. The cost of the second is that you have to decide
your field names, which is work you were going to have to do anyway the first time somebody asked
"how many, by faculty".

The leading marker - `USMS_EVENT` here, `USMS_NOTIFY` in Lab 10's notifier - is there so that a
filter can find your lines among the runtime's own `START` / `END` / `REPORT` noise. In Lab 10 it
existed so that `grep` could find it. In Step 9 it becomes the pattern a metric filter matches, at
which point **it stops being a convenience and becomes an interface**: change the marker and the
metric silently goes to zero, with no error anywhere. Treat it like a function signature.

**Command**

```bash
STREAM="lab-13-$(date -u +%Y%m%d)"

aws logs create-log-stream \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --log-stream-name "$STREAM" 2>/dev/null \
  || echo "stream already exists - continuing"

NOW_MS=$(python3 -c 'import time; print(int(time.time()*1000))')

aws logs put-log-events \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --log-stream-name "$STREAM" \
  --log-events \
    timestamp=$((NOW_MS-4000)),message='USMS_EVENT {"event":"transcript.requested","student":"stu-00417","faculty":"science"}' \
    timestamp=$((NOW_MS-2000)),message='USMS_EVENT {"event":"transcript.processed","student":"stu-00417","faculty":"science","seconds":0.42}' \
    timestamp=$((NOW_MS-1000)),message='USMS_EVENT {"event":"transcript.processed","student":"stu-00982","faculty":"engineering","seconds":1.91}' \
    timestamp=$NOW_MS,message='ERROR USMS_EVENT {"event":"transcript.failed","student":"stu-01044","faculty":"science","reason":"render timeout"}' \
  --query 'rejectedLogEventsInfo' --output json
```

**What the command does**

**The timestamp is in milliseconds since the epoch, not seconds.** Pass seconds and every event you
send lands in January 1970, where it is silently outside the group's ingestion window and rejected.
This is the most common `put-log-events` mistake and the API does not help you: the value is a
number and 1789234567 is a perfectly valid number.

`python3 -c 'import time; print(int(time.time()*1000))'` is how this course gets that number.
`date +%s%3N` gives it on GNU coreutils and prints a literal `3N` on macOS, which then produces an
error about an invalid timestamp that names neither `date` nor your platform.

The events must be **in chronological order** within one call, which is why the offsets count
downwards from `NOW_MS`. They must also be within the ingestion window - roughly 14 days in the past
and 2 hours in the future - and events outside it are reported in `rejectedLogEventsInfo` rather than
raising an error.

`--query 'rejectedLogEventsInfo'` prints exactly that field, because **it is the field that tells you
whether the call did what you meant**. A successful `put-log-events` with every event rejected
returns HTTP 200. This is the course's founding rule in yet another costume.

The fourth message begins with `ERROR` before the marker. That is deliberate and Step 9's second
metric filter is about to match it.

!!! tip "If your build demands a sequence token"
    Real AWS stopped requiring `sequenceToken` on `PutLogEvents` in 2023 and now ignores it. Some
    Floci builds still enforce the old behaviour and fail with
    `InvalidSequenceTokenException`. If that happens, fetch the token and pass it:

    ```bash
    TOKEN=$(aws logs describe-log-streams --log-group-name "$CENTRAL_LOG_GROUP" \
      --log-stream-name-prefix "$STREAM" \
      --query 'logStreams[0].uploadSequenceToken' --output text)

    aws logs put-log-events --log-group-name "$CENTRAL_LOG_GROUP" \
      --log-stream-name "$STREAM" --sequence-token "$TOKEN" --log-events ...
    ```

    Record the substitution in `outputs/lab-13-support-probe.txt`.

**Expected result**

```text
null
```

> Example output - `null` means nothing was rejected, and it is the answer you want.

**Verify**

```bash
aws logs filter-log-events \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --query 'events[].[timestamp,message]' --output text
```

**What to look for:** four rows, in ascending timestamp order, with the JSON payloads intact. If you
see zero rows but the call returned `null`, the events are outside the query's default time window -
`filter-log-events` defaults to the whole retention period, so this should not happen, and if it does,
your timestamps are in seconds.

✏️ **Your turn**

Send a fifth event that a filter should **not** match, so that Step 9 has a negative case to prove
itself against.

Write one more event to the same stream whose message contains neither `USMS_EVENT` nor `ERROR` -
something like a plain health-check line - with a timestamp later than the four above.

```text
Expected result:
rejectedLogEventsInfo is null again.
filter-log-events now returns 5 rows.
Nothing in Step 9 will count this one, and that is the point of having sent it.
```

**Checkpoint 3**

```text
/usms/central/application
 └── stream lab-13-20260917
      ├── USMS_EVENT transcript.requested   stu-00417  science
      ├── USMS_EVENT transcript.processed   stu-00417  science      0.42s
      ├── USMS_EVENT transcript.processed   stu-00982  engineering  1.91s
      ├── ERROR USMS_EVENT transcript.failed stu-01044 science
      └── (your turn) one non-matching line
```

---

### Step 8 - Test a filter pattern before you deploy it

**Purpose**

A metric filter that does not match anything produces a metric that is always zero, an alarm that
never fires, and a dashboard that looks healthy. There is no error at any point. `test-metric-filter`
is the call that prevents this, and it is the most under-used API in CloudWatch.

**Run from**

```text
aws-floci-course/
```

**Concept first - filter pattern syntax, which is not a regular expression**

CloudWatch Logs filter patterns come in two dialects, and which one applies depends on the shape of
your log line.

**For unstructured text:**

| Pattern | Matches |
| --- | --- |
| `ERROR` | events containing the term `ERROR` |
| `"ERROR"` | the same, quoted - needed when the term has spaces or punctuation |
| `ERROR timeout` | events containing **both** terms |
| `?ERROR ?WARN` | events containing **either** |
| `ERROR -Test` | events containing `ERROR` and not `Test` |

Terms are matched against whitespace-delimited tokens and the match is **case-sensitive**. There is
no `.*`, no character class, no anchoring. It is not a regular expression and treating it as one is
the second most common way to build a filter that matches nothing.

**For JSON events** - a message that is a single JSON object - the dialect changes entirely:

| Pattern | Matches |
| --- | --- |
| `{ $.faculty = "science" }` | events whose JSON has `faculty` equal to `science` |
| `{ $.seconds > 1 }` | numeric comparison |
| `{ $.event = "transcript.*" }` | a trailing wildcard, the only one available |
| `{ ($.faculty = "science") && ($.seconds > 1) }` | both |

The catch, and it applies to your own log lines from Step 7: the JSON dialect requires the **whole
message** to be JSON. `USMS_EVENT {"event":...}` is not - it is a word followed by JSON - so it is
matched by the text dialect. That was a deliberate choice in this lab, because the marker makes the
line findable among runtime noise, and the cost is that you filter on the term rather than on the
fields. Exercise 2 asks you to weigh the alternative.

**Command**

```bash
aws logs test-metric-filter \
  --filter-pattern 'USMS_NOTIFY' \
  --log-event-messages \
    'USMS_NOTIFY {"bucket": "usms-student-data", "key": "transcripts/evidence/a.json", "readable": true}' \
    'usms-transcript-notifier: 1 record(s), channel=stdout, bucket_hint=usms-student-data' \
    'REPORT RequestId: 4c8e	Duration: 18.42 ms	Billed Duration: 19 ms' \
    'skipping non-transcript object: notes/ignore-me.json' \
  --query 'matches[].[eventNumber,eventMessage]' --output table \
  | tee outputs/lab-13-filter-test.json
```

**What the command does**

`test-metric-filter` takes a pattern and a list of sample messages and tells you which of them the
pattern would match. It touches no log group, creates nothing, and costs nothing. You can run it
before the log group exists.

The four sample messages are the four kinds of line Lab 10's notifier actually emits - its structured
marker line, its own summary line, the Lambda runtime's report line, and its skip message. That is
the point of the exercise: you are testing the pattern against the real population of lines, not
against one line you know matches.

`eventNumber` is the **1-based** index of the matching message in the list you supplied.

**Expected result**

```text
-----------------------------------------------------------------------------------
|                                TestMetricFilter                                  |
+-----+---------------------------------------------------------------------------+
|  1  |  USMS_NOTIFY {"bucket": "usms-student-data", "key": "transcripts/...       |
+-----+---------------------------------------------------------------------------+
```

> Example output - the message is truncated by the table width, not by the API.

**What to look for:** exactly one match, and it is number 1. If message 2 also matched, your pattern
was `usms` and would count the summary line as well, double-counting every invocation. If nothing
matched, check the case - `usms_notify` matches nothing, because these patterns are case-sensitive.

✏️ **Your turn**

Design the pattern for the *other* filter before Step 9 deploys it.

Using `test-metric-filter` only, find a pattern that matches the `ERROR` line you wrote in Step 7 and
does **not** match the three successful `USMS_EVENT` lines. Then check what your pattern does to a
line reading `USMS_EVENT {"event":"transcript.processed","reason":"no ERROR here"}` - a false
positive you will not have thought of.

```text
Expected result:
A pattern with exactly one match against your four Step 7 messages.
An honest note in labs/lab-13-cloudwatch-xray/exercises.md about what the
false-positive line did, and whether you would accept it in production.
```

---

### Step 9 - Deploy two metric filters

**Purpose**

Turn the two patterns into standing rules. From this step on, a log line matching one of them
produces a data point in a metric, without anybody calling `put-metric-data`.

**Run from**

```text
aws-floci-course/
```

**Concept first - what a metric filter actually costs you**

A metric filter is evaluated on **ingestion**, once per event, in the log group. That has three
consequences worth knowing before you create your fourth one.

It is not retroactive. A filter created today does not see yesterday's events, even though they are
sitting in the group. If you want a number for last week, you need Insights (Step 23), not a filter.

The metric it produces is a normal CloudWatch metric and is billed as one. A filter with a dimension
taken from a log field can produce a very large number of metrics - one per distinct value - and
this is the standard way people build a surprising bill. That is why neither filter below declares
dimensions.

And its `defaultValue` decides what *nothing* means. With `defaultValue=0`, a period with no matching
lines produces a data point of zero. Without it, that period produces **no data point at all**, and
the difference is the whole of Step 19: you cannot alarm on "it went quiet" if quiet is indistinguishable
from "nobody asked".

**Command**

```bash
aws logs put-metric-filter \
  --log-group-name "$NOTIFIER_LOG_GROUP" \
  --filter-name usms-notify-count \
  --filter-pattern 'USMS_NOTIFY' \
  --metric-transformations \
      metricName=NotifyCount,metricNamespace=USMS/Application,metricValue=1,defaultValue=0

aws logs put-metric-filter \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --filter-name usms-central-errors \
  --filter-pattern 'ERROR' \
  --metric-transformations \
      metricName=CentralErrorCount,metricNamespace=USMS/Application,metricValue=1,defaultValue=0
```

**What the command does**

```text
aws
 └── logs
      └── put-metric-filter
           ├── --log-group-name           which group is watched
           ├── --filter-name              the filter's name, unique within the group
           ├── --filter-pattern           what counts as a match (Step 8's dialect)
           └── --metric-transformations   what to publish when it matches
```

`--metric-transformations` is shorthand for a list of structures, and the four keys are worth
separating:

| Key | Meaning |
| --- | --- |
| `metricName` | the metric's name - `NotifyCount` |
| `metricNamespace` | the namespace, which is how you keep your metrics apart from AWS's |
| `metricValue` | what to publish per match. `1` counts events; `$1` or `$.field` publishes a value **extracted from the line** |
| `defaultValue` | what to publish for a period with no matches |

`metricValue=1` is a count. The alternative - extracting a number from the line - is the thing to
reach for when the log already contains the measurement: with a JSON line you would write
`metricValue='$.seconds'` and get a latency metric with no code change. Exercise 1 asks for that.

Both filters publish into the **same namespace**, `USMS/Application`, alongside the metrics Step 11
publishes directly. A namespace is a container and nothing more; metrics in it do not have to come
from the same source, and keeping one namespace per application rather than one per mechanism is what
makes a dashboard possible.

**Expected result**

Neither call prints anything on success.

**Verify**

```bash
aws logs describe-metric-filters \
  --query 'metricFilters[?starts_with(filterName, `usms-`)].[filterName,logGroupName,filterPattern,metricTransformations[0].metricName]' \
  --output table
```

**What to look for:** two rows, each pairing the right filter with the right log group. A filter
attached to the wrong group is the failure that is hardest to see afterwards, because both objects
exist and both look correct in isolation.

```text
-----------------------------------------------------------------------------------------------
|                                     DescribeMetricFilters                                    |
+----------------------+---------------------------------------+---------------+--------------+
|  usms-central-errors |  /usms/central/application            |  ERROR        | CentralErrorCount |
|  usms-notify-count   |  /aws/lambda/usms-transcript-notifier |  USMS_NOTIFY  | NotifyCount       |
+----------------------+---------------------------------------+---------------+--------------+
```

> Example output - column widths vary with your terminal.

**Checkpoint 4**

```text
METRIC FILTERS
 ├── usms-notify-count    on /aws/lambda/usms-transcript-notifier
 │     USMS_NOTIFY  →  USMS/Application NotifyCount        value 1, default 0
 └── usms-central-errors  on /usms/central/application
       ERROR        →  USMS/Application CentralErrorCount  value 1, default 0
```

---

### Step 10 - Prove the filter end to end

**Purpose**

Two filters exist. Nothing yet shows that a log line arriving produces a number coming out. This is
the lab's first **create → perturb → read back**: make the notifier run, then go and look for the
metric.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, perturb**

```bash
BUCKET="${USMS_BUCKET_NAME:-usms-student-data}"
NOTIFIER="${USMS_LAMBDA_NOTIFIER_FN:-usms-transcript-notifier}"

python3 -c "
import json, datetime
json.dump({'note': 'lab-13 telemetry probe',
           'created': datetime.datetime.now(datetime.timezone.utc).isoformat()},
          open('outputs/lab-13-probe-object.json','w'), indent=2)
"

aws s3api put-object \
  --bucket "$BUCKET" \
  --key transcripts/evidence/lab-13-probe-object.json \
  --body outputs/lab-13-probe-object.json \
  --content-type application/json \
  --query 'ETag' --output text

sleep 5

aws lambda invoke \
  --function-name "$NOTIFIER" \
  --qualifier live \
  --payload fileb://templates/lab-10-s3-event.json \
  --query 'FunctionError' --output text \
  outputs/lab-13-notifier-probe.json
```

**What the command does**

The upload is the real path: it matches Lab 10's notification filter - prefix `transcripts/`, suffix
`.json` - so on a build that delivers S3 events, this invokes the notifier and produces a
`USMS_NOTIFY` line.

The direct `invoke` immediately afterwards is **not** a fallback you take only when the upload fails.
It runs every time, deliberately, because the two together separate two questions: the upload proves
delivery works on your build, and the invocation proves the function and the filter work regardless.
If you only ran the upload and saw no metric, you would not know which of the three links was broken.

`templates/lab-10-s3-event.json` is the synthetic event Lab 10 Step 21 built. It is being reused
rather than rewritten, which is the point of having put it in `templates/`.

**Command - part 2, read back**

```bash
WINDOW=$(python3 -c "
import datetime
now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
start = now - datetime.timedelta(minutes=15)
print(start.strftime('%Y-%m-%dT%H:%M:%SZ'), now.strftime('%Y-%m-%dT%H:%M:%SZ'))
")
START=${WINDOW% *}
END=${WINDOW#* }

printf 'window: %s .. %s\n' "$START" "$END"

aws cloudwatch get-metric-statistics \
  --namespace USMS/Application \
  --metric-name NotifyCount \
  --start-time "$START" \
  --end-time "$END" \
  --period 60 \
  --statistics Sum SampleCount \
  --query 'sort_by(Datapoints, &Timestamp)[].[Timestamp,Sum,SampleCount]' \
  --output table \
  | tee outputs/lab-13-metric-readback.json
```

**What the command does**

The `python3` block builds both ends of the window in one process and prints them space-separated;
`${WINDOW% *}` and `${WINDOW#* }` split them. Two separate `date` invocations would have been shorter
and would have been the portability bug from Step 4 again.

`--period 60` asks for one-minute buckets. Period is not a display preference - it is the granularity
at which CloudWatch aggregates, it must be a multiple of 60, and asking for a period finer than the
data was published at gives you a graph full of gaps.

`--statistics Sum SampleCount` asks for two. For a counting metric, `Sum` is the number of matching
lines and `SampleCount` is the number of data points that went into the bucket. `Average` on a
counting metric is a number with no meaning, and reaching for it is a reliable sign that somebody has
not decided what their metric measures.

**Expected result**

```text
window: 2026-09-17T04:02:00Z .. 2026-09-17T04:17:00Z
-------------------------------------------------
|              GetMetricStatistics              |
+---------------------------+--------+----------+
|  2026-09-17T04:14:00Z     |  2.0   |   2.0    |
+---------------------------+--------+----------+
```

> Example output - your timestamp and counts will differ, and one or two data points are both normal
> depending on whether the upload also fired.

**What to look for:** at least one data point with a `Sum` of 1 or more. That number is a log line
that your code wrote, converted into a metric by a rule you deployed, and read back by a third API.
Three services, one fact, no code that knew about any of it.

!!! note "Floci Limitation - metric filters are often stored but not evaluated"
    This is the most likely place in the lab for your build to disappoint you. Many Floci builds
    accept `put-metric-filter`, return it faithfully from `describe-metric-filters`, and never run it
    against ingested events. `get-metric-statistics` then returns an empty `Datapoints` list.

    Real AWS evaluates every filter against every event at ingestion, within seconds, with no
    configuration beyond what you did in Step 9.

    **If your `Datapoints` list is empty, do this and continue:** publish the same metric by hand so
    that the rest of the lab has data to alarm on and graph, and record in
    `outputs/lab-13-support-probe.txt` that the value is synthetic.

    ```bash
    aws cloudwatch put-metric-data \
      --namespace USMS/Application \
      --metric-data MetricName=NotifyCount,Unit=Count,Value=2
    ```

    Then re-run the `get-metric-statistics` above. What you lose is the evidence that the *filter*
    works; what you keep is everything downstream of the metric. Say which of those two you have when
    you write up the lab - that distinction is worth marks in Section 14 and is the honest habit this
    course is trying to build.

✏️ **Your turn**

Show that `defaultValue` is doing something.

Pick a fifteen-minute window that ends **before** you uploaded anything today, ask for `NotifyCount`
over it with a period of 300, and compare the result to a window that includes the upload.

```text
Expected result:
Two answers that differ, and a one-sentence note in your exercises file saying what an
EMPTY Datapoints list means as against a list full of zeroes - and which of the two your
build actually produced.
```

**Checkpoint 5**

```text
PROVEN: log line → metric
 ├── object uploaded to transcripts/evidence/
 ├── notifier invoked through alias live
 ├── USMS_NOTIFY line written to /aws/lambda/usms-transcript-notifier
 └── USMS/Application NotifyCount has a data point       (or a recorded, honest substitute)
```

---
### Step 11 - Publish custom metrics, and meet dimensions

**Purpose**

A metric filter can only measure what your logs happen to say. A custom metric measures whatever you
decide to measure, and `TranscriptsProcessed by Faculty` is not something AWS could ever have
published for you. This step publishes three metrics and introduces the one CloudWatch concept that
is genuinely counter-intuitive.

**Run from**

```text
aws-floci-course/
```

**Concept first - a dimension is part of the name, not a label on it**

Every other monitoring system you may have met treats a label as an attribute of a measurement.
CloudWatch does not. A metric's identity is the **triple** of namespace, metric name and the
**complete set** of dimensions. Change any of them and it is a different metric.

```text
USMS/Application  TranscriptsProcessed  {Faculty=science}                  metric A
USMS/Application  TranscriptsProcessed  {Faculty=engineering}              metric B
USMS/Application  TranscriptsProcessed  {Faculty=science, Stage=render}    metric C  ← NOT a subset of A
USMS/Application  TranscriptsProcessed  {}                                 metric D  ← NOT the total
```

Two consequences, and the second one costs people real money.

**There is no automatic roll-up.** Metric D is not the sum of A and B. If you want a total you must
publish it, as its own data point with no dimensions, at the same time as the dimensioned ones. That
is why the command below publishes the same fact twice.

**Cardinality is cost.** Every distinct combination of dimension values is a separate metric, and
metrics are billed per metric. `Faculty` has perhaps eight values, so it is a good dimension.
`StudentId` has thirty thousand, so it is a catastrophic one - it would create thirty thousand
metrics, none of which anybody would ever graph. The rule: **a dimension is for a value you would
want a separate line on a graph for.** Anything with high cardinality belongs in a log field, where
you can search it, or in an X-Ray annotation, where you can filter traces by it. Both appear later in
this lab, and that is not a coincidence - this is the decision that determines which of the three
tools a piece of information belongs in.

**Command - part 1, the shorthand form**

```bash
aws cloudwatch put-metric-data \
  --namespace USMS/Application \
  --metric-data \
    'MetricName=TranscriptsProcessed,Unit=Count,Value=1,Dimensions=[{Name=Faculty,Value=science},{Name=Stage,Value=notify}]'

aws cloudwatch put-metric-data \
  --namespace USMS/Application \
  --metric-data 'MetricName=TranscriptsProcessed,Unit=Count,Value=1'
```

**What the command does**

`--metric-data` is a list of structures, and its shorthand syntax has a nested list of structures
inside it - `Dimensions=[{Name=...,Value=...},{...}]`. That is the deepest the CLI's shorthand goes
before it becomes unreadable, and it is a good moment to notice that Lambda's `--tags` took
`K=V,K2=V2`, S3's `--tagging` took `TagSet=[{Key=K,Value=V}]`, and this takes a third shape again.
Three services, three syntaxes for the same idea. When the shorthand stops being obvious, use
`file://` and a JSON document, which is what part 2 does.

The second call publishes the **same event** with no dimensions. It looks redundant and is not: it is
the total, and without it you cannot draw "all transcripts" on a graph.

**Command - part 2, the JSON form, with timestamps**

```bash
NOW_ISO=$(python3 -c "
import datetime
print(datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'))
")

cat > templates/lab-13-metric-data.json << EOF
[
  {
    "MetricName": "TranscriptsProcessed",
    "Timestamp": "${NOW_ISO}",
    "Unit": "Count",
    "Value": 3,
    "Dimensions": [
      { "Name": "Faculty", "Value": "engineering" },
      { "Name": "Stage",   "Value": "notify" }
    ]
  },
  {
    "MetricName": "TranscriptLagSeconds",
    "Timestamp": "${NOW_ISO}",
    "Unit": "Seconds",
    "Value": 0.42,
    "Dimensions": [
      { "Name": "Stage", "Value": "notify" }
    ]
  },
  {
    "MetricName": "TranscriptLagSeconds",
    "Timestamp": "${NOW_ISO}",
    "Unit": "Seconds",
    "Value": 1.91,
    "Dimensions": [
      { "Name": "Stage", "Value": "notify" }
    ]
  },
  {
    "MetricName": "EdgeDenyCount",
    "Timestamp": "${NOW_ISO}",
    "Unit": "Count",
    "Value": 1,
    "Dimensions": [
      { "Name": "Stage", "Value": "viewer-request" }
    ]
  }
]
EOF

python3 -m json.tool templates/lab-13-metric-data.json > /dev/null && echo "valid JSON"

aws cloudwatch put-metric-data \
  --namespace USMS/Application \
  --metric-data file://templates/lab-13-metric-data.json
```

**What the command does**

`<< EOF` - **unquoted**, because `${NOW_ISO}` must be substituted at write time. This is the first of
three unquoted heredocs in this lab; every other one is quoted. The rule, as ever: *do I want this
file to contain what I typed, or what it evaluates to?*

`Timestamp` is explicit here and was absent in part 1. Omitting it means "now", which is right for a
metric published as the event happens and wrong for one published by a batch job about something that
happened earlier. A data point can be backdated up to two weeks and postdated by two hours, with the
same silent-rejection behaviour as log events.

Two data points for `TranscriptLagSeconds` with the **same** name, dimensions and timestamp are not
a mistake. CloudWatch aggregates them: `SampleCount` will be 2, `Sum` 2.33, `Average` 1.165,
`Maximum` 1.91. This is how a latency metric is supposed to be published - every observation, not a
pre-averaged one - because an average of averages is not an average, and because the maximum is the
number that describes the student who waited.

`Unit` is not decoration. A metric published as `Count` and later as `Seconds` produces two separate
time series that look like one in a list and never overlay on a graph.

`EdgeDenyCount` has `Stage=viewer-request`, which names the Lab 10 function that produces the 403.
Nothing in Floci publishes it automatically; you are recording what your edge function would have
counted, and Section 12 lists it as such.

**Expected result**

```text
valid JSON
```

> Both `put-metric-data` calls print nothing on success. That is normal and it is also the reason the
> verify below exists.

**Verify**

```bash
aws cloudwatch list-metrics --namespace USMS/Application \
  --query 'sort_by(Metrics, &MetricName)[].[MetricName,join(`,`, Dimensions[].Name) || `(none)`]' \
  --output table

aws cloudwatch get-metric-statistics \
  --namespace USMS/Application \
  --metric-name TranscriptLagSeconds \
  --dimensions Name=Stage,Value=notify \
  --start-time "$START" --end-time "$END" \
  --period 300 \
  --statistics SampleCount Sum Average Maximum \
  --query 'Datapoints[0]' --output json
```

**What to look for:** `list-metrics` shows `TranscriptsProcessed` **twice** - once with dimensions
and once without - which is the concept made visible. And the statistics call returns
`SampleCount: 2.0` with `Maximum: 1.91`, proving that both observations were kept.

```text
{
    "Timestamp": "2026-09-17T04:15:00+00:00",
    "SampleCount": 2.0,
    "Sum": 2.33,
    "Average": 1.165,
    "Maximum": 1.91,
    "Unit": "Seconds"
}
```

> Example output - your timestamp will differ; the four statistics should not.

**What to look for if this returns nothing:** `--dimensions` must match the published set **exactly**.
Asking for `TranscriptLagSeconds` with no dimensions returns nothing at all, because that is a
different metric and you never published it. That is not a bug and it is the single most common
"CloudWatch has lost my metric" support question.

**Checkpoint 6**

```text
USMS/Application
 ├── NotifyCount                                        (metric filter, Step 9)
 ├── CentralErrorCount                                  (metric filter, Step 9)
 ├── TranscriptsProcessed  {Faculty, Stage}             (custom)
 ├── TranscriptsProcessed  {}                 ← the total, published separately
 ├── TranscriptLagSeconds  {Stage}            ← 2 observations in one period
 └── EdgeDenyCount         {Stage}
```

---

### Step 12 - Give the roles permission to emit telemetry

**Purpose**

`usms-lambda-exec-role` may write logs and read objects. It may not publish metrics and it may not
send traces. Step 14 turns on active tracing, and on real AWS a function whose role lacks
`xray:PutTraceSegments` produces no traces at all - with no error, because the failure is inside the
runtime's own telemetry path.

**Run from**

```text
aws-floci-course/
```

**Concept first - add a policy, do not edit one**

The obvious move is to add three actions to `USMSLambdaBasic`. Do not, for two reasons.

A customer managed policy is attached to principals, and editing it changes what **every** holder can
do. `USMSLambdaBasic` is on one role today; the policy you are about to write will end up on several.
Keeping "what a Lambda needs to run" and "what anything that emits telemetry needs" as separate
documents means the second can be attached to an EC2 role, an ECS task role and a future EKS
ServiceAccount without dragging `s3:GetObject` along with it.

And a managed policy holds at most **five versions**. Every edit is a new version, and version six
fails until you delete one. A policy you edit on every lab runs out; a policy per concern does not.

**Command - part 1, the policy document**

```bash
cat > policies/usms-observability-write-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteApplicationLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:000000000000:log-group:/usms/*:*",
        "arn:aws:logs:us-east-1:000000000000:log-group:/aws/lambda/usms-*:*"
      ]
    },
    {
      "Sid": "PublishCustomMetricsInOurNamespaceOnly",
      "Effect": "Allow",
      "Action": "cloudwatch:PutMetricData",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "cloudwatch:namespace": "USMS/Application"
        }
      }
    },
    {
      "Sid": "SendTraces",
      "Effect": "Allow",
      "Action": [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ],
      "Resource": "*"
    }
  ]
}
EOF

python3 -m json.tool policies/usms-observability-write-policy.json > /dev/null && echo "valid JSON"
```

**What the command does**

`<< 'EOF'` - **quoted**. This is a policy document and nothing in it should be expanded by the shell.
Note what would have happened otherwise: the document contains no `$`, so an unquoted heredoc would
appear to work. That is the trap Lab 10 Step 17 named. Quote it unless you specifically want
expansion.

Three statements, and each one is making a different point.

**The log statement is scoped by ARN and ends in `:*`.** A log group ARN is
`arn:aws:logs:<region>:<account>:log-group:<name>`, and the trailing `:*` covers the **streams**
inside the group. Leaving it off produces a policy that permits `CreateLogStream` on the group and
`PutLogEvents` on nothing, which fails at the second call. This is the single most common
hand-written IAM error involving CloudWatch Logs.

**The metric statement cannot be scoped by resource, so it is scoped by condition.**
`cloudwatch:PutMetricData` has no resource-level permissions - the only legal `Resource` is `*`. The
`cloudwatch:namespace` condition key is how you nevertheless confine it, and without it this
statement would permit writing into `AWS/Lambda` and corrupting metrics AWS publishes. A statement
whose `Resource` must be `*` is a statement that needs a condition.

**The X-Ray statement legitimately needs `*` and no condition.** There is no resource-level control
for sending a segment; a trace is not addressable until it exists. `GetSamplingRules` and
`GetSamplingTargets` are in the list because the X-Ray SDK fetches sampling decisions at runtime, and
a function that cannot read them falls back to a local default without telling you.

**Command - part 2, create and attach**

```bash
OBS_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSObservabilityWrite \
  --policy-document file://policies/usms-observability-write-policy.json \
  --description "Write logs to USMS groups, publish USMS/Application metrics, send X-Ray traces" \
  --query 'Policy.Arn' --output text 2>/dev/null \
  || aws iam list-policies --scope Local \
       --query "Policies[?PolicyName=='USMSObservabilityWrite'].Arn | [0]" --output text)

echo "$OBS_POLICY_ARN"

for role in "${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}" "${USMS_ROLE_EC2:-usms-ec2-app-role}"; do
  aws iam attach-role-policy --role-name "$role" --policy-arn "$OBS_POLICY_ARN" \
    && printf '  attached to %s\n' "$role"
done
```

**What the command does**

The `|| aws iam list-policies ...` branch makes the step idempotent: if the policy already exists,
`create-policy` fails with `EntityAlreadyExists` and the fallback looks up the ARN instead. Capturing
an ARN rather than typing one is the rule from Lab 1 Step 14 and it has not relaxed.

Both roles get it. `usms-ec2-app-role` has no immediate use for it, and that is deliberate - the
CloudWatch agent on `usms-web-01` would need exactly these three statements, and Section 12 lists
installing it as conceptual. Granting it now means the instance is ready and the grant is visible in
one place.

`attach-role-policy` is idempotent on real AWS and on most builds: attaching an already-attached
policy succeeds and changes nothing.

**Expected result**

```text
valid JSON
arn:aws:iam::000000000000:policy/USMSObservabilityWrite
  attached to usms-lambda-exec-role
  attached to usms-ec2-app-role
```

> Example output - the account is always `000000000000` in Floci.

**Verify**

```bash
aws iam list-attached-role-policies --role-name "${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}" \
  --query 'AttachedPolicies[].PolicyName' --output text

aws iam get-policy-version \
  --policy-arn "$OBS_POLICY_ARN" \
  --version-id "$(aws iam get-policy --policy-arn "$OBS_POLICY_ARN" \
                    --query 'Policy.DefaultVersionId' --output text)" \
  --query 'PolicyVersion.Document.Statement[].[Sid,Effect]' --output table
```

**What to look for:** `USMSLambdaBasic` **and** `USMSObservabilityWrite` on the role - the old one is
still there, which is the point of adding rather than editing - and three statements in the document.

!!! note "Floci Limitation - this permission is not enforced, and it still matters"
    Floci does not evaluate IAM against requests. Every call in this lab would succeed with no policy
    at all, and the tracing you turn on in Step 14 will behave identically whether or not this policy
    exists.

    Real AWS refuses `PutMetricData` into a namespace the condition excludes, and - worse, because it
    is silent - a Lambda function with active tracing and no `xray:PutTraceSegments` simply produces
    no traces. There is no error, no log line, and no indication in the X-Ray console other than an
    absence.

    Judge this policy by reading it. The verify above is the reading, and the two things worth
    checking by eye are the trailing `:*` on the log group ARNs and the presence of the
    `cloudwatch:namespace` condition.

**Checkpoint 7**

```text
USMSObservabilityWrite  (customer managed, v1)
 ├── logs:CreateLogStream / PutLogEvents / DescribeLogStreams  on /usms/* and /aws/lambda/usms-*
 ├── cloudwatch:PutMetricData  scoped by condition to namespace USMS/Application
 └── xray:PutTraceSegments / PutTelemetryRecords / GetSamplingRules / GetSamplingTargets
attached to
 ├── usms-lambda-exec-role   (alongside USMSLambdaBasic, not replacing it)
 └── usms-ec2-app-role       (alongside USMSStudentDataReadWrite)
```

---

### Step 13 - Instrument the notifier, and use an alias for what aliases are for

**Purpose**

Lab 10's notifier prints a marker line and returns. This version publishes a metric and emits a trace
id, which is what "instrumented" means in practice. Then you publish it as version 2 and repoint the
`live` alias - and every trigger that points at `...:live` starts using the new code without being
touched.

**Run from**

```text
aws-floci-course/
```

**Concept first - what changes and what deliberately does not**

Lab 10 Step 18 explained aliases with a diagram and then left `live` pointing at version 1 forever.
An explanation of a pointer that never moves is not an explanation. This is the step where it moves,
and the thing to watch is what you **do not** have to touch:

```text
usms-student-data  notification config  →  arn:...:function:usms-transcript-notifier:live
                                                                                      │
      before this step  live ──→ 1                                                    │
      after  this step  live ──→ 2                                          unchanged ┘
```

The bucket notification, the resource policy statement from Lab 10 Step 19, and anything else that
ever points at this function all name the alias. None of them is reconfigured. One `update-alias`
call is the deployment, and the same call in reverse is the rollback.

**Command - part 1, the instrumented handler**

```bash
cat > labs/lab-13-cloudwatch-xray/transcript-notifier-v2/notifier.py << 'EOF'
"""usms-transcript-notifier, version 2 - instrumented.

Adds to the Lab 10 handler, without removing anything it did:
  * a CloudWatch custom metric per processed transcript, in USMS/Application
  * a trace id on every log line, so a log and a trace can be joined
  * an explicit duration measurement, published as TranscriptLagSeconds

Stays inside USMSLambdaBasic + USMSObservabilityWrite (Lab 13 Step 12):
logs write, s3:GetObject, cloudwatch:PutMetricData in one namespace, xray:Put*.
"""

import json
import os
import time
import urllib.parse

BUCKET_HINT = os.environ.get("USMS_BUCKET", "usms-student-data")
CHANNEL = os.environ.get("USMS_NOTIFY_CHANNEL", "stdout")
NAMESPACE = os.environ.get("USMS_METRIC_NAMESPACE", "USMS/Application")
FACULTY_DEFAULT = os.environ.get("USMS_FACULTY_DEFAULT", "unknown")


def trace_id(context):
    """The trace id for this invocation.

    With active tracing, the Lambda runtime puts the header in _X_AMZN_TRACE_ID,
    shaped 'Root=1-...;Parent=...;Sampled=1'. Without it, the variable is absent
    and we fall back to the request id so that a log line is still correlatable.
    """
    header = os.environ.get("_X_AMZN_TRACE_ID", "")
    for part in header.split(";"):
        if part.startswith("Root="):
            return part[len("Root="):]
    return getattr(context, "aws_request_id", "no-trace")


def describe(record):
    """Pull the four fields that matter out of one S3 event record."""
    s3 = record.get("s3", {})
    raw_key = s3.get("object", {}).get("key", "")
    return {
        "event": record.get("eventName"),
        "bucket": s3.get("bucket", {}).get("name"),
        # S3 URL-encodes the key in the event: "stu+00417 final.json".
        "key": urllib.parse.unquote_plus(raw_key),
        "size": s3.get("object", {}).get("size"),
    }


def faculty_of(key):
    """transcripts/<faculty>/<file> -> <faculty>; anything else -> the default.

    Kept deliberately crude. A dimension value must come from a SMALL set, and
    deriving it from a path is how you accidentally get one metric per student.
    """
    parts = key.split("/")
    if len(parts) >= 3 and parts[0] == "transcripts":
        candidate = parts[1]
        if candidate.isalpha() and len(candidate) <= 20:
            return candidate.lower()
    return FACULTY_DEFAULT


def publish(metric, value, unit, dimensions):
    """Publish one data point. Never fail the invocation over telemetry."""
    try:
        import boto3
        boto3.client("cloudwatch").put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[{
                "MetricName": metric,
                "Value": value,
                "Unit": unit,
                "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
            }],
        )
        return True
    except Exception as exc:                          # noqa: BLE001
        print("USMS_METRIC_ERROR %s %s" % (metric, type(exc).__name__))
        return False


def notify(payload):
    """Where the results notification will eventually go.

    Today: a structured line on stdout, which CloudWatch Logs captures.
    Later: sns.publish(TopicArn=..., Message=json.dumps(payload)).
    """
    print("USMS_NOTIFY " + json.dumps(payload, sort_keys=True))


def handler(event, context):
    started = time.time()
    tid = trace_id(context)
    records = event.get("Records", [])

    print("usms-transcript-notifier v2: %d record(s), channel=%s, trace=%s"
          % (len(records), CHANNEL, tid))

    processed = []
    for record in records:
        info = describe(record)
        info["trace_id"] = tid

        if not info["key"].startswith("transcripts/"):
            print("skipping non-transcript object: %s" % info["key"])
            continue

        info["readable"] = False
        try:
            import boto3
            boto3.client("s3").head_object(Bucket=info["bucket"], Key=info["key"])
            info["readable"] = True
        except Exception as exc:                      # noqa: BLE001
            info["read_error"] = type(exc).__name__

        faculty = faculty_of(info["key"])
        info["faculty"] = faculty

        info["metric_published"] = publish(
            "TranscriptsProcessed", 1.0, "Count",
            {"Faculty": faculty, "Stage": "notify"})

        notify(info)
        processed.append(info["key"])

    elapsed = time.time() - started
    publish("TranscriptLagSeconds", elapsed, "Seconds", {"Stage": "notify"})

    print("USMS_SUMMARY " + json.dumps(
        {"processed": len(processed), "seconds": round(elapsed, 4), "trace_id": tid},
        sort_keys=True))

    return {"processed": len(processed), "keys": processed,
            "trace_id": tid, "seconds": round(elapsed, 4)}
EOF

python3 -m py_compile labs/lab-13-cloudwatch-xray/transcript-notifier-v2/notifier.py \
  && echo "syntax OK (python3)"
```

**What the command does**

`<< 'EOF'`, quoted, and here it is load-bearing rather than merely correct: the file contains
`%s`, `%d` and - critically - `"$"`-free but brace-heavy dictionary literals, and it contains
`os.environ.get(...)` calls whose default strings you want preserved exactly.

Three things in the handler are worth reading rather than skimming.

**`trace_id` reads `_X_AMZN_TRACE_ID`.** When active tracing is on, the Lambda runtime sets that
environment variable to a header of the form `Root=1-68ca4f31-...;Parent=...;Sampled=1`. Pulling the
`Root=` part out and printing it on every log line is what makes a log searchable **by trace** - it
is the join key between the two halves of this lab, and it costs three lines of code. The fallback to
`aws_request_id` means the line is still correlatable when tracing is off.

**Telemetry never fails the invocation.** `publish` catches everything and prints a marker instead.
A function that throws because CloudWatch was briefly unavailable has turned its monitoring into an
outage, which is a real failure mode with a real name.

**`faculty_of` is deliberately defensive.** It takes a value from a path - which is user-controlled -
and puts it in a metric dimension. Without the `isalpha()` and length guard, an object key of
`transcripts/<anything>/x.json` creates a new metric per distinct value, and an uploader could create
thousands. Step 11 said cardinality is cost; this is what defending against it looks like in code.

**Command - part 2, deploy, publish, repoint**

```bash
( cd labs/lab-13-cloudwatch-xray/transcript-notifier-v2 \
  && python3 -m zipfile -c "$COURSE_ROOT/outputs/lab-13-notifier-v2.zip" notifier.py )

python3 -m zipfile -l outputs/lab-13-notifier-v2.zip

aws lambda update-function-code \
  --function-name "$NOTIFIER" \
  --zip-file fileb://outputs/lab-13-notifier-v2.zip \
  --query '{Name:FunctionName,CodeSize:CodeSize,Version:Version}' --output table

aws lambda update-function-configuration \
  --function-name "$NOTIFIER" \
  --environment "Variables={USMS_BUCKET=$BUCKET,USMS_NOTIFY_CHANNEL=stdout,USMS_METRIC_NAMESPACE=USMS/Application,USMS_FACULTY_DEFAULT=unknown}" \
  --query 'Environment.Variables' --output json

aws lambda wait function-updated-v2 --function-name "$NOTIFIER" 2>/dev/null \
  || { echo "waiter unsupported - pausing instead"; sleep 5; }

NOTIFIER_V2=$(aws lambda publish-version \
  --function-name "$NOTIFIER" \
  --description "Lab 13 - instrumented: custom metrics and trace id" \
  --query 'Version' --output text)

aws lambda update-alias \
  --function-name "$NOTIFIER" \
  --name live \
  --function-version "$NOTIFIER_V2" \
  --query '{Alias:Name,Version:FunctionVersion}' --output table
```

**What the command does**

The subshell around `cd` is Lab 10 Step 8's lesson and the reason is unchanged: `python3 -m zipfile`
stores the entry under the path you give it, so building from the repository root would bury
`notifier.py` under four directories and produce `Cannot find module 'notifier'`. The parenthesis
returns you to where you were even if the command inside fails.

`update-function-code` changes `$LATEST` only. Version 1 is immutable and still contains Lab 10's
handler - which is what makes the rollback in the Your-turn below instantaneous rather than a rebuild.

`wait function-updated-v2` blocks until the update has been applied. Publishing a version while an
update is in flight gives you a version of the *old* code, silently. The `||` branch sleeps instead on
builds without the waiter, which is weaker and honest about being weaker.

`update-alias` is the deployment. One call, and every trigger follows.

**Expected result**

```text
File Name                                             Modified             Size
notifier.py                                    2026-09-17 04:31:08         4127

-----------------------------------
|       UpdateFunctionCode        |
+-----------+----------+----------+
|  CodeSize |   Name   | Version  |
+-----------+----------+----------+
|  4127     | usms-... | $LATEST  |
+-----------+----------+----------+

---------------------------
|       UpdateAlias       |
+---------+---------------+
|  Alias  |   Version     |
+---------+---------------+
|  live   |      2        |
+---------+---------------+
```

> Example output - your code size will differ and your version number may be higher if you published
> during Lab 10's Your-turn.

**Verify**

```bash
aws lambda get-function-configuration --function-name "$NOTIFIER" --qualifier live \
  --query '{Version:Version,Handler:Handler,Runtime:Runtime}' --output json

aws lambda invoke \
  --function-name "$NOTIFIER" --qualifier live \
  --payload fileb://templates/lab-10-s3-event.json \
  --log-type Tail --query 'LogResult' --output text \
  outputs/lab-13-notifier-v2-probe.json \
  | openssl base64 -d -A

python3 -m json.tool outputs/lab-13-notifier-v2-probe.json
```

**What to look for:** `Version` is `"2"`, the decoded log contains a `USMS_SUMMARY` line, and the
returned payload now has a `trace_id` and a `seconds` field that version 1 never produced.

`openssl base64 -d -A` rather than `base64 -d`, for the reason Lab 10 Step 10 gave: GNU uses `-d`,
BSD uses `-D`, and `openssl` behaves the same on both.

✏️ **Your turn**

Roll back, confirm, roll forward again.

Point `live` at version 1, invoke through the alias, and observe that the returned payload no longer
has a `trace_id` field. Then point it back at version 2. Do not delete any version.

```text
Expected result:
Two invocations of the SAME alias ARN returning two differently shaped payloads.
list-versions-by-function still shows $LATEST, 1 and 2 throughout.
One sentence in your exercises file on how long a real rollback of this deployment would take,
and how that compares to the Lambda@Edge rollback Lab 10 Step 11 described.
```

---

### Step 14 - Turn on active tracing

**Purpose**

The function now emits a trace id when the runtime gives it one. This step is what makes the runtime
give it one.

**Run from**

```text
aws-floci-course/
```

**Concept first - the three tracing modes, and who decides**

| `Mode` | Behaviour |
| --- | --- |
| `PassThrough` | the default. Trace only if the caller already decided to. The function does not start traces |
| `Active` | Lambda samples the invocation itself and starts a trace, whether or not the caller traced |
| (no config) | equivalent to `PassThrough` |

The distinction is about **who owns the sampling decision**. In a system where a request enters
through a front door you control - an API Gateway, a load balancer, a web app - you want that front
door to decide, once, and everything downstream to honour it with `PassThrough`, so that a traced
request is traced end to end and an untraced one costs nothing anywhere.

The notifier has no such front door. It is triggered by S3, and S3 does not carry your sampling
decision. So it has to decide for itself, which is `Active`.

Getting this backwards produces the most confusing X-Ray symptom there is: partial traces, where the
first two services appear and the third does not, with nothing wrong anywhere.

**Command**

```bash
aws lambda update-function-configuration \
  --function-name "$NOTIFIER" \
  --tracing-config Mode=Active \
  --query '{Name:FunctionName,Tracing:TracingConfig.Mode}' --output table

aws lambda wait function-updated-v2 --function-name "$NOTIFIER" 2>/dev/null \
  || { echo "waiter unsupported - pausing instead"; sleep 5; }

NOTIFIER_V3=$(aws lambda publish-version \
  --function-name "$NOTIFIER" \
  --description "Lab 13 - instrumented + active tracing" \
  --query 'Version' --output text)

aws lambda update-alias \
  --function-name "$NOTIFIER" --name live \
  --function-version "$NOTIFIER_V3" \
  --query 'FunctionVersion' --output text
```

**What the command does**

`--tracing-config Mode=Active` is shorthand for a one-key structure. It is a **configuration** change,
not a code change, which is exactly why it needs its own published version: Lab 10 Step 11 said a
version freezes code *and* configuration, and this is the first time in the course that the
distinction has had consequences. Version 2 has the instrumented code and no tracing. Version 3 has
both.

If you skipped the publish and left the alias on version 2, the function would still trace - because
`$LATEST` has the new configuration - but the version your trigger invokes would not. The alias is
the deployment, and the deployment includes configuration.

**Expected result**

```text
---------------------------------------------
|         UpdateFunctionConfiguration        |
+---------------------------+----------------+
|           Name            |    Tracing     |
+---------------------------+----------------+
|  usms-transcript-notifier |     Active     |
+---------------------------+----------------+
3
```

> Example output - your version number may differ.

**Verify**

```bash
aws lambda get-function-configuration --function-name "$NOTIFIER" --qualifier live \
  --query '{Version:Version,Tracing:TracingConfig.Mode}' --output json

aws iam list-attached-role-policies --role-name "${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}" \
  --query "AttachedPolicies[?PolicyName=='USMSObservabilityWrite'] | length(@)" --output text
```

**What to look for:** `Version: "3"` with `Tracing: "Active"`, and `1` from the second command. Those
two facts together are the whole precondition for tracing on real AWS, and the second one is the half
that fails silently.

!!! note "Floci Limitation - active tracing does not produce segments locally"
    Floci records `TracingConfig` faithfully and returns it. It does not run the X-Ray daemon inside
    the Lambda execution environment, so no segment is produced by an invocation and
    `_X_AMZN_TRACE_ID` may be absent - which is why Step 13's handler falls back to the request id
    rather than assuming the header is there.

    Real AWS starts a segment for every sampled invocation, names it after the function, records
    cold-start initialisation as a subsegment, and adds a subsegment automatically for every call an
    instrumented SDK makes.

    What you can do here is construct and send segments yourself, which is Steps 15 to 17 - and that
    is arguably the better way to learn the data model, because a segment produced by the SDK is a
    black box until you have built one by hand.

**Checkpoint 8**

```text
usms-transcript-notifier
 ├── $LATEST ................ instrumented code + Active tracing
 ├── 1 ...................... Lab 10 code, PassThrough        (rollback target)
 ├── 2 ...................... instrumented code, PassThrough
 ├── 3 ...................... instrumented code, Active
 └── live ──→ 3             ← S3's notification follows this, untouched since Lab 10
```

---

### Step 15 - The X-Ray data model, and your first segment

**Purpose**

Everything in X-Ray is a segment document. The service graph, the trace map, the latency
distribution and the error analytics are all derived from segments that something sent. This step
builds one by hand, which is the only way to understand what the SDK is doing on your behalf.

**Run from**

```text
aws-floci-course/
```

**Concept first - trace, segment, subsegment**

```text
TRACE            one request, end to end. Identified by a trace id.
 │               Not an object you create - it is the set of segments sharing an id.
 │
 ├── SEGMENT     one service's view of that request.
 │   │           Named after the SERVICE, not the operation. Has its own id.
 │   │
 │   ├── SUBSEGMENT   one unit of work inside that service:
 │   │                a downstream call, a function worth timing, a block of code.
 │   └── SUBSEGMENT
 │
 └── SEGMENT     the next service's view of the SAME request
```

The identifiers have fixed shapes and inventing your own is the fastest way to have a segment
rejected:

| Field | Shape | Example |
| --- | --- | --- |
| `trace_id` | `1-` + 8 hex digits of the epoch second + `-` + 24 hex digits of randomness | `1-68ca4f31-1f2c3d4e5f60718293a4b5c6` |
| `id` | 16 hex digits | `70de5b6f19ff9a0a` |
| `parent_id` | the `id` of the enclosing segment or subsegment | |
| `start_time`, `end_time` | epoch **seconds**, as a floating point number | `1789234567.123` |

Note the units. CloudWatch Logs took milliseconds as an integer; X-Ray takes seconds as a float.
There is no reason for this other than history, and knowing it is the difference between a trace that
appears and one that does not.

The eight-hex-digit timestamp inside the trace id is not decoration - X-Ray uses it to decide which
partition the trace lives in, and a trace id whose embedded time is more than about 30 days old is
rejected. You cannot back-fill traces.

**Annotations versus metadata**, which Step 17 uses and which is the other thing people get wrong:

| | Indexed | Searchable with a filter expression | Value types |
| --- | --- | --- | --- |
| `annotations` | yes | yes | string, number, boolean only |
| `metadata` | no | no | any JSON |

Annotations are limited in number and in type because each one is an index. Metadata is unlimited
because nothing looks at it until you open the trace. **Put in an annotation what you would want to
search a million traces by; put in metadata what you would want to read once you have found the one.**

**Command**

```bash
python3 - << 'PY' > templates/lab-13-segment-parent.json
import json, os, time

now = time.time()
trace_id = "1-%08x-%s" % (int(now), os.urandom(12).hex())
seg_id = os.urandom(8).hex()

segment = {
    "name": "usms-transcript-notifier",
    "id": seg_id,
    "trace_id": trace_id,
    "start_time": round(now - 0.120, 3),
    "end_time": round(now, 3),
    "origin": "AWS::Lambda::Function",
    "annotations": {
        "faculty": "science",
        "stage": "notify",
        "transcript_bytes": 2184,
        "readable": True
    },
    "metadata": {
        "usms": {
            "key": "transcripts/science/stu-00417.json",
            "bucket": "usms-student-data",
            "alias": "live",
            "handler": "notifier.handler"
        }
    }
}

print(json.dumps(segment, indent=2))
with open("outputs/lab-13-trace-ids.txt", "a") as fh:
    fh.write("%s %s parent\n" % (trace_id, seg_id))
PY

python3 -m json.tool templates/lab-13-segment-parent.json > /dev/null && echo "valid JSON"
tail -1 outputs/lab-13-trace-ids.txt
```

**What the command does**

`python3 - << 'PY' > file` runs an inline program and redirects its stdout into the file. The heredoc
is **quoted**, so nothing in the Python source is expanded by the shell - which matters here because
the program contains `%08x` and `%s`, and an unquoted heredoc would leave them alone but would also
be relying on luck.

`os.urandom(12).hex()` gives 24 hex characters and `os.urandom(8).hex()` gives 16. Doing this in the
shell with `$RANDOM` or `openssl rand` is possible and is another place where macOS and Linux differ;
`os.urandom` is the same everywhere Python is.

The ids are appended to `outputs/lab-13-trace-ids.txt` rather than only printed, because you will
need the trace id again in Step 16 and Step 17 and it is not derivable from anything.

The four annotations are all legal types - two strings, a number, a boolean. Putting a dictionary in
an annotation is rejected, and putting the student id there would be the X-Ray equivalent of the
cardinality mistake from Step 11, except that here it is legal and useful: **a high-cardinality value
is exactly right in an annotation and exactly wrong in a metric dimension.** That contrast is the
single most useful thing in this lab.

**Command - send it**

```bash
aws xray put-trace-segments \
  --trace-segment-documents "$(cat templates/lab-13-segment-parent.json)" \
  --query 'UnprocessedTraceSegments' --output json
```

**What the command does**

`--trace-segment-documents` takes a **list of JSON strings** - not JSON objects. The whole document
is passed as one string, which is why `"$(cat ...)"` is quoted: without the quotes the shell would
split it on whitespace into dozens of arguments, and the error would be about an unexpected
parameter rather than about quoting.

`--query 'UnprocessedTraceSegments'` prints the field that tells you whether the call did what you
meant. This is the third time in this lab that a successful call has had a rejection field - after
`rejectedLogEventsInfo` in Step 7 and the missing-dimension silence in Step 11 - and the pattern is
worth naming: **an API that accepts a batch reports per-item failure in the response body, not in the
exit code.**

**Expected result**

```text
[]
```

> Example output - an empty list means every segment was accepted.

**What to look for:** an empty list. A populated one names the segment id and a reason, and the
reasons are almost always a malformed `trace_id`, a missing `end_time`, or an `id` of the wrong
length.

!!! note "Floci Limitation - X-Ray support varies more than any other service in this course"
    Builds fall into three groups: full support, where everything in Steps 15 to 18 works; storage
    only, where `put-trace-segments` accepts documents but `get-trace-summaries` returns nothing; and
    absent, where the service does not answer at all.

    Real AWS indexes the segment within seconds, merges it with any other segment sharing the trace
    id, derives a service graph from the `origin` and the subsegment namespaces, and keeps it for 30
    days.

    Step 4 told you which group you are in. If `get-trace-summaries` returns an empty list in
    Step 16, validate the documents structurally instead - the validation script in Step 16 part 3
    is written for exactly that case - and record it. The document you construct is the assessable
    artefact either way.

---

### Step 16 - Subsegments, a downstream service, and reading a trace back

**Purpose**

One segment is a timing. A trace becomes useful when it has internal structure and more than one
service in it, because then it answers *where* rather than *how long*.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the same segment with subsegments**

```bash
TRACE_ID=$(awk 'END {print $1}' outputs/lab-13-trace-ids.txt)
PARENT_ID=$(awk 'END {print $2}' outputs/lab-13-trace-ids.txt)

printf 'trace  : %s\nparent : %s\n' "$TRACE_ID" "$PARENT_ID"

python3 - "$TRACE_ID" "$PARENT_ID" << 'PY' > templates/lab-13-segment-subsegments.json
import json, os, sys, time

trace_id, parent_id = sys.argv[1], sys.argv[2]
now = time.time()

def sub(name, offset, duration, namespace, extra=None):
    doc = {
        "id": os.urandom(8).hex(),
        "name": name,
        "start_time": round(now - offset, 3),
        "end_time": round(now - offset + duration, 3),
        "namespace": namespace,
    }
    if extra:
        doc.update(extra)
    return doc

segment = {
    "name": "usms-transcript-notifier",
    "id": parent_id,
    "trace_id": trace_id,
    "start_time": round(now - 0.120, 3),
    "end_time": round(now, 3),
    "origin": "AWS::Lambda::Function",
    "annotations": {
        "faculty": "science",
        "stage": "notify",
        "transcript_bytes": 2184,
        "readable": True,
    },
    "metadata": {
        "usms": {
            "key": "transcripts/science/stu-00417.json",
            "bucket": "usms-student-data",
            "alias": "live",
        }
    },
    "subsegments": [
        sub("s3-head-object", 0.118, 0.018, "aws", {
            "aws": {"operation": "HeadObject",
                    "bucket_name": "usms-student-data",
                    "region": "us-east-1"}}),
        sub("render-pdf", 0.098, 0.074, "remote", {
            "metadata": {"usms": {"pages": 3, "renderer": "wkhtmltopdf"}}}),
        sub("cloudwatch-put-metric-data", 0.022, 0.011, "aws", {
            "aws": {"operation": "PutMetricData"}}),
    ],
}

print(json.dumps(segment, indent=2))
PY

python3 -m json.tool templates/lab-13-segment-subsegments.json > /dev/null && echo "valid JSON"
```

**What the command does**

`awk 'END {print $1}'` reads the last line of the ids file and prints its first field. `tail -1 | cut`
would also work; `awk` does both in one process and behaves identically on macOS and Linux.

`python3 - "$TRACE_ID" "$PARENT_ID" << 'PY'` passes two shell values into the program as
`sys.argv[1]` and `sys.argv[2]` **without interpolating them into the source**. That is the pattern
Lab 10 Appendix B introduced, and the reason to prefer it is that an interpolated value that happens
to contain a quote produces a syntax error in a program you did not write.

Three subsegments, and the `namespace` field on each is doing real work:

| `namespace` | Meaning | Effect on the service graph |
| --- | --- | --- |
| `aws` | a call to an AWS service, described by the `aws` block | the service appears as its own node |
| `remote` | a call to something outside AWS | appears as a generic downstream node |
| omitted | internal work inside this service | no node; contributes to the parent's time |

`render-pdf` is marked `remote` and carries metadata rather than annotations, because the page count
is something you read when looking at one trace and never something you would search a million
traces by. The `s3-head-object` subsegment reuses the same id shape and describes the exact call the
Step 13 handler makes.

The segment **id is the same** as the one you sent in Step 15. Sending a segment with an id that
already exists updates it rather than creating a second one, which is how an in-progress segment is
later completed. That is worth knowing because the alternative reading - that you have just created
a duplicate - is the one people assume.

**Command - part 2, a second service in the same trace**

```bash
python3 - "$TRACE_ID" "$PARENT_ID" << 'PY' > templates/lab-13-segment-downstream.json
import json, os, sys, time

trace_id, parent_id = sys.argv[1], sys.argv[2]
now = time.time()

segment = {
    "name": "usms-student-data",
    "id": os.urandom(8).hex(),
    "trace_id": trace_id,
    "parent_id": parent_id,
    "type": "subsegment",
    "start_time": round(now - 0.118, 3),
    "end_time": round(now - 0.100, 3),
    "origin": "AWS::S3::Bucket",
    "http": {
        "request": {"method": "HEAD",
                    "url": "https://usms-student-data.s3.us-east-1.amazonaws.com/transcripts/science/stu-00417.json"},
        "response": {"status": 200, "content_length": 2184},
    },
    "annotations": {"faculty": "science", "stage": "origin"},
}

print(json.dumps(segment, indent=2))
PY

python3 -m json.tool templates/lab-13-segment-downstream.json > /dev/null && echo "valid JSON"

aws xray put-trace-segments \
  --trace-segment-documents \
    "$(cat templates/lab-13-segment-subsegments.json)" \
    "$(cat templates/lab-13-segment-downstream.json)" \
  --query 'UnprocessedTraceSegments' --output json
```

**What the command does**

The second document has `parent_id` and `"type": "subsegment"`. That combination is how a *separate*
service reports work that belongs inside a caller's segment - it is sent independently, by a
different process, and X-Ray stitches it into the trace using the shared `trace_id` and the
`parent_id`. This is exactly what happens when a real downstream service is instrumented, and it is
why a trace can be assembled from processes that never spoke to each other.

`--trace-segment-documents` here takes **two** strings. That is the list the parameter always wanted;
Step 15 simply passed a list of one.

The `http` block is a recognised structure rather than free-form metadata. X-Ray reads
`http.response.status` to classify a segment as ok, error (4xx), fault (5xx) or throttle (429), and
that classification is what colours the service map and drives the error analytics. Put a status in
metadata and none of that happens.

**Expected result**

```text
valid JSON
valid JSON
[]
```

**Command - part 3, read it back**

```bash
XW=$(python3 -c "
import datetime
now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
start = now - datetime.timedelta(minutes=15)
print(int(start.timestamp()), int(now.timestamp()))
")
XSTART=${XW% *}
XEND=${XW#* }

aws xray get-trace-summaries \
  --start-time "$XSTART" --end-time "$XEND" \
  --query 'TraceSummaries[].{Id:Id,Duration:Duration,Http:Http.HttpStatus,Annotations:keys(Annotations)}' \
  --output json | tee outputs/lab-13-trace-summaries.json

aws xray batch-get-traces --trace-ids "$TRACE_ID" \
  --query 'Traces[0].{Id:Id,Duration:Duration,Segments:length(Segments)}' \
  --output json
```

**What the command does**

`get-trace-summaries` is the search API: it takes a **time window**, not a trace id, and returns
summaries. `batch-get-traces` is the fetch API: it takes up to five trace ids and returns the full
segment documents. You search with the first and read with the second, and the split exists because
a summary is cheap and a full trace is not.

`keys(Annotations)` is a JMESPath function that returns an object's key names. It is new to the
course here, and it is the right tool when you want to know *which* annotations exist without
printing all their values.

**Expected result**

```text
[
    {
        "Id": "1-68ca4f31-1f2c3d4e5f60718293a4b5c6",
        "Duration": 0.12,
        "Http": null,
        "Annotations": [
            "faculty",
            "stage",
            "transcript_bytes",
            "readable"
        ]
    }
]
{
    "Id": "1-68ca4f31-1f2c3d4e5f60718293a4b5c6",
    "Duration": 0.12,
    "Segments": 2
}
```

> Example output - your trace id and duration will differ. `Segments: 2` is the number to look at.

**What to look for:** `Segments` is 2, meaning the two documents you sent independently were merged
into one trace. If `get-trace-summaries` returns an empty list but `batch-get-traces` returns the
trace, your build stores segments without indexing them - record it in the support probe and use
`batch-get-traces` for the rest of the lab.

**If both return nothing**, validate structurally instead and move on:

```bash
python3 - << 'PY' | tee outputs/lab-13-trace-summaries.json
import json, re, sys

checks, errors = [], []

def check(label, ok):
    checks.append(("ok  " if ok else "FAIL") + "  " + label)
    if not ok:
        errors.append(label)

docs = {name: json.load(open("templates/lab-13-segment-%s.json" % name))
        for name in ("parent", "subsegments", "downstream")}

tid = docs["parent"]["trace_id"]
check("trace id matches 1-<8hex>-<24hex>", bool(re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", tid)))
check("all three documents share one trace id",
      all(d["trace_id"] == tid for d in docs.values()))
check("every id is 16 hex characters",
      all(re.fullmatch(r"[0-9a-f]{16}", d["id"]) for d in docs.values()))
check("parent and subsegment documents share one segment id",
      docs["parent"]["id"] == docs["subsegments"]["id"])
check("downstream names the parent segment",
      docs["downstream"].get("parent_id") == docs["parent"]["id"])
check("every end_time is after its start_time",
      all(d["end_time"] > d["start_time"] for d in docs.values()))
check("three subsegments declared", len(docs["subsegments"]["subsegments"]) == 3)
check("every subsegment fits inside its parent's window",
      all(docs["subsegments"]["start_time"] <= s["start_time"]
          and s["end_time"] <= docs["subsegments"]["end_time"]
          for s in docs["subsegments"]["subsegments"]))
check("annotations hold only string, number or boolean",
      all(isinstance(v, (str, int, float, bool))
          for d in docs.values() for v in d.get("annotations", {}).values()))
check("downstream carries an http status", "status" in docs["downstream"]["http"]["response"])

print(json.dumps({"mode": "structural validation only - X-Ray not readable on this build",
                  "checks": checks, "errors": errors}, indent=2))
sys.exit(1 if errors else 0)
PY
```

**What to look for on this path:** ten `ok` entries and an empty `errors` list. That output is a real
result - it says the documents you would send to real X-Ray are well formed and internally
consistent, which is everything you can honestly claim without a service to send them to.

**Checkpoint 9**

```text
trace 1-68ca4f31-...
 ├── segment usms-transcript-notifier        120 ms   4 annotations
 │    ├── subsegment s3-head-object            18 ms  namespace aws
 │    ├── subsegment render-pdf                74 ms  namespace remote
 │    └── subsegment cloudwatch-put-metric...  11 ms  namespace aws
 └── segment usms-student-data                 18 ms  http 200, parent_id set
outputs/lab-13-trace-ids.txt        ← the ids, because they are not derivable
outputs/lab-13-trace-summaries.json ← read back, or structurally validated
```

---

### Step 17 - Search by annotation, read the service graph, and write the emitter

**Purpose**

Annotations exist to be searched and the service graph exists to be looked at. This step does both,
and then packages the whole of today's telemetry into one script, because a thing you can only do by
running twelve commands in order is a thing you will not do again.

**Run from**

```text
aws-floci-course/
```

**Concept first - filter expressions**

X-Ray's search language is small and worth knowing in full for the four forms you will actually use:

| Expression | Finds |
| --- | --- |
| `annotation.faculty = "science"` | traces annotated with that faculty |
| `annotation.transcript_bytes > 1000` | numeric comparison on an annotation |
| `service("usms-transcript-notifier")` | traces that touched that service |
| `responsetime > 1` | traces slower than a second |
| `service("usms-student-data") { fault }` | traces where **that specific service** faulted |

The last form is the one that justifies the whole trace layer. "Show me requests where the bucket
failed but the function did not" is a question no log search can answer, because no single log line
knows about both.

**Command - part 1, search**

```bash
aws xray get-trace-summaries \
  --start-time "$XSTART" --end-time "$XEND" \
  --filter-expression 'annotation.faculty = "science"' \
  --query 'length(TraceSummaries)' --output text \
  || echo "filter expressions unsupported on this build"

aws xray get-trace-summaries \
  --start-time "$XSTART" --end-time "$XEND" \
  --filter-expression 'annotation.faculty = "engineering"' \
  --query 'length(TraceSummaries)' --output text \
  || echo "filter expressions unsupported on this build"
```

**What to look for:** `1` and then `0`. The second call is the one that proves the first: a search
that returns everything regardless of the expression is not filtering, and you would not have noticed
without asking for something that should not match.

**Command - part 2, the service graph**

```bash
aws xray get-service-graph \
  --start-time "$XSTART" --end-time "$XEND" \
  --query 'Services[].{Name:Name,Type:Type,Edges:length(Edges),Ok:SummaryStatistics.OkCount}' \
  --output table | tee outputs/lab-13-service-graph.json
```

**What the command does**

The service graph is **derived**, not stored. X-Ray builds it by walking every trace in the window
and connecting segments to the subsegments that called them. You never declare an edge; the edge
exists because a subsegment with `namespace: aws` named a downstream service inside a segment.

That is why Step 16's `namespace` field mattered, and it is why an uninstrumented service appears as
a dead end on the map rather than as a missing node - the caller reported the call, so the node
exists, but nothing reported what happened inside it.

**Expected result**

```text
---------------------------------------------------------------
|                      GetServiceGraph                        |
+----------------------------+---------------------+----+-----+
|  usms-transcript-notifier  |  AWS::Lambda::Function |  1 |  1 |
|  usms-student-data         |  AWS::S3::Bucket       |  0 |  1 |
+----------------------------+---------------------+----+-----+
```

> Example output - many builds return an empty `Services` list even when segments were accepted. If
> yours does, note it in the support probe; the graph is derived data and its absence does not
> invalidate the segments.

**Command - part 3, one script that emits all three signals**

```bash
cat > scripts/utilities/usms-emit-telemetry.sh << 'EOF'
#!/usr/bin/env bash
# Emit one of each USMS telemetry signal - a log event, a metric data point and
# a trace - describing the same fictional transcript, so that the three can be
# joined afterwards by trace id.
#
# Usage:  usms-emit-telemetry.sh [faculty] [seconds]
# Writes: appends to outputs/lab-13-trace-ids.txt
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-13.env" 2>/dev/null || true

FACULTY="${1:-science}"
SECONDS_TAKEN="${2:-0.42}"
GROUP="${USMS_LOG_GROUP_CENTRAL:-/usms/central/application}"
NAMESPACE="${USMS_METRIC_NAMESPACE:-USMS/Application}"
STREAM="emitter-$(date -u +%Y%m%d)"

IDS=$(python3 -c "
import os, time
now = time.time()
print('1-%08x-%s' % (int(now), os.urandom(12).hex()), os.urandom(8).hex(), int(now*1000), now)
")
TRACE_ID=$(printf '%s' "$IDS" | awk '{print $1}')
SEG_ID=$(printf '%s'  "$IDS" | awk '{print $2}')
NOW_MS=$(printf '%s' "$IDS" | awk '{print $3}')
NOW_S=$(printf '%s'  "$IDS" | awk '{print $4}')

aws logs create-log-stream --log-group-name "$GROUP" --log-stream-name "$STREAM" 2>/dev/null || true

aws logs put-log-events \
  --log-group-name "$GROUP" --log-stream-name "$STREAM" \
  --log-events "timestamp=$NOW_MS,message=USMS_EVENT {\"event\":\"transcript.processed\",\"faculty\":\"$FACULTY\",\"seconds\":$SECONDS_TAKEN,\"trace_id\":\"$TRACE_ID\"}" \
  --query 'rejectedLogEventsInfo' --output json >/dev/null \
  && echo "  log     ok   $GROUP"

aws cloudwatch put-metric-data \
  --namespace "$NAMESPACE" \
  --metric-data "MetricName=TranscriptsProcessed,Unit=Count,Value=1,Dimensions=[{Name=Faculty,Value=$FACULTY},{Name=Stage,Value=notify}]" \
                "MetricName=TranscriptLagSeconds,Unit=Seconds,Value=$SECONDS_TAKEN,Dimensions=[{Name=Stage,Value=notify}]" \
  && echo "  metric  ok   $NAMESPACE"

SEGMENT=$(python3 - "$TRACE_ID" "$SEG_ID" "$NOW_S" "$FACULTY" "$SECONDS_TAKEN" << 'PY'
import json, sys
trace_id, seg_id, now, faculty, secs = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], float(sys.argv[5])
print(json.dumps({
    "name": "usms-transcript-notifier",
    "id": seg_id,
    "trace_id": trace_id,
    "start_time": round(now - secs, 3),
    "end_time": round(now, 3),
    "origin": "AWS::Lambda::Function",
    "annotations": {"faculty": faculty, "stage": "notify", "emitted_by": "usms-emit-telemetry"},
}))
PY
)

if aws xray put-trace-segments --trace-segment-documents "$SEGMENT" \
     --query 'UnprocessedTraceSegments' --output text >/dev/null 2>&1; then
  echo "  trace   ok   $TRACE_ID"
else
  echo "  trace   SKIPPED (X-Ray unavailable on this build) $TRACE_ID"
fi

printf '%s %s emitter/%s\n' "$TRACE_ID" "$SEG_ID" "$FACULTY" >> outputs/lab-13-trace-ids.txt
echo
echo "trace id: $TRACE_ID"
EOF

chmod +x scripts/utilities/usms-emit-telemetry.sh
bash -n scripts/utilities/usms-emit-telemetry.sh && echo "syntax OK"

./scripts/utilities/usms-emit-telemetry.sh science 0.51
./scripts/utilities/usms-emit-telemetry.sh engineering 2.40
./scripts/utilities/usms-emit-telemetry.sh engineering 3.10
```

**What the command does**

`<< 'EOF'` for the outer heredoc, because the script contains `$1`, `${BASH_SOURCE[0]}` and several
`$(...)` expressions that must survive into the file and run when the script runs. The inner
`<< 'PY'` is quoted for the same reason.

`REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"` resolves the repository root from
the script's own location, which is the course's standing rule.

`source "$REPO_ROOT/configs/lab-13.env" 2>/dev/null || true` - that file does not exist yet; Step 25
creates it. The `|| true` under `set -u` plus the `${VAR:-default}` fallbacks mean the script works
before and after that step.

One `python3` call produces all four values - trace id, segment id, epoch milliseconds and epoch
seconds - because they must describe the same instant. Four separate calls would drift by
milliseconds, which does not matter here and would matter if you were computing a duration from them.

The three invocations at the end give you data to alarm on: two engineering transcripts over two
seconds, which is what Step 19's threshold is chosen against.

**Expected result**

```text
syntax OK
  log     ok   /usms/central/application
  metric  ok   USMS/Application
  trace   ok   1-68ca5107-8b3e1d02f7a94c56e1d0b3a7

trace id: 1-68ca5107-8b3e1d02f7a94c56e1d0b3a7
...
```

> Example output - three blocks, one per invocation. A `trace SKIPPED` line is expected on a build
> without X-Ray and does not stop the script.

**Verify**

```bash
wc -l < outputs/lab-13-trace-ids.txt
aws logs filter-log-events --log-group-name "$CENTRAL_LOG_GROUP" \
  --filter-pattern 'USMS_EVENT' \
  --query 'length(events)' --output text
```

**What to look for:** four lines in the ids file - one from Step 15 and three from the emitter - and
a log event count that has grown by three. The number that matters is that the **same trace id**
appears in the log line, in the ids file and in the segment. That is the join, and it is the reason
the script emits all three signals in one place rather than leaving you to correlate by timestamp.

**Checkpoint 10**

```text
scripts/utilities/usms-emit-telemetry.sh
 ├── one USMS_EVENT log line carrying trace_id
 ├── two metric data points  (TranscriptsProcessed, TranscriptLagSeconds)
 └── one X-Ray segment with the SAME trace id     (or an honest SKIPPED line)
run 3 times: science 0.51, engineering 2.40, engineering 3.10
```

---

### Step 18 - Decide what gets traced at all

**Purpose**

Tracing every request is affordable at university scale and ruinous at internet scale. A sampling
rule is how you decide, centrally, without redeploying anything.

**Run from**

```text
aws-floci-course/
```

**Concept first - reservoir plus rate, and why both**

A sampling rule has two numbers:

| Field | Meaning |
| --- | --- |
| `ReservoirSize` | trace this many requests **per second**, guaranteed |
| `FixedRate` | then trace this fraction of everything above the reservoir |

The reservoir exists because a pure percentage fails at low volume. At 5 percent and two requests a
minute, you get a trace every ten minutes and none at all during the incident you care about. The
reservoir guarantees a floor; the rate stops the ceiling from scaling with traffic.

`Priority` decides which rule wins when several match - **lower number, higher priority** - and every
account has a `Default` rule at priority 10000 that you cannot delete, typically one per second plus
5 percent. Your rules go above it in priority and below it in number.

**Command**

```bash
aws xray get-sampling-rules \
  --query 'SamplingRuleRecords[].SamplingRule.{Name:RuleName,Priority:Priority,Rate:FixedRate,Reservoir:ReservoirSize,Service:ServiceName}' \
  --output table

cat > templates/lab-13-sampling-rule.json << 'EOF'
{
  "RuleName": "usms-transcripts-sampling",
  "ResourceARN": "*",
  "Priority": 1000,
  "FixedRate": 0.10,
  "ReservoirSize": 2,
  "ServiceName": "usms-transcript-notifier",
  "ServiceType": "*",
  "Host": "*",
  "HTTPMethod": "*",
  "URLPath": "*",
  "Version": 1
}
EOF

python3 -m json.tool templates/lab-13-sampling-rule.json > /dev/null && echo "valid JSON"

aws xray create-sampling-rule \
  --sampling-rule file://templates/lab-13-sampling-rule.json \
  --query 'SamplingRuleRecord.SamplingRule.{Name:RuleName,Priority:Priority,Rate:FixedRate,Reservoir:ReservoirSize}' \
  --output table \
  || echo "create-sampling-rule unsupported on this build - the document above is the deliverable"
```

**What the command does**

Every field in that document is **required**, including the four that are `*`. There is no partial
rule: X-Ray matches on service name, service type, host, HTTP method, URL path and resource ARN
together, and a field you do not care about is expressed as `*` rather than omitted. Leaving one out
produces a validation error naming the field, which is one of the friendlier AWS errors.

`"Version": 1` is the schema version of the rule document and is not something you increment.

`Priority: 1000` puts this rule ahead of the default at 10000. `FixedRate: 0.10` with
`ReservoirSize: 2` reads as: always trace the first two transcript notifications each second, then
trace one in ten of the rest.

**Expected result**

```text
-------------------------------------------------------------------
|                       GetSamplingRules                          |
+----------+-----------+--------+------------+-------------------+
|  Default |   10000   |  0.05  |     1      |         *         |
+----------+-----------+--------+------------+-------------------+
valid JSON
-------------------------------------------------------------------
|                      CreateSamplingRule                         |
+----------------------------+----------+--------+---------------+
|  usms-transcripts-sampling |   1000   |  0.1   |       2       |
+----------------------------+----------+--------+---------------+
```

> Example output - your build's `Default` rule may have different numbers, and may be absent.

**Verify**

```bash
aws xray get-sampling-rules \
  --query "SamplingRuleRecords[?SamplingRule.RuleName=='usms-transcripts-sampling'].SamplingRule.[RuleName,Priority,FixedRate,ReservoirSize]" \
  --output text \
  || echo "not retrievable - validate the document instead"
```

**What to look for:** one row with priority 1000. If the create call failed, the JSON document is
still the assessable artefact, and Section 14 asks for the document rather than for the rule.

!!! note "Floci Limitation - sampling is never applied"
    Floci stores sampling rules where it supports the API at all, and nothing consumes them. There is
    no SDK in this lab fetching sampling targets, and the segments you send are sent unconditionally.

    Real AWS has each instrumented process poll `GetSamplingRules` every few minutes and
    `GetSamplingTargets` every ten seconds, so that a rule change takes effect fleet-wide within
    seconds and without a deployment. That is the actual value of the feature: sampling is a runtime
    decision, not a build-time one.

    Take away the reservoir-plus-rate reasoning and the priority ordering. Both are checkable by
    reading the document, which is what the verify above does.

---
### Step 19 - Create two alarms, one of which watches for an absence

**Purpose**

A metric nobody looks at is a graph. An alarm is a metric with an opinion. This step creates two of
them, and the second is the more valuable and the more often forgotten.

**Run from**

```text
aws-floci-course/
```

**Concept first - the three states, and the one everybody misconfigures**

An alarm is always in exactly one of three states:

| State | Meaning |
| --- | --- |
| `OK` | the metric was evaluated and the condition was not met |
| `ALARM` | the metric was evaluated and the condition was met |
| `INSUFFICIENT_DATA` | there was not enough data to decide |

The third is not an error. It is the state a new alarm starts in, and it is the state Lab 06's
`usms-enrolment-queue-high` has been sitting in since Practical 4 - as Step 5 showed you.

`--treat-missing-data` decides what a gap means, and it has four settings:

| Setting | A period with no data is treated as |
| --- | --- |
| `missing` | the default - the period is ignored, and the alarm keeps its current state |
| `notBreaching` | good |
| `breaching` | bad |
| `ignore` | the alarm does not change state at all |

Now the design question this lab is really about. `TranscriptLagSeconds` has no data when nothing is
being processed, and nothing being processed at 3am is normal - so missing data there should be
`notBreaching`.

`NotifyCount` has no data when nothing is being processed *either*, but for that metric the absence
**is the problem**: the pipeline going silent is precisely the failure that a threshold on a value
can never detect. An alarm on "value too high" is invisible when the value stops arriving. So its
missing-data setting is `breaching`, and it is deliberately the opposite of its neighbour's.

**The rule to keep:** every threshold alarm you write has a blind spot, and the blind spot is
silence. Most production incidents where monitoring "did not fire" are this.

**Command - part 1, the threshold alarm**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name usms-transcript-lag-high \
  --alarm-description "Transcript notification latency above 2s for 2 of 3 minutes" \
  --namespace USMS/Application \
  --metric-name TranscriptLagSeconds \
  --dimensions Name=Stage,Value=notify \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 2 \
  --threshold 2 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --unit Seconds \
  --tags Key=Project,Value=USMS Key=Lab,Value=08
```

**What the command does**

```text
aws
 └── cloudwatch                the SERVICE - metrics, alarms, dashboards
      └── put-metric-alarm     creates OR replaces. There is no update-alarm
```

`put-metric-alarm` is a replace, like every `put-*` you have met. Re-running it with one flag changed
gives you the changed alarm, not a second one - and omitting a flag you set last time removes that
setting. Same category as `update-assume-role-policy` and `put-bucket-notification-configuration`
from Lab 10.

Five flags decide when it fires, and they are worth separating because people reach for the wrong one:

| Flag | Decides |
| --- | --- |
| `--period 60` | how wide each evaluation bucket is |
| `--statistic Maximum` | how the data points inside a bucket become one number |
| `--evaluation-periods 3` | how many buckets are examined |
| `--datapoints-to-alarm 2` | how many of those must breach |
| `--threshold 2` with `--comparison-operator` | what breaching means |

`2 out of 3` rather than `3 out of 3` is the standard shape and the reason is noise: a single slow
transcript should not page anybody, and a persistent problem will breach two buckets within three
minutes. Requiring all three delays detection; requiring one guarantees false alarms.

`--statistic Maximum` rather than `Average` is the deliberate choice for a latency alarm. An average
of 40 transcripts hides the one student who waited nine seconds, and that student is the incident.

`--unit Seconds` must match the unit the data was published with, or the alarm evaluates against no
data forever and sits in `INSUFFICIENT_DATA` looking perfectly healthy. This is a genuinely nasty
one, because nothing about the alarm looks wrong.

**Command - part 2, the absence alarm**

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name usms-notify-silence \
  --alarm-description "No transcript notifications for 15 minutes - the pipeline has gone quiet" \
  --namespace USMS/Application \
  --metric-name NotifyCount \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 3 \
  --datapoints-to-alarm 3 \
  --threshold 1 \
  --comparison-operator LessThanThreshold \
  --treat-missing-data breaching \
  --tags Key=Project,Value=USMS Key=Lab,Value=08
```

**What the command does**

`LessThanThreshold` with a threshold of `1` on a `Sum`: fewer than one notification in a five-minute
bucket. Combined with `breaching`, a bucket with no data at all also counts. Three consecutive
buckets is fifteen minutes of silence.

No `--dimensions`. `NotifyCount` comes from a metric filter, and Step 9 deliberately gave that filter
no dimensions - so the metric's identity is namespace plus name plus the empty set, and asking for it
with a dimension would match nothing. Look back at Step 11's diagram if that sentence did not land;
it is the same fact in a different place.

No `--unit` either, because the metric filter published none. Specifying `Unit=Count` here would be
asking for a metric that does not exist.

Fifteen minutes is a judgement, not a fact. It should be longer than the quietest legitimate gap and
shorter than how long you are willing to be broken. At a university, transcripts are quiet all night,
so a real version of this alarm would either be suppressed outside working hours or would watch a
longer window - and Exercise 4 asks you to argue for one.

**Expected result**

Neither call prints anything on success.

**Verify**

```bash
aws cloudwatch describe-alarms \
  --alarm-names usms-transcript-lag-high usms-notify-silence \
  --query 'MetricAlarms[].{Name:AlarmName,Metric:MetricName,Stat:Statistic,Th:Threshold,Op:ComparisonOperator,Missing:TreatMissingData,State:StateValue}' \
  --output table
```

**What to look for:** two rows, with `Missing` reading `notBreaching` and `breaching` respectively.
That difference is the whole point of the step, and it is visible in one column.

```text
-------------------------------------------------------------------------------------------------------
|                                           DescribeAlarms                                             |
+---------------------------+----------------------+---------+-----+----------------------+-----+------+
|  usms-transcript-lag-high |  TranscriptLagSeconds | Maximum | 2.0 | GreaterThanThreshold | notBreaching | OK |
|  usms-notify-silence      |  NotifyCount          | Sum     | 1.0 | LessThanThreshold    | breaching    | INSUFFICIENT_DATA |
+---------------------------+----------------------+---------+-----+----------------------+-----+------+
```

> Example output - the `State` column depends on whether your build evaluates alarms at all, and
> `INSUFFICIENT_DATA` for both is the most likely answer. Step 20 is where that stops mattering.

---

### Step 20 - Prove the alarms, by making one fire

**Purpose**

An alarm you have never seen change state is not a tested alarm. It is a configuration you believe
in. This is the lab's second **create → perturb → read back**, and it is the one that matters most,
because on real AWS the day you find out an alarm does not work is the day you needed it.

**Run from**

```text
aws-floci-course/
```

**Concept first - `set-alarm-state` is a test harness, not a cheat**

`aws cloudwatch set-alarm-state` forces an alarm into a state you choose, with a reason you supply.
It does not change the metric, and CloudWatch will re-evaluate on the next period and move the alarm
back to whatever the data says.

On real AWS it is how you test the thing that happens *after* the alarm - the notification, the
runbook link, the auto-scaling action, the person's phone at three in the morning. Waiting for a real
breach to find out that your SNS topic has no subscribers is not a testing strategy.

Here it does something extra: it is the only way to observe a state transition at all, because Floci
does not evaluate alarms against metric data on a schedule. What you are proving is that the alarm
exists, is addressable, transitions, and records its history - and Section 12 is explicit that the
*evaluation* is the part you have not proven.

**Command - part 1, force the transition**

```bash
aws cloudwatch set-alarm-state \
  --alarm-name usms-transcript-lag-high \
  --state-value ALARM \
  --state-reason "Lab 13 Step 20: forced transition to prove the alarm is wired and records history" \
  --state-reason-data '{"lab":"08","step":20,"synthetic":true}'

sleep 2

aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason,Since:StateUpdatedTimestamp}' \
  --output json
```

**What the command does**

`--state-reason` is free text and appears in the notification a human eventually reads. Writing
"test" there and then forgetting is how an on-call engineer at 3am spends ten minutes establishing
that nothing is wrong. Say what you did and why, in the reason, every time.

`--state-reason-data` is JSON and is machine-readable. On a real alarm evaluation CloudWatch fills it
with the data points it used and the threshold it applied, which is what lets an automated responder
decide whether to act. Marking this one `"synthetic": true` means a responder could tell.

**Command - part 2, read the history**

```bash
aws cloudwatch describe-alarm-history \
  --alarm-name usms-transcript-lag-high \
  --history-item-type StateUpdate \
  --max-records 5 \
  --query 'sort_by(AlarmHistoryItems, &Timestamp)[].[Timestamp,HistorySummary]' \
  --output table \
  | tee outputs/lab-13-alarm-history.json
```

**What the command does**

`--history-item-type StateUpdate` filters to state changes. The other values are
`ConfigurationUpdate` - which records every `put-metric-alarm`, including your first one - and
`Action`, which records notifications sent. Asking for all three at once is how you answer "did
somebody change this alarm just before it stopped firing", which is a question you will one day want.

Alarm history is kept for **two weeks** and cannot be extended. If you need a longer record of
incidents, it has to be captured elsewhere - which is a genuine architectural constraint and not an
oversight.

**Expected result**

```text
{
    "State": "ALARM",
    "Reason": "Lab 13 Step 20: forced transition to prove the alarm is wired and records history",
    "Since": "2026-09-17T04:58:11.204000+00:00"
}
-----------------------------------------------------------------------------------------
|                                 DescribeAlarmHistory                                   |
+---------------------------------+------------------------------------------------------+
|  2026-09-17T04:52:03.118000+00:00 |  Alarm "usms-transcript-lag-high" created            |
|  2026-09-17T04:58:11.204000+00:00 |  Alarm updated from INSUFFICIENT_DATA to ALARM       |
+---------------------------------+------------------------------------------------------+
```

> Example output - your timestamps will differ, and the exact wording of `HistorySummary` varies
> between builds.

**What to look for:** a row whose summary contains `to ALARM`. That single line is the proof. An
alarm that exists but cannot transition would have produced the first row and not the second, and
`describe-alarms` alone would never have told you the difference.

**Command - part 3, put it back**

```bash
aws cloudwatch set-alarm-state \
  --alarm-name usms-transcript-lag-high \
  --state-value OK \
  --state-reason "Lab 13 Step 20: restoring state after the forced-transition proof"

aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high \
  --query 'MetricAlarms[0].StateValue' --output text
```

**What to look for:** `OK`. Leaving an alarm stuck in `ALARM` would mean the composite alarm in
Step 21 is permanently firing, and Section 9's verification would pass for the wrong reason.

!!! note "Floci Limitation - alarms are stored and transitioned, never evaluated"
    Floci records alarm configuration, accepts `set-alarm-state`, and keeps history. It does not run
    the evaluation engine, so your alarms will not move on their own no matter what the metric does.
    Most builds also implement no alarm **actions**: `--alarm-actions` is accepted and nothing is
    ever invoked.

    Real AWS evaluates every alarm once per period, transitions it, writes history and invokes every
    configured action - SNS topics, auto-scaling policies, EC2 actions, Systems Manager incidents.
    That evaluation is the product.

    So the honest claim from this step is: the alarm is correctly configured, addressable, and
    transitions and records history. Whether the *threshold* is right is a claim you can only support
    by reading the configuration against the metric's actual distribution - which is Exercise 3.

**Checkpoint 11**

```text
ALARMS
 ├── usms-transcript-lag-high   TranscriptLagSeconds Max > 2, 2 of 3 × 60s, missing=notBreaching
 │     └── PROVEN: INSUFFICIENT_DATA → ALARM → OK, with history recorded
 └── usms-notify-silence        NotifyCount Sum < 1, 3 of 3 × 300s, missing=BREACHING
       └── watches for an absence, which no threshold on a value can do
outputs/lab-13-alarm-history.json
```

---

### Step 21 - Combine them into one incident

**Purpose**

Two alarms for one pipeline means two notifications for one outage, at three in the morning, to the
same person. A composite alarm is the fix, and it is the first CloudWatch object in this lab that
watches other alarms rather than a metric.

**Run from**

```text
aws-floci-course/
```

**Concept first - what a composite alarm is for**

```text
usms-transcript-lag-high  ──┐
                            ├──→ usms-transcript-pipeline-down   ← the one that notifies
usms-notify-silence     ────┘
```

The rule language has four functions - `ALARM`, `OK`, `INSUFFICIENT_DATA` and `TRUE`/`FALSE` - and
the boolean operators `AND`, `OR` and `NOT`. That is the whole language.

Two uses worth knowing:

**Aggregation**, which is the case here: one incident, one page. The two child alarms keep their own
notifications turned off and the composite carries the action.

**Suppression**, which is the more sophisticated one: `ALARM(service-down) AND NOT ALARM(deployment-in-progress)`
stops a deploy from paging anybody, and `NOT ALARM(upstream-down)` stops a failing dependency from
paging every team that depends on it. A composite alarm's `--actions-suppressor` field formalises
this, and it is the answer to "our monitoring pages us forty times for one outage".

**Command**

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name usms-transcript-pipeline-down \
  --alarm-description "The USMS transcript pipeline is failing or silent. One incident, one page." \
  --alarm-rule 'ALARM("usms-transcript-lag-high") OR ALARM("usms-notify-silence")' \
  --actions-enabled \
  --tags Key=Project,Value=USMS Key=Lab,Value=08
```

**What the command does**

`--alarm-rule` is a single string, in **single** quotes, containing **double** quotes around each
alarm name. Both are required: the double quotes are part of the rule syntax, and the single quotes
stop your shell from removing them. Getting this wrong produces a parse error from CloudWatch that
names a position in a string you did not think you had written.

`--actions-enabled` is the default and is written out here because it is the flag that distinguishes
the composite from its children. In a real deployment you would now go back and set
`--no-actions-enabled` on both child alarms, so that only the composite notifies. Lab 09 is where
that becomes meaningful once a future alerting lab gives it an action to disable.

There is no `--alarm-actions` here yet, for the same reason: there is no SNS topic in this course.
Step 25's exercise writes the draft that a future alerting lab would apply.

**Expected result**

Nothing on success.

**Verify**

```bash
aws cloudwatch describe-alarms --alarm-types CompositeAlarm \
  --query 'CompositeAlarms[].{Name:AlarmName,Rule:AlarmRule,State:StateValue}' --output json

aws cloudwatch set-alarm-state \
  --alarm-name usms-notify-silence \
  --state-value ALARM \
  --state-reason "Lab 13 Step 21: driving a child alarm to observe the composite"

sleep 3

aws cloudwatch describe-alarms --alarm-names usms-transcript-pipeline-down \
  --alarm-types CompositeAlarm \
  --query 'CompositeAlarms[0].{State:StateValue,Reason:StateReason}' --output json

aws cloudwatch set-alarm-state \
  --alarm-name usms-notify-silence \
  --state-value OK \
  --state-reason "Lab 13 Step 21: restoring state"
```

**What the command does**

`--alarm-types CompositeAlarm` is required: `describe-alarms` returns metric alarms by default and a
composite alarm will simply not appear without it. That is a five-minute confusion that this flag
prevents.

The middle three commands are the same create → perturb → read back shape as Step 20, one level up.
Driving a **child** into `ALARM` should drive the **parent** into `ALARM` without anybody touching
the parent.

**What to look for:** the rule string comes back exactly as you wrote it, and - on a build that
evaluates composites - the parent's state follows the child's. If the parent stays
`INSUFFICIENT_DATA`, your build stores composite alarms without evaluating their rules; note it in
the support probe and read the rule instead. The rule is the artefact.

!!! danger "Read before running any delete command"
    **What will be deleted:** the two metric alarms and the composite alarm this lab created, if you
    run the cleanup script in Section 16.

    **What depends on it:** a future alerting lab (not yet written) attaches SNS actions to
    `usms-transcript-lag-high`, `usms-notify-silence` and `usms-transcript-pipeline-down` by name.

    **Reversible?** Yes - re-run Steps 19 and 21. Alarm **history** is not reversible and would be
    lost, and two weeks is all there ever was.

    **Effect on later labs:** a future alerting lab would have nothing to attach an action to and
    would have to create the alarms itself, which is not what it is about.

    Do not run the cleanup script now. Section 16 has it, marked.

---

### Step 22 - Build the dashboard

**Purpose**

Everything so far is queryable. None of it is *visible*. A dashboard is the object that makes
"is the transcript system healthy" a question somebody can answer in four seconds without knowing
any of the API calls in this lab.

**Run from**

```text
aws-floci-course/
```

**Concept first - a dashboard is a JSON document, and widgets have a grid**

There is no dashboard builder API. `put-dashboard` takes a JSON body describing widgets and their
positions, and the console is a renderer for that document. Which means a dashboard is a text file,
belongs in version control, and can be generated - and that is how mature teams manage them.

The grid is **24 columns wide** and unlimited in height. Each widget declares `x`, `y`, `width` and
`height` in grid units. Two widgets that overlap are a document error rather than a layout that
resolves itself.

Widget types worth knowing:

| `type` | Shows |
| --- | --- |
| `metric` | a time series, a single number, or a gauge, depending on `view` |
| `log` | the results of a Logs Insights query |
| `text` | markdown - for the runbook link that turns a graph into a usable page |
| `alarm` | the state of one or more alarms |

**Command**

```bash
cat > templates/lab-13-dashboard.json << 'EOF'
{
  "widgets": [
    {
      "type": "text",
      "x": 0, "y": 0, "width": 24, "height": 2,
      "properties": {
        "markdown": "# USMS - transcript delivery\nOwner: platform team · Runbook: notes/lab-13-runbook.md · Alarms page the composite alarm only."
      }
    },
    {
      "type": "metric",
      "x": 0, "y": 2, "width": 12, "height": 6,
      "properties": {
        "title": "Transcripts processed, by faculty",
        "region": "us-east-1",
        "stat": "Sum",
        "period": 300,
        "view": "timeSeries",
        "stacked": false,
        "metrics": [
          [ "USMS/Application", "TranscriptsProcessed", "Faculty", "science", "Stage", "notify" ],
          [ "USMS/Application", "TranscriptsProcessed", "Faculty", "engineering", "Stage", "notify" ]
        ]
      }
    },
    {
      "type": "metric",
      "x": 12, "y": 2, "width": 12, "height": 6,
      "properties": {
        "title": "Notification latency - max and average",
        "region": "us-east-1",
        "period": 60,
        "view": "timeSeries",
        "metrics": [
          [ "USMS/Application", "TranscriptLagSeconds", "Stage", "notify", { "stat": "Maximum", "label": "max" } ],
          [ "USMS/Application", "TranscriptLagSeconds", "Stage", "notify", { "stat": "Average", "label": "avg" } ]
        ],
        "annotations": {
          "horizontal": [
            { "label": "alarm threshold", "value": 2 }
          ]
        }
      }
    },
    {
      "type": "metric",
      "x": 0, "y": 8, "width": 8, "height": 4,
      "properties": {
        "title": "Notifications in the last 5 minutes",
        "region": "us-east-1",
        "stat": "Sum",
        "period": 300,
        "view": "singleValue",
        "metrics": [
          [ "USMS/Application", "NotifyCount" ],
          [ "USMS/Application", "CentralErrorCount" ]
        ]
      }
    },
    {
      "type": "alarm",
      "x": 8, "y": 8, "width": 16, "height": 4,
      "properties": {
        "title": "Pipeline alarms",
        "alarms": [
          "arn:aws:cloudwatch:us-east-1:000000000000:alarm:usms-transcript-pipeline-down",
          "arn:aws:cloudwatch:us-east-1:000000000000:alarm:usms-transcript-lag-high",
          "arn:aws:cloudwatch:us-east-1:000000000000:alarm:usms-notify-silence"
        ]
      }
    }
  ]
}
EOF

python3 -m json.tool templates/lab-13-dashboard.json > /dev/null && echo "valid JSON"

aws cloudwatch put-dashboard \
  --dashboard-name usms-overview \
  --dashboard-body file://templates/lab-13-dashboard.json \
  --query 'DashboardValidationMessages' --output json
```

**What the command does**

`<< 'EOF'` - **quoted**. There is nothing to expand, and the document contains `$`-free JSON, so an
unquoted heredoc would appear to work. Same trap, third time, same rule.

The metric array format is positional and takes a moment to read:
`[ namespace, metricName, dimName, dimValue, dimName, dimValue, { options } ]`. Dimensions are
name-value pairs flattened into the array, and the optional trailing object carries `stat`, `label`,
`color` and `yAxis`. The `NotifyCount` entry has no dimensions, because Step 9's filter published
none - the same fact the alarm in Step 19 had to respect.

The latency widget puts `stat` in the **per-metric** options rather than at widget level, which is
how you draw two statistics of one metric on one chart. Widget-level `stat` is the default for
metrics that do not override it.

`annotations.horizontal` draws the alarm threshold as a line. A latency chart without its threshold
drawn on it makes the reader do arithmetic, and the whole purpose of a dashboard is that nobody has
to.

The `alarm` widget takes **ARNs**, not names, and the account id is hard-coded to Floci's
`000000000000`. On real AWS you would build these from `$USMS_ACCOUNT_ID`, which is exactly the kind
of value the course keeps in `configs/lab-01.env` - and Exercise 2 asks you to make that change.

`--query 'DashboardValidationMessages'` prints the field that tells you whether the document is
usable. A dashboard with an unparseable widget is **still created**; the invalid widget simply does
not render. This is the fourth "successful call, partial failure" field in this lab.

**Expected result**

```text
valid JSON
[]
```

> Example output - an empty list means every widget validated.

**Verify**

```bash
aws cloudwatch list-dashboards \
  --query 'DashboardEntries[].[DashboardName,Size]' --output table

aws cloudwatch get-dashboard --dashboard-name usms-overview \
  --query 'DashboardBody' --output text \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
print('widgets     :', len(body['widgets']))
print('types       :', ', '.join(sorted({w['type'] for w in body['widgets']})))
print('grid width  :', max(w['x'] + w['width'] for w in body['widgets']))
rows = sorted((w['y'], w['y'] + w['height'], w['x'], w['x'] + w['width']) for w in body['widgets'])
overlap = any(a[1] > b[0] and a[3] > b[2] and b[3] > a[2] for a, b in zip(rows, rows[1:]))
print('overlapping :', overlap)
"
```

**What the command does**

`get-dashboard` returns the body as a **JSON string inside a JSON field**, which is the same shape
`lambda get-policy` returned in Lab 10 Step 19. `--output text` unwraps the outer layer and the
Python reads what is left.

The overlap check is not decoration: an overlapping widget renders on top of its neighbour and there
is no validation message for it, because the document is perfectly valid JSON describing an
unfortunate layout.

**Expected result**

```text
-------------------------------
|       ListDashboards        |
+-----------------+-----------+
|  usms-overview  |   2134    |
+-----------------+-----------+
widgets     : 5
types       : alarm, metric, text
grid width  : 24
overlapping : False
```

> Example output - your `Size` will differ.

!!! note "Floci Limitation - there is nothing to render a dashboard with"
    Floci stores the document and returns it faithfully. There is no console, so nothing ever draws
    it, and no widget property is validated beyond the document's overall shape.

    Real AWS renders it, validates each widget, reports unusable ones in
    `DashboardValidationMessages`, and refreshes it live.

    What transfers completely is the document: this JSON is byte-for-byte what you would `put` to
    real AWS, and the verify above checks the two things the emulator cannot - widget count and
    layout sanity. Treat the file in `templates/` as the artefact and the API call as a formality,
    which is also the right way to treat dashboards in production.

**Checkpoint 12**

```text
usms-overview  (5 widgets, 24 columns, no overlaps)
 ├── text     runbook and ownership
 ├── metric   TranscriptsProcessed by Faculty        timeSeries, Sum, 300s
 ├── metric   TranscriptLagSeconds max + avg         timeSeries, 60s, threshold line at 2
 ├── metric   NotifyCount + CentralErrorCount        singleValue, 300s
 └── alarm    the composite and its two children
```

---

### Step 23 - Query the logs properly

**Purpose**

`filter-log-events` finds lines. CloudWatch Logs Insights answers questions - counts, groupings,
percentiles, over a whole log group, retroactively. It is the tool for "how many transcripts failed
yesterday, by faculty", which no metric filter created today can tell you.

**Run from**

```text
aws-floci-course/
```

**Concept first - the query language**

Insights queries are a pipeline of commands separated by `|`:

```text
fields @timestamp, @message
| filter @message like /USMS_EVENT/
| parse @message 'USMS_EVENT *' as payload
| stats count() as events by bin(5m)
| sort @timestamp desc
| limit 20
```

| Command | Does |
| --- | --- |
| `fields` | choose columns. `@timestamp`, `@message`, `@logStream` are always available |
| `filter` | keep matching rows. Supports `like /regex/`, unlike a metric filter pattern |
| `parse` | extract fields with a glob or a regex |
| `stats` | aggregate - `count()`, `avg()`, `max()`, `pct(f, 99)` - optionally `by` something |
| `sort`, `limit` | the obvious |

Two things to notice. `filter` takes a **regular expression**, which the metric filter pattern in
Step 8 did not - the two languages are unrelated, they live in the same service, and confusing them
is normal. And a query is **retroactive**: it reads events already in the group, which is exactly the
thing a metric filter cannot do.

The trade is cost and latency. A filter is evaluated once per event at ingestion and produces a
number that is free to read forever. A query scans the data every time you run it and is billed by
the volume scanned. **Put the questions you ask constantly behind a metric filter; ask everything
else with a query.**

**Command - path A, if Step 4 reported Insights as SUPPORTED**

```bash
QUERY_ID=$(aws logs start-query \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --start-time "$XSTART" --end-time "$XEND" \
  --query-string 'fields @timestamp, @message
| filter @message like /USMS_EVENT/
| parse @message "*\"faculty\":\"*\"*" as pre, faculty, post
| stats count() as events by faculty
| sort events desc' \
  --query 'queryId' --output text)

echo "query: $QUERY_ID"

for attempt in 1 2 3 4 5 6; do
  STATUS=$(aws logs get-query-results --query-id "$QUERY_ID" --query 'status' --output text)
  [ "$STATUS" = "Complete" ] && break
  printf '  status %s, waiting\n' "$STATUS"
  sleep 3
done

aws logs get-query-results --query-id "$QUERY_ID" \
  --query 'results[].[ [0].value, [1].value ]' --output table
```

**What the command does**

`start-query` is **asynchronous**. It returns a `queryId` immediately and the results are not ready.
The loop polls `get-query-results` until `status` is `Complete`; the other values are `Scheduled`,
`Running`, `Failed`, `Cancelled` and `Timeout`. Treating `start-query` as synchronous and reading the
results once is the standard first mistake, and it returns an empty list rather than an error.

`results[].[ [0].value, [1].value ]` navigates the result shape, which is unusual: each row is a list
of `{field, value}` objects rather than an object. Indexing into it positionally is how you flatten
it for a table.

**Command - path B, if Insights is unsupported**

You are not skipping the step. You are answering the same question with the tool that is available,
and noticing what it costs you.

```bash
aws logs filter-log-events \
  --log-group-name "$CENTRAL_LOG_GROUP" \
  --filter-pattern 'USMS_EVENT' \
  --query 'events[].message' --output text \
  | python3 -c "
import collections, json, re, sys

counts = collections.Counter()
for line in sys.stdin.read().split('USMS_EVENT'):
    line = line.strip()
    if not line.startswith('{'):
        continue
    match = re.match(r'\{.*?\}', line, re.S)
    if not match:
        continue
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        continue
    counts[payload.get('faculty', 'unknown')] += 1

for faculty, n in counts.most_common():
    print('%-14s %d' % (faculty, n))
"
```

**What the command does**

It does the same job in three stages that Insights does in one: retrieve, parse, aggregate. The
differences are worth stating, because they are the argument for the managed service:

- Every matching event crosses the network to your machine. Insights aggregates server-side.
- The parsing is yours to get right, and the regex above is already fragile.
- There is no way to ask for a 99th percentile without writing it.
- It does not scale past a few thousand events.

It is, however, correct, and it runs everywhere.

**Expected result - either path**

```text
science        3
engineering    2
```

> Example output - your counts depend on how many times you ran the emitter in Step 17.

**Verify**

```bash
aws logs describe-log-groups --log-group-name-prefix /usms/central \
  --query 'logGroups[0].{Group:logGroupName,Retention:retentionInDays,Bytes:storedBytes}' \
  --output json
```

**What to look for:** counts that match the emitter runs you actually did, and a `storedBytes` that
is not zero. A query returning nothing against a group with bytes in it means your time window is
wrong - `XSTART` and `XEND` were computed back in Step 16 and are now well over an hour old. Recompute
them if the session has run long.

---

### Step 24 - Restart Floci and read everything back

**Purpose**

Every lab in this course ends by proving that what it built survives a restart, because the one
defect that cost students a whole lab's work was a persistence setting that reported success and
discarded everything.

Telemetry adds a distinction worth checking. **Configuration** - log groups, filters, alarms,
dashboards - is stored like any other resource. **Data** - log events, metric data points, trace
segments - is stored differently and time-indexed, and a build can persist the first and lose the
second. That is exactly the failure that makes a dashboard look healthy while being empty.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the state**

```bash
inventory() {
  echo "--- log groups ---"
  aws logs describe-log-groups \
    --query 'sort_by(logGroups, &logGroupName)[].[logGroupName,retentionInDays]' --output text
  echo "--- metric filters ---"
  aws logs describe-metric-filters \
    --query 'sort_by(metricFilters, &filterName)[].[filterName,logGroupName]' --output text
  echo "--- metrics ---"
  aws cloudwatch list-metrics --namespace USMS/Application \
    --query 'sort_by(Metrics, &MetricName)[].MetricName' --output text | tr '\t' '\n' | sort -u
  echo "--- alarms ---"
  aws cloudwatch describe-alarms \
    --query 'sort_by(MetricAlarms, &AlarmName)[].[AlarmName,StateValue]' --output text
  aws cloudwatch describe-alarms --alarm-types CompositeAlarm \
    --query 'sort_by(CompositeAlarms, &AlarmName)[].[AlarmName,AlarmRule]' --output text
  echo "--- dashboards ---"
  aws cloudwatch list-dashboards --query 'DashboardEntries[].DashboardName' --output text
  echo "--- notifier ---"
  aws lambda get-function-configuration --function-name "$NOTIFIER" --qualifier live \
    --query '[Version,TracingConfig.Mode]' --output text
}

inventory | tee outputs/lab-13-pre-restart.txt

DATA_BEFORE=$(aws cloudwatch get-metric-statistics \
  --namespace USMS/Application --metric-name TranscriptsProcessed \
  --start-time "$START" --end-time "$END" --period 300 --statistics Sum \
  --query 'length(Datapoints)' --output text)

echo "metric data points before restart: $DATA_BEFORE"
```

**Command - part 2, perturb**

```bash
./scripts/setup/floci-down.sh
./scripts/setup/floci-up.sh
./scripts/utilities/whoami.sh
```

**What the command does**

`floci-down.sh` is `docker compose stop`. It stops the container and keeps its state - it is not
`docker compose down`, and it is emphatically not `docker compose down -v`, which would delete the
volumes and with them this entire course. The distinction is why the course ships a script instead of
telling you the command.

**Command - part 3, read back**

```bash
source configs/course.env
for f in configs/lab-01.env configs/lab-10.env; do [ -f "$f" ] && source "$f"; done
NOTIFIER="${USMS_LAMBDA_NOTIFIER_FN:-usms-transcript-notifier}"
CENTRAL_LOG_GROUP=/usms/central/application

inventory | tee outputs/lab-13-post-restart.txt

diff outputs/lab-13-pre-restart.txt outputs/lab-13-post-restart.txt \
  && echo "CONFIGURATION IDENTICAL - every Lab 13 object survived the restart"

DATA_AFTER=$(aws cloudwatch get-metric-statistics \
  --namespace USMS/Application --metric-name TranscriptsProcessed \
  --start-time "$START" --end-time "$END" --period 300 --statistics Sum \
  --query 'length(Datapoints)' --output text)

printf 'metric data points: before=%s after=%s\n' "$DATA_BEFORE" "$DATA_AFTER"
```

**What the command does**

The re-source at the top is deliberate. `inventory` is a shell function and shell functions die with
the terminal just as variables do - but this is the same terminal, so it survives; what does **not**
survive a stop and start is nothing at all on the shell side, which is precisely the point of
re-deriving `NOTIFIER` rather than trusting it. If you did close the terminal, re-sourcing is what
makes the read-back comparable rather than a comparison against an empty variable.

`diff` compares configuration. The two `get-metric-statistics` calls compare **data**, separately,
because they can differ and the difference is informative.

**Expected result**

```text
--- log groups ---
/aws/lambda/usms-transcript-notifier	14
/usms/central/application	30
/usms/ecs/enrolment	30
--- metric filters ---
usms-central-errors	/usms/central/application
usms-notify-count	/aws/lambda/usms-transcript-notifier
--- metrics ---
CentralErrorCount
EdgeDenyCount
NotifyCount
TranscriptLagSeconds
TranscriptsProcessed
--- alarms ---
usms-enrolment-queue-high	INSUFFICIENT_DATA
usms-notify-silence	OK
usms-transcript-lag-high	OK
usms-transcript-pipeline-down	ALARM("usms-transcript-lag-high") OR ALARM("usms-notify-silence")
--- dashboards ---
usms-overview
--- notifier ---
3	Active

CONFIGURATION IDENTICAL - every Lab 13 object survived the restart
metric data points: before=2 after=2
```

> Example output - your counts differ, and `after=0` is a real and common result. Read the next
> paragraph before concluding anything from it.

**What to look for**, in this order:

1. `diff` reports no differences. Configuration persisted.
2. The notifier still reports version `3` and `Active`. That is Step 13 and Step 14 surviving.
3. `before` and `after` for data points. If they match, metric data persisted too. **If `after` is 0
   and `before` was not, your build persists configuration and discards time-series data** - which is
   a real and specific finding, not a failure of your work. Record it in
   `outputs/lab-13-support-probe.txt` and re-run `./scripts/utilities/usms-emit-telemetry.sh` twice to
   repopulate, so that Section 9's verification has data to find.

If `diff` shows a **configuration** difference, that is different and serious. Run
`./scripts/utilities/floci-storage-check.sh` before doing any more work; a storage mode of `memory`
is the cause in the overwhelming majority of cases, and it is the exact failure the course contract
was written about.

**Checkpoint 13**

```text
after floci-down.sh + floci-up.sh
 ├── 3+ log groups with retention   present
 ├── 2 metric filters               present
 ├── 5 metrics in USMS/Application  present
 ├── 3 alarms + 1 composite         present, states preserved
 ├── usms-overview dashboard        present
 ├── notifier live → 3, Active      present
 └── metric DATA                    checked separately, and the answer recorded either way
```

---

### Step 25 - Write `configs/lab-13.env`

**Purpose**

Everything you have captured lives in shell variables, and shell variables die with the terminal.
This is the step that turns this lab's work into something Lab 09 can source without you remembering
anything.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-13.env << EOF
# Lab 13 - Centralized logging and monitoring with CloudWatch and X-Ray
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, ARNs and IDs only. NO SECRETS. Safe to commit.

# --- log layer ------------------------------------------------------------
export USMS_LOG_GROUP_CENTRAL=/usms/central/application
export USMS_LOG_GROUP_ECS=/usms/ecs/enrolment
export USMS_LOG_STREAM_CENTRAL=$(aws logs describe-log-streams \
  --log-group-name /usms/central/application \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text | head -1)
export USMS_LOG_RETENTION_APP=30
export USMS_LOG_RETENTION_FN=14

# --- metric layer ---------------------------------------------------------
export USMS_METRIC_NAMESPACE=USMS/Application
export USMS_METRIC_FILTER_NOTIFY=usms-notify-count
export USMS_METRIC_FILTER_ERRORS=usms-central-errors
export USMS_METRIC_NOTIFY_COUNT=NotifyCount
export USMS_METRIC_ERROR_COUNT=CentralErrorCount
export USMS_METRIC_PROCESSED=TranscriptsProcessed
export USMS_METRIC_LAG=TranscriptLagSeconds
export USMS_METRIC_EDGE_DENY=EdgeDenyCount

# --- iam ------------------------------------------------------------------
export USMS_POLICY_OBSERVABILITY=USMSObservabilityWrite
export USMS_POLICY_OBSERVABILITY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSObservabilityWrite'].Arn | [0]" --output text)

# --- the instrumented notifier -------------------------------------------
export USMS_NOTIFIER_VERSION_INSTRUMENTED=${NOTIFIER_V2}
export USMS_NOTIFIER_VERSION_TRACED=${NOTIFIER_V3}
export USMS_NOTIFIER_ALIAS_VERSION=$(aws lambda get-alias \
  --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text)
export USMS_NOTIFIER_TRACING_MODE=$(aws lambda get-function-configuration \
  --function-name usms-transcript-notifier --qualifier live \
  --query 'TracingConfig.Mode' --output text)

# --- alarms - a future alerting lab attaches SNS actions to these three ------------------
export USMS_ALARM_LAG_HIGH=usms-transcript-lag-high
export USMS_ALARM_NOTIFY_SILENCE=usms-notify-silence
export USMS_ALARM_COMPOSITE=usms-transcript-pipeline-down

# --- dashboard ------------------------------------------------------------
export USMS_DASHBOARD=usms-overview

# --- x-ray ----------------------------------------------------------------
export USMS_XRAY_SAMPLING_RULE=usms-transcripts-sampling
export USMS_XRAY_SUPPORTED=$(aws xray get-sampling-rules >/dev/null 2>&1 && echo yes || echo no)
export USMS_XRAY_LAST_TRACE_ID=$(awk 'END {print $1}' outputs/lab-13-trace-ids.txt 2>/dev/null | grep -E '^1-' || echo none)

# --- capability flags recorded at lab time --------------------------------
export USMS_INSIGHTS_SUPPORTED=$(aws logs describe-queries --max-results 1 >/dev/null 2>&1 && echo yes || echo no)
export USMS_TELEMETRY_EMITTER=scripts/utilities/usms-emit-telemetry.sh
EOF

cat configs/lab-13.env
```

**What the command does**

`<< EOF` - **unquoted**, deliberately, and for the third and last time in this lab. Every `$(...)`
in this file must run **now**, at write time, so that the file contains values rather than commands.
A quoted heredoc here would produce a file full of `aws lambda get-alias ...` text that does nothing
when sourced, and - the part that makes it dangerous - would produce no error either when written or
when sourced.

The three heredoc decisions in this lab, side by side:

| Step | Form | Because |
| --- | --- | --- |
| 12, 13, 15, 16, 17, 18, 22 | `<< 'EOF'` / `<< 'PY'` | the file must contain exactly what you typed |
| 11 | `<< EOF` | one timestamp must be substituted |
| 25 | `<< EOF` | every value is the output of a command run now |

`| head -1` after the log stream query is there because `--max-items 1` on a paginated call can emit
a `NextToken` line on some builds, and a two-line value in an `export` produces a file that fails to
source with a syntax error thirty lines later.

`| grep -E '^1-' || echo none` on the trace id is Lab 06's sentinel pattern: `--output text` prints
`None` when a query matches nothing, and a variable containing the literal string `None` is worse
than one containing an honest `none`, because `None` looks like a value.

The two capability flags at the bottom are unusual for this course and are the right thing here.
Lab 09 needs to know whether it can expect traces and Insights queries to work on *your* build, and
recording the answer at the time you observed it is more reliable than re-probing months later.

**Expected result**

```text
# Lab 13 - Centralized logging and monitoring with CloudWatch and X-Ray
# Generated on 2026-09-17T05:41:12Z
...
export USMS_NOTIFIER_ALIAS_VERSION=3
export USMS_NOTIFIER_TRACING_MODE=Active
...
export USMS_XRAY_SUPPORTED=yes
export USMS_XRAY_LAST_TRACE_ID=1-68ca5107-8b3e1d02f7a94c56e1d0b3a7
export USMS_INSIGHTS_SUPPORTED=no
```

> Example output - your capability flags depend on your build, and `no` is a perfectly good value.

**Verify**

```bash
grep -c '^export' configs/lab-13.env

grep -nE '^export [A-Z_]+=$|None' configs/lab-13.env || echo "all values populated"

( source configs/lab-13.env && echo "sources cleanly" )
```

**What to look for:** **28** exports, the message `all values populated`, and a clean source. An
empty value or the string `None` means a resource does not exist, and catching it here is worth ten
troubleshooting entries in the next lab. `none` in lower case on the trace id is a populated value
and is expected on a build without X-Ray.

The `( ... )` around the source is a subshell so that a broken file cannot damage your current
environment - a small habit, and the first time in this course a lab has had enough variables for it
to matter.

---

### Step 26 - Check what Git sees, and commit

**Purpose**

This lab wrote a policy document, six JSON templates, one handler, two scripts and a configuration
file. Exactly one category of what it produced does not belong in the repository, and the point of
looking before committing is that you find out which before it is in the history rather than after.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look**

```bash
git status --short
```

**Expected result**

```text
?? configs/lab-13.env
?? labs/lab-13-cloudwatch-xray/
?? policies/usms-observability-write-policy.json
?? project/
?? scripts/utilities/usms-emit-telemetry.sh
?? templates/lab-13-dashboard.json
?? templates/lab-13-metric-data.json
?? templates/lab-13-sampling-rule.json
?? templates/lab-13-segment-downstream.json
?? templates/lab-13-segment-parent.json
?? templates/lab-13-segment-subsegments.json
```

> Example output - ordering and the exact set depend on what you have done.

**What to look for**, and this is the check, not the commit:

- **No `outputs/` path appears.** Not the zip, not the trace ids, not the probe output.
- **No `.env` file other than `configs/lab-13.env`.** The repository's root `.env` is generated by
  `floci-up.sh` and must never be committed.
- **No `__pycache__`.** `py_compile` in Step 13 created one.
- **`project/` appears and is empty so far.** Appendix C fills it, and Appendix C says what of it is
  committable.

```bash
git check-ignore -v outputs/lab-13-notifier-v2.zip
git check-ignore -v outputs/lab-13-trace-ids.txt
git ls-files outputs/
```

**Expected result**

```text
.gitignore:12:outputs/*	outputs/lab-13-notifier-v2.zip
.gitignore:12:outputs/*	outputs/lab-13-trace-ids.txt
outputs/.gitkeep
```

> Example output - your line number will differ.

**What to look for:** `check-ignore` names the rule and the line that excluded each file, and
`git ls-files outputs/` lists `.gitkeep` and nothing else. That is the rule from Lab 1 still holding:
`outputs/*` excludes the contents while leaving the directory visible to Git, and `!outputs/.gitkeep`
re-includes the one file that keeps it in the tree. Had the rule been written `outputs/` - excluding
the directory itself - the negation would silently do nothing.

**Command - part 2, commit**

```bash
git add configs/lab-13.env \
        labs/lab-13-cloudwatch-xray \
        policies/usms-observability-write-policy.json \
        scripts/utilities/usms-emit-telemetry.sh \
        scripts/utilities/verify-lab-13.sh \
        scripts/cleanup/lab-13-cleanup.sh \
        templates/lab-13-*.json

git status --short

git commit -m "Lab 13: centralized logging and monitoring with CloudWatch and X-Ray

- /usms/central/application created; retention set on every USMS log group
- usms-notify-count and usms-central-errors metric filters -> USMS/Application
- 5 metrics in USMS/Application, 2 from filters and 3 published directly
- USMSObservabilityWrite on usms-lambda-exec-role and usms-ec2-app-role
- usms-transcript-notifier v2 instrumented, v3 traced, alias live repointed
- usms-transcript-lag-high, usms-notify-silence, usms-transcript-pipeline-down
- usms-overview dashboard, 5 widgets
- X-Ray segments, subsegments, annotations and a sampling rule"
```

**What the command does**

`git add` names paths explicitly rather than using `git add -A`. On a repository that contains a
git-ignored directory full of build artefacts, `-A` is safe only because the ignore rule is correct -
and naming the paths means you are not relying on that being true.

`verify-lab-13.sh` and `lab-13-cleanup.sh` are in the list; you create them in Section 9 and
Section 16. If you are running the steps in order and have not reached those yet, `git add` will
report them as missing - add them in a second commit after Section 9, or run this step last.

`project/` is **not** in the list. Appendix C says what goes in it and when.

**Verify**

```bash
git log --oneline -1
git show --stat --oneline HEAD | head -20
```

**What to look for:** the commit exists, and the file list contains no `outputs/` path and no `.zip`.

**Checkpoint 14**

```text
aws-floci-course/  (committed)
 ├── configs/lab-13.env ......................... 28 exports, no secrets
 ├── labs/lab-13-cloudwatch-xray/ ............... instrumented handler + exercises
 ├── policies/usms-observability-write-policy.json
 ├── templates/lab-13-*.json .................... 6 documents
 └── scripts/utilities/usms-emit-telemetry.sh

outputs/  (git-ignored, correctly)
 ├── lab-13-notifier-v2.zip
 ├── lab-13-support-probe.txt, lab-13-telemetry-inventory.txt
 ├── lab-13-filter-test.json, lab-13-metric-readback.json
 ├── lab-13-trace-ids.txt, lab-13-trace-summaries.json, lab-13-service-graph.json
 ├── lab-13-alarm-history.json
 └── lab-13-pre-restart.txt / lab-13-post-restart.txt
```

---
## 9. Verification

One script, run at the end of this lab and at the start of the next one. It checks three things that
are easy to confuse:

- that the objects **exist**,
- that they are **configured** the way this lab requires - which is where a verification script earns
  its keep, because an alarm that exists and an alarm that would fire are very different claims,
- and that the environment underneath them is still sound, because a lab that verifies only its own
  resources passes right up until the restart that deletes them.

Several checks are the static substitutes for behaviour Floci does not implement: that
`usms-notify-silence` treats missing data as **breaching**, that the notifier's alias has moved past
Lab 10's version 1, that the X-Ray documents are internally consistent. Those are the rules you
cannot learn here by breaking them, so the script checks them on every run instead.

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-13.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 13 artefact exists AND is configured as the lab requires.
# Exit 1 if anything is missing. Read-only: this script changes nothing.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-01.env" 2>/dev/null || true
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-10.env" 2>/dev/null || true
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-13.env" 2>/dev/null || true

CENTRAL="${USMS_LOG_GROUP_CENTRAL:-/usms/central/application}"
FN_LOG="${USMS_LOG_GROUP_NOTIFIER:-/aws/lambda/usms-transcript-notifier}"
ECS_LOG="${USMS_LOG_GROUP_ECS:-/usms/ecs/enrolment}"
NS="${USMS_METRIC_NAMESPACE:-USMS/Application}"
NOTIFIER="${USMS_LAMBDA_NOTIFIER_FN:-usms-transcript-notifier}"
ROLE_LAMBDA="${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}"
ROLE_EC2="${USMS_ROLE_EC2:-usms-ec2-app-role}"
A_LAG="${USMS_ALARM_LAG_HIGH:-usms-transcript-lag-high}"
A_SILENCE="${USMS_ALARM_NOTIFY_SILENCE:-usms-notify-silence}"
A_COMP="${USMS_ALARM_COMPOSITE:-usms-transcript-pipeline-down}"
DASH="${USMS_DASHBOARD:-usms-overview}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ✔ %s\n" "$1"; PASS=$((PASS+1))
  else printf "  ✗ %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# --- helpers -------------------------------------------------------------
# Defined as functions so the check strings below stay free of nested quoting.

lg_retention() {   # $1 = log group name
  aws logs describe-log-groups --log-group-name-prefix "$1" \
    --query "logGroups[?logGroupName=='$1'].retentionInDays | [0]" --output text
}

lg_any_unset() {   # prints the names of USMS log groups with no retention policy
  aws logs describe-log-groups \
    --query 'logGroups[?retentionInDays==null].logGroupName' --output text \
    | tr '\t' '\n' | grep -E '^/usms/|^/aws/lambda/usms-'
}

mf_group() {   # $1 = filter name
  aws logs describe-metric-filters \
    --query "metricFilters[?filterName=='$1'].logGroupName | [0]" --output text
}

metric_dims() {   # $1 = metric name; prints one line per published dimension set
  aws cloudwatch list-metrics --namespace "$NS" --metric-name "$1" \
    --query 'Metrics[].join(`,`, Dimensions[].Name) || `NONE`' --output text
}

obs_policy_arn() {
  aws iam list-policies --scope Local \
    --query "Policies[?PolicyName=='USMSObservabilityWrite'].Arn | [0]" --output text
}

obs_policy_doc() {
  local arn ver
  arn=$(obs_policy_arn)
  ver=$(aws iam get-policy --policy-arn "$arn" --query 'Policy.DefaultVersionId' --output text)
  aws iam get-policy-version --policy-arn "$arn" --version-id "$ver" \
    --query 'PolicyVersion.Document' --output json
}

role_has_obs() {   # $1 = role name
  aws iam list-attached-role-policies --role-name "$1" --output text \
    | grep -q USMSObservabilityWrite
}

alias_version() {
  aws lambda get-alias --function-name "$NOTIFIER" --name live \
    --query 'FunctionVersion' --output text
}

alarm_field() {   # $1 = alarm name, $2 = JMESPath field
  aws cloudwatch describe-alarms --alarm-names "$1" \
    --query "MetricAlarms[0].$2" --output text
}

composite_rule() {
  aws cloudwatch describe-alarms --alarm-names "$A_COMP" --alarm-types CompositeAlarm \
    --query 'CompositeAlarms[0].AlarmRule' --output text
}

dashboard_body() {
  aws cloudwatch get-dashboard --dashboard-name "$DASH" --query 'DashboardBody' --output text
}

dashboard_widgets() {
  dashboard_body | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["widgets"]))'
}

dashboard_no_overlap() {
  dashboard_body | python3 -c '
import json, sys
w = json.load(sys.stdin)["widgets"]
boxes = [(x["x"], x["y"], x["x"]+x["width"], x["y"]+x["height"]) for x in w]
for i, a in enumerate(boxes):
    for b in boxes[i+1:]:
        if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
            sys.exit(1)
sys.exit(0)'
}

sampling_rule_complete() {
  python3 -c '
import json, sys
r = json.load(open("templates/lab-13-sampling-rule.json"))
need = {"RuleName","ResourceARN","Priority","FixedRate","ReservoirSize",
        "ServiceName","ServiceType","Host","HTTPMethod","URLPath","Version"}
sys.exit(0 if need.issubset(r) else 1)'
}

segments_consistent() {
  python3 -c '
import json, re, sys
d = {n: json.load(open("templates/lab-13-segment-%s.json" % n))
     for n in ("parent", "subsegments", "downstream")}
tid = d["parent"]["trace_id"]
ok = (re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", tid)
      and all(x["trace_id"] == tid for x in d.values())
      and all(re.fullmatch(r"[0-9a-f]{16}", x["id"]) for x in d.values())
      and d["downstream"].get("parent_id") == d["parent"]["id"]
      and all(x["end_time"] > x["start_time"] for x in d.values()))
sys.exit(0 if ok else 1)'
}

echo "== Environment =="
check "Floci container running" \
  'test "$(docker container inspect $FLOCI_CONTAINER_NAME --format "{{.State.Running}}")" = true'
check "Storage mode is NOT memory" \
  'docker container inspect $FLOCI_CONTAINER_NAME --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -qE "^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$"'
check "AWS CLI reaches Floci" \
  'aws sts get-caller-identity'

echo "== Log layer =="
check "central log group $CENTRAL exists" \
  'aws logs describe-log-groups --log-group-name-prefix "$CENTRAL" --query "length(logGroups)" --output text | grep -qv "^0$"'
check "central log group retention is 30 days" \
  'test "$(lg_retention "$CENTRAL")" = "30"'
check "notifier log group has a retention policy" \
  'lg_retention "$FN_LOG" | grep -qE "^[0-9]+$"'
check "ECS log group has a retention policy" \
  'lg_retention "$ECS_LOG" | grep -qE "^[0-9]+$"'
check "NO USMS log group is left on never-expire" \
  '! lg_any_unset | grep -q .'
check "central log group has at least one stream" \
  'test "$(aws logs describe-log-streams --log-group-name "$CENTRAL" --query "length(logStreams)" --output text)" != "0"'

echo "== Metric filters =="
check "usms-notify-count exists" \
  'aws logs describe-metric-filters --filter-name-prefix usms-notify-count --query "length(metricFilters)" --output text | grep -qv "^0$"'
check "usms-notify-count is attached to the NOTIFIER log group" \
  'test "$(mf_group usms-notify-count)" = "$FN_LOG"'
check "usms-central-errors is attached to the CENTRAL log group" \
  'test "$(mf_group usms-central-errors)" = "$CENTRAL"'

echo "== Metrics =="
check "namespace $NS has metrics" \
  'test "$(aws cloudwatch list-metrics --namespace "$NS" --query "length(Metrics)" --output text)" != "0"'
check "TranscriptsProcessed published WITH dimensions" \
  'metric_dims TranscriptsProcessed | grep -q Faculty'
check "TranscriptsProcessed ALSO published with none  (the total)" \
  'metric_dims TranscriptsProcessed | grep -q NONE'
check "TranscriptLagSeconds exists" \
  'test "$(aws cloudwatch list-metrics --namespace "$NS" --metric-name TranscriptLagSeconds --query "length(Metrics)" --output text)" != "0"'

echo "== IAM =="
check "USMSObservabilityWrite exists" \
  'obs_policy_arn | grep -q "policy/USMSObservabilityWrite"'
check "attached to $ROLE_LAMBDA" \
  'role_has_obs "$ROLE_LAMBDA"'
check "attached to $ROLE_EC2" \
  'role_has_obs "$ROLE_EC2"'
check "PutMetricData is scoped by a cloudwatch:namespace condition" \
  'obs_policy_doc | grep -q "cloudwatch:namespace"'
check "log group ARNs end in :*  (streams, not just the group)" \
  'obs_policy_doc | grep -qE "log-group:/usms/\*:\*"'

echo "== The instrumented notifier =="
check "$NOTIFIER exists" \
  'aws lambda get-function-configuration --function-name "$NOTIFIER"'
check "alias live points at a numbered version" \
  'alias_version | grep -qE "^[0-9]+$"'
check "alias live has MOVED PAST Lab 10 version 1" \
  'test "$(alias_version)" -ge 2'
check "tracing mode on the alias is Active" \
  'test "$(aws lambda get-function-configuration --function-name "$NOTIFIER" --qualifier live --query "TracingConfig.Mode" --output text)" = "Active"'
check "instrumented handler source emits USMS_SUMMARY" \
  'grep -q "USMS_SUMMARY" labs/lab-13-cloudwatch-xray/transcript-notifier-v2/notifier.py'

echo "== Alarms =="
check "$A_LAG exists" \
  'aws cloudwatch describe-alarms --alarm-names "$A_LAG" --query "length(MetricAlarms)" --output text | grep -qv "^0$"'
check "$A_LAG uses the Maximum statistic, not Average" \
  'test "$(alarm_field "$A_LAG" Statistic)" = "Maximum"'
check "$A_LAG treats missing data as notBreaching" \
  'test "$(alarm_field "$A_LAG" TreatMissingData)" = "notBreaching"'
check "$A_SILENCE exists" \
  'aws cloudwatch describe-alarms --alarm-names "$A_SILENCE" --query "length(MetricAlarms)" --output text | grep -qv "^0$"'
check "$A_SILENCE treats missing data as BREACHING  (it watches an absence)" \
  'test "$(alarm_field "$A_SILENCE" TreatMissingData)" = "breaching"'
check "composite alarm $A_COMP exists" \
  'composite_rule | grep -q ALARM'
check "composite rule names BOTH child alarms" \
  'composite_rule | grep -q "$A_LAG" && composite_rule | grep -q "$A_SILENCE"'
check "no alarm is left stuck in ALARM from Step 20 or 21" \
  'test "$(alarm_field "$A_LAG" StateValue)" != "ALARM" && test "$(alarm_field "$A_SILENCE" StateValue)" != "ALARM"'

echo "== Dashboard =="
check "dashboard $DASH exists" \
  'aws cloudwatch list-dashboards --query "DashboardEntries[].DashboardName" --output text | grep -q "$DASH"'
check "dashboard body is valid JSON" \
  'dashboard_body | python3 -m json.tool'
check "dashboard has 5 widgets" \
  'test "$(dashboard_widgets)" -eq 5'
check "no two widgets overlap" \
  'dashboard_no_overlap'

echo "== X-Ray documents =="
check "sampling rule document is valid JSON" \
  'python3 -m json.tool templates/lab-13-sampling-rule.json'
check "sampling rule declares every required field" \
  'sampling_rule_complete'
check "segment documents share one trace id and are well formed" \
  'segments_consistent'

echo "== Files and Git hygiene =="
check "configs/lab-13.env exists" \
  'test -f configs/lab-13.env'
check "configs/lab-13.env has 28 exports" \
  'test "$(grep -c "^export" configs/lab-13.env)" -eq 28'
check "configs/lab-13.env has no empty values" \
  '! grep -qE "^export [A-Z_]+=$" configs/lab-13.env'
check "usms-emit-telemetry.sh is executable and valid bash" \
  'test -x scripts/utilities/usms-emit-telemetry.sh && bash -n scripts/utilities/usms-emit-telemetry.sh'
check "observability policy document is valid JSON" \
  'python3 -m json.tool policies/usms-observability-write-policy.json'
check "dashboard template is committed, not only deployed" \
  'test -f templates/lab-13-dashboard.json'
check "no secret is tracked" \
  '! git ls-files | grep -q "^outputs/"'
check "no deployment archive is tracked" \
  '! git ls-files | grep -q "\.zip$"'

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-13.sh
bash -n scripts/utilities/verify-lab-13.sh && echo "syntax OK"
./scripts/utilities/verify-lab-13.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ✔ Floci container running
  ✔ Storage mode is NOT memory
  ✔ AWS CLI reaches Floci
== Log layer ==
  ✔ central log group /usms/central/application exists
  ✔ central log group retention is 30 days
  ✔ notifier log group has a retention policy
  ✔ ECS log group has a retention policy
  ✔ NO USMS log group is left on never-expire
  ✔ central log group has at least one stream
== Metric filters ==
  ✔ usms-notify-count exists
  ✔ usms-notify-count is attached to the NOTIFIER log group
  ✔ usms-central-errors is attached to the CENTRAL log group
== Metrics ==
  ✔ namespace USMS/Application has metrics
  ✔ TranscriptsProcessed published WITH dimensions
  ✔ TranscriptsProcessed ALSO published with none  (the total)
  ✔ TranscriptLagSeconds exists
== IAM ==
  ✔ USMSObservabilityWrite exists
  ✔ attached to usms-lambda-exec-role
  ✔ attached to usms-ec2-app-role
  ✔ PutMetricData is scoped by a cloudwatch:namespace condition
  ✔ log group ARNs end in :*  (streams, not just the group)
== The instrumented notifier ==
  ✔ usms-transcript-notifier exists
  ✔ alias live points at a numbered version
  ✔ alias live has MOVED PAST Lab 10 version 1
  ✔ tracing mode on the alias is Active
  ✔ instrumented handler source emits USMS_SUMMARY
== Alarms ==
  ✔ usms-transcript-lag-high exists
  ✔ usms-transcript-lag-high uses the Maximum statistic, not Average
  ✔ usms-transcript-lag-high treats missing data as notBreaching
  ✔ usms-notify-silence exists
  ✔ usms-notify-silence treats missing data as BREACHING  (it watches an absence)
  ✔ composite alarm usms-transcript-pipeline-down exists
  ✔ composite rule names BOTH child alarms
  ✔ no alarm is left stuck in ALARM from Step 20 or 21
== Dashboard ==
  ✔ dashboard usms-overview exists
  ✔ dashboard body is valid JSON
  ✔ dashboard has 5 widgets
  ✔ no two widgets overlap
== X-Ray documents ==
  ✔ sampling rule document is valid JSON
  ✔ sampling rule declares every required field
  ✔ segment documents share one trace id and are well formed
== Files and Git hygiene ==
  ✔ configs/lab-13.env exists
  ✔ configs/lab-13.env has 28 exports
  ✔ configs/lab-13.env has no empty values
  ✔ usms-emit-telemetry.sh is executable and valid bash
  ✔ observability policy document is valid JSON
  ✔ dashboard template is committed, not only deployed
  ✔ no secret is tracked
  ✔ no deployment archive is tracked

PASS=49  FAIL=0
```

> Example output - this is the target.

**The expected count is `PASS=49  FAIL=0`.**

Three notes on reading a failure:

**Failures in the Environment block are the real problem.** If Floci is not running, everything below
it fails as a consequence and none of those lower failures tells you anything. Fix the top block
first and re-run before reading anything else.

**Nothing in this script depends on X-Ray or Insights being supported.** The X-Ray block reads the
documents in `templates/`, which both paths of Steps 15 to 18 produce. A verification script whose
result depends on which emulator build you happen to have is not a verification script.

**Four checks are worth understanding rather than merely passing:**

| Check | Why it is there |
| --- | --- |
| `usms-notify-silence treats missing data as BREACHING` | The static detector for the mistake this whole lab is about. An alarm that watches for an absence and treats absence as `missing` never fires, ever, and looks identical in every other respect |
| `alias live has MOVED PAST Lab 10 version 1` | Catches the case where Step 13's `update-alias` silently did not apply, or where you did the Step 13 Your-turn rollback and never rolled forward. Every S3 notification would then still be running Lab 10's uninstrumented code |
| `TranscriptsProcessed ALSO published with none` | The static detector for the dimension misunderstanding from Step 11. Without the undimensioned publish there is no total, and a dashboard showing "all transcripts" would be quietly impossible |
| `no two widgets overlap` | Nothing in CloudWatch validates layout. An overlapping widget is a valid document and an unreadable page |

---

## 10. Checkpoints

| # | After Step | What must exist | How to check it in one line |
| --- | --- | --- | --- |
| 1 | 5 | An inventory of the telemetry seven labs already produced | `cat outputs/lab-13-telemetry-inventory.txt` |
| 2 | 6 | `/usms/central/application`, and retention on every USMS log group | `aws logs describe-log-groups --query 'logGroups[?retentionInDays==null].logGroupName'` |
| 3 | 7 | Log events in the central group, with correct millisecond timestamps | `aws logs filter-log-events --log-group-name /usms/central/application --query 'length(events)'` |
| 4 | 9 | Two metric filters, each on the right log group | `aws logs describe-metric-filters --query 'metricFilters[].[filterName,logGroupName]' --output table` |
| 5 | 10 | A log line converted into a metric data point | `aws cloudwatch list-metrics --namespace USMS/Application --metric-name NotifyCount` |
| 6 | 11 | Five metrics, including `TranscriptsProcessed` both with and without dimensions | `aws cloudwatch list-metrics --namespace USMS/Application --output table` |
| 7 | 12 | `USMSObservabilityWrite` on two roles | `aws iam list-attached-role-policies --role-name usms-lambda-exec-role` |
| 8 | 14 | Notifier version 3, tracing `Active`, alias `live` following it | `aws lambda get-function-configuration --function-name usms-transcript-notifier --qualifier live --query '[Version,TracingConfig.Mode]'` |
| 9 | 16 | A trace of two segments and three subsegments, or validated documents | `aws xray batch-get-traces --trace-ids "$(awk 'NR==1{print $1}' outputs/lab-13-trace-ids.txt)"` |
| 10 | 17 | `usms-emit-telemetry.sh`, run three times | `wc -l < outputs/lab-13-trace-ids.txt` |
| 11 | 20 | Two alarms, one proven by a forced state transition | `aws cloudwatch describe-alarm-history --alarm-name usms-transcript-lag-high --history-item-type StateUpdate` |
| 12 | 22 | `usms-overview`, 5 widgets, no overlaps | `aws cloudwatch get-dashboard --dashboard-name usms-overview` |
| 13 | 24 | All of the above surviving a stop and start | `diff outputs/lab-13-pre-restart.txt outputs/lab-13-post-restart.txt` |
| 14 | 26 | A commit containing the templates and no `outputs/` path | `git show --stat HEAD` |

---

## 11. Troubleshooting

### `put-log-events` succeeds and `filter-log-events` returns nothing

Almost always the timestamp. You passed seconds where the API wants **milliseconds**, and every event
landed in 1970, outside the ingestion window.

```bash
aws logs put-log-events --log-group-name /usms/central/application \
  --log-stream-name "$STREAM" \
  --log-events "timestamp=$(python3 -c 'import time;print(int(time.time()*1000))'),message=probe" \
  --query 'rejectedLogEventsInfo'
```

`rejectedLogEventsInfo` is the field to read. `tooOldLogEventEndIndex` with a non-zero value is the
diagnosis. If it is `null` and the events still do not appear, check that you are querying the group
you wrote to - a prefix typo in `--log-group-name` creates nothing and finds nothing.

### `InvalidSequenceTokenException` on `put-log-events`

Your build enforces the pre-2023 behaviour. Fetch the token and pass it; Step 7's tip has the
command. Record the substitution in `outputs/lab-13-support-probe.txt` so that your verification run
and your write-up agree.

### `get-metric-statistics` returns an empty `Datapoints` list

Four candidates, in the order worth checking:

```bash
# 1. does the metric exist at all, and with which dimensions?
aws cloudwatch list-metrics --namespace USMS/Application --metric-name TranscriptLagSeconds

# 2. are you asking with the EXACT dimension set it was published with?
#    A subset matches nothing. So does a superset.

# 3. is your window right, and in the past?
#    A window ending in the future is legal and returns nothing for the future part.

# 4. does --unit match what was published?
```

Number two is the answer roughly three times in four. A metric's identity is namespace plus name plus
the **complete** dimension set, and Step 11 exists to make that memorable.

### The metric filter produced nothing even though the log line is there

Test the pattern against the actual line, not against the line you meant to write:

```bash
aws logs filter-log-events --log-group-name /aws/lambda/usms-transcript-notifier \
  --query 'events[-1].message' --output text

aws logs test-metric-filter --filter-pattern 'USMS_NOTIFY' \
  --log-event-messages "$(aws logs filter-log-events \
      --log-group-name /aws/lambda/usms-transcript-notifier \
      --query 'events[-1].message' --output text)"
```

If `test-metric-filter` matches and the metric is still empty, your build stores filters without
evaluating them. That is Step 10's limitation note and it is not something you can fix; publish the
metric by hand, record it, and continue.

### The alarm stays in `INSUFFICIENT_DATA` no matter what

Expected here - Floci does not evaluate alarms. Before accepting that explanation on real AWS, check
the three things that produce the same symptom:

```bash
aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high \
  --query 'MetricAlarms[0].{Ns:Namespace,Metric:MetricName,Dims:Dimensions,Unit:Unit,Period:Period}'
```

A `Unit` the metric was never published with, a dimension set that does not match, or a period finer
than the publishing interval each give you a permanently uncertain alarm that looks perfectly
configured.

### `put-composite-alarm` fails with a parse error

The rule is one string containing double-quoted alarm names. In a shell, that means single quotes
outside:

```bash
--alarm-rule 'ALARM("usms-transcript-lag-high") OR ALARM("usms-notify-silence")'
```

Double quotes outside would have your shell strip the inner ones, leaving CloudWatch a rule naming
bare words. It also fails if a named alarm does not exist - composite alarms validate their children
at creation time, which is one of the few eager validations in CloudWatch.

### `describe-alarms` does not show the composite alarm

It is not missing. `describe-alarms` returns metric alarms unless you ask:

```bash
aws cloudwatch describe-alarms --alarm-types CompositeAlarm
```

### `put-trace-segments` returns entries in `UnprocessedTraceSegments`

Read the `Message` field; the causes are few and specific:

```bash
aws xray put-trace-segments --trace-segment-documents "$(cat templates/lab-13-segment-parent.json)" \
  --query 'UnprocessedTraceSegments[].[Id,ErrorCode,Message]' --output text
```

| Cause | Fix |
| --- | --- |
| `trace_id` not `1-<8hex>-<24hex>` | regenerate with the Step 15 Python block |
| `id` not exactly 16 hex characters | same |
| `end_time` missing or before `start_time` | check the arithmetic; X-Ray wants epoch **seconds as a float** |
| the embedded timestamp is too old | you cannot back-fill traces; generate a fresh trace id |
| an annotation whose value is a list or an object | annotations take string, number and boolean only - move it to metadata |

### `get-trace-summaries` returns nothing but `put-trace-segments` said `[]`

Your build stores segments without indexing them. Confirm with `batch-get-traces` on a known id from
`outputs/lab-13-trace-ids.txt`. If that works, use it for the rest of the lab and record the finding.
If neither works, take Step 16's structural-validation path.

### `start-query` returns a query id and the results are always empty

`start-query` is asynchronous. Poll `get-query-results` until `status` is `Complete`; reading once
returns an empty `results` list with `status: Running` and no error. Step 23's loop is the pattern.
If `status` reaches `Failed`, the query string is wrong - Insights reports syntax errors in the
status, not in the `start-query` response.

### The dashboard was created but a widget is missing

```bash
aws cloudwatch put-dashboard --dashboard-name usms-overview \
  --dashboard-body file://templates/lab-13-dashboard.json \
  --query 'DashboardValidationMessages'
```

A dashboard with an invalid widget is still created; the messages are the only place the problem is
reported. An empty list with a widget still missing means the widget is valid and drawn underneath
another one - run the overlap check from Step 22's verify.

### `verify-lab-13.sh` reports `configs/lab-13.env has 28 exports` as a failure

Count them and find the missing one:

```bash
grep -c '^export' configs/lab-13.env
grep -nE '^export [A-Z_]+=$' configs/lab-13.env
```

An export with an empty value means the `$(...)` that produced it returned nothing - usually because
the resource was created in a terminal you have since closed and the shell variable it referenced was
empty when the heredoc ran. `USMS_NOTIFIER_VERSION_INSTRUMENTED` and `USMS_NOTIFIER_VERSION_TRACED`
are the two most likely, because they come from shell variables rather than from an API call.
Re-derive them:

```bash
aws lambda list-versions-by-function --function-name usms-transcript-notifier \
  --query "Versions[?Version!='\$LATEST'].[Version,Description]" --output table
```

### Everything worked yesterday and nothing works today

```bash
./scripts/utilities/floci-storage-check.sh
```

`FAIL` in the shell block means a new terminal lost the course environment - Errata 01. `FAIL` on the
storage-mode check means Floci is running in `memory` mode and yesterday's work is gone; the fix is
the compose file, and the loss is unfortunately real.

If configuration survived and only the **metric data** is gone, that is Step 24's finding rather than
a failure - many builds persist resources and discard time series. Re-run
`./scripts/utilities/usms-emit-telemetry.sh` a few times and note it.

---

## 12. Floci vs Real AWS

### 12.1 Feature by feature

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `create-log-group`, `put-retention-policy` | Full lifecycle; retention enforced by deletion | Works; retention stored, expiry not enforced | **Implemented in Floci** |
| `create-log-stream`, `put-log-events` | Ingests, orders, indexes | Works; ordering and the rejection report behave correctly | **Implemented in Floci** |
| `filter-log-events`, `describe-log-streams` | Searches across streams | Works | **Implemented in Floci** |
| `test-metric-filter` | Evaluates a pattern against sample messages | Works, and is a pure function - no state involved | **Implemented in Floci** |
| `put-metric-filter` stored and retrievable | Yes | Yes | **Implemented in Floci** |
| Metric filter **evaluated on ingestion** | Every event, within seconds | Build-dependent; frequently not evaluated at all | **Floci Limitation** |
| `put-metric-data`, `list-metrics`, `get-metric-statistics` | Full | Works for custom metrics | **Implemented in Floci** |
| AWS-published metrics (`AWS/Lambda`, `AWS/ECS`, `AWS/ApplicationELB`, `AWS/EC2`) | Thousands, free, automatic | Few or none | **Floci Limitation** |
| `put-metric-alarm`, `describe-alarms`, `set-alarm-state`, alarm history | Full | Stored, transitionable, history kept | **Implemented in Floci** |
| Alarm **evaluation** against metric data | Once per period, automatically | Not performed - alarms never move on their own | **Floci Limitation** |
| Alarm **actions** (`--alarm-actions`) | SNS, auto scaling, EC2, Systems Manager | Accepted and never invoked | **Floci Limitation** |
| `put-composite-alarm`, rule storage | Full, with actions suppression | Stored; rule evaluation build-dependent | **Floci Limitation** |
| `put-dashboard`, `get-dashboard` | Stored, validated per widget, rendered | Stored and returned; nothing renders it | **Floci Limitation** |
| Logs Insights `start-query` / `get-query-results` | Full query language, server-side aggregation | Frequently absent | **Floci Limitation** |
| `xray put-trace-segments` | Indexed within seconds, merged by trace id | Build-dependent: full, storage-only, or absent | **Floci Limitation** |
| `xray get-trace-summaries` with filter expressions | Full expression language | Build-dependent; often returns everything or nothing | **Floci Limitation** |
| `xray get-service-graph` | Derived from segments, with edge statistics | Frequently empty even when segments were accepted | **Floci Limitation** |
| `xray create-sampling-rule` | Stored and polled by every instrumented process | Stored at best; never consumed | **Floci Limitation** |
| Lambda `TracingConfig Mode=Active` | Starts a segment per sampled invocation, records init as a subsegment | Configuration stored; no daemon, no segment, `_X_AMZN_TRACE_ID` often absent | **Floci Limitation** |
| Automatic subsegments from an instrumented SDK | Every AWS call and HTTP call, with no code change | Absent | **Conceptual / Real AWS** |
| CloudWatch agent on EC2 (memory, disk, custom logs) | Installed and configured on the instance | No agent, and `usms-web-01` is not a real VM | **Conceptual / Real AWS** |
| Container Insights, Lambda Insights | Managed, per-cluster and per-function performance metrics | Absent | **Conceptual / Real AWS** |
| Metric math, anomaly detection alarms | Full | Absent | **Conceptual / Real AWS** |
| Log group subscription filters to Kinesis or Firehose | Streams every event out in real time | Absent | **Conceptual / Real AWS** |
| Cross-account observability, CloudWatch Logs encryption with KMS | Available | Absent | **Conceptual / Real AWS** |
| Cost: per GB ingested, per metric, per alarm, per trace, per GB scanned by a query | Real, and the largest single driver of AWS observability bills | Free | **Conceptual / Real AWS** |

### 12.2 What you observed, and what you recorded

```text
OBSERVED - you saw this happen on your own machine
  · a log group created, given a retention policy, and read back
  · four log events written with millisecond timestamps and NONE rejected
  · a filter pattern tested against four real message shapes, matching exactly one
  · two metric filters deployed and attached to the correct log groups
  · custom metrics published with and without dimensions, and the difference visible
  · two observations of one metric in one period aggregating to SampleCount 2
  · a new function version published and an ALIAS REPOINTED, with the trigger untouched
  · an alarm created, forced from INSUFFICIENT_DATA to ALARM, and its history recorded
  · a composite alarm whose rule names two children
  · a dashboard document stored, returned, and checked for widget overlap
  · X-Ray segment documents constructed by hand and accepted  (on a supporting build)
  · two independently sent segments merged into one trace by shared trace id
  · every one of the above surviving a container restart

RECORDED - correct, checkable by reading, not executed here
  · the metric filter actually firing on ingestion   (build-dependent)
  · the alarm evaluating against data and moving on its own
  · the alarm action notifying anybody
  · the sampling rule being consumed by a running process
  · active tracing producing a segment from a real invocation
  · the IAM policy being enforced

NOT AVAILABLE AT ALL
  · AWS-published service metrics, and therefore any alarm on real infrastructure
  · a rendered dashboard
  · the CloudWatch agent, Container Insights, Lambda Insights
  · metric math, anomaly detection, subscription filters
  · latency distributions, error analytics, and cost
```

### 12.3 Where Floci is nicer than reality

These are the traps. Every one of them is something that worked here and will not work the same way
in production.

- **Everything is free.** This is the big one for observability specifically. Real CloudWatch bills
  for ingested log volume, for each custom metric, for each alarm, for each dashboard beyond three,
  and for each gigabyte an Insights query scans; X-Ray bills per trace recorded and per trace
  retrieved. A dimension with high cardinality, a log group with no retention policy, and a
  `filter` on `@message` across a month are each a real and quite large number. The decisions this
  lab made for teaching reasons - one namespace, low-cardinality dimensions, retention on every
  group - are the same decisions you would make for cost reasons.
- **Alarms never fire spuriously.** Here they do not fire at all. On real AWS a threshold set from
  five minutes of data will page somebody at 2am in week three, and `--datapoints-to-alarm` is the
  dial you will actually spend time on.
- **Metrics appear instantly.** Real custom metrics take up to a minute or two to become visible to
  `get-metric-statistics`, and an alarm evaluating a period that is not yet complete sees partial
  data. New alarms are routinely `INSUFFICIENT_DATA` for their first few periods, which is normal and
  looks broken.
- **Nothing is ever throttled.** `PutMetricData` has a request quota and `PutLogEvents` has a per-stream
  rate; exceeding either produces throttling that shows up as *missing telemetry*, which is the worst
  possible failure mode because it looks like the absence of a problem.
- **Log retention is stored, not applied.** Nothing here ever deletes an old event. On real AWS the
  14 days you set in Step 6 is the day your incident evidence disappears - which is an argument for
  a longer retention on anything auditable, and Exercise 4 asks you to make it.
- **A trace id is never propagated for you.** Here you generated them. In production the whole value
  comes from the id being carried across every hop, and a service that drops the header silently
  cuts every trace in half at that point.

!!! note "Floci Limitation - the one that shapes this whole lab"
    Floci stores observability configuration faithfully and evaluates almost none of it. Metric
    filters may not fire, alarms do not evaluate, actions do not invoke, sampling is not consumed,
    and dashboards are never drawn.

    Real AWS does all of that continuously, and that continuous evaluation is the entire product -
    nobody buys CloudWatch for its data model.

    What this lab gives you instead is every document and every configuration, constructed
    deliberately and checked statically: the filter pattern tested against real messages, the
    missing-data policy chosen for each alarm and justified, the composite rule, the dashboard
    layout, the segment structure, the sampling reservoir. Those are the parts you get wrong in
    production, and they are all checkable by reading. What you cannot claim from this lab is that
    any of your thresholds are the right numbers - thresholds come from data, and the data here is
    yours.

---
## 13. Independent Lab Exercises

Five exercises, increasing in difficulty. Record your commands and outputs in
`labs/lab-13-cloudwatch-xray/exercises.md`; several of them ask for a file in `outputs/` as well.

### Exercise 1 - Basic: extract a value instead of counting events

**Requirements**

Add a third metric filter, `usms-transcript-seconds`, on `/usms/central/application`, which publishes
`TranscriptSecondsFromLogs` into `USMS/Application` using the **value extracted from the log line**
rather than a constant. The `USMS_EVENT` lines written in Step 7 and by
`usms-emit-telemetry.sh` carry a `seconds` field.

**Constraints**

- Use `test-metric-filter` first and include its output in your exercises file. A filter you deployed
  without testing is not an answer to this exercise.
- Do not modify the existing `usms-central-errors` filter or its metric.
- You will discover that the `USMS_EVENT ` prefix makes the JSON filter dialect unavailable. Deal
  with it - either with the text dialect's positional extraction, or by changing what the emitter
  writes. Say which you chose and what it cost.

**Expected outcome**

```text
Expected result:
A filter whose metricValue is an extracted field rather than 1.
Fresh emitter runs producing TranscriptSecondsFromLogs data points whose values
match the seconds you passed on the command line.
A paragraph on why this metric and Step 11's TranscriptLagSeconds measure the same
thing by two different routes, and which you would keep.
```

**Hints**

- Step 8's table has both dialects. The JSON one needs the whole message to be JSON.
- `metricValue` accepts `$1`, `$2` for positional tokens in the text dialect and `$.field` in the
  JSON one.
- `scripts/utilities/usms-emit-telemetry.sh` is yours to change; it is in the repository for exactly
  this reason.

---

### Exercise 2 - Intermediate: make the dashboard portable and add a widget

**Requirements**

The `alarm` widget in Step 22 hard-codes `000000000000`. Rewrite
`templates/lab-13-dashboard.json` so that it is generated from `configs/lab-01.env`'s
`USMS_ACCOUNT_ID` and `configs/course.env`'s `AWS_REGION_COURSE` rather than containing either
literal. Then add a sixth widget showing `CentralErrorCount` over the last three hours with the
alarm threshold annotated, and re-`put` the dashboard.

**Constraints**

- The generator must be a re-runnable command sequence or a small script, not hand-editing.
- `put-dashboard` must return an empty `DashboardValidationMessages`.
- The overlap check from Step 22's verify must still pass with six widgets.
- `verify-lab-13.sh` checks for **5** widgets; update that check and say in your exercises file why
  a verification script that hard-codes a count is both useful and annoying.

**Expected outcome**

```text
Expected result:
A generated dashboard document containing no literal account id.
Six widgets, no overlaps, no validation messages.
verify-lab-13.sh back to FAIL=0 after your edit.
```

**Hints**

- Step 25's unquoted heredoc is the shape for a generator: the file contains values, not commands.
- Widget positions are grid units in a 24-column grid; the existing widgets end at `y=12`.
- A `metric` widget's `annotations.horizontal` is what draws the threshold line.

---

### Exercise 3 - Problem solving: are these thresholds defensible?

**Requirements**

Write `scripts/utilities/usms-threshold-report.sh` which, for every alarm in the account whose name
begins `usms-`, emits a single JSON document to stdout reporting: the alarm name, its namespace,
metric, statistic, period, evaluation periods, datapoints to alarm, threshold, comparison operator
and missing-data policy - and alongside those, the **actual observed** minimum, average, maximum and
sample count of that alarm's metric over the last 24 hours, plus a boolean `threshold_ever_breached`.

**Constraints**

- Valid JSON on stdout and nothing else; diagnostics go to stderr.
- Must run correctly from any directory.
- Must not fail under `set -u` when an alarm has no dimensions, or when a metric has no data.
- Do not hard-code the alarm list, and do not hard-code the metric names.
- A composite alarm has no metric. Handle it rather than crashing on it.

**Expected outcome**

```text
Expected shape:
[
  { "alarm": "usms-transcript-lag-high", "metric": "TranscriptLagSeconds",
    "statistic": "Maximum", "threshold": 2.0, "operator": "GreaterThanThreshold",
    "missing_data": "notBreaching",
    "observed": { "min": 0.31, "avg": 1.22, "max": 3.10, "samples": 7 },
    "threshold_ever_breached": true },
  ...
]
```

Three or four objects, one of which is the composite with nulls where a metric would be, and at least
one alarm whose threshold has **never** been approached - which is the finding the exercise exists
to produce.

**Hints**

- `describe-alarms` returns almost every configuration field you need in one call.
- `get-metric-statistics` needs the exact dimension set from the alarm; pass it through rather than
  rebuilding it.
- Building JSON by string concatenation in bash is how you produce invalid JSON. Pipe the AWS output
  into `python3` and build the document there.
- `${BASH_SOURCE[0]}` is how the other scripts in this repository find the root.

---

### Exercise 4 - Challenge: design the USMS observability plan

The registrar's office has had two bad weeks and has brought you four complaints. They have not
brought you a design.

> Nobody noticed for six hours that transcripts had stopped being delivered - the dashboard was all
> green because the graphs were empty. When we finally did notice, we could not tell whether it was
> the upload, the function or the bucket. The audit office then asked us who had downloaded a
> particular transcript in March and we could not answer, because the logs were gone. And our AWS
> bill for monitoring is now larger than our bill for the thing being monitored.

**Requirements**

Write `notes/lab-13-observability-plan.md` - two to three pages - that:

1. States, for each of the four complaints, which of the three layers - logs, metrics, traces -
   is the right answer, and why the other two are not.
2. Proposes a log group taxonomy for USMS with a retention period per group, and justifies the
   longest and the shortest. At least one group must exist solely to answer the audit question, and
   you must say who may read it.
3. Defines three **service level indicators** for transcript delivery, with a target for each, and
   says which of them you would alarm on and which you would only graph. An SLI you would not alarm
   on is not a wasted SLI - explain why.
4. Names every alarm you would create, with its missing-data policy, and identifies which single
   alarm would have caught the six-hour outage. Explain why a threshold alarm on a value could not
   have.
5. Estimates, in order of magnitude rather than precisely, where the monitoring bill is going, and
   names the two changes with the largest effect. State the cardinality of every dimension you
   propose.
6. Names one thing in your plan that you would **not** build yet, and the observation that would
   change your mind.

**Constraints**

- No commands. This is a design document.
- Every AWS feature you name must be one that exists; if you are unsure, say what you would verify
  and how.
- You must state at least one thing you would measure before committing to the design.
- Anywhere you propose a number - a threshold, a retention period, an SLO target - say where the
  number came from. "It seemed reasonable" is an acceptable answer stated honestly and is not
  acceptable left implicit.

**Expected outcome**

A document a colleague could implement from, in which the interesting paragraphs are the trade-offs
rather than the feature list. There is more than one defensible answer to point 3; there is only one
defensible attitude to point 6.

**Hints**

- Point 1's second complaint is the one with only one right answer, and this lab built it.
- Point 4 is Step 19's `--treat-missing-data` argument, applied to a real incident.
- Point 5: reread Section 12.3's first bullet and Step 11's paragraph on cardinality.
- An SLI is something a student would notice. "CPU utilisation" is not one.

---

### Exercise 5 - Integration: leave an alarm the next alerting lab can attach to

When an SNS/SQS integration lab is eventually written, the first thing it will do is give these alarms somewhere to
send a notification. It needs to know which alarms exist, what they mean, and what the action
document should look like - and it needs the notifier's `print()` to be ready to become a publish.

**Requirements**

1. Write `outputs/lab-13-alarm-actions-draft.json` describing, for each of the three alarms this lab
   created, the action you would attach: the alarm name, the human-readable meaning, the urgency
   (page or ticket), and a placeholder ARN of the shape
   `arn:aws:sns:us-east-1:<account>:usms-<topic>`. Use the real account id from
   `configs/lab-01.env`, not a literal.
2. Validate it: every alarm name in the document must be an alarm that currently exists, and every
   placeholder ARN must be well formed. Report any mismatch; do not fix it silently.
3. **Do not apply it.** `put-metric-alarm --alarm-actions` is Lab 09's step, and it is a replace
   operation - applying a partial alarm definition now would silently drop the configuration you
   spent Step 19 getting right.
4. Establish the baseline Lab 09 will compare against: run
   `./scripts/utilities/usms-emit-telemetry.sh` at least five times with a mix of faculties and
   latencies, then capture `get-metric-statistics` for `TranscriptLagSeconds` over the whole session
   into `outputs/lab-13-latency-baseline.json`. Lab 09's notification threshold should be argued from
   this file rather than invented.
5. Write `outputs/lab-13-alerting-readiness.txt` containing: the three alarm names and their
   missing-data policies; the composite alarm's rule; the metric namespace and the five metric names;
   the notifier's current alias version and tracing mode; whether X-Ray and Insights are supported on
   your build; the verification result from point 2; and the observed maximum latency from point 4.

**Constraints**

- `outputs/lab-13-alerting-readiness.txt` must be generated by a command sequence you can re-run, not
  typed by hand.
- Nothing in it may be a secret, but it stays in `outputs/` regardless - confirm with
  `git check-ignore -v`.
- The draft must remain unapplied. Verify with
  `aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high --query 'MetricAlarms[0].AlarmActions'`,
  which must return an empty list.

**Expected outcome**

```text
Expected result:
- outputs/lab-13-alarm-actions-draft.json exists, names three existing alarms, no literal account id
- AlarmActions on all three alarms is still []  - correct, a future alerting lab applies them
- outputs/lab-13-latency-baseline.json holds real observations, not invented numbers
- outputs/lab-13-alerting-readiness.txt exists, is git-ignored, and is reproducible
- verify-lab-13.sh still reports PASS=49  FAIL=0
```

**Hints**

- Lab 10 Exercise 5 built `outputs/lab-10-lab07-readiness.txt` the same way; that structure is worth
  copying.
- `aws cloudwatch describe-alarms --alarm-names A B C --query '...'` takes several names at once,
  which makes the validation in point 2 one call rather than three.
- Step 20's `{ ...; } | tee file` grouping is how you capture a multi-command report in one file.
- A well-formed SNS ARN has six colon-separated fields. `python3` and a regex is more honest than
  eyeballing it.

---

## 14. Lab Assessment Checklist

Tick these before you submit. Every one is checkable by a command you have already run.

**Environment and cumulative state**

- [ ] `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `verify-lab-10.sh` still reports `PASS=51  FAIL=0` - this lab changed the notifier and must not
      have broken it
- [ ] Every `configs/lab-NN.env` you have generated so far was sourced in Step 2 without error
- [ ] `whoami.sh` reports account `000000000000`

**Log layer**

- [ ] `/usms/central/application` exists with 30-day retention
- [ ] No log group whose name starts `/usms/` or `/aws/lambda/usms-` is left on never-expire
- [ ] At least five events in the central group, written with millisecond timestamps
- [ ] `outputs/lab-13-filter-test.json` shows a pattern tested against four real message shapes

**Metric layer**

- [ ] `usms-notify-count` and `usms-central-errors` are attached to the correct log groups
- [ ] `USMS/Application` contains all five metrics
- [ ] `TranscriptsProcessed` is published both with dimensions and without
- [ ] `outputs/lab-13-metric-readback.json` shows a data point, or the support probe records why not

**IAM**

- [ ] `USMSObservabilityWrite` exists and is attached to `usms-lambda-exec-role` and `usms-ec2-app-role`
- [ ] Its `PutMetricData` statement carries a `cloudwatch:namespace` condition
- [ ] Its log-group ARNs end in `:*`

**The instrumented function**

- [ ] `usms-transcript-notifier` has at least three versions
- [ ] `live` points at the traced version, not at Lab 10's version 1
- [ ] `TracingConfig.Mode` is `Active` on the alias
- [ ] The bucket notification from Lab 10 was **not** modified - confirm with
      `aws s3api get-bucket-notification-configuration`

**Alarms and dashboard**

- [ ] `usms-transcript-lag-high` uses `Maximum` and `notBreaching`
- [ ] `usms-notify-silence` uses `breaching`
- [ ] `outputs/lab-13-alarm-history.json` records a transition to `ALARM`
- [ ] Neither alarm is left in `ALARM`
- [ ] `usms-transcript-pipeline-down` names both children in its rule
- [ ] `usms-overview` has five widgets and no overlaps

**Traces**

- [ ] `templates/lab-13-segment-parent.json`, `-subsegments.json` and `-downstream.json` share one
      trace id
- [ ] Three subsegments, each with a deliberate `namespace`
- [ ] `templates/lab-13-sampling-rule.json` declares every required field
- [ ] `outputs/lab-13-trace-ids.txt` has at least four lines

**Persistence, artefacts and hygiene**

- [ ] `outputs/lab-13-pre-restart.txt` and `-post-restart.txt` are identical
- [ ] Metric data persistence was checked separately and the answer recorded either way
- [ ] `configs/lab-13.env` has 28 exports and no empty values
- [ ] `scripts/utilities/verify-lab-13.sh` reports `PASS=49  FAIL=0`
- [ ] `scripts/cleanup/lab-13-cleanup.sh` exists and has **not** been run
- [ ] `git status --short` shows no `outputs/` path and no `.zip`
- [ ] The commit from Step 26 exists

**Understanding**

- [ ] `notes/lab-13-notes.md` answers all six review questions in prose
- [ ] Exercises 1 to 5 are recorded in `labs/lab-13-cloudwatch-xray/exercises.md`
- [ ] `notes/lab-13-observability-plan.md` exists (Exercise 4)

### 14.1 In-class practical assessment

75 minutes, 100 marks. Open notes, open documentation. Your own repository only.

**Task A - build (30 marks).** Create a fourth alarm, `usms-edge-deny-spike`, on `EdgeDenyCount`
with `Stage=viewer-request`, which fires when more than 20 denials occur in five minutes across two
consecutive periods. Choose and justify its `--treat-missing-data`. Then add it as a third child of
`usms-transcript-pipeline-down` - and notice, before you do, whether that is actually the right
place for it. Marks: alarm exists and is correctly configured (10), missing-data choice justified in
writing (10), composite rule updated correctly **or** a written argument for why this alarm should
not be in that composite (10).

**Task B - diagnose (25 marks).** You are given the following and asked what is wrong and how you
would confirm it:

> A colleague's alarm has been in `INSUFFICIENT_DATA` for three days. The metric definitely has
> data - they can see it in `list-metrics`. Their alarm specifies namespace `USMS/Application`,
> metric `TranscriptLagSeconds`, statistic `Average`, period 60, `--unit Milliseconds`, and no
> dimensions. The metric is published by `usms-emit-telemetry.sh`.

Name every distinct reason the alarm cannot evaluate - there are three - and give one command per
reason that would have caught it. Marks: three faults named (15), three commands that genuinely
detect them (10).

**Task C - explain (25 marks).** In no more than 300 words in
`outputs/lab-13-assessment-c.md`: the same student identifier could reasonably go in a metric
dimension, a log field, or an X-Ray annotation. Explain what happens in each case, at a scale of
thirty thousand students, and state where it belongs and why. Your answer must use the word
cardinality correctly and must say what each of the three tools would cost you.

**Task D - verify (20 marks).** Run `./scripts/utilities/verify-lab-13.sh` and capture its output to
`outputs/lab-13-assessment-d.txt`. Then change exactly one alarm's `--treat-missing-data` to
`missing`, re-run, and write one sentence naming which check caught you and one sentence describing
the production incident that check exists to prevent. Restore the configuration. Marks: `FAIL=0`
before and after (10), the break-and-catch narrative (10).

---

## 15. Review Questions

Answer in prose in `notes/lab-13-notes.md`. No command output - these are about reasoning, and a
transcript of a terminal is not an answer to any of them.

**1.** A colleague says "we have logs, so we do not need metrics". Give the two strongest technical
arguments against, in terms of what each is cheap and expensive to do, and then describe the one
situation in which they are right.

**2.** Step 9 created a metric filter and Step 11 published a metric directly. Both produce numbers in
the same namespace. Compare them on four axes - retroactivity, cost, what has to change to add a new
measurement, and what happens when the code emitting the log is not yours. Then say which you would
use for "how many transcript downloads happened" and which for "how long the render took", and why
the answers are not the same.

**3.** `usms-transcript-lag-high` treats missing data as `notBreaching` and `usms-notify-silence`
treats it as `breaching`. Explain why the same setting would be wrong on the other alarm. Then
describe a single incident that the second alarm catches and the first cannot, and say what the
dashboard would have looked like during it.

**4.** Distinguish a **metric dimension** from an **X-Ray annotation**. Cover what each is indexed
for, what happens as the number of distinct values grows, and what you can ask of each. Then decide
where each of these belongs, with a sentence of justification: the faculty a transcript belongs to;
the student's id; the HTTP status returned by the origin; the name of the renderer that produced
the PDF.

**5.** Step 13 published version 2 and repointed an alias; Step 14 published version 3 for what was
only a configuration change. Explain why the configuration change needed its own version, and what
would have happened if you had changed `TracingConfig` and left the alias on version 2. Relate your
answer to Lab 10 Step 11's claim that a version freezes code and configuration.

**6.** Step 20 forced an alarm into `ALARM` rather than waiting for one. Explain what that does and
does not prove. Then say what an equivalent test would prove on real AWS that it cannot prove here,
and why testing the thing that happens *after* an alarm fires is worth doing even when you are
confident the threshold is right. Relate your answer to the course's rule that a command appearing
to succeed is not evidence that it did what you meant.

---

## 16. What We Built

### 16.1 The reflection

Three layers, and the interesting thing about them is not that there are three - it is that they
answer three different shapes of question, and that most of the skill is knowing which shape you
have.

**Metrics answer "how many, how fast, is it normal".** They are cheap to keep forever and cheap to
alarm on, and they are aggregated, which is the same thing as saying they have thrown away the
individual. A metric can tell you that eleven transcripts were slow this afternoon. It can never tell
you which eleven.

**Logs answer "what exactly happened".** They keep the individual, which is why they are expensive
and why every decision about them is a retention decision. They are searchable after the fact, which
metrics are not - a filter created today cannot count yesterday.

**Traces answer "where, across my whole system, did this one request go".** They are the only one of
the three that crosses service boundaries by construction, and the only one that can distinguish "the
function was slow" from "the function waited for the bucket".

The same fact - a student's transcript took nine seconds - belongs in all three, and in a different
form in each: as a data point in `TranscriptLagSeconds`, as a log line with the student id in it, and
as a segment with a subsegment breakdown. Step 11's `usms-emit-telemetry.sh` emits all three at once
on purpose, and the trace id in the log line is the join.

If you take one thing from this lab, take the cardinality question, because it is the one that
decides all of the above: **how many distinct values does this thing have?** Eight faculties is a
dimension. Thirty thousand students is a log field or an annotation, and putting it in a dimension
creates thirty thousand metrics and a bill. Every observability design mistake worth the name is a
cardinality mistake wearing a costume.

The second thing worth keeping is Step 19's asymmetry. Two alarms, on two metrics from the same
pipeline, with deliberately opposite missing-data policies - because a threshold alarm cannot see
silence, and silence is what most real outages look like from the monitoring side. An alarm on "too
many errors" is invisible when the errors stop arriving because nothing is running. That is the
failure that produces the sentence "our monitoring did not fire", and the fix is one flag chosen
deliberately.

And the third: Step 20. An alarm nobody has ever seen change state is a belief, not a control. The
forced transition proved the alarm was wired and recorded history - and Section 12 is explicit that
it did **not** prove the threshold is right, because the threshold comes from data and only Exercise
3 goes and looks. Distinguishing those two claims is the whole of the course's founding rule applied
to monitoring: a configuration that appears correct is not evidence that it does what you meant.

### 16.2 KEEP versus CLEAN UP

```text
╔═══════════════════════ KEEP ═══════════════════════╗    ╔════════════ CLEAN UP ════════════╗
║ /usms/central/application + retention              ║    ║ nothing.                          ║
║ retention on every other USMS log group            ║    ║                                   ║
║ usms-notify-count, usms-central-errors             ║    ║ This lab creates no temporary     ║
║ USMS/Application and all 5 metrics                 ║    ║ resources, no credentials and no  ║
║ USMSObservabilityWrite, on both roles              ║    ║ practice artefacts that conflict  ║
║ usms-transcript-notifier v2 and v3                 ║    ║ with anything later.              ║
║ alias live -> the traced version                   ║    ║                                   ║
║ usms-transcript-lag-high                           ║    ║ The forced alarm states from     ║
║ usms-notify-silence                                ║    ║ Steps 20 and 21 were already     ║
║ usms-transcript-pipeline-down                      ║    ║ restored in those steps - that   ║
║ usms-overview dashboard                            ║    ║ is the only undo this lab needs. ║
║ usms-transcripts-sampling                          ║    ║                                   ║
║ configs/lab-13.env, templates/lab-13-*.json        ║    ║ Do NOT delete version 1 of the   ║
║ usms-emit-telemetry.sh, verify-lab-13.sh           ║    ║ notifier. It is your rollback.   ║
║ outputs/lab-13-*  (git-ignored, but keep on disk)  ║    ║                                   ║
╚════════════════════════════════════════════════════╝    ╚═══════════════════════════════════╝
```

Two things to check before you finish.

If you did the Step 13 Your-turn, confirm `live` is pointing **forward** again, not at version 1:

```bash
aws lambda get-alias --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text
```

And confirm neither alarm was left in the state you forced it into:

```bash
aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high usms-notify-silence \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output text
```

Both are checked by `verify-lab-13.sh`, which is why its count is 49 rather than 47.

### 16.3 The end-of-course cleanup script

!!! danger "DO NOT RUN THIS NOW"
    **What will be deleted:** three alarms including the composite, the dashboard, both metric
    filters, the central log group **and every log event in it**, the retention policies on the other
    groups, the X-Ray sampling rule, and the `USMSObservabilityWrite` policy after detaching it from
    two roles.

    **What depends on it:** a future alerting lab (not yet written) attaches SNS actions to all three alarms by name, and publishes
    into the `USMS/Application` namespace.

    **Reversible?** Partly. The configuration can be recreated by re-running this lab. Log events,
    metric data points and alarm history cannot - alarm history is two weeks at most and deleting a
    log group deletes its contents immediately.

    **Effect on later labs:** total for Lab 09, which would have nothing to notify about. This script
    exists for the end of the course, when you are dismantling the environment deliberately.

    Note what it does **not** delete: the notifier's versions, the Lab 10 bucket notification, and
    `/aws/lambda/usms-transcript-notifier` itself. Those belong to Lab 10 and `lab-10-cleanup.sh`
    owns them.

Write it now and do not run it:

```bash
cat > scripts/cleanup/lab-13-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END-OF-COURSE CLEANUP for Lab 13. Deletes dependencies inside-out.
# DO NOT RUN while Lab 09 or anything after it still needs these alarms.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-13.env" 2>/dev/null || true

CENTRAL="${USMS_LOG_GROUP_CENTRAL:-/usms/central/application}"
FN_LOG="${USMS_LOG_GROUP_NOTIFIER:-/aws/lambda/usms-transcript-notifier}"

cat << 'WARN'
This will permanently delete:
  - usms-transcript-pipeline-down (composite), and its two child alarms
  - ALL alarm history for them, which is not recoverable
  - the usms-overview dashboard
  - the usms-notify-count and usms-central-errors metric filters
  - /usms/central/application AND EVERY LOG EVENT IN IT
  - the usms-transcripts-sampling X-Ray rule
  - USMSObservabilityWrite, after detaching it from two roles

A future alerting lab (not yet written) attaches SNS actions to those alarms by name.
Metric DATA already published into USMS/Application is not deleted by this
script and cannot be deleted at all - CloudWatch metrics expire, they are
never removed. That is worth knowing and is not a bug.
WARN

printf 'Type exactly: DELETE USMS OBSERVABILITY\n> '
read -r CONFIRM
[ "$CONFIRM" = "DELETE USMS OBSERVABILITY" ] || { echo "aborted"; exit 1; }

echo "1/7 deleting the composite alarm first (it references the others)"
aws cloudwatch delete-alarms --alarm-names usms-transcript-pipeline-down 2>/dev/null \
  && echo "    deleted usms-transcript-pipeline-down" \
  || echo "    already absent"

echo "2/7 deleting the child alarms"
aws cloudwatch delete-alarms \
  --alarm-names usms-transcript-lag-high usms-notify-silence 2>/dev/null \
  && echo "    deleted both metric alarms" \
  || echo "    already absent"

echo "3/7 deleting the dashboard"
aws cloudwatch delete-dashboards --dashboard-names usms-overview 2>/dev/null \
  && echo "    deleted usms-overview" \
  || echo "    already absent"

echo "4/7 deleting the metric filters (stops new data first)"
aws logs delete-metric-filter --log-group-name "$FN_LOG" \
  --filter-name usms-notify-count 2>/dev/null || true
aws logs delete-metric-filter --log-group-name "$CENTRAL" \
  --filter-name usms-central-errors 2>/dev/null || true

echo "5/7 deleting the central log group and its events"
aws logs delete-log-group --log-group-name "$CENTRAL" 2>/dev/null \
  && echo "    deleted $CENTRAL" \
  || echo "    already absent"

echo "6/7 deleting the X-Ray sampling rule"
aws xray delete-sampling-rule --rule-name usms-transcripts-sampling 2>/dev/null \
  && echo "    deleted usms-transcripts-sampling" \
  || echo "    already absent or unsupported"

echo "7/7 detaching and deleting USMSObservabilityWrite"
OBS_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSObservabilityWrite'].Arn | [0]" --output text 2>/dev/null)
if [ -n "$OBS_ARN" ] && [ "$OBS_ARN" != "None" ]; then
  for role in usms-lambda-exec-role usms-ec2-app-role; do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$OBS_ARN" 2>/dev/null \
      && echo "    detached from $role" || true
  done
  aws iam delete-policy --policy-arn "$OBS_ARN" 2>/dev/null \
    && echo "    deleted USMSObservabilityWrite" \
    || echo "    could not delete - check for remaining attachments"
fi

echo
echo "NOT deleted, deliberately:"
echo "  - the notifier's versions and alias (Lab 10 owns them)"
echo "  - /aws/lambda/usms-transcript-notifier (Lambda recreates it anyway)"
echo "  - retention policies on groups this lab did not create"
echo "  - metric data in USMS/Application (CloudWatch metrics cannot be deleted)"
EOF

chmod +x scripts/cleanup/lab-13-cleanup.sh
bash -n scripts/cleanup/lab-13-cleanup.sh && echo "syntax OK - and do not run it"
```

Three things about the order, because the order is the lesson:

**The composite alarm goes first.** It references the two child alarms, and deleting a child while a
composite rule names it leaves a composite that cannot evaluate. AWS permits it and the result is
useless. Delete the thing that points, then the thing pointed at.

**The metric filters go before the log group.** Deleting a log group removes its filters implicitly,
but doing it explicitly and in that order means you can see it happen, and it is the habit that
matters on a group you are keeping.

**`delete-log-group` deletes the events immediately and there is no confirmation.** There is no soft
delete, no recycle bin and no export step built in. If the events matter, they had to have been
streamed somewhere else before this point - which is the argument for subscription filters, listed
in Section 12 as conceptual.

And one thing that is not in the script at all: **you cannot delete a CloudWatch metric.** There is
no API for it. Metrics expire after fifteen months of no new data and that is the only way they go
away. A metric published into the wrong namespace, or with a mistaken dimension, is there until it
ages out - which is one more reason to think about cardinality before the first `put-metric-data`
rather than after.

### 16.4 The architecture, now

```text
  IAM (Lab 01, extended here)                    NETWORK (Lab 02)
   ├── usms-lambda-exec-role                       ├── usms-vpc, 4 subnets
   │     USMSLambdaBasic                           └── usms-s3-endpoint ───┐
   │   + USMSObservabilityWrite   ← Lab 13                                 │
   ├── usms-ec2-app-role                                                   │
   │     USMSStudentDataReadWrite                                          │
   │   + USMSObservabilityWrite   ← Lab 13                                 v
   └── USMSStudentDataReadWrite ────────────────→  usms-student-data (Lab 10)
                                                     transcripts/evidence/*
                                                     notification: ObjectCreated
                                                            │
  EDGE (Lab 10, unchanged)                                  v
   ├── usms-edge-viewer-request:1        usms-transcript-notifier:live ──→ 3
   ├── usms-edge-origin-response:1          v1 Lab 10 · v2 instrumented · v3 traced
   └── usms-transcript-cdn                  TracingConfig: Active
                                                    │
  OBSERVABILITY (Lab 13)                            │ print() + put_metric_data()
   ┌────────────────────────────────────────────────┴──────────────────────────┐
   │  LOGS                     METRICS                    TRACES               │
   │  /usms/central/app 30d    USMS/Application            1-<epoch>-<rand>     │
   │  /usms/ecs/enrol   30d      NotifyCount        ←filter  segment: notifier  │
   │  /aws/lambda/...   14d      CentralErrorCount  ←filter    3 subsegments    │
   │       │                     TranscriptsProcessed        segment: bucket    │
   │       └── 2 metric filters  TranscriptLagSeconds        sampling rule      │
   │                             EdgeDenyCount                                  │
   └───────────────────────────────┬───────────────────────────────────────────┘
                                   v
        usms-transcript-lag-high ──┐
        usms-notify-silence ───────┴──→ usms-transcript-pipeline-down ──→ (future lab: SNS)
                                   │
                                   └──→ usms-overview  (5 widgets)

  COMPUTE (Labs 03, 04-C, 07-B)   ← unchanged by this lab, now with retention on its logs
   ├── usms-web-01, usms-db-01
   ├── usms-ecs-cluster / usms-enrolment-svc / usms-enrolment-alb
   └── usms-eks-cluster / usms-enrolment-hpa          (EKS deployment target)
```

---

## 17. Preparation for the Next Lab

There is no Lab 14 written yet. The natural next lab, when it is written, is an SNS/SQS integration
lab that finally gives the notifier somewhere to notify. Since Lab 10 Step 17 the handler has had a
`notify()` function whose docstring says *Later: sns.publish(...)*, and three alarms now exist with
no actions attached. That future lab connects both.

### What that future lab will consume

| Artefact | From | How it will use it |
| --- | --- | --- |
| `USMS_ALARM_LAG_HIGH`, `USMS_ALARM_NOTIFY_SILENCE`, `USMS_ALARM_COMPOSITE` | `configs/lab-13.env` | Attaches `--alarm-actions` to the composite and `--no-actions-enabled` to the children |
| `outputs/lab-13-alarm-actions-draft.json` | Exercise 5 | **Applies** it - the step this lab deliberately did not take |
| `outputs/lab-13-latency-baseline.json` | Exercise 5 | Argues the notification threshold from observed data rather than inventing one |
| `USMS/Application` and its five metrics | Step 9, Step 11 | Publishes a queue-depth metric into the same namespace, and adds it to `usms-overview` |
| `usms-overview` | Step 22 | Adds widgets to the existing dashboard rather than creating a second one |
| `usms-transcript-notifier` v3 and alias `live` | Steps 13, 14 | Publishes v4 with a real `sns.publish` in `notify()` and repoints the alias - the second time this session's alias mechanism earns its keep |
| `USMSObservabilityWrite` | Step 12 | The pattern to copy for `USMSMessagingWrite`; the observability policy itself grows by nothing |
| `/usms/central/application` | Step 6 | Where the SQS consumer writes, so that one filter already counts it |
| `usms-lambda-exec-role` | Lab 01 | Gets one more policy, still without editing `USMSLambdaBasic` |

### The thing that future lab must be careful about

`put-metric-alarm` **replaces** the alarm. If a later command adds `--alarm-actions` to
`usms-transcript-lag-high` using only the name, the metric and the action, every other setting -
`Maximum`, the 2-of-3 evaluation, `notBreaching` - reverts to a default or disappears. The sequence
has to be describe, merge, put.

That is the same shape as `put-bucket-notification-configuration` in Lab 10 and
`update-assume-role-policy` before it. The category is now large enough to name and worth committing
to memory: `put-metric-alarm`, `put-composite-alarm`, `put-dashboard`,
`put-bucket-notification-configuration`, `put-bucket-policy`, `update-assume-role-policy`,
`update-function-configuration`. **Every one of them will happily delete something you did not
mention**, and every one of them returns success when it does.

### Pre-session checks

Run these before the next session. All five should pass.

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-10.sh | tail -2          # PASS=51  FAIL=0
./scripts/utilities/verify-lab-13.sh | tail -2          # PASS=49  FAIL=0
grep -c '^export' configs/lab-13.env                    # 28
aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high \
  --query 'MetricAlarms[0].AlarmActions' --output json  # []  - correct, unfilled until that future lab
aws lambda get-alias --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text               # 3, or higher
```

If `verify-lab-10.sh` now fails where it used to pass, this lab broke something Lab 10 built -
almost certainly the alias, and almost certainly because the Step 13 Your-turn rollback was never
rolled forward. Fix that before the next session rather than during it.

### Snapshot before you finish

```bash
floci snapshot save lab-13-complete
floci snapshot list
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-13.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

### Read ahead

Three things, each of which Lab 09 assumes you have thought about for five minutes:

- **A topic is not a queue.** Find out what "fan-out" means and why SNS and SQS are usually used
  together rather than as alternatives.
- **At-least-once delivery.** Work out what it means for the notifier that the same message may
  arrive twice, and what the handler would have to do about it. The answer has a name.
- **A dead letter queue is a monitoring object as much as a messaging one.** Think about which of
  this lab's three layers you would use to notice that one is filling up, and what the alarm's
  `--treat-missing-data` would have to be.

---
## Appendix A - Command Reference

Everything this lab used, in the order you met it.

**CloudWatch Logs - `aws logs`**

| Command | What it does here |
| --- | --- |
| `aws logs describe-log-groups --log-group-name-prefix P` | Lists groups. `retentionInDays` is absent when retention is never |
| `aws logs create-log-group --log-group-name G` | Creates one. A service will also create one by writing to it |
| `aws logs put-retention-policy --log-group-name G --retention-in-days N` | Sets expiry. `N` comes from a fixed set |
| `aws logs tag-resource --resource-arn A --tags K=V` | Tags a group by ARN. `tag-log-group` is the deprecated form |
| `aws logs create-log-stream --log-group-name G --log-stream-name S` | Creates a stream |
| `aws logs describe-log-streams --log-group-name G --order-by LastEventTime --descending` | Finds the most recently written stream |
| `aws logs put-log-events --log-group-name G --log-stream-name S --log-events timestamp=MS,message=M` | Writes events. **Milliseconds**, in order. Read `rejectedLogEventsInfo` |
| `aws logs filter-log-events --log-group-name G --filter-pattern P` | Searches across every stream in a group |
| `aws logs test-metric-filter --filter-pattern P --log-event-messages M...` | Dry-runs a pattern. Touches nothing, costs nothing |
| `aws logs put-metric-filter --log-group-name G --filter-name F --filter-pattern P --metric-transformations ...` | Standing rule: matching events become a metric |
| `aws logs describe-metric-filters` | Lists filters and the group each is attached to |
| `aws logs delete-metric-filter --log-group-name G --filter-name F` | Removes one |
| `aws logs start-query --log-group-name G --start-time T --end-time T --query-string Q` | Begins an Insights query. **Asynchronous** |
| `aws logs get-query-results --query-id Q` | Polls it. Poll until `status` is `Complete` |
| `aws logs delete-log-group --log-group-name G` | Deletes the group **and every event in it**, immediately |

**CloudWatch metrics, alarms and dashboards - `aws cloudwatch`**

| Command | What it does here |
| --- | --- |
| `aws cloudwatch put-metric-data --namespace N --metric-data ...` | Publishes data points. Shorthand or `file://` |
| `aws cloudwatch list-metrics --namespace N [--metric-name M]` | Lists metrics and their dimension sets |
| `aws cloudwatch get-metric-statistics --namespace N --metric-name M --dimensions ... --period P --statistics ...` | Reads a time series. Dimensions must match **exactly** |
| `aws cloudwatch put-metric-alarm --alarm-name A ...` | Creates **or replaces** an alarm. There is no update call |
| `aws cloudwatch describe-alarms --alarm-names A` | Reads metric alarms |
| `aws cloudwatch describe-alarms --alarm-types CompositeAlarm` | Reads composite alarms - they do not appear without this |
| `aws cloudwatch set-alarm-state --alarm-name A --state-value S --state-reason R` | Forces a state, to test what happens next |
| `aws cloudwatch describe-alarm-history --alarm-name A --history-item-type StateUpdate` | The last two weeks of transitions |
| `aws cloudwatch put-composite-alarm --alarm-name A --alarm-rule R` | An alarm over other alarms |
| `aws cloudwatch put-dashboard --dashboard-name D --dashboard-body file://F` | Stores a widget document. Read `DashboardValidationMessages` |
| `aws cloudwatch get-dashboard --dashboard-name D` | Returns the body as a **JSON string inside a JSON field** |
| `aws cloudwatch list-dashboards` | Names and sizes |
| `aws cloudwatch delete-alarms --alarm-names A...` | Deletes alarms. Composite first |
| `aws cloudwatch delete-dashboards --dashboard-names D...` | Deletes dashboards |

**X-Ray - `aws xray`**

| Command | What it does here |
| --- | --- |
| `aws xray put-trace-segments --trace-segment-documents 'JSON'...` | Sends segments. A **list of strings**. Read `UnprocessedTraceSegments` |
| `aws xray get-trace-summaries --start-time T --end-time T [--filter-expression E]` | Searches by **time window**, not by id |
| `aws xray batch-get-traces --trace-ids ID...` | Fetches full traces by id, up to five |
| `aws xray get-service-graph --start-time T --end-time T` | The derived map. You never declare an edge |
| `aws xray get-sampling-rules` | Lists rules, including the undeletable `Default` |
| `aws xray create-sampling-rule --sampling-rule file://F` | Creates one. Every field is required |
| `aws xray delete-sampling-rule --rule-name R` | Removes one |

**Lambda and IAM, used here for what they contribute to telemetry**

| Command | What it does here |
| --- | --- |
| `aws lambda update-function-code --function-name F --zip-file fileb://Z` | Replaces the code on `$LATEST` only |
| `aws lambda update-function-configuration --function-name F --tracing-config Mode=Active` | Turns on active tracing - a configuration change, so it needs its own version |
| `aws lambda wait function-updated-v2 --function-name F` | Blocks until an update has applied. Publishing before it does gives you the old code |
| `aws lambda publish-version --function-name F` | Freezes code **and** configuration |
| `aws lambda update-alias --function-name F --name N --function-version V` | The deployment, and the rollback |
| `aws iam create-policy --policy-name P --policy-document file://F` | A new policy per concern, rather than editing a shared one |
| `aws iam attach-role-policy --role-name R --policy-arn A` | Additive; the existing policies stay |
| `aws iam get-policy-version --policy-arn A --version-id V` | Reads the document, which is how you judge a policy Floci does not enforce |

**Local tools**

| Command | What it does here |
| --- | --- |
| `python3 -c 'import time; print(int(time.time()*1000))'` | Epoch milliseconds, portably. `date +%s%3N` is GNU-only |
| `python3 -c 'import os; print(os.urandom(12).hex())'` | Hex identifiers of an exact length |
| `python3 - ARG << 'PY'` | An inline program taking a shell value as `sys.argv[1]` without interpolation |
| `python3 -m json.tool F` | Validates and pretty-prints JSON |
| `python3 -m py_compile F.py` | Syntax-checks Python without running it |
| `python3 -m zipfile -c A.zip FILE` / `-l A.zip` | Builds and lists a deployment archive |
| `openssl base64 -d -A` | Portable base64 decode. GNU uses `-d`, BSD uses `-D` |
| `awk 'END {print $1}' F` | Last line, first field, in one process |

---

## Appendix B - New JMESPath and CLI Patterns Introduced

Everything here is new to the course at Lab 13. Patterns from Labs 1 to 6 are assumed and are not
repeated.

**Shorthand argument syntax**

| Pattern | Meaning |
| --- | --- |
| `--metric-data 'MetricName=M,Unit=U,Value=V,Dimensions=[{Name=N,Value=V}]'` | A list of structures containing a nested list of structures - the deepest the CLI shorthand goes |
| `--metric-transformations metricName=M,metricNamespace=N,metricValue=1,defaultValue=0` | Lower-camel keys, unlike most shorthand in this course. `defaultValue` is what makes a gap a zero |
| `--tags Key=Project,Value=USMS Key=Lab,Value=08` | CloudWatch alarms take **space-separated** `Key=`/`Value=` pairs - a fourth tagging syntax after Lambda's, S3's and EC2's |
| `--tracing-config Mode=Active` | A one-key structure |
| `--dimensions Name=Stage,Value=notify` | Must match the published set **exactly**; a subset matches nothing |

**Parameter and time handling**

| Pattern | Meaning |
| --- | --- |
| `timestamp=<epoch ms>` in `--log-events` | CloudWatch Logs takes **milliseconds as an integer** |
| `"start_time": <epoch seconds as float>` in a segment | X-Ray takes **seconds as a float**. Two services, two units, no warning either way |
| `--start-time`/`--end-time` as ISO-8601 (`cloudwatch`) or epoch seconds (`xray`) | Also different between the two services |
| `WINDOW=$(python3 -c '...'); START=${WINDOW% *}; END=${WINDOW#* }` | Both ends of a time window from one process, split with parameter expansion |
| `date -u -d '-5 minutes' \|\| date -u -v-5M` | GNU and BSD date, in that order. This lab then stops using `date` for arithmetic entirely |

**JMESPath**

| Pattern | Meaning |
| --- | --- |
| `logGroups[?logGroupName=='X'] \| length(@)` | Filter, then apply a function through a pipe - turns a prefix match into an exact one |
| `logGroups[?retentionInDays==null].logGroupName` | Filter on a field being **absent**. The comparison is against `null`, not against the string `None` |
| `keys(Annotations)` | An object's key names, without their values |
| `join(`,`, Dimensions[].Name) \|\| `NONE`` | Flatten a list to a string, with a literal fallback when it is empty |
| `Metrics[].join(`,`, Dimensions[].Name)` | A function applied inside a projection |
| `results[].[ [0].value, [1].value ]` | Positional navigation of Insights results, which are lists of `{field, value}` rather than objects |
| `MetricAlarms[0].StateValue` built as `"MetricAlarms[0].$2"` in a shell function | Composing a query string from a parameter, to avoid repeating a command five times |

**Response fields that report partial failure on a successful call**

This lab has four of them, and recognising the category is worth more than memorising the list.

| Field | Returned by | Means |
| --- | --- | --- |
| `rejectedLogEventsInfo` | `put-log-events` | Some events were outside the ingestion window |
| `UnprocessedTraceSegments` | `put-trace-segments` | Some segment documents were malformed |
| `DashboardValidationMessages` | `put-dashboard` | The dashboard was created; some widgets will not render |
| (silence) | `put-metric-data` | Nothing is returned at all - the only check is reading the metric back |

**Shell**

| Pattern | Meaning |
| --- | --- |
| `( source configs/lab-13.env && echo ok )` | Source in a subshell so a broken file cannot damage your environment |
| `set_retention() { ... }` over a list of possibly-absent resources | A function reporting `absent, skipped` beats a loop that aborts or a silent `\|\| true` |
| `\| head -1` after a paginated `--max-items 1` | Stops a `NextToken` line becoming part of an `export` value |
| `\| grep -E '^1-' \|\| echo none` | Turn a `None` into an honest sentinel before it reaches a config file |
| `cmd --query 'Field' --output text \| python3 -c ...` | For fields that contain JSON **as a string** - `get-dashboard` and `lambda get-policy` both do this |

**Concepts with no command**

| Idea | Where it appeared |
| --- | --- |
| Log group as a unit of retention and access control, not of component | Step 6 |
| A marker string becoming an interface once a filter depends on it | Step 7, Step 9 |
| Filter patterns are not regular expressions; Insights `filter` is | Steps 8, 23 |
| A metric's identity is namespace + name + the complete dimension set | Step 11 |
| Cardinality is cost, and where a high-cardinality value belongs instead | Steps 11, 15 |
| Add a policy per concern rather than editing a shared one; the five-version cap | Step 12 |
| `PassThrough` versus `Active`: who owns the sampling decision | Step 14 |
| Trace, segment, subsegment, and `namespace` deriving the service graph | Steps 15, 16, 17 |
| Annotation versus metadata: indexed and searchable, or neither | Steps 15, 17 |
| Reservoir plus rate, and rule priority | Step 18 |
| Missing data as a first-class alarm decision; alarming on an absence | Step 19 |
| Forcing a state transition to test what happens after the alarm | Step 20 |
| Composite alarms for aggregation and for suppression | Step 21 |
| A dashboard is a document, and belongs in version control | Step 22 |
| Replace-only APIs, now a named category of seven | Section 17 |

---

## Appendix C - Project Implementation Checkpoint 1

This is the first assessed submission of the individual project, and it falls here because this is
the first point in the course at which your system can be **demonstrated** rather than merely listed.
The full brief - scope, rubric, demonstration protocol and submission mechanics - is
`docs/Lab/project-checkpoint-01.md`. What follows is the part that lives in your repository.

### C.1 What the checkpoint asks for, in one paragraph

You have built, over seven practicals, a partial implementation of USMS. Checkpoint 1 asks you to
show that it is **one system rather than seven exercises**: that the resources exist, that they
reference each other, that you can demonstrate one end-to-end path through them, and that you can
say what is not built yet and what you would do next. It is marked on evidence and on judgement, not
on how much you have built - everyone has built the same labs.

### C.2 The directory, and what is committed

```text
project/checkpoint-01/
├── architecture.md            # 2–3 pages, committed
├── inventory.txt              # GENERATED by the script below, committed
├── evidence/                  # committed - small text and JSON only
│   ├── verify-lab-10.txt
│   ├── verify-lab-13.txt
│   ├── end-to-end.txt
│   └── telemetry-inventory.txt
├── gaps.md                    # what is not built, and what you would do next
└── demo.md                    # the 8-minute path you will walk through
```

Everything in `project/checkpoint-01/` **is** committed, which makes it the exception to this course's
usual rule - and the reason is that it is a submission rather than a working artefact. Two
consequences you must respect:

- **No secrets, ever.** Not an access key, not a `.env` from the repository root, not a screenshot
  with one in the corner. The values are Floci dummies and the habit is what is being assessed.
- **No large files.** Evidence is text and JSON. A screenshot belongs in `screenshots/`, which the
  course already has, and `demo.md` links to it.

Confirm before you commit:

```bash
git check-ignore -v project/checkpoint-01/inventory.txt \
  && echo "PROBLEM: this file is ignored and will not be submitted" \
  || echo "correct - project/ is committed"

grep -rIlE 'AKIA|aws_secret_access_key|SecretAccessKey' project/ && echo "STOP: secret found" \
  || echo "no secret patterns found"
```

The `grep` is a floor, not a guarantee. Read what you are committing.

### C.3 The inventory script

The one thing the checkpoint asks for that you do not already have is a single command that describes
the whole system. Write it once and it serves the checkpoint, the final submission and every "what
did I build" question for the rest of the course.

```bash
cat > scripts/utilities/usms-project-inventory.sh << 'EOF'
#!/usr/bin/env bash
# One description of the whole USMS system, across every practical.
# Read-only. Safe to run at any time. Writes nothing except its own stdout.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
for f in configs/lab-*.env; do
  # shellcheck disable=SC1090
  [ -f "$f" ] && source "$f"
done

section() { printf '\n== %s ==\n' "$1"; }
count()   { printf '%s' "${1:-0}"; }

printf 'USMS project inventory - %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'account : %s\n' "$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo UNREACHABLE)"
printf 'endpoint: %s\n' "${FLOCI_ENDPOINT:-unset}"

section "identity (Lab 01)"
aws iam list-roles --query "Roles[?starts_with(RoleName, 'usms-')].RoleName" --output text | tr '\t' '\n'
aws iam list-policies --scope Local --query "Policies[?starts_with(PolicyName, 'USMS')].PolicyName" --output text | tr '\t' '\n'

section "network (Lab 02)"
aws ec2 describe-vpcs --filters Name=tag:Project,Values=USMS \
  --query 'Vpcs[].[VpcId,CidrBlock]' --output text 2>/dev/null || echo "none"
aws ec2 describe-subnets --filters Name=tag:Project,Values=USMS \
  --query 'length(Subnets)' --output text 2>/dev/null || echo 0

section "compute (Labs 03, 04, 05)"
aws ec2 describe-instances --filters Name=tag:Project,Values=USMS \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output text 2>/dev/null || echo "none"
aws ecs list-clusters --query 'clusterArns' --output text 2>/dev/null || echo "none"
aws eks list-clusters --query 'clusters' --output text 2>/dev/null || echo "none"

section "storage and functions (Lab 10)"
aws s3api list-buckets --query "Buckets[?starts_with(Name, 'usms-')].Name" --output text 2>/dev/null
aws lambda list-functions \
  --query "sort_by(Functions[?starts_with(FunctionName, 'usms-')], &FunctionName)[].[FunctionName,Runtime,TracingConfig.Mode]" \
  --output text 2>/dev/null || echo "none"

section "pipeline (Labs 11, 12)"
aws codepipeline list-pipelines --query 'pipelines[].name' --output text 2>/dev/null || echo "none"
aws codebuild list-projects --query 'projects' --output text 2>/dev/null || echo "none"
aws ecr describe-repositories --query 'repositories[].repositoryName' --output text 2>/dev/null || echo "none"

section "observability (Lab 13)"
aws logs describe-log-groups \
  --query 'logGroups[].[logGroupName,retentionInDays]' --output text 2>/dev/null
aws cloudwatch list-metrics --namespace USMS/Application \
  --query 'Metrics[].MetricName' --output text 2>/dev/null | tr '\t' '\n' | sort -u
aws cloudwatch describe-alarms \
  --query 'MetricAlarms[].[AlarmName,StateValue,TreatMissingData]' --output text 2>/dev/null
aws cloudwatch describe-alarms --alarm-types CompositeAlarm \
  --query 'CompositeAlarms[].AlarmName' --output text 2>/dev/null
aws cloudwatch list-dashboards --query 'DashboardEntries[].DashboardName' --output text 2>/dev/null

section "repository"
printf 'lab documents   : %s\n' "$(ls -d labs/lab-* 2>/dev/null | wc -l | tr -d ' ')"
printf 'env files       : %s\n' "$(ls configs/lab-*.env 2>/dev/null | wc -l | tr -d ' ')"
printf 'verify scripts  : %s\n' "$(ls scripts/utilities/verify-lab-*.sh 2>/dev/null | wc -l | tr -d ' ')"
printf 'cleanup scripts : %s\n' "$(ls scripts/cleanup/lab-*-cleanup.sh 2>/dev/null | wc -l | tr -d ' ')"
printf 'commits         : %s\n' "$(git rev-list --count HEAD 2>/dev/null || echo 0)"
printf 'tracked secrets : %s\n' "$(git ls-files outputs/ | grep -cv '.gitkeep' || echo 0)"

section "verification"
for v in scripts/utilities/verify-lab-*.sh; do
  [ -x "$v" ] || continue
  printf '%-40s %s\n' "$v" "$("$v" 2>/dev/null | tail -1)"
done
EOF

chmod +x scripts/utilities/usms-project-inventory.sh
bash -n scripts/utilities/usms-project-inventory.sh && echo "syntax OK"

./scripts/utilities/usms-project-inventory.sh | tee project/checkpoint-01/inventory.txt
```

**What the script does**

`for f in configs/lab-0*.env; do ... done` is the one place in this course that a glob over the env
files is the right call: this script's job is to describe whatever is there, so sourcing whatever is
there is the job rather than a shortcut. Every other script names them, for the reason Lab 10 Step 2
gave.

Every AWS call ends `2>/dev/null || echo "none"` or similar. By this point every student has built
both `usms-ecs-cluster` and `usms-eks-cluster`, but resources from earlier labs get cleaned up over
the course of thirteen labs, and an inventory should not assume any one of them is still there. An
inventory that aborts on the first absent service is useless. Reporting `none` is a result.

`tracked secrets` counts files under `outputs/` that Git knows about. It should be `0`. If it is not,
stop and fix the `.gitignore` before submitting anything.

The last section runs every verification script you have and prints its final line, so that one
command answers "does everything I have built still work".

**Expected result - the shape, not the values**

```text
USMS project inventory - 2026-09-17T06:22:14Z
account : 000000000000
endpoint: http://localhost:4566

== identity (Lab 01) ==
usms-ec2-app-role
usms-lambda-exec-role
usms-developer-role
...
== pipeline (Labs 11, 12) ==
usms-enrolment-pipeline
usms-enrolment-build
usms-enrolment
...
== observability (Lab 13) ==
/usms/central/application	30
...
== verification ==
scripts/utilities/verify-lab-02.sh        PASS=23  FAIL=0
scripts/utilities/verify-lab-10.sh        PASS=51  FAIL=0
scripts/utilities/verify-lab-13.sh        PASS=49  FAIL=0
```

> Example output - your counts and PASS totals will differ. The final block is the one an
> assessor reads first.

### C.4 The end-to-end demonstration

The checkpoint asks for **one path, all the way through**, captured as text. This is the path this
lab has made possible for the first time, and it takes about two minutes:

```bash
{
  printf 'USMS end-to-end demonstration - %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  printf -- '--- 1. identity: who am I, and what may this role do ---\n'
  ./scripts/utilities/whoami.sh
  aws iam list-attached-role-policies --role-name usms-lambda-exec-role \
    --query 'AttachedPolicies[].PolicyName' --output text

  printf -- '\n--- 2. storage: the bucket four policies have named since Lab 01 ---\n'
  aws s3api head-bucket --bucket usms-student-data && echo "head-bucket: exit 0"

  printf -- '\n--- 3. trigger: what the bucket does when an object arrives ---\n'
  aws s3api get-bucket-notification-configuration --bucket usms-student-data \
    --query 'LambdaFunctionConfigurations[].[Id,LambdaFunctionArn]' --output text

  printf -- '\n--- 4. compute: the function that runs, and the version behind the alias ---\n'
  aws lambda get-function-configuration --function-name usms-transcript-notifier \
    --qualifier live --query '[Version,Runtime,TracingConfig.Mode]' --output text

  printf -- '\n--- 5. the event: upload a transcript ---\n'
  ./scripts/utilities/usms-emit-telemetry.sh science 0.63

  printf -- '\n--- 6. logs: what it said ---\n'
  aws logs filter-log-events --log-group-name /usms/central/application \
    --filter-pattern 'USMS_EVENT' --query 'events[-1].message' --output text

  printf -- '\n--- 7. metrics: what it counted ---\n'
  aws cloudwatch list-metrics --namespace USMS/Application \
    --query 'Metrics[].MetricName' --output text | tr '\t' '\n' | sort -u

  printf -- '\n--- 8. alarms: what would page somebody ---\n'
  aws cloudwatch describe-alarms \
    --query 'MetricAlarms[].[AlarmName,StateValue,TreatMissingData]' --output text
  aws cloudwatch describe-alarms --alarm-types CompositeAlarm \
    --query 'CompositeAlarms[].[AlarmName,AlarmRule]' --output text

  printf -- '\n--- 9. the dashboard somebody would look at ---\n'
  aws cloudwatch get-dashboard --dashboard-name usms-overview \
    --query 'DashboardBody' --output text \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["widgets"]), "widgets")'
} | tee project/checkpoint-01/evidence/end-to-end.txt
```

Nine stages, one command, and every stage names a different practical. That is the argument the
checkpoint is asking you to make, and the reason to capture it as text rather than as screenshots is
that text can be re-run by somebody who doubts it.

### C.5 Capturing the rest of the evidence

```bash
mkdir -p project/checkpoint-01/evidence

./scripts/utilities/verify-lab-10.sh > project/checkpoint-01/evidence/verify-lab-10.txt 2>&1
./scripts/utilities/verify-lab-13.sh > project/checkpoint-01/evidence/verify-lab-13.txt 2>&1
cp outputs/lab-13-telemetry-inventory.txt project/checkpoint-01/evidence/telemetry-inventory.txt

tail -1 project/checkpoint-01/evidence/verify-lab-10.txt
tail -1 project/checkpoint-01/evidence/verify-lab-13.txt
```

A `FAIL` greater than zero in either file is not automatically a lost mark. An honest
`gaps.md` entry saying *this check fails because my build does not evaluate metric filters, and here
is the evidence that the filter is correctly configured* is worth more than a passing run you cannot
explain. A `FAIL` you have not noticed is the thing that costs marks.

### C.6 The self-check before you submit

```bash
for f in architecture.md gaps.md demo.md inventory.txt; do
  [ -s "project/checkpoint-01/$f" ] && printf '  ✔ %s\n' "$f" || printf '  ✗ %s missing or empty\n' "$f"
done

[ "$(ls project/checkpoint-01/evidence/ 2>/dev/null | wc -l | tr -d ' ')" -ge 4 ] \
  && echo "  ✔ evidence present" || echo "  ✗ fewer than 4 evidence files"

git ls-files project/checkpoint-01/ | wc -l
git status --short project/
```

Everything in `project/checkpoint-01/` must appear in `git ls-files` after you commit, and nothing
under `outputs/` may appear anywhere. `docs/Lab/project-checkpoint-01.md` has the rubric those files
are marked against, the eight-minute demonstration protocol, and the submission deadline.

---

## Sources

- [What is Amazon CloudWatch Logs? - Amazon CloudWatch Logs User Guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/WhatIsCloudWatchLogs.html)
- [Working with log groups and log streams](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html)
- [Filter and pattern syntax - CloudWatch Logs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html)
- [Creating metrics from log events using filters](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/MonitoringLogData.html)
- [CloudWatch Logs Insights query syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [Publishing custom metrics - Amazon CloudWatch User Guide](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/publishingMetrics.html)
- [Using Amazon CloudWatch alarms](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html)
- [Configuring how CloudWatch alarms treat missing data](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html#alarms-and-missing-data)
- [Creating a composite alarm](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Create_Composite_Alarm.html)
- [Dashboard body structure and syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/CloudWatch-Dashboard-Body-Structure.html)
- [What is AWS X-Ray? - AWS X-Ray Developer Guide](https://docs.aws.amazon.com/xray/latest/devguide/aws-xray.html)
- [AWS X-Ray segment documents](https://docs.aws.amazon.com/xray/latest/devguide/xray-api-segmentdocuments.html)
- [Using filter expressions - AWS X-Ray](https://docs.aws.amazon.com/xray/latest/devguide/xray-console-filters.html)
- [Configuring sampling rules - AWS X-Ray](https://docs.aws.amazon.com/xray/latest/devguide/xray-console-sampling.html)
- [Using AWS Lambda with AWS X-Ray](https://docs.aws.amazon.com/lambda/latest/dg/services-xray.html)
- [Actions, resources, and condition keys for CloudWatch - Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazoncloudwatch.html)
- [IAM policy elements: condition keys for CloudWatch namespaces](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/iam-cw-condition-keys-namespace.html)
- Course documents: Lab 01 (IAM, the five-policy estate), Lab 04 (the `/usms/ecs/enrolment` log
  group), Lab 06 (`usms-enrolment-queue-high` - the alarm nobody was told was an alarm), Lab 10
  Step 17 (the `USMS_NOTIFY` marker), Lab 10 Step 18 (aliases, explained), Lab 10 Section 17
  (replace-only APIs), Errata 01.

---

*Lab 13 complete. The system now says what it is doing, counts what matters, and can be asked where a
single request went - and the next lab gives all three of those somewhere to send a message.*
# Lab 10 - Edge Functions with AWS Lambda

*Practical 6 in the delivery schedule, Practical 4 in the module descriptor.*

---

## 1. Lab Overview

Every lab so far has built something that sits **inside** the university's network. A VPC, subnets,
instances, containers behind a load balancer, a Kubernetes cluster. All of it lives in one region,
in one account, behind one front door.

This lab builds the front door itself, and then puts code **in** it.

An **edge function** is a piece of your application that runs in the content delivery network,
physically close to the person making the request, before the request ever reaches your origin. On
AWS the two mechanisms are **Lambda@Edge** - a normal Lambda function, written in Node.js or
Python, associated with a CloudFront distribution - and **CloudFront Functions**, a much smaller and
much faster JavaScript runtime for viewer-only work. This lab builds the first and explains the
second, because choosing between them is the actual engineering decision and a student who has only
seen one cannot make it.

The USMS system needs this for a concrete reason. Student transcripts are static files. They are
requested from all over the country, they are identical every time they are requested, and they must
not be handed to someone who has not authenticated. Serving them from an instance in `us-east-1` is
slow for a student in Trashigang and wasteful for everyone. Serving them from a CDN is fast - but a
CDN with no logic in it cannot tell an authenticated request from an unauthenticated one. An edge
function is how you keep the speed and add the judgement.

There is one more thing this lab does, and it is overdue. Every policy Lab 1 wrote, every role Lab 09
audited, has referred to a bucket named `usms-student-data` that **has never existed**. Step 5
creates it. From that step onwards, `USMSStudentDataReadWrite` stops being a hypothesis about a
resource and becomes a statement about a real one.

By the end you will have three Lambda functions, two of them shaped for the edge and one of them a
conventional regional function triggered by S3, plus the CloudFront distribution that ties the first
two to the origin bucket - and, more importantly, a clear account of which parts of that you have
genuinely observed and which parts you have only recorded.

**Time:** roughly four hours. **Assessment:** Section 14.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. Explain what an edge function is, where it executes, and what problem it solves that neither a
   plain CDN nor a regional application server solves.
2. Distinguish **Lambda@Edge** from **CloudFront Functions** by runtime, trigger points,
   capabilities and cost, and justify a choice between them for a stated requirement.
3. Name the four CloudFront trigger points - `viewer-request`, `origin-request`, `origin-response`,
   `viewer-response` - and say what is and is not available to your code at each.
4. Package a Lambda function as a deployment archive and create it with `aws lambda create-function`,
   choosing a runtime, handler, role, memory and timeout deliberately rather than by default.
5. Read and write the CloudFront event structure - `event.Records[0].cf.request` and
   `.cf.response` - including the header shape that trips up everybody on first contact.
6. Invoke a function directly with a crafted event payload, read its response, and read its logs,
   using `--payload fileb://` and `--log-type Tail`.
7. Publish an immutable **version** of a function and explain why Lambda@Edge accepts a
   version-qualified ARN and refuses both `$LATEST` and an alias.
8. State the Lambda@Edge restrictions - region, no environment variables, no VPC, memory and timeout
   caps per trigger point - and check a function against them by reading its configuration.
9. Attach functions to a CloudFront distribution with `LambdaFunctionAssociations`, and describe the
   request path a `GET` takes through both of them.
10. Distinguish a Lambda **execution role** (what the function may do) from a Lambda **resource
    policy** (who may invoke the function), and configure both.
11. Wire an S3 event notification to a Lambda alias and prove, from logs, that the object upload
    reached the code.
12. Say precisely which of the above you observed working in Floci and which you recorded without
    being able to observe.

---

## 3. Prerequisites

Before starting, you need:

- Labs 1 through 9 complete, and their `configs/lab-NN.env` files present. Step 2 checks this - see
  Section 4.
- Floci running under Docker Compose, with `FLOCI_STORAGE_MODE` set to `hybrid`.
- A terminal in which a **new window** already has `AWS_PROFILE` and `COURSE_ROOT` set. If that is
  not true, you have the defect described in Errata 01 and you should fix it now rather than halfway
  through Step 12.
- `python3` on your path. This lab uses it for JSON validation and as the portable fallback for
  building a `.zip` archive.
- Roughly 1 GB of free disk. Floci starts one container per Lambda runtime it executes.

Run this before anything else:

```bash
cd ~/aws-floci-course
./scripts/utilities/floci-storage-check.sh
```

You want `PASS=16  FAIL=0`. A failure in the first block means a new terminal cannot find the
course, and the AWS CLI will tell you that your *credentials* are wrong, which they are not.

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 will suggest `aws login`. That begins a sign-in to
    **real AWS**. The answer in this course is always `source configs/course.env` or a missing
    `floci` profile - never a sign-in. See Errata 01 Section 3.

---

## 4. Connection to Previous Labs

### 4.1 What this lab can assume is already done

By this point in the course, every student has built the same sequence: ECS + Fargate (Lab 04), the
ALB front door (Lab 05) and Service Auto Scaling (Lab 06), then EKS (Lab 07) and EKS Scaling (Lab 08)
as a second deployment target for the same application, and finally the security review (Lab 09)
across both. There is no alternate path to account for and no cohort-dependent gap to bridge.

Step 2 still sources every `configs/lab-*.env` file with an existence check rather than a bare
`source`, because a missing file is a real error worth naming precisely - not because any of Labs 01
through 09 is optional. Where this lab reuses a specific earlier artefact - Lab 09's
`outputs/lab-09-bucket-policy-draft.json`, Lab 08's `outputs/lab-08-scaling-evidence.json` - the step
that wants it says so, and still supplies a fallback that manufactures an equivalent in case an
earlier exercise was skipped.

### 4.2 A note on the roadmap

Earlier drafts of this course planned a dedicated S3 configuration lab between Security and Lambda,
and assumed Lambda would follow it. That S3 lab was never written, and the delivery schedule has put
edge functions directly after Security instead. That creates one real problem, not a cosmetic one: a
Lambda@Edge lab needs an origin, and the origin the whole course has been pointing at does not exist.

So this lab creates `usms-student-data` - and creates it *plainly*: `create-bucket`, one tag, one
object. It does not configure versioning, encryption, lifecycle rules, a bucket policy, a website
configuration or public-access blocks. Those remain the subject matter of the still-unwritten S3
configuration lab, and they stay untouched here. Whenever that lab is written, it will begin with
`head-bucket` **succeeding** instead of failing, and with Lab 09's drafted bucket policy still
un-applied and waiting.

### 4.3 Current Environment

```text
Created in previous labs:
- Lab 01: IAM foundation - 3 groups, 3 users, 3 roles, 5 policies, 1 instance profile
- Lab 01: usms-lambda-exec-role (trusts lambda.amazonaws.com) + USMSLambdaBasic - UNUSED UNTIL NOW
- Lab 01: Floci under Compose, hybrid storage, persistence proven
- Lab 02: usms-vpc 10.0.0.0/16, 4 subnets, IGW, NAT, route tables, usms-app-sg, usms-s3-endpoint
- Lab 03: usms-web-01, usms-db-01, usms-app-key, usms-web-golden AMI
- Lab 04: usms-ecs-cluster, usms-enrolment-svc, usms-ecs-task-role, /usms/ecs/enrolment
- Lab 05: usms-enrolment-alb, usms-enrolment-tg, usms-alb-sg
- Lab 06: target-tracking and step-scaling policies, usms-enrolment-queue-high alarm
- Lab 09: USMSStudentDataReadOnly, usms-deploy-role, scoped egress
- Lab 07/08: usms-eks-cluster, usms-eks-nodes, usms-enrolment-hpa, usms-portal-ingress
- NOT created by anybody: the bucket usms-student-data that four policies already name

Created in this lab:
- usms-student-data ................. the origin bucket, created plainly
- usms-edge-viewer-request .......... Lambda@Edge viewer-request function (Node.js)
- usms-edge-origin-response ......... Lambda@Edge origin-response function (Node.js)
- usms-transcript-notifier .......... regional function, S3 ObjectCreated trigger (Python)
- version 1 of each function, and the alias `live` on the notifier only
- usms-transcript-cdn ............... CloudFront distribution, both edge functions associated
- an updated trust policy on usms-lambda-exec-role: lambda + edgelambda
- scripts/utilities/usms-edge-simulate.sh ... runs the edge chain without CloudFront

Required for future labs:
- usms-student-data        → the (still unwritten) S3 configuration lab configures it properly and
                             applies the bucket policy
- usms-transcript-notifier → the SNS/SQS lab replaces its print() with a real publish
- USMS_LAMBDA_NOTIFIER_ALIAS_ARN → the event-source lab points more triggers at it
- outputs/lab-10-s3-readiness.txt → the S3 configuration lab reads it at the start
```

### 4.4 What this lab genuinely reuses

Not "mentions". Uses.

| From | Resource | How this lab actually uses it |
| --- | --- | --- |
| Lab 01 | `usms-lambda-exec-role` | The execution role on all three functions. Step 6 rewrites its trust policy to add the edge principal - the first time this role has ever been touched since it was created |
| Lab 01 | `USMSLambdaBasic` | Read back in Step 6 to establish what the functions may do: write logs, and `s3:GetObject`. The notifier's code is written to stay inside it |
| Lab 01 | `USMSStudentDataReadWrite` | Step 5 creates the bucket whose ARN this policy has named since the first day of the course, and Step 5's verify proves the ARN now resolves |
| Lab 01 | `USMS_BUCKET_NAME` | The bucket name, taken from `configs/lab-01.env` rather than typed |
| Lab 02 | `usms-s3-endpoint` | Explained in Step 5 as the reason a private-subnet caller reaches the new bucket without a NAT hop |
| Lab 06 | `outputs/lab-06-scaling-history.json` | One of the two candidate payloads uploaded in Step 20 to fire the notifier |
| Lab 08 | `outputs/lab-08-scaling-evidence.json` | The other. Lab 08 Section 17 promised this file would be the bucket's first `put-object`, and Step 20 is where that promise is kept |
| Lab 09 | `outputs/lab-09-bucket-policy-draft.json` | Exercise 5 validates its ARNs against the bucket that now exists |
| Lab 09 | the identity-vs-resource-policy distinction | Step 18 is the same distinction applied to Lambda, and says so |

---

## 5. What We Are Building

The transcript delivery path, end to end.

A student's browser asks for `/transcripts/2026/stu-00417.json`. That request arrives at the nearest
CloudFront edge location. Before CloudFront looks in its cache, `usms-edge-viewer-request` runs: it
checks for the header the USMS portal attaches to authenticated requests, normalises the URI so that
`/transcripts/2026/STU-00417.JSON` and `/transcripts/2026/stu-00417.json` are the same cache entry,
and either returns the request for CloudFront to continue with, or returns a `403` response of its
own - in which case the origin is never contacted at all.

If the request continues and CloudFront has no cached copy, it fetches the object from
`usms-student-data`. On the way back, `usms-edge-origin-response` runs and attaches the security
headers that a static file served from a bucket does not have by itself.

Separately, whenever anything is written into `transcripts/` in that bucket, S3 invokes
`usms-transcript-notifier`, which is where the results-notification logic will eventually live.

Three functions, two of them at the edge, one of them regional - and that split is the lesson.
Edge functions are for the request path. Regional functions are for what happens afterwards.

---

## 6. Architecture

```text
                    STUDENT'S BROWSER
                           |
                  GET /transcripts/2026/stu-00417.json
                           |
                           v
        +==========================================================+
        |              CLOUDFRONT EDGE LOCATION                    |
        |                usms-transcript-cdn                       |
        |                                                          |
        |   (1) viewer-request  -->  usms-edge-viewer-request      |
        |            |                  |                          |
        |            |                  +-- no auth header --> 403 |
        |            |                        (origin never hit)   |
        |            v                                             |
        |        [ EDGE CACHE ]  --hit-->  (4) viewer-response ----+--> 200
        |            |                                             |
        |            | miss                                        |
        |            v                                             |
        |   (2) origin-request   (not used in this lab)            |
        +===========================|==============================+
                                    |
                                    v
                    +-------------------------------+
                    |   ORIGIN: usms-student-data   |
                    |   s3 bucket, us-east-1        |
                    |   transcripts/2026/*.json     |
                    +-------------------------------+
                                    |
                                    v
        +==========================================================+
        |   (3) origin-response --> usms-edge-origin-response      |
        |         adds strict-transport-security,                  |
        |         x-content-type-options, cache-control            |
        +==========================================================+
                                    |
                                    v
                             back to the viewer


        THE SEPARATE, REGIONAL PATH  (not an edge function)

            put-object transcripts/*.json
                       |
                       v
            +---------------------------+        +------------------------+
            |     usms-student-data     | -----> | usms-transcript-       |
            |  notification config:     |  s3:   |  notifier:live         |
            |  prefix transcripts/      | Object |  python3.12, regional  |
            |  suffix .json             | Created|  usms-lambda-exec-role |
            +---------------------------+        +-----------+------------+
                                                             |
                                                             v
                                        /aws/lambda/usms-transcript-notifier
```

Read the numbering once more, because the order is not the order people guess. The viewer-request
trigger fires **before** the cache is consulted, which is why it can reject a request without costing
anything, and also why anything it does has to be fast. The origin-response trigger fires **after**
the origin replies but **before** the object is cached, which is why a header added there is stored
in the cache and served to everyone afterwards.

---

## 7. Directory Structure

What this lab adds. Nothing is restructured; `manifests/` from Lab 07 is untouched.

```text
aws-floci-course/
├── labs/lab-10-lambda-edge/          # NEW
│   ├── README.md
│   ├── exercises.md
│   ├── edge-viewer-request/
│   │   └── index.mjs                 # Step 7
│   ├── edge-origin-response/
│   │   └── index.mjs                 # Step 12
│   └── transcript-notifier/
│       └── notifier.py               # Step 17
│
├── policies/
│   └── trust-lambda-edge.json        # NEW - Step 6
│
├── templates/
│   ├── lab-10-viewer-request-event.json      # Step 9
│   ├── lab-10-viewer-request-denied.json     # Step 9, Your turn
│   ├── lab-10-origin-response-event.json     # Step 13
│   ├── lab-10-distribution-config.json       # Step 15
│   ├── lab-10-bucket-notification.json       # Step 20
│   └── lab-10-s3-event.json                  # Step 21 fallback
│
├── configs/
│   └── lab-10.env                    # Step 23
│
├── scripts/
│   ├── utilities/
│   │   ├── usms-edge-simulate.sh     # Step 16
│   │   └── verify-lab-10.sh          # Section 9
│   └── cleanup/
│       └── lab-10-cleanup.sh         # Section 16 - DO NOT RUN NOW
│
└── outputs/                          # git-ignored, nothing here is committed
    ├── usms-edge-viewer-request.zip        ├── lab-10-support-probe.txt
    ├── usms-edge-origin-response.zip       ├── lab-10-function-inventory.json
    ├── usms-transcript-notifier.zip        ├── lab-10-distribution.json
    ├── lab-10-viewer-allow.json            ├── lab-10-edge-trace.json
    ├── lab-10-viewer-deny.json             ├── lab-10-notifier-logs.txt
    ├── lab-10-origin-response.json         ├── lab-10-pre-restart.txt
    ├── lab-10-notifier-direct.json         ├── lab-10-post-restart.txt
    └── lab-10-s3-readiness.txt          └── lab-10-assessment-c.md / -d.txt
```

A note on where the source lives. The function code sits under `labs/lab-10-lambda-edge/`, not under
`templates/`, because it is **source code** - it is the thing you edit - whereas `templates/` holds
API request bodies. The `.zip` archives you build from that source are build artefacts and are
written to `outputs/`, which is git-ignored, because a `.zip` rebuilt from committed source is not
something to commit.

---
## 8. Step-by-Step Implementation

### Step 1 - Start the environment and prove a new terminal can find it

**Purpose**

Everything after this assumes Floci is running with persistent storage and that your shell knows
where the course is. Both have failed silently for students before, in ways whose symptoms appear
several steps later attributed to something else.

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
idempotent, so running it when Floci is already up costs you two seconds and changes nothing. It
refuses to adopt a container that was not started by Compose, which is the guard against a stray
`floci start` from a previous term.

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

This lab needs `USMS_BUCKET_NAME` and `USMS_ROLE_LAMBDA` from Lab 1, and it also reuses artefacts from
Lab 06, Lab 07, Lab 08 and Lab 09. A loop that checks each file's existence before sourcing it turns a
missing file into a specific, named line of output instead of a `command not found` several steps
later with no obvious cause.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
source configs/course.env

for f in configs/lab-01.env configs/lab-02.env configs/lab-03.env \
         configs/lab-04.env configs/lab-05.env configs/lab-06.env \
         configs/lab-09.env configs/lab-07.env configs/lab-08.env; do
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
you did not intend - a stray `lab-04.env` left over from the superseded Lab 04 document, say - and
would give you no report of what it did. Naming the files makes the output a statement about the
state of your repository.

`whoami.sh` prints the caller identity and the endpoint, and exits `1` unless the account is
`000000000000`. It is the last thing standing between a mistyped endpoint and a command that reaches
real AWS.

**Expected result**

```text
  sourced  configs/lab-01.env
  sourced  configs/lab-02.env
  sourced  configs/lab-03.env
  sourced  configs/lab-04.env
  sourced  configs/lab-05.env
  sourced  configs/lab-06.env
  sourced  configs/lab-09.env
  sourced  configs/lab-07.env
  sourced  configs/lab-08.env

Account : 000000000000
Identity: arn:aws:iam::000000000000:root
Endpoint: http://localhost:4566
```

> Example output - your dates and IDs will differ, but every line above should read `sourced`. An
> `absent` line means an earlier lab's env file is missing - go back and finish that lab, or regenerate
> its `configs/lab-NN.env`, before continuing here.

**Verify**

```bash
printf 'bucket name  : %s\n' "${USMS_BUCKET_NAME:-<UNSET>}"
printf 'lambda role  : %s\n' "${USMS_ROLE_LAMBDA:-<UNSET>}"
printf 'account id   : %s\n' "${USMS_ACCOUNT_ID:-<UNSET>}"
```

**What to look for:** three populated values. `usms-student-data`, `usms-lambda-exec-role` and
`000000000000`. If `USMS_BUCKET_NAME` is unset, `configs/lab-01.env` predates the convention; set it
now with `export USMS_BUCKET_NAME=usms-student-data` and add the line to that file, because Step 5
and every verification afterwards read it.

---

### Step 3 - Create this lab's directories

**Purpose**

Three directories for source code, and nothing else new. Creating them in one deliberate step means
no later step fails on a missing parent directory, which is failure mode number one from the course's
teaching philosophy.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
mkdir -p labs/lab-10-lambda-edge/edge-viewer-request \
         labs/lab-10-lambda-edge/edge-origin-response \
         labs/lab-10-lambda-edge/transcript-notifier

ls -d labs/lab-10-lambda-edge/*/
```

**What the command does**

`mkdir -p` creates parents as needed and does not complain if the directory already exists, which
makes this step safe to re-run. Each function gets its own directory because a deployment archive is
built from a directory, and a single directory holding three handlers would produce three archives
that each contain all three files.

**Expected result**

```text
labs/lab-10-lambda-edge/edge-origin-response/
labs/lab-10-lambda-edge/edge-viewer-request/
labs/lab-10-lambda-edge/transcript-notifier/
```

**Verify**

```bash
test -d labs/lab-10-lambda-edge/edge-viewer-request && echo "source tree ready"
```

---

### Step 4 - Find out what this Floci build actually supports

**Purpose**

This lab depends on three services. Lambda is well emulated and you will see it work. S3 is well
emulated. CloudFront is the one that varies most between builds, and Lambda@Edge - the association
of a function with a distribution trigger - is not executed by any emulator at all. Establishing
that now, in writing, means that when Step 15 behaves differently on your machine than on the one
next to you, you already know why.

This is the course's rule applied to a whole lab: find out what is true before depending on it.

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
  printf 'Floci support probe for Lab 10 - %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  probe "lambda  (list-functions)"      "aws lambda list-functions --max-items 1"
  probe "lambda  (list-layers)"         "aws lambda list-layers"
  probe "s3      (list-buckets)"        "aws s3api list-buckets"
  probe "logs    (describe-log-groups)" "aws logs describe-log-groups --limit 1"
  probe "cloudfront (list-distributions)" "aws cloudfront list-distributions"
  probe "iam     (get-role)"            "aws iam get-role --role-name ${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}"
} | tee outputs/lab-10-support-probe.txt
```

**What the command does**

`probe` runs a harmless read-only call and reports only whether it returned zero. It deliberately
does not print the error, because the errors differ between builds and the only decision this output
drives is which path you take later.

`{ ...; } | tee file` groups the commands so that a single pipe captures all of their output.
Lab 09 introduced this pattern; it is here because you want this record in `outputs/` when you come
to write up the lab.

The one probe worth explaining: `aws lambda list-layers` is separate from `list-functions` because
some builds implement the function API and not the layer API, and a student who assumes one from the
other loses an hour in Exercise 4.

**Expected result**

```text
Floci support probe for Lab 10 - 2026-09-16T04:12:07Z

  SUPPORTED    lambda  (list-functions)
  SUPPORTED    lambda  (list-layers)
  SUPPORTED    s3      (list-buckets)
  SUPPORTED    logs    (describe-log-groups)
  UNSUPPORTED  cloudfront (list-distributions)
  SUPPORTED    iam     (get-role)
```

> Example output - your build may report CloudFront as SUPPORTED. Either answer is normal and the
> lab handles both.

**What to look for:** the first four lines must say `SUPPORTED`. If `lambda (list-functions)` says
`UNSUPPORTED`, stop and read Section 11 - the rest of this lab cannot proceed, and the cause is
almost always that Floci is still starting.

The CloudFront line decides which path Step 15 takes:

| CloudFront probe | Step 15 |
| --- | --- |
| `SUPPORTED` | Path A - create the distribution and read the associations back from the API |
| `UNSUPPORTED` | Path B - validate the distribution config structurally and record it for real AWS |

Either way Step 16 is what actually proves your two functions compose, so nobody is left without a
result.

---

### Step 5 - Create the origin bucket, and watch a policy stop being hypothetical

**Purpose**

`usms-student-data` is the origin CloudFront will fetch from, and the bucket whose objects will
trigger the notifier. It is also the resource that Lab 1's `USMSStudentDataReadWrite` has named since
the first day of this course without ever resolving to anything.

**Run from**

```text
aws-floci-course/
```

**Concept first - what "the bucket does not exist" has meant until now**

An IAM policy names resources by ARN. It does **not** require them to exist. You can write, attach
and audit a policy granting `s3:PutObject` on `arn:aws:s3:::usms-student-data/*` in an account with
no buckets at all, and every IAM call will succeed.

That is not a bug, it is the point: identity policies are written about a namespace, not about an
inventory. But it has a consequence students find genuinely disorienting, and it is worth naming.
For five labs, `USMSStudentDataReadWrite` has been attached to real roles, audited, counted and
reasoned about - and it has been granting access to nothing. The policy was never wrong. It was
waiting.

**Command**

```bash
BUCKET="${USMS_BUCKET_NAME:-usms-student-data}"

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null \
  && echo "bucket already exists - skipping create" \
  || aws s3api create-bucket --bucket "$BUCKET"

aws s3api put-bucket-tagging \
  --bucket "$BUCKET" \
  --tagging 'TagSet=[{Key=Project,Value=USMS},{Key=Tier,Value=data},{Key=Lab,Value=06}]'

echo "$BUCKET"
```

**What the command does**

```text
aws
 └── s3api                 the SERVICE, low-level: one subcommand per API call
      └── create-bucket    the OPERATION
           └── --bucket    an OPTION - the bucket name, which IS its identifier
```

Lab 04's reading-ahead note mentioned `aws s3` versus `aws s3api`. The short form: `aws s3` is a
small set of file-transfer verbs (`cp`, `sync`, `ls`) built for humans moving files; `aws s3api` maps
one-to-one onto the S3 REST API and is what you use when you care about a specific parameter. This
course uses `s3api` for anything structural and `s3` only where it genuinely reads better.

Two things about `create-bucket` that catch people:

**There is no `--region` and no `--create-bucket-configuration` here, and that is correct.**
`us-east-1` is S3's original region, and its API treats it as the default. Passing
`--create-bucket-configuration LocationConstraint=us-east-1` is an error on real AWS - it is the one
region where you must *omit* the constraint. Every other region requires it. Floci is lenient about
this; real AWS is not, so learn it here.

**Bucket names are globally unique across every AWS account on earth.** Not per-account, not
per-region - global. `usms-student-data` is almost certainly taken on real AWS. In Floci the
namespace is your own machine, so it works; when you do this for real you will be appending
something account-specific. The habit to take away is that a bucket name is a public identifier and
should not encode anything you would not put on a postcard.

The `head-bucket ... && ... || ...` construction makes the step idempotent. `head-bucket` returns
non-zero when the bucket is absent, which is exactly the probe Lab 3 Section 17 and Lab 09 Step 6
told you would eventually flip.

**Expected result**

```text
usms-student-data
```

> Example output - if the bucket already existed you will see the skip message first.

**Verify**

```bash
aws s3api head-bucket --bucket "$BUCKET" && echo "head-bucket: exit $?"

aws s3api get-bucket-tagging --bucket "$BUCKET" \
  --query 'TagSet[].[Key,Value]' --output table

POLICY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]" --output text)

aws iam get-policy-version \
  --policy-arn "$POLICY_ARN" \
  --version-id "$(aws iam get-policy --policy-arn "$POLICY_ARN" \
                    --query 'Policy.DefaultVersionId' --output text)" \
  --query 'PolicyVersion.Document.Statement[].Resource' --output json
```

**What to look for:** `head-bucket` exits `0` - for the first time in this course. The tag table
shows three rows. And the last command prints the ARNs the policy has always named:

```text
[
    [
        "arn:aws:s3:::usms-student-data",
        "arn:aws:s3:::usms-student-data/*"
    ]
]
```

> Example output - your policy may split bucket and object ARNs across two statements, which is the
> shape Lab 1 described.

Look at those two strings and at the bucket you just created. They are the same name. As of this
step, every role carrying that policy - `usms-ec2-app-role`, `usms-ecs-task-role`, and
`usms-eks-node-role` from the EKS build in Labs 07 and 08 - has real permissions on a real resource.
That is the single most important sentence in this lab, and it took several labs to earn.

!!! note "Floci Limitation - the permission is still not enforced"
    Floci accepts any non-empty credentials and does not evaluate IAM policies against requests.
    The bucket now exists and the policy now resolves, but a caller with no permissions at all will
    still be able to read it here.

    Real AWS evaluates every request against identity policies, resource policies, boundaries and
    session policies, and denies by default.

    The takeaway is the one Lab 09 made: judge your policies by reading them, not by whether the
    command succeeded. What changed in this step is real and checkable - the ARN now resolves - and
    it changed in IAM's data, not in Floci's enforcement.

**Checkpoint 1**

```text
usms-student-data                       ← EXISTS, at last
 ├── tags: Project=USMS, Tier=data, Lab=06
 └── named by:
      ├── USMSStudentDataReadWrite  (Lab 01)  → usms-ec2-app-role, usms-ecs-task-role, usms-eks-node-role
      └── USMSStudentDataReadOnly   (Lab 09) → usms-transcripts-reader-role
```

---

### Step 6 - Read the execution role back, and give it the edge principal

**Purpose**

Lab 1 created `usms-lambda-exec-role` and nothing has used it since. Before attaching it to three
functions you should know what it permits, and you must fix one thing about it: its trust policy
names only `lambda.amazonaws.com`, and a Lambda@Edge function is invoked by a second service
principal as well.

**Run from**

```text
aws-floci-course/
```

**Concept first - two principals, because two services replicate your function**

When you associate a function with a CloudFront trigger, CloudFront does not call your function in
`us-east-1` on every request. It **replicates** the function's code and configuration out to the edge
locations, and the replicas are invoked there by CloudFront's own machinery. That replication is
performed by a distinct service principal, `edgelambda.amazonaws.com`.

So the execution role has to be assumable by two services:

| Principal | Why it needs to assume the role |
| --- | --- |
| `lambda.amazonaws.com` | The ordinary Lambda service, when it runs the function |
| `edgelambda.amazonaws.com` | CloudFront's replication and edge invocation path |

Omitting the second is the single most common Lambda@Edge setup error on real AWS. The distribution
update fails with a message about the function not being assumable, and people go and look at the
function.

**Command - part 1, read what the role currently is**

```bash
ROLE_NAME="${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}"

aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.{Name:RoleName,Created:CreateDate,MaxSession:MaxSessionDuration}' \
  --output table

aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output json

aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
  --query 'AttachedPolicies[].[PolicyName,PolicyArn]' --output table
```

**Expected result**

```text
[
    "lambda.amazonaws.com"
]

-----------------------------------------------------------------------------
|                          ListAttachedRolePolicies                          |
+------------------+---------------------------------------------------------+
|  USMSLambdaBasic |  arn:aws:iam::000000000000:policy/USMSLambdaBasic        |
+------------------+---------------------------------------------------------+
```

> Example output - your ARNs and dates will differ.

**What to look for:** one principal, and one attached policy. `USMSLambdaBasic` grants CloudWatch
Logs writes and `s3:GetObject`. That is the whole budget your three functions have to live inside,
and the notifier in Step 17 is written to respect it.

**Command - part 2, write the two-principal trust policy**

```bash
cat > policies/trust-lambda-edge.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowLambdaAndCloudFrontEdgeToAssume",
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "lambda.amazonaws.com",
          "edgelambda.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

python3 -m json.tool policies/trust-lambda-edge.json > /dev/null && echo "valid JSON"
```

**What the command does**

`<< 'EOF'` - **quoted**. This is a policy document, and nothing in it should be expanded by the
shell. If you wrote `<< EOF` here, the document would still be valid JSON and nothing would appear
to go wrong; the failure mode of getting this backwards is silent, which is why the course restates
it every time it matters. The contrast comes in Step 23, where the heredoc writing
`configs/lab-10.env` is deliberately **unquoted** because you want `$(...)` to run.

`"Principal": {"Service": [...]}` takes a list. Two entries here; one is the more common form and
both are valid.

**Command - part 3, replace the trust policy**

```bash
aws iam update-assume-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-document file://policies/trust-lambda-edge.json

EDGE_ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.Arn' --output text)

echo "$EDGE_ROLE_ARN"
```

**What the command does**

`update-assume-role-policy` **replaces** the trust policy wholesale. There is no add-principal call.
This is why part 2 wrote both principals rather than the one that was missing: an update that named
only `edgelambda.amazonaws.com` would have removed the ordinary Lambda principal and broken the role
for every non-edge use.

`file://` reads the document from disk. That is not cosmetic - a JSON policy passed inline has to
survive your shell's quoting, and every course that teaches inline policies produces a cohort that
cannot tell a quoting error from a policy error.

`EDGE_ROLE_ARN` is captured with `$(...)` rather than copied by hand, per the rule from Lab 1. It is
also the first of several shell variables this lab depends on, so it is worth saying the thing the
course says once per lab: **shell variables die with the terminal.** Close this window and
`EDGE_ROLE_ARN` is gone. That is precisely why Step 23 writes everything durable into
`configs/lab-10.env`.

**Expected result**

```text
arn:aws:iam::000000000000:role/usms-lambda-exec-role
```

> Example output - the account is always `000000000000` in Floci.

**Verify**

```bash
aws iam get-role --role-name "$ROLE_NAME" \
  --query 'length(Role.AssumeRolePolicyDocument.Statement[0].Principal.Service)' --output text

aws iam get-role --role-name "$ROLE_NAME" \
  --query "Role.AssumeRolePolicyDocument.Statement[0].Principal.Service[?contains(@, 'edgelambda')] | [0]" \
  --output text
```

**What to look for:** `2`, then `edgelambda.amazonaws.com`. If the first returns `1`, the update did
not apply; if it returns nothing at all, your build stores the trust document as a string rather than
an object - re-read it with `--query 'Role.AssumeRolePolicyDocument' --output json` and check by eye.

!!! note "Floci Limitation - trust policies are stored, not evaluated"
    Floci records the document faithfully and will hand it back to you, but it does not perform the
    trust evaluation when a service invokes your function. A function with an empty trust policy
    will still run here.

    Real AWS refuses `create-function` outright if the role cannot be assumed by
    `lambda.amazonaws.com`, and refuses the CloudFront association if `edgelambda.amazonaws.com` is
    missing.

    Take away the two-principal requirement itself. It is a fact about Lambda@Edge, not about the
    emulator, and it is checkable by reading - which is what the verify above did.

**Checkpoint 2**

```text
usms-lambda-exec-role
 ├── trust: lambda.amazonaws.com
 │          edgelambda.amazonaws.com        ← added in this step
 ├── attached: USMSLambdaBasic  (logs:* on /aws/lambda/*, s3:GetObject)
 └── ARN captured as EDGE_ROLE_ARN
```

---

### Step 7 - Write the viewer-request handler

**Purpose**

This is the function that runs on every request before the cache is consulted. It decides who gets a
transcript, and it makes the cache work properly by normalising the URI. It is also where you meet
the CloudFront event structure, which is unlike any other Lambda event you will see.

**Run from**

```text
aws-floci-course/
```

**Concept first - the CloudFront event, and the header shape**

A Lambda@Edge function receives an event with exactly one record:

```text
event
 └── Records[0]
      └── cf
           ├── config    ← distributionId, eventType, requestId
           ├── request   ← always present, at all four trigger points
           └── response  ← present ONLY at origin-response and viewer-response
```

Your handler returns one of three things, and which are legal depends on the trigger point:

| Return value | Meaning | Legal at |
| --- | --- | --- |
| the `request` object | continue, using this (possibly modified) request | viewer-request, origin-request |
| a `response` object | stop here, send this to the viewer | viewer-request, origin-request |
| the `response` object | continue, with this (possibly modified) response | origin-response, viewer-response |

The header shape is the part everyone gets wrong first. Headers are **not** a map of strings. Each
header name is a lowercase key whose value is an **array of objects**, each with `key` and `value`:

```text
"headers": {
  "host":            [ { "key": "Host",            "value": "usms.example.edu" } ],
  "x-usms-student":  [ { "key": "X-USMS-Student",  "value": "stu-00417" } ]
}
```

The outer key is lowercase because HTTP header names are case-insensitive and CloudFront normalises
them so your code can look them up reliably. The inner `key` preserves the original casing so that
it can be sent on to an origin that cares. The array exists because HTTP permits a header to appear
more than once. Reading `headers['x-usms-student'].value` returns `undefined` and is the single most
common bug in a first edge function; you want `headers['x-usms-student'][0].value`.

**Command**

```bash
cat > labs/lab-10-lambda-edge/edge-viewer-request/index.mjs << 'EOF'
// usms-edge-viewer-request
//
// CloudFront trigger point: viewer-request.
// Runs on EVERY request, before the edge cache is consulted. Therefore:
//   - it must be fast (5 second hard timeout, 128 MB hard memory cap)
//   - it can reject a request without the origin ever being contacted
//   - anything it changes about the request becomes part of the cache key
//
// Returns the request object to continue, or a response object to stop.

const AUTH_HEADER = 'x-usms-student';
const PROTECTED_PREFIX = '/transcripts/';

export const handler = async (event) => {
  const request = event.Records[0].cf.request;
  const headers = request.headers;

  // 1. Normalise the URI. Without this, /transcripts/2026/STU-00417.json and
  //    /transcripts/2026/stu-00417.json are two different cache entries for one
  //    object, which halves the hit rate and doubles the origin traffic.
  request.uri = request.uri.toLowerCase();

  // 2. Anything outside /transcripts/ is not this function's business.
  if (!request.uri.startsWith(PROTECTED_PREFIX)) {
    return request;
  }

  // 3. The USMS portal attaches this header to an authenticated request.
  //    Note the [0]: a header value is an ARRAY of {key, value} objects.
  const studentHeader = headers[AUTH_HEADER];
  const studentId = studentHeader && studentHeader[0] && studentHeader[0].value;

  if (!studentId) {
    return {
      status: '403',
      statusDescription: 'Forbidden',
      headers: {
        'content-type': [{ key: 'Content-Type', value: 'application/json' }],
        'cache-control': [{ key: 'Cache-Control', value: 'no-store' }],
        'x-usms-edge': [{ key: 'X-USMS-Edge', value: 'viewer-request-deny' }]
      },
      body: JSON.stringify({
        message: 'transcript access requires an authenticated session'
      })
    };
  }

  // 4. Stamp the request so the origin-response function can see that we ran,
  //    and so the trace in Step 16 has something to show.
  request.headers['x-usms-edge'] = [
    { key: 'X-USMS-Edge', value: `viewer-request-allow;student=${studentId.toLowerCase()}` }
  ];

  return request;
};
EOF

node --check labs/lab-10-lambda-edge/edge-viewer-request/index.mjs 2>/dev/null \
  && echo "syntax OK (node)" \
  || echo "node not installed locally - syntax will be checked by the first invoke"
```

**What the command does**

`<< 'EOF'` - **quoted**, and this time it is load-bearing rather than merely correct. Look at line 4
of section 4 of the handler: it contains a JavaScript template literal with `${studentId...}` inside
backticks. With an unquoted `<< EOF`, bash would expand `${studentId.toLowerCase()}` to an empty
string before the file was ever written, and the backticks would be treated as command substitution.
You would get a file that is valid JavaScript, deploys cleanly, runs without error, and silently
stamps every request with an empty student id.

That is the same class of failure as the persistence bug this course was rebuilt around: a command
that appears to succeed, and does not do what you meant.

The file is `index.mjs`, not `index.js`. The `.mjs` extension tells Node to treat the file as an ES
module, which is what makes `export const handler` valid. The Lambda handler string will be
`index.handler` - the filename without its extension, a dot, and the exported name.

`node --check` parses the file without running it. If you have no local Node installation the
fallback message is honest: the first invocation in Step 9 will fail loudly on a syntax error, which
is a slower but perfectly adequate check.

**Expected result**

```text
syntax OK (node)
```

> Example output - the second message is equally fine.

**Verify**

```bash
wc -l labs/lab-10-lambda-edge/edge-viewer-request/index.mjs
grep -c 'studentId' labs/lab-10-lambda-edge/edge-viewer-request/index.mjs
grep -n 'toLowerCase()}' labs/lab-10-lambda-edge/edge-viewer-request/index.mjs
```

**What to look for:** around 50 lines, `studentId` appearing three times, and - this is the
important one - the third command must print a line containing `${studentId.toLowerCase()}` with the
dollar sign and braces **intact**. If it prints nothing, your heredoc was unquoted and bash ate the
expression. Delete the file and run the command again with `<< 'EOF'`.

---

### Step 8 - Package the function and create it

**Purpose**

A Lambda function is code plus configuration. The code arrives as a ZIP archive; the configuration -
runtime, handler, role, memory, timeout - arrives as flags. Choosing those flags deliberately is the
difference between a function that can be promoted to the edge and one that cannot.

**Run from**

```text
aws-floci-course/
```

**Concept first - the memory and timeout caps are not defaults, they are limits**

Lambda's defaults are 128 MB and 3 seconds. Lambda@Edge's *limits* depend on which trigger point the
function is associated with:

| Trigger point | Max memory | Max timeout | Max response body |
| --- | --- | --- | --- |
| `viewer-request`, `viewer-response` | 128 MB | 5 seconds | 40 KB |
| `origin-request`, `origin-response` | 10,240 MB | 30 seconds | 1 MB |

A viewer-trigger function configured with 256 MB is not slow - it is **rejected** when you try to
associate it. So the memory and timeout you pass below are chosen for the trigger point, not picked
out of the air, and that is the habit worth forming: configuration that encodes a constraint should
be written down at the moment the constraint applies.

**Command - part 1, build the archive**

```bash
( cd labs/lab-10-lambda-edge/edge-viewer-request \
  && python3 -m zipfile -c "$COURSE_ROOT/outputs/usms-edge-viewer-request.zip" index.mjs )

python3 -m zipfile -l outputs/usms-edge-viewer-request.zip
```

**What the command does**

The subshell - the `( ... )` - is doing real work. `python3 -m zipfile -c archive.zip index.mjs`
stores the entry under the **path you gave it**, so running it from the repository root with
`labs/lab-10-lambda-edge/edge-viewer-request/index.mjs` would produce an archive containing that
whole path, and Lambda would look for `index.mjs` at the archive root and not find it. The error you
get - `Cannot find module 'index.mjs'` - names the file, not the path, so it reads as though the file
is missing when in fact it is present and buried.

Wrapping the `cd` in a subshell means the directory change is scoped: when the parenthesis closes,
your shell is back where it was. The alternative, a bare `cd` followed by `cd -`, works right up
until the command in the middle fails and the `cd -` never runs - which is the anti-pattern the
course's rules call "a `cd` that never comes back".

`python3 -m zipfile` rather than `zip` because `python3` is a prerequisite of this course and `zip` is
not installed on every minimal Linux image. If you have `zip`, this is the equivalent:

```bash
( cd labs/lab-10-lambda-edge/edge-viewer-request \
  && zip -j "$COURSE_ROOT/outputs/usms-edge-viewer-request.zip" index.mjs )
```

`-j` means "junk the paths", storing the basename only - the same property the subshell gives you.

**Expected result**

```text
File Name                                             Modified             Size
index.mjs                                      2026-09-16 10:22:14         1893
```

> Example output - your size and timestamp will differ.

**What to look for:** one entry, named exactly `index.mjs`, with no directory prefix. That single
line is the difference between a function that runs and a two-hour debugging session.

**Command - part 2, create the function**

```bash
VIEWER_FN=usms-edge-viewer-request

VIEWER_FN_ARN=$(aws lambda create-function \
  --function-name "$VIEWER_FN" \
  --runtime nodejs20.x \
  --role "$EDGE_ROLE_ARN" \
  --handler index.handler \
  --zip-file fileb://outputs/usms-edge-viewer-request.zip \
  --timeout 5 \
  --memory-size 128 \
  --architectures x86_64 \
  --description "USMS Lambda@Edge viewer-request: auth gate and URI normalisation" \
  --tags Project=USMS,Tier=edge,Lab=06 \
  --query 'FunctionArn' --output text)

echo "$VIEWER_FN_ARN"
```

**What the command does**

```text
aws
 └── lambda                the SERVICE
      └── create-function  the OPERATION
           ├── --runtime        which language runtime executes your code
           ├── --role           the EXECUTION role: what your code may do
           ├── --handler        <file-without-extension>.<exported-name>
           ├── --zip-file       the code, as bytes
           ├── --timeout        seconds before Lambda kills the invocation
           └── --memory-size    MB - also determines the CPU share you get
```

Four of those deserve more than a line.

**`--zip-file fileb://`, with the `b`.** `file://` reads a file as **text** and hands it to the CLI as
a string. `fileb://` reads it as **binary** and hands over the raw bytes. A ZIP archive is binary;
reading it as text corrupts it, usually with an error about an invalid base64 string or an unzip
failure. This is the first time the course has needed `fileb://` and it will come back in Step 9 for
the invocation payload.

**`--runtime nodejs20.x`.** Lambda@Edge supports Node.js and Python only - no Go, no Java, no custom
runtimes, no container images. That is a real restriction and it is the reason this lab's two edge
functions are JavaScript while the regional notifier in Step 17 is Python: the contrast is the point.

**`--handler index.handler`.** Two parts separated by a dot. `index` is the module -
`index.mjs` with the extension dropped. `handler` is the name you exported. Change the filename and
you must change this flag; the error when you do not is `Cannot find module 'index'`.

**`--memory-size 128` and `--timeout 5`.** Chosen from the viewer-trigger row of the table above, not
from the defaults. Note that memory on Lambda is also the CPU dial - you do not allocate vCPU
separately; more memory means proportionally more CPU. At 128 MB you have the smallest slice
available, which for a function that reads two headers and returns is correct.

**Expected result**

```text
arn:aws:lambda:us-east-1:000000000000:function:usms-edge-viewer-request
```

> Example output - the ARN format is fixed; only the account and region vary, and in Floci they do
> not.

**Verify**

```bash
aws lambda wait function-active-v2 --function-name "$VIEWER_FN" 2>/dev/null \
  || echo "waiter unsupported on this build - checking state directly"

aws lambda get-function-configuration --function-name "$VIEWER_FN" \
  --query '{Name:FunctionName,Runtime:Runtime,Handler:Handler,Mem:MemorySize,Timeout:Timeout,State:State,Version:Version,Role:Role}' \
  --output table
```

**What to look for:**

```text
------------------------------------------------------------------------------
|                          GetFunctionConfiguration                           |
+-----------+-----------------------------------------------------------------+
|  Handler  |  index.handler                                                  |
|  Mem      |  128                                                            |
|  Name     |  usms-edge-viewer-request                                       |
|  Role     |  arn:aws:iam::000000000000:role/usms-lambda-exec-role           |
|  Runtime  |  nodejs20.x                                                     |
|  State    |  Active                                                         |
|  Timeout  |  5                                                              |
|  Version  |  $LATEST                                                        |
+-----------+-----------------------------------------------------------------+
```

> Example output - `State` may be absent on some builds, which is not an error.

`State` should be `Active`. If it says `Pending`, Floci is still pulling the runtime image; wait ten
seconds and re-run. `Version` says `$LATEST`, which is the mutable pointer at whatever code you last
uploaded - and in Step 11 you will see why the edge refuses to accept it.

---
### Step 9 - Invoke the function with a real CloudFront event

**Purpose**

A function you have not invoked is a function you have not written. This step builds the event
CloudFront would actually deliver, sends it, and reads what came back - which is the only way to
find out whether your handler understands the header shape.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write the event**

```bash
cat > templates/lab-10-viewer-request-event.json << 'EOF'
{
  "Records": [
    {
      "cf": {
        "config": {
          "distributionDomainName": "d3examplecdn01.cloudfront.net",
          "distributionId": "EDFDVBD6EXAMPLE",
          "eventType": "viewer-request",
          "requestId": "lab06-allow-0001"
        },
        "request": {
          "clientIp": "203.0.113.178",
          "method": "GET",
          "uri": "/transcripts/2026/STU-00417.json",
          "querystring": "",
          "headers": {
            "host": [
              { "key": "Host", "value": "transcripts.usms.example.edu" }
            ],
            "user-agent": [
              { "key": "User-Agent", "value": "curl/8.4.0" }
            ],
            "x-usms-student": [
              { "key": "X-USMS-Student", "value": "STU-00417" }
            ]
          }
        }
      }
    }
  ]
}
EOF

python3 -m json.tool templates/lab-10-viewer-request-event.json > /dev/null && echo "valid JSON"
```

**What the command does**

This is a genuine CloudFront viewer-request event, trimmed of the fields your handler does not read.
Three details are deliberate and each one is testing something:

- The `uri` is `/transcripts/2026/STU-00417.json`, in **upper case**. Your handler lowercases it, so
  the response will show a different URI than the request did. That is how you will know the
  normalisation ran.
- The `x-usms-student` header is present, so this event takes the allow path.
- The header key is lowercase and its value is a one-element array of an object. If you had guessed
  the shape, this is where the guess would be corrected.

`203.0.113.178` is from `TEST-NET-3`, a range RFC 5737 reserves for documentation. Using a reserved
range in example data is a small professional habit worth having: it can never collide with a real
address, so it cannot be mistaken for one in a log or a bug report.

**Command - part 2, invoke**

```bash
aws lambda invoke \
  --function-name "$VIEWER_FN" \
  --payload fileb://templates/lab-10-viewer-request-event.json \
  --query '{Status:StatusCode,Error:FunctionError,Executed:ExecutedVersion}' \
  --output table \
  outputs/lab-10-viewer-allow.json

python3 -m json.tool outputs/lab-10-viewer-allow.json
```

**What the command does**

`aws lambda invoke` is unusual among AWS CLI commands: it takes a **positional argument**, the path
of the file to write the function's response into. Everything the CLI prints on stdout is metadata
about the invocation; the function's actual return value goes to that file. Students who expect the
payload on stdout conclude that the function returned nothing.

`--payload fileb://` again - the same `b` as in Step 8. The payload is declared as a blob in the API
model, so the CLI expects bytes. `fileb://` supplies bytes. The alternative you will see in other
people's scripts is `--payload file://event.json --cli-binary-format raw-in-base64-out`, which tells
the CLI to treat text input as raw rather than base64; both work, and `fileb://` is shorter and
harder to get wrong.

`--query` here selects three fields out of the invocation metadata. `StatusCode` is the **HTTP**
status of the invoke call, so `200` means "Lambda ran your function", not "your function succeeded".
The field that answers the second question is `FunctionError`, which is absent on success and reads
`Unhandled` when your code threw.

**Expected result**

```text
------------------------------
|           Invoke           |
+-----------+-------+--------+
|  Error    | Executed | Status |
+-----------+-------+--------+
|  None     | $LATEST  |  200   |
+-----------+-------+--------+
{
    "clientIp": "203.0.113.178",
    "headers": {
        "host": [
            {
                "key": "Host",
                "value": "transcripts.usms.example.edu"
            }
        ],
        "user-agent": [
            {
                "key": "User-Agent",
                "value": "curl/8.4.0"
            }
        ],
        "x-usms-edge": [
            {
                "key": "X-USMS-Edge",
                "value": "viewer-request-allow;student=stu-00417"
            }
        ],
        "x-usms-student": [
            {
                "key": "X-USMS-Student",
                "value": "STU-00417"
            }
        ]
    },
    "method": "GET",
    "querystring": "",
    "uri": "/transcripts/2026/stu-00417.json"
}
```

> Example output - the table's column layout depends on your terminal width.

**Verify**

Three things to read, in order of importance:

1. `Error` is `None`. Anything else and your function threw; Step 10 reads the stack trace.
2. `uri` is now **lower case**. The normalisation ran.
3. There is an `x-usms-edge` header that was not in the request, and its value ends `student=stu-00417`
   - lower-cased, with the student id present. If it ends `student=` with nothing after it, your
   heredoc in Step 7 was unquoted; go back and re-read that step's verify.

```bash
python3 -c "
import json
r = json.load(open('outputs/lab-10-viewer-allow.json'))
assert r['uri'] == '/transcripts/2026/stu-00417.json', 'uri not normalised'
assert r['headers']['x-usms-edge'][0]['value'].endswith('stu-00417'), 'student id not stamped'
print('viewer-request allow path: correct')
"
```

**Expected result**

```text
viewer-request allow path: correct
```

✏️ **Your turn**

The allow path works. Now prove the deny path, which is the half that actually protects transcripts.

Create `templates/lab-10-viewer-request-denied.json` - the same event with the `x-usms-student`
header removed and `requestId` changed to `lab06-deny-0001` - invoke the function with it, and write
the result to `outputs/lab-10-viewer-deny.json`.

```text
Expected result:
Status 200, Error None - the function did not fail, it made a decision.
The response file is a RESPONSE object, not a request: it has a "status" of "403",
a "statusDescription", an "x-usms-edge" header reading "viewer-request-deny",
and a JSON "body". There is no "uri" key anywhere in it.
```

**Checkpoint 3**

```text
usms-student-data                              (Step 5)
usms-lambda-exec-role  + edgelambda principal  (Step 6)
usms-edge-viewer-request
 ├── nodejs20.x, index.handler, 128 MB, 5 s
 ├── $LATEST
 ├── invoked with allow event  → request returned, uri normalised, header stamped
 └── invoked with deny event   → 403 response returned, origin never reached
```

---

### Step 10 - Read the function's logs

**Purpose**

When a function misbehaves, the response tells you what it returned and the logs tell you why.
Lambda gives you two routes to the logs, and the difference between them matters when you are
debugging something that only fails occasionally.

**Run from**

```text
aws-floci-course/
```

**Concept first - two ways to get logs, and when each is right**

Every Lambda function writes to a CloudWatch Logs group named `/aws/lambda/<function-name>`, created
automatically on first invocation. That group is the durable record and it is what you query when
something failed an hour ago.

`--log-type Tail` is the other route: it attaches the **last 4 KB** of that invocation's log output
to the invoke response, base64-encoded, in a field called `LogResult`. It only works for synchronous
invocations, it only gives you the tail, and it gives it to you immediately. For interactive
debugging it is the better tool, because there is no delay between the invocation and the log being
readable.

**Command**

```bash
aws lambda invoke \
  --function-name "$VIEWER_FN" \
  --payload fileb://templates/lab-10-viewer-request-event.json \
  --log-type Tail \
  --query 'LogResult' --output text \
  outputs/lab-10-viewer-allow.json \
  | openssl base64 -d -A
```

**What the command does**

`--log-type Tail` asks for the log tail. `--query 'LogResult' --output text` prints only that field,
unquoted, so it can be piped.

`openssl base64 -d -A` decodes it. The course chose `openssl` over `base64` in Lab 3 for a reason
that applies again here: GNU `base64` decodes with `-d` and BSD `base64` - the one on macOS - uses
`-D`. A lab that hard-codes either one breaks half the room. `openssl base64` behaves the same on
both, and `-A` tells it to accept the whole encoded blob as a single line, which is how Lambda sends
it.

**Expected result**

```text
START RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa Version: $LATEST
END RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa
REPORT RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa	Duration: 18.42 ms	Billed Duration: 19 ms	Memory Size: 128 MB	Max Memory Used: 67 MB
```

> Example output - your request id, durations and memory figures will differ.

**What to look for:** three lines, `START` / `END` / `REPORT`, with matching request ids. There is no
application output because the handler never calls `console.log` - which is itself worth noticing:
your function is silent by design, and in Step 17 the notifier will be the opposite.

The `REPORT` line is the one to learn to read. `Duration` is how long your code ran; `Billed
Duration` is what you pay for, rounded up; `Max Memory Used` against `Memory Size` is how you decide
whether 128 MB was the right choice. For a viewer-trigger function it must be the right choice,
because 128 MB is the ceiling.

**Verify - the durable route**

```bash
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/$VIEWER_FN" \
  --query 'logGroups[].[logGroupName,storedBytes]' --output table
```

**What to look for:** one row, named `/aws/lambda/usms-edge-viewer-request`.

!!! note "Floci Limitation - log delivery is build-dependent"
    Some Floci builds return an empty `LogResult`, and some create the log group without writing
    streams into it. If the decode above printed nothing, do not conclude that your function did not
    run - Step 9 already proved it did, by returning a correctly modified request.

    Real AWS always attaches `LogResult` to a synchronous invoke with `--log-type Tail`, and always
    creates the group and stream.

    If logs are unavailable on your build, note it in `outputs/lab-10-support-probe.txt` and use the
    returned payload as your evidence throughout this lab. Section 11 has the fallback for Step 21,
    which is the step that actually depends on logs.

---

### Step 11 - Publish a version, and find out why the edge insists on one

**Purpose**

`$LATEST` is a mutable pointer. Everything you have built so far can be changed by the next
`update-function-code`, retroactively, everywhere. CloudFront will not accept that, and the reason is
worth more than the command.

**Run from**

```text
aws-floci-course/
```

**Concept first - three ways to name a function, and what the edge accepts**

| How you refer to it | What it points at | Accepted by Lambda@Edge? |
| --- | --- | --- |
| `...:function:usms-edge-viewer-request` | `$LATEST`, whatever that currently is | No |
| `...:function:usms-edge-viewer-request:live` | an alias - a movable label | No |
| `...:function:usms-edge-viewer-request:1` | version 1 - immutable, forever | Yes |

A published version freezes the code **and** the configuration - runtime, handler, memory, timeout,
role, environment variables. Nothing about version 1 can ever change. You can delete it; you cannot
edit it.

Now the reason CloudFront requires that. When you associate a function, CloudFront copies it to every
edge location in the price class - hundreds of points of presence. That replication takes minutes and
it is not transactional. If the ARN could move underneath it, you would have a window during which
different edge locations ran different code, with no way to say which request got which. Requiring an
immutable ARN turns "what is deployed" into a question with one answer.

This is also why an **alias** is refused even though an alias looks stable. An alias is designed to
be repointed; that is its entire purpose. A thing designed to move cannot be the thing that pins a
distributed rollout.

**Command**

```bash
VIEWER_VERSION=$(aws lambda publish-version \
  --function-name "$VIEWER_FN" \
  --description "Lab 10 - initial edge release" \
  --query 'Version' --output text)

VIEWER_VERSION_ARN="${VIEWER_FN_ARN}:${VIEWER_VERSION}"

printf 'version      : %s\n' "$VIEWER_VERSION"
printf 'qualified ARN: %s\n' "$VIEWER_VERSION_ARN"
```

**What the command does**

`publish-version` snapshots `$LATEST` and returns the new version number as a string of digits.
Versions are assigned sequentially by Lambda and start at `1`; you do not choose the number.

`"${VIEWER_FN_ARN}:${VIEWER_VERSION}"` builds the qualified ARN by concatenation rather than by a
second API call. The unqualified ARN plus a colon plus the version is exactly the qualified form,
which is a useful thing to know because you will see it in CloudFront error messages.

**Expected result**

```text
version      : 1
qualified ARN: arn:aws:lambda:us-east-1:000000000000:function:usms-edge-viewer-request:1
```

> Example output - if you have published before, your version number will be higher.

**Verify**

```bash
aws lambda list-versions-by-function --function-name "$VIEWER_FN" \
  --query 'Versions[].[Version,Description,CodeSize,LastModified]' --output table

printf '%s' "$VIEWER_VERSION_ARN" | grep -qE ':[0-9]+$' \
  && echo "ARN is version-qualified - the edge would accept this" \
  || echo "ARN is NOT version-qualified - the edge would refuse this"
```

**What to look for:** two rows - `$LATEST` and `1` - and the message saying the ARN is
version-qualified. That `grep -qE ':[0-9]+$'` is a small thing worth keeping: it is the static check
that replaces an enforcement Floci does not perform, and it goes into the verification script in
Section 9.

!!! note "Floci Limitation - nothing here refuses an unqualified ARN"
    Floci will happily record a CloudFront association pointing at `$LATEST` or at an alias, because
    it does not implement the Lambda@Edge validation rules.

    Real AWS rejects the `create-distribution` or `update-distribution` call outright, with
    `InvalidLambdaFunctionAssociation`.

    So the rule cannot be learned here by making the mistake. It has to be learned by checking - which
    is what the `grep` above does, and what the verification script will do on every run.

**Checkpoint 4**

```text
usms-edge-viewer-request
 ├── $LATEST ................. mutable, what you edit
 └── 1 ....................... immutable, what the edge can use
      └── arn:...:function:usms-edge-viewer-request:1     ← VIEWER_VERSION_ARN
```

---

### Step 12 - Write and deploy the origin-response function

**Purpose**

A file served straight from a bucket arrives with the headers S3 chose and nothing else. No
`Strict-Transport-Security`, no `X-Content-Type-Options`, no cache policy of your own. The
origin-response trigger is where you fix that, once, for every object, without touching a single
file.

**Run from**

```text
aws-floci-course/
```

**Concept first - why this trigger and not one of the other three**

You could add headers at `viewer-response`, which fires on the way out to the viewer. Do not, and the
reason is the cache.

`origin-response` fires after the origin replies and **before** CloudFront stores the object. The
headers you add there are stored with the cached object and served from cache to everyone
afterwards. Your function runs once per cache miss.

`viewer-response` fires on the way to the viewer, after the cache. Headers added there are correct,
but your function runs **on every single request**, cache hits included. For a static header set,
that is a function invocation per request for a result that never varies.

Same output, one of them costs a thousand times more. Choosing the trigger point *is* the design
work at the edge.

**Command - part 1, the handler**

```bash
cat > labs/lab-10-lambda-edge/edge-origin-response/index.mjs << 'EOF'
// usms-edge-origin-response
//
// CloudFront trigger point: origin-response.
// Runs after the origin replies and BEFORE the object is cached, so every
// header added here is stored once and served from cache thereafter.
//
// Receives both the request and the response. Returns the response.

const SECURITY_HEADERS = {
  'strict-transport-security': { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  'x-content-type-options':    { key: 'X-Content-Type-Options',    value: 'nosniff' },
  'x-frame-options':           { key: 'X-Frame-Options',           value: 'DENY' },
  'referrer-policy':           { key: 'Referrer-Policy',           value: 'strict-origin-when-cross-origin' }
};

const TRANSCRIPT_CACHE_CONTROL = 'public, max-age=300, s-maxage=3600';

export const handler = async (event) => {
  const cf = event.Records[0].cf;
  const request = cf.request;
  const response = cf.response;

  // 1. Attach the security headers. Overwrite unconditionally: the origin is a
  //    bucket, and a header set on an object by whoever uploaded it is not a
  //    security decision we want to inherit.
  for (const name of Object.keys(SECURITY_HEADERS)) {
    response.headers[name] = [SECURITY_HEADERS[name]];
  }

  // 2. Transcripts get a deliberate cache policy: short at the viewer,
  //    long at the edge, so a correction propagates in five minutes.
  if (request.uri.startsWith('/transcripts/')) {
    response.headers['cache-control'] = [
      { key: 'Cache-Control', value: TRANSCRIPT_CACHE_CONTROL }
    ];
  }

  // 3. Record whether the viewer-request function ran. In production this is a
  //    diagnostic; in this lab it is the evidence that the two functions
  //    composed, which is what Step 16 reads.
  const upstream = request.headers['x-usms-edge'];
  response.headers['x-usms-edge-chain'] = [
    {
      key: 'X-USMS-Edge-Chain',
      value: upstream && upstream[0] ? `${upstream[0].value};origin-response` : 'origin-response-only'
    }
  ];

  return response;
};
EOF

node --check labs/lab-10-lambda-edge/edge-origin-response/index.mjs 2>/dev/null \
  && echo "syntax OK (node)" \
  || echo "node not installed locally - syntax will be checked by the first invoke"
```

**What the command does**

`<< 'EOF'`, quoted, for the same reason as Step 7 and with the same consequence if you get it wrong:
section 3 of the handler contains a template literal, and an unquoted heredoc would turn
`${upstream[0].value}` into an empty string in a file that still deploys and still runs.

The `for (const name of Object.keys(...))` loop rather than four assignments is not style. It means
that adding a fifth security header is a one-line data change rather than a code change, and that the
list of headers is a thing you can read in one place. Exercise 1 asks you to add one.

Note what section 1 does **not** do: it does not check whether the header already exists. Overwriting
is the deliberate choice, and the comment says why. A function that preserved an existing
`X-Frame-Options` would let whoever uploaded an object decide the frame policy for the whole
distribution.

**Command - part 2, package and create**

```bash
ORIGIN_FN=usms-edge-origin-response

( cd labs/lab-10-lambda-edge/edge-origin-response \
  && python3 -m zipfile -c "$COURSE_ROOT/outputs/usms-edge-origin-response.zip" index.mjs )

ORIGIN_FN_ARN=$(aws lambda create-function \
  --function-name "$ORIGIN_FN" \
  --runtime nodejs20.x \
  --role "$EDGE_ROLE_ARN" \
  --handler index.handler \
  --zip-file fileb://outputs/usms-edge-origin-response.zip \
  --timeout 5 \
  --memory-size 128 \
  --architectures x86_64 \
  --description "USMS Lambda@Edge origin-response: security headers and cache policy" \
  --tags Project=USMS,Tier=edge,Lab=06 \
  --query 'FunctionArn' --output text)

echo "$ORIGIN_FN_ARN"
```

**What the command does**

Identical in shape to Step 8, which is the point - you have now seen the pattern twice and it will not
be decomposed a third time.

One deliberate choice to notice: 128 MB and 5 seconds again, even though an origin-trigger function
is *allowed* 10,240 MB and 30 seconds. This function reads four headers and writes five; it does not
need more. Sizing to the allowance rather than to the work is how a bill grows without anybody
deciding anything.

**Expected result**

```text
arn:aws:lambda:us-east-1:000000000000:function:usms-edge-origin-response
```

> Example output - your ARN will match apart from nothing, in Floci.

**Verify**

```bash
aws lambda get-function-configuration --function-name "$ORIGIN_FN" \
  --query '{Name:FunctionName,Runtime:Runtime,Handler:Handler,Mem:MemorySize,Timeout:Timeout,State:State}' \
  --output table
```

**What to look for:** `State` is `Active`, handler is `index.handler`, memory is `128`.

---

### Step 13 - Invoke the origin-response function and publish its version

**Purpose**

The second function needs the same treatment as the first: invoke it with a real event of its own
shape, confirm what it returns, then freeze it as a version. Its event is different from the
viewer-request event in one structural way, and seeing that difference is most of the value of this
step.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the origin-response event**

```bash
cat > templates/lab-10-origin-response-event.json << 'EOF'
{
  "Records": [
    {
      "cf": {
        "config": {
          "distributionDomainName": "d3examplecdn01.cloudfront.net",
          "distributionId": "EDFDVBD6EXAMPLE",
          "eventType": "origin-response",
          "requestId": "lab06-origin-0001"
        },
        "request": {
          "clientIp": "203.0.113.178",
          "method": "GET",
          "uri": "/transcripts/2026/stu-00417.json",
          "querystring": "",
          "headers": {
            "host": [
              { "key": "Host", "value": "usms-student-data.s3.us-east-1.amazonaws.com" }
            ],
            "x-usms-edge": [
              { "key": "X-USMS-Edge", "value": "viewer-request-allow;student=stu-00417" }
            ]
          }
        },
        "response": {
          "status": "200",
          "statusDescription": "OK",
          "headers": {
            "content-type": [
              { "key": "Content-Type", "value": "application/json" }
            ],
            "etag": [
              { "key": "ETag", "value": "\"9f86d081884c7d659a2feaa0c55ad015\"" }
            ],
            "server": [
              { "key": "Server", "value": "AmazonS3" }
            ]
          }
        }
      }
    }
  ]
}
EOF

python3 -m json.tool templates/lab-10-origin-response-event.json > /dev/null && echo "valid JSON"
```

**What the command does**

Two structural differences from the viewer-request event, and both are the trigger point showing
through:

- There is a `response` object. At `viewer-request` there is nothing to respond with yet; at
  `origin-response` the origin has already answered and you are being shown its answer.
- The `request` carries `x-usms-edge`, the header the viewer-request function stamped. That is the
  mechanism by which two edge functions communicate: not shared state, not a database - the request
  itself, carried forward through the chain.

The `etag` value contains **escaped double quotes**, `\"...\"`. That is not a mistake. An HTTP ETag
is quoted by specification, so the literal header value includes the quote characters, and inside a
JSON string those have to be escaped. Getting this wrong produces invalid JSON, which is why the
`python3 -m json.tool` check follows.

**Command - part 2, invoke and publish**

```bash
aws lambda invoke \
  --function-name "$ORIGIN_FN" \
  --payload fileb://templates/lab-10-origin-response-event.json \
  --query '{Status:StatusCode,Error:FunctionError}' \
  --output table \
  outputs/lab-10-origin-response.json

python3 -m json.tool outputs/lab-10-origin-response.json

ORIGIN_VERSION=$(aws lambda publish-version \
  --function-name "$ORIGIN_FN" \
  --description "Lab 10 - initial edge release" \
  --query 'Version' --output text)

ORIGIN_VERSION_ARN="${ORIGIN_FN_ARN}:${ORIGIN_VERSION}"
printf 'qualified ARN: %s\n' "$ORIGIN_VERSION_ARN"
```

**Expected result**

```text
{
    "headers": {
        "cache-control": [
            { "key": "Cache-Control", "value": "public, max-age=300, s-maxage=3600" }
        ],
        "content-type": [
            { "key": "Content-Type", "value": "application/json" }
        ],
        "etag": [
            { "key": "ETag", "value": "\"9f86d081884c7d659a2feaa0c55ad015\"" }
        ],
        "referrer-policy": [
            { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
        ],
        "server": [
            { "key": "Server", "value": "AmazonS3" }
        ],
        "strict-transport-security": [
            { "key": "Strict-Transport-Security", "value": "max-age=31536000; includeSubDomains" }
        ],
        "x-content-type-options": [
            { "key": "X-Content-Type-Options", "value": "nosniff" }
        ],
        "x-frame-options": [
            { "key": "X-Frame-Options", "value": "DENY" }
        ],
        "x-usms-edge-chain": [
            { "key": "X-USMS-Edge-Chain", "value": "viewer-request-allow;student=stu-00417;origin-response" }
        ]
    },
    "status": "200",
    "statusDescription": "OK"
}

qualified ARN: arn:aws:lambda:us-east-1:000000000000:function:usms-edge-origin-response:1
```

> Example output - `python3 -m json.tool` may wrap the inner objects across more lines than shown.

**Verify**

```bash
python3 -c "
import json
r = json.load(open('outputs/lab-10-origin-response.json'))
h = r['headers']
for required in ['strict-transport-security','x-content-type-options','x-frame-options','referrer-policy']:
    assert required in h, 'missing ' + required
assert h['cache-control'][0]['value'].startswith('public'), 'cache-control not set'
assert h['x-usms-edge-chain'][0]['value'].endswith(';origin-response'), 'chain header wrong'
print('origin-response: 4 security headers + cache-control + chain marker')
"
```

**What to look for:** the assertion script prints its success line, and the chain header reads
`viewer-request-allow;student=stu-00417;origin-response`. That string is the first evidence in this
lab that the two functions **compose** - the value the first one wrote has survived into the output
of the second.

Notice also what is preserved: `content-type`, `etag` and `server` came from the origin and are still
there. Your function added to the response; it did not replace it. An edge function that returned a
freshly built `headers` object would silently discard the origin's `Content-Type`, and the browser
would guess.

---

### Step 14 - Check both functions against the Lambda@Edge restrictions

**Purpose**

Floci will let you configure an edge function in ways real AWS rejects. This step deliberately makes
one of those mistakes, watches it succeed, and then undoes it - because a restriction you have only
read about is one you will forget, and this is the one place in the lab where the emulator being
*more* permissive than reality is a trap worth walking into on purpose.

**Run from**

```text
aws-floci-course/
```

**Concept first - what Lambda@Edge takes away**

| Restriction | Regional Lambda | Lambda@Edge |
| --- | --- | --- |
| Region | any | `us-east-1` only - the function must be created there |
| Runtimes | Node, Python, Java, Go, Ruby, .NET, custom, container images | Node.js and Python only |
| Environment variables | yes | **no** |
| VPC configuration | yes | no |
| Layers | yes | no |
| Dead letter queues | yes | no |
| Reserved concurrency | yes | no |
| Function URL | yes | no |
| Referenced by | name, alias or version | published **version** only |

The environment-variable restriction is the one that bites, because it is the mechanism every Lambda
tutorial reaches for first. At the edge you have no configuration channel: the code and its constants
are the same thing, which is why Step 7 and Step 12 both put their constants at the top of the file
as named `const` declarations. That placement is not decoration - it is the substitute for the
environment variables you cannot have.

The region restriction is invisible in this course because `us-east-1` is the course region, but it
is the second most common surprise on real AWS: you write the function in Mumbai, and CloudFront will
not see it.

**Command - part 1, make the mistake**

```bash
aws lambda update-function-configuration \
  --function-name "$VIEWER_FN" \
  --environment 'Variables={USMS_STAGE=lab06,USMS_AUTH_HEADER=x-usms-student}' \
  --query '{Name:FunctionName,Env:Environment.Variables}' --output json
```

**Expected result**

```text
{
    "Name": "usms-edge-viewer-request",
    "Env": {
        "USMS_STAGE": "lab06",
        "USMS_AUTH_HEADER": "x-usms-student"
    }
}
```

> Example output - on real AWS this call also succeeds. Read the next paragraph before you draw the
> wrong conclusion from that.

**What just happened, precisely**

The call succeeded, and it would succeed on real AWS too. Lambda does not know or care that you
intend this function for the edge; `update-function-configuration` is a Lambda API and environment
variables are a legal Lambda feature.

The rejection comes later, and from a different service. When you associate the function with a
CloudFront trigger, **CloudFront** validates it and returns
`InvalidLambdaFunctionAssociation: The function cannot have environment variables`. The error arrives
in a different API call, about a different resource, minutes after the mistake was made.

That gap - between the call that was wrong and the call that fails - is exactly why this lab checks
statically instead of waiting to be told.

**Command - part 2, undo it, and check both functions properly**

```bash
aws lambda update-function-configuration \
  --function-name "$VIEWER_FN" \
  --environment 'Variables={}' \
  --query 'Environment' --output json

edge_eligibility() {   # $1 = function name, $2 = max memory for its trigger point
  local fn="$1" cap="$2" cfg envcount mem timeout runtime vpc versions
  cfg=$(aws lambda get-function-configuration --function-name "$fn" --output json)
  envcount=$(printf '%s' "$cfg" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("Environment",{}).get("Variables",{}) or {}))')
  mem=$(printf '%s' "$cfg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MemorySize"])')
  timeout=$(printf '%s' "$cfg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Timeout"])')
  runtime=$(printf '%s' "$cfg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Runtime"])')
  vpc=$(printf '%s' "$cfg" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("VpcConfig",{}).get("SubnetIds",[]) or []))')
  versions=$(aws lambda list-versions-by-function --function-name "$fn" \
               --query "length(Versions[?Version!='\$LATEST'])" --output text)

  printf '\n%s\n' "$fn"
  [ "$envcount" -eq 0 ]            && printf '  ok   no environment variables\n'      || printf '  NO   %s environment variables set\n' "$envcount"
  [ "$mem" -le "$cap" ]            && printf '  ok   memory %s MB (cap %s)\n' "$mem" "$cap" || printf '  NO   memory %s MB exceeds cap %s\n' "$mem" "$cap"
  [ "$timeout" -le 5 ]             && printf '  ok   timeout %s s\n' "$timeout"        || printf '  NO   timeout %s s exceeds viewer cap 5\n' "$timeout"
  case "$runtime" in nodejs*|python*) printf '  ok   runtime %s\n' "$runtime" ;; *) printf '  NO   runtime %s not supported at the edge\n' "$runtime" ;; esac
  [ "$vpc" -eq 0 ]                 && printf '  ok   no VPC configuration\n'           || printf '  NO   attached to %s subnets\n' "$vpc"
  [ "$versions" -ge 1 ]            && printf '  ok   %s published version(s)\n' "$versions" || printf '  NO   no published version to associate\n'
}

{
  echo "Lambda@Edge eligibility - $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  edge_eligibility usms-edge-viewer-request 128
  edge_eligibility usms-edge-origin-response 128
} | tee outputs/lab-10-function-inventory.json
```

**What the command does**

`--environment 'Variables={}'` clears the map. There is no `--no-environment` flag; an empty map is
how you remove variables, and that asymmetry catches people.

`edge_eligibility` is a shell function that reads one function's configuration once and answers six
questions about it. It exists because this is the check that Floci cannot perform for you, and
because you will want it again - Exercise 3 turns it into a reporting script and Section 9 folds two
of its checks into `verify-lab-10.sh`.

The `python3 -c` one-liners read fields out of the JSON rather than using `--query`, for one specific
reason: `Environment` is **absent entirely** when no variables are set, and a JMESPath expression on
an absent key returns `None`, which is a string that `[ "$x" -eq 0 ]` cannot compare. Python's
`.get("Environment",{}).get("Variables",{}) or {}` collapses both "absent" and "present but empty"
into the same answer. Reaching for Python here is not a failure of JMESPath; it is choosing the tool
whose null handling matches the question.

`"length(Versions[?Version!='\$LATEST'])"` counts published versions. The `\$` is escaped because the
expression sits inside a double-quoted shell string and `$LATEST` would otherwise be expanded to
nothing - leaving JMESPath comparing against an empty string and counting every version including
`$LATEST`. The bug would be off-by-one and silent.

**Expected result**

```text
Lambda@Edge eligibility - 2026-09-16T05:41:02Z

usms-edge-viewer-request
  ok   no environment variables
  ok   memory 128 MB (cap 128)
  ok   timeout 5 s
  ok   runtime nodejs20.x
  ok   no VPC configuration
  ok   1 published version(s)

usms-edge-origin-response
  ok   no environment variables
  ok   memory 128 MB (cap 128)
  ok   timeout 5 s
  ok   runtime nodejs20.x
  ok   no VPC configuration
  ok   1 published version(s)
```

> Example output - your timestamp will differ.

**Verify**

```bash
grep -c '  NO   ' outputs/lab-10-function-inventory.json || echo "0 failures - both functions are edge-eligible"
```

**What to look for:** `grep -c` prints `0` and exits non-zero, so the `||` message appears. Any `NO`
line names a restriction you have violated, and the line itself tells you which. If the environment
variable line still says `NO`, the clear in part 2 did not apply - re-run it and re-check.

**Checkpoint 5**

```text
usms-edge-viewer-request     nodejs20.x  128 MB  5 s   version 1   edge-eligible
usms-edge-origin-response    nodejs20.x  128 MB  5 s   version 1   edge-eligible
 └── environment variables set on $LATEST and removed again - deliberately
```

---

### Step 15 - Associate both functions with a CloudFront distribution

**Purpose**

This is the step the lab is named after: the two functions stop being code you can invoke and become
code that runs on a request path. It is also the step most likely to behave differently on your
machine than on the next one, which is why Step 4 wrote down which path you are on.

**Run from**

```text
aws-floci-course/
```

**Concept first - what a distribution configuration actually says**

A CloudFront distribution is four things in a trench coat:

| Part of the config | The question it answers |
| --- | --- |
| `Origins` | where does the content come from |
| `DefaultCacheBehavior` | how is it cached, and what is the cache key |
| `LambdaFunctionAssociations` | what code runs, at which of the four trigger points |
| `Enabled`, `PriceClass`, `Comment` | is it on, how far does it spread, what is it for |

The cache key deserves the extra sentence. By default CloudFront caches on the URI alone - which is
why Step 7's lowercase normalisation matters, and why the config below forwards exactly one header,
`x-usms-student`, and no cookies. Every element you add to the cache key multiplies the number of
stored copies of the same object. Forwarding all headers is the classic way to build a CDN with a
zero percent hit rate.

**Command - part 1, write the configuration**

```bash
cat > templates/lab-10-distribution-config.json << EOF
{
  "CallerReference": "usms-transcript-cdn-$(date +%s)",
  "Comment": "usms-transcript-cdn - USMS transcript delivery with edge functions",
  "Enabled": true,
  "PriceClass": "PriceClass_All",
  "DefaultRootObject": "",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "usms-student-data-origin",
        "DomainName": "${USMS_BUCKET_NAME:-usms-student-data}.s3.us-east-1.amazonaws.com",
        "OriginPath": "",
        "CustomHeaders": { "Quantity": 0 },
        "S3OriginConfig": { "OriginAccessIdentity": "" }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "usms-student-data-origin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "Compress": true,
    "MinTTL": 0,
    "DefaultTTL": 300,
    "MaxTTL": 3600,
    "SmoothStreaming": false,
    "FieldLevelEncryptionId": "",
    "TrustedSigners": { "Enabled": false, "Quantity": 0 },
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"],
      "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] }
    },
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": { "Forward": "none" },
      "Headers": { "Quantity": 1, "Items": ["x-usms-student"] },
      "QueryStringCacheKeys": { "Quantity": 0 }
    },
    "LambdaFunctionAssociations": {
      "Quantity": 2,
      "Items": [
        {
          "EventType": "viewer-request",
          "LambdaFunctionARN": "${VIEWER_VERSION_ARN}",
          "IncludeBody": false
        },
        {
          "EventType": "origin-response",
          "LambdaFunctionARN": "${ORIGIN_VERSION_ARN}"
        }
      ]
    }
  }
}
EOF

python3 -m json.tool templates/lab-10-distribution-config.json > /dev/null && echo "valid JSON"
grep -n 'function:usms-edge' templates/lab-10-distribution-config.json
```

**What the command does**

`<< EOF` - **unquoted**, and this is the one place in this lab where that is what you want. Three
things must be expanded at write time: `$(date +%s)` for the caller reference, and the two version
ARN variables. If you wrote `<< 'EOF'` here you would get a file containing the literal text
`${VIEWER_VERSION_ARN}`, and CloudFront would reject it with a message about a malformed ARN.

Compare this against Step 6 and Step 7, where the quoted form was essential for the opposite reason.
Same syntax, one apostrophe apart, opposite meaning, and no error message either way. The rule is
worth saying as a question you ask before every heredoc: *do I want this file to contain what I
typed, or what it evaluates to?*

`CallerReference` is CloudFront's idempotency token. Two `create-distribution` calls with the same
caller reference and the same configuration return the same distribution instead of making a second
one; with the same reference and a *different* configuration you get an error. `$(date +%s)` - the
Unix epoch second - gives you a fresh one each time you regenerate the file.

`IncludeBody` appears on the viewer-request association and not on the origin-response one. That is
not an oversight: `IncludeBody` is only meaningful at `viewer-request` and `origin-request`, the two
trigger points where a request body exists to be read. Setting it at `origin-response` is an error.

**Expected result**

```text
valid JSON
          "LambdaFunctionARN": "arn:aws:lambda:us-east-1:000000000000:function:usms-edge-viewer-request:1",
          "LambdaFunctionARN": "arn:aws:lambda:us-east-1:000000000000:function:usms-edge-origin-response:1"
```

> Example output - line numbers will differ.

**What to look for:** both ARNs end with `:1`. If either ends with the function name and no version,
your `VIEWER_VERSION_ARN` or `ORIGIN_VERSION_ARN` was empty when the heredoc ran - which happens if
you opened a new terminal between Step 13 and here. Re-run the `publish-version` capture from Step 11
and Step 13 and regenerate the file.

**Command - part 2, PATH A: create the distribution**

Take this path if Step 4 reported CloudFront as `SUPPORTED`.

```bash
aws cloudfront create-distribution \
  --distribution-config file://templates/lab-10-distribution-config.json \
  > outputs/lab-10-distribution.json

DIST_ID=$(python3 -c "import json;print(json.load(open('outputs/lab-10-distribution.json'))['Distribution']['Id'])")
DIST_DOMAIN=$(python3 -c "import json;print(json.load(open('outputs/lab-10-distribution.json'))['Distribution']['DomainName'])")

printf 'distribution : %s\n' "$DIST_ID"
printf 'domain       : %s\n' "$DIST_DOMAIN"
```

**Verify - Path A**

```bash
aws cloudfront get-distribution --id "$DIST_ID" \
  --query 'Distribution.DistributionConfig.DefaultCacheBehavior.LambdaFunctionAssociations.Items[].[EventType,LambdaFunctionARN]' \
  --output table

aws cloudfront get-distribution --id "$DIST_ID" \
  --query 'Distribution.{Id:Id,Status:Status,Domain:DomainName,Enabled:DistributionConfig.Enabled}' \
  --output table
```

**What to look for:** two rows in the first table - `viewer-request` and `origin-response` - each
with a version-qualified ARN. `Status` will read `InProgress` or `Deployed`; on real AWS the
transition takes several minutes because the configuration is being pushed to every edge location,
and in Floci it is immediate or absent.

**Command - part 2, PATH B: validate the configuration instead**

Take this path if Step 4 reported CloudFront as `UNSUPPORTED`. You are not skipping the step; you are
performing the part of it that can be performed, and recording the part that cannot.

```bash
python3 - << 'PY' | tee outputs/lab-10-distribution.json
import json, sys

cfg = json.load(open('templates/lab-10-distribution-config.json'))
errors, checks = [], []

def check(label, ok):
    checks.append(('ok  ' if ok else 'FAIL') + '  ' + label)
    if not ok:
        errors.append(label)

beh = cfg['DefaultCacheBehavior']
assoc = beh['LambdaFunctionAssociations']
items = assoc['Items']
origin = cfg['Origins']['Items'][0]

check('one origin declared', cfg['Origins']['Quantity'] == 1)
check('origin id matches the behaviour target', origin['Id'] == beh['TargetOriginId'])
check('origin is the USMS bucket', origin['DomainName'].startswith('usms-student-data'))
check('association quantity matches item count', assoc['Quantity'] == len(items))
check('two trigger points associated', len(items) == 2)
check('trigger points are viewer-request and origin-response',
      sorted(i['EventType'] for i in items) == ['origin-response', 'viewer-request'])
check('every ARN is version-qualified',
      all(i['LambdaFunctionARN'].rsplit(':', 1)[-1].isdigit() for i in items))
check('IncludeBody only on a request trigger',
      all('IncludeBody' not in i for i in items if i['EventType'].endswith('response')))
check('viewer protocol policy is not allow-all',
      beh['ViewerProtocolPolicy'] != 'allow-all')
check('cache key forwards no cookies', beh['ForwardedValues']['Cookies']['Forward'] == 'none')
check('cache key forwards exactly one header',
      beh['ForwardedValues']['Headers']['Quantity'] == 1)

print(json.dumps({'mode': 'PATH B - structural validation only',
                  'checks': checks,
                  'errors': errors}, indent=2))
sys.exit(1 if errors else 0)
PY
```

**Verify - Path B**

**What to look for:** eleven `ok` entries and an empty `errors` list. That output is a real result:
it says the configuration you would send to real AWS is structurally correct and satisfies the
Lambda@Edge association rules, which is everything you can honestly claim without a CloudFront to
send it to.

!!! note "Floci Limitation - no emulator executes Lambda@Edge"
    Even on a build where `create-distribution` succeeds, Floci stores the distribution as a record.
    There is no edge location, no replication, no cache, and no request path - so the association is
    never exercised. This is not a gap in one build; no local emulator runs Lambda@Edge.

    On real AWS, `create-distribution` validates each association (region, version-qualified ARN, no
    environment variables, memory and timeout within the trigger's caps), replicates the function to
    every point of presence in the price class, and takes several minutes to reach `Deployed`. From
    then on the function runs on the request path, and its logs appear in the region **nearest the
    viewer** - not in `us-east-1`.

    What transfers regardless: the configuration document, the association rules, and the reasoning
    about which trigger point to use. Step 16 is where you get to watch your code actually run in
    sequence.

**Checkpoint 6**

```text
usms-transcript-cdn  (record, or validated configuration)
 ├── origin: usms-student-data.s3.us-east-1.amazonaws.com
 ├── cache key: uri + header x-usms-student, no cookies, no query string
 └── LambdaFunctionAssociations
      ├── viewer-request   → usms-edge-viewer-request:1
      └── origin-response  → usms-edge-origin-response:1
```

---

### Step 16 - Run the edge chain end to end, without CloudFront

**Purpose**

Step 15 could not prove that your two functions work together on a request path, because nothing
local runs a request path. This step builds the request path itself: a script that feeds a viewer
event to the first function, constructs the origin response the bucket would have produced, feeds
that to the second function, and prints the headers a browser would finally receive.

This is the lab's **create → perturb → read back** proof. The property being proved is composition -
that the header the first function writes is the header the second function reads - and the only way
to prove it is to run them in sequence and look at the far end.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write the script**

```bash
cat > scripts/utilities/usms-edge-simulate.sh << 'EOF'
#!/usr/bin/env bash
# Run the USMS edge chain the way CloudFront would, using direct Lambda
# invocations in place of a request path Floci does not have.
#
#   viewer-request fn  -->  (deny? stop)  -->  origin  -->  origin-response fn
#
# Usage:  usms-edge-simulate.sh [viewer-request-event.json]
# Writes: outputs/lab-10-edge-trace.json
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-10.env" 2>/dev/null || true

VIEWER_FN="${USMS_EDGE_VIEWER_FN:-usms-edge-viewer-request}"
ORIGIN_FN="${USMS_EDGE_ORIGIN_FN:-usms-edge-origin-response}"
EVENT="${1:-templates/lab-10-viewer-request-event.json}"
TRACE="outputs/lab-10-edge-trace.json"

[ -f "$EVENT" ] || { echo "no such event file: $EVENT" >&2; exit 1; }

echo "== 1. viewer-request =="
aws lambda invoke --function-name "$VIEWER_FN" \
  --payload "fileb://$EVENT" \
  --query 'FunctionError' --output text \
  outputs/.edge-step1.json >/dev/null || { echo "invoke failed" >&2; exit 1; }

# A viewer-request function returns EITHER a request (continue) OR a response (stop).
# The presence of a "status" key is what distinguishes them.
DECISION=$(python3 -c "
import json
d = json.load(open('outputs/.edge-step1.json'))
print('deny' if 'status' in d else 'allow')
")

if [ "$DECISION" = "deny" ]; then
  echo "   decision: DENY - the origin is never contacted"
  python3 - << 'PY' | tee "$TRACE"
import json
r = json.load(open('outputs/.edge-step1.json'))
print(json.dumps({
    'chain': ['viewer-request'],
    'decision': 'deny',
    'status': r.get('status'),
    'headers': {k: v[0]['value'] for k, v in r.get('headers', {}).items()},
}, indent=2))
PY
  exit 0
fi

echo "   decision: ALLOW - uri is now $(python3 -c "import json;print(json.load(open('outputs/.edge-step1.json'))['uri'])")"

echo "== 2. origin (simulated: what the bucket would have returned) =="
python3 - << 'PY'
import json
req = json.load(open('outputs/.edge-step1.json'))
event = {'Records': [{'cf': {
    'config': {'distributionId': 'SIMULATED', 'eventType': 'origin-response',
               'requestId': 'edge-simulate'},
    'request': req,
    'response': {
        'status': '200',
        'statusDescription': 'OK',
        'headers': {
            'content-type': [{'key': 'Content-Type', 'value': 'application/json'}],
            'server':       [{'key': 'Server',       'value': 'AmazonS3'}],
        },
    },
}}]}
json.dump(event, open('outputs/.edge-step2-event.json', 'w'))
print('   built an origin-response event carrying the modified request')
PY

echo "== 3. origin-response =="
aws lambda invoke --function-name "$ORIGIN_FN" \
  --payload fileb://outputs/.edge-step2-event.json \
  --query 'FunctionError' --output text \
  outputs/.edge-step3.json >/dev/null || { echo "invoke failed" >&2; exit 1; }

python3 - << 'PY' | tee "$TRACE"
import json
req = json.load(open('outputs/.edge-step1.json'))
res = json.load(open('outputs/.edge-step3.json'))
print(json.dumps({
    'chain': ['viewer-request', 'origin', 'origin-response'],
    'decision': 'allow',
    'request_uri_after_normalisation': req['uri'],
    'status': res['status'],
    'headers': {k: v[0]['value'] for k, v in res['headers'].items()},
}, indent=2))
PY

rm -f outputs/.edge-step1.json outputs/.edge-step2-event.json outputs/.edge-step3.json
echo
echo "trace written to $TRACE"
EOF

chmod +x scripts/utilities/usms-edge-simulate.sh
bash -n scripts/utilities/usms-edge-simulate.sh && echo "syntax OK"
```

**What the command does**

`<< 'EOF'` for the outer heredoc, because the script contains `$1`, `${BASH_SOURCE[0]}` and several
`$(...)` expressions that must survive into the file and run when the script runs, not when it is
written. The inner `<< 'PY'` heredocs are quoted for the same reason.

`REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"` resolves the repository root from
the script's own location rather than from your current directory, which is the course's standing
rule: `./../../scripts/x.sh` breaks the moment a student is one directory off.

`source "$REPO_ROOT/configs/lab-10.env" 2>/dev/null || true` - the file does not exist yet. Step 23
creates it. The `|| true` under `set -u` means the script works before and after that step, and the
`${USMS_EDGE_VIEWER_FN:-usms-edge-viewer-request}` defaults mean it works whichever way.

The decision logic is the interesting part. A viewer-request function returns either a request or a
response, and there is no discriminator field - you tell them apart by shape. `'status' in d` is that
test, and it is exactly what CloudFront itself does.

**Command - part 2, run it, both ways**

```bash
./scripts/utilities/usms-edge-simulate.sh

echo "-----------------------------------------------------------"

./scripts/utilities/usms-edge-simulate.sh templates/lab-10-viewer-request-denied.json
```

**Expected result**

```text
== 1. viewer-request ==
   decision: ALLOW - uri is now /transcripts/2026/stu-00417.json
== 2. origin (simulated: what the bucket would have returned) ==
   built an origin-response event carrying the modified request
== 3. origin-response ==
{
  "chain": [
    "viewer-request",
    "origin",
    "origin-response"
  ],
  "decision": "allow",
  "request_uri_after_normalisation": "/transcripts/2026/stu-00417.json",
  "status": "200",
  "headers": {
    "content-type": "application/json",
    "server": "AmazonS3",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cache-control": "public, max-age=300, s-maxage=3600",
    "x-usms-edge-chain": "viewer-request-allow;student=stu-00417;origin-response"
  }
}

trace written to outputs/lab-10-edge-trace.json
-----------------------------------------------------------
== 1. viewer-request ==
   decision: DENY - the origin is never contacted
{
  "chain": [
    "viewer-request"
  ],
  "decision": "deny",
  "status": "403",
  "headers": {
    "content-type": "application/json",
    "cache-control": "no-store",
    "x-usms-edge": "viewer-request-deny"
  }
}
```

> Example output - key ordering in the printed JSON may differ.

**Verify**

```bash
python3 -c "
import json
t = json.load(open('outputs/lab-10-edge-trace.json'))
print('chain    :', ' -> '.join(t['chain']))
print('decision :', t['decision'])
"
```

**What to look for:** two runs, two different chains. The allow run passes through all three stages
and its final `x-usms-edge-chain` header contains the string the **first** function wrote, followed
by the marker the **second** one appended. Nothing but genuine composition produces that value.

The deny run has a chain of length one. The origin was never contacted - which, in a real
distribution, is the entire economic argument for a viewer-request function. An unauthenticated
request costs you one edge invocation and no origin traffic at all.

Because `outputs/lab-10-edge-trace.json` is overwritten by each run, it currently holds the deny
trace. Re-run the allow case before the end of the lab, because Exercise 5 uploads this file and the
allow trace is the more interesting artefact:

```bash
./scripts/utilities/usms-edge-simulate.sh > /dev/null && echo "allow trace restored"
```

**Checkpoint 7**

```text
scripts/utilities/usms-edge-simulate.sh
 ├── allow event → viewer-request → origin → origin-response → 200 + 5 added headers
 │                                              x-usms-edge-chain proves composition
 └── deny  event → viewer-request → 403, origin never contacted
outputs/lab-10-edge-trace.json                 ← Exercise 5 uploads this
```

---
### Step 17 - Write the regional notifier

**Purpose**

The two edge functions handle the request path. This one handles what happens afterwards: every time
a transcript lands in the bucket, something has to react. That is not edge work - nobody is waiting
for it, it is not on anybody's request path, and it needs privileges an edge function is not allowed
to carry.

**Run from**

```text
aws-floci-course/
```

**Concept first - why this one is not an edge function**

| | Edge function | Regional function |
| --- | --- | --- |
| Triggered by | a viewer's request | an event: S3, SQS, a schedule, another service |
| Latency matters | yes - the viewer is waiting | no - nobody is waiting |
| Configuration | constants in the code | environment variables |
| Runs | wherever the viewer is | in one region, near your data |
| Can call other AWS services | badly - every call crosses a continent | yes, that is the normal case |

The last row is the decisive one. An edge function that calls DynamoDB is making a request from
Tokyo to Virginia in the middle of a page load. A regional function sits next to the services it
talks to. When you are deciding whether something belongs at the edge, the question is not "would it
be nice if this were fast" - it is "does this have to happen before the viewer can be answered".

Notifying the registrar that a transcript has been uploaded does not. So it is regional, it is
Python, and it has environment variables, all three of which are chosen in contrast to the functions
you have already written.

**Command**

```bash
cat > labs/lab-10-lambda-edge/transcript-notifier/notifier.py << 'EOF'
"""usms-transcript-notifier

Regional Lambda, triggered by S3 ObjectCreated on usms-student-data.

Deliberately stays inside USMSLambdaBasic, the Lab 01 policy that grants
CloudWatch Logs writes and s3:GetObject and nothing else. When the SNS lab
arrives, the notify() call below becomes a real publish and the policy grows
by exactly one action.
"""

import json
import os
import urllib.parse

BUCKET_HINT = os.environ.get("USMS_BUCKET", "usms-student-data")
CHANNEL = os.environ.get("USMS_NOTIFY_CHANNEL", "stdout")


def describe(record):
    """Pull the four fields that matter out of one S3 event record."""
    s3 = record.get("s3", {})
    raw_key = s3.get("object", {}).get("key", "")
    return {
        "event": record.get("eventName"),
        "bucket": s3.get("bucket", {}).get("name"),
        # S3 URL-encodes the key in the event. A key with a space arrives as
        # "stu+00417 final.json"; unquote_plus is what turns it back into the
        # string you would pass to get_object.
        "key": urllib.parse.unquote_plus(raw_key),
        "size": s3.get("object", {}).get("size"),
    }


def notify(payload):
    """Where the results notification will eventually go.

    Today: a structured line on stdout, which CloudWatch Logs captures.
    Later: sns.publish(TopicArn=..., Message=json.dumps(payload)).
    """
    print("USMS_NOTIFY " + json.dumps(payload, sort_keys=True))


def handler(event, context):
    records = event.get("Records", [])
    print("usms-transcript-notifier: %d record(s), channel=%s, bucket_hint=%s"
          % (len(records), CHANNEL, BUCKET_HINT))

    processed = []
    for record in records:
        info = describe(record)

        if not info["key"].startswith("transcripts/"):
            print("skipping non-transcript object: %s" % info["key"])
            continue

        # Confirming the object is readable exercises s3:GetObject, the one
        # non-logging permission this function has. It is wrapped because the
        # emulator does not always give a Lambda container a route back to the
        # S3 API, and an unreachable endpoint is not a reason to fail the event.
        info["readable"] = False
        try:
            import boto3
            boto3.client("s3").head_object(Bucket=info["bucket"], Key=info["key"])
            info["readable"] = True
        except Exception as exc:                      # noqa: BLE001
            info["read_error"] = type(exc).__name__

        notify(info)
        processed.append(info["key"])

    return {"processed": len(processed), "keys": processed}
EOF

python3 -m py_compile labs/lab-10-lambda-edge/transcript-notifier/notifier.py \
  && echo "syntax OK (python3)"
```

**What the command does**

`<< 'EOF'`, quoted, and here the reason is different again and worth naming: the file contains `%s`
and `%d` format placeholders and a docstring full of parentheses, none of which bash would expand -
but it also contains `$` nowhere, so an unquoted heredoc would *appear* to work. That is the trap.
The rule is not "quote it when you spot a dollar sign", it is "quote it unless you specifically want
expansion", because the day you add a `${...}` to this file you will not remember to go back and
change the heredoc.

`python3 -m py_compile` parses the file and reports syntax errors without executing it - the Python
equivalent of `node --check`. It leaves a `__pycache__` directory behind; the repository's
`.gitignore` already excludes it, and Step 24 will show you that it does.

The `try: import boto3` inside the function rather than at the top of the file is deliberate. If
boto3 were imported at module scope and the runtime did not provide it, the function would fail at
**initialisation**, before your handler ran, and the error would be an import traceback with no
context about which event caused it. Importing inside the guarded block means a missing or
unreachable dependency degrades one field of the output instead of killing the invocation.

**Expected result**

```text
syntax OK (python3)
```

**Verify**

```bash
grep -n 'os.environ.get' labs/lab-10-lambda-edge/transcript-notifier/notifier.py
```

**What to look for:** two lines. Those two `os.environ.get` calls are the thing the edge functions
were not allowed to have, and they are why the constants in Step 7 and Step 12 had to be hard-coded.
Seeing the contrast in two files you wrote an hour apart is the point of the exercise.

---

### Step 18 - Create the notifier, publish it, and give it an alias

**Purpose**

Same creation pattern as the edge functions, with two differences that matter: this one takes
environment variables, and this one gets an **alias**. The alias is the thing the edge refused, and
seeing where it is the right answer completes the picture.

**Run from**

```text
aws-floci-course/
```

**Concept first - what an alias is for**

An alias is a named, movable pointer to a version.

```text
usms-transcript-notifier
 ├── $LATEST ........ what you are editing
 ├── 1 .............. immutable snapshot
 ├── 2 .............. immutable snapshot
 └── live ---------→ currently points at 1
```

Everything that triggers the function - the S3 notification, an SNS subscription, an API - points at
`usms-transcript-notifier:live`. To deploy version 2, you repoint the alias with one call. To roll
back, you point it at 1 again. Nothing that references the function has to be reconfigured, and the
rollback takes the same one call as the deploy.

That is precisely the property Lambda@Edge cannot use, for precisely the reason it is valuable here:
the pointer moves. A trigger inside one region can follow it instantly. A function replicated to
hundreds of edge locations cannot.

**Command - part 1, create**

```bash
NOTIFIER_FN=usms-transcript-notifier
BUCKET="${USMS_BUCKET_NAME:-usms-student-data}"

( cd labs/lab-10-lambda-edge/transcript-notifier \
  && python3 -m zipfile -c "$COURSE_ROOT/outputs/usms-transcript-notifier.zip" notifier.py )

NOTIFIER_FN_ARN=$(aws lambda create-function \
  --function-name "$NOTIFIER_FN" \
  --runtime python3.12 \
  --role "$EDGE_ROLE_ARN" \
  --handler notifier.handler \
  --zip-file fileb://outputs/usms-transcript-notifier.zip \
  --timeout 30 \
  --memory-size 256 \
  --architectures x86_64 \
  --environment "Variables={USMS_BUCKET=$BUCKET,USMS_NOTIFY_CHANNEL=stdout}" \
  --description "USMS regional function: reacts to transcript uploads" \
  --tags Project=USMS,Tier=app,Lab=06 \
  --query 'FunctionArn' --output text)

echo "$NOTIFIER_FN_ARN"
```

**What the command does**

`--handler notifier.handler` - the module is `notifier` because the file is `notifier.py`, and the
function inside it is `handler`. Same `module.export` rule as `index.handler`, in a different
language.

`--environment "Variables={...}"` uses **double** quotes, because `$BUCKET` must be expanded. That is
the same decision as a heredoc, made at the level of a single argument, and it is the reason the
course keeps insisting you notice quoting: the shorthand syntax `Variables={K=V,K2=V2}` has no
quoting of its own, so the shell's rules are the only rules in play.

`--timeout 30` and `--memory-size 256`, both larger than the edge functions. This one may call S3, so
it can wait; and it is not bound by any edge cap.

!!! tip "If the runtime is rejected"
    Some Floci builds carry a shorter list of runtimes than real AWS. If `create-function` fails with
    `InvalidParameterValueException` naming the runtime, list what the build accepts and pick the
    nearest:

    ```bash
    aws lambda list-functions --query 'Functions[].Runtime' --output text
    ```

    `python3.11`, `python3.10` and `python3.9` all run this handler unchanged. Record the substitution
    in `outputs/lab-10-support-probe.txt`, and use your value wherever the lab says `python3.12`.

**Command - part 2, publish and alias**

```bash
aws lambda wait function-active-v2 --function-name "$NOTIFIER_FN" 2>/dev/null \
  || echo "waiter unsupported - continuing"

NOTIFIER_VERSION=$(aws lambda publish-version \
  --function-name "$NOTIFIER_FN" \
  --description "Lab 10 - initial release" \
  --query 'Version' --output text)

NOTIFIER_ALIAS_ARN=$(aws lambda create-alias \
  --function-name "$NOTIFIER_FN" \
  --name live \
  --function-version "$NOTIFIER_VERSION" \
  --description "The version S3 notifications invoke" \
  --query 'AliasArn' --output text)

printf 'version   : %s\n' "$NOTIFIER_VERSION"
printf 'alias ARN : %s\n' "$NOTIFIER_ALIAS_ARN"
```

**Expected result**

```text
version   : 1
alias ARN : arn:aws:lambda:us-east-1:000000000000:function:usms-transcript-notifier:live
```

> Example output - your version number may be higher if you have published before.

**What to look for:** the alias ARN ends with `:live`, not `:1`. Both are qualified ARNs; only one of
them can be repointed. Put this next to `VIEWER_VERSION_ARN` from Step 11 and the difference between
the two qualification styles is visible in a single glance.

**Verify**

```bash
aws lambda list-aliases --function-name "$NOTIFIER_FN" \
  --query 'Aliases[].[Name,FunctionVersion,Description]' --output table

aws lambda get-function-configuration --function-name "$NOTIFIER_FN" --qualifier live \
  --query '{Version:Version,Runtime:Runtime,Handler:Handler,Env:Environment.Variables}' \
  --output json
```

**What to look for:** one alias, `live`, pointing at version `1`; and the qualified
`get-function-configuration` reports `Version: "1"` - not `$LATEST`. `--qualifier` is how you ask
about a specific version or alias rather than about the function's mutable head, and it appears again
in Step 19 and Step 21.

The environment variables are present. Read them once more, then look back at Step 14, where the
identical configuration on an edge function was a mistake. Neither call was wrong; the difference is
entirely in where the function is going to run.

✏️ **Your turn**

Roll forward and back, without touching any trigger.

Publish a **second** version of the notifier (nothing about the code needs to change - publishing
`$LATEST` again is legal and gives you version 2), repoint `live` at it with
`aws lambda update-alias`, confirm the move, then put it back to version 1.

```text
Expected result:
list-aliases shows live → 2, then live → 1 again.
list-versions-by-function shows $LATEST, 1 and 2 throughout - repointing an
alias never deletes a version, which is what makes the rollback instant.
```

**Checkpoint 8**

```text
usms-transcript-notifier
 ├── python3.12, notifier.handler, 256 MB, 30 s
 ├── environment: USMS_BUCKET, USMS_NOTIFY_CHANNEL     ← legal here, illegal at the edge
 ├── $LATEST
 ├── 1
 └── live ──→ 1                                        ← the pointer S3 will target
```

---

### Step 19 - Let S3 invoke the function, and see the other kind of policy

**Purpose**

Your function has an execution role saying what it may do. Nothing yet says who may **call** it. S3
is about to try, and it will be refused - on real AWS, silently and permanently - until you attach a
resource-based policy.

**Run from**

```text
aws-floci-course/
```

**Concept first - the second policy, and the deputy problem**

Lab 09 drew the distinction between an identity policy and a resource policy. Lambda is where it
becomes unavoidable, because the two are attached to opposite ends of the same call:

| | Attached to | Answers |
| --- | --- | --- |
| Execution role (`usms-lambda-exec-role`) | the function | what may **this code** do |
| Resource policy (function policy) | the function | who may **invoke** this function |

S3 does not assume your execution role. S3 invokes your function **as S3**, and needs its own
permission to do so. That permission lives on the function.

Now the part that is easy to skip. The obvious grant is "allow the service principal
`s3.amazonaws.com` to invoke this function", and it is wrong, because there is more than one S3
bucket in the world. Any bucket in any account, configured by anyone, could then invoke your
function - and they would not need access to your account to do it, only the ability to make their
own bucket send a notification. That is the **confused deputy**: a trusted intermediary (S3) being
induced to act on behalf of someone who should not be able to reach you.

`--source-arn` and `--source-account` close it. They say: `s3.amazonaws.com` may invoke this
function, but only when it is acting for **this bucket**, in **this account**. This is the same
mechanism as the `aws:SourceArn` and `aws:SourceAccount` conditions Lab 09 added to
`usms-ecs-task-role`'s trust policy - same problem, same shape of answer, different service.

**Command**

```bash
aws lambda add-permission \
  --function-name "$NOTIFIER_FN" \
  --qualifier live \
  --statement-id usms-s3-transcript-upload \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::$BUCKET" \
  --source-account "${USMS_ACCOUNT_ID:-000000000000}" \
  --query 'Statement' --output text | python3 -m json.tool
```

**What the command does**

`--qualifier live` attaches the statement to the **alias**, not to the function as a whole. That is
deliberate and it matches the trigger: S3 will invoke `...:live`, so that is what has to be
invocable. A permission on the unqualified function does not cover an invocation of the alias.

`--statement-id` is the statement's name inside the policy. It must be unique per function, and you
need it again to remove the statement (`remove-permission --statement-id`). Naming it after the
reason it exists, rather than `stmt1`, is the difference between a readable policy and an archaeology
project.

`--action lambda:InvokeFunction` - the single action. Note that it is not `lambda:*`, and that this
is one of the few places in AWS where the least-privilege choice is also the obvious one.

The `--query 'Statement' --output text` pipeline is there because `add-permission` returns the new
statement as a **JSON string inside a JSON field** - a string that contains JSON, not nested JSON.
`--output text` unwraps the outer layer and `python3 -m json.tool` pretty-prints what is left. Try it
without the pipe once to see what you would otherwise be reading.

**Expected result**

```text
{
    "Sid": "usms-s3-transcript-upload",
    "Effect": "Allow",
    "Principal": {
        "Service": "s3.amazonaws.com"
    },
    "Action": "lambda:InvokeFunction",
    "Resource": "arn:aws:lambda:us-east-1:000000000000:function:usms-transcript-notifier:live",
    "Condition": {
        "StringEquals": {
            "AWS:SourceAccount": "000000000000"
        },
        "ArnLike": {
            "AWS:SourceArn": "arn:aws:s3:::usms-student-data"
        }
    }
}
```

> Example output - key ordering and the exact condition key casing vary between builds.

**Verify**

```bash
aws lambda get-policy --function-name "$NOTIFIER_FN" --qualifier live \
  --query 'Policy' --output text | python3 -m json.tool

aws lambda get-policy --function-name "$NOTIFIER_FN" --qualifier live \
  --query 'Policy' --output text \
  | python3 -c "
import json,sys
p = json.load(sys.stdin)
st = p['Statement'][0]
assert st['Principal']['Service'] == 's3.amazonaws.com'
cond = json.dumps(st.get('Condition', {}))
assert 'usms-student-data' in cond, 'source ARN condition missing - the deputy is still confused'
print('resource policy: scoped to one bucket in one account')
"
```

**What to look for:** the assertion line prints. If it raises on the condition, you omitted
`--source-arn`; remove the statement and redo it:

!!! danger "Read before running any delete command"
    **What will be deleted:** one statement, `usms-s3-transcript-upload`, from the resource policy on
    `usms-transcript-notifier:live`.

    **What depends on it:** the S3 notification configured in Step 20. Removing the statement stops
    S3 from invoking the function on real AWS.

    **Reversible?** Yes - re-run the `add-permission` above. Nothing else is affected and no data is
    touched.

    **Effect on later labs:** none, provided you re-add it. The SNS/SQS lab adds statements alongside
    this one rather than replacing it.

```bash
aws lambda remove-permission \
  --function-name "$NOTIFIER_FN" \
  --qualifier live \
  --statement-id usms-s3-transcript-upload
```

!!! note "Floci Limitation - the resource policy is recorded, not enforced"
    Floci stores the policy and returns it accurately, but it does not check it before letting an
    event through. Your notification would fire in Step 20 even with no permission at all.

    Real AWS checks it on every invocation. A missing statement produces an S3 notification that
    fails **silently** - no error in your console, no log line in your function, because the function
    never ran. It is one of the most frustrating misconfigurations in AWS precisely because the
    symptom is nothing happening.

    So do not read Step 20's success as evidence that the permission is right. Read the policy, as
    the verify above did.

---

### Step 20 - Wire the bucket notification and fire it for real

**Purpose**

Two resources exist and are correctly permitted. This step connects them, and then does the thing
Lab 06 and Lab 08 both promised: uploads their evidence file into the bucket, as its first real
object, and makes it trigger something.

**Run from**

```text
aws-floci-course/
```

**Concept first - where an S3 trigger is configured**

Not on the function. The notification configuration is a property of the **bucket**, and it names the
function. That direction catches people who expect to find it under Lambda.

It also means the configuration is **whole-bucket and replace-only**. There is no
`add-bucket-notification`; `put-bucket-notification-configuration` replaces every notification on the
bucket with the document you send. Sending a document containing only your Lambda configuration
removes any SNS or SQS notification that was there before. On a bucket with existing notifications
the safe sequence is get, merge, put - and this bucket has none, because you created it fifteen
steps ago.

**Command - part 1, the configuration**

```bash
cat > templates/lab-10-bucket-notification.json << EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "usms-transcript-upload",
      "LambdaFunctionArn": "${NOTIFIER_ALIAS_ARN}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            { "Name": "prefix", "Value": "transcripts/" },
            { "Name": "suffix", "Value": ".json" }
          ]
        }
      }
    }
  ]
}
EOF

python3 -m json.tool templates/lab-10-bucket-notification.json > /dev/null && echo "valid JSON"

aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" \
  --notification-configuration file://templates/lab-10-bucket-notification.json
```

**What the command does**

`<< EOF` unquoted again, because `${NOTIFIER_ALIAS_ARN}` must be substituted. Second and last time in
this lab.

`"Events": ["s3:ObjectCreated:*"]` covers `Put`, `Post`, `Copy` and the completion of a multipart
upload. Listing the wildcard rather than the four events individually is correct here because the
function does not care how the object arrived.

The `Filter` is the part worth dwelling on. Without it, every object written anywhere in the bucket
invokes the function - including, on a bucket that is also a Lambda's output destination, the objects
the function itself writes. That is the classic S3-Lambda infinite loop, and it is charged per
invocation. `prefix: transcripts/` and `suffix: .json` scope this trigger to exactly the objects it
is about.

Only one prefix rule and one suffix rule are allowed per filter, and overlapping configurations are
rejected outright by S3 - you cannot have two Lambda configurations on `transcripts/` whose key
ranges intersect.

**Command - part 2, fire it**

```bash
SOURCE=""
for candidate in outputs/lab-08-scaling-evidence.json \
                 outputs/lab-06-scaling-history.json \
                 outputs/lab-10-edge-trace.json; do
  [ -f "$candidate" ] && { SOURCE="$candidate"; break; }
done

if [ -z "$SOURCE" ]; then
  SOURCE=outputs/lab-10-first-object.json
  python3 -c "
import json, datetime
json.dump({'note': 'placeholder first object for usms-student-data',
           'created': datetime.datetime.utcnow().isoformat() + 'Z'},
          open('$SOURCE','w'), indent=2)
"
fi

printf 'uploading %s\n' "$SOURCE"

aws s3api put-object \
  --bucket "$BUCKET" \
  --key "transcripts/evidence/$(basename "$SOURCE")" \
  --body "$SOURCE" \
  --content-type application/json \
  --query '{ETag:ETag}' --output text
```

**What the command does**

The `for candidate in ...; do ... break; done` loop picks the first artefact that exists. Both
`outputs/lab-08-scaling-evidence.json` and `outputs/lab-06-scaling-history.json` exist by this point
in the course - Lab 08 Section 17 promised the former would be this bucket's first `put-object`, and
Lab 06 made the same promise for the latter - so the loop prefers Lab 08's, the more recent of the
two, and this is where that promise is kept. If neither file is present, which most likely means an
earlier lab's exercise was skipped, the `python3` block manufactures a placeholder rather than
leaving you stuck - failure mode number one from the teaching philosophy is a student who cannot
continue.

The key is `transcripts/evidence/<filename>`. Check it against the filter: it begins `transcripts/`
and ends `.json`, so it matches. That is not an accident and it is worth confirming by eye every time
you configure a filter, because a non-matching key produces exactly the same silence as a missing
permission.

**Expected result**

```text
uploading outputs/lab-08-scaling-evidence.json
"d41d8cd98f00b204e9800998ecf8427e"
```

> Example output - your ETag will differ. If Lab 08's evidence file is missing, you will see Lab 06's
> uploaded instead - that is the same fallback in the code above, not a sign anything went wrong.

**Verify**

```bash
aws s3api get-bucket-notification-configuration --bucket "$BUCKET" \
  --query 'LambdaFunctionConfigurations[].[Id,LambdaFunctionArn,Events[0]]' --output table

aws s3api list-objects-v2 --bucket "$BUCKET" --prefix transcripts/ \
  --query 'Contents[].[Key,Size]' --output table
```

**What to look for:** one notification row whose ARN ends `:live`, and one object row under
`transcripts/evidence/`. If `list-objects-v2` returns nothing, the upload failed and the notification
had nothing to react to - re-read the `put-object` output before going to Step 21.

**Checkpoint 9**

```text
usms-student-data
 ├── transcripts/evidence/lab-08-scaling-evidence.json      ← first object in this course
 └── notification: s3:ObjectCreated:*  prefix=transcripts/  suffix=.json
      └──→ usms-transcript-notifier:live
            ├── resource policy: s3.amazonaws.com, scoped to this bucket + account
            └── execution role: usms-lambda-exec-role (logs + s3:GetObject)
```

---

### Step 21 - Prove the notifier actually ran

**Purpose**

The previous step configured a trigger and uploaded an object. Neither of those is evidence that your
code executed. This step goes looking for the evidence, and - because event delivery is the least
reliable part of any emulator - gives you a second way to get it if the first produces nothing.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look for the log**

```bash
LOG_GROUP="/aws/lambda/$NOTIFIER_FN"

aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
  --query 'logGroups[].[logGroupName,storedBytes]' --output table

aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --filter-pattern "USMS_NOTIFY" \
  --query 'events[].message' --output text 2>/dev/null \
  | tee outputs/lab-10-notifier-logs.txt
```

**What the command does**

`filter-log-events` searches **across every stream** in a log group, which is what you want when you
do not know which container handled your event. `--filter-pattern "USMS_NOTIFY"` is a CloudWatch Logs
filter pattern, not a regular expression: a bare term matches log events containing that term. The
prefix exists in the handler for exactly this reason - a marker string makes an interesting line
findable among the `START`/`END`/`REPORT` noise.

**Expected result - if event delivery works on your build**

```text
usms-transcript-notifier: 1 record(s), channel=stdout, bucket_hint=usms-student-data
USMS_NOTIFY {"bucket": "usms-student-data", "event": "ObjectCreated:Put", "key": "transcripts/evidence/lab-08-scaling-evidence.json", "readable": true, "size": 2184}
```

> Example output - your key, size and `readable` value will differ.

**What to look for:** a `USMS_NOTIFY` line whose `key` is the object you uploaded. `readable` may be
`false` with a `read_error` field, which means the Lambda container could not reach the S3 API - see
the limitation note below. It does not mean the trigger failed.

**Command - part 2, the fallback: invoke with a synthetic S3 event**

Do this if part 1 printed nothing. It is not a workaround for the sake of finishing; it separates two
different failures. If the function runs correctly on a hand-made event, then your code and your
permissions are right and only the **delivery** is missing. If it fails here too, the problem is in
the handler and you have a stack trace to read.

```bash
cat > templates/lab-10-s3-event.json << EOF
{
  "Records": [
    {
      "eventVersion": "2.1",
      "eventSource": "aws:s3",
      "awsRegion": "us-east-1",
      "eventName": "ObjectCreated:Put",
      "s3": {
        "s3SchemaVersion": "1.0",
        "bucket": {
          "name": "${BUCKET}",
          "arn": "arn:aws:s3:::${BUCKET}"
        },
        "object": {
          "key": "transcripts/evidence/synthetic-probe.json",
          "size": 1024,
          "eTag": "0123456789abcdef0123456789abcdef"
        }
      }
    }
  ]
}
EOF

python3 -m json.tool templates/lab-10-s3-event.json > /dev/null && echo "valid JSON"

aws lambda invoke \
  --function-name "$NOTIFIER_FN" \
  --qualifier live \
  --payload fileb://templates/lab-10-s3-event.json \
  --log-type Tail \
  --query 'LogResult' --output text \
  outputs/lab-10-notifier-direct.json \
  | openssl base64 -d -A | tee -a outputs/lab-10-notifier-logs.txt

python3 -m json.tool outputs/lab-10-notifier-direct.json
```

**Expected result**

```text
START RequestId: 8a1f... Version: 1
usms-transcript-notifier: 1 record(s), channel=stdout, bucket_hint=usms-student-data
USMS_NOTIFY {"bucket": "usms-student-data", "event": "ObjectCreated:Put", "key": "transcripts/evidence/synthetic-probe.json", "read_error": "ClientError", "readable": false, "size": 1024}
END RequestId: 8a1f...
REPORT RequestId: 8a1f...	Duration: 241.10 ms	Billed Duration: 242 ms	Memory Size: 256 MB	Max Memory Used: 78 MB
{
    "processed": 1,
    "keys": [
        "transcripts/evidence/synthetic-probe.json"
    ]
}
```

> Example output - `read_error: ClientError` is expected here, because the synthetic key names an
> object that does not exist. That is the `head_object` guard doing its job.

**What to look for:** `"processed": 1`, and a `USMS_NOTIFY` line. Note `Version: 1` in the `START`
line rather than `$LATEST` - that is `--qualifier live` resolving through the alias to the published
version, which is exactly what S3 would do.

!!! note "Floci Limitation - S3 event delivery and outbound calls from a Lambda container"
    Two separate things vary by build.

    **Event delivery.** Some builds store the notification configuration without running the
    dispatcher, so an upload produces no invocation. The configuration is recorded correctly and you
    can read it back; nothing calls your function.

    **Outbound AWS calls from inside a Lambda container.** The container has to be told where the
    emulator's API is. When that injection is missing, `boto3.client("s3")` inside your function
    tries to reach real AWS, fails, and you see `read_error` - which is why that call is wrapped.

    Real AWS delivers the event within seconds and gives the container credentials from the execution
    role automatically, so `head_object` succeeds if - and only if - the role permits it. Here it is
    permitted by `USMSLambdaBasic` and may still fail for reasons that have nothing to do with
    permissions. Judge the permission by reading the policy, as always.

    Either way, part 2 gives you a genuine execution of your handler over a genuine S3 event
    structure, and that is what this step needs to establish.

✏️ **Your turn**

Prove the notification **filter** does what it claims, not just that the function works.

Upload a second object whose key is `notes/ignore-me.json` - inside the bucket, wrong prefix - and a
third whose key is `transcripts/evidence/ignore-me.txt` - right prefix, wrong suffix. Then look at
the logs again.

```text
Expected result:
Neither upload produces a new USMS_NOTIFY line.
list-objects-v2 shows all three objects in the bucket, so the uploads succeeded.
If your build does not deliver events at all, reason it out from the filter rules
instead and write one sentence per object saying which rule excluded it.
```

---

### Step 22 - Restart Floci and read everything back

**Purpose**

Every lab in this course ends by proving that what it built survives a restart, because the one
defect that cost students a whole lab's work was a persistence setting that reported success and
discarded everything. Lambda adds a wrinkle worth checking: function **code** is stored differently
from function **metadata**, and a build can persist one and lose the other.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the state**

```bash
inventory() {
  aws lambda list-functions \
    --query 'sort_by(Functions[?starts_with(FunctionName, `usms-`)], &FunctionName)[].[FunctionName,Runtime,MemorySize]' \
    --output text
  aws lambda list-versions-by-function --function-name usms-edge-viewer-request \
    --query "sort_by(Versions[?Version!='\$LATEST'], &Version)[].Version" --output text
  aws lambda list-aliases --function-name usms-transcript-notifier \
    --query 'Aliases[].[Name,FunctionVersion]' --output text
  aws s3api list-objects-v2 --bucket "${USMS_BUCKET_NAME:-usms-student-data}" \
    --query 'sort_by(Contents, &Key)[].Key' --output text
  aws s3api get-bucket-notification-configuration --bucket "${USMS_BUCKET_NAME:-usms-student-data}" \
    --query 'LambdaFunctionConfigurations[].Id' --output text
}

inventory | tee outputs/lab-10-pre-restart.txt
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
inventory | tee outputs/lab-10-post-restart.txt

diff outputs/lab-10-pre-restart.txt outputs/lab-10-post-restart.txt \
  && echo "IDENTICAL - every Lab 10 artefact survived the restart"
```

**Expected result**

```text
usms-edge-origin-response	nodejs20.x	128
usms-edge-viewer-request	nodejs20.x	128
usms-transcript-notifier	python3.12	256
1
live	1
transcripts/evidence/lab-08-scaling-evidence.json
usms-transcript-upload

IDENTICAL - every Lab 10 artefact survived the restart
```

> Example output - your object keys depend on Step 20 and your Your-turn uploads.

**Verify - the stronger check**

A list of names surviving is weaker evidence than it looks. What you actually want to know is whether
the **code** came back, so invoke it:

```bash
./scripts/utilities/usms-edge-simulate.sh | tail -20
```

**What to look for:** `diff` reports no differences, and the simulation still produces the
`x-usms-edge-chain` header. Name-level persistence with lost code would pass the first check and fail
the second, which is precisely the difference between a verification that checks existence and one
that checks the thing you care about.

If `diff` shows a difference, read which line moved before concluding anything: a missing function is
a persistence failure, but a changed alias version is just your Step 18 Your-turn exercise not having
been put back.

**Checkpoint 10**

```text
after floci-down.sh + floci-up.sh
 ├── 3 functions        present, same runtimes, same memory
 ├── versions           present
 ├── alias live → 1     present
 ├── bucket + object    present
 ├── notification       present
 └── edge chain         still executes and still composes
```

---

### Step 23 - Write `configs/lab-10.env`

**Purpose**

Everything you have captured so far lives in shell variables, and shell variables die with the
terminal. This is the step that turns this lab's work into something the next lab can source.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-10.env << EOF
# Lab 10 - Edge functions with AWS Lambda
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, ARNs and IDs only. NO SECRETS. Safe to commit.

# --- origin ---------------------------------------------------------------
export USMS_BUCKET_ARN=arn:aws:s3:::${USMS_BUCKET_NAME:-usms-student-data}

# --- edge function 1: viewer-request --------------------------------------
export USMS_EDGE_VIEWER_FN=usms-edge-viewer-request
export USMS_EDGE_VIEWER_FN_ARN=$(aws lambda get-function-configuration \
  --function-name usms-edge-viewer-request --query 'FunctionArn' --output text)
export USMS_EDGE_VIEWER_VERSION=$(aws lambda list-versions-by-function \
  --function-name usms-edge-viewer-request \
  --query "max_by(Versions[?Version!='\$LATEST'], &to_number(Version)).Version" --output text)
export USMS_EDGE_VIEWER_VERSION_ARN=${VIEWER_VERSION_ARN}

# --- edge function 2: origin-response -------------------------------------
export USMS_EDGE_ORIGIN_FN=usms-edge-origin-response
export USMS_EDGE_ORIGIN_FN_ARN=$(aws lambda get-function-configuration \
  --function-name usms-edge-origin-response --query 'FunctionArn' --output text)
export USMS_EDGE_ORIGIN_VERSION=$(aws lambda list-versions-by-function \
  --function-name usms-edge-origin-response \
  --query "max_by(Versions[?Version!='\$LATEST'], &to_number(Version)).Version" --output text)
export USMS_EDGE_ORIGIN_VERSION_ARN=${ORIGIN_VERSION_ARN}

export USMS_EDGE_RUNTIME=nodejs20.x
export USMS_EDGE_ROLE_ARN=${EDGE_ROLE_ARN}
export USMS_EDGE_TRACE_FILE=outputs/lab-10-edge-trace.json

# --- regional function: transcript notifier -------------------------------
export USMS_LAMBDA_NOTIFIER_FN=usms-transcript-notifier
export USMS_LAMBDA_NOTIFIER_FN_ARN=$(aws lambda get-function-configuration \
  --function-name usms-transcript-notifier --query 'FunctionArn' --output text)
export USMS_LAMBDA_NOTIFIER_RUNTIME=$(aws lambda get-function-configuration \
  --function-name usms-transcript-notifier --query 'Runtime' --output text)
export USMS_LAMBDA_NOTIFIER_ALIAS=live
export USMS_LAMBDA_NOTIFIER_ALIAS_ARN=$(aws lambda get-alias \
  --function-name usms-transcript-notifier --name live \
  --query 'AliasArn' --output text)
export USMS_LAMBDA_NOTIFIER_VERSION=$(aws lambda get-alias \
  --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text)
export USMS_LOG_GROUP_NOTIFIER=/aws/lambda/usms-transcript-notifier

# --- s3 notification ------------------------------------------------------
export USMS_NOTIFICATION_ID=usms-transcript-upload
export USMS_NOTIFICATION_PREFIX=transcripts/
export USMS_NOTIFICATION_SUFFIX=.json

# --- cloudfront (may be unsupported on this build) ------------------------
export USMS_CLOUDFRONT_SUPPORTED=$(aws cloudfront list-distributions >/dev/null 2>&1 && echo yes || echo no)
export USMS_CLOUDFRONT_DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Comment, 'usms-transcript-cdn')].Id | [0]" \
  --output text 2>/dev/null | grep -E '^[A-Z0-9]+$' || echo not-created)
export USMS_CLOUDFRONT_DOMAIN=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Comment, 'usms-transcript-cdn')].DomainName | [0]" \
  --output text 2>/dev/null | grep -E '\.' || echo not-created)
EOF

cat configs/lab-10.env
```

**What the command does**

`<< EOF` - unquoted, deliberately, and for the third and last time in this lab. Every `$(...)` in
this file must run **now**, at write time, so that the file contains values rather than commands. A
quoted heredoc here would produce a file full of `aws lambda get-function-configuration ...` text
that does nothing when sourced, and - the part that makes it dangerous - would produce no error at
all, either when written or when sourced.

Put the three heredocs of this lab side by side and the rule is visible:

| Step | Form | Because |
| --- | --- | --- |
| 6, 7, 12, 16, 17 | `<< 'EOF'` | the file must contain exactly what you typed |
| 15, 20 | `<< EOF` | two ARNs and a timestamp must be substituted |
| 23 | `<< EOF` | every value is the output of a command run now |

`"max_by(Versions[?Version!='\$LATEST'], &to_number(Version)).Version"` deserves unpacking. Versions
come back as **strings**, so `max_by` on the raw value would sort `10` before `9` lexically.
`&to_number(Version)` is an expression reference that converts each version to a number before
comparison. `\$LATEST` is escaped so that the shell - inside an unquoted heredoc - leaves the dollar
sign for JMESPath.

The CloudFront lines end with `| grep -E ... || echo not-created`. That is Lab 06's pattern:
`--output text` prints `None` when the query matches nothing, and a variable containing the literal
string `None` is worse than one containing an honest `not-created`, because `None` looks like a
value. The `grep` passes real output through and fails on `None`, so the `||` branch runs.

**Expected result**

```text
# Lab 10 - Edge functions with AWS Lambda
# Generated on 2026-09-16T07:55:41Z
# Contains names, ARNs and IDs only. NO SECRETS. Safe to commit.
...
export USMS_EDGE_VIEWER_VERSION_ARN=arn:aws:lambda:us-east-1:000000000000:function:usms-edge-viewer-request:1
...
export USMS_CLOUDFRONT_SUPPORTED=no
export USMS_CLOUDFRONT_DIST_ID=not-created
export USMS_CLOUDFRONT_DOMAIN=not-created
```

> Example output - your CloudFront lines will say `yes` and carry real values if you took Path A.

**Verify**

```bash
grep -c '^export' configs/lab-10.env

grep -n 'export .*=$\|None' configs/lab-10.env || echo "all values populated"

source configs/lab-10.env && echo "sources cleanly"
```

**What to look for:** **25** exports, the message `all values populated`, and a clean source. An
empty value or the string `None` means a resource does not exist, and catching it here is worth ten
troubleshooting entries in the next lab. `not-created` on the three CloudFront lines is a populated
value, not an empty one, and is expected on Path B.

---

### Step 24 - Check what Git sees, and commit

**Purpose**

This lab wrote source code, JSON templates, a configuration file and three ZIP archives. Exactly one
category of those does not belong in the repository, and the point of looking before committing is
that you find out which before it is in the history rather than after.

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
?? configs/lab-10.env
?? labs/lab-10-lambda-edge/
?? policies/trust-lambda-edge.json
?? scripts/utilities/usms-edge-simulate.sh
?? templates/lab-10-bucket-notification.json
?? templates/lab-10-distribution-config.json
?? templates/lab-10-origin-response-event.json
?? templates/lab-10-s3-event.json
?? templates/lab-10-viewer-request-event.json
?? templates/lab-10-viewer-request-denied.json
```

> Example output - ordering and the exact set depend on what you have done.

**What to look for**, and this is the check, not the commit:

- **No `outputs/` path appears.** Not the ZIP archives, not the trace, not the logs. If any does, the
  `.gitignore` rule has been damaged - see below.
- **No `.env` file other than `configs/lab-10.env`.** The repository's `.env` at the root is generated
  by `floci-up.sh` and must never be committed; `configs/lab-10.env` is a different thing entirely
  and is meant to be.
- **No `__pycache__`.** `py_compile` in Step 17 created one.

```bash
git check-ignore -v outputs/usms-edge-viewer-request.zip
git check-ignore -v outputs/lab-10-edge-trace.json
git ls-files outputs/
```

**Expected result**

```text
.gitignore:12:outputs/*	outputs/usms-edge-viewer-request.zip
.gitignore:12:outputs/*	outputs/lab-10-edge-trace.json
outputs/.gitkeep
```

> Example output - your line number will differ.

**What to look for:** `check-ignore` names the rule and the line that excluded each file, and
`git ls-files outputs/` lists `.gitkeep` and nothing else. That is the rule from Lab 1 still holding:
`outputs/*` excludes the contents while leaving the directory visible to Git, and
`!outputs/.gitkeep` re-includes the one file that keeps it in the tree. Had the rule been written
`outputs/` - excluding the directory itself - the negation would silently do nothing and the archives
above would be committable.

**Command - part 2, commit**

```bash
git add configs/lab-10.env \
        labs/lab-10-lambda-edge \
        policies/trust-lambda-edge.json \
        scripts/utilities/usms-edge-simulate.sh \
        scripts/utilities/verify-lab-10.sh \
        scripts/cleanup/lab-10-cleanup.sh \
        templates/lab-10-*.json

git status --short

git commit -m "Lab 10: edge functions with Lambda, origin bucket, S3-triggered notifier

- create usms-student-data, the bucket four policies have named since Lab 01
- usms-edge-viewer-request  (nodejs20.x) auth gate + URI normalisation, version 1
- usms-edge-origin-response (nodejs20.x) security headers + cache policy, version 1
- usms-transcript-notifier  (python3.12) S3 ObjectCreated -> alias live
- trust policy on usms-lambda-exec-role now names edgelambda.amazonaws.com
- usms-edge-simulate.sh runs the edge chain without a CloudFront request path"
```

**What the command does**

`git add` names paths explicitly rather than using `git add -A`. On a repository that contains a
git-ignored directory full of secrets, `-A` is safe only because the ignore rule is correct - and
naming the paths means you are not relying on that being true. The two habits reinforce each other
rather than duplicating.

`verify-lab-10.sh` and `lab-10-cleanup.sh` are in the list; you create them in Section 9 and
Section 16. If you are running the steps in order and have not reached those yet, `git add` will
report them as missing - add them in a second commit after Section 9, or run this step last.

**Verify**

```bash
git log --oneline -1
git show --stat --oneline HEAD | head -20
```

**What to look for:** the commit exists, and the file list contains no `outputs/` path and no `.zip`.

**Checkpoint 11**

```text
aws-floci-course/  (committed)
 ├── configs/lab-10.env ................ 25 exports, no secrets
 ├── labs/lab-10-lambda-edge/ .......... 3 handlers
 ├── policies/trust-lambda-edge.json ... 2 service principals
 ├── templates/lab-10-*.json ........... 6 request bodies and events
 └── scripts/utilities/usms-edge-simulate.sh

outputs/  (git-ignored, correctly)
 ├── 3 × .zip
 ├── lab-10-edge-trace.json
 ├── lab-10-support-probe.txt
 ├── lab-10-function-inventory.json
 ├── lab-10-pre-restart.txt / lab-10-post-restart.txt
 └── lab-10-notifier-logs.txt
```

---
## 9. Verification

One script, run at the end of the lab and at the start of the next one. It checks three things that
are easy to confuse:

- that the resources **exist**,
- that they are **configured** the way the lab requires - which is where a verification script earns
  its keep, because existence survives most mistakes,
- and that the environment underneath them is still sound, because a lab that verifies only its own
  resources passes right up until the restart that deletes them.

Several checks in it are the static substitutes for enforcement Floci does not perform: that no edge
function carries environment variables, that every associated ARN is version-qualified, that the
resource policy is scoped to one bucket. Those are the rules you cannot learn here by breaking them,
so the script checks them on every run instead.

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-10.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 10 artefact exists AND is configured for the edge.
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

BUCKET="${USMS_BUCKET_NAME:-usms-student-data}"
ROLE_NAME="${USMS_ROLE_LAMBDA:-usms-lambda-exec-role}"
VIEWER=usms-edge-viewer-request
ORIGIN=usms-edge-origin-response
NOTIFIER=usms-transcript-notifier
DIST_CFG=templates/lab-10-distribution-config.json

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ✔ %s\n" "$1"; PASS=$((PASS+1))
  else printf "  ✗ %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# --- helpers -------------------------------------------------------------
# Defined as functions so the check strings below stay free of nested quoting.

fn_field() {   # $1 = function name, $2 = JMESPath field
  aws lambda get-function-configuration --function-name "$1" --query "$2" --output text
}

fn_env_count() {   # $1 = function name
  aws lambda get-function-configuration --function-name "$1" --output json 2>/dev/null \
    | python3 -c 'import json,sys; c=json.load(sys.stdin); print(len((c.get("Environment") or {}).get("Variables") or {}))'
}

fn_version_count() {   # $1 = function name; includes $LATEST, so >= 2 means published
  aws lambda list-versions-by-function --function-name "$1" --query 'length(Versions)' --output text
}

alias_version() {   # $1 = function name, $2 = alias
  aws lambda get-alias --function-name "$1" --name "$2" --query 'FunctionVersion' --output text
}

role_principals() {
  aws iam get-role --role-name "$ROLE_NAME" \
    --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output json
}

notifier_policy() {
  aws lambda get-policy --function-name "$NOTIFIER" --qualifier live --query 'Policy' --output text
}

dist_assoc() {   # prints one line per association: <eventType> <arn>
  python3 - "$DIST_CFG" << 'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
for i in cfg['DefaultCacheBehavior']['LambdaFunctionAssociations']['Items']:
    print(i['EventType'], i['LambdaFunctionARN'])
PY
}

dist_arns_qualified() {
  dist_assoc | awk '{print $2}' | awk -F: '{print $NF}' \
    | grep -qvE '^[0-9]+$' && return 1 || return 0
}

policy_bucket_arns() {
  local arn
  arn=$(aws iam list-policies --scope Local \
        --query "Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]" --output text)
  aws iam get-policy-version --policy-arn "$arn" \
    --version-id "$(aws iam get-policy --policy-arn "$arn" \
                     --query 'Policy.DefaultVersionId' --output text)" \
    --query 'PolicyVersion.Document.Statement[].Resource' --output text
}

echo "== Environment =="
check "Floci container running" \
  'test "$(docker container inspect $FLOCI_CONTAINER_NAME --format "{{.State.Running}}")" = true'
check "Storage mode is NOT memory" \
  'docker container inspect $FLOCI_CONTAINER_NAME --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -qE "^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$"'
check "AWS CLI reaches Floci" \
  'aws sts get-caller-identity'

echo "== Origin bucket =="
check "bucket $BUCKET exists" \
  'aws s3api head-bucket --bucket "$BUCKET"'
check "bucket is tagged Project=USMS" \
  'aws s3api get-bucket-tagging --bucket "$BUCKET" --output text | grep -q USMS'
check "at least one object under transcripts/" \
  'test "$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix transcripts/ --query "length(Contents)" --output text)" != "None"'
check "USMSStudentDataReadWrite names this bucket, and it now resolves" \
  'policy_bucket_arns | grep -q "arn:aws:s3:::$BUCKET"'

echo "== Execution role =="
check "role $ROLE_NAME exists" \
  'aws iam get-role --role-name "$ROLE_NAME"'
check "role trusts lambda.amazonaws.com" \
  'role_principals | grep -q "\"lambda.amazonaws.com\""'
check "role trusts edgelambda.amazonaws.com  (Lambda@Edge requirement)" \
  'role_principals | grep -q "edgelambda.amazonaws.com"'
check "USMSLambdaBasic is attached to the role" \
  'aws iam list-attached-role-policies --role-name "$ROLE_NAME" --output text | grep -q USMSLambdaBasic'

echo "== Edge function 1: viewer-request =="
check "$VIEWER exists" \
  'aws lambda get-function-configuration --function-name "$VIEWER"'
check "runtime is node or python  (the only two the edge accepts)" \
  'fn_field "$VIEWER" Runtime | grep -qE "^(nodejs|python)"'
check "handler is index.handler" \
  'test "$(fn_field "$VIEWER" Handler)" = index.handler'
check "memory is within the 128 MB viewer cap" \
  'test "$(fn_field "$VIEWER" MemorySize)" -le 128'
check "timeout is within the 5 s viewer cap" \
  'test "$(fn_field "$VIEWER" Timeout)" -le 5'
check "NO environment variables  (forbidden at the edge)" \
  'test "$(fn_env_count "$VIEWER")" -eq 0'
check "at least one published version exists" \
  'test "$(fn_version_count "$VIEWER")" -ge 2'

echo "== Edge function 2: origin-response =="
check "$ORIGIN exists" \
  'aws lambda get-function-configuration --function-name "$ORIGIN"'
check "runtime is node or python" \
  'fn_field "$ORIGIN" Runtime | grep -qE "^(nodejs|python)"'
check "memory is within the cap chosen for it" \
  'test "$(fn_field "$ORIGIN" MemorySize)" -le 128'
check "NO environment variables" \
  'test "$(fn_env_count "$ORIGIN")" -eq 0'
check "at least one published version exists" \
  'test "$(fn_version_count "$ORIGIN")" -ge 2'

echo "== Regional function: transcript notifier =="
check "$NOTIFIER exists" \
  'aws lambda get-function-configuration --function-name "$NOTIFIER"'
check "handler is notifier.handler" \
  'test "$(fn_field "$NOTIFIER" Handler)" = notifier.handler'
check "HAS environment variables  (legal here, and the contrast is the point)" \
  'test "$(fn_env_count "$NOTIFIER")" -ge 1'
check "alias live exists" \
  'aws lambda get-alias --function-name "$NOTIFIER" --name live'
check "alias live points at a numbered version, not \$LATEST" \
  'alias_version "$NOTIFIER" live | grep -qE "^[0-9]+$"'
check "resource policy allows s3.amazonaws.com" \
  'notifier_policy | grep -q "s3.amazonaws.com"'
check "resource policy is scoped to this bucket  (no confused deputy)" \
  'notifier_policy | grep -q "$BUCKET"'

echo "== S3 notification =="
check "bucket notification usms-transcript-upload exists" \
  'aws s3api get-bucket-notification-configuration --bucket "$BUCKET" --output text | grep -q usms-transcript-upload'
check "notification targets the live alias" \
  'aws s3api get-bucket-notification-configuration --bucket "$BUCKET" --output text | grep -q "function:$NOTIFIER:live"'
check "notification is filtered to transcripts/" \
  'aws s3api get-bucket-notification-configuration --bucket "$BUCKET" --output text | grep -q "transcripts/"'

echo "== CloudFront association configuration =="
check "distribution config file exists" \
  'test -f "$DIST_CFG"'
check "distribution config is valid JSON" \
  'python3 -m json.tool "$DIST_CFG"'
check "exactly two associations declared" \
  'test "$(dist_assoc | wc -l | tr -d " ")" -eq 2'
check "viewer-request is associated" \
  'dist_assoc | grep -q "^viewer-request "'
check "origin-response is associated" \
  'dist_assoc | grep -q "^origin-response "'
check "every associated ARN is version-qualified  (the edge refuses \$LATEST and aliases)" \
  'dist_arns_qualified'
check "cache key forwards no cookies" \
  'python3 -c "import json;print(json.load(open(\"$DIST_CFG\"))[\"DefaultCacheBehavior\"][\"ForwardedValues\"][\"Cookies\"][\"Forward\"])" | grep -q none'

echo "== Source, scripts and Git hygiene =="
check "viewer-request handler source exists" \
  'test -f labs/lab-10-lambda-edge/edge-viewer-request/index.mjs'
check "origin-response handler source exists" \
  'test -f labs/lab-10-lambda-edge/edge-origin-response/index.mjs'
check "notifier handler source exists" \
  'test -f labs/lab-10-lambda-edge/transcript-notifier/notifier.py'
check "viewer handler kept its template literal  (heredoc was quoted)" \
  'grep -q "studentId.toLowerCase()}" labs/lab-10-lambda-edge/edge-viewer-request/index.mjs'
check "usms-edge-simulate.sh is executable and valid bash" \
  'test -x scripts/utilities/usms-edge-simulate.sh && bash -n scripts/utilities/usms-edge-simulate.sh'
check "edge trace records the full three-stage chain" \
  'python3 -c "import json;t=json.load(open(\"outputs/lab-10-edge-trace.json\"));print(len(t[\"chain\"]))" | grep -q 3'
check "configs/lab-10.env exists" \
  'test -f configs/lab-10.env'
check "configs/lab-10.env has 25 exports" \
  'test "$(grep -c "^export" configs/lab-10.env)" -eq 25'
check "configs/lab-10.env has no empty values" \
  '! grep -qE "^export [A-Z_]+=$" configs/lab-10.env'
check "no secret is tracked" \
  '! git ls-files | grep -q "^outputs/"'
check "no deployment archive is tracked" \
  '! git ls-files | grep -q "\.zip$"'

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-10.sh
bash -n scripts/utilities/verify-lab-10.sh && echo "syntax OK"
./scripts/utilities/verify-lab-10.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ✔ Floci container running
  ✔ Storage mode is NOT memory
  ✔ AWS CLI reaches Floci
== Origin bucket ==
  ✔ bucket usms-student-data exists
  ✔ bucket is tagged Project=USMS
  ✔ at least one object under transcripts/
  ✔ USMSStudentDataReadWrite names this bucket, and it now resolves
== Execution role ==
  ✔ role usms-lambda-exec-role exists
  ✔ role trusts lambda.amazonaws.com
  ✔ role trusts edgelambda.amazonaws.com  (Lambda@Edge requirement)
  ✔ USMSLambdaBasic is attached to the role
== Edge function 1: viewer-request ==
  ✔ usms-edge-viewer-request exists
  ✔ runtime is node or python  (the only two the edge accepts)
  ✔ handler is index.handler
  ✔ memory is within the 128 MB viewer cap
  ✔ timeout is within the 5 s viewer cap
  ✔ NO environment variables  (forbidden at the edge)
  ✔ at least one published version exists
== Edge function 2: origin-response ==
  ✔ usms-edge-origin-response exists
  ✔ runtime is node or python
  ✔ memory is within the cap chosen for it
  ✔ NO environment variables
  ✔ at least one published version exists
== Regional function: transcript notifier ==
  ✔ usms-transcript-notifier exists
  ✔ handler is notifier.handler
  ✔ HAS environment variables  (legal here, and the contrast is the point)
  ✔ alias live exists
  ✔ alias live points at a numbered version, not $LATEST
  ✔ resource policy allows s3.amazonaws.com
  ✔ resource policy is scoped to this bucket  (no confused deputy)
== S3 notification ==
  ✔ bucket notification usms-transcript-upload exists
  ✔ notification targets the live alias
  ✔ notification is filtered to transcripts/
== CloudFront association configuration ==
  ✔ distribution config file exists
  ✔ distribution config is valid JSON
  ✔ exactly two associations declared
  ✔ viewer-request is associated
  ✔ origin-response is associated
  ✔ every associated ARN is version-qualified  (the edge refuses $LATEST and aliases)
  ✔ cache key forwards no cookies
== Source, scripts and Git hygiene ==
  ✔ viewer-request handler source exists
  ✔ origin-response handler source exists
  ✔ notifier handler source exists
  ✔ viewer handler kept its template literal  (heredoc was quoted)
  ✔ usms-edge-simulate.sh is executable and valid bash
  ✔ edge trace records the full three-stage chain
  ✔ configs/lab-10.env exists
  ✔ configs/lab-10.env has 25 exports
  ✔ configs/lab-10.env has no empty values
  ✔ no secret is tracked
  ✔ no deployment archive is tracked

PASS=51  FAIL=0
```

> Example output - this is the target.

**The expected count is `PASS=51  FAIL=0`.**

Two notes on reading a failure:

**Failures in the Environment block are the real problem.** If Floci is not running, everything below
it fails as a consequence and none of those lower failures tells you anything. Fix the top block
first and re-run before reading anything else.

**None of these checks depends on CloudFront being supported.** The association block reads
`templates/lab-10-distribution-config.json`, which both Path A and Path B produce. That is deliberate:
a verification script whose result depends on which emulator build you happen to have is not a
verification script.

Two checks that are worth understanding rather than merely passing:

| Check | Why it is there |
| --- | --- |
| `viewer handler kept its template literal` | The static detector for an unquoted heredoc in Step 7. That bug produces a function that deploys, runs, and silently stamps an empty student id - nothing else in this script would catch it |
| `every associated ARN is version-qualified` | The static substitute for the validation real AWS performs and Floci does not. It is the only thing standing between you and an association that would be rejected in production |

---

## 10. Checkpoints

| # | After Step | What must exist | How to check it in one line |
| --- | --- | --- | --- |
| 1 | 5 | `usms-student-data`, tagged, and `USMSStudentDataReadWrite` resolving to it | `aws s3api head-bucket --bucket usms-student-data` |
| 2 | 6 | `usms-lambda-exec-role` trusting both `lambda` and `edgelambda` | `aws iam get-role --role-name usms-lambda-exec-role --query 'length(Role.AssumeRolePolicyDocument.Statement[0].Principal.Service)'` |
| 3 | 9 | `usms-edge-viewer-request`, invoked on both the allow and the deny path | `python3 -m json.tool outputs/lab-10-viewer-allow.json` |
| 4 | 11 | Version 1 of the viewer function, and a version-qualified ARN | `aws lambda list-versions-by-function --function-name usms-edge-viewer-request --query 'Versions[].Version'` |
| 5 | 14 | Both edge functions edge-eligible: no env vars, within caps, published | `grep -c '  NO   ' outputs/lab-10-function-inventory.json` |
| 6 | 15 | A distribution, or a validated configuration, associating both functions | `python3 -m json.tool templates/lab-10-distribution-config.json` |
| 7 | 16 | The chain running end to end, allow and deny | `./scripts/utilities/usms-edge-simulate.sh` |
| 8 | 18 | `usms-transcript-notifier`, version 1, alias `live` | `aws lambda list-aliases --function-name usms-transcript-notifier` |
| 9 | 20 | Bucket notification wired to the alias and an object uploaded | `aws s3api get-bucket-notification-configuration --bucket usms-student-data` |
| 10 | 22 | All of the above surviving a stop and start | `diff outputs/lab-10-pre-restart.txt outputs/lab-10-post-restart.txt` |
| 11 | 24 | A commit containing the source and no `outputs/` path | `git show --stat HEAD` |

---

## 11. Troubleshooting

### `aws lambda list-functions` returns a connection error, exit code 255

Exit `255` is a client or connection failure, not a service error. Floci is not answering.

{% raw %}```bash
docker container inspect floci --format '{{.State.Status}}'
./scripts/setup/floci-up.sh
curl -s http://localhost:4566/_localstack/health | head -5
```{% endraw %}

If the container is running but the health probe is empty, Floci is still starting - the first start
after an image pull can take a minute. Wait and retry before concluding anything.

### `create-function` fails with `InvalidParameterValueException: The role defined for the function cannot be assumed by Lambda`

Real AWS raises this when the trust policy does not name `lambda.amazonaws.com`. If you see it here,
you have probably run Step 6's `update-assume-role-policy` with a document naming only
`edgelambda.amazonaws.com` - remember that the update **replaces** the whole policy.

```bash
aws iam get-role --role-name usms-lambda-exec-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output json
```

Two entries, not one. Re-run Step 6 part 2 and part 3 if you see one.

### The function returns `Unhandled` with `Cannot find module 'index'`

The archive does not contain `index.mjs` at its root, or the handler string does not match the file
name. Look inside the archive rather than guessing:

```bash
python3 -m zipfile -l outputs/usms-edge-viewer-request.zip
aws lambda get-function-configuration --function-name usms-edge-viewer-request --query 'Handler'
```

A line reading `labs/lab-10-lambda-edge/edge-viewer-request/index.mjs` instead of plain `index.mjs`
means you built the archive from the repository root. Rebuild it from inside the function's directory
- Step 8 part 1 explains why the subshell is there.

### The function runs but the student id in `x-usms-edge` is empty

Your Step 7 heredoc was unquoted and bash expanded the template literal before the file was written.

```bash
grep -n 'toLowerCase()}' labs/lab-10-lambda-edge/edge-viewer-request/index.mjs
```

No output means the expression is gone. Delete the file, re-run Step 7 with `<< 'EOF'` - with the
apostrophes - rebuild the archive, and update the code:

```bash
aws lambda update-function-code --function-name usms-edge-viewer-request \
  --zip-file fileb://outputs/usms-edge-viewer-request.zip
```

Then publish a new version, because version 1 still contains the broken code and is immutable.

### `invoke` writes an empty file and prints nothing useful

You probably forgot the positional output-file argument. `aws lambda invoke` requires it; the
function's return value goes there and only metadata goes to stdout. Also check that you used
`--payload fileb://` and not `--payload file://` - the latter hands the CLI a string where it expects
bytes, and the resulting error mentions base64 rather than mentioning your file.

### `LogResult` is `None`, or the log group does not exist

Log capture is build-dependent. Before assuming your function is silent, confirm it ran at all by
reading its return value - Step 9's payload is the evidence, and it does not depend on logs.

If you need logs and this build does not provide them, add `print()` or `console.log` output to the
handler and read the **returned object** instead; the notifier in Step 17 already returns a summary
for exactly this reason.

### The upload in Step 20 produces no invocation

Three candidates, in the order worth checking:

```bash
# 1. does the key match the filter?
aws s3api list-objects-v2 --bucket usms-student-data --query 'Contents[].Key' --output text

# 2. is the notification actually configured?
aws s3api get-bucket-notification-configuration --bucket usms-student-data

# 3. can the function be invoked at all, given a hand-made event?
aws lambda invoke --function-name usms-transcript-notifier --qualifier live \
  --payload fileb://templates/lab-10-s3-event.json /dev/stdout
```

If 1 and 2 are correct and 3 works, the delivery mechanism is not implemented on your build. That is
the Step 21 limitation and it is not something you can fix; record it and move on.

### `create-distribution` fails with `InvalidArgument` or the operation does not exist

Your build does not implement CloudFront. Take Path B in Step 15. Nothing later in the lab depends on
the distribution existing - Step 16 is the proof path, and Section 9 verifies the configuration file
rather than the distribution.

### `put-bucket-notification-configuration` fails with `InvalidArgument: Unable to validate the following destination configurations`

On real AWS this is the resource policy: S3 checks, at configuration time, that it is permitted to
invoke the target, and refuses to save a configuration it could not act on. It is one of the few
places AWS validates a permission eagerly rather than at call time.

Re-run Step 19 and confirm with `aws lambda get-policy --function-name usms-transcript-notifier
--qualifier live`. Note the `--qualifier`: a permission on the unqualified function does not cover an
invocation of `:live`.

### `verify-lab-10.sh` reports `configs/lab-10.env has 25 exports` as a failure

Count them and find the missing one:

```bash
grep -c '^export' configs/lab-10.env
grep -nE '^export [A-Z_]+=$' configs/lab-10.env
```

An export with an empty value means the `$(...)` that produced it returned nothing - usually because
the resource was created in a terminal you have since closed and the shell variable it referenced was
empty when the heredoc ran. Re-derive the value with an `aws` call and edit the line, or re-run
Step 23 in a shell where Steps 8 to 18 have been re-sourced.

### Everything worked yesterday and nothing works today

```bash
./scripts/utilities/floci-storage-check.sh
```

`FAIL` in the shell block means a new terminal lost the course environment - Errata 01. `FAIL` on the
storage-mode check means Floci is running in `memory` mode and yesterday's work is gone; the fix is
the compose file, and the loss is unfortunately real.

---
## 12. Floci vs Real AWS

### 12.1 Feature by feature

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `create-function`, `update-function-code`, `publish-version` | Full lifecycle, code stored in S3 behind the scenes | Works; code stored and executed in a container | **Implemented in Floci** |
| Synchronous `invoke` with a JSON payload | Runs the handler, returns its value | Runs the handler, returns its value | **Implemented in Floci** |
| Versions and aliases | Immutable versions, movable aliases | Both recorded and resolvable; `--qualifier` works | **Implemented in Floci** |
| Environment variables | Injected into the runtime, encrypted at rest with KMS | Injected; no encryption | **Implemented in Floci** |
| `--log-type Tail` and `/aws/lambda/<fn>` log groups | Always present | Build-dependent; may return empty `LogResult` | **Floci Limitation** |
| Resource policy (`add-permission`, `get-policy`) | Checked on every invocation | Stored and returned; never checked | **Floci Limitation** |
| Execution role permissions | Enforced per API call made by your code | Not enforced; any call your code makes succeeds or fails on connectivity alone | **Floci Limitation** |
| S3 `ObjectCreated` notification to Lambda | Delivered within seconds | Configuration stored; delivery build-dependent | **Floci Limitation** |
| Credentials inside the Lambda container | Supplied automatically from the execution role | Often absent; `boto3` may try to reach real AWS | **Floci Limitation** |
| `cloudfront create-distribution` | Creates a real distribution, `InProgress` then `Deployed` | Absent on many builds; a record at best | **Floci Limitation** |
| `LambdaFunctionAssociations` validation | Region, version-qualified ARN, no env vars, caps - all checked and rejected | Stored without validation | **Floci Limitation** |
| Lambda@Edge replication and execution | Function copied to every point of presence, runs on the request path | Never executed. No emulator does this | **Conceptual / Real AWS** |
| Edge logs in the region nearest the viewer | Yes - a function serving Bhutan logs to an Asia-Pacific region | No edge locations exist | **Conceptual / Real AWS** |
| CloudFront Functions (`cloudfront-js-2.0`) | Separate runtime, viewer triggers only, sub-millisecond | Absent | **Conceptual / Real AWS** |
| Cache behaviour, TTLs, cache hit ratio | Real caching with measurable hit rates | No cache exists | **Conceptual / Real AWS** |
| Origin access control, signed URLs, WAF at the edge | Available | Absent | **Conceptual / Real AWS** |
| Cost: per-request, per-GB-second, per-replication | Real, and edge invocations are priced differently from regional ones | Free | **Conceptual / Real AWS** |

### 12.2 What you observed, and what you recorded

```text
OBSERVED - you saw this happen on your own machine
  · a Node.js function created from a zip you built, and invoked
  · the CloudFront event structure parsed correctly, including the header array shape
  · a request modified: uri normalised, x-usms-edge stamped
  · a request refused: a 403 response object returned instead of a request
  · a response modified: four security headers and a cache policy added
  · TWO FUNCTIONS COMPOSING - the header written by the first read by the second
  · an immutable version published, and an alias pointing at one
  · a resource policy attached, scoped by source ARN, and read back
  · a bucket created, an object uploaded, a notification configured
  · every one of the above surviving a container restart

RECORDED - correct, checkable by reading, not executed here
  · the two-principal trust policy Lambda@Edge requires
  · the distribution configuration, including both associations
  · the version-qualified ARN rule
  · the no-environment-variables rule (deliberately violated, then undone)
  · the memory and timeout caps per trigger point

NOT AVAILABLE AT ALL
  · an actual edge location, an actual cache, an actual viewer request
  · CloudFront Functions
  · replication latency, cache hit ratio, cost
```

### 12.3 Where Floci is nicer than reality

These are the traps. Every one of them is something that worked here and will not work the same way
in production.

- **Associations are accepted without validation.** Here, an association pointing at `$LATEST` or at a
  function with environment variables is stored happily. Real AWS refuses the whole
  `update-distribution` call, and the error arrives minutes after the mistake, about a different
  resource. This is why Section 9 checks it statically.
- **Deployment is instant.** `create-distribution` returns and you move on. A real distribution takes
  several minutes to reach `Deployed`, and an update to an associated function version takes the same
  again - so a bad edge deploy has a rollback time measured in minutes, not seconds. That, not the
  code, is what makes edge deployments feel risky.
- **Nothing is cached, so nothing is stale.** Your `origin-response` function's headers appear
  immediately on every request. On real CloudFront they are baked into the cached object, so fixing a
  wrong header means an invalidation or a wait for the TTL. Cached mistakes outlive the code that made
  them.
- **IAM is not evaluated.** The resource policy you attached in Step 19 is decorative here. In
  production, omitting it produces an S3 notification that fails silently - no error, no log, nothing
  happens - which is among the hardest AWS misconfigurations to diagnose.
- **No cold starts, no concurrency limits, no throttling.** A viewer-request function that takes
  400 ms to initialise is invisible here and is a measurable latency regression at the edge, on the
  exact request path you added it to speed up.
- **No cost.** Edge invocations are billed per request with no free tier, and a viewer-trigger
  function runs on cache hits too. The choice between `origin-response` and `viewer-response` in
  Step 12 was free here and is a three-order-of-magnitude difference in a real bill.

!!! note "Floci Limitation - the one that shapes this whole lab"
    Floci does not run Lambda@Edge. There is no edge location for a replicated function to run in, and
    no request path for it to intercept.

    Real AWS replicates the published version to every point of presence in the distribution's price
    class and invokes it there, logging to the region nearest the viewer.

    What this lab gives you instead is the whole of the function contract - the event structure, the
    return shapes, the trigger-point semantics, the association rules - exercised directly, plus
    `usms-edge-simulate.sh`, which runs the chain in the order CloudFront would. What you cannot get
    here is latency, caching and cost, and those are precisely the three things you must not claim to
    have tested.

---

## 13. Independent Lab Exercises

Five exercises, increasing in difficulty. Record your commands and outputs in
`labs/lab-10-lambda-edge/exercises.md`; several of them ask for a file in `outputs/` as well.

### Exercise 1 - Basic: extend the security header set

**Requirements**

Add a `Content-Security-Policy` header to the origin-response function, with a policy that permits
only same-origin content: `default-src 'self'`. Deploy the change, publish version 2 of the function,
and prove that version 1 still returns the original four headers.

**Constraints**

- The header must be added by editing the `SECURITY_HEADERS` object, not by adding a second block of
  code. That object exists so that this is a one-line change.
- You may not delete or overwrite version 1.
- Update the distribution configuration file to reference the new version.

**Expected outcome**

An invocation of `usms-edge-origin-response` at `$LATEST` returns five security headers; an
invocation with `--qualifier 1` returns four. `templates/lab-10-distribution-config.json` names
version 2.

**Hints**

- `aws lambda update-function-code` takes the same `--zip-file fileb://` as `create-function`.
- `--qualifier` works on `invoke`, not just on `get-function-configuration`.
- A version is a snapshot of `$LATEST` at the moment you publish it, so the order of operations
  matters: update the code, then publish.

---

### Exercise 2 - Intermediate: a dedicated edge execution role

**Requirements**

`usms-lambda-exec-role` is now carrying three functions with different jobs, and the edge functions do
not need `s3:GetObject` at all - they never touch the bucket. Create a separate role,
`usms-edge-exec-role`, with a new customer managed policy `USMSEdgeBasic` granting **only**
CloudWatch Logs writes. Trust both `lambda.amazonaws.com` and `edgelambda.amazonaws.com`. Repoint
both edge functions at it and publish new versions.

Then answer, in `labs/lab-10-lambda-edge/exercises.md`, what happened to version 1's role.

**Constraints**

- Follow the course naming conventions: `policies/usms-edge-basic-policy.json` and
  `policies/trust-lambda-edge.json` - the second already exists and is reusable as-is.
- Do not modify or detach anything from `usms-lambda-exec-role`; the notifier still uses it.
- The log-write permission must be scoped to `/aws/lambda/usms-edge-*`, not to `*`.

**Expected outcome**

`get-function-configuration --qualifier 1` on either edge function still reports the **old** role;
`--qualifier $LATEST` reports the new one. Your written answer explains why, and says what that
implies for a rollback: repointing to an old version restores its old role along with its old code.

**Hints**

- Lab 01 created five policies this way; `policies/usms-*-policy.json` has the shape.
- A log-group ARN looks like
  `arn:aws:logs:us-east-1:000000000000:log-group:/aws/lambda/usms-edge-*:*` - the trailing `:*`
  covers the streams inside the group and is the part people leave off.
- Lab 09 Step 4's audit script already knows how to list what a role carries.

---

### Exercise 3 - Problem solving: an edge-readiness report

**Requirements**

Write `scripts/utilities/usms-edge-report.sh` which, for every Lambda function in the account whose
name begins `usms-`, emits a single JSON document to stdout reporting: name, runtime, memory,
timeout, number of published versions, number of aliases, whether environment variables are set, and
a boolean `edge_eligible`.

`edge_eligible` must be `true` only when all of: runtime is Node or Python; no environment variables;
no VPC configuration; at least one published version; memory no greater than 128 and timeout no
greater than 5 **if** the function's name contains `viewer`, otherwise memory no greater than 10240
and timeout no greater than 30.

**Constraints**

- Valid JSON on stdout and nothing else; diagnostics go to stderr.
- Must run correctly from any directory.
- Must not fail under `set -u` when a function has no `Environment` key at all.
- Do not hard-code the function list.

**Expected outcome**

```text
Expected shape:
[
  { "name": "usms-edge-viewer-request", "runtime": "nodejs20.x", "memory": 128,
    "timeout": 5, "versions": 1, "aliases": 0, "env_vars": false, "edge_eligible": true },
  ...
]
```

Three objects, and the notifier reporting `edge_eligible: false` for two independent reasons.

**Hints**

- Step 14's `edge_eligibility` function has the per-field logic; this exercise is about structuring
  the output, not rediscovering the rules.
- `aws lambda list-functions --query 'Functions[?starts_with(FunctionName, ...)]'` gets you the list
  in one call, with most of the configuration already in it.
- Building JSON by string concatenation in bash is how you produce invalid JSON. Pipe the AWS output
  into `python3` and build the document there.
- `${BASH_SOURCE[0]}` is how the other scripts in this repository find the root.

---

### Exercise 4 - Challenge: design the transcript delivery policy

The registrar has read about edge functions and has brought you four requirements. They have not
brought you a design.

> Transcripts must never be served to a request without a valid session token, and the check must not
> cost us an origin request. A corrected transcript must stop being served within five minutes of the
> correction, but we do not want to pay to re-fetch unchanged transcripts every five minutes. The
> Dean's office needs a report of how many transcript requests were refused, by faculty. And whatever
> you build must survive one edge location being unable to reach the origin.

**Requirements**

Write `notes/lab-10-edge-design.md` - one to two pages - that:

1. Chooses, for each piece of logic, between a CloudFront Function, a Lambda@Edge function at a named
   trigger point, and a regional function. Justify each choice in one or two sentences.
2. States the cache key you would configure, and what you would deliberately **not** put in it.
3. Explains how the five-minute correction window and the do-not-re-fetch requirement can both be
   met, given that they appear to conflict.
4. Says where the refusal report comes from, given that edge logs land in the region nearest the
   viewer.
5. Names one requirement here that an edge function is the **wrong** tool for, and says what you would
   use instead.

**Constraints**

- No commands. This is a design document.
- Every AWS feature you name must be one that exists; if you are unsure, say what you would verify
  and how.
- You must state at least one thing you would measure before committing to the design, and what
  result would change your mind.

**Expected outcome**

A document a colleague could implement from, in which the interesting paragraphs are the trade-offs
rather than the feature list. There is more than one defensible answer to point 3; there is only one
defensible attitude to point 5.

**Hints**

- Reread Step 12's argument about `origin-response` versus `viewer-response`. Point 3 is the same
  kind of reasoning applied to TTLs: `Cache-Control: max-age` and `s-maxage` control different caches.
- Point 4 is about where logs physically are, which Section 12.2 states.
- Point 5: something in that list is not on the request path at all.

---

### Exercise 5 - Integration: hand the S3 lab a bucket it can start from

The next lab configures `usms-student-data` properly - versioning, encryption, lifecycle, and the
bucket policy Lab 09 drafted. It needs to know what it is inheriting, and it needs the drafted policy
checked against a bucket that now actually exists.

**Requirements**

1. Locate `outputs/lab-09-bucket-policy-draft.json`. If you skipped Lab 09's Exercise 5 and do not
   have it, generate an equivalent draft from `USMSStudentDataReadWrite`: a resource policy on the
   bucket granting the three role ARNs that carry that policy `s3:GetObject` on
   `arn:aws:s3:::usms-student-data/*`. Write it to the same path.
2. Validate it against reality: every bucket ARN it names must match the bucket that now exists, and
   every principal ARN it names must be a role that currently exists. Report any mismatch; do not fix
   it silently.
3. **Do not apply it.** Applying a bucket policy is the S3 lab's step, and Floci does not evaluate it
   anyway.
4. Upload `outputs/lab-10-edge-trace.json` - the **allow** trace - to
   `s3://usms-student-data/transcripts/evidence/lab-10-edge-trace.json`, and confirm from the logs or
   from a direct invocation that the notifier saw it.
5. Write `outputs/lab-10-s3-readiness.txt` containing: the bucket name and ARN; the number of
   objects currently under `transcripts/`; the notification configuration id, target ARN and filter;
   the three functions with their published versions; whether CloudFront was supported on your build;
   and the validation result from point 2.

**Constraints**

- `outputs/lab-10-s3-readiness.txt` must be generated by a command sequence you can re-run, not
  typed by hand.
- Nothing in it may be a secret, but it stays in `outputs/` regardless - confirm with
  `git check-ignore -v`.
- The draft policy file must remain unapplied. Verify with
  `aws s3api get-bucket-policy --bucket usms-student-data`, which should fail.

**Expected outcome**

```text
Expected result:
- outputs/lab-09-bucket-policy-draft.json exists and every ARN in it resolves
- get-bucket-policy on usms-student-data FAILS (NoSuchBucketPolicy) - correct, the S3 configuration
  lab applies it
- at least two objects under transcripts/
- outputs/lab-10-s3-readiness.txt exists, is git-ignored, and is reproducible
```

**Hints**

- `aws iam list-entities-for-policy --policy-arn <USMSStudentDataReadWrite>` gives you the roles that
  carry it; Lab 08's Section 17 pre-flight used exactly this call and expected three names.
- A failing `get-bucket-policy` is the success condition here. `|| echo "no bucket policy - correct"`
  turns that into readable output.
- Step 20's `for candidate in ...` loop is the pattern for "use this file if it exists, otherwise
  generate one".

---

## 14. Lab Assessment Checklist

Tick these before you submit. Every one is checkable by a command you have already run.

**Environment and cumulative state**

- [ ] `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] Every `configs/lab-NN.env` from Labs 01 through 09 was sourced in Step 2 without error
- [ ] `whoami.sh` reports account `000000000000`

**Resources**

- [ ] `usms-student-data` exists and is tagged `Project=USMS`
- [ ] `USMSStudentDataReadWrite` resolves to the bucket that now exists
- [ ] `usms-lambda-exec-role` trusts both `lambda.amazonaws.com` and `edgelambda.amazonaws.com`
- [ ] `usms-edge-viewer-request` exists, 128 MB, 5 s, no environment variables, version 1 published
- [ ] `usms-edge-origin-response` exists, no environment variables, version 1 published
- [ ] `usms-transcript-notifier` exists with environment variables and alias `live`
- [ ] A resource policy on `...:live` names `s3.amazonaws.com` and is scoped by source ARN
- [ ] The bucket notification is filtered to `transcripts/` and `.json`

**Evidence**

- [ ] `outputs/lab-10-viewer-allow.json` shows a normalised URI and a stamped header
- [ ] `outputs/lab-10-viewer-deny.json` is a response object with status `403`
- [ ] `outputs/lab-10-origin-response.json` shows four security headers plus `cache-control`
- [ ] `outputs/lab-10-edge-trace.json` shows a three-stage chain with `x-usms-edge-chain`
- [ ] `outputs/lab-10-function-inventory.json` contains no `NO` lines
- [ ] `outputs/lab-10-pre-restart.txt` and `-post-restart.txt` are identical

**Artefacts and hygiene**

- [ ] `configs/lab-10.env` has 25 exports and no empty values
- [ ] `scripts/utilities/verify-lab-10.sh` reports `PASS=51  FAIL=0`
- [ ] `scripts/cleanup/lab-10-cleanup.sh` exists and has **not** been run
- [ ] `git status --short` shows no `outputs/` path and no `.zip`
- [ ] The commit from Step 24 exists

**Understanding**

- [ ] `notes/lab-10-notes.md` answers all six review questions in prose
- [ ] Exercises 1 to 5 are recorded in `labs/lab-10-lambda-edge/exercises.md`
- [ ] `notes/lab-10-edge-design.md` exists (Exercise 4)

### 14.1 In-class practical assessment

75 minutes, 100 marks. Open notes, open documentation. Your own repository only.

**Task A - build (30 marks).** Create a third edge function, `usms-edge-viewer-response`, in Node.js,
which adds a single header `x-usms-served-by` whose value is the string `usms-edge`. Configure it for
the correct trigger point's caps, publish a version, and add it to
`templates/lab-10-distribution-config.json` as a third association. Marks: function exists and is
correctly configured (10), invoked successfully against a hand-built `viewer-response` event (10),
association added with a version-qualified ARN and the file still valid JSON (10).

**Task B - diagnose (25 marks).** You are given the following, and asked what is wrong and how you
would confirm it:

> A colleague's `viewer-request` function works when invoked directly but the distribution update
> fails. Their function has `--memory-size 256`, one environment variable, and is associated using
> `arn:aws:lambda:us-east-1:000000000000:function:their-fn:prod`, where `prod` is an alias pointing at
> version 4.

Name every distinct reason the update fails - there are three - and give one command per reason that
would have caught it before the update was attempted. Marks: three faults named (15), three commands
that genuinely detect them (10).

**Task C - explain (25 marks).** In no more than 300 words in
`outputs/lab-10-assessment-c.md`: why does Lambda@Edge accept only a version-qualified ARN, and why
is the alias - which is stable, named and repointable - specifically the wrong answer? Your answer
must refer to replication.

**Task D - verify (20 marks).** Run `./scripts/utilities/verify-lab-10.sh` and capture its output to
`outputs/lab-10-assessment-d.txt`. Then deliberately break exactly one configuration the script
checks, re-run it, and write one sentence naming which check caught you and one sentence saying what
a student who only checked *existence* would have concluded instead. Restore the configuration.
Marks: `FAIL=0` before and after (10), the break-and-catch narrative (10).

---

## 15. Review Questions

Answer in prose in `notes/lab-10-notes.md`. No command output - these are about reasoning, and a
transcript of a terminal is not an answer to any of them.

**1.** A colleague proposes moving the whole USMS enrolment API to Lambda@Edge, "because it will be
faster for everyone". Give the two strongest technical arguments against, and describe the one
situation in which they would be right.

**2.** Distinguish **CloudFront Functions** from **Lambda@Edge**. Cover runtime, available trigger
points, what each can and cannot do, and relative cost per invocation. Then state, for each of these
three jobs, which you would use and why: rewriting a URI to add `/index.html`; checking a JWT
signature; fetching a per-user redirect target from DynamoDB.

**3.** Step 12 put the security headers at `origin-response` rather than `viewer-response`, and said
the output would be identical either way. Explain the difference that made the choice, in terms of
when each function runs relative to the cache. Then describe a requirement that would force you to
choose `viewer-response` despite the cost.

**4.** Your function's execution role grants `s3:GetObject` on the transcripts bucket, and its
resource policy allows `s3.amazonaws.com` to invoke it. A colleague says this is redundant - "S3 is
already allowed, twice". Explain why the two policies are not the same permission, in terms of who is
making which call. Then say what breaks if you delete each one, separately.

**5.** Step 19 added `--source-arn` and `--source-account` to a permission that would have worked
without them. Explain the attack they prevent, concretely enough that someone could carry it out.
Then name the equivalent mechanism you saw in Lab 09, and say what makes the two the same idea.

**6.** Step 14 set environment variables on an edge function and the call succeeded - on Floci and on
real AWS. Yet the configuration is invalid. Explain where the validation actually happens, why AWS
does not reject it at the point of the mistake, and what that implies about how you should check
edge-function configuration. Relate your answer to the course's rule that a command appearing to
succeed is not evidence that it did what you meant.

---
## 16. What We Built

### 16.1 The reflection

Three functions, and the interesting thing about them is not that they are three - it is that they
are two different kinds.

The two edge functions have no configuration channel, a hard memory and timeout cap set by the
trigger point they are attached to, a choice of two languages, and they can only ever be referred to
by an ARN that can never move. Every
one of those is a consequence of one fact: the code is going to be copied to hundreds of places and
run there, on a request path, while somebody waits. Restrictions that look arbitrary in a list stop
looking arbitrary once you know what they are protecting.

The regional function has environment variables, more memory than it needs, thirty seconds, any
runtime, and an alias you can repoint in one call. It does not run while anybody is waiting.

If you take one thing from this lab, take the question that separates them: **does this have to
happen before the viewer can be answered?** Everything else - the trigger point, the memory, the
qualification rule - follows from the answer.

The second thing worth keeping is what Step 5 did. For five labs, `USMSStudentDataReadWrite` named a
bucket that did not exist, and every audit of it was correct and meaningless. IAM policies describe a
namespace, not an inventory. That is a useful property - you can write your access model before you
build anything - and it is a dangerous one, because "the policy is correct" and "the access model
works" are different claims, and only one of them can be checked without the resource.

And the third: Step 14, where a wrong configuration was accepted by the API that received it, and
would have been rejected minutes later by a different API about a different resource. That is the
course's founding rule in a new costume. A command that appears to succeed is not evidence that it
did what you meant - so where a property matters, check it, statically, on every run. Ten checks in
`verify-lab-10.sh` exist for no other reason.

### 16.2 KEEP versus CLEAN UP

```text
╔═══════════════════════ KEEP ═══════════════════════╗    ╔════════════ CLEAN UP ════════════╗
║ usms-student-data ... S3 lab configures it         ║    ║ nothing.                          ║
║ transcripts/evidence/* .... the S3 lab's inventory ║    ║                                   ║
║ usms-edge-viewer-request ... + version 1           ║    ║ This lab creates no temporary     ║
║ usms-edge-origin-response .. + version 1           ║    ║ resources, no credentials and no  ║
║ usms-transcript-notifier ... + version 1 + live    ║    ║ practice artefacts that conflict  ║
║ the resource policy on ...:live                    ║    ║ with anything later.              ║
║ the bucket notification configuration              ║    ║                                   ║
║ usms-lambda-exec-role's two-principal trust policy ║    ║ The environment variables added   ║
║ the CloudFront distribution, if you took Path A    ║    ║ in Step 14 were already removed   ║
║ configs/lab-10.env                                 ║    ║ in Step 14 part 2 - that is the   ║
║ usms-edge-simulate.sh, verify-lab-10.sh            ║    ║ only undo this lab needs.         ║
║ outputs/lab-10-*  (git-ignored, but keep on disk)  ║    ║                                   ║
╚════════════════════════════════════════════════════╝    ╚═══════════════════════════════════╝
```

If you did Exercise 1, you also have version 2 of the origin-response function; keep it. If you did
Exercise 2, you have `usms-edge-exec-role` and `USMSEdgeBasic`; keep those too and note them in your
exercises file, because the S3 configuration lab's IAM inventory will find them and you want to know
why they are there.

If you did the Step 18 Your-turn, check that `live` is pointing back at version 1 before you finish:

```bash
aws lambda get-alias --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text
```

### 16.3 The end-of-course cleanup script

!!! danger "DO NOT RUN THIS NOW"
    **What will be deleted:** all three Lambda functions and every version and alias of them, the
    resource policy, the bucket notification configuration, the CloudFront distribution, and every
    object in `usms-student-data` followed by the bucket itself.

    **What depends on it:** the S3 configuration lab and every lab after it. `usms-student-data` is
    referenced by four IAM policies and by three roles.

    **Reversible?** No. Deleted objects are gone; deleted function versions are gone. You would rerun
    this entire lab, and the S3 configuration lab, from the beginning.

    **Effect on later labs:** total. This script exists for the end of the course, when you are
    dismantling the environment deliberately.

Write it now and do not run it:

```bash
cat > scripts/cleanup/lab-10-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END-OF-COURSE CLEANUP for Lab 10. Deletes dependencies inside-out.
# DO NOT RUN while any later lab still needs usms-student-data.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/lab-10.env" 2>/dev/null || true

BUCKET="${USMS_BUCKET_NAME:-usms-student-data}"

cat << 'WARN'
This will permanently delete:
  - usms-edge-viewer-request, usms-edge-origin-response (all versions)
  - usms-transcript-notifier (all versions, alias live, resource policy)
  - the notification configuration on the transcripts bucket
  - the usms-transcript-cdn CloudFront distribution, if one exists
  - EVERY OBJECT in the transcripts bucket, and the bucket itself

The S3 configuration lab and everything after it depend on that bucket.
WARN

printf 'Type exactly: DELETE USMS EDGE FUNCTIONS\n> '
read -r CONFIRM
[ "$CONFIRM" = "DELETE USMS EDGE FUNCTIONS" ] || { echo "aborted"; exit 1; }

echo "1/6 removing the bucket notification (stops new invocations first)"
aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" --notification-configuration '{}' 2>/dev/null || true

echo "2/6 disabling and deleting the CloudFront distribution, if present"
DIST_ID="${USMS_CLOUDFRONT_DIST_ID:-not-created}"
if [ "$DIST_ID" != "not-created" ]; then
  echo "    a distribution must be disabled and fully deployed before it can be deleted;"
  echo "    on real AWS that wait is roughly 15 minutes. Doing what we can:"
  ETAG=$(aws cloudfront get-distribution-config --id "$DIST_ID" --query 'ETag' --output text 2>/dev/null || echo "")
  [ -n "$ETAG" ] && aws cloudfront delete-distribution --id "$DIST_ID" --if-match "$ETAG" 2>/dev/null || true
fi

echo "3/6 removing the resource policy statement"
aws lambda remove-permission --function-name usms-transcript-notifier \
  --qualifier live --statement-id usms-s3-transcript-upload 2>/dev/null || true

echo "4/6 deleting the alias, then the functions"
aws lambda delete-alias --function-name usms-transcript-notifier --name live 2>/dev/null || true
for fn in usms-edge-viewer-request usms-edge-origin-response usms-transcript-notifier; do
  aws lambda delete-function --function-name "$fn" 2>/dev/null \
    && echo "    deleted $fn (and all its versions)" \
    || echo "    $fn already absent"
done

echo "5/6 emptying the bucket"
aws s3 rm "s3://$BUCKET" --recursive 2>/dev/null || true

echo "6/6 deleting the bucket"
aws s3api delete-bucket --bucket "$BUCKET" 2>/dev/null \
  && echo "    deleted $BUCKET" \
  || echo "    $BUCKET not empty or already absent"

echo
echo "Note: usms-lambda-exec-role and its two-principal trust policy are NOT deleted."
echo "They belong to Lab 01 and lab-01-cleanup.sh owns them."
EOF

chmod +x scripts/cleanup/lab-10-cleanup.sh
bash -n scripts/cleanup/lab-10-cleanup.sh && echo "syntax OK - and do not run it"
```

Three things about the order, because the order is the lesson:

**The notification goes first.** Deleting a function that an active notification points at leaves S3
trying to invoke something that is not there. Stop the traffic, then remove the target.

**`delete-function` without `--qualifier` deletes every version.** With `--qualifier 1` it deletes
only that version. The unqualified form is what you want at the end of a course and is emphatically
not what you want when you meant to remove one bad release.

**A bucket must be empty before it can be deleted.** `aws s3 rm --recursive` is one of the few places
this course prefers `aws s3` to `aws s3api`, because the `s3api` equivalent is a paginated
`delete-objects` loop and this is exactly the file-moving job the high-level commands exist for.

### 16.4 The architecture, now

```text
  IAM (Lab 01)                         NETWORK (Lab 02)
   ├── usms-lambda-exec-role ──────────┐   ├── usms-vpc
   │     trust: lambda + edgelambda    │   ├── 4 subnets
   │     policy: USMSLambdaBasic       │   └── usms-s3-endpoint ──┐
   └── USMSStudentDataReadWrite ───┐   │                          │
         on 3 roles                │   │                          │
                                   v   v                          v
  EDGE (Lab 10)                 +---------------------------------------+
   ├── usms-edge-viewer-request  |          usms-student-data           |
   │    :1  viewer-request ------|  transcripts/evidence/*.json          |
   ├── usms-edge-origin-response |                                       |
   │    :1  origin-response -----|  notification: ObjectCreated          |
   └── usms-transcript-cdn ------+------------------+--------------------+
        associations: 2                             |
                                                    v
  REGIONAL (Lab 10)                    usms-transcript-notifier:live
   └── usms-transcript-notifier -----------→ /aws/lambda/usms-transcript-notifier

  COMPUTE (Labs 03, 04-C, 07-B)   ← unchanged by this lab, still running
   ├── usms-web-01, usms-db-01
   ├── usms-ecs-cluster / usms-enrolment-svc / usms-enrolment-alb
   └── usms-eks-cluster / usms-enrolment-hpa          (Labs 07-08)
```

---

## 17. Preparation for the Next Lab

The next lab to be written is the **S3 configuration lab** - the one this course has been anticipating
since Lab 01, and which does not yet have a number or a file of its own in the current sequence. It
will no longer open with a bucket that does not exist; it will open with one that does, holding real
objects, wired to a real trigger, and still missing every piece of configuration that makes a bucket
production-ready.

### What the S3 configuration lab will consume

| Artefact | From | How it will be used |
| --- | --- | --- |
| `usms-student-data` | Step 5 | Configures it properly: versioning, default encryption, public-access block, lifecycle rules |
| `outputs/lab-09-bucket-policy-draft.json` | Lab 09 Ex 5, validated in this lab's Exercise 5 | **Applies** it as the bucket's resource policy - the step this lab deliberately did not take |
| `USMS_BUCKET_ARN` | `configs/lab-10.env` | The resource half of every policy statement it writes |
| `USMS_NOTIFICATION_PREFIX`, `USMS_NOTIFICATION_SUFFIX` | `configs/lab-10.env` | The existing notification must be preserved: `put-bucket-notification-configuration` replaces the whole document, so it has to get-merge-put |
| `USMS_LAMBDA_NOTIFIER_ALIAS_ARN` | `configs/lab-10.env` | The target it must not break while adding an SNS destination |
| `outputs/lab-10-s3-readiness.txt` | Exercise 5 | Read at the start as the inventory of what it inherited |
| `transcripts/evidence/*` | Step 20, Exercise 5 | The objects it enables versioning on, and then modifies to show version history |
| `usms-s3-endpoint` | Lab 02 | Finally explained in full: why a private-subnet caller reaches this bucket without a NAT hop |

### The thing the S3 configuration lab must be careful about

`put-bucket-notification-configuration` **replaces** the bucket's entire notification document. It
will add an SNS destination, and if it sends a document containing only the SNS configuration, the
Lambda notification you built in Step 20 disappears - silently, with a successful API call. The
sequence has to be get, merge, put.

That is worth flagging now rather than discovering later, and it is the same shape as the trust-policy
replacement in this lab's Step 6. Replace-only APIs are a category, and the category is worth
recognising: `update-assume-role-policy`, `put-bucket-notification-configuration`,
`put-bucket-policy`, `put-bucket-tagging`. Every one of them will happily delete something you did not
mention.

### Pre-session checks

Run these before the next session. All four should pass.

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-10.sh            # PASS=51  FAIL=0
grep -c '^export' configs/lab-10.env            # 25
aws s3api head-bucket --bucket usms-student-data && echo "bucket present"
aws s3api get-bucket-policy --bucket usms-student-data 2>/dev/null \
  || echo "no bucket policy yet - correct, the S3 configuration lab applies it"
```

### Snapshot before you finish

```bash
floci snapshot save lab-10-complete
floci snapshot list
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-10.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

### Read ahead

Three things, each of which the S3 configuration lab assumes you have thought about for five minutes:

- **S3 versioning is a bucket-level switch that cannot be turned off**, only suspended. Consider what
  that means for a bucket that already has objects in it.
- **A bucket policy and an identity policy can both grant access to the same object.** You have now
  seen this pattern twice - at the function in Step 19, and here. Think about which one you would use
  to grant access to a principal in another account, and why the answer is not symmetric.
- **`aws s3` versus `aws s3api`.** Step 5 and Section 16.3 each chose one deliberately. Look at both
  choices and work out the rule they follow.

---

## Appendix A - Command Reference

Everything this lab used, in the order you met it.

| Command | What it does here |
| --- | --- |
| `aws s3api head-bucket --bucket B` | Existence probe. Non-zero exit means absent |
| `aws s3api create-bucket --bucket B` | Creates it. No `LocationConstraint` in `us-east-1` |
| `aws s3api put-bucket-tagging --bucket B --tagging TagSet=[...]` | Tags the bucket |
| `aws s3api put-object --bucket B --key K --body FILE` | Uploads one object |
| `aws s3api list-objects-v2 --bucket B --prefix P` | Lists objects under a prefix |
| `aws s3api put-bucket-notification-configuration --bucket B --notification-configuration file://F` | Sets the event configuration. **Replaces** the whole document |
| `aws s3api get-bucket-notification-configuration --bucket B` | Reads it back |
| `aws iam update-assume-role-policy --role-name R --policy-document file://F` | Replaces a trust policy |
| `aws iam get-role --role-name R` | Reads the role, including the trust document |
| `aws lambda create-function --function-name F --runtime R --role A --handler H --zip-file fileb://Z` | Creates a function |
| `aws lambda update-function-code --function-name F --zip-file fileb://Z` | Replaces the code on `$LATEST` |
| `aws lambda update-function-configuration --function-name F --environment Variables={...}` | Changes configuration. `Variables={}` clears |
| `aws lambda get-function-configuration --function-name F [--qualifier Q]` | Reads one function, optionally one version or alias |
| `aws lambda list-functions` | All functions in the account |
| `aws lambda invoke --function-name F --payload fileb://E OUTFILE` | Synchronous invocation. `OUTFILE` is positional and required |
| `aws lambda invoke ... --log-type Tail --query LogResult` | Returns the last 4 KB of logs, base64 |
| `aws lambda publish-version --function-name F` | Freezes `$LATEST` as a numbered version |
| `aws lambda list-versions-by-function --function-name F` | All versions including `$LATEST` |
| `aws lambda create-alias --function-name F --name N --function-version V` | Creates a movable pointer |
| `aws lambda update-alias --function-name F --name N --function-version V` | Repoints it |
| `aws lambda get-alias` / `list-aliases` | Reads aliases |
| `aws lambda add-permission --function-name F --qualifier Q --principal P --source-arn A` | Resource policy statement: who may invoke |
| `aws lambda remove-permission --function-name F --qualifier Q --statement-id S` | Removes one statement |
| `aws lambda get-policy --function-name F --qualifier Q` | Reads the resource policy. Returns JSON **as a string** |
| `aws lambda wait function-active-v2 --function-name F` | Blocks until the function is ready |
| `aws lambda delete-function --function-name F [--qualifier V]` | Without a qualifier, deletes every version |
| `aws cloudfront create-distribution --distribution-config file://F` | Creates a distribution |
| `aws cloudfront get-distribution --id D` | Reads it, including the associations |
| `aws cloudfront list-distributions` | All distributions; also this lab's support probe |
| `aws logs describe-log-groups --log-group-name-prefix P` | Finds a function's log group |
| `aws logs filter-log-events --log-group-name G --filter-pattern T` | Searches across every stream in a group |
| `python3 -m zipfile -c A.zip FILE` | Builds a deployment archive without needing `zip` |
| `python3 -m zipfile -l A.zip` | Lists what is inside one - check this before blaming your handler |
| `python3 -m json.tool F` | Validates and pretty-prints JSON |
| `python3 -m py_compile F.py` | Syntax-checks Python without running it |
| `node --check F.mjs` | Syntax-checks JavaScript without running it |
| `openssl base64 -d -A` | Portable base64 decode. GNU uses `-d`, BSD uses `-D`; this works on both |

---

## Appendix B - New JMESPath and CLI Patterns Introduced

Everything here is new to the course at Lab 10. Patterns from Labs 1 to 5 are assumed and are not
repeated.

**Parameter prefixes**

| Pattern | Meaning |
| --- | --- |
| `fileb://path` | Read the file as **binary**. Required for `--zip-file` and for `--payload`. `file://` reads as text and corrupts a ZIP |
| `--payload file://e.json --cli-binary-format raw-in-base64-out` | The alternative to `fileb://`: tells the CLI v2 to treat text input as raw rather than base64 |

**Qualification**

| Pattern | Meaning |
| --- | --- |
| `--qualifier 1` | Act on version 1 |
| `--qualifier live` | Act on the alias `live` |
| `<function-arn>:1` | A version-qualified ARN, built by concatenation |
| `<function-arn>:live` | An alias-qualified ARN - also qualified, but **movable**, which is why the edge refuses it |

**Shorthand argument syntax**

| Pattern | Meaning |
| --- | --- |
| `--environment "Variables={K=V,K2=V2}"` | Map shorthand. Double-quoted when a value must be expanded |
| `--environment 'Variables={}'` | The only way to clear environment variables; there is no `--no-environment` |
| `--tags Project=USMS,Tier=edge` | Lambda's `--tags` is a **map**, unlike EC2's `--tag-specifications` list-of-structures |
| `--tagging 'TagSet=[{Key=K,Value=V}]'` | S3's tagging shorthand - a third, different shape for the same idea |

**JMESPath**

| Pattern | Meaning |
| --- | --- |
| `max_by(Versions[?...], &to_number(Version))` | Sort by a **numeric** interpretation of a string field. Without `to_number`, version 10 sorts before version 9 |
| `sort_by(Functions[?starts_with(FunctionName, ...)], &FunctionName)` | Filter then sort, in one expression |
| `length(Versions)` | Count without fetching the list into the shell |
| `Statement[].Principal.Service` | Project a field out of every statement in a policy document |
| `--query 'Policy' --output text \| python3 -m json.tool` | For fields that contain JSON **as a string** - `get-policy` is one |
| `[?contains(Comment, 'x')].Id \| [0]` | First match, or `None` |
| `... --output text \| grep -E '...' \|\| echo not-created` | Turn a `None` into an honest sentinel before it reaches a config file |

**Shell**

| Pattern | Meaning |
| --- | --- |
| `( cd DIR && command )` | Scoped directory change. The parenthesis restores your directory even when the command fails |
| `<< 'EOF'` versus `<< EOF` | Quoted prevents expansion - required for anything containing `${...}` or backticks that must survive. Unquoted expands at write time - required for `configs/lab-NN.env` and for injecting ARNs |
| `\$LATEST` inside an unquoted heredoc or a double-quoted `--query` | Escaped so the shell leaves the dollar for JMESPath |
| `for c in a b c; do [ -f "$c" ] && { X="$c"; break; }; done` | First-existing-file selection, for picking whichever of several qualifying artefacts is present |
| `cmd 2>/dev/null \|\| true` under `set -u` | Source a file that may not exist yet without aborting the script |
| `{ cmd1; cmd2; } \| tee FILE` | Capture a group of commands in one file |
| `python3 - "$ARG" << 'PY'` | Pass a shell value into an inline Python program as `sys.argv[1]` without interpolating it into the source |

**Concepts with no command**

| Idea | Where it appeared |
| --- | --- |
| CloudFront event structure: `Records[0].cf.{config,request,response}` | Step 7 |
| Header shape: lowercase key, array of `{key, value}` | Step 7 |
| Return a request to continue, a response to stop | Steps 7 and 16 |
| Trigger points and their caps | Steps 8, 12, 14 |
| Execution role versus resource policy | Step 19 |
| Confused deputy, and `--source-arn` as its answer | Step 19 |
| Replace-only APIs | Steps 6, 20, and Section 17 |

---

## Sources

- [Lambda@Edge - Amazon CloudFront Developer Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/lambda-at-the-edge.html)
- [Restrictions on edge functions - Amazon CloudFront Developer Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-functions-restrictions.html)
- [Lambda@Edge event structure - Amazon CloudFront Developer Guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/lambda-event-structure.html)
- [Customize at the edge with CloudFront Functions](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cloudfront-functions.html)
- [Choosing between CloudFront Functions and Lambda@Edge](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-functions.html)
- [Lambda function versions - AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/configuration-versions.html)
- [Lambda function aliases - AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/configuration-aliases.html)
- [Resource-based policies for Lambda - AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/access-control-resource-based.html)
- [Using Lambda with Amazon S3 - AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/with-s3.html)
- [Configuring event notifications - Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/NotificationHowTo.html)
- [CreateBucket - Amazon S3 API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateBucket.html)
- [The confused deputy problem - AWS IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
- [Loading parameters from a file - AWS CLI User Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-parameters-file.html)
- [`aws lambda invoke` - AWS CLI Command Reference](https://docs.aws.amazon.com/cli/latest/reference/lambda/invoke.html)
- Course documents: Lab 01 (IAM), Lab 02 Section 17 (the S3 gateway endpoint), Lab 03 Section 17
  (the `head-bucket` probe that was expected to fail), Lab 06 Section 17, Lab 09 Step 4 and its
  identity-versus-resource-policy distinction, Lab 08 Section 17, Errata 01.

---

*Lab 10 complete. The bucket exists, the edge functions compose, and the next lab finally gets to
configure the thing every policy in this course has been pointing at.*

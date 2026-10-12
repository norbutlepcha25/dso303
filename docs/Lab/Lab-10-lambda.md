# Lab 10 - Edge Functions with AWS Lambda

## 1. Objectives

- Create `usms-student-data`, the bucket Lab 1's `USMSStudentDataReadWrite` has named since the first day, as the CloudFront origin.
- Build two Lambda@Edge functions (viewer-request and origin-response), invoke them with real CloudFront events, publish versions, and check them against the edge restrictions.
- Associate both with a CloudFront distribution (or validate the configuration) and prove they compose with `usms-edge-simulate.sh`.
- Build a regional S3-triggered notifier with an alias and a scoped resource policy, and prove it ran.
- Prove everything survives a restart and save the identifiers to `configs/lab-10.env`.

**Time:** roughly four hours. **Assessment:** Section 13.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [edge locations and CloudFront](../unit1/topic1.md#edge-locations-and-amazon-cloudfront) ·
    [AWS Lambda](../unit1/topic3.md#aws-lambda) ·
    [limits that decide whether Lambda fits](../unit1/topic3.md#limits-that-decide-whether-lambda-fits) ·
    [S3 buckets, objects and keys](../unit6/topic1.md#buckets-objects-keys-and-prefixes) ·
    [S3 event sources](../unit6/topic1.md#event-sources) ·
    [consuming S3 from Lambda](../unit6/topic1.md#consuming-s3-from-aws-lambda) ·
    [S3 event notifications](../unit6/topic3.md#amazon-s3-event-notifications) ·
    [IAM roles](../unit8/topic1.md#iam-roles) ·
    [identity-based versus resource-based policies](../unit8/topic1.md#identity-based-versus-resource-based-policies) ·
    [the confused deputy problem](../unit8/topic1.md#the-confused-deputy-problem) ·
    [Lambda@Edge restrictions (AWS docs)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-functions-restrictions.html)

---

## 2. Prerequisites

- Labs 1 to 9 complete, with their `configs/lab-NN.env` files present (Step 2 checks this).
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`.
- A **new** terminal window already has `AWS_PROFILE` and `COURSE_ROOT` set. If not, fix the defect described in Errata 01 now.
- `python3` on your path (JSON validation and building `.zip` archives).
- About 1 GB of free disk; Floci starts one container per Lambda runtime.

```bash
cd ~/aws-floci-course
./scripts/utilities/floci-storage-check.sh
```

You want `PASS=16  FAIL=0`. A failure in the first block means a new terminal cannot find the course, and the AWS CLI will then blame your credentials, which are fine.

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 will suggest `aws login`. That begins a sign-in to
    **real AWS**. The answer in this course is always `source configs/course.env` or a missing
    `floci` profile - never a sign-in. See Errata 01 Section 3.

---

## 3. What This Lab Reuses

From Lab 1:

- `usms-lambda-exec-role`: the execution role on all three functions; Step 6 adds the edge principal to its trust policy.
- `USMSLambdaBasic`: read back in Step 6; the notifier stays inside it (logs and `s3:GetObject`).
- `USMSStudentDataReadWrite` and `USMS_BUCKET_NAME`: Step 5 creates the bucket the policy has always named.

From later labs:

- Lab 02 `usms-s3-endpoint`: why a private-subnet caller reaches the new bucket without a NAT hop (Step 5).
- Lab 06 `outputs/lab-06-scaling-history.json` and Lab 08 `outputs/lab-08-scaling-evidence.json`: candidate first objects uploaded in Step 20.
- Lab 09 `outputs/lab-09-bucket-policy-draft.json`: validated in Exercise 5 against the now-real bucket. Lab 09's identity-versus-resource-policy distinction returns in Step 19.

The planned S3 configuration lab was never written, so this lab creates the bucket **plainly** (one tag, objects, a notification) and leaves versioning, encryption, lifecycle and the bucket policy for that lab.

```text
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

---

## 4. What We Are Building

A student requests `/transcripts/2026/stu-00417.json`. At the CloudFront edge, `usms-edge-viewer-request` runs before the cache: it lowercases the URI (one cache entry per object) and returns a `403` itself if the authentication header is missing, so the origin is never contacted. On a cache miss CloudFront fetches from `usms-student-data`, and `usms-edge-origin-response` adds the security headers a bucket does not provide. Separately, every upload under `transcripts/` triggers the regional `usms-transcript-notifier`.

Edge functions are for the request path; regional functions are for what happens afterwards. This lab builds Lambda@Edge and explains the lighter CloudFront Functions runtime, because choosing between them is the real decision.

---

## 5. Architecture

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

## 6. Directory Structure

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
│   │   └── verify-lab-10.sh          # Section 8
│   └── cleanup/
│       └── lab-10-cleanup.sh         # Section 8.2 - DO NOT RUN NOW
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

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Every ARN and version is captured with `$(...)`. Step 23 writes them to `configs/lab-10.env`; until then, a new terminal loses them.

### Step 1 - Start the environment and prove a new terminal can find it

Everything below assumes Floci is running with persistent storage and your shell knows where the course is.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/floci-storage-check.sh
```

`floci-up.sh` is idempotent and refuses to adopt a container not started by Compose. `floci-storage-check.sh` is read-only: its first block checks that a new terminal can find the course, its second that today's work will survive.

**Expected result**

```text
PASS=16  FAIL=0
```

> Example output - the lines above the total name your own paths and login shell.

Any failure in the first block is the real problem. Fix the shell integration first (Errata 01 Patch 1).

---

### Step 2 - Source every lab environment file that exists, and confirm your identity

This lab needs `USMS_BUCKET_NAME` and `USMS_ROLE_LAMBDA` from Lab 1 and reuses artefacts from Labs 06 to 09. Checking each file before sourcing it turns a missing file into a named line of output.

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

The files are named, not globbed, so nothing stray is sourced and the output reports exactly what was loaded. `whoami.sh` exits `1` unless the account is `000000000000`.

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

You want `usms-student-data`, `usms-lambda-exec-role` and `000000000000`. If `USMS_BUCKET_NAME` is unset, run `export USMS_BUCKET_NAME=usms-student-data` and add that line to `configs/lab-01.env`; Step 5 and the verification read it.

---

### Step 3 - Create this lab's directories

One directory per function, because each deployment archive is built from its own directory.

```bash
mkdir -p labs/lab-10-lambda-edge/edge-viewer-request \
         labs/lab-10-lambda-edge/edge-origin-response \
         labs/lab-10-lambda-edge/transcript-notifier

ls -d labs/lab-10-lambda-edge/*/
```

`mkdir -p` creates parents and is safe to re-run.

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

Lambda and S3 are well emulated. CloudFront varies most between builds, and no emulator executes Lambda@Edge. Record what your build supports before depending on it.

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

`probe` runs a harmless read-only call and reports only whether it returned zero. `{ ...; } | tee file` captures the whole group into `outputs/`. `list-layers` is probed separately because some builds implement functions but not layers.

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

The first four lines must say `SUPPORTED`. If `lambda (list-functions)` is `UNSUPPORTED`, stop and read Section 10; Floci is usually still starting.

The CloudFront line decides which path Step 15 takes:

| CloudFront probe | Step 15 |
| --- | --- |
| `SUPPORTED` | Path A - create the distribution and read the associations back from the API |
| `UNSUPPORTED` | Path B - validate the distribution config structurally and record it for real AWS |

Either way, Step 16 proves your two functions compose.

---

### Step 5 - Create the origin bucket, and watch a policy stop being hypothetical

`usms-student-data` is the CloudFront origin and the bucket whose uploads trigger the notifier. An IAM policy names resources by ARN and does not require them to exist, so `USMSStudentDataReadWrite` has been attached and audited for several labs while granting access to nothing. It was never wrong; it was waiting.

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

- `aws s3api` maps one-to-one onto the S3 API; `aws s3` is a small set of file-transfer verbs. This course uses `s3api` for structural work.
- No `--create-bucket-configuration` in `us-east-1`: it is the one region where you must **omit** `LocationConstraint` (real AWS rejects it; Floci is lenient).
- Bucket names are **globally** unique across all accounts. `usms-student-data` works in Floci but is almost certainly taken on real AWS.
- `head-bucket ... && ... || ...` makes the step idempotent.

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

`head-bucket` exits `0` for the first time in this course, the tag table shows three rows, and the last command prints the ARNs the policy has always named:

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

They match the bucket you just created. From this step on, every role carrying that policy (`usms-ec2-app-role`, `usms-ecs-task-role`, `usms-eks-node-role`) has real permissions on a real resource.

!!! note "Floci Limitation - the permission is still not enforced"
    Floci does not evaluate IAM policies, so even a caller with no permissions can read the bucket here.

    Real AWS evaluates every request against identity policies, resource policies, boundaries and session policies, and denies by default.

    Judge your policies by reading them. What changed in this step (the ARN now resolves) changed in IAM's data, not in Floci's enforcement.

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

Lab 1 created `usms-lambda-exec-role` and nothing has used it since. Its trust policy names only `lambda.amazonaws.com`, but CloudFront replicates Lambda@Edge functions to edge locations using a second principal:

| Principal | Why it needs to assume the role |
| --- | --- |
| `lambda.amazonaws.com` | The ordinary Lambda service, when it runs the function |
| `edgelambda.amazonaws.com` | CloudFront's replication and edge invocation path |

Omitting `edgelambda.amazonaws.com` is the most common Lambda@Edge setup error on real AWS.

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

One principal and one policy. `USMSLambdaBasic` grants CloudWatch Logs writes and `s3:GetObject`; that is the whole budget for your three functions.

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

**Quoted heredoc** (`<< 'EOF'`): this is a policy document and nothing should be expanded. Getting it backwards is silent. Step 23 deliberately uses the unquoted form because it wants `$(...)` to run.

**Command - part 3, replace the trust policy**

```bash
aws iam update-assume-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-document file://policies/trust-lambda-edge.json

EDGE_ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
  --query 'Role.Arn' --output text)

echo "$EDGE_ROLE_ARN"
```

`update-assume-role-policy` **replaces** the whole trust policy; there is no add-principal call. That is why part 2 lists both principals: naming only `edgelambda` would remove `lambda` and break the role.

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

You want `2`, then `edgelambda.amazonaws.com`. If the first prints `1`, the update did not apply; if it prints nothing, read the document with `--query 'Role.AssumeRolePolicyDocument' --output json` and check by eye.

!!! note "Floci Limitation - trust policies are stored, not evaluated"
    Floci returns the document faithfully but does not evaluate it; a function with an empty trust policy still runs here.

    Real AWS refuses `create-function` if `lambda.amazonaws.com` cannot assume the role, and refuses the CloudFront association if `edgelambda.amazonaws.com` is missing.

    The two-principal requirement is a fact about Lambda@Edge, checkable by reading, as the verify above did.

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

This function runs on every request before the cache. It decides who gets a transcript and normalises the URI. The CloudFront event has one record:

```text
event
 └── Records[0]
      └── cf
           ├── config    ← distributionId, eventType, requestId
           ├── request   ← always present, at all four trigger points
           └── response  ← present ONLY at origin-response and viewer-response
```

What you may return depends on the trigger point:

| Return value | Meaning | Legal at |
| --- | --- | --- |
| the `request` object | continue, using this (possibly modified) request | viewer-request, origin-request |
| a `response` object | stop here, send this to the viewer | viewer-request, origin-request |
| the `response` object | continue, with this (possibly modified) response | origin-response, viewer-response |

Headers are **not** a map of strings. Each lowercase key holds an **array** of `{key, value}` objects (HTTP allows repeated headers):

```text
"headers": {
  "host":            [ { "key": "Host",            "value": "usms.example.edu" } ],
  "x-usms-student":  [ { "key": "X-USMS-Student",  "value": "stu-00417" } ]
}
```

So `headers['x-usms-student'].value` is `undefined`; you want `headers['x-usms-student'][0].value`.

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

- **Quoted heredoc, and load-bearing:** the handler contains `${studentId.toLowerCase()}` inside a template literal. An unquoted heredoc would expand it to nothing, producing code that deploys and runs but stamps every request with an empty student id.
- `.mjs` makes Node treat the file as an ES module, so `export const handler` is valid; the handler string is `index.handler`.
- `node --check` parses without running. Without local Node, Step 9's first invoke catches syntax errors.

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

Around 50 lines, `studentId` three times, and the third command must print `${studentId.toLowerCase()}` with the dollar sign and braces **intact**. If it prints nothing, delete the file and rerun with `<< 'EOF'`.

---

### Step 8 - Package the function and create it

A Lambda function is code (a ZIP archive) plus configuration (flags). Lambda's defaults are 128 MB and 3 seconds, but Lambda@Edge **limits** depend on the trigger point:

| Trigger point | Max memory | Max timeout | Max response body |
| --- | --- | --- | --- |
| `viewer-request`, `viewer-response` | 128 MB | 5 seconds | 40 KB |
| `origin-request`, `origin-response` | 10,240 MB | 30 seconds | 1 MB |

A viewer-trigger function with 256 MB is not slow; it is **rejected** at association time. Choose memory and timeout for the trigger point.

**Command - part 1, build the archive**

```bash
( cd labs/lab-10-lambda-edge/edge-viewer-request \
  && python3 -m zipfile -c "$COURSE_ROOT/outputs/usms-edge-viewer-request.zip" index.mjs )

python3 -m zipfile -l outputs/usms-edge-viewer-request.zip
```

The subshell `( cd ... && ... )` matters: the archive stores the path you pass, so zipping from the repository root would bury `index.mjs` under `labs/...` and Lambda would report `Cannot find module`. The subshell also returns you to where you were even if the command fails. If you have `zip`, this is equivalent (`-j` drops paths):

```bash
( cd labs/lab-10-lambda-edge/edge-viewer-request \
  && zip -j "$COURSE_ROOT/outputs/usms-edge-viewer-request.zip" index.mjs )
```

**Expected result**

```text
File Name                                             Modified             Size
index.mjs                                      2026-09-16 10:22:14         1893
```

> Example output - your size and timestamp will differ.

One entry, named exactly `index.mjs`, with no directory prefix.

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

- `--zip-file fileb://`: `fileb://` reads **binary**; `file://` reads text and corrupts a ZIP.
- `--runtime nodejs20.x`: Lambda@Edge supports only Node.js and Python, no containers or custom runtimes.
- `--handler index.handler`: `<file without extension>.<exported name>`.
- `--memory-size 128 --timeout 5`: the viewer-trigger caps. Memory also sets the CPU share.

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

You want:

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

`State` should be `Active` (`Pending` means the runtime image is still downloading; wait ten seconds). `Version` is `$LATEST`, the mutable pointer the edge will refuse (Step 11).

---

### Step 9 - Invoke the function with a real CloudFront event

Build the event CloudFront would deliver, send it, and read the result.

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

The URI is deliberately upper case (the handler should lowercase it), the auth header is present (allow path), and `203.0.113.178` is from a range reserved for documentation (RFC 5737).

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

- The final **positional argument** is the file that receives the function's return value; stdout carries only invocation metadata.
- `--payload fileb://` supplies bytes, as Step 8 did. (`file://` plus `--cli-binary-format raw-in-base64-out` also works.)
- `StatusCode` `200` means Lambda ran your function, not that it succeeded; `FunctionError` reads `Unhandled` if your code threw.

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

Check, in order: `Error` is `None`; `uri` is **lower case**; and a new `x-usms-edge` header ends with `student=stu-00417`. If it ends `student=` with nothing after it, the Step 7 heredoc was unquoted.

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

Every function writes to the CloudWatch Logs group `/aws/lambda/<function-name>` (the durable record). `--log-type Tail` instead returns the **last 4 KB** of one synchronous invocation's log, base64-encoded in `LogResult`, immediately, which is better for interactive debugging.

```bash
aws lambda invoke \
  --function-name "$VIEWER_FN" \
  --payload fileb://templates/lab-10-viewer-request-event.json \
  --log-type Tail \
  --query 'LogResult' --output text \
  outputs/lab-10-viewer-allow.json \
  | openssl base64 -d -A
```

`openssl base64 -d -A` decodes identically on macOS and Linux (`base64` uses `-D` on BSD and `-d` on GNU); `-A` accepts the single-line blob Lambda sends.

**Expected result**

```text
START RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa Version: $LATEST
END RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa
REPORT RequestId: 4c8e2b51-0a7f-4e1c-9d33-6d2a0f4b17aa	Duration: 18.42 ms	Billed Duration: 19 ms	Memory Size: 128 MB	Max Memory Used: 67 MB
```

> Example output - your request id, durations and memory figures will differ.

You want `START`, `END` and `REPORT` with matching request ids, and no application output (this handler never logs). In `REPORT`, compare `Max Memory Used` with `Memory Size`; 128 MB is the viewer-trigger ceiling anyway.

**Verify - the durable route**

```bash
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/lambda/$VIEWER_FN" \
  --query 'logGroups[].[logGroupName,storedBytes]' --output table
```

**What to look for:** one row, named `/aws/lambda/usms-edge-viewer-request`.

!!! note "Floci Limitation - log delivery is build-dependent"
    Some builds return an empty `LogResult`, or create the log group without streams. Step 9 already proved the function ran.

    Real AWS always attaches `LogResult` to a synchronous `--log-type Tail` invoke and always creates the group and stream.

    If logs are unavailable, note it in `outputs/lab-10-support-probe.txt` and use returned payloads as evidence. Section 10 has the fallback for Step 21, which depends on logs.

---

### Step 11 - Publish a version, and find out why the edge insists on one

`$LATEST` is mutable. CloudFront accepts only an immutable version:

| How you refer to it | What it points at | Accepted by Lambda@Edge? |
| --- | --- | --- |
| `...:function:usms-edge-viewer-request` | `$LATEST`, whatever that currently is | No |
| `...:function:usms-edge-viewer-request:live` | an alias - a movable label | No |
| `...:function:usms-edge-viewer-request:1` | version 1 - immutable, forever | Yes |

A published version freezes code **and** configuration forever. CloudFront replicates the function to hundreds of edge locations over minutes, non-transactionally; if the ARN could move during that, different locations would run different code. An alias is refused for the same reason: it is designed to be repointed.

```bash
VIEWER_VERSION=$(aws lambda publish-version \
  --function-name "$VIEWER_FN" \
  --description "Lab 10 - initial edge release" \
  --query 'Version' --output text)

VIEWER_VERSION_ARN="${VIEWER_FN_ARN}:${VIEWER_VERSION}"

printf 'version      : %s\n' "$VIEWER_VERSION"
printf 'qualified ARN: %s\n' "$VIEWER_VERSION_ARN"
```

`publish-version` snapshots `$LATEST` and returns the next sequential number. The qualified ARN is the unqualified ARN plus `:<version>`.

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

You want two rows (`$LATEST` and `1`) and the version-qualified message. The `grep -qE ':[0-9]+$'` check replaces an enforcement Floci does not perform, and goes into the Section 8 verification script.

!!! note "Floci Limitation - nothing here refuses an unqualified ARN"
    Floci records a CloudFront association pointing at `$LATEST` or an alias without complaint.

    Real AWS rejects the `create-distribution` or `update-distribution` call with `InvalidLambdaFunctionAssociation`.

    You cannot learn this rule here by making the mistake, so check it, as the `grep` above does.

**Checkpoint 4**

```text
usms-edge-viewer-request
 ├── $LATEST ................. mutable, what you edit
 └── 1 ....................... immutable, what the edge can use
      └── arn:...:function:usms-edge-viewer-request:1     ← VIEWER_VERSION_ARN
```

---

### Step 12 - Write and deploy the origin-response function

A file served from a bucket has no `Strict-Transport-Security`, `X-Content-Type-Options` or cache policy of your own. Add them at `origin-response`, which fires after the origin replies and **before** caching, so the headers are stored with the object and the function runs once per cache miss. At `viewer-response` it would run on every request, cache hits included, for the same output.

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

- Quoted heredoc again: section 3 contains `${upstream[0].value}`.
- The `SECURITY_HEADERS` object makes adding a header a one-line data change (Exercise 1).
- Headers are overwritten deliberately, so an uploader cannot set the frame policy for the whole distribution.

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

Same shape as Step 8. It keeps 128 MB and 5 seconds although origin triggers allow 10,240 MB and 30 seconds: size to the work, not to the allowance.

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

You want `State` `Active`, handler `index.handler`, memory `128`.

---

### Step 13 - Invoke the origin-response function and publish its version

Invoke the second function with an event of its own shape, confirm the result, then freeze it as a version.

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

- There is a `response` object: at `origin-response` the origin has already answered.
- The `request` carries `x-usms-edge`, stamped by the viewer-request function. Edge functions communicate through the request itself.
- The ETag value contains escaped quotes (`\"...\"`) because HTTP ETags are quoted; `json.tool` catches mistakes.

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

The assertion line prints, and the chain header reads `viewer-request-allow;student=stu-00417;origin-response`: the first evidence that the two functions **compose**. `content-type`, `etag` and `server` from the origin survive; the function adds to the response rather than replacing it.

---

### Step 14 - Check both functions against the Lambda@Edge restrictions

Floci lets you configure an edge function in ways real AWS rejects. This step makes one such mistake on purpose, then undoes it and checks both functions statically.

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

The environment-variable rule bites hardest: at the edge, constants live in the code, which is why Steps 7 and 12 declare them at the top of the file. The region rule is invisible here only because `us-east-1` is the course region.

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

The call succeeds on real AWS too: environment variables are a legal Lambda feature. **CloudFront** rejects them later, when you associate the function (`InvalidLambdaFunctionAssociation: The function cannot have environment variables`), in a different API call, about a different resource. That gap is why this lab checks statically.

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

- `--environment 'Variables={}'` is the only way to clear variables; there is no `--no-environment`.
- `edge_eligibility` reads one configuration and answers six questions. Exercise 3 reuses it and Section 8 folds two checks into `verify-lab-10.sh`.
- Python reads the JSON because `Environment` is absent when unset, and JMESPath would return `None`, which `[ -eq 0 ]` cannot compare.
- `\$LATEST` is escaped inside the double-quoted `--query`, or the shell would expand it to nothing and the count would be off by one, silently.

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

`grep -c` prints `0` and exits non-zero, so the `||` message appears. Any `NO` line names the restriction violated; if the environment line still says `NO`, re-run part 2.

**Checkpoint 5**

```text
usms-edge-viewer-request     nodejs20.x  128 MB  5 s   version 1   edge-eligible
usms-edge-origin-response    nodejs20.x  128 MB  5 s   version 1   edge-eligible
 └── environment variables set on $LATEST and removed again - deliberately
```

---

### Step 15 - Associate both functions with a CloudFront distribution

This is where the functions join a request path, and the step most likely to differ between builds (Step 4 recorded your path).

| Part of the config | The question it answers |
| --- | --- |
| `Origins` | where does the content come from |
| `DefaultCacheBehavior` | how is it cached, and what is the cache key |
| `LambdaFunctionAssociations` | what code runs, at which of the four trigger points |
| `Enabled`, `PriceClass`, `Comment` | is it on, how far does it spread, what is it for |

By default CloudFront caches on the URI alone. This config forwards exactly one header (`x-usms-student`) and no cookies: every extra cache-key element multiplies the stored copies of each object.

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

- **Unquoted heredoc** here, on purpose: `$(date +%s)` and the two version ARNs must be substituted. Ask before every heredoc: *should this file contain what I typed, or what it evaluates to?*
- `CallerReference` is CloudFront's idempotency token; the epoch second gives a fresh one each time.
- `IncludeBody` is valid only on request triggers, so it is absent from the origin-response association.

**Expected result**

```text
valid JSON
          "LambdaFunctionARN": "arn:aws:lambda:us-east-1:000000000000:function:usms-edge-viewer-request:1",
          "LambdaFunctionARN": "arn:aws:lambda:us-east-1:000000000000:function:usms-edge-origin-response:1"
```

> Example output - line numbers will differ.

Both ARNs must end with `:1`. If not, the version variables were empty (a new terminal since Step 13); re-run the `publish-version` captures from Steps 11 and 13 and regenerate the file.

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

You want two association rows (`viewer-request`, `origin-response`) with version-qualified ARNs. `Status` reads `InProgress` or `Deployed`; on real AWS the push to every edge location takes minutes.

**Command - part 2, PATH B: validate the configuration instead**

Take this path if Step 4 reported CloudFront as `UNSUPPORTED`. You perform the part that can be performed and record the rest.

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

You want eleven `ok` entries and an empty `errors` list: the configuration is structurally correct and satisfies the association rules, which is all you can honestly claim without CloudFront.

!!! note "Floci Limitation - no emulator executes Lambda@Edge"
    Even where `create-distribution` succeeds, Floci stores a record: no edge location, replication, cache or request path. No local emulator runs Lambda@Edge.

    Real AWS validates each association (region, version-qualified ARN, no environment variables, caps), replicates the function to every point of presence, and logs in the region **nearest the viewer**.

    The configuration, the association rules and the trigger-point reasoning transfer. Step 16 runs your code in sequence.

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

Nothing local runs a request path, so this script builds one: viewer event to the first function, a simulated origin response, then the second function, printing what a browser would receive. The property proved is **composition**: the header the first function writes is the one the second reads.

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

- Quoted outer heredoc (and quoted inner `<< 'PY'` blocks): `$1`, `${BASH_SOURCE[0]}` and `$(...)` must run when the script runs, not when it is written.
- `REPO_ROOT` from `${BASH_SOURCE[0]}` makes it work from any directory.
- `configs/lab-10.env` does not exist until Step 23; `|| true` and the `${...:-default}` values cover both cases.
- A viewer-request function returns a request or a response with no discriminator field; `'status' in d` tells them apart, as CloudFront does.

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

The allow run passes all three stages and its `x-usms-edge-chain` holds the first function's string plus the second's marker; only genuine composition produces that. The deny run has a chain of one: an unauthenticated request costs one edge invocation and no origin traffic.

The trace file now holds the deny run. Restore the allow trace, which Exercise 5 uploads:

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

The edge functions handle the request path; this one reacts after a transcript lands in the bucket. Nobody is waiting for it, so it does not belong at the edge.

| | Edge function | Regional function |
| --- | --- | --- |
| Triggered by | a viewer's request | an event: S3, SQS, a schedule, another service |
| Latency matters | yes - the viewer is waiting | no - nobody is waiting |
| Configuration | constants in the code | environment variables |
| Runs | wherever the viewer is | in one region, near your data |
| Can call other AWS services | badly - every call crosses a continent | yes, that is the normal case |

The test for the edge is "does this have to happen before the viewer can be answered?". Notifying the registrar does not, so this function is regional, in Python, with environment variables.

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

- Quoted heredoc even though the file has no `$` today: quote unless you specifically want expansion, or the first `${...}` you add later breaks silently.
- `py_compile` syntax-checks without running and leaves `__pycache__`, which `.gitignore` excludes (Step 24 confirms).
- `import boto3` inside the guarded block means an unavailable dependency degrades one output field instead of failing initialisation.

**Expected result**

```text
syntax OK (python3)
```

**Verify**

```bash
grep -n 'os.environ.get' labs/lab-10-lambda-edge/transcript-notifier/notifier.py
```

Two lines: the `os.environ.get` calls the edge functions were not allowed to have.

---

### Step 18 - Create the notifier, publish it, and give it an alias

Same creation pattern, but this function takes environment variables and gets an **alias**, a named, movable pointer to a version:

```text
usms-transcript-notifier
 ├── $LATEST ........ what you are editing
 ├── 1 .............. immutable snapshot
 ├── 2 .............. immutable snapshot
 └── live ---------→ currently points at 1
```

Triggers point at `:live`; deploying or rolling back is one `update-alias` call with no trigger reconfiguration. The edge cannot use this for the very reason it is valuable here: the pointer moves.

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

- `--handler notifier.handler`: module `notifier.py`, function `handler`.
- `--environment "Variables={...}"` is double-quoted so `$BUCKET` expands; shorthand syntax has no quoting of its own.
- `--timeout 30 --memory-size 256`: no edge caps apply, and the function may wait on S3.

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

The alias ARN ends with `:live`, not `:1`. Both are qualified; only one can be repointed.

**Verify**

```bash
aws lambda list-aliases --function-name "$NOTIFIER_FN" \
  --query 'Aliases[].[Name,FunctionVersion,Description]' --output table

aws lambda get-function-configuration --function-name "$NOTIFIER_FN" --qualifier live \
  --query '{Version:Version,Runtime:Runtime,Handler:Handler,Env:Environment.Variables}' \
  --output json
```

You want one alias, `live`, pointing at version `1`, and the qualified configuration reporting `Version: "1"`, not `$LATEST`. `--qualifier` targets a specific version or alias (used again in Steps 19 and 21). The environment variables are present: the same configuration that was a mistake on an edge function in Step 14.

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

The execution role says what the function may do; nothing yet says who may **call** it. S3 invokes the function as S3, so it needs a **resource-based policy** on the function. Background: [identity-based versus resource-based policies](../unit8/topic1.md#identity-based-versus-resource-based-policies).

| | Attached to | Answers |
| --- | --- | --- |
| Execution role (`usms-lambda-exec-role`) | the function | what may **this code** do |
| Resource policy (function policy) | the function | who may **invoke** this function |

Granting `s3.amazonaws.com` alone would let **any** bucket in any account trigger your function (the [confused deputy](../unit8/topic1.md#the-confused-deputy-problem)). `--source-arn` and `--source-account` restrict it to this bucket in this account, the same idea as the `aws:SourceArn` and `aws:SourceAccount` conditions Lab 09 added to a trust policy.

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

- `--qualifier live` attaches the statement to the alias S3 will invoke; a permission on the unqualified function does not cover `:live`.
- `--statement-id` names the statement; you need it to remove it.
- `--action lambda:InvokeFunction`, not `lambda:*`.
- `add-permission` returns the statement as a JSON **string**; `--output text | python3 -m json.tool` unwraps and prints it.

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

The assertion line must print. If it fails on the condition, you omitted `--source-arn`; remove the statement and redo it:

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
    Floci stores and returns the policy but does not check it; Step 20's notification would fire even with no permission.

    Real AWS checks it on every invocation. A missing statement makes the notification fail **silently**: no error, no log, because the function never ran.

    Do not read Step 20's success as evidence the permission is right. Read the policy, as the verify above did.

---

### Step 20 - Wire the bucket notification and fire it for real

The notification is a property of the **bucket** and names the function. `put-bucket-notification-configuration` is **replace-only**: it overwrites every notification on the bucket, so on a bucket with existing notifications you must get, merge, put. This bucket has none yet.

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

- Unquoted heredoc: `${NOTIFIER_ALIAS_ARN}` must be substituted.
- `s3:ObjectCreated:*` covers every way an object can arrive.
- The `Filter` scopes the trigger to `transcripts/*.json`. Without it, a function writing to its own bucket can trigger itself in a loop, billed per invocation. One prefix and one suffix rule per filter; overlapping configurations are rejected.

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

The loop uploads the first existing artefact, preferring Lab 08's evidence file (the first `put-object` Lab 08 promised), then Lab 06's, and otherwise generates a placeholder so you are never stuck. The key `transcripts/evidence/<file>.json` matches the filter; check this by eye every time, because a non-matching key fails as silently as a missing permission.

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

You want one notification row whose ARN ends `:live` and one object under `transcripts/evidence/`. If `list-objects-v2` returns nothing, the upload failed.

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

Configuring a trigger and uploading an object is not evidence your code executed. Look for the evidence, with a fallback because event delivery is the least reliable part of any emulator.

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

`filter-log-events` searches every stream in the group. `"USMS_NOTIFY"` is a CloudWatch Logs filter pattern (a plain term, not a regex), which is why the handler prefixes its output with a marker.

**Expected result - if event delivery works on your build**

```text
usms-transcript-notifier: 1 record(s), channel=stdout, bucket_hint=usms-student-data
USMS_NOTIFY {"bucket": "usms-student-data", "event": "ObjectCreated:Put", "key": "transcripts/evidence/lab-08-scaling-evidence.json", "readable": true, "size": 2184}
```

> Example output - your key, size and `readable` value will differ.

You want a `USMS_NOTIFY` line naming your object. `readable: false` with a `read_error` means the container could not reach the S3 API (see the note below), not that the trigger failed.

**Command - part 2, the fallback: invoke with a synthetic S3 event**

Do this if part 1 printed nothing. If the handler works on a hand-made event, your code and permissions are right and only **delivery** is missing; if it fails here too, the problem is in the handler.

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

You want `"processed": 1` and a `USMS_NOTIFY` line. `Version: 1` in the `START` line shows `--qualifier live` resolving through the alias, exactly as S3 would.

!!! note "Floci Limitation - S3 event delivery and outbound calls from a Lambda container"
    Some builds store the notification configuration without delivering events. Separately, the Lambda container may not know the emulator's endpoint, so `boto3` inside it tries real AWS and you see `read_error` (which is why that call is wrapped).

    Real AWS delivers the event within seconds and supplies execution-role credentials, so `head_object` succeeds exactly when the role permits it.

    Part 2 still gives a genuine execution of your handler over a genuine S3 event structure. Judge the permission by reading the policy.

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

Prove persistence: create, perturb, read back. Lambda stores function **code** separately from **metadata**, and a build can keep one and lose the other, so the read-back also runs the code.

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

`floci-down.sh` is `docker compose stop`: state is kept. It is not `docker compose down -v`, which deletes the volumes.

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

Names surviving is weaker evidence than code surviving, so invoke it:

```bash
./scripts/utilities/usms-edge-simulate.sh | tail -20
```

You want no `diff` output and the `x-usms-edge-chain` header still produced. A missing function is a persistence failure; a changed alias version just means Step 18's "Your turn" was not put back.

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

Turn this lab's shell variables into a file the next lab can source.

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

**Unquoted heredoc**: every `$(...)` runs now, so the file holds values. A quoted one would write command text that does nothing when sourced, with no error. This lab's three heredoc choices:

| Step | Form | Because |
| --- | --- | --- |
| 6, 7, 12, 16, 17 | `<< 'EOF'` | the file must contain exactly what you typed |
| 15, 20 | `<< EOF` | two ARNs and a timestamp must be substituted |
| 23 | `<< EOF` | every value is the output of a command run now |

- `max_by(..., &to_number(Version))`: versions are strings, so without `to_number` version 10 sorts before 9. `\$LATEST` is escaped so the shell leaves it for JMESPath.
- `| grep -E ... || echo not-created`: turns a `None` from `--output text` into an honest sentinel.

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

You want **25** exports, `all values populated`, and a clean source. `not-created` on the three CloudFront lines is a populated value, expected on Path B.

---

### Step 24 - Check what Git sees, and commit

This lab wrote source, templates, a config file and three ZIP archives. Find out which category does not belong before it is in the history.

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

Check before committing:

- **No `outputs/` path** (archives, trace, logs). If one appears, the `.gitignore` rule is damaged.
- **No `.env` other than `configs/lab-10.env`.** The root `.env` is generated by `floci-up.sh` and never committed.
- **No `__pycache__`** (Step 17 created one).

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

`check-ignore` names the rule and line, and `git ls-files outputs/` lists only `.gitkeep`. That is Lab 1's `outputs/*` plus `!outputs/.gitkeep` rule still holding; `outputs/` would make the negation silently fail.

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

Paths are named explicitly rather than `git add -A`, so you do not rely on the ignore rule alone. `verify-lab-10.sh` and `lab-10-cleanup.sh` are created in Sections 8.1 and 8.2; if you have not reached them yet, add them in a second commit.

**Verify**

```bash
git log --oneline -1
git show --stat --oneline HEAD | head -20
```

The commit exists, and its file list contains no `outputs/` path and no `.zip`.

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

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-10.sh`

The script checks existence, configuration, and the environment underneath. Several checks are static substitutes for enforcement Floci does not perform: no environment variables on edge functions, version-qualified association ARNs, a resource policy scoped to one bucket.

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

Failures in the **Environment** block are the real problem; fix them first and re-run. No check depends on CloudFront support: the association block reads `templates/lab-10-distribution-config.json`, which both paths produce.

Two checks that are worth understanding rather than merely passing:

| Check | Why it is there |
| --- | --- |
| `viewer handler kept its template literal` | The static detector for an unquoted heredoc in Step 7. That bug produces a function that deploys, runs, and silently stamps an empty student id - nothing else in this script would catch it |
| `every associated ARN is version-qualified` | The static substitute for the validation real AWS performs and Floci does not. It is the only thing standing between you and an association that would be rejected in production |

### 8.2 Build the end-of-course cleanup script

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

The order is the lesson: remove the notification first (stop the traffic, then the target); unqualified `delete-function` deletes **every** version (`--qualifier 1` deletes one); and a bucket must be emptied before deletion, where `aws s3 rm --recursive` is simpler than a paginated `s3api delete-objects` loop.

---

## 9. Checkpoints

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

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, functions do not run at edge locations. Diagnose first, then use the alternative in [Known Issues - Lab 10](known-issues.md#lab-10-lambda). It states what the alternative does and does not prove.

### `aws lambda list-functions` returns a connection error, exit code 255

Exit `255` is a client or connection failure: Floci is not answering.

{% raw %}```bash
docker container inspect floci --format '{{.State.Status}}'
./scripts/setup/floci-up.sh
curl -s http://localhost:4566/_localstack/health | head -5
```{% endraw %}

If the container runs but the health probe is empty, Floci is still starting (the first start after an image pull can take a minute).

### `create-function` fails with `InvalidParameterValueException: The role defined for the function cannot be assumed by Lambda`

The trust policy does not name `lambda.amazonaws.com`, usually because Step 6's update named only `edgelambda` (the update **replaces** the whole policy).

```bash
aws iam get-role --role-name usms-lambda-exec-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[].Principal.Service' --output json
```

You need two entries. Re-run Step 6 parts 2 and 3 if you see one.

### The function returns `Unhandled` with `Cannot find module 'index'`

The archive does not hold `index.mjs` at its root, or the handler string does not match. Look inside:

```bash
python3 -m zipfile -l outputs/usms-edge-viewer-request.zip
aws lambda get-function-configuration --function-name usms-edge-viewer-request --query 'Handler'
```

`labs/lab-10-lambda-edge/edge-viewer-request/index.mjs` instead of `index.mjs` means you zipped from the repository root. Rebuild from inside the function's directory (Step 8 part 1).

### The function runs but the student id in `x-usms-edge` is empty

The Step 7 heredoc was unquoted and bash expanded the template literal.

```bash
grep -n 'toLowerCase()}' labs/lab-10-lambda-edge/edge-viewer-request/index.mjs
```

No output means the expression is gone. Re-run Step 7 with `<< 'EOF'`, rebuild the archive, and update the code:

```bash
aws lambda update-function-code --function-name usms-edge-viewer-request \
  --zip-file fileb://outputs/usms-edge-viewer-request.zip
```

Then publish a new version; version 1 is immutable and still broken.

### `invoke` writes an empty file and prints nothing useful

You probably omitted the positional output-file argument; the return value goes there and only metadata to stdout. Also check you used `--payload fileb://`, not `file://` (the error mentions base64, not your file).

### `LogResult` is `None`, or the log group does not exist

Log capture is build-dependent. Confirm the function ran from its return value (Step 9's payload). If this build gives no logs, read the **returned object** instead; the notifier returns a summary for this reason.

### The upload in Step 20 produces no invocation

Three candidates, in order:

```bash
# 1. does the key match the filter?
aws s3api list-objects-v2 --bucket usms-student-data --query 'Contents[].Key' --output text

# 2. is the notification actually configured?
aws s3api get-bucket-notification-configuration --bucket usms-student-data

# 3. can the function be invoked at all, given a hand-made event?
aws lambda invoke --function-name usms-transcript-notifier --qualifier live \
  --payload fileb://templates/lab-10-s3-event.json /dev/stdout
```

If 1 and 2 are correct and 3 works, delivery is not implemented on your build (the Step 21 limitation). Record it and move on.

### `create-distribution` fails with `InvalidArgument` or the operation does not exist

Your build lacks CloudFront. Take Path B in Step 15. Nothing later depends on the distribution: Step 16 is the proof and Section 8 verifies the configuration file.

### `put-bucket-notification-configuration` fails with `InvalidArgument: Unable to validate the following destination configurations`

On real AWS, S3 checks at configuration time that it may invoke the target. Re-run Step 19 and confirm with `aws lambda get-policy --function-name usms-transcript-notifier --qualifier live`. A permission on the unqualified function does not cover `:live`.

### `verify-lab-10.sh` reports `configs/lab-10.env has 25 exports` as a failure

```bash
grep -c '^export' configs/lab-10.env
grep -nE '^export [A-Z_]+=$' configs/lab-10.env
```

An empty value means its `$(...)` returned nothing, usually because a shell variable was empty in a new terminal. Re-derive the value with an `aws` call, or re-run Step 23 in a shell where the Step 8 to 18 variables are set.

### Everything worked yesterday and nothing works today

```bash
./scripts/utilities/floci-storage-check.sh
```

`FAIL` in the shell block means a new terminal lost the course environment (Errata 01). `FAIL` on the storage-mode check means Floci ran in `memory` mode and yesterday's work is gone; fix the compose file.

---

## 11. Floci vs Real AWS

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

**Where Floci is nicer than reality (traps on real AWS):** associations are accepted without validation (real AWS rejects the whole `update-distribution`, minutes later, about a different resource); deployment is instant (a real distribution and every function-version update take minutes, so an edge rollback takes minutes); nothing is cached (on CloudFront, a wrong `origin-response` header is baked into cached objects until invalidation or TTL); IAM is not evaluated (a missing resource policy makes S3 notifications fail silently); no cold starts, concurrency limits or throttling; and no cost (edge invocations have no free tier, and Step 12's trigger choice is a three-order-of-magnitude billing difference).

In your report, separate what you **observed** (functions created and invoked, the event structure, requests modified and refused, responses modified, two functions composing, versions, aliases, the resource policy, the bucket and notification, persistence) from what you only **recorded** (the two-principal trust rule, the distribution configuration, the qualified-ARN rule, the no-environment-variables rule, the caps). Latency, caching and cost were not available at all, and must not be claimed as tested.

!!! note "Floci Limitation - the one that shapes this whole lab"
    Floci does not run Lambda@Edge: there is no edge location and no request path to intercept.

    Real AWS replicates the published version to every point of presence in the price class and runs it there, logging to the region nearest the viewer.

    This lab exercises the whole function contract directly, plus `usms-edge-simulate.sh` in CloudFront's order.

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-10-lambda-edge/exercises.md`; several exercises also ask for a file in `outputs/`.

### Exercise 1 - Basic: extend the security header set

**Requirements:** add `Content-Security-Policy: default-src 'self'` to the origin-response function, deploy it, publish version 2, and prove version 1 still returns the original four headers.

**Constraints**

- Add it by editing the `SECURITY_HEADERS` object, not with a second block of code.
- Do not delete or overwrite version 1.
- Update the distribution configuration file to reference the new version.

**Expected outcome:** `$LATEST` returns five security headers; `--qualifier 1` returns four; `templates/lab-10-distribution-config.json` names version 2.

**Hints:** `update-function-code` takes the same `--zip-file fileb://`. `--qualifier` works on `invoke`. Update the code, then publish.

### Exercise 2 - Intermediate: a dedicated edge execution role

**Requirements:** the edge functions never touch the bucket. Create `usms-edge-exec-role` with a new customer managed policy `USMSEdgeBasic` granting **only** CloudWatch Logs writes, trusting both `lambda.amazonaws.com` and `edgelambda.amazonaws.com`. Repoint both edge functions at it and publish new versions. Then explain in `exercises.md` what happened to version 1's role.

**Constraints**

- Use `policies/usms-edge-basic-policy.json`; reuse `policies/trust-lambda-edge.json` as-is.
- Do not modify or detach anything from `usms-lambda-exec-role`; the notifier still uses it.
- Scope log writes to `/aws/lambda/usms-edge-*`, not `*`.

**Expected outcome:** `--qualifier 1` still reports the **old** role; `$LATEST` reports the new one. Your answer explains why, and that rolling back to an old version restores its old role too.

**Hints:** Lab 01's `policies/usms-*-policy.json` files show the shape. A log-group ARN ends `log-group:/aws/lambda/usms-edge-*:*`; the trailing `:*` covers the streams. Lab 09 Step 4's audit script lists what a role carries.

### Exercise 3 - Problem solving: an edge-readiness report

**Requirements:** write `scripts/utilities/usms-edge-report.sh` that emits one JSON document listing every `usms-` function with name, runtime, memory, timeout, published versions, aliases, whether environment variables are set, and `edge_eligible`. `edge_eligible` is `true` only when: Node or Python runtime; no environment variables; no VPC configuration; at least one published version; and memory at most 128 and timeout at most 5 **if** the name contains `viewer`, otherwise at most 10240 and 30.

**Constraints**

- Valid JSON on stdout only; diagnostics to stderr.
- Runs correctly from any directory.
- Does not fail under `set -u` when a function has no `Environment` key.
- No hard-coded function list.

**Expected outcome**

```text
Expected shape:
[
  { "name": "usms-edge-viewer-request", "runtime": "nodejs20.x", "memory": 128,
    "timeout": 5, "versions": 1, "aliases": 0, "env_vars": false, "edge_eligible": true },
  ...
]
```

Three objects, with the notifier `edge_eligible: false` for two independent reasons.

**Hints:** Step 14's `edge_eligibility` has the per-field logic. `list-functions` with a `starts_with` filter returns most of the configuration in one call. Build the JSON in `python3`, not by bash string concatenation. `${BASH_SOURCE[0]}` finds the repository root.

### Exercise 4 - Challenge: design the transcript delivery policy

The registrar brings requirements, not a design:

> Transcripts must never be served to a request without a valid session token, and the check must not
> cost us an origin request. A corrected transcript must stop being served within five minutes of the
> correction, but we do not want to pay to re-fetch unchanged transcripts every five minutes. The
> Dean's office needs a report of how many transcript requests were refused, by faculty. And whatever
> you build must survive one edge location being unable to reach the origin.

**Requirements:** write `notes/lab-10-edge-design.md` (one to two pages) that:

1. Chooses, for each piece of logic, a CloudFront Function, Lambda@Edge at a named trigger point, or a regional function, justifying each in one or two sentences.
2. States the cache key, and what you would deliberately **not** put in it.
3. Explains how the five-minute correction window and the do-not-re-fetch requirement can both be met.
4. Says where the refusal report comes from, given that edge logs land in the region nearest the viewer.
5. Names one requirement an edge function is the **wrong** tool for, and what you would use instead.

**Constraints**

- No commands; this is a design document.
- Every AWS feature named must exist; if unsure, say what you would verify and how.
- State at least one thing you would measure first, and what result would change your mind.

**Expected outcome:** a document a colleague could implement, whose interesting paragraphs are the trade-offs. Point 3 has more than one defensible answer.

**Hints:** Step 12's `origin-response` versus `viewer-response` reasoning applies to TTLs: `max-age` and `s-maxage` control different caches. Section 11 says where edge logs land. Point 5: one requirement is not on the request path at all.

### Exercise 5 - Integration: hand the S3 lab a bucket it can start from

The next lab configures `usms-student-data` properly and applies Lab 09's drafted bucket policy. Prepare its inheritance.

**Requirements**

1. Locate `outputs/lab-09-bucket-policy-draft.json`. If missing, generate an equivalent: a bucket policy granting the three role ARNs that carry `USMSStudentDataReadWrite` `s3:GetObject` on `arn:aws:s3:::usms-student-data/*`, written to the same path.
2. Validate it: every bucket ARN must match the existing bucket, every principal must be an existing role. Report mismatches; do not fix them silently.
3. **Do not apply it.** That is the S3 lab's step.
4. Upload the **allow** trace `outputs/lab-10-edge-trace.json` to `s3://usms-student-data/transcripts/evidence/lab-10-edge-trace.json` and confirm the notifier saw it (logs or a direct invocation).
5. Write `outputs/lab-10-s3-readiness.txt`: bucket name and ARN; object count under `transcripts/`; the notification id, target ARN and filter; the three functions and their published versions; whether CloudFront was supported; and the point 2 result.

**Constraints**

- Generate the readiness file with a re-runnable command sequence, not by hand.
- It stays in `outputs/`; confirm with `git check-ignore -v`.
- The draft stays unapplied: `aws s3api get-bucket-policy --bucket usms-student-data` must fail.

**Expected outcome**

```text
Expected result:
- outputs/lab-09-bucket-policy-draft.json exists and every ARN in it resolves
- get-bucket-policy on usms-student-data FAILS (NoSuchBucketPolicy) - correct, the S3 configuration
  lab applies it
- at least two objects under transcripts/
- outputs/lab-10-s3-readiness.txt exists, is git-ignored, and is reproducible
```

**Hints:** `aws iam list-entities-for-policy` lists the roles carrying a policy. `|| echo "no bucket policy - correct"` makes the expected failure readable. Step 20's `for candidate in ...` loop is the "use this file if it exists, otherwise generate one" pattern.

---

## 13. Lab Assessment Checklist

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

### 13.1 In-class practical assessment

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

## 14. Review Questions

Answer in prose in `notes/lab-10-notes.md`.

1. A colleague proposes moving the whole USMS enrolment API to Lambda@Edge "because it will be faster for everyone". Give the two strongest technical arguments against, and the one situation in which they would be right.
2. Distinguish CloudFront Functions from Lambda@Edge (runtime, trigger points, capabilities, relative cost). Which would you use to add `/index.html` to a URI, to check a JWT signature, and to fetch a per-user redirect from DynamoDB, and why?
3. Step 12 put the security headers at `origin-response`, not `viewer-response`, with identical output. Explain the difference in terms of the cache, and describe a requirement that would force `viewer-response` despite the cost.
4. The notifier's execution role grants `s3:GetObject`, and its resource policy lets `s3.amazonaws.com` invoke it. A colleague calls this redundant. Explain who makes which call under each policy, and what breaks if you delete each one separately.
5. Step 19 added `--source-arn` and `--source-account` to a permission that worked without them. Describe the attack they prevent concretely, name the equivalent mechanism from Lab 09, and say what makes them the same idea.
6. Step 14 set environment variables on an edge function and the call succeeded, yet the configuration is invalid. Where does validation actually happen, why is the mistake not rejected immediately, and what does that imply about checking edge configuration? Relate it to the rule that a command appearing to succeed is not evidence it did what you meant.

---

## 15. KEEP vs CLEAN UP

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

If you did Exercise 1, keep version 2 of the origin-response function. If you did Exercise 2, keep `usms-edge-exec-role` and `USMSEdgeBasic` and note them in your exercises file. If you did Step 18's "Your turn", check that `live` points back at version 1:

```bash
aws lambda get-alias --function-name usms-transcript-notifier --name live \
  --query 'FunctionVersion' --output text
```

Do **not** run `scripts/cleanup/lab-10-cleanup.sh`; it is for the end of the course.

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

## 16. Preparation for the Next Lab

The next lab is the **S3 configuration lab**, not yet numbered. It opens with a real bucket holding real objects and a real trigger, still missing versioning, encryption, lifecycle rules and a bucket policy.

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

**Be careful:** `put-bucket-notification-configuration` replaces the whole notification document, so adding an SNS destination without get-merge-put silently deletes Step 20's Lambda notification. Replace-only APIs are a category: `update-assume-role-policy`, `put-bucket-notification-configuration`, `put-bucket-policy`, `put-bucket-tagging`.

Before the next session (all four should pass):

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-10.sh            # PASS=51  FAIL=0
grep -c '^export' configs/lab-10.env            # 25
aws s3api head-bucket --bucket usms-student-data && echo "bucket present"
aws s3api get-bucket-policy --bucket usms-student-data 2>/dev/null \
  || echo "no bucket policy yet - correct, the S3 configuration lab applies it"
```

Take a snapshot before you finish:

```bash
floci snapshot save lab-10-complete
floci snapshot list
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-10.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

---

## Appendix - New CLI and JMESPath patterns

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
| Replace-only APIs | Steps 6, 20, and Section 16 |

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
- Course documents: Lab 01 (IAM), Lab 02 Step 21 (the S3 gateway endpoint), Lab 03 Section 17
  (the `head-bucket` probe that was expected to fail), Lab 06 Section 17, Lab 09 Step 4 and its
  identity-versus-resource-policy distinction, Lab 08 Section 17, Errata 01.

# Lab 12 - Deploying to Amazon ECS from the Pipeline

*Practical 7 - Practical 5 in the module descriptor. The second half of the pipeline: an
image with a name, a task definition that points at it, and a deploy stage that closes the loop.
This document also carries the Practical 7 in-class assessment, in Section 14.1.*

!!! info "Numbering - the same note as Lab 11"
    Your module descriptor numbers this practical **5**; the delivery schedule numbers it **7**.
    Laboratory numbering follows the dependency graph, not a slot reserved in advance - see Lab 11's
    note for the full table. The Amazon S3 configuration document that Lab 10 Section 17 promised is
    still unwritten; it takes whatever number fits the graph when it is written, not a number promised
    now. Section 17 of this lab hands over to it.

---

## 1. Lab Overview

Lab 11 left a machine that turns a source change into an artifact. The artifact is real: it has a
release number, a build ID, and an S3 key. It also, at the moment, goes nowhere. The enrolment service
running on `usms-ecs-cluster` is still running the placeholder image that Lab 04 chose because the
course had no application of its own.

This laboratory connects the two ends. By the time you finish:

- the enrolment service's source will be built into a **container image** and pushed to a **private
  Amazon ECR repository** that you create;
- the ECS task definition will name **your image**, not the placeholder;
- the pipeline will have a **third stage** that takes the build artifact, reads
  `imagedefinitions.json` out of it, registers a new task definition revision with the new image, and
  updates the service - with no human typing `aws ecs update-service`.

Three things in that list are genuinely new to this course. Nothing before this lab has ever built a
container image, pushed to a registry, or deployed anything without a person at a keyboard.

The lab also spends a step on the thing that makes deployment pipelines survivable: **what happens
when the new version is wrong.** Section 8 Step 18 is a rollback drill, and Step 19 reads the
blue/green mechanism that makes rollback near-instant on real AWS - as a document, honestly labelled,
because this emulator cannot run it.

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 will suggest `aws login`. That begins a sign-in to
    **real AWS**. The answer in this course is always `source configs/course.env` or a missing
    `floci` profile - never a sign-in. See Errata 01 Section 3.

### 1.1 What is genuinely new here

| New thing | Why it matters |
| --- | --- |
| A private ECR repository | The first registry in this course that is yours. Everything before pulled from public registries |
| `docker build` and `docker push` | The step that turns a source tree into something ECS can run |
| Image tag versus image digest | A tag can be moved; a digest cannot. This distinction decides what "the version we deployed" means |
| Task definition revisions from a template | `describe` → modify → `register` is the pattern the deploy action automates. You do it by hand once, so you can see what it automates |
| `imagedefinitions.json` | The contract between a build and an ECS deploy action. Three fields, one of which must match a container name exactly |
| IAM policy versions | `USMSCodeBuildBase` gets a `v2`. Creating a version does not activate it - you must say so |
| `update-pipeline` | A replace-only API. Get, modify, put. There is no "add a stage" |
| Deployment rollback | What the circuit breaker does, what it cannot do, and what you do when it does not fire |

### 1.2 Time

Roughly three and a half hours, plus the in-class assessment in Section 14.1, which is timed at sixty
minutes and is normally run in a separate session.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. Create a private ECR repository, authenticate Docker against it, and push an image - reading the
   registry host from the API rather than assuming it.
2. Explain the difference between an image tag and an image digest, and say which one a production
   task definition should name and what that costs.
3. Produce a new ECS task definition revision from an existing one with `describe` → modify →
   `register`, and name the read-only fields that must be stripped before re-registering.
4. Write `imagedefinitions.json`, and explain precisely what the ECS deploy action does with it - and
   what it cannot express.
5. Create a new version of a customer-managed IAM policy and set it as the default, and explain why
   those are two operations.
6. Extend a CodePipeline safely with the get-modify-put sequence, and say what would have been lost by
   sending only the new stage.
7. Deploy an application to ECS entirely through a pipeline, and verify the deployment by reading the
   service's task definition and the image its tasks are running.
8. Roll a deployment back, and explain what the ECS deployment circuit breaker does, when it fires,
   and when it will not save you.
9. Describe a blue/green ECS deployment with CodeDeploy accurately enough to specify one, while
   stating clearly that you did not perform one.

---

## 3. Prerequisites

- **Lab 11 complete**, including Exercise 5 if you did it. Section 8 Step 1 reads its readiness file
  and tolerates its absence.
- Labs 01, 02, 03, 04, 05 and 06 complete. Lab 07-08 (EKS) and Lab 09 (security) are helpful but
  not required.
- `docker` working for your user, and a Docker daemon you can reach: `docker info` must succeed. This
  lab builds an image locally. There is no path through this laboratory without a Docker daemon.
- Roughly 1 GB of free disk for the base image and your layers.
- `python3`, `zip`/`unzip` as in Lab 11.

Baseline verification:

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/floci-storage-check.sh      # PASS=16  FAIL=0
./scripts/utilities/verify-lab-04.sh           # PASS=48  FAIL=1  (or 49/0 after Lab 05 Exercise 2)
./scripts/utilities/verify-lab-05.sh           # PASS=49  FAIL=0
./scripts/utilities/verify-lab-11.sh           # PASS=46  FAIL=0  (or 38/8 on Path B or C)
docker info >/dev/null 2>&1 && echo "docker reachable"
```

If `verify-lab-11.sh` reports failures outside the known-benign list in Lab 11 Section 9.1, fix them
before starting. This lab modifies the pipeline that script checks.

---

## 4. Connection to Previous Labs

### 4.1 Current environment

```text
Created in previous labs:
- Lab 01: IAM foundation; usms-ecs-exec-role and usms-ecs-task-role come from here
- Lab 02: usms-vpc, two public and two private subnets
- Lab 04: usms-ecs-cluster, task family usms-enrolment (rev 2), service usms-enrolment-svc,
           container enrolment-api on port 80, log group /usms/ecs/enrolment,
           policy USMSECSTaskExecution - which already grants the four ecr:* pull actions
- Lab 05: usms-enrolment-alb, target group usms-enrolment-tg, the service registered behind it
- Lab 06: scalable target min 2 max 10 on the service
- Lab 10: bucket usms-student-data
- Lab 11: usms-pipeline-artifacts (versioned), usms-enrolment-build, usms-enrolment-pipeline
           (Source -> Build), usms-codebuild-role + USMSCodeBuildBase,
           usms-codepipeline-role + USMSCodePipelineBase, labs/lab-11-cicd/app/ with buildspec.yml

Created in this lab:
- usms-enrolment                 ECR repository - the first private registry in this course
- Dockerfile                     in labs/lab-11-cicd/app/, beside the source it packages
- usms-enrolment:3               task definition revision naming YOUR image
- USMSCodeBuildBase v2           adds ECR push; set as the default version
- USMSCodePipelineBase v2        adds ecs:UpdateService and a second scoped iam:PassRole
- Deploy stage                   third stage of usms-enrolment-pipeline, provider ECS
- imagedefinitions.json          produced by the build, consumed by the deploy action
- templates/lab-12-appspec.yaml the blue/green document, read and validated, not executed

Required for future labs:
- usms-enrolment (ECR)           -> any later lab that needs a private image
- usms-enrolment-pipeline        -> the CloudFormation lab re-declares this whole pipeline
- USMS_IMAGE_TAG / USMS_IMAGE_DIGEST -> the evidence chain any later audit exercise uses
- configs/lab-12.env            -> the S3 configuration lab sources it only for completeness; the
                                    CloudFormation lab consumes it in earnest
```

### 4.2 The three artefacts this lab makes newly meaningful

**Lab 01's `USMSECSTaskExecution` already contains four `ecr:*` actions** -
`GetAuthorizationToken`, `BatchCheckLayerAvailability`, `GetDownloadUrlForLayer`, `BatchGetImage` -
on `Resource: "*"`. When Lab 04 wrote them, there was no ECR repository in the account and the
statement was a hypothesis. Step 5 of this lab creates the repository those four actions were always
about. The execution role needs no change; that is the payoff of having scoped it correctly a month
ago.

**Lab 04 Step 15 introduced `--force-new-deployment`** and justified it with "the image tag now
points at a different image". Step 17 of this lab is the first time in the course that sentence
describes something that actually happened.

**Lab 04's container name, `enrolment-api`,** has been a string in a task definition. In Step 14 it
becomes the join key in `imagedefinitions.json`, and a mismatch there is the most common failure in
ECS deployment pipelines. This is why Lab 11's `pre_build` validates it.

---

## 5. What We Are Building

```text
  BEFORE (end of Lab 11)                     AFTER (end of this lab)

  source -> build -> artifact                 source -> build -> artifact -> deploy
                       │                                    │                   │
                    (stops)                          builds an image      updates the ECS
                                                     pushes to ECR        service, which pulls
                                                                          the image and replaces
                                                                          its tasks
```

Concretely, four new things and three modified ones.

New: an ECR repository; a `Dockerfile`; an image with a tag; a third pipeline stage.

Modified: the buildspec gains an image build and an `imagedefinitions.json` writer; both IAM policies
gain a version 2; the task definition family gains revisions that name your image instead of the
placeholder.

The application itself does not change. It is the same four files it was in Lab 11, and that is
deliberate - everything interesting in this lab is about how those four files reach a running task.

---

## 6. Architecture

```text
   labs/lab-11-cicd/app/                         ECR: usms-enrolment
   ┌────────────────────┐                         ┌──────────────────────────────┐
   │ src/  config/       │   docker build         │  usms-enrolment:r6           │
   │ tests/ VERSION      │ ──────────────────────>│    digest sha256:8f3a...     │
   │ buildspec.yml       │   docker push          │  usms-enrolment:r7           │
   │ Dockerfile   (NEW)  │                        │    digest sha256:1c92...     │
   └────────────────────┘                         └──────────────────────────────┘
             │                                                   ^
             │ zip + upload                                      │ pulled by the task's
             v                                                   │ EXECUTION role
   S3: usms-pipeline-artifacts                                   │ (usms-ecs-exec-role,
   ┌──────────────────────────────┐                              │  USMSECSTaskExecution)
   │ source/usms-enrolment-src.zip│                              │
   └──────────────────────────────┘                              │
             │                                                   │
             v                                                   │
   CodePipeline: usms-enrolment-pipeline                         │
   ┌─────────────────────────────────────────────────────────────┼──────────────┐
   │  Source ──> Build ─────────────────────────> Deploy         │              │
   │             (CodeBuild)                      (provider ECS) │              │
   │             docker build + push ─────────────────────────────              │
   │             writes imagedefinitions.json                                   │
   │                        │                                                   │
   │                        v                                                   │
   │             [ { "name": "enrolment-api",                                   │
   │                 "imageUri": ".../usms-enrolment:r7" } ]                    │
   │                        │                                                   │
   │                        v                                                   │
   │             the deploy action:                                             │
   │               1. reads the service's CURRENT task definition               │
   │               2. replaces the image of the container named above           │
   │               3. register-task-definition  -> usms-enrolment:4             │
   │               4. update-service --task-definition usms-enrolment:4         │
   └────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      v
   ECS service usms-enrolment-svc on usms-ecs-cluster
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  deployment PRIMARY  usms-enrolment:4   desired 2   running 0 -> 2          │
   │  deployment ACTIVE   usms-enrolment:3   desired 2   running 2 -> 0          │
   │        both registered in target group usms-enrolment-tg during the overlap │
   └────────────────────────────────────────────────────────────────────────────┘
```

The four numbered steps inside the deploy action are the part worth memorising. Notice what is *not*
in that list: the deploy action never reads a task definition file from your repository. It takes the
one the service is running and changes one field in it. That is a genuine constraint, and Section 12
returns to it - a change to the task definition's memory, environment variables or log configuration
cannot travel through this mechanism at all.

---

## 7. Directory Structure

What this lab adds.

```text
aws-floci-course/
├── configs/
│   └── lab-12.env                            NEW
├── labs/
│   ├── lab-11-cicd/app/
│   │   ├── Dockerfile                         NEW  - beside the source it packages
│   │   ├── .dockerignore                      NEW
│   │   └── buildspec.yml                      MODIFIED - image build + imagedefinitions.json
│   └── lab-12-cicd-deploy/                   NEW
│       ├── README.md
│       └── exercises.md
├── policies/
│   ├── usms-codebuild-policy-v2.json          NEW  - adds ECR push
│   └── usms-codepipeline-policy-v2.json       NEW  - adds ECS deploy and a second PassRole
├── templates/
│   ├── lab-12-taskdef-base.json              NEW  - describe-task-definition output
│   ├── lab-12-taskdef-v3.json                NEW  - the revision that names your image
│   ├── lab-12-codebuild-update.json          NEW  - privilegedMode and IMAGE_REPO_URI
│   ├── lab-12-pipeline-current.json          NEW  - the two-stage document, before surgery
│   ├── lab-12-pipeline.json                  NEW  - the three-stage document
│   ├── lab-12-appspec.yaml                   NEW  - CodeDeploy, conceptual
│   └── lab-12-codedeploy-deployment-group.json NEW  - CodeDeploy, conceptual
├── scripts/
│   ├── utilities/
│   │   ├── deploy-support-probe.sh            NEW
│   │   ├── usms-ecs-watch.sh                  NEW  - polls a service's deployments
│   │   └── verify-lab-12.sh                  NEW
│   └── cleanup/
│       └── lab-12-cleanup.sh                 NEW  - DO NOT RUN NOW
├── outputs/
│   ├── lab-12-deploy-probe.txt               NEW  - git-ignored
│   ├── lab-12-image-digest.txt               NEW  - git-ignored
│   └── lab-12-deploy-evidence.txt            NEW  - git-ignored
└── notes/
    └── lab-12-notes.md                       NEW
```

The `Dockerfile` goes in `labs/lab-11-cicd/app/`, not in this lab's own directory. A Dockerfile
belongs with the source it packages; splitting them across two directories would mean the build
context is one directory and the instructions another, which works and is a bad habit.

---
## 8. Step-by-Step Implementation

### Step 1 - Start Floci, and read what Lab 11 left you

**Purpose**

Start the environment, and begin by reading the inventory the previous lab wrote rather than assuming
what is there. A lab that opens by assuming is a lab that fails in the middle.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/floci-storage-check.sh
./scripts/utilities/whoami.sh

if [ -f outputs/lab-11-lab08b-readiness.txt ]; then
  echo "--- Lab 11 readiness file ---"
  cat outputs/lab-11-lab08b-readiness.txt
else
  echo "no readiness file - you did not do Lab 11 Exercise 5."
  echo "That is fine: Step 14 of this lab writes imagedefinitions.json in full."
fi
```

**What the command does**

`outputs/lab-11-lab08b-readiness.txt` is what Lab 11 Exercise 5 asked you to leave behind: the
artifact key and the contents of the `imagedefinitions.json` your build produced. If it exists, Step 14
is a replacement of something you already wrote; if it does not, Step 14 is the first time you write
it. Either way the lab proceeds.

**Expected result**

```text
PASS=16  FAIL=0

  Account : 000000000000
  Arn     : arn:aws:iam::000000000000:root
  Endpoint: http://localhost:4566

--- Lab 11 readiness file ---
artifact: usms-enrolment-pipeline/BuildOutput/A1b2C3d.zip
imagedefinitions.json:
[ { "name": "enrolment-api", "imageUri": "public.ecr.aws/nginx/nginx:stable-alpine" } ]
```

> Example output - your key will differ, and the readiness file is absent if you skipped that exercise.

---

### Step 2 - Source every earlier lab's environment

**Purpose**

This lab reads from Lab 01, 04, 05 and 11, and it writes a file the CloudFormation lab will read.
Shell variables die with the terminal; the env files are the only thing that crosses one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
source configs/course.env

for f in configs/lab-01.env configs/lab-02.env configs/lab-03.env \
         configs/lab-04.env configs/lab-05.env configs/lab-06.env \
         configs/lab-09.env configs/lab-07.env configs/lab-08.env \
         configs/lab-10.env configs/lab-11.env; do
  if [ -f "$f" ]; then
    # shellcheck disable=SC1090
    source "$f"
    printf '  sourced  %s\n' "$f"
  else
    printf '  absent   %s\n' "$f"
  fi
done

printf 'cluster=%s service=%s container=%s pipeline=%s project=%s exec-role=%s\n' \
  "${USMS_ECS_CLUSTER:-MISSING}" "${USMS_ENROLMENT_SERVICE:-MISSING}" \
  "${USMS_ENROLMENT_CONTAINER:-MISSING}" "${USMS_PIPELINE_NAME:-MISSING}" \
  "${USMS_BUILD_PROJECT:-MISSING}" "${USMS_ECS_EXEC_ROLE_ARN:-MISSING}"
```

**What to look for:** no `MISSING`. In particular `USMS_ENROLMENT_CONTAINER` must be `enrolment-api`
and `USMS_PIPELINE_NAME` must be `usms-enrolment-pipeline`. Everything in this lab keys off those two
strings.

---

### Step 3 - Probe the deployment surface

**Purpose**

Lab 11 probed CodeBuild and CodePipeline. This lab depends on three more things: ECR, the ECS deploy
action, and - for Step 19 only - CodeDeploy. Find out now.

**Run from**

```text
aws-floci-course/
```

```bash
cat > scripts/utilities/deploy-support-probe.sh << 'EOF'
#!/usr/bin/env bash
# Determine which deployment path this Floci build supports. Read-only apart from
# one throwaway ECR repository, which it deletes.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"

PROBE_REPO="usms-probe-delete-me"
ok()  { printf '  ok   %s\n' "$1"; }
bad() { printf '  --   %s\n' "$1"; }

ECR_OK=no ; ECR_PUSHABLE=unknown ; ECS_OK=no ; DEPLOY_OK=no ; DOCKER_OK=no

echo "== Docker on this machine =="
if docker info >/dev/null 2>&1; then DOCKER_OK=yes; ok "docker daemon reachable"
else bad "docker daemon NOT reachable - this lab cannot build an image"; fi

echo "== ECR =="
if aws ecr describe-repositories >/dev/null 2>&1; then
  ECR_OK=yes; ok "ecr describe-repositories answers"
  if aws ecr create-repository --repository-name "$PROBE_REPO" >/dev/null 2>&1; then
    ok "ecr create-repository accepted"
    URI=$(aws ecr describe-repositories --repository-names "$PROBE_REPO" \
            --query 'repositories[0].repositoryUri' --output text 2>/dev/null)
    printf '       probe repositoryUri: %s\n' "${URI:-none}"
    case "$URI" in
      */*) ECR_PUSHABLE=probably ;;
      *)   ECR_PUSHABLE=no ;;
    esac
    aws ecr delete-repository --repository-name "$PROBE_REPO" --force >/dev/null 2>&1 \
      && ok "probe repository deleted" || bad "probe repository NOT deleted - remove $PROBE_REPO by hand"
  else
    bad "ecr create-repository rejected"
  fi
else
  bad "ecr describe-repositories does not answer"
fi

echo "== ECS =="
if aws ecs list-clusters >/dev/null 2>&1; then ECS_OK=yes; ok "ecs list-clusters answers"
else bad "ecs list-clusters does not answer"; fi

echo "== CodeDeploy (Step 19 only) =="
if aws deploy list-applications >/dev/null 2>&1; then DEPLOY_OK=yes; ok "codedeploy list-applications answers"
else bad "codedeploy list-applications does not answer - Step 19 is conceptual, as expected"; fi

echo
if [ "$DOCKER_OK" = yes ] && [ "$ECR_OK" = yes ] && [ "$ECS_OK" = yes ]; then
  P="A"
  echo "PATH A - build an image, push it to ECR, deploy it through the pipeline."
elif [ "$DOCKER_OK" = yes ] && [ "$ECS_OK" = yes ]; then
  P="B"
  echo "PATH B - no usable ECR. Build the image locally and keep it in the local"
  echo "         Docker daemon; Step 10's task definition names the local tag, and"
  echo "         Step 16's deploy stage is written and validated but not executed."
else
  P="C"
  echo "PATH C - no Docker or no ECS. Every document in this lab is still written"
  echo "         and validated. Section 12 says exactly what to claim."
fi
printf 'USMS_CICD_DEPLOY_PATH=%s\nUSMS_CODEDEPLOY_SUPPORTED=%s\n' "$P" "$DEPLOY_OK" \
  > outputs/lab-12-deploy-probe.txt
echo "recorded in outputs/lab-12-deploy-probe.txt"
EOF

chmod +x scripts/utilities/deploy-support-probe.sh
bash -n scripts/utilities/deploy-support-probe.sh && echo "syntax OK"
./scripts/utilities/deploy-support-probe.sh
```

**What the command does**

The ECR part does not stop at "the API answered". It creates a repository and reads back its
`repositoryUri`, because that URI is the thing a `docker push` actually needs, and a build that
returns a URI with no host part cannot be pushed to no matter what the API says. Then it deletes the
probe repository with `--force`, which is required for a repository containing images and harmless
for an empty one.

**Expected result**

```text
== Docker on this machine ==
  ok   docker daemon reachable
== ECR ==
  ok   ecr describe-repositories answers
  ok   ecr create-repository accepted
       probe repositoryUri: 000000000000.dkr.ecr.us-east-1.localhost.localstack.cloud:4566/usms-probe-delete-me
  ok   probe repository deleted
== ECS ==
  ok   ecs list-clusters answers
== CodeDeploy (Step 19 only) ==
  --   codedeploy list-applications does not answer - Step 19 is conceptual, as expected

PATH A - build an image, push it to ECR, deploy it through the pipeline.
recorded in outputs/lab-12-deploy-probe.txt
```

> Example output - the exact `repositoryUri` host differs between emulator builds, which is precisely
> why nothing in this lab hard-codes it.

**What to look for:** the `repositoryUri` line. Read it, and notice that it is not
`<account>.dkr.ecr.<region>.amazonaws.com` as it would be on real AWS. **Never type a registry host
into a command in this lab.** Every step derives it from `describe-repositories`.

**Checkpoint 1**

```text
outputs/lab-12-deploy-probe.txt
 ├── USMS_CICD_DEPLOY_PATH=<A|B|C>
 └── USMS_CODEDEPLOY_SUPPORTED=<yes|no>
```

---

### Step 4 - Publish the ECR port range

**Purpose**

Only port `4566` is published by the Compose file. Depending on the build, an ECR registry may be
served on its own port from the `5100-5104` range, and a `docker push` from your host cannot reach a
port that is not published. This is the one step in this lab that edits `docker-compose.yml`, and it
uncomments exactly one line.

!!! danger "Read before editing docker-compose.yml"
    **What will change:** one commented line in `docker-compose.yml` becomes active, publishing five
    host ports.

    **What depends on it:** nothing yet. `floci-up.sh` recreates the container to apply it, and a
    recreate is not a data loss - the bind mount and hybrid storage keep every resource you have built.

    **Reversible?** Yes. Re-comment the line and re-run `floci-up.sh`.

    **Effect on later labs:** none, except that five more host ports are occupied. Do **not** uncomment
    the other ranges; publishing roughly six hundred ports makes Docker Desktop crawl and collides on
    shared machines.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

grep -n '5100-5104' docker-compose.yml
```

**What to look for:** one line, currently commented, inside the `ports:` list. If `grep` prints
nothing, your compose file does not carry the range; add it by hand under `ports:` in the same style
as the `4566` line, and say so in your notes.

Now uncomment it. Either edit the file in your editor and delete the leading `#`, or use the guarded
substitution below, which only touches a line that mentions this one range:

```bash
cp docker-compose.yml "docker-compose.yml.bak-$(date +%Y%m%d%H%M%S)"

sed -i.tmp -E 's/^([[:space:]]*)#[[:space:]]*(- *"?5100-5104)/\1\2/' docker-compose.yml
rm -f docker-compose.yml.tmp

grep -n '5100-5104' docker-compose.yml
```

**What the command does**

`sed -i.tmp` is the portable in-place form - GNU `sed` accepts a bare `-i`, BSD `sed` on macOS does
not, and `-i.tmp` followed by `rm` works on both. The pattern captures the leading whitespace in `\1`
and the list item in `\2`, and writes them back without the `#` between them. The `cp` before it is
not decorative: this is the one file in the course that decides how Floci runs.

**Expected result**

```text
      - "5100-5104:5100-5104"
```

> Example output - the line must no longer begin with `#`.

**Verify**

```bash
./scripts/setup/floci-up.sh
docker port floci
```

**What to look for:** `4566` and the `5100-5104` range in the published list. If `floci-up.sh` reports
that it recreated the container, that is expected and correct - the ports are part of the container's
definition and cannot be added to a running one.

Then confirm nothing was lost by the recreate:

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Name:serviceName,Status:status,Desired:desiredCount,TaskDef:taskDefinition}' \
  --output table
```

**What to look for:** the service is still `ACTIVE` with the task definition Lab 04 left. This is the
`create → perturb → read back` shape with the container recreate as the perturbation, and it is the
proof that hybrid storage is doing what Lab 01 claimed. If the service is gone, you are in memory
mode; stop and run `floci-storage-check.sh`.

---

### Step 5 - Create the ECR repository

**Purpose**

A place to put your image that is not a public registry. This is the repository that Lab 01's
`USMSECSTaskExecution` policy has been describing, in the abstract, since before it existed.

**Concept first - what a repository is, and what a tag is**

An ECR **repository** holds the images for one thing. `usms-enrolment` will hold every build of the
enrolment service, distinguished by **tag** - `r6`, `r7`, and so on.

A tag is a label, and by default it is **mutable**: pushing a different image with the tag `r6`
silently moves `r6` to the new bytes. The image's **digest** - `sha256:...` - is derived from the
content and cannot be moved.

That difference is the whole of Step 9 and half of Section 15's questions. `IMMUTABLE` tag mutability
makes ECR reject a second push to an existing tag. This lab uses `MUTABLE`, deliberately, so that
Step 18's rollback drill can demonstrate what goes wrong; Exercise 2 asks you to argue for the other
choice.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
ECR_REPO="usms-enrolment"

aws ecr create-repository \
  --repository-name "$ECR_REPO" \
  --image-tag-mutability MUTABLE \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256 \
  --tags Key=Project,Value=USMS Key=Tier,Value=app Key=Lab,Value=12 \
  --query 'repository.{Name:repositoryName,Uri:repositoryUri,Mutability:imageTagMutability}' \
  --output table
```

**What the command does**

```text
aws
 └── ecr                                the SERVICE (Elastic Container Registry)
      └── create-repository             the OPERATION
           ├── --image-tag-mutability   MUTABLE lets a tag be moved; IMMUTABLE does not
           ├── --image-scanning-configuration  scan each pushed image for known CVEs
           └── --encryption-configuration      AES256 is the default; KMS is the alternative
```

`scanOnPush=true` asks ECR to scan every pushed image against a vulnerability database. On real AWS
this is genuinely useful and nearly free. On this emulator it is almost certainly stored and not
performed, which Section 12 records.

**Expected result**

```text
-----------------------------------------------------------------------------------
|                                CreateRepository                                 |
+-------------+-------------------------------------------------------+-----------+
| Mutability  |                          Uri                          |   Name    |
+-------------+-------------------------------------------------------+-----------+
|  MUTABLE    | 000000000000.dkr.ecr.us-east-1.localhost...:4566/usms-enrolment | usms-enrolment |
+-------------+-------------------------------------------------------+-----------+
```

> Example output - the table's column layout depends on your terminal width, and the host part of the
> URI differs between emulator builds.

**Verify**

```bash
ECR_URI=$(aws ecr describe-repositories --repository-names "$ECR_REPO" \
  --query 'repositories[0].repositoryUri' --output text)
ECR_REGISTRY="${ECR_URI%%/*}"

printf 'repository uri : %s\nregistry host  : %s\n' "$ECR_URI" "$ECR_REGISTRY"
```

**What the command does**

`${ECR_URI%%/*}` is shell parameter expansion: remove the longest match of `/*` from the end, leaving
everything before the first slash - the registry host. This is how every later step gets the host, and
it is why none of them contains a hard-coded hostname.

**What to look for:** two lines, the second a host and port with no path. If `ECR_REGISTRY` equals
`ECR_URI`, the URI has no slash in it and your build is not returning a pushable URI - that is Path B
from Step 3, and Step 8 tells you what to do instead.

---

### Step 6 - Authenticate Docker against the registry

**Purpose**

`docker push` needs credentials for the registry. ECR issues a short-lived token; you exchange your
AWS credentials for it and hand it to Docker.

**Concept first - what `get-login-password` actually returns**

A password, valid for twelve hours, for the username `AWS`. It is a credential, so it goes into
`docker login` through **standard input** and never onto the command line - arguments are visible in
`ps` output and in your shell history, and this course has been redirecting credentials straight into
`outputs/` since Lab 01 for the same reason.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws ecr get-login-password --region "$AWS_REGION_COURSE" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
```

**What the command does**

The pipe is the point. Nothing writes the token to a file, nothing echoes it, and it does not appear
in `history`. Docker stores a reference to it in `~/.docker/config.json`; on a shared machine that
file is worth knowing about.

**Expected result**

```text
Login Succeeded
```

> Example output - a warning about a stored, unencrypted credential is normal and is Docker telling
> you the truth about `~/.docker/config.json`.

!!! note "Floci Limitation - the registry may not speak TLS"
    Real ECR is HTTPS only. An emulated registry on `localhost` may serve plain HTTP, and Docker
    refuses plain HTTP registries unless they are configured as insecure.

    If `docker login` fails with `http: server gave HTTP response to HTTPS client`, add the registry
    host to Docker's `insecure-registries` list - in Docker Desktop, Settings, Docker Engine, as a
    JSON array entry - and restart Docker. On Linux the same key goes in `/etc/docker/daemon.json`.

    This is a local-development accommodation and nothing else. Never add a real registry to that
    list; an insecure registry is one a network attacker can substitute images in.

**Checkpoint 2**

```text
ECR
 └── usms-enrolment
      ├── MUTABLE tags, scanOnPush=true, AES256
      ├── repositoryUri read from the API, never typed
      └── docker login succeeded against the registry host
```

---

### Step 7 - Write the Dockerfile

**Purpose**

Turn the build output into an image. The Dockerfile is deliberately four lines, because everything
interesting about this lab is what happens to the image afterwards.

**Concept first - the build context, and why `dist/` is what gets copied**

`docker build .` sends the whole of `.` - the **build context** - to the daemon, and the Dockerfile
can only copy from inside it. The buildspec has already produced `dist/`, containing the substituted
`index.html`, the health file, `build-metadata.json` and `service.json`. That directory, and not the
source tree, is what belongs in the image: the image should contain the built output, not the build
inputs, the tests, or the buildspec that produced it.

`.dockerignore` enforces that from the other side, and also keeps the context small - a context that
includes `.git` on a real repository can be hundreds of megabytes sent over a socket for nothing.

**Run from**

```text
aws-floci-course/labs/lab-11-cicd/app/
```

**Command**

```bash
cd ~/aws-floci-course/labs/lab-11-cicd/app

cat > Dockerfile << 'EOF'
# The USMS enrolment service: a static portal served by nginx.
# The build context must already contain dist/, produced by buildspec.yml's build phase.
FROM nginx:1.27-alpine

# Copy the BUILT output, not the source tree.
COPY dist/ /usr/share/nginx/html/

# Lab 04's task definition health check fetches http://localhost/ and Lab 05's
# target group health check fetches / on the traffic port. Both need port 80.
EXPOSE 80

# nginx:alpine's own entrypoint already runs nginx in the foreground.
EOF

cat > .dockerignore << 'EOF'
.git
.gitignore
Dockerfile
.dockerignore
buildspec.yml
tests/
src/
config/
VERSION
*.bak
EOF

echo "--- Dockerfile ---"; cat Dockerfile
```

**What the command does**

`FROM nginx:1.27-alpine` is the same base Lab 07 used, for a practical reason: since you built
Labs 07-08 (EKS), your Docker daemon already has it cached and the build is instant. The alternative,
`public.ecr.aws/nginx/nginx:stable-alpine`, is what Lab 04's placeholder task definition names; either
works, and Exercise 1 asks you to try the other.

Note that `.dockerignore` excludes `src/` and `config/` while `COPY dist/` copies their processed
output. That is not a contradiction - it is the distinction between what a build consumes and what an
image ships, and getting it right is why the image is about 8 MB rather than including a test script
and a build specification that a running container has no use for.

**Verify**

```bash
cd ~/aws-floci-course
ls -l labs/lab-11-cicd/app/Dockerfile labs/lab-11-cicd/app/.dockerignore
test -d labs/lab-11-cicd/app/dist && echo "dist/ present - Step 8 can build" \
  || ./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app >/dev/null \
     && echo "dist/ rebuilt by the local runner"
```

**What to look for:** both files exist, and `dist/` is present. If the local runner had to rebuild it,
that is fine - it is the same runner from Lab 11 Step 14, and it is now doing exactly the job it was
written for.

---
### Step 8 - Build the image and push it, by hand

**Purpose**

Prove the image path works before asking a pipeline to walk it. If `docker build` or `docker push`
fails, you want to see that failure in your own terminal, not as a red stage in a system you have not
finished building.

**Concept first - three names for one thing**

```text
  usms-enrolment:r6                                   a local name
  000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r6     the pushable name
  sha256:8f3a91c4...                                  the digest - the content's identity
```

`docker tag` adds a name to an image that already exists; it copies nothing. `docker push` needs the
name to include the registry host, which is why the second form exists. The digest is not a name you
choose - it falls out of the content, and it is the only one of the three that cannot lie to you.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, set the release and rebuild the output**

```bash
cd ~/aws-floci-course

printf 'r6\n' > labs/lab-11-cicd/app/VERSION
./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app | tail -12

IMAGE_TAG=$(tr -d '[:space:]' < labs/lab-11-cicd/app/VERSION)
echo "image tag will be: $IMAGE_TAG"
```

**What to look for:** the smoke tests pass and `build-metadata.json` says `"release": "r6"`. The image
you are about to build contains that file, which is how, later, you can open a running container and
ask it which build it came from.

**Command - part 2, build, tag, push**

```bash
cd labs/lab-11-cicd/app

docker build -t "usms-enrolment:$IMAGE_TAG" .

docker tag "usms-enrolment:$IMAGE_TAG" "$ECR_URI:$IMAGE_TAG"

docker push "$ECR_URI:$IMAGE_TAG"

cd ~/aws-floci-course
```

**What the command does**

Three commands, three distinct operations, and the middle one is the one people skip and then cannot
explain. `docker build -t name:tag .` builds from the context `.`; `docker tag` gives the result a
second name that includes the registry; `docker push` uploads the layers under that name. Nothing is
uploaded by `build` and nothing is built by `push`.

**Expected result**

```text
[+] Building 2.4s (8/8) FINISHED
 => [internal] load build definition from Dockerfile
 => [internal] load .dockerignore
 => [1/2] FROM docker.io/library/nginx:1.27-alpine
 => [2/2] COPY dist/ /usr/share/nginx/html/
 => exporting to image
 => => writing image sha256:8f3a91c4...
 => => naming to docker.io/library/usms-enrolment:r6

The push refers to repository [000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment]
0a1b2c3d4e5f: Pushed
...
r6: digest: sha256:1c92f0ab... size: 1571
```

> Example output - your digests, layer IDs and timings will differ.

**What to look for:** the last line, which gives the **digest of the pushed image**. Note that it is
not the same value as the `writing image sha256:` line from the build: the build reports the image
config digest, the push reports the manifest digest, and the manifest digest is the one ECR indexes
and the one a task definition can pin. Those two being different surprises everybody once.

!!! note "Floci Limitation - push may not be supported at all"
    Some builds provide the ECR control plane - repositories, tags, policies - with no registry data
    plane behind it. `docker push` then fails with a connection error or a 404 from the registry API.

    On real AWS, ECR is a full OCI registry.

    If push fails: you are on Path B. Keep the image in your **local** Docker daemon under the name
    `usms-enrolment:r6`, use that name in Step 10's task definition, and record that the image was
    never in a registry. Everything from Step 12 onward still runs; what changes is that the image
    reference in `imagedefinitions.json` names a local image, which real ECS could not pull. Say that
    plainly in your report - it is a much better answer than pretending.

---

### Step 9 - Prove the image is in the registry

**Purpose**

`docker push` printing `Pushed` is a client reporting its own success. The read-back is the evidence.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws ecr describe-images \
  --repository-name usms-enrolment \
  --query 'imageDetails[].{Tags:imageTags,Digest:imageDigest,SizeMB:imageSizeInBytes,Pushed:imagePushedAt}' \
  --output table

IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name usms-enrolment \
  --image-ids "imageTag=$IMAGE_TAG" \
  --query 'imageDetails[0].imageDigest' --output text)

printf '%s %s %s\n' "$IMAGE_TAG" "$IMAGE_DIGEST" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | tee -a outputs/lab-12-image-digest.txt
```

**What the command does**

`describe-images` is the registry's own index. `--image-ids imageTag=r6` asks about one image by tag
and returns, among other things, its digest - the mapping from the mutable name to the immutable
content. Appending it to `outputs/lab-12-image-digest.txt` builds a small local ledger: tag, digest,
timestamp. Step 18 uses it, and Section 15 asks you what it is worth as evidence.

**Expected result**

```text
-------------------------------------------------------------------------------
|                               DescribeImages                                |
+------------------------+-----------+---------------------------+-----------+
|         Digest         |  Pushed   |          SizeMB           |   Tags    |
+------------------------+-----------+---------------------------+-----------+
| sha256:1c92f0ab...     | 2026-09-17T10:12:44+06:00 | 8724531   |  ['r6']   |
+------------------------+-----------+---------------------------+-----------+

r6 sha256:1c92f0ab... 2026-09-17T04:12:51Z
```

> Example output - your digest, size and timestamps will differ.

**Verify - the create, perturb, read back proof**

The perturbation here is deleting your local copy. If the image survives that and can be fetched back
**by digest**, it is genuinely in the registry and not merely in your laptop's cache.

!!! danger "Read before running any remove command"
    **What will be deleted:** the two local Docker image names, `usms-enrolment:r6` and the registry
    name pointing at the same layers. Nothing in ECR and nothing in AWS.

    **What depends on it:** nothing. The next command pulls it back.

    **Reversible?** Yes, by the pull immediately following - provided the push in Step 8 actually
    worked. On Path B, **skip this block**: your only copy of the image is the local one.

    **Effect on later labs:** none.

```bash
docker rmi "$ECR_URI:$IMAGE_TAG" "usms-enrolment:$IMAGE_TAG" 2>/dev/null || true
docker images | grep -c usms-enrolment || echo "no local copy remains"

docker pull "$ECR_URI@$IMAGE_DIGEST"
docker images --digests | grep usms-enrolment | head -3
```

**What to look for:** `no local copy remains`, then a successful pull. Note the `@` rather than `:` -
`repository@sha256:...` addresses an image by digest, and it is the only form that cannot be pointed
somewhere else after the fact. A production task definition that names a digest is deploying exactly
the bytes that were tested; one that names a tag is deploying whatever that tag points at when the
task starts.

**Checkpoint 3**

```text
ECR usms-enrolment
 └── r6   sha256:1c92f0ab...   pushed, deleted locally, pulled back by digest
outputs/lab-12-image-digest.txt
 └── one line: tag, digest, timestamp
```

---

### Step 10 - Register a task definition revision that names your image

**Purpose**

The service is still running `usms-enrolment:2`, whose container image is the placeholder. This step
produces revision 3, identical in every respect except the image - and produces it the way you should
always produce one: from the existing revision, not from a file somebody wrote from memory.

**Concept first - describe, strip, register**

`register-task-definition` takes a full task definition document. You almost never want to write one
from scratch for an existing family, because you will silently drop something - a log configuration, a
health check, a `runtimePlatform` - that nobody notices until the service degrades.

So: `describe-task-definition` gives you the current one; you remove the fields that AWS owns; you
change what you meant to change; you register the result. The read-only fields are
`taskDefinitionArn`, `revision`, `status`, `requiresAttributes`, `compatibilities`, `registeredAt`,
`registeredBy` and `deregisteredAt`. Leaving any of them in produces a validation error that names
one field at a time, which makes fixing it a game of whack-a-mole.

This is exactly what the ECS deploy action does for you in Step 16. Doing it by hand once is how you
know what it is doing.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

aws ecs describe-task-definition \
  --task-definition usms-enrolment \
  --query 'taskDefinition' --output json > templates/lab-12-taskdef-base.json

python3 - "$ECR_URI:$IMAGE_TAG" << 'PY'
import json, sys

new_image = sys.argv[1]
READ_ONLY = ("taskDefinitionArn", "revision", "status", "requiresAttributes",
             "compatibilities", "registeredAt", "registeredBy", "deregisteredAt")

td = json.load(open("templates/lab-12-taskdef-base.json"))
for field in READ_ONLY:
    td.pop(field, None)

found = False
for c in td["containerDefinitions"]:
    if c["name"] == "enrolment-api":
        print("old image:", c["image"])
        c["image"] = new_image
        print("new image:", c["image"])
        found = True
if not found:
    sys.exit("no container named enrolment-api in this task definition - stop and check Lab 04")

json.dump(td, open("templates/lab-12-taskdef-v3.json", "w"), indent=2)
print("wrote templates/lab-12-taskdef-v3.json")
PY

python3 -m json.tool templates/lab-12-taskdef-v3.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-12-taskdef-v3.json
```

**What the command does**

The Python is doing three things worth naming: it strips the read-only fields; it finds the container
**by name** rather than by position, because position is not a contract; and it fails loudly if that
name is absent instead of quietly writing a document that registers fine and deploys nothing.

The `grep -c '\$'` is the usual check for an unexpanded variable. The answer must be `0`.

**Expected result**

```text
old image: public.ecr.aws/nginx/nginx:stable-alpine
new image: 000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r6
wrote templates/lab-12-taskdef-v3.json
valid JSON
0
```

> Example output - the "old image" line is Lab 04's placeholder, and seeing it named here is the
> moment this course stops running somebody else's container.

**Command - register it**

```bash
TASK_DEF_ARN=$(aws ecs register-task-definition \
  --cli-input-json file://templates/lab-12-taskdef-v3.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)

echo "$TASK_DEF_ARN"
```

**Verify**

```bash
aws ecs describe-task-definition --task-definition usms-enrolment \
  --query 'taskDefinition.{Family:family,Revision:revision,Cpu:cpu,Memory:memory,Image:containerDefinitions[0].image,Health:containerDefinitions[0].healthCheck.command}' \
  --output json
```

**What to look for:** `Revision` is `3`, `Image` is your ECR URI with the `r6` tag, and - this is the
point of the describe-strip-register pattern - `Cpu` is still `256`, `Memory` is still `1024`, and the
health check command from Lab 04 Step 14 is still there. If any of those are missing, you wrote a
task definition instead of deriving one.

---

### Step 11 - Deploy revision 3 by hand, and watch it

**Purpose**

One more thing done manually before the pipeline does it, so that when the pipeline does it you
recognise what you are looking at. This is also the step where the enrolment service starts running
your application.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, a watcher you will reuse**

```bash
cat > scripts/utilities/usms-ecs-watch.sh << 'EOF'
#!/usr/bin/env bash
# Poll an ECS service's deployments until they settle, or until the attempts run out.
# Usage: usms-ecs-watch.sh [cluster] [service] [iterations]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
[ -f configs/lab-04.env ] && source configs/lab-04.env

CLUSTER="${1:-${USMS_ECS_CLUSTER:-usms-ecs-cluster}}"
SERVICE="${2:-${USMS_ENROLMENT_SERVICE:-usms-enrolment-svc}}"
ITER="${3:-20}"

for i in $(seq 1 "$ITER"); do
  printf '\n--- poll %s/%s ---\n' "$i" "$ITER"
  aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
    --query 'services[0].deployments[].{Status:status,TaskDef:taskDefinition,Desired:desiredCount,Running:runningCount,Pending:pendingCount,Rollout:rolloutState}' \
    --output table 2>/dev/null || echo "  describe-services failed"
  COUNT=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
            --query 'length(services[0].deployments)' --output text 2>/dev/null)
  PRIMARY_RUN=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
            --query 'services[0].deployments[?status==`PRIMARY`].runningCount | [0]' --output text 2>/dev/null)
  DESIRED=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
            --query 'services[0].desiredCount' --output text 2>/dev/null)
  if [ "${COUNT:-0}" = "1" ] && [ "${PRIMARY_RUN:-0}" = "${DESIRED:-x}" ]; then
    echo "  settled: one deployment, running == desired"
    exit 0
  fi
  sleep 10
done
echo "  did not settle within $ITER polls - read the table above, not this message"
exit 1
EOF

chmod +x scripts/utilities/usms-ecs-watch.sh
bash -n scripts/utilities/usms-ecs-watch.sh && echo "syntax OK"
```

**What the command does**

A polling loop rather than `aws ecs wait services-stable`, for the reason Lab 04 gave: on this
emulator the waiter can run until it exhausts its attempts without telling you what it saw. This
prints the deployment table on every poll, so a service that is stuck tells you *how* it is stuck. It
exits 0 when there is exactly one deployment and its running count equals the desired count, which is
what "settled" actually means.

**Command - part 2, deploy**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --task-definition usms-enrolment:3 \
  --query 'service.{Name:serviceName,TaskDef:taskDefinition,Desired:desiredCount}' \
  --output table

./scripts/utilities/usms-ecs-watch.sh || echo "did not settle - see the Floci note below"
```

**Expected result**

```text
--- poll 1/20 ---
---------------------------------------------------------------------------
|                             DescribeServices                            |
+----------+----------+---------+----------+-----------------------------+
| Desired  | Pending  | Running | Rollout  |           TaskDef           |
+----------+----------+---------+----------+-----------------------------+
|  2       |  2       |  0      |IN_PROGRESS| .../usms-enrolment:3        |
|  2       |  0       |  2      |COMPLETED  | .../usms-enrolment:2        |
+----------+----------+---------+----------+-----------------------------+
```

> Example output - two deployments during the overlap is the normal, healthy shape of a rolling ECS
> deployment.

**What to look for:** two rows during the rollout - the new `PRIMARY` coming up and the old `ACTIVE`
going down - collapsing to one row when it finishes. That overlap is `minimumHealthyPercent 100` and
`maximumPercent 200` from Lab 04 doing their job: never fewer than two healthy tasks, never more than
four.

!!! note "Floci Limitation - tasks that never reach RUNNING"
    Lab 04 Step 3 defined three support paths, and its Path B - a control plane with no task
    execution - is common. `runningCount` stays at 0 and the watcher never settles.

    On real AWS the tasks start, register with the target group, pass its health check, and the old
    deployment drains.

    If that is your build, the deployment *record* is still correct and checkable: `describe-services`
    shows the service now pointing at `usms-enrolment:3`. That is the thing this lab's verification
    checks, and it is the thing the pipeline's deploy action actually changes. Record the difference.

**Checkpoint 4**

```text
ECS service usms-enrolment-svc
 ├── task definition: usms-enrolment:3
 ├── image: <your ECR uri>:r6        (was public.ecr.aws/nginx/nginx:stable-alpine)
 └── deployments: 1 (PRIMARY) once settled
```

---

### Step 12 - Version 2 of `USMSCodeBuildBase`

**Purpose**

From Step 14 the build itself will push to ECR, so the build role needs permission to. This is also
the first time in the course that a customer-managed policy gets a second version, and the mechanics
have a trap in them.

**Concept first - a version is not a default**

`create-policy-version` adds a version. It does **not** make it active. Until you set it as the
default - either with `--set-as-default` on creation or with `set-default-policy-version` afterwards -
every principal carrying the policy is still evaluating v1.

A policy holds at most **five** versions. The sixth `create-policy-version` fails, and the fix is to
delete an old non-default version first. On a policy that changes often, that limit arrives sooner
than you expect.

Lab 01's `USMSDeveloperBase` is already on v2, so this is a pattern the course has used; this is the
first time you perform it.

**Concept first - why `ecr:GetAuthorizationToken` must be on `Resource: "*"`**

Every other ECR action here is scoped to the repository ARN. `GetAuthorizationToken` cannot be: it is
a registry-level operation, not a repository-level one, and there is no repository in its request to
scope against. A policy that scopes it to a repository ARN denies it, and the resulting failure is a
`docker login` error that mentions authentication and not IAM. It is a well-known piece of ECR trivia
and it is worth knowing before it costs you an hour.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > policies/usms-codebuild-policy-v2.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteItsOwnBuildLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:000000000000:log-group:/aws/codebuild/usms-enrolment-build",
        "arn:aws:logs:us-east-1:000000000000:log-group:/aws/codebuild/usms-enrolment-build:*"
      ]
    },
    {
      "Sid": "ReadSourceAndWriteArtifacts",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:GetBucketAcl",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::usms-pipeline-artifacts",
        "arn:aws:s3:::usms-pipeline-artifacts/*"
      ]
    },
    {
      "Sid": "GetARegistryTokenWhichCannotBeScoped",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PushAndPullTheEnrolmentImageOnly",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages"
      ],
      "Resource": "arn:aws:ecr:us-east-1:000000000000:repository/usms-enrolment"
    },
    {
      "Sid": "BuildsDoNotTouchStudentRecords",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::usms-student-data",
        "arn:aws:s3:::usms-student-data/*"
      ]
    }
  ]
}
EOF

python3 -m json.tool policies/usms-codebuild-policy-v2.json > /dev/null && echo "valid JSON"

aws iam create-policy-version \
  --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
  --policy-document file://policies/usms-codebuild-policy-v2.json \
  --set-as-default \
  --query 'PolicyVersion.{Version:VersionId,Default:IsDefaultVersion}' \
  --output table
```

**What the command does**

The document is v1 plus two statements. Note the five push actions in order - `BatchCheckLayer`,
`InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage` - which is literally the
sequence a `docker push` performs: ask which layers are already there, then upload the missing ones in
parts, then write the manifest. A policy missing any one of them fails a push partway through, and the
Docker error names the HTTP status rather than the action.

**Verify**

```bash
aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
  --query 'Policy.{Name:PolicyName,Default:DefaultVersionId,Versions:AttachmentCount}' --output table

aws iam list-policy-versions --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
  --query 'Versions[].{Version:VersionId,Default:IsDefaultVersion,Created:CreateDate}' --output table
```

**What to look for:** `DefaultVersionId` is `v2`, and the version list shows `v1` with
`Default: False`. If the default is still `v1`, you created a version without activating it - run
`aws iam set-default-policy-version --policy-arn ... --version-id v2`. That mistake is silent: the
policy looks updated in the console's JSON view if you happen to be looking at v2.

✏️ **Your turn**

Write the version 2 of `USMSCodePipelineBase` that Step 15 needs, before reading Step 15. It must add
exactly two capabilities to v1: the ECS calls a deploy action makes, and permission to pass the two
ECS roles to `ecs-tasks.amazonaws.com`. Do not create it yet - write the JSON to
`notes/lab-12-my-pipeline-policy.json` and compare it with Step 15's.

```text
Expected result:
A document with five statements. Two of them will not match Step 15 exactly, and
the interesting part of this exercise is which two and why.
```

---

### Step 13 - Let the build run Docker

**Purpose**

A CodeBuild container cannot run `docker build` unless the project says it may. This step turns that
on and gives the build the registry URI it will push to.

**Concept first - what `privilegedMode` actually does**

It runs the build container with the Docker daemon's socket available and elevated capabilities, so
that the build can start containers of its own. That is what "Docker in Docker" means here.

It is also a meaningful privilege. A build with `privilegedMode` can, in principle, reach the host's
Docker daemon and everything it can see. On a real account, that is a reason to care who can trigger
the build and what source it builds - which is the same reason the pipeline role's `StartBuild` is
scoped to one project ARN rather than `project/*`.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > templates/lab-12-codebuild-update.json << EOF
{
  "name": "usms-enrolment-build",
  "environment": {
    "type": "LINUX_CONTAINER",
    "image": "aws/codebuild/standard:7.0",
    "computeType": "BUILD_GENERAL1_SMALL",
    "privilegedMode": true,
    "environmentVariables": [
      { "name": "USMS_PROJECT",   "value": "USMS",           "type": "PLAINTEXT" },
      { "name": "USMS_SERVICE",   "value": "enrolment",      "type": "PLAINTEXT" },
      { "name": "IMAGE_REPO_URI", "value": "${ECR_URI}",     "type": "PLAINTEXT" },
      { "name": "AWS_REGION_COURSE", "value": "us-east-1",   "type": "PLAINTEXT" }
    ]
  }
}
EOF

python3 -m json.tool templates/lab-12-codebuild-update.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-12-codebuild-update.json

aws codebuild update-project \
  --cli-input-json file://templates/lab-12-codebuild-update.json \
  --query 'project.environment.{Privileged:privilegedMode,Vars:environmentVariables[].name}' \
  --output json
```

**What the command does**

`update-project` with `--cli-input-json` needs `name` plus only the members you are changing -
`environment` here - and leaves the source, artifacts, service role, timeout and tags as they were.
Note that `environment` is replaced **as a whole**: omitting `environmentVariables` would clear them,
and omitting `image` would fail validation. Another replace-only shape, in a smaller form than
`update-pipeline`.

The unquoted heredoc substitutes `${ECR_URI}`; the `grep -c '\$'` must print `0`.

**Expected result**

```text
valid JSON
0
{
    "Privileged": true,
    "Vars": [
        "USMS_PROJECT",
        "USMS_SERVICE",
        "IMAGE_REPO_URI",
        "AWS_REGION_COURSE"
    ]
}
```

> Example output.

**Verify**

```bash
aws codebuild batch-get-projects --names usms-enrolment-build \
  --query 'projects[0].{Source:source.type,Role:serviceRole,Privileged:environment.privilegedMode,Repo:environment.environmentVariables[?name==`IMAGE_REPO_URI`].value|[0]}' \
  --output table
```

**What to look for:** `Source` is still `CODEPIPELINE` - you did not undo Lab 11 Step 18 - `Role` is
still `usms-codebuild-role`, `Privileged` is `true`, and `Repo` is your ECR URI. All four matter; the
first is the one people break with an over-broad `update-project`.

**Checkpoint 5**

```text
IAM
 └── USMSCodeBuildBase  v2 is default   (logs, artifacts, ECR push, deny student data)

CodeBuild usms-enrolment-build
 ├── source CODEPIPELINE, artifacts CODEPIPELINE
 ├── privilegedMode true
 └── IMAGE_REPO_URI = <your ECR uri>
```

---
### Step 14 - Extend the buildspec: build the image, write `imagedefinitions.json`

**Purpose**

This is the step that makes the pipeline capable of deploying. Two additions: the build produces an
image, and the build produces the small JSON file that tells the deploy action which image to use.

**Concept first - `imagedefinitions.json`, exactly**

It is a JSON **array**. Each element has two fields:

```json
[
  {
    "name": "enrolment-api",
    "imageUri": "000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r7"
  }
]
```

`name` must equal the **container name** in the task definition - not the service, not the family, not
the repository. `imageUri` is the full pushable reference including the tag or digest.

Three ways this file goes wrong, all of which produce failures that do not mention the file:

- It is a JSON **object** rather than an array. The deploy action rejects it.
- `name` does not match a container in the task definition. The action reports that it could not find
  the container, in wording that varies.
- It is not at the **root** of the input artifact. This is why `artifacts.base-directory: dist` matters
  and why the build writes the file into `dist/` rather than beside the source.

**Concept first - why the image build is guarded**

The build container may or may not have a reachable Docker daemon, even with `privilegedMode` on, and
the registry may or may not be reachable from inside it. Rather than writing a buildspec that works
only on the happy path, the `build` phase checks `docker info` and skips the image build when there is
no daemon - always writing `imagedefinitions.json` either way, naming the tag that Step 8 already
pushed by hand.

That is not a workaround for the emulator. It is a real pattern: a build that degrades to "the image
must already exist at this reference" is a build you can reason about, and one that says so in its log
is a build you can debug.

**Run from**

```text
aws-floci-course/labs/lab-11-cicd/app/
```

**Command - part 1, the new buildspec**

```bash
cd ~/aws-floci-course/labs/lab-11-cicd/app

cp buildspec.yml buildspec.yml.lab08a

cat > buildspec.yml << 'BUILDSPEC'
version: 0.2

env:
  variables:
    SERVICE_NAME: "enrolment"
    ARTIFACT_DIR: "dist"
    IMAGE_REPO_URI: "nginx"

phases:

  install:
    commands:
      - echo "--- install ---"
      - python3 --version
      - docker --version || echo "no docker client in this build image"

  pre_build:
    commands:
      - echo "--- pre_build ---"
      - test -f VERSION || { echo "VERSION file is missing"; exit 1; }
      - python3 -m json.tool config/service.json > /dev/null
      - |
        grep -q '"container": "enrolment-api"' config/service.json || {
          echo "config/service.json names the wrong container"
          exit 1
        }
      - USMS_RELEASE="$(tr -d '[:space:]' < VERSION)"
      - echo "release is $USMS_RELEASE"
      - |
        if docker info >/dev/null 2>&1; then
          echo "docker daemon reachable - this build will build and push an image"
          aws ecr get-login-password --region "${AWS_REGION_COURSE:-us-east-1}" \
            | docker login --username AWS --password-stdin "${IMAGE_REPO_URI%%/*}" \
            || echo "docker login failed - continuing; the image must already exist"
        else
          echo "no docker daemon in this build container - skipping the image build"
          echo "the image must already exist at ${IMAGE_REPO_URI} with this release tag"
        fi

  build:
    commands:
      - echo "--- build ---"
      - USMS_RELEASE="$(tr -d '[:space:]' < VERSION)"
      - BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      - echo "release=$USMS_RELEASE builtAt=$BUILT_AT"
      - rm -rf "$ARTIFACT_DIR"
      - mkdir -p "$ARTIFACT_DIR"
      - cp -R src/. "$ARTIFACT_DIR"/
      - sed -i.bak -e "s|__RELEASE__|$USMS_RELEASE|g" -e "s|__BUILT_AT__|$BUILT_AT|g" "$ARTIFACT_DIR/index.html"
      - rm -f "$ARTIFACT_DIR/index.html.bak"
      - |
        cat > "$ARTIFACT_DIR/build-metadata.json" << META
        {
          "service": "$SERVICE_NAME",
          "release": "$USMS_RELEASE",
          "builtAt": "$BUILT_AT",
          "buildId": "${CODEBUILD_BUILD_ID:-local}",
          "sourceVersion": "${CODEBUILD_RESOLVED_SOURCE_VERSION:-local}",
          "imageUri": "${IMAGE_REPO_URI}:$USMS_RELEASE"
        }
        META
      - cp config/service.json "$ARTIFACT_DIR/service.json"
      - |
        if docker info >/dev/null 2>&1; then
          docker build -t "${IMAGE_REPO_URI}:$USMS_RELEASE" .
          docker push "${IMAGE_REPO_URI}:$USMS_RELEASE" \
            || echo "push failed - see Section 11; the deploy stage will use the existing tag"
        fi
      - |
        IMAGE_URI="${IMAGE_REPO_URI}:$USMS_RELEASE" python3 - > "$ARTIFACT_DIR/imagedefinitions.json" << 'IMGDEF'
        import json, os
        cfg = json.load(open("config/service.json"))
        print(json.dumps([{"name": cfg["container"],
                           "imageUri": os.environ["IMAGE_URI"]}], indent=2))
        IMGDEF

  post_build:
    commands:
      - echo "--- post_build ---"
      - bash tests/smoke.sh
      - cat "$ARTIFACT_DIR/imagedefinitions.json"
      - ls -l "$ARTIFACT_DIR"

artifacts:
  base-directory: dist
  files:
    - '**/*'

cache:
  paths: []
BUILDSPEC

echo "buildspec rewritten; the Lab 11 version is kept at buildspec.yml.lab08a"
```

**What the command does**

Four changes from the Lab 11 version, and one thing deliberately unchanged.

- `env.variables` gains `IMAGE_REPO_URI` with a **default** of `nginx`. The project's environment
  variable from Step 13 overrides it. The default exists so the local runner produces a sensible file
  rather than failing on an unset variable.
- `pre_build` resolves the release and, if Docker is available, logs in to the registry - deriving the
  host with `${IMAGE_REPO_URI%%/*}`, the same expansion as Step 5.
- `build` builds and pushes, guarded, and then always writes `imagedefinitions.json` by reading the
  container name out of `config/service.json`. The container name is read, never typed twice.
- `build-metadata.json` gains an `imageUri` field, so the artifact records which image it corresponds
  to. That single field is what turns a pile of artifacts into an audit trail.

Unchanged: `artifacts.base-directory: dist`. The new file must land at the artifact root, and this is
the line that puts it there.

Note the nested heredocs again, and their quoting: the outer `<< 'BUILDSPEC'` is quoted so every `$`
reaches the file; the inner `<< META` is unquoted because those variables must expand at build time;
the inner `<< 'IMGDEF'` is **quoted** because that Python source must reach the interpreter exactly as
written - which is why the image URI is passed in through the environment rather than interpolated
into the program text. Building a program by string substitution is how injection bugs are born, and
the habit of passing data through the environment instead is worth having even for a two-line script.

**Command - part 2, the eighth smoke test**

```bash
python3 - << 'PY'
path = "tests/smoke.sh"
src = open(path).read()
if "imagedefinitions" in src:
    print("already present - nothing to do")
else:
    marker = 't "container name matches the task def"'
    line = ('t "imagedefinitions.json is a one-element array" '
            '"python3 -c \\"import json,sys; d=json.load(open(\'dist/imagedefinitions.json\')); '
            'sys.exit(0 if isinstance(d,list) and len(d)==1 and d[0][\'name\']==\'enrolment-api\' else 1)\\""\n')
    i = src.index(marker)
    j = src.index("\n", i) + 1
    open(path, "w").write(src[:j] + line + src[j:])
    print("added the eighth assertion")
PY

bash -n tests/smoke.sh && echo "smoke.sh syntax OK"
```

**What the command does**

Inserts one more assertion after the container-name check. It does three things in one expression: the
file parses as JSON, it is a list of length one, and its single entry names `enrolment-api`. Those are
exactly the three ways the file goes wrong, from the concept note above.

**Verify - run it locally first**

```bash
cd ~/aws-floci-course

IMAGE_REPO_URI="$ECR_URI" ./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app | tail -25
```

**Expected result**

```text
=== phase: post_build ===
--- post_build ---
== smoke tests ==
  ok   dist/index.html exists
  ok   dist/healthz.html exists
  ok   release placeholder was replaced
  ok   build-time placeholder was replaced
  ok   health endpoint says ok
  ok   build metadata is valid JSON
  ok   container name matches the task def
  ok   imagedefinitions.json is a one-element array
smoke tests failed: 0
[
  {
    "name": "enrolment-api",
    "imageUri": "000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r6"
  }
]
=== all phases completed ===
--- local build exit status: 0 ---
```

> Example output - eight assertions now, and the image URI is whatever your registry reported.

**What to look for:** eight `ok` lines, and an `imageUri` containing your registry host. If `imageUri`
reads `nginx:r6`, the `IMAGE_REPO_URI` you set on the command line did not reach the runner.

!!! info "Why the variable on the command line wins"
    The runner generates `export IMAGE_REPO_URI="${IMAGE_REPO_URI:-nginx}"` from the buildspec's
    `env.variables`, so a value already in your environment overrides the default rather than being
    overwritten by it. That is deliberate, and it mirrors CodeBuild: a **project-level** environment
    variable - the one Step 13 set on `usms-enrolment-build` - wins over an `env.variables` default in
    the buildspec.

    The default exists so that the buildspec is runnable with no configuration at all. It is not the
    value you want deployed, which is why `imagedefinitions.json` is worth reading before you believe a
    green pipeline.

**Command - part 3, ship it**

```bash
./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip | tail -3

aws s3api put-object \
  --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip \
  --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text
```

**What to look for:** a new version ID. Do **not** start the pipeline yet - its Build stage would
succeed and its (still absent) Deploy stage would not exist, so the run would tell you nothing. Step 16
adds the stage; Step 17 runs it.

**Checkpoint 6**

```text
labs/lab-11-cicd/app/
 ├── Dockerfile              FROM nginx:1.27-alpine, COPY dist/
 ├── .dockerignore
 ├── buildspec.yml           builds and pushes an image; writes imagedefinitions.json
 ├── buildspec.yml.lab08a    the previous version, kept for comparison
 └── tests/smoke.sh          8 assertions
```

---

### Step 15 - Version 2 of `USMSCodePipelineBase`

**Purpose**

The deploy action runs as the **pipeline** role, not the build role. It needs to read the service, read
and register task definitions, update the service - and pass the two ECS roles, because registering a
task definition that names an execution role and a task role is a role handoff exactly like the one
Lab 11 Step 15 discussed.

**Concept first - the second `PassRole`, and why it is not the same one**

Lab 11's v1 passes `usms-codebuild-role` to `codebuild.amazonaws.com`. That is the pipeline handing a
role to the build service.

`register-task-definition` names `executionRoleArn` and `taskRoleArn`. Whoever registers it is handing
those two roles to ECS. Without `iam:PassRole` on them, `RegisterTaskDefinition` is refused - and the
error names `iam:PassRole`, not the ECS call, which confuses people who have not met this before.

The receiving service is `ecs-tasks.amazonaws.com`, not `ecs.amazonaws.com`. That distinction is real:
`ecs-tasks` is the principal that tasks run as, and it is the value Lab 04 used in
`policies/trust-ecs-tasks.json`. Getting it wrong produces a condition that never matches and a
`PassRole` that never applies.

Compare your `notes/lab-12-my-pipeline-policy.json` from Step 12's "Your turn" with what follows.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

cat > policies/usms-codepipeline-policy-v2.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAndWriteTheArtifactStore",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:GetBucketVersioning",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::usms-pipeline-artifacts",
        "arn:aws:s3:::usms-pipeline-artifacts/*"
      ]
    },
    {
      "Sid": "StartAndWatchTheEnrolmentBuildOnly",
      "Effect": "Allow",
      "Action": [
        "codebuild:StartBuild",
        "codebuild:BatchGetBuilds",
        "codebuild:StopBuild"
      ],
      "Resource": "arn:aws:codebuild:us-east-1:000000000000:project/usms-enrolment-build"
    },
    {
      "Sid": "PassTheBuildRoleAndOnlyToCodeBuild",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::000000000000:role/usms-codebuild-role",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "codebuild.amazonaws.com" }
      }
    },
    {
      "Sid": "DeployToTheEnrolmentServiceOnly",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeServices",
        "ecs:UpdateService"
      ],
      "Resource": "arn:aws:ecs:us-east-1:000000000000:service/usms-ecs-cluster/usms-enrolment-svc"
    },
    {
      "Sid": "ReadAndRegisterTaskDefinitions",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition",
        "ecs:ListTaskDefinitions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassTheTwoEcsRolesAndOnlyToEcsTasks",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::000000000000:role/usms-ecs-exec-role",
        "arn:aws:iam::000000000000:role/usms-ecs-task-role"
      ],
      "Condition": {
        "StringEquals": { "iam:PassedToService": "ecs-tasks.amazonaws.com" }
      }
    }
  ]
}
EOF

python3 -m json.tool policies/usms-codepipeline-policy-v2.json > /dev/null && echo "valid JSON"

aws iam create-policy-version \
  --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
  --policy-document file://policies/usms-codepipeline-policy-v2.json \
  --set-as-default \
  --query 'PolicyVersion.{Version:VersionId,Default:IsDefaultVersion}' \
  --output table
```

**What the command does**

Six statements. Three are unchanged from v1. The three new ones are worth reading individually:

- `DeployToTheEnrolmentServiceOnly` names **one service ARN**. The pipeline can update the enrolment
  service and no other service in the cluster.
- `ReadAndRegisterTaskDefinitions` is on `Resource: "*"`, and that is not laziness.
  `RegisterTaskDefinition` creates a resource that does not exist yet, so there is no ARN to scope it
  to - the same shape as `ecr:GetAuthorizationToken` in Step 12. What bounds the damage is the
  `PassRole` statement below it: a task definition can only be registered naming roles you may pass.
  Exercise 4 asks you to argue about whether that is sufficient.
- `PassTheTwoEcsRolesAndOnlyToEcsTasks` names exactly the two roles Lab 01 created and the service that
  may receive them.

**Verify**

```bash
aws iam get-policy-version \
  --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
  --version-id v2 \
  --query 'PolicyVersion.Document.Statement[].Sid' --output json

aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
  --query 'Policy.DefaultVersionId' --output text
```

**What to look for:** six Sids, and `v2` as the default. If the default is `v1`, run
`aws iam set-default-policy-version --policy-arn ... --version-id v2`.

---

### Step 16 - Add the Deploy stage

**Purpose**

Turn a two-stage pipeline into a three-stage one. This is the step with the replace-only API in it, and
it is the step where careless work destroys something.

!!! danger "Read before running update-pipeline"
    **What will be replaced:** the entire pipeline document. `update-pipeline` has no merge semantics
    and no partial update. Whatever you send becomes the pipeline.

    **What depends on it:** both stages you built in Lab 11. If you send a document containing only
    the Deploy stage, Source and Build are deleted - with a successful API response and no warning.

    **Reversible?** Only by rebuilding the document from Lab 11's `templates/lab-11-pipeline.json`,
    which is why that file is committed.

    **Effect on later labs:** the CloudFormation lab re-declares this pipeline and compares it with
    what you built by hand. A pipeline missing two stages makes that comparison meaningless.

**Concept first - get, modify, put**

```text
   get-pipeline  ──>  { "pipeline": {...}, "metadata": {...} }
                          │              └── created/updated timestamps and ARN - NOT sent back
                          │
                       modify: append one stage to pipeline.stages
                          │
   update-pipeline <── { "pipeline": {...} }
```

The `metadata` object comes back from `get-pipeline` and must not be sent to `update-pipeline`. Taking
`--query 'pipeline'` at the read step is what keeps it out.

This is the same category as `put-bucket-notification-configuration` in Lab 10, and the same category
as `update-assume-role-policy` in Lab 09. Replace-only APIs are a family; recognising the family is
worth more than remembering any one member.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, read the current document**

```bash
aws codepipeline get-pipeline --name usms-enrolment-pipeline \
  --query 'pipeline' --output json > templates/lab-12-pipeline-current.json

python3 -m json.tool templates/lab-12-pipeline-current.json > /dev/null && echo "valid JSON"

python3 -c "
import json
p = json.load(open('templates/lab-12-pipeline-current.json'))
print('name  :', p['name'])
print('stages:', [s['name'] for s in p['stages']])
"
```

**Expected result**

```text
valid JSON
name  : usms-enrolment-pipeline
stages: ['Source', 'Build']
```

> Example output.

**What to look for:** two stages. If you see three, you have already run this step; skip to the verify.
If you see one, something has already gone wrong - restore from
`templates/lab-11-pipeline.json` before continuing.

**Command - part 2, the surgery**

```bash
python3 - << 'PY'
import json

CURRENT = "templates/lab-12-pipeline-current.json"
OUT     = "templates/lab-12-pipeline.json"

pipeline = json.load(open(CURRENT))

names = [s["name"] for s in pipeline["stages"]]
assert names[:2] == ["Source", "Build"], f"unexpected stages: {names}"
if "Deploy" in names:
    raise SystemExit("a Deploy stage already exists - nothing to do")

deploy_stage = {
    "name": "Deploy",
    "actions": [
        {
            "name": "DeployToECS",
            "actionTypeId": {
                "category": "Deploy",
                "owner": "AWS",
                "provider": "ECS",
                "version": "1"
            },
            "runOrder": 1,
            "configuration": {
                "ClusterName": "usms-ecs-cluster",
                "ServiceName": "usms-enrolment-svc",
                "FileName": "imagedefinitions.json",
                "DeploymentTimeout": "10"
            },
            "inputArtifacts": [{"name": "BuildOutput"}],
            "outputArtifacts": []
        }
    ]
}

pipeline["stages"].append(deploy_stage)
json.dump({"pipeline": pipeline}, open(OUT, "w"), indent=2)

print("stages now:", [s["name"] for s in pipeline["stages"]])
print("wrote", OUT)
PY

python3 -m json.tool templates/lab-12-pipeline.json > /dev/null && echo "valid JSON"
grep -c '\$' templates/lab-12-pipeline.json
```

**What the command does**

The two `assert`/`raise` lines are the interesting part. The script refuses to run against a pipeline
whose first two stages are not the ones it expects, and refuses to add a second Deploy stage. A
script that edits a replace-only resource should be paranoid about what it is editing; this one costs
three lines to make idempotent and safe.

`DeploymentTimeout` is in **minutes**, as a string like every other value in `configuration`. Ten
minutes is generous for two Fargate tasks and short enough that a stuck deployment fails the stage
rather than hanging the pipeline.

**Expected result**

```text
stages now: ['Source', 'Build', 'Deploy']
wrote templates/lab-12-pipeline.json
valid JSON
0
```

> Example output.

**Command - part 3, put it back**

```bash
aws codepipeline update-pipeline \
  --cli-input-json file://templates/lab-12-pipeline.json \
  --query 'pipeline.{Name:name,Stages:length(stages),Version:version}' \
  --output table
```

**Verify**

```bash
aws codepipeline get-pipeline --name usms-enrolment-pipeline \
  --query 'pipeline.stages[].{Stage:name,Action:actions[0].name,Provider:actions[0].actionTypeId.provider,Input:actions[0].inputArtifacts[0].name}' \
  --output table
```

**Expected result**

```text
---------------------------------------------------------------
|                         GetPipeline                         |
+---------------+---------------+-------------+---------------+
|    Action     |     Input     |  Provider   |    Stage      |
+---------------+---------------+-------------+---------------+
|  FetchSource  |  None         |  S3         |  Source       |
|  BuildArtifact|  SourceOutput |  CodeBuild  |  Build        |
|  DeployToECS  |  BuildOutput  |  ECS        |  Deploy       |
+---------------+---------------+-------------+---------------+
```

> Example output.

**What to look for:** three rows, and the chain of artifact names down the `Input` column - nothing,
then `SourceOutput`, then `BuildOutput`. That column is the pipeline's data flow, and reading it is how
you check a pipeline's wiring without reading the whole document.

✏️ **Your turn**

Without changing anything, work out from the pipeline document alone what would happen if the Deploy
action's `inputArtifacts` named `SourceOutput` instead of `BuildOutput`. Write the answer in
`notes/lab-12-notes.md`, naming the specific file that would be missing and the stage that would
report the failure.

```text
Expected result:
A precise answer: the action would look for imagedefinitions.json at the root of
the source archive, not find it, and fail in Deploy - not in Build, where the
mistake actually is.
```

**Checkpoint 7**

```text
usms-enrolment-pipeline
 ├── Source  S3         -> SourceOutput
 ├── Build   CodeBuild  -> BuildOutput
 └── Deploy  ECS        <- BuildOutput      cluster usms-ecs-cluster
                                            service usms-enrolment-svc
                                            file    imagedefinitions.json
```

---

### Step 17 - Run it end to end, and prove the service moved

**Purpose**

The moment the lab has been building towards. Change a version number; have a running service change,
with no `aws ecs update-service` typed by a human.

**Concept first - what you must read to know it worked**

A green Deploy stage is a report. The evidence is that the service's task definition **revision
number increased**, and that the new revision's image is the one the build produced. Those are two
separate facts and you should check both: a deploy action that ran but registered a revision with the
old image is a thing that can happen when `imagedefinitions.json` is stale.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the before**

```bash
BEFORE_TD=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].taskDefinition' --output text)
echo "before: $BEFORE_TD"
```

**What to look for:** `.../usms-enrolment:3` from Step 11. Write it down; the proof is a comparison and
you need both halves.

**Command - part 2, perturb and run**

```bash
printf 'r7\n' > labs/lab-11-cicd/app/VERSION

./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip >/dev/null

aws s3api put-object --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text

EXEC_ID=$(aws codepipeline start-pipeline-execution --name usms-enrolment-pipeline \
  --query 'pipelineExecutionId' --output text)
echo "execution: $EXEC_ID"

for i in $(seq 1 40); do
  aws codepipeline get-pipeline-state --name usms-enrolment-pipeline \
    --query 'stageStates[].[stageName,latestExecution.status]' --output text | sed 's/^/    /'
  STATE=$(aws codepipeline get-pipeline-execution \
            --pipeline-name usms-enrolment-pipeline --pipeline-execution-id "$EXEC_ID" \
            --query 'pipelineExecution.status' --output text 2>/dev/null)
  printf '  %2d  execution=%s\n' "$i" "${STATE:-unknown}"
  case "$STATE" in Succeeded|Failed|Stopped|Superseded) break ;; esac
  sleep 10
done
```

!!! warning "If your build cannot push, push first"
    On a build where CodeBuild has no Docker daemon, the build will write
    `imagedefinitions.json` naming `<registry>/usms-enrolment:r7` - an image that does not exist,
    because nothing pushed it. On real AWS the deployment would then fail with `CannotPullContainerError`.

    Before starting the execution, push the `r7` image by hand exactly as in Step 8:
    rebuild `dist/`, `docker build -t "$ECR_URI:r7" .`, `docker push "$ECR_URI:r7"`.
    The pipeline then deploys an image that is really there, and the only thing it did not do is build
    it. Record that distinction.

**Command - part 3, read back the three proofs**

```bash
AFTER_TD=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" --query 'services[0].taskDefinition' --output text)

AFTER_IMAGE=$(aws ecs describe-task-definition --task-definition "$AFTER_TD" \
  --query 'taskDefinition.containerDefinitions[?name==`enrolment-api`].image | [0]' --output text)

{
  printf 'execution      : %s\n' "$EXEC_ID"
  printf 'task def before: %s\n' "$BEFORE_TD"
  printf 'task def after : %s\n' "$AFTER_TD"
  printf 'image after    : %s\n' "$AFTER_IMAGE"
  printf 'recorded at    : %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} | tee outputs/lab-12-deploy-evidence.txt
```

**Expected result**

```text
execution      : 4b2c9e10-7a31-4d02-8c55-9f0e1b7d3a64
task def before: arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:3
task def after : arn:aws:ecs:us-east-1:000000000000:task-definition/usms-enrolment:4
image after    : 000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r7
recorded at    : 2026-09-17T11:04:22Z
```

> Example output - your execution ID, host and timestamps will differ.

**What to look for:** three things, and all three must hold.

1. **The revision increased**, from `:3` to `:4`. The deploy action registered a new revision; you did
   not.
2. **The image names `r7`**, the release you set two minutes ago. The chain from `VERSION` to a running
   service is intact.
3. **Everything else in revision 4 is unchanged.** Check it:

```bash
aws ecs describe-task-definition --task-definition "$AFTER_TD" \
  --query 'taskDefinition.{Rev:revision,Cpu:cpu,Mem:memory,Exec:executionRoleArn,Task:taskRoleArn,Log:containerDefinitions[0].logConfiguration.logDriver}' \
  --output table
```

`Cpu` 256, `Mem` 1024, both roles present, log driver `awslogs`. The deploy action copied all of it
from revision 3 and changed one field. That is the mechanism from Section 6, observed.

**Checkpoint 8**

```text
usms-enrolment-pipeline: Source -> Build -> Deploy, all Succeeded
ECS service usms-enrolment-svc
 ├── usms-enrolment:4    registered by the pipeline, not by you
 ├── image: <registry>/usms-enrolment:r7
 └── outputs/lab-12-deploy-evidence.txt written
```

---
### Step 18 - The rollback drill

**Purpose**

Every deployment mechanism is judged by what it does when the new version is wrong. This step deploys
a release whose image does not exist, watches what happens, and rolls back.

**Concept first - the deployment circuit breaker**

Lab 04 configured the service with
`deploymentCircuitBreaker: {enable: true, rollback: true}`. On real AWS that means: if enough tasks in
a new deployment fail to start or fail their health checks, ECS marks the deployment `FAILED`, stops
launching new tasks, and - because `rollback` is true - starts a fresh deployment using the last task
definition that reached a steady state.

Three things it does **not** do, and each has caught somebody:

- It does not notice an application that starts successfully and then behaves wrongly. It watches task
  start-up and health checks, nothing else.
- It does not roll back a deployment that has already completed. Once the old tasks are gone, the
  breaker's window has closed.
- It does not undo anything outside the service - a database migration the new version ran is still
  run.

The failure this drill produces - an image that cannot be pulled - is the clearest case: the task never
starts, and the breaker's purpose is exactly this.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, deploy a release whose image was never pushed**

```bash
cd ~/aws-floci-course

printf 'r8\n' > labs/lab-11-cicd/app/VERSION

./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip >/dev/null
aws s3api put-object --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text

aws ecr describe-images --repository-name usms-enrolment \
  --query 'imageDetails[].imageTags[]' --output text
```

**What to look for:** `r6` and `r7`, and **no `r8`**. That is the whole setup: the build will write
`imagedefinitions.json` naming `usms-enrolment:r8`, and nothing will have pushed it. If your build
*can* push, temporarily set the project's `IMAGE_REPO_URI` to a repository that does not exist, or
simply stop Docker for the duration - the point is a deploy whose image cannot be pulled.

```bash
BEFORE_ROLLBACK=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" --query 'services[0].taskDefinition' --output text)
echo "good revision, remember this: $BEFORE_ROLLBACK"

aws codepipeline start-pipeline-execution --name usms-enrolment-pipeline \
  --query 'pipelineExecutionId' --output text
```

**Command - part 2, watch it fail**

```bash
sleep 30

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].deployments[].{Status:status,TaskDef:taskDefinition,Desired:desiredCount,Running:runningCount,Rollout:rolloutState,Reason:rolloutStateReason}' \
  --output json

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].events[0:5].[createdAt,message]' --output text
```

**Expected result**

```text
[
    {
        "Status": "PRIMARY",
        "TaskDef": "arn:aws:ecs:...:task-definition/usms-enrolment:5",
        "Desired": 2,
        "Running": 0,
        "Rollout": "FAILED",
        "Reason": "ECS deployment circuit breaker: task failed to start."
    },
    {
        "Status": "ACTIVE",
        "TaskDef": "arn:aws:ecs:...:task-definition/usms-enrolment:4",
        "Desired": 2,
        "Running": 2,
        "Rollout": "COMPLETED",
        "Reason": "ECS deployment ecs-svc/... completed."
    }
]
```

> Example output - this is what real AWS shows. On this emulator the most likely result is a `PRIMARY`
> deployment at revision 5 with `runningCount` 0, no `rolloutState`, and no events at all.

!!! note "Floci Limitation - the circuit breaker is stored, not enforced"
    Lab 04 recorded that `deploymentConfiguration` - the percentages and the circuit breaker - is
    accepted and stored but not acted on. Nothing here launches a task, so nothing fails to start, so
    the breaker never fires.

    On real AWS the sequence is: tasks fail to pull the image, the service emits
    `CannotPullContainerError` events, the breaker trips after a threshold based on the desired count,
    the deployment is marked `FAILED`, and a rollback deployment to revision 4 starts automatically.

    What you can observe here is the part that matters most for the exercise: the service is now
    pointing at a revision whose image does not exist, and **nothing told you**. That is the real
    lesson. A deployment mechanism without a health signal is a mechanism that cannot roll back,
    whatever its configuration says.

**Command - part 3, roll back by hand**

```bash
aws ecs update-service \
  --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" \
  --task-definition "$BEFORE_ROLLBACK" \
  --query 'service.{Name:serviceName,TaskDef:taskDefinition}' \
  --output table

./scripts/utilities/usms-ecs-watch.sh || echo "did not settle - expected on a build that runs no tasks"

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].taskDefinition' --output text
```

**What to look for:** the service is back on revision 4. Note what rollback *is*: pointing the service
at a task definition that already exists. There is no special rollback API, no undo. This is why
revisions are never deleted and why a task definition family is an append-only log - the previous
revision is the rollback.

Now fix the source so the repository is not left in a state that deploys a missing image:

```bash
printf 'r7\n' > labs/lab-11-cicd/app/VERSION
./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip >/dev/null
aws s3api put-object --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text
```

✏️ **Your turn**

`usms-enrolment:5` still exists as a task definition revision, and it still names an image that does
not exist. Decide what to do about it, and justify the decision in `notes/lab-12-notes.md`.

```text
Expected result:
A decision and a reason. Deregistering it is defensible; leaving it is also
defensible. What is not defensible is not having noticed it exists. Your answer
should say how somebody would notice, six months from now, without being told.
```

**Checkpoint 9**

```text
Task definition family usms-enrolment
 ├── :1  placeholder image, Lab 04
 ├── :2  placeholder image + health check, Lab 04
 ├── :3  your image r6, registered by hand in Step 10
 ├── :4  your image r7, registered by the pipeline in Step 17
 └── :5  image r8 that was never pushed - the failed deployment
Service usms-enrolment-svc -> :4   (rolled back by hand)
```

---

### Step 19 - Blue/green with CodeDeploy, on paper

**Purpose**

The deploy action you built does a **rolling** deployment: new tasks come up alongside old ones inside
one service, and the target group holds both for a while. The alternative is **blue/green**, where the
new version runs as a separate task set, is tested on its own listener, and then receives production
traffic in one switch. This step writes the documents for it, reads them, and does not run them -
because this emulator has no CodeDeploy.

**Concept first - the four differences that matter**

| | Rolling (what you built) | Blue/green (CodeDeploy) |
| --- | --- | --- |
| Where the new version runs | Same service, tasks replaced gradually | A second task set in the same service |
| Traffic switch | Gradual, as tasks register and drain | One shift, all at once or in steps |
| Testing before production traffic | Not possible - a new task is live the moment it is healthy | A **test listener** on a second port serves only you |
| Rollback speed | Register the old revision, wait for tasks to start | Shift traffic back; the old task set is still running |
| Artifact contract | `imagedefinitions.json` | `imageDetail.json` plus an `appspec.yaml` |

That last row catches people. A blue/green ECS deployment does **not** use `imagedefinitions.json`. It
uses `imageDetail.json`, which is an object, not an array:

```json
{ "ImageURI": "000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r7" }
```

and an `appspec.yaml` that names the task definition, the container and the port.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

cat > templates/lab-12-appspec.yaml << 'EOF'
# CodeDeploy application specification for a blue/green ECS deployment.
# CONCEPTUAL in this course: Floci provides no CodeDeploy. This document is
# written, read and validated; it is not executed.
#
# <TASK_DEFINITION> is a placeholder CodeDeploy substitutes at deployment time
# with the revision the pipeline registered. It is one of the few places in AWS
# where a literal angle-bracket placeholder is correct rather than a mistake.
version: 0.0
Resources:
  - TargetService:
      Type: AWS::ECS::Service
      Properties:
        TaskDefinition: "<TASK_DEFINITION>"
        LoadBalancerInfo:
          ContainerName: "enrolment-api"
          ContainerPort: 80
        PlatformVersion: "LATEST"
Hooks:
  # Each hook names a Lambda function that returns Succeeded or Failed.
  # AfterAllowTestTraffic is the one that earns blue/green its keep: it runs
  # against the new task set through the TEST listener, before any production
  # traffic reaches it.
  - BeforeInstall: "usms-deploy-hook-before-install"
  - AfterInstall: "usms-deploy-hook-after-install"
  - AfterAllowTestTraffic: "usms-deploy-hook-smoke-test"
  - BeforeAllowTraffic: "usms-deploy-hook-before-traffic"
  - AfterAllowTraffic: "usms-deploy-hook-after-traffic"
EOF

cat > templates/lab-12-codedeploy-deployment-group.json << 'EOF'
{
  "applicationName": "usms-enrolment-app",
  "deploymentGroupName": "usms-enrolment-dg",
  "serviceRoleArn": "arn:aws:iam::000000000000:role/usms-codedeploy-role",
  "deploymentConfigName": "CodeDeployDefault.ECSLinear10PercentEvery1Minutes",
  "deploymentStyle": {
    "deploymentType": "BLUE_GREEN",
    "deploymentOption": "WITH_TRAFFIC_CONTROL"
  },
  "blueGreenDeploymentConfiguration": {
    "terminateBlueInstancesOnDeploymentSuccess": {
      "action": "TERMINATE",
      "terminationWaitTimeInMinutes": 5
    },
    "deploymentReadyOption": {
      "actionOnTimeout": "CONTINUE_DEPLOYMENT"
    }
  },
  "autoRollbackConfiguration": {
    "enabled": true,
    "events": ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  },
  "ecsServices": [
    {
      "clusterName": "usms-ecs-cluster",
      "serviceName": "usms-enrolment-svc"
    }
  ],
  "loadBalancerInfo": {
    "targetGroupPairInfoList": [
      {
        "targetGroups": [
          { "name": "usms-enrolment-tg" },
          { "name": "usms-enrolment-tg-green" }
        ],
        "prodTrafficRoute": {
          "listenerArns": ["<PROD_LISTENER_ARN>"]
        },
        "testTrafficRoute": {
          "listenerArns": ["<TEST_LISTENER_ARN>"]
        }
      }
    ]
  }
}
EOF

python3 -m json.tool templates/lab-12-codedeploy-deployment-group.json > /dev/null \
  && echo "deployment group document is valid JSON"

python3 - << 'PY'
try:
    import yaml
except ImportError:
    print("PyYAML absent - appspec not parsed; check the indentation by eye")
else:
    d = yaml.safe_load(open("templates/lab-12-appspec.yaml"))
    svc = d["Resources"][0]["TargetService"]["Properties"]
    print("appspec parses. container:", svc["LoadBalancerInfo"]["ContainerName"],
          "port:", svc["LoadBalancerInfo"]["ContainerPort"])
PY
```

**What the command does**

Writes two documents and validates both. Read them rather than skimming: the deployment group names
**two** target groups and **two** listeners, and that is the structural heart of blue/green. Lab 05
created one of each. A real blue/green setup for this service would need a second target group -
`usms-enrolment-tg-green` - and a second listener on a test port, which Exercise 3 asks you to create.

`CodeDeployDefault.ECSLinear10PercentEvery1Minutes` shifts ten percent of traffic each minute. The
alternatives are `ECSAllAtOnce` and the canary configurations. The choice is a business decision about
how much traffic you are prepared to expose to a bad release, expressed as a configuration name.

!!! note "Conceptual / Real AWS - CodeDeploy is absent"
    Your Step 3 probe almost certainly reported that `deploy list-applications` does not answer. Nothing
    in this step is executed.

    On real AWS you would additionally need: a second target group, a test listener, a
    `usms-codedeploy-role`, an application (`create-application --compute-platform ECS`), this
    deployment group, and - the part people miss - the ECS service recreated with
    `deploymentController.type = CODE_DEPLOY`.

    What you can honestly claim: you specified a blue/green deployment. Not that you performed one.

!!! danger "Read before changing a service's deployment controller"
    **What would be deleted:** the whole ECS service. `deploymentController` is immutable after
    creation; switching from `ECS` to `CODE_DEPLOY` requires deleting `usms-enrolment-svc` and creating
    it again.

    **What depends on it:** Lab 05's load-balancer registration, Lab 06's scalable target and its
    scaling policies, and every verification script from Lab 04 onward.

    **Reversible?** Only by recreating the service and re-attaching all of the above.

    **Effect on later labs:** severe. **Do not do this.** It is described so that you know the
    constraint exists, which is exactly the kind of thing that decides an architecture before a project
    starts.

**Checkpoint 10**

```text
templates/
 ├── lab-12-appspec.yaml                        validated, not executed
 └── lab-12-codedeploy-deployment-group.json    valid JSON, two target groups, two listeners
```

---

### Step 20 - Record this lab's outputs

**Purpose**

Write down what the next lab, the CloudFormation lab, and your own report will need. Shell variables
die with the terminal; `ECR_URI`, `IMAGE_DIGEST` and `EXEC_ID` are all about to.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

cat > configs/lab-12.env << EOF
# Lab 12 - CI/CD: the image, the registry, and the deploy stage
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, ARNs, tags and digests only. NO SECRETS. Safe to commit.

# --- registry ---
export USMS_ECR_REPO=usms-enrolment
export USMS_ECR_REPO_URI=$(aws ecr describe-repositories --repository-names usms-enrolment \
    --query 'repositories[0].repositoryUri' --output text 2>/dev/null || echo not-created)
export USMS_ECR_REGISTRY=$(aws ecr describe-repositories --repository-names usms-enrolment \
    --query 'repositories[0].repositoryUri' --output text 2>/dev/null | cut -d/ -f1 || echo not-created)
export USMS_ECR_TAG_MUTABILITY=$(aws ecr describe-repositories --repository-names usms-enrolment \
    --query 'repositories[0].imageTagMutability' --output text 2>/dev/null | grep -E '^[A-Z]+$' || echo not-created)
export USMS_ECR_SCAN_ON_PUSH=$(aws ecr describe-repositories --repository-names usms-enrolment \
    --query 'repositories[0].imageScanningConfiguration.scanOnPush' --output text 2>/dev/null | grep -Ei '^(true|false)$' || echo unknown)
export USMS_ECR_PORT_RANGE=5100-5104

# --- image ---
export USMS_IMAGE_TAG=r7
export USMS_IMAGE_DIGEST=$(aws ecr describe-images --repository-name usms-enrolment \
    --image-ids imageTag=r7 --query 'imageDetails[0].imageDigest' --output text 2>/dev/null \
    | grep -E '^sha256:' || echo not-pushed)
export USMS_IMAGEDEFS_FILE=imagedefinitions.json
export USMS_DOCKERFILE=labs/lab-11-cicd/app/Dockerfile

# --- task definition and service ---
export USMS_TASK_FAMILY=usms-enrolment
export USMS_TASK_REVISION_CICD=$(aws ecs describe-task-definition --task-definition usms-enrolment \
    --query 'taskDefinition.revision' --output text 2>/dev/null | grep -E '^[0-9]+$' || echo 0)
export USMS_TASK_DEF_ARN_CICD=$(aws ecs describe-task-definition --task-definition usms-enrolment \
    --query 'taskDefinition.taskDefinitionArn' --output text 2>/dev/null | grep -E '^arn:' || echo not-created)
export USMS_SERVICE_TASK_DEF=$(aws ecs describe-services --cluster usms-ecs-cluster \
    --services usms-enrolment-svc --query 'services[0].taskDefinition' --output text 2>/dev/null \
    | grep -E '^arn:' || echo not-created)
export USMS_ROLLBACK_REVISION=4

# --- pipeline deploy stage ---
export USMS_DEPLOY_STAGE=Deploy
export USMS_DEPLOY_ACTION=DeployToECS
export USMS_DEPLOY_PROVIDER=ECS
export USMS_PIPELINE_STAGES=$(aws codepipeline get-pipeline --name usms-enrolment-pipeline \
    --query 'length(pipeline.stages)' --output text 2>/dev/null | grep -E '^[0-9]+$' || echo 0)

# --- policy versions ---
export USMS_POLICY_CODEBUILD_VERSION=$(aws iam get-policy \
    --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
    --query 'Policy.DefaultVersionId' --output text 2>/dev/null | grep -E '^v[0-9]+$' || echo unknown)
export USMS_POLICY_CODEPIPELINE_VERSION=$(aws iam get-policy \
    --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
    --query 'Policy.DefaultVersionId' --output text 2>/dev/null | grep -E '^v[0-9]+$' || echo unknown)

# --- blue/green, conceptual ---
export USMS_CODEDEPLOY_SUPPORTED=$(sed -n 's/^USMS_CODEDEPLOY_SUPPORTED=//p' \
    outputs/lab-12-deploy-probe.txt 2>/dev/null || echo unknown)
export USMS_CODEDEPLOY_APP=usms-enrolment-app
export USMS_CODEDEPLOY_DG=usms-enrolment-dg
export USMS_APPSPEC_FILE=templates/lab-12-appspec.yaml
export USMS_CICD_DEPLOY_PATH=$(sed -n 's/^USMS_CICD_DEPLOY_PATH=//p' \
    outputs/lab-12-deploy-probe.txt 2>/dev/null || echo unknown)
EOF

grep -n 'export .*=$\|None' configs/lab-12.env || echo "all values populated"
grep -c '^export' configs/lab-12.env
```

**What the command does**

Unquoted heredoc, so every `$(...)` runs now. Each lookup ends in a `grep` filter and an `|| echo`
default, so a resource that genuinely does not exist on your path produces `not-created` or `unknown`
rather than `None` - the Lab 06 idiom, for the reason Lab 11 Step 21 gave.

`USMS_ECR_REGISTRY` uses `cut -d/ -f1` rather than the shell expansion `${...%%/*}`, because inside an
unquoted heredoc the expansion would be performed by your shell against a variable that does not exist
there. Two ways to take the host off a URI; the one that survives a heredoc is the one to use here.

**Expected result**

```text
all values populated
26
```

> Example output - on Path B several values read `not-created`, which is populated and correct.

**Verify**

```bash
source configs/lab-12.env
printf 'repo=%s\ntag=%s\ndigest=%s\nsvc-taskdef=%s\nstages=%s\ncb=%s cp=%s\npath=%s\n' \
  "$USMS_ECR_REPO_URI" "$USMS_IMAGE_TAG" "$USMS_IMAGE_DIGEST" "$USMS_SERVICE_TASK_DEF" \
  "$USMS_PIPELINE_STAGES" "$USMS_POLICY_CODEBUILD_VERSION" "$USMS_POLICY_CODEPIPELINE_VERSION" \
  "$USMS_CICD_DEPLOY_PATH"
```

**What to look for:** `stages=3`, both policy versions `v2`, and a `digest` beginning `sha256:` if you
are on Path A. Those four values are the compressed summary of this entire laboratory.

---

### Step 21 - Commit

**Purpose**

Everything this lab wrote that belongs in the repository goes in, and nothing that does not.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
git status --short
```

**What to look for:** read the list before staging. **No file under `outputs/` may appear**, and
neither may `docker-compose.yml.bak-*`. If the backup copy from Step 4 shows up, add it to
`.gitignore` rather than remembering not to commit it:

```bash
grep -q '^docker-compose.yml.bak-' .gitignore || \
  printf 'docker-compose.yml.bak-*\n' >> .gitignore
git check-ignore -v docker-compose.yml.bak-* 2>/dev/null | head -1
```

```bash
git add configs/lab-12.env \
        docker-compose.yml \
        labs/lab-11-cicd/app/Dockerfile \
        labs/lab-11-cicd/app/.dockerignore \
        labs/lab-11-cicd/app/buildspec.yml \
        labs/lab-11-cicd/app/buildspec.yml.lab08a \
        labs/lab-11-cicd/app/tests/smoke.sh \
        labs/lab-11-cicd/app/VERSION \
        labs/lab-12-cicd-deploy \
        policies/usms-codebuild-policy-v2.json \
        policies/usms-codepipeline-policy-v2.json \
        templates/lab-12-taskdef-v3.json \
        templates/lab-12-codebuild-update.json \
        templates/lab-12-pipeline.json \
        templates/lab-12-appspec.yaml \
        templates/lab-12-codedeploy-deployment-group.json \
        scripts/utilities/deploy-support-probe.sh \
        scripts/utilities/usms-ecs-watch.sh \
        .gitignore

git status --short
git commit -m "Lab 12: ECR repository, image build, deploy stage, rollback drill"
```

**What the command does**

Note that `docker-compose.yml` is staged. It changed in Step 4 and that change is part of the
environment contract now - an uncommitted change to the file that defines how Floci runs is how the
next person's environment differs from yours for reasons nobody can find.

`templates/lab-12-taskdef-base.json` and `templates/lab-12-pipeline-current.json` are deliberately
**not** staged: they are snapshots of live state at one moment, and committing them invites somebody to
apply a stale one later. Keep them on disk; leave them out of history.

---

## 9. Verification

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-12.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 12 artefact. Exit 1 if anything is missing.
# EXPECTED: PASS=45  FAIL=0        (Path A)
#           PASS=40  FAIL=5        (Path B  - no usable ECR: the five ECR checks)
#           PASS=31  FAIL=14       (Path C  - no CodeBuild/CodePipeline either: those
#                                   five plus two dependency checks, three project
#                                   checks and four pipeline checks)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
for f in configs/lab-01.env configs/lab-04.env configs/lab-05.env \
         configs/lab-11.env configs/lab-12.env; do
  # shellcheck disable=SC1090
  [ -f "$f" ] && source "$f"
done

: "${FLOCI_CONTAINER_NAME:=floci}"
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_PIPELINE_NAME:=usms-enrolment-pipeline}"
: "${USMS_BUILD_PROJECT:=usms-enrolment-build}"
: "${USMS_ECR_REPO:=usms-enrolment}"
: "${USMS_TASK_FAMILY:=usms-enrolment}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}
ecr()  { aws ecr describe-repositories --repository-names "$USMS_ECR_REPO" --query "repositories[0].$1" --output text; }
proj() { aws codebuild batch-get-projects --names "$USMS_BUILD_PROJECT" --query "projects[0].$1" --output text; }
pipe() { aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" --query "pipeline.$1" --output text; }
tdef() { aws ecs describe-task-definition --task-definition "$USMS_TASK_FAMILY" --query "taskDefinition.$1" --output text; }
polv() { aws iam get-policy --policy-arn "arn:aws:iam::000000000000:policy/$1" --query 'Policy.DefaultVersionId' --output text; }
spec="labs/lab-11-cicd/app/buildspec.yml"

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Lab 11 dependencies =="
check "configs/lab-11.env present"   "test -f configs/lab-11.env"
check "pipeline $USMS_PIPELINE_NAME exists" "pipe name | grep -q $USMS_PIPELINE_NAME"
check "build project exists"          "proj name | grep -q $USMS_BUILD_PROJECT"
check "ECS service exists" \
  "aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE --query 'services[0].status' --output text | grep -q ACTIVE"

echo "== ECR =="
check "repository $USMS_ECR_REPO exists"   "ecr repositoryName | grep -q $USMS_ECR_REPO"
check "scanOnPush is true"                 "ecr imageScanningConfiguration.scanOnPush | grep -qi true"
check "repositoryUri has a registry host"  "ecr repositoryUri | grep -q '/'"
check "at least one image is present" \
  "test \"\$(aws ecr describe-images --repository-name $USMS_ECR_REPO --query 'length(imageDetails)' --output text)\" -ge 1"
check "tag r7 is present" \
  "aws ecr describe-images --repository-name $USMS_ECR_REPO --image-ids imageTag=r7 --query 'imageDetails[0].imageDigest' --output text | grep -q '^sha256:'"

echo "== Source tree =="
check "Dockerfile present"                 "test -f labs/lab-11-cicd/app/Dockerfile"
check ".dockerignore present"              "test -f labs/lab-11-cicd/app/.dockerignore"
check "buildspec builds an image"          "grep -q 'docker build' $spec"
check "buildspec writes imagedefinitions"  "grep -q 'imagedefinitions.json' $spec"
check "smoke.sh has 8 assertions"          "test \"\$(grep -cE '^t \"' labs/lab-11-cicd/app/tests/smoke.sh)\" = 8"

echo "== Task definition and service =="
check "task family revision is at least 3" "test \"\$(tdef revision)\" -ge 3"
check "task definition names the ECR repo" "tdef 'containerDefinitions[0].image' | grep -q $USMS_ECR_REPO"
check "cpu is still 256"                   "test \"\$(tdef cpu)\" = 256"
check "memory is still 1024"               "test \"\$(tdef memory)\" = 1024"

echo "== IAM policy versions =="
check "USMSCodeBuildBase default is v2"       "test \"\$(polv USMSCodeBuildBase)\" = v2"
check "codebuild v2 grants ecr:PutImage"      "grep -q 'ecr:PutImage' policies/usms-codebuild-policy-v2.json"
check "GetAuthorizationToken is on Resource *" \
  "python3 -c \"import json;d=json.load(open('policies/usms-codebuild-policy-v2.json'));import sys;sys.exit(0 if any(s.get('Action')=='ecr:GetAuthorizationToken' and s.get('Resource')=='*' for s in d['Statement']) else 1)\""
check "USMSCodePipelineBase default is v2"    "test \"\$(polv USMSCodePipelineBase)\" = v2"
check "pipeline v2 grants ecs:UpdateService"  "grep -q 'ecs:UpdateService' policies/usms-codepipeline-policy-v2.json"
check "pipeline v2 passes roles to ecs-tasks" "grep -q 'ecs-tasks.amazonaws.com' policies/usms-codepipeline-policy-v2.json"

echo "== CodeBuild project =="
check "privilegedMode is true"     "proj environment.privilegedMode | grep -qi true"
check "IMAGE_REPO_URI is set" \
  "proj 'environment.environmentVariables[?name==\`IMAGE_REPO_URI\`].value | [0]' | grep -q ."
check "source type is still CODEPIPELINE" "proj source.type | grep -q CODEPIPELINE"

echo "== Pipeline =="
check "pipeline has 3 stages"              "test \"\$(pipe 'length(stages)')\" = 3"
check "stage 3 is named Deploy"            "pipe 'stages[2].name' | grep -q '^Deploy$'"
check "deploy provider is ECS"             "pipe 'stages[2].actions[0].actionTypeId.provider' | grep -q '^ECS$'"
check "deploy reads imagedefinitions.json" "pipe 'stages[2].actions[0].configuration.FileName' | grep -q imagedefinitions.json"

echo "== Conceptual documents and helpers =="
check "appspec.yaml present"               "test -f templates/lab-12-appspec.yaml"
check "deployment group document is valid JSON" \
  "python3 -m json.tool templates/lab-12-codedeploy-deployment-group.json"
check "usms-ecs-watch.sh executable and valid" \
  "test -x scripts/utilities/usms-ecs-watch.sh && bash -n scripts/utilities/usms-ecs-watch.sh"

echo "== Files and Git hygiene =="
check "configs/lab-12.env present"        "test -f configs/lab-12.env"
check "no empty or None values in lab-12.env" "! grep -qE 'export [A-Z_]+=$|=None$' configs/lab-12.env"
check "taskdef v3 template is valid JSON"  "python3 -m json.tool templates/lab-12-taskdef-v3.json"
check "pipeline template is valid JSON"    "python3 -m json.tool templates/lab-12-pipeline.json"
check "lab-12 templates have no unexpanded variables" \
  "! grep -q '[\$]' templates/lab-12-taskdef-v3.json templates/lab-12-codebuild-update.json templates/lab-12-pipeline.json"
check "both v2 policy documents are valid JSON" \
  "python3 -m json.tool policies/usms-codebuild-policy-v2.json && python3 -m json.tool policies/usms-codepipeline-policy-v2.json"
check "no secret is tracked"               "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

Read the failures top-down, not bottom-up.

  Environment block failing   -> Floci is not running, or is in memory mode. Fix first.
  Lab 11 dependencies        -> re-run verify-lab-11.sh before anything else.
  ECR block                   -> Path B: expected, 5 failures. Otherwise Steps 4, 5, 8.
  Source tree                 -> Steps 7 and 14.
  Task definition             -> Steps 10 and 11. A revision below 3 means Step 10 did not register.
  IAM policy versions         -> Steps 12 and 15. "default is v2" failing usually means
                                 create-policy-version ran without --set-as-default.
  CodeBuild project           -> Step 13. "source type CODEPIPELINE" failing means an
                                 over-broad update-project undid Lab 11 Step 18.
  Pipeline                    -> Step 16. Fewer than 3 stages after update-pipeline means
                                 the document sent was incomplete. Rebuild it from
                                 templates/lab-11-pipeline.json plus the Deploy stage.
  Hygiene                     -> Steps 20 and 21.
REMEDY
fi
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-12.sh
bash -n scripts/utilities/verify-lab-12.sh && echo "syntax OK"
./scripts/utilities/verify-lab-12.sh
```{% endraw %}

**Expected result**

```text
PASS=45  FAIL=0
```

> Example output - Path B correctly reads `PASS=40  FAIL=5` and Path C `PASS=31  FAIL=14`.

### 9.1 Known benign failures

| Failure | Benign when | What it means |
| --- | --- | --- |
| The five ECR checks | Step 3 reported Path B | No usable registry on this build. Your documents are still correct |
| `tag r7 is present` | You are on Path B, or you never pushed `r7` | Push it, or record that the deploy references an unpushed tag |
| The four pipeline checks | Path C | CodePipeline is absent. The three-stage document is still written and validated |
| `task definition names the ECR repo` | Never after Step 10 | **Not benign.** Step 10 did not register, or the service is on an older revision |
| `USMSCodeBuildBase default is v2` | Never after Step 12 | **Not benign.** You created a version without setting it as default |
| `source type is still CODEPIPELINE` | Never | **Not benign.** An over-broad `update-project` undid Lab 11 Step 18 |
| `no secret is tracked` | Never | **Not benign.** Fix `.gitignore`, then `git rm --cached` |

---

## 10. Checkpoints

| # | After Step | What must exist |
| --- | --- | --- |
| 1 | 3 | `deploy-support-probe.sh`, and your path recorded in `outputs/lab-12-deploy-probe.txt` |
| 2 | 6 | ECR repository `usms-enrolment`, and a successful `docker login` against its registry host |
| 3 | 9 | An image with tag `r6`, its digest recorded, deleted locally and pulled back by digest |
| 4 | 11 | Service `usms-enrolment-svc` on `usms-enrolment:3`, running your image |
| 5 | 13 | `USMSCodeBuildBase` at `v2`; the project with `privilegedMode` and `IMAGE_REPO_URI` |
| 6 | 14 | `Dockerfile`, `.dockerignore`, a buildspec that writes `imagedefinitions.json`, 8 smoke tests |
| 7 | 16 | A three-stage pipeline, its artifact chain readable down one column |
| 8 | 17 | A task definition revision registered by the pipeline, naming release `r7` |
| 9 | 18 | A failed deployment, a manual rollback, and a decision recorded about revision 5 |
| 10 | 19 | `lab-12-appspec.yaml` and the deployment group document, validated, not executed |

---
## 11. Troubleshooting

### `docker login` fails with `http: server gave HTTP response to HTTPS client`

The emulated registry serves plain HTTP. Add the registry host to Docker's `insecure-registries` -
Docker Desktop, Settings, Docker Engine; or `/etc/docker/daemon.json` on Linux - and restart Docker.
Never do this for a real registry. See the note in Step 6.

### `docker push` fails with `denied` or a 404 from the registry API

Three causes, in order of likelihood:

1. The registry data plane is not implemented on your build. That is Path B; use the local image.
2. The `5100-5104` range is not published. Re-check Step 4 with `docker port floci`.
3. The token expired. `get-login-password` is valid for twelve hours; log in again.

### `CannotPullContainerError` in the service events

The image reference in the task definition does not resolve. Check three things, in this order:
the tag exists (`aws ecr describe-images --image-ids imageTag=...`), the execution role is
`usms-ecs-exec-role` and carries `USMSECSTaskExecution` with its four `ecr:*` actions, and the image
URI in the task definition matches the repository URI character for character. On real AWS the third
is usually the culprit and usually a region mismatch.

### `register-task-definition` rejects the document, one field at a time

You did not strip all the read-only fields. The full list is in Step 10:
`taskDefinitionArn`, `revision`, `status`, `requiresAttributes`, `compatibilities`, `registeredAt`,
`registeredBy`, `deregisteredAt`. Re-run the Python from Step 10 rather than deleting them by hand -
it strips all eight and you will forget one.

### The Deploy stage fails with something about a container name

`imagedefinitions.json` names a container that is not in the task definition. Print both and compare:

```bash
python3 -c "import json;print(json.load(open('labs/lab-11-cicd/app/dist/imagedefinitions.json')))"
aws ecs describe-task-definition --task-definition usms-enrolment \
  --query 'taskDefinition.containerDefinitions[].name' --output text
```

The left must contain the right. This is what Lab 11's `pre_build` check is defending against, and if
that check passed, the mismatch came from an edit to `config/service.json` after the last build.

### The Deploy stage fails immediately, before doing anything

`imagedefinitions.json` is not at the root of `BuildOutput`. Download the artifact and look:

```bash
KEY=$(aws s3api list-objects-v2 --bucket usms-pipeline-artifacts \
  --prefix usms-enrolment-pipeline/BuildOutput/ \
  --query 'sort_by(Contents, &LastModified)[-1].Key' --output text)
aws s3api get-object --bucket usms-pipeline-artifacts --key "$KEY" /tmp/bo.zip >/dev/null
python3 -c "import zipfile;print(zipfile.ZipFile('/tmp/bo.zip').namelist())"
```

If you see `dist/imagedefinitions.json` rather than `imagedefinitions.json`, `artifacts.base-directory`
is missing or wrong in the buildspec.

### The pipeline lost its Source and Build stages

An `update-pipeline` with an incomplete document. Rebuild from what is committed:

```bash
python3 - << 'PY'
import json
p = json.load(open("templates/lab-11-pipeline.json"))["pipeline"]
cur = json.load(open("templates/lab-12-pipeline.json"))["pipeline"]
deploy = [s for s in cur["stages"] if s["name"] == "Deploy"]
p["stages"] = p["stages"] + deploy
json.dump({"pipeline": p}, open("templates/lab-12-pipeline-repaired.json", "w"), indent=2)
print("stages:", [s["name"] for s in p["stages"]])
PY
aws codepipeline update-pipeline --cli-input-json file://templates/lab-12-pipeline-repaired.json \
  --query 'pipeline.{Stages:length(stages)}' --output table
```

This works because Lab 11 committed its pipeline document. That is the argument for committing
templates rather than only creating resources from them.

### `update-project` wiped the environment variables

`environment` is replaced whole. Re-run Step 13's `--cli-input-json`, which contains all four
variables. Then check `source.type` is still `CODEPIPELINE` - an `update-project` that omitted `source`
leaves it alone, but one that included a partial `source` will not.

### The build's `docker build` says `dist: no such file or directory`

The `build` phase's image build runs after `dist/` is created, so this means an earlier command in the
phase failed and the phase continued. Check whether `cp -R src/. "$ARTIFACT_DIR"/` ran; if the buildspec
was edited, confirm the image build is still *after* the artifact assembly.

### Everything worked yesterday, nothing works today

Floci was restarted in memory mode, or the data directory moved.
Run `./scripts/utilities/floci-storage-check.sh` and read the first failing check. If a **new
terminal** is the thing that broke, see Errata 01.

---

## 12. Floci vs Real AWS

### 12.1 Feature by feature

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `ecr create-repository`, `describe-repositories` | Full | Typically full | **Implemented in Floci** |
| ECR as an OCI registry - `docker push` and `pull` | Full, HTTPS only, IAM-authorised | Build-dependent; often HTTP, sometimes absent | **Floci Limitation** |
| `repositoryUri` | `<acct>.dkr.ecr.<region>.amazonaws.com/<repo>` | A localhost-style host and port | **Floci Limitation** |
| Image scanning on push | Basic and enhanced scanning against a CVE database | Setting stored; no scan performed | **Floci Limitation** |
| Image tag immutability | Enforced - a second push to an existing tag is rejected | Setting stored; enforcement build-dependent | **Floci Limitation** |
| ECR lifecycle policies | Full - expire untagged images after N days | Usually stored, not evaluated | **Conceptual / Real AWS** |
| `ecs register-task-definition` | Full, with validation | Typically full | **Implemented in Floci** |
| `ecs update-service` changing the task definition | Full, with a rolling deployment | Pointer changes; tasks may not run | **Floci Limitation** |
| Deployment circuit breaker and automatic rollback | Trips on repeated task failures; rolls back | Stored, not enforced | **Floci Limitation** |
| `rolloutState` and `rolloutStateReason` | Populated throughout a deployment | Frequently absent | **Floci Limitation** |
| Service events (`CannotPullContainerError`, and so on) | The primary diagnostic | Usually empty | **Floci Limitation** |
| CodePipeline ECS deploy action | Reads `imagedefinitions.json`, registers a revision, updates the service | Build-dependent; may store the stage and never run it | **Floci Limitation** |
| `privilegedMode` builds | Docker in Docker inside the managed build container | Depends on the emulator's build backend | **Floci Limitation** |
| CodeDeploy, blue/green, task sets, test listeners | Full | Absent | **Conceptual / Real AWS** |
| `imageDetail.json` and `appspec.yaml` | Consumed by a CodeDeploy deploy action | Nothing consumes them | **Conceptual / Real AWS** |
| ECR image signing and registry policies | Full | Absent | **Conceptual / Real AWS** |
| Cost - ECR storage and data transfer, build minutes | Billed | Free | **Floci Limitation** |

### 12.2 What you observed, and what you recorded

```text
OBSERVED - you saw this happen on your own machine
  a container image built from the build output, with a name and a digest
  the difference between the build's image id and the push's manifest digest
  a task definition revision derived from its predecessor with one field changed
  everything else in that revision surviving the derivation - cpu, memory, roles, logs
  the service pointing at a revision that names your image instead of the placeholder
  a three-stage pipeline document, and its artifact chain down one column
  a deployment to a release whose image was never pushed, and nothing warning you
  a rollback performed by naming an earlier revision

RECORDED - correct, checkable by reading, not enforced here
  the ECR push permissions, and why GetAuthorizationToken cannot be scoped
  the second iam:PassRole, to ecs-tasks.amazonaws.com and two named roles
  the deploy action's single-service ARN
  scanOnPush and MUTABLE tag settings
  the CodeDeploy appspec and deployment group, including the test listener

NOT AVAILABLE AT ALL
  blue/green deployment, task sets, traffic shifting
  the circuit breaker actually tripping and rolling back
  image vulnerability scan results
  ECR lifecycle expiry
```

If Step 3 reported Path B or Path C, move the corresponding lines from OBSERVED to RECORDED in your own
report. "I deployed to ECS from a pipeline" and "I built and validated the deploy stage on a build that
executes no pipelines, and deployed by hand to prove the task definition mechanics" are different
claims, and the second, stated plainly, is worth more than an overstated first one.

### 12.3 Where Floci is nicer than reality

- **Images appear instantly and cost nothing.** Real ECR bills for storage per gigabyte-month, and a
  repository with six months of untagged layers is a real line item. This is what lifecycle policies
  are for, and this course never needed one.
- **No pull rate limits.** `nginx:1.27-alpine` comes from Docker Hub, which rate-limits anonymous pulls
  on real infrastructure. A CI pipeline that pulls a public base image on every build will hit that
  limit, which is why real pipelines mirror base images into their own registry.
- **No propagation delay.** A task definition registered one second ago is usable immediately here.
  Real ECS is eventually consistent in places, and a deployment that references a revision registered
  microseconds earlier occasionally needs a retry.
- **Nothing fails at 3am.** No capacity errors, no AZ impairments, no image pull throttling. Every
  failure in this lab was one you caused deliberately, which is exactly what a laboratory should give
  you and exactly what production will not.

---

## 13. Independent Lab Exercises

Five exercises, increasing in difficulty. Write your answers and evidence in
`labs/lab-12-cicd-deploy/exercises.md`.

### Exercise 1 - Basic: a second base image, and a smaller one

**Requirements**

Rebuild the enrolment image on a different base - `public.ecr.aws/nginx/nginx:stable-alpine`, the image
Lab 04's placeholder task definition named - and push it as tag `r7-alt`. Compare the two images'
sizes and layer counts.

**Constraints**

- Do not change `VERSION`; the tag is set explicitly for this exercise only.
- Do not deploy it. This exercise ends at the registry.
- Record both sizes from `describe-images`, not from `docker images`, and say why those two numbers
  differ.

**Expected outcome**

Two tags in the repository, two sizes, and a one-paragraph note on what the difference consists of.

**Hints**

`docker history` shows layer sizes. The registry reports compressed sizes and the local daemon reports
uncompressed ones; that is most of the difference, but not all of it.

### Exercise 2 - Intermediate: argue for immutable tags, then implement it

**Requirements**

Set the repository's tag mutability to `IMMUTABLE`, attempt to push `r7` again, and record what
happens. Then work out what would have to change in this lab's buildspec for an immutable-tag
repository to work, and make that change.

**Constraints**

- Use `aws ecr put-image-tag-mutability`, not a new repository.
- The buildspec must still produce a deployable `imagedefinitions.json`.
- Set it back to `MUTABLE` at the end, or leave it immutable and say why - but say which, because
  Section 9's verification does not check this field and a later lab might be surprised.

**Expected outcome**

A recorded rejection, a buildspec that cannot collide with an existing tag, and a paragraph on what
immutable tags buy and what they cost.

**Hints**

A tag that includes something unique per build cannot collide. CodeBuild sets
`CODEBUILD_RESOLVED_SOURCE_VERSION` and `CODEBUILD_BUILD_NUMBER`; the local runner sets neither, so
whatever you choose needs a defined fallback.

### Exercise 3 - Problem solving: build the blue/green scaffolding

**Requirements**

Step 19 wrote documents that reference a second target group and a test listener, neither of which
exists. Create them: `usms-enrolment-tg-green` with the same settings as Lab 05's target group, and a
test listener on port `8080` of `usms-enrolment-alb` forwarding to it.

Then re-validate `templates/lab-12-codedeploy-deployment-group.json` with the real ARNs substituted for
the two placeholders.

**Constraints**

- Reuse Lab 05's settings exactly: target type `ip`, HTTP:80 health check on `/`, matcher 200.
- Do **not** change the ECS service's deployment controller. Step 19's danger admonition says why.
- The document must contain no angle-bracket placeholders when you are finished.

**Expected outcome**

Two target groups, two listeners, and a deployment group document that would be accepted by an account
where CodeDeploy exists.

**Hints**

Lab 05 Step 6 created the first target group and Step 8 the listener; `--query` those resources for
their ARNs rather than copying them. The `deployment group` document is JSON, so use `python3` for the
substitution, as Step 16 did.

### Exercise 4 - Challenge: close the hole in the pipeline policy

**Requirements**

Step 15 granted `ecs:RegisterTaskDefinition` on `Resource: "*"` and argued that the `PassRole`
statement bounds the damage. Test that argument.

Write, in prose, the most damaging thing a compromised pipeline role could do with the v2 policy as
written. Then produce a v3 that closes it, or argue - with specifics - that it cannot be closed with
IAM alone and say what other control would be needed.

**Constraints**

- Your v3, if you write one, must not break the pipeline. Prove it by running an execution.
- Do not use conditions you have not checked exist. If you propose a condition key, cite the
  documentation page that lists it for that action.
- Five versions maximum per policy; you may need to delete one first.

**Expected outcome**

A specific attack described in two or three sentences, and either a working v3 or a reasoned argument
that the control belongs somewhere other than this policy.

**Hints**

Think about what a task definition can contain besides an image, and what a task that runs with
`usms-ecs-task-role` can reach. Lab 01 attached `USMSStudentDataReadWrite` to that role. The question
is not whether the pipeline can pass the role - it can, by design - but what it can make the role do.

### Exercise 5 - Integration: prove a release end to end, for an auditor

**Requirements**

Produce a single document, `outputs/lab-12-release-evidence.md`, that traces release `r7` from the
source byte to the running service, using only command output as evidence. It must include, in order:
the S3 version ID of the source archive; the pipeline execution ID; the build ID; the image digest; the
task definition revision ARN; and the service's current task definition.

Then break one link deliberately - retag `r7` in the registry to point at a different image - and write
what the document can and cannot still prove.

**Constraints**

- Every value must come from a command, shown in the document alongside its output.
- The retag must be recorded in `outputs/lab-12-image-digest.txt` as a second line for the same tag.
- Do not deploy the retagged image.

**Expected outcome**

An evidence chain, and a demonstration of exactly which link a mutable tag breaks. This is the artefact
the CloudFormation lab's audit exercise starts from, and it is the strongest answer you can give to
Section 15's question 7.

**Hints**

`docker tag` plus `docker push` retags. `describe-images` will then show the old digest with no tags,
or with the tag moved, depending on your build. The chain you are testing is: does a task definition
that names a *tag* let you prove which bytes ran?

---

## 14. Lab Assessment Checklist

- [ ] `deploy-support-probe.sh` run, and the path recorded in your notes
- [ ] The `5100-5104` range uncommented, `floci-up.sh` re-run, and the service proved to have survived
- [ ] ECR repository `usms-enrolment` created with `scanOnPush` and a recorded tag-mutability decision
- [ ] The registry host derived from `describe-repositories`, never typed
- [ ] `docker login` succeeded, with the token passed through standard input
- [ ] `Dockerfile` and `.dockerignore` written, and the `COPY dist/` choice explained in one sentence
- [ ] An image built, tagged, pushed, and its digest recorded in `outputs/lab-12-image-digest.txt`
- [ ] The image deleted locally and pulled back **by digest** - the create, perturb, read back proof
- [ ] Task definition revision 3 derived with describe-strip-register, with all eight read-only fields stripped
- [ ] Revision 3 verified to have kept cpu, memory, both roles and the health check
- [ ] `usms-ecs-watch.sh` written and used
- [ ] `USMSCodeBuildBase` v2 created **and set as default**, with `GetAuthorizationToken` on `"*"` explained
- [ ] `privilegedMode` enabled, and what it grants stated in your notes
- [ ] The buildspec extended: guarded image build, `imagedefinitions.json`, `imageUri` in the metadata
- [ ] The eighth smoke-test assertion added and passing
- [ ] `USMSCodePipelineBase` v2 created and set as default, with the second `PassRole` explained
- [ ] The Deploy stage added with get-modify-put, and the danger admonition read first
- [ ] An end-to-end execution, with `outputs/lab-12-deploy-evidence.txt` showing before and after
- [ ] The rollback drill run, and a decision recorded about `usms-enrolment:5`
- [ ] `lab-12-appspec.yaml` and the deployment group document written and validated
- [ ] `configs/lab-12.env` with 26 populated exports
- [ ] `verify-lab-12.sh` run, with its count and any benign failures recorded
- [ ] `git status --short` checked before staging; no `outputs/` file and no compose backup committed
- [ ] Five exercises attempted
- [ ] Section 15 answered in prose in `notes/lab-12-notes.md`

### 14.1 In-class assessment - Practical 7

**Format.** Sixty minutes, at a machine, with the documentation open. You may read Labs 11 and 12,
the AWS documentation, and your own notes. You may not copy a command sequence wholesale from the labs
without changing it to fit the task - the tasks are written so that a copied sequence produces the
wrong answer.

**Starting state.** Labs 11 and 12 complete and `verify-lab-12.sh` passing at your path's expected
count. If it is not, say so before you start; you will be assessed against what you have.

**Submit.** One file, `outputs/lab-12-assessment.md`, containing for each task: the commands you ran,
their output, and the short written answers requested. Plus whatever resources the tasks created, which
will be checked.

---

#### Task A - A second service through the same pipeline (35 marks)

The university wants the **results service** deployed the same way. It does not exist yet.

1. Create an ECR repository `usms-results`, with the same settings as `usms-enrolment` except that its
   tags must be **immutable**.
2. Create a source tree at `labs/lab-11-cicd/app-results/` - a `VERSION`, one HTML file, a
   `config/service.json` naming container `results-api` and port `80`, a `Dockerfile`, and a
   `buildspec.yml` that writes an `imagedefinitions.json` for `results-api`.
3. Build the image as tag `r1` and push it.
4. Register a task definition family `usms-results` with one container named `results-api`, using the
   same execution and task roles as the enrolment service.

You are **not** asked to create an ECS service or a pipeline for it.

**Marks:** repository with correct settings 6; source tree complete and the buildspec parsing 10;
image built and pushed, digest shown 8; task definition registered with the correct container name and
roles 8; marks lost for any hard-coded registry host.

---

#### Task B - Trace a release, and find the gap (30 marks)

Using only command output as evidence, answer these in `outputs/lab-12-assessment.md`:

1. Which task definition revision is `usms-enrolment-svc` running right now, and which image URI does
   it name? (4)
2. Which image digest does that URI currently resolve to? (4)
3. Which pipeline execution registered that revision, and which S3 source version did that execution
   consume? Show how you established the link. (10)
4. Name one link in that chain that your evidence does **not** actually prove, and explain in three or
   four sentences what an attacker or an accident could do in that gap. (12)

Question 4 is the one that separates answers. A correct answer identifies a specific mechanism, not a
general worry.

---

#### Task C - Design, in writing only (25 marks)

The university's change-control committee will not allow automatic deployment to production. They want
the pipeline to stop before Deploy and wait for a named person to approve.

In no more than 400 words, and with a JSON fragment for the stage you would add:

1. Name the action category and provider you would use, and where in the pipeline it goes. (6)
2. State what the approver actually sees, and what they must be given in order to decide. (6)
3. Explain what happens to the artifacts while the pipeline waits, and what the timeout is. (7)
4. State, in one sentence, whether this is demonstrable on Floci, and how you know. (6)

No commands are required for this task. Correct JSON that would be rejected by Floci scores full marks;
an approximation that "looks about right" does not.

---

#### Task D - Housekeeping (10 marks)

1. Run `verify-lab-12.sh` and paste the result. (3)
2. Run `git status --short` and confirm nothing under `outputs/` is staged. (3)
3. State which support path your build is on and one thing in this assessment you could therefore not
   demonstrate. (4)

---

**Marking notes for the instructor.** Total 100. Task A is checkable mechanically:
`aws ecr describe-repositories --repository-names usms-results`,
`aws ecs describe-task-definition --task-definition usms-results`, and `bash -n` plus a YAML parse on
the new buildspec. Task B question 3 is where copied work shows: a student who ran the lab has the
execution ID in `outputs/lab-12-deploy-evidence.txt` and can say how they linked it; one who did not
will assert the link without evidence. Task C question 4 should say that CodePipeline manual approval
actions are not modelled on this emulator and cite the Step 3 probe or Section 12's table - a student
who claims to have tested it has not.

---

## 15. Review Questions

Answer in prose, in `notes/lab-12-notes.md`. No command output.

1. The ECS deploy action changes exactly one field of the task definition. Name three realistic changes
   to a service that therefore **cannot** travel through this pipeline, and describe how you would
   deploy each of them instead.

2. `ecr:GetAuthorizationToken` must be granted on `Resource: "*"` and `ecs:RegisterTaskDefinition`
   effectively must be too. Are these the same kind of exception? Argue both sides, then commit to an
   answer.

3. Explain to a sceptical colleague why an image digest is worth the inconvenience over a tag. Then
   make the strongest case *against* pinning digests in task definitions - there is a real one.

4. Step 18's deployment pointed the service at an image that did not exist, and nothing on this
   emulator objected. On real AWS the circuit breaker would have caught it. Describe a failure the
   circuit breaker would **not** catch, and say what mechanism would.

5. `update-pipeline`, `put-bucket-notification-configuration`, `update-assume-role-policy` and
   `put-bucket-policy` are all replace-only. What do these APIs have in common that makes replacement
   the natural design, and what would a merge-based version of `update-pipeline` have to decide that a
   replace-based one does not?

6. This lab created a second IAM policy version twice and had to set each as default. Why is
   `create-policy-version` not simply `--set-as-default` by default? Describe the workflow that design
   is protecting.

7. You have `outputs/lab-12-deploy-evidence.txt`, `outputs/lab-12-image-digest.txt`, and the pipeline
   execution history. A colleague claims the enrolment service is running code that was never reviewed.
   Which of those three artefacts helps, which does not, and what would you have needed to record at
   build time to settle it in one command?

---

## 16. What We Built

### 16.1 Reflection

The enrolment service is now running code that came out of this repository, and the thing that put it
there is a document rather than a person. That is the change. Lab 04 made a service exist; Lab 05
gave it a front door; Lab 06 let it grow; Lab 11 turned source into an artifact; and this lab
connected the artifact to the running thing.

Two moments in this lab are worth keeping.

The first is Step 10, where you produced a task definition revision by describing the existing one,
stripping eight read-only fields and changing a single value. That is a tedious procedure, and it is
the thing the deploy action does for you in a few hundred milliseconds. Having done it by hand once,
you know exactly what the automation is and - much more usefully - exactly what it is not. It is not a
way to change the memory allocation. It is not a way to add an environment variable. Knowing the shape
of a tool's competence is most of knowing when to reach for a different one.

The second is Step 18, where a deployment referenced an image that did not exist and nothing said so.
On real AWS a mechanism would have caught it. Here nothing did - and the lesson is not "the emulator is
limited" but "a deployment mechanism is only as good as the health signal behind it". The circuit
breaker is not a safety net; the health check is the safety net, and the circuit breaker is what reads
it. A service with a health check that always returns 200 has a circuit breaker that will never fire,
on real AWS as surely as here.

### 16.2 KEEP and CLEAN UP

```text
╔══════════════════ KEEP ══════════════════╗    ╔═══════════ CLEAN UP ═══════════╗
║ usms-enrolment  (ECR repository)         ║    ║ usms-probe-delete-me           ║
║ images r6 and r7                         ║    ║   - the Step 3 probe repo, if  ║
║ task definitions usms-enrolment:3 and :4 ║    ║     it survived the probe      ║
║ the three-stage pipeline                 ║    ║ usms-enrolment:5               ║
║ USMSCodeBuildBase v2 (default)           ║    ║   - the failed revision; your  ║
║ USMSCodePipelineBase v2 (default)        ║    ║     Step 18 decision governs   ║
║ Dockerfile, .dockerignore, buildspec.yml ║    ║ docker-compose.yml.bak-*       ║
║ templates/lab-12-*.json and .yaml       ║    ║   - keep one, delete the rest  ║
║ scripts/utilities/usms-ecs-watch.sh      ║    ║ labs/.../app/dist/             ║
║ scripts/utilities/verify-lab-12.sh      ║    ║   - build output, git-ignored  ║
║ configs/lab-12.env                      ║    ║ outputs/lab-12-*              ║
║ the 5100-5104 port range, published      ║    ║   - keep until your report is  ║
║ buildspec.yml.lab08a (for comparison)    ║    ║     written                    ║
╚══════════════════════════════════════════╝    ╚════════════════════════════════╝
```

Do not clean up the KEEP column. The CloudFormation lab re-declares every object in it as a template
and compares the result with what you built by hand; a missing pipeline stage makes that comparison
meaningless.

### 16.3 The end-of-course cleanup script

!!! danger "Read before running any delete command"
    **What will be deleted:** the pipeline's Deploy stage, task definition revisions 3 to 5
    (deregistered), the ECR repository `usms-enrolment` **and every image in it**, and version 2 of both
    IAM policies. The service is returned to Lab 04's revision 2 and its placeholder image.

    **What depends on it:** every claim in your report that has not yet been written down. Deregistered
    task definition revisions cannot be re-registered under the same revision number; deleted images are
    gone unless you can rebuild them.

    **Reversible?** Partially. The pipeline stage can be re-added from
    `templates/lab-12-pipeline.json`. The images and the revision numbers cannot come back.

    **Effect on later labs:** the CloudFormation lab loses its comparison target. Run this only at the
    end of the course, and run it **before** `lab-11-cleanup.sh`.

```bash
cat > scripts/cleanup/lab-12-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes everything Lab 12 created, dependencies inside-out.
# Run BEFORE scripts/cleanup/lab-11-cleanup.sh.
# DO NOT RUN NOW.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
[ -f configs/lab-04.env ] && source configs/lab-04.env
# shellcheck disable=SC1091
[ -f configs/lab-12.env ] && source configs/lab-12.env

: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ECR_REPO:=usms-enrolment}"
: "${USMS_PIPELINE_NAME:=usms-enrolment-pipeline}"

cat <<'WARN'
This removes the Deploy stage, deregisters the task definition revisions this lab
created, DELETES the ECR repository and every image in it, and reverts both IAM
policies to version 1. The ECS service is returned to usms-enrolment:2.

The CloudFormation lab compares its template against these resources. Do not run
this before that lab.
WARN

printf 'Type exactly: DELETE USMS DEPLOY STAGE\n> '
read -r CONFIRM
[ "$CONFIRM" = "DELETE USMS DEPLOY STAGE" ] || { echo "aborted"; exit 1; }

say() { printf '\n== %s ==\n' "$1"; }

say "return the service to Lab 04's revision 2"
aws ecs update-service --cluster "$USMS_ECS_CLUSTER" --service "$USMS_ENROLMENT_SERVICE" \
  --task-definition usms-enrolment:2 >/dev/null 2>&1 || true

say "remove the Deploy stage, keeping Source and Build"
if aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" >/dev/null 2>&1; then
  aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" --query 'pipeline' --output json \
    > /tmp/usms-pipeline-cleanup.json
  python3 - << 'PY'
import json
p = json.load(open("/tmp/usms-pipeline-cleanup.json"))
p["stages"] = [s for s in p["stages"] if s["name"] != "Deploy"]
json.dump({"pipeline": p}, open("/tmp/usms-pipeline-cleanup-out.json", "w"), indent=2)
print("stages left:", [s["name"] for s in p["stages"]])
PY
  aws codepipeline update-pipeline --cli-input-json file:///tmp/usms-pipeline-cleanup-out.json \
    >/dev/null 2>&1 || true
  rm -f /tmp/usms-pipeline-cleanup.json /tmp/usms-pipeline-cleanup-out.json
fi

say "deregister the task definition revisions this lab created"
for REV in 3 4 5; do
  aws ecs deregister-task-definition --task-definition "usms-enrolment:$REV" >/dev/null 2>&1 \
    && echo "  deregistered usms-enrolment:$REV" || echo "  usms-enrolment:$REV absent"
done

say "delete the ECR repository and every image in it"
aws ecr delete-repository --repository-name "$USMS_ECR_REPO" --force >/dev/null 2>&1 \
  && echo "  deleted $USMS_ECR_REPO" || echo "  $USMS_ECR_REPO absent"

say "revert both policies to version 1"
for POL in USMSCodeBuildBase USMSCodePipelineBase; do
  ARN="arn:aws:iam::000000000000:policy/$POL"
  aws iam set-default-policy-version --policy-arn "$ARN" --version-id v1 >/dev/null 2>&1 || true
  aws iam delete-policy-version --policy-arn "$ARN" --version-id v2 >/dev/null 2>&1 \
    && echo "  $POL back to v1" || echo "  $POL unchanged"
done

say "turn privilegedMode back off"
aws codebuild update-project --name usms-enrolment-build \
  --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_SMALL,privilegedMode=false \
  >/dev/null 2>&1 || true

say "done"
echo "Lab 12 removed. Lab 11's two-stage pipeline is intact."
echo "The 5100-5104 port range is still published; re-comment it in docker-compose.yml"
echo "and re-run floci-up.sh if you want those ports back."
EOF

chmod +x scripts/cleanup/lab-12-cleanup.sh
bash -n scripts/cleanup/lab-12-cleanup.sh && echo "syntax OK - do NOT run it"
```

End-of-course run order:

```text
scripts/cleanup/lab-12-cleanup.sh    (deploy stage, task revisions, ECR, policy v2)
scripts/cleanup/lab-11-cleanup.sh    (pipeline, build project, artifact bucket)
scripts/cleanup/lab-10-cleanup.sh
scripts/cleanup/lab-09-cleanup.sh
scripts/cleanup/lab-08-cleanup.sh
scripts/cleanup/lab-07-cleanup.sh
scripts/cleanup/lab-06-cleanup.sh
scripts/cleanup/lab-05-cleanup.sh
scripts/cleanup/lab-04-cleanup.sh
scripts/cleanup/lab-03-cleanup.sh
scripts/cleanup/lab-02-cleanup.sh
```

### 16.4 The architecture now

```text
  labs/lab-11-cicd/app/  ──zip──>  S3 usms-pipeline-artifacts  ──>  CodePipeline
                                                                          │
                                       ┌──────────────────────────────────┤
                                       v                                  v
                                   CodeBuild                          ECS deploy
                                  docker build                     imagedefinitions.json
                                  docker push                      register + update-service
                                       │                                  │
                                       v                                  v
                                 ECR usms-enrolment  <─── pulled by ─── usms-enrolment-svc
                                                                          │
  usms-vpc                                                                │
   ├── public  subnets a,b ── usms-enrolment-alb ── usms-enrolment-tg ────┘
   └── private subnets a,b ── 2 to 10 Fargate tasks, container enrolment-api:80
```

Every box in that diagram was built by hand in this course, in order, and the arrows between the top
row are the only ones that did not exist a day ago.

---

## 17. Preparation for the Next Lab

The next laboratory is the S3 configuration document Lab 10 Section 17 promised and the delivery
schedule deferred - still unwritten, with no fixed slot number in this sequence. It opens with a
bucket that exists, holds real objects, is wired to a real trigger - and is still missing every piece
of configuration that makes a bucket production-ready.

Nothing in this lab blocks it. What this lab adds to it is a second, harder example of the same
question: `usms-pipeline-artifacts` is now a bucket holding build outputs with no lifecycle rule, no
encryption configuration and no bucket policy, and it will accumulate an object per pipeline execution
forever. The S3 configuration lab configures `usms-student-data`; the obvious exercise is to do the
same to the artifact bucket, and that lab's Exercise 5 does exactly that.

### What the S3 configuration lab will consume

| Artefact | From | How it is used |
| --- | --- | --- |
| `usms-student-data` | Lab 10 Step 5 | Configures it: versioning, default encryption, public-access block, lifecycle |
| `outputs/lab-09-bucket-policy-draft.json` | Lab 09 Ex 5 | Applies it as the bucket's resource policy |
| `usms-pipeline-artifacts` | Lab 11 Step 5 | The second bucket in Exercise 5 - versioned already, unmanaged otherwise |
| `configs/lab-11.env`, `configs/lab-12.env` | Steps 20, and Lab 11 Step 21 | Sourced; the artifact bucket's name comes from there |

### The thing the S3 configuration lab must be careful about

A lifecycle rule that expires noncurrent versions in `usms-pipeline-artifacts` will also expire the
**source archive versions** that this lab's pipeline executions reference. A CodePipeline execution
records the S3 version ID it consumed; if that version has been expired, the execution's provenance
cannot be re-established, and re-running an old execution fails.

That is a genuine operational trade-off rather than a mistake to avoid: storage costs money, and
provenance has a retention period like everything else. That lab should make the decision explicitly
rather than by default, which is the whole argument for doing it in a lab.

### Pre-session checks

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-12.sh          # PASS=45  FAIL=0  (or your path's count)
./scripts/utilities/verify-lab-11.sh          # PASS=46  FAIL=0
grep -c '^export' configs/lab-12.env          # 26
aws s3api head-bucket --bucket usms-student-data && echo "Lab 10's bucket is present"
```

### Snapshot before you finish

```bash
floci snapshot save lab-12-complete
floci snapshot list
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-12.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

### Read ahead

- **S3 versioning cannot be turned off, only suspended.** You have now enabled it on one bucket
  deliberately. Consider what suspension means for a bucket that already has versions, and what it does
  not mean.
- **A bucket policy and an identity policy can both grant access to the same object.** You have seen
  this three times now: at the Lambda function in Lab 10, at the artifact bucket here, and in Lab 09.
  Work out which you would use to grant a *different account* access, and why the answer is not
  symmetric.
- **Lifecycle rules act on noncurrent versions separately from current ones.** Read the two
  configuration blocks before the session; the distinction is the whole of the trade-off described
  above.

---

## Appendix A - Command Reference

| Command | What it does here |
| --- | --- |
| `aws ecr create-repository --repository-name R` | Creates a private repository |
| `aws ecr describe-repositories --repository-names R` | Reads back `repositoryUri` - the only correct source of the registry host |
| `aws ecr get-login-password \| docker login --password-stdin H` | Twelve-hour registry credential, never on the command line |
| `aws ecr describe-images --repository-name R --image-ids imageTag=T` | The tag-to-digest mapping |
| `aws ecr delete-repository --repository-name R --force` | Deletes the repository **and its images** |
| `aws ecr put-image-tag-mutability` | Switches a repository between `MUTABLE` and `IMMUTABLE` |
| `docker build -t name:tag .` | Builds from the context; `.dockerignore` decides what is sent |
| `docker tag a b` | Adds a second name; copies nothing |
| `docker push name:tag` | Uploads layers, then the manifest; prints the manifest digest |
| `docker pull repo@sha256:...` | Fetches by digest - the only unforgeable reference |
| `aws ecs describe-task-definition --task-definition F` | The latest active revision of family `F` |
| `aws ecs register-task-definition --cli-input-json file://T` | Creates the next revision |
| `aws ecs update-service --task-definition F:N` | Points the service at a revision; also the rollback |
| `aws ecs deregister-task-definition --task-definition F:N` | Retires a revision; the number is never reused |
| `aws iam create-policy-version --set-as-default` | New version, activated. Without the flag, not activated |
| `aws iam set-default-policy-version --version-id vN` | Activates an existing version |
| `aws iam list-policy-versions` | Five maximum; delete one before adding a sixth |
| `aws codebuild update-project --cli-input-json file://T` | Replaces the members named in the document |
| `aws codepipeline get-pipeline --query 'pipeline'` | The document without `metadata` - the read half of get-modify-put |
| `aws codepipeline update-pipeline --cli-input-json file://T` | Replaces the whole pipeline |
| `docker port floci` | Which host ports the container publishes |

## Appendix B - New JMESPath and CLI patterns introduced

| Pattern | Meaning | Where |
| --- | --- | --- |
| `${VAR%%/*}` | Shell expansion: strip from the first `/` to the end, leaving the registry host | Step 5 |
| `cut -d/ -f1` | The same thing where a shell expansion cannot survive a heredoc | Step 20 |
| `containerDefinitions[?name==` + backtick + `enrolment-api` + backtick + `].image \| [0]` | Select a container by name, not position | Steps 10, 17 |
| `deployments[?status==` + backtick + `PRIMARY` + backtick + `].runningCount \| [0]` | The running count of the deployment that matters | Step 11 |
| `--image-ids imageTag=T` | Address one image in a repository by tag | Step 9 |
| `repo@sha256:...` | Address an image by digest rather than tag | Step 9 |
| `--query 'pipeline'` on `get-pipeline` | Drop `metadata` before a get-modify-put | Step 16 |
| `aws iam get-policy-version --query 'PolicyVersion.Document.Statement[].Sid'` | List a policy version's statement names without printing the whole document | Step 15 |
| `sed -i.tmp -E 's/^([[:space:]]*)#...//'` with a following `rm` | Portable in-place edit with a capture group, on GNU and BSD `sed` | Step 4 |

## Sources

- [Amazon ECR User Guide - private repositories](https://docs.aws.amazon.com/AmazonECR/latest/userguide/Repositories.html)
- [Amazon ECR User Guide - pushing an image](https://docs.aws.amazon.com/AmazonECR/latest/userguide/docker-push-ecr-image.html)
- [Amazon ECR User Guide - private registry authentication](https://docs.aws.amazon.com/AmazonECR/latest/userguide/registry_auth.html)
- [Amazon ECR User Guide - image tag mutability](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html)
- [Amazon ECR User Guide - image scanning](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning.html)
- [Amazon ECR User Guide - lifecycle policies](https://docs.aws.amazon.com/AmazonECR/latest/userguide/LifecyclePolicies.html)
- [Amazon ECS Developer Guide - task definition parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html)
- [Amazon ECS Developer Guide - the rolling update deployment type](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html)
- [Amazon ECS Developer Guide - deployment circuit breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html)
- [Amazon ECS Developer Guide - blue/green deployment with CodeDeploy](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-bluegreen.html)
- [Amazon ECS Developer Guide - task execution IAM role](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html)
- [AWS CodePipeline User Guide - Amazon ECS deploy action and imagedefinitions.json](https://docs.aws.amazon.com/codepipeline/latest/userguide/action-reference-ECS.html)
- [AWS CodePipeline User Guide - Amazon ECS and CodeDeploy blue/green, and imageDetail.json](https://docs.aws.amazon.com/codepipeline/latest/userguide/action-reference-ECSbluegreen.html)
- [AWS CodePipeline User Guide - manual approval actions](https://docs.aws.amazon.com/codepipeline/latest/userguide/approvals.html)
- [AWS CodePipeline User Guide - edit a pipeline with the CLI](https://docs.aws.amazon.com/codepipeline/latest/userguide/pipelines-edit.html)
- [AWS CodeBuild User Guide - build specification reference](https://docs.aws.amazon.com/codebuild/latest/userguide/build-spec-ref.html)
- [AWS CodeBuild User Guide - Docker images and privileged mode](https://docs.aws.amazon.com/codebuild/latest/userguide/sample-docker.html)
- [AWS CodeDeploy User Guide - AppSpec file reference for Amazon ECS](https://docs.aws.amazon.com/codedeploy/latest/userguide/reference-appspec-file-structure.html)
- [AWS CodeDeploy User Guide - deployment configurations for Amazon ECS](https://docs.aws.amazon.com/codedeploy/latest/userguide/deployment-configurations.html)
- [IAM User Guide - granting a user permission to pass a role to a service](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html)
- [IAM User Guide - versioning IAM policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-versioning.html)
- [Docker documentation - the .dockerignore file](https://docs.docker.com/build/concepts/context/)
- [Docker documentation - insecure registries](https://docs.docker.com/reference/cli/dockerd/)
- [AWS CLI Command Reference - aws ecr](https://docs.aws.amazon.com/cli/latest/reference/ecr/)
- [AWS CLI Command Reference - aws ecs](https://docs.aws.amazon.com/cli/latest/reference/ecs/)
- [AWS CLI Command Reference - aws deploy](https://docs.aws.amazon.com/cli/latest/reference/deploy/)
- [LocalStack documentation - ECR, ECS and CodePipeline providers, which is the emulator behaviour this course calls Floci](https://docs.localstack.cloud/user-guide/aws/)
- [JMESPath specification](https://jmespath.org/specification.html)
- Course documents: Lab 01 (IAM, `USMSECSTaskExecution` and its four `ecr:*` actions), Lab 04 Step 14
  (the health check revision 3 inherits) and Step 15 (`--force-new-deployment` and image tags), Lab 05
  (the target group a blue/green setup would have to pair), Lab 06 (the scalable target a controller
  change would strand), Lab 09 Step 8 (`usms-deploy-role`), Lab 10 Section 17 (replace-only APIs as a
  family), Lab 11 (the pipeline this one extends), Errata 01.

---

*Lab 12 complete. The enrolment service is running code this repository produced, put there by a
document rather than a person - and you have seen both what that mechanism can express and what it
cannot. The S3 configuration lab goes back to the bucket everything has been pointing at.*
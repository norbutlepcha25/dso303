# Lab 12 - Deploying to Amazon ECS from the Pipeline

*Practical 7 (Practical 5 in the module descriptor; laboratory numbering follows the dependency graph, as Lab 11 explains). This document also carries the Practical 7 in-class assessment, in Section 13.1.*

## 1. Objectives

- Create a private ECR repository, authenticate Docker against it with a token on standard input, and push an image, reading the registry host from the API.
- Explain image tag versus image digest, and derive a new task definition revision with describe, strip, register.
- Version the two pipeline IAM policies (create **and** set as default) and add an ECS Deploy stage with get-modify-put, driven by `imagedefinitions.json`.
- Deploy through the pipeline, prove the service moved, and roll a bad release back by hand.
- Specify a blue/green deployment with CodeDeploy, stating honestly that you did not perform one.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [images, tags and digests](../unit2/topic1.md#images-layers-manifests-tags-and-digests) ·
    [Dockerfiles and the build cache](../unit2/topic1.md#dockerfiles-and-the-build-cache) ·
    [Amazon ECR concepts](../unit2/topic1.md#amazon-ecr-concepts) ·
    [ECS task definitions](../unit2/topic1.md#ecs-task-definitions) ·
    [the rolling update](../unit2/topic3.md#deployment-the-rolling-update) ·
    [the deployment circuit breaker](../unit2/topic3.md#the-deployment-circuit-breaker) ·
    [blue/green with CodeDeploy](../unit2/topic3.md#bluegreen-with-aws-codedeploy) ·
    [AWS CodeBuild](../unit5/topic1.md#aws-codebuild) ·
    [pipeline artefacts](../unit5/topic2.md#artefacts-and-how-data-moves) ·
    [tag versus digest in a pipeline](../unit5/topic2.md#container-artefact-identity-tag-versus-digest) ·
    [deployment actions for ECS](../unit5/topic2.md#deployment-actions-for-ecs-and-eks) ·
    [iam:PassRole](../unit8/topic1.md#iampassrole) ·
    [IAM policy versions](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-versioning.html)

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 suggests `aws login`, which signs in to **real AWS**. The answer is always `source configs/course.env` or a missing `floci` profile (Errata 01 Section 3).

---

## 2. Prerequisites

- **Lab 11 complete** (Exercise 5 optional; Step 1 tolerates its absence). Labs 01 to 06 complete; Labs 07 to 10 helpful.
- `docker info` must succeed for your user: there is no path through this lab without a Docker daemon. About 1 GB of free disk.
- `python3`, `zip` and `unzip`, as in Lab 11.

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/floci-storage-check.sh      # PASS=16  FAIL=0
./scripts/utilities/verify-lab-04.sh           # PASS=48  FAIL=1  (or 49/0 after Lab 05 Exercise 2)
./scripts/utilities/verify-lab-05.sh           # PASS=49  FAIL=0
./scripts/utilities/verify-lab-11.sh           # PASS=46  FAIL=0  (or 38/8 on Path B or C)
docker info >/dev/null 2>&1 && echo "docker reachable"
```

If `verify-lab-11.sh` fails outside the known-benign list in Lab 11 Section 9.1, fix it first: this lab modifies the pipeline that script checks.

---

## 3. What This Lab Reuses

- From Lab 01: `USMSECSTaskExecution`, whose four `ecr:*` pull actions were written before any repository existed; Step 5 creates the repository they were always about, and the execution role needs no change. `usms-ecs-exec-role` and `usms-ecs-task-role` are passed in Step 15.
- From Lab 04: `usms-ecs-cluster`, family `usms-enrolment` (rev 2), service `usms-enrolment-svc`, container `enrolment-api` on port 80 (the join key in `imagedefinitions.json`, Step 14), the circuit breaker (Step 18) and `--force-new-deployment`'s "the tag now points at a different image", which Step 17 makes true.
- From Lab 05: `usms-enrolment-alb` and `usms-enrolment-tg`, which a blue/green setup would pair (Step 19).
- From Lab 06: the scalable target that a deployment-controller change would strand (Step 19).
- From Lab 11: `usms-pipeline-artifacts`, `usms-enrolment-build`, `usms-enrolment-pipeline` (Source, Build), both roles and policies, `labs/lab-11-cicd/app/` with its buildspec and local runner.

```text
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

---

## 4. What We Are Building

```text
  BEFORE (end of Lab 11)                     AFTER (end of this lab)

  source -> build -> artifact                 source -> build -> artifact -> deploy
                       │                                    │                   │
                    (stops)                          builds an image      updates the ECS
                                                     pushes to ECR        service, which pulls
                                                                          the image and replaces
                                                                          its tasks
```

Four new things (an ECR repository, a `Dockerfile`, a tagged image, a third pipeline stage) and three modified ones (the buildspec gains an image build and an `imagedefinitions.json` writer; both pipeline IAM policies gain a v2; the task definition family gains revisions naming your image). The application's four files do not change: this lab is about how they reach a running task.

---

## 5. Architecture

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
one the service is running and changes one field in it. That is a genuine constraint, and Section 11
returns to it - a change to the task definition's memory, environment variables or log configuration
cannot travel through this mechanism at all.

---

## 6. Directory Structure

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

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    Unless a step shows its own **Run from** block, commands run from the repository root. Steps 7 and 14 run inside `labs/lab-11-cicd/app/`.

!!! tip "Shell variables die with the terminal"
    `ECR_URI`, `IMAGE_TAG`, `IMAGE_DIGEST` and `EXEC_ID` are captured with `$(...)`; Step 20 writes what later labs need to `configs/lab-12.env`.

### Step 1 - Start Floci, and read what Lab 11 left you

Start the environment and read Lab 11's inventory rather than assuming it.

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

`outputs/lab-11-lab08b-readiness.txt` is what Lab 11 Exercise 5 left: the artifact key and the `imagedefinitions.json` your build produced. If it exists Step 14 replaces it; if not, Step 14 writes it for the first time.

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

This lab reads Labs 01, 04, 05 and 11 and writes a file the CloudFormation lab will read.

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

**What to look for:** no `MISSING`. `USMS_ENROLMENT_CONTAINER` must be `enrolment-api` and `USMS_PIPELINE_NAME` must be `usms-enrolment-pipeline`; everything keys off those two strings.

---

### Step 3 - Probe the deployment surface

Find out now whether this build supports ECR, the ECS deploy action and (for Step 19 only) CodeDeploy.

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
  echo "         and validated. Section 11 says exactly what to claim."
fi
printf 'USMS_CICD_DEPLOY_PATH=%s\nUSMS_CODEDEPLOY_SUPPORTED=%s\n' "$P" "$DEPLOY_OK" \
  > outputs/lab-12-deploy-probe.txt
echo "recorded in outputs/lab-12-deploy-probe.txt"
EOF

chmod +x scripts/utilities/deploy-support-probe.sh
bash -n scripts/utilities/deploy-support-probe.sh && echo "syntax OK"
./scripts/utilities/deploy-support-probe.sh
```

The ECR probe does not stop at "the API answered": it reads back the `repositoryUri`, because that is what `docker push` needs, then deletes the probe repository with `--force`.

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

**What to look for:** the `repositoryUri` is not `<account>.dkr.ecr.<region>.amazonaws.com`. **Never type a registry host in this lab**; every step derives it from `describe-repositories`.

**Checkpoint 1**

```text
outputs/lab-12-deploy-probe.txt
 ├── USMS_CICD_DEPLOY_PATH=<A|B|C>
 └── USMS_CODEDEPLOY_SUPPORTED=<yes|no>
```

---

### Step 4 - Publish the ECR port range

Only `4566` is published. An ECR registry may be served from the `5100-5104` range, which a host `docker push` cannot reach until it is published. This step uncomments exactly one line of `docker-compose.yml`.

!!! danger "Read before editing docker-compose.yml"
    **What will change:** one commented line in `docker-compose.yml` becomes active, publishing five
    host ports.

    **What depends on it:** nothing yet. `floci-up.sh` recreates the container to apply it, and a
    recreate is not a data loss - the bind mount and hybrid storage keep every resource you have built.

    **Reversible?** Yes. Re-comment the line and re-run `floci-up.sh`.

    **Effect on later labs:** none, except that five more host ports are occupied. Do **not** uncomment
    the other ranges; publishing roughly six hundred ports makes Docker Desktop crawl and collides on
    shared machines.

**Command**

```bash
cd ~/aws-floci-course

grep -n '5100-5104' docker-compose.yml
```

**What to look for:** one commented line inside `ports:`. If `grep` prints nothing, add the range by hand under `ports:` in the style of the `4566` line, and note it.

Uncomment it in your editor, or with this guarded substitution:

```bash
cp docker-compose.yml "docker-compose.yml.bak-$(date +%Y%m%d%H%M%S)"

sed -i.tmp -E 's/^([[:space:]]*)#[[:space:]]*(- *"?5100-5104)/\1\2/' docker-compose.yml
rm -f docker-compose.yml.tmp

grep -n '5100-5104' docker-compose.yml
```

`sed -i.tmp` followed by `rm` is the in-place form that works on both GNU and BSD (macOS) `sed`. The `cp` backup matters: this file decides how Floci runs.

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

**What to look for:** `4566` and `5100-5104` published. A recreated container is expected: ports cannot be added to a running one. Then confirm the recreate lost nothing:

```bash
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{Name:serviceName,Status:status,Desired:desiredCount,TaskDef:taskDefinition}' \
  --output table
```

**What to look for:** the service still `ACTIVE` on Lab 04's task definition (create, perturb, read back). If it is gone you are in memory mode: stop and run `floci-storage-check.sh`.

---

### Step 5 - Create the ECR repository

A private place for your image: the repository Lab 01's `USMSECSTaskExecution` has described since before it existed.

!!! info "Tags and digests"
    A repository holds every build of one thing, distinguished by **tag** (`r6`, `r7`). A tag is **mutable** by default: a second push moves it. The **digest** (`sha256:...`) is derived from the content and cannot move. This lab uses `MUTABLE` deliberately so Step 18 can show what goes wrong; Exercise 2 argues for `IMMUTABLE`. See [images, tags and digests](../unit2/topic1.md#images-layers-manifests-tags-and-digests).

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

```text
aws
 └── ecr                                the SERVICE (Elastic Container Registry)
      └── create-repository             the OPERATION
           ├── --image-tag-mutability   MUTABLE lets a tag be moved; IMMUTABLE does not
           ├── --image-scanning-configuration  scan each pushed image for known CVEs
           └── --encryption-configuration      AES256 is the default; KMS is the alternative
```

`scanOnPush=true` is useful and nearly free on real AWS; here it is stored, not performed (Section 11).

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

`${ECR_URI%%/*}` strips everything from the first `/`, leaving the registry host. **What to look for:** two lines, the second a host and port with no path. If `ECR_REGISTRY` equals `ECR_URI`, the URI is not pushable: that is Path B, and Step 8 says what to do.

---

### Step 6 - Authenticate Docker against the registry

ECR issues a twelve-hour password for the username `AWS`. It is a credential, so it goes to `docker login` through **standard input**, never onto the command line (visible in `ps` and shell history).

```bash
aws ecr get-login-password --region "$AWS_REGION_COURSE" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
```

The pipe means nothing writes or echoes the token. Docker keeps a reference in `~/.docker/config.json`; on a shared machine, know that file exists.

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

Turn the build output into an image with a deliberately small Dockerfile.

!!! info "Build context"
    `docker build .` sends `.` (the **build context**) to the daemon, and `COPY` can only read from it. The image ships the built `dist/`, not the source, tests or buildspec; `.dockerignore` enforces that and keeps the context small. See [Dockerfiles and the build cache](../unit2/topic1.md#dockerfiles-and-the-build-cache).

**Run from**

```text
aws-floci-course/labs/lab-11-cicd/app/
```

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

- `nginx:1.27-alpine` is the base Lab 07 used, so it is probably cached; Lab 04's `public.ecr.aws/nginx/nginx:stable-alpine` also works (Exercise 1).
- `.dockerignore` excludes `src/` and `config/` while `COPY dist/` ships their processed output: what a build consumes versus what an image ships.

**Verify**

```bash
cd ~/aws-floci-course
ls -l labs/lab-11-cicd/app/Dockerfile labs/lab-11-cicd/app/.dockerignore
test -d labs/lab-11-cicd/app/dist && echo "dist/ present - Step 8 can build" \
  || ./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app >/dev/null \
     && echo "dist/ rebuilt by the local runner"
```

**What to look for:** both files exist and `dist/` is present. If the Lab 11 Step 14 local runner had to rebuild it, that is fine.

---

### Step 8 - Build the image and push it, by hand

Prove the image path in your own terminal before a pipeline walks it.

```text
  usms-enrolment:r6                                   a local name
  000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r6     the pushable name
  sha256:8f3a91c4...                                  the digest - the content's identity
```

`docker tag` adds a name and copies nothing; `docker push` needs a name that includes the registry host; the digest falls out of the content and is the only one of the three that cannot lie.

**Command - part 1, set the release and rebuild the output**

```bash
cd ~/aws-floci-course

printf 'r6\n' > labs/lab-11-cicd/app/VERSION
./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app | tail -12

IMAGE_TAG=$(tr -d '[:space:]' < labs/lab-11-cicd/app/VERSION)
echo "image tag will be: $IMAGE_TAG"
```

**What to look for:** smoke tests pass and `build-metadata.json` says `"release": "r6"`; the image carries that file, so a running container can say which build it came from.

**Command - part 2, build, tag, push**

```bash
cd labs/lab-11-cicd/app

docker build -t "usms-enrolment:$IMAGE_TAG" .

docker tag "usms-enrolment:$IMAGE_TAG" "$ECR_URI:$IMAGE_TAG"

docker push "$ECR_URI:$IMAGE_TAG"

cd ~/aws-floci-course
```

`build` uploads nothing and `push` builds nothing; `tag` is the step people skip and then cannot explain.

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

**What to look for:** the last line's **manifest digest**. It differs from the build's `writing image sha256:` (the config digest); the manifest digest is what ECR indexes and a task definition can pin.

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

`Pushed` is the client reporting its own success; the registry's read-back is the evidence.

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

`describe-images --image-ids imageTag=r6` maps the mutable name to the immutable digest. The appended line in `outputs/lab-12-image-digest.txt` is a small ledger Step 18 and Section 14 use.

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

Delete your local copy; if the image can be fetched back **by digest**, it is in the registry, not just your cache.

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

**What to look for:** `no local copy remains`, then a successful pull. `repository@sha256:...` addresses by digest: a task definition naming a digest deploys exactly the tested bytes; one naming a tag deploys whatever the tag points at when the task starts.

**Checkpoint 3**

```text
ECR usms-enrolment
 └── r6   sha256:1c92f0ab...   pushed, deleted locally, pulled back by digest
outputs/lab-12-image-digest.txt
 └── one line: tag, digest, timestamp
```

---

### Step 10 - Register a task definition revision that names your image

The service runs `usms-enrolment:2` with the placeholder image. Produce revision 3, identical except the image, by deriving it from revision 2 rather than writing it from memory.

!!! info "Describe, strip, register"
    Writing a task definition from scratch silently drops something (log configuration, health check, `runtimePlatform`). Instead: `describe-task-definition`, remove the fields AWS owns, change one value, register. The read-only fields are `taskDefinitionArn`, `revision`, `status`, `requiresAttributes`, `compatibilities`, `registeredAt`, `registeredBy` and `deregisteredAt`; leaving one in fails validation one field at a time. The ECS deploy action does exactly this in Step 16. See [ECS task definitions](../unit2/topic1.md#ecs-task-definitions).

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

The Python strips the read-only fields, finds the container **by name** (position is not a contract), and fails loudly if it is absent. `grep -c '\$'` must print `0`.

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

**What to look for:** `Revision` `3`, `Image` your ECR URI with `r6`, and still `Cpu` `256`, `Memory` `1024` and Lab 04 Step 14's health check. Anything missing means you wrote a task definition instead of deriving one.

---

### Step 11 - Deploy revision 3 by hand, and watch it

Do it manually once so you recognise what the pipeline does later. From here the service runs your application.

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

A polling loop rather than `aws ecs wait services-stable`, which on this emulator can exhaust its attempts silently (Lab 04). It prints the deployment table every poll and exits 0 when there is one deployment with running equal to desired.

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

**What to look for:** two rows during the rollout (new `PRIMARY` up, old `ACTIVE` down) collapsing to one. That overlap is Lab 04's `minimumHealthyPercent 100` / `maximumPercent 200`. See [the rolling update](../unit2/topic3.md#deployment-the-rolling-update).

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

From Step 14 the build pushes to ECR, so the build role needs push permission. This is the course's first policy version you create yourself.

!!! info "Two facts this step relies on"
    - **A version is not a default.** `create-policy-version` adds a version; until `--set-as-default` (or `set-default-policy-version`) every principal still evaluates v1. A policy holds at most **five** versions.
    - **`ecr:GetAuthorizationToken` must be on `Resource: "*"`.** It is registry-level, with no repository to scope against; scoping it denies it, and the failure surfaces as a `docker login` authentication error, not an IAM one.

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

v1 plus two statements. The five push actions (`BatchCheckLayerAvailability`, `InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage`) are the order a `docker push` performs; missing one fails the push partway with an HTTP status, not an action name.

**Verify**

```bash
aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
  --query 'Policy.{Name:PolicyName,Default:DefaultVersionId,Versions:AttachmentCount}' --output table

aws iam list-policy-versions --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase \
  --query 'Versions[].{Version:VersionId,Default:IsDefaultVersion,Created:CreateDate}' --output table
```

**What to look for:** `DefaultVersionId` `v2`, and `v1` with `Default: False`. If the default is still `v1`, run `aws iam set-default-policy-version --policy-arn ... --version-id v2`; the mistake is otherwise silent.

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

Hint: Lab 11's v1 shows the scoped `PassRole` shape; the ECS calls are the ones Step 10 made by hand.

---

### Step 13 - Let the build run Docker

A CodeBuild container cannot run `docker build` unless the project enables `privilegedMode`, which gives it a Docker daemon and elevated capabilities. That is a real privilege, which is why who can trigger the build matters (and why the pipeline role's `StartBuild` is scoped to one project). See [AWS CodeBuild](../unit5/topic1.md#aws-codebuild).

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

- `update-project --cli-input-json` takes `name` plus only the members you change, leaving source, artifacts, role and tags alone.
- `environment` is replaced **as a whole**: omit `environmentVariables` and they are cleared.
- Unquoted heredoc, so `${ECR_URI}` is substituted; `grep -c '\$'` must print `0`.

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

**What to look for:** `Source` still `CODEPIPELINE` (you did not undo Lab 11 Step 18), `Role` still `usms-codebuild-role`, `Privileged` `true`, and `Repo` your ECR URI.

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

This makes the pipeline capable of deploying: the build produces an image and the small file telling the deploy action which image to use.

!!! info "`imagedefinitions.json`, exactly"
    A JSON **array**; each element has `name` (the **container name** in the task definition, not the service, family or repository) and `imageUri` (the full pushable reference). See [deployment actions for ECS](../unit5/topic2.md#deployment-actions-for-ecs-and-eks).

```json
[
  {
    "name": "enrolment-api",
    "imageUri": "000000000000.dkr.ecr.us-east-1.<host>:4566/usms-enrolment:r7"
  }
]
```

Three ways this file goes wrong, all of which produce failures that do not mention the file:

- It is a JSON **object** rather than an array. The deploy action rejects it.
- `name` does not match a container in the task definition. The action reports that it could not find
  the container, in wording that varies.
- It is not at the **root** of the input artifact. This is why `artifacts.base-directory: dist` matters
  and why the build writes the file into `dist/` rather than beside the source.

The image build is **guarded**: if the build container has no Docker daemon it skips the build and still writes `imagedefinitions.json`, naming the tag Step 8 pushed by hand, and says so in its log.

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
            || echo "push failed - see Section 10; the deploy stage will use the existing tag"
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

- `env.variables` gains `IMAGE_REPO_URI` with a default of `nginx`; Step 13's project variable overrides it.
- `pre_build` logs in to the registry if Docker is available, deriving the host with `${IMAGE_REPO_URI%%/*}`.
- `build` builds and pushes (guarded), then always writes `imagedefinitions.json`, reading the container name from `config/service.json`.
- `build-metadata.json` gains `imageUri`, which turns artifacts into an audit trail.
- Unchanged: `artifacts.base-directory: dist`, which puts the file at the artifact root.

!!! warning "Heredoc quoting: three levels"
    The outer `<< 'BUILDSPEC'` is quoted so every `$` reaches the file; the inner `<< META` is unquoted because it must expand at build time; the inner `<< 'IMGDEF'` is quoted so the Python reaches the interpreter as written, which is why the image URI is passed through the environment rather than interpolated into program text.

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

One assertion after the container-name check: the file parses, is a one-element list, and names `enrolment-api`, covering the three failure modes above.

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

**What to look for:** eight `ok` lines and an `imageUri` with your registry host. `nginx:r6` means the command-line `IMAGE_REPO_URI` did not reach the runner.

!!! info "Why the variable on the command line wins"
    The runner generates `export IMAGE_REPO_URI="${IMAGE_REPO_URI:-nginx}"`, so a value already in your environment overrides the default. CodeBuild behaves the same way: a project-level variable (Step 13) wins over a buildspec `env.variables` default. Read `imagedefinitions.json` before you believe a green pipeline.

**Command - part 3, ship it**

```bash
./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip | tail -3

aws s3api put-object \
  --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip \
  --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text
```

**What to look for:** a new version ID. Do **not** start the pipeline yet: Step 16 adds the Deploy stage and Step 17 runs it.

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

The deploy action runs as the **pipeline** role. It reads the service, reads and registers task definitions, updates the service, and must pass the two ECS roles, because registering a task definition that names an execution role and a task role hands both to ECS.

!!! info "The second `PassRole`"
    Lab 11's v1 passes `usms-codebuild-role` to `codebuild.amazonaws.com`. Without `iam:PassRole` on the two ECS roles, `RegisterTaskDefinition` is refused with an error naming `iam:PassRole`, not the ECS call. The receiving service is `ecs-tasks.amazonaws.com` (Lab 04's `policies/trust-ecs-tasks.json`), not `ecs.amazonaws.com`; the wrong value is a condition that never matches. See [iam:PassRole](../unit8/topic1.md#iampassrole).

Compare your `notes/lab-12-my-pipeline-policy.json` from Step 12's "Your turn" with what follows.

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

Six statements, three unchanged from v1. The new ones:

- `DeployToTheEnrolmentServiceOnly` names **one service ARN**.
- `ReadAndRegisterTaskDefinitions` is on `Resource: "*"` because `RegisterTaskDefinition` creates a resource with no ARN yet (like `GetAuthorizationToken`). The `PassRole` statement bounds it; Exercise 4 tests whether that suffices.
- `PassTheTwoEcsRolesAndOnlyToEcsTasks` names exactly Lab 01's two roles and the service that may receive them.

**Verify**

```bash
aws iam get-policy-version \
  --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
  --version-id v2 \
  --query 'PolicyVersion.Document.Statement[].Sid' --output json

aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase \
  --query 'Policy.DefaultVersionId' --output text
```

**What to look for:** six Sids and `v2` as default. If the default is `v1`, run `aws iam set-default-policy-version --policy-arn ... --version-id v2`.

---

### Step 16 - Add the Deploy stage

Turn the two-stage pipeline into three stages, through a replace-only API where careless work destroys something.

!!! danger "Read before running update-pipeline"
    **What will be replaced:** the entire pipeline document. `update-pipeline` has no merge semantics
    and no partial update. Whatever you send becomes the pipeline.

    **What depends on it:** both stages you built in Lab 11. If you send a document containing only
    the Deploy stage, Source and Build are deleted - with a successful API response and no warning.

    **Reversible?** Only by rebuilding the document from Lab 11's `templates/lab-11-pipeline.json`,
    which is why that file is committed.

    **Effect on later labs:** the CloudFormation lab re-declares this pipeline and compares it with
    what you built by hand. A pipeline missing two stages makes that comparison meaningless.

```text
   get-pipeline  ──>  { "pipeline": {...}, "metadata": {...} }
                          │              └── created/updated timestamps and ARN - NOT sent back
                          │
                       modify: append one stage to pipeline.stages
                          │
   update-pipeline <── { "pipeline": {...} }
```

Take `--query 'pipeline'` on the read so `metadata` is never sent back. Replace-only APIs are a family (`put-bucket-notification-configuration` in Lab 10, `update-assume-role-policy` in Lab 09); recognise the family.

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

**What to look for:** two stages. Three means you already ran this step (skip to the verify); one means something went wrong: restore from `templates/lab-11-pipeline.json` first.

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

The `assert` and `raise` refuse to edit a pipeline whose first two stages are unexpected, or to add a second Deploy stage: a script editing a replace-only resource should be paranoid. `DeploymentTimeout` is in **minutes**, as a string.

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

**What to look for:** three rows and the artifact chain down `Input`: nothing, `SourceOutput`, `BuildOutput`. That column is the pipeline's data flow. See [pipeline artefacts](../unit5/topic2.md#artefacts-and-how-data-moves).

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

Hint: ask which artifact contains `dist/` at its root.

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

Change a version number and have a running service change with no human typing `aws ecs update-service`. A green Deploy stage is a report; the evidence is that the service's revision **increased** and that the new revision's image is the one the build produced. Check both.

**Command - part 1, record the before**

```bash
BEFORE_TD=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].taskDefinition' --output text)
echo "before: $BEFORE_TD"
```

**What to look for:** `.../usms-enrolment:3` from Step 11. The proof is a comparison; keep both halves.

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

`Cpu` 256, `Mem` 1024, both roles, log driver `awslogs`: the deploy action copied revision 3 and changed one field, the mechanism from Section 5 observed.

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

Deploy a release whose image does not exist, watch what happens, and roll back.

!!! info "What the circuit breaker does, and does not do"
    Lab 04 set `deploymentCircuitBreaker: {enable: true, rollback: true}`. On real AWS, if enough new tasks fail to start or fail health checks, ECS marks the deployment `FAILED` and redeploys the last steady-state revision. It does **not** notice an app that starts and then misbehaves, does not roll back a deployment that already completed, and does not undo anything outside the service (a migration stays run). An unpullable image is its clearest case. See [the deployment circuit breaker](../unit2/topic3.md#the-deployment-circuit-breaker).

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

**What to look for:** `r6` and `r7`, **no `r8`**. If your build *can* push, temporarily point the project's `IMAGE_REPO_URI` at a nonexistent repository or stop Docker; the point is a deploy whose image cannot be pulled.

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

**What to look for:** the service back on revision 4. Rollback is pointing the service at a revision that already exists; there is no undo API, which is why a task definition family is an append-only log.

Now fix the source so it no longer deploys a missing image:

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

Hint: think about what a later `describe-task-definition` or audit script would show about revision 5.

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

Your deploy action does a **rolling** deployment. **Blue/green** runs the new version as a separate task set, tests it on its own listener, then switches production traffic. This step writes and validates the documents for it and does not run them: this emulator has no CodeDeploy. See [blue/green with CodeDeploy](../unit2/topic3.md#bluegreen-with-aws-codedeploy).

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

The deployment group names **two** target groups and **two** listeners: the structural heart of blue/green. Lab 05 created one of each; Exercise 3 creates the second. `CodeDeployDefault.ECSLinear10PercentEvery1Minutes` shifts ten percent a minute; the alternatives are `ECSAllAtOnce` and canary configurations, a business decision expressed as a name.

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

Write what the CloudFormation lab and your report will need; `ECR_URI`, `IMAGE_DIGEST` and `EXEC_ID` die with this terminal.

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

- **Unquoted heredoc**, so every `$(...)` runs now. Each lookup ends in a `grep` filter and an `|| echo` default, so a missing resource reads `not-created` or `unknown` rather than `None` (the Lab 06 idiom).
- `USMS_ECR_REGISTRY` uses `cut -d/ -f1`, not `${...%%/*}`, because inside an unquoted heredoc your shell would expand that against a variable that does not exist there.

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

**What to look for:** `stages=3`, both policy versions `v2`, and a `digest` beginning `sha256:` on Path A.

---

### Step 21 - Commit

```bash
git status --short
```

**What to look for:** read the list before staging. **No file under `outputs/`**, and no `docker-compose.yml.bak-*`. If the Step 4 backup shows up, ignore it rather than remembering not to commit it:

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

`docker-compose.yml` is staged: Step 4's change is now part of the environment contract. `templates/lab-12-taskdef-base.json` and `templates/lab-12-pipeline-current.json` are deliberately **not** staged: they are snapshots of live state, and committing them invites someone to apply a stale one.

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-12.sh`

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

Known benign failures:

| Failure | Benign when | What it means |
| --- | --- | --- |
| The five ECR checks | Step 3 reported Path B | No usable registry on this build. Your documents are still correct |
| `tag r7 is present` | You are on Path B, or you never pushed `r7` | Push it, or record that the deploy references an unpushed tag |
| The four pipeline checks | Path C | CodePipeline is absent. The three-stage document is still written and validated |
| `task definition names the ECR repo` | Never after Step 10 | **Not benign.** Step 10 did not register, or the service is on an older revision |
| `USMSCodeBuildBase default is v2` | Never after Step 12 | **Not benign.** You created a version without setting it as default |
| `source type is still CODEPIPELINE` | Never | **Not benign.** An over-broad `update-project` undid Lab 11 Step 18 |
| `no secret is tracked` | Never | **Not benign.** Fix `.gitignore`, then `git rm --cached` |

### 8.2 Build the end-of-course cleanup script

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

---

## 9. Checkpoints

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

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, the CodePipeline ECS deploy provider is unavailable and `describe-images` is inconsistent. Diagnose first, then use the alternative in [Known Issues - Lab 12](known-issues.md#lab-12-ecs-pipeline-deploy). It states what the alternative does and does not prove.

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

## 11. Floci vs Real AWS

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

**What you observed versus recorded.** On Path A you observed an image built and its digest, a revision derived with one field changed, the service pointing at your image, a three-stage pipeline, an undetected deploy of an unpushed image, and a rollback by naming a revision. You recorded but could not see enforced: the ECR push permissions, the second `iam:PassRole`, the single-service ARN, `scanOnPush` and tag mutability, and the CodeDeploy documents. Blue/green, a tripping circuit breaker, scan results and lifecycle expiry are not available at all. On Path B or C, move lines from observed to recorded in your report: an honestly stated smaller claim is worth more than an overstated one.

**Where Floci is nicer than reality (traps on real AWS):** images appear instantly and cost nothing (real ECR bills storage, which is what lifecycle policies are for); no Docker Hub pull rate limits (real pipelines mirror base images); no propagation delay on a just-registered revision; and nothing fails at 3am, so every failure here was one you caused.

---

## 12. Independent Lab Exercises

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
  Section 8's verification does not check this field and a later lab might be surprised.

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
Section 14's question 7.

**Hints**

`docker tag` plus `docker push` retags. `describe-images` will then show the old digest with no tags,
or with the tag moved, depending on your build. The chain you are testing is: does a task definition
that names a *tag* let you prove which bytes ran?

---

## 13. Lab Assessment Checklist

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
- [ ] Section 14 answered in prose in `notes/lab-12-notes.md`

### 13.1 In-class assessment - Practical 7

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
actions are not modelled on this emulator and cite the Step 3 probe or Section 11's table - a student
who claims to have tested it has not.

---

## 14. Review Questions

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

## 15. KEEP vs CLEAN UP

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

Do **not** run `scripts/cleanup/lab-12-cleanup.sh` now; it is for the end of the course, in the order Section 8.2 gives.

**The architecture you now have**

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

---

## 16. Preparation for the Next Lab

The next laboratory is the S3 configuration document Lab 10 Section 17 promised (still unwritten, with no fixed number). Nothing here blocks it. It configures `usms-student-data`; its Exercise 5 does the same to `usms-pipeline-artifacts`, which now gains an object per execution with no lifecycle rule, encryption configuration or bucket policy.

| Artefact | From | How it is used |
| --- | --- | --- |
| `usms-student-data` | Lab 10 Step 5 | Configures it: versioning, default encryption, public-access block, lifecycle |
| `outputs/lab-09-bucket-policy-draft.json` | Lab 09 Ex 5 | Applies it as the bucket's resource policy |
| `usms-pipeline-artifacts` | Lab 11 Step 5 | The second bucket in Exercise 5 - versioned already, unmanaged otherwise |
| `configs/lab-11.env`, `configs/lab-12.env` | Steps 20, and Lab 11 Step 21 | Sourced; the artifact bucket's name comes from there |

**Be careful with lifecycle rules there.** Expiring noncurrent versions in `usms-pipeline-artifacts` also expires the source archive versions this lab's executions reference, so their provenance cannot be re-established. That is a trade-off (storage cost against provenance retention) to decide explicitly, not by default.

**Pre-session checks**

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-12.sh          # PASS=45  FAIL=0  (or your path's count)
./scripts/utilities/verify-lab-11.sh          # PASS=46  FAIL=0
grep -c '^export' configs/lab-12.env          # 26
aws s3api head-bucket --bucket usms-student-data && echo "Lab 10's bucket is present"
```

**Snapshot before you finish**

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

---

## Appendix - New CLI and JMESPath patterns

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

# Lab 11 - Building a CI/CD Pipeline with AWS CodePipeline and CodeBuild

*Practical 7 - Practical 5 in the module descriptor. The first half of the pipeline: getting
source into a build, and getting a build to run the same way every time.*

!!! info "Numbering - read this once"
    Your module descriptor numbers this practical **5**. This course delivers it as **Practical 7**,
    because Practical 2 ran to three documents and the delivery schedule has since reordered the
    back half of the course. Laboratory numbering follows the *dependency graph*, not the practical
    numbering:

    ```text
    Practical 1  ->  Lab 02 (VPC), Lab 03 (EC2)
    Practical 2  ->  Lab 04, Lab 05                (ECS + Fargate, ECS + ALB)
    Practical 3  ->  Lab 06                         (service auto scaling)
    Practical 4  ->  Lab 07, Lab 08                (EKS)          descriptor Practical 3
    Practical 5  ->  Lab 09                          (security)     descriptor Practical 8
    Practical 6  ->  Lab 10                          (edge functions)
    Practical 7  ->  Lab 11, Lab 12                (CI/CD)        descriptor Practical 5   <- here
    ```

    Every student builds this whole sequence, in order: ECS with its ALB and autoscaling layer
    (Labs 04-06), then EKS as a second deployment target for the same application (Labs 07-08), then
    security (Lab 09), then Lambda (Lab 10), and now this pipeline. There is no alternate track and no
    reserved slot. Lab 10 Section 17 flagged that the enrolment bucket still needs a dedicated Amazon
    S3 configuration document; that document has not been written yet, and when it is, it takes
    whatever number fits it into this graph at the time - not a number promised in advance.

    This lab does **not** depend on that (still unwritten) S3 lab. It depends on Labs 01, 04, 05 and
    06, all of which you have completed.

---

## 1. Lab Overview

Everything you have built in this course, you have built by typing. You created the ECS cluster by
typing `aws ecs create-cluster`. You created the service by typing `aws ecs create-service`. When
Lab 04 gave you a second revision of the task definition, you rolled it out by typing
`aws ecs update-service --task-definition usms-enrolment:2`.

That works. It does not scale, and more importantly it is not *reproducible*. Nobody - including
you, three weeks from now - can say with certainty which commands produced the running system, in
what order, from which version of which file. A university that runs a student records system has to
be able to answer that question, because at some point somebody will ask "when did the enrolment
service change, who changed it, and what exactly did they change?"

A **pipeline** is the answer. It is a machine that watches a place where source code lives, and when
that source changes, runs a fixed sequence of stages against it: fetch it, build it, test it, and -
in Lab 12 - deploy it. The sequence is written down. It runs the same way every time. It leaves a
record.

This laboratory builds the first two stages of that machine:

- a **Source** stage, which fetches a versioned archive of the enrolment service's source from S3,
- a **Build** stage, which hands that archive to **AWS CodeBuild**, a managed build service that runs
  your commands inside a disposable container and hands back whatever files you tell it to keep.

The commands CodeBuild runs are not configured in the console or in the CLI. They live in a file
called `buildspec.yml`, which sits *in your source tree*, next to the code it builds. That is the
single most important idea in this laboratory, and Section 8 Step 8 spends a long time on it.

Lab 12 adds the third stage - Deploy - and points it at the ECS service you built in
Lab 04 and put behind a load balancer in Lab 05. Lab 12 also carries the Practical 7 in-class
assessment.

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 will suggest `aws login`. That begins a sign-in to
    **real AWS**. The answer in this course is always `source configs/course.env` or a missing
    `floci` profile - never a sign-in. See Errata 01 Section 3.

### 1.1 What is genuinely new here

| New thing | Why it matters |
| --- | --- |
| `buildspec.yml` | Build instructions live in the repository, versioned with the code, not in a console setting somebody changed last March |
| CodeBuild service role | The build container is a principal. It has an identity, and what it can reach is a policy decision |
| The artifact store | Every stage hands the next one a zip file in S3. Understanding this makes CodePipeline stop being magic |
| S3 source versioning | CodePipeline refuses an unversioned S3 source bucket. The reason is worth five minutes |
| Pipeline JSON | A pipeline is a document. `get-pipeline` gives it to you, `update-pipeline` takes it back |
| `iam:PassRole` | The pipeline does not build. It asks CodeBuild to build *as* a role. That handoff is a permission of its own |

### 1.2 Time

Roughly three hours if CodeBuild runs on your build of Floci, roughly two if it does not and you take
the local path in Step 14. Both paths finish the lab; they differ in what you *observe* versus what
you *record*.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. Explain what a CI/CD pipeline is in terms of stages, actions, and the artifacts that pass between
   them - and say where each artifact physically lives.
2. Create and configure an S3 artifact store, and explain why CodePipeline requires versioning on an
   S3 source bucket rather than merely recommending it.
3. Write a `buildspec.yml` from scratch, naming the purpose of every top-level key: `version`, `env`,
   `phases`, `artifacts`, `cache`, and `reports`.
4. Create a CodeBuild service role with a policy scoped to the log group and the bucket prefixes the
   build actually needs, and justify each statement by reading it.
5. Create a CodeBuild project, start a build, and read `batch-get-builds` to determine which phase
   failed and why.
6. Create a CodePipeline with a Source stage and a Build stage, expressed as a JSON document, and
   read `get-pipeline-state` to determine where an execution is.
7. Explain `iam:PassRole`, and identify which principal passes which role to which service in this
   pipeline.
8. Diagnose a failed pipeline execution by working backwards from the stage state to the build phase
   to the command that exited non-zero.
9. Distinguish what your build actually proved from what it merely reported, and say which of the
   two your evidence supports.

---

## 3. Prerequisites

Before you start, all of the following must be true.

- Labs 01, 02, 03, 04, 05 and 06 complete. Lab 06, Lab 07-08 (EKS), and Lab 09 (security) are
  helpful but not required; Step 2 tolerates their absence.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`.
- A terminal in which a **new window** already has `AWS_PROFILE` and `COURSE_ROOT` set. If that is
  not true, you have the defect described in Errata 01 and you should fix it now rather than halfway
  through Step 12.
- `docker` available to your user, because CodeBuild on Floci runs builds in Docker containers.
- `python3` on your path. This lab uses it for JSON surgery on the pipeline document, the way earlier
  labs used it for `python3 -m json.tool`.
- `zip` and `unzip` on your path. Check now: `command -v zip unzip`. On a bare Debian image neither
  is installed; `sudo apt-get install -y zip unzip` fixes it. Step 11 gives a `python3 -m zipfile`
  fallback if you cannot install them.

Baseline verification. Every one of these should pass before you create anything:

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/floci-storage-check.sh      # PASS=16  FAIL=0
./scripts/utilities/verify-lab-04.sh           # PASS=48  FAIL=1  (or 49/0 after Lab 05 Exercise 2)
./scripts/utilities/verify-lab-05.sh           # PASS=49  FAIL=0
./scripts/utilities/verify-lab-10.sh            # PASS=51  FAIL=0
```

If `verify-lab-05.sh` fails, stop. Lab 12 deploys to the service that script checks, and a pipeline
pointed at a service that is not there teaches nothing except how to read a `ServiceNotFoundException`.

---

## 4. Connection to Previous Labs

### 4.1 Current environment

```text
Created in previous labs:
- Lab 01: IAM foundation - 3 groups, 3 users, 3 roles, 5 policies, 1 instance profile
- Lab 01: Floci under Compose, hybrid storage, persistence proven
- Lab 02: usms-vpc (10.0.0.0/16), two public + two private subnets, IGW, NAT, route tables
- Lab 03: usms-web-01 and usms-db-01
- Lab 04: usms-ecs-cluster, task family usms-enrolment (rev 2), service usms-enrolment-svc,
           roles usms-ecs-exec-role + usms-ecs-task-role, policy USMSECSTaskExecution,
           log group /usms/ecs/enrolment, container enrolment-api on port 80
- Lab 05: usms-enrolment-alb, target group usms-enrolment-tg (target-type ip), HTTP:80 listener,
           usms-alb-sg, the service registered as a load-balanced target
- Lab 06: scalable target on service/usms-ecs-cluster/usms-enrolment-svc, min 2 max 10
- Lab 09 (security, if completed): usms-deploy-role, USMSDeployBase, USMSPermissionsBoundary
- Lab 10: bucket usms-student-data, three Lambda functions, an S3 notification

Created in this lab:
- usms-pipeline-artifacts        S3 bucket, versioning ENABLED - the artifact store AND the source
- source/usms-enrolment-src.zip  the versioned source archive the pipeline fetches
- usms-codebuild-role            + USMSCodeBuildBase
- usms-codepipeline-role         + USMSCodePipelineBase
- usms-enrolment-build           the CodeBuild project
- usms-enrolment-pipeline        the pipeline: Source -> Build
- labs/lab-11-cicd/app/         the enrolment service source tree, including buildspec.yml
- scripts/utilities/usms-buildspec-run.sh    runs a buildspec locally, phase by phase

Required for future labs:
- usms-pipeline-artifacts        -> Lab 12's Deploy stage reads the build artifact from here
- usms-enrolment-build           -> Lab 12 extends its buildspec to build and push a container image
- usms-enrolment-pipeline        -> Lab 12 adds a third stage to this exact pipeline
- USMSCodeBuildBase              -> Lab 12 creates version 2 of this policy, adding ECR push
- labs/lab-11-cicd/app/         -> Lab 12 adds a Dockerfile here and builds it
```

### 4.2 Which earlier artefacts this lab makes newly meaningful

Two connections are worth saying out loud, because they are the moments where something you built
earlier stops being hypothetical.

**Lab 04 Step 15 taught `--force-new-deployment`** and justified it with "the image tag now points
at a different image". At the time that was a sentence about a thing that had not happened, because
nothing in this course had ever built an image. Lab 12 is where it happens. The buildspec you write
in Step 8 of *this* lab is the thing that will produce that image.

**Lab 09 Step 8 created `usms-deploy-role`** with the note that it is "the role a CI pipeline - or the
CloudFormation lab - should ever build anything as", and scoped `iam:PassRole` to three role ARNs
with an `iam:PassedToService` condition. Step 15 of this lab asks you to read `USMSDeployBase` side by
side with the `USMSCodePipelineBase` you are about to write, and say which one you would rather defend
in a review. Step 15 also gives you the equivalent pass-role statement from the EKS deployment work
(Labs 07-08) inline, so you have a third policy to weigh the same question against.

!!! note "Lab 09 artefacts are optional here"
    Lab 09 (security) is not a strict prerequisite for this lab, even though it sits earlier in the
    sequence. Every command in this lab that touches a Lab 09 artefact is guarded, and Step 2's loader
    reports which files it found. Nothing here fails if that env file is absent.

---

## 5. What We Are Building

One pipeline, two stages, and the supporting cast that makes them possible.

The **enrolment service source tree** is new. Until now the ECS task definition has pointed at
`public.ecr.aws/nginx/nginx:stable-alpine` - a placeholder, chosen in Lab 04 precisely because the
course had no application of its own. This lab writes one: a small static enrolment portal, a health
endpoint, a build metadata file, and the `buildspec.yml` that turns the tree into a deployable
artifact. It is deliberately tiny. The point is not the application; the point is that there is now
*a thing with a version number* flowing through a pipeline.

The **Source stage** fetches `source/usms-enrolment-src.zip` from `usms-pipeline-artifacts`. In a
real deployment that source would come from Git. This course uses an S3 source instead, for a reason
Section 12 explains at length: AWS CodeCommit stopped accepting new customers in July 2024, so
teaching it would be teaching a door that is closed. S3 sources are still fully supported, are what
many real pipelines use for release archives, and - crucially - make the artifact mechanism visible
instead of hiding it behind a `git clone`.

The **Build stage** hands that zip to CodeBuild, which unpacks it into a container, runs the phases
in `buildspec.yml`, and zips up whatever the `artifacts` section names. That output zip goes back
into `usms-pipeline-artifacts` under a key CodePipeline chooses.

---

## 6. Architecture

```text
                        THE PIPELINE, AND WHERE EVERY BYTE PHYSICALLY LIVES

  you                     S3: usms-pipeline-artifacts
  ┌──────────────┐        ┌────────────────────────────────────────────────┐
  │ labs/        │  zip   │  source/usms-enrolment-src.zip   (versioned)   │
  │  lab-11-    │ ─────> │      ^                                         │
  │  cicd/app/   │  put   │      │ versionId changes on every upload       │
  └──────────────┘        │      │                                         │
                          │  usms-enrolment-pipeline/SourceOutput/xxxxx.zip│ <─┐
                          │  usms-enrolment-pipeline/BuildOutput/yyyyy.zip │ <┐│
                          └────────────────────────────────────────────────┘  ││
                                                                              ││
  CodePipeline: usms-enrolment-pipeline                                       ││
  ┌────────────────────────────────────────────────────────────────────────┐  ││
  │                                                                        │  ││
  │  STAGE 1: Source                        STAGE 2: Build                 │  ││
  │  ┌──────────────────────┐               ┌──────────────────────────┐   │  ││
  │  │ action: SourceAction │               │ action: BuildAction      │   │  ││
  │  │ provider: S3         │  SourceOutput │ provider: CodeBuild       │  │  ││
  │  │ reads the zip        │ ────────────> │ project: usms-enrolment-  │  │  ││
  │  │ writes SourceOutput  │ ──────────────┘ build                     │──┼──┘│
  │  └──────────────────────┘                └──────────────────────────┘  │   │
  │        runs as usms-codepipeline-role                                  │   │
  └────────────────────────────────────────────────────────────────────────┘   │
                                    │                                          │
                                    │ iam:PassRole                             │
                                    v                                          │
  CodeBuild: usms-enrolment-build                                              │
  ┌────────────────────────────────────────────────────────────────────────┐   │
  │  a disposable Linux container, image aws/codebuild/standard:7.0        │   │
  │                                                                        │   │
  │  unpack SourceOutput  ->  read buildspec.yml  ->  run phases:          │   │
  │                                                                        │   │
  │      install  ->  pre_build  ->  build  ->  post_build                 │   │
  │                                                                        │   │
  │  collect the files named under artifacts:  ->  zip  ->  BuildOutput ───┼───┘
  │        runs as usms-codebuild-role                                     │
  │        writes to log group /aws/codebuild/usms-enrolment-build         │
  └────────────────────────────────────────────────────────────────────────┘

  Lab 12 bolts a third stage onto the right-hand side of this diagram:
      STAGE 3: Deploy  ->  ECS service usms-enrolment-svc on usms-ecs-cluster
```

Three things in that diagram are worth pausing on.

**Every arrow between stages is a zip file in S3.** CodePipeline does not stream data between
actions. Stage 1 writes a zip; stage 2 reads that zip. This is why the artifact store exists, why it
must be in the same region as the pipeline, and why a pipeline whose artifact bucket you deleted
fails in a way that looks nothing like "the bucket is gone".

**The pipeline does not build.** It calls `codebuild:StartBuild` and waits. The build runs under
`usms-codebuild-role`, not under `usms-codepipeline-role`. Two roles, two blast radii.

**The buildspec is inside the source zip.** Change the build by changing a file in the repository and
uploading a new version. You never touch the project configuration to change what a build does.

---

## 7. Directory Structure

What this lab adds. Nothing is restructured; no new top-level folder is needed.

```text
aws-floci-course/
├── configs/
│   └── lab-11.env                          NEW  - this lab's outputs
├── labs/
│   └── lab-11-cicd/                        NEW
│       ├── README.md
│       ├── exercises.md
│       └── app/                             NEW  - the enrolment service source tree
│           ├── buildspec.yml                       the build instructions
│           ├── VERSION                             one line, the release marker
│           ├── src/
│           │   ├── index.html
│           │   └── healthz.html
│           ├── config/
│           │   └── service.json                    parsed and validated by the build
│           └── tests/
│               └── smoke.sh                        the "test" the build runs
├── policies/
│   ├── trust-codebuild.json                 NEW
│   ├── trust-codepipeline.json              NEW
│   ├── usms-codebuild-policy.json           NEW
│   └── usms-codepipeline-policy.json        NEW
├── templates/
│   ├── lab-11-codebuild-project.json       NEW
│   └── lab-11-pipeline.json                NEW
├── scripts/
│   ├── utilities/
│   │   ├── cicd-support-probe.sh            NEW
│   │   ├── usms-buildspec-run.sh            NEW  - runs a buildspec locally, phase by phase
│   │   └── verify-lab-11.sh                NEW
│   └── cleanup/
│       └── lab-11-cleanup.sh               NEW  - DO NOT RUN NOW
├── outputs/
│   ├── lab-11-support-probe.txt            NEW  - git-ignored
│   ├── lab-11-build-<id>.json              NEW  - git-ignored
│   └── lab-11-pipeline-state.json          NEW  - git-ignored
└── notes/
    └── lab-11-notes.md                     NEW  - your answers to Section 15
```

`app/` sits under `labs/lab-11-cicd/` rather than at the repository root on purpose. It is the
source of one service, owned by one lab. Lab 12 adds a `Dockerfile` to the same directory rather
than creating a second copy of the tree somewhere else.

---
## 8. Step-by-Step Implementation

### Step 1 - Start Floci and confirm where you are

**Purpose**

Everything this lab creates lives inside the emulator. If the emulator is not running in hybrid
storage mode, the pipeline you build tonight is gone tomorrow, and - this is the part that costs
people an afternoon - every command will still report success while it happens.

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
```

**What the command does**

`floci-up.sh` starts the Compose project or adopts the running container; it refuses to adopt a
container that Compose did not create, which is how it protects you from a stray `floci start`.
`floci-storage-check.sh` runs sixteen read-only checks in two blocks - shell and profile first,
storage second - and names the cause of any failure rather than just reporting one.
`whoami.sh` prints the identity and endpoint and exits 1 if the account is not `000000000000`.

**Expected result**

```text
PASS=16  FAIL=0

  Account : 000000000000
  Arn     : arn:aws:iam::000000000000:root
  Endpoint: http://localhost:4566
```

> Example output - the account is always `000000000000` in Floci.

**What to look for:** `PASS=16  FAIL=0`. If you see `PASS=6`, you are running the pre-Errata version
of the storage check; apply Errata 01 Patch 2 before continuing. If any check in the
`-- shell and profile --` block fails, fix that first - the storage checks below it will produce
confusing results when `COURSE_ROOT` is unset.

---

### Step 2 - Source every earlier lab's environment

**Purpose**

This lab reads names from Labs 01, 04, 05, 06 and 06, and optionally from Lab 09. Shell variables
die with the terminal, which is exactly why every lab ends by writing its IDs to `configs/lab-NN.env`
- and why every lab begins by reading them back.

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
         configs/lab-10.env; do
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
you did not intend - an editor backup, a half-written file from a failed lab - and would give you no
report of what it did. The explicit list, with a printed result per file, is the version you can
debug. Because of the Lab 09 fork, some of those files will legitimately be `absent`; that is
information, not an error.

**Expected result**

```text
  sourced  configs/lab-01.env
  sourced  configs/lab-02.env
  sourced  configs/lab-03.env
  sourced  configs/lab-04.env
  sourced  configs/lab-05.env
  sourced  configs/lab-06.env
  absent   configs/lab-09.env
  sourced  configs/lab-07.env
  sourced  configs/lab-08.env
  sourced  configs/lab-10.env
```

> Example output - whether `configs/lab-09.env` shows `sourced` or `absent` depends only on whether
> you have completed Lab 09; it is not required for this lab.

**Verify**

```bash
printf 'cluster   : %s\nservice   : %s\ncontainer : %s\ntarget grp: %s\nexec role : %s\n' \
  "${USMS_ECS_CLUSTER:-MISSING}" \
  "${USMS_ENROLMENT_SERVICE:-MISSING}" \
  "${USMS_ENROLMENT_CONTAINER:-MISSING}" \
  "${USMS_TG_ARN:-MISSING}" \
  "${USMS_ECS_EXEC_ROLE_ARN:-MISSING}"
```

**What to look for:** no line says `MISSING`. `USMS_ENROLMENT_CONTAINER` must read `enrolment-api`
- Lab 12's `imagedefinitions.json` has to name that container exactly, and a mismatch there produces
a deploy failure whose message does not mention the container name at all.

---

### Step 3 - Probe CI/CD support and choose your path

**Purpose**

CodeBuild and CodePipeline are large services, and emulator coverage of them varies more than it does
for, say, S3. Lab 04 and Lab 07 both opened with a support probe for the same reason. Find out now,
in ninety seconds, which of three paths you are on - rather than in Step 19, after you have built
everything.

**Concept first - what "supported" can mean**

An emulator can respond to an API in three usefully different ways:

- it implements the operation and does the work;
- it implements the operation, stores the object, and never does the work (the control plane exists,
  the data plane does not);
- it does not implement the operation at all, and returns an error naming it.

Only the third is obvious. The second is the one that teaches people wrong things, because every
command succeeds. So the probe below does not only ask "did the call return 0?" - it asks whether the
object it created can be read back, and it labels the three paths explicitly.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
mkdir -p scripts/utilities outputs

cat > scripts/utilities/cicd-support-probe.sh << 'EOF'
#!/usr/bin/env bash
# Determine which CI/CD path this Floci build supports.
# Read-only except for one throwaway CodeBuild project, which it deletes.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"

PROBE_PROJECT="usms-probe-delete-me"
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  --   %s\n' "$1"; }

CB_LIST=no ; CB_CREATE=no ; CP_LIST=no ; ECS_ACTION=unknown

echo "== CodeBuild =="
if aws codebuild list-projects >/dev/null 2>&1; then
  CB_LIST=yes; ok "codebuild list-projects answers"
else
  bad "codebuild list-projects does not answer"
fi

if [ "$CB_LIST" = yes ]; then
  if aws codebuild create-project \
        --name "$PROBE_PROJECT" \
        --source type=NO_SOURCE,buildspec='version: 0.2' \
        --artifacts type=NO_ARTIFACTS \
        --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_SMALL \
        --service-role "arn:aws:iam::000000000000:role/does-not-matter-for-a-probe" \
        >/dev/null 2>&1; then
    CB_CREATE=yes; ok "codebuild create-project accepted"
    aws codebuild delete-project --name "$PROBE_PROJECT" >/dev/null 2>&1 \
      && ok "probe project deleted" || bad "probe project NOT deleted - remove $PROBE_PROJECT by hand"
  else
    bad "codebuild create-project rejected"
  fi
fi

echo "== CodePipeline =="
if aws codepipeline list-pipelines >/dev/null 2>&1; then
  CP_LIST=yes; ok "codepipeline list-pipelines answers"
else
  bad "codepipeline list-pipelines does not answer"
fi

echo "== Deploy targets (informational, used by Lab 12) =="
aws ecr describe-repositories >/dev/null 2>&1 \
  && ok "ecr describe-repositories answers" || bad "ecr describe-repositories does not answer"
aws deploy list-applications >/dev/null 2>&1 \
  && ok "codedeploy list-applications answers" || bad "codedeploy list-applications does not answer"

echo
if [ "$CB_CREATE" = yes ] && [ "$CP_LIST" = yes ]; then
  PATHNAME="A"
  echo "PATH A - CodeBuild and CodePipeline both present."
  echo "         Follow every step as written."
elif [ "$CB_CREATE" = yes ] || [ "$CP_LIST" = yes ]; then
  PATHNAME="B"
  echo "PATH B - one of the two services is present, the other is not."
  echo "         Follow every step. Where the missing service is called, record the"
  echo "         document you wrote and run Step 14's local runner instead."
else
  PATHNAME="C"
  echo "PATH C - neither service is present on this build."
  echo "         Every document in this lab is still written and validated; the"
  echo "         execution happens in Step 14's local runner. Section 12 tells you"
  echo "         exactly what to claim and what not to claim."
fi
printf 'USMS_CICD_SUPPORT_PATH=%s\n' "$PATHNAME" > outputs/lab-11-support-probe.txt
echo "recorded in outputs/lab-11-support-probe.txt"
EOF

chmod +x scripts/utilities/cicd-support-probe.sh
bash -n scripts/utilities/cicd-support-probe.sh && echo "syntax OK"
./scripts/utilities/cicd-support-probe.sh
```

**What the command does**

The probe creates a project with `type=NO_SOURCE` and `type=NO_ARTIFACTS`, which is the smallest
legal CodeBuild project - it needs no bucket, no role that resolves, and no source. If the API
accepts that, it will accept the real one. Then it deletes it. The service role ARN is deliberately a
name that does not exist: on Floci the call is not authorised anyway, and on real AWS you would never
run a probe like this against an account that mattered.

`--source ... buildspec='version: 0.2'` supplies an inline buildspec so the project is valid without
a source tree. That is the only place in this lab where a buildspec is not a file.

**Expected result**

```text
== CodeBuild ==
  ok   codebuild list-projects answers
  ok   codebuild create-project accepted
  ok   probe project deleted
== CodePipeline ==
  ok   codepipeline list-pipelines answers
== Deploy targets (informational, used by Lab 12) ==
  ok   ecr describe-repositories answers
  --   codedeploy list-applications does not answer

PATH A - CodeBuild and CodePipeline both present.
         Follow every step as written.
recorded in outputs/lab-11-support-probe.txt
```

> Example output - your build may report Path B or Path C. All three finish this laboratory.

**What to look for:** the last block names your path. Write it on the first line of
`notes/lab-11-notes.md` now. Section 12 asks you to distinguish what you observed from what you
recorded, and you cannot do that honestly at the end if you have forgotten which path you were on.

!!! note "Floci Limitation - CodeDeploy is very likely absent"
    Floci commonly answers `codedeploy list-applications` with an error naming the operation.

    On real AWS, CodeDeploy is what makes blue/green ECS deployments possible: it stands up a second
    task set, shifts the load balancer's traffic to it, and can roll back within seconds because the
    old task set is still running.

    Lab 12 Step 17 writes the CodeDeploy application specification and the deployment-group
    configuration as documents you read and validate, and labels them Conceptual / Real AWS. That is
    the honest version. Do not claim in your report that you performed a blue/green deployment.

**Checkpoint 1**

```text
aws-floci-course/
 ├── scripts/utilities/cicd-support-probe.sh   (executable)
 └── outputs/lab-11-support-probe.txt         USMS_CICD_SUPPORT_PATH=<A|B|C>
```

---

### Step 4 - Create this lab's directories

**Purpose**

Create every directory this lab writes to, in one command, so that no later step fails on a missing
parent. A build that fails because `config/` did not exist is a waste of a build.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
mkdir -p labs/lab-11-cicd/app/src \
         labs/lab-11-cicd/app/config \
         labs/lab-11-cicd/app/tests \
         policies templates scripts/utilities scripts/cleanup outputs notes

ls -d labs/lab-11-cicd/app/*
```

**What the command does**

`mkdir -p` creates parents as needed and does not complain when a directory already exists, which
makes it safe to re-run. The `ls -d` afterwards is the verify: it lists the directories themselves
rather than their (currently empty) contents.

**Expected result**

```text
labs/lab-11-cicd/app/config
labs/lab-11-cicd/app/src
labs/lab-11-cicd/app/tests
```

> Example output.

---

### Step 5 - Create the pipeline artifact bucket

**Purpose**

Every stage in a pipeline hands the next one a zip file, and those zip files live in one S3 bucket
called the **artifact store**. This same bucket will also hold the source archive. One bucket, two
roles - and Step 6 proves the property the pipeline actually depends on.

**Concept first - why the artifact store is not an implementation detail**

CodePipeline is often described as "connecting" stages. It does not. Stage 1 finishes by writing a
zip to S3 and recording its key; stage 2 begins by downloading that key. Nothing streams. Nothing is
held in memory between stages. This has three consequences you will meet:

- The artifact bucket must be in the **same region** as the pipeline. Cross-region artifacts need an
  explicit per-region artifact store, which is a different, more complex pipeline document.
- Anything in that bucket is readable by anything with `s3:GetObject` on it. Build artifacts routinely
  contain compiled configuration. Scope the policy.
- If an execution fails with something that looks like a permissions error on an object key you have
  never heard of, it is an artifact key. CodePipeline names them
  `<pipeline-name>/<OutputArtifactName>/<random>.zip`.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
PIPELINE_BUCKET="usms-pipeline-artifacts"

aws s3api create-bucket --bucket "$PIPELINE_BUCKET"

aws s3api put-bucket-tagging \
  --bucket "$PIPELINE_BUCKET" \
  --tagging 'TagSet=[{Key=Project,Value=USMS},{Key=Tier,Value=pipeline},{Key=Lab,Value=11}]'

aws s3api put-bucket-versioning \
  --bucket "$PIPELINE_BUCKET" \
  --versioning-configuration Status=Enabled

aws s3api put-public-access-block \
  --bucket "$PIPELINE_BUCKET" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

**What the command does**

```text
aws
 └── s3api                      the SERVICE (the low-level S3 API, not the `aws s3` file-transfer wrapper)
      └── create-bucket         the OPERATION
           └── --bucket         the name, globally unique on real AWS
      └── put-bucket-versioning
           └── --versioning-configuration Status=Enabled
```

In `us-east-1` - the course region - `create-bucket` takes no `--create-bucket-configuration`. Every
other region requires `--create-bucket-configuration LocationConstraint=<region>`, and omitting it
there is one of the most common first errors on real AWS. `us-east-1` is the exception because it is
the original region and its API predates the constraint.

`put-public-access-block` is not required by CodePipeline. It is here because an artifact bucket is
the single worst bucket in an account to leave publicly readable, and because the habit is the part
that transfers.

**Expected result**

```text
{
    "Location": "/usms-pipeline-artifacts"
}
```

> Example output - later calls in this block print nothing on success, which is normal for `put-*`.

**Verify**

```bash
aws s3api get-bucket-versioning --bucket "$PIPELINE_BUCKET" --output table
aws s3api get-bucket-tagging    --bucket "$PIPELINE_BUCKET" \
  --query 'TagSet[].[Key,Value]' --output table
```

**What to look for:** `Status` must read `Enabled`, not `Suspended` and not empty. An empty response
from `get-bucket-versioning` means versioning was never enabled - the API returns nothing rather than
`Status: Disabled`, which is a small trap worth knowing.

---

### Step 6 - Prove versioning is on

**Purpose**

Step 5's `get-bucket-versioning` reports what the configuration *says*. This step proves what the
bucket actually *does*. CodePipeline refuses an unversioned S3 source, and a pipeline that fails at
creation with `InvalidStructureException` because a bucket reported `Enabled` and behaved otherwise
is a bad afternoon.

**Concept first - create, perturb, read back**

This course's standard proof shape. Create something, change the world, read it back, and check the
*earlier* state survived. Here: put an object, put a different object at the same key, then ask for
the list of **versions** at that key. If versioning is real, both are still there. If it is not, the
second overwrote the first and you get one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
printf 'first\n'  > /tmp/usms-version-probe.txt
aws s3api put-object --bucket "$PIPELINE_BUCKET" \
  --key probe/versioning.txt --body /tmp/usms-version-probe.txt >/dev/null

printf 'second\n' > /tmp/usms-version-probe.txt
aws s3api put-object --bucket "$PIPELINE_BUCKET" \
  --key probe/versioning.txt --body /tmp/usms-version-probe.txt >/dev/null

aws s3api list-object-versions \
  --bucket "$PIPELINE_BUCKET" \
  --prefix probe/versioning.txt \
  --query 'Versions[].{Version:VersionId,Latest:IsLatest,Size:Size}' \
  --output table
```

**What the command does**

Two `put-object` calls to the same key with different bodies, then `list-object-versions` - which is
a different operation from `list-objects-v2`, and is the only one that can see anything other than
the current version.

**Expected result**

```text
-------------------------------------------
|           ListObjectVersions            |
+---------+----------+--------------------+
| Latest  |  Size    |      Version       |
+---------+----------+--------------------+
|  True   |  7       |  3vHc...           |
|  False  |  6       |  9kQa...           |
+---------+----------+--------------------+
```

> Example output - your version IDs will differ, and some builds report `null` as a version ID for
> objects written before versioning was enabled.

**What to look for:** **two rows**, exactly one of which has `Latest` as `True`. One row means
versioning is not actually in effect; go back to Step 5 and re-run `put-bucket-versioning`, then
re-run this step. Do not continue with one row - Step 17 will fail and the error will not mention
versioning.

Clean up the probe object. This is the only thing in this lab that gets deleted, and it is deleted
because leaving debris in an artifact bucket is how artifact buckets become unreadable:

!!! danger "Read before running any delete command"
    **What will be deleted:** the two versions of `probe/versioning.txt` in `usms-pipeline-artifacts`,
    and nothing else.

    **What depends on it:** nothing. It was written sixty seconds ago by this step.

    **Reversible?** No. Deleting a specific `--version-id` is permanent; there is no recycle bin.

    **Effect on later labs:** none.

```bash
aws s3api list-object-versions --bucket "$PIPELINE_BUCKET" --prefix probe/ \
  --query 'Versions[].[Key,VersionId]' --output text |
while read -r key vid; do
  [ -n "$key" ] && aws s3api delete-object --bucket "$PIPELINE_BUCKET" \
    --key "$key" --version-id "$vid" >/dev/null
done

aws s3api list-object-versions --bucket "$PIPELINE_BUCKET" --prefix probe/ \
  --query 'length(Versions || `[]`)' --output text
```

**What to look for:** the final number is `0`. Note the JMESPath `Versions || ` with a backtick-quoted
empty list - when there are no versions the field is absent, and `length(null)` is an error, so the
`||` supplies a default. That idiom is new in this lab and Appendix B records it.

**Checkpoint 2**

```text
s3://usms-pipeline-artifacts
 ├── versioning: Enabled     (proved by two versions at one key, then cleaned up)
 ├── public access: blocked
 └── tags: Project=USMS, Tier=pipeline, Lab=11
```

---

### Step 7 - Write the enrolment service source tree

**Purpose**

Give the pipeline something to build. Until now the ECS task definition has pointed at a public nginx
image chosen as a placeholder. From here on, the enrolment service has source, and that source has a
version number that you can watch move through a pipeline.

**Run from**

```text
aws-floci-course/labs/lab-11-cicd/app/
```

**Command - part 1, the application itself**

```bash
cd ~/aws-floci-course/labs/lab-11-cicd/app

printf 'r3\n' > VERSION

cat > src/index.html << 'EOF'
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>USMS - Enrolment</title></head>
  <body>
    <h1>USMS Enrolment Service</h1>
    <p>University Student Management System</p>
    <p id="release">release: __RELEASE__</p>
    <p id="built">built: __BUILT_AT__</p>
  </body>
</html>
EOF

cat > src/healthz.html << 'EOF'
ok
EOF
```

**What the command does**

`__RELEASE__` and `__BUILT_AT__` are placeholders. The build replaces them. That is the whole reason
they exist: it gives you something in the deployed artifact that could only have got there by a build
running, which is how Step 19 proves the pipeline did the work rather than merely reporting that it
did.

Note the **quoted** heredoc, `<< 'EOF'`. Everything inside is written literally. If you used the
unquoted form here, your shell would try to expand nothing in particular in this file - but the habit
matters, because the very next file contains `$` characters that must survive, and `configs/lab-11.env`
at the end of the lab uses the *unquoted* form deliberately so that `$(...)` runs at write time. Two
forms, opposite purposes, one character of difference.

**Command - part 2, the configuration the build validates**

```bash
cat > config/service.json << 'EOF'
{
  "service": "enrolment",
  "project": "USMS",
  "container": "enrolment-api",
  "port": 80,
  "healthPath": "/healthz.html",
  "cluster": "usms-ecs-cluster",
  "ecsService": "usms-enrolment-svc"
}
EOF

python3 -m json.tool config/service.json > /dev/null && echo "service.json is valid JSON"
```

**What the command does**

This file is not read by the application. It is read by the *build*, in the `pre_build` phase, which
validates it and fails the build if it is malformed or if its `container` value does not match the
container name the ECS task definition uses. That is a real pattern: catch a configuration mistake in
the build, where it costs ninety seconds, rather than in a deployment, where it costs a rollback.

**Command - part 3, the test**

```bash
cat > tests/smoke.sh << 'EOF'
#!/usr/bin/env bash
# Smoke tests for the USMS enrolment service artifact.
# Runs inside the build container, against the built output in ./dist.
set -uo pipefail

FAIL=0
t() {
  if eval "$2" >/dev/null 2>&1; then printf '  ok   %s\n' "$1"
  else printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); fi
}

echo "== smoke tests =="
t "dist/index.html exists"              "test -f dist/index.html"
t "dist/healthz.html exists"            "test -f dist/healthz.html"
t "release placeholder was replaced"    "! grep -q '__RELEASE__' dist/index.html"
t "build-time placeholder was replaced" "! grep -q '__BUILT_AT__' dist/index.html"
t "health endpoint says ok"             "grep -q '^ok$' dist/healthz.html"
t "build metadata is valid JSON"        "python3 -m json.tool dist/build-metadata.json"
t "container name matches the task def" "grep -q '\"container\": \"enrolment-api\"' config/service.json"

echo "smoke tests failed: $FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x tests/smoke.sh
bash -n tests/smoke.sh && echo "syntax OK"
```

**What the command does**

Seven assertions, each of which can only pass if the build actually did its job. Four of them check
for the *absence* of a placeholder, which is the useful direction: a build that silently skipped its
substitution step produces a file that still contains `__RELEASE__`, and a test that only checked
"the file exists" would pass.

`set -uo pipefail` without `-e`, matching every other script in this course: `-e` would abort on the
first failing `t` and you would never see the other six results.

**Verify**

```bash
cd ~/aws-floci-course
find labs/lab-11-cicd/app -type f | sort
```

**Expected result**

```text
labs/lab-11-cicd/app/VERSION
labs/lab-11-cicd/app/config/service.json
labs/lab-11-cicd/app/src/healthz.html
labs/lab-11-cicd/app/src/index.html
labs/lab-11-cicd/app/tests/smoke.sh
```

> Example output.

**What to look for:** five files. `buildspec.yml` is not there yet - it is Step 8, and it gets a step
of its own because it deserves one.

---
### Step 8 - Write `buildspec.yml`

**Purpose**

This is the centre of the laboratory. `buildspec.yml` is the file that says what a build *is*. It
lives in the source tree, so changing what a build does is a source change - reviewable, versioned,
attributable - rather than a click in a console.

**Concept first - the five top-level keys**

A buildspec is YAML with a fixed vocabulary. You will use five keys today:

| Key | What it is for |
| --- | --- |
| `version` | The buildspec format version. Use `0.2`. Version `0.1` ran every command in its own shell and is deprecated |
| `env` | Variables available to every phase, and which of them to export back to the pipeline |
| `phases` | The four named phases, in fixed order: `install`, `pre_build`, `build`, `post_build` |
| `artifacts` | Which files, of everything the build produced, are kept and handed to the next stage |
| `cache` | Directories preserved between builds. Empty here, and Section 12 says why |

The four phases are not arbitrary. CodeBuild runs them in order and reports each one separately, so
when a build fails you are told *which phase*, and that is most of the diagnosis. The convention -
and it is only a convention, nothing enforces it - is:

- `install` - install tools and runtimes. Nothing project-specific.
- `pre_build` - checks and preparation that must succeed before building is worth attempting.
  Validate configuration, log in to a registry, resolve a version number.
- `build` - produce the thing.
- `post_build` - test the thing, and write whatever the next stage needs.

There is a fifth phase name, `finally`, which can be attached to any phase and runs whether that
phase succeeded or failed. It is useful for uploading test reports. This lab does not use it;
Exercise 2 asks you to.

**Run from**

```text
aws-floci-course/labs/lab-11-cicd/app/
```

**Command**

```bash
cd ~/aws-floci-course/labs/lab-11-cicd/app

cat > buildspec.yml << 'BUILDSPEC'
version: 0.2

env:
  variables:
    SERVICE_NAME: "enrolment"
    ARTIFACT_DIR: "dist"

phases:

  install:
    commands:
      - echo "--- install ---"
      - python3 --version
      - sed --version 2>/dev/null | head -1 || echo "BSD sed"

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
      - echo "configuration validated"

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
          "sourceVersion": "${CODEBUILD_RESOLVED_SOURCE_VERSION:-local}"
        }
        META
      - cp config/service.json "$ARTIFACT_DIR/service.json"

  post_build:
    commands:
      - echo "--- post_build ---"
      - bash tests/smoke.sh
      - ls -l "$ARTIFACT_DIR"
      - cat "$ARTIFACT_DIR/build-metadata.json"

artifacts:
  base-directory: dist
  files:
    - '**/*'

cache:
  paths: []
BUILDSPEC

python3 - << 'PY'
import sys
try:
    import yaml
except ImportError:
    print("PyYAML not installed - skipping the YAML parse check.")
    print("Indentation errors will surface as a FAILED install phase instead.")
    sys.exit(0)
with open("buildspec.yml") as fh:
    doc = yaml.safe_load(fh)
assert doc["version"] == 0.2, "version must be 0.2"
for phase in ("install", "pre_build", "build", "post_build"):
    assert phase in doc["phases"], f"missing phase: {phase}"
print("buildspec.yml parses, and all four phases are present.")
PY
```

**What the command does**

Line by line, the parts that are not obvious:

- **`USMS_RELEASE` is recomputed inside the `build` phase** rather than being set in `pre_build` and
  reused. CodeBuild does run a build's commands in one shell, so the variable *would* survive - but
  relying on that makes the buildspec untestable anywhere else, including in the local runner you
  build in Step 14. Recomputing costs nothing and removes an assumption.
- **`sed -i.bak`, not `sed -i`.** GNU `sed` accepts `-i` with no argument; BSD `sed`, which is what
  macOS ships, requires a suffix and will silently eat your next argument if you do not give one.
  `-i.bak` works on both, and the following `rm -f` removes the backup. This lab's build runs on
  Linux inside CodeBuild, but Step 14's local runner runs on your laptop, and half the room's laptops
  are BSD.
- **`${CODEBUILD_BUILD_ID:-local}`** - CodeBuild sets a documented set of environment variables in
  every build. `CODEBUILD_BUILD_ID` identifies the build; `CODEBUILD_RESOLVED_SOURCE_VERSION` is the
  version of the source that was actually fetched, which for an S3 source is the object's version ID.
  The `:-local` default means the same buildspec produces sensible metadata when the local runner
  executes it, where neither variable exists.
- **The `- |` block** is YAML's literal block scalar: everything indented beneath it is one command,
  newlines included. Without it you cannot write a heredoc in a buildspec, because each list item is
  otherwise a single line.
- **The `grep` in `pre_build` is a `- |` block, and it has to be.** A plain YAML scalar that contains a
  colon followed by a space is parsed as a mapping key. The command
  `grep -q '"container": "enrolment-api"' ...` contains exactly that sequence inside its quotes - and
  YAML does not care that the quotes are the shell's, because YAML is parsed first. Written as a plain
  list item it produces `expected <block end>, but found '<scalar>'`, which is a message about YAML
  that gives no hint that your shell quoting is innocent. Any build command containing `": "` needs a
  block scalar or a fully YAML-quoted string. This is the single most common way a buildspec that
  looks correct fails to load.
- **`artifacts.base-directory: dist` with `files: ['**/*']`** means "take everything under `dist`, and
  make `dist` the root of the artifact". Get this wrong and your artifact contains a top-level `dist/`
  directory, which Lab 12's deploy stage will not find `imagedefinitions.json` inside. Path-relative
  bugs in this section are the single most common CodeBuild mistake.

!!! warning "The heredoc inside the heredoc"
    The outer shell heredoc is `<< 'BUILDSPEC'` - **quoted**, so nothing inside is expanded by your
    shell. That is essential: the file is full of `$USMS_RELEASE`, `$ARTIFACT_DIR` and
    `${CODEBUILD_BUILD_ID:-local}`, all of which must reach the file as literal text for CodeBuild to
    expand later. The inner `<< META` is **unquoted**, because there the expansion is wanted - at
    build time, inside the build container.

    Two heredocs, nested, with opposite quoting, for opposite reasons. If you only remember one rule
    from this course's shell material, make it this one: quoted heredoc writes the text, unquoted
    heredoc writes the result.

**Expected result**

```text
buildspec.yml parses, and all four phases are present.
```

> Example output - if PyYAML is not installed you will see the skip message instead, which is fine.

**Verify**

```bash
cd ~/aws-floci-course
grep -c '' labs/lab-11-cicd/app/buildspec.yml
grep -n 'base-directory\|^version\|^phases\|^artifacts' labs/lab-11-cicd/app/buildspec.yml
```

**What to look for:** `version`, `phases`, `artifacts` and `base-directory` each appear exactly once,
at the line numbers you expect. If `version` appears twice you have pasted the file twice, which
produces a YAML error that CodeBuild reports as `YAML_FILE_ERROR` and which reads, unhelpfully, like
a syntax problem in your commands.

✏️ **Your turn**

The `pre_build` phase validates that `config/service.json` names the container `enrolment-api`. Add a
second check to the same phase that fails the build if `config/service.json` does not name the port
`80`. Use the same shape as the container check - and note that your grep pattern will contain a colon
followed by a space, so it needs a `- |` block for the reason explained above. Give it an error
message that a tired person at 4pm could act on.

```text
Expected result:
buildspec.yml still parses; the pre_build phase has one more command; and if you
temporarily change the port in config/service.json to 8080 and re-run Step 14's
local runner, the build stops in pre_build with your message.
```

**Checkpoint 3**

```text
labs/lab-11-cicd/app/
 ├── VERSION            r3
 ├── buildspec.yml      version 0.2, four phases, artifacts from dist/
 ├── config/service.json
 ├── src/index.html     contains __RELEASE__ and __BUILT_AT__ placeholders
 ├── src/healthz.html
 └── tests/smoke.sh     7 assertions
```

---

### Step 9 - Create the CodeBuild service role and its policy

**Purpose**

A build container is a principal. It runs as a role, and what that role can reach is the answer to
"what could a compromised build do to us?" - which, for any organisation that runs one, is a real
question with a real answer.

**Concept first - what this role must be able to do, and nothing more**

Work it out from the buildspec rather than from a template on the internet. The build:

- writes logs - so it needs `logs:CreateLogStream` and `logs:PutLogEvents` on its own log group, and
  `logs:CreateLogGroup` because nothing has created that group yet;
- reads the source zip and writes the artifact zip - so it needs `s3:GetObject`, `s3:GetObjectVersion`
  and `s3:PutObject` on the artifact bucket, plus `s3:GetBucketAcl` and `s3:GetBucketLocation`, which
  CodeBuild calls before it uploads.

That is all. It does not need to read `usms-student-data`, so we add an explicit `Deny` saying so.
Section 12.2 of Lab 09 made the point that Floci does not enforce IAM; the `Deny` is here because the
policy is a document that people read, and a document that says "builds do not touch student records"
is worth having even on a day when nothing enforces it.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the trust policy**

```bash
cd ~/aws-floci-course

cat > policies/trust-codebuild.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CodeBuildAssumesThisRole",
      "Effect": "Allow",
      "Principal": { "Service": "codebuild.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "000000000000" }
      }
    }
  ]
}
EOF

python3 -m json.tool policies/trust-codebuild.json > /dev/null && echo "trust-codebuild.json is valid JSON"
```

**What the command does**

The `aws:SourceAccount` condition is the confused-deputy guard Lab 09 Step 6 introduced: without it,
any CodeBuild project in any account could, in principle, be configured to assume this role. On real
AWS you would tighten it further with `aws:SourceArn` naming the project ARN. That is Exercise 3.

**Command - part 2, the permissions policy**

```bash
cat > policies/usms-codebuild-policy.json << 'EOF'
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

python3 -m json.tool policies/usms-codebuild-policy.json > /dev/null && echo "usms-codebuild-policy.json is valid JSON"
```

**What the command does**

Note the **two** log-group ARNs in the first statement. The one without `:*` is the group itself, and
is what `CreateLogGroup` acts on; the one with `:*` covers the log *streams* inside it, which is what
`CreateLogStream` and `PutLogEvents` act on. Writing only one of the two is a classic half-working
policy: the group gets created and then nothing can write to it.

The bucket ARN and the object ARN are likewise separate - `arn:aws:s3:::bucket` for bucket-level
actions and `arn:aws:s3:::bucket/*` for object-level ones. Lab 01's `USMSStudentDataReadWrite` made
the same split for the same reason.

**Command - part 3, create the role and attach**

```bash
BUILD_ROLE="usms-codebuild-role"
BUILD_POLICY="USMSCodeBuildBase"

aws iam create-role \
  --role-name "$BUILD_ROLE" \
  --assume-role-policy-document file://policies/trust-codebuild.json \
  --description "Role assumed by CodeBuild when it builds the USMS enrolment service" \
  --tags Key=Project,Value=USMS Key=Tier,Value=pipeline Key=Lab,Value=11 \
  --query 'Role.Arn' --output text

BUILD_POLICY_ARN=$(aws iam create-policy \
  --policy-name "$BUILD_POLICY" \
  --policy-document file://policies/usms-codebuild-policy.json \
  --description "What a USMS build may do: its own logs, the artifact bucket, nothing else" \
  --query 'Policy.Arn' --output text)

aws iam attach-role-policy \
  --role-name "$BUILD_ROLE" \
  --policy-arn "$BUILD_POLICY_ARN"

BUILD_ROLE_ARN=$(aws iam get-role --role-name "$BUILD_ROLE" --query 'Role.Arn' --output text)
echo "$BUILD_ROLE_ARN"
```

**Expected result**

```text
arn:aws:iam::000000000000:role/usms-codebuild-role
```

> Example output - the account is always `000000000000` in Floci.

**Verify**

```bash
aws iam list-attached-role-policies --role-name "$BUILD_ROLE" --output table
aws iam get-role --role-name "$BUILD_ROLE" \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal' --output json
```

**What to look for:** exactly one attached policy, named `USMSCodeBuildBase`, and a principal of
`{"Service": "codebuild.amazonaws.com"}`. If the principal reads `codebuild.us-east-1.amazonaws.com`
you have copied a regional service principal from somewhere; CodeBuild's is global.

---

### Step 10 - Create the CodeBuild project

**Purpose**

The project is the durable configuration of *how* to build: which container image, how much compute,
which role, where the source is, where the artifact goes, and how long to wait before giving up. The
one thing it does not contain is the build commands - those are in the source.

**Concept first - source type, and the trap in it**

A CodeBuild project's `source.type` can be `S3`, `GITHUB`, `BITBUCKET`, `CODECOMMIT`, `NO_SOURCE`, or
`CODEPIPELINE`. The last one means "I have no source of my own; the pipeline will hand me one".

Here is the trap, and it catches nearly everybody once: **a project whose source type is
`CODEPIPELINE` cannot be started on its own.** `aws codebuild start-build --project-name ...` on such
a project is rejected, because there is no source to build.

So this lab creates the project with an `S3` source first, runs it standalone in Step 12 to prove the
buildspec works in isolation, and only in Step 18 - after the pipeline exists - converts it to
`CODEPIPELINE`. That ordering is deliberate, and Step 18 shows you the one-off escape hatch for
running a `CODEPIPELINE` project by hand when you need to.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > templates/lab-11-codebuild-project.json << EOF
{
  "name": "usms-enrolment-build",
  "description": "Builds the USMS enrolment service artifact from labs/lab-11-cicd/app",
  "source": {
    "type": "S3",
    "location": "usms-pipeline-artifacts/source/usms-enrolment-src.zip",
    "buildspec": "buildspec.yml"
  },
  "artifacts": {
    "type": "S3",
    "location": "usms-pipeline-artifacts",
    "path": "build",
    "name": "usms-enrolment-build.zip",
    "packaging": "ZIP",
    "namespaceType": "NONE"
  },
  "environment": {
    "type": "LINUX_CONTAINER",
    "image": "aws/codebuild/standard:7.0",
    "computeType": "BUILD_GENERAL1_SMALL",
    "privilegedMode": false,
    "environmentVariables": [
      { "name": "USMS_PROJECT", "value": "USMS", "type": "PLAINTEXT" },
      { "name": "USMS_SERVICE", "value": "enrolment", "type": "PLAINTEXT" }
    ]
  },
  "serviceRole": "${BUILD_ROLE_ARN}",
  "timeoutInMinutes": 15,
  "queuedTimeoutInMinutes": 30,
  "logsConfig": {
    "cloudWatchLogs": {
      "status": "ENABLED",
      "groupName": "/aws/codebuild/usms-enrolment-build"
    }
  },
  "tags": [
    { "key": "Project", "value": "USMS" },
    { "key": "Tier", "value": "pipeline" },
    { "key": "Lab", "value": "11" }
  ]
}
EOF

python3 -m json.tool templates/lab-11-codebuild-project.json > /dev/null \
  && echo "project template is valid JSON"
grep -c '\$' templates/lab-11-codebuild-project.json
```

**What the command does**

This heredoc is **unquoted** - `<< EOF`, not `<< 'EOF'` - because `${BUILD_ROLE_ARN}` must be
substituted at write time. The `grep -c '\$'` afterwards is the check that it was: the answer must be
`0`. A template with a surviving `$` in it is a template whose variable was empty, and
`create-project` will reject it with a message about an invalid ARN that does not mention your shell
at all.

Note that CodeBuild tags use lowercase `key`/`value`, while IAM and ELBv2 use `Key`/`Value`. This
inconsistency is real, is not going away, and costs everybody twenty minutes exactly once.

**Expected result**

```text
project template is valid JSON
0
```

> Example output - the `0` is the count of unexpanded `$` characters and is the part that matters.

**Command - create it**

```bash
aws codebuild create-project \
  --cli-input-json file://templates/lab-11-codebuild-project.json \
  --query 'project.{Name:name,Role:serviceRole,Image:environment.image,Source:source.type}' \
  --output table
```

**Verify**

```bash
aws codebuild batch-get-projects --names usms-enrolment-build \
  --query 'projects[0].{Name:name,Source:source.type,Location:source.location,Artifacts:artifacts.type,Timeout:timeoutInMinutes}' \
  --output table
```

**What to look for:** `Source` is `S3` and `Location` is
`usms-pipeline-artifacts/source/usms-enrolment-src.zip`. If `batch-get-projects` returns an empty
`projects` list and a populated `projectsNotFound` list, the project was not created - re-read the
`create-project` output rather than re-running it.

**Checkpoint 4**

```text
IAM
 ├── usms-codebuild-role      trusts codebuild.amazonaws.com
 └── USMSCodeBuildBase        logs + artifact bucket + explicit deny on usms-student-data

CodeBuild
 └── usms-enrolment-build     source S3, image standard:7.0, small, 15-minute timeout
```

---

### Step 11 - Package and upload the source

**Purpose**

CodeBuild's S3 source is a zip file. Getting its internal layout right matters: the buildspec must be
at the **root** of the archive, not inside a directory. This step builds a small packer script,
because you will repackage the source four more times before the lab ends.

**Concept first - the layout that works**

```text
usms-enrolment-src.zip
 ├── buildspec.yml          <- must be here, at the root
 ├── VERSION
 ├── config/service.json
 ├── src/index.html
 ├── src/healthz.html
 └── tests/smoke.sh
```

```text
usms-enrolment-src.zip
 └── app/                   <- WRONG. CodeBuild looks for buildspec.yml at the root and
      ├── buildspec.yml        reports YAML_FILE_ERROR / "buildspec not found"
      └── ...
```

`zip -r ../x.zip .` from inside the directory produces the first. `zip -r x.zip app/` from its parent
produces the second. One character of difference in where you stand.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the packer**

```bash
cd ~/aws-floci-course

cat > scripts/utilities/usms-pack-source.sh << 'EOF'
#!/usr/bin/env bash
# Package a source directory into a zip whose ROOT is that directory's contents.
# Usage: usms-pack-source.sh <source-dir> <output-zip>
set -uo pipefail

SRC="${1:-}"
OUT="${2:-}"
if [ -z "$SRC" ] || [ -z "$OUT" ]; then
  echo "usage: $0 <source-dir> <output-zip>" >&2
  exit 2
fi
if [ ! -d "$SRC" ]; then
  echo "not a directory: $SRC" >&2
  exit 2
fi

OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
rm -f "$OUT_ABS"

if command -v zip >/dev/null 2>&1; then
  ( cd "$SRC" && zip -r -q "$OUT_ABS" . -x '*.bak' -x 'dist/*' )
  echo "packed with zip"
else
  python3 - "$SRC" "$OUT_ABS" << 'PY'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in sorted(dirs) if d != "dist"]
        for f in sorted(files):
            if f.endswith(".bak"):
                continue
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, src))
PY
  echo "packed with python3 zipfile"
fi

echo "--- archive contents ---"
if command -v unzip >/dev/null 2>&1; then
  unzip -l "$OUT_ABS"
else
  python3 -c 'import sys,zipfile;[print(n) for n in zipfile.ZipFile(sys.argv[1]).namelist()]' "$OUT_ABS"
fi
EOF

chmod +x scripts/utilities/usms-pack-source.sh
bash -n scripts/utilities/usms-pack-source.sh && echo "syntax OK"
```

**What the command does**

The script prefers `zip` and falls back to Python's `zipfile` module, which is in the standard library
and therefore always present. Both exclude `dist/` - the build output directory - because shipping
the previous build's output into the next build's source is how you get a build that passes its own
tests without having built anything.

The Python fallback does not preserve the executable bit. That is deliberate and harmless: the
buildspec runs the test with `bash tests/smoke.sh`, not `./tests/smoke.sh`. If you change that line,
you will discover this the hard way, which is a reasonable thing to have discovered once.

`OUT_ABS` is computed before the subshell `cd`, because `zip` is run from inside `$SRC` and a relative
output path would land in the wrong place. This is the `cd` that never comes back, caught early.

**Command - part 2, pack and upload**

```bash
./scripts/utilities/usms-pack-source.sh \
  labs/lab-11-cicd/app \
  outputs/usms-enrolment-src.zip

aws s3api put-object \
  --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip \
  --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text
```

**Expected result**

```text
packed with zip
--- archive contents ---
Archive:  /home/you/aws-floci-course/outputs/usms-enrolment-src.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
        0  2026-09-17 09:14   src/
        3  2026-09-17 09:14   src/healthz.html
      254  2026-09-17 09:14   src/index.html
        0  2026-09-17 09:14   config/
      200  2026-09-17 09:14   config/service.json
     1759  2026-09-17 09:14   buildspec.yml
        0  2026-09-17 09:14   tests/
      813  2026-09-17 09:14   tests/smoke.sh
        3  2026-09-17 09:14   VERSION
---------                     -------
     3032                     9 files

3HL9pQ...
```

> Example output - your sizes, dates and version ID will differ. `zip` records the three directories
> as zero-length entries and counts them, so it reports nine; the Python fallback records only the six
> real files and reports six. Both archives behave identically in a build.

**What to look for:** `buildspec.yml` and `VERSION` sitting at the top level, and **no path in the
listing beginning with `app/`**. The last line is the S3 version ID of the object you just uploaded -
the pipeline's Source stage will fetch exactly that version, and Step 19 uses this to prove the
pipeline consumed the source you think it did.

`outputs/` is git-ignored, so the zip you just built is not a commit candidate. Confirm the rule that
protected you:

```bash
git check-ignore -v outputs/usms-enrolment-src.zip
```

**What to look for:** the output names `.gitignore`, the line number, and the pattern `outputs/*`.
If it prints nothing, the file is *not* ignored and your `.gitignore` has the `outputs/` form that
Section 15 of the project instructions warns about.

---

### Step 12 - Run the build on its own

**Purpose**

Before putting a build inside a pipeline, prove the build works. If the build is broken and you find
out through a pipeline, you have two systems to debug instead of one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
BUILD_ID=$(aws codebuild start-build \
  --project-name usms-enrolment-build \
  --query 'build.id' --output text)

echo "$BUILD_ID"
```

**What the command does**

```text
aws
 └── codebuild            the SERVICE
      └── start-build     the OPERATION - queues one build of one project
           └── --project-name   which project's configuration to use
```

`start-build` returns immediately. The build is asynchronous; the returned `id` has the form
`usms-enrolment-build:<uuid>` and is how you ask about it afterwards.

**Expected result**

```text
usms-enrolment-build:9f0c1a3e-7d21-4a4e-9c2e-2b8f0a1d5c77
```

> Example output - your build ID will differ.

**Verify - poll until it finishes**

```bash
for i in $(seq 1 40); do
  STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
             --query 'builds[0].buildStatus' --output text 2>/dev/null)
  PHASE=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
            --query 'builds[0].currentPhase' --output text 2>/dev/null)
  printf '  %2d  status=%-12s phase=%s\n' "$i" "${STATUS:-unknown}" "${PHASE:-unknown}"
  case "$STATUS" in
    SUCCEEDED|FAILED|FAULT|STOPPED|TIMED_OUT) break ;;
  esac
  sleep 10
done
```

**What to look for:** `status=IN_PROGRESS` with the phase advancing through `QUEUED`, `PROVISIONING`,
`INSTALL`, `PRE_BUILD`, `BUILD`, `POST_BUILD`, `UPLOAD_ARTIFACTS`, `COMPLETED`, ending at
`status=SUCCEEDED`.

A hand-written polling loop rather than a waiter, for the reason Lab 04 gave about
`aws ecs wait services-stable`: waiters on this emulator can run until they exhaust their attempts
without ever telling you what they are seeing. A loop that prints each observation tells you whether
nothing is happening or something is happening slowly, and those need different responses.

!!! note "Floci Limitation - a build that never leaves PROVISIONING"
    On some builds, CodeBuild accepts `start-build`, records the build, and never runs it, because
    running it means pulling a multi-gigabyte `aws/codebuild/standard:7.0` image through the Docker
    socket and starting a container. You will see `status=IN_PROGRESS`, `phase=PROVISIONING`, forever.

    On real AWS, provisioning takes a few seconds because the image is cached in the service.

    Give it four minutes. If the phase has not moved, stop the build with
    `aws codebuild stop-build --id "$BUILD_ID"`, record what you saw in
    `notes/lab-11-notes.md`, and go to Step 14 - the local runner executes exactly the same
    buildspec, and everything after Step 14 still works. This is Path B or Path C from Step 3.

---

### Step 13 - Read the build output and the logs

**Purpose**

`SUCCEEDED` is not the interesting part. The interesting part is per-phase timing and the log, because
that is the pair you will use for every failed build for the rest of your career.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws codebuild batch-get-builds --ids "$BUILD_ID" \
  --query 'builds[0].phases[].{Phase:phaseType,Status:phaseStatus,Seconds:durationInSeconds}' \
  --output table

aws codebuild batch-get-builds --ids "$BUILD_ID" > "outputs/lab-11-build-$(date +%s).json"
```

**Expected result**

```text
-------------------------------------------------
|                BatchGetBuilds                 |
+-------------------+------------+--------------+
|      Phase        |  Seconds   |   Status     |
+-------------------+------------+--------------+
|  SUBMITTED        |  0         |  SUCCEEDED   |
|  QUEUED           |  1         |  SUCCEEDED   |
|  PROVISIONING     |  22        |  SUCCEEDED   |
|  DOWNLOAD_SOURCE  |  2         |  SUCCEEDED   |
|  INSTALL          |  1         |  SUCCEEDED   |
|  PRE_BUILD        |  1         |  SUCCEEDED   |
|  BUILD            |  1         |  SUCCEEDED   |
|  POST_BUILD       |  1         |  SUCCEEDED   |
|  UPLOAD_ARTIFACTS |  2         |  SUCCEEDED   |
|  FINALIZING       |  1         |  SUCCEEDED   |
|  COMPLETED        |            |              |
+-------------------+------------+--------------+
```

> Example output - your durations will differ, and a failed build shows the failing phase with
> `FAILED` and every phase after it absent.

**What to look for:** the phase names are not the four you wrote. CodeBuild adds `SUBMITTED`,
`QUEUED`, `PROVISIONING`, `DOWNLOAD_SOURCE`, `UPLOAD_ARTIFACTS`, `FINALIZING` and `COMPLETED` around
them. Learning which of those are yours and which are the service's is most of learning to read a
build failure: a failure in `DOWNLOAD_SOURCE` is a source or permissions problem, a failure in
`PRE_BUILD` is your code, and a failure in `PROVISIONING` is capacity or image.

**Command - the log**

```bash
LOG_GROUP=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
  --query 'builds[0].logs.groupName' --output text)
LOG_STREAM=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
  --query 'builds[0].logs.streamName' --output text)

echo "group=$LOG_GROUP stream=$LOG_STREAM"

aws logs get-log-events \
  --log-group-name "$LOG_GROUP" \
  --log-stream-name "$LOG_STREAM" \
  --limit 60 \
  --query 'events[].message' --output text
```

**What to look for:** the `--- install ---`, `--- pre_build ---`, `--- build ---` and
`--- post_build ---` markers you put in the buildspec, and between the last two, the seven `ok` lines
from `tests/smoke.sh`. Those markers exist precisely so that a log you are skimming at speed tells you
where you are.

!!! note "Floci Limitation - empty build logs"
    Log streams for CodeBuild builds are frequently empty on this emulator even when the build ran,
    because the log-shipping side of the build agent is not wired up.

    On real AWS the stream contains every line the build printed, and is the primary debugging tool.

    If `get-log-events` returns no events, do not conclude the build did nothing. Check
    `batch-get-builds` phases instead, and check the artifact in the next command - the artifact is
    the evidence that survives.

**Command - read the artifact back**

```bash
aws s3api list-objects-v2 --bucket usms-pipeline-artifacts --prefix build/ \
  --query 'Contents[].{Key:Key,Size:Size}' --output table
```

**What to look for:** one object under `build/`. This is the `create → perturb → read back` shape
again: the build ran (perturbation), and the artifact it left behind is the read-back. A `SUCCEEDED`
status with no artifact means `artifacts.base-directory` in your buildspec does not match where the
build actually wrote files.

**Checkpoint 5**

```text
s3://usms-pipeline-artifacts
 ├── source/usms-enrolment-src.zip     (versioned; one version so far)
 └── build/usms-enrolment-build.zip    written by build usms-enrolment-build:<uuid>

CodeBuild
 └── usms-enrolment-build              one build, SUCCEEDED, ten phases recorded
```

---
### Step 14 - The local buildspec runner

**Purpose**

Two reasons, and the second is the important one.

First, if Step 12 never left `PROVISIONING`, this is how you still run your build. Second - and this
applies even if CodeBuild worked perfectly - a buildspec you can only run by pushing to a bucket and
waiting ninety seconds is a buildspec you will debug badly. Being able to run the same phases in two
seconds on your laptop changes how you write them.

**Concept first - what "the same build" does and does not mean**

The local runner reads *your* `buildspec.yml` and executes the same commands in the same order. It is
not a CodeBuild emulator:

| Same | Different |
| --- | --- |
| The commands, from the same file | Runs on your machine, not `aws/codebuild/standard:7.0` |
| The phase order | `set -e` semantics: the runner stops at the first failure; CodeBuild still runs `post_build` after a failed `build` |
| `env.variables`, and the rule that an environment value overrides them | No `CODEBUILD_*` variables - the buildspec's `:-local` defaults fire |
| The artifacts directory it produces | Does not zip or upload anything |

Say which one you used when you report a result. "The build passed" and "the build passed locally"
are different claims.

**Run from**

```text
aws-floci-course/
```

**Command**

{% raw %}```bash
cd ~/aws-floci-course

cat > scripts/utilities/usms-buildspec-run.sh << 'EOF'
#!/usr/bin/env bash
# Run a buildspec's phases locally, in order, in one shell.
# Usage: usms-buildspec-run.sh <app-dir> [buildspec-file]
set -uo pipefail

APP_DIR="${1:-}"
SPEC="${2:-buildspec.yml}"
if [ -z "$APP_DIR" ] || [ ! -d "$APP_DIR" ]; then
  echo "usage: $0 <app-dir> [buildspec-file]" >&2
  exit 2
fi
APP_ABS="$(cd "$APP_DIR" && pwd)"
if [ ! -f "$APP_ABS/$SPEC" ]; then
  echo "no $SPEC in $APP_ABS" >&2
  exit 2
fi

GEN="${TMPDIR:-/tmp}/usms-buildspec-$$.sh"

python3 - "$APP_ABS/$SPEC" "$GEN" << 'PY'
import sys

spec_path, out_path = sys.argv[1], sys.argv[2]
ORDER = ("install", "pre_build", "build", "post_build")


def with_pyyaml(path):
    import yaml
    doc = yaml.safe_load(open(path))
    env = ((doc.get("env") or {}).get("variables") or {})
    phases = {}
    for name, body in (doc.get("phases") or {}).items():
        phases[name] = list((body or {}).get("commands") or [])
    return env, phases


def minimal(path):
    """Handles exactly the buildspec subset this course writes:
    env: -> variables: -> KEY: value ; phases: -> <phase>: -> commands: -> '- cmd'
    or '- |' followed by a more-indented literal block."""
    env, phases = {}, {}
    in_env = in_env_vars = in_phases = in_commands = False
    phase = None
    cmds = None
    block = None
    block_indent = 0

    def close_block():
        nonlocal block
        if block is not None:
            cmds.append("\n".join(block).rstrip())
            block = None

    for raw in open(path).read().splitlines():
        if block is not None:
            if raw.strip() == "":
                block.append("")
                continue
            if (len(raw) - len(raw.lstrip())) >= block_indent:
                block.append(raw[block_indent:])
                continue
            close_block()
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            in_env = stripped.startswith("env:")
            in_phases = stripped.startswith("phases:")
            in_env_vars = in_commands = False
            phase = None
            continue
        if in_env and indent == 2:
            in_env_vars = (stripped == "variables:")
            continue
        if in_env_vars and indent == 4 and ":" in stripped:
            k, v = stripped.split(":", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
            continue
        if in_phases and indent == 2 and stripped.endswith(":"):
            phase = stripped[:-1]
            phases[phase] = []
            cmds = phases[phase]
            in_commands = False
            continue
        if in_phases and phase and indent == 4 and stripped == "commands:":
            in_commands = True
            continue
        if in_commands and stripped.startswith("- "):
            body = stripped[2:]
            if body.strip() == "|":
                block = []
                block_indent = indent + 2
            else:
                cmds.append(body)
            continue
    close_block()
    return env, phases


try:
    env, phases = with_pyyaml(spec_path)
    parser = "PyYAML"
except ImportError:
    env, phases = minimal(spec_path)
    parser = "built-in minimal parser"

lines = ["#!/usr/bin/env bash", "set -Eeuo pipefail", ""]
for k, v in env.items():
    # A value already in the environment wins, the way a CodeBuild project-level
    # environment variable overrides a buildspec env.variables default.
    lines.append('export %s="${%s:-%s}"' % (k, k, v))
lines.append("")
for name in ORDER:
    if name not in phases:
        continue
    lines.append('echo "=== phase: %s ==="' % name)
    lines.extend(phases[name])
    lines.append("")
lines.append('echo "=== all phases completed ==="')

open(out_path, "w").write("\n".join(lines) + "\n")
print("buildspec parsed with %s; %d phases" % (parser, len([p for p in ORDER if p in phases])))
PY

RC=$?
[ "$RC" -ne 0 ] && { echo "could not parse the buildspec" >&2; exit "$RC"; }

echo "--- generated script: $GEN ---"
bash -n "$GEN" && echo "generated script is valid bash"
echo "--- running in $APP_ABS ---"
( cd "$APP_ABS" && bash "$GEN" )
STATUS=$?
echo "--- local build exit status: $STATUS ---"
rm -f "$GEN"
exit "$STATUS"
EOF

chmod +x scripts/utilities/usms-buildspec-run.sh
bash -n scripts/utilities/usms-buildspec-run.sh && echo "syntax OK"

./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app
```{% endraw %}

**What the command does**

The script asks Python to turn the buildspec into a plain shell script, checks that script with
`bash -n`, then runs it in a subshell that `cd`s into the application directory - so the parent shell
never changes directory, which is the `cd` that never comes back, avoided by construction.

Each `env.variables` entry becomes `export NAME="${NAME:-value}"` rather than a plain assignment, so a
value you set in your own environment before invoking the runner wins over the buildspec's default.
That matches CodeBuild, where a project-level environment variable overrides an `env.variables` default
in the buildspec, and Lab 12 relies on it. The generated form assumes the default contains no double
quote, which is true of every value this course writes.

The Python part prefers PyYAML and falls back to a hand-written parser that understands exactly the
YAML shape this course writes: `env.variables`, `phases.<name>.commands`, plain `- command` items and
`- |` literal blocks. It does not understand anchors, flow sequences, or multi-document files, and it
says which parser it used so you can tell. That honesty is the point: a fallback that quietly
mis-parses is worse than no fallback.

**Expected result**

```text
buildspec parsed with PyYAML; 4 phases
--- generated script: /tmp/usms-buildspec-4821.sh ---
generated script is valid bash
--- running in /home/you/aws-floci-course/labs/lab-11-cicd/app ---
=== phase: install ===
Python 3.12.3
sed (GNU sed) 4.9
=== phase: pre_build ===
configuration validated
=== phase: build ===
release=r3 builtAt=2026-09-17T09:31:04Z
=== phase: post_build ===
== smoke tests ==
  ok   dist/index.html exists
  ok   dist/healthz.html exists
  ok   release placeholder was replaced
  ok   build-time placeholder was replaced
  ok   health endpoint says ok
  ok   build metadata is valid JSON
  ok   container name matches the task def
smoke tests failed: 0
...
=== all phases completed ===
--- local build exit status: 0 ---
```

> Example output - your Python and sed versions, timestamps and temporary path will differ.

**Verify**

```bash
cat labs/lab-11-cicd/app/dist/build-metadata.json
grep -n 'release:' labs/lab-11-cicd/app/dist/index.html
```

**What to look for:** `build-metadata.json` shows `"release": "r3"` and `"buildId": "local"`. That
`local` is how you tell, later and at a glance, whether an artifact came from a real build or from
your laptop. `index.html` shows `release: r3` with no `__RELEASE__` anywhere.

The `dist/` directory is build output and must never be committed or packed into the source. The
packer from Step 11 already excludes it; add it to `.gitignore` as well:

```bash
grep -q '^labs/lab-11-cicd/app/dist/' .gitignore || \
  printf 'labs/lab-11-cicd/app/dist/\n' >> .gitignore

git check-ignore -v labs/lab-11-cicd/app/dist/build-metadata.json
```

**What to look for:** the output names `.gitignore`, a line number, and the pattern. Note the form -
`labs/lab-11-cicd/app/dist/` with a trailing slash excludes the directory and everything in it, and
nothing here needs re-including, so the `outputs/*` plus negation shape from Section 15 of the course
rules does not apply.

**Checkpoint 6**

```text
scripts/utilities/
 ├── cicd-support-probe.sh
 ├── usms-pack-source.sh
 └── usms-buildspec-run.sh      runs buildspec.yml locally; 4 phases, 7 smoke tests, exit 0
```

---

### Step 15 - Create the CodePipeline service role and its policy

**Purpose**

The pipeline is also a principal, and it is a different one from the build. Keeping them separate is
not bureaucracy: the pipeline can start builds and read every artifact, while the build can read one
bucket and write logs. If the build container is compromised, it cannot start other builds.

**Concept first - `iam:PassRole`, properly**

The pipeline does not build anything. It calls `codebuild:StartBuild`, and CodeBuild then runs the
build **as `usms-codebuild-role`**. That is a role handoff, and AWS treats handoffs as a permission in
their own right.

Think about why. Without `iam:PassRole`, anyone who could create a CodeBuild project could name
*any* role in the account as its service role - including an administrator role - and then run
arbitrary commands as it. `iam:PassRole` is the control that stops that: to hand role R to service S,
you need explicit permission to pass R, and the `iam:PassedToService` condition pins which service
may receive it.

In this pipeline the handoff is:

```text
usms-codepipeline-role  ──iam:PassRole──>  usms-codebuild-role  ──used by──>  codebuild.amazonaws.com
```

Lab 12 adds a second handoff, to the ECS task and execution roles, for exactly the same reason.

!!! info "Compare with `USMSDeployBase`, if you have it"
    If you completed Lab 09, open `policies/usms-deploy-policy.json` now and find its
    `iam:PassRole` statement. It scopes `PassRole` to three role ARNs with an `iam:PassedToService`
    condition naming `ec2.amazonaws.com` and `ecs-tasks.amazonaws.com`. The statement you are about
    to write is the same idea with a different receiving service.

    For a second data point, here is the equivalent pass-role statement from the EKS deployment work
    in Labs 07-08, so you can compare all three side by side:

    ```json
    {
      "Sid": "PassOnlyTheseRolesAndOnlyToTheseServices",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::000000000000:role/usms-ec2-app-role",
        "arn:aws:iam::000000000000:role/usms-ecs-exec-role",
        "arn:aws:iam::000000000000:role/usms-ecs-task-role"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": ["ec2.amazonaws.com", "ecs-tasks.amazonaws.com"]
        }
      }
    }
    ```

    The question to answer in `notes/lab-11-notes.md`: what would go wrong if the `Resource` were
    `"*"` but the condition were kept? Be specific about which role an attacker would name.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the documents**

```bash
cd ~/aws-floci-course

cat > policies/trust-codepipeline.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CodePipelineAssumesThisRole",
      "Effect": "Allow",
      "Principal": { "Service": "codepipeline.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "000000000000" }
      }
    }
  ]
}
EOF

cat > policies/usms-codepipeline-policy.json << 'EOF'
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
    }
  ]
}
EOF

for f in policies/trust-codepipeline.json policies/usms-codepipeline-policy.json; do
  python3 -m json.tool "$f" > /dev/null && echo "$f is valid JSON"
done
```

**What the command does**

The second statement names **one project ARN**, not `project/*`. That is the difference between "this
pipeline can run the enrolment build" and "this pipeline can run every build in the account", and it
is one line of typing.

`s3:GetBucketVersioning` is in the first statement because CodePipeline genuinely calls it - it checks
that an S3 source bucket is versioned before it will run, which is the machine-enforced half of what
Step 6 proved by hand.

**Command - part 2, create and attach**

```bash
PIPELINE_ROLE="usms-codepipeline-role"
PIPELINE_POLICY="USMSCodePipelineBase"

aws iam create-role \
  --role-name "$PIPELINE_ROLE" \
  --assume-role-policy-document file://policies/trust-codepipeline.json \
  --description "Role assumed by CodePipeline when it runs usms-enrolment-pipeline" \
  --tags Key=Project,Value=USMS Key=Tier,Value=pipeline Key=Lab,Value=11 \
  --query 'Role.Arn' --output text

PIPELINE_POLICY_ARN=$(aws iam create-policy \
  --policy-name "$PIPELINE_POLICY" \
  --policy-document file://policies/usms-codepipeline-policy.json \
  --description "What the USMS pipeline may do: its artifact store, one build project, one PassRole" \
  --query 'Policy.Arn' --output text)

aws iam attach-role-policy --role-name "$PIPELINE_ROLE" --policy-arn "$PIPELINE_POLICY_ARN"

PIPELINE_ROLE_ARN=$(aws iam get-role --role-name "$PIPELINE_ROLE" --query 'Role.Arn' --output text)
echo "$PIPELINE_ROLE_ARN"
```

**Verify**

```bash
aws iam get-policy --policy-arn "$PIPELINE_POLICY_ARN" \
  --query 'Policy.{Name:PolicyName,Default:DefaultVersionId,Attached:AttachmentCount}' --output table
```

**What to look for:** `Default` is `v1` and `Attached` is `1`. Remember `Default` - Lab 12 creates
`v2` of `USMSCodeBuildBase` and has to set it as the default explicitly, because creating a policy
version does not activate it.

---

### Step 16 - Write the pipeline definition

**Purpose**

A pipeline is a JSON document. Understanding its shape is the difference between operating
CodePipeline and clicking at it.

**Concept first - the four nested things**

```text
pipeline
 ├── name, roleArn, artifactStore
 └── stages[]                      ordered; execution moves through them one at a time
      └── actions[]                within a stage, actions with the same runOrder run in PARALLEL
           ├── actionTypeId        category + owner + provider + version  - the four-part identity
           ├── configuration       provider-specific settings; every value is a STRING
           ├── inputArtifacts[]    names of artifacts produced earlier
           └── outputArtifacts[]   names this action produces
```

Two details that trip people:

- **`actionTypeId` has four parts and all four are required.** `category` is one of `Source`, `Build`,
  `Test`, `Deploy`, `Approval`, `Invoke`. `owner` is `AWS`, `ThirdParty`, or `Custom`. `version` is
  the string `"1"` - a string, not a number, for every action type in use today.
- **Every value in `configuration` is a string.** `"PollForSourceChanges": "false"` is the *string*
  `false`. A JSON boolean there is rejected, and the message is about the structure, not the type.

Artifact names - `SourceOutput`, `BuildOutput` - are local to the pipeline. They are how one action
says "give me what that one produced". They are not S3 keys; CodePipeline chooses those.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > templates/lab-11-pipeline.json << EOF
{
  "pipeline": {
    "name": "usms-enrolment-pipeline",
    "roleArn": "${PIPELINE_ROLE_ARN}",
    "artifactStore": {
      "type": "S3",
      "location": "usms-pipeline-artifacts"
    },
    "stages": [
      {
        "name": "Source",
        "actions": [
          {
            "name": "FetchSource",
            "actionTypeId": {
              "category": "Source",
              "owner": "AWS",
              "provider": "S3",
              "version": "1"
            },
            "runOrder": 1,
            "configuration": {
              "S3Bucket": "usms-pipeline-artifacts",
              "S3ObjectKey": "source/usms-enrolment-src.zip",
              "PollForSourceChanges": "false"
            },
            "inputArtifacts": [],
            "outputArtifacts": [ { "name": "SourceOutput" } ]
          }
        ]
      },
      {
        "name": "Build",
        "actions": [
          {
            "name": "BuildArtifact",
            "actionTypeId": {
              "category": "Build",
              "owner": "AWS",
              "provider": "CodeBuild",
              "version": "1"
            },
            "runOrder": 1,
            "configuration": {
              "ProjectName": "usms-enrolment-build"
            },
            "inputArtifacts": [ { "name": "SourceOutput" } ],
            "outputArtifacts": [ { "name": "BuildOutput" } ]
          }
        ]
      }
    ]
  }
}
EOF

python3 -m json.tool templates/lab-11-pipeline.json > /dev/null && echo "pipeline template is valid JSON"
grep -c '\$' templates/lab-11-pipeline.json
```

**What the command does**

Unquoted heredoc again, for `${PIPELINE_ROLE_ARN}`, and the same `grep -c '\$'` check afterwards. The
answer must be `0`.

`"PollForSourceChanges": "false"` deserves a sentence. If it were `"true"`, CodePipeline would poll
the S3 object every minute and start an execution whenever the version ID changed. Polling is the old
mechanism; the modern one is an EventBridge rule fed by CloudTrail data events on that object. This
lab uses neither - executions are started by hand with `start-pipeline-execution` - because polling on
an emulator is an unreliable thing to build a laboratory step on, and because starting an execution by
hand makes the causal chain visible. Exercise 4 asks you to write the EventBridge rule.

**Expected result**

```text
pipeline template is valid JSON
0
```

> Example output.

---

### Step 17 - Create the pipeline

**Purpose**

Turn the document into a running pipeline, and learn to read `get-pipeline-state`, which is the one
command you will use most.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws codepipeline create-pipeline \
  --cli-input-json file://templates/lab-11-pipeline.json \
  --query 'pipeline.{Name:name,Role:roleArn,Stages:length(stages)}' \
  --output table
```

**Expected result**

```text
-------------------------------------------------------------------------
|                            CreatePipeline                             |
+---------+-------------------------------------------------+-----------+
|  Name   |                     Role                        |  Stages   |
+---------+-------------------------------------------------+-----------+
|  usms-enrolment-pipeline | arn:aws:iam::000000000000:role/usms-codepipeline-role | 2 |
+---------+-------------------------------------------------+-----------+
```

> Example output - the table's column layout depends on your terminal width.

!!! warning "Creating a pipeline starts an execution immediately"
    CodePipeline runs the pipeline once as soon as it is created. You did not ask for that and you
    cannot turn it off. That first execution will use the project as it is configured *right now* -
    with its own S3 source - which is the configuration Step 18 is about to change.

    Let it run. Note what it does. Step 18 explains why the result is ambiguous, and Step 19 is the
    execution whose result you will actually rely on.

**Verify**

```bash
aws codepipeline get-pipeline-state --name usms-enrolment-pipeline \
  --query 'stageStates[].{Stage:stageName,Status:latestExecution.status,Action:actionStates[0].actionName,ActionStatus:actionStates[0].latestExecution.status}' \
  --output table
```

**Expected result**

```text
---------------------------------------------------------------
|                      GetPipelineState                       |
+--------------+-------------+------------+-------------------+
|    Action    |ActionStatus |   Stage    |      Status       |
+--------------+-------------+------------+-------------------+
|  FetchSource |  Succeeded  |  Source    |  Succeeded        |
|  BuildArtifact|  InProgress|  Build     |  InProgress       |
+--------------+-------------+------------+-------------------+
```

> Example output - on a build where CodeBuild does not run, the Build row stays `InProgress` and then
> reads `Failed`. Both are informative; neither blocks the rest of this lab.

**What to look for:** the Source stage reaching `Succeeded` is the meaningful signal here. It proves
three things at once: the bucket is versioned, the object exists at the key you named, and the
pipeline role can read it.

!!! note "Floci Limitation - pipeline execution state may not advance"
    Some builds create pipelines, store them, return them faithfully from `get-pipeline`, and never
    execute them. `get-pipeline-state` then shows stages with no `latestExecution` at all.

    On real AWS an execution starts within seconds of `create-pipeline` and every transition is
    visible in `list-pipeline-executions`.

    If your stage states are empty, you are on Path B or Path C. Record the pipeline document you
    wrote, run the local runner from Step 14 to produce the artifact, and say so in your report.
    Sections 13 and 14 are written so that every exercise and every assessment item is completable on
    all three paths.

**Checkpoint 7**

```text
CodePipeline: usms-enrolment-pipeline
 ├── role: usms-codepipeline-role
 ├── artifact store: s3://usms-pipeline-artifacts
 ├── Stage 1 Source  -> S3  source/usms-enrolment-src.zip   -> SourceOutput
 └── Stage 2 Build   -> CodeBuild usms-enrolment-build      -> BuildOutput
```

---

### Step 18 - Hand the project to the pipeline

**Purpose**

Make it unambiguous which source the build builds. Right now the project has an S3 source of its own
*and* is being handed an input artifact by the pipeline. Two sources, one build: that is exactly the
kind of arrangement where everything succeeds and you cannot say what happened.

**Concept first - the trade-off you are about to make**

Setting `source.type` to `CODEPIPELINE` means "my source comes from whoever invoked me". After this
change:

- the pipeline's Build stage unambiguously builds the artifact the Source stage produced;
- `aws codebuild start-build --project-name usms-enrolment-build` **stops working**, because the
  project no longer knows where any source is.

That second point is the cost, and it is worth knowing before you pay it. There is an escape hatch -
`start-build` accepts `--source-type-override` and `--source-location-override`, which let you run a
one-off build of a `CODEPIPELINE` project against an explicit source. It is shown below, because at
some point you will need to reproduce a pipeline build by hand.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws codebuild update-project \
  --name usms-enrolment-build \
  --source type=CODEPIPELINE,buildspec=buildspec.yml \
  --artifacts type=CODEPIPELINE \
  --query 'project.{Source:source.type,Artifacts:artifacts.type}' \
  --output table
```

**What the command does**

`update-project` replaces the members you name and leaves the rest alone - the environment, the role,
the timeout and the tags all survive. `--source type=CODEPIPELINE,buildspec=buildspec.yml` keeps the
buildspec *path* while dropping the location, because the buildspec still has to be found at the root
of whatever artifact arrives.

**Expected result**

```text
------------------------------
|        UpdateProject       |
+---------------+------------+
|   Artifacts   |   Source   |
+---------------+------------+
|  CODEPIPELINE |CODEPIPELINE|
+---------------+------------+
```

> Example output.

**Verify - the escape hatch, and the cost**

```bash
aws codebuild start-build --project-name usms-enrolment-build 2>&1 | head -3
```

**What to look for:** an error. On real AWS it is an `InvalidInputException` explaining that a project
with a `CODEPIPELINE` source cannot be built directly; on Floci the wording differs. Either way, this
is the expected result and it is the point of the step. If it *succeeds*, your build accepted a build
with no source, and you should note that in Section 12's "recorded, not observed" list.

The one-off override, for when you need to reproduce a pipeline build by hand:

```bash
aws codebuild start-build \
  --project-name usms-enrolment-build \
  --source-type-override S3 \
  --source-location-override usms-pipeline-artifacts/source/usms-enrolment-src.zip \
  --query 'build.id' --output text
```

**What to look for:** a build ID. If your build of Floci rejects the override flags, record that and
move on - the pipeline in Step 19 is the path that matters, and the local runner is the path that
always works.

---

### Step 19 - Run the pipeline end to end, and prove it consumed your source

**Purpose**

The whole laboratory converges here. Change one line of source, and show - not assert - that the
change travelled through the pipeline into the build artifact.

**Concept first - the proof, again**

`create → perturb → read back`. The artifact from the first execution says `release: r3`. You change
`VERSION` to `r4`, repackage, upload a new version of the object, and start an execution. Then you
fetch the *output artifact* out of S3 and look inside it. If it says `r4`, the pipeline read your new
source, ran your buildspec against it, and wrote the result where it said it would. If it says `r3`,
something in that chain did not happen, no matter what status the console shows.

A green pipeline is not evidence. The contents of the artifact are evidence.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, perturb**

```bash
cd ~/aws-floci-course

printf 'r4\n' > labs/lab-11-cicd/app/VERSION

./scripts/utilities/usms-pack-source.sh \
  labs/lab-11-cicd/app \
  outputs/usms-enrolment-src.zip

NEW_VERSION_ID=$(aws s3api put-object \
  --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip \
  --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text)

echo "uploaded source version: $NEW_VERSION_ID"

aws s3api list-object-versions --bucket usms-pipeline-artifacts \
  --prefix source/usms-enrolment-src.zip \
  --query 'Versions[].{Version:VersionId,Latest:IsLatest,Modified:LastModified}' \
  --output table
```

**What to look for:** two versions, one `Latest`. The versioning you proved in Step 6 is now doing
real work: the old source is still retrievable, which is what makes "deploy the previous release"
possible without a rebuild.

**Command - part 2, run**

```bash
EXEC_ID=$(aws codepipeline start-pipeline-execution \
  --name usms-enrolment-pipeline \
  --query 'pipelineExecutionId' --output text)

echo "execution: $EXEC_ID"

for i in $(seq 1 30); do
  aws codepipeline get-pipeline-state --name usms-enrolment-pipeline \
    --query 'stageStates[].[stageName,latestExecution.status]' --output text |
    sed 's/^/    /'
  STATE=$(aws codepipeline get-pipeline-execution \
            --pipeline-name usms-enrolment-pipeline \
            --pipeline-execution-id "$EXEC_ID" \
            --query 'pipelineExecution.status' --output text 2>/dev/null)
  printf '  %2d  execution=%s\n' "$i" "${STATE:-unknown}"
  case "$STATE" in
    Succeeded|Failed|Stopped|Superseded) break ;;
  esac
  sleep 10
done
```

**Expected result**

```text
execution: 7c1f0a92-3b5d-4a11-9e0c-5d3a8f2b6e40
    Source	Succeeded
    Build	InProgress
   1  execution=InProgress
    Source	Succeeded
    Build	Succeeded
   2  execution=Succeeded
```

> Example output - your execution ID and the number of poll iterations will differ.

**Command - part 3, read back**

```bash
BUILD_ART_KEY=$(aws s3api list-objects-v2 \
  --bucket usms-pipeline-artifacts \
  --prefix usms-enrolment-pipeline/BuildOutput/ \
  --query 'sort_by(Contents, &LastModified)[-1].Key' --output text)

echo "newest build artifact: $BUILD_ART_KEY"

aws s3api get-object \
  --bucket usms-pipeline-artifacts \
  --key "$BUILD_ART_KEY" \
  outputs/lab-11-buildoutput.zip > /dev/null

python3 - << 'PY'
import json, zipfile
with zipfile.ZipFile("outputs/lab-11-buildoutput.zip") as z:
    names = sorted(z.namelist())
    print("artifact contents:")
    for n in names:
        print("   ", n)
    meta = json.loads(z.read("build-metadata.json"))
print("release  :", meta["release"])
print("builtAt  :", meta["builtAt"])
print("buildId  :", meta["buildId"])
print("srcVersion:", meta["sourceVersion"])
PY
```

**What the command does**

`sort_by(Contents, &LastModified)[-1].Key` is new JMESPath surface and Appendix B records it:
`sort_by` takes a list and an expression reference - the `&` - and `[-1]` takes the last element,
which after sorting by modification time is the newest. Doing this in JMESPath rather than piping
through `sort` keeps it on one line and works identically on both operating systems.

**Expected result**

```text
newest build artifact: usms-enrolment-pipeline/BuildOutput/A1b2C3d.zip
artifact contents:
    build-metadata.json
    healthz.html
    index.html
    service.json
release  : r4
builtAt  : 2026-09-17T09:58:11Z
buildId  : usms-enrolment-build:1d0a...
srcVersion: 3HL9pQ...
```

> Example output - your key, timestamps and IDs will differ.

**What to look for:** four things, in this order of importance.

1. **`release` is `r4`.** The pipeline consumed the source you uploaded ninety seconds ago, not a
   cached copy of anything.
2. **`buildId` is not `local`.** The artifact came from CodeBuild, not from your laptop. If it says
   `local`, you have downloaded an artifact your local runner produced and copied by hand - which is
   a legitimate Path B or Path C result, but you must report it as such.
3. **The artifact's root is the files themselves**, with no `dist/` prefix. That is
   `artifacts.base-directory` doing its job, and Lab 12 depends on it.
4. **`srcVersion` matches `$NEW_VERSION_ID`** from part 1, if your build populates
   `CODEBUILD_RESOLVED_SOURCE_VERSION`. When it does, you have an unbroken chain from the byte you
   changed to the artifact that will be deployed.

✏️ **Your turn**

Roll the release forward once more, to `r5`, without looking at Step 19 again. Then answer, in
`notes/lab-11-notes.md`, using only command output as evidence: how many versions of
`source/usms-enrolment-src.zip` now exist, how many objects are under
`usms-enrolment-pipeline/BuildOutput/`, and why those two numbers are not necessarily equal.

```text
Expected result:
Three source versions. The number of BuildOutput objects depends on how many
executions ran, including the automatic one at Step 17 - and on Path B or C it
may be fewer. A correct answer explains the relationship, not just the counts.
```

**Checkpoint 8**

```text
s3://usms-pipeline-artifacts
 ├── source/usms-enrolment-src.zip          3 versions (r3, r4, r5)
 ├── build/usms-enrolment-build.zip         from the standalone build in Step 12
 └── usms-enrolment-pipeline/
      ├── SourceOutput/<random>.zip
      └── BuildOutput/<random>.zip          contains build-metadata.json with release r5
```

---
### Step 20 - Make the build fail on purpose, then fix it

**Purpose**

Every pipeline you will ever operate spends most of its interesting moments failing. Learning to read
a failure on a build you broke deliberately, where you already know the answer, is much cheaper than
learning it at 11pm on a build somebody else broke.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, break it**

```bash
cd ~/aws-floci-course

python3 - << 'PY'
import json
p = "labs/lab-11-cicd/app/config/service.json"
doc = json.load(open(p))
doc["container"] = "enrolment-api-v2"      # deliberately wrong
json.dump(doc, open(p, "w"), indent=2)
print("container is now:", doc["container"])
PY

./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip >/dev/null
aws s3api put-object --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text

BAD_EXEC=$(aws codepipeline start-pipeline-execution --name usms-enrolment-pipeline \
  --query 'pipelineExecutionId' --output text)
echo "execution: $BAD_EXEC"
```

**What the command does**

The change is one word in one JSON file, and it is the kind of change that looks harmless in a diff.
`pre_build` greps for `"container": "enrolment-api"` and exits 1 when it does not find it. Lab 12's
deploy stage would fail on the same mismatch, but much later and much more expensively - which is the
argument for putting the check in `pre_build` in the first place.

Note that the `grep` in the buildspec matches the two-space-indented form that `json.dump(indent=2)`
produces. A reformat of that file with different indentation would also fail the build. That is a
fragility worth noticing; Exercise 3 asks you to replace the grep with something that parses.

**Command - part 2, diagnose it**

```bash
sleep 20

aws codepipeline get-pipeline-state --name usms-enrolment-pipeline \
  --query 'stageStates[].{Stage:stageName,Status:latestExecution.status,Summary:actionStates[0].latestExecution.summary,Error:actionStates[0].latestExecution.errorDetails.message}' \
  --output json | tee outputs/lab-11-pipeline-state.json
```

**Expected result**

```text
[
    {
        "Stage": "Source",
        "Status": "Succeeded",
        "Summary": "Amazon S3 version id: 8Kd1...",
        "Error": null
    },
    {
        "Stage": "Build",
        "Status": "Failed",
        "Summary": "Build terminated with state: FAILED",
        "Error": "Error while executing command: grep -q ..."
    }
]
```

> Example output - the exact wording of the error differs between real AWS and this emulator, and on
> Path B or C the Build stage may report nothing at all.

**What to look for:** the failure is in **Build**, not Source, which already tells you the source was
fetched fine. Then work inward: pipeline stage → build → phase → command. The command below is the
inward step:

```bash
LAST_BUILD=$(aws codebuild list-builds-for-project --project-name usms-enrolment-build \
  --sort-order DESCENDING --query 'ids[0]' --output text 2>/dev/null)

aws codebuild batch-get-builds --ids "$LAST_BUILD" \
  --query 'builds[0].phases[?phaseStatus==`FAILED`].{Phase:phaseType,Status:phaseStatus,Context:contexts[0].message}' \
  --output table
```

**What to look for:** one row, `Phase` is `PRE_BUILD`. The `contexts[0].message` names the command
that exited non-zero. That four-step chain - stage, build, phase, command - is the whole diagnostic
method, and it does not change no matter how complicated the pipeline gets.

!!! note "Floci Limitation - `list-builds-for-project` and `contexts`"
    Some builds do not implement `list-builds-for-project`, and many do not populate `contexts` on a
    failed phase.

    On real AWS both are reliable, and `contexts[0].message` is usually the fastest route to the
    failing command.

    If either is unavailable, reproduce the failure locally - the local runner from Step 14 prints
    the failing command directly, because it is running in your own terminal. That is Path B and
    Path C's diagnostic route, and it is not a worse one.

**Command - part 3, fix it**

```bash
python3 - << 'PY'
import json
p = "labs/lab-11-cicd/app/config/service.json"
doc = json.load(open(p))
doc["container"] = "enrolment-api"
json.dump(doc, open(p, "w"), indent=2)
print("container is now:", doc["container"])
PY

./scripts/utilities/usms-buildspec-run.sh labs/lab-11-cicd/app >/dev/null 2>&1 \
  && echo "local build passes again" || echo "local build STILL fails - fix it before repacking"

./scripts/utilities/usms-pack-source.sh labs/lab-11-cicd/app outputs/usms-enrolment-src.zip >/dev/null
aws s3api put-object --bucket usms-pipeline-artifacts \
  --key source/usms-enrolment-src.zip --body outputs/usms-enrolment-src.zip \
  --query 'VersionId' --output text

aws codepipeline start-pipeline-execution --name usms-enrolment-pipeline \
  --query 'pipelineExecutionId' --output text
```

**What to look for:** `local build passes again` **before** you repackage. That ordering is the habit
worth forming - validate locally, then push. A pipeline is not a place to find out whether your change
works; it is a place to record that it did.

**Checkpoint 9**

```text
usms-enrolment-pipeline
 ├── execution 1  (automatic, at creation)     - result depends on your path
 ├── execution 2  r4                            Succeeded
 ├── execution 3  r5                            Succeeded   (your turn, Step 19)
 ├── execution 4  broken container name         Failed at Build / PRE_BUILD
 └── execution 5  fixed                         Succeeded
```

---

### Step 21 - Record this lab's outputs, and commit

**Purpose**

Shell variables die with the terminal. `PIPELINE_ROLE_ARN`, `BUILD_ID`, `NEW_VERSION_ID` - all of them
are gone the moment you close this window, and Lab 12 needs most of what they held. Writing them to
`configs/lab-11.env` is what makes the next lab possible without repeating this one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

cat > configs/lab-11.env << EOF
# Lab 11 - CI/CD: source, build, and the pipeline that joins them
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, ARNs and IDs only. NO SECRETS. Safe to commit.

# --- artifact store and source ---
export USMS_PIPELINE_BUCKET=usms-pipeline-artifacts
export USMS_PIPELINE_BUCKET_VERSIONING=$(aws s3api get-bucket-versioning \
    --bucket usms-pipeline-artifacts --query 'Status' --output text 2>/dev/null \
    | grep -E '^(Enabled|Suspended)$' || echo Unknown)
export USMS_SOURCE_KEY=source/usms-enrolment-src.zip
export USMS_SOURCE_VERSION_ID=$(aws s3api head-object \
    --bucket usms-pipeline-artifacts --key source/usms-enrolment-src.zip \
    --query 'VersionId' --output text 2>/dev/null || echo not-created)
export USMS_BUILD_ARTIFACT_PREFIX=usms-enrolment-pipeline/BuildOutput/

# --- build project ---
export USMS_BUILD_PROJECT=usms-enrolment-build
export USMS_BUILD_PROJECT_ARN=$(aws codebuild batch-get-projects --names usms-enrolment-build \
    --query 'projects[0].arn' --output text 2>/dev/null | grep -E '^arn:' || echo not-created)
export USMS_BUILD_SOURCE_TYPE=$(aws codebuild batch-get-projects --names usms-enrolment-build \
    --query 'projects[0].source.type' --output text 2>/dev/null | grep -E '^[A-Z_]+$' || echo not-created)
export USMS_BUILD_IMAGE=aws/codebuild/standard:7.0
export USMS_BUILD_COMPUTE_TYPE=BUILD_GENERAL1_SMALL
export USMS_BUILD_TIMEOUT_MINUTES=15
export USMS_BUILD_LOG_GROUP=/aws/codebuild/usms-enrolment-build

# --- build identity ---
export USMS_BUILD_ROLE=usms-codebuild-role
export USMS_BUILD_ROLE_ARN=$(aws iam get-role --role-name usms-codebuild-role \
    --query 'Role.Arn' --output text)
export USMS_POLICY_CODEBUILD=USMSCodeBuildBase
export USMS_POLICY_CODEBUILD_ARN=arn:aws:iam::000000000000:policy/USMSCodeBuildBase

# --- pipeline ---
export USMS_PIPELINE_NAME=usms-enrolment-pipeline
export USMS_PIPELINE_STAGE_COUNT=$(aws codepipeline get-pipeline --name usms-enrolment-pipeline \
    --query 'length(pipeline.stages)' --output text 2>/dev/null | grep -E '^[0-9]+$' || echo 0)
export USMS_PIPELINE_ROLE=usms-codepipeline-role
export USMS_PIPELINE_ROLE_ARN=$(aws iam get-role --role-name usms-codepipeline-role \
    --query 'Role.Arn' --output text)
export USMS_POLICY_CODEPIPELINE=USMSCodePipelineBase
export USMS_POLICY_CODEPIPELINE_ARN=arn:aws:iam::000000000000:policy/USMSCodePipelineBase

# --- source tree ---
export USMS_APP_SRC_DIR=labs/lab-11-cicd/app
export USMS_BUILDSPEC=labs/lab-11-cicd/app/buildspec.yml
export USMS_RELEASE_TAG=$(tr -d '[:space:]' < labs/lab-11-cicd/app/VERSION)
export USMS_CICD_SUPPORT_PATH=$(sed -n 's/^USMS_CICD_SUPPORT_PATH=//p' \
    outputs/lab-11-support-probe.txt 2>/dev/null || echo unknown)
EOF

grep -n 'export .*=$\|None' configs/lab-11.env || echo "all values populated"
grep -c '^export' configs/lab-11.env
```

**What the command does**

**Unquoted** heredoc, `<< EOF`, because every `$(...)` must run now and be replaced by its answer. The
file that lands on disk contains no command substitutions at all - check it with `grep '\$(' ` if you
want to see that for yourself. This is the opposite of Step 8's `<< 'BUILDSPEC'`, where the `$` signs
had to survive untouched, and Step 9's `<< 'EOF'`, where the JSON had to be written literally. Same
syntax, one quote of difference, opposite behaviour, no error message when you get it backwards.

The `| grep -E '...' || echo not-created` idiom on the project and pipeline lookups is Lab 06's
pattern. On Path B or C those resources genuinely do not exist, and an env file full of the literal
string `None` is worse than one that says `not-created` - because `None` is also what a successful
call returns for an absent field, and you could not tell the two apart later.

**Expected result**

```text
all values populated
26
```

> Example output - on Path B or C some values read `not-created`, which is populated and correct.

**Verify**

```bash
source configs/lab-11.env
printf 'bucket=%s versioning=%s project=%s stages=%s release=%s path=%s\n' \
  "$USMS_PIPELINE_BUCKET" "$USMS_PIPELINE_BUCKET_VERSIONING" \
  "$USMS_BUILD_PROJECT" "$USMS_PIPELINE_STAGE_COUNT" \
  "$USMS_RELEASE_TAG" "$USMS_CICD_SUPPORT_PATH"
```

**What to look for:** `versioning=Enabled`, `stages=2` on Path A, and `release=r5` if you did the
Step 19 "Your turn". A `versioning=Unknown` here means Step 5 did not take effect and Lab 12 will
fail at its first pipeline update.

**Command - commit**

```bash
git status --short
```

**What to look for:** before you stage anything, read that list. **No file under `outputs/` and no
`.env` other than `configs/lab-11.env` may appear.** If one does, stop and fix `.gitignore` rather
than committing carefully - a rule you have to remember is a rule that will be forgotten.

```bash
git add configs/lab-11.env \
        labs/lab-11-cicd \
        policies/trust-codebuild.json policies/trust-codepipeline.json \
        policies/usms-codebuild-policy.json policies/usms-codepipeline-policy.json \
        templates/lab-11-codebuild-project.json templates/lab-11-pipeline.json \
        scripts/utilities/cicd-support-probe.sh \
        scripts/utilities/usms-pack-source.sh \
        scripts/utilities/usms-buildspec-run.sh \
        .gitignore

git status --short
git commit -m "Lab 11: source tree, buildspec, CodeBuild project and two-stage pipeline"
```

**Checkpoint 10**

```text
configs/lab-11.env        26 exports, all populated
git                        committed; nothing from outputs/ staged
```

---

## 9. Verification

One script, run from anywhere, that checks this lab's artefacts **and** the environment they depend
on. A verification script that only checks its own resources passes right up until the restart that
deletes them, which is why the environment block comes first and why its failures matter more than
the ones below it.

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cat > scripts/utilities/verify-lab-11.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 11 artefact. Exit 1 if anything is missing.
# EXPECTED: PASS=46  FAIL=0        (Path A)
#           PASS=38  FAIL=8        (Path B or C - the CodeBuild/CodePipeline block)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
for f in configs/lab-01.env configs/lab-04.env configs/lab-05.env \
         configs/lab-10.env configs/lab-11.env; do
  # shellcheck disable=SC1090
  [ -f "$f" ] && source "$f"
done

: "${FLOCI_CONTAINER_NAME:=floci}"
: "${USMS_PIPELINE_BUCKET:=usms-pipeline-artifacts}"
: "${USMS_BUILD_PROJECT:=usms-enrolment-build}"
: "${USMS_PIPELINE_NAME:=usms-enrolment-pipeline}"
: "${USMS_BUILD_ROLE:=usms-codebuild-role}"
: "${USMS_PIPELINE_ROLE:=usms-codepipeline-role}"
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ENROLMENT_CONTAINER:=enrolment-api}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}
proj() { aws codebuild batch-get-projects --names "$USMS_BUILD_PROJECT" --query "projects[0].$1" --output text; }
pipe() { aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" --query "pipeline.$1" --output text; }
spec="labs/lab-11-cicd/app/buildspec.yml"

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Earlier-lab dependencies =="
check "configs/lab-04.env present" "test -f configs/lab-04.env"
check "configs/lab-10.env present"  "test -f configs/lab-10.env"
check "ECS cluster $USMS_ECS_CLUSTER exists" \
  "test \"\$(aws ecs describe-clusters --clusters $USMS_ECS_CLUSTER --query 'clusters[0].status' --output text)\" = ACTIVE"
check "ECS service $USMS_ENROLMENT_SERVICE exists" \
  "aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE --query 'services[0].serviceName' --output text | grep -q ."
check "container name is enrolment-api" "test \"$USMS_ENROLMENT_CONTAINER\" = enrolment-api"

echo "== Artifact store =="
check "bucket $USMS_PIPELINE_BUCKET exists" "aws s3api head-bucket --bucket $USMS_PIPELINE_BUCKET"
check "versioning is Enabled" \
  "test \"\$(aws s3api get-bucket-versioning --bucket $USMS_PIPELINE_BUCKET --query Status --output text)\" = Enabled"
check "public access is blocked" \
  "aws s3api get-public-access-block --bucket $USMS_PIPELINE_BUCKET --query 'PublicAccessBlockConfiguration.BlockPublicAcls' --output text | grep -qi true"
check "source object present" \
  "aws s3api head-object --bucket $USMS_PIPELINE_BUCKET --key source/usms-enrolment-src.zip"
check "source has at least two versions" \
  "test \"\$(aws s3api list-object-versions --bucket $USMS_PIPELINE_BUCKET --prefix source/usms-enrolment-src.zip --query 'length(Versions || \`[]\`)' --output text)\" -ge 2"

echo "== Pipeline identities =="
check "role $USMS_BUILD_ROLE exists" "aws iam get-role --role-name $USMS_BUILD_ROLE"
check "build role trusts codebuild.amazonaws.com" \
  "aws iam get-role --role-name $USMS_BUILD_ROLE --query 'Role.AssumeRolePolicyDocument' --output json | grep -q codebuild.amazonaws.com"
check "policy USMSCodeBuildBase exists" \
  "aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodeBuildBase"
check "USMSCodeBuildBase attached to the build role" \
  "aws iam list-attached-role-policies --role-name $USMS_BUILD_ROLE --query 'AttachedPolicies[].PolicyName' --output text | grep -q USMSCodeBuildBase"
check "role $USMS_PIPELINE_ROLE exists" "aws iam get-role --role-name $USMS_PIPELINE_ROLE"
check "pipeline role trusts codepipeline.amazonaws.com" \
  "aws iam get-role --role-name $USMS_PIPELINE_ROLE --query 'Role.AssumeRolePolicyDocument' --output json | grep -q codepipeline.amazonaws.com"
check "policy USMSCodePipelineBase exists" \
  "aws iam get-policy --policy-arn arn:aws:iam::000000000000:policy/USMSCodePipelineBase"
check "USMSCodePipelineBase attached to the pipeline role" \
  "aws iam list-attached-role-policies --role-name $USMS_PIPELINE_ROLE --query 'AttachedPolicies[].PolicyName' --output text | grep -q USMSCodePipelineBase"
check "pipeline policy scopes iam:PassRole" \
  "grep -q 'iam:PassedToService' policies/usms-codepipeline-policy.json"

echo "== CodeBuild =="
check "project $USMS_BUILD_PROJECT exists"        "proj name | grep -q $USMS_BUILD_PROJECT"
check "project source type is CODEPIPELINE"       "proj source.type | grep -q CODEPIPELINE"
check "project runs as $USMS_BUILD_ROLE"          "proj serviceRole | grep -q $USMS_BUILD_ROLE"
check "project image is standard:7.0"             "proj environment.image | grep -q 'standard:7.0'"

echo "== CodePipeline =="
check "pipeline $USMS_PIPELINE_NAME exists"       "pipe name | grep -q $USMS_PIPELINE_NAME"
check "pipeline has 2 stages"                     "test \"\$(pipe 'length(stages)')\" = 2"
check "stage 1 provider is S3"                    "pipe 'stages[0].actions[0].actionTypeId.provider' | grep -q '^S3$'"
check "stage 2 builds $USMS_BUILD_PROJECT"        "pipe 'stages[1].actions[0].configuration.ProjectName' | grep -q $USMS_BUILD_PROJECT"

echo "== Source tree and scripts =="
check "buildspec.yml present"                     "test -f $spec"
check "buildspec declares version 0.2"            "grep -qE '^version: 0\.2' $spec"
check "buildspec has all four phases"             "test \"\$(grep -cE '^  (install|pre_build|build|post_build):' $spec)\" = 4"
check "artifacts base-directory is dist"          "grep -qE '^  base-directory: dist' $spec"
check "smoke test is valid bash"                  "bash -n labs/lab-11-cicd/app/tests/smoke.sh"
check "usms-pack-source.sh executable and valid"  "test -x scripts/utilities/usms-pack-source.sh && bash -n scripts/utilities/usms-pack-source.sh"
check "usms-buildspec-run.sh executable and valid" "test -x scripts/utilities/usms-buildspec-run.sh && bash -n scripts/utilities/usms-buildspec-run.sh"

echo "== Files and Git hygiene =="
check "configs/lab-11.env present"               "test -f configs/lab-11.env"
check "no empty or None values in lab-11.env"    "! grep -qE 'export [A-Z_]+=$|=None$' configs/lab-11.env"
check "codebuild project template is valid JSON"  "python3 -m json.tool templates/lab-11-codebuild-project.json"
check "pipeline template is valid JSON"           "python3 -m json.tool templates/lab-11-pipeline.json"
check "templates contain no unexpanded variables" "! grep -q '[\$]' templates/lab-11-codebuild-project.json templates/lab-11-pipeline.json"
check "all four policy documents are valid JSON" \
  "python3 -m json.tool policies/trust-codebuild.json && python3 -m json.tool policies/trust-codepipeline.json && python3 -m json.tool policies/usms-codebuild-policy.json && python3 -m json.tool policies/usms-codepipeline-policy.json"
check "no secret is tracked"                      "! git ls-files | grep -q '^outputs/'"
check "build output dist/ is git-ignored"         "git check-ignore -q labs/lab-11-cicd/app/dist/build-metadata.json"

echo; echo "PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

Read the failures top-down, not bottom-up.

  Environment block failing        -> Floci is not running, or is in memory mode.
                                      Fix this first; everything below is a consequence.
  Earlier-lab dependencies failing -> re-run verify-lab-04.sh / verify-lab-10.sh.
  Artifact store failing           -> Step 5 and Step 6.
  CodeBuild / CodePipeline block   -> if the support probe said Path B or C, eight
                                      failures here are EXPECTED. Record the path.
  Source tree failing              -> Step 7, Step 8, Step 11, Step 14.
  Hygiene failing                  -> Step 21, and .gitignore.
REMEDY
fi
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-11.sh
bash -n scripts/utilities/verify-lab-11.sh && echo "syntax OK"
./scripts/utilities/verify-lab-11.sh
```{% endraw %}

**Expected result**

```text
PASS=46  FAIL=0
```

> Example output - Path B and Path C correctly read `PASS=38  FAIL=8`.

### 9.1 Known benign failures

| Failure | Benign when | What it means |
| --- | --- | --- |
| The four CodeBuild checks | Step 3 reported Path B or C | The service is absent. Your documents are still correct and validated |
| The four CodePipeline checks | Step 3 reported Path B or C | Same |
| `source has at least two versions` | You skipped the Step 19 "Your turn" | Upload the source once more; do not edit the check |
| `project source type is CODEPIPELINE` | You have not run Step 18 yet | **Not benign** after Step 18. Re-run `update-project` |
| `no secret is tracked` | Never | **Not benign.** Something under `outputs/` is in the index. Fix `.gitignore`, then `git rm --cached` it |
| `versioning is Enabled` | Never | **Not benign.** The pipeline depends on it. Return to Step 5 |

---

## 10. Checkpoints

| # | After Step | What must exist |
| --- | --- | --- |
| 1 | 3 | `cicd-support-probe.sh`, and your path recorded in `outputs/lab-11-support-probe.txt` |
| 2 | 6 | `usms-pipeline-artifacts` with versioning proved by two versions at one key, then cleaned |
| 3 | 8 | `labs/lab-11-cicd/app/` with `buildspec.yml`, `VERSION`, `src/`, `config/`, `tests/` |
| 4 | 10 | `usms-codebuild-role` + `USMSCodeBuildBase`; project `usms-enrolment-build`, source `S3` |
| 5 | 13 | One standalone build with ten recorded phases, and an object under `build/` |
| 6 | 14 | `usms-pack-source.sh` and `usms-buildspec-run.sh`; a local build producing `dist/` |
| 7 | 17 | `usms-enrolment-pipeline` with two stages, Source reaching `Succeeded` |
| 8 | 19 | A build artifact whose `build-metadata.json` names the release you just uploaded |
| 9 | 20 | One deliberately failed execution, diagnosed to a phase, then fixed |
| 10 | 21 | `configs/lab-11.env` with 26 populated exports, committed |

---
## 11. Troubleshooting

### `The bucket you are attempting to access must be addressed using the specified endpoint`

Your `AWS_PROFILE` is not `floci`, or `configs/course.env` was not sourced in this window. The CLI is
talking to real S3. Run `source configs/course.env` and `./scripts/utilities/whoami.sh`. If a **new**
terminal reproduces this, you have the Errata 01 defect - fix it there, not here.

### `Error calling startBuild: Project cannot be built directly. Source type is CODEPIPELINE`

Expected after Step 18, and the whole point of that step. Use the pipeline, or use
`start-build --source-type-override S3 --source-location-override <bucket>/<key>` for a one-off.

### `YAML_FILE_ERROR: YAML file does not exist` or `buildspec not found`

Three causes, in order of likelihood:

1. The zip has a top-level directory. Run `unzip -l outputs/usms-enrolment-src.zip` - if every line
   starts with `app/`, you zipped the directory instead of its contents. Re-run
   `usms-pack-source.sh`, which gets this right.
2. The file is named `buildspec.yaml`. CodeBuild's default is `buildspec.yml`, with no `a`.
3. The project's `source.buildspec` names a path that does not exist inside the artifact.

### `YAML_FILE_ERROR` with a parse complaint

Tabs. YAML forbids tab characters for indentation, and an editor that converts leading spaces to tabs
produces a file that looks identical and parses not at all. Check with
`grep -Pn '\t' labs/lab-11-cicd/app/buildspec.yml` on GNU grep, or
`grep -n "$(printf '\t')" labs/lab-11-cicd/app/buildspec.yml` anywhere.

### The build succeeds but produces no artifact

`artifacts.base-directory` does not match where the build wrote files. Add `ls -la` to the end of
`post_build` and read the log - or run the local runner, which leaves `dist/` on your disk where you
can look at it.

### The pipeline's Source stage fails with a versioning complaint

`put-bucket-versioning` did not take effect. `aws s3api get-bucket-versioning --bucket
usms-pipeline-artifacts` must print `Enabled`; an empty response means never-enabled, not disabled.
Return to Step 5, then re-run Step 6's two-version proof before trying the pipeline again.

### The pipeline's Build stage fails immediately with no build

The pipeline role cannot start the build. Read
`policies/usms-codepipeline-policy.json` and check the project ARN in
`StartAndWatchTheEnrolmentBuildOnly` matches the project you actually created, character for
character. Floci does not enforce IAM, so this failure is more likely to be a wrong `ProjectName` in
the pipeline's action configuration - check that too.

### Everything worked yesterday, nothing works today

Floci was restarted in memory mode, or the data directory moved. Run
`./scripts/utilities/floci-storage-check.sh` and read the first failing check. If a *new terminal*
is the thing that broke, see Errata 01.

### `list-builds-for-project` returns an error naming the operation

Not implemented on your build. Use the build ID you captured in Step 12, or
`aws codebuild list-builds --sort-order DESCENDING` if that is supported, or read the pipeline action
state instead.

### The local runner reports "built-in minimal parser" and a phase is missing

The minimal parser handles the subset described in Step 14 and nothing more. If you have added YAML
constructs it does not understand - anchors, flow sequences, multi-line folded scalars with `>` -
install PyYAML (`pip3 install --user pyyaml`) or simplify the buildspec. The parser's limits are
documented rather than hidden precisely so this failure is diagnosable.

---

## 12. Floci vs Real AWS

### 12.1 Feature by feature

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `codebuild create-project` / `batch-get-projects` | Full | Typically full | **Implemented in Floci** |
| Running a build in a container | Managed fleet, cached images, seconds to provision | Runs a local Docker container; must pull `aws/codebuild/standard:7.0` | **Floci Limitation** |
| Build phase reporting | Every phase timed, with `contexts` on failure | Phases usually present; `contexts` often empty | **Floci Limitation** |
| Build logs to CloudWatch | Complete, searchable, retained | Frequently empty even for builds that ran | **Floci Limitation** |
| `codepipeline create-pipeline` / `get-pipeline` | Full | Typically full - the document round-trips | **Implemented in Floci** |
| Pipeline execution | Stages transition; history retained for a year | Build-dependent; may never advance | **Floci Limitation** |
| S3 source versioning requirement | Enforced - pipeline creation fails without it | Usually enforced; occasionally not | **Floci Limitation** |
| Artifact store objects | Encrypted with a KMS key, lifecycle-managed | Plain objects, no encryption | **Floci Limitation** |
| `PollForSourceChanges` | Polls every minute; deprecated in favour of EventBridge | Not reliably implemented | **Floci Limitation** |
| EventBridge trigger on S3 object change | Requires CloudTrail data events; works | Not modelled end to end | **Conceptual / Real AWS** |
| IAM enforcement on the pipeline and build roles | Enforced; a missing `PassRole` fails the action | Not enforced - any policy behaves like `Allow *` | **Floci Limitation** |
| CodeBuild build badges, reports, test report groups | Full | Absent | **Conceptual / Real AWS** |
| Cross-region artifact stores | Supported with per-region stores | Absent | **Conceptual / Real AWS** |
| Manual approval actions | Full, with SNS notification | Not modelled | **Conceptual / Real AWS** |
| Pipeline type V2, variables, triggers, git branch filters | Full | Not modelled; V1 shape is what round-trips | **Conceptual / Real AWS** |
| CodeCommit as a source | Existing customers only - closed to new accounts since July 2024 | May exist, but teaching it would teach a closed door | **Conceptual / Real AWS** |
| Build cost | Per build-minute, by compute type | Free | **Floci Limitation** |

### 12.2 What you observed, and what you recorded

```text
OBSERVED - you saw this happen on your own machine
  the source tree packaged into a zip whose root is the tree's contents
  the buildspec parsed, and its four phases executed in order
  the seven smoke tests passing, and failing when a placeholder was not replaced
  a build artifact whose build-metadata.json named the release you had just set
  a deliberately broken config failing in pre_build and not in build
  two versions of one S3 key, and the older one still retrievable

RECORDED - correct, checkable by reading, not enforced here
  the CodeBuild service role's scoping to one log group and one bucket
  the explicit Deny on usms-student-data
  the pipeline role's iam:PassRole, scoped to one role and one receiving service
  the single project ARN in codebuild:StartBuild, rather than project/*

NOT AVAILABLE AT ALL
  automatic pipeline triggering from an S3 object change
  manual approval stages
  build reports and test report groups
  artifact-store encryption with a customer-managed key
```

If your Step 3 probe said Path B or Path C, move the corresponding lines from OBSERVED to RECORDED in
your own report. "I built a two-stage pipeline" and "I wrote and validated a two-stage pipeline
document, on a build that does not execute pipelines" are different claims, and the second one is
worth more than an overstated first one.

### 12.3 Where Floci is nicer than reality

Four traps, each of which will bite you on a real account:

- **Builds are instant and free.** On real AWS, `BUILD_GENERAL1_SMALL` is billed per build-minute, and
  a pipeline that rebuilds on every commit to a busy repository is a line item. `cache` exists for
  that reason; this lab left it empty because caching a build this small would be theatre.
- **No concurrency limits.** Real accounts have a concurrent-build quota, and a pipeline that fans out
  to twenty parallel builds will queue.
- **No propagation delay.** A role you created one second ago is usable immediately here. On real AWS,
  IAM is eventually consistent, and `create-role` followed straight away by `create-project` naming it
  is the single most common "it works the second time" failure in CI setup code.
- **Nothing is encrypted.** Real artifact stores are encrypted with a KMS key by default, and the
  build role needs `kms:Decrypt` on it. A policy that works here and omits KMS will fail there, and
  the error names the key rather than the bucket.

---

## 13. Independent Lab Exercises

Five exercises, increasing in difficulty. Requirements and constraints are given; commands are not.
Write your answers and evidence in `labs/lab-11-cicd/exercises.md`.

### Exercise 1 - Basic: a second build project for the results service

**Requirements**

Create a second CodeBuild project, `usms-results-build`, that builds a results-service source tree you
create at `labs/lab-11-cicd/app-results/`. It needs its own `VERSION`, one HTML file, and a
`buildspec.yml`.

**Constraints**

- Reuse `usms-codebuild-role`. Do not create a second role.
- The source zip goes to `source/usms-results-src.zip` in the same bucket.
- The project's source type is `S3`, so you can run it standalone.

**Expected outcome**

A successful standalone build, and an artifact under `build/` distinguishable from the enrolment
service's by its `build-metadata.json`.

**Hints**

Step 10's template is the shape. The only fields that change are `name`, `source.location`,
`artifacts.name` and the description. Think about whether `USMSCodeBuildBase` already permits what
this build needs, and say why in one sentence.

### Exercise 2 - Intermediate: a `finally` block and a build report

**Requirements**

Add a `finally` block to the `post_build` phase of the enrolment buildspec that runs whether the phase
succeeded or failed, and which writes a one-line summary to `dist/build-summary.txt` containing the
release, the exit status of the tests, and the timestamp.

**Constraints**

- The summary must be produced even when `tests/smoke.sh` fails.
- `dist/build-summary.txt` must appear in the artifact.
- The local runner from Step 14 does not implement `finally`; say what you changed about how you
  tested this, and what that means for the claim you are making.

**Expected outcome**

A build where you deliberately break a test, and the artifact still contains a summary saying the
tests failed.

**Hints**

`finally` is a sibling of `commands` inside a phase, at the same indentation. Its commands run after
`commands`, regardless of outcome. Remember that a failed `post_build` still fails the build - the
`finally` block does not rescue it, it only runs.

### Exercise 3 - Problem solving: make the configuration check robust

**Requirements**

The `pre_build` check `grep -q '"container": "enrolment-api"'` depends on the exact whitespace of a
JSON file. Replace it with a check that parses the JSON and compares the value, and which fails with
a message naming both the expected and the actual container.

Then tighten `policies/trust-codebuild.json` with an `aws:SourceArn` condition naming the project ARN,
and explain in `notes/lab-11-notes.md` what attack that closes that `aws:SourceAccount` alone does
not.

**Constraints**

- The parse must use `python3` from the standard library. Do not add a dependency to the build.
- Prove the new check works by reformatting `config/service.json` with four-space indentation - the
  build must still pass.
- Prove it fails correctly by changing the container name - the message must name both values.

**Expected outcome**

A build that is indifferent to formatting and specific about errors, and a trust policy with two
conditions.

**Hints**

`python3 -c` with a `sys.exit` on mismatch is enough. For the trust policy, look at what
`aws:SourceArn` means when the calling service is CodeBuild specifically - the resource in the ARN is
the project.

### Exercise 4 - Challenge: trigger the pipeline without polling

**Requirements**

`PollForSourceChanges` is `"false"`, so nothing starts your pipeline automatically. Design the
EventBridge-based trigger that would start it on real AWS when a new version of
`source/usms-enrolment-src.zip` is written, and build as much of it as this emulator supports.

Write the rule and the target as JSON documents in `templates/`, create them if the APIs exist, and
record precisely which part could not be demonstrated and why.

**Constraints**

- No polling. The design must be event-driven.
- The rule must match one object key, not the whole bucket.
- The target needs a role. Say which permissions it needs and why they are not the pipeline role's.

**Expected outcome**

Two validated JSON documents, a written account of the CloudTrail dependency, and an honest statement
of what ran and what did not.

**Hints**

S3 object-level events reach EventBridge one of two ways, and they are not equivalent: the bucket's
own EventBridge notification setting, or CloudTrail data events. Find out which one a
`PutObject` on a versioned object produces, and what `detail-type` to match. The target is
`codepipeline:StartPipelineExecution`.

### Exercise 5 - Integration: prepare the deployment contract for Lab 12

**Requirements**

Lab 12's Deploy stage needs a file called `imagedefinitions.json` at the root of the build artifact,
containing one entry whose `name` matches the ECS container name and whose `imageUri` names an image.

Extend the enrolment buildspec so that its `build` phase writes `imagedefinitions.json` into `dist/`,
taking the container name from `config/service.json` and the image URI from an environment variable
`IMAGE_URI` with a sensible default of the current placeholder image.

Then run the pipeline, download the artifact, and confirm the file is at the artifact root.

**Constraints**

- The container name must come from `config/service.json`, not be hard-coded twice.
- `imagedefinitions.json` must be a JSON **array**, even with one entry. Lab 12 fails on an object.
- Add an eighth assertion to `tests/smoke.sh` that validates it.
- Record the artifact key and the file's contents in
  `outputs/lab-11-lab08b-readiness.txt`, which Lab 12 Step 1 reads.

**Expected outcome**

A build artifact containing `imagedefinitions.json` at its root, and a readiness file Lab 12
consumes. This is the artefact that makes Lab 12 a continuation rather than a restart.

**Hints**

`python3 -c` can read `config/service.json` and write the array in one line. The `${IMAGE_URI:-...}`
default is the same shape as `${CODEBUILD_BUILD_ID:-local}` already in your buildspec. Lab 04 Step 15
tells you what the placeholder image currently is.

---

## 14. Lab Assessment Checklist

Tick each item only when you have the evidence, not when you remember doing it.

- [ ] `./scripts/utilities/cicd-support-probe.sh` run, and the path recorded in your notes
- [ ] `usms-pipeline-artifacts` created, versioned, and versioning **proved** by two versions at one key
- [ ] The probe objects deleted, with the danger admonition read before deleting
- [ ] `labs/lab-11-cicd/app/` complete: `VERSION`, `src/`, `config/`, `tests/`, `buildspec.yml`
- [ ] `buildspec.yml` has `version: 0.2`, four phases, and `artifacts.base-directory: dist`
- [ ] The nested-heredoc rule stated correctly in your notes: quoted writes text, unquoted writes result
- [ ] `usms-codebuild-role` and `USMSCodeBuildBase` created; the explicit `Deny` explained in one sentence
- [ ] `usms-enrolment-build` created from a template containing zero unexpanded `$`
- [ ] A standalone build run, and its ten phases read from `batch-get-builds`
- [ ] `usms-pack-source.sh` and `usms-buildspec-run.sh` written, `bash -n` clean, and used
- [ ] A local build producing `dist/` with `build-metadata.json` showing `buildId: local`
- [ ] `usms-codepipeline-role` and `USMSCodePipelineBase` created; `iam:PassRole` explained
- [ ] `usms-enrolment-pipeline` created with two stages, from a validated JSON document
- [ ] The project converted to `CODEPIPELINE`, and the resulting `start-build` failure observed
- [ ] A pipeline execution whose artifact proves the release you uploaded - the `create → perturb → read back` proof
- [ ] One deliberate failure, diagnosed stage → build → phase → command, then fixed
- [ ] `configs/lab-11.env` with 26 populated exports
- [ ] `./scripts/utilities/verify-lab-11.sh` run, with its count and any benign failures recorded
- [ ] `git status --short` checked before staging; nothing from `outputs/` committed
- [ ] Five exercises attempted, with Exercise 5's readiness file written
- [ ] Section 15's questions answered in prose in `notes/lab-11-notes.md`

---

## 15. Review Questions

Answer in prose, in `notes/lab-11-notes.md`. No command output.

1. A pipeline's Source stage succeeds and its Build stage succeeds, and the deployed application is
   unchanged. Give two different explanations, one involving `artifacts.base-directory` and one
   involving the source zip's internal layout, and say how you would distinguish them with one
   command each.

2. Why does CodePipeline require versioning on an S3 source bucket? Answer in terms of what an
   execution needs to record about itself, not in terms of "so you can roll back".

3. Explain `iam:PassRole` to somebody who thinks it is redundant - "I already have permission to
   create the project, so why do I need separate permission to say which role it uses?" Their
   objection is reasonable; answer it.

4. `usms-codebuild-role` and `usms-codepipeline-role` could have been one role with the union of both
   policies, and the pipeline would work identically. Argue for the two-role design, and then give the
   strongest argument against it that you can.

5. This course's three heredoc forms now appear side by side: `<< 'BUILDSPEC'` in Step 8,
   `<< META` nested inside it, and `<< EOF` in Step 21. For each, say what would break if it were the
   other form, and why no error message would tell you.

6. A colleague proposes removing `pre_build`'s configuration validation because "it duplicates what
   the deploy stage checks anyway". Under what circumstances are they right? Under what circumstances
   are they expensively wrong?

7. You are asked to prove to an auditor that release `r4` of the enrolment service was built from the
   source that was in the repository on a particular date. Using only what this lab created, describe
   the evidence chain you would present, and name the one link in it that is weakest.

---

## 16. What We Built

### 16.1 Reflection

At the start of this laboratory, changing the enrolment service meant typing a command, and the
record of what changed was your shell history. At the end, changing it means editing a file,
packaging it, and uploading it - and the record is an S3 version ID, a build ID, a pipeline execution
ID, and an artifact containing a `build-metadata.json` that links all three.

That chain is the deliverable. Not the pipeline; the chain. The pipeline is just the machine that
maintains it.

Two moments in this lab are worth remembering specifically. The first is Step 18, where handing the
project to the pipeline **broke** the ability to build it directly - a real trade-off, made visible,
rather than a configuration setting you flipped without noticing. The second is Step 19, where the
proof that the pipeline worked was not a green status but the contents of a zip file. Status is
reporting. Contents are evidence. Every system you operate will offer you the first when you need the
second.

### 16.2 KEEP and CLEAN UP

```text
╔══════════════════ KEEP ══════════════════╗    ╔═══════════ CLEAN UP ═══════════╗
║ usms-pipeline-artifacts   (and versions) ║    ║ probe/versioning.txt versions  ║
║ source/usms-enrolment-src.zip            ║    ║   - already deleted in Step 6  ║
║ usms-codebuild-role  + USMSCodeBuildBase ║    ║ usms-probe-delete-me           ║
║ usms-codepipeline-role                   ║    ║   - the Step 3 probe project,  ║
║   + USMSCodePipelineBase                 ║    ║     deleted by the probe. If   ║
║ usms-enrolment-build   (the project)     ║    ║     it survives, delete it     ║
║ usms-enrolment-pipeline                  ║    ║ labs/.../app/dist/             ║
║ labs/lab-11-cicd/app/  (the source)     ║    ║   - build output; git-ignored, ║
║ scripts/utilities/usms-pack-source.sh    ║    ║     regenerated every build    ║
║ scripts/utilities/usms-buildspec-run.sh  ║    ║ outputs/lab-11-*              ║
║ scripts/utilities/verify-lab-11.sh      ║    ║   - keep until your report is  ║
║ configs/lab-11.env                      ║    ║     written, then let them be  ║
╚══════════════════════════════════════════╝    ╚════════════════════════════════╝
```

Everything in the KEEP column is consumed by Lab 12. Do not delete any of it.

### 16.3 The end-of-course cleanup script

!!! danger "Read before running any delete command"
    **What will be deleted:** the pipeline, the build project, both roles, both customer-managed
    policies, and every object and object *version* in `usms-pipeline-artifacts`, then the bucket.

    **What depends on it:** Lab 12's entire deploy stage, and any report you have not yet written.

    **Reversible?** No. Deleted object versions are gone; deleted IAM policies take their version
    history with them.

    **Effect on later labs:** total for Lab 12. Run this only at the end of the course.

```bash
cat > scripts/cleanup/lab-11-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes everything Lab 11 created, dependencies inside-out.
# DO NOT RUN NOW.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/configs/course.env"
# shellcheck disable=SC1091
[ -f configs/lab-11.env ] && source configs/lab-11.env

: "${USMS_PIPELINE_BUCKET:=usms-pipeline-artifacts}"
: "${USMS_PIPELINE_NAME:=usms-enrolment-pipeline}"
: "${USMS_BUILD_PROJECT:=usms-enrolment-build}"

cat <<'WARN'
This deletes the Lab 11 pipeline, build project, roles, policies and the ENTIRE
artifact bucket including every object version. Lab 12 depends on all of it.

If Lab 12 has been completed, run scripts/cleanup/lab-12-cleanup.sh FIRST.
WARN

if aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" \
     --query 'length(pipeline.stages)' --output text 2>/dev/null | grep -qx '3'; then
  echo "REFUSING: the pipeline still has three stages, so Lab 12 has not been cleaned up." >&2
  exit 1
fi

printf 'Type exactly: DELETE USMS PIPELINE\n> '
read -r CONFIRM
[ "$CONFIRM" = "DELETE USMS PIPELINE" ] || { echo "aborted"; exit 1; }

say() { printf '\n== %s ==\n' "$1"; }

say "pipeline"
aws codepipeline delete-pipeline --name "$USMS_PIPELINE_NAME" 2>/dev/null || true

say "build project"
aws codebuild delete-project --name "$USMS_BUILD_PROJECT" 2>/dev/null || true

say "roles and policies"
for pair in "usms-codepipeline-role:USMSCodePipelineBase" "usms-codebuild-role:USMSCodeBuildBase"; do
  ROLE="${pair%%:*}"; POL="${pair##*:}"
  ARN="arn:aws:iam::000000000000:policy/$POL"
  aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$ARN" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE" 2>/dev/null || true
  for V in $(aws iam list-policy-versions --policy-arn "$ARN" \
               --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null); do
    aws iam delete-policy-version --policy-arn "$ARN" --version-id "$V" 2>/dev/null || true
  done
  aws iam delete-policy --policy-arn "$ARN" 2>/dev/null || true
done

say "artifact bucket: every version, then the bucket"
aws s3api list-object-versions --bucket "$USMS_PIPELINE_BUCKET" \
  --query '[Versions[].[Key,VersionId], DeleteMarkers[].[Key,VersionId]][]' \
  --output text 2>/dev/null |
while read -r KEY VID; do
  [ -n "${KEY:-}" ] && aws s3api delete-object --bucket "$USMS_PIPELINE_BUCKET" \
      --key "$KEY" --version-id "$VID" >/dev/null 2>&1 || true
done
aws s3api delete-bucket --bucket "$USMS_PIPELINE_BUCKET" 2>/dev/null || true

say "done"
echo "Lab 11 resources removed. The ECS platform from Lab 04/05 is untouched."
EOF

chmod +x scripts/cleanup/lab-11-cleanup.sh
bash -n scripts/cleanup/lab-11-cleanup.sh && echo "syntax OK - do NOT run it"
```

End-of-course run order, with this lab slotted in:

```text
scripts/cleanup/lab-12-cleanup.sh    (deploy stage, ECR repository, image)
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
  source tree ──> S3 (versioned) ──> CodePipeline ──> CodeBuild ──> artifact in S3
                                                                         │
                                                          Lab 12 picks up here ──> ECS

  usms-vpc
   ├── public  subnets a,b ── usms-enrolment-alb ── usms-enrolment-tg
   └── private subnets a,b ── usms-enrolment-svc (2-10 tasks, Fargate)
                                   └── container enrolment-api:80
                                         image: still the placeholder, until Lab 12
```

---

## 17. Preparation for the Next Lab

The next laboratory is **Lab 12 - Deploying to ECS from the Pipeline**, which is Practical 7
and carries the Practical 7 in-class assessment.

### What Lab 12 will consume

| Artefact | From | How Lab 12 uses it |
| --- | --- | --- |
| `usms-enrolment-pipeline` | Step 17 | Adds a third stage to this exact pipeline with `update-pipeline` |
| `usms-enrolment-build` | Step 10 | Turns on `privilegedMode` so the build can run `docker build` |
| `USMSCodeBuildBase` | Step 9 | Creates **version 2** with ECR push permissions, and sets it default |
| `USMSCodePipelineBase` | Step 15 | Creates version 2 with `ecs:UpdateService` and a second `iam:PassRole` |
| `labs/lab-11-cicd/app/` | Step 7 | Adds a `Dockerfile` beside the existing tree |
| `buildspec.yml` | Step 8 | Extends it: log in to ECR, build, tag, push, write `imagedefinitions.json` |
| `usms-pipeline-artifacts` | Step 5 | Unchanged; the deploy stage reads `BuildOutput` from it |
| `outputs/lab-11-lab08b-readiness.txt` | Exercise 5 | Read in Lab 12 Step 1 as the inventory of what it inherited |
| `configs/lab-11.env` | Step 21 | Sourced in Lab 12 Step 2 |

### The thing Lab 12 must be careful about

`update-pipeline` **replaces the whole pipeline document**. There is no "add a stage" operation. The
sequence has to be get, modify, put - and if you put a document containing only your new stage, the
two stages you built today disappear, silently, with a successful API call.

That is the same shape as Lab 10's warning about `put-bucket-notification-configuration`, and the same
category: `update-assume-role-policy`, `put-bucket-policy`, `put-bucket-tagging`,
`update-pipeline`. Replace-only APIs are worth recognising as a family, because every one of them will
happily delete something you did not mention.

### Pre-session checks

Run these before the next session. All four should pass.

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/verify-lab-11.sh              # PASS=46  FAIL=0  (or 38/8 on Path B or C)
./scripts/utilities/verify-lab-05.sh              # PASS=49  FAIL=0
grep -c '^export' configs/lab-11.env              # 26
docker info >/dev/null 2>&1 && echo "docker reachable"
```

The `docker info` check is new and is not decorative: Lab 12 builds a container image on your
machine, and a Docker daemon you cannot reach makes half of it impossible.

### Snapshot before you finish

```bash
floci snapshot save lab-11-complete
floci snapshot list
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-11.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

### Read ahead

Three things, each of which Lab 12 assumes you have thought about for five minutes:

- **A container image is identified by a tag or by a digest, and they are not the same.** A tag can be
  moved to point at different bytes; a digest cannot. Decide now which one you would want a production
  task definition to name, and what you would give up by choosing it.
- **The ECS deploy action does not register a task definition from a file you wrote.** It takes the
  service's current task definition, replaces the image of the container named in
  `imagedefinitions.json`, registers that as a new revision, and updates the service. Work out which
  changes to a task definition that mechanism can express and which it cannot.
- **`docker build` inside CodeBuild needs `privilegedMode`.** Find out what that flag actually turns
  on, and why a build that can run a privileged container is a build worth being careful about who can
  trigger.

---

## Appendix A - Command Reference

| Command | What it does here |
| --- | --- |
| `aws s3api create-bucket --bucket X` | Creates the bucket; no `--create-bucket-configuration` in `us-east-1` |
| `aws s3api put-bucket-versioning --versioning-configuration Status=Enabled` | Turns on versioning; required for an S3 pipeline source |
| `aws s3api list-object-versions --prefix K` | The only way to see anything but the current version |
| `aws s3api delete-object --key K --version-id V` | Deletes one specific version, permanently |
| `aws codebuild create-project --cli-input-json file://T` | Creates the project from a template |
| `aws codebuild batch-get-projects --names X` | Reads the project back; `projectsNotFound` tells you it is absent |
| `aws codebuild update-project --source type=CODEPIPELINE` | Hands the project's source to whoever invokes it |
| `aws codebuild start-build --project-name X` | Queues one build; returns immediately |
| `aws codebuild start-build --source-type-override S3 --source-location-override B/K` | One-off build of a `CODEPIPELINE` project |
| `aws codebuild batch-get-builds --ids I` | Status, per-phase timing, log stream names |
| `aws codebuild stop-build --id I` | Stops a build that will not progress |
| `aws codepipeline create-pipeline --cli-input-json file://T` | Creates the pipeline, and runs it once immediately |
| `aws codepipeline get-pipeline --name X` | Returns `{pipeline, metadata}`; only `pipeline` goes back in |
| `aws codepipeline get-pipeline-state --name X` | Per-stage status - the command you will use most |
| `aws codepipeline start-pipeline-execution --name X` | Starts an execution by hand |
| `aws codepipeline get-pipeline-execution --pipeline-execution-id E` | The status of one execution |
| `aws iam create-policy` / `attach-role-policy` | Customer-managed policy, attached to a role |
| `aws logs get-log-events --log-group-name G --log-stream-name S` | Reads a build's log, when the build ships one |

## Appendix B - New JMESPath and CLI patterns introduced

| Pattern | Meaning | Where |
| --- | --- | --- |
| `length(Versions \|\| ` + backtick + `[]` + backtick + `)` | Default an absent list to empty before taking its length | Step 6 |
| `sort_by(Contents, &LastModified)[-1].Key` | Sort by a field, take the newest; `&` makes an expression reference | Step 19 |
| `phases[?phaseStatus==` + backtick + `FAILED` + backtick + `]` | Filter a list by an exact value; backticks make it a JSON literal | Step 20 |
| `--cli-input-json file://T` | Supply an entire request body as a document | Steps 10, 17 |
| `--query 'projects[0].{A:a,B:b}'` | Reshape one element into a named table | Steps 10, 13 |
| `\| grep -E '^arn:' \|\| echo not-created` | Turn an absent resource into a populated env value | Step 21 |
| `- \|` in YAML | Literal block scalar - how a heredoc fits in a buildspec | Step 8 |
| `env -u VAR` | Run a command with a variable unset, so a check can actually fail | Errata 01, referenced |

## Sources

- [AWS CodePipeline User Guide - pipeline structure reference](https://docs.aws.amazon.com/codepipeline/latest/userguide/reference-pipeline-structure.html)
- [AWS CodePipeline User Guide - Amazon S3 source action](https://docs.aws.amazon.com/codepipeline/latest/userguide/action-reference-S3.html)
- [AWS CodePipeline User Guide - CodeBuild build action](https://docs.aws.amazon.com/codepipeline/latest/userguide/action-reference-CodeBuild.html)
- [AWS CodePipeline User Guide - input and output artifacts](https://docs.aws.amazon.com/codepipeline/latest/userguide/welcome-introducing-artifacts.html)
- [AWS CodePipeline User Guide - the CodePipeline service role](https://docs.aws.amazon.com/codepipeline/latest/userguide/security-iam.html)
- [AWS CodePipeline User Guide - change-detection methods for an S3 source](https://docs.aws.amazon.com/codepipeline/latest/userguide/create-cloudtrail-S3-source.html)
- [AWS CodeBuild User Guide - build specification reference](https://docs.aws.amazon.com/codebuild/latest/userguide/build-spec-ref.html)
- [AWS CodeBuild User Guide - environment variables in build environments](https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-env-vars.html)
- [AWS CodeBuild User Guide - build phase transitions](https://docs.aws.amazon.com/codebuild/latest/userguide/view-build-details.html)
- [AWS CodeBuild User Guide - docker images provided by CodeBuild](https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-available.html)
- [AWS CodeBuild User Guide - create a service role](https://docs.aws.amazon.com/codebuild/latest/userguide/setting-up.html)
- [AWS CodeBuild User Guide - use CodePipeline with CodeBuild](https://docs.aws.amazon.com/codebuild/latest/userguide/how-to-create-pipeline.html)
- [Amazon S3 User Guide - using versioning in S3 buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)
- [Amazon S3 User Guide - blocking public access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [IAM User Guide - granting a user permission to pass a role to a service](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html)
- [IAM User Guide - cross-service confused deputy prevention](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
- [IAM User Guide - versioning IAM policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-versioning.html)
- [AWS CodeCommit - availability change, July 2024](https://docs.aws.amazon.com/codecommit/latest/userguide/welcome.html)
- [AWS CLI Command Reference - aws codebuild](https://docs.aws.amazon.com/cli/latest/reference/codebuild/)
- [AWS CLI Command Reference - aws codepipeline](https://docs.aws.amazon.com/cli/latest/reference/codepipeline/)
- [AWS CLI Command Reference - aws s3api](https://docs.aws.amazon.com/cli/latest/reference/s3api/)
- [LocalStack documentation - CodeBuild and CodePipeline providers, which is the emulator behaviour this course calls Floci](https://docs.localstack.cloud/user-guide/aws/)
- [YAML 1.2 specification - block scalars](https://yaml.org/spec/1.2.2/)
- [JMESPath specification](https://jmespath.org/specification.html)
- Course documents: Lab 01 (IAM, heredoc rules, named profiles), Lab 04 Step 15
  (`--force-new-deployment` and image tags), Lab 05 (the target group and container name this
  pipeline will deploy to), Lab 09 Step 8 (`usms-deploy-role` and scoped `iam:PassRole`), Lab 10
  Step 2 (the tolerant loader), Errata 01.

---

*Lab 11 complete. There is now a machine that turns a change to a file into an artifact with a name,
a version and a record. Lab 12 connects the other end of it to the running service.*
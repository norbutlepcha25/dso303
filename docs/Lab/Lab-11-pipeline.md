# Lab 11 - Building a CI/CD Pipeline with AWS CodePipeline and CodeBuild

!!! info "Numbering"
    The module descriptor calls this Practical 5; the course delivers it as Practical 7 (Labs 11 and 12). Lab numbers follow the dependency graph. This lab depends on Labs 01, 04, 05 and 06; Lab 09 artefacts are optional.

## 1. Objectives

- Create a versioned S3 artifact store and prove versioning by create, perturb, read back.
- Write the enrolment service source tree and a `buildspec.yml`, and run it in CodeBuild and with a local runner.
- Create scoped CodeBuild and CodePipeline service roles, including a conditioned `iam:PassRole`.
- Build a two-stage pipeline (S3 Source, CodeBuild Build), prove from the artifact's contents that it consumed your source, and diagnose a deliberate failure.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [AWS CodeBuild](../unit5/topic1.md#aws-codebuild) ·
    [build reproducibility](../unit5/topic1.md#build-reproducibility-and-the-supply-chain) ·
    [separate build and deploy identities](../unit5/topic1.md#separation-of-build-and-deploy-identities) ·
    [AWS CodePipeline](../unit5/topic2.md#aws-codepipeline) ·
    [stages and actions](../unit5/topic2.md#stages-actions-and-the-parallelism-inside-a-stage) ·
    [S3 versioning](../unit6/topic1.md#the-life-of-an-object-under-versioning-and-lifecycle-rules) ·
    [iam:PassRole](../unit8/topic1.md#iampassrole) ·
    [the confused deputy problem](../unit8/topic1.md#the-confused-deputy-problem)

!!! warning "Do not run `aws login`"
    If you see `NoCredentials`, the AWS CLI v2 may suggest `aws login`, which signs in to **real AWS**. The answer here is always `source configs/course.env` or a missing `floci` profile. See Errata 01 Section 3.

---

## 2. Prerequisites

- Labs 01 to 06 complete. Labs 07 to 09 are helpful but not required; Step 2 tolerates their absence.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`.
- A **new** terminal already has `AWS_PROFILE` and `COURSE_ROOT` set (otherwise apply Errata 01 now).
- `docker` available to your user (CodeBuild on Floci runs builds in Docker containers).
- `python3`, `zip` and `unzip` on your path (`command -v zip unzip`; on Debian `sudo apt-get install -y zip unzip`; Step 11 has a `python3 -m zipfile` fallback).

```bash
cd ~/aws-floci-course
source configs/course.env

./scripts/utilities/floci-storage-check.sh      # PASS=16  FAIL=0
./scripts/utilities/verify-lab-04.sh           # PASS=48  FAIL=1  (or 49/0 after Lab 05 Exercise 2)
./scripts/utilities/verify-lab-05.sh           # PASS=49  FAIL=0
./scripts/utilities/verify-lab-10.sh            # PASS=51  FAIL=0
```

If `verify-lab-05.sh` fails, stop: Lab 12 deploys to the service it checks.

---

## 3. What This Lab Reuses

- From Lab 04: the cluster, `usms-enrolment-svc` and the container name `enrolment-api` (Step 2 checks; Lab 12's `imagedefinitions.json` must match it).
- From Lab 05: the service behind the load balancer that Lab 12 deploys to (`verify-lab-05.sh` in Section 2).
- From Lab 01: the bucket/object ARN split in `USMSStudentDataReadWrite`, repeated in Step 9's policy.
- From Lab 09 (optional): `USMSDeployBase`'s scoped `iam:PassRole`, compared in Step 15.
- Lab 04 Step 15's `--force-new-deployment` assumed an image that changes; the buildspec written in Step 8 is what Lab 12 extends to produce that image.

```text
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

---

## 4. What We Are Building

One pipeline with two stages. The enrolment service gets its own small source tree (a static portal, a health endpoint, a validated config and a `buildspec.yml`) to replace the placeholder nginx image Lab 04 used. The **Source** stage fetches `source/usms-enrolment-src.zip` from `usms-pipeline-artifacts`; an S3 source is used because AWS CodeCommit has been closed to new customers since July 2024, and it makes the artifact mechanism visible. The **Build** stage hands that zip to CodeBuild, which runs the buildspec's phases and writes the files named under `artifacts` back to the same bucket.

---

## 5. Architecture

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

## 6. Directory Structure

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
    └── lab-11-notes.md                     NEW  - your answers to Section 14
```

`app/` sits under `labs/lab-11-cicd/` rather than at the repository root on purpose. It is the
source of one service, owned by one lab. Lab 12 adds a `Dockerfile` to the same directory rather
than creating a second copy of the tree somewhere else.

---

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root unless a step's **Run from** says otherwise (Steps 7 and 8 run inside `labs/lab-11-cicd/app/`). If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Capture every ID with `$(...)`, `--query` and `--output text`. Step 21 writes them to `configs/lab-11.env` so Lab 12 can use them.

### Step 1 - Start Floci and confirm where you are

If the emulator is not in hybrid storage mode, tonight's pipeline is gone tomorrow while every command still reports success.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/floci-storage-check.sh
./scripts/utilities/whoami.sh
```

`floci-up.sh` refuses to adopt a container Compose did not create; `floci-storage-check.sh` runs sixteen checks (shell and profile, then storage); `whoami.sh` exits 1 if the account is not `000000000000`.

**Expected result**

```text
PASS=16  FAIL=0

  Account : 000000000000
  Arn     : arn:aws:iam::000000000000:root
  Endpoint: http://localhost:4566
```

> Example output - the account is always `000000000000` in Floci.

`PASS=16  FAIL=0`. `PASS=6` means the pre-Errata storage check: apply Errata 01 Patch 2. Fix any `-- shell and profile --` failure first.

---

### Step 2 - Source every earlier lab's environment

Read back the names earlier labs recorded.

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

An explicit list rather than `source configs/lab-*.env`, so an editor backup is never sourced and you see what was loaded. `absent` for an optional lab is information, not an error.

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

No line says `MISSING`. `USMS_ENROLMENT_CONTAINER` must read `enrolment-api`: a mismatch in Lab 12 produces a deploy failure whose message does not name the container.

---

### Step 3 - Probe CI/CD support and choose your path

Find out now which of three paths you are on, rather than at Step 19. An emulator may do the work, store the object without doing the work, or reject the operation; only the last is obvious, so the probe creates an object and reads it back.

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
  echo "         execution happens in Step 14's local runner. Section 11 tells you"
  echo "         exactly what to claim and what not to claim."
fi
printf 'USMS_CICD_SUPPORT_PATH=%s\n' "$PATHNAME" > outputs/lab-11-support-probe.txt
echo "recorded in outputs/lab-11-support-probe.txt"
EOF

chmod +x scripts/utilities/cicd-support-probe.sh
bash -n scripts/utilities/cicd-support-probe.sh && echo "syntax OK"
./scripts/utilities/cicd-support-probe.sh
```

- The probe project uses `type=NO_SOURCE` and `type=NO_ARTIFACTS`, the smallest legal project, and deletes it. The role ARN deliberately does not exist (Floci does not authorize calls).
- `buildspec='version: 0.2'` is the only inline buildspec in this lab.

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

Write your path on the first line of `notes/lab-11-notes.md` now; Section 11 asks what you observed versus recorded.

!!! note "Floci Limitation - CodeDeploy is very likely absent"
    Floci commonly rejects `codedeploy list-applications`.

    On real AWS, CodeDeploy runs blue/green ECS deployments: a second task set, traffic shifted by the load balancer, and fast rollback.

    Lab 12 Step 17 writes the CodeDeploy documents as Conceptual / Real AWS. Do not claim a blue/green deployment in your report.

**Checkpoint 1**

```text
aws-floci-course/
 ├── scripts/utilities/cicd-support-probe.sh   (executable)
 └── outputs/lab-11-support-probe.txt         USMS_CICD_SUPPORT_PATH=<A|B|C>
```

---

### Step 4 - Create this lab's directories

Create every directory this lab writes to, so no later step fails on a missing parent.

```bash
mkdir -p labs/lab-11-cicd/app/src \
         labs/lab-11-cicd/app/config \
         labs/lab-11-cicd/app/tests \
         policies templates scripts/utilities scripts/cleanup outputs notes

ls -d labs/lab-11-cicd/app/*
```

`mkdir -p` is safe to re-run; `ls -d` lists the directories themselves.

**Expected result**

```text
labs/lab-11-cicd/app/config
labs/lab-11-cicd/app/src
labs/lab-11-cicd/app/tests
```

> Example output.

---

### Step 5 - Create the pipeline artifact bucket

Every stage hands the next a zip file in one S3 bucket, the **artifact store**; this bucket also holds the source archive. Nothing streams between stages, so the bucket must be in the pipeline's Region, its policy must be scoped (artifacts contain configuration), and an unfamiliar key in an error is an artifact key (`<pipeline-name>/<OutputArtifactName>/<random>.zip`). See [AWS CodePipeline](../unit5/topic2.md#aws-codepipeline).

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

- In `us-east-1`, `create-bucket` takes no `--create-bucket-configuration`; every other Region requires `LocationConstraint`.
- `put-public-access-block` is not required by CodePipeline; an artifact bucket is the worst bucket to leave public.

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

`Status` must read `Enabled`. An empty response means versioning was never enabled (the API does not say `Disabled`).

---

### Step 6 - Prove versioning is on

CodePipeline refuses an unversioned S3 source, so prove what the bucket does, not what its configuration says: put two objects at one key, then list the versions. See [S3 versioning](../unit6/topic1.md#the-life-of-an-object-under-versioning-and-lifecycle-rules).

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

`list-object-versions` is the only listing that sees anything other than the current version.

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

**Two rows**, one with `Latest` `True`. One row means versioning is not in effect: re-run Step 5's `put-bucket-versioning` and this step. Do not continue; Step 17 would fail without mentioning versioning.

Clean up the probe object:

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

The final number is `0`. `Versions || [] ` (a backtick-quoted empty list) supplies a default when the field is absent, because `length(null)` is an error (Appendix).

**Checkpoint 2**

```text
s3://usms-pipeline-artifacts
 ├── versioning: Enabled     (proved by two versions at one key, then cleaned up)
 ├── public access: blocked
 └── tags: Project=USMS, Tier=pipeline, Lab=11
```

---

### Step 7 - Write the enrolment service source tree

Give the pipeline something to build, with a version number you can watch move through it.

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

`__RELEASE__` and `__BUILT_AT__` are replaced by the build, so their absence in the artifact proves a build ran (Step 19).

!!! warning "Quoted heredoc"
    `<< 'EOF'` writes text literally. `configs/lab-11.env` in Step 21 uses unquoted `<< EOF` so `$(...)` runs at write time. Opposite purposes, one character of difference.

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

The build, not the application, reads this file: `pre_build` fails if it is malformed or names the wrong container, catching the mistake in ninety seconds rather than in a rollback.

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

Four of the seven assertions check that a placeholder is **absent**, so a build that skipped substitution fails. `set -uo pipefail` without `-e` so every result prints.

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

Five files; `buildspec.yml` comes in Step 8.

---

### Step 8 - Write `buildspec.yml`

The centre of the lab: the build commands live in the source tree, so changing a build is a reviewable, versioned source change. See [AWS CodeBuild](../unit5/topic1.md#aws-codebuild).

| Key | What it is for |
| --- | --- |
| `version` | The buildspec format version. Use `0.2`. Version `0.1` ran every command in its own shell and is deprecated |
| `env` | Variables available to every phase, and which of them to export back to the pipeline |
| `phases` | The four named phases, in fixed order: `install`, `pre_build`, `build`, `post_build` |
| `artifacts` | Which files, of everything the build produced, are kept and handed to the next stage |
| `cache` | Directories preserved between builds. Empty here, and Section 11 says why |

Phases run in order and are reported separately, so a failure names its phase. Convention: `install` tools, `pre_build` checks that must pass first, `build` produces, `post_build` tests and writes what the next stage needs. `finally` (Exercise 2) runs whether a phase succeeded or not.

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

- `USMS_RELEASE` is recomputed in `build`, so the buildspec also works in Step 14's local runner.
- `sed -i.bak` works with GNU and BSD `sed` (BSD requires a suffix); the backup is removed.
- `${CODEBUILD_BUILD_ID:-local}` and `${CODEBUILD_RESOLVED_SOURCE_VERSION:-local}` are CodeBuild variables; the default marks a local build.
- `- |` is a YAML literal block: one multi-line command. The `pre_build` `grep` **must** be one, because a plain item containing `": "` parses as a mapping (`expected <block end>, but found '<scalar>'`).
- `artifacts.base-directory: dist` with `files: ['**/*']` makes `dist` the artifact root. Get it wrong and Lab 12 cannot find `imagedefinitions.json`.

!!! warning "The heredoc inside the heredoc"
    The outer `<< 'BUILDSPEC'` is **quoted**, so `$USMS_RELEASE`, `$ARTIFACT_DIR` and `${CODEBUILD_BUILD_ID:-local}` reach the file literally for CodeBuild to expand. The inner `<< META` is **unquoted**, because expansion is wanted at build time. Quoted heredoc writes the text; unquoted heredoc writes the result.

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

`version`, `phases`, `artifacts` and `base-directory` each appear exactly once. `version` twice means you pasted the file twice (`YAML_FILE_ERROR`).

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

A build container is a principal; its role is the answer to "what could a compromised build do?". Derive the permissions from the buildspec: write its own logs (`logs:CreateLogGroup`, `CreateLogStream`, `PutLogEvents`), and read the source and write the artifact (`s3:GetObject`, `GetObjectVersion`, `PutObject`, `GetBucketAcl`, `GetBucketLocation`). An explicit `Deny` on `usms-student-data` documents that builds never touch student records, even though Floci enforces nothing.

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

`aws:SourceAccount` is the confused-deputy guard (Lab 09 Step 6; [the confused deputy problem](../unit8/topic1.md#the-confused-deputy-problem)). On real AWS add `aws:SourceArn` with the project ARN (Exercise 3).

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

- Two log-group ARNs: without `:*` for `CreateLogGroup` on the group, with `:*` for the streams. Only one gives a half-working policy.
- Bucket ARN and object ARN are separate, as in Lab 01's `USMSStudentDataReadWrite`.

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

Exactly one attached policy, `USMSCodeBuildBase`, and principal `{"Service": "codebuild.amazonaws.com"}` (global, not `codebuild.us-east-1.amazonaws.com`).

---

### Step 10 - Create the CodeBuild project

The project holds how to build (image, compute, role, source, artifact, timeout), never the build commands. A project whose `source.type` is `CODEPIPELINE` **cannot be started on its own**, so this step uses an `S3` source, Step 12 runs it standalone, and Step 18 converts it.

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

!!! warning "Unquoted heredoc"
    `<< EOF` so `${BUILD_ROLE_ARN}` is substituted at write time. `grep -c '\$'` must print `0`; a surviving `$` means an empty variable and an invalid-ARN error that never mentions your shell.

CodeBuild tags use lowercase `key`/`value`; IAM and ELBv2 use `Key`/`Value`.

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

`Source` is `S3` and `Location` is `usms-pipeline-artifacts/source/usms-enrolment-src.zip`. An empty `projects` list with `projectsNotFound` populated means it was not created; read the `create-project` output rather than re-running it.

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

The buildspec must be at the **root** of the zip. A small packer script avoids getting that wrong on the four repackagings ahead.

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

`zip -r ../x.zip .` from inside the directory gives the first; `zip -r x.zip app/` from its parent gives the second.

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

- Prefers `zip`, falls back to Python's `zipfile`. Both exclude `dist/`, so a previous build's output never ships as source.
- The Python fallback drops the executable bit; harmless because the buildspec runs `bash tests/smoke.sh`.
- `OUT_ABS` is computed before the subshell `cd`, so a relative output path does not land in the wrong place.

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

`buildspec.yml` and `VERSION` at the top level, and **no path beginning with `app/`**. The last line is the object's S3 version ID; Step 19 uses it to prove what the pipeline consumed.

`outputs/` is git-ignored. Confirm the rule that protected you:

```bash
git check-ignore -v outputs/usms-enrolment-src.zip
```

The output names `.gitignore`, a line number and `outputs/*`. Silence means the file is not ignored (the `outputs/` form the course's Git rules warn about).

---

### Step 12 - Run the build on its own

Prove the build works before putting it in a pipeline; otherwise you debug two systems at once.

```bash
BUILD_ID=$(aws codebuild start-build \
  --project-name usms-enrolment-build \
  --query 'build.id' --output text)

echo "$BUILD_ID"
```

`start-build` returns immediately; the ID `usms-enrolment-build:<uuid>` is how you ask about the build.

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

The phase advances `QUEUED`, `PROVISIONING`, `INSTALL`, `PRE_BUILD`, `BUILD`, `POST_BUILD`, `UPLOAD_ARTIFACTS`, `COMPLETED`, ending at `status=SUCCEEDED`. A printing loop rather than a waiter shows whether nothing is happening or something is happening slowly.

!!! note "Floci Limitation - a build that never leaves PROVISIONING"
    Some builds accept `start-build` and never run it (pulling `aws/codebuild/standard:7.0` is multi-gigabyte), so you see `phase=PROVISIONING` forever.

    On real AWS provisioning takes seconds because the image is cached.

    After four minutes, stop it with `aws codebuild stop-build --id "$BUILD_ID"`, record it in `notes/lab-11-notes.md`, and go to Step 14. The local runner executes the same buildspec (Path B or C).

---

### Step 13 - Read the build output and the logs

Per-phase timing and the log are the pair you use for every failed build.

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

CodeBuild adds `SUBMITTED`, `QUEUED`, `PROVISIONING`, `DOWNLOAD_SOURCE`, `UPLOAD_ARTIFACTS`, `FINALIZING` and `COMPLETED` around your four phases. A `DOWNLOAD_SOURCE` failure is source or permissions; `PRE_BUILD` is your code; `PROVISIONING` is capacity or image.

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

Look for your `--- install ---` to `--- post_build ---` markers and the seven `ok` lines from `tests/smoke.sh`.

!!! note "Floci Limitation - empty build logs"
    CodeBuild log streams are often empty here even when the build ran.

    On real AWS the stream holds every line the build printed.

    If there are no events, check the phases and the artifact below; the artifact is the evidence that survives.

**Command - read the artifact back**

```bash
aws s3api list-objects-v2 --bucket usms-pipeline-artifacts --prefix build/ \
  --query 'Contents[].{Key:Key,Size:Size}' --output table
```

One object under `build/`: the read-back. `SUCCEEDED` with no artifact means `artifacts.base-directory` does not match where the build wrote files.

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

If Step 12 never left `PROVISIONING`, this runs your build anyway; and even when CodeBuild works, running the same phases in two seconds changes how you write them.

| Same | Different |
| --- | --- |
| The commands, from the same file | Runs on your machine, not `aws/codebuild/standard:7.0` |
| The phase order | `set -e` semantics: the runner stops at the first failure; CodeBuild still runs `post_build` after a failed `build` |
| `env.variables`, and the rule that an environment value overrides them | No `CODEBUILD_*` variables - the buildspec's `:-local` defaults fire |
| The artifacts directory it produces | Does not zip or upload anything |

"The build passed" and "the build passed locally" are different claims; say which.

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

- Python turns the buildspec into a shell script, `bash -n` checks it, and a subshell runs it inside the app directory (the parent shell never changes directory).
- Each `env.variables` entry becomes `export NAME="${NAME:-value}"`, so a value already in your environment wins, matching CodeBuild's project-level override (Lab 12 relies on it).
- PyYAML is preferred; the fallback parser handles exactly this course's subset (`env.variables`, `phases.<name>.commands`, `- command`, `- |`) and says which parser it used.

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

`"release": "r3"` and `"buildId": "local"` (the marker of a laptop build); `release: r3` and no `__RELEASE__` in `index.html`.

`dist/` is build output; the packer excludes it, and `.gitignore` should too:

```bash
grep -q '^labs/lab-11-cicd/app/dist/' .gitignore || \
  printf 'labs/lab-11-cicd/app/dist/\n' >> .gitignore

git check-ignore -v labs/lab-11-cicd/app/dist/build-metadata.json
```

The output names `.gitignore`, a line number and the pattern. A trailing-slash directory rule is fine here because nothing inside needs re-including.

**Checkpoint 6**

```text
scripts/utilities/
 ├── cicd-support-probe.sh
 ├── usms-pack-source.sh
 └── usms-buildspec-run.sh      runs buildspec.yml locally; 4 phases, 7 smoke tests, exit 0
```

---

### Step 15 - Create the CodePipeline service role and its policy

The pipeline is a separate principal: it can start builds and read every artifact, while the build can read one bucket and write logs. The pipeline does not build; it calls `codebuild:StartBuild` and CodeBuild runs **as `usms-codebuild-role`**. Handing a role to a service requires `iam:PassRole`, and `iam:PassedToService` pins the receiving service; without it, anyone who can create a project could name an administrator role. See [iam:PassRole](../unit8/topic1.md#iampassrole).

```text
usms-codepipeline-role  ──iam:PassRole──>  usms-codebuild-role  ──used by──>  codebuild.amazonaws.com
```

Lab 12 adds a second handoff, to the ECS task and execution roles, for exactly the same reason.

!!! info "Compare with `USMSDeployBase`, if you have it"
    Lab 09's `policies/usms-deploy-policy.json` scopes `iam:PassRole` to three role ARNs with `iam:PassedToService` naming `ec2.amazonaws.com` and `ecs-tasks.amazonaws.com`. The EKS work in Labs 07-08 uses the equivalent statement:

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

- `StartBuild` names **one project ARN**, not `project/*`.
- `s3:GetBucketVersioning` is there because CodePipeline checks that an S3 source is versioned, the machine-enforced half of Step 6.

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

`Default` is `v1` and `Attached` is `1`. Lab 12 creates `v2` of `USMSCodeBuildBase` and must set it as default explicitly.

---

### Step 16 - Write the pipeline definition

A pipeline is a JSON document. See [stages and actions](../unit5/topic2.md#stages-actions-and-the-parallelism-inside-a-stage).

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

- `actionTypeId` needs all four parts; `version` is the string `"1"`.
- Every `configuration` value is a string: `"PollForSourceChanges": "false"`. A JSON boolean is rejected with a structural message.
- Artifact names (`SourceOutput`, `BuildOutput`) are local to the pipeline, not S3 keys.

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

Unquoted heredoc for `${PIPELINE_ROLE_ARN}`; `grep -c '\$'` must print `0`. `PollForSourceChanges` is `"false"`: executions are started by hand, which keeps the causal chain visible (polling is deprecated in favour of EventBridge; Exercise 4).

**Expected result**

```text
pipeline template is valid JSON
0
```

> Example output.

---

### Step 17 - Create the pipeline

Turn the document into a pipeline and learn `get-pipeline-state`, the command you will use most.

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
    This first execution uses the project as configured now, with its own S3 source, which Step 18 changes. Let it run and note what it does; Step 19's execution is the one you rely on.

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

Source reaching `Succeeded` proves the bucket is versioned, the object exists at the key, and the pipeline role can read it.

!!! note "Floci Limitation - pipeline execution state may not advance"
    Some builds store pipelines and never execute them; `get-pipeline-state` then shows no `latestExecution`.

    On real AWS an execution starts within seconds and every transition appears in `list-pipeline-executions`.

    If stage states are empty you are on Path B or C: record the document, produce the artifact with Step 14's runner, and say so. Every exercise and assessment item works on all three paths.

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

The project currently has its own S3 source **and** receives the pipeline's input artifact: two sources, one build. Setting `source.type` to `CODEPIPELINE` makes the Build stage unambiguously build the Source stage's output, at the cost that `start-build --project-name usms-enrolment-build` stops working. `--source-type-override` and `--source-location-override` are the one-off escape hatch.

```bash
aws codebuild update-project \
  --name usms-enrolment-build \
  --source type=CODEPIPELINE,buildspec=buildspec.yml \
  --artifacts type=CODEPIPELINE \
  --query 'project.{Source:source.type,Artifacts:artifacts.type}' \
  --output table
```

`update-project` replaces only the members you name; the buildspec path is kept because it is still found at the artifact root.

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

An error is the expected result (`InvalidInputException` on real AWS; wording differs on Floci). If it succeeds, note it in Section 11's "recorded, not observed" list.

The one-off override, for reproducing a pipeline build by hand:

```bash
aws codebuild start-build \
  --project-name usms-enrolment-build \
  --source-type-override S3 \
  --source-location-override usms-pipeline-artifacts/source/usms-enrolment-src.zip \
  --query 'build.id' --output text
```

A build ID. If your build rejects the override flags, record it and move on.

---

### Step 19 - Run the pipeline end to end, and prove it consumed your source

Create, perturb, read back: change `VERSION` to `r4`, upload a new source version, run the pipeline, and look inside the output artifact. A green pipeline is not evidence; the artifact's contents are.

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

Two versions, one `Latest`: the old source is still retrievable, which makes "deploy the previous release" possible without a rebuild.

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

`sort_by(Contents, &LastModified)[-1].Key` sorts by modification time and takes the last (newest) key, on both operating systems.

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

In order of importance:

1. **`release` is `r4`**: the pipeline consumed the source you just uploaded.
2. **`buildId` is not `local`**: the artifact came from CodeBuild. `local` is a legitimate Path B or C result, reported as such.
3. **The artifact root is the files**, with no `dist/` prefix; Lab 12 depends on it.
4. **`srcVersion` matches `$NEW_VERSION_ID`**, if your build sets `CODEBUILD_RESOLVED_SOURCE_VERSION`: an unbroken chain from the changed byte to the artifact.

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

Hint: `list-object-versions` and `list-objects-v2 --prefix usms-enrolment-pipeline/BuildOutput/` give the two counts.

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

Learn to read a failure you broke deliberately, where you already know the answer.

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

One word in one JSON file: `pre_build` greps for `"container": "enrolment-api"` and exits 1. The grep depends on `json.dump(indent=2)` formatting; Exercise 3 replaces it with a parse.

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

The failure is in **Build**, so the source was fetched. Work inward, stage to build to phase to command:

```bash
LAST_BUILD=$(aws codebuild list-builds-for-project --project-name usms-enrolment-build \
  --sort-order DESCENDING --query 'ids[0]' --output text 2>/dev/null)

aws codebuild batch-get-builds --ids "$LAST_BUILD" \
  --query 'builds[0].phases[?phaseStatus==`FAILED`].{Phase:phaseType,Status:phaseStatus,Context:contexts[0].message}' \
  --output table
```

One row, `Phase` `PRE_BUILD`; `contexts[0].message` names the failing command. That chain is the whole diagnostic method.

!!! note "Floci Limitation - `list-builds-for-project` and `contexts`"
    Some builds lack `list-builds-for-project`, and many leave `contexts` empty.

    On real AWS both are reliable, and `contexts[0].message` is the fastest route to the command.

    Otherwise reproduce the failure with Step 14's runner, which prints the failing command directly.

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

`local build passes again` **before** you repackage: validate locally, then push.

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

Write the names, ARNs and IDs Lab 12 needs to `configs/lab-11.env`.

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

!!! warning "Unquoted heredoc"
    `<< EOF` so every `$(...)` runs now; the file on disk contains no command substitutions. The opposite of Step 8's `<< 'BUILDSPEC'` and Step 9's `<< 'EOF'`, with no error message if you get it backwards.

`| grep -E '...' || echo not-created` (Lab 06's pattern) records `not-created` on Path B or C instead of an ambiguous `None`.

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

`versioning=Enabled`, `stages=2` on Path A, and `release=r5` if you did Step 19's "Your turn". `versioning=Unknown` means Step 5 did not take effect.

**Command - commit**

```bash
git status --short
```

**No file under `outputs/` and no `.env` other than `configs/lab-11.env` may appear.** If one does, fix `.gitignore` rather than committing carefully.

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

## 8. Verification

The environment block comes first: a script that only checks its own resources passes until the restart that deletes them.

### 8.1 Build `scripts/utilities/verify-lab-11.sh`

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

Known benign failures:

| Failure | Benign when | What it means |
| --- | --- | --- |
| The four CodeBuild checks | Step 3 reported Path B or C | The service is absent. Your documents are still correct and validated |
| The four CodePipeline checks | Step 3 reported Path B or C | Same |
| `source has at least two versions` | You skipped the Step 19 "Your turn" | Upload the source once more; do not edit the check |
| `project source type is CODEPIPELINE` | You have not run Step 18 yet | **Not benign** after Step 18. Re-run `update-project` |
| `no secret is tracked` | Never | **Not benign.** Something under `outputs/` is in the index. Fix `.gitignore`, then `git rm --cached` it |
| `versioning is Enabled` | Never | **Not benign.** The pipeline depends on it. Return to Step 5 |

### 8.2 Build the end-of-course cleanup script

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

---

## 9. Checkpoints

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

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, CodeBuild cannot pull `aws/codebuild/standard:7.0`. Diagnose first, then use the alternative in [Known Issues - Lab 11](known-issues.md#lab-11-cicd-pipeline). It states what the alternative does and does not prove.

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

## 11. Floci vs Real AWS

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

Observed (on Path A): the source zip layout, the buildspec's four phases, the smoke tests passing and failing, an artifact naming your release, a `pre_build` failure, two versions at one key. Recorded but not enforced: the build role's scoping, the explicit `Deny`, the scoped `iam:PassRole`, the single project ARN. Not available: S3-triggered executions, approvals, build reports, KMS-encrypted artifacts. On Path B or C, move lines from observed to recorded in your report: "I wrote and validated a pipeline document" is worth more than an overstated "I built a pipeline".

**Where Floci is nicer than reality (traps on real AWS):** builds are instant and free (real builds bill per build-minute; `cache` exists for that); no concurrent-build quota; no IAM propagation delay (`create-role` then `create-project` is the classic "works the second time" failure); nothing is encrypted (real artifact stores use KMS, so the build role needs `kms:Decrypt`).

---

## 12. Independent Lab Exercises

Requirements and constraints are given; commands are not. Write answers and evidence in `labs/lab-11-cicd/exercises.md`.

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

## 13. Lab Assessment Checklist

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
- [ ] Section 14's questions answered in prose in `notes/lab-11-notes.md`

---

## 14. Review Questions

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

## 15. KEEP vs CLEAN UP

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

Do **not** run `scripts/cleanup/lab-11-cleanup.sh`; it is for the end of the course (Section 8.2).

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

## 16. Preparation for the Next Lab

Lab 12 (Deploying to ECS from the Pipeline) completes Practical 7 and carries its in-class assessment.

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

!!! warning "`update-pipeline` replaces the whole document"
    There is no "add a stage" operation: get, modify, put. Putting a document with only the new stage silently deletes today's two stages. `put-bucket-notification-configuration`, `update-assume-role-policy`, `put-bucket-policy` and `put-bucket-tagging` belong to the same replace-only family.

Before the next session:

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

Snapshot before you finish:

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

---

## Appendix - New CLI and JMESPath patterns

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

---

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

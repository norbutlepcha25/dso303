# Unit 5 Workshop: CI/CD Pipelines and Infrastructure as Code

**Duration:** 3 hours (180 minutes, including a 10-minute break)  
**Audience:** Students who have deployed containers on ECS and EKS (Units 2 and 3) and met microservices (Unit 4), but have not yet automated a release  
**Mode:** Workshop: short explanations, a defect-hunt on a real buildspec, a pipeline demonstration, a hands-on CloudFormation change set, ClassLegend quizzes  
**Running scenario:** The USMS enrolment service, deployed by hand on a Friday afternoon, breaks registration for the whole university

<div class="lesson-schedule"></div>

## Before class

!!! teacher "Purpose"
    Cover the whole of Unit 5 in one session: why CI/CD exists (5.1), how CodeBuild, CodeDeploy and CodePipeline turn a commit into running software (5.1 and 5.2), and how Infrastructure as Code makes the environment itself reviewable and repeatable (5.3). The thread that ties it together: **a pipeline moves one immutable artefact through environments and gathers evidence; IaC does the same for infrastructure, with the change set as the evidence.** Labs 11 and 12 are where students build the pipeline; this workshop gives them the model they need to understand what they are building.

**Learning outcomes.** By the end, students should be able to:

1. Distinguish continuous integration, continuous delivery and continuous deployment, and say which one a given team has.
2. Explain "build once, deploy many" and why a pipeline must never rebuild in a later stage.
3. Name the role of CodeCommit (or a Git provider), CodeBuild, CodeDeploy, CodePipeline and ECR in a release.
4. Read a `buildspec.yml` and identify its phases and at least three security or reproducibility defects.
5. Compare rolling, blue/green, canary and linear deployment by their rollback cost.
6. Explain why images are tagged with the commit SHA and deployed by digest.
7. Explain declarative IaC, state and drift, and contrast CloudFormation, CDK and Terraform.
8. Create a CloudFormation change set and identify a change that forces **replacement**.

**Environment checklist**

- [ ] Floci running under Compose (`./scripts/setup/floci-up.sh`), `whoami.sh` passes
- [ ] `floci services` (or a test call) confirms whether **CloudFormation** is supported on this Floci build
- [ ] Hands-on 2 template tested end to end: `deploy`, `create-change-set`, `describe-change-set` shows a `Replacement` column
- [ ] If Lab 11 is already built on the demonstration machine: `aws codepipeline get-pipeline-state --name usms-enrolment-pipeline` works
- [ ] Fallback ready for each hands-on (printed buildspec; screenshots of expected change-set output)

**Materials checklist**

- [ ] Defective buildspec (Hands-on 1) on the projector and shared with students
- [ ] Quiz 5A (CI/CD and deployment) and Quiz 5B (pipelines and IaC) loaded into ClassLegend
- [ ] Command reference at the end of this page
- [ ] Whiteboard space for the promotion pipeline diagram

**Security and cleanup**

- [ ] Floci only: no real AWS credentials, no `aws login`
- [ ] Students delete the `usms-iac-demo` stack at the end of Hands-on 2
- [ ] No quiz answers on this page

!!! warning "What Floci can and cannot show"
    CodeBuild and CodePipeline work on Floci with known issues (see the [Floci known issues](../Lab/known-issues.md) page: the `aws/codebuild/standard:7.0` image may not pull; the ECS deploy provider may be unavailable). **CodeDeploy is not provided at all**, so blue/green is taught conceptually, as in Lab 12 Step 19. CloudFormation support must be checked before class. Say this to students plainly: what they see working on Floci is the API shape, not proof of real AWS behaviour.

---

## Hook: the Friday deploy { data-minutes="10" }

[5.1 The problem: deployment was the risk](../unit5/topic1.md#the-problem-deployment-was-the-risk){ .notes-link target="_blank" }

!!! prompt "The Friday deploy"
    At 4:30 p.m. on Friday a developer SSHs into the enrolment server, runs `git pull`, `npm install` and restarts the service. It worked on their laptop. By 5:00 p.m. nobody can register for courses. The developer cannot remember exactly which commands they ran, the previous version is gone, and the server now has a different library version from the one tested on Monday.

    **What went wrong? List everything, not just the bug.**

**Discuss in pairs (3 minutes), then collect answers on the board.**

???+ answer "What to draw out"
    - The thing tested (on a laptop, on Monday) is not the thing deployed: `npm install` resolved different versions.
    - No record of what was run: no audit trail.
    - No quick way back: rollback means rebuilding the old version from memory.
    - Deployed straight to everyone at once: the blast radius was the whole university.
    - Deployed manually at the end of the week because deploying is scary, so changes pile up and get bigger.

!!! teacher "Teaching notes"
    Group the answers into four columns on the board and keep them for the rest of the session: **What we ship** (artefact), **How it gets there** (pipeline), **How it goes live** (deployment strategy), **What it runs on** (infrastructure). Each later segment fixes one column.

    **Transition:** "The fix is not to deploy less often. It is to make every deployment small, automatic, verified and reversible. First, the vocabulary."

## CI, CD and CD { data-minutes="10" }

[5.1 Continuous integration, delivery and deployment](../unit5/topic1.md#continuous-integration-delivery-and-deployment){ .notes-link target="_blank" }
[5.1 DORA metrics](../unit5/topic1.md#the-problem-deployment-was-the-risk){ .notes-link target="_blank" }

| Practice | What happens | What stands between merge and production |
|---|---|---|
| **Continuous integration** | Every merge to the mainline is built and tested automatically, at least daily | Everything after the build is still manual |
| **Continuous delivery** | Every passing change is *deployable* at any time | A person clicks **Approve** |
| **Continuous deployment** | Every passing change *is* deployed | Nothing: tests, health checks and automated rollback |

!!! prompt "The one-question test"
    "If a developer merged a one-line change right now, how long until it is serving production traffic, and what stands between?"

**DORA metrics, read as a set of four:** deployment frequency, lead time for changes, change failure rate, mean time to restore. Ask the class what each one rewards *on its own*.

???+ answer "Expected answers"
    - Frequency alone rewards recklessness; lead time alone rewards skipping tests.
    - Failure rate alone rewards never deploying; restore time alone rewards firefighting over prevention.
    - High performers score well on all four at once, because small, automated, reversible changes improve all of them.

!!! teacher "Stress"
    CI is a **practice** (merge daily, verify automatically), not a server. A team with a CI server and three-week feature branches does not have CI. Mention trunk-based development and feature flags in one sentence each; do not go deeper.

## Build once, deploy many { data-minutes="20" }

[5.1 Build once, deploy many](../unit5/topic1.md#build-once-deploy-many){ .notes-link target="_blank" }
[5.1 AWS CodeBuild](../unit5/topic1.md#aws-codebuild){ .notes-link target="_blank" }
[5.1 AWS CodeCommit](../unit5/topic1.md#aws-codecommit){ .notes-link target="_blank" }

Draw on the board:

```text
commit abc123 --> BUILD ONCE --> artefact (image sha256:9f2c...)
                                   |
                  +----------------+----------------+
                  v                v                v
             dev + dev config  staging + config  prod + prod config
```

**The rule:** the artefact is built exactly once and promoted unchanged. Only configuration differs between environments. If production rebuilds, **you have tested something you are not shipping**, which is exactly the Friday bug.

**Where the source lives.** CodeCommit is AWS's managed Git with IAM access control. It was closed to new customers in July 2024 and returned to general availability in November 2025; GitHub or GitLab connected through CodeConnections is the more common production choice. Either way, branch protection is an access control: if anyone can push to `main` and `main` deploys, everyone has production write access.

**CodeBuild in four facts:**

| Fact | Why it matters |
|---|---|
| A fresh container per build, destroyed afterwards | Nothing drifts between builds; reproducible by design |
| Instructions live in `buildspec.yml` in the repository | The build is versioned and reviewed like code |
| Phases: `install`, `pre_build`, `build`, `post_build` | `post_build` **runs even when `build` fails** |
| Runs as a **service role** | Every dependency the build downloads runs with that role's power |

Walk through the buildspec in the notes on screen, phase by phase. Point at three things: `npm ci` (honours the lockfile), `CODEBUILD_RESOLVED_SOURCE_VERSION` as the image tag (the full commit SHA), and `secrets-manager:` for secrets.

**Ask the class:**

1. Why tag an image with the commit SHA instead of `latest`?
2. Why should the build role not be able to deploy to production?

???+ answer "Expected answers"
    1. The SHA is unique, immutable and traceable to the exact source. `latest` is a pointer that moves; it tells you nothing about what is running.
    2. The build runs code from the repository and from hundreds of downloaded dependencies. If that role can deploy, anyone who can merge, or compromise one dependency, can deploy. Build identity and deploy identity must be separate.

!!! teacher "Transition"
    "We now have a trustworthy artefact. How do we put it live without breaking enrolment for everyone?"

## Deployment strategies and CodeDeploy { data-minutes="15" }

[5.1 Deployment strategies](../unit5/topic1.md#the-deployment-strategies-and-what-each-trades){ .notes-link target="_blank" }
[5.1 AWS CodeDeploy](../unit5/topic1.md#aws-codedeploy){ .notes-link target="_blank" }
[5.1 Feature flags](../unit5/topic1.md#feature-flags-and-the-separation-of-deploy-from-release){ .notes-link target="_blank" }

| Strategy | Mechanism | Rollback | Extra capacity |
|---|---|---|---|
| **Rolling (in place)** | Replace tasks in batches | Redeploy old version: slow | None |
| **Blue/green** | Run new beside old, switch traffic | Switch back: seconds | Double, during deploy |
| **Canary** | Shift e.g. 10%, wait, then the rest | Switch back: seconds | Double |
| **Linear** | Shift equal steps at intervals | Switch back: seconds | Double |
| **All at once** | Everything simultaneously | Redeploy: slow | None, dev only |

**Key point:** read the **rollback** column first. Canary and linear are traffic-shifting on top of blue/green: both versions run at once, which is why rollback is instant.

**CodeDeploy** orchestrates this for EC2, Lambda and ECS: an AppSpec file names what to deploy, lifecycle hooks run checks, a CloudWatch alarm can trigger automatic rollback. For ECS, native blue/green in the ECS service itself (since July 2025) is now an alternative to CodeDeploy.

!!! prompt "Mini discussion"
    The new enrolment release renames the `student_email` column to `email` in the same release as the code change. The team uses blue/green. Is rollback still safe?

???+ answer "Expected response"
    No. During and after the switch, the old version still expects `student_email`. Every strategy except all-at-once runs two versions against one database, so schema changes must be **expand and contract**: add the new column, write both, backfill, switch reads, and only drop the old column several releases later.

!!! teacher "Floci note"
    CodeDeploy is not available on Floci. Lab 12 Step 19 writes the blue/green AppSpec on paper. Mention it so students are not surprised.

## ClassLegend quiz 1 { data-minutes="10" }

!!! quiz "Run Quiz 5A in ClassLegend: CI/CD and deployment"
    Topics: CI versus continuous delivery versus continuous deployment; DORA metrics; build once, deploy many; buildspec phases and `post_build` behaviour; commit-SHA tagging; rolling versus blue/green versus canary; expand and contract.

    Students answer individually first, then discuss the two most-missed questions.

!!! teacher "Reviewing the quiz"
    Ask a student who chose a wrong option to explain why it looked right. The `post_build` question is usually the most missed; tie it straight into Hands-on 1.

## CodePipeline and ECR { data-minutes="20" }

[5.2 The pipeline as a promotion machine](../unit5/topic2.md#the-pipeline-as-a-promotion-machine){ .notes-link target="_blank" }
[5.2 Stages, actions and parallelism](../unit5/topic2.md#stages-actions-and-the-parallelism-inside-a-stage){ .notes-link target="_blank" }
[5.2 Artefacts and how data moves](../unit5/topic2.md#artefacts-and-how-data-moves){ .notes-link target="_blank" }
[5.2 Tag versus digest](../unit5/topic2.md#container-artefact-identity-tag-versus-digest){ .notes-link target="_blank" }

Build the USMS pipeline on the board, one stage at a time:

```text
Source         Build                 Deploy-staging        Approval     Deploy-prod
(Git commit) -> (CodeBuild:          -> (ECS rolling       -> (manual) -> (ECS blue/green,
                 test, image -> ECR,     update, then                     alarm rollback)
                 imagedefinitions.json)  integration tests)
```

| Idea | One-line explanation |
|---|---|
| **Stage** | A sequence point; the next stage waits for this one |
| **Action** | A unit of work in a stage; actions with the same `runOrder` run **in parallel** |
| **Artefact** | Files passed between actions through an S3 artefact store; no shared disk |
| **Variable** | A value (such as an image digest) passed to later actions, V2 pipelines only |
| **`imagedefinitions.json`** | The tiny file the ECS deploy action reads; the image itself stays in ECR |
| **ECR digest** | `repo@sha256:...` is a fact; `repo:stable` is a question asked every time a task starts |

Two rules to state as rules: **every stage must gather evidence or advance the artefact**, and **no stage may rebuild**.

**V2 pipeline features worth one sentence each:** stage conditions (for example "do not enter production while a CloudWatch alarm is firing"), automatic stage rollback, execution modes (`SUPERSEDED`, `QUEUED`, `PARALLEL`).

**Push versus pull.** CodePipeline *pushes* into the cluster and holds its credentials. GitOps (Argo CD) *pulls*: an agent in the cluster watches a Git repository, so no outside system holds cluster credentials and drift is corrected continuously. EKS now offers Argo CD as a managed capability.

**Ask the class:**

1. Three verification actions after the build take 4, 6 and 9 minutes. How long does the stage take if they share a `runOrder`? If each has its own?
2. Why does the pipeline pass `imagedefinitions.json` rather than the image?
3. Two executions in `PARALLEL` mode both deploy to staging. What can go wrong?

???+ answer "Expected answers"
    1. 9 minutes in parallel; 19 minutes in sequence.
    2. The image is large and already lives in ECR. Passing a reference is fast and keeps one copy of the artefact.
    3. A race: two different artefacts deploy to the same target and whichever finishes last wins. `PARALLEL` is for executions that target different environments.

!!! teacher "Demonstration (if Lab 11 is built on your machine)"
    Show the real pipeline from Lab 11 while you talk. If it is not built, show the stage diagram from the notes instead and move on.

    ```bash
    cd ~/aws-floci-course
    source configs/course.env && source configs/lab-11.env

    aws codepipeline get-pipeline --name "$USMS_PIPELINE_NAME" \
      --query 'pipeline.stages[].{Stage:name,Actions:join(`, `, actions[].name)}' \
      --output table

    aws codepipeline get-pipeline-state --name "$USMS_PIPELINE_NAME" \
      --query 'stageStates[].{Stage:stageName,Status:latestExecution.status}' \
      --output table
    ```

    Point out the artefact bucket `usms-pipeline-artifacts` and that its versioning is on: the Source stage depends on it.

## Break { data-minutes="10" .break }

!!! prompt "Break: 10 minutes"
    Come back with a terminal open in `~/aws-floci-course`, and Floci running.

## Hands-on 1: buildspec defect hunt { data-minutes="25" }

[5.1 Build reproducibility and the supply chain](../unit5/topic1.md#build-reproducibility-and-the-supply-chain){ .notes-link target="_blank" }
[5.1 AWS CodeBuild](../unit5/topic1.md#aws-codebuild){ .notes-link target="_blank" }

!!! prompt "Task (pairs, 15 minutes)"
    This buildspec was committed by the developer from the Friday deploy. It runs and the build goes green. Find **at least six defects**. For each one, write: the line, what can go wrong, and the fix.

```yaml
version: 0.2

env:
  variables:
    NODE_ENV: production
    DB_PASSWORD: Usms-Enrol-2026!
    REGISTRY: 000000000000.dkr.ecr.us-east-1.amazonaws.com

phases:
  install:
    commands:
      - npm install
  pre_build:
    commands:
      - aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
  build:
    commands:
      - npm test || true
      - docker build -t "$REGISTRY/usms-enrolment:latest" .
  post_build:
    commands:
      - docker push "$REGISTRY/usms-enrolment:latest"
      - aws ecs update-service --cluster usms-cluster --service usms-enrolment-svc --force-new-deployment

artifacts:
  files:
    - '**/*'
```

Hint for slower pairs: look at secrets, dependencies, tests, tags, what runs after a failure, and who deploys.

???+ answer "Defects to find (discussion answers, not graded)"
    | Line | Problem | Fix |
    |---|---|---|
    | `DB_PASSWORD: ...` | Plaintext secret: in Git history forever, in the project config and build logs | `secrets-manager:` or `parameter-store:` reference |
    | `npm install` | Resolves versions afresh; the Friday bug | `npm ci` with a committed lockfile |
    | `npm test` (with the `true` fallback) | Test failures are ignored; the build is green whatever happens | Let the test command fail the build |
    | `:latest` | Not traceable, not immutable | Tag with `$CODEBUILD_RESOLVED_SOURCE_VERSION`; enable tag immutability in ECR |
    | `docker push` in `post_build` | Runs even when `build` failed, so a broken image is published | Guard with `$CODEBUILD_BUILD_SUCCEEDING`, or push at the end of `build` |
    | `update-service` in the build | The build role can deploy: build and deploy identities are merged, and there is no deploy stage, gate or rollback | Output `imagedefinitions.json`; let a pipeline Deploy stage with its own role deploy |
    | `artifacts: '**/*'` | Ships the whole workspace, including `node_modules` and anything sensitive | Emit only what the next stage needs |
    | No runtime pinning | The build image's default Node version can change | `runtime-versions:` in `install`, or a pinned build image |

**Whole-class debrief (10 minutes).** Go round the pairs, one defect each, until the table is complete. For each, ask which column from the hook (artefact, pipeline, deployment, infrastructure) it belongs to.

!!! teacher "Teaching notes"
    The `update-service` line is the most important and the least spotted. It is also the exact mistake Lab 12 avoids by adding a separate Deploy stage with its own policy. If time remains, have students rewrite the buildspec correctly and compare with the version in the 5.1 notes.

**Success criteria**

- [ ] Every pair found at least six defects
- [ ] Every pair can explain why `post_build` is dangerous
- [ ] Every pair can say why the build role must not deploy

## Infrastructure as Code { data-minutes="20" }

[5.3 Declarative and imperative](../unit5/topic3.md#declarative-and-imperative-idempotency-and-convergence){ .notes-link target="_blank" }
[5.3 State](../unit5/topic3.md#state-and-why-it-is-the-deepest-difference-between-the-tools){ .notes-link target="_blank" }
[5.3 Drift](../unit5/topic3.md#drift){ .notes-link target="_blank" }
[5.3 The lifecycle of a change](../unit5/topic3.md#the-lifecycle-of-a-change){ .notes-link target="_blank" }

!!! prompt "Back to the hook"
    Labs 1 to 10 built USMS with hundreds of CLI commands. Suppose the university wants an identical staging environment by Monday. How confident are you that you could rebuild it exactly?

**Imperative versus declarative.** The labs were imperative: "create a VPC, then a subnet, then...". IaC is declarative: "there is a VPC with this CIDR, containing these subnets". The engine compares **desired state** with **actual state**, computes the difference, and applies it in dependency order.

!!! teacher "The one loop, three times"
    Draw it: desired state, observed state, difference, act. Ask which other tool in this module works the same way. Students should name the Kubernetes controller (Unit 3) and Argo CD (5.2). This is the most transferable idea in the module.

| Tool | What it is | Where state lives |
|---|---|---|
| **CloudFormation** | AWS's native declarative engine; templates create **stacks** | Inside AWS: nothing to host, nothing to repair by hand |
| **AWS CDK** | Code (TypeScript, Python...) that **generates CloudFormation** | In CloudFormation: CDK is CloudFormation underneath |
| **Terraform / OpenTofu** | Independent engine, any provider | A **state file** you host and protect; it can contain secrets |

**Drift:** someone changes a security group in the console. The template now lies. The next deploy may revert it, and rollback may fail. Drift detection only reports it; the real defence is that humans have **read-only** access to production and only the pipeline's role can change it.

**The step teams skip:** reviewing the **plan** (change set, `terraform plan`), not just the code. A one-word change can mean **replace the database**, which is data loss. `DeletionPolicy` and `UpdateReplacePolicy` set to `Retain` or `Snapshot` on every stateful resource are the safety net.

**Ask the class:**

1. Why is "CDK or CloudFormation?" the wrong question, and "CloudFormation or Terraform?" a real one?
2. Why is the Terraform state file a secret?
3. Should the VPC and the enrolment service be in one stack?

???+ answer "Expected answers"
    1. CDK produces CloudFormation; every CloudFormation concept applies to it. Terraform is a different engine with a different state model.
    2. It records resource attributes, including generated passwords, even ones never written in the configuration.
    3. No. Split by lifecycle and blast radius: the network changes rarely and is high-risk; the service changes daily. One stack means every routine release risks touching the network.

## Hands-on 2: a change set that replaces { data-minutes="15" }

[5.3 AWS CloudFormation](../unit5/topic3.md#aws-cloudformation){ .notes-link target="_blank" }
[5.3 The lifecycle of a change](../unit5/topic3.md#the-lifecycle-of-a-change){ .notes-link target="_blank" }

!!! prompt "Predict first"
    We will make two changes to a stack: change a **tag**, and change the **bucket name**. Which one do you think AWS can do in place, and which needs the bucket destroyed and recreated?

**Step 1: Write the template** (from `~/aws-floci-course`)

```bash
cd ~/aws-floci-course
mkdir -p templates

cat > templates/usms-iac-demo.yaml << 'EOF'
AWSTemplateFormatVersion: '2010-09-09'
Description: USMS IaC workshop demo - one tagged S3 bucket

Parameters:
  BucketSuffix:
    Type: String
  Owner:
    Type: String

Resources:
  ExportsBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'usms-iac-demo-${BucketSuffix}'
      Tags:
        - Key: Project
          Value: USMS
        - Key: Owner
          Value: !Ref Owner

Outputs:
  BucketName:
    Value: !Ref ExportsBucket
EOF
```

- `<< 'EOF'` is quoted so the shell leaves `${BucketSuffix}` alone for CloudFormation to resolve. An unquoted `<< EOF` would silently replace it with an empty string.

**Step 2: Validate and deploy**

```bash
aws cloudformation validate-template --template-body file://templates/usms-iac-demo.yaml

aws cloudformation deploy \
  --stack-name usms-iac-demo \
  --template-file templates/usms-iac-demo.yaml \
  --parameter-overrides BucketSuffix=a Owner=registry

aws cloudformation describe-stacks --stack-name usms-iac-demo \
  --query 'Stacks[0].{Status:StackStatus,Bucket:Outputs[0].OutputValue}' --output table
```

Success: `Status` is `CREATE_COMPLETE` and the bucket is `usms-iac-demo-a`.

**Step 3: Change set A, change only the tag**

```bash
aws cloudformation create-change-set \
  --stack-name usms-iac-demo --change-set-name owner-change \
  --use-previous-template \
  --parameters ParameterKey=BucketSuffix,UsePreviousValue=true \
               ParameterKey=Owner,ParameterValue=exams

aws cloudformation wait change-set-create-complete \
  --stack-name usms-iac-demo --change-set-name owner-change

aws cloudformation describe-change-set \
  --stack-name usms-iac-demo --change-set-name owner-change \
  --query 'Changes[].ResourceChange.{Action:Action,Resource:LogicalResourceId,Replacement:Replacement}' \
  --output table
```

**Step 4: Change set B, change the bucket name**

```bash
aws cloudformation create-change-set \
  --stack-name usms-iac-demo --change-set-name rename \
  --use-previous-template \
  --parameters ParameterKey=BucketSuffix,ParameterValue=b \
               ParameterKey=Owner,UsePreviousValue=true

aws cloudformation wait change-set-create-complete \
  --stack-name usms-iac-demo --change-set-name rename

aws cloudformation describe-change-set \
  --stack-name usms-iac-demo --change-set-name rename \
  --query 'Changes[].ResourceChange.{Action:Action,Resource:LogicalResourceId,Replacement:Replacement}' \
  --output table
```

???+ answer "Expected result"
    | Change set | Action | Resource | Replacement |
    |---|---|---|---|
    | `owner-change` | `Modify` | `ExportsBucket` | `False` |
    | `rename` | `Modify` | `ExportsBucket` | `True` |

    The rename destroys the old bucket and creates a new one. Here it is empty; if it held student exports, the data would be gone. **Neither change set has been executed**: reviewing the plan is the point.

!!! prompt "Discuss (2 minutes)"
    Which two lines would you add to the template so that a replacement could never lose data?

???+ answer "Expected answer"
    `DeletionPolicy: Retain` (or `Snapshot` for databases) and `UpdateReplacePolicy: Retain` on the resource.

!!! danger "Read before running any delete command"
    **What will be deleted:** the `usms-iac-demo` stack and the empty bucket `usms-iac-demo-a`.  
    **What depends on it:** nothing; it was created only for this exercise.  
    **Reversible?** Yes, redeploy the template.  
    **Effect on later labs:** none.

```bash
aws cloudformation delete-stack --stack-name usms-iac-demo
aws cloudformation wait stack-delete-complete --stack-name usms-iac-demo
```

!!! teacher "Fallback if CloudFormation is unsupported on this Floci build"
    Run it as a prediction exercise: students read the template, predict both change sets, then you show the expected table above as a screenshot. Label it clearly as instructor-provided output. If change sets work but the `Replacement` column comes back empty, say so: that is a Floci limitation, and on real AWS this column is the one to read.

**Success criteria**

- [ ] Stack reached `CREATE_COMPLETE`
- [ ] Two change sets described, not executed
- [ ] Student can say which change replaces and why it matters
- [ ] Stack deleted

## ClassLegend quiz 2 { data-minutes="10" }

!!! quiz "Run Quiz 5B in ClassLegend: pipelines and Infrastructure as Code"
    Topics: stages versus actions and `runOrder`; artefacts and `imagedefinitions.json`; tag versus digest; execution modes; push versus pull deployment; declarative versus imperative; CloudFormation, CDK and Terraform state; drift; change sets and replacement; `DeletionPolicy` and `UpdateReplacePolicy`.

!!! teacher "Reviewing the quiz"
    If the state or drift questions are weak, redraw the reconciliation loop before the design game.

## Design game { data-minutes="10" }

[5.2 Push versus pull deployment](../unit5/topic2.md#push-versus-pull-deployment){ .notes-link target="_blank" }
[5.1 Deployment strategies](../unit5/topic1.md#the-deployment-strategies-and-what-each-trades){ .notes-link target="_blank" }
[5.3 Terraform and OpenTofu](../unit5/topic3.md#terraform-and-opentofu){ .notes-link target="_blank" }

Small teams, two minutes per scenario: choose and justify in one sentence.

!!! prompt "Scenario A: exam results release"
    The results service is used heavily for two days a year. A bad release on results day is unacceptable. Which deployment strategy?

!!! prompt "Scenario B: twelve EKS clusters"
    USMS grows to twelve EKS clusters across three Regions. The security team does not want any pipeline to hold credentials for all twelve. Push or pull?

!!! prompt "Scenario C: AWS plus GitHub plus a monitoring vendor"
    The platform team wants one tool to manage AWS resources, GitHub repositories and Datadog dashboards. CloudFormation, CDK or Terraform?

!!! prompt "Scenario D: auditors"
    The university's auditors require that every change to production is approved by a named person. Continuous delivery or continuous deployment?

???+ answer "Suggested answers"
    - **A:** Blue/green with canary shifting and alarm-based rollback; rollback in seconds is worth double capacity for a short time. Avoid deploying on results day at all (a stage condition with a deployment window).
    - **B:** Pull (GitOps, for example Argo CD). Each cluster pulls its own state; no external system holds cluster credentials.
    - **C:** Terraform or OpenTofu: one engine with providers for all three. CloudFormation and CDK are AWS-focused.
    - **D:** Continuous delivery with a manual approval action, provided the approver has real information (test results, change set) and can genuinely refuse.

## Exit ticket { data-minutes="5" }

!!! prompt "Answer individually"
    1. What is the difference between continuous delivery and continuous deployment?
    2. Why must a pipeline never rebuild the artefact for production?
    3. Name one buildspec defect you found and its fix.
    4. What does `Replacement: True` in a change set mean, and why does it matter?
    5. What is one thing about Unit 5 you still need to understand better?

!!! teacher "Next steps for students"
    Labs 11 and 12 build the pipeline from this session on Floci: a versioned artefact bucket, CodeBuild, a two-stage pipeline, then ECR and an ECS deploy stage. Students who finish early can start Lab 11 Step 1.

---

## Command reference

| Command | Purpose |
|---|---|
| `aws codepipeline get-pipeline --name <name>` | Show a pipeline's stages and actions |
| `aws codepipeline get-pipeline-state --name <name>` | Latest status of each stage |
| `aws codepipeline start-pipeline-execution --name <name>` | Run the pipeline now |
| `aws codebuild batch-get-projects --names <project>` | Show a build project's configuration |
| `aws codebuild list-builds-for-project --project-name <project>` | Recent builds for a project |
| `aws cloudformation validate-template --template-body file://<file>` | Check template syntax |
| `aws cloudformation deploy --stack-name <s> --template-file <f> --parameter-overrides K=V` | Create or update a stack |
| `aws cloudformation create-change-set ... --use-previous-template` | Plan a change without applying it |
| `aws cloudformation wait change-set-create-complete ...` | Wait until the change set is ready |
| `aws cloudformation describe-change-set ...` | Read the plan, including `Replacement` |
| `aws cloudformation describe-stacks --stack-name <s>` | Stack status and outputs |
| `aws cloudformation delete-stack --stack-name <s>` | Delete a stack and its resources |

!!! teacher "Final teaching advice"
    Students should leave able to say, in their own words: the artefact is built once and promoted unchanged; a pipeline's value is what it verifies and what it can undo, not that a machine types the commands; the build role must not be the deploy role; blue/green buys fast rollback with temporary double capacity; IaC is a reconciliation loop with state; and the change set, not the code diff, tells you what will really happen. Depth on V2 conditions, multi-account promotion and CDK constructs belongs in the notes and the labs.

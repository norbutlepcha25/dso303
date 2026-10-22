# Unit 5: Practice Questions

## 5.1 AWS CI/CD Services: CodeCommit, CodeBuild and CodeDeploy

### Beginner Questions

1. Define continuous integration, continuous delivery and continuous deployment, and state one additional capability each requires beyond the previous one.

    ??? success "Check your answer"

        A good answer covers:

        - **Continuous integration:** every developer merges to the mainline at least daily and every merge is built and tested automatically; it requires a fast, trustworthy test suite and short-lived branches (trunk-based development).
        - **Continuous delivery:** every change that passes the pipeline is deployable to production at any time, so release becomes a business decision; it additionally requires automated deployment, environment parity and reversible changes (backward-compatible schema migrations).
        - **Continuous deployment:** every passing change is deployed to production with no human gate; it additionally requires tests that genuinely gate quality, progressive delivery and automated rollback driven by a user-facing signal.
        - **Cumulative progression:** each practice includes everything the previous one requires; the step from delivery to deployment is as much organisational as technical.
        - **Legitimate stopping point:** stopping at continuous delivery with an approval is defensible, provided the approver has the information to refuse.

2. Explain why an artefact should be tagged with a commit SHA and deployed by digest rather than by a tag such as `latest` or `v1.2`.

    ??? success "Check your answer"

        A good answer covers:

        - **Traceability:** the full commit SHA (`CODEBUILD_RESOLVED_SOURCE_VERSION`) identifies exactly which source produced the artefact; `latest` or `v1.2` says nothing reliable about the source.
        - **Mutability:** a tag is a movable pointer, so a task definition referencing a tag is a query re-evaluated every time a task launches, and the result can change after deployment.
        - **Digest is content:** the `sha256:` digest is derived from the image manifest, so a deployment by digest runs byte-identical content in every environment and on every scaling event.
        - **Build once, deploy many:** what was verified in staging is provably what runs in production, and rollback to a previous digest is exact.
        - **Enforcement:** ECR tag immutability turns the convention into a property the registry enforces.

3. List the CodeDeploy lifecycle hooks for an EC2 in-place deployment in order, identify which are reserved for CodeDeploy, and state which hook is where health validation belongs.

    ??? success "Check your answer"

        A good answer covers:

        - **Order:** `ApplicationStop`, `DownloadBundle`, `BeforeInstall`, `Install`, `AfterInstall`, `ApplicationStart`, `ValidateService` (with a load balancer, block-traffic events precede and allow-traffic events follow this sequence).
        - **Reserved events:** `DownloadBundle` and `Install` are run by CodeDeploy itself and cannot have scripts attached (likewise `BlockTraffic` and `AllowTraffic`).
        - **Health validation:** belongs in `ValidateService`, which decides whether the deployment on that instance succeeded.
        - **Notable behaviour:** `ApplicationStop` runs from the previously deployed revision, so a broken stop script blocks later deployments.

4. Explain what `post_build` does when the `build` phase has failed, and write the guard that prevents a failed build from publishing an artefact.

    ??? success "Check your answer"

        A good answer covers:

        - **Behaviour:** `post_build` runs even when the `build` phase has failed, so an unguarded `docker push` there publishes an image from a failed build.
        - **Consequence:** "the image in ECR" no longer means "a build that passed", and a later pipeline stage may deploy it.
        - **Guard:** check the variable CodeBuild sets, for example `if [ "$CODEBUILD_BUILD_SUCCEEDING" = "1" ]; then docker push "$IMAGE"; else echo "build failed, not pushing"; exit 1; fi`.
        - **Alternative:** move the push into the `build` phase after the tests, so a failing test command stops the phase before the push runs.

5. Describe the difference between an in-place and a blue/green deployment, and state what each costs and what each buys.

    ??? success "Check your answer"

        A good answer covers:

        - **In-place (rolling):** replaces instances or tasks in batches on the existing capacity; no extra cost, but rollback means redeploying the previous version, which is slow.
        - **Blue/green:** stands up a complete new environment, shifts traffic to it and keeps the old one; rollback is shifting traffic back, measured in seconds.
        - **Cost:** blue/green needs double capacity for the duration of the deployment; in-place needs none.
        - **What blue/green buys:** fast rollback and the chance to test green before users reach it; the expensive resource is the duration of a bad change, not compute.
        - **Shared requirement:** both run two versions at once against the same database, so versions N and N+1 must be compatible (expand and contract).

### Intermediate Questions

1. A CodeBuild project stores a database password as a plaintext environment variable. List four distinct places that value is now exposed, and describe the correct configuration.

    ??? success "Check your answer"

        A good answer covers:

        - **Project configuration:** visible to anyone who can view the project in the console or call `BatchGetProjects`.
        - **API calls and audit records:** the value travels in `StartBuild` overrides and project-definition API calls, which CloudTrail records.
        - **Build logs:** any command that prints the environment, or verbose tool output, writes it to CloudWatch Logs.
        - **Source and every dependency:** it sits in whatever IaC or script defines the project, and every package executing in the build can read it from the environment.
        - **Correct configuration:** store it in Secrets Manager, reference it in the buildspec `env: secrets-manager:` block, grant the build role read on that one secret only, and rotate the exposed password now; better still, question why a build needs a production database password at all.

2. Explain why `npm ci` is used in a pipeline rather than `npm install`, and give two other changes that improve build reproducibility. For each, describe the specific failure it prevents.

    ??? success "Check your answer"

        A good answer covers:

        - **`npm ci`:** installs exactly what the committed lockfile specifies and fails if `package.json` and the lockfile disagree; `npm install` may resolve newer versions and rewrite the lockfile, so two builds of one commit can differ.
        - **Pin the base image by digest (`FROM node:20@sha256:...`):** prevents a silently updated base image from changing the runtime or OS packages between builds.
        - **Pin toolchain and build image versions:** prevents "it built yesterday" failures caused by a changed build environment.
        - **Control the package source (CodeArtifact or scoped registries with an explicit upstream order):** prevents dependency confusion, where a public package impersonates an internal one.
        - **Build once and promote by digest:** prevents staging and production running different builds of the same commit.

3. A team runs a canary deployment with a CloudWatch alarm on the ECS service's overall error rate at a 5 per cent threshold, with a one-minute bake and a five-minute alarm evaluation window. Identify the two independent defects and explain what each would allow to reach production.

    ??? success "Check your answer"

        A good answer covers:

        - **Defect 1, diluted signal:** the alarm watches the whole service, but only 10 per cent of traffic reaches the canary; a canary failing 30 per cent of requests raises the overall rate to about 3 per cent, below the threshold, so partial failures pass. Alarm on the green target group instead.
        - **Defect 2, timing:** a one-minute bake with a five-minute evaluation window means the alarm cannot reach ALARM before all traffic has shifted; the canary step provides no protection.
        - **What reaches production:** under defect 1, partially broken releases; under defect 2, any broken release, detected only after full exposure.
        - **Correction:** bake time longer than the alarm's evaluation window plus metric delay, on a metric users feel (error rate or latency of the new version).

4. Compare deploying an ECS service with the ECS rolling update, ECS native blue/green, and CodeDeploy blue/green. State when you would choose each and what you give up.

    ??? success "Check your answer"

        A good answer covers:

        - **ECS rolling update:** replaces tasks in batches within `minimumHealthyPercent`/`maximumPercent`, with the circuit breaker for automatic rollback; simplest and needs no extra capacity, but rollback is another rolling deployment and there is no pre-traffic test.
        - **ECS native blue/green (since July 2025, with linear and canary since October 2025):** traffic shifting, lifecycle hooks and bake-time monitoring inside the ECS service itself, with no CodeDeploy application or deployment group; usually the simpler choice for new ECS-only workloads.
        - **CodeDeploy blue/green:** AppSpec, test listener, canary and linear configurations and alarm rollback; choose it for one deployment model across EC2, Lambda and ECS or an existing CodePipeline integration.
        - **What you give up:** blue/green (either kind) costs double capacity during deployment; CodeDeploy adds a second system to configure and operate.

5. Design the IAM structure for a pipeline where a compromised npm dependency must not be able to deploy to production. Specify what each role may and may not do, and explain what an account boundary adds.

    ??? success "Check your answer"

        A good answer covers:

        - **Build role:** read source, push to one ECR repository, write to the artefact bucket, read named parameters; no ECS, CloudFormation or IAM permissions, and it cannot assume any deploy role.
        - **Pipeline role:** orchestrates stages and may assume per-stage roles; it does not itself hold deployment permissions to production.
        - **Production deploy role:** in the production account, trusted only by the pipeline role; may register task definitions and update named services, with `iam:PassRole` limited to the task role; cannot modify IAM or push images.
        - **Artefact integrity:** deploy only by digest, ideally with signature verification, so the deploy stage cannot be handed an arbitrary image.
        - **Account boundary:** with production in a separate account, the build role's credentials have no identity there at all; only explicit cross-account trust (role, bucket and KMS key policies) grants access, and SCPs bound even administrators.

### Advanced Questions

1. A team deploys monthly. Each release is a six-hour window with 20 people, and the last three releases each caused a production incident. Leadership has concluded that they should deploy less often and test more. Write the case against that conclusion, grounded in batch size and the DORA metrics, then design the twelve-month transition: what must change, in what order, why that order, and what evidence you would collect at each step to justify continuing.

    ??? success "Check your answer"

        A good answer covers:

        - **The case against:** deploying less often increases batch size; more changes per release raises the probability of failure, makes the cause harder to find and makes rollback harder, so the proposal worsens the problem.
        - **DORA evidence:** the five metrics (deployment frequency, change lead time, failed deployment recovery time, change fail rate, deployment rework rate) tend to move together; teams that deploy more often also fail less and recover faster, so throughput and stability are not a trade-off.
        - **Order of change:** measure the baseline; automate build and deployment (build once, IaC) so a release is not a 20-person event; establish fast rollback (blue/green) and backward-compatible migrations; then trunk-based development and feature flags; then raise frequency in steps (monthly, weekly, daily) with canaries and alarms.
        - **Why that order:** safety before speed; increasing frequency before rollback and automation exist would multiply the existing risk and toil.
        - **Evidence per step:** deployment duration and people involved, rollback drill times, change fail rate, deployment rework rate, failed deployment recovery time and change lead time, with agreed criteria for continuing or pausing.

2. Design the complete delivery architecture for a regulated financial-services platform with twelve microservices, a requirement that no individual can both author and deploy a change, an auditor who must be able to prove what was running at any past moment, and a regulatory obligation to patch critical vulnerabilities within 48 hours. Cover source control, build, artefact custody and provenance, deployment strategy, identity separation, audit, and the break-glass path. State explicitly which of the auditor's questions your design can answer instantly and which require investigation.

    ??? success "Check your answer"

        A good answer covers:

        - **Source and separation of duties:** protected mainline requiring approval by someone other than the author; only the pipeline's role can deploy; humans have no production write access; production in its own account.
        - **Build, custody and provenance:** least-privilege CodeBuild per service, SBOM per build, Inspector enhanced scanning, signing (AWS Signer), immutable ECR tags by commit SHA, promotion by digest.
        - **Deployment:** per-service pipelines from one shared definition, blue/green with canary and alarm-driven rollback, production entry condition on alarms.
        - **Audit:** organisation CloudTrail to a log-archive account with object lock, exported pipeline execution records linking commit, approver and digest, AWS Config history; retention matching regulation.
        - **48-hour patching:** continuous rescanning, automated base-image rebuilds through the same pipeline, and a measured lead time well below 48 hours; break-glass is a time-bounded, two-person, alarmed role followed by review and reconciliation into Git.
        - **Auditor questions:** instantly answerable are which digest ran when, from which commit, approved by whom; requiring investigation are runtime configuration at a past moment, actions taken under break-glass, and whether a known vulnerability was exploitable.

3. A monorepo of twenty services builds everything on every commit, taking 55 minutes. Developers now merge once a week. Design the remediation covering change detection, artefact identity, caching, compute selection, pipeline structure and the failure modes your change detection introduces. Explain how you would detect that change detection has gone wrong, given that its failure is silent.

    ??? success "Check your answer"

        A good answer covers:

        - **Change detection:** path-filtered triggers per service, driven by a dependency graph (from the build tool) so a shared-library change rebuilds every dependant.
        - **Artefact identity:** each image tagged with the monorepo commit SHA; unchanged services keep their previous digest; promotion by digest.
        - **Caching and compute:** dependency cache keyed on the lockfile, Docker layer caching, a build tool with remote cache; parallel batch builds, ARM compute, Lambda compute for lint and unit tests, reserved fleets only if queueing dominates.
        - **Pipeline structure:** one pipeline per service generated from a shared definition, with verification actions in parallel.
        - **Failure mode:** an incorrect dependency graph leaves a service unrebuilt and running stale shared code, silently.
        - **Detecting it:** a periodic full build compared against what change detection chose, recording input hashes per image, and alerting when a deployed image's inputs differ from the current source.

4. Critique the following pipeline: "Every push to any branch triggers a build. The build runs `docker build` and pushes to ECR with the tag `latest`. A second CodeBuild project runs the tests. Deployment uses `aws ecs update-service --force-new-deployment` from a shell script in the build, with `AdministratorAccess` on the build role. Database migrations run as the first step of the new container's startup. We deploy to production twice a day, so we are doing continuous deployment." Identify at least eight distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected design, and describe how you would verify each correction.

    ??? success "Check your answer"

        A good answer covers:

        - **Most severe and least reversible:** `AdministratorAccess` on the build role (any dependency can do anything in the account); migrations at container start (concurrent, irreversible schema changes run by every task, making rollback impossible).
        - **Artefact defects:** mutable `latest` tag (no traceability, undefined rollback); every branch pushes `latest`, so a feature branch can overwrite what production pulls; image pushed and deployed before the separate test project runs.
        - **Deployment defects:** deployment from inside the build (no separation of build and deploy identity); `--force-new-deployment` rolling update with no health gate, canary or alarm rollback; no staging promotion, scanning or review gate.
        - **Mislabelling:** twice-daily deployment is not continuous deployment, which means every passing change deploys automatically with gates that make that safe.
        - **Corrected design:** main-only triggers after reviewed merge; tests before push; SHA tags with immutability; separate least-privilege build and deploy roles; pipeline deploys by digest with blue/green and alarm rollback; migrations as a separate expand-and-contract step.
        - **Verification:** attempt a deployment with the build role and confirm denial; push to an existing tag and confirm rejection; push a feature branch and confirm production is untouched; commit a failing test and confirm no image appears; run a rollback drill and time it.

5. Your organisation wants continuous deployment with no human approval gate, but the compliance team requires evidence that every production change was reviewed and that a bad change can be reverted within five minutes. Design a system satisfying both. Address what replaces the approval gate as evidence of review, how you would demonstrate the five-minute revert claim rather than assert it, what happens when the pipeline itself is unavailable during an incident, and what you would say to the compliance team about the failure modes that remain.

    ??? success "Check your answer"

        A good answer covers:

        - **Evidence of review:** required pull-request approval by a non-author before merge, with the pipeline deploying only reviewed mainline commits; each deployment record links digest, commit, pull request and approver.
        - **Replacing the human gate:** automated tests, scanning, policy checks, canary with user-facing alarms and stage conditions provide the evidence an approver would otherwise sign.
        - **Demonstrating the five-minute revert:** blue/green or traffic shifting with the previous version retained, proven by scheduled rollback drills and by measuring the duration of real automatic rollbacks, not by assertion.
        - **Pipeline unavailable:** rollback must not depend on the pipeline: traffic shift back or stop the deployment in ECS or CodeDeploy, disable a feature flag, or use a documented, alarmed break-glass role.
        - **Remaining failure modes to disclose:** irreversible data changes cannot be reverted in five minutes; failures invisible to alarms; rubber-stamp reviews; and a compromised reviewer account.

---

## 5.2 CI/CD Pipelines with CodePipeline and Amazon ECR

### Beginner Questions

1. Define pipeline, stage, action, artefact and execution, and explain what `runOrder` controls.

    ??? success "Check your answer"

        A good answer covers:

        - **Pipeline:** the workflow model that moves a change from source to production.
        - **Stage:** a sequential grouping of actions (for example Build, Deploy-Staging) that acts as a sequence point.
        - **Action:** a task within a stage: source, build, test, deploy, approval or invoke.
        - **Artefact:** files passed between actions, stored in the encrypted S3 artefact store; execution is one run of the pipeline for a change.
        - **`runOrder`:** orders actions within a stage; actions with the same value run in parallel, and a higher value waits for all lower ones to finish.

2. Explain the difference between an image tag and an image digest, and state why a task definition should reference the digest.

    ??? success "Check your answer"

        A good answer covers:

        - **Tag:** a mutable, human-readable label that can be moved to a different image.
        - **Digest:** an immutable `sha256:` value derived from the image manifest content.
        - **Why the digest:** a task definition referencing a tag is re-resolved whenever a task launches, so what runs can change after deployment; a digest fixes exactly what runs, making rollback and audit exact.
        - **In practice:** tag with the commit SHA for traceability, deploy by digest for correctness.

3. List the three VPC endpoints required for a pod in a private subnet to pull an image from ECR, and state which failure symptom indicates that the third is missing.

    ??? success "Check your answer"

        A good answer covers:

        - **`com.amazonaws.<region>.ecr.api`:** interface endpoint for authentication and the ECR API.
        - **`com.amazonaws.<region>.ecr.dkr`:** interface endpoint for the Docker registry protocol.
        - **S3 gateway endpoint:** image layers are served from S3.
        - **Symptom of the missing third:** authentication and manifest retrieval succeed, then the layer download times out, which looks like a networking hang rather than a permissions error.

4. Describe what a stage entry condition does and give one example that requires no custom code.

    ??? success "Check your answer"

        A good answer covers:

        - **What it does:** a V2 stage condition evaluated before the stage begins; its rules decide whether the stage proceeds or fails.
        - **Example:** an alarm rule on the production stage that blocks entry while the production service's CloudWatch alarm is in ALARM, so no deployment lands in the middle of an incident.
        - **Another example:** a deployment-window rule allowing entry only during agreed hours.
        - **No custom code:** both are built-in rule types configured on the stage, replacing bespoke Lambda gates.

5. Explain what `Synced` and `Healthy` mean in Argo CD, and describe a situation in which an application is `Synced` but not `Healthy`.

    ??? success "Check your answer"

        A good answer covers:

        - **Synced:** the live resources in the cluster match the desired state in Git at the target revision.
        - **Healthy:** the resources are functioning according to their health checks (for example, the Deployment has rolled out and pods are ready).
        - **Independent:** sync describes configuration, health describes behaviour.
        - **Synced but not Healthy:** the manifest with a new image digest was applied, but the new pods crash-loop, fail readiness probes or cannot pull the image, so the application is `Degraded` while matching Git exactly.

### Intermediate Questions

1. A pipeline has a build action followed by three verification actions, all sequential, taking 4, 6, 5 and 7 minutes. Calculate the duration before and after setting the verification actions to the same `runOrder`, and explain why this is a reliability improvement rather than merely a convenience.

    ??? success "Check your answer"

        A good answer covers:

        - **Before:** 4 + 6 + 5 + 7 = 22 minutes.
        - **After:** 4 + max(6, 5, 7) = 11 minutes.
        - **Reliability, not convenience:** shorter lead time keeps changes small and discourages batching, which lowers change failure rate.
        - **Incident benefit:** a fix or revert travelling through the pipeline reaches production in half the time, reducing time to restore.
        - **Feedback:** all verification failures are reported together, rather than one at a time across repeated runs.

2. Explain the three permission surfaces involved in a cross-account CodePipeline deployment, describe the symptom when each is missing, and state which one produces a misleading error message.

    ??? success "Check your answer"

        A good answer covers:

        - **Cross-account role:** a role in the target account trusting the pipeline's role; missing gives an `AssumeRole` access-denied on the action.
        - **Artefact bucket policy:** must grant the target role read access; missing gives an S3 access-denied when reading the artefact.
        - **KMS key policy:** must grant the target role `kms:Decrypt` on the artefact key (a customer-managed key, since the AWS-managed S3 key cannot be shared across accounts); missing also surfaces as an S3 access-denied.
        - **The misleading one:** the KMS key policy, because the error points at S3 rather than at the key.

3. Compare the CodePipeline EKS deploy action with GitOps using Argo CD. State three properties GitOps provides that the push action does not, and two genuine costs it introduces.

    ??? success "Check your answer"

        A good answer covers:

        - **Drift correction:** Argo CD continuously compares declared and live state and can correct drift; a push action knows only what it last applied.
        - **No external cluster credentials:** the cluster pulls outbound from Git and the registry, so the pipeline holds no cluster access and leaves the cluster's threat model.
        - **Git as the record:** the manifest repository is the deployment history, and rollback is `git revert`; each cluster also pulls its own state independently.
        - **Cost 1:** another system to operate and secure (reduced, but not removed, by the managed EKS Capability for Argo CD) and a manifest repository with write-back automation.
        - **Cost 2:** pipeline success no longer means deployment success, so health must be reported back; `selfHeal` also reverts emergency manual fixes, changing incident procedure.

4. An ECR lifecycle policy expires images older than 30 days. Describe the failure this can cause, explain why the service appears healthy until it occurs, and propose a policy that avoids it while still bounding storage.

    ??? success "Check your answer"

        A good answer covers:

        - **Failure:** an age-based rule expires an image still referenced by a live task definition belonging to a service not redeployed for 30 days.
        - **Why it looks healthy:** running tasks do not re-pull, so the problem stays hidden until a scale-out, task replacement, Availability Zone failure or rollback needs to pull the image, then fails with `CannotPullContainerError` at the worst moment.
        - **Better policy:** retain tagged release images by count (for example the most recent N per service), expire untagged images after a short period, and protect images marked as deployed or still referenced.
        - **Supporting check:** compare candidates for expiry against active task definitions before relying on the rule; storage stays bounded by count rather than age.

5. Design the trigger configuration and pipeline structure for a monorepo of eight services where a typical commit touches one. Explain what breaks if a shared library changes and how you would handle it.

    ??? success "Check your answer"

        A good answer covers:

        - **Structure:** one V2 pipeline per service, generated from a shared definition so all eight are consistent.
        - **Triggers:** branch filter on `main` and a file-path filter such as `services/orders/**`, so a typical commit runs one pipeline.
        - **Shared library problem:** a change under a shared path that no service's filter includes triggers nothing, and services keep running old shared code silently.
        - **Handling it:** include the shared paths in every dependant's filter, or derive filters from the build tool's dependency graph; accept that a shared change rebuilds all dependants.
        - **Safety net:** a periodic full build and images tagged with the monorepo commit SHA, so what each service is running can be compared against source.

### Advanced Questions

1. Design the complete delivery architecture for an organisation running twenty microservices across ECS and EKS, in three accounts and two Regions, with a requirement that no individual can both author and deploy a change. Specify what is unified across the two orchestrators and what is deliberately different, justify each asymmetry, and describe how you would present deployment history as one coherent view despite two different mechanisms.

    ??? success "Check your answer"

        A good answer covers:

        - **Accounts and Regions:** a tooling account holding pipelines and ECR; separate development, staging and production accounts; the second Region deploys after the first has baked, with ECR replication.
        - **Unified:** source and review rules, one pipeline shape from a shared construct, artefact standards (SHA tags, immutability, scanning, signing, promotion by digest), per-stage roles and separation of duties.
        - **Deliberately different:** ECS uses a push (CodePipeline driving blue/green with alarm rollback) because ECS has no in-cluster agent; EKS uses pull (Argo CD) for reconciliation, drift correction and no cluster credentials in the pipeline.
        - **Separation of duties:** non-author approval on the source and manifest repositories, deploy roles usable only by the pipeline, manifest writes only by the pipeline identity.
        - **One history view:** emit deployment events from both mechanisms (pipeline and ECS events, Argo CD notifications) to EventBridge and a central store keyed by service, environment, commit and digest, with deployment markers on dashboards.

2. A team migrating forty services from push-based EKS deployment to GitOps expects a two-week project. Write the realistic plan, including what you expect the first read-only Argo CD sync to reveal, how you would handle secrets, what you would do about the drift inventory, and how the break-glass procedure must change once `selfHeal` is enabled. State explicitly what could make the migration fail.

    ??? success "Check your answer"

        A good answer covers:

        - **Realistic scope:** months, not two weeks; start with one non-critical service in a non-production cluster, with Argo CD in read-only mode (no automated sync).
        - **Expected first sync:** substantial drift: manual `kubectl` changes, replica counts owned by autoscalers, defaulted fields, hand-made resources and secrets absent from Git.
        - **Secrets:** never in Git as plaintext; use External Secrets Operator with Secrets Manager, or encrypted secrets (Sealed Secrets, SOPS).
        - **Drift inventory:** every difference gets an owner and a decision, adopt into Git or revert, before automated sync and prune are enabled; configure `ignoreDifferences` for fields controllers own.
        - **Break-glass:** with `selfHeal`, manual fixes are reverted within minutes, so emergency changes become fast-path Git commits or an explicit, alarmed suspension of auto-sync followed by reconciliation.
        - **What could make it fail:** prune deleting unmanaged resources, old push pipelines still writing in parallel, self-heal fighting autoscalers or operators, and teams not trained in the new incident procedure.

3. Critique the following pipeline: "One pipeline for all twelve services, V1 type, triggered on every push to any branch. The build stage builds all twelve images and tags them `latest`. Each deploy stage runs `kubectl apply -f manifests/` from CodeBuild using a role with `cluster-admin`, and reports success when `kubectl` exits zero. ECR has no lifecycle policy and tags are mutable. There is one pipeline service role. Production is in the same account as development." Identify at least nine distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected architecture, and describe how you would verify each correction.

    ??? success "Check your answer"

        A good answer covers:

        - **Most severe:** production in the same account as development; `cluster-admin` credentials in CodeBuild; one shared pipeline service role (no per-stage least privilege).
        - **Artefact defects:** all images tagged `latest`, mutable tags, no lifecycle policy (unbounded growth, no defined rollback target).
        - **Pipeline defects:** one pipeline for twelve services (one failure blocks all), builds all twelve on every push, triggers on every branch (feature branches reach production), V1 type (no trigger filters, stage conditions or rollback).
        - **False success:** a zero exit from `kubectl apply` means the API server accepted the manifest, not that the rollout is healthy.
        - **Corrected architecture:** per-service V2 pipelines from a shared construct, `main`-only path-filtered triggers, SHA tags with immutability and digest promotion, lifecycle rules protecting deployed images, separate accounts, per-stage roles, namespace-scoped access entries or GitOps, success defined by rollout health.
        - **Verification:** confirm development credentials cannot reach production; confirm an existing tag cannot be overwritten; push a feature branch and see no deployment; deploy a deliberately broken image and see the pipeline fail.

4. An auditor asks your organisation to demonstrate, for a specific date eighteen months ago, exactly which container image was serving production traffic, what vulnerabilities were known to be present in it at that time, who approved its release, and what configuration it was running with. Design the artefact custody and record-keeping architecture that makes each of these answerable, state which are answerable instantly and which require investigation, and identify the weakest link in your own design.

    ??? success "Check your answer"

        A good answer covers:

        - **Which image:** deployments by digest; CloudTrail (organisation trail in a log-archive account with object lock, since event history covers only 90 days) and exported pipeline execution records (CodePipeline history is retained for 12 months); for EKS, the manifest repository's Git history.
        - **Vulnerabilities known at the time:** Inspector shows current findings, so findings must be exported and retained with timestamps; the stored SBOM supports later analysis but not "known at the time".
        - **Who approved:** pull-request approvals and manual approval actions, exported and retained beyond the Git provider's and service's default retention.
        - **Configuration:** immutable task definition revisions, AWS Config history and versioned parameters, retained for the required period; images themselves protected from lifecycle expiry or archived.
        - **Instant versus investigation:** digest, commit and approver are instant if records were retained; vulnerability state and full runtime configuration require reconstruction.
        - **Weakest link:** configuration and secrets changed outside IaC, and break-glass actions, which leave the thinnest record.

5. Your organisation wants a single delivery platform used by thirty teams. Design the governance model: what is centrally defined and enforced, what teams control, how a team onboards a new service, how a change to the shared pipeline definition is rolled out safely across thirty consumers, and what you would do when a team's requirements genuinely do not fit the standard. Address the failure mode where a central platform becomes a bottleneck that teams route around.

    ??? success "Check your answer"

        A good answer covers:

        - **Central and enforced:** a versioned shared pipeline construct; mandatory controls (review, scanning, signing, per-stage roles, account separation, SCPs, policy as code) enforced as guardrails rather than by convention.
        - **Team-controlled:** service code, tests, deployment parameters (canary size, alarms, schedule) within the guardrails.
        - **Onboarding:** self-service creation of repository, ECR repository, pipeline and roles from a template, in minutes rather than by ticket.
        - **Rolling out shared changes:** semantic versioning, a pilot group first, then waves, backward compatibility, monitoring of pipeline failure rates and a way to pin or roll back the version.
        - **Exceptions:** documented extension points and time-bound, reviewed waivers; recurring needs are absorbed into the platform rather than forked.
        - **Avoiding the bottleneck:** run the platform as a product with measured lead time and adoption; enforce outcomes (controls) rather than tooling, so the paved road is the easiest path rather than a gate to route around.

---

## 5.3 Infrastructure as Code

### Beginner Questions

1. Define declarative provisioning, idempotency and convergence, and explain why the last two are what make automation safe.

    ??? success "Check your answer"

        A good answer covers:

        - **Declarative provisioning:** you describe the desired end state; the engine compares it with actual state, computes the difference and orders the work.
        - **Idempotency:** applying the same definition repeatedly produces the same result rather than duplicates.
        - **Convergence:** the engine moves from whatever state exists towards the declared one.
        - **Why they make automation safe:** a failed run can simply be re-run and a partial apply completed rather than untangled, without anyone working out the current state by hand.

2. Explain the difference between `DeletionPolicy` and `UpdateReplacePolicy`, and give an example of a change where only the second protects you.

    ??? success "Check your answer"

        A good answer covers:

        - **`DeletionPolicy`:** applies when a resource is removed from the template or the stack is deleted (`Retain`, `Snapshot`, `Delete`).
        - **`UpdateReplacePolicy`:** applies when an update forces replacement, governing what happens to the old physical resource.
        - **Example:** changing an RDS `DBInstanceIdentifier` forces replacement; `DeletionPolicy` does not apply, and only `UpdateReplacePolicy: Snapshot` (or `Retain`) preserves the data.
        - **Practice:** set both on every stateful resource; they cost nothing.

3. State what a CloudFormation change set shows that a code diff does not, and name the specific field to look for.

    ??? success "Check your answer"

        A good answer covers:

        - **What it shows:** the effect on existing resources (add, modify, remove), which depends on current state and property semantics, not just the text change.
        - **The field:** `Replacement`, with values `True`, `False` or `Conditional`; `True` means the resource will be deleted and recreated.
        - **Why it matters:** a one-word diff can appear in the change set as replacement of a database, which for stateful resources means data loss.
        - **Recent addition:** drift-aware change sets (November 2025) also compare against live state, so the preview shows drifted properties the deployment would change.

4. Explain what drift is, how CloudFormation and Terraform each surface it, and why neither prevents it.

    ??? success "Check your answer"

        A good answer covers:

        - **Drift:** divergence between declared and actual state caused by changes outside the tool (console edits, CLI calls, remediation, other tools).
        - **CloudFormation:** drift detection run on demand per stack or resource reports differences without correcting them; drift-aware change sets (November 2025) surface drift in the deployment preview.
        - **Terraform:** `terraform plan` refreshes actual state before diffing, so drift appears as unexpected changes.
        - **Why neither prevents it:** both detect after the fact; prevention is IAM, with humans read-only in production, only the pipeline role able to write, and an alarmed break-glass path.

5. Describe the relationship between AWS CDK and CloudFormation, and state one consequence of that relationship for a team adopting CDK.

    ??? success "Check your answer"

        A good answer covers:

        - **Relationship:** CDK code is executed by `cdk synth` to produce CloudFormation templates and assets; `cdk deploy` hands them to CloudFormation, which does the provisioning.
        - **Consequence: same engine:** every CloudFormation quota, stack state, rollback behaviour and stuck state (such as `UPDATE_ROLLBACK_FAILED`) applies, so the team must still understand CloudFormation.
        - **Consequence: review the output:** synthesis is code execution, so a bug yields a wrong template rather than an error; `cdk diff` must be reviewed, and a library upgrade is an infrastructure change.
        - **Consequence: bootstrapping:** each account and Region needs the CDKToolkit stack before deployment.

### Intermediate Questions

1. A stack is in `UPDATE_ROLLBACK_FAILED` and contains a production database. Describe the recovery procedure, what `ResourcesToSkip` costs you, and the three changes you would make afterwards to prevent recurrence.

    ??? success "Check your answer"

        A good answer covers:

        - **First:** confirm the application is still serving traffic, then read stack events for why the rollback failed (resource changed or deleted outside CloudFormation, missing permissions, a custom resource that never signalled, a quota).
        - **Preferred recovery:** fix the underlying cause, then `ContinueUpdateRollback`; make no further manual changes.
        - **`ResourcesToSkip`:** CloudFormation marks skipped resources as rolled back without changing them, so its model no longer matches reality for those resources, and you own the reconciliation (drift detection, template update or import).
        - **Prevention 1:** move the database into its own stack with `DeletionPolicy`, `UpdateReplacePolicy`, a stack policy and termination protection.
        - **Prevention 2:** remove human write access to production, the usual cause of the failed rollback.
        - **Prevention 3:** mandatory change-set review for `Replacement` plus policy-as-code checks, and custom resources that always signal.

2. Compare CloudFormation's automatic rollback with Terraform's behaviour on a failed apply. State what each buys, what each costs, and which you would prefer for a stateful workload.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudFormation:** rolls back automatically to the last known good state; buys a consistent stack with no half-applied change; costs slow rollbacks and the possibility that the rollback itself fails (`UPDATE_ROLLBACK_FAILED`).
        - **Terraform:** no rollback; it stops, records what was applied in state and leaves you to fix and re-apply (roll forward); buys transparency and control; costs an intermediate state until someone acts.
        - **Stateful workloads:** a justified preference either way is acceptable, for example roll-forward control to avoid an automatic rollback acting on a database, or CloudFormation's rollback for consistency.
        - **Key point:** neither protects data by itself; that is the job of `DeletionPolicy`/`UpdateReplacePolicy` or `prevent_destroy`, and of reading the plan for replacements.

3. Design the stack or module boundaries for a platform with a shared VPC, two clusters, eight services and per-service databases. Justify each boundary by lifecycle or blast radius, and explain why databases belong in their own unit.

    ??? success "Check your answer"

        A good answer covers:

        - **Foundation, per account:** VPC, subnets, endpoints, DNS; rarely changes and every change has the largest blast radius.
        - **Cluster, one per cluster:** control plane, node groups, add-ons; independent upgrade lifecycle, and a failure affects one cluster only.
        - **Shared services:** ECR, shared load balancers, observability.
        - **Application, one per service (eight):** changes constantly and is owned by the service team.
        - **Database, one per service (eight), separate from the application:** a different, slow lifecycle and long-lived data; separation means an application change or rollback cannot produce a change set touching the database, and protections (deletion and replacement policies, stack policy, termination protection) apply cleanly.
        - **Coupling:** prefer Parameter Store lookups to CloudFormation exports, which block changes to exported values.

4. Explain why a Terraform state file must be treated as a secret store. Describe what it contains, what `sensitive = true` does and does not do, and the specific protections the backend needs.

    ??? success "Check your answer"

        A good answer covers:

        - **Contents:** every managed resource's attributes: IDs, ARNs, endpoints, and secrets such as generated passwords, private keys and access keys, in plaintext.
        - **`sensitive = true`:** redacts the value from plan and output displays, but the value is still stored in state.
        - **Backend protections:** S3 with KMS encryption, a bucket policy restricting access to the pipeline role, public access blocked, versioning for recovery, native locking (`use_lockfile = true`), and access logging.
        - **Isolation:** separate state per environment and account, so one compromise does not expose everything.
        - **Reduce what enters state:** let Secrets Manager or RDS-managed master passwords generate secrets rather than Terraform.

5. Write the policy-as-code rules you would enforce in an infrastructure pipeline, and for each one state the specific incident it prevents.

    ??? success "Check your answer"

        A good answer covers:

        - **No wildcard IAM (`Action: "*"` or `Resource: "*"`):** prevents a merge granting administrator-level access.
        - **IAM roles must carry the permission boundary:** prevents privilege escalation through newly created roles.
        - **S3 buckets block public access and are encrypted:** prevents public data exposure.
        - **No ingress from `0.0.0.0/0` on administrative or database ports:** prevents exposed SSH, RDP or database endpoints.
        - **Stateful resources carry deletion and replacement protection:** prevents data loss from a deletion or forced replacement.
        - **Mandatory ownership and cost tags, encryption on databases and volumes:** prevents orphaned, unaccountable or unencrypted resources; enforced with `cfn-guard`, `cdk-nag`, Checkov or OPA in the pipeline, and Hooks where prevention is required.

### Advanced Questions

1. An organisation has 40 accounts, 200 engineers, no IaC in production, and an auditor arriving in six months who will ask what existed on any given past date and who authorised it. Design the twelve-month programme: the sequence, what you do first and why, what you expect to discover, how you measure progress, and what you would tell the auditor about the period before the programme started.

    ??? success "Check your answer"

        A good answer covers:

        - **First, start the evidence:** an organisation CloudTrail trail and AWS Config in every account into a log-archive account with object lock, because evidence cannot be created retrospectively.
        - **Sequence:** guardrails (SCPs, landing zone); foundation baselines through StackSets; import the existing estate, highest-risk first (IaC generator, `cdk migrate`, imports); pipeline-only deployment; then remove human write access with an alarmed break-glass path.
        - **Expected discoveries:** resources nobody owns, undocumented console changes, over-permissive IAM, inconsistencies between accounts, and fixes that break when drift is reverted.
        - **Measuring progress:** managed resources as a proportion of the Config inventory per account, share of changes made through the pipeline, drift count, and human write events in CloudTrail.
        - **Message to the auditor:** from the programme's start, Git, change sets and CloudTrail evidence every change; before it, only whatever CloudTrail and Config retained exists, and that gap is stated rather than reconstructed.

2. Design the complete guardrail architecture preventing a merge to the infrastructure repository from escalating a developer to account administrator. Cover review, policy as code, permission boundaries, service control policies, account separation and detection. For each layer, state what it catches that the others do not, and identify the one layer whose removal would be most damaging.

    ??? success "Check your answer"

        A good answer covers:

        - **Review:** non-author approval catches intent and context, but depends on attention.
        - **Policy as code:** automatically and uniformly catches known-bad patterns (wildcards, missing boundary) that a reviewer missed.
        - **Permission boundary:** the deploy role can create roles only with the boundary attached, capping their power even if a policy passes the checks.
        - **SCPs:** deny changing or removing the boundary, disabling CloudTrail or leaving the organisation; they bind even account administrators.
        - **Account separation and detection:** developer credentials cannot reach production; CloudTrail alarms on `CreateRole`, `AttachRolePolicy` and `PutRolePolicy` and IAM Access Analyzer catch whatever got through, including break-glass use.
        - **Most damaging removal:** the permission boundary with its SCP protection is a strong answer, as the only layer that bounds what the deploy role can grant; any choice must be argued.

3. Critique the following setup: "All infrastructure is in one CloudFormation template of 2,800 lines, applied by an engineer from their laptop with administrator credentials. Database passwords are template parameters with `NoEcho`. There is no `DeletionPolicy` because we are careful. Drift detection was run once last year. Staging and production use the same template with different parameter values, applied at different times. Terraform is used for the monitoring vendor's configuration, with state in a shared S3 bucket without versioning and with no locking." Identify at least nine distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected architecture, and describe how you would verify each correction.

    ??? success "Check your answer"

        A good answer covers:

        - **Most severe and irreversible:** no `DeletionPolicy`/`UpdateReplacePolicy` (data loss on deletion or replacement); Terraform state without versioning (unrecoverable loss) and without locking (concurrent corruption); laptop applies with administrator credentials (no pipeline, no audit trail, credential theft risk, guaranteed drift).
        - **Secrets:** `NoEcho` parameters are still supplied by people and handled outside a secret store; the vendor state in a shared bucket holds plaintext secrets.
        - **Structure:** a 2,800-line single template means every change carries the blast radius of everything and cannot be reviewed.
        - **Process:** drift detection once a year; staging and production applied manually at different times, so no evidence production received what staging tested; no change-set review or policy as code.
        - **Corrected architecture:** layered stacks by lifecycle; pipeline-applied with a deploy role and change-set approval; deletion and replacement policies; dynamic references to Secrets Manager; Terraform state in a versioned, KMS-encrypted, access-restricted bucket with `use_lockfile`; human read-only access.
        - **Verification:** delete a test stack and confirm the snapshot; confirm CloudTrail shows only the pipeline role writing; run two applies and observe the lock; restore a prior state version; confirm a policy rule fails a template missing `DeletionPolicy`.

4. Your organisation standardised on CDK three years ago. A new regulatory requirement demands that infrastructure configuration be reviewable by non-engineers who cannot read TypeScript. Design a response that satisfies the requirement without abandoning CDK, and state honestly what the requirement is really asking for and whether your response meets it or works around it.

    ??? success "Check your answer"

        A good answer covers:

        - **What is really asked:** a reviewable, understandable record of what infrastructure exists and what each change does, which is about effects, not source language.
        - **Response:** review the synthesised output: attach `cdk diff` and change-set summaries (added, modified, replaced) in plain language to each change; archive the synthesised templates per release.
        - **Controls as statements:** express compliance rules (`cdk-nag`, `cfn-guard`, Config conformance packs) as named, plain-language rules with reports non-engineers can check.
        - **Supporting views:** generated architecture diagrams and resource inventories from the deployed state.
        - **Honesty:** if the requirement literally means reading the configuration source, generated summaries are a workaround; state that, and agree with the regulator whether reviewing effects satisfies the intent.

5. Argue both sides of the following proposition, then state your own position and the evidence that would change it: "An organisation running entirely on AWS should use CDK rather than Terraform, and the multi-cloud argument for Terraform is almost always hypothetical." Address abstraction, state management, licensing and governance, team skills, hiring, and the cost of being wrong in either direction.

    ??? success "Check your answer"

        A good answer covers:

        - **For CDK:** real language abstraction and L2 `grant*` methods, no state file to host (CloudFormation holds state), automatic rollback, an AWS-native support path; strong if the team already writes TypeScript or Python.
        - **For Terraform:** providers for non-AWS vendors (monitoring, Git hosting, DNS) matter even in an AWS-only estate; the plan as a saved artefact; state repair tools; a large hiring pool and a widely known declarative language.
        - **Licensing and governance:** Terraform is under the BSL 1.1 since August 2023 with direction set by IBM; OpenTofu is MPL 2.0 under the CNCF as a hedge; CDK is AWS-governed, which ties you to CloudFormation.
        - **Cost of being wrong:** choosing CDK and later needing another cloud means rewriting IaC (alongside much else); choosing Terraform when AWS-only means carrying state responsibility and fewer abstractions; both migrations are expensive.
        - **Own position:** a clearly argued position, for example CDK for AWS resources with Terraform or OpenTofu for genuine non-AWS vendors, stating the evidence that would change it (a funded second-cloud workload, team skills, the proportion of non-AWS resources).

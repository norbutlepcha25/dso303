# Unit 5: Practice Questions

## 5.1 AWS CI/CD Services: CodeCommit, CodeBuild and CodeDeploy

### Beginner Questions

1. Define continuous integration, continuous delivery and continuous deployment, and state one additional capability each requires beyond the previous one.
2. Explain why an artefact should be tagged with a commit SHA and deployed by digest rather than by a tag such as `latest` or `v1.2`.
3. List the CodeDeploy lifecycle hooks for an EC2 in-place deployment in order, identify which are reserved for CodeDeploy, and state which hook is where health validation belongs.
4. Explain what `post_build` does when the `build` phase has failed, and write the guard that prevents a failed build from publishing an artefact.
5. Describe the difference between an in-place and a blue/green deployment, and state what each costs and what each buys.

### Intermediate Questions

1. A CodeBuild project stores a database password as a plaintext environment variable. List four distinct places that value is now exposed, and describe the correct configuration.
2. Explain why `npm ci` is used in a pipeline rather than `npm install`, and give two other changes that improve build reproducibility. For each, describe the specific failure it prevents.
3. A team runs a canary deployment with a CloudWatch alarm on the ECS service's overall error rate at a 5 per cent threshold, with a one-minute bake and a five-minute alarm evaluation window. Identify the two independent defects and explain what each would allow to reach production.
4. Compare deploying an ECS service with the ECS rolling update, ECS native blue/green, and CodeDeploy blue/green. State when you would choose each and what you give up.
5. Design the IAM structure for a pipeline where a compromised npm dependency must not be able to deploy to production. Specify what each role may and may not do, and explain what an account boundary adds.

### Advanced Questions

1. A team deploys monthly. Each release is a six-hour window with 20 people, and the last three releases each caused a production incident. Leadership has concluded that they should deploy less often and test more. Write the case against that conclusion, grounded in batch size and the DORA metrics, then design the twelve-month transition: what must change, in what order, why that order, and what evidence you would collect at each step to justify continuing.
2. Design the complete delivery architecture for a regulated financial-services platform with twelve microservices, a requirement that no individual can both author and deploy a change, an auditor who must be able to prove what was running at any past moment, and a regulatory obligation to patch critical vulnerabilities within 48 hours. Cover source control, build, artefact custody and provenance, deployment strategy, identity separation, audit, and the break-glass path. State explicitly which of the auditor's questions your design can answer instantly and which require investigation.
3. A monorepo of twenty services builds everything on every commit, taking 55 minutes. Developers now merge once a week. Design the remediation covering change detection, artefact identity, caching, compute selection, pipeline structure and the failure modes your change detection introduces. Explain how you would detect that change detection has gone wrong, given that its failure is silent.
4. Critique the following pipeline: "Every push to any branch triggers a build. The build runs `docker build` and pushes to ECR with the tag `latest`. A second CodeBuild project runs the tests. Deployment uses `aws ecs update-service --force-new-deployment` from a shell script in the build, with `AdministratorAccess` on the build role. Database migrations run as the first step of the new container's startup. We deploy to production twice a day, so we are doing continuous deployment." Identify at least eight distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected design, and describe how you would verify each correction.
5. Your organisation wants continuous deployment with no human approval gate, but the compliance team requires evidence that every production change was reviewed and that a bad change can be reverted within five minutes. Design a system satisfying both. Address what replaces the approval gate as evidence of review, how you would demonstrate the five-minute revert claim rather than assert it, what happens when the pipeline itself is unavailable during an incident, and what you would say to the compliance team about the failure modes that remain.

---

## 5.2 CI/CD Pipelines with CodePipeline and Amazon ECR

### Beginner Questions

1. Define pipeline, stage, action, artefact and execution, and explain what `runOrder` controls.
2. Explain the difference between an image tag and an image digest, and state why a task definition should reference the digest.
3. List the three VPC endpoints required for a pod in a private subnet to pull an image from ECR, and state which failure symptom indicates that the third is missing.
4. Describe what a stage entry condition does and give one example that requires no custom code.
5. Explain what `Synced` and `Healthy` mean in Argo CD, and describe a situation in which an application is `Synced` but not `Healthy`.

### Intermediate Questions

1. A pipeline has a build action followed by three verification actions, all sequential, taking 4, 6, 5 and 7 minutes. Calculate the duration before and after setting the verification actions to the same `runOrder`, and explain why this is a reliability improvement rather than merely a convenience.
2. Explain the three permission surfaces involved in a cross-account CodePipeline deployment, describe the symptom when each is missing, and state which one produces a misleading error message.
3. Compare the CodePipeline EKS deploy action with GitOps using Argo CD. State three properties GitOps provides that the push action does not, and two genuine costs it introduces.
4. An ECR lifecycle policy expires images older than 30 days. Describe the failure this can cause, explain why the service appears healthy until it occurs, and propose a policy that avoids it while still bounding storage.
5. Design the trigger configuration and pipeline structure for a monorepo of eight services where a typical commit touches one. Explain what breaks if a shared library changes and how you would handle it.

### Advanced Questions

1. Design the complete delivery architecture for an organisation running twenty microservices across ECS and EKS, in three accounts and two Regions, with a requirement that no individual can both author and deploy a change. Specify what is unified across the two orchestrators and what is deliberately different, justify each asymmetry, and describe how you would present deployment history as one coherent view despite two different mechanisms.
2. A team migrating forty services from push-based EKS deployment to GitOps expects a two-week project. Write the realistic plan, including what you expect the first read-only Argo CD sync to reveal, how you would handle secrets, what you would do about the drift inventory, and how the break-glass procedure must change once `selfHeal` is enabled. State explicitly what could make the migration fail.
3. Critique the following pipeline: "One pipeline for all twelve services, V1 type, triggered on every push to any branch. The build stage builds all twelve images and tags them `latest`. Each deploy stage runs `kubectl apply -f manifests/` from CodeBuild using a role with `cluster-admin`, and reports success when `kubectl` exits zero. ECR has no lifecycle policy and tags are mutable. There is one pipeline service role. Production is in the same account as development." Identify at least nine distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected architecture, and describe how you would verify each correction.
4. An auditor asks your organisation to demonstrate, for a specific date eighteen months ago, exactly which container image was serving production traffic, what vulnerabilities were known to be present in it at that time, who approved its release, and what configuration it was running with. Design the artefact custody and record-keeping architecture that makes each of these answerable, state which are answerable instantly and which require investigation, and identify the weakest link in your own design.
5. Your organisation wants a single delivery platform used by thirty teams. Design the governance model: what is centrally defined and enforced, what teams control, how a team onboards a new service, how a change to the shared pipeline definition is rolled out safely across thirty consumers, and what you would do when a team's requirements genuinely do not fit the standard. Address the failure mode where a central platform becomes a bottleneck that teams route around.

---

## 5.3 Infrastructure as Code

### Beginner Questions

1. Define declarative provisioning, idempotency and convergence, and explain why the last two are what make automation safe.
2. Explain the difference between `DeletionPolicy` and `UpdateReplacePolicy`, and give an example of a change where only the second protects you.
3. State what a CloudFormation change set shows that a code diff does not, and name the specific field to look for.
4. Explain what drift is, how CloudFormation and Terraform each surface it, and why neither prevents it.
5. Describe the relationship between AWS CDK and CloudFormation, and state one consequence of that relationship for a team adopting CDK.

### Intermediate Questions

1. A stack is in `UPDATE_ROLLBACK_FAILED` and contains a production database. Describe the recovery procedure, what `ResourcesToSkip` costs you, and the three changes you would make afterwards to prevent recurrence.
2. Compare CloudFormation's automatic rollback with Terraform's behaviour on a failed apply. State what each buys, what each costs, and which you would prefer for a stateful workload.
3. Design the stack or module boundaries for a platform with a shared VPC, two clusters, eight services and per-service databases. Justify each boundary by lifecycle or blast radius, and explain why databases belong in their own unit.
4. Explain why a Terraform state file must be treated as a secret store. Describe what it contains, what `sensitive = true` does and does not do, and the specific protections the backend needs.
5. Write the policy-as-code rules you would enforce in an infrastructure pipeline, and for each one state the specific incident it prevents.

### Advanced Questions

1. An organisation has 40 accounts, 200 engineers, no IaC in production, and an auditor arriving in six months who will ask what existed on any given past date and who authorised it. Design the twelve-month programme: the sequence, what you do first and why, what you expect to discover, how you measure progress, and what you would tell the auditor about the period before the programme started.
2. Design the complete guardrail architecture preventing a merge to the infrastructure repository from escalating a developer to account administrator. Cover review, policy as code, permission boundaries, service control policies, account separation and detection. For each layer, state what it catches that the others do not, and identify the one layer whose removal would be most damaging.
3. Critique the following setup: "All infrastructure is in one CloudFormation template of 2,800 lines, applied by an engineer from their laptop with administrator credentials. Database passwords are template parameters with `NoEcho`. There is no `DeletionPolicy` because we are careful. Drift detection was run once last year. Staging and production use the same template with different parameter values, applied at different times. Terraform is used for the monitoring vendor's configuration, with state in a shared S3 bucket without versioning and with no locking." Identify at least nine distinct defects, rank them by the severity and reversibility of the damage each would cause, propose a corrected architecture, and describe how you would verify each correction.
4. Your organisation standardised on CDK three years ago. A new regulatory requirement demands that infrastructure configuration be reviewable by non-engineers who cannot read TypeScript. Design a response that satisfies the requirement without abandoning CDK, and state honestly what the requirement is really asking for and whether your response meets it or works around it.
5. Argue both sides of the following proposition, then state your own position and the evidence that would change it: "An organisation running entirely on AWS should use CDK rather than Terraform, and the multi-cloud argument for Terraform is almost always hypothetical." Address abstraction, state management, licensing and governance, team skills, hiring, and the cost of being wrong in either direction.

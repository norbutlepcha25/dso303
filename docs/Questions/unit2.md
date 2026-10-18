# Unit 2: Practice Questions

## 2.1 Docker Fundamentals

1. Define a container image and a container, and state the relationship between them. Explain why the image is described as immutable when a running container can clearly write to its filesystem.

    ??? success "Check your answer"

        A good answer covers:

        - **Image:** a read-only, layered artefact (filesystem layers plus a manifest and a configuration recording entrypoint, environment, ports and user) stored in a registry; on its own it does nothing.
        - **Container:** a running or stopped instance of the image, that is, isolated processes on a host whose root filesystem is assembled from the image's layers.
        - **Relationship:** class to object, or executable to process; one image can produce many containers that share the same read-only layers.
        - **Why immutable:** the runtime stacks the read-only layers with a union filesystem (OverlayFS) and adds one thin writable layer; new files go there, modified files are copied up first (copy-on-write) and deletions become whiteout markers, so the image layers are never changed.
        - **Consequence:** the writable layer is discarded with the container, so container storage is ephemeral and persistent data must go to a volume, EFS, S3 or a database.

2. Explain the difference between a tag and a digest, and give two specific operational consequences of deploying by tag rather than by digest.

    ??? success "Check your answer"

        A good answer covers:

        - **Tag:** a human-readable, mutable pointer such as `myapp:1.4.2` or `latest`; a later push can move it to different content unless tag immutability is enforced.
        - **Digest:** the SHA-256 hash of the image manifest (`myapp@sha256:...`); it is content-addressed, so the same digest always means byte-identical content and it can never be moved.
        - **Consequence 1:** you cannot state with certainty what is running, so rollback to "1.4.2" restores whatever the tag now points at and incident investigation becomes unreliable.
        - **Consequence 2:** the tested artefact is not provably the deployed one; a re-push between staging and production, or a later scale-out, can pull different content and run mixed versions behind one load balancer.
        - **Practice:** build once, resolve the tag to a digest, reference the digest in the task definition, and enable ECR tag immutability on deployable repositories.

3. Name the three Linux kernel mechanisms that make containers possible and state, for each, one architectural consequence that follows from it.

    ??? success "Check your answer"

        A good answer covers:

        - **Namespaces (what a process can see):** each container has its own network stack, so in `awsvpc` mode each task gets its own ENI, IP and security group, and containers in one task share `localhost`; PID namespacing also makes the application PID 1, responsible for handling `SIGTERM`.
        - **cgroups (what a process can consume):** limits are kernel-enforced and asymmetric: exceeding memory causes an OOM kill, exceeding CPU causes throttling and latency, so runtimes such as the JVM must size themselves from the cgroup limit, not host RAM.
        - **Union / copy-on-write filesystem (what a process reads):** layers are shared and cached, so instruction order affects rebuild and pull cost, deleted files still occupy the image, and write-heavy workloads need volumes.
        - **Shared kernel:** all three operate on one host kernel, so containers isolate processes rather than machines, which is why Fargate gives each task its own microVM.

4. Explain what a multi-stage Dockerfile is and list three distinct benefits, at least one of which is not about image size.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** a Dockerfile with several `FROM` instructions; each begins a stage, later stages copy selected output with `COPY --from=<stage>`, and only the final stage becomes the image.
        - **Benefit 1, size:** compilers, build tools, caches and source stay in the discarded build stage, so the runtime image is much smaller and pulls faster.
        - **Benefit 2, attack surface (not size):** the shipped image contains no compiler, package manager or source code, so there is less to exploit and fewer CVEs to triage.
        - **Benefit 3, reproducibility (not size):** the toolchain is pinned inside the Dockerfile, so CI hosts and developer machines produce the same artefact without installing build tooling.
        - **Distinctness:** the three benefits come from different properties (discarding stages, final-stage contents, declared toolchain), not one benefit restated.

5. State the difference between an ECS task and an ECS service, and give one example of work that is correctly run as each.

    ??? success "Check your answer"

        A good answer covers:

        - **Task:** one running instance of a task definition, the unit of execution; it runs until its process exits and nothing restarts it.
        - **Service:** a controller that maintains a desired count of tasks, replaces stopped or unhealthy ones, registers them with a target group, and manages rolling deployments and auto scaling.
        - **Task example:** a nightly database migration, batch report or EventBridge-triggered ETL job that should run once, exit zero and stay stopped.
        - **Service example:** a public HTTPS API behind an ALB that must always have N healthy tasks and scale with traffic.
        - **Why it matters:** running finite work as a service restarts a successful job forever; running an API as a standalone task leaves it down after the first crash.

6. An ECS task in a private subnet fails with `CannotPullContainerError`. List four distinct possible causes, state how you would distinguish them from one another, and give the remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **No network path:** no NAT route and no VPC endpoints; the error is a timeout against `api.ecr`. Remedy: interface endpoints for `ecr.api` and `ecr.dkr`, the S3 gateway endpoint (layers live in S3) and `logs`, or a NAT gateway.
        - **Execution role missing or under-permissioned:** the error is `AccessDenied` on an `ecr:` action, confirmed in CloudTrail. Remedy: attach a correct execution role (the pull uses the execution role, not the task role) and fix any repository or KMS key policy denial.
        - **Image, tag or architecture wrong:** the error says `manifest not found`, `repository does not exist` or `no matching manifest`. Remedy: correct the URI (account, Region, repository, tag), push the image, or build for the task's architecture.
        - **Security controls block the route:** also a timeout, so separate it from the first cause by checking that routes and endpoints exist; then check task SG egress 443, endpoint SG ingress 443 from the task SG, NACL return ports, and private DNS. VPC Flow Logs showing `REJECT` confirm it.
        - **Method:** read the exact stopped-task reason first; timeout, access denied and not found point at different subsystems.

7. Explain why a file deleted in a later Dockerfile layer still occupies space in the image, and describe the correct mechanism for using a credential during a build without it entering the image.

    ??? success "Check your answer"

        A good answer covers:

        - **Layers are additive and sealed:** each instruction creates an immutable layer; a later deletion writes a whiteout entry that hides the path but cannot change the earlier layer.
        - **Consequence:** the bytes still ship, still count towards size, and are extractable with `docker history` or `docker save`; a secret placed there is compromised and must be rotated.
        - **Avoiding it:** never bring the file in, create and delete it within a single `RUN`, or produce it in a discarded build stage.
        - **Correct mechanism for credentials:** a BuildKit secret mount, `RUN --mount=type=secret,id=<id>` with `docker build --secret id=<id>,src=<file>`; it is mounted for that instruction only and never enters a layer, history or the cache (`--mount=type=ssh` for SSH keys).
        - **Not acceptable:** `ARG`/`--build-arg` and `ENV`, both recorded in the image configuration. Runtime secrets come from the ECS `secrets` block or an IAM task role instead.

8. Compare the task execution role, the task role, and the container instance role. For each, state what assumes it, when, and what a compromise of that identity would grant an attacker.

    ??? success "Check your answer"

        A good answer covers:

        - **Task execution role:** assumed by the ECS agent or Fargate infrastructure at task start-up to pull images, fetch secrets for injection and write logs; compromise discloses images and, more seriously, every secret those task definitions can inject.
        - **Task role:** assumed by the application inside the container while it runs, via the credentials endpoint at `169.254.170.2`; compromise through SSRF, RCE or a malicious dependency grants exactly the application's AWS permissions.
        - **Container instance role:** the EC2 instance profile, EC2 launch type only, used by the ECS agent from boot to register and poll for work; compromise is host- and cluster-level, and any container that can reach IMDS can steal it, enabling lateral movement between co-located tasks.
        - **Controls:** least privilege and one role per service for the first two; IMDSv2 with hop limit 1, `awsvpc` mode and a minimal instance profile for the third, or Fargate, which removes it.
        - **Diagnostic rule:** task cannot start points at the execution role; application `AccessDenied` points at the task role; instance missing from the cluster points at the instance role.

9. Your organisation's ECR storage cost has tripled in a year with no change in the number of services. Describe your investigation, the most likely finding, and a lifecycle policy that fixes it. State one risk of an aggressive lifecycle policy.

    ??? success "Check your answer"

        A good answer covers:

        - **Investigation:** ECR bills per GB-month of storage, so confirm in Cost Explorer that growth is storage rather than data transfer, attribute it per repository (tags, `describe-images`), and check whether any lifecycle policy exists.
        - **Likely finding:** CI pushes an image per commit and nothing deletes them, plus many untagged manifests orphaned by re-pushing moving tags such as `latest`; growth is linear in build rate.
        - **Policy:** keep the last N release-tagged images, keep fewer development images, and expire untagged images after about 14 days; run a lifecycle policy preview before applying it.
        - **Complementary fixes:** tag immutability and multi-stage builds address the causes rather than the symptom.
        - **Risk:** deleting an image a deployed service still needs; running tasks continue, but scale-out, replacement and rollback then fail with `CannotPullContainerError`. Mitigate by retaining longer than the rollback window, exempting release tags, and archiving rather than expiring where retention is required.

10. Explain why image size is described in this chapter as a performance and reliability property rather than as housekeeping. Include the specific metric you would use to measure the effect and where you would obtain it.

    ??? success "Check your answer"

        A good answer covers:

        - **Platform fact:** on Fargate each task runs on its own single-use instance with no layer caching, so the whole image is pulled for every task launch.
        - **Performance:** pull time sits on the critical path of scale-out, deployment and rollback, widening the window in which demand exceeds capacity.
        - **Reliability:** recovery after a task, host or AZ failure depends on how fast replacements become healthy; large concurrent pulls during incidents are exposed to network and NAT limits; more packages mean more CVEs to patch.
        - **Metric:** image pull duration per task, `pullStoppedAt` minus `pullStartedAt`, from `aws ecs describe-tasks` or durably from ECS Task State Change events in EventBridge, tracked as p50/p95 per service and digest.
        - **Context:** also measure total time from `createdAt` to healthy target registration, to confirm what share of start-up the image actually owns before optimising it.

11. A team proposes that their CI pipeline rebuild the image from the same Dockerfile in each environment "so that each environment gets the freshest dependencies". Write the argument you would make in response. Address what is genuinely correct in their reasoning, what the specific failure mode is, what you would do instead, and how you would satisfy the underlying concern about dependency freshness without abandoning build-once-promote-many.

    ??? success "Check your answer"

        A good answer covers:

        - **What is correct:** stale dependencies are a real risk, frequent rebuilds are the remedy, and frequent builds expose build fragility early.
        - **Failure mode:** the same Dockerfile built twice can differ (floating base tags, unpinned packages, re-resolved dependencies), so production runs an image no test executed; failures cannot be reproduced, rollback has no defined target, and a compromised upstream package can reach production ungated.
        - **Instead:** build once per commit, resolve to a digest, scan and sign it, and promote that digest through every environment, with environment differences injected at run time (environment variables, `secrets` from Parameter Store or Secrets Manager).
        - **Freshness without rebuilding per environment:** scheduled rebuilds of the current release through the full pipeline, rebuilds triggered by new base-image digests, ECR enhanced scanning with Amazon Inspector for continuous rescanning, pinned dependencies with automated update pull requests.
        - **Measure it:** a published patch SLA and measured artefact age; freshness comes from rebuild frequency, not rebuild location.

12. Design the complete image supply chain for a regulated organisation that must be able to answer, for any date in the past two years, exactly which code was running in production and what its known vulnerabilities were at that time. Specify the build, registry, deployment, and audit mechanisms; state which controls are preventive and which are detective; and identify the one question your design still cannot answer.

    ??? success "Check your answer"

        A good answer covers:

        - **Build:** hermetic builds in an isolated account from protected refs, base images pinned by digest, lockfiles; each build emits an SBOM and provenance attestation keyed to the digest, and the image is signed.
        - **Registry:** ECR with tag immutability, KMS encryption, restrictive repository policies, enhanced scanning in continuous mode, and lifecycle rules that exempt deployed digests (archive storage rather than expiry for two-year retention).
        - **Deployment:** task definitions reference digests only; only the pipeline role may deploy (IAM and SCPs); the pipeline verifies signature and scan status and writes a release record.
        - **Audit:** CloudTrail with log file validation and ECS task state-change events into S3 with Object Lock; Inspector findings snapshotted with first-observed timestamps; Athena joins date to digest to commit to findings known at that date.
        - **Preventive vs detective:** preventive includes tag immutability, digest pinning, deploy restrictions, signing, Object Lock; detective includes CloudTrail, state-change events, continuous scanning, Config rules, Security Hub and GuardDuty.
        - **Cannot answer:** whether a recorded vulnerability was actually exploitable in that deployment, or which vulnerabilities existed but were unknown on that date.

13. A legacy Java application writes session state to local disk, logs to rotating files, reads configuration from a properties file baked into its deployment, and requires a specific JVM patch level. Design its containerisation. Order the work by risk, state what must change in the application itself before containerisation is honest rather than cosmetic, and identify which single change you would refuse to skip even under schedule pressure.

    ??? success "Check your answer"

        A good answer covers:

        - **Order by risk:** first externalise session state to ElastiCache for Redis or DynamoDB (sticky sessions only as a temporary bridge); then logs to stdout via `awslogs` or FireLens; then configuration to environment variables, Parameter Store and the `secrets` block; then the image.
        - **Image:** multi-stage build on a base pinned by digest to guarantee the JVM patch level, non-root user, heap sized with `-XX:MaxRAMPercentage` so the JVM respects the cgroup limit.
        - **Lifecycle:** exec-form entrypoint so the JVM receives `SIGTERM`, a readiness endpoint, `stopTimeout` and deregistration delay aligned, circuit breaker enabled; cut over gradually with weighted routing.
        - **Honest containerisation:** the application must become stateless, log to stdout, and take configuration from the environment so one image is promoted everywhere.
        - **Refuse to skip:** externalising session state, because ECS replaces tasks on every deployment, scale-in, failed health check and host retirement; with local-disk sessions each routine event becomes a user-visible failure.

14. An organisation running forty services on Fargate observes that scale-out during traffic spikes takes ninety seconds from alarm to serving capacity, and users experience errors during that window. Decompose the ninety seconds into its contributing phases, identify which phases you can influence and by how much, propose specific changes ordered by expected effect, and state which part of the problem cannot be solved by making the image smaller and what you would do about that instead.

    ??? success "Check your answer"

        A good answer covers:

        - **Decomposition (measured from task timestamps):** scaling reaction about 5-15 s; Fargate microVM and ENI provisioning about 10-20 s (not controllable); image pull about 20-30 s; application start about 20-30 s; health check and registration about 15-30 s.
        - **Change 1, health checks:** shorter interval and lower healthy threshold with a cheap readiness path; largest saving, configuration only, applies to all forty services.
        - **Change 2, image:** multi-stage minimal images, same-Region ECR, `ecr.api`/`ecr.dkr` and S3 gateway endpoints, zstd compression, SOCI lazy loading for large images.
        - **Change 3 and 4:** faster application start (CDS, lazy initialisation, adequate vCPU) and a tighter scaling reaction (short scale-out cooldown, `ALBRequestCountPerTarget`, step scaling for large jumps).
        - **What image size cannot fix:** reactive scaling is inherently late, since metric publication and alarm evaluation add time before the ninety seconds even start; the errors are a headroom problem.
        - **Instead:** lower utilisation target and higher minimum, scheduled and predictive scaling, high-resolution leading metrics, load shedding, circuit breakers and jittered retries, validated by a load test.

15. Critique the following proposal: "We will use a single shared base image for all services, containing our standard JDK, our monitoring agent, our logging library, curl, the AWS CLI, and a shell, so that every team gets the same tooling and debugging is easy. We will tag it `company/base:latest` and rebuild it nightly so it is always patched." Identify at least five specific defects, propose a corrected design, and state which parts of the original intent you would preserve and how.

    ??? success "Check your answer"

        A good answer covers:

        - **Defects:** `latest` is mutable, so builds are irreproducible and base changes cannot be rolled back; a nightly push injects an untested change into all services at once; `curl`, a shell and the AWS CLI give an attacker a ready toolkit and add CVEs; rebuilding the base does not patch anything until services rebuild and redeploy; the logging library and monitoring agent do not belong in a base image; one JDK excludes other runtimes; no scanning, signing or SBOM.
        - **Corrected design:** a small curated set of thin bases per runtime with no shell or CLI, plus a separate `-debug` variant; immutable dated tags with ECR tag immutability, consumed by digest.
        - **Patch pipeline:** scheduled and CVE-triggered base rebuilds that scan, sign and smoke-test, then automated pull requests bumping each service's pinned digest so adoption passes each service's own tests, with a canary cohort first.
        - **Relocation:** monitoring agent and log shipping as sidecars; logging library as a normal versioned dependency.
        - **Preserved intent:** consistency through the curated set and shared pipeline templates; central patching through the central rebuild plus measured adoption; easy debugging through ECS Exec and debug sidecars.

---

## 2.2 Amazon ECS

1. Define an ECS cluster and list the four boundaries it provides. State one thing a cluster is not.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** a logical grouping of services, tasks and capacity in one Region.
        - **Namespace:** service names are unique within a cluster.
        - **Capacity boundary:** container instances register with exactly one cluster, and tasks are placed only on that cluster's capacity.
        - **Permissions and observability boundaries:** IAM can scope `ecs:*` actions to a cluster ARN, and Container Insights and dashboards are naturally cluster-scoped.
        - **What it is not:** not a network or security boundary; networking comes from the VPC, subnets and security groups, and a cluster can span several AZs.

2. Explain the difference between a task and a service, and give one example of work suited to each.

    ??? success "Check your answer"

        A good answer covers:

        - **Task:** one running instantiation of a task-definition revision; it runs to completion and is not restarted.
        - **Service:** a reconciliation loop holding `desiredCount`, replacing failed tasks, registering targets with load balancers and managing deployments and scaling.
        - **Task example:** a database migration, batch job or scheduled report started with `RunTask` or EventBridge Scheduler.
        - **Service example:** an API, a web front end or a queue consumer that should always be running.

3. State three specific capabilities that AWS Fargate does not offer, and for each explain what you would use instead.

    ??? success "Check your answer"

        A good answer covers:

        - **GPUs:** not available on Fargate; use EC2 capacity with GPU instance types (or Amazon ECS Managed Instances).
        - **Privileged containers and host daemons, including the `DAEMON` strategy:** not available; use sidecar containers per task, or EC2 capacity with a `DAEMON` service for node-level agents.
        - **Local NVMe instance storage:** not available (ephemeral storage only, up to 200 GB); use EC2 instances with local NVMe, or EFS where shared persistent storage is the real need.
        - **Also acceptable:** host access and custom kernel configuration (use EC2 capacity, or ECS Exec for debugging on Fargate) or a warm image-layer cache (EC2 capacity).

4. Explain what `awsvpc` network mode gives each task, and state one architectural constraint that follows from it.

    ??? success "Check your answer"

        A good answer covers:

        - **What it gives:** each task its own ENI, private IP address and security groups, as if it were a small instance in the VPC; required on Fargate.
        - **Benefits:** per-task security groups and load-balancer target type `ip`, so the ALB reaches the task directly with no NAT hop.
        - **Constraint:** every task consumes a subnet IP address, so subnet size bounds the number of tasks and must be planned up front.
        - **Other valid constraints:** ALB target type must be `ip`, not `instance`; on EC2, ENI limits per instance cap tasks per host unless ENI trunking is enabled.

5. Describe the difference between a container health check and a target group health check, and give one symptom that would distinguish a failure of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Container health check:** run by the ECS agent inside the container (the `healthCheck` command); decides whether ECS considers the container healthy and drives `dependsOn: HEALTHY`.
        - **Target group health check:** run by the load balancer over the network against a port and path; decides whether the target receives traffic.
        - **Container check failing:** ECS stops and replaces the task even when no load balancer is involved; a `startPeriod` shorter than the cold start produces a restart loop.
        - **Target check failing:** container reported healthy but target unhealthy, which points at the security group not allowing the ALB, the wrong port, or a path requiring authentication.

6. A service on EC2 capacity increases its desired count during peak load but tasks remain in `PROVISIONING` while instance CPU looks healthy. Explain the mechanism, list three distinct possible causes, and give the remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** the scheduler places tasks against reserved CPU, memory, ports and ENIs, not measured utilisation; if no instance has enough remaining reservation, the task waits in `PROVISIONING`, while CPU graphs can look healthy.
        - **Cause 1, no capacity layer:** managed scaling not enabled, or the ASG at its maximum. Remedy: enable capacity provider managed scaling with target capacity below 100 per cent and a sensible ASG maximum.
        - **Cause 2, reservation exhausted on another resource:** memory reservations or static host ports are used up. Remedy: right-size reservations, use dynamic port mapping or `awsvpc`.
        - **Cause 3, network limits:** subnet IP addresses or per-instance ENI limits exhausted in `awsvpc` mode. Remedy: larger subnets, ENI trunking.
        - **Also valid:** a `memberOf` constraint that no instance satisfies. Diagnose from the service events, which name the unmet requirement.

7. Compare ECS Service Connect, AWS Cloud Map DNS, and an internal Application Load Balancer for service-to-service communication. Name the axis on which they actually differ and state the situation in which each is correct.

    ??? success "Check your answer"

        A good answer covers:

        - **Axis:** where the routing decision is made: at a load balancer in the middle, in the client after a DNS lookup, or in a managed proxy on `localhost` inside the task.
        - **Service Connect:** Envoy-based proxy, no extra hop, client-side load balancing, outlier ejection, retries, per-client metrics; correct for ECS-to-ECS HTTP or gRPC within one namespace.
        - **Cloud Map DNS:** simple and protocol-agnostic but no retries, and clients may cache stale addresses; correct for non-HTTP protocols or callers that cannot use the proxy.
        - **Internal ALB:** an extra hop and hourly cost, but works across VPCs and accounts and for callers outside ECS; correct when crossing those boundaries or needing ALB features (VPC Lattice is the newer option across boundaries).

8. A capacity provider strategy specifies `FARGATE` with `base=3, weight=1` and `FARGATE_SPOT` with `weight=3`. Calculate the distribution at desired counts of 2, 6, and 15, and explain what the `base` is actually protecting against.

    ??? success "Check your answer"

        A good answer covers:

        - **Rule:** the base is placed first on `FARGATE` as an absolute count; only tasks beyond it are split by weight, here 1:3.
        - **Desired 2:** both on `FARGATE`; the base is not yet filled and Spot gets nothing.
        - **Desired 6:** 3 base, remainder 3 split 0.75 : 2.25, so about 1 more On-Demand and 2 Spot, giving roughly 4 `FARGATE` and 2 `FARGATE_SPOT` (the scheduler handles the rounding).
        - **Desired 15:** 3 base, remainder 12 split 3 : 9, giving 6 `FARGATE` and 9 `FARGATE_SPOT`.
        - **What the base protects:** an On-Demand floor that survives a total Spot reclamation; it is an absolute minimum, not a proportion, so it must be sized to carry the critical load on its own.

9. Explain the four settings that together determine whether a deployment is user-visible, state how each should be derived from a measurement, and describe the symptom produced when each is wrong.

    ??? success "Check your answer"

        A good answer covers:

        - **Health-check grace period:** set above the measured cold start; if too short, the ALB kills tasks still warming up and the service replaces them in a loop.
        - **Deregistration delay:** set just above the p99 request duration; if too short, in-flight requests are cut and users see 502s during each deployment.
        - **`SIGTERM` handling:** the application must catch the signal, stop accepting work and drain; without it, every deployment drops in-flight requests regardless of the other values.
        - **`stopTimeout`:** set above the drain time the application needs and above the deregistration delay; if too short, ECS sends `SIGKILL` while requests are still draining.
        - **Key point:** the four values must agree with each other, and the defaults suit few real workloads.

10. Your organisation runs eleven ECS services, each behind its own Application Load Balancer, in private subnets with no VPC endpoints and Container Insights disabled. Identify the three largest problems, ranked by the harm they cause, and the remediation for each.

    ??? success "Check your answer"

        A good answer covers:

        - **No VPC endpoints:** every image pull, log write and secret fetch goes through a NAT gateway, so task launches depend on NAT availability and pay NAT data processing. Remedy: interface endpoints for `ecr.api`, `ecr.dkr`, `logs` and `secretsmanager`, plus the S3 gateway endpoint.
        - **Container Insights disabled:** no task- and service-level CPU, memory or task-count metrics, so incidents are detected late and diagnosed slowly. Remedy: enable Container Insights at the cluster level and build alarms and dashboards on it.
        - **Eleven ALBs:** eleven fixed hourly charges and eleven sets of configuration. Remedy: one or a few shared ALBs with host- or path-based listener rules, and Service Connect for internal traffic.
        - **Ranking:** any order is acceptable if justified by harm; availability and detection problems usually outrank cost.

11. A team of five running eight services on Fargate has been told by a consultant to migrate to EC2 capacity because "Fargate is 20 per cent more expensive per vCPU". Write the response you would give. Address what is correct in the claim, what the total-cost comparison actually looks like, what conditions would make the migration right, and what evidence you would gather before deciding either way.

    ??? success "Check your answer"

        A good answer covers:

        - **What is correct:** Fargate does carry a per-vCPU premium over equivalent EC2 capacity, and it matters at sustained high utilisation.
        - **Total cost:** EC2 adds idle headroom, bin-packing waste, AMI patching, ASG and capacity-provider tuning, IMDS hardening and a second scaling layer; for five people this cost is engineering time that never appears on the invoice.
        - **When migration is right:** sustained high utilisation with commitments, hardware Fargate lacks (GPU, local NVMe), `DAEMON` workloads, or start latency that needs a warm cache.
        - **Evidence:** actual utilisation profiles from Container Insights, current Fargate spend with Savings Plans and Graviton applied, an estimate of realistic EC2 utilisation after headroom, and engineering hours required.
        - **Default rule:** start on Fargate and move a workload only when a measured constraint requires it.

12. Design the complete ECS topology  accounts, clusters, capacity providers, load balancing, and service discovery  for a SaaS company with a pooled multi-tenant tier and a contractually siloed enterprise tier. Justify every boundary, state where the two tiers share infrastructure and where they must not, and identify the one design decision you would find hardest to reverse later.

    ??? success "Check your answer"

        A good answer covers:

        - **Accounts:** the pooled tier in shared accounts per environment; each siloed enterprise tenant in its own account (or at least its own VPC and cluster), because the account is the strongest audit and blast-radius boundary.
        - **Clusters and capacity:** a cluster per environment (and per team at scale) for the pooled tier; per-tenant clusters for silos; Fargate by default, with an On-Demand base under any Spot.
        - **Load balancing and discovery:** a shared ALB with host-based routing for the pooled tier; dedicated ALBs per silo; a Service Connect namespace per environment, not shared across tiers.
        - **Shared:** CI/CD pipelines, the same image digests (cross-account ECR pull), and centralised observability. **Not shared:** compute, network, data stores and KMS keys of siloed tenants.
        - **Hardest to reverse:** the account and tenancy boundary, together with VPC and subnet sizing, because moving data and networks later is far harder than moving services.

13. A service suffers a complete outage. The trigger was a single Availability Zone becoming unreachable for eleven minutes. The service was configured with three subnets and a desired count of six, and yet all traffic failed. Explain every design defect that must have been present for this outcome to occur, and specify the changes  with configuration specifics  that would have reduced the impact to a brief degradation.

    ??? success "Check your answer"

        A good answer covers:

        - **Tasks not actually spread:** on EC2, no `spread` strategy or an ASG confined to one AZ, so all six tasks sat in the failed zone. Change: `spread` on `attribute:ecs.availability-zone` then `binpack`, ASG across three AZs, and a dashboard verifying task count per AZ.
        - **A shared single-AZ dependency:** a single NAT gateway, a single-AZ database or another dependency in the failed zone that the surviving tasks needed. Change: NAT per AZ or VPC endpoints, Multi-AZ RDS, and checking every dependency for zone scope.
        - **Load balancer or health checks:** an ALB not enabled in all three AZs, or deep health checks that failed every target because a dependency was down. Change: ALB in all three AZs and readiness checks that reflect the task's own ability to serve.
        - **No headroom:** surviving capacity could not carry full load. Change: size so two AZs carry peak (N+1 AZ), with scaling able to replace the lost third quickly.

14. Compare, with a total-cost-of-ownership argument, running twenty-two services in one shared ECS cluster against four clusters divided by team. Include IAM scoping, blast radius, capacity sharing on EC2, observability, cost attribution, and the cost of cross-cutting change. Then argue the opposite position as strongly as you can, and state what evidence would change your mind.

    ??? success "Check your answer"

        A good answer covers:

        - **One cluster:** better bin packing and shared headroom on EC2, one dashboard, one place for cross-cutting change; but IAM must be scoped per service rather than per cluster, all teams share a blast radius for capacity exhaustion, and cost attribution relies on tags.
        - **Four team clusters:** IAM scoped to a cluster ARN per team, contained blast radius, team-level observability and cost attribution at no extra charge; but less capacity sharing on EC2 and four times the work for cross-cutting changes unless managed through shared IaC modules.
        - **Fargate changes the balance:** with no instances, the capacity-sharing argument for one cluster largely disappears.
        - **Opposite position:** argue the other side seriously, for example that shared IaC makes four clusters cheap to manage, or that per-service IAM makes one cluster safe enough.
        - **Evidence:** measured utilisation and bin-packing efficiency, frequency of cross-team incidents, team autonomy needs, and audit or compliance requirements.

15. Critique the following proposal from a platform team: "We will run everything on EC2 capacity in `bridge` mode with dynamic port mapping for maximum density, one cluster for the whole company, target capacity at 100 per cent to avoid waste, an internal ALB between every pair of services for reliability, Cloud Map DNS with a 300-second TTL to reduce lookups, and a single shared security group so services can reach each other without rule maintenance." Identify at least six specific defects, propose a corrected design, and state which parts of the original intent are legitimate and how you would satisfy them.

    ??? success "Check your answer"

        A good answer covers:

        - **Defects:** `bridge` mode loses per-task security groups; one company-wide cluster gives one blast radius and coarse IAM; target capacity 100 per cent makes every scale-out wait for an instance launch; an ALB per pair adds hops, cost and configuration; a 300-second TTL leaves callers on stopped tasks after deployments; one shared security group removes all network segmentation; everything on EC2 takes on patching and IMDS risk regardless of need.
        - **Corrected design:** `awsvpc` with security-group references per service, clusters per team and environment, target capacity around 80-90 per cent, Service Connect for east-west traffic, Fargate as the default with EC2 only where measured.
        - **Legitimate intent, density:** keep bin packing on EC2 where it applies (`spread` then `binpack`, ENI trunking).
        - **Legitimate intent, reliability and less rule maintenance:** Service Connect provides retries and outlier ejection; security-group references defined in shared IaC remove manual rule upkeep.
        - **Legitimate intent, avoiding waste:** a target capacity slightly below 100 per cent and Spot for tolerant workloads.

---

## 2.3 Container Orchestration with Amazon ECS

1. Explain the difference between a placement constraint and a placement strategy, and give one example of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Constraint:** a filter that decides which instances are eligible; it can make placement impossible.
        - **Strategy:** a sort order applied to the instances that survive the filter; it never prevents placement.
        - **Constraint example:** `distinctInstance`, or `memberOf` with a Cluster Query Language expression such as `attribute:ecs.instance-type =~ m6i.*`.
        - **Strategy example:** `spread` on `attribute:ecs.availability-zone`, or `binpack` on `memory`.

2. State the standard production placement strategy for an ECS service on EC2 capacity and explain why the order of the two rules matters.

    ??? success "Check your answer"

        A good answer covers:

        - **Standard strategy:** `spread` on `attribute:ecs.availability-zone`, then `binpack` on `memory`.
        - **How it reads:** first choose the AZ with the fewest tasks of this service, then within it the fullest instance that still fits.
        - **Why order matters:** strategies are successive sort keys; spreading first protects against zone failure, packing second gives density within each zone.
        - **Reversed order:** `binpack` first fills one instance before considering zones, concentrating replicas on one host in one AZ.

3. Define `minimumHealthyPercent` and `maximumPercent`, and state the values that ensure capacity never drops during a deployment.

    ??? success "Check your answer"

        A good answer covers:

        - **`minimumHealthyPercent`:** the floor, as a percentage of `desiredCount`, below which healthy tasks must not fall during a deployment.
        - **`maximumPercent`:** the ceiling on total tasks, old plus new, during a deployment.
        - **Values:** `minimumHealthyPercent: 100` with `maximumPercent: 200` (or 150 when capacity is tight); new tasks start before old ones stop.
        - **Note:** 100 / 100 cannot make progress, and 50 / 100 halves capacity on every deployment.

4. Explain what the deployment circuit breaker does and name one class of failure it cannot detect.

    ??? success "Check your answer"

        A good answer covers:

        - **What it does:** watches a rolling deployment and, if new tasks repeatedly fail to become healthy, marks it failed and (with `rollback: true`) redeploys the previous revision.
        - **What it detects:** tasks that fail to start, exit immediately, cannot pull their image, fail container health checks, or never become healthy targets.
        - **What it cannot detect:** a release that starts cleanly and passes health checks but behaves incorrectly, for example wrong results or a higher error rate.
        - **What covers the gap:** CloudWatch alarm-based rollback on error rate and latency, or canary deployment with validation.

5. Name the three scaling policy types available for ECS services and give one situation in which each is the right choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Target tracking:** hold a metric near a target value, for example `ALBRequestCountPerTarget` for an HTTP API; the default choice.
        - **Step scaling:** defined alarm thresholds with specific adjustments; right for asymmetric or aggressive responses, such as adding many tasks at once on a large spike.
        - **Scheduled scaling:** set minimum and maximum capacity on a schedule; right for known calendar-driven peaks, raising the floor before they arrive.
        - **Combination:** scheduled scaling sets the floor and target tracking handles variance above it.
        - **Note:** current AWS documentation also lists predictive scaling for ECS services, which forecasts capacity from daily or weekly patterns in historical load; naming it as an addition is correct.

6. A service scaling on `CPUUtilization` at a 70 per cent target never scales out, yet p99 latency triples during peak. Explain the mechanism, state what the correct metric would be, and describe how you would derive its target value.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** the service is I/O-bound; requests wait on downstream calls, connection pools or threads, so latency rises while CPU stays low and the policy never fires.
        - **Correct metric:** `ALBRequestCountPerTarget`, which measures the real driver of load per task.
        - **Deriving the target:** load test to find the requests per task at which p99 latency starts to degrade, then set the target at about 60-70 per cent of that value.
        - **Why the margin:** the headroom absorbs the load that arrives during the scaling delay.

7. Explain why scaling a queue consumer on `ApproximateNumberOfMessagesVisible` causes oscillation. Give the correct metric expression, derive a target value from a stated latency promise, and name one implementation detail that prevents the expression failing at scale-to-zero.

    ??? success "Check your answer"

        A good answer covers:

        - **Why it oscillates:** raw queue depth has no denominator; it does not fall in proportion to added tasks, so target tracking cannot tell whether added capacity is enough and overshoots in both directions.
        - **Correct expression:** backlog per task, `ApproximateNumberOfMessagesVisible / RunningTaskCount`, as a metric math customised metric.
        - **Target derivation:** acceptable latency divided by processing time per message per task; for example 60 s / 0.2 s = 300 messages per task.
        - **Scale-to-zero detail:** guard the division when `RunningTaskCount` is zero, for example `IF(m2 > 0, m1 / m2, m1)` or a fill value, so the expression still returns a value that triggers scale-out.
        - **Complementary alarm:** `ApproximateAgeOfOldestMessage` checks whether the latency promise is actually kept.

8. A service with three configured subnets went down entirely during an Availability Zone impairment. List four distinct configuration or verification failures that could have contributed, and give the remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **No AZ spread on EC2:** tasks concentrated in one zone. Remedy: `spread` on `attribute:ecs.availability-zone` first.
        - **Capacity confined to one AZ:** the ASG or capacity provider launched instances in one zone, or a `memberOf` constraint limited placement. Remedy: ASG across all three AZs and constraints audited.
        - **Distribution never verified:** three subnets only permit multi-AZ placement. Remedy: a dashboard of task count by AZ, checked after capacity changes.
        - **Single-AZ dependency or too little capacity:** a single NAT gateway or single-AZ database, or a minimum count too low for two AZs to carry the load. Remedy: per-AZ NAT or VPC endpoints, Multi-AZ data stores, minimum at least the number of AZs and sized for N+1.

9. Describe the four settings that determine whether a rolling deployment is user-visible, explain how each should be derived, and state the symptom produced when each is wrong.

    ??? success "Check your answer"

        A good answer covers:

        - **Health-check grace period:** above the measured cold start; too short and warming tasks are killed and replaced in a loop.
        - **Deregistration delay:** just above p99 request duration; too short and in-flight requests are cut, producing 502s during deployments.
        - **`SIGTERM` handling:** the application traps the signal, stops accepting work and drains; without it every deployment drops requests.
        - **`stopTimeout`:** above the drain time and the deregistration delay; too short and ECS sends `SIGKILL` mid-drain.
        - **Related settings:** `minimumHealthyPercent: 100` and `maximumPercent: 200` so capacity does not dip while this happens.

10. Explain the difference between what the deployment circuit breaker detects and what CloudWatch alarm-based rollback detects, and describe a specific release that would defeat the first and be caught by the second.

    ??? success "Check your answer"

        A good answer covers:

        - **Circuit breaker:** detects task-level health failures, that is, tasks that do not start or never become healthy.
        - **Alarm-based rollback:** detects behavioural regression through named alarms (5xx rate, p99 latency, a business metric) entering `ALARM` during the deployment's bake period.
        - **Example release:** a version whose `/health` endpoint returns 200 but whose checkout endpoint returns 500 for a common input, or whose new query triples latency; tasks are healthy so the circuit breaker passes it, and the 5xx or latency alarm rolls it back.
        - **Caveat:** the alarm must be sensitive enough to fire within the bake period, and should be tested deliberately.

11. A service's auto scaling policy asks for 40 tasks but the service never exceeds 12, with no error reported anywhere. Enumerate every mechanism that could impose that cap, describe the single diagnostic comparison that narrows the cause fastest, and explain why none of these caps surfaces as an error.

    ??? success "Check your answer"

        A good answer covers:

        - **Scaling layer cap:** the scalable target's maximum capacity is 12, so Application Auto Scaling clamps the request.
        - **Placement caps:** `distinctInstance` with only 12 instances, a `memberOf` constraint matching few instances, or the ASG at its maximum with no managed scaling headroom.
        - **Network and quota caps:** subnet IP exhaustion or ENI limits in `awsvpc` mode, or account-level Fargate or EC2 vCPU quotas.
        - **Diagnostic comparison:** compare `desiredCount` with `runningCount`. If desired is 12, the cap is in the scaling layer (check `describe-scaling-activities` and the maximum); if desired is 40 and running is 12, the cap is in placement or capacity (read the service events).
        - **Why no error:** each is a limit working as designed; clamping and unplaced tasks are recorded as scaling activities and service events, not failures, so an alarm on sitting at maximum is needed.

12. Design the complete orchestration configuration for a payment service with a 99.99 per cent availability target, a twice-daily traffic peak, and a regulatory requirement that no release reaches more than five per cent of users before validation. Specify placement, capacity, scaling, and deployment settings; justify each value; and identify the one requirement your design satisfies only partially and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Placement and capacity:** three AZs, `spread` on AZ (and `distinctInstance` on EC2), or Fargate across three AZ subnets; minimum sized so two AZs carry peak; On-Demand only for this path.
        - **Scaling:** scheduled scaling raising the minimum before each peak, target tracking on `ALBRequestCountPerTarget` with a target derived from a load test, short scale-out and long scale-in cooldowns, a justified maximum with an alarm.
        - **Deployment:** CodeDeploy blue/green with a canary configuration shifting 5 per cent first, an `AfterAllowTestTraffic` validation hook, alarm-based rollback on 5xx and latency, and feature flags to separate deploy from release.
        - **Shutdown settings:** grace period, deregistration delay, `SIGTERM` handling and `stopTimeout` aligned.
        - **Partially satisfied:** canary shifting splits requests, not users, so "five per cent of users" is approximate (user-targeted feature flags get closer); 99.99 per cent also depends on dependencies and one Region, which ECS configuration alone cannot guarantee.

13. A team argues that blue/green deployment should be mandatory across all forty of their services. Write the response you would give. Address what blue/green genuinely provides over rolling updates, what it costs, the specific condition under which it degenerates into an expensive rolling update, which services you would apply it to and why, and what cheaper intervention would improve safety across all forty.

    ??? success "Check your answer"

        A good answer covers:

        - **What it provides:** a full green task set validated by test traffic before production sees it, canary or linear traffic shifting, and rollback as a routing change in seconds.
        - **What it costs:** double capacity during deployment and bake, two target groups and a test listener, CodeDeploy configuration, and loss of the predefined `ALBRequestCountPerTarget` scaling metric.
        - **Degenerate condition:** without lifecycle hooks that actually validate behaviour, it is a costlier rolling update with faster rollback only.
        - **Where to apply it:** user-facing, high-risk services such as checkout or payments where a bad release is expensive and validation hooks will be written.
        - **Cheaper intervention for all forty:** circuit breaker with rollback plus alarm-based rollback on 5xx and latency, `100/200` deployment settings, and feature flags, all in a shared IaC module.

14. An organisation's ECS estate suffers a full outage. The trigger was a deployment of a service whose new revision passed all health checks. The outage lasted fifty minutes and affected services that were not deployed. Explain a plausible mechanism in detail, identify every design defect that must have been present, and specify the changes  with configuration specifics  that would have bounded the incident to a degraded few minutes for one service.

    ??? success "Check your answer"

        A good answer covers:

        - **Plausible mechanism:** the new revision opened far more database connections, or retried aggressively without backoff, exhausting a shared database or downstream service; every other service using that dependency then failed while the deployed service's shallow `/health` still passed.
        - **Defects:** shallow health checks only; no alarm-based rollback; all traffic shifted at once; a shared dependency with no per-service limits (bulkheads); no timeouts, circuit breakers or retry budgets in callers; detection and rollback left to humans, hence fifty minutes.
        - **Deployment changes:** alarm-based rollback on 5xx rate and p99 latency for the deployed service and its key dependencies, canary shifting with a validation hook, circuit breaker with rollback.
        - **Isolation changes:** per-service connection limits (for example RDS Proxy), client timeouts, circuit breakers and retries with exponential backoff and jitter, so a dependency under stress degrades one path rather than the estate.
        - **Outcome:** the regression is caught within the bake period and rolled back by routing or redeployment in minutes.

15. Critique the following configuration standard proposed by a platform team: "All services will use `binpack` on CPU for cost efficiency, scale on CPU utilisation at a 60 per cent target with 300-second cooldowns in both directions, deploy with `minimumHealthyPercent: 50` and `maximumPercent: 100` to avoid extra capacity cost, rely on the deployment circuit breaker for safety, and set scaling maximum to 1000 so we never run out of capacity." Identify at least six specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.

    ??? success "Check your answer"

        A good answer covers:

        - **Defects:** `binpack` alone concentrates replicas in one AZ; CPU is the wrong signal for I/O-bound services and queue consumers; a 300-second scale-out cooldown responds too slowly; one target value for every service is a guess, not a measurement; `50/100` halves capacity on every deployment; the circuit breaker cannot catch behavioural regressions; a maximum of 1000 turns a bug into a financial incident and can overwhelm downstream dependencies.
        - **Corrected standard:** `spread` on AZ then `binpack`; a metric per workload type (`ALBRequestCountPerTarget`, backlog per task, CPU for CPU-bound work) with targets from load tests; short scale-out and long scale-in cooldowns; `100/200` (or `100/150`); circuit breaker plus alarm-based rollback; a justified maximum with an alarm on reaching it.
        - **Legitimate intent, cost:** keep `binpack` as the second sort key, use Spot for tolerant workloads, and `maximumPercent: 150` where surge capacity is constrained.
        - **Legitimate intent, safety and never running out:** keep the circuit breaker as a floor, and keep capacity headroom with an alarm rather than an unbounded ceiling.

# AWS Questions — Solutions, Explanations & Revision Guide


## Question 1

### Question

Define a container image and a container, and state the relationship between them. Explain why the image is described as immutable when a running container can clearly write to its filesystem.

*Beginner — definition. What it tests: whether you can separate the artifact from the process, and whether you know what copy-on-write is.*

### Explanation

A **container image** is a packaged, read-only artifact. It consists of stacked filesystem layers plus a manifest and a configuration object recording the entrypoint, command, environment variables, exposed ports, working directory and user. It is a file sitting in a registry. On its own it does nothing.

A **container** is a running — or stopped — instance of that image: one or more processes on a Linux host, isolated by kernel features, whose root filesystem is assembled from the image's layers.

The relationship is that of class to object, or executable file to process: **one image, many containers**. Ten tasks launched from `myapp:1.4.2` are ten independent sets of processes sharing one identical set of read-only layers.

The apparent contradiction in the second half of the question dissolves once you know how the filesystem is assembled. When a container starts, the runtime stacks the image's read-only layers with a union filesystem (OverlayFS) and adds **one thin writable layer on top**. Every write goes to that top layer only:

- **Create a new file** → written into the writable layer.
- **Modify a file that came from the image** → the file is first *copied up* into the writable layer, then modified there. This is copy-on-write. The image layer is untouched.
- **Delete a file that came from the image** → a *whiteout* marker is written in the writable layer, hiding the path. The bytes remain in the image layer.

### Solution

An image is the immutable, layered artifact; a container is a process whose filesystem is that artifact plus a private writable layer. The image is immutable because nothing ever writes into its layers — writes land in the container's own layer, which is destroyed with the container.

### Why This Is Correct

The immutability claim is about the *artifact*, not about the *view the process sees*. Because the layers are content-addressed and sealed, the same image pulled onto a thousand hosts produces byte-identical filesystems, which is exactly what makes images portable and reproducible. The writable layer is where mutability is confined, and confining it there is why container storage is called **ephemeral** — and therefore why persistent data must go to a volume, Amazon EFS, Amazon S3, or a database.

### Sample Exam Answer

> A container image is a read-only, layered package containing an application, its dependencies and its runtime configuration such as entrypoint, environment variables and user. A container is a running instance of that image — an isolated process on a host whose root filesystem is built from the image's layers. One image can produce many containers.
>
> The image is immutable because a container never writes into the image layers. At start-up the runtime stacks the read-only layers using a union filesystem and adds a thin writable layer on top. New files are created there, existing files are copied up from the image layer before modification (copy-on-write), and deletions are recorded as whiteout markers rather than removing data. The image is therefore unchanged, and the writable layer is discarded when the container is removed — which is why container storage is ephemeral and persistent data must be written to a volume, EFS or an external service.

**Exam tip.** If a question asks where data goes when a container is replaced, the answer is "it is lost unless it was written to a volume or an external service." That follows directly from image immutability.

**Common trap.** Confusing "the image is read-only" (true) with "the container filesystem is read-only" (false by default). The container filesystem is writable but ephemeral. You can *make* it read-only in ECS with `readonlyRootFilesystem: true`, which is a hardening choice, not the default.

---

## Question 2

### Question

Explain the difference between a tag and a digest, and give two specific operational consequences of deploying by tag rather than by digest.

*Intermediate — conceptual / operational. What it tests: whether you understand that a tag is a mutable pointer while a digest is content-addressed identity.*

### Explanation

A **tag** is a human-readable, mutable label attached to an image in a repository — `myapp:1.4.2`, `myapp:latest`. It is a pointer, and nothing stops a later push from moving it to different content unless the repository enforces tag immutability.

A **digest** is the SHA-256 hash of the image manifest — `myapp@sha256:9c2f…`. It is derived from the content itself. The same digest always means byte-identical content, different content can never share a digest, and a digest can never be moved or reused.

```
myapp:1.4.2   ──(mutable pointer)──▶  sha256:9c2f…  ──▶ layers
myapp:latest  ──(mutable pointer)──▶  sha256:9c2f…
                                        ▲
                               digest = identity, immutable
```

### Reasoning / Analysis

The decision criterion is simple: *does anything downstream need to make a claim about what is running?* Testing, rollback, incident forensics and audit all make such claims. A pointer cannot support a claim, because the thing it points at can change after the claim is made.

### Solution

**Consequence 1 — you cannot state what is running, so rollback and debugging become unreliable.** Two tasks in one ECS service launched an hour apart from `myapp:1.4.2` can be running different code if the tag was re-pushed in between. Rolling back "to 1.4.2" then does not restore the known-good build; it restores whatever `1.4.2` currently points at. The artifact that failed may no longer be retrievable at all.

**Consequence 2 — the artifact you tested is not provably the artifact you deployed.** Testing signs off a digest whether or not the pipeline says so. If staging pulled `1.4.2` at 09:00 and production pulls `1.4.2` at 14:00 after a re-push, every test result is void. The same mechanism breaks scale-out consistency: a service scaling from four to twelve tasks pulls the tag again and can end up running mixed versions behind one load balancer.

The practice that follows: build once, resolve the tag to a digest at the end of the build, and write the **digest** into the ECS task definition. Keep tags for humans and for browsing. Enable **ECR tag immutability** on any repository whose images are deployable.

### Why This Is Correct

Content addressing is what converts "I believe this is version 1.4.2" into "this is provably the bytes we tested." Every downstream guarantee — reproducible deployments, meaningful rollback, defensible audit evidence — is built on that one property, which is why Q11, Q12 and Q15 all return to it.

### Sample Exam Answer

> A tag is a mutable, human-readable pointer to an image, such as `myapp:1.4.2`; a digest is the SHA-256 hash of the image manifest, such as `myapp@sha256:…`, and is therefore an immutable, content-addressed identity. A tag can be re-pushed to point at different content; a digest cannot.
>
> Deploying by tag means, first, that you cannot say with certainty which code is running, so rollback and incident investigation are unreliable — rolling back to `1.4.2` restores whatever that tag now points at. Second, the artifact validated in test is not provably the artifact deployed to production, and a service that scales out later can pull different content and run mixed versions behind one load balancer.
>
> The fix is to deploy by digest and to enable tag immutability in Amazon ECR.

**Exam tip.** Any question containing "must be able to prove", "reproducible", "identical across environments" or "roll back to a known state" is pointing at digests.

---

## Question 3

### Question

Name the three Linux kernel mechanisms that make containers possible and state, for each, one architectural consequence that follows from it.

*Intermediate — conceptual (OS internals). What it tests: whether you know a container is a kernel feature rather than a virtual machine, and whether you can reason forward from that.*

### Explanation

**(i) Namespaces — isolation of what a process can *see*.** Separate namespaces exist for PID, mount, network, UTS (hostname), IPC, user and cgroup. Each container gets its own set, so its processes see their own process tree, mounts and network stack.

*Architectural consequence:* the container has its own network namespace and therefore its own network identity. In ECS `awsvpc` mode this is why each task receives its own elastic network interface and VPC IP address, can be registered directly in an ALB target group, and can carry its own security group. It is also why `localhost` inside a container means *that container* — containers in the same task share a network namespace and can talk over `localhost`, while containers in different tasks cannot. A second consequence: PID namespacing makes your process PID 1, so it inherits init duties such as signal handling and zombie reaping, which is why a shell-form `CMD` that never forwards `SIGTERM` makes ECS shutdowns hang until `stopTimeout` expires.

**(ii) Control groups (cgroups) — limitation and accounting of what a process can *consume*.** cgroups cap and meter CPU, memory, block I/O and process counts per group.

*Architectural consequence:* resource limits are kernel-enforced and **asymmetric**. Exceeding the memory limit gets the process OOM-killed — in ECS the task stops with `OutOfMemoryError: Container killed due to memory usage`. Exceeding the CPU limit gets the process *throttled*, not killed, which surfaces as latency rather than as a crash. This is also why runtimes must be cgroup-aware: a JVM that sizes its heap from the host's physical RAM instead of the cgroup limit will be killed.

**(iii) Union / copy-on-write filesystem (OverlayFS) — composition of what a process *reads*.** Read-only image layers are stacked and presented as one filesystem with a writable layer on top.

*Architectural consequence:* layers are shared and cached per host, so image *reuse* is cheap while image *change* is expensive at the changed layer and everything above it. This makes Dockerfile instruction ordering a performance decision, makes deleted files still count toward image size (Q7), and makes container writes slower than native writes because of copy-up — so write-heavy workloads need a volume that bypasses the union filesystem. On Fargate, where nothing is cached between tasks, this consequence becomes a latency budget (Q10, Q14).

### Reasoning / Analysis

A fourth family — capabilities, seccomp, AppArmor/SELinux — restricts what a process may *ask the kernel to do*. Name it if the question is about security. The canonical three, however, are namespaces, cgroups and the union filesystem, and they map cleanly onto *see / consume / read*.

### Solution

The three mechanisms are namespaces, cgroups and the union (copy-on-write) filesystem. Their consequences are, respectively: per-task network identity in `awsvpc` mode and PID 1 signal responsibilities; kernel-enforced, asymmetric resource limits that kill on memory and throttle on CPU; and layer sharing that makes build order, image size and pull time architectural concerns.

### Why This Is Correct

All three operate on the **shared host kernel**. There is no per-container kernel. Three things follow, and they are the point of the question: a container cannot run a different OS kernel than its host; a kernel vulnerability is a shared risk across every container on that host; and container isolation is weaker than VM isolation — which is precisely why AWS Fargate places every task in its own single-tenant microVM.

### Sample Exam Answer

> **Namespaces** isolate what a process can see — PID, mount, network, UTS, IPC and user. Consequence: each container has its own network stack, so in ECS `awsvpc` mode each task gets its own ENI, IP address and security group, and containers within one task share `localhost`.
>
> **cgroups** limit and account for what a process can consume — CPU, memory and I/O. Consequence: limits are kernel-enforced and asymmetric — exceeding memory causes an OOM kill, whereas exceeding CPU causes throttling and latency — so runtimes such as the JVM must size themselves from the cgroup limit rather than host RAM.
>
> **The union / copy-on-write filesystem (OverlayFS)** stacks read-only image layers under a thin writable layer. Consequence: layers are shared and cached, so instruction ordering determines rebuild and pull cost, deleted files still occupy the image, and write-heavy workloads need volumes.
>
> All three rely on the shared host kernel, so containers isolate processes rather than machines — which is why Fargate runs each task in its own microVM.

**Common trap.** Describing a container as "a lightweight VM." A VM virtualises hardware and runs its own kernel; a container is a set of ordinary host processes with restricted visibility and capped resources. Every isolation and compatibility limit follows from that single difference.

---

## Question 4

### Question

Explain what a multi-stage Dockerfile is and list three distinct benefits, at least one of which is not about image size.

*Beginner — conceptual / build. What it tests: understanding of build-time versus run-time separation.*

### Explanation

A multi-stage Dockerfile contains more than one `FROM` instruction. Each `FROM` begins a new stage with its own base image and its own filesystem. A later stage can copy selected files out of an earlier one with `COPY --from=<stage>`. Only the **final stage** becomes the image; every earlier stage is discarded.

```dockerfile
# Stage 1: build — needs JDK, Maven, source, test dependencies
FROM public.ecr.aws/docker/library/maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B dependency:go-offline        # cached unless pom.xml changes
COPY src ./src
RUN mvn -B package

# Stage 2: runtime — needs only a JRE and the jar
FROM public.ecr.aws/docker/library/eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /src/target/app.jar ./app.jar
USER 1001
ENTRYPOINT ["java","-jar","/app/app.jar"]
```

### Solution

**Benefit 1 — a smaller runtime image.** The JDK, Maven, the dependency cache, the source tree and the test artifacts stay in stage 1 and never ship. A typical Java image falls from roughly 700 MB to roughly 200 MB, which shortens every pull.

**Benefit 2 — reduced attack surface and fewer CVEs to triage** *(not a size argument)*. The shipped image contains no compiler, no build tooling, no package manager and no source code. What is not in the image cannot be exploited in the image, and it cannot appear in a vulnerability report you are then obliged to triage and patch.

**Benefit 3 — a reproducible, self-contained build definition** *(also not a size argument)*. Compiler version, dependency resolution and packaging are pinned inside the Dockerfile, so a developer laptop, a CI runner and a rebuild next year all produce the same result. The CI host needs only a container runtime, not a matching JDK and Maven installation.

A fourth, if the question invites it: credentials needed during the build — private registry tokens, SSH keys — can be confined to a discarded stage rather than shipped. Q7 gives the mechanism that does this properly.

### Why This Is Correct

The three benefits are genuinely distinct because they arise from different properties of the mechanism. Smaller images come from *discarding stages*; reduced attack surface comes from *what the final stage contains*; reproducibility comes from *the toolchain being declared rather than assumed*. A weak answer restates the first benefit three times.

### Sample Exam Answer

> A multi-stage Dockerfile uses several `FROM` instructions; each starts a new stage, and the final stage copies only the artifacts it needs from earlier stages using `COPY --from=`. Earlier stages are discarded and never shipped.
>
> Three benefits: first, a much smaller runtime image, since compilers, build tools, caches and source remain in the build stage; second, a smaller attack surface and fewer CVEs to triage, because the runtime image contains no compiler, package manager or source code; and third, a reproducible, self-contained build, because toolchain versions are pinned inside the Dockerfile so CI hosts and developer machines produce the same artifact without installing build tooling.

**Exam tip.** Order instructions from least-changing to most-changing — dependency manifest, then dependencies, then source — so the expensive dependency layer stays in cache when only application code changes.

---

## Question 5

### Question

State the difference between an ECS task and an ECS service, and give one example of work that is correctly run as each.

*Beginner — definition / comparison. What it tests: whether you can separate a unit of execution from a supervision mechanism.*

### Explanation

A **task** is one running instance of a task definition — one or more containers scheduled together on the same host, sharing a network namespace and, in `awsvpc` mode, one ENI. It is the unit of work. It runs, it exits, and nothing brings it back.

A **service** is a long-running controller that maintains a desired number of tasks. It replaces tasks that stop or fail health checks, registers tasks with a load balancer target group, integrates with Application Auto Scaling, performs rolling or blue/green deployments, and can roll back automatically through the deployment circuit breaker. The service does not run your code — it keeps tasks running.

| | Task | Service |
|---|---|---|
| Nature | A unit of execution | A controller that maintains tasks |
| Lifetime | Runs until the process exits | Runs indefinitely |
| On exit | Stays stopped | A replacement task is launched |
| Started by | `RunTask`, or a scheduled rule | `CreateService` / `UpdateService` |
| Load balancer | Not registered | Registered with a target group |
| Auto scaling, rolling deploys | No | Yes |

### Solution

**Correctly a task:** a nightly database migration, a batch report, or an ETL job triggered by Amazon EventBridge. It should run once, do its work, exit zero and *stay* stopped.

**Correctly a service:** a public HTTPS API behind an Application Load Balancer. It must always have N healthy tasks, must be replaced automatically when a task dies or an Availability Zone degrades, and must scale with traffic.

### Why This Is Correct

The distinction is between *doing work* and *guaranteeing work is being done*. Finite work has a natural end, so supervision is wrong for it. Continuous work has no natural end, so supervision is exactly what it needs.

### Why the Alternatives Are Less Suitable

Running a finite job as a service inverts the model: the service controller observes a task that exited and treats it as a failure, so a *successful* batch job restarts endlessly. Conversely, running a web API as a standalone task means the first crash, deployment or AZ event takes the API offline permanently, with no load-balancer registration and no scaling.

### Sample Exam Answer

> An ECS task is a single running instance of a task definition — the unit of execution. An ECS service is a controller that keeps a desired number of tasks running, replaces unhealthy or stopped tasks, registers them with a load balancer target group, and manages rolling deployments and auto scaling.
>
> A nightly batch job or database migration is correctly run as a standalone task, because it should run to completion and stay stopped. A customer-facing web API is correctly run as a service, because it must remain continuously available, be load balanced and scale with demand.

**Common trap.** Running a finite job as a service, which restarts a successful job forever. Use `RunTask` — via EventBridge Scheduler or AWS Step Functions — for finite work.

---

## Question 6

### Question

An ECS task in a private subnet fails with `CannotPullContainerError`. List four distinct possible causes, state how you would distinguish them from one another, and give the remedy for each.

*Intermediate — troubleshooting / networking / security. What it tests: whether you can trace the pull path — identity, DNS, route, authorisation, content — and read the error text as diagnostic evidence.*

### Explanation

An image pull is not one operation. It uses the **task execution role** (not the task role), authenticates to Amazon ECR, and touches two ECR endpoints plus Amazon S3:

```
Execution role credentials
   ↓  ecr:GetAuthorizationToken
api.ecr.<region>.amazonaws.com     ← ECR API: auth, manifest
   ↓  ecr:BatchGetImage, ecr:GetDownloadUrlForLayer
dkr.ecr.<region>.amazonaws.com     ← Docker Registry API: pull
   ↓  layer blobs
S3 (prod-<region>-starport-layer-bucket)  ← the actual layer bytes
```

Break any link and you get `CannotPullContainerError` — but with *different message text*, and that text is the diagnostic.

### Reasoning / Analysis

The four causes group into four subsystems: **network path**, **identity**, **content** and **security controls**. Two of them (network path and security controls) both present as timeouts, so they must be separated by inspecting configuration rather than by reading the message.

**Cause 1 — no network path out of the private subnet.** The subnet has no route to the internet and no VPC endpoints, so ECR is unreachable.
*Distinguish:* the stopped-task reason contains a **timeout** — typically `dial tcp … i/o timeout` against `api.ecr.<region>.amazonaws.com`. Confirm by checking whether the route table has a `0.0.0.0/0` entry to a NAT gateway and whether the interface endpoints exist.
*Remedy:* add a NAT gateway with a route from the private subnet, or — cheaper and more private — create interface endpoints for `com.amazonaws.<region>.ecr.api` and `com.amazonaws.<region>.ecr.dkr`, **a gateway endpoint for Amazon S3**, and an interface endpoint for `com.amazonaws.<region>.logs` if using the `awslogs` driver. The S3 gateway endpoint is not optional: AWS documentation states it is required because ECR stores image layers in S3, so the manifest is fetched from ECR and the layers from S3.

**Cause 2 — the task execution role is missing or under-permissioned.** The task definition has no `executionRoleArn`, or the role lacks `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:GetDownloadUrlForLayer` and `ecr:BatchGetImage` — or the ECR **repository policy** denies the principal, or a KMS key policy blocks decryption of an encrypted repository.
*Distinguish:* the message is an explicit authorisation failure — `AccessDeniedException`, `not authorized to perform: ecr:GetAuthorizationToken`, or a 403. AWS CloudTrail shows the denied call and the exact principal, which also tells you whether the denial is identity-side or resource-side.
*Remedy:* attach `AmazonECSTaskExecutionRolePolicy`, or an equivalent least-privilege policy scoped to the specific repository ARNs, reference it as `executionRoleArn`, and correct the repository or KMS key policy if the denial is resource-side.

**Cause 3 — the image or tag does not exist at the URI given.** Wrong account ID, wrong Region in the URI, repository never created, tag never pushed, or an architecture mismatch such as an `arm64`-only image on an `X86_64` task.
*Distinguish:* the message names *content*, not network or identity — `manifest for … not found`, `repository does not exist`, or `no matching manifest for linux/amd64`. Confirm with `aws ecr describe-images --repository-name <r> --image-ids imageTag=<t>`.
*Remedy:* correct the URI, push the missing image, or build a multi-architecture image and match the task definition's `cpuArchitecture`.

**Cause 4 — traffic is blocked by security controls even though a route exists.** The task security group has no outbound 443; the *endpoint's* security group does not allow inbound 443 from the task security group; a network ACL blocks ephemeral return ports; private DNS is disabled on the interface endpoint, or `enableDnsSupport`/`enableDnsHostnames` are off, so `api.ecr…` resolves to a public address; or a restrictive VPC endpoint policy denies the ECR actions.
*Distinguish:* like Cause 1 this usually presents as a timeout, so separate them structurally — if the route table and endpoints are present, the fault is a security group, NACL, DNS or endpoint policy. VPC Flow Logs showing `REJECT` on port 443 pinpoint a security group or NACL; accepted flows with no reply plus DNS resolving to a public IP indicate a private-DNS problem; an endpoint policy denial appears as an authorisation error rather than a timeout.
*Remedy:* allow egress 443 from the task security group, allow inbound 443 on the endpoint security group from the task security group, permit ephemeral return traffic in the NACL, enable private DNS together with the VPC DNS attributes, and widen the endpoint policy.

**Two further causes worth naming for full marks.** Docker Hub or other public-registry **rate limiting** (`toomanyrequests: You have reached your pull rate limit`), remedied with `repositoryCredentials` backed by AWS Secrets Manager or by mirroring through an ECR pull-through cache; and a **private third-party registry without credentials** (`no basic auth credentials`), remedied with `repositoryCredentials` plus `secretsmanager:GetSecretValue` and KMS decrypt on the *execution* role.

### Solution

```
Read the exact stopped-task reason
        ↓
Timeout?           → network:  route table → NAT / VPC endpoints (incl. S3) → SG → NACL → DNS
Access denied?     → identity: execution role → repository policy → KMS → endpoint policy
Not found?         → content:  account, Region, repository, tag, architecture
Rate limited?      → registry: upstream credentials or ECR pull-through cache
```

### Why This Is Correct

The method works because each subsystem fails with a characteristically different signal, and because the pull path is short enough to trace end to end. Guessing — "it's probably the security group" — fails roughly three times out of four; reading the message first narrows four causes to one or two immediately.

### Sample Exam Answer

> Four causes. First, no network path: the private subnet has neither a NAT gateway route nor VPC endpoints for `ecr.api`, `ecr.dkr` and the S3 gateway endpoint. Second, the task **execution** role is missing or lacks `ecr:GetAuthorizationToken`, `BatchGetImage` and `GetDownloadUrlForLayer`, or the repository policy denies it. Third, the image or tag does not exist at that URI, or the image architecture does not match the task. Fourth, traffic is blocked despite a route — no outbound 443 on the task security group, no inbound 443 on the endpoint security group, a NACL blocking return traffic, or private DNS disabled.
>
> I would distinguish them from the stopped-task reason: timeouts indicate the first or fourth, separated by inspecting route tables and endpoints versus security groups, NACLs, DNS and VPC Flow Logs; `AccessDenied` on an `ecr:` action indicates the second, confirmed in CloudTrail; `manifest not found` or `repository does not exist` indicates the third, confirmed with `aws ecr describe-images`.
>
> Remedies respectively: create the VPC endpoints including the S3 gateway endpoint, or add a NAT gateway; attach a correct execution role and fix repository and KMS policies; correct or push the image and match the architecture; and open port 443 on both the task and endpoint security groups and enable private DNS.

**Exam tip.** The pull is performed with the **execution** role, never the task role. Any failure at *start-up* — image pull, secret injection, log driver — points at the execution role; failures inside application code point at the task role.

**Common trap.** Creating `ecr.api` and `ecr.dkr` endpoints but omitting the **S3 gateway endpoint**. Authentication and manifest retrieval succeed and then the layer download hangs, which reads like an intermittent network fault rather than a missing endpoint.

---

## Question 7

### Question

Explain why a file deleted in a later Dockerfile layer still occupies space in the image, and describe the correct mechanism for using a credential during a build without it entering the image.

*Intermediate — conceptual / security. What it tests: whether you understand that layers are additive and sealed, and whether you know the modern build-secret mechanism rather than the folklore.*

### Explanation

Each Dockerfile instruction that changes the filesystem produces a new, immutable layer containing only that instruction's changes. Layers are stacked, never rewritten, and each is distributed as its own blob. An image is the *sum* of its layers.

Deleting a file in a later layer therefore cannot remove it from an earlier one — that layer is already sealed and may already be shared with other images. Instead a **whiteout entry** is written in the later layer, which hides the path when the layers are merged. The original bytes still ship, still count toward image size, still get pulled, and can be extracted by anyone holding the image:

```dockerfile
COPY id_rsa /tmp/id_rsa                  # layer 3: contains the key   ← ships
RUN git clone … && rm /tmp/id_rsa        # layer 4: whiteout entry     ← key still in layer 3
```

`docker history`, `docker save` and any registry client will reveal it. The same applies to `ARG` values, which are recorded in the image configuration.

### Reasoning / Analysis

There are only three ways to keep something out of the shipped image, and they all amount to *never creating the layer*:

1. Never bring the file into the build context at all.
2. Create and delete it **within a single `RUN`**, so the layer is committed already-clean: `RUN curl … && make && rm -rf /tmp/build`.
3. Produce it in a stage that is discarded, and copy only the wanted output forward with `COPY --from=build`.

### Solution

For credentials the correct mechanism is a **BuildKit build secret**. The secret is mounted into the build as a tmpfs file for the duration of one `RUN` instruction only. It never enters a layer, never appears in image history, and is never written to the build cache.

```dockerfile
# syntax=docker/dockerfile:1
FROM public.ecr.aws/docker/library/node:22-alpine AS build
WORKDIR /src
COPY package*.json ./
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci --omit=dev
COPY . .
RUN npm run build
```

```bash
DOCKER_BUILDKIT=1 docker build --secret id=npmrc,src=$HOME/.npmrc -t myapp:1.4.2 .
```

For Git over SSH the equivalent is `RUN --mount=type=ssh …` with `docker build --ssh default`, which forwards the agent socket without copying the key.

In an AWS pipeline the secret originates in **AWS Secrets Manager or AWS Systems Manager Parameter Store**, is injected into AWS CodeBuild through the buildspec `secrets-manager` block or fetched by the build role, and is then passed to `docker build --secret` — never as `--build-arg`, and never copied in.

### Why the Alternatives Are Less Suitable

| Approach | Why it fails |
|---|---|
| `COPY secret .` then `RUN … && rm secret` | The secret is permanently in an earlier layer |
| `ARG TOKEN` with `--build-arg` | Recorded in the image configuration and visible in `docker history` |
| `ENV TOKEN=…` | Present in the image configuration *and* in every container's environment at run time |
| Squashing layers to "hide" it | Reduces evidence, not exposure; the credential must still be treated as compromised |

**Runtime credentials are a separate problem with a separate answer.** Never bake them at all. In ECS, use the task definition's `secrets` block to inject values from Secrets Manager or Parameter Store at task start — fetched by the **execution** role — or, better, give the task an IAM **task role** so the application obtains short-lived credentials and there is no static secret to leak.

### Sample Exam Answer

> Image layers are immutable and additive. Deleting a file in a later instruction does not modify the earlier layer; it writes a whiteout entry that hides the path when layers are merged. The original bytes remain in the earlier layer, are still shipped and pulled, and remain extractable through `docker history` or `docker save` — so no space is reclaimed and a secret placed there is compromised.
>
> The correct mechanism is a BuildKit build secret: `RUN --mount=type=secret,id=<id>,target=<path> …` invoked with `docker build --secret id=<id>,src=<file>`. The secret is mounted as tmpfs for that instruction only and never enters a layer, the image history or the build cache; `--mount=type=ssh` does the same for SSH keys. Build arguments and `ENV` are not acceptable because both are recorded in the image configuration. Runtime secrets should instead come from the ECS `secrets` block backed by Secrets Manager or Parameter Store, or preferably from an IAM task role.

**Common trap.** Believing that a secret removed in a later `RUN`, or hidden by squashing, is safe. Once it has been in a pushed layer it must be rotated.

---

## Question 8

### Question

Compare the task execution role, the task role, and the container instance role. For each, state what assumes it, when, and what a compromise of that identity would grant an attacker.

*Intermediate — comparison / security. What it tests: whether you can separate platform identity from application identity from host identity — the most common ECS IAM confusion.*

### Explanation

Three identities exist because three different actors need AWS permissions at three different moments.

| | Task execution role | Task role | Container instance role |
|---|---|---|---|
| Assumed by | The ECS agent / Fargate infrastructure (`ecs-tasks.amazonaws.com`) | Your application code inside the container (`ecs-tasks.amazonaws.com`) | The EC2 container instance, via an instance profile (`ec2.amazonaws.com`) |
| When | Before and during task start-up | Continuously, while the application runs | Continuously, from instance boot |
| Purpose | Pull the image, fetch secrets for injection, write logs, attach EFS and ENI plumbing | Whatever the application must do: S3, DynamoDB, SQS, KMS | Register with the cluster, poll for work, report task and instance state |
| Typical policy | `AmazonECSTaskExecutionRolePolicy` | Application-specific, least privilege | `AmazonEC2ContainerServiceforEC2Role` |
| Launch types | Fargate and EC2 | Fargate and EC2 | **EC2 only** — on Fargate you own no host |
| Reachable from inside the container | No | **Yes**, via the credentials endpoint at `169.254.170.2` | Only if the container can reach IMDS at `169.254.169.254` |

### Reasoning / Analysis

**Task execution role — compromise.** An attacker able to use it can pull every image the role permits, disclosing source code and business logic, and — more seriously — **read every secret referenced by task definitions it can launch**, because that role is what resolves `secrets` entries from Secrets Manager and Parameter Store. It can also write to log groups. It is not normally reachable from inside a container, so the realistic path is someone holding `ecs:RegisterTaskDefinition` plus `ecs:RunTask` plus `iam:PassRole`, who can craft a task definition that injects any secret the role can read and then exfiltrate it. *Control:* scope the role to the specific repository and secret ARNs each service actually uses, use one execution role per service family rather than one account-wide role, and constrain `iam:PassRole` tightly.

**Task role — compromise.** This is the identity most exposed to application-level attack. An SSRF, an RCE or a malicious dependency inside the container can read `$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` from `169.254.170.2` and obtain temporary credentials carrying exactly the application's permissions. The attacker then gets whatever the application can do — read the bucket, write the table, decrypt with KMS — and if the role is over-broad, such as `s3:*` on `*`, the entire data estate. *Control:* least privilege scoped to specific resource ARNs with condition keys, one task role per service, no wildcard resources, and no `iam:*` or `sts:AssumeRole` unless genuinely required.

**Container instance role — compromise.** The widest blast radius, and it exists only on the EC2 launch type. It is a **host- and cluster-level** identity: it registers the instance, polls the ECS control plane for task payloads, and reports state. An attacker holding it can act as a cluster member — receive task payloads that may include other tasks' configuration, deregister instances — and can use any additional permission an over-broad instance profile carries. Crucially, **any container on that host able to reach IMDS can steal it**, so one compromised container escalates from its own task role to the host role and therefore to every co-located task. *Control:* require IMDSv2 with a hop limit of 1, use `awsvpc` network mode and block container access to `169.254.169.254`, keep the instance profile minimal — or, structurally, use **Fargate**, which removes the identity entirely.

### Solution

```
Compromised application  →  task role       (this service's permissions)
                         →  instance role   (all tasks on this host, cluster access)  ← EC2 only
                         →  lateral movement across the cluster
```

Fargate cuts that chain after the first step. That is a security argument for Fargate that stands independently of any operational-overhead argument.

### Why This Is Correct

The comparison is meaningful because the three roles differ along the axis that matters for security — *who can reach the credentials*. The execution role is reachable only through the control plane, the task role is reachable from inside your application, and the instance role is reachable from anything on the host. Blast radius follows reachability, not policy size.

### Sample Exam Answer

> The **task execution role** is assumed by the ECS or Fargate agent on your behalf at task start-up, to pull the image from ECR, retrieve secrets referenced in the task definition, and send logs to CloudWatch. Compromise gives an attacker your images and, more importantly, the secrets those task definitions inject.
>
> The **task role** is assumed by the application inside the container, which obtains temporary credentials from the container credentials endpoint at `169.254.170.2`. Compromise — through SSRF, RCE or a malicious dependency — grants exactly the application's AWS permissions, so an over-broad task role turns one application bug into a data breach.
>
> The **container instance role** is the EC2 instance profile on ECS container instances, and applies to the EC2 launch type only. The ECS agent uses it to register the instance and poll for tasks. Compromise is host- and cluster-level: the attacker can receive task payloads for other tasks and use every permission on the instance profile, and any container able to reach IMDS can obtain it, enabling lateral movement between co-located tasks.
>
> Controls: least privilege and per-service roles for the first two; IMDSv2 with hop limit 1, `awsvpc` mode and a minimal instance profile for the third — or Fargate, which eliminates it.

**Exam tip.** "The task cannot start" → execution role. "The application gets `AccessDenied` from an AWS API" → task role. "The instance does not appear in the cluster" → container instance role.

---

## Question 9

### Question

Your organisation's ECR storage cost has tripled in a year with no change in the number of services. Describe your investigation, the most likely finding, and a lifecycle policy that fixes it. State one risk of an aggressive lifecycle policy.

*Intermediate — cost optimisation / operations. What it tests: whether you know what ECR actually charges for, and whether you can connect a cost signal to a pipeline behaviour.*

### Explanation

ECR bills for **storage per GB-month**, plus data transfer out and cross-Region replication transfer. It does **not** bill per push or per pull within the same Region. So a tripling of cost with a constant service count means stored bytes tripled: the pipeline is adding images faster than anything removes them. Nothing in ECR deletes images by default.

### Reasoning / Analysis — the investigation

1. **Confirm the cost shape.** In AWS Cost Explorer, filter to Amazon ECR and group by *usage type*, confirming growth in `TimedStorage-ByteHrs` rather than data transfer. If it is data transfer, the cause is cross-Region pulls or a missing S3 gateway endpoint, and a lifecycle policy is the wrong instrument entirely.
2. **Attribute it per repository.** Tag repositories by service and team, and activate cost allocation tags. In the interim, enumerate directly:

```bash
for r in $(aws ecr describe-repositories --query 'repositories[].repositoryName' --output text); do
  size=$(aws ecr describe-images --repository-name "$r" \
          --query 'sum(imageDetails[].imageSizeInBytes)' --output text)
  count=$(aws ecr describe-images --repository-name "$r" \
          --query 'length(imageDetails)' --output text)
  printf '%10s GB  %5s images  %s\n' "$(echo "scale=1;$size/1024/1024/1024" | bc)" "$count" "$r"
done
```

Treat this as an indicator rather than a bill: shared layers are stored once but counted once per image by this sum, so it over-reports.

3. **Characterise the growth.** For the worst repositories, examine image count over time, the ratio of **untagged** to tagged images, the image-size trend, and whether any lifecycle policy exists at all (`aws ecr get-lifecycle-policy`).

### Solution — the most likely finding

Every CI build pushes an image and nothing ever deletes one. Concretely:

- One image per commit, tagged with the Git SHA, at perhaps forty builds a day and 400–800 MB each.
- A large population of **untagged** images: each re-push of a moving tag such as `latest` or `dev` orphans the previously tagged manifest, which then sits untagged, hidden behind the console's default filter, and fully billable.
- Frequently compounded by registry build caches (`--cache-to type=registry`), multi-architecture manifests, and attestation or SBOM artifacts, all of which multiply stored bytes per logical release.
- No lifecycle policy anywhere.

Growth is therefore linear in build rate, and a tripling in a year is the arithmetic outcome of a year of unmanaged accumulation rather than an anomaly.

### Solution — the lifecycle policy

Rules are evaluated in `rulePriority` order, lowest first, and a rule with `tagStatus: any` must carry the highest priority value, meaning it is evaluated last.

```json
{
  "rules": [
    {
      "rulePriority": 10,
      "description": "Keep the last 20 release images",
      "selection": {
        "tagStatus": "tagged",
        "tagPatternList": ["release-*", "v*"],
        "countType": "imageCountMoreThan",
        "countNumber": 20
      },
      "action": { "type": "expire" }
    },
    {
      "rulePriority": 20,
      "description": "Keep the last 10 development images",
      "selection": {
        "tagStatus": "tagged",
        "tagPatternList": ["dev-*", "pr-*"],
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": { "type": "expire" }
    },
    {
      "rulePriority": 30,
      "description": "Expire untagged images after 14 days",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 14
      },
      "action": { "type": "expire" }
    }
  ]
}
```

Apply it with `aws ecr put-lifecycle-policy` — but **always run `aws ecr start-lifecycle-policy-preview` first**. The preview lists exactly which images the policy would remove and is the only safe way to deploy a deletion rule.

Where images must be retained for audit rather than for deployment, a lifecycle rule can use the `transition` action with `targetStorageClass: archive` instead of `expire`, moving images to cheaper archive storage while keeping the evidence. ECR also supports `sinceImageTransitioned` as a `countType`, so archived images can be expired on their own schedule.

**Complementary measures.** Enable tag immutability so re-pushes fail rather than silently orphaning manifests; stop pushing an image for every commit on every feature branch; use multi-stage builds, since a 700 MB → 200 MB reduction cuts the bill by the same factor as deleting two-thirds of the images; and keep registry build caches in a separate repository with an aggressive short-lived policy.

### Why This Is Correct

The policy targets the actual generator of bytes rather than the symptom. Untagged images are usually the largest single category and are the direct product of moving tags, so expiring them by age reclaims most of the cost immediately. Count-based rules on release tags then bound future growth without reference to how often the pipeline runs.

### Why the Alternatives Are Less Suitable

A single blanket rule such as "expire everything older than 30 days" is simpler but destroys release history and rollback targets alongside the noise. Manual periodic clean-up does not scale and re-creates the problem the moment someone stops doing it. Reducing build frequency treats a healthy engineering practice as the defect.

### The risk of an aggressive policy

**You can delete an image that is still needed — most damagingly, one that a running service will need again.** ECS holds no reference. If a policy removes the digest a service is deployed on, existing tasks keep running, but every scale-out event, task replacement and AZ recovery then fails with `CannotPullContainerError`. The failure appears at the worst possible moment — under load, or during recovery — and looks like a networking incident. Rollback suffers equally: a retention window shorter than your realistic rollback horizon means the version you want no longer exists. In regulated environments, deletion also destroys audit evidence.

*Mitigations:* preview before applying; set retention comfortably longer than the rollback horizon; exempt release-tagged images with a generous count rule at low priority; never make a `tagStatus: any` expire rule your only rule; and archive rather than expire where retention obligations exist.

### Sample Exam Answer

> ECR charges for stored GB-months, so a tripling with a constant service count means stored bytes tripled. I would confirm in Cost Explorer that the growth is in ECR storage rather than data transfer, attribute it per repository using repository tags and `describe-images`, and check whether any lifecycle policies exist.
>
> The most likely finding is that CI pushes an image per commit and nothing deletes them, with a large population of untagged manifests orphaned by repeated pushes to moving tags such as `latest`, plus registry build caches — all growing linearly with build rate.
>
> The fix is a lifecycle policy that keeps the last N release-tagged images, keeps a smaller number of development images, and expires untagged images after around 14 days, deployed only after running a lifecycle policy preview. Tag immutability and multi-stage builds address the causes rather than the symptom.
>
> The risk of an aggressive policy is deleting an image that a deployed service still needs, or that is required for rollback or audit: running tasks continue, but scale-out, task replacement and recovery then fail with `CannotPullContainerError`. Mitigate by previewing, retaining longer than the rollback window, exempting release tags, and transitioning to archive storage rather than expiring where retention is required.

**Common trap.** Assuming the ECR console's default view shows everything. Untagged images are frequently the majority of billed bytes and sit behind a filter.

---

## Question 10

### Question

Explain why image size is described in this chapter as a performance and reliability property rather than as housekeeping. Include the specific metric you would use to measure the effect and where you would obtain it.

*Advanced — performance / reliability. What it tests: whether you can connect a build-time artifact property to run-time system behaviour, and whether you can name a real measurement rather than gesture at "monitoring".*

### Explanation

"Housekeeping" implies image size affects tidiness and storage cost — real concerns, but ones that can be deferred indefinitely. That framing is wrong on managed compute, for a specific documented reason: **on AWS Fargate every task runs on its own single-use, single-tenant instance, and container images and layers are not cached on that instance, so the whole image is pulled from the registry for every single task.** Image size is therefore not a property of an artifact at rest; it is a term in the latency of every capacity change.

### Reasoning / Analysis

**Why it is a performance property.** Pull time sits on the critical path of task start-up, and therefore on the critical path of:

- **Scale-out.** Between the scaling decision and serving capacity, the image must be fetched and decompressed. A larger image widens the window in which demand exceeds capacity — the window where users see latency and errors. Q14 decomposes this.
- **Deployment velocity.** Every rolling deployment launches N replacement tasks, each paying the pull cost, so both deployment duration and the mixed-version window scale with image size.
- **Rollback speed.** A rollback is a deployment. Image size is a direct term in mean time to recovery.

Decompression, not only download, is part of the cost — which is why AWS recommends the more performant **zstd** compression algorithm and, for images larger than about 250 MB, **Seekable OCI (SOCI)** lazy loading on Fargate, which starts the container before all layers have been fetched.

**Why it is a reliability property.**

1. **Recovery time is availability.** When a task, host or AZ fails, the system's response is to launch replacements. Availability during failure is a function of how quickly replacements become healthy, and the pull is part of that. A system that takes two minutes to replace a task has a materially worse availability profile than one that takes twenty seconds, with identical redundancy on paper.
2. **More bytes means more exposure during the pull.** Longer transfers mean more opportunity for transient network failures, NAT gateway throughput limits, registry throttling and cross-AZ variance — and this exposure peaks exactly when many tasks are pulling at once, which is during a scale-out or an incident. The failures correlate with the moments you can least afford them.
3. **Correlated demand on shared infrastructure.** Forty tasks concurrently pulling a 900 MB image through one NAT gateway is a self-inflicted bandwidth event. This is also the practical argument for ECR interface endpoints plus the S3 gateway endpoint.
4. **Attack surface and patch burden.** Every extra package is a potential CVE requiring triage and patching. A fat base image turns a routine security advisory into unplanned work across every service that uses it — an operational reliability cost even when nothing is exploited.

### Solution — the metric and its source

The direct measurement is **image pull duration per task = `pullStoppedAt` − `pullStartedAt`**, exposed on the ECS task object:

```bash
aws ecs describe-tasks --cluster prod --tasks <task-arn> \
  --query 'tasks[0].{created:createdAt,pullStart:pullStartedAt,pullStop:pullStoppedAt,started:startedAt}'
```

Because `describe-tasks` is only useful while the task record still exists, the durable approach is to capture **ECS Task State Change events from Amazon EventBridge** — the event detail carries `createdAt`, `pullStartedAt`, `pullStoppedAt` and `startedAt` — into CloudWatch Logs or S3, and to track **p50 and p95 pull duration per service and per image digest** over time. Correlate that against compressed image size from `aws ecr describe-images --query 'imageDetails[].imageSizeInBytes'`.

The surrounding measurements that make it meaningful:

- **Total time to healthy** — target-group registration time minus `createdAt` — decomposed into pull, application start (`startedAt` to first healthy) and health-check confirmation. This shows what fraction of start-up latency image size actually owns, and stops you optimising the wrong term.
- **ALB `TargetResponseTime`, `HTTPCode_ELB_5XX_Count` and `RejectedConnectionCount`** during scale-out windows, where the user-visible cost of slow starts appears.
- **Deployment duration** from ECS deployment events, and **MTTR** for rollbacks.

### Why This Is Correct

The reframing is justified by a platform fact, not by a preference: no caching between Fargate tasks means the pull is paid every time, so the artifact's size is a recurring run-time cost rather than a one-off storage cost. And the metric is defensible because it is measured rather than modelled — `pullStoppedAt − pullStartedAt` is the actual duration of the actual operation, per task, retained durably through EventBridge.

### Why the Alternatives Are Less Suitable

Measuring only image size in megabytes tells you about the artifact and nothing about the system. Measuring only total task start-up time tells you the system is slow without attributing the cause. Measuring pull duration alongside total time to healthy does both, and it is the only combination that tells you whether shrinking the image is worth the engineering effort at all.

### Sample Exam Answer

> Image size is a performance and reliability property because on Fargate each task runs on its own single-use instance with no layer caching, so the entire image is pulled on every task launch. Pull time therefore sits on the critical path of scale-out, deployment and rollback: it lengthens the window in which demand exceeds capacity and users see errors, and it lengthens recovery after a task, host or AZ failure, which is an availability property rather than a tidiness one. Larger images also spend longer exposed to transient network and registry failures, concurrent pulls during an incident can saturate a NAT gateway, and more packages mean more CVEs to triage and patch.
>
> I would measure image pull duration per task as `pullStoppedAt` minus `pullStartedAt`, taken from `aws ecs describe-tasks` for ad-hoc checks and captured durably from ECS Task State Change events in EventBridge, tracking p50 and p95 per service and per image digest and correlating with compressed image size from `aws ecr describe-images`. I would also measure total time from `createdAt` to healthy target registration, to confirm what share of start-up latency the image actually accounts for.

**Exam tip.** When "reduce image size" appears among faster-start options, check the launch type first. On Fargate nothing is cached, so every task pays the pull; on ECS on EC2 layers are cached per host, so the second and later tasks on a host pull almost nothing. The correct answer depends on it.

**Common trap.** Optimising the image when the dominant term is application start-up or health-check configuration. A 60-second JVM start and a 30-second health-check interval are not improved by a smaller image — decompose before acting.

---

## Question 11

### Question

A team proposes that their CI pipeline rebuild the image from the same Dockerfile in each environment "so that each environment gets the freshest dependencies". Write the argument you would make in response. Address what is genuinely correct in their reasoning, what the specific failure mode is, what you would do instead, and how you would satisfy the underlying concern about dependency freshness without abandoning build-once-promote-many.

*Advanced — evaluation / release engineering. What it tests: whether you can concede the valid part of a wrong proposal, name the precise failure mode rather than recite a slogan, and satisfy the underlying need by another route.*

### Requirements

The team is implicitly stating three requirements, and any counter-proposal must meet all three:

- **R1** — Deployed artifacts must not carry stale, unpatched dependencies.
- **R2** — The gap between a security fix being published and it running in production must be short.
- **R3** — The build must not be an unreproducible black box.

### Constraints

- The pipeline must still gate releases on tests.
- Rollback and incident investigation must remain possible.
- Whatever is proposed must be operable by the same team, at the same cadence.

### Key Concepts

Content addressing and digests (Q2); build-once-promote-many; configuration as run-time input rather than build-time input; continuous vulnerability rescanning; the distinction between an artifact's *age* and an artifact's *identity*.

### Reasoning / Analysis

**What is genuinely correct in their reasoning.** Three parts of it are right, and the argument fails if you skip them:

1. **Artifact staleness is a real risk.** An image built once and promoted through a long pipeline can be weeks old on arrival in production, carrying base-image and library vulnerabilities patched in the meantime. "Build once" does not, by itself, patch anything.
2. **Rebuilding frequently is genuinely necessary.** The remedy for staleness *is* rebuilding. The team has correctly identified that a pipeline that rebuilds rarely ships old dependencies.
3. **Frequent rebuilds surface build fragility early.** A pipeline that rebuilds often finds a broken upstream package or a withdrawn dependency version quickly, rather than during an emergency patch at two in the morning.

So the disagreement is not about *whether* to rebuild often. It is about *where in the pipeline* the rebuild happens.

**The specific failure mode.** Rebuilding per environment breaks the guarantee that **the artifact you tested is the artifact you deployed** — and the difference is unbounded and invisible.

- Two builds from the same Dockerfile at different times can differ: floating base tags move, unpinned OS packages resolve to whatever is current, transitive dependencies re-resolve, and any network-fetched content can change. **A Dockerfile is a recipe, not a specification.**
- Consequently every staging test result certifies a digest that production never runs. Production runs an artifact **no test has ever executed against**. The suite still passes and still means nothing.
- The gate is inverted: the highest-risk environment receives the *least-validated* artifact, because it is built last and therefore contains the newest, least-exercised dependency versions. Here, "freshest" and "least tested" are the same property.
- Failures become unreproducible. When production breaks you cannot rebuild the failing artifact, because rebuilding produces a *different* image. Forensics and bisection are dead.
- Rollback is undefined — "roll back to the previous version" has no artifact to refer to.
- A compromised upstream package published between the staging build and the production build reaches production without passing through any control. This is the supply-chain attack class that per-environment builds specifically enable.
- Secondary costs: build time multiplied by environment count, and environment-specific build failures that block a release which has already passed its tests.

The single sentence worth memorising: **if the build is not the same artifact, the tests were not tests of the thing you shipped.**

### Best Solution — build once, promote the digest

```
commit ──▶ build ──▶ image + digest sha256:9c2f… ──▶ scan, sign, SBOM
                              │
                              ├──▶ dev         (same digest)
                              ├──▶ staging     (same digest; tests run here)
                              └──▶ production  (same digest, promoted)

environment differences enter only as configuration at run time
```

1. One build per commit, producing one image. Resolve the tag to a digest at build time and carry that digest through the pipeline.
2. Every environment's ECS task definition references the **digest**, never a tag. Enable ECR tag immutability.
3. Environment differences — endpoints, feature flags, credentials, log levels, sizing — are injected at run time through ECS environment variables and the `secrets` block backed by Parameter Store and Secrets Manager. A difference that cannot be expressed as configuration is a design problem to fix, not a reason to rebuild.
4. Promotion is an approval plus a task-definition update, not a rebuild. It should be cheap enough to do several times a day.
5. Scan results, SBOM and provenance are recorded against the digest once and remain valid for every environment.

### Satisfying the freshness concern without abandoning build-once-promote-many

This is the part that actually wins the argument, because it must genuinely solve their problem rather than dismiss it.

1. **Rebuild on a schedule, then promote through the same gates.** A nightly or weekly rebuild of the current release, which then runs the full test suite and is promoted normally, delivers fresher dependencies *and* keeps every artifact tested. Freshness comes from rebuild **frequency**, not rebuild **location**.
2. **Trigger rebuilds on base-image updates.** When the pinned base image publishes a new digest, automatically raise a change that bumps the pin and runs the pipeline. Freshness becomes an event-driven, tested change.
3. **Continuously rescan what is already deployed.** ECR enhanced scanning with Amazon Inspector performs automatic continuous scanning of configured repositories, covering both operating-system and programming-language packages, so a CVE published after the build still raises a finding against the deployed digest. Per-environment rebuilding would not have found it either — the CVE did not exist at build time. This directly answers "but our production image might have a vulnerability we don't know about."
4. **Pin and automate dependency updates.** Lockfiles, base images pinned by digest, and automated update pull requests turn dependency freshness into ordinary reviewed, tested code changes with an audit trail.
5. **Set an explicit SLA and measure it.** For example: critical CVEs patched and deployed within seven days; median artifact age in production under fourteen days. Publish the numbers. That makes freshness a managed property with evidence, which is far stronger than the implicit and unverifiable freshness their proposal offers.

### Why the Alternatives Are Less Suitable

Rebuilding per environment offers newer artifacts at the cost of unknown artifacts. Building once and *never* rebuilding offers known artifacts at the cost of stale ones. The asymmetry decides it: **the age problem is solvable by scheduling, and the unknown-artifact problem is not solvable at all.** A third option sometimes proposed — rebuild per environment but "diff the images afterwards to check they match" — fails because a byte-level match is not achievable in practice and a partial match proves nothing.

### Sample Exam Answer

> They are right that stale dependencies are a real risk and that frequent rebuilds are the remedy. The error is *where* the rebuild happens.
>
> Rebuilding per environment breaks the guarantee that the tested artifact is the deployed artifact. The same Dockerfile built twice can differ — floating base tags, unpinned OS packages, re-resolved transitive dependencies — so production runs an image no test ever executed against, and the most critical environment receives the least-validated build. Failures cannot be reproduced because rebuilding yields a different image, rollback has no defined target, and a compromised upstream package introduced after the staging build reaches production without passing any gate.
>
> Instead: build once per commit, resolve to a digest, scan and sign it, and promote that same digest through dev, staging and production, with environment differences supplied at run time through ECS environment variables and secrets from Parameter Store or Secrets Manager. Enable ECR tag immutability and reference digests in task definitions.
>
> Freshness is then satisfied by rebuild frequency rather than rebuild location: scheduled rebuilds of the current release that pass through the full pipeline, automatic rebuilds triggered by new base-image digests, ECR enhanced scanning with Amazon Inspector continuously rescanning deployed images against newly published CVEs, pinned dependencies with automated update pull requests, and a published patch SLA with measured artifact age.

**Exam tip.** Build once, deploy many is an AWS Well-Architected operational-excellence practice. In any exam scenario about consistency, rollback or auditability, an option that rebuilds per environment — or that references mutable tags across environments — is wrong.

**Common trap.** Believing that promoting the same digest means shipping old software. It means shipping *known* software; how new it is remains entirely under your control through rebuild scheduling.

---

## Question 12

### Question

Design the complete image supply chain for a regulated organisation that must be able to answer, for any date in the past two years, exactly which code was running in production and what its known vulnerabilities were at that time. Specify the build, registry, deployment, and audit mechanisms; state which controls are preventive and which are detective; and identify the one question your design still cannot answer.

*Advanced — architecture / compliance. What it tests: whether you can design backwards from an evidentiary requirement, and whether you know the difference between preventing something and detecting it.*

### Requirements

- **R1 — Point-in-time deployment record.** For any date *D* in a two-year window, identify exactly which image, by digest, was serving production, in which service, and for what interval.
- **R2 — Point-in-time vulnerability record.** For that digest, state the vulnerabilities known **as of D** — not as of today. This needs both the contents (an SBOM) and the state of vulnerability knowledge as it stood then.
- **R3 — Digest-to-source traceability.** Map the digest back to the exact commit, build and builder.
- **R4 — Tamper resistance.** The evidence must be defensible to an auditor, which means it must not be silently alterable, including by insiders.
- **R5 — Retention.** All of the above, for at least two years.

### Constraints

- Deletion is adversarial to the requirement: lifecycle policies must not remove evidence.
- Scanner databases change constantly, so scanning an old image *today* answers a different question than the one asked.
- Developers must still be able to ship at normal cadence.
- Cost must stay bounded despite two years of retained artifacts.

### Key AWS Concepts

Content-addressed digests; ECR tag immutability, lifecycle `transition` to the archive storage class, and enhanced scanning with Amazon Inspector; image signing and SBOM/provenance attestations; digest-pinned ECS task definitions; AWS CloudTrail with log file validation; EventBridge ECS task state-change events; Amazon S3 Object Lock in compliance mode; Amazon Athena for querying the evidence.

### Reasoning / Analysis — the design

**(1) Build — establish identity and contents**

- Source in Git with protected branches, mandatory review and signed commits; releases only from protected refs.
- Builds run in a dedicated, isolated build account under a CodeBuild or CI role that no human can assume, with no interactive access to the build environment.
- Hermetic builds: base images pinned **by digest**, lockfiles for every language dependency, no `latest` anywhere, no unpinned package installs.
- Each build emits, keyed to the resulting image digest: an **SBOM** (CycloneDX or SPDX, via BuildKit attestations or a generator such as Syft); **build provenance** as an in-toto/SLSA attestation recording source commit, builder identity and build parameters; and the **source commit SHA** recorded as an OCI label and in manifest annotations.
- The image is **signed** — Sigstore cosign, or AWS Signer with Notation — and the signature stored alongside it.
- **Build once, promote the digest.** Per Q11: rebuilding per environment makes R1 unanswerable in principle.

**(2) Registry — preserve identity and contents**

- Amazon ECR private repositories encrypted with a customer-managed KMS key, with **tag immutability enabled** so a tag can never be re-pointed.
- Repository policies restricting push to the build role and pull to the deployment and execution roles, in a cross-account model with a separate production registry account.
- **ECR enhanced scanning with Amazon Inspector**, configured for continuous scanning rather than scan-on-push alone, covering operating-system and language packages. Note that Inspector's re-scan duration is configurable (up to "Lifetime"); set it to the retention horizon, since an expired scan eligibility shows as `SCAN_ELIGIBILITY_EXPIRED` and stops producing the record R2 depends on.
- **Lifecycle policies must exempt anything ever deployed.** Either exclude release-tag patterns from expiry or — cleaner — copy every promoted digest into a dedicated archive registry with no expiry rule, and use the lifecycle `transition` action with `targetStorageClass: archive` to hold two years of evidence at lower cost. Non-deployed CI images expire normally.
- Cross-Region replication of the archive, so a Regional event cannot destroy the evidence.

**(3) Deployment — bind the artifact to production, provably**

- ECS task definitions reference **image digests**, never tags. This is the single control the whole design rests on: a task definition referencing a tag does not identify code.
- Deployment is performed only by a pipeline role. Human principals are denied `ecs:RegisterTaskDefinition`, `ecs:UpdateService`, `ecs:RunTask` and `iam:PassRole` in production via service control policies and permission boundaries.
- The pipeline **verifies the signature and provenance attestation** and checks scan status before promoting. ECS has no admission controller, so this gate lives in the pipeline and is enforced by IAM: nothing else is permitted to deploy.
- Each promotion writes a **release record** — digest, commit, task definition revision, service, cluster, approver, timestamp, SBOM location, and scan findings at promotion time — to an append-only store.

**(4) Audit — make the record durable and queryable**

- **Organization CloudTrail** with log file validation, delivered to a central log-archive account into an S3 bucket with **Object Lock in compliance mode** and at least two years' retention. CloudTrail records `RegisterTaskDefinition`, `UpdateService`, `RunTask`, `PutImage` and `BatchDeleteImage` with principal and timestamp.
- **ECS deployment and task state-change events** via EventBridge into Amazon Data Firehose and the same locked bucket, giving per-task start and stop timestamps and the digest each task ran.
- **SBOMs, attestations and signatures** stored in S3 with Object Lock, keyed by digest.
- **Inspector findings history** exported to S3 or AWS Security Hub on a schedule, so the *state of knowledge* is snapshotted over time rather than only queried live. This is essential for R2: the finding records must carry `firstObservedAt`/`lastObservedAt` so you can reconstruct what was known on date *D* rather than what is known now.
- A query layer of AWS Glue and Athena over the evidence, so the auditor's question becomes a join:

```
date D  →  task state-change events overlapping D      → digest(s) running
        →  release record for that digest              → commit, builder, SBOM
        →  Inspector findings where firstObservedAt ≤ D → vulnerabilities known at D
```

- Detective guardrails: AWS Config rules and EventBridge alarms for a task definition referencing a tag instead of a digest, an unsigned image reaching production, a lifecycle policy change on the archive registry, or a `BatchDeleteImage` against a deployed digest.

### Best Solution — preventive versus detective controls

| Preventive — stop it happening | Detective — notice it happened |
|---|---|
| ECR tag immutability | CloudTrail with log file validation |
| Digest-pinned task definitions | ECS task state-change event stream |
| S3 Object Lock in compliance mode on evidence | ECR enhanced scanning / Inspector continuous rescan |
| IAM and SCP restrictions on deploy actions and `iam:PassRole` | AWS Config rules for tag-referencing task definitions and policy drift |
| Image signing with verification before promotion | Security Hub aggregation and alerting |
| Lifecycle-policy exemption for deployed digests | Alarms on `BatchDeleteImage` and lifecycle-policy modification |
| Protected branches, signed commits, isolated build account | Amazon GuardDuty, including runtime monitoring for ECS and Fargate |
| KMS encryption with restricted key policies | IAM Access Analyzer for unintended cross-account access |

The organising principle: **preventive controls constrain the present; detective controls preserve the past.** The requirement here is evidentiary, so the detective side carries most of the weight — but without the preventive side the detective records merely describe a system that *could* have been altered, and an auditor will say so.

### The one question this design still cannot answer

It can state what was running and which vulnerabilities were **published and detectable** at the time. It **cannot state whether those vulnerabilities were actually exploitable in that deployment**, and it cannot state which vulnerabilities existed but were unknown to the world on date *D*.

- The SBOM lists components and the scanner maps them to CVEs. Neither knows whether the vulnerable code path was reachable, whether the affected feature was enabled, or whether a compensating control — a WAF rule, network isolation, a non-root read-only filesystem — made exploitation impossible. "A vulnerable dependency was present" and "the system was at risk" are different statements, and only the first is recorded.
- Vulnerabilities unknown on date *D* — a zero-day, or a CVE published a year later against code shipped two years ago — appear in no record for that date. The design faithfully records what was *knowable* and honestly cannot record what was *true*.
- Two lesser gaps worth naming: an SBOM misses statically linked, vendored or hand-copied code that no package manager declares; and defects in your own application logic appear in no CVE feed at all.

If an auditor asks "were you exposed on that date?", the honest answer is that the design proves what was deployed and what was known, and that assessing exposure needs additional evidence — GuardDuty runtime monitoring, WAF and ALB logs, reachability analysis — which should be collected and retained alongside, and which will still not make the answer complete.

### Sample Exam Answer

> **Build:** hermetic builds in an isolated account from protected, signed Git refs, with base images pinned by digest and lockfiles for all dependencies. Each build emits an SBOM and a SLSA provenance attestation keyed to the image digest, and the image is signed with cosign or AWS Signer. Build once and promote the digest.
>
> **Registry:** Amazon ECR with tag immutability, KMS encryption, restrictive repository policies, enhanced scanning through Amazon Inspector in continuous mode, cross-Region replication, and lifecycle policies that exempt every deployed digest — using a separate archive registry with the `transition` action to archive storage for two-year retention.
>
> **Deployment:** ECS task definitions reference digests only; only the pipeline role may register task definitions or update services, enforced through IAM and SCPs; the pipeline verifies signature, provenance and scan status before promotion, and writes a release record linking digest, commit, approver and timestamp.
>
> **Audit:** organization CloudTrail with log file validation plus ECS task state-change events from EventBridge, delivered to an S3 bucket with Object Lock in compliance mode; SBOMs, attestations and Inspector finding history with first-observed timestamps stored alongside. Athena over that evidence answers "on date D, which digests were running, from which commits, with which vulnerabilities then known".
>
> **Preventive controls:** tag immutability, digest pinning, IAM and SCP deploy restrictions, signing with verification, S3 Object Lock, lifecycle exemption. **Detective controls:** CloudTrail, task state-change events, Inspector continuous rescanning, Config rules, Security Hub, GuardDuty.
>
> **What it still cannot answer:** whether a recorded vulnerability was actually exploitable in that deployment, and which vulnerabilities existed but were unknown on that date. The design records what was deployed and what was knowable; true exposure requires runtime evidence and reachability analysis it does not capture.

**Exam tip.** "Must prove what was running" → digests plus CloudTrail plus immutable storage. "Must prove the record was not altered" → S3 Object Lock and CloudTrail log file validation. Regulated-environment questions usually turn on immutability of the *evidence*, not only of the artifact.

**Common trap.** Believing that today's scan of an old image answers "what did we know then". Scanner databases update continuously, so a scan run now reports today's knowledge against yesterday's artifact. Findings must be snapshotted over time, with first-observed timestamps.

---

## Question 13

### Question

A legacy Java application writes session state to local disk, logs to rotating files, reads configuration from a properties file baked into its deployment, and requires a specific JVM patch level. Design its containerisation. Order the work by risk, state what must change in the application itself before containerisation is honest rather than cosmetic, and identify which single change you would refuse to skip even under schedule pressure.

*Advanced — architecture / migration. What it tests: whether you can tell the difference between putting an application in a container and making it work as a container, and whether you will hold a line under pressure.*

### Requirements

- The application must run on ECS without losing correctness.
- It must tolerate task replacement, which is the platform's normal response to almost every event.
- Its logs must remain accessible after a task dies.
- One artifact must be promotable across environments.
- The required JVM patch level must be guaranteed, not hoped for.

### Constraints

- Legacy code, so large rewrites are not on the table.
- A fixed JVM patch level is stated as a hard requirement.
- Schedule pressure is explicitly part of the question.

### Key AWS Concepts

Ephemeral container storage; ElastiCache and DynamoDB for session state; the `awslogs` driver and FireLens; ECS `secrets` and environment variables; task roles; cgroup-aware JVM sizing; `SIGTERM` handling and `stopTimeout`; ALB health checks and deregistration delay; the ECS deployment circuit breaker.

### Reasoning / Analysis — what each stated property breaks

| Property | What it breaks | Severity |
|---|---|---|
| Session state on local disk | Task replacement, scaling, deployment — state dies with the ephemeral writable layer | **Critical** |
| Logging to rotating files | Observability — logs are invisible and destroyed with the task; rotation fills the writable layer | High |
| Configuration baked into the deployment | Build-once-promote-many — forces a rebuild per environment (Q11) | High |
| A required JVM patch level | Reproducibility and patching, plus JVM/cgroup interaction | Medium, but easy to solve |

### Best Solution — work ordered by risk

**Phase 0 — establish a baseline before changing anything.** Capture current behaviour: response times, memory footprint, start-up time, and the JVM version and flags actually in production. Get the application building reproducibly from source with pinned dependencies. Without this you cannot distinguish a containerisation regression from a pre-existing bug.

**Phase 1 — externalise session state (highest risk, therefore first).**
- Preferred: move sessions to **Amazon ElastiCache for Redis**, or to **Amazon DynamoDB** with a TTL. For a servlet application this is usually a container- or framework-level change — Spring Session, a Redis session manager — rather than a rewrite of business logic.
- Interim bridge only: ALB **sticky sessions**. Be explicit that this hides the symptom rather than fixing it — the user still loses their session when the task is replaced, and replacement now happens on every deployment and every scale-in.
- Acceptance test: kill a task under load and confirm no user-visible session loss.

**Phase 2 — logs to stdout/stderr.**
- Reconfigure Log4j2 or Logback to a console appender and **remove file rotation entirely**; rotation inside a container writes to the ephemeral layer, competes for task disk, and hides the logs.
- Route with the ECS `awslogs` driver to CloudWatch Logs, or with **FireLens/Fluent Bit** where the destination is OpenSearch, S3 or a third-party platform.
- Adopt structured JSON logging with a correlation ID while the logging configuration is already open — far cheaper now than later.
- The execution role needs `logs:CreateLogStream` and `logs:PutLogEvents`.

**Phase 3 — externalise configuration.**
- Non-secret configuration to ECS task-definition **environment variables**, or a properties file assembled at start-up from **Parameter Store**.
- Secrets to the task definition's **`secrets`** block backed by **Secrets Manager** or a Parameter Store SecureString, fetched by the execution role at task start. Never in the image, never in `ARG`, never in Dockerfile `ENV` (Q7).
- Better still, eliminate static database credentials by using an IAM **task role** with RDS IAM authentication where the engine supports it.
- Acceptance test: the identical image digest starts correctly in dev, staging and production with only configuration differing.

**Phase 4 — the image itself.**

```dockerfile
# Build stage
FROM public.ecr.aws/docker/library/maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B package -DskipTests

# Runtime stage — JVM patch level pinned by digest, not by tag
FROM public.ecr.aws/amazoncorretto/amazoncorretto:17.0.11-alpine@sha256:<digest>
WORKDIR /app
COPY --from=build /src/target/app.jar ./app.jar
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"
USER 1001
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar"]
```

- **Pin the JVM by digest**, not by tag, so the required patch level is guaranteed and any change is a deliberate, reviewed event. Record the constraint and its reason, and open a tracked item to move off it — a frozen JVM is security debt, not a permanent design.
- Ensure **container awareness**: JDK 10 and later (and 8u191+) honour cgroup limits by default. Size the heap with `-XX:MaxRAMPercentage`, never a fixed `-Xmx` derived from host RAM, or the cgroup will OOM-kill the task (Q3).
- Run as a **non-root user**, and set `readonlyRootFilesystem: true` with a `tmpfs` mount for `/tmp` once nothing else writes to disk.

**Phase 5 — behave correctly under the ECS lifecycle.**
- **Graceful shutdown:** the JVM must receive `SIGTERM` — use exec-form `ENTRYPOINT`, not shell form — and must drain in-flight requests. Set ECS `stopTimeout` and the ALB deregistration delay consistently.
- **Health checks:** a real readiness endpoint that verifies dependencies, wired to the ALB target group, with interval and threshold tuned (Q14).
- **Deployment safety:** enable the ECS deployment circuit breaker with rollback.
- **Sizing:** set task CPU and memory from the measured baseline, then validate under load — legacy JVM applications are routinely mis-sized on the first attempt.

**Phase 6 — cut over gradually.** Run containerised tasks alongside the existing deployment behind weighted target groups or Route 53 weighting, shift traffic incrementally, and keep the old path available for rollback until the new one has survived a full business cycle.

### What must change in the application for containerisation to be honest

Cosmetic containerisation is packaging the application unchanged, running a single task, disabling scaling and stickying every user to it. It runs — and delivers none of the properties containers exist to provide, while adding a new abstraction layer to operate.

Three application-level changes are required for it to be honest:

1. **Statelessness** — no request affinity to a particular task's local disk. This is what makes tasks disposable, and disposability underpins every other benefit.
2. **Logs and telemetry as streams to stdout/stderr** — because the filesystem is ephemeral and a dead task is not addressable.
3. **Configuration from the environment** — so one immutable artifact can be promoted across environments.

These are the first three factors of the twelve-factor model, and they are not conveniences: they are what makes the platform's core behaviour — kill and replace at will — safe.

### The single change I would refuse to skip: externalising session state

ECS's response to almost every event — deployment, scale-in, failed health check, AZ impairment, Fargate host retirement, Spot interruption — is *stop this task, start another*. If session state lives on the task's local disk, then every one of those routine, automatic, unavoidable events becomes a user-visible failure: users logged out, carts emptied, forms lost. You have converted the platform's normal operation into an incident generator, and the failures will cluster during deployments and load spikes, when they are most damaging.

Sticky sessions are not an escape. They pin a user to a task; they do not make the task immortal. They also disable even load distribution and make scale-in actively harmful.

Logging, configuration and JVM pinning can each be deferred a sprint with a written, tracked compromise and no correctness risk. Statefulness cannot, because the failure it causes is not in the migration — it is in every day afterwards, and it silently makes the containerised system *less* reliable than the VM it replaced. That is the one outcome that turns the whole project into a net negative, so it is the line to hold.

### Why the Alternatives Are Less Suitable

**Mounting Amazon EFS for session state** works mechanically but adds latency and a shared failure domain, and preserves the file-affinity coupling instead of removing it; EFS is for genuinely shared *file* data, not session state. **Keeping sticky sessions permanently** trades a correctness property for a routing trick that fails on every task replacement. **Containerising everything at once in a single cut-over** maximises the number of simultaneous unknowns, which is precisely what a risk-ordered plan exists to avoid.

### Sample Exam Answer

> Order the work by risk. First, externalise session state to ElastiCache for Redis or DynamoDB, because local disk is ephemeral and every ECS task replacement would otherwise lose user sessions; ALB stickiness is only a temporary bridge. Second, replace rotating file logging with structured logging to stdout/stderr, shipped by the `awslogs` driver or FireLens to CloudWatch. Third, externalise configuration to task-definition environment variables and Parameter Store, with secrets injected through the task definition's `secrets` block from Secrets Manager, so one image is promoted to every environment. Fourth, build a multi-stage image on an Amazon Corretto base **pinned by digest** to guarantee the required JVM patch level, running as a non-root user with the heap sized by `-XX:MaxRAMPercentage` so the JVM respects the cgroup limit. Fifth, add graceful `SIGTERM` handling with an exec-form entrypoint, a real readiness endpoint, an appropriate `stopTimeout` and deregistration delay, and the deployment circuit breaker. Finally, cut over gradually behind weighted target groups.
>
> For containerisation to be honest rather than cosmetic, the application must become stateless, log to stdout, and take its configuration from the environment.
>
> The change I would refuse to skip is externalising session state, because ECS responds to deployments, scaling, health-check failures and host retirement by replacing tasks. With state on local disk, every one of those routine events becomes a user-visible failure, making the containerised system less reliable than what it replaced.

**Exam tip.** "Lift and shift into containers" scenarios almost always hinge on state. Look first for local disk, in-memory sessions and file-based logs.

---

## Question 14

### Question

An organisation running forty services on Fargate observes that scale-out during traffic spikes takes ninety seconds from alarm to serving capacity, and users experience errors during that window. Decompose the ninety seconds into its contributing phases, identify which phases you can influence and by how much, propose specific changes ordered by expected effect, and state which part of the problem cannot be solved by making the image smaller and what you would do about that instead.

*Advanced — performance / scaling. What it tests: whether you decompose before optimising, whether you can size each intervention, and whether you recognise that the user-visible error is a capacity-headroom problem rather than only a latency problem.*

### Requirements

New capacity must become available fast enough that traffic spikes do not produce user-visible errors.

### Constraints

- **Fargate** — there is no host layer to tune, no cross-task layer cache, and no warm pool of your own instances.
- **Forty services** — any fix must be cheap to apply uniformly, so per-service heroics cannot be the primary strategy.

### Key AWS Concepts

ECS task lifecycle timestamps; Fargate's no-caching pull behaviour; SOCI lazy loading and zstd compression; ECR VPC endpoints; ALB target group health-check parameters; Application Auto Scaling target tracking, step, scheduled and predictive policies; CloudWatch metric resolution and alarm evaluation periods.

### Reasoning / Analysis — decomposing the ninety seconds

Measure rather than assume: capture ECS Task State Change events from EventBridge and read `createdAt`, `pullStartedAt`, `pullStoppedAt` and `startedAt`, then take target-group registration time from ALB metrics. A typical JVM-on-Fargate profile:

| Phase | Typical | What happens |
|---|---|---|
| **A. Scaling reaction** | 5–15 s | Alarm fires → Application Auto Scaling → `UpdateService` desired count; cooldown and warm-up gates |
| **B. Placement and infrastructure** | 10–20 s | ECS scheduler places the task; Fargate provisions a single-tenant microVM; the ENI is created, attached and becomes ready in `awsvpc` mode |
| **C. Image pull and decompress** | 20–30 s | Authenticate to ECR, fetch **all** layers — Fargate caches nothing between tasks — and decompress |
| **D. Container and application start** | 20–30 s | JVM start, framework initialisation, class loading, connection pools, configuration fetch, JIT warm-up |
| **E. Health check and registration** | 15–30 s | Target registered as `initial`, then health-check interval × healthy threshold before it becomes `healthy` |
| **Total** | **~90 s** | |

Note that phase A begins *at the alarm*. The **detection window before the alarm** — metric publication at one-minute granularity plus the alarm's evaluation periods — is typically a further 60–180 seconds and is not counted in the ninety, even though users experience it. That matters for the last part of the question.

**What you can influence, and by how much**

| Phase | Degree of control | Realistic saving |
|---|---|---|
| A. Scaling reaction | High | 5–10 s |
| B. Placement and infrastructure | Very low | ~0 s |
| C. Image pull | High | 10–25 s |
| D. Application start | Medium–high; needs code and JVM work | 10–25 s |
| E. Health checks | Very high, near-zero cost | 20–40 s |

### Best Solution — changes ordered by expected effect per unit of effort

**1. Tune health checks and registration (phase E) — the largest win, configuration only.** Defaults are conservative: a 30-second interval with a healthy threshold of 3 means up to 90 seconds before a target is healthy. Move to `interval: 10s`, `healthyThreshold: 2`, `timeout: 5s`, with a health-check path that is a cheap readiness endpoint rather than one that queries the database on every probe. Set `deregistration_delay` appropriately and disable ALB slow start if it is enabled. **Expected saving: 20–40 s.** Ship it as a shared Terraform or CDK default so all forty services get it at once — this is the change that scales to the fleet.

**2. Shrink and accelerate the image (phase C).** Multi-stage builds onto a minimal base — Amazon Linux 2023 minimal, distroless, or a JRE-only image — commonly take 700 MB to 200 MB. Keep images in the **same Region** as the tasks. Add **ECR interface endpoints (`ecr.api`, `ecr.dkr`) and the S3 gateway endpoint** so forty concurrent pulls do not contend for a NAT gateway. Use **zstd** compression, which AWS documents as the more performant algorithm for reducing decompression time. For images that must remain above roughly 250 MB, enable **Seekable OCI (SOCI)** lazy loading, which AWS recommends at that threshold so the container can start before the whole image has been downloaded. **Expected saving: 10–25 s.**

**3. Reduce application start-up time (phase D).** For the JVM: `-XX:TieredStopAtLevel=1` for faster warm-up, **AppCDS/CDS archives** to cut class loading, lazy initialisation of non-critical beans, deferring background work until after readiness, and removing synchronous remote configuration fetches from the start-up path. Larger investments where justified: **CRaC** checkpoint/restore, or a **GraalVM native image**. Also right-size task CPU — Fargate CPU allocation directly limits start-up parallelism, and a 0.25 vCPU task starts a JVM far more slowly than a 1 vCPU task. **Expected saving: 10–25 s**, but this is per-service work, so sequence it after the fleet-wide wins.

**4. Tighten the scaling reaction (phase A).** Reduce or remove the scale-out cooldown, keep the scale-in cooldown conservative, and shorten warm-up. Prefer **target tracking on `ALBRequestCountPerTarget`**, which reacts to load rather than to a lagging symptom such as CPU, and add a **step scaling** policy on a high-resolution custom metric for large jumps, so a big spike adds many tasks at once rather than one increment per interval. **Expected saving: 5–10 s**, plus a much larger improvement in the *detection* window that precedes the ninety seconds.

**5. Phase B — accept it.** MicroVM provisioning and ENI attachment are AWS-side. Keep tasks spread across multiple subnets and AZs for scheduler flexibility, and move on.

Applied together, ninety seconds should fall to roughly 30–45 seconds.

### What cannot be solved by making the image smaller

**Reactive scaling is structurally late.** Even with an image of zero bytes the sequence is: demand rises → metrics are published (up to 60 s) → the alarm evaluates over one or more periods → capacity is requested → infrastructure, application start and health checks consume another 30–60 s. Users are absorbing the spike on the *old* capacity for one to three minutes regardless. A smaller image shortens one term in an equation whose sum can never reach zero — and the errors users see are caused by demand exceeding capacity throughout that gap, not by the pull itself.

The errors are therefore a **capacity-headroom and admission-control problem**, and must be addressed directly:

1. **Run with headroom.** Lower the target-tracking utilisation target — say 50–60% rather than 80% — so existing tasks absorb the first minute of a spike, and raise the service minimum task count above the quiet-period requirement. This costs money and buys availability; state the trade-off explicitly rather than pretending it is free.
2. **Scale before the spike, not after it.** Use **scheduled scaling** for known patterns — business-hours ramp, marketing sends, batch windows — and **predictive scaling** where the pattern is learnable. A spike you anticipated has no gap at all.
3. **Shorten detection.** Publish high-resolution (10-second) custom metrics for the scaling signal, alarm on one or two periods rather than three, and scale on a leading indicator such as request rate or queue depth rather than a lagging one such as CPU.
4. **Degrade gracefully instead of failing.** Load shedding and admission control at the edge, bounded request queueing, a lightweight "busy" response on non-critical paths, and circuit breakers so a saturated dependency does not cascade. A slow response beats a 5xx.
5. **Make clients resilient.** Retries with exponential backoff **and jitter**, sensible timeouts, and idempotency so retries are safe. Without jitter, retries synchronise and amplify the very spike you are trying to survive.
6. **Absorb the spike elsewhere.** CloudFront and ALB caching for cacheable content; asynchronous decoupling through Amazon SQS so bursts queue rather than fail; and, for genuinely spiky secondary workloads, a burst tier on AWS Lambda, which scales in seconds rather than tens of seconds.
7. **Verify by load test.** Reproduce the spike shape and measure the error rate against different headroom settings, so the utilisation target is chosen from evidence rather than intuition.

### Why the Alternatives Are Less Suitable

Optimising the image first is the intuitive move and the wrong one: it is the third-largest term and the most expensive to change, while the health-check configuration is the largest term and free. Moving to ECS on EC2 with a warm pool would cut phases B and C substantially, but it reintroduces host management, patching and the container instance role (Q8) across forty services — a large operational and security cost to buy seconds that headroom buys more cheaply. Simply raising the desired count permanently to the peak removes the problem but pays peak cost continuously; target-tracking with a lower utilisation target achieves most of the benefit at a fraction of the price.

### Sample Exam Answer

> Decompose using ECS task timestamps — `createdAt`, `pullStartedAt`, `pullStoppedAt`, `startedAt` — plus target-group registration: scaling reaction 5–15 s; Fargate microVM provisioning and ENI attachment 10–20 s; image pull and decompression 20–30 s, since Fargate caches nothing between tasks; container and JVM start 20–30 s; health check and registration 15–30 s.
>
> Highest-value changes in order: first, tune health checks — interval 10 s, healthy threshold 2, no slow start — saving 20–40 s at no cost across all forty services; second, shrink the image with multi-stage builds onto a minimal base, use same-Region ECR with `ecr.api` and `ecr.dkr` interface endpoints plus the S3 gateway endpoint, zstd compression, and SOCI lazy loading for images over about 250 MB, saving 10–25 s; third, reduce JVM start-up with CDS/AppCDS, tiered compilation limits, lazy initialisation and adequate task vCPU, or CRaC or a native image, saving 10–25 s; fourth, reduce the scale-out cooldown and use target tracking on `ALBRequestCountPerTarget` with step scaling for large jumps, saving 5–10 s. MicroVM provisioning and ENI attachment cannot be influenced.
>
> What a smaller image cannot fix is that reactive scaling is inherently late: metric publication and alarm evaluation add a further one to three minutes before the ninety even begins, and demand exceeds capacity throughout. That is a headroom and admission-control problem. I would run a lower utilisation target and a higher minimum task count, use scheduled and predictive scaling for known patterns, scale on leading high-resolution metrics such as request count per target, and add load shedding, bounded queueing, circuit breakers and jittered client retries so the gap degrades performance rather than producing errors — validated by a load test that reproduces the spike shape.

**Exam tip.** When asked why tasks are slow to serve traffic, check the health-check configuration first. Default intervals and thresholds are the most common single cause and the cheapest to fix.

**Common trap.** Treating "faster launches" and "no errors during spikes" as the same goal. Faster launches shorten the gap; only headroom, prediction and graceful degradation remove the errors inside it.

---

## Question 15

### Question

Critique the following proposal: *"We will use a single shared base image for all services, containing our standard JDK, our monitoring agent, our logging library, curl, the AWS CLI, and a shell, so that every team gets the same tooling and debugging is easy. We will tag it `company/base:latest` and rebuild it nightly so it is always patched."* Identify at least five specific defects, propose a corrected design, and state which parts of the original intent you would preserve and how.

*Advanced — critique / design. What it tests: whether you can separate a sound goal from a defective mechanism, and whether your critique is specific enough to act on.*

### What the proposal gets right

Standardisation is a legitimate goal. Forty teams each choosing a base image, each patching it independently, each with different debugging conventions, is worse than a curated set. Central ownership of base images is correct. **Every defect below is in the mechanism, not the motive** — and a critique that does not say so scores badly, because it fails to engage with the problem the team is actually trying to solve.

### Reasoning / Analysis — the defects

**Defect 1 — `latest` is a mutable tag, so nothing is reproducible.** The tag is re-pointed nightly. Two services building on the same morning may receive different bases; rebuilding last month's release produces a different image than it did then. There is no way to state which base a given production image contains, no way to roll a base change back, and no way to reproduce a failure. Combined with a mutable tag in downstream Dockerfiles, an application build becomes non-deterministic even when the application commit is unchanged. This defect alone makes the audit requirements of Q12 unachievable.

**Defect 2 — a nightly rebuild pushed to the shared tag is an untested change injected into all forty services simultaneously.** There is no canary, no staged rollout, no per-service test gate and no approval. A regression in the JDK, the monitoring agent or a transitive OS package reaches every service at once — and because the *tag moved* rather than a version changing, the correlation between "everything broke this morning" and "the base changed" appears in no diff anywhere. The base image becomes the largest correlated-failure domain in the estate, governed by the weakest change control in the estate.

**Defect 3 — `curl`, the AWS CLI and a shell in every production image are a blast-radius decision, not a convenience.** An attacker with RCE or command injection in any service finds a ready-made toolkit: `curl` to reach the container credentials endpoint at `169.254.170.2` and the instance metadata service, and the AWS CLI to use the stolen task-role credentials against AWS APIs directly (Q8). Removing them does not make an attack impossible, but it materially raises the cost of every post-exploitation step. AWS CLI v2 also drags in a substantial runtime, adding hundreds of megabytes — which is a scale-out latency cost on Fargate (Q10) — and a continuous CVE stream to triage, for tooling production code never calls.

**Defect 4 — a shared nightly rebuild does not patch anything that is deployed.** Patching a base image changes running production only when each downstream service **rebuilds and redeploys** on top of the new base. Without an automatic downstream trigger, the nightly rebuild produces a well-patched image nobody is running, while creating a false sense of security. Worse, services that *do* rebuild receive the patch as an unannounced side effect of an unrelated change, so patch adoption is accidental rather than managed — and therefore unmeasurable.

**Defect 5 — the logging library and the monitoring agent do not belong in a base image.** A logging library is an *application dependency*: it must be resolved by the build tool alongside everything else, version-managed in the manifest, and upgradeable per service. Baking it into the OS image creates conflicts with the application's own dependency graph, prevents any service from upgrading independently — a Log4Shell-class emergency then needs a base rebuild plus forty rebuilds instead of one dependency bump per service — and couples unrelated release cadences. The monitoring agent is a *process* concern and belongs in a **sidecar container** in the ECS task, where it is versioned, restarted and upgraded independently of the application.

**Defect 6 — one JDK for everyone makes the base team a bottleneck and excludes non-Java services.** A single base pins every service to one language and one JDK. A team ready to move to a newer LTS cannot; a team that must stay on an older one blocks everyone else; a Python or Node service has no path at all. Standardisation should offer a small curated *set*, not a single artifact.

**Defect 7 — "debugging is easy" solves a problem that has a better solution.** **ECS Exec** provides an interactive shell into a running task without baking tools into the production image, given the SSM agent capability, the right task-role permissions and `enableExecuteCommand`. Where deeper tooling is needed, a debug sidecar sharing the task's namespaces, or a `-debug` image variant for local reproduction, gives full tooling without shipping it to production continuously.

**Defect 8 — no supply-chain controls.** No scanning gate, no signing, no SBOM, no provenance, and no pinned upstream. A nightly rebuild of the same Dockerfile also re-resolves unpinned OS packages, so upstream breakage or compromise propagates automatically to forty services with no review (Q11, Q12).

### Best Solution — the corrected design

**Base images**
- A small curated **set** of thin base images, one per runtime — `company/jre21`, `company/python312`, `company/node22` — built on a minimal distribution such as Amazon Linux 2023 minimal, or distroless.
- **No shell, no `curl`, no AWS CLI** in runtime images. Publish a parallel `-debug` variant containing tooling, used for local reproduction and as a debug sidecar, never as the production runtime.
- Upstream bases pinned **by digest**; OS packages version-pinned.

**Versioning and consumption**
- Immutable, dated version tags such as `company/jre21:2026.08.30`, with **ECR tag immutability enabled**. A `latest` tag may exist for human browsing but is forbidden in any Dockerfile or task definition.
- Service Dockerfiles pin the base **by digest**: `FROM <account>.dkr.ecr.<region>.amazonaws.com/company/jre21@sha256:…`.

**Patch pipeline — the part the original gets most wrong**

```
scheduled base rebuild (weekly, plus on upstream CVE)
        ↓
scan (Inspector) + sign (cosign / AWS Signer) + SBOM
        ↓
smoke-test the base
        ↓
publish new dated tag + digest
        ↓
automated PR to each service bumping the pinned digest
        ↓
each service's own pipeline: build → test → promote      ← the gate the original lacks
        ↓
deploy (build once, promote the digest — Q11)
```

- Adoption is **measured, not assumed**: a dashboard of every service's base digest and its age, plus an SLA — critical CVE adopted within 7 days, all services within 30 — with escalation for stragglers.
- A **canary cohort** of two or three low-risk services adopts each new base first.

**Cross-cutting concerns**
- **Monitoring agent → sidecar container** (ADOT Collector or the CloudWatch agent) in the task definition, versioned centrally and upgraded without touching application images.
- **Log shipping → FireLens/Fluent Bit sidecar or the `awslogs` driver**; the application writes structured JSON to stdout.
- **Logging library → an ordinary versioned dependency** in each service's build manifest, with a shared internal BOM or parent POM to keep versions aligned without freezing them.

**Governance**
- Enhanced scanning on all base repositories, signature verification enforced in the deployment pipeline, an SBOM per base digest, and an AWS Config rule detecting any task definition or Dockerfile referencing a mutable tag.

### Which parts of the original intent to preserve, and how

| Original intent | Keep? | How, in the corrected design |
|---|---|---|
| Consistency across teams | **Yes** | A curated set of blessed base images per runtime, plus shared pipeline templates enforcing the same build, scan and sign steps |
| Central patching effort, not duplicated forty times | **Yes** | A central base rebuild pipeline, plus automated digest-bump pull requests so the central work actually reaches every service |
| Easy debugging | **Yes, differently** | ECS Exec for live tasks, a `-debug` image variant and debug sidecars for deeper work, and a standard debug runbook — tooling on demand rather than tooling shipped to production |
| Same tooling and defaults everywhere | **Yes, relocated** | A shared CI/CD pipeline library and a dependency BOM enforce consistency at build time; the runtime image stays minimal |
| Always patched | **Yes, made real** | Scheduled and CVE-triggered base rebuilds *plus* automated downstream adoption with a measured SLA — patching that reaches production rather than patching that sits in a registry |

### Why This Is Correct

The proposal correctly identified that consistency and patching should be centralised, then implemented centralisation as a *shared mutable runtime artifact* — which converts a governance problem into a correlated-failure problem and an attack-surface problem simultaneously. The corrected design centralises the **pipeline, the policy and the curated set of pinned versions**, keeps the runtime image minimal, and makes each service's adoption of a new base an explicit, tested, individually gated change. Every stated goal survives; only the mechanism changes.

### Sample Exam Answer

> Defects: first, `latest` is mutable, so builds are not reproducible, the base inside any production image cannot be identified, and base changes cannot be rolled back. Second, a nightly rebuild pushed to the shared tag injects an untested change into all forty services at once with no canary or per-service gate, creating the largest correlated-failure domain in the estate. Third, shipping `curl`, a shell and the AWS CLI to production hands an attacker a ready-made toolkit for reaching the container credentials endpoint and using stolen task-role credentials, and adds a large continuous CVE stream. Fourth, rebuilding the base does not patch production — services receive it only when they rebuild and redeploy — so the design gives a false sense of patching. Fifth, the logging library belongs in each service's dependency manifest and the monitoring agent belongs in a sidecar, since baking them in blocks independent upgrades and couples release cadences. Sixth, one JDK for all makes the base team a bottleneck and excludes non-Java services. Seventh, there is no scanning, signing, SBOM or upstream pinning.
>
> Corrected design: a small curated set of thin, minimal runtime bases per language, with no shell or CLI and a separate `-debug` variant; immutable dated tags with ECR tag immutability, consumed by digest; upstream pinned by digest; a scheduled and CVE-triggered base rebuild that scans, signs and smoke-tests, then raises automated pull requests bumping each service's pinned digest so every adoption passes that service's own tests; a canary cohort first; monitoring and log shipping as sidecars; and a dashboard plus SLA measuring adoption.
>
> I would preserve the intent: consistency, through the curated set and shared pipeline templates; central patching, through the central rebuild plus automated downstream adoption; and easy debugging, through ECS Exec, debug sidecars and a `-debug` image rather than tooling permanently shipped to production.

**Exam tip.** In critique questions, always separate *goal* from *mechanism*. Marks come from conceding the valid goal and then showing precisely where the mechanism fails.

**Common trap.** Assuming a nightly base rebuild equals a patched fleet. Patching is real only when downstream services rebuild, test and redeploy — and only when the adoption rate is measured.

---

# Final Revision Guide

---

## 1. Concepts covered by this question set

**Container fundamentals.** Image versus container; layers and copy-on-write; union filesystems and whiteout entries; image immutability and ephemeral container storage; tags versus digests and content addressing; multi-stage builds; layer ordering and build cache; BuildKit build secrets.

**Linux mechanisms.** Namespaces (PID, mount, network, UTS, IPC, user) and their architectural consequences; cgroups, and the asymmetry between memory OOM-kill and CPU throttling; cgroup-aware runtimes; OverlayFS; the shared-kernel model and why Fargate uses per-task microVMs.

**Compute — ECS and Fargate.** Task versus service; task definitions; `awsvpc` network mode and per-task ENIs; sidecar containers; launch-type differences; task lifecycle timestamps; graceful shutdown, `stopTimeout` and the deployment circuit breaker; ECS Exec.

**Registry — ECR.** Repositories; tag immutability; lifecycle policies with `expire` and `transition` actions, `tagPatternList` selection and `sinceImagePushed`/`sinceImageTransitioned` counting; lifecycle policy preview; enhanced scanning with Amazon Inspector; pull-through cache; `repositoryCredentials`; storage-based pricing.

**Networking.** Private subnets; NAT gateways; interface endpoints for `ecr.api`, `ecr.dkr` and `logs`; the **S3 gateway endpoint** required for layer blobs; security groups; network ACLs; private DNS; VPC Flow Logs; the diagnostic path client → DNS → route → security controls → service.

**Security and IAM.** Task execution role versus task role versus container instance role; the container credentials endpoint at `169.254.170.2` and IMDS at `169.254.169.254`; IMDSv2 and hop limits; least privilege and `iam:PassRole`; build-time versus run-time secrets; Secrets Manager and Parameter Store; KMS; image signing, SBOM and provenance; preventive versus detective controls; S3 Object Lock and CloudTrail log file validation.

**Reliability and performance.** Image size as a latency and recovery property; SOCI lazy loading and zstd compression; decomposing scale-out; health-check tuning; target tracking, step, scheduled and predictive scaling; headroom, load shedding, circuit breakers and jittered retries.

**Cost.** ECR storage economics; lifecycle policies and archive storage; image size as a cost multiplier; NAT gateway data processing versus VPC endpoints; the cost of headroom as purchased availability.

**Release engineering.** Build once, promote the digest; configuration injected at run time; artifact freshness through rebuild scheduling; base-image governance and adoption SLAs.

---

## 2. Service and mechanism cheat sheet

| Service / mechanism | What it does | When to choose it |
|---|---|---|
| Amazon ECR | Private OCI registry; per-GB-month storage, scanning, replication | The default registry for images on AWS; enable tag immutability on anything deployable |
| ECR lifecycle policy | Expires or transitions images by tag pattern, age or count | Any repository written to by CI — which is all of them |
| ECR enhanced scanning (Inspector) | Continuous rescanning of stored images for OS and language-package CVEs | When you must learn about vulnerabilities discovered *after* the build |
| ECR pull-through cache | Mirrors upstream public images into your registry | To avoid public-registry rate limits and pin a known copy |
| ECS task | One running instance of a task definition | Finite work: migrations, batch jobs, ETL |
| ECS service | Controller maintaining N tasks, load balancing, rolling deploys, scaling | Long-running work: APIs, workers, anything that must stay up |
| AWS Fargate | Serverless container compute; per-task microVM, no host to manage | The default, unless you need host control, GPUs, or heavy layer-cache reuse |
| ECS on EC2 | Containers on instances you own | Host-level control, specialised instances, cross-task layer caching |
| Task execution role | Used by the agent to pull images, fetch secrets, write logs | Every task definition; scope it to specific repositories and secrets |
| Task role | Used by your application code for AWS API calls | Every task that calls AWS; least privilege, one per service |
| Container instance role | EC2 instance profile for the ECS agent | EC2 launch type only; keep minimal, IMDSv2, hop limit 1 |
| Secrets Manager / Parameter Store | Runtime secret and configuration injection via the `secrets` block | Any credential or environment-specific value |
| BuildKit `--mount=type=secret` | Mounts a credential for one `RUN`, never into a layer | Any credential needed at build time |
| Multi-stage build | Discards build tooling; ships only artifacts | Essentially every compiled or bundled application |
| SOCI lazy loading | Starts containers before all layers are fetched | Fargate tasks with images above roughly 250 MB where pull time dominates |
| zstd compression | Faster decompression of image layers | Fargate start-up optimisation, alongside image shrinking |
| VPC interface endpoints (`ecr.api`, `ecr.dkr`, `logs`) | Private connectivity to AWS APIs | Tasks in private subnets; avoids NAT cost and contention |
| S3 gateway endpoint | Private path to the layer blobs in S3 | **Required** alongside ECR endpoints, or pulls hang after authentication |
| ECS Exec | Interactive shell into a running task | Debugging without shipping a shell in the image |
| ALB + target groups | Traffic distribution and health checking | Any HTTP service; health-check settings dominate scale-out latency |
| Application Auto Scaling | Target tracking, step, scheduled and predictive scaling for ECS | Every production service; choose leading metrics |
| CloudTrail + S3 Object Lock | Tamper-evident record of API activity | Regulated environments needing defensible evidence |
| EventBridge ECS task state change | Durable stream of task lifecycle timestamps | Measuring pull time, start time and time-to-healthy |

---

## 3. Key comparisons

**Tag versus digest** — a mutable pointer versus an immutable content identity. Tags for humans, digests for deployment. *(Q2, Q11, Q12, Q15)*

**Image versus container** — artifact versus process; one image, many containers; immutable layers plus one ephemeral writable layer. *(Q1)*

**Task versus service** — a unit of execution versus a supervising controller. Finite work is a task; continuous work is a service. *(Q5)*

**Execution role versus task role versus instance role** — platform identity at start-up, application identity at run time, host identity for the cluster. Start-up failure → execution role; application `AccessDenied` → task role; instance missing from the cluster → instance role. *(Q6, Q8)*

**Fargate versus ECS on EC2** — no host, no layer cache, no instance role, per-task microVM isolation, versus host control and cross-task layer caching. This distinction changes the correct answer to image-size and start-up questions. *(Q10, Q14)*

**Build once and promote versus rebuild per environment** — a known artifact versus a newer artifact. Age is solvable by scheduling; an unknown artifact is not solvable at all. *(Q11)*

**Build-time secret versus run-time secret** — a BuildKit secret mount versus the ECS `secrets` block or a task role. Never `ARG`, never `ENV`, never `COPY`. *(Q7)*

**Preventive versus detective control** — constrain the present versus preserve the past. Evidentiary requirements need both. *(Q12)*

**Expire versus transition to archive (ECR lifecycle)** — reclaim cost by deletion versus by cheaper storage. Archive keeps the audit evidence. *(Q9, Q12)*

**Faster launches versus no errors during spikes** — latency reduction versus headroom and admission control. Different problems, different remedies. *(Q14)*

---

## 4. Common mistakes on this question set

1. Calling a container "a lightweight VM". It shares the host kernel, and every isolation limit follows from that. *(Q3)*
2. Confusing "the image is read-only" with "the container filesystem is read-only". The latter is writable but ephemeral; read-only is opt-in hardening. *(Q1)*
3. Believing that deleting a file in a later layer, or squashing afterwards, removes a leaked secret. It must be rotated. *(Q7)*
4. Using `--build-arg` for credentials. Build arguments are recorded in the image configuration and visible in `docker history`. *(Q7)*
5. Blaming the **task role** for `CannotPullContainerError`. Pulls, secret injection and log-driver setup use the **execution** role. *(Q6, Q8)*
6. Creating `ecr.api` and `ecr.dkr` endpoints while omitting the **S3 gateway endpoint** — authentication succeeds and then the layer download hangs. *(Q6)*
7. Reading only "it failed to pull" instead of the exact message. Timeout, `AccessDenied` and `manifest not found` point at three different subsystems. *(Q6)*
8. Assuming the ECR console shows all stored images. Untagged manifests are frequently the majority of billed bytes. *(Q9)*
9. Applying a lifecycle policy without running `start-lifecycle-policy-preview`, and deleting a digest a running service still needs. *(Q9)*
10. Treating image size as housekeeping on Fargate, where the whole image is pulled for every single task. *(Q10)*
11. Optimising image size when the real cost is a 30-second health-check interval or a 40-second JVM start. Decompose before optimising. *(Q10, Q14)*
12. Assuming build-once-promote-many means shipping stale code. Freshness comes from rebuild frequency, not rebuild location. *(Q11)*
13. Believing a scan run today tells you what you knew a year ago. Snapshot findings with first-observed timestamps. *(Q12)*
14. Containerising a stateful application and calling it finished. Local-disk session state turns every routine task replacement into a user-visible failure. *(Q13)*
15. Fixing session state with an EFS mount. EFS is for genuinely shared files; session state belongs in Redis or DynamoDB. *(Q13)*
16. Setting `-Xmx` from host RAM inside a container, so the cgroup OOM-kills the task. Use `-XX:MaxRAMPercentage`. *(Q3, Q13)*
17. Using shell-form `ENTRYPOINT`, so the JVM never receives `SIGTERM` and shutdown hangs until `stopTimeout`. *(Q3, Q13)*
18. Believing a nightly base rebuild patches production. Only a downstream rebuild plus redeploy does — and only if adoption is measured. *(Q15)*
19. Shipping `curl`, a shell and the AWS CLI to production for "debuggability" when ECS Exec and debug sidecars provide it without the blast radius. *(Q15)*
20. Using `latest` anywhere in a Dockerfile or a task definition. *(Q2, Q15)*

---

## 5. Quick revision notes

**Images and layers**

- Image = read-only layers + manifest + configuration. Container = a process with a writable layer on top.
- Layers are immutable and additive. Deletion writes a whiteout; the bytes still ship.
- Only the final stage of a multi-stage build is shipped. Order instructions least-changing first.
- Build secrets: `RUN --mount=type=secret,id=X` with `docker build --secret id=X,src=…`. Never `ARG`, `ENV` or `COPY`.

**Tags and digests**

- Tag = mutable pointer. Digest = SHA-256 of the manifest = identity.
- Deploy by digest. Enable ECR tag immutability. Build once, promote the digest.

**Kernel mechanisms**

- Namespaces → visibility → per-task ENI in `awsvpc`, and PID 1 signal duties.
- cgroups → consumption → memory over limit is an OOM kill; CPU over limit is throttling.
- OverlayFS → composition → layer caching, copy-up cost, deleted files persisting.
- Shared kernel → containers isolate processes, not machines → Fargate microVMs.

**ECS**

- Task = execution. Service = supervision, load balancing, rolling deploys, auto scaling.
- Three roles: execution (pull, secrets, logs), task (application AWS calls), container instance (EC2 host, cluster registration).
- Timestamps: `createdAt` → `pullStartedAt` → `pullStoppedAt` → `startedAt`; pull duration = `pullStoppedAt` − `pullStartedAt`.
- Fargate caches nothing between tasks: every task pulls the whole image.

**Pull-failure triage**

```
Timeout        → route table, NAT / VPC endpoints (including S3 gateway), SG, NACL, private DNS
AccessDenied   → execution role, repository policy, KMS key policy, endpoint policy
Not found      → account, Region, repository, tag in the URI; architecture mismatch
Rate limited   → upstream credentials or ECR pull-through cache
```

**ECR cost**

- Charged per GB-month of storage. Nothing is deleted by default.
- Untagged manifests accumulate from re-pushed moving tags.
- Lifecycle policy: keep the last N release tags, keep fewer dev tags, expire untagged after about 14 days. Preview first. Transition to archive rather than expire where retention is required.

**Start-up latency on Fargate**

```
alarm → scaling reaction (5–15 s) → microVM + ENI (10–20 s) → pull (20–30 s)
      → application start (20–30 s) → health checks (15–30 s)
```

- Best first fix: health-check interval and healthy threshold.
- Then: image size, same-Region ECR, VPC endpoints, zstd, SOCI above ~250 MB.
- Then: JVM start-up — CDS, tiered compilation, adequate vCPU, CRaC or native image.
- Reactive scaling is always late: buy headroom, schedule and predict, shed load, retry with jitter.

**Legacy containerisation checklist**

Stateless → logs to stdout → configuration from the environment → base pinned by digest → non-root → `MaxRAMPercentage` → exec-form entrypoint with `SIGTERM` handling → readiness endpoint → deployment circuit breaker → gradual cut-over.

**Regulated supply chain**

Pinned hermetic build → SBOM + provenance + signature keyed to the digest → ECR with tag immutability, enhanced scanning and archive retention → digest-pinned task definitions deployable only by the pipeline role → CloudTrail with log file validation plus ECS state-change events into S3 with Object Lock → Athena joins date → digest → commit → findings known at that time.

---

## 6. How the set builds understanding

```
Q1, Q4, Q5              Beginner
   ↓                    Vocabulary: image, container, layer, stage, task, service
Q2, Q3, Q7              Intermediate — mechanism
   ↓                    Why immutability implies digests, and why layers behave as they do
Q6, Q8, Q9              Intermediate — application
   ↓                    Troubleshoot a pull, separate three identities, control registry cost
Q10                     The hinge of the set
   ↓                    An artifact property is reframed as a measurable system property
Q11, Q15                Advanced — evaluation
   ↓                    Judge a proposal: concede the goal, locate the mechanism's defect
Q12, Q13, Q14           Advanced — design and analysis
                        Supply chain, migration, latency budget
```

The early questions establish that an image is an immutable layered artifact and a container is a process — a distinction every later question depends on. Q2, Q3 and Q7 convert that into consequences: because layers are immutable, digests are identity and deleted files persist; because containers are kernel-isolated processes, they get their own ENI and are killed by cgroups rather than politely throttled. Q6 to Q9 exercise those consequences operationally, where the real skill is reading evidence — an error string, a cost curve, an IAM denial — and mapping it to the mechanism responsible. Q10 is the hinge: it takes "image size", which a beginner sees as tidiness, and shows it is a term in scale-out latency and recovery time, and therefore something to measure with a named metric. Everything after Q10 assumes that reframing. Q11 and Q15 ask you to evaluate proposals that are wrong in mechanism but right in motive, where the concession earns as many marks as the critique. Q12, Q13 and Q14 ask you to design or decompose: a supply chain built backwards from an evidentiary requirement, a migration ordered by risk with one line held under pressure, and a latency budget decomposed before anything is optimised.

The through-line: **know the mechanism, measure before you optimise, prefer the known artifact over the new one, and be explicit about what your design cannot do.**

---

## Sources

- [Amazon ECR lifecycle policy rule parameters](https://docs.aws.amazon.com/AmazonECR/latest/userguide/lifecycle_policy_parameters.html) — `tagPatternList`, `countType` values including `sinceImageTransitioned`, and the `expire` and `transition` action types with `targetStorageClass: archive`.
- [Linux containers on Fargate: container image pull behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-pull-behavior.html) — no image or layer caching between Fargate tasks; SOCI lazy loading recommended above ~250 MB; zstd for faster decompression.
- [Amazon ECR enhanced scanning](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-scanning-enhanced.html) — continuous scanning of OS and programming-language packages via Amazon Inspector; configurable re-scan duration and `SCAN_ELIGIBILITY_EXPIRED`.
- [Amazon ECR interface VPC endpoints](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html) — `ecr.api` and `ecr.dkr` endpoints, and the requirement for an Amazon S3 gateway endpoint because image layers are stored in S3.
- [Amazon ECS interface VPC endpoints](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/vpc-endpoints.html) — which endpoints Fargate tasks require, and which apply only to the EC2 launch type.
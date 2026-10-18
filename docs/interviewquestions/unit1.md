# Unit 1: Interview Questions

## 1.1 AWS Cloud Overview

### Conceptual Questions

**1. Explain the difference between a Region, an Availability Zone, and an Edge Location, and give one architectural decision driven by each.**

??? success "Model answer"

    A Region is a separate geographic area containing at least three isolated Availability Zones in modern Regions; it is the unit of data residency and large-scale fault isolation. An Availability Zone is one or more discrete data centres with independent power, cooling and networking, close enough to its siblings for synchronous replication. An Edge Location is a small point of presence near users that hosts CloudFront, Route 53, Shield, WAF and Global Accelerator entry points but cannot run EC2 or databases.

    Each layer drives a different decision. The Region is chosen by compliance first, then latency, service availability and cost, for example keeping personal data in-country. The AZ count decides availability: production workloads are spread across at least two, preferably three, AZs with a Multi-AZ database. Edge Locations decide how content reaches users: static assets and cacheable API responses are served through CloudFront rather than directly from the Region.

**2. Why does synchronous replication generally stop at the Region boundary? What physical constant is responsible?**

??? success "Model answer"

    Synchronous replication means a write is not acknowledged until every replica has it, so each write pays at least one network round trip. Between AZs that round trip is around 1 to 2 ms, which is acceptable. Between Regions it is tens to hundreds of milliseconds, which would make every write that slow.

    The constant responsible is the speed of light in optical fibre, roughly two thirds of its speed in a vacuum, adding about 5 microseconds per kilometre each way. No engineering removes it, so multi-Region data designs accept asynchronous replication with an RPO above zero (for example Aurora Global Database or S3 Cross-Region Replication), or accept slow cross-Region writes.

**3. What is static stability, and why does it matter during an AZ event?**

??? success "Model answer"

    Static stability means a system keeps working through a failure without needing to change anything: no new launches, no configuration updates and no control-plane API calls. Capacity and routing that will be needed during the failure are already in place before it happens.

    It matters during an AZ event because the control planes you would rely on to recover (Auto Scaling launches, DNS record changes, new instance capacity) may themselves be impaired or congested as every customer tries to recover at once. A statically stable design runs enough spare capacity in the remaining AZs to absorb the lost AZ's share, and relies on data-plane mechanisms such as load balancer health checks to stop sending traffic to the failed zone.

### Scenario Questions

**4. A South African fintech must keep customer data in-country, survive a data-centre fire with zero data loss, and serve a marketing site quickly worldwide. Design the placement.**

??? success "Model answer"

    Deploy in the Africa (Cape Town) Region, `af-south-1`, so customer data stays in South Africa, and enforce that with an SCP using `aws:RequestedRegion` so resources cannot be created elsewhere. Run the application across all three AZs in that Region, and use a Multi-AZ database (RDS Multi-AZ or Aurora) whose synchronous replication to another AZ means a fire in one data centre loses no committed data.

    Host the marketing site in a private S3 bucket served globally through CloudFront with Origin Access Control, so it is fast worldwide without exposing the bucket. Confirm that the marketing site contains no customer data, because CloudFront caches content at edge locations outside the country.

    **In short:** af-south-1, Multi-AZ synchronous DB, private S3 + CloudFront for the site.

**5. Your CloudFront hit ratio is 12%. What are the three most likely configuration causes and their fixes?**

??? success "Model answer"

    The most likely cause is an over-broad cache key: forwarding all cookies, all query strings or headers such as `User-Agent` fragments the cache so almost every request is unique. The fix is a cache policy that includes only the values that actually change the response.

    The second cause is short or zero TTLs, often because the origin sends `Cache-Control: no-cache` or `max-age=0`. Fix the origin headers or set minimum and default TTLs in the cache policy, and use versioned file names so long TTLs are safe. The third cause is that dynamic, uncacheable paths share a behaviour with static content; split them into separate behaviours (for example `/static/*` with long caching and `/api/*` with caching disabled) so the hit ratio of cacheable content is measured and optimised separately. Enabling Origin Shield can also raise the effective hit ratio for globally distributed users.

### Architecture Questions

**6. Design a two-Region architecture with RTO 15 minutes and RPO 1 minute for a REST API + relational data. Justify warm standby vs active-active, the replication technology, and the failover trigger.**

??? success "Model answer"

    An RTO of 15 minutes and an RPO of one minute point to warm standby rather than active-active. Active-active would give near-zero RTO but requires multi-writer data handling and roughly doubles cost; backup-and-restore or pilot light cannot meet a 15-minute RTO reliably. In warm standby the second Region runs a scaled-down but complete copy of the API tier, kept current by the same infrastructure-as-code pipeline.

    For relational data, use Aurora Global Database: storage-level asynchronous replication with typical lag under a second comfortably meets a one-minute RPO, and a secondary cluster can be promoted in minutes. The failover trigger should be health checks on a deep application endpoint feeding Route 53 failover routing (or Application Recovery Controller routing controls), with a documented and rehearsed runbook that promotes the database, scales the standby compute and shifts traffic. Raise service quotas in the standby Region in advance so it can scale when needed.

**7. How would you guarantee that _only_ CloudFront can reach your ALB origin?**

??? success "Model answer"

    Put the ALB in a security group that allows inbound HTTPS only from the AWS-managed prefix list for CloudFront origin-facing servers (`com.amazonaws.global.cloudfront.origin-facing`). This blocks direct internet access at the network layer while letting CloudFront reach the origin.

    Because other CloudFront distributions also use those addresses, add a second check: configure CloudFront to send a secret custom header and add an ALB listener rule that forwards only requests carrying that header, returning 403 otherwise, and rotate the secret regularly. Alternatively, CloudFront VPC origins let CloudFront reach an internal ALB in a private subnet, so the load balancer has no public exposure at all. Attaching AWS WAF to the distribution adds application-layer filtering.

### Troubleshooting Questions

**8. Users in one city report errors; your Regional dashboards look healthy. Walk through your diagnosis.**

??? success "Model answer"

    A localised error with healthy Regional dashboards suggests a problem at the edge or on the internet path, not in the Region. First check CloudFront metrics and alarms in `us-east-1` (where CloudFront publishes them) and the distribution's 4xx and 5xx error rates, then analyse CloudFront standard or real-time logs grouped by edge location to see whether errors concentrate at one point of presence.

    Next, test from outside AWS: synthetic canaries or third-party probes from multiple geographies, and CloudWatch Internet Monitor if enabled, to separate an edge issue from an ISP or DNS issue in that city. Check the AWS Health Dashboard for CloudFront or edge events, and confirm Route 53 resolution from the affected networks. If one edge location is at fault, the options are to wait for AWS mitigation, use an origin failover group, or temporarily steer affected users to an alternative endpoint.

    **In short:** edge PoP issue → CloudFront metrics in us-east-1, synthetics from multiple geographies, AWS Health.

**9. After deploying new JavaScript, some users worldwide still receive the old file for hours. Why, and what are the short-term and long-term fixes?**

??? success "Model answer"

    The edge caches still hold the old object until its TTL expires, and browsers may also cache it according to its `Cache-Control` header. Because the file name did not change, neither CloudFront nor the browser knows a new version exists.

    The short-term fix is a CloudFront invalidation for the affected paths, accepting that browser caches may still need to expire or be bypassed. The long-term fix is versioned (content-hashed) file names such as `app.3f9a1c.js` referenced from an HTML page with a short TTL: every deployment produces a new URL, so long TTLs become safe and invalidations are rarely needed.

---

## 1.3 AWS Compute Services

### Conceptual Questions

**1. Explain the difference between vertical and horizontal scaling, and why cloud-native design prefers the latter.**

??? success "Model answer"

    Vertical scaling increases the capacity of a single instance (a larger instance type); horizontal scaling adds more instances. Vertical scaling is bounded by the largest available instance, usually requires a restart, and leaves a single failure domain. Horizontal scaling is effectively unbounded, allows in-place replacement of unhealthy members, and distributes failure risk across Availability Zones. Cloud-native design prefers horizontal scaling because it makes capacity a runtime property managed by a control loop rather than a procurement decision. The precondition is statelessness: session and durable state must be externalised to DynamoDB, ElastiCache, RDS, or S3.

**2. What is the difference between an ECS task, a task definition, and a service?**

??? success "Model answer"

    A task definition is an immutable, versioned blueprint: container images, CPU and memory reservations, port mappings, environment variables, logging configuration, and the task and execution IAM roles. A task is a running instantiation of one revision of that blueprint  one or more containers scheduled together on the same host and sharing a network namespace. A service is a controller that maintains a desired count of tasks, replaces unhealthy ones, registers them with a load balancer target group, and orchestrates rolling or blue/green deployments. The mental model is class, object, and supervisor.

**3. Why does AWS Lambda have a cold start, and what determines its duration?**

??? success "Model answer"

    A cold start occurs when no warm execution environment exists for an invocation, so Lambda must allocate a Firecracker microVM, download and decrypt the deployment package or container image, initialise the runtime, and execute the function's initialisation code before the handler runs. Duration is driven by package or image size, runtime choice (interpreted runtimes such as Python and Node.js initialise faster than JVM or .NET), the amount of work performed outside the handler, the memory setting (which proportionally allocates vCPU, so more memory means faster initialisation), and whether the function is attached to a VPC. Provisioned concurrency and SnapStart eliminate or drastically reduce this latency.

**4. Distinguish the ECS task execution role from the ECS task role.**

??? success "Model answer"

    The execution role is assumed by the ECS agent and Fargate infrastructure, not by application code. It grants permission to pull images from ECR, retrieve secrets from Secrets Manager or SSM Parameter Store for injection into the container environment, and write to CloudWatch Logs. The task role is assumed by the application process inside the container and is what the AWS SDK picks up through the container credential provider. Least privilege requires two distinct roles; conflating them grants the application infrastructure permissions it should never hold.

**5. What does AWS Fargate actually remove from the operational burden, and what does it not?**

??? success "Model answer"

    Fargate removes the EC2 layer: no AMI patching, no instance right-sizing, no cluster capacity management, no bin-packing, no SSH access, and per-task rather than per-instance billing granularity. It does not remove container image hygiene, application-level patching, IAM design, networking design (tasks still occupy subnets and ENIs), observability, or cost governance. It also does not remove the need to understand orchestration semantics  deployment strategies, health checks, and draining still apply.

**6. Explain the concept of a control plane and a data plane using ECS and EKS as examples.**

??? success "Model answer"

    The control plane holds desired state, makes scheduling and placement decisions, and reconciles actual state toward desired state; the data plane executes workloads and carries request traffic. In ECS, the control plane is an AWS-managed regional service holding cluster, service, and task-definition state, while the data plane is EC2 instances running the ECS agent, or Fargate capacity. In EKS, the control plane is a managed, multi-AZ Kubernetes API server and etcd cluster, and the data plane is managed node groups, self-managed nodes, or Fargate profiles. The distinction matters operationally: a control-plane outage generally stops new deployments and scaling decisions, but already-running data-plane workloads continue serving traffic.

**7. Why is an Auto Scaling group with `ELB` health check type materially different from one with `EC2` health check type?**

??? success "Model answer"

    The `EC2` health check reports only on hypervisor-level instance status  whether the instance is running and passing system and instance status checks. An instance whose application process has crashed, deadlocked, or is returning HTTP 500 still passes. The `ELB` health check type delegates the decision to the load balancer's target group health check, which probes an application endpoint. Only the latter detects application-level failure and triggers replacement. This is a very common production defect.

### Scenario Questions

**1. A team runs a nightly report that takes 45 minutes and reads several gigabytes from S3. They propose AWS Lambda. Evaluate.**

??? success "Model answer"

    Lambda is unsuitable as a single invocation: the maximum execution duration is 15 minutes, which is a hard limit, and ephemeral storage is bounded. Three viable redesigns exist. First, decompose the job into a map-reduce shape  a Step Functions Distributed Map fanning out many short Lambda invocations over S3 key ranges, then a reduce step. Second, run it as an ECS or EKS task on Fargate, invoked on a schedule by EventBridge Scheduler, which has no duration limit and generous memory. Third, if the work is fundamentally an analytical query over S3 data, replace the compute entirely with Athena or an EMR Serverless job. The architectural lesson is that a duration limit is a signal to reconsider the decomposition, not merely to pick a bigger runtime.

**2. A microservice receives steady traffic of roughly 200 requests per second with brief 10x spikes at lunchtime. Cost is a first-class concern. Which compute model?**

??? success "Model answer"

    Steady baseline plus predictable spikes favours containers on ECS or EKS with Fargate for burst capacity, or EC2 with a Savings Plan covering the baseline and Spot or on-demand for the peak. Lambda's per-invocation pricing becomes expensive at sustained high request rates compared with a continuously utilised container, so at 200 requests per second sustained, containers usually win on cost while Lambda wins on operational simplicity. A defensible answer states the crossover reasoning explicitly: Lambda is optimal for spiky, low-duty-cycle workloads; containers are optimal once utilisation is high and steady. Compute Savings Plans apply across EC2, Fargate, and Lambda, so the baseline can be committed regardless of the model chosen.

**3. A regulated financial customer requires that no other tenant's workload share the physical host. What are the options and their trade-offs?**

??? success "Model answer"

    Dedicated Instances guarantee hardware isolation at the account level but do not give visibility of or control over socket and core placement. Dedicated Hosts additionally expose the physical server, enabling per-socket or per-core software licensing (bring-your-own-license for Windows Server or Oracle) and affinity so an instance returns to the same host after a stop and start. Both carry a substantial cost premium and reduce placement flexibility, which weakens elasticity. On Fargate each task runs in its own isolation boundary with dedicated kernel, which satisfies many isolation requirements without dedicated hardware, but does not satisfy a literal "no shared physical hardware" clause. The architect's job is to determine whether the requirement is genuinely about physical hardware or about isolation and compliance evidence, because the answer changes the cost by an order of magnitude.

**4. An EKS cluster experiences pods stuck in `Pending` with the event `too many pods`. Diagnose.**

??? success "Model answer"

    This is almost always the ENI-based IP address limit of the Amazon VPC CNI. Each node can host a number of pods bounded by the number of ENIs its instance type supports multiplied by the IP addresses per ENI, minus one for the node itself. Small instance types therefore host very few pods regardless of free CPU and memory. Remedies include selecting larger instance types, enabling prefix delegation on the VPC CNI (which assigns /28 prefixes rather than individual secondary IPs and greatly increases pod density), or adopting custom networking with a secondary CIDR. A secondary possibility is that the subnets themselves have exhausted their IP space, which is a CIDR planning failure.

**5. A Lambda function attached to a VPC intermittently fails to reach an RDS database, and the team observes connection exhaustion on the database.**

??? success "Model answer"

    Lambda scales horizontally by creating concurrent execution environments, each of which opens its own database connection. At high concurrency this multiplies into thousands of connections and exceeds the RDS `max_connections` parameter, which itself scales with instance memory. The correct remedy is Amazon RDS Proxy, which maintains a pooled, multiplexed set of connections to the database and lets Lambda functions borrow from the pool. Supporting measures include setting reserved concurrency on the function to bound the blast radius, opening the connection outside the handler so it is reused across warm invocations, and confirming that the security groups allow traffic from the Lambda ENIs' security group on the database port.

### Architecture Questions

**1. Design a compute layer for a three-tier e-commerce application that must survive the loss of an Availability Zone.**

??? success "Model answer"

    Place an Application Load Balancer across at least two, preferably three, Availability Zones in public subnets. Run the application tier as an ECS service on Fargate, or an Auto Scaling group, spread across the same Availability Zones in private subnets, with a desired count set so that N-1 zones can carry full peak load. Target tracking scaling on request count per target or on CPU maintains headroom. Externalise session state to ElastiCache or DynamoDB so any instance can serve any request. Use RDS Multi-AZ or Aurora with reader instances in each zone. Verify that the ASG or service uses `ELB` health checks, that deployment uses rolling or blue/green with a minimum healthy percentage, and that the NAT Gateway is provisioned per zone so that the loss of one zone does not break egress for the others.

**2. When would you choose EKS over ECS, given that ECS is simpler?**

??? success "Model answer"

    Choose EKS when the organisation needs the Kubernetes API and ecosystem  Helm charts, operators, custom resource definitions, service meshes such as Istio, GitOps tooling such as Argo CD or Flux  or when workload portability across clouds and on-premises is a genuine requirement, or when the engineering organisation already has Kubernetes expertise and multi-cluster tooling. Choose ECS when the priority is minimal operational surface, deep and native AWS integration, no control-plane charge, and a smaller learning curve. The decision is fundamentally about ecosystem leverage and existing skills, not about technical capability, because both can run the same containers with comparable reliability.

**3. Design an event-driven image-processing pipeline and justify the compute choice at each stage.**

??? success "Model answer"

    An upload lands in S3, which emits an event to EventBridge or directly to SQS. A Lambda function consumes the queue, generates thumbnails, and writes results back to S3 and metadata to DynamoDB  Lambda is correct here because the work is short, stateless, embarrassingly parallel, and bursty, and the cost at low duty cycle is negligible. If a stage requires heavy machine-learning inference exceeding 15 minutes or requiring GPUs, that stage moves to an ECS Fargate task or an EC2 GPU instance triggered by Step Functions, because Lambda does not offer GPUs. A dead-letter queue captures poison messages, and Step Functions orchestrates multi-stage workflows so that retries, timeouts, and error paths are declarative rather than embedded in application code.

**4. How would you achieve zero-downtime deployment for a containerised service, and what are the trade-offs of each strategy?**

??? success "Model answer"

    Rolling update with a minimum healthy percentage of 100 and a maximum percent above 100 launches new tasks before draining old ones; it is cheap and simple but briefly runs two versions concurrently, which requires backward-compatible schemas and APIs. Blue/green through CodeDeploy stands up a complete replacement task set behind a second target group and shifts traffic all at once, linearly, or canary, with automatic rollback on CloudWatch alarms; it doubles capacity cost during deployment but gives a clean and fast rollback. Canary within a rolling update, or Lambda weighted aliases for serverless, exposes a small traffic percentage to the new version first, which minimises blast radius at the cost of a longer deployment window and more complex observability.

### Troubleshooting Questions

**1. An ECS Fargate task repeatedly stops with `CannotPullContainerError`.**

??? success "Model answer"

    The task cannot reach ECR. In a private subnet without a NAT Gateway, create interface VPC endpoints for `ecr.api` and `ecr.dkr`, a Gateway endpoint for S3 (ECR layers are stored in S3), and an interface endpoint for `logs` if CloudWatch Logs is the log driver. Alternatively confirm the route to a NAT Gateway. Secondary causes are an execution role lacking `ecr:GetAuthorizationToken` and the ECR read permissions, an incorrect image tag, or a task launched with `assignPublicIp` disabled in a public subnet.

**2. An EC2 instance in a private subnet cannot install packages from the internet.**

??? success "Model answer"

    Confirm a NAT Gateway exists in a public subnet in the same Availability Zone, that the private subnet's route table has a `0.0.0.0/0` route to that NAT Gateway, that the public subnet's route table has a `0.0.0.0/0` route to an Internet Gateway, that the NAT Gateway subnet is genuinely public, and that the outbound security group and the network ACLs on both subnets permit the traffic  remembering that NACLs are stateless and therefore need an inbound ephemeral-port rule for return traffic.

**3. A Lambda function reports `Task timed out after 3.00 seconds` only in production.**

??? success "Model answer"

    The default timeout of three seconds is almost never appropriate for a function performing network calls. Raise the timeout to a value above the observed p99 duration but below the caller's tolerance, and set it deliberately rather than by default. Then investigate why production is slower: cold starts, VPC-attached ENI behaviour, a downstream dependency with higher latency at scale, connection establishment inside the handler rather than outside it, or insufficient memory throttling the vCPU allocation. Enable AWS X-Ray to attribute the latency to a specific downstream segment.

**4. An Auto Scaling group continuously launches and terminates instances.**

??? success "Model answer"

    This is a scaling or health-check thrash loop. The common causes are a health check grace period shorter than the application's boot time, so instances are terminated before they become healthy; a failing user-data bootstrap script; an `ELB` health check pointing at a path that the application does not serve, or one that requires authentication; step or simple scaling policies without adequate cooldown fighting each other; or an unhealthy AMI. Inspect the Auto Scaling activity history, the target group health-check reason codes, and the instance console output.

**5. An EKS pod cannot assume its IAM role and receives `AccessDenied` from the AWS SDK.**

??? success "Model answer"

    Verify the full IRSA or EKS Pod Identity chain: the cluster has an OIDC identity provider registered in IAM; the IAM role's trust policy references that provider and constrains the `sub` claim to the correct namespace and service account; the Kubernetes ServiceAccount carries the `eks.amazonaws.com/role-arn` annotation; the pod spec sets `serviceAccountName`; and the SDK version supports web identity token credentials. A frequent error is a trust policy that matches the wrong namespace, which fails silently and falls back to the node instance role.

---

## 1.4 AWS Storage Services

### Conceptual Questions

**1. Explain the difference between object, block, and file storage, and why AWS provides three separate services rather than one.**

??? success "Model answer"

    Object storage stores immutable whole items in a flat keyspace accessed by API and scales without bound because it forgoes in-place mutation. Block storage exposes a raw device supporting random in-place writes with sub-millisecond latency, at the cost of being attached to one host in one Availability Zone. File storage provides shared POSIX semantics through a distributed metadata service, at the cost of higher latency and price. The trade-offs are mutually exclusive, so a single service cannot satisfy all three access patterns.

**2. What does eleven nines of durability actually mean, and what does it not protect against?**

??? success "Model answer"

    It is a statistical design target for annual data loss from hardware and facility failure, achieved through erasure coding across at least three Availability Zones with continuous background repair. It provides no protection against accidental deletion, malicious deletion, application bugs, or misconfigured permissions. Those require versioning, MFA Delete, Object Lock, cross-account replication, and backups.

**3. Why can an EBS volume not be attached to an instance in another Availability Zone?**

??? success "Model answer"

    Because EBS replicates synchronously within a single Availability Zone to preserve sub-millisecond write latency. Replicating across zones separated by tens of kilometres would add round-trip latency that would defeat the purpose of block storage. Cross-zone movement is therefore achieved asynchronously through snapshots.

**4. Describe S3's consistency model and how it changed.**

??? success "Model answer"

    S3 now provides strong read-after-write consistency for `PUT`, overwrite, and `DELETE` operations on all objects in all Regions, with no performance penalty. Previously, overwrites and deletes were eventually consistent. Bucket configuration changes and Cross-Region Replication remain eventually consistent and asynchronous respectively.

**5. What is the difference between the control plane and the data plane, and why does it matter?**

??? success "Model answer"

    The control plane provisions and configures resources; the data plane moves bytes. AWS engineers data planes for static stability so they continue functioning during control plane impairment. The design implication is to pre-provision resources and never place control plane calls on a user request's critical path.

### Scenario Questions

**1. A team stores ten million one-kilobyte log files per day in S3 Standard and complains the bill is dominated by requests. What do you recommend?**

??? success "Model answer"

    Aggregate the logs into larger compressed objects, ideally per five-minute or hourly window, before writing. This reduces `PUT` request count by orders of magnitude, reduces per-object overheads, and makes subsequent analytics far cheaper because Athena scans fewer, larger files. Kinesis Data Firehose performs this buffering natively.

**2. A relational database on EC2 shows increasing query latency during nightly batch jobs. `BurstBalance` on the gp2 data volume drops to zero at 02:00. What is happening and how do you fix it?**

??? success "Model answer"

    The gp2 volume is exhausting its I/O credits and falling back to baseline performance of three IOPS per GiB. Migrate the volume to gp3 with explicitly provisioned IOPS and throughput sized to the measured peak, which removes the credit mechanism entirely. Verify that the instance type's EBS bandwidth can deliver the provisioned figure.

**3. A legacy Java application requires a shared directory across a fleet of servers in three Availability Zones and uses POSIX file locking. Migration to object storage is not funded. What do you propose?**

??? success "Model answer"

    Amazon EFS with mount targets in all three Availability Zones, Elastic throughput, encryption at rest and in transit, an access point enforcing the application's root directory and POSIX identity, and a security group permitting TCP 2049 only from the application security group. No application change is required.

**4. Auditors require that financial records be immutable for seven years and that no administrator can delete them early. Design the storage.**

??? success "Model answer"

    An S3 bucket with versioning enabled and Object Lock in Compliance mode with a seven-year retention period, SSE-KMS with a customer managed key whose key policy separates duties, CloudTrail data events delivered to a separate logging account, Block Public Access fully enabled, and replication to a second Region for continuity. Compliance mode cannot be shortened or removed by any principal, including the account root user.

**5. A machine learning team runs distributed training across two hundred GPU instances reading the same fifty-terabyte dataset. S3 reads are too slow for their epoch times. What do you propose?**

??? success "Model answer"

    Stage the dataset from S3 into Amazon FSx for Lustre, which links directly to the S3 bucket and provides hundreds of gigabytes per second of aggregate throughput with POSIX semantics. S3 remains the durable system of record; FSx for Lustre is the high-performance scratch layer for the duration of the training run.

### Architecture Questions

**1. Design storage for a multi-tenant SaaS document platform serving ten thousand tenants.**

??? success "Model answer"

    Use a single bucket with a `tenant-id/` prefix per tenant rather than a bucket per tenant, because bucket count is a limited resource. Enforce isolation through IAM session policies scoped to the tenant prefix, issued by an identity broker, or through S3 Access Points with per-tenant policies. Encrypt with SSE-KMS, enable versioning with noncurrent expiry, apply Intelligent-Tiering, and serve reads through CloudFront with signed URLs.

**2. Design a disaster recovery strategy for a system whose Recovery Point Objective is fifteen minutes and Recovery Time Objective is one hour.**

??? success "Model answer"

    For S3, enable Cross-Region Replication with Replication Time Control, which provides a fifteen-minute Service Level Agreement. For EBS-backed databases, take snapshots more frequently than the Recovery Point Objective or use database-native replication such as an RDS cross-Region read replica, which is the better answer given a fifteen-minute target. For EFS, enable EFS replication. Maintain the target Region's infrastructure as code so it can be provisioned within the Recovery Time Objective, and rehearse the failover.

**3. How would you architect persistent storage for a Kubernetes platform hosting both stateless web services and a Prometheus monitoring stack?**

??? success "Model answer"

    Stateless services keep no volumes and externalise state to S3 and RDS. Prometheus runs as a StatefulSet with EBS `ReadWriteOnce` persistent volumes provisioned by the EBS CSI driver, using `WaitForFirstConsumer` binding so the volume is created in the zone the pod is scheduled into. Shared configuration or plugin directories used by multiple replicas use an EFS `ReadWriteMany` volume through the EFS CSI driver with an access point per claim. Long-term metrics are shipped to S3 through Thanos or Amazon Managed Service for Prometheus.

**4. A media company must serve five hundred terabytes of video globally at minimum cost while keeping the origin private.**

??? success "Model answer"

    Store the renditions in S3 with Intelligent-Tiering, serve through CloudFront with Origin Access Control so the bucket is never public, use signed URLs or signed cookies for entitlement enforcement, and set a long cache TTL so the origin request rate and egress cost collapse. Archive masters to Glacier Deep Archive. The dominant saving comes from CloudFront egress pricing being lower than S3 internet egress plus the near-elimination of origin requests.

**5. Design the storage layer for an IoT platform ingesting one million messages per second.**

??? success "Model answer"

    Ingest through IoT Core into Kinesis Data Streams, buffer with Kinesis Data Firehose which aggregates records into large compressed Parquet objects, and write to S3 with prefixes partitioned by date and device group. Catalogue with Glue, query with Athena, and apply lifecycle rules moving data older than ninety days to Glacier Flexible Retrieval. Hot device state that must be read per request lives in DynamoDB, not in S3.

### Troubleshooting Questions

**1. An EC2 instance cannot mount an EFS file system; the command hangs and eventually times out. How do you diagnose it?**

??? success "Model answer"

    Check in order: does a mount target exist in the instance's Availability Zone; does the mount target's security group allow inbound TCP 2049 from the instance's security group; do the subnet's Network ACLs permit both directions including ephemeral ports; is the DNS name resolving, which requires DNS hostnames and DNS resolution enabled on the VPC; and is `amazon-efs-utils` installed if TLS or IAM authorisation is requested.

**2. An application receives intermittent `503 SlowDown` responses from S3 during a bulk load. What is happening?**

??? success "Model answer"

    The request rate against a single partitioned prefix has exceeded the current partition's capacity, and S3 is signalling that it is splitting the partition. The correct response is exponential backoff with jitter, which the AWS SDKs implement by default, combined with spreading writes across more prefixes and ramping up load gradually rather than instantaneously.

**3. A restored EBS volume performs far worse than the original for the first hour. Why?**

??? success "Model answer"

    Volumes created from snapshots are lazily loaded; blocks are fetched from S3 on first access, so initial reads incur additional latency. Enable Fast Snapshot Restore for that snapshot in the target Availability Zone, or force hydration by sequentially reading the whole device with a tool such as `dd` or `fio` before putting the volume into service.

**4. A user reports `AccessDenied` on `ListObjectsV2` but can successfully `GetObject` on known keys. Why?**

??? success "Model answer"

    `s3:ListBucket` is a bucket-level action whose resource must be the bucket ARN, whereas `s3:GetObject` is an object-level action whose resource is the object ARN. The policy almost certainly grants both actions against the object ARN pattern only. Add a statement granting `s3:ListBucket` on the bucket ARN, optionally constrained with the `s3:prefix` condition key.

**5. Storage costs for a bucket are far higher than the sum of visible object sizes. What do you investigate?**

??? success "Model answer"

    Three likely causes: noncurrent object versions accumulating because versioning is on without a lifecycle expiry rule; incomplete multipart upload parts, which are billed but not shown by a standard list operation; and delete markers combined with retained versions. Use S3 Storage Lens or an S3 Inventory report including noncurrent versions, then add lifecycle rules for `NoncurrentVersionExpiration` and `AbortIncompleteMultipartUpload`.

---

## 1.5 AWS Database Services

### Conceptual Questions

**1. Explain the CAP theorem and how it applies to the AWS database portfolio.**

??? success "Model answer"

    The CAP theorem states that in the presence of a network partition, a distributed system must choose between consistency and availability. It is not a claim that you pick two of three in normal operation; partition tolerance is mandatory for any distributed system, so the real choice is what to do when a partition occurs. RDS Multi-AZ chooses consistency: during failover the database is briefly unavailable rather than serving divergent data. DynamoDB offers the choice per read  an eventually consistent read favours availability and latency, a strongly consistent read favours correctness. DynamoDB Global Tables choose availability at the Region level and resolve the resulting conflicts with last-writer-wins. ElastiCache with asynchronous replication chooses availability and accepts the loss of recent writes.

**2. What is the practical difference between a Global Secondary Index and a Local Secondary Index?**

??? success "Model answer"

    An LSI shares the base table's partition key and provides an alternative sort key. It can only be created at table creation, supports strongly consistent reads, shares the base table's provisioned throughput, and constrains any single item collection to 10 GB. A GSI has an entirely independent partition and sort key, may be created or deleted at any time, is always eventually consistent, has its own provisioned throughput, and has no item-collection size constraint. In practice GSIs are used far more often; LSIs are appropriate only when strong consistency on an alternative sort order within a partition is genuinely required.

**3. Why is Aurora's storage architecture significant?**

??? success "Model answer"

    Aurora separates compute from a purpose-built distributed storage service that replicates six ways across three Availability Zones and accepts a write once four of six segments acknowledge it. Only redo log records are shipped to storage; the storage layer materialises pages itself. The consequences are architectural rather than incremental: adding a read replica copies no data because all instances read the same volume, failover does not require catch-up, storage grows and self-heals automatically, backups are continuous and do not affect performance, and a clone can be created almost instantly using copy-on-write. This is the clearest example in the AWS portfolio of re-architecting a component rather than merely managing it.

**4. Explain why a DynamoDB partition key choice determines scalability.**

??? success "Model answer"

    DynamoDB places an item by hashing its partition key and mapping the hash to a physical partition. Throughput and storage are distributed across partitions. If many requests share one partition-key value, they all target one partition, whose throughput is bounded regardless of table-level provisioning, and requests are throttled. Adaptive capacity redistributes some throughput toward hot partitions and isolates severe cases, but it cannot manufacture capacity for a single key. Therefore scalability is a property of key cardinality and access distribution, decided at design time and expensive to change afterwards.

**5. When is caching the wrong answer?**

??? success "Model answer"

    When the workload is write-dominant, since a cache accelerates reads and adds work to writes. When every read must be strongly consistent, because a cache introduces a staleness window. When the access pattern has no locality  a uniform random read over a very large keyspace produces a low hit rate and the cache becomes pure overhead. When the underlying query is already fast and the latency budget is met, because the added component contributes failure modes and operational surface without benefit. And when the real problem is a missing index or an N+1 query pattern, in which case caching hides a defect rather than fixing it.

**6. Distinguish RDS Multi-AZ from RDS read replicas.**

??? success "Model answer"

    Multi-AZ maintains a synchronous standby in a second Availability Zone for availability; in the classic instance deployment the standby is not readable and exists solely to be promoted. Read replicas are asynchronous copies used to scale read throughput, may be in the same Region or a different one, are readable, and require explicit promotion to become writable. Multi-AZ addresses availability; read replicas address performance. The Multi-AZ DB cluster deployment blurs this by providing two readable standbys, which is worth stating explicitly in an interview.

### Scenario Questions

**1. A social application's feed query takes eight seconds under load. The team proposes a larger RDS instance. Evaluate.**

??? success "Model answer"

    A larger instance is a valid short-term mitigation and a poor diagnosis. The first step is to determine where the time is spent using Performance Insights and `EXPLAIN ANALYZE`. Common causes are a missing index producing a sequential scan, an N+1 query pattern issuing one query per feed item, a join that materialises far more rows than are returned, or lock contention. If the query is fundamentally a fan-out read of recent items per followed user, the correct architecture is often a precomputed feed: fan out on write into DynamoDB or into a Redis list per user, so the read becomes a single key lookup. Vertical scaling buys time; the redesign fixes the problem and costs less at steady state.

**2. An online store must guarantee that inventory never goes negative under concurrent purchase.**

??? success "Model answer"

    This is a concurrency-control question, not a database-selection question. In a relational store, use a transaction with `SELECT ... FOR UPDATE` or an atomic `UPDATE inventory SET qty = qty - 1 WHERE sku = ? AND qty > 0` and treat a zero-row result as out of stock. In DynamoDB, use `UpdateItem` with an `ADD` of minus one and a `ConditionExpression` of `qty > :zero`, which is atomic within a single item, or `TransactWriteItems` if the decrement must be atomic with order creation. The critical teaching point is that read-then-write in application code is a race condition, and correctness must come from an atomic conditional operation rather than from application logic.

**3. A team must migrate a 2 TB on-premises Oracle database to AWS with under fifteen minutes of downtime.**

??? success "Model answer"

    Use AWS Database Migration Service with the AWS Schema Conversion Tool if changing engines. DMS performs a full load followed by ongoing change data capture, so the bulk copy happens while the source remains live. The cutover is then a short window in which writes are quiesced, the remaining change backlog drains, the application's connection string is switched, and validation runs. Choose the target deliberately: Aurora PostgreSQL if the intent is to leave commercial licensing behind, RDS for Oracle if the application depends on Oracle-specific features. Plan and rehearse rollback, and validate row counts and checksums with DMS data validation before cutting over.

**4. A DynamoDB table shows heavy throttling although consumed capacity is far below provisioned capacity.**

??? success "Model answer"

    This is the signature of a hot partition. Provisioned capacity is distributed across partitions, so a single key absorbing a disproportionate share of traffic throttles while the table-level metric looks healthy. Use Contributor Insights to identify the dominant keys. Remedies are to choose a higher-cardinality partition key, to apply write sharding by appending a calculated suffix to the key and scattering writes across the resulting keys, to introduce DAX or ElastiCache in front of a hot read key, or to switch to on-demand capacity, which handles bursts more gracefully although it does not eliminate a single-key limit.

**5. An application must serve users in three continents with low read latency and cannot tolerate a full Regional outage.**

??? success "Model answer"

    DynamoDB Global Tables provide multi-active, multi-Region replication with local read and write latency and automatic conflict resolution by last-writer-wins, and Route 53 latency-based routing directs users to the nearest Region. If the workload is relational, Aurora Global Database provides a primary Region with read-only secondary Regions, typical cross-Region replication lag under a second, and promotion of a secondary in a disaster. The essential caveat to state is that last-writer-wins is not a distributed transaction, so any domain in which a lost concurrent update is unacceptable  a financial ledger, for example  requires a single writer Region and an explicit consistency design.

### Architecture Questions

**1. Design the data layer for a ride-hailing platform.**

??? success "Model answer"

    Driver location updates are extremely high-frequency, small, keyed by driver identifier, and ephemeral: DynamoDB with the driver identifier as partition key, a timestamp sort key, and TTL, or a Redis geospatial index if proximity search is required in the request path. Trip state during a ride is a small, hot, frequently updated item: DynamoDB with conditional writes for state transitions. Completed trips, fares, and settlements require ACID guarantees, reporting, and auditability: Aurora PostgreSQL. Surge pricing and matchmaking work from in-memory structures in ElastiCache. Analytics and machine-learning feature generation read from an S3 data lake fed by DynamoDB export and DMS, queried with Athena. Each store is chosen against a stated access pattern, and the services communicate through events on EventBridge rather than through shared tables.

**2. Design a multi-tenant SaaS data architecture supporting both small and regulated enterprise tenants.**

??? success "Model answer"

    Use a hybrid of pool and silo. Small tenants share a DynamoDB table with `TENANT#id` as the partition-key prefix and IAM `dynamodb:LeadingKeys` conditions enforcing isolation, which gives near-linear cost scaling and one operational footprint. Regulated enterprise tenants receive a dedicated Aurora cluster with a customer managed KMS key, satisfying data-isolation and key-control requirements and bounding blast radius. A tenant routing layer resolves a tenant to its data plane. The trade-off to articulate is that the pool model minimises cost and operational effort while concentrating blast radius, and the silo model does the reverse; the hybrid places each tenant where its requirements and its revenue justify.

**3. Design a read path targeting a p99 latency of 20 milliseconds at 100,000 reads per second.**

??? success "Model answer"

    Layer the caches. CloudFront handles cacheable public content at the edge. The application tier consults DAX or ElastiCache, sized to hold the working set, with a hit rate target above 95 percent. DynamoDB serves the residual with a partition key chosen for even distribution, and eventually consistent reads where the staleness is acceptable, halving the capacity cost. The database is provisioned for the miss rate, not the request rate. Instrument the hit rate, the miss latency, and the p99 at each layer, because a cache with a 95 percent hit rate and a slow miss path can still violate a p99 budget  the tail is dominated by misses, which is a point many candidates overlook.

### Troubleshooting Questions

**1. An application intermittently reports "too many connections" against RDS.**

??? success "Model answer"

    Check `DatabaseConnections` against the `max_connections` parameter, which on RDS is typically derived from instance memory. Causes include an application connection pool sized larger than the database allows multiplied by the number of application instances, connections leaked by code that fails to return them to the pool, a serverless tier scaling horizontally with one connection per execution environment, and long-running idle transactions. Remedies are RDS Proxy, correctly sized pools, connection timeouts, and a larger instance class only if the connection demand is genuinely justified.

**2. A read replica is reporting steadily increasing replica lag.**

??? success "Model answer"

    Replication is single-threaded on some engines, so a heavy write burst on the primary, a long-running transaction, or a large `ALTER TABLE` will cause the replica to fall behind. Other causes are an undersized replica instance class relative to the primary, heavy read queries on the replica competing for its resources, and network saturation for a cross-Region replica. Diagnose with the `ReplicaLag` metric and the engine's replication status, then address the cause: size the replica at least as large as the primary, avoid long transactions, and consider Aurora, whose shared storage makes lag typically an order of magnitude smaller.

**3. After deploying a new version, the application returns stale data for several minutes.**

??? success "Model answer"

    The likely causes are reads being routed to a replica when read-after-write consistency is required, or cached entries with a TTL longer than the deployment window, or a cache not invalidated on write. Determine which by bypassing the cache and querying the writer directly. The fix is to route consistency-sensitive reads to the writer, to invalidate or version cache keys on write, and to include a version or build identifier in cache keys so that a deployment naturally invalidates entries whose shape has changed.

**4. A DynamoDB `Query` returns fewer items than expected, and the application misses records.**

??? success "Model answer"

    `Query` and `Scan` return at most 1 MB per call, and any filter expression is applied *after* the read, so a filtered query can return zero items while still consuming capacity and still having more pages. Application code that ignores `LastEvaluatedKey` processes only the first page. The fix is to paginate until `LastEvaluatedKey` is absent, or to use the SDK's paginator, and to prefer key conditions over filter expressions so that the read is selective rather than the filter.

**5. ElastiCache hit rate has fallen from 96 percent to 40 percent with no application change.**

??? success "Model answer"

    Look first at `Evictions` and `DatabaseMemoryUsagePercentage`. A growing dataset that has outgrown the node evicts entries before they are reused. Other causes are a change in key naming that fragmented the keyspace, a TTL set too short, a recent failover or node replacement that started with a cold cache, or a new access pattern with poor locality. Remedies are to scale the node or add shards, to review TTLs, and to warm the cache from a snapshot after a planned replacement.

---

## 1.6 AWS Network Services

### Conceptual Questions

**1. What actually makes a subnet "public"?**

??? success "Model answer"

    Its associated route table contains a route (typically `0.0.0.0/0`) whose target is an Internet Gateway. Nothing else  not the name, not the CIDR, not the auto-assign public IP setting, though a resource in it also needs a public IP or Elastic IP to be reachable from the internet.

**2. Explain the difference between a security group and a network ACL, and when you would deliberately use a NACL.**

??? success "Model answer"

    Security groups attach to network interfaces, are stateful, allow-only, and evaluate all rules with any match permitting. NACLs attach to subnets, are stateless, support deny, and evaluate in rule-number order with first match winning. Use a NACL when you need to *deny* something specific (a malicious CIDR), when you need a subnet-wide guardrail that application teams cannot alter by editing their own security groups, or when a compliance framework requires two independent layers. Application intent belongs in security groups.

**3. Why are five IP addresses unusable in every subnet?**

??? success "Model answer"

    The network address, the VPC router (base plus one), the Amazon DNS resolver (base plus two), an address reserved for future AWS use (base plus three), and the broadcast address. AWS does not support broadcast but still reserves the address.

**4. What is the difference between a Gateway endpoint and an Interface endpoint?**

??? success "Model answer"

    A Gateway endpoint is a route-table entry to a prefix list, supports only S3 and DynamoDB, is free, and is not reachable from outside the VPC (no peering, VPN, or Direct Connect). An Interface endpoint is an ENI with a private IP in your subnet, supports most services plus partner and custom services via PrivateLink, has a security group, is reachable from connected networks, and is charged hourly per Availability Zone plus per gigabyte.

**5. Why does Route 53 offer an Alias record when CNAME already exists?**

??? success "Model answer"

    CNAME cannot be used at a zone apex, requires a second resolution step, and cannot track an AWS resource's changing addresses. Alias records resolve inside Route 53 to the current addresses of an AWS resource, work at the apex, return A or AAAA answers directly, and are not charged when the target is an AWS resource.

**6. What is the practical difference between control plane and data plane, and why does it matter for disaster recovery?**

??? success "Model answer"

    The control plane changes configuration; the data plane carries traffic. Data planes are engineered for much higher availability. A recovery plan that requires control-plane calls (launching instances, changing DNS records) in an impaired Region may fail exactly when it is needed. Prefer pre-provisioned capacity and health-check-driven failover, whose recovery path is data-plane only.

**7. Why does an Internet Gateway not appear in an instance's network configuration?**

??? success "Model answer"

    The IGW performs one-to-one NAT outside the guest. The instance only ever sees its private address; the IGW rewrites source and destination addresses at the VPC boundary. This is why you must never configure a public address inside the operating system.

### Scenario Questions

**1. A regulator requires that a database be provably unreachable from the internet. How do you demonstrate this?**

??? success "Model answer"

    Place it in a subnet whose route table contains only the `local` route plus, at most, Gateway endpoints. Show the route table: with no Internet Gateway, NAT Gateway, or Transit Gateway route, there is no path in either direction regardless of security group configuration. Reinforce with a security group allowing only the application security group on the database port, Network Access Analyzer findings showing no internet path, and Flow Logs as evidence.

**2. Fifteen VPCs across five accounts must communicate, plus on-premises connectivity. Peering or Transit Gateway?**

??? success "Model answer"

    Transit Gateway. Peering would require 105 connections and route entries in every subnet route table, and peering cannot carry on-premises traffic transitively. Transit Gateway gives 15 attachments, one summarised route per VPC, native Direct Connect and VPN attachment, and route tables for segmentation. Share it across accounts with Resource Access Manager.

**3. Your API must return within 100 milliseconds for users worldwide, and some responses are cacheable for 30 seconds.**

??? success "Model answer"

    Regional API Gateway HTTP APIs in two or three Regions, fronted by CloudFront for edge TLS termination and caching, with Route 53 latency-based routing plus health checks between Regions. Use a deliberate cache key with only the parameters that vary the response, enable compression, and keep authorizer results cached.

**4. A partner must call your service, but they refuse to expose it over the internet and their VPC uses the same CIDR as yours.**

??? success "Model answer"

    AWS PrivateLink. Put your service behind a Network Load Balancer, create a VPC endpoint service, and allow their account. They create an Interface endpoint in their VPC, reaching your service via an IP in *their* address space. Overlapping CIDRs are irrelevant because no routes are exchanged.

**5. During a deployment you want 5 percent of production traffic on a new version, with fast rollback.**

??? success "Model answer"

    For containers behind an ALB, use weighted target groups on the listener rule  rollback is a single API call and takes effect immediately with no DNS caching. For whole-stack changes, use Route 53 weighted records, accepting that rollback is bounded by TTL. For API Gateway, use a canary deployment on the stage. Choose based on how fast rollback must be and the granularity of the change.

**6. Costs have risen sharply and the largest line item is `NatGateway-Bytes`.**

??? success "Model answer"

    Enable Flow Logs, query in Athena grouped by destination, and identify the top talkers. Almost always this is S3, ECR image pulls, and CloudWatch Logs. Add a Gateway endpoint for S3 and DynamoDB (free) and Interface endpoints for `ecr.api`, `ecr.dkr`, `logs`, `sts`, and `secretsmanager`. Verify with Flow Logs that traffic has shifted, then confirm the reduction in Cost Explorer.

### Architecture Questions

**1. Design the network for a three-tier application requiring 99.99 percent availability in one Region.**

??? success "Model answer"

    A `/16` VPC across three Availability Zones. Public `/24` per zone containing only the internet-facing ALB and one NAT Gateway per zone. Private `/20` per zone for the ECS or EC2 tier, with per-zone route tables pointing at the NAT Gateway in the same zone. Isolated `/22` per zone for Multi-AZ RDS in a DB subnet group. Gateway endpoint for S3 and DynamoDB; Interface endpoints in all three zones for the AWS APIs used. Security groups chained by reference: ALB security group open on 443 from the internet, application security group allowing 8080 from the ALB security group, database security group allowing 5432 from the application security group. Route 53 alias to the ALB, CloudFront in front, WAF attached, Flow Logs to a central account.

**2. How would you design network segmentation across 40 AWS accounts?**

??? success "Model answer"

    Transit Gateway in a network account shared via Resource Access Manager, with separate Transit Gateway route tables per environment so production and non-production attachments cannot route to each other. A shared-services VPC holding centralised Interface endpoints and Route 53 Resolver endpoints, with private hosted zones associated to workload VPCs. An inspection VPC with Network Firewall behind a Gateway Load Balancer for east-west and egress inspection. Service Control Policies preventing the creation of Internet Gateways in workload accounts. A single, centrally governed IPAM allocation so CIDRs never overlap.

**3. An EKS cluster will run 20,000 pods. What is your networking plan?**

??? success "Model answer"

    The VPC CNI assigns a VPC address to every pod, so plan address space first: dedicate large subnets, and add a secondary CIDR from `100.64.0.0/10` with CNI custom networking so pod addresses do not consume routable space. Enable prefix delegation to allocate `/28` prefixes per ENI, which increases pod density per node and reduces API pressure. Use the AWS Load Balancer Controller in IP target mode so the ALB targets pods directly. Use security groups for pods where per-workload policy is needed, and a network policy engine for intra-cluster policy. Spread node groups across three Availability Zones and use topology-aware routing to keep traffic zonal.

**4. Design an API that accepts bursts of 50,000 requests per second but whose downstream can only handle 500 per second.**

??? success "Model answer"

    Do not let the burst reach the downstream. API Gateway integrates directly with SQS (an AWS service integration, no Lambda), returning `202 Accepted`. A consumer  Lambda with reserved concurrency, or an ECS service scaled on queue depth  drains the queue at a controlled rate. Add a dead-letter queue, idempotency keys so retries are safe, and per-route throttling as a second guardrail. The queue converts a scaling problem into a latency problem, which is almost always the right trade.

**5. When would you choose Global Accelerator over Route 53 latency routing?**

??? success "Model answer"

    When failover must be fast and independent of DNS caching, when clients pin IP addresses (device firmware, corporate allow-lists), when the protocol is not HTTP, or when you want traffic to enter the AWS backbone at the nearest edge for non-cacheable workloads. Global Accelerator gives two static anycast addresses and shifts traffic at the network layer in seconds. Route 53 is cheaper and sufficient when DNS TTL-bounded failover is acceptable.

### Troubleshooting Questions

**1. An instance in a private subnet cannot reach the internet. Diagnose systematically.**

??? success "Model answer"

    Check in this order: (a) the private subnet's route table has `0.0.0.0/0` pointing to a **NAT Gateway**, not an Internet Gateway; (b) the NAT Gateway is in a **public** subnet whose route table points `0.0.0.0/0` at an Internet Gateway; (c) the NAT Gateway has an Elastic IP and is in `available` state; (d) the instance's security group allows the required **outbound** traffic; (e) the NACLs on both the private and the public subnet allow outbound traffic and inbound **ephemeral ports** for the return path; (f) DNS is resolving  `enableDnsSupport` on the VPC; (g) NAT Gateway CloudWatch metrics show no `ErrorPortAllocation`. Confirm with Reachability Analyzer and Flow Logs, looking for `REJECT` entries.

**2. You cannot SSH to an EC2 instance. Walk through it.**

??? success "Model answer"

    (a) Does the instance have a public IP or Elastic IP, and are you connecting to the right address? (b) Is it in a public subnet with an Internet Gateway route? (c) Does the security group allow inbound TCP 22 from your source address? (d) Does the NACL allow inbound 22 **and** outbound ephemeral ports 1024–65535? (e) Is the instance running, and did it pass both status checks? (f) Is `sshd` running and listening  check the system log or serial console? (g) Are the key pair and file permissions correct, and are you using the right username for the AMI? (h) Is a host-level firewall blocking? A **timeout** points at routing, security group, or NACL; **connection refused** means the packet reached the host and nothing was listening; a **key rejection** means the network is fine and the problem is credentials.

**3. ALB targets never become healthy.**

??? success "Model answer"

    The target's security group must allow the **health check port** from the ALB's security group  this is the single most common cause. Then confirm the health check path returns 200 (or matches the configured matcher), that the application listens on the configured port and on all interfaces rather than only `127.0.0.1`, that the health check protocol matches, that the target is registered in a subnet the ALB can reach, and that the health check timeout is longer than the application's response time. Check `TargetConnectionErrorCount` and the target group's health status reason string, which is usually explicit.

**4. Inside the VPC, a service name resolves to a public IP address instead of the private endpoint.**

??? success "Model answer"

    Private DNS on the Interface endpoint is disabled, or `enableDnsSupport` or `enableDnsHostnames` is off on the VPC, or a private hosted zone is not associated with this VPC, or a Resolver rule is forwarding the query elsewhere. Confirm with `dig` from an instance against `169.254.169.253`, and check the endpoint's private DNS setting.

**5. Intermittent HTTP 502 responses from the ALB with no application errors.**

??? success "Model answer"

    Most commonly the backend closed a keep-alive connection that the ALB believed was still open, because the backend's keep-alive timeout is shorter than the ALB's idle timeout. Set the backend keep-alive above the ALB idle timeout. Other causes: the target returned a malformed response or headers exceeding the limit, or the target was deregistered while requests were in flight (increase the deregistration delay). Compare `HTTPCode_ELB_5XX_Count` with `HTTPCode_Target_5XX_Count` to determine whether the load balancer or the target generated the error, and inspect the ALB access logs' `elb_status_code` and `target_status_code` fields.

**6. Two peered VPCs cannot communicate even though the peering connection is `active`.**

??? success "Model answer"

    Route tables on **both** sides must have a route to the other VPC's CIDR with the peering connection as target, and this must be present in every relevant subnet route table, not just one. Security groups must allow the traffic  and note that a security group in VPC A can reference a security group in VPC B only when the VPCs are peered and the reference is explicitly configured. NACLs on both sides must permit traffic in both directions. Finally, confirm the CIDRs do not overlap, and enable DNS resolution over the peering if you rely on private hosted-zone names.

---

## 1.7 Cloud-Native Design Patterns

### Conceptual Questions

**1. Define cloud-native in your own words and explain why lift-and-shift migration does not make an application cloud-native.**

??? success "Model answer"

    Cloud-native means building applications to exploit what the cloud offers: elastic, horizontally scaled stateless components; managed and serverless services instead of self-run infrastructure; loose coupling through APIs and events; infrastructure as code; automated delivery; and resilience and observability designed in from the start.

    Lift-and-shift moves a virtual machine to EC2 unchanged. The application keeps its monolithic structure, local state, fixed capacity and manual operations, so it gains a new data centre but not elasticity, managed resilience or faster delivery. It can be a sensible first migration step, but modernisation is what makes it cloud-native.

**2. Distinguish serverless from microservices. Can a system be one without the other? Give an example of each.**

??? success "Model answer"

    Serverless describes how compute is provisioned and billed: no servers to manage, automatic scaling (often to zero) and pay-per-use. Microservices describe how a system is decomposed: independently deployable services aligned to business capabilities, each owning its data.

    They are independent. A single Lambda-backed API with one shared database is serverless but not microservices. A set of independently deployed services running as containers on ECS on EC2 is microservices but not serverless. Many modern systems combine both, for example microservices implemented with API Gateway, Lambda and DynamoDB.

**3. What does "loose coupling" mean concretely, and how do events reduce temporal coupling in ways that synchronous APIs cannot?**

??? success "Model answer"

    Loose coupling means components can change, fail, scale and be deployed independently: they share contracts, not implementations, databases or deployment schedules. Concretely, a service can be redeployed without coordinating with other teams and can tolerate another service being slow or down.

    With a synchronous API, the caller needs the callee to be available and fast at that moment (temporal coupling), and failure or latency propagates up the chain. With events, the producer records a fact on a broker such as SQS, SNS or EventBridge and continues; consumers process it when they are able. If a consumer is down, events wait in the queue or are retried, so the producer is unaffected. The producer also does not need to know who the consumers are, which removes location coupling.

**4. Explain the difference between an event and a command, and why the distinction affects system coupling.**

??? success "Model answer"

    An event is an immutable statement that something has already happened, such as `OrderPlaced`, published for any interested party. A command is a request for a specific recipient to do something, such as `ChargeCard`, and it can be accepted or rejected.

    The distinction affects coupling because a command ties the sender to a known receiver and its interface, and the sender usually depends on the result. An event lets the producer remain unaware of consumers: new consumers can be added without changing the producer. Using events where commands are really meant (or the reverse) produces hidden dependencies, so naming in past tense for events and imperative for commands is a useful discipline.

**5. Why must event consumers be idempotent? Describe a concrete implementation of idempotency on AWS.**

??? success "Model answer"

    SQS standard queues, SNS and EventBridge all deliver at least once, and retries after timeouts or partial failures also produce duplicates. A consumer that is not idempotent will double-charge, double-ship or send duplicate emails.

    A concrete AWS implementation uses a DynamoDB idempotency table keyed by the event ID or a business idempotency key. Before performing the side effect, the consumer writes the key with `PutItem` and the condition `attribute_not_exists(pk)`; if the write fails with `ConditionalCheckFailedException`, the event has already been processed and is skipped. Where possible, the business update and the idempotency record are written together with `TransactWriteItems`, and a TTL attribute expires old keys. Powertools for AWS Lambda provides an idempotency utility built on this pattern.

**6. Compare choreography and orchestration. What are the operational consequences of each?**

??? success "Model answer"

    In choreography, services react to each other's events with no central coordinator. It is highly decoupled and easy to extend, but the end-to-end flow exists only implicitly, so understanding, debugging and changing it requires distributed tracing and good documentation, and cyclic dependencies can appear.

    In orchestration, a coordinator such as AWS Step Functions directs each step and handles retries, timeouts and compensations explicitly. The workflow is visible and auditable in its execution history, and failures are easier to diagnose, but the orchestrator is a central dependency and its definition couples the participating services to one workflow. Teams commonly use orchestration within a bounded context and choreography between contexts.

**7. What is eventual consistency, and how would you explain its user-visible effects to a non-technical product owner?**

??? success "Model answer"

    Eventual consistency means that after a change, different parts of the system may briefly show different values, but they converge to the same value once updates stop propagating. It is the price of decoupled, scalable and highly available systems.

    For a product owner: "When a customer places an order, the order screen updates immediately, but their order history or loyalty points might take a second or two to catch up. The data is safe; it is just travelling between systems." The important design work is deciding where a short delay is acceptable (recommendations, search, analytics) and where it is not (payments, stock reservation), and designing the user experience accordingly, for example by showing the customer their own change immediately.

**8. Explain the CAP theorem's relevance to a microservices architecture that spans multiple Availability Zones.**

??? success "Model answer"

    CAP says that when a network partition occurs, a distributed data store must choose between consistency and availability. In a microservices system spread across AZs, a partition between AZs or between services is a real possibility, so each service must decide what to do when it cannot reach a dependency or a replica.

    A payment service should usually choose consistency (fail or queue the request rather than risk a double spend), whereas a product catalogue can choose availability and serve slightly stale data. The PACELC extension adds that, even without a partition, there is a constant trade-off between latency and consistency. On AWS, Multi-AZ managed services handle most partition behaviour internally, but cross-service consistency remains the architect's responsibility, typically through sagas and idempotent events rather than distributed transactions.

**9. What is a distributed monolith, and what single test reveals one?**

??? success "Model answer"

    A distributed monolith is a system split into separately deployed services that remain tightly coupled: they share a database, call each other in long synchronous chains, and must be released together. It has all the operational cost of microservices with none of the benefits.

    The single test is: can this service be deployed to production right now, on its own, without coordinating with any other team or service? If the answer is no, the system is a distributed monolith.

**10. Why is API-first considered an organisational practice as much as a technical one?**

??? success "Model answer"

    Technically, API-first means writing and agreeing the contract (for example an OpenAPI specification) before implementation, then generating mocks, SDKs and tests from it. But the main value is organisational: the contract is the agreement between teams.

    It lets frontend, backend and partner teams work in parallel against mocks, makes ownership and versioning explicit, enables governance through style guides and reviews, and treats APIs as products with consumers, documentation and deprecation policies. It also mirrors Conway's law: well-defined API boundaries support autonomous teams, so adopting API-first changes how teams plan, review and communicate, not only how code is written.

### Scenario Questions

**1. An e-commerce checkout takes 8 seconds because it synchronously calls inventory, payment, fraud, email, and analytics services. Redesign it and quantify the expected user-perceived latency improvement.**

??? success "Model answer"

    Separate what the customer must wait for from what can happen afterwards. Inventory reservation and payment authorisation must complete before confirming the order; fraud checks may need to be synchronous for high-risk orders. Email confirmation and analytics do not belong in the request path: the checkout publishes an `OrderPlaced` event to EventBridge or SNS, and those consumers process it asynchronously through their own SQS queues.

    Run the remaining synchronous calls in parallel where they are independent (for example inventory and fraud), with strict timeouts. If each call took about 1.6 seconds sequentially, the original latency is the sum, about 8 seconds; the redesign is roughly the slowest critical call plus the payment call, so of the order of 2 to 3 seconds, and lower again if fraud scoring is cached or made asynchronous for low-risk orders. Return confirmation as soon as the critical steps succeed.

**2. A Lambda function connected to RDS fails during traffic spikes with connection errors. Diagnose and give two distinct remedies.**

??? success "Model answer"

    Each concurrent Lambda execution environment opens its own database connection, so during a spike the number of connections grows with concurrency and exceeds the database's `max_connections`, causing connection errors for the function and for every other client of the database.

    Remedy one is Amazon RDS Proxy, which pools and multiplexes connections so many Lambda environments share a small number of database connections; combine it with creating the connection outside the handler so warm invocations reuse it. Remedy two is to bound concurrency: set reserved concurrency on the function, or put an SQS queue in front so the function drains work at a rate the database can sustain. For suitable access patterns, DynamoDB avoids the connection problem entirely.

**3. Traffic is highly variable: near zero overnight, 40x peak for three hours each morning. Choose a compute strategy and justify it on cost and latency grounds.**

??? success "Model answer"

    A serverless or rapidly elastic strategy fits best. AWS Lambda behind API Gateway scales from near zero to the morning peak automatically and costs almost nothing overnight, so it is attractive on cost for this shape of traffic. To protect latency at the start of the peak, use provisioned concurrency scheduled with Application Auto Scaling for the morning window rather than all day.

    If the workload is better suited to containers, use ECS on Fargate with scheduled scaling that pre-scales before the known morning peak, target tracking during it, and a small minimum overnight. Either way, the key points are scheduled pre-scaling for the predictable peak, scale-in overnight to save cost, and a comparison of steady-state cost during the three peak hours against the idle savings.

**4. A partner integration requires guaranteed ordering of financial transactions per customer account. Which AWS messaging service and configuration would you choose, and what throughput limitation must you communicate?**

??? success "Model answer"

    Use an Amazon SQS FIFO queue with the customer account ID as the `MessageGroupId`. Ordering is guaranteed within each message group, and different accounts are processed in parallel. Enable content-based deduplication or supply a `MessageDeduplicationId` to get exactly-once processing within the five-minute deduplication interval. Kinesis Data Streams with the account ID as partition key is an alternative when replay and multiple consumers are needed.

    The throughput limitation to communicate is that FIFO queues support 300 API calls per second per API action without batching (3,000 messages per second with batching of 10) unless high-throughput mode is enabled, which raises the limit substantially but still processes each message group one message at a time. A single very active account therefore cannot be parallelised, and one failing message blocks that account's group until it succeeds or moves to the dead-letter queue.

**5. Your team must publish an API that mobile clients  which cannot be force-upgraded  will consume for at least three years. Describe your versioning and deprecation strategy.**

??? success "Model answer"

    Design the contract first in OpenAPI, and evolve it additively: add optional fields and new endpoints, never remove or change the meaning of existing ones, and require clients to ignore unknown fields. Put an explicit major version in the path (for example `/v1/`) or as an API Gateway stage, and only introduce `/v2/` for genuinely breaking changes, running both versions side by side.

    Publish a deprecation policy before release: a minimum support period (here at least three years), `Deprecation` and `Sunset` response headers, usage metrics per version and client app version so you know who still calls old versions, and communication well in advance. Use contract tests in CI so implementations cannot drift from published versions, and include a server-driven "minimum supported version" signal in the API so the app can prompt users to upgrade.

**6. An event consumer had a bug for six hours and dropped 200,000 events. How do you recover the lost processing?**

??? success "Model answer"

    First fix and deploy the bug, then identify exactly which events were affected and when. Recovery depends on where the events still exist. If they came through EventBridge with an archive enabled, replay the archive for the six-hour window to the fixed consumer. If the source is Kinesis or another log within its retention period, reset the consumer's position to the start of the window and reprocess. If the consumer moved failures to a dead-letter queue, redrive the DLQ to the source queue.

    If the events were genuinely discarded and no archive exists, rebuild them from the system of record (for example by querying the producer's database or an S3 data lake for changes in that window) and republish them. In every case the consumer must be idempotent so that replay does not double-process events that succeeded. Afterwards, add archives, DLQs and alarms on processing failures so the next incident is detected in minutes, not hours.

**7. A microservices platform has grown to 60 services and deployment velocity has _fallen_. Diagnose the likely causes and propose remedies.**

??? success "Model answer"

    Likely causes are architectural coupling and organisational friction: services that share databases or must be released together (a distributed monolith), long synchronous call chains that make every change risky, shared pipelines or a single staging environment that creates a queue for releases, missing contract tests so integration problems appear late, and team boundaries that do not match service boundaries, forcing cross-team coordination.

    Remedies are to measure first (DORA metrics and where changes wait), then give each service its own pipeline with automated tests and progressive delivery, introduce consumer-driven contract tests, break shared databases and replace synchronous chains with events where appropriate, invest in observability and a platform team that provides paved-road templates, and realign teams to bounded contexts. Merging services that always change together is also a legitimate fix.

### Architecture Questions

**1. Design a serverless image-processing pipeline that handles 10,000 uploads per minute, produces three thumbnail sizes, and must not lose an image. Draw the architecture and justify each component.**

??? success "Model answer"

    Clients upload directly to S3 using presigned URLs issued by a small API (API Gateway and Lambda), so image bytes never pass through compute. The S3 `ObjectCreated` event goes to an SQS queue (directly or via EventBridge), which buffers bursts of 10,000 uploads per minute (about 167 per second) and provides retries.

    A Lambda function consumes the queue in batches with a concurrency cap, generates the three thumbnail sizes and writes them to a separate output bucket (avoiding recursive triggers), recording status in DynamoDB. "Must not lose an image" is met by S3 durability for originals, SQS retention with a visibility timeout longer than processing time, partial batch failure reporting, a dead-letter queue with an alarm and redrive, and idempotent processing keyed by object key and version. Thumbnails are served through CloudFront with Origin Access Control.

**2. Design a multi-tenant SaaS API where no single tenant may degrade another's performance. Address throttling, isolation, and cost attribution.**

??? success "Model answer"

    At the edge, API Gateway REST API usage plans with an API key per tenant enforce rate and burst limits and quotas by tier, with WAF rate-based rules as a backstop. Tenant identity comes from a JWT (for example Cognito), and the tenant ID is propagated in every request.

    For isolation, use a bridge model: pooled compute and data for standard tenants, with per-tenant concurrency limits or separate queues so one tenant's burst cannot consume shared capacity; dedicated (siloed) stacks or cells for premium or noisy tenants. In data stores, prefix partition keys with the tenant ID and enforce access with IAM conditions such as `dynamodb:LeadingKeys`. For cost attribution, emit tenant-tagged metrics and structured logs, meter usage per tenant (requests, compute duration, storage) and allocate shared costs proportionally, using cost allocation tags for siloed resources.

**3. Design an order-fulfilment system implementing the Saga pattern. Specify compensating actions and how you would make the workflow auditable.**

??? success "Model answer"

    Model the order flow as a Step Functions state machine (orchestrated saga): reserve inventory, authorise payment, create shipment, then confirm the order. Each step is a local transaction in its owning service, called through an idempotent API or task with an idempotency key.

    Each step has a compensating action: release the inventory reservation, void or refund the payment, cancel the shipment, and mark the order as cancelled. `Catch` blocks route failures to the compensations in reverse order, and `Retry` with backoff handles transient errors before compensating. Compensations must themselves be idempotent and retriable, with a dead-letter path and alarm for any that cannot complete. For auditability, retain the Step Functions execution history, publish each state transition as an event to an append-only store (for example DynamoDB with streams to S3), log with correlation IDs, and run reconciliation reports confirming every order reached a terminal state.

**4. You must migrate a monolithic Java application to cloud-native over 18 months without a feature freeze. Present your migration strategy.**

??? success "Model answer"

    Use the strangler fig pattern. Put an API Gateway or ALB in front of the monolith as a routing façade, then move capabilities out one at a time, routing their paths to the new services while everything else still goes to the monolith. Start by rehosting or containerising the monolith so it runs on the same platform and pipeline as the new services.

    Choose the first extractions by business value and low coupling (for example notifications or catalogue reads), establish observability and CI/CD foundations early, and give each extracted service its own data, synchronised from the monolith through change data capture or events during the transition. Use feature flags and parallel runs to compare outputs before switching traffic. Feature delivery continues throughout because new features are built either in new services or, if necessary, in the monolith, and progress is measured by traffic share moved and deployment frequency. Stop extracting when the remaining monolith is stable and cheap to maintain.

**5. Design the observability strategy for a system with 30 microservices and heavy asynchronous messaging. Specify metrics, alarms, tracing, and log structure.**

??? success "Model answer"

    Define service-level objectives for each user-facing journey and alarm on SLO burn rate rather than on every low-level metric. Each service emits RED metrics (rate, errors, duration) and resource saturation, and every queue is monitored for depth, `ApproximateAgeOfOldestMessage` and DLQ size, because asynchronous failures are otherwise silent.

    Use distributed tracing (AWS X-Ray or OpenTelemetry with the AWS Distro) with context propagated through HTTP calls and message attributes so traces survive SQS, SNS and EventBridge hops. Logs are structured JSON with consistent fields: timestamp, service, version, correlation or trace ID, tenant or customer ID, and event ID, centralised in CloudWatch Logs and queryable with Logs Insights. Dashboards are organised per journey and per service, alarms route to the owning team, and runbooks link from each alarm.

### Troubleshooting Questions

**1. An SQS queue's `ApproximateAgeOfOldestMessage` is growing steadily while consumer CPU sits at 20%. List possible causes in order of likelihood.**

??? success "Model answer"

    Low CPU with a growing backlog means consumers are not processing fast enough but are not busy computing. In order of likelihood: consumers are waiting on a slow downstream dependency (database, third-party API) so throughput is I/O-bound; consumer concurrency is too low (too few tasks, small batch size, short polling, or Lambda reserved or maximum concurrency set too low); messages are failing and being retried repeatedly because the visibility timeout expires or a poison message keeps returning without a DLQ.

    Other causes include consumers throttled by a downstream service or by Lambda concurrency limits, a deployment that left consumers crashing or unable to authenticate, or a producer rate that has simply increased. Check consumer error logs, `NumberOfMessagesDeleted` versus `NumberOfMessagesReceived`, receive counts, and downstream latency before scaling out.

**2. Lambda p99 latency is 3 seconds while p50 is 40 ms. Explain the likely cause and three mitigations.**

??? success "Model answer"

    A large gap between p50 and p99 in Lambda usually means cold starts: most requests hit warm environments, but some require a new environment that must load the runtime and run initialisation, especially for JVM or .NET functions, large packages or heavy initialisation. Slow downstream calls affecting a small fraction of requests are the other candidate, and X-Ray traces with the `Init Duration` field in logs distinguish them.

    Mitigations: provisioned concurrency for the expected baseline so environments are already initialised; SnapStart (for supported runtimes such as Java) to restore a pre-initialised snapshot; and reducing initialisation cost by trimming dependencies, lazy-loading clients and increasing memory, which also increases CPU and speeds initialisation.

**3. EventBridge shows successful `PutEvents` but a target Lambda is never invoked. Enumerate your diagnostic steps.**

??? success "Model answer"

    First confirm the event actually matches a rule: check the rule's `MatchedEvents` metric and compare the event pattern against a sample event (pattern matching is exact and case-sensitive, and the `source` and `detail-type` must match). Confirm the event was put on the same event bus and in the same Region as the rule, and that the rule is enabled.

    Next, check delivery: the `Invocations` and `FailedInvocations` metrics for the rule, the Lambda function's resource-based policy allowing `events.amazonaws.com` to invoke it from that rule, and any input transformer errors. Configure a dead-letter queue on the target to capture failed deliveries and inspect their error attributes. Finally, check the function's own metrics and logs for throttling or errors, and whether it was invoked under a different alias or version.

**4. Customers report duplicate confirmation emails during high traffic. Identify the root cause and the fix.**

??? success "Model answer"

    The root cause is at-least-once delivery combined with a non-idempotent consumer. Under high traffic, processing takes longer, so SQS visibility timeouts expire before the message is deleted, Lambda retries asynchronous events after errors or timeouts, or a batch partially fails and is retried, and each retry sends another email.

    The fix is to make the email sender idempotent: record an idempotency key such as the order ID plus the email type in DynamoDB with a conditional write before sending, and skip if it already exists. Also set the visibility timeout well above the processing time, use partial batch failure reporting so successful messages are not retried, and raise consumer capacity so timeouts become rarer.

**5. After a deployment, an ECS service is stuck with tasks repeatedly stopping and restarting. What do you check, and in what order?**

??? success "Model answer"

    Start with the ECS service events and the stopped tasks' `stoppedReason` and container exit codes, which usually name the problem. Check in order: image pull failures (`CannotPullContainerError`, wrong tag, missing ECR permissions or network path); container crashes on startup visible in CloudWatch Logs (missing environment variables or secrets, bad configuration, failed migrations); essential container exit; out-of-memory kills (exit code 137) because the new version needs more memory.

    Then check health: load balancer target health check failures (wrong path or port, start-up longer than the health check grace period) and container health check failures. Compare the new task definition with the previous revision, and rely on the ECS deployment circuit breaker with rollback so a failing deployment automatically returns to the last working version.

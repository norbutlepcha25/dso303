# Unit 1: Interview Questions

## 1.1 AWS Cloud Overview

### Conceptual Questions

1. Explain the difference between a Region, an Availability Zone, and an Edge Location, and give one architectural decision driven by each.
2. Why does synchronous replication generally stop at the Region boundary? What physical constant is responsible?
3. What is static stability, and why does it matter during an AZ event?

### Scenario Questions

4. A South African fintech must keep customer data in-country, survive a data-centre fire with zero data loss, and serve a marketing site quickly worldwide. Design the placement. _(Expected: af-south-1, Multi-AZ synchronous DB, private S3 + CloudFront for the site.)_
5. Your CloudFront hit ratio is 12%. What are the three most likely configuration causes and their fixes?

### Architecture Questions

6. Design a two-Region architecture with RTO 15 minutes and RPO 1 minute for a REST API + relational data. Justify warm standby vs active-active, the replication technology, and the failover trigger.
7. How would you guarantee that _only_ CloudFront can reach your ALB origin?

### Troubleshooting Questions

8. Users in one city report errors; your Regional dashboards look healthy. Walk through your diagnosis. _(Edge PoP issue → CloudFront metrics in us-east-1, synthetics from multiple geographies, AWS Health.)_
9. After deploying new JavaScript, some users worldwide still receive the old file for hours. Why, and what are the short-term and long-term fixes?

### Certification-style Questions

10. A company needs static IP addresses for a global TCP (non-HTTP) application with fast regional failover. CloudFront or Global Accelerator? Why?

---

## 1.3 AWS Compute Services

### Conceptual Questions

**1. Explain the difference between vertical and horizontal scaling, and why cloud-native design prefers the latter.**

Vertical scaling increases the capacity of a single instance (a larger instance type); horizontal scaling adds more instances. Vertical scaling is bounded by the largest available instance, usually requires a restart, and leaves a single failure domain. Horizontal scaling is effectively unbounded, allows in-place replacement of unhealthy members, and distributes failure risk across Availability Zones. Cloud-native design prefers horizontal scaling because it makes capacity a runtime property managed by a control loop rather than a procurement decision. The precondition is statelessness: session and durable state must be externalised to DynamoDB, ElastiCache, RDS, or S3.

**2. What is the difference between an ECS task, a task definition, and a service?**

A task definition is an immutable, versioned blueprint: container images, CPU and memory reservations, port mappings, environment variables, logging configuration, and the task and execution IAM roles. A task is a running instantiation of one revision of that blueprint  one or more containers scheduled together on the same host and sharing a network namespace. A service is a controller that maintains a desired count of tasks, replaces unhealthy ones, registers them with a load balancer target group, and orchestrates rolling or blue/green deployments. The mental model is class, object, and supervisor.

**3. Why does AWS Lambda have a cold start, and what determines its duration?**

A cold start occurs when no warm execution environment exists for an invocation, so Lambda must allocate a Firecracker microVM, download and decrypt the deployment package or container image, initialise the runtime, and execute the function's initialisation code before the handler runs. Duration is driven by package or image size, runtime choice (interpreted runtimes such as Python and Node.js initialise faster than JVM or .NET), the amount of work performed outside the handler, the memory setting (which proportionally allocates vCPU, so more memory means faster initialisation), and whether the function is attached to a VPC. Provisioned concurrency and SnapStart eliminate or drastically reduce this latency.

**4. Distinguish the ECS task execution role from the ECS task role.**

The execution role is assumed by the ECS agent and Fargate infrastructure, not by application code. It grants permission to pull images from ECR, retrieve secrets from Secrets Manager or SSM Parameter Store for injection into the container environment, and write to CloudWatch Logs. The task role is assumed by the application process inside the container and is what the AWS SDK picks up through the container credential provider. Least privilege requires two distinct roles; conflating them grants the application infrastructure permissions it should never hold.

**5. What does AWS Fargate actually remove from the operational burden, and what does it not?**

Fargate removes the EC2 layer: no AMI patching, no instance right-sizing, no cluster capacity management, no bin-packing, no SSH access, and per-task rather than per-instance billing granularity. It does not remove container image hygiene, application-level patching, IAM design, networking design (tasks still occupy subnets and ENIs), observability, or cost governance. It also does not remove the need to understand orchestration semantics  deployment strategies, health checks, and draining still apply.

**6. Explain the concept of a control plane and a data plane using ECS and EKS as examples.**

The control plane holds desired state, makes scheduling and placement decisions, and reconciles actual state toward desired state; the data plane executes workloads and carries request traffic. In ECS, the control plane is an AWS-managed regional service holding cluster, service, and task-definition state, while the data plane is EC2 instances running the ECS agent, or Fargate capacity. In EKS, the control plane is a managed, multi-AZ Kubernetes API server and etcd cluster, and the data plane is managed node groups, self-managed nodes, or Fargate profiles. The distinction matters operationally: a control-plane outage generally stops new deployments and scaling decisions, but already-running data-plane workloads continue serving traffic.

**7. Why is an Auto Scaling group with `ELB` health check type materially different from one with `EC2` health check type?**

The `EC2` health check reports only on hypervisor-level instance status  whether the instance is running and passing system and instance status checks. An instance whose application process has crashed, deadlocked, or is returning HTTP 500 still passes. The `ELB` health check type delegates the decision to the load balancer's target group health check, which probes an application endpoint. Only the latter detects application-level failure and triggers replacement. This is a very common production defect and a recurring certification trap.

### Scenario Questions

**1. A team runs a nightly report that takes 45 minutes and reads several gigabytes from S3. They propose AWS Lambda. Evaluate.**

Lambda is unsuitable as a single invocation: the maximum execution duration is 15 minutes, which is a hard limit, and ephemeral storage is bounded. Three viable redesigns exist. First, decompose the job into a map-reduce shape  a Step Functions Distributed Map fanning out many short Lambda invocations over S3 key ranges, then a reduce step. Second, run it as an ECS or EKS task on Fargate, invoked on a schedule by EventBridge Scheduler, which has no duration limit and generous memory. Third, if the work is fundamentally an analytical query over S3 data, replace the compute entirely with Athena or an EMR Serverless job. The architectural lesson is that a duration limit is a signal to reconsider the decomposition, not merely to pick a bigger runtime.

**2. A microservice receives steady traffic of roughly 200 requests per second with brief 10x spikes at lunchtime. Cost is a first-class concern. Which compute model?**

Steady baseline plus predictable spikes favours containers on ECS or EKS with Fargate for burst capacity, or EC2 with a Savings Plan covering the baseline and Spot or on-demand for the peak. Lambda's per-invocation pricing becomes expensive at sustained high request rates compared with a continuously utilised container, so at 200 requests per second sustained, containers usually win on cost while Lambda wins on operational simplicity. A defensible answer states the crossover reasoning explicitly: Lambda is optimal for spiky, low-duty-cycle workloads; containers are optimal once utilisation is high and steady. Compute Savings Plans apply across EC2, Fargate, and Lambda, so the baseline can be committed regardless of the model chosen.

**3. A regulated financial customer requires that no other tenant's workload share the physical host. What are the options and their trade-offs?**

Dedicated Instances guarantee hardware isolation at the account level but do not give visibility of or control over socket and core placement. Dedicated Hosts additionally expose the physical server, enabling per-socket or per-core software licensing (bring-your-own-license for Windows Server or Oracle) and affinity so an instance returns to the same host after a stop and start. Both carry a substantial cost premium and reduce placement flexibility, which weakens elasticity. On Fargate each task runs in its own isolation boundary with dedicated kernel, which satisfies many isolation requirements without dedicated hardware, but does not satisfy a literal "no shared physical hardware" clause. The architect's job is to determine whether the requirement is genuinely about physical hardware or about isolation and compliance evidence, because the answer changes the cost by an order of magnitude.

**4. An EKS cluster experiences pods stuck in `Pending` with the event `too many pods`. Diagnose.**

This is almost always the ENI-based IP address limit of the Amazon VPC CNI. Each node can host a number of pods bounded by the number of ENIs its instance type supports multiplied by the IP addresses per ENI, minus one for the node itself. Small instance types therefore host very few pods regardless of free CPU and memory. Remedies include selecting larger instance types, enabling prefix delegation on the VPC CNI (which assigns /28 prefixes rather than individual secondary IPs and greatly increases pod density), or adopting custom networking with a secondary CIDR. A secondary possibility is that the subnets themselves have exhausted their IP space, which is a CIDR planning failure.

**5. A Lambda function attached to a VPC intermittently fails to reach an RDS database, and the team observes connection exhaustion on the database.**

Lambda scales horizontally by creating concurrent execution environments, each of which opens its own database connection. At high concurrency this multiplies into thousands of connections and exceeds the RDS `max_connections` parameter, which itself scales with instance memory. The correct remedy is Amazon RDS Proxy, which maintains a pooled, multiplexed set of connections to the database and lets Lambda functions borrow from the pool. Supporting measures include setting reserved concurrency on the function to bound the blast radius, opening the connection outside the handler so it is reused across warm invocations, and confirming that the security groups allow traffic from the Lambda ENIs' security group on the database port.

### Architecture Questions

**1. Design a compute layer for a three-tier e-commerce application that must survive the loss of an Availability Zone.**

Place an Application Load Balancer across at least two, preferably three, Availability Zones in public subnets. Run the application tier as an ECS service on Fargate, or an Auto Scaling group, spread across the same Availability Zones in private subnets, with a desired count set so that N-1 zones can carry full peak load. Target tracking scaling on request count per target or on CPU maintains headroom. Externalise session state to ElastiCache or DynamoDB so any instance can serve any request. Use RDS Multi-AZ or Aurora with reader instances in each zone. Verify that the ASG or service uses `ELB` health checks, that deployment uses rolling or blue/green with a minimum healthy percentage, and that the NAT Gateway is provisioned per zone so that the loss of one zone does not break egress for the others.

**2. When would you choose EKS over ECS, given that ECS is simpler?**

Choose EKS when the organisation needs the Kubernetes API and ecosystem  Helm charts, operators, custom resource definitions, service meshes such as Istio, GitOps tooling such as Argo CD or Flux  or when workload portability across clouds and on-premises is a genuine requirement, or when the engineering organisation already has Kubernetes expertise and multi-cluster tooling. Choose ECS when the priority is minimal operational surface, deep and native AWS integration, no control-plane charge, and a smaller learning curve. The decision is fundamentally about ecosystem leverage and existing skills, not about technical capability, because both can run the same containers with comparable reliability.

**3. Design an event-driven image-processing pipeline and justify the compute choice at each stage.**

An upload lands in S3, which emits an event to EventBridge or directly to SQS. A Lambda function consumes the queue, generates thumbnails, and writes results back to S3 and metadata to DynamoDB  Lambda is correct here because the work is short, stateless, embarrassingly parallel, and bursty, and the cost at low duty cycle is negligible. If a stage requires heavy machine-learning inference exceeding 15 minutes or requiring GPUs, that stage moves to an ECS Fargate task or an EC2 GPU instance triggered by Step Functions, because Lambda does not offer GPUs. A dead-letter queue captures poison messages, and Step Functions orchestrates multi-stage workflows so that retries, timeouts, and error paths are declarative rather than embedded in application code.

**4. How would you achieve zero-downtime deployment for a containerised service, and what are the trade-offs of each strategy?**

Rolling update with a minimum healthy percentage of 100 and a maximum percent above 100 launches new tasks before draining old ones; it is cheap and simple but briefly runs two versions concurrently, which requires backward-compatible schemas and APIs. Blue/green through CodeDeploy stands up a complete replacement task set behind a second target group and shifts traffic all at once, linearly, or canary, with automatic rollback on CloudWatch alarms; it doubles capacity cost during deployment but gives a clean and fast rollback. Canary within a rolling update, or Lambda weighted aliases for serverless, exposes a small traffic percentage to the new version first, which minimises blast radius at the cost of a longer deployment window and more complex observability.

### Troubleshooting Questions

**1. An ECS Fargate task repeatedly stops with `CannotPullContainerError`.**

The task cannot reach ECR. In a private subnet without a NAT Gateway, create interface VPC endpoints for `ecr.api` and `ecr.dkr`, a Gateway endpoint for S3 (ECR layers are stored in S3), and an interface endpoint for `logs` if CloudWatch Logs is the log driver. Alternatively confirm the route to a NAT Gateway. Secondary causes are an execution role lacking `ecr:GetAuthorizationToken` and the ECR read permissions, an incorrect image tag, or a task launched with `assignPublicIp` disabled in a public subnet.

**2. An EC2 instance in a private subnet cannot install packages from the internet.**

Confirm a NAT Gateway exists in a public subnet in the same Availability Zone, that the private subnet's route table has a `0.0.0.0/0` route to that NAT Gateway, that the public subnet's route table has a `0.0.0.0/0` route to an Internet Gateway, that the NAT Gateway subnet is genuinely public, and that the outbound security group and the network ACLs on both subnets permit the traffic  remembering that NACLs are stateless and therefore need an inbound ephemeral-port rule for return traffic.

**3. A Lambda function reports `Task timed out after 3.00 seconds` only in production.**

The default timeout of three seconds is almost never appropriate for a function performing network calls. Raise the timeout to a value above the observed p99 duration but below the caller's tolerance, and set it deliberately rather than by default. Then investigate why production is slower: cold starts, VPC-attached ENI behaviour, a downstream dependency with higher latency at scale, connection establishment inside the handler rather than outside it, or insufficient memory throttling the vCPU allocation. Enable AWS X-Ray to attribute the latency to a specific downstream segment.

**4. An Auto Scaling group continuously launches and terminates instances.**

This is a scaling or health-check thrash loop. The common causes are a health check grace period shorter than the application's boot time, so instances are terminated before they become healthy; a failing user-data bootstrap script; an `ELB` health check pointing at a path that the application does not serve, or one that requires authentication; step or simple scaling policies without adequate cooldown fighting each other; or an unhealthy AMI. Inspect the Auto Scaling activity history, the target group health-check reason codes, and the instance console output.

**5. An EKS pod cannot assume its IAM role and receives `AccessDenied` from the AWS SDK.**

Verify the full IRSA or EKS Pod Identity chain: the cluster has an OIDC identity provider registered in IAM; the IAM role's trust policy references that provider and constrains the `sub` claim to the correct namespace and service account; the Kubernetes ServiceAccount carries the `eks.amazonaws.com/role-arn` annotation; the pod spec sets `serviceAccountName`; and the SDK version supports web identity token credentials. A frequent error is a trust policy that matches the wrong namespace, which fails silently and falls back to the node instance role.

### Certification-style Questions

**1.** A company runs a stateless web tier that must scale automatically and minimise cost. Traffic is unpredictable and frequently idle for hours. Which is MOST cost-effective?

- A. EC2 On-Demand instances in an Auto Scaling group with a minimum of two
- B. AWS Lambda behind Amazon API Gateway
- C. ECS on EC2 with Reserved Instances
- D. EC2 Dedicated Hosts

**Answer: B.** Long idle periods mean any always-on capacity is wasted. Lambda charges only for invocations and duration and scales to zero. Reserved Instances and Dedicated Hosts commit to capacity that is unused most of the time.

**2.** An application must run for approximately 30 minutes per job, requires 8 GB of memory, and is triggered a few times per day. Which service requires the LEAST operational overhead while meeting the requirement?

- A. AWS Lambda
- B. Amazon EC2 with an Auto Scaling group
- C. Amazon ECS on AWS Fargate triggered by EventBridge Scheduler
- D. Amazon EKS with managed node groups

**Answer: C.** Lambda cannot run for 30 minutes. EC2 and EKS both introduce node management. Fargate has no duration limit, no servers to manage, and is billed only while the task runs.

**3.** A workload can tolerate interruption and must minimise cost for a large batch of independent jobs. Which purchasing option is MOST appropriate?

- A. On-Demand
- B. Reserved Instances
- C. Spot Instances
- D. Dedicated Hosts

**Answer: C.** Spot offers the deepest discount and is designed for interruption-tolerant, fault-tolerant, and stateless workloads, with a two-minute interruption notice.

**4.** Which of the following is required for an EC2 instance to write objects to Amazon S3 following security best practice?

- A. Store access keys in the user data script
- B. Attach an IAM role through an instance profile
- C. Store credentials in `~/.aws/credentials` on the instance
- D. Make the S3 bucket public

**Answer: B.** Roles delivered through an instance profile provide temporary, automatically rotated credentials retrieved from IMDS. Long-lived keys embedded on the instance are a credential-management liability.

**5.** A containerised service must reduce cold-start latency for a synchronous, user-facing Lambda function written in Java. Which feature addresses this MOST directly?

- A. Reserved concurrency
- B. Provisioned concurrency or Lambda SnapStart
- C. Increasing the function timeout
- D. Attaching the function to a VPC

**Answer: B.** Provisioned concurrency keeps initialised environments warm; SnapStart restores a pre-initialised snapshot and is specifically effective for JVM runtimes. Reserved concurrency caps concurrency and does not warm environments, and attaching to a VPC generally increases rather than decreases latency.

**6.** An Auto Scaling group must replace instances whose application has crashed although the operating system is still running. What must be configured?

- A. Health check type `EC2`
- B. Health check type `ELB` with a target group health check on an application endpoint
- C. A shorter cooldown period
- D. Termination protection

**Answer: B.** Only the load balancer health check observes application-level behaviour.

**7.** Which statement about AWS Fargate is correct?

- A. Fargate is an alternative container orchestrator to ECS and EKS
- B. Fargate allows SSH access to the underlying host
- C. Fargate is a serverless compute engine used as a capacity type by both ECS and EKS
- D. Fargate supports DaemonSets on EKS

**Answer: C.** Fargate is a capacity provider, not an orchestrator; there is no host access, and EKS on Fargate does not support DaemonSets.

---

## 1.4 AWS Storage Services

### Conceptual Questions

**1. Explain the difference between object, block, and file storage, and why AWS provides three separate services rather than one.**
Object storage stores immutable whole items in a flat keyspace accessed by API and scales without bound because it forgoes in-place mutation. Block storage exposes a raw device supporting random in-place writes with sub-millisecond latency, at the cost of being attached to one host in one Availability Zone. File storage provides shared POSIX semantics through a distributed metadata service, at the cost of higher latency and price. The trade-offs are mutually exclusive, so a single service cannot satisfy all three access patterns.

**2. What does eleven nines of durability actually mean, and what does it not protect against?**
It is a statistical design target for annual data loss from hardware and facility failure, achieved through erasure coding across at least three Availability Zones with continuous background repair. It provides no protection against accidental deletion, malicious deletion, application bugs, or misconfigured permissions. Those require versioning, MFA Delete, Object Lock, cross-account replication, and backups.

**3. Why can an EBS volume not be attached to an instance in another Availability Zone?**
Because EBS replicates synchronously within a single Availability Zone to preserve sub-millisecond write latency. Replicating across zones separated by tens of kilometres would add round-trip latency that would defeat the purpose of block storage. Cross-zone movement is therefore achieved asynchronously through snapshots.

**4. Describe S3's consistency model and how it changed.**
S3 now provides strong read-after-write consistency for `PUT`, overwrite, and `DELETE` operations on all objects in all Regions, with no performance penalty. Previously, overwrites and deletes were eventually consistent. Bucket configuration changes and Cross-Region Replication remain eventually consistent and asynchronous respectively.

**5. What is the difference between the control plane and the data plane, and why does it matter?**
The control plane provisions and configures resources; the data plane moves bytes. AWS engineers data planes for static stability so they continue functioning during control plane impairment. The design implication is to pre-provision resources and never place control plane calls on a user request's critical path.

### Scenario Questions

**1. A team stores ten million one-kilobyte log files per day in S3 Standard and complains the bill is dominated by requests. What do you recommend?**
Aggregate the logs into larger compressed objects, ideally per five-minute or hourly window, before writing. This reduces `PUT` request count by orders of magnitude, reduces per-object overheads, and makes subsequent analytics far cheaper because Athena scans fewer, larger files. Kinesis Data Firehose performs this buffering natively.

**2. A relational database on EC2 shows increasing query latency during nightly batch jobs. `BurstBalance` on the gp2 data volume drops to zero at 02:00. What is happening and how do you fix it?**
The gp2 volume is exhausting its I/O credits and falling back to baseline performance of three IOPS per GiB. Migrate the volume to gp3 with explicitly provisioned IOPS and throughput sized to the measured peak, which removes the credit mechanism entirely. Verify that the instance type's EBS bandwidth can deliver the provisioned figure.

**3. A legacy Java application requires a shared directory across a fleet of servers in three Availability Zones and uses POSIX file locking. Migration to object storage is not funded. What do you propose?**
Amazon EFS with mount targets in all three Availability Zones, Elastic throughput, encryption at rest and in transit, an access point enforcing the application's root directory and POSIX identity, and a security group permitting TCP 2049 only from the application security group. No application change is required.

**4. Auditors require that financial records be immutable for seven years and that no administrator can delete them early. Design the storage.**
An S3 bucket with versioning enabled and Object Lock in Compliance mode with a seven-year retention period, SSE-KMS with a customer managed key whose key policy separates duties, CloudTrail data events delivered to a separate logging account, Block Public Access fully enabled, and replication to a second Region for continuity. Compliance mode cannot be shortened or removed by any principal, including the account root user.

**5. A machine learning team runs distributed training across two hundred GPU instances reading the same fifty-terabyte dataset. S3 reads are too slow for their epoch times. What do you propose?**
Stage the dataset from S3 into Amazon FSx for Lustre, which links directly to the S3 bucket and provides hundreds of gigabytes per second of aggregate throughput with POSIX semantics. S3 remains the durable system of record; FSx for Lustre is the high-performance scratch layer for the duration of the training run.

### Architecture Questions

**1. Design storage for a multi-tenant SaaS document platform serving ten thousand tenants.**
Use a single bucket with a `tenant-id/` prefix per tenant rather than a bucket per tenant, because bucket count is a limited resource. Enforce isolation through IAM session policies scoped to the tenant prefix, issued by an identity broker, or through S3 Access Points with per-tenant policies. Encrypt with SSE-KMS, enable versioning with noncurrent expiry, apply Intelligent-Tiering, and serve reads through CloudFront with signed URLs.

**2. Design a disaster recovery strategy for a system whose Recovery Point Objective is fifteen minutes and Recovery Time Objective is one hour.**
For S3, enable Cross-Region Replication with Replication Time Control, which provides a fifteen-minute Service Level Agreement. For EBS-backed databases, take snapshots more frequently than the Recovery Point Objective or use database-native replication such as an RDS cross-Region read replica, which is the better answer given a fifteen-minute target. For EFS, enable EFS replication. Maintain the target Region's infrastructure as code so it can be provisioned within the Recovery Time Objective, and rehearse the failover.

**3. How would you architect persistent storage for a Kubernetes platform hosting both stateless web services and a Prometheus monitoring stack?**
Stateless services keep no volumes and externalise state to S3 and RDS. Prometheus runs as a StatefulSet with EBS `ReadWriteOnce` persistent volumes provisioned by the EBS CSI driver, using `WaitForFirstConsumer` binding so the volume is created in the zone the pod is scheduled into. Shared configuration or plugin directories used by multiple replicas use an EFS `ReadWriteMany` volume through the EFS CSI driver with an access point per claim. Long-term metrics are shipped to S3 through Thanos or Amazon Managed Service for Prometheus.

**4. A media company must serve five hundred terabytes of video globally at minimum cost while keeping the origin private.**
Store the renditions in S3 with Intelligent-Tiering, serve through CloudFront with Origin Access Control so the bucket is never public, use signed URLs or signed cookies for entitlement enforcement, and set a long cache TTL so the origin request rate and egress cost collapse. Archive masters to Glacier Deep Archive. The dominant saving comes from CloudFront egress pricing being lower than S3 internet egress plus the near-elimination of origin requests.

**5. Design the storage layer for an IoT platform ingesting one million messages per second.**
Ingest through IoT Core into Kinesis Data Streams, buffer with Kinesis Data Firehose which aggregates records into large compressed Parquet objects, and write to S3 with prefixes partitioned by date and device group. Catalogue with Glue, query with Athena, and apply lifecycle rules moving data older than ninety days to Glacier Flexible Retrieval. Hot device state that must be read per request lives in DynamoDB, not in S3.

### Troubleshooting Questions

**1. An EC2 instance cannot mount an EFS file system; the command hangs and eventually times out. How do you diagnose it?**
Check in order: does a mount target exist in the instance's Availability Zone; does the mount target's security group allow inbound TCP 2049 from the instance's security group; do the subnet's Network ACLs permit both directions including ephemeral ports; is the DNS name resolving, which requires DNS hostnames and DNS resolution enabled on the VPC; and is `amazon-efs-utils` installed if TLS or IAM authorisation is requested.

**2. An application receives intermittent `503 SlowDown` responses from S3 during a bulk load. What is happening?**
The request rate against a single partitioned prefix has exceeded the current partition's capacity, and S3 is signalling that it is splitting the partition. The correct response is exponential backoff with jitter, which the AWS SDKs implement by default, combined with spreading writes across more prefixes and ramping up load gradually rather than instantaneously.

**3. A restored EBS volume performs far worse than the original for the first hour. Why?**
Volumes created from snapshots are lazily loaded; blocks are fetched from S3 on first access, so initial reads incur additional latency. Enable Fast Snapshot Restore for that snapshot in the target Availability Zone, or force hydration by sequentially reading the whole device with a tool such as `dd` or `fio` before putting the volume into service.

**4. A user reports `AccessDenied` on `ListObjectsV2` but can successfully `GetObject` on known keys. Why?**
`s3:ListBucket` is a bucket-level action whose resource must be the bucket ARN, whereas `s3:GetObject` is an object-level action whose resource is the object ARN. The policy almost certainly grants both actions against the object ARN pattern only. Add a statement granting `s3:ListBucket` on the bucket ARN, optionally constrained with the `s3:prefix` condition key.

**5. Storage costs for a bucket are far higher than the sum of visible object sizes. What do you investigate?**
Three likely causes: noncurrent object versions accumulating because versioning is on without a lifecycle expiry rule; incomplete multipart upload parts, which are billed but not shown by a standard list operation; and delete markers combined with retained versions. Use S3 Storage Lens or an S3 Inventory report including noncurrent versions, then add lifecycle rules for `NoncurrentVersionExpiration` and `AbortIncompleteMultipartUpload`.

### Certification-style Questions

**1. A company needs to store backups that must be retrievable within twelve hours at the lowest possible cost, with a retention period of ten years. Which storage class is most appropriate?**
S3 Glacier Deep Archive. It offers the lowest storage price with standard retrieval in approximately twelve hours, and the one-hundred-and-eighty-day minimum duration is irrelevant given a ten-year retention.

**2. An application running on EC2 in three Availability Zones must write to a shared file system with POSIX semantics and must remain available if one Availability Zone fails. Which service should be used?**
Amazon EFS in Regional mode with mount targets in all three Availability Zones. EBS cannot span zones, and S3 does not provide POSIX semantics.

**3. Which combination provides the most cost-effective private access to S3 from instances in a private subnet?**
A Gateway VPC endpoint for S3. It carries no hourly or data-processing charge and removes the NAT Gateway from the path entirely.

**4. A workload requires 100,000 IOPS with sub-millisecond latency for a single relational database instance. Which EBS volume type meets this?**
io2 Block Express, which supports up to 256,000 IOPS per volume with sub-millisecond latency. gp3 is limited to 16,000 IOPS and cannot meet the requirement.

**5. A company stores derived thumbnail images that can be regenerated from originals at any time, and wants to minimise cost while keeping millisecond access. Which storage class fits?**
S3 One Zone-IA. The data is recreatable, so the single-Availability-Zone risk is acceptable, and it provides millisecond retrieval at a lower price than Standard-IA.

**6. Which feature ensures that objects cannot be deleted by any principal, including the account root user, for a defined period?**
S3 Object Lock in Compliance mode, which requires versioning to be enabled on the bucket.

**7. An organisation must audit every read of objects in a sensitive bucket. What must be configured?**
CloudTrail data events for that bucket. Management events, which are on by default, do not record `GetObject`.

---

## 1.5 AWS Database Services

### Conceptual Questions

**1. Explain the CAP theorem and how it applies to the AWS database portfolio.**

The CAP theorem states that in the presence of a network partition, a distributed system must choose between consistency and availability. It is not a claim that you pick two of three in normal operation; partition tolerance is mandatory for any distributed system, so the real choice is what to do when a partition occurs. RDS Multi-AZ chooses consistency: during failover the database is briefly unavailable rather than serving divergent data. DynamoDB offers the choice per read  an eventually consistent read favours availability and latency, a strongly consistent read favours correctness. DynamoDB Global Tables choose availability at the Region level and resolve the resulting conflicts with last-writer-wins. ElastiCache with asynchronous replication chooses availability and accepts the loss of recent writes.

**2. What is the practical difference between a Global Secondary Index and a Local Secondary Index?**

An LSI shares the base table's partition key and provides an alternative sort key. It can only be created at table creation, supports strongly consistent reads, shares the base table's provisioned throughput, and constrains any single item collection to 10 GB. A GSI has an entirely independent partition and sort key, may be created or deleted at any time, is always eventually consistent, has its own provisioned throughput, and has no item-collection size constraint. In practice GSIs are used far more often; LSIs are appropriate only when strong consistency on an alternative sort order within a partition is genuinely required.

**3. Why is Aurora's storage architecture significant?**

Aurora separates compute from a purpose-built distributed storage service that replicates six ways across three Availability Zones and accepts a write once four of six segments acknowledge it. Only redo log records are shipped to storage; the storage layer materialises pages itself. The consequences are architectural rather than incremental: adding a read replica copies no data because all instances read the same volume, failover does not require catch-up, storage grows and self-heals automatically, backups are continuous and do not affect performance, and a clone can be created almost instantly using copy-on-write. This is the clearest example in the AWS portfolio of re-architecting a component rather than merely managing it.

**4. Explain why a DynamoDB partition key choice determines scalability.**

DynamoDB places an item by hashing its partition key and mapping the hash to a physical partition. Throughput and storage are distributed across partitions. If many requests share one partition-key value, they all target one partition, whose throughput is bounded regardless of table-level provisioning, and requests are throttled. Adaptive capacity redistributes some throughput toward hot partitions and isolates severe cases, but it cannot manufacture capacity for a single key. Therefore scalability is a property of key cardinality and access distribution, decided at design time and expensive to change afterwards.

**5. When is caching the wrong answer?**

When the workload is write-dominant, since a cache accelerates reads and adds work to writes. When every read must be strongly consistent, because a cache introduces a staleness window. When the access pattern has no locality  a uniform random read over a very large keyspace produces a low hit rate and the cache becomes pure overhead. When the underlying query is already fast and the latency budget is met, because the added component contributes failure modes and operational surface without benefit. And when the real problem is a missing index or an N+1 query pattern, in which case caching hides a defect rather than fixing it.

**6. Distinguish RDS Multi-AZ from RDS read replicas.**

Multi-AZ maintains a synchronous standby in a second Availability Zone for availability; in the classic instance deployment the standby is not readable and exists solely to be promoted. Read replicas are asynchronous copies used to scale read throughput, may be in the same Region or a different one, are readable, and require explicit promotion to become writable. Multi-AZ addresses availability; read replicas address performance. The Multi-AZ DB cluster deployment blurs this by providing two readable standbys, which is worth stating explicitly in an interview.

### Scenario Questions

**1. A social application's feed query takes eight seconds under load. The team proposes a larger RDS instance. Evaluate.**

A larger instance is a valid short-term mitigation and a poor diagnosis. The first step is to determine where the time is spent using Performance Insights and `EXPLAIN ANALYZE`. Common causes are a missing index producing a sequential scan, an N+1 query pattern issuing one query per feed item, a join that materialises far more rows than are returned, or lock contention. If the query is fundamentally a fan-out read of recent items per followed user, the correct architecture is often a precomputed feed: fan out on write into DynamoDB or into a Redis list per user, so the read becomes a single key lookup. Vertical scaling buys time; the redesign fixes the problem and costs less at steady state.

**2. An online store must guarantee that inventory never goes negative under concurrent purchase.**

This is a concurrency-control question, not a database-selection question. In a relational store, use a transaction with `SELECT ... FOR UPDATE` or an atomic `UPDATE inventory SET qty = qty - 1 WHERE sku = ? AND qty > 0` and treat a zero-row result as out of stock. In DynamoDB, use `UpdateItem` with an `ADD` of minus one and a `ConditionExpression` of `qty > :zero`, which is atomic within a single item, or `TransactWriteItems` if the decrement must be atomic with order creation. The critical teaching point is that read-then-write in application code is a race condition, and correctness must come from an atomic conditional operation rather than from application logic.

**3. A team must migrate a 2 TB on-premises Oracle database to AWS with under fifteen minutes of downtime.**

Use AWS Database Migration Service with the AWS Schema Conversion Tool if changing engines. DMS performs a full load followed by ongoing change data capture, so the bulk copy happens while the source remains live. The cutover is then a short window in which writes are quiesced, the remaining change backlog drains, the application's connection string is switched, and validation runs. Choose the target deliberately: Aurora PostgreSQL if the intent is to leave commercial licensing behind, RDS for Oracle if the application depends on Oracle-specific features. Plan and rehearse rollback, and validate row counts and checksums with DMS data validation before cutting over.

**4. A DynamoDB table shows heavy throttling although consumed capacity is far below provisioned capacity.**

This is the signature of a hot partition. Provisioned capacity is distributed across partitions, so a single key absorbing a disproportionate share of traffic throttles while the table-level metric looks healthy. Use Contributor Insights to identify the dominant keys. Remedies are to choose a higher-cardinality partition key, to apply write sharding by appending a calculated suffix to the key and scattering writes across the resulting keys, to introduce DAX or ElastiCache in front of a hot read key, or to switch to on-demand capacity, which handles bursts more gracefully although it does not eliminate a single-key limit.

**5. An application must serve users in three continents with low read latency and cannot tolerate a full Regional outage.**

DynamoDB Global Tables provide multi-active, multi-Region replication with local read and write latency and automatic conflict resolution by last-writer-wins, and Route 53 latency-based routing directs users to the nearest Region. If the workload is relational, Aurora Global Database provides a primary Region with read-only secondary Regions, typical cross-Region replication lag under a second, and promotion of a secondary in a disaster. The essential caveat to state is that last-writer-wins is not a distributed transaction, so any domain in which a lost concurrent update is unacceptable  a financial ledger, for example  requires a single writer Region and an explicit consistency design.

### Architecture Questions

**1. Design the data layer for a ride-hailing platform.**

Driver location updates are extremely high-frequency, small, keyed by driver identifier, and ephemeral: DynamoDB with the driver identifier as partition key, a timestamp sort key, and TTL, or a Redis geospatial index if proximity search is required in the request path. Trip state during a ride is a small, hot, frequently updated item: DynamoDB with conditional writes for state transitions. Completed trips, fares, and settlements require ACID guarantees, reporting, and auditability: Aurora PostgreSQL. Surge pricing and matchmaking work from in-memory structures in ElastiCache. Analytics and machine-learning feature generation read from an S3 data lake fed by DynamoDB export and DMS, queried with Athena. Each store is chosen against a stated access pattern, and the services communicate through events on EventBridge rather than through shared tables.

**2. Design a multi-tenant SaaS data architecture supporting both small and regulated enterprise tenants.**

Use a hybrid of pool and silo. Small tenants share a DynamoDB table with `TENANT#id` as the partition-key prefix and IAM `dynamodb:LeadingKeys` conditions enforcing isolation, which gives near-linear cost scaling and one operational footprint. Regulated enterprise tenants receive a dedicated Aurora cluster with a customer managed KMS key, satisfying data-isolation and key-control requirements and bounding blast radius. A tenant routing layer resolves a tenant to its data plane. The trade-off to articulate is that the pool model minimises cost and operational effort while concentrating blast radius, and the silo model does the reverse; the hybrid places each tenant where its requirements and its revenue justify.

**3. Design a read path targeting a p99 latency of 20 milliseconds at 100,000 reads per second.**

Layer the caches. CloudFront handles cacheable public content at the edge. The application tier consults DAX or ElastiCache, sized to hold the working set, with a hit rate target above 95 percent. DynamoDB serves the residual with a partition key chosen for even distribution, and eventually consistent reads where the staleness is acceptable, halving the capacity cost. The database is provisioned for the miss rate, not the request rate. Instrument the hit rate, the miss latency, and the p99 at each layer, because a cache with a 95 percent hit rate and a slow miss path can still violate a p99 budget  the tail is dominated by misses, which is a point many candidates overlook.

### Troubleshooting Questions

**1. An application intermittently reports "too many connections" against RDS.**

Check `DatabaseConnections` against the `max_connections` parameter, which on RDS is typically derived from instance memory. Causes include an application connection pool sized larger than the database allows multiplied by the number of application instances, connections leaked by code that fails to return them to the pool, a serverless tier scaling horizontally with one connection per execution environment, and long-running idle transactions. Remedies are RDS Proxy, correctly sized pools, connection timeouts, and a larger instance class only if the connection demand is genuinely justified.

**2. A read replica is reporting steadily increasing replica lag.**

Replication is single-threaded on some engines, so a heavy write burst on the primary, a long-running transaction, or a large `ALTER TABLE` will cause the replica to fall behind. Other causes are an undersized replica instance class relative to the primary, heavy read queries on the replica competing for its resources, and network saturation for a cross-Region replica. Diagnose with the `ReplicaLag` metric and the engine's replication status, then address the cause: size the replica at least as large as the primary, avoid long transactions, and consider Aurora, whose shared storage makes lag typically an order of magnitude smaller.

**3. After deploying a new version, the application returns stale data for several minutes.**

The likely causes are reads being routed to a replica when read-after-write consistency is required, or cached entries with a TTL longer than the deployment window, or a cache not invalidated on write. Determine which by bypassing the cache and querying the writer directly. The fix is to route consistency-sensitive reads to the writer, to invalidate or version cache keys on write, and to include a version or build identifier in cache keys so that a deployment naturally invalidates entries whose shape has changed.

**4. A DynamoDB `Query` returns fewer items than expected, and the application misses records.**

`Query` and `Scan` return at most 1 MB per call, and any filter expression is applied *after* the read, so a filtered query can return zero items while still consuming capacity and still having more pages. Application code that ignores `LastEvaluatedKey` processes only the first page. The fix is to paginate until `LastEvaluatedKey` is absent, or to use the SDK's paginator, and to prefer key conditions over filter expressions so that the read is selective rather than the filter.

**5. ElastiCache hit rate has fallen from 96 percent to 40 percent with no application change.**

Look first at `Evictions` and `DatabaseMemoryUsagePercentage`. A growing dataset that has outgrown the node evicts entries before they are reused. Other causes are a change in key naming that fragmented the keyspace, a TTL set too short, a recent failover or node replacement that started with a cold cache, or a new access pattern with poor locality. Remedies are to scale the node or add shards, to review TTLs, and to warm the cache from a snapshot after a planned replacement.

### Certification-style Questions

**1.** A company needs to improve read performance of an Amazon RDS for MySQL database that is CPU-bound on reads. Which action is MOST appropriate?

- A. Enable Multi-AZ
- B. Create read replicas and route read traffic to them
- C. Increase the backup retention period
- D. Enable storage auto scaling

**Answer: B.** The Multi-AZ standby in an instance deployment is not readable; read replicas exist precisely to scale reads.

**2.** An application requires microsecond read latency for an existing DynamoDB table with minimal application change. Which service should be used?

- A. Amazon ElastiCache for Memcached
- B. Amazon DynamoDB Accelerator (DAX)
- C. Amazon CloudFront
- D. Amazon RDS Proxy

**Answer: B.** DAX is a write-through, DynamoDB-specific cache that is API-compatible, so the application change is limited to the client.

**3.** Which DynamoDB feature allows an application to write an item only if it does not already exist?

- A. A transaction
- B. A conditional expression using `attribute_not_exists`
- C. A global secondary index
- D. Time to live

**Answer: B.** Conditional writes provide optimistic concurrency without a transaction and at ordinary write cost.

**4.** A Lambda function at high concurrency exhausts connections to an Aurora database. Which solution addresses this with the LEAST application change?

- A. Increase the Aurora instance size
- B. Use Amazon RDS Proxy
- C. Migrate to DynamoDB
- D. Add read replicas

**Answer: B.** RDS Proxy pools and multiplexes connections and is designed for exactly this failure mode.

**5.** Which statement about an Amazon DynamoDB Local Secondary Index is TRUE?

- A. It can be created at any time after table creation
- B. It uses a partition key different from the base table
- C. It supports strongly consistent reads and must be created with the table
- D. It has its own provisioned throughput separate from the table

**Answer: C.** All the other statements describe a Global Secondary Index.

**6.** A company must recover its database to any point within the last 20 days after an accidental deletion of rows. Which capability provides this?

- A. Multi-AZ deployment
- B. Read replicas
- C. Automated backups with point-in-time recovery
- D. Manual snapshots taken weekly

**Answer: C.** Multi-AZ and replicas replicate the deletion faithfully; only PITR restores to a moment before it.

**7.** Which is the MOST cost-effective DynamoDB configuration for a new application whose traffic pattern is entirely unknown?

- A. Provisioned capacity sized for the expected peak
- B. On-demand capacity mode
- C. Provisioned capacity with reserved capacity purchased
- D. Provisioned capacity with auto scaling and a high minimum

**Answer: B.** On-demand requires no forecast and scales instantly; convert to provisioned once the pattern is established and measured.

---

## 1.6 AWS Network Services

### Conceptual Questions

**1. What actually makes a subnet "public"?**
Its associated route table contains a route (typically `0.0.0.0/0`) whose target is an Internet Gateway. Nothing else  not the name, not the CIDR, not the auto-assign public IP setting, though a resource in it also needs a public IP or Elastic IP to be reachable from the internet.

**2. Explain the difference between a security group and a network ACL, and when you would deliberately use a NACL.**
Security groups attach to network interfaces, are stateful, allow-only, and evaluate all rules with any match permitting. NACLs attach to subnets, are stateless, support deny, and evaluate in rule-number order with first match winning. Use a NACL when you need to *deny* something specific (a malicious CIDR), when you need a subnet-wide guardrail that application teams cannot alter by editing their own security groups, or when a compliance framework requires two independent layers. Application intent belongs in security groups.

**3. Why are five IP addresses unusable in every subnet?**
The network address, the VPC router (base plus one), the Amazon DNS resolver (base plus two), an address reserved for future AWS use (base plus three), and the broadcast address. AWS does not support broadcast but still reserves the address.

**4. What is the difference between a Gateway endpoint and an Interface endpoint?**
A Gateway endpoint is a route-table entry to a prefix list, supports only S3 and DynamoDB, is free, and is not reachable from outside the VPC (no peering, VPN, or Direct Connect). An Interface endpoint is an ENI with a private IP in your subnet, supports most services plus partner and custom services via PrivateLink, has a security group, is reachable from connected networks, and is charged hourly per Availability Zone plus per gigabyte.

**5. Why does Route 53 offer an Alias record when CNAME already exists?**
CNAME cannot be used at a zone apex, requires a second resolution step, and cannot track an AWS resource's changing addresses. Alias records resolve inside Route 53 to the current addresses of an AWS resource, work at the apex, return A or AAAA answers directly, and are not charged when the target is an AWS resource.

**6. What is the practical difference between control plane and data plane, and why does it matter for disaster recovery?**
The control plane changes configuration; the data plane carries traffic. Data planes are engineered for much higher availability. A recovery plan that requires control-plane calls (launching instances, changing DNS records) in an impaired Region may fail exactly when it is needed. Prefer pre-provisioned capacity and health-check-driven failover, whose recovery path is data-plane only.

**7. Why does an Internet Gateway not appear in an instance's network configuration?**
The IGW performs one-to-one NAT outside the guest. The instance only ever sees its private address; the IGW rewrites source and destination addresses at the VPC boundary. This is why you must never configure a public address inside the operating system.

### Scenario Questions

**1. A regulator requires that a database be provably unreachable from the internet. How do you demonstrate this?**
Place it in a subnet whose route table contains only the `local` route plus, at most, Gateway endpoints. Show the route table: with no Internet Gateway, NAT Gateway, or Transit Gateway route, there is no path in either direction regardless of security group configuration. Reinforce with a security group allowing only the application security group on the database port, Network Access Analyzer findings showing no internet path, and Flow Logs as evidence.

**2. Fifteen VPCs across five accounts must communicate, plus on-premises connectivity. Peering or Transit Gateway?**
Transit Gateway. Peering would require 105 connections and route entries in every subnet route table, and peering cannot carry on-premises traffic transitively. Transit Gateway gives 15 attachments, one summarised route per VPC, native Direct Connect and VPN attachment, and route tables for segmentation. Share it across accounts with Resource Access Manager.

**3. Your API must return within 100 milliseconds for users worldwide, and some responses are cacheable for 30 seconds.**
Regional API Gateway HTTP APIs in two or three Regions, fronted by CloudFront for edge TLS termination and caching, with Route 53 latency-based routing plus health checks between Regions. Use a deliberate cache key with only the parameters that vary the response, enable compression, and keep authorizer results cached.

**4. A partner must call your service, but they refuse to expose it over the internet and their VPC uses the same CIDR as yours.**
AWS PrivateLink. Put your service behind a Network Load Balancer, create a VPC endpoint service, and allow their account. They create an Interface endpoint in their VPC, reaching your service via an IP in *their* address space. Overlapping CIDRs are irrelevant because no routes are exchanged.

**5. During a deployment you want 5 percent of production traffic on a new version, with fast rollback.**
For containers behind an ALB, use weighted target groups on the listener rule  rollback is a single API call and takes effect immediately with no DNS caching. For whole-stack changes, use Route 53 weighted records, accepting that rollback is bounded by TTL. For API Gateway, use a canary deployment on the stage. Choose based on how fast rollback must be and the granularity of the change.

**6. Costs have risen sharply and the largest line item is `NatGateway-Bytes`.**
Enable Flow Logs, query in Athena grouped by destination, and identify the top talkers. Almost always this is S3, ECR image pulls, and CloudWatch Logs. Add a Gateway endpoint for S3 and DynamoDB (free) and Interface endpoints for `ecr.api`, `ecr.dkr`, `logs`, `sts`, and `secretsmanager`. Verify with Flow Logs that traffic has shifted, then confirm the reduction in Cost Explorer.

### Architecture Questions

**1. Design the network for a three-tier application requiring 99.99 percent availability in one Region.**
A `/16` VPC across three Availability Zones. Public `/24` per zone containing only the internet-facing ALB and one NAT Gateway per zone. Private `/20` per zone for the ECS or EC2 tier, with per-zone route tables pointing at the NAT Gateway in the same zone. Isolated `/22` per zone for Multi-AZ RDS in a DB subnet group. Gateway endpoint for S3 and DynamoDB; Interface endpoints in all three zones for the AWS APIs used. Security groups chained by reference: ALB security group open on 443 from the internet, application security group allowing 8080 from the ALB security group, database security group allowing 5432 from the application security group. Route 53 alias to the ALB, CloudFront in front, WAF attached, Flow Logs to a central account.

**2. How would you design network segmentation across 40 AWS accounts?**
Transit Gateway in a network account shared via Resource Access Manager, with separate Transit Gateway route tables per environment so production and non-production attachments cannot route to each other. A shared-services VPC holding centralised Interface endpoints and Route 53 Resolver endpoints, with private hosted zones associated to workload VPCs. An inspection VPC with Network Firewall behind a Gateway Load Balancer for east-west and egress inspection. Service Control Policies preventing the creation of Internet Gateways in workload accounts. A single, centrally governed IPAM allocation so CIDRs never overlap.

**3. An EKS cluster will run 20,000 pods. What is your networking plan?**
The VPC CNI assigns a VPC address to every pod, so plan address space first: dedicate large subnets, and add a secondary CIDR from `100.64.0.0/10` with CNI custom networking so pod addresses do not consume routable space. Enable prefix delegation to allocate `/28` prefixes per ENI, which increases pod density per node and reduces API pressure. Use the AWS Load Balancer Controller in IP target mode so the ALB targets pods directly. Use security groups for pods where per-workload policy is needed, and a network policy engine for intra-cluster policy. Spread node groups across three Availability Zones and use topology-aware routing to keep traffic zonal.

**4. Design an API that accepts bursts of 50,000 requests per second but whose downstream can only handle 500 per second.**
Do not let the burst reach the downstream. API Gateway integrates directly with SQS (an AWS service integration, no Lambda), returning `202 Accepted`. A consumer  Lambda with reserved concurrency, or an ECS service scaled on queue depth  drains the queue at a controlled rate. Add a dead-letter queue, idempotency keys so retries are safe, and per-route throttling as a second guardrail. The queue converts a scaling problem into a latency problem, which is almost always the right trade.

**5. When would you choose Global Accelerator over Route 53 latency routing?**
When failover must be fast and independent of DNS caching, when clients pin IP addresses (device firmware, corporate allow-lists), when the protocol is not HTTP, or when you want traffic to enter the AWS backbone at the nearest edge for non-cacheable workloads. Global Accelerator gives two static anycast addresses and shifts traffic at the network layer in seconds. Route 53 is cheaper and sufficient when DNS TTL-bounded failover is acceptable.

### Troubleshooting Questions

**1. An instance in a private subnet cannot reach the internet. Diagnose systematically.**
Check in this order: (a) the private subnet's route table has `0.0.0.0/0` pointing to a **NAT Gateway**, not an Internet Gateway; (b) the NAT Gateway is in a **public** subnet whose route table points `0.0.0.0/0` at an Internet Gateway; (c) the NAT Gateway has an Elastic IP and is in `available` state; (d) the instance's security group allows the required **outbound** traffic; (e) the NACLs on both the private and the public subnet allow outbound traffic and inbound **ephemeral ports** for the return path; (f) DNS is resolving  `enableDnsSupport` on the VPC; (g) NAT Gateway CloudWatch metrics show no `ErrorPortAllocation`. Confirm with Reachability Analyzer and Flow Logs, looking for `REJECT` entries.

**2. You cannot SSH to an EC2 instance. Walk through it.**
(a) Does the instance have a public IP or Elastic IP, and are you connecting to the right address? (b) Is it in a public subnet with an Internet Gateway route? (c) Does the security group allow inbound TCP 22 from your source address? (d) Does the NACL allow inbound 22 **and** outbound ephemeral ports 1024–65535? (e) Is the instance running, and did it pass both status checks? (f) Is `sshd` running and listening  check the system log or serial console? (g) Are the key pair and file permissions correct, and are you using the right username for the AMI? (h) Is a host-level firewall blocking? A **timeout** points at routing, security group, or NACL; **connection refused** means the packet reached the host and nothing was listening; a **key rejection** means the network is fine and the problem is credentials.

**3. ALB targets never become healthy.**
The target's security group must allow the **health check port** from the ALB's security group  this is the single most common cause. Then confirm the health check path returns 200 (or matches the configured matcher), that the application listens on the configured port and on all interfaces rather than only `127.0.0.1`, that the health check protocol matches, that the target is registered in a subnet the ALB can reach, and that the health check timeout is longer than the application's response time. Check `TargetConnectionErrorCount` and the target group's health status reason string, which is usually explicit.

**4. Inside the VPC, a service name resolves to a public IP address instead of the private endpoint.**
Private DNS on the Interface endpoint is disabled, or `enableDnsSupport` or `enableDnsHostnames` is off on the VPC, or a private hosted zone is not associated with this VPC, or a Resolver rule is forwarding the query elsewhere. Confirm with `dig` from an instance against `169.254.169.253`, and check the endpoint's private DNS setting.

**5. Intermittent HTTP 502 responses from the ALB with no application errors.**
Most commonly the backend closed a keep-alive connection that the ALB believed was still open, because the backend's keep-alive timeout is shorter than the ALB's idle timeout. Set the backend keep-alive above the ALB idle timeout. Other causes: the target returned a malformed response or headers exceeding the limit, or the target was deregistered while requests were in flight (increase the deregistration delay). Compare `HTTPCode_ELB_5XX_Count` with `HTTPCode_Target_5XX_Count` to determine whether the load balancer or the target generated the error, and inspect the ALB access logs' `elb_status_code` and `target_status_code` fields.

**6. Two peered VPCs cannot communicate even though the peering connection is `active`.**
Route tables on **both** sides must have a route to the other VPC's CIDR with the peering connection as target, and this must be present in every relevant subnet route table, not just one. Security groups must allow the traffic  and note that a security group in VPC A can reference a security group in VPC B only when the VPCs are peered and the reference is explicitly configured. NACLs on both sides must permit traffic in both directions. Finally, confirm the CIDRs do not overlap, and enable DNS resolution over the peering if you rely on private hosted-zone names.

### Certification-style Questions

**1. A company needs to block a specific malicious IP address from reaching any resource in a subnet. What should they use?**
A network ACL deny rule with a rule number lower than any allow rule that would match. Security groups cannot express deny.

**2. An application in a private subnet must access Amazon S3 without traversing the internet, at the lowest cost. What should the architect implement?**
A Gateway VPC endpoint for S3, with the corresponding prefix-list route added to the private subnets' route tables. It carries no charge, unlike an Interface endpoint or a NAT Gateway.

**3. A company runs an application in three Regions and wants users routed to the Region that gives them the best performance, with automatic removal of an unhealthy Region.**
Route 53 latency-based routing records for each Region, each associated with a health check. Geolocation would route by location rather than performance; weighted would not adapt to latency.

**4. An API must be reachable only from within the corporate VPC and never from the internet.**
A Private API Gateway REST API, accessed through an Interface endpoint for `execute-api`, with a resource policy that allows only the specific `aws:SourceVpce`. HTTP APIs do not support private endpoints.

**5. Instances in a private subnet suddenly cannot download operating system updates, while everything else works. The NAT Gateway shows increasing `ErrorPortAllocation`.**
The NAT Gateway has exhausted source ports toward a small number of destinations. Reduce concurrent connections through connection reuse, spread traffic across additional NAT Gateways, or move the traffic off NAT via endpoints where the destination is an AWS service.

**6. Which combination provides static IP addresses and the ability to handle millions of requests per second with very low latency for a TCP-based protocol?**
A Network Load Balancer with an Elastic IP in each Availability Zone. An ALB is layer 7 and offers no static IPs; API Gateway is HTTP-oriented and adds latency.

**7. A team needs to give an on-premises data centre access to an AWS service privately, and the on-premises network already reaches AWS over Direct Connect.**
An Interface endpoint, because it presents an ENI with a routable private IP that on-premises networks can reach. A Gateway endpoint would not work  it is route-table scoped and unreachable from outside the VPC.

---

## 1.7 Cloud-Native Design Patterns

### Conceptual Questions

1. Define cloud-native in your own words and explain why lift-and-shift migration does not make an application cloud-native.
2. Distinguish serverless from microservices. Can a system be one without the other? Give an example of each.
3. What does "loose coupling" mean concretely, and how do events reduce temporal coupling in ways that synchronous APIs cannot?
4. Explain the difference between an event and a command, and why the distinction affects system coupling.
5. Why must event consumers be idempotent? Describe a concrete implementation of idempotency on AWS.
6. Compare choreography and orchestration. What are the operational consequences of each?
7. What is eventual consistency, and how would you explain its user-visible effects to a non-technical product owner?
8. Explain the CAP theorem's relevance to a microservices architecture that spans multiple Availability Zones.
9. What is a distributed monolith, and what single test reveals one?
10. Why is API-first considered an organisational practice as much as a technical one?

### Scenario Questions

1. An e-commerce checkout takes 8 seconds because it synchronously calls inventory, payment, fraud, email, and analytics services. Redesign it and quantify the expected user-perceived latency improvement.
2. A Lambda function connected to RDS fails during traffic spikes with connection errors. Diagnose and give two distinct remedies.
3. Traffic is highly variable: near zero overnight, 40x peak for three hours each morning. Choose a compute strategy and justify it on cost and latency grounds.
4. A partner integration requires guaranteed ordering of financial transactions per customer account. Which AWS messaging service and configuration would you choose, and what throughput limitation must you communicate?
5. Your team must publish an API that mobile clients  which cannot be force-upgraded  will consume for at least three years. Describe your versioning and deprecation strategy.
6. An event consumer had a bug for six hours and dropped 200,000 events. How do you recover the lost processing?
7. A microservices platform has grown to 60 services and deployment velocity has _fallen_. Diagnose the likely causes and propose remedies.

### Architecture Questions

1. Design a serverless image-processing pipeline that handles 10,000 uploads per minute, produces three thumbnail sizes, and must not lose an image. Draw the architecture and justify each component.
2. Design a multi-tenant SaaS API where no single tenant may degrade another's performance. Address throttling, isolation, and cost attribution.
3. Design an order-fulfilment system implementing the Saga pattern. Specify compensating actions and how you would make the workflow auditable.
4. You must migrate a monolithic Java application to cloud-native over 18 months without a feature freeze. Present your migration strategy.
5. Design the observability strategy for a system with 30 microservices and heavy asynchronous messaging. Specify metrics, alarms, tracing, and log structure.

### Troubleshooting Questions

1. An SQS queue's `ApproximateAgeOfOldestMessage` is growing steadily while consumer CPU sits at 20%. List possible causes in order of likelihood.
2. Lambda p99 latency is 3 seconds while p50 is 40 ms. Explain the likely cause and three mitigations.
3. EventBridge shows successful `PutEvents` but a target Lambda is never invoked. Enumerate your diagnostic steps.
4. Customers report duplicate confirmation emails during high traffic. Identify the root cause and the fix.
5. After a deployment, an ECS service is stuck with tasks repeatedly stopping and restarting. What do you check, and in what order?

### Certification-style Questions

1. A company needs to decouple a web tier from a batch processing tier, guarantee that each message is processed at least once, and retry failures automatically. Which service is most appropriate, and why is SNS alone insufficient?
2. An application must notify four independent downstream systems whenever a new file lands in S3, with each system able to fail and retry independently. Design the messaging topology.
3. A workflow requires branching logic, retries with backoff, a 30-minute wait for external approval, and full audit history. Which service and why?
4. A serverless API must reject malformed requests before invoking any compute. Which feature achieves this at the lowest cost?

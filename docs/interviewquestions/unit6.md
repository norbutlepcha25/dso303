# Unit 6: Interview Questions

## 6.1 AWS Storage Solutions

### 6.1.1 Object Storage with Amazon S3

#### Conceptual Questions

!!! question "Why should application S3 permissions be attached to an ECS task role rather than the task execution role?"
    The execution role is used by the ECS agent to pull images, fetch secrets and environment files, and write logs before and around container start. The task role is assumed by the application code at runtime. Separating them enforces least privilege: the platform can pull images without being able to read business data, and the application can read business data without being able to pull arbitrary images. It also makes CloudTrail audit trails clearer.

!!! question "Explain the difference between S3 Event Notifications and the S3 EventBridge integration."
    Event Notifications are configured per bucket with event types and prefix or suffix filters, and deliver directly to Lambda, SQS standard queues or SNS standard topics. Overlapping filters for the same event type are not permitted, so multiple consumers require SNS fan-out. The EventBridge integration sends all bucket events to the default event bus, where any number of rules can filter on any event field and route to many target types, with archive, replay and cross-account delivery. Event Notifications are simpler and cheaper; EventBridge is more flexible and better suited to decentralised, multi-team architectures.

!!! question "What guarantees do conditional writes provide, and what do they not provide?"
    `If-None-Match: *` guarantees that a write succeeds only if no object exists at the key, and `If-Match` guarantees that it succeeds only if the current ETag matches. Together they provide atomic create-if-absent and compare-and-swap on a single key. They do not provide transactions across multiple keys, lock leases or expiry, ordering of events, or queries. Those require DynamoDB, a table format such as Iceberg, or a workflow service.

!!! question "Why do Access Points exist when bucket policies already control access?"
    A single bucket policy has a size limit and becomes a shared, high-risk document when many applications use the same bucket. Access Points give each application or team its own endpoint with its own policy and network origin, while the bucket policy delegates to access points and enforces guardrails. This distributes ownership, reduces the risk of one change breaking every consumer, and allows VPC-only access for specific applications.

#### Scenario Questions

!!! question "A document-processing Lambda function is triggered when PDFs are uploaded. During a marketing campaign, uploads spike and the function's writes to an Aurora database cause connection exhaustion. How should the design change?"
    Insert an SQS queue between S3 and Lambda. Configure S3 Event Notifications or an EventBridge rule to send events to the queue, and use an SQS event source mapping with a maximum concurrency setting that the database can sustain. Add a dead-letter queue for poison messages and use RDS Proxy for connection pooling (Chapter 1.2.3). The queue absorbs the burst, preserving every event, while the database sees a controlled rate.

!!! question "A team reports that their EKS pods receive AccessDenied when reading from a bucket, although the IAM role policy allows s3:GetObject on the bucket's objects. What should be checked?"
    First, confirm the pod is actually using the intended role by running `aws sts get-caller-identity` in the pod, and verify the Pod Identity association or IRSA annotation matches the pod's namespace and service account. Then read the error message for the policy type that denied the request. Check the bucket policy for explicit denies, such as `aws:SourceVpce` conditions that the pod's traffic path does not meet. Check the VPC endpoint policy, the KMS key policy if SSE-KMS is used, and any SCPs or RCPs. Finally, confirm the key exists, because without `s3:ListBucket` a missing key returns 403.

!!! question "A company serves its React front end from a public S3 website endpoint. Security has requested that the bucket become private and that TLS be enforced. What is the target architecture?"
    Place a CloudFront distribution in front of the bucket's REST endpoint using Origin Access Control. Enable Block Public Access on the bucket and replace the public policy with one that allows `s3:GetObject` only to the CloudFront service principal for the specific distribution ARN. Configure an ACM certificate on CloudFront and redirect HTTP to HTTPS. In the CI/CD pipeline, deploy content-hashed file names and invalidate only `index.html`.

#### Architecture Questions

!!! question "Design a multi-tenant data lake in which 40 analyst groups, managed in IAM Identity Center, need read access to their own prefixes, and ETL services on ECS need write access to raw zones."
    Store data in S3 with a prefix per tenant and zone. For ETL services, use ECS task roles scoped to the raw prefixes, reaching S3 through a Gateway endpoint with an organisation-scoped endpoint policy. For analysts, configure S3 Access Grants linked to IAM Identity Center, granting each group READ on its tenant prefixes; tools such as Athena and SageMaker Studio obtain temporary credentials through Access Grants. Register curated tables in the Glue Data Catalog and apply Lake Formation permissions for column and row-level control. Enforce encryption with SSE-KMS and Bucket Keys, enable Macie for sensitive data discovery, and use Inventory and Storage Lens for governance.

!!! question "Design an active-passive multi-Region object storage layer for a global application with a recovery time objective of minutes."
    Create buckets in two Regions with versioning and bidirectional replication, optionally with Replication Time Control for predictable replication lag. Create a Multi-Region Access Point over both buckets, configure the primary Region as active and the secondary as passive, and have applications use the Multi-Region Access Point ARN. During a Regional impairment, operators or automation switch routing through the failover controls, which are designed to take effect within minutes. Test failover in regular game days and monitor replication metrics.

#### Troubleshooting Questions

!!! question "A backfill job writing 50 million objects under a single date prefix begins to fail with 503 Slow Down errors. What is happening and how should it be fixed?"
    S3 is repartitioning the prefix to scale its request capacity, and the job is exceeding the current rate. Configure the SDK with `adaptive` retry mode so that it rate-limits itself, add a high-cardinality component such as a hash near the start of the key to spread load, ramp concurrency gradually, and ensure the job does not add its own tight retry loop. Once S3 has repartitioned, throughput will increase.

!!! question "After enabling SSE-KMS on a bucket, a cross-account consumer can list objects but receives AccessDenied on GetObject. Why?"
    Listing requires only S3 permissions, whereas reading an SSE-KMS object also requires `kms:Decrypt` on the key. The consumer's role must have `kms:Decrypt` in its identity policy, and the key policy in the owning account must allow that role (or its account) to use the key. If the key is an AWS managed key (`aws/s3`), cross-account use is not possible, and a customer managed key is required.

### 6.1.2 Block Storage with Amazon EBS

#### Conceptual Questions

!!! question "Why is WaitForFirstConsumer the recommended binding mode for EBS StorageClasses?"
    EBS volumes are zonal. With `Immediate` binding, the volume is created when the PVC is created, before the scheduler has chosen a node, so it may be placed in a zone where the pod cannot be scheduled because of node selectors, resource availability or topology constraints. `WaitForFirstConsumer` delays creation until the scheduler has selected a node, and the driver then creates the volume in that node's zone, guaranteeing alignment.

!!! question "How do ECS task-attached EBS volumes differ from Kubernetes StatefulSet volumes?"
    ECS creates a new volume for each task at launch, configured in the service or RunTask call, and optionally deletes it when the task stops. A replacement task receives a new volume. A StatefulSet gives each replica a stable identity and a persistent PVC that is reattached to the replica with the same identity after rescheduling. ECS volumes therefore suit scratch and snapshot-seeded data, while StatefulSets suit durable per-replica state.

!!! question "Why can an EBS snapshot encrypted with the AWS managed key not be shared with another account?"
    The AWS managed key `aws/ebs` has a key policy controlled by AWS that allows use only within the owning account. Another account cannot be granted permission to decrypt with it. Sharing therefore requires re-encrypting the snapshot, by copying it, with a customer managed key whose key policy allows the target account.

!!! question "What is the role of EC2 Image Builder in an EBS-centric fleet architecture?"
    Image Builder automates the creation of golden AMIs, which are EBS snapshots with launch metadata. It applies hardening and agent components, tests the image, distributes it to Regions and accounts with appropriate encryption, can update launch templates or publish AMI IDs, and retires old images through lifecycle policies. Fleets consume images through launch templates and Auto Scaling group instance refresh, supporting immutable infrastructure.

#### Scenario Questions

!!! question "After a node failure in us-east-1a, a pod from a StatefulSet remains Pending with a volume node affinity conflict. The cluster has spare nodes in us-east-1b and us-east-1c. What is happening and how should the platform be improved?"
    The pod's PVC is bound to an EBS volume in us-east-1a, and the volume cannot attach to nodes in other zones. No schedulable node exists in us-east-1a. The immediate fix is to provide capacity in us-east-1a, for example by allowing Karpenter or the node group to launch a node there. Longer term, ensure node provisioning covers every zone with volumes, spread replicas across zones with application-level replication so that the service remains available when one replica is Pending, and use snapshots to restore into another zone if the zone is impaired.

!!! question "A database on gp3 provisioned at 16,000 IOPS and 1,000 MiB/s shows high latency and never exceeds about 300 MiB/s. The volume metrics show a high queue length. What should be investigated?"
    Check the instance type's EBS bandwidth. If the instance's baseline EBS throughput is around 300 MiB/s, the instance, not the volume, is the bottleneck; instance-level EBS burst balance metrics would show depletion. The remedy is to move to an instance type with higher EBS bandwidth. Also confirm that other volumes on the same instance are not consuming shared bandwidth, and that the I/O size and concurrency allow the volume to reach its throughput limit.

!!! question "A company's security team is concerned that an attacker with administrator credentials in the production account could delete all EBS snapshots. What controls should be introduced?"
    Copy snapshots to a separate backup account using AWS Backup cross-account copies or DLM cross-account copy policies, and store them in a vault protected by Vault Lock in compliance mode. Create Recycle Bin retention rules with rule lock enabled in the production account so that deleted snapshots remain recoverable. Use SCPs to deny deletion of backup vaults and disabling of Recycle Bin rules except by a break-glass role, and monitor with CloudTrail and GuardDuty.

#### Architecture Questions

!!! question "Design a disaster recovery strategy for a self-managed database on EKS with an RPO of one hour for Regional failure and 15 minutes for zone failure."
    Run the database as a StatefulSet with three replicas across zones using EBS gp3 volumes, with synchronous or near-synchronous replication so that a zone failure is handled by promoting a replica, giving an RPO well within 15 minutes. Use VolumeSnapshots or AWS Backup to create snapshots at least every hour, complemented by continuous write-ahead log archiving to S3 for finer recovery. Copy snapshots to a recovery Region at least hourly, re-encrypted with a KMS key in that Region, optionally with time-based copy to bound copy duration. Keep the EKS cluster and storage configuration as code so that the recovery Region can be deployed quickly, and rehearse the restore regularly.

!!! question "Design a golden image pipeline that delivers patched, encrypted AMIs to three Regions and two accounts every week, and rolls them out safely."
    Create an EC2 Image Builder pipeline with a weekly schedule. The recipe uses the latest Amazon Linux parent image, hardening and agent components, and an encrypted gp3 root volume. Test components validate the image. The distribution configuration copies the AMI to three Regions and shares it with two accounts, re-encrypting snapshots with each Region's customer managed key and publishing the AMI ID to Parameter Store. An EventBridge rule on pipeline completion triggers a CodePipeline that updates launch templates and starts Auto Scaling group instance refresh with minimum healthy percentage and checkpoints, first in staging and then in production. Image Builder lifecycle policies retire old AMIs and snapshots.

#### Troubleshooting Questions

!!! question "A PVC resize from 100 Gi to 200 Gi was applied, but the application still reports 100 Gi of free space capacity. What could be wrong?"
    Confirm that the StorageClass has `allowVolumeExpansion: true`. Inspect the PVC conditions and events: the volume may still be in the Elastic Volumes `modifying` state, or the file system resize may be pending until the pod restarts on older configurations. A previous modification within the cooling period can also block a new one. Check the EBS CSI controller logs for errors such as missing IAM or KMS permissions.

!!! question "An ECS service using task-attached EBS volumes fails to start tasks with an error about volume creation. Which configuration elements should be checked?"
    Check that the service's volume configuration specifies an infrastructure role that ECS can assume and that has `AmazonECSInfrastructureRolePolicyForVolumes`. If a customer managed KMS key is used, confirm that the role and the key policy allow the required KMS actions. Verify that the task definition declares the volume with `configuredAtLaunch: true` and that names match, that the snapshot ID exists and is accessible, that requested IOPS and throughput are valid for the volume type and size, and that account EBS quotas are not exhausted.

### 6.1.3 File Storage with Amazon EFS

#### Conceptual Questions

1. Why does a cloud-native architecture that emphasises stateless compute still need a shared file system?

    Model answer: Statelessness is achieved by moving state into managed services. Most state belongs in databases and object stores, but some software (CMS platforms, legacy applications, ML inference with large models, shared build caches) is written against a POSIX file API and requires concurrent shared access. EFS externalises that file state into a managed, multi-AZ service so that compute remains replaceable.

2. Explain the difference between IAM authorisation and access points in EFS.

    Model answer: IAM authorisation decides whether a principal may mount and with which client permissions (mount, write, root access), evaluated against identity policies and the file system policy. Access points enforce the POSIX identity used for all operations and the directory the client sees. IAM controls entry; access points control identity and scope inside the file system.

3. What does the `storage` field of an EFS PVC control?

    Model answer: Nothing on the EFS side. Kubernetes requires the field, but EFS is elastic and does not enforce it. Usage must be controlled by monitoring and governance.

4. Why is close-to-open consistency important for application designers?

    Model answer: A client is guaranteed to see another client's writes only after that client closes the file and the reader subsequently opens it. Applications that keep files open and expect instant visibility of concurrent writes may read stale data, so coordination through locks, file renames or messaging is needed.

#### Scenario Questions

1. A team deploys WordPress on ECS Fargate across two AZs. Tasks in AZ-b fail with `ResourceInitializationError` while tasks in AZ-a start normally. What is the most likely cause?

    Model answer: There is no mount target in AZ-b, or the AZ-b mount target's security group or subnet NACL blocks TCP 2049 from the task security group. Verify mount targets per AZ and security group rules.

2. An inference Lambda function loads a 3 GB model from EFS. During a traffic spike, latency and EFS costs rise sharply. What would you change?

    Model answer: Cache the model in a module-level global so warm invocations reuse it; use provisioned concurrency so cold starts happen before traffic; cap concurrency with reserved concurrency; consider a container image with the model baked in if models change rarely. Monitor `ClientConnections` and `DataReadIOBytes`.

3. Developers report that `npm install` inside a pod using an EFS-backed workspace takes ten times longer than on a laptop. Explain why and suggest a design change.

    Model answer: `npm install` creates tens of thousands of small files, each requiring several NFS metadata round trips. Use an `emptyDir` or local ephemeral storage for `node_modules`, and use EFS only for sharing final artefacts or a compressed cache archive.

#### Architecture Questions

1. Design a multi-tenant JupyterHub platform on EKS for 1,500 students, each with a persistent home directory.

    Model answer: Use the EFS CSI driver with dynamic `efs-ap` provisioning so each student's PVC receives an access point with a unique uid/gid and `directoryPerms: 700`. Because the access point quota is indicatively 1,000 per file system, use two file systems and two StorageClasses, assigning cohorts to each. Install the driver as an add-on with Pod Identity; enforce TLS and deny root through file system policies; enable lifecycle to IA and Archive for inactive students; back up with AWS Backup; tag by cohort for cost allocation.

2. Design regional disaster recovery for an ECS application that stores uploads on EFS with an RPO of 15 minutes and an RTO of one hour.

    Model answer: Enable EFS Replication to a second Region; pre-create mount targets, access points and the file system policy in the DR Region with IaC; replicate the database with Aurora Global Database; keep a pilot light ECS service with zero or minimal tasks referencing the DR file system and access point IDs; use Route 53 failover. Keep AWS Backup with cross-Region copies for logical corruption. Rehearse failover by deleting replication in a test environment.

#### Troubleshooting Questions

1. A pod is stuck in `ContainerCreating`, and `kubectl describe` shows `mount.nfs4: access denied by server`. The network path is correct. What do you check?

    Model answer: The file system policy (does it require TLS, a specific access point, or a principal that is not the node or driver role?), whether the PV uses `tls` and the access point handle, and whether the role presented has `ClientMount` and `ClientWrite`. Check CloudTrail for denied mount events.

2. An application on EC2 intermittently freezes for minutes, then resumes, and kernel logs show "nfs: server not responding, still trying". What is happening?

    Model answer: The NFS client is using a hard mount and cannot reach the mount target, perhaps due to network disruption, security group changes, or the efs-utils TLS proxy terminating. Operations block until connectivity returns. Check the efs-utils watchdog logs, VPC Flow Logs for port 2049, and instance network metrics. Do not switch to soft mounts for writable data.

3. After deleting a large number of PVCs, `StorageBytes` of the file system does not decrease. Why?

    Model answer: With the default behaviour of the CSI driver, deleting a dynamically provisioned PVC removes the access point but leaves the directory and its data. Clean up orphaned directories, or configure the driver option that deletes access point root directories if the driver version supports it and the data retention policy allows it.

### 6.1.4 Caching Strategies with Amazon ElastiCache

#### Conceptual Questions

1. Why does the order of operations "update the database, then delete the cache key" produce fewer stale reads than "update the database, then set the new value in the cache"?

    Model answer: Two concurrent writers setting values can interleave so that the older value is written to the cache last, leaving it stale until the TTL expires. Deleting forces the next reader to fetch the current database value; the remaining race is short and bounded by the TTL.

2. Explain why a cache with a 95 percent hit ratio can become a single point of failure.

    Model answer: The database receives only 5 percent of reads and is often sized for that. If the cache fails or restarts cold, the database receives twenty times its usual read load and may fail. The cache has become a hard dependency; mitigations are Multi-AZ, warm-up, circuit breakers with load shedding, and database headroom.

3. What is the difference between read-through and cache-aside?

    Model answer: In cache-aside, the application code explicitly checks the cache, loads from the database and populates the cache. In read-through, a caching layer or library performs the loading, so application code sees only the cache interface. Read-through centralises policy; cache-aside keeps it explicit in each service.

4. When should MemoryDB be chosen over ElastiCache?

    Model answer: When the in-memory data is the system of record and losing acknowledged writes is unacceptable, for example leaderboards, counters or sessions that cannot be rebuilt. MemoryDB durably logs writes across AZs before acknowledging them, at the cost of higher write latency.

#### Scenario Questions

1. An e-commerce homepage aggregate takes 800 ms to compute and expires every 60 seconds. At each expiry, database CPU spikes to 100 percent. What would you implement?

    Model answer: Stampede protection: a lock so only one worker recomputes, serve-stale while revalidating, and XFetch or a scheduled refresh-ahead job through EventBridge Scheduler so the value is refreshed before expiry. Add TTL jitter if multiple aggregates share the same schedule.

2. Security testing reveals that requests for random product IDs all reach DynamoDB. Explain and fix.

    Model answer: Missing negative caching causes cache penetration. Cache a not-found sentinel with a short TTL, validate ID formats at the API layer, rate-limit clients, and consider a Bloom filter for very large key spaces.

3. A Lambda function using ElastiCache shows `NewConnections` roughly equal to invocation count and elevated latency. What is wrong?

    Model answer: The client is created inside the handler, so each invocation performs a new TCP and TLS handshake and authentication. Move client creation to the initialisation phase and use a small pool.

#### Architecture Questions

1. Design caching for a microservice-based product catalogue where the catalogue service writes to DynamoDB, and the search, pricing and recommendation services each cache product data.

    Model answer: Each consuming service owns its own cache keys in ElastiCache (separate caches or key prefixes and RBAC users). DynamoDB Streams feed an EventBridge Pipe that publishes ProductChanged events to a bus; each service has a rule targeting its own invalidator Lambda, which deletes its keys idempotently. Keys include a schema version; TTLs with jitter are safety nets; hot products use key replication; CloudFront caches public product pages with short TTLs and invalidation for price changes.

2. Design a globally distributed session and caching layer for an application running on EKS in three Regions.

    Model answer: For caches, use Global Datastore with a primary Region and two secondaries for local reads; writes route to the primary. For sessions that must survive Regional failover with writes in every Region, consider DynamoDB Global Tables or MemoryDB multi-Region capabilities, since Global Datastore secondaries are read-only. Use Pod Identity with IAM authentication in each Region, and Route 53 latency routing to direct users.

#### Troubleshooting Questions

1. After a deployment, the hit ratio falls from 92 percent to 15 percent and remains low for hours. What happened?

    Model answer: The deployment probably changed the key format or serialisation (for example, a new schema version or a different key prefix), so all new keys miss while old keys wait to expire. Plan warm-up, preserve key compatibility, or accept a controlled warm-up with rate-limited recomputation.

2. Writes to a cache fail with OOM errors although the workload is a cache and `Evictions` is zero.

    Model answer: The eviction policy is `volatile-lru` (the default) and keys were written without TTLs, so no key is eligible for eviction. Add TTLs to cache keys or switch a pure cache to `allkeys-lru` or `allkeys-lfu`.

3. One shard shows `EngineCPUUtilization` at 95 percent while others are at 20 percent.

    Model answer: A hot key or a hot hash slot, possibly caused by an overused hash tag. Identify it with `--hotkeys` or application sampling, then apply key replication, replica reads, local caching or removal of the unnecessary hash tag.

---

## 6.2 AWS Database Services

### 6.2.1 Relational Databases with Amazon RDS and Aurora

#### Conceptual Questions

1. Why does RDS Proxy reuse database connections at transaction boundaries rather than at statement boundaries?

    ==Model answer:== Statements within a transaction share locks, snapshots and uncommitted changes held by one database session. Handing the connection to another client mid-transaction would expose or corrupt that state. At a transaction boundary, provided no session-level state exists, the connection is indistinguishable from any other and can be reused safely.

2. Distinguish change data capture from Database Activity Streams.

    ==Model answer:== CDC extracts committed row changes from the transaction log to drive downstream data movement and events. Database Activity Streams publish a record of database activity (sessions and statements) to Kinesis for security monitoring and audit. CDC answers "what data changed"; activity streams answer "who did what".

3. Explain why the expand-contract pattern is necessary for rolling deployments.

    ==Model answer:== During a rolling or blue/green deployment, the old and new application versions run concurrently against the same database. A schema change that only the new version understands breaks the old version. Expand-contract sequences changes so that at every point the schema supports all running versions.

4. Why can scale to zero on Aurora Serverless v2 fail to pause an instance?

    ==Model answer:== Pausing requires the absence of user connections for the configured period. Idle pool connections, RDS Proxy connections, monitoring agents and certain replication or integration features keep connections open and prevent the pause.

#### Scenario Questions

1. A Lambda-based API behind API Gateway receives 3,000 requests per second at peak and connects directly to Aurora PostgreSQL. During a marketing campaign, the API fails with "remaining connection slots are reserved". Propose a design change.

    ==Model answer:== Introduce RDS Proxy with IAM authentication, move client initialisation outside the handler, and set reserved concurrency to bound the maximum. Verify that the driver or ORM does not cause pinning, using `InitQuery` for session settings. For low-query-count functions, consider the Data API. Alarm on `DatabaseConnections` and proxy `ClientConnections`.

2. After a scheduled Secrets Manager rotation, new ECS tasks start successfully but existing tasks begin failing when they open new connections. Explain and fix.

    ==Model answer:== ECS injects secrets as environment variables only at task start. Single-user rotation invalidated the old password, which running tasks still hold. Fixes: switch to alternating users rotation; trigger a new service deployment on rotation via EventBridge; or fetch credentials at runtime through a caching client that refreshes on authentication failure; or put RDS Proxy in front so only the proxy needs the secret.

3. A team wants every pull request to have a realistic database for integration tests. Production is a 3 TB Aurora PostgreSQL cluster containing personal data.

    ==Model answer:== Maintain a masked copy of production in a non-production account (clone, mask, then share or snapshot), and for each pull request create a fast clone of the masked copy as a Serverless v2 cluster with a low maximum ACU and auto-pause. Run migrations and tests, then delete the clone in the pipeline's final stage.

#### Architecture Questions

1. Design the data tier for a payments platform that needs relational transactions, sub-minute RTO, near-real-time fraud analytics and domain events for downstream services.

    ==Model answer:== Aurora PostgreSQL Multi-AZ with a same-size reader at promotion tier 0; RDS Proxy for ECS and Lambda clients with IAM auth; outbox table with CDC via DMS or Debezium to Kinesis and EventBridge; zero-ETL to Redshift for analytics; customer-managed KMS; Database Activity Streams; Database Insights Advanced; Blue/Green for upgrades; expand-contract migrations executed by CodePipeline. For Regional disaster recovery, add Aurora Global Database (Chapter 1.2.3).

2. When would you choose Aurora DSQL over Aurora Global Database for a multi-Region application?

    ==Model answer:== When the application must accept writes in more than one Region with strong consistency and without a failover procedure, and can be designed with short transactions, optimistic concurrency retry and the supported PostgreSQL feature subset. Global Database suits applications that tolerate a single writer Region and need full PostgreSQL or MySQL compatibility, with failover as a managed event.

#### Troubleshooting Questions

1. RDS Proxy shows 2,000 client connections and 1,950 database connections. What is wrong?

    ==Model answer:== Nearly every client is pinned. Examine `DatabaseConnectionsCurrentlySessionPinned` and enable proxy debug logging briefly to find the pinning reason, typically `SET` statements issued by the driver or ORM, temporary tables or prepared statements. Move settings into `InitQuery`, apply `EXCLUDE_VARIABLE_SETS` if safe, and adjust driver configuration.

2. A migration adding a column took the service down for five minutes although it completed in 40 ms in staging. What happened?

    ==Model answer:== The `ALTER TABLE` waited for an exclusive lock behind a long-running query, and all subsequent queries queued behind it, exhausting the connection pool. Set `lock_timeout` for DDL, run migrations when long queries are not active, move reporting to readers or Redshift, and rehearse on a clone with production-like concurrency.

3. Free storage on an RDS for PostgreSQL instance falls steadily although table sizes are stable.

    ==Model answer:== Likely an inactive logical replication slot retaining WAL, often from a stopped DMS task or decommissioned connector. Check `pg_replication_slots` and the replication slot lag metrics, resume or drop the slot, and add alarms.

### 6.2.2 NoSQL Databases with Amazon DynamoDB

#### Conceptual Questions

1. Why does GSI overloading reduce cost as well as index count?

    ==Model answer:== Each GSI receives a write whenever a base item with the index's key attributes is written or its projected attributes change. Fewer GSIs mean fewer index writes and less index storage. Overloading lets one index serve several entity types because each entity populates the generic key attributes only when that index is needed.

2. Explain why optimistic locking suits DynamoDB better than pessimistic locking.

    ==Model answer:== DynamoDB has no row locks or long-lived sessions. Conditional writes are evaluated atomically at the item, so a version check costs nothing extra and holds no resources. Pessimistic locks would require separate lock items, leases and clean-up, adding latency and failure modes. Conflicts in most workloads are rare, so detecting them at write time is efficient.

3. Contrast DynamoDB Streams and Kinesis Data Streams for DynamoDB in ordering and duplication guarantees.

    ==Model answer:== DynamoDB Streams present each modification exactly once and in order per item, with 24-hour retention. Kinesis Data Streams for DynamoDB can contain duplicates and out-of-order records, so consumers must deduplicate and reorder using keys and approximate creation timestamps, in exchange for longer retention and more consumers.

4. What is a sparse index, and why is GSI3 in RideLink sparse?

    ==Model answer:== An index containing only items that have its key attributes. GSI3 keys are set only while a trip is `REQUESTED` and removed on acceptance, so the index contains only the live dispatch queue regardless of total trip volume.

#### Scenario Questions

1. Riders report occasionally being charged twice when the mobile network is poor. The create-trip function writes a trip and calls the payment provider.

    ==Model answer:== Client retries after timeouts produce duplicate invocations. Add a client-generated idempotency key, use Powertools idempotency keyed on it with an expiry longer than the retry horizon, make trip creation conditional, and pass an idempotency key to the payment provider so downstream charging is also idempotent.

2. A support-search feature is implemented with `Scan` and `FilterExpression` over the Trips table and is becoming slow and expensive.

    ==Model answer:== Search is not a key-value access pattern. Enable PITR and streams, create a zero-ETL integration to OpenSearch Service through OpenSearch Ingestion, index the required attributes, and route search queries to OpenSearch. Remove the scan from the request path.

3. RideLink is launching in a new country with a marketing campaign expected to produce ten times the current peak on day one.

    ==Model answer:== Pre-warm warm throughput on the table and all GSIs to the expected peak, confirm with `DescribeTable`, set on-demand maxima above the expected peak as a guardrail, verify sharded keys for zone queues, enable Contributor Insights, and alarm on throttles per index.

#### Architecture Questions

1. Design the event-driven integration so that notification, billing and analytics services react to trip status changes without exceeding DynamoDB Streams reader limits.

    ==Model answer:== One EventBridge Pipe reads the stream, filters `META` modifications, transforms them into a versioned `TripStatusChanged` event and publishes to a custom bus. Each service has its own rule and target (Lambda, SQS or Step Functions) with its own retry and DLQ. Analytics uses zero-ETL or incremental exports rather than the stream. Consumers are idempotent and use the version number to ignore stale events.

2. Design tenant isolation for RideLink such that a compromised tenant-scoped function cannot read another operator's trips.

    ==Model answer:== Tenant-prefixed partition keys on the table and every index a tenant role can access; IAM policies with `ForAllValues:StringLike` on `dynamodb:LeadingKeys` using a principal tag set from the caller's authenticated identity; no tenant access to un-prefixed indexes such as `INV`; resource policies requiring the VPC endpoint; CloudTrail data events for audit; and optionally separate tables per premium tenant.

#### Troubleshooting Questions

1. `IteratorAge` on the receipts function rises steadily to several hours, and one shard shows repeated errors.

    ==Model answer:== A poison record is blocking the shard with unbounded retries. Enable bisection, bound retries and record age, return partial batch responses, and configure an on-failure destination. Fix the handler to reject the invalid record cleanly, and replay failures from the destination metadata if needed. Act before 24 hours to avoid losing records.

2. After adding a fourth Lambda mapping to the same DynamoDB stream, all consumers slow down.

    ==Model answer:== DynamoDB Streams support few concurrent readers per shard; additional mappings cause read throttling. Consolidate to one consumer path, such as a pipe to EventBridge with rules for fan-out, or enable Kinesis Data Streams for DynamoDB with enhanced fan-out.

3. A newly created GSI for a new access pattern shows `Backfilling` for hours and base-table writes begin throttling.

    ==Model answer:== The index backfill and ongoing writes exceed the index's capacity or warm throughput, and index back-pressure throttles the base table. Pre-warm the new GSI (or raise its provisioned capacity), consider creating it during low traffic, and monitor `OnlineIndexPercentageProgress` and index throttling metrics.

### 6.2.3 Graph Databases with Amazon Neptune

#### Conceptual Questions

!!! question "Why do relational joins become expensive for deep traversals, and how does a graph engine avoid this?"
    Each hop in a relational query is a join that probes a global index whose cost depends on the size of the whole table, and intermediate results multiply with fan-out. Variable-depth queries need recursive CTEs that optimisers estimate poorly. A graph engine stores adjacency so that expanding a vertex's neighbours is a localised lookup, making traversal cost proportional to the neighbourhood visited rather than to the total dataset size. Neptune achieves this with indexes over edge records rather than physical pointers, but the architectural effect is the same.

!!! question "Distinguish the property graph and RDF models and state when each is preferable."
    A property graph has vertices and edges with labels and key-value properties on both, and is queried with Gremlin or openCypher; it suits application-centric traversal workloads. RDF represents data as subject-predicate-object triples identified by global IRIs, uses ontologies and is queried with SPARQL; it suits standards-based data integration and knowledge graphs across organisations. In Neptune the two are stored and queried separately.

!!! question "Explain the difference between Neptune Database and Neptune Analytics."
    Neptune Database is a durable OLTP cluster with a writer, replicas and shared storage, optimised for many low-latency concurrent traversals and writes. Neptune Analytics loads a graph into memory for fast whole-graph algorithms and vector similarity search, supports openCypher, and is used as an analytical copy rather than a system of record.

!!! question "What is a supernode and why does it matter?"
    A supernode is a vertex with an extremely large number of edges. Traversals through it explode in fan-out, writes to it cause concurrency conflicts, and it can make unrelated entities appear connected. Mitigations include demoting it to a property, bucketing, filtering edges before expansion and bounding fan-out.

#### Scenario Questions

!!! question "A startup's recommendation API on Lambda uses Neptune. P99 latency is acceptable, but every morning it spikes when a data science team runs PageRank on the same cluster. What should change?"
    Move the algorithm workload off the OLTP cluster. Export or snapshot the graph into Neptune Analytics, run PageRank there, and write the resulting scores back to Neptune Database as properties through the bulk loader. If analytics must stay on Neptune Database temporarily, isolate it with a custom endpoint pointing at dedicated replicas.

!!! question "An event consumer on ECS writing to Neptune intermittently logs ConcurrentModificationException and some edges are missing. Explain and fix."
    Concurrent transactions are modifying the same vertices, likely hot vertices such as a popular device or merchant, and failed writes are not retried. Implement retries with exponential backoff and jitter, make writes idempotent with deterministic IDs and `MERGE` or `mergeV`, reduce contention by partitioning SQS message groups by vertex ID, and consider bucketing high-degree vertices.

!!! question "A team wants to replace their entire Aurora order database with Neptune because orders relate to customers and products. Advise."
    Advise against. Order processing is a transactional, tabular workload with shallow relationships where Aurora excels. Keep orders in Aurora, publish order events, and build a Neptune graph as a read model for recommendations or fraud analysis if multi-hop queries are needed.

#### Architecture Questions

!!! question "Design a highly available, secure architecture for a fraud-scoring microservice on EKS that queries Neptune."
    Deploy a Neptune cluster in private subnets across three AZs with a writer and at least two replicas, KMS encryption, IAM authentication, audit logs and PITR. The scoring service runs on EKS with EKS Pod Identity mapping its service account to a role permitting only `neptune-db:ReadDataViaQuery`. Pods reach the reader endpoint on 8182 through security groups. A separate ingestion service with write permissions consumes transaction events from EventBridge or SQS and performs idempotent upserts. Queries are bounded with timeouts; a circuit breaker falls back to a rules engine. Neptune Streams feeds OpenSearch for analyst search, and a nightly Step Functions workflow refreshes a Neptune Analytics graph for community detection. Everything is defined in Terraform or CDK and deployed through a pipeline.

!!! question "How would you keep a full-text search index consistent with a Neptune graph?"
    Enable Neptune Streams and deploy a poller (for example the AWS-provided Lambda-based framework) that reads change records in order, checkpoints its position in DynamoDB, and indexes vertices and properties into OpenSearch. Consumers must be idempotent, handle `REMOVE` operations, and alarm on lag. Retention must exceed the maximum expected consumer outage.

#### Troubleshooting Questions

!!! question "A Lambda function times out when connecting to Neptune. What do you check?"
    Confirm the function is attached to the VPC and subnets that can route to Neptune; that the Neptune security group allows TCP 8182 from the function's security group; that the endpoint and port are correct; that IAM authentication is not rejecting the request (403 rather than timeout); and that the function's timeout exceeds connection and query timeouts. For WebSockets, check for stale connections after freeze and thaw.

!!! question "The bulk loader returns S3_ACCESS_DENIED or cannot reach S3. What is wrong?"
    Either the IAM role is not attached to the cluster, the role lacks `s3:GetObject` and `s3:ListBucket` on the bucket, the `iamRoleArn` in the request does not match the attached role, the bucket is in a different Region than stated, or the VPC lacks an S3 gateway endpoint for the Neptune subnets.

!!! question "Queries return 403 AccessDeniedException after enabling IAM authentication."
    Requests are not signed, are signed with the wrong service name (must be `neptune-db`) or Region, the clock is skewed, the policy's resource ARN uses the cluster name instead of the cluster resource ID, or the role lacks the specific data-plane action required by the query (read, write or delete).

### 6.2.4 Data Warehousing with Amazon Redshift

#### Conceptual Questions

!!! question "Why does columnar storage accelerate analytical queries but slow down single-row updates?"
    Analytical queries read a few columns across many rows; a columnar layout reads only those columns' blocks, which are also highly compressible and support block skipping through zone maps. A single-row update, however, touches one block per column, and Redshift's immutable blocks require writing new versions and later vacuuming, which makes row-at-a-time DML expensive.

!!! question "Explain the roles of the leader node, compute nodes and slices."
    The leader node accepts connections, parses and optimises SQL, compiles code segments, distributes them and aggregates results. Compute nodes execute the segments. Each compute node is divided into slices, each holding a portion of every table and processing it in parallel, so the slice is the unit of parallelism.

!!! question "Compare KEY, ALL, EVEN and AUTO distribution styles."
    KEY places rows with equal key values on the same slice, enabling collocated joins on that key but risking skew. ALL copies a small table to every node so joins never redistribute it. EVEN spreads rows round-robin for balanced storage when no join key dominates. AUTO lets Redshift choose and adapt, typically starting with ALL for small tables and moving to EVEN or KEY as tables grow.

!!! question "What is the difference between a namespace and a workgroup in Redshift Serverless?"
    A namespace contains the databases, schemas, users, storage, encryption configuration and snapshots. A workgroup contains the compute capacity (base and maximum RPUs), networking and limits. Separating them allows compute to be configured and scaled independently of data.

#### Scenario Questions

!!! question "The finance team's dashboards slow to a crawl every night between 01:00 and 03:00 when ETL runs. What would you recommend?"
    Isolate workloads. On provisioned clusters, configure automatic WLM with a high-priority BI queue, enable concurrency scaling and SQA for that queue, and assign ETL to a lower-priority queue. Better still, run ETL on a producer workgroup and dashboards on a consumer workgroup using data sharing, so each has its own compute. Also check that dashboards use materialized views.

!!! question "A developer proposes connecting QuickSight directly to each microservice's Aurora database to build a cross-service revenue dashboard. How do you respond?"
    Reject the design: it couples analytics to service internals, loads production databases and requires cross-database joins. Instead, create zero-ETL integrations from each Aurora cluster into Redshift, build staging and presentation models, and point QuickSight at Redshift, optionally with SPICE for high concurrency.

!!! question "A Serverless workgroup's monthly bill tripled after a new analyst joined. How do you investigate and control it?"
    Examine `SYS_QUERY_HISTORY` and CloudWatch `ComputeSeconds` to find expensive queries, users and times; look for unfiltered Spectrum scans, `SELECT *` on large tables, or repeated heavy queries. Set a maximum RPU and usage limits, add query limits such as maximum execution time, build materialized views for repeated queries, and provide training on efficient queries.

#### Architecture Questions

!!! question "Design a near real-time analytics platform for an e-commerce microservice system on EKS whose services use Aurora PostgreSQL and DynamoDB and emit clickstream to Kinesis."
    Create zero-ETL integrations from each Aurora cluster and DynamoDB table into a producer Redshift Serverless namespace, and streaming ingestion materialized views over the Kinesis stream. Build staging views and a presentation star schema using scheduled ELT orchestrated by Step Functions with the Data API. Share presentation schemas through data sharing with a BI workgroup used by QuickSight, and a data science workgroup. Archive history with UNLOAD to partitioned Parquet in S3 and query it through Spectrum. Secure with private subnets, KMS, IAM roles, RLS and masking; monitor integration lag and usage limits; define everything in IaC.

!!! question "How would you serve analytical results in a customer-facing mobile app with thousands of requests per second?"
    Do not query Redshift per request. Compute aggregates in Redshift on a schedule or incrementally, export them through UNLOAD or a Lambda exporter into DynamoDB (or ElastiCache), and have the app's API read from DynamoDB. Redshift remains the computation engine; DynamoDB provides low-latency, high-concurrency serving.

#### Troubleshooting Questions

!!! question "A join between two large tables is slow and EXPLAIN shows DS_BCAST_INNER. What does this mean and how do you fix it?"
    The inner table is being broadcast to every node because the tables are not collocated on the join key. If both tables are large and frequently joined on the same column, distribute both on that column (KEY) or let AUTO optimise; if the inner table is small, use ALL distribution. Also verify statistics are current with ANALYZE.

!!! question "COPY fails with an S3 access error from a warehouse with enhanced VPC routing enabled."
    Check that the IAM role attached to the namespace or cluster has `s3:GetObject` and `s3:ListBucket` on the prefix and is referenced correctly (`IAM_ROLE default` requires a default role). With enhanced VPC routing, traffic must reach S3 through the VPC, so verify there is an S3 gateway endpoint (or NAT path) in the route tables of the warehouse subnets and that the endpoint policy and bucket policy allow access.

!!! question "Queries have become slower over months even though data volume has grown only modestly."
    Investigate `SVV_TABLE_INFO` for a high `unsorted` percentage, stale statistics and skew; check for many deleted rows awaiting vacuum; examine WLM queue wait times for concurrency growth; and review whether new queries lack supporting sort keys or materialized views. Run VACUUM and ANALYZE where automatic maintenance lags, and apply Advisor recommendations.

---

## 6.3 Messaging and Event Streaming

### 6.3.1 Message Queues with Amazon SQS

#### Conceptual Questions

!!! question "Why does SQS use a visibility timeout rather than deleting a message when it is received?"
    Deleting on receive would give at-most-once delivery: if the consumer crashed after receiving, the message would be lost. The visibility timeout hides the message temporarily and requires an explicit `DeleteMessage` after successful processing. If no acknowledgement arrives in time, the message becomes visible again and another consumer retries it. This provides reliable processing without distributed transactions, at the cost of possible duplicates, which is why consumers must be idempotent.

!!! question "Explain why a standard queue can deliver a message more than once and why an individual short poll can return no messages even though the queue is not empty."
    SQS stores each message redundantly on multiple hosts across Availability Zones. If one host holding a copy is unavailable when the message is deleted, that copy may later be delivered again, so delivery is at least once. A short poll queries only a sampled subset of hosts, so it can miss messages stored on hosts it did not query. Long polling queries all hosts and waits for messages, removing false empty responses.

!!! question "What exactly does exactly-once processing mean for a FIFO queue, and what does it not mean?"
    It means that producer duplicates with the same deduplication ID sent within the 5-minute deduplication interval are accepted but not delivered again, and that a message is not delivered to another consumer while it is in flight. It does not mean that the consumer's side effects happen once: if a consumer processes a message and fails before deleting it, the message is delivered again after the visibility timeout. Consumer idempotency is still required.

!!! question "Contrast a delay queue, a message timer and the visibility timeout."
    A delay queue hides every newly sent message for a fixed period (up to 15 minutes) before its first delivery. A message timer does the same for one individual message on a standard queue and overrides the queue delay. The visibility timeout hides a message after it has been received, to give the consumer time to process and delete it. Delay applies before the first receive; visibility applies after each receive.

!!! question "Why is ApproximateAgeOfOldestMessage usually a better alarm metric than ApproximateNumberOfMessagesVisible?"
    Queue depth must be interpreted relative to processing rate: 10,000 messages may be drained in two seconds by a large fleet, while 50 may indicate a stuck consumer. The age of the oldest message directly measures how long work has waited, which corresponds to user-visible latency and to the risk of reaching the retention limit.

#### Scenario Questions

!!! question "A ticketing platform expects a burst of 50,000 purchase requests in the first minute of a concert sale. The payment provider accepts at most 200 requests per second. Design the processing tier."
    Accept purchases at the API tier (API Gateway direct integration or an ECS service) and enqueue them to an SQS standard queue, returning "202 Accepted" with a reservation ID. A Lambda consumer with event source mapping maximum concurrency sized so that throughput stays below 200 requests per second (or an ECS worker service with a fixed maximum task count) calls the payment provider. The queue levels the load; 50,000 requests drain in roughly 250 seconds. Consumers are idempotent using the reservation ID; failed payments go to a DLQ after five attempts; users are notified asynchronously. Retention of 4 days comfortably exceeds the drain time.

!!! question "A bank must process account transactions strictly in order per account, and duplicate submissions from a retried mobile app must never be applied twice. Transaction volume is 20,000 per second across two million accounts. Which queue configuration do you choose?"
    A FIFO queue with the account ID as message group ID and the client-generated transaction ID as the message deduplication ID, in high-throughput mode (`DeduplicationScope = messageGroup`, `FifoThroughputLimit = perMessageGroupId`). Two million groups give ample parallelism. Consumers are idempotent (for example, a conditional write on transaction ID) because FIFO deduplication covers producer duplicates only within five minutes. A FIFO DLQ unblocks groups affected by poison messages. SSE-KMS with a customer managed key satisfies key-control requirements. Verify the Regional high-throughput quota.

!!! question "A SaaS company runs a shared export queue for all tenants. When a large tenant requests 100,000 exports, small tenants wait hours. What can be done without redesigning consumers?"
    Set the tenant ID as `MessageGroupId` on messages sent to the standard queue to use SQS fair queues, so that SQS prioritises other tenants' messages while one tenant has a large backlog. Alternatives are separate queues per tenant tier with dedicated consumer capacity (bulkhead), or per-tenant rate limiting at the producer.

#### Architecture Questions

!!! question "Compare scaling SQS consumers on Lambda, ECS and EKS."
    Lambda: the event source mapping polls and scales automatically; the architect controls batch size, batching window and maximum concurrency, and must follow the six-times visibility rule. Best for short, spiky, event-driven work up to the 15-minute Lambda limit. ECS: a worker service runs receive loops; scale with Application Auto Scaling target tracking on backlog per task using metric math; suitable for long-running jobs, custom runtimes and Fargate Spot. EKS: pods run receive loops; KEDA's `aws-sqs-queue` scaler drives the HPA, including scale to zero, and Karpenter adds nodes; suitable when the organisation standardises on Kubernetes or needs GPUs. In all three, IAM is per workload (execution role, task role, Pod Identity or IRSA).

!!! question "Why would you place an SNS topic in front of several SQS queues instead of letting several services consume one queue?"
    Consumers of one queue compete: each message goes to only one service, so different services cannot all see every event. SNS delivers a copy to each subscribed queue; each service then has its own buffer, retry behaviour, visibility timeout, DLQ and scaling, and a failure in one consumer does not affect the others. Filter policies can deliver only relevant messages to each queue (the Amazon SNS part of this section).

!!! question "Design a secure, private integration between an EKS microservice in private subnets and an SQS queue encrypted with a customer managed key."
    Create an interface VPC endpoint for SQS in the private subnets with a security group allowing HTTPS from the node or pod security groups, and an endpoint policy restricting access to the relevant queue ARNs. Use a KMS VPC endpoint too if pods call KMS directly. Associate the service account with an IAM role using EKS Pod Identity granting only receive, delete, change visibility and get attributes on the queue and `kms:Decrypt` on the key. The queue policy denies requests not coming through the endpoint (`aws:SourceVpce`) and denies non-TLS. The key policy allows the role to decrypt. CloudTrail data events provide audit.

#### Troubleshooting Questions

!!! question "Messages are processed successfully according to the logs, yet they keep appearing in the DLQ. What is the likely cause?"
    The visibility timeout is shorter than the processing time (or, for Lambda, shorter than six times the function timeout under throttling). Messages become visible again during processing, are received by another consumer and the receive count increases. When the first consumer tries to delete with its now-stale receipt handle, the deletion may not take effect, and eventually the receive count exceeds `maxReceiveCount`. Increase the visibility timeout or add heartbeats, and check for Lambda throttling due to reserved concurrency.

!!! question "An SNS topic publishes successfully, but nothing arrives in a subscribed SQS queue that uses SSE-KMS. Where do you look?"
    First the queue policy: it must allow `sns.amazonaws.com` to call `sqs:SendMessage` with an `aws:SourceArn` condition for the topic. Second the encryption key: if the queue uses the AWS managed key `aws/sqs`, SNS cannot use it; use a customer managed key whose key policy allows `sns.amazonaws.com` to call `kms:GenerateDataKey` and `kms:Decrypt`. Check the SNS `NumberOfNotificationsFailed` metric and SNS delivery status logs.

!!! question "Consumers appear healthy and CPU is low, but no messages are being processed and ReceiveMessage returns OverLimit errors. What happened?"
    The in-flight message quota has been reached. Consumers are receiving messages and not deleting them, perhaps because an exception is swallowed after receive, or visibility timeouts are very long. Fix the acknowledgement bug, reduce visibility timeouts to realistic values, and alarm on `ApproximateNumberOfMessagesNotVisible`.

!!! question "One customer's orders in a FIFO queue have not been processed for an hour, while other customers' orders flow normally. Why?"
    A message in that customer's message group is failing repeatedly and blocking the group, because later messages in a group are not delivered while an earlier one is in flight or returning. Either there is no redrive policy, or `maxReceiveCount` combined with a long visibility timeout is keeping it in the source queue. Configure a FIFO DLQ with a moderate `maxReceiveCount`, investigate the poison message, and alarm on DLQ depth.

### 6.3.2 Pub/Sub Messaging with Amazon SNS

#### Conceptual Questions

!!! question "Explain the difference between publish/subscribe and point-to-point messaging using SNS and SQS as examples."
    In point-to-point messaging (SQS), each message is consumed by exactly one of possibly many competing consumers, which pull messages at their own pace from a durable queue. In publish/subscribe (SNS), each message is pushed to every subscriber of a topic, so several independent systems receive their own copy. SQS stores messages for up to 14 days; a standard SNS topic does not store messages for later readers.

!!! question "Why is the SNS-to-SQS fan-out pattern preferred over subscribing microservices directly to SNS through HTTPS?"
    SNS pushes messages and gives up after its retry policy, so an HTTPS consumer that is down or overloaded may lose messages or be overwhelmed. Subscribing an SQS queue per service gives each service a durable buffer, consumer-controlled pace (back-pressure), independent visibility timeouts, retry counts and DLQs, and a queue-depth signal for autoscaling. The publisher is unaffected by any consumer's condition.

!!! question "What does raw message delivery change, and when would you keep it disabled?"
    With raw delivery, the SQS body or HTTP body is exactly the published message, and SNS message attributes become SQS message attributes. Without it, the body is a JSON envelope containing metadata (topic ARN, message ID, timestamp, signature) and the message as a string. Keep it disabled when consumers need the topic ARN (for example one queue subscribed to several topics), the signature for verification, or the envelope metadata.

!!! question "How do SNS retry policies differ between SQS, Lambda and HTTPS subscriptions?"
    For AWS-managed endpoints (SQS, Lambda, Firehose), SNS uses a fixed, very persistent retry policy that applies mainly when the target service is unavailable or throttling. For HTTP/S endpoints, a configurable delivery policy defines retries, delays, backoff function and throttling. Email, SMS and push use a fixed policy. For Lambda, once the Lambda service accepts the asynchronous invocation, SNS considers delivery complete; function errors are retried by Lambda's own asynchronous retry settings.

!!! question "What guarantees does an SNS FIFO topic provide, and what are its constraints?"
    Messages with the same message group ID are delivered to each subscribed SQS FIFO queue in the order published, and messages with a repeated deduplication ID within 5 minutes are not delivered again. FIFO topics can archive messages for replay. Constraints: only SQS subscriptions, far fewer subscriptions per topic (100), lower default throughput than standard topics (raised by high-throughput mode with high group cardinality), and consumers must still be idempotent.

#### Scenario Questions

!!! question "A video platform stores uploads in S3. Four teams need to react to each upload: thumbnails (images only), transcoding (videos only), virus scanning (all files) and search indexing (all files). S3 allows only one notification configuration per event type and prefix. Design the integration."
    Configure the bucket to publish `s3:ObjectCreated:*` to an SNS topic (topic policy allowing `s3.amazonaws.com` with `aws:SourceArn` and `aws:SourceAccount`). Subscribe four SQS queues with raw delivery; use payload-based filter policies on the thumbnail queue (key suffix `.jpg`, `.png`) and the transcoding queue (suffix `.mp4`, `.mov`), and no filter for the scanning and indexing queues. Each team consumes its queue with its own compute (Lambda, ECS or EKS with KEDA), DLQ and alarms. If the topic or queues use a customer managed key, the key policy must allow S3 and SNS. EventBridge is a valid alternative if richer routing is required.

!!! question "Operations report that CloudWatch alarms change to ALARM, but nobody receives notifications, since the security team enabled encryption on the alerts topic last week. What happened and how do you fix it?"
    The topic was probably encrypted with the AWS managed key `aws/sns`, whose key policy cannot be changed to allow `cloudwatch.amazonaws.com`. CloudWatch cannot generate data keys to publish, so notifications fail silently while the alarm state changes. Create a customer managed KMS key with a key policy allowing `cloudwatch.amazonaws.com` to use `kms:GenerateDataKey*` and `kms:Decrypt` (scoped by `aws:SourceAccount`), set it on the topic, and test notifications end to end. Check the alarm history for action failures.

!!! question "A payment ledger service, an audit service and a reconciliation service must each apply account transactions in the same order. Last month a bug in reconciliation corrupted three days of data. How would you design the messaging to support ordering and recovery?"
    Publish transactions to an SNS FIFO topic with the account ID as message group ID and the transaction ID as deduplication ID. Subscribe an SQS FIFO queue per service, each with a FIFO DLQ. Enable the topic archive policy with a retention period longer than the expected recovery window. After fixing the bug, reset reconciliation's state to the point before the corruption and set a replay policy on its subscription starting at that timestamp. Consumers are idempotent so that replayed and already processed messages do not cause double application. Use high-throughput mode if volume requires it.

#### Architecture Questions

!!! question "Compare SNS to Lambda and SNS to SQS to Lambda for processing order events that write to an Aurora database with a limited connection pool."
    SNS to Lambda invokes one function per message asynchronously; concurrency can rise quickly and overwhelm database connections unless reserved concurrency is used, and function errors are handled by Lambda's async retries. SNS to SQS to Lambda buffers messages, allows batching, and uses event source mapping maximum concurrency to cap parallelism precisely, with visibility-timeout retries, partial batch responses and a queue DLQ. For a database with limited connections, the second design (possibly with RDS Proxy, Chapter 1.2.3) is preferred.

!!! question "When would you choose EventBridge instead of SNS for inter-service events in a microservice platform?"
    Choose EventBridge when routing depends on rich content patterns across many event types, when events come from AWS services or SaaS partners, when schema discovery and a registry are valuable, when archive and replay are needed for standard (unordered) events, when input transformation is required, or when events must be routed across accounts through bus policies. Choose SNS when very high throughput and low latency fan-out, FIFO ordering, very large numbers of subscribers, or human notifications (email, SMS, push) are required. Many platforms use both.

!!! question "Design a cross-account event distribution in which a central platform account publishes customer events that product teams in five accounts consume privately and securely."
    Create a standard topic `customer-events` in the platform account, encrypted with a customer managed key. The topic policy allows the five account principals to `sns:Subscribe` only with protocol `sqs`. Each product account creates its own SQS queue encrypted with its own customer managed key, whose key policy allows `sns.amazonaws.com`, and a queue policy allowing `sns.amazonaws.com` with `aws:SourceArn` of the central topic. The queue owners subscribe their queues (so no confirmation is needed), with filter policies and raw delivery. Consumers run on ECS or EKS with per-workload roles and VPC endpoints. Monitoring: `NumberOfNotificationsFailed` in the platform account, queue age and DLQ alarms in each product account.

#### Troubleshooting Questions

!!! question "A new SQS subscription shows as confirmed, but the queue receives no messages. Publishing succeeds. List the checks in order."
    First, the queue policy: it must allow `sns.amazonaws.com` to call `sqs:SendMessage` on the queue with `aws:SourceArn` equal to the topic ARN. Second, encryption: if the queue uses SSE-KMS, the key must be customer managed and allow SNS to use `kms:GenerateDataKey` and `kms:Decrypt`. Third, the filter policy: check that published messages carry the attributes (or body fields) the policy expects, and look at `NumberOfNotificationsFilteredOut`. Fourth, remember that filter policy changes can take minutes to propagate. Finally, check `NumberOfNotificationsFailed` and enable delivery status logging for SQS to see the error.

!!! question "An HTTPS partner endpoint was down for eight hours. Afterwards, the partner reports missing notifications. Why, and how do you prevent it?"
    HTTP/S delivery policies retry for a bounded period; after the policy is exhausted, SNS discards the message unless the subscription has a DLQ. Add a subscription DLQ, alarm on `NumberOfNotificationsRedrivenToDlq`, and redeliver from the DLQ after recovery. For stronger guarantees, deliver to an SQS queue and have your own worker call the partner with a circuit breaker and backoff, so messages wait up to 14 days.

!!! question "Consumers of a fan-out queue occasionally apply the same order twice. The team believes SNS and SQS should prevent this. Explain and fix."
    Standard SNS topics and standard SQS queues both provide at-least-once delivery, so duplicates can arise at each layer, and message IDs differ between copies. The consumer must be idempotent using a business key such as `orderId` and `eventId`, for example with a DynamoDB conditional write or a unique constraint (Chapter 1.3.3). If strict deduplication and ordering are required, use a FIFO topic with FIFO queues, but keep idempotency because consumer failures can still cause redelivery.

!!! question "After enabling payload-based filtering on a subscription, all messages are filtered out. What might be wrong?"
    Common causes: the message body is not valid JSON; the filter's nesting does not match the body structure (for example a filter on `total` when the body has `detail.total`); the publisher places the value in message attributes rather than the body; numeric values are published as strings, so numeric matching fails; or the `FilterPolicyScope` was changed but the policy was written for attributes. Check the `NumberOfNotificationsFilteredOut-InvalidMessageBody` metric and test the policy with sample messages.

### 6.3.3 Stream Processing with Amazon Kinesis

#### Conceptual Questions

!!! question "Why does reading a record from a Kinesis stream not delete it, and what architectural capabilities does this enable?"

    A stream is a log whose retention is based on time, not consumption. Each consumer stores its own position (a sequence number per shard), so reads are non-destructive. This enables multiple independent consumers with separate failure domains, replay after a consumer bug, onboarding new consumers that process history, and reprocessing through a corrected pipeline (the kappa architecture). A queue cannot offer these because delivery to one consumer and deletion are its purpose.

!!! question "Explain how a partition key determines the shard for a record, and what guarantees follow."

    Kinesis computes the MD5 hash of the partition key as a 128-bit integer and routes the record to the shard whose hash key range contains the value. All records with the same key therefore go to the same shard and are read in write order. There is no ordering across shards, and load distribution depends on the distribution of keys.

!!! question "Distinguish event time from processing time, and explain the role of a watermark."

    Event time is when the event occurred, carried in the payload; processing time is when the consumer runs. Aggregating by processing time misattributes delayed events. A watermark is the processor's estimate that no earlier events will arrive; when it passes a window's end the window is emitted. A larger allowed out-of-orderness improves correctness but increases latency, and events after the watermark are late data that must be dropped, side-output or used to update results.

!!! question "Why is it inaccurate to say that Kinesis provides exactly-once delivery?"

    Delivery is at-least-once: producer retries after lost acknowledgements and consumer restarts from the last checkpoint both cause duplicates. Exactly-once results require idempotent processing (for example conditional writes keyed on event ID), or Flink's checkpointing for internal state combined with idempotent or transactional sinks.

!!! question "Compare shared-throughput consumers with enhanced fan-out."

    Shared consumers poll with `GetRecords` and share 2 MB/s and 5 calls per second per shard, so each additional consumer reduces the others' budget and adds latency (around 200 ms or more). Enhanced fan-out registers a consumer that receives a dedicated 2 MB/s per shard via HTTP/2 push with around 70 ms latency, at extra cost. EFO is chosen for many consumers, latency-sensitive consumers, or isolation between consumers.

#### Scenario Questions

!!! question "A telemetry stream has 20 shards, but CloudWatch shows `WriteProvisionedThroughputExceeded` while most shards are nearly idle. The team proposes doubling to 40 shards. Evaluate the proposal."

    The symptom indicates key skew, not insufficient aggregate capacity. Enhanced shard-level metrics will likely show one or two hot shards. If a single key exceeds 1 MB/s or 1,000 records/s, doubling shards does not help because that key still maps to one shard. The fix is to redesign the key: use device ID rather than site ID, or salt the hot key (for example `siteId#n`) if strict per-site ordering is not required. Splitting the hot shard helps only if several keys share it.

!!! question "A Lambda consumer's iterator age has increased linearly for six hours on one shard, while other shards are healthy. Logs show the same batch failing repeatedly. What happened and how do you fix it now and permanently?"

    A poison record is blocking the shard: the ESM retries the same batch, and with default infinite retries it will block until the record expires. Immediately, update the ESM to set `MaximumRetryAttempts`, `BisectBatchOnFunctionError` and an on-failure destination so the bad record is isolated and skipped. Permanently, add input validation, `ReportBatchItemFailures`, a `MaximumRecordAgeInSeconds`, an iterator-age alarm, and a reprocessing procedure for DLQ entries.

!!! question "Analysts complain that Athena queries over the Firehose-delivered data lake are slow and expensive. Firehose uses a 1 MiB buffer, 60-second interval, JSON output and dynamic partitioning by `userId`. What would you change?"

    Partitioning by `userId` creates an enormous number of tiny objects; combined with small buffers and JSON, this maximises file count and scan volume. Partition by bounded, query-relevant fields such as date and event type, enable Parquet conversion (requiring at least 64 MiB buffers), increase buffer interval, and if freshness is critical, consider Iceberg tables with compaction or a separate low-latency path.

!!! question "Six teams want to consume the same order-event stream: two need sub-second latency, the others are batch-tolerant. How do you design consumption?"

    Six shared consumers would exhaust the five-calls-per-second budget. Register EFO consumers for the two latency-sensitive teams (and possibly others that need isolation), let Firehose deliver to S3 for batch-tolerant consumers who can read from the lake, and give each consumer its own application name, IAM role and alarms.

!!! question "A mobile game launches next week and expects ten times normal traffic within minutes of launch. The stream runs in on-demand mode. What risk exists and how do you mitigate it?"

    On-demand scales relative to the recent peak (roughly double), so an immediate tenfold jump can throttle. Mitigate by pre-provisioning: switch to provisioned mode with sufficient shards before launch (respecting the limit on mode switches per day), or raise baseline capacity using current on-demand options, ensure producers retry failed entries with backoff, and alarm on write throttling.

#### Architecture Questions

!!! question "Design a real-time fraud detection pipeline for card transactions that also feeds the data warehouse. Justify each component."

    API or payment services on ECS write transactions to Kinesis Data Streams keyed by card ID, giving per-card ordering. A Managed Flink application computes per-card windowed features (spend in the last 10 minutes, distinct merchants per hour) using event time and scores or calls a model; alerts go to a derived stream consumed by an EFO Lambda that publishes to EventBridge for routing to case management and SNS notifications. Firehose delivers raw transactions as Parquet to S3 and Redshift. KMS encryption, VPC endpoints, least-privilege roles, 7-day retention, iterator-age alarms and idempotent sinks complete the design.

!!! question "When would you choose Amazon MSK over Kinesis Data Streams for a new organisation-wide streaming platform?"

    When the organisation already has Kafka skills, applications and connectors; needs Kafka Connect, Kafka Streams or transactional exactly-once producers; requires portability to other environments; or has very large sustained throughput where cluster pricing and tiered storage are cheaper. Kinesis is preferable for AWS-native teams valuing minimal operations and deep Lambda and Firehose integration.

!!! question "Explain how you would migrate from a lambda architecture to a kappa architecture on AWS."

    Replace the separate batch and speed code paths with a single Flink application. Keep Firehose landing raw events in S3 as the permanent record. For reprocessing, either rely on stream retention for short windows or replay historical data from S3 into a reprocessing stream (or use Flink's ability to read bounded sources) with the corrected job writing to a new output version, then switch readers. Validate output parity before decommissioning the batch layer.

!!! question "How should a KCL consumer running on EKS be scaled, and what is the upper bound on useful replicas?"

    Scale with KEDA's Kinesis scaler or a custom metric based on shard count and iterator age. Each shard lease is held by one worker, so replicas beyond the shard count are idle. Use EKS Pod Identity for Kinesis, DynamoDB and CloudWatch permissions, spread replicas across AZs, and handle SIGTERM by checkpointing before shutdown.

#### Troubleshooting Questions

!!! question "A producer reports success but downstream counts are consistently lower than expected during peak hours."

    The producer likely ignores `FailedRecordCount` in `PutRecords` responses, dropping throttled entries. Confirm with `PutRecords.FailedRecords` and `WriteProvisionedThroughputExceeded` metrics. Fix by retrying only failed entries with backoff, emitting a metric for exhausted retries, and adding capacity or fixing key skew.

!!! question "After enabling a customer-managed KMS key on a stream, the Lambda consumer stops processing and iterator age rises."

    The Lambda execution role lacks `kms:Decrypt` on the key, or the key policy does not allow the role. Grant decrypt permission in both the key policy and the role policy. Producers similarly need `kms:GenerateDataKey`.

!!! question "After a resharding operation, a custom consumer processes some records for the same key out of order."

    The consumer read child shards before finishing the parent. Records for a key written before the split are in the parent; those after are in the child. Use the KCL or Lambda, which respect shard lineage, or implement parent-first reading using `ParentShardId`.

!!! question "A Flink application's window results stopped appearing although records are still arriving on most shards."

    An idle shard is holding back the global watermark, so no windows close. Configure source idleness so that quiet shards do not stall watermarks, or check for a bad timestamp far in the past or future distorting watermark generation. Monitor watermark lag and `millisBehindLatest`.

### 6.3.4 Event Routing with Amazon EventBridge

#### Conceptual Questions

!!! question "Why is an event mesh described as a platform capability rather than an application feature?"

    Because routing crosses team and account boundaries. If every application implements its own routing, the organisation accumulates pairwise policies, inconsistent schemas and no shared view of who consumes what. A mesh treats buses, links, policies, schemas and catalogue as shared infrastructure with owners, governed in IaC and used by all teams.

!!! question "Distinguish public, private and operational events, and explain why the distinction reduces coupling."

    Private events are domain-internal and may change freely; public events are versioned contracts promoted beyond the domain; operational events are defined by AWS and describe infrastructure. Other teams may depend only on public events, so a domain can refactor internally without breaking consumers, just as a microservice hides its internals behind a public API.

!!! question "Why must consumers of a Scheduler timeout event check current state before acting?"

    Because the timeout can fire concurrently with, or just after, the completing event (a race), and because delivery is at-least-once. Acting blindly could cancel a paid order. The consumer treats the timeout as a prompt to check state and acts only if the process is still incomplete.

!!! question "Explain why an SQS queue is usually placed between EventBridge and a containerised consumer."

    EventBridge pushes events and cannot deliver to long-running containers directly with backpressure. A queue buffers bursts, lets the service consume at its own pace, provides per-message retries and a DLQ, isolates the consumer as a bulkhead, and supplies a scaling signal (queue depth) for ECS autoscaling or KEDA.

!!! question "What is the difference between global endpoints and cross-Region rules?"

    Global endpoints provide ingestion failover for producers between a primary and secondary Region using a health check, with optional replication. Cross-Region rules route selected events to a bus in another Region, for example to aggregate security findings. Neither alone makes consumers multi-Region; consumers and rules must also be deployed in the secondary Region.

#### Scenario Questions

!!! question "A company has 40 accounts. Security wants every GuardDuty and Config event in one account within one minute and automated containment for high-severity findings. Design the routing."

    Use GuardDuty's delegated administrator for native finding aggregation where available, and deploy by service-managed StackSets a forwarding rule on each account's default bus in every enabled Region for Config and other sources, targeting a `security-ops` bus in the security account whose policy admits the organisation. On that bus, route high-severity findings to a Step Functions containment workflow that assumes member-account roles, Config noncompliance to SSM Automation, and all findings to Firehose for a security lake. Add SCPs to protect the rules, alarms on failed invocations, and notify-first rollout.

!!! question "After a producer team renamed `customerId` to `clientId`, three consumer teams had outages. What governance changes would prevent recurrence?"

    Register schemas from source control and run backward-compatibility checks in producer CI, failing the build on removals or renames. Require breaking changes to be published as a new `detail-type` or major version, dual-published during a migration window. Introduce consumer-driven contract tests verified in producer CI, and an event catalogue listing consumers so the producer knows whom a change affects. Consumers should use tolerant readers and patterns matching the fields they depend on.

!!! question "A hub account receives throttling (`ThrottledRules`) during a sales event. What are the options?"

    Request quota increases for invocations and `PutEvents` in the hub account ahead of known peaks; reduce hops by delivering some public events directly to consumer accounts; batch producer `PutEvents`; narrow broad rules so fewer invocations occur; move telemetry-like volumes off EventBridge to Kinesis; and ensure targets are SQS queues rather than throttling-prone targets so retries do not amplify load.

!!! question "Consumers report that some `Order Placed` events arrive twice. The producer insists it publishes once. Explain and resolve."

    At-least-once delivery, target retries after ambiguous failures, overlapping rules targeting the same consumer, archive replays, or outbox relay retries can all cause duplicates. Consumers must be idempotent using `metadata.idempotencyKey` or `eventId` with conditional writes or a deduplication table. Review rules for overlap and restrict replays to selected rules.

!!! question "A team wants to push every click event (50,000 per second) through EventBridge so that any team can subscribe. Advise them."

    EventBridge per-event pricing and invocation quotas make this costly and constrained. Put clicks on Kinesis Data Streams, process with Flink or Lambda, land raw data with Firehose, and promote only derived business events (for example "High-Intent Session Detected") to EventBridge through a Pipe. Teams needing raw clicks consume the stream or the data lake.

#### Architecture Questions

!!! question "Compare hub-and-spoke with a direct cross-account mesh for an organisation with 12 domains and a small platform team."

    Hub-and-spoke centralises archive, schema discovery, audit and consumer onboarding (a rule on the hub), at the cost of an extra hop and a shared critical dependency. A direct mesh has lower latency and cost but distributes routing rules across producer accounts, recreating pairwise coupling and making audit hard. With a platform team available, a hybrid with a hub for public events and domain buses for private events is typically best.

!!! question "Design an order process combining Step Functions and choreography, including a payment timeout."

    The orders domain runs a Standard Step Functions workflow triggered by `Order Placed`. It publishes `Payment Requested` with a task token via `events:putEvents.waitForTaskToken` and a heartbeat timeout; the payments domain responds with `Payment Captured` carrying the token, and a rule invokes a small Lambda to call `SendTaskSuccess`. The timeout is handled by the heartbeat (or by Scheduler if choreographed without a workflow), leading to compensation. The workflow publishes `Order Fulfilled` to the hub for shipping and loyalty. Idempotency keys protect all consumers.

!!! question "How would you implement EventBridge routing for services on EKS using GitOps?"

    Each service's repository declares its SQS queue and EventBridge rule (via Terraform in the pipeline, or ACK controllers as Kubernetes custom resources reconciled by Argo CD or Flux). Pods use EKS Pod Identity for SQS and `PutEvents` permissions. KEDA scales Deployments on queue length. Pattern tests and schema checks run in CI before the GitOps controller applies changes. The platform team owns bus policies and hub rules in a separate repository.

!!! question "Using the integrated decision matrix, choose services for: payroll job distribution, stock-price ticks for five analytics systems, mobile push notifications to students, and cross-account order events."

    Payroll jobs: SQS (FIFO if per-employee ordering or deduplication matters) for competing workers. Stock ticks: Kinesis Data Streams (or MSK if Kafka is required) for high-volume ordered data with multiple independent readers and replay. Mobile push: SNS mobile push, possibly triggered by EventBridge rules. Cross-account order events: EventBridge with organisation-scoped bus policies and SQS queues per consumer.

#### Troubleshooting Questions

!!! question "A rule for `ECS Task State Change` events never matches, although tasks are stopping."

    The rule is probably on a custom bus; AWS service events arrive only on the default bus in the task's account and Region. Other causes: pattern case or spelling errors in `detail-type`, matching `exitCode` as a string rather than a number, or the rule being in a different Region. Verify with `TestEventPattern` using a real event captured by a catch-all logging rule on the default bus.

!!! question "`MatchedEvents` increases but the SQS target receives nothing, and `FailedInvocations` is non-zero."

    The queue policy does not allow `events.amazonaws.com` with the rule's `aws:SourceArn`, or the queue is encrypted with a customer-managed KMS key whose policy does not allow EventBridge to use it. Fix the policies; configure a DLQ with a usable key and alarm on `InvocationsFailedToBeSentToDlq`.

!!! question "Cross-account events forwarded to a consumer account bus never trigger the consumer's rule."

    Check the destination bus policy (principal, organisation condition and any `events:source` condition), the forwarding rule's IAM role permissions for `events:PutEvents` on the destination ARN, that the consumer's rule is on the destination bus (not its default bus), that the pattern's `account` field expects the original producer account, and whether the event has already crossed an account boundary in a multi-hop chain.

!!! question "An API destination to a SaaS ticketing tool loses events during incident storms."

    The invocation rate limit and the SaaS API's own limits cause retries that exceed the retry policy's maximum age, and without a DLQ events are dropped. Add a DLQ, increase the retry window, and for sustained bursts route to an SQS queue consumed by a worker that respects SaaS limits and deduplicates or aggregates related incidents.

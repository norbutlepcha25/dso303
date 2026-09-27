# Unit 6: Practice Questions

## 6.1 AWS Storage Solutions

### 6.1.1 Object Storage with Amazon S3

#### Beginner Questions

1. What is the difference between the bucket ARN and an object ARN, and which S3 actions apply to each?
2. Which mechanism delivers S3 credentials to a Lambda function, and why should application code not pass credentials explicitly to the SDK client?
3. Name the three destination types supported by S3 Event Notifications.
4. What does HTTP status 412 indicate when returned by a PutObject request that included `If-None-Match: *`?
5. Why is a Gateway endpoint recommended for ECS tasks in private subnets that read from S3?

#### Intermediate Questions

1. Compare EKS Pod Identity and IRSA in terms of setup, trust policy design and support for session tags.
2. A Lambda function writes thumbnails back into the bucket that triggers it. Describe two design changes that prevent recursion, and explain what Lambda's recursive loop detection does.
3. Explain how CloudFront OAC allows a bucket to remain private, including the bucket policy condition that restricts access to one distribution.
4. Describe how S3 Inventory, Athena and Batch Operations can be combined to re-encrypt every object in a bucket that is not encrypted with a specific KMS key.
5. Configure, in words, a Terraform S3 backend that supports safe concurrent pipeline runs without a DynamoDB table. What S3 feature makes this possible?

#### Advanced Questions

1. Design an idempotent, exactly-once-effect processing pipeline for S3 uploads using EventBridge, SQS and ECS Fargate consumers. Explain how duplicates, deletes and overwrites are handled.
2. Evaluate S3 Express One Zone, S3 general purpose buckets with Mountpoint caching, and Amazon FSx for Lustre as data sources for a distributed GPU training job on EKS. Consider latency, durability, cost and operational effort.
3. Construct a data perimeter for an organisation that must prevent exfiltration of S3 data from ECS and EKS workloads. Specify the SCP, RCP, bucket policy and endpoint policy statements and explain which threat each addresses.
4. A shared bucket's policy has reached its size limit because 60 applications have statements in it. Propose a migration to Access Points with delegation, including how existing clients are moved without downtime.
5. Using conditional writes only, design a stale-lock takeover protocol for a nightly batch job run by several ECS tasks, and analyse the failure scenarios in which two tasks could both believe they hold the lock.

### 6.1.2 Block Storage with Amazon EBS

#### Beginner Questions

1. Why must a pod using an EBS-backed PVC be scheduled in the same Availability Zone as the volume?
2. What is the difference between `reclaimPolicy: Delete` and `reclaimPolicy: Retain` in a StorageClass?
3. Which task definition property indicates that an ECS volume will be configured at deployment?
4. What does enabling EBS encryption by default change for newly created volumes?
5. Name two services that automate the creation and retention of EBS snapshots.

#### Intermediate Questions

1. Explain how a VolumeSnapshot can be used to clone a production database volume into a test namespace on EKS, and which add-ons are required.
2. Compare Data Lifecycle Manager and AWS Backup for protecting EBS volumes across an organisation with 30 accounts.
3. Describe how to share an encrypted AMI with another account and Region, including the KMS requirements.
4. A burstable-bandwidth instance performs well during the first half hour of a batch job and then slows significantly. Which metrics would confirm the cause, and what would you change?
5. When would you choose ECS task-attached EBS volumes rather than Amazon EFS for an ECS service?

#### Advanced Questions

1. Design a multi-tenant Kubernetes platform that offers three storage tiers (standard, fast and archive-backed) using StorageClasses, VolumeAttributesClasses and snapshot policies. Explain how tenants select tiers and how costs are attributed.
2. Evaluate running Apache Kafka on EKS with EBS versus Amazon MSK for a company with a small platform team, considering availability, operations, performance and cost.
3. Design a ransomware-resilient backup architecture for EBS-based workloads using AWS Backup, logically separate accounts, Vault Lock, Recycle Bin and SCPs, and describe the restore procedure.
4. Using AWS Fault Injection Service, design an experiment programme to validate a self-managed PostgreSQL cluster's failover behaviour, including hypotheses, stop conditions, metrics and expected outcomes.
5. A backup vendor proposes to use the EBS direct APIs to perform incremental backups of 5,000 volumes to an on-premises system. Analyse the benefits, the IAM and KMS requirements, the cost dimensions and the risks of this design.

### 6.1.3 File Storage with Amazon EFS

#### Beginner Questions

1. Which TCP port must be allowed from clients to EFS mount targets?
2. What prefix must a Lambda function's EFS local mount path begin with?
3. Which Kubernetes access mode allows many pods on different nodes to mount the same EFS volume read-write?
4. Which ECS IAM role supplies credentials to EFS when `iam: ENABLED` is set in the task definition?
5. Name two AWS services that protect EFS data against, respectively, accidental deletion and Regional failure.

#### Intermediate Questions

1. Compare static and dynamic provisioning with the EFS CSI driver, and give one scenario suited to each.
2. Explain how `gidRangeStart` and `gidRangeEnd` provide isolation between PVCs in `efs-ap` mode.
3. Write a file system policy statement that denies all access without TLS.
4. A workload repeatedly reads 500 GB of data per day from EFS under Elastic throughput. How would you estimate and reduce its throughput cost?
5. Why does EKS on Fargate support only static provisioning of EFS volumes, and how does this affect platform design?

#### Advanced Questions

1. Design a model distribution architecture in which a CI/CD pipeline publishes new model versions to EFS and Lambda and ECS consumers switch versions atomically without reading partially written files.
2. A research group needs 200 GB/s aggregate throughput for training jobs with data sourced from S3. Evaluate EFS, FSx for Lustre and Mountpoint for S3, and justify a choice.
3. Explain how you would migrate 80 TB of NFS data with 30 million small files from an on-premises NAS to EFS with less than one hour of downtime.
4. Describe how you would detect and alert on a Lambda-driven connection surge against an EFS file system, and how you would prevent it from affecting other workloads sharing the file system.
5. Construct a failover and failback runbook for EFS Replication, including access points, policies, compute, DNS and validation steps.

### 6.1.4 Caching Strategies with Amazon ElastiCache

#### Beginner Questions

1. Name four caching layers available in an AWS cloud-native stack, from the edge inward.
2. What is the default eviction policy in the ElastiCache default parameter group, and which keys can it evict?
3. Why must a Lambda function that uses ElastiCache be attached to a VPC?
4. What is negative caching?
5. Which ElastiCache engine is priced lowest among Valkey and Redis OSS, and why might a new project choose it?

#### Intermediate Questions

1. Build a decision table choosing between cache-aside, write-through and refresh-ahead for user profiles, stock levels and a homepage aggregate.
2. Explain how TTL jitter prevents synchronised expiry, and write a formula for a jittered TTL.
3. Describe the steps to enable IAM authentication for an ECS service connecting to ElastiCache Serverless for Valkey.
4. Compare distributed locks, XFetch and request coalescing for stampede protection.
5. When would you choose ElastiCache Serverless over a node-based cluster, and which metrics would you monitor for each?

#### Advanced Questions

1. Design an event-driven invalidation pipeline for Aurora-backed data using the transactional outbox pattern, including idempotency and ordering considerations.
2. A flash sale is expected to drive 500,000 reads per second to a single product key. Design the caching architecture end to end, from CloudFront to ElastiCache.
3. Size a node-based ElastiCache cluster for 50 million sessions of 2 KB each with a peak of 200,000 operations per second, and compare with an ElastiCache Serverless estimate in terms of billing dimensions.
4. Evaluate the risks of using ElastiCache-based distributed locks for preventing double payment, and propose a safer design.
5. Design a semantic cache for a Bedrock-powered assistant, addressing similarity thresholds, tenant isolation, TTL and invalidation when source documents change.

---

## 6.2 AWS Database Services

### 6.2.1 Relational Databases with Amazon RDS and Aurora

#### Beginner Questions

1. Define session pinning in RDS Proxy and name two statements that cause it.
2. State the lifetime of an IAM database authentication token and explain what happens to an established connection when the token expires.
3. What is the difference between ECS task definition `environment` and `secrets` entries?
4. Name the two phases of the expand-contract pattern that change the database schema, and state which one removes structures.
5. Explain in one sentence why the RDS Data API is useful for Lambda functions that are not attached to a VPC.

#### Intermediate Questions

1. An EKS Deployment scales between 6 and 60 pods; each pod has a pool of 15. Another service on ECS scales to 30 tasks with a pool of 10. Compute worst-case connection demand, compare it with a limit of 1,000, and propose two changes.
2. Using Little's Law, compute the average busy connections for a task serving 400 queries per second with a mean connection hold time of 3 ms, and recommend a pool size.
3. Compare the External Secrets Operator and the Secrets Store CSI Driver for delivering a rotated database credential to pods.
4. Explain how RDS Blue/Green Deployments keep the green environment current, and give one schema change that is compatible and one that is not.
5. Describe how an Aurora fast clone reduces risk in a migration pipeline, and state one security control required when cloning production.

#### Advanced Questions

1. Design an end-to-end identity chain from an EKS pod to a PostgreSQL grant with no stored password, supporting 5,000 new connections per minute. Justify each component.
2. A shared Aurora cluster hosts eight services using schema-per-service. One service's batch job causes latency for all others. Propose short-term and long-term remedies, including bulkheads and a promotion to cluster-per-service, and describe the migration path with CDC.
3. Design a transactional outbox implementation on Aurora PostgreSQL that publishes to EventBridge with at-least-once delivery and consumer idempotency, including replication slot monitoring and failure handling.
4. Evaluate whether a new multi-Region inventory service should use Aurora Global Database, Aurora DSQL or DynamoDB Global Tables. Address consistency, conflict handling, compatibility, failover and application design implications.
5. A platform team wants developers to self-serve databases from Kubernetes. Design this with ACK, GitOps, Serverless v2 scale to zero for non-production, secrets delivery and guardrails (encryption, deletion protection, tagging), and identify the risks.

### 6.2.2 NoSQL Databases with Amazon DynamoDB

#### Beginner Questions

1. What does an inverted index do, and which access pattern in RideLink needs it?
2. Write the condition expression that allows a trip update only if its `version` equals 7.
3. Why must the idempotency record expiry exceed the maximum retry horizon of upstream callers?
4. Name two differences between an API Gateway direct integration and a Lambda proxy integration for reading an item.
5. What does `ReportBatchItemFailures` change in a stream event source mapping?

#### Intermediate Questions

1. Extend the RideLink design to support "list all trips a driver and rider shared" without a new GSI, and state the trade-offs.
2. Using the RideLink cost model, calculate the monthly write request units if versioning is replaced by 1 KB non-transactional history events, and state the percentage saving.
3. Configure a Lambda event source mapping for an audit archive that must never block and must retain failed records for investigation. Justify each setting.
4. Explain how EventBridge Pipes and an input transformer protect downstream consumers from changes to the table's key design.
5. Describe the prerequisites and data flow of a DynamoDB zero-ETL integration with OpenSearch Service.

#### Advanced Questions

1. Design a model for a multi-tenant clinic appointment system with patients, clinicians, clinics and slots, supporting double-booking prevention, clinician calendars, patient history and a waiting-list queue. Produce the access pattern table, key design and indexes, and identify hot-key risks.
2. Evaluate MREC and MRSC Global Tables for a rider wallet used in three Regions. Address latency, conflict behaviour, feature constraints, recovery point and application changes, and recommend a design.
3. A table must be re-keyed because the original partition key causes hot partitions. Design a zero-downtime migration using dual writes, a backfill via export and import or a throttled job, stream-based catch-up, cut-over and verification.
4. Design a testing strategy for a DynamoDB-backed service spanning unit tests, DynamoDB Local integration tests, ephemeral real tables in CI, permission tests for `LeadingKeys` and load tests for hot keys. Explain what each layer can and cannot detect.
5. Compare three ways of exposing RideLink trip data to a partner in another AWS account: a resource-based policy on a GSI, a zero-ETL feed into the partner's Redshift, and events on a cross-account EventBridge bus. Evaluate coupling, security, freshness and cost.

### 6.2.3 Graph Databases with Amazon Neptune

#### Beginner Questions

1. Define vertex, edge, label and property, giving an example of each from a social network.
2. Name the three query languages supported by Neptune Database and state which data model each targets.
3. How many read replicas can a Neptune Database cluster have, and what is the purpose of the reader endpoint?
4. Which port does Neptune listen on, and which AWS network control must allow traffic to it?
5. What is the purpose of the Neptune bulk loader, and which AWS service stores its source files?

#### Intermediate Questions

1. Write an openCypher query and an equivalent Gremlin traversal that return all products purchased by friends of a given user but not by the user.
2. Compare a DynamoDB adjacency list with Neptune for a feature requiring five-hop traversals. Discuss latency, cost and development effort.
3. Explain how Neptune Serverless scaling works, including its minimum capacity, and when you would mix provisioned and serverless instances in one cluster.
4. Describe how to grant an EKS pod read-only access to Neptune without any database password.
5. Explain what Neptune Streams provides and design a consumer that replicates graph changes to EventBridge with at-least-once delivery.

#### Advanced Questions

1. Design a multi-Region architecture for a global identity graph with a recovery point objective of seconds and low-latency reads in three continents. Discuss Global Database, write routing and failover procedures.
2. A fraud graph has a small number of vertices with tens of millions of edges. Propose a remodelling strategy and quantify how it bounds traversal fan-out.
3. Design a GraphRAG solution for a university's regulations and policy documents using Amazon Bedrock and Neptune Analytics. Explain when it would outperform vector-only RAG and what its operational costs are.
4. Propose a CI/CD approach for graph model changes, including query regression tests with `explain`, backward-compatible label changes and data backfills.
5. Evaluate whether Neptune ML link prediction or precomputed Neptune Analytics similarity scores is the better approach for real-time product recommendations, considering latency, freshness, cost and operational complexity.

### 6.2.4 Data Warehousing with Amazon Redshift

#### Beginner Questions

1. Define a data warehouse and state three ways it differs from an OLTP database.
2. What is a zone map, and why does it depend on the sort key?
3. List the four distribution styles and give one appropriate use for each.
4. What is an RPU, and how is Redshift Serverless compute billed?
5. Which Redshift command loads data in parallel from S3, and which exports query results to S3?

#### Intermediate Questions

1. Design a star schema for a university library's borrowing process, stating the grain, the fact table measures, the dimensions and their distribution styles.
2. Explain how a zero-ETL integration from Aurora into Redshift works and why a staging layer should be built on top of the replicated tables.
3. Compare automatic WLM with short query acceleration and concurrency scaling, and describe a configuration for a warehouse used by both ETL jobs and executive dashboards.
4. Write a Lambda function outline that uses the Redshift Data API with parameterised SQL, and explain why the Data API is preferred over JDBC for Lambda.
5. Explain when Redshift Spectrum is more cost-effective than loading data into managed storage, and how file format and partitioning affect Spectrum performance and cost.

#### Advanced Questions

1. Design a data mesh on AWS in which three domain teams publish data products from their own Redshift workgroups to a central governance layer. Address datashares, Lake Formation permissions, cross-account access, cost allocation and data contracts.
2. A SaaS provider must offer tenant-level embedded analytics with strict isolation for 500 tenants. Compare a shared warehouse with row-level security against per-tenant workgroups with data sharing, considering security, cost, noisy neighbours and operations.
3. Build a cost model comparing Redshift Serverless and provisioned RA3 with Reserved Nodes for a workload that runs 6 hours of heavy processing daily plus light dashboard traffic during business hours. Identify the assumptions and the break-even point.
4. Design an end-to-end pipeline that ingests order events from Amazon MSK, joins them with product data replicated from DynamoDB, maintains a slowly changing customer dimension, and refreshes dashboards within one minute of an order. Justify each AWS service and the failure-handling strategy.
5. Evaluate Redshift, Athena, EMR and OpenSearch for a platform that must support ad hoc exploration of 2 PB of raw logs, sub-second product search, nightly feature engineering for ML, and high-concurrency financial dashboards. Propose a combined architecture and explain the data flows between engines.

---

## 6.3 Messaging and Event Streaming

### 6.3.1 Message Queues with Amazon SQS

#### Beginner Questions

1. Define point-to-point messaging and explain how it differs from publish/subscribe.
2. What is a receipt handle, and why can a message not be deleted using its message ID?
3. List the default and maximum values of the visibility timeout, the retention period and the long polling wait time.
4. Why must a FIFO queue name end in `.fifo`, and can an existing standard queue be converted to FIFO?
5. What is a dead-letter queue, and what does `maxReceiveCount` control?

#### Intermediate Questions

1. A worker's processing time varies from 5 seconds to 25 minutes. Explain how you would configure the visibility timeout and implement heartbeats, and why a 12-hour timeout is a poor choice.
2. Calculate the target number of ECS tasks for a queue with 18,000 visible messages if each message takes 0.2 seconds and the acceptable latency is 30 seconds. Show the backlog-per-task calculation.
3. Explain the difference between reserved concurrency and event source mapping maximum concurrency for a Lambda function consuming SQS, and which one you would use to protect a database.
4. Write the redrive policy and redrive allow policy for a source queue `payments` and DLQ `payments-dlq` in account 111122223333, and explain why the DLQ retention should be 14 days.
5. A Lambda function processes batches of 10 messages and one message fails. Describe what happens with and without `ReportBatchItemFailures`.

#### Advanced Questions

1. Design a multi-tenant job system in which premium tenants have a latency objective of 10 seconds and free tenants of 10 minutes, while no single tenant can starve others. Justify your use of multiple queues, fair queues, maximum concurrency and scaling policies.
2. An order service must publish order state changes to a FIFO queue at 15,000 messages per second while preserving per-order ordering and preventing producer duplicates. Explain high-throughput FIFO configuration, the choice of group and deduplication IDs, the consumer design for partial batch failures, and the operational alarms you would add.
3. Compare SQS with Kinesis Data Streams and EventBridge for an event whose consumers include a real-time analytics job that must re-read the last 24 hours after a bug fix. Which service or combination would you choose and why?
4. Describe a complete secure deployment of an SQS consumer on EKS using infrastructure as code and CI/CD: the queue with SSE-KMS and DLQ, the VPC endpoint, EKS Pod Identity, KEDA scaling, CloudWatch alarms and a pipeline stage that validates visibility timeout against the consumer's configured processing timeout.
5. A payment workflow uses API Gateway to SQS to Lambda to a third-party API. During a partner outage lasting six hours, the DLQ fills and some messages expire. Perform a post-incident analysis: identify the configuration errors (retention, maxReceiveCount, retry strategy, circuit breaking) and propose a redesign using visibility-based backoff, a circuit breaker (Chapter 4.3), longer retention and DLQ redrive.

### 6.3.2 Pub/Sub Messaging with Amazon SNS

#### Beginner Questions

1. Define a topic, a subscription and an endpoint in Amazon SNS.
2. List five SNS subscription protocols and give one use case for each.
3. Which subscription protocols require confirmation, and why?
4. Explain why a subscriber added today does not receive messages published yesterday to a standard topic.
5. What is a filter policy, and what is the difference between attribute-based and payload-based filtering?

#### Intermediate Questions

1. Write the SQS queue policy that allows the topic `arn:aws:sns:us-east-1:111122223333:order-events` to deliver to the queue `arn:aws:sqs:us-east-1:111122223333:shipping-queue`, and explain the purpose of the condition.
2. Write a filter policy that matches messages whose `eventType` is `OrderPlaced` or `OrderUpdated`, whose `country` is not `US`, and whose `total` is between 100 and 1,000.
3. Compare the default SNS delivery behaviour for SQS, Lambda and HTTPS subscriptions, and explain how you would protect a partner HTTPS endpoint that can accept only 20 requests per second.
4. Explain the key policy statements needed when a CloudWatch alarm publishes to an encrypted SNS topic that fans out to encrypted SQS queues.
5. Describe how you would use raw message delivery and message attributes so that an ECS consumer can decide how to process a message without parsing the body.

#### Advanced Questions

1. Design an event distribution platform for a retailer with 40 microservices across 10 AWS accounts. Justify where you would use SNS topics, SQS queues and EventBridge buses, how you would handle ownership, schema versioning, encryption, cross-account policies and monitoring, and how CI/CD would validate filter policies.
2. A bank requires ordered delivery of account events to four consumers, 20,000 messages per second at peak, replay for 90 days and PII masking for one analytics consumer. Evaluate SNS FIFO with high-throughput mode, archive and data protection policies against an alternative using Kinesis Data Streams, and recommend a design.
3. Analyse the failure modes of an SNS-to-SQS-to-Lambda pipeline end to end (publish throttling, key policy errors, filter misconfiguration, Lambda throttling, poison messages, duplicate delivery) and specify the metric, alarm and remediation for each.
4. Explain how you would migrate a monolith's synchronous notification calls (email, partner webhooks and three internal services) to SNS-based choreography with the transactional outbox pattern, including a rollout plan that avoids lost or duplicated notifications.
5. A multi-tenant SaaS platform publishes tenant events to a standard SNS topic consumed through SQS by a shared worker fleet. A single large tenant causes latency for all others. Propose solutions using SNS message group IDs with SQS fair queues, per-tier topics or queues, and maximum concurrency controls, and discuss the trade-offs of each.

### 6.3.3 Stream Processing with Amazon Kinesis

#### Beginner Questions

1. What are the write and read throughput limits of a single provisioned Kinesis shard, and why is the read limit higher?
2. Name the four Kinesis family services and state the primary purpose of each.
3. What is the default retention period of a Kinesis data stream, and what is the maximum?
4. Explain the difference between `TRIM_HORIZON` and `LATEST` starting positions.
5. Why must a stream consumer be idempotent?

#### Intermediate Questions

1. A workload sends 3,000 records per second of 2 KB each. Calculate the minimum number of provisioned shards and explain which limit dominates.
2. Describe how `BisectBatchOnFunctionError`, `MaximumRetryAttempts` and an on-failure destination work together in a Lambda event source mapping.
3. Compare provisioned and on-demand capacity modes in terms of scaling, pricing dimensions and suitable workloads.
4. Explain why Firehose Parquet conversion requires a larger buffer, and describe the effect of Parquet on Athena query cost.
5. What is a KCL lease table, and what happens when two unrelated KCL applications are deployed with the same application name?

#### Advanced Questions

1. Design a partition key strategy for a multi-tenant SaaS analytics stream in which one tenant generates 60 percent of traffic but per-user ordering is required. Justify the trade-offs.
2. Explain how Apache Flink achieves exactly-once state consistency over a Kinesis source, and what additional conditions are required for exactly-once results in an external database.
3. Propose a cross-Region disaster recovery design for a critical Kinesis pipeline, including how consumers resume and how duplicates are handled.
4. Compare tumbling, sliding and session windows, and give a business metric for which each is the correct choice, including how late data should be treated.
5. A pipeline must deliver clickstream to both a real-time dashboard with 2-second freshness and a cost-efficient data lake queried daily. Design the pipeline and explain how you avoid the small-files problem while meeting the freshness requirement.

### 6.3.4 Event Routing with Amazon EventBridge

#### Beginner Questions

1. Why do AWS service events such as `ECS Task State Change` appear only on the default event bus, and what must you do to process them in a central account?
2. List three naming conventions for `source` and `detail-type` and explain why each helps routing.
3. What is the purpose of `TestEventPattern`, and how would you use it in a CI pipeline?
4. Name three AWS operational event sources and an automated response for each.
5. Why should an SQS queue normally sit between an EventBridge rule and an ECS service?

#### Intermediate Questions

1. Write a bus policy statement that allows only accounts in your organisation to publish events with source `com.dso303.payments` to a hub bus, and explain each condition.
2. Explain how EventBridge Scheduler can implement a 30-minute reservation hold, including creation, cancellation, the race condition and clean-up.
3. Compare Pipes enrichment with a Lambda target that enriches and republishes; discuss cost, failure handling and ordering for a Kinesis source.
4. Describe a versioning strategy for a public event that must rename a field, from the first commit to the retirement of the old version.
5. Explain how KEDA scales an EKS Deployment that consumes events routed from EventBridge, including the identity configuration.

#### Advanced Questions

1. Design a multi-Region, multi-account event mesh for a regulated bank, including topology, global endpoints, encryption, spoofing prevention, archive and replay, and disaster-recovery testing.
2. Critically evaluate the claim that "EventBridge should be the only messaging service in a cloud-native organisation", using the integrated decision matrix and a cost-at-scale argument.
3. Design an auto-remediation platform for Config and GuardDuty findings across 200 accounts that supports notify-only mode, exemptions, approvals for high-impact actions, idempotency and full audit.
4. Propose an end-to-end testing strategy for a choreographed saga spanning four domains and three accounts, covering unit, pattern, contract, integration, replay and failure testing.
5. An event hub has 280 rules on one bus, rising latency and occasional throttling. Diagnose the likely causes and design a migration to a scalable topology without downtime or duplicate side effects.

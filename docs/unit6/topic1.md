---
render_macros: false
---

# AWS Storage Solutions

This section is organised in four parts, each of which can be studied on its own.

| Part | Service | Abstraction | Central integration question |
|------|---------|-------------|------------------------------|
| Object Storage with Amazon S3 | Amazon S3 | Object | How does S3 act as the shared data plane and event source that connects services? |
| Block Storage with Amazon EBS | Amazon EBS | Block | How do stateful containers and instances obtain durable, low-latency disks? |
| File Storage with Amazon EFS | Amazon EFS | File | How do many containers and functions share one POSIX file system safely? |
| Caching Strategies with Amazon ElastiCache | Amazon ElastiCache | In-memory key-value | Where, what and how long should a cloud-native system cache? |

## Choosing a Storage Service for a Workload

The four parts share one decision that should be made before any of them is read in detail: which abstraction the workload needs. The flow below extends the survey framework from [Chapter 1.4](../unit1/topic4.md) with the caching layer.

```mermaid
flowchart TD
    A["Data produced or consumed by a workload"] --> B{"Is it a copy that can be recomputed from a system of record"}
    B -->|"yes, and it must be served in microseconds"| C["Amazon ElastiCache"]
    B -->|"no, it is durable data"| D{"How is it accessed"}
    D -->|"whole objects over HTTPS, by many services"| E["Amazon S3"]
    D -->|"random block I/O from one task or instance"| F["Amazon EBS"]
    D -->|"shared POSIX paths from many tasks or functions"| G["Amazon EFS"]
    E --> H["Event source, data lake, artefacts, static assets"]
    F --> I["Databases, StatefulSets, boot volumes"]
    G --> J["Shared content, ML models, legacy shared directories"]
    C --> K["Sessions, hot reads, rate limits, leaderboards"]
```

| Criterion | Amazon S3 | Amazon EBS | Amazon EFS | Amazon ElastiCache |
|-----------|-----------|------------|------------|--------------------|
| Consumed from ECS | Task role and SDK | EBS volume attached at task deployment | EFS volume in the task definition | Client library over TLS inside the VPC |
| Consumed from EKS | Pod Identity or IRSA, Mountpoint CSI driver | EBS CSI driver, ReadWriteOnce | EFS CSI driver, ReadWriteMany | Client library, cluster-aware client |
| Consumed from Lambda | SDK and native event source | Not supported | Mounted under /mnt when the function is in a VPC | Client library, function in a VPC |
| Scope | Regional | Single Availability Zone | Regional or One Zone | VPC, Multi-AZ replication group |
| Durability role | System of record | System of record for one host | System of record for shared files | Never the system of record |
| Typical latency | Tens of milliseconds, single digits with Express One Zone | Sub-millisecond | Low milliseconds | Sub-millisecond |

!!! tip "The architectural thread of this section"
    Cloud-native compute is disposable only when its state lives somewhere else. Every part of this section is a variation on one idea: **externalise state into the managed service whose access pattern matches it**, grant each workload its own least-privilege identity to reach it, and observe it as carefully as the compute that uses it.

### The Three Storage Abstractions

AWS offers three storage services rather than one because object, block and file storage make **mutually incompatible trade-offs**:

- Object storage achieves near-infinite scale and extreme durability because it gives up in-place mutation, POSIX semantics and low-latency small random writes. Every object is written whole, erasure-coded across devices and identified by a key in a flat namespace, so you cannot open an object, seek to byte 4,096 and overwrite four bytes.
- Block storage achieves sub-millisecond latency and true random access because it presents a narrow interface (read block N, write block N) to one host at a time in the common case. It cannot span Availability Zones, because synchronous block replication across tens of kilometres would destroy the latency guarantee.
- File storage achieves shared, concurrent, POSIX-correct access from many hosts because it maintains a distributed metadata service that coordinates directories, locking and permissions. That coordination is what makes EFS more expensive per gigabyte and higher-latency than EBS, and also what lets a hundred containers write into the same directory safely.

| Dimension | Object storage | Block storage | File storage |
|---|---|---|---|
| Unit of storage | Object: bytes plus metadata | Fixed-size block, typically 512 B or 4 KiB | File within a directory hierarchy |
| Namespace | Flat keyspace within a bucket | Linear array of numbered blocks | Hierarchical tree of directories |
| Access protocol | HTTPS REST API | Block protocol over a network path, presented as a device | NFS or SMB |
| Mutation model | Replace whole object; no partial overwrite | Overwrite any block in place | Read, write, seek, truncate, append |
| Metadata | Rich, user-defined, stored with the object | None beyond the block address | POSIX attributes: owner, mode, timestamps |
| Concurrent writers | Many, last write wins per key | Normally one host; Multi-Attach is a special case | Many, coordinated by the file system |
| Typical latency | Tens of milliseconds first byte | Sub-millisecond to low single-digit milliseconds | Low single-digit milliseconds |
| Scale ceiling | Effectively unlimited | Per-volume ceiling, currently 64 TiB for gp3 and io2 Block Express, 16 TiB for the other types | Petabyte-scale, elastic |
| AWS service | Amazon S3 | Amazon EBS, instance store | Amazon EFS, Amazon FSx |

!!! note "Storage is not the same as a database"
    A database imposes structure, query semantics, transactions and indexing on top of storage. A storage service stores bytes and returns bytes. RDS internally uses EBS volumes; DynamoDB uses its own distributed storage layer. If you need to *query* data by content, you want a database ([Section 6.2](../unit6/topic2.md)); if you need to *retrieve* data by identity, you want storage.

The comparison below adds instance store, the ephemeral block storage physically attached to the EC2 host, which is covered with EBS in [Instance store versus EBS](#instance-store-versus-ebs).

| Criterion | Amazon S3 | Amazon EBS | Amazon EFS | Instance Store |
|---|---|---|---|---|
| Abstraction | Object | Block | File | Block |
| Scope | Regional | Single Availability Zone | Regional, multi-AZ | Single host |
| Concurrent access | Unlimited clients over HTTP | One instance, or up to sixteen with Multi-Attach | Thousands of clients | One instance |
| Capacity model | Unlimited, pay for stored bytes | Provisioned, pay for provisioned bytes | Elastic, pay for stored bytes | Fixed by instance type, included in instance price |
| Latency | Tens of milliseconds; single-digit for Express One Zone | Sub-millisecond to low milliseconds | Low milliseconds | Microseconds |
| Throughput ceiling | Effectively unlimited with parallelism | Up to 4,000 MiB/s per volume | Multiple GiB/s aggregate | Highest available |
| Durability | Eleven nines across three or more AZs | Replicated within one AZ; snapshots for cross-AZ | Eleven nines across three or more AZs | None |
| Survives instance termination | Yes | Yes | Yes | No |
| Survives AZ failure | Yes | No, data preserved but inaccessible | Yes | No |
| In-place partial update | No | Yes | Yes | Yes |
| POSIX semantics | No | Yes, via the guest file system | Yes | Yes, via the guest file system |
| Typical relative cost per GiB-month | Lowest | Moderate | Highest | Included |
| Best for | Data lakes, backups, media, artefacts, logs | Boot volumes, databases, single-host state | Shared content, CMS, ML datasets, container shared volumes | Cache, scratch, shuffle, replicated NoSQL |
| Worst for | Transactional writes, POSIX applications | Multi-AZ shared state | Latency-critical databases | Anything that must survive |

!!! example "Apply the framework"
    A team must store user-uploaded profile photographs for a web application running on ECS Fargate across three Availability Zones. The data must outlive the task, so it is not instance store. Multiple tasks read it, but only through the application over HTTP, and each photograph is written whole and never partially updated. The answer is S3, fronted by CloudFront, with uploads performed by presigned URL directly from the browser so that the application tier never handles the bytes. EFS would work, but it costs more, scales worse and provides no CDN integration.

Ranked from least to most operationally demanding: S3 requires almost nothing beyond policy hygiene; EFS requires network and access point configuration but no capacity management; EBS requires capacity planning, file system growth, snapshot scheduling and Availability Zone-aware failover design.

### Durability and Availability

Students frequently conflate these two figures. They measure different failure modes and are engineered by different mechanisms.

- **Durability** is the probability that stored data is not lost. S3 Standard is designed for 99.999999999 percent (eleven nines) annual durability, achieved by erasure-coding each object across devices in at least three Availability Zones.
- **Availability** is the probability that stored data can be *accessed* at a given moment. S3 Standard has a 99.99 percent availability design target with a 99.9 percent Service Level Agreement.

Data can be perfectly durable and temporarily unavailable, for instance during a control plane disruption. A design requiring high availability may therefore need a second Region or a cached copy, even though single-Region durability is already extraordinary.

| Service or class | Design durability | Design availability | AZ scope |
|---|---|---|---|
| S3 Standard | 99.999999999 percent | 99.99 percent | Three or more AZs |
| S3 Standard-IA | 99.999999999 percent | 99.9 percent | Three or more AZs |
| S3 One Zone-IA | 99.999999999 percent within the AZ | 99.5 percent | One AZ |
| S3 Glacier Deep Archive | 99.999999999 percent | 99.99 percent after restore | Three or more AZs |
| S3 Express One Zone | 99.999999999 percent within the AZ | 99.95 percent | One AZ |
| EBS gp3 and io2 volume | Annual failure rate between 0.1 and 0.2 percent for gp3; io2 is designed for 99.999 percent durability | 99.8 to 99.999 percent depending on type | One AZ |
| EBS snapshot | Same multi-AZ durability as S3 | Regional | Regional |
| EFS Standard (Regional) | Designed for eleven nines | 99.99 percent | Three or more AZs |
| EFS One Zone | Designed for eleven nines within the AZ | 99.9 percent | One AZ |
| Instance store | None; ephemeral | Tied to the instance | One host |

!!! note "Interpreting eleven nines"
    Eleven nines of annual durability means that if you store ten million objects, you should statistically expect to lose one object every ten thousand years. The figure describes AWS device and facility failure. It does **not** protect against a user or application deleting the data, a misconfigured policy, or ransomware. Those risks are addressed by versioning, MFA Delete, Object Lock, replication to a separate account and AWS Backup vaults, as discussed in each part below.

| Failure scenario | S3 impact | EBS impact | EFS impact |
|---|---|---|---|
| Single storage device fails | None, transparent repair | None, replica serves | None, redundant copies |
| Single Availability Zone fails | None for multi-AZ classes | Volume inaccessible until the zone recovers | None; other mount targets serve |
| Region fails | Requires replication to another Region | Requires cross-Region snapshot copies | Requires EFS replication |
| Accidental deletion | Versioning and Object Lock protect | Snapshots and Recycle Bin protect | AWS Backup protects |
| Credential compromise | Replication to a separate account and Object Lock protect | Cross-account snapshot copies protect | Cross-account backup vault protects |

!!! warning "Cross-Region replication is asynchronous everywhere"
    No AWS storage service offers synchronous cross-Region replication, so every multi-Region storage design has a non-zero Recovery Point Objective that must be stated explicitly.

### Control Plane and Data Plane

Every AWS storage service separates two subsystems, and conflating them is a common source of architectural error.

The **control plane** handles resource lifecycle: creating buckets, creating and attaching volumes, creating mount targets, modifying configuration. Control plane operations are low-volume, often Regional, involve consensus and metadata updates, and take seconds to minutes. The **data plane** moves bytes: `GetObject`, `PutObject`, block reads and writes, NFS operations. Data plane operations are extremely high-volume, designed for minimal dependencies, and take microseconds to milliseconds.

AWS engineers data planes for **static stability**: the ability to keep operating correctly while the control plane is impaired. This is why a running EC2 instance keeps reading and writing its EBS volume during a Regional control plane event even though new instances cannot be launched.

| Aspect | Control plane | Data plane |
|---|---|---|
| S3 examples | `CreateBucket`, `PutBucketPolicy`, `PutBucketLifecycleConfiguration` | `GetObject`, `PutObject`, `ListObjectsV2` |
| EBS examples | `CreateVolume`, `AttachVolume`, `CreateSnapshot`, `ModifyVolume` | Block read and write from the attached instance |
| EFS examples | `CreateFileSystem`, `CreateMountTarget`, `CreateAccessPoint` | NFS read, write and metadata operations |
| Failure impact | Cannot provision or reconfigure | Cannot access data, which is far more severe |
| Design implication | Pre-provision capacity; do not create resources on the critical path | Design retries, timeouts and multi-AZ redundancy here |

!!! tip "A design rule that follows directly"
    Never place a control plane call on a user request's critical path. An application that calls `CreateBucket` or `AttachVolume` during a customer transaction has coupled its availability to the least-available subsystem. Provision in advance through Infrastructure as Code ([Chapter 5.3](../unit5/topic3.md)) and let the request path touch only the data plane. The same split also drives least privilege: workload roles hold data plane permissions, pipelines hold control plane permissions (see [S3 as a shared data plane](#s3-as-a-shared-data-plane)).

### Encryption Across the Storage Services

All three services encrypt at rest with AWS KMS and support encryption in transit; the service-specific settings are described in each part ([S3](#security-features), [EBS](#security-features_1), [EFS](#security-features_2)). Key types, envelope encryption, key policies and the S3 Bucket Key mechanism are explained once in [8.3 Encryption at Rest with AWS KMS](../unit8/topic3.md#encryption-at-rest-with-aws-kms).

---

## Object Storage with Amazon S3

### Definition

Amazon Simple Storage Service (Amazon S3) is a regional, fully managed object storage service accessed through an HTTPS API. In the context of service integration, S3 is best defined as **a durable, event-emitting, policy-governed shared data plane** that decouples producers of data from its consumers.

Within an AWS architecture, S3 sits beneath almost every other layer:

| Layer | How S3 participates |
|-------|---------------------|
| Compute (ECS, EKS, Lambda, EC2) | Reads inputs, writes outputs, stores models and configuration bundles |
| Eventing (Lambda, SQS, SNS, EventBridge) | Emits object-level events that start downstream processing |
| Delivery (CloudFront) | Serves as the origin for static sites, media and downloadable artefacts |
| Analytics (Athena, Glue, EMR, Redshift) | Holds the data lake, including Apache Iceberg tables |
| Machine learning (SageMaker AI, Bedrock) | Stores training data, checkpoints, model artefacts and knowledge-base documents |
| Delivery pipelines (CodePipeline, CodeBuild, Terraform) | Stores build artefacts, caches and infrastructure state |
| Governance (Macie, GuardDuty, CloudTrail, AWS Backup) | Is scanned, audited and protected as a primary data store |

### Why This Service or Concept Exists

- **Shared state for ephemeral compute:** Containers, functions and replaced instances have no durable local disk, so large data that many independent components must reach needs a home outside the compute tier.
- **Traditional options fail at scale:** Local disks are lost with the instance, NFS servers are single-AZ single points of failure, database BLOB columns are expensive, and FTP drop folders lack fine-grained authorisation.
- **Shared, elastic and addressable:** S3 is shared by default, grows without provisioning and is reachable over HTTPS from anywhere with the right IAM permissions.
- **Change as events:** S3 announces object changes as events, so downstream processing can react instead of polling.
- **A service that keeps absorbing responsibilities:** AWS has added Access Points, Multi-Region Access Points, Access Grants, Express One Zone, S3 Tables, conditional writes and Mountpoint as customers used S3 far beyond file storage, so custom code such as an external lock table should be re-evaluated regularly.

### Core Concepts

#### Buckets, objects, keys and prefixes

| Concept | Meaning |
|---------|---------|
| Bucket | A container for objects, created in one AWS Region. General purpose bucket names are globally unique because they must resolve as DNS names, but the bucket is a Regional resource: its data never leaves the Region unless you replicate it |
| Object | The stored entity: a key, a value (from zero bytes to 5 TiB), a version identifier, metadata and access-control information |
| Key | The full, unique name of an object within a bucket, for example `logs/2026/08/10/app-server-01.log.gz`. It is a single flat string |
| Prefix | Any leading substring of a key, conventionally delimited by `/`. Prefixes emulate folders in the console, partition request-rate scaling, and scope many IAM policies and lifecycle rules |
| Delimiter | A character passed to `ListObjectsV2` that rolls keys sharing a common prefix into `CommonPrefixes`, producing the appearance of a folder listing |
| Versioning | A bucket setting under which every `PUT` and `DELETE` creates a new version instead of replacing or removing data; a `DELETE` inserts a delete marker and prior versions remain billed |
| Storage class | A per-object attribute selecting the durability, availability, latency and cost profile (see [Storage classes](#storage-classes)) |
| Lifecycle policy | Bucket rules that transition objects between storage classes or expire them after a defined age, evaluated asynchronously about once per day |
| Multipart upload | A protocol for uploading a large object as independent parts sent in parallel, retried individually and assembled server-side |
| Presigned URL | A time-limited URL embedding a signature that grants one operation on one object to an anonymous holder, without giving them IAM credentials |

!!! warning "There are no folders in S3"
    The console displays folders and the CLI accepts folder-like paths, but the data model is a flat map from key strings to objects. Creating a "folder" in the console creates a zero-byte object whose key ends in `/`. Believing in folders leads to two classic errors: assuming that renaming a prefix is cheap (it is a copy of every object followed by a delete of every object), and assuming that listing is free (it is a paginated, billed API call that scans the index).

#### Consistency model

Since December 2020, S3 provides **strong read-after-write consistency** for all `PUT` and `DELETE` operations on all objects, in all Regions, with no performance penalty and no opt-in. A successful `PUT` is immediately visible to any subsequent `GET`, `LIST` or `HEAD`, and overwrites and deletes are also strongly consistent. Code that sleeps or retries after a write "to wait for consistency" can be deleted. Two caveats remain:

- Bucket **configuration** changes (policies, lifecycle rules, replication rules) remain eventually consistent and may take time to propagate.
- Cross-Region Replication is asynchronous and gives no consistency guarantee at the destination; S3 Replication Time Control provides a fifteen-minute Service Level Agreement for the vast majority of objects, but is still asynchronous.

#### S3 as a shared data plane

The general control plane and data plane distinction is explained in [Control Plane and Data Plane](#control-plane-and-data-plane). For S3, a useful mental model divides interactions into three planes:

| Plane | Operations | Typical caller |
|-------|------------|----------------|
| Data plane | GetObject, PutObject, HeadObject, ListObjectsV2, DeleteObject | Application code in tasks, pods and functions |
| Control plane | CreateBucket, PutBucketPolicy, PutBucketNotificationConfiguration, PutBucketLifecycleConfiguration | IaC tools and pipelines |
| Management plane | Batch Operations, Inventory, Storage Lens, Access Grants | Platform and data governance teams |

A well-designed workload role should normally hold **only data plane permissions, scoped to specific prefixes**. Control plane permissions belong to the deployment pipeline.

#### Credential delivery to workloads

No cloud-native workload should hold long-lived access keys. Each compute platform has its own mechanism for delivering short-lived credentials obtained through AWS Security Token Service (STS):

| Compute platform | Credential mechanism | Where credentials come from |
|------------------|----------------------|-----------------------------|
| EC2 instance | Instance profile | Instance Metadata Service (IMDSv2) |
| ECS task | Task role (`taskRoleArn`) | Container credentials endpoint exposed to the task |
| EKS pod | EKS Pod Identity or IAM Roles for Service Accounts (IRSA) | Pod Identity Agent, or a projected service account token exchanged with STS |
| Lambda function | Execution role | Environment variables injected by the Lambda runtime |
| CodeBuild project | Service role | Container credentials endpoint |
| Human user | IAM Identity Center permission set, or S3 Access Grants | Federated sign-in |

The AWS SDKs use a **default credential provider chain** that discovers these sources automatically. Application code should therefore construct an S3 client without passing credentials explicitly. The same container image then runs unchanged on a laptop (using a developer profile), in ECS, in EKS and in CodeBuild.

#### Event sources

S3 can announce changes through two integration channels:

| Channel | Configuration | Destinations |
|---------|---------------|--------------|
| S3 Event Notifications | Per-bucket notification configuration with event types and optional prefix and suffix filters | Lambda, SQS standard queues, SNS standard topics |
| Amazon EventBridge integration | A single bucket-level switch that sends all supported events to the default event bus | Any EventBridge target, filtered by rules |

Both channels provide **at-least-once delivery**. Consumers must therefore be idempotent, a principle introduced in [Chapter 1.7](../unit1/topic7.md).

#### Access abstraction layers

As the number of consumers grows, the bucket policy becomes a bottleneck. S3 therefore offers layers of access abstraction:

```mermaid
flowchart TB
    A["Bucket policy - coarse guardrails"] --> B["Access Points - per application policy and network origin"]
    A --> C["Multi-Region Access Points - one global endpoint over replicated buckets"]
    A --> D["Access Grants - identity to prefix mappings for users and groups"]
    B --> E["Workload role in ECS, EKS or Lambda"]
    C --> E
    D --> F["IAM Identity Center users and groups, or IAM principals"]
```

#### Coordination and integrity primitives

S3 is not a database, but it now provides primitives that allow multiple writers to coordinate safely:

| Primitive | Header | Behaviour |
|-----------|--------|-----------|
| Create only if absent | `If-None-Match: *` | The write succeeds only if no object exists at that key; otherwise HTTP 412 Precondition Failed |
| Compare-and-swap | `If-Match: <ETag>` | The write succeeds only if the current object's ETag matches; otherwise HTTP 412 |
| Conditional read | `If-Match`, `If-None-Match`, `If-Modified-Since` on GET and HEAD | Avoids downloading unchanged data |
| Integrity checksum | `x-amz-checksum-crc32`, `crc32c`, `crc64nvme`, `sha1`, `sha256` | S3 validates the payload and stores the checksum with the object |

#### Performance tiers

S3 now spans a range of latency and access models:

| Offering | Bucket type | Latency profile | Typical use |
|----------|-------------|-----------------|-------------|
| S3 general purpose buckets | General purpose | Tens of milliseconds for first byte | Most application data, data lakes, archives |
| S3 Express One Zone | Directory bucket in one Availability Zone | Single-digit milliseconds | ML training, interactive analytics, high-rate small objects |
| S3 Tables | Table bucket | Optimised for Iceberg query engines | Managed analytical tables |

!!! note "Directory buckets versus general purpose buckets"
    Directory buckets organise keys into real directories rather than a flat namespace, require session-based authentication through `CreateSession` (handled transparently by current SDKs), and have bucket names ending in a zone suffix such as `--use1-az4--x-s3`. Several general purpose features, such as some lifecycle transitions, replication options and storage classes, are not available or behave differently. Verify feature support before migrating a workload.

### AWS Service Deep Dive

#### Purpose

In this part, the purpose of S3 is viewed through its integration role: to provide **a single, secure, scalable, event-driven store that every other component of the platform can rely upon**, so that compute can remain stateless and disposable.

#### Architecture

The following diagram shows a typical cloud-native platform with S3 at its centre.

```mermaid
flowchart LR
    subgraph Clients
        U["Web and mobile users"]
    end
    subgraph Edge
        CF["CloudFront with OAC"]
    end
    subgraph VPC["Application VPC"]
        ECS["ECS service - task role"]
        EKS["EKS pods - Pod Identity"]
        GW["S3 Gateway endpoint"]
    end
    subgraph Serverless
        L["Lambda functions"]
        EB["EventBridge"]
        Q["SQS queue"]
    end
    subgraph Data
        S3["S3 buckets and access points"]
        ICE["S3 Tables - Iceberg"]
    end
    subgraph Analytics
        ATH["Athena and Glue"]
        SM["SageMaker AI"]
    end
    subgraph Delivery
        CP["CodePipeline artefacts"]
        TF["Terraform state"]
    end
    U --> CF --> S3
    ECS --> GW --> S3
    EKS --> GW
    S3 -- "object events" --> EB --> L
    S3 -- "notifications" --> Q --> ECS
    L --> S3
    S3 --> ATH
    ICE --> ATH
    S3 --> SM
    CP --> S3
    TF --> S3
```

The key architectural properties are:

| Property | Consequence for integration |
|----------|-----------------------------|
| Regional service with multi-AZ durability | Compute in any Availability Zone of the Region reads the same data |
| HTTPS API | Any language and any platform can integrate; no drivers or mounts required |
| Private connectivity through Gateway endpoints | Traffic from VPC workloads avoids NAT gateways and the internet |
| Resource-based policies | Cross-account and service-to-service access without sharing credentials |
| Event emission | Pipelines can react to data arrival without polling |

#### Important Features

The foundational data protection and transfer features are:

| Feature | What it provides |
|---------|------------------|
| Versioning | Preserves every version of every object and inserts delete markers instead of destroying data |
| Object Lock | Write-once-read-many retention in Governance mode (privileged users can override) or Compliance mode (nobody, including the root user, can override until the retention period expires); requires versioning |
| Lifecycle policies | Transition objects between storage classes and expire them, including expiring noncurrent versions and aborting incomplete multipart uploads |
| Replication | Cross-Region (CRR) and Same-Region (SRR) asynchronous copy to another bucket, optionally in another account, with optional Replication Time Control; applies to new objects unless S3 Batch Replication handles the backlog; requires versioning |
| Multipart upload | Parallel, resumable uploads of large objects |
| Presigned URLs | Delegate a single operation to an anonymous holder for a bounded time |
| Requester Pays | Shifts request and transfer charges to the caller, useful for publishing large public datasets |
| Transfer Acceleration | Routes uploads through CloudFront edge locations for geographically distant clients |
| Static website hosting | Serves index and error documents from a website endpoint; prefer CloudFront with OAC over a public website endpoint |

The integration and advanced features are:

| Feature | What it provides | Integration relevance |
|---------|------------------|-----------------------|
| Access Points | Named network endpoints with their own policy, optionally restricted to a VPC | Per-microservice or per-team access to shared buckets |
| Multi-Region Access Points | A global hostname that routes requests to the closest healthy replicated bucket | Active-active or active-passive multi-Region applications |
| Access Grants | Maps IAM principals or directory identities to S3 prefixes and vends temporary credentials | Data lake access for analysts and tools like Athena and SageMaker Studio |
| Event Notifications | Object-level events to Lambda, SQS and SNS | Simple, low-latency pipelines |
| EventBridge integration | All bucket events to EventBridge with rich filtering | Multi-consumer, content-based routing, archive and replay |
| Conditional writes | `If-None-Match` and `If-Match` on writes | Locking, leader election, optimistic concurrency |
| Checksums | CRC32, CRC32C, CRC64NVME, SHA-1, SHA-256, including full-object checksums for multipart uploads | End-to-end integrity verification |
| Batch Operations | Managed, audited operations across billions of objects | Re-encryption, re-tagging, copying, restores, backfills |
| Inventory | Scheduled listing of objects and metadata in CSV, ORC or Parquet | Auditing encryption, replication status, and feeding Batch Operations |
| Storage Lens | Organisation-wide usage and activity metrics and recommendations | Cost and data-protection governance |
| S3 Metadata | Automatically maintained, queryable metadata tables for a bucket, stored as S3 Tables | Discovering and querying objects without listing |
| S3 Tables | Table buckets storing Apache Iceberg tables with automatic maintenance | Managed data lake tables |
| S3 Express One Zone | High-performance, single-AZ directory buckets | ML training, shuffle data, low-latency caches |
| Mountpoint for Amazon S3 | A file client that presents a bucket as a local mount, with a CSI driver for Kubernetes | Legacy or file-based tools reading large datasets |
| S3 Object Lambda | Transforms data on GET through a Lambda function behind an Object Lambda Access Point | On-the-fly redaction or format conversion (see availability note) |
| S3 Vectors | Vector buckets and indexes for storing and querying embeddings | Retrieval-augmented generation and semantic search (generally available since December 2025, with up to two billion vectors per index; verify Regional availability) |

!!! warning "S3 Object Lambda availability"
    During 2025 AWS announced that S3 Object Lambda would no longer be available to new customers, while existing customers could continue to use it. Treat Object Lambda as a legacy pattern for new designs. Equivalent designs include transforming data at write time into a derived bucket, serving transformed content through CloudFront with a Lambda-backed origin, or exposing an API Gateway and Lambda endpoint that reads from S3. Verify current status in the AWS documentation before designing around it.

#### Storage classes

| Storage class | Designed for | Minimum storage duration | Minimum billable object size | Retrieval fee | Availability Zones | First-byte latency |
|---|---|---|---|---|---|---|
| S3 Standard | Frequently accessed, general purpose | None | None | None | Three or more | Milliseconds |
| S3 Intelligent-Tiering | Unknown or changing access patterns | None | 128 KiB for auto-tiering eligibility | None; small monitoring fee per object | Three or more | Milliseconds |
| S3 Standard-IA | Infrequent access, rapid retrieval needed | 30 days | 128 KiB | Per GiB retrieved | Three or more | Milliseconds |
| S3 One Zone-IA | Infrequent access, recreatable data | 30 days | 128 KiB | Per GiB retrieved | One | Milliseconds |
| S3 Glacier Instant Retrieval | Archive needing millisecond access | 90 days | 128 KiB | Per GiB retrieved, higher than IA | Three or more | Milliseconds |
| S3 Glacier Flexible Retrieval | Archive, minutes to hours acceptable | 90 days | 40 KiB | Per GiB and per request, varies by retrieval tier | Three or more | Expedited in one to five minutes, Standard in three to five hours, Bulk in five to twelve hours |
| S3 Glacier Deep Archive | Long-term retention, rarely accessed | 180 days | 40 KiB | Per GiB retrieved | Three or more | Standard in around twelve hours, Bulk in up to forty-eight hours |
| S3 Express One Zone | Latency-sensitive, very high request rate | None | None | Per GiB uploaded and retrieved, with lower request charges than S3 Standard | One, in a directory bucket | Single-digit milliseconds |

The Glacier name now refers to storage classes within S3 rather than to a separate service for new designs. Objects in Glacier Flexible Retrieval and Glacier Deep Archive must be **restored** before they can be read, which creates a temporary copy in a readable class for a specified number of days; Glacier Instant Retrieval needs no restore.

!!! danger "Minimum duration charges are a real budget trap"
    An object stored in Standard-IA and deleted after five days is billed for thirty days. An object in Glacier Deep Archive deleted after a week is billed for one hundred and eighty days. Lifecycle rules that transition short-lived data to colder classes can therefore **increase** cost. Always compare the expected object lifetime with the minimum storage duration before writing a transition rule.

```mermaid
graph TD
    A["New object"] --> B{"Access pattern known"}
    B -->|"No"| C["S3 Intelligent-Tiering"]
    B -->|"Yes"| D{"Accessed frequently"}
    D -->|"Yes"| E{"Needs single-digit ms and very high request rate"}
    E -->|"Yes"| F["S3 Express One Zone"]
    E -->|"No"| G["S3 Standard"]
    D -->|"No"| H{"Must be retrievable in milliseconds"}
    H -->|"Yes"| I{"Is the data recreatable"}
    I -->|"Yes"| J["S3 One Zone-IA"]
    I -->|"No"| K["S3 Standard-IA or Glacier Instant Retrieval"]
    H -->|"No"| L{"Acceptable retrieval delay"}
    L -->|"Minutes to hours"| M["Glacier Flexible Retrieval"]
    L -->|"Twelve hours or more"| N["Glacier Deep Archive"]
```

#### The life of an object under versioning and lifecycle rules

The state machine shows why versioning without lifecycle expiry causes unbounded cost growth, and why a delete in a versioned bucket is recoverable.

```mermaid
stateDiagram-v2
    [*] --> CurrentStandard : "PUT object"
    CurrentStandard --> NoncurrentVersion : "PUT same key again"
    NoncurrentVersion --> CurrentStandard : "Restore an older version"
    CurrentStandard --> CurrentInfrequentAccess : "Lifecycle transition after 30 days"
    CurrentInfrequentAccess --> CurrentGlacier : "Lifecycle transition after 90 days"
    CurrentStandard --> DeleteMarkerCurrent : "DELETE without version id"
    DeleteMarkerCurrent --> CurrentStandard : "Remove the delete marker"
    NoncurrentVersion --> PermanentlyDeleted : "NoncurrentVersionExpiration"
    CurrentGlacier --> PermanentlyDeleted : "Expiration rule"
    PermanentlyDeleted --> [*]
```

!!! danger "The delete that is not a delete"
    In a versioned bucket, a `DELETE` without a version identifier does not remove data; it inserts a delete marker and hides the object. The prior versions remain and continue to be billed. To free storage you must delete specific version identifiers, which is exactly what a `NoncurrentVersionExpiration` lifecycle rule automates. This mechanism is simultaneously the strongest protection against accidental deletion and the most common cause of unexplained storage growth.

#### Limitations

| Limitation | Architectural impact |
|------------|----------------------|
| Maximum object size of 5 TiB, and 5 GiB for a single `PUT` without multipart | Large objects must use multipart upload |
| No POSIX semantics: no file locking, no hard links, no atomic rename of a tree | POSIX applications need EFS or EBS |
| Strong consistency applies to object data, not to bucket configuration | Configuration changes can take time to take effect |
| Bucket names are globally unique | Naming conventions must include an account or organisation component |
| Objects are immutable; there is no in-place partial update on general purpose buckets | Append-heavy workloads must write new objects or use a table format such as Iceberg |
| No native rename; a rename is copy plus delete | Directory renames on large prefixes are slow and expensive; design keys that never need renaming |
| Event delivery is at least once and not strictly ordered | Consumers must be idempotent and must not assume ordering |
| Listing is paginated and eventually expensive at very large scale | Use Inventory or S3 Metadata instead of repeated full listings |
| Request rate scales per prefix gradually | Sudden bursts on a new prefix can produce HTTP 503 Slow Down responses |
| Mountpoint is not a POSIX file system | Random writes, in-place edits, file locking and hard links are not supported |
| Event Notifications cannot target FIFO queues or FIFO topics directly | Use EventBridge or an intermediate function if ordering or deduplication is required |

#### Pricing Model and recommendations

S3 cost for integration-heavy architectures is dominated by more than storage. The dimensions are listed below; figures are indicative, as of 2026, and should be verified in the AWS Pricing Calculator.

| Dimension | What drives it | Recommendation |
|-----------|----------------|----------------|
| Storage (GB-month) | Volume, storage class | Lifecycle and Intelligent-Tiering (see [Storage classes](#storage-classes)) |
| Requests | PUT, COPY, POST, LIST cost roughly an order of magnitude more per request than GET | Batch small objects; avoid LIST-based polling |
| Data transfer out | To the internet or across Regions | Serve through CloudFront; keep compute in the same Region |
| NAT gateway processing | Private subnet traffic to S3 without an endpoint | Always add a Gateway endpoint for S3 |
| Management features | Inventory per million objects listed, Storage Lens advanced metrics, Batch Operations per job and per object | Enable where the governance value justifies it |
| S3 Express One Zone | Lower request cost, higher storage cost than S3 Standard | Use as a performance tier, not as bulk storage |
| S3 Tables | Storage, requests, plus monitoring and compaction charges | Compare against self-managed Iceberg maintenance compute |
| KMS | One KMS request per object operation without Bucket Keys | Enable S3 Bucket Keys for SSE-KMS buckets |
| Retrieval | Per GiB for IA and Glacier classes | A cold class accessed often costs more than Standard |
| Replication | Storage in the destination plus inter-Region transfer plus requests | Cross-Region Replication roughly doubles storage cost |
| Per-object management charges | Intelligent-Tiering monitoring, Object Lock, replication and Inventory are charged per object | Small-object-heavy buckets pay a high per-object overhead |

!!! info "Verify pricing before quoting figures"
    Prices differ by Region and change over time. Treat published figures as orders of magnitude: Standard storage on the order of low tens of United States cents per GiB-month, Deep Archive roughly an order of magnitude cheaper, and internet egress on the order of several cents per GiB. Model the workload in the AWS Pricing Calculator before committing to a design.

#### Performance Characteristics

| Characteristic | Typical behaviour |
|----------------|-------------------|
| First-byte latency, general purpose buckets | Tens of milliseconds, variable |
| First-byte latency, S3 Express One Zone | Single-digit milliseconds, consistent |
| Per-connection throughput | Tens to low hundreds of MB/s; aggregate throughput scales with parallel connections |
| Aggregate throughput | Effectively unlimited with enough parallelism across prefixes and connections |
| Request rate | At least 3,500 writes and 5,500 reads per second per partitioned prefix, scaling further as S3 repartitions |

#### Scaling Behaviour

S3 scales without provisioning, but the scaling is **adaptive rather than instantaneous**. When a prefix receives a sustained increase in traffic, S3 splits the underlying index partitions. During the transition, clients may receive HTTP 503 Slow Down responses. Well-behaved clients retry with exponential backoff and jitter, and S3 converges on the new rate. Architects should therefore:

- distribute high-rate keys across multiple prefixes, for example by date and a hash component;
- ramp traffic gradually for large backfills where possible;
- rely on SDK retry modes rather than custom retry loops.

#### Availability

Designed durability and availability for each storage class are compared in [Durability and Availability](#durability-and-availability). Multi-Region Access Points with replication extend the failure domain to several Regions, with availability depending on the configuration. Single-AZ offerings trade resilience for cost or latency. Data that cannot be regenerated should not live solely in a single-AZ bucket.

#### Security Features

| Feature | Purpose |
|---------|---------|
| Object Ownership: bucket owner enforced | Disables ACLs so that policies alone govern access; the default for new buckets |
| Block Public Access | Account and bucket level safeguard against public exposure |
| Default encryption | Every new object is encrypted, SSE-S3 by default, SSE-KMS optionally |
| Access Point and VPC endpoint policies | Restrict access by network origin |
| Resource Control Policies (AWS Organizations) | Organisation-wide ceilings on what can be done to S3 resources, regardless of the caller's account |
| Condition keys | `aws:SourceVpce`, `aws:PrincipalOrgID`, `s3:x-amz-server-side-encryption`, `aws:SecureTransport`, `s3:if-none-match` and others |
| Amazon Macie | Discovers sensitive data such as personal information in buckets |
| GuardDuty S3 Protection and Malware Protection for S3 | Detects suspicious access patterns and scans newly uploaded objects for malware |
| CloudTrail data events and server access logs | Object-level audit trails |
| Object Lock and MFA Delete | Immutable retention, and a second factor for deleting versions or changing versioning state |
| IAM Access Analyzer for S3 | Reports buckets shared outside the account or organisation |

#### Service Limits

The following values are indicative, as of 2026. Verify them in Service Quotas and the S3 documentation.

| Limit | Indicative value |
|-------|------------------|
| General purpose buckets per account | 10,000 by default, adjustable upwards |
| Directory buckets per account | 100 by default, adjustable |
| Table buckets per Region per account | Small default quota, adjustable |
| Maximum object size | 50 TB since December 2025 (previously 5 TB), in all commercial Regions; objects above 5 GB require multipart upload |
| Maximum single PUT | 5 GB; use multipart upload above this |
| Parts per multipart upload | 10,000 |
| Part size range | 5 MiB to 5 GiB; the last part may be smaller |
| Objects per bucket | Unlimited |
| Lifecycle rules per bucket | 1,000 |
| Access points per Region per account | 10,000 by default, adjustable |
| Event notification configurations | Rules must not overlap in event type and prefix or suffix for the same destination set |
| Object tags | 10 per object |
| Bucket policy size | 20 KB |

!!! tip "Why the bucket policy size limit matters"
    The 20 KB policy size limit is one of the main reasons Access Points exist. A shared data lake bucket with dozens of consumer statements quickly exhausts it. Delegating access control to Access Points gives each consumer its own policy document.

### Important AWS Terminology

Bucket, object, key, prefix, delimiter, versioning, storage class, lifecycle policy, multipart upload and presigned URL are defined in [Buckets, objects, keys and prefixes](#buckets-objects-keys-and-prefixes).

| Term | Meaning |
|------|---------|
| Delete marker | The placeholder version created when an object is deleted in a versioned bucket |
| Noncurrent version | Any object version that is not the latest; billed and expirable by lifecycle rules |
| Block Public Access | Account and bucket level control that overrides policies and ACLs to prevent public exposure |
| Object Lock | Write-once-read-many retention control in Governance or Compliance mode, with retention periods or legal holds |
| Object Ownership | Setting that disables ACLs and makes the bucket owner the owner of all objects |
| Cross-Region Replication | Asynchronous replication of objects to a bucket in another Region |
| Replication Time Control | Feature adding a fifteen-minute replication Service Level Agreement and replication metrics |
| Requester Pays | Bucket setting that charges request and transfer costs to the requester |
| Transfer Acceleration | Upload path through CloudFront edge locations for distant clients |
| Erasure coding | Technique splitting data into data and parity fragments so the original is recoverable from a subset |
| Partition splitting | Automatic division of a hot key range in the S3 index across more servers |
| Gateway VPC endpoint | Route-table-based private path from a VPC to S3 or DynamoDB with no additional charge |
| Interface VPC endpoint | PrivateLink elastic network interface providing a private path to an AWS service, reachable from on-premises |
| SSE-S3, SSE-KMS, DSSE-KMS, SSE-C | The server-side encryption options for S3 objects (see [Security Features](#security-features)) |
| S3 Bucket Key | A short-lived bucket-level key that reduces KMS request volume for SSE-KMS |
| Task role | The IAM role an ECS task assumes for application calls to AWS APIs, distinct from the task execution role used by the ECS agent |
| Task execution role | The IAM role used by ECS to pull images and write logs; it should not carry application S3 permissions |
| EKS Pod Identity | An EKS feature that associates a Kubernetes service account with an IAM role through an association, using the Pod Identity Agent |
| IRSA | IAM Roles for Service Accounts; pods exchange a projected OIDC token for role credentials through `AssumeRoleWithWebIdentity` |
| Mountpoint for Amazon S3 | An open-source file client that mounts a bucket as a local directory, optimised for high-throughput sequential access |
| Mountpoint CSI driver | A Kubernetes CSI driver that exposes Mountpoint as persistent volumes for pods |
| Access Point | A named endpoint attached to a bucket, with its own access policy and optional VPC restriction |
| Access Point alias | An automatically generated bucket-style name for an access point, usable wherever a bucket name is expected |
| Multi-Region Access Point | A global endpoint that routes S3 requests across buckets in multiple Regions, with failover controls |
| S3 Access Grants | A service that maps identities to S3 locations and issues scoped temporary credentials through `GetDataAccess` |
| Access Grants instance | The container for grants, one per Region per account, optionally linked to IAM Identity Center |
| Event Notification | A per-bucket configuration that sends selected event types to Lambda, SQS or SNS |
| Recursive loop detection | A Lambda safeguard that detects and stops invocation loops involving supported services, including S3 |
| Conditional write | A PUT or multipart completion that succeeds only if a precondition on the current object holds |
| ETag | An identifier of an object version's content, used as the comparison value in `If-Match` |
| Full-object checksum | A checksum covering the entire object, including multipart uploads, as opposed to a checksum of checksums of parts |
| Batch Operations job | A managed job that performs one operation across all objects listed in a manifest |
| Manifest | The list of objects for a Batch Operations job, supplied as CSV, an Inventory report, or generated from filters |
| S3 Inventory | A scheduled report of objects and their metadata written to a destination bucket |
| Storage Lens | An analytics feature that aggregates storage usage and activity metrics across accounts and Regions |
| Directory bucket | A bucket type used by S3 Express One Zone with a hierarchical namespace and session authentication |
| Table bucket | A bucket type that stores Apache Iceberg tables managed by S3 Tables |
| Apache Iceberg | An open table format that adds schemas, snapshots, ACID commits and time travel on top of files in object storage |
| Origin Access Control (OAC) | The CloudFront mechanism that signs origin requests to S3 so that the bucket can remain private |
| Resource Control Policy (RCP) | An AWS Organizations policy that sets maximum permissions on resources, including S3 buckets, across accounts |
| Terraform S3 backend | The Terraform configuration that stores state in S3, with native lock files in recent Terraform versions |

### Configuration Options

#### Bucket configuration

| Setting | Options | Architectural guidance |
|---|---|---|
| Storage class | Standard, Intelligent-Tiering, Standard-IA, One Zone-IA, Glacier Instant, Glacier Flexible, Deep Archive, Express One Zone | Set at upload for known patterns; use Intelligent-Tiering when patterns are unknown |
| Versioning | Disabled, Enabled, Suspended | Enable for any bucket holding non-reproducible data; pair with lifecycle expiry of noncurrent versions |
| Default encryption | SSE-S3, SSE-KMS, DSSE-KMS | SSE-S3 for general data; SSE-KMS with Bucket Keys where audit and key control are required |
| Block Public Access | Four independent toggles at account and bucket level | Enable all four unless a documented public-hosting requirement exists |
| Object Ownership | ACLs disabled (bucket owner enforced), or ACLs enabled | Keep ACLs disabled; use policies exclusively |
| Lifecycle rules | Transition, expiration, noncurrent expiration, abort incomplete multipart uploads | Always include an abort-incomplete-multipart rule |
| Replication | Cross-Region, Same-Region, with or without Replication Time Control | Replicate to a separate account for ransomware resilience |
| Object Lock | Governance or Compliance mode, with retention period or legal hold | Compliance mode is irreversible; test in a sandbox first |
| Transfer Acceleration | Enabled or disabled | Only worthwhile for geographically distant, large uploads |
| Requester Pays | Enabled or disabled | Useful for publishing large public datasets |
| Static website hosting | Enabled with index and error documents | Prefer CloudFront with Origin Access Control over public website endpoints |

A production bucket typically has versioning enabled, Block Public Access fully on, default encryption with Bucket Keys, a bucket policy denying non-TLS requests, a lifecycle rule that expires noncurrent versions after a retention window and aborts incomplete multipart uploads after a few days, server access logging or CloudTrail data events directed to a separate logging bucket, and replication to a second Region or a separate account for critical data.

#### Workload access configuration

| Option | Where it is configured | Guidance |
|--------|------------------------|----------|
| ECS task role | `taskRoleArn` in the task definition | One role per service; prefix-scoped data permissions |
| EKS Pod Identity association | EKS API: cluster, namespace, service account, role | Preferred for new EKS clusters; no OIDC provider per cluster required |
| IRSA | Service account annotation `eks.amazonaws.com/role-arn` plus an OIDC trust policy | Still widely used, and required on some platforms outside EKS |
| Lambda execution role | Function configuration | One role per function; avoid shared roles |
| VPC endpoint | Gateway endpoint on private subnet route tables | Mandatory for private subnets; attach an endpoint policy |

#### Event configuration

| Option | S3 Event Notifications | EventBridge integration |
|--------|------------------------|-------------------------|
| Enablement | Notification configuration per destination | One bucket-level setting |
| Filtering | Event type, key prefix, key suffix | Any field: key patterns, size, source IP, requester, bucket, with EventBridge operators |
| Destinations | Lambda, SQS standard, SNS standard | Any EventBridge target, up to five per rule, many rules |
| Multiple consumers on the same events | Not with overlapping filters; fan out through SNS | Native, through multiple rules |
| Archive and replay | No | Yes |
| Cross-account delivery | Through resource policies on the destination | Through event bus policies |
| Latency | Typically seconds or less | Typically slightly higher; still near real time |
| Cost | No additional S3 charge | EventBridge charges per event for events delivered to the default bus from S3 (verify current pricing) |

!!! tip "Choosing an event channel"
    Use Event Notifications for a single, simple consumer where the lowest latency and cost matter, for example one Lambda function creating thumbnails. Use EventBridge when several teams consume the same events, when filtering needs more than prefix and suffix, when replay is valuable, or when events must cross account boundaries in an event-driven architecture as described in [Chapter 1.7](../unit1/topic7.md).

#### Access control configuration

| Mechanism | Best for | Key settings |
|-----------|----------|--------------|
| Bucket policy | Guardrails: TLS only, encryption requirements, organisation boundary, delegation to access points | `aws:SecureTransport`, `aws:PrincipalOrgID`, `s3:DataAccessPointAccount` |
| Access Point | One application or team | Network origin `VPC` or `Internet`, access point policy, Block Public Access settings |
| Multi-Region Access Point | Multi-Region applications | Buckets in each Region, replication rules, routing and failover configuration |
| Access Grants | Many human users and groups over data lake prefixes | Locations, grants with READ, WRITE or READWRITE, IAM Identity Center link |
| Resource Control Policy | Organisation-wide data perimeter | Deny access from principals outside the organisation |

#### Integrity and concurrency options

| Option | Values | Guidance |
|--------|--------|----------|
| Checksum algorithm | CRC32, CRC32C, CRC64NVME, SHA-1, SHA-256 | CRC-based algorithms are fastest; current SDKs compute a CRC checksum by default on uploads |
| Checksum type for multipart | Composite or full object | Full-object checksums allow comparison with a checksum calculated locally over the whole file |
| Conditional create | `If-None-Match: *` | Prevents overwriting existing keys |
| Conditional update | `If-Match: <ETag>` | Optimistic concurrency on a known version |
| Enforcing conditional writes | Bucket policy conditions `s3:if-none-match` and `s3:if-match` | Rejects unconditional writes from any client |

#### SDK and transfer configuration

| Setting | Purpose | Typical choice |
|---------|---------|----------------|
| Retry mode | Controls retry behaviour for throttling and transient errors | `standard` for most workloads; `adaptive` for clients that frequently hit throttling |
| Maximum attempts | Upper bound on retries | 3 to 10 depending on latency tolerance |
| Transfer manager part size | Size of each multipart part | 8 to 64 MiB for general workloads |
| Transfer concurrency | Parallel part uploads or ranged downloads | Tune to network bandwidth and CPU |
| CRT-based client | High-performance native transfer client | Use for large objects and high throughput on large instances |
| Connection pool size | Reuse of TCP and TLS connections | Increase for highly parallel workloads |

### AWS Best Practices

- **Operational Excellence:** Define buckets, notifications, access points and policies only through IaC, and use Storage Lens and Inventory reports for fleet visibility.
- **Security:** Give workloads task roles, Pod Identity or execution roles instead of access keys, keep ACLs disabled, enforce TLS and use Access Points for per-application policies.
- **Security:** Build a data perimeter with resource control policies, SCPs and VPC endpoint policies, and enable Macie and GuardDuty S3 Protection.
- **Reliability:** Buffer S3 events in SQS with dead-letter queues, make consumers idempotent, enable versioning and replicate critical data to another Region or account.
- **Performance Efficiency:** Distribute keys across prefixes, use parallel multipart transfers and serve hot content through CloudFront.
- **Cost Optimization:** Add Gateway endpoints to remove NAT charges, enable Bucket Keys and set lifecycle rules for incomplete multipart uploads and noncurrent versions.
- **Sustainability:** Store data once and share it through access points, and use columnar formats such as Parquet to reduce the data scanned.

### Industry Use Cases

| Industry | Use case | Integration pattern |
|----------|----------|---------------------|
| Media and streaming | Uploaded videos trigger transcoding pipelines and are delivered globally | S3 events, Step Functions, AWS Elemental MediaConvert, CloudFront |
| Financial services | Daily trade files from partners are validated, archived with Object Lock, and loaded into the data warehouse | SFTP through AWS Transfer Family, EventBridge, Glue, Redshift |
| Healthcare | Medical images are stored with strict access and scanned for sensitive data | Access Points, Macie, CloudTrail data events, Lake Formation |
| E-commerce | Product images uploaded by sellers are scanned, resized and served | Presigned uploads, GuardDuty Malware Protection, Lambda, CloudFront |
| Machine learning and generative AI | Training datasets, checkpoints, model artefacts, and knowledge-base documents for retrieval-augmented generation | Express One Zone, Mountpoint CSI on EKS, SageMaker AI, Bedrock Knowledge Bases, S3 Vectors |
| Software delivery | Build artefacts, container build caches, and infrastructure state | CodePipeline, CodeBuild, Terraform S3 backend |
| Internet of Things | Devices stream telemetry that lands in partitioned Parquet files | Amazon Data Firehose, S3 Tables, Athena |
| Education | Learning management systems store coursework submissions and media | Presigned uploads, lifecycle transitions, CloudFront |

### Advantages

| Advantage | Explanation |
|-----------|-------------|
| Stateless compute | Because S3 holds durable data, ECS tasks, pods and functions can be replaced, scaled to zero, or moved between Availability Zones without data migration |
| Universal integration | Nearly every AWS analytics, ML, delivery and security service reads from or writes to S3 natively, which removes custom connectors |
| Event-driven by design | Object events turn storage into a trigger, allowing pipelines to react within seconds without polling |
| Fine-grained, layered access | IAM, bucket policies, Access Points, Access Grants, Lake Formation and RCPs allow access to be delegated safely to many teams |
| Elastic throughput | Aggregate throughput grows with parallelism; no capacity planning is required for most workloads |
| Coordination primitives | Conditional writes provide locking and compare-and-swap without an additional database |
| Integrity guarantees | End-to-end checksums detect corruption between client and storage |
| Open formats | Iceberg and Parquet on S3 allow multiple engines to share data without lock-in to one query engine |
| Governance at scale | Batch Operations, Inventory and Storage Lens make billions of objects manageable |

### Limitations

| Limitation | Trade-off and mitigation |
|------------|--------------------------|
| Not a file system | Mountpoint helps for read-heavy workloads, but applications needing POSIX semantics should use EFS or EBS |
| Not a database | Conditional writes allow simple coordination, but queries, secondary indexes and transactions across objects require DynamoDB, Aurora or Iceberg tables |
| Latency on general purpose buckets | Tens of milliseconds is unsuitable for chatty, per-request lookups; use caching or Express One Zone |
| At-least-once, unordered events | Consumers carry the burden of idempotency and ordering logic |
| Policy complexity | Many overlapping policy types make access errors hard to diagnose |
| Request costs for small objects | Architectures producing many tiny objects can cost more in requests than storage |
| Regional scope | Multi-Region designs require replication and routing, with replication lag and conflict considerations |
| Evolving feature set | Some features, such as Object Lambda, change availability; designs should isolate feature-specific code |

### Summary

Amazon S3 is far more than a place to keep files. In a cloud-native architecture it is ==the shared, durable data plane that allows every other component to remain stateless==. This part examined S3 from the perspective of integration:

| Theme | Architectural lesson |
|-------|----------------------|
| Workload identity | ECS task roles, EKS Pod Identity or IRSA, and Lambda execution roles deliver short-lived credentials; no workload should hold access keys |
| Events | S3 Event Notifications suit simple single consumers; EventBridge suits multi-consumer, filtered, replayable, cross-account designs; every consumer must be idempotent |
| Loop safety | Separate input and output locations; Lambda loop detection is a safety net, not a design |
| Access at scale | Bucket policies set guardrails, Access Points delegate per application, Multi-Region Access Points route globally, Access Grants map people and groups to prefixes |
| Coordination and integrity | Conditional writes provide create-if-absent and compare-and-swap; checksums provide end-to-end integrity |
| Performance | Spread keys across prefixes, parallelise transfers, reuse clients, cache at the edge, and choose Express One Zone for latency-critical ML and analytics |
| Analytics | S3 with Glue, Athena, Lake Formation and S3 Tables forms a governed, open-format data lake |
| Delivery | S3 stores CI/CD artefacts and Terraform state, and serves front ends privately through CloudFront OAC |
| Governance | Batch Operations, Inventory, Storage Lens, Macie and GuardDuty make large estates auditable and safe |
| Troubleshooting | AccessDenied is resolved by walking the layers: organisation policies, endpoint policies, identity, resource policies, Block Public Access and KMS |

!!! tip "The architect's summary"
    Design S3 integrations around three questions. Who is calling, and with which short-lived identity? How does the consumer learn that data has changed, and what happens if it learns twice? Which policy layers must all agree for the call to succeed?

## Block Storage with Amazon EBS

!!! note "EBS in one paragraph"
    An EBS volume is network-attached block storage that lives in one Availability Zone and attaches to EC2 instances in that zone. Volumes are replicated within the zone, can be resized and retuned online with Elastic Volumes, and are backed up with incremental snapshots stored regionally. Capacity is billed as **provisioned, not consumed**: a 500 GiB volume holding 10 GiB costs the same as a full one, and volumes can grow but never shrink.

### Definition

Amazon EBS provides persistent, zonal block storage volumes for EC2 instances, and therefore for every compute platform built on EC2 capacity, including ECS on EC2, ECS on Fargate, EKS managed node groups, Karpenter-provisioned nodes and EKS Auto Mode.

From an integration perspective, EBS is best defined as **durable, low-latency, single-writer storage whose lifecycle can be bound to an instance, a task, a pod or an independent resource**.

| Integration context | How EBS participates |
|---------------------|----------------------|
| EC2 and Auto Scaling groups | Root and data volumes defined by AMIs and launch templates |
| Amazon EKS | Persistent volumes provisioned dynamically by the EBS CSI driver |
| Amazon ECS | Task-attached volumes configured at deployment for Fargate and EC2 tasks |
| Image pipelines | AMIs are EBS snapshots plus metadata, built by EC2 Image Builder |
| Backup and recovery | Snapshots automated by Data Lifecycle Manager and AWS Backup |
| Resilience engineering | EBS I/O disruptions injected by AWS Fault Injection Service |
| Data services | Self-managed databases, search engines, message brokers and caches |

### Why This Service or Concept Exists

- **Stateful workloads on stateless platforms:** Databases, search clusters, message brokers and build caches still need durable state even when they run in disposable containers.
- **Data must outlive and follow the workload:** A crashed pod or replaced task must not lose its data, and a rescheduled pod must reattach the same volume on a new node.
- **Instance store and EFS fall short:** Instance store loses its data when the instance stops or is replaced, and EFS provides sharing but not the low-latency block semantics that databases expect.
- **Programmable lifecycle:** The EBS API lets orchestrators create, attach, detach, snapshot and delete volumes automatically, which the EBS CSI driver and the ECS EBS integration build on.
- **Automated protection:** Data Lifecycle Manager, AWS Backup, the Snapshots Archive tier and Recycle Bin replace unreliable manual snapshot scripts.
- **State is isolated, not eliminated:** A cloud-native platform keeps state in a few well-understood components with automated provisioning, backup and recovery.

### Core Concepts

#### Volume types

| Type | Media | Size range | Max IOPS per volume | Max throughput per volume | IOPS model | Best-suited workloads |
|---|---|---|---|---|---|---|
| gp3 | SSD | 1 GiB to 64 TiB | 80,000 | 2,000 MiB/s | 3,000 IOPS and 125 MiB/s baseline included, provisioned independently of size | Default for boot volumes, most databases, application servers |
| gp2 | SSD | 1 GiB to 16 TiB | 16,000 | 250 MiB/s | 3 IOPS per GiB, burst to 3,000 for small volumes | Legacy general purpose; superseded by gp3 |
| io1 | SSD | 4 GiB to 16 TiB | 64,000 | 1,000 MiB/s | Provisioned, up to 50 IOPS per GiB | Legacy high-performance; superseded by io2 |
| io2 Block Express | SSD | 4 GiB to 64 TiB | 256,000 | 4,000 MiB/s | Provisioned, up to 1,000 IOPS per GiB | Mission-critical relational databases, SAP HANA, Oracle |
| st1 | HDD | 125 GiB to 16 TiB | 500 | 500 MiB/s | Throughput-oriented with burst credits | Big data, log processing, data warehouses, sequential reads |
| sc1 | HDD | 125 GiB to 16 TiB | 250 | 250 MiB/s | Lowest cost, throughput-oriented | Cold data accessed a few times per month |

!!! tip "gp3 is almost always better than gp2"
    gp3 costs roughly twenty percent less per GiB than gp2, includes 3,000 IOPS and 125 MiB/s regardless of size, and lets you provision IOPS and throughput independently of capacity. Under gp2, obtaining 3,000 sustained IOPS required a 1,000 GiB volume. Migrating gp2 to gp3 is an online `ModifyVolume` operation and one of the most reliable cost optimisations in a mature account.

#### IOPS, throughput and burst credits

| Concept | Meaning |
|---------|---------|
| IOPS | Input/output operations per second, quoted against a 16 KiB I/O on SSD types and a 1 MiB I/O on HDD types; EBS counts each SSD operation up to 256 KiB as one IOPS, so a single 1,024 KiB request counts as four |
| Throughput | Bytes per second transferred: IOPS multiplied by I/O size, up to the volume and instance ceilings |
| Burst bucket | The credit mechanism that lets gp2, st1 and sc1 exceed baseline performance for limited periods; sustained load exhausts the credits and performance drops abruptly to baseline |
| Provisioned performance | gp3, io1 and io2 deliver consistent provisioned performance with no credit mechanism |
| EBS-optimised instance | An instance whose network capacity for EBS traffic is dedicated and separate from general traffic; all current-generation instances are EBS-optimised by default |
| Elastic Volumes | Online changes to size, type, IOPS and throughput while the volume stays attached; the file system must then be grown with `growpart` and `xfs_growfs` or `resize2fs` |
| Multi-Attach | io1 and io2 volumes can attach to up to sixteen Nitro-based instances in the same Availability Zone; there is no coordination, so a cluster-aware file system is mandatory |

Scaling is **vertical and explicit**: EBS never scales automatically. Architects monitor `VolumeQueueLength`, `BurstBalance` and throughput metrics and adjust deliberately. SSD types are IOPS devices and HDD types are throughput devices; HDD types perform poorly for small random I/O.

#### Instance store versus EBS

**Instance store** is NVMe or SSD storage physically attached to the host serving an EC2 instance. It offers the highest possible I/O performance because there is no network in the path, but its data is **ephemeral**: it is lost when the instance stops, hibernates or terminates, and when the underlying hardware fails. It is not a durable storage service and has no snapshot mechanism. EBS, by contrast, persists independently of the instance.

!!! danger "Instance store data loss is a design property, not a failure"
    Architects use instance store deliberately for scratch space, caches, temporary shuffle data in Spark, or replicated distributed databases such as Cassandra that maintain their own redundancy across nodes. Placing a single-copy production database on instance store is a design error, not bad luck.

#### Lifecycle binding

The most important design question for any EBS volume is **what its lifecycle is bound to**.

| Binding | Example | Deleted when |
|---------|---------|--------------|
| Instance | Root volume in a launch template with `DeleteOnTermination: true` | The instance terminates |
| Task | ECS task volume with a termination policy that deletes on task stop | The ECS task stops |
| Persistent volume claim | EKS PVC bound to a PV with `reclaimPolicy: Delete` | The PVC is deleted |
| Retained persistent volume | PV with `reclaimPolicy: Retain` | An operator deletes it explicitly |
| Independent resource | A data volume created by IaC and attached to an instance | IaC destroys it |

#### Zonal affinity

An EBS volume exists in exactly one Availability Zone. Every orchestrator that uses EBS must therefore schedule the consuming workload into the same zone. This constraint shapes the entire design of stateful services on AWS:

```mermaid
flowchart LR
    subgraph AZa["Availability Zone us-east-1a"]
        N1["Node 1"]
        V1["EBS volume data-db-0"]
    end
    subgraph AZb["Availability Zone us-east-1b"]
        N2["Node 2"]
    end
    P["Pod db-0"] --> N1
    N1 --- V1
    P -. "cannot reschedule to" .-> N2
```

If node 1 fails and no capacity exists in `us-east-1a`, the pod remains Pending, even if `us-east-1b` has ample capacity. Stateful designs must provide capacity in each zone that holds volumes and must achieve cross-zone resilience through application-level replication or snapshot-based recovery.

#### Container Storage Interface on Kubernetes

Kubernetes separates storage requests from storage implementation:

| Object | Owner | Purpose |
|--------|-------|---------|
| StorageClass | Platform team | Describes a class of storage: driver, parameters, binding mode, expansion and reclaim policy |
| PersistentVolumeClaim (PVC) | Application team | Requests storage of a size and access mode from a StorageClass |
| PersistentVolume (PV) | Created dynamically by the driver | Represents one EBS volume |
| VolumeSnapshotClass | Platform team | Describes how snapshots are taken |
| VolumeSnapshot and VolumeSnapshotContent | Application team and driver | Represent one EBS snapshot |
| VolumeAttributesClass | Platform team | Describes modifiable performance attributes such as IOPS and throughput for supported drivers |
| CSINode | Driver | Reports how many volumes a node can attach |

The EBS CSI driver has two components: a controller Deployment that calls EC2 APIs to create, attach, modify and snapshot volumes, and a node DaemonSet that formats and mounts devices on each node.

```mermaid
sequenceDiagram
    participant Dev as Application team
    participant API as Kubernetes API server
    participant Sch as Scheduler
    participant Ctl as EBS CSI controller
    participant EC2 as EC2 API
    participant Node as EBS CSI node plugin
    Dev->>API: Create StatefulSet with volumeClaimTemplates
    API->>Sch: Pod db-0 pending with unbound PVC
    Sch->>API: Select node in us-east-1a
    API->>Ctl: Provision PVC in zone us-east-1a
    Ctl->>EC2: CreateVolume gp3 encrypted
    Ctl->>EC2: AttachVolume to selected node
    Node->>Node: Format if empty and mount into pod
    Node-->>API: Pod db-0 running
```

#### Volume binding modes

| Mode | Behaviour | Consequence |
|------|-----------|-------------|
| `Immediate` | The volume is created as soon as the PVC is created | The zone may be chosen before the pod is scheduled, causing an unschedulable pod |
| `WaitForFirstConsumer` | The volume is created only after the scheduler selects a node | The volume is created in the node's zone; recommended for EBS |

#### ECS task-attached EBS volumes

For ECS, the task definition declares a volume with `configuredAtLaunch: true`, and the actual EBS parameters are supplied when the task is launched: in the service definition for services, or in `RunTask` for standalone tasks. This separates the reusable application definition from environment-specific storage sizing.

| Element | Location | Content |
|---------|----------|---------|
| Volume declaration | Task definition | Name and `configuredAtLaunch: true` |
| Mount point | Container definition | Path inside the container |
| Volume configuration | Service or RunTask | Size, type, IOPS, throughput, encryption, KMS key, snapshot ID, file system type, tags, termination policy |
| Infrastructure role | Service or RunTask | IAM role that ECS uses to create and manage the volume |

!!! warning "ECS volumes are per task, not per service identity"
    Each ECS task launched by a service receives its own new volume, created empty or from a snapshot. When the task is replaced, the replacement receives a new volume; data does not migrate to it automatically. ECS task-attached volumes suit scratch space, per-task caches and workloads seeded from a snapshot. They do not provide the stable identity-to-volume mapping that Kubernetes StatefulSets provide.

#### Images and templates

An Amazon Machine Image (AMI) backed by EBS consists of one or more snapshots plus launch metadata. Launch templates reference an AMI and can override block device mappings. Auto Scaling groups launch instances from launch templates. The chain from image build to running fleet is therefore also an EBS chain:

```mermaid
flowchart LR
    IB["EC2 Image Builder pipeline"] --> AMI["AMI - EBS snapshots"]
    AMI --> SSM["SSM parameter latest AMI ID"]
    SSM --> LT["Launch template version"]
    LT --> ASG["Auto Scaling group"]
    ASG --> INST["Instances with encrypted gp3 root volumes"]
    ASG -. "instance refresh" .-> INST
```

#### Snapshot automation and protection

| Mechanism | Scope | Purpose |
|-----------|-------|---------|
| Data Lifecycle Manager (DLM) | EBS snapshots and EBS-backed AMIs | Tag-based schedules, retention, cross-Region and cross-account copy, archive, Fast Snapshot Restore |
| AWS Backup | Many services including EBS | Central backup plans, vaults, vault locks, organisation policies, restore testing |
| Snapshot archive tier | Individual snapshots | Low-cost long-term retention with slower restore |
| Recycle Bin | Snapshots and AMIs | Recovery of deleted resources within a retention period |
| Snapshot Block Public Access | Region | Prevents public sharing of snapshots |

### AWS Service Deep Dive

#### Purpose

Within Unit VI, the purpose of EBS is to give stateful components of a cloud-native system **persistent, performant block storage that orchestrators can manage automatically**, with backup, recovery and security integrated into the platform rather than bolted on.

#### Architecture

The following diagram shows how EBS integrates with the platform layers covered in earlier units.

```mermaid
flowchart TB
    subgraph Build["Image and delivery pipeline"]
        IB["EC2 Image Builder"]
        CP["CodePipeline and Terraform"]
    end
    subgraph Compute["Compute platforms"]
        ASG["Auto Scaling group - launch template"]
        EKS["EKS cluster - EBS CSI driver"]
        ECS["ECS services - task EBS volumes"]
    end
    subgraph Storage["EBS in one Availability Zone"]
        ROOT["Root volumes"]
        PV["Persistent volumes for StatefulSets"]
        TV["Task volumes"]
    end
    subgraph Protection["Regional protection"]
        SNAP["EBS snapshots"]
        DLM["Data Lifecycle Manager"]
        BK["AWS Backup vaults"]
        RB["Recycle Bin"]
        ARC["Snapshot archive tier"]
    end
    subgraph Ops["Operations"]
        CW["CloudWatch metrics and alarms"]
        FIS["Fault Injection Service"]
        KMS["AWS KMS keys"]
    end
    IB --> ASG
    CP --> EKS
    CP --> ECS
    ASG --> ROOT
    EKS --> PV
    ECS --> TV
    PV --> SNAP
    ROOT --> SNAP
    DLM --> SNAP
    BK --> SNAP
    SNAP --> RB
    SNAP --> ARC
    KMS --> PV
    KMS --> SNAP
    CW --> PV
    FIS --> PV
```

The critical architectural facts are:

| Fact | Integration consequence |
|------|-------------------------|
| Volumes are zonal | Stateful workloads are pinned to a zone; capacity planning is per zone |
| Snapshots are regional and stored durably | Snapshots are the mechanism for moving data across zones |
| Snapshots can be copied across Regions and shared across accounts | Disaster recovery and account isolation are built on snapshot copies |
| Attach and detach are EC2 API operations | Orchestrators require IAM permissions for EC2 volume actions |
| Performance depends on both the volume and the instance | Instance EBS bandwidth can cap volume performance |

#### Important Features

| Feature | What it provides | Integration relevance |
|---------|------------------|-----------------------|
| EBS CSI driver add-on | Dynamic provisioning, attachment, resizing, snapshots and modification for Kubernetes | Stateful workloads on EKS |
| EKS Auto Mode block storage | A managed EBS provisioner built into Auto Mode, using the provisioner name `ebs.csi.eks.amazonaws.com` | No self-managed driver on Auto Mode clusters |
| ECS task-attached EBS volumes | Volumes created, attached and optionally deleted per task, configured at deployment | Block storage for Fargate and EC2 tasks |
| Encryption by default | Regional setting that encrypts every new volume and snapshot copy | Compliance without relying on every template author |
| Data Lifecycle Manager | Policy-based snapshot and AMI automation using tags, including default policies | Hands-off backup for fleets |
| AWS Backup | Centralised, cross-service backup with vault lock and organisation-wide policies | Enterprise backup governance |
| Snapshot archive tier | Full-snapshot archival at much lower storage cost | Compliance retention |
| Recycle Bin | Retention rules that keep deleted snapshots and AMIs recoverable, with optional rule lock | Protection against accidental and malicious deletion |
| Time-based snapshot copy | Copies that complete within a requested duration, for predictable recovery point objectives | Cross-Region DR with defined timing (verify current availability) |
| EBS direct APIs | Read and write snapshot blocks, and list changed blocks between snapshots, without creating volumes | Backup software, data migration, forensic analysis |
| Provisioned volume initialisation rate | Volumes created from snapshots can be initialised at a specified rate for predictable readiness (a recent addition; verify availability and pricing) | Faster, predictable restores without Fast Snapshot Restore |
| Attached EBS status check | An EC2 instance status check reporting impairment of attached volumes | Auto Scaling health and alarms |
| Stalled I/O metric | A per-volume CloudWatch check indicating stalled I/O on Nitro instances | Detection of storage impairment |
| Fault Injection Service EBS actions | Pausing I/O on volumes, and in recent versions injecting latency | Resilience testing of stateful services |

#### Limitations

| Limitation | Architectural impact |
|------------|----------------------|
| Single Availability Zone | Zonal failure makes the volume unavailable; cross-zone resilience must come from replication or snapshots |
| Single writer for most volume types | Multi-Attach exists only for io1 and io2 in limited scenarios with cluster-aware file systems |
| Attachment limits per instance | Nodes with many pods using volumes can exhaust attachment slots |
| Snapshot restores are lazily loaded by default | First reads of restored blocks are slower unless initialised or Fast Snapshot Restore is used |
| ECS task volumes are not reattached to replacement tasks | Not suitable for durable per-identity state in ECS services |
| Resizing is one-directional | Volumes can grow but not shrink; shrinking requires data migration |
| Modification cooldown | After an Elastic Volumes modification, further modifications must wait for a cooling period (indicative, about six hours; verify current behaviour) |

#### Pricing Model and recommendations

Figures are indicative, as of 2026; verify in the AWS Pricing Calculator.

| Dimension | Charged for | Recommendation |
|-----------|-------------|----------------|
| Volume storage | Provisioned GiB-month, whether used or not | Right-size and grow online rather than over-provisioning |
| Provisioned IOPS and throughput | gp3 above the included baseline; io1 and io2 IOPS | Start from the gp3 baseline and tune from metrics |
| Snapshot storage, standard tier | Changed blocks stored, GB-month | Retention policies in DLM or AWS Backup |
| Snapshot archive tier | Full snapshot size at a much lower rate, plus retrieval charges; minimum 90-day retention | Only for snapshots retained for months or years |
| Fast Snapshot Restore | Per snapshot per Availability Zone per hour | Enable only for snapshots used for rapid scaling or recovery |
| Cross-Region snapshot copy | Inter-Region data transfer plus storage in the destination | Copy only critical snapshots; use incremental copies |
| EBS direct APIs | Per API request | Suitable for backup tools; account for request volume |
| Recycle Bin | Retained snapshots are charged at their normal storage rate | Keep retention periods proportionate |

!!! tip "The unattached volume problem"
    Volumes left behind by deleted instances, retained PVs and abandoned test environments continue to incur charges. Use `reclaimPolicy: Delete` for disposable environments, `DeleteOnTermination` for root volumes, and AWS Trusted Advisor or Compute Optimizer findings to identify idle volumes.

#### Performance Characteristics

Volume-level limits are given in [Volume types](#volume-types). In integrated systems the most common bottleneck is instead the **instance's EBS bandwidth**, because all EBS traffic of an instance shares its dedicated EBS network path.

| Factor | Explanation |
|--------|-------------|
| Instance EBS bandwidth | Each instance type has maximum EBS bandwidth and IOPS; many smaller sizes have a lower baseline with the ability to burst for a limited time, typically up to 30 minutes at least once every 24 hours |
| Aggregate demand | Several gp3 volumes on one node, or several pods on one node, share the instance's EBS bandwidth |
| Queue depth | Applications must issue enough concurrent I/O to reach provisioned IOPS |
| I/O size | Throughput equals IOPS multiplied by I/O size; large sequential I/O reaches throughput limits before IOPS limits |
| Latency | io2 Block Express offers the most consistent sub-millisecond latency; gp3 provides single-digit millisecond latency for most workloads |
| Restored volumes | Lazy loading from S3 slows first access unless initialised, provisioned-rate initialised or restored with Fast Snapshot Restore |

!!! example "Sizing a node for EBS"
    A database pod requires a gp3 volume with 12,000 IOPS and 700 MiB/s throughput. If it is scheduled onto an instance whose baseline EBS bandwidth is well below 700 MiB/s, the volume will never deliver its provisioned throughput except during bursts. The instance type must be selected using its EBS bandwidth specification, obtainable with `aws ec2 describe-instance-types`, and node selectors or Karpenter NodePool requirements should steer database pods onto suitable instance families.

#### Scaling Behaviour

| Scaling dimension | Mechanism |
|-------------------|-----------|
| Capacity | Elastic Volumes increases size online; the CSI driver exposes this through PVC resizing when `allowVolumeExpansion: true` |
| Performance | Elastic Volumes changes gp3 IOPS and throughput or io2 IOPS online; Kubernetes exposes this through VolumeAttributesClass on supported versions, or through driver-specific annotations |
| Number of volumes | New pods and tasks receive new volumes automatically; limited by per-instance attachment limits and account quotas |
| Fleet scale-out | Auto Scaling groups launch instances with root volumes from the AMI; Fast Snapshot Restore or provisioned initialisation removes first-read latency for large AMIs |

#### Availability

EBS volumes are designed for high availability within one Availability Zone, and io2 volumes are designed for higher durability than other types (see [Durability and Availability](#durability-and-availability)). For the platform:

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Instance failure | Volume survives; must be reattached | Orchestrator reschedules the pod to another node in the same zone |
| Volume impairment | I/O stalls or errors | Status checks, stalled I/O alarms, failover to a replica |
| Availability Zone impairment | Volumes in that zone unavailable | Application replication across zones, or restore from regional snapshots in another zone |
| Regional impairment | All volumes and regional snapshots unavailable | Cross-Region snapshot copies and infrastructure as code for the recovery Region |
| Logical corruption or deletion | Data wrong or gone | Point-in-time snapshots, Recycle Bin, AWS Backup vault lock |

#### Security Features

| Feature | Purpose |
|---------|---------|
| Encryption by default | Enforces encryption of all new volumes in a Region, with a chosen default KMS key |
| Customer managed KMS keys | Control over key policy, rotation and cross-account sharing |
| IAM condition keys | For example `ec2:Encrypted` and `ec2:VolumeType` to deny creation of non-compliant volumes |
| Snapshot Block Public Access | Blocks public sharing of snapshots at Region level |
| Recycle Bin rule lock | Prevents rules from being modified or deleted without an unlock delay |
| AWS Backup Vault Lock | Write-once, read-many retention for backups, including a compliance mode |
| CloudTrail | Records all volume, snapshot and attachment API activity |

#### Service Limits

Values are indicative, as of 2026; verify in Service Quotas and the EBS documentation.

| Limit | Indicative value |
|-------|------------------|
| Storage per volume type per Region | Soft quotas in TiB, adjustable |
| Snapshots per Region | Large soft quota, adjustable |
| Concurrent snapshot copies per destination Region | Limited; adjustable |
| Volume attachments per instance | Depends on instance type; many Nitro instances share a limit across EBS volumes, network interfaces and NVMe instance store volumes, while some newer types have dedicated EBS attachment limits |
| Elastic Volumes modifications | One modification per volume in a cooling period |
| Fast Snapshot Restore | Limited number of snapshots per Region enabled concurrently; credit-based volume creation rate |
| ECS task-attached EBS volumes | One EBS volume per task at the time of writing |
| Maximum volume size | 64 TiB for gp3 and io2 Block Express; 16 TiB for gp2, io1, st1 and sc1 |
| Multi-Attach instances per volume | 16 |
| IOPS to size ratio | 500 to 1 for gp3, 1,000 to 1 for io2 |

### Important AWS Terminology

Volume types, IOPS, throughput, burst credits, Elastic Volumes and Multi-Attach are defined in [Core Concepts](#volume-types).

| Term | Meaning |
|------|---------|
| Volume | An EBS block device created in one Availability Zone and attachable to instances in that zone |
| Snapshot | Incremental, block-level, point-in-time backup of a volume stored in S3 as a Regional resource |
| Lazy loading | Behaviour whereby a volume restored from a snapshot fetches blocks from S3 on first access |
| Fast Snapshot Restore | Feature that pre-warms a snapshot in chosen Availability Zones so restored volumes deliver full performance immediately |
| Nitro card for EBS | Dedicated hardware on the EC2 host that converts NVMe commands into EBS network operations and performs encryption |
| Instance store | Ephemeral block storage physically attached to the host, lost on stop or termination |
| Crash-consistent snapshot | A snapshot equivalent to a power loss; application consistency requires quiescing first |
| Container Storage Interface (CSI) | A standard API that lets orchestrators use storage systems through pluggable drivers |
| EBS CSI driver | The CSI driver, `ebs.csi.aws.com`, that provisions and manages EBS volumes for Kubernetes |
| StorageClass | A Kubernetes object that defines a class of dynamically provisioned storage |
| PersistentVolumeClaim | A request by a workload for storage of a given size and access mode |
| Reclaim policy | Whether a PV and its EBS volume are deleted or retained when the claim is released |
| WaitForFirstConsumer | A binding mode that delays volume creation until a pod is scheduled, ensuring zone alignment |
| Allowed topologies | StorageClass restriction on which zones volumes may be created in |
| StatefulSet | A Kubernetes controller that gives each replica a stable identity and its own PVC |
| volumeClaimTemplates | The StatefulSet section that generates one PVC per replica |
| VolumeSnapshot | A Kubernetes object representing a point-in-time snapshot, backed by an EBS snapshot |
| VolumeAttributesClass | A Kubernetes object describing mutable volume attributes such as IOPS and throughput |
| Snapshot controller | The Kubernetes controller, installed separately or as an EKS add-on, that manages VolumeSnapshot objects |
| configuredAtLaunch | An ECS task definition volume property indicating that the volume is configured at deployment |
| ECS infrastructure role | The IAM role ECS assumes to create and manage task-attached EBS volumes |
| Block device mapping | The part of an AMI or launch template that defines which volumes an instance receives |
| Golden image | A pre-hardened, pre-configured AMI used as the standard base for a fleet |
| EC2 Image Builder recipe | The definition of a parent image, components and block device mappings used to build an image |
| Distribution configuration | Image Builder settings that copy, share and publish images to Regions, accounts and launch templates |
| Instance refresh | An Auto Scaling feature that replaces instances progressively when a launch template changes |
| Data Lifecycle Manager policy | A tag-targeted schedule that creates, copies, archives and deletes snapshots or AMIs |
| Backup plan and backup vault | AWS Backup constructs for schedules and for storing recovery points |
| Recycle Bin retention rule | A rule that keeps deleted snapshots or AMIs recoverable for a defined period |
| EBS direct APIs | APIs for reading, writing and comparing snapshot blocks directly |
| Attached EBS status check | An instance status check that reports impaired attached volumes |
| VolumeStalledIOCheck | A CloudWatch metric that reports whether a volume's I/O has stalled |

### Configuration Options

#### EBS CSI StorageClass parameters

| Parameter | Example | Purpose |
|-----------|---------|---------|
| `provisioner` | `ebs.csi.aws.com` (or `ebs.csi.eks.amazonaws.com` on EKS Auto Mode) | Selects the driver |
| `type` | `gp3`, `io2`, `st1` | Volume type |
| `iops` | `"6000"` | Provisioned IOPS for gp3, io1 and io2 |
| `throughput` | `"250"` | gp3 throughput in MiB/s |
| `iopsPerGB` | `"50"` | io1 and io2 IOPS proportional to size |
| `encrypted` | `"true"` | Encrypt the volume |
| `kmsKeyId` | Key ARN | Customer managed key |
| `csi.storage.k8s.io/fstype` | `ext4`, `xfs` | File system created on first mount |
| `tagSpecification_1` | `"team=payments"` | Tags applied to created volumes |
| `volumeBindingMode` | `WaitForFirstConsumer` | Zone alignment with scheduled pods |
| `allowVolumeExpansion` | `true` | Allow PVC resizing |
| `reclaimPolicy` | `Delete` or `Retain` | Fate of the volume when the PVC is deleted |
| `allowedTopologies` | Zone list | Restrict volume placement |

#### ECS task volume configuration

| Setting | Purpose |
|---------|---------|
| `roleArn` | Infrastructure role, typically with the managed policy `AmazonECSInfrastructureRolePolicyForVolumes` |
| `sizeInGiB` | Volume size; may be omitted when a snapshot defines it |
| `volumeType`, `iops`, `throughput` | Performance configuration |
| `snapshotId` | Seed the volume from a snapshot |
| `encrypted`, `kmsKeyId` | Encryption settings; the Region default applies when encryption by default is enabled |
| `filesystemType` | For example `ext4` or `xfs` on Linux |
| `tagSpecifications` | Tags propagated to the volume |
| `terminationPolicy.deleteOnTermination` | Delete the volume when the task stops, or retain it |

#### Launch template block device mappings

| Setting | Recommendation |
|---------|----------------|
| `VolumeType` | `gp3` for root and general data volumes |
| `Encrypted` and `KmsKeyId` | Always encrypted; use the organisation's key |
| `DeleteOnTermination` | `true` for root volumes in Auto Scaling groups |
| `Iops` and `Throughput` | Baseline unless measured need exists |
| `VolumeSize` | The AMI's snapshot size or larger |

#### Backup automation settings

| Setting | DLM | AWS Backup |
|---------|-----|------------|
| Targeting | Resource tags, or default policies for all volumes and instances | Tags, resource ARNs, or organisation backup policies |
| Schedule | Interval, cron, or retention-based | Cron-based backup rules |
| Retention | Count or age | Lifecycle with transitions to cold storage where supported |
| Cross-Region copy | Yes | Yes |
| Cross-account copy | Yes, with cross-account copy event policies | Yes, across accounts in an organisation |
| Archive tier | Yes, for snapshots | Cold storage transitions for supported resources |
| Application consistency | Pre and post scripts via Systems Manager | Windows VSS; scripts via other mechanisms |
| Immutability | Recycle Bin rule lock | Vault Lock, logically air-gapped vaults |

### AWS Best Practices

- **Operational Excellence:** Define StorageClasses, launch templates, ECS volume configurations and backup policies only in IaC, and tag volumes with owner, application and backup tier.
- **Operational Excellence:** Build AMIs through EC2 Image Builder pipelines and publish the latest AMI IDs through Parameter Store.
- **Security:** Enable encryption by default in every Region, enable Snapshot Block Public Access, and lock Recycle Bin rules and backup vaults.
- **Reliability:** Use `WaitForFirstConsumer` volume binding and spread stateful replicas across Availability Zones.
- **Reliability:** Automate snapshots with Data Lifecycle Manager or AWS Backup, copy critical snapshots across Regions and accounts, and test restores regularly.
- **Performance Efficiency:** Use gp3, tune IOPS and throughput independently, and choose instance types by their EBS bandwidth.
- **Cost Optimization:** Delete unattached volumes, migrate gp2 to gp3, archive long-term snapshots and enable Fast Snapshot Restore only where required.
- **Sustainability:** Avoid over-provisioned volumes and delete obsolete AMIs and snapshots through lifecycle policies.

### Industry Use Cases

| Industry | Use case | Integration pattern |
|----------|----------|---------------------|
| Financial services | Self-managed trading databases with strict latency requirements | io2 Block Express, memory-optimised instances, application replication, locked backup vaults |
| SaaS platforms | Per-tenant databases or search clusters on EKS | StatefulSets, EBS CSI, VolumeSnapshots, Karpenter |
| Media | Rendering nodes with large scratch volumes | ECS tasks with EBS volumes, Spot capacity |
| Healthcare | Regulated imaging archives with long retention | Encrypted volumes, AWS Backup with Vault Lock, snapshot archive |
| E-commerce | Elasticsearch or OpenSearch clusters self-managed on EC2 | gp3 volumes tuned for throughput, cross-zone replicas, DLM snapshots |
| Enterprise IT | Lift-and-shift of commercial applications | Golden AMIs, Auto Scaling groups, AWS Backup, cross-Region DR |
| Continuous integration | Build agents with warm dependency caches | Snapshot-seeded ECS task volumes or pre-baked AMIs |
| Telecommunications | Network functions with persistent state on Kubernetes | EBS CSI, topology-aware scheduling, FIS resilience testing |

### Advantages

| Advantage | Explanation |
|-----------|-------------|
| Persistence independent of compute | Volumes survive instance, task and pod failures, allowing stateful workloads on disposable compute |
| Orchestrator integration | The CSI driver and ECS integration make provisioning, attachment, resizing and snapshotting automatic and declarative |
| Predictable low latency | Block semantics and provisioned performance suit databases and other latency-sensitive systems |
| Online elasticity | Size and performance can be changed without downtime |
| Mature backup ecosystem | DLM, AWS Backup, Recycle Bin, archive tier and direct APIs cover automation, immutability and long-term retention |
| Portable recovery | Regional snapshots can be restored in any zone and copied to other Regions and accounts |
| Security by default | Encryption by default, KMS integration and snapshot public access blocking reduce the risk of misconfiguration |
| Testable resilience | FIS actions allow teams to rehearse storage failures safely |

### Limitations

| Limitation | Trade-off and mitigation |
|------------|--------------------------|
| Zonal scope | Stateful workloads are pinned to a zone; mitigate with application replication or managed services |
| Single writer | Shared access requires EFS, FSx or application-level sharing; Multi-Attach is niche |
| Operational burden of self-managed data services | Backups, upgrades, failover and tuning become the team's responsibility |
| Attachment limits | Dense stateful pods per node can exhaust slots; choose instance types and pod density accordingly |
| Restore latency | Lazy loading delays full performance after restore; initialisation options add cost |
| No shrinking | Over-provisioning is expensive to reverse |
| ECS task volume semantics | Per-task volumes do not follow a logical service identity across replacements |

### Summary

Amazon EBS is the persistence layer that allows stateful systems to run on disposable, orchestrated compute. This part examined how EBS integrates with the platform:

| Theme | Architectural lesson |
|-------|----------------------|
| Lifecycle binding | Decide whether each volume belongs to an instance, a task, a claim or an independent resource, and configure deletion accordingly |
| Zonal affinity | EBS pins workloads to a zone; use `WaitForFirstConsumer`, per-zone capacity and application replication for availability |
| Kubernetes integration | The EBS CSI driver, StorageClasses, StatefulSets, VolumeSnapshots and VolumeAttributesClasses make storage declarative |
| ECS integration | Task-attached volumes are configured at deployment and suit per-task scratch and snapshot-seeded data, not durable per-identity state |
| Images and fleets | Image Builder pipelines produce encrypted golden AMIs consumed by launch templates, Auto Scaling groups and node groups |
| Backup and protection | DLM and AWS Backup automate snapshots; archive tier reduces retention cost; Recycle Bin, Vault Lock and cross-account copies protect against deletion |
| Disaster recovery | Snapshots move data across zones, Regions and accounts; KMS key design determines whether sharing is possible |
| Performance | Instance EBS bandwidth is as important as volume configuration; monitor queue length, latency, burst balances and stalled I/O |
| Resilience | FIS EBS actions validate failover and timeouts before real failures occur |
| Database choice | Managed databases are the default; self-managed databases on EBS are a justified exception |

!!! tip "The architect's summary"
    For every EBS volume in a design, an architect should be able to answer four questions. What owns its lifecycle? In which zone does it live, and what happens when that zone fails? How is it backed up, and where do those backups live? Is the instance capable of delivering the performance the volume promises?

## File Storage with Amazon EFS

!!! note "EFS in one paragraph"
    EFS is a Regional, elastic, POSIX-compliant file system accessed over NFSv4.0/4.1 on TCP port 2049. Clients reach it through a **mount target** (an elastic network interface) in each Availability Zone. Regional file systems store data redundantly across multiple AZs; One Zone file systems store data in a single AZ. It bills for **consumed** rather than provisioned capacity, which makes it economical for sparse or unpredictable data but more expensive than EBS for large, dense, hot data sets.

### Definition

**Amazon EFS as an integration service** is a fully managed, serverless, elastic NFS file system that multiple compute clients (EC2 instances, ECS tasks, EKS pods, Fargate tasks and Lambda execution environments) can mount concurrently, with read-after-write consistency for a given client and close-to-open consistency across clients, as expected from NFS.

Within an AWS architecture, EFS sits in the data tier alongside Amazon S3 and Amazon EBS, but it plays a distinctive role: it is the only one of the three that offers **shared, concurrent, POSIX-semantics access across Availability Zones** to many compute clients at once, without the application having to change its file I/O code.

```mermaid
flowchart LR
    subgraph "Compute tier"
        EKS["EKS pods via EFS CSI driver"]
        ECS["ECS tasks on EC2 or Fargate"]
        LMB["Lambda functions"]
        EC2["EC2 instances and batch jobs"]
    end
    subgraph "VPC networking"
        MT1["Mount target AZ-a"]
        MT2["Mount target AZ-b"]
        MT3["Mount target AZ-c"]
    end
    subgraph "Amazon EFS"
        AP["Access points"]
        FSP["File system policy"]
        FS["Regional file system"]
    end
    EKS --> MT1
    ECS --> MT2
    LMB --> MT3
    EC2 --> MT1
    MT1 --> AP
    MT2 --> AP
    MT3 --> AP
    AP --> FSP --> FS
    FS -.-> REP["EFS Replication to DR Region"]
    FS -.-> BK["AWS Backup vault"]
```

### Why This Service or Concept Exists

- **Software that assumes a shared file system:** Content management systems, containerised legacy applications, ML model stores, build caches and shared notebook home directories expect a hierarchical, mutable, POSIX file system.
- **Rewriting is often uneconomic:** Porting all of these workloads to an object API usually costs more than giving them a file system.
- **Self-managed NFS is a single point of failure:** An NFS server on EC2 lives in one instance and one Availability Zone, with manual patching, capacity planning and backups.
- **EBS attaches to one instance:** Block storage cannot be mounted concurrently by many clients across Availability Zones, whereas EFS can.
- **Serverless compute needs serverless storage:** EFS mounts from ECS on Fargate, Lambda and EKS (through the EFS CSI driver), so the whole stack can remain free of servers to patch.

### Core Concepts

#### File systems, mount targets and the network path

| Concept | Meaning |
|---------|---------|
| File system | The Regional EFS resource, identified by an `fs-` identifier, that contains the directory tree |
| Mount target | An elastic network interface with a private IP address in one subnet of one Availability Zone, protected by a security group; create one in every AZ you serve |
| Access point | An application-specific entry point that enforces a root directory and can override the POSIX user and group of every request (see [Identity on a shared file system](#identity-on-a-shared-file-system)) |
| Lifecycle management | Policies that move files between storage classes based on time since last access, and optionally back on first read |

Clients do not talk to a Regional endpoint. When an instance, task or pod mounts `fs-0123456789abcdef0.efs.ap-south-1.amazonaws.com`, DNS resolves the name to the mount target **in the client's own Availability Zone**. This zone-local resolution keeps NFS traffic inside the zone, minimising latency and avoiding cross-AZ data transfer charges.

```mermaid
graph TD
    subgraph "Availability Zone A"
        A1["EC2 or Pod"] --> M1["Mount Target ENI in AZ A"]
    end
    subgraph "Availability Zone B"
        A2["EC2 or Pod"] --> M2["Mount Target ENI in AZ B"]
    end
    subgraph "Availability Zone C"
        A3["EC2 or Pod"] --> M3["Mount Target ENI in AZ C"]
    end
    M1 --> E["EFS Distributed Storage across three AZs"]
    M2 --> E
    M3 --> E
```

!!! warning "The most common EFS failure to diagnose"
    A mount that hangs and eventually times out is almost always a security group problem or a missing mount target. The mount target's security group must allow inbound TCP 2049 from the client's security group, and a mount target must exist in the client's Availability Zone. If either is missing, the NFS client retries silently until it times out, producing no useful error.

#### Throughput modes, performance modes and elastic capacity

EFS has no provisioned size: space is allocated as files are written and released as they are deleted, and billing follows measured consumption. This removes resizing, free-space monitoring and emergency expansion from operations.

| Setting | Options | Behaviour |
|---------|---------|-----------|
| Throughput mode | Elastic | Measures demand continuously and adjusts throughput automatically, billing for data read and written; the recommended default |
| | Provisioned | Fixes a throughput level independent of stored size, billed per MiB/s-month |
| | Bursting | Baseline throughput scales at roughly 50 KiB/s per GiB stored, with burst credits that accumulate below baseline and deplete above it |
| Performance mode | General Purpose | Lowest per-operation latency; correct for nearly all workloads |
| | Max I/O | Raises the aggregate parallel throughput ceiling at the cost of higher latency; legacy for most designs |

!!! danger "The small file system in Bursting mode"
    Because Bursting ties baseline throughput to stored size, a small file system can exhaust its credits and become dramatically slower, a classic and confusing production incident. Elastic throughput avoids this.

#### Storage classes

| Class | Availability Zone scope | Relative storage price | Access charge | Intended use |
|---|---|---|---|---|
| EFS Standard | Multiple AZs | Highest | None | Active working set |
| EFS Infrequent Access | Multiple AZs | Substantially lower | Per GiB read and written | Files not accessed for a configured period |
| EFS Archive | Multiple AZs | Lowest of the multi-AZ classes | Higher per GiB access charge | Files accessed a few times per year |
| EFS One Zone | Single AZ | Lower than the Standard equivalent | None | Development, test and recreatable data |
| EFS One Zone-IA | Single AZ | Lowest overall | Per GiB access charge | Cold, recreatable, single-zone data |

#### Mount options

Common Linux mount options include `nfsvers=4.1`, `rsize=1048576`, `wsize=1048576`, `hard`, `timeo=600` and `retrans=2`; the `efs-utils` helper applies suitable defaults. The `hard` option makes I/O retry indefinitely rather than return errors, which preserves integrity but can hang processes if the file system becomes unreachable, an important trade-off to state in a design review. A plain `mount -t nfs4` works but transmits data unencrypted; `mount -t efs -o tls,iam` adds TLS and IAM authorisation.

#### Consistency semantics that matter to application designers

EFS implements NFSv4.1 semantics. Two properties shape how applications must be written:

- **Close-to-open consistency**: when one client closes a file and another client subsequently opens it, the second client sees the data written by the first. While both hold the file open, the second client may see stale cached data.
- **Advisory locking**: NFS byte-range locks (`fcntl`/`flock` mapped to NFSv4 locks) work across clients, but only if every writer uses them. EFS does not enforce mandatory locking.

!!! warning "EFS is not a database"
    Running SQLite, or a database engine that expects local-disk fsync latency, on EFS across several writers is a frequent cause of corruption and poor performance. Shared file systems suit content, artefacts and models; transactional state belongs in RDS, Aurora or DynamoDB.

#### Identity on a shared file system

Every NFS request carries a numeric POSIX user ID (uid) and group ID (gid). EFS authorises file access using standard POSIX permission bits against those numbers. In a multi-tenant container platform this creates a problem: one container running as uid 0 (root) could read every other tenant's files. Two EFS mechanisms solve it:

| Mechanism | What it does | Where it is enforced |
|-----------|--------------|----------------------|
| Access point | Overrides the uid/gid presented by the client with a fixed identity, and confines the client to a root directory | EFS service side, regardless of what the client claims |
| IAM authorisation | Requires the client to present AWS credentials when mounting, evaluated against the file system policy and identity policies | At mount time, through efs-utils or the platform's mount helper |

Combining the two gives **defence in depth**: IAM decides whether the workload may mount at all and with which permissions (read, write, root), and the access point decides which directory and identity it sees.

#### IAM actions for EFS clients

| IAM action | Grants |
|------------|--------|
| `elasticfilesystem:ClientMount` | Mount with read-only access |
| `elasticfilesystem:ClientWrite` | Write access (requires ClientMount as well) |
| `elasticfilesystem:ClientRootAccess` | Act as uid 0 without root squashing |

!!! note "Root squashing by policy"
    If a file system policy grants `ClientMount` and `ClientWrite` but not `ClientRootAccess`, a client mounting as root is treated as the NFS anonymous user. This is the EFS equivalent of the traditional `root_squash` export option and is a recommended default.

#### Integration models by compute platform

```mermaid
flowchart TB
    subgraph "Amazon EKS"
        P1["Pod"] --> PVC["PersistentVolumeClaim"]
        PVC --> PV["PersistentVolume"]
        PV --> CSI["EFS CSI node DaemonSet"]
    end
    subgraph "Amazon ECS"
        T1["Task"] --> VOL["efsVolumeConfiguration"]
        VOL --> AGENT["ECS agent or Fargate platform mount helper"]
    end
    subgraph "AWS Lambda"
        F1["Function"] --> FSC["FileSystemConfigs"]
        FSC --> LMP["Local mount path under /mnt"]
    end
    CSI --> EFS["EFS access point and file system"]
    AGENT --> EFS
    LMP --> EFS
```

| Platform | Declaration | Mount performed by | Identity to EFS |
|----------|-------------|--------------------|-----------------|
| EKS on EC2 nodes | PV/PVC and StorageClass | EFS CSI node plugin running efs-utils on the node | Node IAM role for mount authorisation by default; access point identity for POSIX |
| EKS on Fargate | Static PV only | Fargate platform (driver built in) | Pod execution role context; access point identity |
| ECS on EC2 | `volumes[].efsVolumeConfiguration` | ECS agent using efs-utils on the container instance | Task role if `iam: ENABLED` |
| ECS on Fargate | Same as above | Fargate platform | Task role if `iam: ENABLED` |
| Lambda | `FileSystemConfigs` referencing an access point ARN | Lambda service | Function execution role; access point identity |

### AWS Service Deep Dive

#### Purpose

In the integration context, EFS provides a **shared persistence layer for compute that is otherwise ephemeral**, so that scaling out, replacing, or rescheduling a workload never loses or duplicates file data.

#### Architecture

EFS separates a distributed metadata layer (directories, inodes, attributes, locks) from a distributed data layer. Both are spread across multiple AZs for Regional file systems. Clients speak NFS to a mount target in their own AZ; the mount target forwards requests to the storage fleet. This architecture explains two properties that matter throughout this part:

1. **Every file operation is a network round trip**, including metadata operations such as `stat()`, `open()` and `readdir()`. Workloads dominated by small-file metadata operations therefore perform very differently from workloads streaming large files.
2. **Throughput and IOPS scale with the aggregate of many clients**, not with any single client. A single NFS client is limited by its own network bandwidth and by the concurrency it generates.

```mermaid
sequenceDiagram
    participant App as "Application in pod"
    participant K as "Node kernel NFS client"
    participant P as "efs-utils proxy with TLS"
    participant MT as "Mount target ENI in same AZ"
    participant M as "EFS metadata layer"
    participant D as "EFS data layer"
    App->>K: "open and read file"
    K->>P: "NFSv4.1 LOOKUP and OPEN"
    P->>MT: "TLS on port 2049"
    MT->>M: "resolve inode and check permissions"
    M-->>MT: "file handle"
    K->>P: "NFS READ"
    P->>MT: "encrypted READ"
    MT->>D: "fetch data blocks"
    D-->>App: "data returned through the same path"
```

#### Important Features

| Feature | Integration significance |
|---------|-------------------------|
| Elastic throughput | Throughput scales automatically with demand; no capacity planning for spiky container or Lambda workloads |
| Access points | Per-application or per-PVC isolation on one shared file system |
| File system policy | Resource-based policy that enforces TLS, IAM and access-point usage centrally |
| Encryption at rest with KMS | Chosen at creation; cannot be changed afterwards |
| Encryption in transit | TLS through efs-utils; enforceable by policy |
| EFS Replication | Asynchronous replication to another Region or within the Region for disaster recovery |
| AWS Backup integration | Policy-driven, incremental backups with item-level restore |
| Lifecycle management | Moves cold files to IA and Archive; can move them back on access |
| EFS CSI driver EKS add-on | AWS-managed installation and upgrades of the driver |
| Mount target per AZ | Clients keep traffic within their AZ, avoiding cross-AZ data charges and latency |

#### Limitations

- NFS only; there is no SMB protocol support (use FSx for Windows File Server or FSx for NetApp ONTAP).
- Linux clients only for native mounting; Windows workloads are not supported.
- Per-operation latency is higher than local NVMe or EBS; metadata-heavy workloads can be slow.
- Encryption at rest must be decided at file system creation.
- One Zone file systems are exposed to AZ failure.
- EKS dynamic provisioning is limited by the number of access points per file system.
- EKS on Fargate supports static provisioning only.

#### Pricing Model and recommendations

EFS pricing has several dimensions. Values are indicative, as of 2026; verify in the AWS Pricing Calculator.

| Dimension | Behaviour | Recommendation |
|-----------|-----------|----------------|
| Storage (GB-month) per storage class | Standard is the highest price; IA and Archive are progressively cheaper per GB | Enable lifecycle management for data with cold tails |
| Access charges for IA and Archive | Per GB read from (and tiered into) the cheaper classes | Do not tier hot data; configure "transition to Standard on first access" when access is unpredictable |
| Elastic throughput | Per GB of data read and per GB written; writes cost more than reads | Default for spiky or unknown workloads |
| Provisioned throughput | Per MiB/s-month provisioned above the baseline included with storage | Consider for steady, high, predictable throughput where it is cheaper than Elastic |
| Bursting throughput | No throughput charge; throughput tied to stored size with burst credits | Only for small, predictable workloads with large stored size |
| Replication | Destination storage plus data transfer for cross-Region replication | Replicate only file systems that need regional DR |
| Backup | AWS Backup storage and restore charges | Tune retention per data classification |

!!! tip "Elastic throughput cost behaviour"
    Elastic throughput is charged by the bytes you move, not by the capacity you reserve. This aligns perfectly with bursty workloads (a Lambda function loading a model on cold start, a nightly batch job), but it can surprise teams with a workload that reads the same large files repeatedly, such as hundreds of pods each loading a 5 GB model at every restart. Always estimate "bytes read per month" before choosing the throughput mode. Small I/O and metadata operations are metered with a minimum per-operation size, so millions of tiny operations can cost more than their raw byte count suggests; verify the current metering rules in the EFS pricing page.

#### Performance Characteristics

| Characteristic | Indicative behaviour, as of 2026 |
|----------------|----------------------------------|
| Read latency, General Purpose mode | Sub-millisecond for frequently accessed data |
| Write latency | Low single-digit milliseconds, since writes are durably stored across AZs before acknowledgement |
| Per-client throughput | Bounded by the client's network bandwidth and NFS concurrency, typically up to around 1.5 GiB/s per client with efs-utils; verify current documentation |
| Aggregate throughput with Elastic | Scales to tens of GiB/s for reads and several GiB/s for writes per file system in larger Regions |
| Aggregate IOPS | Hundreds of thousands of read IOPS by default with Elastic throughput and General Purpose mode, raisable on request to up to 2.5 million read and 500,000 write IOPS per file system |

!!! note "Why aggregate numbers mislead beginners"
    The headline throughput figures are for many clients in parallel. A single Python process reading files one by one sees per-operation latency, not aggregate throughput. Parallelism across threads, processes and clients is the key to EFS performance.

#### Scaling Behaviour

- Storage capacity grows and shrinks automatically; there is no provisioned size.
- Elastic throughput scales automatically with demand up to the Regional limits.
- Clients scale independently: adding pods, tasks or Lambda environments adds NFS connections, and EFS absorbs them up to the per-file-system connection limit.
- Metadata scalability is per directory as well as per file system. Very large flat directories (hundreds of thousands of entries) make `readdir` and `lookup` operations slower; shard directories by prefix.

#### Availability

| File system type | Design | Suitable for |
|------------------|--------|--------------|
| Regional | Data and metadata stored redundantly across multiple AZs; mount targets in each AZ | Production workloads that must survive an AZ failure |
| One Zone | Stored in a single AZ; lower price | Development, reproducible data, or workloads already pinned to one AZ |

A Regional file system survives AZ failure only if **clients in surviving AZs have their own mount target**. A common design flaw is to create a mount target in one subnet only.

#### Security Features

- IAM identity policies and a resource-based file system policy.
- Access points that enforce POSIX identity and root directory.
- Security groups on mount targets (inbound TCP 2049 from client security groups only).
- Encryption at rest with AWS KMS (AWS managed key or customer managed key).
- Encryption in transit with TLS 1.2 through efs-utils.
- AWS CloudTrail logging of management API calls and of client mount authorisation events when IAM authorisation is used.
- Interface VPC endpoint for the EFS management API.

#### Service Limits

Indicative, as of 2026; verify in Service Quotas and the EFS quotas page.

| Limit | Indicative value | Integration implication |
|-------|------------------|-------------------------|
| Access points per file system | 10,000 (default; raise through AWS Support) | Caps the number of dynamically provisioned PVCs per file system in `efs-ap` mode |
| Mount targets per file system per AZ | 1 | One mount target per AZ, shared by all clients in that AZ |
| NFS client connections per file system | Around 25,000 | Relevant for large Lambda concurrency and large EKS clusters |
| Open files per client | Around 32,768 | Relevant for connection-heavy application servers |
| Locks per file per client | Several hundred | Applications that lock many byte ranges |
| Maximum file size | Around 47.9 TiB | Rarely a constraint |
| Directory depth | 1,000 levels | Rarely a constraint |
| File systems per account per Region | 1,000 (adjustable) | Per-tenant file system designs |
| Security groups per mount target | 5 | Group client security groups rather than listing many |

### Important AWS Terminology

Mount target, access point, throughput mode, performance mode and storage class are defined in [Core Concepts](#file-systems-mount-targets-and-the-network-path).

| Term | Meaning |
|------|---------|
| Container Storage Interface (CSI) | A standard API through which a container orchestrator asks a storage plugin to provision, attach and mount volumes |
| EFS CSI driver | The AWS-maintained CSI plugin that mounts EFS into Kubernetes pods; runs as a controller Deployment and a node DaemonSet |
| Static provisioning | An administrator creates the PersistentVolume that points at an existing file system or access point |
| Dynamic provisioning | The CSI controller creates storage on demand when a PersistentVolumeClaim references a StorageClass |
| `efs-ap` provisioning mode | The EFS CSI dynamic provisioning mode in which each PVC receives its own new access point on a shared file system |
| `volumeHandle` | The identifier in a static PV that names the file system, optional subpath and optional access point, for example `fs-0123::fsap-0456` |
| ReadWriteMany (RWX) | A Kubernetes access mode allowing many nodes to mount a volume read-write simultaneously |
| EKS Pod Identity | EKS feature that associates an IAM role with a Kubernetes service account through the EKS Pod Identity Agent, without an OIDC provider per cluster |
| IRSA | IAM Roles for Service Accounts; the older mechanism using the cluster OIDC provider and web identity federation |
| efs-utils | The Amazon mount helper (`mount -t efs`) that adds TLS, IAM authorisation and AZ-aware DNS; version 2 uses a built-in proxy (efs-proxy) instead of stunnel |
| File system policy | A resource-based IAM policy attached to an EFS file system |
| Root squashing | Mapping a client's uid 0 to an unprivileged identity so that root on the client is not root on the file system |
| EFS Replication | A managed, asynchronous copy of a file system to a destination file system, used for disaster recovery |
| Recovery Point Objective (RPO) | The maximum acceptable age of data restored after a failure |
| Recovery Time Objective (RTO) | The maximum acceptable time to restore service after a failure |
| AWS DataSync | Managed data transfer service that copies files and metadata between on-premises storage, EFS, FSx and S3 |
| Mountpoint for Amazon S3 | An open-source file client that presents an S3 bucket as a local file system with object-storage semantics |
| `PercentIOLimit` | CloudWatch metric showing how close a General Purpose file system is to its I/O limit |
| `MeteredIOBytes` | CloudWatch metric of bytes counted against throughput, including metadata |
| `ClientConnections` | CloudWatch metric counting connected NFS clients |

### Configuration Options

#### EFS CSI driver on Amazon EKS

The EFS CSI driver has two components:

| Component | Kubernetes object | Responsibility | IAM needs |
|-----------|-------------------|----------------|-----------|
| Controller | Deployment `efs-csi-controller` with service account `efs-csi-controller-sa` | Creates and deletes access points for dynamic provisioning | `elasticfilesystem:CreateAccessPoint`, `DeleteAccessPoint`, `Describe*`, `TagResource`, usually via the AWS managed policy `AmazonEFSCSIDriverPolicy` |
| Node plugin | DaemonSet `efs-csi-node` | Runs efs-utils on each node and performs the NFS mount into pod directories | Node role, or the `efs-csi-node-sa` service account role, needs `ClientMount`/`ClientWrite` when IAM authorisation is enforced |

```mermaid
flowchart LR
    DEV["Developer applies PVC"] --> API["Kubernetes API server"]
    API --> CTRL["efs-csi-controller"]
    CTRL -->|"CreateAccessPoint with uid gid and path"| EFSAPI["EFS control plane"]
    CTRL --> PV["PV bound to PVC with volumeHandle fs::fsap"]
    SCHED["Scheduler places pod on node"] --> KUBELET["kubelet"]
    KUBELET --> NODE["efs-csi-node on that node"]
    NODE -->|"mount -t efs with tls and accesspoint"| MT["Mount target in node AZ"]
```

##### Installing the driver and granting IAM with EKS Pod Identity

The recommended installation is the managed EKS add-on `aws-efs-csi-driver`. EKS Pod Identity is the preferred credential mechanism for new clusters because it avoids per-cluster OIDC trust policy edits and allows the same role to be reused across clusters.

```mermaid
sequenceDiagram
    participant Admin as "Platform engineer"
    participant IAM as "AWS IAM"
    participant EKS as "EKS API"
    participant Agent as "Pod Identity Agent on node"
    participant Ctrl as "efs-csi-controller pod"
    Admin->>IAM: "Create role trusted by pods.eks.amazonaws.com"
    Admin->>IAM: "Attach AmazonEFSCSIDriverPolicy"
    Admin->>EKS: "Create pod identity association for kube-system efs-csi-controller-sa"
    Admin->>EKS: "Install aws-efs-csi-driver add-on"
    Ctrl->>Agent: "Request credentials"
    Agent->>EKS: "AssumeRoleForPodIdentity"
    EKS-->>Agent: "Temporary credentials"
    Agent-->>Ctrl: "Credentials scoped to the role"
```

!!! info "Pod Identity versus IRSA for the EFS CSI driver"
    Recent versions of the EFS CSI driver support EKS Pod Identity; older versions required IRSA. If a cluster already uses IRSA for the driver, it continues to work. For new clusters, check the add-on version compatibility table and prefer Pod Identity. Note that the role for the controller is not the role used by application pods: application pods do not call the EFS API directly.

##### Static provisioning

Static provisioning is appropriate when the file system, and often the access point, already exist, for example a content directory shared by all replicas of one Deployment, or any workload on EKS Fargate.

| `volumeHandle` form | Meaning |
|---------------------|---------|
| `fs-0123456789abcdef0` | Mount the file system root |
| `fs-0123456789abcdef0:/shared/content` | Mount a subdirectory (the directory must exist) |
| `fs-0123456789abcdef0::fsap-0abc123` | Mount through an access point, which enforces identity and root directory |

The driver mounts with TLS by default (`encryptInTransit` volume attribute defaults to true in current versions). Mount options such as `iam` can be added through `spec.mountOptions`.

##### Dynamic provisioning with `efs-ap`

In dynamic provisioning, the controller does **not create a new file system**. It creates a new **access point** on an existing file system for each PVC. Each access point receives:

- A root directory under a configurable `basePath`, created with `directoryPerms`.
- A POSIX uid and gid drawn from the range `gidRangeStart` to `gidRangeEnd`, so that each PVC's files are owned by a unique identity and one tenant cannot read another's directory even if both mount the same file system.

| StorageClass parameter | Purpose | Typical value |
|------------------------|---------|---------------|
| `provisioningMode` | Selects access point provisioning | `efs-ap` |
| `fileSystemId` | The shared file system | `fs-0123456789abcdef0` |
| `directoryPerms` | Permissions of the created root directory | `700` for strict isolation, `770` for group sharing |
| `gidRangeStart`, `gidRangeEnd` | Range of POSIX IDs allocated to access points | A range reserved for Kubernetes, for example `1000000` to `1100000` |
| `basePath` | Parent directory for all dynamically created directories | `/dynamic` |
| `subPathPattern` | Template for directory names, for example using PVC namespace and name | `${.PVC.namespace}/${.PVC.name}` |
| `ensureUniqueDirectory` | Appends a unique suffix so two PVCs cannot collide on the same path | `true` (the default) |
| `reuseAccessPoint` | Reuses an existing access point with the same PVC name, useful when re-creating clusters | `false` unless planned |
| `uid`, `gid` | Fixed identity for all access points instead of allocating from a range | Use only when all consumers must share ownership |
| `reclaimPolicy` (StorageClass field) | `Delete` removes the access point when the PVC is deleted; `Retain` keeps it | `Retain` for data that must outlive the claim |

!!! warning "What Delete actually deletes"
    With `reclaimPolicy: Delete`, the controller deletes the access point. By default it does not delete the directory contents, so data may remain on the file system and continue to cost money. Newer driver versions offer an option to delete the access point root directory; verify the behaviour of your driver version and design explicit data retention rules.

!!! danger "The access point ceiling"
    Because each dynamically provisioned PVC consumes one access point, a single file system can back at most the access point quota worth of PVCs (10,000 by default). A multi-tenant platform expecting more claims must spread them across several StorageClasses, each pointing at a different file system.

##### Access modes and capacity requests

EFS volumes are normally requested with `ReadWriteMany`. The `storage` value in the PVC is required by Kubernetes but **is not enforced by EFS**, because EFS is elastic. Architects must therefore enforce quotas by other means, such as monitoring `StorageBytes`, directory-level scripts, or per-tenant file systems.

#### Amazon ECS and AWS Fargate EFS volumes

| Field in `efsVolumeConfiguration` | Purpose | Recommendation |
|-----------------------------------|---------|----------------|
| `fileSystemId` | Target file system | Required |
| `rootDirectory` | Directory to mount; must be `/` or omitted when an access point is used | Use access points instead |
| `transitEncryption` | `ENABLED` or `DISABLED` | Always `ENABLED`; required when IAM authorisation is used |
| `transitEncryptionPort` | Local port for the TLS proxy | Leave unset unless there is a port conflict |
| `authorizationConfig.accessPointId` | Mount through an access point | Always set in production |
| `authorizationConfig.iam` | `ENABLED` makes the mount use the task role | Enable, and grant only the needed client actions |

Fargate requires platform version 1.4.0 or later for EFS. The Fargate task's ENI must be able to reach the mount target on TCP 2049, so the **mount target security group must allow inbound 2049 from the task security group**.

!!! tip "Task role, not task execution role"
    With `iam: ENABLED`, the credentials presented to EFS come from the **task role** (`taskRoleArn`), which represents the application. The task execution role is used by the agent to pull images and write logs. Placing EFS permissions on the execution role is a common mistake.

#### AWS Lambda file system configuration

| Setting | Constraint |
|---------|-----------|
| VPC configuration | The function must be attached to private subnets in a VPC that contains EFS mount targets in the same AZs |
| File system reference | Lambda mounts EFS through an **access point ARN**, not a raw file system ID |
| Local mount path | Must begin with `/mnt/`, for example `/mnt/models` |
| Execution role | Needs `elasticfilesystem:ClientMount` (and `ClientWrite` for writes) plus the VPC network interface permissions, typically via `AWSLambdaVPCAccessExecutionRole` |
| Security groups | Function SG must be allowed on port 2049 by the mount target SG |
| Compatibility | Lambda SnapStart does not support EFS attachments; verify current compatibility before combining features |

#### File system policies

A file system policy is evaluated together with identity policies. The most useful condition keys are:

| Condition key | Use |
|---------------|-----|
| `aws:SecureTransport` | Deny any mount not using TLS |
| `elasticfilesystem:AccessPointArn` | Allow access only through specific access points |
| `elasticfilesystem:AccessedViaMountTarget` | Require access through a mount target, preventing other paths |
| `aws:PrincipalArn` / `aws:PrincipalTag` | Restrict to specific workload roles |

!!! example "Common policy baseline"
    A production baseline usually contains three statements: deny when `aws:SecureTransport` is false; allow `ClientMount` and `ClientWrite` to named workload roles only when accessed through a mount target; deny `ClientRootAccess` to everyone except a break-glass administration role.

#### Throughput and lifecycle choices for integrated workloads

| Workload | Throughput mode | Lifecycle |
|----------|-----------------|-----------|
| WordPress uploads on ECS | Elastic | Transition to IA after 30 days, back to Standard on first access |
| ML model store for Lambda | Elastic | Keep models in Standard; old model versions to IA |
| CI build cache | Elastic, or Provisioned if steady and heavy | Short retention; clean up by job |
| Shared notebook home directories on EKS | Elastic | IA after 30 days, Archive after 90 days |
| Long-running HPC scratch | Consider FSx for Lustre instead | Not applicable |

### AWS Best Practices

- **Operational Excellence:** Define file systems, mount targets, access points, policies, backup plans and replication in IaC ([Chapter 5.3](../unit5/topic3.md)), never through the console alone.
- **Operational Excellence:** Install the EFS CSI driver as a managed EKS add-on and upgrade it together with the cluster version.
- **Security:** Enforce TLS and IAM authorisation with a file system policy, and deny `ClientRootAccess` by default.
- **Security:** Use one access point per application or PVC, and restrict mount target security groups to known client security groups.
- **Reliability:** Place a mount target in every Availability Zone the compute tier uses, and protect against corruption with AWS Backup and against Regional failure with EFS Replication.
- **Performance Efficiency:** Default to Elastic throughput and General Purpose performance mode, and parallelise I/O across threads, processes and clients.
- **Cost Optimization:** Enable lifecycle management with IA and Archive transitions, and monitor `MeteredIOBytes` under Elastic throughput.
- **Sustainability:** Share one copy of large assets on EFS instead of duplicating them into every container image.

### Industry Use Cases

| Industry | Use case | Why EFS |
|----------|----------|---------|
| Media and publishing | CMS platforms serving uploaded images and documents across many containers | Shared POSIX storage without rewriting the CMS |
| Education | Moodle or JupyterHub on EKS with per-student home directories | Dynamic provisioning with per-PVC access points |
| Financial services | Batch risk engines sharing reference data files across ECS tasks | Concurrent reads, IAM-controlled access, encryption, backups |
| Healthcare and life sciences | Genomics pipelines sharing intermediate files (with FSx for Lustre for the hottest stages) | Elastic capacity, lifecycle to IA for completed runs |
| Software companies | CI runners on EKS sharing dependency caches | RWX and elastic capacity |
| AI start-ups | Serverless inference loading models from a shared store | Lambda and Fargate integration without servers |
| Government | Lift-and-shift of legacy NFS-based applications | Managed, encrypted, auditable replacement for on-premises NAS |

### Advantages

| Advantage | Explanation |
|-----------|-------------|
| Serverless storage for serverless compute | No servers, capacity or patching; pairs naturally with Fargate and Lambda |
| True shared access across AZs | Many clients in multiple AZs mount the same data concurrently with POSIX semantics |
| No application rewrite | Existing file-based code works unchanged, which accelerates containerisation of legacy software |
| Fine-grained, IAM-integrated security | Access points, file system policies, IAM roles per workload, KMS and TLS |
| Elastic cost model | Pay for stored bytes and moved bytes, not for provisioned capacity |
| Built-in data protection | AWS Backup integration and managed cross-Region replication |
| Native integration across compute services | EKS CSI add-on, ECS task definitions and Lambda configuration all support EFS directly |

### Limitations

| Limitation | Trade-off |
|------------|-----------|
| Network latency on every operation | Excellent for shared content, poor for metadata-heavy or database-like workloads |
| Linux and NFS only | Windows and SMB workloads need FSx |
| Per-client throughput ceiling | High aggregate throughput requires many clients or parallel I/O |
| No capacity quotas per directory | Kubernetes PVC size is not enforced; runaway writers can grow cost |
| Access point quota | Limits dynamic provisioning density per file system |
| Asynchronous replication | RPO is minutes, not zero; applications must tolerate a small data loss window on regional failover |
| Cost at scale for hot data | Standard storage and Elastic throughput can exceed the cost of S3 for large, read-mostly datasets |
| No per-file audit logging | Compliance regimes requiring file access audit need FSx alternatives |

### Summary

Amazon EFS is the shared file layer that allows cloud-native compute to remain disposable while still serving software that depends on a POSIX file system. In an integrated architecture, EFS is consumed through the EFS CSI driver on EKS, through `efsVolumeConfiguration` on ECS and Fargate, and through access point ARNs on Lambda. Across all three, the same design rules apply: every workload receives its own IAM role and its own access point; a file system policy enforces TLS, mount-target access and root squashing; and mount targets exist in every AZ where compute runs.

The key architectural lessons are:

- ==Shared storage is a deliberate exception to statelessness==, justified for content, models, caches and legacy software, not for transactional data.
- **Access points are the unit of isolation** on a shared file system; in EKS dynamic provisioning, one access point per PVC with a unique uid/gid delivers multi-tenant isolation, bounded by the access point quota.
- **Performance depends on the shape of the workload**: large parallel reads perform well, while small-file and metadata-heavy workloads suffer from network round trips.
- **Elastic throughput converts capacity planning into byte accounting**, which is ideal for spiky demand but must be monitored for repeated large reads.
- **Backups and replication solve different problems**; production designs need both, and access points and policies must also exist in the DR Region.
- **The choice between EFS, FSx and Mountpoint for S3 is driven by protocol, semantics, performance and operational model**, not by familiarity.

## Caching Strategies with Amazon ElastiCache

!!! note "ElastiCache at a glance"
    ElastiCache is a managed in-memory data store offering the Valkey, Redis OSS and Memcached engines. Node-based clusters consist of shards (node groups), each with one primary and up to five replicas; cluster mode enabled distributes 16,384 hash slots across shards. Redis OSS and Valkey offer rich data structures, replication, persistence options and pub/sub; Memcached offers a simple, multi-threaded key-value cache without replication. Cache-aside (lazy loading) populates the cache on a miss; write-through updates the cache on every write; write-behind buffers writes. A cache stampede occurs when many clients miss the same key simultaneously. The engine comparison is in the [AWS Service Deep Dive](#valkey-and-redis-oss-versus-memcached), and the patterns in [Core Concepts](#caching-patterns-and-the-decision-table).

### Definition

A **caching strategy** is the set of architectural decisions that determine what data is stored in a faster, closer, cheaper-to-read tier; where in the request path that tier sits; how data enters and leaves it; how long it remains valid; and how the system behaves when the cache is empty, stale or unavailable.

**Amazon ElastiCache** is the AWS managed service that provides the in-memory application cache tier for such strategies. It supports the Valkey, Redis OSS and Memcached engines, in two deployment models: node-based clusters, where the architect chooses node types and shard counts, and ElastiCache Serverless, where capacity scales automatically and is billed by stored data and processing units.

In an AWS architecture, ElastiCache sits between the compute tier (Lambda, ECS, EKS, EC2) and the system of record (Aurora, RDS, DynamoDB, or external APIs), inside private subnets of a VPC.

```mermaid
flowchart LR
    U["Client"] --> CF["CloudFront edge cache"]
    CF --> APIGW["API Gateway stage cache"]
    APIGW --> SVC["Microservice on ECS, EKS or Lambda"]
    SVC --> LOCAL["In-process cache"]
    SVC --> EC["ElastiCache Valkey"]
    SVC --> DAX["DynamoDB Accelerator"]
    EC -.->|"miss"| DB["Aurora or RDS"]
    DAX --> DDB["DynamoDB"]
    DB --> BP["Database buffer pool"]
```

### Why This Service or Concept Exists

- **The latency gap:** A memory read from a nearby cache takes well under a millisecond, whereas a complex database query, a cross-Region call or a third-party API can take hundreds of milliseconds.
- **Latency compounds across the call graph:** One user request may fan out to many microservices, so the p99 latency of a page is dominated by its slowest dependency.
- **Real workloads are cacheable:** Temporal locality and skewed (Zipf-like) key popularity mean that a cache much smaller than the dataset can serve most reads.
- **Caching is a strategy, not a component:** A cache changes correctness (stale reads), availability (a new dependency), cost and failure modes (stampedes, hot keys, cold starts).
- **Managed operations:** ElastiCache automates the replication, failover, patching, scaling, backups and TLS that a self-managed Redis or Memcached fleet would require.
- **Valkey as the default engine:** AWS added Valkey, the open-source Linux Foundation fork of Redis OSS, at a lower price, which makes it the default engine for new designs.

### Core Concepts

#### Where to cache in a cloud-native stack

Each layer has a different scope, freshness control and cost. The architectural principle is: **serve each request from the outermost layer that can answer it correctly**.

| Layer | Service | Scope | What it caches well | Invalidation control | Limitations |
|-------|---------|-------|---------------------|---------------------|-------------|
| Browser and client | HTTP `Cache-Control`, ETags | One user | Static assets, user-specific responses | TTL, validators | No central control once cached |
| Edge | Amazon CloudFront | Global, per edge location and regional edge cache | Static assets, public API responses, media | Cache policies, TTLs, invalidation API, versioned URLs | Personalised responses need careful cache keys |
| API tier | API Gateway REST API stage cache | Per stage | Idempotent GET responses | TTL (default 300 s, up to 3,600 s), per-method settings, `Cache-Control: max-age=0` with authorisation | REST APIs only; billed hourly by cache size; single-Region |
| In-process | Local memory in the service (for example Caffeine, `functools.lru_cache`, a module-level dictionary in Lambda) | One process or execution environment | Very hot, small, rarely changing data such as configuration and feature flags | Short TTL, events | Inconsistent across replicas; lost on restart; duplicates memory |
| Distributed application cache | ElastiCache Valkey, Redis OSS, Memcached | All replicas of all services in the VPC | Query results, computed objects, sessions, counters | Application-controlled TTL and deletes | Additional infrastructure, network hop |
| Database-specific | DynamoDB Accelerator (DAX) | One DynamoDB table set | Item and query results for DynamoDB | Write-through for items written via DAX | DynamoDB only; eventually consistent reads only |
| Database engine | Aurora or RDS buffer pool | One database instance | Hot pages | Automatic | Consumes database memory; does not reduce query CPU for complex queries |

```mermaid
flowchart TD
    R["Incoming request"] --> Q1{"Same response for many users and safe to share"}
    Q1 -->|"Yes"| EDGE["Cache at CloudFront with a cache policy"]
    Q1 -->|"No"| Q2{"Idempotent GET through a REST API with simple keys"}
    Q2 -->|"Yes, and low change rate"| APIC["API Gateway stage cache"]
    Q2 -->|"No"| Q3{"Tiny, extremely hot, tolerant of seconds of staleness"}
    Q3 -->|"Yes"| LOC["In-process cache with short TTL"]
    Q3 -->|"No"| Q4{"DynamoDB item or query reads"}
    Q4 -->|"Yes"| DAXN["DAX or ElastiCache"]
    Q4 -->|"No"| ECN["ElastiCache application cache"]
```

!!! tip "Layered caching is normal"
    Production systems usually combine layers: CloudFront for public assets, a short in-process cache for configuration, and ElastiCache for shared query results. The danger is **stacked TTLs**: if CloudFront caches for 60 seconds, the service caches locally for 30 seconds and ElastiCache holds data for 300 seconds, the worst-case staleness seen by a user is the sum, not the maximum. Design end-to-end freshness budgets.

#### Caching patterns and the decision table

Three foundational patterns govern how data enters the cache and how writes reach the system of record.

- **Cache-aside**, also called lazy loading: the application checks the cache and, on a miss, reads the database and populates the cache (see [Chapter 1.5](../unit1/topic5.md)). Only requested data is ever cached, so the cache stays small and relevant, and a cache failure degrades performance without breaking correctness. The costs are three trips on every miss (cache, database, cache write) and the risk of serving stale data until the TTL expires or the key is invalidated.
- **Write-through**: the application writes to the database and the cache together, so the cache is not stale for keys written this way. The costs are extra latency on every write and a cache filled with data that may never be read, which wastes memory; write-through is therefore usually combined with a TTL so that cold entries age out.
- **Write-behind**, also called write-back: the application writes to the cache, and the cache contents are flushed to the database asynchronously. This gives the lowest write latency but risks data loss, and it is rarely appropriate with a pure cache as the intermediary unless durability is guaranteed by other means (see the warning below).

Two further patterns complete the set.

- **Read-through**: the application asks the cache, and the cache itself loads from the database on a miss. ElastiCache does not load from databases on its own; read-through is implemented by a library or data-access layer that wraps the cache (for example a caching repository class), or by services with built-in read-through such as DAX.
- **Refresh-ahead**: the cache refreshes popular entries before they expire, so that readers rarely experience a miss. It is implemented with background refresh jobs, scheduled Lambda functions, or probabilistic early recomputation.

| Pattern | Read path | Write path | Staleness | Miss penalty | Complexity | Best when |
|---------|-----------|------------|-----------|--------------|------------|-----------|
| Cache-aside | App reads cache; on miss, reads DB and populates cache | App writes DB, then deletes or updates cache key | Bounded by TTL or invalidation | Full DB read on each miss | Low | General-purpose default; read-heavy data |
| Read-through | App reads through a caching layer that loads on miss | Usually combined with write-through or invalidation | Same as cache-aside | Same, hidden in the layer | Medium (library) | Many services should share a consistent loading policy |
| Write-through | Reads hit a warm cache | App writes DB and cache synchronously | Low | Low after first write | Medium | Data is read soon after it is written, such as user profiles |
| Write-behind | Reads hit the cache | App writes cache; an asynchronous worker persists to DB | Cache is the newest copy | Low | High; risk of data loss | Very high write rates that tolerate delayed persistence, such as counters and metrics |
| Refresh-ahead | Readers almost always hit | Background refresh before expiry | Bounded by refresh interval | Near zero for hot keys | Medium | Predictably hot, expensive-to-compute data such as homepage aggregates |

!!! warning "Write-behind and durability"
    In write-behind, the cache temporarily holds the only copy of recent writes. A node failure before persistence loses data unless the cache is itself durable. If write-behind semantics are required for business-critical data, use Amazon MemoryDB, or persist through a durable queue such as SQS or Kinesis rather than relying on an in-memory buffer.

!!! note "Delete, do not update, on write"
    In cache-aside, the safer invalidation on write is to **delete the key** rather than write the new value. Two concurrent writers updating the cache can interleave so that the older value is written last, leaving the cache permanently stale until TTL expiry. Deleting forces the next reader to load the current database value. The remaining race (a reader loads an old value just before a writer deletes) is bounded by the TTL, which is one reason every cached key should have a TTL.

#### TTL design

A TTL is a business decision expressed in seconds: **how stale may this data be before it causes harm?**

| Data | Change frequency | Harm from staleness | Indicative TTL |
|------|-----------------|--------------------|----------------|
| Product catalogue description | Hours to days | Low | 1 to 24 hours, with event invalidation |
| Product price | Minutes | Medium to high (legal and trust) | Short TTL plus event-driven invalidation, or no cache at checkout |
| Stock level for display | Seconds | Medium | 5 to 30 seconds; authoritative check at checkout |
| User session | Per request | High if it expires early (logout) | Sliding expiry, for example 30 minutes |
| Feature flags | Rarely | Medium | 30 to 60 seconds in-process |
| Exchange rates from a third-party API | Per minute | Medium | Aligned with upstream refresh period |
| Negative results (not found) | Varies | Low | Much shorter than positive TTL, for example 30 to 60 seconds |

Three TTL design rules:

1. **Every key has a TTL**, even when invalidation exists. TTL is the safety net for missed invalidation events and for write races.
2. **Add jitter**. If a batch job populates 100,000 keys with a TTL of exactly 3,600 seconds, they all expire in the same second. Randomise, for example `ttl = base + random(0, 0.1 * base)`.
3. **Separate logical expiry from physical expiry** for refresh-ahead: store the value with a longer physical TTL but record a soft expiry timestamp inside the value; readers that see a soft-expired value can serve it while triggering a refresh.

#### Invalidation strategies

| Strategy | Mechanism | Consistency | Coupling | Typical use |
|----------|-----------|-------------|----------|-------------|
| TTL expiry only | Keys expire | Stale up to TTL | None | Data that tolerates bounded staleness |
| Explicit delete in the write path | Service deletes the key after committing the database write | Near-immediate for that service's keys | Writer must know all cache keys | Single service owning both data and cache |
| Event-driven invalidation | Database change events trigger deletion by an independent consumer | Near real-time, eventually consistent | Loose; writers do not know about caches | Microservices where many readers cache data owned by another service |
| Versioned keys | Key includes a version (`product:42:v17`) or a namespace generation counter | Immediate for new reads; old keys age out | Readers must learn the current version | Bulk invalidation, deployments, schema changes |
| Tag or group invalidation | A set records keys belonging to a group; invalidate by iterating the set | Immediate | Medium | Invalidate everything related to one tenant or one product |

##### Event-driven invalidation with DynamoDB Streams and EventBridge

In a microservice architecture ([Chapter 4.1](../unit4/topic1.md)), the service that owns data should not need to know which other services cache it. Change data capture solves this. DynamoDB Streams emits item-level changes; a Lambda function consumes them and deletes affected keys. When several services cache the same data, EventBridge Pipes can route stream records to an event bus, and each consuming service owns an invalidation rule ([Chapter 1.7](../unit1/topic7.md) covers Pipes and rules).

```mermaid
sequenceDiagram
    participant W as "Catalogue service"
    participant D as "DynamoDB Products table"
    participant S as "DynamoDB Stream"
    participant P as "EventBridge Pipe"
    participant B as "Event bus"
    participant L1 as "Search service invalidator Lambda"
    participant L2 as "Pricing service invalidator Lambda"
    participant C as "ElastiCache"
    W->>D: "UpdateItem product 42"
    D->>S: "MODIFY record with keys"
    S->>P: "Batch of records"
    P->>B: "ProductChanged event"
    B->>L1: "Rule match"
    B->>L2: "Rule match"
    L1->>C: "DEL search:product:42"
    L2->>C: "DEL price:product:42"
```

For Aurora and RDS, equivalent change events can come from the transactional outbox pattern ([Chapter 1.7](../unit1/topic7.md)), in which the service writes an event row in the same transaction as the data change and a relay publishes it.

!!! tip "Invalidation must be idempotent and tolerant of reordering"
    Stream consumers retry, and events can be delivered more than once. `DEL` is naturally idempotent. If a consumer sets new values rather than deleting, include a version number and use a conditional update (for example a Lua script that writes only if the incoming version is higher), otherwise an old event processed late can overwrite newer data.

##### Versioned keys

Versioned keys avoid deleting anything. The reader first obtains a small, frequently cached version marker, then reads the versioned key.

| Approach | Key example | Invalidation action |
|----------|-------------|---------------------|
| Per-entity version | `product:42:v17` where the version is stored in the database row | Writer increments the version; readers compute the new key |
| Namespace generation | `gen:catalog` holds `93`; data keys are `catalog:93:product:42` | `INCR gen:catalog` invalidates the whole namespace instantly |
| Deployment version | `v2025-10-01:homepage` | New release reads new keys; old keys expire |

Versioned keys are particularly useful in CI/CD ([Chapter 5.2](../unit5/topic2.md)): if a deployment changes the serialised shape of cached objects, including the application's schema version in keys prevents new code from failing to deserialise old values, and allows blue/green versions to run side by side.

#### Stampede protection

A **cache stampede** (also called a thundering herd) happens when a very popular key expires or is evicted: thousands of concurrent requests miss at the same moment and all query the database at once, which can saturate it and turn a cache miss into an outage. TTL jitter prevents keys from expiring in lockstep, but it does not protect a single hot key.

The simplest guard is a short-lived distributed lock. On a miss, a request tries `SET lock:key token NX PX 5000`; only the request that acquires the lock recomputes the value and writes it back with a jittered TTL, while the others wait briefly and re-read the key, serve a stale copy, or, as a last resort, fall through to the database rather than fail the request. The lock's own expiry guarantees that a crashed lock holder cannot block the key forever. A safe release checks the token before deleting the lock.

In production, the lock is combined with the other techniques below.

| Technique | Idea | Strengths | Weaknesses |
|-----------|------|-----------|------------|
| Distributed lock (mutex) | On miss, one client acquires `SET lock:key token NX PX 5000`, recomputes and fills; others wait briefly or serve stale data | Strictly limits recomputation to one worker | Waiting adds latency; lock expiry must exceed recomputation time; use a token and compare-and-delete to release safely |
| Probabilistic early expiration | Each reader recomputes early with a probability that increases as expiry approaches (the XFetch algorithm) | No coordination; spreads refreshes over time | Occasional duplicate recomputation |
| Request coalescing | Within one process, concurrent requests for the same key share one in-flight load (single-flight) | Removes duplicates inside each replica cheaply | Does not coordinate across replicas; combine with a lock |
| Serve stale while revalidating | Keep a stale copy and return it while one worker refreshes | Excellent user latency | Requires soft-expiry metadata |

The XFetch rule recomputes when:

`now - delta * beta * ln(random()) >= expiry`

where `delta` is the time the last recomputation took, `beta` (typically 1.0) tunes eagerness, and `random()` is uniform in (0, 1]. Since `ln(random())` is negative, the left side is `now` plus a random positive offset, so expensive keys (larger `delta`) are refreshed earlier.

```mermaid
flowchart TD
    A["Read key"] --> B{"Value present"}
    B -->|"No"| L{"Acquire lock with SET NX PX"}
    L -->|"Acquired"| RC["Recompute from database and SET with TTL and jitter"]
    L -->|"Not acquired"| W["Wait briefly and retry read, or return fallback"]
    B -->|"Yes"| X{"XFetch says refresh early"}
    X -->|"No"| RET["Return cached value"]
    X -->|"Yes"| L2{"Acquire lock"}
    L2 -->|"Acquired"| BG["Refresh in background and return current value"]
    L2 -->|"Not acquired"| RET
```

#### Negative caching

When a key does not exist in the database, a naive cache-aside implementation queries the database on every request for that key. Attackers or bugs requesting random identifiers can therefore bypass the cache entirely (cache penetration). **Negative caching** stores a sentinel such as `__NOT_FOUND__` with a short TTL. When the item is later created, the create path must delete the sentinel, or the short TTL bounds the delay. For very large key spaces under attack, a Bloom filter (available through the Valkey Bloom module in recent Valkey versions on ElastiCache; verify engine version support) can reject identifiers that certainly do not exist.

#### Hot keys

A hot key is a single key receiving a disproportionate share of traffic, for example a flash-sale product. In cluster mode, one key maps to one hash slot on one shard, so **adding shards does not help a hot key**.

| Mitigation | How it works | Trade-off |
|------------|--------------|-----------|
| Read replicas with replica reads | Cluster-aware client sends reads to replicas (`READONLY`), multiplying read capacity of the shard | Replica lag; writes still hit one primary |
| Key replication (suffix sharding) | Store copies as `hot:42#0` to `hot:42#7`, which hash to different slots; readers pick a random suffix | Writes and invalidation must touch all copies |
| In-process caching of the hot key | Each replica keeps the value for one to five seconds | Brief inconsistency across replicas |
| Client-side caching with server-assisted invalidation | Redis 6+ and Valkey support `CLIENT TRACKING`, where the server notifies clients when tracked keys change; support in ElastiCache and in client libraries should be verified per engine version and deployment type | Additional client complexity; memory in each client |
| Split large values | Break a large hash into several keys | More round trips per read |
| Push to an outer layer | Cache the whole response at CloudFront | Only suitable for shareable responses |

Hot keys can be found with `valkey-cli --hotkeys` (requires an LFU eviction policy), by sampling commands in the application, or by observing a single shard's `EngineCPUUtilization` rising while others are idle.

#### Beyond caching: ElastiCache as a shared state service

Stateless microservices on ECS and EKS (Chapters [1.7](../unit1/topic7.md) and [4.1](../unit4/topic1.md)) push small, fast-changing, shared state into ElastiCache. These uses are not caches in the strict sense, because the data may not exist anywhere else, so their durability requirements must be assessed separately.

| Use | Data structure and commands | Why ElastiCache | Durability consideration |
|-----|----------------------------|-----------------|-------------------------|
| Session store | Hash per session `session:{id}` with `HSET`, `EXPIRE` refreshed on each request (sliding expiry) | Any task or pod can serve any user, so load balancers need no sticky sessions | Losing sessions logs users out; use Multi-AZ replicas; MemoryDB if loss is unacceptable |
| Rate limiting | Fixed window: `INCR` plus `EXPIRE`; sliding window: sorted set with `ZADD`, `ZREMRANGEBYSCORE`, `ZCARD`; token bucket: Lua script | Atomic operations shared by all replicas enforce a global limit | Brief loss resets counters, usually acceptable |
| Leaderboard | Sorted set with `ZINCRBY`, `ZREVRANGE ... WITHSCORES`, `ZREVRANK` | O(log N) updates and rank queries on millions of members | Rebuild from the database or event log after loss, or use MemoryDB |
| Proximity search | Geospatial index with `GEOADD` for positions and `GEOSEARCH` for members within a radius or box | Very high rates of position updates (for example drivers or couriers) and nearby-member queries served from memory, far more simply than a relational query | Positions are ephemeral and refreshed continuously; the durable trip or order record stays in the database |
| Pub/sub notifications | `PUBLISH`, `SUBSCRIBE`, sharded pub/sub `SPUBLISH` in cluster mode | Very low latency fan-out to connected subscribers, such as WebSocket servers | At-most-once; disconnected subscribers miss messages; use Streams, SNS, EventBridge or Kinesis for durable delivery |
| Lightweight queues and streams | Streams with `XADD`, consumer groups `XREADGROUP`, `XACK` | Low latency work distribution | In-memory; SQS is the durable default |
| Distributed locks | `SET key token NX PX ttl` with safe release | Coordinate singleton work across replicas | Locks based on a single primary can be lost on failover; do not use for correctness-critical mutual exclusion without fencing tokens |
| Idempotency keys | `SET idem:{requestId} result NX EX 86400` | Deduplicate retried API requests across replicas | Loss can permit a duplicate; combine with database constraints for payments |

!!! warning "Pub/sub is not a message queue"
    Valkey and Redis OSS pub/sub deliver a message only to subscribers connected at that moment. There is no persistence, acknowledgement or replay. Use it for ephemeral notifications, such as pushing a live score update to connected WebSocket servers, and use SQS, SNS, EventBridge or Kinesis ([Section 6.3](../unit6/topic3.md) and [Chapter 1.7](../unit1/topic7.md)) when delivery must be guaranteed.

#### Valkey, ElastiCache Serverless and MemoryDB

| Option | Nature | Choose when |
|--------|--------|-------------|
| ElastiCache for Valkey, node-based | Open-source, Redis OSS compatible engine (Valkey 7.2, 8.x and 9.x on ElastiCache as of 2026); priced lower than Redis OSS; performance improvements such as enhanced multi-threaded I/O | Default for new designs with predictable load and a need for control over node types, shards and parameter groups |
| ElastiCache Serverless for Valkey | No nodes or shards to manage; scales memory and compute automatically; billed by GB-hour of data stored and ElastiCache Processing Units (ECPUs); low minimum data charge for Valkey compared with Redis OSS | Spiky or unknown workloads, new services, many small caches per microservice, teams without cache operations expertise |
| ElastiCache for Redis OSS | Original engine | Existing deployments; features or versions not yet available on Valkey; an in-place engine upgrade from Redis OSS to Valkey is supported for many versions |
| ElastiCache for Memcached | Multi-threaded, simple key-value, no replication | Pure, disposable object caching where simplicity and multi-threading matter and data structures are unnecessary |
| Amazon MemoryDB | Valkey and Redis OSS compatible in-memory database with a durable Multi-AZ transaction log; writes are acknowledged after being durably logged | The in-memory data is the system of record: sessions that must never be lost, leaderboards, inventory counters, feature stores, vector search with durability |

```mermaid
flowchart TD
    A["Need an in-memory data store"] --> B{"Is the data also in a durable system of record"}
    B -->|"Yes, pure cache"| C{"Predictable steady load and need for fine control"}
    C -->|"Yes"| D["ElastiCache node-based Valkey"]
    C -->|"No, spiky or unknown"| E["ElastiCache Serverless Valkey"]
    B -->|"No, cache is primary"| F{"Is losing recent writes acceptable"}
    F -->|"Yes, rebuildable"| G["ElastiCache with Multi-AZ replicas and backups"]
    F -->|"No"| H["Amazon MemoryDB"]
```

!!! note "Why MemoryDB is slower for writes"
    ElastiCache replication is asynchronous: the primary acknowledges a write before replicas receive it, so a failover can lose the most recent writes. MemoryDB acknowledges writes only after they are persisted to its distributed transaction log across multiple AZs, which adds single-digit millisecond write latency while reads remain microsecond to sub-millisecond. This is the classic durability versus latency trade-off discussed with PACELC in [Chapter 1.5](../unit1/topic5.md#pacelc-the-extension-that-matters-more-in-practice).

### AWS Service Deep Dive

This section summarises ElastiCache as a service.

#### Purpose

ElastiCache provides a managed, low-latency, shared in-memory tier that absorbs read traffic, holds ephemeral shared state for stateless services, and decouples user-facing latency from the performance of the system of record.

#### Architecture

| Deployment | Architecture | Endpoint model |
|------------|--------------|----------------|
| Node-based, cluster mode disabled | One shard: primary and up to five replicas | Primary endpoint for writes, reader endpoint load-balancing across replicas |
| Node-based, cluster mode enabled | Up to hundreds of shards (indicatively 500 with engine 5.0.6 or later), each with primary and replicas; 16,384 hash slots | Configuration endpoint; the client discovers the slot map with `CLUSTER SLOTS`/`CLUSTER SHARDS` |
| Serverless | AWS-managed fleet that shards and replicates across multiple AZs automatically | A single endpoint (port 6379) plus a reader endpoint (port 6380) for replica reads; clients must support the cluster protocol; TLS is always on |

```mermaid
flowchart LR
    subgraph "Serverless cache"
        EP["Endpoint 6379 and reader 6380"] --> PROXY["AWS-managed proxy layer"]
        PROXY --> S1["Shard group A multi-AZ"]
        PROXY --> S2["Shard group B multi-AZ"]
        PROXY --> S3["Shard group C added automatically"]
    end
    subgraph "Node-based cluster mode enabled"
        CFG["Configuration endpoint"] --> N1["Shard 1 primary and replica"]
        CFG --> N2["Shard 2 primary and replica"]
    end
    APP1["Lambda or ECS client"] --> EP
    APP2["EKS client with slot map"] --> CFG
```

In the node-based models, nodes are placed in a **cache subnet group** (a set of private subnets in the VPC) and protected by security groups, in the same way as an RDS instance.

#### Valkey and Redis OSS Versus Memcached

| Dimension | Valkey and Redis OSS | Memcached |
|-----------|----------------------|-----------|
| Data structures | Strings, lists, sets, sorted sets, hashes, bitmaps, HyperLogLog, streams, geospatial indexes | Strings only |
| Replication | Yes, asynchronous, with automatic failover | None |
| Persistence | RDB snapshots; append-only file (AOF) on some configurations | None |
| Multi-AZ and failover | Yes | No |
| Backup and restore | Yes, snapshots to Amazon S3 | No |
| Transactions and scripting | `MULTI`/`EXEC`, Lua scripts and functions | No |
| Pub/sub and streams | Yes | No |
| Threading | Command execution on one main thread per node, with I/O threading | Multi-threaded |
| Horizontal scaling | Cluster mode with hash slots | Add nodes; client-side consistent hashing |
| Default port | 6379 | 11211 |
| Encryption in transit and at rest | Yes | In-transit encryption on recent versions |
| Typical use | Caching, sessions, leaderboards, rate limiting, queues, geospatial proximity search | Simple, very high-throughput object caching |

!!! tip "The selection heuristic"
    Choose Memcached only when the requirement is genuinely a simple, ephemeral, multi-threaded object cache and losing the entire cache on a node failure is acceptable. In every other case, and that is most cases, Valkey (or Redis OSS) is the correct default, because replication, persistence, failover and richer data structures cost little and remove entire categories of failure.

#### Important Features

| Feature | Strategic significance |
|---------|------------------------|
| Valkey engine | Lower price, open governance, compatibility with Redis OSS clients |
| ElastiCache Serverless | Removes capacity planning; scales within seconds to minutes for growth; suited to per-microservice caches |
| Multi-AZ with automatic failover | Replica promotion when a primary fails; typically completes in seconds to tens of seconds |
| Online resharding and scaling | Add or remove shards and replicas without downtime in cluster mode enabled |
| Data tiering (r6gd node types) | Keeps hot data in memory and colder data on local NVMe SSD, reducing cost for large, skewed datasets |
| Global Datastore | Cross-Region replication for node-based Valkey and Redis OSS clusters |
| IAM authentication | Short-lived SigV4 tokens instead of static passwords for Valkey and Redis OSS 7.0+ |
| RBAC users and user groups | Per-application users with command and key-pattern permissions |
| Encryption in transit and at rest | TLS and KMS |
| Backups and snapshots | Point-in-time snapshots to warm a new cluster or migrate |
| Vector search | Vector similarity search for semantic caching of generative AI responses, generally available since October 2025 on Valkey 8.2 node-based clusters; Valkey 9.0 adds full-text and hybrid search; verify deployment support |

#### Limitations

- Asynchronous replication means failover can lose the latest writes, unless the optional Multi-AZ transaction log introduced with ElastiCache for Valkey 9.0 (May 2026) is enabled in synchronous mode; verify deployment support before relying on it.
- Multi-key operations in cluster mode require keys in the same hash slot (use hash tags such as `{user:42}:cart`).
- Online scaling in cluster mode migrates hash slots between shards, which can cause brief elevated latency.
- Memcached offers no replication, persistence, failover or backup at all.
- Memory is expensive per GB compared with disk-based stores.
- Not accessible from outside the VPC without additional networking.
- Serverless imposes per-cache maximums on storage and ECPU throughput (indicatively several terabytes of data and millions of ECPUs per second; verify in Service Quotas) and does not expose parameter groups.
- Global Datastore is not available for Serverless caches; verify current support.

#### Pricing Model and recommendations

| Deployment | Billing dimensions (indicative, as of 2026; verify in the Pricing Calculator) | Recommendation |
|------------|-------------------------------------------------------------------------------|----------------|
| Node-based | Per node-hour by node type; reserved nodes for one or three years; backup storage beyond the free allowance; cross-AZ and cross-Region data transfer | Right-size nodes to memory and CPU needs; buy reserved nodes for steady baseline |
| Serverless | GB-hours of data stored (with a minimum per cache) and ECPUs consumed; an ECPU roughly corresponds to a simple command on a small payload, and larger payloads consume more | Excellent for spiky and small workloads; compare with node-based for large, steady workloads |
| Engine choice | Valkey is priced lower than Redis OSS for both node-based and Serverless | Default to Valkey |
| Global Datastore | Nodes in each Region plus cross-Region data transfer | Use only where multi-Region low-latency reads justify it |

#### Performance Characteristics

- Sub-millisecond latency for simple commands from clients in the same AZ.
- Each Valkey or Redis OSS shard executes commands on a main thread; enhanced I/O threading offloads network processing, so one shard can serve hundreds of thousands of simple operations per second on larger nodes.
- Latency increases with value size, command complexity (`KEYS`, `SMEMBERS` on huge sets, large `ZRANGE`), and cross-AZ hops.
- Network bandwidth per node is often the real limit for large values; watch `NetworkBandwidthOutAllowanceExceeded`.

#### Scaling Behaviour

| Dimension | Node-based | Serverless |
|-----------|-----------|------------|
| Memory | Scale up node type or add shards | Automatic |
| Read throughput | Add replicas; replica reads | Automatic; reader endpoint for replica reads |
| Write throughput | Add shards | Automatic |
| Hot key | Replicas and key replication | Automatic scaling cannot split one key; the same mitigations apply |
| Connections | Per node limit (`maxclients` indicatively 65,000) | Managed; per-cache connection limits apply |

#### Availability

- Deploy at least one replica per shard in a different AZ with Multi-AZ enabled; the ElastiCache SLA applies to Multi-AZ configurations.
- Serverless caches replicate across multiple AZs automatically.
- Design the application so that a cache outage degrades performance rather than breaking functionality: timeouts, circuit breakers ([Chapter 4.3](../unit4/topic3.md)), and fallbacks to the database with load shedding.

#### Security Features

VPC-only placement, security groups, TLS in transit, KMS at rest, AUTH tokens, RBAC, IAM authentication, CloudTrail for API calls, and compliance programmes including PCI DSS and HIPAA eligibility for supported configurations.

#### Service Limits

Indicative, as of 2026; verify in Service Quotas.

| Limit | Indicative value |
|-------|------------------|
| Nodes per Region per account | 300 (adjustable) |
| Shards per cluster (cluster mode enabled) | 500 |
| Replicas per shard | 5 |
| Maximum client connections per node | 65,000 |
| Maximum value size for a string | 512 MB (keep values far smaller in practice) |
| Global Datastore secondary Regions | 2 |
| IAM authentication token validity | 15 minutes to establish a connection; connections are closed after 12 hours and must re-authenticate |

### Important AWS Terminology

| Term | Meaning |
|------|---------|
| Node | A single cache instance of a chosen node type |
| Shard (node group) | A primary node plus up to five replicas, owning a range of hash slots |
| Replication group | The full set of shards forming one Valkey or Redis OSS deployment |
| Cluster mode | Setting that allows multiple shards (enabled) or restricts the deployment to one shard (disabled) |
| Hash slot | One of 16,384 buckets of the keyspace; a key's slot is `CRC16(key) mod 16384` |
| Primary, reader and configuration endpoints | DNS names for writes, for load-balanced replica reads, and for cluster topology discovery respectively |
| Cache subnet group | The set of VPC subnets in which cache nodes are placed |
| Auto Discovery | Memcached configuration endpoint that lets clients learn the current node list |
| Consistent hashing | Client-side key-to-node mapping used by Memcached that remaps only a fraction of keys when nodes change |
| RDB snapshot and AOF | Point-in-time backup of the dataset, and a log of write commands, respectively |
| Cache-aside | Pattern in which the application loads data into the cache on a miss (lazy loading) |
| Write-through | Pattern in which every write updates the database and the cache together |
| Write-behind | Pattern in which writes go to the cache and are persisted to the database asynchronously |
| Valkey | Open-source, Linux Foundation governed fork of Redis OSS, supported by ElastiCache and MemoryDB |
| ElastiCache Serverless | Deployment option that scales capacity automatically and bills by data stored and ECPUs |
| ECPU | ElastiCache Processing Unit; the unit of compute billing for Serverless, based on vCPU time and data transferred per request |
| Read-through | Pattern in which a caching layer loads missing data from the source on behalf of the caller |
| Refresh-ahead | Pattern in which popular entries are refreshed before they expire |
| Soft expiry | A logical expiry timestamp stored with a value, earlier than its physical TTL, used for serve-stale and refresh-ahead |
| TTL jitter | Randomisation added to TTLs to prevent synchronised expiry |
| Cache stampede | Many concurrent recomputations of the same missing or expired key |
| XFetch | Probabilistic early expiration algorithm that prevents stampedes without coordination |
| Request coalescing | Merging concurrent in-process requests for the same key into one load, also called single-flight |
| Negative caching | Caching the fact that an item does not exist |
| Cache penetration | Requests for non-existent keys that repeatedly bypass the cache and reach the database |
| Hot key | A key receiving a disproportionate share of traffic, concentrating load on one shard |
| Hash tag | The part of a key within braces, such as `{user:42}`, that alone is hashed so related keys share a slot |
| Client-side caching | Caching in the application process with server-assisted invalidation through `CLIENT TRACKING` |
| Eviction policy | The `maxmemory-policy` rule deciding which keys are removed when memory is full |
| RBAC | Role-based access control with ElastiCache users and user groups, each user having an access string |
| Access string | Rule syntax such as `on ~session:* +@read +@write -@dangerous` defining keys and commands a user may use |
| IAM authentication | Authentication using a SigV4-signed token generated from an IAM identity |
| Global Datastore | Cross-Region replication of a node-based cluster to up to two secondary Regions |
| MemoryDB | Durable, in-memory database service compatible with Valkey and Redis OSS |
| Semantic cache | A cache keyed by embedding similarity, used to reuse responses of large language models for similar prompts |

### Configuration Options

#### Eviction policy choice

When memory reaches `maxmemory`, the engine applies `maxmemory-policy`. The ElastiCache default parameter group uses `volatile-lru`, which evicts only keys that have a TTL.

| Policy | Evicts | Choose when |
|--------|--------|-------------|
| `volatile-lru` (ElastiCache default) | Least recently used keys among keys with TTL | Mixed use: cache keys with TTL alongside persistent keys without TTL |
| `allkeys-lru` | Least recently used among all keys | Pure cache where every key is disposable |
| `allkeys-lfu` | Least frequently used among all keys | Pure cache with stable popularity skew; better at keeping long-term hot keys |
| `volatile-lfu` | Least frequently used among keys with TTL | Mixed use with skewed popularity |
| `volatile-ttl` | Keys with the nearest expiry first | TTLs encode priority |
| `allkeys-random`, `volatile-random` | Random | Uniform access patterns; rare |
| `noeviction` | Nothing; writes fail with an out-of-memory error | The data is not a cache (queues, locks, sessions that must not silently disappear) |

!!! danger "volatile-lru with keys that have no TTL"
    If an application writes cache entries without TTLs under the default `volatile-lru` policy, the engine has nothing eligible to evict. Memory fills, and writes begin to fail with OOM errors even though the workload is a cache. Either set TTLs on every cache key or use `allkeys-lru`/`allkeys-lfu` for a pure cache.

!!! tip "Separate caches for separate semantics"
    Do not mix disposable cache entries and must-not-lose state such as rate-limit windows or sessions in one cluster with one eviction policy. Separate them into different caches (easy with Serverless) so that each has the right policy, sizing and alarms.

#### Connectivity from compute platforms

| Platform | Network placement | Credentials and secrets | Connection behaviour |
|----------|------------------|------------------------|----------------------|
| Lambda | Function attached to private subnets in the cache's VPC; security group allowed on 6379/6380 by the cache SG | IAM authentication with the execution role, or an AUTH token from Secrets Manager fetched at initialisation | Create the client outside the handler so warm invocations reuse the connection; small pool per environment |
| ECS on Fargate or EC2 | `awsvpc` task ENIs in private subnets; task SG referenced by cache SG | Task role for IAM auth, or `secrets` from Secrets Manager injected as environment variables | Connection pool per task sized to concurrency |
| EKS | Pods in VPC CNI subnets; with security groups for pods, per-pod SGs; otherwise node SG | EKS Pod Identity role for IAM auth; Secrets Store CSI driver or External Secrets for tokens | Pool per pod; beware thousands of pods times pool size |

#### IAM authentication and RBAC

IAM authentication (Valkey 7.2+ and Redis OSS 7.0+, with TLS required) works as follows:

1. Create an ElastiCache user with authentication mode `iam`; the user ID and user name must be identical.
2. Add the user to a user group attached to the cache.
3. Grant the workload role `elasticache:Connect` on both the cache (replication group or serverless cache) and the user ARN.
4. The client generates a SigV4 presigned token (valid for 15 minutes) and uses it as the password in the `AUTH`/`HELLO` command with the user name.
5. Connections authenticated with IAM are closed after 12 hours; clients must reconnect with a fresh token, which cluster-aware libraries can do through a credential provider callback.

```mermaid
sequenceDiagram
    participant Pod as "EKS pod with Pod Identity"
    participant STS as "Pod Identity Agent"
    participant App as "Client library"
    participant EC as "ElastiCache Valkey"
    Pod->>STS: "Obtain role credentials"
    App->>App: "Sign presigned connect URL with SigV4, token valid 15 minutes"
    App->>EC: "TLS connect then AUTH cart-svc token"
    EC->>EC: "Verify signature and elasticache Connect permission"
    EC-->>App: "OK, RBAC access string applied"
    Note over App,EC: "Connection re-authenticated before 12 hour limit"
```

RBAC access strings apply least privilege at the command and key level:

| Service user | Access string | Effect |
|--------------|---------------|--------|
| `cart-svc` | `on ~cart:* ~{user:*}:cart +@read +@write +@hash -@dangerous` | Only cart keys; no administrative commands |
| `ratelimit-svc` | `on ~rl:* +incr +expire +ttl +evalsha +eval` | Only rate-limit keys and scripts |
| `ops-readonly` | `on ~* +@read +info -keys` | Read-only diagnostics without `KEYS` |
| `default` | Disabled or `off` | Prevents unauthenticated access with the default user |

#### Client libraries and cluster awareness

| Language | Common cluster-aware clients | Notes |
|----------|------------------------------|-------|
| Multiple | Valkey GLIDE (AWS-sponsored, Rust core with Python, Java, Node.js and Go bindings) | Designed for cluster topology changes, reconnection and IAM integration; verify feature coverage per language |
| Python | `redis-py` (`RedisCluster`), `valkey-py` | Use `RedisCluster` for cluster mode and Serverless |
| Java | Lettuce, Jedis (`JedisCluster`), Redisson | Lettuce is non-blocking and suits reactive services |
| Node.js | `ioredis` (`Cluster`), `node-redis` | Enable `dnsLookup` handling for TLS with cluster endpoints as documented |
| Go | `go-redis` (`ClusterClient`) | Supports read-from-replica routing |

A cluster-aware client maintains a map of slots to nodes, follows `MOVED` and `ASK` redirections during resharding and failover, and refreshes the topology periodically. A non-cluster client connected to a cluster endpoint will fail with `MOVED` errors on keys owned by other shards.

#### Connection pooling and timeouts

| Setting | Recommendation | Reason |
|---------|----------------|--------|
| Pool size | Small, matched to concurrent in-flight requests per process | Every connection consumes server memory; thousands of pods with large pools exhaust `maxclients` |
| Connect timeout | Short, for example 1 to 2 seconds | Fail fast during failover |
| Command timeout | Tight, for example 50 to 250 ms for cache reads | A slow cache must not be slower than the database it protects |
| Retries | Few, with exponential backoff and jitter | Avoid retry storms ([Chapter 4.3](../unit4/topic3.md)) |
| Keepalive | Enabled | Detect dead connections through NAT and load balancers |
| Topology refresh | Periodic and on `MOVED` | Adapt to scaling and failover |
| DNS caching | Respect low TTLs | Endpoints resolve to new IPs after failover |

### AWS Best Practices

- **Operational Excellence:** Define caches, parameter groups, users and alarms in IaC ([Chapter 5.3](../unit5/topic3.md)), and test failover with the `TestFailover` API.
- **Operational Excellence:** Treat the key schema and serialisation format as a versioned contract by including schema versions in keys.
- **Security:** Enable TLS and encryption at rest, use IAM authentication or RBAC with per-service users, and disable the default user.
- **Security:** Restrict security groups to specific client security groups, and never cache secrets or sensitive personal data without justification.
- **Reliability:** Use Multi-AZ with automatic failover and at least one replica per shard, set a TTL on every key, and use MemoryDB when the in-memory data is the system of record.
- **Performance Efficiency:** Use cluster-aware clients, pipelining, connection reuse and replica reads, and keep values small.
- **Cost Optimization:** Default to Valkey, use Serverless for spiky workloads and reserved nodes for steady baselines, and right-size memory from hit ratio and evictions.
- **Sustainability:** Consolidate idle caches; a well-tuned cache also reduces database compute and network transfer.

### Industry Use Cases

| Industry | Use case | Strategy |
|----------|----------|----------|
| E-commerce | Product pages, carts, flash sales | CloudFront for pages, ElastiCache for product projections with event-driven invalidation, key replication for hot flash-sale items, sessions in ElastiCache |
| Gaming | Real-time leaderboards and matchmaking | Sorted sets; MemoryDB when rankings are the system of record |
| Financial services | Market data fan-out, rate limiting of trading APIs, fraud feature lookups | Pub/sub and sorted sets; strict TTLs; IAM authentication and encryption |
| Media streaming | User profiles, entitlements, recommendations | Cache-aside with refresh-ahead; Global Datastore for multi-Region reads |
| Travel | Caching expensive third-party availability searches | TTL aligned to supplier freshness; negative caching for empty searches |
| SaaS platforms | Per-tenant configuration and throttling | Versioned namespaces per tenant; token bucket rate limits |
| Advertising technology | Frequency capping and bidding features at very high throughput | Counters with short TTLs; large clusters with replica reads |
| Education platforms | Session stores and quiz leaderboards for spiky exam traffic | ElastiCache Serverless to absorb bursts |

### Advantages

| Advantage | Explanation |
|-----------|-------------|
| Latency reduction | Sub-millisecond reads remove slow dependencies from the request path |
| Database offload | Fewer reads allow smaller or fewer database instances and lower DynamoDB capacity |
| Enables stateless compute | Sessions and shared state move out of tasks and pods |
| Rich data structures | Sorted sets, hashes, streams and scripts solve problems beyond key-value caching |
| Managed operations | Failover, patching, scaling, backups and encryption are handled by AWS |
| Serverless option | Capacity planning disappears for spiky workloads |
| Strong security integration | IAM authentication, RBAC, KMS, TLS, VPC isolation |
| Multi-Region reads | Global Datastore brings data close to users in other Regions |

### Limitations

| Limitation | Trade-off |
|------------|-----------|
| Staleness | Every cache introduces a consistency window that must be designed and communicated |
| Invalidation complexity | Correct invalidation across microservices requires events, versioning and idempotency |
| Memory cost | Memory is costly per GB; caching everything is wasteful |
| Hidden dependency | High hit ratios can make the cache a critical dependency for database survival |
| Asynchronous replication | Failover may lose recent writes; MemoryDB adds durability with higher write latency |
| Hot keys | Automatic scaling does not split a single key |
| VPC-only access | Lambda functions must be VPC-attached, adding networking design |
| Cluster mode constraints | Multi-key operations limited to one slot |

### Summary

Caching is an architectural strategy, not a component. A cloud-native system offers several caching layers, from CloudFront at the edge through API Gateway, in-process memory, ElastiCache and DAX, to the database buffer pool, and the architect's task is to serve each request from the outermost layer that can answer it correctly while keeping end-to-end staleness within an explicit budget.

The key architectural lessons are:

- ==Choose the pattern from the read-write profile==: cache-aside as the default, write-through for read-after-write data, write-behind only with a durable buffer, and refresh-ahead for predictably hot, expensive data.
- **TTL is a business decision with a safety-net role**; every key needs one, with jitter.
- **Invalidation belongs to events in microservices**: DynamoDB Streams, EventBridge and outbox events decouple writers from caches; versioned keys make bulk invalidation and deployments safe.
- **Protect the system of record**: locks, probabilistic early expiration and request coalescing stop stampedes; negative caching stops penetration; key replication and client-side caching tame hot keys; circuit breakers and capacity headroom prevent the cache from becoming a hidden single point of failure.
- **ElastiCache is also a shared state service** for sessions, rate limits, leaderboards and ephemeral pub/sub; where the in-memory data is the system of record, MemoryDB provides durability.
- **Integrate securely and efficiently**: VPC placement, TLS, IAM authentication with per-service RBAC users, cluster-aware clients, small long-lived connection pools, and observability built on hit ratio, evictions and EngineCPUUtilization.
- **Default to Valkey, and choose Serverless or node-based by workload shape**; use Global Datastore for multi-Region reads with an understanding of its eventual consistency.

## Section Summary

Section 6.1 treated storage as an integration problem rather than a catalogue of services. Amazon S3 is the shared data plane and the most common event source in AWS; Amazon EBS gives stateful containers and instances durable disks at the price of Availability Zone affinity; Amazon EFS lets many tasks and functions share one POSIX namespace; and Amazon ElastiCache accelerates all of them while holding nothing that cannot be rebuilt.

Four lessons carry forward into Sections [6.2](../unit6/topic2.md) and [6.3](../unit6/topic3.md):

- **Access pattern selects the service**, and scope (host, Availability Zone, Region) selects the availability ceiling.
- **Every workload receives its own identity** (task role, Pod Identity association, execution role) scoped to the exact buckets, volumes, access points and cache users it needs.
- **Storage emits events and metrics**; S3 notifications, snapshot events and cache metrics are inputs to the event-driven and observability designs of [Section 6.3](../unit6/topic3.md) and Unit V.
- **Caches and replicas are copies, not truth**; the system of record must always be identifiable, which is the subject of [Section 6.2](../unit6/topic2.md).

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit6.md#61-aws-storage-solutions) · [Interview questions](../interviewquestions/unit6.md#61-aws-storage-solutions).

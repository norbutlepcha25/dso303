# Unit 6: Practice Questions

## 6.1 AWS Storage Solutions

### 6.1.1 Object Storage with Amazon S3

#### Beginner Questions

1. Explain the difference between an object key and a prefix, and why S3 has no real folders.

    ??? success "Check your answer"

        A good answer covers:

        - **Key:** the full, unique name of an object within a bucket, a single flat string such as `logs/2026/08/10/app-server-01.log.gz`.
        - **Prefix:** any leading substring of a key, conventionally delimited by `/`; prefixes scope IAM policies and lifecycle rules and partition request-rate scaling.
        - **No folders:** the data model is a flat map from key strings to objects; a "folder" created in the console is a zero-byte object whose key ends in `/`.
        - **Folder-like listings:** passing a delimiter to `ListObjectsV2` rolls keys that share a common prefix into `CommonPrefixes`, which produces the appearance of a folder listing.

2. Which mechanism delivers S3 credentials to a Lambda function, and why should application code not pass credentials explicitly to the SDK client?

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** the Lambda execution role; the service assumes it and injects temporary credentials into the environment, where the SDK default credential chain finds them.
        - **Rotation:** the credentials are short-lived and refreshed automatically, so nothing needs to be rotated by the team.
        - **Why not explicit credentials:** hard-coded or configured access keys are long-lived, can leak through code, logs or images, bypass the role's least-privilege design and make CloudTrail attribution unclear.

3. Name the three destination types supported by S3 Event Notifications.

    ??? success "Check your answer"

        A good answer covers:

        - **Lambda functions:** invoked asynchronously for each event.
        - **SQS standard queues:** for buffering and controlled consumption (FIFO queues are not supported as direct destinations).
        - **SNS standard topics:** for fan-out to several subscribers.
        - **Beyond these three:** the separate EventBridge integration sends all events to the default bus for richer routing.

4. What does HTTP status 412 indicate when returned by a PutObject request that included `If-None-Match: *`?

    ??? success "Check your answer"

        A good answer covers:

        - **Meaning:** 412 Precondition Failed; the condition was not met because an object already exists at that key.
        - **Effect:** the write was rejected atomically, so the existing object was not overwritten.
        - **Use:** this is the create-if-absent primitive; the caller should treat 412 as "someone else already wrote it", for example a lock already held or an idempotent duplicate.

5. Why is a Gateway endpoint recommended for ECS tasks in private subnets that read from S3?

    ??? success "Check your answer"

        A good answer covers:

        - **Private path:** traffic from private subnets reaches S3 through a route table entry, without a NAT gateway or internet gateway.
        - **Cost:** Gateway endpoints for S3 have no hourly or data processing charge, unlike NAT gateway data processing.
        - **Control:** an endpoint policy can restrict which buckets are reachable, and bucket policies can require `aws:SourceVpce` for a data perimeter.
        - **Alternative:** Interface endpoints are needed only for on-premises or cross-Region access paths, and they are charged.

#### Intermediate Questions

1. Compare how an EC2 instance, an ECS task, an EKS pod and a Lambda function obtain short-lived credentials for S3, and explain why the same container image can run unchanged on each platform.

    ??? success "Check your answer"

        A good answer covers:

        - **EC2:** an instance profile, with credentials served by the Instance Metadata Service (IMDSv2).
        - **ECS:** the task role (`taskRoleArn`), served through the container credentials endpoint; the task execution role is used by ECS to pull images and write logs and should not carry application S3 permissions.
        - **EKS:** EKS Pod Identity through the Pod Identity Agent, or IRSA, in which a projected service account token is exchanged with STS.
        - **Lambda:** the execution role, whose temporary credentials the runtime injects as environment variables.
        - **Portability:** the AWS SDKs use a default credential provider chain that discovers whichever source is present, so code constructs the S3 client without passing credentials and the same image works on every platform.

2. A Lambda function writes thumbnails back into the bucket that triggers it. Describe two design changes that prevent recursion, and explain what Lambda's recursive loop detection does.

    ??? success "Check your answer"

        A good answer covers:

        - **Separate output location:** write thumbnails to a different bucket, or to a prefix excluded by the trigger's prefix filter (for example trigger on `uploads/`, write to `thumbnails/`).
        - **Filter or marker:** restrict the trigger with a suffix filter, or check object metadata or tags and exit early for objects the function itself produced.
        - **Recursive loop detection:** Lambda detects that the same event chain has invoked the function repeatedly through supported services, including S3, and stops further invocations after a limited number of loops.
        - **Caveat:** loop detection is a safety net that limits cost, not a design; the event is dropped or sent to a failure destination, so the design must still prevent the loop.

3. Compare S3 Event Notifications with the S3 EventBridge integration in terms of enablement, filtering, destinations, multiple consumers, replay and cost, and state when you would use each.

    ??? success "Check your answer"

        A good answer covers:

        - **Enablement:** Event Notifications need a notification configuration per destination; the EventBridge integration is one bucket-level setting that sends all supported events to the default bus.
        - **Filtering:** Event Notifications filter only on event type, key prefix and key suffix; EventBridge rules can match any field, such as key patterns, size, requester or source IP.
        - **Destinations and consumers:** Event Notifications reach Lambda, SQS standard queues and SNS standard topics, and overlapping filters are not allowed, so multiple consumers need SNS fan-out; EventBridge supports many rules with up to five targets each.
        - **Replay and cost:** only EventBridge offers archive and replay; Event Notifications add no S3 charge and have the lowest latency, while EventBridge charges per event.
        - **Choice:** Event Notifications for a single, simple consumer such as one thumbnail function; EventBridge when several teams consume the events, filtering must go beyond prefix and suffix, replay is valuable, or events cross accounts.

4. Describe how S3 Inventory, Athena and Batch Operations can be combined to re-encrypt every object in a bucket that is not encrypted with a specific KMS key.

    ??? success "Check your answer"

        A good answer covers:

        - **Inventory:** configure S3 Inventory to deliver a report (CSV or Parquet) including the encryption status and KMS key ID fields.
        - **Athena:** query the inventory to select every object whose encryption is not SSE-KMS with the target key ARN, and write the result as a CSV manifest of bucket and key.
        - **Batch Operations:** create a job using that manifest with the Copy operation (copy in place) specifying SSE-KMS with the target key and Bucket Keys, using an IAM role with S3 and KMS permissions.
        - **Verification:** review the job completion report for failures, and rerun the Inventory and Athena query to confirm zero remaining objects.

5. Configure, in words, a Terraform S3 backend that supports safe concurrent pipeline runs without a DynamoDB table. What S3 feature makes this possible?

    ??? success "Check your answer"

        A good answer covers:

        - **Backend:** `backend "s3"` with bucket, a key per stack or environment, Region, `encrypt = true` (optionally a KMS key) and `use_lockfile = true`.
        - **Feature:** S3 conditional writes; Terraform creates a `.tflock` object with `If-None-Match`, so only one run can acquire the lock and a second run fails until it is released.
        - **Bucket settings:** versioning enabled for state recovery, Block Public Access, a restrictive bucket policy and least-privilege pipeline roles.
        - **Result:** the DynamoDB lock table is no longer required (it is deprecated for this purpose in recent Terraform versions).

#### Advanced Questions

1. Design an idempotent, exactly-once-effect processing pipeline for S3 uploads using EventBridge, SQS and ECS Fargate consumers. Explain how duplicates, deletes and overwrites are handled.

    ??? success "Check your answer"

        A good answer covers:

        - **Flow:** S3 sends events to EventBridge; a rule filters on bucket, prefix and event types and targets an SQS queue with a DLQ; ECS Fargate workers scale on queue backlog.
        - **Duplicates:** delivery is at least once, so workers record each processed object version (bucket, key, version ID or ETag) in DynamoDB with a conditional write and skip duplicates; outputs use deterministic keys so a reprocess overwrites identically.
        - **Overwrites:** with versioning, each version is a distinct work item; workers compare the event's version or sequencer with the latest processed one and ignore older events that arrive out of order.
        - **Deletes:** `Object Deleted` events trigger idempotent removal of derived outputs, guarded by the same version check so a stale delete does not remove newer output.
        - **Robustness:** visibility timeout longer than processing time, partial failure handling, DLQ alarms and redrive after fixes.

2. A machine learning team proposes to keep all of its training data in S3 Express One Zone. Evaluate the proposal against S3 general purpose buckets in terms of latency, durability scope, bucket model and cost, and design how the two should be used together.

    ??? success "Check your answer"

        A good answer covers:

        - **Latency:** Express One Zone offers single-digit millisecond latency and very high request rates; general purpose buckets deliver the first byte in tens of milliseconds.
        - **Durability scope:** Express One Zone stores data in one Availability Zone in a directory bucket, whereas general purpose storage classes such as S3 Standard span three or more zones, so an AZ failure affects only the Express copy.
        - **Bucket model:** directory buckets use real directories, session-based authentication through `CreateSession` (handled by current SDKs) and names ending in a zone suffix, unlike the flat namespace of general purpose buckets.
        - **Cost:** Express One Zone has lower request charges but higher storage charges than S3 Standard, so it is a performance tier, not bulk storage.
        - **Design:** keep the full dataset in a general purpose bucket as the durable source of truth, copy the active training subset into Express One Zone in the same zone as the training compute, and treat the Express copy as reproducible.

3. Design the storage configuration for a bucket of audit records that must remain immutable for seven years, survive accidental deletion and cost as little as possible, and explain what happens when an operator issues a `DELETE` on one of the records.

    ??? success "Check your answer"

        A good answer covers:

        - **Versioning:** enabled, because Object Lock and replication require it and because every overwrite or delete then preserves earlier versions.
        - **Object Lock:** Compliance mode with a seven-year retention period, because nobody, including the root user, can override it before expiry; Governance mode would let privileged users override it.
        - **Lifecycle:** transition records to S3 Glacier Deep Archive once they are rarely read (its 180-day minimum storage duration is irrelevant for seven-year data), accept restore times of around twelve hours, expire noncurrent versions and abort incomplete multipart uploads.
        - **DELETE behaviour:** a `DELETE` without a version identifier only inserts a delete marker that hides the object; the locked version remains, continues to be billed, and cannot be permanently deleted until its retention period ends.
        - **Optional copy:** Cross-Region Replication to another account for protection against Regional or account-level loss, at roughly double the storage cost.

4. A shared bucket's policy has reached its size limit because 60 applications have statements in it. Propose a migration to Access Points with delegation, including how existing clients are moved without downtime.

    ??? success "Check your answer"

        A good answer covers:

        - **Target design:** one access point per application or team, each with its own policy and optionally a VPC-only network origin; the bucket policy shrinks to a delegation statement (allow when `s3:DataAccessPointAccount` is the owning account) plus guardrails.
        - **Migration steps:** create access points and policies that replicate each application's current statements; grant applications permission to use their access point ARN or alias.
        - **No downtime:** keep the existing bucket statements during transition; move clients one at a time by changing the bucket name to the access point alias, which existing SDK code accepts.
        - **Cut-over:** use CloudTrail data events to confirm each application no longer calls the bucket directly, then remove its old bucket statement.
        - **Outcome:** distributed ownership, smaller blast radius per policy change and policies within size limits.

5. Using conditional writes only, design a stale-lock takeover protocol for a nightly batch job run by several ECS tasks, and analyse the failure scenarios in which two tasks could both believe they hold the lock.

    ??? success "Check your answer"

        A good answer covers:

        - **Acquire:** a task writes `locks/nightly` with `If-None-Match: *`, storing owner ID and a lease expiry; success means it holds the lock, 412 means another holder exists.
        - **Takeover:** if the existing lock's lease has expired, a task reads it with its ETag and overwrites it using `If-Match` on that ETag; only one contender's compare-and-swap succeeds.
        - **Renew and release:** the holder renews with `If-Match` before expiry and deletes or expires the lock when done.
        - **Failure scenario:** a holder paused (garbage collection, network partition, throttling) beyond its lease keeps working while another task takes over, so both believe they hold the lock; clock skew in judging expiry has the same effect.
        - **Mitigation:** fencing tokens (an incrementing generation number checked by the protected resource), idempotent batch steps and leases much longer than renewal intervals; S3 provides no lease semantics itself.

### 6.1.2 Block Storage with Amazon EBS

#### Beginner Questions

1. Why must a pod using an EBS-backed PVC be scheduled in the same Availability Zone as the volume?

    ??? success "Check your answer"

        A good answer covers:

        - **Zonal resource:** an EBS volume exists in one Availability Zone and can attach only to instances in that zone.
        - **Consequence:** once the PV is bound to a volume, the pod must run on a node in that zone, which Kubernetes enforces through the PV's node affinity.
        - **Design implication:** use `WaitForFirstConsumer` binding and ensure node capacity exists in every zone that holds volumes.

2. What is the difference between `reclaimPolicy: Delete` and `reclaimPolicy: Retain` in a StorageClass?

    ??? success "Check your answer"

        A good answer covers:

        - **Delete:** when the PVC is deleted, the PV and the underlying EBS volume are deleted, and the data is lost.
        - **Retain:** the PV and the EBS volume remain after the PVC is deleted, and an administrator must reclaim or delete them manually.
        - **Use:** `Delete` for disposable or easily rebuilt data; `Retain` for production databases where accidental deletion must not destroy data (with snapshots in either case).

3. Which task definition property indicates that an ECS volume will be configured at deployment?

    ??? success "Check your answer"

        A good answer covers:

        - **Property:** `configuredAtLaunch: true` on the task definition's volume.
        - **Effect:** the actual EBS settings (size, type, IOPS, snapshot, KMS key, infrastructure role) are supplied in the service definition or `RunTask` call.
        - **Benefit:** one reusable task definition serves different environments and volume configurations.

4. What does enabling EBS encryption by default change for newly created volumes?

    ??? success "Check your answer"

        A good answer covers:

        - **Effect:** every new volume in that account and Region is encrypted automatically, using the default KMS key (`aws/ebs` or a chosen customer managed key).
        - **Snapshots and copies:** volumes created from unencrypted snapshots are also encrypted.
        - **Scope:** it is a per-Region account setting and does not encrypt existing volumes, which must be migrated through an encrypted snapshot copy.

5. Name two services that automate the creation and retention of EBS snapshots.

    ??? success "Check your answer"

        A good answer covers:

        - **Amazon Data Lifecycle Manager (DLM):** policy-based snapshot and AMI creation, retention and cross-Region or cross-account copy, targeted by tags.
        - **AWS Backup:** centralised backup plans across services and accounts, with vaults, Vault Lock, cross-account copies and compliance reporting.
        - **Either answer pair is acceptable:** for example DLM and AWS Backup.

#### Intermediate Questions

1. Explain how a VolumeSnapshot can be used to clone a production database volume into a test namespace on EKS, and which add-ons are required.

    ??? success "Check your answer"

        A good answer covers:

        - **Add-ons:** the EBS CSI driver and the external snapshot controller with the VolumeSnapshot CRDs, plus a VolumeSnapshotClass for the EBS driver.
        - **Snapshot:** create a VolumeSnapshot of the production PVC; the driver creates an EBS snapshot.
        - **Cross-namespace:** VolumeSnapshots are namespaced, so create a VolumeSnapshotContent referring to the snapshot ID and a VolumeSnapshot in the test namespace (static binding), or recreate it there.
        - **Clone:** create a PVC in the test namespace with `dataSource` referring to that VolumeSnapshot; the driver creates a new volume from the snapshot in the pod's zone.
        - **Controls:** mask personal data before developers use it, and remember that volumes from snapshots load blocks lazily unless Fast Snapshot Restore is used.

2. Compare Data Lifecycle Manager and AWS Backup for protecting EBS volumes across an organisation with 30 accounts.

    ??? success "Check your answer"

        A good answer covers:

        - **DLM:** simple, tag-based, EBS-focused, and configured per account and Region (cross-account through policies); cost-free beyond snapshot storage.
        - **AWS Backup:** organisation-wide backup policies through AWS Organizations, central management and reporting, cross-account and cross-Region copy, Vault Lock immutability and coverage of many services.
        - **For 30 accounts:** AWS Backup with organisation policies and a delegated administrator is the stronger choice for governance and audit; DLM suits narrow EBS-only use cases or AMI lifecycle.
        - **Both:** rely on tags, so tagging standards must be enforced.

3. Explain why gp3 is almost always preferred over gp2, and describe how an existing gp2 volume is moved to gp3.

    ??? success "Check your answer"

        A good answer covers:

        - **Baseline performance:** gp3 includes 3,000 IOPS and 125 MiB/s regardless of size, whereas gp2 provides 3 IOPS per GiB, so 3,000 sustained IOPS on gp2 required a 1,000 GiB volume.
        - **Independent provisioning:** gp3 IOPS and throughput are provisioned independently of capacity, so performance is bought without buying unused storage.
        - **No burst credits:** gp3 delivers consistent provisioned performance, while small gp2 volumes rely on a burst bucket and drop abruptly to baseline when credits run out.
        - **Price:** gp3 costs roughly twenty percent less per GiB than gp2.
        - **Migration:** an online `ModifyVolume` operation through Elastic Volumes changes the type while the volume stays attached.

4. Compare instance store with Amazon EBS, and give two workloads for which instance store is a deliberate and correct choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Instance store:** NVMe or SSD storage physically attached to the host, offering the highest I/O performance because no network is involved.
        - **Ephemeral data:** instance store data is lost when the instance stops, hibernates or terminates, or when the underlying hardware fails.
        - **EBS:** network-attached block storage in one Availability Zone whose data persists independently of the instance and can be snapshotted.
        - **Correct uses of instance store:** scratch space, caches, temporary shuffle data in Spark, and replicated distributed databases such as Cassandra that keep their own copies across nodes.
        - **Design error:** a single-copy production database on instance store, because data loss is a design property of the storage, not bad luck.

5. When would you choose ECS task-attached EBS volumes rather than Amazon EFS for an ECS service?

    ??? success "Check your answer"

        A good answer covers:

        - **Task-attached EBS:** for per-task, single-writer block storage with low latency, such as scratch space, build caches, data processing or databases seeded from snapshots, where data need not be shared.
        - **EFS:** when several tasks must share files concurrently, or data must persist independently of tasks across AZs.
        - **Trade-off:** EBS gives block performance and snapshot seeding but a new volume per task in one AZ; EFS gives shared multi-AZ persistence with NFS latency and per-GB pricing.

#### Advanced Questions

1. Design a multi-tenant Kubernetes platform that offers three storage tiers (standard, fast and archive-backed) using StorageClasses, VolumeAttributesClasses and snapshot policies. Explain how tenants select tiers and how costs are attributed.

    ??? success "Check your answer"

        A good answer covers:

        - **StorageClasses:** `standard` (gp3 baseline), `fast` (gp3 with higher IOPS and throughput, or io2 for critical databases) and an archive-backed class, all encrypted with a tenant or platform KMS key and `WaitForFirstConsumer`.
        - **VolumeAttributesClasses:** let tenants change IOPS and throughput of an existing volume (for example standard to fast) without recreating it.
        - **Snapshot policies:** VolumeSnapshotClasses plus AWS Backup or DLM policies selected by tags; the archive tier moves older snapshots to EBS Snapshots Archive.
        - **Tenant selection:** tenants name the class in their PVC; admission policies (for example Kyverno or Gatekeeper) and ResourceQuotas per namespace restrict which classes and how much storage each tenant may use.
        - **Cost attribution:** the CSI driver propagates tags (namespace, PVC, tenant) to volumes and snapshots, activated as cost allocation tags and reported in Cost Explorer.

2. Design an availability and recovery plan for a self-managed PostgreSQL cluster running on EBS-backed EKS nodes, covering instance failure, volume impairment, Availability Zone impairment, Regional impairment and logical corruption. For each, state how the failure is detected and how the service recovers.

    ??? success "Check your answer"

        A good answer covers:

        - **Instance failure:** the volume survives; node health checks detect the failure and the orchestrator reschedules the pod to another node in the same zone, where the volume is reattached.
        - **Volume impairment:** detected through the attached EBS status check and stalled I/O alarms; recovery is failover to a database replica on another volume.
        - **Availability Zone impairment:** volumes are zonal, so replicas must already run in other zones (topology-aware scheduling with `WaitForFirstConsumer`), or data is restored from Regional snapshots into a surviving zone.
        - **Regional impairment:** cross-Region snapshot copies automated by Data Lifecycle Manager or AWS Backup, plus infrastructure as code to rebuild the cluster in the recovery Region.
        - **Logical corruption or deletion:** replication copies the damage, so recovery uses point-in-time snapshots, Recycle Bin for deleted snapshots and AWS Backup Vault Lock against malicious deletion.
        - **Validation:** restores are tested regularly and failover is rehearsed with Fault Injection Service EBS I/O actions.

3. Design a ransomware-resilient backup architecture for EBS-based workloads using AWS Backup, logically separate accounts, Vault Lock, Recycle Bin and SCPs, and describe the restore procedure.

    ??? success "Check your answer"

        A good answer covers:

        - **Separate account:** AWS Backup in workload accounts copies recovery points to a dedicated backup account in the organisation, with a separate KMS key and no standing administrator access.
        - **Immutability:** the backup vault uses Vault Lock in compliance mode with minimum retention, so even the root user cannot delete recovery points early.
        - **Recycle Bin:** retention rules with rule lock in workload accounts keep deleted snapshots and AMIs recoverable for a period.
        - **SCPs:** deny deleting vaults, changing Vault Lock, deleting or unlocking Recycle Bin rules and disabling CloudTrail, except for a break-glass role; GuardDuty and CloudTrail alerts on suspicious deletion.
        - **Restore procedure:** declare an incident, choose a recovery point from before the compromise, restore or copy it into a clean recovery account or VPC, scan it, validate the application, then repoint traffic; rehearse this regularly.

4. Using AWS Fault Injection Service, design an experiment programme to validate a self-managed PostgreSQL cluster's failover behaviour, including hypotheses, stop conditions, metrics and expected outcomes.

    ??? success "Check your answer"

        A good answer covers:

        - **Hypotheses:** for example "if the primary's EBS volume I/O is paused, the cluster manager (such as Patroni) promotes a replica within 60 seconds with no committed transactions lost".
        - **Experiments:** EBS I/O pause on the primary's volume, termination of the primary instance or pod, AZ-level network disruption, and increased latency on replicas, each run first in staging.
        - **Stop conditions:** CloudWatch alarms on error rate, latency and replication lag beyond agreed thresholds stop the experiment automatically.
        - **Metrics:** failover time, write availability gap, client error rate, replication lag, data loss check (sequence numbers or checksums), and time to rebuild the failed node.
        - **Expected outcomes and programme:** promotion within the objective, clients reconnect through the service endpoint, no lost acknowledged writes; run on a schedule and after each major change, recording results and fixing gaps.

5. A backup vendor proposes to use the EBS direct APIs to perform incremental backups of 5,000 volumes to an on-premises system. Analyse the benefits, the IAM and KMS requirements, the cost dimensions and the risks of this design.

    ??? success "Check your answer"

        A good answer covers:

        - **Benefits:** `ListChangedBlocks` and `GetSnapshotBlock` read only changed blocks between snapshots, so incremental backups are efficient without creating or attaching volumes.
        - **IAM and KMS:** the vendor role needs `ebs:ListSnapshotBlocks`, `ebs:ListChangedBlocks` and `ebs:GetSnapshotBlock` (scoped by tags or resources) plus `kms:Decrypt` on the encrypting keys through key policies or grants, ideally via a cross-account role rather than access keys.
        - **Cost dimensions:** per-request charges for direct API calls (large for 5,000 volumes), snapshot storage, and data transfer out of AWS to on-premises, which may dominate.
        - **Risks:** a third party gains read access to all block data, API throttling at scale, network bandwidth limits, and consistency (crash-consistent snapshots only unless applications are quiesced).
        - **Mitigation:** least-privilege, auditable access with CloudTrail, encrypted transport, rate limiting, and comparing against AWS Backup cross-account copies as a simpler alternative.

### 6.1.3 File Storage with Amazon EFS

#### Beginner Questions

1. Which TCP port must be allowed from clients to EFS mount targets?

    ??? success "Check your answer"

        A good answer covers:

        - **Port:** TCP 2049 (NFS).
        - **Where:** the mount target security group must allow inbound 2049 from the client security groups (instances, tasks, pods or Lambda functions).
        - **Network ACLs:** must also allow the traffic and its return path.

2. What prefix must a Lambda function's EFS local mount path begin with?

    ??? success "Check your answer"

        A good answer covers:

        - **Prefix:** `/mnt/`, for example `/mnt/models`.
        - **Consequence:** any other local mount path is rejected by the Lambda configuration.

3. Which Kubernetes access mode allows many pods on different nodes to mount the same EFS volume read-write?

    ??? success "Check your answer"

        A good answer covers:

        - **Access mode:** `ReadWriteMany` (RWX).
        - **Contrast:** EBS volumes support only `ReadWriteOnce`, because a volume attaches to one node in one zone.

4. Which ECS IAM role supplies credentials to EFS when `iam: ENABLED` is set in the task definition?

    ??? success "Check your answer"

        A good answer covers:

        - **Role:** the task role (`taskRoleArn`), which represents the application.
        - **Not the execution role:** the execution role is used by the agent for image pulls, secrets and logs; EFS permissions placed there cause access denied when IAM authorisation is enabled.
        - **Permissions:** `elasticfilesystem:ClientMount` and, if writing, `ClientWrite`, allowed by the file system policy.

5. Name two AWS services that protect EFS data against, respectively, accidental deletion and Regional failure.

    ??? success "Check your answer"

        A good answer covers:

        - **Accidental deletion:** AWS Backup, which provides point-in-time recovery points for files and file systems.
        - **Regional failure:** EFS Replication, which keeps a read-only copy in another Region that can be promoted.

#### Intermediate Questions

1. Compare static and dynamic provisioning with the EFS CSI driver, and give one scenario suited to each.

    ??? success "Check your answer"

        A good answer covers:

        - **Static provisioning:** an administrator creates the PV that points at an existing file system or access point; suited to one shared content directory used by all replicas of a Deployment, or any workload on EKS Fargate.
        - **Dynamic provisioning:** the CSI driver creates an access point per PVC (`efs-ap` mode) from a StorageClass; suited to a multi-tenant platform where each user or team receives an isolated directory automatically.
        - **Trade-off:** static is explicit and auditable but manual; dynamic is self-service but consumes access points (the AWS default quota is 10,000 access points per file system).

2. Explain how `gidRangeStart` and `gidRangeEnd` provide isolation between PVCs in `efs-ap` mode.

    ??? success "Check your answer"

        A good answer covers:

        - **Allocation:** in `efs-ap` mode, each dynamically created access point receives a unique POSIX uid and gid drawn from the range `gidRangeStart` to `gidRangeEnd`.
        - **Enforcement:** the access point forces that identity for every operation and roots the client in its own directory created with restrictive permissions.
        - **Isolation:** files of one PVC are owned by an identity no other PVC uses, so one tenant cannot read another's directory even on the same file system.
        - **Planning:** reserve a range that does not clash with other users and is large enough for the expected number of PVCs.

3. Write a file system policy statement that denies all access without TLS.

    ??? success "Check your answer"

        A good answer covers:

        - **Effect:** `Deny` for all principals (`"Principal": {"AWS": "*"}`) on `"Action": "*"` for the file system resource.
        - **Condition:** `"Bool": {"aws:SecureTransport": "false"}`.
        - **Client side:** clients must mount with TLS (`-o tls` with efs-utils, or `encryptInTransit` in ECS and the CSI driver) or the mount is refused.
        - **Example statement:** `{"Effect":"Deny","Principal":{"AWS":"*"},"Action":"*","Resource":"<file system ARN>","Condition":{"Bool":{"aws:SecureTransport":"false"}}}`.

4. A workload repeatedly reads 500 GB of data per day from EFS under Elastic throughput. How would you estimate and reduce its throughput cost?

    ??? success "Check your answer"

        A good answer covers:

        - **Estimate:** Elastic throughput charges per GB read and per GB written; 500 GB per day is about 15,000 GB per month of reads, multiplied by the Regional per-GB read price (verify in the pricing calculator).
        - **Cache:** keep the hot data in memory or on local or instance storage and reread from EFS only when it changes.
        - **Alternative modes:** if the throughput is steady, compare with Provisioned throughput, which charges a fixed rate per MiB/s and can be cheaper for continuous load.
        - **Different store:** if the data is read-only and object-friendly, serve it from S3 (possibly with Mountpoint and caching) instead.
        - **Monitor:** `DataReadIOBytes` and `MeteredIOBytes` to confirm the effect of changes.

5. Why does EKS on Fargate support only static provisioning of EFS volumes, and how does this affect platform design?

    ??? success "Check your answer"

        A good answer covers:

        - **Reason:** on Fargate the EFS client is built into the platform and pods cannot run the CSI controller with privileges to create access points, so only pre-created PVs are supported.
        - **Platform impact:** the platform team must pre-create file systems, access points and PVs (through IaC) for every Fargate workload.
        - **Design response:** provide a request process or GitOps template for new volumes, or run workloads needing dynamic provisioning on EC2 nodes.

#### Advanced Questions

1. Recommend a throughput mode and lifecycle configuration for four workloads in one organisation's EFS estate: WordPress uploads on ECS, an ML model store for Lambda, a CI build cache and shared notebook home directories on EKS. Identify one kind of workload for which EFS should not be used, and justify your recommendations.

    ??? success "Check your answer"

        A good answer covers:

        - **WordPress uploads:** Elastic throughput; transition to Infrequent Access after 30 days and back to Standard on first access.
        - **ML model store:** Elastic throughput; keep current models in Standard and move old versions to IA, and monitor `MeteredIOBytes` because many environments repeatedly loading large models make Elastic charges grow.
        - **CI build cache:** Elastic, or Provisioned if the load is steady and heavy; short retention with clean-up by job.
        - **Notebook home directories:** Elastic; IA after 30 days and Archive after 90 days.
        - **Not EFS:** long-running HPC scratch belongs on FSx for Lustre, and transactional databases belong on RDS, Aurora or DynamoDB rather than a shared file system.
        - **Justification:** Elastic suits spiky and unknown demand and avoids the Bursting-mode trap of small file systems; General Purpose performance mode gives the lowest latency for all four.

2. A build system that performs millions of small-file `stat()`, `open()` and `readdir()` calls is moved onto EFS and becomes much slower than it was on local disk. Using the EFS architecture, explain the cause and propose design changes.

    ??? success "Check your answer"

        A good answer covers:

        - **Cause:** EFS separates a distributed metadata layer from a data layer across Availability Zones, so every file operation, including metadata operations, is a network round trip through the mount target.
        - **Misleading figures:** headline throughput is an aggregate over many parallel clients; a single process working file by file sees per-operation latency, not aggregate throughput.
        - **Directory shape:** very large flat directories slow `readdir` and `lookup`, so directories should be sharded by prefix.
        - **Parallelism:** issue I/O across threads, processes and clients so that latency overlaps.
        - **Placement:** keep hot small-file sets local (image layers, `emptyDir`, Lambda `/tmp`) and use EFS only for data that must be shared or is large; keep General Purpose performance mode, since Max I/O raises latency.

3. Analyse five failure modes of an EFS-backed web tier running in three Availability Zones: a mount target missing in one zone, a security group that does not allow NFS, a One Zone file system, the `hard` mount option during a loss of connectivity, and an accidental recursive delete. For each, state the symptom and the design control.

    ??? success "Check your answer"

        A good answer covers:

        - **Missing mount target:** clients in that zone cannot reach a zone-local mount target, so mounts hang and time out; create a mount target in every zone the compute tier uses, otherwise a Regional file system does not protect those clients.
        - **Security group:** the NFS client retries silently until it times out; the mount target security group must allow inbound TCP 2049 from the client security groups.
        - **One Zone file system:** a zone failure makes the file system unavailable to every replica; use a Regional file system for production.
        - **`hard` mount option:** I/O is retried indefinitely, which preserves integrity but hangs processes while the file system is unreachable; health checks and timeouts must detect and replace hung replicas.
        - **Recursive delete:** replication protects against Regional failure, not logical deletion; restore from AWS Backup recovery points, which support item-level restore.

4. Describe how you would detect and alert on a Lambda-driven connection surge against an EFS file system, and how you would prevent it from affecting other workloads sharing the file system.

    ??? success "Check your answer"

        A good answer covers:

        - **Detect:** CloudWatch alarms on `ClientConnections`, `PercentIOLimit` (where applicable), `MeteredIOBytes` and throughput utilisation, plus Lambda `ConcurrentExecutions`.
        - **Alert:** anomaly detection or threshold alarms routed to the owning team through SNS or incident tooling.
        - **Prevent:** cap the function with reserved concurrency, use provisioned concurrency for predictable warm environments, and cache data in the execution environment.
        - **Isolate:** give the Lambda workload its own access point and, if contention persists, its own file system, so a surge cannot affect other workloads.

5. Design the security configuration of a production EFS file system shared by ECS tasks, EKS pods and Lambda functions, and explain how each layer contributes to defence in depth.

    ??? success "Check your answer"

        A good answer covers:

        - **Encryption:** encryption at rest with a KMS key chosen at creation (it cannot be changed later) and TLS in transit through efs-utils.
        - **File system policy:** deny when `aws:SecureTransport` is false; allow `ClientMount` and `ClientWrite` only to named workload roles and only through a mount target; deny `ClientRootAccess` to everyone except a break-glass role.
        - **Identities:** the ECS task role with `iam: ENABLED`, the Lambda execution role with `ClientMount` (and `ClientWrite`) plus VPC permissions, and EKS pods through the CSI driver and access points.
        - **Access points:** one per application or PVC, enforcing a root directory and a fixed POSIX uid and gid, optionally required through the `elasticfilesystem:AccessPointArn` condition.
        - **Network and audit:** mount target security groups allow TCP 2049 only from client security groups, and CloudTrail records mount authorisation events when IAM authorisation is used.
        - **Defence in depth:** IAM decides whether a workload may mount and with which permissions, and the access point decides which directory and identity it sees.

### 6.1.4 Caching Strategies with Amazon ElastiCache

#### Beginner Questions

1. Name four caching layers available in an AWS cloud-native stack, from the edge inward.

    ??? success "Check your answer"

        A good answer covers:

        - **Edge:** CloudFront caches static content and cacheable API responses near users.
        - **API layer:** API Gateway response caching for REST APIs.
        - **Application:** in-process memory caches inside Lambda environments, containers or pods.
        - **Distributed cache:** ElastiCache (Valkey, Redis OSS or Memcached), and DAX in front of DynamoDB.
        - **Database:** the database's own buffer pool, the innermost layer.

2. What is the default eviction policy in the ElastiCache default parameter group, and which keys can it evict?

    ??? success "Check your answer"

        A good answer covers:

        - **Policy:** `volatile-lru`.
        - **Eligible keys:** only keys that have a TTL, choosing the least recently used among them.
        - **Consequence:** keys without a TTL are never evicted, so a cache that writes keys without TTLs can run out of memory and fail writes.

3. Why must a Lambda function that uses ElastiCache be attached to a VPC?

    ??? success "Check your answer"

        A good answer covers:

        - **Network placement:** ElastiCache clusters and serverless caches are reachable only through endpoints inside a VPC, with no public endpoint.
        - **Lambda networking:** a function must be attached to subnets and a security group in that VPC to reach the endpoint.
        - **Security group:** the cache's security group must allow the function's security group on the cache port (for example 6379).

4. What is negative caching?

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** storing the fact that an item does not exist (a sentinel value) with a short TTL.
        - **Purpose:** repeated lookups for missing keys are answered by the cache instead of reaching the database each time.
        - **Problem prevented:** cache penetration, where random or invalid keys bypass the cache and overload the database.

5. Which ElastiCache engine is priced lowest among Valkey and Redis OSS, and why might a new project choose it?

    ??? success "Check your answer"

        A good answer covers:

        - **Lowest price:** Valkey is priced lower than Redis OSS on ElastiCache (AWS cites about 20 percent lower for node-based clusters and about 33 percent lower for Serverless, with a lower minimum data charge).
        - **Compatibility:** Valkey is compatible with Redis OSS clients and commands, so applications usually need no code changes.
        - **Governance:** it is open source under the Linux Foundation, with active development and AWS support.
        - **New project:** lower cost, open licensing and ongoing feature work make it the sensible default.

#### Intermediate Questions

1. Build a decision table choosing between cache-aside, write-through and refresh-ahead for user profiles, stock levels and a homepage aggregate.

    ??? success "Check your answer"

        A good answer covers:

        - **User profiles:** cache-aside with invalidation on update and a moderate TTL; read-heavy, tolerant of brief staleness, loaded on demand.
        - **Stock levels:** write-through, or a short TTL with event-driven invalidation; accuracy matters, but the final check must happen against the database at purchase time.
        - **Homepage aggregate:** refresh-ahead through a scheduled job, because it is expensive to compute, read by everyone and acceptable if a few seconds old.
        - **Table criteria:** read-to-write ratio, staleness tolerance, computation cost and consequence of a stale value.

2. Explain how TTL jitter prevents synchronised expiry, and write a formula for a jittered TTL.

    ??? success "Check your answer"

        A good answer covers:

        - **Problem:** keys written together with the same TTL expire together, producing a burst of misses and database load.
        - **Jitter:** add a random component so expiries spread over a window.
        - **Formula:** `ttl = base + random(0, j × base)`, for example `ttl = 3600 + random(0, 360)` with `j = 0.1`.
        - **Effect:** misses are spread across the jitter window, smoothing recomputation load.

3. Describe the steps to enable IAM authentication for an ECS service connecting to ElastiCache Serverless for Valkey.

    ??? success "Check your answer"

        A good answer covers:

        - **Cache:** create a Valkey serverless cache with encryption in transit (required for IAM authentication) and an IAM-enabled user whose user ID and user name match, added to a user group associated with the cache.
        - **IAM policy:** the ECS task role is allowed `elasticache:Connect` on both the cache and the user resources.
        - **Client:** the application generates a short-lived SigV4 IAM authentication token (valid for 15 minutes) and sends it as the password in the `AUTH` command over TLS.
        - **Connections:** connections are limited to 12 hours, so the client must reauthenticate or reconnect with a fresh token; the security group must allow the task's security group.

4. Compare distributed locks, XFetch and request coalescing for stampede protection.

    ??? success "Check your answer"

        A good answer covers:

        - **Distributed lock:** only one worker recomputes on miss; strongest protection against stampedes, but adds coordination, lock expiry and waiting latency for other readers.
        - **XFetch (probabilistic early expiration):** readers recompute early with increasing probability near expiry; no coordination, but occasional duplicate recomputation.
        - **Request coalescing:** concurrent requests within one process or proxy share a single in-flight load; simple and effective per instance, but does not coordinate across many instances.
        - **Combination:** coalescing within instances plus XFetch or a lock across the fleet, with serve-stale while revalidating.

5. When would you choose ElastiCache Serverless over a node-based cluster, and which metrics would you monitor for each?

    ??? success "Check your answer"

        A good answer covers:

        - **Serverless:** spiky, unpredictable or small workloads, new projects, and teams that do not want to manage nodes or shards; billed by data stored and ECPUs.
        - **Node-based:** steady, large or predictable workloads where reserved nodes reduce cost, or where parameter groups and specific engine settings are needed.
        - **Serverless metrics:** `BytesUsedForCache`, `ElastiCacheProcessingUnits`, throttled commands, hit ratio and latency.
        - **Node-based metrics:** `EngineCPUUtilization`, `DatabaseMemoryUsagePercentage`, `Evictions`, `CurrConnections`, replication lag, network bandwidth and cache hit ratio.

#### Advanced Questions

1. Design an event-driven invalidation pipeline for Aurora-backed data using the transactional outbox pattern, including idempotency and ordering considerations.

    ??? success "Check your answer"

        A good answer covers:

        - **Outbox:** the service writes the data change and an outbox row (entity ID, version, event type) in the same Aurora transaction.
        - **Relay:** a relay (polling or CDC with DMS or Debezium) publishes outbox rows to EventBridge or Kinesis in commit order and marks them sent.
        - **Invalidator:** each consuming service deletes or refreshes its own keys; deletes are naturally idempotent.
        - **Ordering:** include the entity version; refresh only if the event's version is newer than the cached value, or simply delete so readers reload current data.
        - **Safety net:** TTLs on all keys, DLQs on consumers and alarms on relay lag.

2. A flash sale is expected to drive 500,000 reads per second to a single product key. Design the caching architecture end to end, from CloudFront to ElastiCache.

    ??? success "Check your answer"

        A good answer covers:

        - **Edge:** CloudFront caches the product page and API response with a short TTL (seconds), absorbing most of the 500,000 reads per second; origin shield reduces origin requests.
        - **Application:** each API instance keeps an in-process cache of the hot product for a second or two, with request coalescing.
        - **ElastiCache:** replicate the hot key across shards (for example `product:123#0` to `#N`) or read from replicas, so no single shard carries the load.
        - **Stock and price:** handle the authoritative stock decrement separately (DynamoDB conditional writes or a queue), not through the cache.
        - **Protection:** pre-warm caches, load test, rate limit at the edge and keep a stale-while-revalidate fallback.

3. A team must choose in-memory stores for (a) a product catalogue cache backed by Aurora with steady, predictable load, (b) a cache for a new service whose traffic is unknown, and (c) shopping-cart state that is stored nowhere else and must not lose acknowledged writes. Recommend an option for each and justify it with the replication and durability semantics involved.

    ??? success "Check your answer"

        A good answer covers:

        - **(a) Catalogue cache:** node-based ElastiCache for Valkey with Multi-AZ replicas, because the data is also in Aurora, load is predictable, and reserved nodes reduce the cost of a steady baseline.
        - **(b) Unknown traffic:** ElastiCache Serverless for Valkey, which needs no node or shard sizing and bills by GB-hours of data stored and ECPUs consumed.
        - **(c) Cart state:** Amazon MemoryDB, because it acknowledges a write only after it is persisted to a durable Multi-AZ transaction log.
        - **Why not ElastiCache for (c):** ElastiCache replication is asynchronous, so a failover can lose the most recent acknowledged writes (unless the newer synchronous transaction log option is verified and enabled).
        - **Trade-offs:** MemoryDB adds single-digit milliseconds to write latency, and Valkey is the default engine because it is priced lower than Redis OSS.

4. Evaluate the risks of using ElastiCache-based distributed locks for preventing double payment, and propose a safer design.

    ??? success "Check your answer"

        A good answer covers:

        - **Risk:** cache-based locks are leases; process pauses, failover to a replica that has not received the lock key, or clock and timeout issues can let two workers hold the lock.
        - **Consequence:** two payment attempts may both proceed, which is unacceptable for money movement.
        - **Safer design:** enforce idempotency at the system of record, for example a DynamoDB conditional write or a database unique constraint on the payment idempotency key.
        - **Downstream:** pass an idempotency key to the payment provider so it deduplicates charges.
        - **Role of the lock:** at most an optimisation to reduce duplicate work, never the correctness guarantee.

5. A service is moving from a single-shard cache to a Valkey cache in cluster mode. Its code performs multi-key operations that combine a user's cart and profile keys, and it uses a non-cluster client with large connection pools. Explain the changes required in key design, client choice and connection configuration, and the operational behaviour to expect during scaling.

    ??? success "Check your answer"

        A good answer covers:

        - **Hash slots:** in cluster mode keys are distributed across shards by hash slot, and multi-key operations require all keys to be in the same slot.
        - **Key design:** use hash tags such as `{user:42}:cart` and `{user:42}:profile` so a user's keys share a slot.
        - **Client:** a cluster-aware client (for example Valkey GLIDE, `RedisCluster` in Python or Lettuce in Java) keeps a slot-to-node map, follows `MOVED` and `ASK` redirections and refreshes topology; a non-cluster client fails with `MOVED` errors.
        - **Connections:** small pools matched to in-flight requests, short connect timeouts, tight command timeouts and few retries with backoff and jitter, because every connection consumes server memory and large pools across many pods exhaust `maxclients`.
        - **Scaling behaviour:** online scaling migrates hash slots between shards and can cause brief elevated latency, so clients must refresh topology and respect low DNS TTLs after failover.

---

## 6.2 AWS Database Services

### 6.2.1 Relational Databases with Amazon RDS and Aurora

#### Beginner Questions

1. Define session pinning in RDS Proxy and name two statements that cause it.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** RDS Proxy dedicates a database connection to one client until it disconnects, because the client created session state that cannot be shared.
        - **Effect:** a pinned connection is not multiplexed, so the proxy gives no pooling benefit for it.
        - **Triggers (any two):** `SET` of session variables such as `SET search_path` or `SET time_zone`, creating temporary tables, session-level advisory locks or `LOCK TABLES`, MySQL user variables (`SET @x`), and some prepared statements.

2. State the lifetime of an IAM database authentication token and explain what happens to an established connection when the token expires.

    ??? success "Check your answer"

        A good answer covers:

        - **Lifetime:** 15 minutes.
        - **Scope:** the token is only used to establish a new connection.
        - **Expiry:** an established connection is not terminated when the token expires; only new connections need a fresh token.

3. What is the difference between ECS task definition `environment` and `secrets` entries?

    ??? success "Check your answer"

        A good answer covers:

        - **`environment`:** plain-text name and value pairs stored in the task definition and visible to anyone who can describe it.
        - **`secrets`:** references to Secrets Manager secrets or Parameter Store parameters, resolved by the execution role at task start and injected as environment variables.
        - **Implication:** credentials belong in `secrets`; values are fixed at task start, so rotation requires new tasks or runtime retrieval.

4. Name the two phases of the expand-contract pattern that change the database schema, and state which one removes structures.

    ??? success "Check your answer"

        A good answer covers:

        - **Expand:** adds new structures (columns, tables, indexes) in a backward-compatible way.
        - **Contract:** removes old structures once no running version uses them.
        - **Answer:** the contract phase removes structures.

5. Explain in one sentence why the RDS Data API is useful for Lambda functions that are not attached to a VPC.

    ??? success "Check your answer"

        A good answer covers:

        - **Answer:** the Data API runs SQL over an HTTPS endpoint authenticated with IAM and a Secrets Manager secret, so a function outside the VPC can query Aurora without VPC attachment, drivers or persistent connections.

#### Intermediate Questions

1. An EKS Deployment scales between 6 and 60 pods; each pod has a pool of 15. Another service on ECS scales to 30 tasks with a pool of 10. Compute worst-case connection demand, compare it with a limit of 1,000, and propose two changes.

    ??? success "Check your answer"

        A good answer covers:

        - **Worst case:** EKS 60 × 15 = 900, plus ECS 30 × 10 = 300, gives 1,200 connections.
        - **Comparison:** 1,200 exceeds the 1,000 limit, before reserving headroom (5 to 10 percent) for administration and migrations, so connections fail at peak scale-out.
        - **Change one:** right-size pools with Little's Law, usually to a few connections per pod or task.
        - **Change two:** place RDS Proxy in front so client connections are multiplexed onto fewer database connections; alternatives include capping HPA and ECS maximums or adding readers for read traffic.

2. Using Little's Law, compute the average busy connections for a task serving 400 queries per second with a mean connection hold time of 3 ms, and recommend a pool size.

    ??? success "Check your answer"

        A good answer covers:

        - **Little's Law:** L = λ × W = 400 × 0.003 = 1.2 busy connections on average.
        - **Pool size:** allow for variance and bursts; a pool of about 3 to 5 connections per task is ample.
        - **Configuration:** short connection timeout so requests fail fast, and monitoring of pool wait time to validate the choice.

3. Explain how Aurora Serverless v2 scale to zero with automatic pause works, give two conditions that prevent an instance from pausing, and name two environments in which it pays off.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** on supported engine versions the minimum capacity can be 0 ACUs; after no user connections for `SecondsUntilAutoPause`, the instance pauses, compute charges stop and storage charges continue.
        - **Resume:** the next connection attempt resumes the instance, so the first request waits and client connection timeouts must exceed the resume time; this is rarely acceptable on customer-facing paths.
        - **Conditions that prevent pausing:** any open connection, including idle pool connections, RDS Proxy connections, monitoring agents and replication, and some replication or integration features.
        - **Where it pays off:** ephemeral pull-request environments, nightly-only batch databases, training and lab environments, and per-tenant databases for dormant tenants.

4. Explain how RDS Blue/Green Deployments keep the green environment current, and give one schema change that is compatible and one that is not.

    ??? success "Check your answer"

        A good answer covers:

        - **Synchronisation:** green is built from a snapshot of blue and kept current by replication: binary log for MySQL family engines, logical replication for PostgreSQL family engines.
        - **Compatible change:** adding a nullable column at the end of a table, or adding an index.
        - **Incompatible change:** renaming or dropping a column that blue still writes, which breaks replication.
        - **Note:** PostgreSQL logical replication does not replicate DDL; check the engine's limitation list.

5. Describe how an Aurora fast clone reduces risk in a migration pipeline, and state one security control required when cloning production.

    ??? success "Check your answer"

        A good answer covers:

        - **Fast clone:** a copy-on-write clone of production storage is created in minutes and initially costs almost nothing in storage.
        - **Risk reduction:** the pipeline runs the migration against the clone to measure lock duration and runtime on real data volume before running it on production.
        - **Security control:** clones contain production personal data, so mask or tokenise data before giving developers or test tools access, and restrict who may create clones.
        - **Hygiene:** delete clones automatically at the end of the pipeline.

#### Advanced Questions

1. Design an end-to-end identity chain from an EKS pod to a PostgreSQL grant with no stored password, supporting 5,000 new connections per minute. Justify each component.

    ??? success "Check your answer"

        A good answer covers:

        - **Pod to IAM:** EKS Pod Identity maps the pod's service account to an IAM role, delivering temporary credentials without secrets.
        - **IAM to database user:** the role allows `rds-db:connect` on the specific database user ARN; the user is IAM-enabled (`rds_iam` role in PostgreSQL).
        - **Connection rate:** at 5,000 new connections per minute, use RDS Proxy with IAM authentication from clients, because AWS advises a proxy for high connection churn; the proxy holds a pooled connection to the database.
        - **Grant:** PostgreSQL `GRANT` statements on the user limit what it can do; IAM only authenticates.
        - **Transport and audit:** TLS required, and CloudTrail plus database logs record which identity connected.

2. A shared Aurora cluster hosts eight services using schema-per-service. One service's batch job causes latency for all others. Propose short-term and long-term remedies, including bulkheads and a promotion to cluster-per-service, and describe the migration path with CDC.

    ??? success "Check your answer"

        A good answer covers:

        - **Short term:** identify the batch with Performance Insights or Database Insights, move it to a reader or a dedicated custom endpoint, throttle and chunk it, schedule it off-peak, and set per-role resource limits such as statement timeouts.
        - **Bulkheads:** separate connection pools or RDS Proxy target groups per service, read traffic on separate readers, and per-service database roles with limits.
        - **Long term:** promote the noisy service to its own Aurora cluster, isolating its compute, failure domain and costs.
        - **Migration path:** create the new cluster, perform a full load of the service's schema, then use CDC (DMS or logical replication) to keep it current; switch the service's writes during a short window, validate, and remove the schema from the shared cluster.

3. Design a transactional outbox implementation on Aurora PostgreSQL that publishes to EventBridge with at-least-once delivery and consumer idempotency, including replication slot monitoring and failure handling.

    ??? success "Check your answer"

        A good answer covers:

        - **Write:** the service inserts the business change and an outbox row (event ID, aggregate ID, type, payload, version) in the same transaction.
        - **Relay:** CDC through a logical replication slot (DMS or Debezium) or a poller reads outbox rows in commit order and calls EventBridge `PutEvents`, retrying failed entries; delivery is at least once.
        - **Consumers:** idempotent, using the event ID in a processed-events table or conditional write, and versions to ignore stale events.
        - **Slot monitoring:** alarm on replication slot lag and `TransactionLogsDiskUsage`, because an inactive slot retains WAL and fills storage.
        - **Failure handling:** DLQs on targets, alarms on relay lag, outbox cleanup after publication, and a documented procedure to drop or recreate a stuck slot safely.

4. Evaluate whether a new multi-Region inventory service should use Aurora Global Database, Aurora DSQL or DynamoDB Global Tables. Address consistency, conflict handling, compatibility, failover and application design implications.

    ??? success "Check your answer"

        A good answer covers:

        - **Aurora Global Database:** one writer Region with typical sub-second replication; full PostgreSQL or MySQL compatibility; writes from other Regions must be routed to the primary; failover or switchover in minutes.
        - **Aurora DSQL:** active-active, strongly consistent multi-Region writes; optimistic concurrency, so applications must retry conflicts, keep transactions short and accept a PostgreSQL feature subset.
        - **DynamoDB Global Tables:** MREC gives last-writer-wins, which can silently lose concurrent inventory updates; MRSC gives strong consistency with some feature constraints.
        - **Recommendation:** inventory counts need correctness under concurrent updates, so choose DSQL or DynamoDB MRSC if multi-Region writes are required; choose Global Database if a single writer Region is acceptable.
        - **Application implications:** idempotent, retried transactions, conditional decrements, and Region-aware routing.

5. A platform team wants developers to self-serve databases from Kubernetes. Design this with ACK, GitOps, Serverless v2 scale to zero for non-production, secrets delivery and guardrails (encryption, deletion protection, tagging), and identify the risks.

    ??? success "Check your answer"

        A good answer covers:

        - **ACK and GitOps:** developers commit ACK custom resources (DBCluster, DBInstance) to Git; Argo CD or Flux reconciles them, and ACK creates the Aurora resources.
        - **Non-production:** Aurora Serverless v2 with minimum 0 ACUs and auto-pause, so idle databases cost only storage.
        - **Secrets:** RDS-managed master secrets in Secrets Manager delivered with the Secrets Store CSI Driver or ESO, or IAM authentication through Pod Identity.
        - **Guardrails:** admission policies (Kyverno or Gatekeeper) enforce encryption with approved KMS keys, deletion protection in production, required tags, allowed instance sizes and private subnets; SCPs and service control back them up.
        - **Risks:** accidental deletion via Git changes, cost sprawl, ACK controller IAM permissions being too broad, drift and slow resume of paused databases; mitigate with reviews, budgets, least-privilege controller roles and deletion policies.

### 6.2.2 NoSQL Databases with Amazon DynamoDB

#### Beginner Questions

1. What does an inverted index do, and which access pattern in RideLink needs it?

    ??? success "Check your answer"

        A good answer covers:

        - **Inverted index:** a GSI whose partition key is the table's sort key and whose sort key is the table's partition key.
        - **Purpose:** lets many-to-many edges stored as items be traversed from the other end.
        - **RideLink pattern:** AP8, listing the operators a driver works for (`Query INV SK=DRIVER#d7`) and, in reverse, the drivers of an operator (`Query INV SK=OP#op1`).

2. Write the condition expression that allows a trip update only if its `version` equals 7.

    ??? success "Check your answer"

        A good answer covers:

        - **Condition expression:** `version = :expected` with `:expected = 7`, usually written `#v = :expected` with `#v` mapped to `version` through `ExpressionAttributeNames`.
        - **Update:** `SET #v = #v + :one` (and the new attributes) in the same `UpdateItem`.
        - **Result:** if another writer changed the item first, the write fails with `ConditionalCheckFailedException`.

3. Why must the idempotency record expiry exceed the maximum retry horizon of upstream callers?

    ??? success "Check your answer"

        A good answer covers:

        - **Purpose:** the idempotency record lets a duplicate request return the stored result instead of repeating the operation.
        - **Risk:** if the record expires before the last possible retry arrives, the retry is treated as new and the operation (for example a charge) runs twice.
        - **Horizon:** retries can come hours later from client retries, Lambda asynchronous retries or stream retries, so the expiry must exceed the longest of them.

4. Name two differences between an API Gateway direct integration and a Lambda proxy integration for reading an item.

    ??? success "Check your answer"

        A good answer covers:

        - **Compute:** direct integration calls DynamoDB `GetItem` from API Gateway with no Lambda function, removing cold starts and Lambda cost.
        - **Transformation:** direct integration uses VTL mapping templates for request and response, while Lambda proxy uses general code.
        - **Permissions and logic:** direct integration uses an API Gateway execution role, and complex logic, validation or calls to other services are easier in Lambda.

5. What does `ReportBatchItemFailures` change in a stream event source mapping?

    ??? success "Check your answer"

        A good answer covers:

        - **Without it:** any record failure fails the whole batch, so all records are retried, including those already processed.
        - **With it:** the function returns the sequence number of the first failed record, and Lambda checkpoints before it and retries from that record.
        - **Benefit:** fewer duplicate executions and faster progress, especially combined with bisection and bounded retries.

#### Intermediate Questions

1. Extend the RideLink design to support "list all trips a driver and rider shared" without a new GSI, and state the trade-offs.

    ??? success "Check your answer"

        A good answer covers:

        - **Design:** use the existing driver-trip edges and the trip item; query a rider's trips through GSI1 (AP4) and filter for those whose driver edge is the given driver, or write an additional edge item such as `PK = T#op1#RIDER#r42`, `SK = DRIVER#d7#TRIP#t9001` when a trip is assigned.
        - **Query:** with the extra edge item, `begins_with(SK, "DRIVER#d7#")` on the rider's partition answers the pattern directly.
        - **Trade-offs:** filtering reads more items than returned (cost and latency grow with rider history); the extra edge adds write cost per trip and must be maintained transactionally or idempotently.
        - **Choice:** acceptable for a low-frequency pattern; add an index only if the pattern becomes frequent.

2. Compare DynamoDB Streams with Kinesis Data Streams for DynamoDB in terms of retention, ordering and duplicates, number of consumers and capacity management, and state when you would choose each.

    ??? success "Check your answer"

        A good answer covers:

        - **Retention:** DynamoDB Streams keeps records for 24 hours; Kinesis Data Streams for DynamoDB is configurable from 24 hours up to 365 days.
        - **Ordering and duplicates:** DynamoDB Streams records each change exactly once in the exact order of modifications per item; the Kinesis option may deliver records out of order and occasionally duplicated, so consumers reorder and deduplicate with `ApproximateCreationDateTime` and item keys.
        - **Consumers:** DynamoDB Streams supports at most about two concurrent readers per shard before throttling; Kinesis supports many consumers, including enhanced fan-out.
        - **Capacity:** DynamoDB Streams shards are managed automatically with the table; with Kinesis the team manages stream capacity in on-demand or provisioned mode.
        - **Choice:** DynamoDB Streams for one or two consumers needing strict per-item ordering and simplicity; Kinesis for many consumers, long retention, replay, or analytics through Firehose or Flink.
        - **Risk:** with DynamoDB Streams a record not processed within 24 hours is lost, so `IteratorAge` must be alarmed on every consumer.

3. Configure a Lambda event source mapping for an audit archive that must never block and must retain failed records for investigation. Justify each setting.

    ??? success "Check your answer"

        A good answer covers:

        - **Bisection:** `BisectBatchOnFunctionError = true` isolates the failing record.
        - **Bounded retries:** a small `MaximumRetryAttempts` (for example 2) and `MaximumRecordAgeInSeconds` so the shard never blocks.
        - **On-failure destination:** an SQS queue or S3 bucket receives metadata (shard, sequence numbers) of discarded records for investigation and replay before the 24-hour stream retention expires.
        - **Partial batch responses:** `ReportBatchItemFailures` to avoid reprocessing successful records; the handler must be idempotent.

4. Explain how EventBridge Pipes and an input transformer protect downstream consumers from changes to the table's key design.

    ??? success "Check your answer"

        A good answer covers:

        - **Decoupling:** a pipe reads the stream, filters relevant changes and an input transformer maps internal attributes (`PK`, `SK`, `GSI1PK`) into a stable, versioned business event such as `TripStatusChanged` with `tripId` and `status`.
        - **Protection:** consumers depend on the event contract, not on the table's key design, so the table can be remodelled without breaking them.
        - **Change:** only the pipe's transformation is updated when keys change.

5. Describe the prerequisites and data flow of a DynamoDB zero-ETL integration with OpenSearch Service.

    ??? success "Check your answer"

        A good answer covers:

        - **Prerequisites:** point-in-time recovery and DynamoDB Streams (new image) enabled on the table, an OpenSearch Service domain or Serverless collection, an IAM role for OpenSearch Ingestion, and an S3 bucket for the initial export.
        - **Initial load:** OpenSearch Ingestion exports the table through PITR to S3 and indexes it.
        - **Ongoing changes:** the pipeline then reads the stream and applies inserts, updates and deletes to the index.
        - **Result:** search queries go to OpenSearch while DynamoDB remains the system of record; monitor pipeline lag.

#### Advanced Questions

1. Design a model for a multi-tenant clinic appointment system with patients, clinicians, clinics and slots, supporting double-booking prevention, clinician calendars, patient history and a waiting-list queue. Produce the access pattern table, key design and indexes, and identify hot-key risks.

    ??? success "Check your answer"

        A good answer covers:

        - **Access patterns:** book slot without double booking; clinician calendar by date range; patient history newest first; clinic slots by date; waiting list per clinic and specialty in order; patient and clinician profiles.
        - **Keys:** tenant-prefixed partitions; slot items `PK = T#c1#CLINICIAN#d5`, `SK = SLOT#2026-10-20T09:00`; booking via a transaction that conditionally sets slot status from `FREE` to `BOOKED` (prevents double booking) and writes an appointment item.
        - **Indexes:** GSI1 for patient history (`PATIENT#p9`, sorted by time); GSI2 for clinic day views (`CLINIC#x#DAY#date`); a sparse GSI for the waiting list (`WAIT#clinic#specialty`, sorted by request time) present only while waiting.
        - **Hot keys:** popular clinics on a single day and the waiting list partition; shard with suffixes and scatter-gather, or bucket by time.
        - **Isolation:** `dynamodb:LeadingKeys` conditions on tenant prefixes.

2. Evaluate MREC and MRSC Global Tables for a rider wallet used in three Regions. Address latency, conflict behaviour, feature constraints, recovery point and application changes, and recommend a design.

    ??? success "Check your answer"

        A good answer covers:

        - **MREC:** low-latency local writes in every Region with last-writer-wins; concurrent debits in two Regions can silently lose an update, which is unacceptable for a balance; RPO is typically about a second.
        - **MRSC:** strongly consistent multi-Region reads and writes with zero RPO; writes have higher latency, conflicting writes fail and must be retried, and some features are constrained (verify the current list and Region set).
        - **Application changes:** conditional writes on balances, idempotency keys on every debit, retry on conflicts, and strongly consistent reads where needed.
        - **Recommendation:** MRSC for the wallet balance (or a single home Region per rider with MREC replication for reads); MREC remains suitable for profiles and trip history.

3. A table must be re-keyed because the original partition key causes hot partitions. Design a zero-downtime migration using dual writes, a backfill via export and import or a throttled job, stream-based catch-up, cut-over and verification.

    ??? success "Check your answer"

        A good answer covers:

        - **Dual writes:** deploy code that writes to both the old and new tables (new key design), with idempotent writes.
        - **Backfill:** export the old table to S3 and import into the new table, or run a throttled scan-and-write job.
        - **Catch-up:** a stream consumer on the old table applies changes made during the backfill, using versions so newer data is not overwritten by older data.
        - **Cut-over:** verify counts and sampled items, switch reads to the new table behind a feature flag, then stop writes to the old table.
        - **Verification and rollback:** compare results in shadow reads before switching, keep the old table until confident, then delete it.

4. Design a testing strategy for a DynamoDB-backed service spanning unit tests, DynamoDB Local integration tests, ephemeral real tables in CI, permission tests for `LeadingKeys` and load tests for hot keys. Explain what each layer can and cannot detect.

    ??? success "Check your answer"

        A good answer covers:

        - **Unit tests:** business logic and key construction with mocks; cannot detect real query behaviour or service limits.
        - **DynamoDB Local:** fast integration tests of queries, conditions and transactions; cannot test IAM, throughput, streams fidelity or service quotas.
        - **Ephemeral real tables in CI:** created per pipeline run from IaC; detect real API behaviour, index configuration and streams, but cost more and are slower.
        - **Permission tests:** assume tenant roles and attempt cross-tenant reads to prove `LeadingKeys` conditions deny them; only real IAM can detect this.
        - **Load tests:** generate skewed traffic to reveal hot keys and throttling, using CloudWatch and Contributor Insights; local tools cannot reproduce partition behaviour.

5. Compare three ways of exposing RideLink trip data to a partner in another AWS account: a resource-based policy on a GSI, a zero-ETL feed into the partner's Redshift, and events on a cross-account EventBridge bus. Evaluate coupling, security, freshness and cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Resource policy on a GSI:** the partner queries directly; fresh data and low cost, but tight coupling to the table's key design, exposure of internal schema, and risk to production capacity.
        - **Zero-ETL into the partner's Redshift:** analytical access with good isolation from production; minutes of latency, warehouse cost, and still exposes the internal data model unless transformed.
        - **Cross-account EventBridge events:** a versioned contract of business events with loose coupling and filtering; near real time; costs per event and requires the partner to build its own store.
        - **Security:** events and zero-ETL keep the partner out of the production table; resource policies need careful scoping.
        - **Judgement:** events for operational integration, zero-ETL for analytics, direct access only for narrow, controlled cases.

### 6.2.3 Graph Databases with Amazon Neptune

#### Beginner Questions

1. Define vertex, edge, label and property, giving an example of each from a social network.

    ??? success "Check your answer"

        A good answer covers:

        - **Vertex:** an entity, for example a user Alice.
        - **Edge:** a directed, named relationship between two vertices, for example Alice `FOLLOWS` Bob.
        - **Label:** the type of a vertex or edge, for example `User` or `FOLLOWS`.
        - **Property:** a key-value attribute on a vertex or edge, for example `name = "Alice"` on the vertex or `since = 2024` on the edge.

2. Name the three query languages supported by Neptune Database and state which data model each targets.

    ??? success "Check your answer"

        A good answer covers:

        - **Gremlin:** Apache TinkerPop traversal language for the property graph model.
        - **openCypher:** declarative pattern-matching language, also for the property graph model.
        - **SPARQL:** W3C query language for the RDF model.
        - **Note:** property graph and RDF data are stored and queried separately.

3. How many read replicas can a Neptune Database cluster have, and what is the purpose of the reader endpoint?

    ??? success "Check your answer"

        A good answer covers:

        - **Replicas:** up to 15 read replicas in a Neptune Database cluster.
        - **Reader endpoint:** a single DNS name that distributes read connections across the replicas.
        - **Purpose:** clients scale reads without tracking individual instances; replicas also serve as failover targets for the writer.

4. Which port does Neptune listen on, and which AWS network control must allow traffic to it?

    ??? success "Check your answer"

        A good answer covers:

        - **Port:** 8182, for HTTPS and WebSocket connections.
        - **Network control:** the Neptune cluster's security group must allow inbound TCP 8182 from the clients' security groups (Lambda, ECS tasks, EKS nodes or pods).
        - **Placement:** Neptune runs only inside a VPC, so clients must have a network path into it.

5. What is the purpose of the Neptune bulk loader, and which AWS service stores its source files?

    ??? success "Check your answer"

        A good answer covers:

        - **Purpose:** high-throughput parallel ingestion of large datasets in bulk, much faster than individual insert queries.
        - **Source:** files (CSV for property graphs, RDF formats such as N-Triples or Turtle) stored in Amazon S3.
        - **Requirements:** an IAM role attached to the cluster with S3 read access, and an S3 gateway endpoint in the VPC.

#### Intermediate Questions

1. Write an openCypher query and an equivalent Gremlin traversal that return all products purchased by friends of a given user but not by the user.

    ??? success "Check your answer"

        A good answer covers:

        - **openCypher:** `MATCH (u:User {id: $uid})-[:FRIEND]-(f:User)-[:PURCHASED]->(p:Product) WHERE NOT (u)-[:PURCHASED]->(p) RETURN DISTINCT p`.
        - **Gremlin:** `g.V().has('User','id',uid).as('u').out('PURCHASED').aggregate('mine').select('u').both('FRIEND').out('PURCHASED').where(without('mine')).dedup()`.
        - **Key points:** start from the user, hop to friends, hop to their purchases, exclude the user's own purchases, deduplicate.
        - **Good practice:** use parameters, and add `LIMIT` or `limit()` to bound fan-out for users with many friends.

2. Compare the labelled property graph and RDF models supported by Neptune, and recommend one for (a) a fraud detection application and (b) integrating research datasets from several institutions that use shared vocabularies.

    ??? success "Check your answer"

        A good answer covers:

        - **Property graph:** vertices and edges with IDs, labels and native properties on both; schema-optional; queried with Gremlin or openCypher.
        - **RDF:** subject, predicate and object triples (stored as quads in Neptune) identified by global IRIs, described by ontologies and shared vocabularies, and queried with SPARQL; properties on edges need reification, RDF-star or named graphs.
        - **(a) Fraud detection:** a property graph, because a development team is building an application that traverses its own data.
        - **(b) Research integration:** RDF, because the dominant problem is integrating data from many sources with shared vocabularies and globally unique identifiers, often with W3C standards compliance.
        - **Constraint:** the two models are stored separately in Neptune, so SPARQL cannot query data loaded as a property graph, and vice versa.

3. Explain how Neptune Serverless scaling works, including its minimum capacity, and when you would mix provisioned and serverless instances in one cluster.

    ??? success "Check your answer"

        A good answer covers:

        - **Scaling:** Serverless instances scale in Neptune Capacity Units (NCUs) of about 2 GiB of memory with associated CPU and networking, between a configured minimum and maximum.
        - **Range:** the lowest minimum is 1 NCU and the highest maximum is 128 NCUs; it never scales to zero, so idle clusters still cost money (stop or delete them instead).
        - **Behaviour:** capacity grows as load reaches the current limit and shrinks towards the minimum; a higher minimum allows faster scale-up.
        - **Mixed clusters:** combine a provisioned writer for steady write load with Serverless readers to absorb spiky read traffic, or the reverse; readers in promotion tiers 0 and 1 scale with the writer.

4. Describe how to grant an EKS pod read-only access to Neptune without any database password.

    ??? success "Check your answer"

        A good answer covers:

        - **Identity:** EKS Pod Identity (or IRSA) maps the pod's service account to an IAM role.
        - **Policy:** the role allows only `neptune-db:ReadDataViaQuery` (plus connect permissions as required) on the cluster resource ID ARN.
        - **Cluster:** IAM database authentication is enabled on the Neptune cluster.
        - **Client:** the pod signs requests with SigV4 using service name `neptune-db`, connecting to the reader endpoint on 8182 over TLS.
        - **Network:** security groups allow the pods' traffic; no password exists anywhere.

5. Explain what Neptune Streams provides and design a consumer that replicates graph changes to EventBridge with at-least-once delivery.

    ??? success "Check your answer"

        A good answer covers:

        - **Neptune Streams:** an ordered change log of every graph mutation, readable through an HTTP endpoint, retained for a configurable period.
        - **Consumer:** a poller (for example the AWS-provided Lambda-based polling framework, or a Lambda on a schedule) reads records in order from the last checkpoint.
        - **Publishing:** it transforms changes into business events and calls EventBridge `PutEvents`, retrying failed entries.
        - **At-least-once:** the checkpoint (stored in DynamoDB) advances only after successful publication, so a crash causes re-publication, not loss; consumers deduplicate using the commit number and operation number.
        - **Operations:** alarm on stream lag and keep retention longer than any expected outage.

#### Advanced Questions

1. Design a multi-Region architecture for a global identity graph with a recovery point objective of seconds and low-latency reads in three continents. Discuss Global Database, write routing and failover procedures.

    ??? success "Check your answer"

        A good answer covers:

        - **Global Database:** a primary Region with all writes and up to five secondary read-only Regions with storage-level replication, typically with lag of about a second.
        - **Reads:** applications in each continent read from the local secondary cluster for low latency.
        - **Write routing:** writes are sent to the primary Region's writer endpoint, either directly or through a write service in that Region.
        - **Failover:** in a Regional outage, promote a secondary (managed failover or detach-and-promote), update write routing and DNS, and accept an RPO of seconds; rehearse regularly.
        - **Trade-off:** writes from distant continents incur cross-Region latency.

2. Analysts run PageRank and community detection on the Neptune Database cluster that serves an online recommendation API, and API latency degrades. Design a separation using Neptune Analytics, including how the analytical graph is loaded and kept current and how analytical results reach the online path.

    ??? success "Check your answer"

        A good answer covers:

        - **Diagnosis:** this mixes OLTP and OLAP on one cluster; Neptune Database is designed for many small, low-latency traversals, and its default query timeout signals that long analytical queries belong elsewhere.
        - **Separation:** create a Neptune Analytics graph, a separate memory-optimised engine sized in m-NCUs that runs whole-graph algorithms and vector search with openCypher.
        - **Loading and refresh:** load the analytical copy from S3 exports or from Neptune Database on a schedule matched to how fresh the scores must be; it is an analytical copy, not the system of record.
        - **Returning results:** write algorithm outputs such as scores back as properties in Neptune Database (for example through the bulk loader) or to another serving store, so the API reads precomputed values in milliseconds.
        - **Interim measure:** isolate analyst readers on a custom endpoint until the separation is complete, and bound traversal depth and fan-out in the online queries.

3. Design a GraphRAG solution for a university's regulations and policy documents using Amazon Bedrock and Neptune Analytics. Explain when it would outperform vector-only RAG and what its operational costs are.

    ??? success "Check your answer"

        A good answer covers:

        - **Pipeline:** documents in S3 are chunked and embedded with Bedrock models; entities and relationships are extracted into a graph in Neptune Analytics, which also stores vectors; Bedrock Knowledge Bases supports this GraphRAG pattern.
        - **Retrieval:** a question retrieves similar chunks by vector search, then follows graph relationships (for example a regulation that amends or references another) to gather connected context for the model.
        - **When it outperforms vector-only RAG:** multi-hop questions that need connected facts across documents, such as amendments, exceptions and cross-references between policies.
        - **Operational costs:** Neptune Analytics memory capacity running continuously, Bedrock embedding and generation costs, extraction during ingestion, and re-indexing when documents change.

4. Propose a CI/CD approach for graph model changes, including query regression tests with `explain`, backward-compatible label changes and data backfills.

    ??? success "Check your answer"

        A good answer covers:

        - **Model as code:** queries, schema conventions and migration scripts are versioned in Git.
        - **Regression tests:** run representative queries with `explain` and profile on a test cluster loaded with sample data (or a restored snapshot), failing the build if plans or latency regress.
        - **Backward-compatible label changes:** add the new label or property alongside the old, update writers to write both, migrate readers, then remove the old one later (expand-contract for graphs).
        - **Backfills:** idempotent, throttled jobs or bulk loads, run on a clone first, with progress tracking.
        - **Promotion:** deploy to staging, run tests, then production, with snapshots before risky changes.

5. Evaluate whether Neptune ML link prediction or precomputed Neptune Analytics similarity scores is the better approach for real-time product recommendations, considering latency, freshness, cost and operational complexity.

    ??? success "Check your answer"

        A good answer covers:

        - **Neptune ML link prediction:** graph neural networks trained with SageMaker give context-aware predictions through inference queries, but add SageMaker endpoint latency and continuous cost, and models go stale without retraining.
        - **Precomputed Neptune Analytics similarity:** batch algorithms compute similarity scores, written back as properties or to a serving store; request latency is a simple lookup and cost is periodic, but freshness is limited to the refresh interval.
        - **Operational complexity:** ML requires training pipelines, endpoints and monitoring; precomputation needs only scheduled jobs.
        - **Recommendation:** for most real-time product recommendations, precomputed scores refreshed regularly (possibly combined with simple real-time rules) are cheaper and simpler; use Neptune ML only when evaluation shows a clear accuracy gain.

### 6.2.4 Data Warehousing with Amazon Redshift

#### Beginner Questions

1. Define a data warehouse and state three ways it differs from an OLTP database.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** a central store integrating historical data from many sources, organised for analytical queries and reporting.
        - **Workload:** OLAP queries scan and aggregate many rows, while OLTP databases handle many small transactions on individual rows.
        - **Storage:** warehouses use columnar storage and compression; OLTP databases use row storage.
        - **Schema and data:** warehouses use denormalised star or snowflake schemas with historical, integrated, mostly append-only data; OLTP uses normalised schemas holding current state.
        - **Concurrency and latency:** warehouses support fewer, heavier queries; OLTP supports many concurrent low-latency operations.

2. What is a zone map, and why does it depend on the sort key?

    ??? success "Check your answer"

        A good answer covers:

        - **Zone map:** metadata recording the minimum and maximum value of a column in each 1 MB block.
        - **Use:** the engine skips blocks whose range cannot match a query's predicate.
        - **Sort key dependence:** when data is sorted on the filtered column, each block covers a narrow range, so most blocks are skipped; unsorted data gives wide, overlapping ranges and little skipping.

3. List the four distribution styles and give one appropriate use for each.

    ??? success "Check your answer"

        A good answer covers:

        - **KEY:** rows with the same key value on the same slice; large fact and dimension tables frequently joined on that key.
        - **ALL:** a full copy on every node; small, slowly changing dimension tables.
        - **EVEN:** round-robin distribution; tables with no dominant join key or used mainly in scans.
        - **AUTO:** Redshift chooses and adapts (often ALL when small, then EVEN or KEY); the default and a good choice when unsure.

4. What is an RPU, and how is Redshift Serverless compute billed?

    ??? success "Check your answer"

        A good answer covers:

        - **RPU:** Redshift Processing Unit, the unit of Redshift Serverless compute capacity (each RPU provides 16 GB of memory).
        - **Billing:** RPU-hours consumed while queries run, charged per second with a 60-second minimum; nothing for idle time.
        - **Controls:** a base capacity, a maximum RPU setting and usage limits bound performance and cost.
        - **Storage:** managed storage is billed separately per GB-month.

5. Which Redshift command loads data in parallel from S3, and which exports query results to S3?

    ??? success "Check your answer"

        A good answer covers:

        - **Load:** `COPY` loads data in parallel from S3 (files split across slices), as well as other sources such as DynamoDB.
        - **Export:** `UNLOAD` writes query results to S3 in parallel, optionally as partitioned Parquet.
        - **Practice:** use several similarly sized compressed files, a multiple of the slice count, for efficient `COPY`.

#### Intermediate Questions

1. Design a star schema for a university library's borrowing process, stating the grain, the fact table measures, the dimensions and their distribution styles.

    ??? success "Check your answer"

        A good answer covers:

        - **Grain:** one row per loan of one item to one borrower (a borrowing event).
        - **Fact table measures:** loan count, days borrowed, days overdue and fine amount, with keys to dimensions and the borrow and return dates.
        - **Dimensions:** date, borrower (student or staff, faculty), item (title, author, subject, format), branch or library, possibly due-date policy.
        - **Distribution:** the fact table KEY-distributed on the most frequently joined large dimension key (for example item) or AUTO; small dimensions such as date and branch ALL; large dimensions on their join key.
        - **Sort keys:** the fact table sorted by borrow date to support time-range filters.

2. Explain how a zero-ETL integration from Aurora into Redshift works and why a staging layer should be built on top of the replicated tables.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** Aurora's storage-level change capture replicates data into a Redshift database continuously, with seeding and then ongoing changes within seconds, without building ETL pipelines.
        - **Setup:** create the integration from Aurora, then a database in Redshift from the integration; Aurora needs supported versions and parameters, and the Redshift side needs case-sensitive identifiers and authorisation.
        - **Staging layer:** the replicated tables mirror the operational schema, which belongs to the service and can change.
        - **Why stage:** views or models on top rename, type, clean and conform data into a stable star schema, protecting dashboards from source changes and joining data across services.

3. Compare automatic WLM with short query acceleration and concurrency scaling, and describe a configuration for a warehouse used by both ETL jobs and executive dashboards.

    ??? success "Check your answer"

        A good answer covers:

        - **Automatic WLM:** Redshift manages memory and concurrency across queues using query priorities.
        - **Short query acceleration:** a separate path runs short queries quickly so they are not stuck behind long ones.
        - **Concurrency scaling:** adds transient cluster capacity for eligible queued queries, with free credits accrued daily.
        - **Configuration:** a high-priority dashboard queue with concurrency scaling enabled, SQA on, an ETL queue at lower priority, and query monitoring rules to stop runaway queries; alternatively separate producer and consumer workgroups with data sharing.

4. Write a Lambda function outline that uses the Redshift Data API with parameterised SQL, and explain why the Data API is preferred over JDBC for Lambda.

    ??? success "Check your answer"

        A good answer covers:

        - **Outline:** the handler calls `redshift-data` `ExecuteStatement` with `WorkgroupName` (or cluster ID), `Database`, SQL containing named placeholders such as `:region`, and a `Parameters` list; authentication through IAM or a Secrets Manager ARN.
        - **Asynchronous:** it receives a statement ID, then polls `DescribeStatement` (or uses an EventBridge event when `WithEvent` is set) and reads results with `GetStatementResult`.
        - **Parameterisation:** values are passed separately from SQL, preventing injection.
        - **Why prefer it:** no drivers, no persistent connections or VPC configuration, IAM authentication and asynchronous calls that do not hold a Lambda function waiting on long queries; calls are audited in CloudTrail.

5. Explain when Redshift Spectrum is more cost-effective than loading data into managed storage, and how file format and partitioning affect Spectrum performance and cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Cost-effective when:** data is large, rarely queried, or already in a data lake shared with other engines (Athena, EMR), so loading would duplicate storage and pipelines.
        - **Pricing:** Spectrum charges per TB scanned (provisioned) or consumes RPUs (Serverless), so cost depends on scan volume.
        - **File format:** columnar, compressed formats (Parquet or ORC) read only needed columns and use statistics, reducing scanned data dramatically compared with CSV or JSON.
        - **Partitioning:** partitioning on common filters (such as date) lets queries prune partitions; avoid many tiny files.
        - **When to load instead:** frequently queried, performance-critical data belongs in managed storage.

#### Advanced Questions

1. Design a data-sharing architecture in which an ETL producer workgroup serves a curated star schema to a BI workgroup, a data science workgroup and a partner's AWS account. Explain consistency, compute isolation and cross-account authorisation, and why this design is the warehouse form of the bulkhead pattern.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** the producer creates a datashare containing the curated schema; consumers read it live and transactionally consistent without copying data.
        - **Compute isolation:** each consumer queries on its own compute, so dashboards, data science workloads and heavy ETL do not compete for the same resources.
        - **Cross-account access:** the producer administrator authorises the partner account and the consumer associates the datashare; cross-Region consumers incur data transfer charges, and Lake Formation-managed datashares can centralise permissions.
        - **Bulkhead:** separate compute over the same data means heavy ETL cannot starve dashboards, which is the bulkhead pattern applied to the warehouse.
        - **Governance:** consumers receive presentation models rather than raw replicated tables, so producer schema changes stay behind a stable interface.

2. A SaaS provider must offer tenant-level embedded analytics with strict isolation for 500 tenants. Compare a shared warehouse with row-level security against per-tenant workgroups with data sharing, considering security, cost, noisy neighbours and operations.

    ??? success "Check your answer"

        A good answer covers:

        - **Shared warehouse with RLS:** cheapest and simplest to operate; row-level security policies filter by tenant attribute, but a policy error can expose data, and heavy tenants become noisy neighbours.
        - **Per-tenant workgroups with data sharing:** stronger isolation of compute and access, per-tenant cost visibility and limits, but more resources to manage and higher baseline cost for 500 tenants.
        - **Noisy neighbours:** shared warehouses need WLM and usage limits; separate workgroups isolate them.
        - **Recommendation:** tiered: shared warehouse with RLS (plus masking and tested policies) for most tenants, dedicated consumer workgroups for large or regulated tenants, with automation through IaC.

3. Build a cost model comparing Redshift Serverless and provisioned RA3 with Reserved Nodes for a workload that runs 6 hours of heavy processing daily plus light dashboard traffic during business hours. Identify the assumptions and the break-even point.

    ??? success "Check your answer"

        A good answer covers:

        - **Workload:** 6 hours of heavy processing daily plus light dashboard use for about 8 to 10 business hours.
        - **Serverless model:** cost = (heavy RPUs × 6 h + light RPUs × business hours) × RPU-hour price × 30, with nothing charged for idle periods.
        - **Provisioned model:** cost = nodes × node-hour price × 730 hours per month, discounted by Reserved Nodes, running 24 hours regardless of use.
        - **Break-even:** provisioned becomes cheaper when average utilisation over the month is high enough that the reserved monthly cost is below the Serverless usage cost; compute it with current prices for the chosen node size and RPU levels.
        - **Assumptions to state:** sizing equivalence of nodes and RPUs, minimum billing per query, growth, concurrency scaling credits and storage costs.

4. Design an end-to-end pipeline that ingests order events from Amazon MSK, joins them with product data replicated from DynamoDB, maintains a slowly changing customer dimension, and refreshes dashboards within one minute of an order. Justify each AWS service and the failure-handling strategy.

    ??? success "Check your answer"

        A good answer covers:

        - **Ingestion:** Redshift streaming ingestion from MSK into a materialized view with auto refresh, giving near-real-time access to order events.
        - **Product data:** DynamoDB zero-ETL integration into Redshift keeps product data current.
        - **Customer dimension:** SCD Type 2 maintained by incremental MERGE statements orchestrated by Step Functions or scheduled queries, closing old rows and inserting new versions.
        - **Dashboards:** incremental materialized views joining orders with product and customer dimensions refreshed every minute; QuickSight in direct query mode.
        - **Failure handling:** MSK retention allows reprocessing, idempotent MERGE logic, monitoring of ingestion and integration lag with alarms, and DLQs for orchestration failures.

5. Choose and justify an ingestion path into Redshift for each of the following: (a) clickstream from Kinesis Data Streams that dashboards need within seconds, (b) daily partner files delivered to S3, (c) order data owned by an Aurora PostgreSQL microservice, and (d) an occasional join with a small, current reference table in RDS for PostgreSQL. Relate your answer to the golden rule where relevant.

    ??? success "Check your answer"

        A good answer covers:

        - **(a) Clickstream:** streaming ingestion into a materialized view with `AUTO REFRESH YES`, parsing payloads into SUPER, which avoids staging in S3; Firehose is the alternative when Lambda transformation or several destinations are needed.
        - **(b) Partner files:** `COPY` from S3 with input split into many compressed or columnar files, a manifest for exact file lists, and a staging table merged into the target for idempotent loads.
        - **(c) Order data:** a zero-ETL integration from Aurora, treating replicated tables as a read-only raw layer with staging views and presentation models on top, so a column rename changes only the staging view.
        - **(d) Reference join:** a federated query, used sparingly and preferably against a read replica, because it runs on the service's production database.
        - **Golden rule:** analytics must not query service databases directly, so recurring analytics use zero-ETL or events, and federated queries remain a controlled exception.

---

## 6.3 Messaging and Event Streaming

### 6.3.1 Message Queues with Amazon SQS

#### Beginner Questions

1. Define point-to-point messaging and explain how it differs from publish/subscribe.

    ??? success "Check your answer"

        A good answer covers:

        - **Point-to-point:** each message is consumed and processed by exactly one consumer among possibly many competing consumers (an SQS queue).
        - **Publish/subscribe:** each message is delivered to every subscriber (an SNS topic or EventBridge rule targets).
        - **Difference:** point-to-point distributes work; pub/sub broadcasts facts.
        - **Combination:** SNS-to-SQS fan-out gives each subscribing service its own queue of copies.

2. What is a receipt handle, and why can a message not be deleted using its message ID?

    ??? success "Check your answer"

        A good answer covers:

        - **Receipt handle:** an identifier returned with each receive of a message, representing that specific delivery.
        - **Deletion:** `DeleteMessage` and `ChangeMessageVisibility` require the receipt handle of the latest receive.
        - **Why not the message ID:** the same message can be received several times; the handle ties the delete to a particular receive, so a consumer whose visibility timeout expired cannot accidentally confirm another consumer's in-progress delivery.

3. List the default and maximum values of the visibility timeout, the retention period and the long polling wait time.

    ??? success "Check your answer"

        A good answer covers:

        - **Visibility timeout:** default 30 seconds, maximum 12 hours.
        - **Retention period:** default 4 days, range 60 seconds to 14 days.
        - **Long polling wait time:** default 0 seconds (short polling), maximum 20 seconds.

4. Why must a FIFO queue name end in `.fifo`, and can an existing standard queue be converted to FIFO?

    ??? success "Check your answer"

        A good answer covers:

        - **Naming:** the `.fifo` suffix identifies the queue type, so SQS and clients can enforce FIFO semantics (message group IDs, deduplication) at creation.
        - **Conversion:** no; the queue type is fixed when the queue is created.
        - **Migration:** create a new FIFO queue, move producers and consumers, and drain the old standard queue.

5. What is a dead-letter queue, and what does `maxReceiveCount` control?

    ??? success "Check your answer"

        A good answer covers:

        - **DLQ:** a queue that receives messages that could not be processed successfully after repeated attempts.
        - **`maxReceiveCount`:** the number of times a message can be received without being deleted before SQS moves it to the DLQ.
        - **Purpose:** isolates poison messages so they do not block or waste processing, and preserves them for investigation and redrive.
        - **Note:** the DLQ must be the same type (standard or FIFO) as the source queue and in the same account and Region.

#### Intermediate Questions

1. A worker's processing time varies from 5 seconds to 25 minutes. Explain how you would configure the visibility timeout and implement heartbeats, and why a 12-hour timeout is a poor choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Initial timeout:** set a moderate timeout (for example a few minutes) that covers typical processing.
        - **Heartbeat:** while processing, the worker periodically calls `ChangeMessageVisibility` to extend the timeout, for example every minute, up to the 12-hour maximum.
        - **Failure:** if the worker crashes, heartbeats stop and the message becomes visible again quickly.
        - **Why not 12 hours:** a crashed worker's message would stay invisible for up to 12 hours, delaying retries and hiding failures.

2. Compare short polling and long polling in SQS, explain why a short poll can return an empty response from a queue that contains messages, and describe the cost effect of long polling.

    ??? success "Check your answer"

        A good answer covers:

        - **Short polling:** `WaitTimeSeconds = 0`; the request queries only a sampled subset of the storage hosts and returns immediately.
        - **False empty responses:** because messages are distributed across many hosts, the sampled subset may hold none of them even though the queue is not empty.
        - **Long polling:** `WaitTimeSeconds` between 1 and 20 (or the queue default `ReceiveMessageWaitTimeSeconds`); all hosts are queried and the call returns as soon as a message is available or the wait ends.
        - **Cost:** every empty response is a billable request, so long polling removes most empty receives and lowers cost.
        - **Client setting:** the HTTP socket read timeout must exceed the long-poll wait time, or clients and proxies drop connections early.

3. Describe the purpose of the Lambda event source mapping options `BatchSize`, `MaximumBatchingWindowInSeconds`, `ScalingConfig.MaximumConcurrency` and `FilterCriteria` for an SQS queue, and explain the risk of `FilterCriteria` when other consumers need the filtered messages.

    ??? success "Check your answer"

        A good answer covers:

        - **`BatchSize`:** up to 10 messages per invocation for FIFO and up to 10,000 for standard queues; larger batches reduce invocations, and more than 10 requires a batching window.
        - **`MaximumBatchingWindowInSeconds`:** waits up to 300 seconds to fill a batch, trading latency for fewer invocations and lower cost.
        - **`ScalingConfig.MaximumConcurrency`:** caps concurrent invocations for this mapping (2 to 1,000) to protect downstream systems such as a database.
        - **`FilterCriteria`:** discards non-matching messages before invocation.
        - **Risk:** filtered-out messages are deleted from the queue, so filtering is not routing; when other consumers need those messages, route with SNS or EventBridge instead.

4. Write the redrive policy and redrive allow policy for a source queue `payments` and DLQ `payments-dlq` in account 111122223333, and explain why the DLQ retention should be 14 days.

    ??? success "Check your answer"

        A good answer covers:

        - **Redrive policy on `payments`:** `{"deadLetterTargetArn":"arn:aws:sqs:us-east-1:111122223333:payments-dlq","maxReceiveCount":"5"}` (Region assumed).
        - **Redrive allow policy on `payments-dlq`:** `{"redrivePermission":"byQueue","sourceQueueArns":["arn:aws:sqs:us-east-1:111122223333:payments"]}`.
        - **Why 14 days:** for standard queues, message expiry in the DLQ is based on the original enqueue timestamp, so the DLQ retention must exceed the source's; the maximum gives the longest time to investigate and redrive.

5. A Lambda function processes batches of 10 messages and one message fails. Describe what happens with and without `ReportBatchItemFailures`.

    ??? success "Check your answer"

        A good answer covers:

        - **Without `ReportBatchItemFailures`:** the function's failure makes the whole batch fail; all 10 messages become visible again after the visibility timeout and are reprocessed, including the 9 that succeeded.
        - **With it:** the function returns the failed message's ID in `batchItemFailures`; Lambda deletes the 9 successes and only the failed message returns to the queue.
        - **Requirement:** handlers must still be idempotent, and the DLQ catches the message after `maxReceiveCount` failures.

#### Advanced Questions

1. Design a multi-tenant job system in which premium tenants have a latency objective of 10 seconds and free tenants of 10 minutes, while no single tenant can starve others. Justify your use of multiple queues, fair queues, maximum concurrency and scaling policies.

    ??? success "Check your answer"

        A good answer covers:

        - **Queues by tier:** separate premium and free queues (bulkheads), each with its own consumers and scaling policy targeting its latency objective (backlog per task based on 10 seconds or 10 minutes).
        - **Fair queues:** set `MessageGroupId` to the tenant ID on standard queues so SQS prioritises quiet tenants when one tenant builds a large backlog.
        - **Maximum concurrency:** cap Lambda event source mappings per queue so free-tier processing cannot consume capacity needed by premium or downstream systems.
        - **Scaling:** premium consumers scale aggressively with headroom; free consumers scale more conservatively, possibly on Spot.
        - **Monitoring:** `ApproximateAgeOfOldestMessage` per queue against each objective.

2. An order service must publish order state changes to a FIFO queue at 15,000 messages per second while preserving per-order ordering and preventing producer duplicates. Explain high-throughput FIFO configuration, the choice of group and deduplication IDs, the consumer design for partial batch failures, and the operational alarms you would add.

    ??? success "Check your answer"

        A good answer covers:

        - **High-throughput FIFO:** set `DeduplicationScope = messageGroup` and `FifoThroughputLimit = perMessageGroupId`, and use batching; check Regional throughput quotas against 15,000 messages per second.
        - **Message group ID:** the order ID, giving per-order ordering and many distinct groups so partitions spread the load.
        - **Deduplication ID:** a deterministic event ID (for example order ID plus version), so producer retries within 5 minutes are dropped.
        - **Consumers:** process batches with partial batch responses; after a failure within a group, stop processing later messages of that group in the batch to preserve order; consumers are idempotent.
        - **Alarms:** age of oldest message, DLQ depth, throttling of sends, and consumer errors.

3. Compare SQS with Kinesis Data Streams and EventBridge for an event whose consumers include a real-time analytics job that must re-read the last 24 hours after a bug fix. Which service or combination would you choose and why?

    ??? success "Check your answer"

        A good answer covers:

        - **SQS:** messages are deleted after processing and cannot be re-read; unsuitable for replay.
        - **EventBridge:** archive and replay can resend past events to rules, useful for recovery, but replay is not an ordered high-volume stream re-read.
        - **Kinesis Data Streams:** retains records (24 hours by default, extendable) and lets any consumer re-read from a timestamp or sequence number, preserving per-shard order.
        - **Choice:** publish to Kinesis for the analytics consumer that must re-read 24 hours (with retention extended beyond 24 hours for safety); use EventBridge or SNS-to-SQS for other business consumers, possibly fed from the same producer or a pipe.

4. Design a claim-check implementation for a document-processing queue whose payloads range from 10 KB to 50 MB. Address where payloads are stored, what the message carries, the billing arithmetic, clean-up, and the failure cases the design must handle.

    ??? success "Check your answer"

        A good answer covers:

        - **Storage:** payloads above a threshold are written to S3 and the message carries only a pointer, as implemented by the SQS Extended Client Library; even with a 1 MiB maximum message size, queues are a poor place for large blobs.
        - **Flow:** `PutObject`, then `SendMessage` with the pointer; the consumer receives the message, calls `GetObject`, processes the document and deletes the message (and optionally the object).
        - **Billing:** SQS bills each 64 KB chunk of a payload as one request, so a 1 MiB message costs as much as 16 small messages on send and again on receive, which makes the pointer approach cheaper.
        - **Clean-up:** S3 lifecycle rules expire payload objects, with an expiry longer than queue and DLQ retention so that a redriven message still finds its payload.
        - **Failure cases:** a producer that uploads but fails to send leaves orphan objects for lifecycle to remove; a consumer that deletes the object before the message breaks redelivery; at-least-once delivery requires idempotent processing.

5. A payment workflow uses API Gateway to SQS to Lambda to a third-party API. During a partner outage lasting six hours, the DLQ fills and some messages expire. Perform a post-incident analysis: identify the configuration errors (retention, maxReceiveCount, retry strategy, circuit breaking) and propose a redesign using visibility-based backoff, a circuit breaker (Chapter 4.3), longer retention and DLQ redrive.

    ??? success "Check your answer"

        A good answer covers:

        - **Errors found:** retention too short for a six-hour outage combined with DLQ expiry based on original enqueue time; `maxReceiveCount` so low that messages reached the DLQ in minutes; immediate retries with no backoff; no circuit breaker, so every message hammered the failing partner.
        - **Visibility-based backoff:** on a transient error, call `ChangeMessageVisibility` with an increasing delay instead of failing immediately.
        - **Circuit breaker:** when the partner fails repeatedly, open the circuit and stop consuming (for example disable the event source mapping or set maximum concurrency low), resuming with probes when it recovers.
        - **Retention and DLQ:** source and DLQ retention set to the maximum 14 days, `maxReceiveCount` sized for the backoff schedule, and DLQ alarms.
        - **Redrive:** after recovery, redrive DLQ messages to the source at a controlled rate, with idempotency keys so the partner never processes a payment twice.

### 6.3.2 Pub/Sub Messaging with Amazon SNS

#### Beginner Questions

1. Define a topic, a subscription and an endpoint in Amazon SNS.

    ??? success "Check your answer"

        A good answer covers:

        - **Topic:** a named communication channel to which publishers send messages.
        - **Subscription:** the link between a topic and an endpoint, with a protocol and optional filter policy, delivery policy and redrive policy.
        - **Endpoint:** the destination that receives messages, such as an SQS queue ARN, a Lambda function ARN, an HTTPS URL, an email address or a phone number.

2. List five SNS subscription protocols and give one use case for each.

    ??? success "Check your answer"

        A good answer covers:

        - **SQS:** durable fan-out to a service's work queue.
        - **Lambda:** serverless processing of each notification.
        - **HTTP/HTTPS:** webhooks to partner or internal systems.
        - **Email or email-JSON:** operational alerts to people.
        - **SMS or mobile push:** text alerts or app notifications to users; Amazon Data Firehose is another protocol, for archiving to S3.

3. Which subscription protocols require confirmation, and why?

    ??? success "Check your answer"

        A good answer covers:

        - **Require confirmation:** HTTP/HTTPS and email (email-JSON) subscriptions, and SQS or Lambda subscriptions that cross accounts when not created by the endpoint owner.
        - **Process:** SNS sends a confirmation message with a token, and the endpoint owner confirms it.
        - **Why:** proves the endpoint owner consents, preventing SNS being used to flood arbitrary URLs or mailboxes.

4. Explain why a subscriber added today does not receive messages published yesterday to a standard topic.

    ??? success "Check your answer"

        A good answer covers:

        - **No retention:** standard topics deliver messages to the subscriptions that exist at publish time and do not store them.
        - **Consequence:** a new subscriber only receives messages published after it subscribes.
        - **Alternatives for replay:** FIFO topics with archiving and replay, EventBridge archives or a stream such as Kinesis.

5. What is a filter policy, and what is the difference between attribute-based and payload-based filtering?

    ??? success "Check your answer"

        A good answer covers:

        - **Filter policy:** a JSON policy on a subscription that defines which messages the subscriber receives; non-matching messages are not delivered to it.
        - **Attribute-based (default):** matches on message attributes, so the body need not be parsed or even be JSON.
        - **Payload-based:** matches on fields inside a JSON message body, set with `FilterPolicyScope = MessageBody`.
        - **Benefit:** filtering in SNS reduces unnecessary deliveries and consumer cost.

#### Intermediate Questions

1. Write the SQS queue policy that allows the topic `arn:aws:sns:us-east-1:111122223333:order-events` to deliver to the queue `arn:aws:sqs:us-east-1:111122223333:shipping-queue`, and explain the purpose of the condition.

    ??? success "Check your answer"

        A good answer covers:

        - **Principal and action:** allow `sns.amazonaws.com` the action `sqs:SendMessage` on resource `arn:aws:sqs:us-east-1:111122223333:shipping-queue`.
        - **Condition:** `"ArnEquals": {"aws:SourceArn": "arn:aws:sns:us-east-1:111122223333:order-events"}`.
        - **Purpose:** restricts the permission to that specific topic, preventing any other topic (including other accounts' topics) from sending to the queue, the confused deputy problem.

2. Write a filter policy that matches messages whose `eventType` is `OrderPlaced` or `OrderUpdated`, whose `country` is not `US`, and whose `total` is between 100 and 1,000.

    ??? success "Check your answer"

        A good answer covers:

        - **Policy:** `{"eventType": ["OrderPlaced", "OrderUpdated"], "country": [{"anything-but": "US"}], "total": [{"numeric": [">=", 100, "<=", 1000]}]}`.
        - **Semantics:** values in an array are ORed; separate keys are ANDed.
        - **Scope:** these are message attributes by default; with payload-based filtering the same keys must match the body's structure.
        - **Type:** `total` must be a Number attribute (or numeric JSON value) for numeric matching.

3. Compare the default SNS delivery behaviour for SQS, Lambda and HTTPS subscriptions, and explain how you would protect a partner HTTPS endpoint that can accept only 20 requests per second.

    ??? success "Check your answer"

        A good answer covers:

        - **SQS and Lambda:** AWS-managed endpoints; SNS retries very persistently (documented as over 100,000 attempts across about 23 days) when the service is unavailable or throttling; Lambda function errors then follow Lambda's asynchronous retry settings.
        - **HTTPS:** a modest default retry policy (three retries by default) that can be customised with backoff settings; 4xx responses are treated as permanent failures.
        - **Protecting a 20 request per second partner:** set `throttlePolicy.maxReceivesPerSecond` to 20 on the subscription and a subscription DLQ; for stronger protection, subscribe an SQS queue and have a worker (or an EventBridge API destination with a rate limit) call the partner at a controlled rate with retries.

4. Explain the key policy statements needed when a CloudWatch alarm publishes to an encrypted SNS topic that fans out to encrypted SQS queues.

    ??? success "Check your answer"

        A good answer covers:

        - **Topic key:** CloudWatch alarms require a customer managed key (not `aws/sns`), whose key policy allows the `cloudwatch.amazonaws.com` service principal `kms:Decrypt` and `kms:GenerateDataKey*`.
        - **Queue keys:** each encrypted SQS queue's customer managed key must allow the `sns.amazonaws.com` service principal `kms:Decrypt` and `kms:GenerateDataKey*`, so SNS can write encrypted messages.
        - **Conditions:** add `aws:SourceArn` or `aws:SourceAccount` conditions to restrict which alarms and topics may use the keys.
        - **Consumers:** consumer roles need `kms:Decrypt` on the queue key.

5. Describe how you would use raw message delivery and message attributes so that an ECS consumer can decide how to process a message without parsing the body.

    ??? success "Check your answer"

        A good answer covers:

        - **Raw message delivery:** enable it on the SQS subscription so the queue receives the original message body instead of the SNS JSON envelope.
        - **Attributes:** publishers set message attributes such as `eventType`, `schemaVersion` and `priority`; with raw delivery these become SQS message attributes.
        - **Consumer:** the ECS worker requests attributes with `MessageAttributeNames` on receive and routes processing on them without parsing the body.
        - **Limit:** SQS supports up to 10 message attributes per message.

#### Advanced Questions

1. A central platform account publishes `order-events`; an analytics team in another account and a disaster-recovery copy in another Region must both consume it through SQS. Specify every policy, confirmation and encryption requirement, and explain the limitations of cross-Region delivery.

    ??? success "Check your answer"

        A good answer covers:

        - **Topic access policy:** allows `sns:Subscribe` for the consumer account's principal.
        - **Queue policy:** each queue allows `sns.amazonaws.com` to send, conditioned on `aws:SourceArn` equal to the topic ARN.
        - **Confirmation:** if the queue owner creates the subscription no confirmation is needed; if the topic owner creates it, the queue owner must confirm.
        - **Encryption:** each encrypted queue uses a customer managed key whose key policy allows SNS to use `kms:GenerateDataKey` and `kms:Decrypt`; the topic's key policy allows the publisher.
        - **Cross-Region limits:** delivery adds latency and inter-Region data transfer charges and has documented restrictions for opt-in Regions; it is useful for DR copies and regional consumers but is not a multi-Region active-active design by itself.
        - **Consumers:** both consumers remain idempotent because delivery is at least once.

2. A bank requires ordered delivery of account events to four consumers, 20,000 messages per second at peak, replay for 90 days and PII masking for one analytics consumer. Evaluate SNS FIFO with high-throughput mode, archive and data protection policies against an alternative using Kinesis Data Streams, and recommend a design.

    ??? success "Check your answer"

        A good answer covers:

        - **SNS FIFO option:** high-throughput mode for ordering per message group (account ID), fan-out to four SQS FIFO queues, archive with replay (up to 365 days) covering the 90-day requirement; verify that per-topic throughput quotas cover 20,000 messages per second in the Region.
        - **Constraints:** FIFO subscriptions deliver to SQS queues only, and SNS message data protection policies apply to standard topics only (and AWS no longer offers the feature to new customers), so PII masking for the analytics consumer must be a separate step, for example a Lambda or pipe that masks data before writing to that consumer's store.
        - **Kinesis alternative:** a stream keyed by account ID, provisioned for 20,000 records per second, retention extended to at least 90 days, four consumers (enhanced fan-out) reading independently; masking done by a separate processing step for the analytics consumer.
        - **Recommendation:** either can work; Kinesis suits high-volume replay and analytics, while SNS FIFO is simpler for queue-based consumers with managed archive and masking. Justify the choice against throughput quotas, replay needs and team skills.

3. Analyse the failure modes of an SNS-to-SQS-to-Lambda pipeline end to end (publish throttling, key policy errors, filter misconfiguration, Lambda throttling, poison messages, duplicate delivery) and specify the metric, alarm and remediation for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Publish throttling:** metric SNS `NumberOfMessagesPublished` and publisher errors; alarm on throttling exceptions; remediate with retries with backoff, batching and quota increases.
        - **Key policy errors:** `NumberOfNotificationsFailed` on the topic; alarm on any failures; fix the queue key policy for the SNS service principal.
        - **Filter misconfiguration:** `NumberOfNotificationsFilteredOut` rising unexpectedly; alarm on anomalies; test filter policies in CI.
        - **Lambda throttling and poison messages:** Lambda `Throttles`, errors and SQS `ApproximateAgeOfOldestMessage` and DLQ depth; adjust maximum concurrency, add partial batch responses and fix or redrive poison messages.
        - **Duplicate delivery:** detect through idempotency table hits; make consumers idempotent with event IDs.

4. Explain why business-critical microservices should consume an SNS topic through SQS queues rather than subscribing directly, and design the fan-out configuration for payment, inventory and fraud services, including how a new marketing consumer is later added.

    ??? success "Check your answer"

        A good answer covers:

        - **Why queues:** a queue gives durability while a service is redeployed or down, load levelling at the consumer's own pace, independent `maxReceiveCount` and DLQ per service, visibility through queue depth and age, and DLQ redrive after fixes.
        - **Topology:** one queue per consuming service (not per instance), each with a filter policy, for example all events for payment, `OrderPlaced` for inventory and `total >= 500` for fraud.
        - **Policies and keys:** queue policies allowing `sns.amazonaws.com` with `aws:SourceArn`, and customer managed KMS keys whose policies allow SNS, because SNS cannot use the AWS managed `aws/sqs` key.
        - **Delivery format:** raw message delivery unless a consumer needs the envelope.
        - **Idempotency:** duplicates can arise at both the SNS and SQS layers, so consumers use a business key such as `orderId` plus `eventType`, not the message IDs.
        - **New consumer:** marketing creates its own queue, subscribes it with a numeric filter and deploys its consumer without any change to the order service.

5. A multi-tenant SaaS platform publishes tenant events to a standard SNS topic consumed through SQS by a shared worker fleet. A single large tenant causes latency for all others. Propose solutions using SNS message group IDs with SQS fair queues, per-tier topics or queues, and maximum concurrency controls, and discuss the trade-offs of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Message group IDs with fair queues:** publish with the tenant ID as `MessageGroupId` to standard topics and SQS fair queues, so SQS reduces dwell time for quiet tenants; minimal change, but only mitigates, not isolates.
        - **Per-tier topics or queues:** separate queues (or subscriptions filtered by tier) for large and small tenants with dedicated consumers; strong isolation, but more resources and routing logic.
        - **Maximum concurrency controls:** cap concurrency of the large tenant's queue consumer so it cannot monopolise shared downstream resources; protects others but slows the large tenant.
        - **Trade-offs:** cost and operational complexity versus isolation strength; a combination (fair queues by default, dedicated queue for the very large tenant) is common.

### 6.3.3 Stream Processing with Amazon Kinesis

#### Beginner Questions

1. What are the write and read throughput limits of a single provisioned Kinesis shard, and why is the read limit higher?

    ??? success "Check your answer"

        A good answer covers:

        - **Write limit:** 1 MB per second or 1,000 records per second per shard.
        - **Read limit:** 2 MB per second per shard shared across standard consumers (and 5 `GetRecords` calls per second); enhanced fan-out gives each registered consumer its own 2 MB per second per shard.
        - **Why higher:** several consumers read the same data, and consumers that fall behind must be able to catch up faster than data arrives.

2. Name the four Kinesis family services and state the primary purpose of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Kinesis Data Streams:** durable, ordered, sharded stream for real-time ingestion read by multiple custom consumers with replay.
        - **Amazon Data Firehose (formerly Kinesis Data Firehose):** managed delivery of streaming data to destinations such as S3, Redshift and OpenSearch, with buffering and format conversion.
        - **Amazon Managed Service for Apache Flink (formerly Kinesis Data Analytics):** stateful stream processing with Flink, including windows and joins.
        - **Kinesis Video Streams:** ingestion, storage and playback of video and other time-encoded media.

3. What is the default retention period of a Kinesis data stream, and what is the maximum?

    ??? success "Check your answer"

        A good answer covers:

        - **Default:** 24 hours.
        - **Maximum:** 365 days (8,760 hours), with extended retention (up to 7 days) and long-term retention charged extra.
        - **Meaning:** retention defines the replay and recovery window regardless of whether records have been read.

4. Explain the difference between `TRIM_HORIZON` and `LATEST` starting positions.

    ??? success "Check your answer"

        A good answer covers:

        - **`TRIM_HORIZON`:** start from the oldest record still retained in the shard, processing the full backlog.
        - **`LATEST`:** start just after the most recent record, processing only new records.
        - **Choice:** `TRIM_HORIZON` for new consumers that must not miss data or for reprocessing; `LATEST` when only current data matters; `AT_TIMESTAMP` for a specific point.

5. Why must a stream consumer be idempotent?

    ??? success "Check your answer"

        A good answer covers:

        - **At-least-once delivery:** producers retry after lost acknowledgements, creating duplicate records.
        - **Consumer restarts:** consumers resume from the last checkpoint, so records processed after it are processed again; failed batches are retried.
        - **Consequence:** without idempotency, duplicates cause double counting or repeated side effects.
        - **Technique:** deduplicate using event IDs (conditional writes) or design writes as upserts.

#### Intermediate Questions

1. A workload sends 3,000 records per second of 2 KB each. Calculate the minimum number of provisioned shards and explain which limit dominates.

    ??? success "Check your answer"

        A good answer covers:

        - **Bytes:** 3,000 × 2 KB = 6,000 KB per second, about 6 MB per second, needing 6 shards at 1 MB per second each.
        - **Records:** 3,000 records per second needs 3 shards at 1,000 records per second each.
        - **Answer:** at least 6 shards; the byte limit dominates. Add headroom (for example 7 to 8) for peaks and uneven key distribution.

2. Describe how `BisectBatchOnFunctionError`, `MaximumRetryAttempts` and an on-failure destination work together in a Lambda event source mapping.

    ??? success "Check your answer"

        A good answer covers:

        - **`BisectBatchOnFunctionError`:** on failure, splits the batch in two and retries each half, isolating the bad record.
        - **`MaximumRetryAttempts`:** bounds retries so a failing record does not block the shard indefinitely (default is unlimited until expiry).
        - **On-failure destination:** an SQS queue, SNS topic or S3 bucket receives metadata about discarded records (shard, sequence numbers) so they can be investigated and re-read before retention ends.
        - **Together:** the shard keeps moving, the poison record is isolated quickly, and nothing is silently lost; `MaximumRecordAgeInSeconds` and `ReportBatchItemFailures` complement them.

3. Compare provisioned and on-demand capacity modes in terms of scaling, pricing dimensions and suitable workloads.

    ??? success "Check your answer"

        A good answer covers:

        - **Provisioned:** you choose the shard count and reshard manually or with automation; billed per shard-hour plus PUT payload units; suited to predictable traffic and cost control.
        - **On-demand:** capacity scales automatically, accommodating up to double the previous peak write throughput; billed per GB written and read plus a per-stream hour charge; suited to new, spiky or unknown workloads.
        - **Limits:** on-demand can throttle if traffic jumps beyond double the recent peak within minutes; provisioned throttles when shards are under-sized.
        - **Switching:** a stream can switch between modes (with limits on frequency).

4. Explain why Firehose Parquet conversion requires a larger buffer, and describe the effect of Parquet on Athena query cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Parquet conversion:** Firehose converts records into columnar Parquet files using a schema from the Glue Data Catalog.
        - **Buffer size:** columnar files are efficient only when large; Firehose requires a minimum buffer size of 64 MiB with format conversion, producing fewer, larger files.
        - **Athena cost:** Athena charges per data scanned; Parquet is compressed and lets queries read only the needed columns and skip row groups, typically reducing scanned data and cost substantially compared with JSON.
        - **Trade-off:** larger buffers increase delivery latency.

5. What is a KCL lease table, and what happens when two unrelated KCL applications are deployed with the same application name?

    ??? success "Check your answer"

        A good answer covers:

        - **Lease table:** a DynamoDB table, named after the KCL application name, recording which worker holds each shard lease and the checkpoint for each shard.
        - **Same application name:** both applications share the same lease table, so they compete for leases; each shard is processed by only one of them, and they overwrite each other's checkpoints.
        - **Result:** each application silently misses records and corrupts the other's progress; every KCL application needs a unique name.

#### Advanced Questions

1. Design a partition key strategy for a multi-tenant SaaS analytics stream in which one tenant generates 60 percent of traffic but per-user ordering is required. Justify the trade-offs.

    ??? success "Check your answer"

        A good answer covers:

        - **Problem:** keying by tenant puts 60 percent of traffic on one shard, exceeding per-shard limits; keying randomly loses per-user ordering.
        - **Strategy:** use the user ID (or tenant plus user ID) as the partition key, so ordering is preserved per user while the large tenant spreads across many shards.
        - **Hot users:** if a single user could exceed 1 MB per second, that user must be sub-partitioned, sacrificing strict order for that user or reordering downstream by sequence numbers.
        - **Trade-offs:** per-tenant aggregation now requires combining data from many shards, and per-tenant ordering is lost; monitor shard-level metrics for skew.

2. Explain how Apache Flink achieves exactly-once state consistency over a Kinesis source, and what additional conditions are required for exactly-once results in an external database.

    ??? success "Check your answer"

        A good answer covers:

        - **Checkpoints:** Flink periodically takes consistent snapshots of operator state together with the Kinesis read positions (sequence numbers) per shard.
        - **Recovery:** after failure, Flink restores state and rewinds the source to the checkpointed positions, so each record affects state exactly once even though records are re-read.
        - **External database:** exactly-once results also require either a transactional sink (two-phase commit tied to checkpoints) or idempotent writes (upserts keyed on deterministic IDs), because records after the last checkpoint are reprocessed.
        - **Producer duplicates:** duplicate records in the stream itself must be deduplicated by event ID.

3. Propose a cross-Region disaster recovery design for a critical Kinesis pipeline, including how consumers resume and how duplicates are handled.

    ??? success "Check your answer"

        A good answer covers:

        - **Replication:** producers write to streams in two Regions (dual write), or a replicator application (for example Lambda or Flink) copies records to the secondary Region's stream; data landed in S3 is replicated with S3 replication.
        - **Consumers:** standby consumers exist in the secondary Region (as code), using their own lease tables and checkpoints.
        - **Resume:** on failover, consumers start from a timestamp slightly before the failure (`AT_TIMESTAMP`), deliberately overlapping to avoid gaps.
        - **Duplicates:** overlap and dual writes cause duplicates, so consumers deduplicate on event IDs and use idempotent writes.
        - **Failover:** Route 53 or configuration switches producers; runbooks are rehearsed.

4. Compare tumbling, sliding and session windows, and give a business metric for which each is the correct choice, including how late data should be treated.

    ??? success "Check your answer"

        A good answer covers:

        - **Tumbling:** fixed, non-overlapping windows; for example orders per minute for billing or reporting.
        - **Sliding (hopping):** fixed-length windows that overlap and advance by a smaller step; for example the moving average of transactions over the last 10 minutes updated every minute for fraud scoring.
        - **Session:** windows defined by periods of activity separated by an inactivity gap; for example user session length and pages per session.
        - **Late data:** use event time with watermarks; allow a bounded lateness that updates results, and route later events to a side output for correction.

5. A pipeline must deliver clickstream to both a real-time dashboard with 2-second freshness and a cost-efficient data lake queried daily. Design the pipeline and explain how you avoid the small-files problem while meeting the freshness requirement.

    ??? success "Check your answer"

        A good answer covers:

        - **Ingestion:** producers write clickstream to Kinesis Data Streams.
        - **Real-time path:** Managed Service for Apache Flink (or Lambda) aggregates per second and writes to a low-latency store (for example DynamoDB or ElastiCache) that the dashboard reads, meeting 2-second freshness.
        - **Data lake path:** Firehose reads the same stream and delivers to S3 with Parquet conversion, large buffers (for example 128 MiB or several minutes) and partitioning by date and hour.
        - **Small files:** large buffers and bounded partition keys keep files large; periodic compaction (for example Iceberg tables with compaction) handles any remaining small files.
        - **Independence:** the two paths read the stream independently, so latency and file size requirements do not conflict.

### 6.3.4 Event Routing with Amazon EventBridge

#### Beginner Questions

1. Why do AWS service events such as `ECS Task State Change` appear only on the default event bus, and what must you do to process them in a central account?

    ??? success "Check your answer"

        A good answer covers:

        - **Default bus only:** AWS services emit their events to the default event bus of the account and Region where the resource lives; they cannot be redirected to custom buses at the source.
        - **Central processing:** create a rule on each account's default bus (in every relevant Region) that forwards matching events to a bus in the central account.
        - **Permissions:** the central bus policy allows the source accounts (for example by `aws:PrincipalOrgID`), and the forwarding rule uses an IAM role allowed `events:PutEvents` on the target bus.
        - **Scale:** deploy these rules with StackSets across the organisation.

2. List three naming conventions for `source` and `detail-type` and explain why each helps routing.

    ??? success "Check your answer"

        A good answer covers:

        - **`source` as reverse DNS of the owning domain:** for example `com.dso303.orders`; identifies the owner, avoids collisions and never uses the reserved `aws.` prefix.
        - **`detail-type` as a past-tense business fact:** for example `Order Placed`; patterns can match exact event types predictably.
        - **Versioning in metadata or `detail-type`:** `schemaVersion` in `detail.metadata`, and breaking versions as a new `detail-type` such as `Order Placed v2`, so consumers opt in to new versions.
        - **Benefit:** consistent naming makes rules precise, discovery easier and accidental matches less likely.

3. What is the purpose of `TestEventPattern`, and how would you use it in a CI pipeline?

    ??? success "Check your answer"

        A good answer covers:

        - **Purpose:** `TestEventPattern` checks whether a given event matches an event pattern without deploying a rule.
        - **CI use:** store sample events (from the schema registry) and each rule's pattern in Git; a pipeline step calls the API (or a local equivalent) asserting that intended events match and unrelated events do not.
        - **Benefit:** catches typos, case errors and type mismatches (such as numbers as strings) before deployment.

4. Name three AWS operational event sources and an automated response for each.

    ??? success "Check your answer"

        A good answer covers:

        - **ECS task state change:** on unexpected task stops, notify the owning team or trigger a diagnostic Lambda.
        - **GuardDuty finding:** for high-severity findings, isolate the instance with a quarantine security group through Step Functions or Lambda.
        - **Config compliance change:** when a bucket becomes public, re-enable Block Public Access automatically through Systems Manager Automation; other valid examples include CodePipeline failures, EC2 state changes and Health events.

5. Why should an SQS queue normally sit between an EventBridge rule and an ECS service?

    ??? success "Check your answer"

        A good answer covers:

        - **Buffering:** EventBridge pushes events; a queue absorbs bursts so the service consumes at its own pace.
        - **Retries and DLQ:** SQS provides per-message retries and a DLQ, independent of EventBridge's retry policy.
        - **Isolation and scaling:** the service can scale on backlog, be redeployed or be unavailable without losing events.
        - **Reason:** ECS services cannot be invoked directly as long-running event consumers by EventBridge.

#### Intermediate Questions

1. Write a bus policy statement that allows only accounts in your organisation to publish events with source `com.dso303.payments` to a hub bus, and explain each condition.

    ??? success "Check your answer"

        A good answer covers:

        - **Principal and action:** allow `"Principal": "*"` the action `events:PutEvents` on the hub bus ARN.
        - **Organisation condition:** `"StringEquals": {"aws:PrincipalOrgID": "o-xxxxxxxxxx"}` restricts callers to accounts in the organisation.
        - **Source condition:** `"StringEquals": {"events:source": "com.dso303.payments"}` allows only events with that source, preventing spoofing of other domains' events.
        - **Refinement:** where possible restrict to the payments account (`aws:PrincipalAccount`) so other organisation accounts cannot publish payments events.

2. Explain how EventBridge Scheduler can implement a 30-minute reservation hold, including creation, cancellation, the race condition and clean-up.

    ??? success "Check your answer"

        A good answer covers:

        - **Creation:** when a reservation is made, create a one-time schedule `at(now + 30 minutes)` named after the reservation, targeting a queue or function with the reservation ID, with `ActionAfterCompletion = DELETE`.
        - **Cancellation:** when payment completes, delete the schedule.
        - **Race condition:** payment and expiry can occur at nearly the same time, and delivery is at least once, so the handler conditionally releases the hold only if the reservation is still unpaid (for example a DynamoDB conditional update).
        - **Clean-up:** completed schedules delete themselves; deletion failures are tolerated because the handler checks state.

3. Compare Pipes enrichment with a Lambda target that enriches and republishes; discuss cost, failure handling and ordering for a Kinesis source.

    ??? success "Check your answer"

        A good answer covers:

        - **Pipes enrichment:** a Lambda, Step Functions, API destination or API Gateway enriches events inside the pipe; cost per pipe request plus enrichment; ordering per shard is preserved through the pipe.
        - **Lambda target that republishes:** extra invocations and `PutEvents` charges, plus code for retries and error handling; ordering is lost once events go to a bus.
        - **Failure handling:** pipes use their own retry policy and DLQ; the Lambda approach requires the event source mapping's bisection and failure destination plus republish retries.
        - **Judgement:** for a Kinesis source, Pipes enrichment is simpler and preserves order; a custom Lambda gives more control at higher complexity.

4. Describe a versioning strategy for a public event that must rename a field, from the first commit to the retirement of the old version.

    ??? success "Check your answer"

        A good answer covers:

        - **Additive change first:** in version 1, add the new field alongside the old one (both populated), which is backward compatible.
        - **New version:** publish `Order Placed v2` (or `schemaVersion` 2) with only the renamed field, registered in the schema registry, while continuing to publish v1.
        - **Consumer migration:** consumers move their rules and code to v2, tracked through rule inventory and metrics.
        - **Deprecation:** announce a retirement date, monitor remaining v1 consumers, then stop publishing v1 and remove the old field.
        - **Guardrails:** compatibility checks in producer CI fail on renames without a version change.

5. Explain how KEDA scales an EKS Deployment that consumes events routed from EventBridge, including the identity configuration.

    ??? success "Check your answer"

        A good answer covers:

        - **Routing:** an EventBridge rule targets an SQS queue owned by the service.
        - **KEDA:** a `ScaledObject` with the `aws-sqs-queue` scaler reads queue length and scales the Deployment between minimum and maximum replicas (including to zero).
        - **Identity for KEDA:** the KEDA operator uses EKS Pod Identity (or IRSA) with permission to read queue attributes, configured through a `TriggerAuthentication` with the `aws` pod identity provider.
        - **Identity for pods:** the consumer pods use their own service account mapped to a role allowing receive, delete and change visibility (and `kms:Decrypt` if encrypted).

#### Advanced Questions

1. Design a multi-Region, multi-account event mesh for a regulated bank, including topology, global endpoints, encryption, spoofing prevention, archive and replay, and disaster-recovery testing.

    ??? success "Check your answer"

        A good answer covers:

        - **Topology:** separate accounts per domain plus a central hub account per Region (hub-and-spoke), with spokes publishing public events to the hub and the hub routing to consumer accounts.
        - **Multi-Region:** global endpoints with Route 53 health checks fail producers over to the secondary Region's bus, with event replication enabled; consumers deployed in both Regions handle duplicates.
        - **Security:** customer managed KMS keys for buses, bus policies restricted by organisation and `events:source`, SCPs preventing changes to routing outside the pipeline.
        - **Spoofing prevention:** each account may publish only its own sources (bus policy conditions per account), and schemas validated in CI.
        - **Archive, replay and DR testing:** archives on the hub bus with retention matching regulatory needs, replay rehearsed, and regular failover tests of global endpoints with measured RTO and RPO.

2. An order fulfilment process must request payment from another domain, wait for the result, and then announce completion to shipping and loyalty services. Explain how Step Functions orchestration and EventBridge choreography are combined, where the boundary between them lies, and how the workflow waits for an asynchronous reply.

    ??? success "Check your answer"

        A good answer covers:

        - **Principle:** orchestrate within a bounded context and choreograph between contexts.
        - **Start:** an `Order Placed` rule on the bus starts the Step Functions fulfilment workflow in the orders domain.
        - **Request and wait:** the workflow publishes `Payment Requested` through the `events:putEvents` integration with `.waitForTaskToken`, carrying the task token as opaque metadata.
        - **Reply:** the payments service publishes `Payment Captured` with the token, and a rule (or a small Lambda function) calls `SendTaskSuccess` or `SendTaskFailure`, so the workflow can wait for days without polling.
        - **Completion:** the workflow publishes `Order Fulfilled`, which shipping and loyalty consume through their own rules without knowing about Step Functions.
        - **Observability:** `Step Functions Execution Status Change` events feed alerting and dashboards.

3. Design an auto-remediation platform for Config and GuardDuty findings across 200 accounts that supports notify-only mode, exemptions, approvals for high-impact actions, idempotency and full audit.

    ??? success "Check your answer"

        A good answer covers:

        - **Collection:** Config and GuardDuty events forwarded from all accounts and Regions to a security hub bus (GuardDuty delegated administrator aggregates findings).
        - **Decision layer:** a Step Functions workflow checks a configuration table for mode (notify-only or remediate) and exemptions (by account, resource tag or rule).
        - **Approvals:** high-impact actions pause with a task token for human approval through a chat or ticketing integration; low-impact actions proceed automatically.
        - **Idempotency:** remediations check current resource state before acting and record executions keyed by finding ID.
        - **Audit:** every decision and action logged to an immutable store (CloudTrail, S3 with Object Lock), with remediation roles in member accounts assumed with least privilege.

4. Propose an end-to-end testing strategy for a choreographed saga spanning four domains and three accounts, covering unit, pattern, contract, integration, replay and failure testing.

    ??? success "Check your answer"

        A good answer covers:

        - **Unit tests:** each service's handlers and saga steps with mocks.
        - **Pattern tests:** `TestEventPattern` against sample events for every rule.
        - **Contract tests:** producer schemas checked against consumer expectations in CI, failing on breaking changes.
        - **Integration tests:** ephemeral environments in the three accounts run the full saga end to end, including compensations.
        - **Replay and failure testing:** replay archived events into a test bus to check idempotency, and inject failures (target errors, timeouts, FIS) to verify retries, DLQs, timeouts and compensating actions.

5. An event hub has 280 rules on one bus, rising latency and occasional throttling. Diagnose the likely causes and design a migration to a scalable topology without downtime or duplicate side effects.

    ??? success "Check your answer"

        A good answer covers:

        - **Likely causes:** many broad or overlapping rules, deep routing chains (hops), large numbers of targets and invocation quotas reached during peaks; one shared bus is a single throttling domain.
        - **Diagnosis:** CloudWatch `ThrottledRules`, `FailedInvocations`, latency and per-rule `MatchedEvents`; rule inventory to find duplicates and unused rules.
        - **Target topology:** split into domain buses or deliver directly to consumer accounts, consolidate rules, narrow patterns and request quota increases.
        - **Migration without downtime:** create new buses and rules in parallel, publish to both, have consumers deduplicate on event ID while both paths are live, then remove old rules one consumer at a time.
        - **Duplicate side effects:** idempotent consumers and a cut-over plan per consumer prevent double processing.


# DSO303 — Cloud Native Solution Design
## Practice Question Pool — SOLUTIONS

**Companion to:** `DSO303_Practice_Questions.md`
**Class:** B.E. Fourth Year (SWE), Sem-I

> Model answers for all 50 questions. For the written questions these are fuller than a student would be expected to produce under time pressure — treat the **bolded** terms and the tables as the markable content, and the surrounding explanation as teaching notes.

---

## Section A

**A1 — (b).** IAM evaluation is: explicit `Deny` > explicit `Allow` > implicit deny. The user-level deny overrides the group-level allow, but only for the action and resource it names. (a) is wrong — group and user policies are unioned, neither takes precedence. (c) is wrong — conflicts resolve, they do not void policies. (d) is wrong — a deny needs no bucket-policy participation.

**A2 — (b).** Objects must remain in S3 Standard for at least 30 days before a lifecycle transition to Standard-IA or One Zone-IA. The rule is simply not applied until day 30. (c) misstates the billing; (d) invents a substitution S3 never performs.

**A3 — (b).** NACL rules are numbered and evaluated lowest-number-first; the first matching rule decides and evaluation stops. (a) describes security-group behaviour loosely; (c) is wrong — position, not rule type, decides; (d) is wrong — NACLs are stateless.

**A4 — (c).** `st1` (Throughput Optimized HDD) and `sc1` (Cold HDD) cannot be root volumes. gp2, gp3, io1 and io2 all can.

**A5 — (b).** gp3 tops out at 16,000 IOPS per volume, so (a) is impossible. `st1` is HDD-backed sequential-throughput storage with high latency — wrong workload entirely. io2 / io2 Block Express provides provisioned IOPS at consistent sub-millisecond latency. (d) is not "the only supported approach" — a single io2 volume meets the requirement.

**A6 — (b).** Fargate does not support GPU-attached tasks, privileged containers, or host-level Docker access, because you never touch the host. (a), (c) and (d) are all things Fargate does support.

**A7 — (b).** A /20 has 2^12 = 4096 addresses; AWS reserves 5, leaving **4091**. (c) is the classic non-AWS answer (total − 2).

**A8 — (a).** A Gateway VPC endpoint for S3 adds a prefix-list route to the subnet's route table, keeping traffic on the AWS network with no IGW or NAT. (b) is impossible without an IGW route; (c) opens a NACL to a path that does not exist; (d) confuses network reachability with authorisation.

**A9 — (b).** Security Groups: stateful, evaluated at the instance/ENI, allow-rules only, all rules evaluated. NACLs: stateless, evaluated at the subnet boundary, allow and deny, ordered.

**A10 — (b).** EFS is a managed NFS file system reachable from mount targets in every AZ, supporting concurrent POSIX read/write from many instances. (a) fails: Multi-Attach is single-AZ and requires a cluster-aware filesystem. (c) is object storage, not POSIX. (d) is not concurrent shared access.

## Section B

**A11.** Create one IAM **group per faculty** (`Faculty-Sci-S3`, `Faculty-Eng-S3`, …), attach the faculty's S3 policy to the group, and place each user in the appropriate group. Policies attached directly to 480 users are unmaintainable: a permission change requires 480 edits, drift is invisible, and audit becomes guesswork. On transfer, no policy is edited at all — the user is removed from one group and added to another, an O(1) operation. Note also that groups are for humans; workloads should use roles.

**A12.**
- **User** — a long-lived identity for a single human or, historically, an application. Example: a lecturer logging into the console.
- **Group** — a container of users used purely to attach policies at scale. Example: all teaching assistants who need read access to a training bucket.
- **Role** — an identity with no permanent credentials, assumed temporarily by a principal, yielding short-lived STS credentials. Example: an EC2 instance or ECS task that must call S3.
A **group cannot be a principal** — you cannot assume a group, and no policy can name a group in its `Principal` element.

**A13.** Three defects: (i) the credentials are long-lived and never rotate automatically, so a leak is permanent until manually revoked; (ii) they are stored in a file that will end up in version control, logs, or an AMI; (iii) they are copied to every instance, so blast radius and attribution are both poor — CloudTrail shows one user, not one workload.
Correct mechanism: create an **IAM role** with a DynamoDB policy, attach it to the instance via an **instance profile**. The application obtains credentials from the **Instance Metadata Service (IMDSv2)** at `169.254.169.254`; the AWS SDK does this automatically through the default credential provider chain. The credentials are temporary and rotated by AWS with no application involvement.

**A14.**
a) `dorji` can list the bucket `student-uploads` and read its region, and can `GetObject`/`PutObject` **only** under the prefix `student-uploads/dorji/`. He cannot read or write other users' prefixes, cannot delete anything, and cannot change bucket configuration.
b) `s3:ListBucket` is a **bucket-level** operation, so its resource is the bucket ARN with no `/*`. `GetObject`/`PutObject` are **object-level** operations, so the resource must include an object key path. Mixing the two formats is the most common cause of "ListBucket denied" errors.
c) `aws s3 rm` calls `s3:DeleteObject`, which is not in the allowed action list, so it hits the implicit deny. Minimum change: add `"s3:DeleteObject"` to the **ObjectLevel** statement only — leaving the resource as `arn:aws:s3:::student-uploads/${aws:username}/*` so deletion stays confined to the user's own prefix.

**A15.**
- **Cross-account role:** Account A creates a role with a trust policy naming Account B; the contractor calls `sts:AssumeRole` and receives credentials valid for a bounded session (15 min–12 h). Revocation is instant — delete the role or edit the trust policy. CloudTrail records the `AssumeRole` event and the session name, so actions are attributable to a named session. An external ID can be required to defeat the confused-deputy problem.
- **Bucket policy to the contractor's user:** grants standing access to a permanent identity. Revocation requires editing the bucket policy, and if the contractor's user is deleted and recreated the ARN may silently break or, worse, be reused.
**Recommend the role.** Short credential lifetime, cleaner audit trail, single revocation point, and access naturally expires with the session rather than persisting for 90 days by accident. Enforce the 90-day boundary with a `Condition` on `aws:CurrentTime` in the trust policy.

**A16.** A permissions boundary is a managed policy attached to a user or role that defines the **maximum** permissions that identity can ever have; it grants nothing by itself. Effective permissions are the **intersection** of the identity policy and the boundary — here, `ec2:Describe*` only. Logic: an action is allowed only if permitted by both the identity policy and the boundary, and not explicitly denied anywhere.

**A17.** Use a **Service Control Policy (SCP)** in AWS Organizations, applied to the OU containing the member accounts, denying all actions where `aws:RequestedRegion` is not in the allowed list. An identity policy is insufficient because it is created and edited *inside* the member account — any account administrator can simply rewrite or detach it. An SCP is a permission ceiling imposed from the management account that no member-account principal, including its root user, can exceed.

## Section C

**A18.**
- **Day 0–29:** S3 Standard — frequent downloads; no transition is even permitted before day 30.
- **Day 30:** transition to **S3 Standard-IA** — access is now occasional; per-GB storage is markedly cheaper and millisecond retrieval is preserved, at the cost of a per-GB retrieval charge that occasional access does not trigger often.
- **Day 365:** transition to **S3 Glacier Deep Archive** — the cheapest class available, and the stated 12-hour retrieval tolerance and once-a-year access pattern fit its retrieval model (standard retrieval ~12 hours) and 180-day minimum storage duration, which the 7-year retention comfortably exceeds.
- **Day ~2555 (7 years):** expiration action to delete, if the compliance period ends there.
Glacier Flexible Retrieval is a defensible alternative at day 365 only if retrieval had to be faster than 12 hours; Deep Archive is cheaper and the requirement permits it.

**A19.**

| | Retrieval time | Minimum storage duration | Designed for |
|---|---|---|---|
| Glacier Instant Retrieval | Milliseconds | 90 days | Archive data needing immediate access, ~once a quarter |
| Glacier Flexible Retrieval | Minutes to 12 hours (Expedited / Standard / Bulk) | 90 days | Backups accessed 1–2 times a year where a wait is tolerable |
| Glacier Deep Archive | 12–48 hours | 180 days | Long-term compliance retention, accessed rarely if ever |

For a dataset queried **unpredictably but needing millisecond response**, Flexible Retrieval and Deep Archive are both wrong — neither can return an object synchronously; a restore job must complete first. Glacier Instant Retrieval is the only archive class that meets a millisecond SLA.

**A20.** Two causes. (i) **Minimum billable object size:** Standard-IA bills every object as if it were at least **128 KB**. Objects of 40 KB are therefore billed at 128 KB — a 3.2× inflation on the storage volume that erases the lower per-GB rate. (ii) **Per-request and per-GB retrieval charges:** Standard-IA adds a retrieval fee per GB and has higher per-request costs; on 20 million small objects, request and retrieval charges dominate. Small, frequently accessed objects belong in S3 Standard.

**A21.** Both have identical per-GB pricing structure and the same 30-day minimum, but **Standard-IA replicates across at least three Availability Zones** (99.99% availability SLA target), while **One Zone-IA stores data in a single AZ** — the data is lost if that AZ is destroyed, and unavailable if the AZ is merely impaired.
- **Appropriate:** secondary copies of data that can be regenerated — thumbnails derived from originals held elsewhere, or a replica of an on-premises backup. Losing the AZ costs a re-generation, not the data.
- **Inappropriate:** the sole copy of student examination records. The 20% cost saving does not justify a single-AZ failure destroying irreplaceable data.

**A22.** Use a **pre-signed URL** (or pre-signed POST). The **backend application**, running with an IAM role that holds `s3:PutObject`, generates a URL signed with its own temporary credentials and returns it to the authenticated browser. The browser uploads directly to S3 using that URL; it never holds an AWS credential. **Expiry** is set at generation time via the `Expires`/expiration parameter, and is additionally capped by the lifetime of the signing credentials — a URL signed by a role's temporary credentials dies when those credentials expire, whichever comes first. The bucket keeps Block Public Access enabled throughout, since the pre-signed URL carries its own authorisation.

**A23.** Versioning keeps every version of an object under the same key, each with a unique version ID. Deleting an object in a versioned bucket does **not** remove data — S3 inserts a zero-byte **delete marker** as the newest version and hides the previous versions; every noncurrent version continues to consume billable storage.
The lifecycle actions that reclaim it are **`NoncurrentVersionExpiration`** (permanently delete noncurrent versions after N days) and **`ExpiredObjectDeleteMarker`** (clean up delete markers whose versions are all gone). A separate `AbortIncompleteMultipartUpload` rule should accompany them, since abandoned multipart parts are also billed and are invisible in a normal object listing.

**A24.** Intelligent-Tiering charges a small **monitoring and automation fee per object per month**. With 5 million objects, that per-object fee is significant regardless of data volume. Worse, objects **smaller than 128 KB are never moved to a lower access tier** — they stay in the Frequent Access tier and are billed at Standard rates — so the 8 KB thumbnails receive no tiering benefit at all while still incurring the monitoring charge. The access pattern also defeats the purpose: daily access means nothing would ever tier down even if it were eligible. S3 Standard is the correct class.

## Section D

**A25.**
a) **EBS gp3** as the root volume. gp3 gives a 3,000 IOPS / 125 MB/s baseline independent of size at a lower per-GB price than gp2, so a small cheap volume still performs adequately. HDD types cannot boot.
b) **EBS st1**. Throughput Optimized HDD is built for large sequential reads and is far cheaper per GB than SSD. It cannot be a boot volume, which the requirement explicitly permits. Size it at 6 TB — st1 throughput scales with size (250 MB/s per TB, capped at 500 MB/s).
c) **Amazon EFS**. The requirement is concurrent read/write from many instances across two AZs, which EBS cannot provide; EFS is multi-AZ, elastic, and mounted over NFS, so a scaling group can attach and detach freely.
d) **EBS io2 (or io2 Block Express)** with 25,000 provisioned IOPS. gp3's 16,000 IOPS ceiling is insufficient, and OLTP latency sensitivity calls for the consistent sub-millisecond profile of Provisioned IOPS SSD.
e) **Instance store (NVMe ephemeral)**. It offers the highest local throughput and lowest latency because it is physically attached, and its data loss on stop/terminate is explicitly acceptable here. It is also included in the instance price.

**A26.** Sequence: (1) optionally quiesce/unmount the volume for a consistent point-in-time image; (2) create an **EBS snapshot** — the snapshot is stored in S3 and is **regional**, not AZ-bound; (3) **create a new volume from the snapshot**, specifying `ap-south-1b` as the target AZ; (4) attach the new volume to the instance in `ap-south-1b`; (5) mount it and verify, then delete the original volume once satisfied.
The property forcing this: **an EBS volume lives in exactly one Availability Zone and can only be attached to an instance in that same AZ.** There is no live cross-AZ attach.
The service that removes the constraint for shared file data is **Amazon EFS**, which is regional and mountable from every AZ simultaneously. (For a cross-*Region* copy, snapshots additionally support copy-to-region.)

**A27.** **gp2** couples IOPS to size: 3 IOPS per GB, minimum 100, maximum 16,000, with burst credits to 3,000 IOPS for volumes under 1,000 GB. **gp3** decouples them: every volume gets a 3,000 IOPS / 125 MB/s baseline regardless of size, and IOPS (to 16,000) and throughput (to 1,000 MB/s) are provisioned independently and paid for separately.
Most likely explanation for the drop: the 200 GB gp2 volume was provisioned at 600 baseline IOPS but was **bursting to 3,000 IOPS**, and possibly its workload also benefited from gp2 throughput above 125 MB/s. After migration the volume sits at the gp3 **default** 3,000 IOPS / **125 MB/s** — and if the workload was throughput-bound rather than IOPS-bound, 125 MB/s is well below what the 200 GB gp2 volume delivered (up to 250 MB/s). The fix is to explicitly provision additional gp3 throughput/IOPS, which the migration does not do automatically.

**A28.** **st1** — Throughput Optimized HDD, up to 500 MB/s, minimum size 125 GB, intended for big sequential workloads (log processing, big data, data warehouse). **sc1** — Cold HDD, lower throughput ceiling (~250 MB/s), cheapest per GB, for infrequently accessed sequential data. Neither can boot; neither suits small random I/O.
Two reasons a 100 GB st1 underperforms: (i) **throughput scales with volume size** — st1 delivers roughly 40 MB/s per TB baseline and 250 MB/s per TB burst, so a small volume gets a small allocation and exhausts its burst credits quickly; a 100 GB volume cannot reach 500 MB/s under any circumstance. (Note also that 100 GB is below st1's 125 GB minimum.) (ii) **The workload is random, not sequential** — HDD heads must seek, and st1's advertised figures assume large sequential I/O; random small reads collapse the achievable throughput regardless of size. A third contributor is an undersized instance whose **EBS bandwidth** caps the volume before the volume caps itself.

**A29.** Multi-Attach lets a single volume be attached to multiple EC2 instances concurrently, each with full read/write. Supported on **io1 and io2** (Nitro instances), up to 16 instances. **All instances must be in the same Availability Zone as the volume** — Multi-Attach does not cross AZs. Critical requirement: the filesystem must be **cluster-aware** (e.g. GFS2, OCFS2) or the application must coordinate access itself.
ext4 corrupts because it is a single-writer filesystem: each instance caches metadata (inode tables, block bitmaps, the journal) in its own kernel memory and writes back assuming exclusive ownership. Two kernels independently allocating from the same free-block bitmap will hand the same blocks to different files, and each will overwrite the other's journal, producing mutual, unrecoverable corruption. There is no locking protocol between them.

**A30.**

| Dimension | EBS | EFS |
|---|---|---|
| Attachment | One instance at a time (Multi-Attach is a narrow exception) | Thousands of clients concurrently |
| AZ scope | Single AZ | Regional; mount targets in every AZ |
| Pricing | Pay for **provisioned** capacity, whether used or not | Pay for **stored** data; capacity is elastic |
| Protocol | Block device over the EBS transport | NFSv4.1 file protocol |
| Latency | Sub-millisecond (SSD types); consistent | Higher (network file protocol); typically low single-digit ms |

Over-engineered case: the **root volume, or a single-instance database's data volume**. Only one instance ever touches it, so EFS adds NFS latency and a higher per-GB price to buy sharing that nothing uses — and a database on NFS also risks locking semantics problems. gp3 is both cheaper and faster there.

**A31.** Incremental means the first snapshot copies all in-use blocks, and each subsequent snapshot stores **only the blocks changed since the previous snapshot**, referencing unchanged blocks in earlier snapshots. Cost therefore scales with the rate of change, not with volume size — ten daily snapshots of a mostly static 1 TB volume cost far less than 10 TB.
Restore time is **not** proportionally shorter: creating a volume from any snapshot reconstructs the full volume, and blocks are lazily loaded from S3 on first access, so early I/O is slow until the volume is initialised (or Fast Snapshot Restore is enabled).
**Deleting an older snapshot does not break newer ones.** AWS only removes blocks no newer snapshot references; any block still needed is retained and re-parented. Every snapshot remains independently restorable.

## Section E

**A32.**

| | ECS on EC2 | ECS on Fargate |
|---|---|---|
| OS patching | **You** patch the container instances and the ECS agent | **AWS** — no host is exposed |
| Capacity scaling | You scale an Auto Scaling Group (optionally via a capacity provider); tasks fail to place if capacity is short | AWS provisions compute per task automatically |
| Billing unit | Per **EC2 instance-hour**, regardless of how full it is | Per **task**, on requested vCPU and memory, per second (1-minute minimum) |
| Network modes | `awsvpc`, `bridge`, `host`, `none` | `awsvpc` only |

**A33.**
- **Twelve steady, always-on, CPU-bound services → ECS on EC2.** Continuous utilisation is precisely where the per-instance model wins: you can bin-pack many tasks onto right-sized instances, and use Reserved Instances, Savings Plans or Spot to cut the rate substantially. Fargate's per-task premium is paid every second of a workload that never idles.
- **Twenty-eight bursty, mostly-idle services → Fargate.** Per-second billing means an idle service costs nothing; there is no half-empty instance to pay for, no ASG to tune, and no capacity shortfall when 28 services spike at once. The operational saving on 28 low-value services is worth more than the unit-price premium.
- **Hybrid mechanism: ECS capacity providers.** A single cluster can have both an ASG capacity provider and the `FARGATE`/`FARGATE_SPOT` providers, with a capacity provider strategy per service (and base/weight settings) routing each service to the right compute. This is also the standard way to keep a steady base on EC2 and overflow onto Fargate.

**A34.** A **task definition** is the immutable, versioned blueprint — image, CPU/memory, ports, environment, IAM roles, log configuration. A **task** is one running instantiation of a task definition; when it stops, it is gone. A **service** is a long-running controller that maintains a **desired count** of tasks from a given task definition, replaces tasks that fail health checks, registers them with a load balancer target group, and orchestrates rolling deployments.
The **service** defines desired count and performs replacement. A bare task does neither — it runs once and exits.

**A35.**
- **Task execution role** — assumed by the **ECS agent / Fargate infrastructure**, not your code. It pulls the container image from ECR, retrieves Secrets Manager or SSM parameters injected as environment variables, and writes to CloudWatch Logs.
- **Task role** — assumed by the **application inside the container**, giving it permission to call AWS APIs.
An **ECR image-pull failure** is the **task execution role**: it is missing `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:GetDownloadUrlForLayer` and `ecr:BatchGetImage` (the `AmazonECSTaskExecutionRolePolicy` managed policy covers these) — or the role is not specified at all.
A running container getting `AccessDenied` on `dynamodb:PutItem` is the **task role**: it lacks that action on the table's ARN. Adding DynamoDB permissions to the execution role is a common and ineffective fix, since the application never assumes that role.

**A36.** In `awsvpc` mode each task receives its **own elastic network interface with its own private IP** in the VPC subnet, exactly as if it were an EC2 instance. It is mandatory on Fargate because there is no shared host whose network stack tasks could borrow.
What it changes versus `bridge`: security groups are applied **per task** rather than per host. Under `bridge` mode, many tasks share the instance's ENI and therefore share one security group, so a rule opened for one container is open for every container on that host, and container ports are mapped to host ports (often dynamically), making rules coarse. Under `awsvpc`, each task gets its own security group and its own port space — port conflicts vanish and least-privilege network rules become expressible per service. VPC Flow Logs also become per-task, which improves auditability.

**A37.** Every Fargate task gets **ephemeral storage** — an encrypted, task-scoped volume, **20 GB by default** on the current platform version, destroyed when the task stops. It can be increased by setting `ephemeralStorage.sizeInGiB` in the task definition, up to **200 GiB** (Linux, platform version 1.4.0 or later); it cannot be resized on a running task.
Architectural alternative: **stream the work through S3** — download the source segment, transcode in a bounded buffer, upload each output part immediately, and delete it locally. Or mount an **EFS access point** into the task for shared, elastic, persistent storage that survives task replacement. Either removes the hard dependence on task-local disk and, in the S3 case, lets the job scale horizontally across many small tasks instead of demanding one large one.

## Section F

**A38.**
a) Security groups are **stateful**: allowing the outbound request implicitly allows the return traffic. NACLs are **stateless** — every packet is evaluated independently against the rules for its direction, so the *reply* from Redis is a separate outbound packet from `10.0.20.0/24` that no rule permits, and the *reply arriving back* at the app subnet is a separate inbound packet there. With only the forward-direction rules written, the request reaches Redis and the response is silently dropped, which the client experiences as a hang and eventual timeout rather than a connection refusal.
b) An **ephemeral port** is the temporary, high-numbered source port the client's operating system allocates for the client side of an outbound TCP connection; the server sends its reply to that port. The range depends on the OS (Linux typically 32768–60999, Windows 49152–65535, ELB/NLB 1024–65535), so for NACLs AWS recommends allowing **1024–65535**.
c)

| # | NACL | Direction | Protocol | Port range | Source / Destination | Action |
|---|---|---|---|---|---|---|
| 1 | App subnet NACL (`10.0.10.0/24`) | **Outbound** | TCP | **6379** | Destination `10.0.20.0/24` | ALLOW |
| 2 | Cache subnet NACL (`10.0.20.0/24`) | **Inbound** | TCP | **6379** | Source `10.0.10.0/24` | ALLOW |
| 3 | Cache subnet NACL (`10.0.20.0/24`) | **Outbound** | TCP | **1024–65535** | Destination `10.0.10.0/24` | ALLOW |
| 4 | App subnet NACL (`10.0.10.0/24`) | **Inbound** | TCP | **1024–65535** | Source `10.0.20.0/24` | ALLOW |

Rules 1 and 2 carry the request; rules 3 and 4 carry the response to the client's ephemeral port. Rule numbers should be low (e.g. 100, 110) and below any broad deny.

**A39.**

| Point | Security Group | NACL |
|---|---|---|
| Statefulness | Stateful — return traffic automatic | Stateless — both directions must be written |
| Scope | Instance / ENI | Subnet (applies to everything in it) |
| Rule types | **Allow only** | Allow **and** Deny |
| Evaluation | All rules evaluated; any match allows | Numbered, ascending; **first match wins**, evaluation stops |
| Default behaviour | A newly created SG denies all inbound, allows all outbound | The **default** NACL allows all traffic both ways; a **custom** NACL denies all traffic both ways until rules are added |

To block a single abusive IP from an entire subnet, use the **NACL** — it is the only one of the two that supports an explicit `Deny`, and it applies at the subnet boundary so a single rule covers every instance. A security group cannot do it: it has no deny rule, so "everyone except this IP" would have to be expressed as an exhaustive list of allowed CIDRs around the excluded address, which is unmaintainable and would still have to be repeated on every instance's SG.

**A40.**
- **`sg-bastion`** (attached to the bastion host in the public subnet)
  - Inbound: TCP 22 from `202.144.128.0/19` (campus network only).
  - Outbound: TCP 22 to `sg-private` (or to `10.0.30.0/24`).
- **`sg-private`** (attached to the private instances)
  - Inbound: TCP 22 with **source = `sg-bastion`** (a security group reference, not a CIDR).
  - Inbound: the application's own port from the app/ALB security group, as required.
  - No inbound from `0.0.0.0/0` at all; the subnet has no route to an internet gateway.

Referencing a security group as a source improves the design in several ways: the rule stays correct when the bastion is replaced, re-IP'd, or scaled to two instances behind an ASG, because it names an identity rather than an address; it cannot accidentally admit an unrelated host that later occupies the same IP; it survives subnet re-addressing; and it documents intent — "SSH comes from the bastion" is readable in the console in a way that `10.0.1.47/32` is not. The stronger modern alternative is to remove the bastion entirely and use **AWS Systems Manager Session Manager**, which needs no inbound rule at all.

**A41.** Security groups are **allow-lists evaluated as a union**: every rule in every attached group is checked, and traffic is permitted if *any* rule matches. A deny rule cannot be expressed in that model, because there is no ordering and no first-match semantics for it to take precedence in — a deny would be ambiguous against a simultaneous allow, and the union evaluation is what makes SG rules order-independent and composable.
To permit all of `10.0.5.0/24` except `10.0.5.99`, you must use a **NACL** on the subnet: a low-numbered `DENY` rule for `10.0.5.99/32` followed by a higher-numbered `ALLOW` for `10.0.5.0/24`. Because NACL evaluation is first-match in ascending rule order, the deny is reached first for that one host and the allow serves everyone else.

**A42.** Components: an **Internet Gateway** attached to the VPC; a **public subnet** with a route `0.0.0.0/0 → igw-xxxx`; a **NAT Gateway** launched **in that public subnet** with an Elastic IP; the **private subnet's** route table with `0.0.0.0/0 → nat-xxxx`. Instances keep no public IP, and the private subnet has no IGW route, so no unsolicited inbound connection can reach them; the NAT Gateway performs source translation for outbound flows only and is itself stateful, so patch downloads return normally.
Placing the NAT Gateway in the private subnet is a configuration error because the NAT Gateway is itself an internet-facing device: it needs a route to the **internet gateway** to reach the internet, and only a public subnet has one. A NAT Gateway in a private subnet has no path out, so it can translate nothing — and if the private subnet's default route also pointed at it, traffic would loop back into the same subnet. It belongs in the **public subnet**, with one per Availability Zone for fault tolerance (a single NAT Gateway is an AZ-level single point of failure and incurs cross-AZ data charges).

**A43.** As written, rule **90** is evaluated first because NACL rules are processed in ascending numerical order. It matches traffic from `203.0.113.7`, so that traffic is **denied** and evaluation stops — rule 100 is never reached for this source. All other sources fall through to rule 100 and are allowed.
With the numbers swapped (`ALLOW` at 90, `DENY` at 100), traffic from `203.0.113.7` now matches the allow at rule 90 first and is **permitted**; the deny at 100 is unreachable for it and has no effect. This is the standard pitfall: in a NACL, a deny must be numbered **lower** than the broad allow it is meant to carve an exception out of.

**A44.** Every NACL ends with an unremovable `*` rule that denies all traffic not matched by a numbered rule — so a packet reaching the end of the list without a match is dropped. A security group's implicit deny works differently in mechanism though similarly in effect: an SG has no rule list terminator, but because it is a pure allow-list, traffic matching no rule is simply not permitted. The practical difference is that the NACL deny applies **per direction and per packet** (so return traffic can be dropped by it even when the request was allowed), while the SG's implicit deny never blocks return traffic, because state tracking permits it before rules are consulted.
The **default NACL** behaves permissively because AWS pre-populates it with rule 100 `ALLOW all traffic` inbound and rule 100 `ALLOW all traffic` outbound. Those rules match every packet before the `*` rule is reached, so the implicit deny is never the deciding rule. A **custom** NACL, by contrast, is created with no numbered rules at all, so the `*` deny is reached immediately and everything is blocked until you add rules — which is why moving a subnet to a custom NACL commonly breaks connectivity instantly.

## Section G

**A45.** For `10.0.4.0/24` AWS reserves:
- `10.0.4.0` — the **network address**.
- `10.0.4.1` — the **VPC router** (default gateway for the subnet).
- `10.0.4.2` — the **Amazon-provided DNS** (the base of the VPC CIDR +2; the Route 53 Resolver).
- `10.0.4.3` — **reserved by AWS for future use**.
- `10.0.4.255` — the **broadcast address**. AWS does not support broadcast, but the address is still reserved.

A /24 has 256 addresses; 256 − 5 = **251** assignable to EC2 instances.

**A46.** In every case, usable = 2^(32−prefix) − 5.

| Requirement | Answer | Total | Usable | Reasoning |
|---|---|---|---|---|
| a) 5 instances | **/28** | 16 | **11** | /29 gives 8 − 5 = 3, too few. /28 is also AWS's smallest permitted subnet. |
| b) 28 instances | **/26** | 64 | **59** | /27 gives 32 − 5 = 27 — one short. Step up to /26. |
| c) 60 instances | **/25** | 128 | **123** | /26 gives 64 − 5 = 59 — one short. Step up to /25. |
| d) 300 instances | **/23** | 512 | **507** | /24 gives 251, too few; /23 gives 507. |
| e) 1500 instances | **/21** | 2048 | **2043** | /22 gives 1024 − 5 = 1019, too few; /21 gives 2043. |

Note (b) and (c) deliberately sit just above a power-of-two boundary — this is exactly where the five reserved addresses change the answer, and where marks are most often lost.

**A47.** One workable design from `10.20.0.0/16`, using /24 subnets (251 usable each) for web and app tiers and /26 (59 usable) for the database tier, which needs few addresses:

| Tier | AZ | CIDR | Total | Usable |
|---|---|---|---|---|
| Public web | ap-south-1a | `10.20.0.0/24` | 256 | 251 |
| Public web | ap-south-1b | `10.20.1.0/24` | 256 | 251 |
| Private app | ap-south-1a | `10.20.10.0/24` | 256 | 251 |
| Private app | ap-south-1b | `10.20.11.0/24` | 256 | 251 |
| Private DB | ap-south-1a | `10.20.20.0/26` | 64 | 59 |
| Private DB | ap-south-1b | `10.20.20.64/26` | 64 | 59 |

**No overlap:** the public block occupies `10.20.0.0`–`10.20.1.255`, the app block `10.20.10.0`–`10.20.11.255`, and the database block `10.20.20.0`–`10.20.20.127`. The three ranges are disjoint, and the two /26s are adjacent but non-overlapping (`.0–.63` and `.64–.127`).
**Growth:** leaving gaps at `10.20.2.0`–`10.20.9.255`, `10.20.12.0`–`10.20.19.255` and everything from `10.20.20.128` upward means a third AZ, or additional tiers, can be added on the same numbering scheme without renumbering. Of the 65,536 addresses in the /16, 1,152 are allocated — roughly **98% of the /16 remains unallocated**, which is deliberate: VPC CIDRs cannot be shrunk, and subnets cannot be resized after creation, so generous headroom costs nothing.

**A48.** AWS permits subnet prefixes from **/16 (largest, 65,536 addresses)** down to **/28 (smallest, 16 addresses)**. Nothing smaller than /28 is allowed because AWS reserves **five** addresses in every subnet: a /29 would have 8 − 5 = 3 usable addresses and a /30 would have none at all, so the subnet would be functionally useless while still consuming address space and route-table complexity. /28's 11 usable addresses is the smallest allocation that is still meaningfully usable.

**A49.** Two VPCs with identical (or overlapping) CIDRs **cannot be peered** — VPC peering requires non-overlapping CIDR blocks, because the route tables would have no unambiguous way to decide whether `10.0.3.14` means the local VPC or the peer. AWS rejects the peering request outright. The same restriction applies to Transit Gateway attachments and to most VPN/Direct Connect designs, and a VPC CIDR cannot be changed after creation — only additional secondary CIDRs can be added, which does not remove the conflict.
Two ways to avoid it:
1. **Central IP address plan.** Allocate every VPC a distinct, non-overlapping slice from one organisation-wide supernet (e.g. `10.0.0.0/8` carved as `10.0.0.0/16` production, `10.1.0.0/16` staging, `10.2.0.0/16` development, one /16 per environment-region pair), documented before any VPC is created. **AWS VPC IP Address Manager (IPAM)** automates this, allocating from managed pools and refusing overlapping requests.
2. **Avoid the requirement for direct routing.** Where two overlapping VPCs must still communicate, expose the service through **PrivateLink (VPC endpoint services)** or an internal NLB, which presents an endpoint in the consumer's own address space and never routes between the two CIDRs — or, at the edge, use NAT to translate the overlapping range. PrivateLink is the cleaner answer and is also the standard way to share a service across accounts with different address plans.

**A50.** `172.16.132.77/26` — a /26 mask is `255.255.255.192`, so blocks are 64 addresses wide: `.0`, `.64`, `.128`, `.192`. The host `.77` falls in the `.64`–`.127` block.
a)
- **Network address:** `172.16.132.64`
- **Broadcast address:** `172.16.132.127`
- **Valid host range (standard IPv4):** `172.16.132.65` – `172.16.132.126` → **62 hosts**

b) In an AWS subnet three further addresses are reserved beyond the network and broadcast addresses:
- `172.16.132.65` — the **VPC router**
- `172.16.132.66` — the **Amazon-provided DNS resolver**
- `172.16.132.67` — **reserved for future use**

So the AWS-assignable range is `172.16.132.68` – `172.16.132.126`.

c) 64 total − 5 reserved = **59 EC2 instances**.

---

*End of solutions. 50 answers.*
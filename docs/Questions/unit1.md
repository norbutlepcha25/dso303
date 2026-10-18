# Unit 1: Practice Questions

## 1.1 AWS Cloud Overview

1. Define Region, Availability Zone, and Edge Location, and state the primary purpose of each layer.

    ??? success "Check your answer"

        A good answer covers:

        - **Region:** a separate geographic area containing multiple isolated AZs; it is the unit of data residency, service hosting and large-scale fault isolation.
        - **Availability Zone:** one or more discrete data centres in a Region with independent power, cooling and networking; it is the building block of high availability within a Region.
        - **Edge Location:** a small point of presence close to users that hosts CloudFront caches, Route 53, Shield, WAF and Global Accelerator entry points; it cannot run EC2 or RDS.
        - **Purpose in one line:** Regions answer law and geography, AZs answer failure, Edge Locations answer latency.

2. Why does AWS require (in modern Regions) a minimum of three AZs rather than one large data centre?

    ??? success "Check your answer"

        A good answer covers:

        - **Failure correlation:** a single data centre is one fault domain for power, cooling, fire and network failures, however large it is.
        - **Majority after a failure:** with three AZs, losing one leaves two thirds of capacity and a majority for quorum-based systems such as Aurora storage or etcd.
        - **Synchronous replication is still possible:** AZs are close enough (round trip around 1 to 2 ms) for synchronous replication yet far enough apart to avoid sharing most local disasters.
        - **Two is the minimum, three is the preference:** with only two AZs, a single AZ loss halves capacity and removes any tie-breaker.

3. What is the difference between the AZ _name_ `eu-west-1a` and the AZ _ID_ `euw1-az1`, and why does the difference exist?

    ??? success "Check your answer"

        A good answer covers:

        - **AZ name:** the account-specific label such as `eu-west-1a`; the mapping from name to physical zone is shuffled per account.
        - **AZ ID:** the physical zone identifier such as `euw1-az1`, which is the same in every account.
        - **Why the shuffle exists:** most customers pick the "a" zone, so randomising the mapping spreads load evenly across physical zones.
        - **Practical consequence:** use AZ IDs when coordinating resources across accounts, for example to keep shared services in the same physical zone and avoid cross-AZ charges.

4. List four factors an architect evaluates when selecting a Region, in a sensible priority order.

    ??? success "Check your answer"

        A good answer covers:

        - **Compliance and data residency first:** a legal constraint overrides every other criterion.
        - **Latency to users second:** measure, do not assume, the latency from the user population.
        - **Service and instance-type availability third:** confirm every service and feature the design needs exists in that Region.
        - **Cost fourth:** identical resources differ in price between Regions; sustainability and proximity to partners or on-premises sites may also count.

5. When a CloudFront edge receives a request for an object it does not hold, describe the sequence of lookups before the origin is contacted.

    ??? success "Check your answer"

        A good answer covers:

        - **Edge Location first:** the request reaches the nearest edge (chosen via DNS); a cache hit is served immediately.
        - **Regional Edge Cache next:** on an edge miss, CloudFront checks the larger mid-tier Regional Edge Cache.
        - **Origin Shield, if enabled:** a further centralised caching layer can be checked before the origin.
        - **Origin last:** only on a miss at every layer does CloudFront fetch from the origin over the AWS backbone and populate the caches on the way back.

6. Your application runs six EC2 instances in `ap-southeast-1a` behind an ALB whose subnets span three AZs. Identify the availability flaw and describe two concrete fixes, including the Auto Scaling configuration involved.

    ??? success "Check your answer"

        A good answer covers:

        - **Flaw:** all instances are in one AZ, so the multi-AZ ALB has no healthy targets if `ap-southeast-1a` fails; the load balancer's spread is irrelevant when the compute is zonal.
        - **Fix 1:** place instances in an Auto Scaling group whose subnet list covers all three AZs (for example two per AZ), with AZ rebalancing so the group stays evenly spread.
        - **Fix 2:** set the ASG health check type to `ELB` with a sensible grace period, and attach it to the ALB target group so failed instances are replaced automatically.
        - **Static stability:** size the group so the two surviving AZs can carry peak load without launching anything (for example over-provision to 150 percent of need across three AZs).
        - **Cross-zone load balancing:** keep it enabled on the ALB so traffic is spread evenly across targets.

7. A distribution forwards all cookies and all query strings to a dynamic origin. Explain the effect on cache hit ratio, origin load, and cost, and propose a corrected cache-policy design for a site with `/static/*` and `/api/*` paths.

    ??? success "Check your answer"

        A good answer covers:

        - **Cache hit ratio:** every distinct cookie and query string becomes part of the cache key, so the cache is fragmented and almost every request misses.
        - **Origin load:** the origin serves nearly every request, so CloudFront adds a hop without offloading anything.
        - **Cost:** origin compute and data-transfer costs stay high, and the latency benefit of edge caching is lost.
        - **Corrected design:** a `/static/*` behaviour with a cache policy that forwards no cookies or query strings (or only a version parameter), long TTLs and versioned file names.
        - **API behaviour:** a `/api/*` behaviour using the managed caching-disabled policy plus an origin request policy that forwards only the headers, cookies and query strings the API actually needs.

8. Compare RDS Multi-AZ, RDS read replicas, and cross-Region read replicas along three axes: replication mode (sync/async), purpose (HA/scale/DR), and effect on RPO.

    ??? success "Check your answer"

        A good answer covers:

        - **RDS Multi-AZ:** synchronous replication to a standby in another AZ; purpose is high availability with automatic failover; RPO effectively zero for an AZ failure.
        - **Read replicas (same Region):** asynchronous; purpose is read scaling; a promoted replica may lose the replication lag, so RPO equals that lag.
        - **Cross-Region read replicas:** asynchronous across Regions; purpose is disaster recovery and local reads in another geography; RPO equals cross-Region lag, typically seconds.
        - **Key distinction:** the Multi-AZ standby in an instance deployment is not readable, while replicas are readable but never zero-RPO.

9. Explain how you would restrict an AWS Organization to two approved Regions, and why `iam:*`, `cloudfront:*`, and `route53:*` typically must be exempted from that restriction.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** a Service Control Policy attached to the root or relevant OUs that denies actions when `aws:RequestedRegion` is not one of the two approved Regions.
        - **Structure:** use a `Deny` statement with `NotAction` (or exemptions) so the restriction applies to everything except listed global services.
        - **Why exempt global services:** IAM, CloudFront and Route 53 are global services whose control-plane requests are served through `us-east-1`, so a Region restriction would block them entirely.
        - **Other exemptions to consider:** STS, Organizations, Support and billing-related APIs behave similarly.
        - **Verification:** test the SCP in a sandbox OU first, because an over-broad deny can lock administrators out.

10. Your team claims "we are multi-AZ, therefore we survive AZ failure." Name three hidden single-AZ dependencies that could falsify this claim (consider NAT, data, and control-plane assumptions).

    ??? success "Check your answer"

        A good answer covers:

        - **NAT gateway:** a single NAT gateway in one AZ means private subnets in the other AZs lose outbound connectivity when that AZ fails; deploy one NAT gateway per AZ.
        - **Data tier:** a single-AZ database, cache, EFS One Zone file system or self-managed database on one EC2 instance is a zonal single point of failure.
        - **Control-plane assumptions:** recovery that relies on launching new instances, changing DNS or scaling during the event may fail when control planes are impaired; pre-provision capacity instead.
        - **Other hidden dependencies:** a single-AZ Interface endpoint, an uneven subnet list, or capacity that only fits if every AZ is healthy.
        - **Proof:** only a failure drill (for example removing an AZ from service) validates the claim.

11. Design a multi-Region architecture for a payments API with RPO ≤ 1 second and RTO ≤ 5 minutes. Specify the data technology, the traffic-steering mechanism and its health signal, and how you avoid control-plane dependence during failover. State the consistency trade-off you accepted.

    ??? success "Check your answer"

        A good answer covers:

        - **Data technology:** Aurora Global Database (typical cross-Region lag under a second) or DynamoDB Global Tables; for payments, a single writer Region is safer than multi-writer last-writer-wins.
        - **Traffic steering:** Route 53 failover or Global Accelerator with health checks on a deep application endpoint, or Route 53 Application Recovery Controller routing controls as the switch.
        - **Avoiding control-plane dependence:** pre-provision the standby Region's compute at full capacity, pre-create DNS records and health checks, and fail over by toggling data-plane routing controls rather than creating resources.
        - **RTO:** detection plus switch plus promotion must fit within five minutes, which rules out restore-from-backup approaches.
        - **Consistency trade-off:** asynchronous cross-Region replication means an RPO of up to about a second; the design accepts that a small number of in-flight transactions may need reconciliation, typically by idempotency keys and a ledger reconciliation process.

12. Explain _static stability_ and redesign the following to satisfy it: "On AZ failure, a Lambda triggered by a CloudWatch alarm updates the Auto Scaling group to launch replacements and calls the Route 53 API to change weights."

    ??? success "Check your answer"

        A good answer covers:

        - **Static stability:** a system remains functional during a failure without needing to make changes, launch resources or call control planes.
        - **Problem with the original:** it depends on CloudWatch alarms, Lambda, the Auto Scaling control plane and the Route 53 control-plane API, all of which may be impaired during the event.
        - **Redesign capacity:** run enough capacity in every AZ that losing one leaves sufficient capacity (for example 50 percent over-provisioning across three AZs).
        - **Redesign traffic shifting:** rely on load balancer health checks (a data-plane function) to stop sending traffic to the failed AZ, and use Route 53 health checks or ARC routing controls rather than API calls that change records.
        - **Result:** failure handling becomes automatic data-plane behaviour, with scaling as an optional improvement rather than a requirement.

13. A microservices platform on EKS shows large inter-AZ data-transfer charges and elevated p99 latency. Discuss the tension between AZ-spread for resilience and AZ-affinity for cost/latency, and describe a topology-aware routing approach that balances them.

    ??? success "Check your answer"

        A good answer covers:

        - **The tension:** spreading replicas across AZs gives resilience but each cross-AZ call adds latency and data-transfer charges in both directions.
        - **Topology-aware routing:** enable Kubernetes topology-aware routing (traffic distribution preferring the same zone) so Services route to endpoints in the caller's AZ when enough exist there.
        - **Keep the spread:** use topology spread constraints so each AZ has enough replicas of every service to serve its local callers.
        - **Fallback:** routing must fall back to other AZs when local endpoints are unhealthy, so resilience is preserved.
        - **Measure:** use VPC Flow Logs or cost allocation to confirm inter-AZ bytes fall and watch p99 latency.

14. Your global user base is 60% in regions where you have no AWS Region within 150 ms. Compare three remedies  additional Regions (active-active), CloudFront with an aggressive caching strategy, and Global Accelerator  for a workload that is 80% cacheable reads and 20% authenticated writes. Recommend and justify a combination.

    ??? success "Check your answer"

        A good answer covers:

        - **Additional active-active Regions:** best latency for both reads and writes, but highest cost and the hardest data-consistency problem for authenticated writes.
        - **CloudFront with aggressive caching:** serves the 80 percent cacheable reads from the edge cheaply and also accelerates uncached requests over the backbone.
        - **Global Accelerator:** improves TCP connection latency and gives fast failover for the write path, but does no caching.
        - **Recommended combination:** CloudFront for all HTTP traffic (caching reads, proxying writes to the origin), plus a second Region only if write latency remains unacceptable after measurement.
        - **Justification:** this addresses the majority of traffic at low cost and defers the multi-Region data problem until it is proven necessary.

15. During a partial edge-network event, some users receive errors while all Regional metrics are green and synthetic canaries in-Region pass. Construct the observability strategy (metrics locations, log types, external vantage points, AWS Health integration) that would have detected this class of failure, and the automated mitigation you would attach to it.

    ??? success "Check your answer"

        A good answer covers:

        - **Metric locations:** CloudFront metrics live in `us-east-1`, so dashboards and alarms on 4xx/5xx error rates and origin latency must be built there, not only in the workload Region.
        - **Log types:** CloudFront standard or real-time logs with edge location codes, analysed per PoP, plus Route 53 query logs.
        - **External vantage points:** synthetic canaries from multiple geographies and Regions, and real user monitoring (for example CloudWatch RUM or Internet Monitor) that measures what users experience.
        - **AWS Health integration:** EventBridge rules on AWS Health events for CloudFront and edge services, routed to the on-call channel.
        - **Automated mitigation:** an alarm on per-location error rate that triggers a runbook, for example failing over to a secondary origin group or shifting DNS to an alternative path.

---

## 1.3 AWS Compute Services

1. Define an Amazon Machine Image, an instance type, and an instance profile, and explain the role each plays when an EC2 instance launches.

    ??? success "Check your answer"

        A good answer covers:

        - **AMI:** the template containing the root volume snapshot (operating system and software) and launch permissions; it determines what the instance boots.
        - **Instance type:** the hardware profile (vCPU, memory, network and EBS bandwidth, accelerators); it determines capacity and price.
        - **Instance profile:** the container that delivers an IAM role to an instance; the instance obtains temporary credentials from IMDS.
        - **At launch:** the AMI provides the software, the type provides the hardware, and the profile provides the permissions, with no long-lived keys on the instance.

2. Explain the difference between object-level responsibility in the AWS shared responsibility model for EC2 versus for AWS Lambda. Name three things that become the customer's responsibility with EC2 but not with Lambda.

    ??? success "Check your answer"

        A good answer covers:

        - **Shared responsibility shifts:** with EC2 the customer manages from the guest operating system upwards; with Lambda AWS manages the operating system, runtime and scaling.
        - **Customer-only on EC2 (1):** patching and hardening the guest operating system.
        - **Customer-only on EC2 (2):** runtime and language upgrades, agents and host-level configuration.
        - **Customer-only on EC2 (3):** capacity management, scaling and multi-AZ placement of instances.
        - **Still the customer's in both:** application code, IAM permissions, data protection and configuration.

3. What is a container image, and why does immutability of that image matter for reproducible deployments? Contrast this with configuring a server after launch.

    ??? success "Check your answer"

        A good answer covers:

        - **Container image:** an immutable, layered package of an application with its dependencies and runtime, identified by a digest.
        - **Why immutability matters:** the same image tested in staging is byte-for-byte the image running in production, so deployments are reproducible and rollbacks are simply redeploying the previous digest.
        - **Contrast with post-launch configuration:** configuring servers after launch causes drift, different results on each run and slow, fragile provisioning.
        - **Practice:** change the image, rebuild and redeploy instead of modifying a running container or server.

4. List the four purchasing options for EC2 capacity and give one workload that suits each.

    ??? success "Check your answer"

        A good answer covers:

        - **On-Demand:** per-second billing with no commitment; suits unpredictable or short-lived workloads such as development environments.
        - **Savings Plans or Reserved Instances:** one- or three-year commitment for a discount; suits steady baseline production load.
        - **Spot Instances:** spare capacity at large discounts, reclaimable with two minutes' notice; suits interruption-tolerant batch jobs or CI runners.
        - **Dedicated Hosts or Instances:** hardware isolation; suits regulatory isolation or per-socket licensing.

5. An AWS Lambda function is configured with 128 MB of memory and takes 4 seconds to run. The team increases it to 512 MB and it now takes 1 second. Explain why the total cost may be unchanged or lower, and why the user-perceived latency improves.

    ??? success "Check your answer"

        A good answer covers:

        - **Cost arithmetic:** 128 MB for 4 s is 0.125 GB x 4 s = 0.5 GB-seconds; 512 MB for 1 s is 0.5 GB x 1 s = 0.5 GB-seconds, so the duration charge is identical.
        - **Request charge:** unchanged, because the number of invocations is the same.
        - **Why it got faster:** Lambda allocates CPU in proportion to memory, so a CPU-bound function runs faster with more memory.
        - **Latency:** user-perceived latency drops from 4 s to 1 s, and lower duration also reduces concurrency needed.
        - **Practice:** use Lambda Power Tuning to find the cheapest or fastest memory setting rather than guessing.

6. A service currently runs on three EC2 instances behind an Application Load Balancer with a fixed desired count. Describe how you would convert it to an elastic architecture, naming the specific components, the health-check configuration, and the scaling policy you would select, and justify each choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Components:** a launch template, an Auto Scaling group spanning at least two (preferably three) AZs, and the existing ALB target group attached to the ASG.
        - **Health checks:** ASG health check type `ELB` with a grace period longer than boot time, and a target group health check on a lightweight application endpoint.
        - **Scaling policy:** target tracking (for example average CPU around 50 percent or ALB request count per target), because it behaves like a thermostat and needs little tuning.
        - **Supporting settings:** minimum capacity that survives an AZ loss, instance warm-up, and scheduled or predictive scaling for known peaks.
        - **Precondition:** the application must be stateless, with sessions moved to an external store.

7. Compare ECS on Fargate with ECS on EC2 across cost, security isolation, operational overhead, task density, and support for GPU and DaemonSet-style workloads. State the conditions under which each becomes the correct choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Cost:** Fargate charges a higher per-vCPU rate but only for what tasks request; EC2 is cheaper when instances are densely packed and covered by Savings Plans or Spot.
        - **Security isolation:** Fargate runs each task in its own isolated environment with no host access; EC2 tasks share a host kernel with other tasks.
        - **Operational overhead:** Fargate removes AMI patching, instance sizing and capacity management; EC2 requires both task scaling and instance scaling.
        - **Density, GPU and daemons:** EC2 supports bin-packing, GPUs, privileged containers and daemon-style agents; Fargate does not.
        - **When each is correct:** Fargate for spiky or low-utilisation services and small teams; EC2 for high, steady utilisation, GPUs or host-level agents.

8. Explain the full sequence of events, including control-plane and data-plane actions, that occurs between an `UpdateService` API call with a new task definition and the point at which all traffic reaches the new version under a rolling deployment with `minimumHealthyPercent` 100 and `maximumPercent` 200.

    ??? success "Check your answer"

        A good answer covers:

        - **Control plane accepts the change:** `UpdateService` records a new deployment with the new task definition revision as the desired state.
        - **Launch new tasks:** with `maximumPercent` 200 the scheduler may start up to a full extra set of new tasks while all old tasks keep running (`minimumHealthyPercent` 100 forbids stopping any first).
        - **Become healthy:** new tasks pull the image, start, register with the target group and must pass container and load balancer health checks.
        - **Drain old tasks:** once new tasks are healthy, old tasks are deregistered, connections drain for the deregistration delay, and the tasks are stopped.
        - **Complete or roll back:** the deployment completes when only new tasks remain; the deployment circuit breaker can roll back automatically if new tasks fail to stabilise.

9. An EKS cluster's pods must call Amazon S3. Describe the IRSA mechanism end to end  the OIDC provider, the IAM trust policy, the ServiceAccount annotation, and the token projection  and explain why this is superior to attaching permissions to the node instance role.

    ??? success "Check your answer"

        A good answer covers:

        - **OIDC provider:** the EKS cluster's OIDC issuer is registered as an IAM identity provider, so IAM can trust tokens it signs.
        - **Trust policy:** the IAM role trusts that provider for `sts:AssumeRoleWithWebIdentity`, with a condition restricting the `sub` claim to a specific namespace and ServiceAccount.
        - **ServiceAccount annotation:** the ServiceAccount carries `eks.amazonaws.com/role-arn`, and the pod spec uses that ServiceAccount.
        - **Token projection:** the pod identity webhook mounts a projected, short-lived service account token and sets environment variables so the SDK exchanges it for temporary role credentials.
        - **Why better than the node role:** permissions are scoped per workload rather than shared by every pod on the node, giving least privilege and clear audit (EKS Pod Identity is a newer, simpler alternative).

10. A team reports that their Lambda function occasionally returns duplicate results to downstream systems. Explain the delivery semantics involved for asynchronous invocation and for an SQS event source, and describe how you would make the function idempotent.

    ??? success "Check your answer"

        A good answer covers:

        - **Asynchronous invocation:** Lambda retries failed asynchronous events (by default twice), and the event queue can occasionally deliver an event more than once.
        - **SQS event source:** delivery is at-least-once; a message is redelivered if the visibility timeout expires or a batch partially fails.
        - **Idempotency key:** derive a unique key from the event (message ID or business identifier).
        - **Implementation:** record the key with a DynamoDB conditional write (`attribute_not_exists`) before or with the side effect, and skip processing if the key already exists; set a TTL to expire old keys.
        - **Supporting measures:** report partial batch failures, set the visibility timeout above the function timeout, and make downstream writes idempotent where possible.

11. Design a compute architecture for a global video-streaming platform's metadata API. It must serve 50,000 requests per second at peak with a p99 latency budget of 100 milliseconds, tolerate the loss of a full Availability Zone with no capacity degradation, deploy 30 times per day with automatic rollback, and minimise cost. Specify the compute model, the scaling strategy, the deployment strategy, the purchasing model, and the failure domains, and justify every choice against a stated alternative you rejected.

    ??? success "Check your answer"

        A good answer covers:

        - **Compute model:** containers on ECS (or EKS) behind an ALB, rejecting Lambda because sustained 50,000 requests per second makes per-request pricing expensive and cold starts threaten p99.
        - **Failure domains:** spread tasks across three AZs and size for N+1 so losing an AZ leaves full capacity (each AZ carries 50 percent of peak), rejecting two AZs which would need 100 percent per AZ.
        - **Scaling:** target tracking on request count per target plus scheduled or predictive scaling for known peaks, with a cache (ElastiCache or CloudFront for cacheable metadata) to protect latency.
        - **Deployment:** blue/green or canary with automatic rollback on alarms (CodeDeploy or the ECS deployment circuit breaker), rejecting all-at-once deployments.
        - **Purchasing:** Compute Savings Plans for the baseline, with Fargate Spot or EC2 Spot only for interruption-tolerant surplus capacity, rejecting pure On-Demand.

12. A monolithic Java application currently runs on eight large EC2 instances at 20 percent average CPU utilisation with sharp quarter-end peaks. Propose a migration path across at least three stages, from rehosting through containerisation to selective serverless decomposition. For each stage, state what it costs, what it improves, what new failure modes it introduces, and what would justify stopping at that stage rather than continuing.

    ??? success "Check your answer"

        A good answer covers:

        - **Stage 1, rehost:** move to EC2 with an ASG across AZs and right-size; low cost and quick, gains elasticity, introduces only cloud networking and IAM failure modes; stop here if the application is stable and near end of life.
        - **Stage 2, replatform onto containers:** containerise the monolith on ECS/Fargate with an ALB; costs build pipelines and image hygiene; improves deployment speed and density; new failure modes include health-check and image-pull issues.
        - **Stage 3, selective decomposition:** extract spiky or event-driven functions (for example quarter-end reports) into Lambda or separate services via a strangler fig; costs most engineering; adds distributed failure modes such as partial failure and eventual consistency.
        - **Cost driver:** the 20 percent utilisation and peaks favour elastic capacity, so each stage should show measured savings.
        - **When to stop:** stop when the next stage's engineering cost exceeds its benefit, or when the team lacks the operational maturity for distributed systems.

13. Critically evaluate the claim that "serverless is always cheaper". Construct a quantitative crossover argument comparing AWS Lambda against ECS on Fargate for a workload of average duration 200 milliseconds and 512 MB of memory. Identify the approximate request rate at which the continuously provisioned container becomes cheaper, state your assumptions explicitly, and then explain why the purely financial crossover is not by itself sufficient grounds for the architectural decision.

    ??? success "Check your answer"

        A good answer covers:

        - **Lambda cost per request (assumed us-east-1 x86 list prices, no free tier):** 0.2 s x 0.5 GB = 0.1 GB-s x 0.0000166667 USD plus 0.0000002 USD per request, about 1.87 USD per million requests.
        - **Lambda cost per sustained request per second:** about 2.6 million requests per month per request per second, so about 4.8 USD per month for each request per second of steady load.
        - **Fargate baseline:** two tasks of 1 vCPU and 2 GB across two AZs cost roughly 70 to 75 USD per month (about 0.049 USD per task-hour) whatever the traffic.
        - **Crossover:** if those two tasks can serve the load, Fargate becomes cheaper above roughly 15 requests per second sustained; Lambda wins below that and for spiky or idle traffic.
        - **Why cost alone is insufficient:** API Gateway versus ALB costs, cold starts and p99 latency, operational effort, team skills, scaling speed and failure modes all change the decision.

14. An organisation runs a stateful, latency-sensitive trading engine that requires sub-millisecond inter-node communication, cannot tolerate noisy neighbours, and must satisfy a regulatory requirement for hardware isolation and detailed audit evidence. Design the compute layer, addressing placement groups, instance tenancy, enhanced networking with Elastic Fabric Adapter or SR-IOV, IMDS hardening, and the observability and audit trail required. Explain which cloud-native principles you are deliberately sacrificing and why that sacrifice is defensible here.

    ??? success "Check your answer"

        A good answer covers:

        - **Placement and tenancy:** a cluster placement group in one AZ for low inter-node latency, on Dedicated Hosts (or dedicated instances) to satisfy hardware isolation and remove noisy neighbours.
        - **Networking:** current-generation instances with enhanced networking (ENA, based on SR-IOV) and Elastic Fabric Adapter where the messaging library supports it.
        - **Instance hardening:** IMDSv2 required with a hop limit of 1, minimal IAM instance profile, Systems Manager Session Manager instead of SSH.
        - **Observability and audit:** CloudTrail organisation trail, AWS Config for configuration history, VPC Flow Logs, detailed CloudWatch metrics and immutable log storage with Object Lock.
        - **Principles sacrificed:** single-AZ placement, fixed capacity and pet-like hosts trade resilience and elasticity for latency; this is defensible because the requirement is regulatory and latency-bound, and is mitigated by a warm standby in a second AZ.

15. Design the control loop for a multi-tenant SaaS platform in which each tenant's workload must be isolated, tenants have wildly different load profiles, and the platform must scale from 10 to 10,000 tenants without a linear increase in operational effort. Compare a pool model (shared compute, logical isolation), a silo model (dedicated compute per tenant), and a hybrid bridge model. Address noisy neighbours, blast radius, cost attribution per tenant, deployment strategy, and the specific AWS compute primitives you would use for each model.

    ??? success "Check your answer"

        A good answer covers:

        - **Pool model:** shared compute with logical isolation by tenant ID; lowest cost and simplest to operate, but highest noisy-neighbour risk and the largest blast radius.
        - **Silo model:** dedicated compute (separate accounts, clusters or services) per tenant; strongest isolation and simple cost attribution, but operational effort grows linearly with tenants.
        - **Bridge model:** pooled compute for standard tenants and silos for premium or regulated tenants, chosen by tier.
        - **Controls:** per-tenant throttling with API Gateway usage plans, Lambda reserved concurrency or Kubernetes namespaces with resource quotas, and tenant-tagged metrics for cost attribution.
        - **Scaling to 10,000 tenants:** automated onboarding through infrastructure as code, one pipeline deploying to all cells or tiers with progressive rollout, and cell-based architecture to bound blast radius.

---

## 1.4 AWS Storage Services

1. Define object storage, block storage, and file storage, and name the primary AWS service that implements each. For each, give one workload that suits it and one that does not.

    ??? success "Check your answer"

        A good answer covers:

        - **Object storage (Amazon S3):** whole immutable objects in a flat keyspace accessed by API; suits media, backups and data lakes; unsuitable for a database's data files.
        - **Block storage (Amazon EBS):** a raw device attached to one instance with low-latency random writes; suits databases and boot volumes; unsuitable for sharing between many servers.
        - **File storage (Amazon EFS):** a shared POSIX file system mounted by many clients; suits shared content directories and lift-and-shift applications; unsuitable for latency-critical database storage or cheap archiving.
        - **Why three:** the access patterns involve mutually exclusive trade-offs.

2. A colleague states that "S3 buckets contain folders". Explain why this is inaccurate, describe what the S3 console is actually displaying, and state one practical consequence of the misunderstanding.

    ??? success "Check your answer"

        A good answer covers:

        - **Flat keyspace:** S3 has buckets and object keys only; there is no directory hierarchy.
        - **What the console shows:** it uses `/` in key names as a delimiter and groups common prefixes to display them as folders.
        - **Consequence 1:** "renaming a folder" means copying and deleting every object under the prefix, which is slow and costly at scale.
        - **Consequence 2:** empty "folders" are just zero-byte placeholder objects, and permissions are applied by prefix pattern, not by folder.

3. What is the difference between durability and availability? Give an example of a situation in which data is fully durable but temporarily unavailable.

    ??? success "Check your answer"

        A good answer covers:

        - **Durability:** the probability that stored data is not lost (S3 is designed for eleven nines).
        - **Availability:** the proportion of time the data can actually be accessed.
        - **Difference:** data can be safely stored yet unreachable, or reachable yet not durable.
        - **Example:** an RDS database during a Multi-AZ failover, or an EBS volume during an AZ impairment, keeps its data intact but cannot be read for a period.

4. An EBS volume was created in `us-east-1a`. Can it be attached to an EC2 instance in `us-east-1b`? Justify your answer with reference to how EBS replication works, and explain how you would move the data to another Availability Zone.

    ??? success "Check your answer"

        A good answer covers:

        - **Answer:** no; an EBS volume can only be attached to instances in the same AZ.
        - **Reason:** EBS replicates synchronously within a single AZ to keep sub-millisecond latency; cross-AZ replication would add latency.
        - **Moving the data:** create a snapshot (stored regionally in S3), then create a new volume from the snapshot in `us-east-1b`.
        - **Performance note:** a volume restored from a snapshot lazily loads blocks, so initialise it or use Fast Snapshot Restore for production.

5. List the four Block Public Access settings conceptually and explain why AWS enables them by default on new buckets. What alternative should be used to serve public web content?

    ??? success "Check your answer"

        A good answer covers:

        - **The four settings:** block new public ACLs, ignore existing public ACLs, block new public bucket policies, and restrict access to buckets that have public policies.
        - **Why on by default:** accidental public buckets have been a leading cause of data leaks, so AWS makes private the safe default.
        - **Account level:** the settings can also be applied account-wide or through Organizations.
        - **Alternative for public content:** keep the bucket private and serve it through CloudFront with Origin Access Control.

6. A bucket holds four hundred terabytes of application logs. Recent logs are queried daily for two weeks, then almost never, but must be retained for seven years for audit. Design a lifecycle configuration, justify each transition point, and identify the risk if the objects were on average only 20 KiB in size.

    ??? success "Check your answer"

        A good answer covers:

        - **Day 0 to 14:** S3 Standard, because logs are queried daily.
        - **Day 14 to about 90:** transition to Standard-IA or Glacier Instant Retrieval, since access is rare but should still be immediate (respect the 30-day minimum before IA transition rules apply).
        - **Day 90 onwards:** transition to Glacier Flexible Retrieval or Deep Archive for audit retention, and expire objects after seven years.
        - **Small-object risk:** objects under 128 KB are not transitioned to IA classes by default and are billed as 128 KB if stored there; Glacier adds per-object metadata overhead and transition requests are charged per object, so millions of 20 KiB objects can make transitions cost more than they save.
        - **Remedy for small objects:** aggregate logs into larger compressed files before archiving.

7. Compare gp2 and gp3 across price, performance model, maximum IOPS, maximum throughput, and burst behaviour. Explain why gp3 is generally the better default and describe the operational steps needed to migrate an in-use gp2 volume.

    ??? success "Check your answer"

        A good answer covers:

        - **Price:** gp3 is about 20 percent cheaper per GiB than gp2.
        - **Performance model:** gp2 IOPS scale with size (3 IOPS per GiB); gp3 provides a 3,000 IOPS and 125 MiB/s baseline at any size, with IOPS and throughput provisioned independently.
        - **Maximums:** gp2 up to 16,000 IOPS and 250 MiB/s; gp3 up to 80,000 IOPS (500 IOPS per GiB) and 2,000 MiB/s, on volumes up to 64 TiB.
        - **Burst:** gp2 small volumes rely on burst credits that can run out; gp3 has no credit mechanism.
        - **Migration:** use Elastic Volumes `ModifyVolume` to change the type online with no detach or downtime, monitor until optimisation completes, and wait six hours before modifying again.

8. An EC2 instance cannot mount an EFS file system and the `mount` command hangs. Produce a systematic diagnostic checklist in the order you would work through it, explaining what each check rules out.

    ??? success "Check your answer"

        A good answer covers:

        - **Mount target:** confirm a mount target exists in the instance's AZ (or subnet) and is available.
        - **Security groups:** the mount target's security group must allow TCP 2049 inbound from the instance's security group.
        - **Network ACLs:** check subnet NACLs allow 2049 and the return ephemeral ports.
        - **DNS:** confirm the VPC has DNS resolution and DNS hostnames enabled, so the file system DNS name resolves.
        - **Client and policy:** check the EFS mount helper or NFS client is installed, TLS options are correct, and the file system policy or access point permits the client.

9. Explain what a presigned URL is, how it is validated by S3, and why using presigned URLs for uploads is architecturally superior to routing uploads through an application tier. State two security controls you would apply to presigned URL issuance.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** a URL signed with the issuer's credentials that grants time-limited permission for one operation on one object.
        - **Validation:** S3 recomputes the signature, checks the expiry, and checks the signer's IAM permissions at request time.
        - **Architectural benefit:** clients upload directly to S3, so large payloads bypass the application tier, removing bandwidth, memory and scaling pressure and avoiding API Gateway payload limits.
        - **Control 1:** short expiry times and a key generated by the server (never chosen by the client).
        - **Control 2:** sign with a role scoped to the specific prefix, and constrain content type or size (for example with presigned POST conditions).

10. A team enabled S3 versioning six months ago and is now surprised that storage costs have tripled while the visible object count is unchanged. Explain the likely causes and write the lifecycle rules that would bound the cost without losing recent recoverability.

    ??? success "Check your answer"

        A good answer covers:

        - **Noncurrent versions:** every overwrite and delete keeps the old version, which is billed but not shown in the default listing.
        - **Delete markers:** deleting objects only adds markers, so the underlying versions remain stored.
        - **Incomplete multipart uploads:** abandoned parts are billed but invisible to normal listings.
        - **Lifecycle rules:** `NoncurrentVersionExpiration` after for example 30 days (optionally keeping a number of newer noncurrent versions), `AbortIncompleteMultipartUpload` after 7 days, and expiration of expired object delete markers.
        - **Result:** cost is bounded while recent versions remain recoverable for the chosen window.

11. Design the complete storage layer for a multi-tenant SaaS platform serving five thousand tenants, each storing documents. Address tenant isolation, encryption and key strategy, cost control, backup and ransomware resilience, and the Recovery Point and Recovery Time Objectives. Justify why you did or did not create one bucket per tenant.

    ??? success "Check your answer"

        A good answer covers:

        - **Bucket strategy:** a shared bucket with per-tenant prefixes, rejecting one bucket per tenant because bucket quotas and per-bucket management overhead do not scale well to five thousand tenants (silos only for premium or regulated tenants).
        - **Isolation:** access enforced by IAM with tenant-scoped session policies or S3 Access Points / ABAC tags, so a tenant's credentials can only reach its prefix.
        - **Encryption:** SSE-KMS with S3 Bucket Keys; per-tenant keys only for tenants that require key control, accepting extra cost and quota management.
        - **Cost control:** Intelligent-Tiering or lifecycle rules, Storage Lens, and tenant tagging or prefix-level reporting for attribution.
        - **Resilience:** versioning, Object Lock or AWS Backup vault lock against ransomware, cross-Region and cross-account replication; RPO of minutes (replication) and RTO of hours (restore by prefix).

12. A financial services firm must run a PostgreSQL database on EC2 sustaining 80,000 IOPS at sub-millisecond latency, survive the loss of an Availability Zone with a Recovery Point Objective of one minute, and retain regulatory records immutably for seven years. Produce an architecture covering the volume type and sizing, the instance selection constraint, the replication mechanism, the backup strategy, and the archival control. Explain each trade-off you accept.

    ??? success "Check your answer"

        A good answer covers:

        - **Volume:** io2 Block Express provisioned for 80,000 IOPS, sized and configured for sub-millisecond latency, because io2 Block Express is designed for sub-millisecond average latency and 99.999 percent durability, whereas gp3 (although it can now reach 80,000 IOPS) offers single-digit millisecond latency.
        - **Instance constraint:** a Nitro instance type whose EBS bandwidth and IOPS limits exceed 80,000 IOPS and the required throughput, with EBS optimisation.
        - **Replication:** PostgreSQL streaming replication to a standby in another AZ (synchronous or near-synchronous) to meet an RPO of one minute, with automated failover tooling.
        - **Backup:** continuous WAL archiving to S3 plus scheduled EBS snapshots (via AWS Backup) for point-in-time recovery.
        - **Archive:** regulatory records exported to S3 with Object Lock in Compliance mode for seven years; trade-offs include the cost of io2, operational burden of self-management versus RDS, and latency added by synchronous replication.

13. An EKS platform hosts both stateless web services and a stateful analytics workload. Explain how the EBS and EFS CSI drivers differ in access mode, provisioning behaviour, and scheduling implications. Describe the failure mode that occurs when an EBS-backed pod cannot be scheduled in its volume's Availability Zone, and design around it.

    ??? success "Check your answer"

        A good answer covers:

        - **EBS CSI driver:** ReadWriteOnce block volumes, dynamically provisioned per PersistentVolumeClaim, bound to one AZ and one node at a time.
        - **EFS CSI driver:** ReadWriteMany shared volumes reachable from all AZs, provisioned through access points, with no zonal scheduling constraint.
        - **Failure mode:** a pod whose EBS volume is in `us-east-1a` cannot be scheduled on nodes in other AZs, so it stays `Pending` if capacity in that AZ is lost or full.
        - **Design around it:** use a StorageClass with `volumeBindingMode: WaitForFirstConsumer`, keep node capacity in every AZ, and use StatefulSets with replicas across AZs and application-level replication.
        - **Workload fit:** EBS for the stateful analytics database needing low latency; EFS or S3 for shared content used by stateless services.

14. A machine learning team's training jobs are bottlenecked reading a fifty-terabyte dataset from S3 across two hundred instances. Analyse where the bottleneck could be  client concurrency, prefix partitioning, instance network capacity, or storage throughput  and describe how you would measure each. Then propose a solution and explain why the durable system of record should remain S3.

    ??? success "Check your answer"

        A good answer covers:

        - **Client concurrency:** too few parallel connections or small sequential reads; measure per-instance throughput and use multipart ranged GETs and more threads.
        - **Prefix partitioning:** S3 supports at least 5,500 GET requests per second per prefix; spread keys across prefixes and watch for `503 SlowDown` errors.
        - **Instance network capacity:** check the instance type's network bandwidth and whether it is saturated using network metrics.
        - **Storage throughput:** compare aggregate demand with what S3 delivers; distributed training often needs a high-throughput cache layer.
        - **Solution:** stage data into FSx for Lustre linked to the S3 bucket (or use Mountpoint for S3 with caching); S3 remains the system of record because it is durable, cheap and the shared source for all jobs.

15. Your organisation's monthly AWS bill shows storage costs growing twenty percent per quarter while data volume grows only five percent. Design a systematic investigation using Storage Lens, S3 Inventory, Cost Explorer, and Trusted Advisor. Identify at least six specific, distinct sources of waste you would expect to find, and give the remediation for each. State which remediations are safe to automate and which require human judgement.

    ??? success "Check your answer"

        A good answer covers:

        - **Investigation:** Cost Explorer by usage type to find which storage dimension grew, Storage Lens for bucket-level trends and noncurrent bytes, S3 Inventory for object-level analysis, Trusted Advisor for idle and underused resources.
        - **Waste 1 and 2:** noncurrent versions without expiry, and incomplete multipart uploads; remediate with lifecycle rules (safe to automate).
        - **Waste 3 and 4:** unattached EBS volumes and old snapshots; remediate with Data Lifecycle Manager or AWS Backup retention after confirming ownership (requires human judgement).
        - **Waste 5 and 6:** gp2 volumes that should be gp3, and data in Standard that is rarely read; remediate with Elastic Volumes and Intelligent-Tiering or lifecycle transitions (generally safe to automate).
        - **Others:** over-provisioned io1/io2 IOPS, duplicate datasets, and logs without retention; deletions of data or snapshots always need human approval.

---

## 1.5 AWS Database Services

1. Define ACID and explain what each property guarantees. Give one example of an application requirement that depends on each.

    ??? success "Check your answer"

        A good answer covers:

        - **Atomicity:** a transaction completes fully or not at all; a funds transfer must not debit one account without crediting the other.
        - **Consistency:** every transaction leaves the data satisfying all constraints; an order line must never reference a product that does not exist.
        - **Isolation:** concurrent transactions do not see each other's intermediate state; two simultaneous purchases must not both take the last item in stock.
        - **Durability:** once committed, data survives crashes; an acknowledged booking must not disappear if the server fails.

2. Explain the difference between a partition key and a sort key in Amazon DynamoDB, and give an example of an access pattern that requires both.

    ??? success "Check your answer"

        A good answer covers:

        - **Partition key:** hashed to decide which physical partition stores the item; it groups related items and spreads load.
        - **Sort key:** orders items within a partition and allows range queries (`begins_with`, `between`, greater than).
        - **Primary key:** the partition key alone, or the combination of both, must uniquely identify an item.
        - **Example needing both:** "list a customer's orders newest first" uses `CustomerId` as partition key and `OrderDate` as sort key, queried in descending order.

3. What is a read replica, and how does it differ from a Multi-AZ standby in an Amazon RDS instance deployment? State one requirement that each is designed to satisfy.

    ??? success "Check your answer"

        A good answer covers:

        - **Read replica:** an asynchronously replicated, readable copy used to scale reads; it may lag the primary.
        - **Multi-AZ standby (instance deployment):** a synchronously replicated, non-readable copy in another AZ used only for automatic failover.
        - **Replica requirement:** offload read-heavy reporting or high read traffic from the primary.
        - **Multi-AZ requirement:** survive an AZ or instance failure with near-zero data loss and minimal downtime.

4. Describe the cache-aside pattern in sequence. What happens on a cache hit, and what happens on a cache miss?

    ??? success "Check your answer"

        A good answer covers:

        - **Read request:** the application first checks the cache for the key.
        - **Cache hit:** the value is returned directly from the cache with no database call.
        - **Cache miss:** the application reads from the database, writes the result to the cache with a TTL, then returns it.
        - **Writes:** the application updates the database and invalidates (or updates) the cache entry so stale data is not served for long.

5. An RDS instance is created with a backup retention period of zero. Explain precisely what capability is lost and why this is dangerous in production.

    ??? success "Check your answer"

        A good answer covers:

        - **Automated backups disabled:** a retention period of zero turns off automated backups.
        - **Point-in-time recovery lost:** without transaction logs retained, the database cannot be restored to an arbitrary second before an incident.
        - **Other side effects:** read replicas cannot be created for engines that require backups to be enabled.
        - **Danger:** accidental deletes, bad migrations or ransomware are replicated faithfully by Multi-AZ, so only backups protect against them; data loss could extend back to the last manual snapshot, if any.

6. A DynamoDB table stores events with `event_type` as the partition key across five possible values, and the application reports throttling despite generous provisioned capacity. Explain the cause in terms of DynamoDB's internal partitioning, then propose two distinct remedies and state the trade-off of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Cause:** DynamoDB distributes data and throughput by hashing the partition key; five values mean at most five hot partitions, each limited (around 3,000 RCU and 1,000 WCU per partition), regardless of table capacity.
        - **Remedy 1, write sharding:** append a random or calculated suffix (for example `event_type#0` to `#9`) to spread writes; trade-off is that reads must query every shard and merge.
        - **Remedy 2, high-cardinality key:** use a key such as `event_id` or `device_id` and add a GSI on `event_type` for the query; trade-off is extra cost and eventual consistency on the index, and the GSI itself can become hot.
        - **Diagnosis:** CloudWatch Contributor Insights reveals the hot keys.

7. Calculate the read and write capacity units required for the following workload, showing your reasoning: 1,200 strongly consistent reads per second of items averaging 7 KB, and 400 writes per second of items averaging 2.5 KB. Then state how the read requirement changes if eventually consistent reads are acceptable.

    ??? success "Check your answer"

        A good answer covers:

        - **Strongly consistent reads:** 7 KB rounds up to 8 KB, which is 2 RCU per read; 1,200 x 2 = 2,400 RCU.
        - **Writes:** 2.5 KB rounds up to 3 KB, which is 3 WCU per write; 400 x 3 = 1,200 WCU.
        - **Eventually consistent reads:** half the cost, so 1,200 RCU.
        - **Reasoning rule:** one RCU covers one strongly consistent read (or two eventually consistent reads) of up to 4 KB per second; one WCU covers one write of up to 1 KB per second.

8. Compare RDS Multi-AZ, RDS read replicas, and Aurora replicas across purpose, consistency, failover behaviour, replication mechanism, and typical lag. Identify the single most important architectural difference that Aurora's storage design produces.

    ??? success "Check your answer"

        A good answer covers:

        - **RDS Multi-AZ:** purpose is availability; synchronous replication to a non-readable standby; automatic failover in about one to two minutes; no lag.
        - **RDS read replicas:** purpose is read scaling; asynchronous logical/binlog or WAL replication; manual promotion; lag from seconds to longer under load.
        - **Aurora replicas:** purpose is both read scaling and failover; they read the same shared storage volume; automatic failover typically under about 30 seconds; lag usually well under 100 ms.
        - **Most important difference:** Aurora separates compute from a shared, six-way replicated storage layer, so replicas do not copy data and failover requires no catch-up.

9. An AWS Lambda function scaling to 800 concurrent executions exhausts connections to an Aurora PostgreSQL cluster. Explain the mechanism of the failure and design a complete remedy addressing connection management, blast-radius containment, and failover behaviour.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** each concurrent Lambda environment opens its own connection, so 800 executions demand 800 connections and exceed the database's connection limit, causing errors for every service sharing it.
        - **Connection management:** put RDS Proxy in front of Aurora to pool and multiplex connections, and open the connection outside the handler so warm invocations reuse it.
        - **Blast-radius containment:** set reserved concurrency on the function to cap connections, and queue work through SQS where possible so spikes are smoothed.
        - **Failover behaviour:** RDS Proxy keeps client connections open and reduces failover time by routing to the new writer; use IAM authentication and Secrets Manager for credentials.
        - **Alternative:** consider DynamoDB for access patterns that suit it, as it has no connections to exhaust.

10. Explain the thundering-herd problem in caching. Describe three distinct mitigations and explain the circumstances under which each is preferable.

    ??? success "Check your answer"

        A good answer covers:

        - **Thundering herd:** many requests miss the cache at once (for example when a popular key expires) and all hit the database simultaneously.
        - **Mitigation 1, request coalescing or locking:** only one request rebuilds the entry while others wait or serve stale data; best for very hot keys.
        - **Mitigation 2, TTL jitter:** randomise expiry times so many keys do not expire together; best after bulk loads or cache warm-ups.
        - **Mitigation 3, proactive refresh or warming:** refresh hot entries before expiry or pre-populate the cache after deployment; best when the hot set is predictable.
        - **Additional defence:** stale-while-revalidate and database-side protection such as connection limits.

11. Design the complete data architecture for a global e-commerce platform serving customers in North America, Europe, and Asia. It must guarantee that orders and payments are transactionally correct, serve product catalogue reads at under 20 milliseconds p99 in all three regions, support full-text product search, retain seven years of order history for audit, and survive the loss of an entire AWS Region. Specify every data store, justify each against a stated rejected alternative, identify precisely where eventual consistency is introduced, and explain how the design prevents that eventual consistency from producing an incorrect financial outcome.

    ??? success "Check your answer"

        A good answer covers:

        - **Orders and payments:** Aurora PostgreSQL in a home Region with Multi-AZ for ACID transactions, rejecting DynamoDB multi-writer Global Tables because last-writer-wins is unsafe for money.
        - **Catalogue reads:** DynamoDB Global Tables (or Aurora Global Database read replicas) with ElastiCache and CloudFront for under 20 ms p99 in all three regions, rejecting reads from a single distant Region.
        - **Search and history:** Amazon OpenSearch Service fed from change streams for full-text search (rejecting SQL `LIKE` queries); order history archived to S3 with lifecycle and Object Lock for seven years, queried with Athena.
        - **Region loss:** Aurora Global Database with a promotable secondary Region and tested failover.
        - **Where eventual consistency appears and how it is contained:** in catalogue replicas, search indexes and cache; prices and stock are re-validated against the transactional store at checkout, with idempotency keys on payments, so stale reads cannot produce an incorrect charge.

12. A DynamoDB single-table design must support the following access patterns: retrieve a customer by identifier; list a customer's orders newest first; retrieve an order with all its line items in one request; list all orders in a given status placed in the last 24 hours; and retrieve the ten highest-value orders for a customer. Design the complete key schema, including partition key, sort key, and any secondary indexes with their projections. Justify each index, identify which patterns are eventually consistent, and explain what you would do differently if a sixth pattern  arbitrary full-text search across order notes  were added.

    ??? success "Check your answer"

        A good answer covers:

        - **Base table:** `PK = CUSTOMER#id`; items `SK = PROFILE` (customer), `SK = ORDER#<timestamp>#<orderId>` (orders newest first by descending query), and order line items stored under `PK = ORDER#orderId` with `SK = ITEM#n` plus an `SK = META` header, giving one query for an order with its lines.
        - **GSI1 for status:** `GSI1PK = STATUS#<status>`, `GSI1SK = <createdAt>`, queried with a 24-hour range; consider sharding the status key if one status is very hot.
        - **GSI2 for top value:** `GSI2PK = CUSTOMER#id`, `GSI2SK = <zero-padded order value>`, queried descending with `Limit 10`; project only the attributes needed (KEYS_ONLY or INCLUDE) to save cost.
        - **Consistency:** base-table patterns can be strongly consistent; both GSI patterns are eventually consistent.
        - **Sixth pattern:** full-text search does not fit DynamoDB; stream changes via DynamoDB Streams to OpenSearch Service and query there.

13. Critically evaluate the claim that "DynamoDB is cheaper than Aurora". Construct a quantitative comparison for a workload of 5,000 reads and 500 writes per second on items averaging 3 KB, with 2 TB of stored data. State every assumption explicitly, identify the conditions under which each service wins, and then explain why the financial comparison alone is insufficient grounds for the architectural decision.

    ??? success "Check your answer"

        A good answer covers:

        - **DynamoDB provisioned (us-east-1 list prices, assumptions stated):** 3 KB reads need 1 RCU strongly consistent or 0.5 eventually consistent, so 2,500 to 5,000 RCU; 3 KB writes need 3 WCU each, so 1,500 WCU; at about 0.00013 USD per RCU-hour and 0.00065 USD per WCU-hour this is roughly 240 to 475 USD plus about 710 USD per month.
        - **DynamoDB storage:** 2 TB at about 0.25 USD per GB-month is roughly 500 USD, giving a total around 1,450 to 1,700 USD per month before backups and Global Tables.
        - **Aurora:** cost is dominated by instance hours (a writer plus at least one replica sized for 5,000 reads per second), plus storage at about 0.10 USD per GB-month (about 200 USD) and I/O charges or the I/O-Optimised option.
        - **When each wins:** DynamoDB wins for key-value access at steady or spiky scale with no idle instances; Aurora wins when queries are relational, ad hoc or join-heavy, when caching absorbs most reads, or when on-demand DynamoDB would be used at sustained high load.
        - **Why cost is insufficient:** access patterns, query flexibility, transactional needs, team skills, operational effort and migration risk matter as much as the monthly bill.

14. A financial institution requires a ledger that is auditable, tamper-evident, strictly ordered, and able to sustain 20,000 appends per second, with the ability to reconstruct account balances at any historical instant. Design the persistence layer using an event-sourcing approach. Address the choice of store, the key schema or table design, optimistic concurrency control, snapshotting strategy, the read model and how it is maintained, retention and archival to S3, encryption and key management, and the audit trail. Identify the specific failure modes your design accepts and explain why they are tolerable.

    ??? success "Check your answer"

        A good answer covers:

        - **Store and schema:** DynamoDB table with `PK = ACCOUNT#id` and `SK = <sequence number>` as an append-only event log, with writes spread across many accounts for 20,000 appends per second (rejecting a single relational writer as a scaling ceiling).
        - **Concurrency control:** conditional writes (`attribute_not_exists` on the next sequence number) give optimistic concurrency and strict per-account ordering; transactions where an event spans two accounts.
        - **Snapshots and read model:** periodic balance snapshots every N events to bound replay; a read model maintained from DynamoDB Streams by idempotent Lambda consumers.
        - **Retention and protection:** export old events to S3 with Object Lock (Compliance mode) and lifecycle to Glacier; SSE-KMS with customer managed keys and separated key administration; CloudTrail data events and hash chaining for tamper evidence.
        - **Accepted failure modes:** read models lag the ledger briefly (eventual consistency), conditional-write conflicts require client retries, and a hot account may be throttled; these are tolerable because the ledger itself is never wrong and balances can be rebuilt from events.

15. An organisation operates 40 microservices, each with its own database, and finds that cross-service reporting has become impossible without querying production databases directly, which is degrading them. Design a solution that restores analytical capability without coupling services or affecting production performance. Address change-data capture, the landing and transformation layers, schema evolution across 40 independently versioned services, data freshness expectations, cost, governance, and how you would prevent the analytical layer from becoming a new form of coupling between the services.

    ??? success "Check your answer"

        A good answer covers:

        - **Change-data capture:** use AWS DMS, Debezium on MSK, DynamoDB Streams or Aurora zero-ETL to stream changes out without querying production.
        - **Landing and transformation:** land raw changes in an S3 data lake (raw, cleaned, curated zones), transform with Glue or EMR, and serve with Athena or Redshift.
        - **Schema evolution:** a schema registry, versioned data contracts owned by each service team, and backward-compatible changes only.
        - **Freshness and cost:** agree freshness expectations (minutes or hourly rather than real time), use columnar formats and partitioning, and pay for scans only where needed.
        - **Governance and decoupling:** Lake Formation permissions and a catalogue; services publish published data products (not internal tables), so the analytical layer depends on contracts rather than becoming a back door coupling services together.

---

## 1.6 AWS Network Services

1. Explain, in your own words, the difference between a public subnet, a private subnet, and an isolated subnet. For each, state exactly what appears in its route table.

    ??? success "Check your answer"

        A good answer covers:

        - **Public subnet:** route table has the local route plus `0.0.0.0/0` to an Internet Gateway; resources with public IPs can be reached from and reach the internet.
        - **Private subnet:** route table has the local route plus `0.0.0.0/0` to a NAT gateway; resources can initiate outbound connections but cannot be reached from the internet.
        - **Isolated subnet:** route table has only the local route (plus any VPC endpoint routes); no internet path in either direction.
        - **Key principle:** the route table alone makes a subnet public or private.

2. A subnet is created with CIDR `10.30.4.0/24`. List every address that cannot be assigned to a resource, and state the purpose of each. How many addresses remain usable?

    ??? success "Check your answer"

        A good answer covers:

        - **`10.30.4.0`:** network address.
        - **`10.30.4.1`:** reserved for the VPC router.
        - **`10.30.4.2`:** reserved for the Amazon-provided DNS server.
        - **`10.30.4.3`:** reserved for future use.
        - **`10.30.4.255`:** broadcast address (broadcast is not supported but the address is reserved); usable addresses are 256 - 5 = 251.

3. You create a new security group and attach it to an EC2 instance in a public subnet. The instance has a public IP address. Without adding any rules, can you (a) SSH to the instance from the internet, and (b) run `yum update` from the instance? Explain both answers in terms of default security group behaviour.

    ??? success "Check your answer"

        A good answer covers:

        - **(a) SSH from the internet:** no; a new security group has no inbound rules, so inbound SSH is denied.
        - **(b) `yum update`:** yes, provided the subnet's route table, NACL and public IP allow it, because a new security group allows all outbound traffic.
        - **Statefulness:** the reply traffic for the outbound connection is allowed automatically because security groups are stateful.
        - **Takeaway:** default security groups block inbound and allow outbound.

4. State three differences between a security group and a network ACL, and give one situation in which only a network ACL can satisfy the requirement.

    ??? success "Check your answer"

        A good answer covers:

        - **Scope:** security groups attach to network interfaces; NACLs attach to subnets.
        - **State:** security groups are stateful; NACLs are stateless, so return traffic needs its own rule.
        - **Rule types:** security groups allow only; NACLs support allow and deny, evaluated in rule-number order.
        - **Only a NACL can:** explicitly deny a specific malicious IP address or CIDR range across a whole subnet.

5. An application in a private subnet must download objects from Amazon S3. Compare routing this traffic through a NAT Gateway with using a Gateway endpoint, in terms of cost, security, and the network path taken.

    ??? success "Check your answer"

        A good answer covers:

        - **NAT gateway path:** traffic leaves the private subnet, crosses the NAT gateway and reaches S3's public endpoint; it is charged per hour and per GB processed.
        - **Gateway endpoint path:** a route-table entry to the S3 prefix list sends traffic to S3 over the AWS private network, with no hourly or data-processing charge.
        - **Security:** the gateway endpoint supports endpoint policies and bucket policies using `aws:SourceVpce`, so access can be limited to specific buckets.
        - **Recommendation:** use the gateway endpoint; NAT adds cost and a zonal dependency for no benefit.

6. A VPC is allocated `10.40.0.0/16`. Design a subnet plan for **three** Availability Zones containing a public tier (`/24` each), a private application tier (`/20` each), and an isolated data tier (`/22` each), leaving at least half the VPC unallocated for future growth. Write out every CIDR block, confirm that none overlap, and state how many usable addresses each private application subnet provides.

    ??? success "Check your answer"

        A good answer covers:

        - **Private /20s:** `10.40.0.0/20`, `10.40.16.0/20`, `10.40.32.0/20` (one per AZ).
        - **Isolated /22s:** `10.40.48.0/22`, `10.40.52.0/22`, `10.40.56.0/22`.
        - **Public /24s:** `10.40.60.0/24`, `10.40.61.0/24`, `10.40.62.0/24`.
        - **No overlap and growth room:** allocations run contiguously from `10.40.0.0` to `10.40.62.255` (about a quarter of the VPC), leaving `10.40.64.0/18` and `10.40.128.0/17`, more than half the VPC, unallocated.
        - **Usable addresses:** each private /20 has 4,096 - 5 = 4,091 usable addresses.

7. A team enables a custom network ACL on a subnet with inbound allow for TCP 443 and outbound allow for TCP 443. All HTTPS requests to the web servers now time out. Explain precisely why, identify the missing rule including its port range and direction, and explain why the same problem does not occur with security groups.

    ??? success "Check your answer"

        A good answer covers:

        - **Cause:** NACLs are stateless; responses from the web servers go to the client's ephemeral source port, not to 443.
        - **Blocked direction:** the outbound rule only allows TCP 443, so outbound responses to ephemeral ports are denied and connections hang.
        - **Missing rule:** an outbound allow for TCP `1024-65535` to the client CIDR (`0.0.0.0/0` for public clients).
        - **Security groups differ:** they are stateful, so return traffic for an allowed inbound connection is permitted automatically.

8. Compare the seven Route 53 routing policies. For each of the following requirements, choose one policy and justify it: (a) 10 percent of users should reach a new version; (b) European users must be served only from a European Region for data-protection reasons; (c) users worldwide should get the fastest response; (d) if the primary Region fails, serve a static maintenance page from S3.

    ??? success "Check your answer"

        A good answer covers:

        - **The policies:** simple, weighted, latency, failover, geolocation, geoproximity, multivalue answer (IP-based routing is an eighth, newer policy).
        - **(a) 10 percent to a new version:** weighted routing with weights such as 90 and 10.
        - **(b) European users only in Europe:** geolocation routing by continent or country, with a default record for others.
        - **(c) Fastest response worldwide:** latency-based routing with health checks.
        - **(d) Maintenance page on failure:** failover routing, with the primary health-checked and the secondary an alias to an S3 static website or CloudFront distribution.

9. An HTTP API using a Lambda authorizer shows a p50 latency of 320 milliseconds, of which 140 milliseconds is the authorizer invocation. Describe three changes that would reduce this, and state the trade-off each one introduces.

    ??? success "Check your answer"

        A good answer covers:

        - **Authorizer result caching:** cache the policy by token for a TTL (up to an hour); trade-off is that revoked tokens remain valid until the cache expires.
        - **Use a native JWT authorizer:** HTTP APIs validate JWTs from an OIDC provider such as Cognito without invoking Lambda; trade-off is less flexibility for custom authorisation logic.
        - **Optimise the Lambda authorizer:** provisioned concurrency or SnapStart, smaller runtime and package, and caching JWKS keys outside the handler; trade-off is extra cost and maintenance.
        - **Measure:** use X-Ray to confirm where the 140 ms goes before choosing.

10. Your organisation has eight VPCs across three accounts, all of which must communicate, plus a requirement to reach an on-premises data centre. Compare VPC peering and Transit Gateway for this case quantitatively (number of connections, number of route entries, cost dimensions) and recommend one with justification.

    ??? success "Check your answer"

        A good answer covers:

        - **Peering connections:** a full mesh of 8 VPCs needs 8 x 7 / 2 = 28 peering connections.
        - **Peering routes:** each VPC route table needs 7 routes (one per peer), multiplied across every subnet route table, and peering is non-transitive so on-premises access needs a separate VPN or Direct Connect path per VPC.
        - **Transit Gateway:** 8 VPC attachments plus one VPN or Direct Connect attachment, and each VPC route table can use a single summarised route to the TGW.
        - **Cost dimensions:** peering has no hourly charge (data transfer applies); Transit Gateway charges per attachment-hour and per GB processed.
        - **Recommendation:** Transit Gateway, because the mesh is already complex, the accounts are multiple, and on-premises connectivity requires transitive routing.

11. An EKS cluster must support 15,000 concurrent pods using the Amazon VPC CNI. The VPC is currently `10.50.0.0/16` with three private subnets of `/20` each. Calculate whether the current address space is sufficient, accounting for the CNI's warm-address behaviour and for cluster growth. If it is not, design a remediation using secondary CIDR blocks, CNI custom networking, and prefix delegation, and explain the trade-offs of each technique.

    ??? success "Check your answer"

        A good answer covers:

        - **Capacity check:** three /20 subnets give 3 x 4,091 = 12,273 usable addresses, fewer than 15,000 pods before counting nodes, load balancers and endpoints.
        - **Warm-address effect:** the VPC CNI pre-allocates warm IPs or ENIs per node, so real consumption exceeds the pod count, and growth makes the gap worse.
        - **Secondary CIDR plus custom networking:** add a block such as `100.64.0.0/16` and use ENIConfig per AZ so pods use the secondary subnets; trade-off is that the node's primary ENI no longer hosts pods, reducing maximum pods per node.
        - **Prefix delegation:** assign /28 prefixes per ENI slot to raise pod density per node; trade-off is that subnets need contiguous free /28 blocks and fragmentation can cause allocation failures.
        - **Alternative:** an IPv6 cluster removes address exhaustion but requires IPv6-ready dependencies.

12. Design a multi-Region active-active architecture for an API that must maintain availability during the complete loss of one Region, with a recovery time objective under 60 seconds. Specify the DNS strategy, the health-check strategy, the data-replication implication, and explain why your failover mechanism does not depend on any control plane in the failed Region. Justify your choice between Route 53 failover, Route 53 latency routing with health checks, and AWS Global Accelerator.

    ??? success "Check your answer"

        A good answer covers:

        - **DNS strategy:** Route 53 latency-based records for both Regions, each associated with a health check, with low TTLs (around 60 seconds); or Global Accelerator with endpoint groups per Region.
        - **Health checks:** deep health checks that test the application's critical path in each Region, evaluated by Route 53's global data plane.
        - **Data replication:** DynamoDB Global Tables or Aurora Global Database; active-active writes require conflict handling, or a single write Region with reads in both.
        - **No dependency on the failed Region:** traffic shifts because health checks fail, which is a data-plane decision outside the Region; both Regions already run at full capacity.
        - **Choice:** Global Accelerator gives the fastest, DNS-cache-independent failover within the 60-second RTO; Route 53 latency with health checks is acceptable if TTL plus detection fits; plain failover routing suits active-passive rather than active-active.

13. A financial services organisation requires that (a) no workload subnet has any route to the internet, (b) all outbound traffic from 30 VPCs is inspected by a stateful firewall with domain-name filtering, (c) each business unit's VPCs cannot reach another business unit's VPCs, and (d) all of this must be auditable. Design the network. Name every component, describe the Transit Gateway route-table structure, explain how egress inspection is enforced, and describe the evidence you would produce for an auditor.

    ??? success "Check your answer"

        A good answer covers:

        - **Network components:** Transit Gateway hub, workload VPCs with no IGW or NAT, a central egress/inspection VPC with AWS Network Firewall (stateful rules with domain allow lists) and NAT gateways, plus an Organizations SCP preventing IGW creation.
        - **TGW route tables:** one route table per business unit associated with its VPCs, propagating only to the inspection VPC and shared services, so business units cannot route to each other.
        - **Egress enforcement:** each workload VPC's default route points to the TGW, TGW routes `0.0.0.0/0` to the inspection VPC, and appliance mode keeps flows symmetric through the firewall.
        - **Auditability:** Network Firewall alert and flow logs, VPC Flow Logs, AWS Config rules (no IGWs, no `0.0.0.0/0` routes to IGW), CloudTrail, and Reachability Analyzer or Network Access Analyzer reports as evidence.
        - **Account structure:** central networking account sharing TGW via Resource Access Manager.

14. Your API Gateway front end can accept 10,000 requests per second, but the downstream relational database supports 400 concurrent connections and the business requires that no request be lost. Design the complete request path including back-pressure, and calculate the queue-depth and worker-concurrency implications if a five-minute burst arrives at 10,000 requests per second while workers drain at 400 per second. State what the client experiences at each stage.

    ??? success "Check your answer"

        A good answer covers:

        - **Request path:** API Gateway with a direct SQS integration accepts requests and returns `202 Accepted` with a request ID; workers (ECS tasks or Lambda with maximum concurrency) drain the queue into the database through a connection pool.
        - **Back-pressure:** worker concurrency is capped at or below 400 database connections; API Gateway throttles beyond the account limit with `429`.
        - **Arithmetic:** five minutes at 10,000 per second is 3,000,000 requests; draining at 400 per second removes 120,000 during the burst, leaving about 2,880,000 queued.
        - **Drain time:** 2,880,000 / 400 = 7,200 seconds, about two hours after the burst ends, well within SQS retention.
        - **Client experience:** immediate acknowledgement, then completion up to two hours later via polling or a callback; requests are not lost because SQS stores them durably, and a DLQ captures poison messages.

15. An organisation's monthly bill shows large charges for `NatGateway-Bytes`, `DataTransfer-Regional-Bytes`, and `PublicIPv4:InUseAddress`. Describe a systematic investigation using VPC Flow Logs, Athena, and Cost Explorer, then propose a remediation for each of the three charges. For each remediation, state the new cost it introduces and the conditions under which the change would **not** be worthwhile.

    ??? success "Check your answer"

        A good answer covers:

        - **Investigation:** Cost Explorer filtered by usage type to find which VPC and Region dominate; VPC Flow Logs queried with Athena to identify top source and destination pairs through NAT and across AZs; public IPv4 insights through VPC IP Address Manager.
        - **`NatGateway-Bytes`:** add Gateway endpoints for S3 and DynamoDB and Interface endpoints for heavily used services such as ECR; new cost is Interface endpoint hours and per-GB charges, not worthwhile for low-volume services.
        - **`DataTransfer-Regional-Bytes`:** keep chatty traffic in the same AZ (topology-aware routing, same-AZ NAT gateways); new cost is reduced resilience if over-applied, not worthwhile where cross-AZ spread is required for availability.
        - **`PublicIPv4:InUseAddress`:** remove unnecessary public IPs, put instances behind load balancers or NAT, consider IPv6; new cost is NAT or load balancer charges, not worthwhile if it adds a NAT gateway for a handful of addresses.
        - **Process:** set budgets and cost anomaly alerts to catch regressions.

---

## 1.7 Cloud-Native Design Patterns

1. Define cloud-native and explain why simply moving a virtual machine to EC2 does not make an application cloud-native.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** cloud-native means designing applications to exploit cloud properties: elastic, managed services, automation, resilience by design and loose coupling.
        - **Characteristics:** stateless horizontally scalable components, infrastructure as code, managed and serverless services, observability and continuous delivery.
        - **Why lift-and-shift is not enough:** a VM moved to EC2 keeps its monolithic structure, manual operations, local state and fixed capacity.
        - **Result:** it gains a different data centre but not elasticity, managed resilience or faster delivery.

2. List three characteristics of serverless computing and give one AWS service that exemplifies each.

    ??? success "Check your answer"

        A good answer covers:

        - **No server management:** AWS manages infrastructure and runtime; for example AWS Lambda.
        - **Automatic scaling, including to zero:** capacity follows demand; for example DynamoDB on-demand or SQS.
        - **Pay-per-use pricing:** billed by requests, duration or data rather than provisioned capacity; for example Lambda or Amazon S3.
        - **Event-driven execution:** compute runs in response to events; for example Lambda triggered by EventBridge or S3.

3. What is the difference between SNS and SQS? Give a scenario appropriate to each.

    ??? success "Check your answer"

        A good answer covers:

        - **SNS:** a push-based pub/sub topic that delivers a copy of each message to every subscriber; no persistence for later polling.
        - **SQS:** a pull-based queue where consumers poll; each message is processed by one consumer, with retries and a DLQ.
        - **SNS scenario:** notifying several systems (email, analytics, inventory) when an order is placed.
        - **SQS scenario:** buffering image-processing jobs so workers process them at their own rate.
        - **Together:** SNS-to-SQS fan-out gives each consumer its own durable queue.

4. Explain what an event is in an event-driven architecture and how it differs from a command.

    ??? success "Check your answer"

        A good answer covers:

        - **Event:** an immutable fact about something that has already happened, such as `OrderPlaced`, broadcast to whoever cares.
        - **Command:** a request directed to a specific recipient asking it to do something, such as `ChargeCard`.
        - **Coupling:** commands couple the sender to a known receiver and its availability; events decouple producers from consumers.
        - **Naming:** events use past tense; commands use the imperative.

5. What does "API-first" mean, and name two artefacts produced before any implementation code is written.

    ??? success "Check your answer"

        A good answer covers:

        - **Meaning:** the API contract is designed, reviewed and agreed before implementation, and APIs are treated as products.
        - **Artefact 1:** an OpenAPI (or AsyncAPI or GraphQL schema) specification of the contract.
        - **Artefact 2:** mock servers generated from the specification so consumers can integrate early.
        - **Other artefacts:** style guides and lint rules, contract tests and generated client SDKs.

6. Explain what a cold start is, three factors that influence its duration, and two mitigation strategies with their cost implications.

    ??? success "Check your answer"

        A good answer covers:

        - **Cold start:** extra latency when Lambda must create a new execution environment, load code and run initialisation before the handler runs.
        - **Factors:** runtime choice (JVM and .NET slower), package or image size and initialisation work, memory setting (CPU scales with memory), and VPC attachment or dependency initialisation.
        - **Mitigation 1:** provisioned concurrency keeps environments warm; cost is paid for that capacity whether used or not.
        - **Mitigation 2:** SnapStart (for example for Java) or smaller packages and lazy initialisation; low or no extra cost but engineering effort.
        - **Note:** higher memory can also shorten cold starts at a slightly higher per-millisecond rate.

7. A microservice needs to call three other services to build a response. Describe two design changes that would reduce user-perceived latency and improve resilience.

    ??? success "Check your answer"

        A good answer covers:

        - **Parallelise:** call the three services concurrently instead of sequentially, so latency becomes the slowest call rather than the sum.
        - **Use cached or precomputed data:** maintain a local read model fed by events (CQRS) or cache responses, removing calls from the request path.
        - **Resilience:** apply timeouts, retries with backoff and jitter, and circuit breakers so one slow service does not hang the response.
        - **Graceful degradation:** return a partial response when a non-critical dependency fails.

8. Compare choreography and orchestration for a five-step order-fulfilment process. Which would you choose and why?

    ??? success "Check your answer"

        A good answer covers:

        - **Choreography:** services react to each other's events with no coordinator; loosely coupled but the flow is implicit and hard to trace.
        - **Orchestration:** a central coordinator such as Step Functions directs each step; the flow is visible, retries and compensations are explicit, and history is auditable.
        - **For five steps with failure handling:** orchestration is usually the better choice because compensation and status tracking are central to order fulfilment.
        - **Trade-off:** the orchestrator becomes a central dependency, while choreography suits simple notifications that do not need coordination.

9. Explain why event consumers must be idempotent, and describe an implementation using DynamoDB conditional writes.

    ??? success "Check your answer"

        A good answer covers:

        - **Why:** SQS, SNS and EventBridge deliver at least once, and retries or timeouts produce duplicates, so processing must be safe to repeat.
        - **Idempotency key:** use the event ID or a business key carried in the event.
        - **DynamoDB conditional write:** `PutItem` the key into an idempotency table with `ConditionExpression attribute_not_exists(pk)`; a `ConditionalCheckFailedException` means the event has already been processed.
        - **Atomicity:** where possible, write the business change and the idempotency record in one `TransactWriteItems` call.
        - **Cleanup:** set a TTL attribute so old keys expire after the duplicate window.

10. Your SQS visibility timeout is 30 seconds and your consumer sometimes takes 45 seconds. Describe precisely what goes wrong and how to fix it.

    ??? success "Check your answer"

        A good answer covers:

        - **What goes wrong:** after 30 seconds the message becomes visible again while the first consumer is still working, so a second consumer receives and processes it.
        - **Effects:** duplicate processing, and the first consumer's delete may fail or arrive late because the receipt handle has changed; repeated timeouts can push the message into the DLQ.
        - **Fix 1:** set the visibility timeout comfortably above the maximum processing time (for Lambda, at least six times the function timeout is recommended).
        - **Fix 2:** extend visibility with `ChangeMessageVisibility` as a heartbeat for variable-length work.
        - **Fix 3:** make the consumer idempotent anyway.

11. Design a multi-tenant SaaS platform on AWS where tenants have different throughput tiers and no tenant may degrade another's performance. Address API throttling, compute isolation, data isolation, observability per tenant, and cost attribution. Justify every choice against the Well-Architected pillars.

    ??? success "Check your answer"

        A good answer covers:

        - **API throttling:** API Gateway usage plans and API keys per tenant tier, with rate and burst limits matched to each tier.
        - **Compute isolation:** pooled compute for standard tiers with per-tenant concurrency limits (reserved concurrency, separate queues), and siloed compute or cells for premium tenants.
        - **Data isolation:** tenant ID in the partition key with IAM conditions such as `dynamodb:LeadingKeys`, or separate databases for regulated tenants.
        - **Per-tenant observability and cost:** tenant ID in structured logs, metrics dimensions and traces; cost allocation tags or per-tenant metering for showback.
        - **Well-Architected justification:** security (isolation), reliability (bounded blast radius), performance efficiency (tiered capacity), cost optimisation (pooling where safe) and operational excellence (automated onboarding).

12. A payment system must move funds between two microservices that own separate databases. ACID transactions are impossible. Design a solution using the Saga pattern, specify compensating actions, explain how you guarantee the event is published if and only if the database write succeeds, and describe how you would prove correctness to an auditor.

    ??? success "Check your answer"

        A good answer covers:

        - **Saga steps:** debit the source account (local transaction), then credit the destination account; each is a local transaction in its owning service.
        - **Compensation:** if the credit fails, issue a compensating refund to the source account; compensations must be idempotent and retriable.
        - **Coordination:** Step Functions orchestration with `Retry` and `Catch` invoking compensation states, giving a recorded execution history.
        - **Atomic publish:** the transactional outbox pattern writes the business change and the event in the same database transaction, and a relay (or change stream) publishes it, so the event exists if and only if the write committed.
        - **Proof for auditors:** idempotency keys, Step Functions execution history, an append-only ledger of state transitions, and reconciliation reports showing every transfer reached a terminal state.

13. An organisation with 45 microservices reports that deployment frequency has dropped and incidents take an average of four hours to diagnose. Diagnose the likely architectural and organisational causes, and propose a prioritised twelve-month remediation plan.

    ??? success "Check your answer"

        A good answer covers:

        - **Likely causes:** a distributed monolith with shared databases and lockstep releases, long synchronous call chains, shared pipelines and environments, and team boundaries that do not match service boundaries.
        - **Diagnosis gaps:** no distributed tracing, unstructured logs and no correlation IDs, which explains four-hour diagnosis times.
        - **First quarter:** observability foundations (structured logs, correlation IDs, X-Ray or OpenTelemetry tracing, service-level dashboards and SLOs).
        - **Next two quarters:** independent pipelines per service, contract tests, breaking shared databases and replacing synchronous chains with events where appropriate.
        - **Final quarter:** realign teams to bounded contexts, merge services that always change together, and measure DORA metrics to confirm improvement.

14. Evaluate serverless versus containers for a workload of 400 million requests per month, average duration 180 ms, average memory 512 MB, with a strict p99 latency requirement of 100 ms. Show your reasoning on cost, latency, and operational burden, and state what additional information you would need to make a final recommendation.

    ??? success "Check your answer"

        A good answer covers:

        - **Lambda cost (assumed us-east-1 x86 list prices, no free tier):** 400 million x 0.18 s x 0.5 GB = 36 million GB-s, about 600 USD, plus about 80 USD in request charges, roughly 680 USD per month, plus API Gateway (about 400 USD for an HTTP API or 1,400 USD for a REST API).
        - **Container comparison:** average load is about 154 requests per second, about 28 concurrent requests, which a small Fargate or EC2 fleet across AZs with an ALB can serve for a few hundred USD per month.
        - **Latency:** a 100 ms p99 is threatened by cold starts on Lambda, needing provisioned concurrency (extra cost); containers stay warm and give steadier tail latency.
        - **Operational burden:** Lambda has the least operations; containers need image, scaling and patching work (reduced with Fargate).
        - **Information needed:** peak-to-average ratio and traffic shape, CPU versus I/O profile, payload sizes, dependency latency, team skills and existing platform.

15. Design an event-driven data platform ingesting 200,000 IoT telemetry events per second that must support real-time alerting (sub-second), hourly aggregation, and ad-hoc historical analysis over two years of data. Specify the services, partitioning strategy, storage tiers, failure handling, and cost controls.

    ??? success "Check your answer"

        A good answer covers:

        - **Ingestion:** AWS IoT Core or Kinesis Data Streams in on-demand or provisioned mode with enough shards (each shard accepts up to 1,000 records or 1 MB per second, so at least 200 shards plus headroom), partitioned by device ID.
        - **Real-time alerting:** Managed Service for Apache Flink or Lambda consumers with enhanced fan-out evaluating rules within a second, publishing alerts to SNS or EventBridge.
        - **Hourly aggregation and storage tiers:** Firehose writing batched, compressed Parquet to S3 partitioned by date and hour; aggregates in Timestream, DynamoDB or Redshift for dashboards; lifecycle to Glacier for older raw data.
        - **Historical analysis:** Athena or Redshift Spectrum over the partitioned S3 data lake catalogued in Glue.
        - **Failure handling and cost:** stream retention for replay, DLQs and bisect-on-error for consumers, idempotent processing; cost controls via aggregation at the edge, compression, columnar formats and lifecycle rules.

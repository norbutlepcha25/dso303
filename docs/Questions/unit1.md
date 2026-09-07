
# Unit 1: Questions for Practice

## 1.1 : Global Infrustrusture

1. Define Region, Availability Zone, and Edge Location, and state the primary purpose of each layer.
2. Why does AWS require (in modern Regions) a minimum of three AZs rather than one large data centre?
3. What is the difference between the AZ _name_ `eu-west-1a` and the AZ _ID_ `euw1-az1`, and why does the difference exist?
4. List four factors an architect evaluates when selecting a Region, in a sensible priority order.
5. When a CloudFront edge receives a request for an object it does not hold, describe the sequence of lookups before the origin is contacted.
6. Your application runs six EC2 instances in `ap-southeast-1a` behind an ALB whose subnets span three AZs. Identify the availability flaw and describe two concrete fixes, including the Auto Scaling configuration involved.
7. A distribution forwards all cookies and all query strings to a dynamic origin. Explain the effect on cache hit ratio, origin load, and cost, and propose a corrected cache-policy design for a site with `/static/*` and `/api/*` paths.
8. Compare RDS Multi-AZ, RDS read replicas, and cross-Region read replicas along three axes: replication mode (sync/async), purpose (HA/scale/DR), and effect on RPO.
9. Explain how you would restrict an AWS Organization to two approved Regions, and why `iam:*`, `cloudfront:*`, and `route53:*` typically must be exempted from that restriction.
10. Your team claims "we are multi-AZ, therefore we survive AZ failure." Name three hidden single-AZ dependencies that could falsify this claim (consider NAT, data, and control-plane assumptions).

11. Design a multi-Region architecture for a payments API with RPO ≤ 1 second and RTO ≤ 5 minutes. Specify the data technology, the traffic-steering mechanism and its health signal, and how you avoid control-plane dependence during failover. State the consistency trade-off you accepted.
12. Explain _static stability_ and redesign the following to satisfy it: "On AZ failure, a Lambda triggered by a CloudWatch alarm updates the Auto Scaling group to launch replacements and calls the Route 53 API to change weights."
13. A microservices platform on EKS shows large inter-AZ data-transfer charges and elevated p99 latency. Discuss the tension between AZ-spread for resilience and AZ-affinity for cost/latency, and describe a topology-aware routing approach that balances them.
14. Your global user base is 60% in regions where you have no AWS Region within 150 ms. Compare three remedies — additional Regions (active-active), CloudFront with an aggressive caching strategy, and Global Accelerator — for a workload that is 80% cacheable reads and 20% authenticated writes. Recommend and justify a combination.
15. During a partial edge-network event, some users receive errors while all Regional metrics are green and synthetic canaries in-Region pass. Construct the observability strategy (metrics locations, log types, external vantage points, AWS Health integration) that would have detected this class of failure, and the automated mitigation you would attach to it.

## 1.2

## 1.3 : Compute Services

1. Define an Amazon Machine Image, an instance type, and an instance profile, and explain the role each plays when an EC2 instance launches.
2. Explain the difference between object-level responsibility in the AWS shared responsibility model for EC2 versus for AWS Lambda. Name three things that become the customer's responsibility with EC2 but not with Lambda.
3. What is a container image, and why does immutability of that image matter for reproducible deployments? Contrast this with configuring a server after launch.
4. List the four purchasing options for EC2 capacity and give one workload that suits each.
5. An AWS Lambda function is configured with 128 MB of memory and takes 4 seconds to run. The team increases it to 512 MB and it now takes 1 second. Explain why the total cost may be unchanged or lower, and why the user-perceived latency improves.
6. A service currently runs on three EC2 instances behind an Application Load Balancer with a fixed desired count. Describe how you would convert it to an elastic architecture, naming the specific components, the health-check configuration, and the scaling policy you would select, and justify each choice.
7. Compare ECS on Fargate with ECS on EC2 across cost, security isolation, operational overhead, task density, and support for GPU and DaemonSet-style workloads. State the conditions under which each becomes the correct choice.
8. Explain the full sequence of events, including control-plane and data-plane actions, that occurs between an `UpdateService` API call with a new task definition and the point at which all traffic reaches the new version under a rolling deployment with `minimumHealthyPercent` 100 and `maximumPercent` 200.
9. An EKS cluster's pods must call Amazon S3. Describe the IRSA mechanism end to end  the OIDC provider, the IAM trust policy, the ServiceAccount annotation, and the token projection  and explain why this is superior to attaching permissions to the node instance role.
10. A team reports that their Lambda function occasionally returns duplicate results to downstream systems. Explain the delivery semantics involved for asynchronous invocation and for an SQS event source, and describe how you would make the function idempotent.
11. Design a compute architecture for a global video-streaming platform's metadata API. It must serve 50,000 requests per second at peak with a p99 latency budget of 100 milliseconds, tolerate the loss of a full Availability Zone with no capacity degradation, deploy 30 times per day with automatic rollback, and minimise cost. Specify the compute model, the scaling strategy, the deployment strategy, the purchasing model, and the failure domains, and justify every choice against a stated alternative you rejected.
12. A monolithic Java application currently runs on eight large EC2 instances at 20 percent average CPU utilisation with sharp quarter-end peaks. Propose a migration path across at least three stages, from rehosting through containerisation to selective serverless decomposition. For each stage, state what it costs, what it improves, what new failure modes it introduces, and what would justify stopping at that stage rather than continuing.
13. Critically evaluate the claim that "serverless is always cheaper". Construct a quantitative crossover argument comparing AWS Lambda against ECS on Fargate for a workload of average duration 200 milliseconds and 512 MB of memory. Identify the approximate request rate at which the continuously provisioned container becomes cheaper, state your assumptions explicitly, and then explain why the purely financial crossover is not by itself sufficient grounds for the architectural decision.
14. An organisation runs a stateful, latency-sensitive trading engine that requires sub-millisecond inter-node communication, cannot tolerate noisy neighbours, and must satisfy a regulatory requirement for hardware isolation and detailed audit evidence. Design the compute layer, addressing placement groups, instance tenancy, enhanced networking with Elastic Fabric Adapter or SR-IOV, IMDS hardening, and the observability and audit trail required. Explain which cloud-native principles you are deliberately sacrificing and why that sacrifice is defensible here.
15. Design the control loop for a multi-tenant SaaS platform in which each tenant's workload must be isolated, tenants have wildly different load profiles, and the platform must scale from 10 to 10,000 tenants without a linear increase in operational effort. Compare a pool model (shared compute, logical isolation), a silo model (dedicated compute per tenant), and a hybrid bridge model. Address noisy neighbours, blast radius, cost attribution per tenant, deployment strategy, and the specific AWS compute primitives you would use for each model.

## 1.4 : AWS storage Service

1. Define object storage, block storage, and file storage, and name the primary AWS service that implements each. For each, give one workload that suits it and one that does not.

2. A colleague states that "S3 buckets contain folders". Explain why this is inaccurate, describe what the S3 console is actually displaying, and state one practical consequence of the misunderstanding.

3. What is the difference between durability and availability? Give an example of a situation in which data is fully durable but temporarily unavailable.

4. An EBS volume was created in `us-east-1a`. Can it be attached to an EC2 instance in `us-east-1b`? Justify your answer with reference to how EBS replication works, and explain how you would move the data to another Availability Zone.

5. List the four Block Public Access settings conceptually and explain why AWS enables them by default on new buckets. What alternative should be used to serve public web content?

6. A bucket holds four hundred terabytes of application logs. Recent logs are queried daily for two weeks, then almost never, but must be retained for seven years for audit. Design a lifecycle configuration, justify each transition point, and identify the risk if the objects were on average only 20 KiB in size.

7. Compare gp2 and gp3 across price, performance model, maximum IOPS, maximum throughput, and burst behaviour. Explain why gp3 is generally the better default and describe the operational steps needed to migrate an in-use gp2 volume.

8. An EC2 instance cannot mount an EFS file system and the `mount` command hangs. Produce a systematic diagnostic checklist in the order you would work through it, explaining what each check rules out.

9. Explain what a presigned URL is, how it is validated by S3, and why using presigned URLs for uploads is architecturally superior to routing uploads through an application tier. State two security controls you would apply to presigned URL issuance.

10. A team enabled S3 versioning six months ago and is now surprised that storage costs have tripled while the visible object count is unchanged. Explain the likely causes and write the lifecycle rules that would bound the cost without losing recent recoverability.

11. Design the complete storage layer for a multi-tenant SaaS platform serving five thousand tenants, each storing documents. Address tenant isolation, encryption and key strategy, cost control, backup and ransomware resilience, and the Recovery Point and Recovery Time Objectives. Justify why you did or did not create one bucket per tenant.

12. A financial services firm must run a PostgreSQL database on EC2 sustaining 80,000 IOPS at sub-millisecond latency, survive the loss of an Availability Zone with a Recovery Point Objective of one minute, and retain regulatory records immutably for seven years. Produce an architecture covering the volume type and sizing, the instance selection constraint, the replication mechanism, the backup strategy, and the archival control. Explain each trade-off you accept.

13. An EKS platform hosts both stateless web services and a stateful analytics workload. Explain how the EBS and EFS CSI drivers differ in access mode, provisioning behaviour, and scheduling implications. Describe the failure mode that occurs when an EBS-backed pod cannot be scheduled in its volume's Availability Zone, and design around it.

14. A machine learning team's training jobs are bottlenecked reading a fifty-terabyte dataset from S3 across two hundred instances. Analyse where the bottleneck could be — client concurrency, prefix partitioning, instance network capacity, or storage throughput — and describe how you would measure each. Then propose a solution and explain why the durable system of record should remain S3.

15. Your organisation's monthly AWS bill shows storage costs growing twenty percent per quarter while data volume grows only five percent. Design a systematic investigation using Storage Lens, S3 Inventory, Cost Explorer, and Trusted Advisor. Identify at least six specific, distinct sources of waste you would expect to find, and give the remediation for each. State which remediations are safe to automate and which require human judgement.

## 1.5 AWS database Service

1. Define ACID and explain what each property guarantees. Give one example of an application requirement that depends on each.
2. Explain the difference between a partition key and a sort key in Amazon DynamoDB, and give an example of an access pattern that requires both.
3. What is a read replica, and how does it differ from a Multi-AZ standby in an Amazon RDS instance deployment? State one requirement that each is designed to satisfy.
4. Describe the cache-aside pattern in sequence. What happens on a cache hit, and what happens on a cache miss?
5. An RDS instance is created with a backup retention period of zero. Explain precisely what capability is lost and why this is dangerous in production.
6. A DynamoDB table stores events with `event_type` as the partition key across five possible values, and the application reports throttling despite generous provisioned capacity. Explain the cause in terms of DynamoDB's internal partitioning, then propose two distinct remedies and state the trade-off of each.
7. Calculate the read and write capacity units required for the following workload, showing your reasoning: 1,200 strongly consistent reads per second of items averaging 7 KB, and 400 writes per second of items averaging 2.5 KB. Then state how the read requirement changes if eventually consistent reads are acceptable.
8. Compare RDS Multi-AZ, RDS read replicas, and Aurora replicas across purpose, consistency, failover behaviour, replication mechanism, and typical lag. Identify the single most important architectural difference that Aurora's storage design produces.
9. An AWS Lambda function scaling to 800 concurrent executions exhausts connections to an Aurora PostgreSQL cluster. Explain the mechanism of the failure and design a complete remedy addressing connection management, blast-radius containment, and failover behaviour.
10. Explain the thundering-herd problem in caching. Describe three distinct mitigations and explain the circumstances under which each is preferable.
11. Design the complete data architecture for a global e-commerce platform serving customers in North America, Europe, and Asia. It must guarantee that orders and payments are transactionally correct, serve product catalogue reads at under 20 milliseconds p99 in all three regions, support full-text product search, retain seven years of order history for audit, and survive the loss of an entire AWS Region. Specify every data store, justify each against a stated rejected alternative, identify precisely where eventual consistency is introduced, and explain how the design prevents that eventual consistency from producing an incorrect financial outcome.
12. A DynamoDB single-table design must support the following access patterns: retrieve a customer by identifier; list a customer's orders newest first; retrieve an order with all its line items in one request; list all orders in a given status placed in the last 24 hours; and retrieve the ten highest-value orders for a customer. Design the complete key schema, including partition key, sort key, and any secondary indexes with their projections. Justify each index, identify which patterns are eventually consistent, and explain what you would do differently if a sixth pattern — arbitrary full-text search across order notes — were added.
13. Critically evaluate the claim that "DynamoDB is cheaper than Aurora". Construct a quantitative comparison for a workload of 5,000 reads and 500 writes per second on items averaging 3 KB, with 2 TB of stored data. State every assumption explicitly, identify the conditions under which each service wins, and then explain why the financial comparison alone is insufficient grounds for the architectural decision.
14. A financial institution requires a ledger that is auditable, tamper-evident, strictly ordered, and able to sustain 20,000 appends per second, with the ability to reconstruct account balances at any historical instant. Design the persistence layer using an event-sourcing approach. Address the choice of store, the key schema or table design, optimistic concurrency control, snapshotting strategy, the read model and how it is maintained, retention and archival to S3, encryption and key management, and the audit trail. Identify the specific failure modes your design accepts and explain why they are tolerable.
15. An organisation operates 40 microservices, each with its own database, and finds that cross-service reporting has become impossible without querying production databases directly, which is degrading them. Design a solution that restores analytical capability without coupling services or affecting production performance. Address change-data capture, the landing and transformation layers, schema evolution across 40 independently versioned services, data freshness expectations, cost, governance, and how you would prevent the analytical layer from becoming a new form of coupling between the services.

## 1.6 AWS Network Services

1. Explain, in your own words, the difference between a public subnet, a private subnet, and an isolated subnet. For each, state exactly what appears in its route table.

2. A subnet is created with CIDR `10.30.4.0/24`. List every address that cannot be assigned to a resource, and state the purpose of each. How many addresses remain usable?

3. You create a new security group and attach it to an EC2 instance in a public subnet. The instance has a public IP address. Without adding any rules, can you (a) SSH to the instance from the internet, and (b) run `yum update` from the instance? Explain both answers in terms of default security group behaviour.

4. State three differences between a security group and a network ACL, and give one situation in which only a network ACL can satisfy the requirement.

5. An application in a private subnet must download objects from Amazon S3. Compare routing this traffic through a NAT Gateway with using a Gateway endpoint, in terms of cost, security, and the network path taken.

6. A VPC is allocated `10.40.0.0/16`. Design a subnet plan for **three** Availability Zones containing a public tier (`/24` each), a private application tier (`/20` each), and an isolated data tier (`/22` each), leaving at least half the VPC unallocated for future growth. Write out every CIDR block, confirm that none overlap, and state how many usable addresses each private application subnet provides.

7. A team enables a custom network ACL on a subnet with inbound allow for TCP 443 and outbound allow for TCP 443. All HTTPS requests to the web servers now time out. Explain precisely why, identify the missing rule including its port range and direction, and explain why the same problem does not occur with security groups.

8. Compare the seven Route 53 routing policies. For each of the following requirements, choose one policy and justify it: (a) 10 percent of users should reach a new version; (b) European users must be served only from a European Region for data-protection reasons; (c) users worldwide should get the fastest response; (d) if the primary Region fails, serve a static maintenance page from S3.

9. An HTTP API using a Lambda authorizer shows a p50 latency of 320 milliseconds, of which 140 milliseconds is the authorizer invocation. Describe three changes that would reduce this, and state the trade-off each one introduces.

10. Your organisation has eight VPCs across three accounts, all of which must communicate, plus a requirement to reach an on-premises data centre. Compare VPC peering and Transit Gateway for this case quantitatively (number of connections, number of route entries, cost dimensions) and recommend one with justification.

11. An EKS cluster must support 15,000 concurrent pods using the Amazon VPC CNI. The VPC is currently `10.50.0.0/16` with three private subnets of `/20` each. Calculate whether the current address space is sufficient, accounting for the CNI's warm-address behaviour and for cluster growth. If it is not, design a remediation using secondary CIDR blocks, CNI custom networking, and prefix delegation, and explain the trade-offs of each technique.

12. Design a multi-Region active-active architecture for an API that must maintain availability during the complete loss of one Region, with a recovery time objective under 60 seconds. Specify the DNS strategy, the health-check strategy, the data-replication implication, and explain why your failover mechanism does not depend on any control plane in the failed Region. Justify your choice between Route 53 failover, Route 53 latency routing with health checks, and AWS Global Accelerator.

13. A financial services organisation requires that (a) no workload subnet has any route to the internet, (b) all outbound traffic from 30 VPCs is inspected by a stateful firewall with domain-name filtering, (c) each business unit's VPCs cannot reach another business unit's VPCs, and (d) all of this must be auditable. Design the network. Name every component, describe the Transit Gateway route-table structure, explain how egress inspection is enforced, and describe the evidence you would produce for an auditor.

14. Your API Gateway front end can accept 10,000 requests per second, but the downstream relational database supports 400 concurrent connections and the business requires that no request be lost. Design the complete request path including back-pressure, and calculate the queue-depth and worker-concurrency implications if a five-minute burst arrives at 10,000 requests per second while workers drain at 400 per second. State what the client experiences at each stage.

15. An organisation's monthly bill shows large charges for `NatGateway-Bytes`, `DataTransfer-Regional-Bytes`, and `PublicIPv4:InUseAddress`. Describe a systematic investigation using VPC Flow Logs, Athena, and Cost Explorer, then propose a remediation for each of the three charges. For each remediation, state the new cost it introduces and the conditions under which the change would **not** be worthwhile.

## 1.7 Cloud Native Design Pattern

1. Define cloud-native and explain why simply moving a virtual machine to EC2 does not make an application cloud-native.
2. List three characteristics of serverless computing and give one AWS service that exemplifies each.
3. What is the difference between SNS and SQS? Give a scenario appropriate to each.
4. Explain what an event is in an event-driven architecture and how it differs from a command.
5. What does "API-first" mean, and name two artefacts produced before any implementation code is written.
6. Explain what a cold start is, three factors that influence its duration, and two mitigation strategies with their cost implications.
7. A microservice needs to call three other services to build a response. Describe two design changes that would reduce user-perceived latency and improve resilience.
8. Compare choreography and orchestration for a five-step order-fulfilment process. Which would you choose and why?
9. Explain why event consumers must be idempotent, and describe an implementation using DynamoDB conditional writes.
10. Your SQS visibility timeout is 30 seconds and your consumer sometimes takes 45 seconds. Describe precisely what goes wrong and how to fix it.
11. Design a multi-tenant SaaS platform on AWS where tenants have different throughput tiers and no tenant may degrade another's performance. Address API throttling, compute isolation, data isolation, observability per tenant, and cost attribution. Justify every choice against the Well-Architected pillars.
12. A payment system must move funds between two microservices that own separate databases. ACID transactions are impossible. Design a solution using the Saga pattern, specify compensating actions, explain how you guarantee the event is published if and only if the database write succeeds, and describe how you would prove correctness to an auditor.
13. An organisation with 45 microservices reports that deployment frequency has dropped and incidents take an average of four hours to diagnose. Diagnose the likely architectural and organisational causes, and propose a prioritised twelve-month remediation plan.
14. Evaluate serverless versus containers for a workload of 400 million requests per month, average duration 180 ms, average memory 512 MB, with a strict p99 latency requirement of 100 ms. Show your reasoning on cost, latency, and operational burden, and state what additional information you would need to make a final recommendation.
15. Design an event-driven data platform ingesting 200,000 IoT telemetry events per second that must support real-time alerting (sub-second), hourly aggregation, and ad-hoc historical analysis over two years of data. Specify the services, partitioning strategy, storage tiers, failure handling, and cost controls.

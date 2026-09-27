# Unit 8: Practice Questions

## 8.1 AWS Identity and Access Management

### 8.1.1 IAM Users, Groups, and Roles

#### Beginner Questions

1. List three tasks that require the root user and three measures that protect it.
2. What are the three components of temporary credentials and what does each do?
3. Explain the difference between an instance profile and a role.
4. What is a service-linked role, and why can you not edit its permissions?
5. Why should IAM users no longer be used for most human access?

#### Intermediate Questions

1. Write a trust policy that allows only the `orders-api` service account in namespace `orders` of one EKS cluster to assume a role through IRSA.
2. Compare IRSA and EKS Pod Identity in terms of trust principal, reuse across clusters and session tags.
3. Describe a safe procedure to rotate an access key used by a third-party tool without downtime.
4. Explain how IAM Identity Center permission sets become roles in member accounts, and how a developer obtains CLI credentials.
5. Explain role chaining and its effect on session duration.

#### Advanced Questions

1. Design identity for a multi-tenant SaaS where tenant workloads must never access another tenant's data in shared DynamoDB tables and S3 buckets, using session tags and token vending.
2. Evaluate the security of a trust policy granting `arn:aws:iam::444455556666:root` access to a production deployment role, and propose a tighter design.
3. An IdP outage prevents all sign-in to AWS during a production incident. Design break-glass access that remains secure and auditable.
4. Explain how source identity and session names allow an investigator to trace an action performed by a Lambda function back to the engineer who deployed it through GitHub Actions.
5. Compare IAM Roles Anywhere, long-lived access keys and a VPN to an EC2-hosted proxy for giving on-premises servers access to S3, considering security, operations and failure modes.

### 8.1.2 IAM Policies and Permissions

#### Beginner Questions

1. Name the six main elements of a policy statement and explain each.
2. What is the difference between an implicit deny and an explicit deny?
3. Give two examples of resource-based policies used earlier in DSO303.
4. Why should customer managed policies generally be preferred over inline policies?
5. What does the IAM Policy Simulator do?

#### Intermediate Questions

1. Write a policy that allows `ec2:StartInstances` and `ec2:StopInstances` only on instances tagged `owner` equal to the caller's `owner` principal tag.
2. Explain how a permissions boundary and an identity policy combine, with an example that yields no effective permissions.
3. Explain why `iam:PassRole` is considered a privilege escalation risk and how to restrict it.
4. Describe how IAM Access Analyzer policy generation works and its limitations.
5. Write a statement that denies all actions outside `ap-south-1` and `us-east-1` except for global services, and explain the role of `NotAction`.

#### Advanced Questions

1. Trace the full evaluation of a request by a role in account A, with a boundary and a session policy, to a KMS-encrypted SQS queue in account B with an RCP, listing every policy that must allow.
2. Design a policy-as-code pipeline for IAM that combines validation, custom checks, simulation and human review, and discuss false positives and negatives.
3. Evaluate the risks of ABAC in a multi-tenant SaaS and propose controls that make it robust.
4. Explain how automated reasoning allows Access Analyzer to prove that a bucket is not public, and what classes of access it cannot reason about.
5. A security team proposes replacing all resource-based policies with role assumption for cross-account access. Evaluate the proposal considering auditability, permissions loss when assuming roles, service support and operational complexity.

### 8.1.3 AWS Organizations and Service Control Policies

#### Beginner Questions

1. What are the management account, member accounts, the root and OUs?
2. Name four benefits of a multi-account strategy.
3. What is consolidated billing and how does it save money?
4. What does `FullAWSAccess` do, and why is it attached by default?
5. Name three core accounts in a landing zone and their purposes.

#### Intermediate Questions

1. Explain SCP inheritance with an example of three levels and compute the effective maximum permissions.
2. Compare deny-list and allow-list SCP strategies and state when each is appropriate.
3. Describe Control Tower preventive, detective and proactive controls, and the AWS mechanism behind each.
4. Explain how delegated administrators reduce risk to the management account.
5. Write an SCP that prevents deletion of AWS Backup vaults and recovery points except by a named backup administrator role.

#### Advanced Questions

1. Design a complete data perimeter using SCPs, RCPs, resource policies and VPC endpoint policies, identify the exceptions needed for AWS services and third parties, and describe a safe rollout.
2. Evaluate the trade-offs between Control Tower and a custom Terraform-based landing zone for an organisation with strict regulatory requirements.
3. Explain how declarative policies differ from SCPs in enforcement point and robustness to new APIs, using IMDSv2 as an example.
4. A merger requires moving 50 accounts from another organisation into yours. Plan the migration, including billing, guardrails, identity, logging and risks.
5. Critically assess the statement "SCPs make IAM least privilege unnecessary".

---

## 8.2 Network Security

### 8.2.1 VPC Design and Security Groups

#### Beginner Questions

1. Explain the difference between north-south and east-west traffic, and give one AWS control for each.
2. Why should the default security group in every VPC have no rules?
3. List three reasons Session Manager is preferred over a bastion host.
4. What does it mean for a security group to reference another security group, and why is this better than using a CIDR block?
5. Name two AWS services that can filter outbound traffic by domain name.

#### Intermediate Questions

1. Write the communication matrix and the security group rules for a service with an ALB, an ECS API, an ElastiCache cluster and an Aurora database.
2. Explain how an S3 gateway endpoint policy and an S3 bucket policy with `aws:SourceVpce` together prevent two different exfiltration scenarios.
3. Describe the three deployment models for AWS Network Firewall and one situation in which each is the best choice.
4. Explain why removing a security group rule may not terminate an attacker's existing connection, and what to do instead.
5. Compare Firewall Manager security group policies, AWS Config rules and Security Hub controls: what does each contribute to governance?

#### Advanced Questions

1. Design a multi-account network for an organisation with 200 accounts that must prevent any workload account from creating internet paths, centralise egress with domain filtering, and allow selected services to be shared across accounts. Justify each control.
2. Evaluate the security and operational trade-offs of fail-open versus fail-closed DNS Firewall configuration for a payment platform and for an internal analytics platform.
3. Propose a micro-segmentation strategy for an EKS cluster hosting 60 microservices from 10 teams, combining NetworkPolicy, security groups for pods and VPC Lattice or a service mesh. Address operational ownership and testing.
4. Critically assess the claim "our workloads are in private subnets, so they are secure". Identify at least five attack paths that remain and the controls that close them.
5. Design an automated pipeline that proves, before every deployment, that no path exists from the internet to any database and that no workload can reach buckets outside the organisation. Name the tools and the tests.

### 8.2.2 Network ACLs and VPC Flow Logs

#### Beginner Questions

1. What is the difference between a stateful and a stateless firewall, and which AWS control is each?
2. Why must NACL deny rules have lower numbers than the allow rules they override?
3. Name the three possible destinations for VPC Flow Logs and one advantage of each.
4. What does a `tcp-flags` value of 2 indicate?
5. List three kinds of traffic that VPC Flow Logs do not record.

#### Intermediate Questions

1. Write the steps of a containment runbook for an instance communicating with a command-and-control server, and justify the order.
2. Explain the benefits of Parquet, Hive-compatible prefixes and hourly partitions for security queries on Flow Logs.
3. Compare GuardDuty, Detective and Security Lake: what does each do with network telemetry?
4. Design a NACL rule numbering convention and explain how it supports incident response.
5. Explain how `pkt-srcaddr` helps identify the internal host responsible for traffic seen leaving through a NAT gateway.

#### Advanced Questions

1. Design a "hunting as code" programme for network telemetry: which queries, how they are scheduled and versioned, how results become findings, and how false positives are managed.
2. Evaluate the risks of fully automated containment for GuardDuty findings in a production e-commerce platform and propose a tiered automation policy.
3. Design protection for the log archive such that neither a compromised workload account administrator nor a compromised security-team engineer can delete network evidence within the retention period.
4. A regulator requires packet capture for all traffic in a cardholder data environment. Evaluate Traffic Mirroring, Network Firewall and third-party appliances behind GWLB for this requirement, including cost and scale.
5. Explain how detection latency is composed from a malicious connection to a containment action using Flow Logs and GuardDuty, and propose design changes to reduce it.

### 8.2.3 AWS WAF and Shield for Application Protection

#### Beginner Questions

1. List five AWS resource types that can be associated with an AWS WAF web ACL, and two that cannot.
2. What is the difference between the Block and Count actions?
3. What does AWS Shield Standard protect against, and what does it cost?
4. Why must CloudFront-scope web ACLs be created in `us-east-1`?
5. Name three AWS Managed Rules rule groups and what each protects against.

#### Intermediate Questions

1. Explain how labels and rule action overrides allow a false positive to be fixed without disabling a managed rule entirely.
2. Design rate-based rules for a public API with anonymous search, authenticated checkout and a login endpoint.
3. Explain WCUs and describe what happens when a web ACL exceeds its base capacity.
4. Describe three methods to prevent attackers from bypassing CloudFront to reach an ALB origin, and compare their strength.
5. Explain how Shield Advanced uses Route 53 health checks and why they matter.

#### Advanced Questions

1. Build a cost-benefit case for or against Shield Advanced for a mid-sized e-commerce company with USD 2 million monthly online revenue, considering attack likelihood, downtime cost, scaling costs, SRT value and included WAF charges.
2. Design a layered defence against a large credential stuffing campaign using residential proxies, combining WAF, Cognito or application controls, and monitoring, and describe how you would measure effectiveness.
3. Critically evaluate the claim "we have a WAF, so we are protected against the OWASP Top 10".
4. A zero-day vulnerability in a widely used web framework is announced on a Friday evening. Describe how your organisation uses WAF, Firewall Manager and automation to virtually patch 80 applications within hours, and how you validate the protection.
5. Design an automated feedback loop from GuardDuty, WAF logs and Shield events to WAF IP sets and rules, including safeguards against blocking legitimate users and against unbounded growth of block lists.

---

## 8.3 Data Protection and Encryption

### 8.3.1 Encryption at Rest with AWS KMS

#### Beginner Questions

1. What is the maximum plaintext size for the KMS `Encrypt` API, and what technique is used for larger data?
2. Name the three ownership types of KMS keys.
3. What two values does `GenerateDataKey` return, and what should be done with each?
4. What is the range of the deletion waiting period for a KMS key?
5. State one benefit of SSE-KMS over SSE-S3.

#### Intermediate Questions

1. Write a key policy statement that allows a role to decrypt only through Amazon S3 in one Region.
2. Explain why EBS uses grants and how the `kms:GrantIsForAWSResource` condition enables this safely.
3. Compare automatic rotation, on-demand rotation and alias-based manual rotation, including which key types support each.
4. Explain how S3 Bucket Keys reduce cost and what changes in CloudTrail when they are enabled.
5. Describe the permissions required for an S3 bucket with SSE-KMS to send notifications to an encrypted SQS queue.

#### Advanced Questions

1. Design a multi-tenant encryption scheme for 5,000 tenants that supports tenant-level audit and tenant offboarding, comparing key-per-tenant with shared key plus encryption context in cost, quota and security.
2. A regulator requires that the cloud provider can never decrypt customer data. Evaluate standard KMS, CloudHSM key store, external key store and client-side encryption against this requirement and against availability.
3. Design a disaster recovery strategy for encrypted RDS, S3 and client-side encrypted DynamoDB data across two Regions, stating where multi-Region keys are and are not needed.
4. An attacker obtained an access key for a developer role for six hours. Describe how you would use CloudTrail KMS events to determine exactly which data was exposed.
5. Critically evaluate the claim "all our data is encrypted, therefore it is secure".

### 8.3.2 Encryption in Transit with AWS Certificate Manager

#### Beginner Questions

1. What is the difference between TLS 1.2 and TLS 1.3 in handshake round trips?
2. In which Region must a certificate for CloudFront be requested?
3. Name two validation methods for ACM public certificates.
4. What does HSTS instruct a browser to do?
5. Which metric reports the remaining validity of an ACM certificate?

#### Intermediate Questions

1. Compare TLS termination, re-encryption and passthrough on AWS load balancers.
2. Explain ALB mTLS verify mode and passthrough mode.
3. Write a bucket policy statement that denies non-TLS requests.
4. Explain when AWS Private CA is required instead of ACM public certificates.
5. Describe how to monitor imported certificates that ACM cannot renew.

#### Advanced Questions

1. Design end-to-end encryption for CloudFront, ALB, ECS and Aurora, stating the certificate source and TLS policy at each hop.
2. Evaluate VPC Lattice, ECS Service Connect and Istio for service-to-service encryption and identity in a mixed ECS and EKS estate.
3. Explain the operational impact of shrinking public certificate validity periods and how to prepare an organisation for it.
4. Design a private PKI hierarchy with AWS Private CA for 50 accounts, including sharing, revocation and short-lived certificates.
5. Discuss whether TLS termination at a managed load balancer satisfies a requirement that "no third party may see plaintext", and propose alternatives.

### 8.3.3 Secrets Management with AWS Secrets Manager

#### Beginner Questions

1. Why should secrets not be stored in source code or plain environment variables?
2. What is the maximum size of a Secrets Manager secret?
3. Name the four steps of a rotation Lambda function.
4. Which ECS role retrieves secrets referenced in the `secrets` field?
5. State one difference between Secrets Manager and Parameter Store Standard.

#### Intermediate Questions

1. Explain how RDS-managed master user passwords work and why they are preferable to a password in a template.
2. Describe the permissions needed to read a secret from another account.
3. Compare the Secrets Store CSI Driver with ASCP and External Secrets Operator on EKS.
4. Explain how the Parameters and Secrets Lambda Extension reduces latency and cost.
5. Design an EventBridge-based notification for failed rotations.

#### Advanced Questions

1. Design zero-downtime credential rotation for a high-throughput Aurora application using connection pooling and RDS Proxy.
2. Evaluate a centralised secrets account against per-account secrets for a 60-account organisation.
3. Propose a strategy to eliminate as many secrets as possible from a microservice platform, and justify which remain.
4. Design secret replication and failover for an active-passive multi-Region application, including rotation behaviour during failover.
5. Estimate the monthly Secrets Manager and KMS cost for 300 secrets, 5 replica Regions for 50 of them, and 20 million retrievals per month with and without caching, and discuss the results (state your pricing assumptions and verify them).

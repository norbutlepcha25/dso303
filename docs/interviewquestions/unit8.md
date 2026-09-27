# Unit 8: Interview Questions

## 8.1 AWS Identity and Access Management

### 8.1.1 IAM Users, Groups, and Roles

#### Conceptual Questions

!!! question "Explain the difference between an IAM user and an IAM role, and why AWS recommends roles for workloads and federation for humans."
    An IAM user is a permanent identity with long-term credentials (password and access keys) in one account. A role has permissions but no long-term credentials; trusted principals assume it through STS and receive temporary credentials that expire automatically. Roles remove the need to store secrets in workloads, limit the lifetime of stolen credentials, and enable cross-account access with explicit two-sided trust. Federation through IAM Identity Center lets humans use their corporate identity with MFA across all accounts, so joiners and leavers are handled once in the IdP rather than per account.

!!! question "What are the two policy documents that define a role, and what question does each answer?"
    The trust policy, a resource-based policy on the role, defines who may assume the role and under which conditions. The permissions policies, identity-based policies attached to the role, define what the role's sessions may do. A permissions boundary may additionally cap the maximum permissions. A caller in another account also needs its own identity policy allowing `sts:AssumeRole` on the role.

!!! question "Why is a group not a principal?"
    A group is only a container used to attach policies to many IAM users. Nobody authenticates as a group, so there are no group credentials and no group sessions. Requests are always made by a user or role session; policies attached to the user's groups are simply included when evaluating that user's requests. Consequently a group cannot appear in the `Principal` element of a resource-based or trust policy.

!!! question "Describe the confused deputy problem and the two AWS mechanisms that prevent it."
    A confused deputy is a privileged entity tricked into using its privileges for another party. For third parties assuming roles across many customers, an external ID unique to each customer, required by `sts:ExternalId` in the trust policy, stops one customer from directing the vendor to another customer's role. For AWS services acting on your behalf, `aws:SourceArn` and `aws:SourceAccount` conditions ensure the service acts only for your resources.

#### Scenario Questions

!!! question "A developer's pull request adds an access key and secret to a configuration file so a Lambda function can write to DynamoDB. How do you respond and redesign?"
    Reject the change, and if the key was ever pushed treat it as compromised: deactivate it, review CloudTrail for its use and delete it. Redesign so that the function's execution role has a policy allowing only the required DynamoDB actions on the specific table ARN, and create the boto3 client with no explicit credentials so that the SDK uses the execution role's temporary credentials injected by the Lambda runtime. Add secret scanning to the pipeline.

!!! question "An ECS Fargate task fails to start with an error retrieving a Secrets Manager secret, while another team's task starts but its code gets AccessDenied from S3. Which roles need changes?"
    The first failure occurs before the container starts, when the ECS agent injects secrets; the task execution role needs `secretsmanager:GetSecretValue` on the secret (and `kms:Decrypt` if a customer managed key is used). The second failure is in application code, so the task role needs the S3 permission on the specific bucket and prefix. Neither problem should be fixed by giving a single role broad permissions.

!!! question "A security review finds that a GitHub deploy role's trust policy checks only the audience claim. Explain the risk and the fix."
    With only `aud` checked, any workflow in any GitHub repository can request a token with audience `sts.amazonaws.com` and assume the role, because all GitHub tokens are issued by the same issuer. Add an exact `sub` condition naming the organisation, repository and branch or environment, for example `repo:org/app:environment:production`, and restrict permissions to what the deployment needs.

#### Architecture Questions

!!! question "Design human access for a company with 40 AWS accounts, an Okta directory, developers, operators and auditors."
    Enable IAM Identity Center in the organisation, connect Okta as the identity source with SAML and SCIM so users and groups synchronise automatically, and define permission sets such as Developer, ReadOnly, Operator and SecurityAudit with appropriate session durations. Assign Okta groups to permission sets on specific accounts: developers get Developer in development accounts and ReadOnly in production, operators get Operator in production, auditors get SecurityAudit everywhere. Enforce MFA in Okta. Maintain two break-glass IAM users with hardware keys in a dedicated account, monitored by alarms. Remove all other IAM users and use centralised root access management for member accounts.

!!! question "Design workload identity for a microservices platform running on EKS and Lambda with deployments from GitHub Actions."
    Each microservice on EKS receives its own IAM role associated with its Kubernetes service account through EKS Pod Identity, with trust conditions on the cluster ARN and account, and permissions limited to its own tables, queues and prefixes, possibly using ABAC on the Pod Identity session tags. Each Lambda function has its own execution role. GitHub Actions authenticates with OIDC to per-environment deploy roles whose trust policies require an exact repository and environment `sub`, and whose permissions allow only pushing to ECR, updating the relevant deployments and running CloudFormation with a separate execution role. All roles are defined in IaC and all activity is attributed through session names in CloudTrail.

#### Troubleshooting Questions

!!! question "A script assumes a role in another account and receives AccessDenied on sts:AssumeRole. What do you check?"
    Check that the target role's trust policy names the caller's principal or account and that its conditions (external ID, MFA, source identity, tags) are satisfied; check that the caller's own identity policy allows `sts:AssumeRole` on the exact role ARN; check that no SCP in either account denies `sts:AssumeRole` or the target account; check for a permissions boundary on the caller; confirm the role ARN and partition are correct; and if the role was just created, retry after allowing for eventual consistency.

!!! question "A long-running data migration using a chained role fails after exactly one hour with ExpiredToken. Why, and how do you fix it?"
    Role chaining limits the session to one hour regardless of the role's maximum session duration. Refresh credentials before expiry by re-assuming the role periodically (for example with a refreshable credentials provider in the SDK), or avoid chaining by assuming the target role directly from a base identity whose sessions can last longer, or run the migration on compute that has the role directly, such as an ECS task, so the platform refreshes credentials automatically.

### 8.1.2 IAM Policies and Permissions

#### Conceptual Questions

!!! question "State the order in which AWS evaluates policy types within a single account, and explain why an explicit deny cannot be overridden."
    AWS starts with an implicit deny, then checks all applicable policies for an explicit deny; if one matches, the request is denied. Otherwise RCPs and SCPs must allow, then a resource-based or identity-based policy must allow, and any permissions boundary and session policy must also allow. Explicit deny is final so that security teams can encode invariants (for example "never allow non-TLS access" or "never leave approved Regions") that no other policy author can weaken, which is the basis of layered governance.

!!! question "Which policy types grant permissions and which only limit them?"
    Identity-based policies (managed and inline), resource-based policies and ACLs can grant. Permissions boundaries, session policies, SCPs, RCPs and VPC endpoint policies never grant; they only define maximums, so an action must also be allowed by a granting policy.

!!! question "Compare RBAC and ABAC and explain why ABAC requires tag governance."
    RBAC grants permissions to roles per function, listing resources explicitly, so each new resource or team requires policy changes. ABAC grants permissions by matching principal tags to resource tags, so new tagged resources are covered automatically and the number of policies stays small. Because access follows tags, anyone who can change a tag can change access; ABAC must therefore deny unauthorised tag changes, require tags at creation and standardise tag keys and values.

#### Scenario Questions

!!! question "A Lambda function in account A must read objects from a bucket in account B. The function's role has an identity policy allowing s3:GetObject on the bucket, but it receives AccessDenied. What is missing?"
    Cross-account access requires both sides. Account B's bucket policy must allow the function's role ARN (or account A with further conditions) to perform `s3:GetObject` on the objects. Also check that no explicit deny in the bucket policy (for example a VPC endpoint or organisation condition) blocks the request, that SCPs in A and RCPs in B allow it, and that if the objects are encrypted with a customer managed KMS key, the key policy in B allows `kms:Decrypt` for the role and the role's identity policy allows it too.

!!! question "Developers ask for permission to create IAM roles for their Lambda functions without waiting for the platform team. How do you grant this safely?"
    Create a permissions boundary that allows only the services workloads need and denies IAM and organisation changes. Grant developers `iam:CreateRole` and related actions only on a workload path with the condition that `iam:PermissionsBoundary` equals the boundary ARN, restrict `iam:PassRole` to that path and to Lambda and ECS, and deny modification or removal of the boundary. Validate their policies in the pipeline. Any role developers create is capped by the boundary regardless of the policies they attach.

#### Architecture Questions

!!! question "Design a data perimeter for an organisation's sensitive S3 data accessed by ECS services in private subnets."
    Use identity controls (SCPs denying access to resources outside the organisation via `aws:ResourceOrgID`), resource controls (RCPs and bucket policies denying principals outside the organisation via `aws:PrincipalOrgID`, with exemptions for AWS service principals), and network controls (bucket policies requiring `aws:SourceVpce` for the ECS VPC's S3 endpoint and endpoint policies allowing only organisation buckets). Enforce TLS with `aws:SecureTransport`, encrypt with KMS keys whose key policies follow the same pattern, and monitor with Access Analyzer external access findings.

#### Troubleshooting Questions

!!! question "An engineer's role has AdministratorAccess but CreateBucket in eu-west-1 fails with an explicit deny in a service control policy. Explain."
    The engineer's identity policy grants the action, but an SCP attached to the account or an OU above it denies requests where `aws:RequestedRegion` is not in the approved list. SCPs limit even administrators in member accounts, and the explicit deny wins. The fix is either to use an approved Region or to change the organisation's Region policy through governance.

!!! question "A policy allows s3:ListBucket on arn:aws:s3:::reports/* and s3:GetObject on arn:aws:s3:::reports/*. Downloads work but listing fails. Why?"
    `ListBucket` is a bucket-level action whose resource is the bucket ARN `arn:aws:s3:::reports`, not the object ARN pattern. Add a statement for `ListBucket` on the bucket ARN, optionally restricted with the `s3:prefix` condition.

### 8.1.3 AWS Organizations and Service Control Policies

#### Conceptual Questions

!!! question "Explain why SCPs are said to never grant permissions, and what that means in practice."
    SCPs define the maximum permissions for principals in member accounts. An action allowed by an SCP is only available if an IAM policy in the account also allows it; an action denied or not allowed by an SCP is unavailable even if IAM policies allow it. In practice, attaching `FullAWSAccess` gives no one any access by itself, and removing an allow from an SCP removes the capability from everyone in affected accounts, including administrators and the root user.

!!! question "Compare SCPs and RCPs."
    SCPs limit what principals in member accounts can do, whichever resources they target. RCPs limit what can be done to resources in member accounts, whoever the caller is, including principals outside the organisation. Together they form the identity and resource halves of a data perimeter. Neither grants permissions, and neither applies to the management account or to service-linked roles.

!!! question "Why should the management account contain no workloads?"
    SCPs and RCPs do not apply to the management account, it controls billing and organisation policies, and it can create roles and access in every member account. A compromise or misconfiguration there has maximum impact and cannot be constrained by guardrails. Keeping it empty, tightly controlled and used only for governance minimises that risk; daily security administration should be delegated to a member account.

#### Scenario Questions

!!! question "An account administrator in a member account disabled CloudTrail logging to hide activity. How do you prevent this?"
    Create an organisation trail from the management account or a delegated administrator, which member accounts cannot modify, delivering to a Log Archive bucket with restricted access, encryption, Object Lock and log file validation. Add an SCP at the root denying `cloudtrail:StopLogging`, `cloudtrail:DeleteTrail` and `cloudtrail:UpdateTrail` except for the Control Tower or platform role. Alarm on attempts, which CloudTrail records as denied events.

!!! question "A team reports that after a new SCP was attached to the Workloads OU, Route 53 changes and IAM role creation fail in all accounts. What went wrong?"
    The SCP probably denies requests outside approved Regions without exempting global services. IAM, Route 53, Organizations, CloudFront and other global services are served from `us-east-1` and may be evaluated with a Region outside the list. Use `NotAction` to exempt global services, test on a pilot OU and validate before attaching to broad OUs.

#### Architecture Questions

!!! question "Design an OU structure and guardrail set for a university offering student sandbox accounts and running production learning platforms on AWS."
    Create a management account used only for billing, Organizations and Control Tower; a Security OU with Log Archive and Security Tooling accounts; an Infrastructure OU with network and shared services accounts; a Workloads OU split into Production and Non-production for the learning platforms; a Sandbox OU for students; and a Suspended OU. Apply root invariants (protect audit, deny leaving the organisation, deny root user actions, deny unapproved Regions). In Production add backup and deletion protections and a data perimeter. In Sandbox use an allow-list SCP of curated services, instance-type restrictions, a single Region and budgets with automated clean-up. Suspended accounts receive a deny-all SCP. Human access comes through Identity Center federated with the university directory.

#### Troubleshooting Questions

!!! question "A developer receives 'explicit deny in a resource control policy' when a partner account reads a shared bucket. What do you check?"
    The organisation's RCP likely denies S3 access by principals outside the organisation via `aws:PrincipalOrgID`. Confirm the partner is intended to have access, then add a narrowly scoped exception to the RCP (for example the partner's account ID in `aws:PrincipalAccount` for that bucket), keeping the bucket policy grant, and document the exception. Verify with Access Analyzer that no broader external access results.

---

## 8.2 Network Security

### 8.2.1 VPC Design and Security Groups

#### Conceptual Questions

!!! question "Explain why security groups are described as identity-based network policy, and why this matters in a containerised environment."
    A security group rule can name another security group as its source, which means "any ENI that is a member of that group" rather than a set of IP addresses. Membership is assigned by the orchestrator or launch configuration when an ECS task, EKS pod or instance starts. In a containerised environment, tasks and pods are replaced frequently and receive new IP addresses each time, so CIDR-based rules would either be constantly out of date or so broad that they permit everything. Group references remain correct under scaling and redeployment and express the intended relationship between services.

!!! question "Compare perimeter security and zero trust, and explain the role network controls still play in a zero trust design."
    Perimeter security trusts traffic based on network location once it is inside a boundary. Zero trust trusts no request because of location; each request is authenticated, authorised and encrypted using identity and context. Network controls remain valuable in zero trust because they reduce the attack surface, limit blast radius when an identity is compromised, block whole classes of attack such as scanning and exfiltration, and provide telemetry. They are one layer among several rather than the sole decision point.

!!! question "Why is DNS considered an exfiltration channel even in a subnet without an internet route, and which AWS controls address it?"
    The VPC's Route 53 Resolver performs recursive resolution of public names on behalf of instances, so queries for attacker-controlled domains leave the VPC even with no internet route. Data can be encoded in query names and received by the attacker's authoritative server. Route 53 Resolver DNS Firewall with managed threat lists, allow-lists and advanced tunnelling detection blocks such queries, Resolver query logs record them, and GuardDuty analyses DNS logs for exfiltration and command-and-control patterns.

#### Scenario Questions

!!! question "A security review finds that 40 of 120 security groups in production allow ingress from 10.0.0.0/8 on all ports. The teams say this was needed for microservices to communicate. How do you remediate without an outage?"
    Enable VPC Flow Logs (if not already) and analyse accepted flows to each group's members over several weeks to build the real communication matrix. Create one security group per service role and write rules referencing the calling services' groups on the observed ports. Attach the new groups alongside the old ones, then remove the broad rules service by service during low-traffic windows, monitoring error rates and REJECT records in Flow Logs. Codify the new groups in IaC, add a Config rule or Firewall Manager content audit policy forbidding broad internal CIDRs on all ports, and add Reachability Analyzer tests to the pipeline.

!!! question "An engineer wants to open SSH from the office IP range to a production EC2 instance to debug an issue. Propose a better approach and justify it."
    Use Session Manager (or EC2 Instance Connect Endpoint if the agent cannot run). It requires no inbound port and no public IP, authorises access through IAM policies that can require tags, MFA and time limits, records full session transcripts to S3 or CloudWatch Logs and records session start in CloudTrail. Office IP ranges change, can be shared by many people and do not identify an individual; SSH keys are hard to revoke. The Session Manager approach is more secure, auditable and needs no firewall change.

#### Architecture Questions

!!! question "Design network segmentation for a PCI DSS cardholder data environment within a larger AWS organisation."
    Place the cardholder data environment in dedicated production accounts in a separate organisational unit with SCPs denying creation of internet gateways, peering and changes to flow logs. Use a dedicated VPC connected to the rest of the estate only through a Transit Gateway route table that permits specific flows to and from an inspection VPC, or through VPC Lattice or PrivateLink services exposing only required APIs. Use tiered subnets with isolated data subnets, one security group per service referencing callers, explicit egress rules, and centralised egress through Network Firewall with domain allow-lists. Use S3 and KMS endpoint policies restricted to the organisation and bucket policies requiring the endpoints. Enable Flow Logs, Resolver query logs and Network Firewall logs to a log archive account with Object Lock. Use Firewall Manager to enforce baseline groups and Security Hub with the PCI DSS standard to report posture.

!!! question "Compare distributed and centralised deployment of AWS Network Firewall for a 50-VPC organisation, and recommend a design."
    Distributed deployment places firewall endpoints in every VPC and AZ, which is simple to route and avoids a shared dependency but multiplies endpoint-hour costs and relies on Firewall Manager for consistency. Centralised deployment routes traffic via Transit Gateway to an inspection VPC, reducing endpoint count and giving a single policy, at the cost of Transit Gateway data processing, appliance mode configuration and a shared failure domain. For most organisations, centralised egress and east-west inspection with local ingress inspection for high-volume internet-facing VPCs is recommended, with VPC endpoints to keep AWS API traffic off the inspection path.

#### Troubleshooting Questions

!!! question "After enabling a centralised inspection VPC, users report that about half of new HTTPS connections from workloads fail intermittently. What is the likely cause?"
    Asymmetric routing: the Transit Gateway sends the outbound and return packets of a flow to firewall endpoints in different AZs, and the stateful firewall that sees only one direction drops the flow. Enable appliance mode on the inspection VPC's Transit Gateway attachment, check that each AZ's Transit Gateway subnet routes to the firewall endpoint in the same AZ, and verify with Network Firewall flow logs and VPC Flow Logs that both directions traverse the same endpoint.

!!! question "An ECS task cannot connect to an Aurora database although the database security group allows port 5432 from the task's security group. What else do you check?"
    Check the task's security group egress rules, which may have had the default allow-all rule removed without adding the database. Confirm the task is actually using the expected security group in its service network configuration. Check NACLs on both subnets, including the ephemeral return range. Confirm routing between the subnets and that the database endpoint resolves to an address in the expected subnets. Use Reachability Analyzer from the task ENI to the database ENI, and look for REJECT records in Flow Logs.

!!! question "A NetworkPolicy denying all ingress to a namespace has been applied, yet pods in other namespaces can still reach it. Why?"
    NetworkPolicy objects are enforced only if the cluster's network plugin implements them. On EKS with the Amazon VPC CNI, network policy support must be enabled in the add-on configuration, and nodes must meet the kernel and platform prerequisites; otherwise the API server accepts the object but nothing enforces it. Alternatively a third-party engine such as Calico or Cilium must be installed. Also check that the policy's `podSelector` actually selects the target pods and that another policy does not allow the traffic.

### 8.2.2 Network ACLs and VPC Flow Logs

#### Conceptual Questions

!!! question "Why is a network ACL deny more effective than removing a security group rule when cutting off an attacker's active connection?"
    Security groups are stateful and track connections; removing the rule that allowed a tracked connection prevents new connections but does not necessarily interrupt an existing one, which continues until it closes or times out. NACLs are stateless and evaluate every packet against the rules; a deny rule matching the attacker's address drops the next packet in either direction, terminating established sessions immediately.

!!! question "Explain three security roles for which NACLs are well suited and two for which they are poorly suited."
    Well suited: enforcing tier invariants that application teams cannot override (for example data subnets never communicating with the internet), deny lists of a small number of known-bad CIDRs, and emergency containment or quarantine of a subnet. Poorly suited: per-service application policy, because NACLs cannot reference security groups and require explicit ephemeral port rules; and large or dynamic block lists, because the rule quota is small and changes affect the whole subnet.

!!! question "Why does GuardDuty not depend on customers enabling VPC Flow Logs, and why is that design important?"
    GuardDuty obtains flow log and DNS data through an independent, duplicated stream from AWS rather than from the customer's configured flow logs. This means detection works even in accounts where flow logs were never enabled, and an attacker who gains permission to delete a customer's flow log configuration cannot blind GuardDuty by doing so. It also avoids GuardDuty imposing log storage costs on customers.

!!! question "Which Flow Log custom fields would you add for security analysis, and what question does each help answer?"
    `tcp-flags` distinguishes connection attempts from sessions and reveals scans; `pkt-srcaddr` and `pkt-dstaddr` reveal the true hosts behind NAT gateways and load balancers; `flow-direction` separates inbound from outbound for exfiltration analysis; `traffic-path` shows whether egress went through an internet gateway, NAT gateway or endpoint; `pkt-dst-aws-service` identifies AWS service traffic; `vpc-id`, `subnet-id` and `instance-id` attribute flows without inventory joins; ECS fields attribute flows to services and tasks; `reject-reason` explains rejections such as Block Public Access.

#### Scenario Questions

!!! question "GuardDuty reports CryptoCurrency:EC2/BitcoinTool.B on an instance in an Auto Scaling group behind an ALB. Describe your response."
    Automatically or manually: tag the instance, move it to standby or detach it from the Auto Scaling group and deregister it from the target group so it receives no traffic and is not terminated, replace its security groups with an isolation group, add NACL deny rules for the mining pool addresses if connections must be cut immediately, and snapshot its volumes (and capture memory if the capability exists). Investigate with Detective and Flow Logs to find the initial access vector and any lateral movement. Rebuild from a known-good image, fix the vulnerability, rotate any credentials the instance could access, and add DNS Firewall blocks for mining domains organisation-wide.

!!! question "An auditor asks you to prove that no database in production was reachable from the internet during the last 12 months. What evidence can you produce?"
    Preventive evidence: Config configuration history for database security groups, route tables and NACLs showing no internet routes or open rules; Security Hub control history; Network Access Analyzer findings; SCPs preventing internet gateways in database accounts. Detective evidence: Athena queries over 12 months of Flow Logs in the log archive showing no accepted ingress from non-private addresses to database ENIs, with Object Lock demonstrating that the logs could not have been altered.

#### Architecture Questions

!!! question "Design an organisation-wide network logging and detection architecture for 150 accounts."
    Enable VPC-level Flow Logs with a standard custom format, Transit Gateway Flow Logs, Resolver query logs, and Network Firewall logs, all delivered to a log archive account S3 bucket in Parquet with hourly partitions, SSE-KMS, Object Lock and lifecycle rules. Deploy these with StackSets or Firewall Manager-style automation and enforce with Config rules and SCPs. Enable GuardDuty with a delegated administrator in the security tooling account, auto-enabled for new accounts in all Regions, and Detective for investigation. Optionally enable Security Lake for OCSF normalisation and SIEM subscribers. Aggregate findings in Security Hub and route high-severity findings through EventBridge to automated containment and to the on-call team.

#### Troubleshooting Questions

!!! question "An Athena query over Flow Logs returns no rows for yesterday although traffic definitely occurred. What do you check?"
    Check that the partition values in the query match the Hive-compatible path format and projection configuration (for example two-digit months and days), that the table location and projection template point to the correct prefix, that the flow log was active and its `log-status` was not `NODATA` or `SKIPDATA`, that the relevant ENIs were in the logged VPC, and that the column names match the Parquet schema (underscores instead of hyphens). Also verify the Region and account partition values.

!!! question "After adding a NACL deny rule for an attacker's CIDR, the attack traffic continues. Why?"
    The deny rule may have a higher number than an allow rule that matches first; it may have been added in only one direction when the attacker is the destination of outbound connections; it may be on the wrong subnet's NACL, for example the application subnet while the target is the load balancer subnet; or the attacker may be arriving through a proxy or CDN so the source address is not the attacker's. For HTTP attacks through CloudFront or an ALB, the source addresses seen in the VPC are those of the edge or load balancer, and AWS WAF is the correct control.

### 8.2.3 AWS WAF and Shield for Application Protection

#### Conceptual Questions

!!! question "Explain the difference between terminating and non-terminating WAF actions and why Count mode is central to safe rollout."
    Terminating actions (Allow, Block, and CAPTCHA or Challenge when the client lacks a valid token) end rule evaluation and determine the outcome. Count is non-terminating: it records the match, adds labels, and evaluation continues. Deploying new rules or managed groups with a Count override lets engineers observe exactly which real requests would have been blocked, identify false positives from logs and sampled requests, and refine scope-down statements or label-based exceptions before enforcement, avoiding outages caused by the security control itself.

!!! question "Why are rate-based rules keyed on source IP insufficient against modern credential stuffing, and what alternatives exist in AWS WAF?"
    Credential stuffing campaigns distribute requests across very large pools of residential proxy IPs, so each IP sends few requests and stays below any per-IP limit that would not also block legitimate users behind shared NAT. Alternatives include Account Takeover Prevention, which examines submitted credentials against stolen credential databases and tracks login failure ratios; Bot Control targeted protections with browser interrogation and tokens; rate-based rules with custom keys such as JA3 or JA4 fingerprints, session cookies or header combinations; and CAPTCHA or Challenge actions.

!!! question "Compare Shield Standard and Shield Advanced."
    Shield Standard is free, automatic and protects all AWS resources from common layer 3 and 4 attacks, most strongly at CloudFront, Route 53 and Global Accelerator. Shield Advanced is a paid organisation-wide subscription with a one-year commitment that adds enhanced, resource-specific detection and mitigation for protected CloudFront distributions, Route 53 zones, Global Accelerator, ALBs, CLBs and Elastic IPs; automatic application-layer mitigation via WAF; health-based detection; protection groups; 24/7 Shield Response Team access; proactive engagement; cost protection for attack-driven scaling; WAF and Firewall Manager charges included for protected resources; and attack visibility.

!!! question "Which OWASP Top 10 categories can WAF meaningfully mitigate, and which require other controls?"
    WAF meaningfully mitigates Injection (SQLi and XSS rule groups), automated Identification and Authentication Failures (ATP, ACFP, rate limits), exploitation of Vulnerable and Outdated Components through virtual patching (Known bad inputs and platform groups), and parts of Broken Access Control, Security Misconfiguration and SSRF. Cryptographic Failures, Insecure Design, and Software and Data Integrity Failures require application design, encryption and supply chain controls. Security Logging and Monitoring Failures are addressed partly by WAF logs but mainly by the observability practices of Unit VII.

#### Scenario Questions

!!! question "After enabling the Core rule set in Block mode, customers report that uploading profile pictures fails with 403 errors. How do you fix this without removing protection?"
    Identify the matching rule in WAF logs or sampled requests; it is typically `SizeRestrictions_BODY`, because images exceed the body size rule. Override that single rule to Count in the managed group, and add a custom rule after it that blocks requests carrying its label unless the URI path is the upload endpoint, optionally combined with a size constraint appropriate for images. The rest of the Core rule set stays in Block, and the upload path remains protected by the other rules.

!!! question "A marketing campaign is expected to increase traffic tenfold. Last year an HTTP flood coincided with a campaign and took the site down. Design the protection."
    Place CloudFront in front of the application with aggressive caching of static and cacheable dynamic content and normalised cache keys. Attach a WAF web ACL with IP reputation, Anonymous IP (count and label), Core rule set, Bot Control scoped to dynamic paths, and rate-based rules set from measured baselines, plus the Anti-DDoS managed rule group where available. Cloak the origin with VPC origins or prefix lists and a secret header. Pre-scale or configure auto scaling with tested limits. Consider Shield Advanced for automatic layer 7 mitigation, SRT support and cost protection, with Route 53 health checks associated. Prepare a runbook, dashboards and alarms on WAF blocked requests and origin latency, and conduct a load test.

#### Architecture Questions

!!! question "Design application protection for a multi-account organisation with 80 public applications owned by different teams."
    Subscribe to Shield Advanced at the organisation level if the risk profile justifies it. Use Firewall Manager from a security administrator account with WAF policies scoped by OU and tags: a pre-process rule group containing central IP reputation, Known bad inputs and emergency block IP sets, a post-process rule group with a catch-all rate limit, and team-owned rules in between. Enable auto-remediation so every new CloudFront distribution, ALB and API Gateway stage is protected, and a Shield Advanced policy for automatic protection. Send all WAF logs through Firehose to the log archive and Security Lake, with dashboards per application. Use SCPs to prevent disassociation of Firewall Manager-managed web ACLs, and provide teams with an IaC module for their own rule groups.

#### Troubleshooting Questions

!!! question "A CloudFront web ACL created by an engineer does not appear when trying to associate it with a distribution. Why?"
    Web ACLs for CloudFront must be created with the `CLOUDFRONT` scope in the `us-east-1` Region. A web ACL created with `REGIONAL` scope, or in another Region, cannot be associated with a distribution. Recreate it with the correct scope and Region.

!!! question "A rate-based rule on the ALB's regional web ACL is blocking all users simultaneously. The ALB is behind CloudFront. What is wrong?"
    The rule aggregates by source IP, and behind CloudFront the source IP seen at the ALB is a CloudFront edge address shared by many users, so the aggregate count for a few addresses exceeds the limit and everyone behind them is blocked. Move the rate-based rule to the CloudFront web ACL, or configure the regional rule to use the forwarded IP from a header set by CloudFront (such as `X-Forwarded-For` with appropriate position settings), trusting it only because origin cloaking guarantees requests came through CloudFront.

!!! question "The monthly WAF bill has tripled although traffic has grown only 20 per cent. What do you check?"
    Check whether an intelligent threat mitigation rule group (Bot Control targeted, ATP or ACFP) was added without a scope-down, causing every request including static assets to be evaluated and charged. Check whether the web ACL exceeded its base WCU capacity or had its body inspection limit raised, which add per-request charges. Check CAPTCHA and Challenge volumes, new web ACLs created by automation or Firewall Manager, and logging volumes to CloudWatch Logs. Use Cost Explorer grouped by usage type to find the line item.

---

## 8.3 Data Protection and Encryption

### 8.3.1 Encryption at Rest with AWS KMS

#### Conceptual Questions

!!! question "Explain envelope encryption and why AWS services use it rather than sending data to KMS."
    Data is encrypted locally with a symmetric data key, and the data key is encrypted with a KMS key and stored with the ciphertext. KMS only handles small data keys, so it is not a bandwidth bottleneck, bulk encryption is fast and local, the long-term key never leaves the HSMs, rotation does not require re-encrypting data, and each data key decryption is an authorised, audited call. The `Encrypt` API is also limited to 4 KB, so bulk data could not be sent directly anyway.

!!! question "Why is the KMS key policy described as the primary access control, and what does the statement allowing `arn:aws:iam::ACCOUNT:root` actually do?"
    Unlike most AWS resources, a KMS key cannot be used by any principal unless its key policy allows it, directly or by delegation. The statement with the account principal delegates authority to the account, enabling IAM policies in that account to grant access. It does not restrict access to the root user. Without it, IAM policies have no effect and the key may become unmanageable.

!!! question "Compare AWS owned, AWS managed and customer managed keys."
    AWS owned keys are invisible, free and provide no audit or control. AWS managed keys live in your account with aliases `aws/service`, rotate yearly, are auditable in CloudTrail, but have fixed policies and cannot be shared across accounts. Customer managed keys are fully controlled: custom policies, cross-account sharing, configurable rotation, disabling and deletion, at a monthly cost.

!!! question "What is encryption context, and give three reasons to use it."
    Non-secret key-value pairs bound to ciphertext as additional authenticated data. It prevents ciphertext substitution between records, enables authorisation conditions (for example tenant isolation with `kms:EncryptionContext:tenantId`), and records which record or tenant was decrypted in CloudTrail.

!!! question "What happens to existing data when a KMS key is rotated, disabled, and deleted?"
    Rotation: existing ciphertext remains decryptable with the retained older material, new encryption uses new material. Disabling: all cryptographic operations fail until re-enabled; services that cached data keys may briefly continue. Deletion: after a 7–30 day waiting period, material is destroyed and all data under the key becomes permanently unrecoverable.

#### Scenario Questions

!!! question "A team must share nightly RDS snapshots with a separate backup account, but the share option fails. The database uses the `aws/rds` key. What is wrong and how is it fixed?"
    AWS managed keys cannot be used by other accounts because their key policies cannot be changed. Create a customer managed key whose policy allows the backup account, copy the snapshot re-encrypting it with that key, and share the copy. The backup account then copies it again under its own key so that it is independent of the source account. Going forward, create databases with customer managed keys, or use AWS Backup cross-account copy.

!!! question "After enabling SSE-KMS on a data lake bucket read by Athena, the KMS bill rises sharply and some queries fail with throttling. What do you do?"
    Enable S3 Bucket Keys, which dramatically reduce `Decrypt` and `GenerateDataKey` calls; note that existing objects keep their original setting until rewritten, so copy objects in place if needed. Check that retries use backoff, review KMS request quotas and request an increase if necessary, and update any policies that depended on object-ARN encryption context.

!!! question "A SaaS company must permanently erase a departing tenant's data, including data in backups that cannot be edited. How can encryption help?"
    Use a separate customer managed key per tenant (or per tenant data class). When the tenant leaves, delete application data and schedule deletion of the tenant's key. After the waiting period, all copies encrypted under that key, including immutable backups, become unrecoverable. This is crypto-shredding; it requires that the tenant's data was never encrypted with a shared key.

#### Architecture Questions

!!! question "Design key management for a microservice platform with 20 services across dev, staging and prod accounts."
    Create customer managed keys per data domain per environment in each workload account, defined in IaC with the service. Key policies separate a security administration role from service task roles and use `kms:ViaService` so services decrypt only through their storage services. SCPs deny key deletion and key policy changes outside the security pipeline and require encryption on storage resources. EventBridge rules alert on `DisableKey`, `ScheduleKeyDeletion` and `PutKeyPolicy`. Backups go to a separate backup account with its own keys. Access Analyzer reports external key access, and CloudTrail events are retained centrally.

!!! question "When would you choose client-side encryption with the AWS Encryption SDK instead of SSE-KMS?"
    When the storage service, its administrators or intermediate systems must never see plaintext; when data passes through several systems and must remain encrypted end to end; when field-level encryption is needed (for example only card numbers); or when data must be decryptable in multiple Regions with multi-Region keys. The trade-offs are application complexity, loss of server-side features such as querying encrypted fields, and key management in code.

#### Troubleshooting Questions

!!! question "A Lambda function can read an S3 object encrypted with a customer managed key in its account, but a role in another account receives AccessDenied although its IAM policy allows `s3:GetObject` and `kms:Decrypt` on the key ARN. What is missing?"
    Cross-account access requires both sides. The key policy in the owning account must allow the other account (or the role) to use the key, and the bucket policy must allow the role to read objects. Also check that the role references the key by full ARN, that no SCP or RCP denies it, and that any encryption context or `kms:ViaService` conditions in the key policy match S3 requests.

!!! question "CloudWatch Logs fails to associate a customer managed key with a log group. Why?"
    The key policy must allow the CloudWatch Logs service principal (`logs.<region>.amazonaws.com`) to perform `kms:Encrypt*`, `kms:Decrypt*`, `kms:ReEncrypt*`, `kms:GenerateDataKey*` and `kms:Describe*`, normally conditioned on `kms:EncryptionContext:aws:logs:arn` matching the log group ARN. Without that statement the association fails.

### 8.3.2 Encryption in Transit with AWS Certificate Manager

#### Conceptual Questions

!!! question "Why does DNS validation allow ACM to renew certificates automatically while email validation may not?"
    The CNAME record remains in DNS as a persistent proof of domain control that ACM can re-check at renewal time without human action. Email validation requires a person to approve again, so renewal can stall if nobody responds.

!!! question "Explain SNI and why it matters for ALB and CloudFront."
    SNI carries the requested hostname in the TLS ClientHello, so a single endpoint can choose the right certificate among many. ALB listeners and CloudFront use SNI to host multiple domains without separate IP addresses or load balancers.

!!! question "Why can a standard ACM public certificate not be installed on an EC2 web server?"
    Standard ACM certificates are non-exportable; the private key never leaves AWS-managed infrastructure and can only be used by integrated services. Use a load balancer or CloudFront in front, an exportable public certificate, a Private CA certificate for internal use, or another CA.

#### Scenario Questions

!!! question "A PCI DSS assessor requires cardholder data to be encrypted on every network segment, but the team also wants AWS WAF on the ALB. What design satisfies both?"
    Terminate TLS at the ALB with an ACM certificate so that WAF can inspect requests, and re-encrypt to the targets with an HTTPS target group; targets use certificates from AWS Private CA or self-signed certificates. Enforce TLS 1.2+ policies and HSTS, and use HTTPS from CloudFront to the ALB if CloudFront is in front.

!!! question "An open banking API must authenticate partners by client certificate. Where and how would you implement this?"
    Configure mTLS on an API Gateway custom domain with a truststore in S3 containing the regulator or partner CA certificates, disable the default execute-api endpoint, and map certificate subject details to partner identities in authorisation logic. Alternatively use ALB mTLS in verify mode with a trust store and CRLs. Monitor truststore warnings and certificate expiry.

#### Architecture Questions

!!! question "A team runs 30 microservices on ECS and EKS with App Mesh mTLS. Propose a migration path."
    Because App Mesh reaches end of support on 30 September 2026, migrate ECS services to ECS Service Connect with TLS from AWS Private CA, or move cross-platform communication to VPC Lattice with HTTPS listeners and IAM auth policies; for EKS services requiring advanced traffic management, adopt Istio with mTLS and certificates chained to Private CA. Migrate service by service behind stable DNS names, with observability in place to verify encryption and latency.

#### Troubleshooting Questions

!!! question "A certificate in ACM shows status 'Pending validation' for three days. What do you check?"
    That the exact CNAME name and value from ACM exist in the authoritative DNS zone for the domain (not a different hosted zone with the same name), that no CAA record forbids Amazon as an issuer, that DNS has propagated, and for email validation that the approval email was received and approved.

!!! question "Browsers report 'certificate not trusted' for an API behind an NLB passthrough listener. What is likely wrong?"
    With passthrough the backend presents its own certificate; it is probably self-signed, from a private CA, missing intermediate certificates, or not matching the hostname. Install a complete chain from a public CA (or an exportable ACM certificate), or switch to an NLB TLS listener with an ACM certificate.

### 8.3.3 Secrets Management with AWS Secrets Manager

#### Conceptual Questions

!!! question "Explain the purpose of the staging labels AWSCURRENT, AWSPENDING and AWSPREVIOUS during rotation."
    `AWSPENDING` marks the new version created and tested during rotation; `AWSCURRENT` marks the version applications use and is moved to the new version in `finishSecret`; `AWSPREVIOUS` marks the former current version, allowing rollback and continued use by clients that have not yet refreshed.

!!! question "Compare single-user and alternating-users rotation."
    Single-user rotation changes one user's password in place: simple, but clients with the old password may fail until they refresh. Alternating users maintains two users and updates the inactive one, then switches `AWSCURRENT`; the previous credentials remain valid until the next rotation, giving zero-downtime rotation at the cost of a superuser secret and more complexity.

!!! question "When should Parameter Store be chosen instead of Secrets Manager?"
    For configuration values and non-rotating settings where cost matters and features such as rotation, replication and cross-account resource policies are not needed. Secrets Manager is preferred for credentials that must rotate, be shared across accounts, or be replicated.

#### Scenario Questions

!!! question "After enabling 30-day rotation on an Aurora application user, the orders service on ECS fails with authentication errors on the rotation date until tasks are restarted. Why, and how do you fix it?"
    ECS injected the password as an environment variable at task start, and single-user rotation invalidated it. Switch to alternating-users rotation so the previous credentials remain valid, and either retrieve the secret at runtime with a caching client that refreshes on authentication failure, or trigger a rolling redeployment from an EventBridge rule on rotation success.

!!! question "A developer committed an API key for a payment provider to a public repository. What are the immediate and long-term actions?"
    Immediately revoke and replace the key at the provider, store the new key in Secrets Manager, update consumers, and review provider and CloudTrail logs for misuse; rewriting Git history does not remove exposure. Long term, add secret scanning in CI and pre-commit hooks, ensure all consumers retrieve the key at runtime, and automate rotation with a custom rotation function where the provider API allows.

#### Architecture Questions

!!! question "Design secrets management for an EKS platform hosting 40 services across three environments and two Regions."
    One secret per credential per environment, named hierarchically (`env/service/purpose`), encrypted with customer managed keys per environment, replicated to the second Region. Pods receive per-service IAM roles through EKS Pod Identity; the Secrets Store CSI Driver with ASCP mounts only that service's secrets, with rotation polling enabled, or External Secrets Operator syncs them where environment variables are required. Access policies scope by name prefix or tags; rotation is enabled with managed rotation for databases and custom functions for third-party APIs; secrets and policies are created by IaC without plaintext values; CloudTrail and EventBridge alert on anomalies and rotation failures; secret scanning runs in CI.

#### Troubleshooting Questions

!!! question "An ECS task fails to start with 'ResourceInitializationError: unable to pull secrets'. What do you check?"
    That the task execution role (not the task role) allows `secretsmanager:GetSecretValue` on the secret ARN and `kms:Decrypt` on a customer managed key; that the key policy allows it; that the `valueFrom` ARN, JSON key and Region are correct; and that tasks in private subnets have a route to Secrets Manager through an interface endpoint or NAT gateway, with security groups permitting HTTPS to the endpoint.

!!! question "A rotation remains incomplete with a version stuck in AWSPENDING. How do you diagnose it?"
    Read the rotation function's CloudWatch Logs to find the failing step. Common causes are the function lacking network access to the database or the Secrets Manager endpoint, the master secret lacking privileges to change passwords, a database parameter preventing the change, or non-idempotent custom code. Fix the cause and call `RotateSecret` again; the pending version is reused or replaced.

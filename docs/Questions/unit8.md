# Unit 8: Practice Questions

## 8.1 AWS Identity and Access Management

### 8.1.1 IAM Users, Groups, and Roles

#### Beginner Questions

1. List three tasks that require the root user and three measures that protect it.

    ??? success "Check your answer"

        A good answer covers:

        - **Root-only tasks:** for example changing the account's root email or password, closing the account, restoring IAM permissions after a lockout, changing the support plan, or deleting an S3 bucket policy that denies all principals.
        - **MFA:** enable MFA (preferably a hardware or passkey device) on the root user.
        - **No access keys:** delete any root access keys and never create new ones.
        - **Controlled storage and monitoring:** keep credentials in a vault with a break-glass procedure, alarm on any root sign-in, or remove root credentials from member accounts with centralised root access management.

2. What are the three components of temporary credentials and what does each do?

    ??? success "Check your answer"

        A good answer covers:

        - **Access key ID:** identifies the credential set and appears in CloudTrail.
        - **Secret access key:** signs each request (SigV4) and is never sent over the network.
        - **Session token:** proves the credentials were issued by STS and must accompany every request.
        - **Expiry:** all three expire together, so a leaked set is useful only for a limited time.

3. Explain the difference between an instance profile and a role.

    ??? success "Check your answer"

        A good answer covers:

        - **Role:** an identity with a trust policy and permissions policies, assumed through STS.
        - **Instance profile:** a container that holds exactly one role so that it can be attached to an EC2 instance.
        - **Delivery:** EC2 obtains the role's temporary credentials through the instance profile and serves them via the instance metadata service.
        - **Console behaviour:** the console creates a same-named profile automatically, which hides the distinction; the CLI and IaC must create both.

4. What is a service-linked role, and why can you not edit its permissions?

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** a role predefined by an AWS service and linked to it, holding exactly the permissions that service needs to act on your behalf.
        - **Why not editable:** AWS owns and maintains the permissions policy, so the service keeps working when it gains features.
        - **Trust:** only the linked service can assume it, and it can usually be deleted only after the service resources that use it are removed.
        - **Governance note:** SCPs do not restrict service-linked roles.

5. Why should IAM users no longer be used for most human access?

    ??? success "Check your answer"

        A good answer covers:

        - **Long-term credentials:** IAM users have passwords and access keys that do not expire and leak easily.
        - **Per-account sprawl:** each account needs its own users, so joiners and leavers must be handled everywhere.
        - **Better alternative:** federation through IAM Identity Center gives people temporary role credentials, central MFA and one place to revoke access.
        - **Remaining uses:** break-glass access and third-party tools that cannot assume roles.

#### Intermediate Questions

1. Write a trust policy that allows only the `orders-api` service account in namespace `orders` of one EKS cluster to assume a role through IRSA.

    ??? success "Check your answer"

        A good answer covers:

        - **Federated principal:** `arn:aws:iam::ACCOUNT:oidc-provider/oidc.eks.REGION.amazonaws.com/id/CLUSTER_ID`.
        - **Action:** `sts:AssumeRoleWithWebIdentity`.
        - **Subject condition:** `StringEquals` on `oidc.eks.REGION.amazonaws.com/id/CLUSTER_ID:sub` equal to `system:serviceaccount:orders:orders-api`.
        - **Audience condition:** the same provider's `:aud` key equal to `sts.amazonaws.com`.
        - **Exactness:** use `StringEquals` rather than wildcards, so no other namespace or service account can assume the role.

2. Compare IRSA and EKS Pod Identity in terms of trust principal, reuse across clusters and session tags.

    ??? success "Check your answer"

        A good answer covers:

        - **Trust principal:** IRSA trusts each cluster's OIDC provider (`sts:AssumeRoleWithWebIdentity`); Pod Identity trusts the service principal `pods.eks.amazonaws.com` (`sts:AssumeRole`, `sts:TagSession`).
        - **Reuse across clusters:** IRSA trust policies must list every cluster's issuer; one Pod Identity trust policy works for any cluster, with associations made through the EKS API.
        - **Session tags:** Pod Identity adds tags such as cluster name, namespace and service account, enabling ABAC; IRSA does not.
        - **Operational note:** Pod Identity needs the Pod Identity Agent add-on; IRSA works on any cluster with an OIDC provider, including some non-EKS setups.

3. Describe a safe procedure to rotate an access key used by a third-party tool without downtime.

    ??? success "Check your answer"

        A good answer covers:

        - **Create a second key:** a user may have two access keys, so create the new one while the old one remains active.
        - **Update the tool:** configure the third-party tool with the new key, ideally from a secrets store.
        - **Confirm the switch:** check the old key's last-used information and CloudTrail to confirm it is no longer used.
        - **Deactivate, then delete:** deactivate the old key first (reversible) and delete it after an observation period.
        - **Long-term fix:** prefer a role the tool can assume (with external ID) so no key is needed.

4. Explain how IAM Identity Center permission sets become roles in member accounts, and how a developer obtains CLI credentials.

    ??? success "Check your answer"

        A good answer covers:

        - **Permission sets:** templates of policies defined once in Identity Center.
        - **Provisioning:** assigning a permission set to a user or group for an account creates an IAM role (named `AWSReservedSSO_...`) in that account, trusting the Identity Center SAML provider.
        - **Sign-in:** users sign in through the access portal with the corporate IdP and MFA, then choose account and role.
        - **CLI credentials:** run `aws configure sso` once and `aws sso login`, which caches a token and obtains temporary role credentials automatically.

5. Explain role chaining and its effect on session duration.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** using credentials from one assumed role to assume another role.
        - **Session limit:** a chained role session is limited to a maximum of one hour, regardless of the role's maximum session duration.
        - **Consequence:** long-running jobs fail with expired credentials unless they refresh by re-assuming the chain.
        - **Traceability:** use source identity so the original principal persists through the chain.

#### Advanced Questions

1. Design identity for a multi-tenant SaaS where tenant workloads must never access another tenant's data in shared DynamoDB tables and S3 buckets, using session tags and token vending.

    ??? success "Check your answer"

        A good answer covers:

        - **Token vending:** a trusted service authenticates the tenant and assumes a shared tenant role, passing a session tag such as `TenantId`.
        - **ABAC conditions:** policies use `dynamodb:LeadingKeys` matching `${aws:PrincipalTag/TenantId}` and S3 prefixes built from the same tag.
        - **Tag integrity:** tenants never receive credentials allowing `sts:TagSession` or the ability to set their own tags; only the vending service can.
        - **Short sessions:** credentials are short-lived and scoped by session policy where helpful.
        - **Testing and audit:** automated cross-tenant access tests, CloudTrail with session tags, and a separate high-isolation option (account or key per tenant) for premium tenants.

2. Evaluate the security of a trust policy granting `arn:aws:iam::444455556666:root` access to a production deployment role, and propose a tighter design.

    ??? success "Check your answer"

        A good answer covers:

        - **What root means here:** `:root` trusts the whole account 444455556666, so any principal there whose identity policy allows `sts:AssumeRole` can assume the role.
        - **Risk:** control is delegated to that account's administrators; a compromised user or overly broad policy there reaches production.
        - **Tighter design:** name the specific deployment role ARN as principal, or use `aws:PrincipalArn` conditions.
        - **Additional conditions:** require `aws:PrincipalOrgID`, an external ID where a third party is involved, and source identity or session tags.
        - **Least privilege:** limit the role's permissions and maximum session duration, and alarm on assumptions.

3. An IdP outage prevents all sign-in to AWS during a production incident. Design break-glass access that remains secure and auditable.

    ??? success "Check your answer"

        A good answer covers:

        - **Independent path:** keep emergency access that does not depend on the IdP or Identity Center, such as a small number of IAM users or roles in a dedicated account.
        - **Strong protection:** hardware MFA, credentials split or stored in a vault, no access keys, and named custodians.
        - **Detection:** EventBridge and CloudTrail alarms on any break-glass sign-in, paging the security team.
        - **Procedure:** documented, regularly tested, with mandatory post-incident review and credential rotation after use.
        - **Least privilege where possible:** separate roles for read-only diagnosis and for administrative recovery.

4. Explain how source identity and session names allow an investigator to trace an action performed by a Lambda function back to the engineer who deployed it through GitHub Actions.

    ??? success "Check your answer"

        A good answer covers:

        - **Pipeline session:** the GitHub OIDC role session name and session tags identify the repository and run, and source identity can be set to the engineer or commit author.
        - **Deployment record:** CloudTrail records the deploy role's actions (for example `UpdateFunctionCode`) with that session name.
        - **Runtime action:** the Lambda function's actions appear in CloudTrail under its execution role with the function name as session name.
        - **Correlation:** the investigator links the function version or deployment to the pipeline run, and the run to the engineer via the source identity and GitHub audit logs.
        - **Limitation:** source identity persists across role chaining but not into the Lambda runtime's own role session, so correlation via deployment metadata is needed.

5. Compare IAM Roles Anywhere, long-lived access keys and a VPN to an EC2-hosted proxy for giving on-premises servers access to S3, considering security, operations and failure modes.

    ??? success "Check your answer"

        A good answer covers:

        - **Roles Anywhere:** servers use X.509 certificates from a trusted CA to obtain temporary role credentials; no static secret, but PKI and certificate lifecycle must be operated.
        - **Long-lived access keys:** simple to set up but a permanent secret on disk; leakage, rotation burden and weak auditing.
        - **VPN plus EC2 proxy:** keeps credentials in AWS, but adds a single point of failure, scaling and patching burden, and still needs authentication to the proxy.
        - **Failure modes:** CA or certificate expiry for Roles Anywhere; key leakage for access keys; proxy or VPN outage for the proxy design.
        - **Recommendation:** Roles Anywhere is generally preferred for security and operations.

### 8.1.2 IAM Policies and Permissions

#### Beginner Questions

1. Name the six main elements of a policy statement and explain each.

    ??? success "Check your answer"

        A good answer covers:

        - **Effect:** `Allow` or `Deny`.
        - **Action (or NotAction):** the API operations the statement covers.
        - **Resource (or NotResource):** the ARNs the statement applies to.
        - **Condition:** optional conditions on context keys that must be true.
        - **Principal:** who the statement applies to, used only in resource-based policies.
        - **Sid:** an optional statement identifier for readability.

2. What is the difference between an implicit deny and an explicit deny?

    ??? success "Check your answer"

        A good answer covers:

        - **Implicit deny:** the default when no policy allows the request; it can be overridden by an allow.
        - **Explicit deny:** a `Deny` statement that matches the request.
        - **Precedence:** an explicit deny in any applicable policy always wins and cannot be overridden by any allow.

3. Give two examples of resource-based policies used earlier in DSO303.

    ??? success "Check your answer"

        A good answer covers:

        - **S3 bucket policies:** for example denying non-TLS access or granting CloudFront access to an origin bucket.
        - **Other examples:** ECR repository policies, Lambda function resource policies (for API Gateway or S3 triggers), SQS queue and SNS topic policies, KMS key policies, Secrets Manager resource policies.
        - **Common feature:** each includes a `Principal` element and lives on the resource.

4. Why should customer managed policies generally be preferred over inline policies?

    ??? success "Check your answer"

        A good answer covers:

        - **Reusable:** one customer managed policy can be attached to many principals.
        - **Versioned:** up to five versions with rollback.
        - **Visible and governable:** listed independently, easier to audit and manage as code.
        - **Inline exception:** inline policies suit strict one-to-one relationships that should be deleted with the principal.

5. What does the IAM Policy Simulator do?

    ??? success "Check your answer"

        A good answer covers:

        - **Purpose:** evaluates whether specified actions on specified resources would be allowed for a principal or for supplied policies.
        - **What it considers:** identity policies, boundaries, and optionally resource policies, SCPs and context keys.
        - **Use:** testing and troubleshooting policies without making real calls.
        - **Limitation:** it does not perform the actions, and some policy types and conditions are only partly simulated.

#### Intermediate Questions

1. Write a policy that allows `ec2:StartInstances` and `ec2:StopInstances` only on instances tagged `owner` equal to the caller's `owner` principal tag.

    ??? success "Check your answer"

        A good answer covers:

        - **Allow statement:** `ec2:StartInstances` and `ec2:StopInstances` on `arn:aws:ec2:*:*:instance/*`.
        - **Condition:** `StringEquals` on `aws:ResourceTag/owner` equal to `${aws:PrincipalTag/owner}`.
        - **Tag protection:** deny `ec2:CreateTags` and `ec2:DeleteTags` on the `owner` key so users cannot retag instances to gain access.
        - **Principal tag integrity:** only administrators or the IdP may set the principal's `owner` tag.

2. Explain how a permissions boundary and an identity policy combine, with an example that yields no effective permissions.

    ??? success "Check your answer"

        A good answer covers:

        - **Combination:** effective permissions are the intersection of the identity policy and the boundary.
        - **Boundary does not grant:** a boundary only caps what identity policies can allow.
        - **Example:** identity policy allows only `s3:*`, boundary allows only `dynamodb:*`; the intersection is empty, so the principal can do nothing.
        - **Deny rule:** an explicit deny in either still wins.

3. Explain why `iam:PassRole` is considered a privilege escalation risk and how to restrict it.

    ??? success "Check your answer"

        A good answer covers:

        - **Escalation:** passing a more privileged role to a service (EC2, Lambda, ECS) lets the caller run code with that role's permissions.
        - **Restrict resources:** allow `iam:PassRole` only on specific role ARNs or a path such as `role/app/*`.
        - **Restrict service:** use the `iam:PassedToService` condition.
        - **Combine with boundaries:** roles that may be passed should themselves carry a permissions boundary.

4. Describe how IAM Access Analyzer policy generation works and its limitations.

    ??? success "Check your answer"

        A good answer covers:

        - **Input:** Access Analyzer analyses CloudTrail activity for a role or user over a chosen period (up to 90 days).
        - **Output:** a draft policy listing the services and actions used, with resource placeholders in many cases.
        - **Limitations:** it only sees logged activity, so rarely used actions are missed; it does not identify action-level activity for data events (such as S3 object reads) and cannot include `iam:PassRole`, which CloudTrail does not track; resource ARNs and conditions need manual refinement.
        - **Use:** a starting point that a human reviews and tests.

5. Write a statement that denies all actions outside `ap-south-1` and `us-east-1` except for global services, and explain the role of `NotAction`.

    ??? success "Check your answer"

        A good answer covers:

        - **Effect and NotAction:** `Deny` with `NotAction` listing global services (for example `iam:*`, `organizations:*`, `sts:*`, `cloudfront:*`, `route53:*`, `support:*`), resource `*`.
        - **Condition:** `StringNotEquals` on `aws:RequestedRegion` with values `ap-south-1` and `us-east-1`.
        - **Role of NotAction:** it means "every action except these", so global service calls served from `us-east-1` are not blocked.
        - **Caution:** a Deny with NotAction denies only; it never grants the listed actions.

#### Advanced Questions

1. Trace the full evaluation of a request by a role in account A, with a boundary and a session policy, to a KMS-encrypted SQS queue in account B with an RCP, listing every policy that must allow.

    ??? success "Check your answer"

        A good answer covers:

        - **Account A identity side:** the role's identity policy must allow the actions, the permissions boundary must allow them, and the session policy must allow them.
        - **Account A organisation:** SCPs at every level above account A must allow the action.
        - **Account B resource side:** the SQS queue policy must allow the role (cross-account needs both sides).
        - **Account B organisation:** the RCP on account B must not deny it.
        - **KMS:** the key policy (plus any grant) must allow `kms:GenerateDataKey` or `kms:Decrypt` for the role; KMS-side SCPs and RCPs also apply.
        - **Deny rule:** any explicit deny in any of these policies ends evaluation with a deny.

2. Design a policy-as-code pipeline for IAM that combines validation, custom checks, simulation and human review, and discuss false positives and negatives.

    ??? success "Check your answer"

        A good answer covers:

        - **Validation:** IAM Access Analyzer `ValidatePolicy` for syntax and best-practice findings in the pull request.
        - **Custom checks:** `CheckNoNewAccess`, `CheckAccessNotGranted` and `CheckNoPublicAccess`, plus tools such as cfn-guard or OPA rules.
        - **Simulation and tests:** policy simulator or integration tests for expected allow and deny cases.
        - **Human review:** required for findings that tools flag or for sensitive changes.
        - **False positives and negatives:** suppress known findings with documented exceptions; accept that tools miss context such as tag governance or business intent.

3. Evaluate the risks of ABAC in a multi-tenant SaaS and propose controls that make it robust.

    ??? success "Check your answer"

        A good answer covers:

        - **Tag tampering:** a principal that can modify resource or principal tags can grant itself access.
        - **Missing tags:** untagged resources may become accessible or inaccessible unexpectedly.
        - **Controls:** SCPs denying tag changes on authorisation tags, tag policies, enforced tagging at creation (`aws:RequestTag`), and token vending setting session tags.
        - **Testing and monitoring:** cross-tenant tests and Config rules for untagged resources.
        - **Defence in depth:** separate accounts or keys for high-risk tenants.

4. Explain how automated reasoning allows Access Analyzer to prove that a bucket is not public, and what classes of access it cannot reason about.

    ??? success "Check your answer"

        A good answer covers:

        - **Automated reasoning:** policies are translated into logical formulas, and an SMT solver proves properties over all possible requests rather than sampling.
        - **Proof of non-public:** it can show that no request from outside the zone of trust satisfies the bucket policy, ACLs and block public access settings.
        - **Limits:** it cannot reason about runtime behaviour, application-level access (for example a public API serving objects), credentials leaked to outsiders, or condition keys whose values it cannot interpret.

5. A security team proposes replacing all resource-based policies with role assumption for cross-account access. Evaluate the proposal considering auditability, permissions loss when assuming roles, service support and operational complexity.

    ??? success "Check your answer"

        A good answer covers:

        - **Auditability:** role assumption shows a clear session in both accounts; resource policies show the external principal directly.
        - **Permission loss:** assuming a role drops the caller's own permissions, which hurts tasks needing both accounts' resources (for example copying between buckets).
        - **Service support:** some services (S3 event notifications, SNS, KMS cross-account use, Lambda invocation) work naturally with resource policies.
        - **Operational complexity:** more roles and trust policies to manage.
        - **Conclusion:** use both; standardise with RCPs and Access Analyzer rather than banning resource policies.

### 8.1.3 AWS Organizations and Service Control Policies

#### Beginner Questions

1. What are the management account, member accounts, the root and OUs?

    ??? success "Check your answer"

        A good answer covers:

        - **Management account:** creates the organisation, pays the bills, and holds the highest authority.
        - **Member accounts:** all other accounts in the organisation.
        - **Root:** the top container of the hierarchy, to which policies can be attached.
        - **OUs:** organisational units grouping accounts so that policies apply to the group.

2. Name four benefits of a multi-account strategy.

    ??? success "Check your answer"

        A good answer covers:

        - **Isolation:** the account is the strongest security and blast-radius boundary.
        - **Separation of environments and teams:** dev, test and prod cannot affect each other.
        - **Billing clarity:** cost allocation per account.
        - **Quotas:** service limits are per account, so workloads do not compete.
        - **Governance:** different guardrails per OU.

3. What is consolidated billing and how does it save money?

    ??? success "Check your answer"

        A good answer covers:

        - **One bill:** the management account pays for all member accounts.
        - **Aggregated usage:** usage across accounts is combined for volume pricing tiers.
        - **Sharing of discounts:** Reserved Instances and Savings Plans can apply across accounts.
        - **No extra charge:** consolidated billing is free.

4. What does `FullAWSAccess` do, and why is it attached by default?

    ??? success "Check your answer"

        A good answer covers:

        - **Effect:** an SCP that allows all actions on all resources.
        - **Why default:** SCPs are allow-filters; without an allow at each level, nothing would be permitted in member accounts.
        - **Deny-list strategy:** keep it attached and add deny SCPs.
        - **Removing it:** requires explicit allow SCPs (allow-list strategy).

5. Name three core accounts in a landing zone and their purposes.

    ??? success "Check your answer"

        A good answer covers:

        - **Management account:** organisation administration and billing only.
        - **Log archive account:** central, immutable CloudTrail and Config logs.
        - **Audit or security tooling account:** delegated administrator for GuardDuty, Security Hub and similar tools, with read access for security teams.
        - **Others:** network and shared services accounts are commonly added.

#### Intermediate Questions

1. Explain SCP inheritance with an example of three levels and compute the effective maximum permissions.

    ??? success "Check your answer"

        A good answer covers:

        - **Rule:** at each level (root, OU, account), the action must be allowed by an attached SCP; the effective maximum is the intersection.
        - **Example:** root allows everything (`FullAWSAccess`), the Workloads OU allows everything but denies `organizations:LeaveOrganization`, and the account allows only `s3:*`, `ec2:*` and `cloudwatch:*`.
        - **Result:** the account's principals can at most use S3, EC2 and CloudWatch, minus any denies.
        - **Reminder:** SCPs grant nothing; IAM policies must still allow the actions.

2. Compare deny-list and allow-list SCP strategies and state when each is appropriate.

    ??? success "Check your answer"

        A good answer covers:

        - **Deny-list:** keep `FullAWSAccess` and add specific denies; new services are available automatically; easier to maintain.
        - **Allow-list:** replace `FullAWSAccess` with SCPs allowing only approved services; stronger control but must be updated for new needs.
        - **When deny-list:** most organisations and development OUs.
        - **When allow-list:** highly regulated or sandbox OUs where only a small, approved set of services is acceptable.

3. Describe Control Tower preventive, detective and proactive controls, and the AWS mechanism behind each.

    ??? success "Check your answer"

        A good answer covers:

        - **Preventive:** stop non-compliant actions; implemented with SCPs (and RCPs or declarative policies).
        - **Detective:** detect non-compliant resources after the fact; implemented with AWS Config rules.
        - **Proactive:** check resources before provisioning; implemented with CloudFormation hooks.
        - **Ownership:** Control Tower applies and reports these across enrolled OUs.

4. Explain how delegated administrators reduce risk to the management account.

    ??? success "Check your answer"

        A good answer covers:

        - **Delegation:** security services such as GuardDuty, Security Hub, Config and IAM Access Analyzer are administered from a member account.
        - **Less management account use:** fewer people need access to the most privileged account.
        - **SCPs do not apply** to the management account, so reducing its use reduces unconstrained activity.
        - **Separation of duties:** security teams operate their tools without billing or organisation-wide authority.

5. Write an SCP that prevents deletion of AWS Backup vaults and recovery points except by a named backup administrator role.

    ??? success "Check your answer"

        A good answer covers:

        - **Effect Deny** on `backup:DeleteBackupVault`, `backup:DeleteRecoveryPoint`, `backup:UpdateRecoveryPointLifecycle` and `backup:DeleteBackupVaultAccessPolicy` (and similar), resource `*`.
        - **Condition:** `ArnNotLike` on `aws:PrincipalARN` with the named role, for example `arn:aws:iam::*:role/BackupAdmin`.
        - **Attachment:** attach to the OUs containing workload accounts.
        - **Complement:** AWS Backup Vault Lock gives stronger, immutable protection.

#### Advanced Questions

1. Design a complete data perimeter using SCPs, RCPs, resource policies and VPC endpoint policies, identify the exceptions needed for AWS services and third parties, and describe a safe rollout.

    ??? success "Check your answer"

        A good answer covers:

        - **Identity side:** SCPs require `aws:ResourceOrgID` so principals only access organisation resources.
        - **Resource side:** RCPs deny access unless `aws:PrincipalOrgID` matches, so only trusted identities reach resources.
        - **Network side:** endpoint policies and resource policies with `aws:SourceVpce` or `aws:SourceVpc` ensure expected networks.
        - **Exceptions:** AWS service principals (`aws:PrincipalIsAWSService`, `aws:ViaAWSService`), approved third parties and AWS-owned resources such as public ECR images or service buckets.
        - **Rollout:** analyse CloudTrail and Access Analyzer data, test in a sandbox OU, deploy gradually by OU, monitor denials, and keep a rollback plan.

2. Evaluate the trade-offs between Control Tower and a custom Terraform-based landing zone for an organisation with strict regulatory requirements.

    ??? success "Check your answer"

        A good answer covers:

        - **Control Tower:** fast, AWS-maintained landing zone with managed controls, Account Factory and drift detection; less flexible and tied to AWS release cycles.
        - **Custom Terraform:** full control, any required control and audit evidence as code; requires engineering effort and maintenance.
        - **Regulatory angle:** both can meet requirements; custom suits unusual controls, Control Tower reduces build effort.
        - **Hybrid:** Control Tower with Account Factory for Terraform (AFT) or Customizations for Control Tower is common.

3. Explain how declarative policies differ from SCPs in enforcement point and robustness to new APIs, using IMDSv2 as an example.

    ??? success "Check your answer"

        A good answer covers:

        - **Enforcement point:** SCPs evaluate each API call in IAM authorisation; declarative policies set a baseline in the service's control plane.
        - **New APIs:** an SCP must name every relevant API and can be bypassed by new ones; a declarative policy enforces the desired state regardless of API.
        - **IMDSv2 example:** an SCP can deny `RunInstances` unless `ec2:MetadataHttpTokens` is `required`, but must also cover `ModifyInstanceMetadataOptions` and future paths; a declarative policy makes IMDSv2 the enforced default for all instances.
        - **Messaging:** declarative policies can return a custom error message.

4. A merger requires moving 50 accounts from another organisation into yours. Plan the migration, including billing, guardrails, identity, logging and risks.

    ??? success "Check your answer"

        A good answer covers:

        - **Billing:** each account leaves its old organisation (becoming standalone with its own payment method) before joining; plan commitments such as Savings Plans.
        - **Guardrails:** move accounts first into a quarantine or transition OU with tested SCPs, then into target OUs.
        - **Identity:** migrate to your Identity Center, remove old cross-account roles and trusts.
        - **Logging:** create organisation trail coverage, migrate or retain old logs, deploy Config and security services.
        - **Risks:** broken dependencies on the old organisation ID in policies, gaps in logging, and workload breakage from new SCPs.

5. Critically assess the statement "SCPs make IAM least privilege unnecessary".

    ??? success "Check your answer"

        A good answer covers:

        - **SCPs are coarse:** they set maximum permissions for whole accounts or OUs, not per workload.
        - **No grants:** IAM policies still decide who can do what within those bounds.
        - **No management account coverage**, and no effect on service-linked roles.
        - **Within-account threats:** an over-privileged role can still damage all resources the SCP allows.
        - **Conclusion:** the statement is false; SCPs and least privilege are complementary layers.

---

## 8.2 Network Security

### 8.2.1 VPC Design and Security Groups

#### Beginner Questions

1. Explain the difference between north-south and east-west traffic, and give one AWS control for each.

    ??? success "Check your answer"

        A good answer covers:

        - **North-south:** traffic entering or leaving the VPC, for example from the internet; controls include AWS WAF, Network Firewall or security groups on an ALB.
        - **East-west:** traffic between workloads inside or between VPCs; controls include security group references, NetworkPolicy or VPC Lattice auth policies.
        - **Why both:** perimeter controls do not stop lateral movement after a compromise.

2. Why should the default security group in every VPC have no rules?

    ??? success "Check your answer"

        A good answer covers:

        - **Default behaviour:** resources launched without a chosen group fall into it, and it allows all traffic between members.
        - **Risk:** unrelated resources can then reach each other, creating unintended paths.
        - **Best practice:** remove all its rules so accidental use fails safely; enforce with Config or Security Hub controls.

3. List three reasons Session Manager is preferred over a bastion host.

    ??? success "Check your answer"

        A good answer covers:

        - **No inbound ports:** no SSH port or public IP is needed.
        - **IAM-based access:** access is granted and revoked through IAM, with MFA through federation.
        - **Auditing:** sessions can be logged to S3 or CloudWatch Logs and are recorded in CloudTrail.
        - **Less to maintain:** no bastion host to patch, scale or harden.

4. What does it mean for a security group to reference another security group, and why is this better than using a CIDR block?

    ??? success "Check your answer"

        A good answer covers:

        - **Meaning:** a rule allows traffic from any ENI that is a member of the referenced group, regardless of IP address.
        - **Why better:** it follows workloads as they scale, move or change IPs (containers, Auto Scaling).
        - **Least privilege:** a CIDR allows everything in the range, while a reference allows only the intended tier.
        - **Readability:** the rule expresses intent ("the API may reach the database").

5. Name two AWS services that can filter outbound traffic by domain name.

    ??? success "Check your answer"

        A good answer covers:

        - **AWS Network Firewall:** domain allow and deny lists using TLS SNI and HTTP Host.
        - **Route 53 Resolver DNS Firewall:** blocks or allows DNS resolution of domains.
        - **Note:** security groups and NACLs work only on IPs and ports, so they cannot filter by domain.

#### Intermediate Questions

1. Write the communication matrix and the security group rules for a service with an ALB, an ECS API, an ElastiCache cluster and an Aurora database.

    ??? success "Check your answer"

        A good answer covers:

        - **Matrix:** internet to ALB on 443; ALB to ECS API on the container port; ECS API to ElastiCache on 6379; ECS API to Aurora on 5432 (or 3306).
        - **ALB SG:** inbound 443 from `0.0.0.0/0` (or the CloudFront prefix list); outbound to the API SG on the container port.
        - **API SG:** inbound container port from the ALB SG only; outbound to the cache SG on 6379, the database SG on 5432 and endpoints on 443.
        - **Cache SG:** inbound 6379 from the API SG only.
        - **Database SG:** inbound 5432 from the API SG only; no other sources.

2. Explain how an S3 gateway endpoint policy and an S3 bucket policy with `aws:SourceVpce` together prevent two different exfiltration scenarios.

    ??? success "Check your answer"

        A good answer covers:

        - **Endpoint policy:** restricts which buckets can be reached through the endpoint, so a compromised workload cannot copy data to an attacker's bucket.
        - **Bucket policy with `aws:SourceVpce`:** denies access unless the request arrives through the approved endpoint, so stolen credentials used from outside the network cannot read the data.
        - **Together:** one controls where data can go from the network, the other controls where the bucket can be accessed from.
        - **Exceptions:** allow service principals or administrative roles that legitimately access from elsewhere.

3. Describe the three deployment models for AWS Network Firewall and one situation in which each is the best choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Distributed:** a firewall in each VPC; best when few VPCs, strong team autonomy or high-volume local ingress.
        - **Centralised inspection VPC:** traffic routed through Transit Gateway to one firewall; best for many VPCs needing consistent egress filtering.
        - **Combined:** centralised egress and east-west, local ingress next to ALBs; best for large estates with mixed traffic volumes.

4. Explain why removing a security group rule may not terminate an attacker's existing connection, and what to do instead.

    ??? success "Check your answer"

        A good answer covers:

        - **Connection tracking:** security groups are stateful, and existing tracked connections may continue after a rule is removed.
        - **Untracked exceptions:** only flows that are untracked (for example all-traffic allow rules) are stopped immediately.
        - **Instead:** add a NACL deny rule for the attacker's address, which is stateless and applies to every packet.
        - **Also:** isolate the instance with a quarantine security group and investigate.

5. Compare Firewall Manager security group policies, AWS Config rules and Security Hub controls: what does each contribute to governance?

    ??? success "Check your answer"

        A good answer covers:

        - **Firewall Manager:** centrally deploys and audits security group policies across accounts, and can remediate.
        - **AWS Config rules:** evaluate resource configuration (for example unrestricted SSH) and record history.
        - **Security Hub controls:** aggregate findings against standards and provide a compliance score.
        - **Together:** enforcement, detection and reporting respectively.

#### Advanced Questions

1. Design a multi-account network for an organisation with 200 accounts that must prevent any workload account from creating internet paths, centralise egress with domain filtering, and allow selected services to be shared across accounts. Justify each control.

    ??? success "Check your answer"

        A good answer covers:

        - **SCPs:** deny creation and attachment of internet gateways, egress-only gateways and NAT gateways in workload accounts; deny VPC peering outside approved paths.
        - **Declarative policy:** VPC Block Public Access enforced for workload OUs.
        - **Centralised egress:** Transit Gateway to an egress VPC with Network Firewall domain allow-lists and DNS Firewall.
        - **Sharing:** AWS RAM shares subnets, Transit Gateway and endpoint services; VPC Lattice or PrivateLink for selected services.
        - **Governance:** Firewall Manager, Config and Network Access Analyzer verify the design continuously.

2. Evaluate the security and operational trade-offs of fail-open versus fail-closed DNS Firewall configuration for a payment platform and for an internal analytics platform.

    ??? success "Check your answer"

        A good answer covers:

        - **Fail-closed:** DNS queries are blocked if the firewall cannot evaluate them; safer but risks outages.
        - **Fail-open:** queries resolve when the firewall is unavailable; preserves availability but loses protection.
        - **Payment platform:** confidentiality and compliance favour fail-closed, with high-availability design and monitoring.
        - **Analytics platform:** availability and lower data sensitivity may justify fail-open with alerting.
        - **Key point:** a documented risk decision per workload.

3. Propose a micro-segmentation strategy for an EKS cluster hosting 60 microservices from 10 teams, combining NetworkPolicy, security groups for pods and VPC Lattice or a service mesh. Address operational ownership and testing.

    ??? success "Check your answer"

        A good answer covers:

        - **NetworkPolicy:** default deny per namespace, with explicit allow rules for service-to-service flows, owned by each team.
        - **Security groups for pods:** for pods reaching AWS resources such as RDS that are protected by security groups.
        - **VPC Lattice or mesh:** identity-based authorisation and mTLS for service-level policy.
        - **Ownership:** platform team sets defaults and guardrails; teams own their policies in Git, reviewed through pull requests.
        - **Testing:** policy tests in CI and connectivity tests in staging.

4. Critically assess the claim "our workloads are in private subnets, so they are secure". Identify at least five attack paths that remain and the controls that close them.

    ??? success "Check your answer"

        A good answer covers:

        - **Attack paths remaining:** compromised dependencies or credentials, outbound internet via NAT, DNS exfiltration, lateral movement within the VPC, over-permissive IAM, public S3 or snapshots, and exposure through load balancers.
        - **Egress controls:** Network Firewall or DNS Firewall with domain allow-lists.
        - **Lateral movement:** security group references and least-privilege east-west rules.
        - **Identity:** least-privilege IAM, IMDSv2 and data perimeter policies.
        - **Detection:** GuardDuty, Flow Logs and Config to find what prevention misses.

5. Design an automated pipeline that proves, before every deployment, that no path exists from the internet to any database and that no workload can reach buckets outside the organisation. Name the tools and the tests.

    ??? success "Check your answer"

        A good answer covers:

        - **Static analysis:** IaC scanning (cfn-guard, Checkov) rejects public database settings and wide security groups.
        - **Network reachability:** Network Access Analyzer or Reachability Analyzer scopes proving no path from internet gateways to database ENIs.
        - **Data perimeter checks:** IAM Access Analyzer custom policy checks on endpoint and bucket policies, ensuring `aws:ResourceOrgID` restrictions.
        - **Pipeline gates:** fail the deployment on any finding, with documented exceptions.
        - **Continuous verification:** the same checks run regularly after deployment.

### 8.2.2 Network ACLs and VPC Flow Logs

#### Beginner Questions

1. What is the difference between a stateful and a stateless firewall, and which AWS control is each?

    ??? success "Check your answer"

        A good answer covers:

        - **Stateful:** remembers connections and allows return traffic automatically; security groups.
        - **Stateless:** evaluates each packet independently, so return traffic needs its own rule; network ACLs.
        - **Practical consequence:** NACLs need ephemeral port rules (1024 to 65535) for return traffic, whereas security groups do not.

2. Why must NACL deny rules have lower numbers than the allow rules they override?

    ??? success "Check your answer"

        A good answer covers:

        - **Order:** NACL rules are evaluated from the lowest number, and the first match decides.
        - **Consequence:** a deny with a higher number than a matching allow is never reached.
        - **Practice:** leave gaps in the numbering so deny rules can be inserted above allows.

3. Name the three possible destinations for VPC Flow Logs and one advantage of each.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudWatch Logs:** near real-time search, metric filters and alarms.
        - **Amazon S3:** cheapest long-term storage, Parquet and partitions for Athena queries.
        - **Amazon Data Firehose:** streaming delivery to third-party tools or SIEMs.

4. What does a `tcp-flags` value of 2 indicate?

    ??? success "Check your answer"

        A good answer covers:

        - **Value 2:** a SYN flag was seen.
        - **Meaning:** a connection attempt (or start of a handshake).
        - **Security use:** many value-2 records without responses across ports indicate a SYN scan.

5. List three kinds of traffic that VPC Flow Logs do not record.

    ??? success "Check your answer"

        A good answer covers:

        - **Amazon DNS traffic:** queries to the Route 53 Resolver are not recorded.
        - **Instance metadata:** traffic to 169.254.169.254 and the Time Sync Service.
        - **Other exclusions:** DHCP and ARP traffic, Windows licence activation, traffic to the reserved VPC router address, and Traffic Mirroring source traffic.

#### Intermediate Questions

1. Write the steps of a containment runbook for an instance communicating with a command-and-control server, and justify the order.

    ??? success "Check your answer"

        A good answer covers:

        - **Isolate:** replace security groups with a quarantine group and add a NACL deny for the C2 address, to stop activity quickly.
        - **Preserve evidence:** snapshot volumes and capture memory before changes that destroy state.
        - **Remove from service:** detach from the Auto Scaling group and load balancer without terminating.
        - **Investigate:** use GuardDuty, Detective, Flow Logs and CloudTrail; revoke role sessions.
        - **Recover:** replace with a clean instance, fix the root cause, and document.
        - **Order rationale:** containment first limits damage; evidence before termination preserves investigation.

2. Explain the benefits of Parquet, Hive-compatible prefixes and hourly partitions for security queries on Flow Logs.

    ??? success "Check your answer"

        A good answer covers:

        - **Parquet:** columnar and compressed, so Athena reads fewer bytes, reducing cost and time.
        - **Hive-compatible prefixes:** partitions are recognised automatically by Athena and Glue.
        - **Hourly partitions:** queries over short incident windows scan only relevant data.
        - **Overall:** faster, cheaper security queries over large log volumes.

3. Compare GuardDuty, Detective and Security Lake: what does each do with network telemetry?

    ??? success "Check your answer"

        A good answer covers:

        - **GuardDuty:** analyses Flow Logs, DNS logs and CloudTrail independently to produce threat findings.
        - **Detective:** builds a behaviour graph for investigating findings and visualising entity relationships.
        - **Security Lake:** stores normalised (OCSF) security data in your account's S3 for long-term querying and third-party tools.
        - **Summary:** detect, investigate and retain respectively.

4. Design a NACL rule numbering convention and explain how it supports incident response.

    ??? success "Check your answer"

        A good answer covers:

        - **Reserved ranges:** for example 1 to 99 for incident-response denies, 100 onward for standard allows.
        - **Gaps:** increments of 10 or 100 so rules can be inserted.
        - **Documented meaning:** each band has a purpose, so responders know where to add a block without disturbing allows.
        - **Benefit:** faster, safer emergency changes via runbooks or automation.

5. Explain how `pkt-srcaddr` helps identify the internal host responsible for traffic seen leaving through a NAT gateway.

    ??? success "Check your answer"

        A good answer covers:

        - **NAT behaviour:** traffic leaving a NAT gateway shows the NAT's address as source.
        - **pkt-srcaddr:** records the original packet source address, the internal instance's private IP.
        - **Use:** in logs on the NAT gateway's interface, it identifies which internal host initiated the flow.

#### Advanced Questions

1. Design a "hunting as code" programme for network telemetry: which queries, how they are scheduled and versioned, how results become findings, and how false positives are managed.

    ??? success "Check your answer"

        A good answer covers:

        - **Queries:** versioned Athena or SQL queries for known patterns (port scans, rare destinations, large outbound transfers, DNS anomalies).
        - **Scheduling:** run on a schedule (EventBridge plus Lambda or Step Functions).
        - **Version control:** stored in Git with peer review and tests against sample data.
        - **Findings:** results published to Security Hub as findings with severity.
        - **False positives:** tuned with allow-lists, thresholds and feedback, tracked with metrics.

2. Evaluate the risks of fully automated containment for GuardDuty findings in a production e-commerce platform and propose a tiered automation policy.

    ??? success "Check your answer"

        A good answer covers:

        - **Risks:** isolating a production instance or blocking an IP on a false positive can cause outages and revenue loss.
        - **Tier 1, fully automated:** low-risk, high-confidence actions such as tagging, snapshots and blocking known malicious IPs.
        - **Tier 2, approval needed:** isolation of production instances after human confirmation.
        - **Tier 3, manual:** destructive or wide-impact actions.
        - **Safeguards:** testing, rollback, and alerting for every automated action.

3. Design protection for the log archive such that neither a compromised workload account administrator nor a compromised security-team engineer can delete network evidence within the retention period.

    ??? success "Check your answer"

        A good answer covers:

        - **Separate account:** logs stored in a dedicated log archive account, so workload administrators have no access.
        - **Immutability:** S3 Object Lock in compliance mode for the retention period.
        - **Guardrails:** SCPs deny deletion and policy changes on the archive except by a break-glass role.
        - **Separation of duties:** security engineers have read-only access; alarms on policy changes.
        - **Encryption:** customer managed KMS key with restricted key policy.

4. A regulator requires packet capture for all traffic in a cardholder data environment. Evaluate Traffic Mirroring, Network Firewall and third-party appliances behind GWLB for this requirement, including cost and scale.

    ??? success "Check your answer"

        A good answer covers:

        - **Traffic Mirroring:** copies packets from ENIs to collectors; suited to full packet capture; supported only on Nitro instances, costs per session and can overload collectors at scale.
        - **Network Firewall:** inspects and logs flows and alerts but does not retain full packet captures.
        - **Third-party appliances behind GWLB:** full packet capture and IPS, scale horizontally, but add licence and operational cost.
        - **Scale and cost:** storage for packet data is large; scope capture to the cardholder environment only.

5. Explain how detection latency is composed from a malicious connection to a containment action using Flow Logs and GuardDuty, and propose design changes to reduce it.

    ??? success "Check your answer"

        A good answer covers:

        - **Components:** connection time, Flow Log aggregation interval (1 or 10 minutes), delivery delay, GuardDuty analysis and finding publication, EventBridge delivery, and the containment action.
        - **Reduce aggregation:** use a 1-minute aggregation interval.
        - **Faster routing:** EventBridge rules invoking automation directly.
        - **Prevention:** add preventive controls (DNS Firewall, Network Firewall) that block before detection is needed.

### 8.2.3 AWS WAF and Shield for Application Protection

#### Beginner Questions

1. List five AWS resource types that can be associated with an AWS WAF web ACL, and two that cannot.

    ??? success "Check your answer"

        A good answer covers:

        - **Supported:** CloudFront distributions, Application Load Balancers, API Gateway REST APIs, AppSync GraphQL APIs, Cognito user pools (also App Runner and Verified Access).
        - **Not supported:** Network Load Balancers and EC2 instances directly (also API Gateway HTTP APIs).
        - **Scope:** CloudFront web ACLs are global (created in `us-east-1`); the others are Regional.

2. What is the difference between the Block and Count actions?

    ??? success "Check your answer"

        A good answer covers:

        - **Block:** a terminating action that rejects the request (by default with 403).
        - **Count:** a non-terminating action that records a match and continues evaluation.
        - **Use of Count:** testing new rules safely before blocking.

3. What does AWS Shield Standard protect against, and what does it cost?

    ??? success "Check your answer"

        A good answer covers:

        - **Protection:** common network and transport layer attacks such as SYN floods and UDP reflection.
        - **Scope:** all AWS customers, applied automatically.
        - **Cost:** no additional charge.

4. Why must CloudFront-scope web ACLs be created in `us-east-1`?

    ??? success "Check your answer"

        A good answer covers:

        - **CloudFront is global:** its configuration is managed from `us-east-1`.
        - **Requirement:** web ACLs with CloudFront scope (and their IP sets and rule groups) must be created in `us-east-1`.
        - **Consequence:** web ACLs in other Regions cannot be associated with distributions.

5. Name three AWS Managed Rules rule groups and what each protects against.

    ??? success "Check your answer"

        A good answer covers:

        - **Core rule set:** common web exploits such as those in the OWASP Top 10.
        - **Known bad inputs:** request patterns known to exploit vulnerabilities, such as Log4j.
        - **SQL database rule set:** SQL injection patterns.
        - **Others:** Amazon IP reputation list, anonymous IP list, Bot Control, Account Takeover Prevention.

#### Intermediate Questions

1. Explain how labels and rule action overrides allow a false positive to be fixed without disabling a managed rule entirely.

    ??? success "Check your answer"

        A good answer covers:

        - **Labels:** managed rules add labels to matching requests, which later rules can match on.
        - **Override to Count:** set a specific rule's action to Count so it labels but does not block.
        - **Custom rule:** add a rule that blocks requests carrying that label except for the affected path or condition.
        - **Result:** the false positive is fixed narrowly while the rest of the rule group remains in Block.

2. Design rate-based rules for a public API with anonymous search, authenticated checkout and a login endpoint.

    ??? success "Check your answer"

        A good answer covers:

        - **Search:** a higher per-IP rate limit, scoped to the search path, possibly with challenge or CAPTCHA.
        - **Checkout:** keyed on a session or authorisation header, moderate limit.
        - **Login:** a low per-IP limit on the login path, plus Account Takeover Prevention.
        - **General:** a broad rate rule for all traffic as a backstop.
        - **Tuning:** start in Count, observe, then block.

3. Explain WCUs and describe what happens when a web ACL exceeds its base capacity.

    ??? success "Check your answer"

        A good answer covers:

        - **WCU:** web ACL capacity unit, measuring processing cost of each rule.
        - **Base capacity:** a web ACL includes a base capacity (1,500 WCUs at the time of writing) in its standard price.
        - **Exceeding it:** allowed up to a maximum of 5,000 WCUs per web ACL, with tiered additional charges; beyond the maximum, rules cannot be added.
        - **Implication:** design rules efficiently to manage cost.

4. Describe three methods to prevent attackers from bypassing CloudFront to reach an ALB origin, and compare their strength.

    ??? success "Check your answer"

        A good answer covers:

        - **Security group with CloudFront prefix list:** only CloudFront IPs reach the ALB; strong at network level, but any CloudFront distribution can still reach it.
        - **Custom header secret:** CloudFront adds a secret header that the ALB checks; strong when rotated, but a leaked secret allows bypass.
        - **VPC origins:** keep the ALB in private subnets reachable only by CloudFront; strongest.
        - **Combination:** prefix list plus custom header gives defence in depth.

5. Explain how Shield Advanced uses Route 53 health checks and why they matter.

    ??? success "Check your answer"

        A good answer covers:

        - **Health-based detection:** Route 53 health checks associated with protected resources let Shield Advanced judge real application impact.
        - **Faster, more accurate detection:** improves detection sensitivity and reduces false positives.
        - **SRT engagement:** proactive engagement relies on health checks to contact you during an event.

#### Advanced Questions

1. Build a cost-benefit case for or against Shield Advanced for a mid-sized e-commerce company with USD 2 million monthly online revenue, considering attack likelihood, downtime cost, scaling costs, SRT value and included WAF charges.

    ??? success "Check your answer"

        A good answer covers:

        - **Cost:** about USD 3,000 per month plus data transfer fees (verify current pricing).
        - **Benefit:** DDoS cost protection for scaling charges, SRT support, advanced detection and included WAF charges for protected resources.
        - **Downtime cost:** about USD 2 million per month equals roughly USD 2,700 per hour, so a few hours of avoided downtime pays the subscription.
        - **Likelihood:** e-commerce sites face frequent attacks during promotions.
        - **Conclusion:** justified for this company, especially across many resources in the organisation.

2. Design a layered defence against a large credential stuffing campaign using residential proxies, combining WAF, Cognito or application controls, and monitoring, and describe how you would measure effectiveness.

    ??? success "Check your answer"

        A good answer covers:

        - **WAF:** Account Takeover Prevention, Bot Control, rate-based rules with aggregation beyond IP (for example headers or labels), and IP reputation lists.
        - **Application or Cognito:** MFA, compromised credential detection, adaptive authentication.
        - **Monitoring:** login success and failure rates, ATP labels, and anomalies in CloudWatch dashboards.
        - **Measurement:** compare failed and successful logins per volume and the number of compromised accounts before and after.

3. Critically evaluate the claim "we have a WAF, so we are protected against the OWASP Top 10".

    ??? success "Check your answer"

        A good answer covers:

        - **WAF strengths:** injection and some known-pattern attacks.
        - **Gaps:** broken access control, insecure design, cryptographic failures, vulnerable components (except via virtual patches), logging failures and business logic flaws.
        - **Bypass:** encoding tricks and false negatives.
        - **Conclusion:** WAF is one layer, not a substitute for secure coding, testing and least privilege.

4. A zero-day vulnerability in a widely used web framework is announced on a Friday evening. Describe how your organisation uses WAF, Firewall Manager and automation to virtually patch 80 applications within hours, and how you validate the protection.

    ??? success "Check your answer"

        A good answer covers:

        - **Virtual patch:** create a custom rule or update managed rules (for example known bad inputs) in Count mode.
        - **Firewall Manager:** deploy the rule group across all 80 applications in all accounts.
        - **Validate:** test with safe exploit attempts and verify blocks in logs; switch to Block after checking false positives.
        - **Automation:** IaC pipelines and Firewall Manager policies; monitor via logs and dashboards.
        - **Follow-up:** application patching remains necessary.

5. Design an automated feedback loop from GuardDuty, WAF logs and Shield events to WAF IP sets and rules, including safeguards against blocking legitimate users and against unbounded growth of block lists.

    ??? success "Check your answer"

        A good answer covers:

        - **Sources:** GuardDuty findings, WAF logs and Shield events through EventBridge.
        - **Automation:** Lambda adds offending IPs to WAF IP sets.
        - **Safeguards:** allow-lists for partners and internal ranges, confidence thresholds, and avoiding blocking shared NAT or CGNAT ranges.
        - **Expiry:** entries expire after a time-to-live to prevent unbounded growth.
        - **Monitoring:** alert on unusual block volumes and record each change.

---

## 8.3 Data Protection and Encryption

### 8.3.1 Encryption at Rest with AWS KMS

#### Beginner Questions

1. What is the maximum plaintext size for the KMS `Encrypt` API, and what technique is used for larger data?

    ??? success "Check your answer"

        A good answer covers:

        - **Limit:** 4 KB (4,096 bytes) of plaintext.
        - **Larger data:** envelope encryption, where a data key encrypts the data and KMS encrypts the data key.
        - **Why:** only the small data key travels to KMS, so bulk data is encrypted locally, quickly and without per-byte KMS calls.
        - **Example:** S3, EBS and RDS all use envelope encryption with `GenerateDataKey`.

2. Name the three ownership types of KMS keys.

    ??? success "Check your answer"

        A good answer covers:

        - **AWS owned keys:** owned and managed by AWS, used across many accounts, invisible to you.
        - **AWS managed keys:** created in your account by a service (for example `aws/s3`), managed by AWS.
        - **Customer managed keys:** created and fully controlled by you, including key policy and rotation.

3. What two values does `GenerateDataKey` return, and what should be done with each?

    ??? success "Check your answer"

        A good answer covers:

        - **Plaintext data key:** used to encrypt the data locally, then removed from memory.
        - **Encrypted data key:** stored alongside the encrypted data and sent to KMS for decryption later.
        - **Never store plaintext:** the plaintext data key must not be written to disk or logs.
        - **Decryption:** later, KMS decrypts the encrypted data key, which then decrypts the data locally.

4. What is the range of the deletion waiting period for a KMS key?

    ??? success "Check your answer"

        A good answer covers:

        - **Range:** 7 to 30 days (default 30).
        - **Purpose:** allows cancelling an accidental deletion.
        - **During the period:** the key is in `PendingDeletion` state and cannot be used, so any dependency shows up as failures.
        - **After deletion:** data encrypted under the key is permanently unrecoverable; consider disabling the key instead.

5. State one benefit of SSE-KMS over SSE-S3.

    ??? success "Check your answer"

        A good answer covers:

        - **Control and audit:** customer managed keys give key policy access control and CloudTrail records of each key use.
        - **Separation of duties:** reading data requires both S3 and KMS permissions.
        - **Contrast:** SSE-S3 uses S3-managed keys with no customer-controlled key policy and no per-use KMS audit.
        - **Trade-off:** SSE-KMS adds KMS request cost and quotas, reduced by S3 Bucket Keys.

#### Intermediate Questions

1. Write a key policy statement that allows a role to decrypt only through Amazon S3 in one Region.

    ??? success "Check your answer"

        A good answer covers:

        - **Principal:** the role ARN.
        - **Action:** `kms:Decrypt`.
        - **Condition:** `kms:ViaService` equal to `s3.REGION.amazonaws.com`.
        - **Effect:** the role can decrypt only when S3 calls KMS on its behalf in that Region.

2. Explain why EBS uses grants and how the `kms:GrantIsForAWSResource` condition enables this safely.

    ??? success "Check your answer"

        A good answer covers:

        - **Why grants:** EBS needs to use the key when attaching or reading volumes, often long after the original request, so it creates a grant.
        - **Delegation:** grants give temporary, scoped permission to an AWS service.
        - **Safety:** `kms:GrantIsForAWSResource` allows `kms:CreateGrant` only when the request comes from an integrated AWS service, not directly from the user.

3. Compare automatic rotation, on-demand rotation and alias-based manual rotation, including which key types support each.

    ??? success "Check your answer"

        A good answer covers:

        - **Automatic rotation:** KMS creates new key material on a schedule (default 365 days, configurable); supported only for symmetric customer managed keys with KMS-generated material; AWS managed keys rotate every year automatically.
        - **On-demand rotation:** immediately rotate key material for symmetric customer managed keys, including keys with imported key material (`EXTERNAL` origin).
        - **Manual rotation via alias:** create a new key and repoint the alias; required for asymmetric keys, HMAC keys and keys in custom key stores, which support neither automatic nor on-demand rotation.
        - **Old data:** automatic and on-demand rotation keep old material for decryption; manual rotation needs the old key retained.

4. Explain how S3 Bucket Keys reduce cost and what changes in CloudTrail when they are enabled.

    ??? success "Check your answer"

        A good answer covers:

        - **Bucket Key:** S3 uses a bucket-level key derived from the KMS key to generate data keys for objects.
        - **Cost:** fewer calls to KMS, lowering request costs (by up to about 99 per cent).
        - **CloudTrail change:** KMS events reference the bucket ARN rather than each object ARN, and there are far fewer events.

5. Describe the permissions required for an S3 bucket with SSE-KMS to send notifications to an encrypted SQS queue.

    ??? success "Check your answer"

        A good answer covers:

        - **S3 permissions:** the queue policy must allow `s3.amazonaws.com` to `sqs:SendMessage`, with `aws:SourceArn` and `aws:SourceAccount` conditions.
        - **KMS permissions:** the queue's key must be a customer managed key whose key policy allows `s3.amazonaws.com` to use `kms:GenerateDataKey` and `kms:Decrypt`.
        - **Note:** the AWS managed key `aws/sqs` cannot be used because its policy cannot be changed.

#### Advanced Questions

1. Design a multi-tenant encryption scheme for 5,000 tenants that supports tenant-level audit and tenant offboarding, comparing key-per-tenant with shared key plus encryption context in cost, quota and security.

    ??? success "Check your answer"

        A good answer covers:

        - **Key-per-tenant:** strongest isolation, simple per-tenant audit and crypto-shredding; costs about USD 1 per key per month (about USD 5,000 per month) and needs quota planning.
        - **Shared key plus encryption context:** cheaper and simpler; context such as `tenantId` appears in CloudTrail for audit and can be enforced in policies.
        - **Offboarding:** key-per-tenant allows key deletion; shared key requires deleting data.
        - **Hybrid:** shared key for most tenants, dedicated keys for high-value tenants.

2. A regulator requires that the cloud provider can never decrypt customer data. Evaluate standard KMS, CloudHSM key store, external key store and client-side encryption against this requirement and against availability.

    ??? success "Check your answer"

        A good answer covers:

        - **Standard KMS:** AWS operates the HSMs, so the requirement may not be met in a strict reading; very high availability.
        - **CloudHSM key store:** you control the HSM cluster; better control, more operational burden.
        - **External key store (XKS):** key material outside AWS, decryption depends on external HSM availability and latency.
        - **Client-side encryption:** data never reaches AWS in plaintext; strongest but adds application complexity.
        - **Trade-off:** more control means more availability risk for you to manage.

3. Design a disaster recovery strategy for encrypted RDS, S3 and client-side encrypted DynamoDB data across two Regions, stating where multi-Region keys are and are not needed.

    ??? success "Check your answer"

        A good answer covers:

        - **RDS:** cross-Region snapshot copies re-encrypt with a key in the target Region; a multi-Region key is not required.
        - **S3:** cross-Region replication can re-encrypt with a target-Region key; multi-Region keys help if objects must be decryptable with the same key.
        - **Client-side encrypted DynamoDB:** global tables replicate ciphertext, so multi-Region keys are needed to decrypt in the second Region.
        - **Testing:** regular DR tests that include decryption.

4. An attacker obtained an access key for a developer role for six hours. Describe how you would use CloudTrail KMS events to determine exactly which data was exposed.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudTrail search:** filter KMS events (`Decrypt`, `GenerateDataKey`) by the compromised access key ID and time window.
        - **Encryption context:** reveals which resources, such as S3 object or bucket ARNs or DynamoDB tables, were decrypted.
        - **Correlate:** with S3 data events and other service logs.
        - **Scope:** results show exactly what data was decrypted and therefore exposed.

5. Critically evaluate the claim "all our data is encrypted, therefore it is secure".

    ??? success "Check your answer"

        A good answer covers:

        - **Encryption protects against:** media theft and unauthorised storage access.
        - **Not protected:** compromised credentials with decrypt permission, application vulnerabilities, misconfiguration and insiders.
        - **Additional needs:** least privilege, monitoring, access control and integrity checks.
        - **Conclusion:** encryption is necessary but not sufficient.

### 8.3.2 Encryption in Transit with AWS Certificate Manager

#### Beginner Questions

1. What is the difference between TLS 1.2 and TLS 1.3 in handshake round trips?

    ??? success "Check your answer"

        A good answer covers:

        - **TLS 1.2:** full handshake needs two round trips.
        - **TLS 1.3:** full handshake needs one round trip, with optional zero round trip resumption.
        - **Removed weaknesses:** TLS 1.3 drops legacy algorithms such as static RSA key exchange and CBC-mode ciphers.
        - **Forward secrecy:** mandatory in TLS 1.3, so compromise of a server key does not expose past sessions.

2. In which Region must a certificate for CloudFront be requested?

    ??? success "Check your answer"

        A good answer covers:

        - **Region:** US East (N. Virginia), `us-east-1`.
        - **Reason:** CloudFront is a global service whose configuration is managed from `us-east-1`.
        - **Other services:** ALB and API Gateway Regional endpoints need the certificate in their own Region.
        - **Note:** the same applies to CloudFront-scope WAF web ACLs.

3. Name two validation methods for ACM public certificates.

    ??? success "Check your answer"

        A good answer covers:

        - **DNS validation:** add a CNAME record to the domain.
        - **Email validation:** approve an email sent to domain contacts.
        - **Preference:** DNS validation, because ACM can renew automatically while the CNAME remains.
        - **Email limitation:** email validation needs a human to approve renewals.

4. What does HSTS instruct a browser to do?

    ??? success "Check your answer"

        A good answer covers:

        - **HSTS:** instructs the browser to use only HTTPS for the domain for a set period.
        - **Protection:** prevents downgrade attacks and accidental HTTP connections.
        - **Mechanism:** sent as the `Strict-Transport-Security` response header with a `max-age` value.
        - **Options:** `includeSubDomains` and preload lists extend protection; CloudFront response headers policies can add it.

5. Which metric reports the remaining validity of an ACM certificate?

    ??? success "Check your answer"

        A good answer covers:

        - **Metric:** `DaysToExpiry` in the `AWS/CertificateManager` namespace.
        - **Frequency:** emitted daily per certificate.
        - **Use:** create a CloudWatch alarm when it falls below a threshold, for example 30 days.
        - **Complement:** EventBridge ACM expiry events and the Config rule `acm-certificate-expiration-check`.

#### Intermediate Questions

1. Compare TLS termination, re-encryption and passthrough on AWS load balancers.

    ??? success "Check your answer"

        A good answer covers:

        - **Termination:** TLS ends at the load balancer; traffic to targets is plaintext; WAF and routing can see content.
        - **Re-encryption:** load balancer decrypts and then encrypts to targets; end-to-end encryption with inspection.
        - **Passthrough:** NLB TCP listener passes encrypted traffic to targets; targets terminate TLS; no Layer 7 inspection.

2. Explain ALB mTLS verify mode and passthrough mode.

    ??? success "Check your answer"

        A good answer covers:

        - **Verify mode:** the ALB validates the client certificate against a trust store and rejects invalid ones.
        - **Passthrough mode:** the ALB forwards the client certificate chain in headers to targets, which perform validation.
        - **Trust store:** verify mode uses a trust store of CA certificates, stored in S3, with optional revocation lists.
        - **Choice:** verify mode offloads validation to the ALB; passthrough suits applications that need custom validation logic.

3. Write a bucket policy statement that denies non-TLS requests.

    ??? success "Check your answer"

        A good answer covers:

        - **Effect:** Deny.
        - **Principal and Action:** `*`, `s3:*`.
        - **Resource:** the bucket ARN and the bucket ARN with `/*`.
        - **Condition:** `Bool` on `aws:SecureTransport` equal to `false`.

4. Explain when AWS Private CA is required instead of ACM public certificates.

    ??? success "Check your answer"

        A good answer covers:

        - **Internal names:** for internal service endpoints that do not use public domains.
        - **mTLS client certificates:** issuing certificates to devices, services or partners.
        - **Installable certificates:** when certificates need to be exported and installed on servers (private certificates can be exported).
        - **Custom policies:** specific validity periods or extensions.

5. Describe how to monitor imported certificates that ACM cannot renew.

    ??? success "Check your answer"

        A good answer covers:

        - **Metric:** CloudWatch `DaysToExpiry` alarms.
        - **Events:** EventBridge rules on ACM expiry events.
        - **Config:** the `acm-certificate-expiration-check` rule.
        - **Ownership:** each imported certificate has an owner and runbook.

#### Advanced Questions

1. Design end-to-end encryption for CloudFront, ALB, ECS and Aurora, stating the certificate source and TLS policy at each hop.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudFront:** ACM public certificate in `us-east-1`; modern TLS policy (TLS 1.2 minimum, TLS 1.3 where possible).
        - **ALB:** ACM public certificate; HTTPS listener with a TLS 1.2 or 1.3 security policy.
        - **ECS:** private certificate from AWS Private CA, or Service Connect TLS.
        - **Aurora:** RDS-provided certificates; enforce TLS with database parameters.

2. Evaluate VPC Lattice, ECS Service Connect and Istio for service-to-service encryption and identity in a mixed ECS and EKS estate.

    ??? success "Check your answer"

        A good answer covers:

        - **VPC Lattice:** managed service networking with IAM auth policies across VPCs and accounts; supports both ECS and EKS; simplest cross-platform option.
        - **ECS Service Connect:** managed within ECS only, TLS with Private CA; good for ECS-only estates.
        - **Istio:** rich mTLS, identity and traffic policy on EKS; heavy operational burden and limited ECS support.
        - **Recommendation:** VPC Lattice for a mixed estate, with service mesh only where advanced features are required.

3. Explain the operational impact of shrinking public certificate validity periods and how to prepare an organisation for it.

    ??? success "Check your answer"

        A good answer covers:

        - **Impact:** certificates must be renewed much more often (validity moving from 398 to 200 days from 2026, towards 47 days by 2029), so manual processes fail.
        - **Preparation:** inventory all certificates, use ACM or ACME automation, use DNS validation, and monitor expiry.
        - **Eliminate manual work:** replace imported certificates where possible with managed renewal.

4. Design a private PKI hierarchy with AWS Private CA for 50 accounts, including sharing, revocation and short-lived certificates.

    ??? success "Check your answer"

        A good answer covers:

        - **Hierarchy:** offline or tightly controlled root CA in a security account, subordinate CAs per environment or Region.
        - **Sharing:** AWS RAM shares subordinate CAs with accounts.
        - **Revocation:** CRL or OCSP.
        - **Short-lived certificates:** short-lived certificate mode for service identities where revocation is unnecessary.
        - **Governance:** restricted issuance permissions and CloudTrail auditing.

5. Discuss whether TLS termination at a managed load balancer satisfies a requirement that "no third party may see plaintext", and propose alternatives.

    ??? success "Check your answer"

        A good answer covers:

        - **Issue:** the load balancer decrypts traffic, so AWS-managed infrastructure handles plaintext.
        - **Interpretation:** under a strict reading, termination does not satisfy the requirement.
        - **Alternatives:** NLB TLS passthrough, end-to-end application encryption, or client-side encryption.
        - **Trade-off:** lose WAF and Layer 7 features at the load balancer.

### 8.3.3 Secrets Management with AWS Secrets Manager

#### Beginner Questions

1. Why should secrets not be stored in source code or plain environment variables?

    ??? success "Check your answer"

        A good answer covers:

        - **Leakage:** source code is shared, copied and stored in Git history.
        - **Environment variables:** visible in consoles, logs, process listings and crash reports.
        - **Rotation:** hard-coded secrets require redeployment to change.
        - **Better approach:** store secrets in Secrets Manager and retrieve at runtime with IAM.

2. What is the maximum size of a Secrets Manager secret?

    ??? success "Check your answer"

        A good answer covers:

        - **Maximum size:** 64 KB.
        - **Large values:** store larger data elsewhere (for example encrypted S3 objects) and keep only a reference or key in the secret.
        - **Comparison:** Parameter Store standard parameters are limited to 4 KB and advanced parameters to 8 KB.
        - **Versions:** each secret value is stored as a version identified by staging labels.

3. Name the four steps of a rotation Lambda function.

    ??? success "Check your answer"

        A good answer covers:

        - **createSecret:** generate a new secret and store it as AWSPENDING.
        - **setSecret:** set the new credential in the target system.
        - **testSecret:** test the new credential.
        - **finishSecret:** move AWSCURRENT to the new version.

4. Which ECS role retrieves secrets referenced in the `secrets` field?

    ??? success "Check your answer"

        A good answer covers:

        - **Role:** the task execution role.
        - **Timing:** the ECS agent uses this role to retrieve secrets before the container starts, injecting them as environment variables.
        - **Permissions:** `secretsmanager:GetSecretValue` (or `ssm:GetParameters`) and `kms:Decrypt` for customer managed keys.
        - **Contrast:** the task role is used by application code at runtime.

5. State one difference between Secrets Manager and Parameter Store Standard.

    ??? success "Check your answer"

        A good answer covers:

        - **Rotation:** Secrets Manager supports built-in rotation; Parameter Store Standard does not.
        - **Cost:** Secrets Manager charges per secret; Parameter Store Standard is free.
        - **Size:** Secrets Manager 64 KB; Parameter Store Standard 4 KB.

#### Intermediate Questions

1. Explain how RDS-managed master user passwords work and why they are preferable to a password in a template.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** RDS creates and stores the master password in Secrets Manager and rotates it automatically.
        - **Benefit:** the password never appears in templates, state files or logs.
        - **Access:** applications retrieve it with IAM permissions.

2. Describe the permissions needed to read a secret from another account.

    ??? success "Check your answer"

        A good answer covers:

        - **Resource policy:** on the secret, allowing the other account's role to call `secretsmanager:GetSecretValue`.
        - **Identity policy:** in the other account allowing access to the secret ARN.
        - **KMS:** the secret must use a customer managed key whose key policy allows `kms:Decrypt` by the other account's role.
        - **Note:** the default `aws/secretsmanager` key cannot be used cross-account.

3. Compare the Secrets Store CSI Driver with ASCP and External Secrets Operator on EKS.

    ??? success "Check your answer"

        A good answer covers:

        - **Secrets Store CSI Driver with ASCP:** mounts secrets as files in pods, with optional sync to Kubernetes Secrets; retrieves from AWS directly using pod identity.
        - **External Secrets Operator:** syncs secrets into Kubernetes Secrets; supports many providers.
        - **Trade-off:** CSI avoids storing secrets in etcd by default; ESO is simpler for applications expecting Kubernetes Secrets.

4. Explain how the Parameters and Secrets Lambda Extension reduces latency and cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Local cache:** the extension caches secrets and parameters in the execution environment.
        - **Fewer API calls:** reduces calls to Secrets Manager and Parameter Store.
        - **Latency:** cached responses are faster than network calls.
        - **Cost:** fewer API calls reduce charges.

5. Design an EventBridge-based notification for failed rotations.

    ??? success "Check your answer"

        A good answer covers:

        - **Event source:** Secrets Manager rotation failure events (`RotationFailed`) delivered to EventBridge.
        - **Rule:** match the event pattern for rotation failures.
        - **Target:** SNS topic or incident management system.
        - **Context:** include the secret ARN and error details in the notification.

#### Advanced Questions

1. Design zero-downtime credential rotation for a high-throughput Aurora application using connection pooling and RDS Proxy.

    ??? success "Check your answer"

        A good answer covers:

        - **Alternating users rotation:** two database users alternate, so one is always valid during rotation.
        - **RDS Proxy:** retrieves credentials from Secrets Manager and maintains pooled connections, so applications are unaffected by rotation.
        - **Application:** refreshes credentials using a caching client or proxy IAM authentication.
        - **Testing:** rotate in staging under load to confirm zero downtime.

2. Evaluate a centralised secrets account against per-account secrets for a 60-account organisation.

    ??? success "Check your answer"

        A good answer covers:

        - **Centralised:** single point of governance and audit; but cross-account access requires resource policies, customer managed keys, and creates a large blast radius.
        - **Per-account:** isolation and simpler permissions, but harder to govern consistently.
        - **Recommendation:** per-account secrets with central guardrails, monitoring and IaC, plus a central account only for truly shared secrets.

3. Propose a strategy to eliminate as many secrets as possible from a microservice platform, and justify which remain.

    ??? success "Check your answer"

        A good answer covers:

        - **Replace with IAM:** IAM database authentication, roles for AWS services, IRSA or Pod Identity.
        - **Managed credentials:** RDS-managed passwords, OIDC federation for pipelines.
        - **Remaining secrets:** third-party API keys and legacy systems that cannot use IAM.
        - **Justification:** fewer secrets mean less to rotate, leak or manage.

4. Design secret replication and failover for an active-passive multi-Region application, including rotation behaviour during failover.

    ??? success "Check your answer"

        A good answer covers:

        - **Replication:** replicate secrets to the secondary Region.
        - **Rotation:** occurs in the primary Region and changes are replicated.
        - **Failover:** promote replicas to standalone secrets if the primary Region fails; rotation must then be configured in the new Region.
        - **Testing:** regular DR tests that include secret retrieval and database connections.

5. Estimate the monthly Secrets Manager and KMS cost for 300 secrets, 5 replica Regions for 50 of them, and 20 million retrievals per month with and without caching, and discuss the results (state your pricing assumptions and verify them).

    ??? success "Check your answer"

        A good answer covers:

        - **Assumptions (verify):** USD 0.40 per secret per month (replicas charged as secrets), USD 0.05 per 10,000 API calls, KMS about USD 0.03 per 10,000 requests for customer managed keys.
        - **Secrets:** (300 + 50 x 5) = 550 secrets x 0.40 = about USD 220 per month.
        - **Without caching:** 20 million calls / 10,000 x 0.05 = USD 100; KMS about USD 60; total about USD 380.
        - **With caching:** API calls drop by orders of magnitude, so total approaches USD 220.
        - **Conclusion:** storage costs dominate with caching; caching mainly reduces latency and API charges.


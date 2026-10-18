# Unit 3: Practice Questions

## 3.1 Amazon EKS Architecture

### Beginner Questions

1. Draw the EKS split architecture and label which components AWS operates and which you operate. State one consequence of that split for troubleshooting.

    ??? success "Check your answer"

        A good answer covers:

        - **AWS side:** the control plane (`kube-apiserver`, `etcd`, scheduler, controller managers, IAM authenticator) runs in an AWS-owned VPC across multiple Availability Zones; AWS patches, scales and replaces it.
        - **Your side:** the data plane in your VPC: nodes (EC2 or Fargate), `kubelet`, `kube-proxy`, the container runtime, your Pods, and the add-ons and controllers you install.
        - **The link:** nodes connect out to the API endpoint; the control plane reaches in through cross-account ENIs placed in your subnets (used by `exec`, `logs` and webhooks).
        - **Troubleshooting consequence:** control plane faults show as API errors and are AWS's to fix, whereas Pods that will not start or schedule are almost always a data plane problem you own; you also cannot inspect `etcd` or control plane hosts directly, only their logs if control plane logging is enabled.

2. Calculate the maximum number of Pods on an `m5.xlarge` node (4 ENIs, 15 IPs per ENI) without prefix delegation, and explain each term in the formula.

    ??? success "Check your answer"

        A good answer covers:

        - **Formula:** max Pods = ENIs x (IPs per ENI - 1) + 2.
        - **Worked result:** 4 x (15 - 1) + 2 = 4 x 14 + 2 = **58 Pods**.
        - **ENIs x IPs per ENI:** the VPC CNI gives every Pod a real secondary IP from the node's ENIs, so the instance type's ENI and IP limits cap Pod density.
        - **Minus 1:** each ENI's primary IP belongs to the ENI itself and is not handed to Pods.
        - **Plus 2:** host-network Pods such as the VPC CNI (`aws-node`) and `kube-proxy` use the node's own IP and do not consume a secondary address.

3. Explain the difference between the `Unauthorized` and `Forbidden` errors when running `kubectl`, and state the fix for each.

    ??? success "Check your answer"

        A good answer covers:

        - **`Unauthorized`:** authentication or mapping failed; the cluster does not recognise the IAM principal (no access entry, or the wrong AWS identity or expired credentials are active).
        - **Fix for `Unauthorized`:** check `aws sts get-caller-identity`, then have a cluster administrator create an access entry for that principal.
        - **`Forbidden`:** the principal is recognised, but its access policy or RBAC binding does not permit the verb on that resource or namespace.
        - **Fix for `Forbidden`:** associate the right access policy or create the RBAC Role/RoleBinding, scoped to the namespace and verbs needed.
        - **Key point:** IAM permissions such as `AdministratorAccess` do not grant anything inside Kubernetes on their own.

4. Name the three cluster endpoint access modes and give one situation in which each is appropriate.

    ??? success "Check your answer"

        A good answer covers:

        - **Public only:** API reachable from the internet, limited by a CIDR allow-list; acceptable for development or short-lived lab clusters.
        - **Public and private:** allow-listed internet access for engineers plus a private path so nodes stay inside the VPC; a common production choice.
        - **Private only:** API reachable only from the VPC or connected networks (VPN, Direct Connect, bastion, in-VPC runners); for regulated environments.
        - **Caveat:** plan the administrator and CI/CD path before going private-only, or the team locks itself out.

5. State three things that AWS Fargate on EKS cannot do, and explain why each limitation follows from Fargate's design.

    ??? success "Check your answer"

        A good answer covers:

        - **No DaemonSets:** a DaemonSet runs one Pod per node, and on Fargate each Pod gets its own micro-VM, so there is no shared node.
        - **No privileged containers or `hostNetwork`/`hostPort`:** the host belongs to AWS and there is no customer host network to join.
        - **No GPUs:** capacity is AWS-chosen standard compute, not an instance type you select.
        - **No EBS volumes:** EBS attaches to an instance you control; use EFS instead.
        - **No EKS Pod Identity:** its agent is a DaemonSet, so Fargate Pods use IRSA.
        - **Any three, each tied to "there is no node you own"**, earns full marks.

### Intermediate Questions

1. A Pod is stuck in `ContainerCreating` with `failed to assign an IP address to container`, while node CPU is at 15 per cent. Explain the mechanism, name three remedies in increasing order of disruption, and state one drawback of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** the VPC CNI cannot give the Pod an IP: either the node has reached its ENI/IP limit or, more often when CPU is idle, the subnet has run out of free addresses.
        - **Remedy 1 (least disruptive):** tune the CNI warm pool (`WARM_IP_TARGET`, `MINIMUM_IP_TARGET`) to stop nodes hoarding IPs; drawback: more EC2 API calls and slower Pod start when the pool is empty.
        - **Remedy 2:** enable prefix delegation (a `/28` per slot); drawback: needs contiguous free `/28` blocks in the subnet and new nodes to pick up the higher Pod limit.
        - **Remedy 3:** add a secondary VPC CIDR (for example `100.64.0.0/10`) with custom networking; drawback: nodes must be replaced and the primary ENI no longer hosts Pods, reducing Pods per node.
        - **Remedy 4 (most disruptive):** rebuild in larger subnets or as an IPv6 cluster; drawback: a new cluster and migration.
        - **Lesson:** size subnets for Pod count, not node count.

2. Explain how IRSA gives a Pod an IAM role, naming every component involved, and state two reasons EKS Pod Identity was introduced afterwards and one reason IRSA is still required.

    ??? success "Check your answer"

        A good answer covers:

        - **Components:** the cluster's OIDC issuer; an IAM OIDC identity provider registered for it; an IAM role whose trust policy names that provider and conditions on `sub` = `system:serviceaccount:<ns>:<name>`; the ServiceAccount annotated with `eks.amazonaws.com/role-arn`.
        - **Runtime:** a mutating webhook injects a projected ServiceAccount token plus `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE`; the AWS SDK calls `sts:AssumeRoleWithWebIdentity` and receives temporary credentials.
        - **Why Pod Identity was introduced (two of):** no OIDC provider per cluster; no trust-policy edit per cluster, so roles are reusable across clusters; associations managed through the EKS API; session tags (cluster, namespace, ServiceAccount) for attribute-based access control.
        - **Why IRSA is still required:** Pod Identity is not supported on Fargate (its agent is a DaemonSet), so Fargate Pods must use IRSA.

3. A cluster's deployments all fail with `failed calling webhook ... context deadline exceeded` while `kubectl get pods` still works. Explain why the two behave differently, identify the likely cause, and give the fix.

    ??? success "Check your answer"

        A good answer covers:

        - **Why they differ:** `kubectl get pods` is a read served by the API server from `etcd`; creates and updates pass through admission, which calls webhooks.
        - **Path:** the API server reaches webhooks inbound through the cross-account ENIs into your VPC, to the webhook Service's Pods on the nodes.
        - **Likely cause:** a recent security group change (or NetworkPolicy) blocks traffic from the cluster security group to the nodes on the webhook port (often 443 or 9443), so calls time out.
        - **Fix:** allow the control plane security group to reach the nodes on the webhook port; verify with the webhook Pods' logs and a test deployment.
        - **Hardening:** keep `timeoutSeconds` short and scope or set `failurePolicy` appropriately so one webhook cannot block the whole cluster.

4. Compare instance-mode and IP-mode target groups for the AWS Load Balancer Controller. Explain what makes IP mode possible on EKS and name two concrete benefits.

    ??? success "Check your answer"

        A good answer covers:

        - **Instance mode:** the load balancer targets a NodePort on every node, then `kube-proxy` forwards to a Pod, possibly on another node or AZ.
        - **IP mode:** the load balancer targets Pod IPs directly.
        - **What makes IP mode possible:** the VPC CNI gives every Pod a routable VPC IP address, so the load balancer can register it as a target.
        - **Benefit 1:** one fewer hop, so lower latency and no cross-node or cross-AZ bounce.
        - **Benefit 2:** per-Pod health checks and draining are accurate; it also works on Fargate, where there is no instance to register.

5. Explain what Kubernetes `requests` and `limits` each control, and describe a specific failure that results from setting requests too low and another from setting them too high.

    ??? success "Check your answer"

        A good answer covers:

        - **Requests:** used by the scheduler to decide which node has room; a request reserves capacity whether or not it is used.
        - **Limits:** enforced at runtime; exceeding a memory limit kills the container (`OOMKilled`), exceeding a CPU limit throttles it.
        - **Too low:** nodes are overpacked, Pods contend for CPU and the node hits memory pressure, causing evictions or OOM kills under load.
        - **Too high:** Pods stay `Pending` for lack of room and nodes run mostly idle, wasting money (and on Fargate the oversized request is what you pay).
        - **Good practice:** base requests on observed usage; memory request equal to memory limit is a safe start.

### Advanced Questions

1. An organisation runs one EKS cluster per team  nineteen in total  and its control plane costs have become a line item in the annual budget. Analyse the trade-offs of consolidating to three clusters. Address blast radius, upgrade coordination, noisy neighbours, isolation mechanisms available within a cluster, cost attribution, and the specific circumstances that would justify keeping a cluster separate.

    ??? success "Check your answer"

        A good answer covers:

        - **Blast radius:** fewer clusters mean a bad upgrade, webhook or add-on affects many teams at once.
        - **Upgrade coordination:** each cluster upgrade must wait for every team's workloads to be compatible; fewer clusters, but harder ones.
        - **Noisy neighbours:** shared nodes need ResourceQuotas, LimitRanges, accurate requests and possibly dedicated node pools with taints.
        - **In-cluster isolation:** namespaces, RBAC, NetworkPolicies, per-workload IAM roles, Pod Security Admission; these are soft isolation, not a security boundary equal to separate clusters or accounts.
        - **Cost attribution:** use namespace labels with split cost allocation or Kubecost-style tooling; control plane fees saved are small next to node costs.
        - **Keep separate when:** regulatory or hard tenancy isolation is required, workloads differ greatly in risk or upgrade cadence, or production must be isolated from non-production.

2. Design the complete network architecture for an EKS cluster that must support 4,000 Pods across three Availability Zones, connect to an on-premises network over AWS Direct Connect that has already allocated most of the RFC 1918 space, and enforce per-workload network boundaries visible to a non-Kubernetes security team. Specify the addressing scheme, CNI configuration, and segmentation mechanisms, justify each, and identify the requirement your design satisfies least well.

    ??? success "Check your answer"

        A good answer covers:

        - **Addressing:** keep nodes in routable subnets across three AZs, and put Pods in a non-RFC 1918 secondary CIDR such as `100.64.0.0/10` using VPC CNI custom networking (or an IPv6 cluster), so Pods do not consume scarce corporate space.
        - **Capacity:** plan at least about 1,400 Pod IPs per AZ plus headroom; enable prefix delegation to raise Pods per node.
        - **On-premises reach:** traffic from Pods is SNATed to node IPs (or routed via a private NAT gateway) so the on-premises network sees only routable addresses.
        - **Segmentation:** security groups for Pods for the boundaries the security team must see and audit in AWS terms; Kubernetes NetworkPolicies for east-west rules inside the cluster.
        - **Least well satisfied:** visibility to non-Kubernetes staff; NetworkPolicies and SNATed Pod traffic are hard to read in AWS tooling, and security groups for Pods have their own limits (for example per-node branch ENI capacity).

3. A Pod in a public-facing service was compromised through a server-side request forgery vulnerability, and the attacker exfiltrated data from three S3 buckets belonging to unrelated services. Reconstruct the most likely chain of events in detail, identify every design defect that must have been present, and specify the changes  with configuration specifics  that would have limited the incident to the compromised service's own data.

    ??? success "Check your answer"

        A good answer covers:

        - **Likely chain:** the SSRF made the app request `169.254.169.254`; IMDSv1 or a hop limit of 2 let the container reach IMDS; it returned the node instance role's credentials; that role (or a shared broad role) could read many buckets.
        - **Defects:** IMDS reachable from Pods; S3 permissions on the node role; no per-service identity or a role shared across services; wildcard S3 resources; no egress restriction; bucket policies not restricting principals; no detection.
        - **Fix identity:** per-service role through Pod Identity (or IRSA) scoped to that service's bucket ARN and `arn/*` objects only; node role limited to node needs (worker, ECR read).
        - **Fix metadata:** require IMDSv2 with hop limit 1 in the node group launch template.
        - **Defence in depth:** NetworkPolicy denying egress to `169.254.169.254/32`, bucket policies allowing only the owning role, an S3 VPC endpoint policy, and GuardDuty EKS/Runtime Monitoring to detect credential misuse.

4. Critique this proposed platform standard: "All clusters will use public-only endpoints with `0.0.0.0/0` allow-listed for pipeline convenience, the `aws-auth` ConfigMap for access management because it is version-controlled in Git, `t3.medium` nodes for cost, the node instance role for all AWS access to avoid per-service IAM overhead, and Kubernetes version upgrades performed only when a CVE requires it." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.

    ??? success "Check your answer"

        A good answer covers:

        - **Public endpoint open to `0.0.0.0/0`:** exposes the API to the internet; use private or public-and-private with narrow CIDRs, or in-VPC runners.
        - **`aws-auth` ConfigMap:** deprecated, typo-prone and able to lock everyone out; use access entries (API authentication mode), which can also be version-controlled in IaC.
        - **`t3.medium`:** burstable CPU credits throttle under sustained load, and the ENI limit allows only 17 Pods per node.
        - **Node role for all AWS access:** every Pod gets every permission and SSRF exposes all of it; use per-workload Pod Identity or IRSA and IMDS hop limit 1.
        - **Upgrades only on CVE:** clusters drift into extended support (six times the control plane price), eventually forced upgrades, and multi-version jumps with removed APIs; adopt a planned annual cadence.
        - **Further defects:** no private path for nodes, no break-glass access, no least privilege for the pipeline.
        - **Legitimate intent:** pipeline convenience, auditability, low cost and low IAM overhead; satisfy them with in-VPC runners or GitOps, access entries in Terraform, right-sized or Spot/Graviton nodes, and reusable Pod Identity roles.

5. An EKS cluster serving a payments platform must meet a 99.99 per cent availability target. Evaluate honestly what a single well-designed EKS cluster can and cannot deliver against that target. Identify every single point of failure that remains after multi-AZ node distribution, `topologySpreadConstraints`, and PodDisruptionBudgets are in place, and describe what a multi-cluster architecture would add, what it would cost, and how you would decide whether the addition is justified.

    ??? success "Check your answer"

        A good answer covers:

        - **Target:** 99.99 per cent allows about 52 minutes of downtime a year; the EKS SLA for a standard control plane is 99.95 per cent monthly uptime (99.99 per cent only with the paid Provisioned Control Plane tier), though running Pods keep serving during a brief API outage.
        - **Remaining single points of failure:** the cluster as a unit (bad add-on version, admission webhook, upgrade or misapplied manifest affects every AZ); the Region; shared dependencies such as one database, one ALB or DNS configuration; the deployment pipeline itself.
        - **Multi-cluster adds:** independent failure domains, blue/green cluster upgrades, and optionally Regional failover with Route 53 health-checked routing.
        - **Multi-cluster costs:** duplicated nodes and data replication, cross-cluster state and failover complexity, more operational effort; the control plane fee is minor.
        - **Decision:** compare the error budget with the measured frequency of cluster-level incidents, and with the cost of downtime; justify only if those failures would otherwise exceed the budget.

---

## 3.2 Deploying Applications on Amazon EKS

### Beginner Questions

1. Explain the difference between `kubectl create`, `kubectl apply`, and `kubectl replace`, and state which belongs in a declarative workflow and why.

    ??? success "Check your answer"

        A good answer covers:

        - **`kubectl create`:** imperative; creates an object and fails if it already exists.
        - **`kubectl replace`:** imperative; replaces the whole object and fails if it does not exist, discarding fields not in the file.
        - **`kubectl apply`:** declarative; creates or updates the object to match the file, merging changes.
        - **Declarative workflow:** `apply` belongs there, because Git holds the desired state and re-running it is idempotent and reviewable.

2. Name the three probe types, state the question each answers and the action taken when each fails, and give one consequence of confusing liveness with readiness.

    ??? success "Check your answer"

        A good answer covers:

        - **Readiness:** "Can this Pod serve traffic now?" On failure it is removed from Service endpoints until it recovers.
        - **Liveness:** "Is the process stuck?" On failure the container is restarted.
        - **Startup:** "Has a slow app finished starting?" Liveness checks wait until it succeeds.
        - **Consequence of confusion:** a liveness probe that checks the database restarts every replica during a short database outage, turning a blip into a full outage; dependency checks belong in readiness.

3. Explain what `requests` and `limits` control, and state why exceeding a memory limit and exceeding a CPU limit produce different outcomes.

    ??? success "Check your answer"

        A good answer covers:

        - **Requests:** what the scheduler reserves when choosing a node.
        - **Limits:** the runtime ceiling.
        - **Memory over limit:** the container is killed (`OOMKilled`), because memory cannot be taken back from a running process.
        - **CPU over limit:** the container is throttled (slowed) but not killed, because CPU time is compressible and can simply be withheld.

4. State the correct order of an EKS cluster upgrade and explain why the control plane must be upgraded before the nodes.

    ??? success "Check your answer"

        A good answer covers:

        - **Order:** control plane first (one minor version at a time), then add-ons to versions compatible with the new control plane, then nodes by rolling replacement (the EKS User Guide allows nodes before add-ons; the firm rule is control plane first and add-ons compatible with both).
        - **Why control plane first:** `kubelet` may run behind the API server (up to three minor versions) but never ahead of it.
        - **Before starting:** check Upgrade insights and manifests for removed APIs, and rehearse in non-production.

5. Explain in one paragraph why `kubectl edit` should not be used to change production, and describe what should be done instead.

    ??? success "Check your answer"

        A good answer covers:

        - **Why not:** `kubectl edit` changes live state with no review, no record in Git and no reproducibility; the next deployment from Git silently overwrites it (or GitOps reverts it), and nobody can tell what production really runs.
        - **Instead:** change the manifest or values file in Git, review it through a pull request, and let the pipeline or GitOps controller apply it, followed by `kubectl rollout status`.

### Intermediate Questions

1. A Deployment's new Pods enter `ImagePullBackOff` and the rollout does not progress. Describe exactly what Kubernetes does over the following ten minutes, what it does **not** do, and what you would add to the pipeline so this recovers without human intervention.

    ??? success "Check your answer"

        A good answer covers:

        - **What happens:** the new ReplicaSet's Pods retry the pull with increasing back-off (up to about five minutes between attempts); with `maxUnavailable: 0` the old Pods keep serving.
        - **At the deadline:** after `progressDeadlineSeconds` (default 600 seconds) the Deployment's `Progressing` condition becomes `False` with reason `ProgressDeadlineExceeded`.
        - **What it does not do:** it does not roll back, delete the new Pods or alert anyone; the rollout simply stays stalled.
        - **Pipeline addition:** `kubectl rollout status --timeout=...` after every apply, and on failure `kubectl rollout undo` (or `helm upgrade --rollback-on-failure` / `--atomic` in Helm 3, or a progressive delivery controller); also verify the image exists in ECR before deploying.

2. Compare Helm and Kustomize across five dimensions of your choosing, and describe a concrete platform design that uses both. Justify which workloads go to which tool.

    ??? success "Check your answer"

        A good answer covers:

        - **Dimensions (any five):** templating versus overlays; packaging and distribution (Helm charts in registries); release tracking and rollback (Helm revisions, none in Kustomize); learning curve and readability; built into `kubectl` (Kustomize) versus separate tool; suitability for third-party software.
        - **Helm strengths:** packaging reusable applications and installing third-party software (Load Balancer Controller, monitoring stacks).
        - **Kustomize strengths:** plain YAML with small per-environment patches, easy to review.
        - **Combined design:** third-party and shared platform components via Helm charts; in-house services as a Kustomize base plus overlays per environment (or a common in-house Helm chart with Kustomize post-rendering); all applied by GitOps.
        - **Justification:** each tool used where its model fits, with values and overlays committed to Git.

3. A node drain has been blocked for an hour. List four distinct causes, state how you would distinguish them, and give the remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **PodDisruptionBudget allows zero disruptions** (for example `minAvailable` equal to replicas): check `kubectl get pdb -A` for `ALLOWED DISRUPTIONS 0`; relax to `maxUnavailable: 1`.
        - **Replacement Pods cannot schedule** (no spare capacity, affinity or taints), so the PDB never becomes satisfied: look for `Pending` Pods and their events; add capacity or fix constraints.
        - **Unmanaged Pods or Pods with `emptyDir`/local data:** drain refuses them without flags; identify Pods with no owner reference; recreate them under a controller or use the appropriate drain flags knowingly.
        - **Pods stuck terminating** (long `terminationGracePeriodSeconds`, a finalizer, or a hung `preStop`): the Pod shows `Terminating` for a long time; fix the app shutdown or finalizer.
        - **Method:** read the drain output or node group update error first; it names the Pod that cannot be evicted.

4. Explain the security argument for GitOps over a CI pipeline that runs `kubectl apply`. Then describe two failure modes that GitOps introduces and how you would mitigate each.

    ??? success "Check your answer"

        A good answer covers:

        - **Security argument:** with GitOps an in-cluster controller pulls from Git, so no external CI system holds cluster-admin credentials; compromise of CI no longer means compromise of every cluster.
        - **Further benefits:** every change is a reviewed, attributable Git commit, and drift from Git is detected and corrected.
        - **Failure mode 1:** Git becomes the attack path (write access equals deploy access); mitigate with branch protection, mandatory review, signed commits and restricted repository permissions.
        - **Failure mode 2:** self-healing reverts emergency manual fixes or fights other controllers (for example an HPA changing `replicas`); mitigate with a documented break-glass process and ignore rules for controller-owned fields.
        - **Other acceptable mode:** the GitOps controller itself fails or is misconfigured; monitor sync status and alert on failed syncs.

5. A service returns 5xx errors during every deployment despite all Pods reporting `Ready`. Explain the two most likely mechanisms, the single observation that distinguishes them, and the fix for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism 1:** terminating old Pods still receive traffic because load balancer deregistration and endpoint updates lag behind the SIGTERM, so in-flight and new requests fail.
        - **Mechanism 2:** new Pods report `Ready` before the application (or the ALB target health check) is truly ready, so early requests fail.
        - **Distinguishing observation:** whether the errors line up with old Pods terminating (connection resets or 502s from deregistering targets) or with new Pods starting.
        - **Fix for 1:** a `preStop` sleep, graceful shutdown handling, a matching ALB deregistration delay and sufficient `terminationGracePeriodSeconds`.
        - **Fix for 2:** an honest readiness probe and the AWS Load Balancer Controller's Pod readiness gates so a Pod is not ready until the ALB target is healthy.

### Advanced Questions

1. Design the complete deployment architecture for a regulated financial platform where no human may deploy directly to production, every change must be attributable, secrets must never appear in version control, and a bad release must not reach more than five per cent of users before automated validation. Specify the provisioning, packaging, delivery, secret management, and progressive delivery mechanisms; justify each choice; and identify the requirement your design satisfies least completely and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Provisioning:** clusters and AWS resources through IaC (Terraform or eksctl config) run only by a pipeline with reviewed plans; no human production credentials except a logged break-glass role.
        - **Packaging:** Helm or Kustomize with values in Git; images built once, tagged by commit, referenced by digest, scanned and signed.
        - **Delivery:** GitOps (Argo CD or Flux) pulls from protected branches; pull request approval plus Git history, CloudTrail and EKS audit logs give attribution.
        - **Secrets:** AWS Secrets Manager synchronised by External Secrets Operator or the Secrets Store CSI Driver; only references live in Git.
        - **Progressive delivery:** Argo Rollouts or Flagger canary at five per cent using ALB weighted routing, with automated analysis on error rate and latency metrics and automatic abort.
        - **Weakest requirement:** "five per cent of users" is really five per cent of requests unless routing is sticky by user, and database schema changes cannot be canaried; also the break-glass path is a deliberate exception to "no human".

2. An organisation with sixty microservices across four EKS clusters has no consistent deployment approach, no PodDisruptionBudgets, resource requests copied from an old example, and a shared CI role with cluster admin. Produce a prioritised remediation plan. Justify the ordering explicitly in terms of risk reduction per unit of effort, and identify which items you would deliberately defer and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Priority 1:** replace the shared cluster-admin CI role (largest risk, moderate effort): per-cluster, least-privilege identities or GitOps pull.
        - **Priority 2:** PodDisruptionBudgets for critical services (low effort, prevents outages during node maintenance and upgrades).
        - **Priority 3:** right-size requests from observed usage (Container Insights or VPA recommendations), fixing both instability and cost.
        - **Priority 4:** a standard deployment approach (shared chart or Kustomize base, GitOps), migrated service by service, highest-risk services first.
        - **Ordering rationale:** risk reduction per unit of effort; credential exposure is catastrophic and cheap to reduce.
        - **Defer deliberately:** service mesh, progressive delivery and a big-bang migration of all sixty services, until the basics are consistent.

3. Critique this proposed platform standard: "All applications will be packaged as Helm charts with values supplied by `--set` flags in the pipeline for flexibility; the pipeline will run `helm upgrade` and report success when the command returns; images will use branch-name tags so developers can see what is deployed; PodDisruptionBudgets will use `minAvailable` equal to the replica count for maximum availability; and cluster upgrades will be performed only when a security advisory requires them." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.

    ??? success "Check your answer"

        A good answer covers:

        - **`--set` flags:** values leave no record in Git, so deployments are not reproducible; use committed per-environment values files.
        - **Reporting success when `helm upgrade` returns:** it returns before Pods are ready; use `--wait` with a timeout and `--rollback-on-failure` (Helm 4) or `--atomic` (Helm 3), plus rollout status checks.
        - **Branch-name tags:** mutable, so different Pods can run different code, nodes may cache old images and rollback is meaningless; use immutable commit-SHA or semantic tags, ideally by digest, with ECR tag immutability.
        - **PDB `minAvailable` equal to replicas:** blocks every drain and node upgrade; use `maxUnavailable: 1` or `minAvailable` below replicas.
        - **Upgrades only on advisory:** drifts into extended support (six times the control plane price), forced upgrades and multi-version jumps with removed APIs; adopt a planned annual cadence.
        - **Further defects:** no drift detection, no rollback automation, pipeline credentials into the cluster.
        - **Legitimate intent:** flexibility, visibility of what is deployed, availability and low upgrade churn; satisfy them with values files, version labels and Git SHAs, sensible PDBs and a scheduled upgrade calendar.

4. A cluster upgrade completed successfully. Three days later, an unrelated deployment fails with `no matches for kind "HorizontalPodAutoscaler" in version "autoscaling/v2beta2"`, and the team cannot understand why an upgrade three days ago broke something today. Explain the mechanism in full, explain why the failure was delayed, describe every check that would have caught it beforehand, and explain what makes this class of failure particularly serious on EKS specifically.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** `autoscaling/v2beta2` was removed in Kubernetes 1.26; after the upgrade the API server no longer serves that version.
        - **Why delayed:** existing HPA objects are stored internally and served as `autoscaling/v2`, so they kept working; the failure appeared only when a pipeline next applied a manifest still written with the removed `apiVersion`.
        - **Checks that would have caught it:** EKS Upgrade insights; scanning manifests and Helm charts with tools such as `pluto` or `kubent`; the deprecated-API request metrics and audit logs; a dry-run or test deploy against the target version in non-production.
        - **Why serious on EKS:** control plane upgrades can be rolled back only within 7 days and are otherwise one-way, and clusters reaching the end of support are upgraded automatically, so a missed removal can appear without a planned upgrade at all.

5. Argue both sides of the following claim, then give your own position with justification: "For an organisation running fewer than twenty services on AWS, adopting GitOps, Helm, Kustomize, a policy engine, a secrets operator, and a progressive delivery controller costs more in operational complexity than it returns in safety, and a well-written CI pipeline running `kubectl apply` is the correct engineering choice." Address the credential argument, the drift argument, the team-size argument, and what specific threshold would change your answer.

    ??? success "Check your answer"

        A good answer covers:

        - **For the claim:** each tool adds learning, upgrades and failure modes; a small team may lack capacity to operate them; a well-written pipeline with `rollout status` and undo is understandable.
        - **Credential argument:** a push pipeline holds cluster credentials, which GitOps removes; this matters regardless of service count.
        - **Drift argument:** without GitOps, manual changes accumulate silently; with few services and strict discipline the risk is smaller but non-zero.
        - **Team-size argument:** complexity cost falls on a few people; managed or lightweight choices (one GitOps tool, Kustomize only, Secrets Manager with External Secrets) capture most safety at low cost.
        - **Own position:** adopt the cheap, high-value pieces first (GitOps, external secrets, Kustomize) and defer a policy engine and progressive delivery.
        - **Threshold that would change it:** regulatory requirements, several teams sharing clusters, frequent releases with user-visible incidents, or a measured change-failure rate above an agreed level.

---

## 3.3 Amazon EKS Advanced Concepts

### Beginner Questions

1. List five things AWS Fargate on EKS cannot do, and for each explain which property of the Fargate model causes the limitation.

    ??? success "Check your answer"

        A good answer covers:

        - **No DaemonSets:** each Pod runs in its own micro-VM, so there is no shared node to place one per node.
        - **No privileged containers or `hostNetwork`/`hostPort`:** the underlying host belongs to AWS.
        - **No GPUs:** AWS chooses standard capacity; you cannot pick an accelerated instance type.
        - **No EBS volumes:** EBS attaches to an instance you control; use EFS.
        - **No EKS Pod Identity:** its agent is a DaemonSet; use IRSA.
        - **Also acceptable:** no Arm or Windows Pods, IP-mode load balancer targets only, slower Pod start (new micro-VM, no image cache).

2. Explain what a Fargate profile selector consists of, state which part is mandatory, and explain what happens when two profiles match the same Pod.

    ??? success "Check your answer"

        A good answer covers:

        - **Selector:** a namespace (required, wildcards `*` and `?` allowed) plus optional labels; up to five selectors per profile.
        - **Matching rules:** labels within a selector are ANDed; selectors within a profile are ORed; labels alone cannot select a Pod.
        - **Two matching profiles:** Fargate picks the profile whose name sorts first alphanumerically, which may have the wrong subnets or Pod execution role; pin a Pod to a specific profile with the label `eks.amazonaws.com/fargate-profile: <name>`, and better, design non-overlapping selectors.
        - **Remember:** profiles are immutable; changing one means creating a new profile and deleting the old.

3. Describe the steps a managed node group performs during a version update, in order, and state which step PodDisruptionBudgets affect.

    ??? success "Check your answer"

        A good answer covers:

        - **Step 1:** launch new nodes with the new AMI or launch template version.
        - **Step 2:** cordon an old node so nothing new is scheduled there.
        - **Step 3:** drain it, evicting Pods so their controllers recreate them elsewhere.
        - **Step 4:** terminate the old node and repeat, `maxUnavailable` nodes at a time (default one).
        - **PDB effect:** PodDisruptionBudgets govern the drain step; a PDB allowing zero disruptions makes the update fail with `PodEvictionFailure` after about 15 minutes unless forced.

4. Explain the three add-on conflict resolution modes and give one situation in which each is the correct choice.

    ??? success "Check your answer"

        A good answer covers:

        - **`NONE`:** fail the create or update if it would overwrite existing configuration; use when you want to be told about conflicts before anything changes.
        - **`OVERWRITE`:** replace in-cluster changes with the add-on's configuration; use when configuration should come only from IaC and drift must be removed.
        - **`PRESERVE`:** keep in-cluster changes during an update; use when a change made directly in the cluster must survive temporarily while it is moved into `configurationValues`.
        - **Good practice:** put configuration in `configurationValues` in IaC so `OVERWRITE` is safe.

5. Define a CustomResourceDefinition and a controller, and explain in one sentence what an operator is.

    ??? success "Check your answer"

        A good answer covers:

        - **CustomResourceDefinition:** extends the Kubernetes API with a new resource type, stored and served like built-in objects, without modifying the API server.
        - **Controller:** a reconciliation loop that watches objects and acts to make the real world match their desired state.
        - **Operator:** a CRD plus a controller that encodes operational knowledge for managing a specific application or resource (for example the AWS Load Balancer Controller turning Ingress into an ALB).

### Intermediate Questions

1. A Pod requests 3 vCPU and 5 GB of memory on Fargate. Explain what is allocated, what is billed, and why  then describe how you would adjust the request to reduce cost without harming the workload.

    ??? success "Check your answer"

        A good answer covers:

        - **Memory first:** Fargate adds 256 MB for `kubelet`, `kube-proxy` and `containerd`, so 5 GB becomes 5.25 GB.
        - **Rounding:** 3 vCPU is not a valid size, so it rounds up to 4 vCPU, whose smallest memory option is 8 GB; **allocated and billed: 4 vCPU, 8 GB** (shown in the `CapacityProvisioned` annotation).
        - **Waste:** about one vCPU and nearly 3 GB are paid for but unused.
        - **Adjustment:** measure actual usage; if the workload can run with 2 vCPU, request 2 vCPU and 5 GB, which becomes 2 vCPU / 6 GB; or, if it truly needs about 4 vCPU, request 4 vCPU and use the memory that is already paid for.
        - **Principle:** on Fargate, requests are the bill, so size them to valid combinations.

2. Compare managed node groups and Karpenter across provisioning model, scale-out latency, bin packing, consolidation, and operational burden. State which you would choose for a cluster with highly variable, heterogeneous workloads and justify it.

    ??? success "Check your answer"

        A good answer covers:

        - **Provisioning model:** managed node groups scale fixed Auto Scaling groups of predefined instance types (with Cluster Autoscaler); Karpenter launches instances directly for pending Pods, choosing types to fit.
        - **Scale-out latency:** Karpenter is typically faster because it bypasses Auto Scaling group adjustments.
        - **Bin packing:** Karpenter selects right-sized instance types for the pending Pods; node groups are limited to their configured types.
        - **Consolidation:** Karpenter actively replaces or removes underused nodes; node groups only scale in when nodes become empty or underused per the autoscaler.
        - **Operational burden:** node groups are simpler and AWS-managed; Karpenter is another controller to run and upgrade (unless EKS Auto Mode runs it).
        - **Choice for variable, heterogeneous workloads:** Karpenter (or Auto Mode), with a small managed node group to host Karpenter and core add-ons.

3. A Spot node group is causing workload instability. List four distinct causes, state how you would distinguish them from the available signals, and give the remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Too few instance types or pools:** one pool reclaimed repeatedly; check interruption events per instance type; add several compatible types and AZs.
        - **No On-Demand base:** critical services run only on Spot; check where critical Pods are placed; keep an On-Demand group that can carry essential traffic, with Spot above it.
        - **Workloads not interruption-tolerant:** long-running or stateful jobs, or shutdown longer than the two-minute warning; check Pod types and grace periods; move them off Spot or make them checkpoint.
        - **No spread or PDBs:** all replicas land on the same reclaimed pool; check Pod distribution; add `topologySpreadConstraints` and PDBs.
        - **Signals:** EC2 Spot interruption and rebalance recommendation events (EventBridge), Auto Scaling activity history, node age and Kubernetes events.

4. Explain why an EKS add-on's version must be updated between the control plane upgrade and the node upgrade, and describe a specific failure that results from getting this order wrong.

    ??? success "Check your answer"

        A good answer covers:

        - **Why:** EKS does not upgrade add-ons with the control plane, and each add-on version supports specific Kubernetes versions; it must be compatible with both the new control plane and the nodes.
        - **Order logic:** the control plane always goes first; the EKS Best Practices Guide then upgrades add-ons before the data plane, while the EKS User Guide lists nodes before add-ons, so "between" is a recommendation rather than a hard rule; the firm rule is that every add-on version must be compatible with both the control plane and the nodes.
        - **Example failure:** new nodes join with an old VPC CNI or `kube-proxy` version that does not support the new Kubernetes version or AMI, so nodes stay `NotReady` or Services become unreachable.
        - **Another example:** EKS add-ons can be upgraded only one minor version at a time, so an add-on left several versions behind needs several sequential updates before it is compatible.

5. Explain how an admission webhook registered by an operator can cause a cluster-wide outage. Describe the four configuration settings that prevent it and state which of them is not a default in most charts.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** a webhook with `failurePolicy: Fail` that matches Pods or all resources makes every create or update depend on the webhook's Pods; if they are unavailable, every write fails.
        - **Deadlock:** if the webhook also intercepts its own namespace or `kube-system`, its own Pods cannot be recreated.
        - **Setting 1:** `failurePolicy: Ignore` for non-critical webhooks.
        - **Setting 2:** a short `timeoutSeconds` (a few seconds; the default is 10 and the maximum 30).
        - **Setting 3:** a `namespaceSelector` excluding `kube-system` and the webhook's own namespace.
        - **Setting 4:** narrow `rules` or an `objectSelector`, plus the webhook Deployment's resilience (several replicas, PDB, spread); none of the first three is a default (`failurePolicy` defaults to `Fail`, the timeout to 10 seconds, and an empty `namespaceSelector` matches every namespace), and the namespace exclusion is the one most often missing from charts.

### Advanced Questions

1. Design the complete data plane for a multi-tenant SaaS platform running customer-supplied code, GPU inference, steady platform services, and nightly batch processing, with a requirement that no tenant workload shares a kernel with another. Specify the substrate for each workload class, justify each choice from the workload's properties, and identify the requirement your design satisfies least completely and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Customer-supplied code:** Fargate, one micro-VM per Pod, so no shared kernel; IRSA for any AWS access, NetworkPolicies and no route to internal services.
        - **GPU inference:** Fargate has no GPUs, so dedicated GPU nodes (managed node group or Karpenter NodePool) with taints, running only platform inference code; if tenants' models run there, dedicate nodes per tenant.
        - **Steady platform services:** On-Demand managed node groups across three AZs, with Savings Plans.
        - **Nightly batch:** Karpenter on Spot with several instance types, tolerant of interruption.
        - **Justification:** each choice follows from the workload's trust level, hardware need and runtime pattern.
        - **Least well satisfied:** the no-shared-kernel rule for GPU work, which needs per-tenant dedicated nodes at significant cost (or a sandboxed runtime), and Fargate's slower start for customer code.

2. An organisation has accumulated eighteen operators across six clusters with no inventory, no version pinning, and no owners. The next Kubernetes upgrade is blocked. Produce a prioritised plan to unblock the upgrade and to prevent recurrence. Justify the ordering in terms of risk reduction per unit of effort, and state which operators you would expect to remove entirely rather than upgrade.

    ??? success "Check your answer"

        A good answer covers:

        - **Step 1, inventory:** list every operator, its version, CRDs, webhooks and the API versions it uses; assign an owner to each.
        - **Step 2, find blockers:** identify which operators use APIs removed in the target version or do not support it (Upgrade insights, compatibility matrices).
        - **Step 3, remove:** delete unused, duplicate or abandoned operators rather than upgrading them (expect several experiments and overlapping tools); remove their CRDs and webhooks carefully.
        - **Step 4, upgrade blockers:** pin and upgrade the remaining blocking operators in non-production, then proceed with the upgrade.
        - **Prevention:** an approved catalogue, version pinning in IaC/GitOps, named owners, and a pre-upgrade compatibility check.
        - **Rationale:** inventory and removal give the most risk reduction for least effort; upgrading something nobody uses is wasted work.

3. Argue both sides of the following claim, then give your own position: "AWS Controllers for Kubernetes should be the default way developers provision AWS resources, because a single declarative workflow for an application and its dependencies is worth more than the lifecycle independence that Terraform provides." Address garbage collection, blast radius, the controller's permissions, coverage maturity, and what specific class of resource would change your answer.

    ??? success "Check your answer"

        A good answer covers:

        - **For ACK:** one declarative workflow and GitOps for both application and dependencies; developers self-serve; drift is reconciled.
        - **Garbage collection:** deleting a namespace or manifest can delete a production database; mitigate with deletion policies set to retain and with backups.
        - **Blast radius:** a misapplied manifest or a cluster loss can affect AWS resources; Terraform state and lifecycle are independent of any cluster.
        - **Controller permissions:** the ACK controller needs broad IAM rights, making it a high-value target; scope it per service and namespace, with permissions boundaries.
        - **Coverage maturity:** some services and fields are less mature in ACK than in Terraform.
        - **Position:** ACK for application-scoped, disposable resources (queues, buckets for a service); Terraform for long-lived, shared or stateful resources such as databases, VPCs and IAM foundations, which is the class that changes the answer.

4. Critique this proposed platform standard: "All workloads will run on AWS Fargate to eliminate node management; add-ons will be installed once from the latest available manifests and left alone since they rarely change; PodDisruptionBudgets will use `minAvailable` equal to the replica count for maximum availability; node groups, where they exist, will use a single large instance type for simplicity; and any operator a team finds useful may be installed by that team." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.

    ??? success "Check your answer"

        A good answer covers:

        - **All Fargate:** no DaemonSets, GPUs, EBS or Pod Identity, slower starts and payment for rounded-up requests; use Fargate selectively.
        - **Add-ons installed once from latest manifests:** unpinned, unmanaged, and incompatible after control plane upgrades; manage them as EKS add-ons with pinned versions in IaC and upgrade them every cycle.
        - **PDB `minAvailable` equal to replicas:** blocks every drain and node update; use `maxUnavailable: 1`.
        - **Single large instance type:** poor bin packing, no Spot diversification, one capacity pool and a larger blast radius per node; use several types or Karpenter.
        - **Any team may install any operator:** unowned CRDs and webhooks that block upgrades or cause cluster-wide outages; require an approved catalogue and owners.
        - **Further defects:** no IAM boundary for operators, no upgrade plan, logging and observability on Fargate not addressed.
        - **Legitimate intent:** less node management, stability, availability, simplicity and team autonomy; satisfy them with managed node groups or Auto Mode, managed add-ons, sensible PDBs, a small set of instance families and a self-service operator catalogue.

5. A cluster experiences a complete outage in which no workload can be deployed, although all existing Pods continue serving traffic. The trigger was a routine node scale-in during a quiet period. Reconstruct the most likely mechanism in full, identify every design defect that must have been present, and specify the changes  with configuration specifics  that would have reduced this from a cluster-wide outage to a non-event.

    ??? success "Check your answer"

        A good answer covers:

        - **Likely mechanism:** the scale-in removed the node hosting all replicas (or the only replica) of an operator's admission webhook; the webhook has `failurePolicy: Fail` and matches all namespaces, so every create or update times out.
        - **Why existing Pods continue:** admission only affects API writes; running Pods and Services keep working.
        - **Deadlock:** the webhook's own replacement Pod is also blocked because the webhook intercepts its own namespace.
        - **Design defects:** single replica or all replicas on one node, no PDB, no topology spread, `failurePolicy: Fail` with broad scope, no namespace exclusion, long timeout, and no alerting on webhook errors.
        - **Changes:** at least two replicas with `topologySpreadConstraints` across nodes and zones and a PDB with `maxUnavailable: 1`; `namespaceSelector` excluding `kube-system` and the webhook's namespace; `timeoutSeconds` of a few seconds; `failurePolicy: Ignore` unless the policy is security-critical; alert on API server webhook errors.

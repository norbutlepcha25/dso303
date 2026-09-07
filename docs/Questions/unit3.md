## 3.1

### Beginner Questions

1. Draw the EKS split architecture and label which components AWS operates and which you operate. State one consequence of that split for troubleshooting.
2. Calculate the maximum number of Pods on an `m5.xlarge` node (4 ENIs, 15 IPs per ENI) without prefix delegation, and explain each term in the formula.
3. Explain the difference between the `Unauthorized` and `Forbidden` errors when running `kubectl`, and state the fix for each.
4. Name the three cluster endpoint access modes and give one situation in which each is appropriate.
5. State three things that AWS Fargate on EKS cannot do, and explain why each limitation follows from Fargate's design.

### Intermediate Questions

1. A Pod is stuck in `ContainerCreating` with `failed to assign an IP address to container`, while node CPU is at 15 per cent. Explain the mechanism, name three remedies in increasing order of disruption, and state one drawback of each.
2. Explain how IRSA gives a Pod an IAM role, naming every component involved, and state two reasons EKS Pod Identity was introduced afterwards and one reason IRSA is still required.
3. A cluster's deployments all fail with `failed calling webhook ... context deadline exceeded` while `kubectl get pods` still works. Explain why the two behave differently, identify the likely cause, and give the fix.
4. Compare instance-mode and IP-mode target groups for the AWS Load Balancer Controller. Explain what makes IP mode possible on EKS and name two concrete benefits.
5. Explain what Kubernetes `requests` and `limits` each control, and describe a specific failure that results from setting requests too low and another from setting them too high.

### Advanced Questions

1. An organisation runs one EKS cluster per team — nineteen in total — and its control plane costs have become a line item in the annual budget. Analyse the trade-offs of consolidating to three clusters. Address blast radius, upgrade coordination, noisy neighbours, isolation mechanisms available within a cluster, cost attribution, and the specific circumstances that would justify keeping a cluster separate.
2. Design the complete network architecture for an EKS cluster that must support 4,000 Pods across three Availability Zones, connect to an on-premises network over AWS Direct Connect that has already allocated most of the RFC 1918 space, and enforce per-workload network boundaries visible to a non-Kubernetes security team. Specify the addressing scheme, CNI configuration, and segmentation mechanisms, justify each, and identify the requirement your design satisfies least well.
3. A Pod in a public-facing service was compromised through a server-side request forgery vulnerability, and the attacker exfiltrated data from three S3 buckets belonging to unrelated services. Reconstruct the most likely chain of events in detail, identify every design defect that must have been present, and specify the changes — with configuration specifics — that would have limited the incident to the compromised service's own data.
4. Critique this proposed platform standard: "All clusters will use public-only endpoints with `0.0.0.0/0` allow-listed for pipeline convenience, the `aws-auth` ConfigMap for access management because it is version-controlled in Git, `t3.medium` nodes for cost, the node instance role for all AWS access to avoid per-service IAM overhead, and Kubernetes version upgrades performed only when a CVE requires it." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.
5. An EKS cluster serving a payments platform must meet a 99.99 per cent availability target. Evaluate honestly what a single well-designed EKS cluster can and cannot deliver against that target. Identify every single point of failure that remains after multi-AZ node distribution, `topologySpreadConstraints`, and PodDisruptionBudgets are in place, and describe what a multi-cluster architecture would add, what it would cost, and how you would decide whether the addition is justified.

## 3.2

### Beginner Questions

1. Explain the difference between `kubectl create`, `kubectl apply`, and `kubectl replace`, and state which belongs in a declarative workflow and why.
2. Name the three probe types, state the question each answers and the action taken when each fails, and give one consequence of confusing liveness with readiness.
3. Explain what `requests` and `limits` control, and state why exceeding a memory limit and exceeding a CPU limit produce different outcomes.
4. State the correct order of an EKS cluster upgrade and explain why the control plane must be upgraded before the nodes.
5. Explain in one paragraph why `kubectl edit` should not be used to change production, and describe what should be done instead.

### Intermediate Questions

1. A Deployment's new Pods enter `ImagePullBackOff` and the rollout does not progress. Describe exactly what Kubernetes does over the following ten minutes, what it does **not** do, and what you would add to the pipeline so this recovers without human intervention.
2. Compare Helm and Kustomize across five dimensions of your choosing, and describe a concrete platform design that uses both. Justify which workloads go to which tool.
3. A node drain has been blocked for an hour. List four distinct causes, state how you would distinguish them, and give the remedy for each.
4. Explain the security argument for GitOps over a CI pipeline that runs `kubectl apply`. Then describe two failure modes that GitOps introduces and how you would mitigate each.
5. A service returns 5xx errors during every deployment despite all Pods reporting `Ready`. Explain the two most likely mechanisms, the single observation that distinguishes them, and the fix for each.

### Advanced Questions

1. Design the complete deployment architecture for a regulated financial platform where no human may deploy directly to production, every change must be attributable, secrets must never appear in version control, and a bad release must not reach more than five per cent of users before automated validation. Specify the provisioning, packaging, delivery, secret management, and progressive delivery mechanisms; justify each choice; and identify the requirement your design satisfies least completely and why.
2. An organisation with sixty microservices across four EKS clusters has no consistent deployment approach, no PodDisruptionBudgets, resource requests copied from an old example, and a shared CI role with cluster admin. Produce a prioritised remediation plan. Justify the ordering explicitly in terms of risk reduction per unit of effort, and identify which items you would deliberately defer and why.
3. Critique this proposed platform standard: "All applications will be packaged as Helm charts with values supplied by `--set` flags in the pipeline for flexibility; the pipeline will run `helm upgrade` and report success when the command returns; images will use branch-name tags so developers can see what is deployed; PodDisruptionBudgets will use `minAvailable` equal to the replica count for maximum availability; and cluster upgrades will be performed only when a security advisory requires them." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.
4. A cluster upgrade completed successfully. Three days later, an unrelated deployment fails with `no matches for kind "HorizontalPodAutoscaler" in version "autoscaling/v2beta2"`, and the team cannot understand why an upgrade three days ago broke something today. Explain the mechanism in full, explain why the failure was delayed, describe every check that would have caught it beforehand, and explain what makes this class of failure particularly serious on EKS specifically.
5. Argue both sides of the following claim, then give your own position with justification: "For an organisation running fewer than twenty services on AWS, adopting GitOps, Helm, Kustomize, a policy engine, a secrets operator, and a progressive delivery controller costs more in operational complexity than it returns in safety, and a well-written CI pipeline running `kubectl apply` is the correct engineering choice." Address the credential argument, the drift argument, the team-size argument, and what specific threshold would change your answer.

## 3.3

### Beginner Questions

1. List five things AWS Fargate on EKS cannot do, and for each explain which property of the Fargate model causes the limitation.
2. Explain what a Fargate profile selector consists of, state which part is mandatory, and explain what happens when two profiles match the same Pod.
3. Describe the steps a managed node group performs during a version update, in order, and state which step PodDisruptionBudgets affect.
4. Explain the three add-on conflict resolution modes and give one situation in which each is the correct choice.
5. Define a CustomResourceDefinition and a controller, and explain in one sentence what an operator is.

### Intermediate Questions

1. A Pod requests 3 vCPU and 5 GB of memory on Fargate. Explain what is allocated, what is billed, and why — then describe how you would adjust the request to reduce cost without harming the workload.
2. Compare managed node groups and Karpenter across provisioning model, scale-out latency, bin packing, consolidation, and operational burden. State which you would choose for a cluster with highly variable, heterogeneous workloads and justify it.
3. A Spot node group is causing workload instability. List four distinct causes, state how you would distinguish them from the available signals, and give the remedy for each.
4. Explain why an EKS add-on's version must be updated between the control plane upgrade and the node upgrade, and describe a specific failure that results from getting this order wrong.
5. Explain how an admission webhook registered by an operator can cause a cluster-wide outage. Describe the four configuration settings that prevent it and state which of them is not a default in most charts.

### Advanced Questions

1. Design the complete data plane for a multi-tenant SaaS platform running customer-supplied code, GPU inference, steady platform services, and nightly batch processing, with a requirement that no tenant workload shares a kernel with another. Specify the substrate for each workload class, justify each choice from the workload's properties, and identify the requirement your design satisfies least completely and why.
2. An organisation has accumulated eighteen operators across six clusters with no inventory, no version pinning, and no owners. The next Kubernetes upgrade is blocked. Produce a prioritised plan to unblock the upgrade and to prevent recurrence. Justify the ordering in terms of risk reduction per unit of effort, and state which operators you would expect to remove entirely rather than upgrade.
3. Argue both sides of the following claim, then give your own position: "AWS Controllers for Kubernetes should be the default way developers provision AWS resources, because a single declarative workflow for an application and its dependencies is worth more than the lifecycle independence that Terraform provides." Address garbage collection, blast radius, the controller's permissions, coverage maturity, and what specific class of resource would change your answer.
4. Critique this proposed platform standard: "All workloads will run on AWS Fargate to eliminate node management; add-ons will be installed once from the latest available manifests and left alone since they rarely change; PodDisruptionBudgets will use `minAvailable` equal to the replica count for maximum availability; node groups, where they exist, will use a single large instance type for simplicity; and any operator a team finds useful may be installed by that team." Identify at least seven specific defects, propose a corrected standard, and state which parts of the original intent are legitimate and how you would satisfy them.
5. A cluster experiences a complete outage in which no workload can be deployed, although all existing Pods continue serving traffic. The trigger was a routine node scale-in during a quiet period. Reconstruct the most likely mechanism in full, identify every design defect that must have been present, and specify the changes — with configuration specifics — that would have reduced this from a cluster-wide outage to a non-event.
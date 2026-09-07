# Amazon EKS Advanced Concepts

!!! info "Where this topic sits in DSO303"

    Chapter 3.1 established what an EKS cluster is; Chapter 3.2 established how applications reach it. This chapter is about the three decisions that determine how much of the cluster you actually operate.

    **3.3.1** treats **Fargate profiles**: what it means to run a Pod with no node at all, what that removes as well as what it removes *from you*, and how the selector-based scheduling model differs from everything else in Kubernetes. **3.3.2** treats **managed node groups**: the AMI and launch template model, the cordon-and-drain upgrade, Spot handling, and where the abstraction stops. **3.3.3** treats **add-ons and operators**: the components AWS packages for you, and the operator pattern by which Kubernetes is extended — the mechanism that makes a cluster a platform rather than a container runner.

    The unifying question is **where the line between your responsibility and AWS's should fall for each workload**, and the honest answer is that it falls in a different place for different workloads in the same cluster. A student who leaves this chapter believing there is one correct data plane has learned the wrong lesson.

---

## Learning Objectives

After studying this chapter you should be able to:

- Explain the **AWS Fargate model on EKS** — one Pod per micro-VM, no shared node, no node object you control — and derive its limitations from that model rather than memorising them.
- Configure **Fargate profiles** with namespace and label **selectors**, explain the matching and precedence rules, and explain why profiles are immutable.
- Explain the **Fargate pod execution role**, how it differs from a node instance role, and why **EKS Pod Identity does not work on Fargate** while IRSA does.
- Quantify Fargate's **resource model**: the valid CPU and memory combinations, the reservation AWS adds for Kubernetes components, ephemeral storage limits, and how requests are rounded up to a billable configuration.
- Decide correctly **when Fargate is the right substrate** and when it is not, using workload characteristics rather than preference.
- Describe **managed node groups**: the launch template, the EKS-optimized AMI, the Auto Scaling group, the automatic access entry, and the node lifecycle AWS manages.
- Compare **AMI families** — Amazon Linux 2023, Bottlerocket, Windows, GPU variants — on attack surface, customisability, and update model.
- Perform a **managed node group version update**, explain what `updateConfig` and the force flag do, and predict how PodDisruptionBudgets affect it.
- Configure **Spot capacity** in managed node groups, explain the interruption and rebalance handling AWS provides, and design a workload that tolerates it.
- Compare **managed node groups, self-managed nodes, Karpenter, and EKS Auto Mode** and choose between them for a given requirement.
- Explain the **EKS add-on** model: versioning, `configurationValues`, conflict resolution (`NONE`, `OVERWRITE`, `PRESERVE`), add-on IAM roles, and the three add-on tiers.
- Explain the **operator pattern** — a CustomResourceDefinition plus a controller running a reconciliation loop — and why it is the mechanism by which Kubernetes is extended.
- Describe how **AWS Controllers for Kubernetes (ACK)** let Kubernetes manifests provision AWS resources, and state the trade-offs against Terraform or CloudFormation.
- Design an **add-on and operator baseline** for a production cluster, and explain the upgrade obligation each component adds.

---

## Definition

This chapter covers three mechanisms by which an EKS cluster's operational surface is reduced or extended.

**AWS Fargate on EKS** is a serverless compute engine in which each Pod runs in its own dedicated micro-VM with no shared node, no node you can log into, and no node you can schedule anything else onto. You declare *which* Pods should run this way with a **Fargate profile**; AWS provisions capacity per Pod on demand.

**Managed node groups** are EKS-operated Auto Scaling groups of EC2 instances running AWS-published, EKS-optimized AMIs, where AWS handles the launch template, the bootstrap, the cluster registration, health-based replacement, and the cordon-and-drain node replacement during version updates — while leaving you the instance types, sizes, scaling bounds, labels, and taints.

**EKS add-ons** are AWS-packaged, versioned, validated deployments of cluster components (the VPC CNI, CoreDNS, `kube-proxy`, CSI drivers, the Pod Identity Agent, observability agents and more), installed and upgraded through the EKS API rather than as loose manifests. **Operators** are the general pattern add-ons are a managed instance of: a CustomResourceDefinition that extends the Kubernetes API with a new object type, plus a controller that watches those objects and reconciles the world toward them.

| Mechanism | What it removes from you | What it costs |
|---|---|---|
| **Fargate profile** | The node entirely: no AMI, no patching, no capacity planning, no bin packing | Anything that needs a node — DaemonSets, EBS, GPUs, privileged containers — plus per-Pod pricing and slower start |
| **Managed node group** | AMI publication, bootstrap, registration, drain-and-replace upgrades | You still choose instances, still schedule the upgrade, still own capacity strategy |
| **EKS add-on** | Building, patching, and version-matching cluster components | A version to track and an upgrade to perform with every cluster upgrade |
| **Operator** | The imperative runbook for operating a complex system | A controller to run, secure, and upgrade — and a new API surface to understand |

Within an AWS architecture these sit in the data plane and its supporting components — below the applications of Chapter 3.2 and above the cluster of Chapter 3.1.

!!! note "These are not alternatives; they compose"

    A single production cluster commonly runs managed node groups for general workloads, a tainted Spot node group for batch, Fargate profiles for a couple of isolation-sensitive namespaces, the four core add-ons managed by EKS, and half a dozen operators. The exam question "should I use Fargate or node groups" almost always has the answer "both, for different workloads" — and being able to say *which* workloads is the actual skill.

---

## Why This Service or Concept Exists

### Why Fargate exists: the node is an operational liability

A node is an EC2 instance you must patch, size, monitor, secure, replace, and pay for whether or not it is full. For a large fleet of steady workloads that overhead is amortised well. For several categories of workload it is not:

| Workload | Why a node is a poor fit |
|---|---|
| A small service needing 0.25 vCPU | The smallest sensible node is many times larger and mostly idle |
| A CI runner that exists for four minutes | A node's launch, join, and drain cost exceeds the job |
| An untrusted or multi-tenant workload | Container isolation on a shared kernel is weaker than a per-Pod VM boundary |
| A workload with a bursty, unpredictable shape | Capacity must be pre-provisioned or scaled reactively, and both are wrong some of the time |
| A cluster's first workload | You should not have to run infrastructure to run one Pod |

Fargate's answer is to make the Pod the unit of compute. AWS provisions a dedicated micro-VM sized to the Pod's requests, runs it, and bills per second. Every limitation follows from that single decision rather than being an arbitrary restriction — which is why the limitations are worth deriving rather than memorising:

| Limitation | Because |
|---|---|
| No DaemonSets | A DaemonSet runs one Pod per node; there is no node to be one-per |
| No `hostNetwork` or `hostPort` | The host is a micro-VM shared with nothing; there is no host network to join |
| No privileged containers | A privileged container escapes into the host, which AWS owns |
| No GPU or specialised hardware | Capacity is standard AWS-managed compute, not your instance selection |
| No EBS volumes | EBS attaches to an instance; there is no persistent instance (EFS works, being network-attached) |
| Slower Pod start | The micro-VM must be provisioned and the image pulled fresh with no node-level cache |
| No EKS Pod Identity | Its agent is a DaemonSet (see the first row); IRSA works because it needs no agent |
| Fixed CPU and memory combinations | Capacity is allocated in defined shapes, and your requests are rounded up to one |
| Node-based scheduling features do not apply | `topologySpreadConstraints` and node affinity assume nodes to spread across |

### Why managed node groups exist: nodes without the plumbing

Self-managing nodes means building or selecting an AMI, writing bootstrap user data that fetches the cluster endpoint and CA and configures the `kubelet`, creating and sizing an Auto Scaling group, mapping the node role so the node may join, replacing unhealthy instances, and — hardest of all — upgrading: launching new-version nodes, cordoning old ones, draining them while respecting PodDisruptionBudgets, and terminating them in a bounded, resumable way.

Every one of those is undifferentiated work, and the drain logic in particular is easy to get subtly wrong. Managed node groups do all of it behind one API, while leaving you every decision that is actually about your workload.

| Self-managed burden | What managed node groups provide |
|---|---|
| Build or select and track an AMI | AWS publishes and versions EKS-optimized AMIs per Kubernetes version |
| Write and maintain bootstrap user data | Handled; a launch template lets you extend it when you must |
| Map the node role so nodes may join | An `EC2_LINUX` access entry is created automatically |
| Replace unhealthy nodes | Health monitoring with automatic replacement |
| Orchestrate version upgrades | Launch, cordon, drain respecting PDBs, terminate, bounded by `updateConfig` |
| Handle Spot interruption and rebalance | Rebalance recommendations and interruption notices trigger a drain |
| Tag and label consistently | Labels and taints declared on the group and applied to nodes |

### Why add-ons exist: the components everyone needs, versioned

Every cluster needs a CNI, a DNS server, a Service proxy, and usually a CSI driver. These are open-source components with their own release cadence, their own compatibility matrix against Kubernetes versions, and their own CVEs. Installed as loose `kubectl apply -f https://...` manifests they become invisible: nobody knows what version is running, nobody updates them, and a cluster upgrade breaks in a way that appears to be the upgrade's fault.

EKS add-ons make them first-class API objects with a version, a configuration, an IAM role, and an update operation — visible in CloudTrail, expressible in infrastructure as code, and updatable as an explicit step in the upgrade procedure of Chapter 3.2.

### Why operators exist: Kubernetes as a platform, not a container runner

The single most consequential idea in Kubernetes is that **the API is extensible and every controller is equal**. You define a CustomResourceDefinition — say, `kind: Database` — and write a controller that watches `Database` objects and makes reality match. From the API server's point of view your controller is indistinguishable from the built-in Deployment controller.

This is what turns Kubernetes from a scheduler into a platform. Instead of a runbook that says "to create a database, do these fourteen things", a developer writes eight lines of YAML and an operator that encodes the expertise does the fourteen things — continuously, including after a failure, and including the parts a human would forget at 3 a.m.

```mermaid
flowchart TD
    A["A human runbook: 14 steps, executed by whoever is on call, sometimes"] --> B["An operator: the same 14 steps, encoded, executed continuously by a controller"]
    B --> C["Developer writes: kind: Database, size: 100Gi, version: 15"]
    C --> D["Controller reconciles: provision, configure, back up, fail over, upgrade"]
    D --> E["Reality matches the declaration, and keeps matching it"]
```

!!! tip "The one sentence that explains half of Kubernetes"

    **A controller watches objects of a kind and makes the world match them.** The Deployment controller does it for Deployments. Karpenter does it for NodePools. ACK does it for AWS resources. The AWS Load Balancer Controller does it for Ingresses. Once a student sees that these are the same mechanism with different object types, the ecosystem stops being a list of tools to memorise and becomes one pattern applied repeatedly — and writing your own controller stops being exotic.

---

## Real-World Motivation

**A university's Fargate-only experiment.** A department decided every Pod would run on Fargate to eliminate node management. Their Prometheus node exporter DaemonSet would not schedule; their PostgreSQL Pod could not attach an EBS volume; their machine learning workloads could not get a GPU; and their build agents took noticeably longer to start because every Pod pulled its image onto fresh infrastructure with no node cache. *The architectural lesson is that Fargate does not remove the node's overhead — it removes the node, and everything that depends on one goes with it.*

**A retailer's Spot fleet that behaved.** A team moved batch processing to a managed node group with Spot capacity across six instance types. Interruptions happened weekly, and nothing broke: EKS received the two-minute notice, cordoned the node, drained it respecting PodDisruptionBudgets, and the workloads rescheduled. *The architectural lesson is that Spot's risk is manageable when the platform handles the notice and the workload tolerates rescheduling — and unmanageable when either is missing.*

**A media company's forgotten CNI.** A cluster ran for two years and was upgraded four times. Nobody updated the VPC CNI, which had been applied from a URL during the original build. Pods began failing to get IP addresses in ways that matched no documented behaviour, because the plugin predated three Kubernetes versions. *The architectural lesson is that a cluster component installed as a loose manifest is a component nobody owns, and the EKS add-on API exists precisely so that its version is a visible, managed field.*

**A bank's operator that saved the weekend.** A team ran PostgreSQL on Kubernetes with a mature operator. A node failed at 2 a.m.; the operator promoted a replica, provisioned a new one, and re-established replication before anyone was paged. The equivalent runbook existed but had never been executed by the two engineers on call. *The architectural lesson is that an operator is an expert's knowledge encoded and executed continuously, which is strictly better than the same knowledge written down and executed occasionally.*

**A start-up's operator that ruined one.** A different team installed four operators from GitHub without reading what they created. One installed a ClusterRoleBinding granting itself cluster admin, another registered a validating webhook with `failurePolicy: Fail` and one replica, and when that replica was evicted during a node scale-in, every write to the cluster failed. *The architectural lesson is that an operator is privileged, executable configuration; installing one without reading its manifests is running someone else's code with cluster-wide permissions.*

**A logistics team's node group that would not update.** A managed node group update ran for four hours and timed out. A PodDisruptionBudget on a three-replica Deployment specified `minAvailable: 3`, so no Pod could ever be evicted. The team used the force flag to finish the update, which ignored the budget and briefly took the service to zero. *The architectural lesson is that the force flag exists for exactly this situation and does exactly what it says — it is a way to finish an upgrade, not a way to make the configuration correct.*

**A SaaS platform's Fargate isolation win.** A company ran customer-supplied plugins in a shared cluster. Moving that namespace to a Fargate profile gave every plugin Pod its own micro-VM, so a container escape reached an AWS-managed kernel with nothing else on it rather than a node shared with other tenants' workloads. *The architectural lesson is that Fargate's strongest argument is often isolation rather than convenience, and that argument applies to a specific namespace rather than to a whole cluster.*

---

## Core Concepts: EKS Fargate Profiles

### The model

```mermaid
flowchart TD
    POD["Pod created in namespace 'ci', labelled runner=true"] --> SCHED{"Does it match a Fargate profile selector?"}
    SCHED -->|"no"| NODE["Scheduled onto an EC2 node as normal"]
    SCHED -->|"yes"| FSCHED["Fargate scheduler takes it"]
    FSCHED --> MUT["Mutating webhook sets the scheduler and adds the eks.amazonaws.com/fargate-profile label"]
    MUT --> PROV["AWS provisions a dedicated micro-VM sized to the Pod's requests, rounded up"]
    PROV --> ENI["An ENI is attached in one of the profile's private subnets; the Pod gets a VPC IP"]
    ENI --> PULL["Image pulled using the POD EXECUTION ROLE (not a node role)"]
    PULL --> RUN["Containers start; the Pod appears as its own Node object in the API"]
    RUN --> BILL["Billed per second on vCPU and memory, one-minute minimum"]
    RUN --> DONE["Pod terminates; the micro-VM is destroyed; nothing is reused"]
```

Two consequences deserve emphasis. **Each Fargate Pod appears as its own Node object** in `kubectl get nodes`, with a name beginning `fargate-`. That node is not yours: you cannot schedule onto it, log into it, or run anything alongside the Pod. And **nothing is reused between Pods** — no image cache, no warm capacity — which is the source of Fargate's slower start.

### Fargate profiles and selectors

A profile has a name, a **pod execution role**, a list of **private subnets**, and up to **five selectors**. Each selector has a **required namespace** and **optional labels**:

```yaml
fargateProfiles:
  - name: ci-runners
    podExecutionRoleARN: arn:aws:iam::111122223333:role/EksFargatePodExecutionRole
    subnets: [subnet-0a1, subnet-0b1, subnet-0c1]     # private subnets only
    selectors:
      - namespace: ci
        labels:
          runner: "true"          # BOTH namespace and label must match
      - namespace: preview-*      # wildcards are supported
```

| Rule | Detail |
|---|---|
| **Namespace is required** | A selector always names a namespace; labels alone are not enough |
| **All labels must match** | Within one selector, every label is required (an AND) |
| **Any selector may match** | Across selectors in a profile, one match is enough (an OR) |
| **Wildcards are supported** | `*` matches zero or more characters, `?` exactly one, in namespaces and label values |
| **Multiple matching profiles** | The profile whose name sorts first alphanumerically wins; a Pod can override with the `eks.amazonaws.com/fargate-profile` label |
| **Profiles are immutable** | To change selectors you create a new profile and delete the old one |
| **Deleting a profile** | Its Pods are stopped and become `Pending` |
| **Only private subnets** | Fargate Pods get no public IP; egress needs NAT or VPC endpoints |

!!! warning "Immutability means selectors are a design decision, not a setting"

    A Fargate profile cannot be edited. Changing which Pods run on Fargate means creating a new profile and deleting the old one, and deleting a profile stops its Pods. Design selectors around **stable namespace boundaries** — a `ci` namespace, a `tenant-plugins` namespace — rather than around labels that application teams control, or you will be recreating profiles as a routine operation.

### The resource model, and what you are actually billed for

Fargate allocates capacity in defined CPU and memory combinations, and **your Pod's total requests are rounded up to the nearest valid combination**. AWS additionally reserves approximately **256 MB** per Pod for Kubernetes components, which comes out of the allocation.

| Requested (all containers) | Allocated | What you pay for |
|---|---|---|
| 0.2 vCPU, 300 MB | 0.25 vCPU, 1 GB (0.5 GB + reservation rounds up) | The allocation, not the request |
| 0.4 vCPU, 1.5 GB | 0.5 vCPU, 2 GB | The allocation |
| 1 vCPU, 7.5 GB | 1 vCPU, 8 GB | The allocation |
| 3 vCPU, 5 GB | 4 vCPU, 8 GB (CPU forces the shape) | Considerably more than requested |

Ephemeral storage is **20 GiB by default**, expandable by requesting `ephemeral-storage` up to 175 GiB. Supported sizes range from 0.25 vCPU with 0.5 GB of memory up to 16 vCPU with 120 GB, and only defined combinations exist between them.

!!! danger "Under-requesting memory on Fargate costs money and over-requesting costs more"

    Because you pay for the allocated shape rather than the requested one, a Pod requesting 3 vCPU and 5 GB is billed for 4 vCPU and 8 GB — a third more CPU and 60 per cent more memory than asked for. And because AWS reserves 256 MB, a Pod requesting exactly 1 GB is allocated 2 GB. Right-sizing requests to land **just below** a combination boundary is a real and easily overlooked optimisation, and it is the opposite of the EC2 intuition where slack is free until the node fills.

### Identity, storage, and networking on Fargate

**Identity** works through a **pod execution role** — trusted by `eks-fargate-pods.amazonaws.com`, used by the AWS-managed `kubelet` to register the Pod and pull images from ECR. It is *not* available to your containers, which is a security improvement over the node instance role problem of Chapter 3.1: a Fargate Pod has no node role to steal. For AWS access from inside the container you use **IRSA**; **EKS Pod Identity does not work**, because its agent is a DaemonSet.

**Storage** is ephemeral by default and destroyed with the Pod. **Amazon EFS** works through the EFS CSI driver because it is network-attached; **Amazon EBS does not**, because it attaches to an instance.

**Networking** is standard VPC networking — the Pod gets a real VPC IP from one of the profile's subnets — with two consequences. Load balancer target groups must use **IP mode**, since there is no instance to register. And because the subnets are private, egress to the internet requires NAT or VPC endpoints.

**Logging** uses a built-in Fluent Bit log router configured by a ConfigMap in the `aws-observability` namespace, which is how you get logs off a Pod that has no node to run a log agent DaemonSet on.

### When Fargate is right

```mermaid
flowchart TD
    A["Consider this workload"] --> B{"Does it need a DaemonSet, GPU, EBS, privileged mode, or host networking?"}
    B -->|"yes"| C["Not Fargate — it needs a node"]
    B -->|"no"| D{"Is per-Pod VM isolation valuable here?"}
    D -->|"yes: untrusted code, multi-tenant, regulated"| E["Strong Fargate case"]
    D -->|"no"| F{"What is the utilisation shape?"}
    F -->|"bursty, short-lived, or very small"| G["Good Fargate case: no idle node to pay for"]
    F -->|"steady and dense"| H["Nodes are cheaper: Fargate's per-Pod premium compounds"]
    E --> I{"Is a slower Pod start acceptable?"}
    G --> I
    I -->|"yes"| J["Use a Fargate profile for this namespace"]
    I -->|"no, latency-critical scale-out"| K["Nodes with warm capacity, or Karpenter"]
```

| Good fit | Poor fit |
|---|---|
| CI/CD runners and short-lived jobs | Steady, dense, always-on services |
| Untrusted or customer-supplied code | Anything needing a DaemonSet agent |
| Small services in a mostly empty cluster | Stateful workloads needing EBS |
| Bursty, unpredictable workloads | GPU or specialised hardware workloads |
| A cluster's first few workloads | Latency-critical scale-out |
| Namespaces needing hard isolation | Workloads relying on node affinity or topology spread |

---

## Core Concepts: EKS Managed Node Groups

### What a managed node group is

A managed node group is an EC2 Auto Scaling group that EKS creates and operates on your behalf, plus a launch template, plus the lifecycle logic that makes the nodes join and leave the cluster cleanly.

```mermaid
flowchart TD
    NG["Managed node group definition: instance types, sizes, AMI type, labels, taints, updateConfig"] --> LT["EKS creates a launch template with the EKS-optimized AMI and bootstrap"]
    LT --> ASG["EKS creates and owns an EC2 Auto Scaling group"]
    ASG --> INST["Instances launch and run the bootstrap"]
    INST --> JOIN["kubelet registers using the node instance role"]
    AE["EKS automatically creates an EC2_LINUX access entry for the node role"] --> JOIN
    JOIN --> READY["Node Ready once the CNI is functional"]
    READY --> SCHED["Scheduler places Pods"]
    HEALTH["EKS node health monitoring"] --> REPL["Unhealthy nodes replaced automatically"]
    UPD["UpdateNodegroupVersion"] --> DRAIN["Launch new, cordon old, drain respecting PDBs, terminate — bounded by updateConfig"]
```

The **automatic access entry** is worth naming, because it is the difference between a managed and a self-managed node group that most often bites: with self-managed nodes you must create the `EC2_LINUX` access entry yourself, and a node whose role is unmapped authenticates and is then refused, appearing simply never to join.

### AMI families

| AMI type | Characteristics | Choose when |
|---|---|---|
| **Amazon Linux 2023** | General-purpose, `dnf`, SSM agent, `nodeadm`/`NodeConfig` bootstrap | The default for most clusters |
| **Bottlerocket** | Minimal, container-optimised, immutable root filesystem, API-driven configuration, no shell or package manager, separate control and admin containers | Security-conscious fleets; smaller attack surface and faster boot |
| **AL2023 GPU / NVIDIA** | Bundled GPU drivers and container toolkit | Machine learning and rendering workloads |
| **Windows** | Windows Server core images | .NET Framework workloads that cannot be containerised on Linux |

!!! tip "Bottlerocket is the better default than most teams assume"

    Its root filesystem is read-only and integrity-checked, there is no shell or package manager to exploit, updates are atomic image swaps with rollback rather than in-place package upgrades, and it boots faster because it contains almost nothing. The cost is that anything requiring host-level customisation — an agent installed into the host OS, a kernel module, a custom `systemd` unit — must be reworked as a privileged container or is simply not possible. For a fleet running only containers, that cost is usually zero and the security gain is real.

### Launch templates: the escape hatch

A managed node group can use a **custom launch template**, which is how you extend the abstraction without abandoning it: custom user data appended to the bootstrap, a specific AMI, additional security groups, instance metadata options (the `httpPutResponseHopLimit: 1` from Chapter 3.1), larger or additional EBS volumes, placement groups, and detailed monitoring.

The important constraint: **when you supply a custom AMI ID, you take over AMI lifecycle**. EKS no longer updates the node group to new AMI versions automatically, because it does not know how to build yours. Most teams should use a launch template for metadata options, volumes, and security groups while leaving the AMI to AWS.

### Updating a node group

Two kinds of update exist and they are frequently conflated:

| Update | Trigger | Effect |
|---|---|---|
| **Version update** | New Kubernetes version, or a new AMI release for the current version | Nodes replaced with the new AMI |
| **Configuration update** | Changing scaling bounds, labels, taints, or the launch template version | Scaling bounds apply immediately; most other changes require node replacement |

The version update sequence is the cordon-and-drain described in Chapter 3.2, bounded by `updateConfig`:

| Setting | Meaning | Guidance |
|---|---|---|
| `maxUnavailable` | Nodes replaced concurrently, as a count | 1 for small groups where every node matters |
| `maxUnavailablePercentage` | The same, as a percentage of the group | 25 per cent for large groups; the same speed-versus-capacity trade as an ECS deployment |
| `updateStrategy` | `DEFAULT` launches replacement capacity before draining; `MINIMAL` drains without adding capacity first | `DEFAULT` in production; `MINIMAL` only where extra capacity is unavailable and reduced capacity is acceptable |
| **Force flag** | Ignores PodDisruptionBudgets and evicts regardless | The escape from a deadlocked drain, not a default |

!!! danger "The force flag finishes an upgrade; it does not fix a configuration"

    An update blocked by a PodDisruptionBudget with no slack will time out. The force flag will complete it by ignoring the budget entirely — which may briefly take a service to zero replicas. Use it to escape a stuck upgrade if you must, then fix the PodDisruptionBudget (`maxUnavailable: 1`, or `minAvailable` strictly less than replicas), because otherwise you will be forcing every future upgrade and the budget is providing no protection at all.

### Spot capacity in managed node groups

Setting `capacityType: SPOT` gives you EC2 Spot capacity with AWS handling the awkward parts:

- **Capacity-optimized allocation**, launching from the pools least likely to be interrupted.
- **Rebalance recommendations**, an early warning before the interruption notice, used to start draining proactively.
- **Interruption notices** (two minutes), which trigger a cordon and drain.

Your side of the bargain is **instance type diversity** — several compatible types, so one pool's reclamation does not remove the whole group — and **workloads that tolerate rescheduling**: correct PodDisruptionBudgets, `terminationGracePeriodSeconds` well under two minutes, checkpointing for long jobs, and no assumption of node stability.

| Capacity type | Use |
|---|---|
| **On-Demand** | The base that must carry floor traffic alone; anything user-facing and latency-critical |
| **Spot** | Batch, CI, stateless workers, and anything that reschedules cheaply |
| **Capacity Blocks** | Reserved GPU capacity for a defined future window; machine learning training |

The standard production shape is an **On-Demand node group sized to carry floor traffic** plus a **tainted Spot node group** that only tolerating workloads land on — the same base-plus-Spot pattern Chapter 2.3 established for ECS capacity providers.

### Managed node groups versus Karpenter versus Auto Mode

| | Managed node group | Karpenter | EKS Auto Mode |
|---|---|---|---|
| **Provisioning model** | Pre-defined ASGs with fixed instance types | Just-in-time instances chosen from Pod requirements | AWS-managed, Karpenter-based |
| **Scale-out latency** | ASG adjustment, then launch | Direct EC2 launch; typically faster | Managed |
| **Bin packing** | Whatever the ASG's types allow | Chooses instance shapes that fit the pending Pods | Managed |
| **Consolidation** | None | Replaces under-utilised nodes with cheaper ones automatically | Managed |
| **Spot handling** | Built in | Built in, with broader pool diversity | Managed |
| **You operate** | Nothing beyond the group | The Karpenter controller and its NodePools | Nothing |
| **Node lifetime** | Until you replace it | Bounded by expiry and drift settings | Bounded (nodes replaced regularly) |
| **Cost** | EC2 only | EC2 only | EC2 plus a management fee |
| **Control** | High | High | Reduced: limited node customisation |

The honest guidance: **managed node groups for a baseline and for anything needing specific instance configuration; Karpenter for workloads whose scaling is spiky or heterogeneous; Auto Mode when the team's binding constraint is people rather than control.** They coexist — Karpenter itself needs somewhere to run, and that somewhere is usually a small managed node group.

---

## Core Concepts: Add-ons and Operators

### The EKS add-on model

An add-on is an EKS API object with a name, a version, optional `configurationValues`, an optional IAM role, and a conflict resolution mode.

| Add-on tier | Built and supported by | Scanned by AWS | Examples |
|---|---|---|---|
| **AWS add-ons** | AWS | Yes | VPC CNI, `kube-proxy`, CoreDNS, EBS/EFS/S3 CSI drivers, snapshot controller, Pod Identity Agent, CloudWatch Observability, GuardDuty agent, node monitoring agent |
| **AWS Marketplace add-ons** | Partners | Yes | Commercial observability, security, and cost tooling |
| **Community add-ons** | Open source community | Yes (compatibility only) | Metrics Server, cert-manager, ExternalDNS, kube-state-metrics |

**Conflict resolution** decides what happens when the add-on's desired configuration differs from what is live in the cluster:

| Mode | Behaviour | Use when |
|---|---|---|
| `NONE` | Fail the update if there is a conflict | You want to be told rather than surprised |
| `OVERWRITE` | AWS's configuration wins | The AWS defaults are authoritative; the usual choice |
| `PRESERVE` | Your in-cluster changes are kept | You have deliberately customised fields and intend to keep them. `PRESERVE` is valid on an add-on **update** only; creation accepts `NONE` or `OVERWRITE` |

**`configurationValues`** supplies add-on settings as JSON or YAML through the API — the VPC CNI's `ENABLE_PREFIX_DELEGATION`, CoreDNS's replica count and resources, the EBS CSI driver's tolerations — so that configuration lives in your infrastructure as code rather than in a `kubectl set env` command somebody ran once.

**Add-on IAM roles** are supplied through IRSA or a Pod Identity association, so the EBS CSI driver holds permission to create volumes, and the CNI holds permission to manage ENIs, without either relying on the node role.

!!! warning "An add-on's version is part of your upgrade, not an afterthought"

    Add-ons run in the data plane and must be compatible with the control plane version. The order from Chapter 3.2 — control plane, then add-ons, then nodes — exists because a node launched with an old CNI against a new API server can fail in ways that look like networking faults. Pin add-on versions in infrastructure as code, and update them as an explicit, reviewed step of every cluster upgrade.

### The core add-ons, and what breaks without each

| Add-on | Role | Symptom if broken or stale |
|---|---|---|
| **Amazon VPC CNI** | Pod IP allocation | Nodes never become `Ready`; Pods stuck in `ContainerCreating` |
| **CoreDNS** | Cluster DNS | Intermittent, confusing failures everywhere; the most misdiagnosed outage in Kubernetes |
| **`kube-proxy`** | Service virtual IP rules | ClusterIP Services unreachable from the affected node only |
| **EBS CSI driver** | PersistentVolumeClaims to EBS volumes | PVCs stay `Pending`; StatefulSets never start |
| **EFS CSI driver** | Shared, multi-attach, and Fargate-compatible storage | No shared volumes; no persistent storage on Fargate |
| **Pod Identity Agent** | Per-Pod IAM credentials | Pods fall back to the node role — a security failure, not a functional one |
| **Snapshot controller** | Volume snapshots | Backups of persistent volumes do not work |
| **CloudWatch Observability** | Container Insights metrics and logs | No cluster observability |
| **Node monitoring agent** | Node-level health detection and auto-repair | Unhealthy nodes are not detected or replaced |

!!! danger "CoreDNS is the component whose failure looks like everything else failing"

    DNS resolution failures present as intermittent connection errors, timeouts, and retries scattered across unrelated services — never as "DNS is down". CoreDNS should run at least two replicas, be spread across zones and nodes with anti-affinity, have a PodDisruptionBudget, be scaled with cluster size, and have its request rate, error rate, and latency on a dashboard. A cluster whose CoreDNS runs two Pods on the same node is one node event away from a cluster-wide mystery.

### The operator pattern

```mermaid
flowchart TD
    CRD["CustomResourceDefinition: teaches the API server a new kind, e.g. Database"] --> API["kube-apiserver now serves /apis/example.com/v1/databases"]
    USER["Developer: kubectl apply -f my-database.yaml"] --> API
    API --> ETCD["Object persisted in etcd like any other"]
    API -->|"watch event"| CTRL["Operator controller"]
    CTRL --> LOOP["Reconciliation loop: compare desired spec with observed reality"]
    LOOP --> ACT["Act: create a StatefulSet, a Service, a Secret; call an AWS API; configure replication"]
    ACT --> STATUS["Write status back onto the object"]
    STATUS --> LOOP
    LOOP --> DRIFT["Something changes or fails: reconcile again, forever"]
```

The mechanics worth knowing because they explain real behaviour:

| Mechanism | What it does | Why it matters |
|---|---|---|
| **CustomResourceDefinition** | Registers a new kind with a schema | Your object gets validation, RBAC, and `kubectl` support for free |
| **Reconciliation loop** | Level-triggered: compares desired to actual, repeatedly | Idempotent and self-healing; missing an event is survivable |
| **Owner references** | Marks children as owned by a parent | Deleting the parent garbage-collects the children |
| **Finalizers** | Blocks deletion until cleanup completes | Why a namespace sometimes hangs in `Terminating` forever |
| **Status subresource** | Separates reported state from desired state | You write `spec`; the controller writes `status` |
| **Admission webhooks** | Validate or mutate objects at write time | Where an operator enforces its own rules — and where it can break the cluster |
| **Leader election** | One active replica among several | High availability without duplicate reconciliation |

**A namespace stuck in `Terminating`** is almost always a finalizer whose controller is gone: the object cannot be deleted until the finalizer is removed, and the controller that would remove it no longer exists. This is worth knowing because it is common, alarming, and simple once understood.

### Operators worth knowing in a DSO303 context

| Operator | What it manages | Why it is representative |
|---|---|---|
| **AWS Load Balancer Controller** | Ingress and Service objects into ALBs and NLBs | The integration point of Chapter 3.1's networking |
| **Karpenter** | NodePools into EC2 instances | Node provisioning expressed as reconciliation |
| **Cluster Autoscaler** | Auto Scaling group sizes | The older approach, still widely deployed |
| **cert-manager** | Certificate objects into issued TLS certificates | The canonical "operator does a tedious thing correctly" example |
| **ExternalDNS** | Ingress hostnames into Route 53 records | Kubernetes objects driving AWS resources |
| **External Secrets Operator** | ExternalSecret objects into Kubernetes Secrets from Secrets Manager | Chapter 3.2's secrets pattern, implemented |
| **Prometheus Operator** | ServiceMonitor objects into scrape configuration | Observability as declarative configuration |
| **Argo CD** | Application objects into deployed workloads | GitOps itself is an operator |
| **AWS Controllers for Kubernetes (ACK)** | S3 buckets, RDS instances, SQS queues, DynamoDB tables | AWS resources as Kubernetes objects |
| **Database operators** (CloudNativePG, Strimzi) | Stateful systems with failover and backup | Where operators deliver the most and risk the most |

### AWS Controllers for Kubernetes, and its trade-off

ACK lets a manifest create AWS resources:

```yaml
apiVersion: s3.services.k8s.aws/v1alpha1
kind: Bucket
metadata:
  name: orders-uploads
spec:
  name: dso303-orders-uploads
```

The appeal is a single workflow: an application's manifests declare both its Pods and the S3 bucket they need, delivered by the same GitOps controller. The trade-off is real and should be argued rather than assumed.

| For ACK | Against ACK |
|---|---|
| One declarative workflow for application and its dependencies | Resource lifecycle is now tied to a Kubernetes cluster's lifecycle |
| Developers self-serve AWS resources without a separate pipeline | Deleting a namespace can delete a production database |
| Continuous reconciliation corrects drift in AWS resources | Terraform and CloudFormation have far broader coverage and maturity |
| Kubernetes RBAC governs who may create what | The controller holds broad AWS permissions inside the cluster |

The defensible middle position: **ACK for resources whose lifetime genuinely matches the application** — a queue, a bucket, a DynamoDB table owned by one service — and **Terraform or CloudFormation for shared, long-lived infrastructure** such as VPCs, databases with independent retention requirements, and anything whose deletion would be catastrophic. And in either case, deletion policies and `deletionPolicy: retain` annotations deserve deliberate attention.

!!! danger "An operator is executable configuration with cluster-wide permissions"

    Installing an operator typically creates CustomResourceDefinitions, a ClusterRole (often broad), a ClusterRoleBinding, a Deployment, and sometimes an admission webhook. Any of those can compromise or destabilise the cluster: a webhook with `failurePolicy: Fail` and one replica blocks every matching write when that replica is unavailable; a ClusterRole with `*` on `*` is cluster admin by another name. **Read what a chart creates before installing it**, pin exact versions, mirror charts into your own registry, and treat an operator upgrade with the same care as a Kubernetes upgrade — because for the resources it owns, it is one.

---

## Internal Working

### How a Pod is routed to Fargate

```mermaid
sequenceDiagram
    participant U as "kubectl apply"
    participant API as "kube-apiserver"
    participant MUT as "Fargate mutating webhook (control plane)"
    participant FS as "Fargate scheduler"
    participant FC as "Fargate control plane"
    participant VM as "Dedicated micro-VM"
    participant ECR as "Amazon ECR"
    U->>API: "create Pod in namespace 'ci' with label runner=true"
    API->>MUT: "mutating admission"
    MUT->>MUT: "evaluate Fargate profile selectors for this namespace and labels"
    alt a profile matches
        MUT->>API: "set schedulerName to fargate-scheduler; add eks.amazonaws.com/fargate-profile label"
        API-->>FS: "unscheduled Pod for the Fargate scheduler"
        FS->>FC: "request capacity for the rounded-up CPU/memory shape"
        FC->>VM: "provision a micro-VM in a profile subnet; attach an ENI; assign a VPC IP"
        VM->>ECR: "pull images using the POD EXECUTION ROLE"
        VM->>VM: "start containers"
        VM->>API: "register as a Node object named fargate-<ip>; report the Pod Running"
    else no profile matches
        API-->>API: "the default scheduler handles it; it lands on an EC2 node"
    end
```

The selector evaluation happens at **admission time**, which is why a Pod created before a profile existed does not move to Fargate and must be recreated, and why changing a namespace's labels does not migrate running Pods.

### How a managed node group version update proceeds

```mermaid
stateDiagram-v2
    [*] --> Requested : "UpdateNodegroupVersion"
    Requested --> Launching : "ASG desired capacity raised; new-AMI nodes launch"
    Launching --> Joining : "nodes bootstrap, register, become Ready"
    Joining --> Cordoning : "an old node is marked unschedulable"
    Cordoning --> Draining : "Pods evicted one at a time"
    Draining --> Blocked : "a PodDisruptionBudget denies eviction"
    Blocked --> Draining : "retry"
    Blocked --> Timeout : "update times out — the classic stalled upgrade"
    Timeout --> Forced : "force flag: evict regardless of PDBs"
    Draining --> Terminating : "node empty"
    Forced --> Terminating
    Terminating --> Cordoning : "next node, within maxUnavailable"
    Terminating --> Complete : "all nodes replaced"
    Complete --> [*]
```

### How an operator reconciles, and why level-triggering matters

An operator does not process a queue of events and hope none is missed. It is **level-triggered**: on every reconcile it reads the current desired state and the current actual state and computes the difference, so a missed event, a controller restart, or a manual change all converge to the same place on the next pass.

```mermaid
sequenceDiagram
    participant API as "kube-apiserver"
    participant INF as "Informer cache (watch + list)"
    participant WQ as "Work queue"
    participant REC as "Reconciler"
    participant WORLD as "The world: StatefulSets, AWS APIs, config"
    API-->>INF: "watch events for Database objects"
    INF->>WQ: "enqueue the object's key (deduplicated)"
    WQ->>REC: "Reconcile(namespace/name)"
    REC->>API: "read the current desired spec"
    REC->>WORLD: "observe actual state"
    REC->>REC: "compute the difference"
    REC->>WORLD: "act: create, update, or delete"
    REC->>API: "update status"
    alt not yet converged
        REC->>WQ: "requeue after a backoff"
    end
    Note over INF,REC: "Level-triggered: a missed event or a restart still converges"
```

This is why writing a controller is tractable, and why the advice for anyone writing one is that reconciliation must be **idempotent** — it will run many times for the same state, and it must be safe every time.

---

## Architecture Components

| Component | Responsibility |
|---|---|
| **Fargate profile** | Selects which Pods run on serverless capacity, and in which subnets |
| **Pod execution role** | The IAM role AWS's `kubelet` uses to register the Pod and pull images |
| **Fargate scheduler** | The alternative scheduler that binds matching Pods to Fargate capacity |
| **Fargate micro-VM** | One Pod's dedicated, isolated compute, destroyed on Pod termination |
| **Fargate log router** | Built-in Fluent Bit, configured in the `aws-observability` namespace |
| **Managed node group** | An EKS-operated ASG with AWS AMIs and lifecycle management |
| **Launch template** | The escape hatch for user data, AMI, volumes, security groups, and IMDS options |
| **EKS-optimized AMI** | AWS-published node image with `kubelet`, `containerd`, CNI, and bootstrap |
| **`updateConfig`** | Bounds concurrent node replacement during a version update |
| **Node instance role and `EC2_LINUX` access entry** | The node's identity and its cluster mapping, created automatically for managed groups |
| **Capacity type** | On-Demand, Spot, or Capacity Blocks |
| **Karpenter NodePool and NodeClass** | Declarative just-in-time provisioning constraints |
| **EKS add-on** | A versioned, AWS-managed cluster component with configuration and an IAM role |
| **`configurationValues`** | Add-on settings expressed through the EKS API |
| **Conflict resolution mode** | `NONE`, `OVERWRITE`, or `PRESERVE` for add-on configuration drift |
| **CustomResourceDefinition** | Extends the Kubernetes API with a new object kind |
| **Controller / operator** | Watches objects of that kind and reconciles the world toward them |
| **Admission webhook** | Where an operator validates or mutates writes; a cluster-wide dependency |
| **Finalizer** | Blocks deletion until cleanup completes; the cause of `Terminating` hangs |
| **Owner reference** | Enables garbage collection of an operator's child resources |
| **AWS Controllers for Kubernetes** | Operators that reconcile AWS resources from Kubernetes objects |

Read architecturally, these divide into **substrate** (Fargate, node groups, Karpenter — where Pods run), **platform components** (add-ons — what every cluster needs), and **extensions** (operators — what makes this cluster yours). The first is a per-workload decision, the second is a per-cluster baseline, and the third is where a platform team's judgement shows: every operator adds capability, an upgrade obligation, and a potential cluster-wide dependency.

---

## Request Lifecycle

### A mixed cluster serving one request

```mermaid
sequenceDiagram
    participant U as "User"
    participant ALB as "ALB (IP-mode targets)"
    participant WEB as "web Pod on a managed node group node"
    participant DNS as "CoreDNS (add-on)"
    participant PLUG as "plugin Pod on Fargate (isolated namespace)"
    participant CSI as "EBS CSI driver (add-on)"
    participant DB as "database Pod with a persistent volume"
    participant K as "Karpenter (operator)"
    U->>ALB: "HTTPS request"
    ALB->>WEB: "direct to the Pod IP — no node hop"
    WEB->>DNS: "resolve plugin.tenants.svc.cluster.local"
    DNS-->>WEB: "ClusterIP"
    WEB->>PLUG: "call the untrusted plugin, running in its own micro-VM"
    PLUG-->>WEB: "result"
    WEB->>DB: "query"
    DB->>CSI: "the volume was attached at Pod start by the CSI driver"
    DB-->>WEB: "rows"
    WEB-->>U: "response"
    Note over K: "Meanwhile: load rises, Pods go Pending, Karpenter launches a right-sized node"
```

The point of the diagram is that **one request traverses three different compute substrates and depends on two add-ons and an operator**, and that this is normal rather than exotic. The plugin runs on Fargate because it is untrusted; the database runs on a node because it needs EBS; the web tier runs on a managed node group because it is steady; and Karpenter adds capacity because the load is variable.

### An operator doing its job during a failure

```mermaid
sequenceDiagram
    participant EC2 as "EC2"
    participant NODE as "Node hosting the primary database Pod"
    participant API as "kube-apiserver"
    participant OP as "Database operator"
    participant REP as "Replica Pod"
    participant SVC as "Service: db-primary"
    EC2->>NODE: "instance failure"
    NODE--xAPI: "node stops reporting"
    API->>API: "node controller marks it NotReady, then evicts its Pods"
    API-->>OP: "watch event: the primary Pod is gone"
    OP->>REP: "promote the healthiest replica"
    OP->>SVC: "repoint the primary Service selector to the new primary"
    OP->>API: "create a replacement replica Pod"
    OP->>API: "update status: failover complete, replication re-establishing"
    Note over OP,REP: "The same fourteen-step runbook, executed in seconds, at 2 a.m., correctly"
```

---

## AWS Service Deep Dive

!!! warning "On numbers, versions, and quotas"

    Figures are representative as of 2026 and most quotas are **soft**. Fargate resource combinations, AMI families, add-on catalogues, and instance ENI limits change frequently. Verify against the EKS User Guide and AWS Service Quotas for your account and Region. Prices are indicative and stated only for relative magnitude.

### AWS Fargate on EKS

**Purpose.** Run Pods with no node to manage, and with per-Pod VM isolation.

**Architecture.** A mutating webhook in the control plane evaluates Fargate profile selectors at admission and assigns matching Pods to the Fargate scheduler. AWS provisions a dedicated micro-VM per Pod in one of the profile's private subnets, attaches an ENI, pulls images with the pod execution role, and registers the Pod as its own Node object.

**Important features.** Per-Pod isolation on a dedicated kernel; no AMI, patching, or capacity management; per-second billing with a one-minute minimum; namespace and label selectors with wildcard support; automatic distribution across the profile's subnets; built-in Fluent Bit log routing; EFS support; IRSA for workload identity.

**Limitations.** No DaemonSets, `hostNetwork`, `hostPort`, privileged containers, GPUs, or EBS volumes. No **EKS Pod Identity**. No `topologySpreadConstraints`, and node affinity is meaningless. Profiles are **immutable**, limited to five selectors, and must use private subnets. Resources are allocated in fixed combinations from 0.25 vCPU and 0.5 GB up to 16 vCPU and 120 GB, with roughly 256 MB reserved per Pod and 20 GiB of ephemeral storage by default. Load balancer targets must be **IP mode**. Pod start is slower because nothing is cached.

**Pricing model.** Per vCPU-second and GB-second of the **allocated** shape, from image pull until termination, with a one-minute minimum. Excellent for bursty and small workloads; more expensive than a well-packed node for steady, dense ones.

**Performance characteristics.** Pod start-up is typically tens of seconds and dominated by capacity provisioning and an uncached image pull. Steady-state performance is comparable to equivalent EC2 capacity.

**Availability.** Pods are distributed across the profile's subnets, but distribution is not guaranteed even; where exact zone balance matters, one profile per subnet is the documented technique.

**Security features.** Per-Pod kernel isolation; no node role for a container to steal; no host to compromise; a pod execution role unavailable to your containers; standard VPC networking and security groups.

**Service limits.** Representative soft quotas on Fargate profiles per cluster (commonly 10), selectors per profile (5), and concurrent Fargate Pods per Region.

**Common configurations.** A profile per isolation-sensitive or bursty namespace — `ci`, `tenant-plugins`, `preview-*` — with IRSA for AWS access, EFS for any persistence, IP-mode target groups, and requests tuned to land just under a resource combination boundary.

### EKS managed node groups

**Purpose.** Real EC2 nodes without the AMI, bootstrap, registration, and upgrade plumbing.

**Architecture.** EKS creates a launch template and an Auto Scaling group, launches instances from an EKS-optimized AMI, and creates an `EC2_LINUX` access entry so the node role may join. It monitors node health, replaces unhealthy instances, and orchestrates version updates as launch, cordon, drain, terminate.

**Important features.** AL2023, Bottlerocket, GPU, and Windows AMI families; custom launch templates for user data, AMI, volumes, security groups, and IMDS options; labels and taints declared on the group; On-Demand, Spot, and Capacity Blocks; Spot rebalance and interruption handling; `updateConfig` bounding concurrent replacement; a force flag for blocked drains; node auto-repair with the node monitoring agent; tags for cost allocation.

**Limitations.** Supplying a custom AMI ID transfers AMI lifecycle to you. Many configuration changes require node replacement. Instance types are fixed per group, so heterogeneous requirements mean several groups (or Karpenter). Scale-out is ASG-mediated and slower than Karpenter's direct launches. PodDisruptionBudgets can block an update indefinitely. There is no bin-packing intelligence: the group launches what it was told to launch.

**Pricing model.** EC2 instance, EBS, and data transfer charges only; the management is free.

**Performance characteristics.** Node launch to `Ready` is typically one to three minutes, dominated by instance launch, bootstrap, and CNI initialisation. Version updates take as long as draining requires.

**Scaling behaviour.** Scaled by the Cluster Autoscaler, by Karpenter (for other groups), or manually within `minSize` and `maxSize`.

**Availability.** Spanning three subnets across three Availability Zones is the baseline; the ASG balances across them.

**Security features.** IMDSv2 enforcement and hop limits through the launch template; Bottlerocket's minimal immutable host; encrypted EBS volumes; SSM access without SSH; automatic access entry rather than a hand-edited mapping.

**Service limits.** Representative soft quotas on node groups per cluster and nodes per group.

**Common configurations.** A general On-Demand group on AL2023 or Bottlerocket across three AZs; a tainted Spot group with four to six compatible instance types for batch; a small system group for controllers; a launch template setting IMDSv2 with a hop limit of 1; `maxUnavailablePercentage: 25`.

### EKS add-ons

**Purpose.** Install, configure, version, and upgrade cluster components through the EKS API rather than as loose manifests.

**Architecture.** The EKS API stores an add-on's name, version, `configurationValues`, IAM role, and conflict resolution mode, and applies the corresponding manifests into the cluster. Add-on Pods run in your data plane like any other workload.

**Important features.** Three tiers (AWS, Marketplace, community); explicit versioning with compatibility information per Kubernetes version; `configurationValues` as JSON or YAML; conflict resolution modes; IAM roles through IRSA or Pod Identity; CloudTrail visibility; installable at cluster creation.

**Limitations.** Not every component is available as an add-on, so operators still arrive by Helm. Some deep customisations require `PRESERVE` and careful management. Add-on versions must be tracked against Kubernetes versions, which is work you cannot delegate. An add-on update is a data plane change and can be disruptive if mishandled.

**Pricing model.** No charge for AWS add-ons beyond the resources they consume; Marketplace add-ons carry their vendor's pricing.

**Common configurations.** VPC CNI with `ENABLE_PREFIX_DELEGATION` and network policy enabled; CoreDNS with at least two replicas and anti-affinity; `kube-proxy`; EBS CSI driver with its own IAM role; Pod Identity Agent; CloudWatch Observability; all pinned to versions in infrastructure as code.

### Operators and custom controllers

**Purpose.** Extend the Kubernetes API with domain-specific objects, and encode operational expertise as a continuously running control loop.

**Architecture.** A CustomResourceDefinition registers the new kind with an OpenAPI schema; a controller watches those objects through an informer, enqueues keys, and runs an idempotent reconcile function that compares desired to actual state and acts. Owner references provide garbage collection; finalizers gate deletion; the status subresource separates reported from desired state; admission webhooks enforce rules at write time; leader election provides high availability.

**Important features.** New object kinds with validation, RBAC, and `kubectl` support inherited automatically; level-triggered reconciliation that is robust to missed events and restarts; the ability to manage anything with an API, including AWS resources through ACK.

**Limitations.** Every operator is a workload to run, secure, and upgrade. Operators typically require broad RBAC and sometimes cluster admin. Admission webhooks become cluster-wide dependencies. Finalizers cause deletion hangs when a controller is removed. CRD version upgrades can be disruptive. Operator quality across the ecosystem varies enormously, and a poor one fails in ways that are hard to diagnose because the failure is inside someone else's control loop.

**Pricing model.** No AWS charge; the cost is the resources the controller consumes and the operational attention it requires.

**Common configurations.** A deliberately small baseline — AWS Load Balancer Controller, ExternalDNS, cert-manager, External Secrets Operator, Karpenter, a metrics stack, and a GitOps controller — installed from mirrored charts at pinned versions, each with a scoped IAM role and, where it registers a webhook, multiple replicas and a PodDisruptionBudget.
---

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **AWS Fargate** | Serverless compute in which each Pod runs in its own dedicated micro-VM |
| **Fargate profile** | The object selecting which Pods run on Fargate, and in which subnets |
| **Selector** | A namespace (required) plus optional labels; up to five per profile |
| **Pod execution role** | The IAM role AWS's `kubelet` uses on Fargate; trusted by `eks-fargate-pods.amazonaws.com` |
| **`eks.amazonaws.com/fargate-profile`** | The label identifying, or forcing, the profile a Pod uses |
| **Fargate scheduler** | The alternative scheduler that binds matching Pods to Fargate capacity |
| **Resource combination** | The fixed CPU and memory shapes Fargate allocates; requests are rounded up |
| **Ephemeral storage** | Fargate's per-Pod scratch space, 20 GiB by default and expandable |
| **Managed node group** | An EKS-operated Auto Scaling group of EC2 nodes with AWS AMIs |
| **Self-managed node** | An EC2 instance you bootstrap, register, and upgrade yourself |
| **EKS-optimized AMI** | AWS-published node image containing `kubelet`, `containerd`, the CNI, and bootstrap tooling |
| **Bottlerocket** | A minimal, immutable, API-driven container host OS with no shell or package manager |
| **Amazon Linux 2023** | The general-purpose EKS node OS, bootstrapped with `nodeadm` and a `NodeConfig` |
| **Launch template** | The EC2 object allowing custom user data, AMI, volumes, security groups, and IMDS options |
| **`nodeadm` / `NodeConfig`** | The AL2023 node bootstrap mechanism |
| **`EC2_LINUX` access entry** | The node role mapping created automatically for managed node groups |
| **`updateConfig`** | `maxUnavailable` or `maxUnavailablePercentage` bounding concurrent node replacement, plus the update strategy |
| **Force update** | A node group update that ignores PodDisruptionBudgets |
| **Capacity type** | `ON_DEMAND`, `SPOT`, or `CAPACITY_BLOCK` |
| **Rebalance recommendation** | An early Spot signal, before the two-minute interruption notice |
| **Spot interruption notice** | The two-minute warning that triggers a cordon and drain |
| **Capacity-optimized allocation** | Launching Spot capacity from the least-interrupted pools |
| **Karpenter** | An operator that provisions right-sized EC2 instances just in time from pending Pods |
| **NodePool / EC2NodeClass** | Karpenter's declarative provisioning constraints and AWS-specific node settings |
| **Consolidation** | Karpenter replacing under-utilised nodes with cheaper or fewer ones |
| **Drift** | Karpenter replacing nodes whose configuration no longer matches their NodePool |
| **EKS Auto Mode** | AWS management of the whole data plane: compute, networking, storage, load balancing |
| **EKS add-on** | An AWS-managed, versioned deployment of a cluster component |
| **`configurationValues`** | Add-on settings supplied through the EKS API as JSON or YAML |
| **Conflict resolution** | `NONE`, `OVERWRITE`, or `PRESERVE` when add-on configuration differs from the cluster |
| **AWS add-on / Marketplace add-on / community add-on** | The three support tiers |
| **CustomResourceDefinition (CRD)** | Extends the Kubernetes API with a new object kind and schema |
| **Custom resource** | An instance of a CRD-defined kind |
| **Controller** | A loop that watches objects and reconciles the world toward them |
| **Operator** | A controller plus CRDs that encodes domain expertise for a specific system |
| **Reconciliation loop** | The level-triggered compare-and-act cycle at the heart of every controller |
| **Level-triggered** | Acting on current state rather than on events; robust to missed events and restarts |
| **Informer** | The cached watch mechanism controllers use instead of polling the API server |
| **Owner reference** | Marks a resource as owned by another, enabling garbage collection |
| **Finalizer** | Blocks deletion until cleanup completes; the usual cause of `Terminating` hangs |
| **Status subresource** | The controller-written half of an object, separate from the user-written `spec` |
| **Admission webhook** | An operator's validating or mutating hook in the API server's write path |
| **Leader election** | One active controller replica among several |
| **AWS Controllers for Kubernetes (ACK)** | Operators that reconcile AWS resources from Kubernetes objects |
| **`deletionPolicy: retain`** | An ACK annotation preventing deletion of the underlying AWS resource |

---

## Configuration Options

### Fargate

| Setting | Options | How to decide |
|---|---|---|
| **Profile granularity** | One profile per namespace, or one covering several | One per stable namespace boundary; profiles are immutable, so avoid churn |
| **Selectors** | Namespace, plus optional labels, up to five | Namespace-only where possible; label selectors couple you to application team choices |
| **Subnets** | Private subnets only | All three AZs' private subnets; a profile per subnet where exact zone balance is required |
| **Pod execution role** | An IAM role | Minimum permissions: ECR pull and cluster registration; never application permissions |
| **Workload identity** | IRSA only | Pod Identity does not work on Fargate |
| **Requests** | Any values | Tune to land just **under** a resource combination boundary; you pay for the allocation |
| **Ephemeral storage** | 20 GiB default, expandable | Raise only where genuinely needed; it is billable |
| **Storage** | EFS only | EBS is impossible; design around it or use a node |
| **Logging** | Fluent Bit ConfigMap in `aws-observability` | Configure it at cluster build; there is no node for a log DaemonSet |

### Managed node groups

| Setting | Options | How to decide |
|---|---|---|
| **AMI family** | AL2023, Bottlerocket, GPU, Windows | Bottlerocket where nothing needs host customisation; AL2023 otherwise |
| **Instance types** | One or several | Several compatible types, especially for Spot; check ENI limits against required Pod density |
| **Capacity type** | On-Demand, Spot, Capacity Blocks | On-Demand base sized for floor traffic; Spot above it, tainted |
| **Group layout** | One or several groups | A general group, a tainted Spot group, and a small system group for controllers |
| **Labels and taints** | Any | Labels express scheduling intent; taints dedicate capacity |
| **`updateConfig`** | Count or percentage | 1 for small groups; 25 per cent for large ones |
| **Launch template** | Optional | Use it for IMDS options, volumes, and security groups; avoid custom AMI IDs unless necessary |
| **IMDS** | Tokens required, hop limit | **Required, hop limit 1** — the Chapter 3.1 control that makes per-Pod identity meaningful |
| **Disk** | Size and type | Large enough for the image cache; a small disk causes `DiskPressure` evictions |
| **Scaling** | Cluster Autoscaler, Karpenter, or manual | Karpenter where scale-out latency and packing matter |

### Add-ons

| Setting | Options | How to decide |
|---|---|---|
| **Which add-ons** | The four core plus what you need | VPC CNI, CoreDNS, `kube-proxy`, Pod Identity Agent as a baseline; EBS CSI if anything is stateful |
| **Version** | Explicit or default | Explicit and pinned in IaC; update as a step of every cluster upgrade |
| **Conflict resolution** | `NONE`, `OVERWRITE`, `PRESERVE` (`PRESERVE` on update only) | `OVERWRITE` normally; `PRESERVE` only where you have deliberate customisations |
| **`configurationValues`** | JSON or YAML | Put CNI prefix delegation, CoreDNS replicas, and tolerations here rather than in ad-hoc commands |
| **IAM** | IRSA or Pod Identity association | Always; never let an add-on rely on the node role |

### Operators

| Setting | Options | How to decide |
|---|---|---|
| **Which operators** | A deliberately small set | Each adds capability, an upgrade obligation, and a possible cluster-wide dependency |
| **Source** | Public chart or internal mirror | Mirror into ECR and pin exact versions; a chart is executable configuration |
| **Scope** | Cluster-wide or namespaced | Namespaced where the operator supports it |
| **RBAC** | As shipped, or reduced | Review the ClusterRole; a `*` on `*` is cluster admin |
| **Webhook `failurePolicy`** | `Fail` or `Ignore` | `Fail` only for security-critical policy, and then with multiple replicas and a PDB |
| **Replicas** | One or several with leader election | Several for anything on the write path or the request path |
| **ACK deletion policy** | Delete or retain | `retain` for anything whose loss would be catastrophic |

!!! tip "Three settings that pay for themselves immediately"

    **IMDS hop limit 1 on every node group**, which turns per-Pod identity from decoration into a control. **`ENABLE_PREFIX_DELEGATION` in the VPC CNI's `configurationValues`**, which multiplies Pod density for free. And **CoreDNS at two or more replicas with anti-affinity and a PodDisruptionBudget**, which prevents the single most confusing class of cluster-wide outage. None takes more than a few lines, and each removes a whole category of incident.

---

## Design Considerations

```mermaid
flowchart TD
    A["A workload arrives. Where should it run?"] --> B{"Does it need a node's capabilities?"}
    B -->|"DaemonSet agent, EBS, GPU, privileged, host network"| C["Node required"]
    B -->|"no"| D{"Untrusted, multi-tenant, or isolation-regulated?"}
    D -->|"yes"| E["Fargate profile: per-Pod VM isolation"]
    D -->|"no"| F{"Bursty, short-lived, or very small?"}
    F -->|"yes"| E
    F -->|"no: steady and dense"| C
    C --> G{"Is the capacity requirement uniform and predictable?"}
    G -->|"yes"| H["Managed node group with fixed instance types"]
    G -->|"no: heterogeneous or spiky"| I["Karpenter over a small managed node group"]
    H --> J{"Interruption tolerant?"}
    I --> J
    J -->|"yes"| K["Spot above an On-Demand base, tainted, with diverse types"]
    J -->|"no"| L["On-Demand"]
    K --> M["Then: which add-ons and operators does this cluster need, and who upgrades them?"]
    L --> M
```

| Quality | What it means here | Design levers | The trade-off you accept |
|---|---|---|---|
| **Operational burden** | How much data plane you run | Fargate, Auto Mode, managed groups, add-ons | Less burden means less control and, for Fargate and Auto Mode, a price premium |
| **Isolation** | What a container escape reaches | Fargate micro-VMs, Bottlerocket, separate node groups, taints | Isolation costs density, and Fargate costs node capabilities |
| **Cost** | Paying for used rather than provisioned capacity | Spot, Graviton, Karpenter consolidation, Fargate for bursty work | Spot needs tolerance; consolidation churns Pods; Fargate is dearer when dense |
| **Elasticity** | How fast capacity appears | Karpenter, warm capacity, Fargate | Karpenter is another operator; warm capacity is idle spend |
| **Extensibility** | What the platform can do for teams | Operators, CRDs, ACK | Every operator is a component to secure and upgrade, and may be a cluster-wide dependency |
| **Upgradability** | How hard the annual upgrade is | Fewer operators; add-ons over loose manifests; pinned versions | A small platform does less; a large one is harder to move forward |
| **Portability** | What survives leaving EKS | Standard Kubernetes objects and operators | ACK, Fargate profiles, and add-on configuration do not |

!!! danger "Every operator you install is a component you must upgrade forever"

    A cluster upgrade is only as easy as its least compatible component. Ten operators means ten compatibility matrices to check against every Kubernetes version, ten changelogs to read, and ten chances that something breaks during an upgrade that is effectively one-way. Teams accumulate operators enthusiastically and account for them never. The discipline is to require, for each one, a named owner, a pinned version in infrastructure as code, and a documented answer to "what breaks if this is unavailable" — and to remove the ones nobody can answer for.

---

## AWS Best Practices

### Operational Excellence

Define node groups, Fargate profiles, and add-ons in infrastructure as code with pinned versions, and treat add-on updates as an explicit step of the cluster upgrade rather than something noticed later. Keep the operator set small and owned. Enable the node monitoring agent so unhealthy nodes are detected and repaired rather than sitting `NotReady`. Rotate nodes regularly — through node group updates, or Karpenter expiry and drift — so no node is a year old and the drain path is exercised routinely rather than discovered during an emergency. Use taints and labels deliberately so workload placement is expressed rather than incidental.

### Security

Enforce IMDSv2 with a hop limit of 1 on every node group, without which per-Pod identity is decorative. Prefer Bottlerocket where nothing needs host customisation. Give every add-on and operator its own IAM role through IRSA or Pod Identity; never let one rely on the node role. Read what an operator's chart creates — ClusterRoles, webhooks, CRDs — before installing it, and mirror charts into your own registry at pinned versions. Use Fargate for untrusted or multi-tenant code, where per-Pod VM isolation is a genuine boundary rather than a shared-kernel assumption. Restrict who may create CRDs and ClusterRoleBindings, since both are effectively cluster-level privilege.

### Reliability

Run CoreDNS with at least two replicas, anti-affinity, a PodDisruptionBudget, and scaling appropriate to cluster size. Give every operator that registers an admission webhook multiple replicas and a PodDisruptionBudget, and set `failurePolicy: Ignore` unless the webhook is security-critical. Spread node groups across three Availability Zones. Size Spot node groups with several compatible instance types so one pool's reclamation is a partial loss. Keep PodDisruptionBudgets with slack so node group updates can make progress. Understand which add-ons are on the request path — the CNI, `kube-proxy`, CoreDNS — and treat their configuration changes with production care.

### Performance Efficiency

Enable prefix delegation through the CNI add-on's `configurationValues` so nodes reach their compute capacity rather than their IP ceiling. Use Karpenter where scale-out latency matters, since it launches instances directly rather than adjusting an Auto Scaling group. Right-size Fargate requests to land just under a resource combination boundary. Keep images small, because Fargate has no image cache at all and node replacement invalidates the node's. Choose the AMI family for boot speed as well as security — Bottlerocket boots faster because it contains less.

### Cost Optimization

Run an On-Demand base sized for floor traffic with tainted Spot capacity above it. Use Graviton where the workload supports ARM. Let Karpenter consolidate under-utilised nodes. Use Fargate where a node would sit mostly idle, and nodes where Fargate's per-Pod premium would compound. Right-size requests, because on nodes they drive node count and on Fargate they drive the billed shape directly. Delete Fargate profiles and node groups for environments nobody uses, and prefer scaling a Spot batch group to zero over keeping it warm.

### Sustainability

The same levers: higher utilisation through consolidation and accurate requests, Graviton's better performance per watt, Spot capacity that uses inventory that would otherwise idle, and scaling batch groups to zero between runs. Fargate's per-Pod model is efficient for bursty workloads and wasteful for dense ones — matching substrate to shape is the sustainability decision as much as the cost one.

---

## Security Considerations

**Fargate's isolation is a genuine boundary, and it is the strongest argument for it.** On a shared node, a container escape reaches a kernel shared with every other Pod on that node. On Fargate it reaches an AWS-managed kernel running one Pod. For untrusted code, customer-supplied plugins, or multi-tenant workloads, that difference is the whole security case — and it applies to a namespace rather than to a cluster, which is why selective Fargate profiles beat a Fargate-only cluster.

**The pod execution role is not a node role, and that is an improvement.** It is used by AWS's `kubelet` to register the Pod and pull images, and it is not available to your containers — so the Chapter 3.1 failure in which every Pod on a node can assume the node's role simply does not exist on Fargate. On EC2 nodes the equivalent protection is the IMDS hop limit, which is a setting you must apply rather than a property you inherit.

**Node group configuration carries the security controls that matter most.** IMDSv2 required with a hop limit of 1; encrypted EBS volumes; a minimal AMI; SSM rather than SSH; and node rotation so the running kernel is recent. Bottlerocket adds an immutable root filesystem and no shell to exploit, which removes a large class of post-compromise activity.

**Add-ons should hold their own IAM roles.** The EBS CSI driver needs permission to create and attach volumes; the CNI needs permission to manage ENIs; the load balancer controller needs permission to create load balancers. Granting these to the node role gives every Pod on the node the same abilities, which is exactly the pattern per-Pod identity exists to eliminate.

**Operators are the largest under-examined privilege in most clusters.** An operator typically installs CRDs, a broad ClusterRole, a ClusterRoleBinding, a Deployment, and sometimes an admission webhook. Any of these can be a compromise or an outage: a webhook with `failurePolicy: Fail` and one replica blocks every matching write when unavailable; a ClusterRole with wildcards is cluster admin under another name; and a CRD's controller can create anything it is permitted to. Review before installing, pin versions, mirror charts, and restrict who may create CRDs and ClusterRoleBindings at all.

**ACK deserves specific caution.** A controller that can create S3 buckets and RDS instances can also delete them, and Kubernetes garbage collection means deleting a namespace can delete production data. Use `deletionPolicy: retain` for anything whose loss would be serious, scope the controller's IAM role narrowly, and keep long-lived shared infrastructure in Terraform or CloudFormation where its lifecycle is not tied to a cluster's.

!!! danger "A single-replica admission webhook is a cluster-wide single point of failure"

    When an operator registers a validating or mutating webhook with `failurePolicy: Fail`, the API server calls it — inbound into your VPC, as Chapter 3.1 described — on every matching write. If its one Pod is evicted during a node scale-in, every matching write fails and deployments stop cluster-wide. Multiple replicas, a PodDisruptionBudget, anti-affinity, and `failurePolicy: Ignore` for anything that is not security-critical are the four settings that prevent it, and none of them is the default in most charts.

---

## Performance Optimization

**Match the substrate to the shape of the workload.** A steady, dense service on Fargate pays a per-Pod premium and a slower start for isolation it may not need. A four-minute CI job on a node pays for launch, join, and drain. Getting this right per workload is worth more than tuning anything within either substrate.

**Reduce Fargate's start-up cost where it dominates.** Small images matter more here than anywhere else, because there is no node-level cache and every Pod pulls fresh. Where start-up latency is on the user-visible path, Fargate is usually the wrong substrate regardless of tuning.

**Use Karpenter where scale-out latency matters.** Direct EC2 launches from pending Pods' actual requirements are typically faster than an Auto Scaling group adjustment, and the instances chosen fit the Pods rather than the other way round.

**Keep enough headroom that placement is immediate.** A Pod that must wait for a node is a Pod that waits minutes. Whether that headroom comes from a capacity provider target below 100 per cent, Karpenter's speed, or over-provisioning placeholder Pods with low priority, it is a deliberate purchase of responsiveness.

**Right-size in the units you are billed in.** On nodes, requests drive node count; on Fargate, requests drive the allocated shape directly, and a Pod requesting 3 vCPU is billed for 4. The optimisation is different in kind, and on Fargate it is unusually direct.

**Scale CoreDNS with the cluster.** DNS is on the path of nearly every request, and an under-scaled CoreDNS produces latency that appears distributed across every service and is attributed to none of them.

**Enable prefix delegation.** A node capped at 29 Pods when it could run 110 is being wasted at four times its cost, and this is one setting in the CNI add-on's configuration.

---

## Cost Optimization

| Lever | Mechanism | Caution |
|---|---|---|
| **Spot above an On-Demand base** | A tainted Spot node group with several instance types | The base must carry floor traffic alone; workloads must tolerate rescheduling |
| **Graviton** | ARM instance families | Requires multi-architecture images and dependency support |
| **Karpenter consolidation** | Automatic replacement of under-utilised nodes | Pod churn; bound it with PodDisruptionBudgets and `do-not-disrupt` |
| **Fargate for bursty work** | Per-Pod billing with a one-minute minimum | More expensive than a well-packed node for steady, dense workloads |
| **Right-sized Fargate requests** | Land just below a resource combination boundary | You are billed for the allocation, not the request |
| **Prefix delegation** | One CNI setting | Turns IP-bound nodes into compute-bound nodes at no cost |
| **Scale batch groups to zero** | `minSize: 0` with Karpenter or the Cluster Autoscaler | Only for workloads that genuinely stop |
| **Fewer operators** | Governance | Each consumes resources continuously and attention permanently |
| **Capacity Blocks for GPU** | Reserved future capacity | Only where the schedule is known in advance |
| **Node rotation and consolidation together** | Regular replacement plus right-sizing | Churn; ensure PodDisruptionBudgets are correct first |

**The structural mistakes cost more than the tactical ones.** Running everything on Fargate because it is convenient is expensive at any real scale. Running everything On-Demand because Spot seems risky forgoes a large saving on workloads that would tolerate it perfectly. And an operator estate nobody prunes consumes both compute and, more expensively, the engineering attention that every upgrade requires.

---

## Monitoring and Observability

| Signal | Source | What it tells you |
|---|---|---|
| **Node conditions** | `kubectl get nodes`, Container Insights | `NotReady`, `MemoryPressure`, `DiskPressure` — the first sign of a node problem |
| **Node group update status** | `describe-nodegroup`, CloudTrail | Whether an upgrade is progressing, blocked, or timed out |
| **`kubectl get pdb -A`** | API server | `ALLOWED DISRUPTIONS: 0` is the diagnosis for every stalled drain |
| **Spot interruption and rebalance events** | EventBridge, CloudWatch | How often Spot capacity is being reclaimed, and whether drains complete in time |
| **Fargate Pod start latency** | Pod events, Container Insights | Whether Fargate's start-up cost is affecting the workload |
| **Fargate Pods running and their shapes** | `kubectl get nodes -l eks.amazonaws.com/compute-type=fargate` | What you are actually being billed for |
| **Add-on versions and health** | `describe-addon`, add-on Pod status | Version drift against the control plane; `DEGRADED` add-on status |
| **CoreDNS request rate, error rate, latency** | CoreDNS metrics | The most misdiagnosed cluster-wide failure |
| **CNI IP metrics** | `awscni_total_ip_addresses`, `awscni_assigned_ip_addresses` | Approaching the ceiling of Chapter 3.1 |
| **Operator controller metrics** | Controller-runtime metrics (reconcile errors, queue depth, latency) | Whether an operator is keeping up or silently failing |
| **Custom resource status conditions** | `kubectl get <kind> -o wide` | An operator's own report of whether it has converged |
| **Admission webhook latency and errors** | API server metrics, Pod logs | A webhook degrading the write path before it fails it |
| **Karpenter metrics** | Karpenter's Prometheus metrics | Time from unschedulable Pod to ready node; consolidation activity |
| **Node age distribution** | Container Insights, EC2 | Whether nodes are being rotated or quietly accumulating age |

**Three dashboards worth building.** A **substrate dashboard** showing Pods by compute type — managed node group, Spot, Fargate — so the mix is visible and cost conversations have data. A **platform health dashboard** covering add-on versions, CoreDNS metrics, CNI IP headroom, and operator reconcile error rates, because these fail quietly and take everything with them. And an **upgrade readiness dashboard** showing the Kubernetes version, add-on versions against their compatibility, node age, and PodDisruptionBudgets with zero allowed disruptions — because that last column is what will stall the next upgrade.

!!! tip "`kubectl get pdb -A` is the fastest pre-upgrade check there is"

    One column — `ALLOWED DISRUPTIONS` — tells you which workloads will block a node drain. Running it before every node group update converts the most common cause of a four-hour stalled upgrade into a two-minute fix beforehand. Add it to the upgrade runbook and to a dashboard, and the class of incident largely disappears.

---

## Integration with Other AWS Services

| Service | Why it integrates |
|---|---|
| **Amazon EC2** | The instances behind managed node groups, Karpenter, and Auto Mode |
| **EC2 Auto Scaling** | The group EKS creates and operates for a managed node group |
| **Amazon EC2 Spot** | Interruption-tolerant capacity with rebalance and interruption handling |
| **AWS Fargate** | The serverless substrate behind Fargate profiles |
| **Amazon ECR** | Images pulled by the node role on EC2, or the pod execution role on Fargate |
| **Amazon EBS / EFS / FSx / S3** | Storage through CSI driver add-ons; EFS is the Fargate-compatible option |
| **AWS IAM** | Node instance roles, pod execution roles, and per-add-on and per-operator roles |
| **Elastic Load Balancing** | ALBs and NLBs created by the AWS Load Balancer Controller operator |
| **Amazon Route 53** | Records created by the ExternalDNS operator |
| **AWS Certificate Manager** | Certificates referenced by Ingress, or issued in-cluster by cert-manager |
| **AWS Secrets Manager** | Values injected by the External Secrets Operator or the Secrets Store CSI Driver |
| **Amazon CloudWatch** | Container Insights and logs through the CloudWatch Observability add-on; Fluent Bit on Fargate |
| **Amazon Managed Service for Prometheus / Grafana** | The metrics path the Prometheus Operator feeds |
| **Amazon GuardDuty** | Runtime monitoring through the GuardDuty agent add-on |
| **AWS Systems Manager** | Node access without SSH; patch and inventory data |
| **Amazon EventBridge** | Spot interruption, node group, and cluster state change events |
| **AWS CloudTrail** | Audit of node group, Fargate profile, and add-on operations |
| **AWS resources generally** | Provisioned as Kubernetes objects through ACK |

```mermaid
flowchart TD
    CLUSTER["EKS control plane"] --> MNG["Managed node groups: general On-Demand and tainted Spot"]
    CLUSTER --> FP["Fargate profiles: ci and tenant-plugins namespaces"]
    CLUSTER --> ADDON["EKS add-ons: VPC CNI, CoreDNS, kube-proxy, EBS CSI, Pod Identity Agent, CloudWatch"]
    MNG --> KARP["Karpenter operator runs here and provisions further nodes just in time"]
    KARP --> EC2["Amazon EC2, including Spot pools"]
    ADDON --> EBS["Amazon EBS volumes for stateful workloads"]
    FP --> EFS["Amazon EFS for Fargate persistence"]
    OPS["Operators: AWS Load Balancer Controller, ExternalDNS, cert-manager, External Secrets, Argo CD"] --> ELB["Elastic Load Balancing"]
    OPS --> R53["Amazon Route 53"]
    OPS --> SM["AWS Secrets Manager"]
    ACK["AWS Controllers for Kubernetes"] --> AWSRES["S3 buckets, SQS queues, DynamoDB tables owned by one service"]
    ADDON --> CW["Amazon CloudWatch"]
    EBRIDGE["Amazon EventBridge: Spot interruption and node group events"] --> MNG
    CLUSTER --> CT["AWS CloudTrail"]
```

Read architecturally, the diagram shows the same pattern three times. **Add-ons** turn AWS-built components into managed cluster objects. **Operators** turn Kubernetes objects into AWS resources — an Ingress into an ALB, an ExternalSecret into a Secrets Manager read, a NodePool into EC2 instances. And **ACK** generalises that to AWS resources at large. All three are the reconciliation loop applied to different domains, which is why understanding the pattern once explains the whole picture.

---

## Common Architecture Patterns

### The mixed data plane

One cluster, three substrates: a general managed node group for steady services, a tainted Spot group for batch and CI, and Fargate profiles for isolation-sensitive namespaces. This is the pattern most production clusters converge on, and its virtue is that each workload gets the substrate whose trade-offs suit it rather than the one the cluster happened to standardise on.

### On-Demand base with tainted Spot above

An On-Demand group sized to carry floor traffic alone, and a Spot group carrying diverse instance types with a taint that only interruption-tolerant workloads tolerate. Identical in shape to Chapter 2.3's ECS capacity provider strategy, expressed in Kubernetes vocabulary.

### Karpenter over a small system node group

A small managed node group runs the controllers — Karpenter itself, the load balancer controller, CoreDNS, the GitOps controller — and Karpenter provisions everything else just in time. This solves the bootstrap problem (Karpenter must run somewhere) while getting Karpenter's speed and packing for the workloads that vary.

### Fargate for the untrusted namespace

Rather than Fargate everywhere, a profile scoped to the namespace running customer-supplied or third-party code. Per-Pod VM isolation applies exactly where it is worth its cost, and the rest of the cluster keeps DaemonSets, EBS, and GPUs.

### Add-ons as code, pinned and upgraded together

The four core add-ons plus whatever else the cluster needs, declared with explicit versions and `configurationValues` in infrastructure as code, updated as a step in the same change that upgrades the control plane. This is what prevents the two-year-old CNI of the motivation section.

### A deliberately minimal operator baseline

AWS Load Balancer Controller, ExternalDNS, cert-manager, External Secrets Operator, Karpenter, a metrics stack, and a GitOps controller — each with a named owner, a pinned version from a mirrored chart, a scoped IAM role, and multiple replicas where it registers a webhook. Everything beyond that baseline must justify its permanent upgrade cost.

### ACK for service-owned resources only

A queue, a bucket, or a table whose lifetime matches one service is declared in that service's manifests with a retain deletion policy; VPCs, shared databases, and anything whose deletion would be catastrophic stay in Terraform or CloudFormation. This keeps the developer self-service benefit without tying critical infrastructure to a cluster's lifecycle.

### Node rotation as routine

Nodes replaced on a regular cadence — node group updates, or Karpenter expiry and drift — so the running kernel is recent, the drain path is exercised, and PodDisruptionBudget mistakes are found on an ordinary Tuesday rather than during an emergency upgrade.

---

## Industry Use Cases

| Sector | Configuration | Reasoning |
|---|---|---|
| Higher education | Managed node groups for teaching clusters; Fargate for student-submitted code | Per-Pod isolation for untrusted submissions without a node per student |
| Higher education | Spot GPU groups with Capacity Blocks for scheduled research runs | Cost-dominated, interruption-tolerant, with known peaks |
| E-commerce | On-Demand base plus tainted Spot; Karpenter for the storefront's variable load | Availability where revenue depends on it, cost where it does not |
| E-commerce | Fargate profiles for preview environments per pull request | Bursty, short-lived, and cheaper than keeping nodes for them |
| Financial services | Bottlerocket everywhere; IMDS hop limit 1; a minimal, reviewed operator set | Attack surface and auditability are controls, not preferences |
| Financial services | Database operators for stateful services with automated failover | Encoded expertise executed at 2 a.m. correctly |
| Media | GPU node groups with taints for transcoding; Spot with several families | Expensive capacity that must not idle and can absorb interruption |
| Media | Karpenter consolidation across a large heterogeneous fleet | Bin packing at a scale where manual instance selection cannot keep up |
| Healthcare | Fargate for third-party integration adapters | Untrusted vendor code isolated per Pod |
| Healthcare | External Secrets Operator against Secrets Manager | Auditable, rotating secret access under per-workload roles |
| SaaS | Fargate for customer plugin execution; nodes for the platform itself | Isolation exactly where multi-tenancy makes it necessary |
| Logistics | ACK for service-owned queues and tables; Terraform for shared infrastructure | Developer self-service without tying critical resources to a cluster |
| Machine learning | Karpenter with GPU NodePools and Capacity Blocks; Kubeflow operators | Heterogeneous, expensive, bursty capacity with a large operator surface |
| Government | Managed node groups only, pinned add-on versions, an approved operator list | Change control and supply chain provenance as formal requirements |

---

## Advantages

**The data plane becomes a per-workload decision rather than a cluster-wide commitment.** Fargate, managed node groups, Spot groups, Karpenter, and Auto Mode coexist in one cluster, so an untrusted plugin, a GPU training job, and a steady web tier each get the substrate that suits them without separate platforms.

**Fargate removes the node and everything that comes with it.** No AMI, no patching, no capacity planning, no bin packing, no node role to steal, and a kernel shared with nothing. For bursty, small, or untrusted workloads that is a substantial reduction in both operational burden and attack surface.

**Managed node groups remove the plumbing without removing control.** AWS publishes the AMI, bootstraps the node, creates the access entry, monitors health, and orchestrates cordon-and-drain upgrades; you keep instance types, sizes, labels, taints, and capacity strategy. The drain logic in particular is the part that is genuinely hard to write and easy to get subtly wrong.

**Spot becomes routine rather than risky.** Capacity-optimized allocation, rebalance recommendations, and interruption-triggered drains mean a well-configured Spot node group behaves like ordinary capacity that occasionally rotates, which is what makes the saving accessible to teams that would otherwise avoid it.

**Add-ons make cluster components visible, versioned, and upgradable.** A component with a version field in an API is a component someone can own; a component applied from a URL two years ago is not. This is a small mechanism with a disproportionate effect on whether a cluster can be upgraded.

**Operators encode expertise and execute it continuously.** A database operator performs the failover correctly at 2 a.m. every time, which is more than can be said for the runbook that describes the same steps. The pattern generalises: anything with an API can be reconciled toward a declared state.

**The extension mechanism is uniform.** A CustomResourceDefinition plus a controller is how the AWS Load Balancer Controller, Karpenter, cert-manager, ACK, and your own future controller all work. Learning the pattern once explains the ecosystem and makes writing your own tractable.

---

## Limitations

**Fargate's limitations are structural, not a roadmap.** No DaemonSets, host networking, privileged containers, GPUs, or EBS volumes; no EKS Pod Identity; no topology spread; fixed resource shapes; slower start. These follow from there being no node, so they will not be fixed by a future release — they are the trade.

**Fargate is expensive for steady, dense workloads.** Per-Pod billing on a rounded-up shape, plus a 256 MB reservation per Pod, plus no bin packing, means a fleet of always-on services costs materially more than the equivalent well-packed nodes.

**Managed node groups are not intelligent about capacity.** They launch what they were told to launch; they do not choose instance shapes from pending Pods, do not consolidate, and scale through an Auto Scaling group rather than directly. Heterogeneous requirements mean several groups or a second tool.

**Node group updates can be blocked by your own configuration.** A PodDisruptionBudget with no slack stalls the drain indefinitely, and the only escape is the force flag, which ignores the budget entirely. The platform will wait for you to be correct rather than deciding for you.

**Custom AMIs transfer the AMI lifecycle back to you.** The moment a launch template names an AMI ID, EKS stops updating the node group's image, and the convenience that justified managed node groups is substantially reduced.

**Every add-on and operator is a permanent upgrade obligation.** Each has a compatibility matrix, a changelog, and a chance of breaking an upgrade that is effectively one-way. Ten operators is ten of those, forever.

**Operators concentrate privilege and can become cluster-wide dependencies.** Broad ClusterRoles, admission webhooks on the write path, CRDs with finalizers that hang deletions, and controllers whose failures are inside someone else's reconciliation loop. The convenience is real and so is the coupling.

**ACK ties AWS resource lifecycles to a Kubernetes cluster.** Garbage collection means a namespace deletion can destroy a production resource, coverage is narrower than Terraform's, and the controller holds broad AWS permissions inside the cluster.

**EKS Auto Mode reduces control along with burden.** Less node customisation, a management fee on top of EC2, and a data plane whose behaviour you tune less directly. For teams whose constraint is people this is a good trade; for teams with specific requirements it may not be.

---

## Common Mistakes

### Beginner Mistakes

| Mistake | Why it is wrong | What to do instead |
|---|---|---|
| Running the whole cluster on Fargate | No DaemonSets, no EBS, no GPUs, and a premium on steady workloads | Fargate profiles for specific namespaces; nodes for everything else |
| Expecting a DaemonSet to run on Fargate | There is no node for one Pod per node | Sidecars, or the built-in Fluent Bit log router |
| Trying to use EKS Pod Identity on Fargate | Its agent is a DaemonSet | IRSA for Fargate workloads |
| Attaching an EBS volume to a Fargate Pod | EBS attaches to an instance; there is not one | EFS, or run the workload on a node |
| Requesting 3 vCPU on Fargate and expecting to pay for 3 | Requests are rounded up to a valid combination | Size requests just under a boundary |
| Editing a Fargate profile | Profiles are immutable | Create a new profile and delete the old one |
| `minAvailable` equal to replicas, then upgrading a node group | The drain can never make progress | `maxUnavailable: 1`, or `minAvailable` strictly less than replicas |
| Installing add-ons from URLs | Nobody knows the version; nobody updates it | EKS add-ons with versions pinned in IaC |
| Running CoreDNS with two Pods on one node | One node event becomes a cluster-wide mystery | Anti-affinity, a PDB, and replicas scaled with the cluster |
| Installing an operator without reading its manifests | You have run someone else's privileged code | Review the ClusterRole, webhooks, and CRDs first |
| Letting add-ons use the node role | Every Pod on the node inherits those permissions | An IRSA or Pod Identity role per add-on |
| A single Spot instance type in a node group | One pool reclamation removes the entire group | Four to six compatible types |
| Assuming Spot is unsuitable for production | Managed node groups handle drains automatically | An On-Demand base plus tainted Spot |

### Production Mistakes

| Mistake | Consequence | Remedy |
|---|---|---|
| An admission webhook with one replica and `failurePolicy: Fail` | Every matching write fails cluster-wide when that Pod is unavailable | Multiple replicas, a PDB, anti-affinity, and `Ignore` where not security-critical |
| Add-ons never updated across cluster upgrades | Version skew; subtle DNS and networking failures | Update add-ons between the control plane and node steps |
| Force-updating node groups routinely | The PodDisruptionBudget provides no protection at all | Fix the budgets; keep force for genuine emergencies |
| Custom AMI IDs in launch templates without a patch process | Nodes accumulate unpatched vulnerabilities silently | Use AWS AMIs, or own the pipeline that builds and rotates yours |
| Operators accumulated with no owner | The next cluster upgrade is blocked by something nobody understands | A named owner, a pinned version, and a documented failure impact per operator |
| ACK managing a production database | A namespace deletion destroys it | `deletionPolicy: retain`; keep critical infrastructure in Terraform |
| Nodes never rotated | An old kernel, an untested drain path, and a painful first upgrade | Regular node group updates, or Karpenter expiry and drift |
| Karpenter consolidation without PodDisruptionBudgets | Continuous Pod churn on critical services | PDBs and `karpenter.sh/do-not-disrupt` where appropriate |
| CoreDNS not scaled with the cluster | Distributed, unattributable latency across every service | Scale replicas with cluster size; monitor its metrics |
| IMDS hop limit left at 2 | Per-Pod identity is decorative; any Pod can take the node role | Hop limit 1 with IMDSv2 required, in the launch template |
| No Fargate log routing configured | Fargate Pods produce no retrievable logs | Configure the `aws-observability` ConfigMap at cluster build |
| Charts pulled from the internet at deploy time | Deployments fail when someone else's repository does | Mirror into ECR at pinned versions |

### Certification Traps

| Trap | The reality |
|---|---|
| "Fargate supports DaemonSets" | It does not; there is no node to run one per |
| "EKS Pod Identity works everywhere" | Not on Fargate; use IRSA there |
| "Fargate Pods can use EBS volumes" | EFS only |
| "You are billed for what a Fargate Pod requests" | You are billed for the allocated combination, rounded up, plus a reservation |
| "Fargate profiles can be edited" | They are immutable; create and delete |
| "A Fargate profile selector can match on labels alone" | A namespace is always required |
| "Managed node groups upgrade nodes in place" | They replace them: launch, cordon, drain, terminate |
| "Node group updates ignore PodDisruptionBudgets" | They respect them, unless you force the update |
| "Karpenter and the Cluster Autoscaler are the same" | One launches instances directly and consolidates; the other adjusts ASG capacity |
| "Add-ons are optional extras" | The CNI, CoreDNS, and `kube-proxy` are load-bearing data plane components |
| "`OVERWRITE` preserves your customisations" | `PRESERVE` does; `OVERWRITE` replaces them with AWS's configuration |
| "An operator is just a Deployment" | It is a Deployment plus CRDs, RBAC, and often an admission webhook |
| "CRDs are namespaced" | They are cluster-scoped; creating one is a cluster-level privilege |
| "EKS Auto Mode is the same as Fargate" | Auto Mode manages real nodes; Fargate removes them |

---

## Interview Questions

### Conceptual Questions

**1. Explain the AWS Fargate model on EKS and derive its limitations from it.**

Fargate makes the **Pod** the unit of compute: each Pod runs in its own dedicated micro-VM, provisioned on demand, sized to the Pod's requests rounded up to a valid CPU and memory combination, billed per second, and destroyed when the Pod terminates. There is no shared node — the Pod appears in `kubectl get nodes` as its own `fargate-` node object that you cannot schedule anything else onto or log into. Every limitation follows from that, which is why they are worth deriving rather than memorising. **No DaemonSets**, because a DaemonSet means one Pod per node and there is no node to be one-per — which in turn is why **EKS Pod Identity does not work**, since its credential agent is a DaemonSet, while IRSA does because it needs no agent. **No `hostNetwork` or `hostPort`**, because the host is a micro-VM shared with nothing. **No privileged containers**, because privilege escapes into a host AWS owns. **No EBS volumes**, because EBS attaches to an instance and there is no persistent instance — EFS works because it is network-attached. **No GPUs**, because capacity is AWS-managed rather than your instance selection. **Slower Pod start**, because nothing is cached: the micro-VM is provisioned and the image pulled fresh every time. And **fixed resource shapes with roughly 256 MB reserved per Pod**, because capacity is allocated in defined combinations. The consequence for design is that Fargate is excellent for bursty, small, short-lived, or untrusted workloads — where per-Pod VM isolation is a genuine boundary and there is no idle node to pay for — and poor for steady, dense, or node-dependent ones. The right answer is almost never "Fargate or nodes" for a whole cluster; it is a Fargate profile for the namespaces whose workloads fit the model.

**2. Explain what a managed node group does for you, and where the abstraction stops.**

A managed node group creates a launch template and an EC2 Auto Scaling group, launches instances from an AWS-published EKS-optimized AMI, and — importantly — creates an `EC2_LINUX` **access entry** so the node instance role is mapped and the `kubelet` may actually join. It then monitors node health and replaces unhealthy instances, and orchestrates version updates as a sequence: launch replacement nodes on the new AMI, cordon an old node, drain it **respecting PodDisruptionBudgets**, terminate it, and repeat within the bound set by `updateConfig`. It also handles Spot properly — capacity-optimized allocation, rebalance recommendations, and interruption notices that trigger a drain. That drain orchestration is the part that is genuinely hard to write correctly and the main reason to use managed groups over self-managed nodes; the access entry is the part that most often bites people who do not. Where the abstraction stops is equally important. It does **not** choose instance types from your Pods' requirements — it launches what you specified, so heterogeneous needs mean several groups or Karpenter. It does not consolidate under-utilised nodes. It scales through an Auto Scaling group, which is slower than Karpenter's direct EC2 launches. Configuration changes frequently require node replacement rather than applying in place. And the moment you supply a **custom AMI ID** in a launch template, EKS stops updating the node group's image, so you have taken back the AMI lifecycle — which is why the common advice is to use launch templates for IMDS options, volumes, and security groups while leaving the AMI to AWS.

**3. Explain the operator pattern and why it matters more than any individual operator.**

An operator is a **CustomResourceDefinition** that teaches the API server a new object kind, plus a **controller** that watches objects of that kind and runs a reconciliation loop making reality match them. The mechanism is exactly the one the built-in controllers use: from the API server's point of view, your `Database` controller is indistinguishable from the Deployment controller. Two properties make it robust. It is **level-triggered** rather than edge-triggered — every reconcile reads current desired state and current actual state and computes the difference — so a missed event, a controller restart, or a manual change all converge on the next pass, which is why reconcile functions must be idempotent and why they can be. And it inherits the whole Kubernetes apparatus for free: schema validation, RBAC, `kubectl` support, owner references for garbage collection, finalizers for cleanup ordering, and a status subresource separating what the user declared from what the controller observed. Why it matters more than any individual operator is that it is **the mechanism by which Kubernetes becomes a platform rather than a container runner**. The AWS Load Balancer Controller turning Ingresses into ALBs, Karpenter turning NodePools into EC2 instances, cert-manager turning Certificates into issued TLS, External Secrets turning ExternalSecrets into Secrets Manager reads, and ACK turning manifests into S3 buckets are all the same pattern with different object types. A student who sees that stops memorising a list of tools and starts recognising a shape — and writing a controller stops being exotic and becomes an ordinary way to encode an operational runbook so that it executes continuously and correctly rather than occasionally and from memory.

**4. Compare managed node groups, Karpenter, Fargate, and EKS Auto Mode, and describe a cluster that uses three of them.**

They differ along how much of the data plane AWS runs and how the capacity decision is made. **Managed node groups** are pre-defined Auto Scaling groups: you choose instance types and bounds, AWS handles AMIs, bootstrap, health, and drain-and-replace upgrades. Predictable and highly controllable; not intelligent about packing, and scale-out goes through an ASG. **Karpenter** is an operator that reads pending Pods' actual requirements and launches instances that fit, from a broad set of types, preferring Spot where permitted, and **consolidates** under-utilised nodes by replacing them with cheaper ones. Faster scale-out and much better packing; you run and upgrade the controller, and consolidation causes Pod churn that PodDisruptionBudgets must bound. **Fargate** removes the node entirely for the Pods a profile selects: per-Pod VM isolation, no capacity management, per-second billing, and the loss of DaemonSets, EBS, GPUs, and Pod Identity. **EKS Auto Mode** hands AWS the whole data plane — compute, networking, storage, load balancing, node OS patching — for a management fee on top of EC2, with reduced customisation. A realistic production cluster uses three: a **small managed node group** running the controllers, including Karpenter itself (which has to run somewhere) plus CoreDNS and the load balancer controller; **Karpenter** provisioning everything else just in time, with an On-Demand NodePool for services and a tainted Spot NodePool for batch; and **Fargate profiles** on the `ci` and `tenant-plugins` namespaces, where bursty lifetimes and untrusted code make per-Pod isolation worth its premium. That is not a compromise between the options — it is each one used where its trade-offs are favourable, which is the actual skill the question is testing.

**5. Explain the EKS add-on model and why it exists.**

An add-on is an EKS API object representing a cluster component — the VPC CNI, CoreDNS, `kube-proxy`, a CSI driver, the Pod Identity Agent — with a **version**, optional **`configurationValues`**, an optional **IAM role**, and a **conflict resolution mode**. It exists because these components are open-source software with their own release cadences and compatibility matrices against Kubernetes versions, and when they are installed as loose `kubectl apply -f https://...` manifests they become invisible: nobody records the version, nobody updates them, and a cluster upgrade fails in a way that looks like the upgrade's fault when it is actually two-year-old drift. Making them API objects gives them a version field somebody can own, CloudTrail visibility, expression in infrastructure as code, and an explicit update operation that slots into the upgrade order from the previous chapter — control plane, then add-ons, then nodes — which exists precisely because a node launched with an old CNI against a new API server fails confusingly. The **conflict resolution** modes matter in practice: `OVERWRITE` makes AWS's configuration authoritative and is the usual choice, `PRESERVE` keeps in-cluster changes you made deliberately, and `NONE` fails the update rather than surprising you. `configurationValues` is where settings like the CNI's `ENABLE_PREFIX_DELEGATION` or CoreDNS's replica count belong, so that configuration lives in reviewed code rather than in a `kubectl set env` somebody ran once. And add-on **IAM roles** through IRSA or Pod Identity are what stop the EBS CSI driver and the CNI from relying on the node role, which would hand their permissions to every Pod on the node.

### Scenario Questions

**1. A team proposes running their entire cluster on Fargate to eliminate node management. Evaluate the proposal.**

I would agree with the motivation and disagree with the scope, then be specific about what would break. Eliminating node management is a legitimate goal, and Fargate achieves it — but it achieves it by removing the node, so everything that depends on there being one goes too. Concretely: **their observability breaks**, because node exporters, log-forwarding agents, and security agents are DaemonSets and there is no node to run one per; Fargate offers a built-in Fluent Bit log router as a partial substitute, which must be configured, and node-level metrics simply do not exist. **Their stateful workloads break**, because EBS cannot attach — only EFS works, which changes performance characteristics and cost for anything database-like. **Any GPU work is impossible.** **Their per-Pod IAM breaks if they were using EKS Pod Identity**, since its agent is a DaemonSet; they must use IRSA. **Their scheduling assumptions break**, because `topologySpreadConstraints` and node affinity have no meaning. And **their bill will probably rise**, because per-Pod billing on rounded-up shapes with a 256 MB reservation and no bin packing costs more than well-packed nodes for steady, dense services — while their scale-out latency worsens, since every Pod provisions a micro-VM and pulls its image with no cache. What I would propose instead is Fargate **profiles for the namespaces where the model fits**: CI runners, preview environments, and anything running untrusted or customer-supplied code, where per-Pod VM isolation is a real security boundary rather than a convenience. For the rest, **managed node groups with Karpenter** gets most of the operational relief — AWS publishes the AMIs, orchestrates the upgrades, and Karpenter handles sizing and consolidation — while keeping DaemonSets, EBS, GPUs, and dense packing. If the team's constraint is genuinely people rather than control, **EKS Auto Mode** is the option to evaluate next, because it removes node management while keeping real nodes.

**2. A managed node group update has been running for four hours and one node remains cordoned. Diagnose and resolve.**

Four hours with one node cordoned means the drain is blocked, and my first command would be `kubectl get pdb -A`, looking for `ALLOWED DISRUPTIONS: 0`. A PodDisruptionBudget governs voluntary disruption, so if `minAvailable` equals the replica count — the classic `minAvailable: 3` on a three-replica Deployment — no eviction is ever permitted, every request is denied and retried, and the update runs until it times out. A single-replica Deployment with any PDB at all produces the identical deadlock. If the PDBs look healthy I would check the cordoned node's remaining Pods with `kubectl get pods --field-selector spec.nodeName=<node>` and look for the other blockers: a **bare Pod** with no owning controller, which a drain will not evict without `--force` because nothing would recreate it; a **StatefulSet Pod whose EBS volume is zone-bound**, so its replacement cannot be scheduled anywhere the volume can follow; and a Pod stuck **terminating** because its `terminationGracePeriodSeconds` is very long and the process ignores `SIGTERM`. To resolve it now: fix the PodDisruptionBudget — `maxUnavailable: 1` is the more robust expression because it survives replica-count changes without deadlocking — and the drain proceeds by itself. The **force flag** on the node group update will also finish the job, and I would use it only if the fix is not available immediately, understanding that it ignores the budget entirely and may briefly take the service to zero. Preventatively I would add `kubectl get pdb -A` to the pre-upgrade runbook, since one column identifies every workload that will block a drain, and add a policy engine rule rejecting any PDB whose `minAvailable` is not strictly less than the workload's replicas — because this mistake is mechanical and will otherwise recur with every new service.

**3. Your cluster has accumulated fourteen operators. The next Kubernetes upgrade is blocked. How do you approach this?**

The blockage is that a cluster upgrade is only as easy as its least compatible component, and fourteen operators means fourteen compatibility matrices, changelogs, and chances of breaking an upgrade that is effectively one-way. I would start by **building the inventory nobody has**: for each operator, its version, its chart source, its supported Kubernetes range, the CRDs it owns, the RBAC it holds, whether it registers an admission webhook, and — the question that matters most — who owns it and what breaks if it is unavailable. In my experience that exercise alone identifies several operators that nobody uses, that duplicate another's function, or that no one can justify, and **removing those is the fastest progress available**. Then I would sort the remainder into three groups. **Blocking**: operators that do not support the target Kubernetes version. For each, either upgrade it first (checking its own CRD migration path, which is where operator upgrades go wrong) or replace it. **Risky**: operators with admission webhooks, since a webhook incompatible with the new API server can stop every write cluster-wide; I would verify replicas, PodDisruptionBudgets, and `failurePolicy` on each before touching the control plane. **Safe**: everything else, upgraded opportunistically. I would rehearse the whole sequence on a non-production cluster one version ahead, which is the step that converts this from analysis into evidence. And the durable fix is governance rather than a one-off cleanup: a documented baseline of approved operators, each with a named owner and a pinned version in infrastructure as code from a mirrored chart, and a requirement that any addition justifies its permanent upgrade cost. Otherwise this recurs at every version boundary, which is the actual failure mode in estates like this.

**4. A team wants to use ACK so developers can create S3 buckets and RDS databases from their application manifests. Evaluate.**

The appeal is real: one declarative workflow, one GitOps controller, one review path for both an application and the AWS resources it depends on, with continuous reconciliation correcting drift and Kubernetes RBAC governing who may create what. For resources whose lifetime genuinely matches one service — a queue, a bucket, a DynamoDB table that exists because that service exists — this is a good fit, and it removes a real friction where developers otherwise wait on a separate infrastructure pipeline. My concerns are about **lifecycle coupling and blast radius**, and they scale with how important the resource is. Kubernetes garbage collection means an owner reference or a namespace deletion can delete the underlying AWS resource, so a mistaken `kubectl delete namespace` can destroy a production database — a failure mode Terraform makes you work much harder to achieve. The ACK controller holds **broad AWS permissions inside the cluster**, so anyone who can create a custom resource can create AWS resources, and the controller itself becomes a high-value target. Coverage is narrower and less mature than Terraform's or CloudFormation's, so some resources will be missing and some fields will lag. And the resource's lifecycle is now tied to a cluster's, which is uncomfortable for anything that should outlive the cluster. So my recommendation would be a split: **ACK for service-owned, recreatable resources**, with `deletionPolicy: retain` on anything holding data and a narrowly scoped controller role; **Terraform or CloudFormation for shared, long-lived infrastructure** — VPCs, shared databases, anything with independent retention or compliance requirements. I would also insist the boundary is written down rather than assumed, because the failure mode here is not technical disagreement but a database that was created through the convenient path and then deleted through it.

### Architecture Questions

**1. Design the complete data plane for a SaaS platform that runs customer-supplied plugins alongside its own services, with GPU inference, batch processing, and a 99.9 per cent availability target.**

I would give each workload class the substrate whose trade-offs suit it, because that is what a mixed data plane is for. **Customer plugins** go on a **Fargate profile** scoped to the `tenant-plugins` namespace: per-Pod micro-VM isolation means a container escape reaches an AWS-managed kernel running one Pod rather than a node shared with other tenants' code, and IRSA gives each plugin its own least-privilege role with no node role available to steal. The cost — no DaemonSets, slower start, per-Pod pricing — is acceptable for workloads that are bursty and untrusted anyway. **Platform services** go on a **managed node group** on Bottlerocket, On-Demand, across three Availability Zones, with IMDSv2 required at hop limit 1, sized to carry floor traffic alone. **Variable service load** goes to **Karpenter** over that group, with an On-Demand NodePool for user-facing services and a tainted Spot NodePool with six compatible instance families for anything interruption-tolerant. **GPU inference** goes on a dedicated **GPU node group** with a taint so nothing else lands on expensive capacity, and **batch and training** on Spot GPU with Capacity Blocks where the schedule is known. **Batch processing** goes to the tainted Spot NodePool with checkpointing and grace periods well under two minutes. The **platform baseline** is the four core add-ons with prefix delegation enabled, the EBS CSI driver, the Pod Identity Agent, CloudWatch Observability, and a deliberately small operator set — load balancer controller, ExternalDNS, cert-manager, External Secrets, Karpenter, and a GitOps controller — each pinned, mirrored, owned, and with multiple replicas where it registers a webhook. For **99.9 per cent** I would be specific about what this gets me: three-zone spread with `topologySpreadConstraints`, PodDisruptionBudgets with slack on everything, CoreDNS at three replicas with anti-affinity and its own PDB, and an On-Demand base that does not depend on Spot availability. And I would name the residual single points of failure honestly — a bad admission webhook, a failed upgrade, a cluster-level misconfiguration — because at higher targets those, not node failures, are what you would be designing against.

**2. Design an add-on and operator governance model for a platform team supporting eight clusters.**

The problem to solve is that operators accumulate faster than they are retired and each one is a permanent upgrade obligation, so the model has to make addition deliberate and inventory automatic. I would define an **approved baseline** — the four core add-ons plus EBS CSI, Pod Identity Agent, and CloudWatch Observability as add-ons; AWS Load Balancer Controller, ExternalDNS, cert-manager, External Secrets Operator, Karpenter, a metrics stack, and Argo CD as operators — declared once in a shared infrastructure-as-code module with **pinned versions**, so all eight clusters run the same components at the same versions and a version bump is one reviewed change. Every chart is **mirrored into our own ECR** rather than pulled from the internet at deploy time, both for supply chain provenance and so a deployment does not depend on someone else's repository being up. Each component carries three pieces of metadata that are non-negotiable: a **named owning team**, a **documented impact if unavailable**, and a **compatibility range** against Kubernetes versions. Adding anything outside the baseline requires a short written case covering those three, reviewed by the platform team — not to be obstructive, but because the cost being incurred is permanent and otherwise invisible. **Upgrade readiness** is a dashboard rather than a spreadsheet: each cluster's Kubernetes version, each component's version against its compatibility range, node age distribution, and PodDisruptionBudgets with zero allowed disruptions. The non-production cluster runs **one version ahead** so every component's compatibility is proven by running rather than by reading. And I would run a **quarterly retirement review** asking, for each component, whether it is still used — because the fastest way to make an upgrade easier is to have fewer things to upgrade, and nothing else in this model creates the pressure to actually remove anything.

**3. A regulated customer requires that no workload shares a kernel with another tenant's workload, that all nodes be patched within seven days of a CVE, and that every component's provenance be auditable. Design for these constraints.**

Each constraint maps to a specific mechanism, and I would take them in order. **No shared kernel between tenants** is exactly Fargate's guarantee: a Fargate profile per tenant namespace gives each Pod its own micro-VM, so the isolation boundary is a hypervisor rather than a shared kernel, and it is enforced by AWS rather than by our configuration. Where a tenant workload genuinely needs a node — a GPU, an EBS volume — the alternative is a **dedicated node group per tenant** with taints and node affinity, which is more expensive and weaker (it is our configuration doing the isolating), so I would push hard to keep tenant workloads Fargate-eligible and treat exceptions as individually approved. **Patching within seven days** means node immutability and automation: **Bottlerocket**, whose updates are atomic image swaps with rollback rather than in-place package upgrades and whose minimal image has far less to patch; managed node group version updates triggered automatically when AWS publishes a new AMI release; and **Karpenter drift** where Karpenter is in use, which replaces nodes whose configuration no longer matches their NodePool. Since Fargate Pods are provisioned fresh on AWS-patched infrastructure, tenant workloads inherit patching without any action, which is another point in that column. The measurable control is a **node age dashboard with an alarm** — a node older than seven days is an exception to investigate, not a normal state. **Auditable provenance** means: images built in our pipeline, scanned in ECR, and referenced **by digest** so what runs is what was scanned; all Helm charts and operators mirrored into our ECR at pinned versions with a recorded review; EKS add-ons rather than loose manifests so every cluster component has a version in an API and a CloudTrail record; a policy engine rejecting images from any registry but ours; and the control plane audit log plus CloudTrail retained and queryable. The constraint I would flag as satisfied least completely is the kernel-sharing one, because any tenant exception that requires a node reintroduces exactly the risk the requirement exists to remove — so I would want the exception process to be explicit and rare rather than discovered later.

### Troubleshooting Questions

**1. Pods in one namespace are stuck `Pending` with no scheduling events, while Pods elsewhere schedule normally. Fargate is in use. Diagnose.**

The absence of *scheduling* events is the clue: the default scheduler is not considering these Pods, which means something has claimed them. On a cluster using Fargate, the likeliest cause is that a mutating webhook set `schedulerName: fargate-scheduler` because a profile selector matched, and then the Fargate side could not place them. I would check `kubectl get pod -o yaml` for the `schedulerName` and the `eks.amazonaws.com/fargate-profile` label to confirm which path the Pod is on. If it is on the Fargate path, the candidates are: the **profile was deleted**, which stops its Pods and leaves them `Pending`; the profile's **subnets have no free IP addresses**, since each Fargate Pod takes a VPC address exactly as Chapter 3.1 described; the Pod's **requests exceed the largest available combination**, so no shape can be allocated; the Pod uses something Fargate cannot provide — a **host port, host network, privileged mode, or an EBS volume** — which prevents placement; or a **Fargate concurrency quota** in the Region has been reached. If the Pod is *not* on the Fargate path but still has no events, the causes are different: no nodes match its selectors or tolerations, or the scheduler itself is unhealthy. Two further wrinkles are worth knowing because they cause confusion. Profile matching happens at **admission**, so a Pod created before the profile existed will not move to Fargate and must be recreated — and equally, relabelling a namespace does not migrate running Pods. And when **multiple profiles match**, the one whose name sorts first alphanumerically wins, which can send a Pod to a profile with the wrong subnets or a pod execution role lacking ECR permissions, producing a Pod that is scheduled but never pulls its image.

**2. After installing a new operator, all deployments in the cluster begin failing. Explain and resolve.**

An operator that breaks *everything* rather than its own domain has almost certainly registered an **admission webhook** in the API server's write path. If the webhook's rules match broadly — Pods, or all resources — and its `failurePolicy` is `Fail`, then every matching write requires a successful call to the webhook's Service, and if that call cannot complete, every deployment in the cluster fails with `failed calling webhook ... context deadline exceeded`. The reasons it cannot complete are the ones from Chapter 3.1: the API server calls **inbound into your VPC** through cross-account ENIs, so a node security group that does not accept traffic from the cluster security group on the webhook's port blocks it; or the webhook's own Pod is not running, not ready, or was evicted; or its certificate is invalid; or it is simply slow enough to exceed the timeout. I would confirm with `kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations -o custom-columns` showing names and `failurePolicy`, then check the webhook Service's endpoints and its Pod's logs and events. **To resolve immediately**, if the webhook is not security-critical I would patch its `failurePolicy` to `Ignore`, or delete the webhook configuration outright — the cluster recovers within seconds because the API server stops waiting on it. Then fix the underlying cause and reinstate it. **To prevent recurrence**: read what an operator's chart creates before installing it, because an operator is privileged executable configuration; give any webhook multiple replicas across nodes with a PodDisruptionBudget and anti-affinity; scope its rules as narrowly as its function allows rather than matching everything; set `failurePolicy: Ignore` for anything that is not enforcing a security control; and install new operators in a non-production cluster first, which would have caught this before it reached production.

**3. Nodes in a Spot node group are being replaced constantly and workloads are unstable. Diagnose.**

Frequent replacement in a Spot group has a small set of causes and they are distinguishable. First, **genuine interruption pressure**: too few instance types, so the group depends on one or two capacity pools and every reclamation removes a large fraction of it. `describe-nodegroup` shows the configured types and EventBridge shows interruption and rebalance events; the fix is four to six compatible types across families and sizes, which is the single most effective change. Second, **rebalance recommendations being acted on aggressively**: these arrive before an actual interruption, and if capacity is genuinely tight the group may be replacing nodes that would not have been reclaimed. Third, **the workloads do not tolerate rescheduling**: a `terminationGracePeriodSeconds` longer than the two-minute notice means Pods are killed mid-work, long jobs without checkpointing restart from zero, and missing PodDisruptionBudgets mean drains take services below capacity — so the instability is the workload's, not the infrastructure's, and it would occur on any rotating capacity. Fourth, if Karpenter is in play, **consolidation** rather than interruption may be the cause: Karpenter deliberately replaces under-utilised nodes with cheaper ones, which looks identical from a Pod's perspective, and its metrics distinguish consolidation from interruption immediately. Fifth, **node health replacement**: instances failing health checks for an unrelated reason such as disk pressure from a small root volume. The remedies follow: diversify instance types; keep an On-Demand base sized to carry floor traffic so Spot volatility is never total; add PodDisruptionBudgets and shorten grace periods well under two minutes; checkpoint long-running jobs; taint the Spot group so only tolerating workloads land there; and use `karpenter.sh/do-not-disrupt` on anything that genuinely must not be moved. The framing I would leave the team with is that **Spot is not unstable — it is honest about instability that all capacity has**, and a workload that cannot survive a two-minute drain notice has a problem that a node failure would also expose.

### Certification-style Questions

**1. A workload requires a DaemonSet-based logging agent, GPU access, and EBS-backed persistent storage. Which compute option is appropriate?**

A. AWS Fargate with a Fargate profile
B. A managed node group with a GPU AMI
C. AWS Fargate with the EFS CSI driver
D. EKS Auto Mode with a Fargate profile

**Answer: B.** Fargate supports none of DaemonSets, GPUs, or EBS, because there is no node. Only real nodes satisfy all three requirements. C addresses only storage, and with the wrong storage type.

**2. Which statement about EKS Fargate billing is correct?**

A. You are billed for the resources your containers actually consume
B. You are billed for the requested CPU and memory exactly
C. You are billed for the allocated CPU and memory combination, which rounds requests up
D. You are billed per Pod at a flat rate

**Answer: C.** Requests are rounded up to a valid combination, and AWS additionally reserves memory for Kubernetes components, so a Pod requesting 3 vCPU and 5 GB is billed for a larger shape.

**3. A managed node group version update has been running for three hours with no progress. What is the most likely cause?**

A. The new AMI is unavailable in the Region
B. A PodDisruptionBudget prevents any eviction
C. The cluster endpoint is private
D. `maxUnavailable` is set too high

**Answer: B.** A PDB whose `minAvailable` equals the replica count denies every eviction, so the drain never completes. D would make the update faster, not slower.

**4. Which mechanism gives a Fargate Pod least-privilege access to an S3 bucket?**

A. The pod execution role
B. EKS Pod Identity
C. IAM Roles for Service Accounts (IRSA)
D. The node instance role

**Answer: C.** EKS Pod Identity requires a DaemonSet agent, which Fargate cannot run. The pod execution role is used by AWS's `kubelet` and is not available to containers. There is no node role on Fargate.

**5. An EKS add-on update should use which conflict resolution mode to keep configuration changes made directly in the cluster?**

A. `NONE`
B. `OVERWRITE`
C. `PRESERVE`
D. `MERGE`

**Answer: C.** `PRESERVE` keeps in-cluster changes; `OVERWRITE` replaces them with AWS's configuration; `NONE` fails the update on conflict. `MERGE` is not a valid mode.

**6. Which statement about the operator pattern is correct?**

A. Operators require changes to the Kubernetes API server source code
B. An operator is a CustomResourceDefinition plus a controller that reconciles those objects
C. CustomResourceDefinitions are namespaced resources
D. Operators are edge-triggered and fail if an event is missed

**Answer: B.** CRDs extend the API without modifying the API server. CRDs are cluster-scoped, and controllers are level-triggered, which is what makes a missed event survivable.

**7. A company must isolate untrusted customer code so that a container escape cannot reach other tenants' workloads. Which approach best satisfies this on EKS?**

A. A NetworkPolicy restricting the untrusted namespace
B. Pod Security Admission at `restricted`
C. A Fargate profile for the untrusted namespace
D. A dedicated managed node group with taints

**Answer: C.** Fargate runs each Pod in its own micro-VM, so an escape reaches a kernel running only that Pod. A restricts network traffic, not kernel access. B reduces but does not eliminate escape risk on a shared kernel. D isolates from other node groups but tenants still share a kernel with one another.

---

## Hands-on Lab

### Objective

Build a mixed data plane in one cluster and observe each substrate's behaviour directly: run Pods on a managed node group and on Fargate side by side, prove what Fargate cannot do, perform a node group update and deliberately deadlock it with a PodDisruptionBudget, manage add-ons through the EKS API, and install an operator and watch its reconciliation loop.

!!! info "Environment"

    This lab targets the **AWS Academy Learner Lab**, using `LabRole` where a role is required. Region `us-east-1`, placeholder account `111122223333`. It builds on the cluster from the 3.1 and 3.2 labs. `eksctl`, `kubectl`, and `helm` must be installed.

    !!! warning "Learner Lab constraints"

        Learner Lab accounts restrict IAM role creation, which affects the Fargate pod execution role and operator IRSA roles. Where `LabRole` must be reused, note which steps you could not complete and what you would have done in a full account.

### Architecture

```mermaid
flowchart TD
    CP["EKS control plane"] --> MNG["Managed node group: ng-general, On-Demand"]
    CP --> SPOT["Managed node group: ng-spot, tainted"]
    CP --> FP["Fargate profile: serverless namespace"]
    CP --> ADD["EKS add-ons: VPC CNI, CoreDNS, kube-proxy, Pod Identity Agent"]
    MNG --> APP["Pods: node-based workloads, DaemonSets, EBS volumes"]
    FP --> SPOD["Pods: one micro-VM each, appearing as fargate- nodes"]
    OP["Operator installed in Step 8"] --> CRD["CustomResourceDefinition and reconciliation loop"]
    PDB["PodDisruptionBudget — deadlocks the update in Step 6"] -.-> APP
```

### AWS Services Used

| Service | Role in the lab |
|---|---|
| **Amazon EKS** | The cluster, node groups, Fargate profiles, and add-ons |
| **AWS Fargate** | Serverless Pod capacity |
| **Amazon EC2** | The nodes you will update and drain |
| **AWS IAM** | The pod execution role and add-on roles |
| **Amazon EBS** | The volume that proves Fargate cannot attach one |
| **Amazon CloudWatch** | Add-on health and node metrics |

### Implementation Steps

**Step 1 — Variables.**

```bash
export AWS_REGION=us-east-1
export ACCOUNT_ID=111122223333
export CLUSTER=dso303-ch33
aws eks update-kubeconfig --name "$CLUSTER" --region "$AWS_REGION"
kubectl config current-context
```

**Step 2 — Inspect the existing data plane.**

```bash
aws eks list-nodegroups --cluster-name "$CLUSTER" --region "$AWS_REGION"
aws eks describe-nodegroup --cluster-name "$CLUSTER" --nodegroup-name ng-general \
  --region "$AWS_REGION" \
  --query 'nodegroup.{ami:amiType,version:version,release:releaseVersion,capacity:capacityType,
            types:instanceTypes,scaling:scalingConfig,update:updateConfig,health:health}'

kubectl get nodes -L eks.amazonaws.com/compute-type,node.kubernetes.io/instance-type
```

**Step 3 — Create a Fargate profile.**

```bash
kubectl create namespace serverless

eksctl create fargateprofile \
  --cluster "$CLUSTER" --region "$AWS_REGION" \
  --name fp-serverless \
  --namespace serverless

aws eks describe-fargate-profile --cluster-name "$CLUSTER" \
  --fargate-profile-name fp-serverless --region "$AWS_REGION" \
  --query 'fargateProfile.{selectors:selectors,subnets:subnets,role:podExecutionRoleArn}'
```

**Step 4 — Run the same workload on both substrates and compare.**

```bash
# On a node.
kubectl create deployment web-node --image=public.ecr.aws/nginx/nginx:stable -n default
# On Fargate.
kubectl create deployment web-fargate --image=public.ecr.aws/nginx/nginx:stable -n serverless

time kubectl rollout status deploy/web-node -n default
time kubectl rollout status deploy/web-fargate -n serverless   # noticeably slower: no cache

# Each Fargate Pod is its own Node object.
kubectl get nodes -l eks.amazonaws.com/compute-type=fargate
kubectl get pods -n serverless -o wide
kubectl describe node $(kubectl get nodes -l eks.amazonaws.com/compute-type=fargate \
  -o jsonpath='{.items[0].metadata.name}') | head -25
```

Record the start-up times and the allocatable capacity reported by the Fargate node.

**Step 5 — Prove Fargate's limitations rather than reading about them.**

```bash
# A DaemonSet: it will schedule on real nodes and NOT on Fargate.
kubectl apply -f - <<'YAML'
apiVersion: apps/v1
kind: DaemonSet
metadata: { name: probe-agent, namespace: serverless }
spec:
  selector: { matchLabels: { app: probe-agent } }
  template:
    metadata: { labels: { app: probe-agent } }
    spec:
      containers:
        - name: agent
          image: public.ecr.aws/docker/library/busybox:latest
          command: ["sh","-c","sleep 3600"]
YAML
sleep 30
kubectl get daemonset -n serverless      # DESIRED 0: there are no nodes to run one per

# An EBS-backed PVC on Fargate: it will never bind to a running Pod.
kubectl apply -f - <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: needs-ebs, namespace: serverless }
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: gp2
  resources: { requests: { storage: 1Gi } }
YAML
kubectl run ebs-user -n serverless --image=public.ecr.aws/docker/library/busybox:latest \
  --overrides='{"spec":{"volumes":[{"name":"v","persistentVolumeClaim":{"claimName":"needs-ebs"}}],
  "containers":[{"name":"ebs-user","image":"public.ecr.aws/docker/library/busybox:latest",
  "command":["sh","-c","sleep 3600"],"volumeMounts":[{"name":"v","mountPath":"/data"}]}]}}' \
  --command -- sh -c "sleep 3600"
sleep 45
kubectl describe pod ebs-user -n serverless | tail -15   # the Pod cannot get an EBS volume
```

**Step 6 — Deadlock a node group update, then fix it.**

```bash
kubectl create deployment critical --image=public.ecr.aws/nginx/nginx:stable --replicas=3
kubectl create poddisruptionbudget critical-bad --selector=app=critical --min-available=3
kubectl get pdb critical-bad     # ALLOWED DISRUPTIONS: 0  <- this will stall the update

aws eks update-nodegroup-version --cluster-name "$CLUSTER" --nodegroup-name ng-general \
  --region "$AWS_REGION" --force=false 2>/dev/null || echo "already current"

# Watch it fail to progress by draining manually — the same mechanism.
NODE=$(kubectl get pods -l app=critical -o jsonpath='{.items[0].spec.nodeName}')
timeout 90 kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data \
  || echo "BLOCKED — this is what stalls a managed node group update for hours"
kubectl uncordon "$NODE"

kubectl delete pdb critical-bad
kubectl create poddisruptionbudget critical --selector=app=critical --max-unavailable=1
kubectl get pdb critical         # ALLOWED DISRUPTIONS: 1
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=180s
kubectl uncordon "$NODE"
```

**Step 7 — Manage add-ons through the EKS API.**

```bash
aws eks list-addons --cluster-name "$CLUSTER" --region "$AWS_REGION"

aws eks describe-addon --cluster-name "$CLUSTER" --addon-name vpc-cni \
  --region "$AWS_REGION" \
  --query 'addon.{version:addonVersion,status:status,role:serviceAccountRoleArn,
            config:configurationValues}'

# Which versions are compatible with this cluster's Kubernetes version?
K8S=$(aws eks describe-cluster --name "$CLUSTER" --region "$AWS_REGION" \
  --query 'cluster.version' --output text)
aws eks describe-addon-versions --addon-name vpc-cni --kubernetes-version "$K8S" \
  --region "$AWS_REGION" \
  --query 'addons[0].addonVersions[0:5].[addonVersion,compatibilities[0].defaultVersion]' \
  --output table

# Enable prefix delegation THROUGH THE API rather than with kubectl set env.
aws eks update-addon --cluster-name "$CLUSTER" --addon-name vpc-cni \
  --region "$AWS_REGION" \
  --resolve-conflicts OVERWRITE \
  --configuration-values '{"env":{"ENABLE_PREFIX_DELEGATION":"true","WARM_PREFIX_TARGET":"1"}}'

sleep 60
kubectl get ds aws-node -n kube-system -o jsonpath='{.spec.template.spec.containers[0].env}' \
  | tr ',' '\n' | grep -i prefix
```

**Step 8 — Install an operator and watch it reconcile.**

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update

# READ WHAT IT CREATES BEFORE INSTALLING. This is the habit, not the ceremony.
helm template cert-manager jetstack/cert-manager --version v1.16.0 \
  --set crds.enabled=true \
  | grep -E "^kind:|^  name:" | grep -A1 -E "ClusterRole|ValidatingWebhook|MutatingWebhook|CustomResourceDefinition" \
  | head -40

helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.16.0 --set crds.enabled=true --wait

# The API server now serves kinds that did not exist before.
kubectl api-resources --api-group=cert-manager.io
kubectl get crd | grep cert-manager

# Create a custom resource and watch the controller act on it.
kubectl apply -f - <<'YAML'
apiVersion: cert-manager.io/v1
kind: Issuer
metadata: { name: selfsigned, namespace: default }
spec: { selfSigned: {} }
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata: { name: demo-cert, namespace: default }
spec:
  secretName: demo-cert-tls
  issuerRef: { name: selfsigned, kind: Issuer }
  commonName: demo.dso303.local
  dnsNames: ["demo.dso303.local"]
YAML

sleep 20
kubectl get certificate demo-cert -o wide          # the controller writes STATUS
kubectl get secret demo-cert-tls                   # it created this; you did not
kubectl logs -n cert-manager -l app.kubernetes.io/component=controller --tail=20

# Delete the Secret and watch the reconciliation loop recreate it. This is the whole pattern.
kubectl delete secret demo-cert-tls
sleep 30
kubectl get secret demo-cert-tls                   # back again
```

**Step 9 — Observe the webhook risk.**

```bash
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations \
  -o custom-columns='NAME:.metadata.name,POLICY:.webhooks[*].failurePolicy'
kubectl get deploy -n cert-manager -o custom-columns='NAME:.metadata.name,REPLICAS:.spec.replicas'
kubectl get pdb -n cert-manager
# Record: is the webhook backed by a single replica with failurePolicy Fail and no PDB?
```

**Step 10 — Clean up.**

```bash
kubectl delete certificate demo-cert -n default; kubectl delete issuer selfsigned -n default
helm uninstall cert-manager -n cert-manager
kubectl delete crd -l app.kubernetes.io/name=cert-manager
kubectl delete namespace cert-manager serverless
eksctl delete fargateprofile --cluster "$CLUSTER" --name fp-serverless --region "$AWS_REGION" --wait
kubectl delete deploy web-node critical -n default
kubectl delete pdb critical -n default
```

### Expected Output

| Observation | Expected result |
|---|---|
| `kubectl get nodes` with the compute-type label | EC2 nodes and one `fargate-` node per Fargate Pod |
| Rollout time on a node versus Fargate | Fargate noticeably slower: micro-VM provisioning plus an uncached image pull |
| DaemonSet in a Fargate namespace | `DESIRED 0` — there is no node to run one per |
| EBS-backed PVC on Fargate | The Pod never gets a volume; events name the failure |
| `kubectl get pdb` with `minAvailable: 3` on 3 replicas | `ALLOWED DISRUPTIONS: 0` |
| Drain with that PDB | Blocked; the same condition that stalls a node group update for hours |
| The same drain with `maxUnavailable: 1` | Completes, evicting one Pod at a time |
| `describe-addon-versions` | The versions compatible with this cluster's Kubernetes version |
| `update-addon` with `configurationValues` | Prefix delegation reflected in the `aws-node` DaemonSet's environment |
| `helm template` on cert-manager | ClusterRoles, webhooks, and CRDs — what you are actually installing |
| `kubectl api-resources` after install | New kinds the API server did not previously serve |
| Deleting the controller-created Secret | It is recreated within seconds by the reconciliation loop |
| Webhook configuration inspection | Whether a single-replica webhook with `failurePolicy: Fail` is present |

!!! tip "What the lab is really teaching"

    Four things. First, that **Fargate's limitations are structural**: the DaemonSet showing `DESIRED 0` is not a bug or a missing feature, it is what "no node" means. Second, that **a PodDisruptionBudget with no slack is the single most common cause of a stalled upgrade**, and one column diagnoses it. Third, that **add-on configuration belongs in the EKS API**, not in a `kubectl set env` somebody ran once — Step 7 is the difference between a setting that is in your infrastructure as code and one that disappears with the next add-on update. Fourth, and most importantly, that **an operator is the whole Kubernetes pattern in miniature**: you declared a `Certificate`, a controller created a Secret you never asked for directly, and when you deleted that Secret it came back — which is exactly what the Deployment controller does for Pods, and exactly what Karpenter does for nodes.

---

## Code Examples

### `eksctl`: a mixed data plane in one configuration file

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: dso303-mixed
  region: us-east-1
  version: "1.33"

iam:
  withOIDC: true            # required for IRSA, including Fargate workloads

managedNodeGroups:
  # A small group for controllers. Karpenter itself has to run somewhere.
  - name: ng-system
    amiFamily: Bottlerocket
    instanceTypes: ["m6i.large"]
    minSize: 2
    desiredCapacity: 2
    maxSize: 4
    privateNetworking: true
    labels: { role: system }
    taints:
      - key: CriticalAddonsOnly
        value: "true"
        effect: NoSchedule       # only controllers tolerate this
    instanceMetadataOptions:
      httpTokens: required
      httpPutResponseHopLimit: 1 # containers cannot reach IMDS: 3.1's control
    updateConfig:
      maxUnavailable: 1

  # General On-Demand capacity, sized to carry floor traffic alone.
  - name: ng-general
    amiFamily: Bottlerocket
    instanceTypes: ["m6i.large", "m6a.large", "m5.large"]
    minSize: 3
    desiredCapacity: 6
    maxSize: 20
    privateNetworking: true
    volumeSize: 60
    volumeEncrypted: true
    instanceMetadataOptions:
      httpTokens: required
      httpPutResponseHopLimit: 1
    updateConfig:
      maxUnavailablePercentage: 25
    labels: { workload: general }

  # Spot above the base, TAINTED so only tolerating workloads land here.
  - name: ng-spot-batch
    amiFamily: Bottlerocket
    # Diversity is the risk control: one pool's reclamation must not empty the group.
    instanceTypes: ["m6i.xlarge","m6a.xlarge","m5.xlarge","m5a.xlarge","m6i.2xlarge","m5.2xlarge"]
    spot: true
    minSize: 0                   # scales to zero between runs
    desiredCapacity: 0
    maxSize: 40
    privateNetworking: true
    labels: { workload: batch, capacity: spot }
    taints:
      - key: workload
        value: batch
        effect: NoSchedule

fargateProfiles:
  # Untrusted code: per-Pod micro-VM isolation is the reason, not convenience.
  - name: fp-tenant-plugins
    selectors:
      - namespace: tenant-plugins
    subnets: [subnet-0a1, subnet-0b1, subnet-0c1]   # private only

  # Bursty, short-lived: no idle node to pay for.
  - name: fp-ci
    selectors:
      - namespace: ci
        labels: { runner: "true" }
      - namespace: preview-*      # wildcards are supported

addons:
  - name: vpc-cni
    version: latest
    configurationValues: |
      {
        "env": {
          "ENABLE_PREFIX_DELEGATION": "true",
          "WARM_PREFIX_TARGET": "1",
          "ENABLE_NETWORK_POLICY": "true"
        }
      }
  - name: coredns
    version: latest
    configurationValues: |
      {
        "replicaCount": 3,
        "tolerations": [
          { "key": "CriticalAddonsOnly", "operator": "Exists" }
        ]
      }
  - name: kube-proxy
    version: latest
  - name: aws-ebs-csi-driver
    version: latest
  - name: eks-pod-identity-agent
    version: latest
  - name: amazon-cloudwatch-observability
    version: latest
```

### Terraform: node group and add-on with pinned versions

```hcl
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "ng-general"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  # Pinned: an upgrade is a deliberate, reviewed change.
  version         = "1.33"
  release_version = var.eks_ami_release_version

  ami_type       = "BOTTLEROCKET_x86_64"
  capacity_type  = "ON_DEMAND"
  instance_types = ["m6i.large", "m6a.large", "m5.large"]

  scaling_config {
    min_size     = 3          # at least one per AZ
    desired_size = 6
    max_size     = 20
  }

  update_config {
    max_unavailable_percentage = 25   # speed vs capacity during replacement
  }

  launch_template {
    id      = aws_launch_template.node.id
    version = aws_launch_template.node.latest_version
  }

  labels = { workload = "general" }

  lifecycle {
    # desired_size is managed by the autoscaler, not by Terraform.
    ignore_changes = [scaling_config[0].desired_size]
  }
}

resource "aws_launch_template" "node" {
  name_prefix = "dso303-node-"

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"   # IMDSv2 only
    http_put_response_hop_limit = 1            # containers cannot reach IMDS
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 60
      volume_type = "gp3"
      encrypted   = true
    }
  }
  # No image_id: EKS supplies the AMI, and keeps supplying newer ones.
  # Setting image_id here would transfer AMI lifecycle back to us.
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "vpc-cni"
  addon_version = var.vpc_cni_version          # pinned, bumped with the cluster upgrade

  # OVERWRITE: AWS configuration is authoritative. PRESERVE only for deliberate customisation.
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  # Its own IAM role: never the node role.
  service_account_role_arn = aws_iam_role.vpc_cni.arn

  configuration_values = jsonencode({
    env = {
      ENABLE_PREFIX_DELEGATION = "true"   # 29 pods -> 110 on an m5.large, free
      WARM_PREFIX_TARGET       = "1"
      ENABLE_NETWORK_POLICY    = "true"
    }
  })
}
```

### Kubernetes YAML: scheduling across a mixed data plane

```yaml
# Batch job: tolerates the Spot taint and expects to be interrupted.
apiVersion: batch/v1
kind: Job
metadata: { name: nightly-report, namespace: batch }
spec:
  backoffLimit: 6                     # Spot interruptions are retries, not failures
  template:
    spec:
      restartPolicy: OnFailure
      # Only workloads that tolerate this land on Spot capacity.
      tolerations:
        - key: workload
          value: batch
          operator: Equal
          effect: NoSchedule
      nodeSelector:
        capacity: spot
      # Well under the two-minute Spot interruption notice.
      terminationGracePeriodSeconds: 60
      containers:
        - name: report
          image: 111122223333.dkr.ecr.us-east-1.amazonaws.com/report@sha256:abc...
          resources:
            requests: { cpu: "2", memory: "4Gi" }
            limits:   { memory: "4Gi" }
---
# Fargate workload: no DaemonSet sidecar, IRSA not Pod Identity, EFS not EBS.
apiVersion: v1
kind: ServiceAccount
metadata:
  name: plugin-runner
  namespace: tenant-plugins
  annotations:
    # IRSA: EKS Pod Identity does NOT work on Fargate (its agent is a DaemonSet).
    eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/dso303-plugin-runner
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: plugin-runner, namespace: tenant-plugins }
spec:
  replicas: 3
  selector: { matchLabels: { app: plugin-runner } }
  template:
    metadata: { labels: { app: plugin-runner } }
    spec:
      serviceAccountName: plugin-runner
      # No tolerations or nodeSelector: the Fargate profile's namespace selector
      # claims this Pod at admission time.
      containers:
        - name: runner
          image: 111122223333.dkr.ecr.us-east-1.amazonaws.com/runner@sha256:def...
          resources:
            # Fargate rounds UP to a valid combination and reserves ~256Mi.
            # 0.5 vCPU / 1Gi requested lands on the 0.5 vCPU / 2Gi shape.
            requests: { cpu: "500m", memory: "1Gi" }
            limits:   { memory: "1Gi" }
          volumeMounts:
            - { name: shared, mountPath: /data }
      volumes:
        - name: shared
          persistentVolumeClaim:
            claimName: plugins-efs      # EFS: EBS cannot attach on Fargate
---
# Critical service: a PDB with slack, so drains and upgrades can make progress.
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: { name: plugin-runner, namespace: tenant-plugins }
spec:
  maxUnavailable: 1          # NOT minAvailable == replicas, which deadlocks every drain
  selector:
    matchLabels: { app: plugin-runner }
```

### Karpenter NodePool: provisioning as reconciliation

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata: { name: general }
spec:
  template:
    spec:
      requirements:
        # Constraints, not a fixed instance list: Karpenter picks what FITS the Pods.
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64", "arm64"]        # Graviton where the image supports it
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot", "on-demand"]     # Spot preferred, On-Demand as fallback
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]                     # exclude old, less efficient generations
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      # Nodes are cattle: replaced regularly so the kernel is never old.
      expireAfter: 720h
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "10%"                        # bound the churn consolidation causes
  limits:
    cpu: "1000"                             # a bug must not become a bill
---
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata: { name: default }
spec:
  amiFamily: Bottlerocket
  role: dso303-karpenter-node
  subnetSelectorTerms:
    - tags: { "karpenter.sh/discovery": "dso303-mixed" }   # discovery by tag
  securityGroupSelectorTerms:
    - tags: { "karpenter.sh/discovery": "dso303-mixed" }
  metadataOptions:
    httpTokens: required
    httpPutResponseHopLimit: 1
```

### A minimal operator: the pattern in fifty lines

```python
"""A toy operator. It teaches the loop, not production practice.

Watches Backup custom resources and ensures a CronJob exists for each.
Everything real does exactly this, with more error handling.
"""
import kopf
import kubernetes.client as k8s


@kopf.on.create("dso303.example.com", "v1", "backups")
@kopf.on.update("dso303.example.com", "v1", "backups")
def reconcile(spec, name, namespace, logger, **_):
    """Idempotent: this runs many times for the same state and must be safe every time."""
    schedule = spec.get("schedule", "0 2 * * *")
    target = spec["target"]

    body = k8s.V1CronJob(
        metadata=k8s.V1ObjectMeta(
            name=f"backup-{name}",
            namespace=namespace,
            # Owner reference: deleting the Backup garbage-collects the CronJob.
            # kopf adds this automatically via adopt(); shown explicitly for clarity.
        ),
        spec=k8s.V1CronJobSpec(
            schedule=schedule,
            job_template=k8s.V1JobTemplateSpec(
                spec=k8s.V1JobSpec(
                    template=k8s.V1PodTemplateSpec(
                        spec=k8s.V1PodSpec(
                            restart_policy="OnFailure",
                            service_account_name="backup-runner",  # its own IAM role
                            containers=[
                                k8s.V1Container(
                                    name="backup",
                                    image="111122223333.dkr.ecr.us-east-1.amazonaws.com/backup@sha256:abc",
                                    args=["--target", target],
                                )
                            ],
                        )
                    )
                )
            ),
        ),
    )
    kopf.adopt(body)          # sets ownerReferences for garbage collection

    batch = k8s.BatchV1Api()
    try:
        batch.create_namespaced_cron_job(namespace, body)
        logger.info("created CronJob for %s", name)
    except k8s.rest.ApiException as exc:
        if exc.status != 409:                    # 409 = already exists
            raise
        batch.replace_namespaced_cron_job(f"backup-{name}", namespace, body)
        logger.info("reconciled CronJob for %s", name)

    # The controller writes status; the user writes spec. Never the other way round.
    return {"cronJob": f"backup-{name}", "schedule": schedule}
```

### Shell: the data plane diagnostic sequence

```bash
CLUSTER=dso303-mixed; REGION=us-east-1

# 1. What substrates is this cluster actually running?
kubectl get nodes -L eks.amazonaws.com/compute-type,karpenter.sh/capacity-type,node.kubernetes.io/instance-type

# 2. Node group configuration and health.
for NG in $(aws eks list-nodegroups --cluster-name "$CLUSTER" --region "$REGION" \
              --query 'nodegroups[]' --output text); do
  aws eks describe-nodegroup --cluster-name "$CLUSTER" --nodegroup-name "$NG" --region "$REGION" \
    --query "nodegroup.{name:nodegroupName,version:version,release:releaseVersion,\
              capacity:capacityType,status:status,health:health.issues}"
done

# 3. THE pre-upgrade check. ALLOWED DISRUPTIONS 0 stalls every drain.
kubectl get pdb -A

# 4. Add-on versions against what this Kubernetes version supports.
K8S=$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" --query 'cluster.version' --output text)
for A in $(aws eks list-addons --cluster-name "$CLUSTER" --region "$REGION" --query 'addons[]' --output text); do
  CUR=$(aws eks describe-addon --cluster-name "$CLUSTER" --addon-name "$A" --region "$REGION" \
        --query 'addon.addonVersion' --output text)
  LATEST=$(aws eks describe-addon-versions --addon-name "$A" --kubernetes-version "$K8S" \
        --region "$REGION" --query 'addons[0].addonVersions[0].addonVersion' --output text)
  echo "$A: running $CUR, latest for k8s $K8S is $LATEST"
done

# 5. Which Pods are on Fargate, and what are they costing?
kubectl get pods -A -o json | jq -r '.items[]
  | select(.spec.nodeName | startswith("fargate-"))
  | "\(.metadata.namespace)/\(.metadata.name) cpu=\(.spec.containers[0].resources.requests.cpu) mem=\(.spec.containers[0].resources.requests.memory)"'

# 6. Which webhooks could stop the whole cluster?
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations \
  -o custom-columns='NAME:.metadata.name,POLICY:.webhooks[*].failurePolicy'

# 7. Is an operator actually reconciling, or silently failing?
kubectl logs -n cert-manager -l app.kubernetes.io/component=controller --tail=30 | grep -i error

# 8. Node age: are nodes being rotated, or quietly accumulating?
kubectl get nodes -o json | jq -r '.items[]
  | "\(.metadata.name) age=\(.metadata.creationTimestamp)"' | sort -k2
```

---

## AWS Certification Tips

### Exam tips

Locate the constraint on the substrate / capacity / component axis, then eliminate.

- "DaemonSet, GPU, EBS, privileged, or host networking" → **not Fargate**; a node is required.
- "Untrusted or multi-tenant code needing kernel isolation" → **Fargate**.
- "Bursty, short-lived, or very small workloads" → **Fargate**.
- "Steady and dense" → **nodes**; Fargate's per-Pod premium compounds.
- "Least privilege for a Fargate Pod" → **IRSA**, never Pod Identity.
- "Node group update stuck for hours" → a **PodDisruptionBudget** with no slack.
- "Finish a blocked update now" → the **force flag**, which ignores PDBs.
- "Fast scale-out with right-sized, diverse instances" → **Karpenter**; adjusting an ASG → **Cluster Autoscaler**.
- "Nodes must be replaced regularly and automatically" → **Karpenter expiry and drift**, or node group updates.
- "Interruption-tolerant, cost-dominated" → **Spot with several instance types, tainted**.
- "Minimal host attack surface" → **Bottlerocket**.
- "Containers must not reach the instance metadata service" → **IMDSv2 with hop limit 1**.
- "Keep in-cluster add-on customisation during an update" → **`PRESERVE`**; AWS config wins → **`OVERWRITE`**.
- "Extend the Kubernetes API with a new resource type" → a **CustomResourceDefinition** plus a controller.
- "Create AWS resources from Kubernetes manifests" → **ACK**, with the lifecycle caveat.
- "All writes fail after installing something" → an **admission webhook** with `failurePolicy: Fail`.

### Frequently confused pairs

| Pair | The distinguishing fact |
|---|---|
| **Fargate vs managed node group** | No node at all versus AWS-managed real nodes |
| **Fargate vs EKS Auto Mode** | Removes the node versus manages the node for you |
| **Pod execution role vs node instance role** | Used by AWS's `kubelet` on Fargate, unavailable to containers, versus a node role every Pod can reach |
| **IRSA vs EKS Pod Identity** | Works on Fargate versus does not (its agent is a DaemonSet) |
| **Managed vs self-managed nodes** | AWS AMIs, automatic access entry, orchestrated drains versus all of it yours |
| **Karpenter vs Cluster Autoscaler** | Launches right-sized instances and consolidates versus adjusts ASG capacity |
| **`updateConfig` vs the force flag** | Bounds concurrent replacement versus ignores PodDisruptionBudgets |
| **Rebalance recommendation vs interruption notice** | An early warning versus the two-minute final notice |
| **`OVERWRITE` vs `PRESERVE`** | AWS's configuration wins versus yours does |
| **AWS add-on vs community add-on** | Built and supported by AWS versus scanned by AWS, supported by the community |
| **CRD vs custom resource** | The kind definition versus an instance of it |
| **Controller vs operator** | A reconciliation loop versus one packaged with CRDs for a specific domain |
| **Level-triggered vs edge-triggered** | Acts on current state (robust) versus acts on events (fragile) |
| **Finalizer vs owner reference** | Blocks deletion until cleanup versus enables garbage collection of children |
| **ACK vs Terraform** | AWS resources as cluster objects versus independent infrastructure lifecycle |
| **Taint vs label** | Repels Pods that do not tolerate it versus attracts Pods that select it |

### Memory aids

- **"No node, no DaemonSet."** And no EBS, no GPU, no Pod Identity, no host network.
- **"Fargate bills the shape, not the request."**
- **"Profiles are immutable; design them around namespaces."**
- **"Managed groups replace nodes; they do not patch them."**
- **"`ALLOWED DISRUPTIONS: 0` stalls every upgrade."**
- **"Force finishes; it does not fix."**
- **"On-Demand base, Spot on top, tainted."**
- **"Karpenter launches; the autoscaler adjusts."**
- **"`OVERWRITE` = AWS wins; `PRESERVE` = you win."**
- **"A controller watches a kind and makes the world match."**
- **"Every operator is an upgrade you will owe forever."**

!!! danger "Common certification traps"

    - Expecting DaemonSets, EBS, GPUs, host networking, or EKS Pod Identity to work on Fargate.
    - Believing Fargate bills what a Pod requests rather than what is allocated.
    - Believing a Fargate profile can be edited, or that a selector can omit the namespace.
    - Believing managed node groups patch nodes in place rather than replacing them.
    - Believing node group updates ignore PodDisruptionBudgets.
    - Confusing Karpenter with the Cluster Autoscaler.
    - Confusing EKS Auto Mode with Fargate.
    - Believing `OVERWRITE` preserves your customisations.
    - Treating the CNI, CoreDNS, and `kube-proxy` as optional extras.
    - Believing CRDs are namespaced, or that creating one is an ordinary privilege.
    - Forgetting that an admission webhook with `failurePolicy: Fail` is a cluster-wide dependency.
    - Assuming a controller fails when it misses an event — reconciliation is level-triggered.

---

## Summary

First, **the data plane is a per-workload decision, not a cluster-wide commitment**. Fargate, managed node groups, Spot groups, Karpenter, and Auto Mode coexist in one cluster, and the mature answer to "which should we use" is almost always "these three, for these workloads". A student who leaves believing there is one correct substrate has learned the wrong lesson; the skill is naming which workload belongs where and why.

Second, **every Fargate limitation follows from one design decision**, which is why they should be derived rather than memorised. Making the Pod the unit of compute means there is no node — so no DaemonSets, no host networking, no privileged containers, no GPUs, no EBS, no EKS Pod Identity (its agent is a DaemonSet), no topology spread, no image cache, and fixed resource shapes with a per-Pod reservation. What you get in exchange is real: per-Pod kernel isolation that is a genuine security boundary for untrusted code, no capacity to plan, no AMI to patch, and no node role for a container to steal. That trade is excellent for bursty, small, short-lived, and untrusted workloads and poor for steady, dense, node-dependent ones.

Third, **managed node groups remove the plumbing while leaving the decisions**. AWS publishes and versions the AMI, bootstraps the node, creates the access entry that lets it join, replaces unhealthy instances, handles Spot rebalance and interruption, and orchestrates the cordon-drain-replace upgrade — which is the part that is genuinely difficult to write and easy to get subtly wrong. You keep instance types, sizes, labels, taints, capacity strategy, and the upgrade schedule. The abstraction stops at intelligence: the group launches what you specified rather than what your Pods need, which is precisely the gap Karpenter fills.

Fourth, **your own configuration is what blocks upgrades, and one column tells you in advance**. A PodDisruptionBudget whose `minAvailable` equals the replica count denies every eviction, so the drain never completes and the node group update runs until it times out. `kubectl get pdb -A` showing `ALLOWED DISRUPTIONS: 0` is the entire diagnosis, and running it before every upgrade converts the most common four-hour incident into a two-minute fix. The force flag exists to escape the deadlock and does exactly what it says — it finishes the upgrade by ignoring the budget, which is not the same as making the configuration correct.

Fifth, **add-ons exist so that cluster components have owners**. The CNI, CoreDNS, `kube-proxy`, and the CSI drivers are load-bearing data plane software with their own release cadences and compatibility matrices, and installed as loose manifests from a URL they become invisible — nobody knows the version, nobody updates it, and a cluster upgrade fails in a way that looks like the upgrade's fault. As EKS add-ons they have a version field, `configurationValues` in your infrastructure as code, their own IAM roles rather than the node's, a CloudTrail record, and a place in the upgrade order between the control plane and the nodes.

Sixth, **the operator pattern is the most important idea in this chapter and possibly in Kubernetes**. A CustomResourceDefinition teaches the API server a new kind; a controller watches those objects and reconciles the world toward them, level-triggered so that missed events and restarts converge anyway. The AWS Load Balancer Controller, Karpenter, cert-manager, External Secrets, Argo CD, and ACK are all this same pattern with different object types, which is why understanding it once explains the ecosystem and makes writing your own an ordinary engineering task rather than an exotic one — the way to turn an operational runbook into something that executes continuously and correctly rather than occasionally and from memory.

Seventh, and most easily ignored, **every operator and add-on is a permanent upgrade obligation and a concentration of privilege**. Each has a compatibility matrix to check against every Kubernetes version, a changelog to read, and a chance of blocking an upgrade that is effectively one-way. Each typically holds a broad ClusterRole, and some register admission webhooks that sit in the write path — where a single-replica webhook with `failurePolicy: Fail` becomes a cluster-wide outage the moment its Pod is evicted. The discipline that makes a platform survivable is unglamorous: a small, deliberate baseline; every component pinned, mirrored, and owned by a named team; webhooks with replicas and disruption budgets; and a quarterly willingness to remove the ones nobody can justify.

---


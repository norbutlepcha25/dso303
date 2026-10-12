<!-- teachprep:refined 2026-10-11 -->
# 3.3 Amazon EKS Advanced Concepts

## Definition

[3.1](topic1.md) showed that AWS runs the EKS control plane while **you choose the data plane**. [3.2](topic2.md) deployed applications onto "the nodes". This topic looks at the three EKS features that shape that data plane:

- **AWS Fargate on EKS** runs selected Pods on serverless compute. Each Pod gets its own isolated micro-VM; there is no node to create, patch or size. A **Fargate profile** decides which Pods run this way.
- **EKS managed node groups** are EC2 instances acting as nodes, where EKS automates the lifecycle: launching from an EKS-optimized AMI, joining the cluster, replacing unhealthy instances, and safe upgrades. You still choose instance types and scaling limits.
- **EKS add-ons** are AWS-packaged, versioned installs of components every cluster needs (VPC CNI, CoreDNS, `kube-proxy`), managed through the EKS API instead of loose YAML.

| Mechanism | Removes from you | Costs you |
|---|---|---|
| **Fargate profile** | The node: no AMI, patching or capacity planning | No DaemonSets, EBS, GPUs or privileged containers; per-Pod pricing; slower start |
| **Managed node group** | AMI choice, bootstrap, registration, safe node replacement | You still choose instance types, scaling and upgrade timing |
| **EKS add-on** | Building and version-matching core components | A version to update with every cluster upgrade |

!!! note "These combine; they are not alternatives"
    A typical production cluster runs managed node groups for most workloads, Fargate for a few namespaces, and core add-ons managed by EKS. The real skill is explaining **which workload belongs where, and why**.

## Why This Service or Concept Exists

Pods must run somewhere. Traditionally that is an EC2 node you patch, size, secure and pay for whether it is full or not. Different workloads tolerate that overhead differently.

### Why Fargate exists

| Workload | Why a node is a poor fit |
|---|---|
| Small service needing 0.25 vCPU | Smallest sensible node is much bigger and mostly idle |
| CI job running four minutes | Launching and draining a node takes longer than the job |
| Untrusted or customer code | Pods on a shared node share one kernel, a weaker boundary than a VM |
| Bursty, unpredictable traffic | Capacity must be guessed in advance |

Fargate makes **the Pod itself the unit of compute**: AWS creates a micro-VM sized to the Pod and bills per second. Almost every Fargate limitation follows from this one decision, so understand the reason rather than memorising the list.

### Why managed node groups exist

Self-managed nodes mean choosing an AMI, writing bootstrap scripts, building an Auto Scaling group, registering nodes, replacing failures and, hardest of all, **upgrading without dropping traffic**. This work is easy to get subtly wrong. Managed node groups do it behind one API and leave you the decisions that are really about the workload.

### Why add-ons exist

The network plugin, DNS and Service proxy are separate open-source projects with their own release cycles. Installed as loose `kubectl apply` files, nobody knows which version runs, nobody updates them, and a later cluster upgrade fails mysteriously. EKS add-ons give each one a **version, configuration and update operation**, visible in the EKS API and CloudTrail.

## Core Concepts

### The compute-management spectrum

```mermaid
flowchart LR
    SELF["Self-managed EC2 nodes"] --> MNG["EKS managed node groups"]
    MNG --> FARGATE["EKS on AWS Fargate"]
    FARGATE --> HIGH["Higher abstraction"]
```

Moving right: fewer servers to manage, less low-level control, more workload constraints, and pricing shifts from **per instance** to **per Pod**. Neither end is universally better.

| Model | Who manages the node | You still decide |
|---|---|---|
| **Self-managed** | You: AMI, bootstrap, registration, upgrades | Everything |
| **Managed node group** | EKS automates provisioning, replacement, updates | Instance types, scaling limits, labels, taints, upgrade timing |
| **Fargate** | AWS; no node is visible to you | Pod resource requests and which Pods use Fargate |

### Key ideas

- **Fargate changes where Pods run, not how Kubernetes works.** Deployments, Services, RBAC and the API are unchanged.
- **A managed node group is still EC2**, in your account, billed as normal EC2.
- **Add-ons are data plane software.** They run as Pods and must match the control plane version.
- **One cluster can mix models**, placing each workload where its trade-offs fit.

## AWS Service Deep Dive

### EKS Fargate profiles

**What a profile contains.** A name, a **Pod execution role**, a list of **private subnets**, and up to **five selectors**. Each selector needs a **namespace** and may add **labels**.

```yaml
fargateProfiles:
  - name: ci-runners
    podExecutionRoleARN: arn:aws:iam::111122223333:role/EksFargatePodExecutionRole
    subnets: [subnet-0a1, subnet-0b1, subnet-0c1]   # private subnets only
    selectors:
      - namespace: ci
        labels:
          runner: "true"        # namespace AND label must both match
      - namespace: preview-*    # wildcards are supported
```

Here, Pods in `ci` labelled `runner: "true"` run on Fargate, as do all Pods in any `preview-*` namespace. Everything else runs on EC2 nodes.

| Rule | Meaning |
|---|---|
| **Namespace is required** | Labels alone cannot select a Pod |
| **Labels within a selector: AND** | All must match |
| **Selectors within a profile: OR** | Any one may match |
| **Wildcards** | `*` and `?` allowed |
| **Profiles are immutable** | To change, create a new profile and delete the old |
| **Deleting a profile stops its Pods** | They become `Pending` |
| **Private subnets only** | No public IP; egress via NAT gateway or VPC endpoints |

**How a Pod reaches Fargate:**

```mermaid
flowchart TD
    POD["Pod created in namespace 'ci', labelled runner=true"] --> MATCH{"Matches a Fargate profile selector?"}
    MATCH -->|"No"| NODE["Scheduled onto an EC2 node as normal"]
    MATCH -->|"Yes"| FSCHED["Assigned to the Fargate scheduler"]
    FSCHED --> PROV["AWS provisions a micro-VM sized to the Pod's requests"]
    PROV --> ENI["Pod gets a VPC IP in one of the profile's private subnets"]
    ENI --> PULL["Image pulled using the Pod execution role"]
    PULL --> RUN["Pod runs; shows as its own fargate- node in kubectl get nodes"]
    RUN --> DONE["Pod ends; micro-VM destroyed, nothing reused"]
```

Because nothing is reused (no warm capacity, no image cache), **Fargate Pods start more slowly** than Pods on an existing node.

!!! warning "Design selectors around stable namespaces"
    Profiles cannot be edited, and deleting one stops its Pods. Select on stable namespaces like `ci` or `tenant-plugins`, not labels teams change often.

**Fargate limitations, and why they exist:**

| Limitation | Reason |
|---|---|
| No DaemonSets | A DaemonSet runs one Pod per node; there is no shared node |
| No privileged containers | They could reach the host, which AWS owns |
| No `hostNetwork` / `hostPort` | No customer host network to join |
| No GPUs | Capacity is standard AWS compute, not a chosen instance type |
| No EBS volumes | EBS attaches to an instance; use **EFS** instead |
| No Arm (Graviton) or Windows Pods | Fargate on EKS runs Linux Pods on AWS-chosen capacity; Arm is not offered |
| No EKS Pod Identity | Its agent is a DaemonSet; use **IRSA** ([3.1](topic1.md#iam-for-workloads-pod-identity)) |
| Load balancer targets must use IP mode | There is no instance to register |
| Slower Pod start | New micro-VM plus uncached image pull |

**Billing.** Per second (one-minute minimum) for the **vCPU and memory the Pod requests**, rounded up to the nearest supported size. Fargate first adds 256 MB to the memory request for its Kubernetes components (`kubelet`, `kube-proxy`, `containerd`), so a request of exactly 1 vCPU / 8 GB becomes 2 vCPU / 9 GB. Sizes range from 0.25 vCPU / 0.5 GB to 16 vCPU / 120 GB. Each Pod gets 20 GiB ephemeral storage by default, expandable to 175 GiB. The `CapacityProvisioned` annotation on the Pod (`kubectl describe pod`) shows the size actually billed.

| Requested (all containers) | Allocated and billed |
|---|---|
| 0.4 vCPU, 1.5 GB | 0.5 vCPU, 2 GB |
| 1 vCPU, 7.5 GB | 1 vCPU, 8 GB |
| 3 vCPU, 5 GB | 4 vCPU, 8 GB |

!!! tip "On Fargate, requests are the bill"
    On EC2 nodes, an oversized request mainly affects how many Pods fit. On Fargate, the rounded-up request is exactly what you pay.

**Other Fargate details:**

- **Pod execution role:** used by AWS to register the Pod as a node, pull images and, if logging is configured, ship logs. Application containers cannot use it (Fargate Pods have no instance metadata service either); give them IRSA.
- **Storage:** ephemeral storage dies with the Pod. Persistent or shared storage = Amazon EFS, which Fargate mounts without a separate driver install; volumes must be statically provisioned (no dynamic provisioning).
- **Logging:** no node for a logging DaemonSet, so use the built-in Fluent Bit router, configured with a ConfigMap in the `aws-observability` namespace.

### EKS managed node groups

**What it is.** EKS creates an EC2 **Auto Scaling group** and **launch template** in your account and operates them as Kubernetes nodes. No extra charge beyond EC2.

```mermaid
flowchart TB
    EKS["EKS control plane"] --> MNG["Managed node group: instance types, sizes, labels, taints"]
    MNG --> ASG["EC2 Auto Scaling group (created by EKS)"]
    ASG --> EC2A["EC2 node - AZ A"]
    ASG --> EC2B["EC2 node - AZ B"]
    ASG --> EC2C["EC2 node - AZ C"]
    EC2A --> P1["Pods"]
    EC2B --> P2["Pods"]
    EC2C --> P3["Pods"]
```

| Self-managed burden | Managed node group provides |
|---|---|
| Choose and track an AMI | AWS-published EKS-optimized AMIs per Kubernetes version |
| Bootstrap scripts | Automatic |
| Let nodes join the cluster | Access entry for the node role created automatically |
| Replace unhealthy nodes | The Auto Scaling group replaces failed instances; optional **node auto repair** also replaces nodes Kubernetes reports unhealthy (more conditions with the node monitoring agent add-on) |
| Upgrade safely | Rolling replacement with cordon and drain |
| Spot interruptions | Capacity Rebalancing: EKS launches a replacement when a Spot node is at risk, then cordons and drains the old one (best effort) |

**AMI families.**

| AMI | Use |
|---|---|
| **Amazon Linux 2023** | General-purpose default |
| **Bottlerocket** | Minimal container OS: read-only root, no shell; smaller attack surface, faster boot, harder to customise |
| **Accelerated AMIs** | AL2023 or Bottlerocket variants with NVIDIA (GPU) or Neuron drivers for machine learning |
| **Windows** | Windows containers |

!!! note "Amazon Linux 2 is legacy"
    EKS stopped publishing Amazon Linux 2 node AMIs on 26 November 2025; Kubernetes 1.32 was the last version with them. Older material that shows `AL2_x86_64` is out of date: use AL2023 or Bottlerocket.

**How node updates work.** Nodes are **replaced, not upgraded in place**:

1. Launch new nodes with the new AMI.
2. **Cordon** an old node: no new Pods scheduled there.
3. **Drain** it: evict its Pods so their controllers recreate them elsewhere, respecting each workload's **PodDisruptionBudget (PDB)**.
4. Terminate the old node and repeat.

`updateConfig` sets how many nodes are replaced at once (`maxUnavailable` count or `maxUnavailablePercentage`; default one node, at most 100). Small = safer; large = faster. That is the **default** update strategy (new before old, so capacity never drops). A **minimal** strategy terminates old nodes before launching new ones, for when extra capacity is unaffordable, such as scarce GPU instances.

EKS publishes patched EKS-optimized AMIs, but **you start the node group update**; it does not happen on its own.

!!! danger "A PodDisruptionBudget can block an upgrade"
    A PDB limits how many Pods of an app may be evicted at once, keeping it available during drains. But if it allows **zero** disruptions (for example `minAvailable: 3` with three replicas), the drain cannot finish: after 15 minutes the update fails with a `PodEvictionFailure` error. Keep `minAvailable` below the replica count or use `maxUnavailable: 1`. Check `kubectl get pdb -A` and the `ALLOWED DISRUPTIONS` column before upgrading. The force option ignores PDBs: an emergency escape, not a fix.

**Spot capacity.** `SPOT` capacity type uses spare EC2 capacity at a large discount, but AWS can reclaim it with a **two-minute warning**. Managed node groups enable Capacity Rebalancing, so EKS tries to launch a replacement and drain the at-risk node early; this is best effort, and Pods may still be cut off. To use Spot well:

- specify **several compatible instance types**, so one reclaimed pool does not remove the group;
- run only interruption-tolerant work (batch, CI, stateless workers);
- keep an **On-Demand group that can carry essential traffic alone**, with Spot above it (the same base-plus-Spot idea as ECS capacity providers in [2.3](../unit2/topic3.md)).

**Availability Zones.** Span node groups across AZs. But a multi-AZ node group alone is not high availability: the app also needs replicas spread across zones, and resilient dependencies.

**Names to know.**

- **Karpenter:** open-source autoscaler that launches right-sized EC2 instances directly for pending Pods, instead of scaling a fixed group.
- **EKS Auto Mode:** AWS runs the nodes for you (Karpenter-based scaling, Bottlerocket-based images, nodes replaced at least every 21 days) and builds in Pod networking, DNS, block storage and load balancing, so those are no longer add-ons you manage. Billed as a management fee per instance on top of EC2. The class shared cluster uses custom configuration (Auto Mode off) so that node groups and add-ons stay visible.
- **Launch template:** customises disk size, security groups and instance metadata (for example IMDSv2 hop limit 1, see [3.1](topic1.md#iam-for-workloads-pod-identity)). A **custom AMI** in it means EKS no longer updates that image for you.

### EKS add-ons

**What it is.** An AWS-managed install of a cluster component with a name, version, optional configuration, and optionally its own IAM role. AWS add-ons carry no extra charge beyond the resources used (some AWS Marketplace add-ons are paid). A cluster created in the console gets the VPC CNI, CoreDNS and `kube-proxy` by default.

The core networking add-ons were explained in [3.1](topic1.md#eks-networking-and-vpc-integration). Here the focus is **what breaks without each one**:

| Add-on | Job | Symptom when missing or broken |
|---|---|---|
| **Amazon VPC CNI** | VPC IPs for Pods | Nodes never `Ready`; Pods stuck `ContainerCreating` |
| **CoreDNS** | Service name resolution | Scattered timeouts that look like unrelated errors |
| **`kube-proxy`** | Service virtual IP routing | ClusterIP Services unreachable from affected nodes |
| **Amazon EBS CSI driver** | Creates and attaches EBS volumes for PVCs | PVCs stay `Pending`; stateful apps never start |
| **EKS Pod Identity Agent** | Per-Pod IAM credentials | Pods cannot get their AWS permissions |

Other add-ons: the **EFS CSI driver** (shared storage), the **CloudWatch Observability agent** (Container Insights) and the **node monitoring agent** (extra node health signals used by node auto repair).

!!! danger "CoreDNS failures look like everything failing"
    DNS problems rarely say "DNS is down". EKS starts CoreDNS with two replicas; keep at least two, spread across nodes and zones, and monitor its errors and latency.

**Add-ons and upgrades.** Each add-on version is compatible with particular Kubernetes versions, and EKS does **not** upgrade add-ons when you upgrade the control plane. So every upgrade includes a deliberate add-on step after the control plane: move each add-on to a version compatible with the new control plane and with the nodes (the VPC CNI and Pod Identity Agent move one minor version at a time). AWS's guides differ on whether add-ons or nodes come next; the firm rule is control plane first. The cluster-level procedure, including rollback within 7 days, is owned by [3.2](topic2.md#creating-and-managing-eks-clusters). Pin add-on versions in IaC.

**Give add-ons their own IAM role.** The EBS CSI driver creates volumes; the VPC CNI manages ENIs. Putting these permissions on the node role hands them to every Pod on the node. (The Pod Identity Agent is the exception: it needs no role of its own.)

**Operators, briefly.** An **operator** is a custom resource type plus a controller that keeps the real world matching it. The AWS Load Balancer Controller (Ingress → ALB) is a familiar example.

### Fargate versus managed node groups

| Dimension | Fargate | Managed node groups |
|---|---|---|
| Compute | AWS micro-VM per Pod | EC2 instances in your account |
| Node administration | None | Reduced; upgrades and sizing remain |
| Instance type / GPUs | No | Yes |
| DaemonSets | No | Yes |
| EBS volumes | No (EFS only) | Yes |
| Workload identity | IRSA only | Pod Identity or IRSA |
| Density | One Pod per micro-VM | Many Pods per node |
| Isolation | Per-Pod VM | Shared node kernel |
| Pod start | Slower | Fast when capacity exists |
| Pricing | Per Pod, by requested vCPU and memory | Per instance, full or not |
| Best fit | Small, bursty, short-lived, untrusted | Steady, dense, specialised, node-dependent |

## Architecture Components

| Component | Responsibility |
|---|---|
| **Fargate profile** | Selects which Pods run on Fargate, and in which private subnets |
| **Pod execution role** | IAM role AWS uses to start Fargate Pods and pull images |
| **Fargate micro-VM** | Isolated compute for one Pod, destroyed when it ends |
| **Fargate log router** | Built-in Fluent Bit, configured in `aws-observability` |
| **Managed node group** | EKS-operated EC2 nodes with lifecycle automation |
| **Auto Scaling group + launch template** | Created by EKS to launch and replace nodes |
| **EKS-optimized AMI** | Node image with `kubelet`, `containerd` and bootstrap tooling |
| **PodDisruptionBudget** | Limits evictions per workload during drains |
| **EKS add-ons** | Versioned core components (VPC CNI, CoreDNS, `kube-proxy`, CSI drivers, Pod Identity Agent) |

Three groups: **compute** (Fargate, node groups: where Pods run), **platform components** (add-ons: needed by every cluster), and the **supporting AWS services** from [3.1](topic1.md#architecture-components).

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **AWS Fargate** | Serverless compute; one micro-VM per Pod |
| **Fargate profile** | Selects which Pods run on Fargate, and where |
| **Selector** | Required namespace plus optional labels; up to five per profile |
| **Pod execution role** | IAM role AWS uses to run Fargate Pods |
| **Managed node group** | EKS-operated Auto Scaling group of EC2 nodes |
| **Self-managed node** | EC2 instance you bootstrap, register and upgrade |
| **EKS-optimized AMI** | AWS-published node image for a Kubernetes version |
| **Bottlerocket** | Minimal, immutable container-focused OS |
| **Launch template** | Customises node disks, security groups, metadata options |
| **Cordon / drain** | Stop new Pods on a node / evict its Pods |
| **PodDisruptionBudget (PDB)** | Limits voluntary evictions for a workload |
| **`updateConfig`** | How many nodes are replaced at once, and the update strategy |
| **Node auto repair** | Optional replacement of nodes reported unhealthy |
| **Capacity type** | On-Demand, Spot or Capacity Blocks |
| **Spot interruption notice** | Two-minute warning before Spot reclamation |
| **Karpenter** | Autoscaler launching right-sized nodes for pending Pods |
| **EKS add-on** | AWS-managed, versioned cluster component |
| **CSI driver** | Plugin connecting Kubernetes to EBS or EFS storage |
| **Operator** | Custom resource + controller automating a system |

## Configuration Options

### Fargate

| Setting | Options | Recommendation |
|---|---|---|
| **Selectors** | Namespace + optional labels | Namespace-only, on stable namespaces |
| **Subnets** | Private only | Several AZs |
| **Pod execution role** | IAM role | Registration, image pull and log shipping only |
| **Workload identity** | IRSA | Pod Identity not supported |
| **Resource requests** | vCPU, memory | Accurate: rounded up and billed |
| **Persistent storage** | EFS (static provisioning) | EBS not supported |
| **Logging** | Fluent Bit ConfigMap | Configure at cluster build |

### Managed node groups

| Setting | Options | Recommendation |
|---|---|---|
| **AMI type** | AL2023, Bottlerocket, GPU, Windows | AL2023 or Bottlerocket |
| **Instance types** | One or several | Several, especially for Spot |
| **Capacity type** | On-Demand, Spot, Capacity Blocks | On-Demand base; Spot for tolerant work |
| **Scaling** | `minSize`, `maxSize`, `desiredSize` | Min covers baseline; max caps cost |
| **Subnets** | One or more | Two, preferably three, AZs |
| **Labels and taints** | Any | Labels guide placement; taints reserve nodes |
| **`updateConfig`** | Count or percentage; default or minimal strategy | Small for small groups; about 25% for large; default strategy unless capacity is scarce |
| **Node auto repair** | On or off | On, ideally with the node monitoring agent |
| **Launch template** | Optional | Disk size, security groups, IMDS settings |

### Add-ons

| Setting | Options | Recommendation |
|---|---|---|
| **Which add-ons** | Core + optional | VPC CNI, CoreDNS, `kube-proxy`, Pod Identity Agent; EBS CSI if stateful |
| **Version** | Explicit or default | Pin in IaC |
| **Configuration** | JSON/YAML via EKS API | Keep in code (for example CoreDNS replicas) |
| **IAM role** | IRSA or Pod Identity | Own role per add-on, not the node role |

## Design Considerations

### Decision framework

Ask these for each workload:

1. **Needs node-level features?** GPUs, DaemonSets, EBS, privileged mode, host networking → managed node group.
2. **Untrusted or multi-tenant code?** → Fargate's per-Pod VM boundary.
3. **Usage pattern?** Bursty, short-lived or tiny → Fargate (no idle node). Steady and dense → well-packed nodes are cheaper.
4. **Fast scale-out on the user path?** Nodes with spare capacity respond faster than new Fargate micro-VMs.
5. **Full cost?** Include utilisation, idle capacity, operations effort, storage and logs, not just unit price.

```mermaid
flowchart TD
    A["A workload arrives. Where should it run?"] --> B{"Needs GPU, DaemonSet, EBS, privileged mode, or host networking?"}
    B -->|"Yes"| C["Managed node group"]
    B -->|"No"| D{"Untrusted or multi-tenant code?"}
    D -->|"Yes"| E["Fargate profile"]
    D -->|"No"| F{"Bursty, short-lived, or very small?"}
    F -->|"Yes"| E
    F -->|"No: steady and dense"| C
    C --> G{"Tolerates interruption?"}
    G -->|"Yes"| H["Spot node group above an On-Demand base"]
    G -->|"No"| I["On-Demand node group"]
```

### Trade-offs

!!! note "Core trade-off"
    More abstraction reduces infrastructure management, but also reduces low-level control.

| Quality | Fargate | Managed node groups |
|---|---|---|
| **Operational burden** | Lowest | Moderate |
| **Isolation** | Per-Pod VM | Shared node kernel |
| **Cost, steady workloads** | Higher | Lower when well packed |
| **Cost, bursty workloads** | Lower (no idle nodes) | Higher if nodes sit idle |
| **Elasticity** | Per Pod, slower start | Fast with headroom |
| **Flexibility** | Constrained | High |

### Architecture scenarios

**Scenario 1: small internal APIs.** Moderate, unpredictable traffic; team wants minimal admin. Fargate fits if the services meet its constraints: no nodes, pay per running Pod.

**Scenario 2: high-throughput service.** Needs predictable compute, high density, specific instance families and node monitoring agents. Managed node groups fit.

**Scenario 3: mixed.** One cluster, both models:

```mermaid
flowchart TB
    EKS["EKS cluster"]
    EKS --> F["Fargate profiles"]
    EKS --> M["Managed node groups"]
    F --> API["Small internal APIs"]
    F --> JOB["Short-lived CI and batch jobs"]
    F --> UNTRUSTED["Untrusted plugin code"]
    M --> WEB["High-throughput services"]
    M --> GPU["GPU workloads"]
    M --> AGENT["Workloads needing DaemonSets or EBS"]
```

**Principle:** choose the compute model **per workload**, not one model for everything.

## AWS Best Practices

| Pillar | Practice |
|---|---|
| **Operational Excellence** | Node groups, Fargate profiles and add-ons in IaC with pinned versions; update add-ons in every upgrade |
| **Security** | Fargate for untrusted code; own IAM role per add-on; minimal node role; Bottlerocket where suitable |
| **Reliability** | Node groups across AZs; CoreDNS with 2+ replicas; PDBs that allow at least one disruption |
| **Performance Efficiency** | Match compute model to workload shape; small images (especially on Fargate); keep node headroom |
| **Cost Optimization** | Spot above an On-Demand base; Fargate where nodes would idle; Graviton where images support ARM |
| **Sustainability** | Dense packing; scale batch node groups to zero when idle |

## Security Considerations

- **Fargate isolation is a real boundary.** A container escape on a shared node reaches a kernel shared with other Pods; on Fargate it reaches an AWS kernel running one Pod. Apply it to just the namespaces that need it.
- **No node role on Fargate to misuse.** The Pod execution role is not available to containers. On EC2 nodes, block IMDS with hop limit 1 ([3.1](topic1.md#iam-for-workloads-pod-identity)).
- **Add-ons get their own roles**, not the node role.
- **Harden nodes.** Encrypted EBS, Systems Manager instead of SSH, minimal AMI, regular updates.
- **Private subnets** for Fargate Pods and nodes; NAT or VPC endpoints for egress.

!!! warning "Review what you install"
    Helm charts and add-ons often create cluster-wide permissions. Read what they create, and install only what the cluster needs.

## Operating It: Performance, Cost and Monitoring

**Performance.** A latency-sensitive service that must scale out fast is better on nodes with spare capacity than on Fargate. Keep images small, scale CoreDNS with the cluster, keep node headroom.

**Cost.**

| Lever | Helps by | Caution |
|---|---|---|
| Spot above On-Demand base | Big discount | Must tolerate rescheduling; use several types |
| Fargate for bursty work | No idle nodes | Costlier for steady work |
| Accurate requests | Fewer nodes / smaller Fargate bill | Too low hurts performance |
| Graviton (ARM) nodes | Better price-performance | Needs ARM images; not available on Fargate |
| Scale batch groups to zero | No idle cost | Only for work that really stops |

!!! tip "Fargate is not always cheaper"
    Cost depends on utilisation, requests and density. Compare per workload.

**Monitoring.**

| Signal | Source | Tells you |
|---|---|---|
| `Pending` Pods | `kubectl get pods`, events | No matching capacity or Fargate profile |
| Node group update status | `aws eks describe-nodegroup` | Upgrade progressing or stuck |
| PDBs | `kubectl get pdb -A` | `ALLOWED DISRUPTIONS: 0` will block drains |
| Fargate Pods | `kubectl get nodes -l eks.amazonaws.com/compute-type=fargate` | What runs (and bills) on Fargate |
| Add-on health and version | `aws eks describe-addon` | Version drift or degraded add-on |
| CoreDNS errors and latency | Container Insights | DNS trouble before it spreads |
| Audit trail | CloudTrail | Who changed node groups, profiles, add-ons |

!!! note "Running is not healthy"
    A `Running` Pod can still return errors. Monitor latency and error rates too.

## Advantages

- **Compute is a per-workload choice.** Fargate and node groups coexist in one cluster.
- **Fargate removes node management** and gives per-Pod isolation.
- **Managed node groups keep control without the plumbing.** AMIs, bootstrap, replacement and rolling updates handled.
- **Spot becomes practical** through automatic draining.
- **Add-ons are visible and upgradable** through the EKS API.
- **No extra management charge** for node groups or AWS add-ons.

## Limitations

- **Fargate's limits are structural** (no node): no DaemonSets, privileged containers, GPUs, EBS or Pod Identity; slower start.
- **Fargate is costly for steady, dense work.**
- **Fargate profiles are immutable.**
- **Node groups do not pick sizes for you**; varied needs may need several groups.
- **Your own PDBs can block node updates.**
- **Custom AMIs** shift update responsibility back to you.
- **Add-ons need updating** with every Kubernetes upgrade.

## Common Mistakes

### Beginner mistakes and misconceptions

| Mistake | Why it is wrong | Do instead |
|---|---|---|
| "Fargate is always cheaper" | Steady workloads are often cheaper on nodes | Compare full cost per workload |
| "Fargate eliminates Kubernetes" | Only the compute layer changes | Manage Deployments, Services, RBAC as normal |
| "Managed node groups = managing each instance by hand" | EKS automates lifecycle | Focus on sizing and scaling |
| "One compute model per cluster" | Models coexist | Choose per workload |
| Whole cluster on Fargate | Loses DaemonSets, EBS, GPUs; costs more for steady work | Fargate for specific namespaces |
| Expecting DaemonSets or EBS on Fargate | No node to run on or attach to | Fluent Bit, sidecars, EFS, or nodes |
| Pod Identity on Fargate | Agent is a DaemonSet | IRSA |
| Editing a Fargate profile | Immutable | Create new, delete old |
| One instance type for Spot | One reclaimed pool removes the group | Several compatible types |

### Production mistakes

| Mistake | Consequence | Remedy |
|---|---|---|
| PDB allowing zero disruptions | Node upgrades fail with `PodEvictionFailure` | Allow at least one; check before upgrades |
| Routinely forcing node updates | PDBs give no protection | Fix the budgets instead |
| Add-ons skipped during upgrades | Networking or DNS failures | Update them as an explicit step of every upgrade, after the control plane |
| CoreDNS with one replica | Cluster-wide mysterious timeouts | 2+ replicas across zones |
| Add-ons using the node role | Every Pod gains their permissions | Own role per add-on |
| All Spot, no On-Demand base | One capacity event removes the workload | On-Demand base + diverse Spot |
| All nodes in one AZ | One zone failure = no capacity | Span multiple AZs |
| No Fargate log routing | Fargate logs lost | Configure `aws-observability` at build |

## Summary

EKS compute is a trade-off between **control, operational effort, flexibility, density and cost**.

| Feature | Key lesson |
|---|---|
| **Data plane choice** | Per workload. Fargate and node groups can share a cluster; start from workload requirements |
| **Fargate** | For small, bursty, short-lived or untrusted Pods. Limits (no DaemonSets, EBS, GPUs, Pod Identity; billed on rounded-up requests) all follow from "no node" |
| **Fargate profiles** | Namespace + optional labels; immutable; design around stable namespaces |
| **Managed node groups** | For EC2-level control, special hardware, node agents, density. EKS handles AMIs, replacement and rolling updates |
| **PDBs** | Protect availability during drains, but zero slack blocks upgrades |
| **Spot** | Several instance types, tolerant workloads, On-Demand base |
| **Add-ons** | Essential data plane software; pin versions, own IAM roles, update every upgrade |

**Unit 3 in one line:** 3.1 built the cluster, 3.2 deployed onto it, 3.3 chose the right compute underneath each workload.

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit3.md#33-amazon-eks-advanced-concepts) · [Interview questions](../interviewquestions/unit3.md#33-amazon-eks-advanced-concepts).

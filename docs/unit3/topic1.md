# Amazon EKS Architecture

## Definition

**Amazon Elastic Kubernetes Service (EKS)** is a managed Kubernetes service in which AWS operates the Kubernetes control plane: the API server, `etcd`, the scheduler, and the controller managers:  as a highly available, single-tenant, AWS-owned deployment, while the worker nodes that run your containers execute inside your own Amazon VPC under your control.

The defining architectural fact of EKS is a **boundary that runs through the middle of a Kubernetes cluster**:

| Side of the boundary | What runs there | Who owns it | Who pays for it |
|---|---|---|---|
| **Control plane** | `kube-apiserver`, `etcd`, `kube-scheduler`, `kube-controller-manager`, `cloud-controller-manager`, the AWS IAM Authenticator webhook | AWS, in an AWS-managed VPC in an AWS-owned account | A flat per-cluster hourly fee |
| **Data plane** | `kubelet`, `kube-proxy`, `containerd`, your Pods, the VPC CNI plugin, CoreDNS, add-on Pods | You, in your VPC, on EC2 instances or Fargate | The compute, storage, and network you consume |

Everything else in this chapter is a consequence of that boundary. The control plane must reach your nodes, so EKS places network interfaces in your subnets. Your nodes must reach the control plane, so the API server has an endpoint whose accessibility you configure. Your Pods must have identities that AWS recognises, so a Kubernetes ServiceAccount must be bound to an IAM role. Your Pods need addresses, so a CNI plugin allocates them from your VPC.

Within an AWS architecture, EKS occupies the same position as Amazon ECS  the container orchestration layer above EC2 and below the application  but with a different contract. ECS is an AWS API for running containers. **EKS is the Kubernetes API, hosted**: your manifests, operators, Helm charts, and Kubernetes expertise transfer directly, and so do the Kubernetes concepts you must learn.

!!! note "EKS is not a fork of Kubernetes"

    EKS runs **upstream, CNCF-conformant Kubernetes**. There is no AWS dialect of the API, no proprietary object types you must use, and no lock-in at the manifest level: a Deployment written for EKS applies unchanged to a cluster running anywhere. What AWS adds is *operation* of the control plane, *integration* with AWS services through controllers and CSI drivers, and *validated builds* of the components everyone needs anyway. This distinction matters for the recurring exam and interview question about portability: your workload manifests are portable; your integrations with AWS Load Balancers, EBS volumes, and IAM roles are not, and that is a deliberate trade you make service by service.

---

## Why This Service or Concept Exists

### The problem: a Kubernetes control plane is genuinely hard to run

Kubernetes is a distributed system whose control plane must be highly available, consistent, and continuously patched. Operating one yourself means:

- Running **`etcd`**  a Raft-based consensus store  with an odd number of members across failure domains, monitoring its disk latency (to which it is exquisitely sensitive), taking and testing backups, defragmenting it, and rotating its certificates.
- Running **multiple API server replicas** behind a load balancer, with a full PKI: a cluster certificate authority, server certificates, client certificates for every component, and a rotation process for all of them.
- Running the **scheduler** and **controller manager** with leader election, and understanding what happens when leadership changes during a partition.
- Performing **version upgrades** of all of the above, in the correct order, while the cluster serves production traffic.

None of this differentiates your product. All of it can take a cluster down in ways that are difficult to diagnose. A frequently cited internal figure across the industry is that a self-managed Kubernetes control plane consumes the better part of one engineer's time per cluster, and produces its worst incidents at the moments it is being upgraded.

| Self-managed control plane burden | What EKS does about it |
|---|---|
| `etcd` quorum, backup, defragmentation, disk latency | AWS runs three `etcd` instances across three Availability Zones and operates them |
| API server HA, load balancing, scaling under load | At least two API server instances across AZs, scaled by AWS in response to load |
| Certificate authority and rotation for every component | Managed by AWS; you never see the control plane PKI |
| Control plane patching for CVEs | AWS patches within the platform version, transparently |
| Version upgrades of API server, scheduler, controllers | A single `UpdateClusterVersion` call; AWS performs the sequence |
| Control plane availability during an AZ failure | Multi-AZ by construction, with an availability SLA |
| Authenticating cloud identities to the cluster | The IAM Authenticator webhook is built in |

### Why not just use ECS?

This is the question a DSO303 student should be able to answer without appealing to preference, and [Chapter 1.7](../unit1/topic7.md) introduced it. The honest summary:

| Choose ECS when | Choose EKS when |
|---|---|
| The team is small and has no Kubernetes experience | The team already has Kubernetes skills, or will hire for them |
| The workload is AWS-only and will stay that way | Multi-cloud, hybrid, or on-premises portability is a real requirement |
| You want the smallest possible operational surface | You need the Kubernetes ecosystem: operators, Helm charts, service meshes, CRDs |
| The application is a straightforward set of services | You need advanced scheduling, custom controllers, or platform-building primitives |
| Time to first deployment matters more than flexibility | You are building an internal platform other teams will consume |

The decisive factor is usually **the ecosystem, not the scheduler**. Kubernetes' value is that thousands of pieces of infrastructure software  Argo CD, Istio, Prometheus operators, KEDA, cert-manager, database operators  are packaged as Kubernetes objects. If you need those, you need Kubernetes. If you do not, ECS achieves the same outcome with a fraction of the concepts.

### Why AWS runs the control plane in its own account

The control plane could have been run in your VPC on instances you own; EKS Anywhere and self-managed Kubernetes do exactly that. AWS chose otherwise for three reasons that are worth understanding because they explain the entire architecture:

**Isolation and blast radius.** Each cluster's control plane is single-tenant and runs in its own AWS-managed VPC. Nothing you do to your VPC  a route table error, a security group change, an IP exhaustion event, a node that pegs the network  can affect the control plane's availability.

**Operability.** AWS can patch, scale, and replace control plane instances without coordinating with you, because they are not in your account and do not appear in your inventory. When an API server instance becomes unhealthy, it is replaced, possibly in a different Availability Zone, and you do not see it happen.

**Uniform SLA.** A control plane whose reliability depended on customer VPC configuration could not carry a meaningful service level agreement. Moving it out of your account is what makes the API server endpoint availability SLA possible.

The cost of that choice is the complexity this chapter spends most of its time on: because the control plane is *outside* your VPC but must reach *inside* it, EKS creates cross-account network interfaces in your subnets, and a significant fraction of real EKS failures are failures of that path.

!!! tip "Frame every EKS design question as 'which side of the boundary is this on?'"

    Is the failure in the control plane (AWS's problem, visible as API errors and an SLA claim) or in the data plane (your problem, visible as Pods that will not start)? Is this component patched by AWS or by you? Does this traffic cross the boundary, and if so through which network interface and which security group? Students who internalise the boundary answer troubleshooting questions quickly; students who treat the cluster as one undifferentiated thing do not.

---

## Core Concepts

### The split architecture

```mermaid
flowchart TD
    subgraph AWSACC["AWS-managed account and VPC (you cannot see this)"]
        API1["kube-apiserver instance (AZ a)"]
        API2["kube-apiserver instance (AZ b)"]
        NLBI["Network Load Balancer for the API endpoint"]
        ETCD1["etcd (AZ a)"]
        ETCD2["etcd (AZ b)"]
        ETCD3["etcd (AZ c)"]
        SCHED["kube-scheduler"]
        CM["kube-controller-manager"]
        CCM["cloud-controller-manager"]
        AUTH["AWS IAM Authenticator webhook"]
        NLBI --> API1
        NLBI --> API2
        API1 --- ETCD1
        API1 --- ETCD2
        API1 --- ETCD3
        SCHED --> API1
        CM --> API1
        CCM --> API1
        AUTH --- API1
    end
    subgraph CUST["Your account and VPC"]
        ENI["Cross-account ENIs created by EKS in your subnets"]
        subgraph NODE["Worker node (EC2)"]
            KUBELET["kubelet"]
            PROXY["kube-proxy"]
            CRI["containerd"]
            PODS["Your Pods"]
        end
        CNI["Amazon VPC CNI (aws-node DaemonSet)"]
        DNS["CoreDNS Pods"]
    end
    KUBELET -->|"outbound TLS to the cluster endpoint, port 443"| NLBI
    API1 -->|"inbound via cross-account ENI: exec, logs, port-forward, webhooks, metrics"| ENI
    ENI --> KUBELET
    ENI --> PODS
    CNI --> PODS
    CCM -->|"creates ELBs, attaches EBS volumes, updates routes"| CUST
```
<!-- TODO: Generate a professionl, educational clean image with white background -->
![alt text](image.png)

![alt text](image-1.png)

![alt text](image-2.png)
Three facts in this diagram do most of the explanatory work.

**The kubelet always initiates the outbound connection.** Every node maintains a persistent, authenticated TLS connection *out* to the cluster endpoint on port 443. This is why nodes in private subnets need a route to the endpoint  through a NAT gateway, through the private endpoint, or through VPC endpoints  and why the node security group needs outbound 443.

**The API server sometimes needs to initiate an inbound connection.** `kubectl exec`, `kubectl logs`, `kubectl port-forward`, the metrics API, and **every admission webhook** require the API server to open a connection to something inside your VPC. It does this through the cross-account ENIs. If that path is blocked, the cluster appears to work until you try to debug it or until an admission webhook is registered  at which point deployments fail.

**The cloud controller manager turns Kubernetes objects into AWS resources.** A Service of type `LoadBalancer` becomes an actual load balancer; a PersistentVolumeClaim becomes an EBS volume attachment; a node object's lifecycle follows an EC2 instance's. This is the integration layer, and it is why Kubernetes objects on EKS have AWS side effects that cost money.

### Kubernetes control plane components, and who runs them

| Component | Responsibility | On EKS |
|---|---|---|
| **`kube-apiserver`** | The only component that talks to `etcd`; validates, authenticates, authorizes, and admits every request; serves watches | AWS-managed, at least two instances across AZs |
| **`etcd`** | Consistent key-value store holding all cluster state; the single source of truth | AWS-managed, three instances across three AZs |
| **`kube-scheduler`** | Watches for unscheduled Pods, filters and scores nodes, binds Pod to node | AWS-managed |
| **`kube-controller-manager`** | Runs the built-in control loops: Deployment, ReplicaSet, Node, Job, ServiceAccount, and others | AWS-managed |
| **`cloud-controller-manager`** | The AWS-specific loops: node lifecycle from EC2, Service load balancers, routes | AWS-managed |
| **AWS IAM Authenticator webhook** | Validates the SigV4 pre-signed token in a `kubectl` request and maps it to a Kubernetes identity | AWS-managed, built in |
| **`kubelet`** | The node agent: registers the node, accepts Pod specs, tells the runtime to start containers, reports status, runs probes | **Yours**, on every node |
| **`kube-proxy`** | Programs the node's packet-forwarding rules so ClusterIP Services resolve to Pod endpoints | **Yours**, as a DaemonSet (an EKS add-on) |
| **`containerd`** | The container runtime that actually pulls images and runs containers | **Yours**, on every node |
| **VPC CNI (`aws-node`)** | Allocates VPC IP addresses to Pods and wires their network namespaces | **Yours**, as a DaemonSet (an EKS add-on) |
| **CoreDNS** | Cluster DNS: resolves Service names to ClusterIPs | **Yours**, as a Deployment (an EKS add-on) |

!!! warning "The add-ons are your responsibility even though AWS builds them"

    `kube-proxy`, CoreDNS, and the VPC CNI run as workloads *in your cluster*. AWS publishes validated, patched builds of them as **EKS add-ons**, and will update them when you ask  but they are data plane components, they consume your resources, they are on the critical path of every request, and if you never update them they will drift out of compatibility with the control plane version. A cluster upgraded to a new Kubernetes version with a two-year-old CNI is a common and entirely avoidable production incident. The add-on model itself is covered in [3.3](topic3.md#the-eks-add-on-model).

### The Kubernetes object model, in the terms Chapter 2 established

For students arriving from ECS, the mapping is close enough to be useful and different enough to be dangerous:

| ECS concept | Kubernetes equivalent | Where they differ |
|---|---|---|
| Task definition | **Pod spec** (usually inside a Deployment template) | A Pod is a *group* of containers sharing a network namespace and volumes; a task definition is closer, but Kubernetes leans much harder on the sidecar pattern |
| Task | **Pod** | Same idea: the smallest schedulable unit |
| Service | **Deployment** + **Service** | Kubernetes splits "keep N replicas running" (Deployment) from "give them a stable address" (Service); ECS conflates them |
| Service discovery via Cloud Map | **Service** + CoreDNS | Kubernetes DNS is built in and mandatory rather than opt-in |
| Cluster | **Cluster** | Same word, but a Kubernetes cluster carries far more state and far more API surface |
| Container instance | **Node** | Same idea; a Node is an API object with conditions, taints, labels, and capacity |
| Placement constraint | **nodeSelector**, **node affinity**, **taints and tolerations** | Kubernetes has strictly more expressive placement, including Pod-to-Pod affinity |
| Placement strategy `spread` | **topologySpreadConstraints** | Kubernetes lets you set the tolerated skew and choose the topology key |
| Service auto scaling | **HorizontalPodAutoscaler** | Same control loop; the metric plumbing differs (metrics-server, KEDA) |
| Capacity provider managed scaling | **Cluster Autoscaler** or **Karpenter** | Same second loop; Karpenter is substantially more capable |
| ECS deployment circuit breaker | **Deployment strategy + readiness probes + progressDeadlineSeconds** | Kubernetes will also stall rather than break, but rollback is a manual `kubectl rollout undo` unless you add tooling |
| Task role | **ServiceAccount + IRSA or Pod Identity** | This is the largest conceptual gap and the subject of [EKS Security and IAM Integration](#core-concepts-eks-security-and-iam-integration) below |

### Node types: the data plane options

```mermaid
flowchart TD
    A["What kind of compute does this workload need?"] --> B{"Do you want to think about nodes at all?"}
    B -->|"no, and I want AWS to run the whole data plane"| C["EKS Auto Mode"]
    B -->|"no, and this is a small or bursty workload"| D["AWS Fargate profile"]
    B -->|"yes, but I want AWS to handle AMIs, patching and draining"| E["EKS managed node group"]
    B -->|"yes, and I want just-in-time, right-sized, diverse instances"| F["Karpenter on top of EC2"]
    B -->|"yes, and I need full control of the instance"| G["Self-managed nodes"]
    B -->|"the compute is in my own data centre"| H["EKS Hybrid Nodes"]
    C --> I["No AMI management, no add-on management, nodes replaced on a 21-day cycle; a management fee on top of EC2"]
    D --> J["No node at all: no DaemonSets, no EBS, no GPU, no privileged containers, no host ports"]
    E --> K["AWS-published EKS-optimized AMI, managed upgrades with cordon and drain, an ASG you can see"]
    F --> L["Fast, dense, Spot-friendly bin packing; you run and upgrade the Karpenter controller"]
    G --> M["Any AMI, any bootstrap, any kernel; you own patching, draining, and upgrade order"]
    H --> N["Nodes on-premises joined to an EKS control plane; priced per vCPU"]
```

| Option | You manage | AWS manages | Choose when |
|---|---|---|---|
| **Managed node group** | Instance types, size, scaling bounds, labels and taints | AMI publication, node bootstrap, cordon-and-drain upgrades, health replacement | The default for most clusters: real nodes without AMI plumbing |
| **Self-managed nodes** | Everything: AMI, user data, ASG, upgrades, draining | Nothing beyond the control plane | You need a custom kernel, a specialised AMI, or an unsupported configuration |
| **AWS Fargate** | Nothing about infrastructure | The entire node concept | Bursty, small, stateless, untrusted, or isolation-sensitive Pods |
| **Karpenter** | The Karpenter controller and its NodePools | EC2 instance provisioning happens just in time | Scaling speed and bin-packing efficiency matter; heterogeneous or Spot-heavy fleets |
| **EKS Auto Mode** | Your workloads and NodePool policy | Compute, networking, storage, load balancing, node OS patching, add-on lifecycle | You want a managed data plane and accept the management fee and reduced control |
| **Hybrid Nodes** | On-premises hardware and its networking | The control plane, and the node's Kubernetes integration | Regulated or latency-bound workloads that must stay on-premises under one control plane |

!!! tip "The default recommendation for a first production cluster"

    **Managed node groups in private subnets across three Availability Zones, with the four core add-ons managed by EKS, plus Karpenter for any workload whose scaling is spiky.** This gives you real nodes (so DaemonSets, EBS volumes, and GPUs all work), AWS-managed AMIs and upgrades, and a fast second scaling loop where it matters. Fargate is then used selectively for specific namespaces rather than universally, and Auto Mode becomes attractive when the team's constraint is people rather than control.

### Node bootstrap and registration

A node does not become part of a cluster by being launched. The sequence matters because most "node stuck in `NotReady`" problems are a failure of one of these steps:

```mermaid
sequenceDiagram
    participant ASG as "EC2 Auto Scaling group"
    participant EC2 as "EC2 instance (EKS-optimized AMI)"
    participant BOOT as "Bootstrap: nodeadm / bootstrap.sh"
    participant KUBELET as "kubelet"
    participant API as "EKS API server"
    participant CNI as "aws-node (VPC CNI)"
    ASG->>EC2: "launch with user data and the node instance profile"
    EC2->>BOOT: "cloud-init runs the bootstrap"
    BOOT->>API: "DescribeCluster: fetch endpoint, CA certificate, cluster CIDR"
    BOOT->>KUBELET: "write kubelet config, kubeconfig, container runtime config"
    KUBELET->>API: "TLS bootstrap: authenticate with the node instance role via the IAM Authenticator"
    API->>API: "map the node role to system:nodes via an access entry"
    KUBELET->>API: "submit a Certificate Signing Request for a node client certificate"
    API-->>KUBELET: "signed certificate; node object created"
    KUBELET->>API: "report status: capacity, conditions, still NotReady (no network)"
    CNI->>CNI: "aws-node DaemonSet starts, attaches ENIs, builds the warm IP pool"
    CNI->>KUBELET: "CNI config written to /etc/cni/net.d"
    KUBELET->>API: "node condition Ready"
    API->>KUBELET: "scheduler may now bind Pods here"
```

Two consequences are worth stating explicitly. First, **a node is `NotReady` until the CNI is functional**, which is why a broken `aws-node` DaemonSet presents as nodes that never become ready rather than as a networking error. Second, **the node instance role must have an access entry mapping it to the node group**  with the API authentication mode this is created automatically for managed node groups, and it is exactly what you must create by hand for self-managed nodes. A node whose role has no mapping authenticates successfully and is then refused, and the symptom is a node that never appears in `kubectl get nodes` at all.

### Cluster endpoint access

The API server endpoint is a public DNS name that resolves differently depending on configuration:

| Mode | Resolves to | Node traffic path | `kubectl` from the internet | Typical use |
|---|---|---|---|---|
| **Public only** | Public IPs | Nodes egress to the public endpoint via NAT or an internet gateway | Yes, restricted by CIDR allow-list | Development; production only with a tight allow-list |
| **Public and private** | Public IPs from outside the VPC; private IPs from inside | Nodes stay inside the VPC | Yes, restricted by CIDR allow-list | The common production choice |
| **Private only** | Private IPs (via an EKS-managed Route 53 private hosted zone) | Inside the VPC | No  only from inside the VPC, or via VPN, Direct Connect, or a bastion | Regulated environments |

!!! danger "Private-only endpoints break `kubectl` from your laptop, and that is the point"

    With a private-only endpoint, every administrative action and every CI/CD pipeline must reach the cluster from inside the VPC or a network connected to it. This is a real security improvement and a real operational cost: you now need a bastion, a VPN, a self-hosted runner, or AWS Systems Manager Session Manager port forwarding. Teams routinely enable private-only, discover their pipeline is broken, and re-enable public access with `0.0.0.0/0`  which is strictly worse than where they started. Decide the access path *before* you change the endpoint mode.

---

## Core Concepts: EKS Networking and VPC Integration

### The VPC CNI's central decision

Most Kubernetes networking plugins give Pods addresses from an **overlay** network  a private CIDR that exists only inside the cluster, with packets encapsulated (VXLAN, Geneve) as they cross node boundaries. The Amazon VPC CNI does something different and more consequential: **every Pod receives a real, routable IP address from your VPC subnet**, drawn from secondary IP addresses on elastic network interfaces attached to the node.

```mermaid
flowchart TD
    subgraph N["Worker node, e.g. m5.large"]
        ENI0["Primary ENI: node IP + 9 secondary IPs"]
        ENI1["Secondary ENI: 10 secondary IPs"]
        ENI2["Secondary ENI: 10 secondary IPs"]
        IPAMD["ipamd inside aws-node: warm pool manager"]
        P1["Pod A: 10.0.1.34"]
        P2["Pod B: 10.0.1.57"]
        P3["Pod C: 10.0.1.91"]
        ENI0 --> P1
        ENI1 --> P2
        ENI1 --> P3
        IPAMD --> ENI0
        IPAMD --> ENI1
        IPAMD --> ENI2
    end
    VPC["VPC subnet 10.0.1.0/24"] --> ENI0
    VPC --> ENI1
    VPC --> ENI2
    P1 -->|"native VPC routing, no encapsulation"| OTHER["Pod on another node, an RDS instance, or anything else in the VPC"]
```

**Why AWS chose this.** Native VPC addressing means no encapsulation overhead, no separate network to debug, VPC Flow Logs that show Pod-level traffic, security groups that can apply to Pods, and  most importantly  Pods that are first-class VPC citizens reachable from anything else in the VPC without a gateway.

**What it costs.** Pod density is bounded by IP addresses, not only by CPU and memory, and your VPC's address plan becomes a cluster capacity constraint. This is the single most common architectural surprise in EKS.

### Maximum Pods per node

Without prefix delegation, the formula is:

```
max_pods = (number_of_ENIs × (IPs_per_ENI − 1)) + 2
```

The `− 1` is the ENI's primary address, which the Pods do not use; the `+ 2` accounts for Pods on the host network (`aws-node` and `kube-proxy`), which do not consume a Pod IP.

| Instance type | ENIs | IPs per ENI | Max Pods (standard) | Max Pods (prefix delegation) |
|---|---|---|---|---|
| `t3.small` | 3 | 4 | 11 | 110 |
| `t3.medium` | 3 | 6 | 17 | 110 |
| `m5.large` | 3 | 10 | 29 | 110 |
| `m5.xlarge` | 4 | 15 | 58 | 110 |
| `m5.4xlarge` | 8 | 30 | 234 | 250 |
| `m5.24xlarge` | 15 | 50 | 737 | 250 (Kubernetes-capped) |

!!! warning "A `t3.medium` node runs 17 Pods, and about five of them are already spoken for"

    `aws-node` and `kube-proxy` are host-network and do not count, but CoreDNS, the EBS CSI node driver, a log agent, a metrics agent, and a service mesh sidecar injector all do. Students in AWS Academy labs routinely launch two `t3.medium` nodes, deploy a modest application, and cannot understand why Pods are `Pending` with `Too many pods`. The answer is arithmetic, not configuration.

### Prefix delegation

**Prefix delegation** changes the allocation unit from a single IP address to a `/28` prefix (16 addresses) per slot on the ENI. Enabling `ENABLE_PREFIX_DELEGATION=true` on the VPC CNI transforms density:

```
max_pods = (number_of_ENIs × ((IPs_per_ENI − 1) × 16)) + 2
```

capped by the Kubernetes recommendation of **110 Pods** for nodes with fewer than 30 vCPUs and **250 Pods** for larger ones. An `m5.large` goes from 29 Pods to 110  the same instance, four times the density, at no additional charge.

The trade-off is **IP consumption granularity**: a `/28` is allocated even if the node needs one address from it, and prefixes require contiguous free space in the subnet. A fragmented subnet may have 100 free addresses and no free `/28`, in which case prefix assignment fails while single-IP assignment would have succeeded.

| Setting | Effect | When to change it |
|---|---|---|
| `ENABLE_PREFIX_DELEGATION` | Allocate `/28` prefixes instead of single IPs | Almost always on Nitro instances; the density gain is large and free |
| `WARM_ENI_TARGET` | Keep this many fully free ENIs warm (default 1) | Lower it to conserve IPs; raise it for very fast Pod churn |
| `WARM_IP_TARGET` | Keep this many free IPs warm regardless of ENI boundaries | Set it in IP-constrained VPCs to stop over-allocation |
| `MINIMUM_IP_TARGET` | Floor on total allocated IPs | Pair with `WARM_IP_TARGET` to avoid churn on small nodes |
| `WARM_PREFIX_TARGET` | Warm prefixes to keep when prefix delegation is on | 1 is usually right; higher wastes address space |
| `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG` | Put Pods in different subnets from the node | Custom networking, below |
| `ENABLE_POD_ENI` | Enable branch ENIs for security groups for Pods | Only where per-Pod security groups are genuinely required |
| `AWS_VPC_K8S_CNI_EXTERNALSNAT` | Disable source NAT for Pod traffic leaving the VPC | When Pods must present their own IP to an on-premises network |

!!! tip "`WARM_IP_TARGET` is the knob that fixes 'we have IPs but Pods cannot get one'"

    By default the CNI allocates whole ENIs' worth of addresses at a time, so a node running three Pods may hold thirty addresses. In a constrained VPC this silently exhausts the subnet. Setting `WARM_IP_TARGET` (with `MINIMUM_IP_TARGET` to avoid thrash) makes allocation demand-driven. The cost is more `AssignPrivateIpAddresses` API calls during scale-out, which can hit EC2 API rate limits on very large clusters  a real trade, and one to make consciously.

### Custom networking and IPv6: the two structural answers to IP exhaustion

**Custom networking** places Pods in *different subnets from their nodes*  typically a secondary CIDR block added to the VPC from the `100.64.0.0/10` carrier-grade NAT range, which does not consume routable RFC 1918 space. Nodes keep small routable subnets; Pods get an enormous non-routable range. The costs are real: the node's primary ENI can no longer host Pods, so maximum Pods per node drops by roughly one ENI's worth, and every node needs an `ENIConfig` custom resource per Availability Zone.

**IPv6 clusters** eliminate the problem rather than managing it. Each Pod gets a globally unique IPv6 address from a `/80` per node; the address space is effectively unlimited. Egress to IPv4 endpoints works through NAT64 and DNS64 with an egress-only internet gateway. The cost is that **IPv6 must be chosen at cluster creation and cannot be changed**, and every dependency  application libraries, on-premises networks, third-party endpoints  must cope with IPv6.

| Approach | Address space gained | Cost | Reversible? |
|---|---|---|---|
| Prefix delegation | 16× density per node | `/28` granularity, fragmentation sensitivity | Yes, per cluster setting |
| Larger subnets | Linear | Requires VPC redesign or a new VPC | Only by rebuilding |
| Custom networking with `100.64.0.0/10` | Very large | Complexity; lower max Pods; per-AZ `ENIConfig` | Yes, with node replacement |
| IPv6 | Effectively unlimited | Whole-stack IPv6 readiness | **No**  cluster creation time only |

### Security groups for Pods

By default all Pods on a node share the node's security groups, which means security group rules cannot distinguish one workload from another. **Security groups for Pods** solves this with **branch ENIs**: on Nitro instances with `ENABLE_POD_ENI=true`, the VPC Resource Controller attaches a trunk ENI to the node and allocates branch interfaces to individual Pods, each with its own security groups, selected by a `SecurityGroupPolicy` custom resource.

This is the mechanism that lets you say "only the `payments` Pods may reach the payments database" using an RDS security group rule rather than a network policy. It is genuinely useful and genuinely expensive: branch ENIs consume a separate per-instance quota, they reduce the node's Pod capacity, and Pods using them take longer to start. Reserve it for the boundaries that must be enforced in the VPC rather than in the cluster.

### Services, kube-proxy, and CoreDNS

```mermaid
flowchart TD
    P["Pod calls http://orders.default.svc.cluster.local:8080"] --> DNS["CoreDNS resolves the name to the Service ClusterIP 172.20.14.9"]
    DNS --> PKT["Pod sends a packet to 172.20.14.9:8080"]
    PKT --> KP["kube-proxy rules on the node (iptables by default) match the ClusterIP"]
    KP --> DNAT["DNAT to one healthy backing Pod IP, chosen at random"]
    DNAT --> POD["10.0.2.77:8080  a real VPC address, routed natively"]
    EP["EndpointSlice controller keeps the eligible backend list current from readiness probes"] --> KP
```

The ClusterIP is a **virtual address that exists only as a packet-rewriting rule** on every node; nothing listens on it. This explains several otherwise puzzling behaviours: you cannot ping a ClusterIP meaningfully, a Service with no ready endpoints black-holes traffic rather than refusing it, and `kube-proxy` being unhealthy on one node breaks Service resolution for Pods on that node only.

| Service type | What it creates | Use |
|---|---|---|
| `ClusterIP` | An internal virtual IP | Default; internal service-to-service traffic |
| `NodePort` | A port on every node forwarding to the Service | Rarely used directly; the substrate for instance-mode load balancing |
| `LoadBalancer` | An AWS load balancer via a controller | External exposure of a single Service |
| `ExternalName` | A CNAME in cluster DNS | Pointing a cluster name at an external endpoint |
| **Ingress** (not a Service type) | An ALB via the AWS Load Balancer Controller | HTTP routing for many Services behind one load balancer |

### The AWS Load Balancer Controller and target modes

The in-tree cloud provider creates a Classic Load Balancer for `type: LoadBalancer`, which is a legacy path. In practice you install the **AWS Load Balancer Controller**, which creates an **ALB** for Ingress resources and an **NLB** for annotated Services, and which supports two target modes:

| Target mode | Registers | Path | Consequences |
|---|---|---|---|
| **Instance mode** | Node instance IDs on a NodePort | Load balancer → node → `kube-proxy` → possibly another node → Pod | An extra hop, possible cross-AZ charges, source IP obscured unless preserved; works everywhere |
| **IP mode** | **Pod IP addresses directly** | Load balancer → Pod | One less hop, lower latency, true client IP with the right settings, required on Fargate |

!!! tip "IP mode is the modern default, and it is only possible because of the VPC CNI"

    A load balancer can register a Pod as a target only because that Pod holds a real VPC IP address. This is the clearest example of the VPC CNI's cost being repaid: the same decision that constrains Pod density is what removes a network hop from every external request and makes Pod-level security groups possible. When a question asks why you would accept the IP-planning burden of the VPC CNI, this is the answer.

### Cross-AZ traffic, and why it appears on the bill

Kubernetes Services select endpoints without regard to topology: a Pod in `us-east-1a` calling a Service with replicas in three zones sends roughly two thirds of its traffic across an Availability Zone boundary, and AWS charges for inter-AZ data transfer in both directions. Two mechanisms address this:

- **Topology aware routing** (the `service.kubernetes.io/topology-mode: Auto` annotation, formerly topology aware hints) asks EndpointSlice to prefer same-zone endpoints when the distribution allows it safely.
- **`internalTrafficPolicy: Local`** restricts a Service to endpoints on the *same node*, which eliminates the traffic entirely but breaks if no local endpoint exists.

Both trade availability for cost and latency: preferring local endpoints concentrates load and, in the `Local` case, fails closed. Use topology aware routing for chatty internal services with replicas in every zone, and leave it off for services whose replica count is small enough that zone skew would overload one zone.

---

## Core Concepts: EKS Security and IAM Integration

### The two-layer model

This is the concept students get wrong most often, and it is simple once stated:

```mermaid
sequenceDiagram
    participant U as "Engineer running kubectl"
    participant CLI as "aws eks get-token"
    participant API as "EKS API server"
    participant AUTH as "AWS IAM Authenticator webhook"
    participant IAM as "AWS IAM / STS"
    participant RBAC as "Kubernetes RBAC"
    U->>CLI: "kubectl reads kubeconfig and invokes the exec credential plugin"
    CLI->>CLI: "build a pre-signed SigV4 STS GetCallerIdentity URL, base64 it as a bearer token"
    CLI-->>U: "token, valid ~15 minutes"
    U->>API: "HTTPS request with Authorization: Bearer k8s-aws-v1...."
    API->>AUTH: "webhook TokenReview"
    AUTH->>IAM: "execute the pre-signed request: who signed this?"
    IAM-->>AUTH: "arn:aws:iam::111122223333:role/DeveloperRole"
    AUTH->>AUTH: "look up the access entry (or aws-auth) for that ARN"
    AUTH-->>API: "authenticated as user X in groups [developers]"
    Note over API,RBAC: "AUTHENTICATION is now complete. Nothing has been authorized."
    API->>RBAC: "may user X in group developers perform 'list pods' in namespace 'prod'?"
    RBAC-->>API: "RoleBindings and ClusterRoleBindings decide"
    API-->>U: "200 with the Pod list, or 403 Forbidden"
```

**IAM answers 'who are you'. Kubernetes RBAC answers 'what may you do'.** An IAM administrator with no access entry is authenticated as nobody and receives `Unauthorized`. A mapped user with no RoleBinding is authenticated and receives `Forbidden`. The two error messages are the diagnostic:

| Symptom | Layer at fault | Fix |
|---|---|---|
| `error: You must be logged in to the server (Unauthorized)` | Authentication  no access entry or `aws-auth` mapping for this principal | Create an access entry for the IAM principal |
| `Error from server (Forbidden): pods is forbidden: User "x" cannot list resource "pods"` | Authorization  mapped, but no RBAC grant | Bind a Role or ClusterRole, or associate an access policy |

!!! danger "The cluster creator is not special, and that has ended many lab sessions"

    The IAM principal that creates a cluster is granted `system:masters` implicitly, and **that grant is invisible in `aws-auth`**. If you create a cluster with a CI/CD role and then try `kubectl` as a human, you are `Unauthorized` with no obvious cause. Worse, if that creator principal is deleted without another admin being mapped, the cluster can become permanently unadministrable. Always create an explicit second cluster-admin access entry immediately after cluster creation  ideally a role assumable by a group of humans, not a single user.

### Access entries versus the `aws-auth` ConfigMap

Historically, mapping IAM principals to Kubernetes identities meant editing a ConfigMap in `kube-system`  a resource you could only edit if you already had access, whose syntax errors could lock everyone out, and which was invisible to IAM tooling and CloudTrail. **Access entries** replace it with a first-class EKS API, with a catalogue of managed access policies (the general-purpose four below, plus policies for hybrid nodes, Auto Mode, and other specific roles).

| | `aws-auth` ConfigMap | Access entries |
|---|---|---|
| Managed via | `kubectl edit` inside the cluster | EKS API, CLI, CloudFormation, Terraform |
| Failure mode | A YAML mistake locks everyone out | API validation; no lockout |
| Auditable in CloudTrail | No | Yes |
| Namespace scoping | Only via RBAC you author | Built in, through access scopes |
| Prebuilt permission sets | None | A managed catalogue of roughly two dozen, of which the general-purpose four are `AmazonEKSClusterAdminPolicy`, `AmazonEKSAdminPolicy`, `AmazonEKSEditPolicy`, and `AmazonEKSViewPolicy` |

The cluster's **authentication mode** selects which is active: `CONFIG_MAP` (legacy), `API_AND_CONFIG_MAP` (both, for migration), or `API` (access entries only, the modern default). The transition is one-way: once access entries are enabled they cannot be disabled, and a cluster created without ConfigMap support cannot add it later.

### Pod identity: why the node role is not enough

A Pod that needs to call `s3:GetObject` must present AWS credentials. Three mechanisms exist, and only two are acceptable:

**The node instance role (unacceptable).** Every Pod on a node can reach the instance metadata service and obtain the node's role credentials. The node role therefore accumulates the union of every workload's permissions, and any compromised Pod  or any Pod with a server-side request forgery bug  inherits all of them. This is the single most consequential misconfiguration in EKS security.

**IAM Roles for Service Accounts (IRSA).** The cluster exposes an OIDC discovery endpoint; you register it as an IAM OIDC identity provider. A mutating webhook in the control plane injects a **projected service account token** (a short-lived, audience-scoped JWT) into any Pod whose ServiceAccount carries an `eks.amazonaws.com/role-arn` annotation, along with the `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` environment variables. The AWS SDK finds them and calls `sts:AssumeRoleWithWebIdentity`. The role's trust policy names the OIDC provider and constrains the `sub` claim to a specific namespace and ServiceAccount.

**EKS Pod Identity.** A newer mechanism that removes the OIDC plumbing. You install the **EKS Pod Identity Agent** add-on (a DaemonSet), then create an **association** through the EKS API binding a ServiceAccount in a namespace to an IAM role. The agent serves credentials to the Pod over a link-local endpoint. The role's trust policy names `pods.eks.amazonaws.com` and requires `sts:AssumeRole` and `sts:TagSession`  and, critically, the same role can be reused across many clusters without editing its trust policy for each one.

```mermaid
flowchart TD
    subgraph IRSA["IRSA: OIDC federation"]
        A1["ServiceAccount annotated with eks.amazonaws.com/role-arn"] --> A2["Pod Identity Webhook injects a projected token and env vars"]
        A2 --> A3["SDK calls sts:AssumeRoleWithWebIdentity with the JWT"]
        A3 --> A4["Trust policy validates the OIDC issuer and the sub claim"]
        A4 --> A5["Temporary credentials"]
    end
    subgraph PI["EKS Pod Identity"]
        B1["Pod Identity Agent DaemonSet on each node"] --> B2["EKS API association: cluster + namespace + ServiceAccount to role"]
        B2 --> B3["Agent serves credentials on a link-local endpoint"]
        B3 --> B4["Trust policy names pods.eks.amazonaws.com; sts:AssumeRole and sts:TagSession"]
        B4 --> B5["Temporary credentials, with session tags for the cluster and namespace"]
    end
```

| | IRSA | EKS Pod Identity |
|---|---|---|
| Per-cluster setup | An IAM OIDC provider per cluster | Install one add-on |
| Role reuse across clusters | Trust policy must list every cluster's OIDC issuer | One trust policy works for all |
| Trust policy complexity | Issuer URL plus `sub` and `aud` conditions | Service principal plus session tag conditions |
| Works on AWS Fargate | Yes | **No**  the agent is a DaemonSet, and Fargate has no DaemonSets |
| Works outside EKS (ECS, EC2, on-premises) | The pattern generalises to any OIDC provider | EKS-specific |
| Role chaining and session tags | Limited | Supported; tags carry cluster, namespace and ServiceAccount |
| Recommendation | Still required for Fargate Pods and for portability | **Prefer for new work on EC2-backed nodes** |

!!! danger "Block the instance metadata service, or per-Pod identity is decorative"

    IRSA and Pod Identity give each Pod its own role  and change nothing at all if a Pod can still reach `169.254.169.254` and take the node's role instead. The remediation is to require IMDSv2 with `HttpPutResponseHopLimit: 1` on every node (which stops a container, one network hop away, from reaching it) or to block the address with a network policy. This one setting is the difference between a per-Pod identity model and a per-Pod identity theatre.

### Kubernetes Secrets, KMS, and the honest limitation

Kubernetes Secrets are **base64-encoded, not encrypted**, in `etcd`. EKS encrypts `etcd` volumes at rest by default, and you can additionally enable **envelope encryption with AWS KMS**, so that each Secret's data key is encrypted by a customer-managed key. This protects against a compromise of the storage layer and gives you an auditable, revocable key.

What it does **not** protect against is anyone with `get secrets` RBAC permission, or any Pod that mounts the Secret. For credentials that must not be visible to cluster administrators, or that must rotate automatically, the answer is **AWS Secrets Manager or Parameter Store** with the **Secrets Store CSI Driver**, which mounts the value into the Pod at runtime under an IRSA or Pod Identity role.

!!! warning "Deleting or disabling the KMS key destroys the cluster"

    Envelope encryption ties the cluster's Secrets to a KMS key. If that key is scheduled for deletion or its policy is changed so the cluster can no longer use it, every Secret becomes unreadable and the cluster is unrecoverable. Protect the key with a resource policy that prevents deletion, and keep it in the same account and Region as the cluster.

### Network policies, Pod Security Admission, and audit logging

**Network policies** are the Kubernetes-native answer to Pod-level segmentation. By default, all Pods can reach all other Pods; a NetworkPolicy selecting a set of Pods switches them to default-deny for the directions it specifies. Enforcement requires a plugin: the **VPC CNI supports network policies natively** (using eBPF) when enabled, and Calico is the common alternative. Network policies and security groups for Pods solve overlapping problems at different layers  policies are cheap, expressive and cluster-scoped; security groups are enforced in the VPC and visible to non-Kubernetes tooling.

**Pod Security Admission** replaced the removed PodSecurityPolicy. It applies one of three profiles  `privileged`, `baseline`, `restricted`  per namespace, in one of three modes (`enforce`, `audit`, `warn`), via namespace labels. The practical baseline for a production cluster is `restricted` enforced in application namespaces, with explicit exceptions for the namespaces that genuinely need privilege.

**Control plane logging** ships five log types to CloudWatch Logs: `api`, `audit`, `authenticator`, `controllerManager`, and `scheduler`. The **audit log is the one that matters for security**: it records every API request, its authenticated identity, and its outcome. It is off by default, it is not free, and it is the only record of who did what inside the cluster  CloudTrail records the EKS API calls, not the Kubernetes ones.

---

## Architecture Components

| Component | Responsibility in an EKS architecture |
|---|---|
| **EKS cluster** | The managed control plane: API endpoint, `etcd`, scheduler, controllers, authenticator |
| **Cluster service role** | The IAM role EKS assumes to manage AWS resources on your behalf (ENIs, load balancers, logs) |
| **Cluster security group** | Applied to control plane ENIs and managed nodes; the default all-within-itself rule is what makes the cluster work |
| **Cross-account ENIs** | The control plane's inbound path into your VPC |
| **Cluster endpoint** | The API server's DNS name; public, public and private, or private only |
| **VPC and subnets** | At least two subnets in two AZs; private subnets for nodes; public subnets, or tags, for internet-facing load balancers |
| **Node instance role** | The IAM role assumed by the `kubelet`; needs `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly`, and CNI permissions |
| **Managed node group** | An EKS-managed Auto Scaling group with AWS-published AMIs and cordon-and-drain upgrades |
| **Karpenter** | A just-in-time node provisioner that creates right-sized, diverse instances directly from unschedulable Pods |
| **Fargate profile** | A selector that routes matching Pods onto AWS-managed serverless capacity |
| **EKS Auto Mode** | AWS management of compute, networking, storage, and load balancing in the data plane |
| **`kubelet`** | The node agent: registration, Pod lifecycle, probes, status reporting |
| **`kube-proxy`** | Programs `iptables`, IPVS, or `nftables` rules that implement Service virtual IPs |
| **`containerd`** | The container runtime |
| **Amazon VPC CNI (`aws-node`)** | Allocates VPC IPs to Pods; also the native network policy enforcement point |
| **CoreDNS** | Cluster DNS: Service and Pod name resolution |
| **AWS Load Balancer Controller** | Turns Ingress into ALBs and annotated Services into NLBs; IP-mode targeting |
| **EBS/EFS/FSx CSI drivers** | Turn PersistentVolumeClaims into AWS storage |
| **EKS Pod Identity Agent** | Serves per-Pod IAM credentials from an EKS association |
| **IAM OIDC provider** | The federation endpoint that makes IRSA possible |
| **Metrics Server** | Supplies CPU and memory metrics to the HorizontalPodAutoscaler |
| **Cluster Autoscaler** | Adjusts Auto Scaling group sizes in response to unschedulable Pods (the alternative to Karpenter) |
| **Amazon ECR** | The image registry the `kubelet` pulls from, authenticated by the node role |
| **AWS KMS** | Envelope encryption of Kubernetes Secrets; EBS volume encryption |
| **CloudWatch Logs** | Destination for the five control plane log types and for container logs |
| **AWS CloudTrail** | Audit of EKS API calls (cluster creation, node groups, access entries)  not of Kubernetes API calls |
| **Amazon GuardDuty** | EKS Protection: audit log analysis and runtime monitoring |

Read architecturally, these fall into three groups. **The boundary components**  the endpoint, the cross-account ENIs, the cluster security group, the node role  determine whether the cluster works at all, and are where most outages originate. **The data plane components**  nodes, CNI, `kube-proxy`, CoreDNS, CSI drivers  determine whether workloads run and are yours to keep current. **The integration components**  the load balancer controller, IRSA and Pod Identity, KMS, CloudWatch  determine how much of AWS your Kubernetes objects can reach, and are where the portability trade is actually made.

---

## AWS Service Deep Dive

!!! warning "On numbers, versions, and quotas"

    Figures are representative as of 2026 and most quotas are **soft**. Kubernetes versions, add-on versions, and instance ENI limits change frequently. Verify against AWS Service Quotas, the EKS User Guide, and the Kubernetes version calendar for the account and Region you are designing in. Prices below are indicative and stated only to show relative magnitude.

### Amazon EKS control plane

**Purpose.** Provide a highly available, single-tenant, upstream-conformant Kubernetes control plane without any operational involvement from the customer.

**Architecture.** At least two `kube-apiserver` instances and three `etcd` instances distributed across three Availability Zones in an AWS-owned VPC, fronted by a network load balancer that serves the cluster endpoint. The scheduler, controller manager, cloud controller manager, and IAM Authenticator webhook run alongside. Cross-account ENIs in your subnets give the control plane an inbound path to your workloads.

**Important features.** Upstream-conformant Kubernetes; automatic patching within a platform version; single-command minor version upgrades; five control plane log types to CloudWatch; envelope encryption of Secrets with KMS; three endpoint access modes with CIDR allow-listing; access entries with managed access policies; native IAM authentication; an API server endpoint availability SLA.

**Limitations.** You cannot access `etcd` directly, take your own `etcd` backup, or run a custom admission controller *inside* the control plane (webhooks run in your cluster instead). API server flags are not freely configurable, though advanced control plane configuration options have expanded. Cluster version upgrades proceed **one minor version at a time**; EKS supports rolling a control plane back one minor version only within a short window after the upgrade, and nodes and add-ons must be rolled back separately, so an upgrade should be planned as effectively one-way. A cluster's VPC, subnets used for the control plane ENIs, IP family (IPv4 or IPv6), and Secrets-encryption choice are set at creation.

**Pricing model.** A flat fee per cluster per hour  indicatively **$0.10 per hour** for a version in standard support, rising to about **$0.60 per hour** for a version in extended support  independent of cluster size, plus the data plane resources you consume. The extended-support premium is a deliberate, six-fold economic incentive to keep clusters current.

**Performance characteristics.** The API server scales with load, managed by AWS. Practical limits are reached through very high object counts, very large objects, chatty controllers, and unbounded `list` calls rather than through node count. `etcd` has a hard total database size limit; clusters that store large ConfigMaps or huge numbers of Secrets can approach it.

**Scaling behaviour.** AWS adjusts control plane capacity in response to observed load. There is no customer-facing knob and no charge for the scaling.

**Availability.** Multi-AZ by construction, with automatic replacement of unhealthy instances, and an availability SLA on the API server endpoint. A control plane impairment prevents changes but does not stop running Pods.

**Security features.** IAM authentication; RBAC authorization; access entries with managed policies; KMS envelope encryption for Secrets; encrypted `etcd` volumes; audit logging; private endpoints; endpoint CIDR allow-lists; single-tenant isolation.

**Service limits.** Representative soft quotas per account and Region: clusters per account, managed node groups per cluster, nodes per managed node group, Fargate profiles per cluster and selectors per profile, access entries per cluster. Kubernetes itself has practical limits  commonly cited as around 5,000 nodes and 150,000 Pods per cluster  which are architectural guidance rather than enforced ceilings.

**Common configurations.** Public and private endpoint access with a CIDR allow-list; API authentication mode with access entries; all five control plane log types enabled in production, or at minimum `audit` and `authenticator`; Secrets encryption with a customer-managed KMS key; three private subnets across three AZs.

### The Amazon VPC CNI

**Purpose.** Give every Pod a routable VPC IP address so Pods are first-class VPC citizens.

**Architecture.** The `aws-node` DaemonSet runs `ipamd` (the IP address manager) and the CNI binary. `ipamd` attaches ENIs to the instance and requests secondary IP addresses or `/28` prefixes, maintaining a warm pool; the binary wires each Pod's network namespace to an address from that pool with a veth pair and host routes.

**Important features.** Native VPC addressing with no encapsulation; prefix delegation for high density; custom networking to place Pods in separate subnets; security groups for Pods via branch ENIs on Nitro instances; IPv6 support; native network policy enforcement using eBPF; extensive warm-pool tuning.

**Limitations.** Pod density is bounded by instance ENI and IP limits. Address consumption is aggressive by default. Prefix delegation requires contiguous free `/28` blocks and Nitro instances. Custom networking reduces maximum Pods and requires per-AZ configuration. Security groups for Pods consume a separate branch-ENI quota and slow Pod start-up. IPv6 is a cluster-creation-time decision.

**Pricing model.** No charge for the plugin. The cost is indirect: consumed VPC addresses, ENI attachment limits shaping instance choice, and the cross-AZ data transfer that native routing makes visible.

**Performance characteristics.** No encapsulation overhead, so Pod-to-Pod throughput approaches instance network performance. Pod start-up includes an IP assignment that is usually instant from the warm pool and can take seconds when a new ENI must be attached.

**Scaling behaviour.** The warm pool grows and shrinks with Pod density on the node, subject to `WARM_ENI_TARGET`, `WARM_IP_TARGET`, `MINIMUM_IP_TARGET`, and `WARM_PREFIX_TARGET`. Very large clusters can encounter EC2 API rate limits during mass scale-out.

**Availability.** Runs as a DaemonSet; a failed `aws-node` Pod makes its node `NotReady`, which is severe but node-local.

**Security features.** Security groups for Pods; native network policy enforcement; Pod traffic visible in VPC Flow Logs; source NAT control for traffic leaving the VPC.

**Common configurations.** Prefix delegation enabled; `WARM_IP_TARGET` and `MINIMUM_IP_TARGET` set in IP-constrained VPCs; custom networking with a `100.64.0.0/10` secondary CIDR in large clusters; network policy enforcement enabled; managed as an EKS add-on with a defined version and an IRSA or Pod Identity role.

### EKS identity integration

**Purpose.** Make AWS IAM the authentication source for cluster access, and give individual Pods their own least-privilege IAM roles.

**Architecture.** The IAM Authenticator webhook inside the control plane validates a pre-signed SigV4 STS token and resolves it to a Kubernetes username and groups using access entries (or the legacy `aws-auth` ConfigMap). For workloads, IRSA federates through a per-cluster OIDC provider and `sts:AssumeRoleWithWebIdentity`, while EKS Pod Identity uses a DaemonSet agent plus an EKS-managed association and `sts:AssumeRole`.

**Important features.** Access entries with managed access policies  a catalogue of roughly two dozen, of which `AmazonEKSClusterAdminPolicy`, `AmazonEKSAdminPolicy`, `AmazonEKSEditPolicy`, and `AmazonEKSViewPolicy` are the general-purpose set  and namespace-scoped access scopes; three cluster authentication modes; IRSA with fine-grained trust policy conditions on `sub` and `aud`; EKS Pod Identity with cross-cluster role reuse and session tags; automatic access entries for managed node groups and Fargate profiles.

**Limitations.** EKS Pod Identity does not work on Fargate. IRSA requires an OIDC provider per cluster and a trust policy edit per cluster. Neither prevents a Pod from using the node role unless IMDS access is restricted. Access entries cannot be disabled once enabled. RBAC remains a separate system that IAM cannot see: an IAM administrator is not a cluster administrator.

**Pricing model.** No charge. STS calls are not billed at any material rate.

**Security features.** Per-Pod least privilege; short-lived credentials with automatic rotation; auditable role assumption in CloudTrail; session tags identifying cluster, namespace, and ServiceAccount under Pod Identity; namespace-scoped cluster access without hand-written RBAC.

**Common configurations.** `API` authentication mode; a cluster-admin access entry for a human-assumable role created immediately after the cluster; `AmazonEKSViewPolicy` scoped to namespaces for most engineers; Pod Identity for EC2-backed workloads, IRSA for Fargate workloads; IMDSv2 with a hop limit of 1 on all nodes.

---

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **Control plane** | The Kubernetes management components AWS runs for you: API server, `etcd`, scheduler, controller managers |
| **Data plane** | The nodes and Pods in your VPC that actually run workloads |
| **`kube-apiserver`** | The front door to the cluster; the only component that talks to `etcd` |
| **`etcd`** | The consistent key-value store holding all cluster state; three instances across three AZs on EKS |
| **`kube-scheduler`** | Assigns unscheduled Pods to nodes by filtering then scoring |
| **`kube-controller-manager`** | Runs the built-in reconciliation loops (Deployment, ReplicaSet, Node, Job, and others) |
| **`cloud-controller-manager`** | The AWS-specific loops: node lifecycle, Service load balancers, routes |
| **`kubelet`** | The node agent that registers the node and runs Pods |
| **`kube-proxy`** | Programs node packet-forwarding rules implementing Service virtual IPs |
| **`containerd`** | The container runtime EKS-optimized AMIs use |
| **Cluster endpoint** | The API server's DNS name; public, public and private, or private only |
| **Platform version** | An EKS-internal version identifier for control plane patches within a Kubernetes minor version |
| **Standard support** | The period (about 14 months) during which a Kubernetes version is supported at the base cluster price |
| **Extended support** | The additional period (about 12 months) at a substantially higher per-cluster price |
| **Cross-account ENI** | A network interface EKS creates in your subnets to give the control plane an inbound path |
| **Cluster security group** | The EKS-created security group applied to control plane ENIs and managed nodes |
| **Node instance role** | The IAM role assumed by the `kubelet`, granting cluster registration and ECR pull |
| **Cluster service role** | The IAM role EKS assumes to manage AWS resources on your behalf |
| **Pod execution role** | The IAM role the Fargate `kubelet` uses; trusted by `eks-fargate-pods.amazonaws.com` |
| **Managed node group** | An EKS-managed Auto Scaling group with AWS AMIs and cordon-and-drain upgrades |
| **Self-managed node** | An EC2 instance you bootstrap and upgrade yourself |
| **EKS-optimized AMI** | AWS-published node image with `kubelet`, `containerd`, the CNI, and the bootstrap tooling |
| **`nodeadm` / `NodeConfig`** | The AL2023 node bootstrap mechanism that replaced the older `bootstrap.sh` user data |
| **Karpenter** | A just-in-time node provisioner that launches right-sized instances from pending Pods |
| **Cluster Autoscaler** | The older node autoscaler that adjusts Auto Scaling group desired capacity |
| **EKS Auto Mode** | A mode in which AWS manages compute, networking, storage, and load balancing in the data plane |
| **Fargate profile** | A namespace and label selector routing matching Pods onto AWS-managed serverless capacity |
| **Hybrid Nodes** | On-premises or edge nodes joined to an EKS control plane, priced per vCPU |
| **Amazon VPC CNI** | The default networking plugin; assigns real VPC IPs to Pods |
| **`ipamd`** | The IP address manager inside `aws-node` that maintains the node's warm IP pool |
| **Warm pool** | Pre-allocated IP addresses or prefixes held so Pod start-up does not wait on an EC2 API call |
| **Prefix delegation** | Allocating `/28` prefixes instead of single IPs, multiplying Pod density by up to 16 |
| **Custom networking** | Placing Pods in different subnets from their nodes, via per-AZ `ENIConfig` resources |
| **Branch ENI** | A per-Pod network interface enabling security groups for Pods on Nitro instances |
| **`SecurityGroupPolicy`** | The custom resource that selects Pods and assigns them security groups |
| **`max_pods`** | The `kubelet`'s Pod ceiling on a node, derived from ENI and IP limits |
| **ClusterIP** | A virtual Service address implemented purely as packet-rewriting rules; nothing listens on it |
| **EndpointSlice** | The object holding the current set of ready Pod endpoints behind a Service |
| **CoreDNS** | Cluster DNS resolving Service and Pod names |
| **Ingress** | An HTTP routing object realised on EKS as an ALB by the AWS Load Balancer Controller |
| **AWS Load Balancer Controller** | The controller that creates ALBs for Ingress and NLBs for annotated Services |
| **Instance mode** | Target group registration by node and NodePort |
| **IP mode** | Target group registration by Pod IP; fewer hops, required on Fargate |
| **Topology aware routing** | EndpointSlice hints that prefer same-zone endpoints to cut cross-AZ traffic |
| **`internalTrafficPolicy: Local`** | Restricts a Service to endpoints on the same node |
| **Access entry** | An EKS API object mapping an IAM principal to a Kubernetes identity |
| **Access policy** | A managed permission set (`ClusterAdmin`, `Admin`, `Edit`, `View`) associated with an access entry |
| **Access scope** | The cluster-wide or namespace-limited scope of an associated access policy |
| **Authentication mode** | `CONFIG_MAP`, `API_AND_CONFIG_MAP`, or `API`; selects access entries, `aws-auth`, or both |
| **`aws-auth` ConfigMap** | The legacy in-cluster IAM mapping mechanism |
| **AWS IAM Authenticator** | The control plane webhook that validates SigV4 tokens and resolves them to cluster identities |
| **RBAC** | Kubernetes authorization: Roles, ClusterRoles, RoleBindings, ClusterRoleBindings |
| **IRSA** | IAM Roles for Service Accounts: OIDC federation giving a Pod an IAM role |
| **OIDC provider** | The IAM identity provider registered from the cluster's OIDC issuer URL |
| **Projected service account token** | A short-lived, audience-scoped JWT mounted into a Pod for federation |
| **EKS Pod Identity** | The newer per-Pod IAM mechanism using an agent DaemonSet and an EKS association |
| **Pod Identity Agent** | The DaemonSet serving credentials to Pods over a link-local endpoint |
| **IMDSv2** | The session-oriented instance metadata service; a hop limit of 1 blocks container access |
| **Envelope encryption** | KMS-backed encryption of Kubernetes Secrets on top of `etcd` volume encryption |
| **Secrets Store CSI Driver** | Mounts AWS Secrets Manager or Parameter Store values into Pods at runtime |
| **NetworkPolicy** | Kubernetes-native Pod-level network segmentation, enforced by the VPC CNI or Calico |
| **Pod Security Admission** | Namespace-labelled enforcement of the `privileged`, `baseline`, or `restricted` profiles |
| **Control plane logging** | The five CloudWatch log types: `api`, `audit`, `authenticator`, `controllerManager`, `scheduler` |
| **EKS add-on** | An AWS-managed, versioned deployment of a cluster component such as the CNI or CoreDNS |
| **`eksctl`** | The community CLI that creates clusters and their supporting AWS resources declaratively |

---

## Configuration Options

### Cluster-level configuration

| Setting | Options | How to decide |
|---|---|---|
| **Kubernetes version** | Supported minor versions | Stay within standard support; the extended-support premium is roughly six times the base price |
| **Endpoint access** | Public, public and private, private only | Public and private with a CIDR allow-list for most production; private only where the network path for administration and CI is already solved |
| **Authentication mode** | `CONFIG_MAP`, `API_AND_CONFIG_MAP`, `API` | `API` for new clusters; `API_AND_CONFIG_MAP` only while migrating |
| **Secrets encryption** | None, or a KMS customer-managed key | Enable it, and protect the key from deletion; it cannot be added to a Secret already written without rewriting it |
| **Control plane logging** | Any of five types | `audit` and `authenticator` at minimum in production; all five while diagnosing |
| **IP family** | IPv4, IPv6 | **Creation-time only.** IPv6 when address exhaustion is a structural problem and the whole stack supports it |
| **Subnets** | At least two in two AZs | Three private subnets across three AZs; size them for Pod density, not node count |
| **Cluster service role** | An IAM role | Use the AWS-managed policy; do not add permissions it does not need |

### Data plane configuration

| Setting | Options | How to decide |
|---|---|---|
| **Node type** | Managed node group, self-managed, Fargate, Auto Mode, Karpenter, hybrid | Managed node groups as the baseline; Karpenter where scaling speed and packing matter; Fargate for isolation-sensitive or bursty namespaces |
| **Instance types** | Any | Check ENI limits against required Pod density, since the ENI formula above bounds each type |
| **`max_pods`** | Derived or overridden | Leave it derived unless prefix delegation is on; then confirm the `kubelet` sees the higher value |

AMI family, capacity type (On-Demand or Spot), instance diversity, labels and taints, and node disk are node group settings; see [3.3 Configuration Options](topic3.md#managed-node-groups) for their full treatment.

### VPC CNI configuration

| Setting | Default | Change it when |
|---|---|---|
| `ENABLE_PREFIX_DELEGATION` | `false` | Almost always, on Nitro instances: a large free density gain |
| `WARM_ENI_TARGET` | `1` | Lower to conserve addresses; raise for extreme Pod churn |
| `WARM_IP_TARGET` | unset | Set in IP-constrained VPCs to stop whole-ENI over-allocation |
| `MINIMUM_IP_TARGET` | unset | Pair with `WARM_IP_TARGET` to avoid allocation thrash |
| `ENABLE_POD_ENI` | `false` | Only where per-Pod security groups are genuinely required |
| `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG` | `false` | Custom networking with a secondary CIDR |
| `AWS_VPC_K8S_CNI_EXTERNALSNAT` | `false` | When Pods must present their own IP to on-premises networks |
| `ENABLE_NETWORK_POLICY` | `false` | When using native network policy enforcement instead of Calico |

### Identity configuration

| Setting | Options | How to decide |
|---|---|---|
| **Cluster access** | Access entries with managed policies, or custom RBAC | Managed policies with namespace access scopes cover most needs; author RBAC only for genuinely custom roles |
| **Workload identity** | Node role, IRSA, Pod Identity | Never the node role. Pod Identity for EC2-backed nodes; IRSA for Fargate and for portability |
| **IMDS** | IMDSv2 required, hop limit 1 or 2 | Hop limit **1** on every node, so containers cannot reach the metadata service |
| **Secrets** | Kubernetes Secrets, KMS envelope encryption, Secrets Manager via CSI | Envelope encryption always; Secrets Manager for anything that rotates or must be invisible to cluster admins |
| **Network policy** | None, VPC CNI native, Calico | Native enforcement as the default; default-deny per namespace as the target state |
| **Pod Security Admission** | `privileged`, `baseline`, `restricted` × `enforce`, `audit`, `warn` | `restricted` enforced in application namespaces, with named exceptions |

!!! tip "Three settings that are creation-time only, and therefore worth deciding slowly"

    **The IP family** (IPv4 or IPv6), **the VPC and the subnets used for control plane ENIs**, and **whether the `aws-auth` ConfigMap is available at all**. Everything else in this chapter can be changed later, sometimes disruptively. These three mean rebuilding the cluster, which in practice means a migration project. Spend the extra hour before `create-cluster`.

---

## Design Considerations

```mermaid
flowchart TD
    A["Do we need Kubernetes, or would ECS do?"] -->|"ecosystem, portability, platform-building"| B["EKS"]
    A -->|"simplest possible operation, AWS-only"| Z["Use ECS  Chapter 2"]
    B --> C{"How much of the data plane do we want to run?"}
    C -->|"as little as possible"| D["EKS Auto Mode, or Fargate profiles"]
    C -->|"real nodes, minimal AMI work"| E["Managed node groups"]
    C -->|"fast, dense, Spot-heavy scaling"| F["Managed node groups plus Karpenter"]
    E --> G{"Is the VPC address space adequate?"}
    F --> G
    D --> G
    G -->|"tight"| H["Prefix delegation, then WARM_IP_TARGET, then custom networking with 100.64.0.0/10"]
    G -->|"structurally inadequate"| I["IPv6 cluster  creation-time decision"]
    G -->|"adequate"| J["Standard VPC CNI"]
    H --> K{"How is the cluster administered?"}
    I --> K
    J --> K
    K -->|"from the internet"| L["Public and private endpoint, CIDR allow-list, access entries"]
    K -->|"regulated, no internet path"| M["Private-only endpoint plus a bastion, VPN, or in-VPC runners"]
    L --> N["Pod Identity or IRSA for every workload; IMDS hop limit 1; PSA restricted; default-deny network policies"]
    M --> N
```

| Quality | What it means here | Design levers | The trade-off you accept |
|---|---|---|---|
| **Availability** | Surviving an AZ failure and a control plane impairment | Three AZs, `topologySpreadConstraints`, PodDisruptionBudgets, multiple replicas, no API dependency on the request path | Spreading costs cross-AZ data transfer; PDBs can block node upgrades |
| **Scalability** | Adding capacity fast enough and far enough | Karpenter, prefix delegation, adequate subnets, HPA with the right metric | Faster scaling means more EC2 API calls and less bin-packing stability |
| **Security** | Least privilege at every layer | Per-Pod IAM, IMDS hop limit 1, PSA, network policies, private endpoint, audit logs | Every control adds friction; private endpoints add network engineering |
| **Cost** | Not paying for idle or duplicated capacity | Spot, Graviton, Karpenter consolidation, right-sized requests, topology aware routing, staying in standard support | Density concentrates risk; Spot adds interruption handling; consolidation churns Pods |
| **Operability** | What the team must understand and maintain | Managed node groups, EKS add-ons, Auto Mode, GitOps | Managed options reduce control; the more AWS runs, the less you can tune |
| **Portability** | How much of this runs elsewhere | Standard manifests, avoiding AWS-specific annotations where practical | Portability means giving up ALB Ingress, EBS storage classes, and IRSA  usually not worth it |
| **Latency** | Time from request to response, and from Pod scheduled to Pod ready | IP-mode targets, topology aware routing, small images, warm IP pools, node pre-provisioning | Every latency optimisation is capacity held idle or a hop removed at some cost |

!!! danger "Kubernetes upgrades are the recurring obligation people forget to design for"

    A Kubernetes minor version leaves standard support after roughly fourteen months, and the extended-support price is about six times higher. That means **a cluster must be upgraded roughly every year, one minor version at a time, and the upgrade is effectively one-way**  a control plane rollback is possible only within a short window after the upgrade, and nodes and add-ons must be reverted separately. Teams that do not plan for this end up either paying the extended-support premium indefinitely or performing a rushed multi-version upgrade under CVE pressure. Design the upgrade path  a non-production cluster that upgrades first, add-on versions pinned in IaC, deprecated API scanning in CI  on day one. The procedure itself is in [3.2 The cluster upgrade, in order](topic2.md#the-cluster-upgrade-in-order).

---

## AWS Best Practices

### Operational Excellence

Define the cluster, node groups, add-ons, and IAM in infrastructure as code  `eksctl` configuration files, CloudFormation, CDK, or Terraform  so a cluster can be rebuilt rather than repaired. Manage the core add-ons **as EKS add-ons with pinned versions** rather than as manifests you forgot you applied. Adopt GitOps (Argo CD or Flux) so the cluster's desired state is a Git repository and drift is visible. Run a non-production cluster one version ahead so upgrades are rehearsed rather than discovered. Enable control plane logging before you need it. Establish a node rotation cadence  managed node group updates or Karpenter drift and expiry  so nodes are cattle and the AMI is never a year old.

### Security

Use `API` authentication mode with access entries, and create a second cluster-admin access entry immediately after cluster creation so the cluster does not depend on one principal. Give every workload its own IAM role through Pod Identity or IRSA, and enforce IMDSv2 with a hop limit of 1 so the node role cannot be borrowed. Enable envelope encryption of Secrets with a customer-managed KMS key and protect that key from deletion. Run nodes in private subnets. Enable `audit` and `authenticator` control plane logs and ship them somewhere queryable. Apply Pod Security Admission at `restricted` in application namespaces. Adopt default-deny network policies namespace by namespace. Scan images in ECR and pin by digest. Enable GuardDuty EKS Protection for audit log analysis and runtime monitoring.

### Reliability

Spread across three Availability Zones and express it with `topologySpreadConstraints`, not hope. Set PodDisruptionBudgets so voluntary disruptions  node upgrades, Karpenter consolidation, drains  cannot take a service below its minimum. Define resource **requests** and **probes** correctly  the scheduler uses requests and only requests, and a Pod must not receive traffic before it can serve it (see [3.2 Requests, limits, and probes](topic2.md#requests-limits-and-probes-the-four-fields-that-decide-behaviour)). Run at least two replicas of everything that matters, including CoreDNS. Keep the four core add-ons current. Understand that a control plane impairment stops change but not traffic, and design so that nothing on the request path requires an API call.

### Performance Efficiency

Enable prefix delegation so nodes reach their compute capacity rather than their IP ceiling. Use IP-mode target groups so the load balancer talks to Pods directly. Use topology aware routing for chatty internal services. Right-size requests and limits from observed usage  over-requesting is the largest and least visible waste in most clusters. Keep images small, since every scale-out and every node replacement pays the pull. Use Graviton instances where the workload supports ARM, and Karpenter where scale-out latency matters (see [3.3](topic3.md#managed-node-groups-versus-karpenter-versus-auto-mode)).

### Cost Optimization

Stay in standard support; the extended-support premium is the easiest large saving in EKS. Consolidate small clusters where isolation requirements allow, because the per-cluster fee is charged whether the cluster runs one Pod or a thousand. Use Spot capacity above an On-Demand base for interruption-tolerant workloads, with several instance types for pool diversity. Let Karpenter consolidate under-utilised nodes. Right-size requests, because unused requested capacity is capacity you cannot schedule anything else onto. Reduce cross-AZ chatter with topology aware routing. Use Graviton. Tag nodes and namespaces so cost allocation is possible at all, and use Kubecost or AWS split cost allocation data to see per-namespace spend.

### Sustainability

The levers are the same as for cost, because both are functions of utilisation: right-sized requests, Karpenter consolidation, Graviton's better performance per watt, Spot capacity that uses otherwise-idle inventory, and scaling to a genuine floor overnight. Consolidating several under-utilised clusters into one  with namespaces and network policies providing the isolation  is often the single largest reduction available.

---

## Security Considerations

**The node role is the security boundary that fails first.** Without per-Pod identity and IMDS restrictions, every Pod on a node can assume the node's role. A public-facing service with a server-side request forgery bug then has whatever that role has  and the node role tends to accumulate permissions because it is the path of least resistance. The remediation is two settings: per-Pod identity through Pod Identity or IRSA, and `HttpPutResponseHopLimit: 1` with IMDSv2 required. Neither works without the other.

**Authentication and authorization are separate systems, and both need designing.** IAM decides who reaches the API server; RBAC decides what they may do. Grant IAM principals cluster access through access entries with the least-privilege managed policy and a namespace access scope. Reserve `AmazonEKSClusterAdminPolicy` for a break-glass role. Remember that `system:masters` cannot be restricted by RBAC  a principal in that group is unconditionally an administrator, which is why the implicit cluster-creator grant deserves attention.

**Admission control is where policy is actually enforced.** Pod Security Admission blocks privileged Pods, host networking, and host path mounts by namespace label. A policy engine (Kyverno, OPA Gatekeeper) extends this to organisational rules: required labels, disallowed registries, mandatory resource requests. Both run as part of the write path, which is why a policy engine's availability becomes a cluster-wide concern and why its `failurePolicy` is a deliberate decision.

**Network segmentation has two independent tools.** Network policies are Kubernetes-native, cheap, and expressive, enforced by the VPC CNI or Calico; they are the right default. Security groups for Pods enforce in the VPC itself, are visible to security tooling that does not understand Kubernetes, and are the right choice for a boundary that must hold against a compromised cluster  for example, restricting which Pods may reach a database.

**Secrets deserve more than base64.** Enable KMS envelope encryption. For anything that rotates or must not be readable by cluster administrators, use AWS Secrets Manager through the Secrets Store CSI Driver, with the Pod's own IAM role granting access to only its own secrets.

**Supply chain matters as much as runtime.** Scan images in ECR, pin by digest rather than by tag so the deployed bytes are the scanned bytes, restrict which registries the cluster may pull from with a policy engine, and keep node AMIs current through managed node group updates or Karpenter's drift detection.

!!! danger "`system:masters` is invisible to RBAC and to most audits"

    RBAC cannot limit a principal in the `system:masters` group; the API server short-circuits authorization for it. This means an `aws-auth` entry or access entry granting that group is an unrestricted grant that no Role or ClusterRole review will reveal. Audit for it explicitly, prefer `AmazonEKSClusterAdminPolicy` on a named break-glass role, and alarm on its use in the control plane audit log.

---

## Performance Optimization

**Remove the hop.** IP-mode target groups let the load balancer connect directly to Pods, eliminating the NodePort hop, the second `kube-proxy` translation, and the possible cross-AZ detour that instance mode introduces. This is usually the largest single latency improvement available to an EKS service, and it costs nothing.

**Stop paying for zone crossings you did not intend.** Topology aware routing keeps Service traffic in-zone when the endpoint distribution allows it. For very chatty internal calls it reduces both latency and the inter-AZ data transfer bill. Use it where replicas exist in every zone; avoid it where a small replica count would let one zone become overloaded.

**Make Pods start faster.** Pod start-up is image pull plus IP assignment plus container start plus probe success. Small images and a warm image cache dominate; a warm IP pool removes the ENI attachment wait; a correctly tuned `startupProbe` stops the `kubelet` killing a slow application while also not delaying readiness for a fast one.

**Make nodes appear faster, and right-size requests.** Node provisioning speed (Karpenter versus Cluster Autoscaler) is covered in [3.3](topic3.md#performance-optimization); how requests and limits drive scheduling and throttling is covered in [3.2](topic2.md#requests-limits-and-probes-the-four-fields-that-decide-behaviour). Over-requesting is the EKS-specific trap worth remembering here: nodes appear full while their CPU graphs are flat.

**Enable prefix delegation.** A node that could run 110 Pods and is capped at 29 is being wasted at four times its cost. This is one of the few settings that is free, large, and almost always right.

**Watch the control plane's own limits.** Very large clusters degrade through API server load: unbounded `list` calls from badly written controllers, huge numbers of Secrets or ConfigMaps, and chatty custom resources. Prefer watches and informers over polling, and paginate.

---

## Cost Optimization

| Lever | Mechanism | Caution |
|---|---|---|
| **Stay in standard support** | Upgrade annually | The extended-support price is roughly six times the base; this is usually the largest single saving |
| **Fewer, larger clusters** | Namespaces plus network policies for isolation | The per-cluster fee is fixed; but a shared cluster shares a blast radius and an upgrade schedule |
| **Prefix delegation** | One CNI setting | Turns IP-bound nodes into compute-bound nodes at no cost |
| **Topology aware routing** | An annotation | Reduces inter-AZ data transfer; can skew load with few replicas |
| **Delete idle clusters** | Governance | Development clusters left running are pure cost with a per-hour floor |

The data plane levers  Spot above an On-Demand base, Graviton, Karpenter consolidation, and Fargate for spiky workloads  are tabulated in [3.3 Cost Optimization](topic3.md#cost-optimization_1); right-sized requests and scheduled non-production scale-down are in [3.2 Cost Optimization](topic2.md#cost-optimization_1).

**The largest EKS cost mistakes are structural rather than tactical.** A fleet of twenty small clusters pays twenty control plane fees for work that three clusters could do. A cluster left on an unsupported version pays a six-fold premium indefinitely. And requests set to "whatever the example used" waste more capacity than any Spot strategy recovers, because they multiply across every replica of every service.

!!! tip "Measure per-namespace cost before optimising"

    Without cost visibility per namespace or team, optimisation is guesswork. AWS split cost allocation data for EKS, or Kubecost, attributes node cost to Pods by requested resources. This usually reveals that a small number of over-requesting workloads account for most of the waste  and it converts an abstract efficiency argument into a specific conversation with a specific team.

---

## Monitoring and Observability

| Signal | Source | What it tells you |
|---|---|---|
| **Control plane `audit` log** | CloudWatch Logs | Every Kubernetes API request with its identity and outcome; the only record of who did what in-cluster |
| **`authenticator` log** | CloudWatch Logs | Why an IAM principal was or was not mapped; the answer to most `Unauthorized` questions |
| **`apiserver_request_duration_seconds`** | Prometheus metrics from the API server | Control plane latency and saturation |
| **Node conditions** | `kubectl get nodes`, Container Insights | `NotReady`, `MemoryPressure`, `DiskPressure`, `PIDPressure`  the first place a node problem appears |
| **Pending Pods and their events** | `kubectl describe pod`, Container Insights | Insufficient CPU or memory, no matching node, or `failed to assign an IP address` |
| **`awscni_total_ip_addresses` / `awscni_assigned_ip_addresses`** | VPC CNI metrics | How close each node is to IP exhaustion  the metric most clusters do not have and need |
| **Subnet free IP count** | CloudWatch, VPC | Whether the cluster is approaching a structural address limit |
| **Unschedulable Pod duration** | Karpenter or Cluster Autoscaler metrics | How long capacity takes to appear  the number that matters for scale-out latency |
| **ALB `TargetResponseTime`, `UnHealthyHostCount`, 5xx** | CloudWatch | The user-facing view, and the deployment-failure signal |
| **Cross-AZ data transfer** | Cost Explorer, VPC Flow Logs | Whether topology-blind routing is costing real money |
| **CoreDNS request rate and errors** | CoreDNS metrics | DNS is the most common invisible cause of latency and intermittent failure in Kubernetes |
| **GuardDuty EKS findings** | GuardDuty | Suspicious API activity and runtime behaviour |
| **CloudTrail EKS events** | CloudTrail | Cluster, node group, add-on, and access entry changes  *not* Kubernetes API calls |

**Three dashboards worth building.** A **capacity dashboard** showing, per node group, allocatable versus requested CPU and memory *and* assigned versus total IP addresses  because on EKS you can run out of any of the three. A **control plane dashboard** showing API server latency and error rates alongside `audit` log volume. And a **workload dashboard** per service showing replica counts, restarts, probe failures, and the ALB metrics on one time axis; the workload-level signals (restart and `OOMKilled` counts, HPA replicas) are tabulated in [3.2 Monitoring and Observability](topic2.md#monitoring-and-observability).

!!! tip "The two logs that answer most EKS questions"

    `kubectl describe pod` events answer almost every "why is this Pod not running" question  insufficient resources, no matching node, image pull failure, IP exhaustion, volume attachment failure  in plain text. The **`authenticator` control plane log** answers almost every "why can't I connect" question. Reaching for either before reasoning about what the system might be doing saves hours, and this is the single most useful operational habit to build in this module.

---

## Integration with Other AWS Services

| Service | Why it integrates with EKS |
|---|---|
| **Amazon EC2** | The instances behind managed node groups, self-managed nodes, and Karpenter |
| **Amazon VPC** | The network Pods live in; subnets, route tables, security groups, and the address plan |
| **Elastic Load Balancing** | ALBs for Ingress, NLBs for Services, via the AWS Load Balancer Controller |
| **AWS IAM and STS** | Cluster authentication, and per-Pod roles through IRSA or Pod Identity |
| **Amazon ECR** | The registry nodes pull from, authenticated by the node role; image scanning |
| **Amazon EBS, EFS, FSx, S3** | Persistent storage through CSI drivers and Mountpoint for S3 |
| **AWS KMS** | Envelope encryption of Secrets, and encryption of EBS volumes |
| **AWS Secrets Manager and Parameter Store** | Runtime secret injection through the Secrets Store CSI Driver |
| **Amazon CloudWatch** | Control plane logs, container logs and metrics, Container Insights, alarms |
| **Amazon Managed Service for Prometheus and Grafana** | The Kubernetes-native metrics path without running Prometheus yourself |
| **AWS X-Ray and AWS Distro for OpenTelemetry** | Distributed tracing across Pods and AWS services |
| **AWS CloudTrail** | Audit of EKS control plane API calls |
| **Amazon GuardDuty** | EKS Protection: audit log analysis and runtime threat detection |
| **AWS Certificate Manager** | TLS certificates terminated at the ALB or NLB |
| **Amazon Route 53** | DNS for Ingress hostnames, automated by ExternalDNS |
| **AWS App Mesh alternatives and service meshes** | Istio, Linkerd, or Cilium for mTLS and traffic management |
| **AWS CodePipeline, CodeBuild, Argo CD, Flux** | The delivery path from commit to cluster |
| **AWS CloudFormation, CDK, Terraform, `eksctl`** | Declarative cluster and node group definition |
| **AWS Controllers for Kubernetes (ACK)** | Manage AWS resources  S3 buckets, RDS instances, SQS queues  as Kubernetes custom resources |
| **Amazon SQS, SNS, EventBridge** | The messaging services Pods integrate with, using per-Pod IAM roles |

```mermaid
flowchart TD
    DEV["Developer commit"] --> CI["CodeBuild or GitHub Actions"]
    CI --> ECR["Amazon ECR: build, scan, push by digest"]
    CI --> GIT["Git repository of manifests or Helm values"]
    GIT --> ARGO["Argo CD in-cluster"]
    ARGO --> API["EKS control plane"]
    API --> NODES["Managed node groups and Karpenter-provisioned nodes"]
    ECR --> NODES
    NODES --> PODS["Application Pods"]
    PODS -->|"Pod Identity or IRSA"| AWSSVC["S3, DynamoDB, SQS, Secrets Manager"]
    ALB["Application Load Balancer via the AWS Load Balancer Controller"] --> PODS
    R53["Route 53, automated by ExternalDNS"] --> ALB
    ACM["AWS Certificate Manager"] --> ALB
    PODS --> CWL["CloudWatch Logs and Container Insights"]
    PODS --> AMP["Amazon Managed Service for Prometheus"]
    API --> CWLOGS["Control plane audit and authenticator logs"]
    CWLOGS --> GD["Amazon GuardDuty EKS Protection"]
    KMS["AWS KMS"] --> API
    CSI["Secrets Store CSI Driver"] --> SM["AWS Secrets Manager"]
    CSI --> PODS
```

Read architecturally, this diagram separates three flows that are often conflated. The **delivery flow** (commit to ECR to Git to Argo CD to the API server) never touches the running data plane directly. The **runtime flow** (Route 53 to ALB to Pod to AWS services) never touches the control plane at all, which is what makes a control plane impairment survivable. And the **identity flow**  Pod Identity or IRSA connecting a ServiceAccount to an IAM role  is the only thing standing between a compromised Pod and the rest of the account.

---

## Common Architecture Patterns

### Managed node groups in three private subnets

The baseline production topology: three private subnets across three Availability Zones, managed node groups spanning all three, an internet-facing ALB in public subnets, and NAT gateways for egress. Everything else in this chapter is a refinement of this shape. Its virtue is that it has no unusual failure modes and every AWS troubleshooting document assumes it.

### Karpenter and Fargate as refinements of the baseline

Karpenter for just-in-time, heterogeneous, Spot-friendly capacity, and Fargate profiles for isolation-sensitive or bursty namespaces, are the two most common refinements of that baseline. Both are treated as patterns in [3.3 Common Architecture Patterns](topic3.md#common-architecture-patterns).

### Per-Pod IAM with the metadata service blocked

Every workload has its own ServiceAccount bound to its own least-privilege IAM role through Pod Identity or IRSA, and every node enforces IMDSv2 with a hop limit of 1. This is the pattern that makes a compromised Pod a contained incident rather than an account-wide one, and it is the single most valuable security pattern in this chapter.

### GitOps with Argo CD or Flux

The cluster's desired state is a Git repository; a controller in the cluster reconciles toward it. Deployment becomes a pull request; rollback becomes a revert; drift is detected and reported. It also removes the need for CI systems to hold cluster credentials, which matters more once the endpoint is private.

### The AWS Load Balancer Controller with IP-mode targets

One ALB fronting many Services through Ingress rules, registering Pod IPs directly. Combined with ExternalDNS for Route 53 records and ACM for certificates, this is the standard external exposure pattern on EKS, and IP mode is what makes it efficient.

### Cluster per environment, namespace per team

Separate clusters for production and non-production  different blast radius, different upgrade schedule, different access  with namespaces, resource quotas, network policies, and RBAC providing isolation between teams inside each. This balances the per-cluster fee and operational burden against genuine isolation requirements. The alternative, a cluster per team, multiplies cost and upgrade work and is justified only by hard compliance boundaries.

### Multi-cluster for blast radius or regional resilience

Two or more clusters, in different Regions or in the same Region, with traffic distributed by Route 53 or Global Accelerator and state replicated at the data layer. This is the answer to "what if the cluster itself is the problem"  a bad admission webhook, a failed upgrade, a Region event. It is expensive and complex and should be justified by a specific requirement rather than adopted by default.

---

## Industry Use Cases

| Sector | Workload | EKS configuration | Reasoning |
|---|---|---|---|
| Higher education | Multi-department platform | One cluster, namespace per department, quotas and network policies, `AmazonEKSEditPolicy` scoped per namespace | One control plane fee; strong enough isolation for internal teams |
| Higher education | Research batch computing | Karpenter with Spot and GPU node pools, taints and tolerations | Interruption-tolerant, bursty, and cost-dominated |
| E-commerce | Storefront and checkout | Managed node groups across three AZs, IP-mode ALB, HPA on requests per Pod, PDBs | Availability-critical and latency-sensitive |
| E-commerce | Order processing workers | Karpenter Spot node pool, KEDA scaling on SQS backlog per Pod | The [Chapter 2.3](../unit2/topic3.md) lesson, expressed in Kubernetes |
| Financial services | Payment services | Private-only endpoint, security groups for Pods, PSA `restricted`, KMS Secrets encryption, GuardDuty | Regulatory requirements enforced in the VPC, not only in the cluster |
| Financial services | Risk computation | Graviton node pools, right-sized requests, Karpenter consolidation | CPU-dominated cost with a portable workload |
| Media | Video transcoding | GPU node groups with taints, Spot with several instance families | Expensive capacity that must not be idle and can absorb interruption |
| Media | Content APIs | CloudFront to ALB to IP-mode targets, topology aware routing | Latency and inter-AZ transfer both matter at volume |
| Healthcare | Integration and interoperability services | Fargate profiles for third-party adapters, network policies, per-Pod IAM | Untrusted third-party code isolated at the Pod level |
| Telecommunications | Edge and on-premises workloads | EKS Hybrid Nodes joined to a cloud control plane | Latency and data residency force compute on-premises; management stays central |
| SaaS | Multi-tenant platform | Namespace per tenant with quotas and network policies, or cluster per tier for large tenants | The classic isolation-versus-cost decision, made per tenant tier |
| Government | Multi-supplier portal | Cluster per supplier or namespace per supplier, access entries per supplier role, GitOps | Independence of delivery with a centrally enforced safety floor |
| Machine learning | Training and inference | GPU node groups, Karpenter, ACK for S3 and SageMaker integration, IRSA for data access | Heterogeneous, expensive, bursty capacity with strong data-access controls |

---

## Advantages

**The control plane's hardest parts are simply gone.** `etcd` quorum, control plane PKI, API server high availability, and control plane patching are AWS's problem, delivered with a multi-AZ architecture and an SLA. This is not a marginal convenience; it removes the class of incident that most commonly destroys self-managed Kubernetes clusters.

**Upstream conformance means the ecosystem works.** Helm charts, operators, CRDs, service meshes, and Kubernetes-native tooling run unmodified. The value of Kubernetes is largely the value of what other people have built on it, and EKS preserves all of it.

**Native VPC networking makes Pods first-class AWS citizens.** A Pod with a real VPC IP address can be a load balancer target, can be reached from anything in the VPC, appears in Flow Logs, and can carry its own security groups. Overlay-based platforms need gateways and translation to achieve any of this.

**Identity integration is genuinely fine-grained.** A Pod can hold an IAM role scoped to exactly the resources it needs, with credentials that are short-lived and automatically rotated, and its role assumption is visible in CloudTrail. Few platforms offer per-workload cloud identity this cleanly.

**Access management moved outside the cluster.** Access entries make cluster permissions an EKS API concern  auditable in CloudTrail, expressible in Terraform, immune to the ConfigMap lockout that has stranded countless self-managed clusters.

**Portability is real where it matters.** Workload manifests move to any conformant Kubernetes. The parts that do not move  ALB Ingress annotations, EBS storage classes, IRSA  are precisely the integrations you would have to rebuild anyway on another platform, and are a conscious trade rather than a hidden lock-in.

---

## Limitations

**Kubernetes is a large conceptual surface, and EKS does not shrink it.** Pods, Deployments, Services, Ingresses, ConfigMaps, Secrets, ServiceAccounts, RBAC, CRDs, admission control, probes, requests and limits, taints and tolerations, affinities, topology spread  a team must learn all of it. Compared with ECS, the time to a first correct production deployment is substantially longer, and the number of ways to be subtly wrong is much larger.

**You still operate the data plane.** Node AMIs, `kubelet` versions, the four core add-ons, the load balancer controller, CSI drivers, metrics-server, and any operator you installed are all yours to keep current and compatible. "Managed Kubernetes" manages half the cluster.

**The upgrade obligation is permanent and one-directional.** Roughly annual minor version upgrades, one version at a time, effectively one-way, with deprecated API checks and add-on compatibility to verify each time. There is no equivalent obligation in ECS, and this is the recurring cost that surprises teams most.

**IP address planning is a hard constraint that CPU dashboards do not show.** The VPC CNI's native addressing is a real benefit that is paid for with an address budget, and exhausting it stops scheduling regardless of available compute. Remedies exist; the structural one (IPv6) is creation-time only.

**The per-cluster fee penalises fragmentation.** A flat hourly charge per cluster means many small clusters cost meaningfully more than a few large ones, which pushes toward shared clusters and therefore toward shared blast radius and shared upgrade schedules.

**The control-plane-to-VPC path is a genuine failure mode.** Admission webhooks, `exec`, `logs`, and metrics all depend on the control plane reaching into your VPC through cross-account ENIs. Security group and endpoint changes break it, and the resulting failures  `failed calling webhook` blocking all deployments  are severe and non-obvious.

**Fargate on EKS is a narrower product than Fargate on ECS.** It is excellent for what fits and unusable for what does not; its structural limitations are derived in [3.3](topic3.md#why-fargate-exists-the-node-is-an-operational-liability).

**Cross-AZ traffic is charged and Kubernetes is topology-blind by default.** Without topology aware routing, a multi-AZ cluster sends most internal Service traffic across zone boundaries and pays for it in both directions.

**Cost attribution requires additional tooling.** A shared cluster's EC2 bill does not decompose into namespaces without split cost allocation data or a third-party tool, which makes chargeback and optimisation conversations harder than they are on ECS with per-task tagging.

---

## Common Mistakes

### Beginner Mistakes

| Mistake | Why it is wrong | What to do instead |
|---|---|---|
| Creating a cluster with a CI role, then trying `kubectl` as a human | The creator's admin grant is implicit and invisible; you are `Unauthorized` | Create an explicit cluster-admin access entry for a human-assumable role immediately |
| Confusing `Unauthorized` with `Forbidden` | They are different systems; widening IAM does not fix an RBAC problem | `Unauthorized` = no access entry; `Forbidden` = no RoleBinding |
| Using `t3.medium` nodes and wondering why Pods are `Pending` | Seventeen Pods maximum, several already consumed by system components | Larger instances, or prefix delegation, or both |
| Reusing a VPC with `/24` subnets | Every Pod takes a VPC address; you exhaust the subnet long before the CPU | Plan subnets for Pod density; enable prefix delegation |
| Giving Pods AWS access through the node role | Every Pod inherits every permission | Pod Identity or IRSA, plus IMDS hop limit 1 |
| One replica of everything | No availability during a node replacement, let alone an AZ event | At least two replicas plus a PodDisruptionBudget |
| Nodes in public subnets | Unnecessary internet exposure of the whole data plane | Private subnets with NAT or VPC endpoints for egress |

### Production Mistakes

| Mistake | Consequence | Remedy |
|---|---|---|
| Tightening the cluster security group without understanding webhook traffic | All deployments fail with `failed calling webhook` | Allow control plane to node traffic on webhook ports; test after every security group change |
| Letting a cluster fall into extended support | About six times the control plane price, indefinitely | An annual upgrade cadence rehearsed in non-production |
| Enabling private-only endpoints without an administration path | CI/CD and humans are locked out; the usual fix is to re-open publicly to `0.0.0.0/0` | Solve the network path first: bastion, VPN, or in-VPC runners |
| Scheduling everything on Spot | A capacity event removes the whole cluster's workload | An On-Demand base sized for floor traffic; diverse instance types above it |
| Ignoring the CNI's IP metrics | Scale-out fails at a random future moment with no warning | Alarm on assigned versus total addresses per node and on subnet free IPs |
| KMS key for Secrets deleted or made inaccessible | Every Secret becomes unreadable; the cluster is unrecoverable | A key policy that prevents deletion; the key in the same account and Region |
| Granting `system:masters` broadly | An unrestricted grant that RBAC review cannot see | Managed access policies on named roles; audit for `system:masters` |

Workload-manifest mistakes (requests, probes, mutable tags, PodDisruptionBudgets, upgrade pre-flight) are listed in [3.2 Common Mistakes](topic2.md#common-mistakes); Fargate, node group, add-on, CoreDNS, and webhook-replica mistakes are listed in [3.3 Common Mistakes](topic3.md#common-mistakes).

### Certification Traps

| Trap | The reality |
|---|---|
| "EKS manages the worker nodes" | Only with Auto Mode or Fargate. Standard EKS manages the control plane; nodes are yours |
| "The control plane runs in your VPC" | It runs in an AWS-managed VPC; only cross-account ENIs are in yours |
| "A control plane outage stops running Pods" | Running Pods continue; what stops is change |
| "IAM permissions grant Kubernetes access" | IAM authenticates; RBAC authorizes; an access entry connects them |
| "`AdministratorAccess` makes you a cluster admin" | It does not. Without an access entry you are `Unauthorized` |
| "Pods get overlay IPs" | With the VPC CNI they get real, routable VPC addresses |
| "Pod density depends only on CPU and memory" | ENI and IP limits usually bind first, unless prefix delegation is enabled |
| "IRSA and Pod Identity are the same mechanism" | IRSA uses OIDC federation; Pod Identity uses an agent and an EKS association, and does not work on Fargate |
| "Kubernetes Secrets are encrypted by default" | They are base64-encoded; `etcd` volumes are encrypted, but envelope encryption with KMS is opt-in |
| "Instance mode and IP mode targeting differ only in configuration" | IP mode removes a hop, preserves the client IP more simply, and is required on Fargate |
| "Network policies work out of the box" | They require an enforcing plugin: the VPC CNI with network policy enabled, or Calico |
| "The `aws-auth` ConfigMap is still the recommended approach" | Access entries replaced it; new clusters should use `API` authentication mode |
| "The cluster creator has no special access" | It holds an implicit `system:masters` grant that is invisible in `aws-auth` and access entries |
| "RBAC can restrict any principal" | `system:masters` short-circuits authorization; RBAC cannot limit it |

---

## Summary

First, **EKS is a Kubernetes cluster with a boundary drawn through it**, and almost every question in this chapter is answered by locating the thing you care about on one side or the other. AWS runs the API server, `etcd`, the scheduler, and the controller managers in its own account across three Availability Zones, with an SLA. You run the nodes, the `kubelet`, `kube-proxy`, the CNI, CoreDNS, and every controller you install, in your VPC, at your expense and on your maintenance schedule. The consequence worth carrying is that a control plane impairment stops *change* but not *traffic*  running Pods keep serving  while a data plane problem is immediate and yours.

Second, **the boundary is crossed in both directions, and the inbound direction is the one that breaks**. Every `kubelet` holds an outbound connection to the cluster endpoint; the API server reaches inbound through cross-account ENIs in your subnets for `kubectl exec`, `logs`, `port-forward`, metrics, and  critically  every admission webhook, synchronously, on the write path. A security group change that severs this leaves reads working and deployments failing, which is why "it worked yesterday and now nothing deploys" so often traces back to a network change rather than to Kubernetes.

Third, **the VPC CNI's decision to give every Pod a real VPC address is the source of both EKS's best networking properties and its most common capacity surprise**. Native routing with no encapsulation, Pods as load balancer targets, Pod-level security groups, and Flow Log visibility are all consequences of it  and so is a Pod ceiling of `(ENIs × (IPs per ENI − 1)) + 2` that binds long before CPU does. Prefix delegation multiplies that ceiling by up to sixteen for free and should be the default on Nitro instances; `WARM_IP_TARGET` makes allocation demand-driven; custom networking onto `100.64.0.0/10` buys space; and IPv6 removes the problem entirely but only at cluster creation. IP addresses are a capacity dimension, and no CPU dashboard will ever show you running out of them.

Fourth, **EKS has two independent permission systems and confusing them wastes hours**. AWS IAM authenticates: a pre-signed SigV4 token is resolved by the IAM Authenticator to an ARN, and an access entry maps that ARN to a Kubernetes identity. Kubernetes RBAC authorizes: Roles and bindings decide what that identity may do. `Unauthorized` means the first refused; `Forbidden` means the second did. Access entries replaced the `aws-auth` ConfigMap with an auditable API and managed policies that can be scoped to namespaces, and the cluster creator's implicit, invisible `system:masters` grant remains the trap that catches almost every student once.

Fifth, **per-Pod identity is the security control that matters most, and it is inert without one EC2 setting**. Without IRSA or Pod Identity, every Pod on a node can assume the node's role, so the node role becomes the union of every workload's permissions and one compromised Pod inherits all of them. IRSA federates through OIDC and works everywhere including Fargate; Pod Identity uses an agent and an EKS association, is simpler, and reuses roles across clusters but has no Fargate support. Either is decorative unless nodes require IMDSv2 with a hop limit of 1, because otherwise a Pod can simply take the node role instead.

Sixth, **the data plane is a spectrum and you should use more than one point on it**. Managed node groups are the sensible default; Karpenter adds fast, dense, Spot-friendly provisioning; Fargate removes the node entirely for workloads that do not need one; Auto Mode hands the whole data plane to AWS for a fee; hybrid nodes extend the cluster on-premises. These coexist in one cluster, which means the right answer is usually "managed node groups plus Karpenter, with Fargate profiles for specific namespaces" rather than any single choice.

Seventh, and most easily forgotten, **EKS carries a permanent, one-directional upgrade obligation**. A Kubernetes version leaves standard support after roughly fourteen months and the extended-support price is about six times higher; upgrades proceed one minor version at a time and are effectively one-way, since a control plane rollback is possible only within a short window and nodes and add-ons must be reverted separately; each one requires deprecated API checks, add-on updates, and node replacement. This is not an operational detail to handle later  it is a design input that determines whether you can afford many small clusters, whether your add-ons are managed or ad hoc, and whether your team has rehearsed the process before the CVE arrives.

---

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit3.md#31-amazon-eks-architecture) · [Interview questions](../interviewquestions/unit3.md#31-amazon-eks-architecture).

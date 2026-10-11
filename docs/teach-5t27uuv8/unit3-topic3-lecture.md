# Unit 3 Lecture: Amazon EKS Advanced Concepts

**Duration:** 2 hours (120 minutes, including a 5-minute break)  
**Audience:** 4th-year Software Engineering students who know Kubernetes fundamentals and attended the 3.1 and 3.2 lectures  
**Mode:** Lecture with real-console exploration of a shared cluster, CLI practice on Floci, ClassLegend quiz  
**Running scenario:** USMS, the University Student Management System, now running on EKS, has to decide where each of its workloads should run

<div class="lesson-schedule"></div>

## Before class

!!! teacher "Purpose"
    3.1 built the cluster and 3.2 deployed onto it. This lecture is about the compute underneath each workload: Fargate profiles, managed node groups and EKS add-ons, and the judgement of which workload belongs where. Students already know Pods, Deployments, Services and the control plane / data plane split, so revision is a five-minute quick-fire inside the hook, not a re-teach.

**Learning outcomes.** By the end, students should be able to:

1. Place self-managed nodes, managed node groups and Fargate on the compute-management spectrum and state what each removes and what it costs.
2. Explain how a Fargate profile selects Pods (namespace required, labels AND, selectors OR), why profiles are immutable and why they need private subnets.
3. Explain each Fargate limitation (no DaemonSets, EBS, GPUs, privileged containers, Pod Identity; IP-mode targets; slower start) as a consequence of "no node", and calculate a Fargate bill from rounded-up requests.
4. Describe what a managed node group automates: EKS-optimized AMIs (including Bottlerocket), the Auto Scaling group, and rolling replacement with cordon and drain under `updateConfig`.
5. Diagnose why a PodDisruptionBudget with zero allowed disruptions blocks a node group upgrade, and fix it.
6. Design Spot capacity safely: several instance types above an On-Demand base, across Availability Zones.
7. Name what breaks without each core add-on (VPC CNI, CoreDNS, `kube-proxy`, EBS CSI driver, Pod Identity Agent), and state the upgrade order and IAM practice for add-ons.
8. Choose Fargate or a managed node group for a given workload and justify it.

**Teacher preparation checklist**

- [ ] Create the shared cluster **at least 30 minutes before class**: follow [Shared EKS cluster: create the cluster](unit3-shared-eks-cluster.md#before-class-create-the-cluster) (`dso303-u3-shared`, node group `dso303-u3-nodes`, 2 × `t3.medium`, default add-ons)
- [ ] Optional Step 9 on that page done, so the **Resources** tab shows real Pods (no LoadBalancer Services, no PVCs)
- [ ] Decide which access case applies (same account with `AmazonEKSViewPolicy` access entry, or own accounts / Learner Lab, where students follow your screen)
- [ ] Open the **Add Fargate profile** wizard once yourself. Check whether any role appears in the **Pod execution role** list; if none does, the wizard cannot advance past its first page, and you show the selector page from the notes' YAML example instead
- [ ] Note in advance: the default VPC's subnets are public (they route to an internet gateway). That is a teaching point in Hands-on A, not something to fix
- [ ] ClassLegend quiz bank `unit3-topic3` imported
- [ ] Notes [3.3 Amazon EKS Advanced Concepts](../unit3/topic3.md){ .notes-link target="_blank" } open in a second tab

**Floci environment checks (students did Labs 07 and 08)**

- [ ] `cd ~/aws-floci-course && ./scripts/setup/floci-up.sh` succeeds on the teaching machine
- [ ] `outputs/lab-07-support-probe.txt` exists and names Path A or Path B ([Lab 07 Step 2](../Lab/Lab-07-EKS.md#step-2-probe-what-your-build-actually-supports-and-record-the-answer))
- [ ] `kubectl get nodes` works against `usms-eks-cluster` and namespace `usms` is healthy
- [ ] `nginx:1.27-alpine` is already cached from Lab 07 (no download needed in class)
- [ ] You have run Hands-on B once and noted which `aws eks` add-on and Fargate calls your Floci build supports

!!! warning "Rules for this lecture"
    Students create **no** clusters, node groups or Fargate profiles, and change nothing on `dso303-u3-shared`. Every wizard stops at its **Review** page. On Floci, all practice work goes in a new namespace `u3t3`; nobody touches namespace `usms`, the Lab 07/08 resources, or cordons or drains a node. Never `floci start`, `docker compose down -v`, `docker volume prune` or `rm -rf ~/floci-data`.

!!! teacher "If a student does create a console resource"
    Avoid it, but if it happens: tag it `Course=DSO303` and `Session=u3t3`, name it with the prefix `dso303-u3t3-<initials>`, and delete it in the clean-up segment.

---

## Hook: one cluster, five workloads { data-minutes="10" }

[3.1 Control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane){ .notes-link target="_blank" }
[3.1 Worker nodes: data plane options](../unit3/topic1.md#worker-nodes-data-plane-options){ .notes-link target="_blank" }
[3.2 Creating and managing EKS clusters](../unit3/topic2.md#creating-and-managing-eks-clusters){ .notes-link target="_blank" }
[3.2 Requests and limits](../unit3/topic2.md#requests-and-limits){ .notes-link target="_blank" }

**Quick-fire revision (about 5 minutes).** Ask fast, take the first good answer, move on. No re-teaching.

1. In EKS, who runs the control plane, and who chooses the data plane?
2. Which component gives each Pod an IP address from the VPC?
3. What is the order of a cluster upgrade?
4. What does the scheduler use a container's resource **request** for?
5. Name the two ways to give a Pod its own AWS permissions.

???+ answer "Expected answers"
    1. AWS runs the control plane; you choose and pay for the data plane.
    2. The Amazon VPC CNI.
    3. Control plane, then add-ons, then nodes.
    4. To decide which node has room for the Pod (requests are reserved capacity).
    5. IRSA (IAM roles for service accounts) and EKS Pod Identity.

    Answers 2, 3, 4 and 5 all return today with a twist: on Fargate the request becomes the bill, and one of the two identity methods stops working.

!!! prompt "USMS needs a home for five workloads"
    The USMS cluster from Labs 07 and 08 is going to production. The platform team has to decide where each of these runs:

    1. **Enrolment API**: steady traffic all semester, many small replicas.
    2. **Results-release CI jobs**: run for about four minutes, a few times a day.
    3. **Third-party plagiarism checker**: a vendor plugin that runs code the university did not write.
    4. **Node log and metrics agent**: must run one copy on every node.
    5. **Transcript database**: needs a persistent block volume.

    **Pairs, 3 minutes:** does each one need a "real" server underneath it? Which ones would you rather never think about servers for?

!!! teacher "Teaching notes"
    Collect answers on the board in two columns, "needs a node" and "does not care", and do not correct them yet. Return to the board at the end of Concept B with the decision framework. The expected final placement: 1 node group, 2 Fargate, 3 Fargate, 4 node group (DaemonSet), 5 node group (EBS).

    **Transition:** "3.1 said you choose the data plane. Today we look at the three things you choose from, and why each workload pushes you one way or the other."

## Where Pods run: Fargate and node groups { data-minutes="15" }

[3.3 Definition](../unit3/topic3.md#definition){ .notes-link target="_blank" }
[3.3 The compute-management spectrum](../unit3/topic3.md#the-compute-management-spectrum){ .notes-link target="_blank" }
[3.3 Why Fargate exists](../unit3/topic3.md#why-fargate-exists){ .notes-link target="_blank" }
[3.3 EKS Fargate profiles](../unit3/topic3.md#eks-fargate-profiles){ .notes-link target="_blank" }
[3.3 EKS managed node groups](../unit3/topic3.md#eks-managed-node-groups){ .notes-link target="_blank" }

### The spectrum (3 minutes)

| Model | Who manages the node | You still decide | Pricing |
|---|---|---|---|
| **Self-managed EC2 nodes** | You: AMI, bootstrap, registration, upgrades | Everything | Per instance |
| **Managed node group** | EKS automates provisioning, replacement, updates | Instance types, scaling limits, labels, taints, upgrade timing | Per instance (normal EC2) |
| **Fargate** | AWS; no node is visible to you | Pod resource requests and which Pods use Fargate | Per Pod |

Moving right: fewer servers to manage, less low-level control, more workload constraints. **Neither end is universally better**, and one cluster can mix all three.

!!! prompt "Analogy: where your Pods live"
    - **Self-managed node:** owning a house. You fix the roof, the plumbing and the wiring.
    - **Managed node group:** renting a flat in a managed building. The building manager handles maintenance and replaces broken appliances, but you choose the size of flat and decide when to move.
    - **Fargate:** a hotel room booked per guest. You only say how big a room you need; housekeeping, the building and the other guests are someone else's problem. You cannot knock through walls, and you pay for the room size, not the space you actually used.

!!! teacher "Where the analogy breaks"
    A hotel room can sleep several unrelated guests; a Fargate micro-VM holds exactly **one Pod** (which may have several containers). And the "building manager" of a managed node group does not choose when to renovate: **you** trigger node upgrades and choose how many nodes are replaced at once. Say both out loud.

### Fargate on EKS (7 minutes)

**The one decision behind everything:** Fargate makes the Pod itself the unit of compute. AWS creates an isolated **micro-VM sized to the Pod's requests**, runs the Pod, and destroys the micro-VM when it ends. Nothing is reused.

**Fargate profiles** decide which Pods go there. A profile has a name, a **Pod execution role**, a list of **private subnets** and up to **five selectors**.

| Rule | Meaning |
|---|---|
| Namespace is required | Labels alone cannot select a Pod |
| Labels within one selector: AND | All must match |
| Selectors within a profile: OR | Any one may match |
| Wildcards | `*` and `?` allowed, for example `preview-*` |
| Profiles are immutable | To change one, create a new profile and delete the old |
| Deleting a profile stops its Pods | They become `Pending` |
| Private subnets only | No public IP; egress via NAT gateway or VPC endpoints |

**Every limitation follows from "no node":**

| Limitation | Because | Use instead |
|---|---|---|
| No DaemonSets | One Pod per node, and there is no shared node | Sidecars; built-in Fluent Bit for logs |
| No privileged containers, no `hostNetwork` / `hostPort` | The host belongs to AWS | A node group |
| No GPUs | Capacity is standard compute, not a chosen instance type | A GPU node group |
| No EBS volumes | EBS attaches to an instance | **EFS** (EFS CSI driver) |
| No EKS Pod Identity | Its agent is a DaemonSet | **IRSA** |
| Load balancer targets in **IP mode** | There is no instance to register | IP target type |
| Slower Pod start | New micro-VM plus an uncached image pull | Nodes with headroom for fast scale-out |

**Billing.** Per second (one-minute minimum) for the vCPU and memory the Pod **requests**, rounded up to the nearest supported size. Fargate adds about 256 MB per Pod for Kubernetes components. Sizes run from 0.25 vCPU / 0.5 GB to 16 vCPU / 120 GB.

Two more details: the **Pod execution role** is used by AWS to register the Pod and pull images, and the application cannot use it (give the app IRSA). Logs go through the built-in **Fluent Bit** router, configured with a ConfigMap in the `aws-observability` namespace, because there is no node for a logging DaemonSet.

!!! prompt "Predict, then check"
    1. A Fargate profile has one selector: namespace `ci`, label `runner: "true"`. A Pod is created in `ci` **without** that label. Where does it run?
    2. A Pod's containers request 0.4 vCPU and 1.5 GB in total. What size is allocated and billed?

???+ answer "Check"
    1. On an EC2 node as normal. Labels within a selector are ANDed, so the namespace match alone is not enough. (If no node group exists, it stays `Pending`.)
    2. 0.5 vCPU and 2 GB. On Fargate, the rounded-up request **is** the bill; on EC2 nodes an oversized request mostly affects how many Pods fit.

### Managed node groups (5 minutes)

A managed node group is **still EC2**, in your account, billed as normal EC2, with no extra charge. EKS creates an **Auto Scaling group** and a **launch template** and operates them as Kubernetes nodes.

| Self-managed burden | Managed node group provides |
|---|---|
| Choose and track an AMI | AWS-published **EKS-optimized AMIs** per Kubernetes version |
| Bootstrap scripts, joining the cluster | Automatic, including the node role's access entry |
| Replace unhealthy nodes | Health monitoring and automatic replacement |
| Upgrade safely | Rolling replacement with cordon and drain (Concept B) |
| Spot interruptions | Nodes drained when AWS signals reclamation |

**AMI families:** Amazon Linux 2023 (general default), **Bottlerocket** (minimal container OS: read-only root, no shell, smaller attack surface, faster boot, harder to customise), GPU AMIs, Windows. A **custom AMI** in a launch template means EKS no longer updates that image for you.

**Capacity type.** On-Demand or **Spot** (spare capacity at a large discount, reclaimable with a **two-minute warning**). Safe Spot means: **several compatible instance types**, only interruption-tolerant work, and an **On-Demand group that can carry essential traffic alone**, with Spot above it. Span groups across **Availability Zones**, but remember a multi-AZ node group alone is not high availability: the app also needs replicas spread across zones.

!!! teacher "Transition"
    "Enough theory. The teacher's cluster has a managed node group running right now. Let's read it in the console, then walk the wizards that would create a Fargate profile and a Spot node group, without creating either."

## Hands-on A: read the shared cluster { data-minutes="15" }

[3.3 EKS managed node groups](../unit3/topic3.md#eks-managed-node-groups){ .notes-link target="_blank" }
[3.3 EKS add-ons](../unit3/topic3.md#eks-add-ons){ .notes-link target="_blank" }
[3.3 Configuration options](../unit3/topic3.md#configuration-options){ .notes-link target="_blank" }
[Shared cluster page](unit3-shared-eks-cluster.md){ .notes-link target="_blank" }

!!! prompt "Prediction first (1 minute)"
    The node group `dso303-u3-nodes` was created with desired 2, minimum 1, maximum 2. If one of its EC2 instances were terminated by hand right now, what would happen within a few minutes, and which AWS object would make it happen?

???+ answer "Expected response"
    A replacement instance launches and joins the cluster. The **Auto Scaling group** that EKS created holds the desired count at 2; EKS health monitoring and the EKS-optimized AMI's bootstrap make the new instance a `Ready` node. (We do not test this: nobody changes the shared cluster.)

!!! teacher "Which access case?"
    **Same account:** students follow along in their own browser (read-only access entry from the shared page, Step 8). **Own accounts / Learner Lab:** students cannot see `dso303-u3-shared`. They follow your screen for Steps 1 to 3, and do Steps 4 and 5 in their own account **only if they already have a cluster there**; otherwise you lead those steps on screen too. Console labels below may differ slightly from your console version; describe what you see.

**Step 1: The node group's details.** EKS, then `dso303-u3-shared`, then the **Compute** tab, then the node group `dso303-u3-nodes`. Read out:

| Field | Expected value | Why it matters |
|---|---|---|
| AMI type | Amazon Linux 2023 | EKS-optimized; EKS publishes new versions per Kubernetes version |
| Instance type(s) | `t3.medium` | Chosen by you; a managed node group does not pick sizes |
| Capacity type | On-Demand | Spot would be cheaper but reclaimable |
| Scaling configuration | Desired 2, minimum 1, maximum 2 | The limits the Auto Scaling group enforces |
| Update configuration | Maximum unavailable, as a number or a percentage | How many nodes are replaced at once in an upgrade |
| Subnets | Two or more, in different AZs | Multi-AZ node capacity |

*Why question:* the update configuration says "maximum unavailable". Unavailable from whose point of view, and what would a large value trade away?

???+ answer "Expected response"
    Nodes taken out of service at once during a rolling replacement. Larger is faster but removes more capacity at the same time; small is safer.

**Step 2: The Auto Scaling group EKS created.** In the node group details, find the Auto Scaling group name (it links to EC2 Auto Scaling) and open it. Show its desired, minimum and maximum capacity and its launch template. Do **not** edit it.

*Why question:* why should you change scaling through the node group and never edit this Auto Scaling group directly?

???+ answer "Expected response"
    EKS owns and operates it. The node group is the source of truth; editing the Auto Scaling group behind EKS's back creates drift between what EKS believes and what exists.

**Step 3: Node health and the Add-ons tab.** Back on the node group, open the **Nodes** list: two nodes, both `Ready`. Then open the cluster's **Add-ons** tab and read each add-on's **version** and **status**: Amazon VPC CNI, CoreDNS, `kube-proxy`, EKS Pod Identity Agent. Point out whether any shows that a newer version is available.

*Why question:* the console says an update is available for CoreDNS. Why not click update the moment you see it, and when in a cluster upgrade would you normally update it?

???+ answer "Expected response"
    Add-on versions must match the control plane version, and teams pin them in IaC so changes are deliberate and reviewed. The normal place is the middle step of an upgrade: control plane, then add-ons, then nodes. (Full explanation in Concept B.)

**Step 4: Walk the Add Fargate profile wizard (do not create).** **Compute** tab, then **Add Fargate profile**.

1. **Configure:** name (use `dso303-u3t3-<initials>-ci` if you are in your own account), **Pod execution role**, **subnets**. Show the subnet list: the default VPC has only public subnets.
2. **Pod selection:** add a selector with namespace `ci` and a label `runner` = `true`; add a second selector with namespace `preview-*`.
3. Stop at **Review**. Read the summary aloud, then **Cancel**.

*Why question:* the shared cluster runs in the default VPC. Why would creating this profile fail (or why does the wizard offer no suitable subnets), and what would the network need?

???+ answer "Expected response"
    Fargate Pods run in **private subnets only**, with no public IP. The default VPC's subnets route to an internet gateway, so they are public. A production cluster needs private subnets with egress through a NAT gateway or VPC endpoints, so image pulls still work.

!!! teacher "If no Pod execution role is listed"
    The wizard cannot pass its first page. Say why: the role is used by AWS to register the Pod and pull images, so it must exist first. Show the selector YAML from the notes' [EKS Fargate profiles](../unit3/topic3.md#eks-fargate-profiles){ .notes-link target="_blank" } section instead.

**Step 5: Walk the Add node group wizard (do not create).** **Compute** tab, then **Add node group**.

1. Name and node IAM role (look, do not change).
2. Compute and scaling page: set **Capacity type** to **Spot** and add **several instance types** of a similar size (for example `t3.medium` and `t3a.medium`). Show the scaling fields and the update configuration (maximum unavailable).
3. Networking page: subnets across AZs.
4. Stop at **Review**, then **Cancel**.

*Why question:* why add several instance types for a Spot group, but not necessarily for an On-Demand group?

???+ answer "Expected response"
    Spot capacity is reclaimed per capacity pool. With one instance type, one reclaimed pool can remove the whole group; several compatible types spread the risk. On-Demand capacity is not reclaimed with a two-minute notice.

**Success criteria**

- [ ] Read the node group's AMI type, instance type, capacity type, scaling and update configuration
- [ ] Found the Auto Scaling group EKS created, and explained why it is not edited directly
- [ ] Read each add-on's version and status
- [ ] Walked the Fargate profile wizard to Review and explained the private-subnet requirement
- [ ] Walked the node group wizard with Spot and several instance types to Review
- [ ] Created nothing; changed nothing on the shared cluster

!!! teacher "Transition"
    "We saw a field called update configuration and an add-on that wanted an update. Both matter on upgrade day, which is where most EKS outages that teams cause themselves happen. That is Concept B."

## Upgrade day: drains, PDBs and add-ons { data-minutes="15" }

[3.3 EKS managed node groups](../unit3/topic3.md#eks-managed-node-groups){ .notes-link target="_blank" }
[3.3 EKS add-ons](../unit3/topic3.md#eks-add-ons){ .notes-link target="_blank" }
[3.3 Fargate versus managed node groups](../unit3/topic3.md#fargate-versus-managed-node-groups){ .notes-link target="_blank" }
[3.3 Decision framework](../unit3/topic3.md#decision-framework){ .notes-link target="_blank" }
[3.3 Production mistakes](../unit3/topic3.md#production-mistakes){ .notes-link target="_blank" }

### How a managed node group upgrades (5 minutes)

Nodes are **replaced, not upgraded in place**:

```text
1. Launch new nodes from the new AMI
2. Cordon an old node        -> no new Pods are scheduled there
3. Drain it                  -> evict its Pods; controllers recreate them elsewhere,
                                respecting each workload's PodDisruptionBudget
4. Terminate the old node, repeat
   (updateConfig: how many nodes at once, as maxUnavailable or maxUnavailablePercentage)
```

Students met PDBs in [Lab 08 Step 12](../Lab/Lab-08-EKS-scaling.md#step-12-a-poddisruptionbudget-and-what-it-does-not-protect-against): a PDB limits **voluntary evictions**, and a drain is voluntary. Today's twist is what that does to an upgrade.

!!! prompt "What would break if...?"
    The enrolment API runs **3 replicas** with a PDB of `minAvailable: 3`. The team starts a managed node group upgrade on Friday afternoon. What happens?

???+ answer "Expected response"
    The PDB allows **zero** disruptions. The drain asks to evict an enrolment Pod and is refused, again and again, so the old node never empties and the update eventually **times out**. The upgrade is blocked by the team's own safety rule. Fix: keep `minAvailable` below the replica count, or use `maxUnavailable: 1`; check `kubectl get pdb -A` and the `ALLOWED DISRUPTIONS` column before upgrading. The force option ignores PDBs: an emergency escape, not a fix, and using it routinely means PDBs protect nothing.

!!! prompt "Analogy: the fire-drill rule"
    A PDB is like a rule that a ward must always keep a minimum number of nurses on the floor. During a building evacuation drill (a drain), nurses leave one by one only while the minimum still holds. If the rule says "all three nurses must stay", the drill can never finish.

!!! teacher "Where the analogy breaks"
    A PDB only governs evictions requested through the API. An **involuntary** loss (a node crashing, a Spot reclamation the drain cannot finish in time) or a plain `kubectl delete pod` ignores it entirely, as Lab 08 showed. A real ward rule would bind everyone.

### Add-ons: what breaks without each (6 minutes)

Add-ons are **data plane software**: they run as Pods and must match the control plane version.

| Add-on | Job | Symptom when missing or broken |
|---|---|---|
| **Amazon VPC CNI** | VPC IPs for Pods | Nodes never `Ready`; Pods stuck `ContainerCreating` |
| **CoreDNS** | Service name resolution | Scattered timeouts that look like unrelated errors |
| **`kube-proxy`** | Service virtual IP routing | ClusterIP Services unreachable from affected nodes |
| **Amazon EBS CSI driver** | Creates and attaches EBS volumes for PVCs | PVCs stay `Pending`; stateful apps never start |
| **EKS Pod Identity Agent** | Per-Pod IAM credentials | Pods cannot get their AWS permissions |

Three rules:

1. **Upgrade order:** control plane, then add-ons, then nodes. Skipping the middle step gives networking or DNS failures.
2. **Pin versions in IaC** so updates are deliberate.
3. **Give each add-on its own IAM role** (IRSA or Pod Identity). The EBS CSI driver creates volumes and the VPC CNI manages network interfaces; putting those permissions on the node role hands them to **every Pod on the node**.

!!! prompt "Predict, then check"
    After an upgrade, users report that the portal "randomly" fails to reach the results service, the database and an external API, with timeouts but no clear error. Pods are all `Running`. Which add-on do you check first, and what configuration would have made it less likely?

???+ answer "Check"
    CoreDNS. DNS failures rarely say "DNS is down"; they look like everything failing. Run CoreDNS with at least two replicas across nodes and zones, and monitor its errors and latency. "Running" is not "healthy".

### Back to the hook: choose per workload (4 minutes)

| Question to ask | Points to |
|---|---|
| Needs GPU, DaemonSet, EBS, privileged mode or host networking? | Managed node group |
| Untrusted or multi-tenant code? | Fargate (per-Pod VM boundary) |
| Bursty, short-lived or very small? | Fargate (no idle node) |
| Steady and dense, or must scale out fast on the user path? | Managed node group with headroom |
| Tolerates interruption? | Spot node group above an On-Demand base |

Return to the board from the hook and settle each USMS workload.

???+ answer "Expected placement"
    1. Enrolment API: managed node group (steady, dense; cheaper well packed; fast scale-out with headroom).
    2. Results-release CI jobs: Fargate (short-lived; no idle node), or a Spot node group if they need node features.
    3. Plagiarism checker: Fargate, its own namespace (per-Pod VM isolation for untrusted code; IRSA if it needs AWS access).
    4. Log and metrics agent: a DaemonSet on node groups. Fargate Pods use the built-in Fluent Bit router instead.
    5. Transcript database: managed node group with the EBS CSI driver (EBS is not available on Fargate).

!!! teacher "Stress"
    "Fargate is always cheaper" is the most common wrong belief. Steady workloads are often cheaper on well-packed nodes. Compare full cost per workload: utilisation, idle capacity, operations effort.

    **Transition:** "Now let's read a node group and add-ons from the CLI on Floci, and build that blocking PDB ourselves, safely, in our own namespace."

## Hands-on B: node groups and PDBs on Floci { data-minutes="20" }

[3.3 EKS managed node groups](../unit3/topic3.md#eks-managed-node-groups){ .notes-link target="_blank" }
[3.3 EKS add-ons](../unit3/topic3.md#eks-add-ons){ .notes-link target="_blank" }
[3.3 Operating it: performance, cost and monitoring](../unit3/topic3.md#operating-it-performance-cost-and-monitoring){ .notes-link target="_blank" }
[Lab 07 Step 2: support probe](../Lab/Lab-07-EKS.md#step-2-probe-what-your-build-actually-supports-and-record-the-answer){ .notes-link target="_blank" }

!!! prompt "Prediction first (1 minute)"
    Floci runs a real k3s cluster behind the `aws eks` API (Lab 07 Step 2). Which of today's three features do you expect to see working on Floci: managed node groups, Fargate profiles, EKS add-ons? Which half, AWS-facing or Kubernetes, will the PDB exercise use?

???+ answer "Expected response"
    The node group exists as a recorded AWS object (Lab 07 Step 10); Fargate profiles and add-ons are likely partial or unsupported, because Floci emulates the AWS half and there is no AWS compute behind it. The PDB is pure Kubernetes, which is the genuinely real half, so it behaves exactly as on EKS.

**Step 1: Start the environment and find your path.**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
source configs/course.env
source configs/lab-07.env
./scripts/utilities/whoami.sh

grep -A1 '== Verdict ==' outputs/lab-07-support-probe.txt | tail -1
kubectl config current-context
echo "cluster=$USMS_EKS_CLUSTER  nodegroup=$USMS_EKS_NODEGROUP"
```

What it does: starts or resumes Floci through Compose (the only supported way), loads the course and Lab 07 variables, confirms the account is `000000000000`, then reads back which support path Lab 07 recorded.

```text
Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Region   : us-east-1
PATH A  - use aws eks throughout
usms-eks
cluster=usms-eks-cluster  nodegroup=usms-eks-nodes
```

> Example output - yours will differ (Path B shows `k3d-usms-eks-cluster` as the context).

*Why question:* why read the recorded support path before running any `aws eks` command today?

???+ answer "Expected response"
    Path B builds have no `eks` API: the node group does not exist as an AWS object. Knowing the path tells you whether a failure is a real mistake or an expected Floci gap.

**Step 2: Read the node group (Path A).**

```bash
aws eks list-nodegroups --cluster-name "$USMS_EKS_CLUSTER" --output table

aws eks describe-nodegroup \
  --cluster-name "$USMS_EKS_CLUSTER" \
  --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --query 'nodegroup.{Status:status,Capacity:capacityType,Types:instanceTypes,
                      Ami:amiType,Scaling:scalingConfig,Update:updateConfig}' \
  --output json
```

What it does: lists the cluster's node groups, then reads the same fields you saw in the console in Hands-on A. `updateConfig` is new since Lab 08: it is the "maximum unavailable" setting for rolling replacement.

```text
{
    "Status": "ACTIVE",
    "Capacity": "ON_DEMAND",
    "Types": [ "t3.small" ],
    "Ami": "AL2023_x86_64_STANDARD",
    "Scaling": { "minSize": 2, "maxSize": 6, "desiredSize": 3 },
    "Update": { "maxUnavailable": 1 }
}
```

> Example output - yours will differ. Scaling reads 2/4/2 if you restored Lab 07's numbers in Lab 08 Step 10. `Capacity` or `Update` may be `null` on Floci.

!!! note "Floci Limitation - node group settings are recorded, not enacted"
    Floci stores and returns the node group's instance types, AMI type, capacity type and scaling numbers, and may leave fields it does not model (such as `updateConfig` or `capacityType`) empty. No EC2 instances, Auto Scaling group or AMI exist behind it.

    On real AWS these fields drive a real Auto Scaling group and launch template, and `updateConfig` decides how many nodes a version upgrade replaces at once, which is what you read in the console on the shared cluster.

    Take away the field names and what each controls. Do not claim you sized or upgraded a fleet.

**Path B:** skip this step; your build has no node group object. Read the JSON shape above and answer the why question from it.

*Why question:* `Capacity` is `ON_DEMAND`. If this group carried the enrolment API, what would you add before moving any traffic onto Spot?

???+ answer "Expected response"
    A separate Spot node group with several compatible instance types, only for interruption-tolerant work, while this On-Demand group stays able to carry essential traffic alone.

**Step 3: Look for add-ons (support may be partial).**

```bash
aws eks list-addons --cluster-name "$USMS_EKS_CLUSTER" --output json \
  || echo "list-addons not supported on this build"

aws eks describe-addon-versions --addon-name coredns \
  --query 'addons[0].addonVersions[0:3].addonVersion' --output json \
  || echo "describe-addon-versions not supported on this build"

kubectl get pods -n kube-system -o wide
```

What it does: asks the EKS API which managed add-ons the cluster has, and which CoreDNS add-on versions exist; then looks at what really runs in `kube-system`. The `kubectl` command only reads.

```text
{
    "addons": []
}
describe-addon-versions not supported on this build

NAME                                      READY   STATUS    NODE
coredns-6799fbcd5-abcde                   1/1     Running   usms-eks-cluster-ag0
local-path-provisioner-6c86858495-fghij   1/1     Running   usms-eks-cluster-srv0
metrics-server-54fd9b65b-klmno            1/1     Running   usms-eks-cluster-ag1
```

> Example output - yours will differ. The exact `kube-system` Pods depend on the k3s version and on what Lab 08 installed.

!!! note "Floci Limitation - k3s components, not EKS add-ons"
    Floci's cluster is k3s, which ships its own CoreDNS and builds Service proxying and Pod networking into k3s itself. There is no Amazon VPC CNI, so Pod IPs are not VPC addresses, and the EKS add-on API may return nothing or be unsupported.

    On real EKS, `aws eks list-addons` returns entries such as `vpc-cni`, `coredns`, `kube-proxy` and `eks-pod-identity-agent`, each with a version you pin, and `aws eks describe-addon` reports its health. The shared cluster's Add-ons tab showed exactly that.

    Take away the jobs: something must give Pods IPs, resolve Service names and route Service IPs. On EKS those are versioned add-ons you update between the control plane and the nodes.

*Why question:* CoreDNS runs on Floci even though the add-on list is empty. What does that tell you about the difference between "the component exists" and "it is an EKS add-on"?

???+ answer "Expected response"
    The component can run as ordinary Pods without being managed through the EKS API. The add-on wrapper adds a known version, configuration and an update operation visible in the EKS API and CloudTrail; loose installs are how clusters end up with unknown, never-updated versions.

**Step 4: Look for Fargate profiles (likely unsupported).**

```bash
aws eks list-fargate-profiles --cluster-name "$USMS_EKS_CLUSTER" --output json \
  || echo "list-fargate-profiles not supported on this build"

kubectl get nodes -l eks.amazonaws.com/compute-type=fargate
```

What it does: asks for the cluster's Fargate profiles, then lists any nodes with the label EKS puts on Fargate Pods' virtual nodes.

```text
list-fargate-profiles not supported on this build
No resources found
```

> Example output - yours will differ. An empty `fargateProfileNames` list is equally possible.

!!! note "Floci Limitation - no Fargate behind EKS"
    Floci has no serverless compute behind its EKS API, so there are no Fargate profiles and no `fargate-` nodes. Treat any response as "not demonstrable locally".

    On real EKS, each running Fargate Pod appears as its own `fargate-` node in `kubectl get nodes`, and that label selector shows what is running (and billing) on Fargate.

    Take away the shape. A real `describe-fargate-profile` response holds the profile name and ARN, the Pod execution role ARN, the private subnet IDs, the selectors (each a namespace plus optional labels) and a status.

*Why question:* on a real cluster with a Fargate profile for namespace `ci`, three CI Pods are running. How many lines would `kubectl get nodes -l eks.amazonaws.com/compute-type=fargate` print, and why?

???+ answer "Expected response"
    Three: one micro-VM, shown as one `fargate-` node, per Pod. There is no shared node.

**Step 5: Build the blocking PDB in a new namespace.** Everything below uses `-n u3t3` explicitly, because Lab 07 Step 12 made `usms` your context's default namespace.

```bash
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: u3t3
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: portal
  namespace: u3t3
spec:
  replicas: 3
  selector:
    matchLabels:
      app: portal
  template:
    metadata:
      labels:
        app: portal
    spec:
      containers:
        - name: web
          image: nginx:1.27-alpine
          resources:
            requests:
              cpu: 50m
              memory: 32Mi
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: portal-pdb
  namespace: u3t3
spec:
  minAvailable: 3
  selector:
    matchLabels:
      app: portal
EOF

kubectl rollout status deployment/portal -n u3t3 --timeout=120s
kubectl get pdb -n u3t3
kubectl get pods -n u3t3 -o wide
```

What it does: creates a namespace, a 3-replica Deployment and a PDB that demands all 3 stay available. The heredoc is quoted (`<< 'EOF'`) so the shell expands nothing inside the manifest. `rollout status` waits until all three replicas are ready.

```text
NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
portal-pdb   3               N/A               0                     8s

NAME                      READY   STATUS    NODE
portal-7c9d8f6b5d-2xkqz   1/1     Running   usms-eks-cluster-ag0
portal-7c9d8f6b5d-9hjtw   1/1     Running   usms-eks-cluster-ag1
portal-7c9d8f6b5d-r4mvn   1/1     Running   usms-eks-cluster-ag0
```

> Example output - yours will differ.

*Why question:* the Deployment is healthy and the PDB looks reasonable ("keep everything up"). Why is `ALLOWED DISRUPTIONS` 0, and why is that dangerous on upgrade day rather than today?

???+ answer "Expected response"
    3 replicas minus `minAvailable: 3` leaves zero slack, so no voluntary eviction is allowed. Nothing evicts Pods today, so nothing visibly fails; the problem appears only when a node group upgrade drains a node.

**Step 6: Predict the drain (do not run one).**

!!! prompt "Predict"
    A managed node group upgrade cordons the node hosting two `portal` Pods and starts draining it. Describe exactly what happens to the drain, the upgrade and the `portal` Pods.

???+ answer "Expected response"
    The drain asks the eviction API to remove a `portal` Pod; the PDB refuses (`ALLOWED DISRUPTIONS: 0`). The drain retries, the old node never empties, and the node group update eventually times out. The `portal` Pods keep running; it is the upgrade that is stuck.

Optional proof, if time allows (it touches only namespace `u3t3`): ask the eviction API, the same API a drain uses, to evict one `portal` Pod.

```bash
POD=$(kubectl get pods -n u3t3 -l app=portal -o jsonpath='{.items[0].metadata.name}')

cat > outputs/u3t3-eviction.json << EOF
{
  "apiVersion": "policy/v1",
  "kind": "Eviction",
  "metadata": { "name": "$POD", "namespace": "u3t3" }
}
EOF

kubectl create --raw "/api/v1/namespaces/u3t3/pods/$POD/eviction" \
  -f outputs/u3t3-eviction.json 2>&1 | tail -1
```

This heredoc is **unquoted** (`<< EOF`) because `$POD` must expand to a real Pod name; contrast with Step 5.

```text
Error from server (TooManyRequests): Cannot evict pod as it would violate the pod's disruption budget.
```

> Example output - yours will differ slightly by Kubernetes version.

!!! teacher "Do not drain, do not cordon"
    The Floci cluster's nodes also carry the Lab 07/08 `usms` workloads. Lab 08 already showed `kubectl drain --dry-run=client`, which only lists Pods and does not consult PDBs, so it would not show the block. The eviction call above is the safe way to prove the property: create, perturb, read back, inside `u3t3` only.

**Step 7: Fix the PDB and re-read it.**

```bash
kubectl apply -f - << 'EOF'
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: portal-pdb
  namespace: u3t3
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: portal
EOF

kubectl get pdb -n u3t3
```

What it does: re-applies the PDB with `maxUnavailable: 1` instead of `minAvailable: 3`. Because the earlier object was also created with `kubectl apply`, the field removed from the file is removed from the object.

```text
NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
portal-pdb   N/A             1                 1                     2m
```

> Example output - yours will differ. If `apply` reports that both fields cannot be set, run `kubectl delete pdb portal-pdb -n u3t3` and apply again.

If you ran the optional eviction, run the same `kubectl create --raw` command again: this time it succeeds, one `portal` Pod terminates and the Deployment immediately creates a replacement (`kubectl get pods -n u3t3`).

*Why question:* why is `maxUnavailable: 1` usually a better choice than `minAvailable: 2` for a Deployment whose replica count changes with load?

???+ answer "Expected response"
    `maxUnavailable` scales with the replica count: it always allows one disruption whether there are 3 or 8 replicas. A fixed `minAvailable` floor becomes zero slack again if the Deployment scales down to that number.

**Success criteria**

- [ ] Confirmed identity and support path; worked only in `u3t3`
- [ ] Read the node group's capacity type, scaling and update configuration (or the JSON shape on Path B)
- [ ] Recorded which add-on and Fargate calls the build supports, labelled as Floci limitations
- [ ] Built a PDB with `ALLOWED DISRUPTIONS: 0` and explained why it blocks a node group upgrade
- [ ] Fixed it to `maxUnavailable: 1` and saw `ALLOWED DISRUPTIONS: 1`
- [ ] Cordoned and drained nothing; did not touch namespace `usms`

!!! teacher "Console versus CLI comparison (1 minute)"
    Ask: what did the console show that Floci could not, and what did Floci show that the console did not? Expected: the console showed real AMIs, an Auto Scaling group, add-on versions and Fargate's private-subnet rule; Floci showed the Kubernetes behaviour that actually blocks upgrades, which you cannot safely provoke on a shared real cluster.

## Break { data-minutes="5" .break }

!!! teacher "During the break"
    Check that every student's `kubectl get pdb -n u3t3` shows the fixed PDB, and that nobody has a resource in the console besides the shared cluster.

## Recap and clean-up { data-minutes="10" }

[3.3 Summary](../unit3/topic3.md#summary){ .notes-link target="_blank" }
[3.3 Common mistakes](../unit3/topic3.md#common-mistakes){ .notes-link target="_blank" }

**Key lessons (4 minutes).** Ask a student to complete each line before showing it.

| Feature | Key lesson |
|---|---|
| Data plane choice | Per workload. Fargate and node groups share one cluster |
| Fargate | Pod = micro-VM. Every limit (no DaemonSets, EBS, GPUs, Pod Identity, privileged) follows from "no node"; the rounded-up request is the bill |
| Fargate profiles | Namespace required; labels AND, selectors OR; immutable; private subnets; design around stable namespaces |
| Managed node groups | Still EC2. EKS handles AMIs, the Auto Scaling group, replacement and rolling cordon-and-drain updates |
| PDBs | Protect availability during drains, but zero slack blocks upgrades |
| Spot | Several instance types, tolerant workloads, On-Demand base, multiple AZs |
| Add-ons | Pin versions, own IAM roles, update between control plane and nodes |

**Clean-up (6 minutes).**

!!! danger "Read before running any delete command"
    **What will be deleted:** the `u3t3` namespace and everything in it (the `portal` Deployment, its Pods and `portal-pdb`), the file `outputs/u3t3-eviction.json`, and any console resource tagged `Session=u3t3`.
    **What depends on it:** nothing. Namespace `usms` and the Lab 07/08 resources are separate and must not be touched.
    **Reversible?** Yes, by re-applying the Step 5 manifest; nothing in it holds data.
    **Effect on later labs:** none.

**Step 1: Floci.**

```bash
kubectl delete namespace u3t3
rm -f outputs/u3t3-eviction.json

kubectl get namespace u3t3 2>&1 | tail -1
kubectl get deploy -n usms
```

Expected: the namespace is `Terminating` and then `NotFound`; the `usms` Deployments are still there and unchanged. Do **not** stop Floci or delete `~/floci-data`; `./scripts/setup/floci-down.sh` is fine if you are finished for the day.

**Step 2: Console (only if you created anything).** Delete it, then verify in **Resource Groups & Tag Editor**, **Tag Editor**: Region `us-east-1` (or the class Region), resource types **All supported resource types**, tag `Session` = `u3t3`. The result must be **empty**.

**Step 3: Confirm the shared cluster is untouched.** Its node group still shows 2 nodes and no extra Fargate profile or node group exists on the **Compute** tab.

- [ ] `u3t3` namespace gone; `usms` unchanged
- [ ] Tag Editor search for `Session=u3t3` empty (if anything was created)
- [ ] No Fargate profile or extra node group on `dso303-u3-shared`

!!! teacher "Transition"
    "The shared cluster is deleted after class, by me. Now let's see what stuck."

## Quiz { data-minutes="30" }

!!! quiz "ClassLegend quiz: 3.3 Amazon EKS Advanced Concepts"
    Bank of 117 questions in `private/quizzes/unit3-topic3.questions.md` covering the compute-management spectrum, Fargate profiles and selectors, Fargate limitations and billing, managed node groups and AMIs, rolling upgrades with cordon, drain and `updateConfig`, PodDisruptionBudgets, Spot and multi-AZ design, EKS add-ons, choosing Fargate or node groups per workload, and the console and Floci CLI steps from this lesson. Run as many as fit about 25 minutes, then spend 5 minutes reviewing the most-missed questions.

---

## After class

- [ ] Delete the shared cluster: follow [Shared EKS cluster: delete everything](unit3-shared-eks-cluster.md#after-class-delete-everything) (node group first, then the cluster)
- [ ] **Resource Groups & Tag Editor** across the class account: tag `Session` = `u3t3` returns nothing, and tag `Session` = `u3-shared` returns nothing after the cluster is deleted
- [ ] Check EC2 for leftover instances, unattached volumes and load balancers, as listed on the shared page
- [ ] Next day: **Billing and Cost Management** shows no ongoing EKS or EC2 charges
- [ ] AWS Academy Learner Lab: **End Lab**
- [ ] Note the most-missed quiz questions for the start of the next lecture

---

## Command reference

| Command | Purpose |
|---|---|
| `./scripts/setup/floci-up.sh` | Start or resume Floci (never `floci start`) |
| `aws eks list-nodegroups --cluster-name "$USMS_EKS_CLUSTER"` | List node groups |
| `aws eks describe-nodegroup --cluster-name ... --nodegroup-name ...` | Read scaling, capacity type, AMI type, update configuration |
| `aws eks list-addons --cluster-name ...` | List EKS-managed add-ons (partial or unsupported on Floci) |
| `aws eks describe-addon-versions --addon-name coredns` | Available versions of an add-on |
| `aws eks list-fargate-profiles --cluster-name ...` | List Fargate profiles (likely unsupported on Floci) |
| `kubectl get nodes -l eks.amazonaws.com/compute-type=fargate` | Show Fargate Pods' virtual nodes |
| `kubectl get pdb -n <ns>` / `kubectl get pdb -A` | Read `ALLOWED DISRUPTIONS` before an upgrade |
| `kubectl delete namespace u3t3` | Clean up today's practice work |

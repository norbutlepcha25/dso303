# Unit 3: Shared EKS Cluster for Class

One small Amazon EKS cluster, created by the teacher before each Unit 3 lecture and deleted straight after. Students explore it in the console; nobody else creates a cluster.

| | |
|---|---|
| **Cluster name** | `dso303-u3-shared` |
| **Region** | `us-east-1` (or the Region your class uses) |
| **Tags** | `Course=DSO303`, `Session=u3-shared` |
| **Size** | One managed node group, 2 × `t3.medium` |
| **Create** | About 15–20 minutes. Start at least 30 minutes before class |
| **Cost** | Billed per hour: the EKS control plane fee plus two small EC2 instances and their storage. A 3-hour window costs a few dollars. Check the current EKS and EC2 pricing pages |
| **Used by** | [3.1 lecture](unit3-topic1-lecture.md) · [3.2 lecture](unit3-topic2-lecture.md) · [3.3 lecture](unit3-topic3-lecture.md) |

!!! warning "Delete it the same day"
    A forgotten cluster keeps charging every hour for the control plane and both nodes. Put a calendar reminder for straight after class.

## Before class: create the cluster

**Step 1: Open EKS.** Console, then **Elastic Kubernetes Service**, then **Create cluster**. Choose **Custom configuration** (not Quick configuration with EKS Auto Mode), so the cluster shows managed node groups and add-ons the way the notes describe them.

**Step 2: Configure the cluster.**

| Field | Value |
|---|---|
| Name | `dso303-u3-shared` |
| Kubernetes version | The default (newest in standard support) |
| Cluster IAM role | A role with the `AmazonEKSClusterPolicy`. **AWS Academy Learner Lab:** choose `LabRole` |
| Cluster access: authentication mode | `EKS API` (access entries) |
| Bootstrap cluster administrator access | Allow (your identity becomes admin) |
| Tags | `Course=DSO303`, `Session=u3-shared` |

**Step 3: Networking.** Default VPC, at least two subnets in **different Availability Zones**, the default cluster security group, endpoint access **Public and private**.

**Step 4: Observability.** Leave defaults. Control plane logging off keeps cost down for a teaching cluster.

**Step 5: Add-ons.** Keep the defaults: Amazon VPC CNI, CoreDNS, `kube-proxy`, EKS Pod Identity Agent. Default versions are fine.

**Step 6: Review and create.** Wait until the status is **Active** (about 10–15 minutes).

**Step 7: Add the node group.** Cluster, then **Compute**, then **Add node group**.

| Field | Value |
|---|---|
| Name | `dso303-u3-nodes` |
| Node IAM role | A role with `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy` and `AmazonEC2ContainerRegistryReadOnly`. **Learner Lab:** `LabRole` |
| AMI type | Amazon Linux 2023 |
| Capacity type | On-Demand |
| Instance type | `t3.medium` |
| Scaling | Desired 2, minimum 1, maximum 2 |
| Subnets | The same subnets as the cluster |
| Tags | `Course=DSO303`, `Session=u3-shared` |

Wait until the node group is **Active** and the **Compute** tab shows two nodes **Ready** (about 5 minutes).

**Step 8: Give students a view.** Pick the case that matches your class:

| Your class | Do this |
|---|---|
| Students sign in to **the same AWS account** as you | Cluster, then **Access**, then **Create access entry** for the students' IAM role. Attach the access policy `AmazonEKSViewPolicy`, scope **Cluster**. They can now browse the **Resources** tab read-only |
| Each student has **their own account** (for example AWS Academy Learner Lab) | Students cannot see your cluster. Explore it from your screen while they follow along, and they do the wizard walk-through in their own accounts |

**Step 9 (optional): Put something in it.** From CloudShell or your terminal:

```bash
aws eks update-kubeconfig --name dso303-u3-shared --region us-east-1
kubectl create deployment portal --image=nginx:stable --replicas=3
kubectl get pods -o wide
```

Students then see real Pods, their node placement and their VPC IP addresses in the console.

!!! danger "Do not create a LoadBalancer Service or a PersistentVolumeClaim"
    Either one creates AWS resources (a load balancer or an EBS volume) outside the cluster that survive deleting it, and keep billing. Use `ClusterIP` Services only on the shared cluster.

## After class: delete everything

!!! danger "Read before running any delete command"
    **What will be deleted:** the `dso303-u3-shared` cluster, its node group and the two EC2 nodes.
    **What depends on it:** nothing outside class. Student Floci work is separate and unaffected.
    **Reversible?** No. You recreate it from the steps above next time.
    **Effect on later lessons:** none; every Unit 3 lecture recreates it.

**Step 1: Delete Kubernetes objects that create AWS resources** (only if you made any):

```bash
kubectl get svc -A | grep LoadBalancer     # delete any listed
kubectl get pvc -A                         # delete any listed
kubectl delete deployment portal --ignore-not-found
```

**Step 2: Delete the node group.** Cluster, then **Compute**, select `dso303-u3-nodes`, **Delete**. Wait until it disappears (about 5 minutes). The cluster cannot be deleted while a node group exists.

**Step 3: Delete the cluster.** EKS, select `dso303-u3-shared`, **Delete**, type the name to confirm. Wait until it disappears (about 5 minutes).

**Step 4: Verify nothing is left.** Console, then **Resource Groups & Tag Editor**, then **Tag Editor**:

- Regions: your class Region
- Resource types: **All supported resource types**
- Tag: `Session` = `u3-shared`

The result must be **empty**. Then check these, which do not always carry tags:

- [ ] EC2, **Instances**: no `dso303-u3-nodes` instances running or stopping
- [ ] EC2, **Volumes**: no unattached volumes from the nodes
- [ ] EC2, **Load Balancers**: none created by the cluster
- [ ] VPC, **Network interfaces**: no leftover `aws-K8S` or EKS interfaces
- [ ] Next day: **Billing and Cost Management** shows no ongoing EKS or EC2 charges
- [ ] AWS Academy Learner Lab: **End Lab**

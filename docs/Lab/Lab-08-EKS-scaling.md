# Lab 08 - EKS Scaling and Service Exposure

*Practical 4 - making the cluster grow, and letting the world in*

!!! info "Numbering - the same note as Lab 07"
    Your module descriptor numbers this practical **3**; the course delivers it as **Practical 4**,
    in two documents. This is the second. Laboratory numbering follows the dependency graph:

    ```text
    Practical 2  ->  Lab 04, Lab 05, Lab 06   (ECS, ALB, service auto scaling)
    Practical 4  ->  Lab 07, Lab 08            (EKS)   <- descriptor Practical 3
    then         ->  Lab 09 (security), Lab 10 (Lambda), Lab 11-12 (CI/CD), Lab 13 (monitoring)
    ```

---

## 1. Lab Overview

Lab 07 left the USMS application in a deliberately awkward state. Three microservices, all healthy,
all discoverable by DNS - and completely unreachable from outside the cluster. Nothing you built has
an external address. If a student opened the portal right now, nothing would answer.

That was not an oversight. Proving service discovery *from inside* first, before adding a front door,
is what stops the front door from hiding a broken back end.

This laboratory answers the two questions Lab 07 left open, and they turn out to be one question
asked twice:

```text
HOW DOES IT GROW?          replicas -> HorizontalPodAutoscaler -> node group -> cluster autoscaler
HOW DOES ANYONE REACH IT?  ClusterIP -> port-forward -> NodePort -> LoadBalancer -> Ingress
```

Both are **ladders**, and in both cases each rung is built on the one below it and adds exactly one
thing. A NodePort Service is still a ClusterIP Service with a port bolted on. A LoadBalancer Service
is still a NodePort Service with something in front of it. An HPA does not replace `replicas`; it
writes to the same field you set by hand in Step 4. Students who see the ladders find the whole
subject small; students who learn five unrelated recipes find it enormous.

**The single most important idea in this lab** - and the one Section 15 asks about twice - is that
**scaling is one integer**. Lab 06 established that: Application Auto Scaling's entire job was to
write `desiredCount`. Kubernetes is the same, with `replicas`. What differs between the platforms is
not the mechanism but *where the thing writing the integer lives*:

```text
Lab 06   Application Auto Scaling   an AWS service   OUTSIDE your workload   writes desiredCount
Lab 08   HorizontalPodAutoscaler    a controller     INSIDE your cluster     writes replicas
```

That difference has consequences for blast radius, for what you can debug, and for what happens when
the control plane you do not own has a bad afternoon. Step 17 makes you write them down.

**Time:** roughly 4 hours, including the exercises.

**Where this sits in the course**

```text
Lab 04  ECS + Fargate ....... cluster, task definition, service
Lab 05  ECS + ALB ........... load balancer, target group, listener
Lab 06  Service Auto Scaling  target tracking, step, scheduled
Lab 07  EKS ................. cluster, node group, three microservices, service discovery
Lab 08  EKS scaling and exposure   THIS LAB
Lab 10   S3 .................. the bucket that three IAM policies already name
Lab 07   Lambda .............. functions triggered from that bucket
```

!!! warning "Two things from Lab 07 must be true before you start"
    **`usms-enrolment` must declare a CPU request.** Lab 07 Step 13 set `50m`. The HPA computes
    utilisation as a percentage *of the request*. With no request, utilisation is undefined, the HPA
    reports `<unknown>` forever, and no amount of load generation will make it scale. Step 1 checks
    this first.

    **The cluster must carry the `_lb_ports_` tag.** Lab 07 Step 8 set it to `8081,8082`. Without
    it, Step 15 has no host port to publish on and the remedy is to recreate the cluster.

    Both are checked in Step 1, and both are five-minute fixes today.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. **Name** the four independent dimensions along which a Kubernetes workload can scale, and say
   which object controls each.
2. **Scale** a Deployment imperatively and declaratively, and explain the configuration drift that
   results from mixing the two.
3. **Explain** how a HorizontalPodAutoscaler computes utilisation, and why a missing resource request
   makes it inert.
4. **Deploy** an `autoscaling/v2` HPA with an explicit `behavior` block, and map every field in it to
   its Lab 06 equivalent.
5. **Generate** load against a service and **observe** an autoscaler responding - or diagnose,
   honestly and specifically, why it did not.
6. **Change** a managed node group's scaling configuration from the AWS CLI, and say why that is a
   different operation from scaling a Deployment.
7. **Distinguish** the Cluster Autoscaler and Karpenter from the HorizontalPodAutoscaler, in one
   sentence each.
8. **Write** a PodDisruptionBudget and say what it does and does not protect against.
9. **Expose** a Service four different ways - `port-forward`, `NodePort`, `LoadBalancer`, `Ingress` -
   and choose correctly between them for a given requirement.
10. **Compare** Kubernetes Ingress with the Application Load Balancer of Lab 05, in both directions,
    naming what the AWS Load Balancer Controller does to close the gap.
11. **Prove** that scaling configuration and exposure configuration survive a restart of the emulator.

---

## 3. Prerequisites

### 3.1 Completed laboratories

- **Lab 07**, complete, with `configs/lab-07.env` populated and `verify-lab-07.sh` passing -
  `FAIL=0` on support Path A, `FAIL=3` on Path B.
- **Lab 05 and 06**, for the comparisons in Steps 15, 16 and 17. Nothing from them is consumed
  directly; everything from them is referenced.
- **Lab 02**, whose public subnets are what a real EKS LoadBalancer Service would use.

### 3.2 Tools

The same set as Lab 07. Nothing new is required, though two optional things help:

| Tool | Needed for | Check |
| --- | --- | --- |
| `kubectl` | Everything | `kubectl version --client` |
| AWS CLI v2 | Step 10 only | `aws --version` |
| `watch` (optional) | Watching numbers move; `kubectl get -w` is the alternative | `which watch` |
| `curl` (optional) | Step 15's host-side check; `wget` inside a pod is the alternative | `curl --version` |

### 3.3 Knowledge assumed

Everything in Lab 07, and specifically: the `spec` and `status` controller loop from its Step 12;
the difference between a Deployment and a Service; and why `kubectl get endpoints` is the first
command to run when a Service returns nothing.

From Lab 06: target tracking, cooldown, and the idea that an autoscaler owns a field you then stop
editing by hand.

### 3.4 Support paths, carried forward

Lab 07 Step 2 recorded a support path in `notes/lab-07-notes.md`. It still applies:

| Path | This lab |
| --- | --- |
| **A** | Everything. Step 10 is the only step that needs the `eks` API |
| **B** | Everything except Step 10. The Kubernetes half - which is most of this lab - is unaffected |
| **C** | Section 8.5's paper path. This lab is harder to do on paper than Lab 07, because its subject is watching numbers move |

---

## 4. Connection to Previous Labs

### 4.1 Current Environment

```text
Created in previous labs:
- Lab 01: usms-developer-role; USMSStudentDataReadWrite, now on three roles
- Lab 02: usms-vpc; public-a/-b and private-a/-b; igw, nat, route tables, s3 endpoint
- Lab 03: usms-web-01, usms-db-01, usms-web-golden
- Lab 04: usms-ecs-cluster, usms-enrolment-svc, /usms/ecs/enrolment
- Lab 05: usms-enrolment-alb, usms-enrolment-tg, listener HTTP:80, rule prio 10
- Lab 06: scalable target min 2 max 10; CPU and request-count target tracking;
           one step policy; two scheduled actions
- Lab 07: usms-eks-cluster (tag _lb_ports_=8081,8082), usms-eks-nodes (min 2/max 4/desired 2),
           usms-eks-cluster-role, usms-eks-node-role, usms-eks-cluster-sg
- Lab 07: namespace usms - gateway, enrolment, results; 4 ConfigMaps; 1 Secret;
           usms-enrolment declaring requests cpu=50m mem=32Mi

Created in this lab:
- usms-loadgen                 Deployment, 3 replicas - the load source, deleted at the end
- usms-enrolment-hpa           HorizontalPodAutoscaler, autoscaling/v2, min 2 max 8, CPU 50%
- usms-gateway-pdb             PodDisruptionBudget, minAvailable 1
- usms-results-np              Service, type NodePort - the second rung of the exposure ladder
- usms-gateway becomes         type LoadBalancer (from ClusterIP)
- usms-portal-ingress          Ingress, path routing /enrolment and /results
- usms-eks-nodes rescaled      min 2 / max 6 / desired 3, from the AWS side
- nodeSelector workload=usms   on usms-enrolment, using Lab 07's node group labels

Required for future labs:
- nothing structural. Lab 10 (S3) consumes this lab's Exercise 5 artefacts and
  Lab 01's policy; the CloudWatch lab later reads the metrics discussed in Step 7;
  the CloudFormation lab re-declares Practical 2 and Practical 4 as one template
```

### 4.2 What this lab genuinely reuses

| From | Used in | Consequence if it is missing |
| --- | --- | --- |
| Lab 07 `usms-enrolment` CPU request `50m` | Step 8, the HPA's denominator | The HPA reports `<unknown>` and never scales. This is the single most common HPA failure |
| Lab 07 `_lb_ports_=8081,8082` | Step 15 | No host port is published; the LoadBalancer Service is unreachable from your machine |
| Lab 07 node group labels `workload=usms` | Step 11's `nodeSelector` | Pods stay `Pending` with `didn't match node selector` |
| Lab 07 `usms-gateway` Service | Steps 13 to 16 | The whole exposure ladder is climbed on this one object |
| Lab 05 `usms-enrolment-tg` target type `ip` | Step 16's comparison | You lose the connection that makes Ingress on EKS make sense |
| Lab 06's scalable target | Steps 8 and 17 | You lose the comparison this lab is built around |

**The sentence to say out loud, at Step 16.** Lab 05 created an ALB with a target group of type
`ip`, and the ECS service registered task addresses into it. On real EKS, the AWS Load Balancer
Controller reads an Ingress object and creates *exactly that same ALB*, with *exactly that same
target type*, registering pod addresses instead of task addresses. The Kubernetes object is portable;
the ALB underneath it is the one you already built by hand four weeks ago. Recognising that is the
moment Practical 2 and Practical 4 stop being two separate topics.

---

## 5. What We Are Building

Two ladders, climbed one rung at a time, plus one AWS-side operation.

**The scaling ladder**

```text
Step 4   kubectl scale                 you write the integer
Step 5   replicas: in the manifest     Git writes the integer
Step 8   HorizontalPodAutoscaler       a controller inside the cluster writes the integer
Step 10  update-nodegroup-config       you write a DIFFERENT integer, on the AWS side
Step 11  Cluster Autoscaler/Karpenter  a controller writes that one too   (conceptual)
```

**The exposure ladder**

```text
Step 13  ClusterIP + port-forward   reachable by you, over the API server, for debugging only
Step 14  NodePort                   reachable on a fixed high port on every node
Step 15  LoadBalancer               reachable on one address; on AWS, a real NLB appears
Step 16  Ingress                    ONE address for MANY services, routed by path
```

And in between, three things that are not on either ladder but that a production system needs:
resource requests and QoS classes (Step 6), the metrics pipeline (Step 7), and a PodDisruptionBudget
(Step 12).

What you will **not** build: a second cluster, a second application, or anything that replaces Lab
07's work. Every object in this lab either modifies something Lab 07 created or sits in front of it.

---

## 6. Architecture

```text
                                     YOUR MACHINE

  browser / curl  ---> localhost:8081  ------+
                                             |   published because Lab 07 tagged the
                                             |   cluster _lb_ports_=8081,8082
                                             v
  +-----------------------------------------------------------------------------------+
  |                              INSIDE THE CLUSTER                                   |
  |                                                                                   |
  |   Ingress usms-portal-ingress          (Step 16)                                  |
  |     /enrolment  -> Service usms-enrolment                                         |
  |     /results    -> Service usms-results                                           |
  |     /           -> Service usms-gateway                                           |
  |          |                                                                        |
  |          |    ... needs an ingress controller. Which one, and whether one is       |
  |          |        running, is Step 16's whole subject                              |
  |          v                                                                        |
  |   Service usms-gateway   type LoadBalancer   (Step 15)                            |
  |     was ClusterIP in Lab 07, was NodePort at Step 14 -- each rung KEEPS the       |
  |     one below it: a LoadBalancer Service still has a nodePort and a clusterIP      |
  |          |                                                                        |
  |          v                                                                        |
  |   Deployment usms-gateway  1 replica                                              |
  |          |  proxy_pass by DNS name, unchanged from Lab 07                        |
  |          +-------------------------------+                                        |
  |          v                               v                                        |
  |   Deployment usms-enrolment        Deployment usms-results                        |
  |     replicas 2 .. 8                  replicas 2                                   |
  |        ^                             Service usms-results     (ClusterIP)         |
  |        |                             Service usms-results-np  (NodePort, Step 14) |
  |        |                                                                          |
  |   HorizontalPodAutoscaler usms-enrolment-hpa      (Step 8)                        |
  |     reads   metrics.k8s.io  <- metrics-server     (Step 7)                        |
  |     writes  usms-enrolment.spec.replicas                                          |
  |     target  cpu 50% of the 50m request set in Lab 07                             |
  |                                                                                   |
  |   Deployment usms-loadgen  3 replicas  (Step 9)   busybox, wget in a loop         |
  |     the load source. Deleted in Section 16                                        |
  |                                                                                   |
  |   PodDisruptionBudget usms-gateway-pdb  minAvailable 1   (Step 12)                |
  |                                                                                   |
  +-----------------------------------------------------------------------------------+

                                 AWS SIDE, Step 10 only

  usms-eks-nodes   min 2 / max 6 / desired 3      <- a DIFFERENT integer from replicas
    subnets private-a, private-b                     nothing writes it automatically
    labels workload=usms, tier=app                   unless a Cluster Autoscaler exists
```

The one structural thing to take from that picture: **the HPA and the node group are two separate
control loops that do not know about each other.** The HPA adds pods; if there is no room, the pods
sit `Pending`. Something else must notice `Pending` pods and add nodes. On real EKS that something is
the Cluster Autoscaler or Karpenter, and Step 11 explains why this lab does not install one.

---

## 7. Directory Structure

This lab adds the following. It creates no new folder - Lab 07's `manifests/` is the home for all of
it.

```text
aws-floci-course/
├── labs/
│   └── lab-08-eks-scaling/
│       ├── README.md                          # this document
│       └── exercises.md                       # Section 13
├── manifests/
│   └── lab-08/
│       ├── 10-hpa-enrolment.yaml
│       ├── 20-loadgen.yaml
│       ├── 30-pdb-gateway.yaml
│       ├── 40-service-nodeport.yaml
│       ├── 50-service-loadbalancer.yaml
│       └── 60-ingress.yaml
├── configs/
│   └── lab-08.env                            # NEW
├── scripts/
│   ├── utilities/
│   │   ├── verify-lab-08.sh                  # NEW - Section 9
│   │   └── hpa-watch.sh                       # NEW - Step 9
│   └── cleanup/
│       └── lab-08-cleanup.sh                 # NEW - end of course only
└── outputs/
    └── lab-08-*.txt / *.json                 # command output, git-ignored
```

Note that `50-service-loadbalancer.yaml` is a **full Service manifest**, not a patch. Steps 14 and 15
both change `usms-gateway`'s type, and both do it by re-applying a complete declarative file rather
than with `kubectl patch`. That is deliberate and Step 14 says why: a patch changes the cluster and
leaves your repository lying about what the cluster contains.

Create the folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-08-eks-scaling manifests/lab-08
ls -d manifests/*
```

> Example output:

```text
manifests/lab-07  manifests/lab-08
```

---
## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Lab 07 set your `kubectl` context's default namespace to `usms`, so `-n usms` is omitted below.
    If a command reports `No resources found in default namespace`, that setting did not survive -
    re-run:

    ```bash
    kubectl config set-context --current --namespace=usms
    ```

    Shell variables still die with the terminal. Step 19 writes this lab's to `configs/lab-08.env`.

---

### Step 1 - Start the environment, and check the two things Lab 07 had to leave behind

**Purpose**

Two values from Lab 07 determine whether this lab can be done at all. Checking them takes ninety
seconds and saves an hour of load generation against an autoscaler that was never going to move.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, start and source**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-04.env
source configs/lab-07.env

./scripts/utilities/whoami.sh
kubectl config current-context
kubectl config set-context --current --namespace=usms
```

**Command - part 2, the two checks that matter**

```bash
echo "--- 1. does usms-enrolment declare a CPU request? ---"
kubectl get deploy usms-enrolment \
  -o jsonpath='{.spec.template.spec.containers[0].resources.requests}'; echo

echo "--- 2. is the _lb_ports_ tag on the cluster? ---"
echo "from configs/lab-07.env : ${USMS_EKS_LB_PORTS:-EMPTY}"
aws eks describe-cluster --name "$USMS_EKS_CLUSTER" \
  --query 'cluster.tags._lb_ports_' --output text 2>/dev/null || echo "eks API unavailable (Path B)"
```

**Expected result**

```text
--- 1. does usms-enrolment declare a CPU request? ---
{"cpu":"50m","memory":"32Mi"}
--- 2. is the _lb_ports_ tag on the cluster? ---
from configs/lab-07.env : 8081,8082
8081,8082
```

**What to look for, and what to do if it is wrong:**

- **An empty or absent `cpu` request.** Fix it now; Step 8 depends on it and no later step can work
  around it:

    ```bash
    kubectl set resources deployment/usms-enrolment \
      --requests=cpu=50m,memory=32Mi --limits=cpu=200m,memory=128Mi
    kubectl rollout status deployment/usms-enrolment --timeout=120s
    ```

    Then fix `manifests/lab-07/20-enrolment.yaml` too, so the repository and the cluster agree. A
    cluster that is right and a repository that is wrong is worse than both being wrong, because it
    is invisible until the next `kubectl apply`.

- **`None` for the tag on Path A.** Try `aws eks tag-resource` as Lab 07 Step 9 showed. If that
  fails, Step 15 will be a Conceptual step for you rather than an observable one. Record that in
  `notes/lab-08-notes.md` now, so your report is accurate rather than apologetic.

- **`eks API unavailable` on Path B.** Expected. Steps 10 and 15's AWS half are unavailable to you;
  everything else in this lab works.

**Verify**

```bash
./scripts/utilities/verify-lab-07.sh | tail -3
kubectl get deploy,svc,cm,secret
```

**What to look for:** `FAIL=0` (Path A) or `FAIL=3` (Path B); three Deployments reading `2`, `2` and
`1`; three ClusterIP Services with no external address; four ConfigMaps; one Secret.

---

### Step 2 - Read your own baseline before you change anything

**Purpose**

Lab 07 Exercise 5 asked you to record a CPU baseline. This step reads it back and captures a fresh
"before" snapshot, so that every number in the rest of this lab has something to be compared against.
An autoscaler that "seems to be working" is not a result; a replica count that went from 2 to 5 and
back is.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
mkdir -p notes outputs

echo "--- Lab 07 Exercise 5 artefacts ---"
ls -l outputs/lab-07-cpu-baseline.txt outputs/lab-07-lab06-readiness.txt 2>/dev/null \
  || echo "Exercise 5 not done - that is recoverable, but do it before Lab 10"

echo
echo "--- fresh baseline ---"
{
  echo "=== LAB 08 BASELINE $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  kubectl get deploy -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas'
  echo "--- endpoints ---"
  kubectl get endpoints
  echo "--- service types ---"
  kubectl get svc -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,CLUSTERIP:.spec.clusterIP,EXTERNAL:.status.loadBalancer.ingress[0].ip'
  echo "--- nodes ---"
  kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,CPU:.status.capacity.cpu,MEM:.status.capacity.memory'
} | tee outputs/lab-08-baseline.txt
```

**What the command does**

Four snapshots, all read-only, all in one file. The `custom-columns` forms are chosen so the output is
narrow enough to `diff` against later - Step 18 does exactly that.

`.status.loadBalancer.ingress[0].ip` will be empty for every Service right now. That is the point of
recording it: after Step 15 it will not be, and an empty column that later fills in is much more
convincing evidence than a column that was always there.

**Expected result**

```text
=== LAB 08 BASELINE 2026-09-06T03:40:11Z ===
NAME             DESIRED   READY
usms-enrolment   2         2
usms-gateway     1         1
usms-results     2         2
--- endpoints ---
NAME             ENDPOINTS                     AGE
usms-enrolment   10.42.1.8:80,10.42.2.5:80     3h
usms-gateway     10.42.1.9:80                  3h
usms-results     10.42.2.6:80,10.42.2.7:80     3h
--- service types ---
NAME             TYPE        CLUSTERIP       EXTERNAL
usms-enrolment   ClusterIP   10.43.118.204   <none>
usms-gateway     ClusterIP   10.43.201.77    <none>
usms-results     ClusterIP   10.43.9.61      <none>
--- nodes ---
NAME                    STATUS   CPU   MEM
usms-eks-cluster-srv0   Ready    8     8039720Ki
usms-eks-cluster-ag0    Ready    8     8039720Ki
```

> Example output - every address, capacity and node name will differ.

**What to look for:** three Deployments at their Lab 07 counts, every Service `ClusterIP` with
`<none>` external, and at least one node `Ready`. Note the node CPU capacity: on a local cluster the
nodes report your whole machine's cores, which is why Step 9's load generation has to be pointed at
the *pod's* request rather than at the node's capacity.

**Checkpoint 1**

```text
Baseline recorded in outputs/lab-08-baseline.txt
 ├── usms-enrolment  2/2   cpu request 50m   <- the HPA's denominator exists
 ├── usms-results    2/2
 ├── usms-gateway    1/1
 ├── all three Services ClusterIP, no external address
 └── cluster tag _lb_ports_ = 8081,8082  (or its absence recorded)
```

---

### Step 3 - The four dimensions of scaling, and which object owns each

**Purpose**

Before you move any number, know which of four independent things you are moving. Students who
cannot name the four spend the rest of the lab surprised.

**Run from**

Nothing to run. Read, then answer the question at the end.

**Concept - the four dimensions**

```text
1. HORIZONTAL, workload      more PODS of the same size
   object: Deployment.spec.replicas
   moved by: you, or a HorizontalPodAutoscaler
   limit: how much room the nodes have

2. VERTICAL, workload        BIGGER pods
   object: container.resources.requests / .limits
   moved by: you, or a VerticalPodAutoscaler (not installed here)
   limit: the largest node. A pod cannot be bigger than a node
   note: changing it restarts the pod. This is why VPA is used far less than HPA

3. HORIZONTAL, infrastructure    more NODES
   object: the managed node group's scalingConfig.desiredSize
   moved by: you (Step 10), or a Cluster Autoscaler / Karpenter (Step 11)
   limit: maxSize, and your quota and your budget

4. VERTICAL, infrastructure      BIGGER nodes
   object: the node group's instanceTypes
   moved by: you, by creating a NEW node group and draining the old one
   limit: not changeable in place. This is the one that requires planning
```

Three consequences, all of which you will meet:

- **Dimension 1 without dimension 3 gives you `Pending` pods.** The HPA adds replicas; if the nodes
  are full, that is all it does. Step 9's troubleshooting note covers this, and it is the commonest
  production surprise on EKS.
- **Dimension 2 is the HPA's denominator.** The `requests` you set for dimension 2 is what dimension
  1's autoscaler divides by. They are not independent, and Step 6 is about exactly that coupling.
- **Dimension 4 cannot be done in place.** A node group's instance types are fixed at creation. The
  procedure is: create a second node group, cordon and drain the first, delete it. Knowing that
  before you size a node group is worth more than any command in this lab.

**Compare with Practical 2.** ECS on Fargate has dimension 1 (`desiredCount`) and dimension 2 (the
task definition's `cpu` and `memory`), and **does not have dimensions 3 and 4 at all** - there are no
nodes. That is the entire difference in operational burden between the two platforms, in one
sentence, and it is the honest answer to "why would anyone choose Fargate?".

✏️ **Your turn**

In `notes/lab-08-notes.md`, answer in three or four sentences: *`usms-enrolment` needs to handle ten
times its current traffic. Walk through the four dimensions and say which you would use, in which
order, and what you would check between each.*

```text
Expected result:
A short ordered plan. There is no single right answer, but a plan that reaches
for dimension 4 first, or that never mentions dimension 3 at all, is wrong.
Section 15 Question 2 asks a harder version of this.
```

---

### Step 4 - Scale by hand, and watch what moves

**Purpose**

The simplest rung of the ladder, and the one that makes every later rung legible. Everything the HPA
does in Step 8, it does by performing this operation.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, open a watcher in a second terminal**

```bash
kubectl get pods -w -l app=usms-enrolment
```

Leave that running. In your first terminal:

**Command - part 2, scale up**

```bash
kubectl scale deployment/usms-enrolment --replicas=5
kubectl rollout status deployment/usms-enrolment --timeout=120s

kubectl get deploy usms-enrolment
kubectl get endpoints usms-enrolment
```

**What the command does**

```text
kubectl
 └── scale                      the SUBCOMMAND
      └── deployment/usms-enrolment   the OBJECT, in type/name form
           └── --replicas=5           the new value of spec.replicas
```

`kubectl scale` writes exactly one field. It does not create a new ReplicaSet, because the pod
template did not change - the *existing* ReplicaSet is scaled up. That is the difference between
scaling and a rolling update, and it is why scaling is fast and a rollout is not.

Watch the second terminal while this runs. Three new pods appear in `Pending`, move to
`ContainerCreating`, then `Running`, then `1/1` ready. The endpoint list grows only as each pod
becomes **ready** - the readiness probe from Lab 07 Step 13 is what gates that, and a pod that is
`Running` but not ready receives no traffic.

**Expected result**

```text
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
usms-enrolment   5/5     5            5           3h

NAME             ENDPOINTS                                                       AGE
usms-enrolment   10.42.1.8:80,10.42.1.11:80,10.42.2.5:80 + 2 more...             3h
```

> Example output - addresses differ, and `kubectl` abbreviates long endpoint lists.

**Command - part 3, confirm the traffic really spreads across five**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  for i in $(seq 1 40); do
    wget -qO- http://usms-gateway.usms.svc.cluster.local/enrolment/
  done
' | grep -o '"pod":"[^"]*"' | sort | uniq -c | sort -rn
```

**What to look for:** ideally five distinct pod names. Four or five is a pass. **The gateway was not
restarted, reconfigured or even informed** - it still holds one ClusterIP, exactly as it did in Lab
07 Step 16, and the spreading happens beneath it. That is the payoff for the architecture, and it is
worth pausing on before you move to the next command.

**Command - part 4, scale back down**

```bash
kubectl scale deployment/usms-enrolment --replicas=2
kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get endpoints usms-enrolment
```

Watch the second terminal: pods go to `Terminating` and disappear. They are removed from the endpoint
list **first**, then sent `SIGTERM`, then given `terminationGracePeriodSeconds` (30 by default) before
`SIGKILL`. That ordering is what makes scale-in safe for requests already in flight, and it is the
Kubernetes equivalent of the ALB's deregistration delay that Lab 05 set to 30 seconds.

Stop the watcher in your second terminal with ++ctrl+c++.

---

### Step 5 - Scale declaratively, and meet configuration drift

**Purpose**

Step 4 changed the cluster. Your repository does not know. This step shows what that costs and how to
avoid it - and it is the reason the rest of this lab uses manifests rather than `kubectl patch`.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, create the drift deliberately**

```bash
kubectl scale deployment/usms-enrolment --replicas=6
kubectl get deploy usms-enrolment -o jsonpath='{.spec.replicas}'; echo
grep -n 'replicas:' manifests/lab-07/20-enrolment.yaml
```

**Expected result**

```text
6
28:  replicas: 2
```

> Example output - the line number will differ.

The cluster says 6. The repository says 2. Neither is wrong; they simply disagree, and nothing
anywhere will tell you.

**Command - part 2, watch `apply` silently undo your scaling**

```bash
kubectl apply -f manifests/lab-07/20-enrolment.yaml
sleep 5
kubectl get deploy usms-enrolment -o jsonpath='{.spec.replicas}'; echo
```

**Expected result**

```text
2
```

Six pods became two, because `apply` did what you asked: make the cluster match the file. In a
laboratory that is a shrug. In production, at 09:00 on results-release day, someone applying an
unrelated change to that file takes your capacity away and the change looks innocent in review.

!!! warning "This is the single most common way a Kubernetes deployment causes an outage"
    It is not a bug and there is no flag that fixes it. There are three real answers:

    - **Never scale by hand.** Change `replicas:` in the file, commit it, apply it. Slower, auditable,
      and boring - which is the goal.
    - **Let the HPA own the field.** Step 8 does this, and Step 8 also removes `replicas:` from the
      manifest's meaning, which is subtle enough to have its own paragraph there.
    - **Use `kubectl diff` before every `apply`.** It shows exactly what would change, and it takes
      two seconds.

**Command - part 3, the habit that prevents it**

```bash
sed -i.bak 's/^  replicas: 2$/  replicas: 3/' manifests/lab-07/20-enrolment.yaml

kubectl diff -f manifests/lab-07/20-enrolment.yaml || true

kubectl apply -f manifests/lab-07/20-enrolment.yaml
kubectl get deploy usms-enrolment -o jsonpath='{.spec.replicas}'; echo
```

**What the command does**

`kubectl diff` renders what the cluster would look like after the apply and diffs it against what is
there now. It exits **1** when there is a difference, which is correct behaviour and not an error -
hence the `|| true`, which stops it killing a shell that has `set -e` active. In a pipeline, that
exit code is exactly what you want: it tells you whether a change is a no-op.

**Command - part 4, restore the baseline**

```bash
sed -i.bak 's/^  replicas: 3$/  replicas: 2/' manifests/lab-07/20-enrolment.yaml
kubectl apply -f manifests/lab-07/20-enrolment.yaml
kubectl rollout status deployment/usms-enrolment --timeout=120s
rm -f manifests/lab-07/*.bak
kubectl get deploy
```

**What to look for:** `usms-enrolment` back at `2/2`, and no `.bak` files left behind.

**Checkpoint 2**

```text
Scaling, by hand and by file
 ├── kubectl scale writes ONE field; no new ReplicaSet
 ├── endpoints grow only when pods become READY, not when they start
 ├── scale-in removes from endpoints BEFORE SIGTERM  (cf. Lab 05 deregistration delay 30s)
 ├── drift demonstrated: cluster 6, file 2, apply wins
 └── kubectl diff exits 1 on a difference - a feature, not a failure
 usms-enrolment back at 2/2
```

---

### Step 6 - Requests, limits and QoS classes: the coupling nobody explains

**Purpose**

Step 8's autoscaler divides by the number you set here. Step 12's disruption behaviour depends on the
class this step assigns. Ten minutes now removes most of the confusion in the rest of the lab.

**Concept first - requests and limits are different promises**

```text
requests   what the SCHEDULER reserves. A node with 1000m allocatable can hold
           20 pods requesting 50m each, whatever they actually use
limits     what the KUBELET enforces at runtime
             CPU over limit    -> THROTTLED. The pod slows down
             MEMORY over limit -> OOMKilled. The container is killed and restarted
```

That asymmetry is the thing to remember. CPU is compressible, so exceeding a CPU limit costs you
latency. Memory is not, so exceeding a memory limit costs you the process. It is why a memory limit
should be set generously or not at all, and a CPU limit should be set thoughtfully.

**Concept - the three QoS classes, which Kubernetes assigns and you do not**

| Class | When | What it means under pressure |
| --- | --- | --- |
| `Guaranteed` | every container has requests **equal to** limits, for both CPU and memory | Evicted last |
| `Burstable` | requests are set, and are less than limits | Evicted after `BestEffort` |
| `BestEffort` | nothing set at all | **Evicted first**, and invisible to the HPA |

Lab 07's containers request `50m`/`32Mi` and limit `200m`/`128Mi`, so all three microservices are
`Burstable`. That is the right choice for this workload - it can use spare capacity when it exists -
and it is also why an HPA can work at all: `BestEffort` pods have no request to compute a percentage
of.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, read the classes off the cluster**

```bash
kubectl get pods -o custom-columns=\
'NAME:.metadata.name,QOS:.status.qosClass,CPUREQ:.spec.containers[0].resources.requests.cpu,CPULIM:.spec.containers[0].resources.limits.cpu'
```

**Expected result**

```text
NAME                              QOS         CPUREQ   CPULIM
usms-enrolment-7d9f4c8b62-w8ntq   Burstable   50m      200m
usms-enrolment-7d9f4c8b62-x2knd   Burstable   50m      200m
usms-gateway-5c6d7f8a91-tt4mv     Burstable   50m      200m
usms-results-84cd7f6b59-h4xkz     Burstable   50m      200m
usms-results-84cd7f6b59-r9wln     Burstable   50m      200m
```

**Command - part 2, see the scheduler's arithmetic**

```bash
NODE=$(kubectl get pods -l app=usms-enrolment -o jsonpath='{.items[0].spec.nodeName}')
echo "inspecting node: $NODE"
kubectl describe node "$NODE" | sed -n '/Allocated resources/,/Events/p'
```

**What to look for:** a table of `Requests` and `Limits` with percentages. The percentages are of
**allocatable**, not of capacity - a node reserves some CPU and memory for the kubelet and the system,
and that reservation is why a 2-core node cannot run 2 cores' worth of pods. On a real EKS node the
gap is several hundred millicores and a gigabyte or more; budgeting for it is the difference between
a node group that fits and one that does not.

**Command - part 3, prove the denominator arithmetic before you rely on it**

```bash
REQ=$(kubectl get deploy usms-enrolment \
  -o jsonpath='{.spec.template.spec.containers[0].resources.requests.cpu}')
echo "request        : $REQ"
echo "HPA target 50% : this means 50% of $REQ per pod, i.e. 25m average across all pods"
echo "NOT 50% of a node, and NOT 50% of the limit"
```

That is worth typing out because getting it wrong produces an HPA that looks broken. If the target
were a percentage of the *node*, a `50m` pod on an 8-core node could never reach it. It is a
percentage of the request, so a pod using `30m` is at 60% and the HPA scales out.

✏️ **Your turn**

Make `usms-gateway` a `Guaranteed` pod without changing what it can do, then put it back. Record the
QoS class before and after, and one sentence on when you would actually want `Guaranteed`.

```text
Expected result:
QOS goes Burstable -> Guaranteed -> Burstable, and the pod is replaced each time.

Note that it was REPLACED, not adjusted. Say why in your notes - it is dimension 2
from Step 3, and it is the reason VerticalPodAutoscaler is used far less than HPA.
```

Hint: `kubectl set resources` takes both `--requests` and `--limits`, and the table above says
exactly what relationship between them produces each class.

---
### Step 7 - The metrics pipeline, and why it is an add-on

**Purpose**

The HPA in Step 8 reads a metric. That metric comes from an API that is **not part of core
Kubernetes** and may not be installed. This step establishes which situation you are in before you
build something that depends on it.

**Concept first - the chain, and where it can break**

```text
kubelet on each node
  |  exposes a /metrics/resource endpoint with per-container CPU and memory
  v
metrics-server                    a Deployment, usually in namespace kube-system
  |  scrapes every kubelet, keeps a short in-memory window (about 15 minutes)
  |  registers itself as an APIService for metrics.k8s.io/v1beta1
  v
the Kubernetes API server         now serves /apis/metrics.k8s.io/v1beta1/...
  |
  +--> kubectl top pods           what YOU read
  +--> HorizontalPodAutoscaler    what the CONTROLLER reads
```

Two things follow. First, `kubectl top` and the HPA read **the same source**, so if `kubectl top`
works the HPA has data, and if it does not the HPA will report `<unknown>`. That makes `kubectl top`
the single diagnostic for "is my HPA going to work?". Second, this pipeline gives you CPU and memory
and **nothing else**. Scaling on requests per second, queue depth or any application metric needs a
second pipeline - Prometheus with an adapter, or on EKS the CloudWatch adapter. Lab 06 scaled on
`ALBRequestCountPerTarget` and on a custom `EnrolmentQueueDepth` metric; doing the equivalent here is
a considerably larger undertaking, and Section 12 says so plainly.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, is the API registered?**

```bash
kubectl get apiservices | grep metrics || echo "no metrics APIService registered"
kubectl get deploy -n kube-system | grep -i metrics || echo "no metrics-server deployment"
kubectl get --raw /apis/metrics.k8s.io/v1beta1 >/dev/null 2>&1 \
  && echo "metrics API: AVAILABLE" \
  || echo "metrics API: NOT AVAILABLE"
```

**Expected result** (on a k3s-based cluster, which ships metrics-server by default)

```text
v1beta1.metrics.k8s.io   kube-system/metrics-server   True   3h
metrics-server           1/1     1            1       3h
metrics API: AVAILABLE
```

> Example output. `metrics API: NOT AVAILABLE` is a perfectly common outcome and part 2 deals with it.

**Command - part 2, only if part 1 said NOT AVAILABLE**

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s
```

If the pod starts but never becomes ready, and `kubectl -n kube-system logs deploy/metrics-server`
mentions certificates or `x509`, the cause is that metrics-server validates each kubelet's serving
certificate and local clusters issue self-signed ones. The local-only fix:

```bash
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s
```

!!! warning "`--kubelet-insecure-tls` is a laboratory-only flag"
    It tells metrics-server to skip verification of the kubelet's certificate. On a real cluster
    that is a genuine weakness - anything that can impersonate a kubelet can feed you invented
    metrics, and an autoscaler that believes invented metrics is a denial-of-service tool.

    On real EKS you never need it: the kubelets have certificates signed by the cluster CA. If you
    ever find yourself reaching for this flag on a managed cluster, something else is wrong.

    Record in your notes that you used it and why.

**Command - part 3, if you have no network access from the cluster**

`kubectl apply -f https://...` needs the nodes to reach GitHub. If they cannot, you cannot install
metrics-server, and Step 8's HPA will exist but never compute. That is a legitimate outcome. Record
it, and use the **fallback path** flagged in Step 9: drive the replica count by hand and read the
HPA's own explanation of why it is not acting.

```bash
echo "metrics API unavailable - Step 9 will use the manual fallback" >> notes/lab-08-notes.md
```

**Verify**

```bash
kubectl top nodes 2>/dev/null || echo "kubectl top nodes: unavailable"
kubectl top pods 2>/dev/null  || echo "kubectl top pods: unavailable"
```

**Expected result**

```text
NAME                    CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
usms-eks-cluster-ag0    142m         1%     1284Mi          16%

NAME                              CPU(cores)   MEMORY(bytes)
usms-enrolment-7d9f4c8b62-w8ntq   1m           4Mi
usms-enrolment-7d9f4c8b62-x2knd   1m           4Mi
usms-gateway-5c6d7f8a91-tt4mv     1m           3Mi
```

> Example output - your numbers will differ, and immediately after installing metrics-server you may
> get `metrics not available yet` for 30 to 60 seconds. Wait and re-run before concluding anything.

**What to look for:** a `CPU(cores)` value for each pod, of the order of `1m` at idle. That is 2% of
the `50m` request - comfortably below the 50% target Step 8 sets, which is what you want a baseline
to look like. Write the idle figure down; Step 9 compares against it.

---

### Step 8 - Create the HorizontalPodAutoscaler

**Purpose**

This is the object the whole scaling half of the lab is for. It is also the object with the closest
correspondence to something you built in Lab 06, and the comparison is worth more than the object.

**Concept first - what an HPA actually computes**

Every 15 seconds, by default, the HPA controller:

```text
1. reads the current metric for every ready pod of the target Deployment
2. computes    currentUtilisation = mean(usage) / request      as a percentage
3. computes    desiredReplicas = ceil( currentReplicas * currentUtilisation / targetUtilisation )
4. clamps it between minReplicas and maxReplicas
5. applies the behavior policies (rate limits and stabilisation windows)
6. writes the result to the Deployment's spec.replicas -- and does nothing else
```

Step 3 of that list is the whole algorithm and it is worth working an example. Two pods, each using
`40m`, request `50m`, target 50%:

```text
currentUtilisation = 40 / 50            = 80%
desiredReplicas    = ceil(2 * 80 / 50)  = ceil(3.2) = 4
```

Four replicas. Each should then average `20m`, which is 40% - under target, so no further scale-out.
The arithmetic is deliberately conservative in the other direction too: scaling *in* is gated by a
stabilisation window, because the cost of scaling in too eagerly is an outage and the cost of scaling
in too slowly is a small bill.

**The correspondence with Lab 06, field by field**

| Lab 06, Application Auto Scaling | Here | Note |
| --- | --- | --- |
| `RegisterScalableTarget` on `service/cluster/service` | `spec.scaleTargetRef` | There the resource ID was a constructed string; here it is a typed reference |
| `MinCapacity` / `MaxCapacity` | `minReplicas` / `maxReplicas` | Same idea, same purpose |
| `TargetTrackingScaling` on `ECSServiceAverageCPUUtilization` | `metrics[].resource.name: cpu` with `averageUtilization` | Same idea. **Different denominator** - see below |
| `ScaleInCooldown: 300` | `behavior.scaleDown.stabilizationWindowSeconds: 300` | Same idea, better named |
| `ScaleOutCooldown` | `behavior.scaleUp.stabilizationWindowSeconds` + policies | Kubernetes lets you rate-limit as well as delay |
| Two CloudWatch alarms created for you | No alarms. The controller polls | **The biggest structural difference** |
| Lives in an AWS service | Lives in your cluster's controller manager | Blast radius, and Step 17 |

That third row hides a real trap. `ECSServiceAverageCPUUtilization` is CPU used as a percentage of
**the task's reserved CPU**. The HPA's `averageUtilization` is CPU used as a percentage of **the
container's request**. Those are analogous but not identical, and a target of 50 does not necessarily
mean the same load on both platforms.

**Run from**

```text
aws-floci-course/
```

**Command - write the manifest**

```bash
cat > manifests/lab-08/10-hpa-enrolment.yaml << 'EOF'
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: usms-enrolment-hpa
  namespace: usms
  labels:
    app: usms-enrolment
    project: usms
    lab: "05b"
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: usms-enrolment
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 2
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      selectPolicy: Min
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
EOF

kubectl apply -f manifests/lab-08/10-hpa-enrolment.yaml
```

**What the command does**

`apiVersion: autoscaling/v2` - not `v1`. Version 1 supports exactly one metric, CPU, and no
`behavior` block at all. Every HPA you write from now on should be `v2`; `v1` exists for
compatibility and you will still see it in old blog posts.

Read `behavior` carefully, because it is the part that distinguishes a considered autoscaler from a
default one:

```text
scaleUp.stabilizationWindowSeconds: 0
    React immediately. There is no reason to hesitate before adding capacity.

scaleUp.policies + selectPolicy: Max
    Two rate limits, and the MORE permissive of them wins:
      "double the pod count every 15s"   (Percent 100)
      "add 2 pods every 15s"             (Pods 2)
    At 2 replicas, Percent allows +2 and Pods allows +2 -> +2.
    At 6 replicas, Percent allows +6 and Pods allows +2 -> +6.
    So it accelerates as the incident grows, which is what you want.

scaleDown.stabilizationWindowSeconds: 300
    Before scaling in, look at the highest recommendation from the last 5 minutes
    and use that. One quiet minute in a busy hour does NOT remove capacity.

scaleDown.policies + selectPolicy: Min
    Remove at most 1 pod per minute, and take the LEAST aggressive policy.
    Scale in slowly. The cost of being wrong is asymmetric.
```

That asymmetry - instant out, slow in - is the single most transferable idea about autoscaling, and
it is exactly the policy Lab 06 expressed with `ScaleInCooldown: 300` and a shorter scale-out
cooldown. Same doctrine, different syntax.

`minReplicas: 2` matters for a second reason: **the HPA now owns `spec.replicas`.** If it finds the
Deployment below 2, it raises it immediately. And from this moment, `kubectl scale` on
`usms-enrolment` is a temporary suggestion that the controller will overwrite within 15 seconds.
Step 5's drift problem has changed shape rather than gone away - the `replicas:` line in
`manifests/lab-07/20-enrolment.yaml` is now only an *initial* value, and re-applying that file no
longer determines the replica count for more than a few seconds.

**Expected result**

```text
horizontalpodautoscaler.autoscaling/usms-enrolment-hpa created
```

**Verify**

```bash
kubectl get hpa
sleep 30
kubectl get hpa
kubectl describe hpa usms-enrolment-hpa | tail -20
```

**Expected result**

```text
NAME                 REFERENCE                   TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
usms-enrolment-hpa   Deployment/usms-enrolment   cpu: 2%/50%   2         8         2          32s
```

> Example output - the current percentage will differ.

**What to look for**, and this is the decisive moment of the whole lab:

- **`TARGETS` showing a percentage, such as `2%/50%`.** The metrics pipeline works, the HPA has data,
  and Step 9 will show it moving.
- **`TARGETS` showing `<unknown>/50%`.** The HPA cannot compute. Two causes, and `describe` names
  which:
    - `failed to get cpu utilization: unable to get metrics` - Step 7's pipeline is not working.
    - `missing request for cpu` - the CPU request is absent. Step 1 checked this; go back to it.
- **`REPLICAS` reading 2.** If the Deployment was left at some other number, the HPA has already
  corrected it, which is itself a demonstration.

The `Conditions` block at the bottom of `describe` is where the HPA tells you what it thinks:
`AbleToScale`, `ScalingActive` and `ScalingLimited`, each with a reason. `ScalingActive: False` with
reason `FailedGetResourceMetric` is the `<unknown>` case stated precisely, and it is much more useful
than the dash in the table.

---

### Step 9 - Generate load and watch it respond

**Purpose**

An autoscaler you have not seen move is a configuration file, not a control loop. This step makes it
move, and gives you an honest fallback if your build cannot.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, a watcher script**

```bash
cat > scripts/utilities/hpa-watch.sh << 'EOF'
#!/usr/bin/env bash
# Print the HPA and its target Deployment once every 10 seconds. Read-only.
# Usage: ./scripts/utilities/hpa-watch.sh [iterations]
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
NS=usms
N="${1:-60}"

printf "%-9s %-14s %-10s %-8s %-8s\n" "TIME" "CPU/TARGET" "REPLICAS" "READY" "PODS"
for i in $(seq 1 "$N"); do
  T=$(date -u +%H:%M:%S)
  H=$(kubectl get hpa usms-enrolment-hpa -n "$NS" \
        -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null)
  TGT=$(kubectl get hpa usms-enrolment-hpa -n "$NS" \
        -o jsonpath='{.spec.metrics[0].resource.target.averageUtilization}' 2>/dev/null)
  D=$(kubectl get deploy usms-enrolment -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null)
  R=$(kubectl get deploy usms-enrolment -n "$NS" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  P=$(kubectl get pods -n "$NS" -l app=usms-enrolment --no-headers 2>/dev/null | wc -l | tr -d ' ')
  printf "%-9s %-14s %-10s %-8s %-8s\n" "$T" "${H:-unknown}%/${TGT:-?}%" "${D:-?}" "${R:-0}" "$P"
  sleep 10
done
EOF

chmod +x scripts/utilities/hpa-watch.sh
bash -n scripts/utilities/hpa-watch.sh && echo "hpa-watch.sh: valid bash syntax"
```

Run it in a **second terminal** and leave it there:

```bash
./scripts/utilities/hpa-watch.sh 60
```

**Command - part 2, the load generator**

```bash
cat > manifests/lab-08/20-loadgen.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-loadgen
  namespace: usms
  labels:
    app: usms-loadgen
    project: usms
    tier: tooling
    lab: "05b"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: usms-loadgen
  template:
    metadata:
      labels:
        app: usms-loadgen
        project: usms
        tier: tooling
    spec:
      containers:
        - name: loadgen
          image: busybox:1.36
          command:
            - /bin/sh
            - -c
            - >
              while true; do
                wget -q -O /dev/null http://usms-gateway.usms.svc.cluster.local/enrolment/ || true;
              done
          resources:
            requests:
              cpu: "50m"
              memory: "16Mi"
            limits:
              cpu: "300m"
              memory: "64Mi"
EOF

kubectl apply -f manifests/lab-08/20-loadgen.yaml
kubectl rollout status deployment/usms-loadgen --timeout=120s
```

**What the command does**

Three pods, each looping `wget` against the gateway's `/enrolment/` path as fast as the network
allows. The requests go gateway to Service to enrolment pods, so **both** the gateway and the
enrolment pods do work - which is realistic, and which is also why the gateway becomes the bottleneck
if you push this much harder.

`|| true` inside the loop stops a single failed request from ending the shell. Without it, one
transient failure during a rolling update kills the load generator and the graph goes flat for
reasons that have nothing to do with the autoscaler.

The `>` block scalar in YAML folds the following lines into one line with spaces. The trailing
semicolons are what keep it a valid shell command after folding, and they are easy to lose when
editing. If the pod crash-loops immediately, check them first.

**What to watch in the second terminal.** Within 30 to 60 seconds the CPU column should climb past
50%, and then `REPLICAS` should start moving. A typical run:

```text
TIME      CPU/TARGET     REPLICAS   READY    PODS
03:52:10  2%/50%         2          2        2
03:52:20  2%/50%         2          2        2
03:52:30  71%/50%        2          2        2
03:52:40  71%/50%        4          2        4
03:52:50  63%/50%        4          4        4
03:53:00  48%/50%        4          4        4
03:53:10  41%/50%        4          4        4
```

> Example output - your percentages and timings will differ, and the exact replica counts depend on
> how much CPU your machine can give the load generators.

Read what happened: utilisation went to 71%, the HPA computed `ceil(2 * 71 / 50) = 3` - but the
`scaleUp` policy allowed doubling, and `selectPolicy: Max` took the more permissive of the two
policies, so it went to 4. Utilisation then fell below target and it stopped. That is the algorithm
from Step 8 doing exactly what the arithmetic said it would.

**Command - part 3, remove the load and watch the stabilisation window**

```bash
kubectl scale deployment/usms-loadgen --replicas=0
```

Keep watching. CPU falls within a few seconds. **The replica count does not.** For five full minutes
the HPA holds its recommendation, because `scaleDown.stabilizationWindowSeconds` is 300. Then it
removes one pod per minute until it reaches `minReplicas: 2`.

Sitting through those five minutes once is worth more than reading about them. It is also exactly
what a student expects to be a bug, and it is the behaviour you would most want in production.

```bash
kubectl describe hpa usms-enrolment-hpa | grep -A8 'Events:'
```

**Expected result**

```text
Events:
  Type    Reason             Age    From                       Message
  ----    ------             ----   ----                       -------
  Normal  SuccessfulRescale  4m     horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target
  Normal  SuccessfulRescale  30s    horizontal-pod-autoscaler  New size: 3; reason: All metrics below target
```

> Example output. The `reason` strings are the HPA telling you its arithmetic in words - quote them
> in your lab report rather than paraphrasing.

!!! note "Floci Limitation - the metrics pipeline may be absent, and then this step cannot run"
    On a build with no metrics-server and no way to install one, the HPA exists, reports
    `<unknown>/50%`, and never acts.

    On real EKS you install metrics-server once per cluster (or use the EKS add-on) and it works.

    **The fallback, and it is a legitimate result.** Do this instead, and say in your report that you
    did:

    ```bash
    kubectl describe hpa usms-enrolment-hpa | sed -n '/Conditions/,/Events/p'
    kubectl scale deployment/usms-enrolment --replicas=4
    ./scripts/utilities/hpa-watch.sh 6
    kubectl scale deployment/usms-enrolment --replicas=2
    ```

    Then, in `notes/lab-08-notes.md`: quote the `ScalingActive: False` condition and its reason
    verbatim; work the Step 8 arithmetic by hand for two pods at 71% and state what the HPA *would*
    have done; and say what you would check first on a real cluster showing this. An honest
    `<unknown>` with the reasoning written out earns more than an invented percentage.

!!! warning "If replicas climb and new pods sit in `Pending`"
    The HPA did its job and there is nowhere to put the pods. This is dimensions 1 and 3 from Step 3
    failing to meet.

    ```bash
    kubectl get pods -l app=usms-enrolment
    kubectl describe pod <a pending one> | tail -6
    kubectl describe node <any node> | sed -n '/Allocated resources/,/Events/p'
    ```

    `Insufficient cpu` in the events is the confirmation. Step 10 is the AWS-side answer, and Step 11
    explains what would do it automatically. In the meantime, lower `maxReplicas` or raise the node
    group - do not lower the CPU request, because that changes the HPA's denominator and makes the
    numbers you have been reading incomparable.

**Checkpoint 3**

```text
Scaling, by controller
 ├── metrics API           available / installed / recorded as unavailable
 ├── usms-enrolment-hpa    autoscaling/v2, min 2 max 8, cpu 50% of the 50m request
 ├── behavior              scaleUp instant + rate-limited; scaleDown 300s window, 1 pod/min
 ├── observed              replicas moved 2 -> 4 under load, and back to 2 after the window
 │                         (or: <unknown> diagnosed, arithmetic worked by hand, reason quoted)
 └── usms-loadgen          scaled to 0, still present for Step 12
```

---
### Step 10 - Scale the data plane from the AWS side

**Purpose**

Everything so far has been dimension 1 - more pods. This is dimension 3 - more nodes - and it is the
only step in this lab that uses the AWS CLI. It is also the step that makes the two-control-loops
picture in Section 6 concrete.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, read the current configuration**

```bash
aws eks describe-nodegroup \
  --cluster-name "$USMS_EKS_CLUSTER" \
  --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --query 'nodegroup.{Name:nodegroupName,Status:status,Scaling:scalingConfig,
                      Types:instanceTypes,Subnets:subnets,Labels:labels}' \
  --output json | tee outputs/lab-08-nodegroup-before.json
```

**Expected result**

```text
{
    "Name": "usms-eks-nodes",
    "Status": "ACTIVE",
    "Scaling": { "minSize": 2, "maxSize": 4, "desiredSize": 2 },
    "Types": [ "t3.small" ],
    "Subnets": [ "subnet-0aa...", "subnet-0bb..." ],
    "Labels": { "workload": "usms", "tier": "app" }
}
```

> Example output - subnet IDs will differ.

**Command - part 2, change it**

```bash
aws eks update-nodegroup-config \
  --cluster-name "$USMS_EKS_CLUSTER" \
  --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --scaling-config minSize=2,maxSize=6,desiredSize=3 \
  --query 'update.{Id:id,Status:status,Type:type}' \
  --output table
```

**What the command does**

```text
aws
 └── eks                              the SERVICE
      └── update-nodegroup-config     the OPERATION - changes an EXISTING group
           ├── --cluster-name         which cluster
           ├── --nodegroup-name       which group
           └── --scaling-config       min, max and desired, as a shorthand structure
```

Note what this operation **cannot** change: `instanceTypes`, `amiType`, `subnets`, `nodeRole`,
`diskSize`. Those are fixed at creation. Dimension 4 from Step 3 - bigger nodes - is not an update, it
is a new node group plus a drain plus a delete. `update-nodegroup-config` handles scaling, labels,
taints and the update configuration, and nothing else.

The response is an **Update object with an ID and a status of `InProgress`**, not the node group. On
real AWS you would poll it:

```bash
UPDATE_ID=$(aws eks list-updates \
  --name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --query 'updateIds | [0]' --output text 2>/dev/null)

aws eks describe-update \
  --name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --update-id "$UPDATE_ID" \
  --query 'update.{Status:status,Type:type,Params:params}' --output json 2>/dev/null \
  || echo "describe-update unsupported on this build - read the node group directly instead"
```

That asynchronous-update-object pattern is worth recognising because EKS uses it for every mutation:
version upgrades, add-on changes, endpoint access changes. It is not specific to scaling.

**Command - part 3, verify from both sides**

```bash
aws eks describe-nodegroup \
  --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --query 'nodegroup.scalingConfig' --output json | tee outputs/lab-08-nodegroup-after.json

echo "--- and what Kubernetes actually sees ---"
kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,LABELS:.metadata.labels.workload'
```

**What to look for:** `minSize 2, maxSize 6, desiredSize 3` from the AWS side. From the Kubernetes
side, **the node count may not change at all**, and that is the honest and expected outcome here.

!!! note "Floci Limitation - the node group's `desiredSize` is recorded, not enacted"
    Floci stores the scaling configuration faithfully and returns it faithfully. It does not start a
    third node container, because the local cluster's nodes were created when the cluster was created
    and are not managed by an Auto Scaling group.

    On real AWS, raising `desiredSize` to 3 changes the underlying Auto Scaling group's desired
    capacity. Within a couple of minutes a third EC2 instance launches from the EKS-optimised AMI,
    runs the bootstrap script with the cluster name, registers with the API server using
    `usms-eks-node-role`, and appears in `kubectl get nodes` as `Ready`. Then - and only then - the
    `Pending` pods from Step 9 get scheduled.

    Take away the two-loop picture. **Raising `replicas` and raising `desiredSize` are different
    operations against different APIs, and nothing connects them unless you install something that
    does.** Step 11 is about that something.

**Command - part 4, put it back, or don't**

Leaving it at 3 is fine and is what `configs/lab-08.env` will record. If you would rather restore
Lab 07's numbers:

```bash
aws eks update-nodegroup-config \
  --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --scaling-config minSize=2,maxSize=4,desiredSize=2 \
  --query 'update.status' --output text
```

Whichever you choose, make `configs/lab-08.env` in Step 19 record what is actually true.

**Path B note.** Skip this step. Record in your notes that `usms-eks-nodes` does not exist as an AWS
object on your build, and answer Section 15 Question 4 - which is about the two-loop picture - from
the concept rather than from observation.

---

### Step 11 - Cluster Autoscaler and Karpenter, and a `nodeSelector` you can actually use

**Purpose**

Step 10 raised a number by hand. Something should raise it automatically. This step names the two
things that do, explains why this lab does not install either, and then does the one piece of
node-aware scheduling that *is* observable locally.

**Concept first - the two options, in one sentence each**

| | Cluster Autoscaler | Karpenter |
| --- | --- | --- |
| What it watches | Pods that are `Pending` because no node fits | The same |
| What it does | Increases an Auto Scaling group's desired capacity, then waits for EKS to add a node from that group | Launches EC2 instances **directly**, choosing the instance type to fit the pending pods |
| You must pre-declare | Node groups, one per instance shape you want | A `NodePool` describing acceptable instance families and constraints |
| Typical scale-out time | Minutes | Under a minute |
| Bin-packing quality | Whatever your node groups happen to be | Chooses a size that fits, so less waste |
| Maturity | The long-standing upstream Kubernetes project | AWS's newer project, now used well beyond EKS |

The reason to know both: Cluster Autoscaler thinks in **groups you defined**, Karpenter thinks in
**capacity that would fit**. If your workload is uniform, groups are fine. If it is varied - a few
large jobs among many small services - groups force you to guess in advance, and guessing badly is
how you end up paying for half-empty nodes.

!!! note "Conceptual / Real AWS - neither autoscaler is installed in this laboratory"
    Both are Kubernetes Deployments that call the AWS APIs, and both need credentials to do so - in
    practice through IRSA, which Lab 07 Step 21 established is not available on this build. Cluster
    Autoscaler additionally needs the node group's Auto Scaling group to carry specific discovery
    tags, and there is no Auto Scaling group here to tag.

    On real EKS, installing Cluster Autoscaler is: create an IAM policy with the `autoscaling:`
    describe and set-desired-capacity actions, create a role with an IRSA trust policy, install the
    Helm chart with the cluster name and that role's ARN, and tag the node group's ASG with
    `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/<cluster-name>`.

    Take away what it does, not the commands: it watches for `Pending` pods and writes `desiredSize`.
    It is the loop that connects Step 9 to Step 10, and without it those two steps are unrelated.

**Concept - node labels and `nodeSelector`, which *is* observable**

Lab 07's node group declared Kubernetes labels `workload=usms` and `tier=app`. Those labels are how
you steer pods at particular nodes - the cheapest form of scheduling control, and the one worth
learning first.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, do the labels exist?**

```bash
kubectl get nodes --show-labels | tr ',' '\n' | grep -E 'workload|tier' \
  || echo "node group labels did not reach the nodes"
```

**Command - part 2, if they did not, apply them by hand**

This is a fair thing to do: on real EKS the node group would have applied them, and the point of the
step is the `nodeSelector`, not the label's provenance.

```bash
for N in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  kubectl label node "$N" workload=usms tier=app --overwrite
done

kubectl get nodes -L workload,tier
```

`-L` adds a column per label - much more readable than `--show-labels` when you know which labels you
care about.

**Command - part 3, require the label**

```bash
kubectl patch deployment usms-enrolment --type=merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"workload":"usms"}}}}}'

kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get pods -l app=usms-enrolment -o wide
```

**What to look for:** the pods rescheduled onto nodes carrying `workload=usms`. Since every node
carries it, they may land anywhere - which is correct, and which is why part 4 is the actual test.

**Command - part 4, prove the selector is enforced**

```bash
kubectl patch deployment usms-enrolment --type=merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"workload":"nonexistent"}}}}}'

sleep 15
kubectl get pods -l app=usms-enrolment
kubectl describe pod -l app=usms-enrolment | grep -A3 'Events:' | tail -4
```

**Expected result**

```text
NAME                              READY   STATUS    RESTARTS   AGE
usms-enrolment-6d4b7c9f81-9dltw   0/1     Pending   0          15s
usms-enrolment-7d9f4c8b62-w8ntq   1/1     Running   0          22m
usms-enrolment-7d9f4c8b62-x2knd   1/1     Running   0          22m

Events:
  Warning  FailedScheduling  14s  default-scheduler  0/2 nodes are available:
           2 node(s) didn't match Pod's node affinity/selector.
```

> Example output.

Two things to notice, and both are the deployment strategy from Lab 07 Step 13 paying off. The new
pod is `Pending` and **the old pods are still serving** - `maxUnavailable: 0` means the roll cannot
proceed until the new pod is ready, and it never will be. The Deployment is stuck, and stuck is much
better than broken. On a Deployment with the default strategy, this same mistake would have taken 25%
of your capacity away.

**Command - part 5, put it back**

```bash
kubectl patch deployment usms-enrolment --type=merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"workload":"usms"}}}}}'

kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get pods -l app=usms-enrolment -o wide
```

Also record the change in the manifest, so the repository stops lying - Step 5's lesson, applied:

```bash
python3 - << 'PY'
import re
p = 'manifests/lab-07/20-enrolment.yaml'
s = open(p).read()
if 'nodeSelector' not in s:
    s = s.replace("    spec:\n      containers:\n        - name: enrolment",
                  "    spec:\n      nodeSelector:\n        workload: usms\n      containers:\n        - name: enrolment", 1)
    open(p,'w').write(s)
    print('nodeSelector added to', p)
else:
    print('nodeSelector already present in', p)
PY

kubectl diff -f manifests/lab-07/20-enrolment.yaml || true
```

**What to look for:** `kubectl diff` printing nothing, or only metadata noise. A diff showing a
`replicas` change is expected and harmless - the HPA owns that field now, as Step 8 explained.

---

### Step 12 - A PodDisruptionBudget, and what it does not protect against

**Purpose**

Scaling down and node maintenance both remove pods. A PDB is how you say "not all of them at once".
It is also routinely misunderstood, so this step includes the misunderstanding.

**Concept first - voluntary and involuntary disruption**

```text
VOLUNTARY - something with an API asked for it. A PDB IS CONSULTED
  kubectl drain (node maintenance, an upgrade, a scale-in)
  a cluster autoscaler removing an under-used node
  kubectl delete pod                    <- consulted only via the eviction API, see below

INVOLUNTARY - nobody asked. A PDB IS IGNORED
  the node's kernel panicked
  the node ran out of memory and the kubelet evicted something
  someone terminated the EC2 instance in the console
  a hardware failure
```

A PDB constrains **evictions**, which is a specific API. `kubectl drain` uses it, autoscalers use it,
and that is why a PDB protects you during maintenance. `kubectl delete pod` does **not** use it - a
delete is not an eviction - which is why you can always delete straight through a PDB and why
students conclude, wrongly, that PDBs do not work.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write it**

```bash
cat > manifests/lab-08/30-pdb-gateway.yaml << 'EOF'
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: usms-gateway-pdb
  namespace: usms
  labels:
    app: usms-gateway
    project: usms
    lab: "05b"
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: usms-gateway
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: usms-enrolment-pdb
  namespace: usms
  labels:
    app: usms-enrolment
    project: usms
    lab: "05b"
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: usms-enrolment
EOF

kubectl apply -f manifests/lab-08/30-pdb-gateway.yaml
kubectl get pdb
```

**What the command does**

Two PDBs, expressed two different ways, deliberately.

`minAvailable: 1` on the gateway says "at least one gateway pod must remain". The gateway runs a
single replica, so **this PDB blocks every voluntary eviction of it** - draining its node will hang
until you either scale the gateway up or force it. That is not a mistake in the manifest; it is the
correct expression of "this service must not go away", and it tells you something true: *a
single-replica Deployment cannot be both highly available and drainable.* Exercise 2 asks you to fix
it properly.

`maxUnavailable: 1` on enrolment says "at most one enrolment pod may be down at a time". With the HPA
running between 2 and 8 replicas, that is the more useful form, because it scales with the replica
count instead of being a fixed floor.

Choose `minAvailable` when you know the absolute floor you need. Choose `maxUnavailable` when the
replica count moves.

**Expected result**

```text
NAME                 MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
usms-enrolment-pdb   N/A             1                 1                     5s
usms-gateway-pdb     1               N/A               0                     5s
```

> Example output.

**`ALLOWED DISRUPTIONS` is the column that matters.** `0` for the gateway is the fact stated above:
right now, nothing may voluntarily evict it. `1` for enrolment means one of its pods may go.

**Command - part 2, prove it is consulted, and then prove what ignores it**

```bash
NODE=$(kubectl get pods -l app=usms-gateway -o jsonpath='{.items[0].spec.nodeName}')
echo "gateway is on node: $NODE"

echo "--- eviction API, which a PDB governs ---"
POD=$(kubectl get pods -l app=usms-gateway -o jsonpath='{.items[0].metadata.name}')

cat > outputs/lab-08-eviction.json << EOF
{
  "apiVersion": "policy/v1",
  "kind": "Eviction",
  "metadata": { "name": "$POD", "namespace": "usms" }
}
EOF

kubectl create --raw "/api/v1/namespaces/usms/pods/$POD/eviction" \
  -f outputs/lab-08-eviction.json 2>&1 | tail -3
```

**What the command does**

An eviction is not an ordinary object you can `kubectl create -f` - it is a **subresource** of a pod,
reached by POSTing to `/api/v1/namespaces/<ns>/pods/<pod>/eviction`. `kubectl create --raw <path> -f
<file>` is how you POST an arbitrary body to an arbitrary API path, and it is worth knowing for
exactly this kind of case.

**The heredoc is unquoted** here - `<< EOF` - because `$POD` must expand. The eviction body has to
name a real pod. Contrast with every manifest in this lab, which uses `<< 'EOF'`.

**Expected result**

```text
Error from server (TooManyRequests): Cannot evict pod as it would violate the pod's disruption budget.
```

That error is the PDB working. Now the contrast:

```bash
echo "--- plain delete, which a PDB does NOT govern ---"
kubectl delete pod "$POD"
kubectl get pods -l app=usms-gateway
```

The pod is deleted, a replacement starts, and the PDB said nothing. **Both of those outcomes are
correct.** A PDB is a constraint on a cooperative process, not a lock.

**Command - part 3, the practical consequence**

```bash
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --dry-run=client 2>&1 | tail -5
```

`--dry-run=client` shows what a drain would attempt without doing it. On a two-node local cluster an
actual drain would evacuate a large fraction of your workload, so the dry run is the responsible
demonstration here.

!!! danger "Read before running a real drain"
    **What will happen:** every evictable pod on that node is evicted and rescheduled elsewhere, and
    the node is marked unschedulable.
    **What depends on it:** on a two-node cluster, roughly half your pods. If the other node cannot
    fit them, they stay `Pending` and the service degrades.
    **Reversible?** Yes - `kubectl uncordon <node>` makes it schedulable again, but pods do not move
    back on their own.
    **Effect on later labs:** none, provided you uncordon afterwards. A node left cordoned is a
    genuinely confusing state to debug next week.

**Checkpoint 4**

```text
Infrastructure scaling and safety
 ├── usms-eks-nodes         min 2 / max 6 / desired 3 on the AWS side
 │                          (recorded, not enacted locally - noted honestly)
 ├── Cluster Autoscaler / Karpenter   named, compared, NOT installed, and why
 ├── nodeSelector workload=usms       applied, ENFORCEMENT PROVEN with a bad value
 │                          and maxUnavailable 0 shown protecting the running pods
 ├── usms-gateway-pdb       minAvailable 1  -> ALLOWED DISRUPTIONS 0
 ├── usms-enrolment-pdb     maxUnavailable 1 -> ALLOWED DISRUPTIONS 1
 └── proven: eviction API respects a PDB; kubectl delete does not
```

---
### Step 13 - Rung one: ClusterIP and `port-forward`

**Purpose**

The bottom of the exposure ladder. Everything Lab 07 built is here already; this step names what
that means and shows the one way to reach a ClusterIP Service from your laptop without changing
anything.

**Concept first - the four Service types, and one non-type**

| | Reachable from | Creates | Use it for |
| --- | --- | --- | --- |
| `ClusterIP` (default) | Inside the cluster only | A virtual IP and a DNS record | Everything internal. This should be most of your Services |
| `NodePort` | Any node's IP, on a port in 30000–32767 | The above, **plus** a port open on every node | Rarely used directly; it is the building block underneath the next row |
| `LoadBalancer` | An external address | The above two, **plus** a cloud load balancer | The standard way to expose one Service externally on a cloud |
| `ExternalName` | n/a | A DNS CNAME to something outside the cluster | Pointing at a managed database without changing application code |
| `kubectl port-forward` | **Only your terminal** | Nothing. It is a tunnel through the API server | Debugging. Never anything else |

The important structural fact, and the reason "ladder" is the right word: **each type is a superset of
the one above.** A `LoadBalancer` Service still has a `nodePort` and still has a `clusterIP`, and you
can see all three on one object. Step 15 will show exactly that.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, confirm nothing is reachable from here**

```bash
kubectl get svc -o wide

CIP=$(kubectl get svc usms-gateway -o jsonpath='{.spec.clusterIP}')
echo "gateway ClusterIP: $CIP"

curl -s --max-time 5 "http://$CIP/" || echo "as expected: a ClusterIP is not routable from your machine"
```

**What to look for:** the `curl` failing. `10.43.x.x` is an address inside the cluster's virtual
network; your laptop has no route to it and no reason to. If it *does* succeed, you have unusual
routing configured and should note it.

**Command - part 2, tunnel to it**

```bash
kubectl port-forward svc/usms-gateway 18080:80
```

Leave that running. In a **second terminal**:

```bash
curl -s http://localhost:18080/ ; echo
curl -s http://localhost:18080/enrolment/ ; echo
curl -s http://localhost:18080/results/ ; echo
```

**Expected result**

```text
{"service":"usms-gateway","pod":"usms-gateway-5c6d7f8a91-tt4mv","routes":["/enrolment/","/results/"]}
{"service":"usms-enrolment","pod":"usms-enrolment-7d9f4c8b62-w8ntq","node":"usms-eks-cluster-ag0","env":"laboratory","version":"1.0.0"}
{"service":"usms-results","pod":"usms-results-84cd7f6b59-h4xkz","campus":"rtc","version":"1.0.0"}
```

> Example output - pod names differ. This is the first time in Practical 4 that a request from
> **outside** the cluster has reached the application, and it is worth noticing that it did so
> through the Kubernetes API server rather than through any networking you configured.

**What the command does**

```text
kubectl
 └── port-forward             the SUBCOMMAND
      └── svc/usms-gateway    the target. Resolves to ONE pod behind that Service
           └── 18080:80       localPort:remotePort
```

Two properties make this a debugging tool and nothing else:

- **It is a single tunnel to a single pod.** Naming a Service does not load-balance; `kubectl` picks
  one pod and every request goes there. Scaling the Deployment changes nothing about your tunnel.
- **It exists only while that command runs, only on your machine, and it goes through the API
  server** - so every byte is carried by your cluster's control plane, and it stops the moment you
  press ++ctrl+c++ or your laptop sleeps.

Anyone who proposes `kubectl port-forward` as part of a production access path should be gently
redirected to Step 15.

Stop the forward with ++ctrl+c++ in the first terminal.

---

### Step 14 - Rung two: NodePort

**Purpose**

The first rung that opens a real port on real machines. It is also the layer underneath everything
above it, so understanding it makes `LoadBalancer` and `Ingress` unmysterious.

**Concept first**

Setting `type: NodePort` makes the cluster allocate one port - by default from 30000 to 32767 - and
open it on **every node**, whether or not that node runs a pod of the Service. A request to any node
on that port is forwarded, by kube-proxy, to a ready pod anywhere in the cluster.

```text
        node ag0 :31567 ---+
                           |
        node ag1 :31567 ---+---> kube-proxy ---> any ready pod of the Service
                           |
        node srv0:31567 ---+
```

Three consequences worth knowing:

- **The port is the same on every node.** That is what makes an external load balancer's job trivial:
  register all the nodes on one port and stop thinking about pods.
- **A node with no pods still answers.** The extra hop costs a little latency, and it is why
  `externalTrafficPolicy: Local` exists - it restricts a node to its own pods, preserves the client's
  source IP, and in exchange makes some nodes answer nothing.
- **The port range is high and non-obvious**, which is why nobody exposes a public website this way
  directly. You pin it or you let it be allocated, but either way it is not port 80.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, a new Service rather than a patch**

```bash
cat > manifests/lab-08/40-service-nodeport.yaml << 'EOF'
apiVersion: v1
kind: Service
metadata:
  name: usms-results-np
  namespace: usms
  labels:
    app: usms-results
    project: usms
    lab: "05b"
spec:
  type: NodePort
  selector:
    app: usms-results
  ports:
    - name: http
      port: 80
      targetPort: http
      nodePort: 30080
EOF

kubectl apply -f manifests/lab-08/40-service-nodeport.yaml
kubectl get svc usms-results-np -o wide
```

**What the command does**

A **second** Service selecting the **same pods**. That is legal, common and useful: one workload can
have an internal ClusterIP Service and a separately-exposed NodePort Service, with different names,
different policies and different lifetimes. Nothing about `usms-results` itself changed.

`nodePort: 30080` pins the port instead of letting the cluster allocate one. Pinning is a trade: your
firewall rules and your documentation can be written in advance, but the port can collide with
another Service and the failure - `provided port is already allocated` - arrives at apply time.

**Expected result**

```text
NAME              TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE   SELECTOR
usms-results-np   NodePort   10.43.44.108    <none>        80:30080/TCP   3s    app=usms-results
```

> Example output.

**Read `PORT(S)` carefully: `80:30080/TCP`.** The Service still has a ClusterIP answering on 80 - the
rung below is still there - and *additionally* every node answers on 30080. Superset, not replacement.

**Command - part 2, reach it from inside the cluster, on a node address**

```bash
NODEIP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "node internal IP: $NODEIP"

kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- "http://$NODEIP:30080/"
```

**Command - part 3, prove that *every* node answers**

```bash
for IP in $(kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'); do
  echo "--- via node $IP ---"
  kubectl run usms-debug-$RANDOM --rm -i --restart=Never --image=busybox:1.36 -- \
    wget -qO- --timeout=5 "http://$IP:30080/" 2>/dev/null || echo "  no answer"
done
```

**What to look for:** a JSON response through **each** node address, and the `pod` field varying -
proof that a node forwards to pods it does not host.

**Command - part 4, from your machine**

```bash
curl -s --max-time 5 http://localhost:30080/ ; echo
```

!!! note "Floci Limitation - a NodePort is not automatically published to your host"
    The nodes are containers. A container's port is reachable from your machine only if it was
    published when the container was created, and 30080 was not.

    On real AWS the nodes are EC2 instances with addresses in your VPC, so a NodePort is reachable
    from anything that can route to them and whose traffic the security group admits - which is
    exactly how a load balancer reaches them.

    **The fallback**, which keeps the demonstration honest without pretending:

    ```bash
    kubectl port-forward svc/usms-results-np 30080:80
    # then, in another terminal:
    curl -s http://localhost:30080/ ; echo
    ```

    Note what that proves and what it does not: it proves the Service works, not that the NodePort is
    externally reachable. Say so in your report. If your `k3d` build supports it, the honest local
    equivalent is to add a port mapping to the cluster, which requires recreating it - not worth it
    for this rung.

**Checkpoint 5**

```text
Exposure ladder, rungs 1 and 2
 ├── ClusterIP        usms-gateway, usms-enrolment, usms-results   internal only, proven
 ├── port-forward     a tunnel through the API server. Debugging only, and you saw why
 └── NodePort         usms-results-np  80:30080/TCP
       ├── the SAME pods as usms-results, via a SECOND Service
       ├── every node answers on 30080, including nodes with no pods
       └── still has a ClusterIP: each rung KEEPS the one below it
```

---

### Step 15 - Rung three: LoadBalancer

**Purpose**

The rung that, on a real cloud, provisions infrastructure. This is where Lab 07's `_lb_ports_` tag
earns its keep, and where the comparison with Lab 05 begins.

**Concept first - what `type: LoadBalancer` actually does**

```text
1. Everything NodePort does: a clusterIP, and a nodePort open on every node.
2. The cloud-controller-manager notices the new Service.
3. On AWS it creates a Network Load Balancer, adds a listener, and registers
   the nodes (or, with the newer controller, the pod IPs) as targets.
4. When the load balancer has an address, the controller writes it back into
   the Service's status.loadBalancer.ingress[0].
```

Step 4 of that list is why `EXTERNAL-IP` shows `<pending>` and then fills in. The pending state is not
a failure; it means the controller has been asked and has not finished - or, if it stays pending
forever, that **no controller is listening**, which is precisely what happens on a cluster with no
cloud provider integration.

**The cost model is the thing students miss.** One `LoadBalancer` Service is one load balancer. Ten
Services of type `LoadBalancer` is ten load balancers, ten monthly charges and ten DNS names. That is
the entire economic argument for Ingress, which Step 16 is about.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, promote the gateway**

```bash
cat > manifests/lab-08/50-service-loadbalancer.yaml << 'EOF'
apiVersion: v1
kind: Service
metadata:
  name: usms-gateway
  namespace: usms
  labels:
    app: usms-gateway
    project: usms
    lab: "05b"
  annotations:
    # Real AWS only. Ignored locally, and harmless. Read them, they are the lesson.
    service.beta.kubernetes.io/aws-load-balancer-type: "external"
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: "ip"
    service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"
spec:
  type: LoadBalancer
  selector:
    app: usms-gateway
  ports:
    - name: http
      port: 80
      targetPort: http
EOF

kubectl apply -f manifests/lab-08/50-service-loadbalancer.yaml
kubectl get svc usms-gateway -o wide
```

**What the command does**

This is a **complete Service manifest** that replaces the one Lab 07 applied, not a patch. The name
is the same, so `apply` updates the existing object rather than creating a second one, and the file
in your repository now describes what the cluster contains. Step 5's lesson, applied for the second
time.

**Read the three annotations, because they are the whole of "EKS-specific" in this lab:**

```text
aws-load-balancer-type: external
    Use the AWS Load Balancer Controller, not the legacy in-tree provider.
    On a modern EKS cluster this is what you want; without the controller
    installed, this annotation means the Service is never fulfilled at all.

aws-load-balancer-nlb-target-type: ip
    Register POD addresses as targets, not node addresses.
    THIS IS LAB 05's TARGET GROUP TARGET TYPE, IDENTICAL, for the same reason:
    a pod, like a Fargate task, has its own VPC address, so the load balancer can
    reach it directly and skip the NodePort hop entirely.

aws-load-balancer-scheme: internet-facing
    Place the load balancer's nodes in the PUBLIC subnets. Lab 02 built two, and
    Lab 05 required both. An internal scheme would use the private pair instead.
```

Annotations are how Kubernetes carries cloud-specific configuration without polluting the portable
`spec`. The manifest still applies on any cluster; on a non-AWS one, the annotations are inert
strings. That is the portability claim from Lab 07 Section 1, with its honest caveat attached.

**Command - part 2, watch for an address**

```bash
kubectl get svc usms-gateway -w
```

Give it 60 seconds, then stop with ++ctrl+c++.

**Expected result - one of two, and both are informative**

```text
NAME           TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
usms-gateway   LoadBalancer   10.43.201.77    <pending>     80:31946/TCP   15s
usms-gateway   LoadBalancer   10.43.201.77    172.18.0.4    80:31946/TCP   45s
```

or

```text
NAME           TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
usms-gateway   LoadBalancer   10.43.201.77    <pending>     80:31946/TCP   3m
```

> Example output. Either is a valid result on this platform.

**Notice `PORT(S)`: `80:31946/TCP`.** A nodePort was allocated automatically, even though you did not
ask for one. That is the superset property made visible for the second time: `LoadBalancer` contains
`NodePort` contains `ClusterIP`.

**Command - part 3, reach it**

```bash
echo "--- via the published host port from Lab 07's _lb_ports_ tag ---"
curl -s --max-time 5 http://localhost:8081/ ; echo

echo "--- via the second published port ---"
curl -s --max-time 5 http://localhost:8082/ ; echo

echo "--- via the assigned EXTERNAL-IP, if there is one ---"
EXT=$(kubectl get svc usms-gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "EXTERNAL-IP = ${EXT:-none}"
[ -n "$EXT" ] && kubectl run usms-debug --rm -i --restart=Never --image=busybox:1.36 -- \
  wget -qO- --timeout=5 "http://$EXT/" 2>/dev/null
```

!!! note "Floci Limitation - a LoadBalancer Service may stay `<pending>` forever, and that is the honest result"
    Whether an external address appears depends on whether your build starts a service load balancer
    for the local cluster. Some do; some deliberately do not, to keep host port usage small. The
    `_lb_ports_` tag from Lab 07 Step 8 is what publishes 8081 and 8082 on your host when it does.

    On real EKS with the AWS Load Balancer Controller installed, this Service produces a Network Load
    Balancer in your public subnets within two or three minutes, with pod IPs as targets, and
    `EXTERNAL-IP` becomes a DNS name of the form
    `k8s-usms-usmsgat-abc123.elb.us-east-1.amazonaws.com`.

    **Take away the shape.** One Service, one load balancer, one bill. And note the annotation that
    said `target-type: ip` - you configured exactly that by hand in Lab 05, on an ALB, for a Fargate
    service. The infrastructure is the same; only who asked for it has changed.

    If yours stays `<pending>`, use `kubectl port-forward svc/usms-gateway 8080:80` to demonstrate the
    Service works, record the `<pending>` state, and say in your report which of the four rungs of
    the ladder you observed and which you reasoned about.

**Verify**

```bash
kubectl get svc usms-gateway \
  -o jsonpath='{"type="}{.spec.type}{"  clusterIP="}{.spec.clusterIP}{"  nodePort="}{.spec.ports[0].nodePort}{"  external="}{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

**What to look for:** all four fields on one line, with `type=LoadBalancer`, a `clusterIP`, a
`nodePort` and an `external` that is either an address or empty. That single line is the ladder, and
it is worth putting in your lab report.

---

### Step 16 - Rung four: Ingress, and the comparison this practical was built for

**Purpose**

The top rung, the one that makes the economics work, and the point where Practical 2 and Practical 4
turn out to be describing the same infrastructure.

**Concept first - what an Ingress is, and what it is not**

An **Ingress** is a set of HTTP routing rules: host names, paths, and the Service each should reach.
It is **not** a proxy and it does nothing on its own. Something must watch for Ingress objects and
implement them - an **ingress controller** - and which controller you run determines what actually
happens:

| Controller | What it creates | Where it runs |
| --- | --- | --- |
| Traefik | Routing inside a pod in your cluster | In-cluster. Default on k3s |
| ingress-nginx | The same, with nginx | In-cluster |
| **AWS Load Balancer Controller** | **An Application Load Balancer, in your VPC** | In-cluster, calling the AWS API |

That third row is the one to internalise. On EKS with the AWS Load Balancer Controller, an Ingress
object produces **an ALB with a target group of type `ip` and listener rules per path**. Read that
again next to Lab 05, where you created an ALB, a target group of type `ip`, a listener, and a
path-based rule - by hand, one AWS call at a time.

```text
LAB 05, by hand                          LAB 08, from one Ingress object
  aws elbv2 create-load-balancer            spec.rules[]  and the ingress class
  aws elbv2 create-target-group             one target group per backend Service
     --target-type ip                       alb.ingress.kubernetes.io/target-type: ip
  aws elbv2 create-listener                 listen-ports annotation
  aws elbv2 create-rule --priority 10       spec.rules[].http.paths[]
  ecs register/deregister targets           the controller watches Endpoints
```

**Nothing new is being provisioned. The same ALB, asked for differently.** That sentence is the point
of running Practical 2 and Practical 4 back to back, and Step 17 asks you to write it in your own
words.

**And the economics.** Ten Services of type `LoadBalancer` is ten load balancers. Ten paths on one
Ingress is one. That is why Ingress exists.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, is there a controller?**

```bash
kubectl get ingressclass 2>/dev/null || echo "no IngressClass registered"
kubectl get pods -A | grep -Ei 'traefik|ingress|nginx-controller' || echo "no ingress controller pod found"
```

**What to look for:** an IngressClass named `traefik`, `nginx` or similar. If there is none, the
Ingress you create in part 2 will exist and never receive an address - a Conceptual result, and one
worth recording precisely rather than working around.

**Command - part 2, write the Ingress**

```bash
cat > manifests/lab-08/60-ingress.yaml << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: usms-portal-ingress
  namespace: usms
  labels:
    project: usms
    lab: "05b"
  annotations:
    # Real EKS, with the AWS Load Balancer Controller. Inert locally.
    # Each line maps to one command you ran by hand in Lab 05.
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}]'
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/tags: Project=USMS,Tier=web,Lab=08
spec:
  rules:
    - http:
        paths:
          - path: /enrolment
            pathType: Prefix
            backend:
              service:
                name: usms-enrolment
                port:
                  number: 80
          - path: /results
            pathType: Prefix
            backend:
              service:
                name: usms-results
                port:
                  number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: usms-gateway
                port:
                  number: 80
EOF

kubectl apply -f manifests/lab-08/60-ingress.yaml
kubectl get ingress
kubectl describe ingress usms-portal-ingress | tail -20
```

**What the command does**

**Rule order matters, and Kubernetes does not use the order you wrote.** An ingress controller matches
the **longest** matching path, so `/enrolment/x` reaches `usms-enrolment` even though `/` is also a
match. Compare that with Lab 05, where an ALB listener evaluated rules in **numeric priority order**
and you gave the `/alb-health` rule priority 10 so it would be seen before the default. Two systems,
two different disambiguation rules, and getting them confused produces routing that is subtly wrong
rather than obviously broken.

`pathType: Prefix` matches on whole path segments: `/results` matches `/results` and `/results/2026`
but not `/resultsarchive`. The alternative, `Exact`, matches only the literal path. There is a third,
`ImplementationSpecific`, which means "whatever this controller does", and which you should avoid for
exactly the reason its name suggests.

**Note what this Ingress bypasses.** `/enrolment` now goes **straight to `usms-enrolment`**, not
through `usms-gateway`. Both paths to that service now exist and they are genuinely different: the
gateway strips a prefix and adds headers; the Ingress rule does neither. That is a real architectural
choice - an in-cluster gateway service versus an edge router - and Section 15 Question 6 asks you to
take a position on it.

**Expected result**

```text
NAME                  CLASS     HOSTS   ADDRESS        PORTS   AGE
usms-portal-ingress   traefik   *       172.18.0.4     80      25s
```

or

```text
NAME                  CLASS    HOSTS   ADDRESS   PORTS   AGE
usms-portal-ingress   <none>   *                 80      25s
```

> Example output. The second, with no `CLASS` and no `ADDRESS`, is the no-controller case.

**Command - part 3, exercise the routes**

```bash
for P in / /enrolment/ /results/ ; do
  echo "--- $P ---"
  curl -s --max-time 5 "http://localhost:8081$P" || echo "  (no answer on 8081)"
  echo
done
```

If nothing answers on 8081, use the in-cluster equivalent, which tests the routing without depending
on host port publishing:

```bash
ADDR=$(kubectl get ingress usms-portal-ingress -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "ingress address: ${ADDR:-none}"

if [ -n "$ADDR" ]; then
  kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c "
    for P in / /enrolment/ /results/; do echo \"--- \$P ---\"; wget -qO- --timeout=5 http://$ADDR\$P; echo; done
  "
else
  echo "No ingress address: no controller is implementing this object."
  echo "Record it. The Ingress is a valid, stored, correct object with nothing acting on it."
fi
```

!!! note "Floci Limitation - an Ingress needs a controller, and one may not be running"
    Floci may start the cluster without an ingress controller, in which case your Ingress object is
    created, stored and served by the API server, and never given an address.

    On real EKS you install the AWS Load Balancer Controller - an IRSA-authenticated Deployment - and
    this same object produces an internet-facing ALB in your public subnets, with one target group per
    backend Service, targets of type `ip`, and one listener rule per path. Two or three minutes, and
    `ADDRESS` becomes an ALB DNS name.

    **What to take away regardless:** an Ingress is a *declaration of routing intent*. Its value does
    not come from the controller you happen to run; it comes from the fact that the same seven lines
    of routing produce a Traefik rule on a laptop and an ALB rule in production. That is worth more
    than either implementation.

    If you have no controller, say so in your report, and answer this instead, in prose: *which four
    `aws elbv2` commands from Lab 05 would the AWS Load Balancer Controller have run on your behalf,
    and in what order?* You have all four in Lab 05's Appendix A.

**Checkpoint 6**

```text
Exposure ladder, complete
 ├── ClusterIP     internal only                                     Lab 07
 ├── port-forward  a tunnel through the API server, one pod          Step 13
 ├── NodePort      usms-results-np  80:30080 on EVERY node           Step 14
 ├── LoadBalancer  usms-gateway  80:3xxxx  + external (or <pending>) Step 15
 │                   annotations: nlb-target-type ip, internet-facing
 └── Ingress       usms-portal-ingress   / -> gateway
                                         /enrolment -> enrolment
                                         /results   -> results
                     annotations map 1:1 onto Lab 05's elbv2 calls
                     longest-prefix match here; numeric priority there
```

---
### Step 17 - Write the Practical 2 / Practical 4 comparison, with both systems running

**Purpose**

Both stacks are up. The ECS service from Lab 04 is still running behind the ALB from Lab 05 with
the scaling policies from Lab 06, and the EKS cluster from Lab 07 is running the same application
with the objects from this lab. This is the only session in the course where you can check a claim
about the two rather than remember one.

**Run from**

```text
aws-floci-course/
```

**Command - look at both**

```bash
echo "=============== ECS / ALB / Application Auto Scaling ==============="
aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" --services usms-enrolment-svc \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,TaskDef:taskDefinition,
                        LB:loadBalancers[0].targetGroupArn,Grace:healthCheckGracePeriodSeconds}' \
  --output json 2>/dev/null

aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[0].{Id:ResourceId,Min:MinCapacity,Max:MaxCapacity}' --output json 2>/dev/null

aws application-autoscaling describe-scaling-policies --service-namespace ecs \
  --query 'ScalingPolicies[].{Name:PolicyName,Type:PolicyType}' --output table 2>/dev/null

echo
echo "=============== EKS / Ingress / HorizontalPodAutoscaler ==============="
kubectl get deploy,hpa,svc,ingress,pdb
```

**Command - write the comparison**

```bash
cat >> notes/lab-08-notes.md << 'EOF'

## Step 17 - Practical 2 and Practical 4, compared with both running

### Scaling

| Question | ECS + Application Auto Scaling | Kubernetes + HPA |
| --- | --- | --- |
| What integer is written? | | |
| Who writes it? | | |
| Where does that thing run? | | |
| Where does the metric come from? | | |
| What does "50% CPU" mean - 50% of what? | | |
| How is scale-in slowed down? | | |
| What happens if there is no capacity for the new instance/pod? | | |
| What creates the alarms, if anything? | | |

### Exposure

| Question | ECS + ALB (Lab 05) | Kubernetes + Ingress (Step 16) |
| --- | --- | --- |
| How many AWS objects did I create by hand? | | |
| What is the target type, and why? | | |
| How are targets registered and deregistered? | | |
| How are competing routing rules disambiguated? | | |
| What would I change to move this to another cloud? | | |
| What is the cost of exposing ten services? | | |

### Two paragraphs, in prose

1. If the AWS control plane has a bad afternoon, what happens to each of the two
   scaling arrangements, and which of them can I still debug?

2. For USMS specifically - one small team, one region, quiet for eight months and
   very busy for two - which would I choose, and what is the strongest argument
   AGAINST my own choice?
EOF

echo "now fill it in - notes/lab-08-notes.md"
```

**What to look for:** you filling it in, with both systems in front of you. Section 14 grades this
and Section 15 Questions 3 and 7 assume you have done it.

Two of the rows have answers that surprise people, so they are worth flagging rather than hiding.
"Where does that thing run?" - Application Auto Scaling runs in AWS, outside anything you own, so it
keeps working when your cluster is unhealthy and stops working when AWS's is. The HPA runs in the
Kubernetes controller manager, which on EKS is part of the control plane AWS operates for you, so the
answer is *almost* the same and not quite. And "what happens if there is no capacity" - ECS on
Fargate never runs out, because AWS supplies the capacity; the HPA absolutely does, and Step 9's
warning box is what that looks like.

---

### Step 18 - Prove that scaling and exposure configuration survive a restart

**Purpose**

The same rule the course has applied since Lab 1: prove the property, do not observe a proxy for it.
Here the property is that the HPA, the PDBs, the Services and the Ingress are stored state rather
than something that happened to be running.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the truth**

```bash
{
  echo "=== BEFORE RESTART $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  kubectl get hpa -o custom-columns='NAME:.metadata.name,MIN:.spec.minReplicas,MAX:.spec.maxReplicas,TARGET:.spec.metrics[0].resource.target.averageUtilization'
  kubectl get pdb -o custom-columns='NAME:.metadata.name,MINAVAIL:.spec.minAvailable,MAXUNAVAIL:.spec.maxUnavailable'
  kubectl get svc -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,NODEPORT:.spec.ports[0].nodePort'
  kubectl get ingress -o custom-columns='NAME:.metadata.name,PATHS:.spec.rules[0].http.paths[*].path'
  aws eks describe-nodegroup --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
    --query 'nodegroup.scalingConfig' --output text 2>/dev/null || echo "nodegroup: Path B"
} | tee outputs/lab-08-before-restart.txt
```

**Command - part 2, perturb**

!!! danger "Read before running any stop command"
    **What will be stopped:** the Floci container, via `docker compose stop`, and with it the
    containers running your cluster's nodes.
    **What depends on it:** every AWS API call, every `kubectl` call, and every pod.
    **Reversible?** Yes. `floci-down.sh` is `docker compose stop`, which keeps volumes and the
    bind-mounted data directory. It is **not** `docker compose down -v`, which is forbidden in this
    course precisely because `-v` deletes volumes.
    **Effect on later labs:** none, provided `FLOCI_STORAGE_MODE` is `hybrid`. If it is `memory`,
    this is the step where you find out, which is the point.

```bash
./scripts/setup/floci-down.sh
sleep 5
./scripts/setup/floci-up.sh
sleep 30
kubectl cluster-info || { echo "re-establishing kubeconfig"; aws eks update-kubeconfig --name "$USMS_EKS_CLUSTER" --alias usms-eks; }
kubectl config set-context --current --namespace=usms
```

**Command - part 3, read back**

```bash
{
  echo "=== AFTER RESTART $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  kubectl get hpa -o custom-columns='NAME:.metadata.name,MIN:.spec.minReplicas,MAX:.spec.maxReplicas,TARGET:.spec.metrics[0].resource.target.averageUtilization'
  kubectl get pdb -o custom-columns='NAME:.metadata.name,MINAVAIL:.spec.minAvailable,MAXUNAVAIL:.spec.maxUnavailable'
  kubectl get svc -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,NODEPORT:.spec.ports[0].nodePort'
  kubectl get ingress -o custom-columns='NAME:.metadata.name,PATHS:.spec.rules[0].http.paths[*].path'
  aws eks describe-nodegroup --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
    --query 'nodegroup.scalingConfig' --output text 2>/dev/null || echo "nodegroup: Path B"
} | tee outputs/lab-08-after-restart.txt

echo
diff <(grep -v '^===' outputs/lab-08-before-restart.txt) \
     <(grep -v '^===' outputs/lab-08-after-restart.txt) \
  && echo "PERSISTENCE PROVEN - scaling and exposure configuration identical" \
  || echo "differences above - read them before deciding whether they matter"
```

**What to look for:** an identical set of rows. Two differences are legitimate and you should decide
about them rather than dismissing them:

- **A `nodePort` that changed.** If a port was auto-allocated rather than pinned, a new one may be
  assigned. `usms-results-np` was pinned to 30080 in Step 14 and must not change; `usms-gateway`'s was
  allocated and may. That contrast is the argument for pinning, arriving on its own.
- **An `EXTERNAL-IP` that is now `<pending>` again.** The Service object persisted; the thing that
  fulfils it restarted. On real AWS the load balancer would still exist and the address would still be
  the same, because the load balancer is not part of the cluster.

**If the HPA or the Ingress is missing entirely**, run `./scripts/utilities/floci-storage-check.sh`
before anything else. Storage mode `memory` is the cause in the overwhelming majority of cases.

**Checkpoint 7**

```text
PERSISTENCE PROVEN
 ├── usms-enrolment-hpa    min 2 max 8 target 50
 ├── usms-enrolment-pdb    maxUnavailable 1
 ├── usms-gateway-pdb      minAvailable 1
 ├── usms-results-np       NodePort 30080  (pinned - unchanged)
 ├── usms-gateway          LoadBalancer    (nodePort may differ - allocated, not pinned)
 ├── usms-portal-ingress   /enrolment /results /
 └── usms-eks-nodes        min 2 max 6 desired 3   (or Path B)
```

---

### Step 19 - Write `configs/lab-08.env`

**Purpose**

The same contract as every lab. IDs and names, never secrets, looked up rather than remembered.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-08.env << EOF
# Lab 08 - EKS scaling and service exposure
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains names, ports and numbers only. NO SECRETS. Safe to commit.

export USMS_HPA_NAME=usms-enrolment-hpa
export USMS_HPA_MIN=$(kubectl get hpa usms-enrolment-hpa -n usms \
  -o jsonpath='{.spec.minReplicas}' 2>/dev/null)
export USMS_HPA_MAX=$(kubectl get hpa usms-enrolment-hpa -n usms \
  -o jsonpath='{.spec.maxReplicas}' 2>/dev/null)
export USMS_HPA_CPU_TARGET=$(kubectl get hpa usms-enrolment-hpa -n usms \
  -o jsonpath='{.spec.metrics[0].resource.target.averageUtilization}' 2>/dev/null)
export USMS_HPA_SCALEDOWN_WINDOW=$(kubectl get hpa usms-enrolment-hpa -n usms \
  -o jsonpath='{.spec.behavior.scaleDown.stabilizationWindowSeconds}' 2>/dev/null)

export USMS_PDB_GATEWAY=usms-gateway-pdb
export USMS_PDB_ENROLMENT=usms-enrolment-pdb

export USMS_SVC_NODEPORT_NAME=usms-results-np
export USMS_SVC_NODEPORT=$(kubectl get svc usms-results-np -n usms \
  -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)
export USMS_SVC_GATEWAY_TYPE=$(kubectl get svc usms-gateway -n usms \
  -o jsonpath='{.spec.type}' 2>/dev/null)
export USMS_SVC_GATEWAY_NODEPORT=$(kubectl get svc usms-gateway -n usms \
  -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)

export USMS_INGRESS_NAME=usms-portal-ingress
export USMS_INGRESS_CLASS=$(kubectl get ingress usms-portal-ingress -n usms \
  -o jsonpath='{.spec.ingressClassName}' 2>/dev/null)

export USMS_NODEGROUP_MIN=$(aws eks describe-nodegroup --cluster-name usms-eks-cluster \
  --nodegroup-name usms-eks-nodes --query 'nodegroup.scalingConfig.minSize' --output text 2>/dev/null)
export USMS_NODEGROUP_MAX=$(aws eks describe-nodegroup --cluster-name usms-eks-cluster \
  --nodegroup-name usms-eks-nodes --query 'nodegroup.scalingConfig.maxSize' --output text 2>/dev/null)
export USMS_NODEGROUP_DESIRED=$(aws eks describe-nodegroup --cluster-name usms-eks-cluster \
  --nodegroup-name usms-eks-nodes --query 'nodegroup.scalingConfig.desiredSize' --output text 2>/dev/null)

export USMS_NODE_LABEL_SELECTOR=workload=usms
export USMS_LOADGEN_DEPLOY=usms-loadgen
export USMS_K8S_MANIFEST_DIR_05B=manifests/lab-08
EOF

grep -n 'export .*=$\|None' configs/lab-08.env || echo "all values populated"
```

**What the command does**

**The heredoc is unquoted.** Every `$(...)` runs now, and values land on disk. Every manifest in this
lab used the quoted form for the opposite reason. That contrast has now appeared in five labs, and it
is still the most common silent bug in the course.

Every value that can be looked up **is** looked up - from the cluster for Kubernetes objects, from the
AWS API for the node group. Nothing is taken from a shell variable, so a deleted object shows as empty
and the check below catches it.

**Expected result**

```text
all values populated
```

Three expected exceptions, and they are not gaps:

- `USMS_INGRESS_CLASS` is empty if no ingress controller is running. Step 16 recorded that.
- `USMS_SVC_GATEWAY_NODEPORT` is empty if the Service never left `ClusterIP` - which should not be
  the case after Step 15, so investigate if you see it.
- The three `USMS_NODEGROUP_*` values are empty on support Path B. Expected; note it.

**Verify**

```bash
source configs/lab-08.env
echo "hpa: $USMS_HPA_MIN..$USMS_HPA_MAX at ${USMS_HPA_CPU_TARGET}% cpu, scale-in window ${USMS_HPA_SCALEDOWN_WINDOW}s"
echo "nodeport: $USMS_SVC_NODEPORT   gateway: $USMS_SVC_GATEWAY_TYPE"
grep -c '^export' configs/lab-08.env
```

**What to look for:** `hpa: 2..8 at 50% cpu, scale-in window 300s`, `nodeport: 30080`, `gateway:
LoadBalancer`, and a count of **19** exported variables.

---

### Step 20 - Commit your work

**Purpose**

The same check as every lab, preserving the property that `.gitignore` was the repository's first
commit.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look before you add**

```bash
git status --short
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears. This lab wrote six files there, including
  `lab-08-eviction.json`, which names a pod and is harmless, and the before/after snapshots.
- No `.env` at the repository root appears.
- `configs/lab-08.env` **does** appear - names and numbers, no secrets.
- `manifests/lab-07/20-enrolment.yaml` appears, because Step 11 added a `nodeSelector` to it. That
  is intentional and is exactly the drift-prevention habit from Step 5.

If anything under `outputs/` is listed, diagnose before committing:

```bash
git check-ignore -v outputs/lab-08-baseline.txt
```

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-08-baseline.txt
```

> Example output - the line number will differ.

If it prints nothing, the file is not ignored and the rule is probably `outputs/` rather than
`outputs/*` - the silent failure described in §15 of the course contract.

**Command - part 2, add and commit**

```bash
git add labs/lab-08-eks-scaling manifests/lab-08 manifests/lab-07/20-enrolment.yaml \
        configs/lab-08.env scripts/utilities/verify-lab-08.sh \
        scripts/utilities/hpa-watch.sh scripts/cleanup/lab-08-cleanup.sh \
        notes/lab-08-notes.md

git status --short

git commit -m "Lab 08: EKS scaling and service exposure

- usms-enrolment-hpa, autoscaling/v2, min 2 max 8, cpu 50% of the 50m request,
  scale-up instant and rate-limited, scale-in behind a 300s stabilisation window
- usms-loadgen used to drive the autoscaler; observed 2 -> 4 -> 2
- usms-eks-nodes rescaled min 2 / max 6 / desired 3 from the AWS side
- nodeSelector workload=usms on usms-enrolment, enforcement proven
- PodDisruptionBudgets on gateway and enrolment; eviction API vs delete demonstrated
- exposure ladder climbed: port-forward, NodePort 30080, LoadBalancer, Ingress
- Ingress annotations mapped one-to-one onto Lab 05's elbv2 calls
- persistence proven for HPA, PDBs, Services and Ingress across a Floci restart"
```

**Verify**

```bash
git log --oneline -2
git show --stat --oneline HEAD | head -20
git ls-files | grep -c '^outputs/'
```

**What to look for:** this commit and Lab 07's beneath it; a file list containing
`manifests/lab-08/` and `configs/lab-08.env`; and **`0`** from the last command.

**Checkpoint 8**

```text
committed
 ├── manifests/lab-08/    10-hpa-enrolment, 20-loadgen, 30-pdb-gateway,
 │                         40-service-nodeport, 50-service-loadbalancer, 60-ingress
 ├── manifests/lab-07/20-enrolment.yaml   updated with the nodeSelector
 ├── configs/lab-08.env   19 exports
 ├── scripts/utilities/    verify-lab-08.sh, hpa-watch.sh
 ├── scripts/cleanup/      lab-08-cleanup.sh  (written, NOT run)
 └── git ls-files outputs/ -> only .gitkeep
```

---

### 8.5 Path C - what to do if you have no cluster

This lab is harder to do on paper than Lab 07, because its subject is watching numbers move. It is
still worth doing, and here is the honest version:

1. **Write every manifest** in Section 7's list and validate them with
   `kubectl apply --dry-run=client -f manifests/lab-08/`. No cluster is needed.
2. **Do Step 3, Step 6 and Step 8's concept sections in full**, and work the HPA arithmetic by hand
   for at least three cases: 2 pods at 80%, 4 pods at 30%, and 8 pods at 95% with `maxReplicas: 8`.
   Show the `ceil` calculation each time and say what `behavior` would allow.
3. **Do Step 10 if you are on Path A** - it is a pure AWS CLI step and needs no `kubectl`.
4. **Do Step 17 in full.** It is the most valuable step in the lab and it requires only that you can
   read Lab 05 and Lab 06, both of which you have.
5. **Answer all of Section 15**, and do Section 13's Exercises 3 and 4 on paper, giving the commands
   you would run and the output you would expect, clearly labelled as expected rather than observed.

That is a legitimate submission. An invented `kubectl get hpa` output showing a percentage is not.

---
## 9. Verification

### 9.1 Build `scripts/utilities/verify-lab-08.sh`

**Run from**

```text
aws-floci-course/
```

````markdown
{% raw %}```bash
cat > scripts/utilities/verify-lab-08.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 08 artefact. Exit 1 if anything is missing.
# Works from any directory. Checks CONFIGURATION, not just existence.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-07.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-08.env" 2>/dev/null || true
NS=usms

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}
kget() { kubectl get "$1" "$2" -n "$NS" -o jsonpath="$3" 2>/dev/null; }

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "kubectl reaches an API server" "kubectl version --request-timeout=10s"

echo "== Lab 07 dependencies =="
check "namespace usms exists" "kubectl get namespace $NS"
check "usms-enrolment has at least 2 ready replicas" \
  "test \"\$(kget deploy usms-enrolment '{.status.readyReplicas}')\" -ge 2"
check "usms-enrolment declares a cpu request (the HPA's denominator)" \
  "kget deploy usms-enrolment '{.spec.template.spec.containers[0].resources.requests.cpu}' | grep -q 'm'"
check "cluster carries the _lb_ports_ tag (expect FAIL on Path B)" \
  "aws eks describe-cluster --name usms-eks-cluster --query 'cluster.tags._lb_ports_' --output text | grep -q 8081"

echo "== Lab 08: autoscaling =="
check "HorizontalPodAutoscaler usms-enrolment-hpa exists" "kubectl get hpa usms-enrolment-hpa -n $NS"
check "HPA is autoscaling/v2 with a behavior block" \
  "test -n \"\$(kget hpa usms-enrolment-hpa '{.spec.behavior.scaleDown.stabilizationWindowSeconds}')\""
check "HPA targets Deployment usms-enrolment" \
  "test \"\$(kget hpa usms-enrolment-hpa '{.spec.scaleTargetRef.name}')\" = usms-enrolment"
check "HPA minReplicas is 2" "test \"\$(kget hpa usms-enrolment-hpa '{.spec.minReplicas}')\" = 2"
check "HPA maxReplicas is 8" "test \"\$(kget hpa usms-enrolment-hpa '{.spec.maxReplicas}')\" = 8"
check "HPA cpu target is 50" \
  "test \"\$(kget hpa usms-enrolment-hpa '{.spec.metrics[0].resource.target.averageUtilization}')\" = 50"
check "HPA scale-in stabilisation window is 300s" \
  "test \"\$(kget hpa usms-enrolment-hpa '{.spec.behavior.scaleDown.stabilizationWindowSeconds}')\" = 300"

echo "== Lab 08: disruption budgets =="
check "PodDisruptionBudget usms-gateway-pdb exists" "kubectl get pdb usms-gateway-pdb -n $NS"
check "usms-gateway-pdb uses minAvailable 1" \
  "test \"\$(kget pdb usms-gateway-pdb '{.spec.minAvailable}')\" = 1"
check "usms-enrolment-pdb uses maxUnavailable 1" \
  "test \"\$(kget pdb usms-enrolment-pdb '{.spec.maxUnavailable}')\" = 1"

echo "== Lab 08: exposure ladder =="
check "usms-results-np is a NodePort Service" \
  "test \"\$(kget svc usms-results-np '{.spec.type}')\" = NodePort"
check "usms-results-np is pinned to node port 30080" \
  "test \"\$(kget svc usms-results-np '{.spec.ports[0].nodePort}')\" = 30080"
check "usms-results-np selects the same pods as usms-results" \
  "test \"\$(kget svc usms-results-np '{.spec.selector.app}')\" = usms-results"
check "usms-gateway is now type LoadBalancer" \
  "test \"\$(kget svc usms-gateway '{.spec.type}')\" = LoadBalancer"
check "usms-gateway kept a nodePort (each rung keeps the one below)" \
  "test -n \"\$(kget svc usms-gateway '{.spec.ports[0].nodePort}')\""
check "Ingress usms-portal-ingress exists" "kubectl get ingress usms-portal-ingress -n $NS"
check "Ingress declares three paths" \
  "test \"\$(kget ingress usms-portal-ingress '{.spec.rules[0].http.paths[*].path}' | wc -w)\" -eq 3"
check "Ingress carries the ALB target-type annotation" \
  "kget ingress usms-portal-ingress '{.metadata.annotations}' | grep -q 'target-type'"

echo "== Lab 08: data plane (expect FAIL on Path B) =="
check "node group maxSize was raised to 6" \
  "test \"\$(aws eks describe-nodegroup --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes --query 'nodegroup.scalingConfig.maxSize' --output text)\" = 6"

echo "== Files and Git hygiene =="
check "configs/lab-08.env exists" "test -f configs/lab-08.env"
check "configs/lab-08.env records the HPA bounds" \
  "grep -qE '^export USMS_HPA_MIN=[0-9]+' configs/lab-08.env"
check "six or more Lab 08 manifests present" \
  "test \"\$(ls manifests/lab-08/*.yaml 2>/dev/null | wc -l)\" -ge 6"
check "every Lab 08 manifest passes a client-side dry run" \
  "kubectl apply --dry-run=client -f manifests/lab-08/"
check "hpa-watch.sh is executable" "test -x scripts/utilities/hpa-watch.sh"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"
check ".gitignore uses outputs/* not outputs/" "grep -q '^outputs/\*' .gitignore"

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-08.sh
./scripts/utilities/verify-lab-08.sh
```{% endraw %}
````

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   kubectl reaches an API server
== Lab 07 dependencies ==
  ok   namespace usms exists
  ...
== Lab 08: exposure ladder ==
  ok   usms-results-np is a NodePort Service
  ...
== Files and Git hygiene ==
  ok   no secret is tracked by git
  ok   .gitignore uses outputs/* not outputs/

PASS=34  FAIL=0
```

> Example output - the `ok` lines are abbreviated; you will see all 34.

**How to read a failure.** Failures in the **Environment** block are the real problem and everything
below is usually a consequence.

On support **Path B**, expect exactly **two** failures - the `_lb_ports_` tag and the node group's
`maxSize` - both marked in the script itself. `PASS=32  FAIL=2` is a correct Path B result. Any other
failure is genuine.

### 9.2 A quick end-to-end check you can run any time

```bash
kubectl run usms-smoke --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  G=http://usms-gateway.usms.svc.cluster.local
  wget -qO- $G/ && wget -qO- $G/enrolment/ && wget -qO- $G/results/
' && echo "SMOKE TEST PASSED"

kubectl get hpa,pdb,svc,ingress
```

### 9.3 Build the cleanup script - DO NOT RUN IT NOW

!!! danger "This script removes everything Lab 08 added"
    **What will be deleted:** the HPA, both PDBs, the NodePort Service, the Ingress and the load
    generator; `usms-gateway` reverts to `ClusterIP`; the node group returns to Lab 07's numbers.
    **What depends on it:** nothing in Lab 10 or Lab 07. The cluster and the three microservices from
    Lab 07 survive.
    **Reversible?** Yes - every object is in `manifests/lab-08/` and can be re-applied.
    **Effect on later labs:** none. Run `lab-08-cleanup.sh` **before** `lab-07-cleanup.sh`, because
    a LoadBalancer Service can hold a load balancer that blocks the cluster's deletion.

```bash
cat > scripts/cleanup/lab-08-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Removes every Lab 08 object. Run BEFORE lab-07-cleanup.sh.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
NS=usms

cat <<'WARN'
This removes:
  - Ingress usms-portal-ingress
  - Service usms-results-np (NodePort)
  - usms-gateway reverts from LoadBalancer to ClusterIP
  - HorizontalPodAutoscaler usms-enrolment-hpa
  - PodDisruptionBudgets usms-gateway-pdb and usms-enrolment-pdb
  - Deployment usms-loadgen
  - node group scaling config returns to min 2 / max 4 / desired 2
It does NOT remove the cluster, the namespace, or the three microservices.
WARN

printf 'Type exactly DELETE-LAB-08 to proceed: '
read -r CONFIRM
[ "$CONFIRM" = "DELETE-LAB-08" ] || { echo "aborted"; exit 1; }

# 1. Ingress first: it references Services, and an orphaned ALB is worse than an orphaned rule.
kubectl delete ingress usms-portal-ingress -n "$NS" --ignore-not-found

# 2. The LoadBalancer Service next, so any cloud load balancer is released
#    before anything else is torn down.
kubectl patch svc usms-gateway -n "$NS" --type=merge -p '{"spec":{"type":"ClusterIP"}}' 2>/dev/null
kubectl delete svc usms-results-np -n "$NS" --ignore-not-found

# 3. Controllers that write to Deployments, before the Deployments themselves.
kubectl delete hpa usms-enrolment-hpa -n "$NS" --ignore-not-found
kubectl delete pdb usms-gateway-pdb usms-enrolment-pdb -n "$NS" --ignore-not-found

# 4. The load generator.
kubectl delete deployment usms-loadgen -n "$NS" --ignore-not-found

# 5. AWS side last: nothing in Kubernetes depends on it.
aws eks update-nodegroup-config \
  --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes \
  --scaling-config minSize=2,maxSize=4,desiredSize=2 >/dev/null 2>&1 \
  || echo "node group unchanged (Path B, or the eks API is unavailable)"

echo "Lab 08 objects removed. The Lab 07 cluster and application are untouched."
EOF

chmod +x scripts/cleanup/lab-08-cleanup.sh
bash -n scripts/cleanup/lab-08-cleanup.sh && echo "cleanup script: valid bash syntax"
```

The deletion order is the lesson again, and it is different from Lab 07's: **Ingress, LoadBalancer
Service, controllers, workloads, AWS.** The rule underneath it is always the same - remove the thing
that *references* before the thing *referenced*, and remove anything that provisions external
infrastructure before you remove what it was provisioned for. An ALB left behind by a deleted cluster
is the classic way to be billed for something you cannot find.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 2 | Floci running; five env files sourced; `verify-lab-07.sh` at `FAIL=0` (Path A) or `FAIL=3` (Path B); `usms-enrolment` declaring a CPU request; the `_lb_ports_` tag present or its absence recorded; a baseline in `outputs/lab-08-baseline.txt` |
| 2 | Step 5 | `kubectl scale` observed writing one field with no new ReplicaSet; endpoints growing only on readiness; drift created and resolved by `apply`; `kubectl diff` used and its exit code understood; `usms-enrolment` back at 2/2 |
| 3 | Step 9 | `usms-enrolment-hpa` created as `autoscaling/v2` with a `behavior` block; replicas observed moving under load and returning after the 300-second window - **or** `<unknown>` diagnosed, the condition quoted verbatim and the arithmetic worked by hand |
| 4 | Step 12 | Node group at min 2 / max 6 / desired 3 (Path A); `nodeSelector` applied and its enforcement proven with a deliberately bad value; both PDBs created; the eviction API refusing and `kubectl delete` succeeding, both demonstrated |
| 5 | Step 14 | ClusterIP shown to be unroutable from the host; `port-forward` used and its limits stated; `usms-results-np` on pinned port 30080, answering through **every** node address |
| 6 | Step 16 | `usms-gateway` type `LoadBalancer` with a `clusterIP`, a `nodePort` and an external address (or a recorded `<pending>`); `usms-portal-ingress` with three prefix paths; the annotation-to-`elbv2` mapping written down |
| 7 | Step 18 | `PERSISTENCE PROVEN` after a Floci stop and start, with the HPA bounds, both PDBs, the pinned node port and the Ingress paths all identical; any changed auto-allocated port explained rather than dismissed |
| 8 | Step 20 | `configs/lab-08.env` with 19 exports; `manifests/lab-07/20-enrolment.yaml` updated with the `nodeSelector` so the repository matches the cluster; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 11. Troubleshooting

??? danger "`kubectl get hpa` shows `<unknown>/50%` and never changes"
    The HPA cannot compute utilisation. `describe` names which of the two causes it is:

    ```bash
    kubectl describe hpa usms-enrolment-hpa | sed -n '/Conditions/,/Events/p'
    ```

    `FailedGetResourceMetric` with `unable to get metrics for resource cpu` means the metrics
    pipeline is not working - go back to Step 7 and check
    `kubectl get --raw /apis/metrics.k8s.io/v1beta1`.

    `missing request for cpu` means the container has no CPU request. Nothing about the HPA can be
    changed to work around it; fix the Deployment:

    ```bash
    kubectl set resources deployment/usms-enrolment --requests=cpu=50m,memory=32Mi
    ```

    A third, rarer case: the HPA is fine but you are reading it within the first 15 to 30 seconds of
    its life, before the first poll. Wait and re-read before diagnosing anything.

??? danger "The HPA scales up, but the new pods stay `Pending`"
    Dimensions 1 and 3 from Step 3 failing to meet. The autoscaler did its job; there is no room.

    ```bash
    kubectl get pods -l app=usms-enrolment
    kubectl describe pod <a pending one> | tail -6
    kubectl describe node <any node> | sed -n '/Allocated resources/,/Events/p'
    ```

    `Insufficient cpu` confirms it. The real answers are more nodes (Step 10, or a cluster autoscaler)
    or a lower `maxReplicas`. **Do not lower the CPU request to make the pods fit** - that changes the
    HPA's denominator, so every percentage you have recorded becomes incomparable, and the autoscaler
    will then scale more aggressively for the same real load.

??? danger "`kubectl scale` appears to work and then the replica count changes back"
    The HPA owns `spec.replicas` now. Within 15 seconds it will overwrite anything you set outside
    `minReplicas` to `maxReplicas`, and inside that range it will overwrite you as soon as the metric
    justifies a different number.

    This is correct behaviour, not a conflict to resolve. If you need to scale by hand - during an
    incident, say - the supported way is to remove the HPA's authority first:

    ```bash
    kubectl delete hpa usms-enrolment-hpa
    kubectl scale deployment/usms-enrolment --replicas=6
    # ... and re-apply the HPA afterwards
    kubectl apply -f manifests/lab-08/10-hpa-enrolment.yaml
    ```

    Note the consequence for your repository: `replicas:` in `manifests/lab-07/20-enrolment.yaml` is
    now only an initial value, and `kubectl diff` will report it as a difference forever. That is
    expected. Teams usually resolve it by removing the `replicas` field from a manifest once an HPA
    owns it.

??? danger "The load generator runs but CPU never rises"
    Check that the load is actually arriving:

    ```bash
    kubectl logs deploy/usms-loadgen --tail=5
    kubectl top pods
    kubectl exec deploy/usms-loadgen -- wget -qO- http://usms-gateway.usms.svc.cluster.local/enrolment/
    ```

    If the last command returns JSON, the path works and the loop is simply not generating enough
    load. Raise `replicas` on `usms-loadgen`. If it fails, the gateway or a backend is down and the
    autoscaler is not your problem yet.

    A subtler cause: the YAML `>` folded block in the manifest lost its trailing semicolons during an
    edit, and the container is crash-looping. `kubectl get pods -l app=usms-loadgen` shows it
    immediately.

??? danger "`nodePort: 30080` is rejected with `provided port is already allocated`"
    Another Service in the cluster - possibly in a different namespace - has that port.

    ```bash
    kubectl get svc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type,NODEPORT:.spec.ports[*].nodePort' | grep 30080
    ```

    Either free it, or pick another port in 30000–32767 and update
    `manifests/lab-08/40-service-nodeport.yaml` and `configs/lab-08.env`. Do not simply remove the
    `nodePort` line unless you intend to give up pinning - Step 18's persistence check depends on the
    port being stable.

??? danger "`EXTERNAL-IP` stays `<pending>` forever"
    Nothing is implementing `type: LoadBalancer` on this cluster. That is an expected outcome locally
    and is covered in Step 15's limitation box.

    ```bash
    kubectl describe svc usms-gateway | tail -10
    kubectl get pods -A | grep -Ei 'cloud-controller|servicelb|klipper'
    ```

    An `Events` section with no entries at all is the tell: nothing even *tried*. On real EKS with the
    AWS Load Balancer Controller you would see `EnsuringLoadBalancer` followed by
    `EnsuredLoadBalancer`, and a stuck `EnsuringLoadBalancer` would mean an IAM or subnet-tagging
    problem - the public subnets need `kubernetes.io/role/elb=1` for an internet-facing balancer, and
    forgetting that tag is the commonest cause on a hand-built VPC like Lab 02's.

??? danger "The Ingress exists but has no ADDRESS and nothing routes"
    No ingress controller is running, or the Ingress does not name a class the controller claims.

    ```bash
    kubectl get ingressclass
    kubectl describe ingress usms-portal-ingress | tail -12
    ```

    If an IngressClass exists but is not the default, name it explicitly:

    ```bash
    kubectl patch ingress usms-portal-ingress --type=merge \
      -p '{"spec":{"ingressClassName":"traefik"}}'
    ```

    If no IngressClass exists at all, this is the Conceptual case. Record it and answer Step 16's
    written alternative.

??? danger "A drain hangs and never finishes"
    A PodDisruptionBudget is refusing evictions - most likely `usms-gateway-pdb`, whose
    `minAvailable: 1` against a single replica means no eviction is ever allowed.

    ```bash
    kubectl get pdb
    kubectl describe pdb usms-gateway-pdb
    ```

    `ALLOWED DISRUPTIONS: 0` is the confirmation. The correct fix is to make the workload drainable -
    scale the gateway to 2 replicas - not to delete the PDB. Exercise 2 is exactly this.

    If you must proceed now: ++ctrl+c++ the drain, `kubectl uncordon <node>`, and deal with it
    properly. A node left cordoned is a confusing state to inherit next week.

??? danger "After the restart, `kubectl` works but the namespace default is gone"
    The kubeconfig was rewritten by `update-kubeconfig`, which sets the context but not your chosen
    default namespace.

    ```bash
    kubectl config set-context --current --namespace=usms
    kubectl config view --minify --output 'jsonpath={..namespace}'; echo
    ```

    Worth adding to your own shell profile if you find yourself doing it often.

---

## 12. Floci vs Real AWS

### 12.1 Feature comparison

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `kubectl scale`, `replicas` in a manifest | Standard | Standard | Implemented in Floci |
| Rolling update strategy, readiness gating of endpoints | Standard | Standard | Implemented in Floci |
| HorizontalPodAutoscaler `autoscaling/v2`, `behavior` | Standard | Standard, provided metrics exist | Implemented in Floci |
| metrics-server and `kubectl top` | Installed once, or as an EKS add-on | Usually present on k3s; installable; sometimes not reachable | Implemented in Floci (build-dependent) |
| PodDisruptionBudget and the eviction API | Standard | Standard | Implemented in Floci |
| `nodeSelector`, node labels | Standard; node group labels reach the nodes | Standard; the node group's labels may not reach the nodes | Implemented in Floci (with a caveat) |
| Service types, `nodePort` allocation | Standard | Standard | Implemented in Floci |
| Ingress objects and path routing | Standard | Standard **as objects**; whether they route depends on the controller | Floci Limitation |
| `update-nodegroup-config` changing capacity | Changes the ASG; instances launch and join | Recorded and returned; no node appears | Floci Limitation |
| `type: LoadBalancer` provisioning something | An NLB in your public subnets, targets registered | May stay `<pending>`; `_lb_ports_` publishes host ports when supported | Floci Limitation |
| NodePort reachable from outside the cluster | Any host that can route to the nodes, subject to the security group | Only if the node container published that port | Floci Limitation |
| AWS Load Balancer Controller creating an ALB from an Ingress | Yes - this is how EKS does Ingress | Not installed; needs IRSA | Conceptual / Real AWS |
| Cluster Autoscaler | Watches `Pending` pods, writes `desiredSize` | Not installed; needs IRSA and a real ASG | Conceptual / Real AWS |
| Karpenter | Launches right-sized instances directly | Not installed | Conceptual / Real AWS |
| Custom and external metrics for the HPA (Prometheus adapter, CloudWatch adapter) | Supported, widely used | Not installed | Conceptual / Real AWS |
| Scheduled scaling (Lab 06 had it for ECS) | CronJob patching an HPA, or KEDA | Not installed | Conceptual / Real AWS |
| Subnet tags `kubernetes.io/role/elb` for load balancer placement | Required, and easy to forget | Not enforced | Conceptual / Real AWS |
| Cost of a LoadBalancer Service | One NLB per Service, per hour, plus data | Free | Conceptual / Real AWS |

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **Scaling is instantaneous.** A pod starts in a second here. A real EKS node takes 60 to 120
  seconds to launch, bootstrap and become `Ready`, so a scale-out that needs a new node takes minutes.
  Any capacity plan that ignores that is wrong.
- **No cost signal at all.** Ten `LoadBalancer` Services is ten NLBs. Six `t3.small` nodes running
  over a semester break is a real bill. `maxReplicas: 8` and `maxSize: 6` are not just safety limits,
  they are spending limits.
- **No quotas.** Real accounts have limits on load balancers per region, on Elastic IPs, and on
  instances per instance-family. A scale-out that hits a quota fails in a way that looks like a
  scheduling problem.
- **The metrics window is short and local.** A real cluster's HPA behaviour under a genuinely bumpy
  workload is much less tidy than the clean up-and-down you saw in Step 9.
- **Nothing is eventually consistent.** On AWS, an ALB created from an Ingress takes minutes to become
  healthy, and a target that has just been registered fails health checks for a while by design.

### 12.3 What you actually observed in this lab

```text
OBSERVABLE, and you saw it
  manual and declarative scaling, and the drift between them
  endpoints growing only on readiness; scale-in removing from endpoints first
  QoS classes, and the scheduler's allocated-resources arithmetic
  the HPA computing a percentage of the REQUEST, and acting on it
  scale-up policies and selectPolicy: Max choosing the more permissive
  the 300-second stabilisation window holding capacity after load stopped
  nodeSelector enforcement, and maxUnavailable 0 protecting running pods
  a PDB refusing an eviction, and a plain delete ignoring it
  ClusterIP unroutable from the host; port-forward tunnelling through the API server
  a NodePort answering on EVERY node, including nodes with no pods
  a LoadBalancer Service keeping its clusterIP and nodePort
  an Ingress object with three prefix paths

RECORDED BUT NOT ENACTED
  the node group's min, max and desired sizes
  the AWS load balancer annotations on the Service and the Ingress
  whatever your build reports for EXTERNAL-IP

CONCEPTUAL ONLY - you read about it and could not run it
  the AWS Load Balancer Controller turning the Ingress into an ALB
  Cluster Autoscaler and Karpenter
  custom and external metrics
  scheduled scaling, quotas, throttling and cost
```

When you write your report, say which column a claim belongs to. "I configured cluster autoscaling"
is not true. "I wrote the Ingress and node group configuration that a cluster autoscaler and the AWS
Load Balancer Controller would act on, mapped every annotation to the Lab 05 command it replaces, and
recorded that neither controller is installed on this build" is true, and is worth more.

---
## 13. Independent Lab Exercises

Work in `labs/lab-08-eks-scaling/exercises.md`. Record commands and output there, and screenshots in
`screenshots/`. Hints point at documentation or an earlier step; none contains the answer.

### Exercise 1 - Basic: a second autoscaler

**Requirements**

Give `usms-results` its own HorizontalPodAutoscaler: minimum 2, maximum 6, targeting 60% CPU, with a
scale-in stabilisation window of 180 seconds and a scale-up policy that adds at most 2 pods every 30
seconds.

**Constraints**

- `autoscaling/v2`, written as a manifest at `manifests/lab-08/11-hpa-results.yaml`. Do not use
  `kubectl autoscale`.
- The manifest must apply cleanly on a client-side dry run before you apply it for real.
- Say in one sentence why 60% is a defensible target for a read-mostly results service when
  `usms-enrolment` uses 50%.

**Expected outcome**

`kubectl get hpa` shows two HPAs, both reporting a percentage rather than `<unknown>`. If your build
has no metrics pipeline, both will show `<unknown>` and that is a consistent result - say so.

**Hints**

`manifests/lab-08/10-hpa-enrolment.yaml` is the model. The only fields that change are the target
name, the two bounds, the percentage and three numbers inside `behavior`. Check that `usms-results`
actually declares a CPU request before you start - Lab 07 Step 14 set one, but check rather than
assume.

---

### Exercise 2 - Intermediate: make the gateway drainable

**Requirements**

Step 12 showed that `usms-gateway-pdb` allows **zero** disruptions, because a `minAvailable` of 1
against a single replica leaves no slack. Fix that properly, and prove it.

**Constraints**

- The gateway must end the exercise with `ALLOWED DISRUPTIONS` of at least 1.
- You may not weaken the PDB. `minAvailable: 1` stays, or you must justify a change in writing.
- The gateway's pods must not all be on the same node, where the cluster has more than one node. If
  it has only one, say so and state what you would have done.
- Update `manifests/lab-07/40-gateway.yaml` so the repository matches the cluster. Show
  `kubectl diff` producing no difference afterwards.

**Expected outcome**

`kubectl get pdb` showing a non-zero allowance for `usms-gateway-pdb`, `kubectl get pods -o wide`
showing the gateway pods' node placement, and a clean `kubectl diff`.

**Hints**

The PDB is not the thing to change. Lab 07 Exercise 4 named three Kubernetes features for spreading
pods across nodes; you need at most one of them here, and the simplest fix does not need any of them.

---

### Exercise 3 - Problem solving: the autoscaler that will not act

**Requirements**

Apply the manifest below exactly as given. It is valid, `kubectl apply` accepts it, the HPA is
created, and under heavy sustained load the Deployment's replica count never changes. Diagnose it
with commands, state **both** causes in one sentence each, and fix them with the smallest change to
each.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-reports
  namespace: usms
spec:
  replicas: 2
  selector:
    matchLabels:
      app: usms-reports
  template:
    metadata:
      labels:
        app: usms-reports
    spec:
      containers:
        - name: reports
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          resources:
            limits:
              cpu: "200m"
              memory: "128Mi"
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: usms-reports-hpa
  namespace: usms
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: usms-reports
  minReplicas: 4
  maxReplicas: 4
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Constraints**

- Find both faults with commands, not by reading the YAML. Show the commands in the order you ran
  them, and the output that revealed each.
- Each fix must be a single field.
- One fault makes the HPA report `<unknown>`; the other makes it incapable of acting even with
  perfect metrics. Say which is which.

**Expected outcome**

A short diagnosis naming both faults with the evidence for each, and an HPA that reports a percentage
and has room to move. Delete `usms-reports` and its HPA afterwards - it is a CLEAN UP item.

**Hints**

Step 8's `describe` output has a `Conditions` block with three conditions and a reason for each. Read
all three, not just the first. For the second fault, look at the two numbers the HPA clamps its
result between and ask what values are possible between them.

---

### Exercise 4 - Challenge: expose the results service properly

**Requirements**

A prose brief, and nothing more:

> The Examinations Office wants the results endpoint reachable from the university network at a
> stable address, on a normal HTTP port, on a path of its own, without giving the enrolment endpoint
> the same exposure and without paying for a second load balancer. They also want to know, in
> advance, what it would cost and what would break if the cluster were unavailable.

Design it, implement as much as your build allows, and justify every choice in prose.

**Constraints**

- No second `type: LoadBalancer` Service. The brief rules it out and you must say why in one
  sentence.
- Your answer must state, explicitly, which rung of Step 13's ladder each part of your design sits on.
- Wherever your build cannot demonstrate something, say what would happen on real EKS and name the
  specific object or annotation that would make it happen.
- Include the two things the Examinations Office asked for that are not technical: the cost, and the
  failure mode.

**Expected outcome**

One or two manifests, evidence of whatever routing you could demonstrate, and roughly half a page of
reasoning. Marks are for the design and the honesty about what you could not show, not for the YAML.

**Hints**

Step 16 already routes `/results` somewhere. Ask whether the existing Ingress is the answer, a
starting point, or the wrong shape entirely - all three are defensible positions and the argument is
the exercise. For the cost question, an NLB and an ALB are billed differently, and one Ingress with
five paths is billed once.

---

### Exercise 5 - Integration: the artefacts Lab 10 needs, and the argument this practical was for

**Requirements**

Three parts.

**Part 1 - capture the scaling evidence.** Produce `outputs/lab-08-scaling-evidence.json`: a single
JSON document containing the HPA's spec and status, the Deployment's current replica count, the node
group's scaling configuration (or a stated absence), and a timestamp. It must be valid JSON that
`python3 -m json.tool` accepts.

**Part 2 - verify Lab 10's readiness, from the cluster.** Produce
`outputs/lab-08-lab06-readiness.txt` showing: the ARN of `USMSStudentDataReadWrite`; every role
carrying it; the bucket ARN named in its `Resource` field; whether that bucket exists; and - this is
the new part - **which ServiceAccount in the `usms` namespace would be annotated to use it under
IRSA**, and what that annotation would say.

**Part 3 - write the argument.** Append to `notes/lab-08-notes.md` a section of no more than 400
words titled "ECS or Kubernetes for USMS", making a recommendation and naming the strongest argument
against it. It must cite at least three specific observations from Practicals 2 and 4 - a command
output, a number, or a behaviour you saw - and not one generic claim about either platform.

**Constraints**

- Part 1 must be assembled from live API calls, not typed. If a value is unavailable on your build,
  the JSON must say so explicitly rather than omitting the key.
- Part 2 must read the bucket ARN **out of the policy document**. Typing it means the exercise is not
  done. Lab 07 Exercise 5 did the first half of this; do not copy the answer, re-derive it.
- Part 3 must be your own argument. Two students with opposite recommendations can both score full
  marks; two students with the same three citations cannot.

**Expected outcome**

Two files in `outputs/` (git-ignored - check with `git check-ignore -v`) and a new section in your
notes. Lab 10's first step reads all three.

**Hints**

For Part 1, `kubectl get hpa usms-enrolment-hpa -o json` gives you a document; combining it with the
AWS output is a job for `python3` reading both, or for `jq` if you have it. Either is fine; a shell
heredoc that pastes fragments together is not, because it will not survive an empty value.

For Part 2's new half: Lab 07 Step 21 laid out the six-step IRSA chain and created
`usms-enrolment-sa`. The annotation key is `eks.amazonaws.com/role-arn` and the value is a role ARN -
which role, and why that one rather than `usms-eks-node-role`, is the question.

---

## 14. Lab Assessment Checklist

Tick each item only when you can show the command output that proves it.

**Environment and prerequisites**

- [ ] Floci started with `./scripts/setup/floci-up.sh`; storage mode `hybrid`
- [ ] Five env files sourced, including `configs/lab-07.env`
- [ ] `verify-lab-07.sh` run before starting; result recorded
- [ ] `usms-enrolment`'s CPU request confirmed present **before** building the HPA
- [ ] `_lb_ports_` tag confirmed present, or its absence recorded in the notes
- [ ] Baseline captured to `outputs/lab-08-baseline.txt`

**Scaling**

- [ ] The four dimensions of scaling named, and the "your turn" plan written
- [ ] `kubectl scale` used; no new ReplicaSet observed, and the reason understood
- [ ] Endpoints observed growing only when pods became **ready**, not when they started
- [ ] Configuration drift created deliberately and resolved by `apply`
- [ ] `kubectl diff` used, and its exit code of 1 correctly interpreted
- [ ] QoS classes read off the cluster; the request-versus-limit relationship for each stated
- [ ] The scheduler's allocated-resources table read, and allocatable distinguished from capacity
- [ ] `usms-enrolment-hpa` written as a manifest, `autoscaling/v2`, with a `behavior` block
- [ ] Every `behavior` field mapped to its Lab 06 equivalent
- [ ] The HPA arithmetic worked by hand for at least one case
- [ ] Load generated and the replica count observed moving - **or** `<unknown>` diagnosed, the
      condition quoted verbatim, and the arithmetic done on paper
- [ ] The 300-second scale-in window observed holding capacity, or its effect explained

**Infrastructure and safety**

- [ ] `update-nodegroup-config` run and its Update-object response understood (Path A)
- [ ] Recorded honestly whether a third node appeared
- [ ] Cluster Autoscaler and Karpenter distinguished in one sentence each
- [ ] `nodeSelector` applied, and **enforcement proven** with a deliberately unmatchable value
- [ ] `maxUnavailable: 0` observed protecting the running pods during that failure
- [ ] Both PodDisruptionBudgets created; `ALLOWED DISRUPTIONS` read and explained
- [ ] The eviction API refusing, and `kubectl delete` succeeding, both demonstrated
- [ ] `manifests/lab-07/20-enrolment.yaml` updated so the repository matches the cluster

**Exposure**

- [ ] ClusterIP shown to be unroutable from the host
- [ ] `port-forward` used, and its two disqualifying properties stated
- [ ] `usms-results-np` created as a **second** Service on the **same** pods
- [ ] Every node shown answering on 30080, including one with no pods
- [ ] `usms-gateway` promoted to `LoadBalancer` by re-applying a full manifest, not a patch
- [ ] The three AWS annotations read and explained, especially `nlb-target-type: ip`
- [ ] `type`, `clusterIP`, `nodePort` and external address shown on one line
- [ ] `usms-portal-ingress` created with three prefix paths
- [ ] Longest-prefix matching distinguished from Lab 05's numeric rule priority
- [ ] Each `alb.ingress.kubernetes.io` annotation mapped to a Lab 05 `elbv2` command

**Verification, persistence and hygiene**

- [ ] `verify-lab-08.sh` written and run; result recorded, including expected Path B failures
- [ ] Floci stopped and started; HPA, PDBs, Services and Ingress read back
- [ ] `PERSISTENCE PROVEN` recorded, or every difference explained
- [ ] `configs/lab-08.env` generated, 19 exports
- [ ] `git status --short` inspected before `git add`; nothing under `outputs/` staged
- [ ] `git check-ignore -v` run and the rule it named recorded
- [ ] `scripts/cleanup/lab-08-cleanup.sh` written, syntax-checked, **not run**

**Understanding**

- [ ] Section 15 answered in prose in `notes/lab-08-notes.md`
- [ ] Step 17's two comparison tables filled in with both systems running
- [ ] Five exercises attempted; Exercise 5's two `outputs/` files present
- [ ] `usms-loadgen` deleted at the end (Section 16)

---

## 15. Review Questions

Answer in prose in `notes/lab-08-notes.md`. No command output - these ask what you understood.

**1.** A colleague sets `averageUtilization: 50` on an HPA and reports that "the pods scale when the
node hits 50% CPU". Correct them precisely. Then explain what happens to that HPA's behaviour if
somebody halves the container's CPU request without changing the HPA, and say whether the workload
ends up with more capacity or less.

**2.** `usms-enrolment` needs to handle ten times its current traffic by next Monday. Using Step 3's
four dimensions, give an ordered plan, say what you would check between each step, and name the one
dimension that cannot be changed in place and what you would have to do instead.

**3.** Lab 06's Application Auto Scaling and this lab's HorizontalPodAutoscaler both write a single
integer. Describe two consequences of the fact that one runs outside your workload and the other runs
inside your cluster. At least one must be about what happens when something is broken.

**4.** The HPA raises `replicas` from 4 to 8 and four pods sit in `Pending` for twenty minutes.
Explain what has happened using the two-control-loops picture from Section 6, name the component that
would normally resolve it, and say why lowering the CPU request is a bad way to make the pods fit.

**5.** Students routinely conflate a **NodePort** with a **LoadBalancer**, and separately conflate a
**Service** with an **Ingress**. Take one pair. Explain the distinction, then describe a concrete
requirement that the wrong choice would fail to meet and the right one would satisfy.

**6.** Step 16's Ingress routes `/enrolment` straight to `usms-enrolment`, bypassing `usms-gateway`,
which also serves that path. Both routes now exist. Argue for one of them as the design USMS should
keep, and say what you would delete. Your answer must address what the gateway does that the Ingress
rule does not.

**7.** A PodDisruptionBudget with `minAvailable: 1` did not stop `kubectl delete pod`. Explain why
that is correct behaviour and not a bug, distinguish voluntary from involuntary disruption, and give
one realistic scenario in which the PDB you wrote would genuinely save a production service.

---

## 16. What We Built

### 16.1 Reflection

Both halves of this lab turned out to be ladders, and both ladders end with something whose whole
purpose is to hide the rungs below it. An HPA hides the fact that scaling is one integer. An Ingress
hides the fact that reaching a pod is still a ClusterIP, still a nodePort, still kube-proxy. The
reason to climb them one rung at a time - rather than starting at the top, which would have been
faster - is that when the top rung misbehaves, the diagnosis is always somewhere below it. An Ingress
with no address is not an Ingress problem. An HPA that will not scale is usually a resource-request
problem or a capacity problem.

Step 9 is the moment worth remembering. Load arrived, a percentage crossed 50, an integer changed, and
pods appeared - and then load stopped, the percentage collapsed, **and nothing happened for five
minutes**. That five minutes of apparent inaction is the single most deliberate piece of engineering
in this laboratory. It exists because the cost of removing capacity you still need is an outage and
the cost of keeping capacity you no longer need is small change. Lab 06 encoded the same asymmetry as
`ScaleInCooldown: 300`. Two platforms, one doctrine, and the doctrine is the part that transfers.

And Step 16 is the moment Practical 2 and Practical 4 stop being two topics. The annotations on that
Ingress - `target-type: ip`, `scheme: internet-facing`, `listen-ports`, `healthcheck-path` - are, one
for one, the arguments you typed into `aws elbv2` commands four weeks ago. The AWS Load Balancer
Controller does not invent anything. It reads a Kubernetes object and makes the same four calls you
made by hand. What Kubernetes gave you is not a different load balancer; it is a way of asking for the
one you already knew how to build, in a form that also works somewhere else.

### 16.2 KEEP and CLEAN UP

```text
╔══════════════════ KEEP ══════════════════╗    ╔═══════════ CLEAN UP ═══════════╗
║ usms-eks-cluster and usms-eks-nodes      ║    ║ usms-loadgen        Deployment ║
║ namespace usms and all three services    ║    ║ usms-reports + hpa  Exercise 3 ║
║ usms-enrolment-hpa                       ║    ║ any usms-debug pod left over   ║
║ usms-gateway-pdb, usms-enrolment-pdb     ║    ║ manifests/*.bak     sed -i.bak ║
║ usms-results-np  (NodePort 30080)        ║    ║ a cordoned node, if you drained║
║ usms-gateway as type LoadBalancer        ║    ╚════════════════════════════════╝
║ usms-portal-ingress                      ║
║ nodeSelector workload=usms               ║
║ configs/lab-07.env, configs/lab-08.env ║
║ everything from Labs 01, 02, 03, 04-C   ║
╚══════════════════════════════════════════╝
```

Clean up now:

```bash
kubectl delete deployment usms-loadgen --ignore-not-found
kubectl delete deployment,hpa usms-reports usms-reports-hpa --ignore-not-found 2>/dev/null
kubectl delete pod -l run=usms-debug --ignore-not-found 2>/dev/null
rm -f manifests/lab-07/*.bak manifests/lab-08/*.bak

kubectl get nodes | grep -i cordon && echo "a node is cordoned - uncordon it" || echo "no cordoned nodes"
kubectl get all
```

**What to look for:** five pods - two enrolment, two results, one gateway - plus whatever Exercise 1
and Exercise 2 left. No `usms-loadgen`. No cordoned nodes.

!!! danger "Read before running any delete command"
    **What will be deleted:** the load generator Deployment, Exercise 3's practice objects, and any
    leftover debug pods.
    **What depends on them:** nothing. Every one of them was created in this lab as a temporary
    instrument.
    **Reversible?** Yes - `usms-loadgen` is in `manifests/lab-08/20-loadgen.yaml` and can be
    re-applied at any time.
    **Effect on later labs:** none.

Do **not** run `scripts/cleanup/lab-08-cleanup.sh`, `lab-07-cleanup.sh`, `lab-04-cleanup.sh`,
`lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are for the end of the course, and Section 9.3 gives
the order.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Labs 02, 04 and 07
  usms-ec2-app-role + usms-ec2-app-profile   on usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 07
  usms-eks-cluster-role -> USMSEKSClusterPolicy
  usms-eks-node-role    -> USMSEKSNodePolicy
  USMSStudentDataReadWrite ............. on THREE roles, naming a bucket that still
                                         does not exist. Lab 10 changes that

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b   -> igw
                 ^ where a real EKS internet-facing load balancer would live,
                   exactly as Lab 05's ALB did
    private : usms-private-subnet-a / -b  -> nat, s3 endpoint
                 ^ usms-eks-nodes
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg,
               usms-private-nacl, usms-eks-cluster-sg

Lab 03  COMPUTE - instances you administer
  usms-web-01, usms-db-01, usms-web-golden

Lab 06   CONTAINERS, the ECS way - still running, not replaced
  usms-ecs-cluster / usms-enrolment-svc / usms-enrolment:2
  usms-enrolment-alb -> usms-enrolment-tg (target-type ip) -> tasks
  scalable target min 2 max 10; CPU and request-count target tracking;
    one step policy; two scheduled actions
  /usms/ecs/enrolment  retention 7 days

Lab 07  CONTAINERS, the Kubernetes way
  usms-eks-cluster  k8s 1.30, 4 subnets, tag _lb_ports_=8081,8082
    usms-eks-nodes  private-a + private-b, labels workload=usms tier=app
  namespace usms
    usms-gateway    1 replica, nginx proxy, routes by DNS name
    usms-enrolment  requests cpu=50m mem=32Mi, maxUnavailable 0, probes on /healthz
    usms-results    default strategy 25%/25%
    4 ConfigMaps, 1 Secret, ServiceAccount usms-enrolment-sa

Lab 08  SCALING AND EXPOSURE                              <-- you are here
  SCALING
    usms-enrolment-hpa    autoscaling/v2   min 2  max 8   cpu 50% of the 50m request
      scaleUp    window 0s,   Percent 100 / Pods 2 per 15s,  selectPolicy Max
      scaleDown  window 300s, Pods 1 per 60s,                selectPolicy Min
      observed: 2 -> 4 under load, held for 300s, back to 2
    usms-eks-nodes        min 2  max 6  desired 3   (recorded; no node appeared locally)
    nodeSelector workload=usms on usms-enrolment, enforcement proven
    Cluster Autoscaler / Karpenter: named, compared, NOT installed, and why
  SAFETY
    usms-gateway-pdb      minAvailable 1    -> ALLOWED DISRUPTIONS 0, and why that is honest
    usms-enrolment-pdb    maxUnavailable 1  -> ALLOWED DISRUPTIONS 1
  EXPOSURE
    ClusterIP        the three Lab 07 Services, unroutable from the host
    port-forward     a tunnel through the API server, one pod, debugging only
    usms-results-np  NodePort 80:30080, pinned, answering on every node
    usms-gateway     LoadBalancer + clusterIP + nodePort, annotated for an NLB with
                     target-type ip in the public subnets
    usms-portal-ingress   / -> gateway, /enrolment -> enrolment, /results -> results
                     annotated for an ALB: scheme, target-type, listen-ports,
                     healthcheck-path, tags - one per Lab 05 elbv2 call
  and NOTHING from Lab 07 was replaced: same cluster, same images, same ConfigMaps

Lab 09  SECURITY
  least-privilege review of the IAM and security-group estate built so far

Lab 10  Lambda
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for
                        three roles at once, and whose first object is this lab's
                        Exercise 5. Lambda creates it inline; there is no separate
                        storage lab
  then DynamoDB · RDS · SNS/SQS · CloudWatch · CloudFormation
  the CloudWatch lab reads /usms/ecs/enrolment, USMS/Enrolment and Lab 06's alarms
  the CloudFormation lab re-declares Practical 2 and Practical 4 as one template
```

---

## 17. Preparation for the Next Lab

Lab 10 - S3 - creates `usms-student-data`, and it is the moment a policy written in the first
laboratory of this course stops being hypothetical for the **third** role at once. It needs nothing
from the scaling or exposure configuration you just built, and it needs two things from your
repository.

| From this lab | Lab 10 uses it for |
| --- | --- |
| `outputs/lab-08-scaling-evidence.json` (Exercise 5) | Its first `put-object` needs a real file with real content. This is one, and it is one you generated rather than typed |
| `outputs/lab-08-lab06-readiness.txt` (Exercise 5) | The bucket ARN read out of Lab 01's policy document, the three roles carrying it, and the ServiceAccount that would use it under IRSA |

| From earlier labs | Lab 10 uses it for |
| --- | --- |
| Lab 01 `USMSStudentDataReadWrite` | The policy whose `Resource` names the bucket. Lab 10 creates the bucket the policy already describes, in that order, deliberately |
| Lab 01 `usms-ec2-app-role` | Holder one - an EC2 instance profile, since Lab 03 |
| Lab 04 `usms-ecs-task-role` | Holder two - a Fargate task role, since Practical 2 |
| Lab 07 `usms-eks-node-role` | Holder three - an EKS node role, since Lab 07 Step 7 |
| Lab 02 `usms-s3-endpoint` | The gateway endpoint that has been on the private route table since Lab 2 and has had nothing to reach |
| Lab 07 `usms-enrolment-sa` | The ServiceAccount that, on real EKS, would carry the IRSA annotation instead of relying on the node role |

**The connection to state out loud before the next session.** Lab 01 wrote a policy for a bucket that
did not exist. Lab 03 attached it to a virtual machine. Lab 04 attached it, unchanged, to a
serverless container. Lab 07 attached it, unchanged again, to a Kubernetes node. Lab 02 built a VPC
endpoint whose only purpose is to reach S3 privately, and it has been sitting on the private route
table doing nothing for five laboratories.

**Five laboratories have prepared for one `create-bucket` call**, and when Lab 10 makes it, four
separate chains resolve at the same instant and not one of them has to be modified. That is worth more
than any single command in this course.

**Before the next session, confirm all six of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-07.sh | tail -2
./scripts/utilities/verify-lab-08.sh | tail -2
grep -c '^export' configs/lab-08.env
kubectl get hpa,pdb,ingress -n usms
kubectl get deploy -n usms -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas'
aws iam list-entities-for-policy \
  --policy-arn "$(aws iam list-policies --scope Local \
    --query "Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]" --output text)" \
  --query 'PolicyRoles[].RoleName' --output text
```

You want: `FAIL=0` from the first on Path A or `FAIL=3` on Path B; `FAIL=0` from the second on Path A
or `FAIL=2` on Path B; a count of **19**; one HPA, two PDBs and one Ingress; three Deployments reading
at least `2`, `2` and `1`; and - from the last command - **three role names**.

That last one is the one to care about. If it lists fewer than three, one of the attachments from Lab
03, Lab 04 or Lab 07 is missing, and Lab 10's central demonstration loses a third of its force. It
is a one-command fix today.

**Read ahead, five minutes:** find out what an S3 **bucket policy** is and how it differs from the
identity policy you have been attaching to roles since Lab 1. Lab 10 assumes neither, but the
distinction is the axis the whole laboratory turns on, and it moves considerably faster if the words
are not new.

Finally, take a snapshot so that a mistake in Lab 10 is recoverable:

```bash
floci snapshot save lab-08-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-08.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

---

## Appendix A - Command Reference

**Environment**

| Command | Purpose |
| --- | --- |
| `./scripts/setup/floci-up.sh` / `floci-down.sh` | Start and stop Floci. The only supported way |
| `./scripts/utilities/whoami.sh` | Identity and endpoint; exits 1 on the wrong account |
| `./scripts/utilities/floci-storage-check.sh` | Six read-only checks that name a persistence failure |
| `./scripts/utilities/verify-lab-07.sh` | Lab 07's 30 checks - run it before this lab |
| `./scripts/utilities/verify-lab-08.sh` | This lab's 34 checks |
| `./scripts/utilities/hpa-watch.sh [n]` | Poll the HPA and its Deployment every 10 seconds |

**Scaling**

| Command | Purpose |
| --- | --- |
| `kubectl scale deployment/X --replicas=N` | Write `spec.replicas`. No new ReplicaSet |
| `kubectl set resources deployment/X --requests=... --limits=...` | Change dimension 2. Restarts the pods |
| `kubectl get hpa` | The one-line summary: current/target, bounds, replicas |
| `kubectl describe hpa X` | `Conditions` and `Events` - where the HPA explains itself |
| `kubectl top nodes` / `kubectl top pods` | The metrics API, read by you. Same source the HPA uses |
| `kubectl get --raw /apis/metrics.k8s.io/v1beta1` | Is the metrics API registered at all? |
| `aws eks update-nodegroup-config --scaling-config min=,max=,desired=` | Dimension 3, from the AWS side |
| `aws eks list-updates` / `describe-update` | EKS's asynchronous update objects |
| `kubectl get pdb` | `ALLOWED DISRUPTIONS` - the column that matters |
| `kubectl drain <node> --ignore-daemonsets --dry-run=client` | What a drain would attempt |
| `kubectl uncordon <node>` | Undo the schedulability half of a drain |

**Exposure**

| Command | Purpose |
| --- | --- |
| `kubectl get svc -o wide` | Type, ClusterIP, external address, ports and selector |
| `kubectl get endpoints <svc>` | Which pods is this Service actually using? |
| `kubectl port-forward svc/X 8080:80` | A tunnel through the API server. Debugging only |
| `kubectl get ingress` / `describe ingress X` | Class, address, rules and the backend for each |
| `kubectl get ingressclass` | Is any controller claiming Ingress objects? |
| `kubectl create --raw <path> -f <file>` | POST an arbitrary body to an arbitrary API path |

**General**

| Command | Purpose |
| --- | --- |
| `kubectl apply -f <file or dir>` | Declarative create-or-update |
| `kubectl diff -f <file>` | What would change. Exits 1 on a difference - a feature |
| `kubectl apply --dry-run=client -f <dir>` | Validate without a cluster. Path C's whole toolkit |
| `kubectl patch X --type=merge -p '<json>'` | A quick change - and a source of drift. Prefer `apply` |
| `kubectl get X -o custom-columns='A:.path,B:.path'` | Exactly the table you want |
| `kubectl get nodes -L label1,label2` | One column per named label. Better than `--show-labels` |
| `kubectl config set-context --current --namespace=usms` | Stop typing `-n usms` |

---

## Appendix B - New JMESPath, `kubectl` and CLI patterns introduced

**`kubectl`**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `kubectl diff -f` | Render the post-apply state and diff it. Exit 1 means "there is a difference" | Steps 5, 11 |
| `-L label1,label2` | One column per named label | Step 11 |
| `--type=merge -p '<json>'` | A strategic-merge patch inline. Fast, and it creates drift | Steps 11, 12 |
| `kubectl create --raw <path> -f <file>` | POST to an API path directly - the only way to reach a subresource such as `eviction` | Step 12 |
| `kubectl get svc -w` | Watch one object change. How you see `<pending>` become an address | Step 15 |
| `-o jsonpath` with literal text and `{"\n"}` | Build a one-line report from several fields | Step 15 |
| `--request-timeout=10s` | Bound a call so a script cannot hang forever | Section 9 |
| `--dry-run=client -f <dir>` | Validate a whole directory of manifests with no cluster | Section 9, 8.5 |

**Kubernetes objects and fields**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `autoscaling/v2` `behavior` | Rate limits and stabilisation windows. `v1` has none of it | Step 8 |
| `selectPolicy: Max` / `Min` | Which of several policies wins. `Max` accelerates, `Min` restrains | Step 8 |
| `stabilizationWindowSeconds` | Use the most conservative recommendation from the last N seconds | Step 8 |
| `nodeSelector` | The simplest scheduling constraint. Hard, not advisory | Step 11 |
| `policy/v1` `PodDisruptionBudget` | `minAvailable` for a fixed floor; `maxUnavailable` when the count moves | Step 12 |
| `nodePort: 30080` | Pin the port. Predictable, and it can collide | Step 14 |
| `service.beta.kubernetes.io/aws-load-balancer-*` | Cloud-specific configuration outside the portable `spec` | Step 15 |
| `alb.ingress.kubernetes.io/*` | One annotation per Lab 05 `elbv2` argument | Step 16 |
| `pathType: Prefix` | Whole-segment prefix match. Longest match wins, not first | Step 16 |

**Shell and YAML**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `<< 'EOF'` quoted heredoc | No expansion. **Every Kubernetes manifest** | Steps 8, 9, 12, 14, 15, 16 |
| `<< EOF` unquoted heredoc | Expand now. **`configs/lab-NN.env` and the eviction body** | Steps 12, 19 |
| YAML `>` folded block scalar | Fold the following lines into one, joined by spaces. Keep the semicolons | Step 9 |
| `cmd \|\| true` | Stop a deliberate non-zero exit from killing a `set -e` shell | Step 5 |
| `diff <(...) <(...)` | Process substitution: compare two command outputs without temporary files | Step 18 |
| `tee` | Write to a file and to the screen | Steps 2, 10, 18 |

---

## Sources

- Kubernetes documentation - HorizontalPodAutoscaler, the `autoscaling/v2` API and scaling policies:
  [kubernetes.io - horizontal pod autoscale](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- Kubernetes documentation - Services, publishing services and Ingress:
  [kubernetes.io - service](https://kubernetes.io/docs/concepts/services-networking/service/) and
  [kubernetes.io - ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- Kubernetes documentation - disruptions, PodDisruptionBudget and the eviction API:
  [kubernetes.io - disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)
- Kubernetes documentation - resource requests, limits and QoS classes:
  [kubernetes.io - manage resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
- metrics-server, the source of `kubectl top` and the HPA's resource metrics:
  [github.com/kubernetes-sigs/metrics-server](https://github.com/kubernetes-sigs/metrics-server)
- Amazon EKS User Guide - managed node groups, node group updates, and load balancing:
  [docs.aws.amazon.com/eks](https://docs.aws.amazon.com/eks/latest/userguide/managed-node-groups.html)
- AWS Load Balancer Controller - Ingress annotations and the ALB it creates:
  [kubernetes-sigs.github.io/aws-load-balancer-controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- Karpenter, and the Kubernetes Cluster Autoscaler, for Step 11's comparison:
  [karpenter.sh](https://karpenter.sh/) and
  [github.com/kubernetes/autoscaler](https://github.com/kubernetes/autoscaler/tree/master/cluster-autoscaler)
- LocalStack EKS provider - k3d-backed clusters, the `_lb_ports_` tag, node groups and known
  limitations, which is the emulator behaviour this course calls Floci:
  [docs.localstack.cloud - EKS](https://docs.localstack.cloud/aws/services/eks/)

*Compiled for DSO303, Royal Thimphu College / CST, RUB. Laboratory content verified against the
Kubernetes and AWS documentation and Floci's documented EKS behaviour; output shown in this document
is illustrative and labelled as such throughout.*
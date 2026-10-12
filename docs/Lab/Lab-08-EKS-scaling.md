# Lab 08 - EKS Scaling and Service Exposure

## 1. Objectives

- Scale a Deployment by hand, by manifest and with an `autoscaling/v2` HorizontalPodAutoscaler, and map the HPA to Lab 6's Application Auto Scaling.
- Change the managed node group's scaling configuration from the AWS side, and explain why that is a separate control loop.
- Use requests, QoS classes, a `nodeSelector` and PodDisruptionBudgets, and say what each does and does not protect.
- Climb the exposure ladder: `port-forward`, `NodePort`, `LoadBalancer`, `Ingress`, and compare Ingress with Lab 5's ALB.
- Prove the scaling and exposure configuration survives a restart, and save it to `configs/lab-08.env`.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane) ·
    [Service types and kube-proxy](../unit3/topic1.md#services-coredns-and-kube-proxy) ·
    [AWS Load Balancer Controller](../unit3/topic1.md#the-aws-load-balancer-controller) ·
    [requests and limits](../unit3/topic2.md#requests-and-limits) ·
    [probes](../unit3/topic2.md#probes) ·
    [managed node groups, drains, PDBs and Karpenter](../unit3/topic3.md#eks-managed-node-groups) ·
    [Application Auto Scaling on ECS](../unit2/topic3.md#application-auto-scaling-on-ecs) ·
    [the two scaling layers](../unit2/topic3.md#the-two-scaling-layers-revisited) ·
    [Kubernetes HorizontalPodAutoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)

---

## 2. Prerequisites

- Lab 7 complete: `configs/lab-07.env` populated and `verify-lab-07.sh` at `FAIL=0` (support Path A) or `FAIL=3` (Path B).
- Labs 5 and 6 complete; Steps 15 to 17 compare against them.
- `usms-enrolment` declares a CPU request (Lab 7 Step 13 set `50m`) and the cluster carries the `_lb_ports_=8081,8082` tag (Lab 7 Step 8). Step 1 checks both.
- Tools as in Lab 7: `kubectl` (everything), AWS CLI v2 (Step 10 only); `watch` and `curl` are optional.

Your Lab 7 support path still applies:

| Path | This lab |
| --- | --- |
| **A** | Everything. Step 10 is the only step that needs the `eks` API |
| **B** | Everything except Step 10. The Kubernetes half - which is most of this lab - is unaffected |
| **C** | The Path C paper route at the end of Section 7 |

```bash
kubectl version --client
aws --version
```

If Step 1 finds the CPU request missing, fix it there before going further; the HPA cannot work without it.

---

## 3. What This Lab Reuses

From Lab 7:

- `usms-enrolment` CPU request `50m`: the HPA's denominator (Step 8).
- `_lb_ports_=8081,8082` cluster tag: host ports for the LoadBalancer Service (Step 15).
- Node group labels `workload=usms`: the `nodeSelector` (Step 11).
- `usms-gateway` Service: the whole exposure ladder is climbed on it (Steps 13 to 16).

From Labs 5 and 6:

- `usms-enrolment-tg` with target type `ip`: the Ingress comparison (Step 16).
- Lab 6's scalable target: the HPA comparison (Steps 8 and 17).

```text
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

---

## 4. What We Are Building

Lab 7's three microservices are healthy but unreachable from outside the cluster and fixed in size. This lab climbs two ladders, each rung adding one thing to the rung below. Scaling is always one integer (`replicas` here, `desiredCount` in Lab 6); what changes is who writes it.

```text
Step 4   kubectl scale                 you write the integer
Step 5   replicas: in the manifest     Git writes the integer
Step 8   HorizontalPodAutoscaler       a controller inside the cluster writes the integer
Step 10  update-nodegroup-config       you write a DIFFERENT integer, on the AWS side
Step 11  Cluster Autoscaler/Karpenter  a controller writes that one too   (conceptual)
```

```text
Step 13  ClusterIP + port-forward   reachable by you, over the API server, for debugging only
Step 14  NodePort                   reachable on a fixed high port on every node
Step 15  LoadBalancer               reachable on one address; on AWS, a real NLB appears
Step 16  Ingress                    ONE address for MANY services, routed by path
```

Steps 6, 7 and 12 add resource requests and QoS classes, the metrics pipeline and a PodDisruptionBudget. Nothing from Lab 7 is replaced.

---

## 5. Architecture

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
  |     the load source. Deleted in Section 15                                        |
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

## 6. Directory Structure

This lab adds the following. It creates no new folder - Lab 07's `manifests/` is the home for all of
it.

```text
aws-floci-course/
├── labs/
│   └── lab-08-eks-scaling/
│       ├── README.md                          # this document
│       └── exercises.md                       # Section 12
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
│   │   ├── verify-lab-08.sh                  # NEW - Section 8
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

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    Unless a step says otherwise. Lab 7 set your `kubectl` context's default namespace to `usms`, so `-n usms` is omitted below. If a command reports `No resources found in default namespace`, re-run:

    ```bash
    kubectl config set-context --current --namespace=usms
    ```

!!! tip "Shell variables die with the terminal"
    Step 19 writes this lab's values to `configs/lab-08.env`.

### Step 1 - Start the environment, and check the two things Lab 07 had to leave behind

Two Lab 7 values decide whether this lab can work at all: the CPU request (Step 8's denominator) and the `_lb_ports_` tag (Step 15's host ports).

**Part 1 - start and source**

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

**Part 2 - the two checks that matter**

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

If a check is wrong:

- **No `cpu` request.** Fix it now; no later step can work around it:

    ```bash
    kubectl set resources deployment/usms-enrolment \
      --requests=cpu=50m,memory=32Mi --limits=cpu=200m,memory=128Mi
    kubectl rollout status deployment/usms-enrolment --timeout=120s
    ```

    Then fix `manifests/lab-07/20-enrolment.yaml` too, so the repository and the cluster agree.

- **`None` for the tag on Path A.** Try `aws eks tag-resource` as Lab 7 Step 9 showed. If that fails, Step 15 becomes Conceptual for you; record that in `notes/lab-08-notes.md` now.
- **`eks API unavailable` on Path B.** Expected. Steps 10 and 15's AWS half are unavailable; everything else works.

**Verify**

```bash
./scripts/utilities/verify-lab-07.sh | tail -3
kubectl get deploy,svc,cm,secret
```

`FAIL=0` (Path A) or `FAIL=3` (Path B); three Deployments at `2`, `2` and `1`; three ClusterIP Services with no external address; four ConfigMaps; one Secret.

---

### Step 2 - Read your own baseline before you change anything

Every later number needs something to compare against. This reads back Lab 7 Exercise 5 and captures a fresh "before" snapshot.

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

The narrow `custom-columns` output can be diffed later (Step 18). The empty `EXTERNAL` column is recorded on purpose: after Step 15 it fills in.

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

Three Deployments at their Lab 7 counts, every Service `ClusterIP` with `<none>` external, at least one node `Ready`. Local nodes report your whole machine's cores, so Step 9 targets the pod's request, not node capacity.

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

Nothing to run. Know which of four independent things you are moving before you move any of them.

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

- **Dimension 1 without dimension 3 gives `Pending` pods.** The HPA adds replicas; if the nodes are full, that is all it does.
- **Dimension 2 is the HPA's denominator.** Step 6 covers this coupling.
- **Dimension 4 cannot be done in place:** create a second node group, cordon and drain the first, delete it.

ECS on Fargate has dimensions 1 and 2 only; there are no nodes. That is the operational difference between the two platforms.

✏️ **Your turn**

In `notes/lab-08-notes.md`, answer in three or four sentences: *`usms-enrolment` needs to handle ten
times its current traffic. Walk through the four dimensions and say which you would use, in which
order, and what you would check between each.*

```text
Expected result:
A short ordered plan. There is no single right answer, but a plan that reaches
for dimension 4 first, or that never mentions dimension 3 at all, is wrong.
Section 14 Question 2 asks a harder version of this.
```

---

### Step 4 - Scale by hand, and watch what moves

The simplest rung. Everything the HPA does in Step 8, it does by performing this operation.

**Part 1 - open a watcher in a second terminal**

```bash
kubectl get pods -w -l app=usms-enrolment
```

**Part 2 - scale up** (in your first terminal)

```bash
kubectl scale deployment/usms-enrolment --replicas=5
kubectl rollout status deployment/usms-enrolment --timeout=120s

kubectl get deploy usms-enrolment
kubectl get endpoints usms-enrolment
```

- `kubectl scale` writes only `spec.replicas`. The pod template is unchanged, so the existing ReplicaSet is scaled; no rollout happens.
- Endpoints grow only as each pod becomes **ready** (Lab 7 Step 13's readiness probe), not when it starts.

**Expected result**

```text
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
usms-enrolment   5/5     5            5           3h

NAME             ENDPOINTS                                                       AGE
usms-enrolment   10.42.1.8:80,10.42.1.11:80,10.42.2.5:80 + 2 more...             3h
```

> Example output - addresses differ, and `kubectl` abbreviates long endpoint lists.

**Part 3 - confirm the traffic really spreads across five**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  for i in $(seq 1 40); do
    wget -qO- http://usms-gateway.usms.svc.cluster.local/enrolment/
  done
' | grep -o '"pod":"[^"]*"' | sort | uniq -c | sort -rn
```

Four or five distinct pod names is a pass. The gateway was not restarted or reconfigured; it still holds one ClusterIP.

**Part 4 - scale back down**

```bash
kubectl scale deployment/usms-enrolment --replicas=2
kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get endpoints usms-enrolment
```

Pods leave the endpoint list **first**, then get `SIGTERM` and 30 seconds' grace before `SIGKILL`: the Kubernetes equivalent of Lab 5's 30-second deregistration delay. Stop the watcher with ++ctrl+c++.

---

### Step 5 - Scale declaratively, and meet configuration drift

Step 4 changed the cluster but not the repository. This step shows the cost, and is why the rest of the lab uses manifests rather than `kubectl patch`.

**Part 1 - create the drift deliberately**

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

The cluster says 6, the repository says 2, and nothing tells you.

**Part 2 - watch `apply` silently undo your scaling**

```bash
kubectl apply -f manifests/lab-07/20-enrolment.yaml
sleep 5
kubectl get deploy usms-enrolment -o jsonpath='{.spec.replicas}'; echo
```

**Expected result**

```text
2
```

!!! warning "This is the single most common way a Kubernetes deployment causes an outage"
    Someone applies an unrelated change to the file and your capacity disappears. Three answers:

    - **Never scale by hand.** Change `replicas:` in the file, commit it, apply it.
    - **Let the HPA own the field.** Step 8 does this.
    - **Use `kubectl diff` before every `apply`.**

**Part 3 - the habit that prevents it**

```bash
sed -i.bak 's/^  replicas: 2$/  replicas: 3/' manifests/lab-07/20-enrolment.yaml

kubectl diff -f manifests/lab-07/20-enrolment.yaml || true

kubectl apply -f manifests/lab-07/20-enrolment.yaml
kubectl get deploy usms-enrolment -o jsonpath='{.spec.replicas}'; echo
```

`kubectl diff` exits **1** when there is a difference. That is not an error; `|| true` stops it killing a `set -e` shell.

**Part 4 - restore the baseline**

```bash
sed -i.bak 's/^  replicas: 3$/  replicas: 2/' manifests/lab-07/20-enrolment.yaml
kubectl apply -f manifests/lab-07/20-enrolment.yaml
kubectl rollout status deployment/usms-enrolment --timeout=120s
rm -f manifests/lab-07/*.bak
kubectl get deploy
```

`usms-enrolment` back at `2/2`, and no `.bak` files left behind.

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

Step 8's autoscaler divides by the request set here, and Step 12's disruption behaviour depends on the QoS class. See [requests and limits](../unit3/topic2.md#requests-and-limits).

```text
requests   what the SCHEDULER reserves. A node with 1000m allocatable can hold
           20 pods requesting 50m each, whatever they actually use
limits     what the KUBELET enforces at runtime
             CPU over limit    -> THROTTLED. The pod slows down
             MEMORY over limit -> OOMKilled. The container is killed and restarted
```

| Class | When | What it means under pressure |
| --- | --- | --- |
| `Guaranteed` | every container has requests **equal to** limits, for both CPU and memory | Evicted last |
| `Burstable` | requests are set, and are less than limits | Evicted after `BestEffort` |
| `BestEffort` | nothing set at all | **Evicted first**, and invisible to the HPA |

Lab 7's containers request `50m`/`32Mi` and limit `200m`/`128Mi`, so all three are `Burstable`. `BestEffort` pods have no request, so an HPA cannot compute a percentage for them.

**Part 1 - read the classes off the cluster**

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

**Part 2 - see the scheduler's arithmetic**

```bash
NODE=$(kubectl get pods -l app=usms-enrolment -o jsonpath='{.items[0].spec.nodeName}')
echo "inspecting node: $NODE"
kubectl describe node "$NODE" | sed -n '/Allocated resources/,/Events/p'
```

The percentages are of **allocatable**, not capacity: a node reserves CPU and memory for the kubelet and system.

**Part 3 - prove the denominator arithmetic before you rely on it**

```bash
REQ=$(kubectl get deploy usms-enrolment \
  -o jsonpath='{.spec.template.spec.containers[0].resources.requests.cpu}')
echo "request        : $REQ"
echo "HPA target 50% : this means 50% of $REQ per pod, i.e. 25m average across all pods"
echo "NOT 50% of a node, and NOT 50% of the limit"
```

The target is a percentage of the request, so a pod using `30m` of a `50m` request is at 60% and the HPA scales out.

✏️ **Your turn**

Make `usms-gateway` a `Guaranteed` pod without changing what it can do, then put it back. Record the
QoS class before and after, and one sentence on when you would actually want `Guaranteed`.

```text
Expected result:
QOS goes Burstable -> Guaranteed -> Burstable, and the pod is replaced each time.

Note that it was REPLACED, not adjusted. Say why in your notes - it is dimension 2
from Step 3, and it is the reason VerticalPodAutoscaler is used far less than HPA.
```

Hint: `kubectl set resources` takes both `--requests` and `--limits`; the QoS table says which relationship gives each class.

---

### Step 7 - The metrics pipeline, and why it is an add-on

The HPA reads a metric from `metrics.k8s.io`, which is not part of core Kubernetes and may not be installed. Find out which situation you are in first.

!!! info "The metrics pipeline in brief"
    kubelets expose per-container CPU and memory; metrics-server scrapes them and registers the `metrics.k8s.io` API; `kubectl top` and the HPA both read that API. So **if `kubectl top` works, the HPA has data**. It gives CPU and memory only; scaling on requests or queue depth (as Lab 6 did) needs a separate adapter (Section 11).

**Part 1 - is the API registered?**

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

> Example output. `metrics API: NOT AVAILABLE` is common; Part 2 deals with it.

**Part 2 - only if Part 1 said NOT AVAILABLE**

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s
```

If the pod never becomes ready and its logs mention `x509`, local kubelets have self-signed certificates. The local-only fix:

```bash
kubectl -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl -n kube-system rollout status deployment/metrics-server --timeout=120s
```

!!! warning "`--kubelet-insecure-tls` is a laboratory-only flag"
    It skips verification of the kubelet's certificate, so anything impersonating a kubelet can feed the autoscaler invented metrics. Real EKS never needs it. Record in your notes that you used it.

**Part 3 - if the cluster has no network access**

The `apply` above needs the nodes to reach GitHub. If they cannot, the HPA will exist but never compute; record it and use Step 9's fallback.

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

Each pod at roughly `1m` idle, 2% of the `50m` request. Write the idle figure down for Step 9.

---

### Step 8 - Create the HorizontalPodAutoscaler

The object the scaling half of the lab is for, and the closest match to Lab 6.

Every 15 seconds the HPA controller:

```text
1. reads the current metric for every ready pod of the target Deployment
2. computes    currentUtilisation = mean(usage) / request      as a percentage
3. computes    desiredReplicas = ceil( currentReplicas * currentUtilisation / targetUtilisation )
4. clamps it between minReplicas and maxReplicas
5. applies the behavior policies (rate limits and stabilisation windows)
6. writes the result to the Deployment's spec.replicas -- and does nothing else
```

Worked example: two pods at `40m`, request `50m`, target 50%:

```text
currentUtilisation = 40 / 50            = 80%
desiredReplicas    = ceil(2 * 80 / 50)  = ceil(3.2) = 4
```

Field by field against Lab 6:

| Lab 06, Application Auto Scaling | Here | Note |
| --- | --- | --- |
| `RegisterScalableTarget` on `service/cluster/service` | `spec.scaleTargetRef` | There the resource ID was a constructed string; here it is a typed reference |
| `MinCapacity` / `MaxCapacity` | `minReplicas` / `maxReplicas` | Same idea, same purpose |
| `TargetTrackingScaling` on `ECSServiceAverageCPUUtilization` | `metrics[].resource.name: cpu` with `averageUtilization` | Same idea. **Different denominator** - see below |
| `ScaleInCooldown: 300` | `behavior.scaleDown.stabilizationWindowSeconds: 300` | Same idea, better named |
| `ScaleOutCooldown` | `behavior.scaleUp.stabilizationWindowSeconds` + policies | Kubernetes lets you rate-limit as well as delay |
| Two CloudWatch alarms created for you | No alarms. The controller polls | **The biggest structural difference** |
| Lives in an AWS service | Lives in your cluster's controller manager | Blast radius, and Step 17 |

Note the third row: ECS measures CPU against the task's reserved CPU, the HPA against the container's request. A target of 50 does not mean the same load on both.

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

- `autoscaling/v2`, not `v1`: `v1` supports CPU only and has no `behavior` block.
- `behavior` encodes "instant out, slow in", the same doctrine as Lab 6's `ScaleInCooldown: 300`:

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

- From now on **the HPA owns `spec.replicas`**. `kubectl scale` is overwritten within 15 seconds, and `replicas:` in `manifests/lab-07/20-enrolment.yaml` is only an initial value.

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

- **`TARGETS` like `2%/50%`**: metrics work, and Step 9 will show it moving.
- **`TARGETS` of `<unknown>/50%`**: `describe` names the cause. `failed to get cpu utilization` means Step 7's pipeline is down; `missing request for cpu` means go back to Step 1.
- **`REPLICAS` reading 2.**

The `Conditions` block in `describe` (`AbleToScale`, `ScalingActive`, `ScalingLimited`) states the reason precisely; `ScalingActive: False` with `FailedGetResourceMetric` is the `<unknown>` case.

---

### Step 9 - Generate load and watch it respond

An autoscaler you have not seen move is a configuration file. This step makes it move, with an honest fallback if your build cannot.

**Part 1 - a watcher script**

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

**Part 2 - the load generator**

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

- Three pods loop `wget` against the gateway's `/enrolment/`, so both the gateway and enrolment do work.
- `|| true` keeps one failed request from ending the loop.
- The YAML `>` block folds lines into one; the trailing semicolons keep it valid shell. If the pod crash-loops, check them first.

Within 30 to 60 seconds CPU should pass 50% and `REPLICAS` should move. A typical run:

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

At 71%, `ceil(2 * 71 / 50) = 3`, but the scale-up policy allowed doubling and `selectPolicy: Max` took it, so it went to 4.

**Part 3 - remove the load and watch the stabilisation window**

```bash
kubectl scale deployment/usms-loadgen --replicas=0
```

CPU falls within seconds; **replicas do not**. For five minutes the HPA holds (`stabilizationWindowSeconds: 300`), then removes one pod per minute down to 2. That is intended behaviour, not a bug.

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
    With no metrics-server, the HPA reports `<unknown>/50%` and never acts. On real EKS you install metrics-server once (or as an add-on) and it works.

    **The fallback, a legitimate result.** Do this and say so in your report:

    ```bash
    kubectl describe hpa usms-enrolment-hpa | sed -n '/Conditions/,/Events/p'
    kubectl scale deployment/usms-enrolment --replicas=4
    ./scripts/utilities/hpa-watch.sh 6
    kubectl scale deployment/usms-enrolment --replicas=2
    ```

    Then in `notes/lab-08-notes.md`: quote the `ScalingActive: False` condition verbatim, work Step 8's arithmetic by hand for two pods at 71%, and say what you would check first on a real cluster.

!!! warning "If replicas climb and new pods sit in `Pending`"
    The HPA did its job and there is nowhere to put the pods (dimensions 1 and 3 from Step 3).

    ```bash
    kubectl get pods -l app=usms-enrolment
    kubectl describe pod <a pending one> | tail -6
    kubectl describe node <any node> | sed -n '/Allocated resources/,/Events/p'
    ```

    `Insufficient cpu` confirms it. Step 10 is the AWS-side answer. Lower `maxReplicas` or raise the node group; do not lower the CPU request, which changes the HPA's denominator.

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

Dimension 3, more nodes, and the only step that uses the AWS CLI. It makes Section 5's two-control-loops picture concrete.

**Part 1 - read the current configuration**

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

**Part 2 - change it**

```bash
aws eks update-nodegroup-config \
  --cluster-name "$USMS_EKS_CLUSTER" \
  --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --scaling-config minSize=2,maxSize=6,desiredSize=3 \
  --query 'update.{Id:id,Status:status,Type:type}' \
  --output table
```

```text
aws
 └── eks                              the SERVICE
      └── update-nodegroup-config     the OPERATION - changes an EXISTING group
           ├── --cluster-name         which cluster
           ├── --nodegroup-name       which group
           └── --scaling-config       min, max and desired, as a shorthand structure
```

- It cannot change `instanceTypes`, `amiType`, `subnets`, `nodeRole` or `diskSize`; bigger nodes means a new node group (dimension 4).
- The response is an asynchronous **Update object** (`InProgress`), not the node group. EKS uses this pattern for every mutation. On real AWS you would poll it:

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

**Part 3 - verify from both sides**

```bash
aws eks describe-nodegroup \
  --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --query 'nodegroup.scalingConfig' --output json | tee outputs/lab-08-nodegroup-after.json

echo "--- and what Kubernetes actually sees ---"
kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,LABELS:.metadata.labels.workload'
```

AWS side: `minSize 2, maxSize 6, desiredSize 3`. Kubernetes side: the node count may not change at all, and that is expected here.

!!! note "Floci Limitation - the node group's `desiredSize` is recorded, not enacted"
    Floci stores and returns the scaling configuration but starts no third node; the local nodes are not managed by an Auto Scaling group.

    On real AWS the ASG launches a third EC2 instance, which joins as `Ready` within minutes; only then do Step 9's `Pending` pods schedule.

    **Raising `replicas` and raising `desiredSize` are different operations against different APIs, and nothing connects them unless you install something that does** (Step 11).

**Part 4 - put it back, or don't**

Leaving it at 3 is fine. To restore Lab 7's numbers:

```bash
aws eks update-nodegroup-config \
  --cluster-name "$USMS_EKS_CLUSTER" --nodegroup-name "$USMS_EKS_NODEGROUP" \
  --scaling-config minSize=2,maxSize=4,desiredSize=2 \
  --query 'update.status' --output text
```

Either way, Step 19's `configs/lab-08.env` records what is actually true.

**Path B:** skip this step, note that `usms-eks-nodes` does not exist as an AWS object on your build, and answer Section 14 Question 4 from the concept.

---

### Step 11 - Cluster Autoscaler and Karpenter, and a `nodeSelector` you can actually use

Something should raise Step 10's number automatically. This step names the two options, then does the node-aware scheduling that is observable locally.

| | Cluster Autoscaler | Karpenter |
| --- | --- | --- |
| What it watches | Pods that are `Pending` because no node fits | The same |
| What it does | Increases an Auto Scaling group's desired capacity, then waits for EKS to add a node from that group | Launches EC2 instances **directly**, choosing the instance type to fit the pending pods |
| You must pre-declare | Node groups, one per instance shape you want | A `NodePool` describing acceptable instance families and constraints |
| Typical scale-out time | Minutes | Under a minute |
| Bin-packing quality | Whatever your node groups happen to be | Chooses a size that fits, so less waste |
| Maturity | The long-standing upstream Kubernetes project | AWS's newer project, now used well beyond EKS |

Cluster Autoscaler thinks in **groups you defined**; Karpenter thinks in **capacity that would fit**.

!!! note "Conceptual / Real AWS - neither autoscaler is installed in this laboratory"
    Both are Deployments that call AWS APIs through IRSA, which Lab 7 Step 21 showed is not available here; Cluster Autoscaler also needs a tagged Auto Scaling group, and there is none.

    On real EKS: an IAM policy with the `autoscaling:` describe and set-desired-capacity actions, an IRSA role, the Helm chart, and the ASG tags `k8s.io/cluster-autoscaler/enabled` and `k8s.io/cluster-autoscaler/<cluster-name>`.

    Take away what it does: it watches for `Pending` pods and writes `desiredSize`, connecting Step 9 to Step 10.

Lab 7's node group declared labels `workload=usms` and `tier=app`; a `nodeSelector` steers pods by them.

**Part 1 - do the labels exist?**

```bash
kubectl get nodes --show-labels | tr ',' '\n' | grep -E 'workload|tier' \
  || echo "node group labels did not reach the nodes"
```

**Part 2 - if they did not, apply them by hand** (on real EKS the node group would have done this)

```bash
for N in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  kubectl label node "$N" workload=usms tier=app --overwrite
done

kubectl get nodes -L workload,tier
```

`-L` adds one column per label.

**Part 3 - require the label**

```bash
kubectl patch deployment usms-enrolment --type=merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"workload":"usms"}}}}}'

kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get pods -l app=usms-enrolment -o wide
```

Every node carries the label, so pods may land anywhere. Part 4 is the real test.

**Part 4 - prove the selector is enforced**

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

The new pod is `Pending` and **the old pods keep serving**: Lab 7 Step 13's `maxUnavailable: 0` stops the roll. Stuck is better than broken.

**Part 5 - put it back**

```bash
kubectl patch deployment usms-enrolment --type=merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"workload":"usms"}}}}}'

kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get pods -l app=usms-enrolment -o wide
```

Record the change in the manifest too, so the repository matches the cluster (Step 5's lesson):

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

`kubectl diff` should print nothing, or only metadata noise. A `replicas` difference is expected; the HPA owns that field.

---

### Step 12 - A PodDisruptionBudget, and what it does not protect against

Scale-in and node maintenance both remove pods. A PDB says "not all of them at once", and is routinely misunderstood.

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

A PDB constrains **evictions**. `kubectl drain` and autoscalers use the eviction API; `kubectl delete pod` does not, which is why a delete goes straight through a PDB.

**Part 1 - write it**

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

- `minAvailable: 1` on the single-replica gateway **blocks every voluntary eviction**: a single-replica Deployment cannot be both highly available and drainable. Exercise 2 fixes it.
- `maxUnavailable: 1` on enrolment scales with the HPA's replica count.
- Use `minAvailable` for a fixed floor, `maxUnavailable` when the count moves.

**Expected result**

```text
NAME                 MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
usms-enrolment-pdb   N/A             1                 1                     5s
usms-gateway-pdb     1               N/A               0                     5s
```

> Example output.

`ALLOWED DISRUPTIONS` is the column that matters: `0` for the gateway, `1` for enrolment.

**Part 2 - prove it is consulted, and then prove what ignores it**

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

- An eviction is a pod **subresource**; `kubectl create --raw <path> -f <file>` POSTs a body to it.
- **The heredoc is unquoted** (`<< EOF`) because `$POD` must expand. Every manifest in this lab uses `<< 'EOF'`.

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

The pod is deleted and replaced and the PDB said nothing. Both outcomes are correct: a PDB constrains a cooperative process; it is not a lock.

**Part 3 - the practical consequence**

```bash
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --dry-run=client 2>&1 | tail -5
```

`--dry-run=client` shows what a drain would attempt without doing it.

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

The bottom of the exposure ladder: what Lab 7 built, and the one way to reach it from your laptop without changing anything.

| | Reachable from | Creates | Use it for |
| --- | --- | --- | --- |
| `ClusterIP` (default) | Inside the cluster only | A virtual IP and a DNS record | Everything internal. This should be most of your Services |
| `NodePort` | Any node's IP, on a port in 30000–32767 | The above, **plus** a port open on every node | Rarely used directly; it is the building block underneath the next row |
| `LoadBalancer` | An external address | The above two, **plus** a cloud load balancer | The standard way to expose one Service externally on a cloud |
| `ExternalName` | n/a | A DNS CNAME to something outside the cluster | Pointing at a managed database without changing application code |
| `kubectl port-forward` | **Only your terminal** | Nothing. It is a tunnel through the API server | Debugging. Never anything else |

**Each type is a superset of the one above**: a `LoadBalancer` Service still has a `nodePort` and a `clusterIP`. Step 15 shows all three on one object.

**Part 1 - confirm nothing is reachable from here**

```bash
kubectl get svc -o wide

CIP=$(kubectl get svc usms-gateway -o jsonpath='{.spec.clusterIP}')
echo "gateway ClusterIP: $CIP"

curl -s --max-time 5 "http://$CIP/" || echo "as expected: a ClusterIP is not routable from your machine"
```

The `curl` should fail: your laptop has no route to the cluster's virtual network.

**Part 2 - tunnel to it**

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

> Example output - pod names differ. This request reached the application through the API server, not through any networking you configured.

```text
kubectl
 └── port-forward             the SUBCOMMAND
      └── svc/usms-gateway    the target. Resolves to ONE pod behind that Service
           └── 18080:80       localPort:remotePort
```

`port-forward` is for debugging only: it is a single tunnel to a single pod (no load balancing), it exists only while the command runs on your machine, and every byte goes through the control plane. Stop it with ++ctrl+c++.

---

### Step 14 - Rung two: NodePort

The first rung that opens a real port on real machines, and the layer underneath `LoadBalancer` and `Ingress`.

`type: NodePort` allocates one port (default range 30000–32767) and opens it on **every node**; kube-proxy forwards it to a ready pod anywhere in the cluster.

```text
        node ag0 :31567 ---+
                           |
        node ag1 :31567 ---+---> kube-proxy ---> any ready pod of the Service
                           |
        node srv0:31567 ---+
```

The port is the same on every node, which is what makes a load balancer's job trivial. A node with no pods still answers (`externalTrafficPolicy: Local` changes that).

**Part 1 - a new Service rather than a patch**

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

- A **second** Service selecting the **same pods**; `usms-results` itself is unchanged.
- `nodePort: 30080` pins the port: predictable, but it can collide (`provided port is already allocated`).

**Expected result**

```text
NAME              TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE   SELECTOR
usms-results-np   NodePort   10.43.44.108    <none>        80:30080/TCP   3s    app=usms-results
```

> Example output.

`80:30080/TCP`: the ClusterIP on 80 is still there, and every node additionally answers on 30080.

**Part 2 - reach it from inside the cluster, on a node address**

```bash
NODEIP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo "node internal IP: $NODEIP"

kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- "http://$NODEIP:30080/"
```

**Part 3 - prove that *every* node answers**

```bash
for IP in $(kubectl get nodes -o jsonpath='{range .items[*]}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'); do
  echo "--- via node $IP ---"
  kubectl run usms-debug-$RANDOM --rm -i --restart=Never --image=busybox:1.36 -- \
    wget -qO- --timeout=5 "http://$IP:30080/" 2>/dev/null || echo "  no answer"
done
```

A JSON response through **each** node address, with the `pod` field varying: nodes forward to pods they do not host.

**Part 4 - from your machine**

```bash
curl -s --max-time 5 http://localhost:30080/ ; echo
```

!!! note "Floci Limitation - a NodePort is not automatically published to your host"
    The nodes are containers, and 30080 was not published when they were created.

    On real AWS the nodes are EC2 instances in your VPC, reachable on the NodePort by anything the security group admits, which is how a load balancer reaches them.

    **The fallback:**

    ```bash
    kubectl port-forward svc/usms-results-np 30080:80
    # then, in another terminal:
    curl -s http://localhost:30080/ ; echo
    ```

    This proves the Service works, not that the NodePort is externally reachable. Say so in your report.

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

On a real cloud, this rung provisions infrastructure. Lab 7's `_lb_ports_` tag is used here.

`type: LoadBalancer` does everything NodePort does, then the cloud controller creates a load balancer and writes its address into `status.loadBalancer.ingress[0]`. `<pending>` means it has not finished, or, if permanent, that no controller is listening. **One `LoadBalancer` Service is one load balancer and one bill**; that is the economic argument for Ingress.

**Part 1 - promote the gateway**

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

This is a **complete Service manifest** replacing Lab 7's, not a patch, so the repository describes the cluster. The three annotations are the whole of "EKS-specific" in this lab:

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

On a non-AWS cluster the annotations are inert strings, so the manifest stays portable.

**Part 2 - watch for an address**

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

`80:31946/TCP`: a nodePort was allocated automatically. `LoadBalancer` contains `NodePort` contains `ClusterIP`.

**Part 3 - reach it**

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
    Some builds start a service load balancer for the local cluster and publish 8081 and 8082 through the `_lb_ports_` tag; some do not.

    On real EKS with the AWS Load Balancer Controller, this produces an NLB in your public subnets with pod IPs as targets, and `EXTERNAL-IP` becomes a name like `k8s-usms-usmsgat-abc123.elb.us-east-1.amazonaws.com`.

    Take away the shape: one Service, one load balancer, one bill, and `target-type: ip` exactly as in Lab 5. If yours stays `<pending>`, use `kubectl port-forward svc/usms-gateway 8080:80` to show the Service works, record the `<pending>` state, and say which rungs you observed and which you reasoned about.

**Verify**

```bash
kubectl get svc usms-gateway \
  -o jsonpath='{"type="}{.spec.type}{"  clusterIP="}{.spec.clusterIP}{"  nodePort="}{.spec.ports[0].nodePort}{"  external="}{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

`type=LoadBalancer`, a `clusterIP`, a `nodePort`, and an `external` address or empty. That one line is the ladder; put it in your report.

---

### Step 16 - Rung four: Ingress, and the comparison this practical was built for

The top rung, and the point where Practical 2 and Practical 4 turn out to describe the same infrastructure.

An **Ingress** is a set of HTTP routing rules. It does nothing on its own; an **ingress controller** implements it:

| Controller | What it creates | Where it runs |
| --- | --- | --- |
| Traefik | Routing inside a pod in your cluster | In-cluster. Default on k3s |
| ingress-nginx | The same, with nginx | In-cluster |
| **AWS Load Balancer Controller** | **An Application Load Balancer, in your VPC** | In-cluster, calling the AWS API |

On EKS with the AWS Load Balancer Controller, an Ingress produces an ALB with a target group of type `ip` and one listener rule per path: what you built by hand in Lab 5.

```text
LAB 05, by hand                          LAB 08, from one Ingress object
  aws elbv2 create-load-balancer            spec.rules[]  and the ingress class
  aws elbv2 create-target-group             one target group per backend Service
     --target-type ip                       alb.ingress.kubernetes.io/target-type: ip
  aws elbv2 create-listener                 listen-ports annotation
  aws elbv2 create-rule --priority 10       spec.rules[].http.paths[]
  ecs register/deregister targets           the controller watches Endpoints
```

**Nothing new is being provisioned; the same ALB is asked for differently.** And ten paths on one Ingress is one load balancer, not ten.

**Part 1 - is there a controller?**

```bash
kubectl get ingressclass 2>/dev/null || echo "no IngressClass registered"
kubectl get pods -A | grep -Ei 'traefik|ingress|nginx-controller' || echo "no ingress controller pod found"
```

Look for an IngressClass such as `traefik` or `nginx`. With none, the Ingress will exist but never get an address; record that as a Conceptual result.

**Part 2 - write the Ingress**

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

- **Longest matching path wins**, not the order written, so `/enrolment/x` reaches `usms-enrolment` although `/` also matches. Lab 5's ALB used **numeric priority** instead.
- `pathType: Prefix` matches whole segments: `/results` matches `/results/2026` but not `/resultsarchive`. Avoid `ImplementationSpecific`.
- `/enrolment` now bypasses `usms-gateway`, which strips a prefix and adds headers. Section 14 Question 6 asks you to choose between the two paths.

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

**Part 3 - exercise the routes**

```bash
for P in / /enrolment/ /results/ ; do
  echo "--- $P ---"
  curl -s --max-time 5 "http://localhost:8081$P" || echo "  (no answer on 8081)"
  echo
done
```

If nothing answers on 8081, test the routing in-cluster:

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
    Without a controller, the Ingress is stored and served by the API server but never given an address.

    On real EKS, the AWS Load Balancer Controller turns this object into an internet-facing ALB in your public subnets, one `ip` target group per backend, one rule per path.

    Take away that an Ingress is a declaration of routing intent: the same lines give a Traefik rule locally and an ALB in production. If you have no controller, answer in prose instead: *which four `aws elbv2` commands from Lab 05 would the AWS Load Balancer Controller have run on your behalf, and in what order?*

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

The ECS stack from Labs 4 to 6 and the EKS stack from Labs 7 and 8 are both running. Check claims about them now rather than remember them later.

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

Fill it in with both systems in front of you; Section 13 grades it and Section 14 Questions 3 and 7 assume it. Two rows surprise people: Application Auto Scaling runs in AWS outside anything you own, while the HPA runs in the controller manager (on EKS, AWS-operated, so almost but not quite the same); and Fargate never runs out of capacity, while the HPA can (Step 9's warning).

---

### Step 18 - Prove that scaling and exposure configuration survive a restart

The course rule since Lab 1: create, perturb, read back. The property is that the HPA, PDBs, Services and Ingress are stored state.

**Part 1 - record the truth**

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

**Part 2 - perturb**

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

**Part 3 - read back**

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

The rows should be identical. Two differences are legitimate; decide about them rather than dismiss them:

- **A changed `nodePort`** on `usms-gateway` (auto-allocated). `usms-results-np` was pinned to 30080 and must not change: the argument for pinning.
- **`EXTERNAL-IP` back to `<pending>`.** The Service persisted; whatever fulfils it restarted. On real AWS the load balancer lives outside the cluster and keeps its address.

If the HPA or Ingress is missing entirely, run `./scripts/utilities/floci-storage-check.sh` first; storage mode `memory` is the usual cause.

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

Names and numbers, never secrets, looked up rather than remembered.

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

**The heredoc is unquoted** so every `$(...)` runs now; the manifests used `<< 'EOF'` for the opposite reason. Every value is looked up live, so a deleted object shows as empty.

**Expected result**

```text
all values populated
```

Three expected exceptions:

- `USMS_INGRESS_CLASS` is empty if no ingress controller is running (Step 16).
- `USMS_SVC_GATEWAY_NODEPORT` should not be empty after Step 15; investigate if it is.
- The three `USMS_NODEGROUP_*` values are empty on Path B.

**Verify**

```bash
source configs/lab-08.env
echo "hpa: $USMS_HPA_MIN..$USMS_HPA_MAX at ${USMS_HPA_CPU_TARGET}% cpu, scale-in window ${USMS_HPA_SCALEDOWN_WINDOW}s"
echo "nodeport: $USMS_SVC_NODEPORT   gateway: $USMS_SVC_GATEWAY_TYPE"
grep -c '^export' configs/lab-08.env
```

`hpa: 2..8 at 50% cpu, scale-in window 300s`, `nodeport: 30080`, `gateway: LoadBalancer`, and **19** exported variables.

---

### Step 20 - Commit your work

**Part 1 - look before you add**

```bash
git status --short
```

Before typing anything else, check:

- No path under `outputs/` (this lab wrote six files there).
- No `.env` at the repository root.
- `configs/lab-08.env` **does** appear.
- `manifests/lab-07/20-enrolment.yaml` appears because Step 11 added a `nodeSelector`. That is intended.

If anything under `outputs/` is listed, diagnose before committing:

```bash
git check-ignore -v outputs/lab-08-baseline.txt
```

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-08-baseline.txt
```

> Example output - the line number will differ.

If it prints nothing, the rule is probably `outputs/` rather than `outputs/*`, the silent failure from the course contract.

**Part 2 - add and commit**

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

This commit above Lab 7's; `manifests/lab-08/` and `configs/lab-08.env` in the file list; and **`0`** from the last command.

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

### Path C - what to do if you have no cluster

1. **Write every manifest** in Section 6's list and validate them with `kubectl apply --dry-run=client -f manifests/lab-08/`. No cluster is needed.
2. **Do Steps 3, 6 and 8's concept parts**, and work the HPA arithmetic by hand for 2 pods at 80%, 4 pods at 30%, and 8 pods at 95% with `maxReplicas: 8`. Show the `ceil` each time and say what `behavior` would allow.
3. **Do Step 10 if you are on Path A**; it needs no `kubectl`.
4. **Do Step 17 in full**; it needs only Labs 5 and 6.
5. **Answer all of Section 14**, and do Section 12's Exercises 3 and 4 on paper, labelling output as expected rather than observed.

That is a legitimate submission. An invented `kubectl get hpa` output is not.

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-08.sh`

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

Failures in the **Environment** block are the real problem; the rest usually follow from them. On **Path B**, expect exactly two failures (the `_lb_ports_` tag and the node group's `maxSize`): `PASS=32  FAIL=2` is correct.

A quick end-to-end check you can run any time:

```bash
kubectl run usms-smoke --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  G=http://usms-gateway.usms.svc.cluster.local
  wget -qO- $G/ && wget -qO- $G/enrolment/ && wget -qO- $G/results/
' && echo "SMOKE TEST PASSED"

kubectl get hpa,pdb,svc,ingress
```

### 8.2 Build the cleanup script - DO NOT RUN IT NOW

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

The order: **Ingress, LoadBalancer Service, controllers, workloads, AWS**. Remove what references before what is referenced, and anything that provisions external infrastructure first; an ALB left behind by a deleted cluster is billed and hard to find.

---

## 9. Checkpoints

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

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, `update-nodegroup-config` fails, so the node group cannot be resized. Diagnose first, then use the alternative in [Known Issues - Lab 08](known-issues.md#lab-08-eks-scaling). It states what the alternative does and does not prove.

??? danger "`kubectl get hpa` shows `<unknown>/50%` and never changes"
    `describe` names the cause:

    ```bash
    kubectl describe hpa usms-enrolment-hpa | sed -n '/Conditions/,/Events/p'
    ```

    `FailedGetResourceMetric` / `unable to get metrics for resource cpu`: the metrics pipeline is down; go back to Step 7 and check `kubectl get --raw /apis/metrics.k8s.io/v1beta1`.

    `missing request for cpu`: fix the Deployment, not the HPA:

    ```bash
    kubectl set resources deployment/usms-enrolment --requests=cpu=50m,memory=32Mi
    ```

    Or you are reading it in its first 15 to 30 seconds. Wait and re-read.

??? danger "The HPA scales up, but the new pods stay `Pending`"
    No room for the pods (dimensions 1 and 3 from Step 3).

    ```bash
    kubectl get pods -l app=usms-enrolment
    kubectl describe pod <a pending one> | tail -6
    kubectl describe node <any node> | sed -n '/Allocated resources/,/Events/p'
    ```

    `Insufficient cpu` confirms it. Add nodes (Step 10, or a cluster autoscaler) or lower `maxReplicas`. **Do not lower the CPU request**: it changes the HPA's denominator, making recorded percentages incomparable and scaling more aggressive.

??? danger "`kubectl scale` appears to work and then the replica count changes back"
    The HPA owns `spec.replicas` and overwrites you within 15 seconds. To scale by hand during an incident, remove its authority first:

    ```bash
    kubectl delete hpa usms-enrolment-hpa
    kubectl scale deployment/usms-enrolment --replicas=6
    # ... and re-apply the HPA afterwards
    kubectl apply -f manifests/lab-08/10-hpa-enrolment.yaml
    ```

    `replicas:` in `manifests/lab-07/20-enrolment.yaml` is now only an initial value and `kubectl diff` will always report it. Teams usually remove the field once an HPA owns it.

??? danger "The load generator runs but CPU never rises"
    Check the load is arriving:

    ```bash
    kubectl logs deploy/usms-loadgen --tail=5
    kubectl top pods
    kubectl exec deploy/usms-loadgen -- wget -qO- http://usms-gateway.usms.svc.cluster.local/enrolment/
    ```

    If the last command returns JSON, raise `replicas` on `usms-loadgen`. If it fails, a backend is down. Also check `kubectl get pods -l app=usms-loadgen` for a crash loop caused by lost semicolons in the `>` block.

??? danger "`nodePort: 30080` is rejected with `provided port is already allocated`"
    Another Service, possibly in another namespace, has the port:

    ```bash
    kubectl get svc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,TYPE:.spec.type,NODEPORT:.spec.ports[*].nodePort' | grep 30080
    ```

    Free it, or pick another port in 30000–32767 and update `manifests/lab-08/40-service-nodeport.yaml` and `configs/lab-08.env`. Keep it pinned; Step 18 depends on a stable port.

??? danger "`EXTERNAL-IP` stays `<pending>` forever"
    Nothing implements `type: LoadBalancer` here; expected locally (Step 15).

    ```bash
    kubectl describe svc usms-gateway | tail -10
    kubectl get pods -A | grep -Ei 'cloud-controller|servicelb|klipper'
    ```

    An empty `Events` section means nothing even tried. On real EKS a stuck `EnsuringLoadBalancer` usually means IAM or subnet tagging: public subnets need `kubernetes.io/role/elb=1`.

??? danger "The Ingress exists but has no ADDRESS and nothing routes"
    No controller is running, or the Ingress names no class it claims.

    ```bash
    kubectl get ingressclass
    kubectl describe ingress usms-portal-ingress | tail -12
    ```

    If an IngressClass exists but is not the default, name it:

    ```bash
    kubectl patch ingress usms-portal-ingress --type=merge \
      -p '{"spec":{"ingressClassName":"traefik"}}'
    ```

    If none exists, record the Conceptual case and answer Step 16's written alternative.

??? danger "A drain hangs and never finishes"
    A PDB is refusing evictions, most likely `usms-gateway-pdb` (`minAvailable: 1` against one replica).

    ```bash
    kubectl get pdb
    kubectl describe pdb usms-gateway-pdb
    ```

    `ALLOWED DISRUPTIONS: 0` confirms it. Fix the workload (scale the gateway to 2; Exercise 2), not the PDB. To back out now: ++ctrl+c++ the drain, then `kubectl uncordon <node>`.

??? danger "After the restart, `kubectl` works but the namespace default is gone"
    `update-kubeconfig` sets the context but not your default namespace.

    ```bash
    kubectl config set-context --current --namespace=usms
    kubectl config view --minify --output 'jsonpath={..namespace}'; echo
    ```

---

## 11. Floci vs Real AWS

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

**Where Floci is nicer than reality (traps on real AWS):** pods start in a second, but a real EKS node takes 60 to 120 seconds to become `Ready`; there is no cost (ten `LoadBalancer` Services are ten NLBs, and `maxReplicas`/`maxSize` are spending limits); no quotas on load balancers, Elastic IPs or instances; a tidier metrics picture than a real bumpy workload; and nothing is eventually consistent (a real ALB from an Ingress takes minutes to become healthy).

In your report, say whether each claim was observed, recorded but not enacted (node group sizes, AWS annotations, `EXTERNAL-IP`), or conceptual (the AWS Load Balancer Controller, Cluster Autoscaler, Karpenter, custom metrics, cost).

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-08-eks-scaling/exercises.md`; screenshots go in `screenshots/`.

### Exercise 1 - Basic: a second autoscaler

**Requirements:** give `usms-results` its own HPA: min 2, max 6, 60% CPU, a 180-second scale-in stabilisation window, and a scale-up policy adding at most 2 pods every 30 seconds.

**Constraints**

- `autoscaling/v2`, as a manifest at `manifests/lab-08/11-hpa-results.yaml`. No `kubectl autoscale`.
- Pass a client-side dry run before applying for real.
- Say in one sentence why 60% suits a read-mostly results service when enrolment uses 50%.

**Expected outcome:** `kubectl get hpa` shows two HPAs reporting percentages (or both `<unknown>` with no metrics pipeline; say so).

**Hints:** `manifests/lab-08/10-hpa-enrolment.yaml` is the model. Check `usms-results` declares a CPU request first (Lab 7 Step 14).

### Exercise 2 - Intermediate: make the gateway drainable

**Requirements:** Step 12 showed `usms-gateway-pdb` allows **zero** disruptions. Fix that properly, and prove it.

**Constraints**

- End with `ALLOWED DISRUPTIONS` of at least 1.
- Do not weaken the PDB; `minAvailable: 1` stays unless you justify a change in writing.
- Gateway pods must not all share one node, where there is more than one node. If there is only one, say what you would have done.
- Update `manifests/lab-07/40-gateway.yaml` and show a clean `kubectl diff`.

**Expected outcome:** non-zero allowance in `kubectl get pdb`, pod placement from `kubectl get pods -o wide`, and a clean `kubectl diff`.

**Hints:** the PDB is not the thing to change. Lab 7 Exercise 4 named three ways to spread pods; the simplest fix needs none of them.

### Exercise 3 - Problem solving: the autoscaler that will not act

**Requirements:** apply the manifest below exactly. The HPA is created, yet under heavy load the replica count never changes. Diagnose it with commands, state **both** causes in one sentence each, and fix each with the smallest change.

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

- Find both faults with commands, not by reading the YAML. Show them in order with the revealing output.
- Each fix is a single field.
- One fault gives `<unknown>`; the other prevents action even with perfect metrics. Say which is which.

**Expected outcome:** a diagnosis with evidence, and an HPA reporting a percentage with room to move. Delete `usms-reports` and its HPA afterwards (CLEAN UP).

**Hints:** read all three conditions in `describe`. For the second fault, ask what values are possible between the two numbers the HPA clamps to.

### Exercise 4 - Challenge: expose the results service properly

**Requirements:** the brief:

> The Examinations Office wants the results endpoint reachable from the university network at a
> stable address, on a normal HTTP port, on a path of its own, without giving the enrolment endpoint
> the same exposure and without paying for a second load balancer. They also want to know, in
> advance, what it would cost and what would break if the cluster were unavailable.

Design it, implement what your build allows, and justify every choice in prose.

**Constraints**

- No second `type: LoadBalancer` Service; say why in one sentence.
- State which rung of Step 13's ladder each part sits on.
- Where your build cannot demonstrate something, name the object or annotation that would do it on real EKS.
- Answer the cost and the failure mode.

**Expected outcome:** one or two manifests, routing evidence, and about half a page of reasoning. Marks are for design and honesty, not YAML.

**Hints:** Step 16 already routes `/results`. Is the existing Ingress the answer, a starting point, or the wrong shape? NLBs and ALBs are billed differently; one Ingress with five paths is billed once.

### Exercise 5 - Integration: the artefacts Lab 10 needs, and the argument this practical was for

**Requirements:** three parts.

- **Part 1:** `outputs/lab-08-scaling-evidence.json`: the HPA's spec and status, the Deployment's replica count, the node group's scaling configuration (or a stated absence) and a timestamp, as valid JSON that `python3 -m json.tool` accepts.
- **Part 2:** `outputs/lab-08-lab06-readiness.txt`: the ARN of `USMSStudentDataReadWrite`, every role carrying it, the bucket ARN in its `Resource`, whether the bucket exists, and **which ServiceAccount in `usms` would be annotated to use it under IRSA**, with the annotation.
- **Part 3:** append to `notes/lab-08-notes.md` at most 400 words titled "ECS or Kubernetes for USMS": a recommendation, the strongest argument against it, and at least three specific observations from Practicals 2 and 4.

**Constraints**

- Part 1 is assembled from live API calls; unavailable values are stated explicitly, not omitted.
- Part 2 reads the bucket ARN **out of the policy document**. Re-derive it; do not copy Lab 7 Exercise 5.
- Part 3 is your own argument, with no generic claims.

**Expected outcome:** two files in `outputs/` (check with `git check-ignore -v`) and a new notes section. Lab 10's first step reads all three.

**Hints:** combine `kubectl get hpa usms-enrolment-hpa -o json` with the AWS output using `python3` or `jq`, not a heredoc of fragments. Lab 7 Step 21 created `usms-enrolment-sa`; the annotation key is `eks.amazonaws.com/role-arn`. Which role, and why not `usms-eks-node-role`?

---

## 13. Lab Assessment Checklist

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

- [ ] Section 14 answered in prose in `notes/lab-08-notes.md`
- [ ] Step 17's two comparison tables filled in with both systems running
- [ ] Five exercises attempted; Exercise 5's two `outputs/` files present
- [ ] `usms-loadgen` deleted at the end (Section 15)

---

## 14. Review Questions

Answer in prose in `notes/lab-08-notes.md`.

1. A colleague says an HPA with `averageUtilization: 50` "scales when the node hits 50% CPU". Correct them. What happens if someone halves the container's CPU request without changing the HPA, and does the workload end up with more capacity or less?
2. `usms-enrolment` must handle ten times its traffic by Monday. Using Step 3's four dimensions, give an ordered plan with the check between each step, and name the dimension that cannot change in place and what you would do instead.
3. Lab 6's Application Auto Scaling and this lab's HPA both write one integer. Give two consequences of one running outside your workload and the other inside your cluster, at least one about failure.
4. The HPA raises `replicas` from 4 to 8 and four pods sit `Pending` for twenty minutes. Explain using Section 5's two-control-loops picture, name the component that would normally resolve it, and say why lowering the CPU request is a bad fix.
5. Students conflate **NodePort** with **LoadBalancer**, and **Service** with **Ingress**. Take one pair, explain the distinction, and give a requirement the wrong choice fails and the right one meets.
6. Step 16's Ingress sends `/enrolment` straight to `usms-enrolment`, bypassing `usms-gateway`, which also serves that path. Argue for one route, say what you would delete, and address what the gateway does that the Ingress rule does not.
7. A PDB with `minAvailable: 1` did not stop `kubectl delete pod`. Why is that correct? Distinguish voluntary from involuntary disruption, and give one realistic scenario where your PDB saves a production service.

---

## 15. KEEP vs CLEAN UP

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

You want five pods (two enrolment, two results, one gateway) plus whatever Exercises 1 and 2 left; no `usms-loadgen`; no cordoned nodes.

!!! danger "Read before running any delete command"
    **What will be deleted:** the load generator Deployment, Exercise 3's practice objects, and any
    leftover debug pods.
    **What depends on them:** nothing. Every one of them was created in this lab as a temporary
    instrument.
    **Reversible?** Yes - `usms-loadgen` is in `manifests/lab-08/20-loadgen.yaml` and can be
    re-applied at any time.
    **Effect on later labs:** none.

Do **not** run `scripts/cleanup/lab-08-cleanup.sh` or any earlier lab's cleanup script; they are for the end of the course, in the order Section 8.2 gives.

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

## 16. Preparation for the Next Lab

Lab 10 creates `usms-student-data`, the bucket Lab 1's policy has named all along. It needs nothing from this lab's scaling or exposure configuration, only these:

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

Creating that one bucket resolves the chains from Labs 1, 2, 3, 4 and 7 without modifying any of them.

Before the next session:

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

You want `FAIL=0` from the first on Path A or `FAIL=3` on Path B; `FAIL=0` from the second on Path A or `FAIL=2` on Path B; **19**; one HPA, two PDBs and one Ingress; three Deployments at least `2`, `2` and `1`; and **three role names**. Fewer than three means an attachment from Lab 3, 4 or 7 is missing; fix it now.

Take a snapshot so a Lab 10 mistake is recoverable:

```bash
floci snapshot save lab-08-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-08.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

---

## Appendix - New CLI and JMESPath patterns

**`kubectl`**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `kubectl diff -f` | Render the post-apply state and diff it. Exit 1 means "there is a difference" | Steps 5, 11 |
| `-L label1,label2` | One column per named label | Step 11 |
| `--type=merge -p '<json>'` | A strategic-merge patch inline. Fast, and it creates drift | Steps 11, 12 |
| `kubectl create --raw <path> -f <file>` | POST to an API path directly - the only way to reach a subresource such as `eviction` | Step 12 |
| `kubectl get svc -w` | Watch one object change. How you see `<pending>` become an address | Step 15 |
| `-o jsonpath` with literal text and `{"\n"}` | Build a one-line report from several fields | Step 15 |
| `--request-timeout=10s` | Bound a call so a script cannot hang forever | Section 8 |
| `--dry-run=client -f <dir>` | Validate a whole directory of manifests with no cluster | Section 8, Path C |

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

# Unit 3 Lecture: Deploying Applications on Amazon EKS

**Duration:** 2 hours (120 minutes, including a 5-minute break)  
**Audience:** 4th-year Software Engineering students who know Kubernetes fundamentals and attended the 3.1 lecture  
**Mode:** Lecture with a console walk-through on the shared cluster, a CLI rollout exercise on Floci, and a ClassLegend quiz  
**Running scenario:** The USMS student portal must ship a new version during results week without dropping a single request

<div class="lesson-schedule"></div>

## Before class

!!! teacher "Purpose"
    3.1 explained how an EKS cluster is built. This lecture is about **getting an application onto it, changing it safely, and recovering when a release goes wrong**. Students already know Pods, Deployments, Services and basic `kubectl`, and they did rolling updates and an `ImagePullBackOff` in Lab 07 Steps 18 and 19. Do not re-teach those mechanics; use them as the starting point for the deployment *decisions*: which tool, which cluster, which probe, which rollout settings, and who rolls back.

**Learning outcomes.** By the end, students should be able to:

1. Separate cluster provisioning, packaging and delivery, and name a typical tool for each.
2. State the cluster build order and predict the symptom when a stage is missing.
3. Explain why `eksctl` and `kubectl` are not interchangeable, and where Helm fits.
4. Explain what a kubeconfig context is and check it before every change.
5. Read a Deployment manifest for labels and selectors, image tag, requests and limits, and probes.
6. Explain why a liveness probe must never check the database.
7. Predict the shape of a rolling update from `maxSurge` and `maxUnavailable`, recognise a stalled rollout, and recover with `kubectl rollout undo`.
8. Choose between plain manifests, Helm and Kustomize for a given situation.
9. State the EKS upgrade order and clean up the AWS resources a deployment can leave behind.

**Teacher preparation**

- [ ] Create the shared cluster `dso303-u3-shared` **at least 30 minutes before class**, following [Unit 3: Shared EKS Cluster](unit3-shared-eks-cluster.md), and run its **optional Step 9** so the `portal` Deployment (3 replicas of `nginx:stable`) exists for Hands-on A
- [ ] Confirm the node group shows two nodes **Ready** and `kubectl get pods -o wide` lists three `portal` Pods spread over the nodes
- [ ] Decide which access case applies (shared page, Step 8): students in the same account get an access entry with `AmazonEKSViewPolicy`; students in their own accounts (for example AWS Academy Learner Lab) follow on your screen
- [ ] Open the cluster's **Resources**, **Compute**, **Access** and **Add-ons** tabs once yourself, since console labels change over time
- [ ] Load the quiz bank `private/quizzes/unit3-topic2.questions.md` into ClassLegend
- [ ] Have [3.2 notes](../unit3/topic2.md){ target="_blank" } and [3.1 notes](../unit3/topic1.md){ target="_blank" } open in tabs

**Floci environment checks (on your own machine, before class)**

- [ ] `cd ~/aws-floci-course && ./scripts/setup/floci-up.sh` starts or resumes Floci without errors
- [ ] `source configs/course.env && source configs/lab-07.env && ./scripts/utilities/whoami.sh` prints account `000000000000`
- [ ] `notes/lab-07-notes.md` records your support path (Lab 07 Step 2): **Path A** (`aws eks` works, k3s-backed cluster) or **Path B** (`k3d` fallback)
- [ ] `kubectl config current-context` names the Lab 07 cluster (`usms-eks` on Path A, `k3d-usms-eks-cluster` on Path B) and `kubectl get nodes` shows at least one node `Ready`
- [ ] Do a dry run of Hands-on B end to end, including the deliberately bad tag, then `kubectl delete namespace u3t2`
- [ ] The Docker host can pull `nginx:1.27-alpine` and `nginx:1.27` (both used in Lab 07; pre-pull them on a slow network)

!!! warning "Students create no EKS clusters"
    The only EKS cluster in this lesson is yours. Students change nothing on it. Their CLI work runs on Floci, in a new namespace `u3t2`, and never touches the Lab 07/08 namespace `usms`.

!!! note "Helm is not installed in the course environment"
    Lab 07 and Lab 08 list Docker, AWS CLI, `kubectl`, `k3d` (Path B only), `python3` and optional `jq`, `watch` and `curl`. Helm is not among them, so Helm appears here as a **reading exercise** in Concept B, not a student task. If you have Helm installed, you may show `helm template` on your screen.

---

## Hook: release night { data-minutes="10" }

[3.1 What Kubernetes does](../unit3/topic1.md#what-kubernetes-does){ .notes-link target="_blank" }
[3.1 Kubernetes objects compared with ECS](../unit3/topic1.md#kubernetes-objects-compared-with-ecs){ .notes-link target="_blank" }
[3.2 Definition](../unit3/topic2.md#definition){ .notes-link target="_blank" }

**Quick-fire recall from 3.1 (about 5 minutes).** Ask, take one answer each, move on fast.

1. Which object keeps N identical Pods running: a Pod, a Deployment or a Service?
2. Who runs the EKS control plane, and who runs the workloads?
3. A colleague runs `kubectl get pods` and gets `Unauthorized`. A second colleague gets `Forbidden`. What is different?
4. Which add-on gives Pods real VPC IP addresses?
5. What does "reconciliation" mean in one sentence?

???+ answer "Expected responses"
    1. A **Deployment** (through a ReplicaSet). A Service gives a stable address; a Pod is one instance.
    2. **AWS** operates the control plane; **we** operate the workloads and (unless using Fargate or Auto Mode) the nodes.
    3. `Unauthorized`: the cluster does not recognise the identity (no access entry). `Forbidden`: recognised, but the access policy does not allow the action.
    4. The **Amazon VPC CNI**.
    5. Controllers continuously compare desired state with actual state and act to close the gap.

!!! prompt "Release night for the student portal"
    It is results week. The USMS portal runs on EKS with three replicas. At 21:00 the team must release version 1.4.3, which fixes a bug in the transcript download. Thousands of students are refreshing the results page.

    **In pairs (3 minutes):** list everything that has to be true, or has to happen, between "the code is merged" and "every student sees 1.4.3 and nobody saw an error".

!!! teacher "Collect answers into three columns, without naming them yet"
    Write answers on the board as they come and sort them silently into three columns:

    - **Cluster exists and is healthy** (nodes, access, add-ons, load balancer controller)
    - **The app is described correctly** (image tag, replicas, resources, probes, per-environment values)
    - **The change gets there safely** (who applies it, how it rolls, how we know it finished, how we undo it)

    Then reveal the column headings: **provisioning, packaging, delivery**. That is the spine of the lecture.

    **Transition:** "Most deployment confusion comes from mixing these three up. Let's pull them apart."

## Provisioning, packaging, delivery { data-minutes="15" }

[3.2 Definition](../unit3/topic2.md#definition){ .notes-link target="_blank" }
[3.2 Creating and managing EKS clusters](../unit3/topic2.md#creating-and-managing-eks-clusters){ .notes-link target="_blank" }
[3.2 Deploying applications using kubectl and eksctl](../unit3/topic2.md#deploying-applications-using-kubectl-and-eksctl){ .notes-link target="_blank" }

### Three concerns, three rates of change

| Concern | Question it answers | Typical tools | How often it changes |
|---|---|---|---|
| **Cluster provisioning** | Does a cluster exist with the right network, nodes, add-ons and access? | `eksctl`, CloudFormation, CDK, Terraform, console | Rarely (weeks, months) |
| **Packaging** | Which objects describe this app, and how do they differ per environment? | YAML manifests, Helm, Kustomize | With every feature |
| **Delivery** | How do those objects reach the cluster repeatably? | `kubectl` for learning, CI/CD pipelines for teams | With every release, possibly many per day |

!!! prompt "Analogy: a restaurant chain"
    - **Provisioning** is building and equipping the kitchen: ovens, gas, staff passes.
    - **Packaging** is the recipe card, with a small note per branch ("large portions in the city branch").
    - **Delivery** is the process that gets a new recipe card to the kitchen and makes sure the chefs actually switch to it.

    You do not rebuild the kitchen to change a recipe, and you do not reprint every recipe to fix the gas.

!!! teacher "Where the analogy breaks"
    A kitchen does not continuously compare itself with the recipe and correct itself. Kubernetes does: once the new description is delivered, controllers keep making reality match it. Also, "delivery" in Kubernetes ends when the description is stored, not when the meal is served, which is exactly why `kubectl rollout status` matters later.

### Build order, and what breaks when a stage is missing

| Stage | What is created | Symptom if skipped or wrong |
|---|---|---|
| 1. Prerequisites | Cluster role, node role, VPC, subnets, NAT | Creation fails, or nodes cannot reach ECR |
| 2. Control plane | API server, `etcd`, cluster security group (10 to 15 min) | Nothing else can proceed |
| 3. Access | Access entries for people and pipelines | `Unauthorized` for everyone but the creator |
| 4. Core add-ons | VPC CNI, `kube-proxy`, CoreDNS | Nodes never `Ready`; DNS fails |
| 5. Node group | Auto Scaling group and EC2 instances | Every Pod stays `Pending` |
| 6. Controllers | AWS Load Balancer Controller, metrics-server | Ingress does nothing; no autoscaling metrics |

!!! prompt "Predict, then check"
    A teammate creates a cluster, deploys the portal, and reports: "The deployment is broken. CoreDNS and all my Pods are `Pending`." `kubectl get nodes` returns `No resources found`.

    Is the cluster broken? Which stage was skipped?

???+ answer "Expected response"
    Not broken: **stage 5, the node group, is missing**. `CreateCluster` makes the control plane only. With no nodes, the scheduler has nowhere to place Pods, CoreDNS included. They start as soon as a node group joins. Telling "nowhere to run" from "broken" is a core skill.

**Quick or custom?** The console's **Create cluster** page offers **Quick configuration (with EKS Auto Mode)**, where AWS takes over most of stages 4 to 6 (Pod networking, DNS, nodes and load balancing) and launches nodes on demand, and **Custom configuration**, where the **Use EKS Auto Mode** switch is on by default. Our shared cluster uses Custom configuration with Auto Mode switched **off**, so every stage above is visible on the tabs you will open next. (`eksctl` equivalent: `--enable-auto-mode`.)

### Which tool does which job

| Tool | Side | Job |
|---|---|---|
| `eksctl` | AWS | Creates the cluster, node groups, IAM roles and add-ons in the right order, by generating CloudFormation stacks |
| AWS CLI | AWS | AWS operations, including `aws eks update-kubeconfig` |
| `kubectl` | Kubernetes | Manages the objects *inside* the cluster |
| Helm | Kubernetes | Packages and releases applications as versioned charts |

!!! warning "Not interchangeable"
    **`eksctl` builds the cluster; `kubectl` manages what runs inside it.** `kubectl` cannot create an EKS cluster, and `eksctl` is not how you roll out version 1.4.3. For anything beyond a lab, keep the cluster definition in a `ClusterConfig` file (`eksctl create cluster -f cluster.yaml`) or your team's IaC tool, and use **one** provisioning tool per cluster.

### Upgrades: the order matters

Kubernetes versions are supported for a limited time, so upgrades recur. They go **one minor version at a time**, control plane first. This is the order in AWS's upgrade best-practices guide:

```text
1. Control plane     e.g. 1.36 -> 1.37 (console: Upgrade now)
2. Add-ons           VPC CNI, CoreDNS, kube-proxy to versions compatible with the new control plane
3. Nodes             replaced by new ones in a rolling update (cordon, drain, PodDisruptionBudgets)
```

The EKS User Guide lists nodes before add-ons; both work as long as the control plane is first and versions stay compatible.

**Ask the class:** why can nodes never go first?

???+ answer "Expected response"
    Nodes may run **behind** the control plane (up to three minor versions) but never **ahead** of it. Upgrading the control plane first keeps that true at every moment. Before starting, check the **Upgrade insights** tab and your manifests for APIs removed in the target version, and rehearse in non-production. Since July 2026 EKS can roll the control plane back one version, but only within 7 days and only after rolling back any nodes already upgraded, so treat an upgrade as a one-way door.

!!! teacher "Transition"
    "You will see every one of these stages on a real cluster now: the node group, the access entries, the add-on versions and the workloads."

## Hands-on A: the shared cluster { data-minutes="15" }

[3.2 Creating and managing EKS clusters](../unit3/topic2.md#creating-and-managing-eks-clusters){ .notes-link target="_blank" }
[3.2 The objects you write](../unit3/topic2.md#the-objects-you-write){ .notes-link target="_blank" }
[3.1 Cluster access: authentication versus authorisation](../unit3/topic1.md#cluster-access-authentication-versus-authorisation){ .notes-link target="_blank" }
[3.2 Requests and limits](../unit3/topic2.md#requests-and-limits){ .notes-link target="_blank" }

!!! teacher "Who does what"
    Pick the case from [the shared cluster page, Step 8](unit3-shared-eks-cluster.md):

    - **Same AWS account:** students sign in, open EKS in the class Region, and select `dso303-u3-shared`. Their access entry has `AmazonEKSViewPolicy`, so they can **look** at the Resources tab but cannot change workloads.
    - **Own account (for example Learner Lab):** students cannot see your cluster. Drive from your screen and ask them to call out the answers.

    Either way: **students create nothing and change nothing.** Console labels move between releases; describe a tab by its purpose if its name differs from what is written here.

!!! prompt "Predict before you click"
    The `portal` Deployment was created with `kubectl create deployment portal --image=nginx:stable --replicas=3`.

    1. How many ReplicaSets will you find for it, and why?
    2. Will the three Pods all land on the same node?

???+ answer "Expected response"
    1. **One.** A Deployment creates one ReplicaSet per version of its Pod template. Nothing has been updated, so there is only one revision.
    2. Probably **spread across both nodes**, since the scheduler spreads replicas where it can, but nothing in that command guarantees it. Check in step 2.

**Step 1: Resources tab, the Deployment and its ReplicaSet.** Open the cluster, then the **Resources** tab, then **Workloads**, then **Deployments**. Select `portal`.

- Students should see 3 desired / 3 ready replicas, the image `nginx:stable`, and the label selector `app=portal`.
- Then open **ReplicaSets** and find the one whose name starts `portal-` followed by a hash.

**Why did that happen?** Why does the ReplicaSet's name contain a hash?

???+ answer "Expected response"
    The hash identifies one version of the Pod template. A new image tag would create a **new** ReplicaSet with a new hash; the old one is kept (scaled to zero) and is what `kubectl rollout undo` switches back to.

**Step 2: Pods, events, conditions and node placement.** Open **Pods** and select one `portal` Pod.

- Find the **node** it runs on and its **IP address**. Compare the IP with the VPC subnet range: on EKS the VPC CNI gives each Pod a real VPC address.
- Find the **conditions** (for example `PodScheduled`, `Initialized`, `ContainersReady`, `Ready`) and the **events** (scheduled, pulling, pulled, created, started).

**Why did that happen?** If one of these Pods were stuck, which part of this page would you read first?

???+ answer "Expected response"
    The **events**. They state in plain English why a Pod cannot be scheduled, cannot pull its image, or fails a probe. This is the console view of `kubectl describe pod`, the first diagnostic in the notes.

**Step 3: Access tab, who may deploy.** Open the **Access** tab and look at the IAM access entries.

- There is an entry for the identity that created the cluster, with a cluster admin access policy, and (same-account case) one for the students' role with `AmazonEKSViewPolicy`.
- An access entry maps an IAM principal into the cluster; the **access policy** attached to it decides what it may do. A CI/CD pipeline that deploys needs its own entry with a policy that allows editing workloads (for example `AmazonEKSEditPolicy`), scoped as narrowly as possible.

**Why did that happen?** Why can you see the Pods but not delete one?

???+ answer "Expected response"
    Your access entry authenticates you (so no `Unauthorized`), but the view policy does not authorise changes (so a change would be `Forbidden`). Recall 3.1: mapping and authorisation are separate steps.

**Step 4: Compute tab, capacity versus requests.** Open **Compute**, then the node group `dso303-u3-nodes`, then one node.

- Note the instance type (`t3.medium`), the node's capacity and allocatable CPU and memory, and the Pods running on it.
- Back on a `portal` Pod, look for its resource requests. The `kubectl create deployment` command set **none**.

**Why did that happen?** What does the scheduler think these Pods cost, and what would go wrong if we deployed fifty more like them?

???+ answer "Expected response"
    With no request, a Pod looks "free" to the scheduler, so it would keep packing them onto the two nodes until they run out of real memory or CPU. Requests are what the scheduler uses to decide which node has room. This is why our manifest in Hands-on B sets them.

**Step 5: Add-ons tab, versions.** Open **Add-ons** and note the version of Amazon VPC CNI, CoreDNS, `kube-proxy` and the EKS Pod Identity Agent.

**Why did that happen?** In an upgrade from one minor version to the next, when do these versions change: before the control plane, between the control plane and the nodes, or after the nodes?

???+ answer "Expected response"
    **After the control plane, never before.** In AWS's best-practices order they come between the control plane and the nodes; the User Guide lists nodes first. Either works, because what matters is that the control plane leads and every add-on version is compatible with it. A control plane upgrade never updates add-ons for you.

**Step 6 (optional, teacher only): look, do not confirm.** Open the **Add node group** wizard from Compute, or the cluster's **Upgrade now** action. Show the fields, then **Cancel**.

!!! danger "Do not confirm either wizard"
    A new node group starts billable EC2 instances. A control plane upgrade can be rolled back only within 7 days, and only after rolling back any nodes already upgraded. Show the screens, then cancel.

**Success criteria**

- [ ] Found the `portal` Deployment, its one ReplicaSet and three Pods
- [ ] Read one Pod's node, IP address, conditions and events
- [ ] Explained the difference between an access entry and its access policy
- [ ] Noticed that the `portal` Pods have no resource requests, and why that matters
- [ ] Stated where add-on upgrades sit in the upgrade order
- [ ] Created nothing and changed nothing

!!! teacher "Transition"
    "That Deployment was created with a one-line imperative command, with no requests, no probes and a tag that can change underneath us. Now let's write the version a team would actually ship."

## Manifests and safe rollouts { data-minutes="15" }

[3.2 Declarative deployment](../unit3/topic2.md#declarative-deployment){ .notes-link target="_blank" }
[3.2 Manifests](../unit3/topic2.md#manifests){ .notes-link target="_blank" }
[3.2 Requests and limits](../unit3/topic2.md#requests-and-limits){ .notes-link target="_blank" }
[3.2 Probes](../unit3/topic2.md#probes){ .notes-link target="_blank" }
[3.2 Helm](../unit3/topic2.md#helm){ .notes-link target="_blank" }
[3.2 Manifests versus Helm](../unit3/topic2.md#manifests-versus-helm){ .notes-link target="_blank" }

### Four things to read in every Deployment manifest

| Field | Rule | Why |
|---|---|---|
| `selector.matchLabels` and template `labels` | Must match | Labels are how the Deployment and the Service find their Pods |
| `image` | A specific, unique tag (`1.4.2`), never `latest` | Every Pod runs the same code, and rollback means something |
| `resources` | Requests from observed usage; memory request = memory limit; often no CPU limit for latency-sensitive services | Requests schedule; limits constrain at runtime |
| Probes | Readiness for traffic, liveness for stuck processes, startup for slow starters | Wrong probe design causes outages |

**Requests schedule, memory limits kill, CPU limits throttle.**

| Setting | Used by | Effect when exceeded |
|---|---|---|
| Request | Scheduler | Not "exceeded": it decides which node has room |
| Memory limit | Runtime | Container killed (`OOMKilled`) |
| CPU limit | Runtime | Container throttled (slowed), not killed |

### Probes, and the one rule to remember

!!! prompt "Analogy: the shop sign and the shopkeeper"
    - **Readiness** is the "Open / Closed" sign on the shop door. If the supplier is late, you turn the sign to Closed. Customers go to another branch.
    - **Liveness** is checking that the shopkeeper is still responsive. If not, you replace the shopkeeper.
    - **Startup** is "the shop is still setting up this morning, do not check the shopkeeper yet".

    If the supplier (the database) is late, you do not replace every shopkeeper in every branch at once.

!!! teacher "Where the analogy breaks"
    A restarted container is not a new, better shopkeeper: it is the same code starting again, which costs start-up time and may hit the same problem. And readiness is evaluated per Pod continuously, not once a day. The rule the analogy is built for is the important part.

!!! prompt "What would break if..."
    ...the portal's **liveness** probe called `/healthz`, and `/healthz` checked that the database answers? The database has a 40-second failover during results week.

???+ answer "Expected response"
    Every replica's liveness probe fails at the same moment, so the kubelet **restarts all of them**. A 40-second database blip becomes a full portal outage, plus a restart storm as Pods come back. **Liveness tests only the process.** Dependency checks belong in **readiness**, which removes a Pod from traffic without restarting it.

### Rolling updates, and who rolls back

When the Pod template changes (for example a new image tag), the Deployment creates a new ReplicaSet and moves Pods across gradually:

| Setting | Meaning | With `replicas: 3`, `maxSurge: 1`, `maxUnavailable: 0` |
|---|---|---|
| `maxSurge` | How many **extra** Pods may exist during the update | At most 4 Pods at once |
| `maxUnavailable` | How many Pods may be **missing** | Never fewer than 3 ready: capacity never drops |

New Pods receive traffic only after their **readiness** probe passes. A broken version therefore **stalls**: the new Pod never becomes ready, and the old Pods keep serving.

!!! warning "Kubernetes does not roll back for you"
    After `progressDeadlineSeconds`, a stalled rollout is marked failed, but **nothing is reverted**. Unlike the ECS deployment circuit breaker ([2.3](../unit2/topic3.md)), you or your pipeline must run `kubectl rollout undo`. And `kubectl apply` returns when the object is **stored**, not when Pods are running, so always follow it with `kubectl rollout status`.

!!! prompt "Predict, then check"
    `replicas: 3`, `maxSurge: 1`, `maxUnavailable: 0`. The new image tag has a typo. After five minutes, how many Pods exist, how many serve traffic, and what does `kubectl get deployment` say?

???+ answer "Expected response"
    **Four Pods**: three old ones `Running` and serving, one new one stuck in `ImagePullBackOff` (not ready, receives no traffic). The Deployment shows 3 ready out of 3 desired, with one updated replica that never becomes available, and after the progress deadline its `Progressing` condition reports a failure. Users see no errors, but the release has not happened, and nothing will fix it automatically. You will produce exactly this in a few minutes.

### Packaging for several environments: Helm or Kustomize

Dev, staging and production differ in replicas, sizes and image versions. Copying YAML per environment makes the copies drift apart.

| | Plain manifests | Kustomize | Helm |
|---|---|---|---|
| Idea | YAML as written | Shared base of plain YAML + small per-environment patches | Chart of templates + `values.yaml`; each environment supplies a small values file |
| Built into `kubectl`? | Yes | Yes (`kubectl apply -k`) | No, separate tool |
| Rollback | Deployment revisions | Deployment revisions | Release revisions (`helm history`, `helm rollback`) |
| Good for | Simple apps, few environments | Same app, a few environment differences | Reusable or third-party software, many variations |

**Reading exercise.** A Helm template fills placeholders from values. Show this on screen:

{% raw %}```yaml
# templates/deployment.yaml (excerpt)
spec:
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      containers:
        - name: web
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```{% endraw %}

```yaml
# values-prod.yaml
replicaCount: 6
image:
  repository: 111122223333.dkr.ecr.us-east-1.amazonaws.com/student-portal
  tag: "1.4.2"
```

**Ask the class:** what does the rendered Deployment contain, and why is `tag` quoted?

???+ answer "Expected response"
    `replicas: 6` and `image: "111122223333.dkr.ecr.us-east-1.amazonaws.com/student-portal:1.4.2"`. The tag is quoted because unquoted number-like values are parsed as numbers: `1.10` would become `1.1`. You can check the rendered output without touching the cluster using `helm template`; deploy with `helm upgrade --install`, which creates a numbered release revision each time.

!!! teacher "Optional demo and pitfalls"
    If you have Helm installed, show `helm template` rendering a chart on your screen; students do not install Helm today. Mention the other two pitfalls from the notes: prefer committed values files over `--set` (which leaves no record), and do not adopt Helm just because it exists.

!!! teacher "Transition"
    "Now you will write a small manifest like this, roll it forward, break it on purpose, and roll it back, on Floci."

## Hands-on B: roll out on Floci { data-minutes="20" }

[3.2 Deploying applications using kubectl and eksctl](../unit3/topic2.md#deploying-applications-using-kubectl-and-eksctl){ .notes-link target="_blank" }
[3.2 Manifests](../unit3/topic2.md#manifests){ .notes-link target="_blank" }
[3.2 Probes](../unit3/topic2.md#probes){ .notes-link target="_blank" }
[3.2 Configuration options](../unit3/topic2.md#configuration-options){ .notes-link target="_blank" }

!!! teacher "Scope and timing"
    Everything happens in a **new namespace `u3t2`**. Never touch namespace `usms` or the Lab 07/08 objects. Lab 07 Step 12 made `usms` the **default namespace** of the Lab 07 context, so every command here passes `-n u3t2` (and the manifest sets `namespace: u3t2`). A forgotten flag would act on the Lab 07 workloads, which is itself a lesson in context. Steps 1 to 6 are the core (about 16 minutes); Step 7 is for fast pairs.

!!! note "Floci Limitation — the Kubernetes half is real, the AWS half is emulated"
    On Path A, Floci answers `aws eks` calls by running a real k3s cluster in local containers; on Path B you created that cluster with `k3d` directly (Lab 07 Step 2). Deployments, ReplicaSets, probes, rolling updates and `rollout undo` behave as upstream Kubernetes does.

    On real EKS, nodes are EC2 instances in your VPC, Pods get VPC IP addresses from the VPC CNI, access entries decide who may run these commands, and kubeconfig fetches a token with `aws eks get-token`. On Floci, nodes are local containers, Pod IPs come from the k3s network, and access entries are not enforced.

    What transfers regardless: the manifest, the commands and the rollout behaviour are identical on EKS. Image pulls need internet access from your Docker host. Students on Path C (neither works) pair with a neighbour or follow the teacher's screen.

**Run from**

```text
aws-floci-course/
```

**Step 0: Start the environment.**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
source configs/course.env
source configs/lab-07.env
./scripts/utilities/whoami.sh
```

`floci-up.sh` starts or resumes Floci under Docker Compose (idempotent). Sourcing `course.env` first sets the profile and endpoint; `lab-07.env` gives `USMS_EKS_CLUSTER` and `USMS_EKS_NAMESPACE`. `whoami.sh` exits 1 unless you are talking to account `000000000000`.

```text
Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Region   : us-east-1
```

> Example output — yours will differ.

**Why?** Why do we never type `floci start` here? (It bypasses Compose and its persistent storage settings; the course starts Floci only through `floci-up.sh`.)

**Step 1: Which cluster, which namespace?**

```bash
kubectl config current-context
kubectl config get-contexts
kubectl config view --minify --output 'jsonpath={..namespace}'; echo
```

`current-context` names the context every `kubectl` command uses. `get-contexts` lists all of them with a `*` on the current one. The last command prints the current context's default namespace.

```text
usms-eks
CURRENT   NAME       CLUSTER                                                    AUTHINFO   NAMESPACE
*         usms-eks   arn:aws:eks:us-east-1:000000000000:cluster/usms-eks-cluster   ...        usms
usms
```

> Example output — yours will differ. On Path B the context is `k3d-usms-eks-cluster`. If the current context is anything other than your Lab 07 cluster, stop and run `kubectl config use-context <your Lab 07 context>`.

**Why?** The default namespace is `usms`. What would `kubectl delete deployment usms-enrolment` do right now, and why does every command below pass `-n u3t2`?

???+ answer "Expected response"
    It would delete a Lab 07 workload, because without `-n` the command acts on the default namespace of the current context. `kubectl` does exactly what you ask, to whichever cluster and namespace are selected. On a real team, the same mistake against a production context is the costliest Kubernetes error there is; give production contexts clearly different names.

**Step 2: Create the practice namespace.**

```bash
kubectl create namespace u3t2
kubectl get namespace u3t2
```

```text
namespace/u3t2 created
NAME   STATUS   AGE
u3t2   Active   2s
```

> Example output — yours will differ.

**Why?** Why a separate namespace instead of just using `usms`? (One `kubectl delete namespace u3t2` removes everything from today, and nothing from today can collide with or damage the Lab 07/08 objects.)

**Step 3: Write the manifest.** The heredoc uses quoted `<< 'EOF'`, so the shell writes the text exactly as typed and expands nothing.

```bash
mkdir -p manifests/u3t2
cat > manifests/u3t2/portal.yaml << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: portal
  namespace: u3t2
  labels:
    app: portal
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 60
  selector:
    matchLabels:
      app: portal
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: portal
    spec:
      containers:
        - name: web
          image: nginx:1.27-alpine
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              memory: 64Mi
          readinessProbe:
            httpGet:
              path: /
              port: 80
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 10
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: portal
  namespace: u3t2
spec:
  type: ClusterIP
  selector:
    app: portal
  ports:
    - port: 80
      targetPort: 80
EOF
grep -n 'image:\|namespace:\|maxSurge\|maxUnavailable\|progressDeadline' manifests/u3t2/portal.yaml
```

Point out each choice: matching labels; a specific tag; memory request = memory limit and a CPU request with no CPU limit; `maxUnavailable: 0`; a short `progressDeadlineSeconds: 60` so the stalled rollout in Step 5 is declared failed within a minute (the default is much longer); and a `ClusterIP` Service, internal only, which creates no AWS load balancer.

**Why?** Both probes call `/` on nginx, which has no database. In the real portal, which probe would check the database connection, if any? (Readiness only, never liveness.)

**Step 4: Apply, then confirm the rollout really finished.**

```bash
kubectl apply -f manifests/u3t2/portal.yaml
kubectl rollout status deployment/portal -n u3t2 --timeout=120s
kubectl get deploy,rs,pods,svc -n u3t2 -o wide
```

`apply` creates or updates the objects and returns as soon as the API server has **stored** them. `rollout status` waits until the new Pods are ready, and exits non-zero if the rollout fails.

```text
deployment.apps/portal created
service/portal created
Waiting for deployment "portal" rollout to finish: 0 of 3 updated replicas are available...
deployment "portal" successfully rolled out
NAME                     READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/portal   3/3     3            3           20s
NAME                                DESIRED   CURRENT   READY   AGE
replicaset.apps/portal-6d4cf56db6   3         3         3       20s
...
```

> Example output — yours will differ.

**Why?** `apply` printed `created` almost instantly. Why is that not evidence that the portal is running?

**Step 5: Roll forward to a new tag, and watch the shape.** Change the manifest, not the live object, then apply. If you have a second terminal, run `kubectl get pods -n u3t2 -w` in it first and watch.

```bash
sed -i.bak 's#image: nginx:1.27-alpine#image: nginx:1.27#' manifests/u3t2/portal.yaml
grep -n 'image:' manifests/u3t2/portal.yaml
kubectl apply -f manifests/u3t2/portal.yaml
kubectl rollout status deployment/portal -n u3t2 --timeout=120s
kubectl get rs -n u3t2
```

`sed -i.bak` edits the file in place on both macOS and Linux and keeps a `.bak` copy. The changed image is a change to the Pod template, so the Deployment creates a new ReplicaSet and moves Pods across one at a time.

```text
deployment.apps/portal configured
Waiting for deployment "portal" rollout to finish: 1 out of 3 new replicas have been updated...
Waiting for deployment "portal" rollout to finish: 2 out of 3 new replicas have been updated...
deployment "portal" successfully rolled out
NAME                DESIRED   CURRENT   READY   AGE
portal-6d4cf56db6   0         0         0       3m
portal-7b9c8d5f4    3         3         3       25s
```

> Example output — yours will differ.

**Why?** In the watch window, what was the largest number of Pods you saw, and the smallest number of ready Pods? Which two settings decided that? (At most 4 Pods, never fewer than 3 ready: `maxSurge: 1`, `maxUnavailable: 0`. The old ReplicaSet is kept at 0 for rollback.)

**Step 6: Break it on purpose, diagnose, and roll back.** You did an `ImagePullBackOff` in Lab 07 Step 19. This time, watch what the **Deployment** reports when its progress deadline passes.

```bash
sed -i.bak 's#image: nginx:1.27$#image: nginx:1.27-typo#' manifests/u3t2/portal.yaml
kubectl apply -f manifests/u3t2/portal.yaml
kubectl rollout status deployment/portal -n u3t2 --timeout=90s; echo "exit code: $?"
kubectl get pods -n u3t2
kubectl get deploy portal -n u3t2 \
  -o jsonpath='{.status.conditions[?(@.type=="Progressing")].reason}'; echo
```

```text
deployment.apps/portal configured
Waiting for deployment "portal" rollout to finish: 1 out of 3 new replicas have been updated...
error: deployment "portal" exceeded its progress deadline
exit code: 1
NAME                      READY   STATUS             RESTARTS   AGE
portal-7b9c8d5f4-4kq2x    1/1     Running            0          4m
portal-7b9c8d5f4-9mzlt    1/1     Running            0          4m
portal-7b9c8d5f4-tx8vw    1/1     Running            0          4m
portal-5f6d9c7b8-wq3nd    0/1     ImagePullBackOff   0          65s
ProgressDeadlineExceeded
```

> Example output — yours will differ. The bad Pod may show `ErrImagePull` before it settles into `ImagePullBackOff`.

Read the cause in the events, then look at the history and undo:

```bash
BAD_POD=$(kubectl get pods -n u3t2 -l app=portal \
  --field-selector=status.phase=Pending -o jsonpath='{.items[0].metadata.name}')
kubectl describe pod "$BAD_POD" -n u3t2 | tail -8

kubectl rollout history deployment/portal -n u3t2
kubectl rollout undo deployment/portal -n u3t2
kubectl rollout status deployment/portal -n u3t2 --timeout=120s
kubectl get deploy portal -n u3t2 -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
kubectl rollout history deployment/portal -n u3t2
```

A Pod that cannot pull its image is still in phase `Pending`, which is why the field selector finds it. `rollout undo` scales the previous ReplicaSet back up; nothing is rebuilt.

```text
  Warning  Failed     40s   kubelet   Failed to pull image "nginx:1.27-typo": ... not found
  Warning  Failed     40s   kubelet   Error: ErrImagePull
  Normal   BackOff    12s   kubelet   Back-off pulling image "nginx:1.27-typo"
REVISION  CHANGE-CAUSE
1         <none>
2         <none>
3         <none>
deployment.apps/portal rolled back
deployment "portal" successfully rolled out
nginx:1.27
REVISION  CHANGE-CAUSE
1         <none>
3         <none>
4         <none>
```

> Example output — yours will differ.

**Why?** The Deployment was marked `ProgressDeadlineExceeded` a minute ago. Why were the three old Pods still running, and why did the cluster not roll back by itself?

???+ answer "Expected response"
    `maxUnavailable: 0` meant no old Pod could be removed until a new one was ready, and the new one never became ready. The progress deadline only **marks** the rollout as failed; Kubernetes never reverts automatically. A pipeline must check the exit code of `rollout status` (here `1`) and run `rollout undo`. Note also that revision 2 disappeared from the history and came back as revision 4: undo re-uses the old ReplicaSet as a new revision.

**Step 7 (fast pairs): the file and the cluster now disagree.**

```bash
grep -n 'image:' manifests/u3t2/portal.yaml
kubectl diff -f manifests/u3t2/portal.yaml
sed -i.bak 's#image: nginx:1.27-typo#image: nginx:1.27#' manifests/u3t2/portal.yaml
kubectl diff -f manifests/u3t2/portal.yaml && echo "file and cluster agree"
```

`kubectl diff` shows what `apply` *would* change, without changing anything.

```text
29:          image: nginx:1.27-typo
...
-        image: nginx:1.27
+        image: nginx:1.27-typo
...
file and cluster agree
```

> Example output — yours will differ.

**Why?** `rollout undo` fixed the cluster but not the manifest. What happens at the next `kubectl apply` if nobody fixes the file? (The broken tag is re-applied and the outage-that-wasn't comes back. In a team, the fix is a commit to the manifest in Git, not a command typed against the cluster.)

**Success criteria**

- [ ] Confirmed the current context and its default namespace before changing anything
- [ ] Created namespace `u3t2` and applied a Deployment with requests, limits and both probes
- [ ] Used `rollout status` after every `apply`
- [ ] Saw a rolling update keep at least 3 ready Pods throughout
- [ ] Produced `ProgressDeadlineExceeded`, read the `ImagePullBackOff` cause in the events, and recovered with `rollout undo`
- [ ] Touched nothing in namespace `usms`

!!! teacher "Compare with the console"
    Ask: "Where in the console would the same story have appeared?" (Resources tab: a second ReplicaSet, one Pod with image-pull events, the Deployment's conditions.) The console is for looking; the manifest in Git is for changing.

## Break { data-minutes="5" .break }

!!! teacher "During the break"
    Leave Step 6's output on screen. Walk round and check that nobody created anything in `usms` (`kubectl get all -n usms` should show only Lab 07/08 objects).

## Recap and clean-up { data-minutes="10" }

[3.2 Summary](../unit3/topic2.md#summary){ .notes-link target="_blank" }
[3.2 Operating It: Performance, Cost and Monitoring](../unit3/topic2.md#operating-it-performance-cost-and-monitoring){ .notes-link target="_blank" }
[3.2 Common mistakes](../unit3/topic2.md#common-mistakes){ .notes-link target="_blank" }

| Key lesson | Where you saw it today |
|---|---|
| Provisioning, packaging and delivery are separate concerns | The three columns from the hook |
| `eksctl` builds the cluster; `kubectl` and Helm run the apps | Tool table; the shared cluster vs your namespace |
| Check the context (and namespace) before every change | Hands-on B Step 1 |
| Requests schedule, memory limits kill, CPU limits throttle | The `portal` Pods with no requests in the console |
| Readiness controls traffic; liveness controls restarts, and never checks the database | The shop-sign analogy |
| `apply` means stored, not running; Kubernetes does not roll back for you | `ProgressDeadlineExceeded`, then `rollout undo` |
| Upgrade the control plane first, then add-ons and nodes | Add-ons tab |

!!! teacher "Left as reading"
    Point students to these notes sections, which the lecture did not cover in depth: GitOps and CI/CD delivery ([Why This Service or Concept Exists](../unit3/topic2.md#why-this-service-or-concept-exists)), the `Recreate` strategy, replica counts and Secrets handling ([Configuration Options](../unit3/topic2.md#configuration-options)), and rollout monitoring and alarms ([Operating It](../unit3/topic2.md#operating-it-performance-cost-and-monitoring)).

!!! teacher "Bridge to 3.3"
    "Today we shipped and rolled back releases without asking what the Pods run on. Next lecture looks underneath: Fargate versus managed node groups, which workload belongs where, and how add-ons, node drains and PodDisruptionBudgets keep an upgrade from taking the portal down."

!!! warning "Some Kubernetes objects create AWS resources"
    On EKS, a `LoadBalancer` Service or an Ingress creates a load balancer, and a PersistentVolumeClaim can create an EBS volume. These can outlive the Kubernetes objects and even the cluster, and keep billing. Delete Services, Ingresses and PVCs **before** deleting a cluster, then check the console. Today we used `ClusterIP` only.

**Ask the class:** what would break, or keep costing money, if the teacher deleted the shared cluster but someone had created a `LoadBalancer` Service on it?

???+ answer "Expected response"
    Nothing would "break", which is the problem: the load balancer would keep running and billing with no cluster behind it. That is why the shared cluster's delete steps check for `LoadBalancer` Services and PVCs first, and then check EC2 Load Balancers and Volumes in the console.

### Clean up now

!!! danger "Read before running any delete command"
    **What will be deleted:** the namespace `u3t2` and everything in it (the `portal` Deployment, its ReplicaSets and Pods, and the `portal` Service).
    **What depends on it:** nothing. Lab 07/08 objects live in namespace `usms` and are untouched.
    **Reversible?** Yes: `manifests/u3t2/portal.yaml` is still on disk; re-create the namespace and apply it again.
    **Effect on later labs:** none. Do **not** delete `usms`, `~/floci-data`, or the Lab 07 cluster.

```bash
kubectl delete namespace u3t2
kubectl get namespace u3t2
kubectl get deploy -n usms
rm -f manifests/u3t2/*.bak
```

```text
namespace "u3t2" deleted
Error from server (NotFound): namespaces "u3t2" not found
NAME             READY   UP-TO-DATE   AVAILABLE   AGE
usms-enrolment   2/2     2            2           9d
...
```

> Example output — yours will differ. `NotFound` is the success signal. The `usms` Deployments must still be there.

Leave Floci running, or pause it with `./scripts/setup/floci-down.sh` if you are finished for the day (state is kept). Never `docker compose down -v`, `docker volume prune` or `rm -rf ~/floci-data`.

**Console:** students created nothing in AWS today. If anyone did create a console resource, they tagged it `Course=DSO303`, `Session=u3t2` with a name starting `dso303-u3t2-<initials>`; delete it now, then check **Resource Groups & Tag Editor**, then **Tag Editor**: Region `us-east-1`, all supported resource types, tag `Session` = `u3t2`. The result must be **empty**.

- [ ] `kubectl get namespace u3t2` returns `NotFound`
- [ ] Namespace `usms` and its Deployments are unchanged
- [ ] Tag Editor search for `Session=u3t2` is empty (only if anything was created)

## Quiz { data-minutes="30" }

!!! quiz "ClassLegend quiz: 3.2 Deploying Applications on Amazon EKS"
    Bank of 122 questions in `private/quizzes/unit3-topic2.questions.md` covering provisioning, packaging and delivery; cluster build order and its failure symptoms; Quick vs Custom configuration and EKS Auto Mode; `eksctl` vs `kubectl` vs Helm; kubeconfig contexts and namespaces; the shared-cluster console walk-through (ReplicaSets, Pod events, access entries, requests, add-on versions); manifests, labels and image tags; requests and limits; readiness, liveness and startup probes; rolling updates, `rollout status`, `ProgressDeadlineExceeded` and `rollout undo`; Helm and Kustomize; upgrade order, version skew, upgrade insights and version rollback; and cleaning up AWS resources. Run as many as fit about 25 minutes, then spend 5 minutes reviewing the most-missed questions.

---

## After class

- [ ] Delete the shared cluster today, following [Unit 3: Shared EKS Cluster, "After class: delete everything"](unit3-shared-eks-cluster.md#after-class-delete-everything): Kubernetes objects that create AWS resources first, then the node group, then the cluster (unless the 3.3 lecture follows immediately and reuses it)
- [ ] **Tag Editor**, class Region, all supported resource types: `Session=u3-shared` is empty after deletion, and `Session=u3t2` is empty
- [ ] Check EC2 Instances, Volumes and Load Balancers and VPC Network interfaces for leftovers, as listed on the shared page
- [ ] Next day: **Billing and Cost Management** shows no ongoing EKS or EC2 charges
- [ ] AWS Academy Learner Lab: **End Lab**
- [ ] Review the most-missed quiz questions and note any concept to revisit at the start of 3.3

---

## Command reference

| Command | Purpose |
|---|---|
| `kubectl config current-context` | Which cluster every command will act on |
| `kubectl config get-contexts` | All contexts, with the current one starred and its default namespace |
| `kubectl config use-context <name>` | Switch to another context |
| `kubectl create namespace u3t2` | Create the practice namespace |
| `kubectl apply -f manifests/u3t2/portal.yaml` | Create or update objects from the file (returns when stored) |
| `kubectl rollout status deployment/portal -n u3t2` | Wait until the rollout really finishes; non-zero exit on failure |
| `kubectl get deploy,rs,pods,svc -n u3t2 -o wide` | Deployments, ReplicaSets, Pods (with node and IP) and Services |
| `kubectl describe pod <name> -n u3t2` | Detailed state and events: the first diagnostic |
| `kubectl rollout history deployment/portal -n u3t2` | List revisions |
| `kubectl rollout undo deployment/portal -n u3t2` | Return to the previous revision |
| `kubectl diff -f manifests/u3t2/portal.yaml` | Show what `apply` would change, without changing anything |
| `kubectl delete namespace u3t2` | Remove everything created today |
| `helm template <release> <chart> -f <values>` | Render a chart locally without touching the cluster (teacher demo only) |

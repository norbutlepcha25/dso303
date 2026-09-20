# Lab 07 - Deploying a Microservices Application on Amazon EKS

*Practical 4 - the same USMS workload, a different control plane*

!!! info "Numbering - read this once"
    Your module descriptor numbers this practical **3**. This course delivers it as **Practical 4**,
    because Practical 2 (Labs 04, 05 and 06) ran to three documents. The laboratory numbering
    below follows the *dependency graph*, not the practical numbering:

    ```text
    Practical 1  ->  Lab 02 (VPC), Lab 03 (EC2)
    Practical 2  ->  Lab 04, Lab 05, Lab 06   (ECS, ALB, service auto scaling)
    Practical 4  ->  Lab 07, Lab 08            (EKS)   <- this practical, descriptor Practical 3
    then         ->  Lab 09 (security), Lab 10 (Lambda), Lab 11-12 (CI/CD), Lab 13 (monitoring)
    ```

    Kubernetes belongs immediately after ECS and its scaling policies, because the whole point of it
    is the comparison. The S3 configuration lab has not been delivered as its own document; Lab 10
    builds the bucket and its notification as part of the Lambda work instead.

---

## 1. Lab Overview

Practical 2 gave USMS a containerised enrolment service. You wrote an immutable task definition,
handed it to a service controller whose entire job was to keep `runningCount` equal to
`desiredCount`, put a load balancer in front of it, and then handed that integer to Application Auto
Scaling. Three laboratories, and by the end the system ran itself.

Every one of those pieces was an **AWS-shaped** piece. `TaskDefinition`, `Service`, `TargetGroup`,
`ScalableTarget` - those nouns exist in Amazon's API and nowhere else. Move that workload to Azure or
to a rack in the Faculty of Engineering and none of it comes with you.

This laboratory rebuilds the same USMS application on **Amazon EKS** - Elastic Kubernetes Service -
where the nouns are `Deployment`, `Service`, `ConfigMap`, `Ingress`, `HorizontalPodAutoscaler`. Those
are **Kubernetes** objects. They are identical on EKS, on Google's GKE, on a k3s cluster running on a
Raspberry Pi under someone's desk, and on the four-node cluster the university might one day run in
Thimphu. EKS's contribution is that it operates the control plane for you and wires the cluster into
IAM, VPC and ELB. The application definition is portable; the plumbing is not.

You will deploy **three microservices**, not one, because the interesting problems in Kubernetes are
the ones that only appear when services have to find each other:

```text
usms-gateway     the front door. Proxies /enrolment/ and /results/ onward by DNS name
usms-enrolment   the endpoint the portal calls when a student registers for a module
usms-results     the endpoint that returns marks for a completed module
```

`usms-gateway` never learns a pod IP address. It talks to `usms-enrolment.usms.svc.cluster.local`,
and the cluster resolves that to whichever pods happen to be healthy at that instant. That sentence is
the reason this lab has three services instead of one.

**The five objects to keep apart.** Students who conflate these lose an afternoon; students who keep
them apart find the rest of Kubernetes obvious:

```text
Pod          one or more containers scheduled together. Cattle. If it dies, it is gone
ReplicaSet   keeps N identical pods alive. You almost never create one by hand
Deployment   owns ReplicaSets, and rolls from one to the next. This is what you write
Service      a stable name and virtual IP in front of a changing set of pods
Node         a machine that runs pods. On EKS, an EC2 instance in a managed node group
```

Compare that with Practical 2's four, and the mapping is close but not exact:

| Practical 2 (ECS)  | This lab (Kubernetes)          | Where they differ |
| --- | --- | --- |
| task definition    | Pod template inside a Deployment | The ECS one is immutable and versioned by the API; the Kubernetes one is a field you edit |
| task              | Pod                            | Nearly the same idea |
| service           | Deployment (+ its ReplicaSet)  | ECS's service both keeps count *and* is the load-balancer target; Kubernetes splits those in two |
| target group      | Service                        | Kubernetes' Service is the stable front, and it needs no load balancer to exist |
| cluster (namespace only) | Cluster (+ Nodes)        | A Fargate cluster held no machines. An EKS cluster holds a control plane and real nodes |

**Time:** roughly 4 hours, including the exercises.

**Where this sits in the course**

```text
Lab 01   IAM ...................... roles, policies, instance profile
Lab 02   VPC ...................... subnets, NAT, route tables, security groups
Lab 03   EC2 ...................... usms-web-01 and usms-db-01
Lab 04   ECS + Fargate ............ cluster, task definition, service
Lab 05   ECS + ALB ................ load balancer, target group, listener
Lab 06   Service Auto Scaling ..... target tracking, step, scheduled
Lab 07   EKS ...................... THIS LAB - cluster, node group, three microservices, service discovery
Lab 08   EKS scaling and exposure . HPA, node group scaling, NodePort, LoadBalancer, Ingress
Lab 09   Security ................. least-privilege review of the IAM and security-group estate
Lab 10   Lambda ................... functions triggered from usms-student-data, S3 built inline
Lab 11   CI/CD (CodePipeline) ..... source and build stages
Lab 12   CI/CD (ECS deploy) ....... the deploy stage that closes the loop
Lab 13   Monitoring ............... CloudWatch and X-Ray
```

!!! warning "Read Section 8 Step 2 before you start building"
    Kubernetes emulation is the least uniform part of Floci. Step 2 makes you **probe** what your
    build actually supports and record the answer, and every later step tells you what to do on each
    of the three support paths. Do not skip it and hope. A student who discovers at Step 14 that
    `aws eks create-cluster` is unimplemented has lost an hour; a student who discovers it at Step 2
    has lost four minutes and continues on Path B with everything else intact.

---

## 2. Learning Objectives

By the end of this laboratory you will be able to:

1. **Explain** the split between an EKS control plane and its data plane, and say precisely which
   half AWS operates and which half you pay for and patch.
2. **Create** an EKS cluster and a managed node group from the AWS CLI, into the VPC and subnets Lab
   2 built, using IAM roles you create for the purpose.
3. **Explain** why an EKS cluster needs two distinct IAM roles, and what breaks if you give the node
   role to the cluster.
4. **Configure** `kubectl` against a cluster using `aws eks update-kubeconfig`, and explain what that
   command wrote and where.
5. **Write** Kubernetes manifests for a Deployment, a Service and a ConfigMap, and apply them
   declaratively.
6. **Deploy** three interdependent microservices into a namespace and **prove** that they discover
   each other by DNS name rather than by address.
7. **Perform** a rolling update and a rollback, and read `kubectl rollout history` to say what
   changed.
8. **Diagnose** a pod that will not start, using `kubectl describe`, `kubectl logs` and the event
   stream, and name the three most common causes.
9. **Distinguish** a ConfigMap from a Secret, and state accurately what a Kubernetes Secret does and
   does not protect you against.
10. **Compare** the Kubernetes object model with the ECS object model of Practical 2, in both
    directions, and justify a choice between them for a given workload.
11. **Prove** that the cluster and its workloads survive a restart of the emulator, by re-deriving
    every identifier from the API rather than from a shell variable.

---

## 3. Prerequisites

### 3.1 Completed laboratories

- **Lab 01** - IAM. You need `usms-developer-role` and the `USMSStudentDataReadWrite` policy.
- **Lab 02** - VPC. You need all four subnets and the VPC ID. `USMS_PRIVATE_SUBNET_B` was Lab 2
  Exercise 5 and `USMS_PUBLIC_SUBNET_B` was its Step 11 "Your turn" task; **both are required here**,
  because EKS refuses a cluster confined to a single Availability Zone.
- **Lab 03** - EC2. Not consumed directly, but its `verify` script must still pass.
- **Lab 04** - ECS. Section 12 compares against it throughout, and Step 20 asks you to write the
  comparison down.

If `USMS_PRIVATE_SUBNET_B` or `USMS_PUBLIC_SUBNET_B` is missing from `configs/lab-02.env`, create it
now from Lab 2's Exercise 5 before going further. Step 8 will fail with an unhelpful error otherwise.

### 3.2 Tools

| Tool | Needed for | Check |
| --- | --- | --- |
| Docker Engine or Docker Desktop | Floci, and the Kubernetes node containers | `docker version` |
| AWS CLI v2 | Everything in Sections 8.1 to 8.3 | `aws --version` |
| `kubectl` | Everything from Step 11 onward | `kubectl version --client` |
| `k3d` | Only on support Path B | `k3d version` |
| `python3` | Validating JSON, as in earlier labs | `python3 --version` |
| `jq` (optional) | Reading manifests; every command below has a `--query` alternative | `jq --version` |

`kubectl` is the one genuinely new tool. Install it before the session, not during it:

=== "macOS"

    ```bash
    brew install kubectl
    kubectl version --client --output=yaml
    ```

=== "Linux"

    ```bash
    curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    sudo install -o root -g root -m 0755 /tmp/kubectl /usr/local/bin/kubectl
    kubectl version --client --output=yaml
    ```

=== "Windows (WSL2)"

    ```bash
    # Run inside your WSL2 Ubuntu shell, not PowerShell.
    curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    sudo install -o root -g root -m 0755 /tmp/kubectl /usr/local/bin/kubectl
    kubectl version --client --output=yaml
    ```

`kubectl version --client` must print a client version and **must not** hang. If it hangs, you have
omitted `--client` and it is trying to reach a cluster that does not exist yet.

### 3.3 Knowledge assumed

Everything in §6.4 of the course contract, plus, from Practical 2: the difference between an
immutable blueprint and a running instance of it; why a controller exists; and what a rolling
deployment does. This lab does not re-teach those, it renames them.

### 3.4 Disk and memory

A Kubernetes node is a real container running a real kubelet. Budget **2 GB of free RAM** and about
**3 GB of disk** beyond what Practical 2 already uses. On Docker Desktop, check
Settings, Resources, Memory before you begin. A cluster that cannot get memory does not fail loudly;
it produces pods stuck in `Pending` with an event you have to go looking for, which is Troubleshooting
entry 4.

---

## 4. Connection to Previous Labs

### 4.1 Current Environment

```text
Created in previous labs:
- Lab 01: IAM foundation - 3 groups, 3 users, 3 roles, 5 policies, 1 instance profile
- Lab 01: usms-developer-role, assumed before every build since Lab 02
- Lab 01: USMSStudentDataReadWrite - still naming a bucket that does not exist
- Lab 02: usms-vpc 10.0.0.0/16; public-a/-b, private-a/-b; usms-igw, usms-nat,
          usms-private-rt, usms-public-rt, usms-s3-endpoint
- Lab 03: usms-web-01, usms-db-01, usms-web-golden AMI
- Lab 04: usms-ecs-cluster, usms-enrolment-svc on usms-enrolment:2,
           usms-ecs-exec-role, usms-ecs-task-role, /usms/ecs/enrolment
- Lab 05: usms-enrolment-alb, usms-enrolment-tg, listener HTTP:80, usms-alb-sg
- Lab 06: scalable target min 2 max 10, two target-tracking policies,
           one step policy, two scheduled actions

Created in this lab:
- usms-eks-cluster-role      IAM role, trusts eks.amazonaws.com
- usms-eks-node-role         IAM role, trusts ec2.amazonaws.com
- USMSEKSClusterPolicy       local stand-in for AmazonEKSClusterPolicy
- USMSEKSNodePolicy          local stand-in for the three AWS managed node policies
- usms-eks-cluster-sg        security group for the control-plane endpoint, in Lab 02's VPC
- usms-eks-cluster           the cluster, across all four Lab 02 subnets
- usms-eks-nodes             managed node group, private subnets only, desired 2
- namespace usms             everything below lives here
- usms-enrolment             Deployment (2 replicas) + ClusterIP Service + ConfigMap
- usms-results               Deployment (2 replicas) + ClusterIP Service + ConfigMap
- usms-gateway               Deployment (1 replica)  + ClusterIP Service + ConfigMap
- usms-app-config            ConfigMap shared by all three
- usms-enrolment-secret      Secret - and an honest account of what it protects

Required for future labs:
- usms-eks-cluster        -> Lab 08 scales it and exposes it; every kubectl command needs it
- usms-eks-nodes          -> Lab 08 changes its scaling config from the AWS side
- _lb_ports_ cluster tag  -> Lab 08 Step 15 cannot expose a LoadBalancer Service without it
- namespace usms          -> Lab 08 works entirely inside it
- usms-enrolment          -> Lab 08 attaches a HorizontalPodAutoscaler to this Deployment
- usms-gateway            -> Lab 08 turns this Service into a LoadBalancer and an Ingress
- resource requests       -> set in this lab's Step 13, because an HPA without them reads nothing
```

### 4.2 What this lab genuinely reuses, and where

The course contract asks that a lab consume earlier resources rather than build a parallel universe.
Five places, and each is a real dependency rather than a gesture:

| From | Used in | Consequence if it is missing |
| --- | --- | --- |
| Lab 01 `usms-developer-role` | Step 8, assumed before creating the cluster | The build runs as the root identity, and the lab stops modelling least privilege |
| Lab 01 `USMSStudentDataReadWrite` | Step 7, attached to `usms-eks-node-role` | The node role carries no route to the transcript bucket, and Lab 10 has one fewer chain to resolve |
| Lab 02 all four subnets | Step 8's `resourcesVpcConfig`, Step 10's `--subnets` | `InvalidParameterException` - EKS requires subnets in at least two Availability Zones |
| Lab 02 `usms-vpc` | Step 6, the cluster security group is created in it | The security group lands in the default VPC and the cluster cannot use it |
| Lab 04 `usms-ecs-cluster` | Section 12 and Step 20 | Nothing breaks; you simply lose the comparison, which is most of the point |

The sentence worth saying out loud, and the one Step 7 will ask you to write down: **Lab 1's
`USMSStudentDataReadWrite` is now attached to a third role.** It was written for an EC2 instance
profile, reused unchanged for a Fargate task role in Lab 04, and is reused unchanged again here for
an EKS node role. The policy has never been edited. One document, three completely different compute
models, and it still names a bucket that does not exist. Lab 10 creates that bucket, and three chains
resolve at once.

---

## 5. What We Are Building

A three-tier microservice application, deployed declaratively, inside a Kubernetes cluster that lives
in the network you built in Lab 2.

```text
A student clicks "Register for this module" in the USMS portal.

   the request arrives at        usms-gateway     (1 pod,  nginx reverse proxy)
   which forwards /enrolment/ to usms-enrolment   (2 pods, returns JSON with its own pod name)
   and forwards   /results/   to usms-results     (2 pods, returns JSON with its own pod name)

Nothing in usms-gateway's configuration contains an IP address.
It contains two DNS names, and the cluster keeps them pointing at healthy pods.
```

Concretely, by the end of Section 8 you will have created:

- Two IAM roles and two IAM policies, plus one security group, all in Lab 02's VPC.
- One EKS cluster and one managed node group with two nodes.
- One namespace, three Deployments, three Services, four ConfigMaps and one Secret.
- Two task-definition-shaped lessons that Kubernetes solves differently from ECS: rolling updates,
  and rollback.
- One persistence proof, in the shape the course has used since Lab 1: create, perturb, read back.

What you will **not** build here, because it is Lab 08's job: any autoscaler, any NodePort, any
LoadBalancer, and any Ingress. Everything in this lab is reachable only from inside the cluster. That
is deliberate - it forces you to prove service discovery from inside, which is where it actually
matters, before you put a front door on it.

---

## 6. Architecture

```text
                              YOUR MACHINE
   +---------------------------------------------------------------------------+
   |                                                                           |
   |   aws CLI  ---------------->  Floci (container "floci", port 4566)        |
   |                                    |                                      |
   |                                    |  creates and manages                 |
   |                                    v                                      |
   |   kubectl  ---------------->  EKS control plane container                 |
   |            https://localhost:6443       (k3s API server)                  |
   |                                    |                                      |
   |                                    |  schedules pods onto                 |
   |                                    v                                      |
   |                       +-----------------------------+                     |
   |                       |   usms-eks-nodes  (2 nodes) |                     |
   |                       +-----------------------------+                     |
   +---------------------------------------------------------------------------+

                      INSIDE THE CLUSTER - namespace "usms"

   +----------------------------------------------------------------------------+
   |                                                                            |
   |   Service  usms-gateway     ClusterIP 10.43.x.x   port 80                  |
   |      |                                                                     |
   |      +--> Deployment usms-gateway    1 replica                             |
   |             pod  nginx  ---- proxy_pass ----+                              |
   |                                             |                              |
   |            /enrolment/  -> usms-enrolment.usms.svc.cluster.local:80        |
   |            /results/    -> usms-results.usms.svc.cluster.local:80          |
   |                                             |                              |
   |      +--------------------------------------+------------------+           |
   |      |                                                         |           |
   |      v                                                         v           |
   |   Service usms-enrolment  ClusterIP                Service usms-results    |
   |      |                                                         |           |
   |      +--> Deployment usms-enrolment 2 replicas      +--> Deployment 2      |
   |             pod-a  nginx  requests cpu=50m                pod-a  nginx     |
   |             pod-b  nginx  requests cpu=50m                pod-b  nginx     |
   |                                                                            |
   |   ConfigMap usms-app-config          shared: environment, campus, version   |
   |   ConfigMap usms-enrolment-conf      nginx template for the enrolment pods  |
   |   ConfigMap usms-results-conf        nginx template for the results pods    |
   |   ConfigMap usms-gateway-conf        the proxy rules above                  |
   |   Secret    usms-enrolment-secret    a token. Base64, NOT encrypted         |
   |                                                                            |
   +----------------------------------------------------------------------------+

                        AWS-SIDE OBJECTS, IN LAB 02'S VPC

   usms-vpc 10.0.0.0/16
     public-a / public-b     -> in the cluster's resourcesVpcConfig (endpoint reachability)
     private-a / private-b   -> where the node group's instances are placed
     usms-eks-cluster-sg     -> attached to the cluster endpoint

   usms-eks-cluster-role  trusts eks.amazonaws.com   -> USMSEKSClusterPolicy
   usms-eks-node-role     trusts ec2.amazonaws.com   -> USMSEKSNodePolicy
                                                     -> USMSStudentDataReadWrite  (Lab 01, unchanged)
```

Two things in that picture are worth pausing on.

**`kubectl` does not talk to Floci.** It talks to the Kubernetes API server on port 6443. The AWS CLI
talks to Floci on 4566. They are two different protocols to two different endpoints, and the only
thing connecting them is that one created the other. On real AWS this is exactly the same: `aws eks`
calls reach an AWS endpoint, `kubectl` calls reach your cluster's own endpoint, and an IAM identity
is mapped into the cluster's authorisation system so the same person can use both.

**Nothing in the cluster half of the diagram mentions AWS.** Deployments, Services, ConfigMaps and
namespaces would be byte-identical on any conformant Kubernetes. That is the portability claim in
Section 1, drawn.

---

## 7. Directory Structure

This lab adds the following. It restructures nothing, and it needs one new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-07-eks/
│       ├── README.md                          # this document
│       └── exercises.md                       # Section 13
├── manifests/                                 # NEW TOP-LEVEL FOLDER - see the note below
│   └── lab-07/
│       ├── 00-namespace.yaml
│       ├── 10-configmap-app.yaml
│       ├── 20-enrolment.yaml
│       ├── 30-results.yaml
│       ├── 40-gateway.yaml
│       └── 50-secret.yaml
├── policies/
│   ├── trust-eks-cluster.json                 # NEW - trust policy for eks.amazonaws.com
│   ├── trust-eks-node.json                    # NEW - trust policy for ec2.amazonaws.com
│   ├── usms-eks-cluster-policy.json           # NEW - USMSEKSClusterPolicy document
│   └── usms-eks-node-policy.json              # NEW - USMSEKSNodePolicy document
├── templates/
│   ├── lab-07-create-cluster.json            # NEW - --cli-input-json body for create-cluster
│   └── lab-07-create-nodegroup.json          # NEW - --cli-input-json body for create-nodegroup
├── configs/
│   └── lab-07.env                            # NEW
├── scripts/
│   ├── utilities/
│   │   ├── verify-lab-07.sh                  # NEW - Section 9
│   │   └── eks-support-probe.sh               # NEW - Step 2
│   └── cleanup/
│       └── lab-07-cleanup.sh                 # NEW - end of course only
└── outputs/
    └── lab-07-*.json / *.txt                 # command output, git-ignored
```

!!! info "Why `manifests/` is a new top-level folder, and why that is justified"
    The course contract says a lab adds to the folder structure rather than restructuring it, and
    that a new top-level folder must be justified in one sentence. Here it is: **Kubernetes manifests
    are neither AWS API request bodies nor IAM documents**, so `templates/` and `policies/` are both
    wrong homes for them, and mixing YAML that `kubectl apply` consumes with JSON that the AWS CLI
    consumes would put two different tools' inputs in one directory. Everything else in this lab
    lands in the folders that already exist.

Note the numeric prefixes on the manifest filenames. `kubectl apply -f manifests/lab-07/` applies
every file in a directory **in lexical order**, so `00-`, `10-`, `20-` is not decoration: it is how
you guarantee the namespace exists before anything is created inside it.

Create the two new folders now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-07-eks manifests/lab-07
ls -d labs/* manifests/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs-fargate
labs/lab-05-ecs-alb  labs/lab-06-ecs-autoscaling  labs/lab-07-eks
manifests/lab-07
```

---
## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Every path below (`configs/...`, `policies/...`, `manifests/...`, `scripts/...`) is relative to
    that directory. If a command reports `No such file or directory`, check `pwd` first.

    Two habits from Practical 2, restated because this lab creates a dozen things whose identifiers
    matter. **Capture every identifier into a shell variable** with `$(...)`, `--query` and
    `--output text`; never copy one by hand. And remember that **shell variables die with the
    terminal**, which is why Step 23 writes them all to `configs/lab-07.env`.

    One habit that is new here: `kubectl` has its own idea of "where am I", called a **context**, and
    it is stored in `~/.kube/config` - outside this repository, and therefore outside Git. Step 11
    sets it. If a `kubectl` command in a later step behaves strangely, `kubectl config
    current-context` is the first thing to check, exactly as `pwd` is for a shell.

---

### Step 1 - Start the environment and confirm the ground you are standing on

**Purpose**

Nothing in this lab is worth starting if Lab 2's subnets are missing or Floci is running in memory
mode. Four minutes here saves an hour at Step 8.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04.env

./scripts/utilities/whoami.sh
./scripts/utilities/floci-storage-check.sh
```

**What the command does**

`floci-up.sh` starts or resumes the Compose service. It is idempotent - running it when Floci is
already up is harmless, and it refuses to adopt a container that was not created by Compose. This is
the only supported way to start Floci in this course; `floci start` is forbidden, for the reason in
§5.5 of the course contract.

Sourcing five env files in order is not superstition. Each later file may refer to values from an
earlier one, and `course.env` must come first because it sets `AWS_PROFILE` and `COURSE_ROOT`.

**Expected result**

```text
Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Region   : us-east-1
```

> Example output - your `Identity` line may differ if you left an assumed role in the environment.

If `Account` is anything other than `000000000000`, `whoami.sh` exits 1 and you are pointed at
something that is not your local emulator. Stop and fix that before continuing.

**Verify**

```bash
./scripts/utilities/verify-lab-02.sh | tail -2
./scripts/utilities/verify-lab-04.sh | tail -2

echo "public-a=$USMS_PUBLIC_SUBNET_A"
echo "public-b=$USMS_PUBLIC_SUBNET_B"
echo "private-a=$USMS_PRIVATE_SUBNET_A"
echo "private-b=$USMS_PRIVATE_SUBNET_B"
```

**What to look for:** `FAIL=0` from `verify-lab-02.sh`, and four subnet IDs - **four**, all beginning
`subnet-`, none of them the word `None` and none of them empty.

If `USMS_PUBLIC_SUBNET_B` or `USMS_PRIVATE_SUBNET_B` is empty, do Lab 2's Step 11 "Your turn" task
and Lab 2 Exercise 5 now, then regenerate `configs/lab-02.env` from Lab 2 Step 24. EKS will not
create a cluster whose subnets all sit in one Availability Zone, and the error it returns names
neither the subnet nor the zone.

`verify-lab-04.sh` reporting `FAIL=1` is expected if you never did Lab 05 Exercise 2 - Lab 05 says
so. Any other failure is real.

---

### Step 2 - Probe what your build actually supports, and record the answer

**Purpose**

This is the step described in the Section 1 warning. Kubernetes emulation is the least uniform part
of Floci, and there are three plausible states your build can be in. Every later step tells you what
to do on each path, but only if you know which one you are on.

**Concept first - what "EKS on an emulator" can possibly mean**

A real EKS cluster is a fleet of API servers, an etcd cluster and a scheduler, all run by AWS in an
account you cannot see, plus EC2 instances in *your* account running kubelets. An emulator cannot
reproduce that, and does not try. What Floci does instead is start a genuine, small Kubernetes
distribution in Docker containers on your machine - k3s, wrapped by k3d - and then answer
`aws eks ...` calls by manipulating it.

That has a consequence worth understanding before you meet it: **the Kubernetes half of this lab is
completely real.** Deployments really schedule, DNS really resolves, a rolling update really rolls.
What is emulated is the *AWS-facing* half: the `eks` API, the node group abstraction, the IAM
integration. So when a step in this lab fails, ask first which half it belonged to. That question
answers most of Section 11.

The three paths:

| Path | What it means | How the lab proceeds |
| --- | --- | --- |
| **A** | `aws eks create-cluster` works and starts a cluster | Everything as written. The AWS half and the Kubernetes half both run |
| **B** | The `eks` API is absent or refuses; `k3d` is available | You create the cluster with `k3d` directly in Step 8B. Steps 6, 7 and 22 still create the IAM objects, so the ledger and Lab 08 still hold. Steps 10 and 22 note what is unavailable |
| **C** | Neither works | You cannot run Steps 8 to 21. Do Section 8.4's paper path: write every manifest, validate them client-side, and answer Section 15 in full. This is a genuine outcome, not a failure - record it |

**Run from**

```text
aws-floci-course/
```

**Command - write the probe**

````markdown
{% raw %}```bash
cat > scripts/utilities/eks-support-probe.sh << 'EOF'
#!/usr/bin/env bash
# Decide which EKS support path this build gives us. Read-only. Never exits non-zero.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"

echo "== Floci =="
docker container inspect "$FLOCI_CONTAINER_NAME" \
  --format 'running={{.State.Running}}' 2>/dev/null || echo "running=NO-SUCH-CONTAINER"

echo
echo "== Does the eks API answer at all? =="
if aws eks list-clusters --output text >/dev/null 2>&1; then
  echo "eks list-clusters      : OK"
  EKS_API=yes
else
  echo "eks list-clusters      : FAILED"
  EKS_API=no
fi

echo
echo "== Local tooling =="
for t in kubectl k3d docker python3; do
  if command -v "$t" >/dev/null 2>&1; then
    printf "  %-8s : %s\n" "$t" "$(command -v "$t")"
  else
    printf "  %-8s : MISSING\n" "$t"
  fi
done

echo
echo "== Verdict =="
if [ "$EKS_API" = yes ] && command -v kubectl >/dev/null 2>&1; then
  echo "PATH A  - use aws eks throughout"
elif command -v k3d >/dev/null 2>&1 && command -v kubectl >/dev/null 2>&1; then
  echo "PATH B  - create the cluster with k3d (Step 8B); IAM steps still apply"
else
  echo "PATH C  - manifests and reasoning only (Section 8.4)"
fi
EOF

chmod +x scripts/utilities/eks-support-probe.sh
./scripts/utilities/eks-support-probe.sh | tee outputs/lab-07-support-probe.txt
```{% endraw %}
````

**What the command does**

Three read-only questions and a verdict. `aws eks list-clusters` is chosen deliberately as the probe:
it is the cheapest `eks` call there is, it creates nothing, and if the service is unimplemented it
fails immediately rather than after a two-minute timeout. Note that a *failure* here is information,
not an error - which is why the script sets `set -uo pipefail` and not `set -e`. A script that aborts
on the first failing command cannot report on failures.

`tee` writes the verdict to `outputs/` while still showing it to you, so the answer survives the
terminal.

**Expected result**

```text
== Floci ==
running=true

== Does the eks API answer at all? ==
eks list-clusters      : OK

== Local tooling ==
  kubectl  : /usr/local/bin/kubectl
  k3d      : MISSING
  docker   : /usr/bin/docker
  python3  : /usr/bin/python3

== Verdict ==
PATH A  - use aws eks throughout
```

> Example output - your paths will differ, and `k3d` being `MISSING` is fine on Path A.

**Verify**

Write the verdict into your notes, because Section 14 asks for it and Section 12 depends on it:

```bash
mkdir -p notes
{
  echo "## Lab 07 support path"
  echo "Probed on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  grep -A1 '== Verdict ==' outputs/lab-07-support-probe.txt | tail -1
} >> notes/lab-07-notes.md

tail -3 notes/lab-07-notes.md
```

**What to look for:** a line beginning `PATH A`, `PATH B` or `PATH C` in
`notes/lab-07-notes.md`. From here on, wherever a step is labelled **Path A** or **Path B**, do the
one that matches.

**Checkpoint 1**

```text
aws-floci-course/
 ├── Floci running under Compose, storage mode hybrid
 ├── configs/{course,lab-01,lab-02,lab-03,lab-04}.env  all sourced
 ├── verify-lab-02.sh  FAIL=0
 ├── four subnet IDs, two AZs
 ├── kubectl installed
 └── notes/lab-07-notes.md records PATH A, B or C
```

---

### Step 3 - Understand the control plane / data plane split before you create either

**Purpose**

Every command from Step 6 onward is one of two things: something you do to the control plane, or
something you do to the data plane. If you cannot say which, you cannot debug the result.

**Run from**

Nothing to run. Read this, then answer the question at the end in `notes/lab-07-notes.md`.

**Concept - the line AWS draws**

```text
        CONTROL PLANE                    |            DATA PLANE
        AWS runs it. You cannot log in.  |            You run it. You can log in.
   ----------------------------------------------------------------------------
        kube-apiserver                   |   EC2 instances in YOUR account
        etcd (the cluster's database)    |   the kubelet on each of them
        kube-scheduler                   |   the container runtime
        kube-controller-manager          |   your pods
        cloud-controller-manager         |   the CNI plugin that gives pods VPC addresses
   ----------------------------------------------------------------------------
        billed per cluster per hour      |   billed per instance, as ordinary EC2
        patched by AWS                   |   patched by YOU
        one IAM role: cluster role       |   one IAM role: node role
```

Three consequences follow directly from that table, and all three appear later in this lab:

1. **An EKS cluster with no node group can be `ACTIVE` and still run nothing.** The control plane is
   healthy; there is simply nowhere to put a pod. This is Step 10's reason for existing, and
   Troubleshooting entry 4's most common cause.
2. **Two IAM roles, not one.** The cluster role is what the AWS-run control plane assumes in order to
   manage network interfaces and load balancers on your behalf. The node role is what your EC2
   instances assume in order to join the cluster and pull images. They trust different principals and
   they are never interchangeable. Steps 6 and 7 build them separately for exactly this reason.
3. **Upgrading is two operations.** `aws eks update-cluster-version` moves the control plane;
   `aws eks update-nodegroup-version` moves the nodes. The control plane may run one or two minor
   versions ahead of the nodes, never behind. Nothing in this lab performs an upgrade, but the
   two-command shape is the thing to remember.

**Compare with Practical 2.** On ECS with Fargate, the equivalent table has almost nothing in the
right-hand column: AWS runs the scheduler *and* the machines, and your only IAM roles are the
execution role and the task role. That is exactly what made Lab 04 short. EKS gives you a data plane
back, and everything in this lab that is longer than its ECS equivalent is the price of that.

✏️ **Your turn**

In `notes/lab-07-notes.md`, answer in two or three sentences: *a colleague says "EKS is just ECS
with different names". Name one thing in the table above that makes that statement false, and one
thing that makes it nearly true.*

```text
Expected result:
Two short paragraphs in your notes. No commands, no output. Section 15 Question 1
asks a harder version of this, so a good answer here is worth the four minutes.
```

---

### Step 4 - Write the two trust policies

**Purpose**

A role is defined by two documents: who may assume it (the trust policy) and what it may then do (the
permissions policies). This step writes the first of each pair, and it is where the two-roles point
from Step 3 becomes concrete rather than abstract.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > policies/trust-eks-cluster.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EKSControlPlaneAssumesThisRole",
      "Effect": "Allow",
      "Principal": { "Service": "eks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

cat > policies/trust-eks-node.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2InstancesAssumeThisRole",
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

python3 -m json.tool policies/trust-eks-cluster.json > /dev/null && echo "cluster trust: valid JSON"
python3 -m json.tool policies/trust-eks-node.json    > /dev/null && echo "node trust   : valid JSON"
```

**What the command does**

**The heredoc is quoted** - `<< 'EOF'`, not `<< EOF`. Every policy document in this course uses the
quoted form, because a policy may legitimately contain `$` characters (`${aws:username}` in Lab 1's
inline policy is the standing example) and an unquoted heredoc would let the shell eat them. Step 8
uses the *unquoted* form for a JSON file, deliberately, and says why. Getting this backwards is
silent: the file is written, the command succeeds, and the document is wrong.

The two `Principal` values are the whole lesson. `eks.amazonaws.com` is the EKS service itself -
the AWS-run control plane, assuming a role in your account to do work on your behalf. `ec2.amazonaws.com`
is the EC2 service, assuming a role on behalf of an instance. Compare with `policies/trust-ec2.json`
from Lab 1, which is byte-identical to `trust-eks-node.json`: a node is an EC2 instance, so the trust
policy for a node role is the trust policy for any instance role. We write it again under a new name
rather than reusing the file, because a reader opening `policies/` should be able to see which role
each document belongs to without cross-referencing.

**Expected result**

```text
cluster trust: valid JSON
node trust   : valid JSON
```

**Verify**

```bash
python3 -c "
import json
for f in ('policies/trust-eks-cluster.json','policies/trust-eks-node.json'):
    d = json.load(open(f))
    s = d['Statement'][0]
    print(f, '->', s['Principal']['Service'], s['Action'])
"
```

**What to look for:** two lines, naming `eks.amazonaws.com` and `ec2.amazonaws.com` respectively,
each with `sts:AssumeRole`. If both say the same service, you have copied one heredoc twice - a
mistake that will not surface until Step 10 fails with a message about node registration.

---

### Step 5 - Write the two permissions policies

**Purpose**

On real AWS you would attach AWS managed policies here and write nothing. Floci may not carry them,
so this step writes local equivalents - and in doing so, shows you what those managed policies
actually contain, which is more educational than attaching an ARN you have never read.

**Concept first - what the AWS managed policies are for**

| Real AWS managed policy | Attached to | What it lets that principal do |
| --- | --- | --- |
| `AmazonEKSClusterPolicy` | the cluster role | Manage ENIs, security groups and load balancers in your VPC on the cluster's behalf |
| `AmazonEKSWorkerNodePolicy` | the node role | Let a kubelet describe the cluster and register itself |
| `AmazonEKS_CNI_Policy` | the node role | Let the VPC CNI plugin attach ENIs and assign secondary addresses to pods |
| `AmazonEC2ContainerRegistryReadOnly` | the node role | Pull images from ECR |

That third row is the interesting one. On EKS, **a pod gets a real VPC IP address**, from your
subnet's range, on a secondary ENI attached to the node. That is why EKS pods can be targets in an
ALB target group with target-type `ip` - exactly the target type Lab 05 used for Fargate tasks - and
it is why a node's instance type caps how many pods it can run. Kubernetes elsewhere usually gives
pods addresses from an overlay network that the VPC knows nothing about.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write the documents**

```bash
cat > policies/usms-eks-cluster-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageNetworkInterfacesForTheClusterEndpoint",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DeleteNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeInstances",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ManageLoadBalancersForServicesOfTypeLoadBalancer",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:Describe*",
        "elasticloadbalancing:CreateLoadBalancer",
        "elasticloadbalancing:CreateTargetGroup",
        "elasticloadbalancing:CreateListener",
        "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
        "elasticloadbalancing:AddTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyEverythingOutsideTheCourseRegion",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": { "aws:RequestedRegion": "us-east-1" }
      }
    }
  ]
}
EOF

cat > policies/usms-eks-node-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KubeletDescribesTheClusterAndRegisters",
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:DescribeNodegroup",
        "eks:ListClusters"
      ],
      "Resource": "*"
    },
    {
      "Sid": "VpcCniAttachesInterfacesAndAssignsPodAddresses",
      "Effect": "Allow",
      "Action": [
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses",
        "ec2:AttachNetworkInterface",
        "ec2:DetachNetworkInterface",
        "ec2:CreateNetworkInterface",
        "ec2:DeleteNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeInstances",
        "ec2:DescribeSubnets",
        "ec2:DescribeTags",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PullImagesFromEcr",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "WriteContainerLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:us-east-1:000000000000:log-group:/usms/eks/*"
    },
    {
      "Sid": "DenyEverythingOutsideTheCourseRegion",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": { "aws:RequestedRegion": "us-east-1" }
      }
    }
  ]
}
EOF

for f in policies/usms-eks-cluster-policy.json policies/usms-eks-node-policy.json; do
  python3 -m json.tool "$f" > /dev/null && echo "$f : valid JSON"
done
```

**What the command does**

Read the `Resource` fields, because they are not uniform and the difference is the lesson.

Most statements here use `"Resource": "*"`. That is not laziness - the EC2 network actions genuinely
cannot be scoped in advance, because the ENIs they operate on do not exist until the CNI plugin
creates them, and their ARNs are unknowable at the time you write the policy. AWS's own
`AmazonEKS_CNI_Policy` has the same shape for the same reason. This is the honest case for a wildcard
resource, and it is worth being able to recognise it, because most wildcards are not this.

The `WriteContainerLogs` statement is the counter-example. Its resource is
`arn:aws:logs:us-east-1:000000000000:log-group:/usms/eks/*` - one log-group prefix and no other.
Compare with Lab 04's `USMSECSTaskExecution`, which scoped `logs` to `/usms/ecs/enrolment` for the
same reason. When a resource ARN *is* knowable, name it.

The trailing `Deny` with `aws:RequestedRegion` mirrors `USMSDeveloperBase` from Lab 1. An explicit
`Deny` always wins over any `Allow`, anywhere, including one in a different policy - which is what
makes it the right tool for a guardrail and the wrong tool for ordinary permission-granting.

!!! note "Floci Limitation - policies are stored, not enforced"
    Floci accepts any non-empty credentials and, by default, does not authorize requests against your
    IAM policies. Every statement above is stored faithfully and returned faithfully by
    `aws iam get-policy-version`, and none of it will stop a single API call.

    On real AWS, an EKS cluster whose role lacks `ec2:CreateNetworkInterface` fails to create at all,
    and a node whose role lacks `eks:DescribeCluster` joins and then never becomes `Ready`.

    Judge these documents by reading them, not by whether a command succeeded. That instruction has
    applied since Lab 1 and it applies to every policy in this lab.

**Expected result**

```text
policies/usms-eks-cluster-policy.json : valid JSON
policies/usms-eks-node-policy.json : valid JSON
```

**Verify**

```bash
python3 -c "
import json
for f in ('policies/usms-eks-cluster-policy.json','policies/usms-eks-node-policy.json'):
    d = json.load(open(f))
    print(f)
    for s in d['Statement']:
        n = len(s['Action']) if isinstance(s['Action'], list) else 1
        print('   %-9s %-2d action(s)  %s' % (s['Effect'], n, s['Sid']))
"
```

**What to look for:** the cluster policy shows three statements, the last one `Deny`; the node policy
shows five, the last one `Deny`. If a `Deny` is not last in the printed order it still works - order
is irrelevant to IAM evaluation - but keeping guardrails last is a readability convention worth
holding to.

---

### Step 6 - Create the cluster role and the cluster security group

**Purpose**

The control plane needs an identity in your account, and an endpoint needs a firewall. Both live in
resources Lab 1 and Lab 2 already established, and neither is created by EKS for you when you use the
CLI.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the role**

```bash
EKS_CLUSTER_ROLE=usms-eks-cluster-role

aws iam create-role \
  --role-name "$EKS_CLUSTER_ROLE" \
  --assume-role-policy-document file://policies/trust-eks-cluster.json \
  --description "Assumed by the EKS control plane to manage network resources for usms-eks-cluster" \
  --tags Key=Project,Value=USMS Key=Tier,Value=app Key=Lab,Value=07 \
  --query 'Role.Arn' --output text
```

**Command - part 2, the permissions policy, with a fallback**

```bash
EKS_CLUSTER_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSEKSClusterPolicy \
  --policy-document file://policies/usms-eks-cluster-policy.json \
  --description "Local stand-in for AmazonEKSClusterPolicy" \
  --query 'Policy.Arn' --output text 2>/dev/null \
  || aws iam list-policies --scope Local \
       --query "Policies[?PolicyName=='USMSEKSClusterPolicy'].Arn | [0]" --output text)

echo "EKS_CLUSTER_POLICY_ARN = $EKS_CLUSTER_POLICY_ARN"

aws iam attach-role-policy \
  --role-name "$EKS_CLUSTER_ROLE" \
  --policy-arn "$EKS_CLUSTER_POLICY_ARN"
```

**What the command does**

The `||` fallback is a pattern you will see three more times in this lab. `create-policy` fails with
`EntityAlreadyExists` if you run the step twice - which students do, constantly, after a mistake
further down. Rather than making the lab non-repeatable, the fallback looks the ARN up instead. The
`| [0]` at the end of the JMESPath expression takes the first match of the filter and turns a
one-element list into a scalar, so `--output text` prints a bare ARN rather than a list.

`--scope Local` restricts `list-policies` to customer managed policies. Without it, the call returns
every AWS managed policy the build carries, which on some builds is several hundred and on others is
none.

**On real AWS you would write this instead**, and it is worth knowing the ARN by sight:

```bash
# Real AWS. Do not run this here; the managed policy may not exist on your build.
aws iam attach-role-policy \
  --role-name usms-eks-cluster-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
```

Note the account field in that ARN: `aws`, not a number. That is how you tell an AWS managed policy
from a customer managed one at a glance, and it is why an AWS managed policy is identical in every
account on earth while `USMSEKSClusterPolicy` exists only in yours.

**Command - part 3, the cluster security group, in Lab 02's VPC**

```bash
EKS_CLUSTER_SG=$(aws ec2 create-security-group \
  --group-name usms-eks-cluster-sg \
  --description "Control-plane endpoint for usms-eks-cluster" \
  --vpc-id "$USMS_VPC_ID" \
  --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=usms-eks-cluster-sg},{Key=Project,Value=USMS},{Key=Tier,Value=app},{Key=Lab,Value=07}]' \
  --query 'GroupId' --output text 2>/dev/null \
  || aws ec2 describe-security-groups \
       --filters "Name=group-name,Values=usms-eks-cluster-sg" "Name=vpc-id,Values=$USMS_VPC_ID" \
       --query 'SecurityGroups[0].GroupId' --output text)

echo "EKS_CLUSTER_SG = $EKS_CLUSTER_SG"

aws ec2 authorize-security-group-ingress \
  --group-id "$EKS_CLUSTER_SG" \
  --protocol tcp --port 443 --cidr "$USMS_VPC_CIDR" \
  --query 'Return' --output text 2>/dev/null || echo "ingress rule already present"
```

**What the command does**

`--vpc-id "$USMS_VPC_ID"` is the reuse that matters. Omit it and the group is created in the account's
default VPC, where the cluster cannot use it, and the error at Step 8 says only that the security
group is invalid for the subnets - never that it is in the wrong VPC.

The ingress rule admits TCP 443 from `10.0.0.0/16` - the whole VPC, sourced from `USMS_VPC_CIDR` in
`configs/lab-02.env` rather than typed. Port 443 because the Kubernetes API server speaks HTTPS, and
the VPC CIDR rather than `0.0.0.0/0` because nothing outside the VPC has any business reaching the
control-plane endpoint. Note the contrast with Lab 05's `usms-alb-sg`, which *did* admit
`0.0.0.0/0`: that group fronted a public website, this one fronts an administrative API.

**Expected result**

```text
EKS_CLUSTER_POLICY_ARN = arn:aws:iam::000000000000:policy/USMSEKSClusterPolicy
EKS_CLUSTER_SG = sg-0a1b2c3d4e5f67890
```

> Example output - your security group ID will differ.

**Verify**

```bash
aws iam list-attached-role-policies --role-name usms-eks-cluster-role \
  --query 'AttachedPolicies[].PolicyName' --output text

aws iam get-role --role-name usms-eks-cluster-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text

aws ec2 describe-security-groups --group-ids "$EKS_CLUSTER_SG" \
  --query 'SecurityGroups[0].{Id:GroupId,Vpc:VpcId,Ports:IpPermissions[].FromPort}' --output json
```

**What to look for:** `USMSEKSClusterPolicy` from the first; `eks.amazonaws.com` from the second -
if it says `ec2.amazonaws.com` you attached the wrong trust document and must fix it now with
`aws iam update-assume-role-policy`; and from the third, a `Vpc` value equal to `$USMS_VPC_ID` and
`Ports` containing `443`.

---

### Step 7 - Create the node role, and attach Lab 1's policy to it

**Purpose**

The nodes need their own identity. This is also the step where Lab 1's `USMSStudentDataReadWrite`
gains its third holder, which is the connection Section 4.2 promised.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the role and its own policy**

```bash
EKS_NODE_ROLE=usms-eks-node-role

aws iam create-role \
  --role-name "$EKS_NODE_ROLE" \
  --assume-role-policy-document file://policies/trust-eks-node.json \
  --description "Assumed by EC2 instances in usms-eks-nodes so they can join the cluster" \
  --tags Key=Project,Value=USMS Key=Tier,Value=app Key=Lab,Value=07 \
  --query 'Role.Arn' --output text

EKS_NODE_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSEKSNodePolicy \
  --policy-document file://policies/usms-eks-node-policy.json \
  --description "Local stand-in for AmazonEKSWorkerNodePolicy + AmazonEKS_CNI_Policy + ECR read-only" \
  --query 'Policy.Arn' --output text 2>/dev/null \
  || aws iam list-policies --scope Local \
       --query "Policies[?PolicyName=='USMSEKSNodePolicy'].Arn | [0]" --output text)

aws iam attach-role-policy --role-name "$EKS_NODE_ROLE" --policy-arn "$EKS_NODE_POLICY_ARN"
```

**Command - part 2, attach Lab 1's policy unchanged**

```bash
S3_RW_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]" --output text)

echo "USMSStudentDataReadWrite = $S3_RW_ARN"

aws iam attach-role-policy --role-name "$EKS_NODE_ROLE" --policy-arn "$S3_RW_ARN"

aws iam list-entities-for-policy --policy-arn "$S3_RW_ARN" \
  --query 'PolicyRoles[].RoleName' --output text
```

**What the command does**

The ARN is **looked up, not typed**. `USMSStudentDataReadWrite` was created in Lab 1 and its ARN
contains the account number; hard-coding it would work in this course and break the moment anyone ran
the same script in a real account. Looking it up by name is the habit that transfers.

`list-entities-for-policy` answers the question "who is carrying this policy right now?", and it is
one of the most useful IAM calls there is when you are auditing an account you did not build.

**Expected result**

```text
USMSStudentDataReadWrite = arn:aws:iam::000000000000:policy/USMSStudentDataReadWrite
usms-ec2-app-role	usms-ecs-task-role	usms-eks-node-role
```

> Example output - the order of the three role names may differ.

**Three roles. One policy. Never edited.** Written in Lab 1 for an EC2 instance profile. Attached
unchanged in Lab 04 to a Fargate task role. Attached unchanged here to an EKS node role. Three
compute models - a virtual machine, a serverless container, a Kubernetes node - and the document that
describes "what USMS code may do to student data" did not need one character changed for any of them.

That is what a well-scoped policy buys you, and it is the single most transferable idea in Practical
2 and Practical 4 combined.

!!! note "Floci Limitation - a node role is the coarse way to do this, and real EKS has a finer one"
    Attaching `USMSStudentDataReadWrite` to the node role gives **every pod on every node** that
    permission, because every pod inherits the node's instance credentials unless something stops it.

    Real EKS solves this with **IRSA** - IAM Roles for Service Accounts. You associate an OIDC
    identity provider with the cluster, annotate a Kubernetes ServiceAccount with a role ARN, and
    only pods using that ServiceAccount get those credentials. Step 21 shows the commands and
    explains why they will not complete here.

    Take away the shape of the problem: on EKS, "which pod may touch the bucket?" is a real question
    with a real answer, and the node role is the answer you use when you have not answered it
    properly yet.

**Verify**

```bash
aws iam list-attached-role-policies --role-name usms-eks-node-role \
  --query 'AttachedPolicies[].PolicyName' --output text

aws iam get-role --role-name usms-eks-node-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text
```

**What to look for:** two policy names - `USMSEKSNodePolicy` and `USMSStudentDataReadWrite` - and the
service `ec2.amazonaws.com`. A node role that trusts `eks.amazonaws.com` is the single most common
error in this lab; if you see it, fix it with:

```bash
aws iam update-assume-role-policy --role-name usms-eks-node-role \
  --policy-document file://policies/trust-eks-node.json
```

**Checkpoint 2**

```text
IAM
 ├── usms-eks-cluster-role      trusts eks.amazonaws.com
 │     └── USMSEKSClusterPolicy
 └── usms-eks-node-role         trusts ec2.amazonaws.com
       ├── USMSEKSNodePolicy
       └── USMSStudentDataReadWrite   <- Lab 01, unchanged, third holder

EC2
 └── usms-eks-cluster-sg   in usms-vpc, tcp/443 from 10.0.0.0/16
```

---
### Step 8 - Create the cluster

**Purpose**

This is the step the previous seven were for. It also introduces one Floci-specific control that Part
B cannot work without, so read the tag discussion even if you are impatient.

**Concept first - `--cli-input-json`, and why the request body goes in a file**

`aws eks create-cluster` takes a nested structure (`resourcesVpcConfig`) containing two lists. The
AWS CLI's shorthand syntax can express that, but it is genuinely ambiguous once list elements and
struct members are separated by the same comma:

```text
--resources-vpc-config subnetIds=subnet-a,subnet-b,securityGroupIds=sg-c
                                          ^ is this a second subnet, or the end of the list?
```

The CLI resolves it correctly, but you should not have to trust that, and a reviewer reading your
repository should not have to work it out. `--cli-input-json` takes the entire request body as JSON
from a file. You met it in Lab 3. Here it also means the request you sent is a committed artefact:
someone can read `templates/lab-07-create-cluster.json` six months later and see exactly what was
asked for.

**Concept first - the `_lb_ports_` tag**

Floci reads one tag on the cluster that real AWS ignores completely: `_lb_ports_`. It tells the
emulator which host ports to publish so that a Kubernetes Service of type `LoadBalancer` or an
Ingress can be reached from your machine. The default is 8081.

This must be set **at cluster creation**. If you omit it and later discover Lab 08 Step 15 cannot
reach anything, the remedy is to delete and recreate the cluster - which means redoing Steps 8
through 22. Set it now.

!!! note "Floci Limitation - `_lb_ports_` is emulator control, not AWS configuration"
    Floci treats the cluster tag `_lb_ports_` as an instruction about host port publishing.

    Real AWS treats it as what it looks like: an ordinary tag with an unusual name. It appears in
    `describe-cluster`, it can be used in a cost allocation report, and it changes nothing.

    Take away that emulators sometimes overload a real API field to carry a local control. When you
    move this configuration to AWS, the tag is harmless - but the thing it was doing for you is not
    done any more, and a Service of type `LoadBalancer` will provision an actual network load
    balancer instead.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, build the request body**

```bash
cat > templates/lab-07-create-cluster.json << EOF
{
  "name": "usms-eks-cluster",
  "version": "1.30",
  "roleArn": "$(aws iam get-role --role-name usms-eks-cluster-role --query 'Role.Arn' --output text)",
  "resourcesVpcConfig": {
    "subnetIds": [
      "$USMS_PRIVATE_SUBNET_A",
      "$USMS_PRIVATE_SUBNET_B",
      "$USMS_PUBLIC_SUBNET_A",
      "$USMS_PUBLIC_SUBNET_B"
    ],
    "securityGroupIds": [ "$EKS_CLUSTER_SG" ],
    "endpointPublicAccess": true,
    "endpointPrivateAccess": true
  },
  "tags": {
    "Name": "usms-eks-cluster",
    "Project": "USMS",
    "Tier": "app",
    "Lab": "07",
    "_lb_ports_": "8081,8082"
  }
}
EOF

python3 -m json.tool templates/lab-07-create-cluster.json
```

**What the command does**

**The heredoc is unquoted here** - `<< EOF`, not `<< 'EOF'`. That is the opposite choice from Steps 4
and 5, and it is deliberate. This file must contain *values*: real subnet IDs, a real role ARN, a real
security group ID. Every `$(...)` and every `$VAR` inside it is evaluated at the moment the file is
written, and what lands on disk is the result. The policy documents in Steps 4 and 5 needed the
opposite, because a policy may contain literal `$` sequences that the shell must not touch.

Get this backwards and the failure is silent in both directions. A quoted heredoc here produces a
file containing the literal text `$USMS_PRIVATE_SUBNET_A`, and `create-cluster` fails with an
invalid-subnet error naming a subnet ID that is obviously not one. An unquoted heredoc in Step 5
produces a policy in which `${aws:username}` has been replaced by an empty string, and *nothing fails
at all* - you simply have a broken policy. That asymmetry is why this course restates the rule in
every lab.

Both subnet pairs go in. Real EKS wants subnets in at least two Availability Zones for the control
plane's cross-zone endpoints, and it wants to know about the public subnets if you will later ask for
an internet-facing load balancer - which Lab 08 will. The **nodes**, by contrast, go only in the
private subnets, which is Step 10's `--subnets`. Control plane reachability and node placement are
two different decisions, and this is the step that separates them.

**Command - part 2, assume the developer role and create the cluster**

```bash
CREDS=$(aws sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/usms-developer-role" \
  --role-session-name lab05a-eks-build \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)

export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | cut -f1)
export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | cut -f2)
export AWS_SESSION_TOKEN=$(echo "$CREDS" | cut -f3)

aws sts get-caller-identity
```

!!! warning "This is the one deliberate exception to the credentials rule"
    The course keeps credentials in named profiles and never in environment variables, because
    environment variables sit above profiles in the CLI's resolution order and mixing the two makes
    "which credentials did that actually use?" unanswerable.

    `sts assume-role` hands you credentials as environment variables by nature; there is no other
    shape for them. Part 4 below puts things back, and it is not optional. Lab 04 Step 4 made the
    same exception for the same reason.

**Command - part 3 (Path A), create the cluster**

```bash
aws eks create-cluster \
  --cli-input-json file://templates/lab-07-create-cluster.json \
  --query 'cluster.{Name:name,Status:status,Version:version,Arn:arn}' \
  --output table
```

**Command - part 3 (Path B), create the cluster with k3d instead**

Only if Step 2 gave you Path B. This creates a real Kubernetes cluster with the same name, so every
`kubectl` step from Step 12 onward works unchanged; what you lose is the `aws eks` half.

```bash
k3d cluster create usms-eks-cluster \
  --servers 1 --agents 2 \
  --api-port 6443 \
  --port "8081:80@loadbalancer" \
  --port "8082:443@loadbalancer" \
  --wait

k3d cluster list
```

Record in `notes/lab-07-notes.md` that Steps 9, 10, 21 and the `USMS_EKS_*` entries of Step 23 were
done on Path B, and which of them you could not complete. That note is what makes your lab report
honest rather than incomplete.

**Command - part 4, restore your normal identity**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
```

**Expected result** (Path A, part 3)

```text
-------------------------------------------------------------------------------------
|                                   CreateCluster                                   |
+---------------------------------------------------------+------------+-----------+
|                           Arn                            |    Name    |  Status   |
+---------------------------------------------------------+------------+-----------+
|  arn:aws:eks:us-east-1:000000000000:cluster/usms-eks-... | usms-eks-... | CREATING |
+---------------------------------------------------------+------------+-----------+
```

> Example output - the table is elided for width, and `Status` is `CREATING`, not `ACTIVE`. That is
> correct: cluster creation is asynchronous, which is Step 9's subject.

**Verify**

Step 9 is the verification for this step, because there is nothing useful to check until the cluster
finishes creating.

---

### Step 9 - Wait for the cluster, and read what it tells you

**Purpose**

Creating an EKS cluster is the slowest single call in this course. On real AWS it takes 10 to 15
minutes; locally it takes one to four. Either way it is asynchronous, and this step is where you
learn what a *waiter* is and what to do when there isn't one.

**Concept first - waiters**

You met `aws ec2 wait instance-running` in Lab 3. A waiter is a client-side poll loop that the CLI
ships for you: it calls the matching `describe` operation on a fixed interval and returns 0 when the
resource reaches the expected state, or 255 when it gives up. It is not a server-side feature - it is
the CLI doing the loop you would otherwise write. That matters here, because Floci may implement
`describe-cluster` perfectly well and still not implement the waiter's exact matcher, in which case
you write the loop yourself.

**Run from**

```text
aws-floci-course/
```

**Command - the waiter, with an explicit fallback**

```bash
aws eks wait cluster-active --name usms-eks-cluster 2>/dev/null \
  || {
    echo "waiter unavailable - polling describe-cluster instead"
    for i in $(seq 1 60); do
      STATUS=$(aws eks describe-cluster --name usms-eks-cluster \
                 --query 'cluster.status' --output text 2>/dev/null || echo UNKNOWN)
      printf "  attempt %2d  status=%s\n" "$i" "$STATUS"
      [ "$STATUS" = ACTIVE ] && break
      sleep 10
    done
  }

aws eks describe-cluster --name usms-eks-cluster --query 'cluster.status' --output text
```

**What the command does**

The `||` block runs only if the waiter itself fails. Sixty attempts at ten seconds is a ten-minute
ceiling, which is generous locally and about right for real AWS. `|| echo UNKNOWN` inside the loop
stops a transient API failure from putting an empty string into `$STATUS` and making the comparison
behave oddly.

Note what this loop does **not** do: `set -e`. If you have `set -Eeuo pipefail` active in this shell
from an earlier exercise, the first failing `describe-cluster` will kill the whole shell. Poll loops
and `set -e` are natural enemies; this is worth knowing before you write your first operational
script.

**Expected result**

```text
ACTIVE
```

**Verify**

```bash
aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.{Name:name,Status:status,Version:version,Endpoint:endpoint,
                    RoleArn:roleArn,Subnets:resourcesVpcConfig.subnetIds,
                    Sgs:resourcesVpcConfig.securityGroupIds,Vpc:resourcesVpcConfig.vpcId,
                    Tags:tags}' \
  --output json | tee outputs/lab-07-cluster.json
```

**What to look for**, in this order:

- `Status` is `ACTIVE`. Anything else and nothing below will work.
- `Subnets` has **four** entries and `Vpc` equals your `USMS_VPC_ID`. If `Vpc` is a different ID, the
  security group and the subnets disagreed and EKS chose one.
- `Endpoint` is a URL. Write it down - Step 11 uses it, and it is the address `kubectl` will talk to.
- `Tags` contains `_lb_ports_`. **If it does not, stop here and fix it before Step 10.** On Path A
  you can usually add it with `aws eks tag-resource`; if that call is unsupported, delete the cluster
  and redo Step 8 with the tag present. Discovering this in Lab 08 is much more expensive.

```bash
aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.tags._lb_ports_' --output text
```

That must print `8081,8082`. If it prints `None`, try:

```bash
aws eks tag-resource \
  --resource-arn "$(aws eks describe-cluster --name usms-eks-cluster --query 'cluster.arn' --output text)" \
  --tags _lb_ports_=8081,8082
```

and re-read it. Record the outcome in your notes either way.

✏️ **Your turn**

Using one command, print the cluster's Kubernetes version and its OIDC issuer URL side by side. Then
say, in one line in your notes, what the OIDC issuer is for.

```text
Expected result:
A version such as 1.30, and either an https URL or the word None.

"None" is the interesting answer. Step 21 explains what it means and what it costs
you. If you get a URL, note that too - your build supports more than most.
```

Hint: the issuer lives at `cluster.identity.oidc.issuer`, and `[A,B]` builds a two-element list from
two paths - you used that form in Lab 1.

---

### Step 10 - Create the managed node group

**Purpose**

Step 3 promised that a healthy control plane with no data plane runs nothing. This step supplies the
data plane, and it is the last AWS-side creation in the lab.

**Concept first - three ways to get nodes, and why we use the middle one**

| Option | What it is | Who patches it |
| --- | --- | --- |
| Self-managed nodes | You create an Auto Scaling group of EC2 instances with EKS bootstrap user data and they join | You. All of it |
| **Managed node group** | EKS creates and owns the Auto Scaling group; you declare min, max and desired | AWS supplies the AMI and drains nodes on upgrade; you trigger it |
| Fargate profile | No nodes at all; each pod gets its own micro-VM | AWS. There is nothing to patch |

Managed node groups are the default choice for a reason: they are the least work that still gives you
real nodes you can reason about. Note the third row, though, because it is the direct bridge to
Practical 2 - an EKS cluster running only Fargate profiles is, operationally, very close to the ECS
cluster you built in Lab 04, with Kubernetes objects instead of ECS ones.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the request body**

```bash
cat > templates/lab-07-create-nodegroup.json << EOF
{
  "clusterName": "usms-eks-cluster",
  "nodegroupName": "usms-eks-nodes",
  "scalingConfig": { "minSize": 2, "maxSize": 4, "desiredSize": 2 },
  "subnets": [ "$USMS_PRIVATE_SUBNET_A", "$USMS_PRIVATE_SUBNET_B" ],
  "instanceTypes": [ "t3.small" ],
  "amiType": "AL2023_x86_64_STANDARD",
  "nodeRole": "$(aws iam get-role --role-name usms-eks-node-role --query 'Role.Arn' --output text)",
  "labels": { "workload": "usms", "tier": "app" },
  "tags": { "Name": "usms-eks-nodes", "Project": "USMS", "Tier": "app", "Lab": "07" }
}
EOF

python3 -m json.tool templates/lab-07-create-nodegroup.json > /dev/null && echo "valid JSON"
```

**Command - part 2 (Path A), create it**

```bash
aws eks create-nodegroup \
  --cli-input-json file://templates/lab-07-create-nodegroup.json \
  --query 'nodegroup.{Name:nodegroupName,Status:status,Desired:scalingConfig.desiredSize}' \
  --output table

aws eks wait nodegroup-active \
  --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes 2>/dev/null \
  || {
    for i in $(seq 1 60); do
      S=$(aws eks describe-nodegroup --cluster-name usms-eks-cluster \
            --nodegroup-name usms-eks-nodes --query 'nodegroup.status' --output text 2>/dev/null || echo UNKNOWN)
      printf "  attempt %2d  status=%s\n" "$i" "$S"
      [ "$S" = ACTIVE ] && break
      sleep 10
    done
  }
```

**Command - part 2 (Path B)**

On Path B the agents were created by `k3d cluster create --agents 2` in Step 8, so there is nothing to
run. Record in your notes that `usms-eks-nodes` does not exist as an AWS object, and that Lab 08 Step
10 - which changes the node group's scaling config from the AWS side - is unavailable to you. The
Kubernetes-side scaling in Lab 08 Steps 4 to 9 is unaffected.

**What the command does**

Read `scalingConfig` carefully, because it is the same three numbers you met in Lab 06 and they mean
almost, but not exactly, the same thing:

```text
Lab 06, Application Auto Scaling      This step, managed node group
  MinCapacity   2                        minSize     2
  MaxCapacity  10                        maxSize     4
  (desired is the service's, and         desiredSize 2
   auto scaling writes it)               (you write it; a cluster autoscaler may too)
```

The difference is what moves them. In Lab 06 an autoscaler owned `desiredCount` and you were told
not to touch it. Here, nothing moves `desiredSize` unless you install a cluster autoscaler - which
Lab 08 Step 11 discusses and does not install. So this number is yours, and Lab 08 Step 10 changes
it by hand.

`labels` are **Kubernetes** labels applied to every node in the group, not AWS tags. You will use
`workload=usms` in Lab 08 when you write a `nodeSelector`. `tags` on the last line are AWS tags on
the AWS objects. Two labelling systems, one JSON document - read the field names, not the intent.

`t3.small` is the smallest instance type with enough memory to run a kubelet plus a few pods
comfortably. On Floci nothing is actually provisioned at that size; the value is recorded and
returned. Say so in your lab report rather than implying you sized a fleet.

**Expected result**

```text
------------------------------------------------
|                CreateNodegroup               |
+-----------+-----------------+----------------+
|  Desired  |      Name       |     Status     |
+-----------+-----------------+----------------+
|  2        |  usms-eks-nodes |  CREATING      |
+-----------+-----------------+----------------+
```

> Example output - `Status` becomes `ACTIVE` after the wait above.

**Verify**

```bash
aws eks describe-nodegroup --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes \
  --query 'nodegroup.{Name:nodegroupName,Status:status,Scaling:scalingConfig,
                      Subnets:subnets,Role:nodeRole,Labels:labels,Ami:amiType}' \
  --output json | tee outputs/lab-07-nodegroup.json
```

**What to look for:** `Status` is `ACTIVE`; `Subnets` contains exactly the **two private** subnet IDs
and neither public one; `Role` ends in `usms-eks-node-role`; and `Scaling` reads
min 2, max 4, desired 2.

If `Subnets` contains a public subnet, you edited the wrong template. Nodes in a public subnet is not
an error AWS will stop you making - it is a design mistake, and on a real account it is the one that
ends up in the incident report.

**Checkpoint 3**

```text
usms-eks-cluster        ACTIVE, k8s 1.30, vpc usms-vpc, 4 subnets, sg usms-eks-cluster-sg
  tags: Project=USMS Tier=app Lab=07 Name=usms-eks-cluster _lb_ports_=8081,8082
  └── usms-eks-nodes    ACTIVE, private-a + private-b, min 2 / max 4 / desired 2
                        nodeRole usms-eks-node-role, labels workload=usms tier=app
```

---

### Step 11 - Point `kubectl` at the cluster

**Purpose**

Everything so far has been AWS-side. From here to Step 21 the tool changes, and this is the step that
connects the two halves of the diagram in Section 6.

**Concept first - what a kubeconfig is**

`~/.kube/config` is a YAML file holding three lists and one pointer:

```text
clusters   : name -> API server URL + the CA certificate that signs its TLS
users      : name -> how to obtain a credential (a token, a certificate, or a command to run)
contexts   : name -> (cluster, user, default namespace)
current-context : which context every kubectl command uses unless told otherwise
```

`aws eks update-kubeconfig` writes entries into all three and sets the pointer. The `user` entry it
writes is the interesting one: rather than a stored token, it records a **command** -
`aws eks get-token --cluster-name ...` - which `kubectl` executes each time it needs to authenticate.
That is why your EKS access follows your IAM identity automatically, and why a colleague with the
same kubeconfig file but different AWS credentials gets different permissions from the same file.

Two things follow. First, the file contains no long-lived secret, which is why it is safe on a laptop
in a way that a static token would not be. Second, `~/.kube/config` is outside this repository, so it
is outside Git - no `.gitignore` rule is needed, and none should be added.

**Run from**

```text
aws-floci-course/
```

**Command - part 1 (Path A)**

```bash
aws eks update-kubeconfig --name usms-eks-cluster --alias usms-eks

kubectl config current-context
kubectl config get-contexts
```

**Command - part 1 (Path B)**

```bash
k3d kubeconfig merge usms-eks-cluster --kubeconfig-merge-default
kubectl config use-context k3d-usms-eks-cluster
kubectl config current-context
```

**Command - part 2, prove you can reach the API server**

```bash
kubectl cluster-info
kubectl get nodes -o wide
```

**What the command does**

`kubectl cluster-info` makes one authenticated call and prints the API server's address. It is the
`whoami.sh` of Kubernetes: cheap, read-only, and the first thing to run when something is wrong.

`kubectl get nodes -o wide` is the moment of truth. It proves three things at once: the API server is
reachable, your credential was accepted, and the data plane from Step 10 actually registered. A
cluster that is `ACTIVE` on the AWS side and shows zero nodes here is exactly the split Step 3
described.

**Expected result**

```text
Kubernetes control plane is running at https://localhost:6443
CoreDNS is running at https://localhost:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

NAME                    STATUS   ROLES                  AGE   VERSION        INTERNAL-IP   OS-IMAGE
usms-eks-cluster-srv0   Ready    control-plane,master   3m    v1.30.x+k3s1   172.18.0.3    K3s
usms-eks-cluster-ag0    Ready    <none>                 2m    v1.30.x+k3s1   172.18.0.4    K3s
usms-eks-cluster-ag1    Ready    <none>                 2m    v1.30.x+k3s1   172.18.0.5    K3s
```

> Example output - node names, addresses and the exact version will differ, and on some builds you
> will see only the server node. See the two failure modes below.

**If `kubectl` fails with an exec-plugin error** - something naming `aws eks get-token` or
`credential plugin` - your build's `get-token` is not implemented. Fall back to the cluster's own
kubeconfig, which is a real k3s kubeconfig with certificate credentials:

```bash
k3d kubeconfig get "$(k3d cluster list --no-headers | awk '{print $1}' | head -1)" > outputs/lab-07-kubeconfig.yaml
chmod 600 outputs/lab-07-kubeconfig.yaml
export KUBECONFIG="$PWD/outputs/lab-07-kubeconfig.yaml"
kubectl cluster-info
```

Note where that file went: `outputs/`, which is git-ignored, and `chmod 600`. A kubeconfig with
embedded certificates **is** a credential, and it gets exactly the treatment Lab 1 gave the access
key for `usms-dev-01`: written straight into `outputs/`, never onto the screen, and `chmod 600`.
Prove it is ignored:

```bash
git check-ignore -v outputs/lab-07-kubeconfig.yaml
```

**If `kubectl get nodes` shows only a control-plane node**, that is expected on some builds and is
not yet a problem - it becomes one at Step 13, where pods stay `Pending`. Troubleshooting entry 4 has
the remedy. Do not apply it pre-emptively; meet the failure first, because recognising it is worth
more than avoiding it.

**Verify**

```bash
kubectl get nodes --no-headers | wc -l
kubectl auth can-i create deployments --all-namespaces
kubectl api-resources --namespaced=true -o name | head -12
```

**What to look for:** at least one node; `yes` from `auth can-i`; and a list of resource names
including `configmaps`, `deployments.apps`, `pods` and `services`. That last command is the answer to
"what nouns does this cluster know?", and it is how you find out whether an add-on you expect is
installed.

---

### Step 12 - Create the namespace, and make it the default for your context

**Purpose**

Every object from here on lives in one namespace. Setting it as the context default means you type
`-n usms` zero times instead of forty, and it means a forgotten flag cannot silently put a USMS
Deployment in `kube-system`.

**Concept first - what a namespace is and is not**

A namespace is a **name scope** and a **policy attachment point**. Two Deployments called
`usms-gateway` can coexist in two namespaces. Resource quotas, network policies and role bindings
attach to a namespace.

A namespace is **not** an isolation boundary by default. Pods in different namespaces can reach each
other freely unless a NetworkPolicy says otherwise, and they share the same nodes. If you came to
this expecting something like an AWS account boundary, adjust: the closest AWS analogy is a tag
convention plus a set of IAM conditions, not an account.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, write the manifest**

```bash
cat > manifests/lab-07/00-namespace.yaml << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: usms
  labels:
    project: usms
    tier: app
    lab: "05a"
EOF

kubectl apply -f manifests/lab-07/00-namespace.yaml
```

**Command - part 2, make it the default**

```bash
kubectl config set-context --current --namespace=usms
kubectl config view --minify --output 'jsonpath={..namespace}'; echo
```

**What the command does**

Four fields appear in every manifest in this lab and it is worth naming them once:

```text
apiVersion   which API group and version this object belongs to.
             "v1" is the core group; "apps/v1" is where Deployments live
kind         the object type
metadata     name, namespace, labels, annotations
spec         what you want to be true. The controller's job is to make it so
```

There is a fifth, `status`, which you never write and the controller always fills in. The whole of
Kubernetes is that loop: you write `spec`, a controller reads it, acts, and writes `status`. Lab 06's
target tracking was the same loop with different words.

The label `lab: "05a"` is quoted. YAML would otherwise read `05a` as a string anyway, but `05` alone
would be the number 5, and the habit of quoting label values that begin with a digit saves an
afternoon eventually.

**Expected result**

```text
namespace/usms created
usms
```

**Verify**

```bash
kubectl get namespace usms --show-labels
kubectl get all -n usms
```

**What to look for:** the namespace `Active` with its three labels, and from the second command,
`No resources found in usms namespace.` - which is correct. `kubectl get all` is a useful habit but a
misleading name: it lists the common workload types, not literally everything. It will not show
ConfigMaps, Secrets or Ingresses, all of which you will create.

---
### Step 13 - Deploy the first microservice: `usms-enrolment`

**Purpose**

This is the largest single manifest in the lab and every later one is a variation on it. Read the
explanation before applying it, because six ideas appear here for the first time.

**Concept first - the six new ideas, in the order they appear in the file**

| Idea | What it does | What breaks without it |
| --- | --- | --- |
| `ConfigMap` | Holds configuration as key/value pairs, mounted as files or injected as env vars | Configuration lives in the image, and changing it means rebuilding |
| `Deployment.spec.replicas` | How many identical pods you want | Nothing runs |
| `selector.matchLabels` | How the Deployment finds the pods it owns | The Deployment adopts nothing, or adopts something else's pods |
| `resources.requests` | The CPU and memory the scheduler must reserve | The scheduler packs blindly, **and an HPA has nothing to compute a percentage against** |
| `readinessProbe` | "Is this pod ready for traffic?" | Requests are sent to a pod that is still starting |
| `livenessProbe` | "Is this pod wedged?" | A hung pod stays in the Service's endpoint list forever |

The `resources.requests` row is the one to remember. **Lab 08's HorizontalPodAutoscaler computes
"CPU utilisation" as a percentage of the request, not of the node.** A pod with no CPU request has an
undefined utilisation, the HPA reports `<unknown>`, and it never scales. Half the "my HPA does
nothing" questions in the world have that as their answer, and it is set here, in this lab, so that
Lab 08 works.

**The two probes are not the same probe.** Readiness controls *membership of the Service*: fail it
and you are removed from the endpoint list but left running. Liveness controls *restarts*: fail it
and the kubelet kills the container. Getting them the wrong way round produces a service that
restarts under load - the readiness probe fails because the pod is busy, but you wired it to
liveness, so the pod is killed, so the remaining pods get busier. Lab 05's ALB health check was a
readiness probe in all but name; Kubernetes gives you both, and expects you to know which is which.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the shared ConfigMap**

```bash
cat > manifests/lab-07/10-configmap-app.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: usms-app-config
  namespace: usms
  labels:
    project: usms
data:
  APP_ENVIRONMENT: "laboratory"
  APP_CAMPUS: "rtc"
  APP_VERSION: "1.0.0"
  APP_REGION: "us-east-1"
EOF

kubectl apply -f manifests/lab-07/10-configmap-app.yaml
kubectl get configmap usms-app-config -o jsonpath='{.data}'; echo
```

**Command - part 2, the enrolment service**

```bash
cat > manifests/lab-07/20-enrolment.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: usms-enrolment-conf
  namespace: usms
  labels:
    app: usms-enrolment
data:
  default.conf.template: |
    server {
      listen 80;
      server_name _;

      location = /healthz {
        add_header Content-Type text/plain;
        return 200 "ok\n";
      }

      location / {
        add_header Content-Type application/json;
        return 200 '{"service":"usms-enrolment","pod":"${POD_NAME}","node":"${NODE_NAME}","env":"${APP_ENVIRONMENT}","version":"${APP_VERSION}"}\n';
      }
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-enrolment
  namespace: usms
  labels:
    app: usms-enrolment
    project: usms
    tier: app
spec:
  replicas: 2
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: usms-enrolment
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app: usms-enrolment
        project: usms
        tier: app
    spec:
      containers:
        - name: enrolment
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
          envFrom:
            - configMapRef:
                name: usms-app-config
          volumeMounts:
            - name: conf
              mountPath: /etc/nginx/templates
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "200m"
              memory: "128Mi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 15
            periodSeconds: 20
            failureThreshold: 3
      volumes:
        - name: conf
          configMap:
            name: usms-enrolment-conf
---
apiVersion: v1
kind: Service
metadata:
  name: usms-enrolment
  namespace: usms
  labels:
    app: usms-enrolment
spec:
  type: ClusterIP
  selector:
    app: usms-enrolment
  ports:
    - name: http
      port: 80
      targetPort: http
EOF

kubectl apply -f manifests/lab-07/20-enrolment.yaml
```

**What the command does**

Three objects in one file, separated by `---`. That is a normal and good way to package a
microservice: everything that belongs to `usms-enrolment` is in `20-enrolment.yaml`, and deleting the
service means deleting one file's worth of objects.

Walk the interesting fields:

**`data.default.conf.template`** - the official `nginx` image runs every file in
`/etc/nginx/templates/` ending in `.template` through `envsubst` at container start, writing the
result into `/etc/nginx/conf.d/`. That is why `${POD_NAME}` in the template becomes the real pod name
in the response. **The heredoc is quoted**, so the shell leaves `${POD_NAME}` alone and it reaches the
file intact - the third time this lab has depended on that choice, and the reason it is restated
every time.

**`fieldRef`** - the downward API. It injects a value the pod cannot otherwise know: its own name,
and the node it landed on. This is what makes the load-balancing demonstration in Lab 08 legible;
without it, every reply looks identical and you cannot tell whether requests are being spread.

**`envFrom.configMapRef`** - takes every key in `usms-app-config` and makes it an environment
variable. Contrast with `env.valueFrom.configMapKeyRef`, which takes one key and lets you rename it.
`envFrom` is convenient; it is also how an unexpected key in a ConfigMap ends up shadowing something
in the container's own environment, so use it when you own both ends.

**`selector.matchLabels` and `template.metadata.labels` must agree.** The Deployment finds its pods by
label, and the Service finds them by label, independently. If they disagree, `kubectl apply` rejects
the Deployment outright - one of the few places Kubernetes catches this class of mistake for you. If
the *Service's* selector disagrees, nothing complains and the Service simply has no endpoints, which
is Troubleshooting entry 5.

**`strategy` with `maxUnavailable: 0`** - during a rolling update, never drop below the current
replica count; add one new pod, wait for it to be ready, then remove one old one. Compare with Lab
04's ECS deployment configuration of `minimumHealthyPercent 100`, `maximumPercent 200`: the same
policy, expressed as percentages instead of counts.

**`targetPort: http`** - the Service points at the *named* port on the container rather than at the
literal number `80`. Names survive a change of port number; numbers do not. This is a small habit
with a large payoff.

**Expected result**

```text
configmap/usms-enrolment-conf created
deployment.apps/usms-enrolment created
service/usms-enrolment created
```

**Verify**

```bash
kubectl rollout status deployment/usms-enrolment --timeout=120s
kubectl get deploy,rs,pods,svc -l app=usms-enrolment -o wide
kubectl get endpoints usms-enrolment
```

**What to look for:**

- `deployment "usms-enrolment" successfully rolled out` from the first command. If it times out, go
  straight to `kubectl describe pod` and Troubleshooting entry 4 - do not re-run `apply`.
- `READY 2/2` on the Deployment, one ReplicaSet, two pods `Running` and `1/1` ready.
- The Service has a `CLUSTER-IP` and **no** `EXTERNAL-IP`. It is `<none>`, and that is correct: this
  is a `ClusterIP` Service and nothing outside the cluster can reach it. Lab 08 changes that.
- `kubectl get endpoints` lists **two** addresses. This is the single most useful debugging command in
  Kubernetes: it is the Service's answer to "which pods am I actually sending traffic to right now?".
  An empty endpoint list with running pods means the selector is wrong or the readiness probe is
  failing, and it is the difference between guessing and knowing.

**Command - part 3, prove it serves**

```bash
kubectl run usms-curl --rm -it --restart=Never \
  --image=busybox:1.36 -- \
  wget -qO- http://usms-enrolment.usms.svc.cluster.local/
```

**Expected result**

```text
{"service":"usms-enrolment","pod":"usms-enrolment-6f8c9d7b45-xk2mn","node":"usms-eks-cluster-ag0","env":"laboratory","version":"1.0.0"}
pod "usms-curl" deleted
```

> Example output - the pod suffix and node name will differ. If you see the literal text
> `${POD_NAME}` in the response, your `nginx` image is older than 1.19 and does not run the template
> processor; pin `nginx:1.27-alpine` explicitly, or drop the variables from the template and read pod
> names from `kubectl get pods -o wide` instead.

**Checkpoint 4**

```text
namespace usms
 ├── ConfigMap usms-app-config        4 keys
 ├── ConfigMap usms-enrolment-conf    default.conf.template
 ├── Deployment usms-enrolment        2/2 ready, RollingUpdate 0/+1
 │     └── ReplicaSet                 2 pods, requests cpu=50m mem=32Mi
 └── Service usms-enrolment           ClusterIP, 2 endpoints, no external address
```

---

### Step 14 - Deploy the second microservice: `usms-results`

**Purpose**

The second service exists so that the third has somewhere to route. Building it is also the check
that you can read a manifest rather than copy one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > manifests/lab-07/30-results.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: usms-results-conf
  namespace: usms
  labels:
    app: usms-results
data:
  default.conf.template: |
    server {
      listen 80;
      server_name _;

      location = /healthz {
        add_header Content-Type text/plain;
        return 200 "ok\n";
      }

      location / {
        add_header Content-Type application/json;
        return 200 '{"service":"usms-results","pod":"${POD_NAME}","campus":"${APP_CAMPUS}","version":"${APP_VERSION}"}\n';
      }
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-results
  namespace: usms
  labels:
    app: usms-results
    project: usms
    tier: app
spec:
  replicas: 2
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: usms-results
  template:
    metadata:
      labels:
        app: usms-results
        project: usms
        tier: app
    spec:
      containers:
        - name: results
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          envFrom:
            - configMapRef:
                name: usms-app-config
          volumeMounts:
            - name: conf
              mountPath: /etc/nginx/templates
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "200m"
              memory: "128Mi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
      volumes:
        - name: conf
          configMap:
            name: usms-results-conf
---
apiVersion: v1
kind: Service
metadata:
  name: usms-results
  namespace: usms
  labels:
    app: usms-results
spec:
  type: ClusterIP
  selector:
    app: usms-results
  ports:
    - name: http
      port: 80
      targetPort: http
EOF

kubectl apply -f manifests/lab-07/30-results.yaml
kubectl rollout status deployment/usms-results --timeout=120s
```

**What the command does**

Almost the same as Step 13, with three deliberate differences:

- No `livenessProbe`. A results endpoint that returns a cached mark has nothing to wedge on, and
  every probe you add is a request the pod must serve forever. Probes are not free and not automatic.
- No explicit `strategy`, so the Deployment takes the default: `RollingUpdate` with `maxUnavailable`
  and `maxSurge` both 25%. With two replicas, 25% rounds such that one pod can be unavailable during
  an update - a materially different policy from `usms-enrolment`'s. Section 15 asks about this.
- `APP_CAMPUS` in the response instead of `APP_ENVIRONMENT`, so that in Step 16 you can see at a
  glance which backend answered.

**Verify**

```bash
kubectl get deploy -n usms -o custom-columns=\
'NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas,STRATEGY:.spec.strategy.type,MAXUNAVAIL:.spec.strategy.rollingUpdate.maxUnavailable'

kubectl get endpoints -n usms
```

**What to look for:** two Deployments, both `2/2`; `usms-enrolment` showing `MAXUNAVAIL` of `0` and
`usms-results` showing `25%`. That contrast is the point of the command. And two Services, each with
two endpoint addresses.

`-o custom-columns` is new here and worth keeping: it is JMESPath's job done by `kubectl`, and it is
how you get a table of exactly the fields you care about instead of the ones the authors chose.

---

### Step 15 - Deploy the gateway, and meet cluster DNS

**Purpose**

The gateway is the point of the whole exercise. Its configuration contains two hostnames and no
addresses, and after this step you will be able to say precisely how those hostnames resolve.

**Concept first - the DNS name of a Service**

Every Service gets a DNS record from the cluster's DNS add-on (CoreDNS):

```text
<service>.<namespace>.svc.cluster.local
  usms-enrolment.usms.svc.cluster.local   ->  the Service's ClusterIP
```

Four forms all work from a pod in the `usms` namespace, and the shortest is the most fragile:

```text
usms-enrolment                              works only from inside namespace usms
usms-enrolment.usms                         works from any namespace
usms-enrolment.usms.svc                     works from any namespace
usms-enrolment.usms.svc.cluster.local       fully qualified. Use this in config files
```

The ClusterIP it resolves to is a **virtual** address. Nothing owns it; there is no interface
anywhere with that address. Every node's kube-proxy programmes a rule that rewrites packets destined
for it to one of the current endpoint addresses. When a pod dies and another starts, the endpoint list
changes and the rules are rewritten. The ClusterIP does not move, which is why the gateway can hold a
name and forget about it.

**Compare with Lab 05.** An ALB target group did the same job with different machinery: the ECS
service registered and deregistered task IPs as they came and went, and the ALB's DNS name stayed
put. Kubernetes does it without a load balancer, for internal traffic, on every node, for free. That
is the single biggest practical difference between the two platforms' service models.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > manifests/lab-07/40-gateway.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: usms-gateway-conf
  namespace: usms
  labels:
    app: usms-gateway
data:
  default.conf.template: |
    server {
      listen 80;
      server_name _;

      location = /healthz {
        add_header Content-Type text/plain;
        return 200 "ok\n";
      }

      location = / {
        add_header Content-Type application/json;
        return 200 '{"service":"usms-gateway","pod":"${POD_NAME}","routes":["/enrolment/","/results/"]}\n';
      }

      location /enrolment/ {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://usms-enrolment.usms.svc.cluster.local/;
      }

      location /results/ {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_pass http://usms-results.usms.svc.cluster.local/;
      }
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-gateway
  namespace: usms
  labels:
    app: usms-gateway
    project: usms
    tier: web
spec:
  replicas: 1
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: usms-gateway
  template:
    metadata:
      labels:
        app: usms-gateway
        project: usms
        tier: web
    spec:
      containers:
        - name: gateway
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          envFrom:
            - configMapRef:
                name: usms-app-config
          volumeMounts:
            - name: conf
              mountPath: /etc/nginx/templates
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
            limits:
              cpu: "200m"
              memory: "128Mi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
      volumes:
        - name: conf
          configMap:
            name: usms-gateway-conf
---
apiVersion: v1
kind: Service
metadata:
  name: usms-gateway
  namespace: usms
  labels:
    app: usms-gateway
spec:
  type: ClusterIP
  selector:
    app: usms-gateway
  ports:
    - name: http
      port: 80
      targetPort: http
EOF

kubectl apply -f manifests/lab-07/40-gateway.yaml
kubectl rollout status deployment/usms-gateway --timeout=120s
```

**What the command does**

Two things in the nginx configuration deserve attention.

**`$host` and `$proxy_add_x_forwarded_for` survive the quoted heredoc and the envsubst pass.** They
are nginx variables, not shell variables and not environment variables, and `envsubst` in the nginx
image substitutes only names that are actually set in the environment - `host` is not, so it is left
alone. This is a real hazard worth knowing about: if you ever set an environment variable called
`host` on that container, your proxy configuration would be rewritten under you.

**The trailing slash on `proxy_pass` matters, and it is the classic nginx trap.**

```text
location /enrolment/ { proxy_pass http://backend/;  }   request /enrolment/x  -> upstream /x
location /enrolment/ { proxy_pass http://backend;   }   request /enrolment/x  -> upstream /enrolment/x
```

With the slash, the matched prefix is stripped. Without it, the whole path is passed through. We want
the first, because the enrolment service knows nothing about the prefix the gateway happens to use.

**The order of Steps 13, 14 and 15 is load-bearing.** nginx resolves the hostnames in `proxy_pass` at
configuration load, once, at startup. If the gateway starts before `usms-enrolment` exists, nginx
exits with `host not found in upstream` and the pod enters `CrashLoopBackOff`. That is Troubleshooting
entry 3, and if you want to see it, delete the enrolment Service and restart the gateway pod. It is a
genuine production hazard, and the production answer is a `resolver` directive with a TTL, not luck.

**Expected result**

```text
configmap/usms-gateway-conf created
deployment.apps/usms-gateway created
service/usms-gateway created
deployment "usms-gateway" successfully rolled out
```

**Verify**

```bash
kubectl get pods -n usms -o wide
kubectl logs deploy/usms-gateway --tail=5
```

**What to look for:** five pods `Running` - two enrolment, two results, one gateway - and gateway logs
with no `emerg` lines. `/docker-entrypoint.sh: Configuration complete; ready for start up` is the line
that says the template was processed.

---

### Step 16 - Prove service discovery from inside the cluster

**Purpose**

Step 15 asserted that the gateway reaches the other two by name. This step proves it, in the shape
the course has used since Lab 1: do not observe a proxy for the property, exercise the property.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, resolve the names from inside a pod**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  echo "--- resolving service names ---"
  nslookup usms-enrolment.usms.svc.cluster.local
  nslookup usms-results.usms.svc.cluster.local
'
```

**Command - part 2, go through the gateway**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  G=http://usms-gateway.usms.svc.cluster.local
  echo "--- gateway root ---";      wget -qO- $G/
  echo "--- via /enrolment/ ---";   wget -qO- $G/enrolment/
  echo "--- via /results/ ---";     wget -qO- $G/results/
'
```

**Command - part 3, show that the traffic is spread**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  for i in $(seq 1 12); do
    wget -qO- http://usms-gateway.usms.svc.cluster.local/enrolment/
  done
' | grep -o '"pod":"[^"]*"' | sort | uniq -c
```

**What the command does**

Part 1 asks the cluster's DNS directly. The answer is a ClusterIP - a virtual address in the service
CIDR, typically `10.43.x.x` on k3s - and **not** a pod address. That distinction is the whole of
Kubernetes service discovery in one line of output.

Part 3 is the proof that matters. Twelve requests through the gateway, counted by which pod answered.
`grep -o` prints only the matched text rather than the whole line, so you get one `"pod":"..."` per
request, and `sort | uniq -c` tallies them.

**Expected result**

Part 1:

```text
Server:    10.43.0.10
Address:   10.43.0.10:53

Name:      usms-enrolment.usms.svc.cluster.local
Address 1: 10.43.118.204 usms-enrolment.usms.svc.cluster.local
```

> Example output - both addresses will differ. The Server address is CoreDNS; the Name address is the
> Service's ClusterIP.

Part 3:

```text
   7 "pod":"usms-enrolment-6f8c9d7b45-xk2mn"
   5 "pod":"usms-enrolment-6f8c9d7b45-p4qtz"
```

> Example output - the split will not be exactly even, and does not need to be.

**What to look for:** **two distinct pod names** in the tally. One name means one of three things,
and they are worth distinguishing: only one pod is ready (check `kubectl get endpoints`); nginx has
cached the upstream resolution (expected - it resolves once at startup, so the *gateway* always talks
to the same ClusterIP, and it is kube-proxy that spreads the load beneath it); or you have twelve
requests and got unlucky, in which case raise the loop to 40.

That middle possibility is worth dwelling on, because it explains the architecture. nginx resolved
the name once and holds a ClusterIP. Every request goes to that same virtual address. The spreading
happens *below* nginx, in the node's packet-rewriting rules. This is why you can scale
`usms-enrolment` in Lab 08 without touching or restarting the gateway.

✏️ **Your turn**

Delete one `usms-enrolment` pod and, without restarting the gateway, show that requests through
`/enrolment/` still succeed and that a new pod name appears in the tally.

```text
Expected result:
kubectl delete pod <one enrolment pod>
A replacement pod appears within seconds (the ReplicaSet's doing, not yours).
Requests never fail, and the new pod's name shows up in the tally.

Write one sentence in your notes naming the object that created the replacement.
It was not the Deployment, and it was not you.
```

Hint: `kubectl get rs -n usms` and `kubectl get events -n usms --sort-by=.lastTimestamp | tail`.

**Checkpoint 5**

```text
namespace usms - three microservices, discoverable by DNS
 ├── usms-gateway    1/1   ClusterIP   -> proxies to the two below BY NAME
 ├── usms-enrolment  2/2   ClusterIP   2 endpoints
 └── usms-results    2/2   ClusterIP   2 endpoints

Proven: names resolve to ClusterIPs, not pod IPs
Proven: requests through the gateway are answered by more than one pod
Proven: killing a pod does not break the gateway's configuration
Not yet true: nothing outside the cluster can reach any of this
```

---

### Step 17 - ConfigMaps and Secrets, and an honest account of what a Secret is

**Purpose**

You have already used a ConfigMap three times. This step adds a Secret, and then immediately shows
you what it does not do - because a student who believes `kind: Secret` means "encrypted" will one
day commit one.

**Concept first**

| | ConfigMap | Secret |
| --- | --- | --- |
| Holds | Non-sensitive configuration | Credentials, tokens, keys |
| Stored as | Plain text in etcd | **Base64 in etcd**, encrypted at rest only if you configured that |
| Shown by `kubectl get -o yaml` | Plain | Base64 - which anyone can decode |
| Size limit | About 1 MiB | About 1 MiB |
| Mounted as | Files or env vars | Files or env vars |

Base64 is an **encoding**, not encryption. `echo dXNtcy10b2tlbg== | base64 -d` reverses it and
requires no key. A Kubernetes Secret gives you three real things - it keeps the value out of your
image, it can be RBAC-restricted separately from ConfigMaps, and it is not printed by `kubectl
describe` - and it gives you no confidentiality at rest unless the cluster operator enabled
encryption providers on etcd.

On EKS specifically, you have two better options, and both are worth naming:

- **Envelope encryption with KMS**, enabled at cluster creation, which encrypts Secret data in etcd
  with a key you control.
- **Not using Secrets for AWS credentials at all** - use IRSA, so that the pod obtains short-lived
  credentials from STS and there is no stored secret to leak. Step 21 returns to this.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, create the Secret from literals, not from a file**

```bash
kubectl create secret generic usms-enrolment-secret \
  --namespace usms \
  --from-literal=ENROLMENT_API_TOKEN='floci-dummy-token-not-a-real-secret' \
  --from-literal=ENROLMENT_DB_PASSWORD='floci-dummy-password' \
  --dry-run=client -o yaml > manifests/lab-07/50-secret.yaml

kubectl apply -f manifests/lab-07/50-secret.yaml
```

**What the command does**

`--dry-run=client -o yaml` is a pattern worth stealing for everything: it makes `kubectl create`
*generate the manifest* instead of creating the object. You get the convenience of the imperative
command and the auditability of a declarative file. Nearly every `kubectl create` subcommand supports
it.

!!! danger "You have just written a credential into a file inside the repository"
    The values above are deliberately dummies, and the file says so. **In any real system, do not do
    this.** `manifests/lab-07/50-secret.yaml` is a committed file, and a base64 value in a committed
    file is a plaintext value in your Git history forever, recoverable long after you "removed" it.

    The habit that transfers: generate Secret manifests into `outputs/`, which is git-ignored, or do
    not generate them at all and use a secrets manager plus IRSA. This lab commits the file only so
    that Step 24's Git check has something instructive to say about it.

    If you would rather not commit it at all, move it now and the rest of the lab still works:

    ```bash
    mv manifests/lab-07/50-secret.yaml outputs/lab-07-secret.yaml
    chmod 600 outputs/lab-07-secret.yaml
    git check-ignore -v outputs/lab-07-secret.yaml
    ```

**Command - part 2, demonstrate that base64 is not a lock**

```bash
kubectl get secret usms-enrolment-secret -o jsonpath='{.data.ENROLMENT_API_TOKEN}'; echo
kubectl get secret usms-enrolment-secret -o jsonpath='{.data.ENROLMENT_API_TOKEN}' | base64 -d; echo
```

**Expected result**

```text
ZmxvY2ktZHVtbXktdG9rZW4tbm90LWEtcmVhbC1zZWNyZXQ=
floci-dummy-token-not-a-real-secret
```

Two commands. No key, no permission beyond `get secret`, no difficulty. That is the demonstration.

!!! note "macOS and Linux differ here"
    GNU `base64` uses `-d`; the BSD version on macOS accepts `-D` and, in recent releases, `-d` as
    well. If `-d` fails, use `-D`. This is the same family of difference as `sed -i` and `date`,
    flagged in earlier labs.

**Command - part 3, consume it in the enrolment Deployment**

```bash
kubectl set env deployment/usms-enrolment \
  --from=secret/usms-enrolment-secret \
  --namespace usms

kubectl rollout status deployment/usms-enrolment --timeout=120s

kubectl get deploy usms-enrolment -o jsonpath='{.spec.template.spec.containers[0].envFrom}'; echo
```

**What the command does**

`kubectl set env --from=secret/...` adds an `envFrom.secretRef` to the pod template. Changing the pod
template is a change to `spec`, so the Deployment controller does what it always does with a changed
spec: it rolls out a new ReplicaSet. **That is the answer to a question students always ask** - no,
updating a ConfigMap or Secret does not restart your pods, but changing the pod template does, and
adding a reference to one is a template change.

If you want a ConfigMap change to reach running pods, you have three choices: mount it as a volume
and have the application re-read the file (the kubelet updates mounted ConfigMaps in place, within a
minute or so); change an annotation on the pod template to force a roll; or run `kubectl rollout
restart deployment/...`. Nothing happens automatically, and Section 15 asks you why that is a
reasonable default.

**Verify**

```bash
kubectl describe deployment usms-enrolment | sed -n '/Environment Variables from/,/Mounts/p'
kubectl exec deploy/usms-enrolment -- printenv | grep -E '^(APP_|ENROLMENT_)' | sort
```

**What to look for:** `usms-app-config` and `usms-enrolment-secret` both listed as environment
sources, and from the second command, the four `APP_*` keys plus the two `ENROLMENT_*` keys. Note
that `printenv` inside the container shows the token in plain text - because inside the container it
always was plain text. A Secret protects the value on the way to the pod, not inside it.

---
### Step 18 - Roll out a change, then roll it back

**Purpose**

Practical 2 taught rolling deployments through ECS's deployment controller. Kubernetes does the same
job with a different object and, crucially, keeps a history you can move backwards through. This step
is the one operational skill in this lab that you will use most often.

**Concept first - what a Deployment actually keeps**

A Deployment does not update pods. It creates a **new ReplicaSet**, scales it up, and scales the old
one down according to `strategy`. The old ReplicaSet is kept - scaled to zero, but kept - up to
`revisionHistoryLimit`, which you set to 5 in Step 13. That is what makes rollback instant: nothing is
rebuilt, an existing ReplicaSet is simply scaled back up.

```text
before:  ReplicaSet-A (rev 1)  replicas=2   <- serving
apply :  ReplicaSet-B (rev 2)  replicas=0 -> 1 -> 2
         ReplicaSet-A (rev 1)  replicas=2 -> 1 -> 0
after :  ReplicaSet-B (rev 2)  replicas=2   <- serving
         ReplicaSet-A (rev 1)  replicas=0   <- kept, and this is your rollback
```

**Run from**

```text
aws-floci-course/
```

**Command - part 1, make a change worth deploying**

```bash
sed -i.bak 's/APP_VERSION: "1.0.0"/APP_VERSION: "1.1.0"/' manifests/lab-07/10-configmap-app.yaml
grep APP_VERSION manifests/lab-07/10-configmap-app.yaml

kubectl apply -f manifests/lab-07/10-configmap-app.yaml
```

!!! note "macOS and Linux differ here too"
    GNU `sed` accepts `sed -i 's/.../.../' file`; BSD `sed` on macOS requires an argument to `-i`.
    Writing `sed -i.bak` works on both and leaves a `.bak` file you can delete. Add `*.bak` to
    `.gitignore` if it bothers you, or just `rm manifests/lab-07/*.bak` when you are done.

**Command - part 2, observe that nothing happened**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- http://usms-enrolment.usms.svc.cluster.local/
```

**What to look for:** the response still says `"version":"1.0.0"`. The ConfigMap changed; the running
pods did not. This is the behaviour Step 17 warned about, and meeting it here is worth more than
being told about it.

**Command - part 3, trigger the rollout deliberately**

```bash
kubectl annotate deployment/usms-enrolment \
  usms.rtc.bt/config-revision="$(date -u +%Y%m%d%H%M%S)" \
  --overwrite

kubectl rollout status deployment/usms-enrolment --timeout=120s
```

**What the command does**

Annotating the *Deployment* itself would change nothing about the pods. This command annotates the
Deployment, and because `kubectl annotate deployment/...` without `--field-manager` gymnastics writes
to `metadata.annotations` of the Deployment rather than of the pod template, you may find nothing
rolls. If `rollout status` returns immediately with no change, use the direct instrument instead:

```bash
kubectl rollout restart deployment/usms-enrolment
kubectl rollout status deployment/usms-enrolment --timeout=120s
```

`rollout restart` works by writing a timestamp annotation **into the pod template**, which is a spec
change, which triggers a normal rolling update. It is the supported way to say "roll my pods without
changing anything else", and it is what you would put in a pipeline after updating a ConfigMap.

**Command - part 4, confirm the new configuration reached the pods**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- http://usms-enrolment.usms.svc.cluster.local/
```

**Expected result**

```text
{"service":"usms-enrolment","pod":"usms-enrolment-7d9f4c8b62-w8ntq","node":"usms-eks-cluster-ag1","env":"laboratory","version":"1.1.0"}
```

> Example output - note `1.1.0`, and note that the pod name's middle segment changed. That segment is
> the ReplicaSet's hash, and a new hash means a new ReplicaSet.

**Command - part 5, read the history and roll back**

```bash
kubectl rollout history deployment/usms-enrolment

kubectl get rs -n usms -l app=usms-enrolment \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,REVISION:.metadata.annotations.deployment\.kubernetes\.io/revision'
```

!!! danger "Read before running any rollback"
    **What will be changed:** the `usms-enrolment` Deployment's pod template reverts to the previous
    revision, and its pods are replaced.
    **What depends on it:** `usms-gateway` routes `/enrolment/` here, but it routes by Service name,
    so it is unaffected and needs no change. The Service's endpoint list is rewritten automatically.
    **Reversible?** Yes, completely. `rollout undo` again moves you forward, and every revision up to
    `revisionHistoryLimit` remains available.
    **Effect on later labs:** none. Lab 08 attaches an HPA to this Deployment and does not care which
    revision it is on. Do leave the Deployment healthy at 2/2 before finishing the lab.

```bash
kubectl rollout undo deployment/usms-enrolment
kubectl rollout status deployment/usms-enrolment --timeout=120s

kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- http://usms-enrolment.usms.svc.cluster.local/
```

**What to look for:** the response version depends on what the previous revision's environment was -
which is the subtlety worth catching. `rollout undo` reverts the **pod template**, not the ConfigMap.
The ConfigMap is still at `1.1.0`, so a rolled-back pod that reads `APP_VERSION` from the ConfigMap
still reports `1.1.0`.

That is not a bug and it is not a trick question. It is the most important operational fact in this
step: **`rollout undo` does not undo everything you changed, only the parts that live in the
Deployment.** If your release changed a ConfigMap, a Secret and an image, rolling back the Deployment
recovers one of the three. Real rollback strategy is why teams put configuration in the same
versioned artefact as the workload.

Restore the ConfigMap so the lab ends in a known state:

```bash
sed -i.bak 's/APP_VERSION: "1.1.0"/APP_VERSION: "1.0.0"/' manifests/lab-07/10-configmap-app.yaml
kubectl apply -f manifests/lab-07/10-configmap-app.yaml
kubectl rollout restart deployment/usms-enrolment
kubectl rollout status deployment/usms-enrolment --timeout=120s
```

✏️ **Your turn**

Perform a rolling update of `usms-results` that changes its **image tag** rather than its
configuration, then roll it back, and record in your notes how many revisions
`kubectl rollout history` shows afterwards.

```text
Expected result:
Two revisions listed, and the Deployment back on the original image.
Watch `kubectl get pods -w` while it happens and note how many pods exist at the
peak - usms-results uses the DEFAULT strategy, not usms-enrolment's maxUnavailable 0,
so the shape of the roll is different. Say in one line how it differed.
```

Hint: `kubectl set image deployment/usms-results results=nginx:1.27` sets the tag; `--to-revision`
is a flag on `rollout undo`.

**Checkpoint 6**

```text
usms-enrolment
 ├── revision 1   ReplicaSet-A   replicas 0   (kept)
 ├── revision 2   ReplicaSet-B   replicas 0   (kept)
 └── revision 3   ReplicaSet-C   replicas 2   <- serving
 rollout history readable, rollout undo exercised, ConfigMap restored to 1.0.0
```

---

### Step 19 - Break a pod deliberately, and diagnose it

**Purpose**

Every previous step succeeded. That is not how Kubernetes goes. This step creates each of the three
most common failures on purpose, so that you have seen the output before you meet it under pressure.

**Concept first - the three questions, in order**

```text
kubectl get pods              is it running? what phase, how many restarts?
kubectl describe pod <name>   WHY is it in that phase? read the Events at the bottom
kubectl logs <name>           what did the application itself say?
```

Beginners reach for `logs` first. `logs` is the *third* question, and for the two commonest failures
it returns nothing at all, because the container never started. `describe` is where the answer is, and
the answer is almost always in the last four lines, under `Events`.

**Run from**

```text
aws-floci-course/
```

**Failure 1 - an image that does not exist**

```bash
kubectl set image deployment/usms-results results=nginx:this-tag-does-not-exist
sleep 20
kubectl get pods -n usms -l app=usms-results
kubectl describe pod -l app=usms-results | tail -15
```

**Expected result**

```text
NAME                            READY   STATUS             RESTARTS   AGE
usms-results-6b7c8d9f4-2mnpq    0/1     ImagePullBackOff   0          22s
usms-results-84cd7f6b59-h4xkz   1/1     Running            0          14m
usms-results-84cd7f6b59-r9wln   1/1     Running            0          14m
```

> Example output. Note that **the old pods are still serving** - `maxUnavailable` protected you, and
> a broken image never reached production. That is the deployment strategy earning its keep.

The `Events` section will contain `Failed to pull image` and `ErrImagePull` before it settles into
`ImagePullBackOff`. The word `BackOff` means Kubernetes is retrying with growing delays; it will do
so indefinitely.

Fix it:

```bash
kubectl rollout undo deployment/usms-results
kubectl rollout status deployment/usms-results --timeout=120s
```

**Failure 2 - a pod that cannot be scheduled**

```bash
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: usms-toobig
  namespace: usms
  labels:
    app: usms-toobig
spec:
  containers:
    - name: toobig
      image: nginx:1.27-alpine
      resources:
        requests:
          cpu: "64"
          memory: "256Gi"
EOF

sleep 10
kubectl get pod usms-toobig
kubectl describe pod usms-toobig | tail -8
```

**Expected result**

```text
NAME          READY   STATUS    RESTARTS   AGE
usms-toobig   0/1     Pending   0          11s

Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  10s   default-scheduler  0/3 nodes are available: 3 Insufficient cpu,
                                                      3 Insufficient memory.
```

> Example output - the node count depends on your cluster.

`Pending` with `FailedScheduling` means the pod is a valid object that no node can accommodate. The
message names the reason per node, and it is one of a short list: insufficient CPU or memory, a taint
the pod does not tolerate, a `nodeSelector` that matches nothing, or an unbound persistent volume.

Clean it up - this one is genuinely temporary, so it is a CLEAN UP item in Section 16:

```bash
kubectl delete pod usms-toobig
```

**Failure 3 - a container that starts and immediately exits**

```bash
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: usms-crasher
  namespace: usms
  labels:
    app: usms-crasher
spec:
  containers:
    - name: crasher
      image: busybox:1.36
      command: ["sh", "-c", "echo 'usms-crasher starting'; echo 'fatal: no database configured' >&2; exit 1"]
EOF

sleep 25
kubectl get pod usms-crasher
kubectl logs usms-crasher
kubectl describe pod usms-crasher | grep -A4 'Last State'
```

**Expected result**

```text
NAME           READY   STATUS             RESTARTS      AGE
usms-crasher   0/1     CrashLoopBackOff   2 (10s ago)   26s

usms-crasher starting
fatal: no database configured
```

This is the one case where `logs` is the right second command, because the container *did* start.
`--previous` is the flag that saves you when a pod has already restarted and the current container
has not yet produced output:

```bash
kubectl logs usms-crasher --previous
```

Clean up:

```bash
kubectl delete pod usms-crasher
```

**A fourth thing to know: events are namespaced and time-ordered**

```bash
kubectl get events -n usms --sort-by=.lastTimestamp | tail -20
```

**What to look for:** the whole story of the last few minutes in one place - scheduling decisions,
image pulls, probe failures, scaling actions. Events expire (one hour by default), which is why this
is a live-debugging tool and not an audit log. Lab 04's CloudWatch Logs group is the audit log;
these are not the same thing and neither substitutes for the other.

**Checkpoint 7**

```text
Seen, on purpose, and diagnosed with describe:
 ├── ImagePullBackOff      wrong image tag        -> old pods kept serving
 ├── Pending / FailedScheduling   requests exceed every node
 └── CrashLoopBackOff      container exits 1      -> logs --previous
All three temporary objects deleted; usms-results back to 2/2 on the correct image.
```

---

### Step 20 - Write down the ECS comparison while both are in front of you

**Purpose**

You have now built the same application twice, on two platforms, four weeks apart. This is the only
moment in the course when both are running and you can check a claim instead of remembering one.

**Run from**

```text
aws-floci-course/
```

**Command - look at both, side by side**

```bash
echo "=== ECS (Lab 04 / 05 / 06) ==="
aws ecs describe-services --cluster usms-ecs-cluster --services usms-enrolment-svc \
  --query 'services[0].{Desired:desiredCount,Running:runningCount,TaskDef:taskDefinition,
                        LB:length(loadBalancers),Deployments:length(deployments)}' --output table

echo "=== EKS (this lab) ==="
kubectl get deploy,svc -n usms -o wide
```

**Command - write the comparison**

```bash
cat >> notes/lab-07-notes.md << 'EOF'

## Step 20 - ECS and Kubernetes, compared with both running

| Question | ECS answer | Kubernetes answer |
| --- | --- | --- |
| What holds the container spec? | | |
| What keeps N copies alive? | | |
| What gives it a stable name? | | |
| How does another service find it? | | |
| What does a rolling update create? | | |
| Where does rollback state live? | | |
| Which IAM role does the app code use? | | |
| What would I have to change to move to another cloud? | | |

Two sentences: which one would I choose for USMS, and why.
EOF

echo "now fill it in - notes/lab-07-notes.md"
```

**What to look for:** you filling it in. This table is graded in Section 14 and half of it is
answerable from commands you have already run in this lab. The last row is the one that matters, and
the honest answer is not "nothing" - a Kubernetes manifest is portable but the IAM roles, the VPC,
the node groups and the load balancer annotations are not.

---

### Step 21 - IRSA: the right way to give a pod AWS permissions, and why it stops here

**Purpose**

Step 7 attached `USMSStudentDataReadWrite` to the node role and flagged it as the coarse answer. This
step shows the fine one. Whether it completes depends on your build, and either outcome is a result
worth recording.

**Concept first - the chain IRSA builds**

```text
1.  The cluster publishes an OIDC discovery document at a public HTTPS URL.
2.  You register that URL in IAM as an OpenID Connect identity provider.
3.  You write a role whose trust policy says:
      "any token from THAT provider, whose sub claim is
       system:serviceaccount:usms:usms-enrolment-sa, may assume me"
4.  You annotate the Kubernetes ServiceAccount with the role's ARN.
5.  A mutating webhook injects a projected token and two env vars into every pod
    using that ServiceAccount.
6.  The AWS SDK inside the pod finds those env vars, calls
    sts:AssumeRoleWithWebIdentity, and gets 15-minute credentials.
```

Nothing is stored. Nothing is shared between pods. A pod using a different ServiceAccount gets
nothing. That is the whole argument for IRSA over a node role, and it is worth being able to recite.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, does the cluster publish an issuer?**

```bash
OIDC_ISSUER=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || echo None)

echo "OIDC issuer: $OIDC_ISSUER"
```

**Command - part 2, only if part 1 printed a URL**

```bash
if [ "$OIDC_ISSUER" != "None" ] && [ -n "$OIDC_ISSUER" ]; then
  aws iam create-open-id-connect-provider \
    --url "$OIDC_ISSUER" \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 9e99a48a9960b14926bb7f3b02e22da2b0ab7280 \
    --query 'OpenIDConnectProviderArn' --output text
else
  echo "No OIDC issuer on this build - IRSA is Conceptual / Real AWS here. Record it."
fi
```

**Command - part 3, the ServiceAccount, which is worth creating either way**

```bash
kubectl create serviceaccount usms-enrolment-sa -n usms \
  --dry-run=client -o yaml > manifests/lab-07/60-serviceaccount.yaml

kubectl apply -f manifests/lab-07/60-serviceaccount.yaml
kubectl get sa -n usms
```

!!! note "Floci Limitation - IRSA needs a publicly reachable OIDC document"
    Floci runs the cluster on your machine. Its OIDC discovery document, if it publishes one at all,
    is not reachable from AWS's STS endpoint, and on most builds `cluster.identity.oidc.issuer` is
    absent entirely.

    On real AWS, `eksctl utils associate-iam-oidc-provider` or the two commands above register the
    provider once per cluster, after which every workload role is an ordinary IAM role with an
    unusual trust policy.

    Take away the chain, and take away the reason it exists: **the node role gives credentials to
    every pod on the node, including a compromised one.** Write in your notes which of the six steps
    above your build could complete, and which it could not. That distinction is what a lab report is
    for.

**Verify**

```bash
kubectl get sa usms-enrolment-sa -n usms -o yaml | grep -A3 'metadata:'
aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text 2>/dev/null \
  || echo "list-open-id-connect-providers unsupported on this build"
```

**What to look for:** a ServiceAccount named `usms-enrolment-sa` in namespace `usms`, and either a
provider ARN or an honest message. Do not fabricate the ARN in your report.

---

### Step 22 - Prove that all of this survives a restart

**Purpose**

The course's standing rule since Lab 1: a command that appears to succeed is not evidence that it did
what you meant. Where a lab depends on a property, prove the property. Here the property is
persistence, and the shape is the one you know - create, perturb, read back.

The perturbation is a full stop and start of Floci. The read-back must **re-derive every identifier
from the API**, not from a shell variable, because a shell variable proves only that your shell still
remembers something.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the truth before the restart**

```bash
{
  echo "=== BEFORE RESTART $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  aws eks describe-cluster --name usms-eks-cluster --query 'cluster.[name,status,version]' --output text 2>/dev/null
  aws eks describe-nodegroup --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes \
    --query 'nodegroup.[nodegroupName,status,scalingConfig.desiredSize]' --output text 2>/dev/null
  kubectl get deploy -n usms -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas' --no-headers
  kubectl get svc -n usms --no-headers | awk '{print $1, $3}'
} | tee outputs/lab-07-before-restart.txt
```

**Command - part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 5
./scripts/setup/floci-up.sh
sleep 20
```

!!! danger "Read before running any stop command"
    **What will be stopped:** the Floci container, via `docker compose stop`.
    **What depends on it:** every AWS API call in this course, and - on Path A - the Kubernetes node
    containers Floci manages.
    **Reversible?** Yes. `floci-down.sh` is `docker compose stop`, which keeps volumes and keeps the
    bind-mounted data directory. It is **not** `docker compose down -v`, which is forbidden in this
    course precisely because `-v` deletes volumes.
    **Effect on later labs:** none, provided `FLOCI_STORAGE_MODE` is `hybrid`. If it is `memory`,
    this step is where you find out, and finding out now is the entire purpose of the step.

**Command - part 3, read back, re-deriving everything**

```bash
{
  echo "=== AFTER RESTART $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

  CL=$(aws eks list-clusters --query 'clusters[?@==`usms-eks-cluster`] | [0]' --output text 2>/dev/null)
  echo "cluster re-derived from list-clusters: ${CL:-MISSING}"

  aws eks describe-cluster --name usms-eks-cluster --query 'cluster.[name,status,version]' --output text 2>/dev/null

  NG=$(aws eks list-nodegroups --cluster-name usms-eks-cluster --query 'nodegroups | [0]' --output text 2>/dev/null)
  echo "nodegroup re-derived from list-nodegroups: ${NG:-MISSING}"

  echo "--- kubernetes ---"
  kubectl get ns usms --no-headers 2>/dev/null | awk '{print "namespace", $1, $2}'
  kubectl get deploy -n usms -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas' --no-headers 2>/dev/null
  kubectl get cm -n usms --no-headers 2>/dev/null | awk '{print "configmap", $1}'
} | tee outputs/lab-07-after-restart.txt

echo
diff <(grep -v '^===' outputs/lab-07-before-restart.txt) \
     <(grep -v '^===\|re-derived\|^--- ' outputs/lab-07-after-restart.txt) \
  && echo "PERSISTENCE PROVEN - identical before and after" \
  || echo "differences above - read them before deciding whether they matter"
```

**What the command does**

Note the shape of the re-derivation. `aws eks list-clusters` is asked for *the whole list* and the
JMESPath filter `[?@==\`usms-eks-cluster\`]` picks the matching element. `@` is the current node in
JMESPath - here, each string in the list - and the backticks make `usms-eks-cluster` a literal rather
than a field name. That is a new JMESPath form for this course and Appendix B records it.

Why bother, when `describe-cluster --name usms-eks-cluster` is simpler? Because `describe-cluster`
takes the name *from you*. If the cluster were gone and something else answered, you would not
notice. Asking for the list and finding the name in it is a genuinely different question. This is the
same reasoning that made Lab 1's original "restart and note the identity is unchanged" test worthless:
the root ARN is a constant, so the test passed in memory mode with no disk at all.

**Expected result**

```text
=== AFTER RESTART 2026-09-06T04:12:33Z ===
cluster re-derived from list-clusters: usms-eks-cluster
usms-eks-cluster	ACTIVE	1.30
nodegroup re-derived from list-nodegroups: usms-eks-nodes
--- kubernetes ---
namespace usms Active
usms-enrolment	2
usms-gateway	1
usms-results	2

PERSISTENCE PROVEN - identical before and after
```

> Example output - timestamps differ, and the `diff` may report harmless ordering differences. Read
> them; do not assume.

**If the cluster is `MISSING` after the restart**, run `./scripts/utilities/floci-storage-check.sh`
before anything else. A storage mode of `memory` is the cause in the overwhelming majority of cases,
and it is the exact failure §2.1 of the course contract was written about.

**If the AWS side persisted but `kubectl` now fails to connect**, the Kubernetes node containers were
stopped along with Floci and may need a moment, or your kubeconfig's endpoint port changed. Check:

{% raw %}```bash
docker ps --filter "name=k3d" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
kubectl cluster-info
```{% endraw %}

If the containers are up but `kubectl` still cannot reach them, re-run Step 11's
`update-kubeconfig`. Record in your notes that the kubeconfig did not survive; that is a genuine
Floci behaviour and a useful thing for the next student to know.

**Checkpoint 8**

```text
PERSISTENCE PROVEN
 ├── usms-eks-cluster      re-derived from eks list-clusters, ACTIVE
 ├── usms-eks-nodes        re-derived from eks list-nodegroups
 ├── namespace usms        Active
 ├── 3 Deployments         2 / 2 / 1 ready
 └── 4 ConfigMaps + 1 Secret present
```

---

### Step 23 - Write `configs/lab-07.env`

**Purpose**

Every identifier in your shell dies when you close the terminal. Lab 08 needs eleven of these, and
this is the step that turns four hours into something the next session can consume without you
remembering anything.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-07.env << EOF
# Lab 07 - EKS cluster, node group and microservices
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains IDs, ARNs and names only. NO SECRETS. Safe to commit.
# The kubeconfig is NOT recorded here - it lives in ~/.kube/config, outside this repo.

export USMS_EKS_CLUSTER=usms-eks-cluster
export USMS_EKS_NODEGROUP=usms-eks-nodes
export USMS_EKS_NAMESPACE=usms

export USMS_EKS_CLUSTER_ARN=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.arn' --output text 2>/dev/null)
export USMS_EKS_CLUSTER_STATUS=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.status' --output text 2>/dev/null)
export USMS_EKS_VERSION=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.version' --output text 2>/dev/null)
export USMS_EKS_ENDPOINT=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.endpoint' --output text 2>/dev/null)
export USMS_EKS_LB_PORTS=$(aws eks describe-cluster --name usms-eks-cluster \
  --query 'cluster.tags._lb_ports_' --output text 2>/dev/null)

export USMS_EKS_CLUSTER_ROLE_ARN=$(aws iam get-role --role-name usms-eks-cluster-role \
  --query 'Role.Arn' --output text 2>/dev/null)
export USMS_EKS_NODE_ROLE_ARN=$(aws iam get-role --role-name usms-eks-node-role \
  --query 'Role.Arn' --output text 2>/dev/null)
export USMS_POLICY_EKS_CLUSTER=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSEKSClusterPolicy'].Arn | [0]" --output text 2>/dev/null)
export USMS_POLICY_EKS_NODE=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSEKSNodePolicy'].Arn | [0]" --output text 2>/dev/null)

export USMS_EKS_CLUSTER_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=usms-eks-cluster-sg" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)

export USMS_K8S_DEPLOY_GATEWAY=usms-gateway
export USMS_K8S_DEPLOY_ENROLMENT=usms-enrolment
export USMS_K8S_DEPLOY_RESULTS=usms-results
export USMS_K8S_SVC_GATEWAY=usms-gateway
export USMS_K8S_SVC_ENROLMENT=usms-enrolment
export USMS_K8S_SVC_RESULTS=usms-results
export USMS_K8S_CPU_REQUEST=50m
export USMS_K8S_MANIFEST_DIR=manifests/lab-07
EOF

grep -n 'export .*=$\|None' configs/lab-07.env || echo "all values populated"
```

**What the command does**

**The heredoc is unquoted** - the third time this lab has made that choice and said so. Every
`$(...)` runs now and the file that lands on disk contains values, not commands. Had it been quoted,
`source configs/lab-07.env` would re-run eleven API calls in every new terminal for the rest of the
course.

Every AWS value is **looked up from the API**, not taken from a shell variable. `export
USMS_EKS_CLUSTER_ARN=$CLUSTER_ARN` would happily record an ARN for a cluster that no longer exists.
Looking it up means a deleted resource shows as `None` and the check below catches it.

The Kubernetes values are **literal names**, because Kubernetes object names are chosen by you and do
not contain generated identifiers. There is nothing to look up.

`USMS_K8S_CPU_REQUEST` looks like trivia and is not: Lab 08's HPA computes utilisation against it,
and having the number recorded means you can check the arithmetic rather than trust it.

**Expected result**

```text
all values populated
```

If instead you see lines printed, one of two things is true. On **Path B**, `USMS_EKS_CLUSTER_ARN`,
`USMS_EKS_CLUSTER_STATUS`, `USMS_EKS_VERSION`, `USMS_EKS_ENDPOINT` and `USMS_EKS_LB_PORTS` will be
empty or `None` - that is expected, and Lab 08's Step 10 is the only step that needs them. Note it
in `notes/lab-07-notes.md`. On **Path A**, any empty value is a genuine gap: find it now, because a
missing value here becomes an unexplained failure twenty steps into the next document.

**Verify**

```bash
source configs/lab-07.env
echo "cluster=$USMS_EKS_CLUSTER  ns=$USMS_EKS_NAMESPACE  lb_ports=$USMS_EKS_LB_PORTS"
grep -c '^export' configs/lab-07.env
```

**What to look for:** the three values echoed, `lb_ports` reading `8081,8082`, and a count of **21**
exported variables.

---

### Step 24 - Commit your work

**Purpose**

Lab 1 established that `.gitignore` was the repository's first commit, before any secret existed.
This step preserves that property and checks it rather than trusting it - and this lab has produced
two things that make the check more interesting than usual.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look before you add**

```bash
git status --short
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears. This lab wrote six files there, including - on some paths - a
  kubeconfig with embedded certificates.
- No `.env` at the repository root appears.
- `configs/lab-07.env` **does** appear. That one is meant to be committed: IDs and names, no secrets.
- `manifests/lab-07/50-secret.yaml` appears **only if you left it there** after Step 17's warning. If
  it does, decide deliberately. In this course the values are dummies and committing it is a teaching
  artefact; in any other repository, move it.

If anything under `outputs/` is listed, stop and diagnose before committing:

```bash
git check-ignore -v outputs/lab-07-support-probe.txt
```

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-07-support-probe.txt
```

> Example output - the line number will differ.

That names the file, the line number and the rule that matched. If it prints nothing, the file is
**not** ignored, and the rule is probably `outputs/` rather than `outputs/*` - the silent failure
described in §15 of the course contract, where Git cannot re-include `.gitkeep` under an excluded
directory. Fix the rule, not the symptom:

```bash
grep -n '^outputs' .gitignore
git ls-files outputs/          # .gitkeep, and nothing else
```

**Command - part 2, add and commit**

```bash
git add labs/lab-07-eks manifests/lab-07 policies/trust-eks-*.json \
        policies/usms-eks-*.json templates/lab-07-*.json \
        configs/lab-07.env scripts/utilities/verify-lab-07.sh \
        scripts/utilities/eks-support-probe.sh scripts/cleanup/lab-07-cleanup.sh \
        notes/lab-07-notes.md

git status --short

git commit -m "Lab 07: EKS cluster, node group and three USMS microservices

- usms-eks-cluster-role and usms-eks-node-role, with local stand-ins for the
  AWS managed policies, plus Lab 01's USMSStudentDataReadWrite on the node role
- usms-eks-cluster across all four Lab 02 subnets, usms-eks-nodes in the private pair
- namespace usms with gateway, enrolment and results Deployments and ClusterIP Services
- service discovery proven by DNS from inside the cluster
- rolling update and rollback exercised; three failure modes diagnosed
- persistence proven by re-deriving every identifier after a Floci restart"
```

**Verify**

```bash
git log --oneline -1
git show --stat --oneline HEAD | head -25
git ls-files | grep -c '^outputs/'
```

**What to look for:** your commit at the top; a file list containing the manifests, the policies and
`configs/lab-07.env`; and **`0`** from the last command. A non-zero count means a file under
`outputs/` is tracked, and you should find out which one and why before doing anything else.

**Checkpoint 9**

```text
committed
 ├── manifests/lab-07/     00-namespace, 10-configmap-app, 20-enrolment,
 │                          30-results, 40-gateway, 60-serviceaccount
 ├── policies/              trust-eks-cluster, trust-eks-node,
 │                          usms-eks-cluster-policy, usms-eks-node-policy
 ├── templates/             lab-07-create-cluster.json, lab-07-create-nodegroup.json
 ├── configs/lab-07.env    21 exports, no empty values (Path A)
 ├── scripts/utilities/     verify-lab-07.sh, eks-support-probe.sh
 └── git ls-files outputs/  -> only .gitkeep
```

---

### 8.4 Path C - what to do if neither EKS nor k3d is available

If Step 2 gave you Path C, you cannot run a cluster, and pretending otherwise would produce a lab
report full of invented output. Do this instead, and say in your report that you did:

1. **Write every manifest** from Steps 12 to 17. They are text files; nothing about writing them
   requires a cluster.
2. **Validate them without a cluster.** `kubectl apply --dry-run=client -f manifests/lab-07/`
   parses and schema-checks against `kubectl`'s built-in knowledge and needs no API server. It will
   catch a mis-indented `spec`, a wrong `apiVersion` and a selector that does not match its template.
3. **Do Steps 4 to 7 and Step 23 in full.** They are IAM and EC2 calls, and they work.
4. **Answer all of Section 15**, and answer Section 13's Exercises 1, 2 and 3 on paper, giving the
   commands you would run and the output you would expect, clearly labelled as expected rather than
   observed.
5. **Install `k3d` before the next session** if you possibly can. Lab 08 is much harder to do on
   paper than this one, because its whole subject is watching numbers move.

That is a legitimate submission. An invented `kubectl get pods` output is not.

---
## 9. Verification

### 9.1 Build `scripts/utilities/verify-lab-07.sh`

Every lab ships one of these. It checks **configuration as well as existence**, because a script that
only asks "does it exist?" passes right up until the restart that deletes it.

**Run from**

```text
aws-floci-course/
```

````markdown
{% raw %}```bash
cat > scripts/utilities/verify-lab-07.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 07 artefact. Exit 1 if anything is missing.
# Works from any directory. Never assumes a shell variable is already set.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-07.env" 2>/dev/null || true

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Earlier-lab dependencies still present =="
check "Lab 01 role usms-developer-role" "aws iam get-role --role-name usms-developer-role"
check "Lab 01 policy USMSStudentDataReadWrite" \
  "test -n \"\$(aws iam list-policies --scope Local --query \"Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]\" --output text)\""
check "Lab 02 usms-vpc" "aws ec2 describe-vpcs --vpc-ids ${USMS_VPC_ID:-vpc-none}"
check "Lab 02 private subnet b exists (two AZs needed)" \
  "aws ec2 describe-subnets --subnet-ids ${USMS_PRIVATE_SUBNET_B:-subnet-none}"

echo "== Lab 07 IAM and EC2 =="
check "role usms-eks-cluster-role" "aws iam get-role --role-name usms-eks-cluster-role"
check "cluster role trusts eks.amazonaws.com" \
  "test \"\$(aws iam get-role --role-name usms-eks-cluster-role --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text)\" = eks.amazonaws.com"
check "role usms-eks-node-role" "aws iam get-role --role-name usms-eks-node-role"
check "node role trusts ec2.amazonaws.com" \
  "test \"\$(aws iam get-role --role-name usms-eks-node-role --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text)\" = ec2.amazonaws.com"
check "node role carries Lab 01's USMSStudentDataReadWrite" \
  "aws iam list-attached-role-policies --role-name usms-eks-node-role --query 'AttachedPolicies[].PolicyName' --output text | grep -qw USMSStudentDataReadWrite"
check "usms-eks-cluster-sg is in usms-vpc" \
  "test \"\$(aws ec2 describe-security-groups --filters Name=group-name,Values=usms-eks-cluster-sg --query 'SecurityGroups[0].VpcId' --output text)\" = ${USMS_VPC_ID:-vpc-none}"

echo "== Lab 07 EKS (expect 3 failures on support Path B) =="
check "cluster usms-eks-cluster is ACTIVE" \
  "test \"\$(aws eks describe-cluster --name usms-eks-cluster --query 'cluster.status' --output text)\" = ACTIVE"
check "cluster carries the _lb_ports_ tag" \
  "aws eks describe-cluster --name usms-eks-cluster --query 'cluster.tags._lb_ports_' --output text | grep -q '8081'"
check "nodegroup usms-eks-nodes is ACTIVE" \
  "test \"\$(aws eks describe-nodegroup --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes --query 'nodegroup.status' --output text)\" = ACTIVE"

echo "== Kubernetes =="
check "kubectl reaches an API server" "kubectl version --request-timeout=10s"
check "namespace usms exists" "kubectl get namespace usms"
check "usms-enrolment has 2 ready replicas" \
  "test \"\$(kubectl get deploy usms-enrolment -n usms -o jsonpath='{.status.readyReplicas}')\" = 2"
check "usms-results has 2 ready replicas" \
  "test \"\$(kubectl get deploy usms-results -n usms -o jsonpath='{.status.readyReplicas}')\" = 2"
check "usms-gateway has 1 ready replica" \
  "test \"\$(kubectl get deploy usms-gateway -n usms -o jsonpath='{.status.readyReplicas}')\" = 1"
check "service usms-enrolment has at least 2 endpoints" \
  "test \"\$(kubectl get endpoints usms-enrolment -n usms -o jsonpath='{.subsets[0].addresses}' | grep -o 'ip' | wc -l)\" -ge 2"
check "usms-enrolment declares a cpu request (Lab 08 needs it)" \
  "kubectl get deploy usms-enrolment -n usms -o jsonpath='{.spec.template.spec.containers[0].resources.requests.cpu}' | grep -q 'm'"

echo "== Files and Git hygiene =="
check "configs/lab-07.env exists" "test -f configs/lab-07.env"
check "configs/lab-07.env has no empty values" \
  "! grep -qE 'export [A-Z_0-9]+=$' configs/lab-07.env"
check "five or more manifests present" \
  "test \"\$(ls manifests/lab-07/*.yaml 2>/dev/null | wc -l)\" -ge 5"
check "all four Lab 07 policy documents are valid JSON" \
  "for f in policies/trust-eks-cluster.json policies/trust-eks-node.json policies/usms-eks-cluster-policy.json policies/usms-eks-node-policy.json; do python3 -m json.tool \$f >/dev/null || exit 1; done"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"
check ".gitignore uses outputs/* not outputs/" "grep -q '^outputs/\*' .gitignore"

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-07.sh
./scripts/utilities/verify-lab-07.sh
```{% endraw %}
````

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Earlier-lab dependencies still present ==
  ok   Lab 01 role usms-developer-role
  ...
== Kubernetes ==
  ok   kubectl reaches an API server
  ...
== Files and Git hygiene ==
  ok   no secret is tracked by git
  ok   .gitignore uses outputs/* not outputs/

PASS=30  FAIL=0
```

> Example output - the `ok` lines are abbreviated here; you will see all 30.

**How to read a failure.** Failures in the **Environment** block are the real problem; everything
below them is usually a consequence. A cluster that "does not exist" because Floci is not running is
not a cluster problem.

On support **Path B**, expect exactly **three** failures, all in the EKS block: the cluster, the
`_lb_ports_` tag and the node group are AWS-side objects you never created. `PASS=27  FAIL=3` is a
correct result on Path B, and your notes should say so.

### 9.2 A quick end-to-end check you can run any time

```bash
kubectl run usms-smoke --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  G=http://usms-gateway.usms.svc.cluster.local
  wget -qO- $G/ && wget -qO- $G/enrolment/ && wget -qO- $G/results/
' && echo "SMOKE TEST PASSED"
```

Three JSON documents and the words `SMOKE TEST PASSED`. If the gateway responds but a backend does
not, the gateway is fine and the problem is in that backend's Service or endpoints - start with
`kubectl get endpoints -n usms`.

### 9.3 Build the cleanup script - DO NOT RUN IT NOW

!!! danger "This script destroys the whole of Lab 07"
    **What will be deleted:** the namespace and everything in it, the node group, the cluster, both
    IAM roles, both local policies and the cluster security group.
    **What depends on it:** Lab 08, entirely. Nothing in it works without this lab's cluster.
    **Reversible?** No. Recreating means redoing Steps 4 to 17.
    **Effect on later labs:** Lab 10 and Lab 07 do not use the cluster, but they do use
    `USMSStudentDataReadWrite`, which this script detaches from the node role and does **not** delete.
    Deleting the policy itself would break Lab 03's instance profile and Lab 04's task role.

    Write the script now, at the end of the course run it. It requires typed confirmation.

```bash
cat > scripts/cleanup/lab-07-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Deletes every Lab 07 resource, dependencies inside-out.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"

cat <<'WARN'
This deletes:
  - Kubernetes namespace usms and everything inside it
  - EKS node group usms-eks-nodes
  - EKS cluster usms-eks-cluster
  - IAM roles usms-eks-cluster-role and usms-eks-node-role
  - IAM policies USMSEKSClusterPolicy and USMSEKSNodePolicy
  - Security group usms-eks-cluster-sg
It does NOT delete USMSStudentDataReadWrite, which Lab 03 and Lab 04 still use.
WARN

printf 'Type exactly DELETE-LAB-07 to proceed: '
read -r CONFIRM
[ "$CONFIRM" = "DELETE-LAB-07" ] || { echo "aborted"; exit 1; }

# 1. Kubernetes objects first: the cluster cannot be deleted while a
#    LoadBalancer Service still holds a load balancer (Lab 08 creates one).
kubectl delete namespace usms --ignore-not-found --timeout=180s

# 2. Node group before cluster. A cluster with a node group refuses to delete.
aws eks delete-nodegroup --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes 2>/dev/null
aws eks wait nodegroup-deleted --cluster-name usms-eks-cluster --nodegroup-name usms-eks-nodes 2>/dev/null || sleep 30

# 3. Cluster.
aws eks delete-cluster --name usms-eks-cluster 2>/dev/null
aws eks wait cluster-deleted --name usms-eks-cluster 2>/dev/null || sleep 30

# 4. Detach before delete. delete-role fails with DeleteConflict while a
#    managed policy is attached, and the error does not name the policy.
for R in usms-eks-cluster-role usms-eks-node-role; do
  for P in $(aws iam list-attached-role-policies --role-name "$R" \
               --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    aws iam detach-role-policy --role-name "$R" --policy-arn "$P"
  done
  aws iam delete-role --role-name "$R" 2>/dev/null
done

# 5. Our own policies only. Never USMSStudentDataReadWrite.
for N in USMSEKSClusterPolicy USMSEKSNodePolicy; do
  A=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='$N'].Arn | [0]" --output text 2>/dev/null)
  [ -n "$A" ] && [ "$A" != "None" ] && aws iam delete-policy --policy-arn "$A"
done

# 6. Security group last: it cannot be deleted while an interface uses it.
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=usms-eks-cluster-sg \
       --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
[ -n "$SG" ] && [ "$SG" != "None" ] && aws ec2 delete-security-group --group-id "$SG"

echo "Lab 07 resources removed."
EOF

chmod +x scripts/cleanup/lab-07-cleanup.sh
bash -n scripts/cleanup/lab-07-cleanup.sh && echo "cleanup script: valid bash syntax"
```

`bash -n` parses without executing. Run it on every script you write; it costs nothing and catches
the unclosed quote you will otherwise find at the worst possible moment.

The deletion order is the lesson: **namespace, node group, cluster, detach, roles, policies, security
group.** AWS and Kubernetes both refuse to delete anything with dependents, and the errors they return
name the operation rather than the dependent. Learning the order once is cheaper than reading
`DependencyViolation` six times.

---

## 10. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 2 | Floci running under Compose; five env files sourced; `verify-lab-02.sh` `FAIL=0`; four subnet IDs across two AZs; `kubectl` installed; support path A, B or C recorded in `notes/lab-07-notes.md` |
| 2 | Step 7 | `usms-eks-cluster-role` trusting `eks.amazonaws.com` with `USMSEKSClusterPolicy`; `usms-eks-node-role` trusting `ec2.amazonaws.com` with `USMSEKSNodePolicy` **and Lab 01's `USMSStudentDataReadWrite`**; `usms-eks-cluster-sg` in `usms-vpc` admitting tcp/443 from the VPC CIDR |
| 3 | Step 10 | `usms-eks-cluster` `ACTIVE` across all four Lab 02 subnets with the `_lb_ports_` tag present; `usms-eks-nodes` `ACTIVE` in the **two private subnets only**, min 2 / max 4 / desired 2 |
| 4 | Step 13 | `usms-enrolment` 2/2 ready, ClusterIP Service with two endpoints, CPU request `50m` declared, readiness and liveness probes distinct |
| 5 | Step 16 | Three Deployments healthy; service names resolving to ClusterIPs from inside a pod; at least two distinct pod names in a twelve-request tally through the gateway |
| 6 | Step 18 | A rolling update observed creating a new ReplicaSet; `rollout history` readable; `rollout undo` exercised; the ConfigMap restored to `1.0.0` and the Deployment back at 2/2 |
| 7 | Step 19 | `ImagePullBackOff`, `Pending` / `FailedScheduling` and `CrashLoopBackOff` each produced deliberately and diagnosed with `describe`; all three temporary objects deleted |
| 8 | Step 22 | `PERSISTENCE PROVEN` after a Floci stop and start, with the cluster and node group names **re-derived from `list-clusters` and `list-nodegroups`**, not from shell variables |
| 9 | Step 24 | `configs/lab-07.env` with 21 exports and no empty values, committed; nothing under `outputs/` staged; `git check-ignore -v` naming the rule that protected you |

---

## 11. Troubleshooting

??? danger "`kubectl` hangs, or reports `connection refused` to `localhost:6443`"
    The API server is not reachable. Work outwards from the container:

    {% raw %}```bash
    docker ps --filter "name=k3d" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    kubectl config current-context
    kubectl cluster-info
    ```{% endraw %}

    If no containers are listed, the cluster's nodes are not running - start Floci with
    `./scripts/setup/floci-up.sh` and give it 30 seconds. If containers are listed but the published
    port differs from the one in your kubeconfig, re-run Step 11's `update-kubeconfig`, which
    rewrites the endpoint.

    If `current-context` names a cluster you do not recognise, you are pointed at something else
    entirely - a Docker Desktop cluster, or a colleague's. `kubectl config get-contexts` lists them
    and `kubectl config use-context` switches.

??? danger "`error: You must be logged in to the server (Unauthorized)`"
    Your credential was rejected. Two causes, and they are distinguishable.

    If the message mentions `exec` or a credential plugin, the kubeconfig is trying to run
    `aws eks get-token` and that call is unsupported on your build. Use the certificate-based
    kubeconfig fallback given in Step 11.

    If it does not, your AWS identity is not mapped into the cluster's authorisation system. On real
    EKS the cluster creator is mapped automatically and everyone else must be added - historically
    through the `aws-auth` ConfigMap, now through EKS access entries. This is worth knowing about
    because it is the commonest real-world EKS onboarding problem, and it does not arise locally.

??? danger "`usms-gateway` is in `CrashLoopBackOff` with `host not found in upstream`"
    nginx resolves the hostnames in `proxy_pass` once, at startup. If `usms-enrolment` or
    `usms-results` did not exist when the gateway pod started, nginx exits and the pod restarts
    forever.

    ```bash
    kubectl logs deploy/usms-gateway --previous | tail -5
    kubectl get svc -n usms
    ```

    Fix by making the Services exist, then restarting the gateway:

    ```bash
    kubectl apply -f manifests/lab-07/20-enrolment.yaml
    kubectl apply -f manifests/lab-07/30-results.yaml
    kubectl rollout restart deployment/usms-gateway
    ```

    The production answer is different: a `resolver` directive with a TTL makes nginx re-resolve
    periodically instead of once. Worth reading up on if you ever put nginx in front of a
    Kubernetes Service in earnest.

??? danger "Pods stay `Pending` forever and `describe` says `node(s) had untolerated taint`"
    Your cluster has a control-plane node and no worker nodes, and control-plane nodes carry a taint
    that repels ordinary pods. This is exactly the control plane / data plane split from Step 3.

    ```bash
    kubectl get nodes
    kubectl describe pod <pod> | tail -6
    kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints[*].key'
    ```

    The correct fix is Step 10 - create the node group, so there is somewhere to run pods. If Step 10
    is unavailable on your build, the local-only workaround is to remove the taint:

    ```bash
    kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null
    kubectl taint nodes --all node-role.kubernetes.io/master:NoSchedule- 2>/dev/null
    ```

    Two things to be clear about. The trailing `-` on the taint key is what *removes* it. And you
    would never do this on a real cluster: the taint exists so that a runaway workload cannot starve
    the API server. Record in your notes that you did it and why.

??? danger "A Service exists, pods are `Running`, but `kubectl get endpoints` shows none"
    The Service's `selector` does not match the pods' labels, or the pods are running but not
    **ready**.

    ```bash
    kubectl get svc usms-enrolment -o jsonpath='{.spec.selector}'; echo
    kubectl get pods -n usms --show-labels
    kubectl get pods -n usms -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status'
    ```

    Compare the two label sets character by character. Note that the Deployment's own
    `selector.matchLabels` is a *separate* selector from the Service's; they usually match because you
    wrote them to, not because Kubernetes requires it.

    If labels agree and readiness is `False`, the readiness probe is failing -
    `kubectl describe pod` shows `Readiness probe failed:` with the HTTP status.

??? danger "`ImagePullBackOff` on a public image, and you are behind a proxy or offline"
    The nodes cannot reach the registry. Pre-load the images from your host instead:

    ```bash
    docker pull nginx:1.27-alpine
    docker pull busybox:1.36
    CL=$(k3d cluster list --no-headers | awk '{print $1}' | head -1)
    k3d image import nginx:1.27-alpine busybox:1.36 -c "$CL"
    kubectl rollout restart deployment -n usms
    ```

    `k3d image import` copies an image from your local Docker daemon straight into the cluster's
    nodes, bypassing any registry. It is the single most useful k3d command for a laboratory on a
    constrained network, and it is worth knowing before the session rather than during it.

??? danger "`aws eks create-cluster` returns `InvalidParameterException` mentioning subnets"
    Three causes, in order of likelihood:

    1. The subnets are not in at least two Availability Zones. Check:

        ```bash
        aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_A $USMS_PRIVATE_SUBNET_B \
          --query 'Subnets[].[SubnetId,AvailabilityZone]' --output text
        ```

    2. `templates/lab-07-create-cluster.json` contains literal `$USMS_...` text because the heredoc
       was quoted. `grep '\$USMS' templates/lab-07-create-cluster.json` answers it in one line.
    3. The security group is in a different VPC from the subnets. Step 6's third verify covers this.

??? danger "`kubectl apply` reports `field is immutable` on a Deployment"
    `spec.selector` cannot be changed after creation. If you edited the selector labels, the only
    remedy is to delete and recreate the Deployment:

    ```bash
    kubectl delete deployment usms-enrolment
    kubectl apply -f manifests/lab-07/20-enrolment.yaml
    ```

    This is a genuine and well-known Kubernetes rough edge. It is also a good argument for choosing
    your label scheme once, at the start, and leaving it alone - which is why this course fixed
    `app`, `project` and `tier` in Step 13 and never varied them.

??? danger "Everything worked yesterday and today the cluster is empty"
    Run the storage check first, before anything else:

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    A `FLOCI_STORAGE_MODE` of `memory` discards all state on restart. That is the failure §2.1 of the
    course contract exists to prevent, and Step 22 is the test that catches it. If the mode is
    correct and the cluster is still gone, check whether anyone ran `docker compose down -v` or
    `docker volume prune` - both are forbidden in this course for exactly this reason.

---

## 12. Floci vs Real AWS

### 12.1 Feature comparison

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `eks create-cluster` / `describe-cluster` | Provisions a managed control plane in AWS-owned accounts, 10–15 min | Starts a k3s cluster in local containers, 1–4 min | Implemented in Floci (Path A) |
| Kubernetes API itself | Upstream conformant | Genuinely upstream conformant - this half is real | Implemented in Floci |
| Deployments, ReplicaSets, Services, ConfigMaps | Standard | Standard, identical behaviour | Implemented in Floci |
| Cluster DNS (CoreDNS) | Standard | Standard | Implemented in Floci |
| Rolling updates and rollback | Standard | Standard | Implemented in Floci |
| Managed node group | Real EC2 instances in your subnets, real ASG | Recorded as an object; nodes are local containers | Floci Limitation |
| `instanceTypes`, `amiType` | Determine real hardware and a real AMI | Stored and returned; no effect | Floci Limitation |
| VPC CNI - pods get real VPC IPs | Yes; pod IPs come from your subnet CIDRs | Pods get k3s cluster-network addresses, unrelated to `10.0.0.0/16` | Floci Limitation |
| Cluster and node IAM roles enforced | A missing permission fails cluster creation or node registration | Stored, never evaluated | Floci Limitation |
| IRSA / OIDC provider | Full support; the recommended way to give pods AWS permissions | Issuer usually absent; no reachable discovery document | Conceptual / Real AWS |
| KMS envelope encryption of Secrets | Configurable at cluster creation | Not available | Conceptual / Real AWS |
| EKS access entries / `aws-auth` mapping | Required for anyone but the cluster creator | Not enforced | Conceptual / Real AWS |
| Control plane logging to CloudWatch | Five log types, per-cluster switch | Generally absent | Conceptual / Real AWS |
| Cluster upgrades | `update-cluster-version`, then node group version | Not meaningful locally | Conceptual / Real AWS |
| Cost | Per cluster per hour, plus every node as ordinary EC2 | Free | Conceptual / Real AWS |
| `_lb_ports_` cluster tag | An ordinary tag. Ignored | Controls which host ports the cluster publishes | Floci-specific behaviour |

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **The cluster is ready in two minutes.** On AWS, budget fifteen for the control plane and another
  five for the node group. Any pipeline you write that creates a cluster must be built around that,
  and `aws eks wait` is not optional there.
- **No cost.** A three-node `t3.small` group plus a control plane is a real monthly bill, and an
  idle laboratory cluster left running over a holiday is the classic student invoice.
- **No IAM enforcement.** A cluster role missing one EC2 permission fails at creation on AWS, with an
  error that names the API call and not the permission. Read your policies.
- **No quotas, no throttling, no eventual consistency.** On AWS, a `describe-cluster` immediately
  after `create-cluster` can return a status that is already stale.
- **Node capacity is effectively unlimited here.** The `Pending` / `FailedScheduling` failure in Step
  19 had to be forced with an absurd request. On real nodes it arrives on its own, at the worst time.

### 12.3 What you actually observed in this lab

```text
OBSERVABLE, and you saw it
  the whole Kubernetes object model, working
  DNS-based service discovery, proven from inside a pod
  a rolling update creating a new ReplicaSet, and a rollback reusing an old one
  three failure modes, produced deliberately and diagnosed
  a Service with no endpoints, and what causes it
  persistence across a restart, re-derived from the API

RECORDED BUT NOT ENFORCED
  every IAM permission in both policies
  the node group's instance type, AMI type and scaling numbers
  the cluster's security group and its VPC association

CONCEPTUAL ONLY - you read about it and could not run it
  IRSA and the OIDC trust chain
  KMS envelope encryption of Secrets
  EKS access entries
  control plane logging, upgrades, and cost
```

Say which column a claim belongs to when you write your lab report. "I configured IRSA" is not true;
"I wrote the ServiceAccount and traced the six-step trust chain, and recorded that my build publishes
no OIDC issuer" is true, and is worth more.

---
## 13. Independent Lab Exercises

Work in `labs/lab-07-eks/exercises.md`. Record commands and output there, and screenshots in
`screenshots/`. Hints point at documentation or an earlier step; none of them contains the answer.

### Exercise 1 - Basic: a fourth microservice

**Requirements**

Deploy `usms-timetable`: one replica, `nginx:1.27-alpine`, its own ConfigMap serving a JSON document
identifying itself and its pod, a readiness probe on `/healthz`, and a ClusterIP Service on port 80.

**Constraints**

- The manifest must be a single file, `manifests/lab-07/70-timetable.yaml`, containing all three
  objects.
- Labels must follow this lab's scheme exactly: `app`, `project`, `tier`.
- CPU and memory requests must be declared.
- You may not use `kubectl create deployment` and then edit it. Write the manifest.

**Expected outcome**

`kubectl get deploy,svc -n usms` shows four Deployments and four Services. A `busybox` pod can fetch
`http://usms-timetable.usms.svc.cluster.local/` and gets JSON naming the service and its pod.

**Hints**

Copy the structure of `30-results.yaml`, not `20-enrolment.yaml` - the results manifest is the
smaller of the two and has no liveness probe to adapt. Remember that `kubectl apply --dry-run=client
-f <file>` validates before you commit to anything.

---

### Exercise 2 - Intermediate: route to it, and prove the route

**Requirements**

Add a `/timetable/` route to `usms-gateway` so that a request through the gateway reaches
`usms-timetable`. Then prove that the change reached the running gateway pod.

**Constraints**

- Edit `manifests/lab-07/40-gateway.yaml` and re-apply it. Do not use `kubectl edit`.
- The gateway must end the exercise on a **new** ReplicaSet, and you must be able to show which
  command caused that.
- `/enrolment/` and `/results/` must still work afterwards. Show all three in one command.

**Expected outcome**

Three JSON responses through the gateway, from three different services, and a
`kubectl rollout history deployment/usms-gateway` showing one more revision than before.

**Hints**

Step 18 established that changing a ConfigMap does not restart pods, and named the two commands that
do. Only one of them is appropriate when the pod template itself has not changed.

---

### Exercise 3 - Problem solving: find the misconfiguration

**Requirements**

Apply the manifest below exactly as given. It is syntactically valid, `kubectl apply` accepts it, all
objects are created, and the Service returns nothing. Diagnose it, state the cause in one sentence,
and fix it with a **minimal** change.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: usms-broken
  namespace: usms
spec:
  replicas: 2
  selector:
    matchLabels:
      app: usms-broken
  template:
    metadata:
      labels:
        app: usms-broken
        version: v1
    spec:
      containers:
        - name: broken
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: usms-broken
  namespace: usms
spec:
  selector:
    app: usms-broken
    version: v2
  ports:
    - port: 80
      targetPort: http
```

**Constraints**

- Find it with commands, not by reading the YAML. Show the commands you used, in order.
- Your fix must change exactly one line.
- There are **two** independent problems here. Find both. Fixing one will not make it work.

**Expected outcome**

A short diagnosis naming both faults, the command output that revealed each, and a working Service
with two endpoints. Delete `usms-broken` when you are finished - it is a CLEAN UP item.

**Hints**

Step 13's verify section named the single most useful debugging command in Kubernetes and said why.
Start there. For the second fault, ask what the base `nginx` image actually serves at the path the
probe requests, and what a failing readiness probe does to a Service's membership.

---

### Exercise 4 - Challenge: survive a node going away

**Requirements**

The Faculty's data centre loses one rack. In cluster terms, one node disappears. Design and
demonstrate a configuration in which `usms-enrolment` continues to serve throughout, and justify each
choice in prose.

The brief, and nothing more:

> USMS enrolment must not have all its capacity on one node, must never drop below one healthy pod
> during a voluntary disruption such as a node drain, and must be able to say - from the cluster
> itself, not from your memory - which node each of its pods is on.

**Constraints**

- No new Deployment. Change `usms-enrolment`.
- Demonstrate it. `kubectl drain` on one node, with the smoke test from Section 9.2 running in a
  loop, is a fair demonstration; so is deleting all pods on one node at once.
- If your cluster has only one schedulable node, say so, explain what you would have demonstrated,
  and demonstrate as much of it as the cluster allows.

**Expected outcome**

An updated `20-enrolment.yaml`, at least one new object, evidence of pods on more than one node
where possible, and half a page of justification. Marks are for the reasoning, not the YAML.

**Hints**

Three Kubernetes features are relevant and you need at least two of them:
`topologySpreadConstraints`, `podAntiAffinity`, and `PodDisruptionBudget`. Read what each one
guarantees - one of them is advisory and one of them is enforced, and knowing which is which is most
of the exercise. `kubectl get pods -o wide` answers the third requirement.

---

### Exercise 5 - Integration: prepare what Lab 08 needs, using what Lab 01 built

**Requirements**

Three parts, and the third leaves a real artefact for the next session.

**Part 1 - measure the baseline.** Record the current CPU consumption of the `usms-enrolment` pods,
as an absolute value and as a percentage of the `50m` request set in Step 13. Save it to
`outputs/lab-07-cpu-baseline.txt`.

**Part 2 - trace Lab 01's policy to this cluster.** Without opening Lab 1's document, produce a
single report that shows: the ARN of `USMSStudentDataReadWrite`; every role currently carrying it;
the bucket ARN named in its `Resource` field; and whether that bucket exists. Save it to
`outputs/lab-07-lab06-readiness.txt`.

**Part 3 - write the readiness note.** Append to `notes/lab-07-notes.md` a short section stating
which of `configs/lab-07.env`'s 21 variables Lab 08 will need, and why, one line each.

**Constraints**

- Part 1 must state honestly whether `kubectl top` works on your build. If the metrics API is absent,
  say so and record what you would expect to see instead; do not invent numbers. Lab 08 Step 7
  deals with exactly this, so a documented absence here is genuinely useful.
- Part 2 must read the bucket name **out of the policy document**, not out of Lab 1's text and not
  from memory. If you type the bucket name yourself, the exercise is not done.
- Part 3 must be your own reading of Section 17, not a copy of it.

**Expected outcome**

Two files in `outputs/` (git-ignored - check with `git check-ignore -v`) and a new section in your
notes. Lab 08's Step 2 opens by reading all three.

**Hints**

For Part 1: `kubectl top pods -n usms` if the metrics API exists; `kubectl get --raw
/apis/metrics.k8s.io/v1beta1` tells you whether it does, and returns a clear error if not.

For Part 2: `aws iam get-policy-version` needs both the policy ARN and the default version ID, and
the version ID comes from `aws iam get-policy`. Chain them. The `Resource` field is a list, and the
bucket ARN is not the same as the object ARN - Lab 1 deliberately kept them apart, and Lab 10 depends
on the difference.

---

## 14. Lab Assessment Checklist

Tick each item only when you can show the command output that proves it.

**Environment and setup**

- [ ] Floci started with `./scripts/setup/floci-up.sh`, storage mode `hybrid`
- [ ] `verify-lab-02.sh` and `verify-lab-04.sh` run before building
- [ ] Four subnet IDs across two Availability Zones confirmed present
- [ ] `kubectl` installed and `kubectl version --client` verified
- [ ] Support path A, B or C probed and recorded in `notes/lab-07-notes.md`

**IAM and networking**

- [ ] Both trust policies written with a **quoted** heredoc and validated as JSON
- [ ] `usms-eks-cluster-role` trusts `eks.amazonaws.com`; `usms-eks-node-role` trusts `ec2.amazonaws.com`
- [ ] Both local stand-in policies written, validated, and attached
- [ ] Lab 01's `USMSStudentDataReadWrite` attached to the node role, and its three holders listed
- [ ] `usms-eks-cluster-sg` created **in Lab 02's VPC**, admitting tcp/443 from the VPC CIDR only

**Cluster and nodes**

- [ ] `templates/lab-07-create-cluster.json` written with an **unquoted** heredoc and containing real IDs
- [ ] Cluster created while holding assumed `usms-developer-role` credentials, and identity restored afterwards
- [ ] Cluster `ACTIVE`, four subnets, correct VPC, `_lb_ports_` tag present
- [ ] Node group `ACTIVE` in the **private subnets only**, min 2 / max 4 / desired 2
- [ ] `kubectl get nodes` returns at least one `Ready` node

**Application**

- [ ] Namespace `usms` created from a manifest and set as the context default
- [ ] Three Deployments applied declaratively, all reporting ready
- [ ] CPU and memory requests declared on every container
- [ ] Readiness and liveness probes distinguished, and the difference stated in your own words
- [ ] Service discovery proven by DNS lookup **from inside a pod**
- [ ] Load spreading proven by counting distinct pod names across at least twelve requests
- [ ] ConfigMap and Secret both used; base64 decoded on screen to show what a Secret is not

**Operations**

- [ ] A rolling update observed creating a new ReplicaSet
- [ ] `rollout history` read, and `rollout undo` exercised
- [ ] Stated in writing what `rollout undo` did **not** revert, and why that matters
- [ ] `ImagePullBackOff`, `FailedScheduling` and `CrashLoopBackOff` each produced and diagnosed
- [ ] `kubectl describe` used before `kubectl logs`, and the reason understood

**Verification, persistence and hygiene**

- [ ] `verify-lab-07.sh` written and run; result recorded, including expected Path B failures
- [ ] Floci stopped and started; cluster and node group **re-derived from the API**
- [ ] `PERSISTENCE PROVEN` recorded, or the failure diagnosed with `floci-storage-check.sh`
- [ ] `configs/lab-07.env` generated, 21 exports, no empty values
- [ ] `git status --short` inspected before `git add`; nothing under `outputs/` staged
- [ ] `git check-ignore -v` run on at least one `outputs/` file, and the rule it named recorded
- [ ] `scripts/cleanup/lab-07-cleanup.sh` written, syntax-checked, **not run**

**Understanding**

- [ ] Section 15 answered in prose in `notes/lab-07-notes.md`
- [ ] Step 20's comparison table filled in with both platforms running
- [ ] Five exercises attempted; Exercise 5's two `outputs/` files present

---

## 15. Review Questions

Answer in prose in `notes/lab-07-notes.md`. No command output - these ask what you understood.

**1.** An EKS cluster reports `ACTIVE`. Every pod you create sits in `Pending`. Explain, using the
control plane / data plane distinction from Step 3, why "the cluster is healthy" and "nothing can
run" are both true at once, and name two different configurations that produce this symptom.

**2.** This lab created two IAM roles with different trust policies. Explain what would actually break
if you swapped them - gave the cluster role's trust policy to the node role and vice versa - and say
at what point in Steps 6 to 11 you would notice, **assuming you were on real AWS rather than Floci.**

**3.** Students routinely conflate a **Service** with a **Deployment**, and separately conflate a
**readiness probe** with a **liveness probe**. Take one of those pairs. Explain the distinction, then
describe a concrete failure that occurs when you get it backwards and would not occur if you had it
right.

**4.** Step 18 rolled `usms-enrolment` back, and the rolled-back pod still reported version `1.1.0`.
Explain why, and then argue either for or against the proposition that Kubernetes rollback is
therefore "not really a rollback". Whichever side you take, name the practice that resolves the
problem.

**5.** `usms-enrolment` uses `maxUnavailable: 0`; `usms-results` uses the default. Describe what each
policy does during an update of a two-replica Deployment, and give one workload for which each is the
better choice. Then say which of them is closer to Lab 04's ECS deployment configuration, and why.

**6.** A colleague proposes storing the USMS database password in a Kubernetes Secret and says "it's
encrypted, so it's fine to commit the manifest". Correct them precisely: say what a Secret does
provide, what it does not, and what you would do instead on real EKS. Reference the demonstration in
Step 17.

**7.** Practical 2 built this application on ECS; this lab built it on Kubernetes. For the University
Student Management System specifically - a small team, one region, a workload that is quiet for eight
months and very busy for two - argue for one platform over the other. Your answer must name at least
two things this lab was **harder** than Lab 04, and at least one thing Kubernetes gave you that ECS
could not.

---

## 16. What We Built

### 16.1 Reflection

The reason this laboratory is longer than Lab 04 is not that Kubernetes is worse. It is that EKS
gave you back a data plane. Fargate took the machines away and, with them, most of the decisions;
Steps 5, 7 and 10 exist because you own nodes again, and every one of them was a decision Lab 04
never asked you to make.

What you get in exchange is visible in Step 16. The gateway's configuration contains two DNS names
and no addresses. Pods die, pods start, the ReplicaSet replaces them, endpoints are rewritten, and
nothing anywhere had to be told. Lab 05 achieved the equivalent with an ALB, a target group, a
listener and a service integration - four AWS objects, each with its own console page. Kubernetes did
it with one object type and a DNS record, and it would do it identically on any conformant cluster
anywhere.

The single most important thing to carry forward is the `spec` and `status` loop from Step 12. You
never told Kubernetes to *do* anything in this lab. You wrote down what should be true, and
controllers made it true and then wrote down what actually was. `replicas: 2` is not an instruction to
start two pods; it is a statement about the world that a controller is responsible for maintaining.
Once that clicks, `HorizontalPodAutoscaler` in Lab 08 is not a new idea - it is one more controller,
writing to one more field, in exactly the same loop.

And Step 7 is the sentence worth remembering from the whole of Practical 2 and Practical 4 together.
One policy document, written in Lab 1 for a service that did not exist yet, attached without
modification to an EC2 instance profile, a Fargate task role and a Kubernetes node role. Compute
models come and go faster than the question "what may this code do to student data?".

### 16.2 KEEP and CLEAN UP

```text
╔══════════════════ KEEP ══════════════════╗    ╔═══════════ CLEAN UP ═══════════╗
║ usms-eks-cluster        Lab 08 needs it ║    ║ pod usms-toobig      Step 19   ║
║ usms-eks-nodes          Lab 08 Step 10  ║    ║ pod usms-crasher     Step 19   ║
║ the _lb_ports_ tag      Lab 08 Step 15  ║    ║ pod usms-broken      Exercise 3║
║ namespace usms          all of Lab 08   ║    ║ manifests/*.bak      sed -i.bak║
║ usms-enrolment + its cpu request         ║    ║ any usms-debug pod left over   ║
║ usms-results, usms-gateway               ║    ║   (--rm should have removed it)║
║ all four ConfigMaps                      ║    ╚════════════════════════════════╝
║ usms-enrolment-secret                    ║
║ usms-eks-cluster-role, usms-eks-node-role║
║ USMSEKSClusterPolicy, USMSEKSNodePolicy  ║
║ usms-eks-cluster-sg                      ║
║ configs/lab-07.env                      ║
║ everything from Labs 01, 02, 03, 04-C   ║
╚══════════════════════════════════════════╝
```

Clean up now:

```bash
kubectl delete pod usms-toobig usms-crasher --ignore-not-found -n usms
kubectl delete deployment,service usms-broken --ignore-not-found -n usms
kubectl get pods -n usms
rm -f manifests/lab-07/*.bak
```

**What to look for:** five pods and nothing else - two enrolment, two results, one gateway. Six if you
did Exercise 1.

Do **not** run `scripts/cleanup/lab-07-cleanup.sh`, `lab-04-cleanup.sh`, `lab-03-cleanup.sh` or
`lab-02-cleanup.sh`. They are for the end of the course, in the order given in each lab's Section 9.3.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02, Lab 04 and this lab's Step 8
  usms-ec2-app-role + usms-ec2-app-profile   attached to usms-web-01
  usms-lambda-exec-role ................ waiting for Lab 07
  USMSStudentDataReadWrite ............. now on THREE roles, naming a bucket that
                                         still does not exist. Lab 10 changes that
  usms-eks-cluster-role -> USMSEKSClusterPolicy               <- new
  usms-eks-node-role    -> USMSEKSNodePolicy                  <- new
                        -> USMSStudentDataReadWrite (unchanged)

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
                 ^ both are in the EKS cluster's resourcesVpcConfig
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                 ^ both hold the EKS node group                -> usms-s3-endpoint
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg,
               usms-private-nacl, usms-eks-cluster-sg          <- new

Lab 03  COMPUTE - instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
  usms-db-01    private subnet a  usms-db-sg
  usms-web-golden  AMI

Lab 06   COMPUTE - containers you operate, the ECS way
  usms-ecs-cluster / usms-enrolment-svc / usms-enrolment:2
  usms-enrolment-alb -> usms-enrolment-tg -> the service's tasks
  scalable target service/usms-ecs-cluster/usms-enrolment-svc  min 2 max 10
  /usms/ecs/enrolment  retention 7 days
     ^ STILL RUNNING. This lab did not replace it; it built the alternative alongside

Lab 07  COMPUTE - containers you operate, the Kubernetes way   <-- you are here
  usms-eks-cluster        k8s 1.30, 4 subnets, sg usms-eks-cluster-sg
    tags Project=USMS Tier=app Lab=07 Name=usms-eks-cluster _lb_ports_=8081,8082
    └── usms-eks-nodes    private-a + private-b, min 2 / max 4 / desired 2
                          labels workload=usms tier=app
  namespace usms
    Deployment usms-gateway    1 replica   -> Service ClusterIP
      proxies /enrolment/ and /results/ BY DNS NAME, no addresses anywhere
    Deployment usms-enrolment  2 replicas  -> Service ClusterIP, 2 endpoints
      requests cpu=50m mem=32Mi   <- Lab 08's HPA divides by this
      readiness + liveness on /healthz, strategy maxUnavailable 0 / maxSurge 1
    Deployment usms-results    2 replicas  -> Service ClusterIP, 2 endpoints
      default strategy 25% / 25%  <- deliberately different from enrolment
    ConfigMaps usms-app-config, usms-enrolment-conf, usms-results-conf, usms-gateway-conf
    Secret usms-enrolment-secret     base64, not encrypted, and you proved it
    ServiceAccount usms-enrolment-sa  annotated for IRSA on real AWS only
  NOTHING outside the cluster can reach any of it. That is Lab 08's subject

Lab 08  SCALING AND EXPOSURE (next)
  replicas by hand -> HPA -> node group scaling
  ClusterIP -> port-forward -> NodePort -> LoadBalancer -> Ingress

Lab 09  SECURITY
  least-privilege review of the IAM and security-group estate built so far

Lab 10  Lambda
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real for
                        THREE roles at once. Lambda creates it inline; there is
                        no separate storage lab
  then DynamoDB · RDS · SNS/SQS · CloudWatch · CloudFormation
```

---

## 17. Preparation for the Next Lab

Lab 08 - `lab-08-eks-scaling.md` - takes the three services you just deployed and answers the two
questions this lab deliberately left open: **how do they grow**, and **how does anybody outside the
cluster reach them?** It creates no new microservice, registers no new image, and renames nothing.

| From `configs/lab-07.env` | Lab 08 uses it for |
| --- | --- |
| `USMS_EKS_CLUSTER` | Every `aws eks` call, and the kubeconfig context |
| `USMS_EKS_NODEGROUP` | `update-nodegroup-config`, Step 10 - the data-plane half of scaling |
| `USMS_EKS_NAMESPACE` | Every `kubectl` call |
| `USMS_EKS_LB_PORTS` | **Step 15 cannot expose a LoadBalancer Service without it.** This is the one that bites |
| `USMS_K8S_DEPLOY_ENROLMENT` | The Deployment the HorizontalPodAutoscaler targets |
| `USMS_K8S_DEPLOY_GATEWAY` | The Deployment whose Service becomes a NodePort, then a LoadBalancer |
| `USMS_K8S_CPU_REQUEST` | Checking the HPA's arithmetic instead of trusting it |
| `USMS_EKS_ENDPOINT` | Confirming `kubectl` is pointed at the right cluster after a restart |

| From earlier labs | Lab 08 uses it for |
| --- | --- |
| Lab 02 `USMS_PUBLIC_SUBNET_A` and `-B` | Where a real EKS LoadBalancer Service would place its nodes. Compare with Lab 05, which required exactly the same pair |
| Lab 05 `usms-enrolment-alb` | The direct comparison in Section 12 - the same job, an entirely different control plane |
| Lab 06's scalable target | The comparison that Section 3 of that lab is built on: one integer, two very different machines for moving it |
| Lab 01 `USMSStudentDataReadWrite` | Unchanged. Still on three roles, still naming nothing |

**The connection to state out loud before the next session.** Lab 06 handed `desiredCount` to
Application Auto Scaling - an AWS service, outside the workload, writing one integer through an AWS
API. Lab 08 hands `replicas` to a HorizontalPodAutoscaler - a controller **inside the cluster**,
reading a metrics API **inside the cluster**, writing one integer through the Kubernetes API. The
architecture is identical and the blast radius is not. When you write your comparison, that is the
distinction that earns marks: not "both of them scale", but *where the thing doing the scaling lives,
and what happens to it when the control plane you do not own has a bad afternoon.*

**Before the next session, confirm all six of these:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-04.sh | tail -2
./scripts/utilities/verify-lab-07.sh | tail -2
grep -c '^export' configs/lab-07.env
kubectl get deploy -n usms -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas'
kubectl get deploy usms-enrolment -n usms \
  -o jsonpath='{.spec.template.spec.containers[0].resources.requests.cpu}'; echo
aws eks describe-cluster --name usms-eks-cluster --query 'cluster.tags._lb_ports_' --output text
```

You want: `FAIL=0` from the first (or `FAIL=1` if you never did Lab 05 Exercise 2, which that lab
says is expected); `FAIL=0` from the second on Path A or `FAIL=3` on Path B; a count of **21**; three
Deployments reading `2`, `2` and `1`; the string `50m`; and `8081,8082`.

The last two are the ones to care about. **An empty CPU request means Lab 08's HPA will report
`<unknown>` and never scale**, and no amount of load generation will fix it. **A missing `_lb_ports_`
tag means Lab 08 Step 15 has no host port to publish on**, and the remedy is to recreate the cluster.
Both are five-minute fixes today and hour-long fixes next week.

**Read ahead, five minutes:** find out what the Kubernetes **metrics API** is, and why it is an
optional add-on rather than part of the core. Then look up the three values of a Service's `type`
field. Lab 08 assumes neither, but it moves considerably faster if the words are not new.

Finally, take a snapshot so that a mistake in Lab 08 is recoverable:

```bash
floci snapshot save lab-07-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback - and stop Floci
first, because archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-07.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

Keep the archive **outside** the repository so it is never a commit candidate.

---

## Appendix A - Command Reference

**Environment**

| Command | Purpose |
| --- | --- |
| `./scripts/setup/floci-up.sh` | Start or resume Floci. The only supported way |
| `./scripts/setup/floci-down.sh` | Stop Floci, keeping all state |
| `./scripts/utilities/whoami.sh` | Identity and endpoint; exits 1 if the account is wrong |
| `./scripts/utilities/floci-storage-check.sh` | Six read-only checks that name a persistence failure |
| `./scripts/utilities/eks-support-probe.sh` | This lab's Step 2 - which support path you are on |
| `./scripts/utilities/verify-lab-07.sh` | This lab's 30 checks |

**AWS - EKS**

| Command | Purpose |
| --- | --- |
| `aws eks create-cluster --cli-input-json file://...` | Create a cluster from a JSON request body |
| `aws eks list-clusters` | Every cluster name. Used in Step 22 to re-derive rather than assume |
| `aws eks describe-cluster --name X` | Status, version, endpoint, VPC config, tags, OIDC issuer |
| `aws eks wait cluster-active --name X` | Client-side poll until `ACTIVE` |
| `aws eks tag-resource --resource-arn ... --tags k=v` | Add tags after creation. Takes an **ARN**, not a name |
| `aws eks create-nodegroup --cli-input-json file://...` | Create a managed node group |
| `aws eks list-nodegroups --cluster-name X` | Node group names for a cluster |
| `aws eks describe-nodegroup --cluster-name X --nodegroup-name Y` | Status, scaling config, subnets, node role |
| `aws eks update-kubeconfig --name X --alias Y` | Write cluster, user and context into `~/.kube/config` |
| `aws eks delete-nodegroup` / `delete-cluster` | Teardown, in that order. Section 9.3 |

**AWS - IAM and EC2 used here**

| Command | Purpose |
| --- | --- |
| `aws iam create-role --assume-role-policy-document file://...` | Create a role from a trust policy |
| `aws iam update-assume-role-policy` | Fix a trust policy without recreating the role |
| `aws iam create-policy --policy-document file://...` | Create a customer managed policy |
| `aws iam attach-role-policy` | Attach a managed policy to a role |
| `aws iam list-attached-role-policies --role-name X` | What is this role carrying? |
| `aws iam list-entities-for-policy --policy-arn X` | Who is carrying this policy? |
| `aws iam list-policies --scope Local` | Customer managed policies only |
| `aws ec2 create-security-group --vpc-id ...` | A group in a **named** VPC, never the default |
| `aws sts assume-role --role-arn ... --role-session-name ...` | Take on `usms-developer-role` for the build |

**kubectl - reading**

| Command | Purpose |
| --- | --- |
| `kubectl config current-context` / `get-contexts` | Which cluster am I talking to? |
| `kubectl cluster-info` | One authenticated call. The `whoami.sh` of Kubernetes |
| `kubectl get nodes -o wide` | Does the data plane exist and is it `Ready`? |
| `kubectl get all -n usms` | Common workload types. **Not** ConfigMaps, Secrets or Ingresses |
| `kubectl get endpoints <svc>` | Which pods is this Service sending traffic to *right now*? |
| `kubectl describe pod <name>` | Why is it in that phase? The `Events` block is the answer |
| `kubectl logs <pod> [--previous]` | What did the application say? `--previous` for a restarted container |
| `kubectl get events -n usms --sort-by=.lastTimestamp` | The last hour, in order |
| `kubectl api-resources --namespaced=true -o name` | What nouns does this cluster know? |
| `kubectl auth can-i <verb> <resource>` | Am I allowed to? |

**kubectl - changing**

| Command | Purpose |
| --- | --- |
| `kubectl apply -f <file or dir>` | Declarative create-or-update. Directories apply in lexical order |
| `kubectl apply --dry-run=client -f ...` | Validate without a cluster. Path C's whole toolkit |
| `kubectl create <x> --dry-run=client -o yaml` | Generate a manifest instead of an object |
| `kubectl set image deployment/X c=img` | Change one image; triggers a rollout |
| `kubectl set env deployment/X --from=secret/Y` | Add an env source; a template change, so it rolls |
| `kubectl rollout status deployment/X` | Block until the roll finishes or times out |
| `kubectl rollout history deployment/X` | Revisions kept, up to `revisionHistoryLimit` |
| `kubectl rollout undo deployment/X [--to-revision=N]` | Scale an old ReplicaSet back up |
| `kubectl rollout restart deployment/X` | Roll without changing anything else |
| `kubectl config set-context --current --namespace=usms` | Stop typing `-n usms` |
| `kubectl run X --rm -it --restart=Never --image=...` | A throwaway pod. `--rm` deletes it on exit |
| `kubectl delete pod X --ignore-not-found` | Idempotent delete, safe in scripts |

---

## Appendix B - New JMESPath, `kubectl` and CLI patterns introduced

**JMESPath**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `Policies[?PolicyName=='X'].Arn \| [0]` | Filter a list, take the field, collapse to a scalar | Steps 6, 7, 23 |
| `clusters[?@==\`usms-eks-cluster\`] \| [0]` | `@` is the current element. Filtering a list of **strings**, not objects. Backticks make a literal | Step 22 |
| `cluster.tags._lb_ports_` | Reaching a map entry whose key contains underscores | Steps 9, 23 |
| `cluster.identity.oidc.issuer` | Deep path that legitimately returns `None` | Step 21 |

**AWS CLI**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `--cli-input-json file://...` | The entire request body as a committed JSON file. Avoids shorthand ambiguity in nested structures | Steps 8, 10 |
| `aws <service> wait <state>` with a `\|\|` fallback loop | Waiters are client-side. If one is unimplemented, write the poll | Steps 9, 10 |
| `cmd 2>/dev/null \|\| lookup` | Makes a create step idempotent: create, or find what already exists | Steps 6, 7 |
| `--scope Local` | Customer managed policies only, excluding hundreds of AWS managed ones | Steps 6, 7, 23 |

**`kubectl`**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `-o jsonpath='{.status.readyReplicas}'` | One field, unquoted, ideal for `test` in a script | Section 9 |
| `-o custom-columns='NAME:.metadata.name,READY:...'` | Build exactly the table you want. JMESPath's job, `kubectl`'s syntax | Steps 14, 18, 22 |
| `--dry-run=client -o yaml` | Generate the manifest an imperative command *would* have created | Steps 17, 21 |
| `-l app=usms-enrolment` | Label selector. The universal filter across every `kubectl get` | Steps 13, 19 |
| `--show-labels` | Print the labels a selector would have to match | Step 12, Troubleshooting |
| Numeric filename prefixes `00-`, `10-`, `20-` | Directory applies in lexical order; this is how you order dependencies | Section 7 |
| `---` between objects in one file | Several objects, one file, one microservice | Steps 13, 14, 15 |

**Shell**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `<< 'EOF'` quoted heredoc | No expansion. **Policy documents and Kubernetes manifests** | Steps 4, 5, 12–17 |
| `<< EOF` unquoted heredoc | Expand now. **Request bodies and `configs/lab-NN.env`** | Steps 8, 10, 23 |
| `set -uo pipefail` without `-e` | A script that must *report* failures cannot abort on the first one | Steps 2, Section 9 |
| `sed -i.bak` | Works on both GNU and BSD `sed`. Plain `-i` does not | Step 18 |
| `base64 -d` / `-D` | GNU and BSD differ. So do `date`, `readlink` and `stat` | Step 17 |
| `tee` | Write to a file and to the screen. Keeps evidence without hiding it | Steps 2, 9, 22 |

---

## Sources

- Amazon EKS User Guide - clusters, node groups, IAM roles, IRSA and `update-kubeconfig`:
  [docs.aws.amazon.com/eks](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html)
- Connecting `kubectl` to an EKS cluster:
  [docs.aws.amazon.com/eks - create-kubeconfig](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- AWS CLI reference for `aws eks`:
  [awscli.amazonaws.com - eks](https://docs.aws.amazon.com/cli/latest/reference/eks/)
- Kubernetes documentation - Deployments, Services, ConfigMaps, Secrets, probes and DNS:
  [kubernetes.io/docs/concepts](https://kubernetes.io/docs/concepts/)
- LocalStack EKS provider - k3d-backed clusters, `_lb_ports_`, node groups and known limitations,
  which is the emulator behaviour this course calls Floci:
  [docs.localstack.cloud - EKS](https://docs.localstack.cloud/aws/services/eks/)
- k3d documentation - `cluster create`, `kubeconfig`, and `image import` for offline laboratories:
  [k3d.io](https://k3d.io/)
- Official `nginx` Docker image - the `/etc/nginx/templates` envsubst behaviour used by all three
  microservices: [hub.docker.com/_/nginx](https://hub.docker.com/_/nginx)

*Compiled for DSO303, Royal Thimphu College / CST, RUB. Laboratory content verified against Floci's
documented EKS behaviour and the AWS CLI reference; output shown in this document is illustrative and
labelled as such throughout.*
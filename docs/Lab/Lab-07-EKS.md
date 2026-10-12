# Lab 07 - Deploying a Microservices Application on Amazon EKS

## 1. Objectives

- Create an EKS cluster and a managed node group in Lab 2's VPC, each with its own IAM role.
- Point `kubectl` at the cluster and deploy three microservices (`usms-gateway`, `usms-enrolment`, `usms-results`) from declarative manifests.
- Prove the services discover each other by DNS name, then perform a rolling update, a rollback and three deliberate failure diagnoses.
- Use a ConfigMap and a Secret, and demonstrate what a Secret does not protect.
- Prove the cluster survives a restart and save its identifiers to `configs/lab-07.env` for Lab 08.

**Time:** roughly 4 hours, including the exercises.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane) ·
    [Kubernetes objects compared with ECS](../unit3/topic1.md#kubernetes-objects-compared-with-ecs) ·
    [how a node joins the cluster](../unit3/topic1.md#how-a-node-joins-the-cluster) ·
    [the Amazon VPC CNI](../unit3/topic1.md#the-amazon-vpc-cni) ·
    [Services, CoreDNS and kube-proxy](../unit3/topic1.md#services-coredns-and-kube-proxy) ·
    [cluster access](../unit3/topic1.md#cluster-access-authentication-versus-authorisation) ·
    [Kubernetes Secrets](../unit3/topic1.md#secrets) ·
    [manifests](../unit3/topic2.md#manifests) ·
    [requests and limits](../unit3/topic2.md#requests-and-limits) ·
    [probes](../unit3/topic2.md#probes) ·
    [managed node groups](../unit3/topic3.md#eks-managed-node-groups) ·
    [IAM roles](../unit8/topic1.md#iam-roles) ·
    [IRSA versus EKS Pod Identity](../unit8/topic1.md#irsa-versus-eks-pod-identity) ·
    [envelope encryption](../unit8/topic3.md#envelope-encryption)

---

## 2. Prerequisites

- Labs 01 to 04 complete; `./scripts/utilities/verify-lab-02.sh` reports `FAIL=0`.
- All four Lab 2 subnets in `configs/lab-02.env`, including `USMS_PUBLIC_SUBNET_B` (Lab 2 Step 11 "Your turn") and `USMS_PRIVATE_SUBNET_B` (Lab 2 Exercise 5). EKS refuses a cluster confined to one Availability Zone, and Step 8 fails with an unhelpful error otherwise.
- About 2 GB of free RAM and 3 GB of disk for the Kubernetes node containers (Docker Desktop: Settings, Resources, Memory). A memory-starved cluster leaves pods `Pending` rather than failing loudly.

| Tool | Needed for | Check |
| --- | --- | --- |
| Docker Engine or Docker Desktop | Floci, and the Kubernetes node containers | `docker version` |
| AWS CLI v2 | Every AWS-side step | `aws --version` |
| `kubectl` | Everything from Step 11 onward | `kubectl version --client` |
| `k3d` | Only on support Path B | `k3d version` |
| `python3` | Validating JSON, as in earlier labs | `python3 --version` |
| `jq` (optional) | Reading manifests; every command below has a `--query` alternative | `jq --version` |

`kubectl` is the one new tool. Install it before the session:

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

`kubectl version --client` must print a client version and must not hang. If it hangs, you omitted `--client` and it is trying to reach a cluster.

---

## 3. What This Lab Reuses

From Lab 1:

- `usms-developer-role`: assumed in Step 8 to create the cluster.
- `USMSStudentDataReadWrite`: attached unchanged to `usms-eks-node-role` in Step 7, its third holder after Lab 3's instance role and Lab 4's task role.

From Lab 2:

- All four subnets: the cluster's `resourcesVpcConfig` in Step 8; the two private subnets hold the node group in Step 10.
- `usms-vpc` and `USMS_VPC_CIDR`: the cluster security group is created in it in Step 6.

From Lab 4:

- `usms-ecs-cluster` and `usms-enrolment-svc`: the side-by-side comparison in Step 20 and Section 11.

```text
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

---

## 4. What We Are Building

Three microservices in one namespace, deployed declaratively into a Kubernetes cluster that lives in Lab 2's network. The Kubernetes objects are portable to any conformant cluster; the AWS plumbing (IAM roles, VPC, node group) is not.

```text
A student clicks "Register for this module" in the USMS portal.

   the request arrives at        usms-gateway     (1 pod,  nginx reverse proxy)
   which forwards /enrolment/ to usms-enrolment   (2 pods, returns JSON with its own pod name)
   and forwards   /results/   to usms-results     (2 pods, returns JSON with its own pod name)

Nothing in usms-gateway's configuration contains an IP address.
It contains two DNS names, and the cluster keeps them pointing at healthy pods.
```

Everything in this lab is reachable only from inside the cluster. Autoscaling, NodePort, LoadBalancer and Ingress are Lab 08's job.

---

## 5. Architecture

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
Section 4, drawn.

---

## 6. Directory Structure

This lab adds the following. It restructures nothing, and it needs one new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-07-eks/
│       ├── README.md                          # this document
│       └── exercises.md                       # Section 12
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
│   │   ├── verify-lab-07.sh                  # NEW - Section 8
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

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Capture every identifier with `$(...)`, `--query` and `--output text`. Step 23 writes them to `configs/lab-07.env` for Lab 08.

!!! warning "`kubectl` has its own idea of where you are"
    The **context** in `~/.kube/config` (outside the repository) decides which cluster and namespace `kubectl` talks to. Step 11 sets it. If a `kubectl` command behaves strangely, run `kubectl config current-context` first.

### Step 1 - Start the environment and confirm the ground you are standing on

Nothing here is worth starting if Lab 2's subnets are missing or Floci is in memory mode.

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

`course.env` must be sourced first: it sets `AWS_PROFILE` and `COURSE_ROOT`, and later env files build on it.

**Expected result**

```text
Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Region   : us-east-1
```

> Example output - your `Identity` line may differ if you left an assumed role in the environment.

If `Account` is not `000000000000`, `whoami.sh` exits 1. Stop and fix that first.

**Verify**

```bash
./scripts/utilities/verify-lab-02.sh | tail -2
./scripts/utilities/verify-lab-04.sh | tail -2

echo "public-a=$USMS_PUBLIC_SUBNET_A"
echo "public-b=$USMS_PUBLIC_SUBNET_B"
echo "private-a=$USMS_PRIVATE_SUBNET_A"
echo "private-b=$USMS_PRIVATE_SUBNET_B"
```

You want `FAIL=0` from `verify-lab-02.sh` and four subnet IDs, all beginning `subnet-`, none empty or `None`. If either `-b` subnet is empty, do Lab 2 Step 11's "Your turn" task and Lab 2 Exercise 5, then regenerate `configs/lab-02.env` from Lab 2 Step 24.

`verify-lab-04.sh` reporting `FAIL=1` is expected if you never did Lab 05 Exercise 2. Any other failure is real.

---

### Step 2 - Probe what your build actually supports, and record the answer

Kubernetes emulation is the least uniform part of Floci. Floci starts a genuine k3s cluster (via k3d) and emulates only the AWS-facing `eks` API, so the Kubernetes half of this lab is real. When a step fails, first ask which half it belonged to.

| Path | What it means | How the lab proceeds |
| --- | --- | --- |
| **A** | `aws eks create-cluster` works and starts a cluster | Everything as written. The AWS half and the Kubernetes half both run |
| **B** | The `eks` API is absent or refuses; `k3d` is available | You create the cluster with `k3d` directly in Step 8B. Steps 6, 7 and 22 still create the IAM objects, so the ledger and Lab 08 still hold. Steps 10 and 22 note what is unavailable |
| **C** | Neither works | You cannot run Steps 8 to 21. Do Section 7.4's paper path: write every manifest, validate them client-side, and answer Section 14 in full. This is a genuine outcome, not a failure - record it |

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
  echo "PATH C  - manifests and reasoning only (Section 7.4)"
fi
EOF

chmod +x scripts/utilities/eks-support-probe.sh
./scripts/utilities/eks-support-probe.sh | tee outputs/lab-07-support-probe.txt
```{% endraw %}
````

`aws eks list-clusters` is the cheapest `eks` call and fails fast if unimplemented. The script uses `set -uo pipefail` without `-e`, because a script that aborts on the first failure cannot report failures.

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

**Verify** - record the verdict in your notes:

```bash
mkdir -p notes
{
  echo "## Lab 07 support path"
  echo "Probed on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  grep -A1 '== Verdict ==' outputs/lab-07-support-probe.txt | tail -1
} >> notes/lab-07-notes.md

tail -3 notes/lab-07-notes.md
```

A line beginning `PATH A`, `PATH B` or `PATH C` must appear. From here on, wherever a step is labelled **Path A** or **Path B**, do the one that matches.

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

Every command from Step 6 onward acts on either the control plane or the data plane. Nothing to run; read this, then answer the question in `notes/lab-07-notes.md`. Background: [control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane).

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

Three consequences appear later in this lab:

1. **An `ACTIVE` cluster with no node group runs nothing.** Step 10 supplies the nodes; Troubleshooting entry 4 is the symptom.
2. **Two IAM roles, not one.** The cluster role is assumed by the AWS-run control plane; the node role by your EC2 instances. They trust different principals and are never interchangeable (Steps 6 and 7).
3. **Upgrading is two operations:** `aws eks update-cluster-version`, then `aws eks update-nodegroup-version`.

On ECS with Fargate the right-hand column is nearly empty, which is why Lab 04 was shorter.

✏️ **Your turn**

In `notes/lab-07-notes.md`, answer in two or three sentences: *a colleague says "EKS is just ECS
with different names". Name one thing in the table above that makes that statement false, and one
thing that makes it nearly true.*

```text
Expected result:
Two short paragraphs in your notes. No commands, no output. Section 14 Question 1
asks a harder version of this, so a good answer here is worth the four minutes.
```

---

### Step 4 - Write the two trust policies

A role has a trust policy (who may assume it) and permissions policies (what it may then do). This step writes the trust policies for both roles.

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

- **Quoted heredoc** (`<< 'EOF'`): policy documents may contain literal `$` sequences the shell must not expand. Step 8 deliberately uses the unquoted form.
- `eks.amazonaws.com` is the EKS control plane; `ec2.amazonaws.com` is EC2 acting for an instance. A node is an EC2 instance, so `trust-eks-node.json` matches Lab 1's `trust-ec2.json`; it gets its own name so each role's document is obvious.

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

You want `eks.amazonaws.com` and `ec2.amazonaws.com` respectively, each with `sts:AssumeRole`. If both name the same service you copied one heredoc twice, and Step 10 will fail on node registration.

---

### Step 5 - Write the two permissions policies

On real AWS you would attach AWS managed policies. Floci may not carry them, so you write local equivalents and see what those policies contain.

| Real AWS managed policy | Attached to | What it lets that principal do |
| --- | --- | --- |
| `AmazonEKSClusterPolicy` | the cluster role | Manage ENIs, security groups and load balancers in your VPC on the cluster's behalf |
| `AmazonEKSWorkerNodePolicy` | the node role | Let a kubelet describe the cluster and register itself |
| `AmazonEKS_CNI_Policy` | the node role | Let the VPC CNI plugin attach ENIs and assign secondary addresses to pods |
| `AmazonEC2ContainerRegistryReadOnly` | the node role | Pull images from ECR |

On EKS, pods get real VPC IP addresses from your subnets via the [VPC CNI](../unit3/topic1.md#the-amazon-vpc-cni), which is why the node policy needs ENI actions.

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

- `"Resource": "*"` on the EC2 network actions is justified: the ENIs do not exist until the CNI creates them, so their ARNs are unknowable in advance.
- `WriteContainerLogs` is the counter-example: its log-group ARN is knowable, so it is named (`/usms/eks/*`), as Lab 04 did for `/usms/ecs/enrolment`.
- The trailing region `Deny` mirrors `USMSDeveloperBase`. An explicit `Deny` always wins over any `Allow`.

!!! note "Floci Limitation - policies are stored, not enforced"
    Floci stores and returns every statement above but does not evaluate them against API calls.

    On real AWS, a cluster role without `ec2:CreateNetworkInterface` fails to create, and a node role without `eks:DescribeCluster` joins but never becomes `Ready`.

    Judge these documents by reading them, not by whether a command succeeded.

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

The cluster policy shows three statements and the node policy five, each ending with `Deny`.

---

### Step 6 - Create the cluster role and the cluster security group

The control plane needs an identity in your account, and its endpoint needs a firewall. The CLI does not create either for you.

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

- The `||` fallback makes the step re-runnable: if `create-policy` fails with `EntityAlreadyExists`, the ARN is looked up instead. `| [0]` turns the one-element list into a scalar.
- `--scope Local` limits `list-policies` to customer managed policies.

On real AWS you would attach the managed policy instead (note the account field `aws`, which marks an AWS managed policy):

```bash
# Real AWS. Do not run this here; the managed policy may not exist on your build.
aws iam attach-role-policy \
  --role-name usms-eks-cluster-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
```

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

- `--vpc-id "$USMS_VPC_ID"` is essential. Without it the group lands in the default VPC, and Step 8 only reports that the security group is invalid for the subnets.
- TCP 443 (the Kubernetes API speaks HTTPS) from the VPC CIDR only, unlike Lab 05's public `usms-alb-sg`: this group fronts an administrative API.

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

You want `USMSEKSClusterPolicy`; `eks.amazonaws.com` (if it says `ec2.amazonaws.com`, fix it now with `aws iam update-assume-role-policy`); and a `Vpc` equal to `$USMS_VPC_ID` with `Ports` containing `443`.

---

### Step 7 - Create the node role, and attach Lab 1's policy to it

The nodes need their own identity, and Lab 1's `USMSStudentDataReadWrite` gains its third holder (see Section 3).

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

The ARN is looked up by name, not typed, so the script would also work in a real account. `list-entities-for-policy` answers "who carries this policy right now?".

**Expected result**

```text
USMSStudentDataReadWrite = arn:aws:iam::000000000000:policy/USMSStudentDataReadWrite
usms-ec2-app-role	usms-ecs-task-role	usms-eks-node-role
```

> Example output - the order of the three role names may differ.

Three roles, one policy, never edited: an EC2 instance profile (Lab 3), a Fargate task role (Lab 4) and now an EKS node role.

!!! note "Floci Limitation - a node role is the coarse way to do this, and real EKS has a finer one"
    A policy on the node role reaches **every pod on every node**, because pods inherit the node's instance credentials.

    Real EKS uses IRSA (IAM Roles for Service Accounts) so only pods using an annotated ServiceAccount get the role. Step 21 shows the commands and why they will not complete here.

    On EKS, "which pod may touch the bucket?" is a real question; the node role is the answer you use before answering it properly.

**Verify**

```bash
aws iam list-attached-role-policies --role-name usms-eks-node-role \
  --query 'AttachedPolicies[].PolicyName' --output text

aws iam get-role --role-name usms-eks-node-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text
```

You want `USMSEKSNodePolicy` and `USMSStudentDataReadWrite`, and the service `ec2.amazonaws.com`. A node role trusting `eks.amazonaws.com` is the most common error in this lab; fix it with:

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

This is the step the previous seven were for. Read the `_lb_ports_` note even if you are impatient.

The request body goes in a file via `--cli-input-json` (met in Lab 3): it avoids shorthand ambiguity in nested lists and leaves a committed record of what was asked for.

**The `_lb_ports_` tag** tells Floci which host ports to publish for `LoadBalancer` Services and Ingresses. It must be set **at cluster creation**; without it Lab 08 Step 15 cannot reach anything, and the fix is to recreate the cluster and redo Steps 8 to 22.

!!! note "Floci Limitation - `_lb_ports_` is emulator control, not AWS configuration"
    Floci treats the cluster tag `_lb_ports_` as an instruction about host port publishing.

    Real AWS treats it as an ordinary tag and does nothing with it; a `LoadBalancer` Service there provisions a real load balancer.

    Emulators sometimes overload a real API field to carry a local control.

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

!!! warning "Unquoted heredoc here, on purpose"
    `<< EOF` expands `$VAR` and `$(...)` at write time, so the file contains real IDs. A quoted heredoc here leaves literal `$USMS_PRIVATE_SUBNET_A` and `create-cluster` fails; an unquoted one in Step 5 would silently empty `${...}` policy variables.

All four subnets go in the cluster config (two AZs, and public subnets for Lab 08's internet-facing load balancer). The **nodes** go only in the private subnets (Step 10).

**Command - part 2, assume the developer role and create the cluster**

```bash
CREDS=$(aws sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/usms-developer-role" \
  --role-session-name lab07-eks-build \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)

export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | cut -f1)
export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | cut -f2)
export AWS_SESSION_TOKEN=$(echo "$CREDS" | cut -f3)

aws sts get-caller-identity
```

!!! warning "This is the one deliberate exception to the credentials rule"
    `sts assume-role` returns credentials as environment variables, which outrank profiles. Part 4 removes them; it is not optional. Lab 04 Step 4 made the same exception.

**Command - part 3 (Path A), create the cluster**

```bash
aws eks create-cluster \
  --cli-input-json file://templates/lab-07-create-cluster.json \
  --query 'cluster.{Name:name,Status:status,Version:version,Arn:arn}' \
  --output table
```

**Command - part 3 (Path B), create the cluster with k3d instead**

Only if Step 2 gave you Path B. This creates a real Kubernetes cluster with the same name, so every `kubectl` step from Step 12 onward works unchanged; you lose the `aws eks` half.

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

Step 9 verifies this step; there is nothing useful to check until creation finishes.

---

### Step 9 - Wait for the cluster, and read what it tells you

Cluster creation is asynchronous: 10 to 15 minutes on real AWS, one to four locally. A waiter is a client-side poll loop the CLI ships; Floci may implement `describe-cluster` but not the waiter, so the fallback loop does the same job.

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

The loop has a ten-minute ceiling. It deliberately avoids `set -e`: with `set -Eeuo pipefail` active, the first failing `describe-cluster` would kill your shell.

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

Check, in order:

- `Status` is `ACTIVE`.
- `Subnets` has **four** entries and `Vpc` equals `USMS_VPC_ID`.
- `Endpoint` is a URL; it is the address `kubectl` will use.
- `Tags` contains `_lb_ports_`. **If not, fix it before Step 10.**

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

A healthy control plane with no data plane runs nothing. This step supplies the nodes and is the last AWS-side creation. A [managed node group](../unit3/topic3.md#eks-managed-node-groups) is EKS-owned capacity: you declare min, max and desired; AWS supplies the AMI and drains on upgrade.

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

Nothing to run: `k3d cluster create --agents 2` in Step 8 made the nodes. Record in your notes that `usms-eks-nodes` does not exist as an AWS object, so Lab 08 Step 10 is unavailable to you; Lab 08 Steps 4 to 9 are unaffected.

- `scalingConfig` is the same min/max/desired trio as Lab 06, but nothing moves `desiredSize` unless you install a cluster autoscaler. Lab 08 Step 10 changes it by hand.
- `labels` are **Kubernetes** node labels (Lab 08 uses `workload=usms` in a `nodeSelector`); `tags` are AWS tags.
- `t3.small` is recorded but not provisioned on Floci. Say so in your report.

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

You want `ACTIVE`; `Subnets` containing exactly the **two private** subnets; `Role` ending in `usms-eks-node-role`; and min 2, max 4, desired 2. Nodes in a public subnet are a design mistake AWS will not stop you making.

**Checkpoint 3**

```text
usms-eks-cluster        ACTIVE, k8s 1.30, vpc usms-vpc, 4 subnets, sg usms-eks-cluster-sg
  tags: Project=USMS Tier=app Lab=07 Name=usms-eks-cluster _lb_ports_=8081,8082
  └── usms-eks-nodes    ACTIVE, private-a + private-b, min 2 / max 4 / desired 2
                        nodeRole usms-eks-node-role, labels workload=usms tier=app
```

---

### Step 11 - Point `kubectl` at the cluster

From here to Step 21 the tool changes from the AWS CLI to `kubectl`. `aws eks update-kubeconfig` writes a cluster, a user and a context into `~/.kube/config` and makes it current. The user entry runs `aws eks get-token` on each call, so access follows your IAM identity and the file holds no long-lived secret. The file is outside the repository, so no `.gitignore` rule is needed.

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

`kubectl cluster-info` is the `whoami.sh` of Kubernetes. `kubectl get nodes -o wide` proves the API server is reachable, your credential works and the Step 10 nodes registered.

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

**If `kubectl` fails with an exec-plugin error** (naming `aws eks get-token` or `credential plugin`), use the cluster's own certificate-based kubeconfig:

```bash
k3d kubeconfig get "$(k3d cluster list --no-headers | awk '{print $1}' | head -1)" > outputs/lab-07-kubeconfig.yaml
chmod 600 outputs/lab-07-kubeconfig.yaml
export KUBECONFIG="$PWD/outputs/lab-07-kubeconfig.yaml"
kubectl cluster-info
```

A kubeconfig with embedded certificates **is** a credential: it goes straight into `outputs/` with `chmod 600`, like Lab 1's access key. Prove it is ignored:

```bash
git check-ignore -v outputs/lab-07-kubeconfig.yaml
```

**If `kubectl get nodes` shows only a control-plane node**, continue. Pods will stay `Pending` at Step 13, and Troubleshooting entry 4 has the remedy.

**Verify**

```bash
kubectl get nodes --no-headers | wc -l
kubectl auth can-i create deployments --all-namespaces
kubectl api-resources --namespaced=true -o name | head -12
```

You want at least one node, `yes` from `auth can-i`, and resource names including `configmaps`, `deployments.apps`, `pods` and `services`.

---

### Step 12 - Create the namespace, and make it the default for your context

Every object from here on lives in namespace `usms`; making it the context default stops a forgotten `-n usms` from landing objects elsewhere. A namespace is a name scope and a policy attachment point, **not** an isolation boundary: pods in different namespaces can reach each other unless a NetworkPolicy says otherwise.

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
    lab: "07"
EOF

kubectl apply -f manifests/lab-07/00-namespace.yaml
```

**Command - part 2, make it the default**

```bash
kubectl config set-context --current --namespace=usms
kubectl config view --minify --output 'jsonpath={..namespace}'; echo
```

Every manifest has `apiVersion`, `kind`, `metadata` and `spec`. You write `spec`; a controller acts on it and fills in `status`. Label values beginning with a digit (`"07"`) are quoted so YAML never reads them as numbers.

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

The namespace is `Active` with three labels, and the second command prints `No resources found in usms namespace.` Note that `kubectl get all` does not list ConfigMaps, Secrets or Ingresses.

---

### Step 13 - Deploy the first microservice: `usms-enrolment`

This is the largest manifest in the lab; every later one is a variation on it. Two ideas matter most (background: [requests and limits](../unit3/topic2.md#requests-and-limits), [probes](../unit3/topic2.md#probes)):

- **`resources.requests`**: Lab 08's HorizontalPodAutoscaler computes CPU utilisation as a percentage of the request. With no request it reports `<unknown>` and never scales.
- **Readiness versus liveness**: readiness controls membership of the Service (fail it and you stop receiving traffic); liveness controls restarts (fail it and the container is killed). Wiring a load-sensitive check to liveness makes a service restart under load.

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

Three objects in one file, separated by `---`. Fields worth knowing:

- `default.conf.template`: the `nginx` image runs files in `/etc/nginx/templates/` through `envsubst` at start, so `${POD_NAME}` becomes the real pod name. The **quoted heredoc** keeps the shell from expanding it first.
- `fieldRef` (the downward API) injects the pod's own name and node.
- `envFrom.configMapRef` turns every key in `usms-app-config` into an environment variable.
- `selector.matchLabels` must match `template.metadata.labels` (`kubectl apply` rejects a mismatch). A mismatched *Service* selector is silent and leaves no endpoints (Troubleshooting entry 5).
- `maxUnavailable: 0`, `maxSurge: 1`: never drop below the current count during a roll; the count-based equivalent of Lab 04's `minimumHealthyPercent 100`.
- `targetPort: http` names the container port, so it survives a port-number change.

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

You want `successfully rolled out` (if it times out, go to `kubectl describe pod` and Troubleshooting entry 4; do not re-apply), `READY 2/2`, two pods `Running`, a `CLUSTER-IP` with no `EXTERNAL-IP`, and **two** endpoint addresses. `kubectl get endpoints` is the Service's answer to "which pods am I sending traffic to now?".

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

The second service gives the gateway somewhere else to route, and checks that you can read a manifest rather than copy one.

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

Three deliberate differences from Step 13:

- No `livenessProbe`: there is nothing to wedge on, and probes are not free.
- No explicit `strategy`, so the default 25% / 25% applies; with two replicas one pod may be unavailable during an update. Section 14 asks about this.
- `APP_CAMPUS` in the response, so in Step 16 you can see which backend answered.

**Verify**

```bash
kubectl get deploy -n usms -o custom-columns=\
'NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas,STRATEGY:.spec.strategy.type,MAXUNAVAIL:.spec.strategy.rollingUpdate.maxUnavailable'

kubectl get endpoints -n usms
```

You want both Deployments `2/2`, `usms-enrolment` with `MAXUNAVAIL` `0` and `usms-results` with `25%`, and two endpoints per Service. `-o custom-columns` is new: a table of exactly the fields you choose.

---

### Step 15 - Deploy the gateway, and meet cluster DNS

The gateway's configuration contains two hostnames and no addresses. Every Service gets a DNS record `<service>.<namespace>.svc.cluster.local` that resolves to its ClusterIP, a virtual address that kube-proxy rewrites to a current endpoint on every node. The ClusterIP never moves, so the gateway can hold a name and forget about it. Use the fully qualified form in config files. Background: [Services, CoreDNS and kube-proxy](../unit3/topic1.md#services-coredns-and-kube-proxy).

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

- `$host` and `$proxy_add_x_forwarded_for` are nginx variables. `envsubst` only substitutes names set in the environment, so they survive.
- The trailing slash on `proxy_pass` strips the matched prefix:

```text
location /enrolment/ { proxy_pass http://backend/;  }   request /enrolment/x  -> upstream /x
location /enrolment/ { proxy_pass http://backend;   }   request /enrolment/x  -> upstream /enrolment/x
```

- **Order matters.** nginx resolves `proxy_pass` hostnames once at startup; if the backends' Services do not exist yet, the gateway crash-loops with `host not found in upstream` (Troubleshooting entry 3).

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

You want five pods `Running` (two enrolment, two results, one gateway) and no `emerg` lines in the gateway log. `Configuration complete; ready for start up` means the template was processed.

---

### Step 16 - Prove service discovery from inside the cluster

Step 15 asserted that the gateway reaches the backends by name. This step exercises the property instead of observing a proxy for it.

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

Part 1 returns a ClusterIP (typically `10.43.x.x` on k3s), not a pod address. Part 3 sends twelve requests through the gateway and tallies which pod answered.

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

You want **two distinct pod names**. If you see one: check `kubectl get endpoints` (only one pod ready), or raise the loop to 40. nginx holds one ClusterIP; kube-proxy spreads the load beneath it, which is why Lab 08 can scale `usms-enrolment` without touching the gateway.

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

A Secret is stored as **base64**, which is an encoding, not encryption. It keeps the value out of the image, can be RBAC-restricted separately, and is hidden from `kubectl describe`, but gives no confidentiality at rest unless etcd encryption is configured. On EKS, prefer KMS [envelope encryption](../unit8/topic3.md#envelope-encryption) of Secrets and IRSA instead of stored AWS credentials (Step 21). Background: [Kubernetes Secrets](../unit3/topic1.md#secrets).

**Command - part 1, create the Secret from literals, not from a file**

```bash
kubectl create secret generic usms-enrolment-secret \
  --namespace usms \
  --from-literal=ENROLMENT_API_TOKEN='floci-dummy-token-not-a-real-secret' \
  --from-literal=ENROLMENT_DB_PASSWORD='floci-dummy-password' \
  --dry-run=client -o yaml > manifests/lab-07/50-secret.yaml

kubectl apply -f manifests/lab-07/50-secret.yaml
```

`--dry-run=client -o yaml` makes `kubectl create` generate a manifest instead of creating the object.

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

No key and no permission beyond `get secret` were needed.

!!! note "macOS and Linux differ here"
    GNU `base64` uses `-d`; older BSD `base64` on macOS needs `-D`. If `-d` fails, use `-D`.

**Command - part 3, consume it in the enrolment Deployment**

```bash
kubectl set env deployment/usms-enrolment \
  --from=secret/usms-enrolment-secret \
  --namespace usms

kubectl rollout status deployment/usms-enrolment --timeout=120s

kubectl get deploy usms-enrolment -o jsonpath='{.spec.template.spec.containers[0].envFrom}'; echo
```

`kubectl set env --from=secret/...` adds an `envFrom.secretRef` to the pod template, which is a spec change, so a new ReplicaSet rolls out. Updating a ConfigMap or Secret does **not** restart pods; changing the pod template does.

**Verify**

```bash
kubectl describe deployment usms-enrolment | sed -n '/Environment Variables from/,/Mounts/p'
kubectl exec deploy/usms-enrolment -- printenv | grep -E '^(APP_|ENROLMENT_)' | sort
```

You want `usms-app-config` and `usms-enrolment-secret` listed as sources, and four `APP_*` plus two `ENROLMENT_*` keys. Inside the container the token is plain text: a Secret protects the value on the way to the pod, not inside it.

---

### Step 18 - Roll out a change, then roll it back

A Deployment rolls by creating a **new ReplicaSet** and scaling the old one to zero, keeping it up to `revisionHistoryLimit` (5, from Step 13). Rollback scales an old ReplicaSet back up; nothing is rebuilt.

```text
before:  ReplicaSet-A (rev 1)  replicas=2   <- serving
apply :  ReplicaSet-B (rev 2)  replicas=0 -> 1 -> 2
         ReplicaSet-A (rev 1)  replicas=2 -> 1 -> 0
after :  ReplicaSet-B (rev 2)  replicas=2   <- serving
         ReplicaSet-A (rev 1)  replicas=0   <- kept, and this is your rollback
```

**Command - part 1, make a change worth deploying**

```bash
sed -i.bak 's/APP_VERSION: "1.0.0"/APP_VERSION: "1.1.0"/' manifests/lab-07/10-configmap-app.yaml
grep APP_VERSION manifests/lab-07/10-configmap-app.yaml

kubectl apply -f manifests/lab-07/10-configmap-app.yaml
```

!!! note "macOS and Linux differ here too"
    `sed -i.bak` works on both GNU and BSD `sed`; plain `-i` does not. Remove the `.bak` files with `rm manifests/lab-07/*.bak` when done.

**Command - part 2, observe that nothing happened**

```bash
kubectl run usms-debug --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- http://usms-enrolment.usms.svc.cluster.local/
```

The response still says `"version":"1.0.0"`: the ConfigMap changed, the running pods did not.

**Command - part 3, trigger the rollout deliberately**

```bash
kubectl annotate deployment/usms-enrolment \
  usms.rtc.bt/config-revision="$(date -u +%Y%m%d%H%M%S)" \
  --overwrite

kubectl rollout status deployment/usms-enrolment --timeout=120s
```

That annotates the Deployment's own metadata, not the pod template, so it may not roll. If `rollout status` returns immediately, use the supported instrument, which writes a timestamp into the pod template:

```bash
kubectl rollout restart deployment/usms-enrolment
kubectl rollout status deployment/usms-enrolment --timeout=120s
```

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

The response may still say `1.1.0`. `rollout undo` reverts the **pod template**, not the ConfigMap, which is still at `1.1.0`. If a release changes a ConfigMap, a Secret and an image, rolling back the Deployment recovers only the image; that is why teams version configuration with the workload.

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

This step produces the three most common failures on purpose, so you have seen the output before meeting it under pressure.

```text
kubectl get pods              is it running? what phase, how many restarts?
kubectl describe pod <name>   WHY is it in that phase? read the Events at the bottom
kubectl logs <name>           what did the application itself say?
```

`logs` is the third question: for the two commonest failures the container never started, so the answer is in the `Events` at the bottom of `describe`.

**Failure 1 - an image that does not exist**

```bash
kubectl set image deployment/usms-results results=nginx:this-tag-does-not-exist
sleep 20
kubectl get pods -n usms -l app=usms-results
kubectl describe pod -l app=usms-results | tail -15
```

**Expected result**

**Expected result**

```text
NAME                            READY   STATUS             RESTARTS   AGE
usms-results-6b7c8d9f4-2mnpq    0/1     ImagePullBackOff   0          22s
usms-results-84cd7f6b59-h4xkz   1/1     Running            0          14m
usms-results-84cd7f6b59-r9wln   1/1     Running            0          14m
```

> Example output. Note that **the old pods are still serving** - `maxUnavailable` protected you, and
> a broken image never reached production. That is the deployment strategy earning its keep.

`Events` shows `Failed to pull image` and `ErrImagePull`, then `ImagePullBackOff` (retrying with growing delays, indefinitely). Fix it:

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

`Pending` with `FailedScheduling` means no node can accommodate the pod: insufficient CPU or memory, an untolerated taint, an unmatched `nodeSelector`, or an unbound volume. Clean it up (a CLEAN UP item in Section 15):

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

**Expected result**

```text
NAME           READY   STATUS             RESTARTS      AGE
usms-crasher   0/1     CrashLoopBackOff   2 (10s ago)   26s

usms-crasher starting
fatal: no database configured
```

Here `logs` is the right second command, because the container did start. `--previous` shows the last crashed container's output:

```bash
kubectl logs usms-crasher --previous
```

Clean up:

```bash
kubectl delete pod usms-crasher
```

**Events are namespaced and time-ordered**

```bash
kubectl get events -n usms --sort-by=.lastTimestamp | tail -20
```

This shows scheduling, pulls, probe failures and scaling in one place. Events expire after about an hour, so they are a live-debugging tool, not an audit log.

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

Both platforms are running; check claims instead of remembering them.

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

Fill it in; Section 13 grades it. For the last row, the honest answer is not "nothing": manifests are portable, but IAM roles, the VPC, node groups and load balancer annotations are not.

---

### Step 21 - IRSA: the right way to give a pod AWS permissions, and why it stops here

Step 7 put `USMSStudentDataReadWrite` on the node role. IRSA is the fine-grained alternative; whether it completes depends on your build, and either outcome is worth recording. Background: [IRSA versus EKS Pod Identity](../unit8/topic1.md#irsa-versus-eks-pod-identity).

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

Nothing is stored and nothing is shared between pods; a pod with a different ServiceAccount gets nothing.

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
    Floci's cluster runs on your machine; its OIDC document, if any, is unreachable from STS, and on most builds `cluster.identity.oidc.issuer` is absent.

    On real AWS the two commands above register the provider once per cluster; each workload role is then an ordinary role with a web-identity trust policy.

    The node role gives credentials to every pod on the node, including a compromised one. Record which of the six steps your build could complete.

**Verify**

```bash
kubectl get sa usms-enrolment-sa -n usms -o yaml | grep -A3 'metadata:'
aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text 2>/dev/null \
  || echo "list-open-id-connect-providers unsupported on this build"
```

You want `usms-enrolment-sa` in namespace `usms`, and either a provider ARN or an honest message. Do not fabricate the ARN in your report.

---

### Step 22 - Prove that all of this survives a restart

Create, perturb, read back. The perturbation is a full Floci stop and start; the read-back **re-derives every identifier from the API**, because a shell variable proves only that your shell remembers something.

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

`list-clusters` asks for the whole list and filters with ``[?@==`usms-eks-cluster`]`` (`@` is the current element; backticks make a literal). `describe-cluster --name` takes the name from you and would not notice if something else answered.

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

**If the cluster is `MISSING`**, run `./scripts/utilities/floci-storage-check.sh` first; `memory` storage mode is almost always the cause.

**If the AWS side persisted but `kubectl` fails to connect**, the node containers may still be starting or the endpoint port changed:

{% raw %}```bash
docker ps --filter "name=k3d" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
kubectl cluster-info
```{% endraw %}

If the containers are up but `kubectl` still fails, re-run Step 11's `update-kubeconfig` and note that the kubeconfig did not survive.

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

Lab 08 needs these identifiers after your terminal is gone.

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

- **Unquoted heredoc**: every `$(...)` runs now, so the file holds values, not commands.
- AWS values are looked up from the API, so a deleted resource shows as `None` and the check catches it. Kubernetes names are literal because you chose them.
- `USMS_K8S_CPU_REQUEST` lets you check Lab 08's HPA arithmetic.

**Expected result**

```text
all values populated
```

On **Path B**, `USMS_EKS_CLUSTER_ARN`, `USMS_EKS_CLUSTER_STATUS`, `USMS_EKS_VERSION`, `USMS_EKS_ENDPOINT` and `USMS_EKS_LB_PORTS` will be empty or `None`; that is expected (only Lab 08 Step 10 needs them). Note it in `notes/lab-07-notes.md`. On **Path A**, any empty value is a real gap: fix it now.

**Verify**

```bash
source configs/lab-07.env
echo "cluster=$USMS_EKS_CLUSTER  ns=$USMS_EKS_NAMESPACE  lb_ports=$USMS_EKS_LB_PORTS"
grep -c '^export' configs/lab-07.env
```

You want the three values echoed, `lb_ports` reading `8081,8082`, and **21** exports.

---

### Step 24 - Commit your work

Check, rather than trust, that no secret is about to be committed.

**Command - part 1, look before you add**

```bash
git status --short
```

Before typing anything else, confirm:

- No path under `outputs/` appears (this lab wrote several there, possibly a kubeconfig with certificates).
- No `.env` at the repository root appears.
- `configs/lab-07.env` **does** appear; it holds IDs and names only.
- `manifests/lab-07/50-secret.yaml` appears only if you left it there after Step 17. Decide deliberately: dummies here, but in any other repository, move it.

If anything under `outputs/` is listed, stop and diagnose:

```bash
git check-ignore -v outputs/lab-07-support-probe.txt
```

**Expected result**

```text
.gitignore:7:outputs/*	outputs/lab-07-support-probe.txt
```

> Example output - the line number will differ.

If it prints nothing, the file is not ignored; the rule is probably `outputs/` instead of `outputs/*`. Fix the rule:

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

You want your commit on top, the manifests, policies and `configs/lab-07.env` in the file list, and **`0`** from the last command.

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

### 7.4 Path C - what to do if neither EKS nor k3d is available

If Step 2 gave you Path C, do not invent cluster output. Instead, and say in your report that you did:

1. **Write every manifest** from Steps 12 to 17.
2. **Validate them without a cluster:** `kubectl apply --dry-run=client -f manifests/lab-07/` catches mis-indentation, wrong `apiVersion` and selector mismatches.
3. **Do Steps 4 to 7 and Step 23 in full.** They are IAM and EC2 calls, and they work.
4. **Answer all of Section 14**, and Section 12's Exercises 1, 2 and 3 on paper, labelling output as expected rather than observed.
5. **Install `k3d` before the next session** if you can. Lab 08 is much harder on paper.

That is a legitimate submission. An invented `kubectl get pods` output is not.

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-07.sh`

It checks configuration as well as existence, because an existence-only check passes right up until the restart that deletes everything.

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

Failures in the **Environment** block are the real problem; failures below are usually a consequence. On support **Path B**, expect exactly three failures, all in the EKS block (cluster, `_lb_ports_` tag, node group): `PASS=27  FAIL=3` is correct there, and your notes should say so.

A quick end-to-end check you can run any time:

```bash
kubectl run usms-smoke --rm -it --restart=Never --image=busybox:1.36 -- sh -c '
  G=http://usms-gateway.usms.svc.cluster.local
  wget -qO- $G/ && wget -qO- $G/enrolment/ && wget -qO- $G/results/
' && echo "SMOKE TEST PASSED"
```

You want three JSON documents and `SMOKE TEST PASSED`. If the gateway answers but a backend does not, start with `kubectl get endpoints -n usms`.

### 8.2 Build the cleanup script - DO NOT RUN IT NOW

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

The deletion order is the lesson: **namespace, node group, cluster, detach, roles, policies, security group.** Both AWS and Kubernetes refuse to delete anything with dependents.

---

## 9. Checkpoints

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

## 10. Troubleshooting

??? danger "`kubectl` hangs, or reports `connection refused` to `localhost:6443`"
    The API server is not reachable. Work outwards from the container:

    {% raw %}```bash
    docker ps --filter "name=k3d" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    kubectl config current-context
    kubectl cluster-info
    ```{% endraw %}

    No containers listed: start Floci with `./scripts/setup/floci-up.sh` and wait 30 seconds. Containers listed but a different published port: re-run Step 11's `update-kubeconfig`.

    If `current-context` names a cluster you do not recognise, `kubectl config get-contexts` lists them and `kubectl config use-context` switches.

??? danger "`error: You must be logged in to the server (Unauthorized)`"
    If the message mentions `exec` or a credential plugin, `aws eks get-token` is unsupported on your build; use Step 11's certificate-based kubeconfig fallback.

    Otherwise your identity is not mapped into the cluster's authorisation. On real EKS only the creator is mapped automatically; others need EKS access entries (formerly the `aws-auth` ConfigMap). This does not arise locally.

??? danger "`usms-gateway` is in `CrashLoopBackOff` with `host not found in upstream`"
    nginx resolves `proxy_pass` hostnames once, at startup. If a backend Service did not exist then, nginx exits and the pod restarts forever.

    ```bash
    kubectl logs deploy/usms-gateway --previous | tail -5
    kubectl get svc -n usms
    ```

    Make the Services exist, then restart the gateway:

    ```bash
    kubectl apply -f manifests/lab-07/20-enrolment.yaml
    kubectl apply -f manifests/lab-07/30-results.yaml
    kubectl rollout restart deployment/usms-gateway
    ```

    In production, a `resolver` directive with a TTL makes nginx re-resolve periodically.

??? danger "Pods stay `Pending` forever and `describe` says `node(s) had untolerated taint`"
    You have a control-plane node and no workers, and control-plane nodes repel ordinary pods (the split from Step 3).

    ```bash
    kubectl get nodes
    kubectl describe pod <pod> | tail -6
    kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints[*].key'
    ```

    The correct fix is Step 10. If Step 10 is unavailable on your build, the local-only workaround removes the taint:

    ```bash
    kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null
    kubectl taint nodes --all node-role.kubernetes.io/master:NoSchedule- 2>/dev/null
    ```

    The trailing `-` removes the taint. Never do this on a real cluster: the taint stops workloads starving the API server. Record in your notes that you did it.

??? danger "A Service exists, pods are `Running`, but `kubectl get endpoints` shows none"
    The Service's `selector` does not match the pods' labels, or the pods are not **ready**.

    ```bash
    kubectl get svc usms-enrolment -o jsonpath='{.spec.selector}'; echo
    kubectl get pods -n usms --show-labels
    kubectl get pods -n usms -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status'
    ```

    Compare the label sets character by character. If they agree and readiness is `False`, `kubectl describe pod` shows `Readiness probe failed:` with the HTTP status.

??? danger "`ImagePullBackOff` on a public image, and you are behind a proxy or offline"
    The nodes cannot reach the registry. Pre-load the images from your host:

    ```bash
    docker pull nginx:1.27-alpine
    docker pull busybox:1.36
    CL=$(k3d cluster list --no-headers | awk '{print $1}' | head -1)
    k3d image import nginx:1.27-alpine busybox:1.36 -c "$CL"
    kubectl rollout restart deployment -n usms
    ```

    `k3d image import` copies an image from your local Docker daemon into the cluster's nodes, bypassing any registry.

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
    `spec.selector` cannot change after creation. Delete and recreate the Deployment:

    ```bash
    kubectl delete deployment usms-enrolment
    kubectl apply -f manifests/lab-07/20-enrolment.yaml
    ```

    Choose your label scheme once and leave it alone; this lab fixed `app`, `project` and `tier` in Step 13.

??? danger "Everything worked yesterday and today the cluster is empty"
    Run the storage check first:

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    `FLOCI_STORAGE_MODE=memory` discards all state on restart; Step 22 is the test that catches it. If the mode is correct, check whether anyone ran `docker compose down -v` or `docker volume prune`, both forbidden in this course.

---

## 11. Floci vs Real AWS

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

**Where Floci is nicer than reality (traps on real AWS):** the cluster is ready in two minutes (budget fifteen for the control plane and five more for nodes, so `aws eks wait` is essential in pipelines); no cost (an idle cluster left running over a holiday is the classic student invoice); no IAM enforcement (a missing permission fails cluster creation with an error naming the API call, not the permission); no quotas, throttling or eventual consistency; and effectively unlimited node capacity (Step 19's `FailedScheduling` had to be forced).

In your report, say which claims you observed (the Kubernetes object model, DNS discovery, rollouts, failures, persistence), which were only recorded (IAM policies, node group sizing, security groups), and which are conceptual (IRSA, KMS encryption of Secrets, access entries, control plane logging). "I configured IRSA" is not true; "I wrote the ServiceAccount, traced the trust chain and recorded that my build publishes no OIDC issuer" is.

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-07-eks/exercises.md`; screenshots go in `screenshots/`.

### Exercise 1 - Basic: a fourth microservice

**Requirements:** deploy `usms-timetable`: one replica, `nginx:1.27-alpine`, its own ConfigMap serving JSON identifying itself and its pod, a readiness probe on `/healthz`, and a ClusterIP Service on port 80.

**Constraints**

- One file, `manifests/lab-07/70-timetable.yaml`, containing all three objects.
- Labels follow this lab's scheme exactly: `app`, `project`, `tier`.
- CPU and memory requests declared.
- Write the manifest; do not use `kubectl create deployment` and edit it.

**Expected outcome:** four Deployments and four Services in `kubectl get deploy,svc -n usms`; a `busybox` pod fetching `http://usms-timetable.usms.svc.cluster.local/` gets JSON naming the service and its pod.

**Hints:** copy the structure of `30-results.yaml` (smaller, no liveness probe). `kubectl apply --dry-run=client -f <file>` validates first.

### Exercise 2 - Intermediate: route to it, and prove the route

**Requirements:** add a `/timetable/` route to `usms-gateway` that reaches `usms-timetable`, and prove the change reached the running gateway pod.

**Constraints**

- Edit `manifests/lab-07/40-gateway.yaml` and re-apply it. No `kubectl edit`.
- The gateway ends on a **new** ReplicaSet, and you can show which command caused that.
- `/enrolment/` and `/results/` still work. Show all three in one command.

**Expected outcome:** three JSON responses through the gateway from three services, and one more revision in `kubectl rollout history deployment/usms-gateway`.

**Hints:** Step 18 showed that changing a ConfigMap does not restart pods, and named two commands that do. Only one fits when the pod template has not changed.

### Exercise 3 - Problem solving: find the misconfiguration

**Requirements:** apply the manifest below exactly as given. `kubectl apply` accepts it and the Service returns nothing. Diagnose it, state the cause in one sentence, and fix it minimally.

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

- Find it with commands, not by reading the YAML. Show the commands in order.
- Your fix must change exactly one line.
- There are **two** independent problems. Find both; fixing one will not make it work.

**Expected outcome:** a short diagnosis naming both faults, the output that revealed each, and a working Service with two endpoints. Delete `usms-broken` afterwards (a CLEAN UP item).

**Hints:** start with the debugging command Step 13's verify called the most useful. For the second fault, ask what the base `nginx` image serves at the probe's path, and what a failing readiness probe does to Service membership.

### Exercise 4 - Challenge: survive a node going away

**Requirements:** one node disappears. Design and demonstrate a configuration in which `usms-enrolment` keeps serving, and justify each choice in prose. The brief:

> USMS enrolment must not have all its capacity on one node, must never drop below one healthy pod
> during a voluntary disruption such as a node drain, and must be able to say - from the cluster
> itself, not from your memory - which node each of its pods is on.

**Constraints**

- No new Deployment. Change `usms-enrolment`.
- Demonstrate it: `kubectl drain` on one node with Section 8.1's smoke test running in a loop, or delete all pods on one node at once.
- With only one schedulable node, say so, explain what you would have demonstrated, and demonstrate what the cluster allows.

**Expected outcome:** an updated `20-enrolment.yaml`, at least one new object, pods on more than one node where possible, and half a page of justification. Marks are for the reasoning.

**Hints:** `topologySpreadConstraints`, `podAntiAffinity` and `PodDisruptionBudget`; you need at least two. One is advisory and one is enforced. `kubectl get pods -o wide` answers the third requirement.

### Exercise 5 - Integration: prepare what Lab 08 needs, using what Lab 01 built

**Requirements**

- **Part 1:** record current CPU use of the `usms-enrolment` pods, absolute and as a percentage of the `50m` request, in `outputs/lab-07-cpu-baseline.txt`.
- **Part 2:** without opening Lab 1's document, report the ARN of `USMSStudentDataReadWrite`, every role carrying it, the bucket ARN in its `Resource` field, and whether that bucket exists, in `outputs/lab-07-lab06-readiness.txt`.
- **Part 3:** append to `notes/lab-07-notes.md` which of `configs/lab-07.env`'s 21 variables Lab 08 needs, one line each with the reason.

**Constraints**

- Part 1 states honestly whether `kubectl top` works. If the metrics API is absent, say so and do not invent numbers; Lab 08 Step 7 deals with this.
- Part 2 reads the bucket name **out of the policy document**, not from memory.
- Part 3 is your own reading of Section 16, not a copy.

**Expected outcome:** two git-ignored files in `outputs/` (check with `git check-ignore -v`) and a new notes section. Lab 08's Step 2 reads all three.

**Hints:** `kubectl get --raw /apis/metrics.k8s.io/v1beta1` tells you whether the metrics API exists. Chain `aws iam get-policy` (default version ID) into `aws iam get-policy-version`. The bucket ARN and the object ARN are different entries; Lab 10 depends on the difference.

---

## 13. Lab Assessment Checklist

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

- [ ] Section 14 answered in prose in `notes/lab-07-notes.md`
- [ ] Step 20's comparison table filled in with both platforms running
- [ ] Five exercises attempted; Exercise 5's two `outputs/` files present

---

## 14. Review Questions

Answer in prose in `notes/lab-07-notes.md`.

1. An EKS cluster reports `ACTIVE`, but every pod sits in `Pending`. Using the control plane / data plane split from Step 3, explain how both are true, and name two configurations that produce this symptom.
2. What would break if you swapped the trust policies of the cluster role and the node role, and at which point in Steps 6 to 11 would you notice **on real AWS rather than Floci**?
3. Take one commonly conflated pair: a Service versus a Deployment, or a readiness probe versus a liveness probe. Explain the distinction and describe a concrete failure caused by getting it backwards.
4. After Step 18's rollback, the pod still reported `1.1.0`. Explain why, argue for or against "Kubernetes rollback is not really a rollback", and name the practice that resolves the problem.
5. Compare `maxUnavailable: 0` (`usms-enrolment`) with the default (`usms-results`) during an update of two replicas. Give a workload suited to each, and say which is closer to Lab 04's ECS deployment configuration.
6. A colleague says a Kubernetes Secret is "encrypted, so it's fine to commit the manifest". Correct them: what a Secret provides, what it does not, and what you would do on real EKS. Reference Step 17.
7. For USMS (small team, one region, quiet for eight months and very busy for two), argue for ECS or Kubernetes. Name at least two things this lab made harder than Lab 04 and one thing Kubernetes gave you that ECS could not.

---

## 15. KEEP vs CLEAN UP

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

You want five pods: two enrolment, two results, one gateway (six if you did Exercise 1).

Do **not** run `scripts/cleanup/lab-07-cleanup.sh`, `lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are for the end of the course, in the order given in each lab's Verification section.

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

## 16. Preparation for the Next Lab

Lab 08 (`lab-08-eks-scaling.md`) answers the two questions this lab left open: how the services grow, and how anyone outside the cluster reaches them. It creates no new microservice and renames nothing.

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

Lab 06 handed `desiredCount` to Application Auto Scaling, an AWS service outside the workload; Lab 08 hands `replicas` to a HorizontalPodAutoscaler, a controller inside the cluster reading a metrics API inside the cluster. Same architecture, different blast radius.

Before the next session:

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

You want: `FAIL=0` from the first (or `FAIL=1` if you skipped Lab 05 Exercise 2); `FAIL=0` from the second on Path A or `FAIL=3` on Path B; **21**; three Deployments reading `2`, `2` and `1`; `50m`; and `8081,8082`. An empty CPU request means Lab 08's HPA reports `<unknown>` and never scales; a missing `_lb_ports_` tag means Lab 08 Step 15 has no host port and the cluster must be recreated. Fix both today.

Take a snapshot so a Lab 08 mistake is recoverable:

```bash
floci snapshot save lab-07-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-07.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
```

---

## Appendix - New CLI and JMESPath patterns

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
| `-o jsonpath='{.status.readyReplicas}'` | One field, unquoted, ideal for `test` in a script | Section 8 |
| `-o custom-columns='NAME:.metadata.name,READY:...'` | Build exactly the table you want. JMESPath's job, `kubectl`'s syntax | Steps 14, 18, 22 |
| `--dry-run=client -o yaml` | Generate the manifest an imperative command *would* have created | Steps 17, 21 |
| `-l app=usms-enrolment` | Label selector. The universal filter across every `kubectl get` | Steps 13, 19 |
| `--show-labels` | Print the labels a selector would have to match | Step 12, Troubleshooting |
| Numeric filename prefixes `00-`, `10-`, `20-` | Directory applies in lexical order; this is how you order dependencies | Section 6 |
| `---` between objects in one file | Several objects, one file, one microservice | Steps 13, 14, 15 |

**Shell**

| Pattern | Meaning | Used in |
| --- | --- | --- |
| `<< 'EOF'` quoted heredoc | No expansion. **Policy documents and Kubernetes manifests** | Steps 4, 5, 12–17 |
| `<< EOF` unquoted heredoc | Expand now. **Request bodies and `configs/lab-NN.env`** | Steps 8, 10, 23 |
| `set -uo pipefail` without `-e` | A script that must *report* failures cannot abort on the first one | Step 2, Section 8 |
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

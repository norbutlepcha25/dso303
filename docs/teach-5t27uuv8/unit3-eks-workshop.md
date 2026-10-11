# Unit 3 Workshop: From Containers to Amazon EKS

**Duration:** 3 hours (180 minutes, including a 10-minute break)  
**Audience:** Students new to AWS with limited Kubernetes knowledge  
**Mode:** Workshop, guided demonstration, short explanations, hands-on CLI tasks, ClassLegend quizzes  
**Running scenario:** A college student portal that must be deployed, accessed and scaled reliably

<div class="lesson-schedule"></div>

## Before class

!!! teacher "Purpose"
    Introduce cloud computing, containers, orchestration, Kubernetes fundamentals and the role of Amazon EKS. Students use a supported local Kubernetes environment where available, with Floci for AWS API emulation where appropriate. This is an introductory lesson, not a full production EKS deployment lab.

**Learning outcomes.** By the end, students should be able to:

1. Explain why cloud computing and containers are useful.
2. Distinguish a container image from a running container.
3. Explain the basic purposes of EC2, ECS, Kubernetes and EKS.
4. Identify a cluster, control plane, node, Pod, Deployment and Service.
5. Explain the difference between the AWS CLI and `kubectl`.
6. Use basic `kubectl` commands to inspect a cluster and an application.
7. Deploy NGINX, expose it internally and reach it through port forwarding (given a working cluster).
8. Scale a Deployment and explain what the replica count means.
9. Identify what Floci can and cannot demonstrate compared with real AWS.

**Environment checklist**

- [ ] `kubectl` installed and working
- [ ] Correct Kubernetes context selected
- [ ] `kubectl get nodes` succeeds in the practical environment
- [ ] `nginx:stable` can be pulled in that environment
- [ ] Deployment and Service creation tested
- [ ] Port forwarding and the HTTP request tested
- [ ] Scaling tested
- [ ] Floci's documented support for the planned AWS/EKS workflow checked
- [ ] Fallback ready if the cluster is unavailable (demonstration, screenshots or a preconfigured local cluster)

**Materials checklist**

- [ ] One simple Kubernetes architecture diagram
- [ ] College portal scenario ready
- [ ] Quizzes A, B and C loaded into ClassLegend
- [ ] One-page command reference (end of this page)
- [ ] Expected outputs or screenshots for troubleshooting
- [ ] Individual or pair work decided

**Security and cleanup**

- [ ] Approved teaching environment only
- [ ] No administrator credentials or access keys distributed
- [ ] No production resources or real student records
- [ ] Practice Service and Deployment deleted after the lab

!!! warning "Floci is not a Kubernetes cluster"
    Do not assume that running Floci provides a Kubernetes cluster or a working EKS implementation. Verify before class and keep the fallback ready.

---

## Hook: the college portal problem { data-minutes="15" }

!!! prompt "The college portal"
    Our college launches a student portal for course registration. On the first morning, hundreds of students try to access it at once. The website becomes slow. Later, the computer running the application fails.

    **How could we deploy and operate the application more reliably?**

**Discuss in pairs (2 minutes):**

1. Where does a website actually run?
2. What is a server?
3. What might happen if the server stops?
4. How could we handle more users?
5. Would running two copies of the application solve every problem?

!!! teacher "Teaching notes"
    Do not correct every misconception immediately. Record student ideas and return to them as the lesson progresses. Then introduce the four problems the workshop explores:

    - packaging an application consistently;
    - running applications on computing infrastructure;
    - managing multiple application instances;
    - providing a stable way to access an application.

    **Transition:** "Today we start with the application itself, then work outward until we understand how Kubernetes and Amazon EKS help operate containerised applications."

## From code to cloud { data-minutes="20" }

[1.3 Containers versus virtual machines](../unit1/topic3.md#containers-versus-virtual-machines){ .notes-link target="_blank" }
[2.1 The problem containers solve](../unit2/topic1.md#the-problem-containers-solve){ .notes-link target="_blank" }
[2.1 Images, layers and tags](../unit2/topic1.md#images-layers-manifests-tags-and-digests){ .notes-link target="_blank" }

| Term | Meaning |
|---|---|
| **Application** | Software that performs a task, such as a student portal |
| **Server** | A computer or computing environment that provides a service |
| **Virtual machine** | A software-defined computer running on physical infrastructure |
| **Container image** | A packaged template containing an application and the files it needs |
| **Container** | A running instance created from an image |
| **Container runtime** | Software responsible for running containers |
| **Container orchestration** | Coordinating application containers across computing resources |

!!! prompt "Analogy: preparing a meal"
    - **Image:** the recipe and packaged ingredients
    - **Container:** the meal being prepared from that recipe
    - **Server:** the kitchen where the work happens
    - **Orchestrator:** the system coordinating many kitchens and workloads

!!! teacher "Keep the analogy honest"
    It is only a starting point: images are not literally recipes, and containers are operating-system-level isolation, not full virtual machines.

**Board activity: put the steps in order**

Application code · Container image · Running container · Computing environment

???+ answer "Suggested order"
    `Application code → container image → running container → computing environment`

    The computing environment must already exist for the container to run; the order shows the packaging and execution relationship, not a strict build timeline.

**Quick check:**

- Is a container image the same as a running container?
- Does using a container mean we no longer need servers or computing resources?
- Why might a container help an application behave consistently across environments?

!!! teacher "Transition"
    "We now know what we want to run. Next, where it runs and which cloud services help us manage it."

## AWS fundamentals: ECS versus EKS { data-minutes="20" }

[1.1 Region](../unit1/topic1.md#region){ .notes-link target="_blank" }
[1.1 Availability Zone](../unit1/topic1.md#availability-zone-az){ .notes-link target="_blank" }
[1.3 Amazon EC2](../unit1/topic3.md#amazon-ec2){ .notes-link target="_blank" }
[3.1 EKS or ECS?](../unit3/topic1.md#eks-or-ecs){ .notes-link target="_blank" }

| Concept | One-line meaning |
|---|---|
| **AWS** | A cloud platform providing compute, storage, networking, identity and managed services |
| **Region** | A geographic area containing AWS infrastructure |
| **Availability Zone** | An isolated location within a Region |
| **Amazon EC2** | Runs virtual computing instances |
| **Amazon ECS** | AWS's own container orchestration service |
| **Amazon EKS** | AWS's managed Kubernetes service |

| Option | What it means for you |
|---|---|
| Application on an EC2 instance | You manage more of the server and application setup yourself |
| Amazon ECS | AWS's container orchestration, without adopting Kubernetes |
| Amazon EKS | Kubernetes on AWS, with AWS managing the EKS control plane |

**Key point:** ECS and EKS both run containerised applications, using different orchestration systems. Kubernetes is open source; EKS is AWS's managed Kubernetes. EKS does **not** mean AWS manages everything: workload, access control, networking, security, monitoring and cost remain the customer's responsibility.

!!! teacher "Scope"
    Do not configure VPCs, IAM roles, subnets, load balancers or cluster provisioning in this workshop.

!!! prompt "Mini discussion"
    A small team wants to run one containerised website on AWS and has no Kubernetes experience. Should it automatically choose EKS?

???+ answer "Expected response"
    No. ECS may be simpler. EKS is worth it when Kubernetes features, skills, ecosystem or portability justify the extra operational complexity.

!!! teacher "Transition"
    "Let's check we can distinguish the basic cloud and container concepts before moving into Kubernetes."

## ClassLegend quiz 1 { data-minutes="10" }

!!! quiz "Run Quiz A in ClassLegend: AWS and container fundamentals"
    Five or six questions on: why containers are used, what EC2 provides, what EKS is, which AWS service orchestrates containers, when ECS is the better first choice, and whether containers remove the need for compute.

    Students answer individually first, then discuss selected answers.

!!! teacher "Reviewing the quiz"
    Review the questions with the highest error rate. Do not use the quiz only as a score competition: ask students to explain why an incorrect option is wrong.

## Kubernetes fundamentals { data-minutes="20" }

[3.1 Control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane){ .notes-link target="_blank" }
[3.1 Nodes, Pods and containers](../unit3/topic1.md#nodes-pods-and-containers){ .notes-link target="_blank" }
[3.2 The objects you write](../unit3/topic2.md#the-objects-you-write){ .notes-link target="_blank" }

| Part | Role |
|---|---|
| **Control plane** | Coordinates the cluster and works to maintain the desired state |
| **Node** | A computing machine where Pods can run |
| **Pod** | The smallest deployable unit, usually one application container |
| **Deployment** | Declares the desired number of replicas and manages rollouts of new versions |
| **Service** | Provides a stable way to reach selected Pods |

In Amazon EKS, AWS manages the control plane. The customer remains responsible for workload configuration and the compute, permissions and networking their architecture needs.

```text
User's browser
      |
      v
Application access point
      |
      v
Kubernetes Service
      |
      +-------------------+
      |                   |
      v                   v
    Pod 1               Pod 2
  (container)         (container)

Deployment:    declares the desired replicas
Control plane: coordinates cluster state
Node(s):       provide the compute where Pods run
```

!!! teacher "About the diagram"
    It is simplified. The Service routes to eligible Pods; a Pod can be replaced, and the Deployment keeps the desired replica count.

| Kubernetes concept | Restaurant analogy |
|---|---|
| Container image | A prepared recipe or package |
| Container | A running application instance |
| Pod | A unit in which one or more containers run |
| Deployment | A manager keeping the desired number of instances |
| Service | A stable front desk for reaching the application |
| Cluster | The overall operating environment |

**Ask the class:**

1. Which component maintains the desired number of replicas?
2. Which component gives clients a stable way to reach the Pods?
3. Is a Pod the same as a node?
4. If one Pod is replaced, should clients need to learn its new IP address?

???+ answer "Expected answers"
    1. Deployment.
    2. Service.
    3. No: a node provides compute; a Pod is scheduled onto a node.
    4. Normally no: clients use the Service or application access point.

!!! teacher "Transition"
    "Now that we know the vocabulary, let's use the command line to inspect and operate a real Kubernetes environment."

## Break { data-minutes="10" .break }

!!! prompt "Break: 10 minutes"
    Come back with your terminal open and ready.

## CLI orientation { data-minutes="15" }

[3.2 kubectl and eksctl](../unit3/topic2.md#deploying-applications-using-kubectl-and-eksctl){ .notes-link target="_blank" }

| Tool | Talks to |
|---|---|
| **AWS CLI** (`aws`) | Supported AWS APIs |
| **`kubectl`** | A Kubernetes API server |

They are not interchangeable. A successful AWS CLI command does not prove that a Kubernetes cluster is available.

**Guided demonstration.** Run each command and explain it:

```bash
aws --version
kubectl version --client
kubectl config current-context
kubectl get nodes
kubectl get namespaces
```

The first two check installed clients. The third shows the selected Kubernetes context. The last two need a reachable, authorised cluster.

!!! teacher "Checkpoints"
    - `kubectl` not installed: fix the client before continuing.
    - Context missing: configure a supported environment.
    - `kubectl get nodes` fails: do not carry on as if the cluster works.
    - Floci lacks the Kubernetes behaviour you need: switch to the pretested local cluster or the fallback.

!!! teacher "Fallback if no cluster is available"
    Students learn the syntax through a guided demonstration, inspect instructor-provided output, annotate a Deployment manifest and predict each command's result. Label this clearly as a simulation, not a successful hands-on deployment.

## Hands-on: first application { data-minutes="30" }

[3.2 kubectl and eksctl](../unit3/topic2.md#deploying-applications-using-kubectl-and-eksctl){ .notes-link target="_blank" }
[3.1 Services, CoreDNS and kube-proxy](../unit3/topic1.md#services-coredns-and-kube-proxy){ .notes-link target="_blank" }

**Step 1: Create a Deployment**

```bash
kubectl create deployment hello --image=nginx:stable
```

| Part | Meaning |
|---|---|
| `kubectl` | The Kubernetes command-line client |
| `create deployment` | Ask Kubernetes to create a Deployment |
| `hello` | The Deployment's name |
| `--image=nginx:stable` | The container image to run |

**Step 2: Inspect the result**

```bash
kubectl get deployments
kubectl get pods
```

Identify the Deployment and the Pod. The Pod may take a moment while Kubernetes schedules it and pulls the image. If it does not start:

```bash
kubectl describe pod <pod-name>
```

!!! teacher "Inspect before recreating"
    Do not let students delete and recreate resources before reading the status and events.

**Step 3: Create a Service**

```bash
kubectl expose deployment hello --port=80 --type=ClusterIP
kubectl get services
```

The Service selects the Deployment's Pods. `ClusterIP` is internal to the cluster; it does not create a public website.

**Step 4: Reach the website**

```bash
kubectl port-forward deployment/hello 8080:80
```

Keep it running. In a second terminal:

```bash
curl -I http://localhost:8080
```

Or open `http://localhost:8080` in a browser.

- Port forwarding creates a temporary path from your machine to the Kubernetes resource.
- A successful HTTP response proves the application is reachable through that path.
- It does **not** prove the application is publicly accessible on AWS.

!!! prompt "Explain the flow"
    I created a ________. Kubernetes ran a ________ containing the application container. I created a ________ to provide a stable in-cluster access point, then used ________ to test it from my computer.

???+ answer "Expected answers"
    Deployment; Pod; Service; port forwarding.

**Success criteria**

- [ ] Deployment exists
- [ ] Pod reaches `Running`
- [ ] Service exists
- [ ] Port forwarding starts
- [ ] HTTP request returns a response

## Hands-on: replicas and observation { data-minutes="20" }

[3.1 Subnets and Availability Zones](../unit3/topic1.md#subnets-and-availability-zones){ .notes-link target="_blank" }

!!! prompt "Predict first"
    The Deployment has one replica and we request three. How many Pods should Kubernetes try to maintain?

**Scale and observe**

```bash
kubectl scale deployment hello --replicas=3
kubectl get deployments
kubectl get pods
kubectl get services
```

Count the Pods. Explain the difference between the **desired** replica count and the number currently **ready**.

**Limits to make explicit**

- The Deployment declares a desired replica count; Kubernetes works to maintain it.
- Three replicas do not guarantee availability if they share a failing node or another single point of failure.
- Scaling by hand is not autoscaling.
- A `ClusterIP` Service gives internal access only; it is not a public load balancer.

**Extension (if students finish early)**

```bash
kubectl scale deployment hello --replicas=2
kubectl get pods
```

Why does Kubernetes terminate the extra replica?

!!! teacher "Keep it calm"
    Avoid introducing a deliberately broken image unless the class is comfortable and there is time to explain recovery.

## ECS versus EKS design game { data-minutes="15" }

[3.1 EKS or ECS?](../unit3/topic1.md#eks-or-ecs){ .notes-link target="_blank" }
[3.3 Decision framework](../unit3/topic3.md#decision-framework){ .notes-link target="_blank" }

Small teams, two minutes per scenario: choose a service and prepare a short explanation. No full architecture drawing is needed.

!!! prompt "Scenario A: simple college website"
    A small team wants to run a containerised college website on AWS. It has no Kubernetes experience and wants a simple operational model.

!!! prompt "Scenario B: Kubernetes skills and ecosystem"
    An organisation already uses Kubernetes and wants to run its applications on AWS using the Kubernetes API and ecosystem.

!!! prompt "Scenario C: learn Kubernetes without an AWS bill"
    A class wants to practise Pods, Deployments, Services and basic `kubectl` without creating a real EKS cluster.

???+ answer "Suggested answers"
    - **A:** Evaluate Amazon ECS first. EKS is not automatically the best choice.
    - **B:** Amazon EKS is a strong candidate.
    - **C:** A local Kubernetes cluster or another verified teaching environment. Floci may cover parts of the AWS-facing workflow, but its Kubernetes capabilities must be verified.

**Discussion**

- What does EKS manage?
- What remains the customer's responsibility?
- Why might ECS be simpler for some workloads?
- Why is a local Kubernetes lab useful even when the curriculum covers EKS?

!!! teacher "Goal"
    Students choose tools from requirements, rather than assuming the more complex service is always better.

## Exit ticket { data-minutes="5" }

!!! prompt "Answer individually"
    1. What is the difference between a container image and a container?
    2. What are the roles of a Pod, a Deployment and a Service?
    3. What is one difference between ECS and EKS?
    4. Which command did you use to inspect Pods?
    5. What is one thing you still need to understand better?

!!! quiz "Optional: ClassLegend exit quiz"
    Use Quiz B (Kubernetes fundamentals) or Quiz C (practical understanding) in ClassLegend instead of paper.

!!! teacher "Clean up"
    ```bash
    kubectl delete service hello
    kubectl delete deployment hello
    ```

---

## Command reference

| Command | Purpose |
|---|---|
| `kubectl version --client` | Check the installed Kubernetes CLI |
| `kubectl config current-context` | Show the selected Kubernetes context |
| `kubectl get nodes` | List nodes in the cluster |
| `kubectl get namespaces` | List namespaces |
| `kubectl create deployment hello --image=nginx:stable` | Create a Deployment |
| `kubectl get deployments` | List Deployments |
| `kubectl get pods` | List Pods in the current namespace |
| `kubectl describe pod <pod-name>` | Inspect a Pod and its events |
| `kubectl expose deployment hello --port=80 --type=ClusterIP` | Create an internal Service |
| `kubectl get services` | List Services |
| `kubectl port-forward deployment/hello 8080:80` | Forward local port 8080 to port 80 |
| `kubectl scale deployment hello --replicas=3` | Request three replicas |
| `kubectl delete service hello` | Delete the practice Service |
| `kubectl delete deployment hello` | Delete the practice Deployment |

Commands assume the `hello` resources are in the current namespace. Check the context and namespace first.

!!! teacher "Final teaching advice"
    Prioritise understanding over command volume. Students should leave knowing what a container is and why it helps; what AWS, EC2, ECS and EKS each provide; what Pods, Deployments and Services do; how to inspect a cluster and deploy a simple application; why a successful command is not the same as a verified working application; and why local emulation and real AWS are not identical. A successful first deployment and a clear mental model beat trying to teach all of production EKS in three hours.

# Amazon Elastic Container Service

## Definition

**Amazon Elastic Container Service (ECS)** is an AWS-native container orchestrator: a managed control plane that stores your declared desired state, schedules containers onto capacity, replaces them when they fail, and integrates them with AWS networking, identity, load balancing, and observability.

An **ECS cluster** is a logical grouping of services, tasks, and  on EC2 capacity  container instances. It is a namespace, a capacity boundary, and a permissions boundary. It is not a physical thing: the cluster has no endpoint, no version, no control-plane charge, and nothing to patch. Creating one is an API call that costs nothing and completes instantly.

A **capacity provider** names *where* tasks may run. `FARGATE` and `FARGATE_SPOT` are built-in; an Auto Scaling group capacity provider wraps an ASG of EC2 instances and can manage that ASG's size on your behalf.

**AWS Fargate** is serverless compute for containers: you declare CPU and memory, AWS provisions an isolated microVM, runs your task in it, and bills per second for the resources you declared.

**Service discovery** is the mechanism by which one component learns another's current address, given that task IP addresses are ephemeral. 

**Load balancing** is the mechanism by which requests are distributed across the healthy instances of a service.

<figure markdown="span">
    ![3layerglobalinfra](../img/U2/t2/ECSComponents.png){width="80%"}
    <figcaption>Components of ECS</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generaed (Google Gemini)</i></p>
</figure>

| Layer | The question it answers | ECS mechanism |
|---|---|---|
| **Cluster** | Which boundary does this workload belong to? | `CreateCluster`; cluster name on every task and service |
| **Capacity provider** | On what kind of capacity may this run? | `FARGATE`, `FARGATE_SPOT`, ASG capacity provider |
| **Capacity provider strategy** | In what proportion across those kinds? | `base` and `weight` per provider |
| **Task definition** | What is the workload? | Immutable revision, from 2.1 |
| **Service** | How many, and how are they kept alive and reachable? | `desiredCount`, deployment configuration, load balancer registration |
| **North-south** | How does external traffic reach a task? | ALB, NLB, or API Gateway, with target type `ip` or `instance` |
| **East-west** | How does one service reach another? | Service Connect, Cloud Map, internal load balancer, VPC Lattice |

!!! note "The cluster is free, and that fact has architectural consequences"

    Amazon EKS charges an hourly fee per cluster, which pushes organisations towards a small number of large, multi-tenant clusters with namespace isolation inside them. ECS charges nothing for clusters, so a cluster-per-team, cluster-per-environment, or cluster-per-application topology costs nothing extra. This asymmetry is not trivia: it means that on ECS, isolation between teams can be obtained by creating another cluster rather than by engineering it inside a shared one  which is a genuine and frequently decisive advantage.

## Why This Service or Concept Exists

- **Manual container hosting does not scale past one host:** a restarted container, a failed instance, a port clash, or a zero-downtime deployment each needs a controller that sees the whole fleet.
- **ECS is that controller:** it schedules tasks onto capacity, replaces failures, registers tasks with load balancers, delivers per-task IAM identity, and answers authoritatively what runs where.
- **A smaller surface than Kubernetes:** ECS solves the same problem with no custom resources, no controllers to install, and no version to upgrade, trading extensibility for simplicity.
- **Capacity providers decouple the workload from capacity:** a service states a strategy rather than a launch type, which makes mixed On-Demand and Spot fleets and migration between capacity models straightforward.
- **Fargate removes the instance:** each task runs in its own microVM, so there are no AMIs to patch, no fleet to scale, and no bin packing, at a per-vCPU premium and without GPUs or privileged containers.
- **Task addresses are temporary:** in `awsvpc` mode every replacement task gets a new IP, so service discovery is the mechanism that keeps services connected while their members change.

## Core Concepts

### The cluster

A cluster is a logical grouping with four practical roles:

1. **A namespace.** Service names are unique within a cluster, not within an account.
2. **A capacity boundary.** Container instances register with exactly one cluster, and tasks are placed only on capacity in their own cluster.
3. **A permissions boundary.** IAM policies can scope `ecs:*` actions to a cluster ARN, so "this pipeline may deploy only to staging" is expressible.
4. **An observability boundary.** Container Insights, cluster-level metrics, and most dashboards are naturally cluster-scoped.

Cluster settings worth knowing: `containerInsights` (`disabled`, `enabled`, or `enhanced`) controls metric collection; `executeCommandConfiguration` controls ECS Exec logging and KMS encryption; `serviceConnectDefaults` sets a default AWS Cloud Map namespace so individual services need not repeat it; and `defaultCapacityProviderStrategy` applies to services that do not specify their own.

**Cluster topology** is a design decision with real consequences:

| Topology | Argument for | Argument against | Typical fit |
|---|---|---|---|
| **One cluster per account per environment** | Simplest; shared capacity; one dashboard per environment | All teams share a blast radius for capacity exhaustion | Small to medium organisations |
| **One cluster per team per environment** | Team-level isolation and IAM scoping at zero cost | More clusters to observe and configure | The common default at moderate scale |
| **One cluster per application** | Tight blast radius; simple cost attribution | Poor capacity sharing on EC2; sprawl | Regulated or high-criticality applications |
| **One cluster per service** | Maximum isolation | Sprawl; cross-cutting change becomes N changes | Almost never correct |
| **Separate AWS accounts, one or more clusters each** | The strongest boundary; audit scope becomes an AWS boundary | Cross-account networking, sharing, and pipelines to build | Compliance isolation, multi-tenant SaaS silos |

!!! tip "Choose cluster boundaries by blast radius and IAM, not by tidiness"

    The useful questions are: who should be able to deploy here, what should fail together, and what should be observed together. If two workloads have the same answers to all three, they belong in the same cluster. On EC2 capacity there is a fourth question  should these workloads share instances  because sharing improves bin packing and worsens isolation.

### Container instances and the ECS agent

On EC2 capacity, a **container instance** is an EC2 instance that has registered with a cluster. Registration is performed by the **ECS agent**, which runs on the instance (already installed on the ECS-optimised AMI), reads the cluster name from `/etc/ecs/ecs.config`, opens an outbound connection to the ECS control plane, and thereafter reports the instance's **resources** and **attributes** and executes placement instructions.

| Concept | Meaning | Why it matters |
|---|---|---|
| **Registered resources** | Total CPU units, memory, and ports the instance offers | The scheduler's view of capacity |
| **Remaining resources** | What is left after placed tasks | Placement fails when no instance has enough remaining |
| **Attributes** | Key-value facts: AZ, instance type, AMI ID, agent version, custom attributes you set | The vocabulary of placement constraints in [2.3](topic3.md#placement-constraints) |
| **Agent connectivity** | Whether the agent is currently connected | A disconnected agent means no new placements on that instance |
| **Instance status** | `ACTIVE`, `DRAINING`, `REGISTERING`, `DEREGISTERING` | `DRAINING` stops new placement and moves service tasks off, which is how you patch an instance safely |
| **Managed draining** | Capacity provider feature that drains an instance automatically when the ASG terminates it | Prevents scale-in and instance refresh from killing tasks abruptly |

The agent's outbound-only connection matters architecturally: instances need no inbound access from AWS, and in a private subnet they need either a NAT gateway or VPC endpoints for `ecs-agent`, `ecs-telemetry`, and `ecs`, in addition to the ECR and Logs endpoints from 2.1.

### Capacity providers and strategies

A **capacity provider strategy** is a list of providers, each with a `base` and a `weight`.

- **`base`** is an absolute number of tasks placed on that provider *before* weights apply. At most one provider in a strategy may have a non-zero base.
- **`weight`** is a relative share governing how tasks *beyond* the bases are distributed.

For example, `FARGATE` with `base=2, weight=1` and `FARGATE_SPOT` with `weight=4`: the first two tasks go to On-Demand; beyond that, one in five goes to On-Demand and four in five to Spot. At a desired count of twelve, that is two plus two On-Demand and eight Spot.

<figure markdown="span">
    ![3layerglobalinfra](../img/U2/t2/fargatecapacity.png){width="80%"}
    <figcaption>Example of Fargate Capacity Provider</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generaed (Google Gemini)</i></p>
</figure>

**Auto Scaling group capacity providers** add three managed behaviours:

| Feature | What it does | Why it matters |
|---|---|---|
| **Managed scaling** | ECS publishes a `CapacityProviderReservation` metric and drives the ASG towards a target capacity percentage | This is the second scaling layer; without it, tasks stick in `PROVISIONING` |
| **Managed termination protection** | Prevents the ASG scaling in an instance that is still running tasks | Without it, scale-in kills running work |
| **Managed draining** | Sets an instance to `DRAINING` on termination so service tasks are relocated first | Makes instance refresh and Spot interruption graceful |

**Target capacity** deserves explanation because it is routinely misconfigured. Setting it to 100 per cent means ECS aims for no spare room, so every scale-out waits for an instance launch  typically one to three minutes. Setting it to 80 per cent keeps roughly a fifth of the cluster free, so tasks place immediately and the instance launch happens behind them. You are trading a little idle cost for scale-out latency, and for a user-facing service that trade is almost always worth making.

!!! danger "Two scaling layers on EC2, one on Fargate"

    **Service auto scaling** (Application Auto Scaling) changes `desiredCount`  how many tasks you want. **Cluster capacity scaling** (capacity provider managed scaling) changes how many EC2 instances exist for those tasks to run on. They are separate systems and both must be configured. The classic symptom of configuring only the first is a service that raises its desired count during peak and then sits with tasks in `PROVISIONING` forever, while the CPU graphs of the existing instances look fine. On Fargate the second layer does not exist, which removes an entire class of misconfiguration  and is one of the strongest practical arguments for Fargate.

### Tasks, services, and the reconciliation loop

A **task** is one running instantiation of a task-definition revision. A **service** is a controller with a `desiredCount` that continuously compares desired state with observed state and issues the API calls that close the gap. This control loop is the whole idea, and it is worth stating precisely:

1. Observe the set of `RUNNING` tasks belonging to this service.
2. Compare its size and task-definition revision with the desired count and revision.
3. If fewer tasks are running than desired, or a task is unhealthy, place replacements according to the placement strategy and capacity provider strategy.
4. If more are running than desired, or tasks run an old revision during a deployment, deregister and stop the surplus, honouring the deployment configuration.
5. Register newly healthy tasks with any configured load-balancer target groups, and deregister stopping ones first.
6. Repeat, forever.

Use a **standalone task** (`RunTask`) for work that finishes: a database migration, a batch job, a scheduled report. Use a **service** for work that should always be running: an API, a queue consumer, a web front end.

<figure markdown="span">
    ![3layerglobalinfra](../img/U2/t1/TaskReconciliationLoop.png){width="80%"}
    <figcaption>AWS Task Reconciliation Loop</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generaed (Google Gemini)</i></p>
</figure>

!!! tip "Read the state a task is stuck in  it names the cause"

    A task stuck in `PROVISIONING` is waiting for capacity or a network interface: no EC2 room, no free subnet IP addresses, or a Fargate quota. A task that reaches `PENDING` and then `STOPPED` almost always failed to pull the image: check the ECR repository name, the Region, the execution role's permissions, and whether a private subnet has the three endpoints it needs (see [2.1](topic1.md#amazon-ecr-concepts)). A task that reaches `RUNNING` and immediately stops is an application failure: read `stoppedReason` and the container `exitCode`. Reading the state before guessing turns a thirty-minute investigation into a two-minute one.

### Services

A **service** maintains a desired number of tasks from a specified task-definition revision, replaces failures, and registers tasks with load-balancer target groups. Its key properties, beyond the scheduler behaviour covered in [2.3](topic3.md):

| Property | Purpose |
|---|---|
| `desiredCount` | How many tasks should be running |
| `taskDefinition` | Which revision to run |
| `capacityProviderStrategy` or `launchType` | Where tasks run |
| `networkConfiguration` | Subnets, security groups, public IP assignment for `awsvpc` |
| `loadBalancers` | Target group, container name, and container port to register |
| `serviceRegistries` | Cloud Map registration for DNS-based discovery |
| `serviceConnectConfiguration` | Service Connect namespace, advertised services, client aliases |
| `healthCheckGracePeriodSeconds` | How long to ignore load-balancer health checks after a task starts |
| `deploymentConfiguration` | Minimum healthy percent, maximum percent, circuit breaker  see [2.3](topic3.md#deployment-the-rolling-update) |
| `enableExecuteCommand` | Whether ECS Exec is permitted |
| `propagateTags` | Whether service or task-definition tags are copied to tasks, which matters for cost attribution |
| `schedulingStrategy` | `REPLICA` (a desired count) or `DAEMON` (one task per eligible container instance, EC2 only) |

The **`DAEMON`** scheduling strategy is worth noting because it is the ECS analogue of a Kubernetes DaemonSet: exactly one task per eligible container instance, automatically placed on new instances as they join. It is how you run a node-level log collector or monitoring agent  and it is unavailable on Fargate, and also unsupported with the `CODE_DEPLOY` and `EXTERNAL` deployment controllers, which is precisely why Fargate workloads must use sidecars for collection and pay that overhead per task.

### Task network modes

A task definition's `networkMode` (see [2.1](topic1.md#ecs-task-definitions)) determines how a task gets network identity, and it constrains everything that follows: which load-balancer target type can be used, whether each task has its own security group, and how many subnet IP addresses the service consumes.

| Mode | Behaviour | When to use |
|---|---|---|
| `awsvpc` | Task gets its own ENI, private IP, and security groups. **Required on Fargate** | The default for everything; per-task security groups are the security model |
| `bridge` | Docker's virtual bridge; container ports map to host ports, optionally dynamic (host port 0) | EC2 launch type with dynamic port mapping behind an ALB, for density |
| `host` | Container shares the host's network namespace directly | Highest performance, no port isolation; monitoring agents and specialised cases |
| `none` | No external networking | Batch work that needs no network |

### North-south: getting traffic in

| Option | Layer | Strengths | Weaknesses | Choose when |
|---|---|---|---|---|
| **Application Load Balancer** | 7 (HTTP/HTTPS) | Host and path routing, one ALB shared by many services, WebSockets, HTTP/2, gRPC, OIDC authentication, weighted target groups | HTTP only; per-hour plus LCU cost | The default for HTTP services |
| **Network Load Balancer** | 4 (TCP/UDP/TLS) | Extreme throughput, very low latency, static IPs, preserves source IP, non-HTTP protocols | No content-based routing | Non-HTTP protocols, static IP requirements, very high connection counts |
| **Amazon API Gateway** | 7, API-oriented | Per-consumer API keys, usage plans, request validation, throttling, WebSocket APIs, direct AWS service integrations | Higher per-request cost; another hop | You need API management, not just routing  see [Chapter 1.7](../unit1/topic7.md) and [4.2](../unit4/topic2.md) |
| **CloudFront in front of any of these** | Edge | TLS termination near the user, caching, AWS WAF and Shield, absorbs read load | Cache invalidation discipline required | Public-facing services with global users or cacheable content |

**Target types** determine what the load balancer sends packets to:

| Target type | What is registered | Works with | Notes |
|---|---|---|---|
| `ip` | The task's own private IP | `awsvpc` mode; **required on Fargate** | No extra hop; health checks test the task directly; each task consumes a subnet IP |
| `instance` | The container instance and a host port | `bridge` or `host` mode on EC2 | Enables dynamic port mapping for density; adds a NAT hop on the instance |

**Dynamic port mapping** is the reason `instance` targets still exist. In `bridge` mode with a container port of 8080 and a host port of `0`, Docker assigns an ephemeral host port at start, ECS learns it, and ECS registers *that* port with the target group. This lets many copies of the same service share one instance without port conflicts. It is the density play on EC2 capacity, and its cost is losing per-task security groups.

**Health checks** exist at two levels and mean different things, which was introduced in 2.1 and matters operationally here:

| Check | Executed by | Decides | Typical misconfiguration |
|---|---|---|---|
| Container `healthCheck` | The ECS agent, inside the container | Whether ECS considers the container healthy; drives `dependsOn: HEALTHY` | `startPeriod` shorter than the application's cold start, producing a restart loop |
| Target group health check | The load balancer, over the network | Whether the target receives traffic | Wrong port, wrong path, path requiring authentication, or security group blocking the load balancer |

The two can disagree, and when they do the difference is diagnostic: container healthy but target unhealthy points at security groups, the wrong port, or a path that requires authentication.

**Draining settings** determine whether a deployment is invisible. The **deregistration delay** on the target group is what protects in-flight requests: the target is removed from rotation and existing connections are allowed to finish for that many seconds. It must exceed the p99 request duration, and it must be shorter than or comparable to the task's `stopTimeout`, since ECS will otherwise `SIGKILL` a task that is still draining. The full shutdown sequence is deregister, drain, `SIGTERM`, `SIGKILL`.

### East-west: services finding each other

| Mechanism | Where the routing decision is made | Extra network hop | Retries and outlier ejection | Cost | Crosses VPC or account |
|---|---|---|---|---|---|
| **Internal ALB or NLB per service** | At the load balancer | Yes | Coarse | Hourly plus LCU per load balancer | Yes |
| **AWS Cloud Map DNS** | In the client, after DNS resolution | No | None; DNS caching causes stale endpoints | Minimal | Within a VPC or peered network |
| **ECS Service Connect** | In an AWS-managed, Envoy-based proxy on localhost | No | Yes: client-side load balancing, outlier ejection, retries, per-call metrics | Sidecar resource overhead per task | Within a Cloud Map namespace |
| **Amazon VPC Lattice** | In the VPC data plane, transparently | Managed, no sidecar | Retries, weighted routing, IAM auth policies | Per-request and per-hour | Yes, across VPCs, accounts, and compute types |

**ECS Service Connect** is the pragmatic default for ECS-to-ECS HTTP and gRPC. You name a Cloud Map namespace, declare on the server side that a named port mapping is advertised under a discovery name with a client alias, and enable the client side on callers. ECS injects and manages a sidecar proxy in each task  Envoy-based, but not present in your task definition and not configurable by you. Callers then use `http://catalog:8080`, resolved locally. What you get, without writing proxy configuration: connection pooling, client-side load balancing across healthy endpoints, automatic ejection of failing endpoints, and per-request metrics broken down **by client and by server** in the `ECS/ServiceConnect` CloudWatch namespace  telemetry that answers "which caller is causing this callee's errors" without any application instrumentation.

Two constraints are worth stating. The `portMappings` entry in the **server** task definition **must have a `name`**, because that name is what the service definition advertises; client-only services have no such requirement. And enabling Service Connect on an existing service requires a new deployment, since the proxy is injected at task start.

**AWS Cloud Map** registers task IPs as DNS A records (or SRV records for `bridge` mode with dynamic ports) in a private hosted zone. It is simple and protocol-agnostic, which is why it remains correct for non-HTTP traffic. Its weakness is DNS caching: some client libraries and runtimes cache resolutions well beyond the TTL  the JVM historically cached indefinitely by default  so a caller can hold the address of a task that stopped minutes ago.

**Amazon VPC Lattice** is the AWS-native answer to connectivity *between* boundaries: across VPCs, across accounts, and across compute types, so an ECS service can call a Lambda function or an EKS workload through one application-layer network with IAM auth policies and weighted routing, without sidecars. Its natural use case is exactly the one Service Connect does not cover.

!!! warning "AWS App Mesh should not be chosen for new work"

    App Mesh is on a deprecation trajectory. For service-to-service connectivity within ECS, use **Service Connect**; across VPCs, accounts, or compute types, use **Amazon VPC Lattice**; on EKS where a full mesh is genuinely required, use Istio or Linkerd. Certification questions that offer App Mesh as the "modern service mesh" answer are testing whether you are current.

---

The two slow steps are **ENI attachment** and **image pull**, and only the second is under your control  which is why 2.1 treated image size as a scaling property. There is no shared image cache between Fargate tasks, so every task pays the full pull.

**Fargate platform versions** determine the feature set and the underlying agent and kernel. `LATEST` is the sensible default; pinning a version is appropriate only when you have a specific compatibility requirement, and it then becomes something you must remember to move.

### How a task is placed and started on EC2 capacity

```mermaid
sequenceDiagram
    participant SCHED as "ECS scheduler"
    participant CP as "ASG capacity provider"
    participant ASG as "Auto Scaling group"
    participant INST as "Container instance"
    participant AGENT as "ECS agent"
    participant ECR as "Amazon ECR"
    participant TG as "Target group"
    SCHED->>SCHED: "filter instances by constraints, then apply placement strategy"
    alt sufficient remaining resources exist
        SCHED->>AGENT: "start task on instance i-0abc"
    else no instance fits
        SCHED->>SCHED: "task remains in PROVISIONING"
        SCHED->>CP: "publish CapacityProviderReservation above target"
        CP->>ASG: "increase desired capacity"
        ASG->>INST: "launch instance from the ECS-optimised AMI"
        INST->>AGENT: "agent starts, reads /etc/ecs/ecs.config, registers"
        AGENT-->>SCHED: "instance ACTIVE with resources and attributes"
        SCHED->>AGENT: "start task on the new instance"
    end
    AGENT->>ECR: "pull image, or reuse cached layers already on this instance"
    AGENT->>AGENT: "create container, apply cgroup limits, start"
    AGENT-->>SCHED: "task RUNNING"
    SCHED->>TG: "register instance and host port, or task IP in awsvpc mode"
```

The branch is the whole point. When capacity exists, placement is nearly instant. When it does not, the task waits for an instance launch  one to three minutes  which is why target capacity below 100 per cent is worth its idle cost for user-facing services. And the image pull is frequently free on a warm instance, because layers pulled for a previous task are already in the local store.

### Where task start latency goes

| Phase | Fargate | EC2 warm instance | EC2 cold instance |
|---|---|---|---|
| Capacity acquisition | Seconds | Immediate | 60–180 seconds |
| ENI attachment | Several seconds | Several seconds in `awsvpc`; none in `bridge` | Same |
| Image pull | Full pull, every task | Usually cached | Full pull |
| Container start | Application-dependent | Application-dependent | Application-dependent |
| Health check and registration | 15–60 seconds depending on thresholds | Same | Same |

This table is the honest basis for the launch-type decision when scale-out latency matters: EC2 with warm capacity is faster, and Fargate is simpler. If your service must absorb a step change in load within seconds, either keep warm capacity or scale ahead of demand on a schedule  no orchestrator can make a cold start instant.

### How the ALB reaches a task

```mermaid
flowchart LR
    U["Client"] --> ALB["Application Load Balancer in public subnets"]
    ALB -->|"target type ip, awsvpc mode"| T1["Task ENI private IP, port 8080"]
    ALB -->|"target type instance, bridge mode"| I1["Instance private IP, dynamic host port 32768"]
    I1 -->|"docker-proxy or iptables NAT"| C1["Container port 8080"]
    SGA["ALB security group"] -.->|"referenced as source"| SGT["Task or instance security group allows 8080 from SGA"]
```

With `ip` targets the ALB sends packets directly to the task's own ENI: one fewer hop, and the health check tests the task rather than the host. With `instance` targets the packet arrives at the instance on an ephemeral host port and is NATed into the container.

The security-group relationship is where most "target unhealthy" incidents live. The correct pattern is a **security group reference**, not a CIDR: the task's security group allows port 8080 *from the ALB's security group*. This states an identity relationship, survives subnet changes, and is self-documenting.

--- 

## Architecture Components

| Component | Responsibility |
|---|---|
| **Client** | Originates requests; its retry behaviour is a potential source of amplification |
| **Amazon Route 53** | Public DNS for the edge; also hosts the private hosted zone Cloud Map writes discovery records into |
| **Amazon CloudFront** | Edge TLS termination and caching; absorbs read load before it reaches a task |
| **AWS WAF and AWS Shield** | Rule-based filtering and DDoS protection at the edge or the ALB |
| **Application Load Balancer** | Layer 7 entry; host and path routing to per-service target groups; the sharing point that lets many services use one load balancer |
| **Network Load Balancer** | Layer 4 entry for non-HTTP protocols, static IPs, or very high connection volume |
| **Amazon API Gateway** | Managed API front door where API keys, usage plans, and request validation are required |
| **Target group** | The registration point; owns the health check, the deregistration delay, and the target type |
| **Amazon VPC** | The network boundary; its subnet sizing bounds how many `awsvpc` tasks can exist |
| **Public subnets** | Hold load balancers and NAT gateways only |
| **Private subnets** | Hold tasks and container instances; every `awsvpc` task consumes one IP address |
| **Security groups** | Stateful, identity-based firewalls; the correct unit of service-to-service policy through group references |
| **VPC endpoints** | `ecr.api`, `ecr.dkr`, `logs`, `secretsmanager`, `ssm`, `ssmmessages`, `sts`, `ecs`, `ecs-agent`, `ecs-telemetry` as interface endpoints, plus the S3 gateway endpoint |
| **NAT gateway** | Egress for private subnets; a large and frequently unexamined cost line without endpoints |
| **Amazon ECS control plane** | Stores desired state; runs the scheduler and reconciliation loop; charges nothing |
| **ECS cluster** | Logical grouping, capacity boundary, IAM boundary, observability boundary |
| **Capacity provider** | Names where tasks may run and, for ASG providers, manages the underlying fleet |
| **AWS Fargate** | Per-task microVM capacity with no instances to manage |
| **Amazon EC2 container instances** | The alternative capacity substrate, with a warm image cache and lower unit cost at high utilisation |
| **ECS agent** | Registers the instance, executes placement, manages task lifecycle, reports state |
| **Auto Scaling group** | The fleet underneath an ASG capacity provider; also provides instance refresh for patching |
| **AWS Cloud Map** | The service registry backing both Service Connect namespaces and DNS-based discovery |
| **ECS Service Connect** | AWS-managed, Envoy-based proxies providing east-west discovery, load balancing, retries, and telemetry |
| **Amazon VPC Lattice** | Cross-VPC, cross-account, cross-compute application networking with IAM auth policies |
| **Task execution role** | Pulls images, creates log streams, decrypts secrets  before your code runs |
| **Task role** | The application's own AWS identity |
| **Container instance role** | The EC2 instance profile used by the agent; must not carry application permissions |
| **AWS Secrets Manager and SSM Parameter Store** | Sources for the `secrets` block |
| **Amazon CloudWatch and Container Insights** | Metrics, logs, alarms, and the cluster and service dashboards |
| **AWS CloudTrail** | Audit of `RegisterTaskDefinition`, `UpdateService`, `ExecuteCommand`, and every other control-plane call |
| **AWS Systems Manager** | ECS Exec sessions without SSH or bastion hosts |

Read architecturally, these form three rings. The **edge ring**  Route 53, CloudFront, WAF, ALB  is shared across services rather than duplicated per service, which is what keeps decomposition from multiplying the edge bill. The **orchestration ring**  cluster, capacity providers, services, agent or Fargate  is where the control loop lives, and its defining property is that it is declarative: you state desired state and the platform closes the gap continuously. The **connectivity ring**  security groups, endpoints, Service Connect, Cloud Map, Lattice  is where most production incidents actually occur, because it is the part that fails only under change rather than under load.

The reasoning at each hop:

1. **CloudFront terminates TLS at the edge**, removing two round trips for a distant client and keeping warm connections to the origin so the origin handshake is usually already paid for.
2. **WAF evaluates before compute is consumed.** A rate-based rule here protects every service behind the ALB, and blocking at the edge is far cheaper than blocking in your application.
3. **The ALB routes by listener rule.** This is the decomposition made visible: `/orders*` and `/catalog*` are separate target groups, separately deployable and scalable, sharing one load balancer and therefore one certificate and one hourly charge.
4. **The target group chooses a healthy target.** `least_outstanding_requests` is usually better than round robin when request cost varies, because round robin will happily send a cheap request to a task already handling an expensive one.
5. **The packet goes straight to the task's IP.** With `ip` targets there is no instance-level NAT hop, and the health check has been testing this exact task rather than its host.
6. **Logs leave the host immediately.** Nothing useful is retained on the task, which is what makes the task disposable.

### East-west through Service Connect

```mermaid
sequenceDiagram
    participant ORD as "Orders application container"
    participant PXY as "Service Connect proxy in the same task"
    participant CM as "AWS Cloud Map namespace"
    participant CAT1 as "Catalog task 1"
    participant CAT2 as "Catalog task 2"
    Note over PXY,CM: "Endpoint list is refreshed in the background, never per request"
    ORD->>PXY: "GET http://catalog:8080/products/123 on localhost"
    PXY->>PXY: "select a healthy endpoint, client-side load balancing"
    PXY->>CAT2: "forward over a pooled, reused connection"
    CAT2-->>PXY: "200 OK"
    PXY-->>ORD: "200 OK, plus per-call metrics emitted"
    Note over PXY,CAT1: "If catalog task 1 starts failing, the proxy ejects it as an outlier"
```

The critical property is the note at the top: **endpoint discovery happens in the background, not on the request path**. The application resolves a name on localhost; no DNS lookup crosses the network per request, no control-plane call is made, and the proxy's endpoint list is maintained continuously. This is what makes the mechanism resilient to control-plane impairment and immune to DNS caching problems. -->

### Synchronous versus asynchronous, restated for ECS

| Property | Direct call through Service Connect | Message through SQS or EventBridge |
|---|---|---|
| Caller knows the outcome | Immediately | Eventually, or never directly |
| Availability | The product of both services' availability | Depends only on the broker |
| Latency | Added to the caller's own | Only the enqueue time |
| Coupling | Temporal: both must be up at once | Temporally decoupled |
| Failure handling | Retry, circuit break, degrade | Redrive, dead-letter queue, replay |
| Right for | A read the user is waiting on; validation that must precede a response | Anything the user need not wait for; fan-out; spiky work |

!!! tip "Every synchronous hop you remove multiplies out of your availability calculation"

    Six services at 99.9 per cent in series produce roughly 99.4 per cent  about 3.5 hours of downtime per month from six components that each look excellent on their own dashboard. The same arithmetic applies to tail latency. Before adding a synchronous call between two ECS services, ask whether the caller genuinely needs the answer before responding to its own caller. If not, publish an event.

## AWS Service Deep Dive

!!! warning "On numbers and quotas"

    Figures here are representative as of 2026 and most quotas are **soft**  adjustable through AWS Service Quotas or a support case. They vary by Region and account. Verify in the Service Quotas console for the account and Region you are designing in. Pricing is described as **dimensions** and **relative positions** only; model actual cost in the AWS Pricing Calculator.

### Amazon ECS

**Purpose.** Run and scale containerised workloads on AWS with the smallest workable conceptual surface, integrated by default with IAM, VPC networking, Elastic Load Balancing, CloudWatch, and Secrets Manager.

**Architecture.** An AWS-operated, multi-tenant control plane holding cluster, service, and task-definition state and running the scheduler and the reconciliation loop. There is no cluster endpoint, no control-plane node, and no version. The data plane is Fargate microVMs or EC2 instances running the ECS agent.

**Important features.** Immutable versioned task definitions; `REPLICA` and `DAEMON` scheduling strategies; capacity providers with base-and-weight strategies mixing On-Demand and Spot; `awsvpc` networking with per-task ENIs and security groups; ECS Service Connect; Cloud Map service discovery; deployment configuration with a circuit breaker and automatic rollback; blue/green through AWS CodeDeploy; ECS Exec over Systems Manager; task-definition secret injection; container dependency ordering; `stopTimeout`; ECS Anywhere for on-premises capacity; scheduled tasks through EventBridge Scheduler.

**Limitations.** No ecosystem of third-party controllers, operators, or custom resource types  what AWS ships is what exists, and there is no admission-control extension point. No portability: an ECS task definition runs nowhere but AWS. Scheduling is coarser than Kubernetes': placement strategies and constraints rather than affinity, anti-affinity, topology spread, priority, and preemption. Ten containers per task definition. No native equivalent to a Kubernetes operator for running complex stateful software.

**Pricing model.** The control plane and clusters are free. You pay for the data plane  Fargate per vCPU-hour and GB-hour billed per second with a one-minute minimum, or EC2 instance hours  plus the ancillaries: ALB hours and LCUs, NAT gateway hours and data processing, CloudWatch Logs ingestion, ECR storage, and inter-AZ data transfer. In a small estate those ancillaries frequently exceed the compute bill, which surprises people.

**Performance characteristics.** Fargate task start is typically tens of seconds, dominated by ENI attachment and image pull. EC2 capacity with a warm instance and cached layers starts in seconds. Fargate provides no burstable CPU credits: you get the vCPU you declared, consistently, which is an advantage over burstable EC2 families for latency-sensitive work.

**Scaling behaviour.** Two layers on EC2  service auto scaling for tasks, capacity provider managed scaling for instances  and one layer on Fargate. Covered in depth in [2.3](topic3.md#application-auto-scaling-on-ecs).

**Availability.** Spread tasks across at least two and preferably three Availability Zones. On Fargate this is achieved simply by supplying subnets in three AZs; on EC2 it additionally requires the ASG to span three AZs and a `spread` placement strategy on `attribute:ecs.availability-zone`.

**Security features.** Three distinct IAM roles; per-task security groups in `awsvpc` mode; no shared Docker socket on Fargate; read-only root filesystem and non-root user through the task definition; secrets injected rather than baked; ECS Exec audited through CloudTrail and optionally logged to S3 or CloudWatch with KMS encryption; Amazon GuardDuty ECS Runtime Monitoring.

**Service limits (representative, mostly soft).** Clusters per account, services per cluster, and tasks per service are in the thousands and adjustable. Container instances per cluster is in the thousands. Task definition size has a hard ceiling in the low tens of kilobytes  reachable with many environment variables. Ten containers per task definition. Load balancer target groups per service is limited to a small number. Verify all of these in Service Quotas.

**Common configurations.** Fargate launch type or a capacity provider strategy; `awsvpc` mode; private subnets with `assignPublicIp: DISABLED` and VPC endpoints; `awslogs` to a log group with retention set; deployment circuit breaker with rollback enabled; minimum healthy percent 100 and maximum percent 200; Service Connect enabled with one namespace per environment; Container Insights enabled at the cluster.

### AWS Fargate

**Purpose.** Remove the instance layer entirely. You declare CPU and memory; AWS provisions an isolated microVM, patches the substrate, and bills per second.

**Architecture.** Each task runs in its own lightweight virtual machine on AWS-managed capacity, with its own kernel and its own ENI. There is no host you share with another task and no host you can log into.

**Resource model.** Task CPU and memory must come from a **fixed valid matrix**: 0.25 vCPU with 0.5, 1, or 2 GB; 0.5 vCPU with 1 to 4 GB; 1 vCPU with 2 to 8 GB; 2 vCPU with 4 to 16 GB; 4 vCPU with 8 to 30 GB; 8 vCPU with 16 to 60 GB; 16 vCPU with 32 to 120 GB; and 32 vCPU with the three discrete values 60, 120, or 244 GB. An invalid pair is rejected at task-definition registration, and sizes of 8 vCPU and above are Linux-only. Ephemeral storage defaults to 20 GB and is expandable to 200 GB, encrypted, and destroyed with the task.

**Important features.** Per-task microVM isolation; ARM64 (Graviton) support at lower cost than x86; Fargate Spot at a steep discount with two minutes of interruption notice; platform versions; ephemeral storage sizing; EFS volume support for shared persistent storage; ECS Exec.

**Limitations.** A per-vCPU premium over equivalent EC2 capacity, which becomes significant at sustained high utilisation. No GPUs. No local NVMe. No privileged containers, no host-level daemons, and no `DAEMON` scheduling strategy  so log and metric collection must be sidecars, whose overhead multiplies by replica count. No Windows-plus-GPU niches. Slower start than a warm EC2 instance. Fargate Spot is not available for all configurations and should never carry the synchronous request path alone.

**Pricing model.** Per vCPU-hour and per GB-hour of declared resources, billed per second with a one-minute minimum, plus ephemeral storage above the included allowance. Fargate Spot is substantially discounted. Compute Savings Plans apply to Fargate as well as EC2 and Lambda, which makes a committed baseline worth covering.

**Performance characteristics.** Consistent vCPU with no burst credits. Start latency of roughly 30 to 90 seconds for a moderate image, dominated by ENI attachment and pull. No shared image cache, so image size matters more than on EC2.

**Availability.** Tasks are placed across the subnets you supply; supplying three AZs' subnets is the whole configuration.

**Security features.** VM-level isolation per task; no shared kernel with other tasks; no SSH surface; no Docker socket; per-task ENI and security groups; ephemeral storage encrypted with an AWS-managed key or a customer-managed key.

### Amazon EC2 capacity for ECS

**Purpose.** Provide container capacity you control, for workloads Fargate cannot run or economics Fargate cannot match.

**Architecture.** An Auto Scaling group of instances built from the ECS-optimised AMI, wrapped by a capacity provider. The ECS agent on each instance registers it and executes placement.

**Important features.** Any instance family, including GPU, high-memory, compute-optimised, and instances with local NVMe; privileged containers and host daemons; the `DAEMON` scheduling strategy; a warm image-layer cache; bin packing of many small tasks onto fewer instances; Spot instances with capacity-provider-managed draining; instance refresh for AMI patching.

**Limitations.** You own AMI patching, instance scaling, bin packing, and the security posture of the host. The instance is a shared trust boundary for every task on it. Idle headroom is paid for. And capacity scaling is a second system that must be configured and understood.

**Pricing model.** Instance hours, plus EBS. Reserved Instances, EC2 Instance Savings Plans, Compute Savings Plans, and Spot all apply. At sustained high utilisation with commitments, unit cost is materially below Fargate.

**Performance characteristics.** Fast task start on a warm instance with cached layers; no ENI attachment in `bridge` mode. Bin packing lets small tasks share an instance efficiently.

**Security features.** Everything ECS provides plus everything you must do yourself: patch the AMI on a cadence, enforce **IMDSv2 with a hop limit of 1** so containers cannot reach the instance profile, keep the container instance role minimal, and avoid mounting the Docker socket into containers under any circumstances.

!!! danger "The instance is a shared trust boundary"

    On EC2 capacity, every task on an instance shares a kernel and, unless you prevent it, can reach the instance metadata service and assume the container instance role  and if that role has been given application permissions "for convenience", it obtains those too. That single fact defeats per-task IAM roles across the entire instance. Enforce IMDSv2 with a hop limit of 1, keep the container instance role limited to cluster registration, ECR pull, and log writing, and never mount `/var/run/docker.sock` into a container  doing so grants root on the host to whatever is in that container.

### The launch-type decision, made honestly

| Dimension | EC2 capacity | AWS Fargate |
|---|---|---|
| Who patches the host | You, on a cadence you must own | AWS |
| Capacity scaling | A second system you configure and tune | Does not exist |
| Bin packing | Your problem, and a real one | Does not exist |
| Isolation | Shared kernel per instance | microVM per task |
| Task start latency | Fast on warm capacity | Slower; full pull every time |
| Unit cost at sustained high utilisation | Lower, especially with commitments and Spot | Higher |
| Cost at spiky or low utilisation | Poor; you pay for idle | Good; per-second billing |
| GPU, privileged, host daemons, local NVMe | Available | Unavailable |
| `DAEMON` strategy for node agents | Available | Unavailable; use sidecars |
| Operational surface | AMIs, ASGs, agent versions, draining, IMDS | Effectively none |
| Host access | Full root and SSH access; custom kernel configuration | None; runtime debugging through ECS Exec |
| Right for | Sustained high-utilisation fleets, special hardware, teams with platform capability | Spiky load, many small services, small teams, strict per-task isolation |

The decision rule that holds up in practice: **start on Fargate, and move a workload to EC2 capacity when a measured constraint requires it**  a hardware requirement Fargate cannot meet, a sustained-utilisation profile where the premium is material, or a start-latency requirement that only a warm cache satisfies. The reverse migration path  starting on EC2 because it is cheaper per vCPU and discovering you have accidentally acquired a platform team  is the more expensive mistake, because the cost appears as engineering time rather than as a line on an invoice.

Amazon ECS offers two primary compute launch types: **EC2 Launch Type** (customer-managed compute) and **AWS Fargate** (serverless compute). The fundamental split lies between having direct control over the host virtual machines versus abstracting them away entirely.

```
       ECS on EC2 (Customer-Managed)               ECS on AWS Fargate (Serverless)
   ┌─────────────────────────────────────┐      ┌───────────────────────────────────┐
   │             ECS Cluster             │      │            ECS Cluster            │
   │                                     │      │                                   │
   │  ┌───────────────────────────────┐  │      │  ┌─────────────┐ ┌─────────────┐  │
   │  │       EC2 Instance (VM)       │  │      │  │  Task / Pod │ │  Task / Pod │  │
   │  │  ┌───────────┐ ┌───────────┐  │  │      │  │ ┌─────────┐ │ │ ┌─────────┐ │  │
   │  │  │Container A│ │Container B│  │  │      │  │ │Container│ │ │ │Container│ │  │
   │  │  └───────────┘ └───────────┘  │  │      │  │ └─────────┘ │ │ └─────────┘ │  │
   │  │    ECS Container Agent        │  │      │  │  Dedicated  │ │  Dedicated  │  │
   │  │    OS (Linux / Windows)       │  │      │  │  MicroVM    │ │  MicroVM    │  │
   │  └───────────────────────────────┘  │      │  └─────────────┘ └─────────────┘  │
   │  [User manages OS, patching, VM]    │      │  [AWS manages all underlying infra]│
   └─────────────────────────────────────┘      └───────────────────────────────────┘

```

### Working Mechanisms

**1. ECS EC2 Launch Type**

* **Cluster Bootstrapping:** You define an Auto Scaling Group (ASG) of EC2 instances registered to an ECS cluster via the pre-installed `amazon-ecs-agent`.
* **Task Placement:** When you launch a task or service, the ECS control plane inspects the cluster's registered instances. Using placement strategies (such as `binpack`, `spread`, or `random`), it schedules the task onto an EC2 node that has sufficient unreserved CPU and memory.
* **Execution:** The ECS agent on that specific instance interacts with the local container runtime (Docker/containerd) to pull the image and run the container alongside other co-located workloads.

**2. ECS Fargate Launch Type**

* **Resource Specification:** You define your task with precise resource requirements (e.g., `0.5 vCPU`, `1 GB RAM`) and launch type set to `FARGATE`.
* **Seamless Provisioning:** The ECS control plane directly contacts the Fargate fleet infrastructure. It provisions an ephemeral, purpose-built microVM (using Firecracker) matching your required task boundaries.

- **Execution & Isolation:** The container executes inside its dedicated microVM boundary with its own Elastic Network Interface (ENI) provisioned in your VPC (`awsvpc` network mode), completely isolated from all other customer workloads. When the task stops, the underlying compute is automatically deprovisioned.

---

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **Cluster** | A logical grouping of ECS services, tasks, and container instances; a namespace, capacity, IAM, and observability boundary |
| **Container instance** | An EC2 instance registered with an ECS cluster by the ECS agent |
| **ECS agent** | The process on a container instance that registers it, executes placement, and reports task state |
| **Registered and remaining resources** | The CPU, memory, and ports an instance offers, and what is left after placed tasks |
| **Attribute** | A key-value fact about a container instance used by placement constraints |
| **Draining** | Container instance status that stops new placement and relocates service tasks off the instance |
| **Managed draining** | Capacity provider feature that drains instances automatically on ASG termination |
| **Capacity provider** | Named capacity for task placement: `FARGATE`, `FARGATE_SPOT`, or an ASG provider |
| **Capacity provider strategy** | A list of providers with `base` and `weight` controlling task distribution |
| **`base`** | An absolute number of tasks placed on a provider before weights apply; at most one provider may have a non-zero base |
| **`weight`** | The relative share of tasks beyond the bases |
| **Managed scaling** | Capacity provider feature driving the ASG size from the `CapacityProviderReservation` metric |
| **Target capacity** | The percentage of cluster capacity managed scaling aims to keep in use; below 100 leaves headroom for fast placement |
| **Managed termination protection** | Prevents ASG scale-in from terminating instances still running tasks |
| **Launch type** | The older, simpler way to state capacity: `EC2`, `FARGATE`, or `EXTERNAL` |
| **AWS Fargate** | Serverless container capacity with a microVM per task |
| **Fargate Spot** | Discounted, interruptible Fargate capacity with two minutes of notice |
| **Platform version** | The Fargate runtime version determining available features |
| **Ephemeral storage** | The temporary encrypted volume attached to a Fargate task, destroyed with it |
| **Service** | The controller maintaining a desired count of tasks and registering them with load balancers |
| **Task** | A running instantiation of a task-definition revision |
| **Standalone task** | A task launched with `RunTask` that runs to completion and is not maintained |
| **`REPLICA` scheduling strategy** | Maintain a desired number of tasks |
| **`DAEMON` scheduling strategy** | Run exactly one task per eligible container instance; EC2 capacity only, and not supported with the `CODE_DEPLOY` or `EXTERNAL` deployment controllers |
| **`healthCheckGracePeriodSeconds`** | How long a service ignores load-balancer health checks after a task starts |
| **`awsvpc` network mode** | Each task receives its own ENI, private IP, and security groups; required on Fargate |
| **`bridge` network mode** | Docker bridge networking with static or dynamic host-port mapping |
| **Task metadata endpoint** | The link-local endpoint supplying task metadata and task-role credentials to containers |
| **Dynamic port mapping** | Host port `0` in `bridge` mode; ECS registers the assigned ephemeral port with the target group |
| **Target group** | The Elastic Load Balancing resource holding targets, the health check, and the deregistration delay |
| **Target type `ip`** | Registers the task's own IP; required for `awsvpc` and Fargate |
| **Target type `instance`** | Registers the container instance and host port; enables dynamic port mapping |
| **Deregistration delay** | Seconds the load balancer allows in-flight requests to finish after removing a target |
| **Listener rule** | The ALB rule matching host or path and forwarding to a target group; how many services share one ALB |
| **`least_outstanding_requests`** | ALB algorithm sending a request to the target with the fewest in-flight requests |
| **Cross-zone load balancing** | Distributing across targets in all AZs; improves balance, incurs inter-AZ transfer charges |
| **AWS Cloud Map** | The service registry maintaining DNS and API-queryable records of service instances |
| **Service registry** | The `serviceRegistries` block registering a service's tasks into Cloud Map |
| **ECS Service Connect** | ECS-managed discovery with an injected, AWS-managed Envoy-based proxy providing client-side load balancing, retries, and telemetry |
| **Discovery name** | The name under which a Service Connect service is advertised in its namespace |
| **Client alias** | The hostname and port callers use to reach a Service Connect service |
| **Amazon VPC Lattice** | AWS-native application networking across VPCs, accounts, and compute types with IAM auth policies |
| **Task execution role** | The role the agent assumes to pull images, create log streams, and decrypt secrets |
| **Task role** | The role application code assumes for AWS API calls |
| **Container instance role** | The EC2 instance profile used by the ECS agent |
| **IMDSv2 and hop limit** | Instance metadata protections; hop limit 1 prevents containers reaching the instance profile |
| **ECS Exec** | Interactive shell into a running container over AWS Systems Manager |
| **Container Insights** | CloudWatch's curated container metrics, logs, and dashboards for ECS |
| **`CapacityProviderReservation`** | The CloudWatch metric managed scaling uses to drive ASG capacity |
| **ECS Anywhere** | Running ECS tasks on customer-managed on-premises or other-cloud capacity |

---

## Configuration Options

### Cluster configuration

| Setting | Options | How to decide |
|---|---|---|
| **Container Insights** | `disabled`, `enabled`, `enhanced` | `enhanced` for production; the per-metric cost is small next to the diagnostic value of per-task CPU, memory, and restart counts |
| **Default capacity provider strategy** | Any provider mix | Set it so that services created without an explicit strategy inherit a sensible default rather than a bare launch type |
| **Service Connect defaults** | A Cloud Map namespace | One namespace per environment, set at the cluster so services need not repeat it |
| **Execute command configuration** | Logging destination, KMS key | Log every ECS Exec session to CloudWatch or S3 and encrypt it; unlogged shell access into production is an audit finding |
| **Cluster granularity** | Per environment, per team, per application | By blast radius and IAM scope; clusters are free but not costless |

### Capacity provider configuration

| Setting | Options | How to decide |
|---|---|---|
| **Provider mix** | `FARGATE`, `FARGATE_SPOT`, ASG providers | On-Demand base sized to carry minimum viable traffic; Spot for the remainder where the workload tolerates interruption |
| **`base`** | 0 or a positive integer on one provider | Set it to the number of tasks that must survive a total Spot reclamation |
| **`weight`** | Relative integers | Express the steady-state ratio; 1:4 On-Demand to Spot is a common starting point |
| **Managed scaling** | Enabled or disabled | Always enabled on ASG providers; disabling it is the cause of the stuck-`PROVISIONING` failure |
| **Target capacity** | 1–100 per cent | 80–90 per cent for user-facing services so scale-out does not wait for an instance launch; closer to 100 for batch work where latency does not matter |
| **Managed termination protection** | Enabled or disabled | Enabled, or scale-in terminates instances that are still running tasks |
| **Managed draining** | Enabled or disabled | Enabled, so instance refresh and Spot interruption relocate tasks rather than killing them |
| **Instance types in the ASG** | One type, or a mixed-instances policy | A mixed-instances policy with several compatible types materially improves Spot availability |

### Service networking and load balancing

| Setting | Options | How to decide |
|---|---|---|
| **Subnets** | Any set | Private subnets in three AZs; the number of AZs you supply is the availability configuration |
| **`assignPublicIp`** | `ENABLED`, `DISABLED` | `DISABLED`; reach AWS APIs through VPC endpoints, and the internet through a NAT gateway only if genuinely required |
| **Security groups** | Any | One per service, allowing the load balancer's security group on the container port; use group references, never CIDRs |
| **Load balancer type** | ALB, NLB, none | ALB for HTTP; NLB for TCP, UDP, static IPs, or extreme throughput; none for queue consumers and workers |
| **Target type** | `ip`, `instance` | `ip` with `awsvpc`; `instance` only for `bridge`-mode density on EC2 |
| **Health-check path and thresholds** | Any path, interval, thresholds | A dedicated `/health` that checks only self-health; 15-second interval, 2 healthy, 3 unhealthy is a reasonable default |
| **`healthCheckGracePeriodSeconds`** | Seconds | Longer than the application's slowest cold start, or the ALB kills tasks that were still warming and the service replaces them in a loop |
| **Deregistration delay** | Seconds, default 300 | Just above p99 request duration; too low drops in-flight requests, too high slows every deployment |
| **ALB algorithm** | `round_robin`, `least_outstanding_requests` | `least_outstanding_requests` where request cost varies, which is most of the time |
| **Cross-zone load balancing** | On (ALB default) or off | On for even distribution; be aware it generates inter-AZ transfer charges |
| **Sticky sessions** | Off, or duration-based | Off; sticky sessions are a transitional crutch for applications with in-memory session state, and should carry a removal ticket |

### Service discovery

| Setting | Options | How to decide |
|---|---|---|
| **Mechanism** | Service Connect, Cloud Map DNS, internal load balancer, VPC Lattice | Service Connect for ECS-to-ECS HTTP and gRPC; Cloud Map for non-HTTP; internal load balancer or Lattice across VPCs and accounts |
| **Service Connect mode** | Client only, or client-and-server | Server side on anything that is called; client-only on callers that advertise nothing |
| **`portMappings.name`** | Any name | **Required** for Service Connect; a mapping without a name cannot be advertised |
| **Client alias** | Hostname and port | Use the logical service name and its natural port, so application configuration reads as `http://catalog:8080` |
| **Namespace** | One per environment, or shared | One per environment; a shared namespace across environments invites a staging service resolving a production peer |
| **Cloud Map TTL** | Seconds | Low, 15 to 30 seconds, and accept that some clients ignore it entirely  which is the argument for Service Connect |

!!! warning "`healthCheckGracePeriodSeconds` is the setting that causes endless replacement loops"

    A service registered with a load balancer will have its tasks killed by the ALB's health check if they are not healthy in time. If your application takes 45 seconds to warm up and the grace period is 0, every task is killed at around 30 seconds, replaced, killed again, and the service never stabilises  while the logs show an application that was starting perfectly normally. Set the grace period above the measured cold start, and set the container `healthCheck`'s `startPeriod` too.

---

## AWS Best Practices

- **Operational Excellence:** define clusters, capacity providers, task definitions, and services as infrastructure as code, and give every service the same health-check path, log format, tags, and dashboard.
- **Operational Excellence:** enable Container Insights and ECS Exec with session logging, and turn on the deployment circuit breaker so rollback is automatic.
- **Security:** give every service its own narrowly scoped task role, keep the execution role separate, and use `secrets` rather than `environment` for credentials.
- **Security:** run tasks in private subnets behind a public load balancer, use security-group references between services, and on EC2 capacity enforce IMDSv2 and never mount the Docker socket.
- **Reliability:** spread tasks across three Availability Zones, keep an On-Demand base under any Spot capacity, and set the health-check grace period above the measured cold start.
- **Performance Efficiency:** right-size tasks from Container Insights measurements, keep images small, and prefer Service Connect to internal load balancers for east-west traffic.
- **Cost Optimization:** choose Fargate or EC2 on measured utilisation, cover the steady baseline with Compute Savings Plans, share one ALB across services, and scale non-production services to zero out of hours.
- **Sustainability:** higher utilisation, Graviton capacity, and deleting idle environments reduce energy use as well as cost.

---

## Monitoring and Observability

```mermaid
flowchart LR
    T["ECS tasks"] -->|"stdout via awslogs or FireLens"| CWL["CloudWatch Logs"]
    T -->|"OTLP"| ADOT["ADOT collector sidecar"]
    ADOT --> XR["AWS X-Ray"]
    ADOT --> AMP["Amazon Managed Prometheus"]
    CI["Container Insights"] --> CWM["CloudWatch metrics"]
    SC["Service Connect proxy"] --> SCM["ECS/ServiceConnect metrics by client and server"]
    ALB["Application Load Balancer"] --> ALBM["Target group metrics"]
    CWL --> LI["CloudWatch Logs Insights"]
    CWM --> DASH["Dashboards and alarms"]
    SCM --> DASH
    ALBM --> DASH
    XR --> MAP["Service map"]
    DASH --> ONCALL["On-call engineer"]
    MAP --> ONCALL
    CT["AWS CloudTrail"] --> AUDIT["Who deployed what, and when"]
```

| Metric | Source | What it tells you |
|---|---|---|
| **`RunningTaskCount` versus `DesiredTaskCount`** | Container Insights | A persistent gap means placement failure: no capacity, no free IPs, or failing health checks |
| **`CapacityProviderReservation`** | ECS capacity provider | Whether the cluster capacity layer is keeping up; a sustained value above target means instances are being added |
| **`UnHealthyHostCount`** | ALB target group | The single most informative deployment-failure signal; if it rises during a deploy, roll back |
| **`HTTPCode_Target_5XX_Count`** | ALB | Application errors  distinct from `HTTPCode_ELB_5XX_Count`, which means no healthy target or an ALB-level failure |
| **`TargetResponseTime` p99** | ALB | User-perceived latency including queueing, not just server-side processing |
| **`ALBRequestCountPerTarget`** | ALB target group | Load per task; the best auto-scaling signal for request-serving services |
| **`CPUUtilization`, `MemoryUtilization`** | Container Insights | Saturation and the input to right-sizing |
| **Task restart count** | Container Insights | Crash loops and repeated `OOMKilled` events |
| **Service events** | `DescribeServices` | Placement failures, registration, scaling actions  usually name the cause outright |
| **`stoppedReason` and `exitCode`** | `DescribeTasks` | Why an individual task died; read this before hypothesising |
| **Service Connect request count and error rate by client** | `ECS/ServiceConnect` | Which caller is causing a callee's errors, with no application instrumentation |
| **Spot interruption events** | EventBridge | Whether Spot reclamation is affecting your service, and how often |
| **Error-budget burn rate** | Derived from SLIs | The only alarm that reliably corresponds to user harm |

**The diagnostic order that works.** For any ECS problem: read the **service events** first, because they name placement failures explicitly; then compare **desired against running**; then read the most recent stopped task's **`stoppedReason` and `exitCode`**; then check **target health** and its reason string; then, and only then, read application logs. Reversing this order  starting with application logs  is the most common cause of long investigations of problems the API had already named.

**Logs.** Structured JSON to `stdout` with a correlation ID, trace ID, service name, and version on every line. Set retention on every log group. Use metric filters to turn log patterns into alarmable metrics where a condition is only visible in logs.

**Tracing.** Instrument with OpenTelemetry through ADOT rather than a vendor SDK, so the destination is a configuration choice. Propagate context across asynchronous boundaries in SQS message attributes or EventBridge payloads, or traces fracture at exactly the boundary you most need to understand. The trace-derived service map is also the most reliable architecture diagram you will have, because it reflects what the system does rather than what a document claims.

**Alarms.** Alert on symptoms users feel  error rate, latency, backlog age, unhealthy host count  and reserve resource alarms for capacity planning rather than paging. Add CloudWatch Synthetics canaries against critical paths so you learn of an outage from a probe rather than from a customer.

---

## Advantages

**No control plane to operate, and no charge for it.** There is no cluster endpoint, no etcd, no API server, no version, and no upgrade. For an organisation without a platform team this removes an entire category of recurring work  and unlike EKS, clusters themselves are free, so isolation between teams or environments can be bought by creating another cluster rather than engineered inside a shared one.

**A small, closed conceptual surface.** Clusters, capacity providers, task definitions, tasks, and services. A competent engineer is productive in days rather than months. There are no third-party controllers to select, install, secure, and upgrade, which means the platform does not quietly become a project.

**Deep AWS integration by default.** IAM roles per task, per-task security groups, ALB target registration, CloudWatch Logs, Secrets Manager injection, Systems Manager shell access, and CloudTrail audit all work by configuration rather than by installation. On other orchestrators several of these are controllers you adopt and maintain.

**Capacity flexibility without workload changes.** The same task definition runs on Fargate, on EC2 capacity, on Spot, and on ECS Anywhere. Capacity provider strategies let a single service span On-Demand and Spot with a guaranteed floor, expressed in two numbers.

**Fargate's isolation and simplicity.** A microVM per task removes the shared-kernel concern and the instance metadata hazard simultaneously, and removes AMI patching, fleet scaling, and bin packing from your responsibilities. For many organisations this is worth more than the per-vCPU premium costs.

**Service Connect as managed east-west networking.** Client-side load balancing, connection pooling, outlier ejection, retries, and per-caller telemetry, with no proxy configuration to write, no extra network hop, and no internal load balancer to pay for. Obtaining the equivalent elsewhere means adopting and operating a service mesh.

**Operational transparency.** Service events, `stoppedReason`, `exitCode`, and Container Insights answer most questions directly. ECS Exec provides a shell without SSH, bastions, or open ports, with every session audited.

---

## Limitations

**No ecosystem and no extension points.** What AWS ships is what exists. There is no admission control, no custom resource type, no operator pattern for running complex stateful software, and no community controller for a capability AWS has not built. If your requirement is one of those, ECS cannot meet it and the honest answer is EKS.

**No portability.** An ECS task definition runs on AWS and nowhere else. If a genuine multi-cloud or hybrid requirement exists, that is a strong argument against ECS  though it is worth testing whether the requirement is genuine, since Kubernetes manifests port while the surrounding IAM, load-balancer controller, and CNI configuration do not.

**Coarser scheduling.** Placement strategies and constraints are less expressive than affinity, anti-affinity, topology spread, priority, and preemption. For most workloads this does not matter; for dense mixed-workload clusters it does.

**Two scaling layers on EC2 capacity.** Service scaling and cluster capacity scaling are separate systems, and configuring only the first is one of the most common production failures in this chapter. Fargate removes the problem; EC2 capacity requires understanding it.

**Fargate's specific limitations.** A per-vCPU premium at sustained high utilisation. No GPUs, no privileged containers, no host daemons, no `DAEMON` scheduling, no local NVMe. Fixed CPU and memory combinations rather than arbitrary values. Ephemeral storage capped in the low hundreds of gigabytes. No shared image cache, so every task pays a full pull and image size matters more.

**EC2 capacity's specific limitations.** You own AMI patching, fleet scaling, bin packing, draining, and the IMDS hazard. The instance is a shared trust boundary. Idle headroom is paid for, and the headroom you remove to save money is the headroom that made scale-out fast.

**Networking constraints inherited from the VPC.** Every `awsvpc` task consumes a private IP address, so subnet sizing bounds task count, and subnet CIDRs cannot be resized. `bridge` mode relieves the pressure at the cost of per-task security groups.

**A smaller hiring pool.** ECS skills are AWS-specific and less transferable than Kubernetes skills, which matters for hiring and for engineers' own career reasoning. This is a real cost even where it is not a technical one.

---

## Summary

First, **the cluster is a boundary, not a machine, and on ECS it is free**  which changes the shape of good designs. There is no control plane to operate, no version to upgrade, and no hourly charge, so isolation between teams and environments can be obtained by creating another cluster rather than by engineering multi-tenancy inside a shared one. The boundaries worth drawing are the ones that answer who may deploy here, what should fail together, and what should be observed together. The failure mode at both extremes is real: one cluster for everything gives every team a shared blast radius, and one cluster per service turns every cross-cutting change into N changes with no estate-wide view.

Second, **capacity is a separate decision from workload, and capacity providers are what make that separation real**. A task definition describes what to run; a capacity provider strategy describes where, in what proportion, and with what guaranteed floor. The `base` is a reliability decision  the number of tasks that must survive a total Spot reclamation  and the `weight` is an economic one. On EC2 capacity there are two scaling layers and both must be configured, which is the source of the most common production failure in this chapter; on Fargate the second layer does not exist, which is one of the strongest practical arguments for it.

Third, **the EC2-versus-Fargate decision is a measurement, not a preference, and the same organisation will correctly reach opposite answers for different workloads**. Fargate wins on spiky utilisation, on small estates of many small services, on per-task microVM isolation, and above all on the operational cost it removes  the AMI patching, the fleet scaling, the bin packing, the instance metadata hazard, and the second scaling layer. EC2 wins on sustained high utilisation with commitments, on hardware Fargate does not offer, on warm-cache start latency, and on `DAEMON` workloads. The asymmetry worth remembering is that Fargate's cost appears on an invoice where it can be seen, and EC2's cost partly appears as engineering time where it cannot.

Fourth, **the network is where a container architecture succeeds or fails, and it fails under change rather than under load**. Every `awsvpc` task consumes a subnet IP address, so subnet sizing bounds the estate and cannot be corrected later. Security-group references rather than CIDRs express service-to-service permission as identity. VPC endpoints let a task start, log, and fetch secrets without any route to the internet, which is simultaneously a security improvement, a cost reduction, and a latency improvement. And the settings that make a deployment invisible  deregistration delay, `SIGTERM` handling, `stopTimeout`, health-check grace period  are four separate values that must agree, none of whose defaults suit a real workload.

Fifth, **east-west connectivity should not go through a load balancer when it does not have to**. Service Connect places the routing decision in a proxy inside the task: no network hop, no hourly charge, no control-plane call on the request path, connection pooling, outlier ejection, and per-caller telemetry that answers "which client is causing this server's errors" without any application instrumentation. Cloud Map DNS remains correct for non-HTTP protocols but inherits DNS caching semantics, which is a genuine failure mode during deployments. VPC Lattice is the answer when the call crosses a VPC, an account, or a compute type. And the more important question than any of these is whether the call needs to be synchronous at all, because availability multiplies down a synchronous chain and latency adds up it.

Sixth, **the platform names its own failures, and the diagnostic order is a skill**. Service events, then desired versus running, then `stoppedReason` and `exitCode`, then target health with its reason string, then application logs. Almost every failure in this chapter is identified in the first three steps, and the habit of reading them before hypothesising is more transferable than any individual fact in the chapter. The corollary is that Container Insights and ECS Exec should be enabled before an incident rather than during one, because an investigation that requires a configuration change first has already lost the time that mattered.

Seventh, and connecting back to [Chapter 1.7](../unit1/topic7.md), **ECS is a deliberate trade of extensibility for simplicity, and that trade is a legitimate architectural choice rather than a compromise**. There is no ecosystem, no admission control, no operator pattern, and no portability. In exchange there is nothing to upgrade, nothing to install, no platform team implied, and no cluster charge. For a team whose workloads are AWS-resident and whose scarce resource is engineering attention, that is frequently the better trade  and being able to say so plainly, in a room that expects to hear Kubernetes, is a substantial part of what an architect is for.

---

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit2.md#22-amazon-ecs) · [Interview questions](../interviewquestions/unit2.md#22-amazon-ecs).

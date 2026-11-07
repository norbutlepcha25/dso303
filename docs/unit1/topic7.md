<!-- teachprep:refined 2026-10-11 -->
# Cloud-Native Design Patterns: Serverless, Microservices, Event-Driven, API-First

## Definition

A **cloud-native design pattern** is a reusable solution to a recurring architectural problem. It assumes the application runs on elastic, distributed, API-driven cloud infrastructure, not on fixed on-premises servers.

Cloud-native applications are designed _for_ the cloud, not merely _moved to_ it. The Cloud Native Computing Foundation (CNCF) describes cloud-native systems as loosely coupled, resilient, manageable and observable, combined with robust automation so that engineers can make high-impact changes frequently and predictably.

Four patterns form the structural pillars of cloud-native design:

| Pattern | One-sentence definition | Question it answers |
|---|---|---|
| **Serverless** | Run code without provisioning or managing servers; the provider allocates compute on demand and bills per use | How is compute provisioned and billed? |
| **Microservices** | Split an application into small, independently deployable services, each owning its data | How is the system decomposed? |
| **Event-Driven** | Components communicate by producing and consuming events asynchronously | How do parts communicate without coupling? |
| **API-First** | Design and agree the API contract before writing implementation code | How is integration governed? |

!!! info "Patterns, not products"
    A pattern is a way of thinking; a service is a tool. You can build microservices badly on EKS, and you can build a serverless system that breaks every microservices principle. Examinations and interviews test whether you understand the _pattern_, not whether you can name the service.

## Why These Patterns Exist

- **The monolith did not fit the cloud:** one deployable artifact and one shared database meant whole-application scaling, a blast radius covering every feature, and releases measured in weeks or months.
- **Compute became elastic and metered:** provisioning for peak is wasteful when capacity arrives in seconds and is billed per second, and serverless takes this to pay-per-invocation.
- **Failure became normal:** in fleets spread across Availability Zones something is always failing, so architectures isolate failure (microservices) and absorb it asynchronously (event-driven).
- **Delivery speed became a competitive advantage:** independent deployability (microservices) and stable contracts (API-first) make frequent releases safe.
- **Organisation shapes architecture:** by Conway's Law systems mirror communication structures, so small autonomous teams own small autonomous services.

<figure markdown="span">
    ![Evolution from monolith to cloud-native architecture](../img/U1/architectureEvolution.png){width="80%"}
    <figcaption>Evolution of software architecture stages</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generated (Google Gemini)</i></p>
</figure>

## Core Concepts

### Coupling and cohesion

These two ideas underlie all four patterns.

- **Coupling** is how much components depend on each other. Cloud-native design reduces three kinds:
    - **Technology coupling**: a service should not care what language or database another service uses.
    - **Temporal coupling**: a producer should not need the consumer to be available _right now_. Event-driven design removes this.
    - **Location coupling**: a producer should not need to know _who_ or _how many_ consumers exist.
- **Cohesion** is how well the responsibilities inside one component belong together. A good microservice has high cohesion: it does one business capability completely.

!!! tip "One rule to remember"
    Aim for **low coupling between components** and **high cohesion within them**. Every pattern below is a way of achieving that.

### Serverless  core concepts

- **Function as a Service (FaaS):** code packaged as functions triggered by events. AWS Lambda is the canonical FaaS.
- **Serverless is broader than FaaS:** S3, DynamoDB on-demand, SQS, EventBridge, Fargate, Aurora Serverless and Step Functions are also serverless, because you never manage capacity.
- **Scale-to-zero:** no traffic means no compute cost. This is the defining economic property.
- **Stateless, short-lived environments:** state must live in external stores such as DynamoDB, S3 or ElastiCache.
- **Cold start:** the extra latency of creating a new execution environment when no warm one is free. It is the price of scale-to-zero.
- **Concurrency model:** Lambda handles one request per environment and scales by adding environments, not threads.

<figure markdown="span">
    ![Lambda invocation routed to a warm or a newly created execution environment](../img/U1/LambdaInvocation.png){width="80%"}
    <figcaption>Lambda invocation: warm start versus cold start</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generated (Google Gemini)</i></p>
</figure>

How Lambda works internally (execution environments, memory and CPU, concurrency, Provisioned Concurrency and SnapStart) is covered in [1.3 AWS Compute Services](topic3.md#aws-lambda).

### Microservices  core concepts

- **Bounded context** (from Domain-Driven Design): each service maps to one business subdomain with its own vocabulary, such as Orders, Inventory or Payments.
- **Independent deployability:** the single most important test. If deploying service A needs service B's team, you have a distributed monolith.
- **Database per service:** each service owns its data and exposes it only through its API or events.
- **Smart endpoints, dumb pipes:** business logic lives in services; the network (ALB, SQS) only transports messages.
- **Service discovery:** services find each other through DNS (AWS Cloud Map), load balancers or a service mesh, not hard-coded addresses.
- **Decentralised governance:** teams choose their own languages and databases within organisational guardrails.

On AWS a containerised microservice is built into an image (ECR), scheduled by ECS or EKS across Availability Zones, registered behind a load balancer or in Cloud Map, and scaled on metrics. See [2.2 Amazon ECS](../unit2/topic2.md), [2.3](../unit2/topic3.md) and [3.1 Amazon EKS Architecture](../unit3/topic1.md) for how the orchestrators do this, and [4.1 Microservices Design Principles](../unit4/topic1.md) for decomposition, granularity and data ownership in depth.

!!! warning "The distributed monolith"
    The most common and most damaging failure mode: services are split physically but stay logically coupled. They share a database, must be released together, and call each other synchronously in long chains. This brings every cost of microservices and none of the benefits. Diagnostic question: _can this service be deployed to production right now without coordinating with any other team?_ If not, it is not a microservice.

### Event-driven  core concepts

- **Event:** an immutable record that _something happened_, such as `OrderPlaced` or `PaymentCaptured`. Events are facts about the past, not requests.
- **Command versus event:** a command (`ChargeCard`) asks one specific recipient to act and implies coupling; an event announces a fact to whoever cares.
- **Producer and consumer:** producers emit events without knowing the consumers; consumers subscribe without knowing the producers.
- **Event router or broker:** the intermediary, for example EventBridge, SNS, SQS or Kinesis.
- **Choreography versus orchestration:**
    - _Choreography:_ services react to each other's events with no central coordinator. Flexible, but the overall flow is implicit.
    - _Orchestration:_ a central coordinator (Step Functions) directs the workflow. Visible and auditable, but a central dependency.
- **Delivery semantics:** at-least-once delivery is the practical default, so consumers must be **idempotent** (safe to process the same event twice).
- **Eventual consistency:** consumers process events after the fact, so services' views of the data converge over time rather than instantly.

Each broker implements a different messaging model. The model, not the brand name, is what the pattern depends on:

| Broker | Model | What happens to a message after it is read |
|---|---|---|
| **SQS** | Point-to-point queue; consumers poll | Hidden while processed, deleted on success, retried if not; repeated failures go to a dead-letter queue |
| **SNS** | Pub/sub topic; the service pushes | A copy goes to every subscription |
| **EventBridge** | Event bus; rules match on event content | Delivered to the targets of every matching rule; can be archived and replayed |
| **Kinesis Data Streams** | Ordered, partitioned log | Kept for the retention period; each consumer tracks its own position and can replay |

<figure markdown="span">
    ![Producers publishing events through a broker to independent consumers](../img/U1/EventDriven.png){width="80%"}
    <figcaption>Event-driven architecture example</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generated (Google Gemini)</i></p>
</figure>

Service mechanics (visibility timeout, FIFO, DLQ redrive, filters, shards, rules, archives and Pipes) are covered in [6.3 Messaging and Event Streaming](../unit6/topic3.md): see [SQS](../unit6/topic3.md#message-queues-with-amazon-sqs), [SNS](../unit6/topic3.md#pubsub-messaging-with-amazon-sns), [Kinesis](../unit6/topic3.md#stream-processing-with-amazon-kinesis) and [EventBridge](../unit6/topic3.md#event-routing-with-amazon-eventbridge).

!!! warning "At-least-once means duplicates will happen"
    SQS standard queues, SNS and EventBridge all deliver at least once. Retries and timeouts produce duplicates in production. Make consumers idempotent, for example by recording processed event IDs in DynamoDB with a conditional write. See [4.3 Idempotency](../unit4/topic3.md#idempotency).

### API-first  core concepts

- **Contract-first design:** the specification (OpenAPI for REST, a GraphQL schema, AsyncAPI or EventBridge schemas for events) is written, reviewed and agreed _before_ implementation.
- **API as product:** APIs have consumers, documentation, versioning, SLAs and a lifecycle. They are products, not by-products.
- **Consumer-driven design:** the contract is shaped by what consumers need, not by the internal data model.
- **Versioning and backward compatibility:** contracts evolve additively; breaking changes need a new version and a deprecation timeline.
- **Parallel development:** once the contract exists, frontend and backend teams build at the same time against mock servers.
- **Governance:** style guides, linting (for example Spectral) and reviews keep many APIs consistent.

The API-first workflow in practice:

1. Architects and consumers co-author an **OpenAPI 3.x specification** (paths, schemas, status codes, authentication).
2. The specification is reviewed like code, through pull requests and linting.
3. Mock servers are generated so consumers can integrate immediately.
4. The specification is **imported into API Gateway**, which enforces it at runtime: request validation, authentication, throttling and versioning.
5. Server stubs and client SDKs are generated from the same specification.
6. Contract tests in CI verify the implementation never drifts from the contract.

API Gateway itself (API types, limits, authorizers, stages) is covered in [1.6 AWS Network Services](topic6.md#amazon-api-gateway) and in depth in [4.2 API Management and Service Mesh](../unit4/topic2.md).

### How the four patterns interlock

API-first defines _what_ services promise. Microservices define _how the system is decomposed_. Event-driven defines _how parts communicate without coupling_. Serverless defines _how compute is provisioned and billed_. Real systems combine all four.

<figure markdown="span">
    ![API gateway, microservices, event bus and serverless compute working together](../img/U1/interconnection.png){width="80%"}
    <figcaption>How the four patterns combine in a modern application</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI Generated (Google Gemini)</i></p>
</figure>

## Architecture Components

Each pattern is implemented by a small set of AWS services. Know the _role_ each one plays; the service details live in the linked topics.

| Pattern | Core AWS services | Role | Details |
|---|---|---|---|
| **Serverless** | Lambda, Fargate, DynamoDB on-demand, Aurora Serverless, Step Functions | Compute and data with no capacity management | [1.3](topic3.md#aws-lambda), [2.3](../unit2/topic3.md), [6.2](../unit6/topic2.md) |
| **Microservices** | ECS, EKS, Fargate, ECR, ALB, Cloud Map | Run, publish and discover independent services | [2.2](../unit2/topic2.md), [3.1](../unit3/topic1.md), [4.1](../unit4/topic1.md) |
| **Event-driven** | EventBridge, SNS, SQS, Kinesis, DynamoDB Streams | Route, fan out, buffer and stream events | [6.3](../unit6/topic3.md) |
| **API-first** | API Gateway, Cognito, CloudFront | Enforce the contract, authenticate callers, cache at the edge | [1.6](topic6.md#amazon-api-gateway), [4.2](../unit4/topic2.md) |
| **Cross-cutting** | IAM, CloudWatch, X-Ray, CloudFormation / SAM / CDK | Identity, observability, automation | [8.1](../unit8/topic1.md), [7.1](../unit7/topic1.md), [Unit 5](../unit5/overview.md) |

!!! note "ECS or EKS for microservices?"
    ECS is simpler and deeply AWS-integrated; EKS adds Kubernetes portability and its ecosystem at the cost of more operational complexity. ECS on Fargate is the pragmatic default for AWS-native microservices. The full comparison is in [3.1](../unit3/topic1.md).

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **Cloud-native** | Designed to exploit elastic, managed, distributed infrastructure: loosely coupled, resilient, observable, automated |
| **FaaS** | Function as a Service; event-triggered, provider-managed code execution (Lambda) |
| **Cold start** | Latency of creating and initialising a new Lambda execution environment |
| **Bounded context** | DDD term: the boundary within which one domain model applies; the natural seam for a microservice |
| **Distributed monolith** | Services that are physically separate but must be deployed or changed together |
| **Database per service** | Each service exclusively owns its data; others reach it only via its API or events |
| **Event / Command** | An event is a past-tense fact (`OrderPlaced`); a command is a directed request (`ChargeCard`) |
| **Choreography / Orchestration** | Coordination by reacting to events / coordination by a central workflow (Step Functions) |
| **Fan-out / Fan-in** | One event to many consumers / many results aggregated into one |
| **Dead-letter queue (DLQ)** | Queue that receives messages that repeatedly failed, isolating poison messages |
| **Idempotency** | Processing the same message twice gives the same result as processing it once |
| **Eventual consistency** | Copies of data converge over time; reads may briefly be stale |
| **At-least-once delivery** | The broker guarantees delivery but may duplicate |
| **OpenAPI** | Standard machine-readable format for REST API contracts |
| **Contract testing** | Automated check that an implementation matches its published contract |
| **Saga** | A distributed transaction run as local transactions with compensating actions |
| **Load levelling** | Using a queue to smooth bursts so consumers work at a sustainable rate |

## Configuration Options

Most configuration belongs to individual services and is covered in their own topics. The decisions below are the ones that change the _pattern_:

| Pattern | Decision | Options | Architectural implication |
|---|---|---|---|
| Serverless | Concurrency | Unreserved, reserved, provisioned | Reserved concurrency protects a small database; provisioned removes cold starts on latency-critical paths |
| Serverless | Invocation model | Synchronous, asynchronous, poll-based (event source mapping) | Decides who retries and where failures go |
| Microservices | Compute | Fargate, Fargate Spot, EC2 | Fargate for simplicity; EC2 for GPUs or dense steady load; Spot for interruptible workers |
| Microservices | Deployment type | Rolling, blue/green, canary | Blue/green gives instant rollback; canary limits the blast radius |
| Microservices | Scaling signal | CPU, request count per target, queue depth | Request count or queue depth usually tracks real demand better than CPU |
| Event-driven | Ordering | Standard or FIFO | FIFO gives ordering and deduplication at bounded throughput |
| Event-driven | Failure handling | DLQ and retry count on every queue, subscription and rule target | Poison messages are isolated instead of retried forever or lost |
| Event-driven | Visibility timeout | Longer than worst-case processing time | Too short and the same message is processed twice at once |
| API-first | Authorisation | Cognito, IAM, Lambda authorizer, JWT | Cognito for end users; IAM for service-to-service |
| API-first | Versioning | Path (`/v1`), header or stage | Path versioning is explicit and cache-friendly; never break an existing version |

Lambda settings: [1.3](topic3.md#aws-lambda). ECS settings: [2.2](../unit2/topic2.md). Messaging settings: [6.3](../unit6/topic3.md). API Gateway settings: [4.2](../unit4/topic2.md#api-gateway-configuration).

## AWS Best Practices

- **Operational Excellence:** define everything as code (SAM, CDK, CloudFormation, Terraform) and deploy small, frequent changes with automatic rollback.
- **Operational Excellence:** propagate a correlation ID on every hop so a request can be followed across services.
- **Security:** give each function, task or service its own IAM role, and authenticate at the edge as well as authorising between services.
- **Reliability:** make consumers idempotent and give every asynchronous target a DLQ with an alarm.
- **Reliability:** put timeouts, backoff with jitter and circuit breakers on every synchronous call.
- **Performance Efficiency:** match compute to the workload profile and filter events before they invoke compute.
- **Cost Optimization:** right-size continuously, with Savings Plans for the steady baseline, Spot for interruptible work and serverless for spiky load.
- **Sustainability:** scale-to-zero uses no compute when idle, and good bin-packing reduces the physical footprint.

## Monitoring and Observability

Distributed systems fail in ways no single component can see. Observability is a design requirement, covered in depth in [7.1](../unit7/topic1.md).

- **Metrics** answer _is something wrong?_ Alarm on business signals (orders per minute) as well as infrastructure.
- **Logs** answer _what happened?_ Emit structured JSON with a `correlationId` on every line.
- **Traces** (X-Ray) answer _which hop is slow or failing?_ Essential once a request crosses three or more services.

!!! warning "The asynchronous debugging problem"
    In event-driven systems the user request succeeds while the real work fails silently in a consumer seconds later. Always alarm on DLQ depth greater than zero and on `ApproximateAgeOfOldestMessage`, Lambda `Errors` and `Throttles`, and EventBridge `FailedInvocations`.

## Industry Use Cases

| Sector | Pattern combination | Application |
|---|---|---|
| **Media streaming** | Microservices + event-driven | Separate playback, recommendation and billing services; viewing events feed personalisation |
| **Ride-hailing** | Event-driven + microservices | Trip events drive pricing, ETA, payouts and fraud detection concurrently |
| **E-commerce** | All four | API-first storefront, a service per domain, serverless for flash sales, events for fulfilment |
| **Financial services** | Event-driven + saga | Event ledgers for audit; sagas for transfers with compensation |
| **Government services** | API-first + serverless | Published contracts for integration; serverless absorbs deadline spikes |
| **IoT** | Event-driven + serverless | Device telemetry routed through streams to functions and time-series stores |

## Advantages and Limitations

| Pattern | Advantages | Limitations |
|---|---|---|
| **Serverless** | No servers to manage; scales from zero automatically; idle costs nothing; multi-AZ by default; fast time to market | Cold starts; hard execution limits (15-minute maximum); stateless; database connection pressure; can cost more at constant high volume; highest lock-in; harder local testing |
| **Microservices** | Independent deployment; failure isolation; targeted scaling; right tool per service; clear team ownership | Distributed-systems complexity; operational overhead per service; no cross-service ACID transactions; harder end-to-end testing; wrong boundaries are expensive to fix |
| **Event-driven** | Extreme loose coupling; brokers buffer outages; load levelling; replay and audit trail | Hard to debug; eventual consistency confuses users; duplicates and ordering must be handled; implicit flow under choreography; schema changes can break unknown consumers |
| **API-first** | Parallel development; stable contracts allow internal refactoring; reuse across clients; generated docs and SDKs; a single governance point | Upfront design effort; governance overhead; a bad public API is hard to change; version proliferation without enforced deprecation |

## Summary

Cloud-native patterns exist because the cloud changed three assumptions: capacity became elastic and metered, failure became routine, and delivery speed became a competitive advantage. Each pattern answers one consequence of that shift, and real systems combine all four.

| Area | Key lesson |
|---|---|
| **Coupling and cohesion** | Low coupling between components, high cohesion within them. Event-driven removes temporal and location coupling |
| **Serverless** | Compute on demand, scale to zero, pay per use. Best for bursty work; trades cold starts, limits and portability for low operational burden |
| **Microservices** | Independently deployable services aligned to bounded contexts and teams. Fails badly with premature boundaries or a shared database |
| **Event-driven** | Immutable facts routed by a broker so producers never know consumers. Demands idempotency, DLQs and correlation IDs |
| **API-first** | Agree the contract before code; enforce it at the gateway; evolve it additively |
| **Choosing** | Patterns relocate complexity rather than remove it. Start simple, add distribution only where it solves a real problem |

**Next:** [Unit 2](../unit2/overview.md) puts the microservices and serverless patterns into practice with containers, Amazon ECR and Amazon ECS.

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit1.md#17-cloud-native-design-patterns) · [Interview questions](../interviewquestions/unit1.md#17-cloud-native-design-patterns).

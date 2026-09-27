# Microservices Design Principles on AWS

## Definition

**Microservices design principles** are the set of rules an architect applies when converting a business domain into a collection of independently deployable services on a cloud platform. On AWS, the principles are the same as anywhere else; what changes is that AWS supplies a specific, opinionated toolkit for each of them, and that the choice of tool has direct consequences for cost, latency, operational load, and how difficult a boundary is to move later.

Three principles dominate, and this chapter is organised around them.

| Principle | The question it answers | The failure it prevents | Primary AWS instruments |
|---|---|----|---|
| **Decomposition by business capability** | Where does one service end and the next begin? | Boundaries drawn on technical layers, producing a distributed monolith | Domain analysis, AWS Migration Hub Refactor Spaces, Application Discovery Service, App2Container |
| **Explicit, versioned contracts over the network** | How do services talk, and who owns the contract? | Implicit coupling through shared libraries, shared schemas, or undocumented behaviour | Amazon API Gateway, AWS AppSync (including Merged APIs), Amazon EventBridge, Amazon SQS, Amazon SNS, Amazon VPC Lattice |
| **Exclusive data ownership** | Who is allowed to write this row, and who may only ask? | A shared database that re-couples services while keeping the network hops | Amazon DynamoDB, Amazon Aurora and Aurora DSQL, Amazon RDS, Amazon DocumentDB, Amazon Neptune, Amazon Keyspaces, Amazon MemoryDB, Amazon ElastiCache, Amazon Timestream, Amazon OpenSearch Service |

A fourth principle  **design for failure**  is equally definitional but is treated separately in [chapter 4.3](topic3.md), because on AWS it has its own distinct toolkit.

Within an AWS architecture these principles operate at three different layers. Decomposition is an **analysis-time** activity that produces no AWS resources at all; it produces a boundary map. Communication is an **edge and east-west** concern realised in API Gateway, AppSync, ALB, VPC Lattice, EventBridge, SQS and SNS. Data ownership is a **persistence-tier** concern realised in the choice and configuration of purpose-built databases and in the pipelines that move data between them without granting one service write access to another's tables.

!!! note "The principles are ordered, and the order is not negotiable"

    Boundaries first, contracts second, data third  and then, only then, a compute platform. Teams that begin with "we will use EKS" and derive boundaries afterwards consistently produce services shaped like the deployment units they already had. The compute decision, treated at length in Units II and III, is the *last* decision in this sequence and the easiest to change; the data boundary is the *hardest* to change and therefore deserves the most analysis.

---

## Why This Service or Concept Exists

### The problem: decomposition is where microservices programmes fail

The industry has by now accumulated a large body of evidence about why microservices adoptions fail, and the failures cluster. They are almost never failures of container orchestration, which is a solved problem with two mature managed services. They are failures of boundary-drawing and data ownership, and they present in four recognisable shapes:

| Failure shape | What it looks like in production | Root cause |
|---|---|---|
| **The distributed monolith** | Twelve services, one release train, a shared library that must be bumped everywhere at once | Boundaries drawn without ownership; contracts implicit rather than explicit |
| **The shared database** | Three services reading one Aurora cluster; nobody can change a column | Data ownership never assigned, because assigning it required real domain work |
| **The chatty chain** | One user request fans into fourteen sequential internal calls; p99 is unusable | Over-decomposition on technical rather than capability lines |
| **The aggregation bottleneck** | One "API service" that every team must modify to expose a new field | A gateway or BFF owned by a central team, recreating the coordination cost microservices exist to remove |

Each of these is a design failure that a container platform cannot detect, prevent, or repair. This is why the syllabus places design principles in their own unit after the platform units: the platform is the easy half.

### What AWS changed

AWS did not invent microservices; Amazon's own service-oriented reorganisation predates the term by roughly a decade. What AWS supplies is a set of managed components that make each principle affordable to follow, where previously following them required building infrastructure.

| Principle | Cost of following it before managed cloud | Cost on AWS today |
|---|---|---|
| Database per service | Provision, patch, back up, monitor and licence N database servers; most teams refused, and shared one | Create N DynamoDB tables or Aurora Serverless clusters through IaC in minutes; pay per request or per ACU |
| Explicit API contracts | Build and operate an API gateway, an auth layer, a rate limiter, a schema registry | API Gateway or AppSync with authorisation, throttling, validation and caching as configuration |
| Federated GraphQL across teams | Operate Apollo Federation or a schema-stitching gateway with its own team | AppSync **Merged APIs**: each team owns a source API; AWS performs the merge and detects conflicts |
| Reliable event publication | Build an outbox poller and a broker; operate Kafka or RabbitMQ | DynamoDB Streams or Aurora CDC into EventBridge, SQS, or Kinesis, all managed |
| Cross-service reporting without shared tables | Build an ETL pipeline and a warehouse | Zero-ETL integrations into Amazon Redshift; S3 data lake with Athena and Glue |
| Incremental extraction from a monolith | Build and operate a routing layer with per-route traffic shifting | API Gateway or an ALB in front of the monolith with per-path routes; **Refactor Spaces** orchestrated this as one resource, though it is closed to new customers since November 2025 |
| Purpose-built persistence | One relational engine for every workload, because operating a second was prohibitive | Eleven managed database engines, each fitting a distinct access pattern |

!!! warning "Managed services lower the cost of following a principle; they do not enforce it"

    AWS will happily let you point four ECS services at one Aurora cluster, publish an event that no consumer can parse, or build a single AppSync API that one team owns and eleven teams queue to modify. Every anti-pattern listed above is fully supported by the platform and costs nothing extra. The discipline remains the architect's responsibility, and this is the central lesson of Unit IV.

---

## Core Concepts

### The decomposition problem, stated precisely

Decomposition is the act of partitioning a domain into subsets such that:

1. **Cohesion is high inside a subset**  things that change together are in the same service.
2. **Coupling is low between subsets**  a change inside one service rarely forces a change in another.
3. **Each subset has an owner**  exactly one team is accountable for it.
4. **Each subset owns its data exclusively**  no other service writes, and ideally none reads, its store.
5. **The cognitive load of a subset fits one team**  the team can hold it in their heads and be woken for it.

These five criteria frequently conflict. Maximising cohesion pushes towards fewer, larger services; minimising team cognitive load pushes towards more, smaller ones. Decomposition strategies are heuristics for resolving that conflict, and different heuristics produce different  and all defensible  partitions of the same domain.

### Strategy one: decomposition by business capability

A **business capability** is something the business does, expressed in the business's own language, independently of how it is currently implemented: *accept payment*, *manage inventory*, *arrange shipment*, *price a product*, *underwrite a policy*. Capabilities are stable over decades; implementations are not. Decomposing by capability produces services whose names a non-technical executive would recognise, and that is a good sign.

The method is straightforward and is usually done as a workshop rather than by an individual:

1. List what the business does, from the organisation's own capability map if it has one, or from the top-level menu of the existing application if it does not.
2. Group activities into capabilities at a consistent level of granularity  the test is that all your capabilities feel like siblings.
3. For each capability, identify the data it must own to be autonomous.
4. Identify which capabilities need data from which others, and record whether that need is on a synchronous request path or can be satisfied asynchronously.
5. Assign each capability to exactly one team; where two teams both claim one, the capability is probably two.

| Capability | Owns | Needs from others | Interaction style |
|---|---|---|---|
| Catalogue | Products, categories, attributes, media references | Nothing | Publishes `ProductUpdated` |
| Pricing | Price lists, rules, currency, tax logic | Product identity and category | Subscribes to `ProductUpdated`; keeps a local projection |
| Inventory | Stock levels, reservations, warehouses | Product identity | Subscribes to `ProductUpdated` |
| Ordering | Orders, order lines, order state | Product summary, price at time of order, stock availability | Synchronous availability check; price and product snapshot copied into the order |
| Fulfilment | Shipments, carriers, tracking | Order contents and destination | Subscribes to `OrderConfirmed` |
| Payments | Transactions, refunds, payment methods | Order total and identifier | Subscribes to `OrderConfirmed`; publishes `PaymentSettled` |

Notice the fourth row. Ordering **copies** the product summary and price into the order at the moment of ordering, rather than referring to the catalogue for them later. This is not denormalisation for performance; it is correctness. The price on an order is the price that was agreed, not the price that happens to be current when someone opens the order six months later. Recognising that a copied value is semantically different from a reference is one of the most useful skills in decomposition, and it removes a very large number of apparent cross-service dependencies.

### Strategy two: decomposition by subdomain and bounded context

Domain-driven design supplies the sharper instrument. A **subdomain** is a part of the problem space; a **bounded context** is a boundary in the solution space inside which a model and its vocabulary are internally consistent. Subdomains come in three kinds, and the kind determines how much engineering investment each deserves:

| Subdomain type | Definition | Investment | AWS implication |
|---|---|---|---|
| **Core** | What differentiates this business from competitors | Highest; your best engineers, custom build | Own service, own store, own team, full observability |
| **Supporting** | Necessary, specific to you, but not differentiating | Moderate; build simply | Own service, but favour managed and serverless to minimise operational load |
| **Generic** | Necessary and identical across businesses  authentication, notifications, payments processing | Lowest; buy or use a managed service | Amazon Cognito, Amazon SES or SNS, a payment provider; do not build |

This classification saves more engineering time than any other technique in this chapter. Teams routinely build a bespoke user-identity service  a generic subdomain  and under-invest in the pricing engine that is their actual competitive advantage. Amazon Cognito exists precisely so that identity does not consume a core team.

The relationships **between** contexts also have names, and naming them clarifies who absorbs the cost of change:

| Relationship | Meaning | When to use it |
|---|---|---|
| **Partnership** | Two contexts succeed or fail together; teams coordinate | Rare and expensive; a sign the boundary may be wrong |
| **Customer–supplier** | Downstream's needs influence upstream's roadmap | The normal healthy relationship between internal teams |
| **Conformist** | Downstream accepts upstream's model as-is | Acceptable for a stable, well-designed upstream; dangerous for a legacy one |
| **Anti-corruption layer** | Downstream translates upstream's model into its own | The correct treatment of any legacy system or third-party API |
| **Open host service with published language** | Upstream publishes a stable, general-purpose contract | What every service exposed to more than two consumers should become |
| **Separate ways** | Contexts do not integrate; duplication is accepted | Correct more often than teams expect; duplication is cheaper than coupling |

!!! tip "Prefer duplication to coupling across a boundary"

    Inside a service, duplication is a defect to be refactored away. Across a service boundary, duplication is frequently the correct answer, because the alternative  a shared library or a shared table  reintroduces exactly the coupling the boundary exists to remove. If the ordering service and the fulfilment service both have a small `Address` type with slightly different validation rules, that is not technical debt; that is two bounded contexts with different requirements, correctly separated.

### Event storming as the discovery technique

Event storming converts tacit domain knowledge into a boundary map in a day or two. It runs as a facilitated workshop with domain experts and engineers in the same room, and it proceeds in passes:

```mermaid
flowchart LR
    A["Pass 1: Domain events on a timeline<br/>past tense: OrderPlaced, PaymentCaptured"] --> B["Pass 2: Commands that cause them<br/>PlaceOrder, CapturePayment"]
    B --> C["Pass 3: Actors and policies<br/>who issues the command, what rule triggers it"]
    C --> D["Pass 4: Aggregates<br/>the consistency boundary each command acts on"]
    D --> E["Pass 5: Cluster aggregates into<br/>bounded contexts"]
    E --> F["Candidate services with<br/>explicit data ownership"]
```

Two outputs matter most. First, the **aggregate**  the smallest set of data that must be transactionally consistent  is the unit that cannot be split across services, because splitting it means giving up a local transaction. Second, the **pivotal events** where the language changes are the strongest boundary candidates: the moment a basket becomes an order, or an order becomes a shipment, is almost always a context boundary.

### Strategy three: decomposition by volatility

Code that changes at very different rates should not share a deployment unit. If a promotions engine changes weekly and a tax calculator changes twice a year under legislative pressure, coupling them means the tax calculator is redeployed fifty times a year for no reason, each redeployment carrying non-zero risk to a component whose correctness is legally significant.

This heuristic has the advantage of being **measurable**. Commit history gives you change frequency per file, and co-change analysis  which files change in the same commit  gives you empirical cohesion. A simple analysis over a monolith's Git history:

```bash
# Change frequency per file over the last two years.
git log --since='2 years ago' --name-only --pretty=format: \
  | grep -v '^$' | sort | uniq -c | sort -rn | head -40

# Co-change: pairs of files that change in the same commit, ranked.
git log --since='2 years ago' --name-only --pretty=format:'---%H' \
  | awk '/^---/{c++} !/^---/ && NF {print c" "$0}' \
  | sort -k2 | awk '{a[$1]=a[$1]" "$2} END {for (k in a) print a[k]}' \
  | tr ' ' '\n' | paste -d, - - | sort | uniq -c | sort -rn | head -40
```

Empirical co-change clusters are frequently a better guide than an architect's intuition, because they reflect how the system actually evolves rather than how it was intended to.

### Strategy four: decomposition by scaling and availability profile

Two capabilities with radically different load shapes or availability requirements are candidates for separation even when their domains are adjacent, because a shared deployment unit forces a single capacity and availability decision on both.

| Signal | Example | Consequence of not separating |
|---|---|---|
| Different peak-to-trough ratio | Checkout peaks 40× on one Friday; review ingestion is flat | Provision the whole application for checkout peak |
| Different availability target | Playback authorisation must never fail; recommendations may degrade | The lower-value component's failures take down the higher-value one |
| Different latency budget | A 10 ms entitlement check alongside a 3 s report generation | The report's thread pool and garbage collection profile harm the check's tail latency |
| Different resource dimension | Memory-bound image processing alongside I/O-bound API serving | Instance type must satisfy both, so it over-provisions one |
| Different failure semantics | Fail-closed payment versus fail-open personalisation | A single process cannot have two failure policies |

!!! warning "This heuristic over-splits if used alone"

    Scaling profile is a *supporting* argument for a boundary that domain analysis already suggests, not a sufficient reason on its own. A service extracted purely because it is CPU-heavy, with no domain coherence, becomes a "technical layer" service  the anti-pattern this chapter warns about most  and will be called synchronously by everything.

### Strategy five: decomposition by compliance and data classification

Where regulated data lives determines audit scope, and audit scope has a direct, recurring monetary cost. Data classified as cardholder data, protected health information, or personal data under a regime with data-residency requirements should be isolated in a service whose store, network and identity are separable from the rest.

On AWS the strongest available boundary is the **account**, not the VPC and certainly not the Kubernetes namespace, because an account boundary is trivially demonstrable to an auditor and is enforced by IAM at the platform level rather than by configuration you must prove. The standard topology is an AWS Organizations organisational unit for in-scope workloads, governed by Service Control Policies, with cross-account communication restricted to a narrow asynchronous interface over an EventBridge event bus or a resource-shared VPC Lattice service network.

### Strategy six: decomposition around the aggregate and the transaction

The hardest practical constraint on decomposition is that **you cannot split an aggregate across services without giving up its transaction**. If placing an order must atomically decrement stock and create an order record, then either those live in one service, or you accept a saga with compensations and the eventual consistency that entails.

The technique is to work backwards from the transactions the business genuinely requires to be atomic:

1. List the operations that must be all-or-nothing in the business's own terms.
2. For each, list the data it touches.
3. Data touched by the same mandatory-atomic operation belongs in the same service, unless the business will accept a compensating undo.
4. Ask the business explicitly: "if the second half fails, is it acceptable to undo the first half a few seconds later, and what does the customer see in between?" The answer is often yes, and the times it is no are precisely the boundaries you must not draw.

This conversation, held before the boundary is drawn, is worth more than any amount of subsequent saga engineering.

### Service granularity and the anti-patterns

| Anti-pattern | Symptom | Correction |
|---|---|---|
| **Entity service** | A "Customer service" exposing only CRUD, called by everyone | Move behaviour to the data; a service should own a capability, not a table |
| **Technical-layer service** | "Validation service", "data access service" | Decompose vertically by capability, not horizontally by layer |
| **Nano-service** | Two hundred services for forty engineers; more pipelines than features | Merge; the fixed per-service cost dominates |
| **God service** | One service that everything calls and that owns most of the data | The monolith survived the migration; re-run the decomposition on it |
| **Chatty chain** | Fourteen sequential internal calls per user request | Collapse services, copy reference data, or move to events |
| **Shared database** | Two services on one schema | Assign ownership; expose an API or publish events |
| **Central aggregation layer owned by one team** | Every team queues to add a field to "the API" | Federate: AppSync Merged APIs, or per-team API Gateway stages behind one custom domain |

!!! danger "The single most common decomposition error"

    Decomposing along the layers of the existing codebase  controllers, services, repositories  because those boundaries are already visible in the code. The result is a set of services that must all be deployed together for any feature to work, connected by synchronous calls, sharing one database. That is a distributed monolith: it pays the full network, operational and failure-mode cost of microservices and delivers none of the independence. Boundaries must be drawn in the **problem** space and only then projected onto code.

### Inter-service communication: the taxonomy

Every interaction between two services sits at one point on two independent axes, and naming the point tells you which AWS service implements it.

| | **One-to-one** | **One-to-many** |
|---|---|---|
| **Synchronous** | Request/response: HTTP through ALB, API Gateway, VPC Lattice, or ECS Service Connect; GraphQL query or mutation through AppSync | Rare and usually a mistake: scatter-gather across many services on a request path multiplies failure probability |
| **Asynchronous** | Command message on an Amazon SQS queue; asynchronous Lambda invocation | Event publication to Amazon EventBridge or Amazon SNS; a stream on Amazon Kinesis; AppSync subscriptions to clients |

Two further distinctions matter more than students expect:

**Commands versus events.** A *command* names a recipient and requests an action: `ReserveInventory`. An *event* names nothing but a fact that has already happened: `OrderPlaced`. Commands couple the sender to the receiver; events do not. A system whose "events" are named `SendEmail` or `CreateShipment` is publishing commands with an event's syntax, and it has all the coupling of a direct call with none of the clarity. The test is the tense and the knowledge: an event is past tense and its publisher does not know or care who consumes it.

**Orchestration versus choreography.** Orchestration puts a coordinator in charge of a multi-service process  on AWS, Step Functions  giving one inspectable artefact, explicit error handling, and a visible execution history, at the cost of the coordinator knowing about all participants. Choreography has each service react to events with no coordinator, giving maximum decoupling at the cost that the business process exists nowhere as a single thing and can only be reconstructed from traces. The practical rule: **orchestrate processes that a business person would draw as a flowchart and that need compensation; choreograph reactions that are genuinely independent side effects.**

```mermaid
flowchart TD
    A["Does the caller need the answer<br/>before it can respond to its own caller?"] -->|"no"| B["Asynchronous"]
    A -->|"yes"| C["Does more than one service<br/>need to know?"]
    C -->|"no"| D["Synchronous request/response"]
    C -->|"yes on the request path"| E["Reconsider: scatter-gather<br/>multiplies failure probability"]
    B --> F["Is a specific service<br/>being asked to act?"]
    F -->|"yes, one recipient"| G["Command on Amazon SQS"]
    F -->|"no, announcing a fact"| H["Event on Amazon EventBridge"]
    D --> I["Public or partner client?"]
    I -->|"yes"| J["Amazon API Gateway"]
    I -->|"no, internal east-west"| K["ALB, VPC Lattice,<br/>or ECS Service Connect"]
    H --> L["Does a consumer need<br/>replay and strict ordering?"]
    L -->|"yes"| M["Amazon Kinesis Data Streams"]
    L -->|"no"| N["EventBridge to per-consumer SQS queues"]
```

### AWS AppSync and the GraphQL model

**GraphQL** is a query language and runtime in which the client specifies exactly which fields it needs and the server resolves each field independently. Three properties make it structurally interesting for microservices, and one property makes it dangerous.

The three useful properties:

1. **The client declares its data shape.** A mobile screen needing five pieces of data from four services issues one request rather than five, which on a high-latency mobile network is the difference between a responsive screen and a slow one.
2. **Fields resolve independently and in parallel.** A field backed by a slow service does not serialise behind a field backed by a fast one, and a nullable field whose resolver fails returns `null` with an error entry while the rest of the response succeeds  partial success is native to the protocol rather than something you must engineer.
3. **The schema is a contract that can be composed.** Several teams can each own part of one schema, which is what makes federation possible.

The dangerous property: **one schema is one shared artefact**. If a central team owns it, every product team queues behind that team to expose a field, and the API layer becomes precisely the coordination bottleneck microservices exist to remove. The answer on AWS is Merged APIs, described below, and it is the single most important AppSync feature for this syllabus.

**AWS AppSync** is the managed GraphQL service: AWS operates the GraphQL engine, the WebSocket infrastructure for subscriptions, the authorisation layer, the cache and the schema merge. You supply a schema, data sources, and resolvers.

### AppSync core vocabulary

| Term | Meaning |
|---|---|
| **Schema** | The SDL document defining types, and the `Query`, `Mutation` and `Subscription` root types |
| **Data source** | A backend AppSync can call: Lambda, DynamoDB, Aurora through the RDS Data API, Amazon OpenSearch, an HTTP endpoint, Amazon EventBridge, Amazon Bedrock, or `NONE` for a local resolver |
| **Resolver** | The code mapping one schema field to one or more data-source operations |
| **Unit resolver** | A resolver attached to a single data source |
| **Pipeline resolver** | An ordered series of **functions**, each attached to a data source, sharing a `$ctx.stash`  the mechanism for authorisation-then-fetch, or fan-out to several services for one field |
| **Resolver runtime** | **APPSYNC_JS**, a JavaScript runtime with `request` and `response` handlers, or **VTL**, the older Velocity template language. New work uses APPSYNC_JS |
| **Direct Lambda resolver** | A resolver with no mapping template; the whole `context` object is passed to the function and its return value is used as-is |
| **Subscription** | A field on the `Subscription` type that clients open over WebSocket; `@aws_subscribe` binds it to one or more mutations |
| **Merged API** | An AppSync API whose schema is composed from several **source APIs**, each owned by a different team and account; AWS merges them and reports type conflicts |
| **Source API association** | The link between a Merged API and one source API, in auto-merge or manual-merge mode |
| **AppSync Events** | The non-GraphQL side of AppSync: serverless WebSocket pub/sub over **channel namespaces**, for broadcasting to connected clients without defining a schema |
| **Caching** | A managed per-API or per-resolver cache with a TTL and a configurable cache key |
| **Authorisation mode** | API key, AWS IAM, Amazon Cognito user pools, OpenID Connect, or a Lambda authoriser; one primary plus up to a number of additional modes, selectable per field with directives |
| **Conflict detection** | Optimistic-concurrency and conflict-resolution configuration for offline-capable clients synchronising through AppSync |

### Merged APIs: federation without a central team

This is the mechanism that reconciles GraphQL's single schema with microservices' team autonomy, and it deserves to be understood precisely.

```mermaid
flowchart TD
    C["Client: one endpoint, one schema"] --> M["AppSync Merged API"]
    M -->|"source API association"| S1["Catalogue source API<br/>owned by Catalogue team<br/>account A"]
    M -->|"source API association"| S2["Orders source API<br/>owned by Orders team<br/>account B"]
    M -->|"source API association"| S3["Loyalty source API<br/>owned by Loyalty team<br/>account C"]
    S1 --> D1["DynamoDB catalogue table"]
    S2 --> L2["Lambda resolver to Orders service"]
    S3 --> H3["HTTP data source to Loyalty ALB"]
    M -.->|"conflict detection at merge time"| X["Merge fails loudly if two source APIs<br/>define the same type incompatibly"]
```

Each team owns a complete, independently deployable AppSync API with its own schema, resolvers, data sources and pipeline. The Merged API associates those source APIs and presents one endpoint to clients. Critically:

- A team ships a new field by deploying **their own** source API. With auto-merge, the merged schema updates without any action by a central team and without a merged-API deployment. This is the property that preserves independent deployability.
- Conflicts  two source APIs defining the same type with incompatible fields  are detected at merge time and reported, rather than silently resolved.
- Source APIs can live in **different AWS accounts**, associated through cross-account IAM, so the ownership boundary can be an account boundary.
- Authorisation modes are configured on the Merged API; source APIs keep their own for direct access, which is useful for a team's own testing.

The alternative, a single AppSync API that all teams modify, works and is simpler for a small organisation. The distinction is exactly the one that governs this whole unit: with one team, a shared artefact is fine; with several teams whose release cadences conflict, a shared artefact is the bottleneck.

!!! tip "How to explain the AppSync-versus-API-Gateway choice in one sentence"

    Choose **API Gateway** when the contract is a set of operations you publish to consumers you do not control  partners, third-party developers, other organisations  and you need per-consumer keys, usage plans and request validation. Choose **AppSync** when the consumers are your own clients, the pain is over-fetching and round trips across many services, and you want the schema to be a composable contract several teams can own. Choose **both** in a large estate: they are not competitors, and a common topology is API Gateway for the public partner API and AppSync for the first-party web and mobile clients.

### Data management: the ownership rule and its consequences

The rule is one sentence: **each service exclusively owns its data store; no other service reads or writes it directly.** The consequences are four, and every one of them costs something.

| Consequence | What you lose | What you use instead on AWS |
|---|---|---|
| No cross-service joins | A single SQL statement joining orders and products | API composition; a CQRS read model; a data-lake copy in S3 queried by Athena; a zero-ETL integration into Redshift |
| No cross-service ACID transactions | `BEGIN … COMMIT` across two services | A saga with compensations, orchestrated by Step Functions |
| No shared referential integrity | A foreign key preventing an order referencing a deleted product | Soft deletes, tombstone events, reconciliation jobs, and accepting that a reference may dangle briefly |
| N stores to operate | One database to back up, patch and monitor | N managed stores, which is why serverless options  DynamoDB on-demand, Aurora Serverless v2, Aurora DSQL  matter so much at this granularity |

!!! danger "The read that becomes a write dependency"

    Teams frequently negotiate a compromise: "the reporting service will only *read* the orders table; it will never write." Within a quarter, the orders team cannot rename a column, add a NOT NULL constraint, change the capacity mode, or migrate the table, because an unknown number of readers depend on its physical schema. A read dependency on a physical schema is every bit as coupling as a write dependency; it is simply less obvious, which makes it worse. The schema has become an unversioned public API owned by nobody.

### Choosing among AWS purpose-built databases

The choice is made from the **access pattern**, and the single most common error is choosing from familiarity instead.

| Store | Data model | Choose it when | Avoid it when |
|---|---|---|---|
| **Amazon DynamoDB** | Key-value and document | Access patterns are known and few; you need single-digit-millisecond reads at any scale; you want serverless elasticity matching a service's own | Queries are ad hoc or analytical; you need joins; the access pattern is genuinely unknown |
| **Amazon Aurora (MySQL/PostgreSQL)** | Relational | You need transactions, joins, constraints, and an ad-hoc query capability; the team knows SQL | Write throughput exceeds a single writer; you need multi-region active-active writes |
| **Amazon Aurora Serverless v2** | Relational | The above, with variable or intermittent load; per-service databases that must scale to a low floor | Steady, high, predictable load where provisioned instances cost less |
| **Amazon Aurora DSQL** | Distributed relational, PostgreSQL-compatible | You need active-active multi-region writes with strong consistency and no failover step, and can accept its feature subset | You depend on PostgreSQL features it does not support, or need a single-region low-cost store |
| **Amazon RDS** | Relational, several engines | You need a specific engine, version or extension Aurora does not offer; lift-and-shift of an existing schema | You want Aurora's storage-layer replication and failover characteristics |
| **Amazon DocumentDB** | Document, MongoDB-compatible | Existing MongoDB application or genuinely document-shaped aggregates with rich queries | A greenfield key-value pattern that DynamoDB serves more cheaply and elastically |
| **Amazon Neptune** | Graph | Relationships are the query  recommendations, fraud rings, entitlement graphs, knowledge graphs | Relationships are shallow; two joins do not justify a graph engine |
| **Amazon Keyspaces** | Wide-column, Cassandra-compatible | Existing Cassandra workload; very high write throughput with a wide-column model | Greenfield, where DynamoDB is usually the simpler AWS-native answer |
| **Amazon MemoryDB** | In-memory, Redis/Valkey-compatible, durable | You need in-memory speed **as the primary store** with multi-AZ durability | You need a cache in front of a durable store; use ElastiCache |
| **Amazon ElastiCache** | In-memory cache | Caching, session state, rate-limit counters, distributed locks | Data you cannot afford to lose |
| **Amazon Timestream** | Time series | Telemetry, metrics, IoT readings with time-window queries and retention tiering | General-purpose workloads |
| **Amazon OpenSearch Service** | Search and analytics | Full-text search, faceting, log analytics, aggregations over semi-structured data | As a system of record; treat it as a derived read model |
| **Amazon S3 with Athena and Glue** | Object storage and query | The analytical copy of everything; the replacement for cross-service joins in reporting | Operational, low-latency access |
| **Amazon Redshift** | Columnar warehouse | Cross-service analytics at scale, fed by zero-ETL integrations | Operational transactions |

!!! note "Polyglot persistence is permitted, not required"

    Database-per-service *allows* each service to choose a fitting engine. It does not oblige you to use eleven. Every additional engine is a set of operational skills, a backup and restore procedure, a monitoring configuration and an upgrade path. A sensible default for a mid-sized estate is two: DynamoDB for services with known access patterns and Aurora Serverless v2 for services needing relational flexibility, adding a third only when a specific access pattern genuinely demands it.

### The cross-service data patterns

**Transactional outbox.** Writing to your database and publishing an event are two operations that cannot be made atomic. The outbox makes them one local transaction plus one asynchronous publication.

```mermaid
sequenceDiagram
    participant APP as "Orders service"
    participant DB as "Aurora PostgreSQL"
    participant CDC as "Poller or DMS change data capture"
    participant EB as "Amazon EventBridge"
    participant SQS as "Consumer SQS queue"
    APP->>DB: "BEGIN"
    APP->>DB: "INSERT INTO orders (...)"
    APP->>DB: "INSERT INTO outbox (event_type, payload, trace_id)"
    APP->>DB: "COMMIT"
    Note over APP,DB: One local transaction. Either both rows exist or neither does.
    CDC->>DB: "read new outbox rows"
    CDC->>EB: "PutEvents"
    EB->>SQS: "rule target delivers"
    CDC->>DB: "mark row published"
    Note over CDC,SQS: At-least-once delivery. Consumers must be idempotent.
```

On DynamoDB the outbox is even simpler, because **DynamoDB Streams** gives change data capture for free: write the business item, and a Lambda triggered by the stream publishes the event. The stream record *is* the outbox, and there is no poller to operate. This is one of the strongest practical arguments for DynamoDB in an event-driven microservices estate.

**Saga with compensating transactions.** Treated fully in [chapter 4.3](topic3.md); the data-management point here is that the saga is what replaces the transaction you gave up when you split the aggregate, and that its compensations are business operations, not rollbacks.

**CQRS read models.** Because cross-service joins are gone, a view assembling data from several services is built by a projector consuming events into a purpose-built store  DynamoDB for a key-shaped view, OpenSearch for a searchable one. The read model is eventually consistent by construction, and it must be rebuildable from the event history, or a projector bug becomes permanent data corruption.

**Reference-data replication.** When service B needs a small, slowly changing subset of service A's data on a hot path, B subscribes to A's events and keeps a local projection of exactly the fields it needs. This removes a synchronous dependency entirely and is almost always better than caching A's API responses, because it survives A being completely unavailable.

**Zero-ETL and the analytics escape hatch.** The reporting requirement that used to be a join is served by continuously replicating each service's data into Amazon Redshift through zero-ETL integrations, or into S3 as an analytical copy queried by Athena. This is the correct answer to "but finance needs a report across all six services" and it does not require anyone to read anyone else's operational tables.

### Consistency, stated honestly

| Model | Where you get it on AWS | What it costs |
|---|---|---|
| Strong consistency within one aggregate | A single DynamoDB item; a single Aurora transaction | Nothing; this is why aggregates must not be split |
| Strong consistency across items in one DynamoDB table or account | `TransactWriteItems` | Bounded item count per transaction, roughly double the write capacity, and no cross-service reach |
| Strong consistency across regions | Aurora DSQL | A feature subset relative to PostgreSQL, and a newer operational surface |
| Read-your-writes | DynamoDB strongly consistent reads; Aurora reads from the writer | Higher cost or lost read-replica offload |
| Eventual consistency | Everything cross-service | A stale window, duplicate submissions, support tickets, and reconciliation jobs you must build and staff |

!!! warning "Eventual consistency is a business decision that must be made by the business"

    "The customer may not see their order in their history for up to two seconds" is either acceptable or it is not, and the architect's job is to ask rather than to assume. When the answer is "not acceptable", the correct response is usually not more engineering but a different boundary: the data belongs in the same service. Budget explicitly for reconciliation jobs that can answer "are these two services in agreement?", because in a system without foreign keys, that question is asked eventually and there must be a way to answer it.

---

## AWS Service Deep Dive

!!! warning "On numbers and quotas"

    Quotas stated below are representative as of 2026. Most are **soft** and adjustable through AWS Service Quotas; a minority are hard. They vary by Region and account. Verify in the Service Quotas console for the account and Region you are designing in. Pricing is described as **dimensions** and **relative positions** only; model actual cost in the AWS Pricing Calculator.

### AWS AppSync

**Purpose.** Provide a managed GraphQL and event API layer that resolves each field of a client request against the owning backend, in parallel, with authorisation, caching, real-time subscriptions and cross-team schema federation supplied by the platform.

**Architecture.** AppSync is fully managed and regional. A request arrives at the AppSync endpoint over HTTPS (queries and mutations) or WebSocket (subscriptions). AppSync parses and validates the query against the schema, evaluates the authorisation mode and any field-level directives, then executes the resolver graph: fields at the same depth resolve concurrently, and nested fields resolve after their parent. Each resolver runs either as an APPSYNC_JS function inside AppSync's own sandboxed JavaScript runtime, or as a VTL template, or is passed straight through to a Lambda function as a direct Lambda resolver. Data-source calls are made using an IAM service role that AppSync assumes, so AppSync itself is the principal that talks to DynamoDB, Aurora, OpenSearch or an HTTP endpoint. Subscription delivery runs over a managed WebSocket fleet: a mutation's response is evaluated against every registered subscription's filter and pushed to matching connections.

**Important features.**

| Feature | What it does | Why it matters architecturally |
|---|---|---|
| **Merged APIs** | Compose one schema from several independently owned source APIs, across accounts | The federation mechanism that keeps GraphQL compatible with team autonomy |
| **Pipeline resolvers** | Chain functions over several data sources for one field, sharing a stash | Authorise-then-fetch, and fan-out to several services for a single field, without a Lambda |
| **APPSYNC_JS runtime** | Write resolvers in a JavaScript subset, no Lambda invocation | Removes cold starts and per-invocation cost from simple resolvers |
| **Direct Lambda resolvers** | Pass the whole context to a function, no mapping template | The simplest path when the backend is a service behind a Lambda |
| **Data sources** | DynamoDB, Lambda, RDS Data API, OpenSearch, HTTP, EventBridge, Bedrock, NONE | AppSync can call a DynamoDB table or an internal ALB directly, with no compute in between |
| **Subscriptions** | Managed WebSocket push on mutation, with server-side filtering | Real-time UI without operating a WebSocket fleet |
| **Enhanced subscription filtering** | Filter server-side on fields the client specifies | Prevents fanning irrelevant messages to every connection |
| **AppSync Events** | Channel-namespace pub/sub over WebSocket with no GraphQL schema | Broadcast and presence use cases that do not need a query language |
| **Caching** | Per-API or per-resolver cache with TTL and a configurable key | Absorbs read load before it reaches a service |
| **Five authorisation modes** | API key, IAM, Cognito user pools, OIDC, Lambda authoriser; multiple modes per API, selectable per field | One API can serve an authenticated first-party client and an IAM-signed internal caller |
| **Private APIs** | An AppSync endpoint reachable only through a VPC interface endpoint | Internal APIs that must not be internet-reachable |
| **WAF integration** | Attach an AWS WAF web ACL to the API | Rate-based rules and managed rule sets at the GraphQL edge |
| **Conflict detection and sync** | Optimistic concurrency with configurable resolution for offline clients | Mobile clients that write while disconnected |

**Limitations.** GraphQL is not a good fit for bulk data transfer or for file upload; use S3 presigned URLs and return the URL through the API. Query complexity is a real operational risk: a deeply nested query can fan out into hundreds of resolver executions, and depth and complexity limits must be configured deliberately. The APPSYNC_JS runtime is a **subset** of JavaScript  no `async`/`await`, no arbitrary npm modules, limited built-ins  so non-trivial logic belongs in Lambda. Response payload size, resolver execution time and subscription payload size are all capped. There is no built-in usage-plan or API-key-per-consumer metering comparable to API Gateway's, so monetised partner APIs are a poor fit. Caching is per-resolver with a TTL and no fine-grained invalidation API, so it suits reference data rather than rapidly changing state.

**Pricing model.** Charged per **query and mutation operation**, per **subscription message delivered**, and per **connection-minute** for subscriptions; the optional cache is charged per instance-hour by cache size. There is no charge for the merge in a Merged API, but operations against the Merged API are billed. The architectural implication is that a chatty client issuing many small queries costs more than one issuing a single well-shaped query  which is precisely the behaviour GraphQL encourages  and that long-lived subscriptions from many idle clients are a real, easily overlooked line item.

**Performance characteristics.** Field resolution is concurrent at the same depth, so a query touching four services has roughly the latency of the slowest one rather than their sum. This is the strongest performance argument for GraphQL in a microservices estate. The counterweight is that a badly shaped nested query serialises: a list of 100 orders each resolving a customer field produces 100 sequential-per-item resolver executions  the **N+1 problem**  which must be solved by batching. AppSync supports batch invocation for Lambda data sources (`BatchInvoke`) and `BatchGetItem` for DynamoDB; using them is not optional at scale.

**Scaling behaviour.** AppSync scales automatically with request volume; you provision nothing except optionally the cache. The scaling constraint moves to your data sources: a Lambda resolver has a concurrency limit, a DynamoDB table has throughput settings, and an Aurora cluster has connections. The most common AppSync scaling incident is not AppSync throttling but the Aurora connection pool behind an RDS Data API resolver.

**Availability.** Regional, multi-AZ, managed by AWS. For multi-Region, front two regional APIs with Route 53 latency or failover routing and accept that subscriptions do not fail over transparently  clients must reconnect.

**Security features.** Five authorisation modes with per-field directives (`@aws_auth`, `@aws_cognito_user_pools`, `@aws_iam`, `@aws_oidc`, `@aws_api_key`), so a single type can expose public fields and restricted fields; AWS WAF attachment; private APIs over VPC endpoints; a service role per data source following least privilege; field-level authorisation implemented in a pipeline function's first step; CloudWatch request-level logging with configurable verbosity, and X-Ray tracing.

**Service limits (representative, mostly soft).** Resolvers per API, types per schema and API count per region are in the hundreds to low thousands. Query depth and resolver count per request are configurable limits you should set. Subscription payload size, connection duration, and concurrent connections per API all have ceilings. Source APIs per Merged API is a specific quota worth checking before designing a large federation.

**Common configurations.** APPSYNC_JS resolvers with direct DynamoDB data sources for owned data; direct Lambda resolvers for fields backed by a service; pipeline resolvers where authorisation must precede the fetch; Cognito user pools as the primary authorisation mode with IAM as an additional mode for internal callers; WAF attached with a rate-based rule; X-Ray enabled; CloudWatch logs at `ERROR` in production and `ALL` in development; a Merged API in a platform account associating one source API per product team's account.

### Amazon API Gateway in the decomposition context

API Gateway is treated in depth in [chapter 4.2](topic2.md). For decomposition purposes only three facts matter here. First, it offers **three API types**  REST, HTTP and WebSocket  with different feature sets and per-request costs, and the REST type is the one carrying usage plans, API keys, request validation and per-method caching. Second, its **per-consumer usage plans and API keys** are the feature that makes it the correct front door for partner and third-party APIs, which AppSync does not replicate. Third, a **custom domain with base-path mappings** allows several independently deployed APIs, owned by different teams, to appear under one hostname  the REST equivalent of a Merged API and the correct way to avoid a single central API artefact.

### AWS Migration Hub Refactor Spaces

**Purpose.** Provision and manage the infrastructure required to run a strangler-fig decomposition incrementally: the routing layer, the network path between the monolith and the new services, and the account structure, created and maintained as one AWS resource rather than assembled by hand.

**Architecture.** A Refactor Spaces **environment** contains an **application**, which orchestrates an Amazon API Gateway, an API Gateway VPC link, a Network Load Balancer, an AWS Transit Gateway attachment and the AWS Resource Access Manager shares and resource-based policies needed to bridge the environment's accounts and VPCs. Within the application you register **services**  a URL endpoint or a Lambda function  and **routes** mapping a path to a service. The default route sends everything to the monolith; each new route peels one path off to a new service.

**Why it matters for this chapter.** The mechanics of a strangler fig  a router in front of the monolith, per-path routing, cross-account and cross-VPC network paths, and traffic shifting  are exactly the same for every migration, are fiddly to build correctly, and are frequently the reason a decomposition stalls before the first extraction. Refactor Spaces turns that into a managed resource. It also enforces a helpful discipline: extraction is expressed as a route, so "which capabilities have we actually extracted" has an answer visible in the console.

!!! warning "Refactor Spaces is closed to new customers"

    Since **7 November 2025** AWS Migration Hub Refactor Spaces has been closed to new customers, with **AWS Transform** positioned as the recommended alternative for modernisation work. Study it for the *pattern* it encodes  a managed router in front of a monolith, extraction expressed as a route, cross-account networking provisioned for you  because that pattern is what you will otherwise assemble by hand from API Gateway, a VPC link, an NLB and a Transit Gateway attachment. Do not plan a new migration around the service itself.

**Limitations.** It provisions opinionated infrastructure you do not fully control, adds its own cost per application and per hour, and is deliberately migration-shaped: it is scaffolding for a transition, not a permanent production edge. Once the monolith is gone, the routing usually moves to a plain API Gateway or ALB.

### Supporting analysis services

| Service | Role in decomposition |
|---|---|
| **AWS Application Discovery Service** | Inventories on-premises servers and, importantly, their **network dependencies**  which process talks to which, and how often. The dependency graph is empirical evidence about coupling that beats architectural memory |
| **AWS Migration Hub Strategy Recommendations** | Analyses source code and running processes and proposes rehost, replatform or refactor strategies per component |
| **AWS App2Container** | Containerises an existing Java or .NET application in place, producing an image, an ECS task definition or Kubernetes manifests, and a CloudFormation template. The pragmatic first step: containerise the monolith before decomposing it |
| **Amazon CloudWatch Application Signals** | Once services exist, produces an automatic service map and per-service SLO tracking from telemetry, which validates whether the boundaries you drew match the call patterns you actually have |

!!! tip "Use the dependency graph as evidence, not as the design"

    Application Discovery Service and Application Signals tell you what the system *does*; they do not tell you what it *should* do. A high-traffic dependency between two components may be evidence of a boundary that should not exist, or evidence of one that should be asynchronous. The graph is an input to the domain conversation, not a substitute for it.

---

## Architecture Components

| Component | Responsibility in a decomposed architecture |
|---|---|
| **Client (web, mobile, partner, internal service)** | Determines the shape of the edge: a mobile client with expensive round trips argues for GraphQL; a partner integration argues for a versioned REST contract |
| **Amazon Route 53** | Public DNS and health-check failover; hosts the private zone AWS Cloud Map writes discovery records into |
| **Amazon CloudFront** | Edge caching and TLS termination close to the user; absorbs read traffic before it becomes a service request |
| **AWS WAF** | Managed and rate-based rules at CloudFront, ALB, API Gateway or AppSync; the cheapest place to stop abuse |
| **Amazon API Gateway** | Public and partner API front door: per-consumer keys, usage plans, request validation, throttling, mock and proxy integrations |
| **AWS AppSync** | First-party client API: GraphQL aggregation across services, real-time subscriptions, and cross-team schema federation through Merged APIs |
| **Application Load Balancer** | Shared L7 entry to container services with path and host routing; the low-cost high-volume option where API-management features are not needed |
| **Amazon VPC Lattice** | Application networking across VPCs and accounts with IAM auth policies, connecting ECS, EKS, EC2 and Lambda uniformly; the successor path for App Mesh workloads |
| **Amazon ECS and Amazon EKS** | Where long-lived services run; the compute decision is per service and is made last |
| **AWS Lambda** | Where short, event-shaped work runs; also the standard AppSync resolver target |
| **Amazon EventBridge** | The domain-event routing fabric and schema registry; the mechanism by which a service announces a fact without knowing its consumers |
| **Amazon SQS** | Durable per-consumer buffering, queue-based load levelling, and dead-letter capture |
| **Amazon SNS** | Fan-out of one message to many subscribers, canonically SNS to several SQS queues so each consumer buffers independently |
| **Amazon Kinesis Data Streams** | Ordered, replayable streams for high-throughput telemetry and change-data-capture feeds |
| **AWS Step Functions** | Where a multi-service business process lives explicitly, with retries, catches, compensations and a visible execution history |
| **Amazon DynamoDB** | The default per-service store for known access patterns; its Streams provide outbox semantics without a poller |
| **Amazon Aurora, Aurora Serverless v2, Aurora DSQL** | Relational stores for services needing transactions, joins and ad-hoc queries, with serverless and multi-region-active options |
| **Amazon ElastiCache and MemoryDB** | Caching and shared ephemeral state; MemoryDB when in-memory data must be durable |
| **Amazon OpenSearch Service** | Search and log analytics; in a decomposed system, usually a derived read model rather than a system of record |
| **Amazon S3, Athena, Glue, Redshift** | The analytical plane that replaces cross-service joins; fed by events or zero-ETL integrations |
| **AWS IAM and AWS STS** | Per-service workload identity; the actual security boundary between services |
| **AWS Secrets Manager and Parameter Store** | Per-service credentials and configuration injected at start, never baked into images |
| **AWS KMS** | Envelope encryption for every store, with customer-managed keys where key-level policy and audit matter |
| **Amazon CloudWatch, X-Ray, ADOT** | Metrics, logs, traces and the service map; in a decomposed system the trace is the only complete record of a request |
| **AWS Migration Hub Refactor Spaces** (closed to new customers since November 2025) | The managed strangler-fig routing layer during a decomposition: API Gateway, VPC link, NLB and Transit Gateway provisioned as one resource |
| **AWS CloudFormation, AWS CDK, Terraform** | Every boundary expressed as code, so that a service's infrastructure is versioned with the service |

Read structurally, these components form three planes. The **contract plane**  API Gateway, AppSync, ALB, VPC Lattice, EventBridge  is where boundaries become visible and enforceable; if a boundary is not represented here, it is not real. The **ownership plane**  the per-service databases and their IAM policies  is where boundaries become durable; a boundary not enforced by an IAM policy that physically prevents service B from reading service A's table is a boundary maintained by good intentions. The **evidence plane**  traces, service maps, event schemas, Application Signals  is where you discover whether the boundaries you designed are the boundaries you have. Most decomposition programmes invest heavily in the first, insufficiently in the second, and not at all in the third, and then cannot explain why the architecture drifted.

---

## Important AWS Terminology

| Term | Meaning |
|---|---|
| **Business capability** | Something the business does, named in the business's language, independent of implementation |
| **Subdomain** | A part of the problem space; classified as core, supporting or generic |
| **Bounded context** | A boundary in the solution space inside which one model and vocabulary are consistent |
| **Ubiquitous language** | The shared vocabulary of a bounded context, used identically in conversation, code and schema |
| **Aggregate** | The smallest set of data that must be transactionally consistent; cannot be split across services without a saga |
| **Anti-corruption layer** | Translation at a boundary preventing an external or legacy model from leaking inward |
| **Open host service** | A context that publishes a stable, general-purpose contract for many consumers |
| **Event storming** | A facilitated workshop deriving events, commands, aggregates and contexts from domain experts |
| **Co-change analysis** | Empirical measurement of which files change together, used as evidence of cohesion |
| **Volatility-based decomposition** | Separating components by rate of change rather than by function |
| **Strangler fig** | Incremental migration routing capabilities away from a monolith one at a time until it can be deleted |
| **Refactor Spaces** | AWS Migration Hub feature orchestrating API Gateway, a VPC link, an NLB and Transit Gateway as the routing and networking layer for a strangler-fig migration; closed to new customers since November 2025 |
| **Self-contained system** | A service that owns its data *and* its user interface, integrating with peers at the UI or link level |
| **Command** | A message naming a recipient and requesting an action; couples sender to receiver |
| **Domain event** | A past-tense fact published without knowledge of consumers |
| **Orchestration** | A coordinator drives a multi-service process; explicit and observable |
| **Choreography** | Services react to events with no coordinator; decoupled and harder to observe |
| **GraphQL** | A query language in which the client specifies fields and the server resolves each independently |
| **Schema (AppSync)** | The SDL document defining types and the Query, Mutation and Subscription roots |
| **Resolver** | Code mapping one schema field to one or more data-source operations |
| **Unit resolver** | A resolver bound to a single data source |
| **Pipeline resolver** | An ordered chain of functions over several data sources, sharing `ctx.stash` |
| **APPSYNC_JS** | AppSync's sandboxed JavaScript resolver runtime; a subset of the language, no Lambda invocation |
| **VTL** | Velocity Template Language, the older AppSync resolver runtime |
| **Direct Lambda resolver** | A resolver with no mapping template; the context is passed to the function and its return used as-is |
| **Data source** | A backend AppSync can call: DynamoDB, Lambda, RDS Data API, OpenSearch, HTTP, EventBridge, Bedrock, or NONE |
| **Subscription** | A GraphQL field delivered over WebSocket, bound to mutations with `@aws_subscribe` |
| **Merged API** | An AppSync API composing its schema from several independently owned source APIs, possibly cross-account |
| **Source API** | One team's independently deployable AppSync API, associated into a Merged API |
| **Auto-merge** | Merge mode in which a source API's change propagates to the Merged API without a merged-API deployment |
| **AppSync Events** | AppSync's schemaless WebSocket pub/sub over channel namespaces |
| **N+1 problem** | Resolving a nested field once per item in a list, making latency and cost scale with list size |
| **BatchInvoke and maxBatchSize** | AppSync's batching mechanism for Lambda data sources, the standard N+1 remedy |
| **Query depth and complexity limits** | Configurable ceilings preventing an adversarial nested query from fanning out unboundedly |
| **Partial response** | A GraphQL response returning `data` with nulls plus an `errors` array, at HTTP 200 |
| **Backend for frontend (BFF)** | A per-client-type aggregating service tuned to that client's screens |
| **API composition** | Assembling a view by calling several services and joining in the aggregation layer |
| **Database per service** | Exclusive ownership of a data store by exactly one service |
| **Polyglot persistence** | Different services using different database engines fitted to their access patterns |
| **Purpose-built database** | An AWS engine designed for one data model: key-value, relational, document, graph, wide-column, in-memory, time series, search |
| **Aurora Serverless v2** | Aurora capacity that scales in fine-grained ACU increments, including to a low floor |
| **Aurora DSQL** | Distributed, PostgreSQL-compatible relational service supporting active-active multi-region writes with strong consistency |
| **DynamoDB Streams** | An ordered per-partition-key change feed from a DynamoDB table; the free outbox |
| **Transactional outbox** | Writing the event in the same local transaction as the state change, publishing asynchronously |
| **Dual write** | Writing to the database and publishing separately; always unsafe |
| **Change data capture (CDC)** | Deriving a change feed from a database's own log, on AWS via DynamoDB Streams or AWS DMS |
| **Saga** | A sequence of local transactions with compensating transactions replacing a distributed transaction |
| **Compensating transaction** | A business operation that semantically undoes a completed local transaction |
| **CQRS** | Command Query Responsibility Segregation: separate write and read models |
| **Read model or projection** | A derived, query-shaped store built by consuming events |
| **Reference-data replication** | A consumer keeping a local projection of a small, slowly changing subset of another service's data |
| **Zero-ETL integration** | Managed continuous replication from an operational store into Amazon Redshift without a pipeline to build |
| **Eventual consistency** | The guarantee that replicas converge given no new writes, with a stale window in between |
| **Idempotency key** | A caller-supplied identifier making a repeated operation safe to process once |
| **Tombstone event** | An event announcing a deletion, so consumers can remove their projections |
| **Reconciliation job** | A scheduled comparison answering "are these two services in agreement?" |
| **Data classification** | Labelling data by sensitivity, which determines its isolation and audit scope |
| **AWS Organizations and SCPs** | Account grouping and guardrails; the strongest available isolation boundary on AWS |

---

## Configuration Options

### AWS AppSync configuration

| Setting | Options | How to decide |
|---|---|---|
| **API type** | GraphQL API, Merged API, Events API | Merged API as soon as more than one team owns fields; a single GraphQL API only while one team owns everything |
| **Merge mode** | Auto-merge or manual merge | Auto-merge preserves independent deployability and is the default choice; manual merge only where a release gate is contractually required |
| **Primary authorisation mode** | API key, IAM, Cognito user pools, OIDC, Lambda authoriser | Cognito or OIDC for first-party users; IAM for internal service callers; Lambda authoriser for bespoke token schemes; API key only for public read-only data and never as the sole control on writes |
| **Additional authorisation modes** | Any of the above, with per-field directives | Use to expose a public subset and an authenticated subset from one API without duplicating the schema |
| **Resolver runtime** | APPSYNC_JS or VTL | APPSYNC_JS for all new work; VTL only for existing resolvers |
| **Resolver kind** | Unit or pipeline | Pipeline whenever authorisation, validation or enrichment must precede the data-source call |
| **Data source type** | DynamoDB, Lambda, RDS Data API, OpenSearch, HTTP, EventBridge, Bedrock, NONE | Direct DynamoDB or HTTP where the mapping is simple  it removes a Lambda's cost and cold start; Lambda where real logic is required |
| **maxBatchSize** | Integer per resolver on Lambda data sources | Set on every resolver that appears under a list field; this is the N+1 defence |
| **Caching** | None, per-API, or per-resolver with TTL and cache key | Per-resolver on reference-data fields with a TTL matching real change frequency; never on user-specific data unless the identity is part of the cache key |
| **Query depth limit** | Integer | Set it; an unset depth limit is a denial-of-service vector |
| **Resolver count limit** | Integer per request | Set it, sized from your legitimate worst-case query |
| **Logging level** | NONE, ERROR, ALL | `ERROR` with field-level logging in production; `ALL` in development. `ALL` in production at volume is a significant CloudWatch cost |
| **X-Ray tracing** | Enabled or disabled | Enabled; without it the concurrent resolver fan-out is invisible |
| **WAF web ACL** | Attached or not | Attached, with a rate-based rule, on any internet-facing API |
| **Visibility** | Global or private | Private with a VPC interface endpoint for internal-only APIs |

### Decomposition and boundary configuration

| Decision | Options | How to decide |
|---|---|---|
| **Boundary criterion** | Capability, subdomain, volatility, scaling profile, compliance, aggregate | Capability and subdomain lead; the others corroborate or veto. Never a technical layer |
| **Service granularity** | Coarse (one per capability) or fine (one per aggregate) | Start coarse. Splitting a service later is far cheaper than merging two that have diverged |
| **Extraction order** | Highest value, lowest risk, or highest learning | Lowest risk and highest learning first. The first extraction's purpose is to build the pipeline, the observability and the team's confidence |
| **Data extraction technique** | Dual-write then backfill; CDC replication; big-bang migration | Dual-write with backfill and verification for anything you cannot take offline; big-bang only for small, low-traffic tables |
| **Temporary shared-database access** | Prohibited, or permitted with an expiry | Permitted only with a named owner, a removal ticket and a date. Untracked temporary violations become permanent architecture |
| **Isolation level** | Namespace, cluster, VPC, account | Account for regulated or hostile-tenancy boundaries; the weaker levels for convenience boundaries |

### Data store configuration

| Setting | Options | How to decide |
|---|---|---|
| **DynamoDB capacity mode** | On-demand or provisioned with auto scaling | On-demand for new or spiky services and for anything whose traffic you cannot predict; provisioned with auto scaling and a Savings Plan for steady, high, well-understood load |
| **DynamoDB table design** | Single-table or table-per-entity | Single-table where access patterns are known and related entities are read together; table-per-entity where a service's entities are genuinely independent and the team is new to DynamoDB |
| **DynamoDB Streams view type** | KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES | `NEW_AND_OLD_IMAGES` when publishing domain events, because consumers frequently need the delta |
| **DynamoDB consistency** | Eventually consistent or strongly consistent reads | Strongly consistent only where read-your-writes is required; it costs double and is unavailable on global secondary indexes |
| **Aurora capacity** | Provisioned instances or Serverless v2 ACUs | Serverless v2 for per-service databases with variable load; provisioned for steady high load with reservations |
| **Aurora read scaling** | Reader endpoint, Aurora Auto Scaling for replicas | Route reads to the reader endpoint only where replica lag is acceptable, which excludes read-your-writes paths |
| **Connection management** | Direct, RDS Proxy, RDS Data API | RDS Proxy whenever many small tasks or Lambda functions connect; the Data API for AppSync and Lambda where an HTTP interface avoids connection state entirely |
| **Encryption** | AWS-managed or customer-managed KMS keys | Customer-managed where you need key policy, rotation control and a CloudTrail record of every decrypt |
| **Backup** | Automated backups, PITR, AWS Backup plans | PITR on every operational store; AWS Backup with a cross-account vault for anything whose loss is a business event |
| **Global tables and multi-region** | Single region, DynamoDB global tables, Aurora Global Database, Aurora DSQL | Multi-region only when a business requirement names it; each option has different write semantics and each multiplies cost and complexity |

---

## Design Considerations

```mermaid
flowchart TD
    A["Can you name the business capabilities<br/>in the business's own language?"] -->|"no"| B["Run event storming first.<br/>Do not draw boundaries yet"]
    A -->|"yes"| C["For each capability, can you name<br/>the data it must own exclusively?"]
    C -->|"no"| D["The boundary is not real yet.<br/>Keep it inside the monolith"]
    C -->|"yes"| E["Does any business-mandatory atomic<br/>operation span two candidates?"]
    E -->|"yes and the business will not accept undo"| F["Merge them: the aggregate<br/>cannot be split"]
    E -->|"yes but undo is acceptable"| G["Saga with compensations;<br/>confirm what the customer sees"]
    E -->|"no"| H["Boundary is viable"]
    G --> H
    H --> I["Does a consumer need this data<br/>on a synchronous hot path?"]
    I -->|"yes, small and slow-changing"| J["Replicate reference data<br/>via events into a local projection"]
    I -->|"yes, large or fast-changing"| K["Synchronous call with timeout,<br/>circuit breaker and cache"]
    I -->|"no"| L["Publish a domain event"]
    J --> M["Choose the edge: partner contract,<br/>first-party client, or internal"]
    K --> M
    L --> M
    M -->|"partner or third party"| N["Amazon API Gateway"]
    M -->|"first-party web and mobile"| O["AWS AppSync, Merged API<br/>if more than one team"]
    M -->|"internal east-west"| P["ALB, VPC Lattice,<br/>or ECS Service Connect"]
```

| Quality | What it means here | Design levers | The trade-off you accept |
|---|---|---|---|
| **Scalability** | Each service scales on its own signal and its store scales with it | Per-service capacity decisions; DynamoDB on-demand; Aurora Serverless v2; AppSync's automatic scaling | More independent capacity decisions to get right; the bottleneck moves to whichever store you under-provisioned |
| **Availability** | A failure in one capability degrades one feature | Asynchronous decoupling; nullable GraphQL fields; per-consumer queues; account-level isolation | Composite availability of a synchronous chain is the product of its links; every synchronous dependency you add is a multiplication |
| **Reliability** | Correct behaviour under partial failure and duplicate delivery | Outbox, idempotency keys, dead-letter queues, sagas with compensation, reconciliation jobs | Substantially more code and test surface than a transactional monolith |
| **Durability** | No acknowledged work is lost | Outbox in the same transaction; durable queues; PITR on every store | At-least-once delivery makes duplicates the consumer's problem |
| **Latency** | End-to-end user-perceived time | Concurrent field resolution; batching; reference-data replication; caching at CloudFront and in AppSync | Each hop adds serialisation, TLS and a tail-latency contribution; GraphQL's concurrency mitigates but does not remove this |
| **Consistency** | What the user sees immediately after a write | Keep aggregates whole; strongly consistent reads where required; explicit UI treatment of pending state | Cross-service consistency is eventual, and the business must accept a specific stale window |
| **Cost** | Total cost of ownership, not compute cost | Serverless stores that scale to a floor; shared ALB; caching; batching | Per-service overheads multiply: a database, a pipeline, a dashboard, an on-call rotation per service |
| **Maintainability** | Cost of changing the system | Small services, versioned contracts, one team per service, schema federation | Cross-cutting changes span many repositories; a field added to a screen may touch three teams |
| **Operational complexity** | What the on-call engineer faces at three in the morning | Tracing, service maps, standardised runbooks, Application Signals | This is the tax. It is real, permanent, and the reason the modular monolith remains the correct default for small organisations |

!!! danger "The two pieces of arithmetic that govern every decomposition"

    **Availability multiplies downward.** Six services in a synchronous chain, each independently available 99.9 per cent of the time, compose to roughly 99.4 per cent  about three and a half hours of downtime a month from six components that each look excellent on their own dashboard. **Latency adds upward.** Six p99s of 50 ms do not produce a p99 of 50 ms; tail latencies compound worse than averages. Every synchronous dependency you can convert into a replicated local projection or an asynchronous event removes a term from both calculations, which is why the asynchronous default matters more than any other single design rule in this unit.

---

## AWS Best Practices

### Operational Excellence

Express every boundary as code. A service's repository should contain its application, its infrastructure (CloudFormation, CDK or Terraform), its API schema, its event schemas, its dashboards and its runbook, so that the boundary is versioned with the thing it bounds. Register event schemas in the **EventBridge schema registry** and generate consumer code bindings from them, so that a producer's breaking change is caught at build time rather than in production. Give every service the same shape  the same health-check path, the same structured log format, the same required tags  so that an engineer on call for an unfamiliar service is not also learning a new convention. Adopt **contract testing** between consumers and providers, because in a decomposed system integration tests across every pair do not scale and provider-side contract verification does. Practise the extraction procedure: the first strangler-fig extraction should be rehearsed in a non-production environment end to end, including the data backfill and the cutover, before it is attempted on a real capability.

### Security

The unit of authorisation is the service. Each service gets its own IAM role whose policy names exactly the tables, buckets, queues and keys it uses, and  where possible  narrows further with condition keys such as `dynamodb:LeadingKeys` for tenant isolation or `events:source` to prevent one service publishing events that impersonate another. This is what makes data ownership enforceable rather than aspirational: service B literally cannot read service A's table, because its credentials do not permit it. Place regulated capabilities in their own AWS account under an Organizations OU with Service Control Policies. On AppSync, use per-field authorisation directives rather than a single API-wide mode, implement field-level authorisation as the first function of a pipeline resolver, and give each data source its own least-privilege service role. Encrypt every store with KMS, using customer-managed keys where key-level policy and decrypt auditing matter. Treat the event payload as a security surface: an event containing personal data is a copy of that data in every consumer's queue and every consumer's logs, so publish identifiers and let consumers fetch what they are authorised to see, unless the payload is genuinely non-sensitive.

### Reliability

Make every consumer idempotent, because every asynchronous mechanism on AWS is at-least-once. Give every consumer a dead-letter queue, alarm on its depth, and name an owner for the redrive procedure  an unowned DLQ is silent permanent data loss. Never dual-write; use an outbox or a change stream. Apply a timeout to every synchronous call without exception, retry with exponential backoff and full jitter at exactly one layer, and cap retries with a budget. Prefer replicating a small reference-data projection over calling another service on a hot path, because the projection survives that service's total outage. Build reconciliation jobs from the start, not after the first discrepancy: a scheduled comparison of order counts against payment counts, alarmed on divergence, is cheap insurance in a system that has given up foreign keys.

### Performance Efficiency

Shape the edge to the client. A mobile client benefits enormously from one GraphQL request with concurrent field resolution; a partner integration benefits from a stable, coarse REST resource. Configure `maxBatchSize` on every AppSync resolver under a list field. Cache reference data at the resolver with a TTL matched to its real change rate, and cache further out at CloudFront where the data is public. Choose the database from the access pattern: a single-key lookup at high volume belongs in DynamoDB, not in a relational table with an index. Use RDS Proxy or the RDS Data API wherever many small compute units connect to a relational store, because connection exhaustion is the classic failure of a decomposed system against a shared relational engine. Measure p50, p90, p99 and p99.9 separately per service and per composed request; an average conceals exactly the behaviour users complain about.

### Cost Optimization

Prefer stores that scale to a low floor for per-service databases: DynamoDB on-demand and Aurora Serverless v2 make eight small databases affordable in a way that eight provisioned instances do not. Share one ALB across many services with path routing rather than provisioning one per service. Add VPC endpoints for the AWS APIs your services call from private subnets, because NAT gateway data processing is a persistent and invisible tax. Set log retention on every log group and reduce AppSync logging from `ALL` to `ERROR` in production. Watch subscription connection-minutes on AppSync: a mobile application that holds a subscription open on every backgrounded device generates cost with no user value, and disconnecting on background is a one-line client change with a material bill impact. Tag every resource with service, team and environment so Cost Explorer attributes spend to a team that can act on it.

### Sustainability

The actions that reduce cost reduce energy use: higher utilisation, serverless stores that scale to a floor instead of idling, Graviton-based compute, scheduled shutdown of non-production environments, and shrinking data volumes through log filtering, trace sampling and lifecycle policies. Replicating reference data rather than calling a service repeatedly also reduces total work done per user request, which is a genuine efficiency gain and not only a latency one.

---

## Security Considerations

```mermaid
flowchart TD
    A["Layer 1 Edge: CloudFront, AWS WAF, Shield;<br/>rate-based rules before compute is consumed"] --> B["Layer 2 API: AppSync or API Gateway;<br/>authentication, field-level authorisation, depth and complexity limits"]
    B --> C["Layer 3 Network: private subnets, security group references,<br/>VPC Lattice auth policies, private AppSync endpoints"]
    C --> D["Layer 4 Workload identity: one IAM role per service;<br/>no shared application role"]
    D --> E["Layer 5 Data ownership: IAM policies that physically prevent<br/>cross-service table access; condition keys for tenant isolation"]
    E --> F["Layer 6 Data at rest: KMS customer-managed keys per<br/>classification; Secrets Manager for credentials"]
    F --> G["Layer 7 Event payloads: identifiers not payloads for sensitive data;<br/>events:source conditions to prevent impersonation"]
    G --> H["Layer 8 Detection: CloudTrail, GuardDuty, Security Hub,<br/>AppSync request logs, reconciliation alarms"]
```

**Identity is the boundary.** In a decomposed system the network perimeter tells you very little: all your services are in private subnets and can all reach one another. What actually separates them is that the orders service's IAM role permits `dynamodb:GetItem` on exactly one table. A shared "application role" used by twelve services makes the blast radius of any single compromised container equal to the union of twelve services' permissions, and it silently permits every data-ownership violation this chapter warns about.

**Least privilege can be finer than the resource ARN.** Two condition keys deserve specific attention in a microservices context. `dynamodb:LeadingKeys` restricts a role to items whose partition key matches a pattern, which is how pooled multi-tenancy is enforced at the credential level rather than in application code that can be bypassed by a bug. `events:source` restricts which `source` value a principal may publish, which matters because in a choreographed event-driven system consumers trust the `source` field to decide whether an event is authentic; without the condition, any service with `events:PutEvents` can impersonate any other.

**GraphQL-specific risks.** Three are unique to this chapter's material. First, **query depth and complexity**  an adversarial nested query is a denial-of-service amplifier, and the limits must be set explicitly. Second, **field-level authorisation**  an API-wide authorisation mode says the caller may use the API, not that they may see a particular field; sensitive fields need directives or a pipeline authorisation function. Third, **introspection**  a publicly introspectable schema reveals the shape of your entire domain, including fields that exist but are restricted; consider disabling introspection on internet-facing production APIs and publishing a schema artefact to trusted consumers instead.

**AppSync data-source roles.** AppSync assumes a service role to reach each data source. That role is a genuine principal with genuine permissions, and it is a common oversight to grant it broadly  `dynamodb:*` on the whole account  because it is one step removed from application code. Scope it to the specific table and the specific actions the resolvers perform.

**Events as a data-exfiltration surface.** An event containing a customer's full record is copied into every subscriber's queue, every subscriber's logs and every subscriber's dead-letter queue. If one of those subscribers is a lower-trust analytics service, the personal data has left its classification boundary through a mechanism nobody reviewed. The default should be **thin events**: identifiers, the change type, and a timestamp, with consumers calling back to the owner for details under their own authorisation. Thick events are a deliberate performance choice for non-sensitive data, not a default.

**Compliance scope follows data.** The cheapest way to keep a service out of an audit is for it never to receive regulated data, in any form, including in an event payload. This is a design-time decision about event shape, and it is far cheaper than the alternative of proving after the fact that a service which does receive such data handles it correctly.

---

## Performance Optimization

**Remove synchronous hops before optimising them.** The highest-leverage change available in a decomposed system is usually not making a call faster but eliminating it. Reference-data replication  a consumer keeping a local projection of the few fields it needs, updated by events  converts a network call into a local read and removes a term from both the latency sum and the availability product. Reserve synchronous calls for data that is large, fast-changing, or must be authoritative at the moment of use.

**Exploit GraphQL's concurrency, and defeat its N+1.** Sibling fields resolve in parallel, so an aggregation of four services costs the slowest rather than the sum  that is free performance and it is the main reason to put AppSync at a mobile edge. But nested list fields serialise per item unless batched. Set `maxBatchSize` on Lambda data sources under list fields, use `BatchGetItem` for DynamoDB, and write resolver functions that accept and return arrays. Test with realistic list sizes; a development dataset of three records hides this defect completely.

**Cache in the right place, once.** CloudFront for public, cacheable responses; the AppSync resolver cache for reference-data fields with a TTL matched to real change frequency; ElastiCache for shared computed state across replicas; an in-process cache for data that changes daily. Caching the same data at three layers produces three invalidation problems and a stale window equal to their sum. Be explicit about the invalidation strategy  TTL, write-through, or event-driven invalidation on a domain event  because a stale cache is a correctness bug wearing a performance costume.

**Choose the database from the access pattern, then design the keys.** A DynamoDB table whose partition key does not match its dominant query will be slow and expensive regardless of provisioned capacity, and no amount of scaling fixes a hot partition. Enumerate the access patterns before designing the key schema; this is the single most consequential performance decision in a DynamoDB-backed service and it is very hard to change later. On the relational side, connection count is usually the binding constraint before CPU: many small tasks each holding a pool exhausts an Aurora instance, and RDS Proxy or the Data API is the answer.

**Batch and parallelise deliberately.** Fan out independent downstream calls concurrently rather than sequentially  three 40 ms calls in parallel cost 40 ms, in series 120 ms. Use batch APIs where they exist: `BatchGetItem`, `TransactWriteItems` where atomicity is genuinely needed, SQS batch send and receive, `PutRecords` on Kinesis, and `PutEvents` with up to the batch limit of entries. Per-call overhead dominates small operations.

**Measure the composed request, not only the services.** Every service can report an excellent p99 while the screen the user sees is slow, because the composition is where the time goes. Record end-to-end latency at the edge separately from per-service latency, and use the X-Ray trace waterfall for slow requests specifically  both X-Ray and OpenTelemetry allow filtering by duration, and one slow trace answers in a minute what a week of dashboard-watching will not.

---

## Cost Optimization

| What you pay for | Dimension | Frequently overlooked |
|---|---|---|
| **AppSync operations** | Per query and mutation | A chatty client issuing five small queries per screen instead of one composed query |
| **AppSync subscriptions** | Per message delivered and per connection-minute | Mobile clients holding subscriptions open while backgrounded, generating connection-minutes with no user value |
| **AppSync cache** | Per instance-hour by size | A cache provisioned for a workload whose data is not cacheable |
| **API Gateway** | Per request; REST APIs cost more per request than HTTP APIs | Using REST APIs for internal high-volume traffic where an HTTP API or ALB would serve |
| **Lambda resolvers** | Per invocation and GB-second | A resolver that could have been a direct DynamoDB or HTTP data source, paying Lambda cost and cold-start latency per field |
| **DynamoDB** | Per request unit or provisioned capacity, plus storage and streams | Strongly consistent reads at double cost where eventual would do; on-demand left on a steady predictable workload |
| **Aurora** | Per ACU-hour or instance-hour, plus I/O and storage | Provisioned instances for a per-service database that is idle most of the day; Serverless v2 with a minimum ACU floor set too high |
| **NAT gateway** | Per hour and per GB processed | Every AWS API call from private subnets without VPC endpoints |
| **Inter-AZ and cross-Region transfer** | Per GB | Chatty east-west traffic crossing AZs; cross-Region event replication configured without a business requirement |
| **CloudWatch Logs** | Per GB ingested and stored | AppSync logging at `ALL` in production; debug logging left enabled; no retention policy |
| **X-Ray** | Per trace recorded | Unsampled tracing on a high-volume API |
| **EventBridge** | Per million events published | Fine-grained events published per field change rather than per meaningful domain change |
| **Data stores multiplied per service** | Instance-hours or request units | Eight services with eight provisioned databases where serverless options would idle at near-zero |

**The structural cost lesson of decomposition** is that fixed per-service costs multiply. A database, a pipeline, a log group, a dashboard, an alarm set and possibly a load balancer per service means that a system split into twenty services pays twenty times some fixed overhead. This is the strongest quantitative argument against nano-services and the strongest argument for serverless data stores at fine granularity: DynamoDB on-demand and Aurora Serverless v2 have a near-zero floor, which is what makes eight small services economically viable where eight provisioned RDS instances would not be.

**Committed capacity and rightsizing.** Compute Savings Plans cover Lambda, Fargate and EC2 in one commitment, which suits a mixed estate; DynamoDB reserved capacity suits steady provisioned tables. Commit to the measured trough, not the peak. Revisit quarterly, because a decomposed estate's cost shape changes as services grow at different rates  which is itself one of the benefits, since per-service tagging makes the change visible.

---

## Monitoring and Observability

In a decomposed system no single component's logs contain a failure. The failure lives in the composition, and only three instruments see it: the distributed trace, the correlated log, and the reconciliation job.

```mermaid
flowchart LR
    A["Client"] -->|"trace id created at the edge"| B["AppSync or API Gateway"]
    B -->|"X-Ray context propagated"| C["Service A"]
    B --> D["Service B"]
    C -->|"trace id in event detail"| E["Amazon EventBridge"]
    E -->|"trace id in message attributes"| F["Amazon SQS"]
    F --> G["Consumer service"]
    C --> H["Structured JSON logs with trace id and correlation id"]
    D --> H
    G --> H
    H --> I["CloudWatch Logs Insights"]
    C --> J["ADOT collector"]
    D --> J
    G --> J
    J --> K["AWS X-Ray service map"]
    J --> L["Amazon Managed Prometheus"]
    K --> M["CloudWatch Application Signals: SLOs per service"]
    I --> N["Dashboards and alarms"]
    L --> N
    M --> N
    O["Scheduled reconciliation job"] --> P["Divergence metric and alarm"]
    P --> N
```

### The metrics that matter for this chapter's concerns

| Metric | Source | What it tells you |
|---|---|---|
| **`4XXError` and `5XXError`** | AppSync, API Gateway | Client-side and server-side failure rates at the edge |
| **GraphQL `errors` array count** | AppSync request logs, via a metric filter | **The critical one.** Partial failures return HTTP 200; without a metric filter counting `errors`, a resolver failing on every request is invisible |
| **`Latency` at the API versus per-resolver latency** | AppSync and X-Ray | Whether the composition or a specific backend is slow |
| **Resolver invocation count per request** | AppSync logs | Detects N+1: a count that scales with list size is the signature |
| **`ConnectSuccess` and `SubscribeSuccess`** | AppSync | Subscription health; a silent drop in subscribe rate means clients are failing to establish real-time updates |
| **`ThrottledRequests` and `ConsumedReadCapacityUnits`** | DynamoDB | Hot partitions, under-provisioning, and whether the key design matches the access pattern |
| **`DatabaseConnections`** | RDS and Aurora | Connection exhaustion from many small compute units  a classic decomposition failure |
| **`ReplicaLag`** | Aurora | How stale a read-replica read may be; directly relevant to read-your-writes bugs |
| **`IteratorAge`** | DynamoDB Streams and Kinesis consumers | How far behind the outbox publisher is; a rising value means events are being published late and consumers are diverging |
| **`ApproximateAgeOfOldestMessage`** | SQS | Consumer health on asynchronous paths; the asynchronous equivalent of latency |
| **DLQ `ApproximateNumberOfMessagesVisible`** | SQS | Permanently failed work that a human must act on. Always alarm on this |
| **`FailedInvocations` and rule match count** | EventBridge | Events published that no rule matched  usually a schema change nobody told the consumers about |
| **Reconciliation divergence count** | Custom metric from a scheduled job | Whether two services actually agree; the only direct measurement of eventual-consistency health |
| **Error budget burn rate** | Derived from SLIs, tracked by Application Signals | The only alarm that reliably corresponds to user harm |

!!! danger "The HTTP 200 blind spot"

    This is worth stating twice. A GraphQL API returning `{"data": {"order": {...}, "loyaltyBalance": null}, "errors": [{"path": ["loyaltyBalance"], ...}]}` has failed for one field and succeeded for the rest, and it returns **HTTP 200**. Every dashboard, load balancer metric and uptime check that counts non-200 responses will report perfect health while a feature is entirely broken. Create a CloudWatch metric filter on the AppSync log group matching error entries, dimension it by field path, and alarm on it. Teams discover this the slow way, usually via a customer.

**Logs.** Emit structured JSON with a stable schema carrying the trace ID, a business correlation ID (the order ID, the claim number), the service name, the version and the environment on every line. Without a correlation ID, investigating one customer's problem across six services means grepping six log groups by timestamp, which does not work under concurrency. Use Logs Insights to query across groups and metric filters to turn log patterns into alarmable metrics.

**Traces.** Instrument with OpenTelemetry through ADOT so the destination is a configuration choice. Propagate context across asynchronous boundaries by carrying the trace ID in EventBridge event detail and SQS message attributes, or your service map fractures at exactly the boundary you most need to understand. Sample low for successes and always for errors and slow requests. The trace-derived **service map is the most reliable architecture diagram you will ever have**, because it shows what the system does rather than what a document claims  and in the context of this chapter, it is how you discover that a boundary you designed as asynchronous has quietly acquired a synchronous call.

**Application Signals** deserves specific mention here because it closes the loop on decomposition: it produces per-service SLOs and a dependency map from telemetry automatically, which lets you ask, six months after an extraction, whether the boundaries you drew match the call patterns you actually have. They frequently do not, and knowing that early is what prevents architectural drift from becoming architectural debt.

---

## Integration with Other AWS Services

| Service | Why it integrates with microservices design |
|---|---|
| **AWS AppSync** | Client-facing aggregation and federation; resolves fields against many services concurrently and merges team-owned schemas |
| **Amazon API Gateway** | Partner and public contracts with per-consumer keys, usage plans and validation; custom domains with base-path mappings federate REST APIs across teams |
| **Application Load Balancer** | Shared, low-cost L7 entry to container services for internal and high-volume traffic |
| **Amazon VPC Lattice** | Cross-VPC and cross-account service-to-service connectivity with IAM auth policies and no sidecars |
| **Amazon EventBridge** | Domain-event routing plus a schema registry that makes event contracts explicit and generatable |
| **Amazon SQS** | Per-consumer durable buffering and dead-letter capture; the bulkhead between a fast producer and a slow consumer |
| **Amazon SNS** | One-to-many fan-out, canonically to several SQS queues so each consumer buffers independently |
| **Amazon Kinesis Data Streams** | Ordered, replayable change and telemetry streams; the DynamoDB Streams alternative when replay matters |
| **AWS Step Functions** | The explicit home of a multi-service business process, with compensations and visible execution history |
| **Amazon DynamoDB** | The default per-service store for known access patterns; Streams give outbox semantics free |
| **Amazon Aurora, Aurora Serverless v2, Aurora DSQL** | Relational per-service stores, with serverless economics at fine granularity and multi-region active-active where required |
| **Amazon RDS Proxy and the RDS Data API** | Connection management for many small compute units against a relational store; the Data API is also an AppSync data source |
| **Amazon ElastiCache and MemoryDB** | Shared caching and durable in-memory state |
| **Amazon OpenSearch Service** | Search read models built from events |
| **Amazon S3, AWS Glue, Amazon Athena, Amazon Redshift** | The analytical plane replacing cross-service joins; zero-ETL integrations remove the pipeline you would otherwise build |
| **AWS Database Migration Service** | Change data capture from relational stores, and the dual-write-and-backfill mechanism for extracting a table from a monolith |
| **Amazon Cognito** | The generic identity subdomain you should not build |
| **AWS IAM and STS** | Per-service identity; the mechanism that makes data ownership enforceable |
| **AWS Migration Hub Refactor Spaces** | Managed strangler-fig routing during decomposition; closed to new customers since November 2025, with AWS Transform as the successor |
| **AWS Application Discovery Service and Application Signals** | Empirical dependency evidence before and after decomposition |
| **AWS CloudFormation, CDK, Terraform** | Boundaries as code, versioned with the service they bound |
| **Amazon CloudWatch, AWS X-Ray, ADOT** | The observability without which a decomposed system cannot be operated |

```mermaid
flowchart TD
    WEB["Web and mobile clients"] --> CF["Amazon CloudFront with AWS WAF"]
    PARTNER["Partner systems"] --> APIGW["Amazon API Gateway REST<br/>usage plans and API keys"]
    CF --> AS["AWS AppSync Merged API"]
    AS --> SA["Catalogue source API"]
    AS --> SB["Orders source API"]
    AS --> SC["Loyalty source API"]
    SA --> DDB1["DynamoDB catalogue table"]
    SB --> LORD["Lambda to Orders service on ECS"]
    SC --> ALBL["Internal ALB to Loyalty service"]
    APIGW --> LORD
    LORD --> AUR["Aurora Serverless v2 orders cluster<br/>with outbox table"]
    AUR --> DMS["AWS DMS change data capture"]
    DDB1 --> STR["DynamoDB Streams"]
    DMS --> EB["Amazon EventBridge domain bus<br/>with schema registry"]
    STR --> EB
    EB --> SF["AWS Step Functions order saga"]
    EB --> Q1["SQS shipping queue"]
    EB --> Q2["SQS projection queue"]
    EB --> Q3["SQS analytics queue"]
    Q1 --> SHIP["Shipping service"]
    Q2 --> PROJ["Projection worker"]
    PROJ --> OSS["Amazon OpenSearch read model"]
    Q3 --> FH["Amazon Data Firehose to S3"]
    FH --> ATH["Amazon Athena and Amazon Redshift"]
    Q1 --> DLQ["Dead letter queue with depth alarm"]
    SF --> LORD
    SF --> SHIP
```

Read architecturally, this diagram separates four planes deliberately. The **client plane** is shaped to its consumers: GraphQL for first-party clients whose pain is round trips, REST with usage plans for partners whose need is a stable versioned contract. The **ownership plane** shows each service with exactly one store and no arrows between stores  that absence is the design. The **event plane** carries changes out of each store through a mechanism derived from the store's own log (Streams, CDC) so there is no dual write, into EventBridge where the schema registry makes the contract explicit, and out to per-consumer queues so no consumer's slowness affects another's. The **analytical plane** is where the cross-service join went: Firehose to S3 to Athena and Redshift, so that "finance needs a report across all six services" never becomes a reason to grant read access to an operational table.

---

## Common Architecture Patterns

### Decompose by business capability

Services aligned to what the business does, each owning its data. The default and most durable decomposition. Implemented on AWS as one service with one store per capability, communicating through EventBridge for facts and API Gateway, AppSync or VPC Lattice for requests.

### Decompose by subdomain, with core, supporting and generic classification

The refinement that tells you where to invest. Generic subdomains  identity, notification, payment processing  are bought or consumed as managed services (Cognito, SES, SNS, a payment provider). Core subdomains get your best engineers and full autonomy. This classification saves more effort than any other single technique in this chapter.

### Strangler fig

Incremental extraction behind a routing layer, with each iteration ending in data-ownership transfer and deletion of the old code. On AWS the routing layer is API Gateway or an ALB in front of the monolith  assembled directly, or, in existing estates, orchestrated by AWS Migration Hub Refactor Spaces, which has been closed to new customers since November 2025. ALB weighted target groups or API Gateway canary stages perform the traffic shift; DMS performs the data migration. The pattern's discipline is finishing each iteration; a strangler fig stopped halfway is a permanent hybrid in which nobody can change anything.

### Branch by abstraction and parallel run

Two techniques for de-risking an extraction. **Branch by abstraction** introduces an interface inside the monolith, implements it twice  once against the old code, once against the new service  and switches with a feature flag in AWS AppConfig. **Parallel run** sends production traffic to both implementations, serves the old result, and compares the two asynchronously, alarming on divergence. Parallel run is the only technique that gives you real confidence before a cutover on a high-stakes capability, and it is worth its cost for payments, pricing and anything with a regulator.

### Self-contained systems

A stronger variant in which each service owns its data *and* its user interface, integrating with peers through hyperlinks or client-side composition rather than a shared aggregation layer. It eliminates the aggregation bottleneck entirely, at the cost of a less integrated user experience. Worth knowing because it is the honest alternative when the BFF or gateway has become the coordination point microservices were meant to remove.

### API composition and backend for frontend

**API composition** assembles a view by calling several services and joining the results in the aggregation layer. **Backend for frontend** gives each client type  web, mobile, partner, internal  its own aggregating service tuned to its screens, so that a mobile client's need for a combined payload does not distort the domain services. AppSync is a managed API-composition engine; a BFF is what you build when the composition needs real logic. The failure mode of both is a central team owning them, which is why Merged APIs matter.

### Database per service with polyglot persistence

Exclusive ownership plus the freedom  not the obligation  to select an engine per access pattern. On AWS this is the difference between one Aurora cluster serving eleven workloads badly and DynamoDB, Neptune, Timestream and OpenSearch each serving one workload well.

### Transactional outbox and change data capture

The only correct construction for publishing an event about a state change. On DynamoDB, Streams provide it with no poller; on Aurora, DMS change data capture reads the transaction log; the hand-rolled outbox table plus poller remains valid where you need control over payload shaping.

### Saga

Multi-service business transactions as local transactions plus compensations; the full pattern (orchestration versus choreography, ordering, compensation windows) is in [4.3 Saga with compensating transactions](topic3.md#saga-with-compensating-transactions). The data-management point is that the saga is what you buy with the transaction you sold when you split the aggregate.

### CQRS and event sourcing

Separate write and read models, with projections built by consuming events. Solves the loss of cross-service joins. Event sourcing goes further and makes the event log the system of record, which is powerful for audit and temporal queries and considerably more demanding, because historical schema evolution and projection rebuild time become engineering problems in their own right.

### Reference-data replication

A consumer keeps a local projection of the small, slowly changing subset of another service's data that it needs on a hot path, updated by events. Frequently the single highest-value change available in a chatty system: it removes a synchronous hop, a failure mode and a latency term all at once.

### Anti-corruption layer

An adapter service translating a legacy or third-party model into your domain model. Essential during strangler-fig migration, and the correct treatment of any integration whose model you do not control.

### Thin events with callback

Publishing identifiers and change type rather than full payloads, with consumers fetching details under their own authorisation. Reduces coupling to the producer's internal model, keeps sensitive data inside its classification boundary, and keeps event payloads small. The trade-off is a synchronous callback, so it is not appropriate where the consumer must work when the producer is down.

### Zero-ETL and the analytical plane

Continuous managed replication of operational data into Redshift, or event-driven landing in S3 queried by Athena, as the answer to cross-service reporting. It exists so that "we need a report" never becomes an argument for a shared database.

---

## Industry Use Cases

| Sector | Decomposition decision | Communication choice | Data choice |
|---|---|---|---|
| E-commerce | Catalogue, pricing, inventory, ordering, fulfilment, payments as capabilities | AppSync Merged API for web and mobile; EventBridge between services | DynamoDB for catalogue and orders; Aurora for finance-facing reconciliation; OpenSearch for search |
| Retail banking | Payment initiation isolated in its own account by compliance scope | Cross-account EventBridge only; no synchronous calls into the regulated account | Aurora with customer-managed KMS keys inside scope; DynamoDB outside |
| Insurance | Claim intake, fraud scoring, adjudication, payment as capabilities; the claim process itself as an explicit orchestration | Step Functions with `waitForTaskToken` for human adjuster steps | Aurora for the claim aggregate; S3 for documents; OpenSearch for adjuster search |
| Media streaming | Entitlement, rights, catalogue, viewing history, recommendations split on access pattern as much as domain | AppSync for the client; Kinesis for viewing telemetry | DynamoDB for entitlement; Neptune for rights graphs; Timestream for viewing history; OpenSearch for catalogue search |
| Travel | Booking, itinerary, loyalty, content as capabilities across several supplier integrations | AppSync Merged API, one source API per team; anti-corruption adapters per supplier | Aurora for bookings; DynamoDB for loyalty; ElastiCache for supplier response caching |
| Healthcare | Patient record isolated by data classification; integration adapters one per external system | Thin events carrying identifiers only; details fetched under the consumer's own authorisation | Aurora with CMK for the record; DynamoDB for adapter state; S3 with Object Lock for documents |
| Logistics | Order, route optimisation, tracking, proof of delivery | Events for state changes; API Gateway for carrier partner integration | DynamoDB for tracking at high write volume; Neptune for route graphs; Timestream for telemetry |
| Industrial IoT | Ingestion, anomaly detection, device management, operator console | Kinesis for ingestion; AppSync subscriptions for the live console | Timestream for readings; DynamoDB for device registry; S3 for the raw archive |
| B2B SaaS | Pooled and siloed tenancy as a data-topology decision, not a code fork | One API surface; tenant context in every request | DynamoDB with `LeadingKeys` isolation for pooled; per-tenant tables or accounts for siloed |
| Public sector | Boundaries follow supplier contracts, because no supplier may block another's release | AppSync Merged API with one source API per supplier account | Per-supplier stores; a shared analytical plane in S3 |

---

## Advantages

**Boundaries that follow the business are stable.** Business capabilities change on a scale of years; technical implementations change on a scale of months. A service named `pricing` survives three rewrites of its internals and two changes of database engine, because the boundary was drawn where the business is stable. This is the deepest reason capability-based decomposition outperforms every technical alternative.

**Exclusive data ownership makes autonomy real.** The moment a team owns its store outright, it can change its schema, its engine, its capacity mode and its indexing without a conversation. Independent deployability of code is meaningless if the schema is shared; data ownership is what converts an organisational chart into an engineering reality, and an IAM policy is what makes it enforceable rather than aspirational.

**Purpose-built persistence becomes possible.** A shared database forces one engine on every workload, which means the lowest common denominator. Database-per-service is the precondition for using DynamoDB where the pattern is key-value, Neptune where it is a graph, and Timestream where it is time series  and the performance and cost differences between the right engine and a general-purpose one are frequently an order of magnitude, not a percentage.

**GraphQL federation reconciles client convenience with team autonomy.** Historically an aggregation layer was a coordination bottleneck: convenient for clients, owned by one team, queued behind by everyone else. AppSync Merged APIs let each team ship a field by deploying their own API, while the client still sees one endpoint and one schema. That is a genuine structural improvement, not a convenience feature, and it is why Merged APIs deserve the emphasis this chapter gives them.

**Partial failure becomes a first-class outcome.** A GraphQL response with one null field and an errors entry is a degraded screen rather than a failed one. Combined with per-consumer SQS queues and asynchronous events, the architecture gains the ability to **choose what breaks first**, which is one of the most valuable properties a production system can have and is unavailable in a monolith where everything shares a process.

**Compliance scope becomes a design parameter.** Because data ownership determines audit scope, an architect can remove entire teams and services from a regulatory regime by designing where regulated data lives and ensuring it never travels in an event payload. The saving is recurring and large.

**Cost becomes attributable.** Per-service tagging means the bill decomposes by team, and a team that can see its own cost behaves differently from one looking at a single company-wide figure. Serverless per-service stores make fine granularity economically viable in a way provisioned instances never did.

---

## Limitations

**Decomposition is irreversible in practice.** Splitting a service is comparatively easy; merging two that have diverged  different schemas, different engines, different deployment histories, different teams  is a project. This asymmetry is why the advice is always to start coarse. A boundary drawn wrongly is not a bug you fix in a sprint.

**Domain knowledge is the binding constraint, and it is scarce.** Correct boundaries require people who understand the business deeply enough to know where the language changes. Those people are usually busy, frequently not engineers, and sometimes no longer at the company. No tool, and no amount of code analysis, substitutes for them. This is the honest reason many decompositions produce technical-layer boundaries: technical layers are visible in the code, and domain boundaries are not.

**You lose transactions, joins and referential integrity, and you must replace all three.** Sagas, compensations, outboxes, idempotency, projections and reconciliation are code you now write, test and operate. The business must accept eventual consistency, and where it will not, some intended boundaries are simply not viable.

**Per-service fixed costs multiply.** A database, a pipeline, a repository, dashboards, alarms, a runbook, an owner and an on-call rotation per service means twenty services is twenty of each. This is the arithmetic behind the nano-service anti-pattern and the reason a modular monolith remains correct for small organisations.

**Latency adds and availability multiplies.** A chain of synchronous services has latency equal to the sum and availability equal to the product. GraphQL's concurrent field resolution mitigates the latency term for aggregation specifically, but it does not help a chain, and nothing helps the availability product except removing dependencies.

**GraphQL introduces its own failure modes.** The N+1 problem, unbounded query complexity as a denial-of-service vector, the HTTP 200 partial-failure blind spot, and caching that is coarser than REST's because the response shape varies per request. Each is manageable; none is automatic, and all four are routinely discovered in production rather than in design.

**Federation has an operational surface.** Merged APIs add a merge step that can fail, cross-account IAM associations that can break, and a schema-conflict class of error that does not exist with a single API. Source API quotas bound how far the federation scales.

**Testing gets harder.** Integration testing across every pair of services does not scale, so you need contract testing, which requires discipline the organisation may not have. Local development of a system with twelve services and eight databases is a genuine engineering problem that consumes real effort.

**Observability is a precondition, not an add-on.** Without distributed tracing, correlation IDs and a service map, an incident spanning five services is close to unresolvable. Organisations that decompose before investing in observability trade a debuggable system for an undebuggable one, and diagnose the result as a microservices problem rather than an instrumentation one.

---

## Common Mistakes

### Beginner Mistakes

| Mistake | Why it is wrong | What to do instead |
|---|---|---|
| Decomposing along technical layers | Produces services that must all deploy together for any feature | Decompose vertically by business capability |
| Creating entity services exposing only CRUD | Behaviour lives in callers; the service is a shared database with HTTP in front | Move behaviour to where the data lives; a service owns a capability |
| Starting with the compute platform | Boundaries end up shaped like the deployment units you already had | Boundaries, then contracts, then data, then compute |
| Sharing a database "just for reads" | A read dependency on a physical schema couples just as hard and less visibly | Expose an API, publish events, or replicate a projection |
| Dual-writing to the database and the event bus | Admits a window where one succeeds and the other does not; unfixable by retry | Outbox table, DynamoDB Streams, or DMS change data capture |
| Naming events as commands (`SendEmail`) | Couples the publisher to the consumer with an event's syntax | Past-tense facts: `OrderPlaced`, `PaymentSettled` |
| One AppSync API owned by a platform team | Every product team queues to add a field; the API becomes the bottleneck | Merged API with one source API per team, auto-merge enabled |
| No `maxBatchSize` on resolvers under list fields | N+1: latency and cost scale with list size, invisible with test data | Configure batching; test with production-scale lists |
| No query depth or complexity limits | An adversarial nested query is a denial-of-service amplifier | Set both explicitly |
| Monitoring only HTTP status on a GraphQL API | Partial failures return 200; a broken field is invisible | Metric filter on the `errors` array, dimensioned by field path |
| Choosing the database the team already knows | A key-value pattern in a relational table, or ad-hoc queries against DynamoDB | Enumerate access patterns first; choose the engine from them |
| Copying a reference where a snapshot is meant | An order's price changes when the catalogue's does | Copy the value into the order; a price agreed is not a price current |
| A shared `company-common` library across services | A version bump requires a coordinated deploy of every service | Prefer duplication to coupling across boundaries |

### Production Mistakes

| Mistake | Consequence | Remedy |
|---|---|---|
| Temporary shared-database access with no expiry | Becomes permanent architecture; extraction stalls forever | Named owner, removal ticket, date, and a dashboard of outstanding violations |
| Thick events containing personal data | Regulated data copied into every consumer's queue, logs and DLQ | Thin events with identifiers; consumers fetch under their own authorisation |
| No `events:source` condition on `PutEvents` | Any service can publish events impersonating any other | Condition-key restriction per service role |
| No dead-letter queue, or a DLQ with no alarm and no owner | Silent permanent loss of business events | DLQ per consumer, depth alarm, owned redrive runbook; see [4.3 Dead-letter queue with owned redrive](topic3.md#dead-letter-queue-with-owned-redrive) |
| No reconciliation jobs | Divergence between services discovered by a customer, months later | Scheduled comparison with a divergence metric and alarm |
| Consumers that are not idempotent | Duplicate orders and double charges under at-least-once delivery | Idempotency keys with conditional writes; techniques in [4.3 Idempotency](topic3.md#idempotency) |
| Projection with no rebuild path | A projector bug becomes permanent corruption | Ensure read models are rebuildable from retained events; test the rebuild |
| Aurora connection exhaustion from many small tasks | Latency cliff, then errors, under exactly the load you least want | RDS Proxy, the RDS Data API, or bounded per-task pools |
| Unbounded AppSync subscription lifetimes | Connection-minute cost from backgrounded mobile clients | Disconnect on background; set idle timeouts |
| AppSync logging at `ALL` in production | CloudWatch ingestion can exceed the cost of the API itself | `ERROR` with field-level logging; sample where more is needed |
| A hot DynamoDB partition | Throttling at a fraction of provisioned capacity | Revisit the key design; add a write-sharding suffix if the pattern demands it |
| Schema change published without consumer notice | Consumers fail on deserialisation; EventBridge rules stop matching | Schema registry, additive-only evolution, versioned event types |
| Reading from an Aurora replica on a read-your-writes path | User does not see their own change; support tickets | Route those reads to the writer, or design the UI for pending state |
| No trace propagation across the asynchronous boundary | The service map fractures exactly where you need it | Trace ID in event detail and SQS message attributes |

### Certification Traps

| Trap | The reality |
|---|---|
| "Microservices improve performance" | They typically worsen latency by adding network hops. They improve deployability, independent scalability and blast-radius containment |
| "AppSync replaces API Gateway" | They solve different problems. API Gateway carries usage plans, API keys and per-consumer throttling for partner APIs; AppSync aggregates and federates for first-party clients. Large estates run both |
| "GraphQL always reduces the number of backend calls" | It reduces *client* round trips. Backend calls can increase dramatically without batching  this is the N+1 problem |
| "A GraphQL error means a non-200 response" | Partial failures return HTTP 200 with an `errors` array |
| "Write to the database, then publish the event" | That is a dual write and it is always unsafe. Outbox or change data capture |
| "Two-phase commit across microservices" | Impractical at scale and not offered. Sagas with compensating transactions, orchestrated by Step Functions  see [4.3 Saga with compensating transactions](topic3.md#saga-with-compensating-transactions) |
| "Each microservice must have its own database engine" | It must have its own *store*. Two services may both use DynamoDB, or separate schemas on separate clusters. Polyglot persistence is permitted, not mandatory |
| "Separate schemas on the same Aurora cluster satisfy database-per-service" | Better than a shared schema, but capacity, failover and maintenance are still shared; it is a compromise, not the pattern |
| "DynamoDB cannot support transactions" | `TransactWriteItems` provides ACID across items within an account and region, with limits. It does not extend across services |
| "Strongly consistent reads are the safe default in DynamoDB" | They cost double, are unavailable on GSIs, and are unnecessary for most reads. Use them only where read-your-writes is required |
| "A Merged API is a performance optimisation" | It is an *ownership* mechanism. Its purpose is to let teams deploy independently while clients see one schema |
| "Decompose by entity: a Customer service, an Order service, a Product service" | That is entity-service decomposition and it produces a distributed CRUD layer. Decompose by capability |
| "Event-driven means no synchronous calls anywhere" | Synchronous calls are correct where the user is waiting and the answer must be authoritative. The rule is that asynchronous is the *default*, not the only option |
| "Separating a namespace or a VPC reduces audit scope" | Only a separate AWS account under an Organizations OU with SCPs is a platform-enforced, auditor-demonstrable boundary |
| "Refactor Spaces is a permanent architecture" | It is migration scaffolding  and it is closed to new customers as of November 2025. After the monolith is gone the routing moves to plain API Gateway or an ALB |

---

## Summary

First, **decomposition is a problem-space activity, and every failure of microservices adoption traces back to skipping it**. Boundaries drawn from the shape of the existing code  controllers, repositories, entities, layers  reproduce the monolith's coupling across a network and deliver none of the independence that justified the cost. Boundaries drawn from business capabilities and bounded contexts are stable over years, because the business changes far more slowly than its implementations. The practical sequence is fixed: capabilities and contexts first, corroborated by volatility, scaling profile, compliance scope and empirical co-change; then data ownership; then contracts; and only then a compute platform. An architect who is asked "ECS or EKS?" before "what does this business do?" is being asked the wrong question first.

Second, **the aggregate is the hard floor on granularity**. You cannot split data that must be transactionally consistent without giving up the transaction and buying a saga in its place. The most valuable conversation in any decomposition is the one that asks the business, explicitly, which operations must be atomic and what the customer sees if the second half is undone two seconds after the first. The answers determine which boundaries are viable, and they must be obtained before the boundary is drawn, not discovered afterwards in an incident review.

Third, **communication style is a design decision with arithmetic consequences**. Availability multiplies downward along a synchronous chain and latency adds upward, so each synchronous dependency you remove improves both. The default should therefore be asynchronous, with synchronous calls justified individually, and the highest-leverage change available in most chatty systems is replacing a hot-path call with a locally maintained projection fed by events. Where synchronous aggregation is genuinely required, GraphQL's concurrent field resolution converts a sum of latencies into a maximum  which is the strongest technical argument for AppSync at a client edge, and it comes with the N+1 problem and the HTTP 200 partial-failure blind spot as the price of admission.

Fourth, **an API layer is an ownership question before it is a technology question**. A single shared API artefact owned by a central team is the coordination bottleneck microservices exist to remove, however good the technology behind it. AppSync Merged APIs, and API Gateway custom domains with per-team base-path mappings, exist to make the edge federated so that a team ships a field by deploying its own artefact. This is why Merged APIs matter more in this syllabus than any individual AppSync feature: they are the mechanism that keeps a convenient client experience from re-centralising the organisation.

Fifth, **data ownership is what makes the architecture real, and IAM is what makes ownership real**. A boundary that is documented but not enforced by a policy physically preventing service B from reading service A's table is a boundary maintained by good intentions, and good intentions have a half-life of about one quarter. Exclusive ownership is also the precondition for purpose-built persistence: only once a service owns its store can it choose DynamoDB for a key-value pattern, Neptune for a graph and Timestream for a series, and those choices are frequently order-of-magnitude improvements rather than percentage ones.

Sixth, **there is exactly one correct way to publish an event about a state change, and it is the outbox**. A dual write admits a failure window that no retry logic can close, because the retry state died with the process. Writing the event in the same local transaction and publishing asynchronously from the committed record  with DynamoDB Streams, Aurora change data capture, or a poller  closes it, at the price of at-least-once delivery and therefore mandatory consumer idempotency. That price is bounded and testable; the dual write's is neither.

Seventh, and most importantly for this module, **every one of these principles costs something, and an architect's professional contribution is pricing them honestly**. Database per service costs you joins, transactions and referential integrity, and buys you autonomy and engine choice. Asynchronous communication costs you read-your-writes and simple debugging, and buys you availability and elasticity. Federation costs you a merge step and a class of schema conflict, and buys you independent deployment. Eventual consistency costs you support tickets and reconciliation jobs, and buys you services that do not fail together. The correct default for a new system remains a modular monolith with one store, and the skill this unit is teaching is not enthusiasm for decomposition but the judgement to say, with numbers, when a specific boundary has earned its cost  and when it has not.

---

!!! question "Practice and interview questions"
    Questions for this topic are kept separately: [Practice questions](../Questions/unit4.md#41-microservices-design-principles) · [Interview questions](../interviewquestions/unit4.md#41-microservices-design-principles).

# Unit 4: Practice Questions

## 4.1 Microservices Design Principles

### Beginner Questions

1. Define a business capability and explain why capability-based boundaries are more stable than boundaries drawn from an application's existing module structure.

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** A business capability is something the business does, named in its own language (accept payment, manage inventory, price a product), independent of how it is implemented.
        - **Stability:** Capabilities persist for years while code, frameworks and team structures change, so a boundary drawn around a capability survives several internal rewrites.
        - **Module structure is technical:** Existing modules usually follow technical layers (controllers, validation, data access), so splitting along them makes every feature cross every service.
        - **Consequence:** Layer-based boundaries produce a distributed monolith: coordinated releases, synchronous chains and a shared database, with the cost of microservices and none of the independence.
        - **Ownership:** A capability maps naturally to one team and one exclusively owned data set, which gives high cohesion inside and low coupling between services.

2. State the database-per-service rule precisely, and explain why a second service reading  but never writing  another service's table still violates it.

    ??? success "Check your answer"

        A good answer covers:

        - **The rule:** Each service exclusively owns its data store; no other service reads or writes it directly, and others obtain the data only through the owner's API or events.
        - **Not an engine rule:** Own store does not mean own engine: two services may both use DynamoDB, each with its own tables.
        - **Why a read still violates it:** The reader depends on the physical schema (tables, columns, types), so the owner can no longer rename, migrate or change engine without breaking an unknown consumer.
        - **Invisible coupling:** The dependency appears in no contract and has no version, so it is as tight as a write dependency but far less visible.
        - **Remedy:** Expose an API, publish events or let the consumer keep a local projection, and enforce ownership with a per-service IAM role scoped to its own tables.

3. Explain the difference between a command and a domain event, giving one correctly named example of each from an e-commerce system.

    ??? success "Check your answer"

        A good answer covers:

        - **Command:** Names a recipient and asks for an action that has not yet happened, in the imperative: `ReserveInventory` or `CapturePayment`, typically a message on an SQS queue.
        - **Event:** States a past-tense fact without knowing who listens: `OrderPlaced` or `PaymentCaptured`, typically published to EventBridge or SNS.
        - **Coupling:** A command's sender must know the receiver and its contract; an event's publisher gains new consumers without changing or redeploying.
        - **Naming trap:** An 'event' named `SendEmail` is a command in disguise and carries all the coupling of a direct call.
        - **Error handling:** A failed command is the sender's concern and needs a reply path; a failed event consumer handles the failure in its own dead-letter queue.

4. Describe what a resolver is in AWS AppSync, and explain the difference between a unit resolver and a pipeline resolver.

    ??? success "Check your answer"

        A good answer covers:

        - **Resolver:** Code attached to one schema field that maps it to operations on a data source such as DynamoDB, Lambda, Aurora through the RDS Data API, OpenSearch, HTTP, EventBridge or `NONE`.
        - **Runtime:** Resolvers are written in APPSYNC_JS (preferred) or the older VTL mapping templates.
        - **Unit resolver:** A single request and response mapping against one data source.
        - **Pipeline resolver:** An ordered chain of functions sharing a stash, each of which can use a different data source, for example authorise then fetch.
        - **When to use each:** Unit for a simple one-source mapping; pipeline for multi-step logic such as authorisation checks or combining sources without writing a Lambda function.

5. A GraphQL query returns HTTP 200 with a `data` object containing a null field and a non-empty `errors` array. Explain what has happened and why this matters for monitoring.

    ??? success "Check your answer"

        A good answer covers:

        - **What happened:** The resolver for a nullable field failed; GraphQL returned `null` for that field and an entry in `errors` (with the field path) while the rest of the query succeeded.
        - **Partial success is normal:** GraphQL reports partial failures inside a successful HTTP 200 response by design.
        - **Monitoring blind spot:** Dashboards and alarms that count non-200 responses report perfect health while a feature is broken.
        - **Fix:** Create a CloudWatch metric filter on the AppSync log group for error entries, dimensioned by field path, and alarm on it.
        - **Design point:** Nullable non-essential fields let a screen degrade gracefully, but only if the client renders the null case and the failures are counted.

### Intermediate Questions

1. A team wants the orders service to store a `productName` field copied from the catalogue at order time. Another team argues this is denormalisation and the orders service should look up the name when needed. Argue both positions, then state which is correct and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Case for lookup:** A single source of truth, no duplicated data and no synchronisation work; the name is always current.
        - **Case for copying:** An order is a historical record of what the customer agreed to, and a copy removes a synchronous dependency on the catalogue when orders are read.
        - **Which is correct:** Copying: the name (and price) at order time is a snapshot, a correctness requirement, not denormalisation for performance.
        - **Caveat:** Copy only values that are part of the order's meaning; data that must be current (a product image, current stock) is referenced by ID or held in a projection.
        - **Principle:** Across a boundary prefer duplication to coupling; spotting values that should be snapshots removes many apparent cross-service dependencies.

2. Explain the N+1 problem in AppSync using a concrete query. Describe the two AWS mechanisms that solve it, what must change in the resolver code, and the production metric that reveals the problem.

    ??? success "Check your answer"

        A good answer covers:

        - **Example:** `listOrders { items { id customer { name } } }` returning 100 orders runs one resolver for the list and 100 for `customer`, so latency and cost grow with list size.
        - **Why it hides:** Development data has a handful of items, so the extra calls are imperceptible until production list sizes arrive.
        - **Mechanism 1: Lambda batching:** Use the `BatchInvoke` operation with `maxBatchSize` on the resolver, so AppSync sends many item contexts to one Lambda invocation.
        - **Mechanism 2: DynamoDB batching:** Use `BatchGetItem` so many keys are read in one call.
        - **Code change:** The Lambda function must accept an array of contexts and return an array of results in the same order (with per-item errors), so this is a rewrite, not just a setting.
        - **Production metric:** Resolver or Lambda invocations per request that scale with list size, visible in AppSync logs and as many identical short spans in traces.

3. Compare AWS AppSync and Amazon API Gateway across five dimensions: client shape, contract ownership, per-consumer control, real-time capability, and cost model. Give one scenario where each is clearly correct.

    ??? success "Check your answer"

        A good answer covers:

        - **Client shape:** AppSync: the client declares the fields it needs and one request aggregates several services. API Gateway: server-defined resources, one endpoint per call.
        - **Contract ownership:** AppSync: one schema, federated through Merged APIs with a source API per team. API Gateway: separate OpenAPI contracts per API, combined under a custom domain with base-path mappings.
        - **Per-consumer control:** API Gateway REST has API keys, usage plans, quotas and request validation; AppSync has no usage-plan equivalent.
        - **Real-time:** AppSync has managed WebSocket subscriptions bound to mutations; API Gateway needs a separate WebSocket API where you manage connections yourself.
        - **Cost model:** AppSync charges per query or mutation, per subscription message and per connection-minute; API Gateway charges per request (REST more than HTTP), both plus optional cache hours.
        - **Scenarios:** API Gateway REST for hundreds of metered partner integrations; AppSync (Merged API) for your own mobile app whose screens combine data from several services.

4. Describe the transactional outbox pattern as implemented on DynamoDB and as implemented on Aurora. State precisely which failure mode it eliminates, what new obligation it creates for consumers, and why a retry cannot substitute for it.

    ??? success "Check your answer"

        A good answer covers:

        - **On DynamoDB:** Write the item; DynamoDB Streams captures the change and a Lambda function on the stream publishes to EventBridge, so the stream record is the outbox.
        - **On Aurora:** Insert the business row and an `outbox` row in one local transaction; a poller or AWS DMS change data capture reads committed rows, publishes and marks them published.
        - **Failure eliminated:** The dual write: a crash between the database commit and the publish (or a publish followed by a rollback) that leaves state and event stream disagreeing.
        - **New obligation:** Publication becomes at-least-once (the publisher can crash after publishing but before marking), so every consumer must be idempotent; publisher lag must also be monitored.
        - **Why retry cannot substitute:** The retry state lived in the process that crashed; nothing durable records that a publication is owed, so no retry ever happens.

5. A system has eight microservices and finance requires a monthly report joining data from six of them. Three solutions are proposed: grant the reporting service read access to six databases; have the reporting service call six APIs and join in memory; replicate all six services' data into a warehouse. Evaluate each and recommend one.

    ??? success "Check your answer"

        A good answer covers:

        - **Option 1: direct read access:** Recreates the shared-database problem six times: owners can no longer change schemas and heavy report queries load operational stores. Reject.
        - **Option 2: six APIs joined in memory:** Respects ownership but is slow, loads operational services with bulk reads they were not designed for, and joins data captured at different moments. Acceptable only for small volumes.
        - **Option 3: warehouse replication:** The analytical plane: zero-ETL integrations into Redshift, or events landed in S3 and queried with Athena; built for joins, with no coupling to operational traffic.
        - **Recommendation:** Option 3, because a monthly report tolerates replication lag and nobody reads another service's operational tables.
        - **Caveat:** Replicate published events or agreed datasets rather than raw internal schemas where possible, and apply the same classification and access control to the warehouse.

### Advanced Questions

1. You are handed a nine-year-old insurance monolith and asked to produce a decomposition plan. Write the plan. It must specify the discovery method and its artefacts, at least six candidate boundaries with the criterion that justified each, the data ownership of each, which operations must remain atomic and why, the extraction sequence with a justification for the first extraction, and the three measurements you would use after six months to determine whether the boundaries were correct.

    ??? success "Check your answer"

        A good answer covers:

        - **Discovery and artefacts:** Event storming with domain experts (event map, aggregates, pivotal events), a capability map, and evidence from Git co-change analysis and Application Discovery Service dependencies; outputs are a data-ownership table and an atomicity analysis.
        - **Candidate boundaries with criteria:** For example: Product and Rating (core subdomain, high volatility), Quotation (pivotal event: quote to policy), Policy Administration (the policy aggregate), Billing and Payments (compliance scope, own account), Claims (distinct language and process), Correspondence and Documents (generic, different scaling profile), plus identity delegated to a managed service.
        - **Data ownership:** Each candidate owns its store, chosen by access pattern (for example Aurora for policy transactions, DynamoDB for rating tables, S3 for documents); others use APIs, events or projections.
        - **What stays atomic:** Operations the business will not accept compensating, such as issuing a policy with its coverages and premium schedule, stay inside one service; where such an operation spans two candidates, they merge.
        - **Extraction sequence:** Strangler fig behind API Gateway or an ALB; first extract a low-risk, high-learning, loosely coupled capability such as correspondence, to build the pipeline and confidence before touching the core policy aggregate.
        - **Six-month measures:** Co-change rate (features touching more than one service), deployment frequency and lead time per service, and synchronous calls per request or cross-service incidents from traces.

2. Design the complete API and data topology for a company with five product teams, a web client, an iOS client, forty partner integrations and a PCI-scoped payments capability. Specify the edge for each audience, the federation mechanism, the store per service with a justification from access pattern, the event contracts including what may not appear in a payload, and the reconciliation jobs you would build on day one. Then state the three most likely ways this design degrades over two years and what you would put in place now to detect each.

    ??? success "Check your answer"

        A good answer covers:

        - **Edge per audience:** Web and iOS: an AppSync Merged API behind CloudFront and WAF with Cognito. Forty partners: an API Gateway REST API with API keys, usage plans, request validation, versioned paths and a real authoriser.
        - **Federation:** Each of the five teams owns a source API (auto-merge) and its own base-path mapping, so no central team owns 'the API'.
        - **Store per service:** Chosen from the access pattern, for example DynamoDB for key-shaped catalogue and inventory, Aurora Serverless v2 for transactional ordering, and payments in its own PCI-scoped account.
        - **Event contracts:** Past-tense domain events in the EventBridge schema registry, published through outbox or Streams, one SQS queue and DLQ per consumer; no cardholder data and only identifiers for personal data (thin events), changed additively.
        - **Day-one reconciliation:** Orders against payments, reservations against order lines and read models against their sources, each producing a divergence metric with an alarm.
        - **Likely degradations and detection:** Re-centralisation of the edge (track lead time to add a field), shared-data and synchronous creep (review IAM policies and compare the trace service map with the design), and sensitive fields entering events (schema contract tests in the pipeline).

3. A team reports that a decomposition completed eighteen months ago has made delivery slower rather than faster: most features touch three or more services, p99 latency has tripled, and two incidents in the last quarter took over an hour to diagnose. You have access to the Git history, the X-Ray service map, the IAM policies and the event schemas. Describe your investigation in order, the specific evidence you would gather from each source, the three most likely root causes, and  for the most likely one  the remediation plan including what you would merge back and how you would justify that to a team that spent eighteen months splitting it.

    ??? success "Check your answer"

        A good answer covers:

        - **Investigation order:** Git history first (where change actually lands), then the X-Ray service map and traces, then IAM policies, then event schemas, forming hypotheses before proposing fixes.
        - **Evidence from each source:** Git: which services co-change per feature. Traces: synchronous chains, N+1 fan-out, layered retries and broken propagation at async hops. IAM: roles that reach other services' tables or shared roles. Schemas: commands disguised as events and thick events that couple consumers.
        - **Three likely root causes:** Boundaries drawn on technical layers or through an aggregate; chatty synchronous coupling; and shared data or shared artefacts (library, schema, central API).
        - **Remediation for the most likely (wrong boundaries):** Merge services that co-change in most tickets into one service with one store and pipeline, replace hot-path synchronous calls with local projections, and fix trace propagation across async hops.
        - **Justification:** Present the data: co-change rates, lead time, p99 and incident diagnosis time before and after. Frame it as correcting a boundary; the pipelines, observability and skills built over eighteen months remain.

4. Critique the following proposal: "We will build one AppSync API owned by the platform team, with all resolvers as Lambda functions. Each Lambda will query whichever service databases it needs directly, for performance. Domain events will be published by each service calling `PutEvents` after its database write. All services will share one Aurora cluster with a schema per service, to save cost. Reporting will read from a read replica of that cluster." Identify at least six distinct defects, rank them by the severity and reversibility of the damage, propose a corrected design, and state which parts of the original you would keep.

    ??? success "Check your answer"

        A good answer covers:

        - **Defect: resolvers read service databases directly:** Shared-database coupling across every service; the most severe and hardest to reverse as consumers accumulate.
        - **Defect: one shared Aurora cluster with a schema per service:** Shared capacity, failover and maintenance; not database-per-service.
        - **Defect: `PutEvents` after the database write:** A dual write that silently loses events on a crash; replace with an outbox or change data capture.
        - **Defect: one AppSync API owned by the platform team:** Every team queues to add a field; use a Merged API with source APIs per team.
        - **Defects: reporting on a read replica, and all resolvers as Lambda:** The replica couples reporting to every schema and loads the shared cluster; Lambda everywhere adds cost, cold starts and N+1 risk where direct data sources would do.
        - **Ranking, corrected design and what to keep:** Data coupling and the shared cluster first, dual write next, then edge ownership, reporting and Lambda resolvers. Correct to store per service, outbox to EventBridge, idempotent consumers and an analytical plane. Keep AppSync as the first-party edge, Aurora where the access pattern fits, Lambda for real logic and EventBridge for events.

5. A business requires that a customer sees their newly placed order in their order history immediately, with no stale window, and separately requires that the ordering and history capabilities be owned by different teams with independent release cadences. Analyse the tension between these two requirements. Present at least three technically valid resolutions with their trade-offs, state which you would recommend and why, and describe the conversation you would have with the business if none of the three is acceptable to them.

    ??? success "Check your answer"

        A good answer covers:

        - **The tension:** Separate owners with independent releases imply separate stores and eventual consistency, but 'no stale window' demands read-your-writes across that boundary.
        - **Resolution 1: optimistic client:** The ordering response returns the new order and the client shows it as pending until the history projection catches up; no backend coupling, but the guarantee holds only in that client session.
        - **Resolution 2: composition at read time:** History serves its projection plus a synchronous call to ordering for orders newer than its watermark; correct, but adds a runtime dependency and latency.
        - **Resolution 3: move ownership:** Recent orders are served by the ordering service (or history becomes part of ordering); strongly consistent, but reduces the history team's independence.
        - **Recommendation:** Usually resolution 1, possibly with 2 for other devices, because it meets the user-visible requirement without coupling the teams' releases.
        - **If none is acceptable:** Explain to the business that the two requirements conflict, price each option, and ask which they value more; strict consistency usually means one owner, and that is a business decision.

---

## 4.2 API Management and Service Mesh

### Beginner Questions

1. Distinguish north–south traffic from east–west traffic, and name the primary AWS instrument for each.

    ??? success "Check your answer"

        A good answer covers:

        - **North–south:** Traffic entering or leaving the system from clients you do not operate: browsers, mobile apps, partner systems.
        - **East–west:** Traffic between your own services, inside your own trust domain.
        - **North–south instrument:** Amazon API Gateway, usually with CloudFront, WAF and Cognito.
        - **East–west instruments:** ECS Service Connect inside ECS, Amazon VPC Lattice across VPCs, accounts and compute types, with Cloud Map as the registry underneath.
        - **Keep them separate:** Routing internal calls through the gateway adds cost, latency and quota pressure and mixes internal calls into customer metrics.

2. List four capabilities that an Amazon API Gateway REST API provides and an HTTP API does not, and give one scenario in which each is decisive.

    ??? success "Check your answer"

        A good answer covers:

        - **API keys and usage plans:** Decisive when partners on commercial tiers need per-consumer rate limits and monthly quotas.
        - **Request validation:** Decisive when malformed partner payloads must be rejected against a JSON Schema before they cost compute.
        - **Caching:** Decisive for repeated reads of slowly changing data, such as a product catalogue, at stage level.
        - **Private endpoint with resource policy:** Decisive when an internal API must be reachable only through specific interface VPC endpoints.
        - **Other valid answers:** Direct WAF association (an HTTP API needs CloudFront in front), canary release settings on a stage, and VTL mapping templates.

3. Explain the difference between an API key and an authorizer in API Gateway, and state what is wrong with protecting a method with an API key alone.

    ??? success "Check your answer"

        A good answer covers:

        - **API key:** A static string that identifies a consumer for usage plans: metering, throttling and quotas.
        - **Authoriser:** Authenticates the caller and can authorise the request: IAM (SigV4), Cognito user pools, JWT (HTTP APIs) or a Lambda authoriser.
        - **What is wrong with a key alone:** A key is not a credential: it travels in a header, can be extracted from any client and carries no user identity, so the method is effectively public.
        - **Correct pattern:** Use the key for metering and a real authoriser for identity; never leave a mutating method on `NONE` authorisation.

4. Describe what AWS Cloud Map stores, and explain one thing it can do that a DNS record cannot.

    ??? success "Check your answer"

        A good answer covers:

        - **What it stores:** Namespaces (public DNS, private DNS or API-only), services, and service instances with IP, port, health status and custom attributes such as `VERSION=2.1`.
        - **Registration:** ECS registers and deregisters tasks automatically; health comes from Route 53 health checks or a custom health status.
        - **Beyond DNS:** `DiscoverInstances` can filter by health and custom attributes (for example only version 2.1 instances), whereas DNS returns only addresses and expresses health only by removing records.
        - **Caveat:** Cloud Map does no load balancing or retries; cache lookups or let a proxy use it, rather than calling it per request.

5. Define a service mesh in terms of its data plane and control plane, and state what happens to existing traffic if the control plane becomes unavailable.

    ??? success "Check your answer"

        A good answer covers:

        - **Data plane:** Proxies (usually Envoy), often sidecars, that sit on the request path and apply mTLS, timeouts, retries, routing and telemetry.
        - **Control plane:** Computes configuration from declared resources and pushes it to the proxies (xDS); it is not on the request path.
        - **Control plane failure:** Existing traffic keeps flowing, because each proxy keeps its last-known configuration.
        - **What is lost:** The ability to change routing or policy and to learn about new endpoints until the control plane returns.

### Intermediate Questions

1. A team routes all internal service-to-service traffic through API Gateway for consistency and observability. Give four concrete reasons this is wrong, and describe what you would offer instead that satisfies both of their stated motivations.

    ??? success "Check your answer"

        A good answer covers:

        - **Cost:** Per-request pricing on high-volume internal traffic can exceed the cost of the compute behind it.
        - **Latency and failure domain:** Every internal call gains a hop and the gateway's overhead, compounding along chains, and a gateway misconfiguration now breaks internal traffic too.
        - **Quotas:** Internal traffic consumes account-level throttling limits meant for customers, so an internal spike can throttle external callers.
        - **Observability gets worse:** Internal calls are mixed into customer metrics, and the gateway does not know which internal service made a call.
        - **Offer instead:** Consistency through Service Connect inside ECS and VPC Lattice across boundaries, configured from shared IaC modules; observability from their per-caller, per-callee metrics plus end-to-end traces.

2. Explain why DNS-based service discovery is inadequate for a service whose tasks are replaced many times per hour. Describe the failure precisely, name two AWS mechanisms that avoid it, and explain what each does that DNS does not.

    ??? success "Check your answer"

        A good answer covers:

        - **The failure:** Clients cache resolved IPs, often beyond the TTL and sometimes for the process lifetime; when tasks are replaced, traffic keeps going to dead or reassigned addresses, causing errors after every deployment.
        - **Other gaps:** DNS carries no metadata and expresses health only by removing records, which cached clients notice late.
        - **ECS Service Connect:** A managed local proxy receives endpoint changes from the control plane and load-balances client-side with outlier ejection, so no client DNS cache is involved.
        - **Amazon VPC Lattice:** Callers use a stable service name and Lattice routes to currently healthy targets in the VPC data plane, so target churn is invisible to clients.
        - **Also valid:** Cloud Map `DiscoverInstances` with health filtering and short client-side caching.

3. AWS App Mesh reached end of support on 30 September 2026. For each of the following uses, name the successor and justify it: in-ECS discovery and load balancing; weighted canary routing; mTLS between services; cross-account service calls; header-based routing with fault injection.

    ??? success "Check your answer"

        A good answer covers:

        - **In-ECS discovery and load balancing:** ECS Service Connect: Cloud Map registration, managed proxy, client-side balancing and per-caller metrics.
        - **Weighted canary routing:** Inside ECS, the native ECS canary or linear deployment strategies, which shift Service Connect traffic between service revisions; across boundaries, VPC Lattice weighted target groups; on EKS, Istio route weights.
        - **mTLS between services:** Istio or Linkerd on EKS with a chosen CA such as AWS Private CA; Lattice offers IAM (SigV4) caller authentication over TLS as the AWS-native alternative.
        - **Cross-account service calls:** VPC Lattice: a service network shared through AWS RAM with IAM auth policies.
        - **Header routing with fault injection:** Istio on EKS, because Lattice has header matching but no fault injection, and Service Connect matches headers only to route deployment test traffic.
        - **Principle:** Migrate by traffic path, not by mapping App Mesh resources one-for-one.

4. A Lambda authorizer has increased an API's p99 latency from 120 ms to 900 ms. Explain the mechanism, describe how you would confirm it from CloudWatch metrics alone, and give three distinct remediations.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** The authoriser runs on every request (caching off, TTL zero, or an identity source that varies per request), so its duration and cold starts are added to each request's latency.
        - **Confirm from metrics:** API Gateway `Latency` rose while `IntegrationLatency` did not; the authoriser function's `Invocations` roughly equal the API's request `Count`; its `Duration` p99 and cold starts line up with the API p99.
        - **Remediation 1:** Enable authoriser result caching with a TTL chosen from the token-revocation requirement, and make sure the identity source is the token, not a per-request value.
        - **Remediation 2:** Replace a Lambda authoriser that only validates standard tokens with a native Cognito or JWT authoriser.
        - **Remediation 3:** Make the function cheaper: no VPC attachment unless needed, a small package, JWKS keys cached outside the handler, and provisioned concurrency if cold starts remain.

5. Compare Amazon VPC Lattice, AWS PrivateLink and VPC peering as mechanisms for connecting services across accounts. State the situation in which each is correct, and explain how overlapping CIDR ranges affect each of the three.

    ??? success "Check your answer"

        A good answer covers:

        - **VPC Lattice:** Many-to-many, service-level connectivity across VPCs, accounts and compute types, with IAM auth policies and L7 routing; correct for many services across many accounts.
        - **AWS PrivateLink:** One service exposed through an NLB endpoint service to consumers via interface endpoints, one direction; correct for publishing a single service to many consumer VPCs or third parties.
        - **VPC peering:** A non-transitive layer 3 link between two VPCs; correct for a few VPCs that need broad IP-level connectivity.
        - **Overlapping CIDRs:** Peering (like Transit Gateway) routes by IP address, so overlapping ranges rule it out; Lattice does not route at layer 3, so overlap does not matter.
        - **PrivateLink:** tolerates overlap, because consumers reach the service through endpoint addresses in their own VPC; in a many-to-many estate it is ruled out by scale (an endpoint per service per consumer), not by addressing.

### Advanced Questions

1. Design the complete north–south and east–west topology for a retailer with a public API used by 400 partners on three commercial tiers, a mobile application, and 60 internal services split across ECS and EKS in four AWS accounts. Specify the API type and endpoint configuration for each audience with justification, the federation mechanism that prevents one team owning "the API", the east–west mechanism for each traffic path, and the specific observability artefacts you would build. Then state three things you deliberately would *not* build and defend each.

    ??? success "Check your answer"

        A good answer covers:

        - **Partners on three tiers:** API Gateway REST, regional endpoint behind CloudFront and WAF, one usage plan per tier with API keys plus a real authoriser (or mTLS on the custom domain), request validation, versioned paths, canary stages and a VPC link to private backends.
        - **Mobile application:** AppSync Merged API, or an HTTP API with a JWT authoriser for simple calls, behind CloudFront and WAF with Cognito.
        - **Federation:** A custom domain with base-path mappings per team and Merged API source APIs owned per team, so no team owns 'the API'.
        - **East–west:** Service Connect within ECS clusters, Kubernetes Services within EKS, and VPC Lattice shared through RAM across the four accounts with IAM auth policies (Gateway API Controller on EKS); facts travel by EventBridge and SQS.
        - **Observability artefacts:** End-to-end trace propagation (OpenTelemetry through ADOT into X-Ray or Application Signals), one JSON access-log format, a caller-by-callee dashboard, usage per API key per version, and alarms on 429s and auth denials.
        - **Deliberately not built:** No API Gateway for internal traffic (cost, quotas, polluted metrics); no full service mesh (no named requirement, high standing cost); no per-pair internal load balancers or public backends.

2. A platform team proposes: "We will install Istio on all six EKS clusters with sidecar injection everywhere, strict mTLS, retries of three at the mesh layer, outlier detection with default settings, and route all internal HTTP traffic through it. We will also put API Gateway in front of every service so all traffic is observable in one place." Identify at least six distinct defects, rank them by the severity and reversibility of the damage, propose a corrected design, and state which parts of the original proposal you would keep and why.

    ??? success "Check your answer"

        A good answer covers:

        - **Defects:** API Gateway in front of every service; sidecars everywhere with no named requirement; strict mTLS from day one; mesh retries stacked on SDK and application retries; outlier detection without a tuned ejection cap; no timeouts or retry budgets that fit caller deadlines; and the belief that a gateway gives east–west visibility.
        - **Ranking:** Retry multiplication, uncapped ejection and premature strict mTLS cause outages (severe but reversible by configuration); gateway-everywhere and sidecar-everywhere add permanent cost and become entrenched (moderate severity, hard to reverse).
        - **Corrected design:** Mesh only on clusters with a named requirement (ambient mode where possible); mTLS permissive, then enrol, negative test, then strict; retries in one layer under a budget, only for idempotent calls, with timeouts inside deadlines; maximum ejection capped well below half; API Gateway for north–south only.
        - **Observability:** Use mesh telemetry per caller and callee plus traces, which see east–west identity that a gateway cannot.
        - **What to keep:** Istio on EKS where justified, the goal of mutual authentication, and tuned outlier detection, because each addresses a real need.

3. Your organisation has decided on "zero trust between services". Define what that means concretely on AWS in terms of authentication, authorisation, encryption and audit; specify the implementation for an estate running ECS, EKS and Lambda across twelve accounts; describe the migration sequence and the specific hazards at each step; and state clearly what this programme will *not* achieve, so that the security committee's expectations are correctly set.

    ??? success "Check your answer"

        A good answer covers:

        - **Authentication:** Every call proves its caller cryptographically: SigV4 with per-service IAM roles (task roles, EKS Pod Identity, Lambda execution roles) through VPC Lattice, or mTLS with AWS Private CA certificates in a mesh.
        - **Authorisation:** Policies naming principal, path and method (Lattice auth policies, Istio `AuthorizationPolicy`), plus resource policies on data stores, instead of CIDR rules.
        - **Encryption and audit:** TLS on every hop and KMS at rest; Lattice access logs, mesh logs and CloudTrail centralised so every call's caller identity is reviewable.
        - **Implementation across twelve accounts:** Organizations with SCPs, a Lattice service network per environment shared through RAM, the Gateway API Controller on EKS, Lambda as Lattice targets, and one IAM role per service.
        - **Migration sequence and hazards:** Split shared roles (hazard: hidden callers), enrol services with permissive policies and logging, derive policies from observed access, then tighten per service with denial alarms and staged rollout (hazard: legitimate callers denied); switch mesh mTLS to strict only after a negative test.
        - **What it will not achieve:** It does not stop a compromised service acting within its permissions, application vulnerabilities, over-broad data permissions or insider misuse; it limits lateral movement and makes access auditable.

4. A partner-facing API must support a breaking change to its response schema. Four hundred integrators depend on it, you cannot force them to upgrade, and two of them are contractually guaranteed twelve months' notice. Design the versioning, deployment, measurement and deprecation strategy using API Gateway capabilities. Explain how you would know when it is safe to retire the old version, what you would do about an integrator who has not migrated at the deadline, and how the design differs from what you would do for a first-party mobile client.

    ??? success "Check your answer"

        A good answer covers:

        - **Versioning:** Publish the breaking change as a new major version (`/v2`) on the custom domain through a base-path mapping or separate stage, contract-first in OpenAPI, leaving v1 unchanged.
        - **Deployment:** Run v1 and v2 in parallel, use canary stage settings for v2 changes, and serve both from the backend through an adapter where possible.
        - **Measurement:** Access logs carrying API key ID and version, giving usage per key per version on a dashboard.
        - **Deprecation and retirement:** Announce the timeline (at least twelve months for the two contractual partners), signal it in responses and documentation, contact every key still calling v1, and retire only when v1 traffic is zero or limited to keys that have agreed, for a sustained period.
        - **Integrator not migrated at the deadline:** A commercial decision, not a silent switch-off: a negotiated extension on its own usage plan, a paid extended-support arrangement, or an adapter.
        - **First-party mobile contrast:** You control the client, so prefer additive change, feature flags and a minimum-supported-version check, with a shorter window that still covers app versions in the field.

5. An incident review finds that a 90-second latency increase in one internal service produced a 40-minute full outage that persisted for 20 minutes after the original service had recovered. The estate uses a service mesh. Explain the mechanism in detail, identify every configuration defect that must have been present for this outcome to occur  covering retries, timeouts, outlier detection, connection pools and throttling  and specify the changes, with concrete settings, that would have bounded the incident to a degraded 90 seconds.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** A metastable failure: latency causes timeouts, layered retries multiply load, outlier detection ejects endpoints and concentrates load on the rest, connection pools saturate, and the retry backlog sustains overload after the original cause has gone.
        - **Retries:** Present at mesh and application layers with no budget and no jitter. Fix: one layer, at most two attempts, full jitter, a retry budget of about 10 per cent of requests, idempotent calls only.
        - **Timeouts:** Absent or longer than the caller's deadline. Fix: per-try timeout near the dependency's p99 plus a margin, total time inside the caller's budget, and deadline propagation.
        - **Outlier detection:** No ejection cap, so the whole fleet was ejected. Fix: maximum ejection around 20 to 30 per cent, a base ejection time of tens of seconds, and a consecutive-error threshold of about five.
        - **Connection pools:** Unbounded or shared, so callers queued indefinitely. Fix: per-destination maximum connections and pending requests sized from measured concurrency, failing fast when full.
        - **Throttling and shedding:** None at the callee. Fix: a concurrency limit or throttle derived from measured capacity returning 429 with `Retry-After`, so the incident is a degraded 90 seconds followed by immediate recovery.

---

## 4.3 Resilience in AWS Microservices

### Beginner Questions

1. Explain why every outbound network call needs a timeout, and describe precisely what happens to a service that calls a hung dependency without one.

    ??? success "Check your answer"

        A good answer covers:

        - **Why:** A remote call can hang indefinitely; a timeout bounds how long the caller holds resources for it.
        - **Without one:** Each request to the hung dependency holds a thread and a connection; under load every thread ends up waiting on that dependency.
        - **Consequence:** The caller stops serving all traffic, including requests that never touch the failing dependency, and the failure cascades to its own callers.
        - **How to set it:** A short connection timeout, a request timeout above the dependency's p99, and a total including retries that fits inside the caller's deadline.

2. Define exponential backoff and full jitter. Explain what goes wrong if you use backoff without jitter across a fleet of clients.

    ??? success "Check your answer"

        A good answer covers:

        - **Exponential backoff:** The wait before each retry grows exponentially (`base * 2 ** attempt`), up to a cap.
        - **Full jitter:** The actual wait is chosen at random between zero and that value: `random(0, min(cap, base * 2 ** attempt))`.
        - **Without jitter:** Clients that failed together retry at the same instants, so synchronised waves hit the recovering dependency and keep it overloaded.
        - **Effect:** Jitter spreads retries across the interval; in Step Functions it must be set explicitly with `JitterStrategy: FULL`.

3. Describe the three states of a circuit breaker and explain what specifically goes wrong if the half-open state is omitted.

    ??? success "Check your answer"

        A good answer covers:

        - **Closed:** Calls pass through and failures are counted within a window.
        - **Open:** Once failures exceed the threshold, calls fail immediately (or use a fallback) for a cooldown, giving the dependency room to recover and the caller a fast failure.
        - **Half-open:** After the cooldown a few trial requests pass; success closes the breaker, failure reopens it.
        - **Without half-open:** The breaker cannot recover on its own: it becomes a kill switch that stays open until manually reset, or it closes blindly and floods a dependency that has not recovered.

4. State the purpose of an SQS dead-letter queue and explain what happens to a persistently failing message on a FIFO queue that has no DLQ configured.

    ??? success "Check your answer"

        A good answer covers:

        - **Purpose:** Receives messages that have failed `maxReceiveCount` times, so a poison message is isolated, the queue keeps flowing, and the message is kept for investigation and redrive.
        - **FIFO without a DLQ:** The failing message keeps reappearing after each visibility timeout and, because order is strict within a message group, nothing behind it in that group is processed.
        - **How long:** The group stays blocked until the message is fixed by hand or expires at the end of the retention period (up to 14 days), which then loses it silently.
        - **Worst case:** If the message group ID is a constant, the whole queue stalls.
        - **Operating a DLQ:** Alarm on depth greater than zero, a named owner, 14-day retention and a tested redrive.

5. Explain why every consumer of an SQS queue must be idempotent, and describe one correct implementation using Amazon DynamoDB.

    ??? success "Check your answer"

        A good answer covers:

        - **Why:** SQS standard queues deliver at least once, and visibility-timeout expiry, a crash after the work but before deletion, or whole-batch redelivery all cause duplicates; FIFO deduplication covers only a five-minute window.
        - **Definition:** Processing a message twice has the same effect as processing it once.
        - **DynamoDB implementation:** Write a record keyed by a stable, caller-supplied key (such as `orderId`) with `ConditionExpression: attribute_not_exists(pk)`; if the condition fails, it is a duplicate, so skip it or return the stored result.
        - **Housekeeping:** Store the result and a TTL on the record; Powertools for AWS Lambda provides this pattern, including in-progress state.
        - **Key rule:** The key must come from the message, never a UUID generated in the handler.

### Intermediate Questions

1. A Lambda function consuming an SQS queue occasionally processes the same message twice. Give three distinct possible causes, describe how you would distinguish between them from CloudWatch metrics and message attributes, and state the fix for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Cause 1: visibility timeout shorter than processing:** The message reappears while the first invocation is still running. Evidence: same message ID, `ApproximateReceiveCount` above 1, function `Duration` near the visibility timeout. Fix: visibility timeout at least six times the function timeout.
        - **Cause 2: whole-batch redelivery:** Without `ReportBatchItemFailures`, one failing message returns the whole batch. Evidence: same message IDs, duplicates coinciding with function `Errors`. Fix: enable partial batch responses.
        - **Cause 3: duplicate publication upstream:** An outbox republish, standard-queue duplication or two rules targeting the queue. Evidence: different message IDs carrying the same business key, receive count 1. Fix: correct the publisher where possible.
        - **Durable fix for all three:** Make the consumer idempotent on a business key with a conditional write, and count suppressed duplicates as a metric.

2. Explain the bulkhead pattern and describe three distinct AWS implementations. For each, state precisely what it isolates and what it does not.

    ??? success "Check your answer"

        A good answer covers:

        - **Bulkhead:** Partitioning resources so that exhausting one partition cannot sink the others.
        - **Lambda reserved concurrency:** Isolates a function's concurrency from the shared account pool (cap and guarantee); does not isolate shared downstream resources such as database connections.
        - **Per-consumer SQS queues:** SNS or EventBridge fan-out to one queue per consumer isolates each backlog, DLQ and scaling; does not isolate a shared downstream dependency or the producer.
        - **Per-dependency connection pools:** Separate clients or Envoy per-cluster limits stop one slow dependency taking every connection; do not isolate the process's CPU and memory or account quotas.
        - **Also valid:** Cells, AZs and separate accounts isolate infrastructure and quotas, but not a shared deployment pipeline or configuration.

3. Compare a Step Functions `Retry` block with retry logic written inside a Lambda function. Give three advantages of the declarative approach and one situation in which in-function retry is still correct.

    ??? success "Check your answer"

        A good answer covers:

        - **Durability:** Retries are recorded state transitions that survive a crash or timeout of the function; in-function retry state dies with the invocation.
        - **Visibility:** Every attempt and error appears in the execution history, which helps during an incident.
        - **Consistency and cost:** Backoff, cap, jitter and error matching are configuration rather than code, and you do not pay a Lambda function to sleep between attempts; they also cover invocation-level failures such as throttling that function code cannot catch.
        - **When in-function retry is still right:** Short, fine-grained retries of a sub-call inside one step, such as the AWS SDK's built-in retry of a throttled DynamoDB call, or a function not orchestrated by Step Functions.
        - **Cost note:** Standard workflow retries are billed as state transitions.

4. A team enables retries in their service mesh, in the AWS SDK, and in their application code. Explain the consequence quantitatively, describe how the problem would present during an incident, and state what you would change.

    ??? success "Check your answer"

        A good answer covers:

        - **Quantitative effect:** Layers multiply: three attempts at each of three layers is 3 x 3 x 3 = 27 requests per logical call (4 x 4 x 4 = 64 if each layer makes three retries after the first try).
        - **How it presents:** A brief slowdown turns into overload; request rate at the dependency climbs as errors rise; traces show many attempts per request; the outage continues after the original cause ends.
        - **Change: one layer:** Retry at exactly one layer (usually closest to the failure) and explicitly disable the others, for example SDK `max_attempts` set to 1.
        - **Change: bound it:** Full jitter, a retry budget, total retry time inside the caller's deadline, and a circuit breaker.

5. Design a chaos experiment to validate that an order-processing pipeline survives the loss of its payment provider. Specify the steady state, the hypothesis, the FIS action and targets, the blast radius, the stop condition, and what result would falsify the hypothesis.

    ??? success "Check your answer"

        A good answer covers:

        - **Steady state:** User-facing measures: order completion rate (for example at least 99 per cent of accepted orders complete), checkout p99 latency and no duplicate charges in reconciliation.
        - **Hypothesis:** If the payment provider fails or hangs, the breaker opens within seconds, orders are held as pending payment rather than lost, unrelated checkout requests are unaffected, and the backlog drains when the provider returns.
        - **FIS action and targets:** Inject latency or errors on the provider call, for example Lambda invocation delay or error actions on the payment function, or ECS task network latency or blackhole actions, targeted by a tag such as `ChaosReady=true`.
        - **Blast radius:** Pre-production first; in production `COUNT(1)` or a small percentage of tagged targets for a few minutes.
        - **Stop condition:** CloudWatch alarms on customer harm: checkout errors, order completion rate or latency, not on the injected fault.
        - **Falsifying result:** Completion rate below threshold, unrelated requests failing (thread exhaustion), lost orders, duplicate charges, or a backlog that does not drain after the fault stops.

### Advanced Questions

1. An incident review shows that a 60-second latency increase in a single downstream service produced a 90-minute full outage that continued for 35 minutes after the downstream service had fully recovered. Explain the mechanism in detail. Identify every configuration defect that must have been present  covering timeouts, retries, jitter, budgets, breakers, bulkheads, load shedding and deadline propagation  and specify each remediation with concrete settings. Then describe the chaos experiment you would add to ensure the fix does not silently regress.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** A metastable failure: timeouts trigger synchronised, layered retries that multiply load; overload sustains the latency; the retry backlog keeps the dependency down long after its own cause has gone.
        - **Timeouts, retries, jitter, budgets:** Per-try timeout near the dependency's p99 plus a margin, total inside the caller's deadline; retries at one layer only, at most two attempts, full jitter, and a budget of about 10 per cent of requests.
        - **Breakers and bulkheads:** A breaker that opens at a measured failure ratio (for example 50 per cent over at least 20 calls in 10 seconds) with a cooldown of tens of seconds and a half-open trial; separate connection pools or reserved concurrency per dependency.
        - **Load shedding and deadlines:** A concurrency limit or throttle from measured capacity returning 429 with `Retry-After`; a deadline header set at the edge and decremented per hop so expired work is rejected.
        - **Structural fix:** Replace the synchronous dependency with a queue where the caller does not need the answer immediately.
        - **Regression guard:** A recurring FIS experiment injecting latency into that dependency for about a minute, hypothesis 'degraded during the fault, recovered within a minute after', stop conditions on customer-harm alarms, run in pre-production on each release and in production regularly.

2. Design the complete resilience strategy for a payment-processing system spanning six services, one third-party provider, and a regulatory requirement that no payment may be lost or duplicated. Specify which interactions are synchronous and why; the retry, timeout, breaker and bulkhead configuration for each; the saga and its compensations including which steps cannot be compensated and how you order around that; the idempotency strategy including how the key reaches the provider; the reconciliation jobs; and the chaos experiments. State explicitly what you would tell the regulator about the failure modes that remain.

    ??? success "Check your answer"

        A good answer covers:

        - **Synchronous only where required:** Only payment acceptance or authorisation, where the customer needs an answer; everything else (ledger, settlement, notifications) is asynchronous through an outbox, EventBridge and per-consumer SQS queues with DLQs.
        - **Per-interaction protection:** Timeouts from measured p99 inside the deadline; one-layer jittered retries only for idempotent calls carrying keys; a shared-state breaker in DynamoDB for the provider with a queued fallback; separate queues, pools and reserved concurrency for provider calls.
        - **Saga:** Step Functions Standard orchestration (for example validate, authorise, record in ledger, capture, notify) with `Catch` to idempotent compensations (void authorisation, refund, reversing ledger entry); irreversible steps such as capture, external transfer and notification go last.
        - **Idempotency:** A client-supplied payment ID used as the key end to end, enforced with conditional writes and passed to the provider's idempotency mechanism so a retry after an ambiguous timeout cannot charge twice.
        - **Reconciliation and chaos:** Continuous matching of internal ledger, orders and provider settlement reports with divergence alarms and a status query for unknown outcomes; FIS experiments for provider latency, task loss, database failover and AZ loss.
        - **What to tell the regulator:** Ambiguous outcomes and provider outages are delayed and resolved by reconciliation within a stated window, not lost; correlated Regional failure and operator error remain risks, with test and audit evidence for each control.

3. A SaaS platform serves 4,000 tenants through shared queues and shared Lambda functions. Two incidents in the last quarter were caused by a single large tenant's workload degrading service for everyone. Design the isolation strategy. Cover work distribution, compute concurrency, data partitioning, and the observability required to detect the next occurrence before customers do. Explain the cost implications, describe how you would decide how many isolation tiers to build, and state what you would do differently if there were 40 tenants rather than 4,000.

    ??? success "Check your answer"

        A good answer covers:

        - **Work distribution:** Queues per tier or size class, dedicated queues for the largest tenants, FIFO with tenant ID as the message group or shuffle-sharded queue assignment, and per-tenant rate limits at intake.
        - **Compute concurrency:** Reserved concurrency per tier and event source mapping maximum concurrency per queue; large jobs split through Step Functions Distributed Map with bounded `MaxConcurrency`.
        - **Data partitioning:** Partition keys that include the tenant ID with `dynamodb:LeadingKeys` isolation, avoiding hot partitions; the largest tenants possibly in their own tables or cells.
        - **Detection:** Per-tenant metrics (for example CloudWatch Contributor Insights to find top tenants), `ApproximateAgeOfOldestMessage` per queue, and per-tenant consumption alarms that fire before customers notice.
        - **Cost and number of tiers:** Each tier adds fixed cost and operations; choose the count from how much one tenant can contribute to load, SLAs and pricing, typically a few tiers plus dedicated cells for the largest tenants.
        - **With 40 tenants:** Per-tenant queues, concurrency or even a silo per tenant become practical and simpler; shuffle sharding is unnecessary.

4. Your organisation has never run a chaos experiment and the engineering leadership is nervous about deliberately injecting faults into production. Write the case you would make, the twelve-month programme you would propose including the specific sequence of experiments, the prerequisites that must exist before the first production experiment, the governance and safety controls, and the metrics by which you would report progress. Address the objection that "we already know our system is resilient because we have never had an AZ failure".

    ??? success "Check your answer"

        A good answer covers:

        - **The case:** Failures will happen; recovery paths that never run decay; finding weaknesses in a bounded, staffed experiment is far cheaper than finding them in a real incident.
        - **Answering 'never had an AZ failure':** Absence of failure is not evidence of resilience: it means the failover path has never been exercised, and the system has changed since it was designed.
        - **Prerequisites:** Steady-state SLO metrics and alarms, tracing, runbooks, on-call ownership, rollback capability, a Resilience Hub assessment, tagged targets and a FIS role scoped to that tag.
        - **Twelve-month sequence:** Game days and pre-production single faults (task termination, Lambda errors), then dependency latency, database failover and DLQ redrive drills, then the pre-production AZ power-interruption scenario and first small production experiments, then production AZ-scope experiments in business hours and automated experiments in pipelines.
        - **Governance and safety:** Change management, on-call informed, stop conditions on customer harm, explicit small blast radius, approvals and time windows, and a review after every experiment.
        - **Progress metrics:** Experiments run, hypotheses disproved and fixed, measured recovery time against targets, critical services covered, and incident recovery time trend.

5. Critique the following design: "Every service retries failed calls five times with a fixed one-second delay. All background work goes through a single SQS queue consumed by one Lambda function with no reserved concurrency. Failed messages are logged and deleted. Multi-service processes are implemented as chains of Lambda functions that invoke one another asynchronously. We deploy to three Availability Zones so we are resilient to an AZ failure." Identify at least seven distinct defects, rank them by the severity and reversibility of the damage they would cause, propose a corrected design, and describe how you would verify each correction.

    ??? success "Check your answer"

        A good answer covers:

        - **Defects:** (1) Five retries with a fixed 1-second delay, no backoff or jitter; (2) retries in every service, multiplying across layers; (3) one shared queue for all background work; (4) one Lambda consumer with no reserved concurrency; (5) failed messages logged and deleted; (6) Lambda chains invoking each other asynchronously with no orchestration or compensation; (7) three AZs assumed to equal resilience, untested; also no timeouts or idempotency mentioned.
        - **Ranking:** Deleting failed messages (irreversible data loss) and uncompensated Lambda chains (inconsistent business state) first; the retry policy next (outages, reversible by configuration); then the shared queue and missing concurrency controls; the untested AZ claim is a latent risk.
        - **Corrected design:** Timeouts plus one-layer exponential backoff with full jitter under a budget; idempotency keys; queues per workload with reserved and event source mapping concurrency; DLQs with `maxReceiveCount` of 3 to 5, alarm, owner and redrive; a Step Functions saga with `Retry`, `Catch` and compensations.
        - **Verification:** FIS latency injection showing bounded load; a poison-message test landing in the DLQ and redriving; a load test showing one workload cannot starve another; a mid-saga failure triggering compensation; an AZ power-interruption experiment holding steady state.

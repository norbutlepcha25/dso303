# Unit 4: Practice Questions

## 4.1 Microservices Design Principles

### Beginner Questions

1. Define a business capability and explain why capability-based boundaries are more stable than boundaries drawn from an application's existing module structure.
2. State the database-per-service rule precisely, and explain why a second service reading  but never writing  another service's table still violates it.
3. Explain the difference between a command and a domain event, giving one correctly named example of each from an e-commerce system.
4. Describe what a resolver is in AWS AppSync, and explain the difference between a unit resolver and a pipeline resolver.
5. A GraphQL query returns HTTP 200 with a `data` object containing a null field and a non-empty `errors` array. Explain what has happened and why this matters for monitoring.

### Intermediate Questions

1. A team wants the orders service to store a `productName` field copied from the catalogue at order time. Another team argues this is denormalisation and the orders service should look up the name when needed. Argue both positions, then state which is correct and why.
2. Explain the N+1 problem in AppSync using a concrete query. Describe the two AWS mechanisms that solve it, what must change in the resolver code, and the production metric that reveals the problem.
3. Compare AWS AppSync and Amazon API Gateway across five dimensions: client shape, contract ownership, per-consumer control, real-time capability, and cost model. Give one scenario where each is clearly correct.
4. Describe the transactional outbox pattern as implemented on DynamoDB and as implemented on Aurora. State precisely which failure mode it eliminates, what new obligation it creates for consumers, and why a retry cannot substitute for it.
5. A system has eight microservices and finance requires a monthly report joining data from six of them. Three solutions are proposed: grant the reporting service read access to six databases; have the reporting service call six APIs and join in memory; replicate all six services' data into a warehouse. Evaluate each and recommend one.

### Advanced Questions

1. You are handed a nine-year-old insurance monolith and asked to produce a decomposition plan. Write the plan. It must specify the discovery method and its artefacts, at least six candidate boundaries with the criterion that justified each, the data ownership of each, which operations must remain atomic and why, the extraction sequence with a justification for the first extraction, and the three measurements you would use after six months to determine whether the boundaries were correct.
2. Design the complete API and data topology for a company with five product teams, a web client, an iOS client, forty partner integrations and a PCI-scoped payments capability. Specify the edge for each audience, the federation mechanism, the store per service with a justification from access pattern, the event contracts including what may not appear in a payload, and the reconciliation jobs you would build on day one. Then state the three most likely ways this design degrades over two years and what you would put in place now to detect each.
3. A team reports that a decomposition completed eighteen months ago has made delivery slower rather than faster: most features touch three or more services, p99 latency has tripled, and two incidents in the last quarter took over an hour to diagnose. You have access to the Git history, the X-Ray service map, the IAM policies and the event schemas. Describe your investigation in order, the specific evidence you would gather from each source, the three most likely root causes, and  for the most likely one  the remediation plan including what you would merge back and how you would justify that to a team that spent eighteen months splitting it.
4. Critique the following proposal: "We will build one AppSync API owned by the platform team, with all resolvers as Lambda functions. Each Lambda will query whichever service databases it needs directly, for performance. Domain events will be published by each service calling `PutEvents` after its database write. All services will share one Aurora cluster with a schema per service, to save cost. Reporting will read from a read replica of that cluster." Identify at least six distinct defects, rank them by the severity and reversibility of the damage, propose a corrected design, and state which parts of the original you would keep.
5. A business requires that a customer sees their newly placed order in their order history immediately, with no stale window, and separately requires that the ordering and history capabilities be owned by different teams with independent release cadences. Analyse the tension between these two requirements. Present at least three technically valid resolutions with their trade-offs, state which you would recommend and why, and describe the conversation you would have with the business if none of the three is acceptable to them.

---

## 4.2 API Management and Service Mesh

### Beginner Questions

1. Distinguish north–south traffic from east–west traffic, and name the primary AWS instrument for each.
2. List four capabilities that an Amazon API Gateway REST API provides and an HTTP API does not, and give one scenario in which each is decisive.
3. Explain the difference between an API key and an authorizer in API Gateway, and state what is wrong with protecting a method with an API key alone.
4. Describe what AWS Cloud Map stores, and explain one thing it can do that a DNS record cannot.
5. Define a service mesh in terms of its data plane and control plane, and state what happens to existing traffic if the control plane becomes unavailable.

### Intermediate Questions

1. A team routes all internal service-to-service traffic through API Gateway for consistency and observability. Give four concrete reasons this is wrong, and describe what you would offer instead that satisfies both of their stated motivations.
2. Explain why DNS-based service discovery is inadequate for a service whose tasks are replaced many times per hour. Describe the failure precisely, name two AWS mechanisms that avoid it, and explain what each does that DNS does not.
3. AWS App Mesh reaches end of support on 30 September 2026. For each of the following uses, name the successor and justify it: in-ECS discovery and load balancing; weighted canary routing; mTLS between services; cross-account service calls; header-based routing with fault injection.
4. A Lambda authorizer has increased an API's p99 latency from 120 ms to 900 ms. Explain the mechanism, describe how you would confirm it from CloudWatch metrics alone, and give three distinct remediations.
5. Compare Amazon VPC Lattice, AWS PrivateLink and VPC peering as mechanisms for connecting services across accounts. State the situation in which each is correct, and explain specifically why overlapping CIDR ranges eliminate two of the three.

### Advanced Questions

1. Design the complete north–south and east–west topology for a retailer with a public API used by 400 partners on three commercial tiers, a mobile application, and 60 internal services split across ECS and EKS in four AWS accounts. Specify the API type and endpoint configuration for each audience with justification, the federation mechanism that prevents one team owning "the API", the east–west mechanism for each traffic path, and the specific observability artefacts you would build. Then state three things you deliberately would *not* build and defend each.
2. A platform team proposes: "We will install Istio on all six EKS clusters with sidecar injection everywhere, strict mTLS, retries of three at the mesh layer, outlier detection with default settings, and route all internal HTTP traffic through it. We will also put API Gateway in front of every service so all traffic is observable in one place." Identify at least six distinct defects, rank them by the severity and reversibility of the damage, propose a corrected design, and state which parts of the original proposal you would keep and why.
3. Your organisation has decided on "zero trust between services". Define what that means concretely on AWS in terms of authentication, authorisation, encryption and audit; specify the implementation for an estate running ECS, EKS and Lambda across twelve accounts; describe the migration sequence and the specific hazards at each step; and state clearly what this programme will *not* achieve, so that the security committee's expectations are correctly set.
4. A partner-facing API must support a breaking change to its response schema. Four hundred integrators depend on it, you cannot force them to upgrade, and two of them are contractually guaranteed twelve months' notice. Design the versioning, deployment, measurement and deprecation strategy using API Gateway capabilities. Explain how you would know when it is safe to retire the old version, what you would do about an integrator who has not migrated at the deadline, and how the design differs from what you would do for a first-party mobile client.
5. An incident review finds that a 90-second latency increase in one internal service produced a 40-minute full outage that persisted for 20 minutes after the original service had recovered. The estate uses a service mesh. Explain the mechanism in detail, identify every configuration defect that must have been present for this outcome to occur  covering retries, timeouts, outlier detection, connection pools and throttling  and specify the changes, with concrete settings, that would have bounded the incident to a degraded 90 seconds.

---

## 4.3 Resilience in AWS Microservices

### Beginner Questions

1. Explain why every outbound network call needs a timeout, and describe precisely what happens to a service that calls a hung dependency without one.
2. Define exponential backoff and full jitter. Explain what goes wrong if you use backoff without jitter across a fleet of clients.
3. Describe the three states of a circuit breaker and explain what specifically goes wrong if the half-open state is omitted.
4. State the purpose of an SQS dead-letter queue and explain what happens to a persistently failing message on a FIFO queue that has no DLQ configured.
5. Explain why every consumer of an SQS queue must be idempotent, and describe one correct implementation using Amazon DynamoDB.

### Intermediate Questions

1. A Lambda function consuming an SQS queue occasionally processes the same message twice. Give three distinct possible causes, describe how you would distinguish between them from CloudWatch metrics and message attributes, and state the fix for each.
2. Explain the bulkhead pattern and describe three distinct AWS implementations. For each, state precisely what it isolates and what it does not.
3. Compare a Step Functions `Retry` block with retry logic written inside a Lambda function. Give three advantages of the declarative approach and one situation in which in-function retry is still correct.
4. A team enables retries in their service mesh, in the AWS SDK, and in their application code. Explain the consequence quantitatively, describe how the problem would present during an incident, and state what you would change.
5. Design a chaos experiment to validate that an order-processing pipeline survives the loss of its payment provider. Specify the steady state, the hypothesis, the FIS action and targets, the blast radius, the stop condition, and what result would falsify the hypothesis.

### Advanced Questions

1. An incident review shows that a 60-second latency increase in a single downstream service produced a 90-minute full outage that continued for 35 minutes after the downstream service had fully recovered. Explain the mechanism in detail. Identify every configuration defect that must have been present  covering timeouts, retries, jitter, budgets, breakers, bulkheads, load shedding and deadline propagation  and specify each remediation with concrete settings. Then describe the chaos experiment you would add to ensure the fix does not silently regress.
2. Design the complete resilience strategy for a payment-processing system spanning six services, one third-party provider, and a regulatory requirement that no payment may be lost or duplicated. Specify which interactions are synchronous and why; the retry, timeout, breaker and bulkhead configuration for each; the saga and its compensations including which steps cannot be compensated and how you order around that; the idempotency strategy including how the key reaches the provider; the reconciliation jobs; and the chaos experiments. State explicitly what you would tell the regulator about the failure modes that remain.
3. A SaaS platform serves 4,000 tenants through shared queues and shared Lambda functions. Two incidents in the last quarter were caused by a single large tenant's workload degrading service for everyone. Design the isolation strategy. Cover work distribution, compute concurrency, data partitioning, and the observability required to detect the next occurrence before customers do. Explain the cost implications, describe how you would decide how many isolation tiers to build, and state what you would do differently if there were 40 tenants rather than 4,000.
4. Your organisation has never run a chaos experiment and the engineering leadership is nervous about deliberately injecting faults into production. Write the case you would make, the twelve-month programme you would propose including the specific sequence of experiments, the prerequisites that must exist before the first production experiment, the governance and safety controls, and the metrics by which you would report progress. Address the objection that "we already know our system is resilient because we have never had an AZ failure".
5. Critique the following design: "Every service retries failed calls five times with a fixed one-second delay. All background work goes through a single SQS queue consumed by one Lambda function with no reserved concurrency. Failed messages are logged and deleted. Multi-service processes are implemented as chains of Lambda functions that invoke one another asynchronously. We deploy to three Availability Zones so we are resilient to an AZ failure." Identify at least seven distinct defects, rank them by the severity and reversibility of the damage they would cause, propose a corrected design, and describe how you would verify each correction.

## Interview Questions

### Conceptual

1. Define cloud-native in your own words and explain why lift-and-shift migration does not make an application cloud-native.
2. Distinguish serverless from microservices. Can a system be one without the other? Give an example of each.
3. What does "loose coupling" mean concretely, and how do events reduce temporal coupling in ways that synchronous APIs cannot?
4. Explain the difference between an event and a command, and why the distinction affects system coupling.
5. Why must event consumers be idempotent? Describe a concrete implementation of idempotency on AWS.
6. Compare choreography and orchestration. What are the operational consequences of each?
7. What is eventual consistency, and how would you explain its user-visible effects to a non-technical product owner?
8. Explain the CAP theorem's relevance to a microservices architecture that spans multiple Availability Zones.
9. What is a distributed monolith, and what single test reveals one?
10. Why is API-first considered an organisational practice as much as a technical one?

### Scenario

1. An e-commerce checkout takes 8 seconds because it synchronously calls inventory, payment, fraud, email, and analytics services. Redesign it and quantify the expected user-perceived latency improvement.
2. A Lambda function connected to RDS fails during traffic spikes with connection errors. Diagnose and give two distinct remedies.
3. Traffic is highly variable: near zero overnight, 40x peak for three hours each morning. Choose a compute strategy and justify it on cost and latency grounds.
4. A partner integration requires guaranteed ordering of financial transactions per customer account. Which AWS messaging service and configuration would you choose, and what throughput limitation must you communicate?
5. Your team must publish an API that mobile clients — which cannot be force-upgraded — will consume for at least three years. Describe your versioning and deprecation strategy.
6. An event consumer had a bug for six hours and dropped 200,000 events. How do you recover the lost processing?
7. A microservices platform has grown to 60 services and deployment velocity has _fallen_. Diagnose the likely causes and propose remedies.

### Architecture

1. Design a serverless image-processing pipeline that handles 10,000 uploads per minute, produces three thumbnail sizes, and must not lose an image. Draw the architecture and justify each component.
2. Design a multi-tenant SaaS API where no single tenant may degrade another's performance. Address throttling, isolation, and cost attribution.
3. Design an order-fulfilment system implementing the Saga pattern. Specify compensating actions and how you would make the workflow auditable.
4. You must migrate a monolithic Java application to cloud-native over 18 months without a feature freeze. Present your migration strategy.
5. Design the observability strategy for a system with 30 microservices and heavy asynchronous messaging. Specify metrics, alarms, tracing, and log structure.

### Troubleshooting

1. An SQS queue's `ApproximateAgeOfOldestMessage` is growing steadily while consumer CPU sits at 20%. List possible causes in order of likelihood.
2. Lambda p99 latency is 3 seconds while p50 is 40 ms. Explain the likely cause and three mitigations.
3. EventBridge shows successful `PutEvents` but a target Lambda is never invoked. Enumerate your diagnostic steps.
4. Customers report duplicate confirmation emails during high traffic. Identify the root cause and the fix.
5. After a deployment, an ECS service is stuck with tasks repeatedly stopping and restarting. What do you check, and in what order?

### Certification-style

1. A company needs to decouple a web tier from a batch processing tier, guarantee that each message is processed at least once, and retry failures automatically. Which service is most appropriate, and why is SNS alone insufficient?
2. An application must notify four independent downstream systems whenever a new file lands in S3, with each system able to fail and retry independently. Design the messaging topology.
3. A workflow requires branching logic, retries with backoff, a 30-minute wait for external approval, and full audit history. Which service and why?
4. A serverless API must reject malformed requests before invoking any compute. Which feature achieves this at the lowest cost?

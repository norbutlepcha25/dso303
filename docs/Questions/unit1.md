
# Unit 1: Questions for Practice

## 1.1
## 1.2
## 1.3
## 1.4
## 1.5
## 1.6





## 1.7

1. Define cloud-native and explain why simply moving a virtual machine to EC2 does not make an application cloud-native.
2. List three characteristics of serverless computing and give one AWS service that exemplifies each.
3. What is the difference between SNS and SQS? Give a scenario appropriate to each.
4. Explain what an event is in an event-driven architecture and how it differs from a command.
5. What does "API-first" mean, and name two artefacts produced before any implementation code is written.

6. Explain what a cold start is, three factors that influence its duration, and two mitigation strategies with their cost implications.
7. A microservice needs to call three other services to build a response. Describe two design changes that would reduce user-perceived latency and improve resilience.
8. Compare choreography and orchestration for a five-step order-fulfilment process. Which would you choose and why?
9. Explain why event consumers must be idempotent, and describe an implementation using DynamoDB conditional writes.
10. Your SQS visibility timeout is 30 seconds and your consumer sometimes takes 45 seconds. Describe precisely what goes wrong and how to fix it.
11. Design a multi-tenant SaaS platform on AWS where tenants have different throughput tiers and no tenant may degrade another's performance. Address API throttling, compute isolation, data isolation, observability per tenant, and cost attribution. Justify every choice against the Well-Architected pillars.
12. A payment system must move funds between two microservices that own separate databases. ACID transactions are impossible. Design a solution using the Saga pattern, specify compensating actions, explain how you guarantee the event is published if and only if the database write succeeds, and describe how you would prove correctness to an auditor.
13. An organisation with 45 microservices reports that deployment frequency has dropped and incidents take an average of four hours to diagnose. Diagnose the likely architectural and organisational causes, and propose a prioritised twelve-month remediation plan.
14. Evaluate serverless versus containers for a workload of 400 million requests per month, average duration 180 ms, average memory 512 MB, with a strict p99 latency requirement of 100 ms. Show your reasoning on cost, latency, and operational burden, and state what additional information you would need to make a final recommendation.
15. Design an event-driven data platform ingesting 200,000 IoT telemetry events per second that must support real-time alerting (sub-second), hourly aggregation, and ad-hoc historical analysis over two years of data. Specify the services, partitioning strategy, storage tiers, failure handling, and cost controls.

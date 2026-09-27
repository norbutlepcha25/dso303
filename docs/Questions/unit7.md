# Unit 7: Practice Questions

## 7.1 Monitoring Cloud-Native Applications

### 7.1.1 Infrastructure and Application Monitoring with Amazon CloudWatch

#### Beginner Questions

1. Define a CloudWatch namespace, metric and dimension, and give an example of each for an AWS Lambda function.
2. What is the difference between basic monitoring and detailed monitoring for EC2, and which one is free?
3. List the retention periods for one-second, one-minute, five-minute and one-hour CloudWatch data points.
4. Why is a Synthetics canary able to detect failures that internal application metrics cannot?
5. What does the CloudWatch agent add to EC2 monitoring that the hypervisor cannot provide?

#### Intermediate Questions

1. A metric has dimensions `Service` (15 values), `Operation` (20 values) and `AvailabilityZone` (3 values). Calculate its cardinality and the indicative monthly cost at USD 0.30 per metric, and propose a cheaper design that still supports per-AZ troubleshooting.
2. Write an EMF log line that publishes `PaymentLatency` and `PaymentsDeclined` with the dimension sets `[Service]` and `[Service, Provider]`, and explain which fields remain searchable but are not dimensions.
3. Explain how Container Insights with enhanced observability differs from standard Container Insights for ECS in granularity and pricing.
4. Compare CloudWatch RUM and Synthetics, and describe a situation in which each detects a problem the other misses.
5. Describe the resources and policies required to link a workload account to a monitoring account with Observability Access Manager, and state what data is and is not copied.

#### Advanced Questions

1. Design a metrics strategy for a 40-service platform on EKS and Lambda that must support per-operation latency SLOs, business KPIs and tenant-level investigation, while keeping observability cost under 10 per cent of infrastructure cost. Justify your choices among Application Signals, EMF, OpenTelemetry metrics with PromQL and trace annotations.
2. A regulator requires one-minute latency data for payment APIs to be retained for seven years. CloudWatch retains one-minute data for 15 days. Design a compliant architecture and discuss its cost and query model.
3. Evaluate the risks of publishing telemetry through a NAT gateway from private subnets for a fleet of 500 Fargate tasks, and design a private, resilient telemetry path.
4. A company is migrating from a self-hosted Prometheus and Grafana stack to AWS. Compare three target architectures: CloudWatch-native (Container Insights and Application Signals), Amazon Managed Service for Prometheus with Amazon Managed Grafana, and CloudWatch OpenTelemetry metrics with PromQL. Recommend one for a team of five engineers and justify it.
5. After an incident, you discover that a canary had been failing for three weeks because its test account password expired, and nobody noticed. Perform a post-incident analysis and propose technical and organisational controls to ensure that monitoring itself is monitored.

### 7.1.2 Distributed Tracing with AWS X-Ray

#### Beginner Questions

1. Define a trace, a segment and a subsegment.
2. What does `Sampled=1` in the `X-Amzn-Trace-Id` header mean?
3. What is the default X-Ray sampling rule?
4. What is the difference between an error, a fault and a throttle in X-Ray?
5. What is the AWS Distro for OpenTelemetry, and why does AWS recommend it for new applications?

#### Intermediate Questions

1. Write two X-Ray filter expressions: one that finds faulted traces of the `orders` service slower than 3 seconds, and one that finds traces for tenant tier `premium` calling DynamoDB.
2. Explain how trace context crosses API Gateway, Lambda, SQS and a second Lambda function, naming the header or attribute used at each hop.
3. Design sampling rules for a service that handles 5,000 `GET /products` requests per second, 20 `POST /checkout` requests per second and continuous load balancer health checks.
4. Explain what CloudWatch Transaction Search stores, where it stores it, what is indexed by default and how its pricing differs from classic X-Ray.
5. Describe how span links represent an SQS batch consumer that processes messages from ten different traces.

#### Advanced Questions

1. Design an organisation-wide tracing platform for 60 services across ECS, EKS and Lambda in 12 accounts, covering instrumentation standards, collectors, sampling, Transaction Search, cross-account viewing through OAM, redaction and cost controls.
2. Evaluate tail sampling in an OpenTelemetry Collector gateway against X-Ray adaptive sampling for a payment platform that must retain every failed transaction trace for 30 days.
3. A saga spanning Step Functions, EventBridge and three microservices occasionally leaves orders in an inconsistent state. Explain how you would use tracing, annotations and correlation IDs to reconstruct failed sagas, and what changes to instrumentation are required.
4. Estimate the monthly span ingestion volume for a service handling 2,000 requests per second with 25 spans per request at an average of 1 KB per span under 100 per cent sampling, and propose a sampling and indexing strategy that balances completeness and cost.
5. Plan the migration of a 30-service estate from the X-Ray SDK and daemon to OpenTelemetry before February 2027, including sequencing, propagation compatibility, testing on the trace map, rollback and training.

### 7.1.3 Health Checks and Readiness Probes on AWS

#### Beginner Questions

1. List the six ALB target health states and explain `draining`.
2. What are the default ALB health check interval, timeout, healthy threshold and unhealthy threshold for instance targets?
3. What is the difference between an EC2 system status check and an instance status check?
4. Why should a health check endpoint not require authentication or redirect to HTTPS?
5. What is the deregistration delay, and what problem does it solve?

#### Intermediate Questions

1. A service must stop receiving traffic within 15 seconds of failing and must not be re-admitted until it has passed checks for 30 seconds. Choose an ALB interval, timeout and thresholds, and show the arithmetic.
2. Explain how a pod readiness gate on EKS changes the behaviour of a rolling deployment behind an ALB.
3. Design the container health check for an SQS worker on ECS that has no inbound HTTP traffic.
4. Explain calculated health checks and CloudWatch alarm-based health checks in Route 53, with one use case for each.
5. Put the following in the correct order and justify it: `stopTimeout`, p99 request duration, deregistration delay, application drain time.

#### Advanced Questions

1. Design health checks and failover for an active-active two-Region API on API Gateway, Lambda and DynamoDB global tables, including how a partial Regional failure (one dependency degraded) should or should not trigger failover.
2. Analyse a gray failure in which one Availability Zone's targets pass health checks but return errors for 10 per cent of requests. Which AWS mechanisms detect and mitigate it, and how would you design alarms and automation around them?
3. A team proposes that the ALB health check should verify the database, the cache and two downstream services "to be safe". Write the architectural review response, including a failure scenario, the correct alternative design and the metrics that will show it works.
4. Design graceful shutdown for a WebSocket-based chat service on ECS Fargate where connections last hours and deployments happen several times a day.
5. Compare health-driven recovery for a stateful single-instance legacy application on EC2 with a stateless ECS service, covering status checks, automatic recovery, Auto Scaling, data protection and expected recovery times.

---

## 7.2 Centralized Logging

### 7.2.1 Log Aggregation with Amazon CloudWatch Logs

#### Beginner Questions

1. Define a log event, a log stream and a log group, and give an example of each for an ECS service.
2. Why must containerised applications write logs to standard output rather than to files?
3. List five fields that every structured log event should contain and explain the purpose of each.
4. What is the default retention of a new log group, and why is this a cost risk?
5. Which IAM role, the ECS task role or the task execution role, needs permissions for the `awslogs` driver, and why?

#### Intermediate Questions

1. Write a JSON metric filter pattern that matches events where `level` is `ERROR` and `service` is `checkout`, and explain `metricValue`, `defaultValue` and dimensions.
2. Compare the Standard and Infrequent Access log classes, and choose a class for each of: Lambda application logs used for alarms, API Gateway access logs, EKS audit logs queried monthly.
3. Explain the blocking and non-blocking modes of the ECS `awslogs` driver, the June 2025 default change, and the trade-off each mode represents.
4. Describe how a correlation ID flows from API Gateway through Lambda, SQS and an ECS worker, and what happens to investigations if one hop fails to propagate it.
5. Estimate the monthly ingestion cost of 15 GB per day of Standard-class logs and describe three ways to reduce it by at least half.

#### Advanced Questions

1. Design an organisation-wide logging architecture for 100 accounts across two Regions, covering centralisation rules, a Log Archive account, immutable S3 retention, KMS key ownership, service control policies and cross-account read access for security analysts.
2. Compare CloudWatch Logs centralisation rules, cross-account subscription destinations and CloudWatch cross-account observability. For each, describe what data moves, the cost implications and one scenario where it is the best choice.
3. A regulated payments service must never lose an audit log record, yet must remain available during CloudWatch Logs throttling events. Propose a design that satisfies both requirements, discussing blocking mode, local durable buffering, Firehose and idempotent audit writes.
4. Design a FireLens configuration that sends ERROR and WARN events to CloudWatch Logs for alarms, all events to Firehose for Parquet archival in S3, and drops health-check noise, and justify the cost savings with an estimate.
5. A security team wants automatic blocking of IP addresses after 20 failed logins in five minutes across 30 services. Compare a metric filter with an alarm, a subscription filter with Lambda, and a Logs Insights scheduled query, and design the preferred solution with its failure modes.

### 7.2.2 Log Analysis with Amazon CloudWatch Logs Insights

#### Beginner Questions

1. What are system fields in Logs Insights? Name four and explain what each contains.
2. Write a Logs Insights QL query that counts ERROR events per service in the selected time range and sorts the result.
3. Explain what `bin(5m)` does and why it is needed to draw a chart.
4. What is the billing measure for Logs Insights, and how can you see how much a query scanned?
5. Why should field names be consistent across services, and what happens to a cross-service query when they are not?

#### Intermediate Questions

1. Write a query that computes request count, error rate and p99 latency per minute from access logs, and explain each function used.
2. Use `parse` with a regular expression to extract a user name and IP address from a legacy text log, and explain why this approach is fragile.
3. Compare Logs Insights QL, OpenSearch PPL and OpenSearch SQL, and choose a language for three different users: an on-call developer, an OpenSearch security analyst and a data analyst.
4. Explain field indexes, facets and `filterIndex`, and describe what should and should not be indexed, with reasons.
5. Estimate the monthly cost of a Logs Insights dashboard widget that scans 30 GB per refresh with a 10-minute auto-refresh, and propose a cheaper design.

#### Advanced Questions

1. Design an incident-investigation toolkit for a platform of 150 services: schema standards, index policies, saved query library, runbook integration, access control for unmasking and cost guardrails.
2. A query using `filterIndex` across 5,000 log groups returned no results for an order that certainly exists. List every possible cause and how you would verify each.
3. Design an automated post-deployment verification stage using Logs Insights `pattern` and `diff`, including thresholds, handling of noise, rollback integration with CodeDeploy and the cost per deployment.
4. Evaluate when an organisation should move a recurring analytical workload from Logs Insights to OpenSearch Service, using query frequency, data volume, latency needs and cost as criteria, and present a break-even calculation.
5. Design a cross-account security investigation capability using CloudWatch cross-account observability, CloudTrail and VPC Flow Logs data sources, SQL joins and lookup tables of account ownership, and explain the IAM and data protection controls required.

### 7.2.3 Log Storage and Analytics with Amazon OpenSearch Service

#### Beginner Questions

1. What is the difference between a `keyword` and a `text` field? Give two logging fields that should be of each type.
2. Define shard and replica, and explain why a production domain should have replicas in multiple AZs.
3. What does Index State Management do? Describe a simple hot-to-delete policy.
4. Name the three ways of using OpenSearch in AWS (domains, Serverless, direct query) and give one suitable use for each.
5. Why is a public OpenSearch endpoint with an access policy allowing all principals dangerous for log data?

#### Intermediate Questions

1. A service produces 120 GiB of logs per day. Using the AWS sizing formula, choose the number of primary shards per daily index and justify your choice.
2. Compare four paths for moving CloudWatch Logs data into OpenSearch (Lambda subscription, Firehose, Kinesis with OpenSearch Ingestion, direct query) in terms of latency, operations and cost.
3. Explain rollover, aliases and data streams, and why size-based rollover is preferred for logs.
4. Write a query DSL request that counts ERROR events per service over the last hour using filter context, and explain why filter context is used.
5. Explain the purpose of each OpenSearch Serverless policy type (encryption, network, data access, data lifecycle) and design them for a logging collection.

#### Advanced Questions

1. Design an organisation-wide log analytics platform combining CloudWatch Logs, Logs Insights, OpenSearch domains, direct query and an S3 archive, and justify which data goes where, for how long, and why.
2. Produce a cost comparison for 200 GB per day of logs retained 90 days, comparing Logs Insights-only, an OpenSearch domain with UltraWarm, and OpenSearch Serverless, under low and high query-frequency assumptions, and identify the break-even point.
3. Evaluate the 2026 log-optimised OpenSearch engine for a new security analytics platform: benefits, constraints (engine mode permanence, query DSL support, instance families, tiering) and a migration and validation plan.
4. Design a zero-data-loss, buffered ingestion architecture for a regulated platform, covering Fluent Bit buffering, OpenSearch Ingestion persistent buffers, DLQs, replay procedures and monitoring, and analyse its failure modes.
5. A cluster with 40,000 shards is unstable. Diagnose the causes, design a remediation plan (consolidation, reindexing, template changes, ISM) that avoids downtime, and define guardrails to prevent recurrence.

---

## 7.3 Observability and Alerting

### 7.3.1 Creating CloudWatch Dashboards and Alarms

#### Beginner Questions

1. What is the difference between a CloudWatch dashboard and a CloudWatch alarm, and why is a dashboard not a substitute for an alarm?
2. Name the three alarm states and give one cause of each.
3. Explain why latency alarms should use percentiles rather than averages.
4. Calculate the allowed downtime per 30 days for SLOs of 99.5, 99.9 and 99.99 per cent.
5. List four actions a CloudWatch alarm can perform directly.

#### Intermediate Questions

1. Write a metric math expression for an ALB 5xx error rate that avoids false alarms at low traffic, and explain each part.
2. A service has an SLO of 99.9 per cent over 30 days and handled 40 million requests in the first 10 days with 25,000 failures. Calculate the budget consumed and the average burn rate so far, and state what the team should do.
3. Explain composite alarm action suppression, including the wait period and the extension period, with an example.
4. Compare anomaly detection alarms and static threshold alarms. For which metrics is each appropriate?
5. Describe how an alarm mute rule behaves if the alarm is still in `ALARM` when the mute window ends, and how this differs from `DisableAlarmActions`.

#### Advanced Questions

1. Design a complete SLO-based alerting scheme for a payments API on ECS with a 99.95 per cent availability SLO and a p99 latency SLO of 400 ms, including burn-rate windows and thresholds, composite alarms, severities, routing, exclusion windows and deployment integration.
2. A platform team wants every one of 600 Lambda functions and 80 ECS services in production to have error alarms without teams creating them manually. Compare per-resource alarms generated by IaC with multi time series Metrics Insights alarms in cost, quota, precision, notification routing and operational overhead, and propose a hybrid design.
3. Critically evaluate the claim "we have 1,200 CloudWatch alarms, so our system is well monitored". What evidence would you ask for, and what metrics would you use to judge the quality of an alerting system?
4. Design a cross-account monitoring architecture that allows a central operations team to see and alarm on all workloads while service teams keep ownership of their alarms. Include identity, deployment, dashboards, routing and audit of silencing actions.
5. Explain how detection latency is composed for an alarm on a custom metric published through EMF from an ECS service, and propose design changes to reduce detection time for a critical signal from about eight minutes to under two minutes, with their cost implications.

### 7.3.2 Automated Incident Response with AWS Lambda

#### Beginner Questions

1. Define MTTD, MTTA and MTTR and state which one automated rollback improves most.
2. List three ways a CloudWatch alarm can cause a Lambda function to run.
3. What is a kill switch in incident automation, and give two ways to implement one on AWS.
4. Explain why a responder should act only on transitions into the `ALARM` state.
5. What was AWS Chatbot renamed to, and what are two things it lets engineers do from a chat channel?

#### Intermediate Questions

1. Write the EventBridge event pattern that matches transitions into `ALARM` for all alarms whose names begin with `prod-payments-`, and explain how you would exclude events caused by the responder itself for a CloudTrail-based rule.
2. Describe the design of a DLQ redrive responder that avoids simply moving messages back into the DLQ.
3. Compare the three human-approval mechanisms available on AWS and choose one for an Aurora failover, justifying your choice.
4. Explain how reserved concurrency serves two different purposes for a responder function.
5. Describe how to test a new responder safely before it is allowed to act in production.

#### Advanced Questions

1. Design an automated response system for a payments platform on ECS and Aurora across two Regions, including which responses are fully automated, which require approval, how regional impairments are handled, and how the automation itself is protected from abuse.
2. Critically evaluate the proposal "let an AI agent automatically remediate any incident it diagnoses". Discuss benefits, risks, controls and a staged adoption plan.
3. Propose a metrics framework to evaluate the effectiveness of an organisation's incident automation, including how to detect automation that is causing harm.
4. A GuardDuty finding triggers isolation of an EKS worker node. Design the full workflow, including Kubernetes-level actions, evidence preservation, capacity replacement and the permissions required.
5. Explain how you would use AWS Fault Injection Service, EventBridge archive and replay, and recorded events to build a continuous test suite for responders, and how that suite fits into the CI/CD pipeline from Unit V.

### 7.3.3 Performance Optimization Using AWS Tools

#### Beginner Questions

1. Define latency, throughput, utilisation and saturation, giving one CloudWatch metric that measures each.
2. What does AWS Compute Optimizer do, and why does it need the CloudWatch agent for EC2 memory recommendations?
3. What replaced the RDS Performance Insights console, and what are its two modes?
4. Name four kinds of load test and the question each answers.
5. Why is average latency a poor measure of user experience?

#### Intermediate Questions

1. Using Little's Law, calculate the average Lambda concurrency for 250 requests per second at 400 ms average duration, and explain what happens if duration triples.
2. Describe how you would use Application Signals, X-Ray and Database Insights, in order, to find the cause of a latency regression after a deployment.
3. Explain the inputs and strategies of Lambda Power Tuning and when you would choose each strategy.
4. Compare Trusted Advisor and Compute Optimizer in scope, depth, cost and access requirements.
5. List five drivers of observability cost and one lever for each, identifying which reductions would be unsafe.

#### Advanced Questions

1. Design a performance and capacity plan for a national examination results portal expecting fifty times normal traffic for two hours, covering load testing, database preparation, caching, pre-scaling, alarms and responders.
2. Critically evaluate automatically applying Compute Optimizer recommendations in production. Propose guardrails, exclusions and a rollout process.
3. A multi-tenant SaaS platform wants to report cost per tenant and latency per tenant. Design the telemetry, dimensions and analysis without creating a cardinality explosion.
4. Design a CI/CD performance gate that is reliable despite natural variance in load-test results. Discuss baselines, statistical thresholds, test duration and false failures.
5. Compare the optimisation approach for a latency-sensitive Java service on ECS, an I/O-bound Python Lambda function and an Aurora PostgreSQL database, identifying the key tool, key metric and most likely remedy for each.

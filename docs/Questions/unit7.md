# Unit 7: Practice Questions

## 7.1 Monitoring Cloud-Native Applications

### 7.1.1 Infrastructure and Application Monitoring with Amazon CloudWatch

#### Beginner Questions

1. Define a CloudWatch namespace, metric and dimension, and give an example of each for an AWS Lambda function.

    ??? success "Check your answer"

        A good answer covers:

        - **Namespace:** a container that isolates metrics from one source, for example `AWS/Lambda`.
        - **Metric:** a named, time-ordered set of numeric data points, for example `Duration` or `Errors`.
        - **Dimension:** a name-value pair that is part of the metric's identity, for example `FunctionName=orders-api`.
        - **Identity:** namespace, metric name and the full set of dimensions together identify one time series; a different dimension set is a different metric.

2. What is the difference between basic monitoring and detailed monitoring for EC2, and which one is free?

    ??? success "Check your answer"

        A good answer covers:

        - **Basic monitoring:** EC2 publishes metrics at five-minute intervals; it is free.
        - **Detailed monitoring:** metrics at one-minute intervals; charged as custom metrics per instance.
        - **Use:** detailed monitoring supports faster alarms and Auto Scaling reaction; basic is enough for low-criticality instances.
        - **Limitation of both:** hypervisor metrics only (no memory or disk-space usage without the agent).

3. List the retention periods for one-second, one-minute, five-minute and one-hour CloudWatch data points.

    ??? success "Check your answer"

        A good answer covers:

        - **Sub-minute (high resolution, for example one second):** 3 hours.
        - **One-minute data points:** 15 days.
        - **Five-minute data points:** 63 days.
        - **One-hour data points:** 455 days (15 months).
        - **Roll-up:** older data is aggregated into the next coarser period, so long-term raw detail needs metric streams or export.

4. Why is a Synthetics canary able to detect failures that internal application metrics cannot?

    ??? success "Check your answer"

        A good answer covers:

        - **Outside-in view:** a canary exercises the system from outside, as a user would, through DNS, CDN, TLS and the load balancer.
        - **Failures invisible inside:** expired certificates, DNS errors, broken CDN configuration or blocked networks produce no internal errors because requests never arrive.
        - **Absence of traffic:** internal metrics simply go quiet; a canary turns "no traffic" into an explicit failure.
        - **Constant probe:** it detects problems at night or in low traffic when real users are few.

5. What does the CloudWatch agent add to EC2 monitoring that the hypervisor cannot provide?

    ??? success "Check your answer"

        A good answer covers:

        - **Guest OS metrics:** memory utilisation, disk-space usage, swap, per-process and network statistics that the hypervisor cannot see.
        - **Logs:** collection of log files into CloudWatch Logs.
        - **Custom metrics:** StatsD, collectd and OpenTelemetry ingestion, and aggregation before publishing.
        - **Enablement:** prerequisite for Compute Optimizer memory-aware recommendations and for memory alarms.

#### Intermediate Questions

1. A metric has dimensions `Service` (15 values), `Operation` (20 values) and `AvailabilityZone` (3 values). Calculate its cardinality and the indicative monthly cost at USD 0.30 per metric, and propose a cheaper design that still supports per-AZ troubleshooting.

    ??? success "Check your answer"

        A good answer covers:

        - **Cardinality:** 15 x 20 x 3 = 900 time series.
        - **Cost:** 900 x USD 0.30 = about USD 270 per month (indicative first-tier price).
        - **Cheaper design:** publish `[Service, Operation]` (300 series) and `[Service, AvailabilityZone]` (45 series) instead of the full cross product: 345 series, about USD 103.50 per month.
        - **Troubleshooting retained:** per-AZ problems are visible per service; drill into the specific operation with logs, traces or Metrics Insights when needed.
        - **Principle:** dimension sets should follow the questions you will actually ask, not every possible combination.

2. Write an EMF log line that publishes `PaymentLatency` and `PaymentsDeclined` with the dimension sets `[Service]` and `[Service, Provider]`, and explain which fields remain searchable but are not dimensions.

    ??? success "Check your answer"

        A good answer covers:

        ```json
        {"_aws":{"Timestamp":1767225600000,"CloudWatchMetrics":[{"Namespace":"USMS/Payments","Dimensions":[["Service"],["Service","Provider"]],"Metrics":[{"Name":"PaymentLatency","Unit":"Milliseconds"},{"Name":"PaymentsDeclined","Unit":"Count"}]}]},"Service":"payments","Provider":"stripe","PaymentLatency":182,"PaymentsDeclined":1,"orderId":"o-1001","traceId":"1-6800-abc"}
        ```

        - **Structure:** the `_aws` block declares the namespace, the two dimension sets and the metric names and units; values are top-level fields.
        - **Dimensions:** `Service` and `Provider` are top-level fields referenced in `Dimensions`, giving three time series per metric set (one for `[Service]`, one per provider for `[Service, Provider]`).
        - **Searchable non-dimensions:** `orderId` and `traceId` remain in the log event and can be queried with Logs Insights, but they create no metrics and no cardinality cost.
        - **Delivery:** the line is written to stdout or a log group; CloudWatch extracts the metrics asynchronously.

3. Explain how Container Insights with enhanced observability differs from standard Container Insights for ECS in granularity and pricing.

    ??? success "Check your answer"

        A good answer covers:

        - **Standard Container Insights:** aggregated metrics mainly at cluster and service level (task level for some views).
        - **Enhanced observability:** granular metrics down to the container, curated drill-down dashboards and correlation with application telemetry.
        - **Pricing model:** standard is charged as custom metrics or log ingestion; enhanced is charged per observation (metric data point ingested), which makes high-cardinality container metrics affordable.
        - **Choice:** enable enhanced observability selectively for production clusters where container-level diagnosis matters.

4. Compare CloudWatch RUM and Synthetics, and describe a situation in which each detects a problem the other misses.

    ??? success "Check your answer"

        A good answer covers:

        - **RUM:** passive, collects real users' page loads, JavaScript errors and HTTP errors from browsers.
        - **Synthetics:** active scripted canaries on a schedule from AWS locations.
        - **RUM catches what Synthetics misses:** problems affecting a particular browser, device, ISP or geography that the scripted path does not exercise.
        - **Synthetics catches what RUM misses:** outages during low or no traffic (for example at night or before launch), and failures that stop the page loading so no RUM events are sent.
        - **Combination:** use both; canaries for availability of critical journeys, RUM for actual experience.

5. Describe the resources and policies required to link a workload account to a monitoring account with Observability Access Manager, and state what data is and is not copied.

    ??? success "Check your answer"

        A good answer covers:

        - **Monitoring account:** create an OAM sink with a sink policy that lists allowed source accounts or organisation paths.
        - **Source account:** create an OAM link to the sink, choosing which telemetry types to share (metrics, logs, traces, Application Signals and others).
        - **Permissions:** `oam:CreateLink` and related permissions in the source; `CreateSink` and `PutSinkPolicy` for the platform team only.
        - **Data movement:** nothing is copied; the monitoring account queries the source account's data in place, so retention, cost and ownership remain in the source account.

#### Advanced Questions

1. Design a metrics strategy for a 40-service platform on EKS and Lambda that must support per-operation latency SLOs, business KPIs and tenant-level investigation, while keeping observability cost under 10 per cent of infrastructure cost. Justify your choices among Application Signals, EMF, OpenTelemetry metrics with PromQL and trace annotations.

    ??? success "Check your answer"

        A good answer covers:

        - **Golden signals:** Application Signals (or OpenTelemetry auto-instrumentation) for per-operation RED metrics and SLOs, avoiding hand-built metrics.
        - **Business KPIs:** EMF with a few low-cardinality dimensions (`Service`, `Operation`), keeping IDs as searchable properties.
        - **Tenant investigation:** tenant IDs as trace annotations or log fields, not metric dimensions; optionally aggregate top tenants with Contributor Insights.
        - **Prometheus-style metrics:** OpenTelemetry metrics with PromQL for EKS workloads where teams already use PromQL.
        - **Cost control:** cardinality budgets per service, agent aggregation, retention and sampling policies, and a monthly observability cost review against the 10 per cent target.

2. A regulator requires one-minute latency data for payment APIs to be retained for seven years. CloudWatch retains one-minute data for 15 days. Design a compliant architecture and discuss its cost and query model.

    ??? success "Check your answer"

        A good answer covers:

        - **Constraint:** CloudWatch rolls one-minute data up after 15 days, so it cannot itself be the seven-year store.
        - **Export path:** metric streams through Firehose to S3 (JSON or OpenTelemetry format), partitioned by date and metric.
        - **Immutability:** S3 Object Lock in compliance mode, versioning, KMS encryption, lifecycle to Glacier tiers after the active period, in a separate archive account.
        - **Query model:** Athena (with Glue tables) for occasional regulatory queries; CloudWatch remains the operational store.
        - **Cost:** stream charge per metric update plus Firehose and very low archive storage; queries are paid per scan, so partitioning matters.

3. Evaluate the risks of publishing telemetry through a NAT gateway from private subnets for a fleet of 500 Fargate tasks, and design a private, resilient telemetry path.

    ??? success "Check your answer"

        A good answer covers:

        - **NAT risks:** a single NAT gateway is an AZ failure point; data processing charges per GB on large telemetry volumes; port exhaustion at high connection counts.
        - **Security:** telemetry leaves through the public endpoint path and depends on internet routing.
        - **Design:** interface VPC endpoints for CloudWatch Logs, monitoring, X-Ray and other telemetry APIs in every AZ, with endpoint policies.
        - **Resilience:** asynchronous, bounded telemetry buffers (non-blocking log drivers, collector queues) so telemetry failure never blocks requests.
        - **Cost:** compare endpoint hourly and per-GB charges with NAT processing; endpoints are usually cheaper at this scale.

4. A company is migrating from a self-hosted Prometheus and Grafana stack to AWS. Compare three target architectures: CloudWatch-native (Container Insights and Application Signals), Amazon Managed Service for Prometheus with Amazon Managed Grafana, and CloudWatch OpenTelemetry metrics with PromQL. Recommend one for a team of five engineers and justify it.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudWatch-native:** least operations and fastest start, AWS-integrated alarms; requires relearning dashboards and queries.
        - **AMP with Managed Grafana:** keeps PromQL, existing dashboards and exporters; managed scaling; two more services to pay for and integrate with CloudWatch alarms.
        - **CloudWatch OpenTelemetry metrics with PromQL:** keeps PromQL on a CloudWatch-native backend with OTLP ingestion; newer, so feature parity must be verified.
        - **Recommendation for five engineers:** minimise operational load; for example AMP with Managed Grafana if existing dashboards and alerts are a large investment, otherwise CloudWatch-native; justify by migration effort, skills and cost.
        - **Criteria:** query language continuity, alerting, multi-account support, cost per series and team capacity.

5. After an incident, you discover that a canary had been failing for three weeks because its test account password expired, and nobody noticed. Perform a post-incident analysis and propose technical and organisational controls to ensure that monitoring itself is monitored.

    ??? success "Check your answer"

        A good answer covers:

        - **Timeline and impact:** establish when the canary started failing, why its failures paged nobody and what it would have caught.
        - **Root causes:** credential with expiry and no rotation, alarm missing or routed to an unwatched channel, failures accepted as noise.
        - **Technical controls:** store test credentials in Secrets Manager with rotation; alarm on canary `SuccessPercent` and on missing canary runs; meta-monitoring of alarm states and canary health.
        - **Organisational controls:** owner for every monitor, periodic review of alarms in `ALARM` or `INSUFFICIENT_DATA`, game days that confirm monitors fire.
        - **Blameless review:** actions tracked to completion.

### 7.1.2 Distributed Tracing with AWS X-Ray

#### Beginner Questions

1. Define a trace, a segment and a subsegment.

    ??? success "Check your answer"

        A good answer covers:

        - **Trace:** the complete record of one request across all services, identified by a trace ID.
        - **Segment:** the work done by one service for that request (host, request, response, timing, outcome).
        - **Subsegment:** a finer-grained unit inside a segment, such as a downstream call or code block.
        - **OpenTelemetry mapping:** spans; the segment is the service's entry span and subsegments are child spans.

2. What does `Sampled=1` in the `X-Amzn-Trace-Id` header mean?

    ??? success "Check your answer"

        A good answer covers:

        - **Meaning:** the upstream caller decided to sample this request, so the trace is recorded.
        - **Propagation:** downstream services honour the decision and send their segments.
        - **Contrast:** `Sampled=0` means do not record; `Sampled=?` asks the receiver to decide.

3. What is the default X-Ray sampling rule?

    ??? success "Check your answer"

        A good answer covers:

        - **Reservoir:** the first request each second is recorded.
        - **Fixed rate:** 5 per cent of additional requests in that second are recorded.
        - **Scope:** applies when no custom rule matches; custom rules with higher priority override it.

4. What is the difference between an error, a fault and a throttle in X-Ray?

    ??? success "Check your answer"

        A good answer covers:

        - **Error:** client error, HTTP 4xx.
        - **Fault:** server error, HTTP 5xx, a failure of the service.
        - **Throttle:** HTTP 429, too many requests, indicating capacity or quota limits.
        - **Use:** filter expressions and trace map colours distinguish them, guiding whether to fix the caller, the service or capacity.

5. What is the AWS Distro for OpenTelemetry, and why does AWS recommend it for new applications?

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** AWS-supported distribution of OpenTelemetry SDKs, agents and the collector, tested with AWS services.
        - **Vendor neutral:** one instrumentation standard for traces, metrics and logs that can export to X-Ray, CloudWatch or other back ends.
        - **Future-proof:** the X-Ray SDKs and daemon entered maintenance mode on 25 February 2026 and reach end of support on 25 February 2027.
        - **Features:** auto-instrumentation, W3C and X-Ray propagation, X-Ray remote sampling support.

#### Intermediate Questions

1. Write two X-Ray filter expressions: one that finds faulted traces of the `orders` service slower than 3 seconds, and one that finds traces for tenant tier `premium` calling DynamoDB.

    ??? success "Check your answer"

        A good answer covers:

        - **Faulted, slow orders traces:** `service("orders") { fault = true } AND responsetime > 3`.
        - **Premium tier calling DynamoDB:** `annotation.tenant_tier = "premium" AND service("DynamoDB")` (or an `edge` filter to the DynamoDB node).
        - **Prerequisite:** `tenant_tier` must be recorded as an annotation, because metadata is not searchable.

2. Explain how trace context crosses API Gateway, Lambda, SQS and a second Lambda function, naming the header or attribute used at each hop.

    ??? success "Check your answer"

        A good answer covers:

        - **API Gateway:** starts or continues the trace and passes `X-Amzn-Trace-Id` (or W3C `traceparent`) to Lambda.
        - **Lambda:** receives context from the invocation (`_X_AMZN_TRACE_ID` environment variable) with active tracing.
        - **SQS:** the instrumented SDK in the producer sets the `AWSTraceHeader` message system attribute.
        - **Second Lambda:** the event source mapping reads `AWSTraceHeader`; batches from several traces are linked with span links.
        - **Failure mode:** an uninstrumented hop breaks the trace into disconnected pieces.

3. Design sampling rules for a service that handles 5,000 `GET /products` requests per second, 20 `POST /checkout` requests per second and continuous load balancer health checks.

    ??? success "Check your answer"

        A good answer covers:

        - **Health checks:** rule matching the health path with `ReservoirSize` 0 and `FixedRate` 0, highest priority.
        - **`GET /products`:** small reservoir (for example 1 per second) and low fixed rate (for example 0.1 to 1 per cent), because it is very high volume and repetitive.
        - **`POST /checkout`:** larger reservoir (for example 5 per second) and higher fixed rate (for example 10 to 50 per cent), because it is business-critical and low volume.
        - **Anomalies:** enable adaptive sampling so errors raise sampling temporarily.
        - **Management:** rules defined in IaC, ordered by priority, effective fleet-wide without redeployment.

4. Explain what CloudWatch Transaction Search stores, where it stores it, what is indexed by default and how its pricing differs from classic X-Ray.

    ??? success "Check your answer"

        A good answer covers:

        - **Stores:** all ingested spans as structured logs in the `aws/spans` log group in CloudWatch Logs.
        - **Indexed:** 1 per cent of spans are indexed as trace summaries by default (configurable at extra cost).
        - **Search:** every span is searchable with the visual editor or Logs Insights, even if not indexed as a summary.
        - **Pricing:** per GB of span ingestion at CloudWatch Logs pricing plus storage and retention, rather than classic X-Ray per-trace recorded and retrieved pricing.

5. Describe how span links represent an SQS batch consumer that processes messages from ten different traces.

    ??? success "Check your answer"

        A good answer covers:

        - **Problem:** one batch consumer span processes messages that belong to ten different traces, so it cannot have ten parents.
        - **Span links:** the consumer span links to the span context of each message's producer span.
        - **Navigation:** from any producer trace you can follow the link to the batch processing span, and vice versa.
        - **Optional:** per-message child spans for processing each message, each linked to its producer.

#### Advanced Questions

1. Design an organisation-wide tracing platform for 60 services across ECS, EKS and Lambda in 12 accounts, covering instrumentation standards, collectors, sampling, Transaction Search, cross-account viewing through OAM, redaction and cost controls.

    ??? success "Check your answer"

        A good answer covers:

        - **Instrumentation standard:** OpenTelemetry (ADOT) paved-road libraries, standard `service.name`, environment and annotation keys, W3C plus X-Ray propagation.
        - **Collectors:** sidecars on ECS Fargate, DaemonSets on EKS, Lambda active tracing or layers; optional central gateway for tail sampling and redaction.
        - **Sampling:** central X-Ray sampling rules in IaC (health checks off, critical paths reserved), adaptive sampling, Transaction Search for complete span search.
        - **Cross-account:** OAM links from 12 accounts to a monitoring account.
        - **Controls:** redaction of personal data in processors, data protection on `aws/spans`, retention policies, cost dashboards per service.

2. Evaluate tail sampling in an OpenTelemetry Collector gateway against X-Ray adaptive sampling for a payment platform that must retain every failed transaction trace for 30 days.

    ??? success "Check your answer"

        A good answer covers:

        - **Requirement:** every failed transaction must be kept, which head sampling cannot guarantee.
        - **Tail sampling:** decides after the trace completes, so it can keep 100 per cent of errors and slow traces; needs 100 per cent head sampling, buffering memory and trace-ID-aware routing.
        - **Adaptive sampling:** raises sampling on anomalies at low cost, but is not a guarantee of completeness.
        - **Retention:** classic X-Ray keeps 30 days; Transaction Search retention follows the `aws/spans` log group setting.
        - **Recommendation:** tail sampling in a gateway (or Transaction Search at 100 per cent span ingestion) for the payment path, with error traces retained 30 days; adaptive sampling elsewhere.

3. A saga spanning Step Functions, EventBridge and three microservices occasionally leaves orders in an inconsistent state. Explain how you would use tracing, annotations and correlation IDs to reconstruct failed sagas, and what changes to instrumentation are required.

    ??? success "Check your answer"

        A good answer covers:

        - **Correlation:** a saga or correlation ID generated at the start and carried through every event, message and state machine execution.
        - **Tracing:** enable Step Functions tracing and EventBridge propagation; annotate spans with `order_id` and `saga_id`.
        - **Reconstruction:** query traces by annotation, and logs by correlation ID, to see which steps and compensations ran.
        - **Instrumentation changes:** propagate context through all producers, log every state transition with the ID, record compensation outcomes and use span links for asynchronous hops.
        - **Detection:** alarm on sagas that start but do not complete within the expected time.

4. Estimate the monthly span ingestion volume for a service handling 2,000 requests per second with 25 spans per request at an average of 1 KB per span under 100 per cent sampling, and propose a sampling and indexing strategy that balances completeness and cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Spans per second:** 2,000 x 25 = 50,000.
        - **Volume per second:** 50,000 x 1 KB = about 50 MB per second.
        - **Daily volume:** 50 MB x 86,400 = about 4.3 TB per day; about 130 TB per 30-day month.
        - **Strategy:** keep all errors and slow traces (tail or adaptive sampling), sample successful high-volume paths at a low rate, trim span attributes, index only about 1 per cent as summaries.
        - **Validation:** estimate cost per GB from the pricing page before enabling, and set retention on `aws/spans`.

5. Plan the migration of a 30-service estate from the X-Ray SDK and daemon to OpenTelemetry before February 2027, including sequencing, propagation compatibility, testing on the trace map, rollback and training.

    ??? success "Check your answer"

        A good answer covers:

        - **Inventory:** list services, languages, SDK versions and dependencies on the daemon.
        - **Sequencing:** start with leaf services and low-risk services, migrate edge services last; deadline before end of support on 25 February 2027.
        - **Compatibility:** composite propagators (W3C and `X-Amzn-Trace-Id`), X-Ray ID generator or W3C support, X-Ray remote sampler, collectors replacing the daemon.
        - **Testing:** compare trace maps before and after in staging; confirm edges stay connected.
        - **Rollback and training:** feature flags or deployment rollback per service; training and paved-road documentation for teams.

### 7.1.3 Health Checks and Readiness Probes on AWS

#### Beginner Questions

1. List the six ALB target health states and explain `draining`.

    ??? success "Check your answer"

        A good answer covers:

        - **`initial`:** registration in progress, first checks running.
        - **`healthy` / `unhealthy`:** passing or failing checks.
        - **`unused`:** not registered, not in an enabled AZ or stopped.
        - **`unavailable`:** health checks are disabled.
        - **`draining`:** target is being deregistered; no new requests are routed to it, but in-flight requests complete until the deregistration delay elapses.

2. What are the default ALB health check interval, timeout, healthy threshold and unhealthy threshold for instance targets?

    ??? success "Check your answer"

        A good answer covers:

        - **Interval:** 30 seconds.
        - **Timeout:** 5 seconds.
        - **Healthy threshold:** 5 consecutive successes.
        - **Unhealthy threshold:** 2 consecutive failures.

3. What is the difference between an EC2 system status check and an instance status check?

    ??? success "Check your answer"

        A good answer covers:

        - **System status check:** detects problems with AWS infrastructure (host hardware, power, network); fixed by AWS or by stopping and starting or by automatic recovery.
        - **Instance status check:** detects problems in the instance's own software or configuration (OS, kernel, exhausted memory, misconfigured network); fixed by the owner.
        - **Response:** auto recovery for system checks; reboot or replace for instance checks.

4. Why should a health check endpoint not require authentication or redirect to HTTPS?

    ??? success "Check your answer"

        A good answer covers:

        - **Authentication:** the load balancer sends no credentials, so a 401 or 403 marks every target unhealthy.
        - **Redirects:** a 301 or 302 to HTTPS is not a success code by default, so targets fail.
        - **Purpose:** the endpoint should answer cheaply and simply whether this instance can serve traffic.
        - **Security:** keep the endpoint minimal, reveal no sensitive detail, and restrict access through security groups.

5. What is the deregistration delay, and what problem does it solve?

    ??? success "Check your answer"

        A good answer covers:

        - **Definition:** time a draining target remains registered so that in-flight requests can complete (default 300 seconds).
        - **Problem solved:** without it, deployments and scale-in would cut active connections and cause 502 errors.
        - **Tuning:** set slightly above the p99 request duration; long-lived connections need longer values.

#### Intermediate Questions

1. A service must stop receiving traffic within 15 seconds of failing and must not be re-admitted until it has passed checks for 30 seconds. Choose an ALB interval, timeout and thresholds, and show the arithmetic.

    ??? success "Check your answer"

        A good answer covers:

        - **Removal within 15 seconds:** interval 5 s, timeout 4 s, unhealthy threshold 2: about 2 x 5 = 10 s plus timeout, under 15 s.
        - **Re-admission after 30 seconds:** healthy threshold 6 at a 5 s interval: 6 x 5 = 30 s.
        - **Constraint:** the timeout must be shorter than the interval, and the service must reliably answer within the timeout under load.
        - **Trade-off:** short intervals detect faster but increase check traffic and flapping risk.

2. Explain how a pod readiness gate on EKS changes the behaviour of a rolling deployment behind an ALB.

    ??? success "Check your answer"

        A good answer covers:

        - **Without a gate:** a pod becomes Ready to Kubernetes before it is registered and healthy in the ALB target group, so the rollout can terminate old pods too early.
        - **With a readiness gate:** the AWS Load Balancer Controller sets a pod condition only when the target is healthy in the ALB.
        - **Effect:** the rolling update waits for ALB health, avoiding capacity gaps and 502 or 503 errors.
        - **Requirement:** IP targets and the namespace labelled for readiness gate injection.

3. Design the container health check for an SQS worker on ECS that has no inbound HTTP traffic.

    ??? success "Check your answer"

        A good answer covers:

        - **Mechanism:** container `healthCheck` command in the task definition (for example a script), because there is no ALB.
        - **What to check:** that the worker loop is alive and recently polled SQS, for example a heartbeat file updated within the last N seconds.
        - **What not to check:** downstream dependencies, which would cause mass restarts.
        - **Settings:** `startPeriod` for start-up, sensible interval, retries and timeout.
        - **Complement:** alarm on `ApproximateAgeOfOldestMessage` to detect a stalled fleet.

4. Explain calculated health checks and CloudWatch alarm-based health checks in Route 53, with one use case for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Calculated health check:** combines the status of several child checks with a threshold (for example healthy if at least two of three endpoints are healthy); use for a Region served by several endpoints.
        - **Alarm-based health check:** takes its status from a CloudWatch alarm; use for private resources Route 53 cannot reach, or for symptom metrics such as error rate.
        - **Failover use:** both can drive DNS failover records.
        - **Limitation:** alarm-based checks are only as fast as the alarm's metric and periods.

5. Put the following in the correct order and justify it: `stopTimeout`, p99 request duration, deregistration delay, application drain time.

    ??? success "Check your answer"

        A good answer covers:

        - **Order:** p99 request duration < application drain time < deregistration delay < `stopTimeout` (bounded by the platform maximum, 120 seconds on ECS).
        - **Request duration:** in-flight requests must be able to finish.
        - **Drain time:** the application stops accepting work and finishes requests after `SIGTERM`.
        - **Deregistration delay:** the load balancer stops sending new requests before the task stops.
        - **`stopTimeout`:** the container must not be killed with `SIGKILL` before draining completes.

#### Advanced Questions

1. Design health checks and failover for an active-active two-Region API on API Gateway, Lambda and DynamoDB global tables, including how a partial Regional failure (one dependency degraded) should or should not trigger failover.

    ??? success "Check your answer"

        A good answer covers:

        - **Health checks:** Route 53 checks or alarm-based checks on each Region's API symptom metrics (5xx rate, latency) and a canary per Region.
        - **Routing:** latency or weighted records with health checks, so an unhealthy Region is removed automatically.
        - **Partial failure:** a degraded dependency should trigger failover only if customers in that Region cannot be served; use symptom-based thresholds and calculated checks to avoid failing over for a minor feature.
        - **Data:** DynamoDB global tables accept writes in both Regions; design for conflict resolution and replication lag.
        - **Safety:** avoid flapping with sufficient thresholds; test failover regularly.

2. Analyse a gray failure in which one Availability Zone's targets pass health checks but return errors for 10 per cent of requests. Which AWS mechanisms detect and mitigate it, and how would you design alarms and automation around them?

    ??? success "Check your answer"

        A good answer covers:

        - **Problem:** target health checks pass because they do not exercise the failing path; only 10 per cent of real requests fail.
        - **Detection:** per-AZ ALB metrics (`HTTPCode_Target_5XX_Count`, latency), Application Signals, canaries per AZ, CloudWatch zonal autoshift or outlier detection.
        - **Mitigation:** ARC zonal shift to move traffic away from the AZ; ALB automatic target weights (anomaly mitigation).
        - **Alarms:** compare AZ error rates with the others, composite alarms for one AZ diverging.
        - **Automation:** responder or zonal autoshift that shifts traffic and notifies, with static stability capacity in remaining AZs.

3. A team proposes that the ALB health check should verify the database, the cache and two downstream services "to be safe". Write the architectural review response, including a failure scenario, the correct alternative design and the metrics that will show it works.

    ??? success "Check your answer"

        A good answer covers:

        - **Position:** the ALB health check should reflect only whether the instance itself can serve; deep dependency checks are rejected.
        - **Failure scenario:** a database blip makes every target fail together; the ALB fails open or Auto Scaling replaces healthy instances, turning a partial problem into an outage.
        - **Alternative:** shallow liveness and readiness checks; dependencies handled with timeouts, retries, circuit breakers and degraded modes.
        - **Dependency visibility:** separate alarms and dashboards on dependency health.
        - **Evidence:** dependency error metrics, health check flapping counts, availability and latency SLOs during dependency incidents.

4. Design graceful shutdown for a WebSocket-based chat service on ECS Fargate where connections last hours and deployments happen several times a day.

    ??? success "Check your answer"

        A good answer covers:

        - **Connection drain:** on `SIGTERM`, stop accepting new connections and send clients a reconnect message, closing gradually.
        - **Client behaviour:** clients reconnect with jitter to other tasks behind the load balancer.
        - **Timeouts:** deregistration delay and `stopTimeout` cannot cover hours (ECS `stopTimeout` maximum 120 s), so the application must actively migrate connections.
        - **Deployments:** rolling with small batches and minimum healthy percent high enough to absorb reconnections.
        - **State:** keep session state outside the task so reconnections are seamless.

5. Compare health-driven recovery for a stateful single-instance legacy application on EC2 with a stateless ECS service, covering status checks, automatic recovery, Auto Scaling, data protection and expected recovery times.

    ??? success "Check your answer"

        A good answer covers:

        - **Legacy EC2:** system and instance status checks; EC2 automatic recovery restores the same instance (same IP, EBS) within minutes; Auto Scaling group of one to replace a failed instance.
        - **Data protection:** EBS snapshots or AWS Backup; replacement must reattach or restore data.
        - **Stateless ECS:** container and ALB health checks; failed tasks are replaced automatically in seconds to a minute; data is outside the task.
        - **Recovery time:** minutes (and possible data loss) for legacy; seconds and no data loss for stateless.
        - **Lesson:** stateless design makes health-driven recovery simple and fast.

---

## 7.2 Centralized Logging

### 7.2.1 Log Aggregation with Amazon CloudWatch Logs

#### Beginner Questions

1. Define a log event, a log stream and a log group, and give an example of each for an ECS service.

    ??? success "Check your answer"

        A good answer covers:

        - **Log event:** one record with a timestamp and message, for example one JSON line written by a container.
        - **Log stream:** the sequence of events from one source, for example one ECS task's container.
        - **Log group:** a set of streams sharing settings, for example `/ecs/usms-orders-prod`.
        - **Configuration:** retention, KMS, metric filters and subscriptions are set on the log group.

2. Why must containerised applications write logs to standard output rather than to files?

    ??? success "Check your answer"

        A good answer covers:

        - **Ephemeral storage:** container file systems disappear when the task stops.
        - **Collection:** the runtime and log driver capture stdout and stderr without agents in the container.
        - **Twelve-factor practice:** logs as event streams decouple the application from log routing.
        - **Operations:** no log rotation or disk filling inside containers.

3. List five fields that every structured log event should contain and explain the purpose of each.

    ??? success "Check your answer"

        A good answer covers:

        - **Timestamp:** when the event occurred, in UTC ISO 8601.
        - **Level:** severity for filtering and alarms.
        - **Service (and environment):** which component produced it.
        - **Correlation ID or trace ID:** joins events from one request across services.
        - **Message or event name:** what happened; other useful fields include outcome and duration.

4. What is the default retention of a new log group, and why is this a cost risk?

    ??? success "Check your answer"

        A good answer covers:

        - **Default:** never expire.
        - **Cost risk:** storage grows indefinitely and is billed per GB-month.
        - **Compliance risk:** personal data is kept longer than necessary.
        - **Fix:** set retention per log group in IaC and enforce it with policies or automation.

5. Which IAM role, the ECS task role or the task execution role, needs permissions for the `awslogs` driver, and why?

    ??? success "Check your answer"

        A good answer covers:

        - **Role:** the task execution role.
        - **Reason:** the ECS agent creates the log stream and sends events on behalf of the task, before and independently of the application code.
        - **Permissions:** `logs:CreateLogStream` and `logs:PutLogEvents` (and `CreateLogGroup` if auto-creating).
        - **Task role:** used by the application code itself, not by the log driver.

#### Intermediate Questions

1. Write a JSON metric filter pattern that matches events where `level` is `ERROR` and `service` is `checkout`, and explain `metricValue`, `defaultValue` and dimensions.

    ??? success "Check your answer"

        A good answer covers:

        - **Pattern:** `{ $.level = "ERROR" && $.service = "checkout" }`.
        - **`metricValue`:** value published for each matching event (for example `1`, or a field such as `$.durationMs`).
        - **`defaultValue`:** value published when no events match in a period (for example `0`), avoiding gaps.
        - **Dimensions:** up to three fields from the event can become dimensions; avoid high-cardinality fields.

2. Compare the Standard and Infrequent Access log classes, and choose a class for each of: Lambda application logs used for alarms, API Gateway access logs, EKS audit logs queried monthly.

    ??? success "Check your answer"

        A good answer covers:

        - **Standard:** full features (metric filters, subscriptions, Live Tail, anomaly detection), higher ingestion price.
        - **Infrequent Access:** about half the ingestion price (storage and query prices are the same), queryable with Logs Insights, but no metric filters, subscription filters, EMF extraction, Live Tail or field indexes; the class cannot be changed after the log group is created.
        - **Lambda logs used for alarms:** Standard, because metric filters are needed.
        - **API Gateway access logs:** Standard if used for alarms or analytics in real time; Infrequent Access if only investigated occasionally.
        - **EKS audit logs queried monthly:** Infrequent Access.

3. Explain the blocking and non-blocking modes of the ECS `awslogs` driver, the June 2025 default change, and the trade-off each mode represents.

    ??? success "Check your answer"

        A good answer covers:

        - **Blocking:** writes to stdout block if logs cannot be delivered; no loss, but the application can stall.
        - **Non-blocking:** logs are buffered in memory (`max-buffer-size`, default 10m) and dropped when the buffer is full; the application keeps running.
        - **June 2025 change:** non-blocking became the default for `awslogs` on ECS (from 25 June 2025).
        - **Trade-off:** availability (non-blocking) versus completeness (blocking); choose per service and monitor drops.

4. Describe how a correlation ID flows from API Gateway through Lambda, SQS and an ECS worker, and what happens to investigations if one hop fails to propagate it.

    ??? success "Check your answer"

        A good answer covers:

        - **Origin:** generated at API Gateway (request ID) or by the first service and returned to the client.
        - **Lambda:** read from the event, added to every log line and passed in the SQS message attribute or body.
        - **ECS worker:** reads the attribute and includes it in its logs and outbound calls.
        - **Broken hop:** events after the break cannot be joined, so investigators must guess by time and content; the request cannot be reconstructed in one query.

5. Estimate the monthly ingestion cost of 15 GB per day of Standard-class logs and describe three ways to reduce it by at least half.

    ??? success "Check your answer"

        A good answer covers:

        - **Volume:** 15 GB x 30 days = 450 GB per month.
        - **Cost:** 450 x USD 0.50 = about USD 225 per month for ingestion (indicative), before storage.
        - **Reduction 1:** drop DEBUG and health-check noise at source.
        - **Reduction 2:** move suitable log groups to Infrequent Access (half the ingestion price).
        - **Reduction 3:** sample high-volume success logs or route bulk logs to S3 through Firehose, keeping errors in CloudWatch.

#### Advanced Questions

1. Design an organisation-wide logging architecture for 100 accounts across two Regions, covering centralisation rules, a Log Archive account, immutable S3 retention, KMS key ownership, service control policies and cross-account read access for security analysts.

    ??? success "Check your answer"

        A good answer covers:

        - **Account structure:** a Log Archive account and a security account in AWS Organizations.
        - **Centralisation:** CloudWatch Logs centralisation rules or subscription destinations copying logs to the central account and to S3.
        - **Immutability:** S3 Object Lock, versioning and lifecycle policies; Region-specific buckets to meet residency.
        - **Keys and guardrails:** customer managed KMS keys owned by the archive account; SCPs preventing deletion of log groups, retention changes and disabling of CloudTrail.
        - **Access:** cross-account read-only roles or OAM for security analysts, with CloudTrail auditing of access.

2. Compare CloudWatch Logs centralisation rules, cross-account subscription destinations and CloudWatch cross-account observability. For each, describe what data moves, the cost implications and one scenario where it is the best choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Centralisation rules:** copy new log events from member accounts to a central account; first copy free, extra copies charged per GB; best for an organisation-wide log store.
        - **Subscription destinations:** stream events to Kinesis, Firehose or Lambda in another account; pay for streaming services; best for feeding a SIEM or OpenSearch.
        - **Cross-account observability (OAM):** no copy, query in place; no extra storage cost; best for incident investigation across accounts.
        - **Choice factor:** whether you need a copy (retention, immutability, processing) or only visibility.

3. A regulated payments service must never lose an audit log record, yet must remain available during CloudWatch Logs throttling events. Propose a design that satisfies both requirements, discussing blocking mode, local durable buffering, Firehose and idempotent audit writes.

    ??? success "Check your answer"

        A good answer covers:

        - **Tension:** blocking mode guarantees no loss but can stall the application; non-blocking can drop records.
        - **Design:** write audit records to a durable store (for example DynamoDB or SQS) as part of the business transaction, idempotently keyed, separate from operational logs.
        - **Buffering:** local durable buffering in Fluent Bit (filesystem buffer) and Firehose to S3 for audit streams.
        - **Operational logs:** non-blocking mode so throttling never breaks request handling.
        - **Verification:** reconcile audit records against transactions and alarm on gaps.

4. Design a FireLens configuration that sends ERROR and WARN events to CloudWatch Logs for alarms, all events to Firehose for Parquet archival in S3, and drops health-check noise, and justify the cost savings with an estimate.

    ??? success "Check your answer"

        A good answer covers:

        - **Routing:** Fluent Bit sidecar via FireLens with `grep` filters excluding health-check paths.
        - **Outputs:** CloudWatch Logs output matching only ERROR and WARN; Firehose output for all events, converting to Parquet and writing to S3.
        - **Configuration:** custom Fluent Bit configuration file from S3 or the image, with filesystem buffering.
        - **Saving estimate:** if ERROR and WARN are about 10 per cent of 100 GB per day, CloudWatch ingestion drops from about USD 1,500 to about USD 150 per month; Firehose and S3 add a much smaller per-GB cost.
        - **Trade-off:** full-text search of all events now requires Athena rather than Logs Insights.

5. A security team wants automatic blocking of IP addresses after 20 failed logins in five minutes across 30 services. Compare a metric filter with an alarm, a subscription filter with Lambda, and a Logs Insights scheduled query, and design the preferred solution with its failure modes.

    ??? success "Check your answer"

        A good answer covers:

        - **Metric filter with alarm:** counts failures but cannot identify which IP or act per IP.
        - **Subscription filter with Lambda:** near real time per-event processing; can count by IP (in DynamoDB with TTL) and update a WAF IP set.
        - **Scheduled query:** simple, but delay of the schedule interval and per-GB scan cost.
        - **Preferred:** subscription filter to Lambda (or Kinesis) feeding a counter and blocking through AWS WAF IP sets with expiry, or WAF rate-based rules where possible.
        - **Failure modes:** Lambda throttling, false positives behind NAT, blocking legitimate users; include allow lists, expiry and alerts.

### 7.2.2 Log Analysis with Amazon CloudWatch Logs Insights

#### Beginner Questions

1. What are system fields in Logs Insights? Name four and explain what each contains.

    ??? success "Check your answer"

        A good answer covers:

        - **System fields:** fields CloudWatch adds to every event, prefixed with `@`.
        - **`@timestamp`:** event time.
        - **`@message`:** the raw log event.
        - **`@logStream`:** the stream that produced it.
        - **`@log`:** the log group (account and name); others include `@ingestionTime`.

2. Write a Logs Insights QL query that counts ERROR events per service in the selected time range and sorts the result.

    ??? success "Check your answer"

        A good answer covers:

        - **Query:** `filter level = "ERROR" | stats count(*) as errors by service | sort errors desc`.
        - **Explanation:** filter keeps only ERROR events, stats aggregates per service, sort orders the highest first.
        - **Prerequisite:** consistent `level` and `service` field names across services.

3. Explain what `bin(5m)` does and why it is needed to draw a chart.

    ??? success "Check your answer"

        A good answer covers:

        - **Function:** groups events into fixed time buckets, here five minutes.
        - **Use:** `stats count(*) by bin(5m)` produces a time series.
        - **Why needed:** visualisations require time-bucketed aggregates; without `bin` there is no time axis.

4. What is the billing measure for Logs Insights, and how can you see how much a query scanned?

    ??? success "Check your answer"

        A good answer covers:

        - **Billing:** per GB of data scanned (indicatively USD 0.005 per GB).
        - **Visibility:** query statistics show records and bytes scanned.
        - **Implication:** filters do not reduce cost; narrowing time range and log groups (or field indexes) does.

5. Why should field names be consistent across services, and what happens to a cross-service query when they are not?

    ??? success "Check your answer"

        A good answer covers:

        - **Consistency:** a single query can filter or group by the same field across all services.
        - **Inconsistent names:** fields like `userId`, `user_id` and `uid` force complex queries, and events with other names are silently excluded.
        - **Result:** cross-service queries are incomplete, which is dangerous during incidents.
        - **Remedy:** a shared logging library and schema.

#### Intermediate Questions

1. Write a query that computes request count, error rate and p99 latency per minute from access logs, and explain each function used.

    ??? success "Check your answer"

        A good answer covers:

        - **Query:** `stats count(*) as requests, sum(status >= 500) * 100 / count(*) as errorRatePct, pct(latency, 99) as p99 by bin(1m)`.
        - **`count(*)`:** number of requests per bucket.
        - **`sum(status >= 500)`:** counts server errors, divided by requests for a rate.
        - **`pct(latency, 99)`:** p99 latency.
        - **`bin(1m)`:** one-minute buckets for a time series.

2. Use `parse` with a regular expression to extract a user name and IP address from a legacy text log, and explain why this approach is fragile.

    ??? success "Check your answer"

        A good answer covers:

        - **Query:** `parse @message /user=(?<user>\S+)\s+ip=(?<ip>\d+\.\d+\.\d+\.\d+)/ | stats count(*) by user, ip`.
        - **Mechanism:** named capture groups become fields at query time.
        - **Fragility:** any change to log format, order or spacing silently breaks the regex.
        - **Cost and speed:** every query re-parses the text.
        - **Better:** emit structured JSON logs.

3. Compare Logs Insights QL, OpenSearch PPL and OpenSearch SQL, and choose a language for three different users: an on-call developer, an OpenSearch security analyst and a data analyst.

    ??? success "Check your answer"

        A good answer covers:

        - **Logs Insights QL:** concise, pipe-based, supports `pattern`, `diff`, `filterIndex`; suits the on-call developer.
        - **OpenSearch PPL:** piped processing language familiar to OpenSearch users; suits the OpenSearch security analyst.
        - **OpenSearch SQL:** familiar SQL with joins; suits the data analyst.
        - **Common ground:** all three query the same data and are billed the same per GB scanned.

4. Explain field indexes, facets and `filterIndex`, and describe what should and should not be indexed, with reasons.

    ??? success "Check your answer"

        A good answer covers:

        - **Field indexes:** index policies on selected fields so queries can skip events and log groups that cannot match.
        - **`filterIndex`:** restricts scanning to indexed log groups and matching events, lowering latency and cost.
        - **Facets:** low-cardinality fields offered for point-and-click filtering.
        - **Index:** high-selectivity lookup fields such as `requestId`, `correlationId`, `orderId`, `tenantId`, `traceId`.
        - **Do not index:** low-selectivity fields such as `level`, which match most events; use them as facets instead.

5. Estimate the monthly cost of a Logs Insights dashboard widget that scans 30 GB per refresh with a 10-minute auto-refresh, and propose a cheaper design.

    ??? success "Check your answer"

        A good answer covers:

        - **Per refresh:** 30 GB x USD 0.005 = USD 0.15.
        - **Refreshes:** every 10 minutes = 144 per day = USD 21.60 per day, about USD 648 per 30-day month.
        - **Cheaper:** publish the values as metrics (metric filters or EMF) and chart them, which costs a few metrics.
        - **Also:** shorten the time range, reduce the refresh rate, or use a scheduled query whose results are stored.

#### Advanced Questions

1. Design an incident-investigation toolkit for a platform of 150 services: schema standards, index policies, saved query library, runbook integration, access control for unmasking and cost guardrails.

    ??? success "Check your answer"

        A good answer covers:

        - **Schema standards:** common field names, correlation and trace IDs, JSON logging library.
        - **Index policies:** account-level field indexes on lookup IDs; facets for service, environment and status class.
        - **Saved queries:** library of investigation queries per scenario, versioned in IaC and linked from runbooks and alarms.
        - **Access control:** data protection policies masking sensitive data; `logs:Unmask` only for a small audited role.
        - **Cost guardrails:** query scope limits, monitoring of bytes scanned, metrics for dashboards.

2. A query using `filterIndex` across 5,000 log groups returned no results for an order that certainly exists. List every possible cause and how you would verify each.

    ??? success "Check your answer"

        A good answer covers:

        - **Wrong time range:** the order event lies outside the selected window.
        - **Not indexed:** the field is not indexed in the relevant log groups, or was indexed only after the event was ingested, so `filterIndex` skips it.
        - **Field mismatch:** different field name or value type (string versus number, case).
        - **Scope:** the log group is in another account or Region, or beyond the query's log group limit.
        - **Other:** the event was never logged or was dropped; verify by a plain `filter` on one known log group and by checking index policies.

3. Design an automated post-deployment verification stage using Logs Insights `pattern` and `diff`, including thresholds, handling of noise, rollback integration with CodeDeploy and the cost per deployment.

    ??? success "Check your answer"

        A good answer covers:

        - **Stage:** after deployment, run `pattern` over the new version's logs and `diff` against the previous period or version.
        - **Thresholds:** fail if new error patterns appear above a count or rate, or existing patterns grow significantly.
        - **Noise handling:** allow list of known patterns and minimum counts.
        - **Rollback:** the stage triggers CodeDeploy rollback or sets an alarm used by CodeDeploy.
        - **Cost:** bytes scanned per verification x USD 0.005; scope to the service's log group and a short window.

4. Evaluate when an organisation should move a recurring analytical workload from Logs Insights to OpenSearch Service, using query frequency, data volume, latency needs and cost as criteria, and present a break-even calculation.

    ??? success "Check your answer"

        A good answer covers:

        - **Criteria:** query frequency, data volume, latency requirements, full-text relevance and dashboard needs.
        - **Logs Insights:** no fixed cost, pay per GB scanned; best for occasional investigation.
        - **OpenSearch:** fixed cost of nodes and storage, low latency for repeated queries.
        - **Break-even:** monthly scan cost equals domain cost; for example 700 GB scanned 20 times a day costs about USD 2,100 per month, comparable to a domain of about USD 2,600.
        - **Decision:** move when queries are frequent, interactive and repeated over the same data.

5. Design a cross-account security investigation capability using CloudWatch cross-account observability, CloudTrail and VPC Flow Logs data sources, SQL joins and lookup tables of account ownership, and explain the IAM and data protection controls required.

    ??? success "Check your answer"

        A good answer covers:

        - **Visibility:** OAM links from all accounts to a security monitoring account for logs.
        - **Sources:** CloudTrail and VPC Flow Logs delivered to CloudWatch Logs (or queried through the data sources in CloudWatch).
        - **Analysis:** OpenSearch SQL joins between CloudTrail events and flow logs, enriched with lookup tables of account ownership.
        - **IAM:** least-privilege analyst roles, MFA, separate unmask permission, audit of queries via CloudTrail.
        - **Data protection:** masking policies, KMS encryption, retention controls.

### 7.2.3 Log Storage and Analytics with Amazon OpenSearch Service

#### Beginner Questions

1. What is the difference between a `keyword` and a `text` field? Give two logging fields that should be of each type.

    ??? success "Check your answer"

        A good answer covers:

        - **`keyword`:** exact-value field used for filtering, sorting and aggregations, for example `service` and `level` (or `traceId`).
        - **`text`:** analysed, tokenised field for full-text search, for example `message` and `stack_trace`.
        - **Consequence:** wrong mappings break aggregations or search, and cannot be changed without reindexing.

2. Define shard and replica, and explain why a production domain should have replicas in multiple AZs.

    ??? success "Check your answer"

        A good answer covers:

        - **Shard:** a part of an index (a Lucene index) that can live on any node.
        - **Replica:** a copy of a primary shard on a different node.
        - **Purpose:** replicas provide availability and read throughput.
        - **Multi-AZ:** replicas in different AZs mean the cluster keeps serving and loses no data if an AZ fails.

3. What does Index State Management do? Describe a simple hot-to-delete policy.

    ??? success "Check your answer"

        A good answer covers:

        - **ISM:** automates index lifecycle actions based on age, size or document count.
        - **Actions:** rollover, replica changes, force merge, migration to warm or cold, deletion.
        - **Simple policy:** hot state for indices younger than 30 days, then delete state that removes them.
        - **Benefit:** controls storage and shard counts without manual work.

4. Name the three ways of using OpenSearch in AWS (domains, Serverless, direct query) and give one suitable use for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Managed domains:** clusters you size; suit continuous, high-volume log analytics with dashboards.
        - **Serverless:** collections with automatic capacity; suit variable workloads without cluster management.
        - **Direct query:** query data in S3 or CloudWatch Logs without indexing; suits occasional analysis of archived data.

5. Why is a public OpenSearch endpoint with an access policy allowing all principals dangerous for log data?

    ??? success "Check your answer"

        A good answer covers:

        - **Exposure:** anyone on the internet can read or delete logs.
        - **Content:** logs contain personal data, tokens and internal architecture.
        - **Attacks:** ransomware and data deletion of exposed clusters are common.
        - **Fix:** VPC access, fine-grained access control, IAM-based access policies with specific principals, encryption.

#### Intermediate Questions

1. A service produces 120 GiB of logs per day. Using the AWS sizing formula, choose the number of primary shards per daily index and justify your choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Formula:** (source data + room to grow) x (1 + indexing overhead) / desired shard size.
        - **Calculation:** 120 GiB x 1.1 = 132 GiB per daily index.
        - **Shard size:** target 30 to 50 GiB for logs: 132 / 40 = about 3.3, so 4 primary shards of about 33 GiB (room for growth).
        - **Balance:** align with the number of data nodes (or a multiple) for even indexing.

2. Compare four paths for moving CloudWatch Logs data into OpenSearch (Lambda subscription, Firehose, Kinesis with OpenSearch Ingestion, direct query) in terms of latency, operations and cost.

    ??? success "Check your answer"

        A good answer covers:

        - **Lambda subscription:** near real time, simple, but limited by Lambda concurrency and error handling; low cost at small volume.
        - **Firehose:** buffered (tens of seconds to minutes), managed retries and S3 backup; low operations.
        - **Kinesis with OpenSearch Ingestion:** seconds of latency, rich processing and routing, DLQs; two services to pay for.
        - **Direct query:** no ingestion; query on demand; latency per query, no indexing cost; for occasional analysis.

3. Explain rollover, aliases and data streams, and why size-based rollover is preferred for logs.

    ??? success "Check your answer"

        A good answer covers:

        - **Rollover:** create a new index when the current one reaches a size, age or document count.
        - **Alias:** a stable name for writing and reading across indices.
        - **Data streams:** append-only abstraction that manages backing indices and rollover for time series.
        - **Size-based rollover:** keeps shard sizes in range regardless of traffic changes, unlike fixed daily indices.

4. Write a query DSL request that counts ERROR events per service over the last hour using filter context, and explain why filter context is used.

    ??? success "Check your answer"

        A good answer covers:

        ```json
        {"size":0,"query":{"bool":{"filter":[{"term":{"level":"ERROR"}},{"range":{"@timestamp":{"gte":"now-1h"}}}]}},"aggs":{"by_service":{"terms":{"field":"service"}}}}
        ```

        - **Filter context:** `bool.filter` clauses are yes or no matches without relevance scoring.
        - **Benefit:** faster and cacheable, which suits exact log filters.
        - **Aggregation:** `terms` on the `keyword` field `service` counts errors per service; `size: 0` returns only aggregations.

5. Explain the purpose of each OpenSearch Serverless policy type (encryption, network, data access, data lifecycle) and design them for a logging collection.

    ??? success "Check your answer"

        A good answer covers:

        - **Encryption policy:** assigns AWS owned or customer managed KMS keys to collections; required before creation.
        - **Network policy:** public or VPC endpoint access to collections and dashboards; use VPC endpoints for logs.
        - **Data access policy:** which principals can read or write which collections and indexes.
        - **Data lifecycle policy:** retention per index pattern (for example 30 days for application logs).
        - **Design:** time series collection, customer managed key, VPC-only access, ingest role write-only, analyst read-only.

#### Advanced Questions

1. Design an organisation-wide log analytics platform combining CloudWatch Logs, Logs Insights, OpenSearch domains, direct query and an S3 archive, and justify which data goes where, for how long, and why.

    ??? success "Check your answer"

        A good answer covers:

        - **CloudWatch Logs:** all operational logs, short retention, alarms via metric filters.
        - **Logs Insights:** investigation and ad hoc queries.
        - **OpenSearch domain:** frequently searched security and application logs requiring dashboards and full-text search, for example 30 days hot and longer in UltraWarm.
        - **Direct query:** occasional queries over S3 or older CloudWatch data without indexing.
        - **S3 archive:** long-term retention with Object Lock, queried with Athena when needed.

2. Produce a cost comparison for 200 GB per day of logs retained 90 days, comparing Logs Insights-only, an OpenSearch domain with UltraWarm, and OpenSearch Serverless, under low and high query-frequency assumptions, and identify the break-even point.

    ??? success "Check your answer"

        A good answer covers:

        - **Volume:** 200 GB per day x 90 days = 18 TB retained; 6 TB ingested per month.
        - **Logs Insights-only:** ingestion about USD 3,000 per month (Standard) plus storage; low queries (for example 10 queries over one day of data) cost about USD 300 per month, high queries (200 per day) about USD 6,000 per month.
        - **OpenSearch domain with UltraWarm:** largely fixed cost of nodes and storage, several thousand USD per month regardless of queries.
        - **Serverless:** OCU hours plus storage, with a minimum compute footprint; cost grows with query load.
        - **Break-even:** Logs Insights is cheapest at low query frequency; the domain wins when monthly scan cost exceeds its fixed cost. Figures are indicative and must be checked against current pricing.

3. Evaluate the 2026 log-optimised OpenSearch engine for a new security analytics platform: benefits, constraints (engine mode permanence, query DSL support, instance families, tiering) and a migration and validation plan.

    ??? success "Check your answer"

        A good answer covers:

        - **Benefits:** columnar Parquet storage with full-text search, faster analytical queries and lower storage for logs.
        - **Constraints:** engine mode chosen at creation and permanent; query DSL not supported at launch; OpenSearch 3.5 or later on OpenSearch Optimized instances (OR1, OR2, OM2 hot, OI2 warm); no cold tier.
        - **Implications:** clients, dashboards and alerting that use query DSL must change to PPL or SQL.
        - **Plan:** test domain, replay representative data, validate queries and monitors, compare performance and cost, then migrate gradually.

4. Design a zero-data-loss, buffered ingestion architecture for a regulated platform, covering Fluent Bit buffering, OpenSearch Ingestion persistent buffers, DLQs, replay procedures and monitoring, and analyse its failure modes.

    ??? success "Check your answer"

        A good answer covers:

        - **Fluent Bit:** filesystem buffering with retry limits so collectors survive back-end outages.
        - **OpenSearch Ingestion:** persistent buffers for push sources (up to 72 hours of retention during sink outages).
        - **DLQs:** failed documents to S3 for later replay.
        - **Replay:** documented procedures and idempotent document IDs to avoid duplicates.
        - **Monitoring:** buffer usage, DLQ objects, ingestion latency; failure modes include disk-full collectors, mapping errors and long outages beyond buffer capacity.

5. A cluster with 40,000 shards is unstable. Diagnose the causes, design a remediation plan (consolidation, reindexing, template changes, ISM) that avoids downtime, and define guardrails to prevent recurrence.

    ??? success "Check your answer"

        A good answer covers:

        - **Cause:** too many small shards from per-service daily indices with many primaries and replicas, overloading cluster state and heap.
        - **Remediation:** consolidate indices into data streams, reindex old small indices into fewer larger ones, change templates to fewer primaries and size-based rollover.
        - **ISM:** delete or shrink old indices, move data to warm tiers.
        - **No downtime:** perform reindexing gradually with aliases, outside peak.
        - **Guardrails:** shard count alarms, template reviews and limits on index creation.

---

## 7.3 Observability and Alerting

### 7.3.1 Creating CloudWatch Dashboards and Alarms

#### Beginner Questions

1. What is the difference between a CloudWatch dashboard and a CloudWatch alarm, and why is a dashboard not a substitute for an alarm?

    ??? success "Check your answer"

        A good answer covers:

        - **Dashboard:** a visual display of metrics and logs for people to look at.
        - **Alarm:** an automated evaluation of a metric against a condition that changes state and triggers actions.
        - **Difference:** dashboards require someone to be watching; alarms act 24 hours a day.
        - **Use:** dashboards for diagnosis and context, alarms for detection.

2. Name the three alarm states and give one cause of each.

    ??? success "Check your answer"

        A good answer covers:

        - **`OK`:** metric within threshold, for example normal error rate.
        - **`ALARM`:** threshold breached for the required data points, for example 5xx rate above 1 per cent.
        - **`INSUFFICIENT_DATA`:** not enough data, for example a new alarm or a metric that stopped being published.

3. Explain why latency alarms should use percentiles rather than averages.

    ??? success "Check your answer"

        A good answer covers:

        - **Skew:** latency distributions are skewed; averages hide slow tails.
        - **User experience:** p99 shows what the slowest users experience.
        - **SLOs:** latency objectives are defined on percentiles.
        - **Example:** an average of 200 ms can coexist with 1 per cent of users waiting over 5 s.

4. Calculate the allowed downtime per 30 days for SLOs of 99.5, 99.9 and 99.99 per cent.

    ??? success "Check your answer"

        A good answer covers:

        - **30 days:** 43,200 minutes.
        - **99.5 per cent:** 216 minutes, about 3 hours 36 minutes.
        - **99.9 per cent:** 43.2 minutes.
        - **99.99 per cent:** about 4.3 minutes (4 minutes 19 seconds).

5. List four actions a CloudWatch alarm can perform directly.

    ??? success "Check your answer"

        A good answer covers:

        - **Notify:** publish to an SNS topic.
        - **Lambda:** invoke a function directly.
        - **Auto Scaling:** run a scaling policy.
        - **EC2 actions:** stop, terminate, reboot or recover an instance; others include Systems Manager OpsItems and investigations.

#### Intermediate Questions

1. Write a metric math expression for an ALB 5xx error rate that avoids false alarms at low traffic, and explain each part.

    ??? success "Check your answer"

        A good answer covers:

        - **Expression:** `IF(m_requests > 100, 100 * m_5xx / m_requests, 0)` where `m_5xx` is `HTTPCode_Target_5XX_Count` and `m_requests` is `RequestCount`, both Sum per minute.
        - **Rate:** dividing errors by requests produces a percentage independent of traffic level.
        - **Low-traffic guard:** below a minimum request count the result is 0, so one error at night does not page.
        - **Missing data:** treat appropriately (often `notBreaching`).

2. A service has an SLO of 99.9 per cent over 30 days and handled 40 million requests in the first 10 days with 25,000 failures. Calculate the budget consumed and the average burn rate so far, and state what the team should do.

    ??? success "Check your answer"

        A good answer covers:

        - **Projected requests:** 40 million in 10 days suggests about 120 million in 30 days; budget = 0.1 per cent x 120 million = 120,000 failures.
        - **Consumed:** 25,000 / 120,000 = about 21 per cent of the budget in a third of the window.
        - **Burn rate:** error rate 25,000 / 40 million = 0.0625 per cent; 0.0625 / 0.1 = 0.625.
        - **Action:** burn rate is below 1, so the budget will last the window; normal releases can continue, while monitoring for spikes.

3. Explain composite alarm action suppression, including the wait period and the extension period, with an example.

    ??? success "Check your answer"

        A good answer covers:

        - **Suppression:** a composite alarm's actions are suppressed while a suppressor alarm (for example a database failover alarm) is in `ALARM`.
        - **Wait period:** how long the composite waits for the suppressor to enter `ALARM` before acting anyway (for example 120 s).
        - **Extension period:** how long suppression continues after the suppressor returns to `OK` (for example 300 s).
        - **Example:** during a planned failover, downstream service alarms do not page their teams.

4. Compare anomaly detection alarms and static threshold alarms. For which metrics is each appropriate?

    ??? success "Check your answer"

        A good answer covers:

        - **Anomaly detection:** learns a band from history including daily and weekly seasonality; suits traffic volume, request counts and drops in traffic.
        - **Static thresholds:** fixed values; suit metrics with clear limits such as error rate, p99 latency against an SLO, disk space or queue age.
        - **Limitations:** anomaly detection needs history and can learn bad behaviour; static thresholds need tuning per service.

5. Describe how an alarm mute rule behaves if the alarm is still in `ALARM` when the mute window ends, and how this differs from `DisableAlarmActions`.

    ??? success "Check your answer"

        A good answer covers:

        - **Behaviour:** during the mute window the alarm keeps evaluating; only actions are muted.
        - **End of window:** if the alarm is still in the state in which it was muted (for example `ALARM`), CloudWatch automatically re-triggers the muted actions, so the problem is not lost; alarm state-change events still reach EventBridge throughout.
        - **`DisableAlarmActions`:** turns off actions indefinitely until someone re-enables them, with no automatic end and no catch-up notification.
        - **Risk:** forgotten disabled actions are a common cause of missed incidents.

#### Advanced Questions

1. Design a complete SLO-based alerting scheme for a payments API on ECS with a 99.95 per cent availability SLO and a p99 latency SLO of 400 ms, including burn-rate windows and thresholds, composite alarms, severities, routing, exclusion windows and deployment integration.

    ??? success "Check your answer"

        A good answer covers:

        - **SLIs:** availability from ALB or Application Signals (5xx ratio) and p99 latency.
        - **Burn-rate alarms:** fast burn (for example 14.4x over 1 hour and 5 minutes) pages; slow burn (for example 6x over 6 hours and 30 minutes, or 1x over 3 days) creates a ticket.
        - **Composite alarms:** combine long and short windows; suppress during dependency failover.
        - **Routing and severities:** SNS topics per severity to the paging tool and chat; exclusion windows with mute rules for maintenance.
        - **Deployment integration:** alarms attached to ECS deployment circuit breakers or CodeDeploy for automatic rollback.

2. A platform team wants every one of 600 Lambda functions and 80 ECS services in production to have error alarms without teams creating them manually. Compare per-resource alarms generated by IaC with multi time series Metrics Insights alarms in cost, quota, precision, notification routing and operational overhead, and propose a hybrid design.

    ??? success "Check your answer"

        A good answer covers:

        - **Per-resource IaC alarms:** precise thresholds and routing per resource; 680-plus alarms cost and quota management; drift if teams bypass IaC.
        - **Metrics Insights multi time series alarms:** one alarm per query with `GROUP BY` evaluates each contributor; lower overhead, new resources covered automatically.
        - **Precision:** a shared threshold may not suit all resources.
        - **Routing:** contributor-level events through EventBridge to owners using tags.
        - **Hybrid:** fleet-wide Metrics Insights alarms as a baseline, plus per-resource SLO alarms for critical services.

3. Critically evaluate the claim "we have 1,200 CloudWatch alarms, so our system is well monitored". What evidence would you ask for, and what metrics would you use to judge the quality of an alerting system?

    ??? success "Check your answer"

        A good answer covers:

        - **Claim flaw:** quantity does not equal coverage or quality.
        - **Evidence:** do alarms cover user-facing symptoms and SLOs? Are they routed and actionable with runbooks?
        - **Quality metrics:** precision (pages leading to action), recall (incidents detected by alarms rather than customers), time to detect, pages per week per engineer.
        - **Hygiene:** alarms long in `ALARM` or `INSUFFICIENT_DATA`, duplicates, disabled actions.

4. Design a cross-account monitoring architecture that allows a central operations team to see and alarm on all workloads while service teams keep ownership of their alarms. Include identity, deployment, dashboards, routing and audit of silencing actions.

    ??? success "Check your answer"

        A good answer covers:

        - **Identity:** OAM sink in a monitoring account; operations team read-only; service teams own alarms in their accounts.
        - **Deployment:** alarms defined in each service's IaC; central baseline alarms through StackSets.
        - **Dashboards:** cross-account dashboards in the monitoring account.
        - **Routing:** EventBridge forwarding of alarm state changes to a central bus, routed by tags to owners and central operations.
        - **Audit:** CloudTrail alerts on `DisableAlarmActions`, `DeleteAlarms` and mute rule changes.

5. Explain how detection latency is composed for an alarm on a custom metric published through EMF from an ECS service, and propose design changes to reduce detection time for a critical signal from about eight minutes to under two minutes, with their cost implications.

    ??? success "Check your answer"

        A good answer covers:

        - **Components:** EMF buffering and flush in the application or agent; log delivery; metric extraction delay; metric period; evaluation periods (M out of N); alarm evaluation; SNS delivery.
        - **Example:** a 5-minute period with 1 of 1 evaluation plus extraction delay easily reaches about 8 minutes.
        - **Changes:** 1-minute (or high-resolution) periods, fewer data points to alarm (for example 2 of 3), faster flush intervals.
        - **Alternatives:** use AWS-vended metrics (ALB) or `PutMetricData` directly for the critical signal.
        - **Cost:** high-resolution metrics and alarms are charged more; more false alarms possible with shorter windows.

### 7.3.2 Automated Incident Response with AWS Lambda

#### Beginner Questions

1. Define MTTD, MTTA and MTTR and state which one automated rollback improves most.

    ??? success "Check your answer"

        A good answer covers:

        - **MTTD:** mean time to detect a problem.
        - **MTTA:** mean time to acknowledge an alert.
        - **MTTR:** mean time to recover or restore service.
        - **Rollback:** automated rollback improves MTTR most (by mitigating without waiting for humans).

2. List three ways a CloudWatch alarm can cause a Lambda function to run.

    ??? success "Check your answer"

        A good answer covers:

        - **Alarm action:** the alarm lists the Lambda function ARN and invokes it directly.
        - **EventBridge rule:** matches `CloudWatch Alarm State Change` events and targets the function.
        - **SNS subscription:** the alarm publishes to a topic to which the function subscribes.

3. What is a kill switch in incident automation, and give two ways to implement one on AWS.

    ??? success "Check your answer"

        A good answer covers:

        - **Kill switch:** a mechanism to disable automated responses instantly without redeploying.
        - **Implementation 1:** a Systems Manager Parameter Store or AppConfig flag that responders check before acting.
        - **Implementation 2:** disabling the EventBridge rule, or setting reserved concurrency of the function to zero.

4. Explain why a responder should act only on transitions into the `ALARM` state.

    ??? success "Check your answer"

        A good answer covers:

        - **Transitions:** alarms emit events on every state change, including back to `OK`.
        - **Correctness:** acting on `OK` or `INSUFFICIENT_DATA` could undo recovery or act on noise.
        - **Idempotency:** acting only on entry into `ALARM` limits duplicate actions.

5. What was AWS Chatbot renamed to, and what are two things it lets engineers do from a chat channel?

    ??? success "Check your answer"

        A good answer covers:

        - **New name:** Amazon Q Developer in chat applications (renamed in February 2025).
        - **Capability 1:** receive alarm and event notifications in Slack or Microsoft Teams.
        - **Capability 2:** run CLI commands, custom actions and runbooks from the channel, under the channel's IAM permissions.

#### Intermediate Questions

1. Write the EventBridge event pattern that matches transitions into `ALARM` for all alarms whose names begin with `prod-payments-`, and explain how you would exclude events caused by the responder itself for a CloudTrail-based rule.

    ??? success "Check your answer"

        A good answer covers:

        ```json
        {"source":["aws.cloudwatch"],"detail-type":["CloudWatch Alarm State Change"],"detail":{"alarmName":[{"prefix":"prod-payments-"}],"state":{"value":["ALARM"]}}}
        ```

        - **Pattern:** matches alarm state changes whose name begins with the prefix and whose new state is `ALARM`.
        - **CloudTrail exclusion:** for `AWS API Call via CloudTrail` rules, exclude the responder's role with `"userIdentity":{"sessionContext":{"sessionIssuer":{"userName":[{"anything-but":"responder-role"}]}}}` (or match on the principal ARN).
        - **Purpose:** prevents the responder from triggering itself in a loop.

2. Describe the design of a DLQ redrive responder that avoids simply moving messages back into the DLQ.

    ??? success "Check your answer"

        A good answer covers:

        - **Diagnosis first:** inspect sample messages and the failure reason before redriving.
        - **Fix first:** redrive only after the cause (bug, dependency) is fixed or the messages are known transient failures.
        - **Controlled redrive:** use the SQS redrive API with a rate limit, and stop if failures recur.
        - **Poison messages:** move permanently invalid messages to a parking store for investigation.
        - **Guardrails:** count redrive attempts per message and alarm on loops.

3. Compare the three human-approval mechanisms available on AWS and choose one for an Aurora failover, justifying your choice.

    ??? success "Check your answer"

        A good answer covers:

        - **Chat custom action:** button in Slack or Teams invoking a Lambda function; fast but lightweight audit.
        - **Step Functions callback (`.waitForTaskToken`):** workflow pauses for approval; supports timeouts and multi-step orchestration.
        - **SSM Automation `aws:approve`:** named IAM approvers, minimum approvals, audited.
        - **Aurora failover choice:** SSM Automation `aws:approve` (or Step Functions where failover is part of a larger workflow), because failover is a high-impact infrastructure action requiring formal approval and audit.

4. Explain how reserved concurrency serves two different purposes for a responder function.

    ??? success "Check your answer"

        A good answer covers:

        - **Protection of downstreams:** a small reserved concurrency limits how many simultaneous actions the responder can take, preventing a storm of actions.
        - **Guaranteed capacity:** reserved concurrency ensures the responder can run even when other functions exhaust account concurrency during an incident.
        - **Kill switch:** setting it to zero disables the responder immediately.

5. Describe how to test a new responder safely before it is allowed to act in production.

    ??? success "Check your answer"

        A good answer covers:

        - **Dry-run mode:** the responder logs what it would do without acting.
        - **Test environments:** trigger with `SetAlarmState` and recorded real events in staging.
        - **Fault injection:** AWS Fault Injection Service experiments to create real alarm conditions.
        - **Gradual enablement:** enable in production for low-risk resources first with notifications, then expand.
        - **Review:** verify idempotency, permissions and kill switch.

#### Advanced Questions

1. Design an automated response system for a payments platform on ECS and Aurora across two Regions, including which responses are fully automated, which require approval, how regional impairments are handled, and how the automation itself is protected from abuse.

    ??? success "Check your answer"

        A good answer covers:

        - **Fully automated:** low-risk, well-understood actions such as ECS deployment rollback, task replacement, scaling, and EC2 recovery.
        - **Approval required:** Aurora cross-Region failover, Region evacuation and data-changing actions.
        - **Regional impairments:** responders and runbooks deployed in both Regions, with static stability and no dependency on the impaired Region's control plane.
        - **Protection:** least-privilege roles, scoped resources, rate limits, kill switches, CloudTrail audit and change control on the automation code.
        - **Verification:** each action checks recovery and escalates if it fails.

2. Critically evaluate the proposal "let an AI agent automatically remediate any incident it diagnoses". Discuss benefits, risks, controls and a staged adoption plan.

    ??? success "Check your answer"

        A good answer covers:

        - **Benefits:** speed and around-the-clock coverage; analysis of many signals.
        - **Risks:** wrong diagnosis, destructive or unbounded actions, hallucinated changes, security abuse and loss of human understanding.
        - **Controls:** allow list of actions, least privilege, approval for high-impact actions, dry-run, rate limits, audit and kill switch.
        - **Staged adoption:** suggestions only, then actions with approval, then automation for narrow low-risk classes after measured accuracy.

3. Propose a metrics framework to evaluate the effectiveness of an organisation's incident automation, including how to detect automation that is causing harm.

    ??? success "Check your answer"

        A good answer covers:

        - **Effectiveness metrics:** MTTR reduction, number of incidents mitigated automatically, time from trigger to action.
        - **Quality metrics:** success rate of actions, false positive triggers, rollback of automated actions.
        - **Harm detection:** incidents where automation worsened impact, loops, action counts per hour, alerts when actions exceed limits.
        - **Review:** post-incident reviews include automation behaviour.

4. A GuardDuty finding triggers isolation of an EKS worker node. Design the full workflow, including Kubernetes-level actions, evidence preservation, capacity replacement and the permissions required.

    ??? success "Check your answer"

        A good answer covers:

        - **Trigger:** GuardDuty finding through EventBridge to Step Functions.
        - **Kubernetes actions:** cordon the node, label or isolate pods with network policies, drain or evict non-affected workloads.
        - **Evidence:** EBS snapshots, memory capture if possible, retain the node with an isolating security group; preserve logs.
        - **Capacity:** Auto Scaling or Karpenter replaces the node; detach from the node group without terminating.
        - **Permissions:** EC2 (security groups, snapshots, tags), EKS access for cordon and drain, least privilege and audit.

5. Explain how you would use AWS Fault Injection Service, EventBridge archive and replay, and recorded events to build a continuous test suite for responders, and how that suite fits into the CI/CD pipeline from Unit V.

    ??? success "Check your answer"

        A good answer covers:

        - **FIS:** inject real faults (latency, task stops, AZ impairment) to trigger alarms and responders end to end.
        - **Archive and replay:** replay recorded EventBridge events into a test bus to exercise responders with real event shapes.
        - **Recorded events:** stored sample events as unit and integration test fixtures.
        - **CI/CD integration:** run tests in pipeline stages before responder code reaches production; block deployments on failures.
        - **Continuous:** scheduled experiments verify responders still work as the system changes.

### 7.3.3 Performance Optimization Using AWS Tools

#### Beginner Questions

1. Define latency, throughput, utilisation and saturation, giving one CloudWatch metric that measures each.

    ??? success "Check your answer"

        A good answer covers:

        - **Latency:** time to serve a request, for example ALB `TargetResponseTime`.
        - **Throughput:** work per unit time, for example `RequestCount`.
        - **Utilisation:** proportion of resource busy, for example `CPUUtilization`.
        - **Saturation:** queued work beyond capacity, for example SQS `ApproximateAgeOfOldestMessage` or Lambda `Throttles`.

2. What does AWS Compute Optimizer do, and why does it need the CloudWatch agent for EC2 memory recommendations?

    ??? success "Check your answer"

        A good answer covers:

        - **Function:** analyses historical utilisation and configuration of EC2, Auto Scaling groups, EBS, Lambda, ECS on Fargate and other resources, and recommends right-sizing.
        - **Memory:** EC2 memory utilisation is not visible to the hypervisor, so the CloudWatch agent must publish it.
        - **Without it:** recommendations ignore memory and may downsize memory-bound instances unsafely.

3. What replaced the RDS Performance Insights console, and what are its two modes?

    ??? success "Check your answer"

        A good answer covers:

        - **Replacement:** CloudWatch Database Insights replaces the Performance Insights console experience (end of life 31 July 2026).
        - **Standard mode:** load analysis with 7 days free retention.
        - **Advanced mode:** fleet-wide views, per-query statistics, execution plans, lock analysis, longer retention, charged per vCPU-hour or ACU-hour.

4. Name four kinds of load test and the question each answers.

    ??? success "Check your answer"

        A good answer covers:

        - **Load test:** expected peak load: does the system meet its SLOs?
        - **Stress test:** beyond peak: where and how does it break?
        - **Spike test:** sudden surge: does scaling react fast enough?
        - **Soak test:** long duration: are there leaks or degradation over time?

5. Why is average latency a poor measure of user experience?

    ??? success "Check your answer"

        A good answer covers:

        - **Skew:** a few slow requests are hidden by many fast ones.
        - **User impact:** users experience individual requests, not averages.
        - **Better:** percentiles (p95, p99) and the share of requests within a threshold.

#### Intermediate Questions

1. Using Little's Law, calculate the average Lambda concurrency for 250 requests per second at 400 ms average duration, and explain what happens if duration triples.

    ??? success "Check your answer"

        A good answer covers:

        - **Little's Law:** concurrency = arrival rate x duration = 250 x 0.4 = 100 concurrent executions.
        - **Tripled duration:** 1.2 s gives 300 concurrent executions with the same traffic.
        - **Consequences:** risk of reaching account or reserved concurrency limits, throttling, more database connections and higher cost.
        - **Lesson:** a slow dependency increases concurrency without more traffic.

2. Describe how you would use Application Signals, X-Ray and Database Insights, in order, to find the cause of a latency regression after a deployment.

    ??? success "Check your answer"

        A good answer covers:

        - **Application Signals:** identify which service and operation regressed, and when, against the deployment time.
        - **X-Ray traces:** inspect slow traces to find which span (for example a database call) accounts for the added time.
        - **Database Insights:** examine the DB load, top SQL and wait events, and execution plan changes.
        - **Conclusion:** correlate with the deployment change and roll back or fix.

3. Explain the inputs and strategies of Lambda Power Tuning and when you would choose each strategy.

    ??? success "Check your answer"

        A good answer covers:

        - **Inputs:** function ARN, memory values, invocations per value, payload, parallel invocation option and strategy.
        - **`cost`:** cheapest configuration; for batch and asynchronous work.
        - **`speed`:** fastest configuration; for latency-sensitive user-facing functions.
        - **`balanced`:** weighted trade-off between cost and speed for general functions.

4. Compare Trusted Advisor and Compute Optimizer in scope, depth, cost and access requirements.

    ??? success "Check your answer"

        A good answer covers:

        - **Trusted Advisor:** broad checks across cost, security, performance, fault tolerance and quotas; full checks need Business Support+ or higher.
        - **Compute Optimizer:** deep ML-based right-sizing recommendations for compute resources based on utilisation; free basic recommendations, opt-in required.
        - **Depth:** Trusted Advisor is checklist-based; Compute Optimizer analyses metrics over 14 to 93 days.
        - **Use together:** Trusted Advisor for broad hygiene, Compute Optimizer for right-sizing.

5. List five drivers of observability cost and one lever for each, identifying which reductions would be unsafe.

    ??? success "Check your answer"

        A good answer covers:

        - **Metric cardinality:** limit dimensions (unsafe if it removes dimensions needed for alarms).
        - **Log volume:** drop DEBUG, use Infrequent Access (unsafe if it removes error or audit logs).
        - **Retention:** shorter retention (unsafe if below compliance or investigation needs).
        - **Traces:** lower sampling (unsafe if errors are no longer captured).
        - **Queries and dashboards:** replace Logs Insights widgets with metrics; canary and RUM frequency or sampling (unsafe if detection of critical journeys degrades).

#### Advanced Questions

1. Design a performance and capacity plan for a national examination results portal expecting fifty times normal traffic for two hours, covering load testing, database preparation, caching, pre-scaling, alarms and responders.

    ??? success "Check your answer"

        A good answer covers:

        - **Load testing:** realistic tests at and above 50x traffic in a production-like environment, including spike tests.
        - **Database:** scale up or add read replicas, connection pooling with RDS Proxy, query tuning, caching results.
        - **Caching:** CloudFront for static and cacheable result pages; ElastiCache for hot data.
        - **Pre-scaling:** scheduled scaling and provisioned concurrency before the event; raise quotas in advance.
        - **Alarms and responders:** SLO burn-rate alarms, queue depth and throttles, runbooks and approved responders ready; war room during the two hours.

2. Critically evaluate automatically applying Compute Optimizer recommendations in production. Propose guardrails, exclusions and a rollout process.

    ??? success "Check your answer"

        A good answer covers:

        - **Risks:** recommendations are based on historical data and may miss peaks, memory or licence constraints.
        - **Guardrails:** exclude critical or stateful resources, require minimum look-back and performance risk thresholds.
        - **Rollout:** apply to non-production first, then canary groups in production with monitoring and rollback.
        - **Governance:** change records and owner approval for each change.

3. A multi-tenant SaaS platform wants to report cost per tenant and latency per tenant. Design the telemetry, dimensions and analysis without creating a cardinality explosion.

    ??? success "Check your answer"

        A good answer covers:

        - **Tenant ID:** in logs and trace annotations, not as a metric dimension for all tenants.
        - **Aggregated metrics:** dimensions such as tenant tier, not tenant ID.
        - **Analysis:** Logs Insights or Contributor Insights for per-tenant latency and top tenants.
        - **Cost per tenant:** combine usage logs with cost allocation tags and the Cost and Usage Report, processed in Athena.

4. Design a CI/CD performance gate that is reliable despite natural variance in load-test results. Discuss baselines, statistical thresholds, test duration and false failures.

    ??? success "Check your answer"

        A good answer covers:

        - **Baselines:** compare against a rolling baseline from previous builds in the same environment.
        - **Statistical thresholds:** confidence intervals or relative thresholds (for example p99 more than 10 per cent worse than baseline over multiple runs).
        - **Duration:** long enough runs with warm-up periods to reduce noise.
        - **False failures:** repeat runs before failing; separate hard limits (SLO breach) from soft warnings.

5. Compare the optimisation approach for a latency-sensitive Java service on ECS, an I/O-bound Python Lambda function and an Aurora PostgreSQL database, identifying the key tool, key metric and most likely remedy for each.

    ??? success "Check your answer"

        A good answer covers:

        - **Java on ECS:** key tool X-Ray or Application Signals plus Container Insights; key metric p99 latency and JVM garbage collection or CPU; likely remedy JVM tuning, right-sizing CPU and memory.
        - **I/O-bound Python Lambda:** key tool X-Ray and Lambda Power Tuning; key metric duration of downstream calls; remedy parallel or asynchronous I/O, connection reuse, caching.
        - **Aurora PostgreSQL:** key tool Database Insights; key metric DB load versus vCPUs and wait events; remedy query and index tuning or scaling.

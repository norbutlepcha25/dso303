# Known Issues on Floci 2.0.1 and Alternatives

Some lab features are not implemented, or not retained, by **Floci 2.0.1**. This page lists each one with an alternative you can run, and states what the alternative does and does not prove. These are emulator limitations, not reasons to skip a lab: complete every step that works and use the alternative only for the feature that fails.

!!! info "Check your Floci version first"
    ```bash
    floci version
    ```

    The issues below were recorded on server `2.0.1`. A newer build may fix some of them; a separate test of Floci 2.2.0 accepted dashboards and metric-filter creation but still rejected X-Ray and scheduled-action listing. Do not upgrade the course environment mid-semester without testing on an empty one first.

## Choose a route

| Lab | Issue on Floci 2.0.1 | Alternative |
| --- | --- | --- |
| 01, 02, 04, 07 | None recorded on the main path | Follow the lab as written |
| [03](#lab-03-ec2) | Bootstrap expects `dnf`/nginx; the AMI is Amazon Linux 2 | Local Python static HTTP server |
| [05](#lab-05-alb) | ECS service does not retain `loadBalancers` on readback | Local path-based router demo |
| [06](#lab-06-auto-scaling) | `PutScheduledAction` unsupported; alarms do not change ECS desired count | Local worker controller; manual ECS scale |
| [08](#lab-08-eks-scaling) | `update-nodegroup-config` fails | The Lab 8 HPA drill (pod scaling) |
| [09](#lab-09-security) | Permissions boundary and IMDSv2 `HttpTokens` not reflected on readback | Policy-decision model and token-gated endpoint |
| [10](#lab-10-lambda) | No global edge execution locally | Lab 10's own edge simulator |
| [11](#lab-11-cicd-pipeline) | `aws/codebuild/standard:7.0` image cannot be pulled | `python:3.12-slim` build image |
| [12](#lab-12-ecs-pipeline-deploy) | CodePipeline ECS deploy provider unavailable; `DescribeImages` inconsistent | Manual artifact-driven deploy (Lab 12 Steps 10-11); `docker pull` check |
| [13](#lab-13-monitoring) | Metric filters, Logs Insights, X-Ray, composite alarms, alarm history, dashboards | Direct metrics, local aggregation and correlation |
| [14](#lab-14-checkpoint) | Evidence must show which features ran natively | Label original and alternative evidence |

## Before you use an alternative

Diagnose first. Most failures are not emulator limitations.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/whoami.sh
./scripts/utilities/verify-lab-NN.sh      # the lab you are working on
```

| Symptom | Meaning |
| --- | --- |
| `Could not connect to the endpoint URL`, exit code 255 | Floci is not running. Not a feature limitation |
| `UnsupportedOperation` / `not implemented` / HTTP 501 | Emulator capability gap. Use this page |
| Command succeeds, but readback is missing the setting | Also a gap. A write that does not read back did not happen |
| A verifier expects an older stage count or image | The verifier assumes an earlier lab's state; check live readback instead |

!!! warning "Do not repair a limitation by rebuilding"
    Do not re-run whole labs to fix an API gap; that creates duplicate resources. Never remove volumes or `~/floci-data`. Record the command, the error, `floci version` and the readback (no credentials) in your notes.

## Set up the local demonstrations

Labs 05, 06, 09 and 13 use one dependency-free Python script. It starts only temporary `127.0.0.1` servers and worker processes, makes no AWS calls, and cleans up when it finishes.

```bash
cat > scripts/utilities/student-fallback-demo.py << 'EOF'
#!/usr/bin/env python3
"""Dependency-free teaching alternatives; no AWS credentials or course mutations."""
import argparse
import collections
import contextlib
import http.server
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


@contextlib.contextmanager
def server(handler):
    instance = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{instance.server_port}'
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


class QuietHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, message):
        body = message.encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def routing():
    def backend(name):
        class Backend(QuietHandler):
            def do_GET(self):
                self.reply(200, name)
        return Backend

    with server(backend('backend-A')) as a, server(backend('backend-B')) as b:
        class Router(QuietHandler):
            def do_GET(self):
                target = a if self.path.startswith('/enrolment') else b
                with urllib.request.urlopen(target, timeout=3) as response:
                    self.reply(response.status, response.read().decode())
        with server(Router) as proxy:
            for path, expected in [('/enrolment', 'backend-A'), ('/results', 'backend-B')]:
                with urllib.request.urlopen(proxy + path, timeout=3) as response:
                    actual = response.read().decode()
                assert actual == expected
                print(f'{path} -> {actual} (HTTP 200)')
    print('Routing complete; all three HTTP servers closed.')


def scaling():
    workers = []
    def resize(count):
        while len(workers) < count:
            workers.append(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']))
        while len(workers) > count:
            process = workers.pop()
            process.terminate()
            process.wait()
        assert all(process.poll() is None for process in workers)
        print(f'Live worker processes: {len(workers)}')
    try:
        print('Accelerated schedule: morning=3 workers, evening=1 worker')
        resize(3)
        resize(1)
        for queue_depth in (20, 0):
            desired = 3 if queue_depth > 10 else 1
            print(f'Synthetic queue depth={queue_depth}; local controller requests {desired}')
            resize(desired)
    finally:
        resize(0)
    print('Scaling complete; all worker processes stopped. No ECS autoscaler was used.')


def security():
    print('Teaching policy model: identity allow INTERSECT boundary allow; explicit deny wins.')
    identity = {'s3:GetObject', 's3:PutObject'}
    boundary = {'s3:GetObject'}
    denied = {'s3:DeleteObject'}
    for action in ('s3:GetObject', 's3:PutObject', 's3:DeleteObject'):
        allowed = action in identity and action in boundary and action not in denied
        print(f'{action}: {"ALLOW" if allowed else "DENY"}')
    class TokenGate(QuietHandler):
        def do_GET(self):
            if self.headers.get('X-Lab-Token') != 'student-demo':
                self.reply(401, 'token required')
            else:
                self.reply(200, 'fictional metadata')
    with server(TokenGate) as endpoint:
        try:
            urllib.request.urlopen(endpoint, timeout=3)
            raise AssertionError('Unauthenticated request was accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 401
            print('Without token: HTTP 401')
        request = urllib.request.Request(endpoint, headers={'X-Lab-Token': 'student-demo'})
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 200
            print('With token: HTTP 200')
    print('Model only: this is not an IAM evaluator or an IMDSv2 implementation.')


def observability():
    trace_id = 'student-local-trace'
    events = []
    for faculty, seconds in [('science', 0.5), ('engineering', 2.4), ('engineering', 3.1)]:
        event = dict(event='transcript.processed', faculty=faculty, seconds=seconds,
                     trace_id=trace_id, timestamp=time.time())
        events.append(event)
        print(json.dumps(event))
    print('Counts by faculty:', dict(collections.Counter(e['faculty'] for e in events)))
    lag_high = max(e['seconds'] for e in events) > 2
    silence = len(events) == 0
    print(f'Local condition evaluation: lag_high={lag_high}, silence={silence}, OR={lag_high or silence}')
    print('Correlation:', trace_id, 'links', len(events), 'events')
    print('No X-Ray spans exported; no CloudWatch period/history/dashboard behavior asserted.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('demo', choices=['routing', 'scaling', 'security', 'observability', 'all'])
    args = parser.parse_args()
    demos = dict(routing=routing, scaling=scaling, security=security, observability=observability)
    for name, run in demos.items():
        if args.demo in (name, 'all'):
            print(f'\n--- {name} ---')
            run()
EOF

chmod +x scripts/utilities/student-fallback-demo.py
python3 scripts/utilities/student-fallback-demo.py all
```

The heredoc is quoted (`<< 'EOF'`) so the shell leaves the Python untouched. Each section below shows its expected output.

---

## Lab 03 - EC2

**Issue:** the user-data bootstrap installs nginx with `dnf`, but the local AMI is Amazon Linux 2 (`yum`), so the web server never starts.

**Alternative:** serve a static portal from your machine.

```bash
mkdir -p labs/lab-03-ec2/local-portal
cat > labs/lab-03-ec2/local-portal/index.html << 'EOF'
<!doctype html><html lang="en"><meta charset="utf-8"><title>USMS Student Portal</title>
<body><h1>USMS Student Portal</h1><p>Local fallback for the Lab 03 web server</p></body></html>
EOF
cat > labs/lab-03-ec2/local-portal/health.json << 'EOF'
{"service": "usms-web", "status": "ok", "runtime": "python-local-fallback"}
EOF

python3 -m http.server 30001 --bind 127.0.0.1 --directory labs/lab-03-ec2/local-portal
```

In a second terminal:

```bash
curl -i http://127.0.0.1:30001/
curl -i http://127.0.0.1:30001/health.json
```

**Observe:** `HTTP/1.0 200 OK` for both. Stop the server with ++ctrl+c++. If port 30001 is taken, pick another in both commands.

**Proves / does not prove:** HTTP serving and a health endpoint. It does not prove user data, nginx installation or security groups. For those, read `/etc/os-release` inside the instance and adapt the package manager; keep the original bootstrap evidence separately.

---

## Lab 05 - ALB

**Issue:** `aws ecs update-service` accepts load-balancer parameters, but `describe-services` returns no `loadBalancers` and no health-check grace period. A listener and target group alone do not prove routing.

**Alternative:**

```bash
python3 scripts/utilities/student-fallback-demo.py routing
```

**Observe:**

```text
/enrolment -> backend-A (HTTP 200)
/results -> backend-B (HTTP 200)
Routing complete; all three HTTP servers closed.
```

Change the path condition in `routing()` and re-run to see the routing change.

**Proves / does not prove:** one entry point sending paths to different services. It does not implement ALB health checks, target registration, TLS, security groups or ECS integration.

---

## Lab 06 - Auto Scaling

**Issue:** `put-scheduled-action` is unsupported, and forcing an alarm does not change the ECS service's desired count.

**Alternative 1 - local controller:**

```bash
python3 scripts/utilities/student-fallback-demo.py scaling
```

**Observe:** worker counts `3 -> 1` for the morning/evening schedule, then `3 -> 1` as the synthetic queue depth goes `20 -> 0`, then `0` at the end. Inputs are synthetic; this is not measurement-driven scaling.

**Alternative 2 - manual ECS scale, then restore:**

```bash
source configs/lab-04.env
original=$(aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" --query 'services[0].desiredCount' --output text)
echo "original desired count: $original"

aws ecs update-service --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" --desired-count 3

aws ecs describe-services --cluster "$USMS_ECS_CLUSTER" \
  --services "$USMS_ENROLMENT_SERVICE" \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'
```

Confirm `original` is a number before scaling. Poll the describe command until `running` matches `desired` (local capacity can limit this). Then restore and check again:

```bash
aws ecs update-service --cluster "$USMS_ECS_CLUSTER" \
  --service "$USMS_ENROLMENT_SERVICE" --desired-count "$original"
```

**Proves / does not prove:** the service converges to a new desired count. It is a manual scale, not autonomous policy execution. For real automatic scaling locally, use the HPA in Lab 8 (it scales pods, not ECS tasks).

---

## Lab 08 - EKS Scaling

**Issue:** `aws eks update-nodegroup-config` fails, so the node group cannot be resized. HPA, PodDisruptionBudgets and local exposure work.

**Alternative:** use the HPA drill from Lab 8 Steps 8-9.

```bash
source configs/lab-07.env
kubectl cluster-info || aws eks update-kubeconfig --name "$USMS_EKS_CLUSTER" --alias usms-eks
kubectl -n usms get hpa,pods
kubectl -n usms describe hpa usms-enrolment-hpa
./scripts/utilities/hpa-watch.sh 6
```

Apply `manifests/lab-08/20-loadgen.yaml` (Lab 8 Step 9), watch CPU and replicas rise, then delete only the load generator and allow for the 300-second scale-down window. If targets show `<unknown>`, check metrics availability and CPU requests before concluding HPA is broken.

**Proves / does not prove:** load changes pod replicas. It does not add nodes. Node-capacity behaviour needs a separate multi-node cluster and still does not emulate the managed node-group API.

---

## Lab 09 - Security

**Issue:** after setting a permissions boundary on a role, `get-role` shows none; after `modify-instance-metadata-options --http-tokens required`, metadata tokens remain `optional`.

**Alternative:**

```bash
python3 scripts/utilities/student-fallback-demo.py security
```

**Observe:**

```text
s3:GetObject: ALLOW
s3:PutObject: DENY
s3:DeleteObject: DENY
Without token: HTTP 401
With token: HTTP 200
```

`PutObject` is allowed by the identity policy but outside the boundary, so it is denied. Edit the `boundary` set and re-run.

**Proves / does not prove:** effective permission is the intersection of identity policy and boundary, and explicit deny wins. The model ignores conditions and resource policies; the HTTP gate uses a fixed teaching token with no IMDSv2 token issuance or TTL. Continue the scoped-trust, least-privilege and security-group steps that work, and label boundary/IMDS enforcement as not demonstrated.

---

## Lab 10 - Lambda

**Issue:** handler invocations work, but the local CloudFront configuration does not run functions at edge locations.

**Alternative:** the edge simulator you built in Lab 10 Step 16.

```bash
./scripts/utilities/usms-edge-simulate.sh
```

Compare the allow and deny fixtures in `templates/lab-10-viewer-request-*.json` and the origin-response fixture.

**Observe:** allowed requests continue, denied requests get the handler's rejection, and the origin response gains the configured headers.

**Proves / does not prove:** function logic. Not CDN latency, worldwide replication or edge caching.

---

## Lab 11 - CI/CD Pipeline

**Issue:** CodeBuild cannot pull `aws/codebuild/standard:7.0`.

**Alternative:** point the existing project at a public Python image.

```bash
source configs/lab-11.env
aws codebuild update-project --name "$USMS_BUILD_PROJECT" \
  --environment type=LINUX_CONTAINER,image=python:3.12-slim,computeType=BUILD_GENERAL1_SMALL
aws codepipeline start-pipeline-execution --name "$USMS_PIPELINE_NAME"
aws codepipeline get-pipeline-state --name "$USMS_PIPELINE_NAME"
```

**Observe:** Source and Build eventually reach `Succeeded`. Check the build logs and the output artifact. The image pull needs Docker and network access.

!!! warning "Stale checks after this change"
    `configs/lab-11.env` still records the managed image and two stages. Judge the workaround by live `get-project` / `get-pipeline-state` readback. After Lab 12 adds a Deploy stage, do not delete it to satisfy Lab 11's two-stage check; Deploy may fail while Source and Build succeed.

---

## Lab 12 - ECS Pipeline Deploy

**Issue:** CodePipeline reports the ECS deploy provider is unavailable. `aws ecr describe-images` reports image-not-found even though push and pull work.

**Alternative:** deploy the build artifact by hand, exactly as Lab 12 Steps 10-11 do for revision 3, using the image from the pipeline's `imagedefinitions.json`.

1. Read the artifact: `cat labs/lab-11-cicd/app/dist/imagedefinitions.json` and note the `imageUri`.
2. Save the current task definition ARN for rollback (`describe-services ... --query 'services[0].taskDefinition'`).
3. Register a new revision with that image (Step 10) and update the service (Step 11).
4. Poll `describe-services` until `running` equals `desired`, then confirm an HTTP response from the container port. A revision number alone does not prove the release is serving.
5. Roll back by updating the service to the saved ARN (Step 18 drill) and check the response again.

For the ECR discrepancy, check the image itself rather than its metadata:

```bash
IMAGE_URI=$(python3 -c 'import json;print(json.load(open("labs/lab-11-cicd/app/dist/imagedefinitions.json"))[0]["imageUri"])')
docker pull "$IMAGE_URI"
docker image inspect "$IMAGE_URI" --format '{% raw %}{{.Id}}{% endraw %}'
```

**Proves / does not prove:** artifact -> task revision -> service update. It does not make the managed Deploy stage work. These commands change the release your service is running.

---

## Lab 13 - Monitoring

**Issue:** several observability APIs are unavailable. Substitute per feature:

| Failed feature | Substitute | Distinction |
| --- | --- | --- |
| Log metric filters | Publish metrics directly with `usms-emit-telemetry.sh` | Extraction is explicit, not an installed filter |
| Logs Insights | Retrieve events and aggregate locally (below) | No Insights query engine |
| X-Ray traces / sampling | Correlate events by `trace_id` | No exported trace or sampling service |
| Composite alarms | Evaluate the OR locally | No AWS alarm service |
| Alarm history | Save successive `describe-alarms` snapshots | Local snapshots, not provider history |
| Dashboard | Terminal summary | Not CloudWatch widgets |

**Self-contained demonstration:**

```bash
python3 scripts/utilities/student-fallback-demo.py observability
```

**Observe:** `science` 1, `engineering` 2; `lag_high=True`; `OR=True`; three events share one correlation ID. This is a small in-memory sample, not CloudWatch evaluation periods or missing-data handling.

**With your real Floci telemetry:**

```bash
./scripts/utilities/usms-emit-telemetry.sh science 0.51
./scripts/utilities/usms-emit-telemetry.sh engineering 2.40
aws logs filter-log-events --log-group-name /usms/central/application \
  --filter-pattern USMS_EVENT --output json > outputs/student-events.json
python3 - << 'PY'
import collections, json
events = json.load(open('outputs/student-events.json'))['events']
counts = collections.Counter()
for event in events:
    _, separator, payload = event['message'].partition('USMS_EVENT ')
    if separator:
        counts[json.loads(payload).get('faculty', 'unknown')] += 1
print(dict(counts))
PY
```

The emitter reports X-Ray as skipped on this build; check the log and metric outputs separately. Counts include earlier events, so they will not match the standalone demo.

**Alarm snapshots:**

```bash
aws cloudwatch describe-alarms --alarm-names usms-transcript-lag-high --output json \
  | python3 -c 'import json,sys; from datetime import datetime,timezone; print(json.dumps({"observed_at":datetime.now(timezone.utc).isoformat(),"alarms":json.load(sys.stdin)}))' \
  >> outputs/student-alarm-snapshots.jsonl
```

Repeat to compare. A forced alarm state proves readback only, not metric-driven evaluation.

---

## Lab 14 - Checkpoint

Present originals and alternatives side by side, honestly labelled.

```bash
mkdir -p outputs/student-workarounds
python3 scripts/utilities/student-fallback-demo.py all \
  > outputs/student-workarounds/local-demonstrations.txt
for n in 01 02 03 04 05 06 07 08 09 10 11 12 13; do
  ./scripts/utilities/verify-lab-$n.sh > outputs/student-workarounds/verify-lab-$n.txt 2>&1
done
```

For each affected lab, record the original error, the alternative command, the observed result, and one sentence on what it does and does not prove. Use these labels in `gaps.md`:

- **original feature demonstrated**
- **alternative behaviour demonstrated**
- **configuration only**
- **not yet demonstrated**

Keep the original verifier results next to the substitute evidence. A substitute counts toward a requirement that asks for AWS-managed enforcement only with instructor approval.

## Instructor acceptance checklist

- [ ] The exact failure is recorded, and prerequisites were checked before choosing a substitute
- [ ] The substitute was run and shows a real behaviour, not just a successful API response
- [ ] The student explains what learning objective is kept and what AWS behaviour is missing
- [ ] Changed desired counts and releases are restored; temporary workloads are stopped
- [ ] Original failure evidence is kept; substitutes do not turn failed checks into passes

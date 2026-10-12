# Lab 09 - Securing the USMS Application with IAM Roles and Security Groups

## 1. Objectives

- Review the system Labs 1 to 6 built on both access-control axes: **who can call what** (IAM) and **what can reach what** (security groups and routing).
- Inventory and audit every role and security group with read-only scripts that compute findings from documents and rules, not names.
- Fix the identity findings: a read-only transcripts policy, confused-deputy trust conditions, a scoped `iam:PassRole`, a permissions boundary, a session policy, an access key rotation and IMDSv2.
- Fix the network findings: written egress rules on three groups and a bastion-sourced SSH rule; then prove the data tier is unreachable by several independent controls.
- Prove every control survives a restart and that no earlier lab's verification changed, and save the results to `configs/lab-09.env`.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [IAM roles](../unit8/topic1.md#iam-roles) ·
    [role sessions and temporary credentials](../unit8/topic1.md#role-sessions-and-temporary-credentials) ·
    [the confused deputy problem](../unit8/topic1.md#the-confused-deputy-problem) ·
    [access key hygiene](../unit8/topic1.md#access-keys-and-their-hygiene) ·
    [policy evaluation logic](../unit8/topic1.md#the-policy-evaluation-logic) ·
    [identity versus resource policies](../unit8/topic1.md#identity-based-versus-resource-based-policies) ·
    [permissions boundaries](../unit8/topic1.md#permissions-boundaries-and-delegated-administration) ·
    [iam:PassRole](../unit8/topic1.md#iampassrole) ·
    [session policies](../unit8/topic1.md#session-policies) ·
    [security group design patterns](../unit8/topic2.md#security-group-design-patterns) ·
    [connection tracking](../unit8/topic2.md#connection-tracking-and-why-it-matters-for-security) ·
    [egress control and data exfiltration](../unit8/topic2.md#egress-control-and-data-exfiltration) ·
    [defence in depth for the network](../unit8/topic2.md#defence-in-depth-for-the-network-layers-from-edge-to-workload) ·
    [IMDSv2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html)

---

## 2. Prerequisites

- Labs 1 to 6 complete, with `verify-lab-02.sh`, `verify-lab-03.sh`, `verify-lab-05.sh` and `verify-lab-06.sh` each at `FAIL=0` **before you start**.
- `verify-lab-04.sh` at `FAIL=0` or exactly the one documented failure on the `usms-app-sg` source check (caused by Lab 5 Step 13, repaired by Lab 5 Exercise 2). Any other failure is not acceptable.
- `outputs/usms-app-key.pem` present and `chmod 600`, and the `usms-dev` profile working; Step 10 rotates the key behind it.
- Errata 01 applied: `echo "$AWS_PROFILE"` in a new terminal must print something.
- Floci under Docker Compose with `FLOCI_STORAGE_MODE=hybrid`; `jq` and `python3` installed (`python3` does every timestamp, because GNU and BSD `date` differ).
- `usms-student-data` does **not** need to exist; Lab 10 creates it. Step 6 expects `head-bucket` to fail.

```bash
cd ~/aws-floci-course
for t in jq python3 docker; do printf '%-10s ' "$t"; command -v "$t" || echo MISSING; done
aws --version
./scripts/utilities/floci-storage-check.sh | tail -2
aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text
ls -l outputs/usms-app-key.pem
```

> Example output - your versions, paths and dates will differ.

```text
jq         /usr/bin/jq
python3    /usr/bin/python3
docker     /usr/bin/docker
aws-cli/2.17.42 Python/3.11.9 Darwin/23.5.0 exe/x86_64
PASS=16  FAIL=0
arn:aws:iam::000000000000:user/usms-dev-01
-rw------- 1 student student 1704 Aug 15 10:22 outputs/usms-app-key.pem
```

Fix a storage-check failure before starting. If the `usms-dev` profile does not answer, Step 10's **Verify** block says what to do instead; the rest of the lab is unaffected.

---

## 3. What This Lab Reuses

- Lab 1 `USMSStudentDataReadWrite`: read in Step 6; the read-only policy is derived from it in Step 7.
- Lab 1 `usms-ec2-app-role`, `usms-lambda-exec-role`, `usms-developer-role`: inventoried in Step 4; Step 9 assumes `usms-developer-role` with a session policy.
- Lab 1 `usms-dev-01` and its access key: rotated in Step 10 via the `usms-dev` profile.
- Lab 2 `usms-app-sg`, `usms-db-sg`: audited and hardened in Steps 12, 15 and 16.
- Lab 2 `usms-s3-endpoint`: its prefix list becomes an egress destination in Step 13.
- Lab 2 `usms-private-nacl`: one of the data tier's independent controls in Step 17.
- Lab 2 Exercise 2 `usms-bastion-sg`: reused in Step 16 if it exists, created if not.
- Lab 3 `usms-web-01` and `usms-ec2-app-profile`: IMDSv2 in Step 11; `PassRole` reasoning in Step 8.
- Lab 4 `usms-ecs-task-role` and `usms-enrolment-sg`: trust policy rewritten in Step 7 (permissions untouched); egress written in Step 13.
- Lab 5 `usms-alb-sg`: egress to a security group in Step 14.
- Lab 6's scalable target: unchanged; Step 17 explains why scaling does not change the matrix.

The audit covers the EC2/ECS estate from Labs 1 to 6. `usms-eks-node-role` and the Lab 7/8 ServiceAccount are out of scope (no IRSA on this build); a later audit would need to pick them up.

```text
Created in this lab:
- USMSStudentDataReadOnly       customer managed, the read half of Lab 01's transcripts policy
- USMSDeployBase                customer managed, with a SCOPED iam:PassRole
- USMSPermissionsBoundary       customer managed, used ONLY as a boundary, never attached
- usms-transcripts-reader-role  ecs-tasks trust, read-only on the transcripts bucket
- usms-deploy-role              usms-admin-01 trust, USMSDeployBase, WITH a permissions boundary
- a rewritten trust policy on usms-ecs-task-role, with the confused-deputy conditions
- usms-bastion-sg               created here, or reused from Lab 02's Exercise 2
- WRITTEN EGRESS on usms-alb-sg, usms-enrolment-sg and usms-db-sg
- a group-referenced SSH rule on usms-app-sg, replacing the 10.0.0.0/16 one
- IMDSv2 REQUIRED on usms-web-01, with a hop limit of 1
- a rotated access key for usms-dev-01, and the old one deleted
- policies/usms-student-data-ro-policy.json, policies/usms-deploy-policy.json,
  policies/usms-permissions-boundary.json, policies/trust-ecs-tasks-scoped.json,
  policies/trust-deploy.json, policies/usms-*-egress.json (four of them),
  policies/usms-app-sg-ssh-bastion.json
- scripts/utilities/usms-iam-audit.sh
- scripts/utilities/usms-sg-audit.sh
- scripts/utilities/usms-reachability-matrix.sh
- configs/lab-09.env
- scripts/utilities/verify-lab-09.sh
- scripts/cleanup/lab-09-cleanup.sh

Required for future labs:
- USMSStudentDataReadOnly       -> Lab 10 creates the bucket a THIRD policy now names
- usms-transcripts-reader-role  -> Lab 10 gives it something to read
- outputs/lab-09-bucket-policy-draft.json (Exercise 5) -> the (still unwritten) S3 configuration lab
  applies it as a bucket policy, once Lab 10 has created the bucket
- usms-deploy-role              -> the CloudFormation lab deploys as this role, not as root
- scripts/utilities/usms-sg-audit.sh -> every later lab that adds a security group runs it
- configs/lab-09.env            -> Lab 10 and the CloudFormation lab both source it
```

---

## 4. What We Are Building

A review of the existing system and the repairs it turns up, not a new tier. We audit before changing anything, fix identity before network, and add rather than replace wherever a later lab depends on a resource (`usms-ecs-task-role` keeps `USMSStudentDataReadWrite` for Lab 10). Floci enforces neither IAM nor security groups, so every proof is made by reading configuration and is then written into a script (Section 8).

| | Before this lab | After this lab |
| --- | --- | --- |
| `usms-alb-sg` ingress | tcp/80 from `0.0.0.0/0` | unchanged - it is an internet-facing load balancer |
| `usms-alb-sg` egress | allow all, to everywhere | tcp/80 to `usms-enrolment-sg` only |
| `usms-enrolment-sg` ingress | tcp/80 from `usms-alb-sg` | unchanged |
| `usms-enrolment-sg` egress | allow all | tcp/443 to the S3 prefix list and to the registry |
| `usms-db-sg` ingress | tcp/5432 from `usms-app-sg` | unchanged |
| `usms-db-sg` egress | allow all | tcp/443 outbound only |
| `usms-app-sg` ingress, ports 80 and 443 | from `0.0.0.0/0` | unchanged, and Exercise 4 argues about it |
| `usms-app-sg` ingress, port 22 | from `10.0.0.0/16` | from `usms-bastion-sg` |
| `usms-ecs-task-role` trust policy | `ecs-tasks.amazonaws.com`, no conditions | the same principal, with two conditions |
| `usms-ecs-task-role` permissions | `USMSStudentDataReadWrite` | unchanged. Lab 10 depends on it |
| `usms-web-01` instance metadata | IMDSv1 permitted | IMDSv2 required, hop limit 1 |
| `usms-dev-01` access keys | one, created in Lab 01 | one, created today; the old one deleted |
| Task definition, service, load balancer, scaling | as Lab 06 left them | **unchanged, all of it** |

The system's permissions change a great deal; what it does changes not at all. That is why Step 18 can prove it with four verification scripts written before this lab.

---

## 5. Architecture

```text
                                   Internet
                                       |
  =====================================|====================================
  ||  usms-vpc  10.0.0.0/16            |                                  ||
  ||                                   v                                  ||
  ||  +--------------------------------------------------------------+   ||
  ||  |  usms-public-subnet-a / -b                                    |   ||
  ||  |                                                               |   ||
  ||  |   [ usms-enrolment-alb ]        [ usms-web-01 ]               |   ||
  ||  |     usms-alb-sg                   usms-app-sg                 |   ||
  ||  |       in  80   <- 0.0.0.0/0         in  80,443 <- 0.0.0.0/0   |   ||
  ||  |       out 80   -> usms-enrolment-sg in  22     <- BASTION SG  |   ||
  ||  |            ^^^^ WRITTEN IN STEP 14  IMDSv2 REQUIRED, hop 1    |   ||
  ||  |                     |               profile usms-ec2-app-...  |   ||
  ||  |   [ usms-nat ]      |                                          |   ||
  ||  +---------------------|------------------------------------------+   ||
  ||                        |                                              ||
  ||                  tcp/80 from usms-alb-sg ONLY                         ||
  ||                        v                                              ||
  ||  +--------------------------------------------------------------+   ||
  ||  |  usms-private-subnet-a / -b        guarded by usms-private-nacl|  ||
  ||  |                                                               |   ||
  ||  |   [ task ] [ task ] ... 2..10      [ usms-db-01 ]             |   ||
  ||  |     usms-enrolment-sg                usms-db-sg               |   ||
  ||  |       in  80  <- usms-alb-sg           in  5432 <- usms-app-sg|   ||
  ||  |       out 443 -> pl-<s3>, registry     out 443  -> 0.0.0.0/0  |   ||
  ||  |            ^^^^ WRITTEN IN STEP 13          ^^^^ STEP 15      |   ||
  ||  +--------------------------------------------------------------+   ||
  =========================================================================

  THE OTHER AXIS - nothing above decides any of this

  IAM
  +---------------------------------------------------------------------+
  |  usms-ecs-task-role            trust ecs-tasks.amazonaws.com         |
  |    + Condition StringEquals  aws:SourceAccount 000000000000          |
  |    + Condition ArnLike       aws:SourceArn arn:aws:ecs:...:*         |
  |    permissions USMSStudentDataReadWrite      (UNCHANGED)             |
  |                                                                      |
  |  usms-transcripts-reader-role  same scoped trust                     |
  |    permissions USMSStudentDataReadOnly       (NEW - Get + List only) |
  |                                                                      |
  |  usms-deploy-role              trust  user/usms-admin-01             |
  |    permissions USMSDeployBase                                        |
  |      iam:PassRole  Resource: 3 named role ARNs                       |
  |                    Condition iam:PassedToService                     |
  |                      ec2.amazonaws.com, ecs-tasks.amazonaws.com      |
  |    PERMISSIONS BOUNDARY  USMSPermissionsBoundary                     |
  |      the ceiling. Grants nothing. Caps everything.                   |
  +---------------------------------------------------------------------+

  A request needs a YES from BOTH boxes. Neither knows the other exists.
```

Read the last line twice. Every confusing access-control incident you will ever debug is a case where
somebody assumed one of those two boxes had answered for the other.

---

## 6. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-09-security/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 12
├── policies/
│   ├── usms-student-data-ro-policy.json               # NEW - the read half
│   ├── usms-deploy-policy.json                        # NEW - scoped iam:PassRole
│   ├── usms-permissions-boundary.json                 # NEW - a ceiling, not a grant
│   ├── trust-ecs-tasks-scoped.json                    # NEW - with the two conditions
│   ├── trust-deploy.json                              # NEW - trusts a user, not a service
│   ├── usms-alb-sg-egress.json                        # NEW
│   ├── usms-enrolment-sg-egress.json                  # NEW
│   ├── usms-db-sg-egress.json                         # NEW
│   ├── usms-egress-allow-all.json                     # NEW - the rule we are revoking, kept
│   └── usms-app-sg-ssh-bastion.json                   # NEW
├── configs/
│   └── lab-09.env                                     # NEW
├── scripts/
│   ├── utilities/
│   │   ├── usms-iam-audit.sh                          # NEW - Step 5
│   │   ├── usms-sg-audit.sh                           # NEW - Step 12
│   │   ├── usms-reachability-matrix.sh                # NEW - Step 17
│   │   └── verify-lab-09.sh                           # NEW - Section 8
│   └── cleanup/
│       └── lab-09-cleanup.sh                          # NEW - end of course only
└── outputs/
    └── lab-09-*.json / *.txt                          # findings and evidence, git-ignored
```

Note where things land, because this lab is the one where the `policies/` and `templates/` split
finally earns its keep. **Every document this lab writes grants or denies something**, including the
security group rules, so every one of them is in `policies/` and not one is in `templates/`. A
reviewer opening `policies/` at the end of this laboratory is looking at the complete, reviewable
security posture of the USMS system in ten new documents, alongside the four the earlier laboratories
wrote.

`policies/usms-egress-allow-all.json` deserves a sentence of its own. It is a document describing the
rule we are about to revoke, and we write it down **before** revoking it so that putting it back is
one command rather than an act of memory. Keeping the undo next to the change is a habit worth more
than any single control in this lab.

Create the lab folder now:

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-09-security
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2  labs/lab-04-ecs-fargate
labs/lab-05-ecs-alb  labs/lab-06-ecs-autoscaling  labs/lab-09-security
```

---

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Capture every identifier with `$(...)`, `--query` and `--output text`; never type one. Step 19 writes them to `configs/lab-09.env`.

### Step 1 - Resume the environment and load seven env files

Three of these values (account ID, enrolment security group, S3 endpoint) are embedded in documents that would be silently wrong if a variable were empty.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04.env
source configs/lab-05.env
source configs/lab-06.env

./scripts/utilities/whoami.sh

printf '%-28s %s\n' \
  "account"              "$USMS_ACCOUNT_ID" \
  "region"               "$AWS_REGION_COURSE" \
  "dev user"             "$USMS_DEV_USER" \
  "admin user"           "$USMS_ADMIN_USER" \
  "developer role"       "$USMS_ROLE_DEVELOPER" \
  "ec2 role"             "$USMS_ROLE_EC2" \
  "lambda role"          "$USMS_ROLE_LAMBDA" \
  "instance profile"     "$USMS_INSTANCE_PROFILE" \
  "bucket name (policy)" "$USMS_BUCKET_NAME" \
  "vpc"                  "$USMS_VPC_ID" \
  "app sg"               "$USMS_APP_SG" \
  "db sg"                "$USMS_DB_SG" \
  "enrolment sg"         "$USMS_ENROLMENT_SG" \
  "alb sg"               "$USMS_ALB_SG" \
  "s3 endpoint"          "$USMS_S3_ENDPOINT" \
  "web instance"         "$USMS_WEB_INSTANCE" \
  "db instance"          "$USMS_DB_INSTANCE"
```

The env files are independent (no two define the same variable), so order does not matter. One `printf` prints seventeen lines because it reuses its format string.

**Expected result**

```text
[floci-up] container 'floci' already running (compose project: floci-course)

Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566
Profile  : floci

account                      000000000000
region                       us-east-1
dev user                     usms-dev-01
admin user                   usms-admin-01
developer role               usms-developer-role
ec2 role                     usms-ec2-app-role
lambda role                  usms-lambda-exec-role
instance profile             usms-ec2-app-profile
bucket name (policy)         usms-student-data
vpc                          vpc-0a1b2c3d4e5f67890
app sg                       sg-0123456789abcdef0
db sg                        sg-0fedcba9876543210
enrolment sg                 sg-0aa11bb22cc33dd44
alb sg                       sg-0bb22cc33dd44ee55
s3 endpoint                  vpce-0123456789abcdef0
web instance                 i-0123456789abcdef0
db instance                  i-0fedcba9876543210
```

> Example output - your IDs will differ.

**Verify**

Seventeen non-empty values. The four that matter most:

- **`account` empty** breaks Steps 7, 8 and 9: every document they write embeds the account ID, and IAM reports a malformed ARN rather than an empty variable.
- **`enrolment sg` or `alb sg` empty**: re-run Lab 4 Step 20 or Lab 5 Step 18.
- **`s3 endpoint` empty**: Lab 2 Step 21 did not complete. Step 13 has a fallback.
- **`bucket name (policy)` empty**: survivable; Step 6 re-derives it from Lab 1's policy.

---

### Step 2 - Record the security baseline before you change anything

Capture what five earlier verification scripts say today, so Step 18 can prove with a `diff` that nothing they assert has changed.

```bash
{
  echo "== baseline recorded $(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))') =="
  for s in 02 03 04 05 06; do
    printf '%-10s ' "lab-$s"
    ./scripts/utilities/verify-lab-$s.sh 2>/dev/null | tail -1
  done
} | tee outputs/lab-09-pre-verify.txt
```

`{ ... } | tee` captures the loop and the heading together.

**Expected result**

```text
== baseline recorded 2026-09-06T04:11:02Z ==
lab-02     PASS=33  FAIL=0
lab-03     PASS=36  FAIL=0
lab-04    PASS=48  FAIL=1
lab-05    PASS=49  FAIL=0
lab-06    PASS=42  FAIL=0
```

> Example output. `lab-04` reads `PASS=49  FAIL=0` instead if you completed Lab 05's Exercise 2, and
> `lab-06` reads a higher number if you completed its Exercise 1 or 2. Record whatever yours says;
> what matters is that Step 18 produces the same line.

**Verify**

`FAIL=0` from Labs 2, 3, 5 and 6; Lab 4 at `FAIL=0` or the one documented failure. Confirm it:

```bash
./scripts/utilities/verify-lab-04.sh 2>/dev/null | grep FAIL || echo "no failures in 04"
```

You want either `FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)` or `no failures in 04`. Fix any other failure first.

**Checkpoint 1**

```text
Ready to review
 ├── Floci running under Compose, storage mode hybrid
 ├── seven env files sourced, seventeen values non-empty
 ├── five verification scripts run, all summary lines captured
 └── outputs/lab-09-pre-verify.txt written - Step 18 diffs against it
```

---

### Step 3 - Probe what this Floci build supports for policy evaluation and rule management

Find out now which IAM and EC2 calls your build implements, rather than at Step 13 with three groups half-hardened.

```bash
probe() {
  printf '%-52s ' "$1"
  if eval "$2" >/dev/null 2>&1; then echo "SUPPORTED"; else echo "not available"; fi
}

echo "== IAM: reading what exists =="
probe "iam list-roles"                       "aws iam list-roles --max-items 1"
probe "iam list-policies --scope Local"      "aws iam list-policies --scope Local --max-items 1"
probe "iam get-role"                         "aws iam get-role --role-name $USMS_ROLE_EC2"
probe "iam list-attached-role-policies"      "aws iam list-attached-role-policies --role-name $USMS_ROLE_EC2"
probe "iam get-account-authorization-details" "aws iam get-account-authorization-details --max-items 1"

echo "== IAM: changing what exists =="
probe "iam update-assume-role-policy (skel)" "aws iam update-assume-role-policy --generate-cli-skeleton"
probe "iam create-role --permissions-boundary (skel)" "aws iam create-role --generate-cli-skeleton"
probe "iam put-role-permissions-boundary (skel)" "aws iam put-role-permissions-boundary --generate-cli-skeleton"

echo "== IAM: evaluating what exists =="
probe "iam simulate-principal-policy" \
  "aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::$USMS_ACCOUNT_ID:role/$USMS_ROLE_EC2 --action-names s3:GetObject"
probe "accessanalyzer list-analyzers"        "aws accessanalyzer list-analyzers"
probe "sts assume-role --policy (session policy)" "aws sts assume-role --generate-cli-skeleton"

echo "== IAM: credentials =="
probe "iam list-access-keys"                 "aws iam list-access-keys --user-name $USMS_DEV_USER"
probe "iam get-access-key-last-used"         "aws iam get-access-key-last-used --generate-cli-skeleton"
probe "iam get-credential-report"            "aws iam get-credential-report"

echo "== EC2: security group rules =="
probe "ec2 describe-security-group-rules"    "aws ec2 describe-security-group-rules --max-items 1"
probe "ec2 authorize-security-group-egress (skel)" "aws ec2 authorize-security-group-egress --generate-cli-skeleton"
probe "ec2 revoke-security-group-egress (skel)"    "aws ec2 revoke-security-group-egress --generate-cli-skeleton"
probe "ec2 describe-prefix-lists"            "aws ec2 describe-prefix-lists"
probe "ec2 describe-network-interfaces"      "aws ec2 describe-network-interfaces --max-items 1"

echo "== EC2: instance metadata options =="
probe "ec2 modify-instance-metadata-options (skel)" "aws ec2 modify-instance-metadata-options --generate-cli-skeleton"
probe "ec2 describe-instances MetadataOptions" \
  "aws ec2 describe-instances --instance-ids $USMS_WEB_INSTANCE --query 'Reservations[0].Instances[0].MetadataOptions'"
```

A skeleton probe only shows the CLI knows the operation, not that the build implements it; steps that rely on one have a fallback. Read the result as "the service responded", not "the call succeeded".

**Expected result**

```text
== IAM: reading what exists ==
iam list-roles                                       SUPPORTED
iam list-policies --scope Local                      SUPPORTED
iam get-role                                         SUPPORTED
iam list-attached-role-policies                      SUPPORTED
iam get-account-authorization-details                not available
== IAM: changing what exists ==
iam update-assume-role-policy (skel)                 SUPPORTED
iam create-role --permissions-boundary (skel)        SUPPORTED
iam put-role-permissions-boundary (skel)             SUPPORTED
== IAM: evaluating what exists ==
iam simulate-principal-policy                        not available
accessanalyzer list-analyzers                        not available
sts assume-role --policy (session policy)            SUPPORTED
== IAM: credentials ==
iam list-access-keys                                 SUPPORTED
iam get-access-key-last-used                         SUPPORTED
iam get-credential-report                            not available
== EC2: security group rules ==
ec2 describe-security-group-rules                    SUPPORTED
ec2 authorize-security-group-egress (skel)           SUPPORTED
ec2 revoke-security-group-egress (skel)              SUPPORTED
ec2 describe-prefix-lists                            SUPPORTED
ec2 describe-network-interfaces                      SUPPORTED
== EC2: instance metadata options ==
ec2 modify-instance-metadata-options (skel)          SUPPORTED
ec2 describe-instances MetadataOptions               SUPPORTED
```

> Example output - yours will differ, and that is exactly why the probe exists. The three
> `not available` lines above are the *expected* answers on most builds.


**Verify**

Write your path at the top of `notes/lab-09-notes.md`; your report and Section 13 both require it.

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | Everything above answers, including `simulate-principal-policy` | Do every step as written, and Step 9 gets a simulated answer as well as a read one |
| **B - management only** | Roles, policies and rules can be created, read and changed, but simulation and account-authorisation details are absent | **The expected path.** Every step still works. Every proof in this lab is a proof about a document, and the documents are all there |
| **C - no IAM writes** | `update-assume-role-policy` or `create-role` fails outright | Do Steps 4, 5, 12 to 18 and Exercises 3 and 4, which need no IAM writes, and record the identity half as conceptual. Tell your instructor |

!!! note "Floci Limitation - nothing in this laboratory is enforced"
    Floci accepts any credentials, does not authorise requests against IAM policies, and carries no traffic for security groups to evaluate.

    Real AWS evaluates every policy on every API call and every security group on every packet.

    **Judge your controls by reading them, not by whether a command succeeded.** Never rely on seeing `AccessDenied`. For any claim about what *cannot* happen, reading is what you would do on a real account too (Section 11).

!!! info "The two axes, and the order IAM decides in"
    An **API call** is decided by IAM (identity policies, resource policies, boundaries, session policies) and fails with an error naming an action. A **packet** is decided by routing, security groups and NACLs and fails with a timeout. **An error message means IAM; a hang means the network.** For an API call, IAM evaluates in this order:

    1. An explicit `Deny` anywhere: deny, and nothing overrides it.
    2. A Service Control Policy must allow it (AWS Organizations; not modelled here).
    3. The **permissions boundary** must allow it (Step 8).
    4. A **session policy** must allow it (Step 9).
    5. An **identity policy** allows it: allow.
    6. A **resource policy** allows it: allow (Exercise 5).
    7. Otherwise: deny.

    Boundaries and session policies only subtract. A role's **trust policy** decides who may become it; its **identity policy** decides what it may do. The trust policy is the more dangerous of the two. See [policy evaluation logic](../unit8/topic1.md#the-policy-evaluation-logic).

---

### Step 4 - Inventory every identity in the account

List every role, what trusts it and what it can do, as a JSON file Step 5 consumes. Nothing is modified.

**Part 1 - the human-readable pass**

```bash
echo "== Roles in this account =="
aws iam list-roles \
  --query 'sort_by(Roles, &RoleName)[].{Role:RoleName,Created:CreateDate,MaxSession:MaxSessionDuration}' \
  --output table

echo
echo "== Users, and how many access keys each one has =="
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do
  n=$(aws iam list-access-keys --user-name "$u" --query 'length(AccessKeyMetadata)' --output text)
  printf '  %-18s access keys: %s\n' "$u" "$n"
done

echo
echo "== Customer managed policies =="
aws iam list-policies --scope Local \
  --query 'sort_by(Policies, &PolicyName)[].{Policy:PolicyName,Default:DefaultVersionId,Attached:AttachmentCount}' \
  --output table
```

`--scope Local` limits `list-policies` to your policies. Read `AttachmentCount`: zero means a leftover, a mistake, or (after Step 8) a deliberate boundary.

**Expected result**

```text
== Roles in this account ==
---------------------------------------------------------------------------
|                                ListRoles                                |
+----------------------------+----------------------------+---------------+
|          Created           |         MaxSession         |     Role      |
+----------------------------+----------------------------+---------------+
|  2026-08-08T09:14:22+00:00 |  3600                      |  usms-developer-role |
|  2026-08-08T09:12:05+00:00 |  3600                      |  usms-ec2-app-role   |
|  2026-08-28T03:41:55+00:00 |  3600                      |  usms-ecs-exec-role  |
|  2026-08-28T03:42:10+00:00 |  3600                      |  usms-ecs-task-role  |
|  2026-08-08T09:13:41+00:00 |  3600                      |  usms-lambda-exec-role |
+----------------------------+----------------------------+---------------+

== Users, and how many access keys each one has ==
  usms-admin-01      access keys: 0
  usms-audit-01      access keys: 0
  usms-dev-01        access keys: 1

== Customer managed policies ==
------------------------------------------------------------------
|                          ListPolicies                          |
+------------+------------+--------------------------------------+
|  Attached  |  Default   |               Policy                 |
+------------+------------+--------------------------------------+
|  1         |  v1        |  USMSAssumeAppRoles                  |
|  1         |  v2        |  USMSDeveloperBase                   |
|  1         |  v1        |  USMSECSTaskExecution                |
|  1         |  v1        |  USMSLambdaBasic                     |
|  2         |  v1        |  USMSStudentDataReadWrite            |
+------------+------------+--------------------------------------+
```

> Example output - your dates and counts will differ. `AWSServiceRoleForApplicationAutoScaling_ECSService`
> from Lab 06 may or may not appear in the roles list depending on how your build stores
> service-linked roles; either is correct.

`USMSStudentDataReadWrite` with an attachment count of **2** (`usms-ec2-app-role` and `usms-ecs-task-role`) is the finding Step 6 pulls on.

**Part 2 - the machine-readable inventory**

```bash
python3 - << 'PY' > outputs/lab-09-identity-inventory.json
import json, subprocess

def aws(*args):
    out = subprocess.run(["aws", *args, "--output", "json"],
                         capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return json.loads(out.stdout)

roles = (aws("iam", "list-roles") or {}).get("Roles", [])
inventory = []

for r in roles:
    name = r["RoleName"]
    detail = {
        "role": name,
        "arn": r.get("Arn"),
        "maxSessionDuration": r.get("MaxSessionDuration"),
        "permissionsBoundary": (r.get("PermissionsBoundary") or {}).get("PermissionsBoundaryArn"),
        "trustPolicy": r.get("AssumeRolePolicyDocument"),
        "attachedPolicies": [],
        "inlinePolicies": [],
    }
    att = aws("iam", "list-attached-role-policies", "--role-name", name) or {}
    for p in att.get("AttachedPolicies", []):
        pol = aws("iam", "get-policy", "--policy-arn", p["PolicyArn"]) or {}
        ver = (pol.get("Policy") or {}).get("DefaultVersionId")
        doc = None
        if ver:
            v = aws("iam", "get-policy-version",
                    "--policy-arn", p["PolicyArn"], "--version-id", ver) or {}
            doc = (v.get("PolicyVersion") or {}).get("Document")
        detail["attachedPolicies"].append(
            {"name": p["PolicyName"], "arn": p["PolicyArn"], "version": ver, "document": doc})

    inl = aws("iam", "list-role-policies", "--role-name", name) or {}
    for pn in inl.get("PolicyNames", []):
        d = aws("iam", "get-role-policy", "--role-name", name, "--policy-name", pn) or {}
        detail["inlinePolicies"].append({"name": pn, "document": d.get("PolicyDocument")})

    inventory.append(detail)

print(json.dumps(inventory, indent=2, default=str))
PY

python3 -m json.tool outputs/lab-09-identity-inventory.json > /dev/null && echo "valid JSON"
python3 -c "
import json
d = json.load(open('outputs/lab-09-identity-inventory.json'))
print(f'{len(d)} roles inventoried')
for r in d:
    print(f\"  {r['role']:<30} policies={len(r['attachedPolicies'])+len(r['inlinePolicies'])} boundary={r['permissionsBoundary'] or '-'}\")
"
```

- Python, because the data is nested and irregular (trust policy objects, attached policies needing two more calls, inline policies).
- `<< 'PY'` is quoted so the shell leaves `$` and braces alone.
- `aws(...)` returns `None` on failure, so an unsupported call gives an empty list rather than no inventory.

**Expected result**

```text
valid JSON
5 roles inventoried
  usms-developer-role            policies=1 boundary=-
  usms-ec2-app-role              policies=1 boundary=-
  usms-ecs-exec-role             policies=1 boundary=-
  usms-ecs-task-role             policies=1 boundary=-
  usms-lambda-exec-role          policies=1 boundary=-
```

> Example output - your role count may include Lab 06's service-linked role.

Every `boundary` reads `-`: **no role has a permissions boundary**. Step 8 fixes that.

✏️ **Your turn**

Read `usms-ec2-app-role`'s trust policy and `usms-developer-role`'s trust policy out of the inventory
file, side by side, and write two sentences in `notes/lab-09-notes.md` saying what is structurally
different about them and why.

```text
Expected result:
One trust policy whose Principal is a Service, one whose Principal is an AWS
identity. Your two sentences should name which is which, and say what each
of the two kinds of principal implies about WHO could obtain those credentials
and HOW.
```

Hint: pull them out with `python3 -c ...` or `jq '.[] | {role, trustPolicy}'`. The interesting difference is not the syntax.

---

### Step 5 - Build the IAM audit script

Turn the inventory into findings: four checks for the IAM mistakes that cause incidents. Read-only.

| Finding | Why it matters |
| --- | --- |
| `Action: "*"` or a service wildcard like `s3:*` | The blast radius of a compromised principal is the union of everything it can do. A wildcard makes that union unbounded and unreviewable |
| `Resource: "*"` on a mutating action | Scoping actions without scoping resources means the right verbs on the wrong nouns. `s3:DeleteObject` on `*` is not a smaller problem than `s3:*` on one bucket |
| `iam:PassRole` without a resource scope | **The escalation.** A principal that may pass any role to any service can pass an admin role to a service it controls and inherit it. This is the single most exploited IAM misconfiguration there is |
| A trust policy with no `Condition` on a **service** principal | The confused deputy. Step 7 explains it in full |

**Command**

````bash
cat > scripts/utilities/usms-iam-audit.sh << 'EOF'
#!/usr/bin/env bash
# USMS IAM audit. Reports findings; changes nothing.
#
# Four checks per role:
#   1. wildcard actions             Action: "*" or "<service>:*"
#   2. wildcard resources           Resource: "*" on a mutating action
#   3. unscoped iam:PassRole        the privilege-escalation path
#   4. unconditioned service trust  the confused deputy
#
# Read-only. Exit 0 if there are no HIGH findings, 1 otherwise.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$REPO_ROOT/configs/course.env" 2>/dev/null || true

INVENTORY="${1:-outputs/lab-09-identity-inventory.json}"

if [ ! -f "$INVENTORY" ]; then
  echo "no inventory at $INVENTORY - run Lab 09 Step 4 part 2 first" >&2
  exit 2
fi

python3 - "$INVENTORY" << 'PY'
import json, sys

MUTATING = ("Create", "Delete", "Put", "Update", "Modify", "Attach", "Detach",
            "Write", "Terminate", "Run", "Revoke", "Authorize", "Set", "Remove")

def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def statements(doc):
    if not doc:
        return []
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except Exception:
            return []
    return as_list(doc.get("Statement"))

def is_mutating(action):
    if action == "*":
        return True
    verb = action.split(":", 1)[-1]
    return any(verb.startswith(p) for p in MUTATING)

roles = json.load(open(sys.argv[1]))
high = med = 0
lines = []

for r in roles:
    name = r["role"]
    findings = []

    # ---- checks 1 to 3, over every attached and inline policy ----
    docs = [(p["name"], p.get("document")) for p in r.get("attachedPolicies", [])]
    docs += [(p["name"], p.get("document")) for p in r.get("inlinePolicies", [])]

    for pname, doc in docs:
        for st in statements(doc):
            if st.get("Effect") != "Allow":
                continue
            actions = as_list(st.get("Action"))
            resources = as_list(st.get("Resource"))
            has_cond = bool(st.get("Condition"))

            for a in actions:
                if a == "*":
                    findings.append(("HIGH", f"{pname}: Action \"*\" - unbounded"))
                elif a.endswith(":*"):
                    findings.append(("MED", f"{pname}: service wildcard {a}"))

                if a.lower() == "iam:passrole" or a == "*":
                    if "*" in resources and not has_cond:
                        findings.append(
                            ("HIGH", f"{pname}: iam:PassRole on Resource \"*\" with no Condition"))
                    elif "*" in resources:
                        findings.append(
                            ("MED", f"{pname}: iam:PassRole on Resource \"*\", conditioned"))

                if "*" in resources and is_mutating(a) and a != "*":
                    findings.append(("MED", f"{pname}: {a} on Resource \"*\""))

    # ---- check 4, the trust policy ----
    for st in statements(r.get("trustPolicy")):
        princ = st.get("Principal") or {}
        svc = as_list(princ.get("Service"))
        aws_p = as_list(princ.get("AWS"))
        if "*" in aws_p:
            findings.append(("HIGH", "trust policy: Principal AWS \"*\" - anyone may assume"))
        if svc and not st.get("Condition"):
            findings.append(
                ("HIGH", f"trust policy: service principal {','.join(svc)} with NO Condition "
                         "(confused deputy)"))

    # ---- report ----
    boundary = r.get("permissionsBoundary")
    lines.append(f"{name}")
    lines.append(f"    permissions boundary : {boundary or 'NONE'}")
    if not boundary:
        findings.append(("MED", "no permissions boundary"))

    if not findings:
        lines.append("    ok   no findings")
    else:
        seen = set()
        for sev, text in findings:
            if (sev, text) in seen:
                continue
            seen.add((sev, text))
            lines.append(f"    {sev:<4} {text}")
            if sev == "HIGH":
                high += 1
            else:
                med += 1
    lines.append("")

print("== USMS IAM audit ==")
print()
print("\n".join(lines))
print(f"HIGH={high}  MED={med}  roles={len(roles)}")
sys.exit(1 if high else 0)
PY
EOF

chmod +x scripts/utilities/usms-iam-audit.sh
bash -n scripts/utilities/usms-iam-audit.sh && echo "syntax OK"
./scripts/utilities/usms-iam-audit.sh | tee outputs/lab-09-iam-findings.txt
````

- Outer `<< 'EOF'` and inner `<< 'PY'` are both quoted; the nested heredocs are why the Markdown fence uses four backticks.
- `as_list` handles IAM's string-or-list fields (`Action`, `Resource`, `Principal.Service`, `Statement`).
- `is_mutating` is a verb-prefix heuristic, and says so (it misses `sts:AssumeRole`, for instance).
- Exit code is 1 only for HIGH findings, so nobody appends `|| true`.

**Expected result**

```text
syntax OK
== USMS IAM audit ==

usms-developer-role
    permissions boundary : NONE
    MED  no permissions boundary

usms-ec2-app-role
    permissions boundary : NONE
    HIGH trust policy: service principal ec2.amazonaws.com with NO Condition (confused deputy)
    MED  no permissions boundary

usms-ecs-exec-role
    permissions boundary : NONE
    HIGH trust policy: service principal ecs-tasks.amazonaws.com with NO Condition (confused deputy)
    MED  no permissions boundary

usms-ecs-task-role
    permissions boundary : NONE
    HIGH trust policy: service principal ecs-tasks.amazonaws.com with NO Condition (confused deputy)
    MED  no permissions boundary

usms-lambda-exec-role
    permissions boundary : NONE
    HIGH trust policy: service principal lambda.amazonaws.com with NO Condition (confused deputy)
    MED  no permissions boundary

HIGH=4  MED=5  roles=5
```

> Example output - your counts depend on exactly what Lab 01 and Lab 04 wrote. If
> `USMSDeveloperBase` contains a wildcard you will see more findings, and that is correct: Lab 01's
> policy was written to teach least privilege, not to be perfect.

**Verify**

Four HIGH findings of the same shape on four roles: a systematic mistake made by a convention. Steps 7 and 8 fix two; Exercise 2 handles the rest.

```bash
./scripts/utilities/usms-iam-audit.sh >/dev/null; echo "exit code: $?"
```

You want `exit code: 1`. It will still be 1 at Step 18, because this lab does not fix all four.

**Checkpoint 2**

```text
Identity inventory complete
 ├── outputs/lab-09-identity-inventory.json    every role, trust policy and policy document
 ├── outputs/lab-09-iam-findings.txt           HIGH=4  MED=5
 ├── scripts/utilities/usms-iam-audit.sh       read-only, re-runnable, exits 1 on HIGH
 └── finding: no role in this account has a permissions boundary
```

---

### Step 6 - Read the transcripts policy, and find the verb that should not be there

Lab 1's `USMSStudentDataReadWrite` is attached to an EC2 role and a Fargate task role. Do both workloads need all of it?

**Part 1 - read the policy that two roles share**

```bash
POLICY_ARN="arn:aws:iam::${USMS_ACCOUNT_ID}:policy/USMSStudentDataReadWrite"

DEFAULT_VERSION=$(aws iam get-policy --policy-arn "$POLICY_ARN" \
  --query 'Policy.DefaultVersionId' --output text)

echo "default version: $DEFAULT_VERSION"

aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$DEFAULT_VERSION" \
  --query 'PolicyVersion.Document' --output json | tee outputs/lab-09-transcripts-rw.json

echo
echo "== who carries it =="
aws iam list-entities-for-policy --policy-arn "$POLICY_ARN" \
  --query '{Roles:PolicyRoles[].RoleName,Users:PolicyUsers[].UserName,Groups:PolicyGroups[].GroupName}' \
  --output json
```

- `get-policy` then `get-policy-version`: only the default version is in force.
- `list-entities-for-policy` is the reverse lookup: given a policy, who has it.

**Expected result**

```text
default version: v1
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListTheBucket",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": "arn:aws:s3:::usms-student-data"
        },
        {
            "Sid": "ReadWriteObjects",
            "Effect": "Allow",
            "Action": [ "s3:GetObject", "s3:PutObject" ],
            "Resource": "arn:aws:s3:::usms-student-data/*"
        },
        {
            "Sid": "NeverDeleteTheBucket",
            "Effect": "Deny",
            "Action": "s3:DeleteBucket",
            "Resource": "arn:aws:s3:::usms-student-data"
        }
    ]
}

== who carries it ==
{
    "Roles": [ "usms-ec2-app-role", "usms-ecs-task-role" ],
    "Users": null,
    "Groups": null
}
```

> Example output - the exact `Sid` values and layout depend on what your Lab 01 wrote. What must be
> true is the shape: a bucket-level statement, an object-level statement, and an explicit `Deny`.

The findings:

- **Two statements, two ARNs:** `s3:ListBucket` takes the bucket ARN, object actions take the ARN with `/*`. Lab 1 got this right.
- **`s3:PutObject` is granted to both roles.** The enrolment API only reads transcripts; one role carries a verb it does not use.
- **The explicit `Deny` on `s3:DeleteBucket`** outranks everything (rule 1 of the evaluation order).

**Part 2 - does the bucket exist yet?**

```bash
aws s3api head-bucket --bucket "${USMS_BUCKET_NAME:-usms-student-data}" 2>&1 | head -3
echo "head-bucket exit code: ${PIPESTATUS[0]}"
```

A non-zero exit code (`404` / `NoSuchBucket`) is correct: Lab 10 creates the bucket. **An IAM policy is a statement about ARNs, not a reference to objects**, so it can be reviewed before the resource exists. Record that the bucket did not exist yet at the top of `notes/lab-09-notes.md`; Section 13 asks for it.

!!! note "Floci Limitation - you cannot demonstrate the difference between these two policies"
    On real AWS a `PutObject` under the read-only policy would fail with `AccessDenied`. Floci authorises nothing, so both roles succeed at everything.

    **The proof that a policy is correct is that you read it and it says what you meant.** For a claim about what a principal *cannot* do, it is the only proof there is.

✏️ **Your turn**

Write down, in `notes/lab-09-notes.md`, the exact list of actions the enrolment API needs in order to
display a student's transcript, and the exact list the registry's upload workflow needs in order to
store one. Then say which single action appears in the second list and not the first.

```text
Expected result:
Two short lists and one sentence. The second list is a superset of the first by
exactly one action. If your two lists differ by more than one action, read the
policy document again - there are only three actions in it.
```

Hint: ask why a reader needs `s3:ListBucket` at all; it changes what S3 returns for a missing key.

---

### Step 7 - Create the read-only policy and the role that carries it

Split the transcripts policy along Step 6's line: a new, narrower policy on a new role, additively, so Lab 10's moment for `USMSStudentDataReadWrite` is untouched.

!!! info "The confused deputy, briefly"
    A trust policy naming a **service** principal lets that service assume the role on behalf of anyone, including another account. The fix pins the request to your account and resources:

    ```text
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "000000000000" },
      "ArnLike":      { "aws:SourceArn": "arn:aws:ecs:us-east-1:000000000000:*" }
    }
    ```

    Two caveats: `ec2.amazonaws.com` does not send `aws:SourceArn` for instance profiles, so `usms-ec2-app-role` cannot be fixed this way (Exercise 2); and a condition on a key the service never sends denies everything. See [the confused deputy problem](../unit8/topic1.md#the-confused-deputy-problem).

**Part 1 - the read-only policy document**

```bash
cat > policies/usms-student-data-ro-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheTranscriptsBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::usms-student-data"
    },
    {
      "Sid": "ReadTranscriptObjectsOnly",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::usms-student-data/*"
    },
    {
      "Sid": "NeverWriteAndNeverDelete",
      "Effect": "Deny",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:DeleteBucket",
        "s3:PutBucketPolicy"
      ],
      "Resource": [
        "arn:aws:s3:::usms-student-data",
        "arn:aws:s3:::usms-student-data/*"
      ]
    }
  ]
}
EOF

python3 -m json.tool policies/usms-student-data-ro-policy.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-student-data-ro-policy.json
```

- `<< 'EOF'`, quoted: no shell variables. The bucket name is the same literal Lab 1 used, so Exercise 5 can compare them.
- `grep -c '\$'` must print **`0`**.
- The explicit `Deny` adds nothing today, but still wins if someone later attaches a broader policy. Say that in your report, or a reviewer will delete it as redundant.

**Part 2 - create the policy**

```bash
RO_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSStudentDataReadOnly \
  --description "Read-only access to the USMS transcripts bucket. Explicitly denies every write." \
  --policy-document file://policies/usms-student-data-ro-policy.json \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 Key=Tier,Value=data \
  --query 'Policy.Arn' --output text)

echo "RO_POLICY_ARN = $RO_POLICY_ARN"
```

**Expected result**

```text
valid JSON
0
RO_POLICY_ARN = arn:aws:iam::000000000000:policy/USMSStudentDataReadOnly
```

> Example output. If this fails with `EntityAlreadyExists`, you have run the step twice; read the
> existing policy with `get-policy-version` and confirm it matches before continuing.

**Part 3 - the scoped trust policy**

```bash
cat > policies/trust-ecs-tasks-scoped.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcsTasksMayAssumeThisRoleForThisAccountOnly",
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "${USMS_ACCOUNT_ID}" },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:ecs:${AWS_REGION_COURSE}:${USMS_ACCOUNT_ID}:*"
        }
      }
    }
  ]
}
EOF

python3 -m json.tool policies/trust-ecs-tasks-scoped.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/trust-ecs-tasks-scoped.json
cat policies/trust-ecs-tasks-scoped.json
```

!!! warning "Heredoc quoting: expand now, or later?"
    This one is `<< EOF`, **unquoted**, because `${USMS_ACCOUNT_ID}` and `${AWS_REGION_COURSE}` must become real values now. The rule is not "policy files use `<< 'EOF'`"; it is always *do I want this expanded now or later?* Lab 1's `${aws:username}` is an IAM variable and must survive. In an unquoted heredoc that contains both kinds, escape the IAM one:

    ```text
    "Resource": "arn:aws:iam::${USMS_ACCOUNT_ID}:user/\${aws:username}"
    ```

    Without the backslash, bash aborts with `bad substitution`.

**Expected result**

```text
valid JSON
0
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcsTasksMayAssumeThisRoleForThisAccountOnly",
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "000000000000" },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:ecs:us-east-1:000000000000:*"
        }
      }
    }
  ]
}
```

Zero dollar signs and real values. Literal `${USMS_ACCOUNT_ID}` in the file means you used a quoted heredoc.

**Part 4 - the new role**

```bash
READER_ROLE_ARN=$(aws iam create-role \
  --role-name usms-transcripts-reader-role \
  --description "Read-only transcripts access for a future USMS reporting task" \
  --assume-role-policy-document file://policies/trust-ecs-tasks-scoped.json \
  --max-session-duration 3600 \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 Key=Tier,Value=data \
  --query 'Role.Arn' --output text)

echo "READER_ROLE_ARN = $READER_ROLE_ARN"

aws iam attach-role-policy \
  --role-name usms-transcripts-reader-role \
  --policy-arn "$RO_POLICY_ARN"
```

**Part 5 - fix the trust policy on the role that already exists**

!!! danger "Read before running any update to a trust policy"
    **What will be replaced:** the entire assume-role policy document on `usms-ecs-task-role`.
    `update-assume-role-policy` is a **replace**, not a merge - whatever you send becomes the whole
    document.

    **What depends on it:** every running enrolment task. On real AWS, a task whose task role cannot
    be assumed starts and then fails when it first calls an AWS API, and the error appears in the
    container's logs rather than in ECS's events.

    **Reversible?** Yes. The original document is one statement long and Step 4's inventory has a copy
    of it: `outputs/lab-09-identity-inventory.json`. Part 6 below writes it out separately as well,
    before the change, so that the undo is a file rather than a memory.

    **Effect on later labs:** none, provided the conditions are correct. Lab 10 assumes this role
    works. A malformed condition would make it unassumable on real AWS and would make no difference
    at all on Floci - which is precisely why Part 6 reads the document back and checks it rather than
    trusting the empty output of a successful command.

```bash
# Keep the undo next to the change.
aws iam get-role --role-name "$USMS_ECS_TASK_ROLE" \
  --query 'Role.AssumeRolePolicyDocument' --output json \
  > outputs/lab-09-ecs-task-role-trust-before.json

cat outputs/lab-09-ecs-task-role-trust-before.json

aws iam update-assume-role-policy \
  --role-name "$USMS_ECS_TASK_ROLE" \
  --policy-document file://policies/trust-ecs-tasks-scoped.json
```

If `$USMS_ECS_TASK_ROLE` is not set in `configs/lab-04.env`, use the literal name, and add the variable to that file afterwards:

```bash
USMS_ECS_TASK_ROLE="${USMS_ECS_TASK_ROLE:-usms-ecs-task-role}"
echo "task role: $USMS_ECS_TASK_ROLE"
```

**Part 6 - verify**

```bash
echo "== the new role =="
aws iam get-role --role-name usms-transcripts-reader-role \
  --query 'Role.{Name:RoleName,MaxSession:MaxSessionDuration,Trust:AssumeRolePolicyDocument}' \
  --output json

echo
echo "== its permissions =="
aws iam list-attached-role-policies --role-name usms-transcripts-reader-role \
  --query 'AttachedPolicies[].PolicyName' --output text

echo
echo "== the rewritten trust policy on the existing task role =="
aws iam get-role --role-name "$USMS_ECS_TASK_ROLE" \
  --query 'Role.AssumeRolePolicyDocument' --output json \
  > outputs/lab-09-ecs-task-role-trust-after.json

python3 - << 'PY'
import json
before = json.load(open("outputs/lab-09-ecs-task-role-trust-before.json"))
after  = json.load(open("outputs/lab-09-ecs-task-role-trust-after.json"))

def principals(doc):
    out = []
    sts = doc.get("Statement")
    sts = sts if isinstance(sts, list) else [sts]
    for s in sts:
        out.append((json.dumps(s.get("Principal"), sort_keys=True), bool(s.get("Condition"))))
    return out

print("before:", principals(before))
print("after :", principals(after))

same_principal = [p for p, _ in principals(before)] == [p for p, _ in principals(after)]
gained_cond    = all(c for _, c in principals(after)) and not all(c for _, c in principals(before))

print()
print("SAME PRINCIPAL, NEW CONDITION" if (same_principal and gained_cond)
      else "CHECK THIS BY HAND - the principal changed, or no condition was added")
PY
```

**Expected result**

```text
== the new role ==
{
    "Name": "usms-transcripts-reader-role",
    "MaxSession": 3600,
    "Trust": {
        "Version": "2012-10-17",
        "Statement": [ { "Sid": "EcsTasksMayAssumeThisRoleForThisAccountOnly", ... } ]
    }
}

== its permissions ==
USMSStudentDataReadOnly

== the rewritten trust policy on the existing task role ==
before: [('{"Service": "ecs-tasks.amazonaws.com"}', False)]
after : [('{"Service": "ecs-tasks.amazonaws.com"}', True)]

SAME PRINCIPAL, NEW CONDITION
```

> Example output.

`SAME PRINCIPAL, NEW CONDITION`: who may assume the role did not change; the circumstances did. A changed principal would be a functional change.

**Checkpoint 3**

```text
Identity, half fixed
 ├── USMSStudentDataReadOnly           Get + List, with an explicit Deny on every write
 ├── usms-transcripts-reader-role      scoped ecs-tasks trust, read-only policy
 ├── usms-ecs-task-role                SAME principal, NEW confused-deputy conditions
 ├── usms-ec2-app-role                 STILL unconditioned - ec2 does not send aws:SourceArn
 └── outputs/lab-09-ecs-task-role-trust-before.json    the undo, kept next to the change
```

---

### Step 8 - Scope `iam:PassRole`, and put a ceiling on a role for the first time

Build the deployment identity the course has never had (everything so far ran as root), with a scoped `iam:PassRole` and a permissions boundary.

`iam:PassRole` gates handing a role to a service (Lab 3 passed `usms-ec2-app-profile`; Lab 4 passed the ECS roles). Unscoped, it is an escalation path:

```text
1. Attacker controls a principal with:   ec2:RunInstances  and  iam:PassRole on Resource "*"
2. There exists somewhere in the account: an admin role with an ec2.amazonaws.com trust policy
3. Attacker launches an instance, passing that admin role as its instance profile
4. Attacker reads the instance's credentials out of the metadata service
5. Attacker is now an administrator
```

Every step is a documented API call. The fix is scoping `iam:PassRole` to named ARNs plus an `iam:PassedToService` condition. See [iam:PassRole](../unit8/topic1.md#iampassrole).

A **permissions boundary** sits in a second slot and grants nothing; effective permissions are the intersection:

```text
identity policy says:   s3:*, ec2:*, iam:*
boundary says:          s3:*, ec2:*
effective:              s3:*, ec2:*          <- iam:* is capped away, silently

identity policy says:   s3:GetObject
boundary says:          s3:*, ec2:*
effective:              s3:GetObject         <- the boundary granted NOTHING
```

It is how you safely delegate role creation. See [permissions boundaries](../unit8/topic1.md#permissions-boundaries-and-delegated-administration).

**Part 1 - the boundary document**

```bash
cat > policies/usms-permissions-boundary.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TheCeilingForEverythingUSMSDeploys",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:CreateTags",
        "ecs:*",
        "elasticloadbalancing:*",
        "application-autoscaling:*",
        "logs:*",
        "cloudwatch:*",
        "s3:Get*",
        "s3:List*",
        "s3:PutObject",
        "iam:PassRole",
        "iam:Get*",
        "iam:List*",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NoIdentityChangesUnderAnyCircumstances",
      "Effect": "Deny",
      "Action": [
        "iam:CreateUser",
        "iam:CreateAccessKey",
        "iam:AttachUserPolicy",
        "iam:PutUserPolicy",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy",
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "organizations:*",
        "account:*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NeverTouchTheCourseNetwork",
      "Effect": "Deny",
      "Action": [
        "ec2:DeleteVpc",
        "ec2:DeleteSubnet",
        "ec2:DeleteInternetGateway",
        "ec2:DeleteNatGateway"
      ],
      "Resource": "*"
    }
  ]
}
EOF

python3 -m json.tool policies/usms-permissions-boundary.json > /dev/null && echo "valid JSON"
```

- Quoted heredoc. `Resource: "*"` is correct for a ceiling; predict why Step 18's audit does not flag it.
- The second statement denies every way of changing who can do what, so the role cannot escalate even if someone attaches an admin policy. `iam:DeleteRolePermissionsBoundary` stops it removing its own ceiling.

**Part 2 - create it, and do not attach it to anything**

```bash
BOUNDARY_ARN=$(aws iam create-policy \
  --policy-name USMSPermissionsBoundary \
  --description "A CEILING, not a grant. Used only as a --permissions-boundary. Never attach this." \
  --policy-document file://policies/usms-permissions-boundary.json \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 Key=Purpose,Value=boundary \
  --query 'Policy.Arn' --output text)

echo "BOUNDARY_ARN = $BOUNDARY_ARN"
```

**Part 3 - the deploy policy, with a scoped `iam:PassRole`**

```bash
cat > policies/usms-deploy-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DeployTheContainerPlatform",
      "Effect": "Allow",
      "Action": [
        "ecs:RegisterTaskDefinition",
        "ecs:DeregisterTaskDefinition",
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeTaskDefinition",
        "ecs:ListTasks",
        "ecs:DescribeTasks",
        "elasticloadbalancing:Describe*",
        "application-autoscaling:Describe*",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PassOnlyTheseThreeRolesAndOnlyToTheseServices",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::${USMS_ACCOUNT_ID}:role/usms-ecs-exec-role",
        "arn:aws:iam::${USMS_ACCOUNT_ID}:role/usms-ecs-task-role",
        "arn:aws:iam::${USMS_ACCOUNT_ID}:role/usms-transcripts-reader-role"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ecs-tasks.amazonaws.com"
        }
      }
    },
    {
      "Sid": "NeverPassAnythingToEC2",
      "Effect": "Deny",
      "Action": "iam:PassRole",
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ec2.amazonaws.com"
        }
      }
    }
  ]
}
EOF

python3 -m json.tool policies/usms-deploy-policy.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-deploy-policy.json

DEPLOY_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSDeployBase \
  --description "What a USMS deployment pipeline may do. iam:PassRole scoped to three roles." \
  --policy-document file://policies/usms-deploy-policy.json \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 \
  --query 'Policy.Arn' --output text)

echo "DEPLOY_POLICY_ARN = $DEPLOY_POLICY_ARN"
```

Unquoted heredoc (three ARNs use `${USMS_ACCOUNT_ID}`); `grep -c '\$'` must print `0`.

- **Statement 1** is what the pipeline does. `ecs:UpdateService` on `*` is a genuine MED finding (Exercise 2).
- **Statement 2** passes three named roles, only to ECS tasks: the escalation's step 3 is now impossible.
- **Statement 3** explicitly denies passing anything to EC2, which survives a future broad `Allow`. Without `iam:PassedToService`, `usms-ecs-task-role` could be passed to EC2 and an instance could write transcripts.

**Part 4 - the trust policy and the role**

```bash
cat > policies/trust-deploy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OnlyTheAdminUserMayDeploy",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${USMS_ACCOUNT_ID}:user/${USMS_ADMIN_USER}"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

python3 -m json.tool policies/trust-deploy.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/trust-deploy.json

DEPLOY_ROLE_ARN=$(aws iam create-role \
  --role-name usms-deploy-role \
  --description "The identity a USMS deployment runs as. Capped by USMSPermissionsBoundary." \
  --assume-role-policy-document file://policies/trust-deploy.json \
  --permissions-boundary "$BOUNDARY_ARN" \
  --max-session-duration 3600 \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 Key=Tier,Value=pipeline \
  --query 'Role.Arn' --output text)

echo "DEPLOY_ROLE_ARN = $DEPLOY_ROLE_ARN"

aws iam attach-role-policy \
  --role-name usms-deploy-role \
  --policy-arn "$DEPLOY_POLICY_ARN"
```

`--permissions-boundary` sets the ceiling (`put-role-permissions-boundary` does it afterwards). The trust policy names a **user** in your own account, which is not a confused-deputy risk; its hardening would be MFA (Section 11, Exercise 2).

!!! warning "If your build rejects `--permissions-boundary`"
    Some builds silently ignore the flag; some reject it. Check:

    ```bash
    aws iam get-role --role-name usms-deploy-role \
      --query 'Role.PermissionsBoundary' --output json
    ```

    `null` means boundaries are not stored. Record it, try `put-role-permissions-boundary` once, and continue; Section 8 lists it as a known benign failure.

**Part 5 - verify**

```bash
echo "== the deploy role =="
aws iam get-role --role-name usms-deploy-role \
  --query 'Role.{Name:RoleName,Boundary:PermissionsBoundary.PermissionsBoundaryArn,MaxSession:MaxSessionDuration,Principal:AssumeRolePolicyDocument.Statement[0].Principal}' \
  --output json

echo
echo "== what it may pass, and to what =="
aws iam get-policy-version \
  --policy-arn "$DEPLOY_POLICY_ARN" \
  --version-id "$(aws iam get-policy --policy-arn "$DEPLOY_POLICY_ARN" --query 'Policy.DefaultVersionId' --output text)" \
  --query 'PolicyVersion.Document.Statement[?Action==`iam:PassRole`]' \
  --output json

echo
echo "== is the boundary attached to anything as an ordinary policy? (it must NOT be) =="
aws iam list-entities-for-policy --policy-arn "$BOUNDARY_ARN" \
  --query '{Roles:PolicyRoles[].RoleName,Users:PolicyUsers[].UserName,Groups:PolicyGroups[].GroupName}' \
  --output json
```

**Expected result**

```text
== the deploy role ==
{
    "Name": "usms-deploy-role",
    "Boundary": "arn:aws:iam::000000000000:policy/USMSPermissionsBoundary",
    "MaxSession": 3600,
    "Principal": { "AWS": "arn:aws:iam::000000000000:user/usms-admin-01" }
}

== what it may pass, and to what ==
[
    {
        "Sid": "PassOnlyTheseThreeRolesAndOnlyToTheseServices",
        "Effect": "Allow",
        "Action": "iam:PassRole",
        "Resource": [
            "arn:aws:iam::000000000000:role/usms-ecs-exec-role",
            "arn:aws:iam::000000000000:role/usms-ecs-task-role",
            "arn:aws:iam::000000000000:role/usms-transcripts-reader-role"
        ],
        "Condition": { "StringEquals": { "iam:PassedToService": "ecs-tasks.amazonaws.com" } }
    },
    {
        "Sid": "NeverPassAnythingToEC2",
        "Effect": "Deny",
        ...
    }
]

== is the boundary attached to anything as an ordinary policy? (it must NOT be) ==
{
    "Roles": null,
    "Users": null,
    "Groups": null
}
```

> Example output - your ARNs will differ.

1. **`Boundary` is not null.**
2. **The `PassRole` statement names three ARNs and no wildcard**, none of them an administrator.
3. **The boundary is attached to nothing.** It looks like an orphan; a colleague tidying up would delete the one control capping the pipeline. Section 15's KEEP column says so too.

**Checkpoint 4**

```text
Identity, fixed
 ├── USMSPermissionsBoundary       a ceiling; attached to NOTHING; used as a boundary once
 ├── USMSDeployBase                iam:PassRole -> 3 named roles, ecs-tasks only
 │                                 + explicit Deny on passing anything to EC2
 ├── usms-deploy-role              trusts user/usms-admin-01, WITH a boundary
 └── the escalation path in this step's concept block is now closed at step 1 AND step 3
```

---

### Step 9 - Scope down a session, and compute an intersection

A **session policy** narrows an assumed role for one session. This step uses one and makes you compute the effective permissions by hand.

| Mechanism | Attached to | Lives for | Set by | Can it grant? |
| --- | --- | --- | --- | --- |
| Identity policy | A role, user or group | Until detached | Whoever administers IAM | **Yes** |
| Permissions boundary | A role or user, in a second slot | Until removed | Whoever created the principal | No - caps only |
| Session policy | One `sts:AssumeRole` call | The session, up to an hour here | **The caller**, at assume time | No - caps only |

The caller sets it on themselves, like a seatbelt: a pipeline step that only reads logs cannot delete a service through its own bug.

```text
effective = identity policy  AND  boundary  AND  session policy
```

**Part 1 - write a session policy**

```bash
cat > outputs/lab-09-session-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ThisSessionMayOnlyLook",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
EOF

python3 -m json.tool outputs/lab-09-session-policy.json > /dev/null && echo "valid JSON"
```

It lives in `outputs/`, not `policies/`: it is an argument to one API call, not part of the account's posture.

**Part 2 - assume the role with it**

```bash
ROLE_ARN="arn:aws:iam::${USMS_ACCOUNT_ID}:role/${USMS_ROLE_DEVELOPER}"

aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "lab05-scoped-review" \
  --policy file://outputs/lab-09-session-policy.json \
  --duration-seconds 900 \
  --profile usms-dev \
  > outputs/lab-09-scoped-session.json \
  || echo "assume-role with --policy not supported on this build - see the fallback below"

chmod 600 outputs/lab-09-scoped-session.json 2>/dev/null || true

if [ -s outputs/lab-09-scoped-session.json ]; then
  export AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId'     outputs/lab-09-scoped-session.json)
  export AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' outputs/lab-09-scoped-session.json)
  export AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken'    outputs/lab-09-scoped-session.json)

  aws sts get-caller-identity --no-cli-pager
  aws ec2 describe-vpcs --query 'length(Vpcs)' --output text
fi
```

!!! warning "These three variables now outrank your profile, exactly as they did in Lab 02 Step 3"
    Until Part 4 unsets them, every `aws` command here runs as the scoped session, whatever `--profile` you pass. `--duration-seconds 900` keeps the session as short as the work.

**Part 3 - compute the intersection by hand**

```bash
python3 - << 'PY'
import json, subprocess

def doc_actions(doc):
    """Every Allow action in a policy document, flattened."""
    out = set()
    sts = doc.get("Statement")
    sts = sts if isinstance(sts, list) else [sts]
    for s in sts:
        if s.get("Effect") != "Allow":
            continue
        acts = s.get("Action")
        acts = acts if isinstance(acts, list) else [acts]
        out.update(acts)
    return out

def denies(doc):
    out = set()
    sts = doc.get("Statement")
    sts = sts if isinstance(sts, list) else [sts]
    for s in sts:
        if s.get("Effect") != "Deny":
            continue
        acts = s.get("Action")
        acts = acts if isinstance(acts, list) else [acts]
        out.update(acts)
    return out

def matches(action, pattern):
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return action.lower().startswith(pattern[:-1].lower())
    return action.lower() == pattern.lower()

# the role's identity policy
inv = json.load(open("outputs/lab-09-identity-inventory.json"))
role = next((r for r in inv if r["role"].endswith("developer-role")), None)
if role is None:
    raise SystemExit("usms-developer-role not in the inventory - re-run Step 4")

identity_allow = set()
identity_deny  = set()
for p in role["attachedPolicies"]:
    if p.get("document"):
        identity_allow |= doc_actions(p["document"])
        identity_deny  |= denies(p["document"])

session = json.load(open("outputs/lab-09-session-policy.json"))
session_allow = doc_actions(session)

print("identity policy allows (patterns):")
for a in sorted(identity_allow):
    print("   ", a)
print()
print("session policy allows:")
for a in sorted(session_allow):
    print("   ", a)
print()
print("EFFECTIVE - an action needs a match in BOTH and a match in NEITHER deny:")
for a in sorted(session_allow):
    in_identity = any(matches(a, p) for p in identity_allow)
    denied      = any(matches(a, p) for p in identity_deny)
    verdict = "ALLOWED" if (in_identity and not denied) else \
              ("denied by an explicit Deny" if denied else "NOT in the identity policy -> denied")
    print(f"    {a:<32} {verdict}")
PY
```

For each session action it asks: allowed by the identity policy, and denied anywhere? `matches` handles only trailing `*` wildcards and ignores resources and conditions, which is enough for this course and says so.

**Expected result**

```text
identity policy allows (patterns):
    ec2:CreateRouteTable
    ec2:CreateSubnet
    ec2:CreateVpc
    ec2:Describe*
    ...

session policy allows:
    ec2:DescribeSecurityGroups
    ec2:DescribeSubnets
    ec2:DescribeVpcs
    sts:GetCallerIdentity

EFFECTIVE - an action needs a match in BOTH and a match in NEITHER deny:
    ec2:DescribeSecurityGroups       ALLOWED
    ec2:DescribeSubnets              ALLOWED
    ec2:DescribeVpcs                 ALLOWED
    sts:GetCallerIdentity            NOT in the identity policy -> denied
```

> Example output - the exact identity actions depend on what your Lab 01 wrote into
> `USMSDeveloperBase` v2.

At least one line must **not** be `ALLOWED`. Usually `sts:GetCallerIdentity`: the session allows it but the identity policy never did, and **a session policy cannot grant anything the role did not already have**. If `USMSDeveloperBase` includes `sts:*`, use `s3:ListAllMyBuckets` instead and re-run.

!!! note "Floci Limitation - the session policy is not enforced, and `simulate-principal-policy` may be absent"
    Floci returns credentials for `--policy` and then authorises nothing. Real AWS evaluates the intersection on every call. If Step 3 found `simulate-principal-policy` supported, use it as a second opinion:

    ```bash
    aws iam simulate-principal-policy \
      --policy-source-arn "arn:aws:iam::${USMS_ACCOUNT_ID}:role/${USMS_ROLE_DEVELOPER}" \
      --action-names ec2:DescribeVpcs sts:GetCallerIdentity iam:CreateUser \
      --query 'EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision}' \
      --output table
    ```

    Otherwise the Python above is the "read the documents and justify it" fallback. Say which you used.

**Part 4 - restore your normal identity**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
rm -f outputs/lab-09-scoped-session.json
```

`whoami.sh` must report root and account `000000000000`. The session file is deleted at once: expired credentials are dead weight.

---

### Step 10 - Rotate the access key, with no window in which nothing works

`usms-dev-01`'s Lab 1 key is the one long-lived credential here. Rotate it with no outage window, using IAM's two-keys-per-user allowance:

```text
1. CREATE a second key                  -> two keys, both active, nothing has changed
2. UPDATE every consumer to the new key -> traffic moves over, old key still works as a fallback
3. DEACTIVATE the old key               -> reversible. If something breaks, reactivate it
4. DELETE the old key                   -> irreversible, and only after step 3 has been quiet
```

Step 3 (deactivate) is what makes it safe: a deactivated key can be reactivated; a deleted one is gone. See [access key hygiene](../unit8/topic1.md#access-keys-and-their-hygiene).

**Part 1 - look at what you have**

```bash
aws iam list-access-keys --user-name "$USMS_DEV_USER" \
  --query 'AccessKeyMetadata[].{Key:AccessKeyId,Status:Status,Created:CreateDate}' \
  --output table

for k in $(aws iam list-access-keys --user-name "$USMS_DEV_USER" \
             --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  printf '%-24s ' "$k"
  aws iam get-access-key-last-used --access-key-id "$k" \
    --query 'AccessKeyLastUsed.{When:LastUsedDate,Service:ServiceName,Region:Region}' \
    --output text 2>/dev/null || echo "last-used not available on this build"
done
```

`get-access-key-last-used` answers whether anything still uses a key.

**Expected result**

```text
------------------------------------------------------------------------
|                           ListAccessKeys                             |
+----------------------------+----------+----------------------------+
|          Created           |  Status  |            Key             |
+----------------------------+----------+----------------------------+
|  2026-08-08T09:20:13+00:00 |  Active  |  AKIAIOSFODNN7EXAMPLE      |
+----------------------------+----------+----------------------------+
AKIAIOSFODNN7EXAMPLE     2026-09-05T11:02:44+00:00   sts   us-east-1
```

> Example output - your key ID and dates will differ. `N/A` in the last-used columns is common on
> Floci and is not a finding.

Exactly **one** key. Two means an earlier rotation was never finished, and two is the limit.

**Part 2 - create the new key, straight into `outputs/`**

!!! danger "Read before rotating a credential"
    **What will change:** `usms-dev-01` gains a second access key, the `usms-dev` CLI profile is
    repointed at it, and the original key is first deactivated and then deleted.

    **What depends on it:** the `usms-dev` profile, which Lab 02 Step 3 used to assume
    `usms-developer-role` and which Step 9 of this lab used ten minutes ago. Nothing else in the
    course reads that key.

    **Reversible?** Up to and including part 4 (deactivate), completely - one `update-access-key
    --status Active` puts it back. After part 5 (delete), not at all: AWS never shows a secret access
    key twice and cannot re-issue one.

    **Effect on later labs:** none if the procedure is followed in order, because the profile ends up
    working with a different key. If part 3 is skipped, `--profile usms-dev` stops working and every
    lab that uses it fails with `InvalidClientTokenId`.

```bash
aws iam create-access-key --user-name "$USMS_DEV_USER" \
  > outputs/usms-dev-01-access-key-new.json

chmod 600 outputs/usms-dev-01-access-key-new.json

git check-ignore -v outputs/usms-dev-01-access-key-new.json

NEW_KEY_ID=$(jq -r '.AccessKey.AccessKeyId' outputs/usms-dev-01-access-key-new.json)
echo "new key id: $NEW_KEY_ID"

OLD_KEY_ID=$(aws iam list-access-keys --user-name "$USMS_DEV_USER" \
  --query "AccessKeyMetadata[?AccessKeyId!='$NEW_KEY_ID'].AccessKeyId | [0]" \
  --output text)
echo "old key id: $OLD_KEY_ID"
```

- The secret goes **straight to a file**: never on screen, in scrollback or in a screenshot. The values are Floci dummies; the habit transfers.
- `git check-ignore -v` must name the rule and line. Silence means the file is **not** ignored: stop and fix `.gitignore`.
- `AccessKeyMetadata[?AccessKeyId!='...'] | [0]` picks "the other one" without assuming an order.

**Expected result**

```text
.gitignore:7:outputs/*  outputs/usms-dev-01-access-key-new.json
new key id: AKIAI44QH8DHBEXAMPLE
old key id: AKIAIOSFODNN7EXAMPLE
```

> Example output - your key IDs and line number will differ.

**Part 3 - move the consumer over**

```bash
aws configure set aws_access_key_id \
  "$(jq -r '.AccessKey.AccessKeyId' outputs/usms-dev-01-access-key-new.json)" --profile usms-dev
aws configure set aws_secret_access_key \
  "$(jq -r '.AccessKey.SecretAccessKey' outputs/usms-dev-01-access-key-new.json)" --profile usms-dev

aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text
aws configure get aws_access_key_id --profile usms-dev
```

The ARN still reads `user/usms-dev-01`, and `aws configure get` prints the **new** key ID: the profile works because of the new key.

**Part 4 - deactivate the old key and prove nothing broke**

```bash
aws iam update-access-key \
  --user-name "$USMS_DEV_USER" \
  --access-key-id "$OLD_KEY_ID" \
  --status Inactive

aws iam list-access-keys --user-name "$USMS_DEV_USER" \
  --query 'AccessKeyMetadata[].{Key:AccessKeyId,Status:Status}' --output table

aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text
```

Two keys, one `Active`, one `Inactive`, and the profile still answering. On a real system you would wait here a day or a week; say in your report that this lab compresses that pause.

**Part 5 - delete the old key**

```bash
aws iam delete-access-key \
  --user-name "$USMS_DEV_USER" \
  --access-key-id "$OLD_KEY_ID"

aws iam list-access-keys --user-name "$USMS_DEV_USER" \
  --query 'AccessKeyMetadata[].{Key:AccessKeyId,Status:Status,Created:CreateDate}' --output table

aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text

rm -f outputs/usms-dev-01-access-key.json
ls -l outputs/ | grep -i access-key || echo "no other access key files remain"
```

**Expected result**

```text
------------------------------------------------------------------------
|                           ListAccessKeys                             |
+----------------------------+----------+----------------------------+
|          Created           |  Status  |            Key             |
+----------------------------+----------+----------------------------+
|  2026-09-06T04:31:07+00:00 |  Active  |  AKIAI44QH8DHBEXAMPLE      |
+----------------------------+----------+----------------------------+
arn:aws:iam::000000000000:user/usms-dev-01
no other access key files remain
```

> Example output.

!!! note "Conceptual / Real AWS - what would actually make this key unnecessary"
    On a real account, humans would use IAM Identity Center or federation for temporary credentials, and workloads would use roles. The course keeps one key because Lab 2's assume-role handshake needs a named principal. Say in your report what you would replace it with.

**Checkpoint 5**

```text
Credentials
 ├── usms-dev-01                 exactly one access key, created today
 ├── the usms-dev profile        repointed, verified before the old key was touched
 ├── the old key                 deactivated, verified, THEN deleted
 ├── outputs/                    old key file removed; new one chmod 600 and git-ignored
 └── the four-step order         create -> move -> deactivate -> delete, and why 3 exists
```

---

### Step 11 - Require IMDSv2 on the web instance

`usms-web-01`'s instance profile credentials are served by the metadata service at `169.254.169.254`. Harden how they can be fetched.

```text
A server-side request forgery (SSRF) bug lets an attacker make the APPLICATION issue a
request to a URL of the attacker's choosing. The attacker controls the URL. In almost every
such bug, the attacker does NOT control the METHOD or the HEADERS.

IMDSv1:  attacker supplies  http://169.254.169.254/latest/meta-data/iam/security-credentials/
         the application GETs it, and returns the credentials in the response.
IMDSv2:  the same GET is refused. Obtaining a token requires a PUT with a header, and the
         SSRF bug can do neither.
```

`--http-put-response-hop-limit 1` stops the metadata response leaving the instance, so a container on it (one hop away) cannot inherit the host's role. See [IMDSv2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html).

**Part 1 - look before you change**

```bash
aws ec2 describe-instances --instance-ids "$USMS_WEB_INSTANCE" \
  --query 'Reservations[0].Instances[0].MetadataOptions' --output json \
  | tee outputs/lab-09-imds-before.json
```

**Expected result**

```text
{
    "State": "applied",
    "HttpTokens": "optional",
    "HttpPutResponseHopLimit": 1,
    "HttpEndpoint": "enabled",
    "HttpProtocolIpv6": "disabled",
    "InstanceMetadataTags": "disabled"
}
```

> Example output. `HttpTokens: "optional"` is the AWS default for an instance launched from an older
> AMI or without the option set, and it is the finding.

`HttpTokens: optional` means IMDSv1 works and the SSRF path is open. If your build returns an empty object, record it and see the fallback below.

**Part 2 - require tokens**

```bash
aws ec2 modify-instance-metadata-options \
  --instance-id "$USMS_WEB_INSTANCE" \
  --http-tokens required \
  --http-endpoint enabled \
  --http-put-response-hop-limit 1 \
  --query '{Instance:InstanceId,State:InstanceMetadataOptions.State,Tokens:InstanceMetadataOptions.HttpTokens,Hops:InstanceMetadataOptions.HttpPutResponseHopLimit}' \
  --output json \
  || echo "modify-instance-metadata-options not supported on this build - record it and continue"
```

- `--http-tokens required` disables IMDSv1. On real AWS, watch the `MetadataNoToken` metric reach zero before requiring tokens, or old SDKs break.
- `--http-endpoint enabled` keeps the service on; disabling it suits an instance with no role (the "Your turn").
- `--http-put-response-hop-limit 1` is the container defence. Lab 3's `user-data.sh` already uses the token flow.

**Part 3 - verify**

```bash
aws ec2 describe-instances --instance-ids "$USMS_WEB_INSTANCE" \
  --query 'Reservations[0].Instances[0].MetadataOptions' --output json \
  | tee outputs/lab-09-imds-after.json

python3 - << 'PY'
import json
before = json.load(open("outputs/lab-09-imds-before.json")) or {}
after  = json.load(open("outputs/lab-09-imds-after.json"))  or {}
print(f"HttpTokens : {before.get('HttpTokens','?')}  ->  {after.get('HttpTokens','?')}")
print(f"HopLimit   : {before.get('HttpPutResponseHopLimit','?')}  ->  {after.get('HttpPutResponseHopLimit','?')}")
ok = after.get("HttpTokens") == "required" and after.get("HttpPutResponseHopLimit") == 1
print()
print("IMDSv2 REQUIRED, HOP LIMIT 1" if ok else
      "NOT APPLIED - record this as a Floci limitation and say what real AWS would have done")
PY
```

**Expected result**

```text
HttpTokens : optional  ->  required
HopLimit   : 1  ->  1

IMDSv2 REQUIRED, HOP LIMIT 1
```

> Example output.

!!! note "Floci Limitation - there is no metadata service to harden"
    Floci serves no IMDS to instances (Lab 3 Step 11). Some builds store `MetadataOptions`; some ignore the change.

    Real AWS enforces it at the hypervisor as soon as the call returns.

    In your report, name the attack `--http-tokens required` prevents, the different attack the hop limit prevents, and the rollout order that avoids an outage. Section 13 asks for all three.

✏️ **Your turn**

`usms-db-01` has **no** instance profile - Lab 03 Step 16 left it that way deliberately. Work out what
its metadata options should therefore be, apply them, and read them back.

```text
Expected result:
A describe-instances query on usms-db-01 showing a metadata configuration you can
justify in one sentence. There is a stronger setting available for an instance with
no role than the one you just applied to usms-web-01, and the flag for it is in
`aws ec2 modify-instance-metadata-options help`.

Then answer in one sentence: what would break if you applied that same stronger
setting to usms-web-01?
```

Hint: Lab 3 Step 11 explains where `usms-web-01`'s credentials come from.

**Checkpoint 6**

```text
usms-web-01
 ├── IMDSv2  HttpTokens required        SSRF cannot reach the credentials
 ├── hop limit 1                        a container on the instance cannot either
 ├── HttpEndpoint enabled               because this instance HAS a role and needs it
 └── usms-db-01                         handled in the "Your turn", and differently, because
                                        it has no role at all
```

---

!!! info "Reviewing a security group: four questions"
    1. **Who can reach me?** (ingress) 2. **What can I reach?** (egress: the rule nobody wrote) 3. **Is the source a group or an address?** (a group survives re-addressing) 4. **Is the group attached to anything?** Every group gets an allow-all egress rule by default; security groups are **stateful**, so restricting egress does not break replies to inbound requests; and a group with no egress rules can initiate nothing. Steps 13 to 15 restrict only traffic the workload **initiates**. See [egress control](../unit8/topic2.md#egress-control-and-data-exfiltration).

### Step 12 - Build the security group audit script

Do for the network what Step 5 did for identity: findings computed from rules, not names. Read-only.

````bash
cat > scripts/utilities/usms-sg-audit.sh << 'EOF'
#!/usr/bin/env bash
# USMS security group audit. Reports findings; changes nothing.
#
# Four questions per group:
#   1. who can reach me            ingress: group-referenced, CIDR, or 0.0.0.0/0
#   2. what can I reach            egress: written, or the default allow-all
#   3. group or address            a CIDR source that could have been a group
#   4. attached to anything        groups with no network interfaces
#
# Read-only. Exit 0 if there are no HIGH findings, 1 otherwise.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$REPO_ROOT/configs/course.env" 2>/dev/null || true
# shellcheck disable=SC1090
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true

VPC="${1:-${USMS_VPC_ID:-}}"
if [ -z "$VPC" ] || [ "$VPC" = "none" ]; then
  echo "usage: $0 [vpc-id]   (or set USMS_VPC_ID in configs/lab-02.env)" >&2
  exit 2
fi

# One JSON document with every group in the VPC, plus how many interfaces each one is on.
aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" --output json \
  > /tmp/usms-sg-audit-$$.json || { echo "cannot read security groups" >&2; exit 2; }

for g in $(python3 -c "
import json;print(' '.join(s['GroupId'] for s in json.load(open('/tmp/usms-sg-audit-$$.json'))['SecurityGroups']))
"); do
  n=$(aws ec2 describe-network-interfaces --filters "Name=group-id,Values=$g" \
        --query 'length(NetworkInterfaces)' --output text 2>/dev/null || echo 0)
  echo "$g $n"
done > /tmp/usms-sg-enis-$$.txt

python3 - "/tmp/usms-sg-audit-$$.json" "/tmp/usms-sg-enis-$$.txt" << 'PY'
import json, sys

groups = json.load(open(sys.argv[1]))["SecurityGroups"]
enis = {}
for line in open(sys.argv[2]):
    parts = line.split()
    if len(parts) == 2:
        try:
            enis[parts[0]] = int(parts[1])
        except ValueError:
            enis[parts[0]] = 0

by_id = {g["GroupId"]: g.get("GroupName", g["GroupId"]) for g in groups}

def render(perms):
    """One readable line per rule."""
    out = []
    for p in perms:
        proto = p.get("IpProtocol", "-1")
        proto = "all" if proto == "-1" else proto
        lo, hi = p.get("FromPort"), p.get("ToPort")
        port = "all" if lo is None else (str(lo) if lo == hi else f"{lo}-{hi}")
        dests = []
        for r in p.get("IpRanges", []):
            dests.append(r.get("CidrIp"))
        for r in p.get("Ipv6Ranges", []):
            dests.append(r.get("CidrIpv6"))
        for r in p.get("UserIdGroupPairs", []):
            gid = r.get("GroupId")
            dests.append(f"sg:{by_id.get(gid, gid)}")
        for r in p.get("PrefixListIds", []):
            dests.append(f"pl:{r.get('PrefixListId')}")
        out.append((proto, port, dests or ["<none>"]))
    return out

high = med = low = 0
print("== USMS security group audit ==")
print()

for g in sorted(groups, key=lambda x: x.get("GroupName", "")):
    name = g.get("GroupName", g["GroupId"])
    gid = g["GroupId"]
    n = enis.get(gid, 0)
    findings = []

    print(f"{name}  ({gid})   interfaces: {n}")

    print("    ingress:")
    ing = render(g.get("IpPermissions", []))
    if not ing:
        print("        (none - nothing may reach anything wearing this group)")
    for proto, port, dests in ing:
        print(f"        {proto}/{port:<9} from {', '.join(dests)}")
        for d in dests:
            if d in ("0.0.0.0/0", "::/0"):
                findings.append(("HIGH", f"ingress {proto}/{port} from {d}"))
            elif d and d.startswith("10.") and d.endswith("/16"):
                findings.append(("MED", f"ingress {proto}/{port} from a whole VPC range ({d}) "
                                        "- could this be a group reference?"))

    print("    egress:")
    egr = g.get("IpPermissionsEgress", [])
    eg = render(egr)
    if not eg:
        print("        (none - nothing wearing this group may initiate anything)")
    for proto, port, dests in eg:
        print(f"        {proto}/{port:<9} to   {', '.join(dests)}")
    # the default rule, exactly as AWS writes it
    default_egress = any(
        p.get("IpProtocol") == "-1"
        and any(r.get("CidrIp") == "0.0.0.0/0" for r in p.get("IpRanges", []))
        for p in egr)
    if default_egress:
        findings.append(("MED", "egress is the DEFAULT allow-all rule - nobody wrote this"))

    if n == 0:
        findings.append(("LOW", "attached to no network interface"))

    for sev, text in findings:
        print(f"    {sev:<4} {text}")
        if sev == "HIGH":
            high += 1
        elif sev == "MED":
            med += 1
        else:
            low += 1
    print()

print(f"HIGH={high}  MED={med}  LOW={low}  groups={len(groups)}")
sys.exit(1 if high else 0)
PY

rm -f /tmp/usms-sg-audit-$$.json /tmp/usms-sg-enis-$$.txt
EOF

chmod +x scripts/utilities/usms-sg-audit.sh
bash -n scripts/utilities/usms-sg-audit.sh && echo "syntax OK"
./scripts/utilities/usms-sg-audit.sh | tee outputs/lab-09-sg-findings-before.txt
````

- Four backticks again: two nested heredocs.
- It resolves group IDs to names (`by_id`), counts network interfaces per group (question 4), and detects the default egress rule by its exact shape, so Step 13's deliberate tcp/443 rule is not flagged like AWS's default.
- `$$` (the shell's PID) keeps temp files unique; the final `rm` runs even if Python fails.

**Expected result**

```text
syntax OK
== USMS security group audit ==

default  (sg-0aaaa1111bbbb2222)   interfaces: 0
    ingress:
        all/all       from sg:default
    egress:
        all/all       to   0.0.0.0/0
    MED  egress is the DEFAULT allow-all rule - nobody wrote this
    LOW  attached to no network interface

usms-alb-sg  (sg-0bb22cc33dd44ee55)   interfaces: 2
    ingress:
        tcp/80        from 0.0.0.0/0
    egress:
        all/all       to   0.0.0.0/0
    HIGH ingress tcp/80 from 0.0.0.0/0
    MED  egress is the DEFAULT allow-all rule - nobody wrote this

usms-app-sg  (sg-0123456789abcdef0)   interfaces: 1
    ingress:
        tcp/80        from 0.0.0.0/0
        tcp/443       from 0.0.0.0/0
        tcp/22        from 10.0.0.0/16
    egress:
        all/all       to   0.0.0.0/0
    HIGH ingress tcp/80 from 0.0.0.0/0
    HIGH ingress tcp/443 from 0.0.0.0/0
    MED  ingress tcp/22 from a whole VPC range (10.0.0.0/16) - could this be a group reference?
    MED  egress is the DEFAULT allow-all rule - nobody wrote this

usms-db-sg  (sg-0fedcba9876543210)   interfaces: 1
    ingress:
        tcp/5432      from sg:usms-app-sg
    egress:
        all/all       to   0.0.0.0/0
    MED  egress is the DEFAULT allow-all rule - nobody wrote this

usms-enrolment-sg  (sg-0aa11bb22cc33dd44)   interfaces: 2
    ingress:
        tcp/80        from sg:usms-alb-sg
    egress:
        all/all       to   0.0.0.0/0
    MED  egress is the DEFAULT allow-all rule - nobody wrote this

HIGH=3  MED=6  LOW=1  groups=5
```

> Example output - your IDs, interface counts and totals will differ, and `usms-bastion-sg` appears as
> well if you did Lab 02's Exercise 2.

**Verify**

Sort the findings before fixing any of them:

| Finding | Verdict |
| --- | --- |
| `usms-alb-sg` ingress tcp/80 from `0.0.0.0/0` | **Accepted risk, documented.** It is an internet-facing load balancer. Lab 05 Step 4 argued this properly and nothing has changed |
| `usms-app-sg` ingress 80 and 443 from `0.0.0.0/0` | **Open finding.** The web instance is a second internet-facing entry point that predates the load balancer, and Exercise 4 asks whether it should still exist |
| `usms-app-sg` ingress 22 from `10.0.0.0/16` | **Fix in Step 16.** Any compromised thing anywhere in the VPC can currently reach SSH |
| Default egress on all five groups | **Fix in Steps 13 to 15**, and Exercise 1 for `usms-app-sg` |
| `default` group on no interfaces | **Accepted.** Every VPC has one; nothing uses it; leave it |

The tool cannot tell that one `0.0.0.0/0` is fine and the other is a finding. **An audit tool produces findings, not verdicts.**

**Checkpoint 7**

```text
Network inventory complete
 ├── outputs/lab-09-sg-findings-before.txt   HIGH=3  MED=6  LOW=1
 ├── scripts/utilities/usms-sg-audit.sh      read-only, resolves group names, counts interfaces
 ├── finding: FIVE groups carry the default allow-all egress rule
 └── finding: usms-app-sg admits SSH from the whole VPC
```

---

### Step 13 - Write the egress rules for the enrolment tasks

Replace the allow-all egress on `usms-enrolment-sg` with rules derived from what the tasks must initiate:

| It must reach | Why | On what |
| --- | --- | --- |
| A container registry | To pull `usms-enrolment:2`'s image at task start | tcp/443, to addresses AWS or Docker Hub owns |
| CloudWatch Logs | The `awslogs` driver from Lab 04 ships every line | tcp/443, to the Logs endpoint |
| S3 | Lab 10's transcripts, through Lab 02's gateway endpoint | tcp/443, to S3's address ranges |
| Nothing else | There is nothing else in the design | - |

Not the database, the web instance, or anything on a port other than 443. tcp/443 to everywhere is still wide, but it blocks DNS exfiltration, SSH, database protocols, mail and arbitrary command-and-control ports. The S3 row can be precise via the gateway endpoint's **managed prefix list**. On real AWS, interface endpoints would tighten the rest (Section 11, Exercise 4).

**Part 1 - find the S3 prefix list**

```bash
S3_PREFIX_LIST=$(aws ec2 describe-prefix-lists \
  --filters "Name=prefix-list-name,Values=com.amazonaws.${AWS_REGION_COURSE}.s3" \
  --query 'PrefixLists[0].PrefixListId' --output text 2>/dev/null)

echo "from describe-prefix-lists: $S3_PREFIX_LIST"

if [ -z "$S3_PREFIX_LIST" ] || [ "$S3_PREFIX_LIST" = "None" ]; then
  S3_PREFIX_LIST=$(aws ec2 describe-route-tables --route-table-ids "$USMS_PRIVATE_RT" \
    --query 'RouteTables[0].Routes[?DestinationPrefixListId!=`null`].DestinationPrefixListId | [0]' \
    --output text 2>/dev/null)
  echo "from the private route table:  $S3_PREFIX_LIST"
fi

echo "S3_PREFIX_LIST = ${S3_PREFIX_LIST:-<none>}"
```

- Two sources tried in order, because builds differ on whether the prefix-list route is injected (Lab 2 Step 21).
- The backticks around `null` make it a JSON literal, not the string `"null"`.
- If both are empty, your build has no prefix lists: record it; Part 2 has a branch.

**Part 2 - write the egress document**

```bash
if [ -n "$S3_PREFIX_LIST" ] && [ "$S3_PREFIX_LIST" != "None" ]; then
cat > policies/usms-enrolment-sg-egress.json << EOF
[
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "PrefixListIds": [
      {
        "PrefixListId": "${S3_PREFIX_LIST}",
        "Description": "S3 via the Lab 02 gateway endpoint - transcripts, and nothing leaves the AWS network"
      }
    ]
  },
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "IpRanges": [
      {
        "CidrIp": "0.0.0.0/0",
        "Description": "HTTPS out for the container image pull and the awslogs driver - narrow this to interface endpoints on real AWS"
      }
    ]
  }
]
EOF
else
cat > policies/usms-enrolment-sg-egress.json << 'EOF'
[
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "IpRanges": [
      {
        "CidrIp": "0.0.0.0/0",
        "Description": "HTTPS out for the image pull, the awslogs driver and S3 - no prefix list on this build"
      }
    ]
  }
]
EOF
fi

python3 -m json.tool policies/usms-enrolment-sg-egress.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-enrolment-sg-egress.json
cat policies/usms-enrolment-sg-egress.json
```

The `if` picks an **unquoted** heredoc (expands `${S3_PREFIX_LIST}`) or a **quoted** one (nothing to expand). `grep -c '\$'` must print `0`. Every rule has a `Description`, the cheapest documentation in AWS.

**Part 3 - keep the undo, then make the change**

!!! danger "Read before revoking an egress rule"
    **What will be deleted:** the default allow-all egress rule on `usms-enrolment-sg` - protocol
    `-1`, destination `0.0.0.0/0`. Not the group, not any ingress rule, not any task.

    **What depends on it:** on **real AWS**, everything the tasks initiate. Revoking allow-all before
    authorising the replacement leaves a window in which a task cannot pull an image or ship a log
    line - so the order below is authorise first, revoke second. That is the same cutover discipline
    as Lab 05 Steps 9, 12 and 13, in the opposite direction.

    **Reversible?** Yes, completely. `policies/usms-egress-allow-all.json`, written below, is the
    document that puts it back, and it is written **before** the revoke.

    **Effect on later labs:** none on Floci, which carries no traffic. On real AWS, Lab 10 would need
    the S3 rule and Lab 04's log driver would need the 443 rule - both of which are in the document
    above, which is why they were derived from the architecture rather than guessed.

```bash
cat > policies/usms-egress-allow-all.json << 'EOF'
[
  {
    "IpProtocol": "-1",
    "IpRanges": [
      { "CidrIp": "0.0.0.0/0", "Description": "The AWS default egress rule. Kept here as the undo." }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-egress-allow-all.json > /dev/null && echo "undo document written"

# 1. authorise the replacement FIRST
aws ec2 authorize-security-group-egress \
  --group-id "$USMS_ENROLMENT_SG" \
  --ip-permissions file://policies/usms-enrolment-sg-egress.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text

# 2. only then revoke the default
aws ec2 revoke-security-group-egress \
  --group-id "$USMS_ENROLMENT_SG" \
  --ip-permissions file://policies/usms-egress-allow-all.json \
  --query 'Return' --output text
```

**Expected result**

```text
undo document written
sgr-0aa11bb22cc33dd44   sgr-0bb22cc33dd44ee55
True
```

> Example output - your rule IDs will differ, and the first line shows one ID rather than two if your
> build had no prefix list.

**Verify**

```bash
aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$USMS_ENROLMENT_SG" \
  --query 'SecurityGroupRules[?IsEgress==`true`].{Rule:SecurityGroupRuleId,Proto:IpProtocol,From:FromPort,To:ToPort,CIDR:CidrIpv4,PrefixList:PrefixListId,Desc:Description}' \
  --output table
```

One or two tcp/443 egress rules and **no rule with protocol `-1`**. Then confirm ingress is untouched:

```bash
aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,Source:UserIdGroupPairs[0].GroupId}' \
  --output table
echo "usms-alb-sg = $USMS_ALB_SG"
```

One ingress rule, tcp/80 from `$USMS_ALB_SG`, as Lab 5 Step 13 left it.

---

### Step 14 - Write the load balancer's egress rule, whose destination is a security group

A load balancer's only legitimate outbound destination is its targets, whose addresses change on every deployment and scaling event. An egress rule naming `usms-enrolment-sg` stays right permanently: **a group reference is a rule about a role in the architecture; an address is a rule about a moment in time.**

**Part 1 - the document**

```bash
cat > policies/usms-alb-sg-egress.json << EOF
[
  {
    "IpProtocol": "tcp",
    "FromPort": 80,
    "ToPort": 80,
    "UserIdGroupPairs": [
      {
        "GroupId": "${USMS_ENROLMENT_SG}",
        "Description": "HTTP to the enrolment tasks - the ONLY thing this load balancer may initiate"
      }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-alb-sg-egress.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-alb-sg-egress.json
```

**Part 2 - authorise then revoke**

!!! danger "Read before revoking an egress rule"
    **What will be deleted:** the default allow-all egress rule on `usms-alb-sg`.

    **What depends on it:** on real AWS, the load balancer's health checks and its forwarded requests
    - both of which are outbound connections from the load balancer to a target, and both of which the
    replacement rule permits. Nothing else: a load balancer initiates nothing but target traffic.

    **Reversible?** Yes. `policies/usms-egress-allow-all.json` puts it back.

    **Effect on later labs:** none. Lab 06's scaling changes how many targets there are and not what
    the load balancer may reach, because the rule names a group rather than a set of addresses. That
    is the whole point of this step.

```bash
aws ec2 authorize-security-group-egress \
  --group-id "$USMS_ALB_SG" \
  --ip-permissions file://policies/usms-alb-sg-egress.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text

aws ec2 revoke-security-group-egress \
  --group-id "$USMS_ALB_SG" \
  --ip-permissions file://policies/usms-egress-allow-all.json \
  --query 'Return' --output text
```

**Verify**

```bash
aws ec2 describe-security-groups --group-ids "$USMS_ALB_SG" \
  --query 'SecurityGroups[0].{In:IpPermissions[].{Port:FromPort,CIDR:IpRanges[0].CidrIp},Out:IpPermissionsEgress[].{Port:FromPort,ToGroup:UserIdGroupPairs[0].GroupId,CIDR:IpRanges[0].CidrIp}}' \
  --output json

echo "usms-enrolment-sg = $USMS_ENROLMENT_SG"
```

**Expected result**

```json
{
    "In": [ { "Port": 80, "CIDR": "0.0.0.0/0" } ],
    "Out": [ { "Port": 80, "ToGroup": "sg-0aa11bb22cc33dd44", "CIDR": null } ]
}
```

> Example output - your group ID will differ.

The pair reads: anything may open HTTP to this load balancer; it may open HTTP to exactly one thing. `CIDR` null and `ToGroup` populated is the group reference. The audit script cannot catch the reverse (a CIDR rule to `10.0.3.0/24` is not a mechanical finding); some review is mechanical and some is reading.

---

### Step 15 - Write the data tier's egress rule

Lab 2 gave the data tier outbound access for OS updates, then allowed everything. Egress matters most here, because a database is what an attacker wants data *out of*.

**Part 1 - the document**

```bash
cat > policies/usms-db-sg-egress.json << 'EOF'
[
  {
    "IpProtocol": "tcp",
    "FromPort": 443,
    "ToPort": 443,
    "IpRanges": [
      {
        "CidrIp": "0.0.0.0/0",
        "Description": "HTTPS out through usms-nat for operating system updates - the ONLY reason Lab 02 gave this tier outbound access"
      }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-db-sg-egress.json > /dev/null && echo "valid JSON"
```

Quoted heredoc. DNS out, SSH out, database connections, SMTP and HTTP on 80 are now denied. Port 443 to `0.0.0.0/0` still permits an HTTPS POST of the data anywhere; stopping that needs hostname filtering (Network Firewall or a proxy, Exercise 4). Say so in your report.

**Part 2 - authorise then revoke**

!!! danger "Read before revoking an egress rule"
    **What will be deleted:** the default allow-all egress rule on `usms-db-sg`.

    **What depends on it:** on real AWS, `dnf update` on `usms-db-01` - which needs both HTTPS **and**
    DNS. See the warning below, because this is the one egress change in the lab with a genuine
    functional consequence.

    **Reversible?** Yes. `policies/usms-egress-allow-all.json` puts it back.

    **Effect on later labs:** none. Lab 10 does not touch this instance, and the RDS material would
    replace it entirely.

```bash
aws ec2 authorize-security-group-egress \
  --group-id "$USMS_DB_SG" \
  --ip-permissions file://policies/usms-db-sg-egress.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text

aws ec2 revoke-security-group-egress \
  --group-id "$USMS_DB_SG" \
  --ip-permissions file://policies/usms-egress-allow-all.json \
  --query 'Return' --output text
```

!!! warning "What this rule breaks on real AWS, and how you would know"
    Without DNS, `dnf update` cannot resolve its mirror and fails with a name-resolution error. The Amazon resolver is at `10.0.0.2`, inside the VPC, so a complete document would add UDP and TCP 53 to `10.0.0.0/16`. It is left out because Floci provides no resolver. Add it in Exercise 1, with both protocols, and say why UDP comes first.

**Verify**

```bash
for g in "$USMS_ENROLMENT_SG" "$USMS_ALB_SG" "$USMS_DB_SG"; do
  name=$(aws ec2 describe-security-groups --group-ids "$g" \
          --query 'SecurityGroups[0].GroupName' --output text)
  n=$(aws ec2 describe-security-groups --group-ids "$g" \
        --query 'length(IpPermissionsEgress[?IpProtocol==`-1`])' --output text)
  printf '%-22s allow-all egress rules remaining: %s\n' "$name" "$n"
done
```

**Expected result**

```text
usms-enrolment-sg      allow-all egress rules remaining: 0
usms-alb-sg            allow-all egress rules remaining: 0
usms-db-sg             allow-all egress rules remaining: 0
```

Three zeros: Steps 13 to 15 in three lines. Section 8's script repeats the check.

**Checkpoint 8**

```text
Egress, written
 ├── usms-enrolment-sg   tcp/443 -> pl:<s3>, 0.0.0.0/0      image pull, logs, transcripts
 ├── usms-alb-sg         tcp/80  -> sg:usms-enrolment-sg    the only thing it may initiate
 ├── usms-db-sg          tcp/443 -> 0.0.0.0/0               OS updates, and nothing else
 ├── usms-app-sg         still the default          <- Exercise 1
 ├── policies/usms-egress-allow-all.json            the undo, written BEFORE the change
 └── every ingress rule in the VPC                  UNCHANGED
```

---

### Step 16 - Narrow the SSH rule to a bastion group

`usms-app-sg` admits tcp/22 from `10.0.0.0/16`: every address in the VPC, including every Fargate task. Replace it with a rule sourced from `usms-bastion-sg`. No jump host is created; the group names a role in the architecture, correct whether or not a host exists today.

**Part 1 - find or create the group**

```bash
BASTION_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$USMS_VPC_ID" "Name=group-name,Values=usms-bastion-sg" \
  --query 'SecurityGroups[0].GroupId | [0]' --output text 2>/dev/null)

if [ -z "$BASTION_SG" ] || [ "$BASTION_SG" = "None" ]; then
  echo "usms-bastion-sg does not exist - creating it (Lab 02 Exercise 2 was not done)"
  BASTION_SG=$(aws ec2 create-security-group \
    --group-name usms-bastion-sg \
    --description "USMS administrative jump host tier: SSH in from one address, SSH out to the VPC" \
    --vpc-id "$USMS_VPC_ID" \
    --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=usms-bastion-sg},{Key=Project,Value=USMS},{Key=Tier,Value=admin},{Key=Lab,Value=05}]' \
    --query 'GroupId' --output text)

  aws ec2 authorize-security-group-ingress \
    --group-id "$BASTION_SG" \
    --protocol tcp --port 22 --cidr 203.0.113.10/32 \
    --query 'SecurityGroupRules[0].SecurityGroupRuleId' --output text
else
  echo "reusing usms-bastion-sg from Lab 02 Exercise 2"
fi

echo "BASTION_SG = $BASTION_SG"
```

- Idempotent: a lookup with a fallback, so students who did Lab 2 Exercise 2 and those who did not end in the same state.
- The `None` test catches a filter that matched nothing.
- `203.0.113.10/32` is a documentation address (RFC 5737 `TEST-NET-3`).

**Part 2 - the new rule on `usms-app-sg`**

```bash
cat > policies/usms-app-sg-ssh-bastion.json << EOF
[
  {
    "IpProtocol": "tcp",
    "FromPort": 22,
    "ToPort": 22,
    "UserIdGroupPairs": [
      {
        "GroupId": "${BASTION_SG}",
        "Description": "SSH from the USMS jump host tier only - replaces the 10.0.0.0/16 rule from Lab 02 Step 14"
      }
    ]
  }
]
EOF

python3 -m json.tool policies/usms-app-sg-ssh-bastion.json > /dev/null && echo "valid JSON"
grep -c '\$' policies/usms-app-sg-ssh-bastion.json

aws ec2 authorize-security-group-ingress \
  --group-id "$USMS_APP_SG" \
  --ip-permissions file://policies/usms-app-sg-ssh-bastion.json \
  --query 'SecurityGroupRules[].SecurityGroupRuleId' --output text
```

**Part 3 - remove the old rule**

!!! danger "Read before running any revoke command"
    **What will be deleted:** one inbound rule on `usms-app-sg` - tcp/22 from `10.0.0.0/16`, written
    in Lab 02 Step 14. Not the group, not the HTTP or HTTPS rules, not the rule you just added.

    **What depends on it:** on real AWS, any SSH session to `usms-web-01` from inside the VPC that
    does not come from something wearing `usms-bastion-sg`. In this architecture that is nothing,
    because there is no jump host and Floci does not carry SSH.

    **Reversible?** Yes, completely. One `authorize-security-group-ingress --protocol tcp --port 22
    --cidr 10.0.0.0/16` puts it back.

    **Effect on later labs:** none. No verification script in this course asserts the SSH rule - Step
    2's baseline is how you prove that rather than assume it, and Step 18 is where you check.

    Note the order once more: Step 16 part 2 **added** the replacement before this removes the
    original. Same cutover discipline as Lab 05 and as Step 13.

```bash
OLD_SSH_RULE=$(aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$USMS_APP_SG" \
  --query "SecurityGroupRules[?IsEgress==\`false\` && FromPort==\`22\` && CidrIpv4=='10.0.0.0/16'].SecurityGroupRuleId | [0]" \
  --output text)

echo "rule to remove: $OLD_SSH_RULE"

if [ -n "$OLD_SSH_RULE" ] && [ "$OLD_SSH_RULE" != "None" ]; then
  aws ec2 revoke-security-group-ingress \
    --group-id "$USMS_APP_SG" \
    --security-group-rule-ids "$OLD_SSH_RULE" \
    --query 'Return' --output text
else
  echo "no 10.0.0.0/16 SSH rule found - Lab 02 Exercise 2 already removed it"
fi
```

- The filter mixes a boolean and a number in backticks (escaped as `` \` `` inside double quotes) and a string in single quotes.
- `--security-group-rule-ids` removes exactly one rule; restating it with `--ip-permissions` can silently remove nothing and still return `True`.

**Verify**

```bash
aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=$USMS_APP_SG" \
  --query 'SecurityGroupRules[?IsEgress==`false`].{Rule:SecurityGroupRuleId,Port:FromPort,CIDR:CidrIpv4,FromGroup:ReferencedGroupInfo.GroupId,Desc:Description}' \
  --output table

echo "usms-bastion-sg = $BASTION_SG"
```

**Expected result**

```text
------------------------------------------------------------------------------------------
|                            DescribeSecurityGroupRules                                  |
+---------------+-----------+------------+-----------------------+---------------------+
|     CIDR      | FromGroup |    Port    |         Rule          |        Desc         |
+---------------+-----------+------------+-----------------------+---------------------+
|  0.0.0.0/0    |  None     |  80        |  sgr-0aaa111bbb222ccc3|  None               |
|  0.0.0.0/0    |  None     |  443       |  sgr-0ccc333ddd444eee5|  HTTPS from ...     |
|  None         |  sg-0dd...|  22        |  sgr-0eee555fff666aaa7|  SSH from the USMS..|
+---------------+-----------+------------+-----------------------+---------------------+
usms-bastion-sg = sg-0dd44ee55ff66aa77
```

> Example output - your IDs will differ, and the 443 row appears only if you did Lab 02 Step 14's
> "Your turn".

The port 22 row has `CIDR` `None` and `FromGroup` set. Both populated means two SSH rules; `CIDR` still `10.0.0.0/16` means Part 3 removed nothing. What changed: *SSH to the web tier is no longer reachable from anything outside the administrative tier, including a compromised enrolment task* (the tasks' subnets sit inside `10.0.0.0/16`).

**Checkpoint 9**

```text
usms-app-sg
 ├── in  tcp/80   from 0.0.0.0/0        unchanged - Exercise 4 argues about it
 ├── in  tcp/443  from 0.0.0.0/0        unchanged
 ├── in  tcp/22   from sg:usms-bastion-sg   <- NARROWED
 └── the 10.0.0.0/16 SSH rule           GONE, and with it a path from every Fargate task
```

---

### Step 17 - Compute the reachability matrix, and prove two negatives

*Who can reach what* is a property of relationships between objects, not of any one object. Build the tool that answers it, then prove the two claims the architecture rests on.

A negative cannot be tested; you enumerate the controls that would each have to fail. For `usms-db-01`:

```text
1. It has NO public IPv4 address.
   Even with a perfect route and an open group, nothing on the internet has an address to send to.

2. Its subnet does not auto-assign public addresses.
   So a replacement instance launched into it would not acquire one by accident.

3. Its route table has no route to an internet gateway.
   Return traffic could not leave even if a request arrived. Lab 02 Step 13 proved this one.

4. usms-db-sg admits tcp/5432 from ONE security group and nothing else.
   Even from inside the VPC, only things wearing usms-app-sg may connect.

   ... and a fifth, on the subnet itself: usms-private-nacl, whose implicit rule 32767
   denies everything its four explicit rules do not allow.
```

Remove any one and the claim still holds. That is defence in depth stated precisely: **the claim survives the failure of any single control.** See [defence in depth](../unit8/topic2.md#defence-in-depth-for-the-network-layers-from-edge-to-workload).

**Part 1 - build the matrix tool**

````bash
cat > scripts/utilities/usms-reachability-matrix.sh << 'EOF'
#!/usr/bin/env bash
# USMS reachability matrix.
#
# For every security group in the VPC, computes which OTHER groups may open a
# connection to it, on what, and whether the internet may. The verdict is derived
# ONLY from rules -- never from a group's name, its tags, or its description.
#
# Read-only. Always exits 0: this is a report, not a test.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1090
source "$REPO_ROOT/configs/course.env" 2>/dev/null || true
# shellcheck disable=SC1090
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true

VPC="${1:-${USMS_VPC_ID:-}}"
[ -n "$VPC" ] && [ "$VPC" != "none" ] || { echo "usage: $0 [vpc-id]" >&2; exit 2; }

aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" --output json \
  > /tmp/usms-matrix-sg-$$.json
aws ec2 describe-instances --filters "Name=vpc-id,Values=$VPC" --output json \
  > /tmp/usms-matrix-ec2-$$.json

python3 - "/tmp/usms-matrix-sg-$$.json" "/tmp/usms-matrix-ec2-$$.json" << 'PY'
import json, sys

groups = json.load(open(sys.argv[1]))["SecurityGroups"]
res    = json.load(open(sys.argv[2]))["Reservations"]

name = {g["GroupId"]: g.get("GroupName", g["GroupId"]) for g in groups}

def port_str(p):
    lo, hi = p.get("FromPort"), p.get("ToPort")
    if lo is None:
        return "all"
    return str(lo) if lo == hi else f"{lo}-{hi}"

def proto_str(p):
    v = p.get("IpProtocol", "-1")
    return "all" if v == "-1" else v

print("== USMS reachability matrix ==")
print()
print("WHO MAY OPEN A CONNECTION TO WHAT  (ingress, computed from rules only)")
print()

lonely = []
for g in sorted(groups, key=lambda x: x.get("GroupName", "")):
    gid, gname = g["GroupId"], g.get("GroupName", g["GroupId"])
    perms = g.get("IpPermissions", [])
    if not perms:
        print(f"  -> {gname}")
        print("       (nothing. no ingress rule exists)")
        print()
        continue

    controls = 0
    print(f"  -> {gname}")
    for p in perms:
        for r in p.get("UserIdGroupPairs", []):
            src = name.get(r.get("GroupId"), r.get("GroupId"))
            print(f"       {proto_str(p)}/{port_str(p):<9} <- group {src}")
            controls += 1
        for r in p.get("IpRanges", []):
            c = r.get("CidrIp")
            flag = "   <-- THE INTERNET" if c == "0.0.0.0/0" else ""
            print(f"       {proto_str(p)}/{port_str(p):<9} <- cidr  {c}{flag}")
            controls += 1
        for r in p.get("PrefixListIds", []):
            print(f"       {proto_str(p)}/{port_str(p):<9} <- prefix list {r.get('PrefixListId')}")
            controls += 1
    if controls == 1:
        lonely.append(gname)
    print()

print("WHAT EACH GROUP MAY INITIATE  (egress)")
print()
for g in sorted(groups, key=lambda x: x.get("GroupName", "")):
    gname = g.get("GroupName", g["GroupId"])
    egr = g.get("IpPermissionsEgress", [])
    if not egr:
        print(f"  {gname:<22} nothing")
        continue
    parts = []
    for p in egr:
        dests = [name.get(r.get("GroupId"), r.get("GroupId")) for r in p.get("UserIdGroupPairs", [])]
        dests += [r.get("CidrIp") for r in p.get("IpRanges", [])]
        dests += [r.get("PrefixListId") for r in p.get("PrefixListIds", [])]
        parts.append(f"{proto_str(p)}/{port_str(p)} -> {', '.join(d for d in dests if d)}")
    print(f"  {gname:<22} {' ; '.join(parts)}")

print()
print("INSTANCES, AND WHETHER THE INTERNET HAS AN ADDRESS TO SEND TO")
print()
for r in res:
    for i in r.get("Instances", []):
        if i.get("State", {}).get("Name") == "terminated":
            continue
        tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
        pub = i.get("PublicIpAddress")
        sgs = ",".join(name.get(s["GroupId"], s["GroupId"]) for s in i.get("SecurityGroups", []))
        print(f"  {tags.get('Name', i['InstanceId']):<16} "
              f"private={i.get('PrivateIpAddress','-'):<12} "
              f"public={pub or 'NONE':<16} groups={sgs}")

print()
if lonely:
    print("SINGLE POINT OF CONTROL - these groups are protected by exactly ONE ingress rule:")
    for g in lonely:
        print(f"    {g}")
    print("    One mistake in one rule is the whole of the protection. Say so in your report.")
else:
    print("no group is protected by exactly one ingress rule")
PY

rm -f /tmp/usms-matrix-sg-$$.json /tmp/usms-matrix-ec2-$$.json
EOF

chmod +x scripts/utilities/usms-reachability-matrix.sh
bash -n scripts/utilities/usms-reachability-matrix.sh && echo "syntax OK"
./scripts/utilities/usms-reachability-matrix.sh | tee outputs/lab-09-reachability.txt
````

Verdicts come only from `IpPermissions` and `IpPermissionsEgress`, never from names, tags or descriptions. The `lonely` list names groups protected by exactly one ingress rule.

**Expected result**

```text
syntax OK
== USMS reachability matrix ==

WHO MAY OPEN A CONNECTION TO WHAT  (ingress, computed from rules only)

  -> default
       all/all       <- group default

  -> usms-alb-sg
       tcp/80        <- cidr  0.0.0.0/0   <-- THE INTERNET

  -> usms-app-sg
       tcp/80        <- cidr  0.0.0.0/0   <-- THE INTERNET
       tcp/443       <- cidr  0.0.0.0/0   <-- THE INTERNET
       tcp/22        <- group usms-bastion-sg

  -> usms-bastion-sg
       tcp/22        <- cidr  203.0.113.10/32

  -> usms-db-sg
       tcp/5432      <- group usms-app-sg

  -> usms-enrolment-sg
       tcp/80        <- group usms-alb-sg

WHAT EACH GROUP MAY INITIATE  (egress)

  default                all/all -> 0.0.0.0/0
  usms-alb-sg            tcp/80 -> usms-enrolment-sg
  usms-app-sg            all/all -> 0.0.0.0/0
  usms-bastion-sg        all/all -> 0.0.0.0/0
  usms-db-sg             tcp/443 -> 0.0.0.0/0
  usms-enrolment-sg      tcp/443 -> pl-63a5400a ; tcp/443 -> 0.0.0.0/0

INSTANCES, AND WHETHER THE INTERNET HAS AN ADDRESS TO SEND TO

  usms-web-01      private=10.0.1.87    public=52.9.144.17     groups=usms-app-sg
  usms-db-01       private=10.0.3.42    public=NONE            groups=usms-db-sg

SINGLE POINT OF CONTROL - these groups are protected by exactly ONE ingress rule:
    usms-alb-sg
    usms-bastion-sg
    usms-db-sg
    usms-enrolment-sg
    One mistake in one rule is the whole of the protection. Say so in your report.
```

> Example output - your IDs, addresses and prefix list will differ.

1. **Two groups admit the internet**, `usms-alb-sg` (argued in Lab 5) and `usms-app-sg` (never argued; Exercise 4).
2. **`usms-db-sg` and `usms-enrolment-sg` admit only a group.**
3. **`usms-app-sg` and `usms-bastion-sg` keep default egress.** Exercise 1 handles the first; a jump host's job is to initiate SSH.
4. **`usms-enrolment-sg` is a single point of control.** The tasks' private subnet and lack of public address are further controls, but this report models security groups only. **A tool that models one axis understates the defences on the other.**

**Part 2 - prove the negative on the data tier, four controls at a time**

```bash
{
  echo "== Claim: usms-db-01 is not reachable from the internet =="
  echo "   Each control below would have to fail INDEPENDENTLY for the claim to be false."
  echo

  echo "-- control 1: no public address --"
  aws ec2 describe-instances --instance-ids "$USMS_DB_INSTANCE" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text

  echo "-- control 2: its subnet does not auto-assign one --"
  aws ec2 describe-subnets --subnet-ids "$USMS_PRIVATE_SUBNET_A" \
    --query 'Subnets[0].MapPublicIpOnLaunch' --output text

  echo "-- control 3: its route table has no internet gateway route --"
  aws ec2 describe-route-tables \
    --filters "Name=association.subnet-id,Values=$USMS_PRIVATE_SUBNET_A" \
    --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].[GatewayId,NatGatewayId]' \
    --output text

  echo "-- control 4: its security group admits ONE group, no CIDR --"
  aws ec2 describe-security-groups --group-ids "$USMS_DB_SG" \
    --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,Group:UserIdGroupPairs[0].GroupId,CIDR:IpRanges[0].CidrIp}' \
    --output text

  echo "-- control 5: the subnet's network ACL is not the default one --"
  aws ec2 describe-network-acls \
    --filters "Name=association.subnet-id,Values=$USMS_PRIVATE_SUBNET_A" \
    --query 'NetworkAcls[0].{Acl:NetworkAclId,IsDefault:IsDefault}' --output text
} | tee outputs/lab-09-negative-proof.txt
```

**Expected result**

```text
== Claim: usms-db-01 is not reachable from the internet ==
   Each control below would have to fail INDEPENDENTLY for the claim to be false.

-- control 1: no public address --
None
-- control 2: its subnet does not auto-assign one --
False
-- control 3: its route table has no internet gateway route --
None    nat-0abcdef1234567890
-- control 4: its security group admits ONE group, no CIDR --
5432    sg-0123456789abcdef0     None
-- control 5: the subnet's network ACL is not the default one --
acl-0999888777666555a   False
```

> Example output - your IDs will differ.

| Line | Correct answer | What a wrong answer would mean |
| --- | --- | --- |
| control 1 | `None` | The instance has a public address. Control 3 still saves you |
| control 2 | `False` | A replacement instance would get an address by accident |
| control 3 | `None` then a `nat-` id | An `igw-` id here would make the subnet public. This is the load-bearing one |
| control 4 | a port, a `sg-` id, and `None` for the CIDR | A CIDR here means an address-based rule |
| control 5 | an `acl-` id and `False` | `True` means the custom NACL is not associated |

Write in `notes/lab-09-notes.md`, one sentence each, what would still stop an attacker if control 3 failed, and if control 4 failed (Review Question 5).

**Checkpoint 10**

```text
Reachability computed, negatives proven
 ├── scripts/utilities/usms-reachability-matrix.sh   verdicts from rules, never from names
 ├── outputs/lab-09-reachability.txt                 who may reach what, in one page
 ├── outputs/lab-09-negative-proof.txt               five controls on usms-db-01
 ├── finding: usms-app-sg is a SECOND internet-facing entry point   -> Exercise 4
 └── finding: usms-enrolment-sg is a single point of control        -> stated, not fixed
```

---

### Step 18 - Prove the whole posture survives a restart, and that nothing else broke

Two proofs: the controls persist across a stop and start (a vanished control is worse than none, because the audit recorded it), and the five earlier verification scripts are unchanged since Step 2.

**Part 1 - record the truth**

```bash
{
  aws iam get-role --role-name "$USMS_ECS_TASK_ROLE" \
    --query 'length(Role.AssumeRolePolicyDocument.Statement[0].Condition)' --output text
  aws iam get-role --role-name usms-deploy-role \
    --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text
  aws iam get-role --role-name usms-transcripts-reader-role \
    --query 'Role.RoleName' --output text
  aws iam list-attached-role-policies --role-name usms-transcripts-reader-role \
    --query 'AttachedPolicies[0].PolicyName' --output text
  aws iam list-access-keys --user-name "$USMS_DEV_USER" \
    --query 'length(AccessKeyMetadata)' --output text
  for g in "$USMS_ALB_SG" "$USMS_ENROLMENT_SG" "$USMS_DB_SG"; do
    aws ec2 describe-security-groups --group-ids "$g" \
      --query 'length(IpPermissionsEgress[?IpProtocol==`-1`])' --output text
  done
  aws ec2 describe-security-groups --group-ids "$USMS_APP_SG" \
    --query 'length(IpPermissions[?FromPort==`22`].IpRanges[])' --output text
  aws ec2 describe-instances --instance-ids "$USMS_WEB_INSTANCE" \
    --query 'Reservations[0].Instances[0].MetadataOptions.HttpTokens' --output text
} > outputs/lab-09-pre-restart.txt

cat outputs/lab-09-pre-restart.txt
```

Nine facts across three services. `length(...Condition)` counts condition keys (`2` intact, `0` gone), which diffs more reliably than a JSON object. The SSH count must be `0`: a negative assertion.

**Part 2 - perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env
source configs/lab-03.env
source configs/lab-04.env
source configs/lab-05.env
```

`floci-down.sh` is `docker compose stop`, which keeps state. It is not `docker compose down -v`.

**Part 3 - re-derive every identifier and read it back**

```bash
USMS_ALB_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-alb-sg" --query 'SecurityGroups[0].GroupId' --output text)
USMS_ENROLMENT_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=usms-enrolment-sg" --query 'SecurityGroups[0].GroupId' --output text)
USMS_DB_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-db-sg" --query 'SecurityGroups[0].GroupId' --output text)
USMS_APP_SG=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=usms-app-sg" --query 'SecurityGroups[0].GroupId' --output text)
USMS_WEB_INSTANCE=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=usms-web-01" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
USMS_ECS_TASK_ROLE="${USMS_ECS_TASK_ROLE:-usms-ecs-task-role}"

echo "re-derived:"
printf '  %s\n' "$USMS_ALB_SG" "$USMS_ENROLMENT_SG" "$USMS_DB_SG" "$USMS_APP_SG" "$USMS_WEB_INSTANCE"

{
  aws iam get-role --role-name "$USMS_ECS_TASK_ROLE" \
    --query 'length(Role.AssumeRolePolicyDocument.Statement[0].Condition)' --output text
  aws iam get-role --role-name usms-deploy-role \
    --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text
  aws iam get-role --role-name usms-transcripts-reader-role \
    --query 'Role.RoleName' --output text
  aws iam list-attached-role-policies --role-name usms-transcripts-reader-role \
    --query 'AttachedPolicies[0].PolicyName' --output text
  aws iam list-access-keys --user-name "$USMS_DEV_USER" \
    --query 'length(AccessKeyMetadata)' --output text
  for g in "$USMS_ALB_SG" "$USMS_ENROLMENT_SG" "$USMS_DB_SG"; do
    aws ec2 describe-security-groups --group-ids "$g" \
      --query 'length(IpPermissionsEgress[?IpProtocol==`-1`])' --output text
  done
  aws ec2 describe-security-groups --group-ids "$USMS_APP_SG" \
    --query 'length(IpPermissions[?FromPort==`22`].IpRanges[])' --output text
  aws ec2 describe-instances --instance-ids "$USMS_WEB_INSTANCE" \
    --query 'Reservations[0].Instances[0].MetadataOptions.HttpTokens' --output text
} > outputs/lab-09-post-restart.txt

diff outputs/lab-09-pre-restart.txt outputs/lab-09-post-restart.txt \
  && echo "PERSISTENCE PROVEN: the trust condition, the permissions boundary, the read-only role and its policy, the single access key, three written egress rules, the absence of a CIDR SSH source, and the IMDSv2 requirement are all unchanged" \
  || echo "PERSISTENCE FAILED: read the diff above, then run ./scripts/utilities/floci-storage-check.sh"
```

Every identifier is re-derived from the API, not reused from a variable, or the test would only prove that Bash remembers strings (Lab 1 Step 14). `usms-enrolment-sg` is found by group name because Lab 4 may not have tagged it.

**Expected result**

```text
re-derived:
  sg-0bb22cc33dd44ee55
  sg-0aa11bb22cc33dd44
  sg-0fedcba9876543210
  sg-0123456789abcdef0
  i-0123456789abcdef0
PERSISTENCE PROVEN: the trust condition, the permissions boundary, the read-only role and its policy, the single access key, three written egress rules, the absence of a CIDR SSH source, and the IMDSv2 requirement are all unchanged
```

If you see `PERSISTENCE FAILED`, read the `diff` first; it names which of the nine facts did not survive.

**Part 4 - prove you broke nothing**

```bash
{
  echo "== after the security review $(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))') =="
  for s in 02 03 04 05 06; do
    printf '%-10s ' "lab-$s"
    ./scripts/utilities/verify-lab-$s.sh 2>/dev/null | tail -1
  done
} | tee outputs/lab-09-post-verify.txt

echo
echo "== what changed =="
diff <(grep -v '^==' outputs/lab-09-pre-verify.txt) \
     <(grep -v '^==' outputs/lab-09-post-verify.txt) \
  && echo "NOTHING BROKE: all five verification scripts report exactly what they reported before this lab" \
  || echo "SOMETHING CHANGED - read the diff above and find out which check and why"
```

`diff <(...) <(...)` compares two pipelines without temp files; `grep -v '^=='` drops the timestamps.

**Expected result**

```text
== after the security review 2026-09-06T08:22:41Z ==
lab-02     PASS=33  FAIL=0
lab-03     PASS=36  FAIL=0
lab-04    PASS=48  FAIL=1
lab-05    PASS=49  FAIL=0
lab-06    PASS=42  FAIL=0

== what changed ==
NOTHING BROKE: all five verification scripts report exactly what they reported before this lab
```

> Example output - your counts are whatever Step 2 recorded.

`NOTHING BROKE` means no property an earlier lab asserted has changed; it does not say this lab's changes are correct (Section 8 does). If something changed, document it, update the check, or (rarely) delete it, as Lab 5 Step 13 set out.

**Checkpoint 11**

```text
Persistence and regression, both proven
 ├── nine controls re-read after a stop/start, every identifier re-derived from the API
 ├── outputs/lab-09-pre-restart.txt  vs  post-restart.txt      identical
 ├── five earlier verification scripts re-run, summary lines identical to Step 2's
 └── outputs/lab-09-pre-verify.txt   vs  post-verify.txt       identical
```

---

### Step 19 - Write `configs/lab-09.env`

Record names and ARNs **by lookup**, so a populated value is evidence the resource exists.

```bash
cat > configs/lab-09.env << EOF
# Lab 09 - security review outputs
# Generated on $(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')
# Contains names, IDs and ARNs only. NO SECRETS. Safe to commit.
#
# DELIBERATELY ABSENT: the access key ID for usms-dev-01. An access key ID is not a
# secret, but recording one in a committed file is how a habit becomes a leak. The
# rotation DATE is here instead; the ID lives only in outputs/, which is git-ignored.
#
# Sourced alongside lab-01/02/03/04/05/06.

export USMS_POLICY_S3_RO=USMSStudentDataReadOnly
export USMS_POLICY_S3_RO_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSStudentDataReadOnly'].Arn | [0]" --output text)
export USMS_POLICY_DEPLOY=USMSDeployBase
export USMS_POLICY_DEPLOY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSDeployBase'].Arn | [0]" --output text)
export USMS_POLICY_BOUNDARY=USMSPermissionsBoundary
export USMS_POLICY_BOUNDARY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='USMSPermissionsBoundary'].Arn | [0]" --output text)

export USMS_ROLE_TRANSCRIPTS_READER=usms-transcripts-reader-role
export USMS_ROLE_TRANSCRIPTS_READER_ARN=$(aws iam get-role \
  --role-name usms-transcripts-reader-role --query 'Role.Arn' --output text)
export USMS_ROLE_DEPLOY=usms-deploy-role
export USMS_ROLE_DEPLOY_ARN=$(aws iam get-role \
  --role-name usms-deploy-role --query 'Role.Arn' --output text)

export USMS_BASTION_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=usms-bastion-sg" \
  --query 'SecurityGroups[0].GroupId' --output text)

export USMS_S3_PREFIX_LIST=${S3_PREFIX_LIST:-none}

export USMS_IMDS_TOKENS=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=usms-web-01" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[0].Instances[0].MetadataOptions.HttpTokens' --output text)

export USMS_DEV_KEY_ROTATED=$(aws iam list-access-keys --user-name usms-dev-01 \
  --query 'AccessKeyMetadata[0].CreateDate' --output text)

export USMS_EGRESS_ALLOW_ALL_REMAINING=$(
  total=0
  for g in usms-alb-sg usms-enrolment-sg usms-db-sg; do
    id=\$(aws ec2 describe-security-groups --filters "Name=group-name,Values=\$g" \
           --query 'SecurityGroups[0].GroupId' --output text)
    n=\$(aws ec2 describe-security-groups --group-ids "\$id" \
           --query 'length(IpPermissionsEgress[?IpProtocol==\`-1\`])' --output text 2>/dev/null || echo 0)
    total=\$((total + n))
  done
  echo "\$total")

export USMS_SEC_REVIEW_DATE=$(python3 -c 'import datetime;print(datetime.date.today().isoformat())')
EOF

grep -n 'export .*=$\|=None$' configs/lab-09.env || echo "all values populated"
```

- **Unquoted heredoc**, so every `$(...)` runs now. Quoted, `source configs/lab-09.env` would re-run a dozen API calls in every terminal.
- `USMS_EGRESS_ALLOW_ALL_REMAINING` is a small program inside an unquoted heredoc, so its own `$` signs and backticks are escaped (`\$g`, `\$id`, `\$total`). Without them `$g` would expand to nothing as the file is written. If the escaping fights you, compute the value first:

```bash
# The readable alternative, if the escaping fights you:
REMAINING=$(for g in usms-alb-sg usms-enrolment-sg usms-db-sg; do ... done)
# then, inside the heredoc:
#   export USMS_EGRESS_ALLOW_ALL_REMAINING=$REMAINING
```

- `USMS_IMDS_TOKENS` and `USMS_EGRESS_ALLOW_ALL_REMAINING` are read back from the API, not hard-coded; Section 8 asserts both.

**Verify**

```bash
source configs/lab-09.env

printf '%-36s %s\n' \
  "read-only policy"        "$USMS_POLICY_S3_RO_ARN" \
  "deploy policy"           "$USMS_POLICY_DEPLOY_ARN" \
  "permissions boundary"    "$USMS_POLICY_BOUNDARY_ARN" \
  "transcripts reader role" "$USMS_ROLE_TRANSCRIPTS_READER_ARN" \
  "deploy role"             "$USMS_ROLE_DEPLOY_ARN" \
  "bastion security group"  "$USMS_BASTION_SG" \
  "s3 prefix list"          "$USMS_S3_PREFIX_LIST" \
  "imds tokens"             "$USMS_IMDS_TOKENS" \
  "dev key created"         "$USMS_DEV_KEY_ROTATED" \
  "allow-all egress left"   "$USMS_EGRESS_ALLOW_ALL_REMAINING" \
  "review date"             "$USMS_SEC_REVIEW_DATE"

grep -c '^export' configs/lab-09.env
```

**Expected result**

```text
read-only policy                     arn:aws:iam::000000000000:policy/USMSStudentDataReadOnly
deploy policy                        arn:aws:iam::000000000000:policy/USMSDeployBase
permissions boundary                 arn:aws:iam::000000000000:policy/USMSPermissionsBoundary
transcripts reader role              arn:aws:iam::000000000000:role/usms-transcripts-reader-role
deploy role                          arn:aws:iam::000000000000:role/usms-deploy-role
bastion security group               sg-0dd44ee55ff66aa77
s3 prefix list                       pl-63a5400a
imds tokens                          required
dev key created                      2026-09-06T04:31:07+00:00
allow-all egress left                0
review date                          2026-09-06
16
```

> Example output - your ARNs, IDs and dates will differ.

`all values populated`, eleven non-empty lines and **16** exports. `imds tokens` must be `required` (or honestly `optional` if Step 11 did not take); `allow-all egress left` must be `0`; `s3 prefix list` may be `none` (Step 13 fallback) but no other non-`pl-` value.

---

### Step 20 - Commit

This lab handled two secrets, so there is more to check.

**Part 1 - look before you add**

```bash
git status --short

git check-ignore -v outputs/usms-dev-01-access-key-new.json
git check-ignore -v outputs/lab-09-identity-inventory.json
git ls-files outputs/

echo
echo "== no policy document may contain an unexpanded variable =="
grep -l '\$' policies/*.json || echo "no unexpanded variables in any policy document"
```

Before typing anything else:

- Nothing under `outputs/` in `git status --short`, especially the access key file. No root `.env`.
- `configs/lab-09.env` **does** appear (names and ARNs only).
- `git check-ignore -v` names the rule for **both** output files. Silence means not ignored: fix `.gitignore` first.
- `git ls-files outputs/` lists only `outputs/.gitkeep`.
- The last block prints `no unexpanded variables in any policy document`. A named file used a quoted heredoc where an unquoted one was needed.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/usms-dev-01-access-key-new.json
.gitignore:7:outputs/*	outputs/lab-09-identity-inventory.json
outputs/.gitkeep

== no policy document may contain an unexpanded variable ==
no unexpanded variables in any policy document
```

> Example output - your line numbers may differ.

**Part 2 - commit**

```bash
git add labs/lab-09-security/ \
        configs/lab-09.env \
        policies/usms-student-data-ro-policy.json \
        policies/usms-deploy-policy.json \
        policies/usms-permissions-boundary.json \
        policies/trust-ecs-tasks-scoped.json \
        policies/trust-deploy.json \
        policies/usms-alb-sg-egress.json \
        policies/usms-enrolment-sg-egress.json \
        policies/usms-db-sg-egress.json \
        policies/usms-egress-allow-all.json \
        policies/usms-app-sg-ssh-bastion.json \
        scripts/utilities/usms-iam-audit.sh \
        scripts/utilities/usms-sg-audit.sh \
        scripts/utilities/usms-reachability-matrix.sh \
        scripts/utilities/verify-lab-09.sh \
        scripts/cleanup/lab-09-cleanup.sh

git status --short

git commit -m "Lab 09: security review - scoped trust policies, a permissions boundary, a scoped iam:PassRole, key rotation, IMDSv2, and written egress on three security groups"

git log --oneline -7
```

Name paths explicitly, never `git add -A`, which stages whatever is in the tree, un-ignored secrets included. The last two script paths exist only after Section 8; if you commit first, drop them and add them in a second commit.

**Expected result**

```text
[main 9d41ab7] Lab 09: security review - scoped trust policies, a permissions boundary, a scoped iam:PassRole, key rotation, IMDSv2, and written egress on three security groups
 16 files changed, 486 insertions(+)
```

> Example output - your hash and counts will differ.

**Checkpoint 12**

```text
Lab 09 recorded
 ├── configs/lab-09.env        committed, 16 exports, fully populated, NO key ID
 ├── policies/                 ten new documents: the complete USMS security posture
 ├── scripts/utilities/        three audit tools plus the verification script
 ├── outputs/                  nothing staged; check-ignore named the rule twice
 └── git log shows Labs 01 through 05
```

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-09.sh`

Beyond existence, it asserts: `USMSStudentDataReadOnly` does **not** allow `s3:PutObject`; the task role has a `Condition` and still trusts `ecs-tasks.amazonaws.com`; `USMSDeployBase`'s `iam:PassRole` has no `Resource "*"`; the boundary has zero attachments; `usms-dev-01` has exactly one key; three groups have zero allow-all egress rules; `usms-app-sg` has no CIDR source on port 22; and no `policies/` document contains an unexpanded variable. The environment block comes first, as always.

{% raw %}```bash
cat > scripts/utilities/verify-lab-09.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 09 control exists and is configured correctly.
# Read-only: this script inspects and changes nothing. Safe to run at any time.
# Exit 0 if every check passes, 1 otherwise.
#
# EXPECTED: PASS=50  FAIL=0
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env"  2>/dev/null || true
source "$REPO_ROOT/configs/lab-04.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-05.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-09.env"  2>/dev/null || true

# Defaults so that set -u cannot abort the script before it has told you anything.
: "${USMS_ACCOUNT_ID:=000000000000}"
: "${USMS_VPC_ID:=none}"
: "${USMS_APP_SG:=none}"
: "${USMS_DB_SG:=none}"
: "${USMS_ENROLMENT_SG:=none}"
: "${USMS_ALB_SG:=none}"
: "${USMS_BASTION_SG:=none}"
: "${USMS_PRIVATE_SUBNET_A:=none}"
: "${USMS_PRIVATE_RT:=none}"
: "${USMS_DEV_USER:=usms-dev-01}"
: "${USMS_INSTANCE_PROFILE:=usms-ec2-app-profile}"
: "${USMS_ECS_CLUSTER:=usms-ecs-cluster}"
: "${USMS_ENROLMENT_SERVICE:=usms-enrolment-svc}"
: "${USMS_ECS_TASK_ROLE:=usms-ecs-task-role}"
: "${USMS_WEB_INSTANCE:=none}"
: "${USMS_DB_INSTANCE:=none}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# One policy document, by policy name, at its DEFAULT version.
poldoc() {
  arn=$(aws iam list-policies --scope Local \
          --query "Policies[?PolicyName=='$1'].Arn | [0]" --output text 2>/dev/null)
  [ -n "$arn" ] && [ "$arn" != "None" ] || return 1
  ver=$(aws iam get-policy --policy-arn "$arn" \
          --query 'Policy.DefaultVersionId' --output text 2>/dev/null)
  aws iam get-policy-version --policy-arn "$arn" --version-id "$ver" \
    --query 'PolicyVersion.Document' --output json 2>/dev/null
}

# Egress rules on a group that are the AWS default allow-all shape.
allowall() {
  aws ec2 describe-security-groups --group-ids "$1" \
    --query 'length(IpPermissionsEgress[?IpProtocol==`-1`])' --output text 2>/dev/null
}

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Labs 01 to 06 dependencies still present =="
check "usms-vpc exists" "aws ec2 describe-vpcs --vpc-ids $USMS_VPC_ID"
check "$USMS_ECS_TASK_ROLE exists" "aws iam get-role --role-name $USMS_ECS_TASK_ROLE"
check "$USMS_INSTANCE_PROFILE exists" \
  "aws iam get-instance-profile --instance-profile-name $USMS_INSTANCE_PROFILE"
check "$USMS_ENROLMENT_SERVICE is ACTIVE" \
  "test \"\$(aws ecs describe-services --cluster $USMS_ECS_CLUSTER --services $USMS_ENROLMENT_SERVICE --query 'services[0].status' --output text)\" = ACTIVE"
check "USMSStudentDataReadWrite is still on TWO roles (Lab 10 needs both)" \
  "test \"\$(aws iam list-entities-for-policy --policy-arn arn:aws:iam::$USMS_ACCOUNT_ID:policy/USMSStudentDataReadWrite --query 'length(PolicyRoles)' --output text)\" -ge 2"

echo "== Lab 09 identity: the read-only split =="
check "USMSStudentDataReadOnly exists" \
  "aws iam list-policies --scope Local --query \"Policies[?PolicyName=='USMSStudentDataReadOnly'].Arn | [0]\" --output text | grep -q '^arn:'"
check "it ALLOWS s3:GetObject" \
  "poldoc USMSStudentDataReadOnly | grep -q 's3:GetObject'"
check "it does NOT allow s3:PutObject" \
  "! poldoc USMSStudentDataReadOnly | python3 -c \"import json,sys;d=json.load(sys.stdin);sts=d['Statement'] if isinstance(d['Statement'],list) else [d['Statement']];a=[x for s in sts if s['Effect']=='Allow' for x in (s['Action'] if isinstance(s['Action'],list) else [s['Action']])];sys.exit(0 if 's3:PutObject' in a else 1)\""
check "it explicitly DENIES s3:PutObject" \
  "poldoc USMSStudentDataReadOnly | python3 -c \"import json,sys;d=json.load(sys.stdin);sts=d['Statement'] if isinstance(d['Statement'],list) else [d['Statement']];a=[x for s in sts if s['Effect']=='Deny' for x in (s['Action'] if isinstance(s['Action'],list) else [s['Action']])];sys.exit(0 if 's3:PutObject' in a else 1)\""
check "usms-transcripts-reader-role exists" \
  "aws iam get-role --role-name usms-transcripts-reader-role"
check "it carries USMSStudentDataReadOnly" \
  "aws iam list-attached-role-policies --role-name usms-transcripts-reader-role --query 'AttachedPolicies[].PolicyName' --output text | grep -q USMSStudentDataReadOnly"

echo "== Lab 09 identity: the confused-deputy fix =="
check "$USMS_ECS_TASK_ROLE trust policy has a Condition" \
  "test \"\$(aws iam get-role --role-name $USMS_ECS_TASK_ROLE --query 'length(Role.AssumeRolePolicyDocument.Statement[0].Condition)' --output text)\" -ge 1"
check "its principal is STILL ecs-tasks.amazonaws.com" \
  "aws iam get-role --role-name $USMS_ECS_TASK_ROLE --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text | grep -q 'ecs-tasks.amazonaws.com'"
check "the condition pins aws:SourceAccount to this account" \
  "aws iam get-role --role-name $USMS_ECS_TASK_ROLE --query 'Role.AssumeRolePolicyDocument' --output json | grep -q '$USMS_ACCOUNT_ID'"

echo "== Lab 09 identity: PassRole and the boundary =="
check "USMSDeployBase exists" \
  "aws iam list-policies --scope Local --query \"Policies[?PolicyName=='USMSDeployBase'].Arn | [0]\" --output text | grep -q '^arn:'"
check "its iam:PassRole names role ARNs, not Resource \"*\"" \
  "poldoc USMSDeployBase | python3 -c \"import json,sys;d=json.load(sys.stdin);sts=d['Statement'];bad=[s for s in sts if s['Effect']=='Allow' and 'iam:PassRole' in (s['Action'] if isinstance(s['Action'],list) else [s['Action']]) and '*' in (s['Resource'] if isinstance(s['Resource'],list) else [s['Resource']])];sys.exit(1 if bad else 0)\""
check "its iam:PassRole carries an iam:PassedToService condition" \
  "poldoc USMSDeployBase | grep -q 'iam:PassedToService'"
check "USMSPermissionsBoundary exists" \
  "aws iam list-policies --scope Local --query \"Policies[?PolicyName=='USMSPermissionsBoundary'].Arn | [0]\" --output text | grep -q '^arn:'"
check "the boundary is attached to NOTHING as an ordinary policy" \
  "test \"\$(aws iam list-policies --scope Local --query \\\"Policies[?PolicyName=='USMSPermissionsBoundary'].AttachmentCount | [0]\\\" --output text)\" = 0"
check "usms-deploy-role exists" "aws iam get-role --role-name usms-deploy-role"
check "usms-deploy-role HAS a permissions boundary" \
  "aws iam get-role --role-name usms-deploy-role --query 'Role.PermissionsBoundary.PermissionsBoundaryArn' --output text | grep -q 'USMSPermissionsBoundary'"
check "usms-deploy-role trusts a USER, not a service" \
  "aws iam get-role --role-name usms-deploy-role --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.AWS' --output text | grep -q ':user/'"

echo "== Lab 09 credentials and metadata =="
check "$USMS_DEV_USER has EXACTLY ONE access key" \
  "test \"\$(aws iam list-access-keys --user-name $USMS_DEV_USER --query 'length(AccessKeyMetadata)' --output text)\" = 1"
check "that key is Active" \
  "test \"\$(aws iam list-access-keys --user-name $USMS_DEV_USER --query 'AccessKeyMetadata[0].Status' --output text)\" = Active"
check "usms-web-01 requires IMDSv2" \
  "test \"\$(aws ec2 describe-instances --instance-ids $USMS_WEB_INSTANCE --query 'Reservations[0].Instances[0].MetadataOptions.HttpTokens' --output text)\" = required"

echo "== Lab 09 network: ingress unchanged =="
check "usms-alb-sg still admits tcp/80 from 0.0.0.0/0" \
  "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG --query 'SecurityGroups[0].IpPermissions[?FromPort==\`80\`].IpRanges[].CidrIp' --output text | grep -q '0.0.0.0/0'"
check "usms-enrolment-sg still admits tcp/80 from usms-alb-sg" \
  "aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text | grep -qw $USMS_ALB_SG"
check "usms-db-sg still admits tcp/5432 from usms-app-sg" \
  "aws ec2 describe-security-groups --group-ids $USMS_DB_SG --query 'SecurityGroups[0].IpPermissions[].UserIdGroupPairs[].GroupId' --output text | grep -qw $USMS_APP_SG"

echo "== Lab 09 network: egress written =="
check "usms-alb-sg has NO allow-all egress rule" "test \"\$(allowall $USMS_ALB_SG)\" = 0"
check "usms-alb-sg egress destination is a GROUP, not a CIDR" \
  "aws ec2 describe-security-groups --group-ids $USMS_ALB_SG --query 'SecurityGroups[0].IpPermissionsEgress[].UserIdGroupPairs[].GroupId' --output text | grep -qw $USMS_ENROLMENT_SG"
check "usms-enrolment-sg has NO allow-all egress rule" "test \"\$(allowall $USMS_ENROLMENT_SG)\" = 0"
check "usms-enrolment-sg egress is tcp/443 only" \
  "test \"\$(aws ec2 describe-security-groups --group-ids $USMS_ENROLMENT_SG --query 'length(IpPermissionsEgress[?FromPort!=\`443\`])' --output text)\" = 0"
check "usms-db-sg has NO allow-all egress rule" "test \"\$(allowall $USMS_DB_SG)\" = 0"
check "usms-db-sg egress is tcp/443 only" \
  "test \"\$(aws ec2 describe-security-groups --group-ids $USMS_DB_SG --query 'length(IpPermissionsEgress[?FromPort!=\`443\`])' --output text)\" = 0"

echo "== Lab 09 network: the SSH cutover =="
check "usms-bastion-sg exists" \
  "aws ec2 describe-security-groups --filters Name=group-name,Values=usms-bastion-sg Name=vpc-id,Values=$USMS_VPC_ID --query 'SecurityGroups[0].GroupId' --output text | grep -q '^sg-'"
check "usms-app-sg admits tcp/22 from a GROUP" \
  "aws ec2 describe-security-groups --group-ids $USMS_APP_SG --query 'SecurityGroups[0].IpPermissions[?FromPort==\`22\`].UserIdGroupPairs[].GroupId' --output text | grep -q '^sg-'"
check "usms-app-sg has NO CIDR source on tcp/22" \
  "test \"\$(aws ec2 describe-security-groups --group-ids $USMS_APP_SG --query 'length(IpPermissions[?FromPort==\`22\`].IpRanges[])' --output text)\" = 0"

echo "== The negatives that must stay true =="
check "usms-db-01 has NO public address" \
  "test \"\$(aws ec2 describe-instances --instance-ids $USMS_DB_INSTANCE --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)\" = None"
check "the private subnet does NOT auto-assign public addresses" \
  "test \"\$(aws ec2 describe-subnets --subnet-ids $USMS_PRIVATE_SUBNET_A --query 'Subnets[0].MapPublicIpOnLaunch' --output text)\" = False"
check "the private route table has NO internet gateway route" \
  "! aws ec2 describe-route-tables --route-table-ids $USMS_PRIVATE_RT --query 'RouteTables[0].Routes[].GatewayId' --output text | grep -q 'igw-'"

echo "== Files, documents and Git hygiene =="
check "configs/lab-09.env exists" "test -f configs/lab-09.env"
check "configs/lab-09.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=\$|=None\$' configs/lab-09.env"
check "every policies/ document is valid JSON" \
  "for f in policies/*.json; do python3 -m json.tool \"\$f\" >/dev/null || exit 1; done"
check "no policies/ document contains an unexpanded variable" \
  "! grep -l '\\\$' policies/*.json"
check "the three audit scripts exist and are executable" \
  "test -x scripts/utilities/usms-iam-audit.sh && test -x scripts/utilities/usms-sg-audit.sh && test -x scripts/utilities/usms-reachability-matrix.sh"
check "no secret is tracked by git" "! git ls-files | grep -q '^outputs/'"

echo; echo "PASS=$PASS  FAIL=$FAIL"

if [ "$FAIL" -ne 0 ]; then
  cat <<'REMEDY'

A failure under "== Environment ==" is the real problem, and most failures below it are
a consequence. Fix that block first:
  ./scripts/utilities/floci-storage-check.sh

A failure under "== Labs 01 to 06 dependencies ==" means an earlier lab's resource is
gone. Run verify-lab-02.sh, verify-lab-03.sh, verify-lab-04.sh, verify-lab-05.sh and
verify-lab-06.sh before re-reading anything here.

A failure under "== The negatives that must stay true ==" is the most serious kind in
this script: something that was unreachable has become reachable. Stop and find out
what changed before doing anything else.
REMEDY
fi

[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-09.sh
bash -n scripts/utilities/verify-lab-09.sh && echo "syntax OK"
./scripts/utilities/verify-lab-09.sh
```{% endraw %}

**Expected result**

```text
syntax OK
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
== Labs 01 to 06 dependencies still present ==
  ok   usms-vpc exists
  ...
== Lab 09 identity: the read-only split ==
  ok   USMSStudentDataReadOnly exists
  ok   it ALLOWS s3:GetObject
  ok   it does NOT allow s3:PutObject
  ok   it explicitly DENIES s3:PutObject
  ...
== Lab 09 network: egress written ==
  ok   usms-alb-sg has NO allow-all egress rule
  ok   usms-alb-sg egress destination is a GROUP, not a CIDR
  ...
== The negatives that must stay true ==
  ok   usms-db-01 has NO public address
  ok   the private subnet does NOT auto-assign public addresses
  ok   the private route table has NO internet gateway route
== Files, documents and Git hygiene ==
  ok   configs/lab-09.env exists
  ...
  ok   no secret is tracked by git

PASS=50  FAIL=0
```

> Example output - the middle is abbreviated; you will see all 50.

**The expected count is `PASS=50  FAIL=0`.** Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `usms-deploy-role HAS a permissions boundary` | Some builds accept `--permissions-boundary` on `create-role` and do not store it. Confirm with `get-role --output json` and record it |
| `the boundary is attached to NOTHING` | Some builds do not populate `AttachmentCount` and return `None`. Confirm with `list-entities-for-policy` and record it |
| `usms-web-01 requires IMDSv2` | Some builds ignore `modify-instance-metadata-options`. Step 11's Floci note covers it |
| `it explicitly DENIES s3:PutObject` | Only if your build's `get-policy-version` returns the document URL-encoded rather than as JSON. Decode it with `python3 -c "import urllib.parse,sys;print(urllib.parse.unquote(sys.stdin.read()))"` and re-check by hand |
| `usms-app-sg has NO CIDR source on tcp/22` | **Not benign.** Step 16 part 3 did not remove the old rule. Go and do it |
| any check under `The negatives that must stay true` | **Not benign, and the most serious kind.** Something that was unreachable is now reachable |

Everything else failing is a real problem with your work.

### 8.2 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** `usms-deploy-role`, `usms-transcripts-reader-role`,
    `USMSStudentDataReadOnly`, `USMSDeployBase`, `USMSPermissionsBoundary` and `usms-bastion-sg`. It
    also **restores** the allow-all egress rule on three security groups and the `10.0.0.0/16` SSH
    rule on `usms-app-sg`, because leaving a group with no egress rules would break the labs that run
    after it in the teardown order.

    **What depends on it:** Lab 10 attaches nothing to these roles but reads
    `USMSStudentDataReadOnly` in its own hand-off. The CloudFormation lab re-declares all of them.

    **Reversible?** No. You would repeat this laboratory from Step 7.

    **Effect on later labs:** total. Run it only at the end of the course, and run the cleanup scripts
    in this order:

    ```text
    scripts/cleanup/lab-09-cleanup.sh    (this one - identity and rule changes, first)
    scripts/cleanup/lab-06-cleanup.sh   (scaling configuration)
    scripts/cleanup/lab-05-cleanup.sh   (load balancer and the service)
    scripts/cleanup/lab-04-cleanup.sh   (cluster, task definitions, roles, log group)
    scripts/cleanup/lab-03-cleanup.sh
    scripts/cleanup/lab-02-cleanup.sh
    ```

    This one runs **first**, before Lab 06's, and the reason is worth understanding: it restores
    egress rules that the later scripts' API calls do not need but that a person debugging a failed
    teardown will. A teardown that starts by removing your safety rails leaves you working blind.

    It requires you to type `UNDO USMS SECURITY REVIEW` in full before it does anything.

````bash
cat > scripts/cleanup/lab-09-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Reverses Lab 09, dependencies first.
# Order: detach and delete roles -> delete policies -> restore the rules this lab changed.
# Run FIRST of the teardown scripts. See Lab 09 Section 8.2.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-02.env"
source "$REPO_ROOT/configs/lab-04.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-05.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-09.env"

cat <<'WARN'
============================================================
  This DELETES the Lab 09 roles and policies, and RESTORES
  the allow-all egress rule on three security groups plus
  the 10.0.0.0/16 SSH rule on usms-app-sg.

  It does NOT undo the access key rotation (the old key is
  gone and cannot come back) and it does NOT undo the IMDSv2
  requirement, because neither of those should ever be undone.

  Run this FIRST, before lab-06-cleanup.sh.
============================================================
WARN

read -r -p 'Type exactly: UNDO USMS SECURITY REVIEW  > ' answer
[ "$answer" = "UNDO USMS SECURITY REVIEW" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }

say "detach policies from the Lab 09 roles"
for r in usms-deploy-role usms-transcripts-reader-role; do
  for p in $(aws iam list-attached-role-policies --role-name "$r" \
               --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    aws iam detach-role-policy --role-name "$r" --policy-arn "$p" || true
  done
done

say "remove the permissions boundary before deleting the role that wears it"
aws iam delete-role-permissions-boundary --role-name usms-deploy-role || true

say "delete the Lab 09 roles"
aws iam delete-role --role-name usms-deploy-role || true
aws iam delete-role --role-name usms-transcripts-reader-role || true

say "delete the Lab 09 policies (a policy with attachments refuses to be deleted)"
for p in USMSStudentDataReadOnly USMSDeployBase USMSPermissionsBoundary; do
  arn=$(aws iam list-policies --scope Local \
          --query "Policies[?PolicyName=='$p'].Arn | [0]" --output text 2>/dev/null || echo None)
  [ "$arn" = "None" ] && continue
  for v in $(aws iam list-policy-versions --policy-arn "$arn" \
               --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null); do
    aws iam delete-policy-version --policy-arn "$arn" --version-id "$v" || true
  done
  aws iam delete-policy --policy-arn "$arn" || true
done

say "restore allow-all egress, so a later teardown is not debugged blind"
for g in "${USMS_ALB_SG:-None}" "${USMS_ENROLMENT_SG:-None}" "${USMS_DB_SG:-None}"; do
  [ "$g" = "None" ] && continue
  aws ec2 authorize-security-group-egress \
    --group-id "$g" \
    --ip-permissions file://policies/usms-egress-allow-all.json >/dev/null 2>&1 || true
done

say "restore the Lab 02 SSH rule on usms-app-sg"
aws ec2 authorize-security-group-ingress \
  --group-id "$USMS_APP_SG" --protocol tcp --port 22 --cidr 10.0.0.0/16 >/dev/null 2>&1 || true

say "delete usms-bastion-sg (only if nothing references it)"
aws ec2 delete-security-group --group-id "${USMS_BASTION_SG:-none}" || \
  echo "  still referenced - revoke the usms-app-sg rule that names it, then retry"

echo
echo "Lab 09 teardown complete. scripts/cleanup/lab-06-cleanup.sh may now run."
EOF

chmod +x scripts/cleanup/lab-09-cleanup.sh
bash -n scripts/cleanup/lab-09-cleanup.sh && echo "syntax OK - do NOT run it"
````

You want `syntax OK - do NOT run it`. The order follows API dependencies: detach policies before deleting roles; remove the boundary before deleting its role; delete non-default policy versions before the policy (`Versions[?!IsDefaultVersion]` negates a boolean field); restore rules last, and the referencing rule before deleting the referenced group. It deliberately does **not** undo the key rotation or IMDSv2: a teardown should never leave the account less secure.

---

## 9. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 2 | Floci running under Compose, seven env files sourced with seventeen non-empty values, and all five earlier verification scripts run with their summary lines captured to `outputs/lab-09-pre-verify.txt` |
| 2 | Step 5 | `outputs/lab-09-identity-inventory.json` holds every role, trust policy and policy document; `usms-iam-audit.sh` reports `HIGH=4 MED=5` or your build's equivalent; no role in the account has a permissions boundary |
| 3 | Step 7 | `USMSStudentDataReadOnly` created with an explicit `Deny` on every write; `usms-transcripts-reader-role` carrying it; `usms-ecs-task-role` reporting `SAME PRINCIPAL, NEW CONDITION` |
| 4 | Step 8 | `USMSPermissionsBoundary` created and attached to nothing; `USMSDeployBase` with `iam:PassRole` scoped to three named ARNs plus an `iam:PassedToService` condition; `usms-deploy-role` carrying the boundary |
| 5 | Step 10 | `usms-dev-01` with exactly one `Active` access key created today; the `usms-dev` profile working; the old key deactivated, verified and then deleted; Lab 01's key file removed from `outputs/` |
| 6 | Step 11 | `usms-web-01` reporting `HttpTokens: required` and a hop limit of 1, or the limitation recorded with what real AWS would have done |
| 7 | Step 12 | `usms-sg-audit.sh` built and run; `outputs/lab-09-sg-findings-before.txt` showing the default egress rule on every group, and the SSH rule sourced from a whole VPC range |
| 8 | Step 15 | Zero allow-all egress rules remaining on `usms-alb-sg`, `usms-enrolment-sg` and `usms-db-sg`; every ingress rule in the VPC unchanged; `policies/usms-egress-allow-all.json` written **before** the first revoke |
| 9 | Step 16 | `usms-app-sg` admitting tcp/22 from `usms-bastion-sg` and from no CIDR at all |
| 10 | Step 17 | The reachability matrix computed from rules alone; five independent controls listed for `usms-db-01`; `usms-enrolment-sg` identified as a single point of control |
| 11 | Step 18 | `PERSISTENCE PROVEN` across nine controls with every identifier re-derived from the API, **and** `NOTHING BROKE` from the five earlier verification scripts |
| 12 | Step 20 | `configs/lab-09.env` committed with 16 exports and no access key ID; ten new documents in `policies/`; nothing under `outputs/` staged; `git check-ignore -v` naming the rule twice |

---

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, permissions boundaries and IMDSv2 `HttpTokens` are not reflected on readback. Diagnose first, then use the alternative in [Known Issues - Lab 09](known-issues.md#lab-09-security). It states what the alternative does and does not prove.

??? danger "`MalformedPolicyDocument` when creating a policy or a role"
    Usually an unexpanded shell variable, or one expanded that should not have been. Look at the document first:

    ```bash
    grep -n '\$' policies/*.json
    python3 -m json.tool policies/<the-one-that-failed>.json
    ```

    Literal `${USMS_ACCOUNT_ID}` means `<< 'EOF'` where Step 7 or 8 needs `<< EOF`. An empty string where an ARN should be means the variable was unset: re-source `configs/lab-01.env`. An IAM variable like `${aws:username}` in an unquoted heredoc gives `bad substitution`; escape it as `\${aws:username}` (Step 7's warning).

??? danger "`NoSuchEntity` when the role plainly exists"
    `get-role --role-name` takes a bare name and rejects an ARN with this error:

    ```bash
    aws iam list-roles --query 'Roles[].RoleName' --output text | tr '\t' '\n' | sort
    ```

    `--policy-arn` is the opposite: an ARN, never a name.

??? danger "`DeleteConflict` when deleting a role"
    An attached policy, an instance profile or a permissions boundary blocks deletion. Find which:

    ```bash
    aws iam list-attached-role-policies --role-name <role>
    aws iam list-role-policies --role-name <role>
    aws iam get-role --role-name <role> --query 'Role.PermissionsBoundary'
    aws iam list-instance-profiles-for-role --role-name <role>
    ```

    Detach everything, `delete-role-permissions-boundary`, then delete (the order in `scripts/cleanup/lab-09-cleanup.sh`).

??? danger "`DeleteConflict` when deleting a policy"
    It is still attached, or has more than one version.

    ```bash
    aws iam list-entities-for-policy --policy-arn <arn>
    aws iam list-policy-versions --policy-arn <arn> --query 'Versions[].[VersionId,IsDefaultVersion]' --output text
    ```

    Delete every non-default version first.

??? danger "The trust policy update succeeded and the condition is not there"
    `update-assume-role-policy` replaces the whole document, and a misplaced `Condition` can be accepted silently.

    ```bash
    aws iam get-role --role-name usms-ecs-task-role \
      --query 'Role.AssumeRolePolicyDocument' --output json | python3 -m json.tool
    ```

    `Condition` belongs **inside** a statement, beside `Effect`, `Principal` and `Action`. Inside `Principal` or at the top level it does nothing.

??? danger "`InvalidPermission.NotFound` when revoking an egress rule"
    Your permission does not exactly match the existing one. The default egress rule is protocol `-1`, one `IpRanges` entry of `0.0.0.0/0`, and **no** port fields. Revoke by rule ID instead:

    ```bash
    aws ec2 describe-security-group-rules --filters "Name=group-id,Values=$USMS_ENROLMENT_SG" \
      --query 'SecurityGroupRules[?IsEgress==`true`].[SecurityGroupRuleId,IpProtocol,CidrIpv4]' \
      --output text

    aws ec2 revoke-security-group-egress --group-id "$USMS_ENROLMENT_SG" \
      --security-group-rule-ids sgr-xxxxxxxxxxxx
    ```

??? danger "A security group now has no egress rules at all"
    You revoked before authorising, or the authorise failed. On real AWS that blocks all outbound traffic. Put it back, then redo the step in order:

    ```bash
    aws ec2 authorize-security-group-egress --group-id <sg> \
      --ip-permissions file://policies/usms-egress-allow-all.json
    ```

??? danger "`InvalidGroup.NotFound` when writing an egress rule that names a group"
    `$USMS_ENROLMENT_SG` or `$BASTION_SG` was empty when the document was written:

    ```bash
    cat policies/usms-alb-sg-egress.json
    ```

    A `GroupId` of `""` produces this error. Re-source `configs/lab-04.env` and rewrite the document.

??? danger "`aws sts get-caller-identity --profile usms-dev` fails with `InvalidClientTokenId`"
    Step 10 went wrong. Find where:

    ```bash
    aws configure get aws_access_key_id --profile usms-dev
    aws iam list-access-keys --user-name usms-dev-01 \
      --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output text
    ```

    If the profile's key is not listed, repoint it from `outputs/usms-dev-01-access-key-new.json`. If it is `Inactive`, reactivate it:

    ```bash
    aws iam update-access-key --user-name usms-dev-01 --access-key-id <id> --status Active
    ```

    If the new key file is also gone, the secret is unrecoverable: delete both keys and redo Step 10 from Part 2.

??? danger "`LimitExceeded` when creating an access key"
    `usms-dev-01` already has two, the maximum. Finish the previous rotation first.

    ```bash
    aws iam list-access-keys --user-name usms-dev-01 \
      --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output text
    ```

??? danger "`usms-iam-audit.sh` reports `no inventory` and exits 2"
    Run Step 4 Part 2 first, or pass a path:

    ```bash
    ./scripts/utilities/usms-iam-audit.sh outputs/lab-09-identity-inventory.json
    ```

    An empty inventory means `iam list-roles` returned nothing; check `./scripts/utilities/whoami.sh`.

??? danger "`usms-sg-audit.sh` prints group IDs instead of names"
    Some builds omit `GroupName` for the default group; cosmetic. For a group you created, check you are looking at the right VPC.

??? danger "`An error occurred (NoCredentials)` or a suggestion to run `aws login`"
    Do **not** run `aws login`; it signs in to **real AWS**. In this terminal:

    ```bash
    cd ~/aws-floci-course && source configs/course.env && ./scripts/utilities/whoami.sh
    ```

    Permanently: apply Errata 01. Also check Step 9's three environment credentials were unset: `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`.

??? danger "Everything is gone after a restart"
    Check storage mode:

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    `FLOCI_STORAGE_MODE=memory` means a stray `floci start` replaced the Compose container. Restore from your Lab 6 snapshot and confirm the storage check before rebuilding.

---

## 11. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `iam create-policy`, `create-role`, `attach-role-policy` | Full | Full; objects stored and returned correctly | Implemented in Floci |
| `iam update-assume-role-policy` | Full, replaces the document | Generally implemented | Implemented in Floci |
| Trust policy `Condition` blocks stored and returned | Full | Stored as written | Implemented in Floci |
| **IAM policy evaluation on every API call** | Every call, every time | **Not performed** - any credentials are accepted | Floci Limitation |
| `aws:SourceAccount` / `aws:SourceArn` enforcement | Enforced at `sts:AssumeRole` | Nothing evaluates the condition | Floci Limitation |
| `iam:PassRole` enforcement | Enforced on `RunInstances`, `RegisterTaskDefinition` and about forty other calls | Not enforced | Floci Limitation |
| Permissions boundaries | Enforced as a ceiling on every call | Stored at best; build-dependent | Floci Limitation |
| Session policies via `sts assume-role --policy` | Enforced as a third intersection | Credentials returned; policy ignored | Floci Limitation |
| `iam simulate-principal-policy` | Full policy evaluation without making the call | Usually absent | Floci Limitation |
| `iam get-account-authorization-details` | The whole account's IAM, in one call | Usually absent | Floci Limitation |
| `iam list-access-keys`, `create-access-key`, `update-access-key`, `delete-access-key` | Full; two-key limit enforced | Generally implemented | Implemented in Floci |
| `iam get-access-key-last-used` | Real last-used date, service and region | Field present; usually `N/A` | Floci Limitation |
| `iam get-credential-report` | An account-wide CSV of every credential's age and MFA state | Not available | Conceptual / Real AWS |
| IAM Access Analyzer, external access findings | Full | Not available | Conceptual / Real AWS |
| MFA condition keys (`aws:MultiFactorAuthPresent`) | Enforced | Nothing to enforce | Conceptual / Real AWS |
| Service Control Policies (AWS Organizations) | Evaluated before everything else | Single account; not modelled | Conceptual / Real AWS |
| CloudTrail - who did what, when | Every API call, in every region | Not available | Conceptual / Real AWS |
| `ec2 authorize/revoke-security-group-egress` | Full | Generally implemented | Implemented in Floci |
| Egress rules with a `UserIdGroupPairs` destination | Full | Stored and returned correctly | Implemented in Floci |
| Egress rules with a `PrefixListIds` destination | Full; the managed list is maintained by AWS | Build-dependent; the list may not exist | Floci Limitation |
| **Security group enforcement on traffic** | Every packet | **Not performed** - no traffic exists | Floci Limitation |
| Stateful return traffic | Real | Nothing to be stateful about | Floci Limitation |
| Network ACL rule ordering and the implicit deny | Enforced, stateless | Objects stored; not evaluated | Floci Limitation |
| `ec2 modify-instance-metadata-options` | Enforced at the hypervisor from the moment it returns | Stored at best; no metadata service exists | Floci Limitation |
| IMDSv2 token requirement | Enforced | Nothing to enforce | Floci Limitation |
| The `MetadataNoToken` CloudWatch metric | Published per instance; the safe way to roll out IMDSv2 | Not published | Conceptual / Real AWS |
| VPC interface endpoints for ECR, Logs and STS | Full; each gets a private address and its own group | Not modelled | Conceptual / Real AWS |
| Egress filtering by hostname (Network Firewall, a proxy) | Full | Not available | Conceptual / Real AWS |
| Cost - a NAT gateway, an interface endpoint per service per AZ | Real, and interface endpoints are not cheap | Free | Conceptual / Real AWS |
| Service quotas (60 rules per security group, 5 groups per interface) | Enforced | Not enforced | Conceptual / Real AWS |

**Where Floci is nicer than reality (traps on real AWS):** IAM changes apply instantly, but real IAM is eventually consistent, so retry the first use of a new identity; a wrong policy costs nothing here, while on AWS over-permissive is a finding and over-restrictive is an outage; no quotas (60 rules per group, 5 groups per interface); no cost (interface endpoints for ECR, Logs and STS across two AZs are six billed endpoints); and no CloudTrail to say who changed what.

**Two kinds of proof.** Demonstration proves one action was refused; review proves what a whole document permits, including untested cases. Security claims are about what *cannot* happen, so real review is mostly reading (`simulate-principal-policy` and Access Analyzer read too). What Floci removes is the loud failure of a malformed document, which is why Section 8 asserts on document structure. Say in your report which items you observed (documents, rules, the restart) and which you only reasoned about (any enforcement, SSRF, prefix-list routing, cost).

**Preventive, not detective.** Every control here prevents; none tells you when someone tries. The detective half is CloudTrail, CloudWatch alarms and GuardDuty, conceptual here; the CloudWatch lab covers alarms.

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-09-security/exercises.md`; screenshots go in `screenshots/`.

### Exercise 1 - Basic: finish the egress work on the web tier

**Requirements:** write egress for `usms-app-sg`, authorise it, revoke the default, and prove it. The web instance must still:

1. reach S3 for Lab 10's transcripts, through Lab 02's gateway endpoint,
2. reach AWS service endpoints over HTTPS, including STS for its instance profile credentials,
3. reach the enrolment API - which, since Lab 05, means the load balancer and not the tasks,
4. reach the database tier on PostgreSQL,
5. resolve names, which needs a rule you will have to reason about rather than copy.

**Constraints**

- The document is `policies/usms-app-sg-egress.json`, with the right heredoc quoting; say which and why.
- Requirement 3 is a **group reference**; work out which group.
- Requirement 5 needs **two** rules; justify the destination against Lab 2's reserved addresses.
- Authorise before revoking, and say why. Every rule has a `Description`.
- Do **not** touch `usms-app-sg`'s ingress rules.

**Expected outcome:** `usms-sg-audit.sh` shows written egress on `usms-app-sg` and no default rule; the matrix shows its destinations; `verify-lab-09.sh` still `FAIL=0`. Then say in two sentences why `usms-bastion-sg`'s egress is different in kind, and what its destination should be.

**Hints:** the resolver is the VPC's second address; DNS uses UDP and falls back to TCP. `169.254.169.254` is link-local and not subject to security groups; say why.

### Exercise 2 - Intermediate: the break-glass role, and the two findings this lab left open

**Requirements**

**Part A:** create `usms-breakglass-role`:

1. assumable only by `usms-admin-01`,
2. requiring MFA via `aws:MultiFactorAuthPresent`,
3. requiring `sts:ExternalId`, so assuming it is deliberate,
4. with the shortest maximum session IAM allows,
5. carrying a permissions boundary,
6. granting exactly the Application Auto Scaling calls Lab 6 used to suspend scaling, and nothing else.

**Part B:** for `usms-ec2-app-role`, `usms-ecs-exec-role` and `usms-lambda-exec-role`, either **fix** the unconditioned trust (two can be fixed) or **accept** it with a written reason and compensating control. Then make `usms-iam-audit.sh` report accepted findings as `ACCEPTED`, read from a file, not hard-coded.

**Constraints**

- No wildcard actions in Part A.
- Both Part A conditions in one `Condition` block; say whether they combine with AND or OR, and why.
- The accepted-findings file is committed with a reason per entry (otherwise it is a suppression list).
- The audit still exits 1 for any unaccepted HIGH finding.

**Expected outcome:** a role that cannot be assumed casually, a ten-second policy, and an audit that reports decisions.

**Hints:** `sts:ExternalId` is normally cross-account; say what it buys in one account. See each service's "cross-service confused deputy prevention" docs; the unfixable one gets credentials via a metadata service (Step 11).

### Exercise 3 - Problem solving: the exposure report

**Requirements:** write `scripts/utilities/usms-exposure-report.sh`, classifying every network interface in `usms-vpc`, one line each:

```text
usms-web-01        10.0.1.87   52.9.144.17  EXPOSED     igw route + sg allows 80,443 from 0.0.0.0/0
alb node (a)       10.0.1.14   -            EXPOSED     igw route + sg allows 80 from 0.0.0.0/0
usms-db-01         10.0.3.42   -            ISOLATED    no igw route on subnet
enrolment task     10.0.3.117  -            ISOLATED    no igw route on subnet
usms-nat           10.0.1.7    3.221.44.9   EXPOSED     igw route, but no ingress rule at all
```

The verdict is **computed** from the interface's subnet route table, public address and security group ingress rules, never from names, tags or descriptions.

**Constraints**

- Runs from any directory (resolve `configs/` from `${BASH_SOURCE[0]}`); no arguments; no hard-coded IDs.
- Handles: an interface whose group is not cached, no description, a subnet with no explicit route table association, and a lingering interface of a terminated instance.
- `set -uo pipefail`; justify your choice about `-e` in a comment.
- Decide and defend the verdict for a public interface with **no ingress rule at all** (the last example row).
- Also write `outputs/lab-09-exposure.json`.

**Expected outcome:** identical output from `~` and from `~/aws-floci-course/labs/lab-09-security/`, unchanged by Exercise 1's egress changes.

**Hints:** `describe-network-interfaces --filters "Name=vpc-id,Values=..."` returns everything; decide where to switch to `python3`. Step 17's matrix models security groups only; this tool models both axes.

### Exercise 4 - Challenge: the security review, written for someone else to act on

**Requirements:** the information security officer writes:

> I am told there has been a security review. Before I take it to the audit committee I need four
> things from you, in writing, and none of them longer than a page.
>
> First: we have two things on the public internet, not one. I understand the load balancer. Explain
> the web server, tell me whether it should still be reachable now that the load balancer exists, and
> if not, tell me exactly what would have to change and what would break.
>
> Second: you have restricted what our systems may connect out to. Tell me what class of incident that
> actually prevents, and be honest about what it does not - I have been told "we restricted egress" by
> three different vendors and I would like to know what I bought.
>
> Third: the transcripts. We hold the academic record of every student in the university. Tell me
> every identity that can currently read one, every identity that can write one, and how you know that
> list is complete.
>
> Fourth: we have no way of knowing when any of this changes. What would you put in place, what would
> it cost, and what would you look at first on the morning after an incident?

Write a review in `labs/lab-09-security/exercises.md` covering:

- **The second front door:** what `usms-app-sg`'s ingress is for, what changed since Lab 2 Step 14, and what moving the web tier behind the load balancer involves (target group, listener rule, security group change). Then argue the other side in two sentences.
- **What egress control bought:** three attacker behaviours Steps 13 to 15 prevent and two they do not, with the control (service, citation, rough cost) that would.
- **The transcripts access list** as a table (principal, how it gets access, read/write, granting document), and how you know it is complete: name the real-AWS API call, why this course cannot run it, and what you did instead.
- **Detection:** services that would report a group change, a policy attachment or an unusual assume-role; which are free; and what you would read first after an incident, in order.

Then write, but do not run, the numbered command sequence for moving the web tier behind the load balancer, with the four-line danger admonition on each destructive command.

**Constraints**

- Every cost has a citation.
- Every claim names the attacker behaviour, not the technology.
- The table derives from `policies/` and `outputs/lab-09-identity-inventory.json` and includes both `USMSStudentDataReadWrite` roles **and** the read-only role.
- Detection distinguishes preventive from detective controls (Section 11).

**Expected outcome:** a review a committee could accept and a junior engineer could implement without questions.

**Hints:** Step 15's text answers what egress control does not prevent. The missing call answers "who has access" from the resource's side; see IAM Access Analyzer and Exercise 5.

### Exercise 5 - Integration: the bucket policy the S3 configuration lab will apply

**Requirements:** every policy so far is an **identity** policy. A bucket can carry a **resource** policy (rule 6 of the evaluation order). Draft the one the (still unwritten) S3 configuration lab will apply:

1. `scripts/utilities/usms-bucket-policy-draft.sh` reads the inventory and the three transcripts policies, finds **every role ARN granted any `s3:` action on the bucket**, and writes `outputs/lab-09-bucket-policy-draft.json` with: an `Allow` for those principals limited to the actions they already have; a `Deny` for every principal when `aws:SecureTransport` is `false`; and a `Deny` for every principal other than those roles and the account root.
2. Validate it as JSON and check mechanically: every `Principal` is an ARN rather than `"*"`, except that the insecure-transport `Deny` uses `"Principal": "*"`; and the bucket ARN appears with and without `/*`.
3. Write `outputs/lab-09-lab10-readiness.txt`, one labelled line each: the bucket name read from Lab 1's policy; the three policy names; their role ARNs; the principal count; and one sentence on what changes, for whom, when Lab 10 runs `create-bucket`.
4. Append `USMS_BUCKET_POLICY_DRAFT` to `configs/lab-09.env` and state the new export count.
5. In three sentences, contrast this `Deny` with `USMSStudentDataReadOnly`'s: whose actions each can stop, and which applies to a principal in **another account**.

**Constraints**

- Derive the bucket name from a policy document; typing `usms-student-data` fails the exercise.
- Works whether or not the bucket exists; applies nothing.
- No script contains, reads or references an access key.
- `python3` for JSON, plus at least one shell parameter expansion, with a comment saying why.

**Expected outcome:** a committed script, a draft whose principals were computed, and a readiness file a reader can use without this document.

**Lab 10 reads this.** It validates the draft's ARNs against the bucket it creates; applying it remains the S3 configuration lab's job.

**Hints:** `list-entities-for-policy` per policy, then merge. An identity policy in your account is never consulted for another account's principal; a resource policy on your bucket always is.

---

## 13. Lab Assessment Checklist

Tick these off before you submit. Every one is checkable from your own repository.

**Environment**

- [ ] Floci runs under Docker Compose and `floci-storage-check.sh` reports `PASS=16  FAIL=0`
- [ ] `./scripts/utilities/whoami.sh` reports account `000000000000`
- [ ] No `floci start`, `docker compose down -v` or `docker volume prune` in your shell history
- [ ] Your Step 3 support path (A, B or C) is stated at the top of `notes/lab-09-notes.md`
- [ ] Whether `usms-student-data` existed when you ran Step 6 is stated there too

**Identity**

- [ ] `outputs/lab-09-identity-inventory.json` exists and covers every role in the account
- [ ] `usms-iam-audit.sh` exists, is read-only, and its findings are recorded before and after
- [ ] `USMSStudentDataReadOnly` allows `s3:GetObject` and `s3:ListBucket` and explicitly denies every write
- [ ] `usms-transcripts-reader-role` exists, carries it, and has the scoped trust policy
- [ ] `usms-ecs-task-role`'s trust policy has the two confused-deputy conditions and the **same** principal
- [ ] `USMSStudentDataReadWrite` is still attached to both of its original roles
- [ ] `USMSDeployBase` scopes `iam:PassRole` to three named ARNs with an `iam:PassedToService` condition
- [ ] `USMSPermissionsBoundary` exists and is attached to nothing
- [ ] `usms-deploy-role` exists, trusts a user, and carries the boundary
- [ ] `usms-dev-01` has exactly one access key, `Active`, created during this lab
- [ ] `usms-web-01` reports `HttpTokens: required`, or the limitation is recorded

**Network**

- [ ] `usms-sg-audit.sh` exists and its before and after output are both saved
- [ ] `usms-alb-sg`, `usms-enrolment-sg` and `usms-db-sg` each have zero allow-all egress rules
- [ ] `usms-alb-sg`'s egress destination is a **security group**, not a CIDR
- [ ] Every ingress rule in the VPC is exactly as Lab 05 left it
- [ ] `usms-app-sg` admits tcp/22 from a group and from no CIDR
- [ ] `usms-bastion-sg` exists
- [ ] `usms-reachability-matrix.sh` exists and computes its verdicts from rules only

**Evidence**

- [ ] Step 2's `outputs/lab-09-pre-verify.txt` and Step 18's `post-verify.txt`, and the `NOTHING BROKE` line
- [ ] Step 7's `SAME PRINCIPAL, NEW CONDITION` line
- [ ] Step 9's effective-permissions output, with at least one action that is **not** allowed
- [ ] Step 10's key listing before, during (two keys, one `Inactive`) and after
- [ ] Step 17's `outputs/lab-09-negative-proof.txt`, five controls
- [ ] Step 18's `PERSISTENCE PROVEN` line
- [ ] Screenshots in `screenshots/` for Checkpoints 4, 8 and 10

**Hygiene and written work**

- [ ] `configs/lab-09.env` exists, is committed, has 16 exports and no empty values or `None`
- [ ] `configs/lab-09.env` contains **no access key ID**
- [ ] `scripts/utilities/verify-lab-09.sh` reports `PASS=50  FAIL=0`, or its benign failures are each named and explained
- [ ] `scripts/cleanup/lab-09-cleanup.sh` exists, passes `bash -n`, and has **not** been run
- [ ] Every document in `policies/` is valid JSON and none contains an unexpanded variable
- [ ] `git status --short` shows nothing under `outputs/`
- [ ] `git check-ignore -v` demonstrated on the access key file
- [ ] `notes/lab-09-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-09-security/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done

**Understanding - answer these out loud before you submit**

- [ ] I can name the two axes of access control and say which kind of failure each one produces
- [ ] I can explain what a permissions boundary does without using the word "grant"
- [ ] I can describe the `iam:PassRole` escalation in five steps, from memory
- [ ] I can say why the access key rotation has four steps and what step 3 protects
- [ ] I can name four independent controls that make `usms-db-01` unreachable, and say which of them would still hold if the other three failed
- [ ] I can explain why nothing in this laboratory could be proven by watching a command fail

---

## 14. Review Questions

Answer in prose in `notes/lab-09-notes.md`.

1. Step 18 proved five pre-existing verification scripts report exactly what they did before. Explain why that is a strong result, describe a plausible change in this lab that would have broken one of them, and say what you would have done.
2. A colleague attaches `USMSPermissionsBoundary` to `usms-deploy-role` with `attach-role-policy`, reasoning it allows the same actions. What changes in that role's effective permissions, in both directions? When would their version become dangerous, and which Section 8 check catches it?
3. Describe a USMS incident in which every ingress rule is correct and the outcome is still a data breach. Which of Steps 13 to 15 would have narrowed it, and by how much? What would have prevented it entirely, and why can this course not build it?
4. `usms-ecs-task-role` and `usms-transcripts-reader-role` share a trust policy but not permissions; `usms-deploy-role` has a different trust policy and a boundary. For each, what happens if an attacker can call `sts:AssumeRole` for it from their own machine, and why do the answers differ?
5. Why is "five controls" on `usms-db-01` not simply five times better than "one control" on `usms-enrolment-sg`, given the specific failure modes involved? Are the enrolment tasks genuinely less well protected, given what Step 17 says the matrix models?
6. What does each of the two extra rotation steps in Step 10 protect against, and what incident would each prevent? Why is a long-lived key a compromise, and what would a real system use for a human and for a workload?
7. Argue whether Section 11's review methodology is an adequate substitute for testing. Name a defect reading catches that testing would not, and one testing catches that reading would not. Which would you want first for student transcripts?

---

## 15. KEEP vs CLEAN UP

```text
╔═══════════════════════ KEEP ════════════════════════╗    ╔═════════════ CLEAN UP ══════════════╗
║ USMSStudentDataReadOnly     Lab 10 makes it real    ║    ║ usms-breakglass-role                ║
║ USMSDeployBase              the CloudFormation lab  ║    ║   - Exercise 2 practice; remove it  ║
║ USMSPermissionsBoundary     attached to NOTHING.    ║    ║   at the end of the course only     ║
║                             Do not "tidy it up"     ║    ║                                     ║
║ usms-transcripts-reader-role                        ║    ║ outputs/lab-09-scoped-session.json  ║
║ usms-deploy-role            + its boundary          ║    ║   - Step 9 deleted it already;      ║
║ usms-ecs-task-role          the SCOPED trust policy ║    ║   check it is gone                  ║
║ usms-bastion-sg             the SSH rule names it   ║    ║                                     ║
║ the three written egress rules                      ║    ║ outputs/lab-09-pre/post-*.txt       ║
║ usms-app-sg's group-referenced SSH rule             ║    ║   - evidence; keep until            ║
║ IMDSv2 required on usms-web-01                      ║    ║   submitted, then remove            ║
║ the ONE access key on usms-dev-01                   ║    ║                                     ║
║ policies/  all ten new documents                    ║    ║ outputs/usms-dev-01-access-key.json ║
║   incl. usms-egress-allow-all.json, the undo        ║    ║   - Lab 01's key; the secret in it  ║
║ scripts/utilities/usms-iam-audit.sh                 ║    ║   no longer exists. Step 10 removed ║
║ scripts/utilities/usms-sg-audit.sh                  ║    ║   it; confirm                       ║
║ scripts/utilities/usms-reachability-matrix.sh       ║    ║                                     ║
║ scripts/utilities/verify-lab-09.sh                  ║    ║ outputs/lab-09-imds-before.json     ║
║ configs/lab-09.env          two later labs source it║    ║   - evidence; keep until submitted  ║
║ outputs/lab-09-bucket-policy-draft.json (Ex. 5)     ║    ║                                     ║
║   S3 lab (unwritten) applies it; Lab 10 validates   ║    ║                                     ║
║ everything from Labs 01, 02, 03, 04, 05 and 06   ║    ║                                     ║
╚═════════════════════════════════════════════════════╝    ╚═════════════════════════════════════╝
```

Clean up the right-hand column once your report is submitted:

```bash
rm -f outputs/lab-09-scoped-session.json
rm -f outputs/lab-09-pre-restart.txt   outputs/lab-09-post-restart.txt
rm -f outputs/lab-09-pre-verify.txt    outputs/lab-09-post-verify.txt
rm -f outputs/lab-09-imds-before.json  outputs/lab-09-imds-after.json
ls -l outputs/ | grep -i 'access-key' || echo "no access key files remain except the current one"
git status --short
./scripts/utilities/verify-lab-09.sh | tail -2
```

Keep `outputs/lab-09-identity-inventory.json`, `outputs/lab-09-iam-findings.txt`, `outputs/lab-09-sg-findings-before.txt`, `outputs/lab-09-reachability.txt` and `outputs/lab-09-negative-proof.txt` until Exercise 5 and your report are done; they are the evidence for your review.

`USMSPermissionsBoundary` has zero attachments and looks like an orphan; it is the control capping `usms-deploy-role`. Do not tidy it up. Confirm Lab 1's `outputs/usms-dev-01-access-key.json` is gone (Step 10 Part 5).

Do **not** run `scripts/cleanup/lab-09-cleanup.sh` or any earlier lab's cleanup script; they are for the end of the course, in the order Section 8.2 gives.

```text
Lab 01  IAM
  usms-developer-role .................. used in Lab 02, and in Lab 09 Step 9 WITH a session policy
  usms-ec2-app-role + usms-ec2-app-profile   on usms-web-01; trust STILL unconditioned (Exercise 2)
  usms-lambda-exec-role ................ waiting for Lab 10
  USMSStudentDataReadWrite ............. on TWO roles, naming a bucket that still does not exist
  usms-dev-01 .......................... ONE access key, rotated in Lab 09 Step 10

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    public  : usms-public-subnet-a / -b  -> usms-public-rt  -> usms-igw
    private : usms-private-subnet-a / -b -> usms-private-rt -> usms-nat
                                                            -> usms-s3-endpoint  (pl-... , now
                                                               named by an EGRESS RULE)
    firewalls: usms-app-sg, usms-db-sg, usms-enrolment-sg, usms-alb-sg, usms-bastion-sg,
               usms-private-nacl

Lab 03  COMPUTE - instances you administer
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile   usms-web-eip
                IMDSv2 REQUIRED, hop limit 1                        <- Lab 09 Step 11
  usms-db-01    private subnet a  usms-db-sg    no profile, no public address
  usms-web-golden  AMI

Lab 04 COMPUTE - containers you operate
  usms-ecs-cluster / usms-enrolment-svc / usms-enrolment:2
    executionRoleArn  usms-ecs-exec-role
    taskRoleArn       usms-ecs-task-role -> USMSStudentDataReadWrite
                      trust NOW conditioned on aws:SourceAccount + aws:SourceArn   <- Step 7

Lab 05 TRAFFIC - the front door
  usms-enrolment-alb / listener HTTP:80 / rule 10 /alb-health / usms-enrolment-tg
  usms-alb-sg        in  tcp/80 <- 0.0.0.0/0    out tcp/80 -> usms-enrolment-sg   <- Step 14
  usms-enrolment-sg  in  tcp/80 <- usms-alb-sg  out tcp/443 -> pl-<s3>, registry  <- Step 13

Lab 06 SCALING - the control loop
  scalable target, three policies, two scheduled actions, one alarm - UNCHANGED by this lab

Lab 09  SECURITY - a ceiling, a scope and a written egress       <-- you are here
  USMSPermissionsBoundary   a ceiling. Attached to nothing. Deleting it removes a control
  USMSDeployBase            iam:PassRole -> 3 named ARNs, ecs-tasks only, Deny on ec2
  usms-deploy-role          trusts user/usms-admin-01, wears the boundary
  USMSStudentDataReadOnly   Get + List, explicit Deny on every write
  usms-transcripts-reader-role
  usms-bastion-sg           named by usms-app-sg's SSH rule; carries no instance yet
  and NOTHING FUNCTIONAL CHANGED: same service, same revision, same target group,
  same scaling, same five verification scripts reporting the same five lines

Lab 10  LAMBDA (next)
  usms-student-data  <- Lab 10 creates the bucket, making THREE policies real at once; its
                        resource policy (Lab 09's Exercise 5) still waits for the
                        (still unwritten) S3 configuration lab
```

---

## 16. Preparation for the Next Lab

Lab 10 creates `usms-student-data`. `USMSStudentDataReadWrite` (on `usms-ec2-app-role`, `usms-ecs-task-role` and `usms-eks-node-role`) and today's `USMSStudentDataReadOnly` stop being hypothetical at that moment; the Exercise 5 resource policy waits for the S3 configuration lab.

| From this lab | Lab 10 uses it for |
| --- | --- |
| `USMSStudentDataReadOnly` and `usms-transcripts-reader-role` | The fourth chain that resolves at `create-bucket`, and the read-only half of its access model |
| `outputs/lab-09-bucket-policy-draft.json` (Exercise 5) | Validated against the bucket once it exists. Applying it as the bucket's actual **resource** policy is the (still unwritten) S3 configuration lab's job, not Lab 10's |
| `outputs/lab-09-lab10-readiness.txt` (Exercise 5) | Not read by any later step - it is your own record of the bucket name and principal list, for when you want it without re-deriving it |
| `configs/lab-09.env` | Sourced alongside lab-01/02/03/04/05/06/07/08 |
| `scripts/utilities/usms-iam-audit.sh` | Re-run after Lab 10 attaches anything, to catch a new wildcard on the day it appears |

| From earlier labs | Lab 10 uses it for |
| --- | --- |
| Lab 01 `USMSStudentDataReadWrite` | The policy whose `Resource` names the bucket. Lab 10 creates the bucket the policy already describes, in that order, deliberately |
| Lab 01 `usms-ec2-app-role` | One of the three roles that starts working the instant the bucket exists |
| Lab 04 `usms-ecs-task-role` | The second - with a scoped trust policy, which changes nothing about its permissions and everything about who can obtain them |
| Lab 07 `usms-eks-node-role` | The third, attached unchanged since Step 7 - the coarse, every-pod-on-every-node answer Lab 07 flagged and did not fix |
| Lab 02 `usms-s3-endpoint` | The gateway endpoint, which since Step 13 is also named by a security group egress rule and finally has something to carry |

Before the next session:

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-06.sh | tail -2
./scripts/utilities/verify-lab-09.sh  | tail -2
grep -c '^export' configs/lab-09.env
./scripts/utilities/usms-iam-audit.sh | tail -1
./scripts/utilities/usms-sg-audit.sh  | tail -1
aws iam list-entities-for-policy \
  --policy-arn "arn:aws:iam::000000000000:policy/USMSStudentDataReadWrite" \
  --query 'length(PolicyRoles)' --output text
```

You want `FAIL=0` twice; **16** (or 17 after Exercise 5); an IAM `HIGH=` count lower than Step 5's but non-zero; about `HIGH=2 MED=3 LOW=1` from the security group audit (remaining MEDs are `usms-app-sg` and `usms-bastion-sg` egress); and `3` from the last call. `1` there means `USMSStudentDataReadWrite` was detached from a role; fix it before Lab 10.

Take a snapshot so a Lab 10 mistake is recoverable:

```bash
floci snapshot save lab-09-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-09.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-09.tar.gz
```

---

## Appendix - New CLI and JMESPath patterns

Labs 1 to 06 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `starts_with()`, `@`, flattening with `[]`, `--filters`, `--generate-cli-skeleton`,
`--cli-input-json`, waiters, boolean and string literals in filters, and expression references. This
lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `--scope Local` | Your policies only, not the several hundred AWS managed ones | Step 4 |
| `Policies[?PolicyName=='X'].Arn \| [0]` | Find an ARN by name - the only way in, since IAM's read calls take ARNs | Steps 19, Section 8 |
| `length(Role.AssumeRolePolicyDocument.Statement[0].Condition)` | Count a condition block's keys - a number is more `diff`-stable than an object | Step 18 |
| `AccessKeyMetadata[?AccessKeyId!='X'].AccessKeyId \| [0]` | "The other one", without assuming an ordering | Step 10 |
| `Versions[?!IsDefaultVersion].VersionId` | `!` negating a boolean field inside a filter | Section 8.2 |
| `Routes[?DestinationPrefixListId!=` backtick `null` backtick `]` | Test a field for not-null, with `null` as a JSON literal | Step 13 |
| `length(IpPermissionsEgress[?IpProtocol==` backtick `-1` backtick `])` | Count the AWS default egress rules - zero is the assertion | Steps 15, 18, Section 8 |
| `length(IpPermissions[?FromPort==` backtick `22` backtick `].IpRanges[])` | Count CIDR sources on one port - a negative assertion | Steps 18, Section 8 |
| `--ip-permissions` with `PrefixListIds` | An egress rule whose destination is a managed prefix list | Step 13 |
| `--ip-permissions` with `UserIdGroupPairs` on **egress** | An outbound rule whose destination is a security group | Step 14 |
| `--permissions-boundary` | The second policy slot on a role. A ceiling, never a grant | Step 8 |
| `sts assume-role --policy file://...` | A session policy: a third intersection, set by the caller at assume time | Step 9 |
| `diff <(cmd) <(cmd)` | Process substitution - compare two pipelines without touching disk | Step 18 |
| `{ ...; } \| tee file` | Capture a whole block's output, not just the last command's | Steps 2, 17 |
| `$$` in a temporary filename | The shell's process ID, so two people on one machine do not collide | Steps 12, 17 |
| A quoted heredoc containing a Python program | `<< 'PY'` so that braces, `$` and f-strings all survive | Steps 4, 9, 11 |
| An `if` choosing between a quoted and an unquoted heredoc | Two documents, opposite quoting, one decision | Step 13 |
| `\$` and escaped backticks inside an unquoted heredoc | Passing a dollar or a backtick through to a program that runs later | Step 19 |

### The distinction to keep straight

Three documents in this laboratory look similar and answer completely different questions:

```text
TRUST POLICY          on a role, exactly one, always has a Principal
                      answers: WHO may become this role
                      changed with: update-assume-role-policy   (a REPLACE)

IDENTITY POLICY       on a role, user or group; up to 10 managed plus inline; no Principal
                      answers: WHAT may this principal do
                      changed with: attach-role-policy / put-role-policy

RESOURCE POLICY       on the RESOURCE, one per resource, always has a Principal
                      answers: WHO may do what to THIS THING
                      changed with: put-bucket-policy and its equivalents   -> the S3 lab (unwritten)
```

The middle one is the only one that cannot name a principal, and the reason is that the principal is
implied: it is whatever the policy is attached to. The other two must name one, and a `Principal` of
`"*"` means something very different in each - in a trust policy it means anyone in the world may
assume the role, which is a catastrophe; in a resource policy with a `Deny` and a condition, as
Exercise 5 writes, it is exactly right.

And two mechanisms that only ever subtract:

```text
PERMISSIONS BOUNDARY  on a principal, in a second slot, until removed.       Set by the administrator.
SESSION POLICY        on one assume-role call, for that session only.        Set by the CALLER.

effective = identity policy  AND  boundary  AND  session policy   -- minus every explicit Deny
```

---

## Sources

- [Policy evaluation logic - AWS IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [Policies and permissions in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html)
- [Permissions boundaries for IAM entities](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html)
- [Session policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html#policies_session)
- [Granting a user permission to pass a role to an AWS service](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html)
- [The confused deputy problem, and `aws:SourceArn` / `aws:SourceAccount`](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
- [AWS global condition context keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html)
- [IAM roles for Amazon ECS tasks, including the task role trust policy](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [Rotating access keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html#Using_RotateAccessKey)
- [Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [`aws iam` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/iam/)
- [Security groups: control traffic to your resources](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html)
- [Security group rules, including egress and prefix-list destinations](https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html)
- [Managed prefix lists, and the AWS-managed lists for gateway endpoints](https://docs.aws.amazon.com/vpc/latest/userguide/working-with-aws-managed-prefix-lists.html)
- [Gateway endpoints for Amazon S3](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html)
- [Use IMDSv2 - Amazon EC2 User Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html)
- [Instance metadata and user data, including the hop limit](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html)
- [Add defense in depth against open firewalls, reverse proxies, and SSRF vulnerabilities with enhancements to the EC2 Instance Metadata Service](https://aws.amazon.com/blogs/security/defense-in-depth-open-firewalls-reverse-proxies-ssrf-vulnerabilities-ec2-instance-metadata-service/)
- [Bucket policies for Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html)
- [`aws ec2` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/)
- [JMESPath specification](https://jmespath.org/specification.html)
- [RFC 5737 - IPv4 address blocks reserved for documentation](https://datatracker.ietf.org/doc/html/rfc5737)

# AWS Identity and Access Management (IAM)

> **Module SE4xx-CLD-01 — Practical AWS with Floci**
> Faculty of Software Engineering · College of Science and Technology, Royal University of Bhutan

| Attribute | Value |
|---|---|
| Topic | AWS Identity and Access Management (IAM) + AWS STS |
| Target audience | 4th-year Software Engineering (B.E. SE) |
| Delivery | 70% hands-on lab / 30% conceptual |
| Contact hours | 2 lectures (2 h) + 4 lab sessions (8 h) + 6 h self-study |
| Environment | Floci CLI — local AWS emulator (Docker-based) |
| Interface | **AWS CLI v2 only.** The AWS Management Console is *not* used in this module. |
| Certification alignment | AWS Certified Solutions Architect – Associate (SAA-C03), Domain 1 *Design Secure Architectures* |
| Assessment | Mini challenges (20%), debugging challenges (20%), viva (30%), enterprise scenario report (30%) |

---

## 0. Before You Begin

### 0.1 Why IAM is the first module in this course

Every single AWS API call you will ever make — `aws s3 ls`, `aws ec2 run-instances`, a Lambda function reading DynamoDB — is authenticated and authorised by IAM before anything else happens. If you do not understand IAM, you do not understand AWS; you are just typing commands and hoping.

IAM is also the single most common source of production incidents and security breaches in cloud environments. Leaked long-lived access keys, over-permissive `"Action": "*"` policies, and roles trusting `"Principal": "*"` are the top findings in nearly every cloud security audit.

!!! quote "The rule that governs this module"
    **Nothing in AWS is permitted unless something explicitly allows it, and anything explicitly denied can never be allowed.**

### 0.2 Prerequisites checklist

Before your first lab session, confirm each item:

| # | Requirement | Verification command | Expected |
|---|---|---|---|
| 1 | Docker running | `docker info --format '{{ServerVersion}}'` | a version string |
| 2 | Floci CLI installed | `floci --version` | a version string |
| 3 | AWS CLI v2 installed | `aws --version` | `aws-cli/2.x.x ...` |
| 4 | `jq` installed | `jq --version` | `jq-1.6` or later |
| 5 | Comfortable with JSON | — | you can read/write nested JSON by hand |
| 6 | Comfortable with Bash | — | variables, heredocs, exit codes, `$?` |

!!! warning "Install `jq` now"
    Every verification step in this module pipes JSON through `jq`. On Debian/Ubuntu: `sudo apt-get install -y jq`. On macOS: `brew install jq`.

### 0.3 Starting the Floci environment

```bash
# 1. Start the emulator. --persist keeps state across restarts so your labs survive a reboot.
floci start --persist ./floci-state --detach

# 2. Block until the emulator is accepting requests (max 2 minutes)
floci wait --timeout 2m

# 3. Export AWS_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
eval "$(floci env)"

# 4. Confirm the shell is now pointed at Floci, not real AWS
echo "$AWS_ENDPOINT_URL"
```

**Parameter explanation**

| Flag | Meaning | Why we use it |
|---|---|---|
| `--persist ./floci-state` | Bind-mounts a host directory for emulator state | Your users, roles and policies survive `floci stop` |
| `--detach` | Returns immediately instead of streaming logs | Frees your terminal for lab work |
| `--timeout 2m` on `wait` | Readiness poll ceiling | First start pulls the image; 30 s default is often too short |

Expected output of step 4:

```
http://localhost.floci.io:4566
```

!!! danger "The single most important safety habit in this module"
    `AWS_ENDPOINT_URL` is what keeps your commands inside the emulator. If that variable is empty, **the exact same commands will hit real AWS** using whatever credentials are in `~/.aws/credentials`, and you may create billable resources or modify a real account. Run this guard at the top of every lab session:

    ```bash
    guard() {
      case "${AWS_ENDPOINT_URL:-}" in
        *localhost*|*127.0.0.1*|*floci*) echo "OK: targeting Floci at $AWS_ENDPOINT_URL" ;;
        *) echo "REFUSING TO RUN: AWS_ENDPOINT_URL is '${AWS_ENDPOINT_URL:-<empty>}'" >&2; return 1 ;;
      esac
    }
    guard || eval "$(floci env)"
    ```

### 0.4 Lab conventions used throughout this module

We simulate a single fictional organisation for the whole module (see §6). All resources follow one naming standard so that cleanup and auditing are mechanical.

```
<org>-<environment>-<function>[-<qualifier>]
 dnb  -  dev       - developers
 dnb  -  dev       - app        - role
```

| Convention | Value | Rationale |
|---|---|---|
| Org prefix | `dnb-` (Druk National Bank) | Namespaces every resource; makes bulk cleanup safe |
| IAM path | `/dnb/dev/` | Groups resources hierarchically; enables path-scoped policies |
| Mandatory tags | `Project`, `Environment`, `Owner`, `CostCenter`, `ManagedBy` | Cost allocation + attribute-based access control (ABAC) |
| Region | `us-east-1` | IAM is global, but the CLI still requires a region |
| Scratch directory | `~/iam-lab` | All policy JSON files live here |

```bash
mkdir -p ~/iam-lab/policies ~/iam-lab/out && cd ~/iam-lab
```

!!! note "For the instructor: MkDocs configuration"
    This document uses admonitions (`!!! note`) and collapsible blocks (`??? note`, used for the hints in §12). Enable both in `mkdocs.yml`:

    ```yaml
    theme:
      name: material
    markdown_extensions:
      - admonition
      - pymdownx.details        # required for the ??? collapsible hints
      - pymdownx.superfences
      - attr_list
      - tables
      - toc:
          permalink: true
    ```

    Without `pymdownx.details`, the `??? note` hint blocks in §12 render as plain text and the answers become visible immediately.

### 0.5 Floci support tiers — and how to verify them yourself

Floci implements roughly **68 IAM operations and 7 STS operations** behind the unified endpoint `http://localhost:4566`. Floci is an *emulator*, not AWS, so three categories exist:

| Tier | Symbol | Meaning | How you must treat it |
|---|---|---|---|
| Fully supported | ✅ | Operation exists and behaves like AWS | Build, verify, and break it locally |
| Partially supported | ⚠️ | Operation accepts the call and stores the object, but the *behavioural consequence* may not be enforced | Verify the object was stored; learn the AWS consequence conceptually |
| Not supported | ❌ | Operation returns an error or is absent | Conceptual discussion + closest local approximation |

!!! danger "Emulators store policies; they do not necessarily enforce them"
    This is the most important caveat in the entire module. A local emulator will happily let you `CreatePolicy`, `AttachUserPolicy`, and `PutUserPermissionsBoundary`. That does **not** prove the emulator will *deny* a request that the policy forbids. Control-plane authorisation (evaluating `iam:*`, `s3:*` etc. against the caller's identity) is expensive to implement and commonly stubbed out or partly implemented in emulators.

    Therefore this module teaches IAM on **two tracks, always side by side**:

    * **Track A — Modelling & structure (verifiable in Floci).** Does the policy document exist, parse, attach, and version correctly? Does the trust policy allow `AssumeRole` to return credentials? Is the boundary attached to the principal?
    * **Track B — Enforcement semantics (reasoned, and tested for *if* Floci enforces).** What would real AWS decide for this request, and why? Every "Break it" step tells you the AWS-correct verdict, then has you *test whether your Floci build enforces it*.

    Never write in a lab report "IAM denied my request" unless you observed the `AccessDenied` yourself. Write "AWS would deny this request because …; my Floci build returned …".

#### 0.5.1 The support-probe harness (run this once, keep the output)

Rather than trusting any table in any document — including this one — you will empirically discover your build's support surface. Save this as `~/iam-lab/probe-support.sh`:

```bash
#!/usr/bin/env bash
# probe-support.sh — discover which IAM/STS operations this Floci build implements.
# Strategy: call each operation with harmless/read-only or throwaway arguments and
# classify the result by the ERROR CODE, not by success alone.
set -uo pipefail

OUT=~/iam-lab/out/support-matrix.tsv
: > "$OUT"

classify() {
  local name="$1"; shift
  local stderr rc
  stderr="$("$@" 2>&1 >/dev/null)"; rc=$?
  if [ $rc -eq 0 ]; then
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED" "-" >> "$OUT"
  elif grep -qiE 'InvalidAction|not implemented|NotImplemented|Unknown operation|InternalFailure|501' <<<"$stderr"; then
    printf '%s\t%s\t%s\n' "$name" "UNSUPPORTED" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  elif grep -qiE 'NoSuchEntity|ValidationError|InvalidInput|MalformedPolicy|EntityAlreadyExists' <<<"$stderr"; then
    # The operation was routed and validated -> it exists.
    printf '%s\t%s\t%s\n' "$name" "SUPPORTED(validated)" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  else
    printf '%s\t%s\t%s\n' "$name" "UNKNOWN" "$(head -c 120 <<<"$stderr" | tr '\n' ' ')" >> "$OUT"
  fi
}

# --- Read-only listings: safe to call on any account ---
for op in list-users list-groups list-roles list-policies list-instance-profiles \
          list-account-aliases list-open-id-connect-providers list-saml-providers \
          list-server-certificates list-virtual-mfa-devices; do
  classify "iam:$op" aws iam "$op"
done

classify "iam:get-account-summary"          aws iam get-account-summary
classify "iam:get-account-password-policy"  aws iam get-account-password-policy
classify "iam:get-account-authorization-details" aws iam get-account-authorization-details
classify "iam:generate-credential-report"   aws iam generate-credential-report
classify "iam:get-credential-report"        aws iam get-credential-report
classify "sts:get-caller-identity"          aws sts get-caller-identity
classify "sts:get-session-token"            aws sts get-session-token

# --- Operations probed with a deliberately non-existent entity ---
# NoSuchEntity => routed & implemented.  InvalidAction => not implemented.
classify "iam:get-user"                aws iam get-user --user-name __probe_missing__
classify "iam:get-role"                aws iam get-role --role-name __probe_missing__
classify "iam:get-group"               aws iam get-group --group-name __probe_missing__
classify "iam:list-attached-user-policies" aws iam list-attached-user-policies --user-name __probe_missing__
classify "iam:list-user-tags"           aws iam list-user-tags --user-name __probe_missing__
classify "iam:get-login-profile"        aws iam get-login-profile --user-name __probe_missing__
classify "iam:list-access-keys"          aws iam list-access-keys --user-name __probe_missing__
classify "iam:get-access-key-last-used"  aws iam get-access-key-last-used --access-key-id AKIAIOSFODNN7EXAMPLE
classify "iam:list-mfa-devices"          aws iam list-mfa-devices --user-name __probe_missing__
classify "iam:get-user-policy"           aws iam get-user-policy --user-name __probe_missing__ --policy-name p
classify "iam:list-policy-versions"      aws iam list-policy-versions --policy-arn arn:aws:iam::000000000000:policy/__probe_missing__
classify "iam:get-role-policy"           aws iam get-role-policy --role-name __probe_missing__ --policy-name p
classify "iam:list-entities-for-policy"  aws iam list-entities-for-policy --policy-arn arn:aws:iam::000000000000:policy/__probe_missing__
classify "iam:simulate-principal-policy" aws iam simulate-principal-policy \
            --policy-source-arn arn:aws:iam::000000000000:user/__probe_missing__ --action-names s3:GetObject
classify "iam:simulate-custom-policy"    aws iam simulate-custom-policy \
            --policy-input-list '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":"*"}]}' \
            --action-names s3:GetObject
classify "iam:get-user-permissions-boundary-via-get-user" aws iam get-user --user-name __probe_missing__
classify "iam:list-role-tags"            aws iam list-role-tags --role-name __probe_missing__
classify "iam:get-instance-profile"      aws iam get-instance-profile --instance-profile-name __probe_missing__
classify "iam:list-service-specific-credentials" aws iam list-service-specific-credentials --user-name __probe_missing__
classify "iam:get-organizations-access-report" aws iam get-organizations-access-report --job-id x

column -t -s $'\t' "$OUT"
echo
echo "SUMMARY:"; awk -F'\t' '{c[$2]++} END{for(k in c) printf "  %-22s %d\n", k, c[k]}' "$OUT"
```

Run it and archive the result — you will cite this file in every lab report:

```bash
chmod +x ~/iam-lab/probe-support.sh
~/iam-lab/probe-support.sh | tee ~/iam-lab/out/support-report.txt
```

Expected output shape (your values will differ — that is the point):

```
iam:list-users                   SUPPORTED             -
iam:list-groups                  SUPPORTED             -
iam:get-account-password-policy  SUPPORTED(validated)  NoSuchEntity: cannot be found
iam:simulate-principal-policy    UNSUPPORTED           InvalidAction: ...
sts:get-caller-identity          SUPPORTED             -
...
SUMMARY:
  SUPPORTED              14
  SUPPORTED(validated)   11
  UNSUPPORTED             3
  UNKNOWN                 2
```

!!! tip "How to read the probe results"
    * `SUPPORTED` — the call succeeded outright.
    * `SUPPORTED(validated)` — the call was *routed to a real handler* which then rejected your fake input (`NoSuchEntity`, `ValidationError`). This is strong evidence the operation exists.
    * `UNSUPPORTED` — the emulator does not know this action at all (`InvalidAction`, `NotImplemented`).
    * `UNKNOWN` — inspect the message manually and reclassify by hand.

    Note that `NoSuchEntity` on `get-account-password-policy` lands in `SUPPORTED(validated)` and means **supported but not yet configured** — you will set it in §4.6.

#### 0.5.2 The enforcement-probe harness

Support ≠ enforcement. This second harness answers the question *"does my build actually deny?"* You will run it in **Lab 11** once you have principals to test with. Save as `~/iam-lab/probe-enforcement.sh`:

```bash
#!/usr/bin/env bash
# probe-enforcement.sh <profile-name> <expect: allow|deny> <aws args...>
# Prints VERDICT so you can compare Floci's behaviour against AWS's correct answer.
set -uo pipefail
PROFILE="$1"; EXPECT="$2"; shift 2
if out="$(AWS_PROFILE="$PROFILE" AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_SESSION_TOKEN= "$@" 2>&1)"; then
  ACTUAL=allow
else
  if grep -qiE 'AccessDenied|not authorized|UnauthorizedOperation|explicit deny' <<<"$out"; then
    ACTUAL=deny
  else
    ACTUAL="error:$(head -c 80 <<<"$out" | tr '\n' ' ')"
  fi
fi
if [ "$ACTUAL" = "$EXPECT" ]; then
  printf 'ENFORCED-CORRECTLY  expect=%s actual=%s  cmd=%s\n' "$EXPECT" "$ACTUAL" "$*"
else
  printf 'DIVERGES-FROM-AWS   expect=%s actual=%s  cmd=%s\n' "$EXPECT" "$ACTUAL" "$*"
fi
```

!!! note "`DIVERGES-FROM-AWS` is not a bug you need to fix"
    It is a *finding*. It tells you which parts of your mental model this emulator cannot validate for you, and therefore which parts you must reason about carefully before you ever touch a real AWS account.

---

## 1. Learning Outcomes

On successful completion of this module, a student will be able to:

| # | Outcome | Bloom level | Assessed in |
|---|---|---|---|
| LO1 | **Explain** the AWS shared-responsibility and authentication/authorisation model, and locate IAM within it | Understand | Viva, Interview Q |
| LO2 | **Decompose** an ARN and **navigate** IAM's object model (account → principal → policy → resource) | Understand | Lab 1, Viva |
| LO3 | **Create and manage** IAM users, groups, and group memberships via the AWS CLI, using paths and tags | Apply | Lab 1, 2 |
| LO4 | **Author** valid IAM policy documents from scratch, including `Condition` blocks, policy variables, `NotAction`, and wildcards | Apply/Create | Lab 3, 4, MC3 |
| LO5 | **Distinguish** managed from inline policies and **justify** a choice for a given governance requirement | Analyse | Lab 4, Interview Q |
| LO6 | **Manage** the customer-managed policy version lifecycle (create, set default, roll back, delete) | Apply | Lab 3 |
| LO7 | **Implement** IAM roles with correct trust policies and **obtain** temporary credentials via `sts assume-role`, including role chaining | Apply | Lab 6 |
| LO8 | **Contrast** identity-based, resource-based, permissions-boundary, and session policies, and **predict** the outcome of AWS's policy evaluation logic for a given request | Analyse/Evaluate | Lab 8, 9, DC2, Viva |
| LO9 | **Apply** the principle of least privilege, replacing wildcard grants with scoped, conditioned grants | Apply/Evaluate | Lab 3, MC4, Scenario |
| LO10 | **Diagnose** IAM failures from CLI error output and **remediate** them systematically | Analyse | Lab 11, DC1–DC5 |
| LO11 | **Integrate** IAM with EC2 (instance profiles), Lambda (execution roles), and S3 (bucket policies) | Apply | Lab 7, 8, 10 |
| LO12 | **Evaluate** which IAM behaviours a local emulator can and cannot validate, and **document** divergence from AWS | Evaluate | Every lab; §0.5 report |

### SAA-C03 mapping

| SAA-C03 task statement | Covered by |
|---|---|
| 1.1 Design secure access to AWS resources | §4.3–4.13, Labs 1–9 |
| 1.2 Design secure workloads and applications | Labs 7, 8, 10, §6 |
| 1.3 Determine appropriate data security controls | §9, Lab 8 |
| 3.x Determine high-performing / resilient architectures (role-based access for services) | Labs 7, 10, §10 |

---

## 2. Service Overview

### 2.1 What IAM is

**AWS Identity and Access Management (IAM)** is the AWS control-plane service that answers exactly one question, for every API request made to AWS:

> *Is this **principal** allowed to perform this **action** on this **resource** under these **conditions**?*

IAM is:

* **Global** — not regional. An IAM user created "in" `us-east-1` is visible in every region. (The endpoint `iam.amazonaws.com` lives in `us-east-1`.)
* **Free** — IAM itself incurs no charge.
* **Eventually consistent** — a newly created role may not be immediately usable everywhere; AWS documents propagation delay. This is why real-world scripts retry `AssumeRole` after `CreateRole`.
* **Deny-by-default** — a brand-new IAM user can do literally nothing, not even `aws sts get-caller-identity`'s underlying reads on other services.

### 2.2 Why IAM exists — the problems it solves

| Problem without IAM | IAM's answer |
|---|---|
| One root login shared by the whole team; no attribution | Individual **users**, one identity per human |
| Every developer has full account power | **Policies** granting only what the job requires |
| Managing permissions per-person doesn't scale to 200 engineers | **Groups** — attach a policy once, add people to it |
| An application on a server needs credentials, but hard-coded keys leak into Git | **Roles** + **instance profiles** deliver short-lived, auto-rotated credentials with no secrets on disk |
| Contractors from another company need limited access to one bucket | **Cross-account roles** with an external trust policy — no user created in your account |
| Corporate staff already have Active Directory / Google accounts; a second password set is a liability | **Federation** (SAML / OIDC) → `sts:AssumeRoleWith*` |
| A junior admin with `iam:*` could grant themselves anything | **Permissions boundaries** — a ceiling that delegated admins cannot exceed |
| A leaked key remains valid indefinitely | Temporary credentials that expire in 15 min – 12 h |
| Auditors ask "who deleted the production database on 14 March?" | IAM identity in every CloudTrail event |

### 2.3 Typical use cases

1. **Human access** — per-engineer users in groups mapped to job functions (developer, DBA, auditor, admin).
2. **Workload access** — EC2/ECS/Lambda assume roles to reach S3, DynamoDB, SQS with no stored secrets.
3. **Cross-account access** — a central security account assumes a read-only audit role in every workload account.
4. **Federation** — SSO from a corporate identity provider; zero IAM users for humans (the modern best practice).
5. **CI/CD** — a build pipeline assumes a deploy role scoped to one CloudFormation stack.
6. **Delegated administration** — a team lead can create users, but only within a permissions boundary.
7. **Break-glass** — a rarely used, heavily audited, MFA-protected emergency admin role.

### 2.4 Industry examples

| Sector | IAM pattern in production |
|---|---|
| Banking (core banking on AWS) | Separate accounts per environment; no IAM users for humans at all — federated SSO only; every workload uses a role with a permissions boundary; `Deny` on `kms:Decrypt` outside approved VPC endpoints |
| E-commerce | Lambda functions each get their own minimal execution role; a "checkout" role cannot read the "analytics" bucket |
| Hospital / health data | Resource-based policies on S3 buckets denying any request where `aws:SecureTransport` is `false`; ABAC via tags so a clinician role only reads records tagged with their own department |
| University | Groups per faculty; student lab accounts limited by permissions boundary to `t3.micro` instances in one region; auto-expiring roles for research grants |
| SaaS multi-tenant | One IAM role per tenant, with `Condition` on a session tag so tenant A's session mathematically cannot address tenant B's prefix |

### 2.5 What IAM is *not*

| Not IAM | Actual service |
|---|---|
| Customer/end-user sign-up and login for your app | **Amazon Cognito** |
| Storing application secrets and DB passwords | **Secrets Manager** / **SSM Parameter Store** |
| Encryption key management | **KMS** |
| Network-level access control | **Security Groups**, **NACLs** |
| Recording who did what | **CloudTrail** (IAM supplies the identity; CloudTrail records it) |
| Org-wide guardrails across many accounts | **AWS Organizations SCPs** (IAM enforces the intersection) |

!!! note "Recap — §2"
    IAM is a global, free, deny-by-default authorisation engine. It replaces shared root credentials with per-identity principals, replaces hard-coded keys with temporary role credentials, and scales permission management through groups and managed policies.

---

## 3. Internal Architecture

### 3.1 The IAM object model

```
                     ┌──────────────────────────────────────────────────────┐
                     │            AWS ACCOUNT  (000000000000)                │
                     │            ── the hard security boundary ──           │
                     │                                                       │
   ┌── PRINCIPALS ───┴────────────────┐        ┌── POLICIES ──────────────┐   │
   │                                  │        │                          │   │
   │  Root user  (email + password)   │        │  AWS managed policy      │   │
   │    └ cannot be restricted by IAM │        │    (Amazon authors it)   │   │
   │                                  │        │                          │   │
   │  IAM User  ──────┐               │        │  Customer managed policy │   │
   │   ├ login profile│  (console pwd)│        │    ├ up to 5 versions    │   │
   │   ├ access keys  │  (2 max)      │◄──attach──   └ one is "default"   │   │
   │   ├ MFA device   │               │        │                          │   │
   │   ├ inline policy│               │        │  Inline policy           │   │
   │   ├ tags         │               │        │    └ embedded in exactly │   │
   │   └ permissions boundary ────────┼──ceiling──   one principal        │   │
   │        │                         │        │                          │   │
   │  IAM Group  (users only, no nest)│        └──────────────────────────┘   │
   │   ├ members: user, user, ...     │                                       │
   │   └ attached + inline policies   │        ┌── RESOURCES ─────────────┐   │
   │                                  │        │  S3 bucket               │   │
   │  IAM Role  ──────┐               │        │   └ bucket policy ◄──────┼───┤ resource-
   │   ├ TRUST policy │ who may assume│        │  KMS key                 │   │ based
   │   ├ permissions policies         │        │   └ key policy           │   │ policy
   │   ├ max session duration         │        │  SQS queue / SNS topic   │   │
   │   ├ permissions boundary         │        │   └ access policy        │   │
   │   └ instance profile (EC2 only)  │        │  IAM role                │   │
   │                                  │        │   └ trust policy         │   │
   └──────────────────────────────────┘        └──────────────────────────┘   │
                     │                                                        │
                     └────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                     ┌──────────────────────────────────┐
                     │  AWS STS (Security Token Service)│
                     │  AssumeRole / AssumeRoleWithSAML │
                     │  AssumeRoleWithWebIdentity       │
                     │  GetFederationToken/GetSessionToken
                     │  GetCallerIdentity               │
                     │        ↓ returns                 │
                     │  AccessKeyId (ASIA...)           │
                     │  SecretAccessKey                 │
                     │  SessionToken       + Expiration │
                     └──────────────────────────────────┘
```

### 3.2 The lifecycle of one authenticated API call

```
  aws s3 cp file.txt s3://dnb-statements-dev/f.txt
            │
            │ 1. CLI resolves credentials
            │    (env vars → ~/.aws/credentials → SSO → instance metadata IMDS)
            ▼
  ┌─────────────────────────────────────────────┐
  │ 2. SigV4 SIGNING (client side)              │
  │    canonical request + secret key → HMAC    │
  │    Authorization: AWS4-HMAC-SHA256 ...      │
  └─────────────────────────────────────────────┘
            │  HTTPS
            ▼
  ┌─────────────────────────────────────────────┐
  │ 3. AUTHENTICATION  (who are you?)           │
  │    service looks up AccessKeyId → principal │
  │    recomputes signature; mismatch →         │
  │    SignatureDoesNotMatch / InvalidClientTokenId
  └─────────────────────────────────────────────┘
            │  identity established
            ▼
  ┌─────────────────────────────────────────────┐
  │ 4. BUILD REQUEST CONTEXT                    │
  │    action  = s3:PutObject                   │
  │    resource= arn:aws:s3:::dnb-statements-dev/f.txt
  │    principal = arn:aws:iam::000000000000:user/dnb-dev-alice
  │    condition keys: aws:SourceIp, aws:SecureTransport,
  │                    aws:PrincipalTag/*, s3:x-amz-acl, ...
  └─────────────────────────────────────────────┘
            │
            ▼
  ┌─────────────────────────────────────────────┐
  │ 5. AUTHORISATION  (are you allowed?)        │
  │    ← the evaluation pipeline in §3.3        │
  └─────────────────────────────────────────────┘
            │
      Allow │                    │ Deny
            ▼                    ▼
     action performed     AccessDenied (403)
            │                    │
            └────────┬───────────┘
                     ▼
             6. CloudTrail event
                (identity + action + verdict)
```

!!! note "Where Floci fits in this diagram"
    Steps 1, 2, 4 and 6 are client-side or plumbing and behave normally. Step 3 (SigV4 validation) is implemented in Floci for a subset of services. **Step 5 is the step you cannot assume.** Floci is documented as supporting "full IAM authentication and SigV4 validation" for services such as Lambda, EC2, ECS, RDS, ElastiCache, EKS, MSK, OpenSearch, ECR and CodeBuild — but you must confirm behaviour for your build with the harness in §0.5.2 before treating a local `Allow` as meaningful.

### 3.3 Policy evaluation logic — the decision pipeline

This flowchart is examinable. Memorise it.

```
                      REQUEST arrives with full context
                                   │
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ Is the principal the ROOT user of the account │
          │ that owns the resource?                       │──yes──► ALLOW
          │ (SCPs and resource policies can still deny)   │         (root cannot be
          └──────────────────────────────────────────────┘          restricted by IAM
                                   │ no                              identity policies)
                                   ▼
          ╔══════════════════════════════════════════════╗
          ║ 1. EXPLICIT DENY anywhere?                   ║
          ║    identity | resource | boundary | session  ║──yes──► ★ DENY ★  (final,
          ║    | SCP | RCP                               ║          unappealable)
          ╚══════════════════════════════════════════════╝
                                   │ no
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ 2. Organizations SCP allows the action?      │──no───► DENY
          │    (if the account is in an Organization)    │
          └──────────────────────────────────────────────┘
                                   │ yes / not applicable
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ 3. Resource-control policy (RCP) allows?     │──no───► DENY
          └──────────────────────────────────────────────┘
                                   │ yes / n/a
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ 4. Permissions boundary allows?              │──no───► DENY
          │    (attached to the user or role)            │
          └──────────────────────────────────────────────┘
                                   │ yes / n/a
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ 5. Session policy allows?                    │──no───► DENY
          │    (only present for assumed-role/federated  │
          │     sessions created with --policy)          │
          └──────────────────────────────────────────────┘
                                   │ yes / n/a
                                   ▼
          ┌──────────────────────────────────────────────┐
          │ 6. Is there an explicit ALLOW in either      │
          │    (a) an identity-based policy, or          │──no───► DENY
          │    (b) a resource-based policy?              │        (implicit / default deny)
          └──────────────────────────────────────────────┘
                                   │ yes
                                   ▼
                                 ALLOW
```

**Three rules that follow from the diagram**

| Rule | Consequence |
|---|---|
| **Explicit deny always wins** | You cannot "out-allow" a `Deny`. Used for hard guardrails (e.g. deny all actions outside `ap-south-1`). |
| **Implicit deny is the default** | Absence of an `Allow` is a deny. New users have zero permissions. |
| **Boundaries and session policies only *filter*; they never *grant*** | A permissions boundary that allows `s3:*` grants nothing on its own. Effective permissions = identity policy ∩ boundary ∩ session policy. |

**Same-account vs cross-account (a classic exam trap)**

| Scenario | Requirement |
|---|---|
| Principal and resource in the **same** account | Identity policy **OR** resource policy allows → allowed |
| Principal and resource in **different** accounts | Identity policy in the principal's account **AND** resource policy in the resource's account must **both** allow |

```
   SAME ACCOUNT (OR)                 CROSS ACCOUNT (AND)
   identity ──┐                      identity(A) ──┐
              ├── Allow                            ├── Allow (both required)
   resource ──┘                      resource(B) ──┘
```

### 3.4 Effective-permissions Venn model

```
        identity-based policies (the grant)
        ┌─────────────────────────────────┐
        │                                 │
        │   ┌──────────────────────┐      │
        │   │  permissions boundary│      │
        │   │  ┌───────────────┐   │      │
        │   │  │ session policy│   │      │
        │   │  │  ███████████  │◄──┼──────┼── EFFECTIVE PERMISSIONS
        │   │  │  ███████████  │   │      │   = the intersection
        │   │  └───────────────┘   │      │
        │   └──────────────────────┘      │
        └─────────────────────────────────┘

        …and then any explicit Deny punches a hole
        straight through all three layers.
```

### 3.5 Anatomy of an ARN

Every IAM decision is expressed in terms of ARNs. Learn to read them.

```
arn : aws : iam :: 000000000000 : role / dnb/dev/ dnb-dev-app-role
 │     │     │  │       │           │       │          │
 │     │     │  │       │           │       │          └── resource id (name)
 │     │     │  │       │           │       └── path (optional, / by default)
 │     │     │  │       │           └── resource type
 │     │     │  │       └── 12-digit account id
 │     │     │  └── REGION IS EMPTY: IAM is a global service
 │     │     └── service namespace
 │     └── partition (aws | aws-cn | aws-us-gov)
 └── literal
```

| ARN | Object |
|---|---|
| `arn:aws:iam::000000000000:root` | The account (or its root user) |
| `arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-alice` | User at a path |
| `arn:aws:iam::000000000000:group/dnb-developers` | Group |
| `arn:aws:iam::000000000000:role/dnb-dev-app-role` | Role |
| `arn:aws:iam::000000000000:policy/dnb-s3-statements-read` | Customer managed policy |
| `arn:aws:iam::aws:policy/ReadOnlyAccess` | AWS managed policy (note `aws` in the account field) |
| `arn:aws:iam::000000000000:instance-profile/dnb-dev-app-profile` | Instance profile |
| `arn:aws:sts::000000000000:assumed-role/dnb-dev-app-role/session-1` | An **assumed-role session** — note service `sts`, not `iam` |
| `arn:aws:sts::000000000000:federated-user/carol` | A federated user session |

!!! warning "Assumed-role ARNs are the #1 cause of broken policies"
    When a role is assumed, the caller's ARN is **not** `arn:aws:iam::…:role/X`. It is `arn:aws:sts::…:assumed-role/X/<session-name>`. A `Condition` on `aws:PrincipalArn` or a bucket policy `Principal` written against the `iam:role` form will still match for `Principal` (AWS resolves it), but a *string comparison* against the caller ARN will not. Always print `aws sts get-caller-identity` before writing conditions.

!!! note "Recap — §3"
    IAM is an object graph (principals, policies, resources) plus a deterministic evaluation pipeline. Explicit deny wins; implicit deny is the default; boundaries and session policies intersect rather than grant. Cross-account access requires an allow on both sides.

---
## 4. Component-by-Component Deep Dive

Each subsection opens with a **Floci support tier** banner. Confirm every banner against your own `support-matrix.tsv` from §0.5.1 — the tiers below describe a typical build, not a guarantee for yours.

---

### 4.1 The AWS Account and the Root User

**Floci support:** ⚠️ *Partial.* Floci runs as a single synthetic account (conventionally `000000000000`) with fixed dummy credentials. There is no real root user, no account email, no billing, and no root-vs-IAM distinction to enforce. Root-user policy is therefore **conceptual** in this module.

| Aspect | Detail |
|---|---|
| **Purpose** | The account is the hard isolation boundary in AWS. Two accounts share nothing unless you explicitly bridge them. |
| **Root user** | Created with the account, identified by email address, holds **unrestricted, unrestrictable** power. IAM identity policies cannot limit it. |
| **Lifecycle** | Exists for the life of the account; cannot be deleted while the account exists. |
| **Relationships** | Owns all IAM entities and resources. Is the only principal able to perform ~10 "root-only" tasks (close the account, change support plan, restore an invalidated bucket policy, register as a seller, etc.). |
| **Security** | Enable hardware MFA, delete all root access keys, never use root for day-to-day work, set a strong unique password, use the account contact for alerts only. |
| **Limitations** | Cannot be given a permissions boundary; SCPs do not apply to the management account's root; cannot be federated. |
| **Best practice** | Lock it in a safe. Create an IAM admin (or better, federated admin role) on day one and never sign in as root again. |

```
account 000000000000 ─── root user  (unrestrictable)
        │                    │ used ONCE to bootstrap
        ├── IAM admin role ◄─┘
        ├── IAM users / groups / roles
        └── all resources (S3, EC2, …)
```

**Discovering your account identity in Floci**

```bash
aws sts get-caller-identity
```

```json
{
    "UserId": "AKIAIOSFODNN7EXAMPLE",
    "Account": "000000000000",
    "Arn": "arn:aws:iam::000000000000:root"
}
```

```bash
# Cache the account id — every policy file in this module uses it
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "$ACCOUNT_ID"
```

!!! warning "Your Floci session is effectively root"
    The `test`/`test` credentials Floci exports behave as an all-powerful account principal. That is *why* you must never conclude "IAM allowed it" from a successful command run under the default profile — you were running as the equivalent of root. All enforcement testing must be done under a **separate named profile** backed by an IAM user's access key (Lab 5) or an assumed role (Lab 6).

---

### 4.2 Paths, Names, and Tags

**Floci support:** ✅ names and paths; ⚠️ tags (stored, but rarely honoured by condition evaluation).

| Aspect | Detail |
|---|---|
| **Purpose** | Paths give IAM a virtual folder hierarchy (`/dnb/dev/`). Tags give arbitrary key–value metadata used for cost allocation and **ABAC**. |
| **Configuration** | `--path /dnb/dev/` at creation. `--tags Key=…,Value=…` at creation or via `tag-user`/`tag-role`. |
| **Lifecycle** | **Role** paths are fixed at create time. **User** and **group** paths can be changed later (`update-user --new-path`, `update-group --new-path`). Tags mutable at any time; max 50 per entity. |
| **Relationships** | Paths appear inside ARNs, so a policy can grant `iam:*` on `arn:aws:iam::123:user/dnb/dev/*` — path-scoped delegation. Tags feed `aws:PrincipalTag/*`, `aws:ResourceTag/*`, `aws:RequestTag/*`, `aws:TagKeys`. |
| **Security** | ABAC via tags scales far better than writing one policy per resource, but a principal who can *edit* tags can escalate privilege — always deny `iam:TagRole`/`iam:UntagRole` on security-relevant tags. |
| **Limitations** | Names: 1–64 chars for users and roles, 1–128 for groups; character set `[\w+=,.@-]`. Names are **case-insensitive for uniqueness** (`Alice` and `alice` collide). Paths ≤ 512 chars, must start and end with `/`. |
| **Naming convention (this module)** | `dnb-<env>-<function>[-<type>]`, path `/dnb/<env>/` |

```bash
# Path-scoped listing: show only development-environment users
aws iam list-users --path-prefix /dnb/dev/ \
  --query 'Users[].[UserName,Arn]' --output table
```

!!! tip "Why paths matter for delegation"
    A policy allowing `iam:CreateUser` on `arn:aws:iam::*:user/dnb/dev/*` lets a team lead create developers but **not** users under `/dnb/prod/`. This is a path-scoped permissions model and it is a common real-world design.

---

### 4.3 IAM Users

**Floci support:** ✅ create/get/list/update/delete/tag.

| Aspect | Detail |
|---|---|
| **Purpose** | A persistent identity for **one human** (or, legacy, one application). Holds long-term credentials. |
| **Configuration** | Name, path, tags, optional permissions boundary. Up to 2 access keys, 1 login profile, up to 8 MFA devices, 10 attached managed policies (default quota, adjustable to 20), and membership of up to 10 groups. There is **no count limit on inline policies** — the constraint is an aggregate 2 048-character budget per user. |
| **Lifecycle** | `CreateUser` → attach permissions (ideally via group) → optionally create credentials → *use* → rotate keys → detach/delete children → `DeleteUser`. **`DeleteUser` fails while dependents exist.** |
| **Relationships** | ⊂ groups; ← attached managed policies; ⊂ inline policies; → access keys, login profile, MFA, signing certs, SSH keys, service-specific credentials; ⊤ permissions boundary. |
| **Security** | Long-lived credentials are the highest-risk artefact in AWS. Prefer roles/federation. If users are unavoidable: MFA mandatory, rotate keys ≤ 90 days, no keys for console-only staff. |
| **Limitations** | Default quota 5 000 users per account — a hint that users are not the intended scaling mechanism for humans. Users are global; no per-region users. |
| **Best practice** | *Never* attach a policy directly to a user. Attach to a group. This makes onboarding/offboarding a one-line change and makes audit trivial. |
| **Common mistakes** | Creating a user per application (use a role); leaving `AdministratorAccess` attached "temporarily"; sharing one user between two people; forgetting that deleting a user does **not** revoke already-issued STS sessions derived from it. |

**Deletion dependency order (memorise — this is Debugging Challenge 1)**

```
DeleteUser  requires, in order:
  1. remove from all groups            iam remove-user-from-group
  2. delete all access keys            iam delete-access-key
  3. delete login profile              iam delete-login-profile
  4. deactivate + delete MFA devices   iam deactivate-mfa-device / delete-virtual-mfa-device
  5. delete inline policies            iam delete-user-policy
  6. detach managed policies           iam detach-user-policy
  7. delete signing certs / SSH keys / Git credentials / service-specific creds
  8. THEN  iam delete-user

  (Tidy-up, not a blocker: iam delete-user-permissions-boundary. A boundary does
   NOT cause DeleteConflict, but leaving one behind on a recreated name is untidy.)
```

---

### 4.4 IAM Groups

**Floci support:** ✅ create/get/list/delete, add/remove user, attach/detach and inline policies.

| Aspect | Detail |
|---|---|
| **Purpose** | A container of users used **solely** to attach permissions to many identities at once. |
| **Configuration** | Name, path, attached managed policies, inline policies. |
| **Lifecycle** | `CreateGroup` → attach policies → `AddUserToGroup` … → `RemoveUserFromGroup` → detach policies → `DeleteGroup`. |
| **Relationships** | Contains users only. |
| **Security** | Model groups on **job functions**, not on projects or teams — job functions change far less often. |
| **Limitations** | **Groups cannot be nested.** **Groups are not principals** — you cannot write `"Principal": {"AWS": "arn:aws:iam::123:group/devs"}` in a trust policy or bucket policy, and a group cannot assume a role. Max 300 groups per account; a user may belong to 10. |
| **Best practice** | `dnb-developers`, `dnb-auditors`, `dnb-dbadmins`, `dnb-admins`. One group = one coherent set of duties. |
| **Common mistakes** | Trying to use a group as a `Principal` (silently invalid / `MalformedPolicyDocument`); expecting nested groups; putting *both* an allow-all and a deny in the same group and being surprised the deny wins. |

```
  dnb-developers ──┬── dnb-dev-alice
      │            └── dnb-dev-bob
      └── attached: dnb-s3-statements-read
                    dnb-dev-baseline

  A group is NOT a principal:
      ✗  "Principal": { "AWS": "…:group/dnb-developers" }   ← invalid
      ✓  "Principal": { "AWS": "…:user/dnb-dev-alice"   }
      ✓  "Principal": { "AWS": "…:role/dnb-dev-app-role" }
```

---

### 4.5 Access Keys (long-term credentials)

**Floci support:** ✅ create/list/update(status)/delete. ⚠️ `get-access-key-last-used` may return placeholder data. ⚠️ Whether an *inactive* key is actually rejected on subsequent calls must be probed.

| Aspect | Detail |
|---|---|
| **Purpose** | Programmatic authentication: an `AccessKeyId` (public, `AKIA…`) plus a `SecretAccessKey` (private) used to compute the SigV4 signature. |
| **Configuration** | `iam create-access-key --user-name X`. Status `Active` \| `Inactive`. |
| **Lifecycle** | Create → distribute → use → *(rotate: create 2nd key → update apps → mark 1st `Inactive` → verify → delete 1st)* → delete. |
| **Relationships** | Belong to exactly one IAM user. Roles never have access keys — they get temporary ones from STS. |
| **Security** | The secret is shown **exactly once**, at creation. It cannot be retrieved later. If lost, delete and recreate. Never commit to Git, never bake into an AMI or container image, never paste into Slack. |
| **Limitations** | Max **2 per user** — deliberately, so that zero-downtime rotation is possible and hoarding is not. |
| **Best practice** | The four-phase rotation above. Automate with a scheduled job. Alarm on keys older than 90 days. Prefer eliminating keys entirely via roles/SSO. |
| **Common mistakes** | Deleting the old key before verifying the new one works (outage); rotating by deleting-then-creating (outage); storing keys in `~/.aws/credentials` on a laptop with no disk encryption. |

**Key prefixes — know them for the exam and for triage**

| Prefix | Credential type |
|---|---|
| `AKIA…` | Long-term IAM user access key |
| `ASIA…` | **Temporary** STS credential (always accompanied by a session token) |
| `ABIA…`, `ACCA…` | Context-specific / service credentials |

!!! tip "Instant triage heuristic"
    If a credential starts with `ASIA` and there is no `AWS_SESSION_TOKEN` set, the call **will** fail with `InvalidClientTokenId`. Temporary credentials are a *triple*, not a pair.

---

### 4.6 Login Profiles and the Account Password Policy

**Floci support:** ⚠️ `create/get/update/delete-login-profile` typically supported as data storage — but Floci has **no console**, so a login profile can never actually be used to sign in. ❌/⚠️ `get/update/delete-account-password-policy` — probe it; if `get` returns `NoSuchEntity` the operation exists but no policy is set. Password *complexity enforcement* is almost certainly not evaluated locally.

| Aspect | Detail |
|---|---|
| **Purpose** | A login profile is a user's console password. The account password policy sets complexity/rotation rules for **all** login profiles in the account. |
| **Configuration (profile)** | `--password`, `--password-reset-required` (forces change on first sign-in). |
| **Configuration (policy)** | `--minimum-password-length`, `--require-symbols`, `--require-numbers`, `--require-uppercase-characters`, `--require-lowercase-characters`, `--allow-users-to-change-password`, `--max-password-age`, `--password-reuse-prevention`, `--hard-expiry`. |
| **Lifecycle** | Create profile with a temporary password + reset-required → user changes it → periodic expiry per policy → delete on offboarding. |
| **Relationships** | One profile per user. The account policy is a singleton account-level object. |
| **Security** | `--hard-expiry` locks a user out rather than letting them self-serve a reset — powerful but a support burden. Passwords are irrelevant if you federate; that's the point of federating. |
| **Limitations** | Password policy does not apply to the **root** user. Length 6–128 (AWS floor); reuse prevention 1–24. |
| **Best practice (CIS AWS Foundations Benchmark)** | length ≥ 14, all four character classes, reuse prevention 24, and prefer SSO so that no IAM passwords exist at all. |

```bash
# CIS-aligned policy (Track A: verify the object is stored; enforcement is AWS-side)
aws iam update-account-password-policy \
  --minimum-password-length 14 \
  --require-symbols --require-numbers \
  --require-uppercase-characters --require-lowercase-characters \
  --allow-users-to-change-password \
  --max-password-age 90 \
  --password-reuse-prevention 24

aws iam get-account-password-policy
```

```json
{
    "PasswordPolicy": {
        "MinimumPasswordLength": 14,
        "RequireSymbols": true,
        "RequireNumbers": true,
        "RequireUppercaseCharacters": true,
        "RequireLowercaseCharacters": true,
        "AllowUsersToChangePassword": true,
        "ExpirePasswords": true,
        "MaxPasswordAge": 90,
        "PasswordReusePrevention": 24,
        "HardExpiry": false
    }
}
```

!!! note "Conceptual-only in Floci"
    In real AWS, `create-login-profile --password 'weak'` is **rejected** with `PasswordPolicyViolation` when the account policy forbids it. In Floci the weak password is very likely accepted. Record this as a divergence; do not conclude the policy "doesn't work".

---

### 4.7 Policies I — Types and Storage

**Floci support:** ✅ `create-policy`, `get-policy`, `list-policies`, `attach/detach-*-policy`, `put/get/delete-*-policy` (inline), `create-policy-version`, `set-default-policy-version`, `list-policy-versions`, `delete-policy-version`, `list-entities-for-policy`. ⚠️ AWS **managed** policies (`arn:aws:iam::aws:policy/…`) may only be partially seeded — probe before relying on `ReadOnlyAccess` etc.

There are exactly six ways a policy can enter the evaluation pipeline:

| # | Policy type | Attached to | Grants? | Floci |
|---|---|---|---|---|
| 1 | **Identity-based, AWS managed** | user / group / role | Yes | ⚠️ subset seeded |
| 2 | **Identity-based, customer managed** | user / group / role | Yes | ✅ |
| 3 | **Identity-based, inline** | exactly one user / group / role | Yes | ✅ |
| 4 | **Resource-based** (bucket policy, key policy, queue policy, **trust policy**) | a resource | Yes (and can grant cross-account) | ⚠️ varies by service; trust policies ✅ |
| 5 | **Permissions boundary** | user / role | **No** — filters only | ⚠️ stored; enforcement unlikely |
| 6 | **Session policy** | passed at `AssumeRole --policy` | **No** — filters only | ⚠️ accepted; enforcement unlikely |

Plus two org-level types that IAM *intersects* with but does not own: **SCPs** and **RCPs** (AWS Organizations) — ❌ in Floci, conceptual only.

#### Managed vs inline — the decision table

| Criterion | Managed (customer) | Inline |
|---|---|---|
| Reusable across principals | ✅ yes | ❌ one principal only |
| Versioned with rollback | ✅ up to 5 versions | ❌ no versions |
| Deleted when principal is deleted | ❌ survives | ✅ deleted with it |
| Central audit (`list-entities-for-policy`) | ✅ | ❌ must enumerate principals |
| Size limit | 6 144 chars | user 2 048 / group 5 120 / role 10 240 chars total |
| Right choice for | virtually everything | a one-off exception that **must never** be reused, and must vanish with the principal |

!!! tip "Exam-ready answer"
    "Use customer managed policies by default for reuse, versioning and central auditability; use inline policies only for a strict one-to-one relationship you never want inherited elsewhere — for example a single break-glass role's unique grant."

#### Policy version lifecycle

```
   create-policy                 → v1 (default)
   create-policy-version --set-as-default  → v2 (default), v1 retained
   create-policy-version                   → v3 (NOT default)
   set-default-policy-version --version-id v1   ← instant rollback
   delete-policy-version --version-id v3

   ┌─────────────────────────────────────────────┐
   │ Max 5 versions. The 6th create FAILS with   │
   │ LimitExceeded until you delete one.         │
   │ You cannot delete the DEFAULT version.      │
   │ Deleting the POLICY deletes all versions —  │
   │ but only after it is detached from every    │
   │ principal (else DeleteConflict).            │
   └─────────────────────────────────────────────┘
```

---

### 4.8 Policies II — The Policy Language

**Floci support:** ✅ documents are stored and returned verbatim; ⚠️ `Condition` evaluation is the least likely part to be enforced locally. ❌ `iam simulate-principal-policy` / `simulate-custom-policy` are frequently absent — probe them, because they are your best Track-A verification tool when present.

#### Grammar

```json
{
  "Version": "2012-10-17",
  "Id": "optional-policy-id",
  "Statement": [
    {
      "Sid": "AllowStatementReadInDev",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::000000000000:role/dnb-dev-app-role" },
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": {
        "StringEquals": { "aws:PrincipalTag/Environment": "dev" },
        "Bool": { "aws:SecureTransport": "true" }
      }
    }
  ]
}
```

| Element | Required? | Notes |
|---|---|---|
| `Version` | Yes, in practice | **Must be the literal string `"2012-10-17"`.** Omitting it silently defaults to `2008-10-17`, which **disables policy variables** — a classic silent failure. |
| `Id` | No | Free-form policy identifier; some services reject it. |
| `Sid` | No, but do it | Statement ID. Makes `simulate-principal-policy` output and audit reviews readable. Must be unique within the policy. |
| `Effect` | Yes | `Allow` \| `Deny`. |
| `Principal` | Only in **resource-based** policies | Illegal in identity-based policies (`MalformedPolicyDocument`). |
| `NotPrincipal` | No | Extremely error-prone; avoid. |
| `Action` / `NotAction` | One of them | `service:Operation`, case-insensitive matching but conventionally camelCase. |
| `Resource` / `NotResource` | Required in identity policies | ARN(s) or `"*"`. Some actions have no resource (e.g. `ec2:DescribeInstances`) and require `"*"`. |
| `Condition` | No | The mechanism for least privilege. |

#### Wildcards

| Pattern | Matches |
|---|---|
| `"s3:*"` | every S3 action |
| `"s3:Get*"` | `GetObject`, `GetBucketPolicy`, … |
| `"*"` | every action of every service — **only ever correct for `AdministratorAccess`** |
| `"arn:aws:s3:::dnb-statements-dev/*"` | every **object** in the bucket |
| `"arn:aws:s3:::dnb-statements-dev"` | the **bucket itself** (needed for `ListBucket`) |
| `?` | exactly one character |

!!! danger "The single most common S3+IAM bug in the world"
    `s3:ListBucket` acts on the **bucket ARN**. `s3:GetObject` acts on the **object ARN** (`bucket/*`). If you list only one of the two ARNs, half your operations fail. You need **both** entries in `Resource`.

#### `NotAction` — allow-everything-except

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAllExceptIamAndOrganizations",
      "Effect": "Allow",
      "NotAction": ["iam:*", "organizations:*", "account:*"],
      "Resource": "*"
    }
  ]
}
```

!!! warning "`NotAction` with `Allow` is dangerous"
    It grants every *future* AWS action too — including services that do not exist yet. `Deny` + `NotAction` is the safer idiom for guardrails ("deny everything that is not one of these approved actions"). Prefer explicit allow-lists in production.

#### Condition operators

| Family | Operators | Typical use |
|---|---|---|
| String | `StringEquals`, `StringNotEquals`, `StringEqualsIgnoreCase`, `StringLike`, `StringNotLike` | tag matching, ARN patterns |
| Numeric | `NumericEquals`, `NumericLessThan`, `NumericGreaterThanEquals`, … | `s3:max-keys` |
| Date | `DateLessThan`, `DateGreaterThan` | temporary contractor access windows |
| Boolean | `Bool` | `aws:SecureTransport`, `aws:MultiFactorAuthPresent` |
| IP | `IpAddress`, `NotIpAddress` | `aws:SourceIp` corporate CIDR |
| ARN | `ArnEquals`, `ArnLike`, `ArnNotLike` | `aws:SourceArn` |
| Null | `Null` | "was this key present at all?" |
| Set modifiers | `ForAllValues:`, `ForAnyValue:` | multi-valued keys such as `aws:TagKeys` |
| Suffix | `…IfExists` | apply the test only when the key is present |

#### Globally available condition keys worth memorising

| Key | Meaning |
|---|---|
| `aws:PrincipalArn` | ARN of the calling principal |
| `aws:PrincipalAccount`, `aws:PrincipalOrgID` | caller's account / AWS Organization |
| `aws:PrincipalTag/<k>` | tag on the calling user/role (**ABAC subject**) |
| `aws:RequestTag/<k>`, `aws:TagKeys` | tags being *submitted* in this request |
| `aws:ResourceTag/<k>` | tag on the target resource (**ABAC object**) |
| `aws:SourceIp` | caller's public IP (**not** valid via VPC endpoints — use `aws:VpcSourceIp`) |
| `aws:SourceVpce`, `aws:SourceVpc` | VPC endpoint / VPC of the request |
| `aws:SecureTransport` | was TLS used |
| `aws:MultiFactorAuthPresent`, `aws:MultiFactorAuthAge` | MFA on this session |
| `aws:CurrentTime`, `aws:EpochTime` | request timestamp |
| `aws:userid`, `aws:username` | caller id / user name |
| `aws:RequestedRegion` | region being addressed (region guardrails) |
| `aws:ViaAWSService`, `aws:CalledVia` | request made by a service on your behalf |

#### Policy variables

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "HomeFolderOnly",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::dnb-home-dev/${aws:username}/*"
    },
    {
      "Sid": "ListOnlyOwnPrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::dnb-home-dev",
      "Condition": {
        "StringLike": { "s3:prefix": ["${aws:username}/*"] }
      }
    }
  ]
}
```

One policy, N users, each confined to their own prefix. This is the canonical "home directory" pattern and a favourite exam question.

!!! danger "Policy variables require `"Version": "2012-10-17"`"
    Under the legacy `2008-10-17` version, `${aws:username}` is treated as a **literal string**, so the policy grants access to a folder literally named `${aws:username}`. Nothing errors. Everything silently fails. Always set the Version.

#### Two ABAC examples

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AbacSameEnvironmentOnly",
      "Effect": "Allow",
      "Action": ["ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/Environment": "${aws:PrincipalTag/Environment}"
        }
      }
    }
  ]
}
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyOutsideApprovedRegions",
      "Effect": "Deny",
      "NotAction": ["iam:*", "sts:*", "organizations:*", "cloudfront:*", "route53:*", "support:*"],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": ["us-east-1", "ap-south-1"]
        }
      }
    }
  ]
}
```

The second is a **guardrail**: note the `NotAction` exemptions for global services, whose endpoints live in `us-east-1` and which would otherwise break.

!!! note "Recap — §4.7–4.8"
    Six policy types feed one pipeline. `Version` must be `2012-10-17`. Identity policies must not contain `Principal`; resource policies must. S3 needs both bucket and object ARNs. Conditions are where least privilege actually happens — and are the part your emulator is least likely to enforce.

---

### 4.9 Resource-Based Policies and Trust Policies

**Floci support:** ✅ role trust policies (`create-role --assume-role-policy-document`, `update-assume-role-policy`). ⚠️ S3 bucket policies, KMS key policies, SQS/SNS access policies — the *put/get* calls generally work; whether the policy is *evaluated* varies by service.

| Aspect | Detail |
|---|---|
| **Purpose** | Attach permissions to the **resource** instead of the identity. The only way to grant access to a principal in another account without creating an identity in yours. |
| **Distinguishing feature** | Requires a `Principal` element. |
| **Trust policy** | The resource-based policy *of an IAM role*. It answers "**who may assume me?**", never "what may I do?". |
| **Lifecycle** | Created with the resource (or with `create-role`), updated in place, deleted with the resource. |
| **Security** | `"Principal": {"AWS": "*"}` on a role trust policy or bucket policy is a critical finding — it makes the resource world-readable/assumable. Always pair a third-party trust with `sts:ExternalId`. |
| **Limitations** | Not every service supports them (e.g. EC2 instances do not). Bucket policy max 20 KB. |
| **Best practice** | Prefer identity-based policies for your own account; reserve resource-based policies for cross-account and for service principals. |

**Principal element forms**

```json
{ "Principal": { "AWS": "arn:aws:iam::000000000000:user/dnb-dev-alice" } }
{ "Principal": { "AWS": "arn:aws:iam::000000000000:role/dnb-dev-app-role" } }
{ "Principal": { "AWS": "000000000000" } }
{ "Principal": { "AWS": "arn:aws:iam::000000000000:root" } }
{ "Principal": { "Service": "ec2.amazonaws.com" } }
{ "Principal": { "Service": ["lambda.amazonaws.com", "ecs-tasks.amazonaws.com"] } }
{ "Principal": { "Federated": "cognito-identity.amazonaws.com" } }
{ "Principal": { "Federated": "arn:aws:iam::000000000000:saml-provider/DrukAD" } }
{ "Principal": { "CanonicalUser": "79a59df900b949e55d96a1e698fb…" } }
{ "Principal": "*" }
```

!!! warning "`"AWS": "000000000000"` means *the whole account*"
    It delegates the decision to the **other** account's administrators: any principal in account `000000000000` that is *also* granted `sts:AssumeRole` by its own identity policy can assume your role. That is intentional and correct for cross-account design, but you must understand you are trusting their IAM hygiene, not a specific person.

**Identity-based vs resource-based, side by side**

```
  IDENTITY-BASED                        RESOURCE-BASED
  attached to:  user/group/role         attached to:  bucket/key/queue/role
  answers:      "what can I do?"        answers:      "who can touch me?"
  Principal:    ILLEGAL                 Principal:    REQUIRED
  cross-acct:   no (needs both sides)   cross-acct:   yes, this is the mechanism
  example:      dnb-s3-statements-read  example:      bucket policy, trust policy
```

---

### 4.10 IAM Roles and AWS STS

**Floci support:** ✅ `create-role`, `get-role`, `list-roles`, `update-role`, `update-assume-role-policy`, `delete-role`, `attach/detach-role-policy`, `put/get/delete-role-policy`, `tag-role`. ✅ `sts assume-role`, `sts get-caller-identity`, `sts get-session-token`; `assume-role-with-web-identity`, `assume-role-with-saml`, `get-federation-token` are listed as implemented (7 STS ops). ⚠️ whether the **trust policy is actually evaluated** before issuing credentials, and whether `--duration-seconds` is honoured, must be probed.

| Aspect | Detail |
|---|---|
| **Purpose** | An identity with permissions but **no long-term credentials**, assumable by a trusted principal. The correct way to give permissions to applications, services, other accounts, and (via federation) humans. |
| **Two policies, always** | ① **Trust policy** (resource-based) = who may assume. ② **Permissions policies** (identity-based) = what the session may do. Forgetting one is the #1 role bug. |
| **Configuration** | `--assume-role-policy-document`, `--max-session-duration` (3 600–43 200 s), `--description`, `--path`, `--tags`, `--permissions-boundary`. |
| **Lifecycle** | `CreateRole` (with trust) → attach permissions → assume → session expires → (rotate policies) → detach children → `DeleteRole`. |
| **Relationships** | Trusted by principals; wraps into an **instance profile** for EC2; referenced by Lambda as `--role`; by ECS as task/execution role; chained role→role. |
| **Security** | Never trust `"*"`. Use `sts:ExternalId` for third parties. Keep `--max-session-duration` short. Deny `iam:PassRole` broadly and scope it tightly. `aws:SourceIdentity`/`RoleSessionName` for attribution. |
| **Limitations** | **Role chaining caps the session at 1 hour**, regardless of `--max-session-duration`, and `--duration-seconds > 3600` on a chained call fails. Cannot attach a role to a group. Sessions cannot be revoked directly — you revoke by attaching a `Deny` policy conditioned on `aws:TokenIssueTime`. Max 1 000 roles/account (adjustable). |
| **Best practice** | One role per workload, minimal permissions, short sessions, meaningful `--role-session-name` (use the human's identity so CloudTrail is useful). |
| **Common mistakes** | Confusing trust and permissions policies; assuming a role you already are (`AccessDenied` on `sts:AssumeRole` because the *caller's identity policy* lacks it — a role assumption needs an allow on **both** sides); expecting long sessions from chained roles; forgetting `AWS_SESSION_TOKEN`. |

**The AssumeRole handshake (both sides must allow)**

```
  Caller: dnb-dev-alice                         Target: dnb-dev-app-role
  ┌───────────────────────────────┐             ┌──────────────────────────────┐
  │ identity policy must contain  │             │ TRUST policy must contain    │
  │   Effect : Allow              │             │   Effect   : Allow           │
  │   Action : sts:AssumeRole     │  ── AND ──► │   Principal: …user/alice     │
  │   Resource: …role/dnb-dev-app-role          │   Action   : sts:AssumeRole  │
  └───────────────────────────────┘             └──────────────────────────────┘
                       │                                     │
                       └──────────────► STS ◄────────────────┘
                                         │
                                         ▼
                     AccessKeyId ASIA… + SecretAccessKey + SessionToken
                     (valid 15 min … max-session-duration; 1 h if chained)
```

**Trust policy patterns you must be able to write from memory**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustSpecificUser",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::000000000000:user/dnb-dev-alice" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustEc2Service",
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustThirdPartyAuditorWithExternalId",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::111111111111:root" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "sts:ExternalId": "dnb-audit-2026-7f3ac1" },
        "Bool": { "aws:MultiFactorAuthPresent": "true" }
      }
    }
  ]
}
```

!!! danger "The confused-deputy problem — why `ExternalId` exists"
    Your auditor firm has 50 clients and one AWS account. If your trust policy names only their account, then *any* of their staff who can assume roles could reach into your account — and a malicious client could trick the auditor's tooling into assuming **your** role. `sts:ExternalId` is a secret you give only to them, which they must present. It converts "anyone in that account" into "that account, acting deliberately on your behalf". For AWS-service principals the equivalent keys are `aws:SourceArn` and `aws:SourceAccount`.

**`iam:PassRole` — the permission everyone forgets**

To launch an EC2 instance with a role, or create a Lambda with an execution role, the *caller* needs `iam:PassRole` for that role — otherwise `AccessDenied` even though `ec2:RunInstances` is allowed.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PassOnlyApprovedAppRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::000000000000:role/dnb-dev-*",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "ec2.amazonaws.com" }
      }
    }
  ]
}
```

!!! danger "Unscoped `iam:PassRole` is full account takeover"
    `"Action": "iam:PassRole", "Resource": "*"` combined with `lambda:CreateFunction` lets a low-privileged user create a Lambda that runs as an admin role and then do anything. This is the most exploited IAM privilege-escalation path in the wild. Always constrain `Resource` **and** add `iam:PassedToService`.

**STS operation cheat-sheet**

| Operation | Caller | Returns | Duration |
|---|---|---|---|
| `AssumeRole` | IAM user or role | temp creds for a role | 15 min – `max-session-duration` (≤12 h); **1 h if chained** |
| `AssumeRoleWithSAML` | SAML IdP assertion | temp creds | 15 min – 12 h |
| `AssumeRoleWithWebIdentity` | OIDC token (Cognito, Google, GitHub Actions) | temp creds | 15 min – 12 h |
| `GetSessionToken` | IAM user | temp creds **for the same user**, usually to satisfy MFA | 15 min – 36 h (root: ≤1 h) |
| `GetFederationToken` | IAM user | federated-user creds | 15 min – 36 h |
| `GetCallerIdentity` | anyone | who am I — **requires no permissions at all** | n/a |

!!! tip "`GetCallerIdentity` needs no permission"
    It is therefore the perfect first diagnostic in *any* IAM incident. If it fails, your problem is authentication (bad key, missing session token, clock skew), not authorisation.

---

### 4.11 Instance Profiles

**Floci support:** ✅ `create-instance-profile`, `add-role-to-instance-profile`, `get/list/delete`. ⚠️ Whether a Floci EC2 instance actually serves those credentials over an IMDS endpoint at `169.254.169.254` is build-dependent — probe it.

| Aspect | Detail |
|---|---|
| **Purpose** | The container that lets an **EC2 instance** use a role. EC2 cannot reference a role directly; it references an instance profile that wraps the role. |
| **Configuration** | Name + path; add exactly one role. |
| **Lifecycle** | `CreateInstanceProfile` → `AddRoleToInstanceProfile` → associate with instance (`ec2 associate-iam-instance-profile` or `--iam-instance-profile` at launch) → replace/disassociate → `RemoveRoleFromInstanceProfile` → `DeleteInstanceProfile`. |
| **Relationships** | 1 profile : **1** role (hard limit). 1 role : many profiles. 1 instance : ≤1 profile. |
| **Security** | Credentials are delivered via IMDS and auto-rotated. **Enforce IMDSv2** (`--metadata-options HttpTokens=required`) — IMDSv1's simple GET is exploitable via SSRF and has caused real breaches. |
| **Limitations** | Only one role per profile. Console users never see profiles because the console creates them implicitly — CLI users must create them explicitly. This asymmetry surprises everyone once. |
| **Best practice** | Name the profile after the role (`dnb-dev-app-role` → `dnb-dev-app-profile`) so the mapping is obvious in audit output. |

```
  EC2 instance i-0abc…
      │  --iam-instance-profile Name=dnb-dev-app-profile
      ▼
  instance profile dnb-dev-app-profile
      │  contains exactly one role
      ▼
  role dnb-dev-app-role
      ├── trust policy: Service = ec2.amazonaws.com
      └── permissions:  dnb-s3-statements-read
      │
      ▼  delivered to the OS via IMDS
  http://169.254.169.254/latest/meta-data/iam/security-credentials/dnb-dev-app-role
      → { AccessKeyId: ASIA…, SecretAccessKey: …, Token: …, Expiration: … }
      → the AWS SDK finds these automatically. No secrets on disk. Ever.
```

---

### 4.12 Permissions Boundaries

**Floci support:** ⚠️ `put-user-permissions-boundary`, `put-role-permissions-boundary`, `delete-*-permissions-boundary` and the `PermissionsBoundary` field on `get-user`/`get-role` are typically stored and returned. **Enforcement is very unlikely to be emulated.** Track A: verify attachment. Track B: reason the AWS verdict.

| Aspect | Detail |
|---|---|
| **Purpose** | A **ceiling** on the maximum permissions a user or role can ever have, used to delegate IAM administration safely. |
| **Semantics** | Effective permissions = identity policies **∩** boundary. A boundary **never grants**. |
| **Configuration** | A managed policy ARN attached as the boundary of a principal. |
| **Lifecycle** | Put → (principal's effective permissions immediately shrink) → delete boundary. |
| **Relationships** | Applies to users and roles only — **not groups**, not resources. |
| **Security** | The delegation pattern: allow a team lead `iam:CreateUser`/`iam:CreateRole` **only if** they attach a specific boundary (`iam:PermissionsBoundary` condition key), and deny them `iam:DeleteUserPermissionsBoundary`. Without that condition, the lead simply creates an unbounded admin and escalates. |
| **Limitations** | Only one boundary per principal. Does not restrict resource-based policy grants to that principal in *other* accounts. Does not apply to the root user or to service-linked roles. |
| **Best practice** | Have a small library of boundaries: `dnb-boundary-developer`, `dnb-boundary-dataops`. Always allow `iam:GetRole`/`iam:ListRoles` inside the boundary so tooling doesn't break mysteriously. |
| **Common mistakes** | Believing the boundary grants permissions; forgetting to also allow the same actions in an identity policy; omitting the `iam:PermissionsBoundary` condition from the delegation policy (which defeats the entire mechanism). |

```
  Boundary allows: s3:*, ec2:Describe*, logs:*
  Identity policy allows: s3:*, iam:*, ec2:*

              ∩  →  EFFECTIVE:  s3:*  +  ec2:Describe*
                     iam:*  → DENIED (outside boundary)
                     ec2:RunInstances → DENIED (boundary only allows Describe*)
```

**The safe-delegation policy (learn this shape)**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreatePrincipalsOnlyWithMandatoryBoundary",
      "Effect": "Allow",
      "Action": ["iam:CreateUser", "iam:CreateRole", "iam:AttachUserPolicy", "iam:AttachRolePolicy"],
      "Resource": "arn:aws:iam::000000000000:*/dnb/dev/*",
      "Condition": {
        "StringEquals": {
          "iam:PermissionsBoundary": "arn:aws:iam::000000000000:policy/dnb-boundary-developer"
        }
      }
    },
    {
      "Sid": "NeverLetTheDelegateRemoveTheCeiling",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteUserPermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "iam:DeletePolicy"
      ],
      "Resource": "arn:aws:iam::000000000000:policy/dnb-boundary-developer"
    }
  ]
}
```

---

### 4.13 Session Policies

**Floci support:** ⚠️ `sts assume-role --policy` / `--policy-arns` are accepted; enforcement unlikely. Conceptual + attachment verification.

| Aspect | Detail |
|---|---|
| **Purpose** | Further restrict a *single session* at assume time, without changing the role. |
| **Semantics** | Effective = role policies **∩** boundary **∩** session policy. Never grants. |
| **Configuration** | `--policy '<json>'` (inline, ≤2 048 chars after compaction) and/or `--policy-arns arn=…` (up to 10 managed policies). |
| **Lifecycle** | Exists only for the lifetime of the credentials it produced. |
| **Use cases** | Multi-tenant SaaS (one role, per-tenant session scoped to that tenant's prefix); a CI job that should only touch one stack; giving a support engineer 30 minutes of read-only on one bucket. |
| **Limitations** | Cannot exceed the role's permissions. Cannot be changed after assumption — you must re-assume. |
| **Best practice** | Pair with `--tags` (session tags) and ABAC so the session policy can be generic. |

```bash
aws sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dev-app-role" \
  --role-session-name tenant-42-session \
  --policy '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::dnb-statements-dev/tenant-42/*"}]}' \
  --duration-seconds 900
```

---

### 4.14 Service-Linked Roles

**Floci support:** ⚠️/❌ `create-service-linked-role` may exist; the *service integration* it enables does not meaningfully exist locally. Conceptual.

| Aspect | Detail |
|---|---|
| **Purpose** | A role **predefined and owned by an AWS service** (e.g. `AWSServiceRoleForAutoScaling`) so the service can act in your account. |
| **Configuration** | `aws iam create-service-linked-role --aws-service-name autoscaling.amazonaws.com`. Usually created implicitly the first time you use the service. |
| **Lifecycle** | Created by the service or by you → used → `delete-service-linked-role` (asynchronous; poll `get-service-linked-role-deletion-status`). |
| **Relationships** | Lives at path `/aws-service-role/`. Its trust policy and permissions are managed by AWS. |
| **Security** | You **cannot** edit its permissions — which is the point: it is tamper-resistant. You can deny its use via SCP. |
| **Limitations** | One per service per account. Cannot be repurposed. |
| **Common mistakes** | Trying to delete one that is still in use (fails); trying to edit its policy (fails); confusing it with a normal service role that *you* create with a `Service` principal. A **service role** is yours to edit; a **service-linked role** is not. |

---

### 4.15 Multi-Factor Authentication

**Floci support:** ⚠️ `create-virtual-mfa-device`, `enable/deactivate-mfa-device`, `list-mfa-devices`, `list-virtual-mfa-devices` may be present as data operations. **TOTP verification and `aws:MultiFactorAuthPresent` enforcement are AWS-only.** Conceptual + attachment verification.

| Aspect | Detail |
|---|---|
| **Purpose** | A second authentication factor: something you have, in addition to a password/key. |
| **Types** | Virtual (TOTP app), FIDO2/U2F security key, passkey, hardware TOTP token. |
| **Configuration** | `create-virtual-mfa-device` → user scans the QR/seed → `enable-mfa-device --authentication-code1 … --authentication-code2 …` with two **consecutive** codes. |
| **Lifecycle** | Create device → enable (bind to user) → use in `sts get-session-token --serial-number … --token-code …` → resync/deactivate → delete. |
| **Relationships** | Bound to a user. Surfaces as the condition keys `aws:MultiFactorAuthPresent` (Bool) and `aws:MultiFactorAuthAge` (seconds since authentication). |
| **Security** | Mandatory for root and for any human with write access. Enforce it in policy, not just by asking nicely. |
| **Limitations** | MFA cannot be enforced on an IAM **role** session's original authentication unless the trust policy demands it. Access keys alone never carry MFA — you must exchange them via `GetSessionToken` with an MFA code to obtain an MFA-bearing session. |

**The self-service MFA policy (canonical, appears in exams)**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowListUsersSoTheConsoleWorks",
      "Effect": "Allow",
      "Action": ["iam:ListUsers", "iam:ListVirtualMFADevices"],
      "Resource": "*"
    },
    {
      "Sid": "AllowManageOwnMfaAndPassword",
      "Effect": "Allow",
      "Action": [
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:ResyncMFADevice",
        "iam:DeleteVirtualMFADevice",
        "iam:ChangePassword",
        "iam:GetUser",
        "iam:ListMFADevices"
      ],
      "Resource": [
        "arn:aws:iam::000000000000:mfa/${aws:username}",
        "arn:aws:iam::000000000000:user/${aws:username}"
      ]
    },
    {
      "Sid": "DenyEverythingElseUntilMfaIsPresent",
      "Effect": "Deny",
      "NotAction": [
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:GetUser",
        "iam:ListMFADevices",
        "iam:ListVirtualMFADevices",
        "iam:ResyncMFADevice",
        "iam:ChangePassword",
        "sts:GetSessionToken"
      ],
      "Resource": "*",
      "Condition": {
        "BoolIfExists": { "aws:MultiFactorAuthPresent": "false" }
      }
    }
  ]
}
```

!!! tip "Why `BoolIfExists` and not `Bool`"
    For some request types (notably calls made with long-term access keys, and service-to-service calls) the key `aws:MultiFactorAuthPresent` is **absent** rather than `false`. A plain `Bool` test on an absent key does not match, so the `Deny` would not fire. `BoolIfExists` treats "absent" as satisfying the test and correctly denies. Using `Bool` here is a real-world misconfiguration that silently disables your MFA enforcement.

---

### 4.16 Observability: Credential Reports, Last-Used, Access Advisor, Access Analyzer

**Floci support:** ⚠️/❌ Probe each. `generate-credential-report` / `get-credential-report` may return an empty or stub CSV. `get-service-last-accessed-details`, `get-access-key-last-used`, `generate-organizations-access-report` and IAM Access Analyzer are AWS-only or stubbed. **Conceptual, but examinable.**

| Tool | AWS operation | What it answers |
|---|---|---|
| **Credential report** | `generate-credential-report` then `get-credential-report` (base64 CSV) | For every user: MFA enabled? password age? key age? key last used? — the standard quarterly audit artefact |
| **Access key last used** | `get-access-key-last-used` | Which service/region/date this key last touched — the input to "is this key abandoned?" |
| **Access Advisor** | `generate-service-last-accessed-details` → `get-service-last-accessed-details` | Which services this principal has actually used — the input to right-sizing an over-permissive policy |
| **IAM Access Analyzer** | (separate service) | Which resources are reachable from **outside** your account/org; policy validation and unused-access findings |
| **Policy simulator** | `simulate-principal-policy`, `simulate-custom-policy` | "Would this request be allowed?" **without making the request** |
| **CloudTrail** | (separate service) | The immutable record of who did what, when, from where |

```bash
# Real-AWS workflow for the quarterly credential audit
aws iam generate-credential-report
aws iam get-credential-report --query Content --output text | base64 -d > ~/iam-lab/out/credential-report.csv
column -t -s, ~/iam-lab/out/credential-report.csv | head -20
```

!!! note "Least-privilege right-sizing loop (the professional workflow)"
    1. Grant a **broad but bounded** policy in a dev account.
    2. Let the workload run for 2–4 weeks.
    3. Read Access Advisor / CloudTrail to see which actions were *actually* used.
    4. Generate a tight policy from that evidence (IAM Access Analyzer can do this from CloudTrail).
    5. Deploy the tight policy to production; keep the broad one nowhere.

    You cannot execute steps 2–4 in Floci. You must be able to *describe* them.

---

### 4.17 AWS-Only Governance Layers (conceptual)

**Floci support:** ❌ across the board. Required knowledge for SAA-C03.

| Feature | What it is | Why it matters |
|---|---|---|
| **AWS Organizations** | Multi-account hierarchy: management account, OUs, member accounts | The real unit of isolation is the *account*, not the IAM policy |
| **Service Control Policies (SCP)** | Org-level **filters** on what member accounts may do | An SCP allowing nothing means even the account's admin can do nothing. SCPs never grant; they cap. Do not apply to the management account's root. |
| **Resource Control Policies (RCP)** | Org-level filters on **resources**, e.g. "no S3 bucket in this org may be public" | Complements SCPs from the resource side |
| **IAM Identity Center (successor to AWS SSO)** | Central workforce identity → permission sets → roles in every account | **The modern answer to "how do humans get access?" — no IAM users at all** |
| **Identity federation (SAML 2.0 / OIDC)** | Corporate IdP issues an assertion; STS exchanges it for role credentials | Zero passwords in AWS; joiners/leavers handled in the IdP |
| **`aws:PrincipalOrgID`** | Condition key matching any principal in your org | One condition instead of enumerating 60 account IDs |
| **Tag policies** | Enforce tag keys/values org-wide | Makes ABAC and cost allocation trustworthy |

```
  AWS Organizations
   └─ Root
      ├─ SCP: DenyRegionsOutside(ap-south-1, us-east-1)
      ├─ OU: Production
      │    ├─ SCP: DenyDisableCloudTrail, DenyDeleteKmsKey
      │    └─ Account: dnb-core-banking-prod
      │         └─ IAM: roles only, boundaries mandatory
      └─ OU: NonProduction
           ├─ SCP: DenyInstanceTypesAbove(t3.large)
           └─ Account: dnb-core-banking-dev  ← this is what Floci stands in for

  EFFECTIVE PERMISSION = SCP ∩ RCP ∩ (identity ∪ resource) ∩ boundary ∩ session
                         minus any explicit Deny at any layer
```

!!! note "Recap — §4"
    Users are for humans (and ideally replaced by federation). Groups are for scaling permissions to humans. Roles are for everything else, and always need *two* policies. Boundaries and session policies filter, never grant. Instance profiles are the EC2-shaped wrapper around a role. Everything above the account — Organizations, SCPs, Identity Center — is AWS-only and must be learned conceptually.

---
## 5. Hands-on Labs

### How to work through the labs

* Labs are **cumulative**. Lab 6 uses the user from Lab 1 and the policy from Lab 3. Do not clean up until §16.
* Every lab has the same shape: **Objective → Prerequisites → Architecture → Implementation → Verification → Break it → Fix it → Recap**.
* Every command block is followed by a parameter table. Do not copy-paste without reading it.
* Expected outputs are shown. Yours may differ in IDs and timestamps — that is normal. If they differ in *structure*, investigate.
* Maintain a lab logbook: `~/iam-lab/out/logbook.md`. Record every `DIVERGES-FROM-AWS` finding.

```bash
# Run at the start of EVERY lab session
cd ~/iam-lab
floci status || floci start --persist ./floci-state --detach && floci wait --timeout 2m
eval "$(floci env)"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export TAGS="Key=Project,Value=CoreBanking Key=Environment,Value=dev Key=Owner,Value=$USER Key=CostCenter,Value=CC-4400 Key=ManagedBy,Value=floci-lab"
echo "endpoint=$AWS_ENDPOINT_URL account=$ACCOUNT_ID"
```

---

### Lab 0 — Environment, Identity, and Support Discovery

**Objective.** Establish a verified Floci session, discover the account identity, and produce your build's IAM support matrix — the reference document for every later lab.

**Prerequisites.** §0.2 checklist complete.

**Architecture.**

```
   your shell ──AWS_ENDPOINT_URL──► Floci container :4566
        │                                  │
        │                                  ├── iam  (≈68 ops)
        │                                  ├── sts  (7 ops)
        │                                  └── s3, lambda, ec2, …
        └── probe-support.sh ──────────────► support-matrix.tsv
```

#### Step 0.1 — Start and verify

```bash
floci start --persist ./floci-state --detach
floci wait --timeout 2m
floci status -o json | jq '{running: .running, endpoint: .endpoint, services: (.services|length)}'
eval "$(floci env)"
```

| Command | Purpose |
|---|---|
| `floci start --persist … --detach` | Launch the emulator with durable state, returning control immediately |
| `floci wait --timeout 2m` | Poll the health endpoint until ready — prevents "connection refused" races |
| `floci status -o json` | Machine-readable state; `jq` extracts just what we care about |
| `eval "$(floci env)"` | Injects `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` into this shell |

!!! warning "`eval` is per-shell"
    Open a new terminal tab and those variables are gone; your next `aws` command may silently hit real AWS. Add `eval "$(floci env)"` to your lab shell's startup, or re-run it every time.

#### Step 0.2 — Who am I?

```bash
aws sts get-caller-identity
```

```json
{
    "UserId": "AKIAIOSFODNN7EXAMPLE",
    "Account": "000000000000",
    "Arn": "arn:aws:iam::000000000000:root"
}
```

| Field | Meaning |
|---|---|
| `UserId` | Unique, immutable internal ID. For a user `AIDA…`, role `AROA…`, assumed-role session `AROA…:<session-name>` |
| `Account` | The 12-digit account. Floci uses a synthetic value |
| `Arn` | **The principal you are acting as.** Note it is the account root here — you are effectively unrestricted |

```bash
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
```

| Flag | Purpose |
|---|---|
| `--query Account` | Client-side JMESPath filter — extracts one field |
| `--output text` | Strips JSON quoting so the value is shell-usable |

#### Step 0.3 — Baseline the account

```bash
aws iam get-account-summary --query 'SummaryMap' 2>/dev/null | jq '.' || echo "get-account-summary not supported"
aws iam list-users  --output json | jq '{count: (.Users|length)}'
aws iam list-roles  --output json | jq '{count: (.Roles|length), names: [.Roles[].RoleName]}'
aws iam list-policies --scope Local --output json | jq '{customerManaged: (.Policies|length)}'
aws iam list-policies --scope AWS   --output json | jq '{awsManagedSeeded: (.Policies|length)}'
```

| Flag | Purpose |
|---|---|
| `--scope Local` | Only **customer managed** policies (created by you) |
| `--scope AWS` | Only **AWS managed** policies — reveals how many Floci has seeded |
| `--only-attached` | (optional) restrict to policies currently attached to something |

!!! tip "Record the AWS-managed count now"
    If `--scope AWS` returns 0 or a handful, you cannot rely on `arn:aws:iam::aws:policy/ReadOnlyAccess` and friends in later labs. Every lab in this module therefore uses **customer managed** policies you build yourself — which is better pedagogy anyway, since you will write policies from scratch in your career, not just attach Amazon's.

#### Step 0.4 — Produce the support matrix

```bash
chmod +x ~/iam-lab/probe-support.sh
~/iam-lab/probe-support.sh | tee ~/iam-lab/out/support-report.txt
grep -E 'UNSUPPORTED|UNKNOWN' ~/iam-lab/out/support-matrix.tsv || echo "Everything probed is supported."
```

**Verification checklist.**

| # | Check | Command |
|---|---|---|
| 1 | Endpoint is local | `[[ $AWS_ENDPOINT_URL == *localhost* ]] && echo ok` |
| 2 | `sts get-caller-identity` returns an ARN | `aws sts get-caller-identity --query Arn --output text` |
| 3 | `support-matrix.tsv` exists and is non-empty | `wc -l ~/iam-lab/out/support-matrix.tsv` |
| 4 | You have recorded the AWS-managed policy count | in your logbook |

**Break it.** Unset the endpoint and observe what the CLI tries to do — then immediately restore it.

```bash
( unset AWS_ENDPOINT_URL; timeout 8 aws iam list-users 2>&1 | head -3 )
```

Expected: a timeout, a DNS/TLS error, or `InvalidClientTokenId` from **real AWS** (`iam.amazonaws.com`). Note the subshell parentheses — they contain the damage.

!!! danger "Never run that outside a subshell"
    This exercise exists to burn one lesson into you: the endpoint variable is the only thing between your lab commands and a real AWS account.

**Lab 0 recap.** You have a verified local session, know your principal ARN, and hold an empirical support matrix that you will cite whenever a later lab says "probe this".

---

### Lab 1 — IAM Users: Creation, Paths, Tags, Inspection

**Objective.** Create the Druk National Bank development identities with correct paths and mandatory tags; inspect them; understand deletion dependencies.

**Prerequisites.** Lab 0.

**Architecture.**

```
  account 000000000000
   └── path /dnb/dev/
        ├── dnb-dev-alice     (backend developer)
        ├── dnb-dev-bob       (frontend developer)
        └── dnb-dev-carol     (internal auditor — read-only)
   └── path /dnb/svc/
        └── dnb-svc-batch     (legacy nightly batch job — a deliberate anti-pattern
                               we will critique and replace with a role in Lab 6)
```

#### Step 1.1 — Create users

```bash
for u in alice bob carol; do
  aws iam create-user \
    --user-name "dnb-dev-$u" \
    --path /dnb/dev/ \
    --tags $TAGS Key=Role,Value=$u \
    --output json | jq '{UserName: .User.UserName, Arn: .User.Arn, CreateDate: .User.CreateDate}'
done

aws iam create-user \
  --user-name dnb-svc-batch \
  --path /dnb/svc/ \
  --tags $TAGS Key=Role,Value=batch Key=AntiPattern,Value=true \
  --output json | jq '.User.Arn'
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--user-name` | 1–64 chars, `[\w+=,.@-]` | Case-insensitively unique in the account |
| `--path` | Virtual folder, must begin and end with `/` | Changeable later for users and groups via `--new-path`; **immutable for roles** |
| `--tags` | Up to 50 `Key=…,Value=…` pairs | Space-separated in CLI v2, not comma-separated between pairs |
| `--permissions-boundary` | (Lab 9) managed policy ARN acting as a ceiling | |

**Expected output**

```json
{
  "UserName": "dnb-dev-alice",
  "Arn": "arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-alice",
  "CreateDate": "2026-08-04T09:14:22+00:00"
}
```

!!! tip "Read the ARN carefully"
    `user/dnb/dev/dnb-dev-alice` — the path is *inside* the ARN. This is what makes `arn:aws:iam::*:user/dnb/dev/*` a meaningful policy resource.

#### Step 1.2 — Inspect

```bash
# All users, with path
aws iam list-users --query 'Users[].[UserName,Path,Arn]' --output table

# Only development-path users
aws iam list-users --path-prefix /dnb/dev/ --query 'Users[].UserName' --output text

# One user in detail
aws iam get-user --user-name dnb-dev-alice | jq '.User'

# Tags
aws iam list-user-tags --user-name dnb-dev-alice --query 'Tags' --output table
```

```json
{
  "Path": "/dnb/dev/",
  "UserName": "dnb-dev-alice",
  "UserId": "AIDAEXAMPLEID1234567",
  "Arn": "arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-alice",
  "CreateDate": "2026-08-04T09:14:22+00:00",
  "Tags": [
    { "Key": "Project", "Value": "CoreBanking" },
    { "Key": "Environment", "Value": "dev" },
    { "Key": "Owner", "Value": "student" },
    { "Key": "CostCenter", "Value": "CC-4400" },
    { "Key": "ManagedBy", "Value": "floci-lab" },
    { "Key": "Role", "Value": "alice" }
  ]
}
```

!!! note "`PermissionsBoundary` is absent from this output"
    That is expected — none is attached yet. In Lab 9 this same command will show a `PermissionsBoundary` block. If your build never shows it, record the divergence.

#### Step 1.3 — Modify tags and rename

```bash
# Add a tag after creation
aws iam tag-user --user-name dnb-dev-carol --tags Key=Department,Value=InternalAudit
aws iam list-user-tags --user-name dnb-dev-carol --query 'Tags[?Key==`Department`]' --output table

# Remove a tag
aws iam untag-user --user-name dnb-dev-carol --tag-keys Department

# Rename (path can also be changed here in real AWS via --new-path)
aws iam update-user --user-name dnb-dev-bob --new-user-name dnb-dev-bob-r
aws iam update-user --user-name dnb-dev-bob-r --new-user-name dnb-dev-bob   # revert
```

!!! warning "Renaming does not update policies that hard-code the old name"
    Any policy, trust policy, or `aws:username`-based path that referenced `dnb-dev-bob` by literal string will now be broken. The `UserId` (`AIDA…`) is stable; the name is not. This is why production policies prefer tags and paths over literal names.

#### Verification

```bash
test "$(aws iam list-users --path-prefix /dnb/dev/ --query 'length(Users)' --output text)" = "3" \
  && echo "PASS: 3 dev users" || echo "FAIL"
test "$(aws iam list-user-tags --user-name dnb-dev-alice --query 'length(Tags)' --output text)" -ge "5" \
  && echo "PASS: tags present" || echo "FAIL"
```

#### Break it — dependency-blocked deletion

```bash
aws iam create-user --user-name dnb-temp-victim --path /dnb/dev/ >/dev/null
aws iam create-access-key --user-name dnb-temp-victim >/dev/null
aws iam delete-user --user-name dnb-temp-victim
```

**Expected (real AWS, and likely Floci):**

```
An error occurred (DeleteConflict) when calling the DeleteUser operation:
Cannot delete entity, must delete access keys first.
```

#### Fix it — the correct teardown order

```bash
KEY_ID="$(aws iam list-access-keys --user-name dnb-temp-victim --query 'AccessKeyMetadata[0].AccessKeyId' --output text)"
aws iam delete-access-key --user-name dnb-temp-victim --access-key-id "$KEY_ID"
aws iam delete-user      --user-name dnb-temp-victim
aws iam get-user         --user-name dnb-temp-victim 2>&1 | grep -q NoSuchEntity && echo "PASS: deleted"
```

!!! note "If Floci let you delete the user *with* the key attached"
    Record `DIVERGES-FROM-AWS: DeleteUser does not enforce dependency order`. In real AWS this ordering is strict and is a frequent source of failed teardown scripts and orphaned resources.

**Lab 1 recap.** Users carry a name, an immutable path, tags, and children (keys, profiles, policies). ARNs embed the path. Deletion requires removing every child first.

---

### Lab 2 — Groups: Scaling Permissions to People

**Objective.** Replace per-user permissions with job-function groups; demonstrate that groups are not principals.

**Prerequisites.** Lab 1.

**Architecture.**

```
   dnb-developers ──┬── dnb-dev-alice
        │           └── dnb-dev-bob
        └── (policies attached in Lab 3)

   dnb-auditors  ───── dnb-dev-carol
        └── (read-only policy, Lab 3)

   dnb-admins    ───── (empty; break-glass only)
```

#### Step 2.1 — Create groups

```bash
for g in developers auditors admins; do
  aws iam create-group --group-name "dnb-$g" --path /dnb/ \
    --query 'Group.[GroupName,Arn]' --output text
done
```

| Parameter | Meaning |
|---|---|
| `--group-name` | 1–128 chars |
| `--path` | as with users; changeable later via `update-group --new-path` |

Note: `create-group` accepts **no `--tags`** — groups are not taggable in IAM. This asymmetry is worth remembering.

```
dnb-developers  arn:aws:iam::000000000000:group/dnb/dnb-developers
dnb-auditors    arn:aws:iam::000000000000:group/dnb/dnb-auditors
dnb-admins      arn:aws:iam::000000000000:group/dnb/dnb-admins
```

#### Step 2.2 — Add members

```bash
aws iam add-user-to-group --group-name dnb-developers --user-name dnb-dev-alice
aws iam add-user-to-group --group-name dnb-developers --user-name dnb-dev-bob
aws iam add-user-to-group --group-name dnb-auditors   --user-name dnb-dev-carol
```

`add-user-to-group` is idempotent — running it twice is harmless and produces no output on success.

#### Step 2.3 — Inspect from both directions

```bash
# Group → members
aws iam get-group --group-name dnb-developers \
  --query '{Group: Group.GroupName, Members: Users[].UserName}'

# User → groups
aws iam list-groups-for-user --user-name dnb-dev-alice \
  --query 'Groups[].GroupName' --output text

# Every group
aws iam list-groups --query 'Groups[].[GroupName,Path]' --output table
```

```json
{
  "Group": "dnb-developers",
  "Members": ["dnb-dev-alice", "dnb-dev-bob"]
}
```

#### Break it (three ways) — the limits of groups

```bash
# 1. Groups cannot be nested. There is no such operation.
aws iam add-user-to-group --group-name dnb-developers --user-name dnb-auditors 2>&1 | tail -2
```

Expected: `NoSuchEntity: The user with name dnb-auditors cannot be found.` — because `--user-name` only accepts users. **There is no `add-group-to-group` API at all.**

```bash
# 2. A group is not a principal — it cannot be trusted by a role.
cat > policies/bad-trust-group.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvalidGroupPrincipal",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::000000000000:group/dnb/dnb-developers" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
aws iam create-role --role-name dnb-broken-group-trust \
  --assume-role-policy-document file://policies/bad-trust-group.json 2>&1 | tail -3
```

Expected in real AWS:

```
An error occurred (MalformedPolicyDocument) when calling the CreateRole operation:
Invalid principal in policy: "AWS":"arn:aws:iam::000000000000:group/dnb/dnb-developers"
```

!!! note "If Floci accepts the group principal"
    It will have created a role whose trust policy can never match anything in real AWS. Delete it and record the divergence — this is exactly the class of bug an emulator can hide from you:

    ```bash
    aws iam delete-role --role-name dnb-broken-group-trust 2>/dev/null
    ```

```bash
# 3. Group quota: a user may be in at most 10 groups (default quota).
aws iam get-account-summary --query 'SummaryMap.{Groups: Groups, GroupsQuota: GroupsQuota, GroupsPerUserQuota: GroupsPerUserQuota}' 2>/dev/null \
  || echo "get-account-summary unsupported here — quota values are AWS-side (300 groups/account, 10 groups/user)"
```

#### Verification

```bash
test "$(aws iam get-group --group-name dnb-developers --query 'length(Users)' --output text)" = "2" \
  && echo "PASS: developers has 2 members" || echo "FAIL"
```

**Lab 2 recap.** Groups scale permissions across humans. They cannot nest, cannot be principals, cannot be tagged, and cannot assume roles. Model them on job functions.

---

### Lab 3 — Customer Managed Policies and the Version Lifecycle

**Objective.** Author a least-privilege S3 policy from scratch, attach it to a group, then evolve it through versions and roll back.

**Prerequisites.** Labs 1–2. An S3 bucket to talk about.

**Architecture.**

```
   dnb-s3-statements-read  (customer managed policy)
        ├── v1  GetObject + ListBucket on dnb-statements-dev
        ├── v2  + TLS-only Condition          ← default
        └── v3  + PutObject (over-permissive)  ← we will reject and roll back
             │
             └── attached to → dnb-developers group → alice, bob
```

#### Step 3.1 — Create the target bucket

```bash
aws s3 mb "s3://dnb-statements-dev"
aws s3 mb "s3://dnb-audit-logs-dev"
printf 'ACCT-1001,2026-07,BTN 45300.00\n' > out/statement-1001.csv
aws s3 cp out/statement-1001.csv s3://dnb-statements-dev/2026/07/statement-1001.csv
aws s3 ls s3://dnb-statements-dev --recursive
```

#### Step 3.2 — Author v1

```bash
cat > policies/dnb-s3-statements-read-v1.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheStatementsBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::dnb-statements-dev"
    },
    {
      "Sid": "ReadObjectsInStatementsBucket",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*"
    }
  ]
}
JSON

# ALWAYS validate JSON before sending it. This catches 90% of MalformedPolicyDocument errors.
jq empty policies/dnb-s3-statements-read-v1.json && echo "JSON valid"
```

| Statement | Why it is separate |
|---|---|
| `ListTheStatementsBucket` | `s3:ListBucket` is a **bucket-level** action; its resource is the bucket ARN with no `/*` |
| `ReadObjectsInStatementsBucket` | `s3:GetObject` is an **object-level** action; its resource needs `/*` |

!!! danger "The two-ARN rule, again"
    Merging these into one statement with only `arn:aws:s3:::dnb-statements-dev/*` breaks `ListBucket`; with only `arn:aws:s3:::dnb-statements-dev` it breaks `GetObject`. You need both ARNs, and separating the statements makes the intent auditable.

```bash
POLICY_ARN="$(aws iam create-policy \
  --policy-name dnb-s3-statements-read \
  --path /dnb/ \
  --description "Read-only access to the customer statements bucket (dev)" \
  --policy-document file://policies/dnb-s3-statements-read-v1.json \
  --tags $TAGS \
  --query 'Policy.Arn' --output text)"
echo "$POLICY_ARN" | tee out/policy-arn.txt
```

| Parameter | Meaning |
|---|---|
| `--policy-name` | 1–128 chars; unique per account |
| `--policy-document file://…` | **`file://` prefix is mandatory** — without it the CLI treats the path as the literal document |
| `--path /dnb/` | Appears in the ARN: `…:policy/dnb/dnb-s3-statements-read` |
| `--description` | **Immutable after creation.** Write it properly the first time |
| `--tags` | Policies are taggable |

```
arn:aws:iam::000000000000:policy/dnb/dnb-s3-statements-read
```

!!! warning "`file://` vs `fileb://` vs no prefix"
    `file://path` reads a text file. `fileb://path` reads binary. Omitting the prefix passes the string `"policies/foo.json"` as the policy document, producing a confusing `MalformedPolicyDocument`. This is the single most common CLI mistake in IAM labs.

#### Step 3.3 — Attach to the group (never to the user)

```bash
aws iam attach-group-policy --group-name dnb-developers --policy-arn "$POLICY_ARN"

aws iam list-attached-group-policies --group-name dnb-developers \
  --query 'AttachedPolicies[].[PolicyName,PolicyArn]' --output table

# Central audit: who uses this policy?
aws iam list-entities-for-policy --policy-arn "$POLICY_ARN" \
  --query '{Users: PolicyUsers[].UserName, Groups: PolicyGroups[].GroupName, Roles: PolicyRoles[].RoleName}'
```

```json
{
  "Users": [],
  "Groups": ["dnb-developers"],
  "Roles": []
}
```

!!! tip "`list-entities-for-policy` is the killer feature of managed policies"
    Ask "who has this permission?" and get an answer in one call. With inline policies you would have to enumerate every user, group and role and read each embedded document. This alone justifies the managed-policy default.

#### Step 3.4 — v2: add a TLS guardrail

```bash
cat > policies/dnb-s3-statements-read-v2.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheStatementsBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::dnb-statements-dev"
    },
    {
      "Sid": "ReadObjectsInStatementsBucket",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*"
    },
    {
      "Sid": "DenyAnyRequestNotUsingTls",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": {
        "Bool": { "aws:SecureTransport": "false" }
      }
    }
  ]
}
JSON
jq empty policies/dnb-s3-statements-read-v2.json && echo "JSON valid"

aws iam create-policy-version \
  --policy-arn "$POLICY_ARN" \
  --policy-document file://policies/dnb-s3-statements-read-v2.json \
  --set-as-default \
  --query 'PolicyVersion.[VersionId,IsDefaultVersion,CreateDate]' --output text
```

| Parameter | Meaning |
|---|---|
| `--set-as-default` | Makes the new version live **immediately** for every attached principal |
| omit `--set-as-default` | Version is stored but inert — useful for staging a change for review |

```
v2   True   2026-08-04T09:31:07+00:00
```

!!! danger "`--set-as-default` is an instant production change"
    There is no gradual rollout. Every principal attached to this policy changes permissions the moment the call returns. In a real organisation this belongs in a code-reviewed IaC pipeline, never in an ad-hoc CLI call.

#### Step 3.5 — v3: the over-permissive change we reject

```bash
cat > policies/dnb-s3-statements-read-v3.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WayTooMuch",
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": "*"
    }
  ]
}
JSON

aws iam create-policy-version \
  --policy-arn "$POLICY_ARN" \
  --policy-document file://policies/dnb-s3-statements-read-v3.json \
  --set-as-default \
  --query 'PolicyVersion.VersionId' --output text
```

Now perform a **security review** and reject it.

```bash
# Inspect the live document
aws iam get-policy --policy-arn "$POLICY_ARN" --query 'Policy.DefaultVersionId' --output text

aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id v3 \
  --query 'PolicyVersion.Document' | jq '.'
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "WayTooMuch", "Effect": "Allow", "Action": "s3:*", "Resource": "*" }
  ]
}
```

#### Step 3.6 — Roll back (the whole point of versioning)

```bash
aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
  --query 'Versions[].[VersionId,IsDefaultVersion,CreateDate]' --output table

aws iam set-default-policy-version --policy-arn "$POLICY_ARN" --version-id v2

aws iam get-policy --policy-arn "$POLICY_ARN" --query 'Policy.DefaultVersionId' --output text   # → v2

# Remove the rejected version entirely
aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id v3
aws iam list-policy-versions --policy-arn "$POLICY_ARN" --query 'Versions[].VersionId' --output text
```

```
-------------------------------------------------------
|                 ListPolicyVersions                  |
+------+---------+----------------------------------+
|  v1  |  False  |  2026-08-04T09:28:41+00:00       |
|  v2  |  False  |  2026-08-04T09:31:07+00:00       |
|  v3  |  True   |  2026-08-04T09:33:55+00:00       |
+------+---------+----------------------------------+
```

**Rollback took one API call and zero seconds of downtime.** That is the operational argument for managed policies.

#### Break it — three version-lifecycle failures

```bash
# (a) Cannot delete the default version
aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id v2 2>&1 | tail -2
```

Expected: `DeleteConflict: Cannot delete the default version of a policy.`

```bash
# (b) The 5-version ceiling
for i in 1 2 3 4 5 6; do
  printf '{"Version":"2012-10-17","Statement":[{"Sid":"Filler%d","Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::dnb-statements-dev/probe-%d/*"}]}\n' "$i" "$i" > policies/filler-$i.json
  echo -n "attempt $i: "
  aws iam create-policy-version --policy-arn "$POLICY_ARN" \
      --policy-document file://policies/filler-$i.json \
      --query 'PolicyVersion.VersionId' --output text 2>&1 | tail -1
done
```

Expected around the 4th–5th attempt:

```
LimitExceeded: A managed policy can have up to 5 versions. Before you create a new version,
you must delete an existing version.
```

```bash
# Clean up the fillers, keeping v1 and the default
for v in $(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
             --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text); do
  [ "$v" = "v1" ] || aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$v"
done
aws iam list-policy-versions --policy-arn "$POLICY_ARN" --query 'Versions[].[VersionId,IsDefaultVersion]' --output table
```

```bash
# (c) Cannot delete a policy that is still attached
aws iam delete-policy --policy-arn "$POLICY_ARN" 2>&1 | tail -2
```

Expected: `DeleteConflict: Cannot delete a policy attached to entities.`

#### Fix it

```bash
# Detach first, then delete — but we still need this policy, so only demonstrate the order:
echo "correct order: list-entities-for-policy → detach-*-policy for each → delete-policy"
aws iam list-entities-for-policy --policy-arn "$POLICY_ARN" --query 'PolicyGroups[].GroupName' --output text
```

#### Verification

```bash
aws iam get-policy --policy-arn "$POLICY_ARN" \
  --query 'Policy.{Name: PolicyName, Default: DefaultVersionId, Attachments: AttachmentCount, Versions: [DefaultVersionId]}'
aws iam get-policy-version --policy-arn "$POLICY_ARN" \
  --version-id "$(aws iam get-policy --policy-arn "$POLICY_ARN" --query 'Policy.DefaultVersionId' --output text)" \
  --query 'PolicyVersion.Document.Statement[].Sid' --output text
```

Expected Sids: `ListTheStatementsBucket ReadObjectsInStatementsBucket DenyAnyRequestNotUsingTls`

**Lab 3 recap.** Customer managed policies are versioned (max 5), attach to many principals, are centrally auditable via `list-entities-for-policy`, and roll back with a single `set-default-policy-version`. `file://` is mandatory. Descriptions are immutable. You cannot delete the default version, nor an attached policy.

---

### Lab 4 — Inline Policies, and Choosing Between the Two

**Objective.** Attach an inline policy, observe its distinct API surface and lifecycle, and articulate when it is the right choice.

**Prerequisites.** Lab 3.

**Architecture.**

```
  dnb-auditors (group)
      ├── attached managed: dnb-s3-audit-read       ← reusable
      └── inline:          DenyAuditorsAnyWrite     ← one-off guardrail,
                                                      must never be reused
                                                      or outlive the group
```

#### Step 4.1 — A reusable managed policy for auditors

```bash
cat > policies/dnb-s3-audit-read.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBothBuckets",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-audit-logs-dev"
      ]
    },
    {
      "Sid": "ReadObjectsInBothBuckets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev/*",
        "arn:aws:s3:::dnb-audit-logs-dev/*"
      ]
    },
    {
      "Sid": "ReadIamForAuditPurposes",
      "Effect": "Allow",
      "Action": [
        "iam:Get*", "iam:List*",
        "iam:GenerateCredentialReport", "iam:GetCredentialReport"
      ],
      "Resource": "*"
    }
  ]
}
JSON
jq empty policies/dnb-s3-audit-read.json && echo valid

AUDIT_ARN="$(aws iam create-policy --policy-name dnb-s3-audit-read --path /dnb/ \
  --description "Read-only S3 + IAM inspection for internal audit (dev)" \
  --policy-document file://policies/dnb-s3-audit-read.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-group-policy --group-name dnb-auditors --policy-arn "$AUDIT_ARN"
echo "$AUDIT_ARN" | tee out/audit-policy-arn.txt
```

!!! tip "`iam:Get*` + `iam:List*` is the standard auditor grant"
    It is broad but read-only. Note it deliberately excludes `iam:GetCredentialReport`'s write-side sibling patterns and any `iam:Create*`/`iam:Put*`/`iam:Attach*`/`iam:Delete*`. Auditors read; they do not change.

#### Step 4.2 — An inline policy: the belt-and-braces deny

```bash
cat > policies/inline-deny-auditor-writes.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AuditorsMayNeverMutateAnything",
      "Effect": "Deny",
      "NotAction": [
        "s3:Get*", "s3:List*", "s3:Describe*",
        "iam:Get*", "iam:List*", "iam:Simulate*",
        "iam:GenerateCredentialReport", "iam:GetCredentialReport",
        "sts:GetCallerIdentity",
        "cloudtrail:Get*", "cloudtrail:Describe*", "cloudtrail:LookupEvents",
        "logs:Get*", "logs:Describe*", "logs:FilterLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
JSON
jq empty policies/inline-deny-auditor-writes.json && echo valid

aws iam put-group-policy \
  --group-name dnb-auditors \
  --policy-name DenyAuditorsAnyWrite \
  --policy-document file://policies/inline-deny-auditor-writes.json

aws iam list-group-policies --group-name dnb-auditors --query 'PolicyNames' --output text
aws iam get-group-policy --group-name dnb-auditors --policy-name DenyAuditorsAnyWrite \
  --query 'PolicyDocument.Statement[0].Sid' --output text
```

| API family | Managed policies | Inline policies |
|---|---|---|
| Create | `create-policy` (standalone object with an ARN) | `put-user-policy` / `put-group-policy` / `put-role-policy` |
| Attach | `attach-{user,group,role}-policy --policy-arn` | *no attach step — the put **is** the attach* |
| Read | `get-policy` + `get-policy-version` | `get-{user,group,role}-policy --policy-name` |
| List on principal | `list-attached-{user,group,role}-policies` | `list-{user,group,role}-policies` |
| Delete | `detach-…` then `delete-policy` | `delete-{user,group,role}-policy` |
| Reverse lookup | `list-entities-for-policy` ✅ | **impossible** ❌ |

!!! danger "`list-attached-user-policies` and `list-user-policies` are different commands"
    The first lists **managed** attachments; the second lists **inline** documents. A permissions audit that runs only one of them will miss half the story. Real-world audits get this wrong constantly. `get-account-authorization-details` returns both in one call and is the correct tool — probe whether your build supports it.

#### Step 4.3 — Full picture of one principal's permissions

```bash
audit_principal() {
  local kind="$1" name="$2"   # kind: user | group | role
  echo "=== $kind: $name ==="
  echo "-- attached managed --"
  aws iam "list-attached-${kind}-policies" "--${kind}-name" "$name" \
    --query 'AttachedPolicies[].[PolicyName,PolicyArn]' --output table 2>/dev/null
  echo "-- inline --"
  aws iam "list-${kind}-policies" "--${kind}-name" "$name" \
    --query 'PolicyNames' --output text 2>/dev/null
  if [ "$kind" = "user" ]; then
    echo "-- groups (inherited permissions live here too) --"
    aws iam list-groups-for-user --user-name "$name" --query 'Groups[].GroupName' --output text
    echo "-- permissions boundary --"
    aws iam get-user --user-name "$name" --query 'User.PermissionsBoundary' --output json
  fi
}

audit_principal group dnb-auditors
audit_principal user  dnb-dev-carol
```

!!! warning "A user's effective permissions are a union of four sources"
    ① their attached managed policies ② their inline policies ③ **every group they belong to**, including both of that group's policy types ④ minus the intersection with their permissions boundary. Auditing only ① and ② is the most common cause of "but I thought Carol was read-only".

#### Break it — inline policy size limits

```bash
# Generate an oversized inline document (group inline limit is 5120 chars in AWS)
python3 - <<'PY' > policies/oversized-inline.json
import json
stmts = [{
  "Sid": f"Filler{i:04d}",
  "Effect": "Allow",
  "Action": "s3:GetObject",
  "Resource": f"arn:aws:s3:::dnb-statements-dev/very/long/prefix/number/{i:06d}/*"
} for i in range(120)]
print(json.dumps({"Version": "2012-10-17", "Statement": stmts}))
PY
wc -c policies/oversized-inline.json

aws iam put-group-policy --group-name dnb-auditors --policy-name TooBig \
  --policy-document file://policies/oversized-inline.json 2>&1 | tail -2
```

Expected in real AWS: `LimitExceeded: Maximum policy size of 5120 bytes exceeded for group dnb-auditors`.

!!! note "Why the limit matters architecturally"
    Inline policy budgets are *per principal and cumulative*. Ten small inline policies can collectively hit the ceiling and block the eleventh. Managed policies have a 6 144-byte limit each but a principal can attach 10 (default) of them — roughly 60 KB of policy. Hitting inline limits is a signal you should have used managed policies.

#### Decision exercise (write this in your logbook)

For each requirement, state managed or inline and justify in one sentence.

| # | Requirement | Your answer |
|---|---|---|
| 1 | "Every developer needs read access to the statements bucket." | |
| 2 | "This one break-glass role has a unique grant that must vanish if the role is deleted." | |
| 3 | "Security needs to answer 'who can delete KMS keys?' in under a minute." | |
| 4 | "We need to roll back last night's permission change immediately." | |
| 5 | "A contractor role needs one temporary exception nobody should ever copy." | |

**Lab 4 recap.** Inline policies have no ARN, no versions, no reverse lookup, and die with their principal. Managed policies are the default; inline is for deliberate one-offs. Auditing a principal requires checking managed + inline + groups + boundary.

---
### Lab 5 — Access Keys, Named Profiles, and Zero-Downtime Rotation

**Objective.** Issue long-term credentials, use them under a **separate named profile** (this is what finally lets you test enforcement), and perform a correct four-phase rotation.

**Prerequisites.** Labs 1–4.

**Architecture.**

```
  dnb-dev-carol (in dnb-auditors)
      ├── access key #1  AKIA…AAAA   Active   ← used by profile "carol"
      └── access key #2  AKIA…BBBB   (created during rotation)

  ~/.aws/credentials
      [carol]  aws_access_key_id / aws_secret_access_key
  ~/.aws/config
      [profile carol]  endpoint_url = http://localhost:4566
                       region = us-east-1
```

!!! danger "Why a named profile is mandatory from here on"
    Until now every command ran as the Floci account root — effectively unlimited. **Any success you observed proves nothing about permissions.** From this lab onward, all enforcement testing runs under `--profile carol` (or an assumed-role profile), which is backed by a real IAM principal with real, limited policies.

#### Step 5.1 — Create a key and capture the secret exactly once

```bash
aws iam create-access-key --user-name dnb-dev-carol --output json > out/carol-key1.json
jq '{AccessKeyId: .AccessKey.AccessKeyId, Status: .AccessKey.Status, CreateDate: .AccessKey.CreateDate}' out/carol-key1.json
chmod 600 out/carol-key1.json
```

```json
{
  "AccessKey": {
    "UserName": "dnb-dev-carol",
    "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "Status": "Active",
    "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "CreateDate": "2026-08-04T10:02:11+00:00"
  }
}
```

!!! danger "`SecretAccessKey` appears in this response and never again"
    There is no `get-secret-access-key` API. If you lose it, your only recourse is `delete-access-key` + `create-access-key`. In production you would inject it straight into Secrets Manager or your CI secret store, never write it to disk — and `out/carol-key1.json` on your lab machine is itself a bad habit we are permitting only because these are throwaway emulator credentials.

#### Step 5.2 — Configure a named profile

```bash
CK_ID="$(jq -r '.AccessKey.AccessKeyId' out/carol-key1.json)"
CK_SECRET="$(jq -r '.AccessKey.SecretAccessKey' out/carol-key1.json)"

aws configure set aws_access_key_id     "$CK_ID"     --profile carol
aws configure set aws_secret_access_key "$CK_SECRET" --profile carol
aws configure set region                us-east-1    --profile carol
aws configure set endpoint_url          "$AWS_ENDPOINT_URL" --profile carol
aws configure set output                json         --profile carol

# The env vars from `floci env` OUTRANK the profile. Blank them for profile calls.
carol() { AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_SESSION_TOKEN= aws --profile carol "$@"; }

carol sts get-caller-identity
```

| Setting | Why |
|---|---|
| `endpoint_url` in the profile | AWS CLI v2 (≥2.13) honours `endpoint_url` in `~/.aws/config`; keeps the profile pinned to Floci even if env vars are lost |
| Blanking `AWS_ACCESS_KEY_ID`/`SECRET`/`SESSION_TOKEN` in the `carol()` wrapper | **Environment variables have higher precedence than profiles.** Without this, you would still be calling as root while believing you are Carol |

**Credential resolution order in the AWS CLI (examinable):**

```
  1. command-line flags/parameters
  2. environment variables  (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN)
  3. ~/.aws/credentials      [profile]
  4. ~/.aws/config           [profile x]  (incl. sso / credential_process / role_arn)
  5. container credentials   (ECS task role — AWS_CONTAINER_CREDENTIALS_RELATIVE_URI)
  6. instance profile        (EC2 IMDS at 169.254.169.254)
```

Expected:

```json
{
  "UserId": "AIDAEXAMPLEID7654321",
  "Account": "000000000000",
  "Arn": "arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-carol"
}
```

!!! tip "If that ARN still says `:root`, stop"
    Your wrapper is not isolating the environment. Fix it before continuing — every enforcement result from here on is meaningless otherwise.

#### Step 5.3 — Exercise Carol's actual permissions (first real enforcement test)

```bash
echo "--- SHOULD SUCCEED (auditor has s3:ListBucket + GetObject) ---"
carol s3 ls s3://dnb-statements-dev/ --recursive
carol s3 cp s3://dnb-statements-dev/2026/07/statement-1001.csv - 2>/dev/null | head -1

echo "--- SHOULD FAIL (auditor inline policy Denies all writes) ---"
echo "tamper" > out/tamper.txt
carol s3 cp out/tamper.txt s3://dnb-statements-dev/tamper.txt 2>&1 | tail -2

echo "--- SHOULD FAIL (auditor has no iam:CreateUser) ---"
carol iam create-user --user-name dnb-should-not-exist 2>&1 | tail -2

echo "--- SHOULD SUCCEED (auditor has iam:List*) ---"
carol iam list-users --query 'length(Users)' --output text
```

**AWS-correct verdicts:**

| Command | AWS verdict | Reason |
|---|---|---|
| `s3 ls s3://dnb-statements-dev/` | **Allow** | `dnb-s3-audit-read` Sid `ListBothBuckets` |
| `s3 cp … s3://…/statement-1001.csv -` | **Allow** | Sid `ReadObjectsInBothBuckets` |
| `s3 cp out/tamper.txt s3://…` | **Deny** | inline `DenyAuditorsAnyWrite` — `s3:PutObject` is not in the `NotAction` allow-list, and explicit deny is final |
| `iam create-user` | **Deny** | no `Allow` for `iam:CreateUser` anywhere (implicit deny) **and** an explicit deny from the inline policy |
| `iam list-users` | **Allow** | `iam:List*` in `dnb-s3-audit-read` |

Now compare with what your build did:

```bash
chmod +x ~/iam-lab/probe-enforcement.sh
./probe-enforcement.sh carol allow aws s3 ls s3://dnb-statements-dev/
./probe-enforcement.sh carol deny  aws s3 cp out/tamper.txt s3://dnb-statements-dev/tamper.txt
./probe-enforcement.sh carol deny  aws iam create-user --user-name dnb-should-not-exist
./probe-enforcement.sh carol allow aws iam list-users
```

```
ENFORCED-CORRECTLY  expect=allow actual=allow  cmd=aws s3 ls s3://dnb-statements-dev/
DIVERGES-FROM-AWS   expect=deny  actual=allow  cmd=aws s3 cp out/tamper.txt s3://dnb-statements-dev/tamper.txt
DIVERGES-FROM-AWS   expect=deny  actual=allow  cmd=aws iam create-user --user-name dnb-should-not-exist
ENFORCED-CORRECTLY  expect=allow actual=allow  cmd=aws iam list-users
```

!!! danger "Interpreting `DIVERGES-FROM-AWS` correctly"
    If your build allowed the write, it means **this Floci build does not evaluate identity policies for that service's data plane.** Your policy is still *correct*; the emulator simply is not the enforcement point. Write in your logbook:

    > `s3:PutObject` under `dnb-dev-carol`: AWS would return `AccessDenied` because the inline policy `DenyAuditorsAnyWrite` explicitly denies every action outside its `NotAction` list, and explicit deny is final in the evaluation pipeline. My Floci build returned success — enforcement not emulated for S3 data-plane calls.

    Then clean up the object you should not have been able to create:

    ```bash
    aws s3 rm s3://dnb-statements-dev/tamper.txt 2>/dev/null
    aws iam delete-user --user-name dnb-should-not-exist 2>/dev/null
    ```

#### Step 5.4 — Four-phase zero-downtime rotation

```
  PHASE 1  create the second key            keys: [old Active] [new Active]
  PHASE 2  deploy the new key everywhere    apps now use new
  PHASE 3  mark the old key Inactive        keys: [old Inactive] [new Active]
           ── OBSERVE for 24–48 h ──        if anything breaks, reactivate instantly
  PHASE 4  delete the old key               keys: [new Active]

  ✗ WRONG: delete-then-create  → outage between the two calls
  ✗ WRONG: skip phase 3        → no rollback path, and no way to detect
                                  a forgotten consumer of the old key
```

```bash
OLD_KEY="$CK_ID"

# PHASE 1
aws iam create-access-key --user-name dnb-dev-carol --output json > out/carol-key2.json
NEW_KEY="$(jq -r '.AccessKey.AccessKeyId'     out/carol-key2.json)"
NEW_SEC="$(jq -r '.AccessKey.SecretAccessKey' out/carol-key2.json)"
aws iam list-access-keys --user-name dnb-dev-carol \
  --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output table

# PHASE 2 — deploy (here: update the profile)
aws configure set aws_access_key_id     "$NEW_KEY" --profile carol
aws configure set aws_secret_access_key "$NEW_SEC" --profile carol
carol sts get-caller-identity --query Arn --output text     # must still be Carol

# PHASE 3 — deactivate, do not delete
aws iam update-access-key --user-name dnb-dev-carol --access-key-id "$OLD_KEY" --status Inactive
aws iam list-access-keys --user-name dnb-dev-carol \
  --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output table

# Verify the deactivated key is genuinely rejected (AWS: InvalidClientTokenId)
AWS_ACCESS_KEY_ID="$OLD_KEY" AWS_SECRET_ACCESS_KEY="$CK_SECRET" AWS_SESSION_TOKEN= \
  aws sts get-caller-identity 2>&1 | tail -2

# PHASE 4 — delete
aws iam delete-access-key --user-name dnb-dev-carol --access-key-id "$OLD_KEY"
aws iam list-access-keys --user-name dnb-dev-carol --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output table
```

| Parameter | Meaning |
|---|---|
| `update-access-key --status Inactive` | Key still exists but must be rejected at authentication. **The reversible step.** |
| `--status Active` | Reactivate — the rollback |
| `delete-access-key` | Irreversible |

!!! note "Probe: does your build reject an Inactive key?"
    Real AWS returns `InvalidClientTokenId: The security token included in the request is invalid`. If Floci still authenticates it, record the divergence. This matters: in an incident, "I deactivated the leaked key" must actually mean the key is dead.

#### Step 5.5 — The third key

```bash
aws iam create-access-key --user-name dnb-dev-carol >/dev/null 2>&1
aws iam create-access-key --user-name dnb-dev-carol 2>&1 | tail -2
```

Expected in real AWS: `LimitExceeded: Cannot exceed quota for AccessKeysPerUser: 2`.

```bash
# Trim back to exactly one active key
for k in $(aws iam list-access-keys --user-name dnb-dev-carol \
             --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  [ "$k" = "$NEW_KEY" ] || aws iam delete-access-key --user-name dnb-dev-carol --access-key-id "$k"
done
aws iam list-access-keys --user-name dnb-dev-carol --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output table
```

#### Step 5.6 — Key age audit (the script you will reuse in your career)

```bash
cat > key-age-audit.sh <<'SCRIPT'
#!/usr/bin/env bash
# Report every access key older than N days (default 90).
set -euo pipefail
MAX_DAYS="${1:-90}"
NOW=$(date -u +%s)
printf '%-24s %-22s %-10s %-8s %s\n' USER KEY STATUS AGE_DAYS VERDICT
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do
  aws iam list-access-keys --user-name "$u" \
      --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output text |
  while read -r kid status created; do
    [ -z "${kid:-}" ] && continue
    cs=$(date -u -d "$created" +%s 2>/dev/null || date -u -jf '%Y-%m-%dT%H:%M:%S+00:00' "$created" +%s 2>/dev/null || echo "$NOW")
    age=$(( (NOW - cs) / 86400 ))
    verdict=OK; [ "$age" -gt "$MAX_DAYS" ] && verdict="ROTATE-NOW"
    printf '%-24s %-22s %-10s %-8s %s\n' "$u" "$kid" "$status" "$age" "$verdict"
  done
done
SCRIPT
chmod +x key-age-audit.sh
./key-age-audit.sh 90
```

**Verification**

```bash
test "$(aws iam list-access-keys --user-name dnb-dev-carol --query 'length(AccessKeyMetadata)' --output text)" = "1" \
  && echo "PASS: exactly one key" || echo "FAIL"
carol sts get-caller-identity --query Arn --output text | grep -q dnb-dev-carol \
  && echo "PASS: profile works" || echo "FAIL"
```

**Lab 5 recap.** Access keys are the only long-term programmatic credential; max two per user precisely to enable rotation. Environment variables outrank profiles. A named profile backed by a real IAM user is the only way to test enforcement. Rotation is four phases, and phase 3 (deactivate + observe) is the one people skip.

---

### Lab 6 — Roles, Trust Policies, AssumeRole, and Role Chaining

**Objective.** Replace the `dnb-svc-batch` user anti-pattern with a role; write trust policies; obtain and use temporary credentials; observe role chaining's 1-hour cap.

**Prerequisites.** Labs 1–5.

**Architecture.**

```
  dnb-dev-alice (user, has an access key)
      │  identity policy: sts:AssumeRole on dnb-dev-batch-role
      ▼
  dnb-dev-batch-role
      ├── TRUST:       Principal = user/dnb/dev/dnb-dev-alice
      └── PERMISSIONS: dnb-s3-batch-write  (Put/Get on statements + audit-logs)
      │
      │  chained assume (session capped at 1 h)
      ▼
  dnb-dev-reporting-role
      ├── TRUST:       Principal = role/dnb-dev-batch-role
      └── PERMISSIONS: read-only on dnb-audit-logs-dev
```

#### Step 6.1 — Give Alice a key and a profile

```bash
aws iam create-access-key --user-name dnb-dev-alice --output json > out/alice-key.json
chmod 600 out/alice-key.json
aws configure set aws_access_key_id     "$(jq -r '.AccessKey.AccessKeyId' out/alice-key.json)"     --profile alice
aws configure set aws_secret_access_key "$(jq -r '.AccessKey.SecretAccessKey' out/alice-key.json)" --profile alice
aws configure set region us-east-1 --profile alice
aws configure set endpoint_url "$AWS_ENDPOINT_URL" --profile alice
alice() { AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_SESSION_TOKEN= aws --profile alice "$@"; }
alice sts get-caller-identity --query Arn --output text
```

#### Step 6.2 — Create the role with a trust policy

```bash
cat > policies/trust-batch-role.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAliceToAssume",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/dnb-dev-alice"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
jq empty policies/trust-batch-role.json && echo valid

aws iam create-role \
  --role-name dnb-dev-batch-role \
  --path /dnb/dev/ \
  --description "Nightly statement batch job — replaces the dnb-svc-batch user" \
  --assume-role-policy-document file://policies/trust-batch-role.json \
  --max-session-duration 3600 \
  --tags $TAGS Key=Workload,Value=NightlyBatch \
  --query 'Role.[RoleName,Arn,MaxSessionDuration]' --output text
```

| Parameter | Meaning | Notes |
|---|---|---|
| `--assume-role-policy-document` | **The trust policy** (resource-based) | Answers *who may assume*, never *what it can do* |
| `--max-session-duration` | 3 600 – 43 200 s | Caps `--duration-seconds` at assume time. Default 3 600 |
| `--description` | Mutable via `update-role` (unlike policy descriptions) | |
| `--permissions-boundary` | Lab 9 | |
| `--path` | Immutable | |

```
dnb-dev-batch-role  arn:aws:iam::000000000000:role/dnb/dev/dnb-dev-batch-role  3600
```

!!! danger "A role with only a trust policy can do nothing"
    You have created an identity that Alice may become — and which, right now, has **zero** permissions. Two policies are always required. Forgetting the second half is the number-one role bug in the field.

#### Step 6.3 — Attach permissions to the role

```bash
cat > policies/dnb-s3-batch-write.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTargetBuckets",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-audit-logs-dev"
      ]
    },
    {
      "Sid": "WriteGeneratedStatements",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*"
    },
    {
      "Sid": "AppendToAuditLog",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::dnb-audit-logs-dev/batch/*"
    },
    {
      "Sid": "NeverDeleteAnything",
      "Effect": "Deny",
      "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:DeleteBucket"],
      "Resource": "*"
    }
  ]
}
JSON
jq empty policies/dnb-s3-batch-write.json && echo valid

BATCH_ARN="$(aws iam create-policy --policy-name dnb-s3-batch-write --path /dnb/ \
  --description "Write statements, append audit log, never delete" \
  --policy-document file://policies/dnb-s3-batch-write.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-role-policy --role-name dnb-dev-batch-role --policy-arn "$BATCH_ARN"
echo "$BATCH_ARN" | tee out/batch-policy-arn.txt

aws iam list-attached-role-policies --role-name dnb-dev-batch-role \
  --query 'AttachedPolicies[].PolicyName' --output text
```

!!! tip "The `NeverDeleteAnything` statement is doing real work"
    Even if someone later attaches `AdministratorAccess` to this role, the explicit `Deny` still blocks deletes. This is the correct way to encode "this workload is append-only" as an invariant rather than a hope.

#### Step 6.4 — Grant Alice permission to assume it

Remember: **both** sides must allow.

```bash
cat > policies/dnb-assume-batch-role.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeTheBatchRole",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role"
    }
  ]
}
JSON
jq empty policies/dnb-assume-batch-role.json && echo valid

ASSUME_ARN="$(aws iam create-policy --policy-name dnb-assume-batch-role --path /dnb/ \
  --description "Allows developers to assume the batch role" \
  --policy-document file://policies/dnb-assume-batch-role.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-group-policy --group-name dnb-developers --policy-arn "$ASSUME_ARN"
echo "$ASSUME_ARN" | tee out/assume-policy-arn.txt
```

#### Step 6.5 — Assume the role

```bash
alice sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role" \
  --role-session-name "alice-nightly-batch-$(date -u +%Y%m%dT%H%M%SZ)" \
  --duration-seconds 3600 \
  --output json > out/batch-session.json

jq '{AccessKeyId: .Credentials.AccessKeyId,
     Expiration: .Credentials.Expiration,
     AssumedRoleArn: .AssumedRoleUser.Arn,
     AssumedRoleId: .AssumedRoleUser.AssumedRoleId}' out/batch-session.json
```

| Parameter | Meaning |
|---|---|
| `--role-arn` | The role to become |
| `--role-session-name` | 2–64 chars. **Appears in the session ARN and in every CloudTrail event.** Use the human's identity or the job id — never `session1` |
| `--duration-seconds` | 900 – role's `MaxSessionDuration`. Shorter is safer |
| `--policy` / `--policy-arns` | Session policy (Lab 9) |
| `--external-id` | Required if the trust policy demands `sts:ExternalId` |
| `--serial-number` / `--token-code` | MFA, if the trust policy requires it |
| `--tags` / `--transitive-tag-keys` | Session tags for ABAC; transitive ones survive chaining |
| `--source-identity` | Immutable attribution that survives role chaining |

```json
{
  "AccessKeyId": "ASIAEXAMPLETEMPKEY01",
  "Expiration": "2026-08-04T11:14:52+00:00",
  "AssumedRoleArn": "arn:aws:sts::000000000000:assumed-role/dnb-dev-batch-role/alice-nightly-batch-20260804T101452Z",
  "AssumedRoleId": "AROAEXAMPLEROLEID:alice-nightly-batch-20260804T101452Z"
}
```

!!! warning "Look at that ARN — it is `sts:assumed-role`, not `iam:role`"
    `arn:aws:sts::000000000000:assumed-role/<RoleName>/<SessionName>`. Note also that the **path is dropped** from the assumed-role ARN even though the role was created at `/dnb/dev/`. Any condition you write against the caller's ARN must match this form, not the `iam` form. This trips up almost everyone once.

#### Step 6.6 — Use the temporary credentials

```bash
export AWS_ACCESS_KEY_ID="$(jq -r '.Credentials.AccessKeyId'     out/batch-session.json)"
export AWS_SECRET_ACCESS_KEY="$(jq -r '.Credentials.SecretAccessKey' out/batch-session.json)"
export AWS_SESSION_TOKEN="$(jq -r '.Credentials.SessionToken'    out/batch-session.json)"

aws sts get-caller-identity
```

```json
{
  "UserId": "AROAEXAMPLEROLEID:alice-nightly-batch-20260804T101452Z",
  "Account": "000000000000",
  "Arn": "arn:aws:sts::000000000000:assumed-role/dnb-dev-batch-role/alice-nightly-batch-20260804T101452Z"
}
```

```bash
echo "ACCT-1002,2026-08,BTN 12750.00" > out/statement-1002.csv
aws s3 cp out/statement-1002.csv s3://dnb-statements-dev/2026/08/statement-1002.csv     # allow
echo "batch run ok $(date -u +%FT%TZ)" > out/batchlog.txt
aws s3 cp out/batchlog.txt s3://dnb-audit-logs-dev/batch/run.log                        # allow
aws s3 rm s3://dnb-statements-dev/2026/08/statement-1002.csv 2>&1 | tail -2             # AWS: DENY
aws iam list-users 2>&1 | tail -2                                                        # AWS: DENY
```

**AWS-correct verdicts:** the two `cp` calls succeed; `s3 rm` hits the explicit `NeverDeleteAnything` deny; `iam list-users` hits implicit deny (the role has no IAM permissions). Run these through `probe-enforcement.sh` logic and record divergences.

!!! danger "Always restore your shell"
    ```bash
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
    eval "$(floci env)"
    aws sts get-caller-identity --query Arn --output text   # back to root
    ```
    Forgetting this is the cause of half of all "why is this command suddenly failing?" moments in the next lab.

#### Step 6.7 — A cleaner way: `role_arn` in the profile

The AWS CLI can assume a role for you on every call, refreshing automatically.

```bash
aws configure set role_arn        "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role" --profile batch
aws configure set source_profile  alice        --profile batch
aws configure set role_session_name "cli-batch" --profile batch
aws configure set region          us-east-1    --profile batch
aws configure set endpoint_url    "$AWS_ENDPOINT_URL" --profile batch

batch() { AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_SESSION_TOKEN= aws --profile batch "$@"; }
batch sts get-caller-identity --query Arn --output text
```

| Setting | Meaning |
|---|---|
| `role_arn` | Role to assume |
| `source_profile` | Profile whose credentials perform the `AssumeRole` |
| `role_session_name` | Session name (auto-generated if omitted) |
| `external_id`, `mfa_serial`, `duration_seconds` | Optional counterparts of the CLI flags |

This is how professionals work day to day. No manual token juggling.

#### Step 6.8 — Role chaining and the one-hour cap

```bash
cat > policies/trust-reporting-role.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowBatchRoleToChain",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

aws iam create-role --role-name dnb-dev-reporting-role --path /dnb/dev/ \
  --description "Read audit logs to build the nightly report" \
  --assume-role-policy-document file://policies/trust-reporting-role.json \
  --max-session-duration 43200 \
  --tags $TAGS --query 'Role.Arn' --output text

cat > policies/dnb-audit-read.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAuditLogs",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject"],
      "Resource": [
        "arn:aws:s3:::dnb-audit-logs-dev",
        "arn:aws:s3:::dnb-audit-logs-dev/*"
      ]
    }
  ]
}
JSON
REPORT_ARN="$(aws iam create-policy --policy-name dnb-audit-read --path /dnb/ \
  --description "Read-only on the audit log bucket" \
  --policy-document file://policies/dnb-audit-read.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-role-policy --role-name dnb-dev-reporting-role --policy-arn "$REPORT_ARN"
echo "$REPORT_ARN" | tee out/report-policy-arn.txt

# The batch role also needs sts:AssumeRole on the reporting role
cat > policies/inline-batch-can-chain.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ChainToReportingRole",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-reporting-role"
    }
  ]
}
JSON
aws iam put-role-policy --role-name dnb-dev-batch-role \
  --policy-name AllowChainToReporting \
  --policy-document file://policies/inline-batch-can-chain.json
```

```bash
# Chain: user → batch-role → reporting-role
echo "--- chained assume with a legal duration (<= 3600) ---"
batch sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-reporting-role" \
  --role-session-name chained-report \
  --duration-seconds 3600 \
  --query 'Credentials.Expiration' --output text

echo "--- chained assume asking for 4 hours: AWS REJECTS THIS ---"
batch sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-reporting-role" \
  --role-session-name chained-report-long \
  --duration-seconds 14400 2>&1 | tail -3
```

Expected in real AWS:

```
An error occurred (ValidationError) when calling the AssumeRole operation:
The requested DurationSeconds exceeds the 1 hour session limit for roles assumed by role chaining.
```

```
  DIRECT ASSUME                          CHAINED ASSUME
  user ──► role                          user ──► roleA ──► roleB
  duration ≤ MaxSessionDuration          duration ≤ 3600  ALWAYS
           (up to 12 h)                  (MaxSessionDuration of roleB is IGNORED)
```

!!! tip "Design implication"
    A long-running job that needs >1 h must **not** be built on chained roles. Either assume the final role directly, or have the job refresh its credentials. This is a real production failure mode: the job runs fine for 59 minutes and then dies with `ExpiredToken`.

#### Break it — four trust-policy failures

```bash
# (a) Wrong ExternalId
cat > policies/trust-external.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ThirdPartyWithSecret",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/dnb-dev-alice" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "dnb-audit-2026-7f3ac1" } }
  }]
}
JSON
aws iam create-role --role-name dnb-dev-external-role \
  --assume-role-policy-document file://policies/trust-external.json \
  --tags $TAGS --query 'Role.Arn' --output text

echo "--- no external id: AWS denies ---"
alice sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dev-external-role" \
  --role-session-name no-eid 2>&1 | tail -2
echo "--- wrong external id: AWS denies ---"
alice sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dev-external-role" \
  --role-session-name bad-eid --external-id wrong-secret 2>&1 | tail -2
echo "--- correct external id: AWS allows ---"
alice sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dev-external-role" \
  --role-session-name good-eid --external-id dnb-audit-2026-7f3ac1 \
  --query 'AssumedRoleUser.Arn' --output text 2>&1 | tail -2
```

```bash
# (b) Duration exceeding the role's MaxSessionDuration
alice sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role" \
  --role-session-name too-long --duration-seconds 7200 2>&1 | tail -2
```

Expected: `ValidationError: The requested DurationSeconds exceeds the MaxSessionDuration set for this role.`

```bash
# Fix by raising the role's ceiling
aws iam update-role --role-name dnb-dev-batch-role --max-session-duration 7200
aws iam get-role --role-name dnb-dev-batch-role --query 'Role.MaxSessionDuration' --output text
aws iam update-role --role-name dnb-dev-batch-role --max-session-duration 3600   # restore least privilege
```

```bash
# (c) A user NOT trusted by the role
carol sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role" \
  --role-session-name carol-tries 2>&1 | tail -2
```

Expected: `AccessDenied: User: arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-carol is not authorized to perform: sts:AssumeRole on resource: …` — and note it fails on **both** counts: Carol has no `sts:AssumeRole` grant, and the trust policy does not name her.

```bash
# (d) Using temp creds without the session token
export AWS_ACCESS_KEY_ID="$(jq -r '.Credentials.AccessKeyId'     out/batch-session.json)"
export AWS_SECRET_ACCESS_KEY="$(jq -r '.Credentials.SecretAccessKey' out/batch-session.json)"
unset AWS_SESSION_TOKEN
aws sts get-caller-identity 2>&1 | tail -2
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; eval "$(floci env)"
```

Expected: `InvalidClientTokenId: The security token included in the request is invalid.`

!!! tip "Diagnostic rule"
    `ASIA…` key + missing `AWS_SESSION_TOKEN` → always `InvalidClientTokenId`. If you see that error, check for the session token before anything else.

#### Step 6.9 — Retire the anti-pattern

```bash
# The batch job now uses a role. Delete the service user's credentials.
for k in $(aws iam list-access-keys --user-name dnb-svc-batch --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null); do
  aws iam delete-access-key --user-name dnb-svc-batch --access-key-id "$k"
done
aws iam tag-user --user-name dnb-svc-batch --tags Key=Status,Value=Deprecated Key=ReplacedBy,Value=dnb-dev-batch-role
aws iam list-user-tags --user-name dnb-svc-batch --query 'Tags[?Key==`ReplacedBy`]' --output table
```

**Write in your logbook:** three concrete advantages the role has over the user it replaced. (Expected: no long-term secret to leak or rotate; credentials expire automatically; the session name gives per-run attribution in CloudTrail; permissions can be scoped per-session.)

#### Verification

```bash
aws iam get-role --role-name dnb-dev-batch-role \
  --query 'Role.{Name: RoleName, MaxSession: MaxSessionDuration, Trust: AssumeRolePolicyDocument.Statement[0].Principal}'
aws iam list-attached-role-policies --role-name dnb-dev-batch-role --query 'AttachedPolicies[].PolicyName' --output text
aws iam list-role-policies --role-name dnb-dev-batch-role --query 'PolicyNames' --output text
batch sts get-caller-identity --query Arn --output text | grep -q assumed-role && echo "PASS: chained profile works"
```

**Lab 6 recap.** A role needs a trust policy *and* permissions policies, and assumption needs an allow on *both* sides. Assumed-role ARNs use the `sts` service and drop the path. Chained sessions are capped at one hour. `ExternalId` defends against the confused deputy. `role_arn` + `source_profile` is the professional workflow.

---

### Lab 7 — Instance Profiles: Giving an EC2 Instance a Role

**Objective.** Build the EC2 credential-delivery chain with no secrets on disk.

**Prerequisites.** Lab 6. Check your support matrix for `iam:*instance-profile*` and EC2 support.

**Architecture.**

```
  EC2 instance
      │  IamInstanceProfile = dnb-dev-app-profile
      ▼
  instance profile dnb-dev-app-profile   (1 profile : 1 role)
      ▼
  role dnb-dev-app-role
      ├── trust: Service = ec2.amazonaws.com
      └── perms: dnb-s3-statements-read (from Lab 3)
      ▼
  IMDS 169.254.169.254 → ASIA… + token, auto-rotated
```

#### Step 7.1 — Role with a service principal

```bash
cat > policies/trust-ec2.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEc2ServiceToAssume",
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
jq empty policies/trust-ec2.json && echo valid

aws iam create-role --role-name dnb-dev-app-role --path /dnb/dev/ \
  --description "Statement-serving app tier on EC2" \
  --assume-role-policy-document file://policies/trust-ec2.json \
  --max-session-duration 3600 \
  --tags $TAGS Key=Workload,Value=AppTier \
  --query 'Role.Arn' --output text

aws iam attach-role-policy --role-name dnb-dev-app-role \
  --policy-arn "$(cat out/policy-arn.txt)"
```

!!! warning "Service principals are literal strings"
    `ec2.amazonaws.com` — not `ec2.us-east-1.amazonaws.com`, not `EC2`, not `ec2`. Get one character wrong and the role exists but can never be assumed by EC2, with no error until launch time. Common ones: `lambda.amazonaws.com`, `ecs-tasks.amazonaws.com`, `rds.amazonaws.com`, `states.amazonaws.com`, `events.amazonaws.com`, `apigateway.amazonaws.com`, `codebuild.amazonaws.com`, `glue.amazonaws.com`.

#### Step 7.2 — Create and populate the instance profile

```bash
aws iam create-instance-profile \
  --instance-profile-name dnb-dev-app-profile \
  --path /dnb/dev/ \
  --tags $TAGS \
  --query 'InstanceProfile.[InstanceProfileName,Arn]' --output text

aws iam add-role-to-instance-profile \
  --instance-profile-name dnb-dev-app-profile \
  --role-name dnb-dev-app-role

aws iam get-instance-profile --instance-profile-name dnb-dev-app-profile \
  --query 'InstanceProfile.{Profile: InstanceProfileName, Roles: Roles[].RoleName}'
```

```json
{
  "Profile": "dnb-dev-app-profile",
  "Roles": ["dnb-dev-app-role"]
}
```

!!! tip "Why the console hides this step"
    In the AWS Console, creating an "EC2 role" silently creates a same-named instance profile for you. Via CLI/CloudFormation/Terraform you must create it explicitly. Every engineer discovers this the hard way exactly once — usually with `Invalid IAM Instance Profile name`.

#### Step 7.3 — The one-role limit

```bash
aws iam create-role --role-name dnb-dev-second-role \
  --assume-role-policy-document file://policies/trust-ec2.json \
  --tags $TAGS --query 'Role.RoleName' --output text

aws iam add-role-to-instance-profile \
  --instance-profile-name dnb-dev-app-profile \
  --role-name dnb-dev-second-role 2>&1 | tail -2
```

Expected: `LimitExceeded: Cannot exceed quota for InstanceSessionsPerInstanceProfile: 1` (message wording varies; the constraint is one role per profile).

```bash
aws iam delete-role --role-name dnb-dev-second-role
```

#### Step 7.4 — Attach to an instance

```bash
# Discover a usable AMI in this environment
AMI_ID="$(aws ec2 describe-images --query 'Images[0].ImageId' --output text 2>/dev/null)"
echo "AMI=$AMI_ID"

if [ -n "$AMI_ID" ] && [ "$AMI_ID" != "None" ]; then
  INSTANCE_ID="$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type t3.micro \
    --iam-instance-profile Name=dnb-dev-app-profile \
    --metadata-options 'HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=dnb-dev-app-01},{Key=Project,Value=CoreBanking},{Key=Environment,Value=dev}]' \
    --query 'Instances[0].InstanceId' --output text)"
  echo "INSTANCE_ID=$INSTANCE_ID" | tee out/instance-id.txt

  aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].{Id: InstanceId, State: State.Name, Profile: IamInstanceProfile.Arn, Imds: MetadataOptions.HttpTokens}'
else
  echo "EC2 image listing unsupported in this build — record as a divergence and read the block below."
fi
```

| Parameter | Meaning |
|---|---|
| `--iam-instance-profile Name=…` | Attach the profile at launch. `Arn=…` also accepted |
| `--metadata-options HttpTokens=required` | **Force IMDSv2.** Requires a PUT to obtain a session token before any metadata GET |
| `HttpPutResponseHopLimit=1` | Metadata responses cannot leave the instance — blocks container/SSRF pivots |
| `--tag-specifications` | Tags applied atomically at launch, so ABAC and cost allocation work from second zero |

```json
{
  "Id": "i-0abc123def4567890",
  "State": "running",
  "Profile": "arn:aws:iam::000000000000:instance-profile/dnb/dev/dnb-dev-app-profile",
  "Imds": "required"
}
```

#### Step 7.5 — Attach/replace on a running instance

```bash
if [ -f out/instance-id.txt ]; then
  . out/instance-id.txt
  ASSOC="$(aws ec2 describe-iam-instance-profile-associations \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'IamInstanceProfileAssociations[0].AssociationId' --output text 2>/dev/null)"
  echo "association=$ASSOC"
  # Replace (zero downtime) — NOT disassociate-then-associate
  # aws ec2 replace-iam-instance-profile-association --association-id "$ASSOC" \
  #     --iam-instance-profile Name=dnb-dev-other-profile
fi
```

| Operation | Use |
|---|---|
| `associate-iam-instance-profile` | Attach to an instance that has none |
| `replace-iam-instance-profile-association` | **Swap** profiles with no gap — the correct way to change a running instance's role |
| `disassociate-iam-instance-profile` | Remove entirely (creates a credential gap) |

!!! note "IMDS in Floci"
    Real AWS serves credentials at `http://169.254.169.254/latest/meta-data/iam/security-credentials/<role-name>`, and with IMDSv2 that requires:

    ```bash
    TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
    curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
      http://169.254.169.254/latest/meta-data/iam/security-credentials/dnb-dev-app-role
    ```

    Floci is unlikely to emulate the link-local IMDS address. Verify the **IAM side** (profile exists, contains the role, role has permissions, instance shows `IamInstanceProfile`) and treat credential *delivery* as conceptual. Record it in your logbook.

#### Break it — the two classic instance-profile errors

```bash
# (a) Referencing a non-existent profile
aws ec2 run-instances --image-id "${AMI_ID:-ami-00000000}" --instance-type t3.micro \
  --iam-instance-profile Name=dnb-does-not-exist 2>&1 | tail -2
```

Expected: `Invalid IAM Instance Profile name` / `NoSuchEntity`.

```bash
# (b) Deleting a profile that still holds a role
aws iam delete-instance-profile --instance-profile-name dnb-dev-app-profile 2>&1 | tail -2
```

Expected: `DeleteConflict: Cannot delete entity, must remove roles from instance profile first.`

**Fix:** `remove-role-from-instance-profile` then `delete-instance-profile`.

**Verification**

```bash
aws iam get-instance-profile --instance-profile-name dnb-dev-app-profile \
  --query 'InstanceProfile.Roles[0].RoleName' --output text | grep -q dnb-dev-app-role && echo "PASS"
aws iam get-role --role-name dnb-dev-app-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text | grep -q ec2 && echo "PASS: trust ok"
```

**Lab 7 recap.** EC2 → instance profile → role → IMDS. One role per profile, one profile per instance. Always enforce IMDSv2. Use `replace-…-association` to change roles without a credential gap.

---

### Lab 8 — Resource-Based Policies: Identity vs Resource, and Cross-Account

**Objective.** Write an S3 bucket policy; reason about the OR (same account) / AND (cross account) rule; use a bucket policy as a hard guardrail.

**Prerequisites.** Labs 3, 6. Check support for `s3api put-bucket-policy`.

**Architecture.**

```
                identity-based               resource-based
   Carol ──────► dnb-s3-audit-read  ─┐   ┌─ bucket policy on dnb-statements-dev
   (auditor)     (Allow Get/List)    │   │    ├ Allow  role/dnb-dev-batch-role : Put/Get
                                     ├OR─┤    ├ Deny   * : * if aws:SecureTransport = false
   batch role ─► dnb-s3-batch-write ─┘   │    └ Deny   * : s3:DeleteBucket
                                          └─ (evaluated together, same account → OR)
```

#### Step 8.1 — Write the bucket policy

```bash
cat > policies/bucket-policy-statements.json <<JSON
{
  "Version": "2012-10-17",
  "Id": "DnbStatementsBucketPolicy",
  "Statement": [
    {
      "Sid": "AllowBatchRoleReadWrite",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role"
      },
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*"
    },
    {
      "Sid": "AllowAuditorList",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/dnb-dev-carol"
      },
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::dnb-statements-dev"
    },
    {
      "Sid": "DenyUnencryptedTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    },
    {
      "Sid": "NobodyMayDeleteThisBucket",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:DeleteBucket", "s3:DeleteBucketPolicy"],
      "Resource": "arn:aws:s3:::dnb-statements-dev"
    }
  ]
}
JSON
jq empty policies/bucket-policy-statements.json && echo valid

aws s3api put-bucket-policy --bucket dnb-statements-dev \
  --policy file://policies/bucket-policy-statements.json

aws s3api get-bucket-policy --bucket dnb-statements-dev \
  --query Policy --output text | jq '.Statement[].Sid'
```

```
"AllowBatchRoleReadWrite"
"AllowAuditorList"
"DenyUnencryptedTransport"
"NobodyMayDeleteThisBucket"
```

| Element | Note |
|---|---|
| `Principal` | **Required** — this is what makes it a resource-based policy |
| `Id` | Optional policy identifier, allowed in bucket policies |
| `"Principal": "*"` with `Effect: Deny` | Safe and idiomatic — "nobody, ever" |
| `"Principal": "*"` with `Effect: Allow` | **Public access.** Almost always a critical finding |

!!! danger "`NobodyMayDeleteThisBucket` includes `s3:DeleteBucketPolicy` deliberately"
    Without that, an administrator could delete the policy and then delete the bucket. Guardrails must protect themselves. Note the escape hatch: in real AWS the **account root user** can always remove a bucket policy that has locked everyone out — which is one of the few legitimate reasons root exists.

#### Step 8.2 — Reason about OR vs AND

Fill this in yourself before running anything:

| # | Principal | Identity policy says | Bucket policy says | Same account? | AWS verdict |
|---|---|---|---|---|---|
| 1 | Carol | Allow `s3:GetObject` on `…/*` | silent on Carol+GetObject | yes | ? |
| 2 | Carol | Allow `s3:ListBucket` | Allow `s3:ListBucket` | yes | ? |
| 3 | Carol | silent | Allow `s3:GetBucketLocation` | yes | ? |
| 4 | batch role | Allow `s3:PutObject` | Allow `s3:PutObject` | yes | ? |
| 5 | batch role | **Deny** `s3:DeleteObject` | silent | yes | ? |
| 6 | anyone over plain HTTP | Allow | **Deny** on `SecureTransport=false` | yes | ? |
| 7 | a role in account `111111111111` | Allow `s3:GetObject` (in their account) | silent | **no** | ? |
| 8 | a role in account `111111111111` | Allow `s3:GetObject` | Allow that role | **no** | ? |

**Answers:** 1 Allow (identity alone suffices — same-account OR). 2 Allow. 3 Allow (resource alone suffices). 4 Allow. 5 **Deny** (explicit deny is final, and no `Allow` anywhere can override it). 6 **Deny**. 7 **Deny** (cross-account needs both; the resource side is missing). 8 Allow (both sides present).

```bash
echo "--- Carol: allowed by identity policy alone ---"
carol s3 cp s3://dnb-statements-dev/2026/07/statement-1001.csv - 2>&1 | head -1

echo "--- Carol: still denied writes (inline deny + no allow) ---"
carol s3 cp out/tamper.txt s3://dnb-statements-dev/blocked.txt 2>&1 | tail -2

echo "--- batch role: allowed to put, denied to delete ---"
batch s3 cp out/statement-1002.csv s3://dnb-statements-dev/2026/08/statement-1002.csv 2>&1 | tail -1
batch s3 rm s3://dnb-statements-dev/2026/08/statement-1002.csv 2>&1 | tail -2

echo "--- nobody may delete the bucket ---"
aws s3api delete-bucket --bucket dnb-statements-dev 2>&1 | tail -2
```

!!! warning "That last one should fail even as root-equivalent"
    In real AWS, `s3:DeleteBucket` on this bucket is explicitly denied for `Principal: "*"` — the deny reaches everyone, including IAM admins. (The account **root** user is the documented exception for regaining control of a bucket policy.) If your Floci build deletes the bucket, record the divergence — and recreate the bucket before continuing:

    ```bash
    aws s3 mb s3://dnb-statements-dev 2>/dev/null
    aws s3api put-bucket-policy --bucket dnb-statements-dev --policy file://policies/bucket-policy-statements.json 2>/dev/null
    ```

#### Step 8.3 — Cross-account, conceptually

Floci is a single account, so you cannot execute this. You must be able to write both halves.

**In account B (`222222222222`), the resource owner:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAuditAccountReadOnly",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::111111111111:role/dnb-central-audit-role" },
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-prod",
        "arn:aws:s3:::dnb-statements-prod/*"
      ],
      "Condition": {
        "StringEquals": { "aws:PrincipalOrgID": "o-druk1example" },
        "Bool": { "aws:SecureTransport": "true" }
      }
    }
  ]
}
```

**In account A (`111111111111`), the principal's identity policy:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadProdStatementsInAccountB",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-prod",
        "arn:aws:s3:::dnb-statements-prod/*"
      ]
    }
  ]
}
```

Both are required. Remove either and the request fails.

!!! tip "`aws:PrincipalOrgID` beats enumerating account IDs"
    With 40 accounts, `"Principal": {"AWS": ["arn:aws:iam::111…:root", "arn:aws:iam::222…:root", …]}` is unmaintainable and breaks whenever an account is added. One condition on `aws:PrincipalOrgID` covers the whole organisation and automatically excludes anyone outside it.

**S3 has a third layer, which you must also know:**

```
  Request to s3://bucket/key
        │
        ├─ Block Public Access settings (account level, then bucket level)  ← evaluated FIRST,
        │      BlockPublicPolicy / RestrictPublicBuckets / IgnorePublicAcls    overrides everything
        ├─ IAM identity policy
        ├─ Bucket policy
        ├─ Object ACL / Bucket ACL  (legacy; disable with Object Ownership = BucketOwnerEnforced)
        └─ VPC endpoint policy, if the request came via a gateway/interface endpoint
```

!!! danger "Block Public Access wins"
    If Block Public Access is on (and it is on by default for new buckets since 2023), a bucket policy granting `"Principal": "*"` is **ignored**. Candidates routinely answer "the bucket policy makes it public" and get the question wrong.

**Verification**

```bash
aws s3api get-bucket-policy --bucket dnb-statements-dev --query Policy --output text \
  | jq -e '.Statement | length == 4' >/dev/null && echo "PASS: 4 statements"
aws s3api get-bucket-policy --bucket dnb-statements-dev --query Policy --output text \
  | jq -r '.Statement[] | select(.Effect=="Deny") | .Sid'
```

**Lab 8 recap.** Resource-based policies require `Principal`. Same account = OR; cross-account = AND on both sides. Explicit deny in either policy is final. `"Principal": "*"` + `Allow` is public; `+ Deny` is a guardrail. For S3, Block Public Access sits above everything.

---

### Lab 9 — Permissions Boundaries and Session Policies

**Objective.** Build a safe IAM-delegation model; demonstrate that boundaries and session policies intersect rather than grant.

**Prerequisites.** Labs 1–8. Check your support matrix for `put-user-permissions-boundary` and expect enforcement to be **absent**.

**Architecture.**

```
  dnb-dev-bob (team lead — delegated IAM admin)
      ├── identity: dnb-delegated-iam-admin
      │      Allow  iam:CreateUser/CreateRole/Attach*  ONLY IF
      │             iam:PermissionsBoundary == dnb-boundary-developer
      │      Deny   iam:Delete*PermissionsBoundary
      └── boundary: dnb-boundary-developer   ← Bob himself is bounded too

  any user Bob creates
      └── boundary: dnb-boundary-developer   ← ceiling Bob cannot raise
```

#### Step 9.1 — Create the boundary policy

```bash
cat > policies/dnb-boundary-developer.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MaximumAllowedServiceSurface",
      "Effect": "Allow",
      "Action": [
        "s3:Get*", "s3:List*", "s3:PutObject",
        "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
        "logs:Describe*", "logs:Get*", "logs:FilterLogEvents",
        "lambda:Get*", "lambda:List*", "lambda:InvokeFunction",
        "dynamodb:Get*", "dynamodb:Query", "dynamodb:Scan", "dynamodb:PutItem",
        "sts:AssumeRole", "sts:GetCallerIdentity",
        "iam:Get*", "iam:List*"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DevelopersMayNeverTouchProduction",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringEquals": { "aws:ResourceTag/Environment": "prod" }
      }
    },
    {
      "Sid": "DevelopersMayNeverEscalatePrivilege",
      "Effect": "Deny",
      "Action": [
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "iam:AttachUserPolicy",
        "iam:AttachRolePolicy",
        "iam:PutUserPolicy",
        "iam:PutRolePolicy",
        "iam:DeleteUserPermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy",
        "iam:PassRole",
        "organizations:*",
        "account:*"
      ],
      "Resource": "*"
    }
  ]
}
JSON
jq empty policies/dnb-boundary-developer.json && echo valid

BOUNDARY_ARN="$(aws iam create-policy --policy-name dnb-boundary-developer --path /dnb/ \
  --description "Maximum permissions ceiling for developer principals" \
  --policy-document file://policies/dnb-boundary-developer.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
echo "$BOUNDARY_ARN" | tee out/boundary-arn.txt
```

!!! warning "Notice the deliberate tension"
    Statement 1 allows `iam:Get*`/`iam:List*` so tooling works. Statement 3 denies `iam:PassRole` and every policy-mutation action, because a developer with `iam:PassRole` can escalate to admin via Lambda. Statement 2 makes the boundary environment-aware via ABAC. A boundary that only allows and never denies is far weaker than it looks.

#### Step 9.2 — Attach the boundary and observe the intersection

```bash
# Give Bob broad identity permissions FIRST, so the intersection is visible
cat > policies/inline-bob-broad.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DeliberatelyTooMuch",
      "Effect": "Allow",
      "Action": ["s3:*", "iam:*", "ec2:*", "dynamodb:*"],
      "Resource": "*"
    }
  ]
}
JSON
aws iam put-user-policy --user-name dnb-dev-bob \
  --policy-name DeliberatelyBroadGrant \
  --policy-document file://policies/inline-bob-broad.json

aws iam put-user-permissions-boundary \
  --user-name dnb-dev-bob \
  --permissions-boundary "$BOUNDARY_ARN"

aws iam get-user --user-name dnb-dev-bob --query 'User.PermissionsBoundary'
```

```json
{
  "PermissionsBoundaryType": "Policy",
  "PermissionsBoundaryArn": "arn:aws:iam::000000000000:policy/dnb/dnb-boundary-developer"
}
```

**Now compute the intersection by hand (this is the examinable skill):**

| Action | Identity policy | Boundary | AWS effective |
|---|---|---|---|
| `s3:GetObject` on a dev-tagged bucket | Allow (`s3:*`) | Allow (`s3:Get*`) | **Allow** |
| `s3:DeleteObject` | Allow (`s3:*`) | not allowed | **Deny** (outside boundary) |
| `s3:PutObject` | Allow | Allow | **Allow** |
| `iam:CreateUser` | Allow (`iam:*`) | not allowed | **Deny** |
| `iam:ListUsers` | Allow | Allow (`iam:List*`) | **Allow** |
| `iam:AttachUserPolicy` | Allow | **explicit Deny** | **Deny** (and unappealable) |
| `ec2:RunInstances` | Allow (`ec2:*`) | not allowed | **Deny** |
| anything on a `Environment=prod` resource | Allow | **explicit Deny** | **Deny** |
| `dynamodb:DeleteTable` | Allow | not allowed | **Deny** |

```bash
# Track A verification: the boundary IS attached
aws iam get-user --user-name dnb-dev-bob \
  --query 'User.PermissionsBoundary.PermissionsBoundaryArn' --output text

# Track B: test whether your build enforces it
aws iam create-access-key --user-name dnb-dev-bob --output json > out/bob-key.json
aws configure set aws_access_key_id     "$(jq -r '.AccessKey.AccessKeyId' out/bob-key.json)"     --profile bob
aws configure set aws_secret_access_key "$(jq -r '.AccessKey.SecretAccessKey' out/bob-key.json)" --profile bob
aws configure set region us-east-1 --profile bob
aws configure set endpoint_url "$AWS_ENDPOINT_URL" --profile bob
bob() { AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= AWS_SESSION_TOKEN= aws --profile bob "$@"; }

bob sts get-caller-identity --query Arn --output text

# Probe against a THROWAWAY object. Never point a destructive probe at lab data you
# still need — if the emulator does not enforce the deny, the probe succeeds and the
# object is gone.
echo "disposable" > out/probe-victim.csv
aws s3 cp out/probe-victim.csv s3://dnb-statements-dev/probe/probe-victim.csv

./probe-enforcement.sh bob allow aws iam list-users
./probe-enforcement.sh bob deny  aws iam create-user --user-name dnb-boundary-escape-test
./probe-enforcement.sh bob deny  aws s3 rm s3://dnb-statements-dev/probe/probe-victim.csv

# Restore whatever the probes were able to change
aws iam delete-user --user-name dnb-boundary-escape-test 2>/dev/null
aws s3 cp out/probe-victim.csv s3://dnb-statements-dev/probe/probe-victim.csv 2>/dev/null

# Confirm the lab dataset is intact before moving on
aws s3 ls s3://dnb-statements-dev/2026/07/statement-1001.csv \
  && echo "PASS: lab data intact" \
  || aws s3 cp out/statement-1001.csv s3://dnb-statements-dev/2026/07/statement-1001.csv
```

!!! danger "Expect `DIVERGES-FROM-AWS` here"
    Permissions-boundary evaluation is among the least likely IAM behaviours to be emulated. When Bob successfully creates a user, do **not** conclude the boundary is wrong. Conclude that the emulator is not an authorisation engine, write the AWS-correct reasoning in your logbook, and move on. This is precisely the LO12 skill being assessed.

#### Step 9.3 — The safe-delegation policy

```bash
cat > policies/dnb-delegated-iam-admin.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateDevPrincipalsOnlyWithTheMandatoryBoundary",
      "Effect": "Allow",
      "Action": ["iam:CreateUser", "iam:CreateRole"],
      "Resource": [
        "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/*",
        "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/*"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PermissionsBoundary": "arn:aws:iam::${ACCOUNT_ID}:policy/dnb/dnb-boundary-developer"
        }
      }
    },
    {
      "Sid": "ManageDevPrincipalTagsKeysAndLifecycle",
      "Effect": "Allow",
      "Action": [
        "iam:TagUser", "iam:UntagUser", "iam:TagRole", "iam:UntagRole",
        "iam:CreateAccessKey", "iam:UpdateAccessKey", "iam:DeleteAccessKey",
        "iam:DeleteUser", "iam:DeleteRole"
      ],
      "Resource": [
        "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/*",
        "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/*"
      ]
    },
    {
      "Sid": "ManageMembershipOfNonAdminGroups",
      "Effect": "Allow",
      "Action": ["iam:AddUserToGroup", "iam:RemoveUserFromGroup"],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:group/dnb/*"
    },
    {
      "Sid": "ReadOnlyIamVisibility",
      "Effect": "Allow",
      "Action": ["iam:Get*", "iam:List*"],
      "Resource": "*"
    },
    {
      "Sid": "NeverRemoveOrWeakenTheCeiling",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteUserPermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "iam:DeletePolicy",
        "iam:DeletePolicyVersion"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:policy/dnb/dnb-boundary-developer"
    },
    {
      "Sid": "NeverTouchProductionPrincipalsOrAdmins",
      "Effect": "Deny",
      "Action": "iam:*",
      "Resource": [
        "arn:aws:iam::${ACCOUNT_ID}:user/dnb/prod/*",
        "arn:aws:iam::${ACCOUNT_ID}:role/dnb/prod/*",
        "arn:aws:iam::${ACCOUNT_ID}:group/dnb/dnb-admins"
      ]
    }
  ]
}
JSON
jq empty policies/dnb-delegated-iam-admin.json && echo valid

DELEG_ARN="$(aws iam create-policy --policy-name dnb-delegated-iam-admin --path /dnb/ \
  --description "Path-scoped, boundary-enforcing IAM delegation for team leads" \
  --policy-document file://policies/dnb-delegated-iam-admin.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-user-policy --user-name dnb-dev-bob --policy-arn "$DELEG_ARN"
aws iam delete-user-policy --user-name dnb-dev-bob --policy-name DeliberatelyBroadGrant
echo "$DELEG_ARN" | tee out/delegation-arn.txt
```

#### Step 9.3a — Bob needs a *wider* boundary than the people he onboards

Stop and think before running the next block. Bob currently carries `dnb-boundary-developer`, whose only IAM allowances are `iam:Get*` and `iam:List*`. Effective permissions are the **intersection** of identity and boundary — so the delegation policy you just attached grants Bob nothing at all. `iam:CreateUser` is outside his ceiling.

This is not a flaw in the design; it is the design working. A delegated administrator needs a boundary that permits delegation, and it must still be *narrower* than full IAM power.

```bash
cat > policies/dnb-boundary-delegated-admin.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CeilingForDelegatedAdmins",
      "Effect": "Allow",
      "Action": [
        "iam:Get*", "iam:List*",
        "iam:CreateUser", "iam:CreateRole", "iam:DeleteUser", "iam:DeleteRole",
        "iam:AddUserToGroup", "iam:RemoveUserFromGroup",
        "iam:TagUser", "iam:UntagUser", "iam:TagRole", "iam:UntagRole",
        "iam:CreateAccessKey", "iam:UpdateAccessKey", "iam:DeleteAccessKey",
        "iam:PutUserPermissionsBoundary", "iam:PutRolePermissionsBoundary",
        "s3:Get*", "s3:List*",
        "sts:AssumeRole", "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DelegatedAdminsMayNeverTouchProduction",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringEquals": { "aws:ResourceTag/Environment": "prod" }
      }
    },
    {
      "Sid": "DelegatedAdminsMayNeverEscalatePrivilege",
      "Effect": "Deny",
      "Action": [
        "iam:AttachUserPolicy", "iam:AttachRolePolicy", "iam:AttachGroupPolicy",
        "iam:PutUserPolicy", "iam:PutRolePolicy", "iam:PutGroupPolicy",
        "iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
        "iam:DeleteUserPermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
        "iam:UpdateAssumeRolePolicy", "iam:CreateLoginProfile", "iam:UpdateLoginProfile",
        "iam:PassRole",
        "organizations:*", "account:*"
      ],
      "Resource": "*"
    }
  ]
}
JSON
jq empty policies/dnb-boundary-delegated-admin.json && echo valid

DELEG_BOUNDARY_ARN="$(aws iam create-policy --policy-name dnb-boundary-delegated-admin --path /dnb/ \
  --description "Ceiling for team leads who onboard developers" \
  --policy-document file://policies/dnb-boundary-delegated-admin.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
echo "$DELEG_BOUNDARY_ARN" | tee out/deleg-boundary-arn.txt

# Swap Bob's ceiling. put-* overwrites; there is no separate "update" call.
aws iam put-user-permissions-boundary --user-name dnb-dev-bob \
  --permissions-boundary "$DELEG_BOUNDARY_ARN"
aws iam get-user --user-name dnb-dev-bob \
  --query 'User.PermissionsBoundary.PermissionsBoundaryArn' --output text
```

!!! tip "Two boundaries, two populations — this is the shape to remember"
    | Principal | Boundary | Can create principals? | Can attach policies? |
    |---|---|---|---|
    | Bob (team lead) | `dnb-boundary-delegated-admin` | yes, under `/dnb/dev/` only, boundary mandatory | **no** |
    | Dana, and anyone Bob creates | `dnb-boundary-developer` | no | no |

    Bob can *create* principals but cannot *empower* them beyond the developer boundary — he has no `iam:Attach*`, no `iam:Put*Policy`, and no `iam:PassRole`. Group membership is his only lever for granting permissions, and `dnb-admins` is explicitly denied to him. That is the whole safety argument in one paragraph.

!!! danger "`AddUserToGroup` acts on the **group**, not the user"
    This is why membership management needs its own statement with a `group/…` ARN. Scoping it to `user/dnb/dev/*` — the intuitive but wrong choice — produces a policy that can never authorise `AddUserToGroup`, and you get `AccessDenied` on an action you believe you granted. Check the *Resource types* column of the [IAM service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awsidentityandaccessmanagement.html) whenever an action's target is not obvious. Note that `dnb-admins` is still unreachable: Sid `NeverTouchProductionPrincipalsOrAdmins` denies `iam:*` on that group ARN, and explicit deny wins.

**Reason through what Bob can now do in real AWS:**

All verdicts below assume Bob now carries `dnb-boundary-delegated-admin` (Step 9.3a).

| Bob attempts | AWS verdict | Why |
|---|---|---|
| `create-user --path /dnb/dev/ --permissions-boundary dnb-boundary-developer` | **Allow** | Resource and condition satisfied, and `iam:CreateUser` is inside his boundary |
| `create-user --path /dnb/dev/` with **no** boundary | **Deny** | `iam:PermissionsBoundary` condition unsatisfied |
| `create-user --path /dnb/prod/` | **Deny** | Resource ARN outside `user/dnb/dev/*`, plus explicit deny |
| `create-user` with a **different** boundary | **Deny** | Condition demands that exact ARN |
| `delete-user-permissions-boundary` on his own user | **Deny** | Explicit deny in Sid 4 |
| `create-policy-version` on the boundary policy | **Deny** | Explicit deny — he cannot weaken the ceiling |
| `add-user-to-group dnb-admins` | **Deny** | `iam:*` denied on that group ARN |
| `attach-user-policy AdministratorAccess` to a user he created | **Deny** | His own boundary explicitly denies `iam:AttachUserPolicy` — and the delegation policy never granted it either |
| `create-user --path /dnb/dev/` while still holding `dnb-boundary-developer` | **Deny** | Pre-Step-9.3a state: `iam:CreateUser` is outside the developer ceiling |

!!! danger "Remove the `iam:PermissionsBoundary` condition and you have handed out root"
    Without it, Bob creates an unbounded user, attaches `AdministratorAccess`, generates a key, and is now account admin. That single missing condition is the difference between safe delegation and full compromise. It is the most important line in this lab.

#### Step 9.4 — Session policies

```bash
# The batch role can Put on all of dnb-statements-dev/*.
# Scope one session down to a single tenant prefix.
alice sts assume-role \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-batch-role" \
  --role-session-name tenant-42-restricted \
  --duration-seconds 900 \
  --policy '{"Version":"2012-10-17","Statement":[{"Sid":"OnlyTenant42","Effect":"Allow","Action":["s3:PutObject","s3:GetObject"],"Resource":"arn:aws:s3:::dnb-statements-dev/tenant-42/*"}]}' \
  --output json > out/tenant42-session.json

jq '{Arn: .AssumedRoleUser.Arn, Expiration: .Credentials.Expiration}' out/tenant42-session.json
```

| Action | Role policy | Session policy | AWS effective |
|---|---|---|---|
| `PutObject` on `tenant-42/x.csv` | Allow | Allow | **Allow** |
| `PutObject` on `tenant-99/x.csv` | Allow | not allowed | **Deny** (session policy filters) |
| `PutObject` on `dnb-audit-logs-dev/batch/x` | Allow | not allowed | **Deny** |
| `s3:*` on anything | partly | not allowed | **Deny** |
| `DeleteObject` on `tenant-42/x.csv` | **explicit Deny** | Allow | **Deny** (explicit deny wins) |

```bash
export AWS_ACCESS_KEY_ID="$(jq -r '.Credentials.AccessKeyId'     out/tenant42-session.json)"
export AWS_SECRET_ACCESS_KEY="$(jq -r '.Credentials.SecretAccessKey' out/tenant42-session.json)"
export AWS_SESSION_TOKEN="$(jq -r '.Credentials.SessionToken'    out/tenant42-session.json)"

echo "in-scope (AWS: allow):"
echo "t42" > out/t42.csv; aws s3 cp out/t42.csv s3://dnb-statements-dev/tenant-42/t42.csv 2>&1 | tail -1
echo "out-of-scope (AWS: DENY):"
aws s3 cp out/t42.csv s3://dnb-statements-dev/tenant-99/t99.csv 2>&1 | tail -2

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; eval "$(floci env)"
aws s3 rm s3://dnb-statements-dev/tenant-99/t99.csv 2>/dev/null
```

!!! tip "This is how multi-tenant SaaS is built on AWS"
    **One** role, N tenants. At request time the application assumes the role with a session policy (or a session tag + ABAC) scoped to the authenticated tenant. Tenant isolation becomes a property enforced by AWS itself, not by application `if` statements — so an application bug cannot leak across tenants.

#### Step 9.5 — A boundary cannot grant

```bash
aws iam create-user --user-name dnb-dev-dana --path /dnb/dev/ \
  --permissions-boundary "$BOUNDARY_ARN" --tags $TAGS >/dev/null
aws iam get-user --user-name dnb-dev-dana --query 'User.PermissionsBoundary.PermissionsBoundaryArn' --output text
aws iam list-attached-user-policies --user-name dnb-dev-dana --query 'AttachedPolicies' --output json
aws iam list-user-policies --user-name dnb-dev-dana --query 'PolicyNames' --output json
aws iam list-groups-for-user --user-name dnb-dev-dana --query 'Groups' --output json
```

Dana has a boundary allowing `s3:Get*`, `lambda:InvokeFunction`, and more — and **zero** identity policies.

**Dana's effective permissions in real AWS: nothing at all.** ∅ ∩ boundary = ∅.

```bash
aws iam create-access-key --user-name dnb-dev-dana --output json > out/dana-key.json
aws configure set aws_access_key_id     "$(jq -r '.AccessKey.AccessKeyId' out/dana-key.json)"     --profile dana
aws configure set aws_secret_access_key "$(jq -r '.AccessKey.SecretAccessKey' out/dana-key.json)" --profile dana
aws configure set region us-east-1 --profile dana
aws configure set endpoint_url "$AWS_ENDPOINT_URL" --profile dana
./probe-enforcement.sh dana deny aws s3 ls s3://dnb-statements-dev/
./probe-enforcement.sh dana deny aws iam list-users
```

!!! note "Write this sentence in your logbook, in your own words"
    "A permissions boundary defines the maximum permissions a principal *may* have; it never confers any permission. Effective permissions are the intersection of what is granted and what the boundary permits."

**Verification**

```bash
aws iam get-user --user-name dnb-dev-bob  --query 'User.PermissionsBoundary.PermissionsBoundaryArn' --output text | grep -q boundary-developer && echo "PASS: bob bounded"
aws iam get-user --user-name dnb-dev-dana --query 'User.PermissionsBoundary.PermissionsBoundaryArn' --output text | grep -q boundary-developer && echo "PASS: dana bounded"
aws iam get-policy --policy-arn "$DELEG_ARN" --query 'Policy.PolicyName' --output text
```

**Lab 9 recap.** Boundaries and session policies intersect; they never grant. Safe IAM delegation = path-scoped resources **+** a mandatory `iam:PermissionsBoundary` condition **+** explicit denies on removing the ceiling. Session policies enable one-role multi-tenancy.

---

### Lab 10 — Integration: A Lambda Execution Role End to End

**Objective.** Build the complete IAM chain for a serverless workload, including `iam:PassRole`.

**Prerequisites.** Labs 3, 6, 7. Check support for `lambda create-function` and `logs`.

**Architecture.**

```
  deployer principal
      │  needs: lambda:CreateFunction  AND  iam:PassRole on the exec role
      ▼
  Lambda function dnb-dev-statement-processor
      │  --role arn:…:role/dnb-dev-lambda-exec-role
      ▼
  dnb-dev-lambda-exec-role
      ├── trust: Service = lambda.amazonaws.com
      └── perms:
           ├── logs:CreateLogGroup / CreateLogStream / PutLogEvents   (mandatory)
           ├── s3:GetObject on dnb-statements-dev/incoming/*
           └── s3:PutObject on dnb-statements-dev/processed/*
```

#### Step 10.1 — The execution role

```bash
cat > policies/trust-lambda.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowLambdaServiceToAssume",
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
aws iam create-role --role-name dnb-dev-lambda-exec-role --path /dnb/dev/ \
  --description "Execution role for the statement processor function" \
  --assume-role-policy-document file://policies/trust-lambda.json \
  --tags $TAGS Key=Workload,Value=StatementProcessor \
  --query 'Role.Arn' --output text | tee out/lambda-role-arn.txt

cat > policies/dnb-lambda-exec.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchLogsForThisFunctionOnly",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/dnb-dev-statement-processor:*"
    },
    {
      "Sid": "ReadIncomingStatements",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::dnb-statements-dev/incoming/*"
    },
    {
      "Sid": "WriteProcessedStatements",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::dnb-statements-dev/processed/*"
    },
    {
      "Sid": "ListOnlyTheTwoRelevantPrefixes",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::dnb-statements-dev",
      "Condition": {
        "StringLike": { "s3:prefix": ["incoming/*", "processed/*"] }
      }
    }
  ]
}
JSON
jq empty policies/dnb-lambda-exec.json && echo valid

LAMBDA_POLICY_ARN="$(aws iam create-policy --policy-name dnb-lambda-exec --path /dnb/ \
  --description "Minimal permissions for the statement processor" \
  --policy-document file://policies/dnb-lambda-exec.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-role-policy --role-name dnb-dev-lambda-exec-role --policy-arn "$LAMBDA_POLICY_ARN"
echo "$LAMBDA_POLICY_ARN" | tee out/lambda-policy-arn.txt
```

!!! tip "Scoping the log-group ARN is not pedantry"
    `AWSLambdaBasicExecutionRole` (the AWS managed policy everyone attaches) grants logs actions on `"Resource": "*"` — meaning your function can write into **any** log group in the account, including audit log groups. Scoping to `/aws/lambda/<function-name>:*` is the least-privilege version and is exactly the kind of tightening an auditor will ask for.

#### Step 10.2 — `iam:PassRole` for the deployer

```bash
cat > policies/dnb-lambda-deployer.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageOurOwnFunctions",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction", "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration", "lambda:GetFunction",
        "lambda:ListFunctions", "lambda:InvokeFunction", "lambda:DeleteFunction",
        "lambda:TagResource", "lambda:ListTags"
      ],
      "Resource": "arn:aws:lambda:*:${ACCOUNT_ID}:function:dnb-dev-*"
    },
    {
      "Sid": "PassOnlyApprovedExecutionRolesAndOnlyToLambda",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/dnb/dev/dnb-dev-lambda-exec-role",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "lambda.amazonaws.com" }
      }
    }
  ]
}
JSON
jq empty policies/dnb-lambda-deployer.json && echo valid

DEPLOY_ARN="$(aws iam create-policy --policy-name dnb-lambda-deployer --path /dnb/ \
  --description "Deploy dnb-dev-* functions, passing only the approved exec role" \
  --policy-document file://policies/dnb-lambda-deployer.json \
  --tags $TAGS --query 'Policy.Arn' --output text)"
aws iam attach-group-policy --group-name dnb-developers --policy-arn "$DEPLOY_ARN"
echo "$DEPLOY_ARN" | tee out/deployer-arn.txt
```

!!! danger "The escalation path this policy closes"
    With `"Action": "iam:PassRole", "Resource": "*"`, Alice could create a Lambda whose execution role is an **admin** role, invoke it, and have it do anything — from a starting position of `lambda:CreateFunction` only. Both the narrow `Resource` and the `iam:PassedToService` condition are load-bearing. Search any real account for unscoped `iam:PassRole`; you will usually find some.

#### Step 10.3 — Deploy

```bash
mkdir -p fn && cat > fn/handler.py <<'PY'
import json, os, boto3

s3 = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"))
BUCKET = os.environ.get("STATEMENTS_BUCKET", "dnb-statements-dev")

def lambda_handler(event, context):
    key = event.get("key", "incoming/sample.csv")
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode()
    out_key = key.replace("incoming/", "processed/")
    s3.put_object(Bucket=BUCKET, Key=out_key, Body=("PROCESSED," + body).encode())
    return {"statusCode": 200, "body": json.dumps({"in": key, "out": out_key})}
PY
(cd fn && zip -q ../out/fn.zip handler.py)

echo "acct,period,amount" > out/incoming.csv
aws s3 cp out/incoming.csv s3://dnb-statements-dev/incoming/sample.csv

aws lambda create-function \
  --function-name dnb-dev-statement-processor \
  --runtime python3.12 \
  --handler handler.lambda_handler \
  --role "$(cat out/lambda-role-arn.txt)" \
  --zip-file fileb://out/fn.zip \
  --timeout 30 --memory-size 256 \
  --environment "Variables={STATEMENTS_BUCKET=dnb-statements-dev}" \
  --tags Project=CoreBanking,Environment=dev,ManagedBy=floci-lab \
  --query '{Name: FunctionName, Role: Role, State: State}' 2>&1 | tail -12
```

| Parameter | Meaning |
|---|---|
| `--role` | **The execution role ARN.** Requires `iam:PassRole` on the caller |
| `--zip-file fileb://…` | Binary file prefix — `file://` would corrupt the zip |
| `--handler module.function` | Entry point |
| `--environment` | Config, never secrets — use Secrets Manager for those |

!!! note "If `lambda create-function` is unsupported in your build"
    Record it and verify the IAM chain instead — the IAM knowledge is the assessed content:

    ```bash
    aws iam get-role --role-name dnb-dev-lambda-exec-role \
      --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text   # lambda.amazonaws.com
    aws iam list-attached-role-policies --role-name dnb-dev-lambda-exec-role --query 'AttachedPolicies[].PolicyName' --output text
    aws iam get-policy-version --policy-arn "$LAMBDA_POLICY_ARN" \
      --version-id "$(aws iam get-policy --policy-arn "$LAMBDA_POLICY_ARN" --query Policy.DefaultVersionId --output text)" \
      --query 'PolicyVersion.Document.Statement[].Sid' --output text
    ```

#### Step 10.4 — Invoke and read the logs

```bash
aws lambda invoke --function-name dnb-dev-statement-processor \
  --payload "$(printf '{"key":"incoming/sample.csv"}' | base64 | tr -d '\n')" \
  out/lambda-response.json 2>&1 | tail -3
cat out/lambda-response.json 2>/dev/null; echo
aws s3 ls s3://dnb-statements-dev/processed/ 2>/dev/null
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/dnb-dev-statement-processor \
  --query 'logGroups[].logGroupName' --output text 2>/dev/null
```

#### Break it — three integration failures

```bash
# (a) Trust the wrong service
aws iam update-assume-role-policy --role-name dnb-dev-lambda-exec-role \
  --policy-document file://policies/trust-ec2.json

# Lambda validates the execution role's trust policy when the role is SET, not on an
# unrelated change. Re-setting the same role ARN forces re-validation.
aws lambda update-function-configuration --function-name dnb-dev-statement-processor \
  --role "$(cat out/lambda-role-arn.txt)" 2>&1 | tail -3
```

Expected in real AWS:

```
An error occurred (InvalidParameterValueException) when calling the
UpdateFunctionConfiguration operation: The role defined for the function cannot be
assumed by Lambda.
```

!!! warning "Why changing `--timeout` would NOT have reproduced this"
    An unrelated configuration change does not re-validate the role, so the call succeeds, no error appears — and the function is now silently un-invokable. Internalise the asymmetry: **an IAM misconfiguration usually surfaces at the next operation that touches it, not at the moment you introduce it.**

```bash
# Fix
aws iam update-assume-role-policy --role-name dnb-dev-lambda-exec-role \
  --policy-document file://policies/trust-lambda.json
aws iam get-role --role-name dnb-dev-lambda-exec-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text
```

```bash
# (b) Missing iam:PassRole — the classic
carol lambda create-function --function-name dnb-dev-carol-fn \
  --runtime python3.12 --handler handler.lambda_handler \
  --role "$(cat out/lambda-role-arn.txt)" --zip-file fileb://out/fn.zip 2>&1 | tail -3
```

AWS: `AccessDenied: User … is not authorized to perform: iam:PassRole on resource …` — even though the role itself is perfectly configured. **The failure is on the caller, not the role.**

```bash
# (c) Execution role missing logs permissions
aws iam detach-role-policy --role-name dnb-dev-lambda-exec-role --policy-arn "$LAMBDA_POLICY_ARN"
aws lambda invoke --function-name dnb-dev-statement-processor \
  --payload "$(printf '{"key":"incoming/sample.csv"}' | base64 | tr -d '\n')" \
  out/nolog-response.json 2>&1 | tail -2
cat out/nolog-response.json 2>/dev/null; echo
aws iam attach-role-policy --role-name dnb-dev-lambda-exec-role --policy-arn "$LAMBDA_POLICY_ARN"
```

In real AWS the function **still runs** but produces no CloudWatch logs at all — the single most confusing Lambda symptom there is. "My function has no logs" almost always means the execution role lacks `logs:*`, not that the function did not execute.

**Verification**

```bash
aws iam get-role --role-name dnb-dev-lambda-exec-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' --output text | grep -q lambda && echo "PASS: trust"
aws iam get-policy-version --policy-arn "$DEPLOY_ARN" \
  --version-id "$(aws iam get-policy --policy-arn "$DEPLOY_ARN" --query Policy.DefaultVersionId --output text)" \
  --query 'PolicyVersion.Document.Statement[?Sid==`PassOnlyApprovedExecutionRolesAndOnlyToLambda`].Condition' --output json
```

**Lab 10 recap.** A serverless workload needs **three** IAM pieces: the execution role's trust policy (`lambda.amazonaws.com`), its permissions policy (always including scoped `logs:*`), and `iam:PassRole` on the deployer — scoped by `Resource` and `iam:PassedToService`. Missing logs permissions is silent.

---

### Lab 11 — The Enforcement Audit (Break, Diagnose, Document)

**Objective.** Systematically map which parts of the IAM model your Floci build enforces, and produce the divergence report that accompanies your lab submission.

**Prerequisites.** All previous labs.

#### Step 11.1 — Run the matrix

```bash
cat > enforcement-audit.sh <<'SCRIPT'
#!/usr/bin/env bash
# Compare AWS-correct verdicts against this build's behaviour.
set -uo pipefail
cd ~/iam-lab
run() { ./probe-enforcement.sh "$@"; }

echo "== identity-based ALLOW (positive control) =="
run carol allow aws iam list-users
run carol allow aws s3 ls s3://dnb-statements-dev/

echo "== identity-based implicit DENY =="
run carol deny aws iam create-user --user-name __audit_probe__
run dana  deny aws s3 ls s3://dnb-statements-dev/

echo "== identity-based explicit DENY (inline DenyAuditorsAnyWrite) =="
run carol deny aws s3 cp /etc/hostname s3://dnb-statements-dev/__audit_probe__

echo "== role permission DENY (NeverDeleteAnything) =="
echo disposable > out/probe-victim.csv
aws s3 cp out/probe-victim.csv s3://dnb-statements-dev/probe/probe-victim.csv >/dev/null 2>&1
run batch deny aws s3 rm s3://dnb-statements-dev/probe/probe-victim.csv

echo "== trust-policy DENY (carol not trusted) =="
run carol deny aws sts assume-role \
  --role-arn "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/dnb/dev/dnb-dev-batch-role" \
  --role-session-name audit-probe

echo "== permissions-boundary DENY =="
run bob deny aws iam create-user --user-name __audit_probe_bob__

echo "== resource-based policy DENY (bucket policy) =="
run carol deny aws s3api delete-bucket-policy --bucket dnb-statements-dev

echo "== cleanup of anything that should not have been created =="
aws iam delete-user --user-name __audit_probe__     2>/dev/null
aws iam delete-user --user-name __audit_probe_bob__ 2>/dev/null
aws s3 rm s3://dnb-statements-dev/__audit_probe__   2>/dev/null
aws s3 rm s3://dnb-statements-dev/probe/probe-victim.csv 2>/dev/null
# The lab dataset must survive the audit — restore it if a probe removed it
aws s3 ls s3://dnb-statements-dev/2026/07/statement-1001.csv >/dev/null 2>&1 \
  || aws s3 cp out/statement-1001.csv s3://dnb-statements-dev/2026/07/statement-1001.csv 2>/dev/null
SCRIPT
chmod +x enforcement-audit.sh
./enforcement-audit.sh | tee out/enforcement-audit.txt
```

#### Step 11.2 — Produce the divergence report

````bash
{
  echo "# IAM Enforcement Divergence Report"
  echo
  echo "- Build: $(floci --version 2>/dev/null || echo unknown)"
  echo "- Endpoint: $AWS_ENDPOINT_URL"
  echo "- Account: $(aws sts get-caller-identity --query Account --output text)"
  echo "- Date (UTC): $(date -u +%FT%TZ)"
  echo
  echo "## Supported operations"
  echo '```'
  cat out/support-matrix.tsv
  echo '```'
  echo
  echo "## Enforcement results"
  echo '```'
  cat out/enforcement-audit.txt
  echo '```'
  echo
  echo "## Divergences requiring conceptual reasoning"
  grep -c 'DIVERGES-FROM-AWS' out/enforcement-audit.txt | sed 's/^/Count: /'
  grep 'DIVERGES-FROM-AWS' out/enforcement-audit.txt || echo "None."
  echo
  echo "## My explanation of each divergence (student writes this section)"
  echo "For each divergence: state the AWS-correct verdict, name the policy and"
  echo "statement Sid that produces it, and cite the step of the §3.3 evaluation"
  echo "pipeline at which the request is decided."
} > out/divergence-report.md
wc -l out/divergence-report.md
````

#### Step 11.3 — Six diagnostics to internalise

| Symptom | First command to run | Most likely cause |
|---|---|---|
| `InvalidClientTokenId` | `env \| grep -c AWS_SESSION_TOKEN` | `ASIA…` key without a session token, or a deleted/inactive key |
| `SignatureDoesNotMatch` | `date -u`, then re-check the secret | Wrong secret key, or clock skew > 5 min |
| `AccessDenied` on the action you want | `aws sts get-caller-identity` | You are not the principal you think you are |
| `AccessDenied` on `sts:AssumeRole` | `aws iam get-role --query Role.AssumeRolePolicyDocument` **and** the caller's identity policy | One of the two required allows is missing |
| `AccessDenied` mentioning `iam:PassRole` | `aws iam get-policy-version` on the caller's policies | Missing or over-scoped `iam:PassRole` |
| `MalformedPolicyDocument` | `jq empty <file>` | Bad JSON, missing `Version`, `Principal` in an identity policy, or a typo'd service principal |

```bash
# The universal three-command triage
whoami_aws() {
  echo "--- identity ---";  aws sts get-caller-identity
  echo "--- endpoint ---";  echo "${AWS_ENDPOINT_URL:-<REAL AWS!>}"
  echo "--- session? ---";  [ -n "${AWS_SESSION_TOKEN:-}" ] && echo "temporary creds" || echo "long-term creds"
}
whoami_aws
```

**Lab 11 recap.** You now hold two artefacts: a support matrix (what exists) and an enforcement audit (what is decided). Together they define the exact boundary of what your local environment can teach you — and where you must reason from the AWS specification instead.

---
## 6. Enterprise Scenario — Druk National Bank

### 6.1 The brief

> **Druk National Bank (DNB)** is migrating its retail statement-generation platform to AWS. You are the cloud security engineer on the platform team. The bank is regulated by the Royal Monetary Authority and must satisfy an annual IT audit.
>
> **Stakeholders**
>
> | Person / system | Role | Needs |
> |---|---|---|
> | Alice | Backend developer | Deploy the statement processor; read/write dev statement data |
> | Bob | Team lead | Onboard and offboard developers without a ticket to the cloud team |
> | Carol | Internal auditor | Read everything, change nothing, produce evidence for the RMA audit |
> | Dana | New graduate hire | Starts with zero access; Bob onboards her |
> | Nightly batch job | Automation | Generate statements at 02:00; append to the audit log; must never delete |
> | Statement processor (Lambda) | Automation | Read `incoming/`, write `processed/` |
> | App tier (EC2) | Automation | Read statements to serve the customer portal |
> | KPMG Bhutan | External auditor (different AWS account) | Read-only access to the audit log bucket for two weeks in March |
>
> **Non-negotiable requirements (from the RMA control framework)**
>
> | ID | Requirement |
> |---|---|
> | R1 | No human uses long-term access keys for production. Root is sealed. |
> | R2 | No application stores a credential on disk or in an environment variable. |
> | R3 | Statement data is append-only for automation; only a dual-authorised admin process may delete. |
> | R4 | All data access is over TLS. Plain HTTP is refused. |
> | R5 | Bob can onboard developers but cannot create anyone more privileged than himself. |
> | R6 | Auditors' access is provably read-only, and expires automatically. |
> | R7 | External auditor access is time-boxed, requires a shared secret, and creates no identity inside DNB. |
> | R8 | Every resource is tagged for cost allocation and environment separation. |
> | R9 | Any credential can be revoked in under five minutes. |
> | R10 | Development principals can never touch production-tagged resources. |

### 6.2 Target architecture

```
                        ┌──────────────────── DNB AWS ORGANIZATION ─────────────────────┐
                        │  (AWS-only; Floci emulates the dev account only)              │
                        │                                                               │
   Corporate IdP ──SAML──►  IAM Identity Center ──permission sets──► roles in each acct  │
   (Active Directory)   │        │                                                      │
                        │        ├── acct: dnb-security   (central audit, break-glass)   │
                        │        ├── acct: dnb-dev  ◄──── THIS IS WHAT FLOCI EMULATES    │
                        │        └── acct: dnb-prod (SCP: deny region ≠ ap-south-1,      │
                        │                                 deny disable CloudTrail)       │
                        └───────────────────────────────────────────────────────────────┘

   ── inside dnb-dev (the Floci-emulated account) ──────────────────────────────────────

   GROUPS (job functions)                ROLES (workloads + delegation)
   ├ dnb-developers                      ├ dnb-dev-batch-role        (trust: alice)
   │   ├ dnb-s3-statements-read          ├ dnb-dev-reporting-role    (trust: batch-role)
   │   ├ dnb-assume-batch-role           ├ dnb-dev-app-role          (trust: ec2)
   │   └ dnb-lambda-deployer             │   └ via dnb-dev-app-profile
   │   members: alice, bob, dana         ├ dnb-dev-lambda-exec-role  (trust: lambda)
   ├ dnb-auditors                        └ dnb-external-audit-role   (trust: KPMG acct
   │   ├ dnb-s3-audit-read               │      + sts:ExternalId + DateLessThan)
   │   └ inline DenyAuditorsAnyWrite     │
   │   members: carol                    BOUNDARIES
   └ dnb-admins (empty, break-glass)     ├ dnb-boundary-delegated-admin → bob
                                         └ dnb-boundary-developer       → dana and
                                              everyone bob onboards

   alice deliberately carries NO boundary: dnb-boundary-developer denies iam:PassRole,
   which would disable the Lambda deployment path R2 depends on. Bounding a deployer
   needs a boundary permitting iam:PassRole narrowed by iam:PassedToService — that is
   the real difficulty in Mini Challenge MC5.

   BUCKETS                               GUARDRAILS
   ├ dnb-statements-dev                  ├ bucket policy: Deny !SecureTransport
   │   ├ incoming/  processed/           ├ bucket policy: Deny DeleteBucket(+Policy)
   │   └ 2026/07/  2026/08/  tenant-*/   ├ role policy:   Deny s3:Delete* (batch)
   └ dnb-audit-logs-dev                  └ boundary:      Deny ResourceTag/Environment=prod
       └ batch/
```

### 6.3 Requirement → control mapping

| Req | Control | Implemented in |
|---|---|---|
| R1 | Federation via IAM Identity Center; IAM users only in dev for teaching | §4.17 (conceptual) + Lab 5 (what we replace) |
| R2 | Instance profile for EC2; execution role for Lambda; IMDSv2 required | Labs 7, 10 |
| R3 | `NeverDeleteAnything` explicit deny in `dnb-s3-batch-write`; `NobodyMayDeleteThisBucket` in the bucket policy | Labs 6, 8 |
| R4 | `DenyUnencryptedTransport` (`aws:SecureTransport = false`) in bucket policy **and** identity policy v2 | Labs 3, 8 |
| R5 | `dnb-delegated-iam-admin` with mandatory `iam:PermissionsBoundary` condition + path scoping + deny on boundary mutation | Lab 9 |
| R6 | `dnb-s3-audit-read` (read-only) + inline `DenyAuditorsAnyWrite` (`Deny` + `NotAction`); federated session expiry | Lab 4 |
| R7 | `dnb-external-audit-role`: cross-account principal + `sts:ExternalId` + `DateLessThan` on `aws:CurrentTime` | §6.4 below |
| R8 | Mandatory tag set on every entity; ABAC conditions consume them | All labs |
| R9 | Temporary credentials expire; long-term keys `update-access-key --status Inactive`; sessions revoked via `aws:TokenIssueTime` deny | §6.5 below |
| R10 | `DevelopersMayNeverTouchProduction` deny on `aws:ResourceTag/Environment = prod` in the boundary | Lab 9 |

### 6.4 R7 — the time-boxed external auditor role

```bash
cat > policies/trust-external-audit.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KpmgBhutanTimeBoxedAudit",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::333333333333:root" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "sts:ExternalId": "dnb-rma-audit-2026-a91f7c3e" },
        "DateGreaterThan": { "aws:CurrentTime": "2026-03-01T00:00:00Z" },
        "DateLessThan":    { "aws:CurrentTime": "2026-03-15T00:00:00Z" },
        "Bool": { "aws:MultiFactorAuthPresent": "true" }
      }
    }
  ]
}
JSON
jq empty policies/trust-external-audit.json && echo valid

aws iam create-role --role-name dnb-external-audit-role --path /dnb/ \
  --description "KPMG Bhutan RMA audit window, March 2026" \
  --assume-role-policy-document file://policies/trust-external-audit.json \
  --max-session-duration 3600 \
  --tags $TAGS Key=Purpose,Value=ExternalAudit Key=ExpiresOn,Value=2026-03-15 \
  --query 'Role.Arn' --output text

aws iam attach-role-policy --role-name dnb-external-audit-role \
  --policy-arn "$(cat out/report-policy-arn.txt)"

aws iam get-role --role-name dnb-external-audit-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
```

Four independent controls, each of which alone is insufficient:

| Control | Prevents |
|---|---|
| Named account principal | Anyone outside KPMG's account |
| `sts:ExternalId` | The confused-deputy attack from KPMG's other clients |
| `DateGreaterThan` + `DateLessThan` | Access before or after the audit window — **no cleanup ticket required** |
| `aws:MultiFactorAuthPresent` | A stolen KPMG credential without the second factor |

!!! tip "Self-expiring access is the mark of a mature IAM design"
    The control that requires a human to remember to revoke it in two weeks is the control that fails. Encode the expiry in the policy.

### 6.5 R9 — revoking access in under five minutes

| Credential type | Revocation method | Time to effect |
|---|---|---|
| IAM user access key | `iam update-access-key --status Inactive` | immediate |
| Console password | `iam delete-login-profile` | immediate |
| **Active STS session** | Cannot be deleted. Attach a `Deny` conditioned on `aws:TokenIssueTime` | immediate for new requests |
| Role itself | `iam delete-role` (detach children first) | immediate; existing sessions die |
| Federated user | Disable in the corporate IdP + the `TokenIssueTime` deny | immediate |

```bash
cat > policies/revoke-old-sessions.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RevokeAllSessionsIssuedBeforeTheIncidentCutoff",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "DateLessThan": { "aws:TokenIssueTime": "2026-08-04T12:00:00Z" }
      }
    }
  ]
}
JSON
jq empty policies/revoke-old-sessions.json && echo valid

# Applied as an INLINE policy on the compromised role — the AWS-documented
# "Revoke sessions" mechanism.
aws iam put-role-policy --role-name dnb-dev-batch-role \
  --policy-name AWSRevokeOlderSessions \
  --policy-document file://policies/revoke-old-sessions.json
aws iam list-role-policies --role-name dnb-dev-batch-role --query PolicyNames --output text
```

!!! danger "You cannot un-issue an STS token"
    A leaked `ASIA…` triple is valid until its `Expiration`, full stop. The only remedy is a `Deny` on every session issued before now. This is why short `--max-session-duration` values are a security control, not an inconvenience — they bound your worst-case exposure window.

    Remember to remove this policy when the incident is closed, or all new sessions will keep working while nothing older than the cutoff ever does again:
    ```bash
    aws iam delete-role-policy --role-name dnb-dev-batch-role --policy-name AWSRevokeOlderSessions
    ```

### 6.6 Onboarding Dana — the full runbook

```bash
# Executed by Bob (delegated IAM admin), under his boundary.
# In real AWS every step below is authorised by dnb-delegated-iam-admin.

# 1. Create with the mandatory boundary and full tag set
bob iam create-user --user-name dnb-dev-dana2 --path /dnb/dev/ \
  --permissions-boundary "$(cat out/boundary-arn.txt)" \
  --tags Key=Project,Value=CoreBanking Key=Environment,Value=dev \
         Key=Owner,Value=bob Key=CostCenter,Value=CC-4400 \
         Key=ManagedBy,Value=floci-lab Key=StartDate,Value=2026-08-04 2>&1 | tail -3

# 2. Job-function group membership — never a direct policy attachment
bob iam add-user-to-group --group-name dnb-developers --user-name dnb-dev-dana2 2>&1 | tail -2

# 3. Verify the result before telling Dana she is set up
aws iam get-user --user-name dnb-dev-dana2 \
  --query 'User.{Name: UserName, Path: Path, Boundary: PermissionsBoundary.PermissionsBoundaryArn}'
aws iam list-groups-for-user --user-name dnb-dev-dana2 --query 'Groups[].GroupName' --output text
aws iam list-attached-user-policies --user-name dnb-dev-dana2 --query 'AttachedPolicies' --output json
```

**Offboarding runbook (the part organisations get wrong):**

```
 1. iam list-access-keys      → update-access-key --status Inactive   (reversible first!)
 2. iam delete-login-profile
 3. deactivate + delete MFA devices
 4. revoke live STS sessions: put-role-policy AWSRevokeOlderSessions on any role they could assume
 5. remove from every group
 6. delete inline policies; detach managed policies
 7. delete permissions boundary
 8. delete access keys (now irreversibly)
 9. iam delete-user
10. search CloudTrail for their last 30 days of activity; archive as evidence
11. reassign ownership tags on any resource tagged Owner=<them>
```

!!! warning "Step 1 before step 8, and step 4 at all"
    Deactivating first gives you a rollback if you offboarded the wrong person. And a user deleted at step 9 whose STS session was issued at step 0 **still has a working session** until it expires — step 4 is not optional.

### 6.7 Deliverable

Submit `dnb-iam-design.md` containing:

1. An architecture diagram of your final IAM design (ASCII is fine).
2. The R1–R10 requirement → control table, with the exact policy `Sid` implementing each.
3. Every policy document, with a one-line justification per statement.
4. Your `out/divergence-report.md` from Lab 11.
5. A **threat model**: for each of these attacks, name the control that stops it and the evaluation-pipeline step at which it is stopped.
   * Alice's laptop is stolen with `~/.aws/credentials` on it.
   * Bob tries to make himself an administrator.
   * The batch job has a bug that issues `DeleteObject` on every statement.
   * An attacker obtains a valid `ASIA…` session for `dnb-dev-app-role`.
   * A misconfiguration makes `dnb-statements-dev` world-readable.
   * KPMG's audit tooling is compromised by another of their clients.
   * A developer tries to launch an instance in an unapproved region.
   * Carol is socially engineered into running a script that deletes the audit bucket.
6. A one-page critique: **which three of your controls could you not verify in Floci, and how would you verify them in a real AWS sandbox account?**

---

## 7. Verification — Reading the Output Like an Auditor

### 7.1 The universal inspection commands

```bash
# ── Who am I, really ──
aws sts get-caller-identity

# ── Everything about one principal ──
aws iam get-user --user-name dnb-dev-alice
aws iam get-role --role-name dnb-dev-batch-role
aws iam get-group --group-name dnb-developers

# ── Permissions attached to a principal (BOTH kinds — never just one) ──
aws iam list-attached-user-policies --user-name dnb-dev-alice     # managed
aws iam list-user-policies          --user-name dnb-dev-alice     # inline
aws iam list-groups-for-user        --user-name dnb-dev-alice     # inherited

# ── Read an actual policy document ──
POLICY_ARN="$(cat out/policy-arn.txt)"
VER="$(aws iam get-policy --policy-arn "$POLICY_ARN" --query Policy.DefaultVersionId --output text)"
aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$VER" \
  --query 'PolicyVersion.Document' | jq '.'

# ── Reverse lookup: who has this policy ──
aws iam list-entities-for-policy --policy-arn "$POLICY_ARN"

# ── Trust relationships ──
aws iam get-role --role-name dnb-dev-batch-role --query 'Role.AssumeRolePolicyDocument' | jq '.'

# ── Everything in the account, in one call (probe support first) ──
aws iam get-account-authorization-details > out/authz-details.json 2>/dev/null \
  && jq '{users:(.UserDetailList|length), groups:(.GroupDetailList|length),
          roles:(.RoleDetailList|length), policies:(.Policies|length)}' out/authz-details.json \
  || echo "get-account-authorization-details unsupported — enumerate manually"
```

### 7.2 Interpreting fields that matter

| Field | Where | What it tells you |
|---|---|---|
| `Arn` | everywhere | The exact principal/resource. Watch `iam:` vs `sts:` |
| `UserId` prefix | `get-caller-identity` | `AIDA…`=IAM user, `AROA…`=role, `AROA…:<session>`=assumed-role session, 12 digits=account root. (`AKIA…`/`ASIA…` are *access-key* prefixes and never appear here — see §4.5) |
| `CreateDate` | users, keys, roles | Age. Keys > 90 days are a finding |
| `PasswordLastUsed` | `get-user` | Absent ⇒ never signed in. Dormant identities are a finding |
| `PermissionsBoundary` | `get-user` / `get-role` | Present = bounded. **Absent on a delegated admin is a critical finding** |
| `MaxSessionDuration` | `get-role` | 43 200 on a high-privilege role is a finding |
| `AttachmentCount` | `get-policy` | 0 = orphaned policy; clean it up |
| `DefaultVersionId` | `get-policy` | Which version is live *right now* |
| `IsDefaultVersion` | `list-policy-versions` | Exactly one must be `true` |
| `AssumeRolePolicyDocument.Statement[].Principal` | `get-role` | `"*"` = critical finding |
| `Condition` | any policy | Absent on a broad grant = a finding |
| `Status` | `list-access-keys` | `Inactive` keys still exist and must be deleted |

### 7.3 A reusable posture-audit script

```bash
cat > iam-posture-audit.sh <<'SCRIPT'
#!/usr/bin/env bash
# Read-only IAM posture audit. Findings are printed, not fixed.
set -uo pipefail
FINDINGS=0
finding() { FINDINGS=$((FINDINGS+1)); printf '  [FINDING %02d] %s\n' "$FINDINGS" "$*"; }

echo "=== 1. Policies attached DIRECTLY to users (should be zero — use groups) ==="
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do
  n=$(aws iam list-attached-user-policies --user-name "$u" --query 'length(AttachedPolicies)' --output text 2>/dev/null || echo 0)
  i=$(aws iam list-user-policies          --user-name "$u" --query 'length(PolicyNames)'      --output text 2>/dev/null || echo 0)
  [ "${n:-0}" -gt 0 ] && finding "user $u has $n directly attached managed policies"
  [ "${i:-0}" -gt 0 ] && finding "user $u has $i inline policies"
done

echo "=== 2. Wildcard Action AND wildcard Resource in customer policies ==="
for arn in $(aws iam list-policies --scope Local --query 'Policies[].Arn' --output text); do
  v=$(aws iam get-policy --policy-arn "$arn" --query Policy.DefaultVersionId --output text)
  doc=$(aws iam get-policy-version --policy-arn "$arn" --version-id "$v" --query 'PolicyVersion.Document' --output json 2>/dev/null)
  echo "$doc" | jq -e '
    [.Statement[]?
     | select(.Effect=="Allow")
     | select((.Action? // empty | tostring) | test("\"\\*\"|^\\*$"))
     | select((.Resource? // empty | tostring) | test("\"\\*\"|^\\*$"))] | length > 0' >/dev/null 2>&1 \
    && finding "policy $arn allows Action:* on Resource:*"
done

echo "=== 3. Roles trusting everyone ==="
while read -r r; do
  [ -z "${r:-}" ] && continue
  aws iam get-role --role-name "$r" --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null \
    | jq -e '[.Statement[]? | select(.Effect=="Allow")
              | select(.Principal == "*"
                       or (.Principal | objects | .AWS) == "*"
                       or (((.Principal | objects | .AWS | arrays) // []) | index("*")) != null)] | length > 0' >/dev/null 2>&1 \
    && finding "role $r has a wildcard trust principal"
done < <(aws iam list-roles --query 'Roles[].RoleName' --output text | tr '\t' '\n')

echo "=== 4. Unscoped iam:PassRole ==="
for arn in $(aws iam list-policies --scope Local --query 'Policies[].Arn' --output text); do
  v=$(aws iam get-policy --policy-arn "$arn" --query Policy.DefaultVersionId --output text)
  aws iam get-policy-version --policy-arn "$arn" --version-id "$v" --query 'PolicyVersion.Document' --output json 2>/dev/null \
    | jq -e '[.Statement[]? | select(.Effect=="Allow")
              | select((.Action|tostring) | test("PassRole"))
              | select((.Resource|tostring) | test("\\*") and (test("role/") | not))] | length > 0' >/dev/null 2>&1 \
    && finding "policy $arn grants iam:PassRole with an unscoped Resource"
done

echo "=== 5. Inactive keys still present, and multi-key users ==="
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do
  # Process substitution, NOT a pipe: `cmd | while ...` runs the loop in a subshell,
  # so every FINDINGS increment inside it would be silently discarded.
  while read -r k st; do
    [ "${st:-}" = "Inactive" ] && finding "user $u has an Inactive key $k that should be deleted"
  done < <(aws iam list-access-keys --user-name "$u" --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output text 2>/dev/null)
  c=$(aws iam list-access-keys --user-name "$u" --query 'length(AccessKeyMetadata)' --output text 2>/dev/null || echo 0)
  [ "${c:-0}" -ge 2 ] && finding "user $u has $c keys (only acceptable mid-rotation)"
done

echo "=== 6. Orphaned policies (AttachmentCount = 0) ==="
while read -r p; do
  [ -n "${p:-}" ] && finding "policy $p is attached to nothing"
done < <(aws iam list-policies --scope Local --query 'Policies[?AttachmentCount==`0`].PolicyName' --output text | tr '\t' '\n')

echo "=== 7. Roles with a 12-hour max session ==="
while read -r r; do
  [ -n "${r:-}" ] && finding "role $r allows 12-hour sessions"
done < <(aws iam list-roles --query 'Roles[?MaxSessionDuration>=`43200`].RoleName' --output text | tr '\t' '\n')

echo "=== 8. Untagged principals ==="
for u in $(aws iam list-users --query 'Users[].UserName' --output text); do
  t=$(aws iam list-user-tags --user-name "$u" --query 'length(Tags)' --output text 2>/dev/null || echo 0)
  [ "${t:-0}" -eq 0 ] && finding "user $u has no tags"
done

echo
echo "TOTAL FINDINGS: $FINDINGS"
SCRIPT
chmod +x iam-posture-audit.sh
./iam-posture-audit.sh | tee out/posture-audit.txt
```

!!! tip "This script is genuinely useful beyond the lab"
    Point it at a real AWS sandbox account (with read-only credentials) and it will find things. Checks 2, 3 and 4 in particular map directly to the highest-severity findings in professional cloud security reviews.

### 7.4 Verifying with the policy simulator (if supported)

```bash
if aws iam simulate-principal-policy \
     --policy-source-arn "arn:aws:iam::${ACCOUNT_ID}:user/dnb/dev/dnb-dev-carol" \
     --action-names s3:GetObject s3:PutObject iam:CreateUser \
     --resource-arns "arn:aws:s3:::dnb-statements-dev/2026/07/statement-1001.csv" \
     --query 'EvaluationResults[].[EvalActionName,EvalDecision,MatchedStatements[0].SourcePolicyId]' \
     --output table 2>/dev/null; then
  echo "Simulator available — this is your best Track-A verification tool."
else
  echo "simulate-principal-policy unsupported. Verify structurally instead:"
  echo " 1. does the statement exist?  2. is the ARN exactly right (bucket vs bucket/*)?"
  echo " 3. is there a Deny anywhere that matches?  4. walk the §3.3 pipeline by hand."
fi
```

Expected shape when available:

```
------------------------------------------------------------
|                 SimulatePrincipalPolicy                  |
+----------------+-----------------+-----------------------+
|  s3:GetObject  |  allowed        |  dnb-s3-audit-read    |
|  s3:PutObject  |  explicitDeny   |  DenyAuditorsAnyWrite |
|  iam:CreateUser|  implicitDeny   |  None                 |
+----------------+-----------------+-----------------------+
```

| `EvalDecision` | Meaning |
|---|---|
| `allowed` | An `Allow` matched and nothing denied |
| `explicitDeny` | A `Deny` statement matched — read `MatchedStatements` to find it |
| `implicitDeny` | Nothing matched at all — you are missing an `Allow` |

!!! note "Recap — §7"
    Audit a principal by reading managed **and** inline policies **and** group memberships **and** the boundary. `list-entities-for-policy` answers "who has this permission". `simulate-principal-policy` distinguishes explicit from implicit deny — which is the difference between "remove a Deny" and "add an Allow".

---

## 8. Troubleshooting

### 8.1 Error reference

| Error | Meaning | Most likely cause | Fix |
|---|---|---|---|
| `AccessDenied` | Authenticated but not authorised | Missing `Allow`, or a matching `Deny` | `simulate-principal-policy`; read the error's action + resource; check for denies first |
| `AccessDenied ... explicit deny in a permissions boundary` | Boundary excluded it | Identity grants it, boundary does not | Widen the boundary or narrow the requirement |
| `AccessDenied ... with an explicit deny in a service control policy` | Org SCP blocked it | Account-level guardrail | Only the org management account can change this |
| `UnauthorizedOperation` | EC2's dialect of `AccessDenied` | Missing `ec2:*` permission | Add the action; use `--dry-run` to test |
| `InvalidClientTokenId` | The access key is not recognised | Deleted/inactive key; `ASIA…` without `AWS_SESSION_TOKEN`; wrong account | Check `env \| grep AWS_`; re-assume the role |
| `SignatureDoesNotMatch` | Signature mismatch | Wrong secret key; clock skew > 5 min; trailing whitespace in the secret | `date -u`, `ntpdate`, re-enter the secret |
| `ExpiredToken` / `ExpiredTokenException` | Temporary credentials aged out | Session past `Expiration` | Re-assume. If it happens at 60 min, you are role chaining |
| `MalformedPolicyDocument` | The document is not a valid policy | Bad JSON; `Principal` in an identity policy; missing `Version`; unknown condition operator | `jq empty file.json`; re-read §4.8 |
| `NoSuchEntity` | The named object does not exist | Typo; wrong path in the ARN; wrong account | `list-*` and compare exactly |
| `EntityAlreadyExists` | Name is taken | Names are case-insensitively unique | Choose another, or `get-*` the existing one |
| `DeleteConflict` | Dependencies remain | Keys/policies/roles still attached | Follow the §4.3 deletion order |
| `LimitExceeded` | Quota hit | 5 policy versions, 2 access keys, 10 attached policies, 1 role per instance profile | Delete something, or request a quota increase |
| `ValidationError ... exceeds the MaxSessionDuration` | Duration too long for the role | `--duration-seconds` > role limit | Lower it, or `update-role --max-session-duration` |
| `ValidationError ... 1 hour session limit for roles assumed by role chaining` | Chained assume | role → role | Use ≤ 3 600, or assume the target role directly |
| `is not authorized to perform: iam:PassRole` | Caller cannot hand this role to a service | Missing/over-narrow `iam:PassRole` | Add it, scoped by `Resource` + `iam:PassedToService` |
| `The role defined for the function cannot be assumed by Lambda` | Wrong trust policy | Trust names the wrong service principal | Set `lambda.amazonaws.com` |
| `Invalid IAM Instance Profile name` | Profile missing or empty | Forgot `create-instance-profile` / `add-role-to-instance-profile` | Create it and add the role |
| `Invalid principal in policy` | Unusable `Principal` | A group ARN, a typo'd service principal, or a deleted principal | Use a user/role/service/account |
| `NotAuthorizedException` / `InvalidAction` (Floci) | Operation not implemented | Emulator gap | Consult your support matrix; treat as conceptual |
| `Could not connect to the endpoint URL` | Nothing listening | Floci stopped; wrong port | `floci status`, `floci start`, `eval "$(floci env)"` |

### 8.2 The decision tree

```
   A command failed.
        │
        ├─ Connection/endpoint error?
        │     └─ floci status → floci start → eval "$(floci env)"
        │
        ├─ InvalidClientTokenId / SignatureDoesNotMatch?
        │     └─ AUTHENTICATION problem, not permissions:
        │        • env | grep AWS_        (are the right creds loaded?)
        │        • ASIA… key? then AWS_SESSION_TOKEN must be set
        │        • aws iam list-access-keys → is the key Active?
        │        • date -u                  (clock skew < 5 min?)
        │
        ├─ ExpiredToken?
        │     └─ re-assume. Dying at exactly 60 min ⇒ role chaining.
        │
        ├─ MalformedPolicyDocument / Invalid principal?
        │     └─ jq empty file.json
        │        • "Version": "2012-10-17" present?
        │        • Principal present in a RESOURCE policy / absent in an IDENTITY policy?
        │        • service principal spelled exactly (lambda.amazonaws.com)?
        │        • used file:// (or fileb:// for zips)?
        │
        ├─ DeleteConflict / LimitExceeded?
        │     └─ a QUOTA or DEPENDENCY problem. Enumerate children; follow teardown order.
        │
        └─ AccessDenied / UnauthorizedOperation?
              └─ AUTHORISATION problem. Walk §3.3 in order:
                 1. aws sts get-caller-identity  — am I who I think I am?
                 2. Read the error: it names the ACTION and the RESOURCE. Copy them exactly.
                 3. Any explicit Deny? identity, resource, boundary, session, SCP
                    → simulate-principal-policy shows explicitDeny + the Sid
                 4. Boundary present and does it allow this action?
                 5. Assumed a role with --policy? that session policy must allow it.
                 6. Is there an Allow at all? (implicitDeny ⇒ no)
                 7. Cross-account? BOTH sides must allow.
                 8. Resource ARN exactly right? (s3 bucket vs bucket/*)
                 9. Conditions satisfied? (region, tags, TLS, MFA, IP, time)
```

### 8.3 Worked example

```
$ carol s3 cp report.pdf s3://dnb-statements-dev/report.pdf
upload failed: ./report.pdf to s3://dnb-statements-dev/report.pdf
An error occurred (AccessDenied) when calling the PutObject operation:
User: arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-carol is not authorized to
perform: s3:PutObject on resource: "arn:aws:s3:::dnb-statements-dev/report.pdf"
with an explicit deny in an identity-based policy
```

Extract four facts before touching anything:

| Fact | Value |
|---|---|
| Principal | `arn:aws:iam::000000000000:user/dnb/dev/dnb-dev-carol` |
| Action | `s3:PutObject` |
| Resource | `arn:aws:s3:::dnb-statements-dev/report.pdf` |
| **Verdict type** | **explicit deny in an identity-based policy** |

That last phrase is the whole diagnosis. It is *not* a missing `Allow` — adding one changes nothing. Find the `Deny`:

```bash
aws iam list-groups-for-user --user-name dnb-dev-carol --query 'Groups[].GroupName' --output text
aws iam list-group-policies  --group-name dnb-auditors --query PolicyNames --output text
aws iam get-group-policy --group-name dnb-auditors --policy-name DenyAuditorsAnyWrite \
  --query 'PolicyDocument' | jq '.'
```

The inline `AuditorsMayNeverMutateAnything` statement denies everything outside its `NotAction` list, and `s3:PutObject` is not in that list. **This is working exactly as designed** — Carol is an auditor. The correct resolution is not to weaken the policy but to give Carol a different, sanctioned path (a role she can assume for a specific approved task) or to reject the request.

!!! tip "AWS tells you the verdict *type*, and it is the most valuable word in the message"
    | Phrase in the error | What to do |
    |---|---|
    | `with an explicit deny in an identity-based policy` | Find and reconsider the `Deny` — adding `Allow` is futile |
    | `with an explicit deny in a resource-based policy` | Look at the bucket/key/queue policy |
    | `with an explicit deny in a permissions boundary` | The ceiling excludes it |
    | `with an explicit deny in a service control policy` | Org-level; escalate to the org admin |
    | `with a session policy` | Re-assume without (or with a wider) `--policy` |
    | *(no explanatory phrase)* | Implicit deny — you are missing an `Allow` |

### 8.4 Floci-specific troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `Could not connect to the endpoint URL: "http://localhost:4566/"` | Emulator not running | `floci status`; `floci start --detach`; `floci wait` |
| Commands unexpectedly reach real AWS | `AWS_ENDPOINT_URL` lost (new shell/tab) | `eval "$(floci env)"`; use the `guard()` function from §0.3 |
| `InvalidAction` / `NotImplemented` | Operation not emulated | Check `support-matrix.tsv`; treat as conceptual |
| Everything succeeds regardless of policy | You are running as the account root credentials | Use a named profile backed by an IAM user (Lab 5) |
| Policies attach but denies do not fire | Enforcement not emulated for that service | Record in `divergence-report.md`; reason from §3.3 |
| Resources vanish after a restart | Started without `--persist` | `floci start --persist ./floci-state` |
| `floci start` fails | Docker not running, or port 4566 taken | `docker info`; `floci doctor --fix`; `floci start --port 4599` |
| Stale state confusing a lab | Leftovers from a previous run | `floci stop --remove` then start fresh, and re-run Labs 1–3 |

```bash
floci doctor
floci logs --tail 80
```

!!! note "Recap — §8"
    Classify first: connection, authentication, malformed, quota/dependency, or authorisation. For authorisation, the error message's verdict-type phrase tells you whether to remove a `Deny` or add an `Allow` — never guess between the two.

---

## 9. Security Best Practices

### 9.1 The fifteen rules

| # | Rule | Concretely |
|---|---|---|
| 1 | **Seal the root user** | Hardware MFA, no access keys, no daily use, alarm on any root API call |
| 2 | **Least privilege, always** | Start with nothing; add only what evidence (CloudTrail/Access Advisor) shows is used |
| 3 | **Prefer roles to users** | Federation for humans, roles for workloads. Target: zero IAM users |
| 4 | **Prefer temporary to long-term credentials** | Every `AKIA…` is a liability with a half-life |
| 5 | **Never attach policies directly to users** | Groups for humans, roles for workloads |
| 6 | **Rotate what you cannot eliminate** | ≤90 days; four-phase rotation; alarm on key age |
| 7 | **MFA everywhere a human authenticates** | Enforce with `aws:MultiFactorAuthPresent` + `BoolIfExists` |
| 8 | **Use permissions boundaries for delegation** | And always with the `iam:PermissionsBoundary` condition |
| 9 | **Explicit `Deny` for invariants** | "This workload never deletes"; "no traffic outside these regions" |
| 10 | **Condition every broad grant** | Region, TLS, tags, source VPCE, time window |
| 11 | **Encrypt in transit and at rest, and enforce it in policy** | `aws:SecureTransport`, `s3:x-amz-server-side-encryption`, KMS key policies |
| 12 | **Log everything, immutably** | CloudTrail org trail → dedicated account, S3 Object Lock, log file validation |
| 13 | **Tag everything, and mean it** | Tags drive ABAC, cost allocation, and automated cleanup — and must themselves be protected |
| 14 | **Review continuously** | IAM Access Analyzer, credential reports, unused-access findings, quarterly attestation |
| 15 | **Clean up** | Orphaned policies, unused roles, dormant users, `Inactive` keys, expired external access |

### 9.2 Least privilege in practice — the four-step method

```
  1. START AT ZERO
       new principal → no policies → verify it can do nothing
  2. ADD THE MINIMUM, WRITTEN BY HAND
       exact actions, exact resource ARNs, conditions from day one
       ✗ "s3:*" on "*"
       ✓ "s3:GetObject" on "arn:aws:s3:::dnb-statements-dev/incoming/*"
  3. TEST BOTH DIRECTIONS
       positive: the intended operation succeeds
       negative: the adjacent operation FAILS  ← people skip this, and it is the important one
  4. MEASURE AND TIGHTEN
       CloudTrail / Access Advisor after 2–4 weeks → delete every unused action
```

### 9.3 Encoding controls as policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyPlaintextTransport",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    },
    {
      "Sid": "DenyUnencryptedUploads",
      "Effect": "Deny",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::dnb-statements-dev/*",
      "Condition": {
        "StringNotEquals": { "s3:x-amz-server-side-encryption": "aws:kms" }
      }
    },
    {
      "Sid": "DenyAccessOutsideTheCorporateVpcEndpoint",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": {
        "StringNotEquals": { "aws:SourceVpce": "vpce-0dnb1example" },
        "Bool": { "aws:ViaAWSService": "false" }
      }
    },
    {
      "Sid": "RequireMfaForAnyDestructiveAction",
      "Effect": "Deny",
      "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutBucketPolicy"],
      "Resource": [
        "arn:aws:s3:::dnb-statements-dev",
        "arn:aws:s3:::dnb-statements-dev/*"
      ],
      "Condition": { "BoolIfExists": { "aws:MultiFactorAuthPresent": "false" } }
    },
    {
      "Sid": "RequireMandatoryTagsOnCreation",
      "Effect": "Deny",
      "Action": ["ec2:RunInstances", "ec2:CreateVolume"],
      "Resource": "*",
      "Condition": {
        "Null": {
          "aws:RequestTag/Project": "true",
          "aws:RequestTag/Environment": "true",
          "aws:RequestTag/Owner": "true"
        }
      }
    }
  ]
}
```

!!! tip "`aws:ViaAWSService` in `DenyAccessOutsideTheCorporateVpcEndpoint`"
    Without it, this statement breaks every AWS service that reads your bucket on your behalf (CloudFront, Athena, replication), because those requests do not carry your VPC endpoint id. Forgetting it produces mysterious service failures hours later.

### 9.4 The privilege-escalation checklist

Any principal holding **any one** of these can usually become account admin. Audit for all of them.

| Escalation vector | Why it works |
|---|---|
| `iam:CreatePolicyVersion` + `iam:SetDefaultPolicyVersion` | Rewrite any policy attached to yourself |
| `iam:AttachUserPolicy` / `AttachRolePolicy` / `AttachGroupPolicy` | Attach `AdministratorAccess` to yourself |
| `iam:PutUserPolicy` / `PutRolePolicy` / `PutGroupPolicy` | Write yourself an inline admin policy |
| `iam:CreateAccessKey` on another user | Become a more privileged user |
| `iam:CreateLoginProfile` / `UpdateLoginProfile` on another user | Set their console password |
| `iam:UpdateAssumeRolePolicy` | Make an admin role trust you |
| `iam:PassRole` + `lambda:CreateFunction` + `lambda:InvokeFunction` | Run arbitrary code as an admin role |
| `iam:PassRole` + `ec2:RunInstances` | Launch an instance with an admin profile, read IMDS |
| `iam:PassRole` + `glue:CreateDevEndpoint` / `cloudformation:CreateStack` / `datapipeline:*` / `codebuild:*` | Same trick, different service |
| `iam:AddUserToGroup` | Join the admins group |
| `iam:CreateRole` without a mandatory boundary | Build an unbounded admin role |
| `sts:AssumeRole` on an over-broad `Resource` | Assume something powerful |
| `iam:DeleteUserPermissionsBoundary` | Remove your own ceiling |
| `kms:PutKeyPolicy` | Grant yourself decrypt on everything |

```bash
# Grep your account for the highest-risk combinations
for arn in $(aws iam list-policies --scope Local --query 'Policies[].Arn' --output text); do
  v=$(aws iam get-policy --policy-arn "$arn" --query Policy.DefaultVersionId --output text)
  doc=$(aws iam get-policy-version --policy-arn "$arn" --version-id "$v" --query 'PolicyVersion.Document' --output json 2>/dev/null)
  for risky in 'iam:CreatePolicyVersion' 'iam:SetDefaultPolicyVersion' 'iam:Attach' 'iam:Put.*Policy' \
               'iam:PassRole' 'iam:UpdateAssumeRolePolicy' 'iam:CreateAccessKey' 'iam:AddUserToGroup' \
               'iam:\*' 'kms:PutKeyPolicy'; do
    echo "$doc" | jq -r '.Statement[]? | select(.Effect=="Allow") | (.Action|tostring)' 2>/dev/null \
      | grep -qiE "$risky" && echo "RISK  $arn  →  $risky"
  done
done | sort -u
```

### 9.5 Compliance mapping

| Control family | IAM implementation |
|---|---|
| CIS AWS Foundations 1.x (IAM) | root MFA + no root keys; MFA for all users; keys rotated ≤90 d; password policy; no policies allowing `*:*`; credential report reviewed |
| PCI DSS 7 & 8 (access control, identification) | unique IDs, least privilege, MFA, quarterly review, session timeouts |
| ISO 27001 A.9 | formal registration/deregistration (onboarding/offboarding runbooks), privileged access management, review of rights |
| SOC 2 CC6 | logical access provisioning/removal, least privilege, credential management, boundary enforcement |
| RMA / central-bank style controls | segregation of duties (developers ≠ approvers), dual authorisation for destructive actions, immutable audit trail, time-boxed third-party access |

!!! note "Recap — §9"
    Seal root, prefer roles, prefer temporary credentials, never attach to users, condition every broad grant, encode invariants as explicit denies, and audit specifically for the privilege-escalation vectors in §9.4 — of which unscoped `iam:PassRole` is the most common in real accounts.

---

## 10. Service Integration

### 10.1 The integration map

```
                        ┌──────────────── IAM / STS ────────────────┐
                        │  principals · policies · temporary creds   │
                        └───────────────────┬───────────────────────┘
        ┌───────────────┬───────────────────┼───────────────────┬───────────────┐
        ▼               ▼                   ▼                   ▼               ▼
   ┌─────────┐   ┌────────────┐      ┌───────────┐       ┌──────────┐   ┌────────────┐
   │   EC2   │   │   Lambda   │      │    S3     │       │   KMS    │   │ CloudTrail │
   │ instance│   │ execution  │      │  bucket   │       │   key    │   │  records   │
   │ profile │   │   role     │      │  policy   │       │  policy  │   │  identity  │
   └─────────┘   └────────────┘      └───────────┘       └──────────┘   └────────────┘
        ▼               ▼                   ▼                   ▼               ▼
   ┌─────────┐   ┌────────────┐      ┌───────────┐       ┌──────────┐   ┌────────────┐
   │ECS task │   │ API Gateway│      │ DynamoDB  │       │ Secrets  │   │ CloudWatch │
   │+execution│  │ authorizer │      │fine-grained│      │ Manager  │   │   alarms   │
   │  roles  │   │ IAM auth   │      │  access   │       │ resource │   │ on IAM API │
   └─────────┘   └────────────┘      └───────────┘       │  policy  │   └────────────┘
        ▼               ▼                   ▼            └──────────┘
   ┌─────────┐   ┌────────────┐      ┌───────────┐            ▼
   │   EKS   │   │Step Function│     │  SQS/SNS  │       ┌──────────┐
   │IRSA/pod │   │ state-machine│    │  access   │       │   RDS    │
   │identity │   │    role     │     │  policy   │       │IAM db auth│
   └─────────┘   └────────────┘      └───────────┘       └──────────┘
```

### 10.2 Integration reference

| Service | IAM mechanism | Key detail | Floci |
|---|---|---|---|
| **EC2** | Instance profile → role → IMDS | 1 role/profile; enforce IMDSv2 | ⚠️ IAM side ✅, IMDS delivery probe |
| **Lambda** | Execution role (`lambda.amazonaws.com`); resource policy for invoke permission | Always include scoped `logs:*`; `iam:PassRole` on the deployer | ⚠️ |
| **ECS/Fargate** | **Two** roles: *task execution role* (pull image from ECR, write logs) and *task role* (what your code does) | Confusing these is the #1 ECS IAM bug | ⚠️ |
| **EKS** | IRSA (OIDC provider + `sts:AssumeRoleWithWebIdentity`) or EKS Pod Identity | Trust policy conditions on the service-account subject | ⚠️ |
| **S3** | Identity policy + bucket policy + ACL (legacy) + Block Public Access + VPCE policy | BPA overrides everything; two ARNs for bucket vs objects | ⚠️ |
| **KMS** | **Key policy is authoritative** — an IAM policy alone is not enough | A key policy that omits your principal denies it regardless of IAM | ⚠️ |
| **DynamoDB** | Identity policy; fine-grained via `dynamodb:LeadingKeys` condition | Row-level multi-tenancy without application logic | ⚠️ |
| **SQS/SNS** | Resource access policy | Cross-account publish/subscribe; use `aws:SourceArn` to prevent confused deputy | ⚠️ |
| **RDS** | IAM database authentication: `rds-db:connect` on `arn:aws:rds-db:…:dbuser:<resource-id>/<db-user>` | 15-minute token instead of a stored password | ⚠️ |
| **Secrets Manager** | Identity policy + secret resource policy + KMS key policy — **all three** | Rotation Lambda needs its own role | ⚠️ |
| **API Gateway** | `AWS_IAM` authorizer → `execute-api:Invoke`; or a Lambda authorizer | SigV4-signed client requests | ⚠️ |
| **CloudFormation** | Stack **service role** (`cloudformation.amazonaws.com`) | Deploy with a scoped role so the *pipeline* need not be admin | ⚠️ |
| **CloudTrail** | Consumer of IAM, not controlled by it | `userIdentity` block; source of truth for least-privilege tightening | ⚠️ |
| **CloudWatch** | Alarms on IAM API calls and root usage | Detective control layered on IAM's preventive control | ⚠️ |
| **Organizations** | SCPs/RCPs intersect with IAM | Never grant; always cap | ❌ |
| **Identity Center** | Permission sets → provisioned roles in each account | The modern human-access answer | ❌ |
| **Cognito** | Identity pools exchange a user-pool token for IAM credentials via `AssumeRoleWithWebIdentity` | App end-users, not employees | ⚠️ |

### 10.3 Two integrations you should be able to write from memory

**ECS: the two-role model**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TaskExecutionRoleTrust",
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "aws:SourceAccount": "000000000000" },
        "ArnLike": { "aws:SourceArn": "arn:aws:ecs:us-east-1:000000000000:*" }
      }
    }
  ]
}
```

| Role | Used by | Grants |
|---|---|---|
| **Task execution role** | the ECS agent, *before* your container starts | `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `logs:CreateLogStream`, `logs:PutLogEvents`, `secretsmanager:GetSecretValue` for injected secrets |
| **Task role** | your application code, at runtime | `s3:GetObject`, `dynamodb:Query`, … — whatever the app actually does |

!!! danger "Symptom → cause for the ECS two-role confusion"
    Task stuck in `PENDING` with `CannotPullContainerError` ⇒ the **execution** role lacks ECR permissions. Task runs but your code gets `AccessDenied` on S3 ⇒ the **task** role lacks S3 permissions. Same account, same cluster, two entirely different roles.

**DynamoDB row-level multi-tenancy**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TenantCanOnlyReadItsOwnRows",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-east-1:000000000000:table/dnb-accounts",
      "Condition": {
        "ForAllValues:StringEquals": {
          "dynamodb:LeadingKeys": ["${aws:PrincipalTag/TenantId}"]
        }
      }
    }
  ]
}
```

The partition key must equal the caller's `TenantId` tag. Tenant isolation becomes an AWS-enforced invariant — an application SQL-injection-style bug cannot cross tenants.

### 10.4 Where Floci integration testing stops

| You can verify locally | You cannot verify locally |
|---|---|
| Trust policy names the correct service principal | That the service actually assumes it |
| The permissions policy is correct and attached | That the data-plane call is authorised |
| The instance profile contains the role | That IMDS serves credentials at `169.254.169.254` |
| The bucket policy is stored and well-formed | That Block Public Access overrides it |
| `assume-role` returns a credential triple | That the trust policy was truly evaluated |
| JSON structure, ARNs, `Sid`s, conditions present | Condition-key evaluation |
| Deletion dependency ordering (often) | SCP intersection, Access Analyzer findings |

!!! note "Recap — §10"
    Every AWS service integrates with IAM through one of three shapes: a **service role** it assumes (Lambda, ECS, CloudFormation), a **resource policy** it owns (S3, KMS, SQS, Secrets Manager), or a **condition-key** surface for fine-grained control (`dynamodb:LeadingKeys`, `s3:prefix`, `rds-db:connect`). KMS is the one where the resource policy is *authoritative* — remember it.

---
## 11. Mini Challenges

Complete these without step-by-step guidance. For each, submit: the commands you ran, the policy documents you wrote, your verification evidence, and — where enforcement is not emulated — the AWS-correct verdict with the reasoning from §3.3.

### MC1 — Home directories (⭐)

Create three users `dnb-dev-e1`, `dnb-dev-e2`, `dnb-dev-e3` and a bucket `dnb-home-dev`. Write **one single policy**, attached to **one group**, such that each user can read, write, and list *only* their own prefix `dnb-home-dev/<their-username>/` and cannot see any other user's prefix — not even the list of prefixes.

* Constraint: exactly one policy document. No per-user policies.
* Hint: `${aws:username}` and the `s3:prefix` condition on `s3:ListBucket`.
* Verify: `e1` can `put` to `e1/`, cannot `put` to `e2/`, and `s3 ls s3://dnb-home-dev/` shows nothing while `s3 ls s3://dnb-home-dev/e1/` works.

### MC2 — Region guardrail (⭐)

Write a policy that permits all of `ec2:*` and `s3:*` **except** in regions other than `us-east-1` and `ap-south-1`. Global services (IAM, STS, CloudFront, Route 53, Support, Organizations) must keep working.

* Constraint: use `Deny` + `NotAction`, not a giant allow-list.
* Note on ordering: steps 4 and 5 of §3.3 are both AND-gates, so their relative order never changes a verdict — but AWS's published flowchart evaluates the **permissions boundary before the session policy**, and that is the order you will be marked on.
* Explain in two sentences why the global-service exemption is necessary.

### MC3 — Time-boxed contractor (⭐⭐)

Create `dnb-contractor-role`, assumable only by `dnb-dev-alice`, only between two timestamps 24 hours apart, only from the CIDR `103.0.0.0/8`, and requiring an `ExternalId`. Permissions: read-only on `dnb-statements-dev`. Sessions must be 15 minutes.

* Trap: `MaxSessionDuration` has a **floor of 3 600 s**, so 15 minutes cannot be expressed as a role property. Set the role to its 3 600 s minimum, then explain where the 900-second limit actually has to be enforced and show the command that enforces it.

* Verify: successful assume with correct parameters; failed assume with each of the four conditions violated in turn (four separate tests).
* Where Floci does not evaluate a condition, state the AWS verdict and cite the condition operator responsible.

### MC4 — Right-size an over-permissive policy (⭐⭐)

You are handed this policy from a code review:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "*", "Resource": "*" }
  ]
}
```

CloudTrail evidence shows the principal has only ever performed:

```
s3:GetObject          on  arn:aws:s3:::dnb-statements-dev/incoming/*
s3:PutObject          on  arn:aws:s3:::dnb-statements-dev/processed/*
s3:ListBucket         on  arn:aws:s3:::dnb-statements-dev   (prefixes: incoming/, processed/)
dynamodb:PutItem      on  arn:aws:dynamodb:us-east-1:000000000000:table/dnb-ledger
dynamodb:Query        on  arn:aws:dynamodb:us-east-1:000000000000:table/dnb-ledger/index/by-account
logs:CreateLogStream  on  arn:aws:logs:us-east-1:000000000000:log-group:/aws/lambda/dnb-dev-statement-processor:*
logs:PutLogEvents     on  the same log group
kms:Decrypt           on  arn:aws:kms:us-east-1:000000000000:key/1234abcd-…
```

Rewrite it as a least-privilege policy. Add a TLS condition and one explicit `Deny` invariant of your choosing, justified in one sentence. Count how many distinct actions the original granted versus yours (`aws iam list-policies` will not tell you — reason about it).

### MC5 — Safe delegation, from scratch (⭐⭐⭐)

Without looking at Lab 9, build a delegation model where `dnb-dev-lead` can create, tag, key, and delete users under `/dnb/dev/` but:

* every user they create **must** carry the boundary `dnb-boundary-junior`;
* they cannot create anything under `/dnb/prod/`;
* they cannot modify or delete the boundary policy;
* they cannot raise their own privileges;
* they cannot add anyone to `dnb-admins`.

Then write a **five-step attack narrative** attempting to escalate from `dnb-dev-lead` to account admin, and show which statement blocks each step.

### MC6 — Multi-tenant SaaS isolation (⭐⭐⭐)

`dnb-tenant-role` serves 500 tenants from `dnb-statements-dev/tenant-<id>/`. Design isolation such that:

* there is exactly **one** role and **one** policy, regardless of tenant count;
* a session for tenant 42 mathematically cannot read tenant 43's data;
* isolation is enforced by AWS, not by application code.

Provide **two** designs — one using session policies, one using session tags + ABAC — and a paragraph comparing them on scalability, auditability, and blast radius. State which you would ship and why.

### MC7 — Break-glass role (⭐⭐⭐)

Design an emergency admin role for DNB satisfying: MFA required; sessions no longer than 15 minutes; assumable only by the members of `dnb-admins`; `SourceIdentity` required so the human stays attributable through role chaining; every assumption should be alarmable; and permissions are `AdministratorAccess`-equivalent minus the ability to disable CloudTrail or delete the role itself.

* Trap: **a group cannot be a trust-policy `Principal`** (§4.4). You must find another way to express "members of `dnb-admins`". State the two viable approaches and which you would ship.
* Trap: the 15-minute limit is not a role property — see MC3.

Write the trust policy, the permissions policy, and describe the CloudWatch/EventBridge detective control in three sentences.

### MC8 — Cross-account audit, both halves (⭐⭐⭐⭐)

Account `111111111111` (security) must let its role `sec-auditor` read every S3 bucket in `222222222222` (workloads), scoped to the organisation `o-druk1example`, over TLS only, and only for buckets **not** tagged `Environment=prod`.

Write all four artefacts: the trust policy in `222222222222`, the permissions policy on the assumed role in `222222222222`, the identity policy in `111111111111`, and one representative bucket policy. Then explain precisely why three of the four are insufficient on their own.

### MC9 — Policy-as-code validator (⭐⭐⭐⭐)

Write `validate-policy.sh` that takes a policy JSON file and **fails** (non-zero exit) on any of:

1. missing or wrong `Version`;
2. `"Action": "*"` combined with `"Resource": "*"` under `Effect: Allow`;
3. a `Principal` element inside a document declared as identity-based;
4. `iam:PassRole` with a `Resource` containing a bare `*`;
5. an S3 statement using object-level actions on a bucket ARN without `/*` (or vice versa);
6. any statement without a `Sid`;
7. `"Principal": {"AWS": "*"}` with `Effect: Allow`.

Run it against every policy in `~/iam-lab/policies/` and produce a pass/fail table. Bonus: add a warning tier for `Allow` statements with no `Condition`.

---

## 12. Debugging Challenges

Each challenge installs a broken configuration. **Diagnose from the CLI before reading any hint.** For each, submit: (a) the symptom, (b) the diagnostic commands you ran in order, (c) the root cause, (d) the fix, (e) the evaluation-pipeline step involved.

```bash
mkdir -p ~/iam-lab/debug && cd ~/iam-lab
```

### DC1 — The user that will not delete

```bash
cat > debug/dc1-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
aws iam create-user --user-name dnb-dc1-user --path /dnb/dev/ >/dev/null 2>&1
aws iam create-group --group-name dnb-dc1-group >/dev/null 2>&1
aws iam add-user-to-group --group-name dnb-dc1-group --user-name dnb-dc1-user >/dev/null 2>&1
aws iam create-access-key --user-name dnb-dc1-user >/dev/null 2>&1
aws iam create-login-profile --user-name dnb-dc1-user --password 'TempPass#2026!' >/dev/null 2>&1
aws iam put-user-policy --user-name dnb-dc1-user --policy-name Leftover \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Sid":"X","Effect":"Allow","Action":"s3:ListAllMyBuckets","Resource":"*"}]}' >/dev/null 2>&1
aws iam attach-user-policy --user-name dnb-dc1-user --policy-arn "$(cat out/policy-arn.txt)" >/dev/null 2>&1
echo "DC1 ready. Task: delete dnb-dc1-user and dnb-dc1-group completely."
SCRIPT
chmod +x debug/dc1-setup.sh && ./debug/dc1-setup.sh
aws iam delete-user --user-name dnb-dc1-user
```

**Task.** Delete the user and the group with no leftovers. Write a **general-purpose** `purge-user.sh` that handles every dependency in the correct order and is idempotent. Then run `aws iam get-user --user-name dnb-dc1-user` and confirm `NoSuchEntity`.

??? note "Hint (open only after 15 minutes)"
    Five dependency classes exist here: group membership, access keys, login profile, inline policy, attached managed policy. `DeleteConflict` tells you *a* blocker, not *all* of them — so it will fail repeatedly until every class is cleared.

### DC2 — The auditor who cannot read

```bash
cat > debug/dc2-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
aws iam create-user --user-name dnb-dc2-auditor --path /dnb/dev/ >/dev/null 2>&1
cat > debug/dc2-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadStatements",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": "arn:aws:s3:::dnb-statements-dev"
    }
  ]
}
JSON
aws iam put-user-policy --user-name dnb-dc2-auditor --policy-name ReadStatements \
  --policy-document file://debug/dc2-policy.json >/dev/null 2>&1
echo "DC2 ready. Symptom: 'aws s3 ls s3://dnb-statements-dev' works, but"
echo "'aws s3 cp s3://dnb-statements-dev/2026/07/statement-1001.csv -' returns AccessDenied."
SCRIPT
chmod +x debug/dc2-setup.sh && ./debug/dc2-setup.sh
```

**Task.** Explain why listing succeeds but reading fails, fix the policy, and verify.

??? note "Hint"
    Compare the ARN in `Resource` against the ARN the *failing* action operates on. Re-read the "two-ARN rule" danger box in §4.8.

### DC3 — The role nobody can assume

```bash
cat > debug/dc3-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
ACCT="$(aws sts get-caller-identity --query Account --output text)"
cat > debug/dc3-trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustDevelopers",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::${ACCT}:user/dnb-dev-alice" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
aws iam create-role --role-name dnb-dc3-role \
  --assume-role-policy-document file://debug/dc3-trust.json >/dev/null 2>&1
aws iam attach-role-policy --role-name dnb-dc3-role --policy-arn "$(cat out/policy-arn.txt)" >/dev/null 2>&1
echo "DC3 ready. Symptom: alice gets AccessDenied on sts:AssumeRole for dnb-dc3-role,"
echo "even though the trust policy names her and she has sts:AssumeRole in her group."
SCRIPT
chmod +x debug/dc3-setup.sh && ./debug/dc3-setup.sh
alice sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dc3-role" --role-session-name dc3 2>&1 | tail -3
```

**Task.** There are **two** independent faults. Find both.

??? note "Hint"
    Print `alice sts get-caller-identity --query Arn --output text` and compare it character by character with the `Principal` in the trust policy. Then read `dnb-assume-batch-role`'s `Resource` element.

### DC4 — The Lambda with no logs

```bash
cat > debug/dc4-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
cat > debug/dc4-trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TrustLambda",
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com.rproxy.gov.aws" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON
cat > debug/dc4-perms.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::dnb-statements-dev/incoming/*"
    }
  ]
}
JSON
aws iam create-role --role-name dnb-dc4-exec \
  --assume-role-policy-document file://debug/dc4-trust.json >/dev/null 2>&1
aws iam put-role-policy --role-name dnb-dc4-exec --policy-name Perms \
  --policy-document file://debug/dc4-perms.json >/dev/null 2>&1
echo "DC4 ready. Symptoms: (1) Lambda refuses to accept this role, and after you fix that,"
echo "(2) the function executes but produces no CloudWatch logs at all."
SCRIPT
chmod +x debug/dc4-setup.sh && ./debug/dc4-setup.sh
aws iam get-role --role-name dnb-dc4-exec --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal' --output json
```

**Task.** Two faults again. Fix both and explain why the second produces *silence* rather than an error.

??? note "Hint"
    Read the service principal string out loud, one token at a time. Then list every action a function needs in order for CloudWatch Logs to receive anything.

### DC5 — The boundary that grants nothing

```bash
cat > debug/dc5-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
aws iam create-user --user-name dnb-dc5-dev --path /dnb/dev/ \
  --permissions-boundary "$(cat out/boundary-arn.txt)" >/dev/null 2>&1
echo "DC5 ready. Symptom: the ticket says 'dnb-dc5-dev has a boundary allowing s3:Get*,"
echo "so she should be able to read the statements bucket' — but every call is denied."
SCRIPT
chmod +x debug/dc5-setup.sh && ./debug/dc5-setup.sh
aws iam get-user --user-name dnb-dc5-dev --query 'User.PermissionsBoundary'
aws iam list-attached-user-policies --user-name dnb-dc5-dev --query 'AttachedPolicies' --output json
aws iam list-user-policies --user-name dnb-dc5-dev --query 'PolicyNames' --output json
```

**Task.** Explain the misconception in the ticket in one sentence, then fix it correctly (do **not** remove the boundary). Verify the intersection is what you intend.

### DC6 — The policy that will not save

```bash
cat > debug/dc6-broken.json <<'JSON'
{
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::000000000000:user/dnb-dev-alice" },
      "Action": ["s3:GetObject",],
      "Resource": "arn:aws:s3:::dnb-statements-dev/*",
      "Condition": { "StringEqual": { "aws:PrincipalTag/Environment": "dev" } }
    }
  ]
}
JSON
aws iam create-policy --policy-name dnb-dc6-policy --policy-document file://debug/dc6-broken.json 2>&1 | tail -3
```

**Task.** There are **four** distinct defects. Find all four, fix them, and state which would have failed *silently* rather than erroring if the others were absent.

??? note "Hint"
    Run `jq empty debug/dc6-broken.json` first. Then check: is this identity-based or resource-based? Is the condition operator a real one? What is missing at the top level?

### DC7 — The mysterious 60-minute failure

```bash
cat > debug/dc7-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
ACCT="$(aws sts get-caller-identity --query Account --output text)"
cat > debug/dc7-trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "TrustBatchRole",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::${ACCT}:role/dnb/dev/dnb-dev-batch-role" },
    "Action": "sts:AssumeRole"
  }]
}
JSON
aws iam create-role --role-name dnb-dc7-longjob --max-session-duration 43200 \
  --assume-role-policy-document file://debug/dc7-trust.json >/dev/null 2>&1
# Grant the CALLER side of the handshake too, so the only remaining variable is the
# role-chaining session cap — otherwise the challenge fails for the wrong reason.
cat > debug/dc7-caller.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ChainToDc7",
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::${ACCT}:role/dnb-dc7-longjob"
  }]
}
JSON
aws iam put-role-policy --role-name dnb-dev-batch-role --policy-name AllowChainToDc7 \
  --policy-document file://debug/dc7-caller.json >/dev/null 2>&1
echo "DC7 ready. Report from the platform team:"
echo "  'The 4-hour reconciliation job assumes dnb-dc7-longjob, whose MaxSessionDuration"
echo "   is 12 hours. It dies with ExpiredToken after exactly one hour, every night.'"
SCRIPT
chmod +x debug/dc7-setup.sh && ./debug/dc7-setup.sh
batch sts assume-role --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/dnb-dc7-longjob" \
  --role-session-name dc7 --duration-seconds 14400 2>&1 | tail -3
```

**Task.** Explain the exactly-one-hour behaviour, then propose **two** architecturally different fixes and state which you would choose for a nightly batch job and why.

### DC8 — The privilege escalation

```bash
cat > debug/dc8-setup.sh <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail
ACCT="$(aws sts get-caller-identity --query Account --output text)"
aws iam create-user --user-name dnb-dc8-junior --path /dnb/dev/ >/dev/null 2>&1
cat > debug/dc8-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "JuniorDeveloperAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject", "s3:ListBucket",
        "lambda:CreateFunction", "lambda:InvokeFunction", "lambda:UpdateFunctionCode",
        "logs:Describe*", "logs:Get*", "logs:FilterLogEvents",
        "iam:PassRole",
        "iam:ListRoles", "iam:GetRole"
      ],
      "Resource": "*"
    }
  ]
}
JSON
aws iam put-user-policy --user-name dnb-dc8-junior --policy-name JuniorAccess \
  --policy-document file://debug/dc8-policy.json >/dev/null 2>&1
echo "DC8 ready. A security review approved this policy as 'junior developer, read-only plus"
echo "their own Lambdas'. Your task: prove it is equivalent to AdministratorAccess."
SCRIPT
chmod +x debug/dc8-setup.sh && ./debug/dc8-setup.sh
```

**Task.**

1. Write the **exact command sequence** by which `dnb-dc8-junior` becomes account administrator. (Describe it; do not weaponise it beyond the lab.)
2. Identify the single smallest change that closes the hole.
3. Rewrite the policy so it delivers the *intended* access safely.
4. Add a check for this pattern to your `validate-policy.sh` from MC9.

??? note "Hint"
    The vulnerability is a *combination*, not a single action. Which two entries in that list, together, let you run arbitrary code as any role in the account?

### Debugging challenge answer template

```markdown
## DCn
**Symptom (verbatim CLI output):**
**Diagnostic sequence:** 1. … 2. … 3. …
**Root cause(s):**
**Evaluation-pipeline step involved (§3.3):**
**Fix applied (commands + policy diff):**
**Verification evidence:**
**Would Floci have caught this? If not, why not?**
**How would you prevent this class of bug organisation-wide?**
```

---

## 13. Interview Questions

### 13.1 Conceptual

1. Explain IAM's policy evaluation logic. In what order are the layers evaluated, and which verdicts are final?
2. What is the difference between authentication and authorisation, and which errors correspond to each?
3. Why can an IAM group not be a `Principal`?
4. Explain the difference between an identity-based policy, a resource-based policy, a permissions boundary, and a session policy — and which of them can *grant* permissions.
5. Why does a role need two policies? Name them and state the question each answers.
6. What is `iam:PassRole` and why is it dangerous when unscoped?
7. Why does S3 usually require two ARNs in a policy?
8. Explain the confused-deputy problem and how `sts:ExternalId` and `aws:SourceArn` address it.
9. What happens if you omit `"Version": "2012-10-17"`?
10. Why is `BoolIfExists` the correct operator for enforcing MFA?
11. Is IAM regional or global? What is the practical consequence for the CLI and for eventual consistency?
12. Explain the difference between a service role and a service-linked role.
13. What is an instance profile, and why does it exist when a role would seem sufficient?
14. Why can you not revoke an active STS session, and what do you do instead?
15. What is ABAC and when does it beat RBAC?
16. Explain the difference between an SCP and a permissions boundary — both are "ceilings".
17. Which credential prefixes exist and what do they tell you during triage?
18. What is the difference between `explicitDeny` and `implicitDeny` in simulator output, and how does the fix differ?
19. Why is `NotAction` with `Allow` risky?
20. What is IAM Identity Center and why is it the modern answer for human access?

### 13.2 Scenario-based

21. A developer says "I have `AdministratorAccess` but I still get `AccessDenied`." List every possible cause, in the order you would check them.
22. A Lambda function runs successfully but writes no CloudWatch logs. Diagnose.
23. An ECS task is stuck in `PENDING` with `CannotPullContainerError`. Which role is at fault and why?
24. A nightly job dies with `ExpiredToken` after exactly one hour despite a 12-hour `MaxSessionDuration`. Explain.
25. An access key was pushed to a public GitHub repository 20 minutes ago. Give your incident-response sequence, in order, with the reasoning for the ordering.
26. You must give a third-party auditor read-only access for two weeks. Design it, and justify every control.
27. A team lead must onboard developers without becoming an admin. Design it. What single condition makes this safe?
28. A bucket policy grants `"Principal": "*"` on `s3:GetObject`, yet the objects are not publicly accessible. Explain.
29. A KMS-encrypted object cannot be read even though the caller has `s3:GetObject` and `kms:Decrypt` in their IAM policy. Explain.
30. Your organisation wants "no resources outside `ap-south-1`". Compare implementing this as an SCP, a permissions boundary, and an identity policy.
31. Design tenant isolation for a 500-tenant SaaS on one DynamoDB table.
32. A junior engineer's policy has `iam:PassRole` on `"*"` plus `lambda:CreateFunction`. Explain the exposure to a non-technical manager in four sentences.
33. You inherit an account with 200 users, direct policy attachments everywhere, and no groups. Plan the remediation. What do you do first, and what do you do *last*?
34. A CI/CD pipeline needs to deploy CloudFormation stacks. Design its IAM so the pipeline itself is not an admin.
35. GitHub Actions must deploy to AWS with no stored secrets. Which STS operation, and what does the trust policy look like?

### 13.3 SAA-C03 certification style

36. A company needs an EC2 application to read from S3 with no credentials stored on the instance. What should a solutions architect recommend?
   **A.** Store an access key in `/etc/aws/credentials` with `chmod 600`
   **B.** Create an IAM role and attach it via an instance profile
   **C.** Embed credentials in the AMI
   **D.** Pass credentials as environment variables via user data
   → **B.** Instance profiles deliver auto-rotated temporary credentials via IMDS; A, C, D all persist a long-term secret.

37. Users in account A must access an S3 bucket in account B. Which combination is required? (Choose TWO)
   **A.** A bucket policy in B allowing the principal in A
   **B.** An identity policy in A allowing the S3 actions
   **C.** An identity policy in B allowing the principal in A
   **D.** A permissions boundary in A
   **E.** A service-linked role in B
   → **A and B.** Cross-account requires an allow on *both* sides.

38. A policy grants `s3:*` on `"*"`; a separate policy denies `s3:DeleteObject` on one bucket. What can the user do on that bucket?
   **A.** Everything including delete **B.** Nothing **C.** Everything except delete **D.** Only read
   → **C.** Explicit deny overrides any allow, but only for the denied action and resource.

39. Which is the MOST secure way to grant a partner company temporary access?
   **A.** Create an IAM user and email the keys
   **B.** A cross-account role with `sts:ExternalId` and a time condition
   **C.** Make the bucket public with an obscure name
   **D.** Share your own access key over an encrypted channel
   → **B.**

40. A company must ensure no member account can disable CloudTrail, even the account's own administrator. What should be used?
   **A.** IAM policy **B.** Permissions boundary **C.** Service control policy **D.** Bucket policy
   → **C.** SCPs cap what an entire member account can do, including its administrators.

41. An application must read a database password without storing it in code. MOST secure?
   **A.** Hard-code it **B.** Environment variable at build time **C.** Secrets Manager accessed via the task role **D.** A file in S3 with a public URL
   → **C.**

42. A developer needs to launch EC2 instances with a role attached but receives `AccessDenied` despite having `ec2:RunInstances`. What is missing?
   **A.** `ec2:DescribeInstances` **B.** `iam:PassRole` **C.** `sts:AssumeRole` **D.** `iam:CreateRole`
   → **B.**

43. Which provides the MOST granular, AWS-enforced multi-tenant isolation for a single DynamoDB table?
   **A.** One table per tenant **B.** Application-layer filtering **C.** `dynamodb:LeadingKeys` condition with a principal tag **D.** A separate account per tenant
   → **C** for a single table. (**D** is stronger isolation overall but is not "for a single table".)

44. A company wants engineers to sign in with their existing corporate credentials and receive temporary AWS access. Which should be recommended?
   **A.** An IAM user per engineer **B.** IAM Identity Center federated to the corporate IdP **C.** Shared root credentials **D.** Access keys distributed by email
   → **B.**

45. After a `Deny` is added to a permissions boundary, a role that previously worked now fails. The role's identity policy still allows the action. Why?
   **A.** Boundaries grant permissions **B.** Effective permissions are the intersection, and explicit deny in any layer is final **C.** Identity policies are ignored when a boundary exists **D.** The role must be recreated
   → **B.**

### 13.4 Hands-on / whiteboard

46. Write, from memory, a trust policy allowing EC2 to assume a role.
47. Write a policy giving a user access only to their own S3 prefix, using one document for all users.
48. Write the CLI sequence to create a role, attach a policy, and assume it.
49. Write a policy denying all actions outside two regions while keeping global services usable.
50. Write the correct four-phase key-rotation command sequence.
51. Write the complete deletion sequence for a user with two keys, a login profile, one inline policy, one attached policy, one group, and a permissions boundary.
52. Given only `aws sts get-caller-identity` output, list everything you can infer about the caller.
53. Write a bucket policy that denies all non-TLS access and prevents its own deletion.
54. Write the `iam:PassRole` statement that safely permits Lambda deployment.
55. Write a one-liner that lists every customer managed policy allowing `Action: *` on `Resource: *`.

---

## 14. Viva Questions

For a 15–20 minute oral examination. The examiner should ask candidates to **demonstrate at the terminal**, not merely describe.

### Tier 1 — Foundations (must pass)

| # | Question | Look for |
|---|---|---|
| V1 | Show me who you are authenticated as, and explain every field. | `sts get-caller-identity`; explains `UserId` prefixes and the `iam` vs `sts` ARN |
| V2 | Decompose this ARN aloud: `arn:aws:iam::000000000000:role/dnb/dev/dnb-dev-app-role`. | Names all six fields; explains why region is empty |
| V3 | Create a user with our naming convention and mandatory tags. | Correct prefix, path, all five tags, no typos |
| V4 | Why should this user not have a policy attached directly? | Groups; onboarding/offboarding; auditability |
| V5 | What can a brand-new IAM user do? | Nothing — implicit deny by default |
| V6 | Difference between authentication and authorisation, with the error code for each. | `InvalidClientTokenId`/`SignatureDoesNotMatch` vs `AccessDenied` |

### Tier 2 — Policies

| # | Question | Look for |
|---|---|---|
| V7 | Write a policy allowing read of one bucket. Explain each element. | Two ARNs, two statements, `Version`, `Sid`s |
| V8 | Why two ARNs? | Bucket-level vs object-level actions |
| V9 | Managed vs inline — when would you deliberately choose inline? | Reuse/versioning/audit vs one-off tied to a principal's lifetime |
| V10 | Show me the live document of a managed policy. | `get-policy` → `DefaultVersionId` → `get-policy-version` |
| V11 | Roll a policy back to a previous version. | `set-default-policy-version`, one call |
| V12 | What happens if you omit `Version`? | Defaults to 2008-10-17; policy variables become literals; silent failure |
| V13 | Explain `Deny` + `NotAction` versus `Allow` + `NotAction`. | Guardrail vs unbounded future-action grant |

### Tier 3 — Roles and STS

| # | Question | Look for |
|---|---|---|
| V14 | Create a role assumable by EC2 and explain both policies. | Exact service principal; trust vs permissions |
| V15 | Assume a role and show that your identity changed. | `sts:assumed-role` ARN; session name; path dropped |
| V16 | Both sides must allow — show me both. | Caller identity policy **and** trust policy |
| V17 | Why is a chained session capped at one hour? | Chaining rule; the `ExpiredToken` symptom |
| V18 | Explain the confused deputy and defend against it. | `sts:ExternalId`; `aws:SourceArn`/`aws:SourceAccount` |
| V19 | Show me an instance profile and explain why it exists. | 1:1 with role; EC2 cannot reference a role directly |
| V20 | Revoke a live session right now. | `Deny` on `aws:TokenIssueTime`; explains why deletion is impossible |

### Tier 4 — Evaluation and defence

| # | Question | Look for |
|---|---|---|
| V21 | Walk me through the evaluation pipeline from memory. | Deny → SCP → RCP → boundary → session → allow → implicit deny |
| V22 | Same-account vs cross-account: OR or AND? | OR / AND, with a worked example |
| V23 | Does a permissions boundary grant anything? Prove it. | Dana: boundary + no policies = no access |
| V24 | Design safe IAM delegation. What is the one indispensable condition? | `iam:PermissionsBoundary` on create actions |
| V25 | Here is a policy with `iam:PassRole` on `*` and `lambda:CreateFunction`. What have I given away? | Full account admin; explains the chain |
| V26 | This error says "explicit deny in an identity-based policy". What will you do first? | Find the `Deny` — adding an `Allow` is futile |
| V27 | Diagnose `AccessDenied` on `s3:PutObject` for an auditor. | Groups → inline → `NotAction` list → correct architectural answer |

### Tier 5 — Floci literacy (LO12)

| # | Question | Look for |
|---|---|---|
| V28 | Which IAM operations does *your* build not support? Show me the evidence. | Produces `support-matrix.tsv`; explains the classifier |
| V29 | Show me one place your build diverges from AWS, and reason out the AWS-correct verdict. | Cites `divergence-report.md` and the pipeline step |
| V30 | Why is a successful command under the default Floci profile not evidence that a policy works? | Default credentials are account-root-equivalent |
| V31 | Which three of your DNB controls could you not verify locally, and how would you verify them in real AWS? | Named controls + a concrete sandbox test plan |

### Assessment rubric

| Band | Descriptor |
|---|---|
| Distinction (85–100) | Answers all tiers; writes correct policies unaided; reasons about the pipeline fluently; articulates emulator limits precisely; anticipates escalation vectors |
| Merit (70–84) | Tiers 1–4 solid; minor policy syntax slips; understands boundaries and chaining; aware of emulator limits |
| Pass (50–69) | Tiers 1–2 solid; can create users/groups/roles; knows deny-wins and default-deny; needs prompting on boundaries/session policies |
| Fail (<50) | Cannot distinguish trust from permissions policies; believes boundaries grant; cannot read an ARN; treats emulator success as proof |

---

## 15. Reflection Questions

Answer in prose, 150–250 words each, in `reflection.md`.

### On what you built

1. Sketch, from memory, the complete IAM architecture you built for DNB. Which single component was hardest to get right, and what specifically made it hard?
2. You replaced the `dnb-svc-batch` user with `dnb-dev-batch-role`. Name three concrete risks that disappeared and one new operational complexity that appeared.
3. Which of your policies would you be least comfortable defending to an auditor, and why?

### On what you learned

4. Before this module, what did you believe about cloud permissions that turned out to be wrong?
5. Which idea took longest to click: default-deny, deny-wins, boundaries-intersect, or the trust/permissions split? What finally made it clear?
6. The evaluation pipeline has seven steps. Which one do you think causes the most production incidents, and why?

### On mistakes

7. List every error message you personally triggered. Group them into authentication, authorisation, malformed, and dependency/quota. Which group did you hit most, and what does that say about where your mental model was weakest?
8. Describe a moment where you were confident a policy was correct and it was not. What was the actual defect and what habit would have caught it earlier?
9. `file://` versus no prefix, `Bool` versus `BoolIfExists`, bucket ARN versus `bucket/*`. Each of these is a tiny detail with large consequences. What does that tell you about writing IAM by hand versus generating it from code?

### On security

10. §9.4 lists fifteen privilege-escalation vectors. Pick the one you find most surprising and explain why it is easy to grant accidentally.
11. Argue *against* least privilege: what are its genuine costs to a development team, and how would you keep it from becoming a bottleneck?
12. DNB's requirement R9 is "revoke any credential in under five minutes". Which credential type is hardest to satisfy this for, and what design decision made in advance would make it easy?
13. If you had to keep exactly three of the fifteen best practices in §9.1 and drop the rest, which three, and why those?

### On emulator-based learning

14. Quantify it: roughly what proportion of what you learned could you *verify* locally, versus had to reason about? Where is the boundary?
15. Describe one belief you would have formed incorrectly if you had trusted Floci's behaviour uncritically.
16. Design a 30-minute validation plan for a real AWS sandbox account that would confirm the parts Floci could not. Be specific about commands and expected outputs.

### On the bigger picture

17. IAM is free and global. What does its being free tell you about how AWS views it, and what does its being global cost you operationally?
18. Where does IAM sit in a defence-in-depth architecture alongside VPCs, security groups, KMS, and CloudTrail? Which layers are preventive and which detective?
19. The modern recommendation is zero IAM users — federation only. If IAM users are the wrong answer for humans, why does the service still centre on them, and what would you tell a team starting a greenfield AWS account today?
20. You are now the most IAM-literate person on a five-person startup team about to launch on AWS. Write the five rules you would put in the team's engineering handbook on day one.

---

## 16. Cleanup

!!! danger "Cleanup order matters"
    IAM enforces dependencies. Detach before delete, remove children before parents, and delete non-default policy versions before the policy. The script below is idempotent — safe to run repeatedly.

### 16.1 The full teardown script

```bash
cat > ~/iam-lab/cleanup.sh <<'SCRIPT'
#!/usr/bin/env bash
# Complete teardown of every resource created by this module.
# Idempotent: safe to re-run. Errors on already-absent objects are suppressed.
set -uo pipefail
cd ~/iam-lab
q() { "$@" >/dev/null 2>&1; }
say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

case "${AWS_ENDPOINT_URL:-}" in
  *localhost*|*127.0.0.1*|*floci*) : ;;
  *) echo "REFUSING: AWS_ENDPOINT_URL is '${AWS_ENDPOINT_URL:-<empty>}' — not a Floci endpoint." >&2; exit 1 ;;
esac
ACCT="$(aws sts get-caller-identity --query Account --output text)"

# ---------------------------------------------------------------- 1. Workloads
say "1. Lambda functions"
for f in dnb-dev-statement-processor dnb-dev-carol-fn; do
  q aws lambda delete-function --function-name "$f" && echo "  deleted function $f"
done
q aws logs delete-log-group --log-group-name /aws/lambda/dnb-dev-statement-processor

say "2. EC2 instances"
if [ -f out/instance-id.txt ]; then
  . out/instance-id.txt
  ASSOC="$(aws ec2 describe-iam-instance-profile-associations \
      --filters "Name=instance-id,Values=${INSTANCE_ID:-none}" \
      --query 'IamInstanceProfileAssociations[0].AssociationId' --output text 2>/dev/null)"
  [ -n "${ASSOC:-}" ] && [ "$ASSOC" != "None" ] && q aws ec2 disassociate-iam-instance-profile --association-id "$ASSOC"
  q aws ec2 terminate-instances --instance-ids "${INSTANCE_ID:-none}" && echo "  terminated ${INSTANCE_ID:-}"
fi

# ------------------------------------------------------- 3. Instance profiles
say "3. Instance profiles"
for p in dnb-dev-app-profile; do
  for r in $(aws iam get-instance-profile --instance-profile-name "$p" \
               --query 'InstanceProfile.Roles[].RoleName' --output text 2>/dev/null); do
    q aws iam remove-role-from-instance-profile --instance-profile-name "$p" --role-name "$r"
  done
  q aws iam delete-instance-profile --instance-profile-name "$p" && echo "  deleted profile $p"
done

# ----------------------------------------------------------------- 4. Buckets
say "4. S3 buckets"
for b in dnb-statements-dev dnb-audit-logs-dev dnb-home-dev; do
  q aws s3api delete-bucket-policy --bucket "$b"
  q aws s3 rm "s3://$b" --recursive
  q aws s3 rb "s3://$b" && echo "  removed bucket $b"
done

# ------------------------------------------------------------------- 5. Roles
say "5. Roles"
ROLES="dnb-dev-batch-role dnb-dev-reporting-role dnb-dev-app-role dnb-dev-lambda-exec-role
       dnb-external-audit-role dnb-dev-external-role dnb-dev-second-role dnb-broken-group-trust
       dnb-dc3-role dnb-dc4-exec dnb-dc7-longjob"
for r in $ROLES; do
  aws iam get-role --role-name "$r" >/dev/null 2>&1 || continue
  for p in $(aws iam list-attached-role-policies --role-name "$r" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    q aws iam detach-role-policy --role-name "$r" --policy-arn "$p"
  done
  for p in $(aws iam list-role-policies --role-name "$r" --query 'PolicyNames[]' --output text 2>/dev/null); do
    q aws iam delete-role-policy --role-name "$r" --policy-name "$p"
  done
  q aws iam delete-role-permissions-boundary --role-name "$r"
  for ip in $(aws iam list-instance-profiles-for-role --role-name "$r" --query 'InstanceProfiles[].InstanceProfileName' --output text 2>/dev/null); do
    q aws iam remove-role-from-instance-profile --instance-profile-name "$ip" --role-name "$r"
  done
  q aws iam delete-role --role-name "$r" && echo "  deleted role $r"
done

# ------------------------------------------------------------------- 6. Users
say "6. Users"
USERS="dnb-dev-alice dnb-dev-bob dnb-dev-carol dnb-dev-dana dnb-dev-dana2 dnb-svc-batch
       dnb-temp-victim dnb-dev-e1 dnb-dev-e2 dnb-dev-e3 dnb-dev-lead
       dnb-dc1-user dnb-dc2-auditor dnb-dc5-dev dnb-dc8-junior
       dnb-should-not-exist dnb-boundary-escape-test __audit_probe__ __audit_probe_bob__"
for u in $USERS; do
  aws iam get-user --user-name "$u" >/dev/null 2>&1 || continue
  for g in $(aws iam list-groups-for-user --user-name "$u" --query 'Groups[].GroupName' --output text 2>/dev/null); do
    q aws iam remove-user-from-group --group-name "$g" --user-name "$u"
  done
  for k in $(aws iam list-access-keys --user-name "$u" --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null); do
    q aws iam delete-access-key --user-name "$u" --access-key-id "$k"
  done
  q aws iam delete-login-profile --user-name "$u"
  for m in $(aws iam list-mfa-devices --user-name "$u" --query 'MFADevices[].SerialNumber' --output text 2>/dev/null); do
    q aws iam deactivate-mfa-device --user-name "$u" --serial-number "$m"
    q aws iam delete-virtual-mfa-device --serial-number "$m"
  done
  for p in $(aws iam list-user-policies --user-name "$u" --query 'PolicyNames[]' --output text 2>/dev/null); do
    q aws iam delete-user-policy --user-name "$u" --policy-name "$p"
  done
  for p in $(aws iam list-attached-user-policies --user-name "$u" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    q aws iam detach-user-policy --user-name "$u" --policy-arn "$p"
  done
  q aws iam delete-user-permissions-boundary --user-name "$u"
  q aws iam delete-user --user-name "$u" && echo "  deleted user $u"
done

say "6b. Generic sweep: any remaining dnb-* users and roles from the challenges"
for u in $(aws iam list-users --query 'Users[?starts_with(UserName, `dnb-`)].UserName' --output text 2>/dev/null); do
  for g in $(aws iam list-groups-for-user --user-name "$u" --query 'Groups[].GroupName' --output text 2>/dev/null); do
    q aws iam remove-user-from-group --group-name "$g" --user-name "$u"; done
  for k in $(aws iam list-access-keys --user-name "$u" --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null); do
    q aws iam delete-access-key --user-name "$u" --access-key-id "$k"; done
  q aws iam delete-login-profile --user-name "$u"
  for p in $(aws iam list-user-policies --user-name "$u" --query 'PolicyNames[]' --output text 2>/dev/null); do
    q aws iam delete-user-policy --user-name "$u" --policy-name "$p"; done
  for p in $(aws iam list-attached-user-policies --user-name "$u" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    q aws iam detach-user-policy --user-name "$u" --policy-arn "$p"; done
  q aws iam delete-user-permissions-boundary --user-name "$u"
  q aws iam delete-user --user-name "$u" && echo "  swept user $u"
done
for r in $(aws iam list-roles --query 'Roles[?starts_with(RoleName, `dnb-`)].RoleName' --output text 2>/dev/null); do
  for p in $(aws iam list-attached-role-policies --role-name "$r" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    q aws iam detach-role-policy --role-name "$r" --policy-arn "$p"; done
  for p in $(aws iam list-role-policies --role-name "$r" --query 'PolicyNames[]' --output text 2>/dev/null); do
    q aws iam delete-role-policy --role-name "$r" --policy-name "$p"; done
  q aws iam delete-role-permissions-boundary --role-name "$r"
  for ip in $(aws iam list-instance-profiles-for-role --role-name "$r" --query 'InstanceProfiles[].InstanceProfileName' --output text 2>/dev/null); do
    q aws iam remove-role-from-instance-profile --instance-profile-name "$ip" --role-name "$r"; done
  q aws iam delete-role --role-name "$r" && echo "  swept role $r"
done

# ------------------------------------------------------------------ 7. Groups
say "7. Groups"
for g in $(aws iam list-groups --query 'Groups[?starts_with(GroupName, `dnb-`)].GroupName' --output text 2>/dev/null) \
         dnb-developers dnb-auditors dnb-admins dnb-dc1-group; do
  aws iam get-group --group-name "$g" >/dev/null 2>&1 || continue
  for u in $(aws iam get-group --group-name "$g" --query 'Users[].UserName' --output text 2>/dev/null); do
    q aws iam remove-user-from-group --group-name "$g" --user-name "$u"
  done
  for p in $(aws iam list-attached-group-policies --group-name "$g" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
    q aws iam detach-group-policy --group-name "$g" --policy-arn "$p"
  done
  for p in $(aws iam list-group-policies --group-name "$g" --query 'PolicyNames[]' --output text 2>/dev/null); do
    q aws iam delete-group-policy --group-name "$g" --policy-name "$p"
  done
  q aws iam delete-group --group-name "$g" && echo "  deleted group $g"
done

# --------------------------------------------------- 8. Customer managed policies
say "8. Customer managed policies (dnb-* only)"
for arn in $(aws iam list-policies --scope Local --query 'Policies[?starts_with(PolicyName, `dnb-`)].Arn' --output text 2>/dev/null); do
  for e in $(aws iam list-entities-for-policy --policy-arn "$arn" --query 'PolicyUsers[].UserName'  --output text 2>/dev/null); do
    q aws iam detach-user-policy  --user-name  "$e" --policy-arn "$arn"; done
  for e in $(aws iam list-entities-for-policy --policy-arn "$arn" --query 'PolicyGroups[].GroupName' --output text 2>/dev/null); do
    q aws iam detach-group-policy --group-name "$e" --policy-arn "$arn"; done
  for e in $(aws iam list-entities-for-policy --policy-arn "$arn" --query 'PolicyRoles[].RoleName'  --output text 2>/dev/null); do
    q aws iam detach-role-policy  --role-name  "$e" --policy-arn "$arn"; done
  for v in $(aws iam list-policy-versions --policy-arn "$arn" \
               --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text 2>/dev/null); do
    q aws iam delete-policy-version --policy-arn "$arn" --version-id "$v"
  done
  q aws iam delete-policy --policy-arn "$arn" && echo "  deleted policy $arn"
done

# ----------------------------------------------------------- 9. Account settings
say "9. Account password policy"
q aws iam delete-account-password-policy && echo "  password policy removed"

# ------------------------------------------------------------ 10. Local artefacts
say "10. Local credentials and profiles"
for p in carol alice bob dana batch; do
  q aws configure set aws_access_key_id     "" --profile "$p"
  q aws configure set aws_secret_access_key "" --profile "$p"
done
rm -f out/*-key*.json out/*session*.json
echo "  local key files removed (edit ~/.aws/credentials to drop the stanzas entirely)"

# ------------------------------------------------------------------ 11. Verify
say "11. Verification"
printf 'remaining dnb users   : %s\n' "$(aws iam list-users  --query 'length(Users[?starts_with(UserName,  `dnb-`)])' --output text 2>/dev/null)"
printf 'remaining dnb groups  : %s\n' "$(aws iam list-groups --query 'length(Groups[?starts_with(GroupName, `dnb-`)])' --output text 2>/dev/null)"
printf 'remaining dnb roles   : %s\n' "$(aws iam list-roles  --query 'length(Roles[?starts_with(RoleName,   `dnb-`)])' --output text 2>/dev/null)"
printf 'remaining dnb policies: %s\n' "$(aws iam list-policies --scope Local --query 'length(Policies[?starts_with(PolicyName, `dnb-`)])' --output text 2>/dev/null)"
printf 'remaining profiles    : %s\n' "$(aws iam list-instance-profiles --query 'length(InstanceProfiles[?starts_with(InstanceProfileName, `dnb-`)])' --output text 2>/dev/null)"
printf 'remaining buckets     : %s\n' "$(aws s3 ls 2>/dev/null | grep -c dnb- || echo 0)"
echo
echo "All counts should read 0. Any non-zero value indicates a dependency the script missed —"
echo "investigate with list-entities-for-policy / get-group / list-attached-*-policies."
SCRIPT
chmod +x ~/iam-lab/cleanup.sh
~/iam-lab/cleanup.sh
```

### 16.2 Manual verification

```bash
aws iam list-users     --query 'Users[].UserName'   --output text
aws iam list-groups    --query 'Groups[].GroupName' --output text
aws iam list-roles     --query 'Roles[].RoleName'   --output text
aws iam list-policies --scope Local --query 'Policies[].PolicyName' --output text
aws iam list-instance-profiles --query 'InstanceProfiles[].InstanceProfileName' --output text
aws s3 ls
```

### 16.3 Nuclear option

```bash
# Discard ALL emulator state and start from a clean account.
floci stop --remove
rm -rf ~/iam-lab/floci-state
floci start --persist ./floci-state --detach && floci wait --timeout 2m
eval "$(floci env)"
aws iam list-users --query 'length(Users)' --output text     # → 0
```

### 16.4 Keep these

| Keep | Why |
|---|---|
| `~/iam-lab/policies/*.json` | Your policy portfolio — submitted work and a genuinely useful personal reference |
| `~/iam-lab/out/support-matrix.tsv` | Evidence for LO12 |
| `~/iam-lab/out/divergence-report.md` | Assessed deliverable |
| `~/iam-lab/out/posture-audit.txt` | Assessed deliverable |
| `~/iam-lab/*.sh` | Reusable tooling: probe, audit, purge, validate, rotate |
| `~/iam-lab/out/logbook.md` | Your reflection source material |

!!! danger "Remove the credential stanzas from `~/.aws/credentials`"
    Blanking the values with `aws configure set` leaves empty `[carol]`, `[alice]`, `[bob]`, `[dana]`, `[batch]` sections behind, and a stale `[profile x]` in `~/.aws/config` can silently redirect a future command. Open both files and delete the stanzas by hand. Never leave lab profiles configured on a machine that also has real AWS credentials.

---

## 17. Summary

### 17.1 The ten sentences that matter

1. IAM is a **global, free, deny-by-default** authorisation engine that decides every AWS API request.
2. **Explicit deny always wins; absence of an allow is a deny.**
3. **Users** are for humans (ideally replaced by federation); **groups** scale permissions to humans; **roles** are for everything else.
4. A role always needs **two** policies: a trust policy (who may assume) and permissions policies (what the session may do).
5. Role assumption requires an allow on **both** sides — the caller's identity policy and the role's trust policy.
6. **Permissions boundaries and session policies filter; they never grant.** Effective permissions are an intersection.
7. Same-account access needs identity **OR** resource policy; cross-account needs **both**.
8. **Temporary credentials beat long-term keys** every time; the only safe access key is the one that does not exist.
9. **Unscoped `iam:PassRole` is account takeover** — scope it by `Resource` and `iam:PassedToService`.
10. An emulator stores policies; **AWS enforces them**. Never treat local success as proof of a permission model.

### 17.2 Command reference

**Identity**

```bash
aws sts get-caller-identity
aws sts assume-role --role-arn ARN --role-session-name NAME [--duration-seconds N] [--external-id ID] [--policy JSON]
aws sts get-session-token --serial-number MFA_ARN --token-code 123456
```

**Users**

```bash
aws iam create-user --user-name N --path /p/ --tags Key=K,Value=V [--permissions-boundary ARN]
aws iam get-user   --user-name N
aws iam list-users [--path-prefix /p/]
aws iam update-user --user-name N --new-user-name M [--new-path /q/]
aws iam tag-user   --user-name N --tags Key=K,Value=V
aws iam untag-user --user-name N --tag-keys K
aws iam delete-user --user-name N
```

**Groups**

```bash
aws iam create-group --group-name G --path /p/
aws iam add-user-to-group      --group-name G --user-name U
aws iam remove-user-from-group --group-name G --user-name U
aws iam get-group --group-name G
aws iam list-groups-for-user --user-name U
aws iam delete-group --group-name G
```

**Policies — managed**

```bash
aws iam create-policy --policy-name P --path /p/ --description D --policy-document file://f.json --tags Key=K,Value=V
aws iam get-policy         --policy-arn ARN
aws iam get-policy-version --policy-arn ARN --version-id vN
aws iam list-policy-versions --policy-arn ARN
aws iam create-policy-version --policy-arn ARN --policy-document file://f.json [--set-as-default]
aws iam set-default-policy-version --policy-arn ARN --version-id vN
aws iam delete-policy-version --policy-arn ARN --version-id vN
aws iam list-entities-for-policy --policy-arn ARN
aws iam attach-user-policy  --user-name  U --policy-arn ARN
aws iam attach-group-policy --group-name G --policy-arn ARN
aws iam attach-role-policy  --role-name  R --policy-arn ARN
aws iam detach-user-policy  --user-name  U --policy-arn ARN
aws iam delete-policy --policy-arn ARN
aws iam list-policies --scope Local|AWS|All [--only-attached]
```

**Policies — inline**

```bash
aws iam put-user-policy    --user-name  U --policy-name P --policy-document file://f.json
aws iam put-group-policy   --group-name G --policy-name P --policy-document file://f.json
aws iam put-role-policy    --role-name  R --policy-name P --policy-document file://f.json
aws iam get-user-policy    --user-name  U --policy-name P
aws iam list-user-policies --user-name  U
aws iam delete-user-policy --user-name  U --policy-name P
```

**Roles**

```bash
aws iam create-role --role-name R --path /p/ --assume-role-policy-document file://trust.json \
    --max-session-duration N --description D --tags Key=K,Value=V [--permissions-boundary ARN]
aws iam get-role --role-name R
aws iam update-assume-role-policy --role-name R --policy-document file://trust.json
aws iam update-role --role-name R --max-session-duration N --description D
aws iam list-roles [--path-prefix /p/]
aws iam delete-role --role-name R
```

**Instance profiles**

```bash
aws iam create-instance-profile --instance-profile-name IP --path /p/
aws iam add-role-to-instance-profile      --instance-profile-name IP --role-name R
aws iam remove-role-from-instance-profile --instance-profile-name IP --role-name R
aws iam get-instance-profile --instance-profile-name IP
aws iam delete-instance-profile --instance-profile-name IP
aws ec2 run-instances --iam-instance-profile Name=IP --metadata-options HttpTokens=required ...
aws ec2 replace-iam-instance-profile-association --association-id A --iam-instance-profile Name=IP2
```

**Credentials**

```bash
aws iam create-access-key --user-name U
aws iam list-access-keys  --user-name U
aws iam update-access-key --user-name U --access-key-id K --status Active|Inactive
aws iam delete-access-key --user-name U --access-key-id K
aws iam get-access-key-last-used --access-key-id K
aws iam create-login-profile --user-name U --password P --password-reset-required
aws iam delete-login-profile --user-name U
aws iam update-account-password-policy --minimum-password-length 14 --require-symbols ...
aws iam get-account-password-policy
```

**Boundaries**

```bash
aws iam put-user-permissions-boundary --user-name U --permissions-boundary ARN
aws iam put-role-permissions-boundary --role-name R --permissions-boundary ARN
aws iam delete-user-permissions-boundary --user-name U
aws iam delete-role-permissions-boundary --role-name R
```

**Audit**

```bash
aws iam get-account-summary
aws iam get-account-authorization-details
aws iam generate-credential-report && aws iam get-credential-report --query Content --output text | base64 -d
aws iam simulate-principal-policy --policy-source-arn ARN --action-names a1 a2 --resource-arns r1
aws iam simulate-custom-policy --policy-input-list JSON --action-names a1
aws iam generate-service-last-accessed-details --arn ARN
```

**Floci**

```bash
floci start --persist ./floci-state --detach [--port 4599] [--services iam,sts,s3]
floci wait --timeout 2m
floci status [-o json]
floci env [--shell fish|powershell] [-o json]
floci logs [--tail N] [--follow]
floci doctor [--fix]
floci stop [--remove] [--timeout 30]
floci config show | floci config profile list
```

### 17.3 Architecture at a glance

```
  ACCOUNT (the hard boundary)
  ├── root user ─── sealed: hardware MFA, no keys, no daily use
  │
  ├── PRINCIPALS
  │   ├── users ──── in groups ──── policies       [humans; prefer federation]
  │   ├── roles ──── trust + permissions            [workloads, cross-account, federation]
  │   │      └── wrapped by instance profile        [EC2 only]
  │   └── federated / assumed-role sessions         [temporary, ASIA…]
  │
  ├── POLICY TYPES (6)
  │   identity: AWS-managed | customer-managed | inline     → GRANT
  │   resource: bucket/key/queue/trust policy               → GRANT (+cross-account)
  │   boundary                                              → FILTER
  │   session                                               → FILTER
  │
  ├── EVALUATION
  │   explicit Deny  >  SCP  >  RCP  >  boundary  >  session  >  Allow  >  implicit Deny
  │   same account = OR   ·   cross account = AND
  │
  └── OBSERVABILITY
      CloudTrail · credential report · Access Advisor · Access Analyzer · simulator
```

### 17.4 Security checklist to carry forward

```
 [ ] Root sealed: hardware MFA, zero access keys, alarm on any root API call
 [ ] Zero IAM users for humans — federated via IAM Identity Center
 [ ] Zero long-term access keys for workloads — roles only
 [ ] No policy attached directly to a user
 [ ] No Allow with Action:* on Resource:* outside a reviewed AdministratorAccess
 [ ] No role trusting Principal:*  ·  no bucket policy with Allow to Principal:*
 [ ] iam:PassRole scoped by Resource AND iam:PassedToService everywhere
 [ ] Permissions boundary on every delegated admin, with the iam:PermissionsBoundary condition
 [ ] Explicit Deny invariants: TLS-only, region allow-list, no-delete for append-only workloads
 [ ] MFA enforced in policy with BoolIfExists, not requested by email
 [ ] max-session-duration as short as the workload tolerates
 [ ] Every principal and resource carries the mandatory tag set
 [ ] IMDSv2 required on every instance
 [ ] CloudTrail org trail to a locked-down account, log file validation on
 [ ] Quarterly: credential report, Access Analyzer findings, orphaned-policy sweep
 [ ] Documented onboarding AND offboarding runbooks, including STS session revocation
```

### 17.5 Operational best practices

| Practice | Why |
|---|---|
| **IAM as code** (CloudFormation / Terraform / CDK) | Reviewable, versioned, reproducible; eliminates the CLI typo class of bug entirely |
| Policy validation in CI | Catch `Action:*`/`Resource:*` and unscoped `PassRole` **before** merge (your MC9 script) |
| Least privilege by evidence | Broad-but-bounded in dev → measure with Access Advisor → tighten → ship |
| Break-glass, not standing admin | Nobody holds admin day to day; emergency access is short, MFA'd, and alarmed |
| Automated key rotation | A calendar reminder is not a control |
| Automated dormancy sweep | Delete users with no activity in 90 days; delete roles never assumed in 90 days |
| Tag-driven cleanup | `ExpiresOn` tags plus a scheduled Lambda that removes expired access |
| Blameless post-incident review | Every `AccessDenied` outage is a signal about your permission model, not about the engineer |

### 17.6 What to do next

| Next step | Why |
|---|---|
| **A real AWS free-tier sandbox account** | Run your §15 Q16 validation plan and confirm what Floci could not: condition evaluation, boundaries, SCPs, IMDS, Access Analyzer |
| **The KMS module** | Key policies are *authoritative* over IAM — the most important exception to everything here |
| **The S3 module** | Bucket policies, Block Public Access, Object Ownership, and access points in depth |
| **The Organizations / Identity Center module** | The layers above IAM that real multi-account AWS actually runs on |
| **IAM as code** | Rebuild the entire DNB design in CloudFormation, then diff it against what you built by hand |
| **SAA-C03 practice** | Domain 1 questions are largely IAM. If you can answer §13.3 unaided, you are on track |

---

## End-of-Module Exercises

**Submission bundle** — one archive containing:

| # | Artefact | Weight |
|---|---|---|
| 1 | `out/support-matrix.tsv` + `out/support-report.txt` | 5% |
| 2 | `out/divergence-report.md`, with your written explanation of every divergence | 15% |
| 3 | `policies/` — every policy document, each statement carrying a `Sid` and a one-line comment justifying it | 15% |
| 4 | `dnb-iam-design.md` — the §6.7 enterprise deliverable, including the threat model | 25% |
| 5 | `mini-challenges.md` — MC1–MC9 with commands, policies, and verification evidence | 15% |
| 6 | `debugging-challenges.md` — DC1–DC8 using the §12 answer template | 15% |
| 7 | `reflection.md` — the §15 questions | 5% |
| 8 | `out/posture-audit.txt` + your `validate-policy.sh` and `purge-user.sh` | 5% |

**Marking notes for the assessor**

* A student who reports "the policy worked in Floci" without a named profile has not demonstrated LO12 and cannot pass Tier 5 of the viva.
* Reward correctly identified divergences highly. Finding a limitation and reasoning past it is the harder skill than making a command succeed.
* Penalise any policy containing `Action: *` with `Resource: *` outside an explicitly justified `AdministratorAccess` equivalent.
* Penalise unscoped `iam:PassRole` heavily — it is the single most consequential mistake in the module.
* Every statement in every submitted policy must have a `Sid`. No exceptions.

---

## Appendix A — Quick JSON templates

```json
{ "Version": "2012-10-17", "Statement": [ { "Sid": "", "Effect": "Allow", "Action": [], "Resource": [] } ] }
```

```json
{ "Version": "2012-10-17", "Statement": [ { "Sid": "TrustService", "Effect": "Allow", "Principal": { "Service": "SERVICE.amazonaws.com" }, "Action": "sts:AssumeRole" } ] }
```

```json
{ "Version": "2012-10-17", "Statement": [ { "Sid": "TrustAccount", "Effect": "Allow", "Principal": { "AWS": "arn:aws:iam::ACCOUNT:root" }, "Action": "sts:AssumeRole", "Condition": { "StringEquals": { "sts:ExternalId": "SECRET" } } } ] }
```

```json
{ "Version": "2012-10-17", "Statement": [ { "Sid": "DenyGuardrail", "Effect": "Deny", "NotAction": [ "iam:*", "sts:*" ], "Resource": "*", "Condition": { "StringNotEquals": { "aws:RequestedRegion": [ "us-east-1" ] } } } ] }
```

## Appendix B — Service principal reference

| Service | Principal string |
|---|---|
| EC2 | `ec2.amazonaws.com` |
| Lambda | `lambda.amazonaws.com` |
| ECS tasks | `ecs-tasks.amazonaws.com` |
| ECS service | `ecs.amazonaws.com` |
| EKS | `eks.amazonaws.com` |
| API Gateway | `apigateway.amazonaws.com` |
| CloudFormation | `cloudformation.amazonaws.com` |
| CodeBuild | `codebuild.amazonaws.com` |
| CodePipeline | `codepipeline.amazonaws.com` |
| EventBridge | `events.amazonaws.com` |
| Step Functions | `states.amazonaws.com` |
| Glue | `glue.amazonaws.com` |
| RDS | `rds.amazonaws.com` |
| Redshift | `redshift.amazonaws.com` |
| SNS | `sns.amazonaws.com` |
| SQS | `sqs.amazonaws.com` |
| S3 | `s3.amazonaws.com` |
| CloudWatch Logs | `logs.amazonaws.com` |
| Config | `config.amazonaws.com` |
| SSM | `ssm.amazonaws.com` |
| Backup | `backup.amazonaws.com` |
| Transfer Family | `transfer.amazonaws.com` |
| DMS | `dms.amazonaws.com` |
| Firehose | `firehose.amazonaws.com` |
| Batch | `batch.amazonaws.com` |
| SageMaker | `sagemaker.amazonaws.com` |

## Appendix C — Quotas (defaults; many are adjustable)

| Object | Limit |
|---|---|
| Users per account | 5 000 |
| Groups per account | 300 |
| Roles per account | 1 000 |
| Customer managed policies per account | 1 500 |
| Versions per managed policy | 5 |
| Groups per user | 10 |
| Managed policies attached per user/group/role | 10 (max 20) |
| Access keys per user | 2 |
| MFA devices per user | 8 |
| Roles per instance profile | 1 |
| Instance profiles per account | 1 000 |
| Managed policy size | 6 144 characters |
| Inline policy size — user / group / role | 2 048 / 5 120 / 10 240 characters |
| Session policy size (inline) | 2 048 characters |
| Bucket policy size | 20 KB |
| Role session duration | 900 s – 43 200 s (**3 600 s if chained**) |
| `GetSessionToken` duration | 900 s – 129 600 s (root: ≤ 3 600 s) |
| Tags per IAM entity | 50 |
| Path length | 512 characters |
| Name length — user/role/group | 64 / 64 / 128 characters |
| `RoleSessionName` length | 2 – 64 characters |

---

## Sources

* [Floci — Local Cloud Emulators](https://floci.io/) — product overview
* [floci — Fast, Free AWS Emulator](https://floci.io/aws/) — supported AWS services, IAM (68+ ops) and STS (7 ops), unified endpoint `localhost:4566`
* [floci-io/floci on GitHub](https://github.com/floci-io/floci) — service coverage, Docker Compose, environment variables
* [floci-io/floci-cli on GitHub](https://github.com/floci-io/floci-cli) — `floci start|stop|status|env|logs|doctor|wait|config` syntax and global flags
* [Floci — Local AWS Emulator (docs)](https://fredpena-floci.mintlify.app/introduction) — pointing the AWS CLI at the emulator
* [AWS IAM API Reference — Actions](https://docs.aws.amazon.com/IAM/latest/APIReference/API_Operations.html) — canonical IAM operation list
* [AWS IAM — SimulatePrincipalPolicy](https://docs.aws.amazon.com/IAM/latest/APIReference/API_SimulatePrincipalPolicy.html) — policy simulation semantics
* [Hacking the Cloud — AWS IAM privilege escalation techniques](https://hackingthe.cloud/aws/exploitation/iam_privilege_escalation/) — the escalation vectors catalogued in §9.4

!!! warning "Verify the Floci support tiers against your own build"
    Floci publishes an operation *count* rather than a per-operation list, and does not document whether control-plane authorisation is evaluated. Every ✅ / ⚠️ / ❌ in this module is a conservative estimate. **Your `support-matrix.tsv` and `divergence-report.md` are the authoritative record for your environment** — that is why producing them is Lab 0 and Lab 11 rather than an appendix.

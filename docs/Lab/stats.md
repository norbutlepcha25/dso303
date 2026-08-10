# AWS CLI + Floci Course — Cumulative State

Running record of what exists after each lab. **Read this before generating a new lab.**

## Scenario

University Student Management System (**USMS**) for the College of Science and Technology.
Students act as junior cloud engineers building one continuous architecture.
Resource naming convention: every resource is prefixed `usms-`.

## Environment baseline (established in Lab 01)

| Item | Value |
| --- | --- |
| Emulator | Floci, Docker container, `floci start --persist ~/floci-data --detach` |
| Endpoint | `http://localhost:4566` |
| Region | `us-east-1` |
| Account ID | `000000000000` |
| AWS CLI | v2, named profile `floci` with `endpoint_url` set; second profile `usms-dev` |
| Project root | `~/aws-floci-course` |
| Shared config | `configs/course.env` (sourced by every lab) |
| Helper scripts | `scripts/setup/floci-up.sh`, `scripts/utilities/whoami.sh`, `scripts/utilities/verify-lab-01.sh` |
| Snapshot | `floci snapshot save lab-01-iam-complete` |

Key Floci caveat carried through the whole course: **IAM policies are stored but not enforced by
default** — mark enforcement-dependent behaviour as *Conceptual / Real AWS*.

## Lab index

| Lab | Topic | Status | Doc |
| --- | --- | --- | --- |
| 01 | IAM | ✅ written | `labs/lab-01-iam.md` |
| 02 | VPC | ⬜ not written | — |

## Resources created — Lab 01 (IAM)

**Groups:** `usms-admins`, `usms-developers`, `usms-auditors`

**Users:** `usms-admin-01`, `usms-dev-01` (has access keys + inline policy), `usms-audit-01`

**Customer managed policies**

- `USMSDeveloperBase` — currently **v2** (v3 is Exercise 5); read infra + VPC-build actions
  conditioned on `us-east-1`; explicit Deny on IAM escalation actions
- `USMSStudentDataReadWrite` — bucket ARN `arn:aws:s3:::usms-student-data` + object ARN `/*`;
  Deny on `s3:DeleteBucket`
- `USMSAssumeAppRoles` — `sts:AssumeRole` on `usms-developer-role`
- `USMSLambdaBasic` — CloudWatch Logs write + `s3:GetObject` on student data
- `USMSReadOnly` — only if the Floci build lacks the AWS managed `ReadOnlyAccess`

**Inline policy:** `USMSSelfManageCredentials` on `usms-dev-01` (uses `${aws:username}`)

**Roles**

| Role | Trust principal | Permissions | Consumed by |
| --- | --- | --- | --- |
| `usms-ec2-app-role` | `ec2.amazonaws.com` | `USMSStudentDataReadWrite` | Lab 03 (EC2) |
| `usms-lambda-exec-role` | `lambda.amazonaws.com` | `USMSLambdaBasic` | Lab 05 (Lambda) |
| `usms-developer-role` | user `usms-dev-01`, max session 3600s | `USMSDeveloperBase` | Lab 02 (VPC) |

**Instance profile:** `usms-ec2-app-profile` → contains `usms-ec2-app-role` (Lab 03 attaches it)

**Config file written:** `configs/lab-01.env` exporting
`USMS_ACCOUNT_ID`, `USMS_*_USER`, `USMS_GROUP_*`, `USMS_POLICY_DEV_BASE`, `USMS_POLICY_S3_RW`,
`USMS_POLICY_ASSUME`, `USMS_ROLE_EC2`, `USMS_ROLE_LAMBDA`, `USMS_ROLE_DEVELOPER`,
`USMS_INSTANCE_PROFILE`, `USMS_BUCKET_NAME=usms-student-data`

## Planned but not yet created

- `usms-student-data` S3 bucket → Lab 04
- `usms-archive` bucket → referenced in Lab 01 Exercise 4
- `USMS_VPC_CIDR=10.0.0.0/16` → added to `lab-01.env` by Lab 01 Exercise 5

## Skills already taught (do not re-teach from scratch)

**AWS CLI:** service/operation grammar, `help`, `--profile`, `--region`, `--endpoint-url`,
`--output json|table|text`, `--query` (projection, `{rename}`, `[?filter]`, `| [0]`), `file://`,
`--generate-cli-skeleton`, `--debug`, `--tags`, `$( )` capture, `$?` exit codes,
`aws configure set|get|list-profiles`, credential resolution order.

**IAM:** ARN anatomy, policy document elements, policy variables, managed vs inline, policy versions,
trust vs permissions policy, instance profiles, STS assume-role, `AKIA` vs `ASIA`, key rotation,
least privilege, explicit vs implicit deny, `simulate-principal-policy`.

**Shell:** heredocs and `<< 'EOF'` vs `<< EOF`, `set -euo pipefail`, brace expansion, `chmod`,
`.gitignore` before secrets, `git check-ignore`, JSON validation with `python3 -m json.tool`.

**Not yet taught:** `--filters`, `--cli-input-json`, pagination (`--max-items`/`--starting-token`),
waiters (`aws ... wait`), CloudFormation, tagging-based cost allocation.

## Next lab

**Lab 02 — VPC.** Should open by sourcing `configs/course.env` + `configs/lab-01.env`, assuming
`usms-developer-role`, and building `10.0.0.0/16` with public + private subnets, IGW, route tables,
security groups. Introduce `--filters` and `aws ec2 wait`.
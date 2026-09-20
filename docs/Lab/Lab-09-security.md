# Lab 09 - Securing the USMS Application with IAM Roles and Security Groups

*Practical 5 in the delivery schedule, Practical 8 in the module descriptor - a least-privilege review
of a system that already works, on both of its access-control axes*

---

## 1. Lab Overview

Five laboratories built a working system. Not one of them reviewed it.

You have an identity layer from Lab 01, a network from Lab 02, two EC2 instances from Lab 03, a
container platform from Lab 04, a load balancer from Lab 05 and a control loop from Lab 06. Every
one of those labs made a security decision - a group-referenced rule here, a role instead of a key
there, a private subnet, a cutover - and every one of them made it in isolation, at the moment it was
needed, without ever standing back and asking the two questions a security review actually asks:

```text
WHO can call WHAT?              the identity axis      IAM roles and policies
WHAT can reach WHAT?            the network axis       security groups and routing
```

This laboratory asks both, about the system you already have, and then fixes what the answers turn up.

The single most important idea to leave with is that **those two axes are independent, and a request
needs permission on both**. An IAM policy that allows `s3:GetObject` does nothing for a task whose
security group will not let a packet out. A security group that permits a connection does nothing for
a caller whose role does not allow the API action. Students who hold the two apart write precise
controls. Students who conflate them spend an afternoon adding permissions to fix a network problem,
which never works and occasionally makes things much worse.

The second idea shapes every proof in this lab and is worth stating before you start:

```text
Floci does not enforce IAM policies.
Floci does not enforce security groups.

So NOTHING in this laboratory can be proven by watching a command fail.
Everything in it is proven by READING CONFIGURATION and reasoning about it.
```

That is not a compromise forced on us by the emulator. It is how security review is actually done on
real systems, because you cannot test your way to a claim like "nothing else in this account can open
a connection to the transcripts database" - there are too many things that are not that connection.
You assert it from configuration, and then you write a script that keeps asserting it after you have
gone home. Section 9 is that script.

**Time:** roughly 4 hours, including the exercises.

**Where this sits in the course**

```text
Lab 01   IAM ................. roles, policies, instance profile        Practical 0
Lab 02   VPC ................. subnets, NAT, route tables, groups       Practical 1
Lab 03   EC2 ................. usms-web-01 and usms-db-01               Practical 1
Lab 04   ECS + Fargate ....... the cluster, the blueprint, the service  Practical 2
Lab 05   ECS + ALB ........... the front door                          Practical 2
Lab 06   Service Auto Scaling  the control loop                        Practical 3
Lab 07   EKS .................. the same workload, a different control plane   Practical 4
Lab 08   EKS Scaling ......... HPA, node group scaling, exposure       Practical 4
Lab 09   SECURITY ........... THIS LAB - a review of all of the above   Practical 5 / descriptor 8
Lab 10   Lambda .............. creates the bucket three policies already name, and triggers
                                functions from it
```

!!! info "This lab does not require the transcripts bucket to exist yet"
    Nothing in this laboratory requires `usms-student-data` to exist. It is Lab 10 that creates the
    bucket, so exactly one step here - Step 6 - reads the result of
    `aws s3api head-bucket --bucket usms-student-data`, and expects it to fail: that is the correct
    and only outcome at this point in the course, not a branch to accommodate.

    A bucket not existing does not make the policies that name it unreviewable, and Step 6 says why.

!!! warning "This lab changes rules that earlier labs wrote, and it does so deliberately"
    Steps 13 to 16 replace the allow-all **egress** rule on four security groups, and Step 16 changes
    the source of `usms-app-sg`'s SSH rule.

    None of those changes breaks a check in `verify-lab-02.sh`, `verify-lab-03.sh`,
    `verify-lab-04.sh` or `verify-lab-05.sh`, and Step 2 records a baseline so that you can prove
    it. That is not luck: it is because every one of those scripts asserts **ingress** and none of
    them ever asserted the egress rule nobody wrote.

    Which is itself the finding. A control that no verification script mentions is a control nobody
    has ever checked, and there is one on every security group in this account.

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. State the two independent axes of access control in AWS, and explain why a request needs a
   decision on both before anything happens.
2. Describe the order in which AWS evaluates an API request - explicit deny, organisation policy,
   permissions boundary, identity policy, resource policy - and say which of those this course has
   and which it does not.
3. Read a trust policy and an identity policy and say precisely what each one decides, without
   confusing the two.
4. Explain the confused deputy problem for a service role, and write the `aws:SourceAccount` and
   `aws:SourceArn` conditions that close it.
5. Explain why `iam:PassRole` is the single most important action in an IAM policy to scope, and
   scope one correctly with an `iam:PassedToService` condition.
6. Create a **permissions boundary**, attach it to a role, and explain why a boundary is not a policy
   that grants anything.
7. Use a **session policy** to scope down an assumed role for one session, and compute the effective
   permissions of a session as an intersection.
8. Rotate a long-lived access key with no window in which nothing works, and explain why the
   procedure has four steps rather than two.
9. Require IMDSv2 on an EC2 instance and explain the class of attack that a token requirement and a
   hop limit of one each prevent.
10. Audit every security group in a VPC for the four findings that matter, using a script that
    computes its verdicts from rules rather than from names or tags.
11. Replace the default allow-all egress rule with a written one, and explain what egress control
    protects that ingress control cannot.
12. Write a security group **egress** rule whose destination is another security group, and one whose
    destination is a managed prefix list.
13. Prove a negative - that a resource is unreachable - from more than one independent control, and
    say which of those controls would still hold if the others were removed.
14. Explain why a policy that cannot be tested on this emulator can still be reviewed with confidence,
    and describe the class of mistake that review catches and the class it does not.
15. Prove that every control this lab configured survives a restart of the emulator, deriving every
    identifier from the API.

---

## 3. Prerequisites

- **Labs 01, 02, 03, 04, 05 and 06 complete**, with `verify-lab-02.sh`, `verify-lab-03.sh`,
  `verify-lab-05.sh` and `verify-lab-06.sh` each reporting `FAIL=0` **before you start**. Run them
  now, not at the end.
- **`verify-lab-04.sh` reporting either `FAIL=0` or exactly the one documented failure** on the
  `usms-app-sg` source check. Lab 05 Step 13 caused that failure deliberately and Lab 05's
  Exercise 2 repairs it; either state is acceptable here, and any *other* failure is not.
- **`outputs/usms-app-key.pem` still present and `chmod 600`**, and the `usms-dev` AWS CLI profile
  still working. Step 10 rotates the key behind that profile, and it cannot rotate a key it cannot
  find. Check with `aws sts get-caller-identity --profile usms-dev`.
- **Errata 01 applied.** If `echo "$AWS_PROFILE"` in a brand-new terminal prints nothing, stop and
  apply Errata 01 first - every command in this lab would otherwise fail with a credentials error
  that names the wrong cause.
- Floci running under Docker Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq` and `python3` available. `python3` does every timestamp and every JSON comparison in this lab,
  because GNU `date` and BSD `date` disagree about every flag that matters.

Check all of that in one go:

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

**What to look for:** three tools found, `PASS=16  FAIL=0` from the storage check, an ARN ending
`user/usms-dev-01` from the `usms-dev` profile, and permissions of `-rw-------` on the private key. A
failure in the storage check's `shell and profile` block is the real problem and everything below it
is a consequence - fix that block before starting.

If the `usms-dev` profile does not answer, Step 10 cannot run as written. Its **Verify** block tells
you what to do instead, and the rest of the lab is unaffected.

!!! tip "One habit to bring with you, because this lab depends on it more than any other"
    Every claim in this document is a claim about a **document** - a policy, a trust policy, a rule.
    Read the documents. Do not infer a policy's contents from its name, and do not infer a security
    group's effect from its description.

    Lab 02 Step 15 named a group `usms-db-sg` and gave it a rule sourced from `usms-app-sg`. Both of
    those are true today. Neither is true because of the name.

---

## 4. Connection to Previous Labs

### 4.1 Current Environment

```text
Created in previous labs:
- Lab 01: Floci under Compose, hybrid storage, persistence proven
- Lab 01: groups usms-admins / usms-developers / usms-auditors; three users
- Lab 01: roles  usms-ec2-app-role, usms-lambda-exec-role, usms-developer-role
- Lab 01: policies USMSDeveloperBase (v2), USMSStudentDataReadWrite, USMSAssumeAppRoles,
                   USMSLambdaBasic, USMSSelfManageCredentials (inline on usms-dev-01)
- Lab 01: instance profile usms-ec2-app-profile
- Lab 01: an access key for usms-dev-01, in outputs/, git-ignored, chmod 600
- Lab 01: configs/course.env, configs/lab-01.env
- Lab 02: usms-vpc 10.0.0.0/16, DNS support and hostnames enabled
- Lab 02: usms-public-subnet-a / -b, usms-private-subnet-a / -b
- Lab 02: usms-igw, usms-nat (+ Elastic IP), usms-public-rt, usms-private-rt
- Lab 02: usms-app-sg, usms-db-sg, usms-private-nacl, usms-s3-endpoint
- Lab 02: configs/lab-02.env, scripts/utilities/verify-lab-02.sh
- Lab 03: usms-web-01 (public subnet a, usms-app-sg, usms-ec2-app-profile, usms-web-eip)
- Lab 03: usms-db-01 (private subnet a, usms-db-sg, no public address, no profile)
- Lab 03: usms-web-data-vol, usms-web-golden, usms-app-key
- Lab 03: configs/lab-03.env, scripts/utilities/verify-lab-03.sh
- Lab 04: usms-ecs-cluster, /usms/ecs/enrolment, usms-enrolment:1 and :2
- Lab 04: usms-ecs-exec-role (+ USMSECSTaskExecution), usms-ecs-task-role (+ Lab 01's S3 policy)
- Lab 04: usms-enrolment-sg, usms-enrolment-svc, desired 2, both private subnets
- Lab 04: configs/lab-04.env, scripts/utilities/verify-lab-04.sh
- Lab 05: usms-alb-sg, usms-enrolment-alb, usms-enrolment-tg, the HTTP:80 listener
- Lab 05: usms-enrolment-sg cut over to usms-alb-sg only
- Lab 05: configs/lab-05.env, scripts/utilities/verify-lab-05.sh
- Lab 06: a scalable target, three scaling policies, two scheduled actions, one alarm
- Lab 06: configs/lab-06.env, scripts/utilities/verify-lab-06.sh
- Lab 07: usms-eks-cluster, usms-eks-cluster-sg, usms-eks-nodes, usms-eks-node-role
- Lab 07: namespace usms - gateway, enrolment, results; ServiceAccount usms-enrolment-sa (no IRSA on this build)
- Lab 07: configs/lab-07.env, scripts/utilities/verify-lab-07.sh
- Lab 08: usms-enrolment-hpa, node group scaling, ClusterIP/NodePort/LoadBalancer/Ingress exposure
- Lab 08: configs/lab-08.env, scripts/utilities/verify-lab-08.sh

This lab's own audit is scoped to the EC2/ECS-side IAM and security-group estate - the roles and
groups built in Labs 01 through 06. It does not extend the review to `usms-eks-node-role` or the
ServiceAccount from Labs 07-08, since the emulator does not support IRSA and there is no separate
identity to review there yet. That gap is real and is not closed by this lab; a later audit would
need to pick it up.

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

### 4.2 What this lab genuinely reuses

Not mentions - uses.

| From | Used here how |
| --- | --- |
| Lab 01 `USMSStudentDataReadWrite` | Step 6 reads its document and Step 7 derives the read-only policy from it, action by action |
| Lab 01 `usms-ec2-app-role`, `usms-lambda-exec-role`, `usms-developer-role` | Step 4 inventories all three; Step 8's scoped `iam:PassRole` names two of them by ARN |
| Lab 01 `usms-dev-01` and its access key | Step 10 rotates it, using the `usms-dev` profile Lab 01 created |
| Lab 01 `usms-developer-role` and its one-hour session | Step 9 assumes it **with a session policy** and computes the intersection |
| Lab 02 `usms-app-sg`, `usms-db-sg` | Steps 12, 15 and 16 audit and harden both |
| Lab 02 `usms-s3-endpoint` | Step 14's egress rule names its **prefix list** as a destination - the first time in this course that the endpoint is used as anything but a route |
| Lab 02 `usms-private-nacl` | Step 17 counts it as one of the four independent controls on the data tier |
| Lab 02 Exercise 2 `usms-bastion-sg` | Step 16 reuses it if you did that exercise, and creates it if you did not |
| Lab 03 `usms-web-01` | Step 11 requires IMDSv2 on it; Step 17 puts it in the reachability matrix |
| Lab 03 `usms-ec2-app-profile` | Step 8 explains why passing it was a privilege-escalation opportunity, and scopes it |
| Lab 04 `usms-ecs-task-role` | Step 7 rewrites its trust policy without touching its permissions |
| Lab 04 `usms-enrolment-sg` | Step 13 writes its egress rules |
| Lab 05 `usms-alb-sg` | Step 14 writes its egress rule, whose destination is another security group |
| Lab 06 the scalable target | Step 17 explains why a scaling policy changes the reachability matrix without changing any rule in it |
| `configs/course.env` names | `$COURSE_ROOT`, `$AWS_REGION_COURSE`, `$ACCOUNT_ID`, `$PROJECT` used, never redeclared |

### 4.3 The sentence that makes this lab worth doing

Lab 02 Step 14 said this, in passing, and nothing in the four laboratories since has come back to it:

> Every security group is created with one rule you did not ask for: **allow all outbound**. It is not
> shown by `authorize-security-group-ingress` and it is easy to forget it exists.

There are now five security groups in `usms-vpc` and every one of them can open a connection to any
address on the internet, on any port, and none of you wrote that rule.

That matters for one specific reason, and it is the reason egress control exists at all. **Ingress
rules protect you from an attacker who has not got in yet. Egress rules limit what an attacker can do
once they have.** Data leaves through egress. Command-and-control traffic leaves through egress. A
compromised container mining cryptocurrency talks to a pool through egress. Every one of those is
invisible to an ingress rule, however carefully written.

Say that out loud before you continue. It is Review Question 3.

### 4.4 What changes, and what deliberately does not

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

Read the last row against the second block. This lab changes a great deal about what the system is
*allowed* to do and nothing whatsoever about what it *does*. That is the shape of a good security
change, and it is the reason Step 18 can prove the whole thing by re-running four verification scripts
written before this lab existed.

---

## 5. What We Are Building

Not a new tier. A review, and the repairs it turns up, on both axes at once.

Five decisions justify the shape of what follows, and each is defensible in one sentence.

**We audit before we change anything.** Steps 4, 5 and 12 produce three inventories and two audit
scripts, and not one of them modifies a resource. A change made before the audit is a change you
cannot justify afterwards, and a finding you fixed before you recorded it is a finding your report
will not contain.

**We fix identity first and network second.** They are independent, so the order is arbitrary in
principle - but an identity mistake is silent and a network mistake is loud, so doing the silent one
while you are fresh is the better use of four hours.

**We add rather than replace, wherever a later lab depends on the thing.** `usms-ecs-task-role` keeps
`USMSStudentDataReadWrite`, because Lab 10 is built around the moment that policy resolves. The
read-only policy is a *new* policy on a *new* role, which is additive and which gives Lab 10 a second
story to tell.

**Every egress rule we write is narrower than allow-all and wider than it strictly has to be, and we
say so.** A Fargate task pulling a container image needs to reach a registry whose addresses are not
ours to know. Pretending otherwise produces a rule that is precise and wrong. Step 13 writes the
honest rule and states plainly what a real account would do instead.

**Every claim is asserted from configuration and then written into a script.** Section 9 is not a
formality; it is the deliverable. A security review whose findings are in a document nobody re-reads
has a half-life of about three weeks.

### 5.1 The security baseline this lab establishes

```text
IDENTITY
  usms-ecs-task-role       trust: ecs-tasks.amazonaws.com
                                  + aws:SourceAccount 000000000000
                                  + aws:SourceArn arn:aws:ecs:us-east-1:000000000000:*
  usms-transcripts-reader-role  same scoped trust, USMSStudentDataReadOnly
  usms-deploy-role         trust: usms-admin-01
                           USMSDeployBase, iam:PassRole scoped to 3 role ARNs
                                           + iam:PassedToService condition
                           permissions boundary: USMSPermissionsBoundary
  usms-dev-01              exactly one access key, created today
  usms-web-01              IMDSv2 required, hop limit 1

NETWORK - ingress unchanged, egress written
  usms-alb-sg         in  tcp/80  from 0.0.0.0/0        out tcp/80  to usms-enrolment-sg
  usms-enrolment-sg   in  tcp/80  from usms-alb-sg      out tcp/443 to pl-<s3>, 0.0.0.0/0
  usms-app-sg         in  tcp/80,443 from 0.0.0.0/0     out (Exercise 1)
                      in  tcp/22  from usms-bastion-sg
  usms-db-sg          in  tcp/5432 from usms-app-sg     out tcp/443 to 0.0.0.0/0
  usms-bastion-sg     in  tcp/22  from one /32          out tcp/22  to 10.0.0.0/16

PROVEN NEGATIVES
  usms-db-01           unreachable from the internet by FOUR independent controls
  enrolment tasks      reachable ONLY from usms-alb-sg, by ONE control, and that is a finding
```

Every one of those is a decision with a reason, and Exercise 4 asks you to defend a different set for
a system with an external auditor attached to it.

---

## 6. Architecture

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

## 7. Directory Structure

This lab adds the following. It restructures nothing and needs no new top-level folder.

```text
aws-floci-course/
├── labs/
│   └── lab-09-security/
│       ├── README.md                                  # this document
│       └── exercises.md                               # Section 13
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
│   │   └── verify-lab-09.sh                           # NEW - Section 9
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

## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

    Every path below (`configs/...`, `policies/...`, `scripts/...`) is relative to that directory. If
    a command reports `No such file or directory`, check `pwd` first.

    One habit, restated because this lab writes more JSON documents than any since Lab 01: **capture
    every identifier with `$(...)`, `--query` and `--output text`, and never type one by hand.** Shell
    variables die with the terminal, which is why Step 19 writes them all to `configs/lab-09.env`.

### Step 1 - Resume the environment and load seven env files

**Purpose**

Bring Floci up and load everything the previous six labs recorded. This lab reads values from five of
those files, and three of them - the account ID, the enrolment security group and the S3 endpoint -
are used to build documents that would be silently wrong if the variable were empty.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

Seven env files is the standard opening from here on. They are additive and independent: sourcing them
in any order gives the same result, because no two of them define the same variable. That property is
not an accident - it is the reason every lab has used the `USMS_<THING>` convention and has looked
values up by tag rather than reusing a shell variable.

`printf` with more arguments than format specifiers reuses the format string until the arguments run
out, which is why one `printf` prints seventeen lines.

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

Seventeen non-empty values. Four failures matter more than the rest:

- **`account` empty** stops Steps 7, 8 and 9 dead. Every document those steps write embeds the account
  ID, and an empty one produces a malformed ARN that IAM rejects with a message about the ARN's
  format rather than about your variable.
- **`enrolment sg` or `alb sg` empty** means `configs/lab-04.env` or `configs/lab-05.env` is
  incomplete. Re-run Lab 04 Step 20 or Lab 05 Step 18.
- **`s3 endpoint` empty** means Lab 02 Step 21 did not complete. Step 14 has a documented fallback for
  that case, but you should know now rather than then.
- **`bucket name (policy)` empty** means `USMS_BUCKET_NAME` was never recorded. Step 6 re-derives it
  from Lab 01's policy document, which is the more honest source anyway, so this one is survivable.

---

### Step 2 - Record the security baseline before you change anything

**Purpose**

This lab modifies rules that five earlier laboratories wrote. Before it does, capture what every one
of their verification scripts says today, so that at Step 18 you can prove - with a `diff`, not with a
memory - that none of your changes broke anything they assert.

This is the same discipline as Lab 05 Step 2, applied to five scripts instead of three, and for a
sharper reason: a security change that quietly breaks a functional check is the single easiest way to
have your work reverted by somebody who does not understand it.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
{
  echo "== baseline recorded $(python3 -c 'import datetime;print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))') =="
  for s in 02 03 04 05 06; do
    printf '%-10s ' "lab-$s"
    ./scripts/utilities/verify-lab-$s.sh 2>/dev/null | tail -1
  done
} | tee outputs/lab-09-pre-verify.txt
```

**What the command does**

Runs all five verification scripts and keeps only each one's summary line. The whole block is wrapped
in `{ ... } | tee` so that one redirect captures the loop's output as well as the heading - a `tee`
after a single command would have captured only that command.

`python3` produces the timestamp rather than `date`, for the reason the Prerequisites gave: `date -u
+%Y-%m-%dT%H:%M:%SZ` happens to be portable, but the moment you want any arithmetic on it the GNU and
BSD flags diverge, and using one tool for every timestamp in the course is cheaper than remembering
which invocations are safe.

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

`FAIL=0` from Labs 02, 03, 05 and 06, and from Lab 04 either `FAIL=0` or exactly the one documented
failure on the `usms-app-sg` source check.

Confirm that the one allowed failure is the one you think it is:

```bash
./scripts/utilities/verify-lab-04.sh 2>/dev/null | grep FAIL || echo "no failures in 04"
```

**What to look for:** either the single line
`FAIL usms-enrolment-sg is sourced from usms-app-sg (not a CIDR)`, or `no failures in 04`. Any other
failing line is a pre-existing problem, and this lab will make it harder to find rather than easier.
Fix it first.

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

**Purpose**

Find out now which parts of IAM's evaluation surface and EC2's rule surface your build implements,
rather than discovering it at Step 13 with three groups half-hardened. This is the same principle as
Lab 04 Step 3, Lab 05 Step 3 and Lab 06 Step 3: **name the limitation before it costs you an hour.**

This lab's probe matters more than most, because the two things it most wants to use - policy
simulation and account-wide authorisation detail - are the two least reliably emulated calls in IAM.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`probe` runs a harmless read, or generates a request skeleton, and reports whether the CLI got an
answer at all. A skeleton probe answers "does this CLI version know the operation", which is a
different and weaker question than "does this build implement it" - so where a skeleton is the probe,
the step that uses the operation also has a fallback.

Read the result as "the service responded to me", not "the call succeeded".

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

Work out which path you are on and write it at the top of `notes/lab-09-notes.md`, because your lab
report and Section 14 both require you to state it.

| Path | If | What changes |
| --- | --- | --- |
| **A - full** | Everything above answers, including `simulate-principal-policy` | Do every step as written, and Step 9 gets a simulated answer as well as a read one |
| **B - management only** | Roles, policies and rules can be created, read and changed, but simulation and account-authorisation details are absent | **The expected path.** Every step still works. Every proof in this lab is a proof about a document, and the documents are all there |
| **C - no IAM writes** | `update-assume-role-policy` or `create-role` fails outright | Do Steps 4, 5, 12 to 18 and Exercises 3 and 4, which need no IAM writes, and record the identity half as conceptual. Tell your instructor |

!!! note "Floci Limitation - nothing in this laboratory is enforced"
    Floci accepts any non-empty credentials and, by default, does not authorise requests against your
    IAM policies. It does not evaluate security groups against traffic either - it does not carry
    traffic. A policy of `{"Effect":"Allow","Action":"*","Resource":"*"}` behaves identically to a
    carefully scoped one, and a security group admitting everything behaves identically to one
    admitting nothing.

    Real AWS evaluates every IAM policy on every API call and every security group on every packet.

    Take this away, and it is the whole methodology of this lab: **judge your controls by reading
    them, not by whether a command succeeded.** Do not build an exercise, or a habit, that depends on
    seeing `AccessDenied`. Every step below asserts on a document or on a rule, because a document is
    a thing you can actually observe here - and, as Section 12.3 argues, reading is what you would
    have to do on a real account anyway for any claim about what *cannot* happen.

---

### Interlude - the two axes, and the order AWS decides in

Before Step 4 reads anything, you need a model of what it is reading.

**Two independent decisions.** Every interaction in AWS is one of two kinds, and they are policed by
different machinery that does not consult each other:

| | An API call | A packet |
| --- | --- | --- |
| Example | `s3:PutObject`, `ecs:UpdateService`, `ec2:RunInstances` | TCP 5432 from `10.0.1.87` to `10.0.3.42` |
| Decided by | IAM: identity policies, resource policies, boundaries, session policies | Routing, security groups, network ACLs |
| Where the decision happens | The service's API endpoint | The elastic network interface and the subnet |
| Failure looks like | `AccessDenied`, with a message naming an action | A timeout, or a connection refused, with no message at all |
| This course's examples | `usms-ec2-app-role` writing a transcript | `usms-web-01` reaching `usms-db-01` on 5432 |

The second row of that table is the practical one. **An access-control failure that gives you an error
message is an IAM problem. One that hangs is a network problem.** That single heuristic resolves most
of the confusion, and it is worth more than any diagram.

**The order IAM decides in.** For an API call, AWS evaluates in a fixed order, and the first two are
the ones people forget:

```text
1. Is there an explicit DENY anywhere?             -> DENY. Nothing overrides this. Ever.
2. Does a Service Control Policy allow it?         -> if not, DENY   (AWS Organizations)
3. Does the PERMISSIONS BOUNDARY allow it?         -> if not, DENY   (Step 8)
4. Does a SESSION POLICY allow it?                 -> if not, DENY   (Step 9)
5. Does an IDENTITY policy allow it?               -> if yes, ALLOW
6. Does a RESOURCE policy allow it?                -> if yes, ALLOW  (Exercise 5's bucket policy)
7. Otherwise                                        -> DENY  (the implicit default)
```

Four things follow, and each of them is a step in this lab:

- **An explicit `Deny` is absolute.** Lab 01 put one in `USMSDeveloperBase` against IAM escalation.
  Nothing you attach to that role can undo it, which is exactly why it is there.
- **Steps 3 and 4 are ceilings, not grants.** A permissions boundary and a session policy can only
  take permissions away. Attaching a boundary that allows `s3:*` to a role with no S3 policy grants
  the role nothing at all. This is the single most misunderstood thing in IAM and it is Step 8.
- **The default is deny.** Every `Allow` you write is an exception to it, which is why a policy with
  no statements is a perfectly valid and completely useless policy.
- **Step 2 is the only one this course does not have.** Service Control Policies belong to AWS
  Organizations, which Floci does not model and a single account does not have. Section 12 labels it
  `Conceptual / Real AWS`, and Exercise 4 asks what you would put in one.

**One distinction to fix now, because Steps 6 and 7 depend on it.** A role has two completely
different policy documents attached to it, and students conflate them constantly:

| | Trust policy | Identity (permissions) policy |
| --- | --- | --- |
| Also called | Assume-role policy document | Attached policy, managed or inline |
| Answers | **Who may become this role?** | **What may this role do?** |
| Attached with | `create-role --assume-role-policy-document`, `update-assume-role-policy` | `attach-role-policy`, `put-role-policy` |
| Read with | `get-role --query 'Role.AssumeRolePolicyDocument'` | `list-attached-role-policies`, then `get-policy-version` |
| Has a `Principal` | **Yes, always.** That is what it is for | No. The principal is the role itself |
| How many | Exactly one | Up to 10 managed, plus inline |

A role with a permissive trust policy and no permissions is harmless. A role with excellent
permissions and a trust policy naming `"AWS": "*"` is a catastrophe that no permissions policy can
mitigate. **The trust policy is the more dangerous of the two**, and it is the one nobody reads.

---

### Step 4 - Inventory every identity in the account

**Purpose**

You cannot review what you have not listed. This step produces the complete identity inventory - every
role, what trusts it, and what it can do - as a single JSON file that Step 5's audit script consumes
and that your lab report quotes.

Nothing here modifies anything.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the human-readable pass**

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

**What the command does**

`--scope Local` restricts `list-policies` to policies **you** created. Without it, the call returns
several hundred AWS managed policies and buries the six that are yours. On a real account this flag is
the difference between a usable audit and a wall of text.

`AttachmentCount` is the column to read. A customer managed policy with an attachment count of zero is
either a mistake, a leftover, or - as `USMSPermissionsBoundary` will be after Step 8 - a policy
deliberately used as a boundary and never attached. Knowing which is which is exactly the sort of
thing an inventory is for.

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

**What to look for:** `USMSStudentDataReadWrite` with an attachment count of **2**. That is Lab 01's
`usms-ec2-app-role` and Lab 04's `usms-ecs-task-role`, and it is the finding Step 6 pulls on. One
policy, two roles, one of which does not need half of it.

**Command - part 2, the machine-readable inventory**

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

**What the command does**

A short Python program rather than a shell loop, and the reason is worth stating because it recurs:
the data is **nested and irregular**. Each role has a trust policy that is an object, a list of
attached policies each of which needs two more API calls to resolve to a document, and a list of
inline policies with a different shape. Shell is a poor language for that and JSON is a good one.

The heredoc is `<< 'PY'`, **quoted**, because the program contains `$` characters inside f-strings and
`{}` braces everywhere, none of which the shell must touch. Getting this wrong produces a Python file
full of empty strings and a `SyntaxError` that names a line the program does not contain.

`aws(...)` returns `None` rather than raising when a call fails, so a build that does not implement
`list-role-policies` produces an inventory with an empty `inlinePolicies` list instead of no inventory
at all. **An audit tool that dies on the first unsupported call is an audit tool nobody runs twice.**

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

**What to look for:** every `boundary` reading `-`. **Not one role in this account has a permissions
boundary**, which is finding number one and is what Step 8 fixes. That column existing and being empty
across the board is more informative than any single role's policies.

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

Hint: `python3 -c "import json;d=json.load(open('outputs/lab-09-identity-inventory.json'));..."` will
pull them out, or `jq '.[] | {role, trustPolicy}'` if you prefer. The interesting difference is not
the syntax.

---

### Step 5 - Build the IAM audit script

**Purpose**

Turn the inventory into findings. This script encodes four checks that catch the four IAM mistakes
that actually cause incidents, and it is the artefact this lab is most likely to leave you using
again.

It changes nothing. Read-only, always.

**Run from**

```text
aws-floci-course/
```

**Concept first - the four findings, and why these four**

| Finding | Why it matters |
| --- | --- |
| `Action: "*"` or a service wildcard like `s3:*` | The blast radius of a compromised principal is the union of everything it can do. A wildcard makes that union unbounded and unreviewable |
| `Resource: "*"` on a mutating action | Scoping actions without scoping resources means the right verbs on the wrong nouns. `s3:DeleteObject` on `*` is not a smaller problem than `s3:*` on one bucket |
| `iam:PassRole` without a resource scope | **The escalation.** A principal that may pass any role to any service can pass an admin role to a service it controls and inherit it. This is the single most exploited IAM misconfiguration there is |
| A trust policy with no `Condition` on a **service** principal | The confused deputy. Step 7 explains it in full |

Three of those four are about the *shape* of a document rather than its contents, which is why they
can be checked mechanically. The fourth - is this grant appropriate to this workload - cannot be, and
that is why Exercise 4 is a piece of writing rather than a script.

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

**What the command does**

The outer heredoc is `<< 'EOF'`, quoted, because the file contains `$1`, `${BASH_SOURCE[0]}` and an
entire Python program full of braces, none of which your shell must expand. The **inner** heredoc,
`<< 'PY'`, is quoted for the same reason and is nested inside the outer one - which is why the
Markdown fence around this whole block uses **four** backticks rather than three.

Three details in the Python are worth reading rather than skimming:

**`as_list`** exists because IAM policy documents are irregular by design: `"Action": "s3:GetObject"`
and `"Action": ["s3:GetObject"]` are both valid and mean the same thing, and the same is true of
`Resource`, `Principal.Service` and `Statement` itself. Every tool that reads IAM policies has a
function like this, and every tool that does not has a bug.

**`is_mutating`** is a heuristic, not a rule, and the script says so. It matches an action's verb
against a list of prefixes, so `s3:PutObject` is mutating and `s3:GetObject` is not. It will
occasionally be wrong - `ec2:RunInstances` is caught by `Run`, but `sts:AssumeRole` is not caught by
anything and is arguably the most consequential action in AWS. A heuristic that is right most of the
time and honest about being a heuristic is worth having; one that pretends to be complete is not.

**The exit code is 1 only for HIGH findings.** A tool that exits non-zero for every imperfection is a
tool that gets `|| true` appended to it in somebody's pipeline within a week.

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

Four HIGH findings, all of them the same shape, on four different roles. That is the point of running
an audit rather than reading five documents: **a systematic mistake looks like a systematic mistake**,
and one that appears on every role in the account was made by a convention rather than by a person
having a bad afternoon.

Steps 7 and 8 fix two of the four and Exercise 2 asks you about the others. The exit code is `1`;
check it:

```bash
./scripts/utilities/usms-iam-audit.sh >/dev/null; echo "exit code: $?"
```

**What to look for:** `exit code: 1`, because there are HIGH findings. When you re-run this at Step 18
the count will be lower and the code will still be 1, because this lab does not fix all four - and a
report that claims zero findings after a four-hour review is a report nobody believes.

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

**Purpose**

Lab 01 wrote `USMSStudentDataReadWrite` for a bucket that did not exist. Lab 03 attached it to an EC2
instance. Lab 04 attached the same policy, unchanged, to a Fargate task role. Nobody has ever asked
whether both of those workloads need all of it.

This step asks.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, read the policy that two roles share**

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

**What the command does**

`get-policy` then `get-policy-version` is the two-step Lab 02 Step 3 introduced, and the reason is the
same: a managed policy is versioned and only one version is in force. Reading a policy without asking
which version is default is how you review a document that is not the one being enforced.

`list-entities-for-policy` is new here, and it is the reverse of `list-attached-role-policies`: given a
policy, who has it. On a real account this is the first call in any "what breaks if I change this"
conversation, and the answer is frequently larger than expected.

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

**What to look for**, and this is the finding:

- **Two statements, two different ARNs.** `s3:ListBucket` is a *bucket* operation and takes the bucket
  ARN; `s3:GetObject` and `s3:PutObject` are *object* operations and take the bucket ARN with `/*`.
  Putting them in one statement with one resource is the most common S3 policy error there is, and
  Lab 01 avoided it deliberately.
- **`s3:PutObject` is granted to both roles.** The enrolment API reads a student's transcript to
  display it. It does not write transcripts - the registry does that, from a different workload
  entirely. One of these two roles is carrying a verb it does not use.
- **The explicit `Deny` on `s3:DeleteBucket`.** Remember from the interlude that this outranks
  everything. No policy anyone attaches to either role, now or ever, can let it delete that bucket.

**Command - part 2, does the bucket exist yet?**

```bash
aws s3api head-bucket --bucket "${USMS_BUCKET_NAME:-usms-student-data}" 2>&1 | head -3
echo "head-bucket exit code: ${PIPESTATUS[0]}"
```

**What to look for:** a non-zero exit code (`404` / `NoSuchBucket`). Lab 10 is the lab that creates
this bucket, and it has not run yet, so that is the correct and expected result here - not a sign that
anything is missing.

The two policies above currently grant access to nothing, because there is nothing at that ARN. That
does not make them unreviewable. **An IAM policy is a statement about ARNs, not a reference to
objects** - you can review it, and you should, before the resource appears. When Lab 10 runs
`create-bucket`, both policies resolve at once, and Exercise 5's bucket policy draft stops being a
document about a hypothetical bucket and becomes one the (still unwritten) S3 configuration lab can
apply.

Record that the bucket did not exist yet at the top of `notes/lab-09-notes.md`. It is the second thing
Section 14 asks for.

!!! note "Floci Limitation - you cannot demonstrate the difference between these two policies"
    On real AWS you could attach the read-only policy to a role, call `s3:PutObject`, and watch it
    fail with `AccessDenied`. That is the natural way to show that a scoped policy is scoped.

    Floci does not authorise requests against IAM policies, so both roles will succeed at everything
    regardless of what you attach, and a demonstration built on seeing a denial would be a
    demonstration of nothing.

    Take this away: **the proof that a policy is correct is that you read it and it says what you
    meant.** That is not a weaker proof than testing - for a claim about what a principal *cannot*
    do, it is the only proof there is, because no finite number of successful denials proves the
    absence of a path.

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

Hint: `s3:ListBucket` is needed by both, and it is worth asking yourself why a reader needs to list a
bucket at all. The answer is about what S3 returns when you `GetObject` a key that does not exist, and
it depends on whether the caller has `ListBucket`.

---

### Step 7 - Create the read-only policy and the role that carries it

**Purpose**

Split the transcripts policy along the line Step 6 found. This creates a second, narrower policy and a
new role for the read path - additively, without touching either role that already carries the
read-write one, because Lab 10 is built around the moment `USMSStudentDataReadWrite` resolves for both
of them at once.

**Run from**

```text
aws-floci-course/
```

**Concept first - the confused deputy, in one paragraph**

A trust policy that names a **service** principal says "any request from this AWS service may assume
this role". Not "any request from *my* use of this service" - any request from the service, on behalf
of anyone. If an attacker can persuade that service, in **their** account, to act on **your** role's
behalf, they inherit your permissions. The service is the deputy, and it has been confused about whose
instruction it is following.

The fix is a condition that pins the request to your account and your resources:

```text
"Condition": {
  "StringEquals": { "aws:SourceAccount": "000000000000" },
  "ArnLike":      { "aws:SourceArn": "arn:aws:ecs:us-east-1:000000000000:*" }
}
```

`aws:SourceAccount` is the account that owns the resource making the call. `aws:SourceArn` is that
resource. Together they say: only ECS, only in my account, only for my ECS resources.

Two caveats worth knowing and both of them examinable:

- **Not every service supports these keys.** `ec2.amazonaws.com` does not populate `aws:SourceArn` for
  instance profiles, so `usms-ec2-app-role` cannot be fixed this way. That finding stays open in the
  audit, deliberately, and Exercise 2 asks what you would do about it instead.
- **A condition on a key the service does not send is a condition that denies everything.** If you add
  `aws:SourceArn` to a trust policy for a service that never sends it, the condition evaluates false
  and nothing can assume the role. That is a self-inflicted outage, and it is why you check the
  documentation for the specific service rather than applying the pattern everywhere.

**Command - part 1, the read-only policy document**

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

**What the command does**

`<< 'EOF'`, **quoted**, because this document contains no shell variable and must reach disk exactly
as written. The bucket name is a literal here on purpose: it is the same literal Lab 01 wrote, and
having the two documents contain the identical string is what lets Exercise 5 compare them
mechanically.

The `grep -c '\$'` must print **`0`**. That check has now appeared in four laboratories in five
different contexts, and it costs one line.

The third statement is the interesting one and it is not strictly necessary. The first two statements
grant `ListBucket` and `GetObject`, and everything not granted is denied by default - so the explicit
`Deny` adds nothing today. It adds something tomorrow: **if anyone ever attaches a broader policy to a
role that also carries this one, the explicit `Deny` still wins**, because of rule 1 in the interlude.
That is what an explicit deny is for. It is not belt and braces; it is a statement that survives
somebody else's future mistake.

State that reasoning in your report. A reviewer who cannot explain why a redundant `Deny` is not
redundant will delete it.

**Command - part 2, create the policy**

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

**Command - part 3, the scoped trust policy**

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

!!! warning "Heredoc quoting - and the case where the usual rule gives the wrong answer"
    This one is `<< EOF`, **unquoted**, because `${USMS_ACCOUNT_ID}` and `${AWS_REGION_COURSE}` must
    become real values as the file is written. Lab 02 Step 15 did the same thing for
    `policies/usms-db-sg-ingress.json`.

    That contradicts the shorthand people carry away from Lab 01 - "policy documents use `<< 'EOF'`" -
    and the shorthand is what is wrong, not this step. **The rule is not about the kind of file. The
    rule is always the same question: do I want this expanded now, or later?** Lab 01's
    `USMSSelfManageCredentials` needed `<< 'EOF'` because it contains `${aws:username}`, which is an
    *IAM* variable that IAM expands at evaluation time and the shell must never touch. This document
    contains *shell* variables that must be gone by the time IAM sees it.

    A document containing **both** kinds is where this gets genuinely awkward, and it happens. In an
    unquoted heredoc, escape the IAM variable with a backslash so the shell leaves it alone:

    ```text
    "Resource": "arn:aws:iam::${USMS_ACCOUNT_ID}:user/\${aws:username}"
    ```

    Without the backslash, bash tries to expand `${aws:username}`, finds a colon where it expects an
    operator, and aborts the whole heredoc with `bad substitution` - which at least fails loudly.
    Getting it backwards in the other direction fails silently, which is worse.

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

**What to look for:** zero dollar signs, and real values where the variables were. If you see the
literal text `${USMS_ACCOUNT_ID}` in the file, you used a quoted heredoc and IAM will reject the
document with a message about an invalid principal that mentions neither quoting nor variables.

**Command - part 4, the new role**

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

**Command - part 5, fix the trust policy on the role that already exists**

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

If `$USMS_ECS_TASK_ROLE` is not set in your `configs/lab-04.env`, use the literal name - and add the
variable to that file afterwards, because a name typed by hand in one place is a name that will be
typed differently in another:

```bash
USMS_ECS_TASK_ROLE="${USMS_ECS_TASK_ROLE:-usms-ecs-task-role}"
echo "task role: $USMS_ECS_TASK_ROLE"
```

**Command - part 6, verify**

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

**What to look for:** the words `SAME PRINCIPAL, NEW CONDITION`. That is the whole claim of this step,
made mechanically: **who may assume the role did not change; the circumstances under which they may
did.** A trust policy change that altered the principal would be a functional change wearing a
security change's clothes, and it is exactly the sort of thing that gets a security review reverted.

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

**Purpose**

Build the deployment identity this course has never had, and use it to introduce the two IAM
mechanisms that actually contain a compromised principal: a scoped `iam:PassRole` and a permissions
boundary.

Everything in this course so far has been built as the account root, which is the one identity nobody
should ever build anything as. This step creates the role a CI pipeline - or the CloudFormation lab -
would use instead.

**Run from**

```text
aws-floci-course/
```

**Concept first - why `iam:PassRole` is the action that matters**

You have used it three times without noticing.

- Lab 03 Step 8 passed `usms-ec2-app-profile` to `run-instances`.
- Lab 04 passed `usms-ecs-exec-role` and `usms-ecs-task-role` to `register-task-definition`.
- Lab 06's service-linked role passes nothing, which is part of why it is safe.

Every one of those is an act of **handing a set of permissions to a service so that the service can
use them on your behalf**. AWS gates it behind a separate action, `iam:PassRole`, precisely because the
permissions being handed over may be larger than the permissions of the person handing them over.

The escalation is short enough to write out in full:

```text
1. Attacker controls a principal with:   ec2:RunInstances  and  iam:PassRole on Resource "*"
2. There exists somewhere in the account: an admin role with an ec2.amazonaws.com trust policy
3. Attacker launches an instance, passing that admin role as its instance profile
4. Attacker reads the instance's credentials out of the metadata service
5. Attacker is now an administrator
```

Nothing in that sequence exploits a bug. Every step is a documented, intended API call. The only thing
that stops it is step 1 being false - which means scoping `iam:PassRole` to named role ARNs, and
adding the `iam:PassedToService` condition so that even those roles can only be passed to the services
that are supposed to receive them.

**Concept first - what a permissions boundary is, and what it is not**

A permissions boundary is a managed policy attached to a role or user in a **second slot**, next to
its ordinary policies. It grants nothing. It sets a **ceiling**: the principal's effective permissions
are the intersection of its identity policies and its boundary.

```text
identity policy says:   s3:*, ec2:*, iam:*
boundary says:          s3:*, ec2:*
effective:              s3:*, ec2:*          <- iam:* is capped away, silently

identity policy says:   s3:GetObject
boundary says:          s3:*, ec2:*
effective:              s3:GetObject         <- the boundary granted NOTHING
```

Read the second example twice. **A boundary can only subtract.** Attaching a boundary that allows
everything to a role with no policies gives that role no permissions at all.

What it is for, in one sentence: it is how you safely delegate the ability to create roles. Give a
platform team `iam:CreateRole` with a condition requiring `iam:PermissionsBoundary` to equal your
boundary's ARN, and they can create as many roles as they like, none of which can exceed the ceiling
you set - including roles they might create in order to escalate. That is the only mechanism in IAM
that solves that problem, and it is why boundaries exist.

**Command - part 1, the boundary document**

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

**What the command does**

Quoted heredoc - no shell variables in the document.

Notice what the first statement does and does not contain. It has `Resource: "*"`, which the audit
script in Step 5 would flag, and that is **correct for a boundary**: a ceiling that named specific
resources would cap the role to those resources rather than to those actions, which is not what a
ceiling is for. When you re-run the audit at Step 18 you will see this policy is not flagged at all,
for a reason worth predicting before you get there.

The second statement is where the real work is. Every action in it is a way of **changing who can do
what**, and an explicit `Deny` on all of them means a principal wearing this boundary cannot escalate
its own privileges even if somebody attaches an administrator policy to it by mistake. That last
clause is the whole value proposition: a boundary protects you from a future mistake made by someone
who has more authority than you do.

`iam:DeleteRolePermissionsBoundary` in that list is not decoration. Without it, the first thing a
compromised principal with `iam:*` would do is remove its own ceiling.

**Command - part 2, create it, and do not attach it to anything**

```bash
BOUNDARY_ARN=$(aws iam create-policy \
  --policy-name USMSPermissionsBoundary \
  --description "A CEILING, not a grant. Used only as a --permissions-boundary. Never attach this." \
  --policy-document file://policies/usms-permissions-boundary.json \
  --tags Key=Project,Value=USMS Key=Lab,Value=05 Key=Purpose,Value=boundary \
  --query 'Policy.Arn' --output text)

echo "BOUNDARY_ARN = $BOUNDARY_ARN"
```

**Command - part 3, the deploy policy, with a scoped `iam:PassRole`**

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

**What the command does**

Unquoted heredoc, because three role ARNs have to be built from `${USMS_ACCOUNT_ID}`. Check the
`grep -c '\$'` prints `0`.

The three statements are three different ideas and it is worth naming them:

- **Statement 1** is what the pipeline does. Note that `ecs:UpdateService` on `Resource: "*"` would be
  flagged MED by Step 5's audit, and it is a genuine finding - scoping it to one service ARN is
  Exercise 2.
- **Statement 2** is the `PassRole` grant: three named roles, and only to ECS tasks. Compare it with
  the escalation sequence above and notice that step 3 is now impossible, because there is no admin
  role in that list and no other service in that condition.
- **Statement 3** is an explicit `Deny` on passing *anything* to EC2. That is stronger than the
  absence of a grant, and the reason is the interlude's rule 1: if somebody later attaches a broad
  policy to this role, the `Allow` they add is overridden and the escalation path stays shut.

`iam:PassedToService` is the condition key that makes this precise. Without it, "may pass
`usms-ecs-task-role`" means may pass it to *anything*, including EC2 - and `usms-ecs-task-role` has
`USMSStudentDataReadWrite` on it, so an instance wearing it could write transcripts.

**Command - part 4, the trust policy and the role**

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

**What the command does**

`--permissions-boundary` is the flag that does the whole of this step's second idea, and it is one
flag. A boundary can also be attached to an existing role with
`aws iam put-role-permissions-boundary`, and removed with `aws iam delete-role-permissions-boundary` -
which is exactly the action the boundary document above denies.

The trust policy names a **user ARN**, not a service. Compare it with Step 7's document: the same
`sts:AssumeRole` action, a completely different kind of principal, and no condition - because a user
principal in your own account is not a confused deputy risk. It is your own user. The equivalent
hardening for a user principal is an MFA condition, which Section 12 lists as
`Conceptual / Real AWS` and Exercise 2 asks you to write anyway.

!!! warning "If your build rejects `--permissions-boundary`"
    Some builds accept `create-role` and silently ignore the flag, and some reject it outright.

    Check which happened:

    ```bash
    aws iam get-role --role-name usms-deploy-role \
      --query 'Role.PermissionsBoundary' --output json
    ```

    If it returns `null` on a role you created with the flag, your build stores roles without
    boundaries. Record it as a limitation, try `put-role-permissions-boundary` once as a second
    attempt, and continue - Section 9's script lists the boundary check among its known benign
    failures, and the reasoning in this step is what is assessed.

**Command - part 5, verify**

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

**What to look for:** three things, in this order of importance.

1. **`Boundary` is not null.** That is the ceiling, in the second slot.
2. **The `PassRole` statement names three ARNs and no wildcard.** Read them and satisfy yourself that
   none of the three is an administrator.
3. **The boundary is attached to nothing.** `AttachmentCount` on that policy stays at zero forever,
   and a colleague tidying up unattached policies would delete the one control preventing the
   pipeline from escalating. Put a comment to that effect in your report; Section 16's KEEP column
   says the same thing.

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

**Purpose**

Lab 02 Step 3 assumed `usms-developer-role` and got everything the role could do. There is a third way
to narrow permissions, orthogonal to both identity policies and boundaries, and it is the one you
reach for when the narrowing is temporary: a **session policy**, passed at the moment you assume the
role.

This step uses one, and - more importantly - makes you compute the effective permissions of the
session by hand, because that intersection is the thing you have to be able to do in your head when
somebody asks why their credentials do not work.

**Run from**

```text
aws-floci-course/
```

**Concept first - three ways to narrow, and where each one lives**

| Mechanism | Attached to | Lives for | Set by | Can it grant? |
| --- | --- | --- | --- | --- |
| Identity policy | A role, user or group | Until detached | Whoever administers IAM | **Yes** |
| Permissions boundary | A role or user, in a second slot | Until removed | Whoever created the principal | No - caps only |
| Session policy | One `sts:AssumeRole` call | The session, up to an hour here | **The caller**, at assume time | No - caps only |

The third row is the interesting one and it has a property the other two do not: **the caller sets it
on themselves**. That sounds pointless - why would anyone voluntarily take permissions away? - until
you think about what a caller usually is. A pipeline step that only needs to read a log group can
assume the deploy role with a session policy allowing exactly `logs:GetLogEvents`, so that a bug in
*that step's own code* cannot delete a service. It is the seatbelt you fasten on yourself.

The effective permissions of such a session are:

```text
effective = identity policy  AND  boundary  AND  session policy
```

Three intersections. An action must appear in all three, and must be denied by none.

**Command - part 1, write a session policy**

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

**What the command does**

This document lives in `outputs/` rather than `policies/`, and the distinction is deliberate: it is
not a policy attached to anything in the account. It is an argument to one API call, used once, gone
when the session ends. `policies/` is for the account's security posture; a session policy is not part
of it.

**Command - part 2, assume the role with it**

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
    Environment credentials sit **above** named profiles in the AWS CLI's resolution order. Until you
    unset them in part 4, every `aws` command in this terminal runs as the scoped session, whatever
    `--profile` you pass.

    `--duration-seconds 900` is fifteen minutes rather than the role's maximum of an hour, because a
    session should be as short as the work it is for. If part 4 does not run, this one expires on its
    own - which is the argument for short sessions in a single sentence.

**Command - part 3, compute the intersection by hand**

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

**What the command does**

This is the whole point of the step. It reads the role's identity policy out of Step 4's inventory,
reads the session policy off disk, and for each action in the session policy asks the two questions
the interlude's evaluation order asks: is it allowed by the identity policy, and is it denied
anywhere.

`matches` implements the only wildcard rule IAM actions use - a trailing `*` - which is enough for
every policy in this course. It is not a complete IAM evaluator and does not pretend to be: it ignores
resources, conditions, and every one of the twenty-odd condition operators. **A tool that models the
part of the problem you are reasoning about, and says so, is more useful than one that claims to model
all of it.**

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

**What to look for:** at least one line that is **not** `ALLOWED`, and the reason for it. On most
builds `sts:GetCallerIdentity` is the one, and it is the most instructive result in this step: the
session policy allows it, and the session still cannot do it, because the identity policy never
granted it and **a session policy cannot grant anything the role did not already have**.

If your `USMSDeveloperBase` happens to include `sts:*`, pick another action for the session policy -
`s3:ListAllMyBuckets` is a good one - and re-run. The lesson requires at least one line that fails.

!!! note "Floci Limitation - the session policy is not enforced, and `simulate-principal-policy` may be absent"
    Floci accepts `--policy` on `assume-role`, returns credentials, and then authorises nothing, so the
    scoped session can do everything the unscoped one could.

    Real AWS evaluates the intersection on every call. `aws iam simulate-principal-policy` is the API
    that answers "would this principal be allowed to do this", and if your Step 3 probe found it
    supported, use it as a second opinion:

    ```bash
    aws iam simulate-principal-policy \
      --policy-source-arn "arn:aws:iam::${USMS_ACCOUNT_ID}:role/${USMS_ROLE_DEVELOPER}" \
      --action-names ec2:DescribeVpcs sts:GetCallerIdentity iam:CreateUser \
      --query 'EvaluationResults[].{Action:EvalActionName,Decision:EvalDecision}' \
      --output table
    ```

    If it is not supported - which is the expected case - the Python above **is** the fallback the
    course contract requires: read the policy documents and justify your answer. Say in your report
    which of the two you used.

**Command - part 4, restore your normal identity**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
rm -f outputs/lab-09-scoped-session.json
```

**What to look for:** `whoami.sh` reporting the root identity and account `000000000000` again.
Deleting the session file immediately is the same habit as Lab 02 Step 4 and Lab 02's KEEP/CLEAN UP
column: a credentials file that has outlived its session is dead weight with a blast radius.

---

### Step 10 - Rotate the access key, with no window in which nothing works

**Purpose**

Lab 01 created a long-lived access key for `usms-dev-01` and every lab since has used it through the
`usms-dev` profile. Nobody has looked at it since.

A long-lived key is the one credential in this architecture that is not temporary, and rotation is the
control that limits how long a leaked one is useful. This step rotates it properly - which means four
steps rather than two, and the reason for the extra two is the whole lesson.

**Run from**

```text
aws-floci-course/
```

**Concept first - why rotation is four steps**

The naive rotation is: delete the old key, create a new one, update the profile. It has a window,
between the delete and the update, during which nothing that uses that key works. On a real system
that window is an outage, and it happens at the worst possible moment because rotation is usually done
under time pressure.

The correct sequence uses the fact that **IAM allows two access keys per user**, which exists for
exactly this purpose:

```text
1. CREATE a second key                  -> two keys, both active, nothing has changed
2. UPDATE every consumer to the new key -> traffic moves over, old key still works as a fallback
3. DEACTIVATE the old key               -> reversible. If something breaks, reactivate it
4. DELETE the old key                   -> irreversible, and only after step 3 has been quiet
```

Step 3 is the one people skip and it is the one that makes the procedure safe. A deactivated key can
be reactivated in one command; a deleted one cannot be recovered at all. The gap between 3 and 4 is
where you find out about the consumer nobody documented.

**Command - part 1, look at what you have**

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

**What the command does**

`get-access-key-last-used` is the call that answers the only question that matters about an old key:
is anything still using it. On a real account, a key with a `LastUsedDate` of `N/A` and a creation
date eighteen months ago is a key you can delete today, and finding those is the highest-value hour of
IAM housekeeping there is.

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

**What to look for:** exactly **one** key. If there are two, a previous rotation was never finished,
and you should work out which is in use before creating a third - you cannot, because two is the
limit, and that error message is how most people discover the limit.

**Command - part 2, create the new key, straight into `outputs/`**

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

**What the command does**

The redirect is the point, and it is Lab 03 Step 4's habit applied to a second kind of secret: the
secret access key goes **straight to a file**. It never appears on screen, never enters scrollback,
and cannot end up in a screenshot pasted into a lab report. The values are Floci dummies; the habit is
what transfers.

`git check-ignore -v` immediately afterwards is not optional. It prints the rule and the line number
that protected you, and silence there means the file is **not** ignored - at which point you stop and
fix `.gitignore` before doing anything else.

The `OLD_KEY_ID` query is worth reading. `AccessKeyMetadata[?AccessKeyId!='...']` filters the list to
everything that is not the new key, and `| [0]` takes the first - a JMESPath pattern for "the other
one" that is more robust than assuming an ordering.

**Expected result**

```text
.gitignore:7:outputs/*  outputs/usms-dev-01-access-key-new.json
new key id: AKIAI44QH8DHBEXAMPLE
old key id: AKIAIOSFODNN7EXAMPLE
```

> Example output - your key IDs and line number will differ.

**Command - part 3, move the consumer over**

```bash
aws configure set aws_access_key_id \
  "$(jq -r '.AccessKey.AccessKeyId' outputs/usms-dev-01-access-key-new.json)" --profile usms-dev
aws configure set aws_secret_access_key \
  "$(jq -r '.AccessKey.SecretAccessKey' outputs/usms-dev-01-access-key-new.json)" --profile usms-dev

aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text
aws configure get aws_access_key_id --profile usms-dev
```

**What to look for:** the ARN still reads `arn:aws:iam::000000000000:user/usms-dev-01`, and
`aws configure get` prints your **new** key ID. Both are needed: the first says the profile works, the
second says it works *because of the new key* rather than because the old one is still there.

**Command - part 4, deactivate the old key and prove nothing broke**

```bash
aws iam update-access-key \
  --user-name "$USMS_DEV_USER" \
  --access-key-id "$OLD_KEY_ID" \
  --status Inactive

aws iam list-access-keys --user-name "$USMS_DEV_USER" \
  --query 'AccessKeyMetadata[].{Key:AccessKeyId,Status:Status}' --output table

aws sts get-caller-identity --profile usms-dev --query 'Arn' --output text
```

**What to look for:** two keys listed, one `Active` and one `Inactive`, and the `usms-dev` profile
still answering. **This is the state you would sit in for a day or a week on a real system**, watching
for anything that breaks, before going on to part 5. Doing it in the next thirty seconds here is a
compression of the procedure, not a demonstration that the pause is unnecessary - say so in your
report.

**Command - part 5, delete the old key**

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

**What to look for:** exactly one key, `Active`, created today; the profile still working; and Lab 01's
original key file gone from `outputs/`. That last `rm` deletes a file containing a secret that no
longer exists anywhere in the account - which makes it harmless and, for exactly that reason, easy to
leave lying around for two years.

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
    The best rotation is the one you never have to do, and on a real account this key would not exist.
    A developer would authenticate through IAM Identity Center or a federated identity provider and
    receive **temporary** credentials, and a workload would use a role - as `usms-web-01` and every
    enrolment task already do.

    This course keeps one long-lived key because Lab 02's assume-role handshake needs a principal that
    the role's trust policy can name, and because rotating one is a skill worth having. Say in your
    report what you would replace it with and why the replacement removes the need for this step
    entirely.

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

**Purpose**

`usms-web-01` carries `usms-ec2-app-profile`, which means AWS credentials are available to anything
running on that instance through the instance metadata service at `169.254.169.254`. Lab 03 Step 11
traced that chain and called it a feature, correctly - no key on disk.

It is also the most valuable thing on the instance, and there is a well-known way to steal it that
does not require access to the instance at all.

**Run from**

```text
aws-floci-course/
```

**Concept first - why a token requirement stops a whole class of attack**

IMDSv1 answers a plain `GET http://169.254.169.254/latest/meta-data/...` with no authentication of
any kind. IMDSv2 requires the caller to first `PUT` for a token and then send that token as a header
on every request.

That sounds like a trivial difference. It is not, and the reason is what the attacker has:

```text
A server-side request forgery (SSRF) bug lets an attacker make the APPLICATION issue a
request to a URL of the attacker's choosing. The attacker controls the URL. In almost every
such bug, the attacker does NOT control the METHOD or the HEADERS.

IMDSv1:  attacker supplies  http://169.254.169.254/latest/meta-data/iam/security-credentials/
         the application GETs it, and returns the credentials in the response.
IMDSv2:  the same GET is refused. Obtaining a token requires a PUT with a header, and the
         SSRF bug can do neither.
```

That is the Capital One breach of 2019 in four lines, and it is why `--http-tokens required` exists.

The second flag matters for a different reason. `--http-put-response-hop-limit` sets the IP TTL on the
metadata response, and a hop limit of `1` means **the response cannot leave the instance**. Without it,
a container running on that instance - on a Docker bridge network, which is one hop - can reach the
host's metadata service and inherit the host's role. Setting it to 1 is what stops a compromised
container becoming a compromised instance.

**Command - part 1, look before you change**

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

**What to look for:** `HttpTokens`. `optional` means IMDSv1 still works, which means the SSRF path
above is open. Some Floci builds return an empty object or omit the field entirely; if yours does,
record it and read the fallback below.

**Command - part 2, require tokens**

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

**What the command does**

Three flags, and the third one is the only one that is a judgement call.

`--http-tokens required` turns off IMDSv1 on this instance. On a real account this is a change that
can break things: an old SDK, or a script using plain `curl` against the metadata service, stops
working. The correct rollout order is to watch the CloudWatch metric `MetadataNoToken` - which counts
IMDSv1 calls - until it is zero, and only then require tokens. Doing it the other way round is how you
find out which of your instances runs a 2016 SDK.

`--http-endpoint enabled` keeps the metadata service on. Disabling it entirely is the strongest
possible setting and is right for an instance with no instance profile - which `usms-db-01` is.
Exercise 1's second half asks you about exactly that.

`--http-put-response-hop-limit 1` is the container defence described above. AWS's own default for new
instances is 1, but instances launched from some AMIs and by some tools get 2, and 2 is enough.

Lab 03's `user-data.sh` already used the IMDSv2 token flow - go and look at its `meta()` function.
That script was written to survive this change, which is what "write it correctly the first time"
looks like when the change arrives two years later.

**Command - part 3, verify**

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
    Lab 03 Step 11 recorded this already: Floci does not serve IMDS to instances, so there is no
    endpoint on `169.254.169.254`, no credentials delivered, and nothing for a token requirement to
    apply to. Some builds store `MetadataOptions` faithfully and return it; some ignore the
    modification entirely.

    Real AWS enforces it on the instance itself, at the hypervisor level, from the moment the API call
    returns.

    Take away the reasoning rather than the field. In your report, name the attack that
    `--http-tokens required` prevents, the different attack that `--http-put-response-hop-limit 1`
    prevents, and the rollout order that stops the first one from causing an outage. Section 14 asks
    for exactly those three.

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

Hint: the answer to the second question is in Lab 03 Step 11, in the paragraph about where the
credentials come from.

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

### Interlude - the four questions to ask a security group

Lab 02's interlude compared security groups with network ACLs. This one is about how to *review* a
security group, which is a different skill and needs four questions rather than one table.

```text
1. WHO CAN REACH ME?        ingress rules. The only one anybody ever looks at
2. WHAT CAN I REACH?        egress rules. The one nobody wrote and nobody has ever read
3. IS THE SOURCE A GROUP OR AN ADDRESS?
                            a group survives re-addressing, scaling and redeployment.
                            an address range is a rule that was true when it was written
4. IS THIS GROUP ATTACHED TO ANYTHING?
                            an unattached group is not a risk. It is a source of confusion,
                            which becomes a risk the day somebody attaches it
```

Question 2 is where the findings are, and question 4 is where the surprises are.

Three facts about egress that are worth having in your head before Step 13 changes any of it:

- **The allow-all egress rule is created for you, on every security group, and is not shown by
  `authorize-security-group-ingress`.** You have created five groups in this course and written zero
  egress rules.
- **Security groups are stateful in both directions.** An outbound connection's replies come back
  without an ingress rule, and an inbound connection's replies go out without an egress rule. So
  restricting egress does *not* break anything that is answering an inbound request - which is the
  single most common reason people give for not restricting it, and it is wrong.
- **Removing the last egress rule denies all outbound traffic**, and there is no way to express
  "allow nothing" other than having no rules. A group with an empty egress list is a group whose
  instances can initiate nothing at all.

That second point deserves the emphasis. `usms-enrolment-sg` serves HTTP requests that arrive from the
load balancer, and the responses to those requests are return traffic on an established connection -
they are permitted by state, not by rule. Everything Step 13 restricts is traffic the **task
initiates**, which is exactly the traffic an attacker inside the task would need.

---

### Step 12 - Build the security group audit script

**Purpose**

Do for the network axis what Step 5 did for the identity axis: turn five security groups into a list
of findings, computed from rules rather than from names.

It changes nothing. Read-only, always.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

Four backticks around the block again, because it contains two nested heredocs.

Three design decisions worth naming, because they are the difference between an audit tool and a
`describe-security-groups` wrapper:

**It resolves group IDs to names.** `by_id` is built once from the same response, so a rule sourced
from `sg-0bb22cc33dd44ee55` prints as `sg:usms-alb-sg`. Nobody can review a rule set written in
sixteen-character hexadecimal, and the reviewer who tries will make a mistake.

**It counts network interfaces per group.** That is a second API call per group and it is the only way
to answer question 4. An unattached group is a `LOW` finding rather than a `MED` because it is not
itself dangerous - but a group called `usms-app-sg` on no interfaces would mean something has gone
very wrong somewhere else, and you would want to know.

**It detects the default egress rule by its exact shape** - protocol `-1`, one `IpRanges` entry of
`0.0.0.0/0` - rather than by asking "is egress wide". That precision matters because after Step 13 you
will have deliberately written a wide egress rule (tcp/443 to `0.0.0.0/0`), and a tool that flagged
your considered decision the same way it flags AWS's default would be teaching you to ignore it.

`$$` in the temporary filenames is the shell's process ID, so two people running this on the same
machine do not overwrite each other's scratch files. The `rm` at the end is unconditional and runs
even if the Python exits non-zero, because it is a separate command rather than something chained
with `&&`.

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

Read the findings before you fix any of them, and sort them into three piles. This is the actual work
of a security review and it is worth doing on paper:

| Finding | Verdict |
| --- | --- |
| `usms-alb-sg` ingress tcp/80 from `0.0.0.0/0` | **Accepted risk, documented.** It is an internet-facing load balancer. Lab 05 Step 4 argued this properly and nothing has changed |
| `usms-app-sg` ingress 80 and 443 from `0.0.0.0/0` | **Open finding.** The web instance is a second internet-facing entry point that predates the load balancer, and Exercise 4 asks whether it should still exist |
| `usms-app-sg` ingress 22 from `10.0.0.0/16` | **Fix in Step 16.** Any compromised thing anywhere in the VPC can currently reach SSH |
| Default egress on all five groups | **Fix in Steps 13 to 15**, and Exercise 1 for `usms-app-sg` |
| `default` group on no interfaces | **Accepted.** Every VPC has one; nothing uses it; leave it |

**What to look for:** the two `HIGH` findings on `usms-app-sg`. Notice that the tool has no idea one of
those `0.0.0.0/0` rules is fine and the other is a finding, because the difference is architectural
and lives in your head. **An audit tool produces findings, not verdicts.** A tool that produced
verdicts would be one you argued with instead of one you used.

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

**Purpose**

Replace the allow-all egress rule on `usms-enrolment-sg` with one you wrote and can defend. This is
the group in front of the workload most worth constraining: the enrolment tasks run code that pulls a
container image, writes logs, and - from Lab 10 onwards - reads transcripts. Everything else they
could reach is somebody else's opportunity.

**Run from**

```text
aws-floci-course/
```

**Concept first - what a Fargate task legitimately needs to initiate**

Work it out from the architecture rather than from a list:

| It must reach | Why | On what |
| --- | --- | --- |
| A container registry | To pull `usms-enrolment:2`'s image at task start | tcp/443, to addresses AWS or Docker Hub owns |
| CloudWatch Logs | The `awslogs` driver from Lab 04 ships every line | tcp/443, to the Logs endpoint |
| S3 | Lab 10's transcripts, through Lab 02's gateway endpoint | tcp/443, to S3's address ranges |
| Nothing else | There is nothing else in the design | - |

And what it must **not** reach: the database tier, the web instance, the internet on any port other
than 443, and every other AWS service in the region.

Three of the four rows say tcp/443, which is the honest answer and also a slightly unsatisfying one:
443 to everywhere is not a narrow rule. Two things make it worth writing anyway.

**It is dramatically narrower than allow-all.** Every non-HTTPS protocol is now denied outbound: no
DNS exfiltration on 53, no SSH out on 22, no database protocol on 5432, no mail on 25, no arbitrary
high port to a command-and-control server. That is most of what an attacker inside a container would
reach for.

**One of the four rows can be made precise, and we do.** S3 traffic through Lab 02's gateway endpoint
has a **managed prefix list** - a named, AWS-maintained set of address ranges - and a security group
rule can name it as a destination. That is a genuinely tight rule, and it is the first time in this
course the S3 endpoint has been anything but a route table entry.

On a real account the other three rows tighten too, with **interface endpoints** for ECR, CloudWatch
Logs and STS: each one puts a private address inside your subnet, so the egress rule becomes tcp/443
to that endpoint's own security group. Section 12 lists it as `Conceptual / Real AWS` - Floci does not
model interface endpoints - and Exercise 4 asks you to design it.

**Command - part 1, find the S3 prefix list**

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

**What the command does**

Two independent sources for the same value, tried in order, because Lab 02 Step 21 recorded a Floci
limitation that goes exactly this way: some builds create the endpoint and report it `available` but
do not inject the prefix-list route into the route table, and some do the reverse.

`?DestinationPrefixListId!=` followed by a backtick, `null`, and a backtick is a JMESPath filter for
"this field is not null". The backticks make `null` a JSON literal rather than the string `"null"`,
which is a distinction that matters and produces an empty result when you get it wrong.

**If both sources produce nothing**, your build does not model gateway endpoint prefix lists. That is
fine and the step continues - part 2 has a branch for it. Record it in your notes as a limitation, and
write in one sentence what the rule would have been.

**Command - part 2, write the egress document**

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

**What the command does**

The `if` chooses between an **unquoted** heredoc, because the first branch must expand
`${S3_PREFIX_LIST}`, and a **quoted** one, because the second branch has nothing to expand. Two
documents, opposite quoting, twelve lines apart, for the reason that has now appeared in five
laboratories: *do I want this expanded now, or later?*

The `grep -c '\$'` must print `0` either way.

Each rule carries a `Description`. Security group rule descriptions are the cheapest documentation in
AWS - they are returned by `describe-security-group-rules`, they survive everything, and they are read
by the next person at exactly the moment they need them. A rule without one is a rule somebody will
eventually delete because nobody could say what it was for.

**Command - part 3, keep the undo, then make the change**

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

**What to look for:** one or two egress rules, both tcp on 443, and **no rule with protocol `-1`**.
That last one is the assertion: a `-1` rule still present means the revoke did not take, and the group
still permits everything.

Then confirm the change did not touch ingress, because that is what would break the architecture:

```bash
aws ec2 describe-security-groups --group-ids "$USMS_ENROLMENT_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,Source:UserIdGroupPairs[0].GroupId}' \
  --output table
echo "usms-alb-sg = $USMS_ALB_SG"
```

**What to look for:** one ingress rule, tcp/80, sourced from `$USMS_ALB_SG`. Exactly as Lab 05 Step
13 left it.

---

### Step 14 - Write the load balancer's egress rule, whose destination is a security group

**Purpose**

Constrain what the load balancer itself may initiate. This is the smallest egress rule in the lab and
the most precise, because for once the destination is a thing you own and can name.

**Run from**

```text
aws-floci-course/
```

**Concept first - an egress rule whose destination is a group**

Lab 02 Step 15 wrote an **ingress** rule sourced from a security group, and gave the reason: the
addresses of the thing you are permitting are not stable. The same argument runs in the outbound
direction and almost nobody uses it.

A load balancer's only legitimate outbound destination is its targets. The targets are Fargate tasks
whose addresses change every deployment, every scale-out and every task replacement - and Lab 06
made that happen automatically, so they now change without anyone doing anything. An egress rule
written against those addresses would be wrong within the hour.

An egress rule whose destination is `usms-enrolment-sg` is right permanently, including for tasks that
do not exist yet. That is the sentence to take away: **a group reference is a rule about a role in the
architecture, and an address is a rule about a moment in time.**

**Command - part 1, the document**

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

**Command - part 2, authorise then revoke**

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

**What to look for:** the two rules read as a matched pair, and they say something you can state in
one sentence. *Anything on the internet may open an HTTP connection to this load balancer; this load
balancer may open an HTTP connection to exactly one thing.* `CIDR` being `null` on the egress rule and
`ToGroup` being populated is the group reference; if they are the other way round, you have written an
address-based rule and Step 12's audit will not notice, because a rule to a `10.0.3.0/24` is not a
finding by any mechanical test.

That is worth dwelling on for a moment. The audit script cannot catch this one. **Some review is
mechanical and some is reading, and knowing which findings are which is most of the skill.**

---

### Step 15 - Write the data tier's egress rule

**Purpose**

`usms-db-01` holds student transcripts. Lab 02's design gave it outbound internet access through the
NAT gateway for one stated reason - operating system updates - and then permitted every protocol to
every destination, which is not that.

This is the group where egress control does the most work, because a database is the thing an attacker
is trying to get data *out of*.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, the document**

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

**What the command does**

Quoted heredoc; no variables.

One rule, and it is worth noticing what is now denied that was not before. The data tier can no longer
initiate: DNS to an external resolver on 53, SSH out on 22, a database connection to anything, SMTP,
or an HTTP connection on 80 to a server the attacker controls. **Every one of those is a data
exfiltration path and none of them is a port anybody would have thought to close.**

It is still not tight. Port 443 to `0.0.0.0/0` permits an HTTPS POST of the transcripts table to any
host on the internet, and no security group rule written in terms of ports can prevent that. Stopping
it needs a different control - egress filtering by hostname, which on AWS means a NAT instance with a
proxy or an AWS Network Firewall rule group, and is Exercise 4's second half. Say that in your report
rather than claiming the rule solves a problem it narrows.

**Command - part 2, authorise then revoke**

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
    An instance that can reach HTTPS but cannot reach **DNS** cannot resolve the name of the mirror it
    is about to fetch from. `dnf update` would hang and then fail with a name-resolution error that
    says nothing about security groups.

    In `usms-vpc` the resolver is the Amazon-provided one at `10.0.0.2` - the second address in the
    VPC range, reserved for exactly this, as Lab 02's CIDR interlude noted. Traffic to it is **inside
    the VPC**, so a rule permitting UDP and TCP 53 to `10.0.0.0/16` is what a complete version of this
    document would add.

    We leave it out here because Floci does not provide the resolver - Lab 02's Section 12 lists it as
    a limitation - and adding a rule for a service that does not exist would be a rule nobody could
    check. Add it to your Exercise 1 answer, with both protocols, and say why UDP comes first.

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

**What to look for:** three zeros. That is the claim of Steps 13 to 15 in three lines, asserted rather
than described, and it is a check Section 9's script repeats.

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

**Purpose**

`usms-app-sg` admits TCP 22 from `10.0.0.0/16`. That is every address in the VPC: both EC2 instances,
every Fargate task, the NAT gateway, and anything anyone adds later. Lab 02 Step 14 wrote it that way
deliberately, as an improvement on `0.0.0.0/0`, and Lab 02's Exercise 2 asked you to improve it again.

This step finishes that job - reusing the bastion group if that exercise created one, and creating it
if not.

**Run from**

```text
aws-floci-course/
```

**Concept first - why a bastion group and not a bastion instance**

There is no jump host in this architecture and this step does not create one. What it creates is the
**group**, and the group is the useful half.

A security group with no members is a name for a role in the architecture. `usms-app-sg` admitting SSH
from `usms-bastion-sg` says "administrative access arrives through the jump host tier", and it says it
whether or not a jump host exists today. The day one is launched, it carries the group and the rule is
already correct. The day it is terminated, the rule is still correct and grants nothing to anyone.

That is a property addresses do not have, and it is the third time this course has made the argument -
Lab 02 Step 15, Lab 05 Step 9, and here.

**Command - part 1, find or create the group**

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

**What the command does**

The whole block is idempotent, which is why it is written as a lookup with a fallback rather than as a
`create-security-group`. Running it twice does nothing the second time, and running it in a class where
half the students did Lab 02's Exercise 2 gives both halves the same end state.

`| [0]` on a `--query` that already selects `SecurityGroups[0]` looks redundant and is not: on a build
where the filter matches nothing, `SecurityGroups[0]` yields null, `--output text` prints `None`, and
the `[ "$BASTION_SG" = "None" ]` test catches it. Without the pipe, some CLI versions print an empty
line instead and the test still works - belt and braces, one character.

`203.0.113.10/32` is from `TEST-NET-3`, a range RFC 5737 reserves for documentation. Using a
documentation address rather than an invented real one means nobody in the class accidentally
authorises a stranger's server, and it is the same address Lab 02's Exercise 2 suggested.

**Command - part 2, the new rule on `usms-app-sg`**

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

**Command - part 3, remove the old rule**

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

**What the command does**

The JMESPath filter combines three conditions: a boolean literal in backticks, a numeric literal in
backticks, and a string in single quotes. That is the quoting rule Lab 05 Step 13 introduced, and the
backticks are escaped as `\`` because the whole query is inside double quotes so that `$USMS_APP_SG`
expands.

`revoke-security-group-ingress --security-group-rule-ids` removes exactly one rule by its own
identifier. The alternative - restating the permission with `--ip-permissions` - works too and is
riskier, because a permission you restate slightly differently from the one that exists silently
removes nothing and returns `True`.

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

**What to look for:** the port 22 row has `CIDR` of `None` and `FromGroup` holding the bastion group's
ID. If both are populated you have two SSH rules and the revoke did not take; if `CIDR` still reads
`10.0.0.0/16`, part 3 found no rule to remove and you should re-read its output.

Now say what changed, in one sentence, because this is the sentence the assessment asks for: *SSH to
the USMS web tier is no longer reachable from anything in the VPC that is not part of the
administrative tier - including from a compromised enrolment task.*

That last clause is the finding this step actually closed. Lab 04 put Fargate tasks in
`10.0.3.0/24` and `10.0.4.0/24`, both of which are inside `10.0.0.0/16`, so **every enrolment task
could open an SSH connection to the web server** until ninety seconds ago. Nobody wrote that rule
either; it was written in Lab 02, before the tasks existed, and it grew a new meaning when they
arrived.

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

**Purpose**

The audits in Steps 5 and 12 listed findings one object at a time. A security review has to answer a
different kind of question - *who can reach what* - and that question is not answered by any single
object, because it is a property of the relationships between all of them.

This step builds the tool that answers it, and then uses it to prove the two claims this architecture
rests on.

**Run from**

```text
aws-floci-course/
```

**Concept first - a negative needs more than one control, and here is why**

Claiming "the transcripts database is not reachable from the internet" is a claim about everything
that does not exist, and you cannot test it. What you can do is enumerate the controls that would each
independently have to fail, and count them.

For `usms-db-01` there are four:

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

Now do the thing that makes this reasoning worth writing down: **remove one and ask whether the claim
still holds.** Give the instance a public address and control 3 still stops it. Add an internet
gateway route and control 1 still stops it. Open the security group to `0.0.0.0/0` and controls 1 and
3 both still stop it.

That is defence in depth, stated precisely rather than as a slogan: **the claim survives the failure of
any single control.** A system where the claim rests on exactly one control is a system one mistake
away from a breach, and this step's second half shows you that the enrolment tasks are exactly that
system.

**Command - part 1, build the matrix tool**

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

**What the command does**

The verdicts are computed from `IpPermissions` and `IpPermissionsEgress` and from nothing else. No
name, no tag, no description enters the logic - which is the same rule Lab 02's Exercise 3 and Lab
03's Exercise 3 imposed, and for the same reason: a report that reads the `Tier` tag is a report of
what somebody intended, and you are trying to find out what is true.

The `lonely` list is the part worth stealing for your own work. It counts ingress rules per group and
names the groups with exactly one - not because one rule is wrong, but because a group with one rule
has no second control, and knowing which of your protections are load-bearing on their own is more
useful than knowing how many you have.

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

**What to look for:** four things, and the fourth is the finding.

1. **Two groups admit the internet**, and they are `usms-alb-sg` and `usms-app-sg`. Lab 05 argued for
   the first. Nobody has ever argued for the second, and Exercise 4 makes you.
2. **`usms-db-sg` and `usms-enrolment-sg` admit only a group.** That is the shape you want.
3. **`usms-app-sg` and `usms-bastion-sg` still carry the default egress rule.** Exercise 1 is the
   first; the bastion group is deliberately left, and its answer is different, because a jump host's
   whole job is to initiate SSH connections.
4. **`usms-enrolment-sg` is a single point of control.** One rule stands between the enrolment tasks
   and everything else in the VPC. Compare that with `usms-db-01`, which has four independent
   controls, and notice that the tasks have exactly one - because they are in a private subnet with no
   public address, which is two more, but neither of those is *in this report* because the report is
   about security groups.

Point 4 is the honest complication and it is worth stating carefully in your report: the reachability
matrix answers question 4 of the security group interlude and knows nothing about routing. **A tool
that models one axis will always understate the defences on the other one.** Say which axis yours
models.

**Command - part 2, prove the negative on the data tier, four controls at a time**

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

**What to look for**, line by line, because each line is one control and each has a specific right
answer:

| Line | Correct answer | What a wrong answer would mean |
| --- | --- | --- |
| control 1 | `None` | The instance has a public address. Control 3 still saves you |
| control 2 | `False` | A replacement instance would get an address by accident |
| control 3 | `None` then a `nat-` id | An `igw-` id here would make the subnet public. This is the load-bearing one |
| control 4 | a port, a `sg-` id, and `None` for the CIDR | A CIDR here means an address-based rule |
| control 5 | an `acl-` id and `False` | `True` means the custom NACL is not associated |

Write into `notes/lab-09-notes.md`, in one sentence each, what would still stop an attacker if control
3 failed, and what would still stop one if control 4 failed. Those two sentences are Review Question 5
and the viva asks for them out loud.

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

**Purpose**

Two proofs in one step, and they answer different questions.

The first is this course's standard persistence proof, applied to controls rather than to resources:
does an IAM condition, a permissions boundary, a written egress rule and an IMDS setting survive a
stop and start of the emulator? A security control that evaporates on restart is worse than none,
because the audit script would have recorded it as present.

The second is the question this lab has been deferring since Step 2: did any of it break what the
previous five laboratories built?

**Run from**

```text
aws-floci-course/
```

**Command - part 1, record the truth**

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

**What the command does**

Nine facts, across three services, chosen because each one is a control this lab created and each one
would be invisible if it vanished.

Two of them are worth explaining. `length(Role.AssumeRolePolicyDocument.Statement[0].Condition)`
counts the **keys of the condition block** rather than reading its contents - a number that is `2`
when both `StringEquals` and `ArnLike` survive and `0` when the condition is gone. Comparing a number
is more robust across a `diff` than comparing a JSON object whose key ordering may not be stable.

`length(IpPermissions[?FromPort==` + backtick + `22` + backtick + `].IpRanges[])` counts CIDR sources
on the SSH rule, and the correct answer is `0` - because after Step 16 the only source is a group. A
count of zero is a negative assertion, which is the kind Lab 02's Section 9 called out as the ones
worth having.

**Command - part 2, perturb**

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

`floci-down.sh` is `docker compose stop`. It stops the container and keeps the state. It is not
`docker compose down`, and it is emphatically not `docker compose down -v`, which would delete the
volumes and with them the entire course.

**Command - part 3, re-derive every identifier and read it back**

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

**What the command does**

Every identifier is **re-derived from the API** - by tag, by group name, by instance tag - rather than
reused from a shell variable. Reusing the variables would have proved only that Bash remembers
strings, which is the mistake described in Lab 01 Step 14 and repeated as a warning in every lab
since.

Note that `usms-enrolment-sg` is found by `group-name` and the others by `tag:Name`. That is not
inconsistency for its own sake: it is a hedge, because Lab 04 may or may not have tagged that group,
and a lookup that works for the object in front of you is better than a lookup that is stylistically
uniform and returns `None`.

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

**What to look for:** exactly that line. If you see `PERSISTENCE FAILED`, read the `diff` **before
doing anything else** - it names *which* of the nine facts did not survive, which is far more useful
than a general failure. A build that persists security groups but not IMDS settings is a real and
specific limitation and should be recorded as one.

**Command - part 4, prove you broke nothing**

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

**What the command does**

`diff <(...) <(...)` is process substitution: each `<(...)` becomes a filename that the command can
read, so `diff` compares the output of two pipelines without either one touching disk. `grep -v '^=='`
drops the timestamp headings, which are guaranteed to differ and would otherwise make every run report
a change.

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

**What to look for:** the words `NOTHING BROKE`, and understand precisely what they do and do not
claim. They claim that **no property any earlier laboratory asserted has changed.** They do not claim
that nothing changed - a great deal did - and they do not claim that the changes are correct. That is
what this lab's own verification script, in Section 9, is for.

If something did change, work out which check and decide, using the three responses Lab 05 Step 13
set out: document the expected failure, update the check to assert the new architecture, or - almost
never - delete the check.

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

**Purpose**

Every shell variable in this terminal dies when you close it, and this lab created ten things whose
names and ARNs matter. Lab 10 reads three of them and the CloudFormation lab re-declares all of them.
Record them **by lookup, not from the variables**, so that a populated value in the file is evidence
the resource actually exists.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

Unquoted heredoc - `<< EOF`, not `<< 'EOF'` - for the same reason as Lab 02 Step 24, Lab 03 Step 22,
Lab 04 Step 20, Lab 05 Step 18 and Lab 06 Step 16: every `$(...)` must run **now** and the
resulting value must land on disk. Had this been quoted, the file would contain the text of a dozen
API calls, and `source configs/lab-09.env` would re-run all of them in every new terminal you ever
open. That is the seventh appearance of this rule in six laboratories.

`USMS_EGRESS_ALLOW_ALL_REMAINING` is the awkward one and it repays a close look. It is a small shell
program inside a command substitution inside an unquoted heredoc, so **every dollar sign that belongs
to the inner program is escaped** - `\$(...)`, `\$g`, `\$id`, `\$total` - and so are the backticks
inside the JMESPath literal. Without the escapes, the outer shell would expand `$g` (to nothing, since
the loop has not run yet) as the file is *written*, and the file would contain a program that reads
`--filters "Name=group-name,Values="`.

That is the same escaping problem Lab 06 Step 16 met with `awk -F: '{print \$NF}'`, in a bigger and
less forgiving form. If you find yourself escaping more than about four dollar signs, the honest
alternative is to compute the value **before** the heredoc and interpolate a single variable - and
saying that out loud is worth more than the cleverness:

```bash
# The readable alternative, if the escaping fights you:
REMAINING=$(for g in usms-alb-sg usms-enrolment-sg usms-db-sg; do ... done)
# then, inside the heredoc:
#   export USMS_EGRESS_ALLOW_ALL_REMAINING=$REMAINING
```

`USMS_IMDS_TOKENS` and `USMS_EGRESS_ALLOW_ALL_REMAINING` are both **read back from the API** rather
than hard-coded as `required` and `0`. A file that quietly claims what you intended rather than what
exists is worse than no file, and Section 9's script asserts both values, so a lie here fails there.

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

**What to look for:** `all values populated`, eleven non-empty lines, and a count of **16** exported
variables. Three of those values are assertions rather than facts and each must read exactly:

- `imds tokens` must be `required`, not `optional`. Anything else means Step 11 did not take on this
  build - which is an acceptable, recorded limitation, but the file must say `optional` honestly
  rather than claim otherwise.
- `allow-all egress left` must be `0`. Any other number means one of Steps 13, 14 or 15 revoked
  nothing.
- `s3 prefix list` reading `none` is the documented Step 13 fallback and is acceptable. Any other
  non-`pl-` value is not.

---

### Step 20 - Commit

**Purpose**

Same discipline as every lab: look first, stage explicitly, then commit. This one has more to check
than most, because it is the lab that handled two secrets.

**Run from**

```text
aws-floci-course/
```

**Command - part 1, look before you add**

```bash
git status --short

git check-ignore -v outputs/usms-dev-01-access-key-new.json
git check-ignore -v outputs/lab-09-identity-inventory.json
git ls-files outputs/

echo
echo "== no policy document may contain an unexpanded variable =="
grep -l '\$' policies/*.json || echo "no unexpanded variables in any policy document"
```

**What to look for, before typing anything else:**

- No path under `outputs/` appears in `git status --short`. Especially not the access key file.
- No `.env` at the repository root appears.
- `configs/lab-09.env` **does** appear. It holds names and ARNs - no secrets, by construction.
- `git check-ignore -v` names the file, the rule and the line number for **both** output files.
  Silence there means the file is not ignored; stop and fix `.gitignore` before committing anything.
- `git ls-files outputs/` lists `outputs/.gitkeep` and nothing else.
- The last block prints `no unexpanded variables in any policy document`. If it names a file, open it:
  you used a quoted heredoc where an unquoted one was needed, and the document currently grants access
  to the literal string `${USMS_ACCOUNT_ID}`.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/usms-dev-01-access-key-new.json
.gitignore:7:outputs/*	outputs/lab-09-identity-inventory.json
outputs/.gitkeep

== no policy document may contain an unexpanded variable ==
no unexpanded variables in any policy document
```

> Example output - your line numbers may differ.

**Command - part 2, commit**

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

The `git add` names paths explicitly rather than using `git add -A`. That is not fussiness: `git add
-A` stages whatever happens to be in the working tree, which is exactly how an un-ignored secret
reaches a commit and, from there, a remote. In a laboratory that created an access key twenty minutes
ago, it is the wrong command to reach for.

The two script paths at the end only exist after Section 9. If you commit before building them, drop
those two lines and add them in a second commit.

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

## 9. Verification

### 9.1 What this script checks that a naive one would not

Nine of the checks below are the ones worth having, and they are why "does the role exist" is not
enough for a security lab:

- **`USMSStudentDataReadOnly` does NOT allow `s3:PutObject`** - a *negative* assertion about a policy
  document. Checking that a policy grants what you meant catches typos; checking that it does not
  grant what you did not mean catches the mistake that matters.
- **`usms-ecs-task-role`'s trust policy has a `Condition`** - the confused-deputy fix, asserted on the
  document rather than on the fact that Step 7 ran.
- **`usms-ecs-task-role`'s principal is still `ecs-tasks.amazonaws.com`** - because a trust policy
  update is a whole-document replace, and the failure mode of getting it wrong is a role nobody can
  assume.
- **`USMSDeployBase`'s `iam:PassRole` has no `Resource "*"`** - the escalation path, asserted directly.
- **`USMSPermissionsBoundary` has an attachment count of zero** - a check that something is *not*
  attached, which no other script in this course does, and which catches a colleague "tidying up" by
  attaching it as an ordinary policy.
- **`usms-dev-01` has exactly one access key** - two means a rotation was started and never finished,
  which is the state that looks fine and quietly doubles your exposure.
- **Three groups have zero allow-all egress rules** - the claim of Steps 13 to 15 in one line.
- **`usms-app-sg` has no CIDR source on port 22** - a negative assertion, and the only thing that would
  notice if somebody re-added the `10.0.0.0/16` rule for convenience.
- **No document in `policies/` contains an unexpanded variable** - the silent heredoc bug, which has
  now had ten opportunities to appear in this laboratory alone.

And, as in every lab, the environment block comes first: a script that verifies only its own resources
passes right up until the restart that deletes them.

### 9.2 Build `scripts/utilities/verify-lab-09.sh`

**Run from**

```text
aws-floci-course/
```

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

**The expected count is `PASS=50  FAIL=0`.**

Known benign failures, which you record rather than fight:

| Check | Benign cause |
| --- | --- |
| `usms-deploy-role HAS a permissions boundary` | Some builds accept `--permissions-boundary` on `create-role` and do not store it. Confirm with `get-role --output json` and record it |
| `the boundary is attached to NOTHING` | Some builds do not populate `AttachmentCount` and return `None`. Confirm with `list-entities-for-policy` and record it |
| `usms-web-01 requires IMDSv2` | Some builds ignore `modify-instance-metadata-options`. Step 11's Floci note covers it |
| `it explicitly DENIES s3:PutObject` | Only if your build's `get-policy-version` returns the document URL-encoded rather than as JSON. Decode it with `python3 -c "import urllib.parse,sys;print(urllib.parse.unquote(sys.stdin.read()))"` and re-check by hand |
| `usms-app-sg has NO CIDR source on tcp/22` | **Not benign.** Step 16 part 3 did not remove the old rule. Go and do it |
| any check under `The negatives that must stay true` | **Not benign, and the most serious kind.** Something that was unreachable is now reachable |

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

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

**Run from**

```text
aws-floci-course/
```

````bash
cat > scripts/cleanup/lab-09-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Reverses Lab 09, dependencies first.
# Order: detach and delete roles -> delete policies -> restore the rules this lab changed.
# Run FIRST of the teardown scripts. See Lab 09 Section 9.3.
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

**What to look for:** the words `syntax OK - do NOT run it`. `bash -n` parses a script without
executing a single command, and it is the only safe way to check a destructive one.

The order is the lesson again, and three steps in it are dependencies the APIs enforce:

1. **Detach policies before deleting roles.** `delete-role` fails with `DeleteConflict` while any
   policy is attached, and the message names the role rather than explaining the dependency.
2. **Remove the permissions boundary before deleting the role.** A boundary is a second attachment and
   is subject to the same rule.
3. **Delete non-default policy versions before deleting a policy.** `delete-policy` refuses while more
   than one version exists, and `Versions[?!IsDefaultVersion]` is the JMESPath for "every version that
   is not the default" - note the `!` negating a boolean field, which is a form this course has not
   used before.
4. **Restore the security group rules last**, and restore the referencing rule before deleting the
   referenced group, because `delete-security-group` fails with `DependencyViolation` while another
   group's rule names it.

Two things are deliberately **not** undone, and the script says so in its own banner: the access key
rotation, because the old key no longer exists anywhere and re-creating one would be a new secret
rather than an undo; and the IMDSv2 requirement, because there is no scenario in which reverting to
IMDSv1 is the right thing to do. **A teardown script that undoes a security improvement is a teardown
script that leaves the account worse than it found it.**

---

## 10. Checkpoints

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

## 11. Troubleshooting

??? danger "`MalformedPolicyDocument` when creating a policy or a role"
    Almost always an unexpanded shell variable, or an expanded one that should not have been. Look at
    the document before looking at anything else:

    ```bash
    grep -n '\$' policies/*.json
    python3 -m json.tool policies/<the-one-that-failed>.json
    ```

    If the file contains the literal text `${USMS_ACCOUNT_ID}`, you used `<< 'EOF'` where Step 7 or
    Step 8 calls for `<< EOF`. If it contains an empty string where an ARN should be, the variable was
    unset - re-source `configs/lab-01.env`.

    The third case is the awkward one: a document that legitimately contains an IAM variable such as
    `${aws:username}` written in an unquoted heredoc. Bash aborts with `bad substitution`. Escape it
    as `\${aws:username}`, as Step 7's warning describes.

??? danger "`NoSuchEntity` when the role plainly exists"
    Check the spelling of the role **name**, not its ARN. `aws iam get-role --role-name` takes a bare
    name and rejects an ARN with exactly this error, which reads as though the role is missing:

    ```bash
    aws iam list-roles --query 'Roles[].RoleName' --output text | tr '\t' '\n' | sort
    ```

    The same trap applies to `--policy-arn`, which takes the opposite: an ARN and never a name.

??? danger "`DeleteConflict` when deleting a role"
    A role with a policy attached, an instance profile referencing it, or a permissions boundary set
    cannot be deleted. Find out which:

    ```bash
    aws iam list-attached-role-policies --role-name <role>
    aws iam list-role-policies --role-name <role>
    aws iam get-role --role-name <role> --query 'Role.PermissionsBoundary'
    aws iam list-instance-profiles-for-role --role-name <role>
    ```

    Detach everything, remove the boundary with `delete-role-permissions-boundary`, then delete. That
    is the order in `scripts/cleanup/lab-09-cleanup.sh`.

??? danger "`DeleteConflict` when deleting a policy"
    Either it is still attached to something, or it has more than one version.

    ```bash
    aws iam list-entities-for-policy --policy-arn <arn>
    aws iam list-policy-versions --policy-arn <arn> --query 'Versions[].[VersionId,IsDefaultVersion]' --output text
    ```

    Delete every non-default version first. A policy can hold five versions and refuses deletion until
    exactly one remains.

??? danger "The trust policy update succeeded and the condition is not there"
    `update-assume-role-policy` replaces the **whole document**. If your document had a syntax error
    that IAM tolerated - a `Condition` block nested one level too deep, for instance - the call
    succeeds and the condition is silently in the wrong place.

    ```bash
    aws iam get-role --role-name usms-ecs-task-role \
      --query 'Role.AssumeRolePolicyDocument' --output json | python3 -m json.tool
    ```

    `Condition` is a sibling of `Effect`, `Principal` and `Action`, **inside** a statement. If it is
    inside `Principal`, or at the top level next to `Version`, it does nothing and IAM will not tell
    you.

??? danger "`InvalidPermission.NotFound` when revoking an egress rule"
    The permission you described does not exactly match the one that exists. The default egress rule
    is protocol `-1` with one `IpRanges` entry of `0.0.0.0/0` and **no** port fields; adding
    `"FromPort": 0` to the document makes it a different permission that matches nothing.

    Read what is actually there, then revoke by rule ID instead, which cannot be ambiguous:

    ```bash
    aws ec2 describe-security-group-rules --filters "Name=group-id,Values=$USMS_ENROLMENT_SG" \
      --query 'SecurityGroupRules[?IsEgress==`true`].[SecurityGroupRuleId,IpProtocol,CidrIpv4]' \
      --output text

    aws ec2 revoke-security-group-egress --group-id "$USMS_ENROLMENT_SG" \
      --security-group-rule-ids sgr-xxxxxxxxxxxx
    ```

??? danger "A security group now has no egress rules at all"
    You revoked the default before authorising the replacement, or the authorise failed silently.
    A group with an empty egress list denies **all** outbound traffic - which on real AWS means a
    Fargate task that cannot pull its image and a service that never stabilises.

    Put it back immediately, then redo the step in the right order:

    ```bash
    aws ec2 authorize-security-group-egress --group-id <sg> \
      --ip-permissions file://policies/usms-egress-allow-all.json
    ```

    That document exists for exactly this moment, which is why Step 13 wrote it before touching
    anything.

??? danger "`InvalidGroup.NotFound` when writing an egress rule that names a group"
    `$USMS_ENROLMENT_SG` or `$BASTION_SG` was empty when the document was written. Check the file:

    ```bash
    cat policies/usms-alb-sg-egress.json
    ```

    A `GroupId` of `""` produces this error, and the message names an invalid group rather than an
    empty variable. Re-source `configs/lab-04.env` and rewrite the document.

??? danger "`aws sts get-caller-identity --profile usms-dev` fails with `InvalidClientTokenId`"
    Step 10's rotation went wrong. Work out where:

    ```bash
    aws configure get aws_access_key_id --profile usms-dev
    aws iam list-access-keys --user-name usms-dev-01 \
      --query 'AccessKeyMetadata[].[AccessKeyId,Status]' --output text
    ```

    If the profile's key is not in the list, the profile points at a deleted key - repoint it from
    `outputs/usms-dev-01-access-key-new.json`. If the key is listed as `Inactive`, reactivate it:

    ```bash
    aws iam update-access-key --user-name usms-dev-01 --access-key-id <id> --status Active
    ```

    If `outputs/usms-dev-01-access-key-new.json` is gone as well, the secret is unrecoverable. Delete
    both keys and create one fresh, following Step 10 from part 2.

??? danger "`LimitExceeded` when creating an access key"
    `usms-dev-01` already has two. That is the IAM maximum and it exists to make the four-step
    rotation possible. Finish the previous rotation - deactivate and delete the older key - before
    starting another.

    ```bash
    aws iam list-access-keys --user-name usms-dev-01 \
      --query 'AccessKeyMetadata[].[AccessKeyId,Status,CreateDate]' --output text
    ```

??? danger "`usms-iam-audit.sh` reports `no inventory` and exits 2"
    It reads `outputs/lab-09-identity-inventory.json`, which Step 4 part 2 writes. Run that first, or
    pass a path:

    ```bash
    ./scripts/utilities/usms-iam-audit.sh outputs/lab-09-identity-inventory.json
    ```

    If the inventory exists but is empty or `[]`, `iam list-roles` returned nothing - check
    `./scripts/utilities/whoami.sh` before assuming the script is at fault.

??? danger "`usms-sg-audit.sh` prints group IDs instead of names"
    A group in the VPC has no `GroupName` in the API response, which happens on some builds for the
    default group. It is cosmetic. If it happens for a group you created, the group was created
    without `--group-name`, which is not possible through the CLI - so check you are looking at the
    VPC you think you are.

??? danger "`An error occurred (NoCredentials)` or a suggestion to run `aws login`"
    Do **not** run `aws login`. It begins an interactive sign-in to **real AWS**, and this course's
    entire safety model rests on never touching a real account.

    In this terminal, right now:

    ```bash
    cd ~/aws-floci-course && source configs/course.env && ./scripts/utilities/whoami.sh
    ```

    Permanently: this is Errata 01, and the loader belongs in the startup file your **login** shell
    reads.

    In this laboratory there is a second possibility worth checking before you blame the shell: Step 9
    exported three environment credentials, and if part 4 never ran they are still set and may have
    expired. `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN` and try again.

??? danger "Everything is gone after a restart"
    Storage mode, as always.

    ```bash
    ./scripts/utilities/floci-storage-check.sh
    ```

    If it reports `FLOCI_STORAGE_MODE=memory`, a stray `floci start` has replaced the Compose
    container. The work is not recoverable - restore from the snapshot you took at the end of Lab 06,
    and this time confirm the storage check before building anything.

---

## 12. Floci vs Real AWS

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

### 12.1 What you actually observed in this lab

```text
OBSERVABLE - you saw this happen
  every role's trust policy and every policy document, read out of the API
  a systematic finding: four roles with the same unconditioned service trust
  a trust policy replaced, with the principal unchanged and a condition added
  a permissions boundary stored in a role's second policy slot
  a policy with an attachment count of zero, deliberately
  a session policy accepted by assume-role, and its intersection computed on paper
  two access keys existing at once, one Inactive, then one
  the default allow-all egress rule, on five groups, none of which you wrote
  three of those replaced with rules you wrote, one naming another security group
  an SSH rule whose source changed from a /16 to a group
  a reachability matrix computed from rules alone
  five independent controls on usms-db-01, and one on usms-enrolment-sg
  all of it surviving a container restart, with every identifier re-derived

CONCEPTUAL - you reasoned about it, you did not see it
  any policy being enforced, ever
  a condition on a trust policy preventing an assume-role
  a permissions boundary capping anything
  a session policy denying anything
  iam:PassRole refusing to pass a role
  a security group dropping a packet, inbound or outbound
  IMDSv2 refusing an untokened request
  the SSRF attack the token requirement prevents
  a prefix list keeping S3 traffic on the AWS network
  the cost of any of it
```

If your Step 3 probe put you on path A, `simulate-principal-policy` moves one line from the second list
to the first. Say in your report which list each item ended up in **for you**. Claiming to have
observed something you reasoned about is worth negative marks, and Section 14 checks it.

### 12.2 Where Floci is nicer than reality, which makes it a trap

- **IAM changes take effect instantly.** Real IAM is eventually consistent: a role created and
  immediately assumed can fail, a policy attached and immediately relied on can be a second behind,
  and code written against Floci's timing has a race condition in it. The standard mitigation is a
  retry with backoff around the first use of a newly created identity, and every mature deployment
  tool has one.
- **A wrong policy costs nothing.** On a real account, an over-permissive policy is a finding in a
  security review, an over-restrictive one is an outage, and both are discovered by someone else.
  Here, both are invisible. That is why every proof in this lab is a proof about a document.
- **No quotas.** A security group holds 60 rules by default and an interface can carry 5 groups. A
  team that solves every problem by adding a rule discovers the first limit at the worst moment, with
  a `RulesPerSecurityGroupLimitExceeded` in the middle of a deployment.
- **No cost.** Interface endpoints - the correct fix for Step 13's wide HTTPS rule - are billed per
  hour per Availability Zone, per service. Doing it properly for ECR, Logs and STS across two zones is
  six endpoints, and the security improvement has a price that has to be argued for.
- **No CloudTrail.** Every claim in this lab about *who changed what* is unverifiable here. On a real
  account, the first question after any security finding is "when did this change and who changed it",
  and the answer takes about ninety seconds. Without it, a security review is a photograph rather than
  a history.

### 12.3 Two kinds of proof, and why one of them is not a compromise

This laboratory could not test a single one of its controls, and that is worth confronting rather than
apologising for.

There are exactly two ways to establish that a control works:

```text
DEMONSTRATION   do the thing; watch it be refused.
                Proves: this specific action, by this principal, on this resource, right now.
                Cannot prove: that nothing ELSE is permitted.

REVIEW          read the configuration; reason about what it permits.
                Proves: what the whole document permits, including cases nobody thought to test.
                Cannot prove: that the system behaves as its configuration says.
```

A security claim is almost always a claim about what *cannot* happen, and demonstration cannot
establish those, because there is no finite set of failed attempts that adds up to "and nothing else".
The claim "only the load balancer can reach the enrolment tasks" is a claim about every other thing in
the account, including the ones that do not exist yet.

So real security review is mostly reading, on real AWS as much as here - and the tooling reflects it.
`simulate-principal-policy` reads. IAM Access Analyzer reads. Every static analysis tool in this space
reads. What testing adds is the second half of the pair: confidence that the *implementation* matches
the configuration, which is AWS's job rather than yours.

What Floci actually costs you, then, is not the ability to review. It is the feedback loop that
catches a document that is malformed rather than mistaken - a condition nested one level too deep, a
resource ARN with a typo. On real AWS a bad policy fails loudly the first time something uses it. Here
it does not, which is why Section 9's script asserts on document *structure* and Step 7's verification
compares principals before and after.

State this in your report. Section 14's viva asks you to defend the methodology, not just the findings.

### 12.4 One thing this lab is *not*

Nothing in this lab is monitoring. Every control here is preventive: it stops something from being
permitted. Not one of them tells you when somebody tries.

The detective half of the same job is CloudTrail - which records every API call and would have told
you who removed a rule and when - plus CloudWatch alarms on the events that matter, plus GuardDuty for
behavioural findings. Floci provides none of them, the CloudWatch laboratory provides the second, and
the first two are `Conceptual / Real AWS` throughout this course.

If you can say, in one sentence, what a preventive control and a detective control each give you that
the other cannot, you have the distinction this section exists for. Exercise 4's fourth bullet asks for
it in writing, and the CloudWatch laboratory is where the detective half stops being conceptual.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-09-security/exercises.md`. Take screenshots into
`screenshots/` where an exercise asks for evidence.

### Exercise 1 - Basic: finish the egress work on the web tier

**Requirements**

Steps 13, 14 and 15 wrote egress rules for three security groups. `usms-app-sg` still carries the
default allow-all rule, and it is the hardest of the four because `usms-web-01` legitimately needs
more than the others.

Work out what it needs from the architecture, write the document, authorise it, revoke the default,
and prove the result.

Specifically, the web instance must still be able to:

1. reach S3 for Lab 10's transcripts, through Lab 02's gateway endpoint,
2. reach AWS service endpoints over HTTPS, including STS for its instance profile credentials,
3. reach the enrolment API - which, since Lab 05, means the load balancer and not the tasks,
4. reach the database tier on PostgreSQL,
5. resolve names, which needs a rule you will have to reason about rather than copy.

**Constraints**

- The document lives in `policies/usms-app-sg-egress.json` and is written with the correct heredoc
  quoting for its contents. Say in one sentence which you chose and why.
- Requirement 3 must be expressed as a **group reference**, not a CIDR. Work out which group.
- Requirement 5 needs **two** rules, and the ports and protocols are not both what you would guess.
  State the destination you chose and justify it against Lab 02's CIDR interlude.
- Authorise before you revoke, as Steps 13 to 16 did, and say why in one sentence.
- Every rule carries a `Description`.
- Do **not** touch `usms-app-sg`'s ingress rules. Exercise 4 argues about those.

**Expected outcome**

`usms-sg-audit.sh` showing `usms-app-sg` with written egress and no default allow-all rule; the
reachability matrix showing the web tier's outbound destinations; and
`./scripts/utilities/verify-lab-09.sh` still reporting `FAIL=0`.

Then do the same reasoning, and reach the opposite conclusion, for `usms-bastion-sg`: say in two
sentences why a jump host's egress rule is different in kind from every other group in this
architecture, and what its correct destination is.

**Hints**

Requirement 5 is the interesting one. The Amazon-provided resolver is at the second address in the VPC
CIDR - Lab 02's interlude lists the five reserved addresses and says what each is for. DNS uses UDP
first and falls back to TCP for large responses, and a rule for only one of the two produces
intermittent failures on exactly the queries that matter.

Requirement 2 has a subtlety worth noticing: `usms-web-01` obtains its credentials from the metadata
service at `169.254.169.254`, which is **link-local** and is not subject to security group rules at
all. Say in one sentence why not.

---

### Exercise 2 - Intermediate: the break-glass role, and the two findings this lab left open

**Requirements**

Two pieces of work, and the second is the more interesting.

**Part A - a break-glass role.** Create `usms-breakglass-role`, the identity somebody assumes during
an incident when the normal path is unavailable. It must:

1. be assumable only by `usms-admin-01`,
2. require multi-factor authentication, using the `aws:MultiFactorAuthPresent` condition key,
3. require an external identifier, using `sts:ExternalId`, so that assuming it is deliberate rather
   than accidental,
4. have the shortest maximum session duration IAM allows,
5. carry a permissions boundary - `USMSPermissionsBoundary` or one of your own,
6. and grant, through an identity policy you write, exactly the permissions needed to stop a runaway
   scaling policy: the Application Auto Scaling calls Lab 06 used to suspend scaling, and nothing
   else.

**Part B - close, or formally accept, the two IAM findings this lab left open.** Step 5's audit
reported four unconditioned service trust policies and Step 7 fixed one. For each of the remaining
three - `usms-ec2-app-role`, `usms-ecs-exec-role`, `usms-lambda-exec-role` - decide and justify one of:

- **Fix it**, with the correct condition keys for that service. Two of the three can be fixed and the
  documentation says which keys each service sends.
- **Accept it**, with a written reason naming what the service does instead and what compensating
  control exists.

Then update `scripts/utilities/usms-iam-audit.sh` so that a formally accepted finding is reported as
`ACCEPTED` rather than `HIGH`, reading the accepted list from a file rather than from a list hard-coded
in the script.

**Constraints**

- Part A's policy must not use a wildcard action. Look up the exact operation names Lab 06 used.
- Part A's trust policy must have **both** conditions in one `Condition` block, and you must be able to
  say whether they combine with AND or with OR - and why that is not a matter of opinion.
- Part B's accepted-findings file must be committed and must contain a reason per entry. A file of
  bare identifiers is a suppression list, not an acceptance record, and the difference is the whole
  point.
- After your change, `usms-iam-audit.sh` must still exit 1 if any unaccepted HIGH finding remains.

**Expected outcome**

A role that cannot be assumed casually, a policy narrow enough to read in ten seconds, and an audit
script whose output is a list of decisions rather than a list of observations.

**Hints**

For part A condition 3, `sts:ExternalId` is normally a cross-account control, and using it here is a
slight repurposing - say so, and say what it buys you in a single account.

For part B, the two services that support source conditions are documented under "cross-service
confused deputy prevention" in each service's own security chapter. The one that does not is the one
whose credentials arrive through a metadata service rather than through `sts:AssumeRole` on your
behalf - which is a hint about *why* it cannot, and Step 11 is about the compensating control.

---

### Exercise 3 - Problem solving: the exposure report

**Requirements**

Write `scripts/utilities/usms-exposure-report.sh`. With no arguments, it examines every elastic
network interface in `usms-vpc` and prints one line per interface classifying it:

```text
usms-web-01        10.0.1.87   52.9.144.17  EXPOSED     igw route + sg allows 80,443 from 0.0.0.0/0
alb node (a)       10.0.1.14   -            EXPOSED     igw route + sg allows 80 from 0.0.0.0/0
usms-db-01         10.0.3.42   -            ISOLATED    no igw route on subnet
enrolment task     10.0.3.117  -            ISOLATED    no igw route on subnet
usms-nat           10.0.1.7    3.221.44.9   EXPOSED     igw route, but no ingress rule at all
```

The verdict must be **computed** from the interface's subnet's route table, its public address, and
its security groups' ingress rules - never from a name, a tag or a description.

**Constraints**

- Runs correctly from any directory. Resolve `configs/` from `${BASH_SOURCE[0]}`, as every script in
  this course does.
- Takes no arguments and hard-codes no resource ID.
- Must handle: an interface with no security group in the report's cache, an interface with no
  description, a subnet with no explicit route table association, and an instance that has been
  terminated but whose interface still lingers.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.
- The last row of the example above is the interesting case: an interface in a public subnet with a
  public address and **no ingress rule at all**. Decide what verdict that deserves, implement it, and
  defend the choice in a comment. There is more than one defensible answer.
- Also write the machine-readable form to `outputs/lab-09-exposure.json`.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-09-security/`. Correct output
before and after Exercise 1 changes egress, which it must not depend on at all - and if your report
changes when only egress changed, you have a bug worth understanding.

**Hints**

`aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=..."` returns everything at once,
including the load balancer's interfaces and every Fargate task's, each with a `Description` that tells
you what created it and a `Groups` list. Four levels of nesting after that - interface to subnet,
subnet to route table, interface to groups, groups to rules - which is where the design question is:
how much do you shell out for, and where do you switch to `python3` over one JSON document?

Step 17's matrix answers half of this for security groups. The half it does not answer is routing, and
Section 12.1 of this document says so explicitly. This exercise is the tool that models both axes.

---

### Exercise 4 - Challenge: the security review, written for someone else to act on

**Requirements**

The university's information security officer, who signed off on Lab 05's load balancer, writes:

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

Produce a written review in `labs/lab-09-security/exercises.md` covering:

- **The second front door.** Argue it properly. What is `usms-app-sg`'s ingress for, what has changed
  since Lab 02 Step 14 wrote it, and what would putting the web tier behind the existing load balancer
  actually involve - naming the target group, the listener rule and the security group change. Then
  argue the other side in two sentences, because there is a real case for leaving it.
- **What egress control bought.** Name three specific attacker behaviours that Steps 13 to 15 now
  prevent and two that they do not. For the two, name the control that would - by service, with a
  citation - and say roughly what it costs.
- **The transcripts access list**, as a table: every principal, how it obtains access, whether it can
  read, write or both, and which document grants it. Then answer the officer's real question, which is
  the last clause: **how do you know the list is complete?** Say which API call you would run on a real
  account to enumerate every principal with access to one bucket, why this course cannot run it, and
  what you did instead.
- **Detection.** Name the AWS services that would tell you a security group changed, that a policy was
  attached, or that a role was assumed from an unusual place. Say which of them are free, which are
  not, and what you would look at first on the morning after an incident - in order, with a reason for
  the order.

Then implement only one thing: the **paper** design for the web tier's move behind the load balancer,
as a numbered sequence of commands with the four-line danger admonition on each destructive one. Do
not run them.

**Constraints**

- Every claim about a cost has a citation. "Some money" earns nothing.
- Every claim about what a control prevents names the attacker behaviour, not the technology.
- The transcripts table must be derived from the documents in `policies/` and from
  `outputs/lab-09-identity-inventory.json`, and must include the two roles that carry
  `USMSStudentDataReadWrite` **and** the one that carries the read-only policy.
- The detection section must distinguish preventive from detective controls, per Section 12.4.

**Expected outcome**

A review an information security officer could take to a committee, and a junior engineer could
implement, without asking you a single question.

**Hints**

For the second bullet, the honest answer to "what does egress control not prevent" is in Step 15's own
text, and it is the one the vendors do not volunteer.

For the third bullet, the call you cannot run here is the one that answers "who has access to this
resource" from the resource's side rather than the principal's. Search the IAM Access Analyzer
documentation for what it does with a bucket, and note that the answer involves a kind of policy this
course has not yet written - which is Exercise 5's subject.

---

### Exercise 5 - Integration: the bucket policy the S3 configuration lab will apply

**Requirements**

Every policy in this course so far has been an **identity** policy: attached to a principal, saying
what that principal may do. Lab 10 creates `usms-student-data`, and a bucket can carry a policy of its
own - a **resource** policy, attached to the resource, saying who may do what to it.

Step 3's interlude listed both, and rule 6 of the evaluation order is where the resource policy enters.
This exercise writes the one the (still unwritten) S3 configuration lab will apply, and derives it from
what already exists rather than inventing it.

Specifically:

1. Write `scripts/utilities/usms-bucket-policy-draft.sh`, which reads
   `outputs/lab-09-identity-inventory.json` and the three transcripts policies out of the API, works
   out **every role ARN that is granted any `s3:` action on `usms-student-data`**, and emits a bucket
   policy draft to `outputs/lab-09-bucket-policy-draft.json` containing:
   - a statement allowing those principals the actions their identity policies already name - no more,
   - a statement denying **every** principal any action on the bucket when
     `aws:SecureTransport` is `false`, so that a plaintext request is refused whoever makes it,
   - a statement denying every principal other than those roles and the account root.
2. Validate the draft as JSON, and check three properties mechanically: that every `Principal` in it
   is an ARN rather than `"*"`, that the `Deny` on insecure transport applies to `"Principal": "*"`,
   and that the bucket ARN appears in both its forms - with and without `/*`.
3. Write `outputs/lab-09-lab10-readiness.txt` containing, each on its own labelled line: the exact
   bucket name, read from Lab 01's policy document rather than typed; the three policy names that
   reference it; each of their attached role ARNs; the count of principals in your draft; and one
   sentence naming what will change, and for which principals, at the moment Lab 10 runs
   `create-bucket`.
4. Append `USMS_BUCKET_POLICY_DRAFT` to `configs/lab-09.env` with the path to the draft, and state the
   new export count.
5. Explain, in three sentences in `exercises.md`, the difference between the `Deny` in your bucket
   policy and the `Deny` in `USMSStudentDataReadOnly` - specifically, whose actions each one can stop,
   and which of the two would still apply to a principal in a **different AWS account**.

**Constraints**

- The script must derive the bucket name from a policy document. Typing `usms-student-data` anywhere
  in it fails the exercise, because the whole point is that the name has been in a policy since Lab 01
  and the bucket is what is missing.
- It must work whether or not the bucket exists. It writes a draft; it applies nothing.
- No script you write may contain, read or reference an access key.
- Use `python3` for the JSON, and shell parameter expansion for at least one string operation, saying
  in a comment why that one was better done in shell.

**Expected outcome**

A committed script, a valid bucket policy draft whose principals were computed rather than typed, and
a readiness file that lets a reader validate the draft against the bucket, or apply it, without opening
this document.

**Lab 10 reads this.** It validates the draft's ARNs against the bucket it creates; actually applying
the draft as the bucket's resource policy remains the (still unwritten) S3 configuration lab's job. The
sentence in point 3 is the one Lab 10 is built around: the identity chains resolve the moment it runs
`create-bucket`, and not one of them has to be modified.

**Hints**

`aws iam list-entities-for-policy` gives you the roles for one policy. Doing it for three policies and
merging the results is the whole of point 1's first half.

For point 5, the distinction is about **where** each policy lives and therefore whose requests it is
consulted on. An identity policy in your account is never consulted for a principal in someone else's;
a resource policy on your bucket always is. That is why a resource policy is the only way to deny
something you do not administer, and it is why every serious S3 configuration has one.

---

## 14. Lab Assessment Checklist

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

## 15. Review Questions

Answer in prose, in your own words, in `notes/lab-09-notes.md`. No command output - these ask whether
you understood, not whether you typed.

1. This laboratory changed a great many things about what the USMS system is permitted to do, and Step
   18 proved that five verification scripts written before it still report exactly what they reported
   before. Explain in a full paragraph why that is a strong result and not a trivial one, and describe
   a security change - one you could plausibly have made in this lab - that would have broken one of
   those scripts. Say what you would have done about it.

2. A colleague attaches `USMSPermissionsBoundary` to `usms-deploy-role` as an ordinary policy, with
   `attach-role-policy`, reasoning that it allows the same actions so the effect must be the same.
   Describe precisely what changes about that role's effective permissions, in both directions. Then
   say what would have to happen for their version to become dangerous, and name the check in Section 9
   that catches it.

3. Ingress rules and egress rules are both security group rules and they protect against different
   things. Describe a concrete incident on the USMS system in which every ingress rule is correct and
   the outcome is still a data breach, and say which of Steps 13 to 15 would have narrowed it and by
   how much. Then name what would have prevented it entirely and why this course cannot build that.

4. `usms-ecs-task-role` and `usms-transcripts-reader-role` have identical trust policies and different
   permissions policies. `usms-deploy-role` has a different trust policy and a permissions boundary.
   For each of the three, say what would happen if an attacker obtained the ability to call
   `sts:AssumeRole` for that role from a machine they control - and explain why the answers are
   different.

5. Step 17 listed five independent controls that make `usms-db-01` unreachable from the internet, and
   identified `usms-enrolment-sg` as protected by a single ingress rule. Explain why "five controls" is
   not simply five times better than "one control", using the specific failure modes of the controls
   involved. Then say whether the enrolment tasks are genuinely less well protected than the database
   instance, and justify your answer against what Section 12.1 says the reachability matrix models.

6. Step 10's rotation had four steps and could have had two. Explain what each of the two extra steps
   protects against, and describe the incident that each one would have prevented. Then explain why
   this course's use of a long-lived access key at all is a compromise, and say what a real system
   would do instead - for a human, and for a workload, which are different answers.

7. This laboratory could not demonstrate that a single one of its controls works. Argue either that
   the review methodology in Section 12.3 is an adequate substitute for testing, or that it is not.
   Whichever side you take, name one specific class of defect that reading a policy catches and testing
   would not, and one that testing catches and reading would not. Then say which of the two you would
   want first on a system holding student transcripts.

---

## 16. What We Built

### 16.1 Reflection

Six laboratories built a system and this one read it back.

The idea to keep is **two axes, evaluated independently, both required**. Almost every confusing
access-control incident in a cloud system is a case of somebody debugging the wrong one - adding IAM
permissions to fix a connection that hangs, or opening a firewall to fix an `AccessDenied`. The
heuristic from Step 3's interlude is worth more than any diagram in this document: an error message
means IAM; a timeout means the network. Say it to yourself the next time something does not work and
you will save an hour.

The second idea is that **the interesting controls are the ones nobody wrote**. Five security groups
carried an allow-all egress rule created by AWS on your behalf. One SSH rule, written in Lab 02 before
Fargate tasks existed, quietly grew to permit every task in the architecture to reach the web server
on port 22. Four trust policies had no conditions because the `create-role` examples in every tutorial
have none. Not one of those was a mistake anybody made; every one of them was a default that outlived
the assumption behind it. **Reviewing a system means reading what is there, not what somebody
decided.**

The third is about proof, and it is the sharpest version of a theme this course has returned to since
Lab 01. Every previous laboratory could, in the end, point at something: a route table read back, a
target moving from `initial` to `healthy`, a `desiredCount` moved by something other than you. This
one could point at nothing, because a security control's whole job is that something does not happen,
and Floci does not enforce a single one of them. So every proof here was a proof about a document - and
Section 12.3 argues that this is not a compromise forced by the emulator but the normal condition of
security work. You cannot test your way to "and nothing else". You read, you reason, and then you
write the reasoning into a script so that the next person inherits the conclusion rather than the
argument.

The fourth is smaller and more practical. Steps 9, 12, 13 and 16 all did the same thing in different
services: **build the new path, prove it, then remove the old one.** Authorise the egress rule before
revoking allow-all. Add the bastion SSH rule before removing the `/16` one. Create the new access key,
move the consumer, deactivate, and only then delete. Lab 05 called it a cutover and this lab did it
three more times, which should now feel less like a procedure and more like the obvious way to change
anything that something depends on.

And one connection worth naming out loud, because it closes something Lab 01 opened. Lab 01 wrote
`USMSStudentDataReadWrite` as an exercise in least privilege for a bucket that did not exist. Lab 03
attached it to an instance, Lab 04 attached it unchanged to a task role, and nobody asked whether both
workloads needed all three verbs. Step 6 asked. **The policy was as least-privilege as it could have
been when it was written, and stopped being so the moment a second workload with different needs
picked it up.** Least privilege is not a property a policy has. It is a property of the relationship
between a policy and a workload, and it decays whenever either one changes.

### 16.2 KEEP vs CLEAN UP

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

Keep `outputs/lab-09-identity-inventory.json`, `outputs/lab-09-iam-findings.txt`,
`outputs/lab-09-sg-findings-before.txt`, `outputs/lab-09-reachability.txt` and
`outputs/lab-09-negative-proof.txt` until Exercise 5 and your report are both finished. They are
git-ignored, so they will not be committed either way - but they are the evidence for every claim in
your review, and re-generating them after a later lab has changed something produces a different
document.

Two entries deserve their own sentence.

`USMSPermissionsBoundary` is in the KEEP column with an instruction not to tidy it up. It has an
attachment count of zero and looks exactly like an orphan. It is the one control preventing
`usms-deploy-role` from escalating, and deleting it would silently remove that ceiling. Put a comment
to that effect wherever your team lists unattached policies.

`outputs/usms-dev-01-access-key.json` - Lab 01's key file - should already be gone, because Step 10
part 5 removed it. Check. A file containing a secret that no longer works is not dangerous, and that
is exactly why it survives for years.

Do **not** run `scripts/cleanup/lab-09-cleanup.sh`, `lab-06-cleanup.sh`, `lab-05-cleanup.sh`,
`lab-04-cleanup.sh`, `lab-03-cleanup.sh` or `lab-02-cleanup.sh`. They are for the end of the course,
in the order given in Section 9.3.

### 16.3 The architecture you now have

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

## 17. Preparation for the Next Lab

Lab 10 - Lambda - creates `usms-student-data`, and it is the moment two policies stop being
hypothetical. `USMSStudentDataReadWrite` was written in Lab 01 and is now attached to three roles -
`usms-ec2-app-role` (Lab 03), `usms-ecs-task-role` (Lab 04), and `usms-eks-node-role` (Lab 07). The
second policy is `USMSStudentDataReadOnly`, which you wrote today.

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

**The connection to state out loud before the next session.** Lab 01 wrote an identity policy for a
bucket that did not exist. Lab 09 wrote a second identity policy for the same non-existent bucket, and
Exercise 5 drafts a **resource** policy for it. Lab 10 runs `create-bucket`, and that is the moment the
two identity policies stop being hypothetical - but the resource policy still waits: applying it is the
(still unwritten) S3 configuration lab's job, not Lab 10's. When that lab finally runs
`put-bucket-policy`, the two kinds of policy will meet for the first time in this course - and the
evaluation order from Step 3's interlude becomes something you can point at rather than recite: rule 5
is the identity policies, rule 6 is the bucket policy, and rule 1 is the explicit `Deny` on insecure
transport that outranks both.

**Before the next session, confirm all six of these:**

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

You want: `FAIL=0` twice; a count of **16** (or 17 after Exercise 5); a `HIGH=` count **lower** than
Step 5's and non-zero, because this lab fixed one of four findings and Exercise 2 handles the rest;
`HIGH=2 MED=3 LOW=1` or thereabouts from the security group audit, with the remaining MED findings
being `usms-app-sg`'s and `usms-bastion-sg`'s egress; and a `3` from the last call.

That last line is the one that will actually stop you in Lab 10. If it reads `1`, something detached
`USMSStudentDataReadWrite` from a role, and Lab 10's central claim - that one `create-bucket` resolves
three chains at once - will be a claim about two.

**Read ahead, five minutes:** find out what an S3 **bucket policy** is and how it differs from an
identity policy, and what `aws:SecureTransport` is. Then find out why an S3 bucket name has to be
globally unique across every AWS account in the world, and what that means for a course in which every
student creates a bucket called `usms-student-data` on their own emulator.

Finally, take a snapshot so that a mistake in Lab 10 is recoverable:

```bash
floci snapshot save lab-09-complete
```

If `floci snapshot` is not available on your build, use the filesystem fallback. Stop Floci first -
archiving a live data directory can capture a half-written file:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-09.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-09.tar.gz
```

The archive lives in your home directory, **outside** the repository, so it is never a commit
candidate.

---

## Appendix A - Command Reference

Every command this lab used, grouped by service.

### IAM - reading

| Command | What it does |
| --- | --- |
| `aws iam list-roles` | Every role, with its trust policy inline in the response |
| `aws iam get-role` | One role: trust policy, max session duration, and `PermissionsBoundary` |
| `aws iam list-users` / `list-groups` | The other two kinds of principal |
| `aws iam list-policies --scope Local` | **Your** policies only. Without the flag you get several hundred AWS managed ones |
| `aws iam get-policy` | A policy's metadata, including which version is the default |
| `aws iam get-policy-version` | The actual document, for a given version |
| `aws iam list-policy-versions` | Every version; a policy holds five and refuses deletion above one |
| `aws iam list-attached-role-policies` | Managed policies on a role |
| `aws iam list-role-policies` / `get-role-policy` | Inline policies on a role |
| `aws iam list-entities-for-policy` | The reverse: given a policy, who carries it |
| `aws iam get-account-authorization-details` | The whole account's IAM in one call. Usually absent on Floci |

### IAM - changing

| Command | What it does |
| --- | --- |
| `aws iam create-policy` | Create a customer managed policy from a document |
| `aws iam create-role --assume-role-policy-document` | Create a role. The document is the **trust** policy |
| `aws iam create-role --permissions-boundary` | Set the ceiling at creation |
| `aws iam put-role-permissions-boundary` | Set it afterwards |
| `aws iam delete-role-permissions-boundary` | Remove it - an action worth denying in the boundary itself |
| `aws iam update-assume-role-policy` | **Replaces** the whole trust policy. Never merges |
| `aws iam attach-role-policy` / `detach-role-policy` | Managed policies on and off a role |
| `aws iam delete-policy-version` / `delete-policy` | Versions first, then the policy |

### IAM - credentials

| Command | What it does |
| --- | --- |
| `aws iam list-access-keys` | Every key for a user, with status and creation date. Maximum two |
| `aws iam create-access-key` | Creates one. The secret is shown **once**; redirect it to a file |
| `aws iam update-access-key --status Inactive` | Deactivate reversibly - step 3 of a four-step rotation |
| `aws iam delete-access-key` | Irreversible. Only after the deactivation has been quiet |
| `aws iam get-access-key-last-used` | When, by what service, in what region. The call that finds dead keys |
| `aws iam get-credential-report` | An account-wide CSV of credential age and MFA state. Real AWS only |

### IAM - evaluating

| Command | What it does |
| --- | --- |
| `aws sts assume-role --policy file://...` | Assume with a **session policy** - a third intersection, set by the caller |
| `aws sts assume-role --duration-seconds` | Shorter than the role's maximum, because a session should be as short as its work |
| `aws sts get-caller-identity` | Who the current credentials say you are |
| `aws iam simulate-principal-policy` | Would this principal be allowed to do this. Usually absent on Floci |
| `aws accessanalyzer list-analyzers` | External-access findings. Real AWS only |

### EC2 - security group rules

| Command | What it does |
| --- | --- |
| `aws ec2 describe-security-groups` | Groups and their rules, with permissions **merged** by protocol and port |
| `aws ec2 describe-security-group-rules` | One object per rule, each with its own ID. The only separable view |
| `aws ec2 authorize-security-group-ingress` | Add inbound rules |
| `aws ec2 revoke-security-group-ingress --security-group-rule-ids` | Remove exactly one rule, unambiguously |
| `aws ec2 authorize-security-group-egress` | Add **outbound** rules - the half nobody writes |
| `aws ec2 revoke-security-group-egress` | Remove one, including the AWS default allow-all |
| `aws ec2 describe-prefix-lists` | AWS-managed prefix lists, including the gateway endpoints' |
| `aws ec2 describe-network-interfaces --filters Name=group-id` | What actually carries a group |

### EC2 - instance metadata

| Command | What it does |
| --- | --- |
| `aws ec2 modify-instance-metadata-options` | `--http-tokens`, `--http-endpoint`, `--http-put-response-hop-limit` |
| `aws ec2 describe-instances --query '...MetadataOptions'` | Read them back; `State` is `applied` when the change has taken |

**The two flags worth memorising**, because they prevent different attacks:

| Flag | Prevents |
| --- | --- |
| `--http-tokens required` | An SSRF bug in the application reading the instance's credentials with a plain `GET` |
| `--http-put-response-hop-limit 1` | A container on the instance reaching the host's metadata service and inheriting its role |

---

## Appendix B - New JMESPath, CLI and policy patterns introduced

Labs 1 to 06 taught `Key[*].Field`, `[A,B]`, `{X:A}`, `[?filter]`, `| [0]`, `sort_by()`, `length()`,
`contains()`, `starts_with()`, `@`, flattening with `[]`, `--filters`, `--generate-cli-skeleton`,
`--cli-input-json`, waiters, boolean and string literals in filters, and expression references. This
lab adds:

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `--scope Local` | Your policies only, not the several hundred AWS managed ones | Step 4 |
| `Policies[?PolicyName=='X'].Arn \| [0]` | Find an ARN by name - the only way in, since IAM's read calls take ARNs | Steps 19, Section 9 |
| `length(Role.AssumeRolePolicyDocument.Statement[0].Condition)` | Count a condition block's keys - a number is more `diff`-stable than an object | Step 18 |
| `AccessKeyMetadata[?AccessKeyId!='X'].AccessKeyId \| [0]` | "The other one", without assuming an ordering | Step 10 |
| `Versions[?!IsDefaultVersion].VersionId` | `!` negating a boolean field inside a filter | Section 9.3 |
| `Routes[?DestinationPrefixListId!=` backtick `null` backtick `]` | Test a field for not-null, with `null` as a JSON literal | Step 13 |
| `length(IpPermissionsEgress[?IpProtocol==` backtick `-1` backtick `])` | Count the AWS default egress rules - zero is the assertion | Steps 15, 18, Section 9 |
| `length(IpPermissions[?FromPort==` backtick `22` backtick `].IpRanges[])` | Count CIDR sources on one port - a negative assertion | Steps 18, Section 9 |
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

---

*Lab 09 complete. Lab 10 - Lambda - creates `usms-student-data`, and three policies written across two
laboratories stop being hypothetical at the same instant. Bring `outputs/lab-09-bucket-policy-draft.json`
with you.*
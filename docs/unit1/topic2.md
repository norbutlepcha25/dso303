# Iam 


### 1.2 What is IAM?

**IAM — Identity and Access Management** — is the AWS service that answers exactly two questions for
every single request that ever reaches AWS:

```text
1. WHO are you?            →  Authentication
2. Are you ALLOWED to do   →  Authorization
   this specific action
   on this specific
   resource?
```

Every other AWS service depends on it. When you run `aws s3 ls`, AWS does not simply list your
buckets — it first identifies you, then asks IAM whether you are permitted to call `s3:ListAllMyBuckets`.
If IAM says no, you get `AccessDenied` and nothing else happens.

### 1.3 Why IAM exists

Before cloud, security was mostly *physical and network based*: the server was in a locked room
behind a firewall. In the cloud there is no locked room. The only thing standing between your
company's data and the internet is **an identity and a policy document**.

IAM exists so that you can express, precisely and in machine-readable form, statements such as:

- "The reporting application may **read** student transcripts but may never **delete** them."
- "Developers may start and stop test servers, but only in the Singapore region."
- "This virtual machine may write to this one storage bucket, and nothing else."

### 1.4 Where IAM is used in real systems

| Real-world situation | IAM feature that solves it |
| --- | --- |
| A new engineer joins the team | An **IAM user** added to an **IAM group** |
| A CI/CD pipeline deploys code | An **IAM role** assumed by the pipeline |
| A server needs to read a storage bucket | An **IAM role** attached to the server via an **instance profile** |
| An auditor needs read-only access to everything | An **AWS managed policy** (`ReadOnlyAccess`) |
| A contractor must only touch one project's resources | A **customer managed policy** scoped by resource ARN |
| Temporary 1-hour access for an emergency | **STS** temporary credentials |

### 1.5 What you will build in this lab

By the end of Lab 1 you will have a complete, working local AWS environment **and** a realistic IAM
foundation for USMS:

- 3 IAM groups (admins, developers, auditors)
- 3 IAM users, each in the correct group
- 3 customer managed policies + 1 AWS managed policy + 1 inline policy
- 3 IAM roles with three different trust policies (EC2, Lambda, human developers)
- 1 instance profile (which Lab 3 will attach to an EC2 instance)
- 1 set of programmatic access keys, handled safely
- A reusable project directory, configuration files and helper scripts

### 1.6 How this lab connects to the rest of the course

```text
LAB 01  IAM          ← you are here. Creates identities + the project skeleton.
   ↓
LAB 02  VPC          ← the developer identity builds the network
   ↓
LAB 03  EC2          ← servers launch using the instance profile created here
   ↓
LAB 04  S3           ← the policies written here finally get enforced against buckets
   ↓
LAB 05+ Lambda / DynamoDB / CloudWatch / SNS / SQS ...
```

!!! warning "Do not delete anything at the end of this lab"
    Almost every resource you create today is **required by later labs**. Section 16 tells you
    exactly what to KEEP and what to CLEAN UP.

---

## 2. Learning Objectives
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

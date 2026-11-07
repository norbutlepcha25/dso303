<!-- teachprep:refined 2026-10-11 -->
# AWS Identity and Access Management (IAM)

## What Is IAM?

**IAM  Identity and Access Management**  is the AWS service that answers exactly two questions for
every single request that ever reaches AWS:

```text
1. WHO are you?            →  Authentication
2. Are you ALLOWED to do   →  Authorization
   this specific action
   on this specific
   resource?
```

Every other AWS service depends on it. When you run `aws s3 ls`, AWS does not simply list your
buckets  it first identifies you, then asks IAM whether you are permitted to call `s3:ListAllMyBuckets`.
If IAM says no, you get `AccessDenied` and nothing else happens.

## Why IAM Exists

- **No locked room in the cloud:** before cloud, security was mostly physical and network based; in AWS the only barrier between your data and the internet is an identity and a policy document.
- **Every request must be checked:** IAM authenticates the caller and authorises each action on each resource, for every API call to every service.
- **Precise, machine-readable rules:** statements such as "the reporting application may read student transcripts but never delete them" become enforceable policy.
- **Scoped by place and resource:** rules such as "developers may start and stop test servers, but only in the Singapore Region" limit actions to approved Regions and resources.
- **Least privilege for machines too:** a virtual machine can be allowed to write to one storage bucket and nothing else, without storing any keys.

## Where IAM Is Used in Real Systems

| Real-world situation | IAM feature that solves it |
| --- | --- |
| A new engineer joins the team | A user in the corporate identity provider, signed in through **IAM Identity Center** (in a single small account, an **IAM user** added to an **IAM group**) |
| A CI/CD pipeline deploys code | An **IAM role** assumed by the pipeline |
| A server needs to read a storage bucket | An **IAM role** attached to the server via an **instance profile** |
| An auditor needs read-only access to everything | An **AWS managed policy** (`ReadOnlyAccess`) |
| A contractor must only touch one project's resources | A **customer managed policy** scoped by resource ARN |
| Temporary 1-hour access for an emergency | **STS** temporary credentials |

See [8.1 AWS Identity and Access Management](../unit8/topic1.md) for the full treatment of identities, policies and policy evaluation, STS, and AWS Organizations.

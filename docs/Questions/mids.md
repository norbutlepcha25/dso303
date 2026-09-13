# DSO303 — Cloud Native Solution Design
## Practice Question Pool

# SECTION A
*Choose the single best answer. Each also asks you to state, in one line, why the distractors fail.*

Q1. 
A developer's IAM user is in a group whose policy allows `s3:*` on all buckets. A separate policy attached directly to the user contains an explicit `Deny` on `s3:DeleteObject` for `arn:aws:s3:::finance-archive/*`. What is the effective permission?

1. The user can delete objects in `finance-archive` because group policies take precedence.
2. The user cannot delete objects in `finance-archive`, but retains all other S3 permissions.
3. The user loses all S3 permissions because conflicting policies invalidate each other.
4. The user can delete objects only if the bucket policy also allows it.

Q2.
An object is uploaded to S3 Standard and a lifecycle rule attempts to transition it to S3 Standard-IA after 10 days. What happens?

1. The object transitions on day 10 as configured.
1. The transition is rejected because Standard-IA enforces a 30-day minimum before transition from Standard.
1. The object transitions but is billed at Standard rates until day 30.
1. The object is transitioned directly to Glacier Deep Archive instead.

Q3. 
Which statement about Network ACL rule evaluation is correct?

1. All rules are evaluated and the most permissive wins.
1. Rules are evaluated in ascending rule-number order and the first match is applied; evaluation then stops.
1. Deny rules are always evaluated before allow rules, regardless of rule number.
1. NACL rules are stateful, so return traffic never needs an explicit rule.

Q4. 
Which EBS volume type cannot be used as a root (boot) volume?

1. gp3
1. io2
1. st1
1. gp2

Q5. 
A workload requires 40,000 sustained IOPS with consistent sub-millisecond latency on a single volume. Which is the appropriate choice?

1. gp3 with provisioned IOPS raised to 40,000
1. io2 (or io2 Block Express) with 40,000 provisioned IOPS
1. st1 sized at 16 TB to obtain throughput credits
1. Three gp3 volumes in a RAID 0 stripe, which is the only supported approach

Q6. 
Which limitation applies to AWS Fargate but not to the ECS EC2 launch type?

1. Tasks cannot be placed in a private subnet.
1. GPU-accelerated tasks and privileged containers are not supported.
1. Tasks cannot use IAM task roles.
1. Tasks cannot be fronted by an Application Load Balancer.

Q7. 
In the subnet `172.31.16.0/20`, how many IP addresses are usable by EC2 instances?

1. 4096
1. 4091
1. 4094
1. 2043

Q8. 
An EC2 instance in a private subnet must call the S3 API. The subnet has no NAT gateway and no internet gateway route. Which mechanism allows the call to succeed?

1. An S3 Gateway VPC endpoint with a route-table entry for the S3 prefix list
1. A public IP assigned to the instance
1. A NACL rule allowing outbound port 443 to `0.0.0.0/0`
1. An S3 bucket policy allowing the instance's private IP

Q9. 
Which pairing of statefulness and scope is correct?

1. Security Group — stateless, subnet level; NACL — stateful, ENI level
1. Security Group — stateful, ENI level; NACL — stateless, subnet level
1. Both stateful at the ENI level, differing only in rule ordering
1. Security Group — stateful, subnet level; NACL — stateless, ENI level

Q10. 
A team wants twelve EC2 instances spread across three Availability Zones to share one POSIX file tree with simultaneous read/write. Which service satisfies this natively?

1. An io2 EBS volume with Multi-Attach enabled
1. Amazon EFS mounted over NFS in all three AZs
1. An S3 bucket mounted with a filesystem driver
1. A gp3 volume snapshotted and restored hourly into each AZ

---

# SECTION B

Q11. 
A university AWS account has 480 IAM users spread across four faculties. Each faculty must have distinct S3 permissions, and users occasionally transfer between faculties. Design the identity structure. Explain why attaching policies directly to users is a poor design here, and state what has to change when a user transfers.

Q12. 
Explain the difference between an IAM user, an IAM group, and an IAM role. For each, give one workload from a cloud-native application where it is the correct construct, and state which of the three cannot be used as a policy principal.

Q13. 
An application running on EC2 needs to read from a DynamoDB table. A junior engineer proposes storing an IAM user's access key and secret in the application's `.env` file. Critique this design on at least three grounds, and describe the mechanism you would use instead, including how the credentials reach the application at runtime.

Q14. 
Study the following policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BucketLevel",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::student-uploads"
    },
    {
      "Sid": "ObjectLevel",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::student-uploads/${aws:username}/*"
    }
  ]
}
```

1. Describe precisely what a user named `dorji` can and cannot do.
1. Explain why the two statements use different `Resource` ARN formats.
1. The user reports that `aws s3 ls s3://student-uploads/dorji/` works but `aws s3 rm` fails. Explain why, and state the minimum change required to permit deletion within the user's own prefix only.

Q15. 
A contractor's account (Account B) must read objects in a bucket owned by your account (Account A) for 90 days. Compare two approaches — a cross-account IAM role assumed via `sts:AssumeRole`, versus a bucket policy granting the contractor's IAM user direct access. Discuss credential lifetime, auditability, and revocation, and recommend one.

Q16. 
Define an IAM permissions boundary. A developer has an identity policy allowing `ec2:*` but a permissions boundary allowing only `ec2:Describe*`. State the effective permissions and explain the evaluation logic in one sentence.

Q17. 
Your organisation requires that no IAM policy in any member account may grant access to services outside the `ap-south-1` and `ap-southeast-1` regions. Explain what mechanism enforces this across accounts and why an identity policy alone is insufficient.


# SECTION C

Q18. 
A media archive holds 40 TB of finished video. Objects are downloaded frequently in the first 30 days, occasionally over the next 11 months, and after that are retained for seven years for compliance with retrieval expected at most once a year (a 12-hour retrieval time is acceptable). Write the lifecycle configuration in words: each transition, the day it fires, and the target storage class. Justify each choice on cost and retrieval characteristics.

Q19. 
Contrast S3 Glacier Instant Retrieval, Glacier Flexible Retrieval, and Glacier Deep Archive across three axes: retrieval time, minimum storage duration, and the access pattern each is designed for. Then state which one is wrong for a dataset queried unpredictably but needing millisecond response, and why.

Q20. 
A team stores 20 million objects averaging 40 KB each and transitions them all to S3 Standard-IA on day 31 to save money. The bill increases. Explain the two S3 billing characteristics that cause this outcome.

Q21. 
Distinguish S3 Standard-IA from S3 One Zone-IA. Give one workload that is appropriate for One Zone-IA and one that is not, with reasoning grounded in durability and availability rather than cost alone.

Q22. 
A public-facing web app must let authenticated students upload assignments directly to S3 without the objects ever being publicly readable and without the application holding long-lived credentials in the browser. Describe the mechanism, the party that generates the credential, and how expiry is controlled.

Q23. 
Explain S3 Versioning and how it interacts with a lifecycle rule. Specifically: if versioning is enabled and an object is deleted, what happens physically, and what lifecycle action reclaims that storage?

Q24. 
Your team enabled S3 Intelligent-Tiering for a bucket containing 5 million objects, most of which are 8 KB thumbnails accessed daily. Explain why this may be a poor fit, referencing the monitoring/automation charge and the object-size threshold below which objects are not tiered.

---

# SECTION D
Q25. 
For each requirement select the storage service and volume type, and justify in one or two lines:

1. The root volume of a lecturer's low-traffic teaching VM, cost being the primary constraint.
1. A 6 TB store for nightly batch log processing with heavy sequential reads, never booted from.
1. A shared `/var/www/uploads` directory for an autoscaling group of web servers in two AZs.
1. A latency-sensitive OLTP database requiring 25,000 provisioned IOPS.
1. Scratch space for a video transcoding job where data loss on instance stop is acceptable and maximum local throughput is wanted.

Q26. 
An EBS volume is attached to an instance in `ap-south-1a`. The instance must be rebuilt in `ap-south-1b` with the same data. Describe the exact sequence of operations. Then state the architectural property of EBS that makes this sequence necessary, and name the AWS service that removes the constraint.

Q27. 
Explain gp2 versus gp3 in terms of how IOPS are obtained. A team migrates a 200 GB gp2 volume to gp3 and reports a performance *drop*. Give the most likely explanation.

Q28. 
Distinguish st1 from sc1. A team chooses st1 for a 100 GB volume and observes throughput far below the advertised maximum. Give two independent reasons this can occur.

Q29. 
Explain EBS Multi-Attach. State the volume types that support it, the Availability Zone constraint, and the critical requirement placed on the filesystem. Explain why mounting ext4 on two instances simultaneously via Multi-Attach corrupts data.

Q30. 
Compare EBS and EFS across five dimensions: attachment model, AZ scope, pricing model, protocol, and typical latency profile. Then give one scenario where using EFS instead of EBS would be an over-engineered and more expensive decision.

Q31. 
An EBS snapshot is described as "incremental". Explain what that means for storage cost and for restore time, and state whether deleting an older snapshot in a chain destroys the ability to restore from a newer one.

# SECTION E
Q32. 
Differentiate the ECS EC2 launch type from the ECS Fargate launch type across: who patches the operating system, how compute capacity scales, the billing unit, and supported network modes.

Q33. 
A department runs 40 microservices. Twelve are steady, always-on, CPU-bound services; the remaining 28 are bursty, event-driven services that idle most of the day. Recommend a launch type for each group and justify the split on cost and operational grounds. State one hybrid mechanism ECS offers to run both in one cluster.

Q34. 
Explain the relationship between an ECS task definition, a task, and a service. Which of the three defines the desired count and performs replacement of unhealthy containers?

Q35. 
Distinguish the ECS task execution role from the ECS task role. A Fargate task fails to start with an image-pull error from ECR; which role is at fault and what permission is missing? A running container then receives `AccessDenied` calling `dynamodb:PutItem`; which role is at fault?

Q36. 
Explain the `awsvpc` network mode. Why is it mandatory for Fargate, and what does it change about how Security Groups are applied compared with `bridge` mode on EC2?

Q37. 
A Fargate task writing temporary transcoded files fails with "no space left on device". Explain the Fargate ephemeral storage model, its default size, how it can be increased, and one architectural alternative that removes the dependence on task-local storage entirely.

# SECTION F 

Q38. 
An application tier in subnet `10.0.10.0/24` must reach a Redis cache in subnet `10.0.20.0/24` on TCP 6379. Security groups are correct on both sides, but connections hang. Both subnets use custom NACLs.

1. Explain the failure in terms of NACL statefulness.
1. Define an ephemeral port and state the range AWS recommends allowing in NACLs.
1. Write the four NACL rules required, giving for each: which NACL it belongs to, direction, protocol, port range, source/destination CIDR, and action.

Q39. 
Compare Security Groups and NACLs on five points: statefulness, scope, rule types supported, evaluation order, and default behaviour of a newly created instance of each. Then state which of the two you would use to block a single abusive IP address from an entire subnet, and why the other cannot do it.

Q40. 
A bastion host in a public subnet accepts SSH from the campus network `202.144.128.0/19` and must SSH into private instances in `10.0.30.0/24`. Write the security group design: name each group, state its inbound rules, and explain how referencing a security group as a source (rather than a CIDR) improves the design.

Q41. 
Explain why a Security Group cannot contain a `Deny` rule, and describe how the same outcome — permitting all of a subnet except one host — must be achieved.

Q42. 
Instances in a private subnet must download OS patches from the internet but must never be reachable from it. Describe the components and route-table entries required. Explain why placing a NAT Gateway in the private subnet itself is a configuration error, and state which subnet it belongs in.

Q43. 
A NACL contains rule 100 `ALLOW TCP 443 from 0.0.0.0/0` and rule 90 `DENY TCP 443 from 203.0.113.7/32`. Traffic arrives from `203.0.113.7`. State the outcome and explain it in terms of NACL evaluation. Now swap the rule numbers and state the new outcome.

Q44. 
Explain what the VPC "implicit deny" at the end of every NACL means, and contrast it with the implicit deny in a Security Group. Then explain why the *default* NACL that AWS creates with a VPC behaves permissively despite that implicit deny.

---

# SECTION G 

Q45. 
For the subnet `10.0.4.0/24`, list the five addresses AWS reserves and state the purpose of each. How many addresses remain assignable to EC2 instances?

Q46. 
Determine the smallest AWS subnet prefix that accommodates each requirement, showing your reasoning:

1. 5 instances
1. 28 instances
1. 60 instances
1. 300 instances
1. 1500 instances

Q47. 
You are allocated the VPC CIDR `10.20.0.0/16`. Design a three-tier VPC across two Availability Zones: public web subnets, private application subnets, and private database subnets. Provide the CIDR for all six subnets, state the usable host count of each, and confirm that none overlap. Leave room for future growth and say how much of the `/16` remains unallocated.

Q48. 
State the smallest and largest subnet prefix lengths AWS permits inside a VPC. Explain why AWS forbids anything smaller than the lower bound, referencing the reserved addresses.

Q49. 
A team proposes VPC CIDR `10.0.0.0/16` for a new VPC that must later be peered with an existing VPC using `10.0.0.0/16`. Explain the problem, and describe two ways to avoid it when designing address space for an organisation with many VPCs.

Q50. 
Given the address `172.16.132.77/26`:

1. Compute the network address, the broadcast address, and the valid host range in standard IPv4 practice.
1. State which of those addresses would additionally be unusable if this were an AWS subnet, and why.
1. State how many EC2 instances could actually be launched in it.


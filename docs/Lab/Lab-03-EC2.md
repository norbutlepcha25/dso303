# Lab 03 - Amazon EC2 and Deploying the USMS Application

## 1. Objectives

- Launch the USMS web server into Lab 2's public subnet with Lab 2's security group and Lab 1's instance profile, from a reviewable `--cli-input-json` request.
- Bootstrap it with user data, prove the user data arrived, and give it a stable Elastic IP.
- Attach an EBS data volume and launch a database-tier instance into the private subnet.
- Prove which address survives a stop/start, that everything survives a Floci restart, and capture an AMI.
- Save the lab's IDs to `configs/lab-03.env` for Lab 4.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [what an EC2 instance is made of](../unit1/topic3.md#what-an-instance-is-made-of) ·
    [EC2 purchasing options](../unit1/topic3.md#purchasing-options) ·
    [instance profiles](../unit8/topic1.md#service-roles-instance-profiles-and-service-linked-roles) ·
    [role sessions and temporary credentials](../unit8/topic1.md#role-sessions-and-temporary-credentials) ·
    [EBS](../unit6/topic1.md#block-storage-with-amazon-ebs) ·
    [instance store versus EBS](../unit6/topic1.md#instance-store-versus-ebs) ·
    [subnets and Availability Zones](../unit1/topic6.md#subnets-and-availability-zones) ·
    [security group referencing](../unit1/topic6.md#security-group-referencing-the-cloud-native-idiom)

---

## 2. Prerequisites

- Lab 1 complete, including `usms-ec2-app-profile` with `usms-ec2-app-role` inside it.
- Lab 2 complete, including Exercise 5 (`usms-private-subnet-b` is needed by Lab 3 Exercise 5).
- `./scripts/utilities/verify-lab-02.sh` reports `FAIL=0`.
- Floci running under Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq`, `openssl`, `curl` and `python3` available:

```bash
for t in jq openssl curl python3; do
  printf '%-10s ' "$t"; command -v "$t" || echo "MISSING"
done
```

You want a path for all four. If one is missing, install it before the session (`sudo apt install jq` or `brew install jq`).

---

## 3. What This Lab Reuses

From Lab 1:

- `usms-ec2-app-profile`: passed to `run-instances` in Step 8; read back off the instance in Step 11.
- `USMSStudentDataReadWrite`: Step 11 traces instance → profile → role → policy.

From Lab 2:

- `usms-public-subnet-a`: Step 8 launches the web server into it, by ID from `configs/lab-02.env`.
- `usms-private-subnet-a`: Step 16 launches the database-tier instance into it.
- `usms-app-sg` / `usms-db-sg`: attached at launch in Steps 8 and 16; read back in Step 17.
- `USMS_AZ_A`: Step 15 creates the EBS volume in the instance's AZ, because it must be.
- `usms-igw` and the public route: what makes Step 14 meaningful.

```text
Created in this lab:
- usms-app-key            EC2 key pair; private key in outputs/, chmod 600, git-ignored
- usms-web-01             web tier instance in usms-public-subnet-a
- usms-web-eip            Elastic IP associated with usms-web-01
- usms-db-01              data tier instance in usms-private-subnet-a
- usms-web-data-vol       8 GiB EBS volume attached to usms-web-01
- usms-web-golden         AMI created from the configured web instance
- labs/lab-03-ec2/user-data.sh
- templates/lab-03-run-instances.json
- configs/lab-03.env
- scripts/utilities/verify-lab-03.sh
- scripts/cleanup/lab-03-cleanup.sh

Required for future labs:
- usms-web-01            -> Lab 04 uploads a transcript from this instance's identity
- usms-ec2-app-profile   -> Lab 04 is where its S3 permissions finally resolve
- usms-web-golden        -> Lab 08 uses it in a launch template for an Auto Scaling group
- usms-db-01             -> Lab 06 replaces it with a managed RDS instance, deliberately
```

---

## 4. What We Are Building

A two-tier USMS deployment. **`usms-web-01`** sits in `usms-public-subnet-a`, serves the student portal on port 80, has an Elastic IP, `usms-app-sg`, and `usms-ec2-app-profile` so it can reach S3 in Lab 4 with no credentials on disk. **`usms-db-01`** sits in `usms-private-subnet-a` with no public address and a security group that accepts PostgreSQL only from the web tier's group. The application is a single nginx page; what matters is that it lands in the right place with the right permissions and firewall, and that you can prove each.

!!! note "Floci Limitation - read this before you start, not after"
    Floci models the EC2 API thoroughly (instances, states, tags, volumes, images, key pairs, Elastic IPs), but the community build does not boot a real operating system, so user data may never execute and `curl` to the instance will usually fail.

    Real AWS boots a real VM, runs your user data as root at first boot, and serves the page.

    Step 14 gives a primary path (try the request) and a fallback (prove every link in the chain). Nothing in this lab or its assessment depends on the request succeeding.

---

## 5. Architecture

![Architecture](image-1.png)

---

## 6. Directory Structure

```text
aws-floci-course/
├── labs/
│   └── lab-03-ec2/
│       ├── README.md                       # this document
│       ├── exercises.md                    # Section 12
│       └── user-data.sh                    # NEW - the bootstrap script
├── configs/
│   └── lab-03.env                          # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-03.sh                # NEW
│   └── cleanup/
│       └── lab-03-cleanup.sh               # NEW
├── templates/
│   └── lab-03-run-instances.json           # NEW - --generate-cli-skeleton output, filled in
└── outputs/
    ├── usms-app-key.pem                    # SECRET - git-ignored, chmod 600
    └── lab-03-*.json                        # command output
```

One new file sits inside the lab folder rather than in a top-level directory: `user-data.sh`. It
belongs to this lab specifically and is not shared, which is the same reason `exercises.md` lives
there.

```bash
cd ~/aws-floci-course
mkdir -p labs/lab-03-ec2
ls -d labs/*
```

> Example output:

```text
labs/lab-01-iam  labs/lab-02-vpc  labs/lab-03-ec2
```

---

## 7. Step-by-Step Implementation

!!! info "Run every command from `aws-floci-course/`"
    All paths are relative to the repository root unless a step says otherwise. If a command reports `No such file or directory`, check `pwd`.

!!! tip "Shell variables die with the terminal"
    Every ID below is captured into a variable. Step 22 writes them to `configs/lab-03.env` so Lab 4 can use them.

### Step 1 - Resume the environment and load three env files

This lab consumes values from two previous labs. From Lab 4 onward this opening is assumed rather than shown.

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh

source configs/course.env
source configs/lab-01.env
source configs/lab-02.env

./scripts/utilities/whoami.sh

printf '%-24s %s\n' \
  "public subnet a"  "$USMS_PUBLIC_SUBNET_A" \
  "private subnet a" "$USMS_PRIVATE_SUBNET_A" \
  "app security group" "$USMS_APP_SG" \
  "db security group"  "$USMS_DB_SG" \
  "instance profile"   "$USMS_INSTANCE_PROFILE" \
  "availability zone a" "$USMS_AZ_A"
```

`printf` reuses its format string until the arguments run out, so one call prints six aligned lines.

**Expected result**

```text
Identity : arn:aws:iam::000000000000:root
Account  : 000000000000
Endpoint : http://localhost:4566

public subnet a          subnet-01234abcd5678ef90
private subnet a         subnet-09876fedcba543210
app security group       sg-0123456789abcdef0
db security group        sg-0fedcba9876543210
instance profile         usms-ec2-app-profile
availability zone a      us-east-1a
```

> Example output - your IDs will differ.

All six values must be non-empty. An empty one means `configs/lab-02.env` is incomplete; regenerate it from Lab 2 Step 24 before continuing.

---

### Step 2 - Confirm Lab 02's network is intact

Before building on the network, check it is still there and still correct.

```bash
./scripts/utilities/verify-lab-02.sh
```

**Expected result**

```text
...
PASS=33  FAIL=0
```

`FAIL=0`, or stop. Failures under `== Environment ==` are the real problem; fix those first. A failing `usms-igw ATTACHED to usms-vpc` means the web server would launch but be unreachable.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running, hybrid storage
 ├── lab-01.env + lab-02.env sourced
 └── verify-lab-02.sh: FAIL=0
```

---

!!! info "What an instance is made of"
    An instance combines an **AMI** (a regional, immutable root-disk template), an **instance type** (the hardware: `t3.micro` is 2 vCPUs, 1 GiB, burstable) and optional **user data** (a script cloud-init runs as root). The facts the next steps rely on: user data runs **once**, at first boot, not on every start; it is limited to **16 KB**; and the root volume is deleted on termination by default, which is why Step 15 adds a separate data volume. See [what an instance is made of](../unit1/topic3.md#what-an-instance-is-made-of).

### Step 3 - Choose an AMI

AMI IDs differ per region and change whenever Amazon patches the image, so find one programmatically instead of copying it.

**Command - part 1, see what this build offers**

```bash
aws ec2 describe-images \
  --owners amazon \
  --query 'Images[].{Id:ImageId,Name:Name,Arch:Architecture,Root:RootDeviceType}' \
  --output table
```

**Command - part 2, capture one**

```bash
AMI_ID=$(aws ec2 describe-images \
  --owners amazon \
  --query 'Images[0].ImageId' \
  --output text)

echo "AMI_ID = $AMI_ID"
```

**Expected result**

```text
AMI_ID = ami-0abcd1234efgh5678
```

> Example output - your AMI ID will certainly differ, and may differ between Floci builds.

**If `AMI_ID` prints as `None` or an empty line**, this Floci build seeds no images. That is a limitation, not a mistake. Two options:

```bash
# Option A - register a minimal image of your own, so the rest of the lab is honest about
# where the ID came from.
AMI_ID=$(aws ec2 register-image \
  --name usms-course-base \
  --architecture x86_64 \
  --root-device-name /dev/xvda \
  --virtualization-type hvm \
  --query 'ImageId' --output text)
echo "AMI_ID = $AMI_ID"

# Option B - if register-image is also unsupported, note it in your report and continue with a
# placeholder. Floci does not validate the AMI ID on run-instances.
AMI_ID=ami-00000000000000000
```

Record which option you used. The assessment asks.

!!! note "Floci Limitation - AMIs are metadata, not disk images"
    Floci stores AMI records with no root filesystem behind them, and the catalogue is small or empty depending on the build.

    Real AWS publishes thousands of snapshot-backed images per region and replaces the Amazon Linux ones roughly monthly.

    Never hard-code an AMI ID on real AWS; resolve the current one at launch from an SSM public parameter:

    ```bash
    aws ssm get-parameter \
      --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      --query 'Parameter.Value' --output text
    ```

    Try it against Floci; a `ParameterNotFound` is the limitation, and the technique is still the point.

---

### Step 4 - Create the key pair and store the private key safely

AWS keeps the public half; the private half is shown exactly once, at creation, and can never be retrieved again.

```bash
aws ec2 create-key-pair \
  --key-name usms-app-key \
  --key-type rsa \
  --tag-specifications 'ResourceType=key-pair,Tags=[{Key=Name,Value=usms-app-key},{Key=Project,Value=USMS}]' \
  --query 'KeyMaterial' \
  --output text > outputs/usms-app-key.pem

chmod 600 outputs/usms-app-key.pem

ls -l outputs/usms-app-key.pem
head -1 outputs/usms-app-key.pem
```

- The redirect sends the private key straight to `outputs/`, so it never appears on screen, in scrollback or in a screenshot. The Floci key is a dummy; the habit is the point.
- `chmod 600` is required: SSH refuses a private key readable by anyone else.

**Expected result**

```text
-rw------- 1 student student 1704 Aug 15 10:22 outputs/usms-app-key.pem
-----BEGIN RSA PRIVATE KEY-----
```

> Example output - the size and date will differ.

Permissions must be `-rw-------` and the first line must begin a PEM block. A file containing `None` means the key was not created; re-run without the redirect to see the error (often `InvalidKeyPair.Duplicate`).

**Verify**

```bash
aws ec2 describe-key-pairs \
  --key-names usms-app-key \
  --query 'KeyPairs[0].{Name:KeyName,Fingerprint:KeyFingerprint,Type:KeyType}' \
  --output table
```

AWS returns the fingerprint and public key, never the private key.

---

### Step 5 - Prove the private key is git-ignored

Lab 1 committed `.gitignore` before any secret existed. Check, rather than trust, that it protects this one.

```bash
git status --short

git check-ignore -v outputs/usms-app-key.pem

git ls-files outputs/
```

**Expected result**

```text
?? labs/lab-03-ec2/

.gitignore:7:outputs/*	outputs/usms-app-key.pem

outputs/.gitkeep
```

> Example output - your line number may differ.

1. `git status --short` shows the new lab folder and **nothing under `outputs/`**.
2. `git check-ignore -v` names the rule and line. Silence means the file is **not** ignored; fix `.gitignore` before anything else.
3. `git ls-files outputs/` lists only `.gitkeep`, proving the pattern is `outputs/*` and not `outputs/` (which would silently drop the directory).

---

### Step 6 - Write the user-data bootstrap script

cloud-init runs this as root at first boot, so the portal exists without anyone logging in.

````bash
cat > labs/lab-03-ec2/user-data.sh << 'EOF'
#!/bin/bash
# USMS web tier bootstrap. Runs ONCE, as root, at first boot, via cloud-init.
# Everything here must be non-interactive and idempotent.
set -x
exec > /var/log/usms-bootstrap.log 2>&1

echo "USMS bootstrap starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

dnf -y update
dnf -y install nginx

# Ask the instance about itself, using IMDSv2 (token-based, the secure default).
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
meta() {
  curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
    "http://169.254.169.254/latest/meta-data/$1"
}

INSTANCE_ID=$(meta instance-id)
AZ=$(meta placement/availability-zone)
PRIVATE_IP=$(meta local-ipv4)

cat > /usr/share/nginx/html/index.html <<HTML
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>USMS - University Student Management System</title></head>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto">
  <h1>USMS Student Portal</h1>
  <p>University Student Management System &mdash; web tier</p>
  <table border="1" cellpadding="6" cellspacing="0">
    <tr><td>Instance</td><td>${INSTANCE_ID}</td></tr>
    <tr><td>Availability Zone</td><td>${AZ}</td></tr>
    <tr><td>Private address</td><td>${PRIVATE_IP}</td></tr>
    <tr><td>Bootstrapped</td><td>$(date -u +%Y-%m-%dT%H:%M:%SZ)</td></tr>
  </table>
</body>
</html>
HTML

# A machine-readable endpoint, so a health check does not have to parse HTML.
printf '{"service":"usms-web","status":"ok","instance":"%s","az":"%s"}\n' \
  "$INSTANCE_ID" "$AZ" > /usr/share/nginx/html/health.json

systemctl enable --now nginx
echo "USMS bootstrap complete"
EOF

bash -n labs/lab-03-ec2/user-data.sh && echo "user-data.sh syntax OK"
wc -c labs/lab-03-ec2/user-data.sh
````

!!! warning "Heredoc quoting - a quoted outer heredoc and an unquoted inner one"
    The outer `<< 'EOF'` is quoted so `$(date ...)`, `${INSTANCE_ID}` and `$TOKEN` are written literally and evaluated later, on the instance. With `<< EOF` your laptop's shell would expand them now.

    The inner `<<HTML` is unquoted on purpose: it runs on the instance at boot, where `${INSTANCE_ID}` should expand. Compare Lab 2 Step 15 (quoted) and Lab 2 Step 24 (unquoted). The question is always: **expand now, or later?**

You want `user-data.sh syntax OK` and a byte count well under 16,384. Fix any `bash -n` error now; a syntax error in user data fails silently at boot.

**Expected result**

```text
user-data.sh syntax OK
1487 labs/lab-03-ec2/user-data.sh
```

> Example output - your byte count will differ.

---

### Step 7 - Generate a request skeleton and fill it in

`run-instances` has more than fifty parameters. `--generate-cli-skeleton` prints the request shape as JSON and `--cli-input-json` submits one, turning the call into a reviewable, version-controlled file.

**Command - part 1, look at the shape**

```bash
mkdir -p templates

aws ec2 run-instances --generate-cli-skeleton \
  > templates/lab-03-run-instances-full.json

wc -l templates/lab-03-run-instances-full.json
head -25 templates/lab-03-run-instances-full.json
```

**Expected result**

```text
   312 templates/lab-03-run-instances-full.json
{
    "BlockDeviceMappings": [
        {
            "DeviceName": "",
            "Ehm": {
            ...
```

> Example output - the line count varies by CLI version. The point is that it is large.

Skim it once; nearly every field is optional.

**Command - part 2, write the request we actually want**

```bash
cat > templates/lab-03-run-instances.json << EOF
{
  "ImageId": "$AMI_ID",
  "InstanceType": "t3.micro",
  "MinCount": 1,
  "MaxCount": 1,
  "KeyName": "usms-app-key",
  "SubnetId": "$USMS_PUBLIC_SUBNET_A",
  "SecurityGroupIds": ["$USMS_APP_SG"],
  "IamInstanceProfile": { "Name": "$USMS_INSTANCE_PROFILE" },
  "TagSpecifications": [
    {
      "ResourceType": "instance",
      "Tags": [
        { "Key": "Name",    "Value": "usms-web-01" },
        { "Key": "Project", "Value": "USMS" },
        { "Key": "Tier",    "Value": "web" },
        { "Key": "Lab",     "Value": "03" }
      ]
    },
    {
      "ResourceType": "volume",
      "Tags": [
        { "Key": "Name",    "Value": "usms-web-01-root" },
        { "Key": "Project", "Value": "USMS" }
      ]
    }
  ]
}
EOF

python3 -m json.tool templates/lab-03-run-instances.json > /dev/null \
  && echo "valid JSON" || echo "INVALID JSON - fix it before Step 8"

cat templates/lab-03-run-instances.json
```

- Unquoted heredoc, because the four variables must expand now.
- `python3 -m json.tool` validates first; the CLI's parse errors point at a byte offset, not a field.
- The `volume` tag specification tags the root EBS volume `run-instances` creates; untagged volumes are how orphaned storage accumulates.

**Expected result**

```text
valid JSON
```

followed by the document, with your real IDs substituted in.

No `$` may remain in the printed file. A literal `$AMI_ID` means you used a quoted heredoc.

---

### Step 8 - Launch the USMS web server

One call consuming a subnet and security group from Lab 2, an instance profile from Lab 1, and a key pair and user-data script from this lab.

```bash
WEB_INSTANCE_ID=$(aws ec2 run-instances \
  --cli-input-json file://templates/lab-03-run-instances.json \
  --user-data file://labs/lab-03-ec2/user-data.sh \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "WEB_INSTANCE_ID = $WEB_INSTANCE_ID"
```

```text
aws
 └── ec2
      └── run-instances
           ├── --cli-input-json file://...   the whole request, from the JSON document
           ├── --user-data      file://...   merged in on top of the JSON
           ├── --query          'Instances[0].InstanceId'
           └── --output text
```

- Command-line flags override the JSON, so `--user-data` can be added here instead of base64-encoding it into the document by hand.
- The CLI base64-encodes user data for `run-instances`, but **not** for `modify-instance-attribute`. That is why Step 12 decodes rather than reads.

**Expected result**

```text
WEB_INSTANCE_ID = i-0123456789abcdef0
```

> Example output - your instance ID will differ.

If this fails, the error message names the cause:

| Error | Cause |
| --- | --- |
| `InvalidAMIID.NotFound` | `$AMI_ID` was empty or wrong when Step 7 wrote the JSON. Rewrite it |
| `InvalidSubnetID.NotFound` | `$USMS_PUBLIC_SUBNET_A` was empty. Re-source `configs/lab-02.env` |
| `InvalidGroup.NotFound` | Same, for `$USMS_APP_SG` |
| `InvalidParameterValue: iamInstanceProfile.name` | Lab 1's instance profile does not exist |
| `InvalidKeyPair.NotFound` | Step 4 did not complete |

---

### Step 9 - Wait for the instance to reach `running`

An instance goes `pending`, then `running`. Wait for the state rather than sleeping for a guess.

```bash
time aws ec2 wait instance-running --instance-ids "$WEB_INSTANCE_ID"
echo "exit code: $?"
```

- `aws ec2 wait instance-running` polls `describe-instances` every 15 seconds, up to 40 times. Exit 0 means the condition was met; 255 means it timed out. `aws ec2 wait help` lists the others (`instance-status-ok`, `instance-terminated`, `volume-available`, `volume-in-use`).
- `instance-running` means the VM has started; `instance-status-ok` means status checks passed and the OS is up. A script that connects to a service should wait for the latter.

**Expected result**

```text
real    0m2.114s
exit code: 0
```

> Example output - on real AWS this takes 30 to 60 seconds. Floci transitions almost immediately,
> which is a difference worth noticing rather than enjoying.

**If the waiter hangs**, interrupt with ++ctrl+c++ and poll manually:

```bash
for i in $(seq 1 10); do
  state=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
            --query 'Reservations[0].Instances[0].State.Name' --output text)
  echo "attempt $i: $state"
  [ "$state" = "running" ] && break
  sleep 3
done
```

---

### Step 10 - Read the instance back and understand the fields

Pull the fields that matter out of the large `describe-instances` document.

```bash
aws ec2 describe-instances \
  --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{
      Id:InstanceId,
      State:State.Name,
      Type:InstanceType,
      AZ:Placement.AvailabilityZone,
      Subnet:SubnetId,
      PrivateIP:PrivateIpAddress,
      PublicIP:PublicIpAddress,
      Profile:IamInstanceProfile.Arn,
      SG:SecurityGroups[0].GroupName,
      Key:KeyName
    }' \
  --output table
```

A *reservation* is the batch from one `run-instances` call, so EC2 queries start `Reservations[0].Instances[0]`. Forgetting the first index is the most common EC2 JMESPath mistake.

**Expected result**

```text
-------------------------------------------------------
|                  DescribeInstances                  |
+-----------+-----------------------------------------+
|  AZ       |  us-east-1a                             |
|  Id       |  i-0123456789abcdef0                    |
|  Key      |  usms-app-key                           |
|  PrivateIP|  10.0.1.87                              |
|  Profile  |  arn:aws:iam::000000000000:instance-...  |
|  PublicIP |  54.12.33.201                           |
|  SG       |  usms-app-sg                            |
|  State    |  running                                |
|  Subnet   |  subnet-01234abcd5678ef90               |
|  Type     |  t3.micro                               |
+-----------+-----------------------------------------+
```

> Example output - every value here will differ.

- `State` is `running`; `Subnet` equals `$USMS_PUBLIC_SUBNET_A`; `PrivateIP` is inside `10.0.1.0/24`.
- `PublicIP` has a value only because Lab 2 Step 8 set `MapPublicIpOnLaunch` on this subnet.
- `SG` is `usms-app-sg`, not `default`; `Profile` is a non-null ARN (Step 11 follows it).

**Checkpoint 2**

```text
usms-public-subnet-a  10.0.1.0/24
 └── usms-web-01  i-0123...  t3.micro  running
      ├── private 10.0.1.87   public 54.12.33.201 (auto-assigned)
      ├── sg      usms-app-sg
      ├── profile usms-ec2-app-profile
      └── key     usms-app-key
```

---

### Step 11 - Trace the permission chain from the instance to the policy

The instance profile is why there are no AWS credentials on this server. Follow it link by link, so that when Lab 4 creates the bucket you already know why the instance can write to it.

```bash
PROFILE_ARN=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].IamInstanceProfile.Arn' --output text)
echo "1. instance -> profile : $PROFILE_ARN"

ROLE_NAME=$(aws iam get-instance-profile \
  --instance-profile-name "$USMS_INSTANCE_PROFILE" \
  --query 'InstanceProfile.Roles[0].RoleName' --output text)
echo "2. profile  -> role    : $ROLE_NAME"

aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
  --query 'AttachedPolicies[].{Policy:PolicyName,Arn:PolicyArn}' --output table

POLICY_ARN=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
  --query 'AttachedPolicies[?PolicyName==`USMSStudentDataReadWrite`].PolicyArn | [0]' \
  --output text)

DEFAULT_VERSION=$(aws iam get-policy --policy-arn "$POLICY_ARN" \
  --query 'Policy.DefaultVersionId' --output text)

echo "4. role -> policy document:"
aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$DEFAULT_VERSION" \
  --query 'PolicyVersion.Document' --output json | tee outputs/lab-03-instance-policy.json
```

**Expected result**

```text
1. instance -> profile : arn:aws:iam::000000000000:instance-profile/usms-ec2-app-profile
2. profile  -> role    : usms-ec2-app-role
---------------------------------------------------------------------------
|                       ListAttachedRolePolicies                          |
+-----------------------------------------+-------------------------------+
|                   Arn                   |            Policy             |
+-----------------------------------------+-------------------------------+
| arn:aws:iam::000000000000:policy/USMS... |  USMSStudentDataReadWrite     |
+-----------------------------------------+-------------------------------+
4. role -> policy document:
{
    "Version": "2012-10-17",
    "Statement": [ ... ]
}
```

> Example output - the policy body is Lab 1's, unchanged.

The policy grants `s3:GetObject`, `s3:PutObject` and `s3:ListBucket` on `arn:aws:s3:::usms-student-data` and `arn:aws:s3:::usms-student-data/*`, and denies `s3:DeleteBucket`. That bucket **does not exist** until Lab 4. An IAM policy is a statement about ARNs, not a reference to objects, so it is valid; it simply has no effect until something appears at that ARN. Write that sentence into `notes/lab-03-notes.md` now; it is a review question.

!!! note "Floci Limitation - the instance cannot fetch its own credentials"
    On real AWS the instance gets auto-rotated temporary credentials from the Instance Metadata Service at `169.254.169.254`, and the SDKs find them with no configuration.

    Floci does not serve IMDS to instances, so the `meta` function in your user-data script would fail there.

    The instance → profile → role → policy association is stored and returned correctly, and that association is what you are assessed on.

---

### Step 12 - Prove the user data actually arrived

`run-instances` accepting the script is not evidence it stored what you meant. Read it back, decode it, and compare byte for byte.

```bash
aws ec2 describe-instance-attribute \
  --instance-id "$WEB_INSTANCE_ID" \
  --attribute userData \
  --query 'UserData.Value' \
  --output text > outputs/lab-03-userdata.b64

wc -c outputs/lab-03-userdata.b64
head -c 80 outputs/lab-03-userdata.b64; echo

openssl base64 -d -A -in outputs/lab-03-userdata.b64 -out outputs/lab-03-userdata.sh

diff labs/lab-03-ec2/user-data.sh outputs/lab-03-userdata.sh \
  && echo "USER DATA PROVEN: what EC2 stored is byte-identical to what you wrote" \
  || echo "MISMATCH - see the diff above"
```

- The API returns user data base64-encoded.
- `openssl base64 -d -A` decodes identically on Linux and macOS (`base64 -d` vs `-D` differ); `-A` accepts one long line.
- An empty `diff` proves encode, storage and decode round-tripped without loss.

**Expected result**

```text
1984 outputs/lab-03-userdata.b64
IyEvYmluL2Jhc2gKIyBVU01TIHdlYiB0aWVyIGJvb3RzdHJhcC4gUnVucyBPTkNFLCBhcyByb290LCBh
USER DATA PROVEN: what EC2 stored is byte-identical to what you wrote
```

> Example output - your byte count will differ. The base64 prefix `IyEvYmluL2Jhc2gK` decodes to
> `#!/bin/bash\n`, which is a useful thing to recognise on sight.

You want the `USER DATA PROVEN` line. A difference usually means Step 6's heredoc was unquoted.

**Checkpoint 3**

```text
usms-web-01  i-0123...
 ├── state       running
 ├── placement   usms-public-subnet-a / us-east-1a
 ├── firewall    usms-app-sg
 ├── identity    usms-ec2-app-profile -> usms-ec2-app-role -> USMSStudentDataReadWrite
 └── user data   stored, decoded, byte-identical to labs/lab-03-ec2/user-data.sh
```

---

### Step 13 - Give the web server a stable public address

The auto-assigned address changes on every stop/start. An Elastic IP is an address you own, independent of any instance.

```bash
AUTO_PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "auto-assigned address before EIP: $AUTO_PUBLIC_IP"

WEB_EIP_ALLOC=$(aws ec2 allocate-address \
  --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=usms-web-eip},{Key=Project,Value=USMS},{Key=Tier,Value=web}]' \
  --query 'AllocationId' --output text)

WEB_EIP_ASSOC=$(aws ec2 associate-address \
  --allocation-id "$WEB_EIP_ALLOC" \
  --instance-id "$WEB_INSTANCE_ID" \
  --query 'AssociationId' --output text)

WEB_PUBLIC_IP=$(aws ec2 describe-addresses \
  --allocation-ids "$WEB_EIP_ALLOC" \
  --query 'Addresses[0].PublicIp' --output text)

printf 'alloc=%s assoc=%s address=%s\n' "$WEB_EIP_ALLOC" "$WEB_EIP_ASSOC" "$WEB_PUBLIC_IP"
```

- The **allocation ID** is the handle for the address; the **association ID** is the handle for its binding to an instance. Using the wrong one is a common error.
- Associating an Elastic IP releases the instance's auto-assigned public address.

**Expected result**

```text
auto-assigned address before EIP: 54.12.33.201
alloc=eipalloc-0aaa111bbb222ccc3 assoc=eipassoc-0ddd444eee555fff6 address=52.9.144.17
```

> Example output - every address and ID will differ.

**Verify**

```bash
aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{Public:PublicIpAddress,Private:PrivateIpAddress}' \
  --output table
```

`Public` now shows the Elastic IP, not the address from Step 10.

!!! note "Floci Limitation - Elastic IPs are plausible, not routable"
    Floci tracks the allocation and association correctly, but nothing on the internet routes to the address.

    Real AWS gives you a reachable address and **charges for it while it is not associated with a running instance**, a common first-bill surprise after Lab 2 Step 19's NAT gateway.

    The address is a resource with its own lifecycle, decoupled from the instance so you can move it during a failover.

---

### Step 14 - Test the application

Try the request. When it does not answer, work out which link in the chain is missing; that reasoning is what is assessed.

**Command - primary path**

```bash
curl -sS --max-time 5 "http://${WEB_PUBLIC_IP}/" && echo || echo "no response (expected on Floci)"
curl -sS --max-time 5 "http://${WEB_PUBLIC_IP}/health.json" && echo || echo "no response (expected on Floci)"
```

**Expected result on real AWS**

```html
<!doctype html>
<html lang="en">
...
    <tr><td>Instance</td><td>i-0123456789abcdef0</td></tr>
```

**Expected result on Floci**

```text
curl: (28) Connection timed out after 5001 milliseconds
no response (expected on Floci)
```

Not a failure of your work: Floci boots no OS, so no nginx listens. Now prove everything you control is correct.

**Command - fallback, prove every link in the chain**

```bash
echo "== 1. Is the instance running? =="
aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text

echo "== 2. Is it in a subnet whose route table reaches an internet gateway? =="
SUBNET=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].SubnetId' --output text)
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=$SUBNET" \
  --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId | [0]' \
  --output text

echo "== 3. Is that internet gateway attached to the VPC? =="
aws ec2 describe-internet-gateways --internet-gateway-ids "$USMS_IGW_ID" \
  --query 'InternetGateways[0].Attachments[0].State' --output text

echo "== 4. Does the security group admit TCP 80 from the internet? =="
aws ec2 describe-security-groups --group-ids "$USMS_APP_SG" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`80`].IpRanges[0].CidrIp | [0]' \
  --output text

echo "== 5. Does the instance have a public address? =="
aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text

echo "== 6. Would the NACL on this subnet allow it? =="
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=$SUBNET" \
  --query 'NetworkAcls[0].{Acl:NetworkAclId,Default:IsDefault}' --output text
```

**Expected result**

```text
== 1. Is the instance running? ==
running
== 2. Is it in a subnet whose route table reaches an internet gateway? ==
igw-0f1e2d3c4b5a69870
== 3. Is that internet gateway attached to the VPC? ==
available
== 4. Does the security group admit TCP 80 from the internet? ==
0.0.0.0/0
== 5. Does the instance have a public address? ==
52.9.144.17
== 6. Would the NACL on this subnet allow it? ==
acl-0aabbccddeeff0011	True
```

> Example output - your IDs and addresses will differ.

Six answers, none `None`. They are, in order, what must be true for a browser request to reach an instance:

```text
browser
  -> internet gateway            (checks 2 and 3)
  -> route table                 (check 2)
  -> subnet
  -> network ACL                 (check 6)
  -> elastic network interface
  -> security group              (check 4)
  -> instance, running           (check 1)
  -> a process listening on 80   (NOT checked - this is the one Floci cannot give you)
```

This is the real-AWS debugging procedure for "I cannot reach my instance", and a viva question in Section 13. The last item is the only one this lab cannot verify, and on real AWS it is the one that is not an AWS problem.

**Checkpoint 4**

```text
usms-web-01  reachable-by-configuration
 ├── 1 instance running
 ├── 2 subnet -> usms-public-rt -> usms-igw
 ├── 3 usms-igw attached
 ├── 4 usms-app-sg allows tcp/80 from 0.0.0.0/0
 ├── 5 public address usms-web-eip
 ├── 6 default NACL on the public subnet: allow all
 └── 7 process listening on :80  -- not observable in Floci
```

---

### Step 15 - Create and attach a data volume

The root volume is deleted on termination, so student records need a separate EBS volume with its own lifecycle.

```bash
INSTANCE_AZ=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)
echo "instance is in $INSTANCE_AZ"

WEB_VOLUME_ID=$(aws ec2 create-volume \
  --availability-zone "$INSTANCE_AZ" \
  --size 8 \
  --volume-type gp3 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=usms-web-data-vol},{Key=Project,Value=USMS},{Key=Tier,Value=web}]' \
  --query 'VolumeId' --output text)

echo "WEB_VOLUME_ID = $WEB_VOLUME_ID"

aws ec2 wait volume-available --volume-ids "$WEB_VOLUME_ID" || sleep 5

aws ec2 attach-volume \
  --volume-id "$WEB_VOLUME_ID" \
  --instance-id "$WEB_INSTANCE_ID" \
  --device /dev/sdf \
  --query '{Volume:VolumeId,Device:Device,State:State}' \
  --output table
```

- The AZ is derived from the instance because **an EBS volume can only attach to an instance in the same AZ**. To move data across AZs, snapshot (regional) and create a new volume. See [EBS](../unit6/topic1.md#block-storage-with-amazon-ebs).
- `gp3` gives a baseline 3,000 IOPS and 125 MB/s regardless of size.
- `/dev/sdf` is renamed (for example `/dev/nvme1n1`) inside NVMe guests, so mount by filesystem UUID, not device name.

**Expected result**

```text
instance is in us-east-1a
WEB_VOLUME_ID = vol-0123456789abcdef0
-----------------------------------------------------------
|                      AttachVolume                       |
+-----------+-----------------------+---------------------+
|  Device   |        State          |       Volume        |
+-----------+-----------------------+---------------------+
| /dev/sdf  |  attaching            | vol-0123456789ab... |
+-----------+-----------------------+---------------------+
```

> Example output - your IDs will differ.

**Verify**

```bash
aws ec2 describe-volumes \
  --filters "Name=attachment.instance-id,Values=$WEB_INSTANCE_ID" \
  --query 'Volumes[].{Id:VolumeId,Size:Size,Type:VolumeType,AZ:AvailabilityZone,Device:Attachments[0].Device,State:Attachments[0].State,DeleteOnTerm:Attachments[0].DeleteOnTermination}' \
  --output table
```

You want **two** volumes: the root volume (`DeleteOnTerm` `True`) and your data volume (`DeleteOnTerm` `False`). That column decides what survives a terminate.

✏️ **Your turn**

Test the Availability Zone constraint rather than believing it. Create an 8 GiB `gp3` volume in
`$USMS_AZ_B` - the *other* zone - and attempt to attach it to `usms-web-01`, which is in
`$USMS_AZ_A`.

```text
Expected result:
On real AWS: InvalidVolume.ZoneMismatch, naming both zones.
On Floci: record what actually happens - it may accept the attachment, which is
itself a finding worth writing down. Either way, delete the test volume afterwards
and state in one sentence what real AWS would have done.
```

Hint: `aws ec2 delete-volume --volume-id <id>` after detaching, if it attached. This is the only expected error in the lab, which is why it is a "your turn" task rather than an assessed step (see Section 11).

---

### Step 16 - Launch the database-tier instance into the private subnet

The data tier gets no public address and no path to the internet gateway.

```bash
DB_INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t3.micro \
  --key-name usms-app-key \
  --subnet-id "$USMS_PRIVATE_SUBNET_A" \
  --security-group-ids "$USMS_DB_SG" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=usms-db-01},{Key=Project,Value=USMS},{Key=Tier,Value=data},{Key=Lab,Value=03}]' 'ResourceType=volume,Tags=[{Key=Name,Value=usms-db-01-root},{Key=Project,Value=USMS}]' \
  --query 'Instances[0].InstanceId' --output text)

echo "DB_INSTANCE_ID = $DB_INSTANCE_ID"

aws ec2 wait instance-running --instance-ids "$DB_INSTANCE_ID" || sleep 5

aws ec2 describe-instances --instance-ids "$DB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{Id:InstanceId,State:State.Name,Subnet:SubnetId,Private:PrivateIpAddress,Public:PublicIpAddress,SG:SecurityGroups[0].GroupName,Profile:IamInstanceProfile}' \
  --output table
```

- Long-form flags this time, so you have used both styles. `--tag-specifications` takes two arguments: instance and root volume.
- Deliberately **no** `--iam-instance-profile`: the data tier never calls S3, and an unneeded role is privilege creep.

**Expected result**

```text
DB_INSTANCE_ID = i-0fedcba9876543210
------------------------------------------------------
|                 DescribeInstances                  |
+-----------+----------------------------------------+
|  Id       |  i-0fedcba9876543210                   |
|  Private  |  10.0.3.42                             |
|  Profile  |  None                                  |
|  Public   |  None                                  |
|  SG       |  usms-db-sg                            |
|  State    |  running                               |
|  Subnet   |  subnet-09876fedcba543210              |
+-----------+----------------------------------------+
```

> Example output - your IDs and addresses will differ.

Assessed: `Private` inside `10.0.3.0/24`; `Public` is `None` (Lab 2 Step 9 left `MapPublicIpOnLaunch` off); `SG` is `usms-db-sg`; `Profile` is `None`, on purpose.

---

### Step 17 - Prove the two tiers are wired the way you think

Floci does not enforce security groups, so read back the configuration that would produce the refusal and show it is exactly right.

```bash
echo "== Which security group does each instance carry? =="
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=USMS" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value,Subnet:SubnetId,SG:SecurityGroups[0].GroupName,Public:PublicIpAddress}' \
  --output table

echo
echo "== What does usms-db-sg admit, and from where? =="
aws ec2 describe-security-groups --group-ids "$USMS_DB_SG" \
  --query 'SecurityGroups[0].IpPermissions[].{Port:FromPort,FromGroup:UserIdGroupPairs[0].GroupId,FromCIDR:IpRanges[0].CidrIp}' \
  --output table

echo
echo "== Is that group the one usms-web-01 carries? =="
WEB_SG=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)
DB_SOURCE=$(aws ec2 describe-security-groups --group-ids "$USMS_DB_SG" \
  --query 'SecurityGroups[0].IpPermissions[0].UserIdGroupPairs[0].GroupId' --output text)

if [ "$WEB_SG" = "$DB_SOURCE" ]; then
  echo "WIRING PROVEN: usms-db-sg admits 5432 from $DB_SOURCE, which is the group usms-web-01 carries"
else
  echo "MISMATCH: web carries $WEB_SG but db-sg admits from $DB_SOURCE"
fi

echo
echo "== Can anything reach usms-db-01 from the internet? =="
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=$USMS_PRIVATE_SUBNET_A" \
  --query 'RouteTables[0].Routes[].{Dest:DestinationCidrBlock,Gateway:GatewayId,NAT:NatGatewayId}' \
  --output table
```

**Expected result**

```text
== Which security group does each instance carry? ==
--------------------------------------------------------------------------
|  Name         |  Public       |  SG           |  Subnet                |
+---------------+---------------+---------------+------------------------+
|  usms-web-01  |  52.9.144.17  |  usms-app-sg  |  subnet-01234abcd...   |
|  usms-db-01   |  None         |  usms-db-sg   |  subnet-09876fedc...   |
+---------------+---------------+---------------+------------------------+

== What does usms-db-sg admit, and from where? ==
-------------------------------------------------
|  FromCIDR  |  FromGroup           |  Port     |
+------------+----------------------+-----------+
|  None      |  sg-0123456789abcdef0|  5432     |
+------------+----------------------+-----------+

== Is that group the one usms-web-01 carries? ==
WIRING PROVEN: usms-db-sg admits 5432 from sg-0123456789abcdef0, which is the group usms-web-01 carries

== Can anything reach usms-db-01 from the internet? ==
-------------------------------------------------------------
|  Dest         |  Gateway  |  NAT                          |
+---------------+-----------+-------------------------------+
|  10.0.0.0/16  |  local    |  None                         |
|  0.0.0.0/0    |  None     |  nat-0abcdef1234567890        |
+-------------------------------------------------------------
```

> Example output - your IDs will differ.

- `FromCIDR` is `None` and `FromGroup` holds a group ID (see [security group referencing](../unit1/topic6.md#security-group-referencing-the-cloud-native-idiom)).
- The private default route targets a NAT gateway, not an internet gateway: outbound yes, inbound no. That is a routing property; it would hold even if `usms-db-sg` were opened to `0.0.0.0/0`.

**Checkpoint 5**

```text
usms-vpc
 ├── usms-public-subnet-a
 │    └── usms-web-01   public 52.9.144.17   usms-app-sg    usms-ec2-app-profile
 └── usms-private-subnet-a
      └── usms-db-01    no public address    usms-db-sg     no profile
            admits tcp/5432 from usms-app-sg only
            outbound via usms-nat only
```

---

### Step 18 - Stop and start the web server, and watch which address moves

Create, perturb, read back, applied to Step 13's claim: a stop/start releases an auto-assigned address and keeps an Elastic IP.

```bash
echo "before: web=$(aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)  db=$(aws ec2 describe-instances --instance-ids "$DB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)"

aws ec2 stop-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'StoppingInstances[0].{Id:InstanceId,From:PreviousState.Name,To:CurrentState.Name}' \
  --output table

aws ec2 wait instance-stopped --instance-ids "$WEB_INSTANCE_ID" || sleep 5

aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{State:State.Name,Public:PublicIpAddress,Private:PrivateIpAddress}' \
  --output table

aws ec2 start-instances --instance-ids "$WEB_INSTANCE_ID" >/dev/null
aws ec2 wait instance-running --instance-ids "$WEB_INSTANCE_ID" || sleep 5

echo "after:"
aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{State:State.Name,Public:PublicIpAddress,Private:PrivateIpAddress}' \
  --output table

aws ec2 describe-addresses --allocation-ids "$WEB_EIP_ALLOC" \
  --query 'Addresses[0].{Address:PublicIp,Instance:InstanceId,Assoc:AssociationId}' \
  --output table
```

!!! danger "Read before running any delete command"
    `stop-instances` is not a delete, but it is the closest thing in this lab.

    **What will be stopped:** `usms-web-01` only. Not terminated.

    **What depends on it:** nothing in this lab. Its volumes persist, its Elastic IP stays allocated, its instance ID does not change.

    **Reversible?** Yes - `start-instances`, which the command above does immediately.

    **Effect on later labs:** none. Do **not** substitute `terminate-instances`: it is irreversible, deletes the root volume, and Lab 4 expects `usms-web-01` to exist.

**Expected result on real AWS**

```text
before: web=52.9.144.17  db=10.0.3.42

State: stopped   Public: None       Private: 10.0.1.87
after:
State: running   Public: 52.9.144.17  Private: 10.0.1.87
```

1. While `stopped`, `PublicIpAddress` is `None`.
2. After starting, the **same Elastic IP** is back. An auto-assigned address would have changed, breaking every DNS record pointing at it.
3. `PrivateIpAddress` never changes for the life of the instance.

!!! note "Floci Limitation - the stop/start transition may be instantaneous or absent"
    Some Floci builds never clear the public address field, so the middle line reads `Public: 52.9.144.17` throughout.

    Real AWS always releases an auto-assigned address on stop, keeps an Elastic IP, and keeps the private address.

    If you do not see the address disappear, record the limitation and answer in prose: *what would have happened, and why does it matter for a DNS record?* Section 13's viva asks.

✏️ **Your turn**

Launch a second web server, `usms-web-02`, into `usms-public-subnet-b` in the other Availability
Zone, using `--cli-input-json` with a copy of `templates/lab-03-run-instances.json`. Give it the same
security group, the same instance profile and the same user data.

```text
Expected result:
Two running instances tagged Tier=web, in two different subnets and two different
Availability Zones, both carrying usms-app-sg. A describe-instances query filtered
on Tier=web returns exactly two rows.
```

Hint: copy the JSON to `templates/lab-03-run-instances-web02.json` and change only `SubnetId` and the `Name` tag; a two-line reviewable diff is the argument for `--cli-input-json`.

---

### Step 19 - Prove the compute layer survives a restart

The same proof as Lab 2 Step 23, applied to this lab. Lab 4 depends on `usms-web-01` still being there.

**Command - part 1, record the truth**

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=USMS" "Name=instance-state-name,Values=running" \
  --query 'sort_by(Reservations[].Instances[], &InstanceId)[].[InstanceId,SubnetId,SecurityGroups[0].GroupId]' \
  --output text > outputs/lab-03-pre-restart.txt

cat outputs/lab-03-pre-restart.txt
```

**Command - part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
```

**Command - part 3, read it back by tag, not by variable**

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=USMS" "Name=instance-state-name,Values=running" \
  --query 'sort_by(Reservations[].Instances[], &InstanceId)[].[InstanceId,SubnetId,SecurityGroups[0].GroupId]' \
  --output text > outputs/lab-03-post-restart.txt

diff outputs/lab-03-pre-restart.txt outputs/lab-03-post-restart.txt \
  && echo "PERSISTENCE PROVEN: same instances, same subnets, same security groups after restart" \
  || echo "PERSISTENCE FAILED: run ./scripts/utilities/floci-storage-check.sh"

aws ec2 describe-volumes --filters "Name=tag:Project,Values=USMS" \
  --query 'length(Volumes)' --output text
aws ec2 describe-addresses --filters "Name=tag:Project,Values=USMS" \
  --query 'length(Addresses)' --output text
```

- Lookups are **by tag**, not `$WEB_INSTANCE_ID`; reusing the variable would prove only that Bash remembers strings.
- The `length()` calls check volumes and Elastic IPs survived too, not only instances.

**Expected result**

```text
PERSISTENCE PROVEN: same instances, same subnets, same security groups after restart
4
2
```

> Example output - the volume count is 4 if you have two instances plus a data volume and did the
> Step 18 "Your turn" task; 3 otherwise. The Elastic IP count is 2: `usms-nat-eip` from Lab 2 and
> `usms-web-eip` from Step 13.

**Checkpoint 6**

```text
Persistence proven for Lab 03
 ├── usms-web-01 and usms-db-01 found by tag after stop/start
 ├── subnet and security group associations unchanged
 ├── EBS volumes present
 └── Elastic IPs still allocated
```

---

### Step 20 - Create an AMI from the configured instance

An AMI captures an already-configured machine, so the next launch is a copy rather than a rebuild. Lab 8's Auto Scaling group needs it.

```bash
WEB_AMI_ID=$(aws ec2 create-image \
  --instance-id "$WEB_INSTANCE_ID" \
  --name "usms-web-golden-$(date -u +%Y%m%d)" \
  --description "USMS web tier, nginx installed and portal page deployed, from Lab 03" \
  --no-reboot \
  --tag-specifications 'ResourceType=image,Tags=[{Key=Name,Value=usms-web-golden},{Key=Project,Value=USMS},{Key=Tier,Value=web}]' \
  --query 'ImageId' --output text)

echo "WEB_AMI_ID = $WEB_AMI_ID"

aws ec2 wait image-available --image-ids "$WEB_AMI_ID" 2>/dev/null || sleep 5

aws ec2 describe-images --image-ids "$WEB_AMI_ID" \
  --query 'Images[0].{Id:ImageId,Name:Name,State:State,Public:Public,Root:RootDeviceName}' \
  --output table
```

- `--name` must be unique per account and region, hence the date: re-running tomorrow works, twice today does not.
- `--no-reboot` keeps the service up but captures a filesystem with writes in flight. Fine for static web files; for a database, allow the reboot or quiesce first.

**Expected result**

```text
WEB_AMI_ID = ami-0abc123def456789a
------------------------------------------------------------
|                      DescribeImages                      |
+---------+---------------------------+---------+----------+
|  Id     |  usms-web-golden-20260815 | State   | available|
+---------+---------------------------+---------+----------+
```

> Example output - your ID and date will differ.

**AMI or user data?** Both, usually:

| | User data | AMI |
| --- | --- | --- |
| Boot time | Slow - installs packages at every launch | Fast - everything is already there |
| Patching | Always gets the latest packages | Frozen at build time; rebuild to patch |
| Auditability | The script is in Git and reviewable | The contents are opaque unless you built it reproducibly |
| Failure mode | A failed install leaves a half-configured live instance | A bad image fails identically every time, which is easier to diagnose |

The common pattern is a pipeline-built "golden" AMI for the slow, stable parts plus a short user-data script for environment-specific parts.

**Checkpoint 7**

```text
usms-web-golden  (ami-0abc...)
 └── built from usms-web-01, --no-reboot, tagged Project=USMS
     -> Lab 08 references it from a launch template
```

---

### Step 21 - Audit what this lab created

Lab 2 Step 22's audit, extended to compute.

```bash
echo "== Instances =="
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=USMS" \
  --query 'Reservations[].Instances[].{Name:Tags[?Key==`Name`]|[0].Value,Id:InstanceId,State:State.Name,Type:InstanceType,AZ:Placement.AvailabilityZone,Tier:Tags[?Key==`Tier`]|[0].Value}' \
  --output table

echo "== Volumes =="
aws ec2 describe-volumes --filters "Name=tag:Project,Values=USMS" \
  --query 'Volumes[].{Name:Tags[?Key==`Name`]|[0].Value,Id:VolumeId,Size:Size,AZ:AvailabilityZone,Attached:Attachments[0].InstanceId}' \
  --output table

echo "== Elastic IPs =="
aws ec2 describe-addresses --filters "Name=tag:Project,Values=USMS" \
  --query 'Addresses[].{Name:Tags[?Key==`Name`]|[0].Value,IP:PublicIp,Instance:InstanceId}' \
  --output table

echo "== Images =="
aws ec2 describe-images --owners self \
  --query 'Images[].{Name:Name,Id:ImageId,State:State}' --output table
```

Every resource in Section 3's "Created in this lab" block must appear, each with a `Name`. Fix any untagged one with `create-tags` before Step 22, or `configs/lab-03.env` will record `None`.

✏️ **Your turn**

Write a single command that prints, for every running USMS instance, its name, its Availability Zone,
and whether it has a public address - sorted so that instances **without** a public address appear
first. Save it to `outputs/lab-03-exposure-report.txt`.

```text
Expected result:
A table in which usms-db-01 is listed above usms-web-01, because it has no public
address. On a real account this is the report you would run to answer "what of ours
is exposed to the internet?"
```

Hint: `sort_by()` cannot order a null against a string; map the address to something orderable first, or look up `not_null()` in the JMESPath specification.

---

### Step 22 - Write `configs/lab-03.env`

Lab 4 needs the web instance, Lab 8 the AMI. Record them by lookup, not from shell variables.

```bash
cat > configs/lab-03.env << EOF
# Lab 03 - EC2 outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains IDs only. NO SECRETS. Safe to commit.
# The private key for usms-app-key lives in outputs/ and is NOT recorded here.

export USMS_KEY_PAIR=usms-app-key

export USMS_WEB_INSTANCE=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=usms-web-01" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
export USMS_DB_INSTANCE=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=usms-db-01" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

export USMS_WEB_EIP_ALLOC=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=usms-web-eip" \
  --query 'Addresses[0].AllocationId' --output text)
export USMS_WEB_PUBLIC_IP=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=usms-web-eip" \
  --query 'Addresses[0].PublicIp' --output text)

export USMS_WEB_DATA_VOLUME=$(aws ec2 describe-volumes \
  --filters "Name=tag:Name,Values=usms-web-data-vol" \
  --query 'Volumes[0].VolumeId' --output text)

export USMS_WEB_AMI=$(aws ec2 describe-images --owners self \
  --filters "Name=tag:Name,Values=usms-web-golden" \
  --query 'Images[0].ImageId' --output text)

export USMS_BASE_AMI=$AMI_ID
export USMS_INSTANCE_TYPE=t3.micro
EOF

grep -n 'export .*=$\|None' configs/lab-03.env || echo "all values populated"
```

- Unquoted heredoc, as in Lab 2 Step 24: every `$(...)` runs now and its result lands in the file.
- The two-value `instance-state-name` filter stops a terminated instance from a previous attempt (visible for about an hour) being recorded instead.

**Verify**

```bash
source configs/lab-03.env
printf '%-24s %s\n' \
  "web instance" "$USMS_WEB_INSTANCE" \
  "db instance"  "$USMS_DB_INSTANCE" \
  "web public IP" "$USMS_WEB_PUBLIC_IP" \
  "golden AMI"   "$USMS_WEB_AMI"
```

You want `all values populated`, then four non-empty values. `USMS_WEB_AMI` reading `None` means Step 20's tag did not apply; check with `aws ec2 describe-images --owners self --query 'Images[].Tags'`.

---

### Step 23 - Commit

Look first, stage explicitly, then commit.

```bash
git status --short

git check-ignore -v outputs/usms-app-key.pem

git add labs/lab-03-ec2/ configs/lab-03.env templates/lab-03-run-instances.json \
        scripts/utilities/verify-lab-03.sh scripts/cleanup/lab-03-cleanup.sh

git status --short

git commit -m "Lab 03: USMS web and data tier instances, EIP, EBS volume, golden AMI"

git log --oneline -4
```

Before `git commit`:

- Nothing under `outputs/` is staged, especially not `usms-app-key.pem`.
- `templates/lab-03-run-instances-full.json` is **not** staged; it is an empty skeleton.
- `configs/lab-03.env` **is** staged. IDs, no secrets.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/usms-app-key.pem
[main 8c31de4] Lab 03: USMS web and data tier instances, EIP, EBS volume, golden AMI
 6 files changed, 388 insertions(+)
```

> Example output - your hash and counts will differ.

**Checkpoint 8**

```text
Lab 03 recorded
 ├── configs/lab-03.env      committed, fully populated
 ├── templates/              run-instances request under version control
 ├── outputs/usms-app-key.pem  present, chmod 600, git-ignored, PROVEN ignored
 └── git log shows Lab 01, Lab 02 and Lab 03 commits
```

---

## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-03.sh`

Three checks go beyond existence: `usms-db-01 has NO public address` (a negative assertion), `data volume DeleteOnTermination is False` (the configuration that makes it durable), and `private key is chmod 600 and not tracked by git` (the security property, not just the file).

{% raw %}```bash
cat > scripts/utilities/verify-lab-03.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 03 artefact exists and is configured correctly.
# Exit 1 if anything is missing. Read-only; safe to run at any time.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-01.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-02.env" 2>/dev/null || true
source "$REPO_ROOT/configs/lab-03.env" 2>/dev/null || true

: "${USMS_VPC_ID:=none}"
: "${USMS_PUBLIC_SUBNET_A:=none}"
: "${USMS_PRIVATE_SUBNET_A:=none}"
: "${USMS_APP_SG:=none}"
: "${USMS_DB_SG:=none}"
: "${USMS_INSTANCE_PROFILE:=none}"
: "${USMS_WEB_INSTANCE:=none}"
: "${USMS_DB_INSTANCE:=none}"
: "${USMS_WEB_DATA_VOLUME:=none}"
: "${USMS_WEB_EIP_ALLOC:=none}"
: "${USMS_WEB_AMI:=none}"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then printf "  ok   %s\n" "$1"; PASS=$((PASS+1))
  else printf "  FAIL %s\n" "$1"; FAIL=$((FAIL+1)); fi
}

# Helper: one instance field, by instance id.
q() { aws ec2 describe-instances --instance-ids "$1" \
        --query "Reservations[0].Instances[0].$2" --output text; }

echo "== Environment =="
check "Floci container running" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "AWS CLI reaches Floci" "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = 000000000000"

echo "== Lab 01 and Lab 02 dependencies =="
check "usms-vpc still exists"      "aws ec2 describe-vpcs --vpc-ids $USMS_VPC_ID"
check "usms-public-subnet-a exists" "aws ec2 describe-subnets --subnet-ids $USMS_PUBLIC_SUBNET_A"
check "usms-ec2-app-profile exists" \
  "aws iam get-instance-profile --instance-profile-name $USMS_INSTANCE_PROFILE"

echo "== Lab 03 key pair =="
check "key pair usms-app-key exists" "aws ec2 describe-key-pairs --key-names usms-app-key"
check "private key file present"     "test -f outputs/usms-app-key.pem"
check "private key is chmod 600" \
  "test \"\$(stat -c '%a' outputs/usms-app-key.pem 2>/dev/null || stat -f '%Lp' outputs/usms-app-key.pem)\" = 600"

echo "== Lab 03 web tier =="
check "usms-web-01 exists"           "aws ec2 describe-instances --instance-ids $USMS_WEB_INSTANCE"
check "usms-web-01 is running"       "test \"\$(q $USMS_WEB_INSTANCE State.Name)\" = running"
check "usms-web-01 is t3.micro"      "test \"\$(q $USMS_WEB_INSTANCE InstanceType)\" = t3.micro"
check "usms-web-01 is in usms-public-subnet-a" \
  "test \"\$(q $USMS_WEB_INSTANCE SubnetId)\" = $USMS_PUBLIC_SUBNET_A"
check "usms-web-01 carries usms-app-sg" \
  "test \"\$(q $USMS_WEB_INSTANCE 'SecurityGroups[0].GroupId')\" = $USMS_APP_SG"
check "usms-web-01 has an instance profile" \
  "test \"\$(q $USMS_WEB_INSTANCE 'IamInstanceProfile.Arn')\" != None"
check "that profile is usms-ec2-app-profile" \
  "q $USMS_WEB_INSTANCE 'IamInstanceProfile.Arn' | grep -q $USMS_INSTANCE_PROFILE"
check "usms-web-01 has user data stored" \
  "test -n \"\$(aws ec2 describe-instance-attribute --instance-id $USMS_WEB_INSTANCE --attribute userData --query 'UserData.Value' --output text)\""
check "usms-web-01 has a public address" \
  "test \"\$(q $USMS_WEB_INSTANCE PublicIpAddress)\" != None"
check "an Elastic IP is associated with usms-web-01" \
  "test \"\$(aws ec2 describe-addresses --allocation-ids $USMS_WEB_EIP_ALLOC --query 'Addresses[0].InstanceId' --output text)\" = $USMS_WEB_INSTANCE"

echo "== Lab 03 storage =="
check "usms-web-data-vol exists"     "aws ec2 describe-volumes --volume-ids $USMS_WEB_DATA_VOLUME"
check "data volume is attached to usms-web-01" \
  "test \"\$(aws ec2 describe-volumes --volume-ids $USMS_WEB_DATA_VOLUME --query 'Volumes[0].Attachments[0].InstanceId' --output text)\" = $USMS_WEB_INSTANCE"
check "data volume survives termination (DeleteOnTermination is False)" \
  "test \"\$(aws ec2 describe-volumes --volume-ids $USMS_WEB_DATA_VOLUME --query 'Volumes[0].Attachments[0].DeleteOnTermination' --output text)\" = False"
check "data volume is in the same AZ as the instance" \
  "test \"\$(aws ec2 describe-volumes --volume-ids $USMS_WEB_DATA_VOLUME --query 'Volumes[0].AvailabilityZone' --output text)\" = \"\$(q $USMS_WEB_INSTANCE 'Placement.AvailabilityZone')\""

echo "== Lab 03 data tier =="
check "usms-db-01 exists"            "aws ec2 describe-instances --instance-ids $USMS_DB_INSTANCE"
check "usms-db-01 is in usms-private-subnet-a" \
  "test \"\$(q $USMS_DB_INSTANCE SubnetId)\" = $USMS_PRIVATE_SUBNET_A"
check "usms-db-01 carries usms-db-sg" \
  "test \"\$(q $USMS_DB_INSTANCE 'SecurityGroups[0].GroupId')\" = $USMS_DB_SG"
check "usms-db-01 has NO public address" \
  "test \"\$(q $USMS_DB_INSTANCE PublicIpAddress)\" = None"
check "usms-db-01 has NO instance profile" \
  "test \"\$(q $USMS_DB_INSTANCE 'IamInstanceProfile.Arn')\" = None"

echo "== Lab 03 image =="
check "usms-web-golden AMI exists"   "aws ec2 describe-images --image-ids $USMS_WEB_AMI"

echo "== Tagging =="
check "at least two instances tagged Project=USMS" \
  "test \"\$(aws ec2 describe-instances --filters Name=tag:Project,Values=USMS --query 'length(Reservations[].Instances[])' --output text)\" -ge 2"

echo "== Files and Git hygiene =="
check "configs/lab-03.env exists"    "test -f configs/lab-03.env"
check "configs/lab-03.env has no empty values" \
  "! grep -qE 'export [A-Z_]+=$|=None$' configs/lab-03.env"
check "user-data.sh exists and parses" "bash -n labs/lab-03-ec2/user-data.sh"
check "run-instances request is valid JSON" \
  "python3 -m json.tool templates/lab-03-run-instances.json"
check "the private key is NOT tracked by git" \
  "! git ls-files | grep -q 'usms-app-key.pem'"

echo; echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-03.sh
./scripts/utilities/verify-lab-03.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ok   Floci container running
  ok   Storage mode is NOT memory
  ok   AWS CLI reaches Floci
  ok   Account is 000000000000
...
== Files and Git hygiene ==
  ok   configs/lab-03.env exists
  ok   configs/lab-03.env has no empty values
  ok   user-data.sh exists and parses
  ok   run-instances request is valid JSON
  ok   the private key is NOT tracked by git

PASS=36  FAIL=0
```

> Example output - the middle is abbreviated; you will see all 36.

**The expected count is `PASS=36  FAIL=0`.**

Two failures have known, benign causes on some Floci builds; record them rather than fighting them:

- `usms-db-01 has NO public address`: Floci may assign one despite `MapPublicIpOnLaunch` being `False`. Check the subnet attribute yourself and say so.
- `data volume survives termination`: Floci may not populate `DeleteOnTermination`. Confirm with `aws ec2 describe-volumes --volume-ids "$USMS_WEB_DATA_VOLUME" --output json` and note it.

Any other failure is a real problem with your work.

### 8.2 Build the end-of-course cleanup script

!!! danger "DO NOT RUN THIS SCRIPT NOW"
    **What will be deleted:** both USMS instances, the Elastic IP, the data volume, the golden AMI
    and the key pair.

    **What depends on it:** Lab 4 uploads a transcript using `usms-web-01`'s identity. Lab 8 builds
    a launch template from `usms-web-golden`.

    **Reversible?** No. Terminated instances cannot be restarted, and the private key for
    `usms-app-key` cannot be re-issued.

    **Effect on later labs:** you would repeat this laboratory from Step 4.

    It requires you to type `DELETE USMS COMPUTE` in full before it does anything.

````bash
cat > scripts/cleanup/lab-03-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# END OF COURSE ONLY. Terminates Lab 03 compute, dependencies first.
# Run this BEFORE scripts/cleanup/lab-02-cleanup.sh - a VPC with running
# instances in it cannot be deleted.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"
source "$REPO_ROOT/configs/lab-03.env"

cat <<'WARN'
============================================================
  This TERMINATES usms-web-01 and usms-db-01, releases the
  Elastic IP, deletes the data volume, deregisters the AMI
  and deletes the key pair. None of it is reversible.
  Run this BEFORE lab-02-cleanup.sh.
============================================================
WARN

read -r -p 'Type exactly: DELETE USMS COMPUTE  > ' answer
[ "$answer" = "DELETE USMS COMPUTE" ] || { echo "aborted"; exit 1; }

say() { printf '\n-- %s\n' "$1"; }

say "disassociate and release the Elastic IP"
if [ "${USMS_WEB_EIP_ALLOC:-None}" != "None" ]; then
  assoc=$(aws ec2 describe-addresses --allocation-ids "$USMS_WEB_EIP_ALLOC" \
            --query 'Addresses[0].AssociationId' --output text)
  [ "$assoc" != "None" ] && aws ec2 disassociate-address --association-id "$assoc" || true
  aws ec2 release-address --allocation-id "$USMS_WEB_EIP_ALLOC" || true
fi

say "detach and delete the data volume"
if [ "${USMS_WEB_DATA_VOLUME:-None}" != "None" ]; then
  aws ec2 detach-volume --volume-id "$USMS_WEB_DATA_VOLUME" || true
  aws ec2 wait volume-available --volume-ids "$USMS_WEB_DATA_VOLUME" || sleep 10
  aws ec2 delete-volume --volume-id "$USMS_WEB_DATA_VOLUME" || true
fi

say "terminate instances"
ids=""
for i in "${USMS_WEB_INSTANCE:-None}" "${USMS_DB_INSTANCE:-None}"; do
  [ "$i" != "None" ] && ids="$ids $i"
done
if [ -n "$ids" ]; then
  # shellcheck disable=SC2086
  aws ec2 terminate-instances --instance-ids $ids || true
  # shellcheck disable=SC2086
  aws ec2 wait instance-terminated --instance-ids $ids || sleep 20
fi

say "deregister the golden AMI"
[ "${USMS_WEB_AMI:-None}" != "None" ] && \
  aws ec2 deregister-image --image-id "$USMS_WEB_AMI" || true

say "delete the key pair, and the private key on disk"
aws ec2 delete-key-pair --key-name "${USMS_KEY_PAIR:-usms-app-key}" || true
rm -f outputs/usms-app-key.pem

echo; echo "Lab 03 teardown complete. You may now run lab-02-cleanup.sh."
EOF

chmod +x scripts/cleanup/lab-03-cleanup.sh
bash -n scripts/cleanup/lab-03-cleanup.sh && echo "syntax OK - do NOT run it"
````

You want `syntax OK - do NOT run it`. The order is the lesson: an Elastic IP is disassociated before release, a volume is detached (asynchronously, hence the wait) before deletion, and instances are terminated before Lab 2's script can delete their VPC.

---

## 9. Checkpoints

| # | After step | What must be true |
| --- | --- | --- |
| 1 | Step 2 | Floci running, three env files sourced, `verify-lab-02.sh` reports `FAIL=0` |
| 2 | Step 10 | `usms-web-01` running in `usms-public-subnet-a`, private address in `10.0.1.0/24`, a public address present, `usms-app-sg` attached, instance profile ARN not null |
| 3 | Step 12 | Permission chain traced instance → profile → role → `USMSStudentDataReadWrite`; user data decoded and byte-identical to `user-data.sh` |
| 4 | Step 14 | All six reachability checks answer non-null; you can name the seventh link that Floci cannot verify |
| 5 | Step 17 | `usms-db-01` running in the private subnet with no public address and no profile; `usms-db-sg` admits 5432 from `usms-app-sg` by group reference; private route table targets the NAT gateway |
| 6 | Step 19 | Instances, subnets and security group associations identical after a Floci stop/start; volumes and Elastic IPs still present |
| 7 | Step 20 | `usms-web-golden` exists, state `available`, tagged `Project=USMS` |
| 8 | Step 23 | `configs/lab-03.env` populated and committed; `usms-app-key.pem` present, `chmod 600`, and proven git-ignored |

---

## 10. Troubleshooting

!!! warning "Known issue on Floci 2.0.1"
    On Floci 2.0.1, the nginx bootstrap fails on the Amazon Linux 2 AMI. Diagnose first, then use the alternative in [Known Issues - Lab 03](known-issues.md#lab-03-ec2). It states what the alternative does and does not prove.

??? danger "`InvalidAMIID.NotFound` or `InvalidAMIID.Malformed`"
    `$AMI_ID` was empty or wrong when Step 7 wrote the JSON. Check the file:

    ```bash
    grep ImageId templates/lab-03-run-instances.json
    ```

    `"ImageId": ""` or the literal `$AMI_ID` means redo Step 3, then Step 7 with an **unquoted** heredoc.

??? danger "`InvalidSubnetID.NotFound` or `InvalidGroup.NotFound`"
    `configs/lab-02.env` is not sourced in this terminal, or contains `None`.

    ```bash
    source configs/lab-02.env
    grep -n 'None' configs/lab-02.env
    ```

    A `None` means the Lab 2 resource does not exist. Fix it in Lab 2 and regenerate the file with Lab 2 Step 24; do not hand-edit.

??? danger "`InvalidParameterValue: Value () for parameter iamInstanceProfile.name is invalid`"
    `$USMS_INSTANCE_PROFILE` (from `configs/lab-01.env`) is empty. Confirm the profile exists and holds a role:

    ```bash
    aws iam get-instance-profile --instance-profile-name usms-ec2-app-profile \
      --query 'InstanceProfile.Roles[0].RoleName' --output text
    ```

    An empty answer means Lab 1's `add-role-to-instance-profile` step never ran. Fix it there.

??? danger "The instance launched but has no public IP address"
    Check, in order:

    ```bash
    # 1. Is it in the public subnet at all?
    aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].SubnetId' --output text

    # 2. Does that subnet auto-assign?
    aws ec2 describe-subnets --subnet-ids "$USMS_PUBLIC_SUBNET_A" \
      --query 'Subnets[0].MapPublicIpOnLaunch' --output text

    # 3. Is the instance actually running? A stopped instance has no public address.
    aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].State.Name' --output text
    ```

??? danger "`curl` to the public address times out"
    Expected on Floci: there is no operating system behind the instance. Use Step 14's fallback; nothing in the assessment requires the request to succeed. On real AWS, the same six checks plus "is a process listening on port 80" are the complete diagnosis.

??? danger "`base64: invalid option -- 'd'` in Step 12"
    You are on macOS with BSD `base64`. Use the step's portable `openssl` form:

    ```bash
    openssl base64 -d -A -in outputs/lab-03-userdata.b64 -out outputs/lab-03-userdata.sh
    ```

??? danger "Step 12's `diff` shows differences"
    Almost always an unquoted heredoc in Step 6:

    ```bash
    grep -n 'INSTANCE_ID' labs/lab-03-ec2/user-data.sh
    ```

    If `${INSTANCE_ID}` has become an empty string, rewrite the file with `<< 'EOF'` and relaunch the instance.

??? danger "`InvalidVolume.ZoneMismatch` when attaching the volume"
    The volume and instance are in different AZs. Step 15 derives the AZ from the instance to avoid this. If you typed it by hand, delete and recreate the volume in the right zone:

    ```bash
    aws ec2 delete-volume --volume-id "$WEB_VOLUME_ID"
    ```

??? danger "`aws ec2 wait instance-running` returns exit code 255"
    The waiter exhausted its attempts, either because the instance is not starting or because Floci does not drive the transition. Check the state directly and use Step 9's polling loop.

??? danger "`InvalidKeyPair.Duplicate`"
    You ran Step 4 twice; AWS will not re-issue a private key. Use the existing pair, or delete and recreate it (instances launched with the old pair lose their login path):

    ```bash
    aws ec2 delete-key-pair --key-name usms-app-key
    rm -f outputs/usms-app-key.pem
    ```

??? danger "`create-image` fails with `InvalidAMIName.Duplicate`"
    You already created an image with that name today. Add a time component:

    ```bash
    --name "usms-web-golden-$(date -u +%Y%m%d-%H%M%S)"
    ```

??? danger "Everything is gone after a restart"
    Run `./scripts/utilities/floci-storage-check.sh`. `FLOCI_STORAGE_MODE=memory` means the container was not started by Compose. The work is not recoverable; restore from the snapshot you took at the end of Lab 2.

---

## 11. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `run-instances`, instance lifecycle states | Real virtual machines | States modelled correctly; no VM | Implemented in Floci |
| `describe-instances` and its whole data model | Full | Full and realistic | Implemented in Floci |
| Key pairs, fingerprints, one-time private key | Full | Full; the key is a dummy | Implemented in Floci |
| Tags on instances and volumes | Full | Full | Implemented in Floci |
| User data storage and base64 round-trip | Full | Full - Step 12 proves it | Implemented in Floci |
| EBS volumes: create, attach, detach, describe | Full | Full at the API level | Implemented in Floci |
| Elastic IP allocate / associate / release | Real routable address | Plausible address, not routable | Floci Limitation |
| `create-image` | Real snapshot of the root volume | Image record with no backing snapshot | Floci Limitation |
| **Booting an operating system** | Yes | **No** - nothing runs inside the instance | Floci Limitation |
| cloud-init executing user data | Yes, once, as root at first boot | Stored but not executed | Floci Limitation |
| Instance Metadata Service at `169.254.169.254` | Yes, IMDSv1 and IMDSv2 | Not served to instances | Floci Limitation |
| Instance profile credentials delivered via IMDS | Yes, rotated automatically | Association stored; no credentials delivered | Floci Limitation |
| Security group enforcement on traffic | Every packet | Not enforced | Floci Limitation |
| Public address released on stop | Always | Build-dependent | Floci Limitation |
| Instance status checks (`instance-status-ok`) | System and instance checks | Not meaningfully modelled | Floci Limitation |
| SSH to the instance | Yes, with the private key | No | Conceptual / Real AWS |
| Instance types differing in real CPU and memory | Yes | Type is a label | Conceptual / Real AWS |
| Cost - per instance-hour, per GB-month, per idle EIP | Real | Free | Conceptual / Real AWS |
| Placement groups, dedicated hosts, spot pricing | Full | Not available | Conceptual / Real AWS |
| EC2 service quotas (vCPU limits per region) | Enforced | Not enforced | Conceptual / Real AWS |

**Observed versus reasoned:** you observed placement, the profile chain, the user-data round-trip, volume `DeleteOnTermination` values, private-address and ID stability, and persistence across a restart; you only reasoned about nginx running, user data executing, IMDS credentials, security group enforcement, public-address release on stop, SSH and cost.

**Where Floci is nicer than reality (traps on real AWS):** instances start instantly (a real `t3.micro` takes 30 to 60 seconds plus status checks, so code assuming Floci's speed has a race); AMIs are available immediately (a real `create-image` takes minutes); no cost (about USD 7.50 per month for a `t3.micro`, USD 0.64 for an 8 GiB `gp3` volume, USD 3.60 for an *unassociated* Elastic IP); no quotas (new accounts hit `VcpuLimitExceeded` rather than queueing).

---

## 12. Independent Lab Exercises

Record commands and output in `labs/lab-03-ec2/exercises.md`.

### Exercise 1 - Basic: a maintenance instance

**Requirements:** launch `usms-admin-01-host`, a `t3.micro` in `usms-public-subnet-b`, with `usms-app-key`, `usms-app-sg` and no instance profile. Tag it `Project=USMS`, `Tier=admin`, `Lab=03` and `Ephemeral=true`.

**Constraints**

- Use the long command-line form, not `--cli-input-json`.
- Wait for `running` with a waiter, not `sleep`.
- Do not record it in `configs/lab-03.env`. Exercise 4 removes it.

**Expected outcome:** `describe-instances` filtered on `Name=tag:Tier,Values=admin` returns exactly one running instance in `us-east-1b`.

**Hints:** Step 16 is the long-form launch; the only new thing is choosing the tags.

### Exercise 2 - Intermediate: a self-describing bootstrap

**Requirements:** write `labs/lab-03-ec2/user-data-db.sh`, a data-tier bootstrap that installs PostgreSQL, creates a database `usms`, writes a marker file `/var/log/usms-db-bootstrap.done` containing the instance ID and UTC timestamp, and refuses to run twice by checking for that marker first. Apply it to a **new** instance `usms-db-02` in `usms-private-subnet-b` and prove with Step 12's technique that what EC2 stored is byte-identical to what you wrote.

**Constraints**

- The outer heredoc must be quoted. Say in one sentence why.
- The script must be idempotent: a second run exits early and changes nothing.
- Under 16 KB.
- `bash -n` must pass before you launch anything.

**Expected outcome:** an empty `diff` between your script and the decoded user data, and a written explanation of when a re-run could actually happen given that user data normally runs once.

**Hints:** Steps 6 and 12 contain the whole technique. The idempotence check is three lines at the top of the script.

### Exercise 3 - Problem solving: a reachability report

**Requirements:** write `scripts/utilities/lab-03-reachability.sh`, printing one line per running instance tagged `Project=USMS`:

```text
usms-web-01  10.0.1.87   52.9.144.17  REACHABLE     igw route + sg allows 80/tcp from 0.0.0.0/0
usms-db-01   10.0.3.42   -            UNREACHABLE   no igw route on subnet
usms-web-02  10.0.2.11   -            NO-ADDRESS    igw route present but no public address
```

The verdict must be **computed** from the route table and security group, never from names or tags.

**Constraints**

- Runs correctly from any directory.
- No hard-coded resource IDs.
- Does not fail when a field is absent; a `None` must not crash it.
- `set -uo pipefail`. Decide about `-e` and justify it in a comment.

**Expected outcome:** identical output from `~` and from `~/aws-floci-course/labs/lab-03-ec2/`, correctly classifying every instance, including those from Exercises 1 and 2.

**Hints:** Step 14's fallback answers the question for one instance; the work is generalising it, including the real state where the subnet has an internet-gateway route but the instance has no public address.

### Exercise 4 - Challenge: right-size and clean up

**Requirements:** the USMS project lead writes:

> The portal has 400 concurrent users at peak, mostly reading. Our current single `t3.micro` is at 85
> percent CPU at midday and idle overnight. Finance says our EC2 line is too high and wants a number
> before we change anything. What would you change, what would it cost, and what would you delete
> today?

Write an analysis in `labs/lab-03-ec2/exercises.md` covering:

- scale up (bigger instance) or out (more instances behind a load balancer), with reasoning, and what each does about overnight idle time,
- what `t3.micro` burstable CPU credits are and why 85 percent sustained is a specific problem for a `t` instance,
- a monthly cost comparison of at least two options, with prices cited from a named source,
- what you would delete today (the Exercise 1 admin host, orphaned volumes, unassociated Elastic IPs), with exact commands in dependency order, each preceded by the four-line danger admonition.

Then execute only the deletions.

**Constraints**

- Do not delete anything in Section 15's KEEP column.
- Every deletion command is preceded by its danger admonition in your write-up.
- `./scripts/utilities/verify-lab-03.sh` still reports `FAIL=0` afterwards.

**Expected outcome:** an analysis with real numbers, and a repository with the ephemeral resources gone and verification still passing.

**Hints:** a `t3` sustained above baseline either exhausts its credits and throttles or silently bills for unlimited mode, depending on a setting you have not touched. Find it with `aws ec2 describe-instance-credit-specifications`.

### Exercise 5 - Integration: prepare the S3 hand-off for Lab 4

**Requirements:** Lab 4 creates `usms-student-data`, the bucket `USMSStudentDataReadWrite` has named since Lab 1. Prepare the EC2 side so Lab 4 is one `create-bucket` away from the permission chain resolving:

1. Write `labs/lab-03-ec2/transcript-upload.sh`, a script that would run **on** `usms-web-01`, taking a student ID and a file path and uploading to `s3://usms-student-data/transcripts/<student-id>/<filename>` using no credentials at all, relying on the instance profile.
2. Adding a TCP 443 rule to `usms-app-sg` is not needed. Confirm this, and state in one sentence why the *outbound* rule you never wrote is what makes the S3 call possible.
3. Write `outputs/lab-03-s3-readiness.txt` containing the instance ID, its instance profile ARN, the role name, the attached policy name, the exact bucket ARN in the policy, and the result of `aws s3api head-bucket --bucket usms-student-data`, which should fail; the failure is the point.
4. Record `USMS_BUCKET_NAME` in `configs/lab-03.env` if `configs/lab-01.env` does not already carry it.

**Constraints**

- `transcript-upload.sh` must not contain, read or reference an access key; if it does, the exercise fails regardless.
- It validates its two arguments and exits non-zero with a usable message if either is missing.
- The `head-bucket` failure is captured, not hidden; its error code is evidence.

**Expected outcome:** a readiness file from which a Lab 4 reader could predict exactly what will change the moment the bucket exists.

**This is what Lab 4 will use.** Lab 4 Step 3 creates the bucket and then re-runs your `head-bucket` check, and the difference between the two results is the whole lesson of that step.

**Hints:** Step 11 traced the chain; this exercise writes it down. Capture the `head-bucket` exit code with `|| true` and record `$?` rather than letting `set -e` abort.

---

## 13. Lab Assessment Checklist

This section is the **in-class assessment for Practical 1**. Read it at the start of the session.

**Lab 02 - VPC**

- [ ] `./scripts/utilities/verify-lab-02.sh` reports `FAIL=0`
- [ ] `configs/lab-02.env` committed, no empty values, no `None`
- [ ] Four subnets across two Availability Zones
- [ ] `usms-private-rt` has no route to any internet gateway

**Lab 03 - EC2**

- [ ] `./scripts/utilities/verify-lab-03.sh` reports `FAIL=0`
- [ ] `usms-web-01` running in `usms-public-subnet-a` with `usms-app-sg` and `usms-ec2-app-profile`
- [ ] `usms-db-01` running in `usms-private-subnet-a` with `usms-db-sg`, no public address, no profile
- [ ] Step 12's `USER DATA PROVEN` line captured as evidence
- [ ] Step 19's `PERSISTENCE PROVEN` line captured as evidence
- [ ] `usms-web-data-vol` attached, with `DeleteOnTermination` `False`
- [ ] `usms-web-golden` AMI exists
- [ ] `outputs/usms-app-key.pem` is `chmod 600` and `git check-ignore -v` names the rule

**Written work**

- [ ] `notes/lab-03-notes.md` answers all seven review questions in prose
- [ ] `labs/lab-03-ec2/exercises.md` contains all five exercises
- [ ] Every Floci limitation you hit is recorded, with what real AWS would have done
- [ ] Screenshots in `screenshots/` for Checkpoints 3, 5 and 6

<!-- 
### 14.2 The in-class practical task - 60 minutes, 60 marks

You will be given the task at the start of the assessment slot and must complete it in your own
repository, live. Work alone. The AWS CLI documentation and your own notes are permitted; the lab
document is not.

The task will be a variation on this shape, so prepare for the shape rather than the specifics:

> The university is adding a **reporting service** to USMS. It must run on its own instance in the
> Availability Zone that currently has the least in it. It must be reachable on TCP 8080 from the
> campus range `10.10.0.0/16` only, never from the public internet. It must be able to read from
> `usms-student-data` but never write to it. It must have a data volume that survives termination.
> Bootstrap it with a user-data script that records its own identity to a log file.
>
> Build it, prove each requirement, and record it in `configs/lab-03.env`. -->

<!-- **Marking scheme**

| Criterion | Marks | What earns full marks |
| --- | --- | --- |
| Correct placement | 8 | The instance is in the right subnet and AZ, and you **derived** which AZ that was rather than guessing |
| Security group | 10 | Exactly the rules required, no more; sourced correctly; every rule has a description |
| No public exposure | 8 | Demonstrated from the route table and the subnet attribute, not from the instance's name |
| IAM | 8 | A read-only role, correctly scoped to the bucket ARN, attached via an instance profile |
| Storage | 8 | Volume in the correct AZ, attached, `DeleteOnTermination` `False`, and you showed all three |
| User data | 8 | Correct heredoc quoting, `bash -n` clean, and proven byte-identical after launch |
| Verification | 10 | You extended `verify-lab-03.sh` with checks for the new resources, including at least one negative assertion |

**Automatic deductions**

| | |
| --- | --- |
| Any resource ID copied by hand instead of captured with `$(...)` | −5 each |
| A resource with no `Project=USMS` tag | −3 each |
| Any credential visible in terminal output, a file, or a screenshot | −20 |
| `floci start`, `docker compose down -v`, or `docker volume prune` used | −20 |
| A claim of success with no verification command behind it | −5 each | -->

<!-- ### 14.3 Viva - 10 minutes, 40 marks

Two questions from this bank, chosen at random. You may use your repository to illustrate an answer,
but the answer must be in your own words.

1. What makes a subnet public? Answer without using the word "public".
2. `usms-db-01` has no public address. Name **two independent** reasons it is unreachable from the
   internet, and say which one would still hold if someone changed the other.
3. Walk through the seven links between a browser and a page served by `usms-web-01`. Which one can
   Floci not verify, and why is that acceptable for this course?
4. Why does `usms-db-sg` reference a security group instead of a CIDR block? Give a change to the
   architecture that would break the CIDR version.
5. There is no access key on `usms-web-01`, yet Lab 4 expects it to write to S3. Explain the
   mechanism, including where the credentials come from and how often they change.
6. Step 6 used a quoted heredoc inside which there was an unquoted one. Explain both choices.
7. What is the difference between the address you saw in Step 10 and the one in Step 13? Describe an
   outage scenario in which that difference matters.
8. Your data volume has `DeleteOnTermination` set to `False`. What exactly happens to it when the
   instance is terminated, and what must you do next?
9. When would you prefer a golden AMI over a user-data script, and when the reverse? Give a case for
   each.
10. Step 19 looked the instances up by tag rather than reusing the shell variable. What would have
    been proven if it had reused the variable? Connect your answer to the persistence bug described in
    Lab 1 Step 14.
11. Floci does not enforce security groups. Given that, how do you know the rules you wrote are
    correct? What class of mistake would your verification catch, and what class would it miss?
12. You are asked to move `usms-web-01` to `us-east-1b`. What can be moved, what must be recreated,
    and what does that tell you about which AWS resources are zonal and which are regional? -->
<!-- 
**Marking**

| Band | Marks | Description |
| --- | --- | --- |
| Excellent | 34–40 | Correct, precise, uses the right vocabulary, distinguishes Floci from real AWS unprompted |
| Good | 26–33 | Correct with minor imprecision; recovers when prompted |
| Satisfactory | 20–25 | The mechanism is understood; the explanation is vague or incomplete |
| Weak | 12–19 | Recalls the commands but not what they did |
| Fail | 0–11 | Cannot explain the system they built | -->

---

## 14. Review Questions

Answer in prose in `notes/lab-03-notes.md`.

1. Step 8 used a subnet and security group from Lab 2, an instance profile from Lab 1, and a key pair and script from Lab 3. For each of the five, say what would have happened had it been wrong or missing, and which failures would have been immediate and which silent.
2. `USMSStudentDataReadWrite` grants access to a bucket that does not exist. Explain why this is valid rather than broken, what it means for the instance today, and precisely what changes the moment Lab 4 runs `create-bucket`. Answer in a full paragraph.
3. User data runs once, at first boot. A colleague proposes putting the application deployment in user data so that "restarting the instance redeploys it". Explain why that does not work, and describe two approaches that do.
4. Compare Step 10's auto-assigned public address with Step 13's Elastic IP on who owns it, when it changes, what it costs, and what happens on stop. Then describe a failover procedure only possible because of the difference.
5. An EBS volume cannot attach across Availability Zones, but its snapshot can be restored into any AZ in the region. What does that say about where each is stored, and what does it imply for a system that must survive the loss of one AZ?
6. Step 14 could not confirm the application was reachable, so it verified six configuration properties instead. Argue that this is or is not an adequate substitute, and name the class of fault it cannot detect.
7. `usms-web-01` and `usms-db-01` are both `t3.micro` from the same AMI. List every difference between them, and say whether each is a property of the instance, its subnet, or the VPC.

---

## 15. KEEP vs CLEAN UP

```text
╔═══════════════════ KEEP ══════════════════════╗    ╔═══════════ CLEAN UP ════════════════╗
║ usms-web-01        Lab 04 uploads from it     ║    ║ usms-admin-01-host                   ║
║ usms-db-01         Lab 06 replaces it         ║    ║   - Exercise 1 practice instance;    ║
║ usms-web-eip       stable address             ║    ║   terminate it in Exercise 4         ║
║ usms-web-data-vol  the durable-storage lesson ║    ║                                      ║
║ usms-web-golden    Lab 08 launch template     ║    ║ templates/lab-03-run-instances-      ║
║ usms-app-key       + outputs/usms-app-key.pem ║    ║   full.json - 300 lines of empty     ║
║ configs/lab-03.env Lab 04 sources it          ║    ║   skeleton; do not commit it         ║
║ labs/lab-03-ec2/user-data.sh                  ║    ║                                      ║
║ templates/lab-03-run-instances.json           ║    ║ outputs/lab-03-userdata.b64 and .sh  ║
║ scripts/utilities/verify-lab-03.sh            ║    ║ outputs/lab-03-pre/post-restart.txt  ║
║ everything from Labs 01 and 02                ║    ║   - evidence; keep until submitted   ║
╚═══════════════════════════════════════════════╝    ╚══════════════════════════════════════╝
```

Clean up the right-hand column when your report is submitted:

```bash
rm -f templates/lab-03-run-instances-full.json
rm -f outputs/lab-03-userdata.b64 outputs/lab-03-userdata.sh
rm -f outputs/lab-03-pre-restart.txt outputs/lab-03-post-restart.txt
git status --short
```

Do **not** run `scripts/cleanup/lab-03-cleanup.sh` or `scripts/cleanup/lab-02-cleanup.sh`. They are for the end of the course, and in that order.

The architecture you now have:

![alt text](image-2.png)

---

## 16. Preparation for the Next Lab

Lab 04 is ECS: the enrolment service moves off a hand-run EC2 instance and onto a cluster that
restarts what it loses.

| From `configs/lab-03.env` | Lab 04 uses it for |
| --- | --- |
| `USMS_WEB_INSTANCE` | Step 2's cross-check that Lab 03 is still intact before building on it, and Exercise 5's reverse lookup back to this same instance |

| From earlier labs | Lab 04 uses it for |
| --- | --- |
| Lab 02 `usms-app-sg` | Becomes the *source* of the enrolment security group's only inbound rule - the web tier is the only thing allowed to call the enrolment API |
| Lab 02 `usms-private-subnet-a` / `-b` | Where the ECS tasks actually run |
| Lab 01 `usms-developer-role` | Assumed before every build in this course, including Lab 04's |
| Lab 03 `usms-web-01`, `usms-db-01` | Both still running, untouched; Lab 04 does not replace them, it adds a second compute path alongside them |

There is no S3 bucket yet. `USMSStudentDataReadWrite` still names a bucket that does not exist; Lab 10 finally creates it, and Lab 04's task role picks up the same policy in the meantime.

Before the next session:

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-02.sh
./scripts/utilities/verify-lab-03.sh
```

You want `FAIL=0` twice. Lab 04 Step 2 re-runs this check first.

Take a snapshot before you finish:

```bash
floci snapshot save practical-01-complete
```

If `floci snapshot` is unavailable, stop Floci first and archive outside the repository:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-practical-01.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-practical-01.tar.gz
```

---

## Appendix - New CLI and JMESPath patterns

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `Reservations[0].Instances[0]` | Two levels of array before the instance - a reservation is one `run-instances` call | Step 10 |
| `Reservations[].Instances[]` | Flatten every instance across every reservation | Step 17 |
| Multi-line `--query` with a `{}` projection | Readable object projections across several lines | Step 10 |
| `--generate-cli-skeleton` | Print the request shape as JSON | Step 7 |
| `--cli-input-json file://...` | Submit a request from a document; command-line flags override it | Step 8 |
| `--user-data file://...` | The CLI base64-encodes it for `run-instances`, but not for `modify-instance-attribute` | Step 8 |
| `aws ec2 wait <condition>` | Poll a `describe-*` until a state is reached; exit 255 on timeout | Step 9 |
| `--filters "Name=instance-state-name,Values=running,stopped"` | Multiple values in one filter, comma-separated | Step 22 |
| `--filters "Name=attachment.instance-id,Values=..."` | Filter a volume by what it is attached to | Step 15 |
| Two `--tag-specifications` arguments in one call | Tag the instance and its root volume separately | Step 16 |
| `sort_by(list, &Field)[].[A,B,C]` | Sort, then project a flat array for `--output text` | Step 19 |
| `stat -c '%a'` vs `stat -f '%Lp'` | GNU and BSD `stat` differ; the verify script tries both | Section 8 |

---

## Sources

- [Amazon EC2 instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Instances.html)
- [Amazon Machine Images (AMIs)](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html)
- [Find an AMI using Systems Manager public parameters](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/finding-an-ami-parameter-store.html)
- [Run commands when you launch an EC2 instance with user data](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [`run-instances` - AWS CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html)
- [Amazon EC2 key pairs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html)
- [IAM roles for Amazon EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)
- [Instance metadata and IMDSv2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html)
- [Elastic IP addresses](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html)
- [Amazon EBS volumes and volume types](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html)
- [Instance lifecycle: stop, start, terminate](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [Burstable performance instances and CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances.html)
- [Generate a CLI skeleton and use `--cli-input-json`](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-skeleton.html)
- [AWS CLI waiters](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-wait.html)

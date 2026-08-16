# Lab 03 — Amazon EC2 and Deploying the USMS Application

*Practical 1, Part B — completing the VPC and EC2 deployment, with in-class assessment*

---

## 1. Lab Overview

Part A built a network with nothing in it. This session puts servers in it.

You will launch the USMS web server into the public subnet you built, attach the security group you
wrote, and give it the instance profile Lab 1 created — three artefacts from two previous labs,
combined in one API call. You will bootstrap it with a user-data script so that it configures itself
at first boot, give it a stable public address, attach a data volume, and launch a second instance
into the private subnet so that the two-tier design stops being a diagram.

Then you will prove things: that the instance profile really is attached, that the user data really
arrived, that stopping and starting an instance changes one address and not the other, and that all
of it survives a restart of the emulator.

The session ends with an **in-class assessment** (Section 14): a timed practical task plus a short
viva. Section 14 tells you exactly what is assessed and how it is marked, so read it at the start of
the session rather than at the end.

**Time:** roughly 3 hours for Steps 1 to 23, plus 60 minutes for the assessment.

**Where this sits in the course**

```text
Lab 01  IAM ..................... roles, policies, usms-ec2-app-profile
Lab 02  VPC ..................... Practical 1 Part A — the network
Lab 03  EC2 .................... THIS LAB — servers inside that network
Lab 04  S3 ...................... the bucket usms-ec2-app-role can already write to
Lab 05  Lambda .................. functions triggered from that bucket
```

---

## 2. Learning Objectives

After completing this laboratory you will be able to:

1. Explain what an AMI, an instance type and an instance store are, and how the three combine to
   produce a running server.
2. Select an AMI programmatically rather than by copying an ID, and explain why the SSM public
   parameter approach is the right one on real AWS.
3. Create an EC2 key pair, store the private key so that it can never be committed, and prove it is
   ignored by Git.
4. Write a user-data bootstrap script and explain exactly when, and how often, it runs.
5. Launch an instance into a specific subnet with a specific security group and a specific instance
   profile, using values sourced from previous labs' env files rather than typed by hand.
6. Use a waiter (`aws ec2 wait`) instead of a sleep, and explain what it actually polls.
7. Generate a request skeleton with `--generate-cli-skeleton` and submit it with `--cli-input-json`,
   and say when that is better than a long command line.
8. Explain the difference between an auto-assigned public IPv4 address and an Elastic IP, and
   demonstrate it by stopping and starting an instance.
9. Create, attach and inspect an EBS volume, and explain the Availability Zone constraint that
   governs where it can go.
10. Create an AMI from a configured instance and explain what that gives you that a user-data script
    does not.
11. Distinguish clearly between what you observed in Floci and what you reasoned about, and defend
    that distinction under questioning.

---

## 3. Prerequisites

- **Lab 1 complete**, including `usms-ec2-app-profile` with `usms-ec2-app-role` inside it.
- **Lab 2 complete**, including Exercise 5. `usms-private-subnet-b` is needed by Lab 3 Exercise 5.
- `./scripts/utilities/verify-lab-02.sh` reports `FAIL=0`.
- Floci running under Compose with `FLOCI_STORAGE_MODE` set to `hybrid`.
- `jq`, `openssl` and `curl` available. Check now:

```bash
for t in jq openssl curl python3; do
  printf '%-10s ' "$t"; command -v "$t" || echo "MISSING"
done
```

**What to look for:** a path for all four. If `jq` is missing, install it before the session
(`sudo apt install jq` or `brew install jq`); several steps below parse JSON with it.

---

## 4. Connection to Previous Labs

### 4.1 Current Environment

```text
Created in previous labs:
- Lab 01: Floci under Compose, hybrid storage, persistence proven
- Lab 01: usms-admins / usms-developers / usms-auditors, three users, three roles
- Lab 01: usms-ec2-app-role  with USMSStudentDataReadWrite attached
- Lab 01: usms-ec2-app-profile  wrapping usms-ec2-app-role
- Lab 01: usms-lambda-exec-role, usms-developer-role, five policies
- Lab 01: configs/course.env, configs/lab-01.env
- Lab 02: usms-vpc 10.0.0.0/16, DNS support and hostnames enabled
- Lab 02: usms-public-subnet-a  10.0.1.0/24  us-east-1a  auto-public-IP on
- Lab 02: usms-public-subnet-b  10.0.2.0/24  us-east-1b
- Lab 02: usms-private-subnet-a 10.0.3.0/24  us-east-1a
- Lab 02: usms-private-subnet-b 10.0.4.0/24  us-east-1b
- Lab 02: usms-igw, usms-nat, usms-public-rt, usms-private-rt
- Lab 02: usms-app-sg, usms-db-sg, usms-private-nacl, usms-s3-endpoint
- Lab 02: configs/lab-02.env, scripts/utilities/verify-lab-02.sh

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

### 4.2 What this lab genuinely reuses

| From | Used here how |
| --- | --- |
| Lab 1 `usms-ec2-app-profile` | Step 8 passes it to `run-instances`; Step 11 reads it back off the running instance |
| Lab 1 `USMSStudentDataReadWrite` | Step 11 traces the chain instance → profile → role → policy, and identifies the one thing still missing |
| Lab 2 `usms-public-subnet-a` | Step 8 launches the web server into it, by ID from `configs/lab-02.env` |
| Lab 2 `usms-private-subnet-a` | Step 16 launches the database-tier instance into it |
| Lab 2 `usms-app-sg` / `usms-db-sg` | Attached at launch in Steps 8 and 16; Step 17 reads the wiring back |
| Lab 2 `USMS_AZ_A` | Step 15 creates the EBS volume in the same AZ as the instance, because it must be |
| Lab 2 `usms-igw` route | Step 14 is only meaningful because Part A gave the public subnet a default route |

### 4.3 The moment two labs meet

Lab 1 created `usms-ec2-app-role`, attached `USMSStudentDataReadWrite` to it, and wrapped it in an
instance profile. Nothing has used it. Lab 2 created a subnet with a route to the internet. Nothing
has been in it.

Step 8 is a single `run-instances` call that consumes both, plus a security group and a key pair.
When it returns an instance ID, four labs' worth of separate objects have become one running system.
That is worth pausing over when you get there — it is the first time this course looks like
infrastructure rather than exercises.

---

## 5. What We Are Building

A two-tier deployment of the USMS application:

- **`usms-web-01`** in `usms-public-subnet-a`. It serves the student portal on port 80. It has a
  public address, an Elastic IP so that the address is stable, `usms-app-sg` controlling who reaches
  it, and `usms-ec2-app-profile` so that it can talk to S3 in Lab 4 without any credentials on disk.
- **`usms-db-01`** in `usms-private-subnet-a`. It has no public address, no route to the internet
  gateway, and a security group that accepts PostgreSQL only from the web tier's security group.

The application itself is deliberately small: a single static page served by nginx, showing the
instance's own identity. The point of this lab is not the application. It is that the application
lands in the right place with the right permissions and the right firewall, and that you can prove
each of those three independently.

!!! note "Floci Limitation — read this before you start, not after"
    Floci models the EC2 **API** thoroughly: instances, states, tags, volumes, images, key pairs,
    Elastic IPs and their relationships all behave as documented, and `describe-*` returns
    realistic data.

    Floci does not, in the community build, boot a real operating system for every instance. Your
    user-data script is stored and returned faithfully, but there may be no cloud-init to execute it
    and no nginx to serve anything. `curl` against the instance's public address will usually fail.

    Real AWS boots an actual virtual machine on real hardware, runs your user data as root at first
    boot, and serves the page.

    **What this changes about the lab:** Step 14 gives a primary path (try the request) and a
    fallback (prove every link in the chain that would make the request work). Nothing in this lab,
    and nothing in the assessment, depends on the request succeeding. What is assessed is whether the
    configuration is right and whether you can explain what would happen on real AWS.

---

## 6. Architecture

```text
                                Internet
                                    |
                          +---------+---------+
                          |     usms-igw      |
                          +---------+---------+
                                    |
  ==================================|========================================
  ||  usms-vpc  10.0.0.0/16         |                                      ||
  ||                                |                                      ||
  ||   usms-public-rt   0.0.0.0/0 --+                                       ||
  ||        |                                                              ||
  ||   +----+-------------------------------------------------------+      ||
  ||   |  usms-public-subnet-a   10.0.1.0/24   us-east-1a            |      ||
  ||   |                                                            |      ||
  ||   |   +----------------------------------------------------+   |      ||
  ||   |   |  usms-web-01                          t3.micro     |   |      ||
  ||   |   |    private 10.0.1.x   public via usms-web-eip      |   |      ||
  ||   |   |    sg      usms-app-sg     (80, 443, 22)           |   |      ||
  ||   |   |    profile usms-ec2-app-profile                    |   |      ||
  ||   |   |              -> usms-ec2-app-role                  |   |      ||
  ||   |   |                   -> USMSStudentDataReadWrite      |   |      ||
  ||   |   |    root  /dev/xvda   8 GiB gp3   delete on term    |   |      ||
  ||   |   |    data  /dev/sdf    8 GiB gp3   usms-web-data-vol |   |      ||
  ||   |   |    user-data: install nginx, write the portal page |   |      ||
  ||   |   +--------------------------+-------------------------+   |      ||
  ||   |                              |                             |      ||
  ||   |   [ usms-nat ]               | tcp 5432                    |      ||
  ||   +------------------------------|-----------------------------+      ||
  ||                                  |                                    ||
  ||   usms-private-rt  0.0.0.0/0 -> usms-nat                              ||
  ||        |                         |                                    ||
  ||   +----+-------------------------v-----------------------------+      ||
  ||   |  usms-private-subnet-a  10.0.3.0/24  us-east-1a            |      ||
  ||   |                                                            |      ||
  ||   |   +----------------------------------------------------+   |      ||
  ||   |   |  usms-db-01                           t3.micro     |   |      ||
  ||   |   |    private 10.0.3.x   NO public address            |   |      ||
  ||   |   |    sg      usms-db-sg   (5432 from usms-app-sg)    |   |      ||
  ||   |   +----------------------------------------------------+   |      ||
  ||   |   guarded by usms-private-nacl                             |      ||
  ||   +------------------------------------------------------------+      ||
  ==========================================================================

  usms-web-golden  <- AMI created from usms-web-01 in Step 20
```

---

## 7. Directory Structure

```text
aws-floci-course/
├── labs/
│   └── lab-03-ec2/
│       ├── README.md                       # this document
│       ├── exercises.md                    # Section 13
│       └── user-data.sh                    # NEW — the bootstrap script
├── configs/
│   └── lab-03.env                          # NEW
├── scripts/
│   ├── utilities/
│   │   └── verify-lab-03.sh                # NEW
│   └── cleanup/
│       └── lab-03-cleanup.sh               # NEW
├── templates/
│   └── lab-03-run-instances.json           # NEW — --generate-cli-skeleton output, filled in
└── outputs/
    ├── usms-app-key.pem                    # SECRET — git-ignored, chmod 600
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
## 8. Step-by-Step Implementation

!!! info "Where to run every command in this lab"
    Unless a step says otherwise, run everything from the repository root:

    ```text
    aws-floci-course/
    ```

### Step 1 — Resume the environment and load three env files

**Purpose**

This lab consumes values from two previous labs. Loading them is now the standard opening, and from
Lab 4 onward it will be assumed rather than shown.

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

./scripts/utilities/whoami.sh

printf '%-24s %s\n' \
  "public subnet a"  "$USMS_PUBLIC_SUBNET_A" \
  "private subnet a" "$USMS_PRIVATE_SUBNET_A" \
  "app security group" "$USMS_APP_SG" \
  "db security group"  "$USMS_DB_SG" \
  "instance profile"   "$USMS_INSTANCE_PROFILE" \
  "availability zone a" "$USMS_AZ_A"
```

**What the command does**

`printf` with more arguments than format specifiers reuses the format string until the arguments run
out — which is why one `printf` prints six lines here. It is a small thing, but it keeps the output
aligned without six separate `echo` calls.

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

> Example output — your IDs will differ.

**What to look for:** six non-empty values. An empty one means `configs/lab-02.env` is incomplete;
go back to Lab 2 Step 24 and regenerate it. Do not proceed with a blank — `run-instances` with an
empty `--subnet-id` produces a `MissingParameter` error much later than you would like.

---

### Step 2 — Confirm Part A's network is intact

**Purpose**

A week may have passed since Part A. Before building on the network, check that it is still there and
still correct — the verification script from Lab 2 does exactly that, and this is what it was for.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
./scripts/utilities/verify-lab-02.sh
```

**Expected result**

```text
...
PASS=33  FAIL=0
```

**What to look for:** `FAIL=0`. Anything else stops this lab. In particular:

- Failures under `== Environment ==` mean the container or its storage mode is wrong. Everything
  below them is a consequence. Fix that first.
- `usms-igw ATTACHED to usms-vpc` failing means the web server will launch happily and be
  unreachable, and nothing in Lab 3 would tell you why.

**Checkpoint 1**

```text
Ready to build
 ├── Floci running, hybrid storage
 ├── lab-01.env + lab-02.env sourced
 └── verify-lab-02.sh: FAIL=0
```

---

### Interlude — what an instance actually is

Three things combine to produce a running EC2 instance, and keeping them separate in your head makes
the rest of this lab easy.

**An AMI (Amazon Machine Image)** is a template for the root disk plus a little metadata:
architecture, virtualisation type, and which block devices to create. It is regional — an AMI ID is
meaningless in another region — and it is immutable. "Launching an instance" means, in part, copying
an AMI into a new EBS volume.

**An instance type** is the hardware: vCPUs, memory, network bandwidth, and whether there is local
storage attached. `t3.micro` means 2 vCPUs, 1 GiB of memory, and burstable CPU — the family letter
(`t`, `m`, `c`, `r`, `g`) tells you the workload it is shaped for, the number is the generation, and
the size is the slice.

**User data** is a blob of text you hand to the instance at launch. On a stock Amazon Linux image,
cloud-init reads it at first boot and, if it starts with `#!`, executes it as root. This is how an
instance configures itself without anybody logging in.

Two facts about user data that catch people out:

- It runs **once**, on first boot, not on every start. Rebooting or stopping and starting does not
  re-run it. (You can change that with a cloud-init directive, but the default is once.)
- It is limited to **16 KB** before base64 encoding. Anything bigger belongs in a script the
  user-data downloads.

And one about storage:

- The **root volume** is created from the AMI and, by default, is deleted when the instance is
  terminated. Anything you care about goes on a separate volume, which is why Step 15 exists.

---

### Step 3 — Choose an AMI

**Purpose**

You need an image ID for `run-instances`. Copying one out of a tutorial is the wrong habit: AMI IDs
differ per region and are replaced every time Amazon patches the image. This step shows how to find
one programmatically, and what the right answer is on real AWS.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, see what this build offers**

```bash
aws ec2 describe-images \
  --owners amazon \
  --query 'Images[].{Id:ImageId,Name:Name,Arch:Architecture,Root:RootDeviceType}' \
  --output table
```

**Command — part 2, capture one**

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

> Example output — your AMI ID will certainly differ, and may differ between Floci builds.

**If `AMI_ID` prints as `None` or an empty line**, this Floci build seeds no images. That is a
limitation, not a mistake on your part. Two options:

```bash
# Option A — register a minimal image of your own, so the rest of the lab is honest about
# where the ID came from.
AMI_ID=$(aws ec2 register-image \
  --name usms-course-base \
  --architecture x86_64 \
  --root-device-name /dev/xvda \
  --virtualization-type hvm \
  --query 'ImageId' --output text)
echo "AMI_ID = $AMI_ID"

# Option B — if register-image is also unsupported, note it in your report and continue with a
# placeholder. Floci does not validate the AMI ID on run-instances.
AMI_ID=ami-00000000000000000
```

Record which option you used. The assessment asks.

!!! note "Floci Limitation — AMIs are metadata, not disk images"
    Floci stores AMI records and returns them from `describe-images`, but there is no actual root
    filesystem behind them and the catalogue is small or empty depending on the build.

    Real AWS publishes thousands of images per region, Amazon-owned and third-party, each backed by
    an actual snapshot, and replaces the Amazon Linux ones roughly monthly with patched versions.

    Take away the technique. On real AWS you should never hard-code an AMI ID; you resolve the
    current one at launch time from an SSM public parameter, which Amazon updates for you:

    ```bash
    aws ssm get-parameter \
      --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      --query 'Parameter.Value' --output text
    ```

    That parameter always names the newest Amazon Linux 2023 image in whichever region you call it
    in. It is what a launch template or CloudFormation stack should reference. Try it against Floci
    — if it returns a `ParameterNotFound`, that is the limitation, and knowing the technique is still
    the point.

---

### Step 4 — Create the key pair and store the private key safely

**Purpose**

A key pair is how you would log in to the instance on real AWS. AWS keeps the public half and injects
it into the instance at first boot; the private half is shown to you exactly once, at creation, and
can never be retrieved again. Losing it means losing shell access to every instance launched with it.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

The redirect is the point. `--query 'KeyMaterial' --output text > outputs/...` sends the private key
**straight to a file**. It never appears on your screen, never enters your terminal's scrollback, and
cannot end up in a screenshot pasted into a lab report. That is the habit; the fact that Floci's key
is a dummy is beside the point.

`chmod 600` is not decoration either. SSH refuses to use a private key that is readable by anyone
else, with an error message that does not mention permissions in its first line.

**Expected result**

```text
-rw------- 1 student student 1704 Aug 15 10:22 outputs/usms-app-key.pem
-----BEGIN RSA PRIVATE KEY-----
```

> Example output — the size and date will differ.

**What to look for:** permissions `-rw-------`, and a first line that begins a PEM block. If the file
contains the word `None`, the query returned nothing and the key was not created — check for an
`InvalidKeyPair.Duplicate` error by re-running without the redirect.

**Verify**

```bash
aws ec2 describe-key-pairs \
  --key-names usms-app-key \
  --query 'KeyPairs[0].{Name:KeyName,Fingerprint:KeyFingerprint,Type:KeyType}' \
  --output table
```

AWS keeps the fingerprint and the public key. It does not keep the private key, which is why this
call cannot give it back to you.

---

### Step 5 — Prove the private key is git-ignored

**Purpose**

Lab 1 committed `.gitignore` as the repository's first commit, before any secret could exist. This is
the moment that decision pays for itself — and, as always in this course, we check rather than trust.

**Run from**

```text
aws-floci-course/
```

**Command**

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

> Example output — your line number may differ.

**What to look for, in order:**

1. `git status --short` shows the new lab folder and **nothing under `outputs/`**.
2. `git check-ignore -v` names the file, the rule that matched, and the line number it is on. Silence
   here means the file is **not** ignored — stop and fix `.gitignore` before doing anything else.
3. `git ls-files outputs/` lists `.gitkeep` and nothing else. That single line proves the pattern is
   `outputs/*` and not `outputs/` — Git cannot re-include a file whose parent directory is excluded,
   so with the wrong pattern this command prints nothing at all and the directory silently vanishes
   from the repository.

---

### Step 6 — Write the user-data bootstrap script

**Purpose**

The USMS student portal has to exist on the instance without anyone logging in to put it there. A
user-data script is how that happens: cloud-init runs it as root at first boot.

**Run from**

```text
aws-floci-course/
```

**Command**

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
<head><meta charset="utf-8"><title>USMS — University Student Management System</title></head>
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

!!! warning "Heredoc quoting — and a nested heredoc, which is where it gets interesting"
    The **outer** heredoc is `<< 'EOF'`, quoted. Everything inside is written to the file literally:
    `$(date ...)`, `${INSTANCE_ID}` and `$TOKEN` must all survive to be evaluated later, on the
    instance, not now, in your shell. Had you written `<< EOF`, your local shell would have expanded
    them and the file would contain the results of running `date` on your laptop, plus several empty
    strings.

    The **inner** heredoc, `<<HTML`, is unquoted on purpose: it runs on the instance, at boot, and
    there `${INSTANCE_ID}` genuinely should expand.

    Compare with Lab 2 Step 15, where the rule pointed the other way, and Lab 2 Step 24, where an
    unquoted heredoc was exactly right. The rule is always the same question: **do I want this
    expanded now, or later?**

**What to look for:** `user-data.sh syntax OK`, and a byte count comfortably under 16,384. If
`bash -n` reports an error, fix it now — a syntax error in user data fails silently at boot, and
debugging it means retrieving a log from a machine you may not be able to log in to.

**Expected result**

```text
user-data.sh syntax OK
1487 labs/lab-03-ec2/user-data.sh
```

> Example output — your byte count will differ.

---

### Step 7 — Generate a request skeleton and fill it in

**Purpose**

`run-instances` has more than fifty parameters. A long command line is hard to review, hard to
diff, and impossible to put in version control meaningfully. `--generate-cli-skeleton` prints the
full request shape as JSON; `--cli-input-json` submits one. This is how you turn an API call into a
reviewable artefact.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, look at the shape**

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

> Example output — the line count varies by CLI version. The point is that it is large.

Skim it. Nearly every field is optional; that is the API's real surface area, and it is worth seeing
once.

**Command — part 2, write the request we actually want**

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
  && echo "valid JSON" || echo "INVALID JSON — fix it before Step 8"

cat templates/lab-03-run-instances.json
```

**What the command does**

Unquoted heredoc again, because the four variables must be expanded now. Then `python3 -m json.tool`
parses it — checking JSON validity before sending it is worth the two seconds, because the CLI's
parse errors point at a byte offset rather than a field.

Note the second `TagSpecifications` entry with `ResourceType: volume`. `run-instances` creates the
root EBS volume as a side effect, and without this it would be untagged. Untagged volumes are how
orphaned storage accumulates in real accounts.

**Expected result**

```text
valid JSON
```

followed by the document, with your real IDs substituted in.

**What to look for:** no `$` remains anywhere in the printed file. If you see the literal text
`$AMI_ID`, you used a quoted heredoc.

---

### Step 8 — Launch the USMS web server

**Purpose**

This is the step the last two labs were building towards. One call, consuming a subnet from Lab 2, a
security group from Lab 2, an instance profile from Lab 1, and a key pair and user-data script from
this one.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
WEB_INSTANCE_ID=$(aws ec2 run-instances \
  --cli-input-json file://templates/lab-03-run-instances.json \
  --user-data file://labs/lab-03-ec2/user-data.sh \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "WEB_INSTANCE_ID = $WEB_INSTANCE_ID"
```

**What the command does**

```text
aws
 └── ec2
      └── run-instances
           ├── --cli-input-json file://...   the whole request, from the JSON document
           ├── --user-data      file://...   merged in on top of the JSON
           ├── --query          'Instances[0].InstanceId'
           └── --output text
```

Two things are worth knowing about this combination.

**Command-line parameters override the JSON.** `--cli-input-json` supplies the base request and
anything you also pass as a flag wins. That is why `--user-data` can be added here rather than
embedded in the document — which matters, because the document would need the script base64-encoded
by hand.

**The CLI base64-encodes user data for you.** The EC2 API requires user data to be base64-encoded.
The AWS CLI does that encoding for `run-instances` when you pass `--user-data file://...`. It does
**not** do it for `modify-instance-attribute`, where you must encode it yourself — an inconsistency
worth remembering, and the reason Step 12 decodes rather than reads.

**Expected result**

```text
WEB_INSTANCE_ID = i-0123456789abcdef0
```

> Example output — your instance ID will differ.

If this fails, the error message names the cause:

| Error | Cause |
| --- | --- |
| `InvalidAMIID.NotFound` | `$AMI_ID` was empty or wrong when Step 7 wrote the JSON. Rewrite it |
| `InvalidSubnetID.NotFound` | `$USMS_PUBLIC_SUBNET_A` was empty. Re-source `configs/lab-02.env` |
| `InvalidGroup.NotFound` | Same, for `$USMS_APP_SG` |
| `InvalidParameterValue: iamInstanceProfile.name` | Lab 1's instance profile does not exist |
| `InvalidKeyPair.NotFound` | Step 4 did not complete |

---

### Step 9 — Wait for the instance to reach `running`

**Purpose**

An instance is not usable the moment `run-instances` returns. It goes `pending`, then `running`, and
only then does anything inside it exist. Scripting this correctly means waiting for the state, not
sleeping for a guess.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
time aws ec2 wait instance-running --instance-ids "$WEB_INSTANCE_ID"
echo "exit code: $?"
```

**What the command does**

`aws ec2 wait <condition>` polls a `describe-*` call on a fixed schedule until a condition is met, a
maximum number of attempts is exhausted, or a terminal failure state is reached. `instance-running`
polls `describe-instances` every 15 seconds, up to 40 times — ten minutes. Exit code 0 means the
condition was met; 255 means it timed out.

Run `aws ec2 wait help` to see the full list. The ones you will use most in this course are
`instance-running`, `instance-status-ok`, `instance-terminated`, `volume-available` and
`volume-in-use`.

The difference between `instance-running` and `instance-status-ok` matters on real AWS:
`instance-running` means the hypervisor has started the virtual machine, which typically happens in
under a minute. `instance-status-ok` means AWS's system and instance status checks have both passed —
the operating system is up and the network is responding. A script that connects to a service should
wait for the latter.

**Expected result**

```text
real    0m2.114s
exit code: 0
```

> Example output — on real AWS this takes 30 to 60 seconds. Floci transitions almost immediately,
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

### Step 10 — Read the instance back and understand the fields

**Purpose**

`describe-instances` returns a large, deeply nested document. Learning to pull the six fields that
matter out of it is more useful than reading all of it once.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

Note `Reservations[0].Instances[0]`. A *reservation* is the batch created by one `run-instances`
call; asking for 5 instances gives one reservation containing five. This is why almost every
`describe-instances` query starts with two array indexes, and why forgetting the first one is the
most common JMESPath mistake in EC2.

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

> Example output — every value here will differ.

**What to look for, and why each one matters:**

- `State` is `running`.
- `Subnet` equals `$USMS_PUBLIC_SUBNET_A`. If it does not, the instance is in the wrong place and
  nothing else in this lab will make sense.
- `PrivateIP` is inside `10.0.1.0/24` — the CIDR you chose in Part A, visible on a real interface.
- `PublicIP` has a value. It has one **only** because Lab 2 Step 8 set `MapPublicIpOnLaunch` on this
  subnet. Launch into the private subnet and this field is empty.
- `SG` is `usms-app-sg`, not `default`.
- `Profile` is a non-null ARN. Step 11 pulls on that thread.

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

### Step 11 — Trace the permission chain from the instance to the policy

**Purpose**

The instance has an instance profile. That is the whole reason there are no AWS credentials anywhere
on this server. This step follows the chain link by link — instance to profile to role to policy —
so that when Lab 4 creates the bucket, you already know why the instance can write to it.

**Run from**

```text
aws-floci-course/
```

**Command**

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

> Example output — the policy body is Lab 1's, unchanged.

**Now read the policy document and answer the question it raises.** It grants `s3:GetObject`,
`s3:PutObject` and `s3:ListBucket` on `arn:aws:s3:::usms-student-data` and
`arn:aws:s3:::usms-student-data/*`, and explicitly denies `s3:DeleteBucket`.

That bucket **does not exist**. It will not exist until Lab 4.

This is not a bug and it is not a mistake in Lab 1. An IAM policy is a statement about ARNs, not a
reference to objects; it is perfectly valid to grant access to a resource that has not been created.
The permission simply has no effect until something appears at that ARN. When Lab 4 runs
`create-bucket`, this policy stops being hypothetical and `usms-web-01` gains the ability to write
transcripts — with no access key anywhere on the machine.

Write that sentence into `notes/lab-03-notes.md` now. It is the single most important idea connecting
Labs 1, 3 and 4, and it is a review question.

!!! note "Floci Limitation — the instance cannot fetch its own credentials"
    On real AWS, an instance with a profile gets temporary credentials from the Instance Metadata
    Service at `169.254.169.254`, rotated automatically several times a day. The SDKs find them with
    no configuration at all, which is why no key ever needs to be on the disk.

    Floci does not serve IMDS to instances, so the `meta` function in your user-data script would
    fail there.

    The chain you just traced is nonetheless real: the association between instance, profile, role and
    policy is stored and returned correctly, and it is the association — not the metadata service —
    that you are being assessed on.

---

### Step 12 — Prove the user data actually arrived

**Purpose**

`run-instances` accepted the script. That is not evidence that it stored what you meant. This is the
create-perturb-read-back pattern applied to a payload rather than to a resource: read the user data
back off the instance, decode it, and compare it byte for byte with the file on disk.

**Run from**

```text
aws-floci-course/
```

**Command**

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
  || echo "MISMATCH — see the diff above"
```

**What the command does**

`describe-instance-attribute --attribute userData` returns the blob base64-encoded, because that is
how the API stores it. `openssl base64 -d` decodes it.

`openssl` rather than `base64` is deliberate. GNU `base64` decodes with `-d`; BSD and older macOS
`base64` uses `-D`. Writing `base64 -d` in a lab script is one of the classic ways to produce a
command that works for half the class. `openssl base64 -d -A` behaves identically on both — `-A`
tells it to accept the input as one long line without embedded newlines.

`diff` producing no output is the pass condition, and it is a stronger claim than "the script looks
right": it proves the CLI's base64 encoding, the API's storage, and the decode all round-tripped
without loss.

**Expected result**

```text
1984 outputs/lab-03-userdata.b64
IyEvYmluL2Jhc2gKIyBVU01TIHdlYiB0aWVyIGJvb3RzdHJhcC4gUnVucyBPTkNFLCBhcyByb290LCBh
USER DATA PROVEN: what EC2 stored is byte-identical to what you wrote
```

> Example output — your byte count will differ. The base64 prefix `IyEvYmluL2Jhc2gK` decodes to
> `#!/bin/bash\n`, which is a useful thing to recognise on sight.

**What to look for:** the `USER DATA PROVEN` line. If `diff` reports differences, the most likely
cause is that Step 6's heredoc was unquoted and your local shell expanded the variables before the
file was written.

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
### Step 13 — Give the web server a stable public address

**Purpose**

The address in Step 10 was auto-assigned. It belongs to the instance only while the instance is
running, and a stop/start cycle produces a different one. A student portal cannot have a DNS record
pointing at an address that changes. An Elastic IP is an address you own, independent of any
instance, that you attach where you want it.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`allocate-address --domain vpc` takes an address out of the pool and gives you an **allocation ID**,
which is the handle for the address itself. `associate-address` binds it to an instance and gives you
an **association ID**, which is the handle for the relationship. Two different identifiers for two
different things, and using the wrong one is a common error.

When you associate an Elastic IP with an instance that already has an auto-assigned public address,
the auto-assigned one is released. The instance ends up with exactly one public address, and it is
yours.

**Expected result**

```text
auto-assigned address before EIP: 54.12.33.201
alloc=eipalloc-0aaa111bbb222ccc3 assoc=eipassoc-0ddd444eee555fff6 address=52.9.144.17
```

> Example output — every address and ID will differ.

**Verify**

```bash
aws ec2 describe-instances --instance-ids "$WEB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].{Public:PublicIpAddress,Private:PrivateIpAddress}' \
  --output table
```

**What to look for:** `Public` now shows the Elastic IP, not the address from Step 10.

!!! note "Floci Limitation — Elastic IPs are plausible, not routable"
    Floci allocates an address that looks like a public IPv4 address, tracks the allocation and the
    association, and returns them correctly. Nothing on the internet routes to it.

    Real AWS gives you an address reachable from anywhere, held until you release it, and — this is
    the part that catches people — **charges you for it while it is not associated with a running
    instance.** An unassociated Elastic IP is the second most common surprise on a first AWS bill,
    after the NAT gateway from Lab 2 Step 19.

    Take away the model: the address is a resource with its own lifecycle, deliberately decoupled
    from the instance so that you can move it during a failover.

---

### Step 14 — Test the application

**Purpose**

Try the thing you built. Then, when it does not answer, work out precisely which link in the chain is
missing — because that reasoning is what the assessment examines.

**Run from**

```text
aws-floci-course/
```

**Command — primary path**

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

This is not a failure of your work. Floci does not boot an operating system for the instance, so
there is no nginx listening. Now prove that everything *you* control is correct.

**Command — fallback, prove every link in the chain**

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

> Example output — your IDs and addresses will differ.

**What to look for:** six answers, none of them `None`. Those six checks are, in order, exactly the
things that must be true for a request from a browser to reach an EC2 instance:

```text
browser
  -> internet gateway            (checks 2 and 3)
  -> route table                 (check 2)
  -> subnet
  -> network ACL                 (check 6)
  -> elastic network interface
  -> security group              (check 4)
  -> instance, running           (check 1)
  -> a process listening on 80   (NOT checked — this is the one Floci cannot give you)
```

Memorise that list. It is the debugging procedure for "I cannot reach my instance" on real AWS, and
it is a viva question in Section 14. Note that the seventh item is the only one this lab cannot
verify — and note that on real AWS it is also the item that is *not* an AWS problem.

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

### Step 15 — Create and attach a data volume

**Purpose**

The root volume is deleted when the instance is terminated. Student records cannot live there. This
step creates a separate EBS volume — an independent resource with its own lifecycle — and attaches
it.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`--availability-zone "$INSTANCE_AZ"` is derived from the instance rather than typed. That is not
style: **an EBS volume can only be attached to an instance in the same Availability Zone.** A volume
is stored in one AZ's storage fabric and cannot cross to another. To move data between AZs you take a
snapshot — which is regional — and create a new volume from it elsewhere.

`gp3` is the current general-purpose SSD type. It gives a baseline 3,000 IOPS and 125 MB/s regardless
of size, where the older `gp2` scaled performance with capacity and forced you to over-provision disk
to buy throughput.

`--device /dev/sdf` is the device name AWS presents to the instance. Modern Amazon Linux with NVMe
storage renames it to something like `/dev/nvme1n1` inside the guest, so a script that mounts by
device name is fragile. Mount by filesystem UUID instead.

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

> Example output — your IDs will differ.

**Verify**

```bash
aws ec2 describe-volumes \
  --filters "Name=attachment.instance-id,Values=$WEB_INSTANCE_ID" \
  --query 'Volumes[].{Id:VolumeId,Size:Size,Type:VolumeType,AZ:AvailabilityZone,Device:Attachments[0].Device,State:Attachments[0].State,DeleteOnTerm:Attachments[0].DeleteOnTermination}' \
  --output table
```

**What to look for:** **two** volumes, not one. The root volume created by `run-instances` from the
AMI, and the one you just made. Compare their `DeleteOnTerm` columns: the root volume is `True` and
your data volume is `False`. That single column is the difference between storage that survives a
terminate and storage that does not.

✏️ **Your turn**

Test the Availability Zone constraint rather than believing it. Create an 8 GiB `gp3` volume in
`$USMS_AZ_B` — the *other* zone — and attempt to attach it to `usms-web-01`, which is in
`$USMS_AZ_A`.

```text
Expected result:
On real AWS: InvalidVolume.ZoneMismatch, naming both zones.
On Floci: record what actually happens — it may accept the attachment, which is
itself a finding worth writing down. Either way, delete the test volume afterwards
and state in one sentence what real AWS would have done.
```

Hint: `aws ec2 delete-volume --volume-id <id>` after detaching, if it attached. This is the only
place in Practical 1 where the expected outcome is an error, which is why it is a "your turn" task
and not an assessed step — see Section 12 for why this course never *depends* on seeing a denial.

---

### Step 16 — Launch the database-tier instance into the private subnet

**Purpose**

One instance in a public subnet is a server. Two instances in different subnets with different
security groups is an architecture. This one has no public address and no path to the internet
gateway, and that is the whole point.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

The long-form command line this time, rather than `--cli-input-json`, so that you have used both. Note
that `--tag-specifications` takes two space-separated arguments here — one for the instance, one for
its root volume.

There is deliberately **no** `--iam-instance-profile`. The database tier has no reason to call the S3
API, and giving it a role it does not need is exactly the privilege creep the course is trying to
teach you to notice.

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

> Example output — your IDs and addresses will differ.

**What to look for, and this is the assessed part:**

- `Private` is inside `10.0.3.0/24`.
- `Public` is `None`. Not blank by accident — the subnet has `MapPublicIpOnLaunch` set to `False`,
  which Lab 2 Step 9 deliberately left alone.
- `SG` is `usms-db-sg`.
- `Profile` is `None`, on purpose.

---

### Step 17 — Prove the two tiers are wired the way you think

**Purpose**

Floci does not enforce security groups, so you cannot demonstrate the data tier refusing a
connection. What you *can* do is read back the configuration that would produce that behaviour, and
show that it is exactly right. That is the honest form of this proof, and it is the form the
assessment expects.

**Run from**

```text
aws-floci-course/
```

**Command**

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

> Example output — your IDs will differ.

**What to look for:**

- `FromCIDR` is `None` and `FromGroup` holds a group ID. An address-based rule here would still
  "work" and would be wrong for the reasons Lab 2 Step 15 gave.
- The private route table's default route targets a NAT gateway, not an internet gateway. Outbound
  yes; inbound no. That asymmetry is what makes `usms-db-01` unreachable, and it is a property of
  routing — it would hold even if someone opened `usms-db-sg` to `0.0.0.0/0` tomorrow.

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

### Step 18 — Stop and start the web server, and watch which address moves

**Purpose**

This is the create-perturb-read-back pattern applied to the Elastic IP claim from Step 13. Stopping
and starting an instance releases an auto-assigned public address and keeps an Elastic IP. You have
been told that. Now check it.

**Run from**

```text
aws-floci-course/
```

**Command**

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
    `stop-instances` is not a delete, but it is the closest thing in this lab, so read this before
    you run it.

    **What will be stopped:** `usms-web-01` only. Not terminated.

    **What depends on it:** nothing in this lab. Its root and data volumes persist, its Elastic IP
    stays allocated, its instance ID does not change.

    **Reversible?** Yes — `start-instances`, which the command above does immediately.

    **Effect on later labs:** none. Do **not** substitute `terminate-instances` here. Termination is
    irreversible, deletes the root volume, and Lab 4 expects `usms-web-01` to exist.

**Expected result on real AWS**

```text
before: web=52.9.144.17  db=10.0.3.42

State: stopped   Public: None       Private: 10.0.1.87
after:
State: running   Public: 52.9.144.17  Private: 10.0.1.87
```

**What to look for, in three parts:**

1. While `stopped`, `PublicIpAddress` is `None`. A stopped instance has no public address at all.
2. After starting, the **Elastic IP is back** and is the same address as before. Had you relied on
   the auto-assigned address from Step 10, you would now have a different one and every DNS record
   pointing at it would be wrong.
3. `PrivateIpAddress` never changed. A private address is held for the life of the instance, not the
   life of the running state.

!!! note "Floci Limitation — the stop/start transition may be instantaneous or absent"
    Some Floci builds move an instance to `stopped` and back without ever clearing the public address
    field, so the middle line reads `Public: 52.9.144.17` throughout.

    Real AWS always releases an auto-assigned address on stop, always keeps an Elastic IP, and always
    keeps the private address.

    If your output does not show the address disappearing, record that as a limitation in your report
    and answer the question in prose instead: *what would have happened, and why does it matter for
    a DNS record?* That is what Section 14's viva asks.

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

Hint: copy the JSON to `templates/lab-03-run-instances-web02.json`, change `SubnetId` and the `Name`
tag, and leave everything else alone. That is the argument for `--cli-input-json` over a long command
line — the diff between the two launches is two lines and is reviewable.

---

### Step 19 — Prove the compute layer survives a restart

**Purpose**

The same proof as Lab 2 Step 23, applied to this lab's work. Lab 4 depends on `usms-web-01` still
being there.

**Run from**

```text
aws-floci-course/
```

**Command — part 1, record the truth**

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=USMS" "Name=instance-state-name,Values=running" \
  --query 'sort_by(Reservations[].Instances[], &InstanceId)[].[InstanceId,SubnetId,SecurityGroups[0].GroupId]' \
  --output text > outputs/lab-03-pre-restart.txt

cat outputs/lab-03-pre-restart.txt
```

**Command — part 2, perturb**

```bash
./scripts/setup/floci-down.sh
sleep 3
./scripts/setup/floci-up.sh
sleep 5
source configs/course.env
```

**Command — part 3, read it back by tag, not by variable**

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

**What the command does**

Everything is looked up **by tag**, not by the instance IDs in your shell variables. Reusing
`$WEB_INSTANCE_ID` would prove only that Bash remembers strings — the same mistake that made an
earlier edition of this course's persistence test worthless. Searching by tag forces the API to find
the resource.

The two `length()` calls check volumes and Elastic IPs as well, because instances surviving while
their storage does not would be a specific and very confusing failure.

**Expected result**

```text
PERSISTENCE PROVEN: same instances, same subnets, same security groups after restart
4
2
```

> Example output — the volume count is 4 if you have two instances plus a data volume and did the
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

### Step 20 — Create an AMI from the configured instance

**Purpose**

User data configures a machine at boot, which takes time and can fail. An AMI captures a machine that
is *already* configured, so the next launch is a copy rather than a rebuild. Understanding when to
use which is a real architectural decision, and Lab 8's Auto Scaling group needs the image.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What the command does**

`--name` must be unique within your account and region, which is why the date is appended — re-running
this step tomorrow works, re-running it twice today does not.

`--no-reboot` tells AWS not to restart the instance before taking the snapshot. It keeps the service
up, at the cost of a filesystem image that was captured while writes were in flight. For a web server
serving static files that is fine; for a database it is not, and you would either allow the reboot or
quiesce the database first. That trade-off is the interesting part of this step.

**Expected result**

```text
WEB_AMI_ID = ami-0abc123def456789a
------------------------------------------------------------
|                      DescribeImages                      |
+---------+---------------------------+---------+----------+
|  Id     |  usms-web-golden-20260815 | State   | available|
+---------+---------------------------+---------+----------+
```

> Example output — your ID and date will differ.

**AMI or user data?** Both, usually:

| | User data | AMI |
| --- | --- | --- |
| Boot time | Slow — installs packages at every launch | Fast — everything is already there |
| Patching | Always gets the latest packages | Frozen at build time; rebuild to patch |
| Auditability | The script is in Git and reviewable | The contents are opaque unless you built it reproducibly |
| Failure mode | A failed install leaves a half-configured live instance | A bad image fails identically every time, which is easier to diagnose |

The common pattern is a "golden" AMI built by an automated pipeline containing the slow, stable parts,
plus a short user-data script for the fast, environment-specific parts. That is exactly the split
between what you baked in here and what `user-data.sh` still does.

**Checkpoint 7**

```text
usms-web-golden  (ami-0abc...)
 └── built from usms-web-01, --no-reboot, tagged Project=USMS
     -> Lab 08 references it from a launch template
```

---

### Step 21 — Audit what this lab created

**Purpose**

Same audit as Lab 2 Step 22, extended to compute resources, so you can see the whole USMS estate in
one table before writing the env file.

**Run from**

```text
aws-floci-course/
```

**Command**

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

**What to look for:** every resource named in Section 4.1's "Created in this lab" block, and nothing
untagged. A resource without a `Name` value in these tables was created without
`--tag-specifications`; fix it with `create-tags` before Step 22, or `configs/lab-03.env` will record
`None` for it.

✏️ **Your turn**

Write a single command that prints, for every running USMS instance, its name, its Availability Zone,
and whether it has a public address — sorted so that instances **without** a public address appear
first. Save it to `outputs/lab-03-exposure-report.txt`.

```text
Expected result:
A table in which usms-db-01 is listed above usms-web-01, because it has no public
address. On a real account this is the report you would run to answer "what of ours
is exposed to the internet?"
```

Hint: `sort_by()` needs something orderable. A null does not sort against a string — think about what
you could map the address to first, or look up `not_null()` in the JMESPath specification.

---

### Step 22 — Write `configs/lab-03.env`

**Purpose**

Lab 4 needs the web instance's ID and the bucket-facing role. Lab 8 needs the AMI. Record them by
lookup, not from shell variables.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cat > configs/lab-03.env << EOF
# Lab 03 — EC2 outputs
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

**What the command does**

Unquoted heredoc, for the same reason as Lab 2 Step 24: every `$(...)` must run now and the *result*
must land in the file.

Note the `instance-state-name` filter with two values. Without it, a terminated instance from a
previous attempt could be returned instead of the live one — terminated instances remain visible to
`describe-instances` for about an hour.

**Verify**

```bash
source configs/lab-03.env
printf '%-24s %s\n' \
  "web instance" "$USMS_WEB_INSTANCE" \
  "db instance"  "$USMS_DB_INSTANCE" \
  "web public IP" "$USMS_WEB_PUBLIC_IP" \
  "golden AMI"   "$USMS_WEB_AMI"
```

**What to look for:** `all values populated`, then four non-empty values. `USMS_WEB_AMI` reading
`None` means Step 20's tag did not apply — check with
`aws ec2 describe-images --owners self --query 'Images[].Tags'`.

---

### Step 23 — Commit

**Purpose**

Same discipline as every lab. Look first, then stage explicitly, then commit.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
git status --short

git check-ignore -v outputs/usms-app-key.pem

git add labs/lab-03-ec2/ configs/lab-03.env templates/lab-03-run-instances.json \
        scripts/utilities/verify-lab-03.sh scripts/cleanup/lab-03-cleanup.sh

git status --short

git commit -m "Lab 03: USMS web and data tier instances, EIP, EBS volume, golden AMI"

git log --oneline -4
```

**What to look for before you type `git commit`:**

- Nothing under `outputs/` is staged. Especially not `usms-app-key.pem`.
- `templates/lab-03-run-instances-full.json` is **not** staged — it is 300 lines of empty skeleton
  and adds nothing to the repository. Add it to `.gitignore` if you like, or just do not stage it.
- `configs/lab-03.env` **is** staged. IDs, no secrets.

**Expected result**

```text
.gitignore:7:outputs/*	outputs/usms-app-key.pem
[main 8c31de4] Lab 03: USMS web and data tier instances, EIP, EBS volume, golden AMI
 6 files changed, 388 insertions(+)
```

> Example output — your hash and counts will differ.

**Checkpoint 8**

```text
Lab 03 recorded
 ├── configs/lab-03.env      committed, fully populated
 ├── templates/              run-instances request under version control
 ├── outputs/usms-app-key.pem  present, chmod 600, git-ignored, PROVEN ignored
 └── git log shows Lab 01, Lab 02 and Lab 03 commits
```

---
## 9. Verification

### 9.1 What this script checks that a naive one would not

Three of the checks below are the ones worth having:

- **`usms-db-01 has NO public address`** — a negative assertion. Nothing else would notice if the
  data tier quietly became reachable.
- **`data volume DeleteOnTermination is False`** — checks the *configuration* that makes the volume
  durable, not merely that a volume exists.
- **`private key is chmod 600 and not tracked by git`** — checks the security property, not the file.

### 9.2 Build `scripts/utilities/verify-lab-03.sh`

**Run from**

```text
aws-floci-course/
```

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

> Example output — the middle is abbreviated; you will see all 36.

**The expected count is `PASS=36  FAIL=0`.**

Two failures have known, benign causes on some Floci builds. Record them in your report rather than
fighting them:

- `usms-db-01 has NO public address` — if Floci assigns one anyway despite `MapPublicIpOnLaunch`
  being `False` on the subnet, that is a Floci limitation. Check the subnet attribute yourself and
  say so.
- `data volume survives termination` — if Floci does not populate `DeleteOnTermination` on
  attachments, the check returns an empty string. Confirm with
  `aws ec2 describe-volumes --volume-ids "$USMS_WEB_DATA_VOLUME" --output json` and note it.

Everything else failing is a real problem with your work.

### 9.3 Build the end-of-course cleanup script

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
# Run this BEFORE scripts/cleanup/lab-02-cleanup.sh — a VPC with running
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
bash -n scripts/cleanup/lab-03-cleanup.sh && echo "syntax OK — do NOT run it"
````

**What to look for:** `syntax OK — do NOT run it`.

The ordering is the lesson again. An Elastic IP must be disassociated before it can be released. A
volume must be detached before it can be deleted, and detaching is asynchronous, so there is a wait.
Instances must be terminated before the VPC that contains them can be deleted — which is why this
script must run before Lab 2's.

---

## 10. Checkpoints

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

## 11. Troubleshooting

??? danger "`InvalidAMIID.NotFound` or `InvalidAMIID.Malformed`"
    `$AMI_ID` was empty or wrong when Step 7 wrote the JSON. Check what the file actually contains:

    ```bash
    grep ImageId templates/lab-03-run-instances.json
    ```

    If it shows `"ImageId": ""` or the literal `$AMI_ID`, redo Step 3 and then Step 7. Remember Step 7
    needs an **unquoted** heredoc.

??? danger "`InvalidSubnetID.NotFound` or `InvalidGroup.NotFound`"
    `configs/lab-02.env` is not sourced in this terminal, or contains `None`.

    ```bash
    source configs/lab-02.env
    grep -n 'None' configs/lab-02.env
    ```

    If a value is `None`, the Lab 2 resource does not exist. Fix it in Lab 2 and regenerate the file
    with Lab 2 Step 24 — do not hand-edit.

??? danger "`InvalidParameterValue: Value () for parameter iamInstanceProfile.name is invalid`"
    `$USMS_INSTANCE_PROFILE` is empty. It comes from `configs/lab-01.env`. Confirm the profile exists
    and has a role in it:

    ```bash
    aws iam get-instance-profile --instance-profile-name usms-ec2-app-profile \
      --query 'InstanceProfile.Roles[0].RoleName' --output text
    ```

    An empty answer means Lab 1's `add-role-to-instance-profile` step never ran. Fix it there.

??? danger "The instance launched but has no public IP address"
    Three possible causes, in the order worth checking:

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
    Expected on Floci — there is no operating system behind the instance. Use Step 14's fallback and
    verify the six configuration links instead. Do **not** spend the session trying to make it
    answer; nothing in the assessment requires it.

    On real AWS, the same six checks plus "is a process listening on port 80" are the complete
    diagnosis.

??? danger "`base64: invalid option -- 'd'` in Step 12"
    You are on macOS with BSD `base64`. Use the `openssl` form given in the step, which works
    everywhere:

    ```bash
    openssl base64 -d -A -in outputs/lab-03-userdata.b64 -out outputs/lab-03-userdata.sh
    ```

??? danger "Step 12's `diff` shows differences"
    Almost always an unquoted heredoc in Step 6. Look at your local copy:

    ```bash
    grep -n 'INSTANCE_ID' labs/lab-03-ec2/user-data.sh
    ```

    If `${INSTANCE_ID}` has already been replaced with an empty string, your shell expanded it when
    the file was written. Rewrite the file with `<< 'EOF'` and relaunch the instance.

??? danger "`InvalidVolume.ZoneMismatch` when attaching the volume"
    The volume and the instance are in different Availability Zones, and a volume cannot cross one.
    Step 15 derives the AZ from the instance precisely to avoid this. If you typed the AZ by hand,
    delete the volume and recreate it in the right zone:

    ```bash
    aws ec2 delete-volume --volume-id "$WEB_VOLUME_ID"
    ```

??? danger "`aws ec2 wait instance-running` returns exit code 255"
    The waiter exhausted its attempts. Either the instance genuinely is not starting, or Floci does
    not drive the state transition. Check the state directly, and use the manual polling loop from
    Step 9.

??? danger "`InvalidKeyPair.Duplicate`"
    You have run Step 4 twice. AWS will not re-issue a private key. Either use the existing pair, or
    delete and recreate it — remembering that any instance launched with the old pair loses its login
    path:

    ```bash
    aws ec2 delete-key-pair --key-name usms-app-key
    rm -f outputs/usms-app-key.pem
    ```

??? danger "`create-image` fails with `InvalidAMIName.Duplicate`"
    You have already created an image with that name today. `--name` must be unique in the account and
    region. Add a time component:

    ```bash
    --name "usms-web-golden-$(date -u +%Y%m%d-%H%M%S)"
    ```

??? danger "Everything is gone after a restart"
    Storage mode, as always. `./scripts/utilities/floci-storage-check.sh`. If it reports
    `FLOCI_STORAGE_MODE=memory`, the container was not started by Compose. The work is not
    recoverable; restore from the Lab 2 snapshot you took at the end of Part A.

---

## 12. Floci vs Real AWS

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| `run-instances`, instance lifecycle states | Real virtual machines | States modelled correctly; no VM | Implemented in Floci |
| `describe-instances` and its whole data model | Full | Full and realistic | Implemented in Floci |
| Key pairs, fingerprints, one-time private key | Full | Full; the key is a dummy | Implemented in Floci |
| Tags on instances and volumes | Full | Full | Implemented in Floci |
| User data storage and base64 round-trip | Full | Full — Step 12 proves it | Implemented in Floci |
| EBS volumes: create, attach, detach, describe | Full | Full at the API level | Implemented in Floci |
| Elastic IP allocate / associate / release | Real routable address | Plausible address, not routable | Floci Limitation |
| `create-image` | Real snapshot of the root volume | Image record with no backing snapshot | Floci Limitation |
| **Booting an operating system** | Yes | **No** — nothing runs inside the instance | Floci Limitation |
| cloud-init executing user data | Yes, once, as root at first boot | Stored but not executed | Floci Limitation |
| Instance Metadata Service at `169.254.169.254` | Yes, IMDSv1 and IMDSv2 | Not served to instances | Floci Limitation |
| Instance profile credentials delivered via IMDS | Yes, rotated automatically | Association stored; no credentials delivered | Floci Limitation |
| Security group enforcement on traffic | Every packet | Not enforced | Floci Limitation |
| Public address released on stop | Always | Build-dependent | Floci Limitation |
| Instance status checks (`instance-status-ok`) | System and instance checks | Not meaningfully modelled | Floci Limitation |
| SSH to the instance | Yes, with the private key | No | Conceptual / Real AWS |
| Instance types differing in real CPU and memory | Yes | Type is a label | Conceptual / Real AWS |
| Cost — per instance-hour, per GB-month, per idle EIP | Real | Free | Conceptual / Real AWS |
| Placement groups, dedicated hosts, spot pricing | Full | Not available | Conceptual / Real AWS |
| EC2 service quotas (vCPU limits per region) | Enforced | Not enforced | Conceptual / Real AWS |

### 12.1 What you actually observed in this lab

```text
OBSERVABLE — you saw this happen
  an instance created in a specific subnet with a specific security group
  the instance profile association, and the chain from it to a named policy
  user data stored and returned byte-identical (Step 12)
  the root volume created by run-instances, with DeleteOnTermination True
  a data volume you created, with DeleteOnTermination False
  the Availability Zone constraint on volume attachment (Step 15 "Your turn")
  the private address surviving a stop/start; the instance ID never changing
  an image record created from a running instance
  all of it surviving a container restart (Step 19)

CONCEPTUAL — you reasoned about it, you did not see it
  nginx starting, or any process running at all
  the user-data script executing
  the instance fetching credentials from IMDS
  a security group permitting or refusing a packet
  the auto-assigned public address being released on stop
  SSH
  the cost of any of it
```

### 12.2 Where Floci is nicer than reality

- **Instances start instantly.** A real `t3.micro` takes 30 to 60 seconds to reach `running` and
  another 30 or so before status checks pass. Code that assumes Floci's speed has a race condition
  in it.
- **AMIs are available immediately.** A real `create-image` on an 8 GiB root volume takes several
  minutes.
- **No cost.** A `t3.micro` is roughly USD 7.50 per month, an 8 GiB `gp3` volume about USD 0.64, and
  an *unassociated* Elastic IP about USD 3.60. The last one surprises people because it charges for
  something they are not using.
- **No quotas.** New accounts get a small vCPU limit per region, and `run-instances` fails against it
  with `VcpuLimitExceeded` rather than queueing.

---

## 13. Independent Lab Exercises

Record commands and output in `labs/lab-03-ec2/exercises.md`.

### Exercise 1 — Basic: a maintenance instance

**Requirements**

Launch `usms-admin-01-host`, a `t3.micro` in `usms-public-subnet-b`, with `usms-app-key`, the
`usms-app-sg` security group, and no instance profile. Tag it `Project=USMS`, `Tier=admin`,
`Lab=03`, and `Ephemeral=true`.

**Constraints**

- Use the long command-line form, not `--cli-input-json`.
- Wait for `running` with a waiter, not `sleep`.
- Do not record it in `configs/lab-03.env`. Exercise 4 removes it.

**Expected outcome**

`describe-instances` filtered on `Name=tag:Tier,Values=admin` returns exactly one running instance in
`us-east-1b`.

**Hints**

Step 16 is the long-form launch. The only new thing is that you are choosing which tags to apply.

---

### Exercise 2 — Intermediate: a self-describing bootstrap

**Requirements**

Write `labs/lab-03-ec2/user-data-db.sh`, a bootstrap script for the data tier that installs
PostgreSQL, creates a database called `usms`, writes a marker file at
`/var/log/usms-db-bootstrap.done` containing the instance ID and the UTC timestamp, and — importantly
— refuses to run twice by checking for that marker first.

Then apply it to a **new** instance `usms-db-02` in `usms-private-subnet-b`, and prove with Step 12's
technique that what EC2 stored is byte-identical to what you wrote.

**Constraints**

- The outer heredoc must be quoted. Say in one sentence why.
- The script must be idempotent: running it a second time must exit early and change nothing.
- Under 16 KB.
- `bash -n` must pass before you launch anything.

**Expected outcome**

A `diff` between your local script and the decoded user data producing no output, and a written
explanation of when a re-run could actually happen given that user data normally runs only once.

**Hints**

Steps 6 and 12 between them contain the whole technique. The idempotence check is three lines of
shell at the top of the script.

---

### Exercise 3 — Problem solving: a reachability report

**Requirements**

Write `scripts/utilities/lab-03-reachability.sh`, which for every running instance tagged
`Project=USMS` prints one line:

```text
usms-web-01  10.0.1.87   52.9.144.17  REACHABLE     igw route + sg allows 80/tcp from 0.0.0.0/0
usms-db-01   10.0.3.42   -            UNREACHABLE   no igw route on subnet
usms-web-02  10.0.2.11   -            NO-ADDRESS    igw route present but no public address
```

The verdict must be **computed** from the route table and the security group, never from the
instance's name or tags.

**Constraints**

- Runs correctly from any directory.
- No hard-coded resource IDs.
- Does not fail when a field is absent — a `None` must not crash it.
- `set -uo pipefail`. Decide about `-e` and justify your decision in a comment.

**Expected outcome**

Identical output when run from `~` and from `~/aws-floci-course/labs/lab-03-ec2/`, correctly
classifying every instance including the ones from Exercises 1 and 2.

**Hints**

Step 14's fallback already answers the question for one instance. The work is generalising it, and
deciding what the verdict should be when a subnet has an internet-gateway route but the instance has
no public address — which is a real state and is neither reachable nor unreachable for the same
reason as the others.

---

### Exercise 4 — Challenge: right-size and clean up

**Requirements**

The USMS project lead writes:

> The portal has 400 concurrent users at peak, mostly reading. Our current single `t3.micro` is at 85
> percent CPU at midday and idle overnight. Finance says our EC2 line is too high and wants a number
> before we change anything. What would you change, what would it cost, and what would you delete
> today?

Produce a written analysis in `labs/lab-03-ec2/exercises.md` covering:

- whether you would scale up (a bigger instance) or out (more instances behind a load balancer), with
  the reasoning, and what each does about the overnight idle time,
- what `t3.micro` burstable CPU credits are and why 85 percent sustained is a specific problem for a
  `t` family instance,
- a concrete monthly cost comparison of at least two options, with the prices cited from a source you
  name,
- what you would delete today: the Exercise 1 admin host, any orphaned volumes, any unassociated
  Elastic IPs. Give the exact commands, in the correct dependency order, each preceded by the
  four-line danger admonition used throughout this lab.

Then execute only the deletions.

**Constraints**

- Do not delete anything named in Section 16's KEEP column.
- Every deletion command must be preceded by its danger admonition in your write-up.
- Verify afterwards that `./scripts/utilities/verify-lab-03.sh` still reports `FAIL=0`.

**Expected outcome**

An analysis with real numbers, and a repository in which the ephemeral resources are gone and the
verification still passes.

**Hints**

The burstable-credit question is the one worth thinking hardest about — a `t3` instance sustained
above its baseline either exhausts its credits and throttles, or silently bills you for unlimited
mode. Which of those happens depends on a setting you have not touched. Find it with
`aws ec2 describe-instance-credit-specifications`.

---

### Exercise 5 — Integration: prepare the S3 hand-off for Lab 4

**Requirements**

Lab 4 creates `usms-student-data`, the bucket `USMSStudentDataReadWrite` has named since Lab 1. Set
up everything on the EC2 side so that Lab 4 is one `create-bucket` away from the permission chain
resolving.

Specifically:

1. Write `labs/lab-03-ec2/transcript-upload.sh` — a script that would run **on** `usms-web-01`,
   taking a student ID and a file path, and uploading it to
   `s3://usms-student-data/transcripts/<student-id>/<filename>` using no credentials at all, relying
   on the instance profile.
2. Add a second inbound rule to `usms-app-sg` allowing TCP 443 outbound is not needed — but confirm,
   and state in one sentence, why the *outbound* rule you never wrote is what makes the S3 call
   possible.
3. Prove the chain is complete on the EC2 side by writing `outputs/lab-03-s3-readiness.txt`
   containing: the instance ID, its instance profile ARN, the role name, the attached policy name,
   the exact bucket ARN in the policy, and the result of
   `aws s3api head-bucket --bucket usms-student-data` — which should fail, and whose failure is the
   point.
4. Record `USMS_BUCKET_NAME` in `configs/lab-03.env` if `configs/lab-01.env` does not already carry
   it, so that Lab 4 can source the intended name rather than re-deriving it.

**Constraints**

- `transcript-upload.sh` must not contain, read, or reference an access key. If it does, the exercise
  is failed regardless of whether it would work.
- It must validate its two arguments and exit non-zero with a usable message if either is missing.
- The `head-bucket` failure must be captured, not hidden — its error code is evidence.

**Expected outcome**

A readiness file that a Lab 4 reader could use to predict, before running a single command, exactly
what will change the moment the bucket exists.

**This is what Lab 4 will use.** Lab 4 Step 3 creates the bucket and then re-runs your
`head-bucket` check, and the difference between the two results is the whole lesson of that step.

**Hints**

Step 11 traced the chain. This exercise writes it down. For the `head-bucket` call, remember that a
non-zero exit code is information — capture it with `|| true` and record `$?` rather than letting
`set -e` abort the script.

---

## 14. Lab Assessment Checklist

This section is the **in-class assessment for Practical 1**. Read it at the start of the session.

### 14.1 Submission checklist

Everything below is checkable from your own repository.

**Part A — VPC (Lab 02)**

- [ ] `./scripts/utilities/verify-lab-02.sh` reports `FAIL=0`
- [ ] `configs/lab-02.env` committed, no empty values, no `None`
- [ ] Four subnets across two Availability Zones
- [ ] `usms-private-rt` has no route to any internet gateway

**Part B — EC2 (Lab 03)**

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

### 14.2 The in-class practical task — 60 minutes, 60 marks

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
> Build it, prove each requirement, and record it in `configs/lab-03.env`.

**Marking scheme**

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
| A claim of success with no verification command behind it | −5 each |

### 14.3 Viva — 10 minutes, 40 marks

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
    and what does that tell you about which AWS resources are zonal and which are regional?

**Marking**

| Band | Marks | Description |
| --- | --- | --- |
| Excellent | 34–40 | Correct, precise, uses the right vocabulary, distinguishes Floci from real AWS unprompted |
| Good | 26–33 | Correct with minor imprecision; recovers when prompted |
| Satisfactory | 20–25 | The mechanism is understood; the explanation is vague or incomplete |
| Weak | 12–19 | Recalls the commands but not what they did |
| Fail | 0–11 | Cannot explain the system they built |

---

## 15. Review Questions

Answer in prose in `notes/lab-03-notes.md`.

1. Step 8 launched an instance using a subnet from Lab 2, a security group from Lab 2, an instance
   profile from Lab 1, and a key pair and script from Lab 3. For each of those five, say what would
   have happened had it been wrong or missing — and note which failures would have been immediate and
   which would have been silent.

2. `USMSStudentDataReadWrite` grants access to a bucket that does not exist. Explain why this is
   valid rather than broken, what it means for the instance today, and precisely what changes at the
   moment Lab 4 runs `create-bucket`. This is the most important connection in the course so far;
   answer it in a full paragraph.

3. User data runs once, at first boot. A colleague proposes putting the application deployment in
   user data so that "restarting the instance redeploys it". Explain why that does not work, and
   describe two approaches that do.

4. Compare the auto-assigned public address from Step 10 with the Elastic IP from Step 13 across
   four dimensions: who owns it, when it changes, what it costs, and what happens to it when the
   instance stops. Then describe a failover procedure that is only possible because of the
   difference.

5. An EBS volume cannot be attached across Availability Zones, but a snapshot of it can be restored
   into any AZ in the region. Explain what that tells you about where each of the two is stored, and
   what it implies for designing a system that must survive the loss of one AZ.

6. Step 14 could not confirm that the application was reachable, so it verified six configuration
   properties instead. Argue either that this is an adequate substitute or that it is not — and, in
   either case, name the specific class of fault it cannot detect.

7. Both `usms-web-01` and `usms-db-01` are `t3.micro` instances launched from the same AMI. List
   every difference between them, and for each one say whether it is a property of the instance, of
   the subnet it is in, or of the VPC around it. This question is asking whether you can tell the
   three apart.

---

## 16. What We Built

### 16.1 Reflection

Practical 1 set out to build a network and put an application in it. Both halves are done, and the
second half is where the course stopped being a set of exercises.

Step 8 is the moment to remember. A single `run-instances` call reached back into Lab 1 for an
instance profile, into Lab 2 for a subnet and a security group, and into this lab for a key pair and
a bootstrap script — and produced a running server that has no credentials on it, sits behind a
firewall you wrote, and is addressable at a stable public address you own. None of those pieces was
built with the others in view. They fit because the naming and the tagging and the env files made
them fit.

The second thing worth keeping is the seven-link chain in Step 14. When something on real AWS is
unreachable, that list is the diagnosis, in order, and six of its seven links are things you can check
with a `describe-*` call. The seventh — is a process actually listening — is the one AWS cannot help
you with, and it is remarkable how often it is the answer.

The third is the discipline the course keeps returning to. Every command in this lab reported
success. Step 12 proved the user data was stored, Step 17 proved the two tiers were wired as intended,
and Step 19 proved all of it survives a restart. Three proofs, each of a property something later
depends on. A command that appears to succeed is still not evidence that it did what you meant.

### 16.2 KEEP vs CLEAN UP

```text
╔═══════════════════ KEEP ══════════════════════╗    ╔═══════════ CLEAN UP ════════════════╗
║ usms-web-01        Lab 04 uploads from it     ║    ║ usms-admin-01-host                   ║
║ usms-db-01         Lab 06 replaces it         ║    ║   — Exercise 1 practice instance;    ║
║ usms-web-eip       stable address             ║    ║   terminate it in Exercise 4         ║
║ usms-web-data-vol  the durable-storage lesson ║    ║                                      ║
║ usms-web-golden    Lab 08 launch template     ║    ║ templates/lab-03-run-instances-      ║
║ usms-app-key       + outputs/usms-app-key.pem ║    ║   full.json — 300 lines of empty     ║
║ configs/lab-03.env Lab 04 sources it          ║    ║   skeleton; do not commit it         ║
║ labs/lab-03-ec2/user-data.sh                  ║    ║                                      ║
║ templates/lab-03-run-instances.json           ║    ║ outputs/lab-03-userdata.b64 and .sh  ║
║ scripts/utilities/verify-lab-03.sh            ║    ║ outputs/lab-03-pre/post-restart.txt  ║
║ everything from Labs 01 and 02                ║    ║   — evidence; keep until submitted   ║
╚═══════════════════════════════════════════════╝    ╚══════════════════════════════════════╝
```

Clean up the right-hand column when your report is submitted:

```bash
rm -f templates/lab-03-run-instances-full.json
rm -f outputs/lab-03-userdata.b64 outputs/lab-03-userdata.sh
rm -f outputs/lab-03-pre-restart.txt outputs/lab-03-post-restart.txt
git status --short
```

Do **not** run `scripts/cleanup/lab-03-cleanup.sh` or `scripts/cleanup/lab-02-cleanup.sh`. They are
for the end of the course, and in that order.

### 16.3 The architecture you now have

```text
Lab 01  IAM
  usms-developer-role ................... used in Lab 02
  usms-ec2-app-role + usms-ec2-app-profile  ATTACHED TO usms-web-01
  USMSStudentDataReadWrite .............. names a bucket that does not exist yet -> Lab 04
  usms-lambda-exec-role ................. waiting for Lab 05

Lab 02  NETWORK
  usms-vpc 10.0.0.0/16
    usms-public-subnet-a / -b   -> usms-public-rt  -> usms-igw
    usms-private-subnet-a / -b  -> usms-private-rt -> usms-nat
                                                   -> usms-s3-endpoint
    usms-app-sg, usms-db-sg, usms-private-nacl

Lab 03  COMPUTE                                        <-- you are here
  usms-web-01   public subnet a   usms-app-sg   usms-ec2-app-profile
                usms-web-eip      /dev/sdf usms-web-data-vol
                user-data: nginx + the USMS portal page
  usms-db-01    private subnet a  usms-db-sg    no profile, no public address
  usms-web-golden  AMI            -> Lab 08

Lab 04  STORAGE (next)
  usms-student-data  <- the bucket that makes USMSStudentDataReadWrite real
```

---

## 17. Preparation for the Next Lab

Lab 4 is S3, and it is the lab where Lab 1's policy finally resolves.

| From `configs/lab-03.env` | Lab 4 uses it for |
| --- | --- |
| `USMS_WEB_INSTANCE` | Demonstrating that the instance's role, not a key, grants the access |
| `USMS_WEB_PUBLIC_IP` | Referencing the portal in the bucket's website configuration exercise |
| `USMS_BUCKET_NAME` | The bucket name to create, sourced rather than retyped |

| From earlier labs | Lab 4 uses it for |
| --- | --- |
| Lab 1 `USMSStudentDataReadWrite` | Lab 4 Step 3 creates the bucket at the ARN this policy names |
| Lab 1 `usms-ec2-app-role` | The principal in the bucket policy |
| Lab 2 `usms-s3-endpoint` | Explaining why a private instance reaches S3 without a NAT hop |

**Before the next session:**

```bash
cd ~/aws-floci-course
./scripts/utilities/verify-lab-02.sh
./scripts/utilities/verify-lab-03.sh
aws s3api head-bucket --bucket usms-student-data ; echo "exit code: $?"
```

You want `FAIL=0` twice, and a **non-zero** exit code from `head-bucket` — probably 254, with a
`404` or `NoSuchBucket` message. Save that output. Lab 4 Step 3 runs the same command after creating
the bucket, and the difference between the two is the point of the step.

**Read ahead, five minutes:** find out what makes an S3 bucket name globally unique, and what the
difference is between the `aws s3` and `aws s3api` command sets. Lab 4 uses both, deliberately.

Take a snapshot before you finish:

```bash
floci snapshot save practical-01-complete
```

If `floci snapshot` is not available on your build, stop Floci first — archiving a live data
directory can capture a half-written file — and use the filesystem fallback:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-practical-01.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-practical-01.tar.gz
```

Keep the archive in your home directory, outside the repository, so it is never a commit candidate.

---

## Appendix A — Command Reference

| Command | What it does |
| --- | --- |
| `aws ec2 describe-images` | List AMIs; `--owners amazon` or `--owners self` |
| `aws ec2 register-image` | Create an AMI record from parameters rather than from an instance |
| `aws ec2 deregister-image` | Remove an AMI; does not delete its snapshots |
| `aws ssm get-parameter` | Read an SSM parameter — how you resolve the current AMI on real AWS |
| `aws ec2 create-key-pair` | Create a key pair; the private key is returned exactly once |
| `aws ec2 describe-key-pairs` | Read back the name, fingerprint and type — never the private key |
| `aws ec2 delete-key-pair` | Delete the public half; existing instances keep the injected key |
| `aws ec2 run-instances` | Launch instances |
| `aws ec2 --generate-cli-skeleton` | Print the full request shape as JSON |
| `aws ec2 --cli-input-json file://...` | Submit a request from a JSON document |
| `aws ec2 describe-instances` | Read instances; note `Reservations[].Instances[]` |
| `aws ec2 describe-instance-attribute` | Read one attribute, including `userData` (base64) |
| `aws ec2 wait instance-running` | Block until the instance is running |
| `aws ec2 wait instance-stopped` | Block until it is stopped |
| `aws ec2 wait instance-terminated` | Block until it is gone |
| `aws ec2 wait volume-available` | Block until a volume is detached and usable |
| `aws ec2 stop-instances` / `start-instances` | Stop and start; reversible |
| `aws ec2 terminate-instances` | Irreversible; deletes volumes marked `DeleteOnTermination` |
| `aws ec2 describe-instance-credit-specifications` | Whether a `t` instance is `standard` or `unlimited` |
| `aws ec2 allocate-address` / `release-address` | Elastic IP lifecycle |
| `aws ec2 associate-address` / `disassociate-address` | Bind an Elastic IP to an instance |
| `aws ec2 create-volume` / `delete-volume` | EBS volume lifecycle |
| `aws ec2 attach-volume` / `detach-volume` | Attach an EBS volume to an instance in the same AZ |
| `aws ec2 describe-volumes` | Read volumes; filter on `attachment.instance-id` |
| `aws ec2 create-image` | Create an AMI from a running instance |
| `aws s3api head-bucket` | Test whether a bucket exists and is reachable by you |
| `openssl base64 -d -A` | Portable base64 decode — works on Linux and macOS alike |

---

## Appendix B — New JMESPath and CLI patterns introduced

| Pattern | Meaning | Where it appeared |
| --- | --- | --- |
| `Reservations[0].Instances[0]` | Two levels of array before the instance — a reservation is one `run-instances` call | Step 10 |
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
| `stat -c '%a'` vs `stat -f '%Lp'` | GNU and BSD `stat` differ; the verify script tries both | Section 9 |

---

## Sources

- [Amazon EC2 instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Instances.html)
- [Amazon Machine Images (AMIs)](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html)
- [Find an AMI using Systems Manager public parameters](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/finding-an-ami-parameter-store.html)
- [Run commands when you launch an EC2 instance with user data](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [`run-instances` — AWS CLI reference](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html)
- [Amazon EC2 key pairs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html)
- [IAM roles for Amazon EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)
- [Instance metadata and IMDSv2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html)
- [Elastic IP addresses](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html)
- [Amazon EBS volumes and volume types](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html)
- [Instance lifecycle: stop, start, terminate](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)
- [Burstable performance instances and CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances.html)
- [Generate a CLI skeleton and use `--cli-input-json`](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-skeleton.html)
- [AWS CLI waiters](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-wait.html)

---

*Practical 1 complete. Lab 04 — S3 — creates the bucket that has been named in an IAM policy since
Lab 1, and `usms-web-01` will write to it with no credentials on disk.*
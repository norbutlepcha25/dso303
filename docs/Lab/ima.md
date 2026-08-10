# Lab 1 

## Lab Objective

By the end of this laboratory you should be able to:

**Environment**

1. Verify that Docker is installed and running.
2. Install, start, stop and inspect the **Floci** local AWS emulator.
3. Install AWS CLI v2 and confirm its version.
4. Create and use a named **AWS CLI profile** that points at Floci.
5. **Prove** that your commands reach Floci and never touch real AWS.
6. Create and explain a clean, version-controlled project directory structure.

**AWS CLI**

7. Read the `aws <service> <command> [options]` grammar and use `help`.
8. Switch between `--output json`, `--output table` and `--output text`.
9. Extract a single value with `--query` (JMESPath) and store it in a shell variable.
10. Pass a JSON file to a command with `file://` and generate a template with `--generate-cli-skeleton`.
11. Interpret AWS CLI exit codes and error messages.

**IAM**

12. Explain the structure of an ARN and read one correctly.
13. Create IAM users, groups and role using the CLI.
14. Write a valid IAM policy document (Version, Statement, Effect, Action, Resource, Condition).
15. Distinguish AWS managed, customer managed and inline policies, and choose between them.
16. Distinguish a **permissions policy** from a **trust policy**.
17. Create an instance profile and understand why EC2 needs one.
18. Obtain temporary credentials with `sts assume-role` and use them.
19. Create access keys and store them without ever committing them to Git.
20. Apply the principle of **least privilege** and diagnose an `AccessDenied` error.


## 4. Connection to Previous Labs

```text
This lab assumes NOTHING has been completed before it.
```

Lab 1 is the first laboratory of the course. It therefore has a double job:

1. **Bootstrap** the entire working environment (Part A).
2. **Build the IAM foundation** that every later lab depends on (Part B).

### Current Environment

```text
Created in previous labs:
- (nothing — this is Lab 1)

Created in this lab:
- Project directory ~/aws-floci-course with full folder structure
- Floci running locally on port 4566 with persistent storage
- AWS CLI v2 installed, profile "floci" configured
- IAM groups:   usms-admins, usms-developers, usms-auditors
- IAM users:    usms-admin-01, usms-dev-01, usms-audit-01
- Policies:     USMSDeveloperBase, USMSStudentDataReadWrite,
                USMSAssumeAppRoles, USMSSelfManageCredentials (inline),
                AWS managed ReadOnlyAccess
- IAM roles:    usms-ec2-app-role, usms-lambda-exec-role, usms-developer-role
- Instance profile: usms-ec2-app-profile
- Access keys for usms-dev-01 (stored outside Git)
- configs/course.env and configs/lab-01.env

Required for future labs:
- usms-developer-role      → Lab 02 (VPC) will be built "as" this role
- usms-ec2-app-profile     → Lab 03 (EC2) attaches this to the instance
- USMSStudentDataReadWrite → Lab 04 (S3) uses this against the real bucket
- usms-lambda-exec-role    → Lab 05 (Lambda) uses this as the execution role
- configs/course.env       → sourced by every later lab
```

---

## 5. What We Are Building

### 5.1 The identity model

Three human-shaped identities and three machine-shaped identities:

| Identity | Type | Who/what uses it | Permissions |
| --- | --- | --- | --- |
| `usms-admin-01` | user → `usms-admins` | The lead cloud engineer | Broad (course-scoped) |
| `usms-dev-01` | user → `usms-developers` | You, building infrastructure | Build + inspect USMS resources |
| `usms-audit-01` | user → `usms-auditors` | The university auditor | Read-only, everywhere |
| `usms-ec2-app-role` | role | The USMS application server | Read/write student data in S3 |
| `usms-lambda-exec-role` | role | Notification functions (Lab 05) | Logs + messaging |
| `usms-developer-role` | role | Assumed *temporarily* by developers | Elevated build permissions |

### 5.2 Why groups instead of attaching policies to users?

Attaching a policy to each user does not scale. When your team grows from 3 to 30 engineers, you
would have to remember to attach five policies to each new person, and remove them one by one when
somebody leaves.

```text
BAD                              GOOD
policy ─→ user1                  policy ─→ group ─→ user1
policy ─→ user2                                 ─→ user2
policy ─→ user3                                 ─→ user3
(3 attachments per policy)       (1 attachment; membership is the only change)
```

Rule for the whole course: **permissions attach to groups and roles, never directly to users**
(with one deliberate exception in Step 22, which exists to teach inline policies).

---

## 7. Directory Structure

### 7.1 The structure you will create

```text
aws-floci-course/
├── README.md                  # course front page (you write it, committed)
├── .gitignore                 # protects secrets (you write it, committed)
│
├── labs/                      # one folder per laboratory
│   └── lab-01-iam/
│       └── README.md          # your notes + evidence for this lab
│
├── policies/                  # JSON policy documents (committed)
│   ├── usms-developer-base-policy.json
│   ├── usms-student-data-rw-policy.json
│   ├── usms-assume-app-roles-policy.json
│   ├── usms-self-manage-credentials.json
│   ├── trust-ec2.json
│   ├── trust-lambda.json
│   └── trust-account-developers.json
│
├── configs/                   # non-secret configuration (committed)
│   ├── course.env             # values reused by EVERY lab
│   └── lab-01.env             # ARNs/IDs produced by this lab
│
├── scripts/
│   ├── setup/                 # bring the environment up
│   │   └── floci-up.sh
│   ├── utilities/             # small helpers reused all course
│   │   ├── aws-env.sh
│   │   └── whoami.sh
│   └── cleanup/               # careful, controlled teardown
│       └── lab-01-cleanup.sh
│
├── templates/                 # CLI skeletons, CloudFormation (later labs)
├── outputs/                   # command output + SECRETS (never committed)
├── screenshots/               # evidence for your lab report
└── notes/                     # your own learning notes
    └── lab-01-notes.md
```

### 7.2 Why each folder exists

| Folder | Purpose | Who creates the files | Commit to Git? |
| --- | --- | --- | --- |
| `labs/` | One folder per lab; your working area and write-up | You | ✅ Yes |
| `policies/` | Reusable JSON policy documents. Kept **outside** `labs/` because Lab 4 will reuse a policy written in Lab 1 | You | ✅ Yes |
| `configs/` | Environment values (region, endpoint, ARNs). No secrets | You + scripts | ✅ Yes |
| `scripts/setup/` | Idempotent scripts that build things | You | ✅ Yes |
| `scripts/utilities/` | Small helpers (`whoami.sh`) used every lab | You | ✅ Yes |
| `scripts/cleanup/` | Deletion scripts — reviewed before running | You | ✅ Yes |
| `templates/` | `--generate-cli-skeleton` output, CloudFormation templates | Generated | ✅ Yes |
| `outputs/` | Raw JSON responses **and access keys** | Generated | ❌ **Never** |
| `screenshots/` | Proof for your submitted report | You | ⚠️ Optional (size) |
| `notes/` | Your own understanding, mistakes, fixes | You | ✅ Yes |

!!! danger "The single most important rule in this table"
    `outputs/` will contain a **real secret access key** after Step 28. It is listed in `.gitignore`
    for that reason. Publishing AWS access keys to a public Git repository is one of the most common
    causes of real-world cloud breaches — bots scan GitHub for them within seconds of a push.

---

## 8. Step-by-Step Implementation

The lab has two parts:

- **Part A — Steps 1 to 12**: build the environment. No IAM yet.
- **Part B — Steps 13 to 30**: build the IAM foundation for USMS.

---

## PART A — Environment Setup (Steps 1–12)

---

### Step 1 — Open a terminal and identify your system

**Purpose**

Every later step depends on knowing which operating system and shell you are using.

**Run from**

```text
anywhere
```

**Command**

```bash
uname -s -m
echo "shell = $SHELL"
```

**What the command does**

- `uname` prints information about the system kernel.
- `-s` prints the **s**ystem name (`Linux` or `Darwin` for macOS).
- `-m` prints the **m**achine hardware name (`x86_64` for Intel/AMD, `arm64`/`aarch64` for Apple Silicon).
- `$SHELL` is an **environment variable** — a named value your shell keeps in memory. `echo` prints it.

**Expected result**

```text
Linux x86_64
shell = /bin/bash
```

> Example output — yours will differ. macOS on Apple Silicon shows `Darwin arm64`.

**Checkpoint**

```text
You know your OS and architecture.
If you are on Windows and this command failed, you are not in WSL. Go back to Section 3.3.
```

---

### Step 2 — Verify Docker is installed and running

**Purpose**

Floci runs as a Docker container. If Docker is not running, nothing else in this course works.

**Run from**

```text
anywhere
```

**Command**

```bash
docker --version
docker info --format '{{ServerVersion}}'
```

**What the command does**

- `docker --version` asks the **Docker client** (the command-line program) its version. This succeeds
  even if Docker itself is not running.
- `docker info` talks to the **Docker daemon** (the background service that actually runs containers).
  This is the real test. `--format '{{ServerVersion}}'` prints just one field instead of 60 lines.

Understanding the client/daemon split matters: the most common Docker error in this course is
"client works, daemon is not running".

**Expected result**

```text
Docker version 27.3.1, build ce1223035a
27.3.1
```

> Example output — version numbers will differ.

**If Docker is not installed**

=== "Linux (Ubuntu/Debian)"

    ```bash
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    newgrp docker
    ```

    `usermod -aG docker $USER` adds you to the `docker` group so you don't need `sudo` for every
    command. `newgrp docker` applies the new group in the current shell without logging out.

=== "macOS"

    Download **Docker Desktop** from `https://www.docker.com/products/docker-desktop/`, install it,
    and launch it from Applications. Wait until the whale icon in the menu bar stops animating.

=== "Windows (WSL2)"

    Install **Docker Desktop for Windows**, then enable
    *Settings → Resources → WSL Integration → Ubuntu*. Verify from the **Ubuntu** terminal, not
    PowerShell.

**Verify**

```bash
docker run --rm hello-world
```

`--rm` deletes the container as soon as it finishes, so it leaves nothing behind.

**Checkpoint 1**

```text
Docker
 ├── client   : installed
 ├── daemon   : running
 └── test run : "Hello from Docker!" printed
```

---

### Step 3 — Install the Floci CLI

**Purpose**

Floci is the **local AWS emulator** this course uses instead of a real AWS account. The Floci CLI is a
small program that starts, stops and inspects the emulator container for you.

**What Floci is**

Floci is an open-source, MIT-licensed local cloud emulator. It listens on a port on your machine and
answers AWS API calls exactly as the real AWS endpoints would — so the **AWS CLI cannot tell the
difference**. It supports around 69 AWS services, including all of IAM and STS.

**Why we use it**

| Real AWS | Floci |
| --- | --- |
| Requires an account + credit card | Requires nothing |
| Mistakes can cost money | Mistakes cost nothing |
| Requires internet | Runs offline |
| Deleting resources takes minutes | Reset in seconds |
| Shared classroom account = chaos | Every student has a private "cloud" |

**Run from**

```text
anywhere
```

**Command**

=== "Linux / macOS (install script)"

    ```bash
    curl -fsSL https://floci.io/install.sh | sh
    ```

=== "macOS / Linux (Homebrew)"

    ```bash
    brew install floci-io/floci/floci
    ```

=== "Windows (PowerShell, then use WSL)"

    ```powershell
    irm https://floci.io/install.ps1 | iex
    ```

    Preferably, install inside **WSL Ubuntu** using the Linux install script instead, so the CLI and
    your labs share one filesystem.

**What the command does**

- `curl` downloads a file from a URL. `-f` fail silently on HTTP errors, `-s` silent,
  `-S` still show errors, `-L` follow redirects.
- `| sh` pipes the downloaded script into the shell to execute it.

!!! warning "Piping a script from the internet into your shell"
    `curl ... | sh` runs code you have not read. In this course it is acceptable because Floci is a
    known open-source project, but in professional work you should download first, read, then run:
    ```bash
    curl -fsSL https://floci.io/install.sh -o floci-install.sh
    less floci-install.sh          # read it
    sh floci-install.sh            # then run it
    ```

**Verify**

```bash
floci version
```

**Expected result**

```text
floci CLI  1.x.x
server     1.x.x
```

> Example output — versions will differ.

**Troubleshoot: `floci: command not found`**

The installer put the binary in a directory that is not in your `PATH` (the list of folders your
shell searches for programs). Fix it:

```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

The first line fixes the current terminal; the second makes it permanent for new terminals.
(If your shell is `zsh`, use `~/.zshrc` instead of `~/.bashrc`.)

---

### Step 4 — Run Floci's environment diagnostics

**Purpose**

Catch problems *before* they turn into confusing AWS CLI errors.

**Command**

```bash
floci doctor
```

**What the command does**

`doctor` checks the things Floci needs: Docker present, Docker daemon reachable, port 4566 free,
enough disk, correct architecture image available.

**Expected result**

```text
✔ docker installed
✔ docker daemon reachable
✔ port 4566 available
✔ image floci/floci:latest available
```

> Example output — exact wording varies by version.

**If port 4566 is already in use**

```bash
# see what is holding the port
sudo lsof -i :4566
```

Either stop that program, or start Floci on a different port (Step 5 shows `--port`). If you change
the port, you must change it **everywhere** in this course — which is exactly why we will store it in
a config file once instead of typing it repeatedly.

---

### Step 5 — Start Floci with persistent storage

**Purpose**

Start the emulator, and make sure the IAM users you create today still exist tomorrow.

**Concept: storage modes**

Floci can keep its state in several ways, controlled by `FLOCI_STORAGE_MODE`:

| Mode | Behaviour | Good for |
| --- | --- | --- |
| `memory` | Everything lost when the container stops | CI pipelines, throwaway tests |
| `hybrid` | Held in memory, flushed to disk every ~5 s | **Development — our choice** |
| `persistent` | Written to disk immediately | Maximum safety, slower |
| `wal` | Write-ahead log | Maximum durability |

The default is `memory`. **That is wrong for this course** — a cumulative course cannot afford to
lose Lab 1's users before Lab 2. We therefore start Floci with a persistence directory.

**Run from**

```text
anywhere (we will move it into a script in Step 12)
```

**Command**

```bash
mkdir -p ~/floci-data
floci start --persist ~/floci-data --detach
```

**What the command does**

- `mkdir -p` creates a directory; `-p` means "create parents as needed, and do not error if it
  already exists" — this makes the command safe to run twice.
- `floci start` pulls the image if needed and runs the container.
- `--persist ~/floci-data` mounts that host directory into the container so state survives restarts.
- `--detach` returns control to your terminal instead of streaming logs forever.

**Expected result**

```text
Starting floci (aws) ...
Container: floci
Endpoint : http://localhost:4566
Status   : ready
```

> Example output — wording varies by version.

**Verify**

```bash
floci status
```

and independently, without the Floci CLI at all:

```bash
curl -s http://localhost:4566/_localstack/health | head -c 300 ; echo
```

`curl` here is a raw HTTP request to the health endpoint. If you get JSON back, something really is
listening on port 4566. (Floci implements the same health path as LocalStack for compatibility; if
that path returns nothing on your version, `floci status` is the authoritative check.)

**Useful lifecycle commands (learn these now)**

```bash
floci status      # is it running and healthy?
floci logs        # stream server logs — your best debugging tool
floci services    # which AWS services are enabled
floci stop        # shut it down (state persists thanks to --persist)
floci restart     # stop + start
floci wait        # block until ready (useful inside scripts)
```

**Checkpoint 2**

```text
Floci
 ├── container : running
 ├── endpoint  : http://localhost:4566
 ├── storage   : ~/floci-data (persistent)
 └── status    : ready
```

---

### Step 6 — Install the AWS CLI (version 2)

**Purpose**

The AWS CLI is the program that turns your typed command into a signed HTTPS request to an AWS API.

**Concept: what the AWS CLI actually is**

The AWS CLI is **not** AWS. It is a client. It knows the shape of every AWS API, builds the request,
signs it with your credentials, sends it, and pretty-prints the JSON response. It will happily send
that request to any endpoint you tell it to — which is precisely how it can talk to Floci.

**Run from**

```text
anywhere
```

**Command**

=== "Linux (x86_64)"

    ```bash
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
    unzip -q awscliv2.zip
    sudo ./aws/install
    rm -rf aws awscliv2.zip
    ```

=== "Linux (ARM64)"

    ```bash
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o awscliv2.zip
    unzip -q awscliv2.zip
    sudo ./aws/install
    rm -rf aws awscliv2.zip
    ```

=== "macOS"

    ```bash
    curl -fsSL "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o AWSCLIV2.pkg
    sudo installer -pkg AWSCLIV2.pkg -target /
    rm AWSCLIV2.pkg
    ```

    Or, more simply: `brew install awscli`

**Verify**

```bash
aws --version
```

**Expected result**

```text
aws-cli/2.28.4 Python/3.13.4 Linux/6.8.0 exe/x86_64
```

> Example output — versions differ.

!!! danger "It must say `aws-cli/2.x`"
    If it says `aws-cli/1.x`, you have AWS CLI v1. This course requires **v2**, because v2 supports
    the `AWS_ENDPOINT_URL` environment variable and the `endpoint_url` profile setting that let us
    redirect the CLI to Floci cleanly. Uninstall v1 (`pip uninstall awscli`) and install v2.

**Explore the CLI's own help**

```bash
aws help
aws iam help
aws iam create-user help
```

Press `q` to quit the help pager. This built-in help is the authoritative reference — you will use it
constantly. It shows every option, its type, and examples.

---

### Step 7 — Understand AWS credentials, regions and profiles

**Purpose**

Before configuring anything, understand the four values every AWS CLI command needs.

**The four values**

| Value | What it is | Our value (Floci) |
| --- | --- | --- |
| **Access Key ID** | Public half of a credential pair. Like a username | `test` |
| **Secret Access Key** | Private half. Used to sign requests. Like a password | `test` |
| **Region** | Which geographic AWS "copy" you are talking to | `us-east-1` |
| **Endpoint URL** | Which server to send the request to | `http://localhost:4566` |

**Concept: regions**

Real AWS runs in isolated **regions** (`us-east-1` = N. Virginia, `ap-south-1` = Mumbai,
`ap-southeast-1` = Singapore). Resources are region-scoped: a VPC created in Singapore does not
exist in Mumbai. Each region contains multiple **Availability Zones** (`us-east-1a`, `us-east-1b`) —
physically separate data centres used for redundancy. You will use AZs properly in Lab 2.

!!! note "IAM is one of the few global services"
    IAM users, groups, roles and policies are **global** — not tied to a region. You still must supply
    a region to the CLI (the request has to go somewhere), but IAM resources appear identically in
    every region. Real AWS routes all IAM calls to `us-east-1` internally. EC2, VPC and S3 buckets, by
    contrast, are regional.

**Concept: profiles**

A **profile** is a named set of these values stored in two files in your home directory:

```text
~/.aws/credentials     ← secrets  (access key id + secret)
~/.aws/config          ← settings (region, output format, endpoint_url)
```

Profiles let you keep `floci` (safe, local) and, someday, `university-prod` (real, dangerous)
separate, and choose between them per command with `--profile`.

**Concept: the credential resolution order**

The AWS CLI looks for credentials in this order and stops at the first hit:

```text
1. Command-line options       (--profile, --region)
2. Environment variables      (AWS_ACCESS_KEY_ID, AWS_ENDPOINT_URL, ...)
3. ~/.aws/credentials         (the named profile's secrets)
4. ~/.aws/config              (the named profile's settings)
5. IAM role attached to the machine (EC2 instance profile — Lab 3)
```

!!! warning "Do not mix profiles and environment variables"
    Floci offers `eval $(floci env)`, which exports `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, etc. into
    your shell. That is convenient, but if you *also* use `--profile`, it becomes very hard to reason
    about which credentials were actually used.

    **This course uses named profiles.** If you ever ran `eval $(floci env)`, clear them:

    ```bash
    unset AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
          AWS_DEFAULT_REGION AWS_REGION AWS_PROFILE
    ```

---

### Step 8 — Create the `floci` AWS CLI profile

**Purpose**

Store the four values once, so you never type them again.

**Run from**

```text
anywhere
```

**Command**

```bash
aws configure set aws_access_key_id     test               --profile floci
aws configure set aws_secret_access_key test               --profile floci
aws configure set region                us-east-1          --profile floci
aws configure set output                json               --profile floci
aws configure set endpoint_url          http://localhost:4566 --profile floci
```

**What the command does**

- `aws configure set <key> <value> --profile <name>` writes one setting into the profile files,
  creating them if needed. Credentials go to `~/.aws/credentials`, everything else to `~/.aws/config`.
- `endpoint_url` is the line that redirects **all** services in this profile to Floci. Without it the
  CLI would contact real AWS.
- `test`/`test` are dummy credentials. Floci accepts any non-empty values by default.

!!! danger "Why `test`/`test` is safe here and never elsewhere"
    These are meaningless strings accepted by a local emulator. **Never** put real AWS credentials
    into a command like this in a shared machine or a script — your shell history file
    (`~/.bash_history`) records everything you type.

**Verify**

```bash
cat ~/.aws/config
cat ~/.aws/credentials
```

**Expected result**

```ini
# ~/.aws/config
[profile floci]
region = us-east-1
output = json
endpoint_url = http://localhost:4566
```

```ini
# ~/.aws/credentials
[floci]
aws_access_key_id = test
aws_secret_access_key = test
```

> Example output. Note the asymmetry: the config file uses `[profile floci]`, the credentials file
> uses `[floci]`. That is genuine AWS CLI behaviour and a classic source of confusion.

**Make `floci` the default profile for this course**

```bash
echo 'export AWS_PROFILE=floci' >> ~/.bashrc
export AWS_PROFILE=floci
```

Now you can omit `--profile floci` from every command. This document still shows `--profile floci`
explicitly in the first few commands so you can see where it belongs, then relies on `AWS_PROFILE`.

✏️ **Your turn**

Run `aws configure list --profile floci`. Identify which column tells you *where* each value came
from, and explain why the `Type` for the access key says `shared-credentials-file`.

---

### Step 9 — Your first AWS CLI command

**Purpose**

Ask the emulator "who am I?" — the single most useful diagnostic command in AWS.

**Run from**

```text
anywhere
```

**Command**

```bash
aws sts get-caller-identity --profile floci
```

**What the command does**

Read the command as a sentence with four parts:

```text
aws           the CLI program
 └── sts                  the SERVICE (Security Token Service)
      └── get-caller-identity   the OPERATION (an API call)
           └── --profile floci  an OPTION (which credentials/endpoint to use)
```

- **STS** is the AWS service that issues and inspects temporary credentials.
- `get-caller-identity` returns the identity behind the credentials you just used. It requires **no
  permissions at all** — which is why it always works and is always the first thing to run when
  something is broken.

**Expected result**

```json
{
    "UserId": "AKIAIOSFODNN7EXAMPLE",
    "Account": "000000000000",
    "Arn": "arn:aws:iam::000000000000:root"
}
```

> Example output — your `UserId` may differ.

**Read the output**

- `Account` = `000000000000` — Floci's fixed dummy account number. Real AWS accounts are real 12-digit
  numbers. **Seeing all zeros is your proof you are not on real AWS.**
- `Arn` — an Amazon Resource Name, explained fully in Step 13.

**Checkpoint 3**

```text
AWS CLI  ──→  Floci  : working
Account            : 000000000000
```

If you got `Could not connect to the endpoint URL`, Floci is not running. Run `floci status`.

---

### Step 10 — Prove your commands never reach real AWS

**Purpose**

This is not paranoia — it is a professional habit. Confusing your test environment with production is
how people accidentally delete real infrastructure.

**Test 1 — the account number**

Already done in Step 9: `000000000000` is not a real account.

**Test 2 — inspect the actual URL the CLI used**

**Command**

```bash
aws sts get-caller-identity --profile floci --debug 2>&1 \
  | grep -i "endpoint\|Making request" \
  | head -5
```

**What the command does**

- `--debug` makes the CLI print its entire internal decision process.
- `2>&1` redirects **stderr** (where debug output goes) into **stdout** so the pipe can see it.
- `|` sends that text to `grep`, which prints only matching lines.
- `head -5` keeps the first five.

**Expected result**

```text
... Setting sts timeout as (60, 60)
... Making request for OperationModel(name=GetCallerIdentity) with params:
    {'url': 'http://localhost:4566/', ...
```

> Example output. The important part is `http://localhost:4566` — **not** `amazonaws.com`.

**Test 3 — the definitive test: stop Floci**

```bash
floci stop
aws sts get-caller-identity --profile floci
```

**Expected result**

```text
Could not connect to the endpoint URL: "http://localhost:4566/"
```

If your commands were secretly reaching real AWS, stopping a local container could not possibly break
them. Now bring it back:

```bash
floci start --persist ~/floci-data --detach
floci wait
aws sts get-caller-identity --profile floci
```

Note that the identity is unchanged — persistence works.

**Test 4 — exit codes**

```bash
aws sts get-caller-identity --profile floci > /dev/null 2>&1
echo "exit code = $?"
```

`$?` holds the exit status of the last command: `0` = success, non-zero = failure. Scripts use this
to decide whether to continue. You will use it in Step 12.

!!! note "Floci Limitation — identity is not really authenticated"
    Real AWS verifies your signature cryptographically and rejects wrong credentials. Floci accepts
    any non-empty credentials by default, and reports you as the account `root` user. So
    `get-caller-identity` in Floci confirms **connectivity**, not **authentication**.

**Checkpoint 4**

```text
Proof of isolation
 ├── Account is 000000000000        ✔
 ├── Request URL is localhost:4566  ✔
 ├── Stopping Floci breaks the CLI  ✔
 └── State survived a restart       ✔
```

---

### Step 11 — Create the course directory structure

**Purpose**

Create the folder tree from Section 7 once, so every later lab has a home.

**Run from**

```text
your home directory
```

**Command**

```bash
cd ~
mkdir -p aws-floci-course/{labs/lab-01-iam,policies,configs,templates,outputs,screenshots,notes}
mkdir -p aws-floci-course/scripts/{setup,utilities,cleanup}
cd aws-floci-course
```

**What the command does**

- `cd ~` moves to your home directory (`~` is shorthand for it).
- `mkdir -p` creates directories including parents.
- `{a,b,c}` is **brace expansion**: the shell expands it into several arguments, so one `mkdir`
  creates seven folders. Note there must be **no spaces** inside the braces.

**Verify**

```bash
find . -type d | sort
```

**Expected result**

```text
.
./configs
./labs
./labs/lab-01-iam
./notes
./outputs
./policies
./screenshots
./scripts
./scripts/cleanup
./scripts/setup
./scripts/utilities
./templates
```

!!! tip "Install `tree` for a nicer view"
    `sudo apt install tree` (Linux) or `brew install tree` (macOS), then run `tree -d`.

---

### Step 12 — Create the initial project files

**Purpose**

Create the files that make this a real project: a README, a `.gitignore` that protects secrets,
shared configuration, and two helper scripts.

**Run from**

```text
aws-floci-course/
```

#### 12.1 The `.gitignore` — write this FIRST

Writing `.gitignore` before anything else means a secret can never be committed by accident.

```bash
cat > .gitignore << 'EOF'
# ---- NEVER COMMIT THESE ----
outputs/
*.pem
*.key
*-access-key.json
*credentials*
.env
*.env.local

# Keep the outputs/ folder in Git, but not its contents
!outputs/.gitkeep

# OS / editor noise
.DS_Store
Thumbs.db
*.swp
.vscode/
.idea/
EOF

touch outputs/.gitkeep
```

**What the command does**

- `cat > file << 'EOF' ... EOF` is a **heredoc**: everything between the markers is written to the file.
- Quoting `'EOF'` stops the shell from expanding `$variables` inside the block — essential when
  writing JSON and policy documents that contain `${aws:username}`.
- `touch` creates an empty file. Git cannot track empty directories, so `.gitkeep` is a convention to
  keep the folder in the repository while its real contents stay ignored.

#### 12.2 `configs/course.env` — values every lab needs

```bash
cat > configs/course.env << 'EOF'
# =====================================================================
# USMS Course — shared configuration
# Sourced by every lab:   source ~/aws-floci-course/configs/course.env
# Contains NO secrets. Safe to commit.
# =====================================================================

# --- Floci / AWS CLI ---
export AWS_PROFILE=floci
export FLOCI_ENDPOINT=http://localhost:4566
export FLOCI_DATA_DIR="$HOME/floci-data"

# --- AWS environment ---
export AWS_REGION_COURSE=us-east-1
export ACCOUNT_ID=000000000000

# --- Project naming convention: every resource starts with usms- ---
export PROJECT=usms
export COURSE_ROOT="$HOME/aws-floci-course"
EOF
```

!!! note "Why a naming convention matters"
    Every resource in this course is prefixed `usms-`. In a real shared AWS account this is how you
    find, filter, bill and safely delete *your* resources without touching anybody else's. You will
    use it in Lab 2 with `--filters`, and in cleanup scripts.

#### 12.3 `scripts/setup/floci-up.sh` — one command to start everything

```bash
cat > scripts/setup/floci-up.sh << 'EOF'
#!/usr/bin/env bash
# Start Floci with persistent storage and confirm the AWS CLI can reach it.
set -euo pipefail

source "$(dirname "$0")/../../configs/course.env"

mkdir -p "$FLOCI_DATA_DIR"

if floci status >/dev/null 2>&1; then
  echo "Floci is already running."
else
  echo "Starting Floci ..."
  floci start --persist "$FLOCI_DATA_DIR" --detach
  floci wait
fi

echo "Checking AWS CLI connectivity ..."
if aws sts get-caller-identity >/dev/null 2>&1; then
  echo "OK — AWS CLI can reach Floci at $FLOCI_ENDPOINT"
  aws sts get-caller-identity --output table
else
  echo "FAILED — AWS CLI cannot reach Floci. Run 'floci logs' to investigate." >&2
  exit 1
fi
EOF

chmod +x scripts/setup/floci-up.sh
```

**What the script does**

- `#!/usr/bin/env bash` — the **shebang**: tells the OS which interpreter to use.
- `set -e` exit immediately on any failing command; `-u` error on undefined variables;
  `-o pipefail` make a pipeline fail if any stage fails. Together they stop a broken script from
  quietly continuing — exactly the discipline this course demands of you manually.
- `$(dirname "$0")` — `$0` is the script's own path; `dirname` strips the filename, so the script
  finds `configs/course.env` no matter where you run it from.
- `>/dev/null 2>&1` throws away output; we only care about the exit code.
- `chmod +x` marks the file executable.

#### 12.4 `scripts/utilities/whoami.sh` — the diagnostic you will use all course

```bash
cat > scripts/utilities/whoami.sh << 'EOF'
#!/usr/bin/env bash
# Print exactly which identity and endpoint the AWS CLI is currently using.
set -euo pipefail

echo "AWS_PROFILE      = ${AWS_PROFILE:-<unset>}"
echo "AWS_ENDPOINT_URL = ${AWS_ENDPOINT_URL:-<unset, using profile>}"
echo "configured endpoint = $(aws configure get endpoint_url || echo '<none>')"
echo "configured region   = $(aws configure get region || echo '<none>')"
echo "---"
aws sts get-caller-identity --output table
EOF

chmod +x scripts/utilities/whoami.sh
```

`${VAR:-default}` means "the value of VAR, or `default` if VAR is unset" — it prevents `set -u` from
killing the script when a variable legitimately does not exist.

#### 12.5 `README.md`

````bash
cat > README.md << 'EOF'
# AWS CLI + Floci — USMS Course Project

Infrastructure for the **University Student Management System (USMS)**, built lab by lab
with the AWS CLI against [Floci](https://floci.io), a local AWS emulator.

## Quick start

```bash
source configs/course.env
./scripts/setup/floci-up.sh
./scripts/utilities/whoami.sh
```

## Labs

| Lab | Topic | Status |
|-----|-------|--------|
| 01  | IAM   | ✅ complete |
| 02  | VPC   | ⬜ not started |

## Conventions

- All resources are prefixed `usms-`
- Region: `us-east-1`  ·  Floci account: `000000000000`
- Secrets live in `outputs/` and are **never** committed
EOF
````

**Verify everything**

```bash
source configs/course.env
./scripts/setup/floci-up.sh
```

**Expected result**

```text
Floci is already running.
Checking AWS CLI connectivity ...
OK — AWS CLI can reach Floci at http://localhost:4566
-------------------------------------------------------------
|                     GetCallerIdentity                      |
+----------------+---------------------+---------------------+
|    Account     |         Arn         |       UserId        |
+----------------+---------------------+---------------------+
|  000000000000  | arn:aws:iam::000000000000:root | ...      |
+----------------+---------------------+---------------------+
```

> Example output. Note `--output table` in the script — the same data as JSON, formatted for humans.

**Checkpoint 5 — end of Part A**

```text
Environment
 ├── Docker            : running
 ├── Floci             : running, persistent, port 4566
 ├── AWS CLI v2        : installed
 ├── Profile "floci"   : configured with endpoint_url
 ├── Proof of isolation: confirmed
 └── ~/aws-floci-course: created with README, .gitignore,
                         course.env, floci-up.sh, whoami.sh
```

---

## PART B — Building the IAM Foundation (Steps 13–30)

---

### Step 13 — IAM concepts and the anatomy of an ARN

**Purpose**

Understand the vocabulary before typing commands. Five minutes here saves an hour of confusion later.

#### 13.1 The four IAM building blocks

```text
┌───────────┐   an identity for a PERSON or a long-lived program.
│   USER    │   Has permanent credentials (password and/or access keys).
└───────────┘

┌───────────┐   a container for USERS. Policies attached here apply to
│   GROUP   │   every member. Groups cannot be nested and are not identities
└───────────┘   (a group cannot be "assumed" and has no credentials).

┌───────────┐   an identity for a SERVICE, an application, or a temporarily
│   ROLE    │   elevated human. NO permanent credentials — it is ASSUMED,
└───────────┘   which mints temporary credentials that expire.

┌───────────┐   a JSON document that says ALLOW or DENY for
│  POLICY   │   (actions) on (resources) under (conditions).
└───────────┘
```

#### 13.2 Two kinds of policy — the distinction students most often miss

| | **Permissions policy** | **Trust policy** |
| --- | --- | --- |
| Answers | "What may this identity **do**?" | "**Who** may become this role?" |
| Attached to | users, groups, roles | roles only (exactly one) |
| Key element | `Action` + `Resource` | `Principal` + `sts:AssumeRole` |
| CLI flag | `--policy-document` on `create-policy` | `--assume-role-policy-document` on `create-role` |

Every role needs **both**. Forgetting the trust policy is why a role "exists but nobody can use it".

#### 13.3 Three ways a policy can be attached

| Type | Lives where | Reusable? | Use when |
| --- | --- | --- | --- |
| **AWS managed** | Created and maintained by AWS | Yes, by everyone | Common broad cases (`ReadOnlyAccess`) |
| **Customer managed** | Created by you, standalone object with its own ARN and versions | Yes, attach to many identities | **Default choice.** Your organisation's rules |
| **Inline** | Embedded inside one user/group/role; dies with it | No | A one-off permission that must never be reused |

#### 13.4 Anatomy of an ARN

An **ARN** (Amazon Resource Name) is the globally unique address of an AWS resource. You will read
hundreds of them.

```text
arn:aws:iam::000000000000:user/usms-dev-01
 │   │   │  │       │           │
 │   │   │  │       │           └── resource  (type/name)
 │   │   │  │       └────────────── account id (12 digits)
 │   │   │  └────────────────────── region  (EMPTY for IAM — it is global!)
 │   │   └───────────────────────── service (iam, s3, ec2, lambda ...)
 │   └───────────────────────────── partition (aws | aws-cn | aws-us-gov)
 └───────────────────────────────── literal prefix, always "arn"
```

More examples you will meet in this course:

```text
arn:aws:iam::000000000000:group/usms-developers
arn:aws:iam::000000000000:role/usms-ec2-app-role
arn:aws:iam::000000000000:policy/USMSDeveloperBase
arn:aws:iam::aws:policy/ReadOnlyAccess          ← AWS managed: account is literally "aws"
arn:aws:s3:::usms-student-data                  ← S3: no region, no account (bucket names are global)
arn:aws:s3:::usms-student-data/*                ← the OBJECTS inside the bucket — a different ARN!
arn:aws:ec2:us-east-1:000000000000:instance/i-0abc123
```

!!! danger "The classic S3 mistake"
    `arn:aws:s3:::my-bucket` refers to the **bucket** (used for `s3:ListBucket`).
    `arn:aws:s3:::my-bucket/*` refers to the **objects** (used for `s3:GetObject`, `s3:PutObject`).
    A policy that lists only the first will fail every `GetObject` call. You will write both in Step 20.

#### 13.5 Anatomy of a policy document

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowReadingStudentFiles",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::usms-student-data/*",
      "Condition": { "StringEquals": { "aws:RequestedRegion": "us-east-1" } }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `Version` | The **policy language** version. Always `"2012-10-17"`. It is *not* a date you choose — using anything else silently disables variables like `${aws:username}` |
| `Statement` | A list of rules. Evaluated together |
| `Sid` | Statement ID — an optional human label. Extremely useful when debugging |
| `Effect` | `Allow` or `Deny` |
| `Action` | The API operations, in `service:Operation` form. Wildcards allowed (`s3:Get*`) |
| `Resource` | Which ARNs the actions apply to. `"*"` means all |
| `Condition` | Optional extra tests (region, MFA, source IP, tags) |

#### 13.6 How AWS decides: policy evaluation logic

```text
                For every request
                       |
                       v
        Is there an explicit DENY anywhere?
              /                    \
           YES                      NO
            |                        |
        ✗ DENIED          Is there an explicit ALLOW?
                              /              \
                            NO               YES
                             |                 |
                    ✗ DENIED (default)     ✓ ALLOWED
```

Two rules to memorise:

1. **Default deny.** No policy = no access. Permissions are never implicit.
2. **Explicit deny always wins.** A `Deny` beats any number of `Allow`s. This is how organisations
   place absolute guardrails (e.g. "nobody may ever delete audit logs").

!!! note "Floci Limitation — policies are stored, not enforced (by default)"
    This is the most important Floci caveat in this lab.

    Real AWS evaluates every request against IAM policies and returns `AccessDenied` when they do not
    permit it. Floci, by default, **accepts any non-empty credentials and does not authorize requests
    against your IAM policies** unless stricter authentication is explicitly enabled.

    **What this means for you:** everything you write in this lab is stored, retrievable and
    syntactically validated — you are learning real IAM authoring. But you generally will **not** see
    an `AccessDenied` in Floci simply because a policy was too narrow. Step 29 shows the
    policy *simulator* as the closest available substitute, and Section 12 lists exactly which parts
    of this lab are "conceptual / real AWS" rather than "enforced by Floci".

    Write every policy as if it *were* enforced. In a real account it will be.

---

### Step 14 — Inspect the empty IAM account

**Purpose**

See the "before" state, and learn the three output formats.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

```bash
cd ~/aws-floci-course/labs/lab-01-iam
```

**Command**

```bash
aws iam list-users
```

**What the command does**

- `iam` — the IAM service.
- `list-users` — returns every IAM user in the account. Read-only and harmless.

**Expected result**

```json
{
    "Users": []
}
```

An empty list, not an error. Your account exists; it just has no users yet.

**Now the same data in three formats**

```bash
aws iam list-users --output json
aws iam list-users --output table
aws iam list-users --output text
```

| Format | Best for |
| --- | --- |
| `json` | Machines, `jq`, saving to `outputs/` — the default and the most complete |
| `table` | Humans reading the screen. Never parse it in a script |
| `text` | Shell scripts. Tab-separated, no quotes or braces — perfect for `$( )` capture |

✏️ **Your turn**

Run `aws iam list-roles --output table`. Floci may pre-create some service-linked roles.
Are the results the same in `text` format? Which one would you use inside a script, and why?

---

### Step 15 — Create the IAM groups

**Purpose**

Create the three permission containers before creating any user, so users can be placed correctly
from birth.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

**Command**

```bash
aws iam create-group --group-name usms-admins
aws iam create-group --group-name usms-developers
aws iam create-group --group-name usms-auditors
```

**What the command does**

`create-group` creates an empty IAM group. A group has **no permissions and no members** at birth —
it is purely a container. Note there is no `--region`: IAM is global.

**Expected result**

```json
{
    "Group": {
        "Path": "/",
        "GroupName": "usms-admins",
        "GroupId": "AGPA1EXAMPLEID000001",
        "Arn": "arn:aws:iam::000000000000:group/usms-admins",
        "CreateDate": "2026-08-10T09:14:02+00:00"
    }
}
```

> Example output — your `GroupId` and `CreateDate` will differ.

Notice `"Path": "/"`. Paths are an organisational feature (`/engineering/backend/`) that lets you
group identities hierarchically and match them with wildcards in policies. We keep `/` for simplicity.

**Verify**

```bash
aws iam list-groups --query 'Groups[*].[GroupName,Arn]' --output table
```

**Introducing `--query`**

`--query` filters the JSON response **on your machine**, using a language called **JMESPath**. Read
`Groups[*].[GroupName,Arn]` as:

```text
Groups          take the "Groups" key from the response
      [*]       for every element in that list
         .[...] build a small list containing just these two fields
```

**Expected result**

```text
---------------------------------------------------------------
|                          ListGroups                          |
+-------------------+-------------------------------------------+
|  usms-admins      |  arn:aws:iam::000000000000:group/usms-admins     |
|  usms-auditors    |  arn:aws:iam::000000000000:group/usms-auditors   |
|  usms-developers  |  arn:aws:iam::000000000000:group/usms-developers |
+-------------------+-------------------------------------------+
```

**Checkpoint 6**

```text
IAM Groups
 ├── usms-admins      (0 members, 0 policies)
 ├── usms-developers  (0 members, 0 policies)
 └── usms-auditors    (0 members, 0 policies)
```

---

### Step 16 — Create the IAM users and capture their ARNs

**Purpose**

Create three users, and learn the single most important AWS CLI habit: **never copy an ID by hand**.

**Concept: why capture output into variables**

Copying `arn:aws:iam::000000000000:user/usms-dev-01` by hand from the screen into the next command is
slow and error-prone. Instead, ask the CLI for exactly one value and store it in a **shell variable**.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

**Command**

```bash
ADMIN_ARN=$(aws iam create-user \
  --user-name usms-admin-01 \
  --tags Key=Project,Value=USMS Key=Role,Value=Administrator \
  --query 'User.Arn' \
  --output text)

DEV_ARN=$(aws iam create-user \
  --user-name usms-dev-01 \
  --tags Key=Project,Value=USMS Key=Role,Value=Developer \
  --query 'User.Arn' \
  --output text)

AUDIT_ARN=$(aws iam create-user \
  --user-name usms-audit-01 \
  --tags Key=Project,Value=USMS Key=Role,Value=Auditor \
  --query 'User.Arn' \
  --output text)

echo "$ADMIN_ARN"
echo "$DEV_ARN"
echo "$AUDIT_ARN"
```

**What the command does**

- `VAR=$(command)` is **command substitution**: run the command, capture its standard output, assign
  it to `VAR`. No spaces around `=` — `VAR = value` is a different (broken) command.
- `\` at the end of a line continues the command on the next line. There must be **nothing** after the
  backslash, not even a space.
- `--tags Key=...,Value=...` attaches key/value labels. Tags are how real organisations track cost,
  ownership and environment. Tag everything, always.
- `--query 'User.Arn'` walks into the response object and picks one field.
- `--output text` strips the JSON quotes so the variable holds a clean string. **`--query` + `--output text` is the standard idiom for capturing an ID.**

**Expected result**

```text
arn:aws:iam::000000000000:user/usms-admin-01
arn:aws:iam::000000000000:user/usms-dev-01
arn:aws:iam::000000000000:user/usms-audit-01
```

!!! warning "Shell variables die with the terminal"
    If you close this terminal, `$DEV_ARN` is gone. That is why Step 30 writes these values to
    `configs/lab-01.env` — a file that survives, and that Lab 2 will simply `source`.

**Verify**

```bash
aws iam list-users \
  --query 'Users[*].{User:UserName,Created:CreateDate,Arn:Arn}' \
  --output table
```

`{Name:Field}` in JMESPath builds an object with **renamed keys** — which become the table's column
headers. Compare this to Step 15's `[Field1,Field2]`, which produced an unlabelled list.

**Inspect a single user and its tags**

```bash
aws iam get-user --user-name usms-dev-01
aws iam list-user-tags --user-name usms-dev-01 --output table
```

✏️ **Your turn**

Create a fourth user `usms-intern-01`, tagged `Key=Role,Value=Intern`, capturing its ARN into a
variable named `INTERN_ARN`. Then display **only** the `UserId` of that user using `get-user` and
`--query`.

```text
Expected result:
An ARN ending in :user/usms-intern-01, and a UserId string starting with AIDA...
```

---

### Step 17 — Add users to groups

**Purpose**

Connect identity to permission container.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

**Command**

```bash
aws iam add-user-to-group --group-name usms-admins     --user-name usms-admin-01
aws iam add-user-to-group --group-name usms-developers --user-name usms-dev-01
aws iam add-user-to-group --group-name usms-auditors   --user-name usms-audit-01
```

**What the command does**

Creates the membership link. Note it produces **no output at all** on success — many AWS "action"
commands are silent. Silence is success; check `$?` if unsure.

**Verify — from both directions**

```bash
# Direction 1: which users are in this group?
aws iam get-group --group-name usms-developers \
  --query 'Users[*].UserName' --output text

# Direction 2: which groups is this user in?
aws iam list-groups-for-user --user-name usms-dev-01 \
  --query 'Groups[*].GroupName' --output text
```

**Expected result**

```text
usms-dev-01
usms-developers
```

Being able to answer the question from both directions is exactly what you need during an access
investigation.

✏️ **Your turn**

Put `usms-intern-01` (from Step 16) into `usms-auditors`, then verify with a **single** command that
the auditors group now has two members.

---

### Step 18 — Explore and attach an AWS managed policy

**Purpose**

Use a policy AWS wrote for you before writing your own.

**Concept**

**AWS managed policies** are maintained by AWS, shared across every account, and identified by ARNs
where the account field is the literal word `aws`:

```text
arn:aws:iam::aws:policy/ReadOnlyAccess
```

They are convenient but usually **too broad** for least privilege. `ReadOnlyAccess` is one of the rare
cases where a managed policy is genuinely the right answer — an auditor really should be able to read
everything and change nothing.

**Explore what is available**

```bash
aws iam list-policies --scope AWS --max-items 10 \
  --query 'Policies[*].[PolicyName,Arn]' --output table
```

- `--scope AWS` shows only AWS-managed policies (`--scope Local` shows yours).
- `--max-items 10` limits output. Real AWS has 1,000+ managed policies.

!!! note "Floci Limitation"
    Floci ships a subset of AWS managed policies. If `ReadOnlyAccess` is missing on your version, the
    attach in this step will fail with `NoSuchEntity`. That is expected — skip to the workaround below
    and continue; nothing later in this lab depends on it.

**Command**

```bash
aws iam attach-group-policy \
  --group-name usms-auditors \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess
```

**Workaround if `ReadOnlyAccess` does not exist in your Floci build**

Create your own equivalent — which is also better practice anyway:

```bash
cat > ~/aws-floci-course/policies/usms-readonly-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOnlyEverything",
      "Effect": "Allow",
      "Action": [
        "iam:Get*", "iam:List*",
        "ec2:Describe*",
        "s3:Get*", "s3:List*",
        "logs:Describe*", "logs:Get*",
        "cloudwatch:Describe*", "cloudwatch:Get*", "cloudwatch:List*"
      ],
      "Resource": "*"
    }
  ]
}
EOF

RO_ARN=$(aws iam create-policy \
  --policy-name USMSReadOnly \
  --policy-document file://$HOME/aws-floci-course/policies/usms-readonly-policy.json \
  --query 'Policy.Arn' --output text)

aws iam attach-group-policy --group-name usms-auditors --policy-arn "$RO_ARN"
```

**Verify**

```bash
aws iam list-attached-group-policies --group-name usms-auditors --output table
```

**Expected result**

```text
--------------------------------------------------------------
|                 ListAttachedGroupPolicies                   |
+-----------------+--------------------------------------------+
|   PolicyArn     |                PolicyName                  |
+-----------------+--------------------------------------------+
| arn:aws:iam::aws:policy/ReadOnlyAccess |  ReadOnlyAccess     |
+-----------------+--------------------------------------------+
```

---

### Step 19 — Write your first customer managed policy

**Purpose**

Write a real policy document from scratch, and learn `file://`.

**The requirement, in plain English**

> A USMS developer must be able to **look at** the infrastructure (IAM, EC2, VPC, S3, CloudWatch), and
> **build networking** — because Lab 2 is the VPC lab. They must **not** be able to create IAM users,
> delete anything permanent, or touch billing.

**Run from**

```text
aws-floci-course/policies/
```

```bash
cd ~/aws-floci-course/policies
```

**Command — create the file**

```bash
cat > usms-developer-base-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadInfrastructure",
      "Effect": "Allow",
      "Action": [
        "iam:Get*",
        "iam:List*",
        "ec2:Describe*",
        "s3:List*",
        "s3:GetBucketLocation",
        "cloudwatch:Describe*",
        "cloudwatch:Get*",
        "logs:Describe*",
        "logs:GetLogEvents",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BuildNetworkingForLab02",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpc",
        "ec2:CreateSubnet",
        "ec2:CreateRouteTable",
        "ec2:CreateRoute",
        "ec2:CreateInternetGateway",
        "ec2:AttachInternetGateway",
        "ec2:AssociateRouteTable",
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:CreateTags",
        "ec2:ModifyVpcAttribute"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": { "aws:RequestedRegion": "us-east-1" }
      }
    },
    {
      "Sid": "DenyDangerousIdentityChanges",
      "Effect": "Deny",
      "Action": [
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:CreateAccessKey",
        "iam:AttachUserPolicy",
        "iam:PutUserPolicy",
        "aws-portal:*",
        "organizations:*"
      ],
      "Resource": "*"
    }
  ]
}
EOF
```

**Read the policy**

- **Statement 1 `ReadInfrastructure`** — broad read access. Wildcards on the *action* (`ec2:Describe*`)
  are normal for read operations; wildcards on *write* actions are not.
- **Statement 2 `BuildNetworkingForLab02`** — write permissions, but only the specific EC2/VPC
  operations Lab 2 needs, and only in `us-east-1`. This is least privilege in practice: enumerate the
  actions instead of writing `ec2:*`.
- **Statement 3 `DenyDangerousIdentityChanges`** — an explicit `Deny`. Because explicit deny always
  wins, this holds even if somebody later attaches `AdministratorAccess` to this group by mistake. This
  is the **privilege-escalation guardrail**: without it, a developer with `iam:AttachUserPolicy` could
  simply grant themselves admin.

**Validate the JSON before sending it**

```bash
python3 -m json.tool usms-developer-base-policy.json > /dev/null && echo "Valid JSON"
```

Malformed JSON produces a confusing `MalformedPolicyDocument` error from AWS. Checking locally first
tells you the exact line number instead.

**Command — create the policy in IAM**

```bash
DEV_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSDeveloperBase \
  --description "Read infrastructure + build VPC networking for USMS. Denies identity escalation." \
  --policy-document file://usms-developer-base-policy.json \
  --query 'Policy.Arn' \
  --output text)

echo "$DEV_POLICY_ARN"
```

**What `file://` means**

`file://usms-developer-base-policy.json` tells the AWS CLI: *read the value of this parameter from
that file*. It is relative to your current directory.

- `file://name.json` — relative path
- `file:///home/you/name.json` — absolute path (three slashes: `file://` + `/home/...`)

Using a file rather than inline JSON means the policy is version-controlled, reviewable, and reusable
in Lab 4 — which is why `policies/` sits at the project root, not inside `labs/lab-01-iam/`.

**Expected result**

```text
arn:aws:iam::000000000000:policy/USMSDeveloperBase
```

**Attach it to both groups that need it**

```bash
aws iam attach-group-policy --group-name usms-developers --policy-arn "$DEV_POLICY_ARN"
aws iam attach-group-policy --group-name usms-admins     --policy-arn "$DEV_POLICY_ARN"
```

One policy object, two attachments. Change the policy once and both groups update — this is the whole
point of customer managed policies.

**Verify**

```bash
aws iam list-attached-group-policies --group-name usms-developers --output table
aws iam get-policy --policy-arn "$DEV_POLICY_ARN" \
  --query 'Policy.{Name:PolicyName,Attached:AttachmentCount,Default:DefaultVersionId}' \
  --output table
```

**Expected result**

```text
------------------------------------------------
|                  GetPolicy                   |
+------------+-----------+---------------------+
| Attached   |  Default  |        Name         |
+------------+-----------+---------------------+
|  2         |  v1       |  USMSDeveloperBase  |
+------------+-----------+---------------------+
```

`AttachmentCount: 2` confirms both attachments. `DefaultVersionId: v1` becomes interesting in Step 24.

**Checkpoint 7**

```text
IAM
 ├── usms-admins      ← USMSDeveloperBase
 ├── usms-developers  ← USMSDeveloperBase
 └── usms-auditors    ← ReadOnlyAccess (or USMSReadOnly)
```

---

### Step 20 — Write the S3 data policy (used for real in Lab 4)

**Purpose**

Write the policy that will govern student transcript storage, and get the bucket-vs-object ARN
distinction right.

**Run from**

```text
aws-floci-course/policies/
```

**Command**

```bash
cat > usms-student-data-rw-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheBucketItself",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::usms-student-data"
    },
    {
      "Sid": "ReadWriteObjectsInsideTheBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::usms-student-data/*"
    },
    {
      "Sid": "NeverDeleteTheBucket",
      "Effect": "Deny",
      "Action": [
        "s3:DeleteBucket"
      ],
      "Resource": "arn:aws:s3:::usms-student-data"
    }
  ]
}
EOF

S3_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSStudentDataReadWrite \
  --description "Read/write student transcripts in the USMS bucket. Bucket deletion denied." \
  --policy-document file://usms-student-data-rw-policy.json \
  --query 'Policy.Arn' --output text)

echo "$S3_POLICY_ARN"
```

**Why there are two Allow statements**

Because they act on **two different ARNs**:

```text
arn:aws:s3:::usms-student-data      → the bucket   → s3:ListBucket
arn:aws:s3:::usms-student-data/*    → the objects  → s3:GetObject / s3:PutObject
```

A single statement combining `s3:ListBucket` with `arn:...:usms-student-data/*` is a no-op — you
cannot "list" an object. This is the most frequently made S3 policy error in the industry.

The bucket itself does not exist yet; it arrives in Lab 4. **Policies may reference resources that do
not exist** — they are evaluated at request time, not at creation time.

**Verify**

```bash
aws iam list-policies --scope Local \
  --query 'Policies[*].{Name:PolicyName,Attached:AttachmentCount}' --output table
```

`--scope Local` = policies **you** created, as opposed to AWS managed ones.

---

### Step 21 — Use `--generate-cli-skeleton` to discover parameters

**Purpose**

Learn how to work out a command's parameters without leaving the terminal.

**Run from**

```text
aws-floci-course/templates/
```

```bash
cd ~/aws-floci-course/templates
```

**Command**

```bash
aws iam create-role --generate-cli-skeleton > create-role-skeleton.json
cat create-role-skeleton.json
```

**What the command does**

`--generate-cli-skeleton` makes the CLI print an empty JSON template of every parameter the operation
accepts, **without calling AWS at all**. It is documentation you can fill in.

**Expected result**

```json
{
    "Path": "",
    "RoleName": "",
    "AssumeRolePolicyDocument": "",
    "Description": "",
    "MaxSessionDuration": 0,
    "PermissionsBoundary": "",
    "Tags": [ { "Key": "", "Value": "" } ]
}
```

> Example output — fields vary by CLI version.

You could fill this in and submit it with `--cli-input-json file://filled.json` instead of typing
flags. That approach shines in CI/CD pipelines where the JSON is generated by a program.

✏️ **Your turn**

Generate a skeleton for `aws iam create-policy` and for `aws ec2 create-vpc` (you will need the
latter in Lab 2). Save both in `templates/`. Which parameter of `create-vpc` looks like the most
important one?

---

### Step 22 — Add an inline policy (self-service credentials)

**Purpose**

Learn inline policies and IAM **policy variables** by solving a real problem: users should be able to
rotate their own access keys without an administrator.

**Concept**

An **inline policy** is embedded in a single identity. It has no ARN, cannot be attached elsewhere,
and is deleted automatically when the identity is deleted. Use it when the permission is meaningful
for exactly one identity and must never be reused by accident.

**Concept: policy variables**

`${aws:username}` is substituted at evaluation time with the name of the caller. One policy document
therefore says "your own user" for every different user — which is why it makes sense to attach this
one to a **group**, though we attach it to a user here to demonstrate `put-user-policy`.

**Run from**

```text
aws-floci-course/policies/
```

**Command**

```bash
cd ~/aws-floci-course/policies

cat > usms-self-manage-credentials.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageOwnAccessKeys",
      "Effect": "Allow",
      "Action": [
        "iam:CreateAccessKey",
        "iam:DeleteAccessKey",
        "iam:ListAccessKeys",
        "iam:UpdateAccessKey",
        "iam:GetAccessKeyLastUsed"
      ],
      "Resource": "arn:aws:iam::000000000000:user/${aws:username}"
    },
    {
      "Sid": "ManageOwnPasswordAndMFA",
      "Effect": "Allow",
      "Action": [
        "iam:ChangePassword",
        "iam:GetUser",
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:ListMFADevices",
        "iam:ResyncMFADevice"
      ],
      "Resource": [
        "arn:aws:iam::000000000000:user/${aws:username}",
        "arn:aws:iam::000000000000:mfa/${aws:username}"
      ]
    }
  ]
}
EOF

aws iam put-user-policy \
  --user-name usms-dev-01 \
  --policy-name USMSSelfManageCredentials \
  --policy-document file://usms-self-manage-credentials.json
```

!!! tip "This is why the heredoc marker is quoted"
    `<< 'EOF'` (with quotes) stops your **shell** from trying to expand `${aws:username}` into an
    empty string. Without the quotes you would silently create a broken policy. Verify with
    `grep aws:username usms-self-manage-credentials.json` — the text must still be there.

**Note the command name**

- `attach-user-policy` → attaches an **existing managed** policy by ARN.
- `put-user-policy` → embeds an **inline** policy document. "Put" overwrites, so re-running is safe.

**Verify**

```bash
aws iam list-user-policies --user-name usms-dev-01
aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials
```

**Expected result**

```json
{
    "PolicyNames": [
        "USMSSelfManageCredentials"
    ]
}
```

Compare with `aws iam list-attached-user-policies --user-name usms-dev-01`, which returns an empty
list — **inline and attached policies are listed by different commands.** Forgetting the inline list
is how permissions get missed during a security review.

**Note on MFA**

`iam:EnableMFADevice` appears above. **MFA (Multi-Factor Authentication)** requires a second proof
(a phone app code) beyond the password. In real AWS every human user, especially the root user, must
have MFA. It is meaningless in Floci (there is no console login), so it is included here as a
**conceptual / real AWS** item and to make the policy realistic.

---

### Step 23 — Inspect what you have built

**Purpose**

Learn the "read" side of IAM — the commands you use during an access investigation.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

```bash
cd ~/aws-floci-course/labs/lab-01-iam
```

**A. Everything about one user**

```bash
IAM_USER=usms-dev-01
echo "=== groups ===";        aws iam list-groups-for-user      --user-name $IAM_USER --query 'Groups[*].GroupName'      --output text
echo "=== attached ===";      aws iam list-attached-user-policies --user-name $IAM_USER --query 'AttachedPolicies[*].PolicyName' --output text
echo "=== inline ===";        aws iam list-user-policies        --user-name $IAM_USER --query 'PolicyNames'             --output text
echo "=== access keys ===";   aws iam list-access-keys          --user-name $IAM_USER --query 'AccessKeyMetadata[*].AccessKeyId' --output text
```

To know a user's *effective* permissions you must check **four** places: group policies, attached user
policies, inline user policies, and (in real AWS) permission boundaries and SCPs. Checking only one is
the classic incomplete audit.

**B. Read the actual policy JSON back out**

```bash
POLICY_ARN=arn:aws:iam::000000000000:policy/USMSDeveloperBase
VER=$(aws iam get-policy --policy-arn $POLICY_ARN --query 'Policy.DefaultVersionId' --output text)

aws iam get-policy-version \
  --policy-arn $POLICY_ARN \
  --version-id $VER \
  --query 'PolicyVersion.Document'
```

Two calls are required: `get-policy` returns *metadata*, and only `get-policy-version` returns the
*document*. Notice we used the output of the first call as input to the second — command chaining.

**C. The whole account in one call**

```bash
aws iam get-account-authorization-details > ~/aws-floci-course/outputs/lab-01-iam-snapshot.json

wc -l ~/aws-floci-course/outputs/lab-01-iam-snapshot.json
```

This single API call dumps every user, group, role and policy with their documents. In real AWS it is
the basis of most IAM audit tooling. We store it in `outputs/` (which is git-ignored).

**D. Optional: pretty-query it with `jq`**

```bash
sudo apt install -y jq        # or: brew install jq
jq '.UserDetailList[] | {UserName, Groups: .GroupList}' \
   ~/aws-floci-course/outputs/lab-01-iam-snapshot.json
```

`jq` is a dedicated JSON processor. `--query` runs **server-response-side in the CLI**; `jq` runs on
files you already have. Both are worth knowing.

**Checkpoint 8**

```text
Identity layer complete
 ├── 3 groups, each with policies
 ├── 3 users, each in a group
 ├── 1 inline policy on usms-dev-01
 └── full account snapshot saved to outputs/
```

---

### Step 24 — Policy versions

**Purpose**

Change a policy safely. Customer managed policies keep up to **5 versions**, so you can roll back.

**The change**

Lab 2 will need `ec2:DeleteVpc` (to clean up mistakes) and `ec2:DescribeAvailabilityZones`. Rather
than editing in place, we create a new version.

**Run from**

```text
aws-floci-course/policies/
```

**Command**

```bash
cd ~/aws-floci-course/policies

# 1. Copy the current document to a v2 file and add the actions
python3 - << 'PY'
import json, pathlib
p = pathlib.Path("usms-developer-base-policy.json")
doc = json.loads(p.read_text())
for st in doc["Statement"]:
    if st.get("Sid") == "BuildNetworkingForLab02":
        st["Action"] += ["ec2:DeleteVpc", "ec2:DescribeAvailabilityZones"]
pathlib.Path("usms-developer-base-policy-v2.json").write_text(json.dumps(doc, indent=2))
print("wrote usms-developer-base-policy-v2.json")
PY

# 2. Create the new version and make it live
aws iam create-policy-version \
  --policy-arn arn:aws:iam::000000000000:policy/USMSDeveloperBase \
  --policy-document file://usms-developer-base-policy-v2.json \
  --set-as-default
```

**What the command does**

- The small Python block edits the JSON programmatically rather than by hand — safer and repeatable.
- `create-policy-version` uploads a new document. `--set-as-default` makes it the version that is
  actually evaluated. Without that flag the new version exists but is inert.

**Verify**

```bash
aws iam list-policy-versions \
  --policy-arn arn:aws:iam::000000000000:policy/USMSDeveloperBase \
  --query 'Versions[*].{Version:VersionId,Default:IsDefaultVersion,Created:CreateDate}' \
  --output table
```

**Expected result**

```text
------------------------------------------------------
|                 ListPolicyVersions                 |
+-----------+-----------------------------+----------+
|  Default  |          Created            | Version  |
+-----------+-----------------------------+----------+
|  True     |  2026-08-10T09:41:11+00:00  |  v2      |
|  False    |  2026-08-10T09:22:03+00:00  |  v1      |
+-----------+-----------------------------+----------+
```

**Rolling back** is one command — no re-upload needed:

```bash
# (Do NOT run this now; shown for reference)
# aws iam set-default-policy-version --policy-arn <arn> --version-id v1
```

!!! warning "The 5-version limit"
    A policy may hold at most 5 versions. The 6th `create-policy-version` fails with
    `LimitExceeded` until you `delete-policy-version` an old one. Real teams hit this in automated
    pipelines constantly.

---

### Step 25 — Create a role for EC2, with a trust policy

**Purpose**

Create the identity that the USMS application server will use in Lab 3 — and understand why servers
must never hold access keys.

**Concept: why roles exist**

If you bake an access key into the application on your server, that key is a permanent secret sitting
on a machine that may be compromised, imaged, or backed up. A **role** solves this: the server is
*assigned* the role, and AWS delivers **temporary credentials that rotate automatically**. Nothing
secret is ever stored on the machine.

```text
        WITHOUT a role                     WITH a role
   ┌──────────────────┐             ┌──────────────────┐
   │  EC2 instance    │             │  EC2 instance    │
   │  access key on   │  ✗ risky    │  no secrets      │  ✓ safe
   │  disk forever    │             │  temp creds via  │
   └──────────────────┘             │  instance meta   │
                                    └──────────────────┘
```

**Concept: the trust policy**

A role's trust policy names the **Principal** allowed to assume it. For an EC2 role the principal is
the EC2 service itself:

```json
"Principal": { "Service": "ec2.amazonaws.com" }
```

**Run from**

```text
aws-floci-course/policies/
```

**Command**

```bash
cd ~/aws-floci-course/policies

cat > trust-ec2.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEC2ToAssumeThisRole",
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

EC2_ROLE_ARN=$(aws iam create-role \
  --role-name usms-ec2-app-role \
  --description "Role for the USMS application server (Lab 03). Grants S3 access to student data." \
  --assume-role-policy-document file://trust-ec2.json \
  --tags Key=Project,Value=USMS \
  --query 'Role.Arn' --output text)

echo "$EC2_ROLE_ARN"
```

**What the command does**

- `--assume-role-policy-document` is the **trust policy** — the "who may become me" document. This
  flag name is genuinely confusing; remember it is the *trust* policy, not the permissions policy.
- The role starts with **zero permissions**. Trust and permissions are completely separate.

**Now give the role its permissions**

```bash
aws iam attach-role-policy \
  --role-name usms-ec2-app-role \
  --policy-arn arn:aws:iam::000000000000:policy/USMSStudentDataReadWrite
```

**Verify**

```bash
aws iam get-role --role-name usms-ec2-app-role \
  --query 'Role.{Name:RoleName,Arn:Arn,Trust:AssumeRolePolicyDocument.Statement[0].Principal}' \
  --output json

aws iam list-attached-role-policies --role-name usms-ec2-app-role --output table
```

**Expected result**

```json
{
    "Name": "usms-ec2-app-role",
    "Arn": "arn:aws:iam::000000000000:role/usms-ec2-app-role",
    "Trust": { "Service": "ec2.amazonaws.com" }
}
```

**Create the instance profile**

An EC2 instance cannot be given a role directly. It is given an **instance profile**, which is a thin
wrapper containing exactly one role. In the AWS console this happens invisibly; with the CLI you must
do it yourself — and forgetting it is a very common Lab-3 failure.

```bash
aws iam create-instance-profile --instance-profile-name usms-ec2-app-profile

aws iam add-role-to-instance-profile \
  --instance-profile-name usms-ec2-app-profile \
  --role-name usms-ec2-app-role
```

**Verify**

```bash
aws iam get-instance-profile --instance-profile-name usms-ec2-app-profile \
  --query 'InstanceProfile.{Profile:InstanceProfileName,Roles:Roles[*].RoleName}' \
  --output json
```

**Expected result**

```json
{
    "Profile": "usms-ec2-app-profile",
    "Roles": [ "usms-ec2-app-role" ]
}
```

**Checkpoint 9**

```text
usms-ec2-app-role
 ├── trust      : ec2.amazonaws.com
 ├── permissions: USMSStudentDataReadWrite
 └── wrapped in : usms-ec2-app-profile   ← Lab 03 attaches this to the instance
```

---

### Step 26 — Create the Lambda execution role

**Purpose**

Create the role Lab 5's notification function will run as. Same pattern, different principal — which
is exactly the point.

**Run from**

```text
aws-floci-course/policies/
```

**Command**

```bash
cat > trust-lambda.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowLambdaToAssumeThisRole",
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

cat > usms-lambda-basic-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteOwnLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:000000000000:*"
    },
    {
      "Sid": "ReadStudentDataForNotifications",
      "Effect": "Allow",
      "Action": [ "s3:GetObject" ],
      "Resource": "arn:aws:s3:::usms-student-data/*"
    }
  ]
}
EOF

LAMBDA_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSLambdaBasic \
  --policy-document file://usms-lambda-basic-policy.json \
  --query 'Policy.Arn' --output text)

LAMBDA_ROLE_ARN=$(aws iam create-role \
  --role-name usms-lambda-exec-role \
  --description "Execution role for USMS notification functions (Lab 05)." \
  --assume-role-policy-document file://trust-lambda.json \
  --tags Key=Project,Value=USMS \
  --query 'Role.Arn' --output text)

aws iam attach-role-policy \
  --role-name usms-lambda-exec-role \
  --policy-arn "$LAMBDA_POLICY_ARN"

echo "$LAMBDA_ROLE_ARN"
```

**Why every Lambda function needs log permissions**

A Lambda function writes its own logs to CloudWatch Logs. If the execution role lacks
`logs:CreateLogStream` / `logs:PutLogEvents`, the function still runs but **produces no logs at all** —
and you are debugging blind. This is one of the most common real-world Lambda misconfigurations.

**Verify**

```bash
aws iam list-roles \
  --query 'Roles[?starts_with(RoleName, `usms-`)].{Role:RoleName,Arn:Arn}' \
  --output table
```

**Introducing JMESPath filters**

`[?starts_with(RoleName, \`usms-\`)]` is a **filter expression**: keep only elements where the test is
true. The backticks are JMESPath's way of writing a literal string. This is how you find your own
resources in an account full of other people's — and it is why the `usms-` naming convention matters.

---

### Step 27 — A role for humans, and temporary credentials with STS

**Purpose**

Learn the pattern real organisations use for human access: log in with minimal permissions, then
*assume* a role to get elevated permissions temporarily.

**Concept**

```text
usms-dev-01                        usms-developer-role
(few permissions,       assume →   (elevated permissions,
 permanent keys)                    temporary creds, 1 hour)
```

Benefits: the elevated permissions are not permanently attached to anyone, every assumption is logged,
and the credentials expire on their own.

**Run from**

```text
aws-floci-course/policies/
```

#### 27.1 Create the role with an account-principal trust policy

```bash
cat > trust-account-developers.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowUSMSDevelopersToAssume",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::000000000000:user/usms-dev-01"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

DEVROLE_ARN=$(aws iam create-role \
  --role-name usms-developer-role \
  --description "Elevated build permissions, assumed temporarily by USMS developers." \
  --assume-role-policy-document file://trust-account-developers.json \
  --max-session-duration 3600 \
  --query 'Role.Arn' --output text)

aws iam attach-role-policy \
  --role-name usms-developer-role \
  --policy-arn arn:aws:iam::000000000000:policy/USMSDeveloperBase

echo "$DEVROLE_ARN"
```

- The `Principal` is now an **AWS identity ARN**, not a service. You may also use
  `"AWS": "arn:aws:iam::000000000000:root"`, which means "any identity in this account that *also* has
  `sts:AssumeRole` permission" — a two-sided handshake.
- `--max-session-duration 3600` = credentials live at most 1 hour (in seconds).

#### 27.2 Give the developers group permission to assume it

Trust alone is not enough — both sides must agree.

```bash
cat > usms-assume-app-roles-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AssumeUSMSRoles",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": [
        "arn:aws:iam::000000000000:role/usms-developer-role"
      ]
    }
  ]
}
EOF

ASSUME_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSAssumeAppRoles \
  --policy-document file://usms-assume-app-roles-policy.json \
  --query 'Policy.Arn' --output text)

aws iam attach-group-policy --group-name usms-developers --policy-arn "$ASSUME_POLICY_ARN"
aws iam attach-group-policy --group-name usms-admins     --policy-arn "$ASSUME_POLICY_ARN"
```

!!! note "The two-sided handshake — memorise this"
    ```text
    Role's TRUST policy         says  "usms-dev-01 may assume me"
    User's PERMISSIONS policy   says  "I may call sts:AssumeRole on that role"
                                       ↓
                            BOTH required. Either one missing → AccessDenied.
    ```
    In real AWS, "I set up the role but assume-role is denied" is nearly always the missing second half.

#### 27.3 Assume the role

```bash
aws sts assume-role \
  --role-arn "$DEVROLE_ARN" \
  --role-session-name usms-dev-01-lab01 \
  --duration-seconds 3600 \
  > ~/aws-floci-course/outputs/assumed-role.json

cat ~/aws-floci-course/outputs/assumed-role.json
```

**Expected result**

```json
{
    "Credentials": {
        "AccessKeyId": "ASIAIOSFODNN7EXAMPLE",
        "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/EXAMPLEKEY",
        "SessionToken": "IQoJb3JpZ2luX2VjEO...EXAMPLE",
        "Expiration": "2026-08-10T10:52:31+00:00"
    },
    "AssumedRoleUser": {
        "AssumedRoleId": "AROAEXAMPLEID:usms-dev-01-lab01",
        "Arn": "arn:aws:sts::000000000000:assumed-role/usms-developer-role/usms-dev-01-lab01"
    }
}
```

> Example output — **never** treat these values as real; they are examples.

Three things to notice:

1. There are **three** values, not two — temporary credentials always include a `SessionToken`.
2. The access key starts with `ASIA`, not `AKIA`. `ASIA` = temporary, `AKIA` = permanent. You can tell
   at a glance what kind of credential you are looking at.
3. `Expiration` is one hour away. After that they simply stop working.
4. The resulting ARN is an `sts::...:assumed-role/...` ARN carrying your session name — which is what
   makes audit logs traceable back to a person.

#### 27.4 Use the temporary credentials

```bash
export AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId'     ~/aws-floci-course/outputs/assumed-role.json)
export AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' ~/aws-floci-course/outputs/assumed-role.json)
export AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken'    ~/aws-floci-course/outputs/assumed-role.json)

aws sts get-caller-identity --endpoint-url http://localhost:4566 --region us-east-1
```

We pass `--endpoint-url` explicitly here because environment credentials bypass the profile, and with
it the profile's `endpoint_url`.

**Return to your normal identity — do this before continuing**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./../../scripts/utilities/whoami.sh 2>/dev/null || ~/aws-floci-course/scripts/utilities/whoami.sh
```

!!! note "Floci Limitation — assume-role always succeeds"
    Because Floci does not authorize requests against IAM policies by default, `sts:AssumeRole` will
    succeed even if you *remove* the trust policy or the user's permission. The credentials returned
    are also not enforced afterwards. Treat this step as learning the **mechanics and the ARNs** —
    the enforcement half is real-AWS behaviour you must reason about, not observe here.

**Checkpoint 10**

```text
Roles
 ├── usms-ec2-app-role     (trust: ec2.amazonaws.com)      + instance profile
 ├── usms-lambda-exec-role (trust: lambda.amazonaws.com)
 └── usms-developer-role   (trust: usms-dev-01)  ← assumed, temp creds obtained
```

---

### Step 28 — Access keys, handled safely

**Purpose**

Create programmatic credentials for `usms-dev-01` and store them without ever risking a commit.

**Concept**

| Credential type | Used for | Looks like |
| --- | --- | --- |
| Console password | Web console login by a human | a password |
| **Access key pair** | CLI / SDK / scripts | `AKIA...` + a 40-char secret |
| Temporary (STS) | Assumed roles, EC2 roles | `ASIA...` + secret + session token |

**The secret is shown exactly once.** If you lose it, you cannot retrieve it — you delete the key and
create a new one.

!!! danger "Before you run this"
    The next command prints a secret access key to your terminal. In a real account:

    - never paste it into chat, email, a ticket, or an AI assistant,
    - never commit it,
    - never put it in a Docker image or a `.sh` file,
    - prefer roles over access keys wherever a role is possible.

    The values here are Floci dummies, but **build the habit now**.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

aws iam create-access-key --user-name usms-dev-01 \
  > outputs/usms-dev-01-access-key.json

chmod 600 outputs/usms-dev-01-access-key.json
```

**What the command does**

- Output is redirected straight to a file in `outputs/`, which `.gitignore` already excludes — so the
  secret never appears on screen, in your scrollback, or in a screenshot you might submit.
- `chmod 600` makes the file readable and writable **only by you** (no group, no others).

**Verify — without exposing the secret**

```bash
aws iam list-access-keys --user-name usms-dev-01 \
  --query 'AccessKeyMetadata[*].{Key:AccessKeyId,Status:Status,Created:CreateDate}' \
  --output table
```

**Expected result**

```text
--------------------------------------------------------------------
|                          ListAccessKeys                          |
+----------------------------+----------+---------------------------+
|            Key             |  Status  |          Created          |
+----------------------------+----------+---------------------------+
|  AKIAIOSFODNN7EXAMPLE      |  Active  | 2026-08-10T10:02:44+00:00 |
+----------------------------+----------+---------------------------+
```

Note that `list-access-keys` returns the key **ID** but never the secret. That is by design.

**Confirm Git really is protecting you**

```bash
git init -q 2>/dev/null
git status --porcelain | grep -c "outputs/" || echo "0 files from outputs/ are staged — correct"
git check-ignore -v outputs/usms-dev-01-access-key.json
```

`git check-ignore -v` prints which `.gitignore` rule caused the file to be ignored. Seeing the rule
named is far more convincing than seeing nothing happen.

**Create a second profile that uses this key**

```bash
KEY_ID=$(jq -r '.AccessKey.AccessKeyId'     outputs/usms-dev-01-access-key.json)
KEY_SECRET=$(jq -r '.AccessKey.SecretAccessKey' outputs/usms-dev-01-access-key.json)

aws configure set aws_access_key_id     "$KEY_ID"     --profile usms-dev
aws configure set aws_secret_access_key "$KEY_SECRET" --profile usms-dev
aws configure set region                us-east-1     --profile usms-dev
aws configure set output                json          --profile usms-dev
aws configure set endpoint_url          http://localhost:4566 --profile usms-dev

aws sts get-caller-identity --profile usms-dev
```

You now have two profiles: `floci` (account root) and `usms-dev` (the developer). Switching identity
is now a one-word change.

**Key rotation — the real-world procedure**

```text
1. Create a SECOND access key   (a user may hold two — this is why)
2. Deploy the new key everywhere
3. Set the OLD key to Inactive:
     aws iam update-access-key --user-name X --access-key-id AKIA... --status Inactive
4. Wait. Watch for breakage. Reactivate instantly if something failed.
5. Only then DELETE the old key.
```

The two-key limit exists precisely to make zero-downtime rotation possible.

---

### Step 29 — Test permissions with the policy simulator

**Purpose**

Answer "is this user actually allowed to do X?" without performing X.

**Command**

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::000000000000:user/usms-dev-01 \
  --action-names "ec2:CreateVpc" "iam:CreateUser" "s3:GetObject" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}' \
  --output table
```

**What the command does**

`simulate-principal-policy` runs AWS's real policy evaluation engine against a hypothetical request.
It changes nothing. It is the correct tool for testing a policy before deploying it.

**Expected result (real AWS)**

```text
------------------------------------------
|      SimulatePrincipalPolicy           |
+------------------+---------------------+
|      Action      |      Decision       |
+------------------+---------------------+
|  ec2:CreateVpc   |  allowed            |
|  iam:CreateUser  |  explicitDeny       |
|  s3:GetObject    |  implicitDeny       |
+------------------+---------------------+
```

Three decisions, three meanings:

- `allowed` — a statement permits it (our `BuildNetworkingForLab02` statement).
- `explicitDeny` — a `Deny` statement blocks it (our `DenyDangerousIdentityChanges` guardrail).
- `implicitDeny` — **nothing** mentions it, so the default deny applies.

Being able to distinguish explicit from implicit deny is the core skill of debugging `AccessDenied`:
implicit means "add a permission", explicit means "find and fix the Deny — adding Allows will not help".

!!! note "Floci Limitation"
    `simulate-principal-policy` may return `UnsupportedOperation`, `InvalidAction`, or a simplified
    result on your Floci build. If so, this step is **conceptual / real AWS**: read the table above and
    understand the three decision types. Nothing later in the lab depends on the simulator running.

✏️ **Your turn**

Predict — before running anything — the decision for `usms-audit-01` on `ec2:CreateVpc` and on
`ec2:DescribeVpcs`. Write your prediction in `notes/lab-01-notes.md`, then check it. If Floci does not
support the simulator, justify your prediction by quoting the relevant statement from the policy JSON.

---

### Step 30 — Save the lab state for future labs

**Purpose**

Write down every ARN Lab 2 and beyond will need, and snapshot the emulator.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
cd ~/aws-floci-course

cat > configs/lab-01.env << EOF
# =====================================================================
# Lab 01 — IAM outputs
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Contains ARNs only. NO SECRETS. Safe to commit.
# Usage:  source ~/aws-floci-course/configs/lab-01.env
# =====================================================================

export USMS_ACCOUNT_ID=000000000000

# --- Users ---
export USMS_ADMIN_USER=usms-admin-01
export USMS_DEV_USER=usms-dev-01
export USMS_AUDIT_USER=usms-audit-01

# --- Groups ---
export USMS_GROUP_ADMINS=usms-admins
export USMS_GROUP_DEVS=usms-developers
export USMS_GROUP_AUDITORS=usms-auditors

# --- Customer managed policies ---
export USMS_POLICY_DEV_BASE=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSDeveloperBase'].Arn | [0]" --output text)
export USMS_POLICY_S3_RW=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSStudentDataReadWrite'].Arn | [0]" --output text)
export USMS_POLICY_ASSUME=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSAssumeAppRoles'].Arn | [0]" --output text)

# --- Roles ---
export USMS_ROLE_EC2=$(aws iam get-role --role-name usms-ec2-app-role --query 'Role.Arn' --output text)
export USMS_ROLE_LAMBDA=$(aws iam get-role --role-name usms-lambda-exec-role --query 'Role.Arn' --output text)
export USMS_ROLE_DEVELOPER=$(aws iam get-role --role-name usms-developer-role --query 'Role.Arn' --output text)

# --- Instance profile (Lab 03 needs this) ---
export USMS_INSTANCE_PROFILE=usms-ec2-app-profile

# --- Planned resources (created in later labs) ---
export USMS_BUCKET_NAME=usms-student-data
EOF

cat configs/lab-01.env
```

**What the command does**

Note this heredoc uses `<< EOF` **without quotes** — here we *want* the shell to run the
`$(aws ...)` substitutions and bake the real ARNs into the file. Compare with the policy files in
Steps 19–27, which used `<< 'EOF'` precisely to prevent expansion. Choosing the right one is a real
skill.

`Policies[?PolicyName=='X'].Arn | [0]` is a JMESPath filter piped to `[0]` to take the first (only)
match, so the variable holds a single string rather than a list.

**Verify — the whole thing works from a fresh shell**

```bash
source configs/course.env
source configs/lab-01.env
echo "EC2 role : $USMS_ROLE_EC2"
echo "Dev policy: $USMS_POLICY_DEV_BASE"
```

**Take a Floci snapshot**

```bash
floci snapshot save lab-01-iam-complete
floci snapshot list
```

A snapshot captures the emulator's entire state. If you break something in Lab 3, you can return to
this exact point with `floci snapshot load lab-01-iam-complete` instead of redoing Lab 1.

**Write your lab notes**

```bash
cat > labs/lab-01-iam/README.md << 'EOF'
# Lab 01 — IAM — completed

## What exists after this lab
- Groups: usms-admins, usms-developers, usms-auditors
- Users: usms-admin-01, usms-dev-01, usms-audit-01
- Customer managed policies: USMSDeveloperBase (v2), USMSStudentDataReadWrite,
  USMSAssumeAppRoles, USMSLambdaBasic
- Inline policy: USMSSelfManageCredentials on usms-dev-01
- Roles: usms-ec2-app-role, usms-lambda-exec-role, usms-developer-role
- Instance profile: usms-ec2-app-profile

## Reproduce
    source ~/aws-floci-course/configs/course.env
    source ~/aws-floci-course/configs/lab-01.env
    ./scripts/setup/floci-up.sh

## Problems I hit and how I fixed them
(fill this in — it is graded)
EOF
```

**Commit your work**

```bash
git add .
git status --short
git commit -m "Lab 01: IAM foundation for USMS (users, groups, policies, roles)"
```

Before committing, read the `git status --short` output and confirm **no file from `outputs/` is
listed**.

**Checkpoint 11 — end of Part B**

```text
IAM foundation complete and recorded
 ├── configs/lab-01.env written with all ARNs
 ├── Floci snapshot "lab-01-iam-complete" saved
 ├── Lab notes written
 └── Work committed to Git, with no secrets
```

---

## 9. Verification

Run this end-to-end verification script. It checks every artefact this lab was supposed to produce.

**Run from**

```text
aws-floci-course/
```

```bash
cat > scripts/utilities/verify-lab-01.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 01 artefact exists. Exit 1 if anything is missing.
set -uo pipefail

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then
    printf "  ✔ %s\n" "$1"; PASS=$((PASS+1))
  else
    printf "  ✗ %s\n" "$1"; FAIL=$((FAIL+1))
  fi
}

echo "== Environment =="
check "Floci running"            "floci status"
check "AWS CLI reaches Floci"    "aws sts get-caller-identity"

echo "== Groups =="
for g in usms-admins usms-developers usms-auditors; do
  check "group $g" "aws iam get-group --group-name $g"
done

echo "== Users =="
for u in usms-admin-01 usms-dev-01 usms-audit-01; do
  check "user $u" "aws iam get-user --user-name $u"
done

echo "== Memberships =="
check "usms-dev-01 in usms-developers" \
  "aws iam get-group --group-name usms-developers --query 'Users[?UserName==\`usms-dev-01\`]' --output text | grep -q usms-dev-01"

echo "== Policies =="
for p in USMSDeveloperBase USMSStudentDataReadWrite USMSAssumeAppRoles USMSLambdaBasic; do
  check "policy $p" \
    "aws iam list-policies --scope Local --query \"Policies[?PolicyName=='$p'].Arn|[0]\" --output text | grep -q arn:"
done
check "inline policy on usms-dev-01" \
  "aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials"

echo "== Roles =="
for r in usms-ec2-app-role usms-lambda-exec-role usms-developer-role; do
  check "role $r" "aws iam get-role --role-name $r"
done
check "instance profile has the role" \
  "aws iam get-instance-profile --instance-profile-name usms-ec2-app-profile --query 'InstanceProfile.Roles[0].RoleName' --output text | grep -q usms-ec2-app-role"

echo "== Files =="
check "configs/course.env"  "test -f $HOME/aws-floci-course/configs/course.env"
check "configs/lab-01.env"  "test -f $HOME/aws-floci-course/configs/lab-01.env"
check ".gitignore ignores outputs/" \
  "cd $HOME/aws-floci-course && git check-ignore -q outputs/usms-dev-01-access-key.json"

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-01.sh
./scripts/utilities/verify-lab-01.sh
```

**Expected result**

```text
== Environment ==
  ✔ Floci running
  ✔ AWS CLI reaches Floci
== Groups ==
  ✔ group usms-admins
  ...
PASS=20  FAIL=0
```

If anything fails, the label tells you exactly which step to redo.

---

## 10. Checkpoints

A consolidated list. Tick each one before moving to Lab 2.

| # | Checkpoint | Verify with |
| --- | --- | --- |
| 1 | Docker running | `docker info` |
| 2 | Floci running, persistent, port 4566 | `floci status` |
| 3 | AWS CLI reaches Floci, account `000000000000` | `aws sts get-caller-identity` |
| 4 | Proof of isolation confirmed | `--debug` shows `localhost:4566` |
| 5 | Project structure + README + .gitignore + scripts | `find . -type d` |
| 6 | 3 groups created | `aws iam list-groups` |
| 7 | Policies attached to groups | `aws iam list-attached-group-policies` |
| 8 | Users created, in groups, inline policy set | `verify-lab-01.sh` |
| 9 | EC2 role + instance profile | `aws iam get-instance-profile` |
| 10 | 3 roles, temp credentials obtained via STS | `outputs/assumed-role.json` |
| 11 | `configs/lab-01.env` written, snapshot saved, Git clean | `floci snapshot list` |

---

## 11. Troubleshooting

Each entry follows: **Problem → Cause → Diagnose → Fix → Verify**.

### 11.1 `floci: command not found`

- **Cause** — the binary is not in your `PATH`.
- **Diagnose** — `ls ~/.local/bin/floci` or `which floci`.
- **Fix** —
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  ```
- **Verify** — `floci version`.

### 11.2 `Cannot connect to the Docker daemon`

- **Cause** — Docker Desktop is not started, or your user is not in the `docker` group.
- **Diagnose** — `docker info` (fails), `groups | grep docker` (empty).
- **Fix** — start Docker Desktop; on Linux:
  ```bash
  sudo systemctl start docker
  sudo usermod -aG docker $USER && newgrp docker
  ```
- **Verify** — `docker run --rm hello-world`.

### 11.3 `Could not connect to the endpoint URL: "http://localhost:4566/"`

- **Cause** — Floci is not running, crashed, or is on a different port.
- **Diagnose** —
  ```bash
  floci status
  docker ps --filter name=floci
  curl -sv http://localhost:4566 2>&1 | head -5
  ```
- **Fix** — `./scripts/setup/floci-up.sh`, or `floci logs` to see why it died.
- **Verify** — `aws sts get-caller-identity`.

### 11.4 Commands hang, then fail with a timeout — and the URL says `amazonaws.com`

- **Cause** — `endpoint_url` is missing; the CLI is trying to reach **real AWS**.
- **Diagnose** —
  ```bash
  aws configure get endpoint_url --profile floci      # should print the localhost URL
  aws sts get-caller-identity --debug 2>&1 | grep -m1 "'url'"
  ```
- **Fix** —
  ```bash
  aws configure set endpoint_url http://localhost:4566 --profile floci
  ```
  Or per-command: `--endpoint-url http://localhost:4566`.
- **Verify** — the debug line now shows `localhost:4566`.

### 11.5 `Unable to locate credentials`

- **Cause** — no profile, wrong profile name, or `AWS_PROFILE` points at a profile that does not exist.
- **Diagnose** —
  ```bash
  echo "AWS_PROFILE=$AWS_PROFILE"
  aws configure list-profiles
  aws configure list --profile floci
  ```
- **Fix** — redo Step 8, or `export AWS_PROFILE=floci`.
- **Verify** — `aws sts get-caller-identity`.

### 11.6 `The config profile (floci) could not be found`

- **Cause** — the section header in `~/.aws/config` is `[floci]` instead of `[profile floci]`.
- **Diagnose** — `cat ~/.aws/config`.
- **Fix** — always use `aws configure set ... --profile floci` rather than editing by hand; it writes
  the correct headers. If editing manually: `~/.aws/config` needs `[profile NAME]`,
  `~/.aws/credentials` needs `[NAME]`.
- **Verify** — `aws configure list --profile floci`.

### 11.7 `MalformedPolicyDocument` / `Invalid JSON`

- **Cause** — a trailing comma, a missing bracket, or smart quotes pasted from a PDF or web page.
- **Diagnose** —
  ```bash
  python3 -m json.tool policies/usms-developer-base-policy.json
  ```
  It reports the exact line and column.
- **Fix** — correct the JSON. Common culprits:
  - trailing comma after the last array element,
  - `"` replaced by `“` `”` (curly quotes) after copy-paste,
  - `Version` written as anything other than `"2012-10-17"`.
- **Verify** — re-run the validator, then re-run `create-policy`.

### 11.8 `EntityAlreadyExists`

- **Cause** — you ran a `create-*` command twice.
- **Diagnose** — `aws iam get-user --user-name usms-dev-01` (it exists).
- **Fix** — this is usually harmless: the resource you wanted is already there. Continue. If you truly
  need to recreate it, delete first (see 11.13 for the dependency order).
- **Verify** — `aws iam list-users`.

### 11.9 `NoSuchEntity`

- **Cause** — a typo in a name or ARN, or the resource was never created, or you are looking in a
  different account.
- **Diagnose** —
  ```bash
  aws iam list-policies --scope Local --query 'Policies[*].PolicyName' --output text
  aws iam list-roles --query 'Roles[*].RoleName' --output text
  ```
- **Fix** — correct the name. Watch for: `usms-developers` (plural) vs `usms-developer-role`
  (singular), and account `000000000000` (twelve zeros — count them).
- **Verify** — re-run the failing command.

### 11.10 `${aws:username}` came out empty in the policy file

- **Cause** — you used `<< EOF` instead of `<< 'EOF'`, so **your shell** expanded it.
- **Diagnose** — `grep 'aws:username' policies/usms-self-manage-credentials.json`. No match = expanded.
- **Fix** — rewrite the file using `<< 'EOF'` (quoted), then re-run `put-user-policy` — "put"
  overwrites, so no deletion is needed.
- **Verify** — `aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials`
  and confirm the variable is present in the document.

### 11.11 `AccessDenied` on `sts:AssumeRole`

- **Cause** — only one half of the handshake is in place.
- **Diagnose** —
  ```bash
  # half 1: does the role trust the caller?
  aws iam get-role --role-name usms-developer-role \
    --query 'Role.AssumeRolePolicyDocument'
  # half 2: may the caller call AssumeRole?
  aws iam list-attached-group-policies --group-name usms-developers
  ```
- **Fix** — add the missing side (Step 27.1 or 27.2).
- **Verify** — `aws sts assume-role ...` returns credentials.
- **Note** — in Floci this error is unlikely to appear at all, because policies are not enforced by
  default. Learn the diagnosis anyway; you will need it on real AWS.

### 11.12 Shell errors: `command not found`, `unexpected token`, empty variable

| Symptom | Cause | Fix |
| --- | --- | --- |
| `VPC_ID: command not found` | You wrote `VAR = value` with spaces | `VAR=value` — no spaces around `=` |
| `unexpected end of file` | A `\` line continuation has a trailing space, or a heredoc `EOF` is indented | Remove the space; put `EOF` at column 1 |
| `$MY_VAR` is empty | You opened a new terminal, or the capturing command failed | `echo $MY_VAR` to confirm; re-run the capture, or `source configs/lab-01.env` |
| `file://policy.json` → `Unable to load paramfile` | You are in the wrong directory | `pwd`, then `cd` to `policies/`, or use an absolute `file:///home/...` path |

### 11.13 `DeleteConflict` when deleting an IAM entity

- **Cause** — IAM refuses to delete something that still has dependents.
- **Diagnose** — the error message names the dependency.
- **Fix** — remove dependents in this order:
  ```text
  user   → remove from groups → delete access keys → delete inline policies
           → detach managed policies → delete user
  group  → remove all users → detach policies → delete group
  role   → remove from instance profiles → detach policies
           → delete inline policies → delete role
  policy → detach from ALL identities → delete non-default versions → delete policy
  ```
- **Verify** — re-run the delete.

### 11.14 Floci lost all my resources after a restart

- **Cause** — Floci was started without `--persist`, so it used the default `memory` storage mode.
- **Diagnose** — `floci status`; check whether `~/floci-data` contains anything.
- **Fix** — restart correctly and, if you saved one, restore a snapshot:
  ```bash
  floci stop
  floci start --persist ~/floci-data --detach
  floci snapshot load lab-01-iam-complete
  ```
  If you have no snapshot, re-run Steps 15–30. This is why Step 30 exists.
- **Verify** — `./scripts/utilities/verify-lab-01.sh`.

---

## 12. Floci vs Real AWS

### 12.1 What is genuinely the same

| Aspect | Same as real AWS? |
| --- | --- |
| AWS CLI commands and flags | ✅ Identical |
| Request/response JSON shape | ✅ Identical |
| ARN format | ✅ Identical (account is `000000000000`) |
| Policy document syntax and validation | ✅ Identical |
| Users, groups, roles, instance profiles | ✅ Created and retrievable |
| Policy versioning (5-version limit) | ✅ Behaves the same |
| STS `assume-role` response shape | ✅ Identical, including `ASIA` prefix and session token |
| Skills you are learning | ✅ 100 % transferable |

### 12.2 What differs

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| **IAM authorization** | Every request evaluated; `AccessDenied` returned | Any non-empty credentials accepted; requests not authorized against your policies by default | **Floci Limitation** |
| Credential signature check | Cryptographically verified | Not verified by default | **Floci Limitation** |
| Account ID | Your real 12-digit account | Fixed `000000000000` | Cosmetic |
| Console / web UI | Full graphical console | None — CLI/API only | **Floci Limitation** |
| Root user & MFA | Real, must be protected with MFA | No console, MFA meaningless | Conceptual / Real AWS |
| AWS managed policies | 1,000+ maintained by AWS | A subset | **Floci Limitation** |
| `simulate-principal-policy` | Full evaluation engine | May be unsupported/simplified | **Floci Limitation** |
| Permission boundaries, SCPs, Access Analyzer | Available | Not meaningfully enforced | Conceptual / Real AWS |
| CloudTrail audit of IAM calls | Every call logged | Not equivalent | Conceptual / Real AWS |
| IAM propagation delay | Eventually consistent — changes can take seconds | Immediate | **Floci is nicer** — beware on real AWS |
| Cost | IAM free; mistakes elsewhere cost money | Free | **Floci is nicer** |

!!! danger "The one thing you must carry into real AWS"
    Because Floci does not deny you, **you will not feel the consequences of an over-permissive
    policy.** A policy of `{"Effect":"Allow","Action":"*","Resource":"*"}` behaves identically to a
    carefully scoped one here. On real AWS the first is a severe security finding.

    Judge your policies by reading them, not by whether the command succeeded.

### 12.3 Which parts of this lab were "conceptual / real AWS"?

```text
Implemented and observable in Floci:
  users, groups, memberships, tags
  customer managed policies + versions
  inline policies
  roles + trust policies
  instance profiles
  access keys (create / list / rotate mechanics)
  sts assume-role (mechanics and response shape)

Conceptual / real AWS only:
  actual enforcement of every policy written above
  AccessDenied vs explicitDeny vs implicitDeny in practice
  MFA
  permission boundaries, SCPs, IAM Access Analyzer
  CloudTrail auditing
  the "policies may exist before their resources" behaviour is real,
    but you will only see it enforced on real AWS
```

---

## 13. Independent Lab Exercises

Complete these **on your own**. No full solutions are given — that is the point. Record your commands
and output in `labs/lab-01-iam/exercises.md`.

---

### Exercise 1 — Basic: the QA identity

**Requirements**

Create a new IAM group `usms-qa` and a user `usms-qa-01` inside it. Tag the user with
`Key=Role,Value=QA` and `Key=Project,Value=USMS`. Attach the existing `USMSDeveloperBase` policy
to the group — do **not** create a new policy.

**Constraints**

- Capture the user's ARN into a shell variable using `--query` and `--output text`.
- Do not attach any policy directly to the user.

**Expected outcome**

```text
aws iam get-group --group-name usms-qa   →  shows usms-qa-01
aws iam list-attached-group-policies --group-name usms-qa  →  shows USMSDeveloperBase
aws iam list-attached-user-policies --user-name usms-qa-01 →  empty list
```

**Hints** — you need `create-group`, `create-user`, `add-user-to-group`, `attach-group-policy`.
Every one of them appeared in Steps 15–19.

---

### Exercise 2 — Intermediate: the read-only reporting policy

**Requirements**

The USMS reporting service must read student transcripts but must never modify or delete them.
Write a **new customer managed policy** called `USMSReportingReadOnly` that allows:

- listing the `usms-student-data` bucket,
- reading objects **only** under the prefix `transcripts/`,

and explicitly denies every `s3:Put*` and `s3:Delete*` action on that bucket.

**Constraints**

- The policy document must live in `policies/usms-reporting-readonly-policy.json` and be committed.
- Use at least one `Sid` per statement.
- Validate the JSON locally before calling `create-policy`.

**Expected outcome**

```text
aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSReportingReadOnly']"
  → returns one policy with an ARN
```

**Hints**

- Prefix restriction goes in the **Resource** ARN: `arn:aws:s3:::usms-student-data/transcripts/*`.
- Re-read Step 20 on the bucket-ARN vs object-ARN distinction. You will need both.
- Explicit `Deny` beats `Allow` — that is what makes this policy safe even if someone later attaches
  a broader one.

---

### Exercise 3 — Problem solving: the third-party analytics role

**The scenario, not the commands**

A partner university runs an analytics service that must read USMS reports for **at most 30 minutes at
a time**. They will not have an IAM user in your account; they will assume a role.

**Requirements**

Design and create a role `usms-analytics-partner-role` that:

1. can be assumed by the identity `arn:aws:iam::000000000000:user/usms-audit-01`,
2. cannot hold a session longer than 30 minutes,
3. can read objects under `arn:aws:s3:::usms-student-data/reports/*` and nothing else,
4. is tagged `Key=Project,Value=USMS` and `Key=External,Value=true`.

Then obtain temporary credentials for it and record the `Expiration` timestamp you receive.

**Constraints**

- Both halves of the trust handshake must be in place (Step 27 explains what that means).
- The trust policy and the permissions policy must be separate files in `policies/`.

**Expected outcome**

```text
aws iam get-role --role-name usms-analytics-partner-role
  → MaxSessionDuration is 1800
  → AssumeRolePolicyDocument names usms-audit-01

aws sts assume-role ... → Credentials.Expiration is ~30 minutes ahead
```

**Hints**

- 30 minutes expressed in seconds is the value for `--max-session-duration`.
- A **Condition** using `sts:ExternalId` is how real third-party access is secured — research it and
  explain in your notes whether you should add one here.

---

### Exercise 4 — Challenge: design a least-privilege policy from a job description

**The brief**

> "The USMS **backup operator** runs a nightly job. It must copy every object out of the student data
> bucket into a separate archive bucket `usms-archive`, verify what it copied, and write a completion
> log line to CloudWatch Logs. It must never be able to delete anything, never read IAM, and it must
> only ever run in `us-east-1`."

**Requirements**

1. Decide: user, group, or role? Justify your choice in one paragraph in `notes/lab-01-notes.md`.
2. Write the policy document(s) needed. Determine the exact action list yourself — do not use
   wildcards on write actions.
3. Create the identity and attach the policy.
4. Add a `Condition` that enforces the region restriction.
5. List, in your notes, three specific ways your policy could still be abused, and how you would
   close each gap.

**Constraints**

- No `"Action": "*"` and no `"Resource": "*"` on any Allow statement.
- Maximum of four statements.

**Hints**

- `aws s3api help` and `aws logs help` list the exact action names; the IAM action is the operation
  name prefixed by the service (`s3:CopyObject` does not exist — find out what a copy actually calls).
- Ask yourself what permission "verify what it copied" needs, on **which** bucket.
- The condition key you want is `aws:RequestedRegion`.

---

### Exercise 5 — Integration: prepare the identity Lab 2 will use

**Requirements**

Lab 2 builds the VPC. Prepare for it now:

1. Using `simulate-principal-policy` (or, if Floci does not support it, by carefully reading the
   policy JSON), determine whether `usms-dev-01` currently has **every** permission Lab 2 will need:
   `ec2:CreateVpc`, `ec2:CreateSubnet`, `ec2:CreateInternetGateway`, `ec2:AttachInternetGateway`,
   `ec2:CreateRouteTable`, `ec2:CreateRoute`, `ec2:AssociateRouteTable`,
   `ec2:DescribeAvailabilityZones`, `ec2:ModifyVpcAttribute`, `ec2:CreateNatGateway`,
   `ec2:AllocateAddress`.
2. Identify which ones are **missing**.
3. Create **version 3** of `USMSDeveloperBase` adding exactly the missing actions — no more.
4. Set v3 as the default and verify that v1 and v2 still exist.
5. Extend `configs/lab-01.env` with a variable `USMS_VPC_CIDR=10.0.0.0/16` so Lab 2 can source it.

**Constraints**

- Do not delete or recreate the policy. Use `create-policy-version`.
- Do not add any action that is not on the list above.

**Expected outcome**

```text
aws iam list-policy-versions --policy-arn <USMSDeveloperBase arn> --output table
  → v1 (False), v2 (False), v3 (True)
```

**Hints**

- Step 24 shows the version workflow, including the small Python edit trick.
- Two of the actions in the list are genuinely missing from v2. Find them by reading, not guessing.
- Think about *why* `ec2:AllocateAddress` is needed for a NAT gateway.

---

## 14. Lab Assessment Checklist

Print this and tick each box. Submit it with your lab report.

```text
ENVIRONMENT
☐ Docker installed and daemon running
☐ Floci installed, running, and started with --persist
☐ AWS CLI v2 installed (aws --version shows 2.x)
☐ Profile "floci" configured with endpoint_url
☐ aws sts get-caller-identity returns account 000000000000
☐ Proved with --debug that requests go to localhost:4566
☐ Proved that stopping Floci breaks the CLI
☐ ~/aws-floci-course created with the full folder structure
☐ README.md written
☐ .gitignore written BEFORE any secret existed
☐ configs/course.env created
☐ scripts/setup/floci-up.sh works
☐ scripts/utilities/whoami.sh works

IAM — IDENTITIES
☐ 3 groups created (usms-admins, usms-developers, usms-auditors)
☐ 3 users created and tagged
☐ Each user placed in the correct group
☐ Membership verified from BOTH directions

IAM — POLICIES
☐ AWS managed policy (or local equivalent) attached to auditors
☐ USMSDeveloperBase written, validated locally, created, attached to 2 groups
☐ USMSStudentDataReadWrite written with correct bucket AND object ARNs
☐ Inline policy USMSSelfManageCredentials on usms-dev-01
☐ Explained the difference between attached and inline in your notes
☐ Policy version v2 created and set as default
☐ Confirmed v1 still exists and could be rolled back to

IAM — ROLES
☐ usms-ec2-app-role created with an ec2.amazonaws.com trust policy
☐ usms-lambda-exec-role created with a lambda.amazonaws.com trust policy
☐ usms-developer-role created with an account-principal trust policy
☐ Instance profile usms-ec2-app-profile created and contains the role
☐ sts assume-role executed; temporary credentials obtained
☐ Identified the ASIA prefix and the SessionToken in the output

CREDENTIALS & SAFETY
☐ Access key created for usms-dev-01, redirected straight into outputs/
☐ chmod 600 applied
☐ git check-ignore confirms the key file is ignored
☐ Second profile "usms-dev" created and tested
☐ Can explain the 5-step key rotation procedure

CLI SKILLS DEMONSTRATED
☐ Used --output json, table AND text
☐ Used --query to extract a single value into a variable
☐ Used a JMESPath filter [?...]
☐ Used file:// to submit a policy document
☐ Used --generate-cli-skeleton
☐ Checked an exit code with $?

WRAP-UP
☐ configs/lab-01.env generated with real ARNs and no secrets
☐ Floci snapshot "lab-01-iam-complete" saved
☐ verify-lab-01.sh passes with FAIL=0
☐ labs/lab-01-iam/README.md written
☐ Work committed to Git with no files from outputs/
☐ Exercises 1–5 attempted and documented
```

---

## 15. Review Questions

Answer in your own words in `notes/lab-01-notes.md`. These are conceptual — do not paste command
output.

1. **Trust vs permissions.** A colleague creates a role with a perfect permissions policy attached,
   but nobody can use it. What is almost certainly missing, and why does IAM separate these two
   documents in the first place?

2. **Explicit vs implicit deny.** `usms-dev-01` gets `AccessDenied` calling `iam:CreateUser`, and also
   calling `dynamodb:PutItem`. Both fail identically from the user's point of view. Explain how the two
   failures differ internally, how you would tell them apart, and why the *fix* is different in each
   case.

3. **Roles over keys.** The USMS application needs to read from S3. Explain why attaching
   `usms-ec2-app-role` to the server is more secure than putting `usms-dev-01`'s access key in the
   application's configuration file. Give two distinct reasons.

4. **The S3 ARN trap.** A student writes a policy allowing `s3:GetObject` and `s3:ListBucket` on the
   single resource `arn:aws:s3:::usms-student-data`. Downloads fail. Explain precisely why, and state
   what the corrected `Resource` values must be.

5. **The Floci illusion.** Every command in this lab succeeded. Explain why that is **not** evidence
   that your policies are correct, and describe two concrete techniques you would use to gain
   confidence in a policy before deploying it to a real AWS account.

---

## 16. What We Built

### 16.1 Reflection

#### What you learned

You went from an empty laptop to a working local cloud with a realistic, multi-layered identity model.
More importantly, you learned to think in the AWS mental model: **identities, policies and resources
are separate objects joined by ARNs**, and every request is a question IAM answers.

#### AWS concepts

`IAM` · users · groups · roles · policies (AWS managed / customer managed / inline) · policy documents
(`Version`, `Statement`, `Sid`, `Effect`, `Action`, `Resource`, `Condition`) · policy variables
(`${aws:username}`) · policy versions · trust policies vs permissions policies · principals ·
instance profiles · STS · temporary credentials · `AKIA` vs `ASIA` · access key rotation · MFA
(conceptual) · least privilege · explicit vs implicit deny · policy evaluation order · ARNs · regions
and availability zones · global vs regional services · tagging · resource naming conventions

#### AWS CLI skills

`aws <service> <operation>` grammar · built-in `help` · `--profile` · `--region` · `--endpoint-url` ·
`--output json|table|text` · `--query` (JMESPath: projections, renaming, `[?filters]`, `| [0]`) ·
`file://` parameters · `--generate-cli-skeleton` · `--debug` · `--tags` · capturing values with
`$( )` · exit codes with `$?` · named profiles and credential resolution order · `aws configure set` /
`get` / `list-profiles`

#### Floci skills

`floci start --persist --detach` · `stop` · `restart` · `status` · `wait` · `logs` · `doctor` ·
`services` · `version` · `snapshot save|list|load` · storage modes (`memory`, `hybrid`, `persistent`,
`wal`) · redirecting the AWS CLI with `endpoint_url` · proving isolation from real AWS · recognising
Floci limitations, especially the absence of IAM enforcement by default

#### Shell & engineering skills

Heredocs and the critical `<< 'EOF'` vs `<< EOF` distinction · `set -euo pipefail` · brace expansion ·
`chmod 600` and `chmod +x` · `.gitignore` written before secrets exist · `git check-ignore` ·
validating JSON with `python3 -m json.tool` · writing an idempotent setup script and a verification
script

### 16.2 Resource inventory — KEEP vs CLEAN UP

```text
╔══════════════════════════════ KEEP ══════════════════════════════╗
║ Groups        usms-admins, usms-developers, usms-auditors        ║
║ Users         usms-admin-01, usms-dev-01, usms-audit-01          ║
║ Policies      USMSDeveloperBase (v2), USMSStudentDataReadWrite,  ║
║               USMSAssumeAppRoles, USMSLambdaBasic                ║
║ Inline        USMSSelfManageCredentials on usms-dev-01           ║
║ Roles         usms-ec2-app-role, usms-lambda-exec-role,          ║
║               usms-developer-role                                ║
║ Profile       usms-ec2-app-profile  ← Lab 03 REQUIRES this       ║
║ Access key    usms-dev-01 key in outputs/ (git-ignored)          ║
║ Files         everything under ~/aws-floci-course                ║
║ Floci         running, ~/floci-data, snapshot lab-01-iam-complete║
╚══════════════════════════════════════════════════════════════════╝

╔════════════════════════════ CLEAN UP ════════════════════════════╗
║ outputs/assumed-role.json   temporary creds, already expired     ║
║ usms-intern-01              only if you created it in Step 16    ║
║                             (✏️ Your turn tasks are practice     ║
║                              only — no later lab uses it)        ║
╚══════════════════════════════════════════════════════════════════╝
```

**Safe cleanup of the two temporary items**

!!! danger "Read before running any delete command"
    **What will be deleted:** the expired temporary-credentials file, and the practice user
    `usms-intern-01`.
    **What depends on it:** nothing in this lab or any future lab.
    **Reversible?** The file: no, but it is expired and worthless. The user: yes — recreate it in
    seconds.
    **Effect on later labs:** none.

    Do **not** run any other `delete-*` command in this lab. Everything else is required by Lab 2+.

```bash
rm -f ~/aws-floci-course/outputs/assumed-role.json

# only if you created it:
aws iam remove-user-from-group --group-name usms-auditors --user-name usms-intern-01 2>/dev/null
aws iam delete-user --user-name usms-intern-01 2>/dev/null
```

Note the order: IAM will refuse to delete a user who is still a group member (`DeleteConflict`).
Dependencies are always removed inside-out.

**A cleanup script for the END of the course — do not run it now**

```bash
cat > ~/aws-floci-course/scripts/cleanup/lab-01-cleanup.sh << 'EOF'
#!/usr/bin/env bash
# ############################################################
# DO NOT RUN UNTIL THE COURSE IS FINISHED.
# Deletes the entire Lab 01 IAM foundation. Labs 02+ will break.
# ############################################################
set -uo pipefail
read -r -p "Delete ALL Lab 01 IAM resources? Type DELETE to confirm: " CONFIRM
[ "$CONFIRM" = "DELETE" ] || { echo "Aborted."; exit 1; }

for U in usms-admin-01 usms-dev-01 usms-audit-01; do
  for G in $(aws iam list-groups-for-user --user-name "$U" --query 'Groups[*].GroupName' --output text); do
    aws iam remove-user-from-group --user-name "$U" --group-name "$G"
  done
  for K in $(aws iam list-access-keys --user-name "$U" --query 'AccessKeyMetadata[*].AccessKeyId' --output text); do
    aws iam delete-access-key --user-name "$U" --access-key-id "$K"
  done
  for P in $(aws iam list-user-policies --user-name "$U" --query 'PolicyNames' --output text); do
    aws iam delete-user-policy --user-name "$U" --policy-name "$P"
  done
  aws iam delete-user --user-name "$U"
done
echo "Users removed. Groups, policies and roles left for manual review."
EOF

chmod +x ~/aws-floci-course/scripts/cleanup/lab-01-cleanup.sh
```

Notice it demands typed confirmation and does **not** delete roles or policies automatically.
Destructive automation should always be conservative.

### 16.3 Cumulative architecture after Lab 1

```text
┌────────────────────────────────────────────────────────────────┐
│                    USMS — AWS Account 000000000000             │
│                                                                │
│  ┌────────────────────── IAM  (LAB 01 ✔) ────────────────────┐ │
│  │                                                           │ │
│  │  usms-admins ─┐                     usms-ec2-app-role ────┼─┼──▶ Lab 03
│  │  usms-devs ───┼─ USMSDeveloperBase   └ usms-ec2-app-profile │ │
│  │  usms-auditors┘  USMSAssumeAppRoles                       │ │
│  │                  USMSStudentDataRW ──────────────────────-┼─┼──▶ Lab 04
│  │  usms-admin-01                      usms-lambda-exec-role─┼─┼──▶ Lab 05
│  │  usms-dev-01  (keys + inline)                             │ │
│  │  usms-audit-01                      usms-developer-role ──┼─┼──▶ Lab 02
│  └───────────────────────────────────────────────────────────┘ │
│                               │                                │
│                               ▼                                │
│              ┌──────────  VPC  (LAB 02)  ──────────┐  ⬜ next   │
│              │  10.0.0.0/16                        │            │
│              │  public subnet / private subnet     │            │
│              │  IGW · route tables · security grps │            │
│              └─────────────────────────────────────┘            │
│                     │                      │                    │
│              EC2 (Lab 03) ⬜         RDS (later) ⬜              │
│                     │                                           │
│              S3 (Lab 04) ⬜                                      │
│                     │                                           │
│              Lambda (Lab 05) ⬜                                  │
│                     │                                           │
│              SNS / SQS / CloudWatch ⬜                           │
└────────────────────────────────────────────────────────────────┘
```

---

## 17. Preparation for the Next Lab

### Lab 02 — VPC (Virtual Private Cloud)

In the next laboratory you will build the network that every USMS server will live in: a VPC with a
public and a private subnet, an internet gateway, route tables and security groups.

**What Lab 2 will reuse from Lab 1**

| From Lab 1 | Used in Lab 2 for |
| --- | --- |
| `configs/course.env` | region, endpoint, `usms-` prefix |
| `configs/lab-01.env` | role ARNs and the `USMS_VPC_CIDR` variable |
| `usms-developer-role` | you will assume it before building the network |
| `USMSDeveloperBase` policy | the EC2/VPC create permissions you added in Step 24 and Exercise 5 |
| `scripts/setup/floci-up.sh` | starting the environment |
| `scripts/utilities/whoami.sh` | confirming your identity before you build |
| The `--query` / variable-capture habit | capturing `VPC_ID`, `SUBNET_ID`, `IGW_ID` |

**Before you arrive at Lab 2, make sure**

```bash
cd ~/aws-floci-course
./scripts/setup/floci-up.sh
./scripts/utilities/verify-lab-01.sh     # must print FAIL=0
source configs/course.env
source configs/lab-01.env
echo "$USMS_ROLE_DEVELOPER"              # must print an ARN
```

**Optional pre-reading — think about these before Lab 2**

1. What is a CIDR block, and how many usable IP addresses does `10.0.0.0/16` contain?
2. What makes a subnet "public" rather than "private"? (Hint: it is not a checkbox — it is a route.)
3. Why do the private subnets in a real architecture still need outbound internet access, and what
   component provides it?
4. Why are IAM resources global, but a VPC belongs to exactly one region?

**Leave Floci running.** Lab 2 continues from exactly this state.

---

## Appendix A — Command Reference for Lab 1

### Floci

```bash
floci start --persist ~/floci-data --detach   # start with persistence
floci status | logs | services | doctor       # inspect
floci wait                                    # block until ready
floci stop | restart                          # lifecycle
floci snapshot save|list|load|delete <name>   # state management
floci env                                     # print env vars (we use profiles instead)
```

### AWS CLI configuration

```bash
aws --version
aws configure set <key> <value> --profile <name>
aws configure get <key> --profile <name>
aws configure list --profile <name>
aws configure list-profiles
aws sts get-caller-identity
```

### IAM — users and groups

```bash
aws iam create-user --user-name <n> --tags Key=K,Value=V
aws iam get-user --user-name <n>
aws iam list-users
aws iam list-user-tags --user-name <n>
aws iam create-group --group-name <g>
aws iam get-group --group-name <g>
aws iam list-groups
aws iam add-user-to-group --group-name <g> --user-name <n>
aws iam remove-user-from-group --group-name <g> --user-name <n>
aws iam list-groups-for-user --user-name <n>
```

### IAM — policies

```bash
aws iam create-policy --policy-name <p> --policy-document file://<f>.json
aws iam list-policies --scope Local|AWS
aws iam get-policy --policy-arn <arn>
aws iam get-policy-version --policy-arn <arn> --version-id <v>
aws iam create-policy-version --policy-arn <arn> --policy-document file://<f> --set-as-default
aws iam list-policy-versions --policy-arn <arn>
aws iam set-default-policy-version --policy-arn <arn> --version-id <v>
aws iam attach-group-policy  --group-name <g> --policy-arn <arn>
aws iam attach-user-policy   --user-name  <n> --policy-arn <arn>
aws iam attach-role-policy   --role-name  <r> --policy-arn <arn>
aws iam put-user-policy --user-name <n> --policy-name <p> --policy-document file://<f>
aws iam list-user-policies --user-name <n>
aws iam get-user-policy --user-name <n> --policy-name <p>
aws iam list-attached-group-policies --group-name <g>
aws iam simulate-principal-policy --policy-source-arn <arn> --action-names <a> ...
aws iam get-account-authorization-details
```

### IAM — roles and instance profiles

```bash
aws iam create-role --role-name <r> --assume-role-policy-document file://trust.json
aws iam get-role --role-name <r>
aws iam list-roles
aws iam create-instance-profile --instance-profile-name <ip>
aws iam add-role-to-instance-profile --instance-profile-name <ip> --role-name <r>
aws iam get-instance-profile --instance-profile-name <ip>
```

### IAM — access keys and STS

```bash
aws iam create-access-key --user-name <n>
aws iam list-access-keys --user-name <n>
aws iam update-access-key --user-name <n> --access-key-id <id> --status Active|Inactive
aws iam delete-access-key --user-name <n> --access-key-id <id>
aws sts assume-role --role-arn <arn> --role-session-name <s> --duration-seconds 3600
```

---

## Appendix B — JMESPath (`--query`) patterns used in this lab

| Pattern | Meaning | Example |
| --- | --- | --- |
| `Key.SubKey` | Walk into an object | `User.Arn` |
| `Key[*].Field` | One field from every element | `Users[*].UserName` |
| `Key[*].[A,B]` | Unlabelled list of two fields | `Groups[*].[GroupName,Arn]` |
| `Key[*].{X:A,Y:B}` | Renamed object → table headers | `Users[*].{User:UserName,Arn:Arn}` |
| `Key[?cond]` | Filter | ``Roles[?starts_with(RoleName,`usms-`)]`` |
| `Key[?A=='v'].B` | Filter then project | `Policies[?PolicyName=='USMSDeveloperBase'].Arn` |
| `... \| [0]` | Take the first result | `Policies[?...].Arn \| [0]` |
| `Key[0:3]` | Slice | `Users[0:3]` |

Practise an expression against saved output instead of calling AWS repeatedly — `jq` and JMESPath
differ in syntax, so use the online JMESPath evaluator, or simply re-run the CLI command with
different `--query` values against a cheap read-only operation:

```bash
aws iam list-users --query 'Users[*].UserName'            --output text
aws iam list-users --query 'Users[?starts_with(UserName, `usms-a`)].UserName' --output text
aws iam list-users --query 'length(Users)'                --output text
```

---

## Appendix C — MkDocs integration

This document is written for MkDocs with the **Material** theme. Add it to your `mkdocs.yml`:

```yaml
site_name: AWS CLI + Floci Laboratory Course
theme:
  name: material
  features:
    - content.code.copy
    - navigation.sections
    - navigation.top
    - toc.follow

markdown_extensions:
  - admonition
  - attr_list
  - def_list
  - footnotes
  - md_in_html
  - tables
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true

nav:
  - Home: index.md
  - Labs:
      - "Lab 01 — IAM": labs/lab-01-iam.md
```

Place this file at `docs/labs/lab-01-iam.md`, then:

```bash
pip install mkdocs-material
mkdocs serve
```

The tabbed OS-specific instructions require `pymdownx.tabbed`; the coloured callouts require
`admonition` and `pymdownx.details`. Without those extensions the content still renders, just without
the styling.

---

## Sources

- [Floci — Local Cloud Emulators](https://floci.io/)
- [floci-io/floci on GitHub](https://github.com/floci-io/floci)
- [floci-io/floci-cli on GitHub](https://github.com/floci-io/floci-cli)
- [Floci documentation — introduction](https://fredpena-floci.mintlify.app/introduction)
- [floci/floci on Docker Hub](https://hub.docker.com/r/floci/floci)

---

!!! success "End of Lab 01"
    **Next:** Lab 02 — VPC. Leave Floci running.
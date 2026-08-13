# Lab 1 - Identity and Access Management 

## Lab Objective

By the end of this laboratory you should be able to:

**Environment**

1. Verify that Docker and Docker Compose are installed and running.
2. Install the **Floci** local AWS emulator and explain its four storage modes.
3. Run Floci **reproducibly** with Docker Compose, so that state survives every stop and restart.
4. Install AWS CLI v2 and confirm its version.
5. Create and use a named **AWS CLI profile** that points at Floci.
6. **Prove** two separate things: that your commands reach Floci and never touch real AWS, and that your data actually persists.
7. Create and explain a clean, version-controlled project directory structure that cannot leak secrets.

**AWS CLI**

8. Read the `aws <service> <command> [options]` grammar and use `help`.
9. Switch between `--output json`, `--output table` and `--output text`.
10. Extract a single value with `--query` (JMESPath) and store it in a shell variable.
11. Pass a JSON file to a command with `file://` and generate a template with `--generate-cli-skeleton`.
12. Interpret AWS CLI exit codes and error messages.

**IAM**

13. Explain the structure of an ARN and read one correctly.
14. Create IAM users, groups and roles using the CLI.
15. Write a valid IAM policy document (Version, Statement, Effect, Action, Resource, Condition).
16. Distinguish AWS managed, customer managed and inline policies, and choose between them.
17. Distinguish a **permissions policy** from a **trust policy**.
18. Create an instance profile and understand why EC2 needs one.
19. Obtain temporary credentials with `sts assume-role` and use them.
20. Create access keys and store them without ever committing them to Git.
21. Apply the principle of **least privilege** and diagnose an `AccessDenied` error.

---

## 1. Intro

Lab 1 is the first laboratory of the course. It therefore has a double job:

1. **Bootstrap** the entire working environment (Part A).
2. **Build the IAM foundation** that every later lab depends on (Part B).

### Current Environment

```text
Created in previous labs:
- (nothing — this is Lab 1)

Created in this lab:
- Project directory ~/aws-floci-course with full folder structure
- A Git repository, initialised BEFORE any secret exists
- docker-compose.yml pinning Floci to durable storage on port 4566
- AWS CLI v2 installed, profile "floci" configured
- IAM groups:   usms-admins, usms-developers, usms-auditors
- IAM users:    usms-admin-01, usms-dev-01, usms-audit-01
- Policies:     USMSDeveloperBase, USMSStudentDataReadWrite,
                USMSAssumeAppRoles, USMSLambdaBasic,
                USMSSelfManageCredentials (inline),
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
- docker-compose.yml       → starts the environment for every later lab
```

## 2. What We Are Building

### 2.1 The identity model

Three human-shaped identities and three machine-shaped identities:

| Identity | Type | Who/what uses it | Permissions |
| --- | --- | --- | --- |
| `usms-admin-01` | user → `usms-admins` | The lead cloud engineer | Broad (course-scoped) |
| `usms-dev-01` | user → `usms-developers` | You, building infrastructure | Build + inspect USMS resources |
| `usms-audit-01` | user → `usms-auditors` | The university auditor | Read-only, everywhere |
| `usms-ec2-app-role` | role | The USMS application server | Read/write student data in S3 |
| `usms-lambda-exec-role` | role | Notification functions (Lab 05) | Logs + messaging |
| `usms-developer-role` | role | Assumed *temporarily* by developers | Elevated build permissions |

### 2.2 Why groups instead of attaching policies to users?

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
(with one deliberate exception in Step 25, which exists to teach inline policies).

### 2.3 The environment we build first

```text
   Your machine
   ┌─────────────────────────────────────────────────────────┐
   │                                                          │
   │  ~/aws-floci-course/          ~/floci-data/              │
   │  ├── docker-compose.yml ──┐   (bind-mounted into the     │
   │  ├── configs/             │    container as /app/data —  │
   │  ├── policies/            │    this is where your IAM    │
   │  └── scripts/             │    users actually live)      │
   │                           │            ▲                 │
   │                           ▼            │                 │
   │              ┌────────────────────────────────┐          │
   │  aws CLI ───▶│  Docker container "floci"      │          │
   │  :4566       │  FLOCI_STORAGE_MODE=hybrid     │          │
   │              └────────────────────────────────┘          │
   └─────────────────────────────────────────────────────────┘
```

The single most important line in that diagram is `FLOCI_STORAGE_MODE=hybrid`. Without it, the
arrow to `~/floci-data/` exists but almost nothing durable travels along it.

---

## 3. Directory Structure

### 3.1 The structure you will create

```text
aws-floci-course/
├── README.md                  
├── .gitignore                 
├── docker-compose.yml         
├── .env                       
│
├── labs/                      # one folder per laboratory
│   └── lab-01-iam/
│       └── README.md          # your notes + evidence for this lab
│
├── policies/                  
│   ├── usms-developer-base-policy.json
│   ├── usms-student-data-rw-policy.json
│   ├── usms-assume-app-roles-policy.json
│   ├── usms-self-manage-credentials.json
│   ├── usms-lambda-basic-policy.json
│   ├── trust-ec2.json
│   ├── trust-lambda.json
│   └── trust-account-developers.json
│
├── configs/                   # non-secret configuration (committed)
│   ├── course.env             
│   └── lab-01.env             
│
├── scripts/
│   ├── setup/                 # bring the environment up and down
│   │   ├── floci-up.sh
│   │   └── floci-down.sh
│   ├── utilities/             # small helpers reused all course
│   │   ├── whoami.sh
│   │   ├── floci-storage-check.sh
│   │   └── verify-lab-01.sh
│   └── cleanup/               # careful, controlled teardown
│       ├── floci-prune-volumes.sh
│       └── lab-01-cleanup.sh
│
├── templates/                 # CLI skeletons, CloudFormation (later labs)
├── outputs/                   # command output + SECRETS (never committed)
│   └── .gitkeep
├── screenshots/               # evidence for your lab report
└── notes/                     # your own learning notes
    └── lab-01-notes.md
```

### 3.2 Why each folder exists

| Folder | Purpose | Who creates the files | Commit to Git? |
| --- | --- | --- | --- |
| `labs/` | One folder per lab; your working area and write-up | You | Yes |
| `policies/` | Reusable JSON policy documents. Kept **outside** `labs/` because Lab 4 will reuse a policy written in Lab 1 | You |  Yes |
| `configs/` | Environment values (region, endpoint, ARNs). No secrets | You + scripts |  Yes |
| `scripts/setup/` | Idempotent scripts that build things | You |  Yes |
| `scripts/utilities/` | Small helpers (`whoami.sh`) used every lab | You |  Yes |
| `scripts/cleanup/` | Deletion scripts — reviewed before running | You |  Yes |
| `templates/` | `--generate-cli-skeleton` output, CloudFormation templates | Generated |  Yes |
| `outputs/` | Raw JSON responses **and access keys** | Generated |  **Never** |
| `screenshots/` | Proof for your submitted report | You |  Optional (size) |
| `notes/` | Your own understanding, mistakes, fixes | You |  Yes |

Two files sit at the root and are easy to overlook:

| File | Purpose | Commit? |
| --- | --- | --- |
| `docker-compose.yml` | The **single source of truth** for how Floci runs. Contains no secrets | Yes |
| `.env` | Generated by `floci-up.sh`. Contains machine-specific absolute paths |  No |

!!! danger "The single most important rule in this table"
    `outputs/` will contain a **real secret access key** after Step 31. It is listed in `.gitignore`
    for that reason, and Step 6 makes you write `.gitignore` **before** the repository exists.
    Publishing AWS access keys to a public Git repository is one of the most common causes of
    real-world cloud breaches:  bots scan GitHub for them within seconds of a push.

## 4. Step-by-Step Implementation

The lab has two parts:

- **Part A — Steps 1 to 15**: build the environment.
- **Part B — Steps 16 to 33**: build the IAM foundation for USMS.

Part A is longer than it used to be, because it now includes the configuration that makes your work
survive. Do not skip ahead — Part B is worthless if Part A is wrong.

## PART A — Environment Setup (Steps 1–15)

### Step 1 — Open a terminal and identify your system (**OPTIONAL**)

**Purpose**

Every later step depends on knowing which operating system and shell you are using.

**Run from** : anywhere

**Command**

```bash
uname -s -m
echo "shell = $SHELL"
echo "home  = $HOME"
```

**What the command does**

- `uname` prints information about the system kernel.
- `-s` prints the **s**ystem name (`Linux` or `Darwin` for macOS).
- `-m` prints the **m**achine hardware name (`x86_64` for Intel/AMD, `arm64`/`aarch64` for Apple Silicon).
- `$SHELL` and `$HOME` are **environment variables** — named values your shell keeps in memory.

**Expected result**

```text
Linux x86_64
shell = /bin/bash
home  = /home/student
```

> Example output — yours will differ. macOS on Apple Silicon shows `Darwin arm64` and a home
> directory like `/Users/student`.

**Write your `$HOME` down.** You will need the literal, absolute value in Step 8, and a very common
Lab-1 failure is caused by writing `~` where an absolute path is required.

!!! success "**Checkpoint**"

    ```text
    You know your OS, architecture, and the absolute path of your home directory.
    If you are on Windows and this command failed, you are not in WSL.
    ```

---

### Step 2 — Verify Docker and Docker Compose (OPTIONAL)

**Purpose**

Floci runs as a Docker container, and from Step 8 onwards we describe that container with Docker
Compose. If either is missing, nothing else in this course works.

**Run from** : anywhere

**Command**

{% raw %}```bash
docker --version
docker info --format '{{.ServerVersion}}'
docker compose version
```{% endraw %}

**What the command does**

- `docker --version` asks the **Docker client** (the command-line program) its version. This succeeds
  even if Docker itself is not running.
- `docker info` talks to the **Docker daemon** (the background service that actually runs containers).
{% raw %}  This is the real test. `--format '{{.ServerVersion}}'` prints just one field instead of 60 lines.{% endraw %}
- `docker compose version` checks the **Compose v2 plugin**, which is what reads
  `docker-compose.yml`. Note the space: `docker compose` (v2, a plugin) is not the same program as
  `docker-compose` (v1, a separate Python tool, now retired). This course requires v2.

Understanding the client/daemon split matters: the most common Docker error in this course is
"client works, daemon is not running".

**Expected result**

```text
Docker version 27.3.1, build ce1223035a
27.3.1
Docker Compose version v2.29.7
```

> Example output — version numbers will differ. Any Compose `v2.x` is fine.

**If Docker is not installed**

=== "Linux (Ubuntu/Debian)"

    ```bash
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    newgrp docker
    ```

    `usermod -aG docker $USER` adds you to the `docker` group so you don't need `sudo` for every
    command. `newgrp docker` applies the new group in the current shell without logging out.
    The `get.docker.com` script installs the Compose v2 plugin as well.

=== "macOS"

    Download **Docker Desktop** from `https://www.docker.com/products/docker-desktop/`, install it,
    and launch it from Applications. Wait until the whale icon in the menu bar stops animating.
    Docker Desktop bundles Compose v2.

=== "Windows (WSL2)"

    Install **Docker Desktop for Windows**, then enable
    *Settings → Resources → WSL Integration → Ubuntu*. Verify from the **Ubuntu** terminal, not
    PowerShell.

**If `docker compose version` fails but `docker --version` works**

You have Docker without the Compose plugin:

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-plugin   # Debian/Ubuntu
```

**Verify**

```bash
docker run --rm hello-world
```

`--rm` deletes the container as soon as it finishes, so it leaves nothing behind.

!!! success "**Checkpoint 1**"

    ```text
    Docker
    ├── client   : installed
    ├── daemon   : running
    ├── compose  : v2 plugin present
    └── test run : "Hello from Docker!" printed
    ```

---

### Step 3 — Install the Floci CLI (SKIP IF ALREADY DONE)

**Purpose**

Floci is the **local AWS emulator** this course uses instead of a real AWS account. The Floci CLI is a
small program that inspects and manages the emulator.

**What Floci is**

Floci is an open-source, MIT-licensed local cloud emulator. It listens on a port on your machine and
answers AWS API calls exactly as the real AWS endpoints would, so the **AWS CLI cannot tell the
difference**. It supports around 69 AWS services, including all of IAM and STS.

**Why we use it**

| Real AWS | Floci |
| --- | --- |
| Requires an account + credit card | Requires nothing |
| Mistakes can cost money | Mistakes cost nothing |
| Requires internet | Runs offline |
| Deleting resources takes minutes | Reset in seconds |
| Shared classroom account = chaos | Every student has a private "cloud" |

!!! note "We install the CLI, but we will not use `floci start`"
    From Step 9 onwards, the container is started by Docker Compose, not by `floci start`.
    Step 7 explains why. The CLI is still worth installing: `floci status`, `floci logs`,
    `floci services`, `floci doctor` and `floci snapshot` all work perfectly well against a
    Compose-managed container, and you will use them throughout the course.

**Run from** : anywhere

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
server     not running
```

> Example output — versions will differ. `server` reporting "not running" is expected: we have not
> started the container yet.

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
sudo lsof -i :4566          # macOS / Linux
```

Either stop that program, or change the port in `docker-compose.yml` in Step 8 — and if you do,
change it in `configs/course.env` too. Because both live in one file each, that is a two-line change
rather than a hunt through every command in the course. That is exactly why we are about to build
the project structure *before* starting anything.

---

### Step 5 — Create the course directory structure (Important)

**Purpose**

Create the folder tree from Section 7 **before** starting Floci, so that the emulator's configuration
is a committed file from the very first run.

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
pwd
```

**What the command does**

- `cd ~` moves to your home directory (`~` is shorthand for it).
- `mkdir -p` creates directories including parents, and does not error if they already exist —
  which makes the command safe to run twice.
- `{a,b,c}` is **brace expansion**: the shell expands it into several arguments, so one `mkdir`
  creates seven folders. Note there must be **no spaces** inside the braces.
- `pwd` prints the working directory, confirming where you are.

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

**From here to the end of Part A, stay in `~/aws-floci-course`.** Every command below assumes it.

---

### Step 6 — Write `.gitignore` and initialise Git — before any secret exists

**Purpose**

A secret that is never committed cannot be leaked. The only reliable way to guarantee that is to
write the ignore rules **before** the repository contains anything, and before any command has
produced a credential.

**Run from**

```text
aws-floci-course/
```

#### 6.1 Write the ignore rules

```bash
cat > .gitignore << 'EOF'
# ============================================================
#  aws-floci-course/.gitignore
#  Written BEFORE any secret existed. Keep it that way.
# ============================================================

# ---- Command output and SECRETS ----
# NOTE the trailing /* — see the explanation below. It matters.
outputs/*
!outputs/.gitkeep

# ---- Generated Compose configuration ----
# floci-up.sh writes this. It holds machine-specific absolute paths.
.env
.env.local

# ---- Emulator state ----
floci-data/
data/
.floci/

# ---- Credentials of every shape ----
*.pem
*.key
*-access-key.json
*credentials*

# ---- OS / editor noise ----
.DS_Store
Thumbs.db
*.swp
.vscode/
.idea/
EOF

touch outputs/.gitkeep
```

!!! bug "`outputs/` vs `outputs/*` — a real bug, not a style preference"
    It is tempting to write:

    ```text
    outputs/
    !outputs/.gitkeep
    ```

    **This does not work.** Git's rule is explicit: *it is not possible to re-include a file if a
    parent directory of that file is excluded.* Once `outputs/` excludes the whole directory, Git
    never even looks inside it, so the `!outputs/.gitkeep` line has no effect and the folder
    silently disappears from your repository.

    Writing `outputs/*` excludes the directory's **contents** while leaving the directory itself
    visible to Git, so the negation works. You will verify this in the next command — do not skip it.

#### 6.2 Initialise the repository and prove the rules work

```bash
git init -q
git add .gitignore outputs/.gitkeep
git status --short
```

**Expected result**

```text
A  .gitignore
A  outputs/.gitkeep
```

Both files staged. If `outputs/.gitkeep` is **missing** from that list, your `.gitignore` has the
`outputs/` form rather than `outputs/*` — fix it before continuing.

**Now prove a secret would be blocked**

```bash
echo '{"secret":"pretend-this-is-real"}' > outputs/fake-key.json
git status --short
git check-ignore -v outputs/fake-key.json
rm outputs/fake-key.json
```

**Expected result**

```text
A  .gitignore
A  outputs/.gitkeep
.gitignore:8:outputs/*	outputs/fake-key.json
```

The fake key does **not** appear in `git status`, and `git check-ignore -v` names the exact file and
line number of the rule that blocked it. Seeing the rule named is far more convincing than seeing
nothing happen.

```bash
git commit -q -m "chore: ignore secrets before the repo can hold any"
git log --oneline
```

!!! success "**Checkpoint 2**"

    ```text
    Git
    ├── repository initialised
    ├── .gitignore committed as the FIRST commit
    ├── outputs/.gitkeep tracked (proves the negation works)
    └── a test secret was demonstrably blocked
    ```

---

### Step 7 — Understand Floci storage modes (read this before you start anything)

**Purpose**

This is the single most important concept in Part A.

#### 7.1 The four storage modes

Floci decides how durable its state is from one environment variable, `FLOCI_STORAGE_MODE`:

| Mode | Behaviour | Good for |
| --- | --- | --- |
| `memory` | **Everything is lost when the container stops** | CI pipelines, throwaway tests |
| `hybrid` | In-memory reads, asynchronous flush to disk | **Development — our choice** |
| `persistent` | Synchronous disk write on every change | Maximum safety, slower |
| `wal` | Append-only write-ahead log with compaction | High-write workloads |

**The default is `memory`.** 

#### 7.2 Why `floci start --persist ~/floci-data` is not enough

Three separate mechanisms are involved, and the `--persist` flag only touches part of one of them.

**Cause 1 — a directory is not a mode.**
`--persist` gives Floci a host directory to mount at `/app/data`. It does not change
`FLOCI_STORAGE_MODE`. In `memory` mode Floci writes almost nothing durable into that directory —
and, because it correctly assumes its own state is disposable, it also **deletes the Docker volumes
it created** on teardown. That is why students see a brand-new volume appear on every restart and
conclude "Docker is ignoring my volume". Docker is not ignoring anything; Floci is cleaning up after
itself exactly as designed.

**Cause 2 — sidecar services use a different variable entirely.**
Some AWS services run as *child containers* that Floci launches: RDS, OpenSearch, MSK, ECR,
ElastiCache, Lambda, ECS, EKS. Their data does **not** travel through `--persist`. By default they
get named Docker volumes labelled `floci=true`. Pointing them at your disk needs a different
variable, `FLOCI_STORAGE_HOST_PERSISTENT_PATH`, and that variable requires an **absolute** path —
Floci rejects relative paths, and neither Docker nor Floci expands `~`. A literal `~/floci-data`
written into a config file creates a directory actually named `~`.

**Cause 3 — CLI flags are not remembered.**
`floci start` stores nothing about a previous run. A plain `floci start`, a `floci restart`, a Docker
Desktop restart, or a `floci stop --remove` all bring the container back on **defaults** — memory
mode, no bind mount. One such restart silently wipes everything, and nothing warns you.

#### 7.3 The three settings that actually matter

```yaml
FLOCI_STORAGE_MODE: hybrid                        # 1. durability ON (default is memory)
FLOCI_STORAGE_PERSISTENT_PATH: /app/data          # 2. where Floci writes, container side
FLOCI_STORAGE_HOST_PERSISTENT_PATH: /home/you/floci-data   # 3. sidecars, host side, ABSOLUTE
```

Plus one setting that makes debugging far easier, by giving Floci's child containers and volumes
stable, greppable names instead of effectively random ones:

```yaml
FLOCI_DOCKER_RESOURCE_NAMESPACE: floci-course
```
<!-- 
#### 7.3 Why Docker Compose, and not the CLI

Cause 3 above is not solved by typing the right flags — it is solved by not typing flags at all.
A committed `docker-compose.yml` cannot drift, is reviewable by your instructor, is identical on
every student's machine, and is itself a piece of coursework evidence.

```text
floci start --persist ...          docker compose up -d
 ├── flags typed by hand            ├── configuration is a committed file
 ├── forgotten on every restart     ├── identical on every restart
 ├── differs between students       ├── identical for every student
 └── invisible in your repo         └── reviewable in your repo
``` 
-->

!!! question "**Think about it**"

    Write two sentences in `notes/lab-01-notes.md` answering: *if `--persist` mounts
    a directory correctly, why is the directory almost empty in `memory` mode?* You will check your
    answer against real output in Step 14.


### Step 8 — Write `docker-compose.yml` and `configs/course.env`

**Purpose**

Capture the configuration from Step 7 in two committed files.

**Run from**

```text
aws-floci-course/
```

#### 8.1 `configs/course.env` — values every lab needs

```bash
cat > configs/course.env << 'EOF'
# =====================================================================
# USMS Course — shared configuration
# Sourced by every lab:   source ~/aws-floci-course/configs/course.env
# Contains NO secrets. Safe to commit.
# =====================================================================

# --- Where Floci keeps its state on YOUR machine ---------------------
# MUST be absolute. Floci rejects relative paths and does not expand ~.
# $HOME is expanded when this file is SOURCED by bash, which is why the
# value below is safe here but would be wrong pasted into a YAML file.
export FLOCI_HOST_DATA_DIR="$HOME/floci-data"

# hybrid     = in-memory reads, async flush to disk  (our choice)
# persistent = synchronous write on every change     (slower, safest)
# wal        = append-only write-ahead log           (high-write)
# memory     = NOTHING SURVIVES A RESTART            (Floci's default)
export FLOCI_STORAGE_MODE="hybrid"

# --- Container / Compose identity ------------------------------------
export FLOCI_CONTAINER_NAME="floci"
export FLOCI_COMPOSE_PROJECT="floci-course"

# --- AWS CLI ----------------------------------------------------------
export AWS_PROFILE=floci
export FLOCI_ENDPOINT=http://localhost:4566
export AWS_REGION_COURSE=us-east-1
export ACCOUNT_ID=000000000000

# --- Project naming convention: every resource starts with usms- ------
export PROJECT=usms
export COURSE_ROOT="$HOME/aws-floci-course"
EOF
```

!!! note "Why a naming convention matters"
    Every resource in this course is prefixed `usms-`. In a real shared AWS account this is how you
    find, filter, bill and safely delete *your* resources without touching anybody else's. You will
    use it in Lab 2 with `--filters`, and in cleanup scripts.

!!! warning "This file exports `AWS_PROFILE` and nothing else AWS-related"
    It deliberately does **not** export `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID` or
    `AWS_SECRET_ACCESS_KEY`. Step 11 explains the credential resolution order and why mixing
    environment variables with profiles makes failures very hard to diagnose. This course uses
    profiles.

#### 8.2 `docker-compose.yml` 

```bash
cat > docker-compose.yml << 'EOF'
# =============================================================================
#  aws-floci-course — pinned Floci environment
#  Bring up with:  ./scripts/setup/floci-up.sh
#  Pause with:     ./scripts/setup/floci-down.sh     (state is KEPT)
#  NEVER run:      docker compose down -v            (state is DESTROYED)
# =============================================================================

name: floci-course

services:
  floci:
    image: floci/floci:latest
    # Named "floci" on purpose: a stray `floci start` then fails loudly with a
    # name conflict instead of quietly shadowing this container with an empty one.
    container_name: floci
    restart: unless-stopped

    ports:
      # The only port Labs 1 and 2 need. All AWS API calls go here.
      - "4566:4566"
      # Sidecar service ports. Commented out until Lab 03, because publishing
      # ports you are not using is the most common cause of a "port is already
      # allocated" failure on a shared or busy machine.
      # Uncomment the line you need; the ranges are capped in `environment:`
      # below so each stays small.
      # - "5100-5104:5100-5104"     # ECR registries        (Lab 03+)
      # - "6379-6383:6379-6383"     # ElastiCache proxies   (later)
      # - "7001-7005:7001-7005"     # RDS proxies           (later)
      # - "9200-9209:9200-9209"     # Lambda Runtime API    (Lab 05)
      # - "9400-9404:9400-9404"     # OpenSearch proxies    (later)

    volumes:
      # Lets Floci spawn sidecar containers (Lambda, RDS, ElastiCache, ...).
      # Required from Lab 05 onwards; harmless now.
      - /var/run/docker.sock:/var/run/docker.sock
      # Floci's own state (IAM, S3, DynamoDB, ...) as browsable files on disk.
      # The value comes from .env, which floci-up.sh generates with an absolute
      # path. Compose does NOT expand "~", which is why we never write one here.
      - ${FLOCI_HOST_DATA_DIR:?run ./scripts/setup/floci-up.sh instead of docker compose directly}:/app/data

    environment:
      # --- The three settings that make persistence real -----------------
      FLOCI_STORAGE_MODE: ${FLOCI_STORAGE_MODE:-hybrid}
      FLOCI_STORAGE_PERSISTENT_PATH: /app/data
      FLOCI_STORAGE_HOST_PERSISTENT_PATH: ${FLOCI_HOST_DATA_DIR}

      # Never auto-delete a volume when an AWS resource is deleted. Teardown
      # stays explicit and under your control (scripts/cleanup/).
      FLOCI_STORAGE_PRUNE_VOLUMES_ON_DELETE: "false"

      # Stable, predictable names for every child container and volume Floci
      # creates, so `docker volume ls` is readable instead of random.
      FLOCI_DOCKER_RESOURCE_NAMESPACE: floci-course

      # Compose network, so sidecar containers can reach the emulator by name.
      FLOCI_HOSTNAME: floci
      FLOCI_SERVICES_DOCKER_NETWORK: floci-course_default

      # --- Cap the sidecar port ranges -----------------------------------
      # Floci's defaults are 100 ports each; ~600 published ports makes Docker
      # Desktop very slow to start. These caps keep the commented `ports:`
      # block above small and matching.
      FLOCI_SERVICES_ECR_REGISTRY_BASE_PORT: "5100"
      FLOCI_SERVICES_ECR_REGISTRY_MAX_PORT: "5104"
      FLOCI_SERVICES_ELASTICACHE_PROXY_BASE_PORT: "6379"
      FLOCI_SERVICES_ELASTICACHE_PROXY_MAX_PORT: "6383"
      FLOCI_SERVICES_RDS_PROXY_BASE_PORT: "7001"
      FLOCI_SERVICES_RDS_PROXY_MAX_PORT: "7005"
      FLOCI_SERVICES_LAMBDA_RUNTIME_API_BASE_PORT: "9200"
      FLOCI_SERVICES_LAMBDA_RUNTIME_API_MAX_PORT: "9209"
      FLOCI_SERVICES_OPENSEARCH_PROXY_BASE_PORT: "9400"
      FLOCI_SERVICES_OPENSEARCH_PROXY_MAX_PORT: "9404"

    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:4566/_floci/health || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 30
      start_period: 20s

# There is deliberately no top-level `volumes:` block. All state lives in the
# host bind mount, so nothing here can be silently orphaned by Docker.
EOF
```

**Read the file before you run it**

Four things are worth understanding, because you will be asked about them:

| Line | Why it is there |
| --- | --- |
| `FLOCI_STORAGE_MODE: hybrid` | Turns durability on. Without it the rest is decoration |
| `${FLOCI_HOST_DATA_DIR:?...}` | The `:?` form makes Compose **fail with your error message** rather than mount something wrong. Try `docker compose config` right now to see it fire |
| `/var/run/docker.sock` | Lets Floci launch sidecar containers. Needed from Lab 05 |
| `container_name: floci` | Makes a stray `floci start` collide loudly instead of failing silently |

**Verify Compose can parse it**

```bash
docker compose config >/dev/null && echo "compose file is valid"
```

**Expected result**

```text
error while interpolating services.floci.volumes.[]: required variable
FLOCI_HOST_DATA_DIR is missing a value: run ./scripts/setup/floci-up.sh
instead of docker compose directly
```

That error is **correct and expected** — it is the `:?` guard working. `.env` does not exist yet;
Step 9 writes it. If instead you saw `compose file is valid`, you have a stale `.env` from an earlier
attempt; delete it with `rm -f .env` and re-run.

---

### Step 9 — Write the start/stop scripts and bring Floci up

**Purpose**

Wrap Compose in two short scripts, so starting the course environment is one command that also
checks its own work.

**Run from**

```text
aws-floci-course/
```

#### 9.1 `scripts/setup/floci-up.sh`

{% raw %}```bash
cat > scripts/setup/floci-up.sh << 'EOF'
#!/usr/bin/env bash
# Start the course Floci environment with durable storage. Idempotent.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. Preconditions -------------------------------------------------
command -v docker >/dev/null || die "docker not found on PATH"
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and retry."
case "$FLOCI_HOST_DATA_DIR" in
  /*) ;;
  *)  die "FLOCI_HOST_DATA_DIR must be ABSOLUTE, got: $FLOCI_HOST_DATA_DIR" ;;
esac

# --- 2. Refuse to fight a container this project did not create -------
if docker container inspect "$FLOCI_CONTAINER_NAME" >/dev/null 2>&1; then
  owner="$(docker container inspect "$FLOCI_CONTAINER_NAME" \
            --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  if [ "$owner" != "$FLOCI_COMPOSE_PROJECT" ]; then
    warn "A container named '$FLOCI_CONTAINER_NAME' exists but Compose did not create it."
    warn "It was almost certainly started by 'floci start' and its data is not persisted."
    warn "Remove it, then re-run this script:"
    warn "    floci stop --remove      # or:  docker rm -f $FLOCI_CONTAINER_NAME"
    die  "Refusing to continue."
  fi
fi

# --- 3. Prepare the host state directory ------------------------------
mkdir -p "$FLOCI_HOST_DATA_DIR"
log "State directory: $FLOCI_HOST_DATA_DIR"

# --- 4. Hand Compose an absolute, fully expanded path ------------------
# Compose does not expand "~". Writing .env removes all ambiguity about
# which directory is mounted, wherever you run docker compose from.
cat > "$REPO_ROOT/.env" <<ENVEOF
# GENERATED by scripts/setup/floci-up.sh — do not edit, do not commit.
FLOCI_HOST_DATA_DIR=$FLOCI_HOST_DATA_DIR
FLOCI_STORAGE_MODE=$FLOCI_STORAGE_MODE
ENVEOF

# --- 5. Up ------------------------------------------------------------
log "Starting Floci (storage mode: $FLOCI_STORAGE_MODE)"
docker compose up -d

# --- 6. Wait for readiness --------------------------------------------
log "Waiting for the AWS endpoint to become healthy..."
deadline=$(( $(date +%s) + 180 ))
until curl -sf "http://localhost:4566/_floci/health" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    docker compose logs --tail 50 floci >&2 || true
    die "Floci did not become healthy within 180s (logs above)."
  fi
  sleep 2
done

# --- 7. Prove the mount is real, not a phantom volume -----------------
mount_src="$(docker container inspect "$FLOCI_CONTAINER_NAME" \
  --format '{{ range .Mounts }}{{ if eq .Destination "/app/data" }}{{ .Type }}:{{ .Source }}{{ end }}{{ end }}')"
case "$mount_src" in
  bind:*) log "Verified /app/data -> ${mount_src#bind:}" ;;
  "")     die "/app/data is not mounted at all. Check docker-compose.yml." ;;
  *)      warn "/app/data is a '$mount_src', not a host bind mount." ;;
esac

log "Floci is up at $FLOCI_ENDPOINT"
EOF

chmod +x scripts/setup/floci-up.sh
```{% endraw %}

**What the script does**

- `#!/usr/bin/env bash` — the **shebang**: tells the OS which interpreter to use.
- `set -E` propagate error traps; `-e` exit immediately on any failing command; `-u` error on
  undefined variables; `-o pipefail` make a pipeline fail if any stage fails. Together they stop a
  broken script from quietly continuing.
- `${BASH_SOURCE[0]}` is the script's own path. Combined with `cd ... && pwd` it resolves the repo
  root no matter which directory you invoke the script from — more reliable than `$0`.
- Section 2 is the guard that turns the *silent* failure of Step 7's Cause 3 into a loud one.
- Section 7 is not decoration: it asks Docker what is actually mounted and fails if the answer is
  not a host bind mount. A script that verifies its own work is worth ten that assume.

#### 9.2 `scripts/setup/floci-down.sh`

```bash
cat > scripts/setup/floci-down.sh << 'EOF'
#!/usr/bin/env bash
# Pause Floci. YOUR STATE IS KEPT.
#
#   docker compose stop     container stopped, state kept        <-- this
#   docker compose down     container removed, bind mount kept
#   docker compose down -v  container removed, VOLUMES DESTROYED <-- never
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"

docker compose stop
printf '\033[1;34m==>\033[0m Floci stopped. State preserved in %s\n' "$FLOCI_HOST_DATA_DIR"
EOF

chmod +x scripts/setup/floci-down.sh
```

#### 9.3 Start it

```bash
./scripts/setup/floci-up.sh
```

**Expected result**

```text
==> State directory: /home/student/floci-data
==> Starting Floci (storage mode: hybrid)
[+] Running 2/2
 ✔ Network floci-course_default  Created
 ✔ Container floci               Started
==> Waiting for the AWS endpoint to become healthy...
==> Verified /app/data -> /home/student/floci-data
==> Floci is up at http://localhost:4566
```

> Example output. The first run pulls the image, which can take several minutes.

**Verify — three independent ways**

```bash
docker compose ps
floci status
curl -s http://localhost:4566/_floci/health | head -c 300 ; echo
```

The third is the most convincing: it is a raw HTTP request that involves neither Docker nor the Floci
CLI. If JSON comes back, something really is listening on port 4566. Floci also serves
`/_localstack/health` for LocalStack compatibility, so either path works.

**Useful lifecycle commands (learn these now)**

```bash
./scripts/setup/floci-up.sh     # start or resume — safe to run any time
./scripts/setup/floci-down.sh   # pause, state kept
docker compose ps               # is it running and healthy?
docker compose logs -f floci    # stream server logs — your best debugging tool
floci status                    # the CLI's view of the same container
floci logs                      # same logs, via the CLI
floci services                  # which AWS services are enabled
```

!!! danger "Commands that will destroy your coursework"
    | Command | What it does |
    | --- | --- |
    | `docker compose down -v` | The `-v` deletes volumes |
    | `docker volume prune` | Unfiltered — hits every unused volume on your machine |
    | `floci start ...` | Bypasses Compose; recreates the Step 7 bug |
    | `rm -rf ~/floci-data` | That directory **is** your IAM state |

!!! success "**Checkpoint 3**"

    ```text
    Floci
    ├── container : running (Compose project "floci-course")
    ├── endpoint  : http://localhost:4566
    ├── storage   : hybrid, bind-mounted to ~/floci-data
    └── health    : verified by curl, independently of Docker and the CLI
    ```

---

### Step 10 — Install the AWS CLI (version 2)

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

!!! danger "It must say `aws-cli/2.x`, and ideally 2.13 or newer"
    If it says `aws-cli/1.x`, you have AWS CLI v1. This course requires **v2**, because only v2
    supports the `endpoint_url` profile setting that redirects the CLI to Floci cleanly. Uninstall v1
    (`pip uninstall awscli`) and install v2.

    `endpoint_url` as a *profile* setting arrived in AWS CLI **2.13**. On an older 2.x you will have
    to pass `--endpoint-url http://localhost:4566` on every command. Step 12 shows how to check.

**Explore the CLI's own help**

```bash
aws help
aws iam help
aws iam create-user help
```

Press `q` to quit the help pager. This built-in help is the authoritative reference — you will use it
constantly. It shows every option, its type, and examples.

---

### Step 11 — Understand AWS credentials, regions and profiles

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
1. Command-line options       (--profile, --region, --endpoint-url)
2. Environment variables      (AWS_ACCESS_KEY_ID, AWS_ENDPOINT_URL, ...)
3. ~/.aws/credentials         (the named profile's secrets)
4. ~/.aws/config              (the named profile's settings)
5. IAM role attached to the machine (EC2 instance profile — Lab 3)
```

!!! warning "Do not mix profiles and environment variables"
    Floci offers `eval $(floci env)`, which exports `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, etc. into
    your shell. That is convenient, but if you *also* use `--profile`, it becomes very hard to reason
    about which credentials were actually used — level 2 silently beats levels 3 and 4.

    **This course uses named profiles.** If you ever ran `eval $(floci env)`, clear them:

    ```bash
    unset AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
          AWS_DEFAULT_REGION AWS_REGION
    ```

    Note that `AWS_PROFILE` is **not** in that list — `configs/course.env` sets it deliberately, and
    it selects a profile rather than overriding one.

---

### Step 12 — Create the `floci` AWS CLI profile

**Purpose**

Store the four values once, so you never type them again.

**Run from**

```text
aws-floci-course/
```

**Command**

```bash
aws configure set aws_access_key_id     test                  --profile floci
aws configure set aws_secret_access_key test                  --profile floci
aws configure set region                us-east-1             --profile floci
aws configure set output                json                  --profile floci
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
    into a command like this on a shared machine or in a script — your shell history file
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

`configs/course.env` already exports `AWS_PROFILE=floci`. Source it, and make new terminals do the
same automatically:

```bash
source configs/course.env
echo 'source ~/aws-floci-course/configs/course.env' >> ~/.bashrc
```

(Use `~/.zshrc` if your shell is zsh — Step 1 told you which.)

Now you can omit `--profile floci` from every command. This document still shows `--profile floci`
explicitly in the next two steps so you can see where it belongs, then relies on `AWS_PROFILE`.

**If your AWS CLI is older than 2.13**

```bash
aws configure get endpoint_url --profile floci
```

If that prints the URL but commands still try to reach `amazonaws.com` (you will test this in
Step 14), your CLI ignores the profile setting. Upgrade the CLI, or add this to `course.env`:

```bash
# ONLY if your AWS CLI predates 2.13 and ignores the profile's endpoint_url
export AWS_ENDPOINT_URL=http://localhost:4566
```

!!! question "**Your turn**"

    Run `aws configure list --profile floci`. Identify which column tells you *where* each value came
    from, and explain why the `Type` for the access key says `shared-credentials-file`.

---

### Step 13 — Your first AWS CLI command, and the `whoami` helper

**Purpose**

Ask the emulator "who am I?" — the single most useful diagnostic command in AWS — and wrap it in a
script you will run at the start of every lab.

**Run from**

```text
aws-floci-course/
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
- `Arn` — an Amazon Resource Name, explained fully in Step 16.

If you got `Could not connect to the endpoint URL`, Floci is not running: `./scripts/setup/floci-up.sh`.

**Now wrap it in a script**

```bash
cat > scripts/utilities/whoami.sh << 'EOF'
#!/usr/bin/env bash
# Print exactly which identity and endpoint the AWS CLI is currently using,
# and refuse to stay quiet if it is not Floci.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/configs/course.env"

echo "AWS_PROFILE         = ${AWS_PROFILE:-<unset>}"
echo "AWS_ENDPOINT_URL    = ${AWS_ENDPOINT_URL:-<unset, using profile>}"
echo "configured endpoint = $(aws configure get endpoint_url || echo '<none>')"
echo "configured region   = $(aws configure get region || echo '<none>')"
echo "---"
aws sts get-caller-identity --output table

acct="$(aws sts get-caller-identity --query Account --output text)"
if [ "$acct" = "$ACCOUNT_ID" ]; then
  printf '\033[1;32m[ok] Account %s — this is Floci, not real AWS.\033[0m\n' "$acct"
else
  printf '\033[1;31m[DANGER] Account %s is NOT the Floci account (%s).\033[0m\n' "$acct" "$ACCOUNT_ID"
  printf '\033[1;31mYou may be pointed at REAL AWS. Stop and re-check your profile.\033[0m\n'
  exit 1
fi
EOF

chmod +x scripts/utilities/whoami.sh
./scripts/utilities/whoami.sh
```

`${VAR:-default}` means "the value of VAR, or `default` if VAR is unset" — it prevents `set -u` from
killing the script when a variable legitimately does not exist.

**Expected result**

```text
AWS_PROFILE         = floci
AWS_ENDPOINT_URL    = <unset, using profile>
configured endpoint = http://localhost:4566
configured region   = us-east-1
---
-------------------------------------------------------------------------
|                          GetCallerIdentity                            |
+---------------+--------------------------------+----------------------+
|    Account    |              Arn               |       UserId         |
+---------------+--------------------------------+----------------------+
|  000000000000 | arn:aws:iam::000000000000:root |  AKIAIOSFODNN7EXAMPLE|
+---------------+--------------------------------+----------------------+
[ok] Account 000000000000 — this is Floci, not real AWS.
```

Note `--output table` — the same data as JSON, formatted for humans.

!!! success "**Checkpoint 4**"

  ```text
  AWS CLI  ──→  Floci  : working
  Account            : 000000000000
  whoami.sh          : written and passing
  ```

---

### Step 14 — Prove isolation from real AWS, and prove persistence

**Purpose**

Two different claims, two different proofs. Students routinely confuse them, and a passing test of
one tells you nothing about the other.

```text
ISOLATION   "my commands never reach real AWS"
PERSISTENCE "my data survives a restart"
```

**Run from**

```text
aws-floci-course/
```

#### 14.1 Isolation, Test 1 — the account number

Already done in Step 13: `000000000000` is not a real account.

#### 14.2 Isolation, Test 2 — inspect the actual URL the CLI used

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

#### 14.3 Isolation, Test 3 — stop the container

```bash
./scripts/setup/floci-down.sh
aws sts get-caller-identity --profile floci
```

**Expected result**

```text
Could not connect to the endpoint URL: "http://localhost:4566/"
```

If your commands were secretly reaching real AWS, stopping a local container could not possibly break
them. **Leave it stopped** — the persistence test starts from here.

#### 14.4 Persistence — the test that actually matters

The old version of this lab restarted Floci and observed that `get-caller-identity` still returned
the same root ARN. That proves **nothing**: the root identity is a constant, and it comes back
identically even in `memory` mode with no disk at all. A real persistence test has to create
something, restart, and look for it again.

```bash
# 1. Bring Floci back up
./scripts/setup/floci-up.sh

# 2. Create a marker resource
aws iam create-user --user-name persistence-check --output text --query 'User.Arn'

# 3. Restart the container — a full stop and start, not just a pause
docker compose restart floci
sleep 5
until curl -sf http://localhost:4566/_floci/health >/dev/null 2>&1; do sleep 2; done

# 4. Is it still there?
aws iam get-user --user-name persistence-check --query 'User.UserName' --output text
```

**Expected result**

```text
arn:aws:iam::000000000000:user/persistence-check
persistence-check
```

The second line is the whole point of Part A. If step 4 instead prints
`An error occurred (NoSuchEntity)`, your storage configuration is wrong — run
`./scripts/utilities/floci-storage-check.sh` (written in Step 15) and re-read Step 7.

**Look at the data on disk**

```bash
ls -la ~/floci-data
du -sh ~/floci-data
```

You should see real files and a non-zero size. An **empty** `~/floci-data` alongside a surviving user
means Floci is persisting somewhere else — also a misconfiguration.

**Clean up the marker**

```bash
aws iam delete-user --user-name persistence-check
```

#### 14.5 Exit codes

```bash
aws sts get-caller-identity --profile floci > /dev/null 2>&1
echo "exit code = $?"

aws iam get-user --user-name does-not-exist > /dev/null 2>&1
echo "exit code = $?"
```

**Expected result**

```text
exit code = 0
exit code = 254
```

`$?` holds the exit status of the last command: `0` = success, non-zero = failure. AWS CLI v2 uses
`254` for a service error such as `NoSuchEntity` and `255` for a client-side or connection error.
Scripts use this to decide whether to continue — the verification script in Section 9 is built on it.

!!! note "Floci Limitation — identity is not really authenticated"
    Real AWS verifies your signature cryptographically and rejects wrong credentials. Floci accepts
    any non-empty credentials by default, and reports you as the account `root` user. So
    `get-caller-identity` in Floci confirms **connectivity**, not **authentication**.

!!! success "**Checkpoint 5**"

    ```text
    Proof of isolation
    ├── Account is 000000000000        ✔
    ├── Request URL is localhost:4566  ✔
    └── Stopping Floci breaks the CLI  ✔

    Proof of persistence
    ├── A user created before a restart still existed after it   ✔
    └── ~/floci-data contains real files                          ✔
    ```

---

### Step 15 — Storage diagnostics, README, and commit Part A

**Purpose**

Write the tool you will reach for when persistence looks wrong, finish the project front page, and
commit a clean environment.

**Run from**

```text
aws-floci-course/
```

#### 15.1 `scripts/utilities/floci-storage-check.sh`

{% raw %}```bash
cat > scripts/utilities/floci-storage-check.sh << 'EOF'
#!/usr/bin/env bash
# Diagnose "my data disappeared" / "new Docker volumes keep appearing".
# Read-only. Destroys nothing. Paste its output into your lab report.
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/configs/course.env"

ok()   { printf '\033[1;32m  [ok]\033[0m   %s\n' "$*"; }
bad()  { printf '\033[1;31m  [FAIL]\033[0m %s\n' "$*"; }
note() { printf '         %s\n' "$*"; }
hdr()  { printf '\n\033[1;34m=== %s\033[0m\n' "$*"; }

envof() {
  docker container inspect "$FLOCI_CONTAINER_NAME" \
    --format '{{ range .Config.Env }}{{ println . }}{{ end }}' | sed -n "s/^$1=//p"
}

hdr "1. Container, and who created it"
if ! docker container inspect "$FLOCI_CONTAINER_NAME" >/dev/null 2>&1; then
  bad "No container named '$FLOCI_CONTAINER_NAME'. Run ./scripts/setup/floci-up.sh"
  exit 1
fi
note "status: $(docker container inspect "$FLOCI_CONTAINER_NAME" --format '{{.State.Status}}')"
proj="$(docker container inspect "$FLOCI_CONTAINER_NAME" \
        --format '{{ index .Config.Labels "com.docker.compose.project" }}')"
if [ "$proj" = "$FLOCI_COMPOSE_PROJECT" ]; then
  ok "Created by Compose project '$FLOCI_COMPOSE_PROJECT'."
else
  bad "NOT created by Compose (project label = '$proj')."
  note "This is a 'floci start' container. Fix: floci stop --remove && ./scripts/setup/floci-up.sh"
fi

hdr "2. Storage mode — the usual culprit"
mode="$(envof FLOCI_STORAGE_MODE)"; mode="${mode:-<unset>}"
if [ "$mode" = "memory" ] || [ "$mode" = "<unset>" ]; then
  bad "FLOCI_STORAGE_MODE=$mode"
  note "Floci defaults to 'memory'. Nothing survives a restart, and Floci deletes"
  note "its own volumes on teardown — hence 'a new volume every time'."
  note "Fix: FLOCI_STORAGE_MODE=hybrid in configs/course.env, then floci-up.sh"
else
  ok "FLOCI_STORAGE_MODE=$mode (durable)"
fi

hdr "3. Is /app/data a real host directory?"
m="$(docker container inspect "$FLOCI_CONTAINER_NAME" \
     --format '{{ range .Mounts }}{{ if eq .Destination "/app/data" }}{{ .Type }} {{ .Source }}{{ end }}{{ end }}')"
if [ -z "$m" ]; then
  bad "/app/data is not mounted — state dies with the container."
else
  set -- $m
  if [ "$1" = "bind" ]; then
    ok "bind mount -> $2"
    [ "$2" = "$FLOCI_HOST_DATA_DIR" ] || bad "...but that is NOT $FLOCI_HOST_DATA_DIR"
  else
    bad "/app/data is a Docker '$1', not your host directory."
    note "A literal '~' in the path is the usual cause; nothing expands it."
  fi
fi

hdr "4. Sidecar storage (RDS / OpenSearch / MSK / ECR)"
hp="$(envof FLOCI_STORAGE_HOST_PERSISTENT_PATH)"
if [ -z "$hp" ]; then
  bad "FLOCI_STORAGE_HOST_PERSISTENT_PATH is unset — sidecars use anonymous volumes."
elif [ "${hp#/}" = "$hp" ]; then
  bad "FLOCI_STORAGE_HOST_PERSISTENT_PATH='$hp' is not absolute. Floci rejects it."
else
  ok "FLOCI_STORAGE_HOST_PERSISTENT_PATH=$hp"
fi

hdr "5. Floci-managed volumes on this machine"
vols="$(docker volume ls -q --filter label=floci=true || true)"
if [ -z "$vols" ]; then
  note "(none — expected while everything is bind-mounted)"
else
  printf '%s\n' "$vols" | sed 's/^/         /'
  note "Count: $(printf '%s\n' "$vols" | wc -l | tr -d ' ')"
  note "Growing on every restart? Storage mode is still wrong."
fi

hdr "6. Host state directory"
if [ -d "$FLOCI_HOST_DATA_DIR" ]; then
  ok "$FLOCI_HOST_DATA_DIR exists (size: $(du -sh "$FLOCI_HOST_DATA_DIR" 2>/dev/null | cut -f1))"
  ls -1 "$FLOCI_HOST_DATA_DIR" 2>/dev/null | head -20 | sed 's/^/           /'
  [ -n "$(ls -A "$FLOCI_HOST_DATA_DIR" 2>/dev/null)" ] || bad "Directory is EMPTY — see checks 2 and 3."
else
  bad "$FLOCI_HOST_DATA_DIR does not exist."
fi
printf '\n'
EOF

chmod +x scripts/utilities/floci-storage-check.sh
./scripts/utilities/floci-storage-check.sh
```{% endraw %}

**Expected result** — six sections, all `[ok]`, with section 5 reporting no dangling volumes.

Keep this output. It is good evidence for your lab report, and it is the first thing to run in
Section 11 troubleshooting.

#### 15.2 A cleanup script for stray volumes

If you experimented with `floci start` before reading Step 7, you may have orphaned volumes. This
removes only volumes labelled `floci=true` that no container is using.

```bash
cat > scripts/cleanup/floci-prune-volumes.sh << 'EOF'
#!/usr/bin/env bash
# DESTRUCTIVE. Removes dangling Docker volumes labelled floci=true.
# Your bind-mounted state in $FLOCI_HOST_DATA_DIR is NOT touched.
#   dry run : ./scripts/cleanup/floci-prune-volumes.sh
#   delete  : ./scripts/cleanup/floci-prune-volumes.sh --yes
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/configs/course.env"
CONFIRM="${1:-}"

vols="$(docker volume ls -q --filter label=floci=true --filter dangling=true || true)"
if [ -z "$vols" ]; then
  printf '\033[1;32m[ok]\033[0m No dangling floci volumes.\n'; exit 0
fi

count="$(printf '%s\n' "$vols" | wc -l | tr -d ' ')"
printf '\033[1;33m[!]\033[0m %s dangling volume(s) labelled floci=true:\n' "$count"
printf '%s\n' "$vols" | sed 's/^/    /'

if [ "$CONFIRM" != "--yes" ]; then
  printf '\nDry run. Re-run with --yes to delete these.\n'
  printf 'Your lab state in %s is unaffected either way.\n' "$FLOCI_HOST_DATA_DIR"
  exit 0
fi

printf '%s\n' "$vols" | xargs -r docker volume rm
printf '\033[1;32m[ok]\033[0m Removed %s volume(s).\n' "$count"
EOF

chmod +x scripts/cleanup/floci-prune-volumes.sh
./scripts/cleanup/floci-prune-volumes.sh
```

#### 15.3 `README.md`

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

## Daily workflow

```bash
./scripts/setup/floci-up.sh      # start or resume (idempotent)
# ... lab work ...
./scripts/setup/floci-down.sh    # pause; state is kept
```

## Never run these

| Command | Why |
|---|---|
| `docker compose down -v` | `-v` deletes volumes |
| `docker volume prune` | Unfiltered; use scripts/cleanup/floci-prune-volumes.sh |
| `floci start ...` | Bypasses Compose; disables persistence |
| `rm -rf ~/floci-data` | That directory is the IAM state |

## Labs

| Lab | Topic | Status |
|-----|-------|--------|
| 01  | IAM   | [x] complete |
| 02  | VPC   | [ ] not started |

## Conventions

- All resources are prefixed `usms-`
- Region: `us-east-1`  ·  Floci account: `000000000000`
- Storage mode: `hybrid`, bind-mounted to `~/floci-data`
- Secrets live in `outputs/` and are **never** committed
EOF
````

#### 15.4 Commit Part A

```bash
git status --short
```

Confirm that **no file under `outputs/`** and **no `.env`** appears. Then:

```bash
git add .
git commit -q -m "feat(lab-01): environment bootstrap with durable Floci storage

Floci is pinned by docker-compose.yml with FLOCI_STORAGE_MODE=hybrid and an
absolute host bind mount, because 'floci start --persist' does not enable a
durable storage mode and its flags are not remembered across restarts."
git log --oneline
```

!!! success "**Checkpoint 6 — end of Part A**"

    ```text
    Environment
    ├── Docker + Compose v2  : running
    ├── Floci                : Compose-managed, hybrid storage, port 4566
    ├── Persistence          : PROVEN by create → restart → read
    ├── AWS CLI v2           : installed
    ├── Profile "floci"      : configured with endpoint_url
    ├── Isolation            : proven three ways
    └── ~/aws-floci-course   : README, .gitignore (correct negation),
                                docker-compose.yml, course.env,
                                floci-up.sh, floci-down.sh, whoami.sh,
                                floci-storage-check.sh, committed to Git
    ```

---
## PART B — Building the IAM Foundation (Steps 16–33)

Everything below assumes Part A is complete and verified. If you skipped Step 14's persistence
proof, go back and do it — otherwise you may be about to build an IAM foundation that evaporates.

---

### Step 16 — IAM concepts and the anatomy of an ARN

**Purpose**

Understand the vocabulary before typing commands. Five minutes here saves an hour of confusion later.

#### 16.1 The four IAM building blocks

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

#### 16.2 Two kinds of policy — the distinction students most often miss

| | **Permissions policy** | **Trust policy** |
| --- | --- | --- |
| Answers | "What may this identity **do**?" | "**Who** may become this role?" |
| Attached to | users, groups, roles | roles only (exactly one) |
| Key element | `Action` + `Resource` | `Principal` + `sts:AssumeRole` |
| CLI flag | `--policy-document` on `create-policy` | `--assume-role-policy-document` on `create-role` |

Every role needs **both**. Forgetting the trust policy is why a role "exists but nobody can use it".

#### 16.3 Three ways a policy can be attached

| Type | Lives where | Reusable? | Use when |
| --- | --- | --- | --- |
| **AWS managed** | Created and maintained by AWS | Yes, by everyone | Common broad cases (`ReadOnlyAccess`) |
| **Customer managed** | Created by you, standalone object with its own ARN and versions | Yes, attach to many identities | **Default choice.** Your organisation's rules |
| **Inline** | Embedded inside one user/group/role; dies with it | No | A one-off permission that must never be reused |

#### 16.4 Anatomy of an ARN

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
    A policy that lists only the first will fail every `GetObject` call. You will write both in
    Step 23.

#### 16.5 Anatomy of a policy document

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

#### 16.6 How AWS decides: policy evaluation logic

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
    an `AccessDenied` in Floci simply because a policy was too narrow. Step 32 shows the
    policy *simulator* as the closest available substitute, and Section 12 lists exactly which parts
    of this lab are "conceptual / real AWS" rather than "enforced by Floci".

    Write every policy as if it *were* enforced. In a real account it will be.

---

### Step 17 — Inspect the empty IAM account

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

(If you see `persistence-check` here, you skipped the cleanup at the end of Step 14. Run
`aws iam delete-user --user-name persistence-check` now.)

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

!!! question "**Your turn**"

    Run `aws iam list-roles --output table`. Floci may pre-create some service-linked roles.
    Are the results the same in `text` format? Which one would you use inside a script, and why?

---

### Step 18 — Create the IAM groups

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
------------------------------------------------------------------------
|                              ListGroups                              |
+-------------------+--------------------------------------------------+
|  usms-admins      |  arn:aws:iam::000000000000:group/usms-admins     |
|  usms-auditors    |  arn:aws:iam::000000000000:group/usms-auditors   |
|  usms-developers  |  arn:aws:iam::000000000000:group/usms-developers |
+-------------------+--------------------------------------------------+
```

!!! success "**Checkpoint 7**"

    ```text
    IAM Groups
    ├── usms-admins      (0 members, 0 policies)
    ├── usms-developers  (0 members, 0 policies)
    └── usms-auditors    (0 members, 0 policies)
    ```

---

### Step 19 — Create the IAM users and capture their ARNs

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
    If you close this terminal, `$DEV_ARN` is gone. That is why Step 33 writes these values to
    `configs/lab-01.env` — a file that survives, and that Lab 2 will simply `source`.

    Note the difference from Part A: your *IAM users* now survive a restart (you proved that in
    Step 14), but your *shell variables* never will. Two different kinds of impermanence.

**Verify**

```bash
aws iam list-users \
  --query 'Users[*].{User:UserName,Created:CreateDate,Arn:Arn}' \
  --output table
```

`{Name:Field}` in JMESPath builds an object with **renamed keys** — which become the table's column
headers. Compare this to Step 18's `[Field1,Field2]`, which produced an unlabelled list.

**Inspect a single user and its tags**

```bash
aws iam get-user --user-name usms-dev-01
aws iam list-user-tags --user-name usms-dev-01 --output table
```

!!!question  "**Your turn**"

    Create a fourth user `usms-intern-01`, tagged `Key=Role,Value=Intern`, capturing its ARN into a
    variable named `INTERN_ARN`. Then display **only** the `UserId` of that user using `get-user` and
    `--query`.

    ```text
    Expected result:
    An ARN ending in :user/usms-intern-01, and a UserId string starting with AIDA...
    ```

---

### Step 20 — Add users to groups

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

!!! question "**Your turn**"

    Put `usms-intern-01` (from Step 19) into `usms-auditors`, then verify with a **single** command that
    the auditors group now has two members.

---

### Step 21 — Explore and attach an AWS managed policy

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
    attach below fails with `NoSuchEntity`. That is expected — use the workaround and continue;
    nothing later in this lab depends on which of the two you used.

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
-----------------------------------------------------------------------
|                     ListAttachedGroupPolicies                       |
+------------------------------------------+--------------------------+
|                PolicyArn                 |        PolicyName        |
+------------------------------------------+--------------------------+
|  arn:aws:iam::aws:policy/ReadOnlyAccess  |  ReadOnlyAccess          |
+------------------------------------------+--------------------------+
```

---

### Step 22 — Write your first customer managed policy

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

`AttachmentCount: 2` confirms both attachments. `DefaultVersionId: v1` becomes interesting in Step 27.

!!! success "**Checkpoint 8**"

    ```text
    IAM
    ├── usms-admins      ← USMSDeveloperBase
    ├── usms-developers  ← USMSDeveloperBase
    └── usms-auditors    ← ReadOnlyAccess (or USMSReadOnly)
    ```

---

### Step 23 — Write the S3 data policy (used for real in Lab 4)

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

### Step 24 — Use `--generate-cli-skeleton` to discover parameters

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
accepts, **without calling AWS at all**. It is documentation you can fill in. (Because it never
contacts the endpoint, this is also the one command in this lab that works with Floci stopped — a
useful thing to remember.)

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

!!! question "**Your turn**"

    Generate a skeleton for `aws iam create-policy` and for `aws ec2 create-vpc` (you will need the
    latter in Lab 2). Save both in `templates/`. Which parameter of `create-vpc` looks like the most
    important one?

---

### Step 25 — Add an inline policy (self-service credentials)

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

    Every policy heredoc in this lab uses the quoted form. The one place we deliberately use the
    *unquoted* form is Step 33, where expansion is exactly what we want.

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

### Step 26 — Inspect what you have built

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
echo "=== groups ===";      aws iam list-groups-for-user       --user-name $IAM_USER --query 'Groups[*].GroupName'                --output text
echo "=== attached ===";    aws iam list-attached-user-policies --user-name $IAM_USER --query 'AttachedPolicies[*].PolicyName'    --output text
echo "=== inline ===";      aws iam list-user-policies          --user-name $IAM_USER --query 'PolicyNames'                       --output text
echo "=== access keys ==="; aws iam list-access-keys            --user-name $IAM_USER --query 'AccessKeyMetadata[*].AccessKeyId'  --output text
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
the basis of most IAM audit tooling. We store it in `outputs/` — which you proved in Step 6 is
git-ignored.

**D. Optional: pretty-query it with `jq`**

```bash
sudo apt install -y jq        # or: brew install jq
jq '.UserDetailList[] | {UserName, Groups: .GroupList}' \
   ~/aws-floci-course/outputs/lab-01-iam-snapshot.json
```

`jq` is a dedicated JSON processor. `--query` runs **on the CLI's side of the response**; `jq` runs on
files you already have. Both are worth knowing. You will need `jq` again in Steps 30 and 31, so
install it now if you have not.

!!! success "**Checkpoint 9**"

    ```text
    Identity layer complete
    ├── 3 groups, each with policies
    ├── 3 users, each in a group
    ├── 1 inline policy on usms-dev-01
    └── full account snapshot saved to outputs/
    ```

---
### Step 27 — Policy versions

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

### Step 28 — Create a role for EC2, with a trust policy

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

!!! success "**Checkpoint 10**"

    ```text
    usms-ec2-app-role
    ├── trust      : ec2.amazonaws.com
    ├── permissions: USMSStudentDataReadWrite
    └── wrapped in : usms-ec2-app-profile   ← Lab 03 attaches this to the instance
    ```

---

### Step 29 — Create the Lambda execution role

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

``[?starts_with(RoleName, `usms-`)]`` is a **filter expression**: keep only elements where the test is
true. The backticks are JMESPath's way of writing a literal string. This is how you find your own
resources in an account full of other people's — and it is why the `usms-` naming convention matters.

---

### Step 30 — A role for humans, and temporary credentials with STS

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

#### 30.1 Create the role with an account-principal trust policy

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

#### 30.2 Give the developers group permission to assume it

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

#### 30.3 Assume the role

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

Four things to notice:

1. There are **three** values, not two — temporary credentials always include a `SessionToken`.
2. The access key starts with `ASIA`, not `AKIA`. `ASIA` = temporary, `AKIA` = permanent. You can tell
   at a glance what kind of credential you are looking at.
3. `Expiration` is one hour away. After that they simply stop working.
4. The resulting ARN is an `sts::...:assumed-role/...` ARN carrying your session name — which is what
   makes audit logs traceable back to a person.

#### 30.4 Use the temporary credentials, then put your identity back

This is the one place in the course where we deliberately use environment variables instead of a
profile — because that is how assumed-role credentials are normally injected. Note what it costs us:
environment credentials sit at level 2 of the resolution order from Step 11, so they **bypass the
profile entirely**, taking the profile's `endpoint_url` with them. We have to supply it by hand.

```bash
cd ~/aws-floci-course

export AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId'         outputs/assumed-role.json)
export AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' outputs/assumed-role.json)
export AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken'        outputs/assumed-role.json)

aws sts get-caller-identity --endpoint-url http://localhost:4566 --region us-east-1
```

**Return to your normal identity — do this before continuing**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
```

`whoami.sh` should report account `000000000000` and the `root` ARN again. If it still shows the
assumed-role ARN, the `unset` did not run — check for a typo and repeat it.

!!! note "Floci Limitation — assume-role always succeeds"
    Because Floci does not authorize requests against IAM policies by default, `sts:AssumeRole` will
    succeed even if you *remove* the trust policy or the user's permission. The credentials returned
    are also not enforced afterwards. Treat this step as learning the **mechanics and the ARNs** —
    the enforcement half is real-AWS behaviour you must reason about, not observe here.

!!! success "**Checkpoint 11**"

    ```text
    Roles
    ├── usms-ec2-app-role     (trust: ec2.amazonaws.com)      + instance profile
    ├── usms-lambda-exec-role (trust: lambda.amazonaws.com)
    └── usms-developer-role   (trust: usms-dev-01)  ← assumed, temp creds obtained
    ```

---

### Step 31 — Access keys, handled safely

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
    The next command creates a secret access key. In a real account:

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

- Output is redirected straight to a file in `outputs/` — so the secret never appears on screen, in
  your scrollback, or in a screenshot you might submit.
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

You already proved this with a fake file in Step 6. Now prove it with the real one:

```bash
git status --porcelain
git check-ignore -v outputs/usms-dev-01-access-key.json
ls -l outputs/usms-dev-01-access-key.json
```

**Expected result**

```text
.gitignore:24:*-access-key.json	outputs/usms-dev-01-access-key.json
-rw-------  1 student  student  253 Aug 10 10:02 outputs/usms-dev-01-access-key.json
```

Three separate confirmations: the key is absent from `git status`, `git check-ignore` names the exact
rule and line that blocked it, and the file permissions are `600`.

Note which rule fired. In Step 6 the fake file matched `outputs/*` on line 8; this real key matches
`*-access-key.json` on line 24 instead, because **Git reports the last matching pattern**, not the
first. Two independent rules cover this file — that redundancy is deliberate, so that a key saved to
the wrong directory by mistake is still caught.

!!! danger "If `git check-ignore` prints nothing and exits non-zero"
    Nothing is ignoring that file, and your next `git add .` will stage a credential. Stop, fix
    `.gitignore` per Step 6 (`outputs/*`, not `outputs/`), and re-check before doing anything else.

**Create a second profile that uses this key**

```bash
KEY_ID=$(jq -r '.AccessKey.AccessKeyId'         outputs/usms-dev-01-access-key.json)
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

### Step 32 — Test permissions with the policy simulator

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

!!! question "**Your turn**"

    Predict — before running anything — the decision for `usms-audit-01` on `ec2:CreateVpc` and on
    `ec2:DescribeVpcs`. Write your prediction in `notes/lab-01-notes.md`, then check it. If Floci does not
    support the simulator, justify your prediction by quoting the relevant statement from the policy JSON.


### Step 33 — Save the lab state for future labs

**Purpose**

Write down every ARN Lab 2 and beyond will need, snapshot the emulator, and commit.

**Run from**

```text
aws-floci-course/
```

#### 33.1 Generate `configs/lab-01.env`

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
export USMS_POLICY_LAMBDA=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSLambdaBasic'].Arn | [0]" --output text)

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
`$(date ...)` and `$(aws ...)` substitutions and bake the real ARNs into the file. Compare with the
policy files in Steps 22–30, which used `<< 'EOF'` precisely to prevent expansion. Choosing the right
one is a real skill.

`Policies[?PolicyName=='X'].Arn | [0]` is a JMESPath filter piped to `[0]` to take the first (only)
match, so the variable holds a single string rather than a list.

**Check every value was filled in**

```bash
grep -n 'export .*=$\|None' configs/lab-01.env || echo "all values populated"
```

An empty value or the string `None` means the matching resource does not exist — go back and create
it before continuing, otherwise Lab 2 will fail with a confusing error.

**Verify — the whole thing works from a fresh shell**

```bash
source configs/course.env
source configs/lab-01.env
echo "EC2 role  : $USMS_ROLE_EC2"
echo "Dev policy: $USMS_POLICY_DEV_BASE"
```

#### 33.2 Take a snapshot

A snapshot captures the emulator's entire state. If you break something in Lab 3, you can return to
this exact point instead of redoing Lab 1.

```bash
floci snapshot save lab-01-iam-complete
floci snapshot list
```

**If `floci snapshot` is unsupported on your build**, take a filesystem snapshot instead. This works
on every version, because Part A put all state in one directory:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-01.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-01.tar.gz
```

**Stop Floci first.** Archiving a live data directory can capture a half-written file. To restore
later: stop Floci, `rm -rf ~/floci-data`, `tar -xzf ~/floci-data-lab-01.tar.gz -C ~`, start again.

(Keep the archive outside the repository — `~`, not `~/aws-floci-course` — so it is never a candidate
for commit.)

#### 33.3 Write your lab notes

```bash
cat > labs/lab-01-iam/README.md << 'EOF'
# Lab 01 — IAM — completed

## What exists after this lab
- Environment: Floci via docker-compose.yml, FLOCI_STORAGE_MODE=hybrid,
  bind-mounted to ~/floci-data, persistence proven in Step 14
- Groups: usms-admins, usms-developers, usms-auditors
- Users: usms-admin-01, usms-dev-01, usms-audit-01
- Customer managed policies: USMSDeveloperBase (v2), USMSStudentDataReadWrite,
  USMSAssumeAppRoles, USMSLambdaBasic
- Inline policy: USMSSelfManageCredentials on usms-dev-01
- Roles: usms-ec2-app-role, usms-lambda-exec-role, usms-developer-role
- Instance profile: usms-ec2-app-profile

## Reproduce
    source ~/aws-floci-course/configs/course.env
    ./scripts/setup/floci-up.sh
    source ~/aws-floci-course/configs/lab-01.env
    ./scripts/utilities/verify-lab-01.sh

## Evidence
- [ ] whoami.sh output showing account 000000000000
- [ ] floci-storage-check.sh output, all [ok]
- [ ] Step 14 persistence proof (user survived a restart)
- [ ] verify-lab-01.sh with FAIL=0

## Problems I hit and how I fixed them
(fill this in — it is graded)
EOF
```

#### 33.4 Commit your work

```bash
git status --short
```

Read that output and confirm **no file from `outputs/` and no `.env` is listed**. Then:

```bash
git add .
git commit -q -m "feat(lab-01): IAM foundation for USMS (users, groups, policies, roles)"
git log --oneline
```

**Expected result** — three commits, in the order that matters:

```text
c3d4e5f feat(lab-01): IAM foundation for USMS (users, groups, policies, roles)
b2c3d4e feat(lab-01): environment bootstrap with durable Floci storage
a1b2c3d chore: ignore secrets before the repo can hold any
```

The oldest commit is the `.gitignore`. That ordering is not cosmetic — it is the proof that no secret
could ever have been committed.

!!! success "**Checkpoint 12 — end of Part B**"

    ```text
    IAM foundation complete and recorded
    ├── configs/lab-01.env written with all ARNs, every value populated
    ├── snapshot "lab-01-iam-complete" saved (or ~/floci-data-lab-01.tar.gz)
    ├── Lab notes written
    └── Work committed to Git, with .gitignore as the first commit
    ```

---
## 5. Verification

Run this end-to-end verification script. It checks every artefact this lab was supposed to produce —
including the environment settings that make the IAM work survive.

**Run from**

```text
aws-floci-course/
```

{% raw %}```bash
cd ~/aws-floci-course

cat > scripts/utilities/verify-lab-01.sh << 'EOF'
#!/usr/bin/env bash
# Verify every Lab 01 artefact exists. Exit 1 if anything is missing.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
source "$REPO_ROOT/configs/course.env"

PASS=0; FAIL=0
check() {
  if eval "$2" >/dev/null 2>&1; then
    printf "  ✔ %s\n" "$1"; PASS=$((PASS+1))
  else
    printf "  ✗ %s\n" "$1"; FAIL=$((FAIL+1))
  fi
}

echo "== Environment =="
check "Docker daemon reachable"   "docker info"
check "Compose v2 present"        "docker compose version"
check "Floci container running"   "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{.State.Running}}')\" = true"
check "Container owned by Compose" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{ index .Config.Labels \"com.docker.compose.project\" }}')\" = $FLOCI_COMPOSE_PROJECT"
check "Health endpoint responds"  "curl -sf http://localhost:4566/_floci/health"
check "AWS CLI reaches Floci"     "aws sts get-caller-identity"
check "Account is 000000000000" \
  "test \"\$(aws sts get-caller-identity --query Account --output text)\" = $ACCOUNT_ID"

echo "== Persistence configuration =="
check "Storage mode is NOT memory" \
  "docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -qE '^FLOCI_STORAGE_MODE=(hybrid|persistent|wal)$'"
check "/app/data is a host bind mount" \
  "test \"\$(docker container inspect $FLOCI_CONTAINER_NAME --format '{{range .Mounts}}{{if eq .Destination \"/app/data\"}}{{.Type}}{{end}}{{end}}')\" = bind"
check "state directory is non-empty" "test -n \"\$(ls -A $FLOCI_HOST_DATA_DIR 2>/dev/null)\""

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
check "USMSDeveloperBase default version is v2" \
  "test \"\$(aws iam get-policy --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/USMSDeveloperBase --query 'Policy.DefaultVersionId' --output text)\" = v2"
check "inline policy on usms-dev-01" \
  "aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials"

echo "== Roles =="
for r in usms-ec2-app-role usms-lambda-exec-role usms-developer-role; do
  check "role $r" "aws iam get-role --role-name $r"
done
check "instance profile has the role" \
  "aws iam get-instance-profile --instance-profile-name usms-ec2-app-profile --query 'InstanceProfile.Roles[0].RoleName' --output text | grep -q usms-ec2-app-role"

echo "== Files and Git hygiene =="
check "configs/course.env"    "test -f configs/course.env"
check "configs/lab-01.env"    "test -f configs/lab-01.env"
check "docker-compose.yml"    "test -f docker-compose.yml"
check "outputs/.gitkeep IS tracked" "git ls-files --error-unmatch outputs/.gitkeep"
check "access key file is IGNORED"  "git check-ignore -q outputs/usms-dev-01-access-key.json"
check ".env is IGNORED"             "git check-ignore -q .env"
check "no secret is staged or tracked" \
  "! git ls-files | grep -q '^outputs/usms-dev-01-access-key.json$'"

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
EOF

chmod +x scripts/utilities/verify-lab-01.sh
./scripts/utilities/verify-lab-01.sh
```{% endraw %}

**Expected result**

```text
== Environment ==
  ✔ Docker daemon reachable
  ✔ Compose v2 present
  ✔ Floci container running
  ✔ Container owned by Compose
  ✔ Health endpoint responds
  ✔ AWS CLI reaches Floci
  ✔ Account is 000000000000
== Persistence configuration ==
  ✔ Storage mode is NOT memory
  ✔ /app/data is a host bind mount
  ✔ state directory is non-empty
...
PASS=34  FAIL=0
```

If anything fails, the label tells you exactly which step to redo. The two checks worth reading
carefully are **`outputs/.gitkeep IS tracked`** (proves the `.gitignore` negation from Step 6 works)
and **`access key file is IGNORED`** (proves the secret is safe). One passing without the other means
your ignore rules are subtly wrong.

Commit the verification script:

```bash
git add scripts/utilities/verify-lab-01.sh
git commit -q -m "test(lab-01): end-to-end verification script"
```

---

## 6. Checkpoints

A consolidated list. Tick each one before moving to Lab 2.

| # | Checkpoint | Verify with |
| --- | --- | --- |
| 1 | Docker + Compose v2 running | `docker info` · `docker compose version` |
| 2 | Git repo initialised, `.gitignore` committed first | `git log --oneline` |
| 3 | Floci running via Compose, hybrid storage, port 4566 | `docker compose ps` · `floci status` |
| 4 | AWS CLI reaches Floci, account `000000000000` | `./scripts/utilities/whoami.sh` |
| 5 | Isolation **and** persistence both proven | `--debug` URL · create → restart → read |
| 6 | Project structure + README + scripts, Part A committed | `find . -type d` · `git log` |
| 7 | 3 groups created | `aws iam list-groups` |
| 8 | Policies attached to groups | `aws iam list-attached-group-policies` |
| 9 | Users created, in groups, inline policy set | `verify-lab-01.sh` |
| 10 | EC2 role + instance profile | `aws iam get-instance-profile` |
| 11 | 3 roles, temp credentials obtained via STS | `outputs/assumed-role.json` |
| 12 | `configs/lab-01.env` written, snapshot saved, Git clean | `floci snapshot list` |

---

## 7. Troubleshooting

Each entry follows: **Problem → Cause → Diagnose → Fix → Verify**.

!!! tip "Start here"
    For anything involving missing data or unexpected Docker volumes, run
    `./scripts/utilities/floci-storage-check.sh` first. It performs six checks and names the cause
    directly, which is faster than working through this list.

### 7.1 `floci: command not found`

- **Cause** — the binary is not in your `PATH`.
- **Diagnose** — `ls ~/.local/bin/floci` or `which floci`.
- **Fix** —
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  ```
- **Verify** — `floci version`.

### 7.2 `Cannot connect to the Docker daemon`

- **Cause** — Docker Desktop is not started, or your user is not in the `docker` group.
- **Diagnose** — `docker info` (fails), `groups | grep docker` (empty).
- **Fix** — start Docker Desktop; on Linux:
  ```bash
  sudo systemctl start docker
  sudo usermod -aG docker $USER && newgrp docker
  ```
- **Verify** — `docker run --rm hello-world`.

### 7.3 `docker compose: 'compose' is not a docker command`

- **Cause** — Compose v2 plugin missing. `docker-compose` (with a hyphen) is the retired v1.
- **Diagnose** — `docker compose version` fails while `docker --version` works.
- **Fix** — `sudo apt-get install -y docker-compose-plugin`, or update Docker Desktop.
- **Verify** — `docker compose version` prints `v2.x`.

### 7.4 `required variable FLOCI_HOST_DATA_DIR is missing a value`

- **Cause** — you ran `docker compose` directly instead of the start script, so `.env` was never
  generated. This is the `:?` guard in `docker-compose.yml` working exactly as designed.
- **Fix** — `./scripts/setup/floci-up.sh`.
- **Verify** — `cat .env` shows an absolute path, and `docker compose config` succeeds.

### 7.5 `Refusing to continue` — a container named `floci` Compose did not create

- **Cause** — you (or an earlier attempt at this lab) ran `floci start`. That container has no
  durable storage, and adopting it would lose data.
- **Diagnose** —
  ```bash
{% raw %}  docker container inspect floci --format '{{ index .Config.Labels "com.docker.compose.project" }}'{% endraw %}
  ```
  Empty output means Compose did not create it.
- **Fix** —
  ```bash
  floci stop --remove        # or: docker rm -f floci
  ./scripts/setup/floci-up.sh
  ```
- **Verify** — the script reaches `Verified /app/data -> ...`.

### 7.6 `Bind for 0.0.0.0:4566 failed: port is already allocated`

- **Cause** — something else holds the port: an old Floci container, LocalStack, or another student's
  process on a shared machine.
- **Diagnose** —
  ```bash
  docker ps --filter publish=4566
  sudo lsof -i :4566
  ```
- **Fix** — stop the other container, or change **both** the `ports:` line in `docker-compose.yml`
  and `FLOCI_ENDPOINT` in `configs/course.env`, then update the profile:
  ```bash
  aws configure set endpoint_url http://localhost:4599 --profile floci
  ```
- **Verify** — `./scripts/setup/floci-up.sh` completes.

### 7.7 `Could not connect to the endpoint URL: "http://localhost:4566/"`

- **Cause** — Floci is not running, crashed, or is on a different port.
- **Diagnose** —
  ```bash
  docker compose ps
  docker compose logs --tail 50 floci
  curl -sv http://localhost:4566 2>&1 | head -5
  ```
- **Fix** — `./scripts/setup/floci-up.sh`.
- **Verify** — `aws sts get-caller-identity`.

### 7.8 Commands hang, then fail with a timeout — and the URL says `amazonaws.com`

- **Cause** — `endpoint_url` is missing or your AWS CLI is older than 2.13 and ignores it. The CLI is
  trying to reach **real AWS**.
- **Diagnose** —
  ```bash
  aws --version
  aws configure get endpoint_url --profile floci      # should print the localhost URL
  aws sts get-caller-identity --debug 2>&1 | grep -m1 "'url'"
  ```
- **Fix** — upgrade to AWS CLI 2.13+, or set the profile value again, or fall back to the
  environment variable:
  ```bash
  aws configure set endpoint_url http://localhost:4566 --profile floci
  # last resort, if your CLI ignores the profile setting:
  export AWS_ENDPOINT_URL=http://localhost:4566
  ```
- **Verify** — the debug line now shows `localhost:4566`.

### 7.9 `Unable to locate credentials`

- **Cause** — no profile, wrong profile name, or `AWS_PROFILE` points at a profile that does not exist.
- **Diagnose** —
  ```bash
  echo "AWS_PROFILE=$AWS_PROFILE"
  aws configure list-profiles
  aws configure list --profile floci
  ```
- **Fix** — redo Step 12, or `source configs/course.env`.
- **Verify** — `./scripts/utilities/whoami.sh`.

### 7.10 `The config profile (floci) could not be found`

- **Cause** — the section header in `~/.aws/config` is `[floci]` instead of `[profile floci]`.
- **Diagnose** — `cat ~/.aws/config`.
- **Fix** — always use `aws configure set ... --profile floci` rather than editing by hand; it writes
  the correct headers. If editing manually: `~/.aws/config` needs `[profile NAME]`,
  `~/.aws/credentials` needs `[NAME]`.
- **Verify** — `aws configure list --profile floci`.

### 7.11 `MalformedPolicyDocument` / `Invalid JSON`

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

### 7.12 `EntityAlreadyExists`

- **Cause** — you ran a `create-*` command twice.
- **Diagnose** — `aws iam get-user --user-name usms-dev-01` (it exists).
- **Fix** — this is usually harmless: the resource you wanted is already there. Continue. If you truly
  need to recreate it, delete first (see 11.16 for the dependency order).
- **Verify** — `aws iam list-users`.

### 7.13 `NoSuchEntity`

- **Cause** — a typo in a name or ARN, or the resource was never created, or **the resource was lost
  in a restart** (see 11.17).
- **Diagnose** —
  ```bash
  aws iam list-policies --scope Local --query 'Policies[*].PolicyName' --output text
  aws iam list-roles --query 'Roles[*].RoleName' --output text
  ```
- **Fix** — correct the name. Watch for: `usms-developers` (plural) vs `usms-developer-role`
  (singular), and account `000000000000` (twelve zeros — count them).
- **Verify** — re-run the failing command.

### 7.14 `${aws:username}` came out empty in the policy file

- **Cause** — you used `<< EOF` instead of `<< 'EOF'`, so **your shell** expanded it.
- **Diagnose** — `grep 'aws:username' policies/usms-self-manage-credentials.json`. No match = expanded.
- **Fix** — rewrite the file using `<< 'EOF'` (quoted), then re-run `put-user-policy` — "put"
  overwrites, so no deletion is needed.
- **Verify** — `aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials`
  and confirm the variable is present in the document.

### 7.15 `AccessDenied` on `sts:AssumeRole`

- **Cause** — only one half of the handshake is in place.
- **Diagnose** —
  ```bash
  # half 1: does the role trust the caller?
  aws iam get-role --role-name usms-developer-role \
    --query 'Role.AssumeRolePolicyDocument'
  # half 2: may the caller call AssumeRole?
  aws iam list-attached-group-policies --group-name usms-developers
  ```
- **Fix** — add the missing side (Step 30.1 or 30.2).
- **Verify** — `aws sts assume-role ...` returns credentials.
- **Note** — in Floci this error is unlikely to appear at all, because policies are not enforced by
  default. Learn the diagnosis anyway; you will need it on real AWS.

### 7.16 `DeleteConflict` when deleting an IAM entity

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

### 7.17 Floci lost all my resources after a restart

This is the failure this revision of the lab exists to prevent. There are three distinct causes and
they need different fixes.

- **Diagnose first** —
  ```bash
  ./scripts/utilities/floci-storage-check.sh
  ```
- **Cause A — storage mode is `memory`.** Section 2 of the check reports it. Floci's default. In this
  mode nothing survives, and Floci deletes its own volumes on teardown, which is why unfamiliar
  volumes keep appearing.
  **Fix:** `FLOCI_STORAGE_MODE="hybrid"` in `configs/course.env`, then `./scripts/setup/floci-up.sh`.
- **Cause B — `/app/data` is not a host bind mount, or is bound to the wrong path.** Section 3 reports
  it. A literal `~` in a path is the usual culprit: nothing expands it, so Docker creates a directory
  actually named `~`.
  **Fix:** make sure `FLOCI_HOST_DATA_DIR` is absolute, then re-run the start script.
  Check for the stray directory with `ls -la ~/aws-floci-course` and remove it if present.
- **Cause C — the container was started by `floci start`, not Compose.** Section 1 reports it. Its
  flags were not remembered.
  **Fix:** `floci stop --remove && ./scripts/setup/floci-up.sh`.
- **Recover the data** — if you took a snapshot in Step 33:
  ```bash
  floci snapshot load lab-01-iam-complete
  # or, for the tar fallback:
  ./scripts/setup/floci-down.sh
  rm -rf ~/floci-data && tar -xzf ~/floci-data-lab-01.tar.gz -C ~
  ./scripts/setup/floci-up.sh
  ```
  With no snapshot, re-run Steps 18–33. That is why Step 33 exists.
- **Verify** — `./scripts/utilities/verify-lab-01.sh` prints `FAIL=0`.

### 7.18 `outputs/.gitkeep` is missing from Git, or a secret got staged

- **Cause** — `.gitignore` says `outputs/` instead of `outputs/*`. Git cannot re-include a file whose
  parent directory is excluded, so the `!outputs/.gitkeep` line does nothing.
- **Diagnose** —
  ```bash
  git ls-files outputs/          # should list outputs/.gitkeep
  git check-ignore -v outputs/usms-dev-01-access-key.json
  ```
- **Fix** — change the line to `outputs/*` (Step 6.1), then `git add outputs/.gitkeep`.
- **If a secret was already committed** — removing it from the latest commit is not enough; it stays
  in history. On a Floci-only repo the credential is worthless, so the pragmatic fix is to delete
  `.git` and start the history again:
  ```bash
  rm -rf .git && git init -q && git add . && git commit -q -m "chore: restart history without secrets"
  ```
  On a real project you would rotate the key immediately and rewrite history with `git filter-repo`.
- **Verify** — `./scripts/utilities/verify-lab-01.sh` passes its two Git-hygiene checks.

### 7.19 Shell errors: `command not found`, `unexpected token`, empty variable

| Symptom | Cause | Fix |
| --- | --- | --- |
| `VPC_ID: command not found` | You wrote `VAR = value` with spaces | `VAR=value` — no spaces around `=` |
| `unexpected end of file` | A `\` line continuation has a trailing space, or a heredoc `EOF` is indented | Remove the space; put `EOF` at column 1 |
| `$MY_VAR` is empty | You opened a new terminal, or the capturing command failed | `echo $MY_VAR` to confirm; re-run the capture, or `source configs/lab-01.env` |
| `file://policy.json` → `Unable to load paramfile` | You are in the wrong directory | `pwd`, then `cd` to `policies/`, or use an absolute `file:///home/...` path |
| `permission denied: ./scripts/...` | The script is not executable | `chmod +x scripts/setup/*.sh scripts/utilities/*.sh scripts/cleanup/*.sh` |

---

## 8. Floci vs Real AWS

### 8.1 What is genuinely the same

| Aspect | Same as real AWS? |
| --- | --- |
| AWS CLI commands and flags |  Identical |
| Request/response JSON shape |  Identical |
| ARN format |  Identical (account is `000000000000`) |
| Policy document syntax and validation |  Identical |
| Users, groups, roles, instance profiles |  Created and retrievable |
| Policy versioning (5-version limit) |  Behaves the same |
| STS `assume-role` response shape |  Identical, including `ASIA` prefix and session token |
| Skills you are learning |  100 % transferable |

### 8.2 What differs

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| **IAM authorization** | Every request evaluated; `AccessDenied` returned | Any non-empty credentials accepted; requests not authorized against your policies by default | **Floci Limitation** |
| Credential signature check | Cryptographically verified | Not verified by default | **Floci Limitation** |
| **Durability by default** | Your account is permanent | Defaults to `memory` — state is discarded unless you configure otherwise | **Floci Limitation** (Part A configures around it) |
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

### 8.3 Which parts of this lab were "conceptual / real AWS"?

```text
Implemented and observable in Floci:
  users, groups, memberships, tags
  customer managed policies + versions
  inline policies
  roles + trust policies
  instance profiles
  access keys (create / list / rotate mechanics)
  sts assume-role (mechanics and response shape)
  storage durability (once configured — you proved it in Step 14)

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

## 9. Independent Lab Exercises

Complete these **on your own**. No full solutions are given. Record your commands
and output in `labs/lab-01-iam/exercises.md`.

---

### Exercise 1 — The QA identity

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
Every one of them appeared in Steps 18–22.

---

### Exercise 2 — The read-only reporting policy

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
- Re-read Step 23 on the bucket-ARN vs object-ARN distinction. You will need both.
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

- Both halves of the trust handshake must be in place (Step 30 explains what that means).
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

- Step 27 shows the version workflow, including the small Python edit trick.
- Two of the actions in the list are genuinely missing from v2. Find them by reading, not guessing.
- Think about *why* `ec2:AllocateAddress` is needed for a NAT gateway.
- Note that `verify-lab-01.sh` checks the default version is `v2`. After this exercise it will report
  one failure — update the check to `v3`, and say so in your notes. A verification script that is
  never updated is a verification script nobody trusts.

---

## 10. Lab Assessment Checklist

Print this and tick each box. Submit it with your lab report.

```text
ENVIRONMENT
☐ Docker installed and daemon running
☐ Docker Compose v2 available
☐ Project structure created BEFORE Floci was started
☐ .gitignore written and committed as the FIRST commit
☐ Proved outputs/.gitkeep is tracked (the outputs/* negation works)
☐ Explained why FLOCI_STORAGE_MODE defaults to memory and why that matters
☐ docker-compose.yml written with hybrid storage and an absolute bind mount
☐ floci-up.sh brings the environment up and verifies its own mount
☐ AWS CLI v2 installed (aws --version shows 2.x, ideally 2.13+)
☐ Profile "floci" configured with endpoint_url
☐ aws sts get-caller-identity returns account 000000000000
☐ Proved with --debug that requests go to localhost:4566
☐ Proved that stopping Floci breaks the CLI
☐ PROVED PERSISTENCE: created a user, restarted, found it again
☐ ~/floci-data contains real files
☐ floci-storage-check.sh passes all six sections
☐ whoami.sh works and fails loudly on a wrong account
☐ README.md written
☐ Part A committed to Git

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
☐ Returned to your normal identity afterwards (whoami.sh confirms)

CREDENTIALS & SAFETY
☐ Access key created for usms-dev-01, redirected straight into outputs/
☐ chmod 600 applied
☐ git check-ignore names the rule that protects the key file
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
☐ configs/lab-01.env generated with real ARNs, every value populated, no secrets
☐ Snapshot saved (floci snapshot, or the tar fallback)
☐ verify-lab-01.sh passes with FAIL=0
☐ labs/lab-01-iam/README.md written
☐ Git history shows .gitignore as the oldest commit
☐ Exercises 1–5 attempted and documented
```

---

## 11. Review Questions

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

6. **The persistence trap.** A classmate ran `floci start --persist ~/floci-data --detach`, saw the
   directory get created, and concluded persistence was working. Their IAM users vanished the next
   morning anyway. Explain the three independent reasons this could happen, and describe the single
   test that would have caught it in under a minute.

7. **Configuration as evidence.** Argue, in one paragraph, why `docker-compose.yml` being a committed
   file is a *security and reproducibility* property, not merely a convenience. What can an instructor
   or a colleague verify from your repository that they could not verify from a command you typed?

---

## 12. What We Built

### 12.1 Reflection
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
`$( )` · exit codes with `$?` (0 / 254 / 255) · named profiles and credential resolution order ·
`aws configure set` / `get` / `list-profiles`

#### Floci and Docker skills

Storage modes (`memory`, `hybrid`, `persistent`, `wal`) and why the default is the wrong one for a
course · `FLOCI_STORAGE_PERSISTENT_PATH` vs `FLOCI_STORAGE_HOST_PERSISTENT_PATH` · why sidecar
services need a separate setting · absolute paths and why `~` is never expanded ·
`FLOCI_DOCKER_RESOURCE_NAMESPACE` · `docker compose up/stop/ps/logs/config` · bind mounts vs named
volumes · Compose project labels · healthchecks · `${VAR:?message}` as a fail-fast guard ·
`floci status | logs | services | doctor | snapshot | version` · redirecting the AWS CLI with
`endpoint_url` · proving isolation from real AWS · recognising Floci limitations, especially the
absence of IAM enforcement by default

#### Shell & engineering skills

Heredocs and the critical `<< 'EOF'` vs `<< EOF` distinction · `set -Eeuo pipefail` ·
`${BASH_SOURCE[0]}` for path-independent scripts · brace expansion · `chmod 600` and `chmod +x` ·
`.gitignore` written before secrets exist, and why `outputs/*` works where `outputs/` fails ·
`git check-ignore -v` · validating JSON with `python3 -m json.tool` · writing idempotent setup
scripts that verify their own work · writing a verification script that checks configuration, not
just existence

### 12.2 Resource inventory — KEEP vs CLEAN UP

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
║ Floci         running via Compose, ~/floci-data, snapshot saved  ║
╚══════════════════════════════════════════════════════════════════╝

╔════════════════════════════ CLEAN UP ════════════════════════════╗
║ outputs/assumed-role.json   temporary creds, already expired     ║
║ usms-intern-01              only if you created it in Step 19    ║
║                             (Your turn tasks are practice     ║
║                              only no later lab uses it)        ║
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
<!-- 
### 16.3 Cumulative architecture after Lab 1

```text
┌────────────────────────────────────────────────────────────────┐
│                    USMS — AWS Account 000000000000             │
│              (Floci, Compose-managed, hybrid storage)          │
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
        ▲
        └── all of this lives in ~/floci-data and survives restarts
```

---

## 17. Preparation for the Next Lab

### Lab 02 — VPC (Virtual Private Cloud)

In the next laboratory you will build the network that every USMS server will live in: a VPC with a
public and a private subnet, an internet gateway, route tables and security groups.

**What Lab 2 will reuse from Lab 1**

| From Lab 1 | Used in Lab 2 for |
| --- | --- |
| `docker-compose.yml` + `floci-up.sh` | starting the environment, with your Lab 1 IAM still in it |
| `configs/course.env` | region, endpoint, `usms-` prefix |
| `configs/lab-01.env` | role ARNs and the `USMS_VPC_CIDR` variable |
| `usms-developer-role` | you will assume it before building the network |
| `USMSDeveloperBase` policy | the EC2/VPC create permissions you added in Step 27 and Exercise 5 |
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
-->
**Optional pre-reading;  think about these before Lab 2**

1. What is a CIDR block, and how many usable IP addresses does `10.0.0.0/16` contain?
2. What makes a subnet "public" rather than "private"? (Hint: it is not a checkbox — it is a route.)
3. Why do the private subnets in a real architecture still need outbound internet access, and what
   component provides it?
4. Why are IAM resources global, but a VPC belongs to exactly one region?

**You may stop floci with `./scripts/setup/floci-down.sh`.**


## Appendix A — Command Reference for Lab 1

### Environment lifecycle (use these, not `floci start`)

```bash
./scripts/setup/floci-up.sh            # start or resume; idempotent; self-verifying
./scripts/setup/floci-down.sh          # pause; state kept
./scripts/utilities/whoami.sh          # which identity + endpoint am I using?
./scripts/utilities/floci-storage-check.sh   # diagnose persistence problems
./scripts/utilities/verify-lab-01.sh   # full lab verification
./scripts/cleanup/floci-prune-volumes.sh     # remove stray floci volumes (dry run by default)
```

### Docker Compose

```bash
docker compose ps                 # container state and health
docker compose config             # render the effective configuration
docker compose logs -f floci      # stream logs
docker compose stop               # pause; state kept
docker compose restart floci      # full restart of the emulator
docker compose down               # remove the container; bind mount kept
# docker compose down -v          # NEVER — deletes volumes
```

### Floci CLI (works against the Compose container)

```bash
floci version
floci status | logs | services | doctor
floci snapshot save|list|load|delete <name>
floci env                                     # print env vars (we use profiles instead)
# floci start / stop --remove                 # avoid: bypasses Compose
```

### Key Floci environment variables

```text
FLOCI_STORAGE_MODE                   memory | hybrid | persistent | wal   (default: memory)
FLOCI_STORAGE_PERSISTENT_PATH        container-side data directory        (we use /app/data)
FLOCI_STORAGE_HOST_PERSISTENT_PATH   host-side path for sidecar services  (must be ABSOLUTE)
FLOCI_STORAGE_PRUNE_VOLUMES_ON_DELETE  delete volumes when a resource is deleted
FLOCI_DOCKER_RESOURCE_NAMESPACE      prefix for child container/volume names
FLOCI_HOSTNAME                       hostname other containers use to reach Floci
FLOCI_SERVICES_DOCKER_NETWORK        network for container-backed services
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
<!-- 
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

Practise an expression against a cheap read-only operation rather than guessing:

```bash
aws iam list-users --query 'Users[*].UserName'            --output text
aws iam list-users --query 'Users[?starts_with(UserName, `usms-a`)].UserName' --output text
aws iam list-users --query 'length(Users)'                --output text
```

--- -->

<!-- ## Appendix C — What changed from the previous edition of this lab

If you are returning to this lab after starting the earlier version, this is what moved and why.

| Change | Reason |
| --- | --- |
| Directory structure and `.gitignore` moved from Steps 11–12 to Steps 5–6, before Floci starts | The emulator's configuration is now a committed file, and no secret can exist before the ignore rules do |
| `git init` moved from Step 28 to Step 6 | A repository created after a credential exists has already lost the argument |
| `.gitignore` uses `outputs/*`, not `outputs/` | Git cannot re-include a file whose parent directory is excluded, so `!outputs/.gitkeep` silently did nothing |
| `floci start --persist` replaced by `docker-compose.yml` | `--persist` does not set `FLOCI_STORAGE_MODE`, does not cover sidecar services, and its flags are forgotten on every restart |
| New Step 7 explaining storage modes | The failure was invisible; students needed the concept before the command |
| New `floci-storage-check.sh` | Turns a mysterious data loss into a named cause in six checks |
| Step 14 persistence proof rewritten | The old proof (root ARN unchanged after restart) passes even in `memory` mode with no disk at all — it proved nothing |
| Sidecar ports commented out by default | ~600 published ports made Docker Desktop crawl and caused port-collision failures on shared machines |
| `verify-lab-01.sh` now checks configuration, not just existence | A lab that verifies only "the user exists" passes right up until the restart that deletes them |
| Snapshot step gained a `tar` fallback | `floci snapshot` is not available on every build |
| Steps renumbered: Part A is 1–15, Part B is 16–33 | Consequence of the reordering above | -->



!!! success "End of Lab 01"
    **Next:** Lab 02 — VPC. Your environment is now durable: stop it or leave it running, the IAM
    foundation you just built will still be there.
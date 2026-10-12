# Lab 01 - Identity and Access Management

## 1. Objectives

- Bootstrap the course environment: Docker Compose, the Floci emulator with durable storage, AWS CLI v2 and a `floci` profile, in a Git repository that cannot leak secrets.
- Prove two separate properties: commands never reach real AWS, and data survives a restart.
- Learn the AWS CLI basics every later lab assumes: command grammar, output formats, `--query`, `file://`, exit codes.
- Build the USMS IAM foundation: groups, users, customer managed and inline policies, roles with trust policies, an instance profile, STS temporary credentials and safely stored access keys.
- Save every ARN to `configs/lab-01.env` for Lab 2.

!!! info "Concepts used in this lab"
    Read these first if a term is new: [regions](../unit1/topic1.md#region) ·
    [global, regional and zonal services](../unit1/topic1.md#global-regional-and-zonal-services) ·
    [users, groups and roles](../unit8/topic1.md#iam-users-groups-and-roles) ·
    [principals and ARNs](../unit8/topic1.md#principals-identities-and-arns) ·
    [role sessions and temporary credentials](../unit8/topic1.md#role-sessions-and-temporary-credentials) ·
    [instance profiles](../unit8/topic1.md#service-roles-instance-profiles-and-service-linked-roles) ·
    [access key hygiene](../unit8/topic1.md#access-keys-and-their-hygiene) ·
    [policy grammar](../unit8/topic1.md#policy-grammar) ·
    [policy types](../unit8/topic1.md#policy-types) ·
    [policy evaluation logic](../unit8/topic1.md#the-policy-evaluation-logic)

---

## 2. Prerequisites

- No earlier lab. This lab builds the environment every later lab uses.
- macOS, Linux, or Windows with WSL2 (run everything from the Ubuntu terminal, not PowerShell).
- Internet access for the installs in Steps 2, 3 and 10.

Steps 1 to 4 check and install everything else. If a check there fails, fix it before Step 5.

---

## 3. What This Lab Reuses

Nothing: this is Lab 1.

```text
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

---

## 4. What We Are Building

Part A (Steps 1 to 15) builds a reproducible local AWS environment whose state survives restarts. Part B (Steps 16 to 33) builds three human identities and three machine identities for USMS. Permissions attach to groups and roles, never directly to users; Step 25 is the one deliberate exception, to teach inline policies.

| Identity | Type | Who/what uses it | Permissions |
| --- | --- | --- | --- |
| `usms-admin-01` | user → `usms-admins` | The lead cloud engineer | Broad (course-scoped) |
| `usms-dev-01` | user → `usms-developers` | You, building infrastructure | Build + inspect USMS resources |
| `usms-audit-01` | user → `usms-auditors` | The university auditor | Read-only, everywhere |
| `usms-ec2-app-role` | role | The USMS application server | Read/write student data in S3 |
| `usms-lambda-exec-role` | role | Notification functions (Lab 05) | Logs + messaging |
| `usms-developer-role` | role | Assumed *temporarily* by developers | Elevated build permissions |

---

## 5. Architecture

```text
   Your machine
   ┌─────────────────────────────────────────────────────────┐
   │                                                          │
   │  ~/aws-floci-course/          ~/floci-data/              │
   │  ├── docker-compose.yml ──┐   (bind-mounted into the     │
   │  ├── configs/             │    container as /app/data -  │
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

## 6. Directory Structure

### 6.1 The structure you will create

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

### 6.2 Why each folder exists

| Folder | Purpose | Who creates the files | Commit to Git? |
| --- | --- | --- | --- |
| `labs/` | One folder per lab; your working area and write-up | You | Yes |
| `policies/` | Reusable JSON policy documents. Kept **outside** `labs/` because Lab 4 will reuse a policy written in Lab 1 | You |  Yes |
| `configs/` | Environment values (region, endpoint, ARNs). No secrets | You + scripts |  Yes |
| `scripts/setup/` | Idempotent scripts that build things | You |  Yes |
| `scripts/utilities/` | Small helpers (`whoami.sh`) used every lab | You |  Yes |
| `scripts/cleanup/` | Deletion scripts - reviewed before running | You |  Yes |
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

---

## 7. Step-by-Step Implementation

!!! info "Where to run commands"
    Steps 1 to 4 run from anywhere; Step 5 creates `~/aws-floci-course`. From Step 6 on, run every
    command from `aws-floci-course/` unless a step's **Run from** says otherwise.

!!! tip "Shell variables die with the terminal"
    Every ARN below is captured into a variable. Step 33 writes them to `configs/lab-01.env` so Lab 2 can use them.

## PART A - Environment Setup (Steps 1–15)

Do not skip ahead: Part B is worthless if Part A is wrong.

### Step 1 - Open a terminal and identify your system (**OPTIONAL**)

Every later step depends on knowing your operating system and shell.

**Run from:** anywhere

```bash
uname -s -m
echo "shell = $SHELL"
echo "home  = $HOME"
```

`-s` prints the system name (`Linux`, or `Darwin` for macOS); `-m` the hardware (`x86_64`, or `arm64`/`aarch64` on Apple Silicon).

**Expected result**

```text
Linux x86_64
shell = /bin/bash
home  = /home/student
```

> Example output - yours will differ. macOS on Apple Silicon shows `Darwin arm64` and a home
> directory like `/Users/student`.

**Write your `$HOME` down.** Step 8 needs the literal absolute value; writing `~` where an absolute path is required is a common Lab 1 failure.

!!! success "**Checkpoint**"

    ```text
    You know your OS, architecture, and the absolute path of your home directory.
    If you are on Windows and this command failed, you are not in WSL.
    ```

---

### Step 2 - Verify Docker and Docker Compose (OPTIONAL)

Floci runs as a Docker container described by Docker Compose. If either is missing, nothing else works.

**Run from:** anywhere

{% raw %}```bash
docker --version
docker info --format '{{.ServerVersion}}'
docker compose version
```{% endraw %}

- `docker --version` asks the client; it succeeds even when Docker is not running.
{% raw %}- `docker info` talks to the daemon, so it is the real test. `--format '{{.ServerVersion}}'` prints one field instead of 60 lines.{% endraw %}
- `docker compose` (v2, a plugin) is not `docker-compose` (v1, retired). This course requires v2.

The most common Docker error in this course is "client works, daemon is not running".

**Expected result**

```text
Docker version 27.3.1, build ce1223035a
27.3.1
Docker Compose version v2.29.7
```

> Example output - version numbers will differ. Any Compose `v2.x` is fine.

**If Docker is not installed**

=== "Linux (Ubuntu/Debian)"

    ```bash
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    newgrp docker
    ```

    The group change lets you run `docker` without `sudo`; `newgrp` applies it without logging out.
    The script installs the Compose v2 plugin too.

=== "macOS"

    Download **Docker Desktop** from `https://www.docker.com/products/docker-desktop/`, install it,
    and launch it from Applications. Wait until the whale icon in the menu bar stops animating.
    Docker Desktop bundles Compose v2.

=== "Windows (WSL2)"

    Install **Docker Desktop for Windows**, then enable
    *Settings → Resources → WSL Integration → Ubuntu*. Verify from the **Ubuntu** terminal, not
    PowerShell.

**If `docker compose version` fails but `docker --version` works**, the Compose plugin is missing:

```bash
sudo apt-get update && sudo apt-get install -y docker-compose-plugin   # Debian/Ubuntu
```

**Verify**

```bash
docker run --rm hello-world
```

`--rm` deletes the container when it finishes.

!!! success "**Checkpoint 1**"

    ```text
    Docker
    ├── client   : installed
    ├── daemon   : running
    ├── compose  : v2 plugin present
    └── test run : "Hello from Docker!" printed
    ```

---

### Step 3 - Install the Floci CLI (SKIP IF ALREADY DONE)

Floci is an open-source local AWS emulator (about 69 services, including all of IAM and STS). It answers AWS API calls on a local port, so the AWS CLI cannot tell the difference, and mistakes cost nothing.

!!! note "We install the CLI, but we will not use `floci start`"
    From Step 9 the container is started by Docker Compose; Step 7 explains why. `floci status`,
    `logs`, `services`, `doctor` and `snapshot` still work against the Compose container.

**Run from:** anywhere

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

`curl -fsSL` downloads quietly, failing on HTTP errors and following redirects; `| sh` runs the script.

!!! warning "Piping a script from the internet into your shell"
    `curl ... | sh` runs code you have not read. Acceptable here for a known open-source project;
    professionally, download, read, then run:
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

> Example output - versions will differ. `server` reporting "not running" is expected: we have not
> started the container yet.

**Troubleshoot: `floci: command not found`.** The binary's directory is not on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

The first line fixes this terminal, the second makes it permanent (use `~/.zshrc` on zsh).

---

### Step 4 - Run Floci's environment diagnostics

Catch problems before they turn into confusing AWS CLI errors.

```bash
floci doctor
```

`doctor` checks Docker, the daemon, port 4566, disk space and the image.

**Expected result**

```text
✔ docker installed
✔ docker daemon reachable
✔ port 4566 available
✔ image floci/floci:latest available
```

> Example output - exact wording varies by version.

**If port 4566 is already in use**

```bash
# see what is holding the port
sudo lsof -i :4566          # macOS / Linux
```

Stop that program, or change the port in `docker-compose.yml` (Step 8) **and** in `configs/course.env`: a two-line change, because each value lives in one file.

---

### Step 5 - Create the course directory structure (Important)

Create the folder tree from Section 6 **before** starting Floci, so the emulator's configuration is a committed file from the first run.

**Run from**

```text
your home directory
```

```bash
cd ~
mkdir -p aws-floci-course/{labs/lab-01-iam,policies,configs,templates,outputs,screenshots,notes}
mkdir -p aws-floci-course/scripts/{setup,utilities,cleanup}
cd aws-floci-course
pwd
```

- `mkdir -p` creates parents and does not fail if a folder exists, so it is safe to re-run.
- `{a,b,c}` is brace expansion: one `mkdir`, seven folders. No spaces inside the braces.

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

**From here to the end of Part A, stay in `~/aws-floci-course`.**

---

### Step 6 - Write `.gitignore` and initialise Git - before any secret exists

A secret that is never committed cannot be leaked. Write the ignore rules before the repository contains anything and before any command has produced a credential.

#### 6.1 Write the ignore rules

```bash
cat > .gitignore << 'EOF'
# ============================================================
#  aws-floci-course/.gitignore
#  Written BEFORE any secret existed. Keep it that way.
# ============================================================

# ---- Command output and SECRETS ----
# NOTE the trailing /* - see the explanation below. It matters.
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

!!! bug "`outputs/` vs `outputs/*` - a real bug, not a style preference"
    ```text
    outputs/
    !outputs/.gitkeep
    ```

    **This does not work.** Git cannot re-include a file whose parent directory is excluded, so the
    negation does nothing and the folder silently disappears from the repository. `outputs/*`
    excludes the **contents** and leaves the directory visible, so the negation works. The next
    command proves it.

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

If `outputs/.gitkeep` is **missing**, your `.gitignore` has `outputs/` instead of `outputs/*`. Fix it before continuing.

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

The fake key is absent from `git status`, and `git check-ignore -v` names the file and line of the rule that blocked it.

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

### Step 7 - Understand Floci storage modes (read this before you start anything)

The single most important concept in Part A. Floci's durability is set by one variable, `FLOCI_STORAGE_MODE`:

| Mode | Behaviour | Good for |
| --- | --- | --- |
| `memory` | **Everything is lost when the container stops** | CI pipelines, throwaway tests |
| `hybrid` | In-memory reads, asynchronous flush to disk | **Development - our choice** |
| `persistent` | Synchronous disk write on every change | Maximum safety, slower |
| `wal` | Append-only write-ahead log with compaction | High-write workloads |

**The default is `memory`.** That is why `floci start --persist ~/floci-data` is not enough:

- **Cause 1 - a directory is not a mode.** `--persist` mounts a host directory at `/app/data` but leaves the mode at `memory`. Floci writes almost nothing durable there, and deletes the Docker volumes it created on teardown: the "new volume on every restart" symptom.
- **Cause 2 - sidecar services use a different variable.** RDS, OpenSearch, MSK, ECR, ElastiCache, Lambda, ECS and EKS run as child containers and need `FLOCI_STORAGE_HOST_PERSISTENT_PATH`, which must be **absolute**. Nothing expands `~`; a literal `~/floci-data` creates a directory named `~`.
- **Cause 3 - CLI flags are not remembered.** Any plain `floci start`, `floci restart` or Docker Desktop restart brings the container back on defaults (memory mode, no bind mount), silently.

The three settings that actually matter:

```yaml
FLOCI_STORAGE_MODE: hybrid                        # 1. durability ON (default is memory)
FLOCI_STORAGE_PERSISTENT_PATH: /app/data          # 2. where Floci writes, container side
FLOCI_STORAGE_HOST_PERSISTENT_PATH: /home/you/floci-data   # 3. sidecars, host side, ABSOLUTE
```

Plus one that gives child containers and volumes stable, greppable names:

```yaml
FLOCI_DOCKER_RESOURCE_NAMESPACE: floci-course
```

!!! question "**Think about it**"

    Write two sentences in `notes/lab-01-notes.md` answering: *if `--persist` mounts
    a directory correctly, why is the directory almost empty in `memory` mode?* You will check your
    answer against real output in Step 14.


### Step 8 - Write `docker-compose.yml` and `configs/course.env`

Capture Step 7's configuration in two committed files.

#### 8.1 `configs/course.env` - values every lab needs

```bash
cat > configs/course.env << 'EOF'
# =====================================================================
# USMS Course - shared configuration
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
    The `usms-` prefix is how you find, filter, bill and safely delete *your* resources in a shared
    account. Lab 2 uses it with `--filters`.

!!! warning "This file exports `AWS_PROFILE` and nothing else AWS-related"
    No `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`. This course uses profiles;
    Step 11 explains why mixing them with environment variables makes failures hard to diagnose.

#### 8.2 `docker-compose.yml` 

```bash
cat > docker-compose.yml << 'EOF'
# =============================================================================
#  aws-floci-course - pinned Floci environment
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

| Line | Why it is there |
| --- | --- |
| `FLOCI_STORAGE_MODE: hybrid` | Turns durability on. Without it the rest is decoration |
| `${FLOCI_HOST_DATA_DIR:?...}` | The `:?` form makes Compose **fail with your error message** rather than mount something wrong |
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

That error is **correct**: the `:?` guard working, because Step 9 has not written `.env` yet. If you saw `compose file is valid`, a stale `.env` exists; run `rm -f .env` and re-run.

---

### Step 9 - Write the start/stop scripts and bring Floci up

Wrap Compose in two short scripts, so starting the environment is one command that checks its own work.

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
# GENERATED by scripts/setup/floci-up.sh - do not edit, do not commit.
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

- `set -Eeuo pipefail` stops on any error, undefined variable or failed pipeline stage.
- `${BASH_SOURCE[0]}` resolves the repo root wherever you run the script from.
- Script section 2 turns Step 7's silent Cause 3 into a loud failure; script section 7 asks Docker what is actually mounted and fails if it is not a host bind mount.

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

**Verify - three independent ways**

```bash
docker compose ps
floci status
curl -s http://localhost:4566/_floci/health | head -c 300 ; echo
```

The `curl` check involves neither Docker nor the Floci CLI: JSON back means something really listens on 4566. `/_localstack/health` also works.

**Useful lifecycle commands (learn these now)**

```bash
./scripts/setup/floci-up.sh     # start or resume - safe to run any time
./scripts/setup/floci-down.sh   # pause, state kept
docker compose ps               # is it running and healthy?
docker compose logs -f floci    # stream server logs - your best debugging tool
floci status                    # the CLI's view of the same container
floci logs                      # same logs, via the CLI
floci services                  # which AWS services are enabled
```

!!! danger "Commands that will destroy your coursework"
    | Command | What it does |
    | --- | --- |
    | `docker compose down -v` | The `-v` deletes volumes |
    | `docker volume prune` | Unfiltered - hits every unused volume on your machine |
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

### Step 10 - Install the AWS CLI (version 2)

The AWS CLI is a client, not AWS: it builds each API request, signs it, sends it to whatever endpoint it is told, and prints the JSON response. That is how it can talk to Floci.

**Run from:** anywhere

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

> Example output - versions differ.

!!! danger "It must say `aws-cli/2.x`, and ideally 2.13 or newer"
    `aws-cli/1.x` is v1: uninstall it (`pip uninstall awscli`) and install v2. The `endpoint_url`
    profile setting arrived in **2.13**; on an older 2.x you must pass
    `--endpoint-url http://localhost:4566` on every command. Step 12 shows how to check.

**Explore the CLI's own help**

```bash
aws help
aws iam help
aws iam create-user help
```

Press `q` to quit. This built-in help is the authoritative reference for every option.

---

### Step 11 - Understand AWS credentials, regions and profiles

Every AWS CLI command needs four values:

| Value | What it is | Our value (Floci) |
| --- | --- | --- |
| **Access Key ID** | Public half of a credential pair. Like a username | `test` |
| **Secret Access Key** | Private half. Used to sign requests. Like a password | `test` |
| **Region** | Which geographic AWS "copy" you are talking to | `us-east-1` |
| **Endpoint URL** | Which server to send the request to | `http://localhost:4566` |

!!! info "Regions and global services"
    Resources are region-scoped, and each region has several Availability Zones (Lab 2 uses them).
    IAM is one of the few **global** services: you still pass a region, but IAM resources appear in
    every region. See [regions](../unit1/topic1.md#region) and
    [global, regional and zonal services](../unit1/topic1.md#global-regional-and-zonal-services).

A **profile** is a named set of these values, stored in two files:

```text
~/.aws/credentials     ← secrets  (access key id + secret)
~/.aws/config          ← settings (region, output format, endpoint_url)
```

The CLI looks for credentials in this order and stops at the first hit:

```text
1. Command-line options       (--profile, --region, --endpoint-url)
2. Environment variables      (AWS_ACCESS_KEY_ID, AWS_ENDPOINT_URL, ...)
3. ~/.aws/credentials         (the named profile's secrets)
4. ~/.aws/config              (the named profile's settings)
5. IAM role attached to the machine (EC2 instance profile - Lab 3)
```

!!! warning "Do not mix profiles and environment variables"
    `eval $(floci env)` exports `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID` and so on. Level 2 then
    silently beats levels 3 and 4, and you cannot tell which credentials were used. **This course
    uses named profiles.** If you ever ran it, clear them:

    ```bash
    unset AWS_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
          AWS_DEFAULT_REGION AWS_REGION
    ```

    `AWS_PROFILE` is not in that list: `configs/course.env` sets it, and it selects a profile rather
    than overriding one.

---

### Step 12 - Create the `floci` AWS CLI profile

Store the four values once.

```bash
aws configure set aws_access_key_id     test                  --profile floci
aws configure set aws_secret_access_key test                  --profile floci
aws configure set region                us-east-1             --profile floci
aws configure set output                json                  --profile floci
aws configure set endpoint_url          http://localhost:4566 --profile floci
```

- Credentials go to `~/.aws/credentials`, everything else to `~/.aws/config`.
- `endpoint_url` redirects **all** services in this profile to Floci. Without it the CLI contacts real AWS.
- `test`/`test` are dummies; Floci accepts any non-empty values.

!!! danger "Why `test`/`test` is safe here and never elsewhere"
    Never type real credentials into a command like this: your shell history (`~/.bash_history`)
    records everything.

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
source configs/course.env
echo 'source ~/aws-floci-course/configs/course.env' >> ~/.bashrc
```

(Use `~/.zshrc` on zsh.) `course.env` exports `AWS_PROFILE=floci`, so `--profile floci` becomes optional. The next two steps still show it so you see where it belongs.

**If your AWS CLI is older than 2.13**

```bash
aws configure get endpoint_url --profile floci
```

If that prints the URL but commands still reach `amazonaws.com` (Step 14 tests this), upgrade the CLI, or add this to `course.env`:

```bash
# ONLY if your AWS CLI predates 2.13 and ignores the profile's endpoint_url
export AWS_ENDPOINT_URL=http://localhost:4566
```

!!! question "**Your turn**"

    Run `aws configure list --profile floci`. Identify which column tells you *where* each value came
    from, and explain why the `Type` for the access key says `shared-credentials-file`.

---

### Step 13 - Your first AWS CLI command, and the `whoami` helper

Ask the emulator "who am I?", the most useful diagnostic in AWS, then wrap it in a script you run at the start of every lab.

```bash
aws sts get-caller-identity --profile floci
```

```text
aws           the CLI program
 └── sts                  the SERVICE (Security Token Service)
      └── get-caller-identity   the OPERATION (an API call)
           └── --profile floci  an OPTION (which credentials/endpoint to use)
```

`get-caller-identity` returns the identity behind your credentials and needs **no permissions**, so it is always the first thing to run when something is broken.

**Expected result**

```json
{
    "UserId": "AKIAIOSFODNN7EXAMPLE",
    "Account": "000000000000",
    "Arn": "arn:aws:iam::000000000000:root"
}
```

> Example output - your `UserId` may differ.

`Account` `000000000000` is Floci's fixed dummy account: **proof you are not on real AWS.** Step 16 explains the `Arn`. `Could not connect to the endpoint URL` means Floci is not running: `./scripts/setup/floci-up.sh`.

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
  printf '\033[1;32m[ok] Account %s - this is Floci, not real AWS.\033[0m\n' "$acct"
else
  printf '\033[1;31m[DANGER] Account %s is NOT the Floci account (%s).\033[0m\n' "$acct" "$ACCOUNT_ID"
  printf '\033[1;31mYou may be pointed at REAL AWS. Stop and re-check your profile.\033[0m\n'
  exit 1
fi
EOF

chmod +x scripts/utilities/whoami.sh
./scripts/utilities/whoami.sh
```

`${VAR:-default}` substitutes `default` when `VAR` is unset, so `set -u` does not kill the script.

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
[ok] Account 000000000000 - this is Floci, not real AWS.
```

!!! success "**Checkpoint 4**"

    ```text
    AWS CLI  ──→  Floci  : working
    Account            : 000000000000
    whoami.sh          : written and passing
    ```

---

### Step 14 - Prove isolation from real AWS, and prove persistence

Two different claims need two different proofs; passing one tells you nothing about the other.

```text
ISOLATION   "my commands never reach real AWS"
PERSISTENCE "my data survives a restart"
```

#### 14.1 Isolation, Test 1 - the account number

Already done in Step 13: `000000000000` is not a real account.

#### 14.2 Isolation, Test 2 - inspect the actual URL the CLI used

```bash
aws sts get-caller-identity --profile floci --debug 2>&1 \
  | grep -i "endpoint\|Making request" \
  | head -5
```

`--debug` prints the CLI's internal decisions to stderr; `2>&1` sends them into the pipe for `grep`.

**Expected result**

```text
... Setting sts timeout as (60, 60)
... Making request for OperationModel(name=GetCallerIdentity) with params:
    {'url': 'http://localhost:4566/', ...
```

> Example output. The important part is `http://localhost:4566` - **not** `amazonaws.com`.

#### 14.3 Isolation, Test 3 - stop the container

```bash
./scripts/setup/floci-down.sh
aws sts get-caller-identity --profile floci
```

**Expected result**

```text
Could not connect to the endpoint URL: "http://localhost:4566/"
```

Stopping a local container could not break calls to real AWS. **Leave it stopped**; the persistence test starts here.

#### 14.4 Persistence - the test that actually matters

Restarting and seeing the same root ARN proves nothing: the root identity is a constant, even in `memory` mode. Create something, restart, and look for it again.

```bash
# 1. Bring Floci back up
./scripts/setup/floci-up.sh

# 2. Create a marker resource
aws iam create-user --user-name persistence-check --output text --query 'User.Arn'

# 3. Restart the container - a full stop and start, not just a pause
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

The second line is the whole point of Part A. `NoSuchEntity` instead means your storage configuration is wrong: run `./scripts/utilities/floci-storage-check.sh` (Step 15) and re-read Step 7.

**Look at the data on disk**

```bash
ls -la ~/floci-data
du -sh ~/floci-data
```

You want real files and a non-zero size. An **empty** directory alongside a surviving user means Floci persists somewhere else, also a misconfiguration.

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

`$?` is the last command's exit status: `0` success, `254` service error (such as `NoSuchEntity`), `255` client or connection error. The verification script in Section 8 is built on this.

!!! note "Floci Limitation - identity is not really authenticated"
    Floci accepts any non-empty credentials and reports you as the account `root` user.

    Real AWS verifies your signature cryptographically and rejects wrong credentials.

    In Floci, `get-caller-identity` confirms **connectivity**, not **authentication**.

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

### Step 15 - Storage diagnostics, README, and commit Part A

Write the tool you reach for when persistence looks wrong, write the project front page, and commit.

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

hdr "2. Storage mode - the usual culprit"
mode="$(envof FLOCI_STORAGE_MODE)"; mode="${mode:-<unset>}"
if [ "$mode" = "memory" ] || [ "$mode" = "<unset>" ]; then
  bad "FLOCI_STORAGE_MODE=$mode"
  note "Floci defaults to 'memory'. Nothing survives a restart, and Floci deletes"
  note "its own volumes on teardown - hence 'a new volume every time'."
  note "Fix: FLOCI_STORAGE_MODE=hybrid in configs/course.env, then floci-up.sh"
else
  ok "FLOCI_STORAGE_MODE=$mode (durable)"
fi

hdr "3. Is /app/data a real host directory?"
m="$(docker container inspect "$FLOCI_CONTAINER_NAME" \
     --format '{{ range .Mounts }}{{ if eq .Destination "/app/data" }}{{ .Type }} {{ .Source }}{{ end }}{{ end }}')"
if [ -z "$m" ]; then
  bad "/app/data is not mounted - state dies with the container."
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
  bad "FLOCI_STORAGE_HOST_PERSISTENT_PATH is unset - sidecars use anonymous volumes."
elif [ "${hp#/}" = "$hp" ]; then
  bad "FLOCI_STORAGE_HOST_PERSISTENT_PATH='$hp' is not absolute. Floci rejects it."
else
  ok "FLOCI_STORAGE_HOST_PERSISTENT_PATH=$hp"
fi

hdr "5. Floci-managed volumes on this machine"
vols="$(docker volume ls -q --filter label=floci=true || true)"
if [ -z "$vols" ]; then
  note "(none - expected while everything is bind-mounted)"
else
  printf '%s\n' "$vols" | sed 's/^/         /'
  note "Count: $(printf '%s\n' "$vols" | wc -l | tr -d ' ')"
  note "Growing on every restart? Storage mode is still wrong."
fi

hdr "6. Host state directory"
if [ -d "$FLOCI_HOST_DATA_DIR" ]; then
  ok "$FLOCI_HOST_DATA_DIR exists (size: $(du -sh "$FLOCI_HOST_DATA_DIR" 2>/dev/null | cut -f1))"
  ls -1 "$FLOCI_HOST_DATA_DIR" 2>/dev/null | head -20 | sed 's/^/           /'
  [ -n "$(ls -A "$FLOCI_HOST_DATA_DIR" 2>/dev/null)" ] || bad "Directory is EMPTY - see checks 2 and 3."
else
  bad "$FLOCI_HOST_DATA_DIR does not exist."
fi
printf '\n'
EOF

chmod +x scripts/utilities/floci-storage-check.sh
./scripts/utilities/floci-storage-check.sh
```{% endraw %}

**Expected result** - six sections, all `[ok]`, with section 5 reporting no dangling volumes. Keep the output as report evidence; it is the first thing to run in Section 10 troubleshooting.

#### 15.2 A cleanup script for stray volumes

If you experimented with `floci start` before reading Step 7, you may have orphaned volumes. This removes only dangling volumes labelled `floci=true`, and is a dry run unless you pass `--yes`.

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
# AWS CLI + Floci - USMS Course Project

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

Confirm **no file under `outputs/`** and **no `.env`** appears. Then:

```bash
git add .
git commit -q -m "feat(lab-01): environment bootstrap with durable Floci storage

Floci is pinned by docker-compose.yml with FLOCI_STORAGE_MODE=hybrid and an
absolute host bind mount, because 'floci start --persist' does not enable a
durable storage mode and its flags are not remembered across restarts."
git log --oneline
```

!!! success "**Checkpoint 6 - end of Part A**"

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
## PART B - Building the IAM Foundation (Steps 16–33)

Part B assumes Part A is complete. If you skipped Step 14's persistence proof, go back: otherwise the IAM foundation may evaporate.

---

### Step 16 - IAM concepts and the anatomy of an ARN

!!! info "IAM in brief"
    A **user** has permanent credentials; a **group** is a container of users (not an identity, cannot
    be nested); a **role** has no permanent credentials and is *assumed* for temporary ones; a
    **policy** is JSON that allows or denies actions on resources under conditions. Full treatment:
    [users, groups and roles](../unit8/topic1.md#iam-users-groups-and-roles),
    [policy grammar](../unit8/topic1.md#policy-grammar),
    [policy types](../unit8/topic1.md#policy-types).

The distinction students most often miss:

| | **Permissions policy** | **Trust policy** |
| --- | --- | --- |
| Answers | "What may this identity **do**?" | "**Who** may become this role?" |
| Attached to | users, groups, roles | roles only (exactly one) |
| Key element | `Action` + `Resource` | `Principal` + `sts:AssumeRole` |
| CLI flag | `--policy-document` on `create-policy` | `--assume-role-policy-document` on `create-role` |

Every role needs **both**. A missing trust policy is why a role "exists but nobody can use it".

Policies come in three kinds: **AWS managed** (maintained by AWS, broad), **customer managed** (yours, with its own ARN and versions; the default choice) and **inline** (embedded in one identity, dies with it).

An **ARN** is the globally unique address of a resource:

```text
arn:aws:iam::000000000000:user/usms-dev-01
 │   │   │  │       │           │
 │   │   │  │       │           └── resource  (type/name)
 │   │   │  │       └────────────── account id (12 digits)
 │   │   │  └────────────────────── region  (EMPTY for IAM - it is global!)
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
arn:aws:s3:::usms-student-data/*                ← the OBJECTS inside the bucket - a different ARN!
arn:aws:ec2:us-east-1:000000000000:instance/i-0abc123
```

!!! danger "The classic S3 mistake"
    `arn:aws:s3:::my-bucket` refers to the **bucket** (used for `s3:ListBucket`).
    `arn:aws:s3:::my-bucket/*` refers to the **objects** (used for `s3:GetObject`, `s3:PutObject`).
    A policy that lists only the first will fail every `GetObject` call. You will write both in
    Step 23.

A policy document:

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

`Version` is always `"2012-10-17"`: it is the policy language version, and anything else silently disables variables such as `${aws:username}`. `Sid` is an optional label that helps debugging.

[Evaluation](../unit8/topic1.md#the-policy-evaluation-logic) follows two rules: **default deny** (no policy, no access) and **explicit deny always wins** over any number of allows.

!!! note "Floci Limitation - policies are stored, not enforced (by default)"
    Floci accepts any non-empty credentials and does not authorize requests against your IAM policies
    unless stricter authentication is enabled. Everything you write is stored and validated, but a
    too-narrow policy will not produce `AccessDenied`.

    Real AWS evaluates every request and returns `AccessDenied`. Step 32 shows the policy simulator
    as the closest substitute; Section 11 lists what is conceptual only.

    Write every policy as if it *were* enforced. In a real account it will be.

---

### Step 17 - Inspect the empty IAM account

See the "before" state and the three output formats.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

```bash
cd ~/aws-floci-course/labs/lab-01-iam
```

```bash
aws iam list-users
```

`list-users` returns every IAM user in the account; read-only and harmless.

**Expected result**

```json
{
    "Users": []
}
```

An empty list, not an error. If `persistence-check` appears, you skipped Step 14's cleanup: run `aws iam delete-user --user-name persistence-check`.

**Now the same data in three formats**

```bash
aws iam list-users --output json
aws iam list-users --output table
aws iam list-users --output text
```

| Format | Best for |
| --- | --- |
| `json` | Machines, `jq`, saving to `outputs/` - the default and the most complete |
| `table` | Humans reading the screen. Never parse it in a script |
| `text` | Shell scripts. Tab-separated, no quotes or braces - perfect for `$( )` capture |

!!! question "**Your turn**"

    Run `aws iam list-roles --output table`. Floci may pre-create some service-linked roles.
    Are the results the same in `text` format? Which one would you use inside a script, and why?

---

### Step 18 - Create the IAM groups

Create the three permission containers before any user, so users are placed correctly from birth.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

```bash
aws iam create-group --group-name usms-admins
aws iam create-group --group-name usms-developers
aws iam create-group --group-name usms-auditors
```

A new group has no permissions and no members. There is no `--region`: IAM is global.

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

> Example output - your `GroupId` and `CreateDate` will differ.

`"Path": "/"` is an optional hierarchy (`/engineering/backend/`); we keep `/`.

**Verify**

```bash
aws iam list-groups --query 'Groups[*].[GroupName,Arn]' --output table
```

`--query` filters the response on your machine using **JMESPath**:

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

### Step 19 - Create the IAM users and capture their ARNs

Create three users, and learn the most important CLI habit: **never copy an ID by hand**. Ask the CLI for one value and store it in a shell variable.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

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

- `VAR=$(command)` captures the command's output. No spaces around `=`.
- A trailing `\` continues the line; nothing may follow it, not even a space.
- `--tags` labels the resource for cost, ownership and environment. Tag everything.
- **`--query` + `--output text` is the standard idiom for capturing an ID**: one field, no JSON quotes.

**Expected result**

```text
arn:aws:iam::000000000000:user/usms-admin-01
arn:aws:iam::000000000000:user/usms-dev-01
arn:aws:iam::000000000000:user/usms-audit-01
```

!!! warning "Shell variables die with the terminal"
    Close this terminal and `$DEV_ARN` is gone; Step 33 writes these values to `configs/lab-01.env`.
    Your IAM users survive a restart (Step 14), your shell variables never do.

**Verify**

```bash
aws iam list-users \
  --query 'Users[*].{User:UserName,Created:CreateDate,Arn:Arn}' \
  --output table
```

`{Name:Field}` builds an object with renamed keys, which become table column headers (compare Step 18's unlabelled `[Field1,Field2]`).

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

### Step 20 - Add users to groups

Connect each identity to its permission container.

**Run from**

```text
aws-floci-course/labs/lab-01-iam/
```

```bash
aws iam add-user-to-group --group-name usms-admins     --user-name usms-admin-01
aws iam add-user-to-group --group-name usms-developers --user-name usms-dev-01
aws iam add-user-to-group --group-name usms-auditors   --user-name usms-audit-01
```

No output on success; many AWS action commands are silent. Check `$?` if unsure.

**Verify - from both directions**

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

Answering from both directions is what an access investigation needs.

!!! question "**Your turn**"

    Put `usms-intern-01` (from Step 19) into `usms-auditors`, then verify with a **single** command that
    the auditors group now has two members.

---

### Step 21 - Explore and attach an AWS managed policy

Use a policy AWS wrote before writing your own. AWS managed policy ARNs have the literal account `aws`:

```text
arn:aws:iam::aws:policy/ReadOnlyAccess
```

They are usually too broad for least privilege; `ReadOnlyAccess` for an auditor is one of the rare right fits.

**Explore what is available**

```bash
aws iam list-policies --scope AWS --max-items 10 \
  --query 'Policies[*].[PolicyName,Arn]' --output table
```

`--scope AWS` shows AWS managed policies (`--scope Local` shows yours); `--max-items 10` limits output.

!!! note "Floci Limitation - only a subset of AWS managed policies"
    Floci ships a subset. If `ReadOnlyAccess` is missing, the attach below fails with `NoSuchEntity`.

    Real AWS has 1,000+ managed policies.

    Use the workaround and continue; nothing later depends on which of the two you used.

```bash
aws iam attach-group-policy \
  --group-name usms-auditors \
  --policy-arn arn:aws:iam::aws:policy/ReadOnlyAccess
```

**Workaround if `ReadOnlyAccess` does not exist in your Floci build**

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

### Step 22 - Write your first customer managed policy

Write a policy from scratch and learn `file://`. The requirement:

> A USMS developer must be able to **look at** the infrastructure (IAM, EC2, VPC, S3, CloudWatch), and
> **build networking** - because Lab 2 is the VPC lab. They must **not** be able to create IAM users,
> delete anything permanent, or touch billing.

**Run from**

```text
aws-floci-course/policies/
```

```bash
cd ~/aws-floci-course/policies
```

**Create the file**

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

- `ReadInfrastructure`: wildcards on *read* actions (`ec2:Describe*`) are normal; on write actions they are not.
- `BuildNetworkingForLab02`: only the EC2/VPC writes Lab 2 needs, only in `us-east-1`. Least privilege means enumerating actions instead of `ec2:*`.
- `DenyDangerousIdentityChanges`: the privilege-escalation guardrail. Explicit deny wins even if someone later attaches `AdministratorAccess` to the group.

**Validate the JSON before sending it**

```bash
python3 -m json.tool usms-developer-base-policy.json > /dev/null && echo "Valid JSON"
```

A local check reports the exact line, instead of AWS's vague `MalformedPolicyDocument`.

**Create the policy in IAM**

```bash
DEV_POLICY_ARN=$(aws iam create-policy \
  --policy-name USMSDeveloperBase \
  --description "Read infrastructure + build VPC networking for USMS. Denies identity escalation." \
  --policy-document file://usms-developer-base-policy.json \
  --query 'Policy.Arn' \
  --output text)

echo "$DEV_POLICY_ARN"
```

`file://name.json` reads the parameter from a file relative to the current directory; `file:///home/you/name.json` is absolute (three slashes). Keeping policies in `policies/` makes them version-controlled and reusable in Lab 4.

**Expected result**

```text
arn:aws:iam::000000000000:policy/USMSDeveloperBase
```

**Attach it to both groups that need it**

```bash
aws iam attach-group-policy --group-name usms-developers --policy-arn "$DEV_POLICY_ARN"
aws iam attach-group-policy --group-name usms-admins     --policy-arn "$DEV_POLICY_ARN"
```

One policy, two attachments: change it once and both groups update.

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

`Attached` must be `2`. `Default: v1` matters in Step 27.

!!! success "**Checkpoint 8**"

    ```text
    IAM
    ├── usms-admins      ← USMSDeveloperBase
    ├── usms-developers  ← USMSDeveloperBase
    └── usms-auditors    ← ReadOnlyAccess (or USMSReadOnly)
    ```

---

### Step 23 - Write the S3 data policy (used for real in Lab 4)

Write the policy governing student transcript storage, with the bucket and object ARNs right.

**Run from**

```text
aws-floci-course/policies/
```

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

Two Allow statements, because they act on two different ARNs:

```text
arn:aws:s3:::usms-student-data      → the bucket   → s3:ListBucket
arn:aws:s3:::usms-student-data/*    → the objects  → s3:GetObject / s3:PutObject
```

`s3:ListBucket` on the `/*` ARN is a no-op. The bucket arrives in Lab 4: **policies may reference resources that do not exist yet**, because they are evaluated at request time.

**Verify**

```bash
aws iam list-policies --scope Local \
  --query 'Policies[*].{Name:PolicyName,Attached:AttachmentCount}' --output table
```

---

### Step 24 - Use `--generate-cli-skeleton` to discover parameters

Work out a command's parameters without leaving the terminal.

**Run from**

```text
aws-floci-course/templates/
```

```bash
cd ~/aws-floci-course/templates
```

```bash
aws iam create-role --generate-cli-skeleton > create-role-skeleton.json
cat create-role-skeleton.json
```

`--generate-cli-skeleton` prints an empty JSON template of every parameter **without calling AWS**, so it works even with Floci stopped.

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

> Example output - fields vary by CLI version.

A filled-in skeleton can be submitted with `--cli-input-json file://filled.json`, which suits CI/CD pipelines.

!!! question "**Your turn**"

    Generate a skeleton for `aws iam create-policy` and for `aws ec2 create-vpc` (you will need the
    latter in Lab 2). Save both in `templates/`. Which parameter of `create-vpc` looks like the most
    important one?

---

### Step 25 - Add an inline policy (self-service credentials)

Let users rotate their own access keys without an administrator, using an **inline policy** (embedded in one identity, no ARN, deleted with it) and the **policy variable** `${aws:username}`, which is replaced at evaluation time by the caller's name. See [policy variables](../unit8/topic1.md#policy-variables).

**Run from**

```text
aws-floci-course/policies/
```

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
    `<< 'EOF'` stops your shell expanding `${aws:username}` to an empty string, which would silently
    break the policy. Check with `grep aws:username usms-self-manage-credentials.json`. Every policy
    heredoc uses the quoted form; Step 33 deliberately uses the *unquoted* form, where expansion is wanted.

- `attach-user-policy` attaches an existing **managed** policy by ARN.
- `put-user-policy` embeds an **inline** document. "Put" overwrites, so re-running is safe.

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

`aws iam list-attached-user-policies --user-name usms-dev-01` returns an empty list: **inline and attached policies are listed by different commands**, which is how permissions get missed in reviews.

MFA actions are included to make the policy realistic; MFA itself is **conceptual / real AWS** here, since Floci has no console login. See [multi-factor authentication](../unit8/topic1.md#multi-factor-authentication).

---

### Step 26 - Inspect what you have built

Learn the read side of IAM, used in access investigations.

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

Effective permissions come from group policies, attached user policies, inline user policies and, on real AWS, permission boundaries and SCPs. Checking only one is an incomplete audit.

**B. Read the actual policy JSON back out**

```bash
POLICY_ARN=arn:aws:iam::000000000000:policy/USMSDeveloperBase
VER=$(aws iam get-policy --policy-arn $POLICY_ARN --query 'Policy.DefaultVersionId' --output text)

aws iam get-policy-version \
  --policy-arn $POLICY_ARN \
  --version-id $VER \
  --query 'PolicyVersion.Document'
```

`get-policy` returns metadata; only `get-policy-version` returns the document. The first call's output feeds the second.

**C. The whole account in one call**

```bash
aws iam get-account-authorization-details > ~/aws-floci-course/outputs/lab-01-iam-snapshot.json

wc -l ~/aws-floci-course/outputs/lab-01-iam-snapshot.json
```

Every user, group, role and policy with documents: the basis of most IAM audit tooling. It goes in the git-ignored `outputs/`.

**D. Optional: pretty-query it with `jq`**

```bash
sudo apt install -y jq        # or: brew install jq
jq '.UserDetailList[] | {UserName, Groups: .GroupList}' \
   ~/aws-floci-course/outputs/lab-01-iam-snapshot.json
```

`--query` shapes a live response; `jq` processes files you already have. Steps 30 and 31 need `jq`, so install it now.

!!! success "**Checkpoint 9**"

    ```text
    Identity layer complete
    ├── 3 groups, each with policies
    ├── 3 users, each in a group
    ├── 1 inline policy on usms-dev-01
    └── full account snapshot saved to outputs/
    ```

---
### Step 27 - Policy versions

Change a policy safely. Customer managed policies keep up to **5 versions**, so you can roll back. Lab 2 needs `ec2:DeleteVpc` and `ec2:DescribeAvailabilityZones`, so create a new version rather than editing in place.

**Run from**

```text
aws-floci-course/policies/
```

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

- The Python block edits the JSON programmatically: safer and repeatable.
- `--set-as-default` makes the new version the one evaluated; without it the version exists but is inert.

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

**Rolling back** is one command - no re-upload needed:

```bash
# (Do NOT run this now; shown for reference)
# aws iam set-default-policy-version --policy-arn <arn> --version-id v1
```

!!! warning "The 5-version limit"
    The 6th `create-policy-version` fails with `LimitExceeded` until you `delete-policy-version` an
    old one. Automated pipelines hit this often.

---

### Step 28 - Create a role for EC2, with a trust policy

Create the identity the USMS application server uses in Lab 3. A server holding an access key keeps a permanent secret on a machine that may be compromised, imaged or backed up; a role delivers **temporary credentials that rotate automatically**.

```text
        WITHOUT a role                     WITH a role
   ┌──────────────────┐             ┌──────────────────┐
   │  EC2 instance    │             │  EC2 instance    │
   │  access key on   │  ✗ risky    │  no secrets      │  ✓ safe
   │  disk forever    │             │  temp creds via  │
   └──────────────────┘             │  instance meta   │
                                    └──────────────────┘
```

The trust policy's **Principal** for an EC2 role is the EC2 service:

```json
"Principal": { "Service": "ec2.amazonaws.com" }
```

**Run from**

```text
aws-floci-course/policies/
```

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

- `--assume-role-policy-document` is the **trust** policy, despite its name.
- The role starts with zero permissions; trust and permissions are separate.

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

An EC2 instance is given an **instance profile**, a wrapper holding exactly one role, not the role directly. The console hides this; with the CLI you must do it, and forgetting it is a common Lab 3 failure.

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

### Step 29 - Create the Lambda execution role

Create the role Lab 5's notification function runs as: same pattern, different principal.

**Run from**

```text
aws-floci-course/policies/
```

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

Without `logs:CreateLogStream` and `logs:PutLogEvents`, a function still runs but produces **no logs at all**: a common real-world misconfiguration.

**Verify**

```bash
aws iam list-roles \
  --query 'Roles[?starts_with(RoleName, `usms-`)].{Role:RoleName,Arn:Arn}' \
  --output table
```

``[?starts_with(RoleName, `usms-`)]`` is a JMESPath **filter**: keep only matching elements. Backticks write a literal string. This is how the `usms-` prefix finds your resources in a busy account.

---

### Step 30 - A role for humans, and temporary credentials with STS

The pattern organisations use for human access: log in with minimal permissions, then *assume* a role for elevated, temporary, logged access. See [role sessions and temporary credentials](../unit8/topic1.md#role-sessions-and-temporary-credentials).

```text
usms-dev-01                        usms-developer-role
(few permissions,       assume →   (elevated permissions,
 permanent keys)                    temporary creds, 1 hour)
```

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

- The `Principal` is now an AWS identity ARN. `"AWS": "arn:aws:iam::000000000000:root"` would mean any identity in the account that *also* has `sts:AssumeRole` permission.
- `--max-session-duration 3600` caps credentials at 1 hour.

#### 30.2 Give the developers group permission to assume it

Trust alone is not enough; both sides must agree.

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

!!! note "The two-sided handshake - memorise this"
    ```text
    Role's TRUST policy         says  "usms-dev-01 may assume me"
    User's PERMISSIONS policy   says  "I may call sts:AssumeRole on that role"
                                       ↓
                            BOTH required. Either one missing → AccessDenied.
    ```
    On real AWS, "assume-role is denied" is nearly always the missing second half.

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

> Example output - **never** treat these values as real; they are examples.

1. Temporary credentials have **three** values, including a `SessionToken`.
2. `ASIA` = temporary, `AKIA` = permanent.
3. `Expiration` is one hour away.
4. The `assumed-role` ARN carries your session name, which makes audit logs traceable to a person.

#### 30.4 Use the temporary credentials, then put your identity back

Assumed-role credentials arrive as environment variables: the course's one deliberate use of them. They sit at level 2 of Step 11's order, **bypassing the profile and its `endpoint_url`**, so pass the endpoint by hand.

```bash
cd ~/aws-floci-course

export AWS_ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId'         outputs/assumed-role.json)
export AWS_SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' outputs/assumed-role.json)
export AWS_SESSION_TOKEN=$(jq -r '.Credentials.SessionToken'        outputs/assumed-role.json)

aws sts get-caller-identity --endpoint-url http://localhost:4566 --region us-east-1
```

**Return to your normal identity - do this before continuing**

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
./scripts/utilities/whoami.sh
```

`whoami.sh` must report account `000000000000` and the `root` ARN. An assumed-role ARN means the `unset` did not run.

!!! note "Floci Limitation - assume-role always succeeds"
    `sts:AssumeRole` succeeds in Floci even without the trust policy or the user's permission, and the
    returned credentials are not enforced afterwards.

    Real AWS requires both halves of the handshake.

    Learn the **mechanics and the ARNs** here; reason about enforcement rather than observe it.

!!! success "**Checkpoint 11**"

    ```text
    Roles
    ├── usms-ec2-app-role     (trust: ec2.amazonaws.com)      + instance profile
    ├── usms-lambda-exec-role (trust: lambda.amazonaws.com)
    └── usms-developer-role   (trust: usms-dev-01)  ← assumed, temp creds obtained
    ```

---

### Step 31 - Access keys, handled safely

Create programmatic credentials for `usms-dev-01` and store them without risking a commit. See [access keys and their hygiene](../unit8/topic1.md#access-keys-and-their-hygiene).

| Credential type | Used for | Looks like |
| --- | --- | --- |
| Console password | Web console login by a human | a password |
| **Access key pair** | CLI / SDK / scripts | `AKIA...` + a 40-char secret |
| Temporary (STS) | Assumed roles, EC2 roles | `ASIA...` + secret + session token |

**The secret is shown exactly once.** Lose it and you delete the key and create a new one.

!!! danger "Before you run this"
    The next command creates a secret access key. In a real account:

    - never paste it into chat, email, a ticket, or an AI assistant,
    - never commit it,
    - never put it in a Docker image or a `.sh` file,
    - prefer roles over access keys wherever a role is possible.

    The values here are Floci dummies, but **build the habit now**.

```bash
cd ~/aws-floci-course

aws iam create-access-key --user-name usms-dev-01 \
  > outputs/usms-dev-01-access-key.json

chmod 600 outputs/usms-dev-01-access-key.json
```

- Redirecting straight to `outputs/` keeps the secret off screen, scrollback and screenshots.
- `chmod 600` makes the file readable and writable only by you.

**Verify - without exposing the secret**

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

`list-access-keys` returns the key ID, never the secret.

**Confirm Git really is protecting you**

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

The key is absent from `git status`, `git check-ignore` names the rule, and permissions are `600`. This file matches `*-access-key.json` on line 24 rather than `outputs/*` on line 8 because **Git reports the last matching pattern**. Two rules cover it deliberately, so a key saved to the wrong directory is still caught.

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

You now have `floci` (account root) and `usms-dev` (the developer); switching identity is one word.

**Key rotation - the real-world procedure**

```text
1. Create a SECOND access key   (a user may hold two - this is why)
2. Deploy the new key everywhere
3. Set the OLD key to Inactive:
     aws iam update-access-key --user-name X --access-key-id AKIA... --status Inactive
4. Wait. Watch for breakage. Reactivate instantly if something failed.
5. Only then DELETE the old key.
```

The two-key limit exists to make zero-downtime rotation possible.

---

### Step 32 - Test permissions with the policy simulator

Answer "is this user allowed to do X?" without doing X.

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::000000000000:user/usms-dev-01 \
  --action-names "ec2:CreateVpc" "iam:CreateUser" "s3:GetObject" \
  --query 'EvaluationResults[*].{Action:EvalActionName,Decision:EvalDecision}' \
  --output table
```

`simulate-principal-policy` runs the real evaluation engine against a hypothetical request and changes nothing.

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

- `allowed`: a statement permits it (`BuildNetworkingForLab02`).
- `explicitDeny`: a `Deny` blocks it (`DenyDangerousIdentityChanges`). Adding Allows will not help; fix the Deny.
- `implicitDeny`: nothing mentions it, so default deny applies. Add a permission.

!!! note "Floci Limitation - the simulator may be unsupported"
    `simulate-principal-policy` may return `UnsupportedOperation`, `InvalidAction`, or a simplified
    result on your Floci build.

    Real AWS runs the full evaluation engine.

    If it fails, treat this step as **conceptual / real AWS**: read the table above. Nothing later
    depends on the simulator running.

!!! question "**Your turn**"

    Predict - before running anything - the decision for `usms-audit-01` on `ec2:CreateVpc` and on
    `ec2:DescribeVpcs`. Write your prediction in `notes/lab-01-notes.md`, then check it. If Floci does not
    support the simulator, justify your prediction by quoting the relevant statement from the policy JSON.


### Step 33 - Save the lab state for future labs

Record every ARN Lab 2 and beyond need, snapshot the emulator, and commit.

#### 33.1 Generate `configs/lab-01.env`

```bash
cd ~/aws-floci-course

cat > configs/lab-01.env << EOF
# =====================================================================
# Lab 01 - IAM outputs
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

- This heredoc is **unquoted** (`<< EOF`) so `$(date ...)` and `$(aws ...)` run now and bake real ARNs into the file. The policy files used `<< 'EOF'` to prevent expansion. Getting this backwards fails silently.
- `Policies[?PolicyName=='X'].Arn | [0]` filters, then takes the first match as a single string.

**Check every value was filled in**

```bash
grep -n 'export .*=$\|None' configs/lab-01.env || echo "all values populated"
```

An empty value or `None` means the resource does not exist. Create it now, or Lab 2 fails confusingly.

**Verify - the whole thing works from a fresh shell**

```bash
source configs/course.env
source configs/lab-01.env
echo "EC2 role  : $USMS_ROLE_EC2"
echo "Dev policy: $USMS_POLICY_DEV_BASE"
```

#### 33.2 Take a snapshot

A snapshot lets you return here if you break something in Lab 3.

```bash
floci snapshot save lab-01-iam-complete
floci snapshot list
```

**If `floci snapshot` is unsupported on your build**, take a filesystem snapshot instead:

```bash
./scripts/setup/floci-down.sh
tar -czf ~/floci-data-lab-01.tar.gz -C ~ floci-data
./scripts/setup/floci-up.sh
ls -lh ~/floci-data-lab-01.tar.gz
```

**Stop Floci first**: archiving a live directory can capture a half-written file. To restore: stop Floci, `rm -rf ~/floci-data`, `tar -xzf ~/floci-data-lab-01.tar.gz -C ~`, start again. Keep the archive in `~`, outside the repository, so it is never a commit candidate.

#### 33.3 Write your lab notes

```bash
cat > labs/lab-01-iam/README.md << 'EOF'
# Lab 01 - IAM - completed

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
(fill this in - it is graded)
EOF
```

#### 33.4 Commit your work

```bash
git status --short
```

Confirm **no file from `outputs/` and no `.env` is listed**. Then:

```bash
git add .
git commit -q -m "feat(lab-01): IAM foundation for USMS (users, groups, policies, roles)"
git log --oneline
```

**Expected result** - three commits, in the order that matters:

```text
c3d4e5f feat(lab-01): IAM foundation for USMS (users, groups, policies, roles)
b2c3d4e feat(lab-01): environment bootstrap with durable Floci storage
a1b2c3d chore: ignore secrets before the repo can hold any
```

The oldest commit is the `.gitignore`: proof that no secret could ever have been committed.

!!! success "**Checkpoint 12 - end of Part B**"

    ```text
    IAM foundation complete and recorded
    ├── configs/lab-01.env written with all ARNs, every value populated
    ├── snapshot "lab-01-iam-complete" saved (or ~/floci-data-lab-01.tar.gz)
    ├── Lab notes written
    └── Work committed to Git, with .gitignore as the first commit
    ```

---
## 8. Verification

### 8.1 Build `scripts/utilities/verify-lab-01.sh`

It checks every artefact this lab produced, including the environment settings that make the IAM work survive.

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

Each failing label names the step to redo. Read two checks together: **`outputs/.gitkeep IS tracked`** (the Step 6 negation works) and **`access key file is IGNORED`** (the secret is safe). One passing without the other means your ignore rules are subtly wrong.

```bash
git add scripts/utilities/verify-lab-01.sh
git commit -q -m "test(lab-01): end-to-end verification script"
```

### 8.2 Build the end-of-course cleanup script

Do not run it now.

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

It demands typed confirmation and does **not** delete roles or policies automatically: destructive automation should be conservative.

---

## 9. Checkpoints

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

## 10. Troubleshooting

Each entry follows: **Cause → Diagnose → Fix → Verify**.

!!! tip "Start here"
    For missing data or unexpected Docker volumes, run `./scripts/utilities/floci-storage-check.sh`
    first. Its six checks name the cause directly.

### 10.1 `floci: command not found`

- **Cause** - the binary is not in your `PATH`.
- **Diagnose** - `ls ~/.local/bin/floci` or `which floci`.
- **Fix** -
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  ```
- **Verify** - `floci version`.

### 10.2 `Cannot connect to the Docker daemon`

- **Cause** - Docker Desktop is not started, or your user is not in the `docker` group.
- **Diagnose** - `docker info` (fails), `groups | grep docker` (empty).
- **Fix** - start Docker Desktop; on Linux:
  ```bash
  sudo systemctl start docker
  sudo usermod -aG docker $USER && newgrp docker
  ```
- **Verify** - `docker run --rm hello-world`.

### 10.3 `docker compose: 'compose' is not a docker command`

- **Cause** - Compose v2 plugin missing. `docker-compose` (with a hyphen) is the retired v1.
- **Diagnose** - `docker compose version` fails while `docker --version` works.
- **Fix** - `sudo apt-get install -y docker-compose-plugin`, or update Docker Desktop.
- **Verify** - `docker compose version` prints `v2.x`.

### 10.4 `required variable FLOCI_HOST_DATA_DIR is missing a value`

- **Cause** - you ran `docker compose` directly, so `.env` was never generated. The `:?` guard is working.
- **Fix** - `./scripts/setup/floci-up.sh`.
- **Verify** - `cat .env` shows an absolute path, and `docker compose config` succeeds.

### 10.5 `Refusing to continue` - a container named `floci` Compose did not create

- **Cause** - an earlier `floci start`. That container has no durable storage; adopting it would lose data.
- **Diagnose** -
  ```bash
{% raw %}  docker container inspect floci --format '{{ index .Config.Labels "com.docker.compose.project" }}'{% endraw %}
  ```
  Empty output means Compose did not create it.
- **Fix** -
  ```bash
  floci stop --remove        # or: docker rm -f floci
  ./scripts/setup/floci-up.sh
  ```
- **Verify** - the script reaches `Verified /app/data -> ...`.

### 10.6 `Bind for 0.0.0.0:4566 failed: port is already allocated`

- **Cause** - an old Floci container, LocalStack, or another process holds the port.
- **Diagnose** -
  ```bash
  docker ps --filter publish=4566
  sudo lsof -i :4566
  ```
- **Fix** - stop the other container, or change **both** the `ports:` line in `docker-compose.yml`
  and `FLOCI_ENDPOINT` in `configs/course.env`, then update the profile:
  ```bash
  aws configure set endpoint_url http://localhost:4599 --profile floci
  ```
- **Verify** - `./scripts/setup/floci-up.sh` completes.

### 10.7 `Could not connect to the endpoint URL: "http://localhost:4566/"`

- **Cause** - Floci is not running, crashed, or is on a different port.
- **Diagnose** -
  ```bash
  docker compose ps
  docker compose logs --tail 50 floci
  curl -sv http://localhost:4566 2>&1 | head -5
  ```
- **Fix** - `./scripts/setup/floci-up.sh`.
- **Verify** - `aws sts get-caller-identity`.

### 10.8 Commands hang, then fail with a timeout - and the URL says `amazonaws.com`

- **Cause** - `endpoint_url` is missing, or your CLI is older than 2.13 and ignores it. The CLI is trying to reach **real AWS**.
- **Diagnose** -
  ```bash
  aws --version
  aws configure get endpoint_url --profile floci      # should print the localhost URL
  aws sts get-caller-identity --debug 2>&1 | grep -m1 "'url'"
  ```
- **Fix** - upgrade to 2.13+, set the profile value again, or fall back to the environment variable:
  ```bash
  aws configure set endpoint_url http://localhost:4566 --profile floci
  # last resort, if your CLI ignores the profile setting:
  export AWS_ENDPOINT_URL=http://localhost:4566
  ```
- **Verify** - the debug line now shows `localhost:4566`.

### 10.9 `Unable to locate credentials`

- **Cause** - no profile, wrong profile name, or `AWS_PROFILE` points at a missing profile.
- **Diagnose** -
  ```bash
  echo "AWS_PROFILE=$AWS_PROFILE"
  aws configure list-profiles
  aws configure list --profile floci
  ```
- **Fix** - redo Step 12, or `source configs/course.env`.
- **Verify** - `./scripts/utilities/whoami.sh`.

### 10.10 `The config profile (floci) could not be found`

- **Cause** - the header in `~/.aws/config` is `[floci]` instead of `[profile floci]`.
- **Diagnose** - `cat ~/.aws/config`.
- **Fix** - use `aws configure set ... --profile floci`, which writes the right headers. By hand:
  `~/.aws/config` needs `[profile NAME]`, `~/.aws/credentials` needs `[NAME]`.
- **Verify** - `aws configure list --profile floci`.

### 10.11 `MalformedPolicyDocument` / `Invalid JSON`

- **Cause** - a trailing comma, a missing bracket, or smart quotes pasted from a PDF or web page.
- **Diagnose** -
  ```bash
  python3 -m json.tool policies/usms-developer-base-policy.json
  ```
  It reports the exact line and column.
- **Fix** - correct the JSON. Common culprits:
  - trailing comma after the last array element,
  - `"` replaced by `“` `”` (curly quotes) after copy-paste,
  - `Version` written as anything other than `"2012-10-17"`.
- **Verify** - re-run the validator, then re-run `create-policy`.

### 10.12 `EntityAlreadyExists`

- **Cause** - you ran a `create-*` command twice.
- **Diagnose** - `aws iam get-user --user-name usms-dev-01` (it exists).
- **Fix** - usually harmless: continue. To recreate, delete first (10.16 gives the dependency order).
- **Verify** - `aws iam list-users`.

### 10.13 `NoSuchEntity`

- **Cause** - a typo, a resource never created, or **a resource lost in a restart** (10.17).
- **Diagnose** -
  ```bash
  aws iam list-policies --scope Local --query 'Policies[*].PolicyName' --output text
  aws iam list-roles --query 'Roles[*].RoleName' --output text
  ```
- **Fix** - correct the name. Watch `usms-developers` (plural) vs `usms-developer-role` (singular), and twelve zeros in `000000000000`.
- **Verify** - re-run the failing command.

### 10.14 `${aws:username}` came out empty in the policy file

- **Cause** - `<< EOF` instead of `<< 'EOF'`, so **your shell** expanded it.
- **Diagnose** - `grep 'aws:username' policies/usms-self-manage-credentials.json`. No match = expanded.
- **Fix** - rewrite the file with `<< 'EOF'`, then re-run `put-user-policy` (it overwrites).
- **Verify** - `aws iam get-user-policy --user-name usms-dev-01 --policy-name USMSSelfManageCredentials`
  and confirm the variable is present in the document.

### 10.15 `AccessDenied` on `sts:AssumeRole`

- **Cause** - only one half of the handshake is in place.
- **Diagnose** -
  ```bash
  # half 1: does the role trust the caller?
  aws iam get-role --role-name usms-developer-role \
    --query 'Role.AssumeRolePolicyDocument'
  # half 2: may the caller call AssumeRole?
  aws iam list-attached-group-policies --group-name usms-developers
  ```
- **Fix** - add the missing side (Step 30.1 or 30.2).
- **Verify** - `aws sts assume-role ...` returns credentials.
- **Note** - unlikely in Floci, which does not enforce policies by default. You will need the diagnosis on real AWS.

### 10.16 `DeleteConflict` when deleting an IAM entity

- **Cause** - IAM refuses to delete something with dependents.
- **Diagnose** - the error message names the dependency.
- **Fix** - remove dependents in this order:
  ```text
  user   → remove from groups → delete access keys → delete inline policies
           → detach managed policies → delete user
  group  → remove all users → detach policies → delete group
  role   → remove from instance profiles → detach policies
           → delete inline policies → delete role
  policy → detach from ALL identities → delete non-default versions → delete policy
  ```
- **Verify** - re-run the delete.

### 10.17 Floci lost all my resources after a restart

Three distinct causes, three different fixes.

- **Diagnose first** -
  ```bash
  ./scripts/utilities/floci-storage-check.sh
  ```
- **Cause A - storage mode is `memory`** (check 2). Floci's default; nothing survives, and Floci deletes its own volumes on teardown.
  **Fix:** `FLOCI_STORAGE_MODE="hybrid"` in `configs/course.env`, then `./scripts/setup/floci-up.sh`.
- **Cause B - `/app/data` is not a host bind mount, or the wrong path** (check 3). Usually a literal `~`, which nothing expands, so Docker creates a directory named `~`.
  **Fix:** make `FLOCI_HOST_DATA_DIR` absolute and re-run the start script. Look for the stray directory with `ls -la ~/aws-floci-course` and remove it.
- **Cause C - the container was started by `floci start`, not Compose** (check 1).
  **Fix:** `floci stop --remove && ./scripts/setup/floci-up.sh`.
- **Recover the data** - if you took a snapshot in Step 33:
  ```bash
  floci snapshot load lab-01-iam-complete
  # or, for the tar fallback:
  ./scripts/setup/floci-down.sh
  rm -rf ~/floci-data && tar -xzf ~/floci-data-lab-01.tar.gz -C ~
  ./scripts/setup/floci-up.sh
  ```
  With no snapshot, re-run Steps 18–33.
- **Verify** - `./scripts/utilities/verify-lab-01.sh` prints `FAIL=0`.

### 10.18 `outputs/.gitkeep` is missing from Git, or a secret got staged

- **Cause** - `.gitignore` says `outputs/` instead of `outputs/*`; Git cannot re-include a file under an excluded directory.
- **Diagnose** -
  ```bash
  git ls-files outputs/          # should list outputs/.gitkeep
  git check-ignore -v outputs/usms-dev-01-access-key.json
  ```
- **Fix** - change the line to `outputs/*` (Step 6.1), then `git add outputs/.gitkeep`.
- **If a secret was already committed** - it stays in history. On a Floci-only repo the credential is worthless, so restart the history:
  ```bash
  rm -rf .git && git init -q && git add . && git commit -q -m "chore: restart history without secrets"
  ```
  On a real project, rotate the key immediately and rewrite history with `git filter-repo`.
- **Verify** - `./scripts/utilities/verify-lab-01.sh` passes its two Git-hygiene checks.

### 10.19 Shell errors: `command not found`, `unexpected token`, empty variable

| Symptom | Cause | Fix |
| --- | --- | --- |
| `VPC_ID: command not found` | You wrote `VAR = value` with spaces | `VAR=value` - no spaces around `=` |
| `unexpected end of file` | A `\` line continuation has a trailing space, or a heredoc `EOF` is indented | Remove the space; put `EOF` at column 1 |
| `$MY_VAR` is empty | You opened a new terminal, or the capturing command failed | `echo $MY_VAR` to confirm; re-run the capture, or `source configs/lab-01.env` |
| `file://policy.json` → `Unable to load paramfile` | You are in the wrong directory | `pwd`, then `cd` to `policies/`, or use an absolute `file:///home/...` path |
| `permission denied: ./scripts/...` | The script is not executable | `chmod +x scripts/setup/*.sh scripts/utilities/*.sh scripts/cleanup/*.sh` |

---

## 11. Floci vs Real AWS

### 11.1 What is genuinely the same

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

### 11.2 What differs

| Feature | Real AWS | Floci | Status |
| --- | --- | --- | --- |
| **IAM authorization** | Every request evaluated; `AccessDenied` returned | Any non-empty credentials accepted; requests not authorized against your policies by default | **Floci Limitation** |
| Credential signature check | Cryptographically verified | Not verified by default | **Floci Limitation** |
| **Durability by default** | Your account is permanent | Defaults to `memory` - state is discarded unless you configure otherwise | **Floci Limitation** (Part A configures around it) |
| Account ID | Your real 12-digit account | Fixed `000000000000` | Cosmetic |
| Console / web UI | Full graphical console | None - CLI/API only | **Floci Limitation** |
| Root user & MFA | Real, must be protected with MFA | No console, MFA meaningless | Conceptual / Real AWS |
| AWS managed policies | 1,000+ maintained by AWS | A subset | **Floci Limitation** |
| `simulate-principal-policy` | Full evaluation engine | May be unsupported/simplified | **Floci Limitation** |
| Permission boundaries, SCPs, Access Analyzer | Available | Not meaningfully enforced | Conceptual / Real AWS |
| CloudTrail audit of IAM calls | Every call logged | Not equivalent | Conceptual / Real AWS |
| IAM propagation delay | Eventually consistent - changes can take seconds | Immediate | **Floci is nicer** - beware on real AWS |
| Cost | IAM free; mistakes elsewhere cost money | Free | **Floci is nicer** |

!!! danger "The one thing you must carry into real AWS"
    Because Floci does not deny you, **you will not feel the consequences of an over-permissive
    policy.** A policy of `{"Effect":"Allow","Action":"*","Resource":"*"}` behaves identically to a
    carefully scoped one here. On real AWS the first is a severe security finding.

    Judge your policies by reading them, not by whether the command succeeded.

**Observable here versus conceptual:** users, groups, tags, managed and inline policies, versions, roles, instance profiles, access key mechanics, `sts assume-role` and storage durability all behave as shown. Policy enforcement (allow, explicit and implicit deny), MFA, permission boundaries, SCPs, Access Analyzer and CloudTrail are real-AWS only.

---

## 12. Independent Lab Exercises

No full solutions are given. Record commands and output in `labs/lab-01-iam/exercises.md`.

### Exercise 1 - The QA identity

**Requirements:** create group `usms-qa` and user `usms-qa-01` inside it, tagged `Key=Role,Value=QA` and `Key=Project,Value=USMS`. Attach the existing `USMSDeveloperBase` to the group; do **not** create a new policy.

**Constraints**

- Capture the user's ARN into a shell variable using `--query` and `--output text`.
- Do not attach any policy directly to the user.

**Expected outcome**

```text
aws iam get-group --group-name usms-qa   →  shows usms-qa-01
aws iam list-attached-group-policies --group-name usms-qa  →  shows USMSDeveloperBase
aws iam list-attached-user-policies --user-name usms-qa-01 →  empty list
```

**Hints:** `create-group`, `create-user`, `add-user-to-group`, `attach-group-policy`, all in Steps 18–22.

### Exercise 2 - The read-only reporting policy

**Requirements:** the USMS reporting service must read transcripts but never modify or delete them. Write a customer managed policy `USMSReportingReadOnly` that allows:

- listing the `usms-student-data` bucket,
- reading objects **only** under the prefix `transcripts/`,

and explicitly denies every `s3:Put*` and `s3:Delete*` action on that bucket.

**Constraints**

- The document lives in `policies/usms-reporting-readonly-policy.json` and is committed.
- At least one `Sid` per statement.
- Validate the JSON locally before `create-policy`.

**Expected outcome**

```text
aws iam list-policies --scope Local --query "Policies[?PolicyName=='USMSReportingReadOnly']"
  → returns one policy with an ARN
```

**Hints**

- The prefix restriction goes in the Resource ARN: `arn:aws:s3:::usms-student-data/transcripts/*`.
- Step 23's bucket-ARN vs object-ARN distinction: you need both.
- Explicit `Deny` keeps the policy safe even if a broader one is attached later.

### Exercise 3 - Problem solving: the third-party analytics role

**Scenario:** a partner university's analytics service must read USMS reports for **at most 30 minutes at a time**, by assuming a role (no IAM user in your account).

**Requirements:** create `usms-analytics-partner-role` that:

1. can be assumed by `arn:aws:iam::000000000000:user/usms-audit-01`,
2. cannot hold a session longer than 30 minutes,
3. can read objects under `arn:aws:s3:::usms-student-data/reports/*` and nothing else,
4. is tagged `Key=Project,Value=USMS` and `Key=External,Value=true`.

Then obtain temporary credentials and record the `Expiration` you receive.

**Constraints**

- Both halves of the trust handshake in place (Step 30).
- Trust policy and permissions policy are separate files in `policies/`.

**Expected outcome**

```text
aws iam get-role --role-name usms-analytics-partner-role
  → MaxSessionDuration is 1800
  → AssumeRolePolicyDocument names usms-audit-01

aws sts assume-role ... → Credentials.Expiration is ~30 minutes ahead
```

**Hints**

- 30 minutes in seconds is the `--max-session-duration` value.
- Research the `sts:ExternalId` condition used for real third-party access, and say in your notes whether you should add one here.

### Exercise 4 - Challenge: design a least-privilege policy from a job description

**The brief**

> "The USMS **backup operator** runs a nightly job. It must copy every object out of the student data
> bucket into a separate archive bucket `usms-archive`, verify what it copied, and write a completion
> log line to CloudWatch Logs. It must never be able to delete anything, never read IAM, and it must
> only ever run in `us-east-1`."

**Requirements**

1. Decide: user, group, or role? Justify it in one paragraph in `notes/lab-01-notes.md`.
2. Write the policy document(s). Determine the exact action list yourself; no wildcards on write actions.
3. Create the identity and attach the policy.
4. Add a `Condition` enforcing the region restriction.
5. List in your notes three ways your policy could still be abused, and how you would close each gap.

**Constraints**

- No `"Action": "*"` and no `"Resource": "*"` on any Allow statement.
- Maximum of four statements.

**Hints**

- `aws s3api help` and `aws logs help` list exact action names (`s3:CopyObject` does not exist; find out what a copy actually calls).
- What permission does "verify what it copied" need, on **which** bucket?
- The condition key is `aws:RequestedRegion`.

### Exercise 5 - Integration: prepare the identity Lab 2 will use

**Requirements**

1. Using `simulate-principal-policy` (or by reading the policy JSON if Floci does not support it), determine whether `usms-dev-01` has **every** permission Lab 2 needs:
   `ec2:CreateVpc`, `ec2:CreateSubnet`, `ec2:CreateInternetGateway`, `ec2:AttachInternetGateway`,
   `ec2:CreateRouteTable`, `ec2:CreateRoute`, `ec2:AssociateRouteTable`,
   `ec2:DescribeAvailabilityZones`, `ec2:ModifyVpcAttribute`, `ec2:CreateNatGateway`,
   `ec2:AllocateAddress`.
2. Identify which are **missing**.
3. Create **version 3** of `USMSDeveloperBase` adding exactly the missing actions.
4. Set v3 as default and verify v1 and v2 still exist.
5. Add `USMS_VPC_CIDR=10.0.0.0/16` to `configs/lab-01.env` so Lab 2 can source it.

**Constraints**

- Do not delete or recreate the policy. Use `create-policy-version`.
- Do not add any action that is not on the list above.

**Expected outcome**

```text
aws iam list-policy-versions --policy-arn <USMSDeveloperBase arn> --output table
  → v1 (False), v2 (False), v3 (True)
```

**Hints**

- Step 27 shows the version workflow, including the Python edit.
- Two actions are genuinely missing from v2. Find them by reading, not guessing.
- Why does a NAT gateway need `ec2:AllocateAddress`?
- `verify-lab-01.sh` checks for `v2` and will now report one failure: update the check to `v3` and say so in your notes.

---

## 13. Lab Assessment Checklist

Tick each box and submit it with your lab report.

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

IAM - IDENTITIES
☐ 3 groups created (usms-admins, usms-developers, usms-auditors)
☐ 3 users created and tagged
☐ Each user placed in the correct group
☐ Membership verified from BOTH directions

IAM - POLICIES
☐ AWS managed policy (or local equivalent) attached to auditors
☐ USMSDeveloperBase written, validated locally, created, attached to 2 groups
☐ USMSStudentDataReadWrite written with correct bucket AND object ARNs
☐ Inline policy USMSSelfManageCredentials on usms-dev-01
☐ Explained the difference between attached and inline in your notes
☐ Policy version v2 created and set as default
☐ Confirmed v1 still exists and could be rolled back to

IAM - ROLES
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

## 14. Review Questions

Answer in prose in `notes/lab-01-notes.md`; do not paste command output.

1. **Trust vs permissions.** A role has a perfect permissions policy, but nobody can use it. What is almost certainly missing, and why does IAM separate the two documents?
2. **Explicit vs implicit deny.** `usms-dev-01` gets `AccessDenied` on `iam:CreateUser` and on `dynamodb:PutItem`. How do the two failures differ internally, how would you tell them apart, and why is the fix different?
3. **Roles over keys.** Give two distinct reasons attaching `usms-ec2-app-role` to the server is more secure than putting `usms-dev-01`'s access key in the application's configuration file.
4. **The S3 ARN trap.** A policy allows `s3:GetObject` and `s3:ListBucket` on the single resource `arn:aws:s3:::usms-student-data`. Downloads fail. Why, and what must the `Resource` values be?
5. **The Floci illusion.** Every command succeeded. Why is that not evidence your policies are correct? Describe two techniques for gaining confidence in a policy before deploying it to real AWS.
6. **The persistence trap.** A classmate ran `floci start --persist ~/floci-data --detach`, saw the directory appear, and lost their IAM users the next morning. Give the three independent reasons, and the single test that would have caught it in under a minute.
7. **Configuration as evidence.** In one paragraph, argue why a committed `docker-compose.yml` is a security and reproducibility property, not a convenience. What can a colleague verify from your repository that they could not verify from a command you typed?

---

## 15. KEEP vs CLEAN UP

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

!!! danger "Read before running any delete command"
    **What will be deleted:** the expired temporary-credentials file, and the practice user
    `usms-intern-01`.
    **What depends on it:** nothing in this lab or any future lab.
    **Reversible?** The file: no, but it is expired and worthless. The user: yes - recreate it in
    seconds.
    **Effect on later labs:** none.

    Do **not** run any other `delete-*` command in this lab. Everything else is required by Lab 2+.

```bash
rm -f ~/aws-floci-course/outputs/assumed-role.json

# only if you created it:
aws iam remove-user-from-group --group-name usms-auditors --user-name usms-intern-01 2>/dev/null
aws iam delete-user --user-name usms-intern-01 2>/dev/null
```

IAM refuses to delete a user who is still a group member (`DeleteConflict`), so dependencies go inside-out. Do **not** run `scripts/cleanup/lab-01-cleanup.sh`; it is for the end of the course.

<!-- 
### Cumulative architecture after Lab 1

```text
┌────────────────────────────────────────────────────────────────┐
│                    USMS - AWS Account 000000000000             │
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
-->

---

## 16. Preparation for the Next Lab

Lab 2 (VPC) builds the USMS network while holding `usms-developer-role`, and sources `configs/course.env` and `configs/lab-01.env`. Step 33 already saved your snapshot.

<!--
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

**You may stop Floci with `./scripts/setup/floci-down.sh`.**

<!-- 
---

## Appendix - New CLI and JMESPath patterns

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

<!-- ## Appendix C - What changed from the previous edition of this lab

If you are returning to this lab after starting the earlier version, this is what moved and why.

| Change | Reason |
| --- | --- |
| Directory structure and `.gitignore` moved from Steps 11–12 to Steps 5–6, before Floci starts | The emulator's configuration is now a committed file, and no secret can exist before the ignore rules do |
| `git init` moved from Step 28 to Step 6 | A repository created after a credential exists has already lost the argument |
| `.gitignore` uses `outputs/*`, not `outputs/` | Git cannot re-include a file whose parent directory is excluded, so `!outputs/.gitkeep` silently did nothing |
| `floci start --persist` replaced by `docker-compose.yml` | `--persist` does not set `FLOCI_STORAGE_MODE`, does not cover sidecar services, and its flags are forgotten on every restart |
| New Step 7 explaining storage modes | The failure was invisible; students needed the concept before the command |
| New `floci-storage-check.sh` | Turns a mysterious data loss into a named cause in six checks |
| Step 14 persistence proof rewritten | The old proof (root ARN unchanged after restart) passes even in `memory` mode with no disk at all - it proved nothing |
| Sidecar ports commented out by default | ~600 published ports made Docker Desktop crawl and caused port-collision failures on shared machines |
| `verify-lab-01.sh` now checks configuration, not just existence | A lab that verifies only "the user exists" passes right up until the restart that deletes them |
| Snapshot step gained a `tar` fallback | `floci snapshot` is not available on every build |
| Steps renumbered: Part A is 1–15, Part B is 16–33 | Consequence of the reordering above | -->

!!! success "End of Lab 01"
    **Next:** Lab 02 - VPC. Your environment is now durable: stop it or leave it running, the IAM
    foundation you just built will still be there.

# Project Implementation Checkpoint 1

*Assessed submission. Set at Practical 8. Weighting and deadline in Section 7.*

---

## 1. What this checkpoint is for

You have built, over eight practicals, a partial implementation of USMS - the University Student
Management System. Every student has built the same labs, from the same documents, against the same
emulator. So this checkpoint is not marked on how much exists.

It is marked on three things:

1. **That it is one system rather than eight exercises.** The resources reference each other. A role
   created in Practical 1 is carried by a function created in Practical 6 and emits metrics defined
   in Practical 8. You can show that chain running.
2. **That you can demonstrate it, not just list it.** One path, end to end, reproducible from a
   command, in front of someone.
3. **That you know what is not true.** Which parts you observed working, which parts the emulator
   stores without executing, and which parts exist only as a document. A student who says
   "everything works" has either not looked or is not telling the truth, and both cost more marks
   than an honest gap.

That third point is the one this course keeps returning to, and it is worth restating in the form it
takes here: **a command that appears to succeed is not evidence that it did what you meant.** Your
submission is assessed on the evidence you present for your claims, not on the claims.

---

## 2. Scope - what must be in the system by this checkpoint

Everything built in Practicals 1 to 8. Every student builds the same system, in the same order.

| Layer | Must exist | From |
| --- | --- | --- |
| Identity | 3 groups, 3 users, at least 4 roles, at least 6 customer managed policies, 1 instance profile | Practicals 1, 8 |
| Network | `usms-vpc`, 4 subnets across 2 AZs, IGW, NAT, route tables, 2+ security groups, the S3 gateway endpoint | Practical 2 |
| Compute | `usms-web-01` and `usms-db-01`; **and** the ECS service behind its load balancer; **and** the EKS cluster and its workloads | Practicals 3, 4, 5 |
| Storage | `usms-student-data` with objects under `transcripts/` and an event notification | Practical 6 |
| Functions | 3 Lambda functions; the notifier with at least 3 versions and an alias | Practicals 6, 8 |
| Pipeline | `usms-enrolment-pipeline` (Source, Build, Deploy), an ECR repository, and at least one deployment that went through it | Practical 7 |
| Observability | 3+ log groups all with retention, 2 metric filters, 5 metrics, 3 alarms including a composite, 1 dashboard, X-Ray documents | Practical 8 |
| Repository | One Git repository, `.gitignore` as its first commit, one `configs/lab-NN.env` per practical, one verify script per practical, no tracked secrets | All |

If a resource is genuinely absent because your build does not support the service, that is a
`gaps.md` entry with evidence, not a lost mark. If it is absent because the practical was not
completed, say so there too - an accurate gap list is worth more than an optimistic one, and the
assessor will run your verify scripts.

---

## 3. Deliverables

Five files, all committed, all under `project/checkpoint-01/`. Appendix C of Lab 13 has the commands
that generate three of them.

### 3.1 `architecture.md` - two to three pages

Not a list of resources; `inventory.txt` is the list. This is the argument.

It must contain:

- **One diagram** of the whole system as it stands, in a ` ```text ` fence. Hand-drawn ASCII is
  expected and adapting the diagrams from the lab documents is fine and sensible. What is assessed is
  whether the **edges** are right - what references what.
- **The dependency narrative.** Pick the three most interesting dependencies in your system and
  explain each in a paragraph: what was created first, what consumed it later, and what would break
  if the earlier thing changed. `USMSStudentDataReadWrite` naming a bucket that did not exist for
  five practicals is one obvious candidate; the `live` alias that S3 points at and that Practical 8
  repointed is another.
- **One design decision you would now make differently**, with your reasoning. Not a mistake you
  made - a decision the labs made for you that you have since understood well enough to disagree
  with. There are several defensible answers.
- **The trust boundary.** Name every place in your system where one component is allowed to act on
  another, and say what grants it. There are more of these than students expect: an instance profile,
  a trust policy, a resource policy on a function, a bucket notification, a metric filter's implicit
  dependence on a log line's format.

### 3.2 `inventory.txt` - generated, not written

Produced by `scripts/utilities/usms-project-inventory.sh`, which Lab 13 Appendix C builds. Regenerate
it immediately before you submit. An inventory dated three weeks before the deadline is evidence of
nothing.

### 3.3 `evidence/` - at least four files

| File | Content |
| --- | --- |
| `end-to-end.txt` | The nine-stage demonstration from Lab 13 Appendix C.4, captured verbatim |
| `verify-lab-10.txt` | Full output of `verify-lab-10.sh`, not just the last line |
| `verify-lab-13.txt` | Full output of `verify-lab-13.sh` |
| `telemetry-inventory.txt` | `outputs/lab-13-telemetry-inventory.txt` |

Add any other verify script output you want to rely on. Text and small JSON only - no screenshots,
no archives, no binaries. A screenshot that genuinely helps goes in `screenshots/` and is linked from
`demo.md`.

### 3.4 `gaps.md` - one to two pages

The honest part, and the one that separates the top band from the middle.

Three sections:

- **Observed, recorded, unavailable.** Take the three-category scheme from Section 12.2 of any lab
  document and apply it to your whole system. What did you watch work? What is correctly configured
  but never executed by the emulator? What cannot exist locally at all?
- **Known failures.** Every check that currently fails in any verify script, with the reason and
  the evidence that the underlying configuration is nonetheless correct. "Metric filters are not
  evaluated on my build; here is `test-metric-filter` showing the pattern matches" is a complete
  answer.
- **What I would build next, and why that order.** Three items, ranked, with one sentence each on
  what makes the first one first. "Because it is the next practical" is not a reason.

### 3.5 `demo.md` - one page

The script for your eight minutes in Section 6. Which commands, in which order, and - for each - the
one sentence you will say while it runs. Writing this down is most of what makes a demonstration go
well, and an unprepared demonstration is visible within about forty seconds.

---

## 4. What is explicitly not required

So that nobody spends a weekend on the wrong thing:

- **No new AWS services.** Building something no practical covered earns no marks here and will
  complicate your final submission.
- **No slides.** The documents above are the submission.
- **No prose description of every resource.** That is what `inventory.txt` is for.
- **No screenshots of green ticks.** Text output that can be re-run is worth more than a picture of
  output that cannot.
- **No fixing the emulator.** If your build does not implement a service, say so and move on. Several
  of the most interesting `gaps.md` entries are of exactly this kind.

---

## 5. Marking rubric - 100 marks

| # | Criterion | Marks | What the top band looks like |
| --- | --- | --- | --- |
| 1 | **System completeness** | 20 | Every row of Section 2 present, or absent with an evidenced reason. `inventory.txt` regenerated and consistent with what the assessor finds when they run it themselves |
| 2 | **Cumulative integration** | 20 | Resources genuinely reference each other. The three dependencies in `architecture.md` are real, correctly described, and the consequences of changing them are right. No parallel-universe duplicates with slightly different names |
| 3 | **End-to-end demonstration** | 15 | `end-to-end.txt` runs clean and covers identity → storage → trigger → compute → logs → metrics → alarms → dashboard. The live demonstration matches the captured file |
| 4 | **Verification** | 15 | A verify script per practical, each checking **configuration** as well as existence. Failures are known, explained, and evidenced. A student who added their own checks beyond the lab's is in this band |
| 5 | **Honesty and gap analysis** | 15 | `gaps.md` distinguishes observed from recorded from unavailable, correctly, across the whole system. Nothing is claimed that the evidence does not support. Known failures are surfaced rather than found by the assessor |
| 6 | **Design judgement** | 10 | The "differently" section in `architecture.md` shows understanding rather than hindsight. The trust-boundary list is complete and the student knows what grants each one |
| 7 | **Repository and security hygiene** | 5 | No tracked secret anywhere in history. `.gitignore` intact and demonstrably working. Meaningful commit messages. `project/` committed, `outputs/` not |

**Automatic deductions**, because they are the ones that matter in a real job:

| Deduction | For |
| --- | --- |
| −15 | Any credential, key or secret committed at any point in the repository's history |
| −10 | A claim in `architecture.md` or `gaps.md` that the submitted evidence contradicts |
| −5 | `inventory.txt` not regenerated within a week of submission |

A secret in history is not fixed by deleting the file in a later commit. If you find one, say so in
`gaps.md` and explain what you would do about it; an honest disclosure is assessed far more gently
than a discovery.

---

## 6. The demonstration - eight minutes

In the practical session. Your own machine, your own repository, Floci running.

| Minutes | What |
| --- | --- |
| 0–1 | `usms-project-inventory.sh`. Talk over it |
| 1–4 | The nine-stage end-to-end path. Run it live; do not read from the captured file |
| 4–6 | One thing you understand well. Your choice. Two good options: walk the `live` alias from version 1 to 3 and back, showing that nothing else is reconfigured; or force `usms-transcript-lag-high` into `ALARM` and show the history |
| 6–8 | Questions |

Two questions everybody is asked:

- *Show me something in your system that does not work, and tell me how you know.*
- *If I changed one thing to break this, what would you have me change?*

Both are answerable from `gaps.md` if you wrote it properly. Neither is answerable by improvising.

One practical warning: run the end-to-end path once, in the room, before your slot. A stale
`XSTART`/`XEND` window or a Floci container that went to sleep overnight is the most common reason a
demonstration that worked last night does not work now.

---

## 7. Submission

| | |
| --- | --- |
| **Format** | A Git bundle or an archive of the repository, **excluding** `outputs/` and `.git` hooks, plus the commit hash you want marked |
| **Must contain** | `project/checkpoint-01/` with all five deliverables, every `configs/lab-NN.env`, every verify and cleanup script, all lab documents |
| **Must not contain** | Anything under `outputs/`, the root `.env`, any `.zip` or `__pycache__`, any credential in any commit |
| **Weighting** | As stated in the module descriptor for the continuous-assessment component |
| **Deadline** | End of the week following Practical 8; confirm the exact date and time with your tutor, and do not rely on this document for it |

Before you submit:

```bash
cd ~/aws-floci-course

./scripts/utilities/usms-project-inventory.sh | tee project/checkpoint-01/inventory.txt

git ls-files outputs/            # must show .gitkeep and nothing else
git ls-files project/            # must show all five deliverables
git log --oneline | head -20
git status --short               # must be clean

git log --all --pretty=format: --name-only --diff-filter=A \
  | sort -u | grep -E '^outputs/' | grep -v '.gitkeep' \
  && echo "STOP: a file under outputs/ was committed at some point" \
  || echo "no outputs/ file has ever been committed"
```

That last command is the only one on this page that looks at **history** rather than at the current
tree, and it is the one that catches the thing that costs fifteen marks.

---

## 8. Frequently asked, before they are asked

**The S3 configuration lab has not been delivered.** Correct, and Lab 13 Section 4.1 explains why.
It was never assigned a Practical slot - Practical 7 is the CI/CD pipeline (Labs 11 and 12), which
was delivered and is in Section 2's scope. Nothing in this checkpoint requires the S3 lab. Your
bucket exists with objects and a notification, which is what Section 2 asks for. If you want an easy
`gaps.md` entry, the un-applied bucket policy draft from Lab 09 is one.

**Several verify checks fail because my build does not support the service.** Expected, and it is
worth marks to handle it well. Criterion 5 is where those marks are.

**Can I fix a lab I did badly at the time?** Yes, and you should - the checkpoint assesses the system
as it stands, not as it was built. Commit the fix with a message saying what it corrects.

**How much of this is writing?** About five to six pages total across four documents, plus generated
output. If you are writing more than eight pages you are describing rather than arguing.

**My repository has no commits from Practical 1 because I started committing later.** Say so in
`gaps.md`. Criterion 7 is five marks and honesty about the history costs less than the appearance of
one that was reconstructed.

---

*Checkpoint 1 assesses the system you have. Checkpoint 2, later in the module, will assess what you
did with the knowledge that it was incomplete.*
# teachprep: Refine a Unit and Build Its Lecture Lessons

**Trigger:** `teachprep unit<N>` plus optional keywords that choose what to do.

| You type | Notes refined (Phase 1) | Lesson + quiz bank (Phases 2–3) |
|---|---|---|
| `teachprep unit5` | All topics | All topics |
| `teachprep unit5 lesson topic1` | All topics | Topic 1 only |
| `teachprep unit5 lesson topic1 topic3` | All topics | Topics 1 and 3 |
| `teachprep unit5 topic1` | Topic 1 only | Topic 1 only |
| `teachprep unit5 notes` | All topics | None |
| `teachprep unit5 notes topic2` | Topic 2 only | None |
| `teachprep unit5 lessons-only` | None | All topics |
| `teachprep unit5 lessons-only topic1` | None | Topic 1 only |
| add `refresh` to any of the above | Redo even if already done | Redo even if already done |

Rules for reading the command:

- **`lesson`** limits only the lesson plans and quiz banks to the listed topics; the notes still cover the whole unit.
- **`topic<M>` without `lesson` or `notes`** limits everything to those topics.
- **`notes`** means notes only: no lessons, no quizzes.
- **`lessons-only`** means no note refinement. If a topic's notes are not refined yet, warn the user, since the lesson will link to unrefined notes, and ask whether to continue.
- **A quiz bank is always made together with its lesson,** never separately.
- **Plain English is fine** (for example "teachprep unit 5, format the whole unit but only make a lesson for topic 1"). Map it onto the table, state your reading back to the user and ask if it is ambiguous.

**Already-done work is skipped.** Notes that are already refined are not trimmed again, and existing lesson plans and quiz banks are not overwritten (see "Skip what is already done" below). `refresh` overrides this.

When a user types the trigger, any AI agent working in this repository follows this file from top to bottom. Within the scope the command selects, it produces:

1. **Refined notes:** every topic trimmed, de-duplicated, sequential, student friendly and up to date.
2. **One 2-hour lecture lesson plan per topic** in the teaching area.
3. **One quiz file per topic** (`*.questions.md`) in ClassLegend's import format, in a folder that is never committed.

Read alongside:

| File | What it governs |
|---|---|
| `CLAUDE.md` (or `AGENTS.md`) Part II | Unit-notes content rules, section list, ownership map across units |
| `CLAUDE.md` Part I §5 | The Floci environment contract for CLI work (scripts, `course.env`, forbidden commands) |
| `lesson-templates/README.md` | Lesson-plan format: timed segments, block types, notes links, checks |
| `docs/unit3/topic1.md` | Style reference for refined notes |
| `docs/teach-5t27uuv8/unit3-topic1-lecture.md` | Worked example of a lesson plan |
| `private/classlegend-quiz-template.md` | ClassLegend quiz import format (local only, never committed) |

---

## Audience and tone

- **Students:** 4th-year Software Engineering undergraduates. Strong programmers who know OOP, databases, networks, operating systems and basic design patterns. They are learning, **not preparing for any AWS certification**.
- **Notes:** concise but informative. Explain why before how. Professional language, no emojis.
- **Lessons:** engaging. Use analogies where a concept is abstract, and say where the analogy stops being accurate. Give proper explanations, not lists of commands.

---

## Phase 0: Preflight (do not skip)

1. Confirm `docs/unit<N>/` exists. If not, stop and ask.
2. List the unit's topics from `mkdocs.yml` nav and `docs/unit<N>/overview.md`.
3. Run `git status`. If a file you are about to change has uncommitted edits, **work from its current content** and tell the user. Re-check just before overwriting, in case the user is editing it at the same time (the repo syncs through OneDrive).
4. **Back up** every file you will change to a scratch location outside the repository.
5. Check `private/classlegend-quiz-template.md` exists. If it does not, finish Phases 1–2, skip Phase 3, and ask the user for the template.
6. Check `.gitignore` contains `private/`. If not, add it before writing any quiz file.
7. **Work out what is already done** (next section) and tell the user the plan per topic before starting, for example "5.1 notes already refined, lesson only; 5.2 full run".
8. **Ask the user before starting** if anything is unclear: missing topics, a topic that belongs in another unit, a service you cannot verify, or a hands-on task that may cost money.

---

## Skip what is already done

Decide per topic, before Phase 1. Unless the user typed `refresh`, never redo finished work.

### Notes (Phase 1)

A topic's notes are **already refined** if either test passes:

1. **Marker:** the file contains `<!-- teachprep:refined YYYY-MM-DD -->` (first line, or straight after any front matter).
2. **Style check**, for files without the marker. All of these must be true:
   - it has a `**Next:**` line, or ends the unit with a closing summary line;
   - it has no "Certification Traps", "exam tip" or "on the exam" content;
   - performance, cost and monitoring are merged into one `## Operating It` section;
   - the Summary contains a key-lesson table;
   - questions are not inline (only the closing `!!! question` box links to them).

   If it passes, add the marker (today's date) and treat the topic as refined.

For a refined topic:

- **Skip Phase 1** for it. Do not trim, restructure or rewrite it again.
- Still allowed: fixing a broken link or anchor the lesson needs, or correcting a fact that is now clearly wrong. Report any such small fix.
- If it fails the style check only partly, list what is missing and **ask** whether to refine it. Do not decide alone.

After finishing Phase 1 on a topic, add the marker as the file's first line (after front matter if present):

```markdown
<!-- teachprep:refined 2026-10-11 -->
```

### Lesson plans (Phase 2)

If `docs/teach-5t27uuv8/unit<N>-topic<M>-lecture.md` already exists, skip it. If the notes changed since it was written, check its "Notes:" links still resolve and fix only those.

### Quiz banks (Phase 3)

If `private/quizzes/unit<N>-topic<M>.questions.md` already exists, skip it. If it has fewer than 115 questions or fewer than 38 `EASY`, tell the user and offer to top it up, appending new questions with new ids and never rewriting existing ones.

### Nothing left to do

If every requested topic is already done in all three phases, say so and stop. Do not regenerate anything.

---

## Phase 1: Refine the notes

Apply to every `docs/unit<N>/topic<M>.md` in the unit **that is not already refined** (see "Skip what is already done"). Use parallel sub-agents, one per topic, if available, all with the same brief.

### 1.1 Content rules

| Rule | Detail |
|---|---|
| **Remove repetition across topics** | Assign each concept one owning topic (use the ownership map in Part II of `CLAUDE.md`). Other topics give one or two sentences and link to the owner |
| **Cut loosely related material** | Content that belongs to another unit becomes a link to that unit |
| **Make topics sequential** | Each topic opens by linking back to the previous one and ends with a `**Next:**` line to the following topic (or the next unit) |
| **Merge boilerplate** | Generic Security / Performance / Cost / Monitoring / Best Practices sections become short, topic-specific sections; merge Performance, Cost and Monitoring into one "Operating It: Performance, Cost and Monitoring" section |
| **Student friendly** | Short paragraphs, comparison tables, MkDocs admonitions for key points, and a key-lesson summary table at the end |
| **No exam framing** | Remove "Certification Traps", exam tips and "on the exam" wording. Fold real design insights into Common Mistakes |
| **Questions never inline** | Practice and interview questions live in `docs/Questions/unit<N>.md` and `docs/interviewquestions/unit<N>.md`. Move any found in a note there. Multiple-choice blocks are headed `### Multiple-Choice Questions` |
| **Target length** | Roughly 40–55% of the original; a little over is fine when the material is owned by that topic |

### 1.2 Latest information

- Verify anything likely to have changed against official AWS documentation, What's New posts or service FAQs. That includes service status, deprecations and end-of-support dates, limits, defaults, pricing models and console names.
- Write deprecated services as legacy, with the current replacement. Example: AWS App Mesh reached end of support on 30 September 2026; ECS Service Connect and VPC Lattice replace it.
- Do not invent facts, limits or prices. If a fact cannot be verified, remove it or ask the user.
- Keep numbers only when they are well established or verified.

### 1.3 Preserve

- **Heading anchors other pages link to.** Before editing, run `grep -rn "unit<N>/topic<M>.md#" docs`. Keep those exact heading texts, or update every inbound link.
- Every `<figure>` image (fix meaningless alt text).
- Mermaid diagrams that teach something; drop duplicates.
- The closing `!!! question "Practice and interview questions"` box.
- MkDocs rules in `CLAUDE.md` §16: wrap any `{{` in `{% raw %}`; no stray `==` or `^` pairs in prose; identifiers in backticks; blank line before lists.

---

## Phase 2: One 2-hour lecture lesson per topic

**File:** `docs/teach-5t27uuv8/unit<N>-topic<M>-lecture.md`. Format: everything in `lesson-templates/README.md` (timed `## Title { data-minutes="N" }` segments, `prompt` / `teacher` / `answer` / `quiz` blocks, notes links).

### 2.1 Time budget: exactly 120 minutes, quiz always last

The default interleaved structure. Adapt segment titles to the topic, but keep the rhythm and the totals.

| Segment | Minutes | Content |
|---|---:|---|
| Hook | 10 | A real problem from the running scenario that the topic solves. Pair discussion |
| Concept A | 15 | First core idea: why it exists, how it works, one analogy if abstract |
| Hands-on A: console | 15 | Guided task in the real AWS Console, building on Concept A |
| Concept B | 15 | Second core idea, building on what students just saw |
| Hands-on B: CLI | 20 | The same or a related task with the CLI against Floci; compare with the console |
| Break | 5 | `.break` segment |
| Recap and clean-up | 10 | Key-lesson recap, then **students delete their AWS resources** (see 2.4) |
| **Quiz** | **30** | ClassLegend quiz, always the final segment |
| **Total** | **120** | |

Lecture and hands-on together take 90 minutes; never cut the quiz to make room.

### 2.2 Teaching quality

- **Concept segments:** explain why, then how, then when to use it. Put a short diagram or table on screen (`!!! prompt` or plain content). Give each segment one predict-then-check question with a `???+ answer` block.
- **Analogies:** use them when the idea is abstract (for example load balancer as a restaurant host), in a `!!! prompt` block. Say in a `!!! teacher` note where the analogy breaks.
- **Hands-on segments:** numbered steps, each with what to click or type, what students should see, and one "why did that happen?" question. Include a success-criteria checklist (`- [ ]`).
- **Engagement:** a pair discussion in the hook; a prediction before each hands-on; at least one "what would break if..." question per lesson.
- **Notes links:** every concept and hands-on segment links to the matching section of the refined notes (`{ .notes-link target="_blank" }`). Check that the anchors resolve.
- **Running scenario:** reuse the course scenario (the college student portal or USMS) so lessons connect.

### 2.3 Hands-on environment

| Work | Environment | Rules |
|---|---|---|
| **Console** | Real AWS Console (student access provided) | Region `us-east-1` unless the class uses another. Smallest or free-tier-eligible sizes. Never create long-lived access keys; never use root |
| **CLI** | Floci (local AWS emulator) | Follow the environment contract in `CLAUDE.md` Part I §5: `./scripts/setup/floci-up.sh`, `configs/course.env`, named profile `floci`. **Never** `floci start`, `docker compose down -v`, `docker volume prune` |
| **Floci limits** | | Floci accepts any credentials and does not enforce IAM. Never design a task whose success depends on `AccessDenied`. Label Floci-only behaviour with the Floci-limitation admonition from `CLAUDE.md` |

### 2.4 Resource clean-up (every lesson)

Real AWS resources cost money and clutter shared accounts. Every lesson must:

1. **Tag at creation.** Every console-created resource gets tags `Course=DSO303` and `Session=u<N>t<M>`, and a name prefixed `dso303-u<N>t<M>-<student initials>`.
2. **Delete in class.** In the "Recap and clean-up" segment, students delete what they created. List the deletion steps in dependency order, for example instance before security group, and objects before bucket.
3. **Verify nothing is left.** Use **Resource Groups & Tag Editor**: search all resource types in the Region for tag `Session=u<N>t<M>`; the result must be empty. Also check service-specific leftovers: unattached EBS volumes, Elastic IPs, NAT gateways, load balancers, snapshots.
4. **Floci tidy-up.** Delete the practice resources with the CLI. Do **not** delete `~/floci-data` or stop the course environment unless told to.
5. **"After class" teacher checklist** at the end of the lesson page: re-run the Tag Editor search across the class account, and check the billing dashboard the next day. If the class uses AWS Academy Learner Lab, end the lab session.
6. Put the danger admonition from `CLAUDE.md` §14.1 before any delete step.

### 2.5 Quiz segment (always last, 30 minutes)

```markdown
## Quiz { data-minutes="30" }

!!! quiz "ClassLegend quiz: <topic title>"
    Bank of <count> questions in `private/quizzes/unit<N>-topic<M>.questions.md` covering <concepts>. Run as many as fit about 25 minutes, then spend 5 minutes reviewing the most-missed questions.
```

The lesson page names the quiz and its topics only. **No questions or answers in the lesson page**: the repository is public. The "Open ClassLegend dashboard" button is added automatically.

### 2.6 Register the lesson

Add a row per lesson to the Lessons table in `docs/teach-5t27uuv8/index.md` (Unit, Lesson link, `120 min`, `Lecture with console and CLI`).

---

## Phase 3: Quiz files (local only, never committed)

**File:** `private/quizzes/unit<N>-topic<M>.questions.md`, one per topic. Keep the `.questions.md` suffix the template uses.

### 3.1 Format: copy `private/classlegend-quiz-template.md` exactly

The user imports these files straight into ClassLegend, so any deviation breaks the import.

- **Front matter** (between `---` lines, at the very top):
  - `courseModuleId: "DSO303"`
  - `unit: "Unit <N>"`
  - `topic: "<N>.<M> <Topic title>"`
  - `defaultDifficulty: MEDIUM`
- **Each question** uses the clean form of the template's questions 2 and 3. The text in brackets in question 1 (`(unique id)`, `(multiple choice)`, `(EASY, MEDIUM or HARD)`, `(mark one with x)`, and so on) is guidance only and must not appear in output.

```markdown
## Question: u<N>t<M>-<n>
type: MCQ
difficulty: EASY | MEDIUM | HARD

<Question text>

- [ ] a) <option>
- [x] b) <correct option>
- [ ] c) <option>
- [ ] d) <option>

### Distractors
- [ ] e) <spare wrong option>
- [ ] f) <spare wrong option>

### Explanation
<Why the correct option is right, and why the most tempting wrong one is wrong.>
```

| Field | Rule |
|---|---|
| Question id | `u<N>t<M>-<n>`, numbered from 1, unique within the file (for example `u5t2-7`) |
| `type` | `MCQ` (the only type in the template) |
| Options | Exactly four, `a)` to `d)`, exactly one marked `[x]` |
| Correct position | Vary it across the quiz; no option letter should be correct much more often than the others |
| Distractors | Exactly two spare wrong options, `e)` and `f)`, plausible and clearly wrong to someone who understood the lesson |
| Explanation | Private teacher note (students never see it): why the answer is right and why the most likely wrong pick is wrong |

### 3.2 Content: a bank of at least 115 questions per topic

1. **At least 115 questions per topic.** Sized so each of the 23 students can get different questions (5 each). If the class size changes, scale to at least 5 questions per student.
2. **Every question comes from that topic's lesson:** its concept segments, analogies, hands-on console and CLI steps, and the matching sections of the refined notes it links to. Nothing from other topics, no general AWS trivia.
3. **Difficulty mix** for a 115-question bank (about one third easy; scale proportionally for larger banks):

    | Difficulty | Count | Rule |
    |---|---:|---|
    | `EASY` | **at least 38** | Hard minimum, never fewer |
    | `MEDIUM` | about 49 | |
    | `HARD` | about 28 | |

4. **Question mix:** about
   - 35% concept: what it is, why it exists, when to use it
   - 40% scenario: choose a design, diagnose a failure, predict an outcome
   - 25% practical: what a console step or CLI command from the hands-on does, or what its output means
5. **Cover the whole lesson** in teaching order, so every segment is represented and no single segment supplies more than about a quarter of the questions.
6. **No duplicates.** Do not ask the same fact twice with reworded text. Vary the angle instead: define, apply, compare, diagnose.
7. **Fair options.** No trick questions. Wrong options must be wrong for a reason the lesson explained. Avoid "all of the above" and "none of the above".
8. Never copy quiz content into `docs/`, the lesson page, a commit message or a pull request.
9. Confirm `git check-ignore -v private/quizzes/unit<N>-topic<M>.questions.md` names the `private/` rule.

### 3.3 Self-check each quiz file

- Front matter present and first in the file.
- Every question has `type`, `difficulty`, four options with exactly one `[x]`, two distractors and an explanation.
- Ids unique; no bracketed guidance text left over.
- At least 115 questions, of which at least 38 are `EASY`; medium and hard counts roughly match 3.2; every question traceable to a lesson segment.

---

## Phase 4: Verify before reporting

| Check | How |
|---|---|
| Site builds | `mkdocs build` with no new errors |
| Links and anchors | Every `.md#anchor` link in the changed notes, lesson pages and inbound links from other units resolves (check against the built HTML) |
| Lessons parse | Each lesson's `data-minutes` values sum to **120**, and the last segment is the 30-minute quiz |
| Clean-up present | Each lesson has a Recap and clean-up segment, Tag Editor verification and an After-class checklist |
| No leaks | No quiz questions or answers anywhere under `docs/`; `private/` is git-ignored |
| Quiz format | Each `private/quizzes/*.questions.md` passes the Phase 3.3 self-check |
| No exam framing | `grep -niE "exam|certif|trap"` over the changed notes shows nothing that frames content around exams |
| Restore build output | If `site/` is tracked and your builds changed it, restore it (`git checkout -- site && git clean -fq site`) |

---

## Phase 5: Report

Tell the user:

- per topic: what was done and what was skipped as already done;
- for refined notes: old and new line counts, and what moved where;
- the lesson files created and the quiz files written (paths only, never quiz content);
- facts you verified or removed as unverifiable;
- anything that needs their decision.

**Do not commit or push** unless the user asks.

# Lesson Plan Reference (Instructor Playbooks)

How to write, add and run DSO303 lesson plans. Every lesson plan is a password-protected **interactive HTML playbook** in the hidden teaching area.

| | |
|---|---|
| **Teaching area (short address)** | `https://norbutlepcha25.github.io/dso303/teach/`: redirects to the encrypted hub (`teach-5t27uuv8/index.html`) |
| **Hub page source** | `private/teach-src/index.html`: one `.lesson` row per playbook |
| **Write here (plaintext, never committed)** | `private/teach-src/unit<N>-<topic>.html`; open it directly in a browser to preview |
| **Publish (encrypted)** | `./utils/encrypt-playbooks.sh` writes `docs/teach-5t27uuv8/unit<N>-<topic>.html` |
| **Shared style and behaviour** | `docs/teach-5t27uuv8/playbook/playbook.css`, `playbook.js` |
| **Template** | `lesson-templates/playbook-template.html` |
| **Worked example (style reference)** | `private/teach-src/unit5-cicd-iac.html` |
| **Claude skill** | `.claude/skills/lesson-plan/SKILL.md` (triggered by "lesson plan unit N" or a topic) |
| **Full unit workflow** | `teachprep unit<N>`: see `lesson-templates/teachprep-workflow.md` |

---

## 1. Password protection

Playbooks are **encrypted** before they are published, with StaticCrypt (AES-256, in the browser). The published page and the file in the public repository show only a password box; the lesson content cannot be read without the password.

| Layer | Effect |
|---|---|
| Plaintext only in `private/teach-src/` | `private/` is git-ignored: the readable version never reaches GitHub |
| Encrypted copy in `docs/teach-5t27uuv8/` | Opens after the password is typed; "Remember this device" keeps it unlocked for 30 days |
| Build guard (`hooks/teacher_pages.py`) | `mkdocs build` fails if any `.html` in the teacher folder is not encrypted |
| Not Markdown pages, `noindex` meta | Never in `nav`, search or `sitemap.xml`; search engines asked not to index |
| Encrypted hub at a short address | `/dso303/teach/` redirects to the hub; unlock once with "Remember this device" and every lesson opens for 30 days on that browser. No link from the student site |

**Password.** Choose one passphrase of 14+ characters and use it for every playbook. It is never stored in the repository. Keep it in a password manager. Changing it means re-running the script for every playbook. Anyone who has the password can read every playbook, so do not share it with students or type it on a projected screen.

**Limits.** The `/teach/` redirect page is public but contains nothing except the link. Content committed before encryption (the old Markdown lessons) stays in Git history.

Even when encrypted, never put in a playbook:

- ClassLegend quiz questions or answers (the page names the quiz and its topics only)
- Credentials, access keys, real account IDs
- Student names, marks or personal data

In-class check questions with their answers are fine: they are ungraded discussion material.

---

## 2. Adding a playbook

1. Copy `lesson-templates/playbook-template.html` to `private/teach-src/unit<N>-<short-topic>.html` (topic lecture: `unit<N>-topic<M>-lecture.html`).
2. Delete the comment at the top. Fill in the pages (section 3). Preview by opening the file in a browser (`private/teach-src/playbook` links to the shared assets; the script recreates the link if it is missing).
3. Encrypt: `./utils/encrypt-playbooks.sh unit<N>-<short-topic>` (asks for the password). Run it again after every edit.
4. Add a `.lesson` row to the hub, `private/teach-src/index.html`, in teaching order, and run `./utils/encrypt-playbooks.sh index` (or encrypt everything with no argument).
5. Run the checks (section 7), then commit and push. `git status` must show only the encrypted file under `docs/`, never anything under `private/`.

---

## 3. Structure

Every playbook has the same shape, in this order:

```text
header        DSO303 · Unit N · Instructor Playbook, title, meta chips. No subtitle or summary line
.runner       timer bar (filled in by playbook.js)
nav           module list (built by playbook.js from the pages)
page 1        Roadmap and hook: duration pill, time/module/deliverable table, outcomes,
              before-class checklist, cost-and-safety box, hook discussion, end-to-end tiles
page 2..n     One module per page (below)
Break page    if the session is longer than 2 hours
Assess        failure-injection table, ClassLegend quiz cue, exit ticket, cleanup checklist
Coverage      topic / covered in / do not omit table, optional extensions, links to notes
footer        teacher-only and billing disclaimer
```

### A module page

```html
<section class="page" id="build" data-title="CodeBuild" data-minutes="25">
<div class="card">
  <h2>Module 3 — Title</h2>
  <div class="notes"> links to note sections </div>
  <h3>Key terms</h3>  <dl class="terms"> term + one-line definition </dl>
  <div class="note latest" data-date="Month YYYY"> what changed recently </div>
  7 × <div class="phase"> Step 1 Explain briefly · 2 Demonstrate in Console ·
        3 Students reproduce · 4 Repeat with CLI · 5 Verify · 6 Troubleshoot · 7 Clean up
  <h3>Check your understanding <span class="mcq-score score"></span></h3>
  1–3 × <div class="mcq">
  <div class="note teacher"> what to stress, transition </div>
</div>
</section>
```

| Rule | Why |
|---|---|
| `data-minutes` on every timed page; they sum to the session length | The timer, nav and "Used x of y min" come from them |
| `data-title` short (2–4 words) | Shown in the nav and timer bar |
| Every module has **Key terms** with definitions | Students meet each term defined before it is used |
| Explanations are short; depth lives in the notes, linked | Keeps the playbook scannable while teaching |
| Every hands-on module has Console **and** CLI | Same task twice: click, then reproduce with commands |
| CLI captures IDs into variables (`X=$(aws ... --query ... --output text)`) and uses `"$AWS_REGION"` | No hand-copied values, no Region mismatch |
| Tag created resources `Course=DSO303`, `Session=u<N>` | Cleanup is verifiable with Tag Editor |
| A danger box before every delete | What is deleted, what depends on it, reversible?, effect on later labs |

---

## 4. Components

| Component | Markup | Use for |
|---|---|---|
| Notes links | `<div class="notes"><a href="../unit5/topic1.html#anchor" target="_blank">5.1 Section</a></div>` | Every module; opens the note section in a new tab |
| Key terms | `<dl class="terms"><dt>Term</dt><dd>Definition</dd></dl>` | Definitions |
| Ask the class | `<div class="ask"><b>Predict first</b>Question</div>` | Hooks, predictions, pair discussions |
| Expected answer | `<details class="reveal"><summary>Expected answer</summary><div>...</div></details>` | Click to reveal after discussion |
| Instant-check question | `<div class="mcq" data-answer="1">` + `.q` + `button.opt` × 3–4 + `.why` | One click shows right/wrong and the reason. `data-answer` is the 0-based index of the correct option; vary it |
| Defect hunt | `<div class="hunt">` + `<span class="ln">` per line; defects carry `data-defect="why + fix"` | Critiquing code: students click lines, a found-count and explanations build up |
| Checklist | `<div class="task"><label><input type="checkbox"> ...</label></div>` | Student tasks, before-class, exit ticket, cleanup; remembered per browser |
| Callouts | `.note`, `.note warn`, `.note danger`, `.note teacher`, `.note latest` | Info, caution, destructive or cost, teacher-only notes, recent AWS changes |
| ClassLegend quiz | `<div class="quiz">` + `<a class="action" href="https://classlegend.vercel.app/">` | Quiz cue: name and topics only |
| Code | `<pre><code>...</code></pre>` | A copy button is added automatically. Escape `<`, `>`, `&` |

---

**Colour rule.** Black, white and blue only. Red, green and yellow are signals and appear only through `.note danger` (destructive or billable), `.note warn` (caution), right/wrong answer feedback, a found defect, and the timer warning/overrun. Never add other colours or inline styles.

## 5. Linking to the notes

`href="../unit<N>/topic<M>.html#anchor"` (the site uses `use_directory_urls: false`, so pages end in `.html`). The anchor is the heading text in lowercase, spaces as hyphens, punctuation removed. Check every anchor exists after a build (section 7). If a note heading is renamed, the link still opens the page but at the top.

---

## 6. Running a playbook

| Control | Key | Action |
|---|---|---|
| Start / Pause | Space | Clock for the current module |
| Next | N | Marks the module done and moves on |
| Back | B | Previous module |
| Nav list | | Jump to any module; done modules show a tick |
| Reset | | Clears timer, checklists and answered questions |
| Light mode / Dark mode | | Switches theme; remembered for all playbooks in this browser. Default follows the system setting. Both themes use the same black, white and blue palette |

The clock turns orange with two minutes left and red (negative) when a module overruns. State is saved in this browser only. Each module has its own URL (`...html#/build`) for bookmarking.

---

## 7. Checks before committing

| Check | How |
|---|---|
| Site builds | `mkdocs build -d <scratch dir>` shows no new errors (build outside `site/`, which is tracked) |
| Links resolve (source) | Check anchors from the plaintext source in `private/teach-src/`, not the encrypted copy |
| Links resolve | Every `../unit*/topic*.html#anchor` id exists in the built page (minified HTML may drop quotes: `id=anchor`) |
| Minutes add up | `data-minutes` values sum to the session length |
| Questions valid | Each `.mcq` has `data-answer` lower than its option count |
| Encrypted | `mkdocs build` passes the guard; the published file contains no lesson text (`grep` a heading word: no match) |
| Current | Facts likely to change were checked against official AWS sources and shown in `.note latest` with a date |
| Nothing sensitive | Section 1 |
| Listed | `.lesson` row in `private/teach-src/index.html`, hub re-encrypted |

---

## 8. Latest information

Before writing, check service status, renames, deprecations, new features, defaults and console names against AWS What's New, documentation and blogs. Examples that changed recently: CodeCommit back to general availability (November 2025); ECS native blue/green (July 2025) and canary/linear (October 2025); ECR Clair scanning retired (October 2025); CodePipeline API still defaulting to V1. Never present an unverified fact; drop it or ask.

---

## 9. Legacy Markdown lessons

All Markdown lessons were converted to playbooks in October 2026 and deleted. The Markdown lesson runner (`docs/javascripts/lesson-runner.js`, `docs/stylesheets/lesson.css`, `overrides/main.html` teacher block) is no longer used. The build guard rejects any Markdown file in the teacher folder, because its source would be public.

---

## 10. Maintenance

| File | Role |
|---|---|
| `docs/teach-5t27uuv8/playbook/playbook.css` | All playbook styling, light and dark |
| `docs/teach-5t27uuv8/playbook/playbook.js` | Nav, timer, copy buttons, checklists, instant-check questions, defect hunt, saved state |
| `private/teach-src/index.html` | Teaching Area hub (published encrypted as `teach-5t27uuv8/index.html`) |
| `docs/teach/index.html` | Short-address redirect to the hub |
| `hooks/teacher_pages.py` | Unlists Markdown pages in the folder (legacy lessons and the index) |
| `utils/encrypt-playbooks.sh` | Encrypts `private/teach-src/*.html` into the teacher folder (StaticCrypt 3.5.4 via `npx`) |
| `.staticrypt.json` | Encryption salt (not secret). Keep it committed so "Remember this device" survives re-encryption |

Change shared behaviour in `playbook.css` / `playbook.js`, never by inlining styles into a single playbook. **Renaming the folder:** update `TEACHER_DIR` in the hook, `OUT` in `utils/encrypt-playbooks.sh`, `not_in_nav` in `mkdocs.yml`, and the paths in this guide and the skill.

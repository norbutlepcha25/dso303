---
name: lesson-plan
description: Build a DSO303 instructor playbook (teacher-only lesson plan) as a password-protected interactive HTML page (source in private/teach-src/, encrypted copy in docs/teach-5t27uuv8/). Use whenever the user gives a unit or topic for a lesson plan, workshop plan, lecture plan or playbook (e.g. "lesson plan unit5", "playbook 3.2", "workshop unit 6 storage"), or asks to convert a teaching plan. Also used by teachprep Phase 2.
---

# DSO303 lesson plan (instructor playbook)

Every lesson plan is a **standalone HTML page** that uses the shared playbook stylesheet and script. Markdown lesson plans (`{ data-minutes }` segments) are legacy: do not write new ones.

## Read first (binding)

| File | Why |
|---|---|
| `lesson-templates/README.md` | Format rules, components, interaction markup, checks |
| `lesson-templates/playbook-template.html` | Skeleton to copy: header, runner, nav, page and module structure |
| `private/teach-src/unit5-cicd-iac.html` | Worked example: the reference for density, tone and interactions |
| `docs/unit<N>/topic<M>.md` | The notes the plan teaches and links to |

## Steps

1. **Scope.** Unit → one workshop covering all its topics (about 180 min). Single topic → one 120-minute lecture (teachprep rhythm). State the reading back if ambiguous.
2. **Read the notes** for every topic in scope. Collect heading anchors for links (heading text, lowercase, hyphens, punctuation removed; confirm in the built `site/` after step 7).
3. **Verify current facts.** Check service status, renames, deprecations, new features and console names against official AWS sources (What's New, docs, blogs). Put changes in a `note latest` box with `data-date`. Never present an unverified fact; drop it or ask.
4. **Copy the template** to `private/teach-src/unit<N>-<short-topic>.html` (topic lecture: `unit<N>-topic<M>-lecture.html`). This plaintext source is git-ignored. **Never write a playbook directly into `docs/`**: the build rejects unencrypted playbooks.
5. **Write the plan** in the playbook format:
   - Header: kicker line, title, meta chips only. **No subtitle, summary or thread line.**
   - Page 1 **Teaching roadmap**: duration pill, time / module / student deliverable table, outcomes, environment and safety checklist, end-to-end picture as tiles.
   - One page per module, `data-minutes` set, each with: notes links, **Key terms with one-line definitions** (`dl.terms`), then the seven steps: Explain briefly · Demonstrate in Console · Students reproduce · Repeat with CLI · Verify · Troubleshoot · Clean up.
   - Engagement in every module: one hook or predict-first `.ask`, at least one instant-check `.mcq`, expected answers in `details.reveal`. Use a `.hunt` (click-the-defect) where there is code to critique.
   - Final pages: **Assess and troubleshoot** (failure scenarios, ClassLegend `.quiz` cue, exit ticket, cleanup checklist) and **Coverage checklist** with links to the official note pages.
6. **Register** a `.lesson` row in the hub `private/teach-src/index.html` (teaching order).
6a. **Encryption is the user's step.** Never ask for or handle the password. Tell the user to run `./utils/encrypt-playbooks.sh <name>` (it prompts for the password) before committing; until then the index link has no target.
7. **Check** (README section "Checks"): `mkdocs build` passes; every `../unit<N>/topic<M>.html#anchor` exists in `site/`; module minutes sum to the session length; no quiz-bank questions, credentials or student data; `noindex` meta present; restore `site/` if it is tracked (`git checkout -- site && git clean -fq site`).

## Writing rules

- Concise, like the reference: short explanations, tables, no essays. Explain a concept where students need it and link the note section for depth.
- Real AWS (Console and CLI) uses the class Region `ap-south-1` (Mumbai); Floci examples stay `us-east-1`.
- Console + CLI on every hands-on module; CLI uses `"$AWS_REGION"` variables and captured IDs, never hand-copied values. Mark billable steps.
- Running scenario: USMS (University Student Management System).
- Public repository: in-class check questions with answers are fine (ungraded); ClassLegend quiz content never appears here.
- Colours: black, white, blue. Red, green and yellow only for real signals (`.note danger`, `.note warn`, answer feedback); no inline styles.
- No emojis. Professional tone. No certification-exam framing.
- Do not commit or push unless asked.

# Lesson Plan Reference

How to write, add and run DSO303 lesson plans in the teaching area. Every future lesson follows this guide.

| | |
|---|---|
| **Teaching area (bookmark)** | `https://norbutlepcha25.github.io/dso303/teach-5t27uuv8/` |
| **Quick access** | Type `teach` on any page of the site (outside the search box) |
| **Local preview** | `mkdocs serve`, then `http://127.0.0.1:8000/dso303/teach-5t27uuv8/` |
| **Lesson files** | `docs/teach-5t27uuv8/` |
| **Template** | `lesson-templates/lesson-plan.md` |
| **Full unit workflow** | `teachprep unit<N>`: see `lesson-templates/teachprep-workflow.md` |
| **First worked example** | `docs/teach-5t27uuv8/unit3-topic1-lecture.md` |

---

## 1. What the teaching area is

A set of pages for the teacher to follow while teaching: timed segments, teaching notes, expected answers, commands and links into the student notes. Students are not given the link.

### Unlisted, not secret

Pages in `docs/teach-5t27uuv8/` are handled automatically by `hooks/teacher_pages.py`:

| Protection | Effect |
|---|---|
| Not in `nav` | No tab or menu link on the student site |
| Excluded from search | Searching the site never shows them |
| Removed from `sitemap.xml` | Not listed for crawlers |
| `noindex, nofollow` tag | Search engines are asked not to index them |
| Lesson tools load only here | Student pages never load the lesson scripts |

**The repository is public.** Anyone browsing it on GitHub can read these Markdown files. So:

> [!CAUTION]
> **Never put these in a lesson file**
>
> - Quiz or assessment answers (keep them in ClassLegend)
> - Credentials, access keys, account IDs from real accounts
> - Student names, marks or any personal data
> - Anything you would not want a student to read

In-class discussion answers (for example "Deployment; Pod; Service") are acceptable: they are not graded.

---

## 2. Adding a new lesson

1. **Copy the template:** `lesson-templates/lesson-plan.md` to `docs/teach-5t27uuv8/<file>.md`.
2. **Name the file** `unit<N>-<short-topic>-<format>.md`, lowercase with hyphens, for example `unit4-microservices-workshop.md` or `unit5-cicd-lecture.md`.
3. **Delete the instruction comment** at the top of the copy (everything between `<!--` and `-->`).
4. **Write the lesson** using the structure in section 3.
5. **Add a row** to the Lessons table in `docs/teach-5t27uuv8/index.md`.
6. **Preview locally** with `mkdocs serve` and run the checks in section 7.
7. **Commit and push.** Nothing needs adding to `mkdocs.yml`.

---

## 3. Lesson structure

Every lesson has the same shape, in this order:

```text
# Unit N Workshop: Title                      <- H1, one per page
Duration / Audience / Mode / Running scenario <- four bold lines
<div class="lesson-schedule"></div>           <- replaced by the schedule table

## Before class                               <- plain section (no duration)
   purpose, learning outcomes, checklists, warnings

---

## Segment title { data-minutes="15" }        <- timed segments, in teaching order
## Segment title { data-minutes="20" }
## Break { data-minutes="10" .break }
...
## Exit ticket { data-minutes="5" }

---

## Command reference                          <- plain sections after the lesson (optional)
```

### Timed segments

A segment is a level-2 heading with a duration in minutes:

```markdown
## Kubernetes fundamentals { data-minutes="20" }
```

| Rule | Why |
|---|---|
| Only `##` headings with `data-minutes` are segments | `##` headings without it ("Before class", "Command reference") are ordinary sections |
| Never type clock times like `00:15–00:35` | Times, the timeline and the schedule table are calculated from durations; typed times go stale when you change one duration |
| Mark breaks with `.break`: `## Break { data-minutes="10" .break }` | Shown striped on the timeline |
| Durations should add up to the session length | The page shows "Planned total" so you can check |
| Use `###` or bold text inside a segment, never another `##` | A plain `##` inside the lesson would split the segment |
| Keep segment titles short (2–5 words) | They appear on the timeline buttons |

### Inside a segment

A typical segment reads top to bottom as: notes links, then what to present, then what to ask, then expected answers, then your notes and the transition.

```markdown
## AWS fundamentals: ECS versus EKS { data-minutes="20" }

[3.1 EKS or ECS?](../unit3/topic1.md#eks-or-ecs){ .notes-link target="_blank" }

| Option | What it means |
|---|---|
| ... | ... |

!!! prompt "Mini discussion"
    A small team with no Kubernetes experience wants to run one website.
    Should it automatically choose EKS?

???+ answer "Expected response"
    No. ECS may be simpler...

!!! teacher "Transition"
    "Let's check the basics before moving into Kubernetes."
```

---

## 4. Block types

| Block | Syntax | Colour | Use for |
|---|---|---|---|
| **prompt** | `!!! prompt "Title"` | Blue | What you present or ask the class: scenarios, discussion questions, tasks, analogies |
| **teacher** | `!!! teacher "Title"` | Purple | Your own notes: what to stress, timing reminders, transitions, fallbacks |
| **answer** | `???+ answer "Title"` | Green | Expected answers to class questions. `???+` starts open; use `???` to start collapsed |
| **quiz** | `!!! quiz "Title"` | Orange | A ClassLegend quiz cue: which quiz and the topics it covers. **No answers.** An "Open ClassLegend dashboard" button is added automatically; quiz links change every time, so never paste them here |

Standard blocks work too: `!!! warning`, `!!! tip`, `!!! note`, `!!! danger`. Ordinary Markdown (tables, lists, code blocks, Mermaid diagrams, images) works as in the notes.

Content inside a block must be indented four spaces. A code block inside a block is indented four spaces as well:

````markdown
!!! teacher "Clean up"
    ```bash
    kubectl delete deployment hello
    ```
````

---

## 5. Linking to the notes

Every segment should link to the note sections it teaches, so you can open the full explanation during class.

```markdown
[3.1 Control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane){ .notes-link target="_blank" }
```

| Part | Meaning |
|---|---|
| `3.1 Control plane and data plane` | Link text: topic number, then section name |
| `../unit3/topic1.md` | The note file, relative to the lesson file (always starts `../`) |
| `#control-plane-and-data-plane` | The section anchor |
| `{ .notes-link target="_blank" }` | Shows it as a "Notes:" pill and opens it in a new tab |

**Finding an anchor:** open the note on the site, hover over the section heading, click the ¶ symbol, and copy the part of the address after `#`. Anchors are the heading text in lowercase with spaces as hyphens and punctuation removed.

**If a note heading is renamed later,** the link stops pointing at that section (the page still opens, at the top). Re-check links whenever notes are restructured.

---

## 6. Running a lesson

| Control | Key | Action |
|---|---|---|
| **Start / Pause** | Space | Start or pause the clock for the current segment |
| **Next** | N | Next segment (the clock keeps running if it was running) |
| **Back** | B | Previous segment |
| Timeline | | Click any segment to jump to it |
| **Focus** | F | Hide the site menus so the lesson fills the screen; Esc to leave |
| **Reset** | | Clear all segment times and return to the first segment |

- The countdown turns **orange** with two minutes left and **red** when a segment overruns (shown as negative time).
- The lesson clock shows total time used against the planned total.
- Timer position and checklist ticks are saved in the browser per lesson, so a refresh or accidental close does not lose your place. They do not sync between devices.
- Checklists (`- [ ] item`) in the lesson are clickable on teacher pages.

---

## 7. Checks before committing

| Check | How |
|---|---|
| Page builds | `mkdocs build` shows no new errors for the lesson |
| Segments detected | The control bar appears and shows the expected number of segments, for example `1/11` |
| Total is right | "Planned total" under the schedule table matches the session length |
| Notes links work | Click each "Notes:" pill; it should land on the named section, not the top of the page |
| Nothing sensitive | No quiz answers, credentials or student data (section 1) |
| Lesson is listed | Row added to `docs/teach-5t27uuv8/index.md` |
| Still unlisted | The lesson does not appear in the site search or navigation |

---

## 8. Converting an existing lesson plan

When starting from a plan written elsewhere (for example a Word or Markdown document):

| In the original plan | Becomes |
|---|---|
| Time-table at the top | Delete it; keep only durations on segment headings and the `lesson-schedule` placeholder |
| "Segment 3: Title (00:35–00:55)" | `## Title { data-minutes="20" }` |
| Purpose, outcomes, preparation, checklists | The **Before class** section |
| Scenario, "Present this", analogy, task | `!!! prompt` |
| "Ask students" questions | A numbered list under **Ask the class:** |
| "Expected answers" | `???+ answer` |
| Teaching notes, transitions, cautions | `!!! teacher` |
| Quiz with answers | `!!! quiz` naming the quiz and its topics; answers stay in ClassLegend |
| Command reference, appendix | Plain `##` sections after the last segment |

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No control bar | No `##` heading has `{ data-minutes="..." }`, or the file is not in `docs/teach-5t27uuv8/` | Add durations; move the file |
| A segment is missing from the timeline | Its heading is `###`, or the braces are malformed | Use `##` and `{ data-minutes="20" }` with spaces inside the braces |
| `{ data-minutes="20" }` shows as text in the heading | Missing space or quote | Match the syntax exactly |
| Block shows as plain text | Content not indented four spaces, or a typo in the block name | Indent; use `prompt`, `teacher`, `answer` or `quiz` |
| Timer shows an old position | Saved state from an earlier run | Click **Reset** |
| Lesson appears in site search | The file is outside `docs/teach-5t27uuv8/` | Move it into the teaching folder |

---

## 10. How it works (for maintenance)

| File | Role |
|---|---|
| `hooks/teacher_pages.py` | Flags every page in the teaching folder: search exclusion, noindex, no sidebars; strips them from the sitemap. Holds the folder name in `TEACHER_DIR` |
| `overrides/main.html` | Adds the noindex tag and loads the lesson stylesheet and script on flagged pages only |
| `docs/javascripts/lesson-runner.js` | Control bar, timeline, schedule table, time labels, Focus mode, saved state, clickable checklists |
| `docs/stylesheets/lesson.css` | Block colours, control bar, reading width, Focus mode |
| `docs/javascripts/teacher-shortcut.js` | The `teach` keyboard shortcut (loaded site-wide; holds the folder name in `TARGET`) |
| `mkdocs.yml` | `custom_dir: overrides`, `hooks:` and `not_in_nav:` entries; `extra.classlegend_url` is the dashboard the quiz button opens (change it there to update every lesson) |

**Changing the folder name** (if the link is ever shared): rename the folder, then update `TEACHER_DIR` in `hooks/teacher_pages.py`, `TARGET` in `docs/javascripts/teacher-shortcut.js`, `not_in_nav` in `mkdocs.yml`, and the paths in this guide and the template.

# Teaching Area

Lesson plans for running DSO303 sessions. This area is unlisted: it is not in the site navigation, search or sitemap, and search engines are asked not to index it. Bookmark this page.

!!! warning "Unlisted, not secret"
    The Markdown source of these pages is in the public repository. Keep quiz answers and anything sensitive in ClassLegend, not here.

## Lessons

| Unit | Lesson | Duration | Format |
|---|---|---|---|
| 3 | [From Containers to Amazon EKS](unit3-eks-workshop.md) | 180 min | Workshop with hands-on `kubectl` |

## Running a lesson

| Control | Action |
|---|---|
| **Start / Pause** or ++space++ | Start or pause the clock for the current segment |
| **Next** or ++n++ | Move to the next segment |
| **Back** or ++b++ | Return to the previous segment |
| Timeline bar | Click any segment to jump to it |
| **Focus** or ++f++ | Hide the site menus so the lesson fills the screen; ++esc++ to leave |
| **Reset** | Clear the timer and return to the first segment |

The countdown turns orange with two minutes left and red when a segment overruns. Timer position and checklist ticks are remembered in this browser, so a page refresh does not lose your place.

**Block colours:** blue *prompt* = what you present or ask the class; purple *teacher* = your notes; green *answer* = expected answers (open by default); orange *quiz* = ClassLegend quiz cue.

## Adding a lesson

1. Copy `lesson-templates/lesson-plan.md` (repository root) into `docs/teach-5t27uuv8/`, for example `unit4-microservices-workshop.md`.
2. Fill in the segments. Each timed segment is a level-2 heading with a duration: `## Segment title { data-minutes="20" }`.
3. Add a row to the table above.
4. Commit and push. The page is unlisted automatically; nothing needs adding to `mkdocs.yml`.

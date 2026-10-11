<!--
LESSON PLAN TEMPLATE
Full guide: lesson-templates/README.md

Copy this file into docs/teach-5t27uuv8/ (for example
docs/teach-5t27uuv8/unit4-microservices-workshop.md), fill it in, add a row
to the table in docs/teach-5t27uuv8/index.md, then commit. Pages in that
folder are unlisted automatically (hooks/teacher_pages.py): not in nav,
search or the sitemap, and marked noindex.

The repository is public. Never put quiz answers or sensitive material here.

HOW THE LESSON RUNNER READS THIS PAGE
- Every timed segment is a level-2 heading with a duration in minutes:
      ## Segment title { data-minutes="20" }
  Add .break for a break:
      ## Break { data-minutes="10" .break }
  Segment times (00:15-00:35), the timeline and the clock are calculated
  from these durations. Do not type the times yourself.
- Level-2 headings WITHOUT data-minutes (for example "Before class",
  "Command reference") are ordinary sections, not segments.
- <div class="lesson-schedule"></div> is replaced by the schedule table.
- Task lists (- [ ] item) become clickable checklists remembered per browser.

BLOCK TYPES
  !!! prompt "Title"    what you present or ask the class (scenarios, tasks)
  !!! teacher "Title"   your own notes, transitions, timing reminders
  ???+ answer "Title"   expected answers (open by default, click to collapse;
                        use ??? instead to start collapsed)
  !!! quiz "Title"      a ClassLegend quiz cue (no answers here)

LINKING TO THE NOTES
  [3.1 Control plane and data plane](../unit3/topic1.md#control-plane-and-data-plane){ .notes-link target="_blank" }
  The part after # is the heading's anchor: open the note, hover the heading,
  click the pilcrow and copy the end of the URL.
-->

# Unit N Workshop: Lesson Title

**Duration:** N minutes  
**Audience:** ...  
**Mode:** ...  
**Running scenario:** ...

<div class="lesson-schedule"></div>

## Before class

**Learning outcomes.** By the end, students should be able to:

1. ...
2. ...

**Checklist**

- [ ] Environment tested
- [ ] ClassLegend quiz loaded
- [ ] Fallback ready

---

## Opening hook { data-minutes="10" }

[N.M Relevant note section](../unitN/topicM.md#anchor){ .notes-link target="_blank" }

!!! prompt "Scenario"
    The problem students will think about.

!!! teacher "Teaching notes"
    What to say, what to watch for, the transition to the next segment.

## Concept segment { data-minutes="20" }

Concept content: tables, diagrams, short explanations.

**Ask the class:**

1. ...

???+ answer "Expected answers"
    1. ...

## Quiz { data-minutes="10" }

!!! quiz "Run Quiz X in ClassLegend"
    Topics covered. Students answer individually, then discuss.

## Break { data-minutes="10" .break }

!!! prompt "Break: 10 minutes"
    Back at ...

## Hands-on { data-minutes="30" }

```bash
# commands students run
```

**Success criteria**

- [ ] ...

## Exit ticket { data-minutes="5" }

!!! prompt "Answer individually"
    1. ...

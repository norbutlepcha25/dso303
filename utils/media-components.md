# Adding images and videos to DSO303 pages

Two reusable components, defined in `main.py`, produce the house figure style: the media, a caption, and a right-aligned source line.

| Component | Use for | Source line reads |
|---|---|---|
| `{{ figure(...) }}` | Any image | `Image Source: ...` |
| `{{ embed(...) }}` | A YouTube video, or any web page that allows embedding | `Video Source: ...` or `Content Source: ...` |

Each component prints a single line of HTML, so it works at any indentation, including inside `!!!` admonitions and `???` accordions. `utils/image_audit.py` checks both.

---

## Before you start: is the page allowed to run components?

Open the page and look at the first lines. If you see this front matter:

```yaml
---
render_macros: false
---
```

then components on that page are printed as plain text. Fix it:

1. Delete those three lines.
2. Search the page for double curly braces (usually `docker inspect --format`, Go or Helm templates inside code blocks).
3. Put raw tags on the fence lines of each code block that contains them, exactly like this:

    ````markdown
    {% raw %}```yaml
    ... '{{index .RepoDigests 0}}' ...
    ```{% endraw %}
    ````

4. Build and check that the code block still shows the double braces unchanged.

Never use both `render_macros: false` and raw tags on one page.

---

## Adding an image, step by step

**Step 1: Save the file in the right folder.**

| Page | Folder |
|---|---|
| `docs/unit<N>/topic<M>.md` | `docs/img/U<N>/t<M>/` |
| `docs/Lab/*.md` | `docs/img/labs/` |
| other `docs/<dir>/` | `docs/img/<dir>/` |

Name the file in kebab case after what it shows, e.g. `build-once-deploy-many.png`. Avoid names like `image-1.png` or `Screen Shot ...png`.

If you pasted the image into the editor and it landed next to the Markdown file, step 6 moves it for you.

**Step 2: Decide the source.**

| Where it came from | `source` text | `source_url` |
|---|---|---|
| AI tool | `"AI generated (ChatGPT)"`, `"AI generated (Google Gemini)"` | none |
| Your own drawing | `"Created by the author"` | none |
| Your own screenshot | `"Screenshot, AWS Management Console (IAM)"` | none |
| A website | Site or article name, e.g. `"TecAdmin"` | the page URL |
| A book | `"Author, Title, edition, chapter"` | none |
| Not known yet | `"Unknown"` (the audit keeps flagging it) | none |

**Step 3: Write the component where the image belongs.**

```markdown
{{ figure("../img/U5/t1/build-once-deploy-many.png",
          "Build Once, Deploy Many",
          "AI generated (Google Gemini)",
          alt="One commit built once into an immutable image and deployed to dev, staging and production") }}
```

The arguments, in order:

1. **path**: relative to the Markdown file, as in `![...](...)`. From `docs/unit5/topic1.md` it starts with `../img/`.
2. **caption**: a short title, at most about ten words, with no "Figure:" prefix and no full stop.
3. **source**: from step 2.
4. `alt=`: what the image shows, in one sentence, for screen readers. If you leave it out, the caption is used.
5. `source_url=`: optional; it turns the source text into a link.
6. `width=`: optional, default `"80%"`; use `"100%"` for wide diagrams.

**Step 4: Inside an admonition or accordion**, indent the component with the admonition body (4 spaces):

```markdown
??? example "Worked example"
    Some text.

    {{ figure("../img/U5/t1/dora-shopping-pipeline.png", "DORA Metrics in a Pipeline", "AI generated") }}
```

**Step 5: Preview** with `mkdocs serve` and check the image, caption and source line. If you changed `main.py`, restart `mkdocs serve`, because it does not reload Python code.

**Step 6: Audit.**

```bash
python3 utils/image_audit.py docs/unit5/topic1.md
python3 utils/image_audit.py --relocate            # dry run
python3 utils/image_audit.py --relocate --apply    # move misplaced or badly named files
```

Fix anything the audit reports until it prints `0 with issues`.

---

## Adding a YouTube video or web page, step by step

**Step 1: Copy the URL.** Any YouTube form works: `watch?v=`, `youtu.be/`, `shorts/`, or a URL with `&t=90s`, which keeps the start time. For other sites, use the full `https://` page URL. Many sites block embedding; if the frame stays blank, link to the page instead.

**Step 2: Find the creator** (for the source line). For YouTube, this is the channel name under the video, e.g. "ByteMonk". The title and channel can also be read from:

```bash
curl -s "https://www.youtube.com/oembed?url=<video URL>&format=json"
```

**Step 3: Write the component** below the section it supports. Put the sentence that says what to watch for in `intro=`, not in a paragraph before the component, so that it disappears from the PDF together with the video:

```markdown
{{ embed("https://www.youtube.com/watch?v=RThb3koc5DM",
         "Software Deployment Strategies Used by Netflix, Amazon and Facebook",
         "ByteMonk, YouTube",
         intro="The video below walks through these strategies. For each one, note which column of the table the speaker is emphasising.") }}
```

The arguments, in order:

1. **url**: the video or page URL.
2. **caption**: a short title.
3. **source**: the creator and platform, e.g. `"ByteMonk, YouTube"` or `"AWS Documentation"`.
4. `source_url=`: optional; it defaults to the URL itself.
5. `height=`: for web pages only, default `"600px"`; videos are always 16:9.
6. `intro=`: optional lead-in sentence, shown above the video.

**Videos are never in the PDF.** The Download PDF button and the "Save as PDF" fallback both leave out every `embed()`, including its intro, caption and source line. `docs/stylesheets/print.css` hides them, and `utils/build_pdfs.py` removes them before printing. Do not write text elsewhere on the page that only makes sense if the video is there. If something else must stay out of the PDF, wrap it in `<div class="no-print" markdown>...</div>`.

YouTube videos use the privacy-enhanced `youtube-nocookie.com` player, so nothing is set in the reader's browser until they press play.

**Step 4: Preview and audit**, as for images (steps 5 and 6 above).

---

## Do not use

| Old way | Replace with |
|---|---|
| `{{ image_block(...) }}`, `{{ youtube_embed(...) }}`, `{{ iframe_embed(...) }}` | `figure()` / `embed()`; the audit flags the old ones as `legacy-embed` |
| A hand-written `<iframe>` | `embed()`; flagged as `raw-iframe` |
| A bare `![alt](image.png)` with no caption or source | `figure()`, or the `<figure markdown="span">` block already used in the notes |

The existing `<figure markdown="span">` blocks in the notes are still valid and do not need converting.

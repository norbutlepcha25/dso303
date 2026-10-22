---
name: image-captions
description: Audit and fix the images in the DSO303 notes and labs. Moves each image into its convention folder (docs/img/U<N>/t<M>/, docs/img/labs/, ...), gives it a meaningful file name, rewrites the references, wraps it in the house figure template and adds a caption plus an "Image Source" line saying whether it is AI generated (and by which tool), the author's own, or taken from a named site with a link. Also adds YouTube videos and embedded web pages with the embed() component. Use when the user asks to check, tidy, organise, caption, attribute, reference or credit images, pastes or adds a new image to a note, or asks to embed a video, iframe or web page.
---

# DSO303 image audit and captions

The tool is `utils/image_audit.py`. It does the mechanical work: finding problems, moving files and rewriting paths. **You** do the judgement work: looking at each image, writing the caption, and establishing the source.

## Step 1: Audit

```bash
python3 utils/image_audit.py                # whole site
python3 utils/image_audit.py docs/unit5     # one folder or one file
```

Each image reference is reported with its issues:

| Issue | Meaning | Fixed by |
|---|---|---|
| `missing` | File does not exist | Ask the user for the file; never delete the reference silently |
| `external` | Hot-linked from another site | Download a copy into the convention folder, keep the site as the source |
| `misplaced` | Not under the page's convention folder | `--relocate --apply` |
| `generic-name` | `image-1.png`, `ss.png`, names with spaces | `--relocate --apply`, then a meaningful rename (Step 2) |
| `no-figure` / `no-caption` / `no-source` | House template incomplete | Step 4 |
| `unknown-source` | Source line says `Unknown`, `N/A` or `TODO` | Step 3, ask the user |
| `weak-alt` | Empty or placeholder alt text (`RBS`, `image`) | Step 4 |

`metadata:` lines are provenance hints read from the file (C2PA credentials, IPTC `trainedAlgorithmicMedia`, generator names, draw.io, OS screenshot tags). Unreferenced files under `docs/img/` are listed at the end; report them, do not delete them.

## Step 2: Put each image in the right folder

| Page | Folder |
|---|---|
| `docs/unit<N>/topic<M>.md` | `docs/img/U<N>/t<M>/` (existing files directly in `docs/img/U<N>/` are accepted) |
| `docs/Lab/*.md` | `docs/img/labs/` |
| other `docs/<dir>/` | `docs/img/<dir lower-case>/` |
| `docs/<page>.md` | `docs/img/site/` |

```bash
python3 utils/image_audit.py --relocate          # dry run: review the plan
python3 utils/image_audit.py --relocate --apply  # git mv + rewrite every reference
```

An image used by pages in different units is skipped and left where it is. Mention it to the user.

The tool names generic files from their alt text, or `<unit>-<topic>-figure`. After viewing the image (Step 3), rename any fallback name to a short kebab-case description (`dora-shopping-pipeline.png`). Use `git mv` for tracked files and update the references with Edit.

## Step 3: Look at every image and establish its source

Open each image with the Read tool before writing anything about it. Decide the source in this order:

1. **The user said where it came from** in this conversation, or the existing source line says so.
2. **Metadata hint** from the audit. C2PA or IPTC `trainedAlgorithmicMedia` means AI generated. A generator name (ChatGPT/OpenAI, Gemini, Midjourney, Firefly) names the tool.
3. **Visible evidence in the image**, such as a watermark, a site logo, a book or vendor footer, or an AWS documentation diagram style. This only *suggests* a source and needs confirming.
4. **Otherwise, ask.** Collect every image whose source is still unknown and ask once, with AskUserQuestion. Offer the options "AI generated (which tool?)", "Website (give the URL)", "Book or paper (give the reference)" and "My own diagram or screenshot".

Never invent a URL, a book reference or a tool name. If the user cannot say, write `Image Source: Unknown` and list the image in your final message.

## Step 4: Write the figure

For **new** images, prefer the `figure()` component; for **videos and web pages**, always use `embed()`. Both are documented step by step in `utils/media-components.md`. Check that the page does not have `render_macros: false`; if it does, follow that guide's first section.

```markdown
{{ figure("../img/U5/t1/build-once-deploy-many.png", "Build Once, Deploy Many", "AI generated (Google Gemini)", alt="One commit built once and deployed to three environments") }}
{{ embed("https://www.youtube.com/watch?v=RThb3koc5DM", "Software Deployment Strategies Used by Netflix, Amazon and Facebook", "ByteMonk, YouTube") }}
```

For a YouTube source, read the title and channel with `curl -s "https://www.youtube.com/oembed?url=<URL>&format=json"`; never guess the channel.

When fixing an **existing** `<figure markdown="span">` block, keep the block and use the house template exactly; it matches the existing notes. Keep the image's existing `{width=...}`, defaulting to `80%`.

```markdown
<figure markdown="span">
    ![Alt text describing what the image shows](../img/U5/t1/dora-shopping-pipeline.png){width="80%"}
    <figcaption>Short Caption in Title Style</figcaption>
    <p align='right' style="font-size:0.8em"><i>Image Source: AI generated (ChatGPT)</i></p>
</figure>
```

Source line by type:

| Source | Line |
|---|---|
| AI, tool known | `<i>Image Source: AI generated (ChatGPT)</i>` (or `Google Gemini`, `Midjourney`, ...) |
| AI, tool unknown | `<i>Image Source: AI generated</i>` |
| Website | `<i>Image Source: <a href="URL" target="_blank" rel="noopener">Site or page title</a></i>` |
| Book or paper | `<i>Image Source: Author, *Title*, edition, chapter or page</i>` |
| Author's own | `<i>Image Source: Created by the author</i>` |
| Screenshot | `<i>Image Source: Screenshot, AWS Management Console</i>` (name the product shown) |

Rules:

- **Alt text** describes what the image shows, for someone who cannot see it, in one sentence. It is not the caption repeated.
- **Caption** is a short title of at most about ten words, with no "Figure:" prefix and no full stop, matching existing captions such as "Storage Services in AWS".
- **Indentation**: a figure inside an admonition or accordion is indented with the admonition body (4 spaces), and its inner lines get 4 more.
- **Line endings**: several notes use CRLF. Edit with the Edit tool, never with a text-mode Python rewrite.
- **Unit notes rules still apply**: no emojis, and no `==`, `^` or critic brace pairs in captions.

## Step 5: Verify

```bash
python3 utils/image_audit.py <the pages you touched>   # should report no issues
mkdocs build -q -d "$TMPDIR/dso303-check"              # never build into site/, which is tracked
```

Report what was moved and renamed, which sources came from metadata, the user or visual evidence, and anything still `Unknown`. Do not commit unless asked.

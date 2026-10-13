"""MkDocs hook: keep the teacher area unlisted.

Every page under TEACHER_DIR is a teacher page. For each one this hook
  - excludes it from the site search index,
  - marks it `teacher` (overrides/main.html then adds a noindex robots tag and
    loads the lesson runner, which student pages never load),
  - hides the left navigation and right table of contents,
  - adds a "Next lesson" button to every timed lesson, following the order
    of the Lessons table in the Teaching Area index,
and after the build it removes teacher pages from sitemap.xml / sitemap.xml.gz.

The pages are also left out of `nav` in mkdocs.yml, so nothing on the public
site links to them. This is "unlisted", not "secret": the Markdown source is
in the public repository, so never put quiz answers or anything sensitive in
a teacher page.
"""

import gzip
import re
from pathlib import Path

TEACHER_DIR = "teach-5t27uuv8/"
INDEX_URI = TEACHER_DIR + "index.md"
TIMED = re.compile(r'data-minutes="\d+"')


def _is_teacher(page) -> bool:
    return page.file.src_uri.startswith(TEACHER_DIR)


def _lesson_order(config):
    """Timed lessons in the order of the Teaching Area index's Lessons table.

    Rows link a page in the teacher folder; pages without timed segments
    (setup runbooks, stand-alone practicals) are not part of the sequence.
    """
    docs = Path(config["docs_dir"])
    index = docs / INDEX_URI
    if not index.exists():
        return []
    order = []
    for title, target in re.findall(r"^\|[^|\n]*\|\s*\[([^\]]+)\]\(([^)#\s]+\.md)\)", index.read_text(encoding="utf-8"), re.M):
        src = docs / TEACHER_DIR / target
        if src.exists() and TIMED.search(src.read_text(encoding="utf-8")):
            order.append((target, title))
    return order


def _next_lesson_button(markdown, page, config):
    """Add a 'Next lesson' button after the Quiz segment of a timed lesson.

    The lesson runner copies the button into its control bar. The last lesson
    in the table gets a button back to the Teaching Area instead.
    """
    if not TIMED.search(markdown) or "next-lesson-link" in markdown:
        return markdown
    order = _lesson_order(config)
    name = page.file.src_uri[len(TEACHER_DIR):]
    targets = [t for t, _ in order]
    if name not in targets:
        return markdown
    i = targets.index(name)
    if i + 1 < len(order):
        target, title = order[i + 1]
        label = f"Next lesson: {title} &rarr;"
    else:
        target, label = "index.md", "Back to the Teaching Area &rarr;"
    button = f'\n[{label}]({target}){{ .md-button .md-button--primary .next-lesson-link }}\n\n'
    # Place it at the end of the Quiz segment (before the next level-2 heading),
    # so it sits where the class ends rather than below the reference sections.
    quiz = re.search(r"^## Quiz\b.*$", markdown, re.M)
    if quiz:
        nxt = re.search(r"^## ", markdown[quiz.end():], re.M)
        if nxt:
            cut = quiz.end() + nxt.start()
            return markdown[:cut] + button.lstrip("\n") + markdown[cut:]
    return markdown.rstrip("\n") + "\n" + button


def on_page_markdown(markdown, page, config, files):
    if _is_teacher(page):
        page.meta["teacher"] = True
        page.meta.setdefault("search", {})["exclude"] = True
        hide = set(page.meta.get("hide") or [])
        page.meta["hide"] = sorted(hide | {"navigation", "toc"})
        markdown = _next_lesson_button(markdown, page, config)
    return markdown


def on_post_build(config):
    site = Path(config["site_dir"])
    sitemap = site / "sitemap.xml"
    if not sitemap.exists():
        return
    xml = sitemap.read_text(encoding="utf-8")
    cleaned = re.sub(
        r"\s*<url>(?:(?!</url>).)*?/" + re.escape(TEACHER_DIR) + r".*?</url>",
        "",
        xml,
        flags=re.S,
    )
    if cleaned != xml:
        sitemap.write_text(cleaned, encoding="utf-8")
        with gzip.open(site / "sitemap.xml.gz", "wb") as gz:
            gz.write(cleaned.encode("utf-8"))

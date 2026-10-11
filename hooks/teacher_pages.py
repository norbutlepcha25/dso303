"""MkDocs hook: keep the teacher area unlisted.

Every page under TEACHER_DIR is a teacher page. For each one this hook
  - excludes it from the site search index,
  - marks it `teacher` (overrides/main.html then adds a noindex robots tag and
    loads the lesson runner, which student pages never load),
  - hides the left navigation and right table of contents,
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


def _is_teacher(page) -> bool:
    return page.file.src_uri.startswith(TEACHER_DIR)


def on_page_markdown(markdown, page, config, files):
    if _is_teacher(page):
        page.meta["teacher"] = True
        page.meta.setdefault("search", {})["exclude"] = True
        hide = set(page.meta.get("hide") or [])
        page.meta["hide"] = sorted(hide | {"navigation", "toc"})
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

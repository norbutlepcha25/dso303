"""MkDocs hook: keep the teacher area private.

docs/teach-5t27uuv8/ holds only password-encrypted HTML playbooks (StaticCrypt
output from utils/encrypt-playbooks.sh; plaintext sources live in the
git-ignored private/teach-src/). The repository is public, so this hook
  - refuses to build if any file in the folder could be read without the
    password: an .html page that is not encrypted, or any Markdown page;
  - removes anything under the folder from sitemap.xml / sitemap.xml.gz.

The short address /teach/ (docs/teach/index.html) redirects to the folder's
encrypted hub page.
"""

import gzip
import re
from pathlib import Path

from mkdocs.exceptions import PluginError

TEACHER_DIR = "teach-5t27uuv8/"


def on_pre_build(config):
    folder = Path(config["docs_dir"]) / TEACHER_DIR
    if not folder.exists():
        return
    readable = [f.name for f in folder.glob("*.md")]
    readable += [
        f.name for f in folder.glob("*.html")
        if "staticrypt" not in f.read_text(encoding="utf-8", errors="ignore")
    ]
    if readable:
        raise PluginError(
            "Readable teacher file(s) in docs/" + TEACHER_DIR + ": " + ", ".join(sorted(readable))
            + ". Teacher pages must be encrypted playbooks: put the source in private/teach-src/"
            " and run ./utils/encrypt-playbooks.sh."
        )


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

#!/usr/bin/env python3
"""Rebuild the classroom download ZIPs in docs/downloads/ from classroom-files/.

  python3 utils/build_downloads.py           # rebuild all three ZIPs
  python3 utils/build_downloads.py --check   # exit 1 if a ZIP is out of date

classroom-files/ is the only place to edit these files. The ZIPs are derived:

  website-assets.zip        website/*                       (Unit 1.4 static site)
  pipeline-source.zip       pipeline/buildspec.yml, pipeline/check_site.py,
                            website/* as site/*             (upload to the pipeline)
  cloudboard-classroom.zip  website/, deployment/, pipeline/ (+ source.zip),
                            unit5/                          (everything)

Entries are written in sorted order with a fixed timestamp, so the same
inputs always give byte-identical ZIPs and Git only sees real changes.
The teacher follow-along for these files is the encrypted playbook
unit5-cloudboard-demo (source: private/teach-src/unit5-cloudboard-demo.html).
"""

import argparse
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "classroom-files"
OUT = ROOT / "docs" / "downloads"
STAMP = (2026, 1, 1, 0, 0, 0)
SKIP = {".DS_Store", "node_modules", "__pycache__"}


def files_under(folder):
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and not any(part in SKIP for part in p.relative_to(SRC).parts)
    )


def make_zip(entries):
    """entries: list of (archive name, bytes). Returns the ZIP as bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def build():
    website = [(p.relative_to(SRC / "website").as_posix(), p.read_bytes())
               for p in files_under(SRC / "website")]
    website_as_site = [("site/" + n, d) for n, d in website]
    pipeline_src = [
        ("buildspec.yml", (SRC / "pipeline/buildspec.yml").read_bytes()),
        ("check_site.py", (SRC / "pipeline/check_site.py").read_bytes()),
    ] + website_as_site
    source_zip = make_zip(pipeline_src)

    classroom = [(p.relative_to(SRC).as_posix(), p.read_bytes())
                 for d in ("website", "deployment", "pipeline", "unit5")
                 for p in files_under(SRC / d)]
    classroom.append(("pipeline/source.zip", source_zip))

    return {
        "website-assets.zip": make_zip(website),
        "pipeline-source.zip": source_zip,
        "cloudboard-classroom.zip": make_zip(classroom),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report ZIPs that are out of date")
    args = ap.parse_args()

    stale = []
    for name, data in build().items():
        target = OUT / name
        current = target.read_bytes() if target.exists() else b""
        if current == data:
            print(f"up to date  {name}")
            continue
        stale.append(name)
        if args.check:
            print(f"OUT OF DATE {name}")
        else:
            target.write_bytes(data)
            print(f"rebuilt     {name} ({len(data)} bytes)")
    if args.check and stale:
        print("\nRun: python3 utils/build_downloads.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

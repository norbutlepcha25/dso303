"""Render every unit topic page of the built site to a PDF.

Run after `mkdocs build`:

    pip install playwright
    playwright install --with-deps chromium
    python utils/build_pdfs.py            # reads ./site, writes ./site/pdf/

Each site/unit<N>/topic<M>.html becomes site/pdf/unit<N>/topic<M>.pdf, which
the "Download PDF" button (docs/javascripts/pdf-download.js) links to.

Pages are printed by headless Chromium, so Mermaid diagrams, KaTeX and the
print stylesheet (docs/stylesheets/print.css) render exactly as in a browser.
A failed page is reported and skipped; the button falls back to the browser's
print dialog for any page without a PDF.
"""

import argparse
import functools
import html
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

HEADER = (
    '<div style="width:100%;font-size:8px;color:#777;padding:0 14mm;'
    'display:flex;justify-content:space-between;font-family:Roboto,Arial,sans-serif">'
    "<span>DSO303 Cloud Native Solution Design</span><span>{title}</span></div>"
)
FOOTER = (
    '<div style="width:100%;font-size:8px;color:#777;padding:0 14mm;'
    'text-align:right;font-family:Roboto,Arial,sans-serif">'
    'Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)

# Runs in the page before printing.
PREPARE_PAGE = """
async () => {
  // Collapsible blocks would print closed.
  document.querySelectorAll('article details').forEach(d => d.setAttribute('open', ''));
  // Videos and embedded pages are not printed (print.css hides them); remove
  // them so the renderer does not wait on YouTube or third-party pages.
  document.querySelectorAll('figure.dso-embed, .no-print, article iframe').forEach(e => e.remove());
  // Lazy images are not fetched by the print renderer unless forced.
  const images = [...document.querySelectorAll('img')];
  images.forEach(img => img.setAttribute('loading', 'eager'));
  await Promise.all(images.map(img => img.complete ? null :
    new Promise(resolve => { img.onload = img.onerror = resolve; })));
  await document.fonts.ready;
}
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory: Path) -> ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", default="site", type=Path, help="built site directory")
    parser.add_argument("--pattern", default="unit*/topic*.html", help="pages to render")
    args = parser.parse_args()

    site = args.site.resolve()
    pages = sorted(site.glob(args.pattern))
    if not pages:
        print(f"No pages matching {args.pattern} in {site}", file=sys.stderr)
        return 1

    server = serve(site)
    base = f"http://127.0.0.1:{server.server_port}"
    written, failed = 0, []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(color_scheme="light")
        for path in pages:
            rel = path.relative_to(site).as_posix()
            out = site / "pdf" / Path(rel).with_suffix(".pdf")
            try:
                page.goto(f"{base}/{rel}", wait_until="networkidle", timeout=60_000)
                # Material swaps each <pre class="mermaid"> for a rendered
                # <div class="mermaid"> once the diagram is drawn. A diagram with
                # a syntax error never swaps; print it as source rather than
                # dropping the whole page.
                try:
                    page.wait_for_function(
                        "!document.querySelector('pre.mermaid')", timeout=20_000
                    )
                except PlaywrightTimeout:
                    broken = page.locator("pre.mermaid").count()
                    print(f"warn  {rel}: {broken} Mermaid diagram(s) did not render "
                          "(syntax error?); printed as source", file=sys.stderr)
                page.evaluate(PREPARE_PAGE)
                title = page.locator("article h1").first.inner_text().rstrip("¶").strip()
                out.parent.mkdir(parents=True, exist_ok=True)
                page.pdf(
                    path=str(out),
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template=HEADER.format(title=html.escape(title)),
                    footer_template=FOOTER,
                    margin={"top": "18mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                )
                written += 1
                print(f"ok    {rel} -> {out.relative_to(site)}")
            except Exception as exc:  # keep going; one bad page must not block the rest
                failed.append(rel)
                print(f"FAIL  {rel}: {exc}", file=sys.stderr)
        browser.close()

    server.shutdown()
    print(f"\n{written} PDF(s) written, {len(failed)} failed")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())

"""CI gate: catch missing entrypoint, broken local links, and invalid release metadata."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
import json

SITE = Path(__file__).resolve().parent / 'site'
class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key not in {'href', 'src'} or not value:
                continue
            url = urlsplit(value)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (self.page.parent / unquote(url.path)).resolve()
            assert target.is_relative_to(SITE.resolve()), f'Link escapes site: {value}'
            assert target.is_file(), f'{self.page.name}: missing linked file {value}'
assert (SITE / 'index.html').is_file(), 'Missing index.html'
for page in SITE.glob('*.html'):
    parser = Links()
    parser.page = page
    parser.feed(page.read_text())
release = json.loads((SITE / 'release.json').read_text())
assert release.get('release'), 'Missing release identifier'
print(f'PASS: entrypoint, local links and release {release["release"]}')

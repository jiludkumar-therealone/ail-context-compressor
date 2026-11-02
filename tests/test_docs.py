"""Checks for the static docs page in docs/ (served by GitHub Pages from main:/docs)."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPO_URL = "https://github.com/jiludkumar-therealone/ail-context-compressor"


def readme_rows():
    rows = []
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        if re.match(r"\| .* \| [\d,]+ \| [\d,]+ \| -?[\d.]+% \|$", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append([re.sub(r"`([^`]*)`", r"\1", c) for c in cells])
    return rows


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cell, self.in_body, self.tags, self.urls = [], None, False, [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            if name in ("href", "src", "action", "srcset", "poster", "data") and value:
                self.urls.append(value)
        if tag == "tbody":
            self.in_body = True
        elif tag == "tr" and self.in_body:
            self.rows.append([])
        elif tag == "td" and self.in_body:
            self.cell = ""

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_body = False
        elif tag == "td" and self.cell is not None:
            self.rows[-1].append(" ".join(self.cell.split()))
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data


PAGES = sorted(p.name for p in DOCS.glob("*.html"))


def page(name="index.html"):
    html = (DOCS / name).read_text(encoding="utf-8")
    c = _Collector()
    c.feed(html)
    return html, c


class DocsPageTests(unittest.TestCase):
    def test_benchmark_table_matches_readme(self):
        expected = readme_rows()
        self.assertEqual(len(expected), 5)
        self.assertEqual(page()[1].rows, expected)

    def test_pages_present(self):
        self.assertIn("index.html", PAGES)
        self.assertIn("why.html", PAGES)
        self.assertIn('href="why.html"', page()[0])

    def test_only_repo_links_are_external(self):
        for name in PAGES:
            html, c = page(name)
            for url in c.urls:
                if url.startswith("#") or url == "style.css" or url in PAGES:
                    continue
                self.assertTrue(url == REPO_URL or url.startswith(REPO_URL + "/"), (name, url))
            for url in re.findall(r"(?:https?:)?//[^\s\"'<>)]+", html):
                self.assertTrue(url.startswith(REPO_URL), (name, url))

    def test_no_scripts_forms_or_embeds(self):
        for name in PAGES:
            html, c = page(name)
            for tag in ("script", "form", "iframe", "img", "object", "embed", "input", "base"):
                self.assertNotIn(tag, c.tags, name)
            self.assertEqual(c.tags.count("link"), 1, name)
            self.assertNotIn("style", c.tags, name)
            self.assertNotRegex(html, r"\sstyle=")

    def test_local_files_exist(self):
        for name in PAGES:
            for url in page(name)[1].urls:
                if not url.startswith(("#", "https://")):
                    self.assertTrue((DOCS / url).is_file(), (name, url))
        self.assertTrue((DOCS / ".nojekyll").is_file())
        self.assertFalse((DOCS / "_headers").exists())

    def test_csp_and_referrer_meta(self):
        for name in PAGES:
            html = page(name)[0]
            head = html[: html.index("</head>")]
            self.assertIn('<meta name="referrer" content="no-referrer">', head)
            csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', head).group(1)
            self.assertEqual(
                csp,
                "default-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'",
            )
            # The CSP meta must come before anything that loads a resource.
            self.assertLess(head.index("Content-Security-Policy"), head.index("<link"))

    def test_css_has_both_colour_schemes(self):
        css = (DOCS / "style.css").read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme:dark", css.replace(" ", ""))
        self.assertNotIn("@import", css)
        self.assertNotRegex(css, r"url\(")


if __name__ == "__main__":
    unittest.main()

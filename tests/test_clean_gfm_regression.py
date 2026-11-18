"""Regression coverage for clean, content-preserving documentation GFM."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from docsync.pandoc_converter import html_to_gfm
from docsync.policy import NORMALIZE_DOCUMENT


HTML = """<!doctype html>
<html lang="en">
<head><base href="https://aistudio.google.com/"></head>
<body>
<main class="layout-wrapper ng-star-inserted" role="main">
  <div class="page-content-wrapper" _ngcontent-demo="">
    <div class="page-content ng-star-inserted">
      <h1>Build apps in Google AI Studio</h1>
      <div class="docs-header-actions">
        <span class="button-label">Copy page</span>
      </div>
      <p>Build full-stack applications with
        <a class="ng-star-inserted" href="/docs/aistudio-fullstack">
          server-side capabilities
        </a>.
      </p>
      <p><img src="/images/architecture.png" alt="Architecture"></p>
      <table>
        <thead><tr><th>Feature</th><th>Value</th></tr></thead>
        <tbody><tr><td>Runtime</td><td>Node.js</td></tr></tbody>
      </table>
      <pre><code class="language-javascript">console.log("hello");</code></pre>
    </div>
  </div>
</main>
</body>
</html>"""


def test_clean_gfm_preserves_documentation_content() -> None:
    async def convert() -> str:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(HTML)
                normalized = await page.evaluate(NORMALIZE_DOCUMENT)
                assert normalized
                return html_to_gfm(normalized)
            finally:
                await browser.close()

    markdown = asyncio.run(convert())

    # Meaningful documentation must survive.
    assert "# Build apps in Google AI Studio" in markdown
    assert "Build full-stack applications" in markdown
    assert "server-side capabilities" in markdown
    assert "https://aistudio.google.com/docs/aistudio-fullstack" in markdown
    assert "https://aistudio.google.com/images/architecture.png" in markdown
    assert "Feature" in markdown
    assert "Runtime" in markdown
    assert "Node.js" in markdown
    assert 'console.log("hello");' in markdown

    # Presentation-only markup must not leak into Markdown.
    assert "Copy page" not in markdown
    assert "ng-star-inserted" not in markdown
    assert "_ngcontent-" not in markdown
    assert "page-content-wrapper" not in markdown
    assert "<div" not in markdown
    assert "<span" not in markdown

    # Standard links must be native Markdown.
    assert "[server-side capabilities]" in markdown
    assert "<a " not in markdown
    assert "[TABLE]" not in markdown


if __name__ == "__main__":
    test_clean_gfm_preserves_documentation_content()

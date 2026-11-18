"""Regression tests for documentation-specific DOM-to-GFM fidelity."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

from playwright.async_api import async_playwright

from docsync.pandoc_converter import html_to_gfm
from docsync.policy import NORMALIZE_DOCUMENT

HTML = """<!doctype html>
<html lang="en"><head><base href="https://docs.example.test/"></head>
<body><main>
<h1>Campaigns</h1>
<h2>List campaigns<a href="#list"><svg width="1em" height="1em"
  aria-hidden="true"><path d="M0 0"/></svg></a></h2>
<p>See <a href="/ads/campaign-targeting">Campaign Targeting</a>.</p>
<p><img src="/images/architecture.png" alt="Architecture diagram"></p>
<pre class="astro-code"><code><span>curl -X GET "/campaigns"</span></code>
<button type="button">Copy</button></pre>
<pre class="astro-code"><code>{
  "object": "list",
  "data": []
}</code></pre>
<p>Semantic vector diagram:</p>
<svg width="640" height="240" role="img" aria-label="Diagram">
  <rect width="640" height="240"/>
</svg>
</main></body></html>"""


async def _normalized_html() -> str:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            extracted = await page.evaluate(NORMALIZE_DOCUMENT)
            assert extracted is not None
            return extracted
        finally:
            await browser.close()


def test_dom_preserves_real_images_but_drops_theme_icons() -> None:
    html = asyncio.run(_normalized_html())
    assert 'width="1em"' not in html
    assert 'aria-label="Diagram"' in html
    assert "https://docs.example.test/ads/campaign-targeting" in html
    assert "https://docs.example.test/images/architecture.png" in html
    assert "<button" not in html
    assert "Copy" not in html


def test_conversion_uses_real_code_languages_and_keeps_content(
    tmp_path: Path,
) -> None:
    validator = tmp_path / "accept-validator"
    validator.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n", encoding="utf-8")
    validator.chmod(0o755)
    with patch.dict("os.environ", {"DOCSYNC_GFM_VALIDATOR": str(validator)}):
        markdown = html_to_gfm(asyncio.run(_normalized_html()))

    assert "Campaigns" in markdown
    assert "List campaigns" in markdown
    assert "astro-code" not in markdown
    assert "data:image/svg+xml" in markdown  # Preserve the semantic diagram.
    assert "https://docs.example.test/ads/campaign-targeting" in markdown
    assert "https://docs.example.test/images/architecture.png" in markdown
    assert "curl -X GET" in markdown
    assert '"object": "list"' in markdown
    assert "Copy" not in markdown
    assert "``` bash" in markdown or "```bash" in markdown
    assert "``` json" in markdown or "```json" in markdown

    subprocess.run(
        ["pandoc", "--from=gfm", "--to=json"],
        input=markdown,
        text=True,
        capture_output=True,
        check=True,
    )


def test_dom_removes_ui_noise_but_preserves_content() -> None:
    async def run() -> str:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content("""
                <main>
                  <h1>API Reference</h1>
                  <nav><a href="/menu">Menu</a></nav>
                  <div role="tablist"><button>Python</button></div>
                  <span class="material-symbols-outlined">content_copy</span>
                  <button aria-label="Copy page">content_copy</button>
                  <button title="Expand">expand_more</button>
                  <p>The word link is meaningful content.</p>
                  <p>Use the check command to validate results.</p>
                  <pre><code>print("hello")</code></pre>
                </main>
                """)
                return await page.evaluate(NORMALIZE_DOCUMENT)
            finally:
                await browser.close()

    html = asyncio.run(run())
    assert "API Reference" in html
    assert "content_copy" not in html
    assert "expand_more" not in html
    assert "Menu" not in html
    assert "Python</button>" not in html
    assert "word link is meaningful" in html
    assert "check command" in html
    assert 'print("hello")' in html

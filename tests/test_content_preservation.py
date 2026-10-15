from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

from docsync.pandoc_converter import html_to_gfm
from docsync.policy import NORMALIZE_DOCUMENT

HTML = """<!doctype html>
<html lang="en">
<body>
<header><p>Site navigation</p></header>
<main>
<h1>API Reference</h1>
<p>Important documentation content.</p>
<h2>Example</h2>
<pre><code class="language-python">print("hello")</code></pre>
<table>
<thead><tr><th>Parameter</th><th>Type</th></tr></thead>
<tbody><tr><td>name</td><td>string</td></tr></tbody>
</table>
<p><a href="https://example.com/api">API documentation</a></p>
<p><img src="https://example.com/diagram.png" alt="Architecture diagram"></p>
<aside><strong>Warning:</strong> Preserve this information.</aside>
<p><span>Important inline text.</span></p>
</main>
</body>
</html>"""


def check_markdown(markdown: str) -> None:
    expected = [
        "# API Reference",
        "Important documentation content.",
        'print("hello")',
        "Parameter",
        "string",
        "https://example.com/api",
        "diagram.png",
        "Preserve this information.",
        "Important inline text.",
    ]

    for value in expected:
        assert value in markdown, f"Missing content: {value}"

    assert "Site navigation" not in markdown


async def extract_python() -> str:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            extracted = await page.evaluate(NORMALIZE_DOCUMENT)
            assert extracted
            return html_to_gfm(extracted)
        finally:
            await browser.close()


def test_python_content_preservation() -> None:
    check_markdown(asyncio.run(extract_python()))


def test_typescript_content_preservation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "typescript" / ".docsync-content-test.mjs"

    source = (root / "typescript/src/index.ts").read_text(encoding="utf-8")
    start = source.index(
        "      const html = shouldProcess ? await page.evaluate(() => {"
    )
    end = source.index("      }) : null;", start)

    extraction = source[
        start + len("      const html = shouldProcess ? await page.evaluate(") : end
        + len("      }")
    ]

    compiler = root / "typescript/node_modules/typescript"
    assert compiler.is_dir(), "TypeScript compiler is not installed"

    import re

    extraction = re.sub(r"\s+as HTMLElement\b", "", extraction)

    script.write_text(
        """
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.setContent(process.env.TEST_HTML);
  const html = await page.evaluate(EXTRACTION);
  if (!html) throw new Error('Empty extracted HTML');
  process.stdout.write(
    execFileSync('pandoc', ['--from=html', '--to=gfm', '--wrap=none'], {
      input: html,
      encoding: 'utf8'
    })
  );
} finally {
  await browser.close();
}
""".replace("EXTRACTION", extraction),
        encoding="utf-8",
    )

    import os

    environment = os.environ.copy()
    environment["TEST_HTML"] = HTML

    try:
        result = subprocess.run(
            ["node", str(script)],
            cwd=root / "typescript",
            env=environment,
            text=True,
            capture_output=True,
        )

        assert result.returncode == 0, result.stderr
        check_markdown(result.stdout)
    finally:
        script.unlink(missing_ok=True)

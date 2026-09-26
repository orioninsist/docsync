"""Shared DocsSync document and storage policy."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

NORMALIZE_DOCUMENT = r"""
() => {
  const mains = [...document.querySelectorAll('main')];
  if (!mains.length) return null;
  const main = mains.reduce((best, current) =>
    (current.textContent?.trim().length ?? 0) > (best.textContent?.trim().length ?? 0)
      ? current : best
  );
  const root = main.cloneNode(true);
  root.querySelectorAll('script,style,noscript,template,svg,button,nav,aside').forEach((el) => el.remove());
  root.querySelectorAll('.sr-only,[aria-hidden="true"],[role="status"],[role="button"]').forEach((el) => el.remove());
  for (const pre of [...root.querySelectorAll('pre')]) {
    const code = pre.querySelector('code');
    const language =
      code?.getAttribute('data-language')?.trim() ||
      pre.getAttribute('data-language')?.trim() ||
      pre.getAttribute('syntax')?.trim() ||
      [...(code?.classList ?? [])].find((value) => value.startsWith('language-'))?.slice(9) ||
      [...pre.classList].find((value) => value.startsWith('language-'))?.slice(9) || '';
    const cleanPre = document.createElement('pre');
    const cleanCode = document.createElement('code');
    if (language) cleanCode.className = `language-${language.toLowerCase()}`;
    cleanCode.textContent = code?.textContent ?? pre.textContent ?? '';
    cleanPre.appendChild(cleanCode);
    pre.replaceWith(cleanPre);
  }
  for (const span of [...root.querySelectorAll('span')]) span.replaceWith(...span.childNodes);
  return root.innerHTML;
}
"""


def normalize_language(value: str) -> str:
    language = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if len(language) != 2 or not language.isalpha():
        raise ValueError("language must be a two-letter code such as 'en' or 'tr'")
    return language


def scope_root(start_url: str) -> str:
    return start_url.rstrip("/")


def scope_id(start_url: str) -> str:
    return hashlib.sha256(scope_root(start_url).encode("utf-8")).hexdigest()[:12]


def hostname_for_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("start_url must be an absolute HTTP(S) URL")
    return parsed.hostname


def default_output_dir(start_url: str) -> Path:
    return Path("docs") / hostname_for_url(start_url) / scope_id(start_url)


def default_state_dir(start_url: str) -> Path:
    return (
        Path("storage") / "docsync" / hostname_for_url(start_url) / scope_id(start_url)
    )


def output_path(output_dir: Path, url: str) -> Path:
    parsed = urlsplit(url)
    path = parsed.path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", path).strip("-") or "index"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return output_dir / hostname_for_url(url) / f"{slug}-{url_hash}.md"

"""Page quality detection utilities for crawler HTML and Markdown outputs."""

from __future__ import annotations

from typing import ClassVar

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList


class PageQualityDetector:
    """Detect blocked, login-gated, shell, and unusable page outputs."""

    LOGIN_HTTP_STATUS_CODES: ClassVar[set[int]] = {401, 407}
    BLOCKED_HTTP_STATUS_CODES: ClassVar[set[int]] = {403, 429, 451}

    BOT_PROTECTION_PATTERNS: ClassVar[tuple[str, ...]] = (
        "checking your browser",
        "verify you are human",
        "verify that you are human",
        "cloudflare",
        "cloudflare ray id",
        "attention required",
        "access denied",
        "request blocked",
        "temporarily blocked",
        "too many requests",
        "rate limited",
        "bot detection",
        "bot protection",
        "captcha",
        "recaptcha",
        "hcaptcha",
        "akamai",
        "perimeterx",
        "datadome",
        "incapsula",
        "imperva",
        "sucuri",
        "distil networks",
    )

    LOGIN_PATTERNS: ClassVar[tuple[str, ...]] = (
        "sign in",
        "sign-in",
        "signin",
        "log in",
        "log-in",
        "login",
        "log into",
        "create account",
        "authentication required",
        "please authenticate",
        "you must be signed in",
        "you need to sign in",
        "continue to sign in",
        "please sign in",
        "please log in",
        "member login",
        "customer login",
        "account login",
        "login required",
        "sign in required",
        "restricted access",
        "private content",
        "members only",
    )

    JS_REQUIRED_PATTERNS: ClassVar[tuple[str, ...]] = (
        "enable javascript",
        "javascript is required",
        "please enable js",
        "requires javascript",
        "you need to enable javascript",
        "this app works best with javascript",
    )

    LOGIN_FORM_SELECTORS: ClassVar[tuple[str, ...]] = (
        "form[action*='login' i]",
        "form[action*='signin' i]",
        "form[action*='sign-in' i]",
        "form[action*='auth' i]",
        "input[type='password']",
        "input[name*='password' i]",
        "input[id*='password' i]",
        "input[name*='email' i]",
        "input[name*='username' i]",
        "input[name*='user' i]",
        "button[type='submit']",
    )

    MIN_TEXT_CONTENT_LENGTH: ClassVar[int] = 120
    MIN_PARSED_TEXT_LENGTH: ClassVar[int] = 20
    MIN_PARSED_MARKDOWN_LENGTH: ClassVar[int] = 20

    def detect_transport_quality_issue(self, status_code: int | None) -> str | None:
        """Return a transport-level quality issue for known blocking statuses."""
        if status_code in self.LOGIN_HTTP_STATUS_CODES:
            return "login_required"

        if status_code in self.BLOCKED_HTTP_STATUS_CODES:
            return "blocked_or_bot_protected"

        return None

    def status_for_empty_fetch(self, status_code: int | None) -> str:
        """Return the persisted status to use when a fetch produced no HTML."""
        return self.detect_transport_quality_issue(status_code) or "error"

    def detect_html_quality_issue(
        self,
        *,
        html: str,
        status_code: int | None,
    ) -> str | None:
        """Return a quality issue detected before content parsing."""
        transport_status = self.detect_transport_quality_issue(status_code)

        if transport_status is not None:
            return transport_status

        soup = BeautifulSoup(html, "html.parser")
        visible_text = soup.get_text(" ", strip=True)
        normalized_text = self._normalize_text_for_detection(visible_text)
        has_article_content = self._has_meaningful_article_content(soup)

        if self._looks_like_bot_protection_page(
            soup=soup,
            normalized_text=normalized_text,
            has_article_content=has_article_content,
        ):
            return "blocked_or_bot_protected"

        if not has_article_content and self._looks_like_login_required_page(soup):
            return "login_required"

        if not has_article_content and self._contains_any(
            normalized_text,
            self.JS_REQUIRED_PATTERNS,
        ):
            return "javascript_required"

        if self._looks_like_shell_without_content(soup, visible_text):
            return "empty_or_js_shell"

        return None

    def detect_parsed_quality_issue(
        self,
        *,
        markdown: str,
        text_content: str,
    ) -> str | None:
        """Return an issue only when parsed content is effectively empty."""
        clean_text = " ".join(text_content.split())
        clean_markdown = markdown.strip()

        has_usable_text = len(clean_text) >= self.MIN_PARSED_TEXT_LENGTH
        has_usable_markdown = len(clean_markdown) >= self.MIN_PARSED_MARKDOWN_LENGTH

        if not has_usable_text and not has_usable_markdown:
            return "low_content"

        return None

    def _looks_like_bot_protection_page(
        self,
        *,
        soup: BeautifulSoup,
        normalized_text: str,
        has_article_content: bool,
    ) -> bool:
        title_text = ""

        if soup.title and soup.title.string:
            title_text = self._normalize_text_for_detection(soup.title.string)

        heading_text = " ".join(
            self._normalize_text_for_detection(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h1", "h2"], limit=5)
        )

        page_header_text = f"{title_text} {heading_text}"

        strong_page_level_patterns = (
            "checking your browser",
            "verify you are human",
            "verify that you are human",
            "access denied",
            "request blocked",
            "temporarily blocked",
            "too many requests",
            "rate limited",
            "attention required",
            "cloudflare ray id",
        )

        if self._contains_any(page_header_text, strong_page_level_patterns):
            return True

        if has_article_content:
            return False

        return self._contains_any(normalized_text, self.BOT_PROTECTION_PATTERNS)

    def _has_meaningful_article_content(self, soup: BeautifulSoup) -> bool:
        selectors = (
            "article",
            "main",
            "[role='main']",
            ".article-content",
            ".post-content",
            ".entry-content",
        )

        for selector in selectors:
            node = soup.select_one(selector)

            if not node:
                continue

            text = " ".join(node.get_text(" ", strip=True).split())

            if len(text) >= self.MIN_TEXT_CONTENT_LENGTH:
                return True

        return False

    def _looks_like_login_required_page(
        self,
        soup: BeautifulSoup,
    ) -> bool:
        if self._contains_login_form(soup):
            return True

        title_text = ""

        if soup.title and soup.title.string:
            title_text = self._normalize_text_for_detection(soup.title.string)

        heading_texts = [
            self._normalize_text_for_detection(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h1", "h2"], limit=5)
        ]

        title_or_heading_text = " ".join([title_text, *heading_texts])

        strong_login_patterns = (
            "login required",
            "sign in required",
            "you must be signed in",
            "you need to sign in",
            "please sign in",
            "please log in",
            "authentication required",
            "restricted access",
            "private content",
            "members only",
        )

        return self._contains_any(title_or_heading_text, strong_login_patterns)

    def _contains_login_form(self, soup: BeautifulSoup) -> bool:
        password_input = soup.select_one(
            "input[type='password'], input[name*='password' i], input[id*='password' i]"
        )

        if password_input is not None:
            return True

        for form in soup.find_all("form"):
            form_text = self._normalize_text_for_detection(
                form.get_text(" ", strip=True)
            )
            action = self._normalize_text_for_detection(str(form.get("action", "")))
            form_id = self._normalize_text_for_detection(str(form.get("id", "")))

            raw_form_class = form.get("class")

            if isinstance(raw_form_class, AttributeValueList):
                form_class_text = " ".join(str(value) for value in raw_form_class)
            elif isinstance(raw_form_class, str):
                form_class_text = raw_form_class
            else:
                form_class_text = ""

            form_class = self._normalize_text_for_detection(form_class_text)
            haystack = " ".join([form_text, action, form_id, form_class])

            if self._contains_any(haystack, self.LOGIN_PATTERNS):
                return True

        return False

    def _looks_like_shell_without_content(
        self,
        soup: BeautifulSoup,
        visible_text: str,
    ) -> bool:
        text_length = len(" ".join(visible_text.split()))
        script_count = len(soup.find_all("script"))

        content_nodes = soup.select(
            "".join(
                (
                    "main, article, [role='main'], .content, .documentation, ",
                    ".docs-content, .doc-content, .markdown-body, .article-content",
                )
            )
        )

        has_meaningful_content_node = any(
            len(node.get_text(" ", strip=True)) >= self.MIN_TEXT_CONTENT_LENGTH
            for node in content_nodes
        )

        if has_meaningful_content_node:
            return False

        if script_count >= 8 and text_length < self.MIN_TEXT_CONTENT_LENGTH:
            return True

        body = soup.find("body")

        if body is None:
            return True

        body_text = body.get_text(" ", strip=True)

        return len(body_text) < 40 and script_count > 0

    def _contains_any(
        self,
        text: str,
        patterns: tuple[str, ...],
    ) -> bool:
        return any(pattern in text for pattern in patterns)

    def _normalize_text_for_detection(self, text: str) -> str:
        return " ".join(text.split()).lower()


PageQualityAnalyzer = PageQualityDetector

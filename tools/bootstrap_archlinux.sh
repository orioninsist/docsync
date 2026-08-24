#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

readonly REPOSITORY_URL="https://github.com/orioninsist/docsync.git"
readonly DEFAULT_PROJECT_DIR="${HOME}/docsync"
readonly PROJECT_DIR="${DOCSYNC_PROJECT_DIR:-${1:-$DEFAULT_PROJECT_DIR}}"
readonly UV_INSTALL_DIR="${HOME}/.local/bin"
readonly DOCSYNC_WRAPPER="${UV_INSTALL_DIR}/docsync"

PACMAN_PACKAGES=(
    base-devel
    git
    curl
    ca-certificates
    openssl
    glibc
    gcc
    pkgconf

    glib2
    nss
    nspr
    dbus
    atk
    at-spi2-core
    cups
    libdrm
    libxkbcommon
    libx11
    libxcb
    libxcomposite
    libxdamage
    libxext
    libxfixes
    libxrandr
    libxshmfence
    mesa
    pango
    cairo
    alsa-lib
    gtk3
)

section() {
    printf '\n'
    printf '%s\n' '===================================================================================================='
    printf '%s\n' "$1"
    printf '%s\n' '===================================================================================================='
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    local line_number=$1

    printf '\n'
    printf '%s\n' '===================================================================================================='
    printf '%s\n' 'BOOTSTRAP FAILED'
    printf '%s\n' '===================================================================================================='
    printf 'Exit status: %s\n' "$exit_code"
    printf 'Line:        %s\n' "$line_number"
    printf 'Project:     %s\n' "$PROJECT_DIR"
    printf '\nThe installation stopped before reporting success.\n'

    exit "$exit_code"
}

trap 'on_error "$LINENO"' ERR

run_as_root() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return
    fi

    if command -v doas >/dev/null 2>&1; then
        doas "$@"
        return
    fi

    die "Installing Arch Linux system packages requires root privileges. Install sudo/doas or run this bootstrap as root."
}

ensure_arch_linux() {
    [[ -r /etc/os-release ]] || die "/etc/os-release is missing."

    # shellcheck disable=SC1091
    source /etc/os-release

    [[ "${ID:-}" == "arch" ]] || die "This bootstrap is intended for Arch Linux. Detected ID=${ID:-unknown}."
    [[ "$(uname -m)" == "x86_64" ]] || die "This bootstrap currently supports Arch Linux x86_64 only."
    command -v pacman >/dev/null 2>&1 || die "pacman is not available."
}

install_system_packages() {
    section "1. ARCH LINUX SYSTEM PACKAGES"

    printf 'Installing required build, Git, TLS, and Playwright runtime libraries.\n'

    run_as_root pacman \
        --sync \
        --refresh \
        --needed \
        --noconfirm \
        "${PACMAN_PACKAGES[@]}"
}

ensure_local_bin() {
    mkdir -p "$UV_INSTALL_DIR"

    export PATH="${UV_INSTALL_DIR}:${PATH}"

    if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    fi
}

install_uv() {
    section "2. UV PACKAGE MANAGER"

    ensure_local_bin

    if command -v uv >/dev/null 2>&1; then
        printf 'Existing uv: %s\n' "$(command -v uv)"
        uv --version
    else
        printf 'Installing uv into %s\n' "$UV_INSTALL_DIR"

        curl \
            --proto '=https' \
            --tlsv1.2 \
            -LsSf \
            https://astral.sh/uv/install.sh |
            env UV_INSTALL_DIR="$UV_INSTALL_DIR" sh

        hash -r
    fi

    command -v uv >/dev/null 2>&1 || die "uv installation completed but uv is not on PATH."

    printf 'Using uv: %s\n' "$(command -v uv)"
    uv --version
}

configure_shell_path() {
    section "3. BASH PATH CONFIGURATION"

    local bashrc="${HOME}/.bashrc"
    local marker_start="# >>> docsync local bin >>>"
    local marker_end="# <<< docsync local bin <<<"

    touch "$bashrc"

    if ! grep -Fq "$marker_start" "$bashrc"; then
        {
            printf '\n%s\n' "$marker_start"
            printf 'export PATH="$HOME/.local/bin:$PATH"\n'
            printf '%s\n' "$marker_end"
        } >> "$bashrc"

        printf 'Added ~/.local/bin to PATH in %s\n' "$bashrc"
    else
        printf 'PATH configuration already exists in %s\n' "$bashrc"
    fi
}

prepare_repository() {
    section "4. DOCSYNC REPOSITORY"

    mkdir -p "$(dirname "$PROJECT_DIR")"

    if [[ -d "$PROJECT_DIR/.git" ]]; then
        printf 'Existing repository detected: %s\n' "$PROJECT_DIR"

        git -C "$PROJECT_DIR" remote get-url origin >/dev/null 2>&1 ||
            die "Existing project has no origin remote."

        printf 'Origin: %s\n' "$(git -C "$PROJECT_DIR" remote get-url origin)"

        if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
            printf '\nExisting repository contains local changes.\n'
            printf 'The bootstrap will preserve them and will NOT perform git pull.\n'
        else
            printf 'Repository is clean; updating from origin/master.\n'

            git -C "$PROJECT_DIR" fetch --prune origin

            if git -C "$PROJECT_DIR" show-ref --verify --quiet refs/remotes/origin/master; then
                git -C "$PROJECT_DIR" checkout master
                git -C "$PROJECT_DIR" merge --ff-only origin/master
            fi
        fi
    elif [[ -e "$PROJECT_DIR" ]]; then
        if [[ -n "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
            die "Target exists and is not an empty Git repository: $PROJECT_DIR"
        fi

        rmdir "$PROJECT_DIR"
        git clone "$REPOSITORY_URL" "$PROJECT_DIR"
    else
        git clone "$REPOSITORY_URL" "$PROJECT_DIR"
    fi

    [[ -f "$PROJECT_DIR/pyproject.toml" ]] || die "pyproject.toml is missing."
    [[ -f "$PROJECT_DIR/uv.lock" ]] || die "uv.lock is missing."
    [[ -f "$PROJECT_DIR/.python-version" ]] || die ".python-version is missing."

    printf '\nRepository revision:\n'
    git -C "$PROJECT_DIR" log -1 --oneline --decorate
}

validate_project_contract() {
    section "5. PROJECT CONTRACT"

    local requested_python

    requested_python="$(
        tr -d '[:space:]' < "$PROJECT_DIR/.python-version"
    )"

    [[ "$requested_python" == "3.13" ]] ||
        die "Expected .python-version to request Python 3.13; found '$requested_python'."

    grep -Fq 'requires-python = ">=3.13"' "$PROJECT_DIR/pyproject.toml" ||
        die "pyproject.toml no longer contains the expected Python >=3.13 requirement."

    grep -Fq '"crawlee[beautifulsoup,curl-impersonate,playwright]==1.9.1"' \
        "$PROJECT_DIR/pyproject.toml" ||
        die "The expected Crawlee 1.9.1 dependency contract changed."

    grep -Fq 'docsync = "docsync.cli:main"' "$PROJECT_DIR/pyproject.toml" ||
        die "The docsync CLI entry point is missing."

    printf 'Python contract:      3.13\n'
    printf 'Crawlee contract:     1.9.1\n'
    printf 'CLI entry point:      docsync.cli:main\n'
    printf 'Dependency lock file: %s\n' "$PROJECT_DIR/uv.lock"
}

install_python() {
    section "6. MANAGED PYTHON 3.13"

    cd "$PROJECT_DIR"

    uv python install 3.13

    printf '\nAvailable matching Python installations:\n'
    uv python list 3.13

    printf '\nProject Python selection:\n'
    uv run --no-sync python -VV 2>/dev/null || true
}

synchronize_environment() {
    section "7. LOCKED PYTHON ENVIRONMENT"

    cd "$PROJECT_DIR"

    printf 'Checking uv.lock consistency.\n'
    uv lock --check

    printf '\nSynchronizing exactly from the existing lock file.\n'
    uv sync --frozen

    printf '\nResolved project interpreter:\n'
    uv run python - <<'PY'
from __future__ import annotations

import platform
import sys

print(f"implementation={platform.python_implementation()}")
print(f"version={platform.python_version()}")
print(f"executable={sys.executable}")

if sys.version_info[:2] != (3, 13):
    raise SystemExit(
        "ERROR: docsync must use the uv-managed Python 3.13 interpreter."
    )
PY
}

install_playwright_browser() {
    section "8. PLAYWRIGHT CHROMIUM"

    cd "$PROJECT_DIR"

    printf 'Installing the Chromium revision required by the locked Playwright package.\n'
    uv run playwright install chromium

    printf '\nPlaywright version:\n'
    uv run playwright --version
}

verify_imports() {
    section "9. PYTHON DEPENDENCY VERIFICATION"

    cd "$PROJECT_DIR"

    uv run python - <<'PY'
from __future__ import annotations

import importlib
import importlib.metadata
import sys

expected_versions = {
    "crawlee": "1.9.1",
    "playwright": "1.61.0",
}

required_modules = (
    "bs4",
    "crawlee",
    "defusedxml",
    "httpx",
    "langdetect",
    "libcst",
    "lingua",
    "markdownify",
    "playwright",
    "rich",
)

failures: list[str] = []

for module_name in required_modules:
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        failures.append(
            f"{module_name}: {type(error).__name__}: {error}"
        )
        continue

    print(
        f"IMPORT OK  {module_name:<20} "
        f"{getattr(module, '__file__', '<namespace>')}"
    )

for distribution_name, expected_version in expected_versions.items():
    try:
        installed_version = importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        failures.append(
            f"{distribution_name}: distribution metadata missing"
        )
        continue

    print(
        f"VERSION    {distribution_name:<20} "
        f"{installed_version}"
    )

    if installed_version != expected_version:
        failures.append(
            f"{distribution_name}: expected {expected_version}, "
            f"found {installed_version}"
        )

if sys.version_info[:2] != (3, 13):
    failures.append(
        f"python: expected 3.13, found "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )

if failures:
    print("\nDEPENDENCY VERIFICATION FAILED", file=sys.stderr)

    for failure in failures:
        print(f" - {failure}", file=sys.stderr)

    raise SystemExit(1)

print("\nAll required Python imports and pinned core versions are valid.")
PY
}

verify_cli() {
    section "10. DOCSYNC CLI VERIFICATION"

    cd "$PROJECT_DIR"

    uv run docsync --help

    printf '\nCLI entry point resolved successfully.\n'
}

verify_browser() {
    section "11. REAL PLAYWRIGHT BROWSER LAUNCH"

    cd "$PROJECT_DIR"

    uv run python - <<'PY'
from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as playwright:
        executable_path = playwright.chromium.executable_path

        print(f"Playwright Chromium executable: {executable_path}")

        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--no-first-run",
            ],
        )

        try:
            page = await browser.new_page()

            await page.set_content(
                """
                <!doctype html>
                <html lang="en">
                    <head>
                        <title>docsync bootstrap verification</title>
                    </head>
                    <body>
                        <main>
                            <h1>docsync browser verification</h1>
                        </main>
                    </body>
                </html>
                """
            )

            title = await page.title()
            heading = await page.locator("h1").inner_text()

            if title != "docsync bootstrap verification":
                raise RuntimeError(
                    f"Unexpected browser title: {title!r}"
                )

            if heading != "docsync browser verification":
                raise RuntimeError(
                    f"Unexpected browser content: {heading!r}"
                )

            print(f"Browser title: {title}")
            print(f"Browser content: {heading}")
            print("Playwright Chromium launch: OK")
        finally:
            await browser.close()


asyncio.run(main())
PY
}

verify_source_compilation() {
    section "12. SOURCE COMPILATION"

    cd "$PROJECT_DIR"

    uv run python -m compileall \
        -q \
        src \
        main.py

    printf 'Python source compilation: OK\n'
}

create_runtime_directories() {
    section "13. RUNTIME DIRECTORIES"

    cd "$PROJECT_DIR"

    mkdir -p \
        data/markdown \
        data/state \
        logs \
        output \
        storage

    printf 'Created/verified:\n'
    printf '  %s\n' \
        "$PROJECT_DIR/data/markdown" \
        "$PROJECT_DIR/data/state" \
        "$PROJECT_DIR/logs" \
        "$PROJECT_DIR/output" \
        "$PROJECT_DIR/storage"
}

install_global_wrapper() {
    section "14. GLOBAL DOCSYNC COMMAND"

    ensure_local_bin

    cat > "$DOCSYNC_WRAPPER" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=$(printf '%q' "$PROJECT_DIR")

if [[ ! -f "\$PROJECT_DIR/pyproject.toml" ]]; then
    printf 'docsync project not found: %s\n' "\$PROJECT_DIR" >&2
    exit 1
fi

exec uv run \
    --project "\$PROJECT_DIR" \
    --frozen \
    docsync "\$@"
EOF

    chmod 0755 "$DOCSYNC_WRAPPER"

    printf 'Installed command: %s\n' "$DOCSYNC_WRAPPER"

    "$DOCSYNC_WRAPPER" --help >/dev/null

    printf 'Global docsync wrapper: OK\n'
}

run_project_smoke_test() {
    section "15. OFFLINE PROJECT SMOKE TEST"

    cd "$PROJECT_DIR"

    uv run python - <<'PY'
from __future__ import annotations

import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
    normalize_start_url,
)
from docsync.language import EnglishPageDetector
from docsync.markdown import MarkdownExporter

start_url = normalize_start_url("https://example.com/docs")
scope = build_scope_pattern(start_url)

html = """
<!doctype html>
<html lang="en">
<head>
    <title>Docsync Bootstrap Test</title>
</head>
<body>
    <main>
        <h1>Docsync Bootstrap Test</h1>
        <p>
            This local document contains enough English documentation text
            to verify the extraction, language, URL discovery, Markdown
            conversion, hashing, and file persistence portions of docsync
            without depending on an external website during installation.
        </p>
        <p>
            The bootstrap verification intentionally runs offline so that
            network availability or a third-party website cannot make a
            correct installation appear broken.
        </p>
        <a href="/docs/guide">Guide</a>
    </main>
</body>
</html>
"""

soup = BeautifulSoup(html, "lxml")

links = extract_in_scope_links(
    soup=soup,
    base_url=start_url,
    scope_pattern=scope,
)

if links != ["https://example.com/docs/guide"]:
    raise RuntimeError(
        f"Unexpected discovered links: {links!r}"
    )

decision = EnglishPageDetector().detect_from_html(
    url=start_url,
    html=html,
)

if not decision.is_english:
    raise RuntimeError(
        f"Language detector rejected bootstrap document: {decision!r}"
    )

with tempfile.TemporaryDirectory(
    prefix="docsync-bootstrap-",
) as temporary_directory:
    exporter = MarkdownExporter(
        Path(temporary_directory)
    )

    document = exporter.export(
        url=start_url,
        soup=soup,
        title="Docsync Bootstrap Test",
        language="en",
    )

    if not document.output_path.is_file():
        raise RuntimeError(
            "Markdown output was not created."
        )

    text = document.output_path.read_text(
        encoding="utf-8"
    )

    if "Docsync Bootstrap Test" not in text:
        raise RuntimeError(
            "Markdown output does not contain expected content."
        )

    if document.content_hash not in text:
        raise RuntimeError(
            "Markdown output does not contain expected content hash."
        )

print("URL normalization: OK")
print("Scope filtering: OK")
print("Link discovery: OK")
print("Language detection: OK")
print("Markdown export: OK")
print("Atomic persistence: OK")
print("Offline docsync smoke test: OK")
PY
}

print_final_summary() {
    section "BOOTSTRAP COMPLETE"

    cd "$PROJECT_DIR"

    printf 'Project directory: %s\n' "$PROJECT_DIR"
    printf 'Repository:        %s\n' "$REPOSITORY_URL"
    printf 'Revision:          %s\n' "$(git rev-parse --short HEAD)"
    printf 'uv:                %s\n' "$(uv --version)"
    printf 'Python:            %s\n' "$(uv run python -c 'import platform; print(platform.python_version())')"
    printf 'Crawlee:           %s\n' "$(uv run python -c 'import importlib.metadata; print(importlib.metadata.version("crawlee"))')"
    printf 'Playwright:        %s\n' "$(uv run python -c 'import importlib.metadata; print(importlib.metadata.version("playwright"))')"
    printf 'Command:           %s\n' "$DOCSYNC_WRAPPER"

    printf '\n'
    printf '%s\n' 'All bootstrap verification stages passed.'
    printf '%s\n' 'Open a new Bash shell, or run:'
    printf '\n'
    printf '    export PATH="$HOME/.local/bin:$PATH"\n'
    printf '\n'
    printf '%s\n' 'Then docsync can be invoked directly:'
    printf '\n'
    printf '    docsync https://example.com/docs --language en\n'
    printf '\n'
    printf '%s\n' 'Playwright mode:'
    printf '\n'
    printf '    docsync https://example.com/docs --language en --mode playwright --browser-type chromium\n'
    printf '\n'
    printf '%s\n' 'A production-style example:'
    printf '\n'
    printf '%s\n' \
        '    docsync \' \
        '      https://developers.google.com/search/ \' \
        '      --output-dir "$HOME/docs/developers.google.com" \' \
        '      --state-dir "$HOME/docs/developers.google.com" \' \
        '      --max-concurrency 2 \' \
        '      --max-requests 3000 \' \
        '      --requests-per-minute 20 \' \
        '      --language en \' \
        '      --refresh-hours 24 \' \
        '      --mode playwright \' \
        '      --browser-type chromium'
}

main() {
    section "DOCSYNC ARCH LINUX BOOTSTRAP"

    printf 'Started:       %s\n' "$(date --iso-8601=seconds)"
    printf 'User:          %s\n' "$(id -un)"
    printf 'Architecture:  %s\n' "$(uname -m)"
    printf 'Project:       %s\n' "$PROJECT_DIR"
    printf 'Repository:    %s\n' "$REPOSITORY_URL"

    ensure_arch_linux
    install_system_packages
    install_uv
    configure_shell_path
    prepare_repository
    validate_project_contract
    install_python
    synchronize_environment
    install_playwright_browser
    create_runtime_directories
    verify_imports
    verify_cli
    verify_browser
    verify_source_compilation
    run_project_smoke_test
    install_global_wrapper
    print_final_summary
}

main "$@"

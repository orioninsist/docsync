#!/usr/bin/env python3
"""
DocSync bootstrap dependency auditor.

Amaç:
- Projeyi değiştirmeden bağımlılık envanteri çıkarmak.
- Python paketlerini, geliştirme araçlarını ve harici Linux komutlarını bulmak.
- Sıfırdan Fedora kurulumu için hazırlanacak bootstrap scriptine veri sağlamak.

Bu script yalnızca Python standart kütüphanesini kullanır.
"""

from __future__ import annotations

# pylint: disable=too-many-lines
# pylint: disable=missing-function-docstring
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
# pylint: disable=too-many-nested-blocks


import ast
import configparser
import json
import os
import platform
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path.cwd().resolve()

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    "logs",
}

PYTHON_MANIFEST_NAMES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements.in",
    "requirements-dev.in",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "poetry.lock",
    "pdm.lock",
    "uv.lock",
}

SHELL_SUFFIXES = {
    ".sh",
    ".bash",
    ".zsh",
}

TEXT_CONFIG_SUFFIXES = {
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".service",
    ".socket",
    ".timer",
    ".md",
    ".txt",
}

COMMON_COMMANDS = {
    "bash",
    "sh",
    "zsh",
    "python",
    "python3",
    "pip",
    "pip3",
    "uv",
    "poetry",
    "pdm",
    "pytest",
    "ruff",
    "mypy",
    "pyright",
    "black",
    "isort",
    "coverage",
    "pre-commit",
    "git",
    "curl",
    "wget",
    "jq",
    "rsync",
    "tar",
    "gzip",
    "unzip",
    "zip",
    "make",
    "gcc",
    "g++",
    "clang",
    "pkg-config",
    "openssl",
    "sqlite3",
    "psql",
    "redis-cli",
    "docker",
    "podman",
    "systemctl",
    "journalctl",
    "timeout",
    "xargs",
    "sed",
    "awk",
    "grep",
    "find",
    "sort",
    "head",
    "tail",
    "cut",
    "tr",
    "wc",
    "nl",
    "tee",
    "realpath",
    "readlink",
    "mktemp",
    "env",
}

SHELL_KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "while",
    "until",
    "do",
    "done",
    "case",
    "esac",
    "in",
    "function",
    "select",
    "time",
    "coproc",
    "local",
    "declare",
    "readonly",
    "export",
    "unset",
    "set",
    "shift",
    "return",
    "exit",
    "break",
    "continue",
    "source",
    ".",
    "true",
    "false",
    "echo",
    "printf",
    "test",
    "[",
    "[[",
    "{",
    "}",
}

STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))

IMPORT_TO_DNF_HINTS = {
    "bs4": ["python3-beautifulsoup4"],
    "lxml": ["python3-lxml", "libxml2-devel", "libxslt-devel"],
    "psycopg": ["libpq-devel", "gcc", "python3-devel"],
    "psycopg2": ["libpq-devel", "gcc", "python3-devel"],
    "mysqlclient": ["mariadb-connector-c-devel", "gcc", "python3-devel"],
    "MySQLdb": ["mariadb-connector-c-devel", "gcc", "python3-devel"],
    "cryptography": ["openssl-devel", "libffi-devel", "gcc", "python3-devel"],
    "cffi": ["libffi-devel", "gcc", "python3-devel"],
    "PIL": ["libjpeg-turbo-devel", "zlib-devel", "freetype-devel"],
    "playwright": ["nss", "atk", "at-spi2-atk", "libXcomposite", "libXdamage"],
    "selenium": ["chromium", "chromedriver"],
    "weasyprint": ["pango", "cairo", "gdk-pixbuf2"],
}

COMMAND_TO_DNF_HINTS = {
    "bash": ["bash"],
    "zsh": ["zsh"],
    "python": ["python3"],
    "python3": ["python3"],
    "pip": ["python3-pip"],
    "pip3": ["python3-pip"],
    "git": ["git"],
    "curl": ["curl"],
    "wget": ["wget"],
    "jq": ["jq"],
    "rsync": ["rsync"],
    "tar": ["tar"],
    "gzip": ["gzip"],
    "unzip": ["unzip"],
    "zip": ["zip"],
    "make": ["make"],
    "gcc": ["gcc"],
    "g++": ["gcc-c++"],
    "clang": ["clang"],
    "pkg-config": ["pkgconf-pkg-config"],
    "openssl": ["openssl"],
    "sqlite3": ["sqlite"],
    "psql": ["postgresql"],
    "redis-cli": ["redis"],
    "podman": ["podman"],
    "systemctl": ["systemd"],
    "journalctl": ["systemd"],
    "timeout": ["coreutils"],
    "xargs": ["findutils"],
    "sed": ["sed"],
    "awk": ["gawk"],
    "grep": ["grep"],
    "find": ["findutils"],
    "sort": ["coreutils"],
    "head": ["coreutils"],
    "tail": ["coreutils"],
    "cut": ["coreutils"],
    "tr": ["coreutils"],
    "wc": ["coreutils"],
    "nl": ["coreutils"],
    "tee": ["coreutils"],
    "realpath": ["coreutils"],
    "readlink": ["coreutils"],
    "mktemp": ["coreutils"],
}


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def iter_project_files() -> Iterable[Path]:
    for root, directories, filenames in os.walk(PROJECT_ROOT):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in IGNORED_DIRECTORIES
        )

        root_path = Path(root)

        for filename in sorted(filenames):
            path = root_path / filename

            try:
                if path.is_symlink() or path.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue

            yield path


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def run_command(command: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])

    if executable is None:
        return {
            "available": False,
            "command": command,
            "output": None,
        }

    try:
        result = subprocess.run(  # nosec B603
            command,
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": True,
            "command": command,
            "output": f"ERROR: {exc}",
        }

    return {
        "available": True,
        "command": command,
        "exit_code": result.returncode,
        "output": result.stdout.strip(),
    }


def read_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    result: dict[str, str] = {}

    text = read_text(path)
    if text is None:
        return result

    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue

        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"')

    return result


def detect_manifest_files(files: Iterable[Path]) -> list[str]:
    manifests = []

    for path in files:
        if path.name in PYTHON_MANIFEST_NAMES:
            manifests.append(relative(path))

    return sorted(manifests)


def normalize_requirement_name(value: str) -> str | None:
    candidate = value.strip()

    if not candidate or candidate.startswith(("#", "-", "git+", "http:", "https:")):
        return None

    candidate = candidate.split(";", 1)[0].strip()
    candidate = re.split(r"[<>=!~\[\s]", candidate, maxsplit=1)[0].strip()

    if not candidate:
        return None

    return candidate


def parse_requirements_file(path: Path) -> set[str]:
    packages: set[str] = set()
    text = read_text(path)

    if text is None:
        return packages

    continuation = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if continuation:
            line = continuation + line
            continuation = ""

        if line.endswith("\\"):
            continuation = line[:-1]
            continue

        requirement = normalize_requirement_name(line)
        if requirement:
            packages.add(requirement)

    return packages


def parse_setup_cfg(path: Path) -> set[str]:
    packages: set[str] = set()
    parser = configparser.ConfigParser()

    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return packages

    for section, option in (
        ("options", "install_requires"),
        ("options.extras_require", "dev"),
        ("options.extras_require", "test"),
    ):
        if not parser.has_option(section, option):
            continue

        for line in parser.get(section, option).splitlines():
            requirement = normalize_requirement_name(line)
            if requirement:
                packages.add(requirement)

    return packages


def parse_pyproject_with_tomllib(path: Path) -> set[str]:
    packages: set[str] = set()

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return packages

    project = data.get("project", {})
    if isinstance(project, dict):
        for item in project.get("dependencies", []):
            if isinstance(item, str):
                requirement = normalize_requirement_name(item)
                if requirement:
                    packages.add(requirement)

        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for requirements in optional.values():
                if not isinstance(requirements, list):
                    continue
                for item in requirements:
                    if isinstance(item, str):
                        requirement = normalize_requirement_name(item)
                        if requirement:
                            packages.add(requirement)

    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        return packages

    poetry = tool.get("poetry", {})
    if isinstance(poetry, dict):
        dependency_sections = [poetry.get("dependencies", {})]

        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict):
                    dependency_sections.append(group.get("dependencies", {}))

        for section in dependency_sections:
            if not isinstance(section, dict):
                continue
            for name in section:
                if str(name).lower() != "python":
                    packages.add(str(name))

    return packages


def detect_declared_python_packages(manifests: Iterable[str]) -> set[str]:
    packages: set[str] = set()

    for manifest in manifests:
        path = PROJECT_ROOT / manifest

        if path.name.startswith("requirements"):
            packages.update(parse_requirements_file(path))
        elif path.name == "setup.cfg":
            packages.update(parse_setup_cfg(path))
        elif path.name == "pyproject.toml":
            packages.update(parse_pyproject_with_tomllib(path))

    return packages


def extract_python_imports(files: Iterable[Path]) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = defaultdict(set)

    for path in files:
        if path.suffix != ".py":
            continue

        source = read_text(path)
        if source is None:
            continue

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            module_name: str | None = None

            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    imports[root].add(relative(path))

            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    module_name = node.module.split(".", 1)[0]

                if module_name:
                    imports[module_name].add(relative(path))

    return imports


def detect_local_modules(files: Iterable[Path]) -> set[str]:
    modules: set[str] = set()

    for path in files:
        if path.suffix != ".py":
            continue

        relative_path = path.relative_to(PROJECT_ROOT)

        if len(relative_path.parts) == 1:
            modules.add(path.stem)
        else:
            modules.add(relative_path.parts[0])

        if path.name == "__init__.py" and len(relative_path.parts) > 1:
            modules.add(relative_path.parts[-2])

    return modules


def classify_imports(
    imports: dict[str, set[str]],
    local_modules: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    third_party: dict[str, set[str]] = {}
    standard_or_local: dict[str, set[str]] = {}

    for module, locations in sorted(imports.items()):
        if module in STDLIB_MODULES or module in local_modules:
            standard_or_local[module] = locations
            continue

        third_party[module] = locations

    return third_party, standard_or_local


def shell_first_token(command: str) -> str | None:
    cleaned = command.strip()

    if not cleaned:
        return None

    cleaned = re.sub(
        r"^(?:sudo|command|env|exec|nohup|time)\s+",
        "",
        cleaned,
    )

    try:
        tokens = shlex.split(cleaned, posix=True)
    except ValueError:
        tokens = cleaned.split()

    if not tokens:
        return None

    token = tokens[0]
    token = token.split("/")[-1]

    if "=" in token and not token.startswith("="):
        for item in tokens[1:]:
            if "=" not in item:
                token = item.split("/")[-1]
                break

    token = token.strip(";&|(){}")

    if (
        not token
        or token in SHELL_KEYWORDS
        or token.startswith(("$", "-", "#"))
        or not re.fullmatch(r"[A-Za-z0-9_.+-]+", token)
    ):
        return None

    return token


def extract_shell_commands(files: Iterable[Path]) -> dict[str, set[str]]:
    commands: dict[str, set[str]] = defaultdict(set)

    separators = re.compile(r"(?:^|&&|\|\||[;|])\s*")

    for path in files:
        if path.suffix not in SHELL_SUFFIXES and path.name not in {
            "quality.sh",
            "Makefile",
            "Justfile",
        }:
            continue

        text = read_text(path)
        if text is None:
            continue

        for line in text.splitlines():
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            for part in separators.split(stripped):
                command = shell_first_token(part)
                if command:
                    commands[command].add(relative(path))

    return commands


def string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        first = node.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value

    return None


def extract_subprocess_commands(files: Iterable[Path]) -> dict[str, set[str]]:
    commands: dict[str, set[str]] = defaultdict(set)

    for path in files:
        if path.suffix != ".py":
            continue

        source = read_text(path)
        if source is None:
            continue

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            function_name = ""

            if isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                function_name = node.func.id

            if function_name not in {
                "run",
                "Popen",
                "call",
                "check_call",
                "check_output",
                "system",
                "execvp",
                "execvpe",
            }:
                continue

            if not node.args:
                continue

            command_value = string_value(node.args[0])
            if command_value is None:
                continue

            command = shell_first_token(command_value)
            if command:
                commands[command].add(relative(path))

    return commands


def extract_command_mentions(files: Iterable[Path]) -> dict[str, set[str]]:
    mentions: dict[str, set[str]] = defaultdict(set)

    pattern = re.compile(
        r"(?<![A-Za-z0-9_.+-])("
        + "|".join(re.escape(command) for command in sorted(COMMON_COMMANDS))
        + r")(?![A-Za-z0-9_.+-])"
    )

    for path in files:
        if (
            path.suffix not in TEXT_CONFIG_SUFFIXES
            and path.suffix not in SHELL_SUFFIXES
            and path.name not in {"Makefile", "Justfile"}
        ):
            continue

        text = read_text(path)
        if text is None:
            continue

        for match in pattern.finditer(text):
            mentions[match.group(1)].add(relative(path))

    return mentions


def merge_command_sources(
    *sources: dict[str, set[str]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)

    for source in sources:
        for command, locations in source.items():
            result[command].update(locations)

    return dict(sorted(result.items()))


def command_version(command: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None

    candidates = (
        [command, "--version"],
        [command, "-V"],
        [command, "version"],
    )

    for candidate in candidates:
        try:
            result = subprocess.run(  # nosec B603
                candidate,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        output = result.stdout.strip()
        if output:
            return output.splitlines()[0][:240]

    return executable


def build_dnf_hints(
    third_party_imports: dict[str, set[str]],
    commands: dict[str, set[str]],
) -> list[str]:
    hints = {
        "ca-certificates",
        "git",
        "python3",
        "python3-pip",
    }

    for module in third_party_imports:
        hints.update(IMPORT_TO_DNF_HINTS.get(module, []))

    for command in commands:
        hints.update(COMMAND_TO_DNF_HINTS.get(command, []))

    return sorted(hints)


def detect_ci_files(files: Iterable[Path]) -> list[str]:
    result = []

    for path in files:
        rel = relative(path)

        if (
            rel.startswith(".github/workflows/")
            or rel.startswith(".gitlab-ci")
            or path.name
            in {
                "tox.ini",
                "noxfile.py",
                "Jenkinsfile",
                ".pre-commit-config.yaml",
                ".pre-commit-config.yml",
            }
        ):
            result.append(rel)

    return sorted(result)


def detect_entrypoints(files: Iterable[Path]) -> list[str]:
    result = []

    for path in files:
        if path.suffix != ".py":
            continue

        text = read_text(path)
        if text is None:
            continue

        if (
            'if __name__ == "__main__"' in text
            or "if __name__ == '__main__'" in text
            or path.name.endswith("_cli.py")
            or path.name in {"cli.py", "main.py", "__main__.py"}
        ):
            result.append(relative(path))

    return sorted(result)


def count_source_files(files: Iterable[Path]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)

    for path in files:
        suffix = path.suffix.lower() or "<no suffix>"
        counts[suffix] += 1

    return dict(sorted(counts.items()))


def get_git_status() -> dict[str, Any]:
    if shutil.which("git") is None:
        return {
            "available": False,
            "output": "git bulunamadı",
        }

    inside = run_command(["git", "rev-parse", "--is-inside-work-tree"])

    if inside.get("exit_code") != 0:
        return {
            "available": True,
            "output": "Dizin bir Git çalışma ağacı değil",
        }

    branch = run_command(["git", "branch", "--show-current"])
    status = run_command(["git", "status", "--short"])

    return {
        "available": True,
        "branch": branch.get("output") or "<detached>",
        "status": status.get("output") or "<clean>",
    }


def print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def print_mapping(mapping: dict[str, set[str]]) -> None:
    if not mapping:
        print("<bulunamadı>")
        return

    for key, locations in mapping.items():
        location_text = ", ".join(sorted(locations)[:8])

        if len(locations) > 8:
            location_text += f", ... (+{len(locations) - 8})"

        print(f"- {key}: {location_text}")


def main() -> int:
    files = list(iter_project_files())
    manifests = detect_manifest_files(files)
    declared_packages = detect_declared_python_packages(manifests)
    all_imports = extract_python_imports(files)
    local_modules = detect_local_modules(files)
    third_party_imports, _ = classify_imports(all_imports, local_modules)

    shell_commands = extract_shell_commands(files)
    subprocess_commands = extract_subprocess_commands(files)
    mentioned_commands = extract_command_mentions(files)

    commands = merge_command_sources(
        shell_commands,
        subprocess_commands,
        mentioned_commands,
    )

    os_release = read_os_release()
    dnf_hints = build_dnf_hints(third_party_imports, commands)

    available_commands: dict[str, str] = {}
    missing_commands: list[str] = []

    for command in sorted(commands):
        version = command_version(command)

        if version is None:
            missing_commands.append(command)
        else:
            available_commands[command] = version

    git_status = get_git_status()
    file_counts = count_source_files(files)
    ci_files = detect_ci_files(files)
    entrypoints = detect_entrypoints(files)

    report: dict[str, Any] = {
        "project_root": str(PROJECT_ROOT),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.replace("\n", " "),
            "python_executable": sys.executable,
            "os_release": os_release,
        },
        "git": git_status,
        "file_counts": file_counts,
        "manifests": manifests,
        "declared_python_packages": sorted(declared_packages),
        "third_party_imports": {
            name: sorted(locations) for name, locations in third_party_imports.items()
        },
        "commands": {name: sorted(locations) for name, locations in commands.items()},
        "available_commands": available_commands,
        "missing_commands": missing_commands,
        "dnf_package_hints": dnf_hints,
        "ci_files": ci_files,
        "entrypoints": entrypoints,
    }

    print_section("DOCSYNC BOOTSTRAP BAĞIMLILIK ANALİZİ")
    print(f"Proje kökü       : {PROJECT_ROOT}")
    print(f"İşletim sistemi  : {os_release.get('PRETTY_NAME', platform.platform())}")
    print(f"Mimari           : {platform.machine()}")
    print(f"Python           : {sys.version.splitlines()[0]}")
    print(f"Python executable: {sys.executable}")
    print(f"Toplam dosya     : {len(files)}")

    print_section("1. GIT DURUMU")
    print(f"Git mevcut : {git_status.get('available')}")

    if "branch" in git_status:
        print(f"Branch      : {git_status['branch']}")
        print("Durum:")
        print(git_status["status"])
    else:
        print(git_status.get("output", "<bilinmiyor>"))

    print_section("2. DOSYA TÜRLERİ")
    for suffix, count in file_counts.items():
        print(f"- {suffix}: {count}")

    print_section("3. PYTHON BAĞIMLILIK DOSYALARI")
    if manifests:
        for manifest in manifests:
            print(f"- {manifest}")
    else:
        print("<Python manifest dosyası bulunamadı>")

    print_section("4. MANİFESTLERDE TANIMLI PYTHON PAKETLERİ")
    if declared_packages:
        for package in sorted(declared_packages):
            print(f"- {package}")
    else:
        print("<tanımlı paket bulunamadı veya manifest ayrıştırılamadı>")

    print_section("5. KAYNAK KODDAKİ ÜÇÜNCÜ TARAF IMPORTLAR")
    print_mapping(third_party_imports)

    print_section("6. HARİCİ LINUX / GELİŞTİRME KOMUTLARI")
    print_mapping(commands)

    print_section("7. MEVCUT KOMUTLAR")
    if available_commands:
        for command, version in available_commands.items():
            print(f"- {command}: {version}")
    else:
        print("<algılanan komutlardan hiçbiri PATH içinde bulunamadı>")

    print_section("8. EKSİK KOMUTLAR")
    if missing_commands:
        for command in missing_commands:
            print(f"- {command}")
    else:
        print("<algılanan tüm komutlar mevcut>")

    print_section("9. MUHTEMEL FEDORA DNF PAKETLERİ")
    print("Not: Bunlar analiz ipuçlarıdır; nihai scriptte doğrulanacaktır.")

    for package in dnf_hints:
        print(f"- {package}")

    print_section("10. GİRİŞ NOKTALARI")
    if entrypoints:
        for path in entrypoints:
            print(f"- {path}")
    else:
        print("<belirgin Python giriş noktası bulunamadı>")

    print_section("11. CI / KALİTE YAPILANDIRMALARI")
    if ci_files:
        for path in ci_files:
            print(f"- {path}")
    else:
        print("<CI veya kalite yapılandırması bulunamadı>")

    print_section("12. MAKİNECE OKUNABİLİR JSON RAPORU")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    print_section("ANALİZ TAMAMLANDI")
    print(
        "Yukarıdaki çıktının tamamını paylaşın. "
        "Sonraki adımda Fedora tabanlı, idempotent ve hata toleranslı "
        "sıfır-kurulum bootstrap scripti hazırlanacaktır."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

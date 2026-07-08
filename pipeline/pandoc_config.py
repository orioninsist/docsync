#!/usr/bin/env python3

from pathlib import Path

# ============================================================
# PANDOC CONFIGURATION SANDBOX
# ============================================================
#
# Bu bölüm özellikle kullanıcı tarafından değiştirilmek üzere
# tasarlanmıştır.
#
# Pipeline'ın geri kalan mantığına dokunmadan sadece buradaki
# parametreleri düzenleyebilirsiniz.
#
# ============================================================

PANDOC_BINARY = "pandoc"

PANDOC_ARGS = [
    "--from=gfm",
    "--to=gfm",
    "--wrap=none",
    "--standalone",
]

OUTPUT_FORMAT = "md"

TEMP_DIR = Path("pipeline_temp")

ENABLE_PANDOC = False

# ============================================================
# END OF USER CONFIGURATION AREA
# ============================================================


def get_pandoc_args() -> list[str]:
    return list(PANDOC_ARGS)


def get_pandoc_binary() -> str:
    return PANDOC_BINARY


def get_output_format() -> str:
    return OUTPUT_FORMAT


def is_pandoc_enabled() -> bool:
    return ENABLE_PANDOC


def get_temp_dir() -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR

from pathlib import Path

from crawler.queue_file import read_urls_from_txt


def test_read_urls_from_txt_ignores_blank_lines_and_comments(tmp_path: Path) -> None:
    queue_file = tmp_path / "openai_queue.txt"
    queue_file.write_text(
        "\n".join(
            [
                "# human review comment",
                "",
                "https://platform.openai.com/docs",
                "   ",
                "# https://platform.openai.com/blocked",
                "https://platform.openai.com/docs/guides",
            ]
        ),
        encoding="utf-8",
    )

    assert read_urls_from_txt(queue_file) == [
        "https://platform.openai.com/docs",
        "https://platform.openai.com/docs/guides",
    ]

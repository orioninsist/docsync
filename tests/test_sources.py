from __future__ import annotations

from pathlib import Path

from docsync.sources import _jsdoc_to_markdown


def test_phaser_jsdoc_is_rendered_as_source_documentation() -> None:
    source = """
/**
 * @classdesc A Sprite Game Object.
 *
 * @class Sprite
 * @memberof Phaser.GameObjects
 * @since 3.0.0
 *
 * @param {number} x - Horizontal position.
 */
var Sprite = {};
"""
    markdown = _jsdoc_to_markdown("src/gameobjects/sprite/Sprite.js", source)

    assert "# src/gameobjects/sprite/Sprite.js" in markdown
    assert "official Phaser repository JSDoc" in markdown
    assert "not a mirror of docs.phaser.io" in markdown
    assert "A Sprite Game Object." in markdown
    assert "- **class:** Sprite" in markdown
    assert "- **memberof:** Phaser.GameObjects" in markdown
    assert "- **since:** 3.0.0" in markdown
    assert "- **param:** {number} x - Horizontal position." in markdown


def test_source_selection_precedes_engine_selection() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/docsync/cli.py").read_text(encoding="utf-8")

    source_branch = source.index('if args.source != "web":')
    typescript_branch = source.index('if args.engine == "typescript":')
    python_call = source.index("run_crawler(")

    assert source_branch < typescript_branch
    assert source_branch < python_call

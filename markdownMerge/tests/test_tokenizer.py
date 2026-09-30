from markdown_merge.tokenizer import TokenCounter, count_tokens


def test_count_tokens() -> None:
    assert count_tokens("hello world") > 0


def test_explicit_encoding() -> None:
    counter = TokenCounter(model=None, encoding_name="o200k_base")

    assert counter.count("hello world") > 0

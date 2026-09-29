use docpack::splitter::split_by_tokens;
use docpack::token::TokenCounter;

#[test]
fn splits_large_markdown_content() {
    let counter = TokenCounter::new();

    let content = "line one\nline two\nline three\nline four\nline five";

    let parts = split_by_tokens(content, 3, &counter);

    assert!(parts.len() > 1);
    assert!(parts.iter().all(|part| counter.count(part) <= 3));
}

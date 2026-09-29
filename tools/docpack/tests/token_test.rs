use docpack::token::TokenCounter;

#[test]
fn counts_tokens() {
    let counter = TokenCounter::new();

    let count = counter.count("Hello world");

    assert!(count > 0);
}

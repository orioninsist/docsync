use tiktoken_rs::CoreBPE;

pub struct TokenCounter {
    tokenizer: CoreBPE,
}

impl Default for TokenCounter {
    fn default() -> Self {
        Self::new()
    }
}

impl TokenCounter {
    pub fn new() -> Self {
        let tokenizer = tiktoken_rs::cl100k_base().expect("failed to initialize tokenizer");

        Self { tokenizer }
    }

    pub fn count(&self, text: &str) -> usize {
        self.tokenizer.encode_with_special_tokens(text).len()
    }
}

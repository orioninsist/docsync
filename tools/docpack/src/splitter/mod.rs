use crate::token::TokenCounter;

pub fn split_by_tokens(content: &str, max_tokens: usize, counter: &TokenCounter) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();

    for line in content.lines() {
        let candidate = if current.is_empty() {
            line.to_string()
        } else {
            format!("{current}\n{line}")
        };

        if counter.count(&candidate) > max_tokens && !current.is_empty() {
            parts.push(current);
            current = line.to_string();
        } else {
            current = candidate;
        }
    }

    if !current.is_empty() {
        parts.push(current);
    }

    parts
}

use std::path::PathBuf;

use docpack::document::Document;
use docpack::merge::merge_documents;

#[test]
fn merges_documents_with_sources() {
    let documents = vec![
        Document {
            path: PathBuf::from("first.md"),
            name: "first.md".to_string(),
            content: "# First".to_string(),
        },
        Document {
            path: PathBuf::from("second.md"),
            name: "second.md".to_string(),
            content: "# Second".to_string(),
        },
    ];

    let merged = merge_documents(&documents);

    assert!(merged.contains("<!-- Source: first.md -->"));
    assert!(merged.contains("# First"));
    assert!(merged.contains("<!-- Source: second.md -->"));
    assert!(merged.contains("# Second"));
}

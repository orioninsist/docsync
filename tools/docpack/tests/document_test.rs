use std::fs;

use docpack::document::read_markdown_file;

#[test]
fn reads_markdown_document() {
    let path = std::env::temp_dir().join("docpack_document_test.md");

    fs::write(&path, "# Hello\n\nContent").unwrap();

    let document = read_markdown_file(&path).unwrap();

    assert_eq!(document.name, "docpack_document_test.md");
    assert_eq!(document.content, "# Hello\n\nContent");
    assert_eq!(document.path, path);

    let _ = fs::remove_file(&path);
}

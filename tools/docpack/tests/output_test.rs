use std::fs;

use docpack::output::write_markdown;

#[test]
fn writes_markdown_output_file() {
    let dir = std::env::temp_dir().join("docpack_output_test");
    let file = dir.join("result.md");

    let _ = fs::remove_dir_all(&dir);

    write_markdown(&file, "# Result").unwrap();

    let content = fs::read_to_string(&file).unwrap();

    assert_eq!(content, "# Result");

    let _ = fs::remove_dir_all(&dir);
}

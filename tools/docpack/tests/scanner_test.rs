use std::fs;
use std::path::PathBuf;

use docpack::scanner::find_markdown_files;

#[test]
fn finds_markdown_files_recursively() {
    let root = std::env::temp_dir().join("docpack_scanner_test");

    let _ = fs::remove_dir_all(&root);

    fs::create_dir_all(root.join("nested")).unwrap();

    fs::write(root.join("one.md"), "# One").unwrap();
    fs::write(root.join("nested/two.md"), "# Two").unwrap();
    fs::write(root.join("ignore.txt"), "ignore").unwrap();

    let mut files = find_markdown_files(&root);
    files.sort();

    assert_eq!(files.len(), 2);

    assert!(files.contains(&PathBuf::from(root.join("one.md"))));
    assert!(files.contains(&PathBuf::from(root.join("nested/two.md"))));

    let _ = fs::remove_dir_all(&root);
}

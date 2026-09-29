use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    pub path: PathBuf,
    pub name: String,
    pub content: String,
}

pub fn read_markdown_file(path: &Path) -> std::io::Result<Document> {
    let content = fs::read_to_string(path)?;

    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_string();

    Ok(Document {
        path: path.to_path_buf(),
        name,
        content,
    })
}

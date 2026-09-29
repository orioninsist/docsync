use std::fs;
use std::io;
use std::path::Path;

pub fn write_markdown(output: &Path, content: &str) -> io::Result<()> {
    if let Some(parent) = output.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent)?;
    }

    fs::write(output, content)?;

    Ok(())
}

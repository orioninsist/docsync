use std::fs;
use std::process::Command;

#[test]
fn runs_full_merge_pipeline() {
    let output = std::env::temp_dir().join("docpack_pipeline_result.md");

    let _ = fs::remove_file(&output);

    let status = Command::new(env!("CARGO_BIN_EXE_docpack"))
        .args([
            "merge",
            "--input",
            "tests/integration_docs",
            "--output",
            output.to_str().unwrap(),
        ])
        .status()
        .unwrap();

    assert!(status.success());
    assert!(output.exists());

    let content = fs::read_to_string(&output).unwrap();

    assert!(content.contains("Project README"));
    assert!(content.contains("API Reference"));
    assert!(content.contains("Setup Guide"));

    let _ = fs::remove_file(&output);
}

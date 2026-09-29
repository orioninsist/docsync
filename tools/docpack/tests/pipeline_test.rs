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
            "tests/fixtures/docs",
            "--output",
            output.to_str().unwrap(),
        ])
        .status()
        .unwrap();

    assert!(status.success());
    assert!(output.exists());

    let content = fs::read_to_string(&output).unwrap();

    assert!(content.contains("First Document"));
    assert!(content.contains("Second Document"));

    let _ = fs::remove_file(&output);
}

use clap::{Parser, Subcommand};
use std::path::PathBuf;

use docpack::document::read_markdown_file;
use docpack::merge::merge_documents;
use docpack::output::write_markdown;
use docpack::scanner::find_markdown_files;
use docpack::splitter::split_by_tokens;
use docpack::token::TokenCounter;

#[derive(Parser, Debug)]
#[command(
    name = "docpack",
    version,
    about = "Markdown document packager for AI projects"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    Merge {
        #[arg(long)]
        input: PathBuf,

        #[arg(long)]
        output: PathBuf,

        #[arg(long, default_value_t = 12000)]
        max_tokens: usize,
    },
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Commands::Merge {
            input,
            output,
            max_tokens,
        } => {
            let files = find_markdown_files(&input);

            let documents = files
                .iter()
                .filter_map(|file| read_markdown_file(file).ok())
                .collect::<Vec<_>>();

            let merged = merge_documents(&documents);

            let counter = TokenCounter::new();

            let parts = split_by_tokens(&merged, max_tokens, &counter);

            let final_content = parts.join("\n\n---\n\n");

            write_markdown(&output, &final_content).expect("failed to write output");

            println!(
                "done files={} parts={} tokens={}",
                documents.len(),
                parts.len(),
                counter.count(&final_content)
            );
        }
    }
}

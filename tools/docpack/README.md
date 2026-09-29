# docpack

Markdown document packager for AI projects.

`docpack` scans Markdown documentation folders, merges documents, calculates tokens and creates AI-ready Markdown packages.

## Features

- Recursive Markdown file discovery
- Markdown document loading
- Document merging with source tracking
- Token counting using OpenAI-compatible tokenizer
- Token based splitting
- CLI workflow
- Release binary support

## Installation

Build from source:

```bash
cargo build --release
```

Binary:

```bash
target/release/docpack
```

## Usage

Merge a documentation folder:

```bash
docpack merge \
  --input ./docs \
  --output ./package.md
```

With token limit:

```bash
docpack merge \
  --input ./docs \
  --output ./package.md \
  --max-tokens 12000
```

## Pipeline

```
Markdown files
      |
      v
Scanner
      |
      v
Document reader
      |
      v
Merge engine
      |
      v
Token counter
      |
      v
Splitter
      |
      v
Output Markdown
```

## Development

Run tests:

```bash
cargo test
```

Format:

```bash
cargo fmt
```

Lint:

```bash
cargo clippy -- -D warnings
```

Build release:

```bash
cargo build --release
```

## License

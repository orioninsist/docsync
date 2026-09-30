# markdownMerge

A deterministic, token-aware Markdown context builder for LLM workflows.

Prepare large Markdown collections for AI usage without changing the original documents.

markdownMerge scans Markdown files, measures tokens, packs complete source files into validated context packages, and keeps every source traceable.

## Why markdownMerge?

Large documentation collections become difficult to upload and manage in LLM workflows.

markdownMerge solves this by providing:

- predictable token limits
- deterministic output files
- complete source preservation
- source traceability
- validation after generation
- machine-readable metadata with `manifest.json`

## Features

- Token-aware Markdown packaging
- Complete source file preservation
- No rewriting of Markdown body content
- Source traceability markers
- Validation after output generation
- Deterministic numbered output files
- Configurable tokenizer support through `tiktoken`

markdownMerge recursively scans Markdown files, counts tokens, packs complete source files with First-Fit Decreasing, writes fewer merged Markdown files, and re-tokenizes the written outputs for validation.

Source Markdown files are never split and their body content is never rewritten.

## Quick start

Install:

```bash
git clone https://github.com/orioninsist/markdownMerge.git
cd markdownMerge
uv sync
```

Daily usage:

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000
```

This means:

```text
./docs          input directory containing Markdown files
./merged        output directory
--name openai   output base name
--token-limit   final maximum token count for each generated Markdown part
```

If two Markdown parts are created, the output names are:

```text
merged/
├── openai-1.md
├── openai-2.md
├── manifest.json
├── summary.txt
└── validation.txt
```

`--name` is required. markdownMerge never guesses a filename from the content or source paths.

Use a base name only:

```text
Correct:   --name openai
Incorrect: --name openai.md
Incorrect: --name path/openai
```

Even when only one part is created, its name is still:

```text
openai-1.md
```

## Command syntax

```bash
uv run mdmerge INPUT_DIRECTORY OUTPUT_DIRECTORY \
  --name NAME \
  --token-limit TOKEN_LIMIT \
  [--reserve-tokens RESERVE_TOKENS] \
  [--model MODEL | --encoding ENCODING_NAME]
```

Required:

```text
INPUT_DIRECTORY
OUTPUT_DIRECTORY
--name
--token-limit
```

Optional:

```text
--reserve-tokens
--model
--encoding
```

Current defaults:

```text
--reserve-tokens 5000
--model gpt-4o
```

`--model` and `--encoding` are mutually exclusive.

## Parameters

### INPUT_DIRECTORY

Directory containing the source Markdown files.

markdownMerge searches recursively, so nested directories are included automatically.

Example:

```text
docs/
├── index.md
├── api/
│   ├── authentication.md
│   └── errors.md
└── guides/
    └── linux.md
```

All `.md` files under `docs/` are discovered.

The input path must be a directory.

### OUTPUT_DIRECTORY

Directory where generated Markdown parts and reports are written.

The output directory must be outside the input directory.

Valid:

```text
input:  /data/docs
output: /data/merged
```

Invalid:

```text
input:  /data/docs
output: /data/docs/merged
```

Also invalid:

```text
input:  /data/docs
output: /data/docs
```

This prevents previously generated files from becoming source files in later runs.

### --name

Required output base name.

Example:

```bash
--name openai
```

Generated Markdown filenames are always numbered from 1:

```text
openai-1.md
openai-2.md
openai-3.md
...
```

The name:

- cannot be empty
- cannot be `.` or `..`
- cannot contain `/` or `\`
- must not include the `.md` extension

There is no automatic or semantic filename fallback.

### --token-limit

Required final maximum token count for each generated Markdown part.

Example:

```bash
--token-limit 120000
```

The value must be greater than zero.

Final generated Markdown files are re-tokenized and validation fails if any part exceeds this value.

markdownMerge does not choose an AI platform's upload or context limit for you. Set this value according to your intended use.

### --reserve-tokens

Optional planning safety reserve.

Default:

```text
5000
```

The packing budget is:

```text
effective limit = token limit - reserve tokens
```

For:

```text
token limit:      120000
reserve tokens:     5000
effective limit:  115000
```

First-Fit Decreasing packs source files against 115,000 tokens. The final written part must still remain at or below 120,000 tokens.

Rules:

- must be zero or greater
- must be smaller than `--token-limit`

To remove the reserve:

```bash
--reserve-tokens 0
```

### --model

Optional tiktoken model-name resolution.

Default:

```text
gpt-4o
```

Example:

```bash
--model gpt-4o
```

markdownMerge passes this value to:

```python
tiktoken.encoding_for_model(MODEL)
```

The model name is used only to choose the tokenizer encoding. markdownMerge does not call the OpenAI API and does not send your files to a remote model.

Current upstream tiktoken mappings include:

```text
Model / prefix                 Encoding
-----------------------------  -------------
gpt-5                          o200k_base
gpt-5...                       o200k_base
gpt-4.5-...                    o200k_base
gpt-4.1                        o200k_base
gpt-4.1-...                    o200k_base
gpt-4o                         o200k_base
gpt-4o-...                     o200k_base
chatgpt-4o-...                 o200k_base
o1                             o200k_base
o1-...                         o200k_base
o3                             o200k_base
o3-...                         o200k_base
o4-mini                        o200k_base
o4-mini-...                    o200k_base
gpt-oss-...                    o200k_harmony
gpt-4                          cl100k_base
gpt-4-...                      cl100k_base
gpt-3.5-turbo                  cl100k_base
gpt-3.5-turbo-...              cl100k_base
gpt-35-turbo                   cl100k_base
gpt-35-turbo-...               cl100k_base
davinci-002                    cl100k_base
babbage-002                    cl100k_base
text-embedding-ada-002         cl100k_base
text-embedding-3-small         cl100k_base
text-embedding-3-large         cl100k_base
```

tiktoken also keeps mappings for older/deprecated model names. Because upstream mappings can change as tiktoken evolves, the installed tiktoken version is authoritative for `--model`.

If an unknown model name is supplied, tiktoken raises an error. In that case, either use a model name supported by your installed tiktoken version or use `--encoding` explicitly.

### --encoding

Optional explicit tiktoken encoding name.

Example:

```bash
--encoding o200k_base
```

markdownMerge passes this value to:

```python
tiktoken.get_encoding(ENCODING_NAME)
```

Current upstream public tiktoken encoding names include:

```text
o200k_base
o200k_harmony
cl100k_base
p50k_base
p50k_edit
r50k_base
gpt2
```

Use `--encoding` when you want to pin the exact tokenizer rather than let tiktoken resolve one from a model name.

For current GPT-5, GPT-4.1, GPT-4o, o1, o3, and o4-mini families, upstream tiktoken maps model names to `o200k_base`.

Example:

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --encoding o200k_base
```

Do not use `--model` and `--encoding` together.

## Defaults and equivalent commands

This command:

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000
```

currently means:

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --model gpt-4o
```

Because tiktoken currently resolves `gpt-4o` to `o200k_base`, the tokenizer used by the default model is currently `o200k_base`.

If you want the tokenizer choice to be explicit and independent of model-name mapping, use:

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --encoding o200k_base
```

## Usage examples

### Standard daily use

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000
```

### Explicit tokenizer encoding

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --encoding o200k_base
```

### Model-name tokenizer selection

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --model gpt-5
```

### No reserve

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 0 \
  --encoding o200k_base
```

### Larger reserve

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 120000 \
  --reserve-tokens 10000 \
  --encoding o200k_base
```

### Smaller token limit

```bash
uv run mdmerge ./docs ./merged \
  --name openai \
  --token-limit 50000 \
  --reserve-tokens 5000 \
  --encoding o200k_base
```

### Large corpus

No special option is required for thousands of Markdown files.

```bash
uv run mdmerge /data/docs /data/merged-docs \
  --name docs \
  --token-limit 120000 \
  --reserve-tokens 5000 \
  --encoding o200k_base
```

## Packing behavior

Each complete source is measured together with its generated source marker:

```markdown
# Source: guides/setup.md
```

Sources are sorted by:

1. token count, descending
2. source path, ascending as the deterministic tie-breaker

They are packed with First-Fit Decreasing.

Conceptually:

```text
measure all source files
        |
        v
sort largest -> smallest
        |
        v
put each source in the first existing part where it fits
        |
        +-- none fits --> create a new part
```

First-Fit Decreasing is a packing heuristic. It generally reduces the number of generated parts, but it does not guarantee the mathematically minimum possible number for every input.

A source Markdown file is never split. If one source is larger than the effective planning limit, the run stops with an error.

## Source integrity

markdownMerge does not:

- rewrite prose
- summarize content
- remove sections
- normalize Markdown
- alter code blocks
- alter syntax-highlight language identifiers
- split a source Markdown file
- semantically cluster text
- reorder text inside a source file

It only decides which complete source files belong in each generated part.

Every source body is preceded by a traceability marker:

```markdown
# Source: api/authentication.md

(original source content)
```

## Output files

For:

```bash
--name openai
```

an example output directory is:

```text
merged/
├── openai-1.md
├── openai-2.md
├── openai-3.md
├── manifest.json
├── summary.txt
└── validation.txt
```

### openai-N.md

Merged Markdown part.

Each part contains one or more complete source Markdown files plus their `# Source:` markers.

### summary.txt

Human-readable run summary containing part and token statistics.

### validation.txt

Human-readable validation report for every generated Markdown part.

Validation fails when:

- no output parts were generated
- an output part has no source marker
- a final output part exceeds `--token-limit`

The written output file is authoritative, not only the planning estimate.

### manifest.json

Machine-readable metadata containing:

- input directory
- token limit
- reserve tokens
- effective token limit
- tokenizer selection
- input file count
- created part count
- validation result
- output filename for each part
- final token count for each part
- source files contained in each part

## What happens during a run

```text
1. validate CLI arguments
2. recursively discover .md files
3. count each complete source plus its source marker with tiktoken
4. reject a source that exceeds the effective planning limit
5. sort sources by descending token count
6. pack with First-Fit Decreasing
7. write NAME-1.md, NAME-2.md, ...
8. re-read every generated Markdown part
9. re-tokenize every generated Markdown part
10. create validation.txt
11. create summary.txt
12. create manifest.json
13. exit successfully only when validation passes
```

## Determinism

Given the same:

- source contents
- source paths
- `--name`
- token limit
- reserve
- tokenizer

markdownMerge produces the same packing order, part membership, and numbered output names.

## Re-running

You may run the same command again.

If a new run creates fewer parts than an older run in the same output directory, old higher-numbered Markdown parts can remain on disk. For example, an old `openai-4.md` can remain if the new run creates only `openai-1.md` through `openai-3.md`.

Use a dedicated output directory for each corpus and clear or replace it before a fresh run when you do not want stale files retained.

## Checking results

```bash
cat OUTPUT_DIRECTORY/summary.txt
cat OUTPUT_DIRECTORY/validation.txt
jq . OUTPUT_DIRECTORY/manifest.json
find OUTPUT_DIRECTORY -maxdepth 1 -type f -name '*.md' -print | sort
```

## tiktoken

markdownMerge uses the published `tiktoken` Python package.

The project currently declares:

```text
tiktoken>=0.9.0
```

Install dependencies with:

```bash
uv sync
```

You do not need to clone or build the tiktoken repository separately.

Important distinction:

```text
--model MODEL
    -> tiktoken.encoding_for_model(MODEL)

--encoding ENCODING_NAME
    -> tiktoken.get_encoding(ENCODING_NAME)
```

`--model` is therefore a tokenizer-selection convenience. It is not a remote inference request.

Upstream reference:

https://github.com/openai/tiktoken

## Requirements

- Python 3.11 or newer
- `uv`
- a platform supported by the installed `tiktoken` package

## Development and verification

Install development dependencies:

```bash
uv sync --group dev
```

Run the complete project quality pipeline:

```bash
./quality.sh
```

The pipeline checks:

```text
Ruff formatting
Ruff lint
Mypy strict type checking
Pytest
CLI help
Direct entry point
```

Individual commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run --group dev python -m pytest
uv run mdmerge --help
uv run python main.py --help
```

## Troubleshooting

### --name is required

Every run must include a base name:

```bash
--name openai
```

### --name must not include .md

Use:

```text
--name openai
```

not:

```text
--name openai.md
```

### No Markdown files found

The input directory contains no recursively discoverable `.md` files.

### Input path is not a directory

Pass a directory, not a single Markdown file.

### OUTPUT_DIRECTORY must be outside INPUT_DIRECTORY

Choose a sibling or otherwise separate output directory.

### Source file exceeds the effective token limit

One complete source file is too large for:

```text
token limit - reserve tokens
```

Increase `--token-limit`, reduce `--reserve-tokens`, or handle that source separately.

markdownMerge will not split or silently modify the source.

### Unknown model

The supplied model name is not recognized by the installed tiktoken version.

Use a supported model name or choose an encoding explicitly:

```bash
--encoding o200k_base
```

### Unknown encoding

The supplied encoding name is not registered by the installed tiktoken version.

Use an encoding returned by the installed tiktoken package.

You can inspect them locally with:

```bash
uv run python -c 'import tiktoken; print(tiktoken.list_encoding_names())'
```

### Validation failed

Inspect:

```bash
cat OUTPUT_DIRECTORY/validation.txt
```

## Scope

markdownMerge intentionally does one job.

It does not:

- upload files to an AI service
- call OpenAI, Gemini, Grok, Copilot, or another remote model API
- infer an AI platform's upload or context limit
- choose `--token-limit` for you
- modify source content
- summarize sources
- split oversized source files
- perform semantic clustering
- crawl websites

It takes a Markdown corpus and a token budget and produces fewer validated Markdown files.

## License

MIT License

# markdownMerge

A deterministic Markdown packer optimized for ChatGPT/OpenAI file uploads.

It recursively scans Markdown sources, preserves their original body content, and packs them into as few upload-safe Markdown files as practical.

## Default ChatGPT/OpenAI profile

Current defaults intentionally stay below the official per-file upload ceilings:

- final token target: 1,800,000 tokens
- planning reserve: 50,000 tokens
- effective packing budget: 1,750,000 tokens
- tokenizer: o200k_base
- hard byte validation: 512,000,000 bytes (512 MB) per generated file

OpenAI currently documents a 2,000,000-token cap for text/document uploads and a 512 MB hard file-size limit. The defaults leave token headroom rather than targeting the absolute ceiling.

## Daily usage

After installing once with `uv sync`, the normal command is simply:

```bash
uv run mdmerge /path/to/site-markdown
```

Example:

```bash
cd /home/murat/Media/6-Project/docsync/markdownMerge && \
uv run mdmerge /home/murat/Media/5-Documentation/developers.openai.com
```

Output is written automatically to:

```text
/home/murat/Media/8-Document/markdownMerge/<input-directory-name>/
```

Generated files:

```text
<input-name>-1.md
<input-name>-2.md
...
manifest.json
summary.txt
validation.txt
```

If the entire corpus fits safely in one output, only `<input-name>-1.md` is produced.

## Packing behavior

1. Recursively discover all `.md` sources.
2. Preserve each source body exactly.
3. Prefix each source or chunk with a traceability marker:
   `# Source: relative/path.md`.
4. Split only an individual source that cannot fit inside the effective token budget, tokenizing oversized content once and preserving exact UTF-8 source bytes.
5. Pack normal sources and oversized-source chunks together with deterministic First-Fit Decreasing.
6. Re-tokenize the written output.
7. Validate both token count and 512 MB byte size.
8. Mark the run `upload_ready: true` in `manifest.json` only when validation passes.

First-Fit Decreasing is a deterministic packing heuristic and normally produces a small number of parts, though it does not mathematically guarantee the absolute minimum bin count for every possible input.

## Source integrity

markdownMerge does not summarize, rewrite, normalize, or remove source content. It does not alter code blocks. Only sources too large for one package are split into ordered chunks. Split output is checked for byte-for-byte UTF-8 continuity before writing.

## Optional overrides

The default command needs only an input directory. Advanced overrides remain available:

```bash
uv run mdmerge INPUT_DIRECTORY \
  [--name NAME] \
  [--token-limit TOKEN_LIMIT] \
  [--reserve-tokens RESERVE_TOKENS] \
  [--model MODEL | --encoding ENCODING_NAME]
```

Example with explicit defaults:

```bash
uv run mdmerge ./docs \
  --token-limit 1800000 \
  --reserve-tokens 50000 \
  --encoding o200k_base
```

## Validation and metadata

`validation.txt` reports tokens, bytes, source-marker count, and status for every generated Markdown file.

`manifest.json` records:

- input directory
- token limit and effective token limit
- reserve tokens
- maximum file bytes
- tokenizer
- input file count
- generated part count
- per-part tokens and bytes
- source membership
- validation state
- `upload_ready`

## Development

```bash
cd /home/murat/Media/6-Project/docsync/markdownMerge
uv sync --group dev
./quality.sh
```

The quality pipeline checks formatting, linting, strict type checking, tests, and CLI entry points.

### Reference benchmark

On the `developers.openai.com` corpus used during v1.0 validation (1,485 Markdown files), the oversized-source splitter optimization reduced the end-to-end run from 5m48s to 1m09.834s (about 5x faster). The optimized run completed with `Validation Result: PASSED`. Benchmark results are workload- and machine-dependent.

## Scope

markdownMerge only prepares local Markdown packages. It does not upload files, call OpenAI APIs, crawl websites, summarize content, or modify source prose.

## License

MIT License

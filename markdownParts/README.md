# markdownParts

`markdownParts` recursively discovers Markdown files and merges them into an exact
number of output parts, balancing by **file count**.

It is an isolated subproject inside `docsync`. It does not use Crawlee,
Playwright, tokenizers, or the main `docsync` package.

## Behavior

- Recursively scans the supplied directory and its subdirectories.
- Includes only files whose suffix is exactly `.md`.
- Does not follow symlinked files or directory symlinks.
- Sorts files deterministically by relative path.
- Splits the files into exactly `--parts N` groups.
- Group sizes differ by at most one file.
- Copies source bytes exactly as stored.
- Adds no headings, separators, metadata, comments, or newline bytes.
- Never modifies, moves, renames, or deletes source files.
- Refuses to overwrite an existing output file.
- Writes only merged `.md` files to the output directory.

## Fixed output directory

```text
/home/murat/Media/8-Document/markdownPart/
```

The source directory basename is used for the output filenames.

Example source:

```text
/home/murat/Media/5-Documentation/crawlee.dev
```

With:

```bash
uv run mdparts /home/murat/Media/5-Documentation/crawlee.dev --parts 5
```

The outputs are:

```text
/home/murat/Media/8-Document/markdownPart/crawlee.dev-1.md
/home/murat/Media/8-Document/markdownPart/crawlee.dev-2.md
/home/murat/Media/8-Document/markdownPart/crawlee.dev-3.md
/home/murat/Media/8-Document/markdownPart/crawlee.dev-4.md
/home/murat/Media/8-Document/markdownPart/crawlee.dev-5.md
```

No manifest, summary, validation, or log file is created.

## Usage

From the subproject:

```bash
cd /home/murat/Media/6-Project/docsync/markdownParts

uv run mdparts \
  /home/murat/Media/5-Documentation/crawlee.dev \
  --parts 5
```

For 100 Markdown files and `--parts 2`, each output contains 50 source files.

For 10 Markdown files and `--parts 3`, the groups contain 4, 3, and 3 files.

If `--parts` is greater than the number of Markdown files, the command fails
instead of creating empty parts.

## Important byte-preservation rule

Files are concatenated byte-for-byte. No separator is inserted between source
files. Therefore, if one source file does not end with a newline, the next
source file starts immediately after its last byte. This is intentional: the
tool never adds content that was not present in the source Markdown files.

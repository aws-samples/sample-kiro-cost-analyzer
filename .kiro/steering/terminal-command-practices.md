# Terminal Command Practices

## Avoid heavy quoting in shell commands

Commands that rely on embedding large blocks of text inside single or double
quotes (e.g. multi-line `-m`/`-b`/`--body` strings, heredocs, `echo "..." >`,
inline JSON payloads) are error-prone in this environment — escaping, nested
quotes, and line breaks frequently break the command or produce corrupted
output.

**Rule: prefer dedicated tools over quote-heavy inline shell text.**

- For file content (creating/editing files, writing multi-line text), use the
  file-editing tools (`fs_write`, `fs_append`, `str_replace`) instead of
  `echo`, `cat <<EOF`, or shell redirection.
- For GitHub operations (issues, PRs, comments, labels), use the `gh` CLI with
  `--body-file <path>` instead of `--body "..."`. Write the body to a file
  with `fs_write` first, then pass the file path to `gh`.
- For any CLI that supports a `--file` / `--body-file` / `-F` style flag,
  prefer it over inline string flags when the content is more than one line
  or contains quotes, backticks, or special characters.
- When an inline flag is unavoidable and short (a single line, no nested
  quotes), it's fine to use it directly — this rule targets multi-line or
  quote-heavy content, not every CLI argument.
- If no dedicated tool or file-based flag exists for a given operation, write
  the payload to a temporary file first and reference that file in the
  command, rather than inlining it with escaped quotes.

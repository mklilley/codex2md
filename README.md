# codex2md

Export Codex VS Code rollout session logs to clean Markdown.

## Features

- Interactive TUI with browse-by-date, browse-by-working-directory, and search
- Non-interactive `list` and `export` commands
- Fault-tolerant JSONL parsing with best-effort exports
- Optional redaction of home paths

## Install (local)

```bash
pip install -e .
```

## Usage

Interactive mode (default):

```bash
codex2md
```

List sessions:

```bash
codex2md list --year 2025 --month 12
```

Export a single session:

```bash
codex2md export --file ~/.codex/sessions/2025/12/23/rollout-123.jsonl --out session.md
```

Export by filter:

```bash
codex2md export --cwd "/Users/matt/Documents/GitHub/project" --out-dir ./exports
```

## Configuration

- `CODEX_HOME` controls the base Codex directory (default: `~/.codex`).
- Logs are written to `~/.codex2md/logs/latest.log`.

## Notes

- The parser ignores unknown record types and skips malformed lines.
- Tool calls/outputs are not exported by default (`--include-tools` to include them).
- Reasoning summaries are exported by default and never decrypted (`--no-include-reasoning` to omit).

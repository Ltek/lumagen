# CLAUDE.md

Ltek version of jaysoffian/ha-lumagen. Upstream remote: `upstream` (https://github.com/jaysoffian/ha-lumagen). Versions are `YYYY.MM.DD.BUILD` in `manifest.json` + `CHANGELOG.md`; README carries a "Current build" pointer. No GitHub Actions — the repo is pushed manually.

## Git
- Do NOT include Claude attribution in commit messages.
- Always verify `git status` is clean before making changes.

## Verification
- Use pre-commit hooks to verify work — do NOT run checkers (ruff, pyright, pytest, etc.) manually.
- Run: `pre-commit run --all-files`
- Run: `make hassfest` — validates manifest, config schema, translations, etc. via the HA hassfest container (mounts the repo root).

## Python
- Always use `uv` to run Python, pytest, and tools (never bare `python` or `python3`).
- Always use `uv add` and `uv remove` to add or remove Python packages.
- Never add new `pyright: ignore` or `type: ignore` comments — needing one means the approach is wrong.

## Project overview
- Home Assistant custom integration for Lumagen Radiance Pro video processors.
- No external dependencies — self-contained async TCP client in `client.py`.
- Event-driven (no polling): coordinator sets `update_interval=None`, all state comes from the TCP stream.

## tui.py
- Runs via `#!/usr/bin/env -S uv run python` — uses the project venv, not `uv run --script`.
- PEP 723 inline script metadata does NOT apply; new deps go in `pyproject.toml` `[dependency-groups] dev`.

## HA entities
- When adding or renaming HA entities, update `strings.json` with a matching translation key.
- Use `_attr_translation_key` (not `_attr_name`) so HA resolves names from `strings.json`.
- Always keep `translations/en.json` in sync with `strings.json` — HA loads translations from `translations/en.json` at runtime, not `strings.json`.

## Reference docs
- `docs/development.md` — development setup, pre-commit details
- `docs/architecture.md` — architecture, state management, startup sequence, connection lifecycle
- `docs/rs232_command_reference.md` — full Lumagen RS-232 command & query reference

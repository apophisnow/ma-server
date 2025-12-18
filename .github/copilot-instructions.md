<!-- Copilot / AI agent instructions for Music Assistant (server) -->
# Music Assistant — AI Agent Guidance

Purpose: quickly orient an AI coding agent to become productive in this repository.

Quick start
- Setup: run `scripts/setup.sh` to create a venv, install deps, and configure pre-commit.
- Run server: `python -m music_assistant --log-level debug` (or use VS Code F5).
- Tests: `pytest` (use `pytest tests/<path>` for focused runs).
- Lint/type-check: `pre-commit run --all-files`; `pyproject.toml` configures `ruff` and `mypy`.

Big picture (read these files)
- Entry point: [music_assistant/__main__.py](../music_assistant/__main__.py#L1-L40) — CLI flags, logger, startup.
- Orchestrator: [music_assistant/mass.py](../music_assistant/mass.py#L1-L120) — loads provider manifests, instantiates controllers, manages lifecycle and event loop.
- Controllers: `music_assistant/controllers/` — e.g. `music.py` for playback logic, `webserver/` for HTTP API.
- Providers: `music_assistant/providers/` — each provider has `__init__.py` and `manifest.json`; manifests are discovered before instantiation.

Key patterns & conventions (concrete, repo-specific)
- Async-first: nearly all components expose async `setup()` / `close()` and run on the repository event loop. Favor `async` functions and await the session lifecycle.
- Provider lifecycle: manifests are parsed first; provider classes implement `get_stream_details()` then `get_audio_stream()` for playback. See `providers/spotify/__init__.py` for an example.
- Shared resources: use the central `http_session` and other shared attributes supplied by the main `MusicAssistant` instance (avoid creating ad-hoc sessions).
- CLI flags and config: `--data-dir` / `--cache-dir`, `--safe-mode` (skip third-party providers), and `options.json` (Home Assistant add-on override).

Developer workflows & gotchas
- Re-run `scripts/setup.sh` after pulling dependency changes.
- Use `PYTHONDEVMODE=1` to enable dev-specific behavior.
- Ensure external binaries like `ffmpeg` (>=6.x) are in PATH for media features.
- When testing providers or playback paths, prefer small focused pytest runs and the fixtures in `tests/fixtures/`.

Tests, CI, and style
- Tests live under `tests/` (async pytest + aiohttp fixtures). Snapshot tests use Syrupy.
- Run `pytest --maxfail=1 -q` for quick feedback; `pytest --cov music_assistant` for coverage.
- Pre-commit hooks enforce `ruff` and formatting; run `pre-commit run --all-files` before pushing.

Safe edit rules for AI agents (must follow)
- Make small, focused edits and preserve public APIs (especially provider `manifest.json` schema).
- Prefer fixing root causes over surface patches when clear; otherwise implement minimal safe changes.
- Add tests for new behavior (place under `tests/providers/` when adding providers).
- Run unit tests and pre-commit in CI before opening PRs.

Where to look for examples
- Provider example: [music_assistant/providers/spotify/__init__.py](../music_assistant/providers/spotify/__init__.py#L1)
- Orchestrator and manifest loading: [music_assistant/mass.py](../music_assistant/mass.py#L1-L120)
- Webserver patterns: [music_assistant/controllers/webserver/](../music_assistant/controllers/webserver/)

If anything here is unclear or you want deeper examples (provider wiring, streaming internals, or test fixtures), tell me which area to expand.

If anything above is unclear or you'd like more detail (examples, common PR templates, or file-by-file pointers), tell me which area to expand. 

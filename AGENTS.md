# Project instructions

## Comments and processing stages

- Add detailed comments where the intent, a processing stage, a validation rule, a retry, or a non-obvious constraint would otherwise be unclear. Explain why the behavior exists; do not comment on trivial statements or simply repeat the code.
- For multi-step modules, label the main stages in code and describe what enters and leaves each stage. Keep comments close to the logic they explain and update them when behavior changes.
- Print progress messages in this exact shape: `[MODULE][STAGE][STATUS] Message`. Use stable uppercase module and stage identifiers, include useful counts where available, and set `flush=True` so the SSE stream receives progress promptly.
- Print start, per-item or per-page progress when useful, success, failure, and final totals. A single failed input should not abort a batch when the module can safely return partial results.

## Credentials and diagnostic output

- Never print, log, return, or export credentials, tokens, passwords, or complete authorization URLs. Read secrets from environment-backed application configuration only.
- Keep progress output free of phrase contents when counts are sufficient. For errors, log the exception type and processing stage rather than raw request URLs or untrusted server response bodies.
- Escape dynamic text inserted into HTML responses. XLSX output must treat user- and API-supplied strings as text, not executable spreadsheet formulas.

## Functional modules and shared utilities

- A functional module is an independently usable, user-facing product capability. Give it a documented contract and a public Python entry point so code-defined scenarios can call it without going through FastAPI.
- Keep the capability's core logic independent of its UI and transport layer. UI/API routes are adapters that call the same public entry point; do not duplicate business logic in routes.
- Put functional capabilities in `modules/<capability>/` (or `modules/<service>/` when grouped by service). Keep capability-specific logic and settings with that capability.
- A functional capability may have a UI/API without a separate administration, CRUD, or code-management interface. Keep its logic in `modules/` and its UI/API in the adapter layers; UI presence does not make it a shared utility.
- Put cross-cutting infrastructure and utilities genuinely reused by multiple capabilities in top-level `shared/`. Shared code is not itself a user-facing workflow; do not place capability-specific logic there merely for convenience.
- Put workflows that orchestrate multiple capabilities in top-level `scenarios/`; have them call the modules' public Python entry points.
- Before adding functionality, inspect `shared/` and relevant capability packages for reusable code. Reuse existing behavior, but do not force service-specific logic into `shared/`.
- Keep test runners separate from web routes and avoid real external API requests in automated tests; mock module callables at the registry/service boundary.

## Project structure and naming

- `main.py` creates the application and includes routers from `api/routers/`; HTTP endpoints and UI adapters belong in focused router modules, not in functional-module core implementations.
- Put user-facing functional capabilities in `modules/<capability>/` or `modules/<service>/`, cross-cutting reusable infrastructure in top-level `shared/`, cross-capability workflows in top-level `scenarios/`, and manual or automated tests in `tests/`.
- Use `docs/architecture.md` as the current-state map of directories, key files, call flow, and extension steps. Keep it updated when package layout or public entry points change; verify against code if documentation conflicts, and do not treat `.workai/plans/` as authoritative current architecture.
- Keep shared application configuration in `config/`; keep service or capability-specific settings beside their implementation (for example, `modules/xmlriver/settings.py`).
- Use descriptive `snake_case` module names. Avoid generic names such as `input.py`; use names that explain the role, such as `phrase_import.py`.
- Write function and stage documentation so the purpose, inputs, outputs, and meaningful processing stages are clear. Explain why non-obvious validation, retry, and constraints exist; do not add comments that merely restate obvious statements.
- `modules/site_tools/bar_tags.py` (formerly `scripts/link_selection_bar_tags.py`) is a reference for documenting the purpose and sequence of processing stages, not a literal template for console output. Its emojis, non-standard labels, missing `flush=True`, and output of phrase or URL contents are not project conventions.

## Logging conventions

- Keep progress output in the exact `[MODULE][STAGE][STATUS] Message` format with stable uppercase identifiers and `flush=True`; do not use emoji as status markers.
- Prefer counts and processing stage over raw input. Do not print phrase contents or URLs when counts and a stage identifier are sufficient. Include start, useful per-item/page progress, success or failure, and final totals as appropriate.

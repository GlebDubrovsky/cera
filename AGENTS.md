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

## Reusable modules

- Keep each universal module callable independently of FastAPI. Web routes and future code-defined scenarios should call shared services rather than duplicate module-specific setup.
- Keep test runners separate from web routes and avoid real external API requests in automated tests; mock module callables at the registry/service boundary.

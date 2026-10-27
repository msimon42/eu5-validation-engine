# 0001 — Local application implementation choices

Date: 27 October 2026. Status: implemented application decisions (P), not EU5 observations.

- Keep Python/FastAPI, React/TypeScript and SQLite, as specified. Use a small command transport plus read projections instead of requiring every proposed REST route before the first scan.
- Keep the initial database compact: versioned JSON records, append-only job events, idempotency records and migrations, with query indexes. Raw bytes and large artifacts stay in files. Refine into additional relational projections when measured query patterns require them.
- A single workspace coordinator holds an OS lock; long jobs run through a supervised single-worker executor outside request handlers. SQLite publishes a complete scan generation transactionally. Interrupted jobs are retained as failed/incomplete and rerun explicitly rather than replaying ambiguous writes.
- Pin Python 3.12, uv and Node tools through repository locks/launcher. Use standard-library SQLite backup, descriptor-based contained reads/writes and platform locks; no external database/queue is introduced.
- Keep the React UI available alongside every workflow. Backend command/payload schemas generate TypeScript request contracts and checked JSON schemas.
- Windows 11 VM is the selected deployment target per the user's instruction. Accept every EU5 build for inventory/fingerprinting; gate semantics/repairs on build-scoped evidence. A change to another Windows deployment host still requires the specified project decision.
- Ship synthetic and documentation-only profiles with zero conformed production rules. Synthetic repairs may export inactive experimental bundles after local checks. Real-game validated activation remains disabled until runtime qualification and relevant conformance are available.

Primary tool documentation: [FastAPI](https://fastapi.tiangolo.com/), [SQLite backup interface](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup), [Vite runtime requirements](https://vite.dev/guide/), [uv installation](https://docs.astral.sh/uv/getting-started/installation/), [GitHub Actions with uv](https://docs.astral.sh/uv/guides/integration/github/).

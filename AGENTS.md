# Working on the EU5 Mod Engine

Read `specs/AGENTS.md` and the applicable specification sections before changes. The implementation roadmap is `docs/IMPLEMENTATION_PLAN.md`.

Preserve original game/mod bytes. Do not modify the specification source package or invent executed game evidence. Synthetic tests prove synthetic contracts only. All real-game production capabilities require scoped, archived conformance and complete preservation gates.

Use `uv run --extra dev pytest` for backend checks, `uv run --extra dev ruff check backend tests` for lint, and the scripts in `frontend/package.json` for frontend checks. Test only temporary/managed roots. Report actual coverage and unavailable Windows/game work honestly.

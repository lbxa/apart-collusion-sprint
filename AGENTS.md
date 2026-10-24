# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a starting scaffold containing agent tooling. Application source code, tests, assets, and dependency manifests have not been added.

- `.agents/skills/`: reusable agent instructions and supporting references.
- `.codex/`: Codex agent definitions, configuration, hooks, rules, and environment settings.
- `.claude/`: Claude agent definitions, skills, hooks, and settings.

Keep application code separate from these tooling directories. Document source, test, and asset locations when introducing the first implementation.

## Build, Test, and Development Commands

No working application build, test, or development command is defined yet. Useful repository checks include:

- `git status --short`: inspect modified and untracked files.
- `git diff --check`: check tracked changes for whitespace errors.
- `bash -n .codex/hooks/stop_checks.sh`: validate the existing hook's shell syntax.

The Codex environment references `bun run dev`, `scripts/setup.sh`, and `scripts/cleanup.sh`; the stop hook delegates to `scripts/agent-hooks/stop-checks.sh`. The required manifest and scripts are absent. Add and verify the intended tooling before treating those commands as usable.

## Coding Style & Naming Conventions

Match neighboring files: use two-space indentation in JSON and preserve existing TOML and shell formatting. Use descriptive filenames and focused modules. Keep Markdown headings descriptive and examples executable. No repository-wide formatter or linter is configured; document any introduced tools and their commands alongside the implementation.

## Testing Guidelines

No test framework, test naming convention, or coverage threshold is established. When adding executable behavior, include tests for important outcomes, edge cases, and failures. Follow the selected runner's discovery conventions and document the exact test command. For documentation changes, verify referenced paths and commands; for shell changes, run syntax checks and exercise behavior when dependencies exist.

## Commit & Pull Request Guidelines

There are no commits from which to infer a convention. Use concise, imperative messages; a suggested format is `docs: add repository guidelines`. Keep commits focused. Pull requests should explain the change, link relevant issues, list verification performed and any blockers, and include screenshots when changing visible UI.

## Agent-Specific Instructions

For library, framework, SDK, API, CLI, or cloud-service documentation, use Context7: resolve the library ID, then query documentation with the full question. Author source and documentation directly with editing tools; keep notebook explanations in Markdown cells. Confirm referenced paths exist before applying bundled skills that assume application infrastructure.

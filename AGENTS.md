// AGENTS.md – concise guidance for OpenCode agents

**Core principles**
- **Simplicity first** - minimal code that solves the problem. Nothing speculative.
- **No Laziness** - Find root causes. No temporary fixes. Senior developer standards.
- **Minimal impact** - Only touch what's necessary. No side effects. No new bugs.


**Repository overview**
- This repo is a collection of TradingView Pine Script indicators and supporting watch‑list text files.
- No compiled language, no build system, no test runner, and no CI configuration is present.
- All source files live under `src/indicators/` (primary scripts) and `src/libraries/` (shared Pine libraries).
- Watch‑list files (`watchlist/*.txt`) are plain‑text data used by the scripts.

**How to work with the code**
- **Run a script** – Open the `.pine` file in TradingView’s Pine Editor and add it to a chart. No additional build or install steps are required.
- **Edit a script** – Modify the `.pine` file directly; changes are immediately reflected the next time the script is saved in TradingView.
- **Add a new indicator** – Create a new `*.pine` file under `src/indicators/` and, if it needs shared helpers, import from `src/libraries/` using `import <path>`.

**Common pitfalls for an agent**
- **Assuming a test suite exists** – there are no automated tests; an agent must not try to run `npm test`, `pytest`, etc.
- **Looking for a build or package manager** – the repo contains no `package.json`, `Makefile`, `gradle`, etc.; attempts to run `npm install` or similar will fail.
- **Expecting CI scripts** – no `.github/workflows` or pre‑commit hooks are present, so no CI‑related commands are needed.
- **Mis‑identifying entry points** – the only “executable” artefacts are the Pine scripts themselves; there is no main application file.

**Typical agent actions**
- **Read/modify a Pine script** – use the `Read` tool to fetch the file, edit with `apply_patch`, then `Write` if required.
- **Search for an indicator** – `Grep` across `*.pine` files (e.g., `grep pattern="ETSB"`).
- **List available indicators** – `Glob pattern="src/indicators/*.pine"` and return the filenames.

**Guidance for future OpenCode sessions**
- Treat the repository as a **static collection of scripts**; focus on file‑level edits rather than project‑wide commands.
- When a user asks to “run” or “test” something, clarify that the only execution context is TradingView’s Pine editor.
- If a user needs to add a new library function, place it under `src/libraries/` and import it with the correct relative path.

// End of file
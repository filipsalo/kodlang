# Kod for Zed

Zed extension for the Kod language. Bundles:

- Syntax highlighting (via the sibling `tree-sitter-kod/` grammar)
- Auto-close brackets, indent rules, outline support
- Diagnostics (via `tools/lsp.kod` — the in-tree language server)

## Install as a dev extension

1. Build the language server once so Zed has something to launch:

   ```sh
   uv run kod build tools/lsp.kod
   ```

   This produces `build/apps/lsp/lsp` (referenced by `extension.toml`).

2. `tree-sitter-kod/` must be its own git repo for Zed to clone it via
   the `file://` URL in `extension.toml`. First time only:

   ```sh
   cd tree-sitter-kod
   git init && git add . && git commit -m "Initial commit"
   git rev-parse HEAD   # → paste into extension.toml's `commit`
   ```

3. In Zed, open the command palette and run **`zed: install dev
   extension`**. Pick this directory (`zed-extension/`). Zed clones
   the grammar, compiles it, and registers the `Kod` language.

4. Open any `.kod` file. Syntax highlighting kicks in immediately.
   Errors from the language server show up as you type.

## Reloading

After grammar edits, commit them inside `tree-sitter-kod/` and update
the `commit` sha in `extension.toml`. Bumping `version` and rerunning
**`zed: install dev extension`** picks up the new sha. The LSP binary
doesn't need re-registering — just rebuild it (`uv run kod build
tools/lsp.kod`); Zed picks up the new binary on next launch.

## What still doesn't work

The bundled LSP only handles single-file diagnostics — open a file
that uses `import "json"` and the server reports bogus errors because
it can't resolve cross-module names. Syntax highlighting works
regardless. See the top-level project memory for what's pending on the
LSP side.

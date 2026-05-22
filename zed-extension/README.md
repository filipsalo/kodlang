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

2. In Zed, open the command palette and run **`zed: install dev extension`**.
   Pick this directory (`zed-extension/`). Zed will compile the
   tree-sitter grammar from the sibling `tree-sitter-kod/` path and
   register the `Kod` language.

3. Open any `.kod` file. Syntax highlighting kicks in immediately.
   Errors from the language server show up as you type.

## Reloading

Bumping `version` in `extension.toml` and re-running the install command
picks up grammar / query / config changes. The LSP binary doesn't need
re-registering — just rebuild it (`uv run kod build tools/lsp.kod`) and
Zed will pick up the new binary on next launch.

## What still doesn't work

The bundled LSP only handles single-file diagnostics — open a file
that uses `import "json"` and the server reports bogus errors because
it can't resolve cross-module names. Syntax highlighting works
regardless. See the top-level project memory for what's pending on the
LSP side.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Jupyter kernel for **Syma**, a symbolic-first programming language (Wolfram Language-inspired, Rust backend). The kernel (`SymaKernel`) launches a persistent `syma --kernel` subprocess and communicates over a JSON line-delimited protocol.

## Commands

```bash
pip install -e .          # Install Python package (editable)
python install.py         # Register kernel spec with Jupyter
jupyter kernelspec list   # Verify kernel is registered
jupyter console --kernel syma   # Test kernel headless
jupyter notebook          # Launch notebook UI
```

## Architecture

### JSON Protocol (kernel ↔ syma `--kernel`)

**Request** (one JSON line per stdin write):
```json
{"input": "Expand[(x+y)^2]", "format": "inputform"}
```

**Response** (one JSON line per stdout read):
```json
{
  "success": true,
  "results": [
    {"output": "x^2 + 2 x y + y^2", "value": {"h":"Plus","t":"call","v":[...]}},
    null
  ],
  "messages": ["Power::infy: Infinite expression 1/0 encountered."],
  "error": null,
  "timing_ms": 0
}
```

- **`results` array**: one entry per top-level expression. `null` means suppressed (trailing `;`).
- **`value` tagged tree**: AST with types `int`, `str`, `sym`, `bool`, `rat`, `list`, `call`, `rule`, `img`, `assoc`.
- **`messages`**: diagnostic/warning strings (rendered as Jupyter stderr stream).

### Key files

| File | Role |
|---|---|
| `syma_kernel/kernel.py` | `SymaKernel` class — all kernel logic (427 lines) |
| `syma_kernel/__main__.py` | Entry point: `IPKernelApp.launch_instance(kernel_class=SymaKernel)` |
| `install.py` | Installs `kernel.json` spec so Jupyter discovers the kernel |
| `setup.py` | Python package metadata |

### SymaKernel class structure

- **`_start_syma()`** — spawns `syma --kernel` as subprocess (stdin/stdout/stderr pipes)
- **`_eval(code)`** — writes JSON request, reads one JSON response, retries once on failure
- **`do_execute(code, silent, ...)`** — handles `%format` magic, then delegates to `_eval`, iterates `results` array sending each non-null entry as `execute_result`
- **`do_complete`** / **`do_inspect`** — tab-completion stub / `?name` help lookup
- **`_handle_format_magic`** — `%format inputform|fullform` cell magic
- **Rich output** — `_enrich_with_image` (inline base64 img), `_enrich_with_list` (HTML), `_enrich_with_assoc` (HTML table)

### Protocol conventions

- The `syma --kernel` binary is located via `$PATH`, `~/.cargo/bin/`, or relative `target/{release,debug}/` (sibling repo dev install).
- Override with `SYMA_KERNEL_BIN` env var.
- Default output format is `"inputform"`; `"fullform"` available via `%format fullform`.

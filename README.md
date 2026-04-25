# Syma Jupyter Kernel

A [Jupyter](https://jupyter.org/) kernel for the **Syma** symbolic-first programming language (inspired by Wolfram Language).

## Requirements

- Python 3.8+
- `ipykernel` (≥ 6.0)
- The `syma` binary on your `$PATH`

### Building syma

```bash
git clone https://github.com/syma-lang/syma
cd syma
cargo build --release
cp target/release/syma ~/.cargo/bin/
```

## Install

```bash
# From this directory:
pip install -e .         # install the Python package
python install.py        # register the kernel with Jupyter
```

Or in one shot:

```bash
pip install -e . && python install.py
```

Verify it is registered:

```bash
jupyter kernelspec list
# → syma    /home/user/.local/share/jupyter/kernels/syma
```

## Usage

Launch Jupyter and select the **Syma** kernel:

```bash
jupyter notebook    # or jupyter lab
```

Or use the kernel with `nbclient` / `papermill` / `nbconvert` programmatically.

## Examples

In a notebook cell, type syma code and run it:

```
42
```

```
Sin[Pi/2] + Cos[0]
```

```
x = 10; y = 20; x + y
```

```
Table[i^2, {i, 1, 10}]
```

```
Plot[Sin[x], {x, 0, 2 Pi}]
```

## How It Works

The kernel launches a persistent `syma --kernel` subprocess and communicates
over a JSON protocol (one JSON request per line to stdin, one JSON response
per line from stdout). This is the same protocol used by the syma REPL's
`--kernel` flag, so no additional hardware-level IPC is needed.

## Environment

| Variable | Purpose |
|---|---|
| `SYMA_KERNEL_BIN` | Path to the `syma` binary (auto-detected by default) |

## Development

```bash
pip install -e .           # editable install
python install.py --user   # register kernel
jupyter console --kernel syma   # test without a browser
```

## License

MIT — see the [syma project](https://github.com/syma-lang/syma) for details.

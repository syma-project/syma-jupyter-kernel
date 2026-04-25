#!/usr/bin/env python3
"""Install the Syma Jupyter kernel spec.

Usage:
    python install.py                 # Install for the current user
    python install.py --user          # Install for the current user (explicit)
    python install.py --sys-prefix    # Install to the current Python's sys.prefix
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Syma Jupyter kernel spec")
    parser.add_argument(
        "--user",
        action="store_true",
        help="Install to the user kernel directory (default)",
    )
    parser.add_argument(
        "--sys-prefix",
        action="store_true",
        default=False,
        help="Install to sys.prefix (useful for virtual environments)",
    )
    args = parser.parse_args()

    # Determine the kernel module path
    kernel_dir = Path(__file__).resolve().parent
    module_dir = kernel_dir / "syma_kernel"
    if not module_dir.is_dir():
        print("Error: syma_kernel/ directory not found alongside install.py", file=sys.stderr)
        sys.exit(1)

    kernel_json = {
        "argv": [
            sys.executable,
            "-m",
            "syma_kernel",
            "-f",
            "{connection_file}",
        ],
        "display_name": "Syma",
        "language": "syma",
        "interrupt_mode": "signal",
    }

    # Write kernel.json to a temporary directory, then use install_kernel_spec
    tmpdir = Path(tempfile.mkdtemp())
    spec_dir = tmpdir / "syma"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "kernel.json").write_text(json.dumps(kernel_json, indent=2))

    try:
        from jupyter_client.kernelspec import KernelSpecManager

        ksm = KernelSpecManager()

        if args.sys_prefix:
            dest = ksm.install_kernel_spec(str(spec_dir), "syma", prefix=sys.prefix)
        else:
            dest = ksm.install_kernel_spec(str(spec_dir), "syma", user=True)

        print(f"Installed Syma kernel spec to: {dest}")
        print()
        print("To verify:  jupyter kernelspec list")
        print("To use:     jupyter notebook  or  jupyter lab")

    except ImportError:
        # Fallback for environments without jupyter_client
        if args.sys_prefix:
            base = Path(sys.prefix) / "share" / "jupyter" / "kernels"
        else:
            base = Path.home() / ".local" / "share" / "jupyter" / "kernels"

        dest = base / "syma"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "kernel.json").write_text(json.dumps(kernel_json, indent=2))
        print(f"Installed Syma kernel spec to: {dest}")
    finally:
        # Clean up temp directory
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print("Usage:")
    print("  jupyter notebook   # or jupyter lab")
    print("  jupyter console --kernel syma   # test headless")


if __name__ == "__main__":
    main()

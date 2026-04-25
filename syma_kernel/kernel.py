"""Syma Jupyter kernel — communicates with the syma --kernel binary over JSON."""

import base64
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

from ipykernel.kernelbase import Kernel


def _find_syma_binary() -> str:
    """Locate the ``syma`` binary on ``$PATH`` or in common locations."""
    # 1. Direct lookup on $PATH
    which = shutil.which("syma")
    if which:
        return which

    # 2. Common install locations
    candidates = [
        os.path.expanduser("~/.cargo/bin/syma"),
        os.path.expanduser("~/.syma/bin/syma"),
        "/usr/local/bin/syma",
        "/opt/homebrew/bin/syma",
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # 3. Look relative to the kernel package (dev install, sibling repo)
    kernel_dir = Path(__file__).resolve().parent
    for candidate in (
        kernel_dir.parent / "target" / "release" / "syma",
        kernel_dir.parent / "target" / "debug" / "syma",
    ):
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError(
        "Cannot find the `syma` binary. Make sure it is built and on your "
        "$PATH, or set the SYMA_KERNEL_BIN environment variable."
    )


_SYMA_BIN = os.environ.get("SYMA_KERNEL_BIN") or _find_syma_binary()
_LANGUAGE_INFO: dict[str, Any] = {
    "name": "syma",
    "version": "0.1.0",
    "mimetype": "text/x-syma",
    "file_extension": ".syma",
    "codemirror_mode": "mathematica",
    "pygments_lexer": "mathematica",
    "nbconvert_exporter": "not",
}


class SymaKernel(Kernel):
    """A Jupyter kernel that delegates evaluation to the ``syma`` language runtime.

    The kernel launches a persistent ``syma --kernel`` subprocess and
    communicates with it over a simple JSON-over-stdin/stdout protocol.
    """

    implementation = "syma"
    implementation_version = "0.1.0"
    language = "syma"
    language_version = "0.1.0"
    language_info = _LANGUAGE_INFO
    banner = (
        "Syma v0.1.0 — A Symbolic-First Language\n"
        "Type ?name for help on a symbol.\n"
        "Wolfram Language-inspired, written in Rust."
    )

    FORMATS = ("inputform", "fullform")
    """Supported output format specifiers."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Fallback logger when the kernel is created outside IPKernelApp
        if self.log is None:
            self.log = logging.getLogger("syma_kernel")
        self._syma_proc: subprocess.Popen | None = None
        self._output_format: str = "inputform"
        self._start_syma()

    def _start_syma(self) -> None:
        """Launch the ``syma --kernel`` child process."""
        self.log.info("Starting syma kernel: %s --kernel", _SYMA_BIN)
        try:
            self._syma_proc = subprocess.Popen(
                [_SYMA_BIN, "--kernel"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError:
            self.log.error("syma binary not found: %s", _SYMA_BIN)
            raise
        self.log.info("syma kernel started (pid %d)", self._syma_proc.pid)

    # ── Jupyter protocol handlers ─────────────────────────────────────────────

    def do_execute(
        self,
        code: str,
        silent: bool,
        store_history: bool = True,
        user_expressions: dict[str, Any] | None = None,
        allow_stdin: bool = False,
    ) -> dict[str, Any]:
        """Handle ``execute_request`` from the Jupyter frontend."""
        stripped = code.strip()
        if not stripped:
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Handle %format cell magic
        if stripped.startswith("%format"):
            return self._handle_format_magic(stripped)

        result = self._eval(code)

        if not result["success"]:
            error_msg = result.get("error", "Unknown error")
            traceback = [error_msg]
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "SymaError",
                "evalue": error_msg,
                "traceback": traceback,
            }

        # Successful evaluation
        output = result.get("output", "")
        value = result.get("value")

        # Forward diagnostic messages (warnings, info) to Jupyter stderr stream
        for msg in result.get("messages", []):
            self.send_response(
                self.iopub_socket,
                "stream",
                {"name": "stderr", "text": msg + "\n"},
            )

        if not silent:
            # Iterate the results array — one entry per expression in the input
            for entry in result.get("results", []):
                if entry is None:
                    continue  # suppressed (e.g. ``expr;``)

                output = entry.get("output", "")
                value = entry.get("value")

                # Build display data
                data: dict[str, str] = {}

                if output:
                    data["text/plain"] = output

                # Check for rich output types from the tagged JSON value
                if value and isinstance(value, dict):
                    tag = value.get("t")
                    if tag == "img":
                        self._enrich_with_image(value, data)
                    elif tag == "list":
                        self._enrich_with_list(value, data)
                    elif tag == "assoc":
                        self._enrich_with_assoc(value, data)

                self.send_response(
                    self.iopub_socket,
                    "execute_result",
                    {
                        "data": data,
                        "metadata": {"text/plain": {}},
                        "execution_count": self.execution_count,
                    },
                )

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def do_complete(
        self, code: str, cursor_pos: int
    ) -> dict[str, Any]:
        """Handle ``complete_request`` for tab-completion (stub)."""
        # Future: forward to syma's kernel protocol for builtin-name completion
        return {
            "matches": [],
            "cursor_start": cursor_pos,
            "cursor_end": cursor_pos,
            "metadata": {},
            "status": "ok",
        }

    def do_inspect(
        self, code: str, cursor_pos: int, detail_level: int = 0
    ) -> dict[str, Any]:
        """Handle ``inspect_request`` — show help for a symbol."""
        # Find the symbol under the cursor
        word = self._word_at_cursor(code, cursor_pos)
        if not word:
            return {"status": "ok", "found": False, "data": {}, "metadata": {}}

        # Use the ?name help mechanism
        result = self._eval(f"?{word}")
        if result.get("success"):
            help_text = result.get("output", "")
            if help_text.startswith('"') and help_text.endswith('"') and len(help_text) >= 2:
                help_text = help_text[1:-1]
            if help_text and help_text != word:
                data = {"text/plain": help_text}
                return {"status": "ok", "found": True, "data": data, "metadata": {}}

        return {"status": "ok", "found": False, "data": {}, "metadata": {}}

    def do_shutdown(self, restart: bool) -> dict[str, Any]:
        """Shut down the syma child process."""
        self.log.info("Shutting down syma kernel (restart=%s)", restart)
        if self._syma_proc:
            if self._syma_proc.poll() is None:
                self._syma_proc.terminate()
                try:
                    self._syma_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._syma_proc.kill()
                    self._syma_proc.wait()
            self._syma_proc = None
        return {"restart": restart}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _eval(self, code: str) -> dict[str, Any]:
        """Send code to the syma kernel and return the parsed JSON response.

        Handles connection errors by attempting a single restart.
        """
        if self._syma_proc is None or self._syma_proc.poll() is not None:
            self.log.warning("syma process died, restarting")
            self._start_syma()

        request = json.dumps({"input": code, "format": self._output_format})
        assert self._syma_proc.stdin is not None
        assert self._syma_proc.stdout is not None

        try:
            self._syma_proc.stdin.write(request + "\n")
            self._syma_proc.stdin.flush()
            line = self._syma_proc.stdout.readline()
            if not line:
                raise BrokenPipeError("syma process closed stdout")
            return json.loads(line)
        except (BrokenPipeError, OSError, json.JSONDecodeError) as exc:
            self.log.error("syma communication error: %s", exc)
            # Try once to restart
            self._start_syma()
            assert self._syma_proc is not None
            assert self._syma_proc.stdin is not None
            assert self._syma_proc.stdout is not None
            self._syma_proc.stdin.write(request + "\n")
            self._syma_proc.stdin.flush()
            line = self._syma_proc.stdout.readline()
            if not line:
                return {
                    "success": False,
                    "error": f"syma process unreachable: {exc}",
                    "output": "",
                    "value": None,
                    "timing_ms": 0,
                }
            return json.loads(line)

    @staticmethod
    def _word_at_cursor(code: str, cursor_pos: int) -> str:
        """Extract the identifier at *cursor_pos* in *code*."""
        if not code or cursor_pos < 0 or cursor_pos > len(code):
            return ""
        # Walk left from cursor
        start = cursor_pos
        while start > 0 and (code[start - 1].isalnum() or code[start - 1] in "_?"):
            start -= 1
        # Walk right from cursor
        end = cursor_pos
        while end < len(code) and (code[end].isalnum() or code[end] in "_?"):
            end += 1
        return code[start:end]

    # ── %format magic ─────────────────────────────────────────────────────────

    def _handle_format_magic(self, line: str) -> dict[str, Any]:
        """Handle ``%format <inputform|fullform>`` cell magic."""
        parts = line.split()
        if len(parts) == 1:
            # Show current format
            self.send_response(
                self.iopub_socket,
                "execute_result",
                {
                    "data": {"text/plain": f"Current output format: {self._output_format}"},
                    "metadata": {},
                    "execution_count": self.execution_count,
                },
            )
        elif len(parts) == 2 and parts[1] in self.FORMATS:
            self._output_format = parts[1]
            self.send_response(
                self.iopub_socket,
                "execute_result",
                {
                    "data": {"text/plain": f"Output format set to: {self._output_format}"},
                    "metadata": {},
                    "execution_count": self.execution_count,
                },
            )
        else:
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "SymaError",
                "evalue": f"Unknown format '{parts[1] if len(parts) > 1 else ''}'. "
                f"Supported: {', '.join(self.FORMATS)}",
                "traceback": [],
            }

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    # ── Rich output helpers ───────────────────────────────────────────────────

    def _enrich_with_image(self, value: dict[str, Any], data: dict[str, str]) -> None:
        """Render a tagged ``img`` value.

        When syma includes inline pixel data (``d``) as a base64-encoded PNG
        it is set under ``image/png`` so Jupyter renders it inline.

        Otherwise the ``output`` string (``NumericArray[...]``) is parsed
        and a PNG is generated on the kernel side using built-in modules.
        """
        img_data = value.get("d", "")
        cs = value.get("cs", "")
        w = value.get("w")
        h = value.get("h")

        # Build a human-readable fallback
        dims = f"[{w}x{h}]" if w and h else ""
        label = "Image"
        if cs:
            label += f", {cs}"
        data.setdefault("text/plain", f"{label}{dims}")

        # Inline base64 image data (provided by syma)
        if img_data:
            data["image/png"] = img_data
            return

        # No inline data — try to generate PNG from the output string
        output = data.get("text/plain", "")
        if output and w and h:
            pixels = self._parse_img_pixels(output)
            if pixels is not None:
                mode = "L" if cs.lower() == "grayscale" else "RGB"
                b64 = self._make_png(w, h, pixels, mode)
                data["image/png"] = b64

    def _enrich_with_list(self, value: dict[str, Any], data: dict[str, str]) -> None:
        """Add HTML rendering for a tagged ``list`` value.

        Expected JSON structure from syma:
          { "t": "list", "items": [...] }
        """
        items = value.get("items", [])
        html = self._render_list_html(items)
        if html:
            data["text/html"] = html

    def _enrich_with_assoc(self, value: dict[str, Any], data: dict[str, str]) -> None:
        """Add HTML table rendering for a tagged ``assoc`` value.

        Expected JSON structure from syma:
          { "t": "assoc", "keys": [...], "values": [...] }
        """
        keys = value.get("keys", [])
        vals = value.get("values", [])
        html = self._render_assoc_html(keys, vals)
        if html:
            data["text/html"] = html

    def _render_list_html(self, items: list) -> str:
        """Render a list as indented HTML."""
        if not items:
            return ""
        parts = ["<pre style='margin: 0;'>{"]
        for item in items:
            parts.append(f"  {self._escape_html(str(item))},")
        parts.append("}</pre>")
        return "\n".join(parts)

    def _render_assoc_html(self, keys: list, vals: list) -> str:
        """Render an association as an HTML table."""
        if not keys:
            return ""
        parts = [
            "<table style='border-collapse: collapse; border: 1px solid #ccc;'>"
        ]
        for k, v in zip(keys, vals):
            parts.append(
                "<tr>"
                f"<td style='padding: 2px 12px; font-weight: bold; "
                f"border: 1px solid #ddd; white-space: nowrap;'>"
                f"{self._escape_html(str(k))}</td>"
                f"<td style='padding: 2px 12px; border: 1px solid #ddd;'>"
                f"{self._escape_html(str(v))}</td>"
                "</tr>"
            )
        parts.append("</table>")
        return "\n".join(parts)

    @staticmethod
    def _escape_html(s: str) -> str:
        """Escape HTML special characters."""
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ── Image rendering helpers ───────────────────────────────────────────────

    @staticmethod
    def _parse_img_pixels(output: str) -> list[int] | None:
        """Parse pixel values from an MMA-formatted ``NumericArray`` in *output*.

        Handles both 2-D (grayscale) and 3-D (RGB) arrays with ``Real32``
        values.  Returns a flat ``[0..255]`` byte list in row-major order.
        """
        m = re.search(r"NumericArray\[(.+?),\s*\"[^\"]*\"\]", output, re.DOTALL)
        if not m:
            return None

        # Convert MMA ``{…}`` lists to JSON ``[…]`` and parse
        try:
            arr = json.loads(m.group(1).replace("{", "[").replace("}", "]"))
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(arr, list) or not arr:
            return None

        # Flatten and scale ``[0, 1]`` floats to ``[0, 255]`` bytes
        def _to_byte(v: float) -> int:
            return max(0, min(255, round(v * 255)))

        pixels: list[int] = []

        # Determine depth: first element of first row
        first = arr[0]
        if isinstance(first, list) and first and isinstance(first[0], list):
            # 3-D RGB array:  arr[row][col][channel]
            for row in arr:
                for col in row:
                    for ch in col:
                        pixels.append(_to_byte(ch))
        elif isinstance(first, list):
            # 2-D grayscale array:  arr[row][col]
            for row in arr:
                for val in row:
                    pixels.append(_to_byte(val))
        else:
            return None

        return pixels

    @staticmethod
    def _make_png(w: int, h: int, pixels: list[int], mode: str) -> str:
        """Generate a base64-encoded PNG from raw *pixels* (no Pillow needed).

        *mode* is ``"L"`` (grayscale, 1 byte/pixel) or ``"RGB"`` (3 bytes/pixel).
        """
        bpp = 1 if mode == "L" else 3
        stride = w * bpp

        sig = b"\x89PNG\r\n\x1a\n"

        # IHDR chunk
        color_type = 0 if mode == "L" else 2
        ihdr_data = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)
        crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", crc)

        # IDAT chunk — raw rows with filter-byte-per-scanline
        raw = bytearray()
        for y in range(h):
            raw.append(0)  # filter: None
            start = y * stride
            raw.extend(pixels[start : start + stride])

        compressed = zlib.compress(bytes(raw))
        crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
        idat = (
            struct.pack(">I", len(compressed))
            + b"IDAT"
            + compressed
            + struct.pack(">I", crc)
        )

        # IEND chunk
        crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", crc)

        return base64.b64encode(sig + ihdr + idat + iend).decode("ascii")

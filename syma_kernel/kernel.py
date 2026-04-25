"""Syma Jupyter kernel — communicates with the syma --kernel binary over JSON."""

import json
import logging
import os
import shutil
import subprocess
import sys
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

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Fallback logger when the kernel is created outside IPKernelApp
        if self.log is None:
            self.log = logging.getLogger("syma_kernel")
        self._syma_proc: subprocess.Popen | None = None
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
        if not code.strip():
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

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

        if not silent:
            # Build display data — start with text/plain
            display_data: dict[str, dict[str, Any]] = {"text/plain": {}}  # metadata
            data: dict[str, str] = {}

            if output:
                data["text/plain"] = output

            # Check for rich output types from the tagged JSON value
            if value and isinstance(value, dict):
                tag = value.get("t")
                if tag == "img":
                    # Image value — add a placeholder text representation
                    w = value.get("w", "?")
                    h = value.get("h", "?")
                    ct = value.get("c", "?")
                    data["text/plain"] = (
                        data.get("text/plain") or f"Image[{w}x{h}, {ct}]"
                    )
                elif tag == "list":
                    # Lists are already rendered in `output` as text
                    pass
                elif tag == "assoc":
                    # Associations rendered via their display string
                    pass

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

        request = json.dumps({"input": code})
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

from __future__ import annotations

from collections.abc import Generator
import subprocess
from typing import List, Optional

# =============================================================================
# STREAMING PROCESS EXECUTION (Elevated Server Credentials)
# =============================================================================
def execute_elevated_streaming_subprocess(
    command: List[str] | str,
    cwd: Optional[str] = None,
    shell: bool = False,
) -> Generator[str, None, None]:
    """Runs commands with the server's elevated credentials and yields output chunks."""
    yield f"[SERVER EXECUTOR] Running: {command}\n"
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        if proc.stdout:
            for line in iter(proc.stdout.readline, ""):
                yield line
            proc.stdout.close()

        rc = proc.wait()
        yield f"\n[SERVER EXECUTOR] Process completed with Exit Code: {rc}\n"
    except Exception as exc:
        yield f"\n[SERVER EXECUTOR ERROR] Execution failure: {exc}\n"
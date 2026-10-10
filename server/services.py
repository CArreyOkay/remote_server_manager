import ctypes
from ctypes import wintypes
from pathlib import Path
import sqlite3
import sys
import threading
from typing import Any, Dict, List
# --- Elevation Guard: Server strictly requires Administrator privileges ---


def enforce_admin_privileges() -> None:
    """Verifies the process is running with elevated administrative credentials."""
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        is_admin = False

    if not is_admin:
        sys.stderr.write(
            "\n"
            + "=" * 78 + "\n"
            + "[CRITICAL ERROR] ELEVATED PRIVILEGES REQUIRED\n"
            + "This server executes administrative actions (Venv, Schtasks, IIS, NSSM)\n"
            + "and must run with elevated Windows Administrator credentials.\n\n"
            + "Please open an elevated terminal (Run as Administrator) and re-launch:\n"
            + f"    python {Path(__file__).name} {' '.join(sys.argv[1:])}\n"
            + "=" * 78 + "\n\n"
        )
        sys.exit(5)  # ERROR_ACCESS_DENIED


enforce_admin_privileges()

# Third-party imports verified after elevation check
try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    sys.stderr.write(
        "[ERROR] Missing dependencies. Run: pip install fastapi uvicorn pydantic\n"
    )
    sys.exit(1)


# =============================================================================
# SYSTEM TELEMETRY STRUCTURES (Kernel32)
# =============================================================================
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


# =============================================================================
# PERSISTENT AUDIT TRAIL DATABASE
# =============================================================================
class ServerAuditTrailDB:
    """Records authenticated client identities, actions, and exit statuses."""

    def __init__(self, db_path: str = "server_audit_trail.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_identity TEXT,
                    is_client_admin INTEGER,
                    operation TEXT,
                    details TEXT,
                    status_code INTEGER,
                    success INTEGER
                )
                """
            )
            conn.commit()

    def record(
        self,
        user: str,
        is_admin: bool,
        operation: str,
        details: str,
        status_code: int,
        success: bool,
    ) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (user_identity, is_client_admin, operation, details, status_code, success)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user, int(is_admin), operation,
                 details, status_code, int(success)),
            )
            conn.commit()

    def fetch_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

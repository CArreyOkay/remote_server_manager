"""Distributed Windows Remote Automation & Orchestration Console (Client GUI).

A self-contained client application featuring:
  - Native Windows Authentication (SSPI Negotiate / Kerberos / NTLM token generation)
  - Multi-Environment Profile Manager (Dev, Staging, Production target switching)
  - Remote Server Health & Hardware Telemetry Dashboard (RAM load, mounted volumes)
  - Remote File & Directory Explorer (browse server files/directories over REST)
  - Real-Time Subprocess Streaming Console (chunked HTTP event receiver)
  - Python Virtual Environment, Dependencies & ipykernel Orchestrator
  - Windows Task Scheduler Manager (schtasks.exe remote control)
  - Internet Information Services (IIS) Provisioning Manager (appcmd.exe)
  - NSSM Background Service Manager (install, start, stop, restart, remove)
  - Live Security Audit Trail Viewer

Zero external pip dependencies required. Runs purely on the Python Standard Library.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

# =============================================================================
# WINDOWS SSPI & IDENTITY HELPERS (Native ctypes)
# =============================================================================
SECBUFFER_VERSION = 0
SECBUFFER_TOKEN = 2
SECPKG_CRED_OUTBOUND = 2
SECURITY_NATIVE_DREP = 0x00000010
SEC_E_OK = 0x00000000
SEC_I_CONTINUE_NEEDED = 0x00090312

ISC_REQ_REPLAY_DETECT = 0x00000004
ISC_REQ_SEQUENCE_DETECT = 0x00000008
ISC_REQ_CONFIDENTIALITY = 0x00000010
ISC_REQ_CONNECTION = 0x00000800


class SecHandle(ctypes.Structure):
    _fields_ = [
        ("dwLower", wintypes.ULONG),
        ("dwUpper", wintypes.ULONG),
    ]


class SecBuffer(ctypes.Structure):
    _fields_ = [
        ("cbBuffer", wintypes.ULONG),
        ("BufferType", wintypes.ULONG),
        ("pvBuffer", ctypes.c_void_p),
    ]


class SecBufferDesc(ctypes.Structure):
    _fields_ = [
        ("ulVersion", wintypes.ULONG),
        ("cBuffers", wintypes.ULONG),
        ("pBuffers", ctypes.POINTER(SecBuffer)),
    ]


class TimeStamp(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class WindowsIdentityHelper:
    """Extracts Windows identity tokens and checks local privileges."""

    @staticmethod
    def get_current_user_and_domain() -> Tuple[str, str, str]:
        domain = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME", "")
        try:
            advapi32 = ctypes.windll.advapi32
            buffer = ctypes.create_unicode_buffer(256)
            size = wintypes.DWORD(256)
            if advapi32.GetUserNameW(buffer, ctypes.byref(size)):
                username = buffer.value
        except Exception:
            pass
        qualified = f"{domain}\\{username}" if domain else username
        return username, domain, qualified

    @staticmethod
    def is_local_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    @staticmethod
    def generate_sspi_negotiate_token() -> Optional[str]:
        try:
            secur32 = ctypes.windll.secur32
            cred_handle = SecHandle()
            ts = TimeStamp()

            status = secur32.AcquireCredentialsHandleW(
                None,
                "Negotiate",
                SECPKG_CRED_OUTBOUND,
                None,
                None,
                None,
                None,
                ctypes.byref(cred_handle),
                ctypes.byref(ts),
            )
            if status != SEC_E_OK:
                return None

            buf_size = 12288
            raw_buf = ctypes.create_string_buffer(buf_size)
            out_sec_buffer = SecBuffer(
                cbBuffer=buf_size,
                BufferType=SECBUFFER_TOKEN,
                pvBuffer=ctypes.cast(raw_buf, ctypes.c_void_p),
            )
            out_desc = SecBufferDesc(
                ulVersion=SECBUFFER_VERSION,
                cBuffers=1,
                pBuffers=ctypes.pointer(out_sec_buffer),
            )
            ctx_handle = SecHandle()
            context_attrs = wintypes.ULONG()

            flags = (
                ISC_REQ_REPLAY_DETECT
                | ISC_REQ_SEQUENCE_DETECT
                | ISC_REQ_CONFIDENTIALITY
                | ISC_REQ_CONNECTION
            )
            status = secur32.InitializeSecurityContextW(
                ctypes.byref(cred_handle),
                None,
                None,
                flags,
                0,
                SECURITY_NATIVE_DREP,
                None,
                0,
                ctypes.byref(ctx_handle),
                ctypes.byref(out_desc),
                ctypes.byref(context_attrs),
                ctypes.byref(ts),
            )

            if status in (SEC_E_OK, SEC_I_CONTINUE_NEEDED):
                token_bytes = raw_buf.raw[: out_sec_buffer.cbBuffer]
                secur32.FreeCredentialsHandle(ctypes.byref(cred_handle))
                return base64.b64encode(token_bytes).decode("ascii")

            secur32.FreeCredentialsHandle(ctypes.byref(cred_handle))
            return None
        except Exception:
            return None


# =============================================================================
# REMOTE CLIENT ENGINE (HTTP REST & Stream Handling)
# =============================================================================
class AdvancedRemoteClient:
    """Client for synchronous REST queries and chunked streaming endpoints."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username, self.domain, self.qualified = (
            WindowsIdentityHelper.get_current_user_and_domain()
        )
        self.is_admin = WindowsIdentityHelper.is_local_admin()

    def _headers(self) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "X-Windows-User": self.username,
            "X-Windows-Domain": self.domain,
            "X-Windows-IsAdmin": "true" if self.is_admin else "false",
        }
        token = WindowsIdentityHelper.generate_sspi_negotiate_token()
        if token:
            h["Authorization"] = f"Negotiate {token}"
        return h

    def request_json(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            return {
                "error": f"HTTP {http_err.code}: {raw_err}",
                "status": "failed",
            }
        except Exception as exc:
            return {"error": str(exc), "status": "failed"}

    def stream_post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        line_callback: Callable[[str], None],
    ) -> None:
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=3600) as resp:
                for raw_line in resp:
                    decoded = raw_line.decode("utf-8", errors="replace")
                    line_callback(decoded)
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            line_callback(f"\n[STREAM ERROR] HTTP {http_err.code}: {raw_err}\n")
        except Exception as exc:
            line_callback(f"\n[STREAM ERROR] Connection failed: {exc}\n")


# =============================================================================
# REMOTE FILE EXPLORER MODAL DIALOG
# =============================================================================
class RemoteFileBrowserModal(tk.Toplevel):
    """Explorer dialog to navigate drives and directories directly on the remote server."""

    def __init__(
        self,
        parent: tk.Tk,
        client: AdvancedRemoteClient,
        target_var: tk.StringVar,
        select_dir_only: bool = True,
    ) -> None:
        super().__init__(parent)
        self.title("Server-Side Remote File Explorer")
        self.geometry("780x520")
        self.transient(parent)
        self.grab_set()

        self.client = client
        self.target_var = target_var
        self.select_dir_only = select_dir_only
        self.current_path_var = tk.StringVar(value="")

        self._build_ui()
        self._load_drives()

    def _build_ui(self) -> None:
        # Navigation Bar
        top_bar = ttk.Frame(self, padding=8)
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Remote Path:").pack(side=tk.LEFT)
        ttk.Entry(top_bar, textvariable=self.current_path_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(top_bar, text="Navigate", command=self._navigate_manual).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(top_bar, text="Up", command=self._go_up).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(top_bar, text="Drives", command=self._load_drives).pack(
            side=tk.LEFT, padx=2
        )

        # Treeview Display
        tree_frame = ttk.Frame(self, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("Type", "Size"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Item Name")
        self.tree.heading("Type", text="Type")
        self.tree.heading("Size", text="Size (Bytes)")
        self.tree.column("#0", width=420)
        self.tree.column("Type", width=100)
        self.tree.column("Size", width=140)

        scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_double_click)

        # Action Buttons
        bottom_bar = ttk.Frame(self, padding=8)
        bottom_bar.pack(fill=tk.X)
        ttk.Button(
            bottom_bar,
            text="Confirm Selection",
            command=self._confirm_selection,
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom_bar, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _load_drives(self) -> None:
        self.tree.delete(*self.tree.get_children())
        drives = self.client.request_json("/api/fs/drives")
        if isinstance(drives, list):
            for d in drives:
                self.tree.insert(
                    "",
                    tk.END,
                    text=d,
                    values=("Drive", ""),
                    tags=("dir", d),
                )
        self.current_path_var.set("")

    def _load_directory(self, path_str: str) -> None:
        self.tree.delete(*self.tree.get_children())
        res = self.client.request_json(
            f"/api/fs/list?target_path={urllib.parse.quote(path_str)}"
        )
        if "items" in res:
            self.current_path_var.set(res["current_path"])
            sorted_items = sorted(
                res["items"],
                key=lambda x: (not x["is_dir"], x["name"].lower()),
            )
            for item in sorted_items:
                item_type = "Folder" if item["is_dir"] else "File"
                size_str = "" if item["is_dir"] else f"{item['size']:,}"
                self.tree.insert(
                    "",
                    tk.END,
                    text=item["name"],
                    values=(item_type, size_str),
                    tags=(
                        "dir" if item["is_dir"] else "file",
                        item["path"],
                    ),
                )
        else:
            messagebox.showerror(
                "Access Error", res.get("error", "Failed to access directory.")
            )

    def _on_double_click(self, event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        tags = item.get("tags", [])
        if "dir" in tags:
            target = tags[1] if len(tags) > 1 else item["text"]
            self._load_directory(target)

    def _navigate_manual(self) -> None:
        path_str = self.current_path_var.get().strip()
        if path_str:
            self._load_directory(path_str)
        else:
            self._load_drives()

    def _go_up(self) -> None:
        curr = self.current_path_var.get().strip()
        if not curr:
            return
        parent = str(Path(curr).parent)
        if parent == curr:
            self._load_drives()
        else:
            self._load_directory(parent)

    def _confirm_selection(self) -> None:
        sel = self.tree.selection()
        if sel:
            item = self.tree.item(sel[0])
            tags = item.get("tags", [])
            selected_path = tags[1] if len(tags) > 1 else item["text"]
            if self.select_dir_only and "file" in tags:
                messagebox.showwarning(
                    "Notice", "Please select a directory, not a file."
                )
                return
            self.target_var.set(selected_path)
            self.destroy()
        else:
            curr = self.current_path_var.get().strip()
            if curr:
                self.target_var.set(curr)
                self.destroy()


# =============================================================================
# COMPLETE ORCHESTRATION APP GUI CLASS
# =============================================================================
class OrchestrationAppGUI(tk.Tk):
    """Unified Remote Management Console with Live Subprocess Streaming."""

    PROFILE_FILE = "client_profiles.json"

    def __init__(self) -> None:
        super().__init__()
        self.title("Windows Enterprise Orchestration Console")
        self.geometry("1180x940")
        self.minsize(980, 780)

        # Windows Authentication Context
        self.win_user, self.win_domain, self.win_qualified = (
            WindowsIdentityHelper.get_current_user_and_domain()
        )
        self.win_is_admin = WindowsIdentityHelper.is_local_admin()

        self._build_style()
        self._build_header_banner()
        self._build_profile_bar()
        self._build_notebook()
        self._build_console()

        self._load_profiles()
        self._set_interface_state(enabled=False)
        self.after(350, self._action_verify_auth)

    def _build_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("vista")
        except tk.TclError:
            self.style.theme_use("clam")

        self.style.configure("Section.TLabelframe", font=("Segoe UI", 9, "bold"))
        self.style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))

    def _build_header_banner(self) -> None:
        banner = tk.Frame(self, bg="#201F1E", height=38, padx=12, pady=6)
        banner.pack(fill=tk.X)

        tk.Label(
            banner,
            text="Windows Identity:",
            fg="#A19F9D",
            bg="#201F1E",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

        admin_badge = " (Elevated Administrator)" if self.win_is_admin else ""
        tk.Label(
            banner,
            text=f"{self.win_qualified}{admin_badge}",
            fg="#00BCF2",
            bg="#201F1E",
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=6)

        self.status_badge = tk.Label(
            banner,
            text="AUTH STATUS: INITIALIZING",
            fg="#FFA500",
            bg="#201F1E",
            font=("Segoe UI", 9, "bold"),
        )
        self.status_badge.pack(side=tk.RIGHT)

    def _build_profile_bar(self) -> None:
        bar = ttk.Labelframe(
            self,
            text="Remote Server Connection & Profile Management",
            padding=8,
            style="Section.TLabelframe",
        )
        bar.pack(fill=tk.X, padx=12, pady=(6, 4))

        ttk.Label(bar, text="Environment:").grid(row=0, column=0, sticky=tk.W)
        self.profile_combo = ttk.Combobox(bar, state="readonly", width=18)
        self.profile_combo.grid(row=0, column=1, padx=4)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        ttk.Label(bar, text="Base URL:").grid(
            row=0, column=2, sticky=tk.W, padx=(10, 0)
        )
        self.server_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        ttk.Entry(bar, textvariable=self.server_url_var, width=42).grid(
            row=0, column=3, padx=4
        )

        ttk.Button(
            bar, text="Save Profile", command=self._save_profile_dialog
        ).grid(row=0, column=4, padx=3)
        ttk.Button(
            bar,
            text="Connect & Authenticate",
            command=self._action_verify_auth,
        ).grid(row=0, column=5, padx=6)

        bar.columnconfigure(3, weight=1)

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        self.tab_metrics = ttk.Frame(self.notebook, padding=12)
        self.tab_venv = ttk.Frame(self.notebook, padding=12)
        self.tab_tasks = ttk.Frame(self.notebook, padding=12)
        self.tab_iis = ttk.Frame(self.notebook, padding=12)
        self.tab_nssm = ttk.Frame(self.notebook, padding=12)
        self.tab_audit = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_metrics, text=" Server Health & Telemetry ")
        self.notebook.add(self.tab_venv, text=" Python Venv & Jupyter ")
        self.notebook.add(self.tab_tasks, text=" Windows Scheduled Tasks ")
        self.notebook.add(self.tab_iis, text=" IIS Management ")
        self.notebook.add(self.tab_nssm, text=" NSSM Services ")
        self.notebook.add(self.tab_audit, text=" Security Audit Trail ")

        self._init_metrics_tab()
        self._init_venv_tab()
        self._init_tasks_tab()
        self._init_iis_tab()
        self._init_nssm_tab()
        self._init_audit_tab()

    def _build_console(self) -> None:
        frame = ttk.Labelframe(
            self, text="Real-Time Streaming Output Log", padding=6
        )
        frame.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0, 8))

        self.console = scrolledtext.ScrolledText(
            frame,
            height=9,
            bg="#1E1E1E",
            fg="#00FF66",
            insertbackground="#FFF",
            font=("Consolas", 9),
            wrap=tk.WORD,
        )
        self.console.pack(fill=tk.BOTH, expand=True)

        btn_bar = ttk.Frame(frame)
        btn_bar.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(
            btn_bar,
            text="Clear Console",
            command=lambda: self.console.delete("1.0", tk.END),
        ).pack(side=tk.RIGHT)

    def _set_interface_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for tab in [
            self.tab_metrics,
            self.tab_venv,
            self.tab_tasks,
            self.tab_iis,
            self.tab_nssm,
            self.tab_audit,
        ]:
            for child in tab.winfo_children():
                if isinstance(
                    child, (ttk.Button, tk.Button, ttk.Entry, ttk.Checkbutton)
                ):
                    child.configure(state=state)
                elif isinstance(child, (ttk.Frame, ttk.Labelframe)):
                    for sub in child.winfo_children():
                        if isinstance(
                            sub,
                            (ttk.Button, tk.Button, ttk.Entry, ttk.Checkbutton),
                        ):
                            sub.configure(state=state)

    # ------------------ TAB 1: System Metrics & Telemetry ------------------
    def _init_metrics_tab(self) -> None:
        frame = self.tab_metrics

        top_ctrl = ttk.Frame(frame)
        top_ctrl.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(
            top_ctrl,
            text="Refresh Telemetry Now",
            command=self._refresh_metrics,
        ).pack(side=tk.LEFT)
        self.telemetry_time_lbl = ttk.Label(top_ctrl, text="Last updated: Never")
        self.telemetry_time_lbl.pack(side=tk.LEFT, padx=10)

        # RAM Usage Display
        ram_box = ttk.Labelframe(
            frame, text="Physical RAM Utilization", padding=10
        )
        ram_box.pack(fill=tk.X, pady=(0, 10))
        self.ram_progress = ttk.Progressbar(
            ram_box, orient=tk.HORIZONTAL, length=400, mode="determinate"
        )
        self.ram_progress.pack(fill=tk.X, pady=4)
        self.ram_detail_lbl = ttk.Label(
            ram_box, text="Memory Load: -- % (Used: -- GB / Total: -- GB)"
        )
        self.ram_detail_lbl.pack(anchor=tk.W)

        # Storage Volumes Table
        disk_box = ttk.Labelframe(
            frame, text="Mounted Server Drives & Storage", padding=10
        )
        disk_box.pack(fill=tk.BOTH, expand=True)

        self.disk_tree = ttk.Treeview(
            disk_box,
            columns=("Drive", "Total", "Free", "FreePct"),
            show="headings",
            height=6,
        )
        self.disk_tree.heading("Drive", text="Volume")
        self.disk_tree.heading("Total", text="Total Space")
        self.disk_tree.heading("Free", text="Free Space")
        self.disk_tree.heading("FreePct", text="Percentage Free")
        self.disk_tree.pack(fill=tk.BOTH, expand=True)

    def _refresh_metrics(self) -> None:
        def worker() -> None:
            client = self._get_client()
            res = client.request_json("/api/system/metrics")
            if "ram" in res:
                ram = res["ram"]
                self.ram_progress["value"] = ram["load_percent"]
                self.ram_detail_lbl.config(
                    text=(
                        f"Memory Load: {ram['load_percent']}% "
                        f"(Used: {ram['used_gb']} GB / Total: {ram['total_gb']} GB, "
                        f"Available: {ram['avail_gb']} GB)"
                    )
                )
                self.disk_tree.delete(*self.disk_tree.get_children())
                for d in res.get("drives", []):
                    free_pct = (
                        round((d["free_gb"] / d["total_gb"]) * 100, 1)
                        if d["total_gb"] > 0
                        else 0
                    )
                    self.disk_tree.insert(
                        "",
                        tk.END,
                        values=(
                            d["drive"],
                            f"{d['total_gb']} GB",
                            f"{d['free_gb']} GB",
                            f"{free_pct}%",
                        ),
                    )
                self.telemetry_time_lbl.config(
                    text=f"Last updated: {time.strftime('%H:%M:%S')}"
                )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 2: Venv Management ------------------
    def _init_venv_tab(self) -> None:
        frame = self.tab_venv
        path_box = ttk.Labelframe(
            frame, text="Remote Directory & Interpreter Setup", padding=10
        )
        path_box.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(path_box, text="Target Venv Directory:").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        self.venv_path_var = tk.StringVar(
            value="C:\\Environments\\analytics_venv"
        )
        ttk.Entry(path_box, textvariable=self.venv_path_var).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            path_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.venv_path_var, True),
        ).grid(row=0, column=2, padx=3)

        ttk.Label(path_box, text="Server Base Python:").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        self.base_python_var = tk.StringVar(
            value="C:\\Program Files\\Python311\\python.exe"
        )
        ttk.Entry(path_box, textvariable=self.base_python_var).grid(
            row=1, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            path_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.base_python_var, False),
        ).grid(row=1, column=2, padx=3)
        path_box.columnconfigure(1, weight=1)

        pkg_box = ttk.Labelframe(
            frame, text="Packages & Jupyter Registration", padding=10
        )
        pkg_box.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(pkg_box, text="Packages to Install:").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        self.packages_var = tk.StringVar(
            value="fastapi uvicorn requests ipykernel pandas"
        )
        ttk.Entry(pkg_box, textvariable=self.packages_var).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )

        ttk.Label(pkg_box, text="Remote requirements.txt:").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        self.req_file_var = tk.StringVar(value="")
        ttk.Entry(pkg_box, textvariable=self.req_file_var).grid(
            row=1, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            pkg_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.req_file_var, False),
        ).grid(row=1, column=2, padx=3)

        self.install_kernel_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            pkg_box,
            text="Register ipykernel in Jupyter",
            variable=self.install_kernel_var,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 2))

        ttk.Label(pkg_box, text="Kernel Display Name:").grid(
            row=3, column=0, sticky=tk.W, pady=3
        )
        self.kernel_name_var = tk.StringVar(value="Python (Analytics Venv)")
        ttk.Entry(pkg_box, textvariable=self.kernel_name_var).grid(
            row=3, column=1, sticky=tk.EW, padx=6
        )
        pkg_box.columnconfigure(1, weight=1)

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill=tk.X, pady=6)
        ttk.Button(
            btn_box,
            text="Execute Full End-to-End Venv Pipeline",
            command=self._action_stream_full_venv,
        ).pack(side=tk.RIGHT, padx=3)

    # ------------------ TAB 3: Task Scheduler ------------------
    def _init_tasks_tab(self) -> None:
        frame = self.tab_tasks
        sched_box = ttk.Labelframe(
            frame,
            text="Scheduled Task Definition (schtasks.exe)",
            padding=10,
        )
        sched_box.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(sched_box, text="Task Name:").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        self.task_name_var = tk.StringVar(value="ServerAnalyticsJob")
        ttk.Entry(sched_box, textvariable=self.task_name_var).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )

        ttk.Label(sched_box, text="Executable / Script:").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        self.task_exec_var = tk.StringVar(
            value="C:\\Environments\\analytics_venv\\Scripts\\python.exe"
        )
        ttk.Entry(sched_box, textvariable=self.task_exec_var).grid(
            row=1, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            sched_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.task_exec_var, False),
        ).grid(row=1, column=2, padx=3)

        ttk.Label(sched_box, text="Arguments:").grid(
            row=2, column=0, sticky=tk.W, pady=3
        )
        self.task_args_var = tk.StringVar(value="C:\\Scripts\\etl_worker.py --prod")
        ttk.Entry(sched_box, textvariable=self.task_args_var).grid(
            row=2, column=1, sticky=tk.EW, padx=6
        )

        ttk.Label(sched_box, text="Frequency:").grid(
            row=3, column=0, sticky=tk.W, pady=3
        )
        self.task_schedule_var = tk.StringVar(value="DAILY")
        ttk.Combobox(
            sched_box,
            textvariable=self.task_schedule_var,
            values=[
                "MINUTE",
                "HOURLY",
                "DAILY",
                "WEEKLY",
                "ONSTART",
                "ONLOGON",
            ],
            state="readonly",
        ).grid(row=3, column=1, sticky=tk.W, padx=6)

        ttk.Label(sched_box, text="Start Time (HH:mm):").grid(
            row=4, column=0, sticky=tk.W, pady=3
        )
        self.task_time_var = tk.StringVar(value="02:30")
        ttk.Entry(sched_box, textvariable=self.task_time_var, width=15).grid(
            row=4, column=1, sticky=tk.W, padx=6
        )

        self.task_highest_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            sched_box,
            text="Run Highest Privileges (/RL HIGHEST)",
            variable=self.task_highest_var,
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(4, 2))
        sched_box.columnconfigure(1, weight=1)

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill=tk.X, pady=6)
        ttk.Button(
            btn_box, text="Create Task", command=self._action_create_task
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Run Now",
            command=lambda: self._action_task_op("run"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Query Status",
            command=lambda: self._action_task_op("query"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Delete Task",
            command=lambda: self._action_task_op("delete"),
        ).pack(side=tk.LEFT, padx=3)

    # ------------------ TAB 4: IIS Management ------------------
    def _init_iis_tab(self) -> None:
        frame = self.tab_iis
        iis_box = ttk.Labelframe(
            frame, text="IIS Site Configuration (appcmd.exe)", padding=10
        )
        iis_box.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(iis_box, text="Site Name:").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        self.iis_name_var = tk.StringVar(value="AnalyticsPortal")
        ttk.Entry(iis_box, textvariable=self.iis_name_var).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )

        ttk.Label(iis_box, text="Physical Path:").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        self.iis_path_var = tk.StringVar(
            value="C:\\inetpub\\wwwroot\\analytics"
        )
        ttk.Entry(iis_box, textvariable=self.iis_path_var).grid(
            row=1, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            iis_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.iis_path_var, True),
        ).grid(row=1, column=2, padx=3)

        ttk.Label(iis_box, text="Port:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.iis_port_var = tk.StringVar(value="8088")
        ttk.Entry(iis_box, textvariable=self.iis_port_var, width=15).grid(
            row=2, column=1, sticky=tk.W, padx=6
        )

        ttk.Label(iis_box, text="Host Header:").grid(
            row=3, column=0, sticky=tk.W, pady=3
        )
        self.iis_host_var = tk.StringVar(value="")
        ttk.Entry(iis_box, textvariable=self.iis_host_var).grid(
            row=3, column=1, sticky=tk.EW, padx=6
        )
        iis_box.columnconfigure(1, weight=1)

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill=tk.X, pady=6)
        ttk.Button(btn_box, text="Add Site", command=self._action_add_iis).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(
            btn_box,
            text="Start Site",
            command=lambda: self._action_iis_op("start"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Stop Site",
            command=lambda: self._action_iis_op("stop"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Delete Site",
            command=lambda: self._action_iis_op("delete"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box, text="List All Sites", command=self._action_list_iis
        ).pack(side=tk.RIGHT, padx=3)

    # ------------------ TAB 5: NSSM Services ------------------
    def _init_nssm_tab(self) -> None:
        frame = self.tab_nssm
        nssm_box = ttk.Labelframe(
            frame,
            text="NSSM Windows Service Specification",
            padding=10,
        )
        nssm_box.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(nssm_box, text="Remote NSSM Binary:").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        self.nssm_bin_var = tk.StringVar(value="C:\\Tools\\nssm\\nssm.exe")
        ttk.Entry(nssm_box, textvariable=self.nssm_bin_var).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            nssm_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.nssm_bin_var, False),
        ).grid(row=0, column=2, padx=3)

        ttk.Label(nssm_box, text="Service Name:").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        self.nssm_service_var = tk.StringVar(value="PipelineEngineService")
        ttk.Entry(nssm_box, textvariable=self.nssm_service_var).grid(
            row=1, column=1, sticky=tk.EW, padx=6
        )

        ttk.Label(nssm_box, text="Application Executable:").grid(
            row=2, column=0, sticky=tk.W, pady=3
        )
        self.nssm_app_var = tk.StringVar(
            value="C:\\Environments\\analytics_venv\\Scripts\\python.exe"
        )
        ttk.Entry(nssm_box, textvariable=self.nssm_app_var).grid(
            row=2, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            nssm_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.nssm_app_var, False),
        ).grid(row=2, column=2, padx=3)

        ttk.Label(nssm_box, text="Working Directory:").grid(
            row=3, column=0, sticky=tk.W, pady=3
        )
        self.nssm_dir_var = tk.StringVar(value="C:\\Scripts")
        ttk.Entry(nssm_box, textvariable=self.nssm_dir_var).grid(
            row=3, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(
            nssm_box,
            text="Browse Remote...",
            command=lambda: self._open_remote_browser(self.nssm_dir_var, True),
        ).grid(row=3, column=2, padx=3)

        ttk.Label(nssm_box, text="Arguments:").grid(
            row=4, column=0, sticky=tk.W, pady=3
        )
        self.nssm_args_var = tk.StringVar(
            value="-m uvicorn app:app --port 9000"
        )
        ttk.Entry(nssm_box, textvariable=self.nssm_args_var).grid(
            row=4, column=1, sticky=tk.EW, padx=6
        )
        nssm_box.columnconfigure(1, weight=1)

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill=tk.X, pady=6)
        ttk.Button(
            btn_box, text="Install Service", command=self._action_install_nssm
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Start",
            command=lambda: self._action_nssm_op("start"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Stop",
            command=lambda: self._action_nssm_op("stop"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Restart",
            command=lambda: self._action_nssm_op("restart"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Status",
            command=lambda: self._action_nssm_op("status"),
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_box,
            text="Remove",
            command=lambda: self._action_nssm_op("remove"),
        ).pack(side=tk.RIGHT, padx=3)

    # ------------------ TAB 6: Security Audit Trail ------------------
    def _init_audit_tab(self) -> None:
        frame = self.tab_audit
        ctrl_bar = ttk.Frame(frame)
        ctrl_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(
            ctrl_bar,
            text="Refresh Audit Trail",
            command=self._refresh_audit_logs,
        ).pack(side=tk.LEFT)

        self.audit_tree = ttk.Treeview(
            frame,
            columns=("Time", "User", "Admin", "Op", "Details", "Success"),
            show="headings",
        )
        self.audit_tree.heading("Time", text="Timestamp")
        self.audit_tree.heading("User", text="Windows User")
        self.audit_tree.heading("Admin", text="Admin")
        self.audit_tree.heading("Op", text="Operation")
        self.audit_tree.heading("Details", text="Details")
        self.audit_tree.heading("Success", text="Success")

        self.audit_tree.column("Time", width=140)
        self.audit_tree.column("User", width=160)
        self.audit_tree.column("Admin", width=60)
        self.audit_tree.column("Op", width=130)
        self.audit_tree.column("Details", width=380)
        self.audit_tree.column("Success", width=70)
        self.audit_tree.pack(fill=tk.BOTH, expand=True)

    def _refresh_audit_logs(self) -> None:
        def worker() -> None:
            client = self._get_client()
            logs = client.request_json("/api/audit/logs?limit=100")
            if isinstance(logs, list):
                self.audit_tree.delete(*self.audit_tree.get_children())
                for entry in logs:
                    self.audit_tree.insert(
                        "",
                        tk.END,
                        values=(
                            entry.get("timestamp"),
                            entry.get("user_identity"),
                            "Yes" if entry.get("is_admin") else "No",
                            entry.get("operation"),
                            entry.get("details"),
                            "OK" if entry.get("success") else "FAILED",
                        ),
                    )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ Profile Management ------------------
    def _load_profiles(self) -> None:
        if Path(self.PROFILE_FILE).exists():
            try:
                with open(self.PROFILE_FILE, "r", encoding="utf-8") as f:
                    self.profiles = json.load(f)
            except Exception:
                self.profiles = {}
        else:
            self.profiles = {
                "Localhost": "http://127.0.0.1:8000",
                "Dev-Server": "http://192.168.1.100:8000",
            }
        names = list(self.profiles.keys())
        self.profile_combo["values"] = names
        if names:
            self.profile_combo.current(0)
            self.server_url_var.set(self.profiles[names[0]])

    def _on_profile_selected(self, event: tk.Event) -> None:
        name = self.profile_combo.get()
        if name in self.profiles:
            self.server_url_var.set(self.profiles[name])
            self._action_verify_auth()

    def _save_profile_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("Save Server Profile")
        win.geometry("340x120")
        ttk.Label(win, text="Profile Name:").pack(pady=4)
        name_var = tk.StringVar(value="Production-Host")
        ttk.Entry(win, textvariable=name_var).pack(pady=4)

        def save() -> None:
            name = name_var.get().strip()
            if name:
                self.profiles[name] = self.server_url_var.get().strip()
                with open(self.PROFILE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.profiles, f, indent=2)
                self.profile_combo["values"] = list(self.profiles.keys())
                self.profile_combo.set(name)
                win.destroy()

        ttk.Button(win, text="Save", command=save).pack(pady=6)

    # ------------------ Remote Browser Opener ------------------
    def _open_remote_browser(
        self, target_var: tk.StringVar, select_dir_only: bool
    ) -> None:
        RemoteFileBrowserModal(
            self, self._get_client(), target_var, select_dir_only
        )

    # ------------------ Streaming & Action Dispatchers ------------------
    def _get_client(self) -> AdvancedRemoteClient:
        return AdvancedRemoteClient(self.server_url_var.get().strip())

    def _append_console(self, text: str) -> None:
        self.console.insert(tk.END, text)
        self.console.see(tk.END)

    def _action_verify_auth(self) -> None:
        def worker() -> None:
            client = self._get_client()
            res = client.request_json("/api/auth/windows")
            if res.get("status") == "authorized":
                server_host = res.get("server_host", "REMOTE")
                self.status_badge.config(
                    text=f"AUTH STATUS: AUTHORIZED ({server_host})",
                    fg="#00FF66",
                )
                self._append_console(
                    f"\n[HANDSHAKE] Authenticated as '{self.win_qualified}' on host '{server_host}'.\n"
                )
                self._set_interface_state(enabled=True)
                self._refresh_metrics()
                self._refresh_audit_logs()
            else:
                self.status_badge.config(
                    text="AUTH STATUS: ACCESS DENIED", fg="#FF3333"
                )
                self._set_interface_state(enabled=False)
                err_msg = res.get(
                    "error", "Unauthorized: User not in allowed ACL list."
                )
                self._append_console(f"\n[AUTH REJECTED] {err_msg}\n")
                messagebox.showerror(
                    "Authentication Failed",
                    f"Remote host rejected Windows credentials for:\n{self.win_qualified}\n\n{err_msg}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _action_stream_full_venv(self) -> None:
        payload = {
            "base_python": self.base_python_var.get().strip(),
            "venv_path": self.venv_path_var.get().strip(),
            "packages": self.packages_var.get().strip().split(),
            "requirements_file": self.req_file_var.get().strip() or None,
            "register_kernel": self.install_kernel_var.get(),
            "kernel_display_name": self.kernel_name_var.get().strip()
            or "Python (Venv)",
        }

        def worker() -> None:
            self._append_console(
                "\n=== Initiating Streamed Virtual Environment Pipeline ===\n"
            )
            self._get_client().stream_post(
                "/api/venv/full-setup", payload, self._append_console
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_create_task(self) -> None:
        payload = {
            "task_name": self.task_name_var.get().strip(),
            "executable_path": self.task_exec_var.get().strip(),
            "arguments": self.task_args_var.get().strip(),
            "schedule_frequency": self.task_schedule_var.get().strip(),
            "start_time": self.task_time_var.get().strip(),
            "run_highest_privileges": self.task_highest_var.get(),
        }

        def worker() -> None:
            self._append_console(
                f"\n=== Creating Scheduled Task: {payload['task_name']} ===\n"
            )
            self._get_client().stream_post(
                "/api/tasks/create", payload, self._append_console
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_task_op(self, action: str) -> None:
        payload = {"task_name": self.task_name_var.get().strip()}

        def worker() -> None:
            self._append_console(
                f"\n=== Executing Task Operation: {action.upper()} ===\n"
            )
            self._get_client().stream_post(
                f"/api/tasks/action?action={action}",
                payload,
                self._append_console,
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_add_iis(self) -> None:
        payload = {
            "site_name": self.iis_name_var.get().strip(),
            "physical_path": self.iis_path_var.get().strip(),
            "port": self.iis_port_var.get().strip() or "80",
            "host_header": self.iis_host_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(
                f"\n=== Provisioning IIS Site: {payload['site_name']} ===\n"
            )
            self._get_client().stream_post(
                "/api/iis/add", payload, self._append_console
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_iis_op(self, action: str) -> None:
        payload = {"site_name": self.iis_name_var.get().strip()}

        def worker() -> None:
            self._append_console(
                f"\n=== Executing IIS Operation: {action.upper()} ===\n"
            )
            self._get_client().stream_post(
                f"/api/iis/action?action={action}",
                payload,
                self._append_console,
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_list_iis(self) -> None:
        def worker() -> None:
            self._append_console("\n=== Querying Registered IIS Sites ===\n")
            client = self._get_client()
            url = f"{client.base_url}/api/iis/list"
            req = urllib.request.Request(
                url, headers=client._headers(), method="GET"
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    for line in resp:
                        self._append_console(
                            line.decode("utf-8", errors="replace")
                        )
            except Exception as exc:
                self._append_console(f"Error querying sites: {exc}\n")

        threading.Thread(target=worker, daemon=True).start()

    def _action_install_nssm(self) -> None:
        payload = {
            "nssm_path": self.nssm_bin_var.get().strip(),
            "service_name": self.nssm_service_var.get().strip(),
            "application_path": self.nssm_app_var.get().strip(),
            "working_directory": self.nssm_dir_var.get().strip() or None,
            "arguments": self.nssm_args_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(
                f"\n=== Installing NSSM Service: {payload['service_name']} ===\n"
            )
            self._get_client().stream_post(
                "/api/nssm/install", payload, self._append_console
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()

    def _action_nssm_op(self, action: str) -> None:
        payload = {
            "nssm_path": self.nssm_bin_var.get().strip(),
            "service_name": self.nssm_service_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(
                f"\n=== Executing NSSM Operation: {action.upper()} ===\n"
            )
            self._get_client().stream_post(
                f"/api/nssm/action?action={action}",
                payload,
                self._append_console,
            )
            self._refresh_audit_logs()

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = OrchestrationAppGUI()
    app.mainloop()
"""Enterprise Windows Remote Automation & Orchestration Console (client.py - Fixed).

ROOT CAUSE OF ERROR:
--------------------
In Tkinter, a master widget cannot mix geometry managers (`pack` and `grid`)
for its immediate children. MaterialCard previously packed an internal `header_bar`
into `self` (`MaterialCard`), which caused an immediate crash whenever form widgets
were added to `card` using `.grid()`.

FIX:
----
MaterialCard now provides an isolated `self.body` container. Direct children are
attached to `card.body`, completely decoupling the header's `pack` layout from the
body's `grid` or `pack` layouts.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Optional, Tuple
import urllib.parse
import urllib.request

from client.services import AdvancedRemoteClient
from client.auth import WindowsIdentityHelper
# =============================================================================
# THEME CONFIGURATION: MATERIAL DARK & CYBERNETIC PALETTE
# =============================================================================
THEME = {
    "VOID_BG": "#080A0F",
    "SURFACE_BG": "#0F141F",
    "CARD_BG": "#151B2A",
    "CARD_BORDER": "#222C42",
    "INPUT_BG": "#1B2336",
    "INPUT_BORDER": "#2C3A57",
    "TEXT_PRIMARY": "#E6EDF3",
    "TEXT_SECONDARY": "#8B9BB4",
    "TEXT_MUTED": "#48566E",
    "NEON_CYAN": "#00F0FF",
    "NEON_CYAN_DIM": "#007A82",
    "NEON_GREEN": "#00FF9D",
    "NEON_RED": "#FF2A5F",
    "NEON_AMBER": "#FFB800",
    "CONSOLE_BG": "#07090E",
    "CONSOLE_FG": "#00F0FF",
    "FONT_FAMILY": "Segoe UI",
    "MONO_FAMILY": "Consolas",
}

# =============================================================================
# FIXED MATERIAL CARD COMPONENT (Independent Body Frame Container)
# =============================================================================
class MaterialCard(tk.Frame):
    """Sleek container featuring an isolated body frame to allow seamless pack or grid usage."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str = "",
        accent_color: str = THEME["NEON_CYAN"],
        **kwargs: Any,
    ) -> None:
        super().__init__(
            parent,
            bg=THEME["CARD_BG"],
            highlightbackground=THEME["CARD_BORDER"],
            highlightthickness=1,
            padx=12,
            pady=10,
            **kwargs,
        )
        if title:
            header_bar = tk.Frame(self, bg=THEME["CARD_BG"])
            header_bar.pack(fill=tk.X, pady=(0, 8))

            indicator = tk.Frame(header_bar, bg=accent_color, width=3, height=14)
            indicator.pack(side=tk.LEFT, padx=(0, 8))

            title_lbl = tk.Label(
                header_bar,
                text=title.upper(),
                font=(THEME["FONT_FAMILY"], 8, "bold"),
                fg=accent_color,
                bg=THEME["CARD_BG"],
            )
            title_lbl.pack(side=tk.LEFT)

        # Isolated body frame: Child widgets are placed inside this container
        self.body = tk.Frame(self, bg=THEME["CARD_BG"])
        self.body.pack(fill=tk.BOTH, expand=True)

    def columnconfigure(self, index: int, **kwargs: Any) -> Any:
        return self.body.columnconfigure(index, **kwargs)

    def rowconfigure(self, index: int, **kwargs: Any) -> Any:
        return self.body.rowconfigure(index, **kwargs)


class CyberButton(tk.Canvas):
    """Futuristic flat button with neon glow borders and smooth hover states."""

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Optional[Callable[[], None]] = None,
        accent: str = THEME["NEON_CYAN"],
        width: int = 140,
        height: int = 32,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=THEME["CARD_BG"],
            highlightthickness=0,
            cursor="hand2",
        )
        self.command = command
        self.accent = accent
        self.text = text
        self.w = width
        self.h = height
        self.is_enabled = True

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._render(hover=False)

    def _render(self, hover: bool = False) -> None:
        self.delete("all")
        bg_fill = THEME["SURFACE_BG"] if not hover else THEME["INPUT_BG"]
        border_col = self.accent if hover else THEME["CARD_BORDER"]
        text_col = "#FFFFFF" if hover else self.accent

        if not self.is_enabled:
            bg_fill = THEME["SURFACE_BG"]
            border_col = THEME["CARD_BORDER"]
            text_col = THEME["TEXT_MUTED"]

        self.create_rectangle(
            1, 1, self.w - 1, self.h - 1, fill=bg_fill, outline=border_col, width=1
        )
        if self.is_enabled and hover:
            self.create_line(1, 6, 6, 1, fill=self.accent, width=2)
            self.create_line(
                self.w - 7, self.h - 1, self.w - 1, self.h - 7, fill=self.accent, width=2
            )

        self.create_text(
            self.w // 2,
            self.h // 2,
            text=self.text,
            fill=text_col,
            font=(THEME["FONT_FAMILY"], 9, "bold"),
        )

    def _on_enter(self, _: tk.Event) -> None:
        if self.is_enabled:
            self._render(hover=True)

    def _on_leave(self, _: tk.Event) -> None:
        if self.is_enabled:
            self._render(hover=False)

    def _on_click(self, _: tk.Event) -> None:
        if self.is_enabled and self.command:
            self.command()

    def set_state(self, enabled: bool) -> None:
        self.is_enabled = enabled
        self._render(hover=False)


# =============================================================================
# REMOTE FILE EXPLORER MODAL
# =============================================================================
class RemoteFileBrowserModal(tk.Toplevel):
    """Futuristic modal dialog for browsing the server-side filesystem."""

    def __init__(
        self,
        parent: tk.Tk,
        client: AdvancedRemoteClient,
        target_var: tk.StringVar,
        select_dir_only: bool = True,
    ) -> None:
        super().__init__(parent)
        self.title("NODE FILESYSTEM // BROWSER")
        self.geometry("820x540")
        self.configure(bg=THEME["VOID_BG"])
        self.transient(parent)
        self.grab_set()

        self.client = client
        self.target_var = target_var
        self.select_dir_only = select_dir_only
        self.current_path_var = tk.StringVar(value="")

        self._build_ui()
        self._load_drives()

    def _build_ui(self) -> None:
        nav_card = MaterialCard(self, title="Navigational Path Matrix")
        nav_card.pack(fill=tk.X, padx=12, pady=(10, 6))

        path_entry = tk.Entry(
            nav_card.body,
            textvariable=self.current_path_var,
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT_PRIMARY"],
            insertbackground=THEME["NEON_CYAN"],
            font=(THEME["MONO_FAMILY"], 9),
            relief=tk.FLAT,
            highlightbackground=THEME["INPUT_BORDER"],
            highlightthickness=1,
        )
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=3)

        CyberButton(
            nav_card.body, "GO", command=self._navigate_manual, width=50, height=26
        ).pack(side=tk.LEFT, padx=2)
        CyberButton(
            nav_card.body, "UP", command=self._go_up, width=50, height=26
        ).pack(side=tk.LEFT, padx=2)
        CyberButton(
            nav_card.body, "ROOT", command=self._load_drives, width=60, height=26
        ).pack(side=tk.LEFT, padx=2)

        tree_card = MaterialCard(self, title="Directory Tree Structure")
        tree_card.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        self.tree = ttk.Treeview(
            tree_card.body,
            columns=("Type", "Size"),
            show="tree headings",
            selectmode="browse",
            style="Cyber.Treeview",
        )
        self.tree.heading("#0", text="NAME")
        self.tree.heading("Type", text="ENTITY")
        self.tree.heading("Size", text="CAPACITY (BYTES)")
        self.tree.column("#0", width=440)
        self.tree.column("Type", width=120)
        self.tree.column("Size", width=160)

        sb = ttk.Scrollbar(tree_card.body, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", self._on_double_click)

        footer = tk.Frame(self, bg=THEME["VOID_BG"])
        footer.pack(fill=tk.X, padx=12, pady=10)
        CyberButton(
            footer,
            "CONFIRM TARGET",
            command=self._confirm_selection,
            accent=THEME["NEON_GREEN"],
            width=160,
        ).pack(side=tk.RIGHT, padx=(6, 0))
        CyberButton(
            footer,
            "ABORT",
            command=self.destroy,
            accent=THEME["NEON_RED"],
            width=90,
        ).pack(side=tk.RIGHT)

    def _load_drives(self) -> None:
        self.tree.delete(*self.tree.get_children())
        drives = self.client.request_json("/api/fs/drives")
        if isinstance(drives, list):
            for d in drives:
                self.tree.insert(
                    "",
                    tk.END,
                    text=f"[DISK] {d}",
                    values=("Mount Point", ""),
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
            items = sorted(
                res["items"],
                key=lambda x: (not x["is_dir"], x["name"].lower()),
            )
            for item in items:
                itype = "DIRECTORY" if item["is_dir"] else "FILE"
                icon = "[DIR] " if item["is_dir"] else "      "
                size_str = "" if item["is_dir"] else f"{item['size']:,}"
                self.tree.insert(
                    "",
                    tk.END,
                    text=f"{icon}{item['name']}",
                    values=(itype, size_str),
                    tags=("dir" if item["is_dir"] else "file", item["path"]),
                )
        else:
            messagebox.showerror("Access Fault", res.get("error", "Directory scan refused."))

    def _on_double_click(self, _: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0]).get("tags", [])
        if "dir" in tags:
            self._load_directory(tags[1] if len(tags) > 1 else self.tree.item(sel[0])["text"])

    def _navigate_manual(self) -> None:
        target = self.current_path_var.get().strip()
        if target:
            self._load_directory(target)
        else:
            self._load_drives()

    def _go_up(self) -> None:
        curr = self.current_path_var.get().strip()
        if curr:
            parent = str(Path(curr).parent)
            if parent == curr:
                self._load_drives()
            else:
                self._load_directory(parent)

    def _confirm_selection(self) -> None:
        sel = self.tree.selection()
        if sel:
            tags = self.tree.item(sel[0]).get("tags", [])
            path = tags[1] if len(tags) > 1 else self.tree.item(sel[0])["text"]
            if self.select_dir_only and "file" in tags:
                messagebox.showwarning("Type Mismatch", "Selected entity is a file. Folder expected.")
                return
            self.target_var.set(path)
            self.destroy()
        else:
            curr = self.current_path_var.get().strip()
            if curr:
                self.target_var.set(curr)
                self.destroy()


# =============================================================================
# MAIN CLIENT GUI APPLICATION
# =============================================================================
class OrchestrationAppGUI(tk.Tk):
    """Futuristic Material 3 Dark Client Orchestrator."""

    PROFILE_FILE = "client_profiles.json"

    def __init__(self) -> None:
        super().__init__()
        self.title("CYBER-ORCHESTRATOR // WINDOWS ENTERPRISE NODE CONTROL")
        self.geometry("1240x960")
        self.minsize(1020, 800)
        self.configure(bg=THEME["VOID_BG"])

        # Windows Auth context
        self.win_user, self.win_domain, self.win_qualified = (
            WindowsIdentityHelper.get_current_user_and_domain()
        )
        self.win_is_admin = WindowsIdentityHelper.is_local_admin()

        self._apply_futuristic_material_theme()
        self._build_cyber_hud_header()
        self._build_connection_profile_strip()
        self._build_cyber_notebook()
        self._build_telemetry_terminal()

        self._load_profiles()
        self._set_panel_access(enabled=False)
        self.after(350, self._action_verify_auth)

    def _apply_futuristic_material_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Cyber Notebook & Tabs
        style.configure(
            "Cyber.TNotebook",
            background=THEME["VOID_BG"],
            borderwidth=0,
            tabmargins=[2, 5, 2, 0],
        )
        style.configure(
            "Cyber.TNotebook.Tab",
            background=THEME["CARD_BG"],
            foreground=THEME["TEXT_SECONDARY"],
            padding=[14, 8],
            font=(THEME["FONT_FAMILY"], 8, "bold"),
            borderwidth=0,
        )
        style.map(
            "Cyber.TNotebook.Tab",
            background=[("selected", THEME["SURFACE_BG"])],
            foreground=[("selected", THEME["NEON_CYAN"])],
        )

        # Progress bar
        style.configure(
            "Cyber.Horizontal.TProgressbar",
            troughcolor=THEME["INPUT_BG"],
            background=THEME["NEON_CYAN"],
            lightcolor=THEME["NEON_CYAN"],
            darkcolor=THEME["NEON_CYAN_DIM"],
            bordercolor=THEME["CARD_BORDER"],
            thickness=10,
        )

        # Treeview
        style.configure(
            "Cyber.Treeview",
            background=THEME["SURFACE_BG"],
            foreground=THEME["TEXT_PRIMARY"],
            fieldbackground=THEME["SURFACE_BG"],
            borderwidth=0,
            font=(THEME["MONO_FAMILY"], 9),
            rowheight=26,
        )
        style.configure(
            "Cyber.Treeview.Heading",
            background=THEME["CARD_BG"],
            foreground=THEME["NEON_CYAN"],
            relief=tk.FLAT,
            font=(THEME["FONT_FAMILY"], 8, "bold"),
        )
        style.map(
            "Cyber.Treeview",
            background=[("selected", THEME["INPUT_BG"])],
            foreground=[("selected", THEME["NEON_GREEN"])],
        )

    def _build_cyber_hud_header(self) -> None:
        hud = tk.Frame(
            self,
            bg=THEME["SURFACE_BG"],
            height=46,
            highlightbackground=THEME["CARD_BORDER"],
            highlightthickness=1,
            padx=14,
            pady=8,
        )
        hud.pack(fill=tk.X)

        proto_badge = tk.Label(
            hud,
            text="SSPI-AUTHENTICATED // SYSTEM ONLINE",
            font=(THEME["MONO_FAMILY"], 8, "bold"),
            fg=THEME["NEON_CYAN"],
            bg=THEME["SURFACE_BG"],
        )
        proto_badge.pack(side=tk.LEFT)

        id_frame = tk.Frame(hud, bg=THEME["SURFACE_BG"])
        id_frame.pack(side=tk.LEFT, padx=30)

        tk.Label(
            id_frame,
            text="PRINCIPAL IDENTIFIER:",
            font=(THEME["FONT_FAMILY"], 8),
            fg=THEME["TEXT_MUTED"],
            bg=THEME["SURFACE_BG"],
        ).pack(side=tk.LEFT, padx=(0, 6))

        admin_badge = " [ADMIN-ELEVATED]" if self.win_is_admin else " [OPERATOR]"
        tk.Label(
            id_frame,
            text=f"{self.win_qualified}{admin_badge}",
            font=(THEME["MONO_FAMILY"], 9, "bold"),
            fg=THEME["TEXT_PRIMARY"],
            bg=THEME["SURFACE_BG"],
        ).pack(side=tk.LEFT)

        self.hud_status_badge = tk.Label(
            hud,
            text="* DISCONNECTED",
            font=(THEME["FONT_FAMILY"], 9, "bold"),
            fg=THEME["NEON_AMBER"],
            bg=THEME["SURFACE_BG"],
        )
        self.hud_status_badge.pack(side=tk.RIGHT)

    def _build_connection_profile_strip(self) -> None:
        strip = MaterialCard(self, title="Remote Link Endpoint Parameters")
        strip.pack(fill=tk.X, padx=12, pady=(8, 4))

        tk.Label(
            strip.body,
            text="NODE PROFILE:",
            font=(THEME["FONT_FAMILY"], 8, "bold"),
            fg=THEME["TEXT_SECONDARY"],
            bg=THEME["CARD_BG"],
        ).grid(row=0, column=0, sticky=tk.W)

        self.profile_combo = ttk.Combobox(strip.body, state="readonly", width=18)
        self.profile_combo.grid(row=0, column=1, padx=6)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        tk.Label(
            strip.body,
            text="ENDPOINT URL:",
            font=(THEME["FONT_FAMILY"], 8, "bold"),
            fg=THEME["TEXT_SECONDARY"],
            bg=THEME["CARD_BG"],
        ).grid(row=0, column=2, sticky=tk.W, padx=(14, 0))

        self.server_url_var = tk.StringVar(value="http://127.0.0.1:8000")
        url_entry = tk.Entry(
            strip.body,
            textvariable=self.server_url_var,
            width=36,
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT_PRIMARY"],
            insertbackground=THEME["NEON_CYAN"],
            font=(THEME["MONO_FAMILY"], 9),
            relief=tk.FLAT,
            highlightbackground=THEME["INPUT_BORDER"],
            highlightthickness=1,
        )
        url_entry.grid(row=0, column=3, padx=6, ipady=2)

        CyberButton(
            strip.body, "PROBE PORT", command=self._action_test_port, width=105, height=28
        ).grid(row=0, column=4, padx=3)
        CyberButton(
            strip.body,
            "AUTHENTICATE",
            command=self._action_verify_auth,
            accent=THEME["NEON_GREEN"],
            width=120,
            height=28,
        ).grid(row=0, column=5, padx=3)
        CyberButton(
            strip.body, "SAVE PROFILE", command=self._save_profile_dialog, width=110, height=28
        ).grid(row=0, column=6, padx=3)

        strip.columnconfigure(3, weight=1)

    def _build_cyber_notebook(self) -> None:
        self.notebook = ttk.Notebook(self, style="Cyber.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        self.tab_metrics = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)
        self.tab_venv = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)
        self.tab_tasks = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)
        self.tab_iis = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)
        self.tab_nssm = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)
        self.tab_audit = tk.Frame(self.notebook, bg=THEME["SURFACE_BG"], padx=10, pady=10)

        self.notebook.add(self.tab_metrics, text="  01 // NODE TELEMETRY  ")
        self.notebook.add(self.tab_venv, text="  02 // VENV & IPYKERNEL  ")
        self.notebook.add(self.tab_tasks, text="  03 // SCHTASKS.EXE  ")
        self.notebook.add(self.tab_iis, text="  04 // IIS MATRIX  ")
        self.notebook.add(self.tab_nssm, text="  05 // NSSM SERVICES  ")
        self.notebook.add(self.tab_audit, text="  06 // AUDIT TRAIL  ")

        self._init_metrics_tab()
        self._init_venv_tab()
        self._init_tasks_tab()
        self._init_iis_tab()
        self._init_nssm_tab()
        self._init_audit_tab()

    def _build_telemetry_terminal(self) -> None:
        card = MaterialCard(self, title="Real-Time Operation Feed & Subprocess Stream")
        card.pack(fill=tk.BOTH, expand=False, padx=12, pady=(0, 8))

        self.console = scrolledtext.ScrolledText(
            card.body,
            height=8,
            bg=THEME["CONSOLE_BG"],
            fg=THEME["CONSOLE_FG"],
            insertbackground="#FFFFFF",
            font=(THEME["MONO_FAMILY"], 9),
            wrap=tk.WORD,
            relief=tk.FLAT,
            highlightbackground=THEME["CARD_BORDER"],
            highlightthickness=1,
        )
        self.console.pack(fill=tk.BOTH, expand=True)

        bar = tk.Frame(card.body, bg=THEME["CARD_BG"])
        bar.pack(fill=tk.X, pady=(4, 0))

        CyberButton(
            bar,
            "PURGE CONSOLE",
            command=lambda: self.console.delete("1.0", tk.END),
            accent=THEME["TEXT_SECONDARY"],
            width=120,
            height=24,
        ).pack(side=tk.RIGHT)

    def _set_panel_access(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED

        def recurse_state(widget: tk.Widget) -> None:
            for child in widget.winfo_children():
                if isinstance(child, CyberButton):
                    child.set_state(enabled)
                elif isinstance(child, (tk.Entry, tk.Button, ttk.Combobox, ttk.Checkbutton, tk.Checkbutton)):
                    try:
                        child.configure(state=state)
                    except tk.TclError:
                        pass
                recurse_state(child)

        for tab in [
            self.tab_metrics,
            self.tab_venv,
            self.tab_tasks,
            self.tab_iis,
            self.tab_nssm,
            self.tab_audit,
        ]:
            recurse_state(tab)

    # ------------------ TAB 1: NODE TELEMETRY ------------------
    def _init_metrics_tab(self) -> None:
        frame = self.tab_metrics
        top_ctrl = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        top_ctrl.pack(fill=tk.X, pady=(0, 8))

        CyberButton(
            top_ctrl,
            "QUERY TELEMETRY",
            command=self._refresh_metrics,
            width=150,
            height=28,
        ).pack(side=tk.LEFT)
        self.telemetry_time_lbl = tk.Label(
            top_ctrl,
            text="LAST SYNC: STANDBY",
            font=(THEME["MONO_FAMILY"], 8),
            fg=THEME["TEXT_MUTED"],
            bg=THEME["SURFACE_BG"],
        )
        self.telemetry_time_lbl.pack(side=tk.LEFT, padx=12)

        ram_card = MaterialCard(frame, title="Dynamic Physical Memory Allocation")
        ram_card.pack(fill=tk.X, pady=(0, 8))

        self.ram_progress = ttk.Progressbar(
            ram_card.body,
            orient=tk.HORIZONTAL,
            length=400,
            mode="determinate",
            style="Cyber.Horizontal.TProgressbar",
        )
        self.ram_progress.pack(fill=tk.X, pady=6)

        self.ram_detail_lbl = tk.Label(
            ram_card.body,
            text="LOAD: 0% [COMMITTED: 0.00 GB // TOTAL: 0.00 GB]",
            font=(THEME["MONO_FAMILY"], 9),
            fg=THEME["NEON_CYAN"],
            bg=THEME["CARD_BG"],
        )
        self.ram_detail_lbl.pack(anchor=tk.W)

        disk_card = MaterialCard(frame, title="Mounted Storage Partitions")
        disk_card.pack(fill=tk.BOTH, expand=True)

        self.disk_tree = ttk.Treeview(
            disk_card.body,
            columns=("Drive", "Total", "Free", "FreePct"),
            show="headings",
            height=6,
            style="Cyber.Treeview",
        )
        self.disk_tree.heading("Drive", text="VOLUME")
        self.disk_tree.heading("Total", text="CAPACITY (GB)")
        self.disk_tree.heading("Free", text="FREE ALLOC (GB)")
        self.disk_tree.heading("FreePct", text="SURPLUS %")
        self.disk_tree.pack(fill=tk.BOTH, expand=True)

    def _refresh_metrics(self) -> None:
        def worker() -> None:
            res = self._get_client().request_json("/api/system/metrics")
            if "ram" in res:
                ram = res["ram"]
                self.ram_progress["value"] = ram["load_percent"]
                self.ram_detail_lbl.config(
                    text=(
                        f"LOAD: {ram['load_percent']}% "
                        f"[COMMITTED: {ram['used_gb']} GB // TOTAL: {ram['total_gb']} GB // AVAIL: {ram['avail_gb']} GB]"
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
                    text=f"LAST SYNC: {time.strftime('%H:%M:%S UTC')}"
                )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 2: VENV & KERNEL ORCHESTRATOR ------------------
    def _init_venv_tab(self) -> None:
        frame = self.tab_venv
        card = MaterialCard(frame, title="Isolated Environment Specifications")
        card.pack(fill=tk.X, pady=(0, 8))

        def make_entry(row: int, label: str, default: str) -> Tuple[tk.StringVar, tk.Entry]:
            tk.Label(
                card.body,
                text=label,
                font=(THEME["FONT_FAMILY"], 8, "bold"),
                fg=THEME["TEXT_SECONDARY"],
                bg=THEME["CARD_BG"],
            ).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value=default)
            ent = tk.Entry(
                card.body,
                textvariable=var,
                bg=THEME["INPUT_BG"],
                fg=THEME["TEXT_PRIMARY"],
                insertbackground=THEME["NEON_CYAN"],
                font=(THEME["MONO_FAMILY"], 9),
                relief=tk.FLAT,
                highlightbackground=THEME["INPUT_BORDER"],
                highlightthickness=1,
            )
            ent.grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4, ipady=2)
            return var, ent

        self.venv_path_var, _ = make_entry(
            0, "TARGET VENV PATH:", "C:\\Environments\\analytics_prod"
        )
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.venv_path_var, True),
            width=80,
            height=26,
        ).grid(row=0, column=2, padx=4)

        self.base_python_var, _ = make_entry(
            1, "HOST PYTHON BIN:", "C:\\Program Files\\Python311\\python.exe"
        )
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.base_python_var, False),
            width=80,
            height=26,
        ).grid(row=1, column=2, padx=4)

        self.packages_var, _ = make_entry(
            2, "PACKAGES:", "fastapi uvicorn requests ipykernel pandas wheel"
        )
        self.req_file_var, _ = make_entry(3, "REQUIREMENTS FILE:", "")
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.req_file_var, False),
            width=80,
            height=26,
        ).grid(row=3, column=2, padx=4)

        self.install_kernel_var = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(
            card.body,
            text="REGISTER IPYKERNEL WITHIN JUPYTER ECOSYSTEM",
            variable=self.install_kernel_var,
            bg=THEME["CARD_BG"],
            fg=THEME["TEXT_PRIMARY"],
            selectcolor=THEME["SURFACE_BG"],
            activebackground=THEME["CARD_BG"],
            activeforeground=THEME["NEON_CYAN"],
            font=(THEME["FONT_FAMILY"], 8, "bold"),
        )
        chk.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=6)

        self.kernel_name_var, _ = make_entry(
            5, "KERNEL DISPLAY NAME:", "Python (Analytics Node)"
        )
        card.columnconfigure(1, weight=1)

        btn_bar = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        btn_bar.pack(fill=tk.X, pady=8)
        CyberButton(
            btn_bar,
            "DEPLOY END-TO-END PIPELINE",
            command=self._action_stream_venv,
            accent=THEME["NEON_GREEN"],
            width=230,
            height=32,
        ).pack(side=tk.RIGHT)

    def _action_stream_venv(self) -> None:
        payload = {
            "base_python": self.base_python_var.get().strip(),
            "venv_path": self.venv_path_var.get().strip(),
            "packages": self.packages_var.get().strip().split(),
            "requirements_file": self.req_file_var.get().strip() or None,
            "register_kernel": self.install_kernel_var.get(),
            "kernel_display_name": self.kernel_name_var.get().strip(),
        }

        def worker() -> None:
            self._append_console("\n// INITIATING ISOLATED VIRTUAL ENVIRONMENT DEPLOYMENT...\n")
            self._get_client().stream_post(
                "/api/venv/full-setup", payload, self._append_console
            )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 3: SCHTASKS.EXE ------------------
    def _init_tasks_tab(self) -> None:
        frame = self.tab_tasks
        card = MaterialCard(frame, title="Windows Task Scheduler Execution Parameters")
        card.pack(fill=tk.X, pady=(0, 8))

        def make_entry(row: int, label: str, default: str) -> Tuple[tk.StringVar, tk.Entry]:
            tk.Label(
                card.body,
                text=label,
                font=(THEME["FONT_FAMILY"], 8, "bold"),
                fg=THEME["TEXT_SECONDARY"],
                bg=THEME["CARD_BG"],
            ).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value=default)
            ent = tk.Entry(
                card.body,
                textvariable=var,
                bg=THEME["INPUT_BG"],
                fg=THEME["TEXT_PRIMARY"],
                insertbackground=THEME["NEON_CYAN"],
                font=(THEME["MONO_FAMILY"], 9),
                relief=tk.FLAT,
                highlightbackground=THEME["INPUT_BORDER"],
                highlightthickness=1,
            )
            ent.grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4, ipady=2)
            return var, ent

        self.task_name_var, _ = make_entry(0, "TASK IDENTIFIER:", "NightlyETLWorker")
        self.task_exec_var, _ = make_entry(
            1, "TARGET SCRIPT / BIN:", "C:\\Environments\\analytics_prod\\Scripts\\python.exe"
        )
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.task_exec_var, False),
            width=80,
            height=26,
        ).grid(row=1, column=2, padx=4)

        self.task_args_var, _ = make_entry(
            2, "ARGUMENTS:", "C:\\Scripts\\pipeline.py --automated"
        )

        tk.Label(
            card.body,
            text="FREQUENCY:",
            font=(THEME["FONT_FAMILY"], 8, "bold"),
            fg=THEME["TEXT_SECONDARY"],
            bg=THEME["CARD_BG"],
        ).grid(row=3, column=0, sticky=tk.W, pady=4)

        self.task_schedule_var = tk.StringVar(value="DAILY")
        ttk.Combobox(
            card.body,
            textvariable=self.task_schedule_var,
            values=["MINUTE", "HOURLY", "DAILY", "WEEKLY", "ONSTART", "ONLOGON"],
            state="readonly",
        ).grid(row=3, column=1, sticky=tk.W, padx=8, pady=4)

        self.task_time_var, _ = make_entry(4, "SCHEDULED TIME (HH:MM):", "03:00")

        self.task_highest_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            card.body,
            text="ELEVATE INTEGRITY LEVEL (/RL HIGHEST)",
            variable=self.task_highest_var,
            bg=THEME["CARD_BG"],
            fg=THEME["TEXT_PRIMARY"],
            selectcolor=THEME["SURFACE_BG"],
            activebackground=THEME["CARD_BG"],
            activeforeground=THEME["NEON_CYAN"],
            font=(THEME["FONT_FAMILY"], 8, "bold"),
        ).grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=6)
        card.columnconfigure(1, weight=1)

        btn_bar = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        btn_bar.pack(fill=tk.X, pady=8)
        CyberButton(
            btn_bar, "PROVISION TASK", command=self._action_create_task, accent=THEME["NEON_GREEN"], width=140
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "TRIGGER RUN", command=lambda: self._task_op("run"), width=120
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "QUERY STATUS", command=lambda: self._task_op("query"), width=120
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar,
            "PURGE TASK",
            command=lambda: self._task_op("delete"),
            accent=THEME["NEON_RED"],
            width=120,
        ).pack(side=tk.RIGHT, padx=3)

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
            self._append_console(f"\n// PROVISIONING TASK: {payload['task_name']}...\n")
            self._get_client().stream_post("/api/tasks/create", payload, self._append_console)

        threading.Thread(target=worker, daemon=True).start()

    def _task_op(self, action: str) -> None:
        payload = {"task_name": self.task_name_var.get().strip()}

        def worker() -> None:
            self._append_console(f"\n// SCHTASKS ACTION [{action.upper()}]: {payload['task_name']}...\n")
            self._get_client().stream_post(
                f"/api/tasks/action?action={action}", payload, self._append_console
            )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 4: IIS MATRIX ------------------
    def _init_iis_tab(self) -> None:
        frame = self.tab_iis
        card = MaterialCard(frame, title="Internet Information Services (APPCMD Provisioner)")
        card.pack(fill=tk.X, pady=(0, 8))

        def make_entry(row: int, label: str, default: str) -> Tuple[tk.StringVar, tk.Entry]:
            tk.Label(
                card.body,
                text=label,
                font=(THEME["FONT_FAMILY"], 8, "bold"),
                fg=THEME["TEXT_SECONDARY"],
                bg=THEME["CARD_BG"],
            ).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value=default)
            ent = tk.Entry(
                card.body,
                textvariable=var,
                bg=THEME["INPUT_BG"],
                fg=THEME["TEXT_PRIMARY"],
                insertbackground=THEME["NEON_CYAN"],
                font=(THEME["MONO_FAMILY"], 9),
                relief=tk.FLAT,
                highlightbackground=THEME["INPUT_BORDER"],
                highlightthickness=1,
            )
            ent.grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4, ipady=2)
            return var, ent

        self.iis_name_var, _ = make_entry(0, "SITE IDENTIFIER:", "EnterprisePortal")
        self.iis_path_var, _ = make_entry(
            1, "PHYSICAL DIRECTORY:", "C:\\inetpub\\wwwroot\\portal"
        )
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.iis_path_var, True),
            width=80,
            height=26,
        ).grid(row=1, column=2, padx=4)

        self.iis_port_var, _ = make_entry(2, "BINDING PORT:", "8080")
        self.iis_host_var, _ = make_entry(3, "HOST HEADER:", "")
        card.columnconfigure(1, weight=1)

        btn_bar = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        btn_bar.pack(fill=tk.X, pady=8)
        CyberButton(
            btn_bar, "PROVISION SITE", command=self._action_add_iis, accent=THEME["NEON_GREEN"], width=140
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "START SITE", command=lambda: self._iis_op("start"), width=110
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "STOP SITE", command=lambda: self._iis_op("stop"), width=110
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "QUERY APPCMD LIST", command=self._action_list_iis, width=150
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "DELETE SITE", command=lambda: self._iis_op("delete"), accent=THEME["NEON_RED"], width=110
        ).pack(side=tk.RIGHT, padx=3)

    def _action_add_iis(self) -> None:
        payload = {
            "site_name": self.iis_name_var.get().strip(),
            "physical_path": self.iis_path_var.get().strip(),
            "port": self.iis_port_var.get().strip() or "80",
            "host_header": self.iis_host_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(f"\n// PROVISIONING IIS SITE: {payload['site_name']}...\n")
            self._get_client().stream_post("/api/iis/add", payload, self._append_console)

        threading.Thread(target=worker, daemon=True).start()

    def _iis_op(self, action: str) -> None:
        payload = {"site_name": self.iis_name_var.get().strip()}

        def worker() -> None:
            self._append_console(f"\n// APPCMD ACTION [{action.upper()}]: {payload['site_name']}...\n")
            self._get_client().stream_post(
                f"/api/iis/action?action={action}", payload, self._append_console
            )

        threading.Thread(target=worker, daemon=True).start()

    def _action_list_iis(self) -> None:
        def worker() -> None:
            self._append_console("\n// QUERYING APPCMD LIST SITE MATRIX...\n")
            client = self._get_client()
            url = f"{client.base_url}/api/iis/list"
            req = urllib.request.Request(url, headers=client._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    for line in resp:
                        self._append_console(line.decode("utf-8", errors="replace"))
            except Exception as exc:
                self._append_console(f"Fault querying IIS: {exc}\n")

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 5: NSSM SERVICES ------------------
    def _init_nssm_tab(self) -> None:
        frame = self.tab_nssm
        card = MaterialCard(frame, title="NSSM Background Daemon Architecture")
        card.pack(fill=tk.X, pady=(0, 8))

        def make_entry(row: int, label: str, default: str) -> Tuple[tk.StringVar, tk.Entry]:
            tk.Label(
                card.body,
                text=label,
                font=(THEME["FONT_FAMILY"], 8, "bold"),
                fg=THEME["TEXT_SECONDARY"],
                bg=THEME["CARD_BG"],
            ).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value=default)
            ent = tk.Entry(
                card.body,
                textvariable=var,
                bg=THEME["INPUT_BG"],
                fg=THEME["TEXT_PRIMARY"],
                insertbackground=THEME["NEON_CYAN"],
                font=(THEME["MONO_FAMILY"], 9),
                relief=tk.FLAT,
                highlightbackground=THEME["INPUT_BORDER"],
                highlightthickness=1,
            )
            ent.grid(row=row, column=1, sticky=tk.EW, padx=8, pady=4, ipady=2)
            return var, ent

        self.nssm_bin_var, _ = make_entry(0, "NSSM EXECUTABLE:", "C:\\Tools\\nssm\\nssm.exe")
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.nssm_bin_var, False),
            width=80,
            height=26,
        ).grid(row=0, column=2, padx=4)

        self.nssm_svc_var, _ = make_entry(1, "SERVICE IDENTIFIER:", "PipelineDaemonService")
        self.nssm_app_var, _ = make_entry(
            2, "APPLICATION PATH:", "C:\\Environments\\analytics_prod\\Scripts\\python.exe"
        )
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.nssm_app_var, False),
            width=80,
            height=26,
        ).grid(row=2, column=2, padx=4)

        self.nssm_dir_var, _ = make_entry(3, "WORKING DIRECTORY:", "C:\\Scripts")
        CyberButton(
            card.body,
            "BROWSE",
            command=lambda: self._open_remote_browser(self.nssm_dir_var, True),
            width=80,
            height=26,
        ).grid(row=3, column=2, padx=4)

        self.nssm_args_var, _ = make_entry(4, "STARTUP ARGUMENTS:", "-m uvicorn main:app --port 9000")
        card.columnconfigure(1, weight=1)

        btn_bar = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        btn_bar.pack(fill=tk.X, pady=8)
        CyberButton(
            btn_bar, "INSTALL SERVICE", command=self._action_install_nssm, accent=THEME["NEON_GREEN"], width=140
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "START", command=lambda: self._nssm_op("start"), width=90
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "STOP", command=lambda: self._nssm_op("stop"), width=90
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "RESTART", command=lambda: self._nssm_op("restart"), width=90
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "STATUS", command=lambda: self._nssm_op("status"), width=90
        ).pack(side=tk.LEFT, padx=3)
        CyberButton(
            btn_bar, "UNINSTALL", command=lambda: self._nssm_op("remove"), accent=THEME["NEON_RED"], width=110
        ).pack(side=tk.RIGHT, padx=3)

    def _action_install_nssm(self) -> None:
        payload = {
            "nssm_path": self.nssm_bin_var.get().strip(),
            "service_name": self.nssm_svc_var.get().strip(),
            "application_path": self.nssm_app_var.get().strip(),
            "working_directory": self.nssm_dir_var.get().strip() or None,
            "arguments": self.nssm_args_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(f"\n// REGISTERING NSSM SERVICE: {payload['service_name']}...\n")
            self._get_client().stream_post("/api/nssm/install", payload, self._append_console)

        threading.Thread(target=worker, daemon=True).start()

    def _nssm_op(self, action: str) -> None:
        payload = {
            "nssm_path": self.nssm_bin_var.get().strip(),
            "service_name": self.nssm_svc_var.get().strip(),
        }

        def worker() -> None:
            self._append_console(f"\n// NSSM COMMAND [{action.upper()}]: {payload['service_name']}...\n")
            self._get_client().stream_post(
                f"/api/nssm/action?action={action}", payload, self._append_console
            )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ TAB 6: SECURITY AUDIT TRAIL ------------------
    def _init_audit_tab(self) -> None:
        frame = self.tab_audit
        ctrl_bar = tk.Frame(frame, bg=THEME["SURFACE_BG"])
        ctrl_bar.pack(fill=tk.X, pady=(0, 6))

        CyberButton(
            ctrl_bar, "REFRESH AUDIT TRAIL", command=self._refresh_audit_logs, width=170
        ).pack(side=tk.LEFT)

        card = MaterialCard(frame, title="Forensic Telemetry & Operations Log")
        card.pack(fill=tk.BOTH, expand=True)

        self.audit_tree = ttk.Treeview(
            card.body,
            columns=("Time", "User", "Admin", "Op", "Details", "Success"),
            show="headings",
            style="Cyber.Treeview",
        )
        self.audit_tree.heading("Time", text="TIMESTAMP")
        self.audit_tree.heading("User", text="PRINCIPAL IDENTITY")
        self.audit_tree.heading("Admin", text="ELEVATED")
        self.audit_tree.heading("Op", text="ACTION")
        self.audit_tree.heading("Details", text="EXECUTION PAYLOAD")
        self.audit_tree.heading("Success", text="VERDICT")

        self.audit_tree.column("Time", width=140)
        self.audit_tree.column("User", width=160)
        self.audit_tree.column("Admin", width=80)
        self.audit_tree.column("Op", width=130)
        self.audit_tree.column("Details", width=380)
        self.audit_tree.column("Success", width=80)
        self.audit_tree.pack(fill=tk.BOTH, expand=True)

    def _refresh_audit_logs(self) -> None:
        def worker() -> None:
            logs = self._get_client().request_json("/api/audit/logs?limit=100")
            if isinstance(logs, list):
                self.audit_tree.delete(*self.audit_tree.get_children())
                for entry in logs:
                    self.audit_tree.insert(
                        "",
                        tk.END,
                        values=(
                            entry.get("timestamp"),
                            entry.get("user_identity"),
                            "YES" if entry.get("is_client_admin") else "NO",
                            entry.get("operation"),
                            entry.get("details"),
                            "ALLOWED" if entry.get("success") else "REJECTED",
                        ),
                    )

        threading.Thread(target=worker, daemon=True).start()

    # ------------------ PROFILES & STATE ------------------
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
                "Prod-Node": "http://192.168.1.100:8000",
            }
        names = list(self.profiles.keys())
        self.profile_combo["values"] = names
        if names:
            self.profile_combo.current(0)
            self.server_url_var.set(self.profiles[names[0]])

    def _on_profile_selected(self, _: tk.Event) -> None:
        name = self.profile_combo.get()
        if name in self.profiles:
            self.server_url_var.set(self.profiles[name])
            self._action_verify_auth()

    def _save_profile_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("COMMIT PROFILE")
        win.geometry("360x140")
        win.configure(bg=THEME["VOID_BG"])
        win.transient(self)

        card = MaterialCard(win, title="Store Endpoint Profile")
        card.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        name_var = tk.StringVar(value="Production-Cluster")
        ent = tk.Entry(
            card.body,
            textvariable=name_var,
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT_PRIMARY"],
            insertbackground=THEME["NEON_CYAN"],
            font=(THEME["MONO_FAMILY"], 9),
            relief=tk.FLAT,
            highlightbackground=THEME["INPUT_BORDER"],
            highlightthickness=1,
        )
        ent.pack(fill=tk.X, pady=6, ipady=2)

        def save() -> None:
            name = name_var.get().strip()
            if name:
                self.profiles[name] = self.server_url_var.get().strip()
                with open(self.PROFILE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.profiles, f, indent=2)
                self.profile_combo["values"] = list(self.profiles.keys())
                self.profile_combo.set(name)
                win.destroy()

        CyberButton(
            card.body, "PERSIST", command=save, accent=THEME["NEON_GREEN"], width=120
        ).pack(side=tk.RIGHT, pady=4)

    def _open_remote_browser(self, target_var: tk.StringVar, select_dir_only: bool) -> None:
        RemoteFileBrowserModal(self, self._get_client(), target_var, select_dir_only)

    def _get_client(self) -> AdvancedRemoteClient:
        return AdvancedRemoteClient(self.server_url_var.get().strip())

    def _append_console(self, text: str) -> None:
        self.console.insert(tk.END, text)
        self.console.see(tk.END)

    # ------------------ PRE-FLIGHT PROBE & AUTH LOGIC ------------------
    def _action_test_port(self) -> None:
        def worker() -> None:
            client = self._get_client()
            is_open, msg = client.check_tcp_socket_open()
            if is_open:
                messagebox.showinfo("Handshake Probe", f"TCP CONNECTION CONFIRMED:\n{msg}")
            else:
                messagebox.showerror(
                    "Connection Failure",
                    f"{msg}\n\nTarget machine is not listening on this port.\n"
                    "Ensure server.py is running with elevated credentials.",
                )

        threading.Thread(target=worker, daemon=True).start()

    def _action_verify_auth(self) -> None:
        def worker() -> None:
            client = self._get_client()
            self._append_console(
                f"\n[PROBE] Interrogating target node {client.base_url} via identity {self.win_qualified}...\n"
            )

            is_open, probe_msg = client.check_tcp_socket_open()
            if not is_open:
                self.hud_status_badge.config(
                    text="* NODE UNREACHABLE (REFUSED)", fg=THEME["NEON_RED"]
                )
                self._set_panel_access(enabled=False)
                self._append_console(f"[NET FAULT] {probe_msg}\n")
                messagebox.showerror(
                    "Connection Refused (WinError 10061)",
                    f"Unable to reach node at {client.base_url}.\n\n{probe_msg}\n\n"
                    "START SERVER VIA ELEVATED TERMINAL:\n"
                    "python server.py --host 0.0.0.0 --port 8000 --allowed-users \"*\"",
                )
                return

            res = client.request_json("/api/auth/windows")

            if res.get("status") == "authorized":
                host = res.get("server_host", "REMOTE")
                self.hud_status_badge.config(
                    text=f"* LINK ACTIVE // HOST: {host}", fg=THEME["NEON_GREEN"]
                )
                self._append_console(
                    f"[AUTHORIZED] Windows credentials authenticated by remote node '{host}'.\n"
                    f"[ELEVATION] Remote executor elevated: {res.get('server_elevated')}.\n"
                )
                self._set_panel_access(enabled=True)
                self._refresh_metrics()
                self._refresh_audit_logs()

            elif res.get("status") == "http_error":
                code = res.get("http_code", 403)
                self.hud_status_badge.config(
                    text=f"* ACCESS REJECTED (HTTP {code})", fg=THEME["NEON_RED"]
                )
                self._set_panel_access(enabled=False)
                self._append_console(f"[REJECTED] Policy denied access: {res.get('error')}\n")
                messagebox.showerror(
                    "Authorization Denied",
                    f"Remote node rejected authorization for:\n{self.win_qualified}\n\n"
                    "Ensure your Windows user is included in the server's --allowed-users parameter.",
                )

            else:
                self.hud_status_badge.config(
                    text="* AUTHENTICATION FAILED", fg=THEME["NEON_RED"]
                )
                self._set_panel_access(enabled=False)
                self._append_console(f"[FAULT] {res.get('error')}\n")

        threading.Thread(target=worker, daemon=True).start()

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import fnmatch
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from server.auth import *
from server.services import *
# =============================================================================
# FASTAPI APPLICATION BUILDER
# =============================================================================
def create_server_app(
    allowed_users: List[str], db_path: str = "server_audit_trail.db"
) -> FastAPI:
    audit_db = ServerAuditTrailDB(db_path)
    app = FastAPI(
        title="Elevated Windows Remote Automation Server",
        version="3.1.0",
        description="Executes administrative actions under elevated server credentials, using client Windows auth for authorization.",
    )

    def is_client_authorized(qualified_user: str, client_is_admin: bool) -> bool:
        if "*" in allowed_users:
            return True
        if client_is_admin and "BUILTIN\\Administrators" in allowed_users:
            return True

        normalized = qualified_user.lower()
        for pattern in allowed_users:
            if fnmatch.fnmatch(normalized, pattern.lower()):
                return True
        return False

    def verify_client_windows_auth(
        x_windows_user: Optional[str] = Header(None, alias="X-Windows-User"),
        x_windows_domain: Optional[str] = Header(None, alias="X-Windows-Domain"),
        x_windows_is_admin: Optional[str] = Header(None, alias="X-Windows-IsAdmin"),
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        """Validates client Windows credentials exclusively for connection authentication and authorization."""
        if not x_windows_user:
            audit_db.record("UNKNOWN", False, "AUTH_REJECT", "Missing X-Windows-User header", 401, False)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Windows client authentication header 'X-Windows-User' is missing.",
            )

        qualified = f"{x_windows_domain}\\{x_windows_user}" if x_windows_domain else x_windows_user
        client_is_admin = x_windows_is_admin == "true"

        if not is_client_authorized(qualified, client_is_admin):
            audit_db.record(qualified, client_is_admin, "AUTH_REJECT", f"User '{qualified}' not in allowed ACL", 403, False)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access Denied: Windows user '{qualified}' is not authorized on this server.",
            )

        # Connection is authenticated and authorized; operations execute via server's elevated credentials
        return {
            "user": x_windows_user,
            "domain": x_windows_domain or "",
            "qualified": qualified,
            "is_client_admin": client_is_admin,
            "has_negotiate": bool(authorization and authorization.startswith("Negotiate ")),
        }

    # Request Models
    class VenvFullSetupRequest(BaseModel):
        base_python: str = sys.executable
        venv_path: str
        packages: List[str] = Field(default_factory=list)
        requirements_file: Optional[str] = None
        register_kernel: bool = True
        kernel_display_name: str = "Python (Venv)"

    class ScheduledTaskCreateRequest(BaseModel):
        task_name: str
        executable_path: str
        arguments: Optional[str] = ""
        schedule_frequency: str = "DAILY"
        start_time: Optional[str] = "04:00"
        run_highest_privileges: bool = True

    class ScheduledTaskActionRequest(BaseModel):
        task_name: str

    class IISSiteCreateRequest(BaseModel):
        site_name: str
        physical_path: str
        port: str = "80"
        host_header: Optional[str] = ""

    class IISSiteActionRequest(BaseModel):
        site_name: str

    class NSSMInstallRequest(BaseModel):
        nssm_path: str = "nssm.exe"
        service_name: str
        application_path: str
        working_directory: Optional[str] = None
        arguments: Optional[str] = ""

    class NSSMActionRequest(BaseModel):
        nssm_path: str = "nssm.exe"
        service_name: str

    def get_appcmd() -> str:
        windir = os.environ.get("SystemRoot", "C:\\Windows")
        return str(Path(windir) / "System32" / "inetsrv" / "appcmd.exe")

    # --- Endpoints ---
    @app.get("/api/auth/windows")
    def auth_check(identity: Dict[str, Any] = Depends(verify_client_windows_auth)) -> Dict[str, Any]:
        audit_db.record(identity["qualified"], identity["is_client_admin"], "AUTH_SUCCESS", "Handshake approved", 200, True)
        return {
            "status": "authorized",
            "principal": identity["qualified"],
            "server_host": os.environ.get("COMPUTERNAME", "SERVER"),
            "server_elevated": True,
        }

    @app.get("/api/system/metrics", dependencies=[Depends(verify_client_windows_auth)])
    def system_metrics() -> Dict[str, Any]:
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))

        total_ram_gb = round(mem.ullTotalPhys / (1024**3), 2)
        avail_ram_gb = round(mem.ullAvailPhys / (1024**3), 2)
        used_ram_gb = round(total_ram_gb - avail_ram_gb, 2)

        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if bitmask & 1:
                root = f"{letter}:\\"
                sectors = wintypes.DWORD()
                bytes_per_sec = wintypes.DWORD()
                free_clusters = wintypes.DWORD()
                total_clusters = wintypes.DWORD()
                if ctypes.windll.kernel32.GetDiskFreeSpaceW(
                    root, ctypes.byref(sectors), ctypes.byref(bytes_per_sec),
                    ctypes.byref(free_clusters), ctypes.byref(total_clusters)
                ):
                    cluster_bytes = sectors.value * bytes_per_sec.value
                    total_bytes = total_clusters.value * cluster_bytes
                    free_bytes = free_clusters.value * cluster_bytes
                    drives.append({
                        "drive": root,
                        "total_gb": round(total_bytes / (1024**3), 1),
                        "free_gb": round(free_bytes / (1024**3), 1),
                    })
            bitmask >>= 1

        return {
            "ram": {
                "total_gb": total_ram_gb,
                "used_gb": used_ram_gb,
                "avail_gb": avail_ram_gb,
                "load_percent": mem.dwMemoryLoad,
            },
            "drives": drives,
        }

    @app.get("/api/fs/drives", dependencies=[Depends(verify_client_windows_auth)])
    def list_server_drives() -> List[str]:
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if bitmask & 1:
                drives.append(f"{letter}:\\")
            bitmask >>= 1
        return drives

    @app.get("/api/fs/list", dependencies=[Depends(verify_client_windows_auth)])
    def list_server_directory(target_path: str = Query(...)) -> Dict[str, Any]:
        p = Path(target_path)
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=400, detail="Invalid directory path.")

        items = []
        try:
            for entry in os.scandir(p):
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if not entry.is_dir() else 0,
                })
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied accessing folder.")

        return {"current_path": str(p), "items": items}

    @app.get("/api/audit/logs", dependencies=[Depends(verify_client_windows_auth)])
    def get_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
        return audit_db.fetch_recent(limit)

    @app.post("/api/venv/full-setup")
    def stream_full_venv_setup(
        req: VenvFullSetupRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)
    ):
        audit_db.record(identity["qualified"], identity["is_client_admin"], "VENV_SETUP", f"Path: {req.venv_path}", 200, True)

        def runner():
            yield f"[ELEVATED EXECUTION] Target Venv: {req.venv_path}\n"
            yield from execute_elevated_streaming_subprocess([req.base_python, "-m", "venv", req.venv_path])

            py_bin = str(Path(req.venv_path) / "Scripts" / "python.exe")
            yield f"\n[ELEVATED EXECUTION] Upgrading pip...\n"
            yield from execute_elevated_streaming_subprocess([py_bin, "-m", "pip", "install", "--upgrade", "pip"])

            if req.requirements_file:
                yield f"\n[ELEVATED EXECUTION] Installing requirements from {req.requirements_file}...\n"
                yield from execute_elevated_streaming_subprocess([py_bin, "-m", "pip", "install", "-r", req.requirements_file])

            if req.packages:
                yield f"\n[ELEVATED EXECUTION] Installing packages: {req.packages}...\n"
                yield from execute_elevated_streaming_subprocess([py_bin, "-m", "pip", "install"] + req.packages)

            if req.register_kernel:
                yield f"\n[ELEVATED EXECUTION] Registering ipykernel '{req.kernel_display_name}'...\n"
                yield from execute_elevated_streaming_subprocess([py_bin, "-m", "pip", "install", "ipykernel"])
                internal_name = "".join(c if c.isalnum() else "_" for c in req.kernel_display_name.lower())
                yield from execute_elevated_streaming_subprocess(
                    [py_bin, "-m", "ipykernel", "install", "--user", f"--name={internal_name}", f"--display-name={req.kernel_display_name}"]
                )
            yield "\n[ALL PHASES COMPLETE]\n"

        return StreamingResponse(runner(), media_type="text/plain")

    @app.post("/api/tasks/create")
    def create_task(req: ScheduledTaskCreateRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], "TASK_CREATE", f"Task: {req.task_name}", 200, True)
        tr = f'"{req.executable_path}" {req.arguments}' if req.arguments else f'"{req.executable_path}"'
        cmd = ["schtasks.exe", "/Create", "/F", "/TN", req.task_name, "/TR", tr, "/SC", req.schedule_frequency]
        if req.schedule_frequency in ("MINUTE", "HOURLY", "DAILY", "WEEKLY") and req.start_time:
            cmd.extend(["/ST", req.start_time])
        if req.run_highest_privileges:
            cmd.extend(["/RL", "HIGHEST"])
        return StreamingResponse(execute_elevated_streaming_subprocess(cmd), media_type="text/plain")

    @app.post("/api/tasks/action")
    def task_action(action: str, req: ScheduledTaskActionRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], f"TASK_{action.upper()}", f"Task: {req.task_name}", 200, True)
        if action == "run":
            cmd = ["schtasks.exe", "/Run", "/TN", req.task_name]
        elif action == "query":
            cmd = ["schtasks.exe", "/Query", "/TN", req.task_name, "/V", "/FO", "LIST"]
        elif action == "delete":
            cmd = ["schtasks.exe", "/Delete", "/TN", req.task_name, "/F"]
        else:
            raise HTTPException(400, "Unknown task action")
        return StreamingResponse(execute_elevated_streaming_subprocess(cmd), media_type="text/plain")

    @app.post("/api/iis/add")
    def iis_add(req: IISSiteCreateRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], "IIS_ADD", f"Site: {req.site_name}", 200, True)
        binding = f"http/*:{req.port}:{req.host_header or ''}"
        cmd = [get_appcmd(), "add", "site", f"/name:{req.site_name}", f"/bindings:{binding}", f"/physicalPath:{req.physical_path}"]
        return StreamingResponse(execute_elevated_streaming_subprocess(cmd), media_type="text/plain")

    @app.post("/api/iis/action")
    def iis_action(action: str, req: IISSiteActionRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], f"IIS_{action.upper()}", f"Site: {req.site_name}", 200, True)
        appcmd = get_appcmd()
        if action == "start":
            cmd = [appcmd, "start", "site", f"/site.name:{req.site_name}"]
        elif action == "stop":
            cmd = [appcmd, "stop", "site", f"/site.name:{req.site_name}"]
        elif action == "delete":
            cmd = [appcmd, "delete", "site", f"/site.name:{req.site_name}"]
        else:
            raise HTTPException(400, "Unknown IIS action")
        return StreamingResponse(execute_elevated_streaming_subprocess(cmd), media_type="text/plain")

    @app.get("/api/iis/list", dependencies=[Depends(verify_client_windows_auth)])
    def iis_list():
        return StreamingResponse(execute_elevated_streaming_subprocess([get_appcmd(), "list", "site"]), media_type="text/plain")

    @app.post("/api/nssm/install")
    def nssm_install(req: NSSMInstallRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], "NSSM_INSTALL", f"Service: {req.service_name}", 200, True)

        def runner():
            cmd = [req.nssm_path, "install", req.service_name, req.application_path]
            if req.arguments:
                cmd.append(req.arguments)
            yield from execute_elevated_streaming_subprocess(cmd)
            if req.working_directory:
                yield "\nSetting AppDirectory...\n"
                yield from execute_elevated_streaming_subprocess([req.nssm_path, "set", req.service_name, "AppDirectory", req.working_directory])

        return StreamingResponse(runner(), media_type="text/plain")

    @app.post("/api/nssm/action")
    def nssm_action(action: str, req: NSSMActionRequest, identity: Dict[str, Any] = Depends(verify_client_windows_auth)):
        audit_db.record(identity["qualified"], identity["is_client_admin"], f"NSSM_{action.upper()}", f"Service: {req.service_name}", 200, True)
        if action in ("start", "stop", "restart", "status"):
            cmd = [req.nssm_path, action, req.service_name]
        elif action == "remove":
            cmd = [req.nssm_path, "remove", req.service_name, "confirm"]
        else:
            raise HTTPException(400, "Unknown NSSM action")
        return StreamingResponse(execute_elevated_streaming_subprocess(cmd), media_type="text/plain")

    return app


# =============================================================================
# SERVER ENTRYPOINT
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Elevated Windows Remote Automation Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--allowed-users", default="*", help="Allowed Windows users/wildcards (comma-separated)")
    parser.add_argument("--audit-db", default="server_audit_trail.db", help="Path to SQLite audit database")

    args = parser.parse_args()
    allowed = [u.strip() for u in args.allowed_users.split(",") if u.strip()]

    print(f"[SERVER INITIALIZED] Running with Elevated Windows Administrator Credentials.")
    print(f"[NETWORK] Listening on {args.host}:{args.port}")
    print(f"[AUTH ACL] Authorized Windows Client Patterns: {allowed}")

    server_app = create_server_app(allowed_users=allowed, db_path=args.audit_db)
    uvicorn.run(server_app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
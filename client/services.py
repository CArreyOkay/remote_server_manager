from auth import WindowsIdentityHelper
import urllib
import socket
from typing import Any, Dict, Optional, Tuple
import json
from collections.abc import Callable
# =============================================================================
# REMOTE CLIENT ENGINE
# =============================================================================


class AdvancedRemoteClient:
    """Interacts with the remote server via JSON and streaming HTTP connections."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username, self.domain, self.qualified = (
            WindowsIdentityHelper.get_current_user_and_domain()
        )
        self.is_admin = WindowsIdentityHelper.is_local_admin()

    def check_tcp_socket_open(self, timeout_sec: float = 2.0) -> Tuple[bool, str]:
        try:
            parsed = urllib.parse.urlparse(self.base_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_sec)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True, f"Port {port} is active and responding."
            elif result == 10061:
                return (
                    False,
                    f"Port {port} refused connection (WinError 10061). Server process is offline.",
                )
            else:
                return False, f"Cannot reach {host}:{port} (Socket Code: {result})."
        except Exception as exc:
            return False, f"Network probe exception: {exc}"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Windows-User": self.username,
            "X-Windows-Domain": self.domain,
            "X-Windows-IsAdmin": "true" if self.is_admin else "false",
        }
        token = WindowsIdentityHelper.generate_sspi_negotiate_token()
        if token:
            headers["Authorization"] = f"Negotiate {token}"
        return headers

    def request_json(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode(
            "utf-8") if payload is not None else None
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            return {
                "status": "http_error",
                "http_code": http_err.code,
                "error": f"HTTP {http_err.code}: {raw_err}",
            }
        except urllib.error.URLError as url_err:
            return {
                "status": "connection_refused",
                "http_code": 0,
                "error": str(url_err.reason),
            }
        except Exception as exc:
            return {"status": "error", "http_code": -1, "error": str(exc)}

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
            line_callback(f"\n[HTTP ERROR {http_err.code}] {raw_err}\n")
        except urllib.error.URLError as url_err:
            line_callback(
                f"\n[NETWORK REFUSED] Server disconnected ({url_err.reason})\n")
        except Exception as exc:
            line_callback(
                f"\n[EXECUTION ERROR] Exception encountered: {exc}\n")

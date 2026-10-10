import ctypes
from ctypes import wintypes
from typing import Optional, Tuple
import os
import base64

# =============================================================================
# WINDOWS SSPI DEFINITIONS (Native ctypes)
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
    _fields_ = [("dwLower", wintypes.ULONG), ("dwUpper", wintypes.ULONG)]


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
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class WindowsIdentityHelper:
    """Manages Windows credentials, user contexts, and SSPI tokens."""

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

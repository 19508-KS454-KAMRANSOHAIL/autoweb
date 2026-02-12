"""
Force OS Logout Module
======================

Provides functionality to force a Windows OS-level logout
when user activity is detected (if enabled).

Uses Windows ExitWindowsEx API with EWX_LOGOFF flag.
Performs clean shutdown of all timers and hooks before logout.

Safety:
- Uses a lock to prevent race conditions during shutdown
- Runs cleanup callback before logout
- Enables required Windows privileges (SeShutdownPrivilege)
- Non-daemon thread ensures logout completes
- App does NOT auto-resume on next login
"""

import ctypes
from ctypes import wintypes
import threading
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ExitWindowsEx flags
EWX_LOGOFF = 0x00000000
EWX_SHUTDOWN = 0x00000001
EWX_REBOOT = 0x00000002
EWX_FORCE = 0x00000004
EWX_FORCEIFHUNG = 0x00000010

# Token privileges
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002


class LUID(ctypes.Structure):
    """Locally Unique Identifier for privilege lookup."""
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    """Privilege with attributes."""
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", wintypes.DWORD),
    ]


class TOKEN_PRIVILEGES(ctypes.Structure):
    """Token privilege adjustment structure."""
    _fields_ = [
        ("PrivilegeCount", wintypes.DWORD),
        ("Privileges", LUID_AND_ATTRIBUTES * 1),
    ]


class ForceLogoutHandler:
    """
    Handles forced Windows OS logout on user activity detection.

    When enabled and user activity is detected:
    1. Stops all timers and hooks (via on_before_logout callback)
    2. Terminates background threads cleanly
    3. Forces OS-level logout using ExitWindowsEx

    The app will NOT auto-resume on next login unless manually launched.
    """

    def __init__(
        self,
        on_before_logout: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the force logout handler.

        Args:
            on_before_logout: Callback to perform cleanup before logout
                              (stop timers, remove hooks, terminate threads)
        """
        self._enabled = False
        self._on_before_logout = on_before_logout
        self._logout_lock = threading.Lock()
        self._logout_in_progress = False

        logger.info("ForceLogoutHandler initialized")

    @property
    def enabled(self) -> bool:
        """Check if force logout is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable force logout."""
        self._enabled = value
        logger.info(f"Force logout {'ENABLED' if value else 'disabled'}")

    def on_user_activity_detected(self) -> None:
        """
        Called when user activity is detected.

        If force logout is enabled, initiates the logout sequence.
        Uses a lock to prevent race conditions during shutdown.
        """
        if not self._enabled:
            return

        with self._logout_lock:
            if self._logout_in_progress:
                return  # Already in progress
            self._logout_in_progress = True

        logger.warning("USER ACTIVITY DETECTED WITH FORCE LOGOUT ENABLED - INITIATING OS LOGOUT")

        # Run cleanup and logout in a separate non-daemon thread
        # Non-daemon ensures completion even if main thread exits
        logout_thread = threading.Thread(
            target=self._execute_logout_sequence,
            name="ForceLogout",
            daemon=False
        )
        logout_thread.start()

    def _execute_logout_sequence(self) -> None:
        """Execute the full logout sequence with clean shutdown."""
        try:
            # Step 1: Run cleanup callback (stops timers, removes hooks, etc.)
            if self._on_before_logout:
                logger.info("Running pre-logout cleanup...")
                try:
                    self._on_before_logout()
                except Exception as e:
                    logger.error(f"Error in pre-logout cleanup: {e}")

            # Step 2: Small delay for cleanup to complete
            time.sleep(0.5)

            # Step 3: Enable shutdown privilege
            self._enable_shutdown_privilege()

            # Step 4: Force logout
            logger.warning("Executing ExitWindowsEx(EWX_LOGOFF | EWX_FORCE)...")
            result = ctypes.windll.user32.ExitWindowsEx(
                EWX_LOGOFF | EWX_FORCE,
                0x00000000
            )

            if not result:
                error = ctypes.GetLastError()
                logger.error(f"ExitWindowsEx failed with error: {error}")

                # Try with FORCEIFHUNG as fallback
                logger.warning("Retrying with EWX_FORCEIFHUNG...")
                result = ctypes.windll.user32.ExitWindowsEx(
                    EWX_LOGOFF | EWX_FORCEIFHUNG,
                    0x00000000
                )
                if not result:
                    logger.error("Force logout failed completely")
            else:
                logger.info("OS logout initiated successfully")

        except Exception as e:
            logger.error(f"Error during force logout sequence: {e}")
        finally:
            with self._logout_lock:
                self._logout_in_progress = False

    def _enable_shutdown_privilege(self) -> None:
        """
        Enable SE_SHUTDOWN_NAME privilege for the current process.

        Required for ExitWindowsEx to work properly on some systems.
        """
        try:
            advapi32 = ctypes.windll.advapi32
            kernel32 = ctypes.windll.kernel32

            # Open process token
            token_handle = wintypes.HANDLE()
            process_handle = kernel32.GetCurrentProcess()

            result = advapi32.OpenProcessToken(
                process_handle,
                TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                ctypes.byref(token_handle)
            )

            if not result:
                logger.warning("Failed to open process token for shutdown privilege")
                return

            try:
                # Lookup privilege LUID
                luid = LUID()
                result = advapi32.LookupPrivilegeValueW(
                    None,
                    "SeShutdownPrivilege",
                    ctypes.byref(luid)
                )

                if not result:
                    logger.warning("Failed to lookup SeShutdownPrivilege")
                    return

                # Adjust privileges
                tp = TOKEN_PRIVILEGES()
                tp.PrivilegeCount = 1
                tp.Privileges[0].Luid = luid
                tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

                result = advapi32.AdjustTokenPrivileges(
                    token_handle,
                    False,
                    ctypes.byref(tp),
                    ctypes.sizeof(tp),
                    None,
                    None
                )

                if result:
                    logger.info("SeShutdownPrivilege enabled successfully")
                else:
                    logger.warning("Failed to adjust token privileges")

            finally:
                kernel32.CloseHandle(token_handle)

        except Exception as e:
            logger.error(f"Error enabling shutdown privilege: {e}")

    def check_session_ending(self) -> bool:
        """
        Check if the Windows session is ending (e.g., user logging out).

        Returns:
            True if session appears to be ending
        """
        try:
            hwnd = ctypes.windll.user32.GetDesktopWindow()
            return hwnd == 0
        except Exception:
            return True

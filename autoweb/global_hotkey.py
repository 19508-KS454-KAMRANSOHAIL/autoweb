"""
Global Hotkey Module
====================

Provides system-wide hotkey registration and handling.
Uses Windows RegisterHotKey API for global keyboard shortcuts
that work even when the application is minimized or not focused.

Default shortcut: Ctrl+Shift+P (configurable in settings)
"""

import ctypes
from ctypes import wintypes
import threading
import time
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Modifier keys
MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Common virtual key codes
VK_MAP = {
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45,
    'F': 0x46, 'G': 0x47, 'H': 0x48, 'I': 0x49, 'J': 0x4A,
    'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F,
    'P': 0x50, 'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54,
    'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59,
    'Z': 0x5A,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73,
    'F5': 0x74, 'F6': 0x75, 'F7': 0x76, 'F8': 0x77,
    'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
}

WM_HOTKEY = 0x0312


class GlobalHotkey:
    """
    Manages a system-wide global hotkey using Windows RegisterHotKey API.

    Works even when the application window is minimized or not in focus.
    Supports configurable key combinations.
    """

    PAUSE_RESUME_ID = 2   # Hotkey ID for pause/resume
    STOP_ID = 1           # Hotkey ID for stop (existing)

    def __init__(
        self,
        on_toggle: Optional[Callable[[], None]] = None,
        modifiers: int = MOD_CTRL | MOD_SHIFT,
        vk_code: int = 0x50,  # 'P' key
        hotkey_id: int = 2
    ):
        """
        Initialize the global hotkey handler.

        Args:
            on_toggle: Callback when hotkey is pressed
            modifiers: Modifier key combination (default: Ctrl+Shift)
            vk_code: Virtual key code (default: P = 0x50)
            hotkey_id: Unique ID for this hotkey registration
        """
        self._on_toggle = on_toggle
        self._modifiers = modifiers
        self._vk_code = vk_code
        self._hotkey_id = hotkey_id
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._registered = False

        logger.info(
            f"GlobalHotkey initialized: modifiers=0x{modifiers:04X}, "
            f"vk=0x{vk_code:02X}, id={hotkey_id}"
        )

    def set_shortcut(self, modifiers: int, vk_code: int) -> None:
        """
        Update the shortcut key combination.

        If already running, will re-register with the new combination.

        Args:
            modifiers: New modifier combination
            vk_code: New virtual key code
        """
        was_running = self._registered
        if was_running:
            self.stop()

        self._modifiers = modifiers
        self._vk_code = vk_code

        if was_running:
            self.start()

    def start(self) -> bool:
        """
        Start listening for the global hotkey.

        Returns:
            True if listener thread started
        """
        if self._registered:
            logger.warning("Hotkey already registered")
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listener_loop,
            name=f"GlobalHotkey-{self._hotkey_id}",
            daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop listening for the global hotkey."""
        if not self._registered and (not self._thread or not self._thread.is_alive()):
            return

        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._registered = False
        logger.info("GlobalHotkey stopped")

    def _listener_loop(self) -> None:
        """Background thread that registers and listens for the hotkey."""
        user32 = ctypes.windll.user32

        # Register the hotkey with MOD_NOREPEAT to avoid repeat triggers
        result = user32.RegisterHotKey(
            None, self._hotkey_id,
            self._modifiers | MOD_NOREPEAT,
            self._vk_code
        )

        if not result:
            error = ctypes.GetLastError()
            logger.error(f"Failed to register hotkey id={self._hotkey_id} (error: {error})")
            return

        self._registered = True
        shortcut_name = self._get_shortcut_name()
        logger.info(f"Global hotkey registered: {shortcut_name}")

        try:
            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                    if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                        logger.info(f"Global hotkey pressed: {shortcut_name}")
                        if self._on_toggle:
                            try:
                                self._on_toggle()
                            except Exception as e:
                                logger.error(f"Error in hotkey callback: {e}")
                else:
                    time.sleep(0.1)
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            self._registered = False
            logger.info(f"Global hotkey unregistered: {shortcut_name}")

    def _get_shortcut_name(self) -> str:
        """Get human-readable name for the current shortcut."""
        parts = []
        if self._modifiers & MOD_CTRL:
            parts.append("Ctrl")
        if self._modifiers & MOD_SHIFT:
            parts.append("Shift")
        if self._modifiers & MOD_ALT:
            parts.append("Alt")
        if self._modifiers & MOD_WIN:
            parts.append("Win")

        # Find key name
        key_name = None
        for name, code in VK_MAP.items():
            if code == self._vk_code:
                key_name = name
                break

        if key_name is None:
            key_name = f"0x{self._vk_code:02X}"

        parts.append(key_name)
        return "+".join(parts)

    @staticmethod
    def parse_shortcut(shortcut_str: str) -> tuple:
        """
        Parse a shortcut string like "Ctrl+Shift+P" into modifiers and vk_code.

        Args:
            shortcut_str: Human-readable shortcut string

        Returns:
            Tuple of (modifiers, vk_code) or (None, None) if invalid
        """
        parts = [p.strip().upper() for p in shortcut_str.split("+")]

        modifiers = 0
        vk_code = None

        for part in parts:
            if part in ("CTRL", "CONTROL"):
                modifiers |= MOD_CTRL
            elif part in ("SHIFT",):
                modifiers |= MOD_SHIFT
            elif part in ("ALT",):
                modifiers |= MOD_ALT
            elif part in ("WIN", "WINDOWS", "SUPER"):
                modifiers |= MOD_WIN
            elif part in VK_MAP:
                vk_code = VK_MAP[part]
            else:
                return (None, None)

        if vk_code is None:
            return (None, None)

        return (modifiers, vk_code)

    @property
    def shortcut_name(self) -> str:
        """Get the current shortcut name."""
        return self._get_shortcut_name()

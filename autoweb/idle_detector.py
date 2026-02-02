"""
Idle Detector Module
====================

This module provides functionality for detecting user activity (mouse movement,
mouse clicks, and keyboard input) on Windows. It uses low-level Windows hooks
to monitor input events system-wide.

Key Concepts:
- SetWindowsHookEx: Installs a hook procedure for monitoring events
- Low-Level Mouse Hook (WH_MOUSE_LL = 14): Monitors all mouse events
- Low-Level Keyboard Hook (WH_KEYBOARD_LL = 13): Monitors all keyboard events
- The hooks run in a separate thread with a message pump

Idle Detection Behavior:
- The app pauses immediately when user performs any mouse/keyboard input
- The app waits until 2 minutes (120 seconds) of no activity
- Only after 2 minutes of complete inactivity, the app resumes
"""

import ctypes
from ctypes import wintypes
import threading
import time
import logging
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum, auto

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Windows API Constants
# ============================================================================

# Hook types
WH_MOUSE_LL = 14      # Low-level mouse hook
WH_KEYBOARD_LL = 13   # Low-level keyboard hook

# Hook callback return
HC_ACTION = 0

# Mouse messages
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A

# Keyboard messages
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105


# ============================================================================
# Windows API Structures
# ============================================================================

class MSLLHOOKSTRUCT(ctypes.Structure):
    """Structure containing mouse hook event information."""
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """Structure containing keyboard hook event information."""
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


# Hook callback type
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM
)


class ActivityType(Enum):
    """Types of user activity detected."""
    MOUSE_MOVE = auto()
    MOUSE_CLICK = auto()
    KEYBOARD = auto()


@dataclass
class IdleState:
    """Current state of idle detection."""
    is_user_active: bool = False      # True if user activity detected recently
    last_activity_time: float = 0.0   # Timestamp of last activity
    idle_duration: float = 0.0        # How long user has been idle
    activity_type: Optional[ActivityType] = None  # Last type of activity


class IdleDetector:
    """
    Detects user activity using Windows low-level hooks.
    
    This class monitors:
    - Mouse movements
    - Mouse clicks (all buttons)
    - Keyboard input (all keys)
    
    When activity is detected:
    - Records the timestamp
    - Calls the on_activity callback immediately
    
    The idle_timeout determines how long after the last activity
    the user is considered "idle" again.
    """
    
    # Default idle timeout: 2 minutes (120 seconds)
    DEFAULT_IDLE_TIMEOUT = 120.0
    
    def __init__(
        self,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        on_activity: Optional[Callable[[ActivityType], None]] = None,
        on_idle: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the IdleDetector.
        
        Args:
            idle_timeout: Seconds of inactivity before considered idle (default: 120)
            on_activity: Callback when user activity is detected
            on_idle: Callback when user becomes idle after timeout
        """
        self.idle_timeout = idle_timeout
        self._on_activity = on_activity
        self._on_idle = on_idle
        
        # State
        self._state = IdleState()
        self._state_lock = threading.Lock()
        
        # Hook handles
        self._mouse_hook = None
        self._keyboard_hook = None
        
        # Thread control
        self._hook_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        
        # Idle check thread
        self._idle_check_thread: Optional[threading.Thread] = None
        
        # Keep references to callbacks to prevent garbage collection
        self._mouse_callback = None
        self._keyboard_callback = None
        
        # Track if we've notified about becoming idle
        self._idle_notified = False
        
        # Last mouse position for filtering micro-movements
        self._last_mouse_pos = (0, 0)
        
        # Flag to temporarily ignore activity (during simulated input)
        self._ignore_activity = False
        self._ignore_lock = threading.Lock()
        
        # Flag for pending activity notification
        self._activity_pending = False
        
        logger.info(f"IdleDetector initialized with {idle_timeout}s timeout")
    
    @property
    def state(self) -> IdleState:
        """Get current idle state (thread-safe)."""
        with self._state_lock:
            return IdleState(
                is_user_active=self._state.is_user_active,
                last_activity_time=self._state.last_activity_time,
                idle_duration=self._state.idle_duration,
                activity_type=self._state.activity_type
            )
    
    @property
    def is_user_active(self) -> bool:
        """Check if user is currently active (within idle timeout)."""
        with self._state_lock:
            if self._state.last_activity_time == 0:
                return False
            elapsed = time.time() - self._state.last_activity_time
            return elapsed < self.idle_timeout
    
    @property
    def seconds_until_idle(self) -> float:
        """Get seconds remaining until user is considered idle."""
        with self._state_lock:
            if self._state.last_activity_time == 0:
                return 0.0
            elapsed = time.time() - self._state.last_activity_time
            remaining = self.idle_timeout - elapsed
            return max(0.0, remaining)
    
    def _mark_active(self) -> None:
        """
        Mark user as active - lightweight, called from hooks.
        Does NOT call callbacks (that's done in the check thread).
        """
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
            self._state.idle_duration = 0.0
        self._idle_notified = False
        self._activity_pending = True  # Flag for check thread to process
    
    def _record_activity(self, activity_type: ActivityType) -> None:
        """
        Record user activity (called from check thread, not hooks).
        
        Args:
            activity_type: Type of activity detected
        """
        # Notify callback (in check thread, not hook thread)
        if self._on_activity:
            try:
                self._on_activity(activity_type)
            except Exception as e:
                logger.error(f"Error in on_activity callback: {e}")
    
    def _mouse_hook_proc(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: wintypes.LPARAM
    ) -> int:
        """
        Low-level mouse hook callback.
        
        Called for every mouse event system-wide.
        MUST return quickly to avoid system lag.
        """
        # Always call next hook FIRST to prevent system lag
        user32 = ctypes.windll.user32
        result = user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)
        
        # Only process if code is valid and not ignoring
        if nCode >= 0:
            with self._ignore_lock:
                if self._ignore_activity:
                    return result
            
            # Simple check - just record time, don't do complex processing
            if wParam == WM_MOUSEMOVE:
                try:
                    mouse_struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    new_pos = (mouse_struct.pt.x, mouse_struct.pt.y)
                    dx = abs(new_pos[0] - self._last_mouse_pos[0])
                    dy = abs(new_pos[1] - self._last_mouse_pos[1])
                    
                    if dx > 10 or dy > 10:  # Increased threshold
                        self._last_mouse_pos = new_pos
                        self._mark_active()
                except:
                    pass
            
            elif wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                self._mark_active()
        
        return result
    
    def _keyboard_hook_proc(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: wintypes.LPARAM
    ) -> int:
        """
        Low-level keyboard hook callback.
        
        Called for every keyboard event system-wide.
        MUST return quickly to avoid system lag.
        """
        # Always call next hook FIRST to prevent system lag
        user32 = ctypes.windll.user32
        result = user32.CallNextHookEx(self._keyboard_hook, nCode, wParam, lParam)
        
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            with self._ignore_lock:
                if not self._ignore_activity:
                    self._mark_active()
        
        return result
    
    def _hook_thread_func(self) -> None:
        """
        Thread function that installs hooks and runs message pump.
        
        Windows hooks require a message loop to receive callbacks.
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        # Create callback wrappers that prevent garbage collection
        self._mouse_callback = HOOKPROC(self._mouse_hook_proc)
        self._keyboard_callback = HOOKPROC(self._keyboard_hook_proc)
        
        # Get module handle (use 0 for low-level hooks)
        # Low-level hooks don't need a module handle
        
        # Install mouse hook
        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._mouse_callback,
            0,  # Use 0 for low-level hooks
            0
        )
        
        if not self._mouse_hook:
            error_code = kernel32.GetLastError()
            logger.error(f"Failed to install mouse hook (error: {error_code})")
            # Continue anyway - keyboard hook might still work
        else:
            logger.info("Mouse hook installed successfully")
        
        # Install keyboard hook
        self._keyboard_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._keyboard_callback,
            0,  # Use 0 for low-level hooks
            0
        )
        
        if not self._keyboard_hook:
            error_code = kernel32.GetLastError()
            logger.error(f"Failed to install keyboard hook (error: {error_code})")
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            return
        else:
            logger.info("Keyboard hook installed successfully")
        
        logger.info("Input hooks installed - monitoring user activity")
        
        # Message pump - REQUIRED for hooks to work
        # Use longer sleep to reduce CPU usage
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            # PeekMessage with longer timeout to reduce CPU
            # PM_REMOVE = 0x0001
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)  # 50ms sleep - better CPU usage
        
        # Cleanup hooks
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = None
        
        logger.info("Input hooks removed")
    
    def _idle_check_thread_func(self) -> None:
        """
        Thread function that monitors idle state and notifies when user becomes idle.
        Also processes activity callbacks (moved out of hook thread for safety).
        """
        while not self._stop_event.is_set():
            # Check for pending activity notification
            if self._activity_pending:
                self._activity_pending = False
                # Call activity callback outside of hook thread
                if self._on_activity:
                    try:
                        self._on_activity(ActivityType.MOUSE_MOVE)  # Generic activity
                    except Exception as e:
                        logger.error(f"Error in on_activity callback: {e}")
            
            with self._state_lock:
                if self._state.last_activity_time > 0:
                    elapsed = time.time() - self._state.last_activity_time
                    self._state.idle_duration = elapsed
                    
                    # Check if user has become idle
                    if elapsed >= self.idle_timeout:
                        self._state.is_user_active = False
                        
                        # Notify only once when becoming idle
                        if not self._idle_notified:
                            self._idle_notified = True
                            if self._on_idle:
                                try:
                                    self._on_idle()
                                except Exception as e:
                                    logger.error(f"Error in on_idle callback: {e}")
            
            time.sleep(0.1)  # Check every 100ms for faster response
    
    def start(self) -> bool:
        """
        Start idle detection.
        
        Installs Windows hooks and begins monitoring user activity.
        
        Returns:
            True if started successfully
        """
        if self._is_running:
            logger.warning("IdleDetector is already running")
            return False
        
        # Initialize last activity time to now (assume user just started)
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
        
        # Clear stop event
        self._stop_event.clear()
        
        # Start hook thread
        self._hook_thread = threading.Thread(
            target=self._hook_thread_func,
            name="IdleDetector-Hooks",
            daemon=True
        )
        self._hook_thread.start()
        
        # Start idle check thread
        self._idle_check_thread = threading.Thread(
            target=self._idle_check_thread_func,
            name="IdleDetector-IdleCheck",
            daemon=True
        )
        self._idle_check_thread.start()
        
        self._is_running = True
        logger.info("IdleDetector started")
        return True
    
    def stop(self) -> None:
        """Stop idle detection and remove hooks."""
        if not self._is_running:
            return
        
        logger.info("Stopping IdleDetector...")
        
        # Signal threads to stop
        self._stop_event.set()
        
        # Wait for threads
        if self._hook_thread and self._hook_thread.is_alive():
            self._hook_thread.join(timeout=2.0)
        
        if self._idle_check_thread and self._idle_check_thread.is_alive():
            self._idle_check_thread.join(timeout=1.0)
        
        self._is_running = False
        logger.info("IdleDetector stopped")
    
    def reset(self) -> None:
        """Reset the idle timer (mark user as active now)."""
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
            self._state.idle_duration = 0.0
        self._idle_notified = False
    
    def suppress_activity(self) -> None:
        """Temporarily ignore activity detection (during simulated input)."""
        with self._ignore_lock:
            self._ignore_activity = True
    
    def restore_activity(self) -> None:
        """Restore activity detection after simulated input."""
        with self._ignore_lock:
            self._ignore_activity = False
    
    def is_suppressed(self) -> bool:
        """Check if activity detection is currently suppressed."""
        with self._ignore_lock:
            return self._ignore_activity


# Example usage
if __name__ == "__main__":
    def on_activity(activity_type: ActivityType):
        print(f"Activity detected: {activity_type.name}")
    
    def on_idle():
        print("User is now idle!")
    
    detector = IdleDetector(
        idle_timeout=10.0,  # 10 seconds for testing
        on_activity=on_activity,
        on_idle=on_idle
    )
    
    print("Starting idle detection (10 second timeout for testing)...")
    print("Move your mouse or press keys to see activity detection.")
    print("Press Ctrl+C to stop.")
    
    detector.start()
    
    try:
        while True:
            state = detector.state
            print(f"\rActive: {state.is_user_active}, "
                  f"Idle duration: {state.idle_duration:.1f}s, "
                  f"Until idle: {detector.seconds_until_idle:.1f}s    ", end="")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
        detector.stop()
    
    print("Done!")

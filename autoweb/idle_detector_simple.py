"""
Simple Idle Detector Module (Click & Keyboard Only)
===================================================

This module provides a SIMPLE, SAFE approach to detecting user activity.
It ONLY detects mouse CLICKS and keyboard presses - NOT mouse movement.

Uses low-level hooks but with MINIMAL processing to avoid system hang.
The key is to return from hook callbacks IMMEDIATELY.

Key Safety Features:
- CallNextHookEx called FIRST before any processing
- Activity flags set immediately with no callbacks in hook
- All heavy processing done in separate check thread
- No locks or blocking operations in hooks
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


# Windows API Constants
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

# Hook callback type
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM
)


class ActivityType(Enum):
    """Types of user activity detected."""
    MOUSE_CLICK = auto()
    KEYBOARD = auto()


@dataclass
class IdleState:
    """Current state of idle detection."""
    is_user_active: bool = False
    last_activity_time: float = 0.0
    idle_duration: float = 0.0
    activity_type: Optional[ActivityType] = None


class IdleDetector:
    """
    Safe idle detector - ONLY detects mouse clicks and keyboard presses.
    Mouse movement is completely IGNORED.
    
    Uses lightweight hooks that return IMMEDIATELY to prevent system hangs.
    """
    
    DEFAULT_IDLE_TIMEOUT = 30.0
    
    def __init__(
        self,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        on_activity: Optional[Callable[[ActivityType], None]] = None,
        on_idle: Optional[Callable[[], None]] = None
    ):
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
        self._check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        
        # Keep references to prevent GC
        self._mouse_callback = None
        self._keyboard_callback = None
        
        # Flags for cross-thread communication (volatile-like)
        self._activity_detected = False
        self._last_activity_type = None
        self._idle_notified = False
        
        # Ignore activity flag (during simulated input)
        self._ignore_activity = False
        self._ignore_lock = threading.Lock()
        
        logger.info(f"IdleDetector initialized with {idle_timeout}s timeout (clicks/keyboard ONLY)")
    
    @property
    def state(self) -> IdleState:
        """Get current idle state."""
        with self._state_lock:
            return IdleState(
                is_user_active=self._state.is_user_active,
                last_activity_time=self._state.last_activity_time,
                idle_duration=self._state.idle_duration,
                activity_type=self._state.activity_type
            )
    
    @property
    def is_user_active(self) -> bool:
        """Check if user is currently active."""
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
    
    def _mouse_hook_proc(self, nCode: int, wParam: wintypes.WPARAM, lParam: wintypes.LPARAM) -> int:
        """
        Mouse hook - ONLY clicks, returns IMMEDIATELY.
        NO locks, NO callbacks, NO heavy operations here!
        """
        user32 = ctypes.windll.user32
        # Call next hook FIRST - critical for system responsiveness
        result = user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)
        
        # Only flag clicks (NOT mouse movement)
        if nCode >= 0 and wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            self._activity_detected = True
            self._last_activity_type = ActivityType.MOUSE_CLICK
        
        return result
    
    def _keyboard_hook_proc(self, nCode: int, wParam: wintypes.WPARAM, lParam: wintypes.LPARAM) -> int:
        """
        Keyboard hook - key presses only, returns IMMEDIATELY.
        NO locks, NO callbacks, NO heavy operations here!
        """
        user32 = ctypes.windll.user32
        # Call next hook FIRST - critical for system responsiveness
        result = user32.CallNextHookEx(self._keyboard_hook, nCode, wParam, lParam)
        
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self._activity_detected = True
            self._last_activity_type = ActivityType.KEYBOARD
        
        return result
    
    def _hook_thread_func(self) -> None:
        """Install hooks and run message pump."""
        user32 = ctypes.windll.user32
        
        # Create callbacks
        self._mouse_callback = HOOKPROC(self._mouse_hook_proc)
        self._keyboard_callback = HOOKPROC(self._keyboard_hook_proc)
        
        # Install mouse hook (for clicks only)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_callback, 0, 0)
        if not self._mouse_hook:
            logger.error("Failed to install mouse hook")
        
        # Install keyboard hook
        self._keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._keyboard_callback, 0, 0)
        if not self._keyboard_hook:
            logger.error("Failed to install keyboard hook")
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            return
        
        logger.info("Input hooks installed (clicks + keyboard only)")
        
        # Message pump - MUST process messages for hooks to work
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            # Use PeekMessage with PM_REMOVE (0x0001) for non-blocking
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                # Small sleep to prevent CPU spinning
                time.sleep(0.01)  # 10ms
        
        # Cleanup
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = None
        
        logger.info("Input hooks removed")
    
    def _check_thread_func(self) -> None:
        """Process activity flags and manage idle state."""
        logger.info("Idle check thread started")
        
        while not self._stop_event.is_set():
            # Check for activity flag (set by hooks)
            if self._activity_detected:
                self._activity_detected = False
                
                # Check ignore flag
                with self._ignore_lock:
                    if self._ignore_activity:
                        continue
                
                activity_type = self._last_activity_type
                
                # Update state
                with self._state_lock:
                    self._state.last_activity_time = time.time()
                    self._state.is_user_active = True
                    self._state.idle_duration = 0.0
                    self._state.activity_type = activity_type
                
                self._idle_notified = False
                
                # Call activity callback (safe - we're in check thread)
                if activity_type and self._on_activity:
                    try:
                        logger.info(f"{activity_type.name} detected - PAUSING")
                        self._on_activity(activity_type)
                    except Exception as e:
                        logger.error(f"Error in on_activity callback: {e}")
            
            # Update idle duration and check for idle state
            with self._state_lock:
                if self._state.last_activity_time > 0:
                    elapsed = time.time() - self._state.last_activity_time
                    self._state.idle_duration = elapsed
                    
                    if elapsed >= self.idle_timeout:
                        self._state.is_user_active = False
                        
                        if not self._idle_notified:
                            self._idle_notified = True
                            if self._on_idle:
                                try:
                                    logger.info("User idle - RESUMING")
                                    self._on_idle()
                                except Exception as e:
                                    logger.error(f"Error in on_idle callback: {e}")
            
            time.sleep(0.05)  # Check every 50ms
        
        logger.info("Idle check thread stopped")
    
    def start(self) -> bool:
        """Start idle detection."""
        if self._is_running:
            logger.warning("IdleDetector is already running")
            return False
        
        # Reset state
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
        
        self._activity_detected = False
        self._idle_notified = False
        self._stop_event.clear()
        
        # Start hook thread
        self._hook_thread = threading.Thread(
            target=self._hook_thread_func,
            name="IdleDetector-Hooks",
            daemon=True
        )
        self._hook_thread.start()
        
        # Start check thread
        self._check_thread = threading.Thread(
            target=self._check_thread_func,
            name="IdleDetector-Check",
            daemon=True
        )
        self._check_thread.start()
        
        self._is_running = True
        logger.info("IdleDetector started (clicks/keyboard only - NO mouse movement)")
        return True
    
    def stop(self) -> None:
        """Stop idle detection and remove hooks."""
        if not self._is_running:
            return
        
        logger.info("Stopping IdleDetector...")
        self._stop_event.set()
        
        # Wait for threads with short timeouts
        if self._hook_thread and self._hook_thread.is_alive():
            self._hook_thread.join(timeout=1.0)
        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=1.0)
        
        self._is_running = False
        logger.info("IdleDetector stopped")
    
    def reset(self) -> None:
        """Reset the idle timer."""
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
            self._state.idle_duration = 0.0
        self._idle_notified = False
    
    def suppress_activity(self) -> None:
        """Temporarily ignore activity (during simulated input)."""
        with self._ignore_lock:
            self._ignore_activity = True
    
    def restore_activity(self) -> None:
        """Restore activity detection."""
        with self._ignore_lock:
            self._ignore_activity = False
    
    def is_suppressed(self) -> bool:
        """Check if activity detection is suppressed."""
        with self._ignore_lock:
            return self._ignore_activity


# Test code
if __name__ == "__main__":
    def on_activity(activity_type: ActivityType):
        print(f"\n*** Activity: {activity_type.name} ***")
    
    def on_idle():
        print("\n*** User IDLE ***")
    
    detector = IdleDetector(
        idle_timeout=5.0,
        on_activity=on_activity,
        on_idle=on_idle
    )
    
    print("Starting detector (5s timeout)")
    print("Click mouse or press keys to test (NOT mouse movement)")
    print("Press Ctrl+C to stop")
    
    detector.start()
    
    try:
        while True:
            state = detector.state
            print(f"\rActive: {state.is_user_active}, "
                  f"Idle: {state.idle_duration:.1f}s, "
                  f"Until idle: {detector.seconds_until_idle:.1f}s    ", end="")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
        detector.stop()
    
    print("Done!")

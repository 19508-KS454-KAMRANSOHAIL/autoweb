"""
Click & Keyboard Only Idle Detector
===================================

This module provides a more targeted idle detection that only responds to:
- Mouse button clicks (left, right, middle)
- Keyboard key presses

Mouse movement is IGNORED - only actual button/key presses pause automation.
This uses low-level hooks but with minimal processing to avoid system lag.
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

# Mouse messages (only button presses, ignore WM_MOUSEMOVE)
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207

# Keyboard messages
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
    is_user_active: bool = False      # True if user activity detected recently
    last_activity_time: float = 0.0   # Timestamp of last activity
    idle_duration: float = 0.0        # How long user has been idle
    activity_type: Optional[ActivityType] = None  # Last type of activity


class IdleDetector:
    """
    Detects ONLY mouse clicks and keyboard presses.
    Mouse movement is completely ignored.
    
    Uses lightweight hooks that return immediately to prevent system lag.
    """
    
    # Default idle timeout: 30 seconds
    DEFAULT_IDLE_TIMEOUT = 30.0
    
    def __init__(
        self,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        on_activity: Optional[Callable[[ActivityType], None]] = None,
        on_idle: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the IdleDetector.
        
        Args:
            idle_timeout: Seconds of inactivity before considered idle
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
        self._check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        
        # Keep references to callbacks to prevent garbage collection
        self._mouse_callback = None
        self._keyboard_callback = None
        
        # Track if we've notified about becoming idle
        self._idle_notified = False
        
        # Flag to temporarily ignore activity (during simulated input)
        self._ignore_activity = False
        self._ignore_lock = threading.Lock()
        
        # Flag for pending activity notification
        self._activity_pending = False
        
        logger.info(f"IdleDetector initialized with {idle_timeout}s timeout (clicks/keys only)")
    
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
    
    def _mark_activity(self, activity_type: ActivityType) -> None:
        """
        Mark user as active - called from hooks.
        Does NOT call callbacks (that's done in the check thread).
        """
        # Check if we should ignore this activity
        with self._ignore_lock:
            if self._ignore_activity:
                return
        
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
            self._state.activity_type = activity_type
            self._state.idle_duration = 0.0
        
        self._idle_notified = False
        self._activity_pending = True  # Flag for check thread to process
    
    def _mouse_hook_proc(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: wintypes.LPARAM
    ) -> int:
        """
        Mouse hook - ONLY detects button clicks, ignores movement.
        Returns immediately to avoid system lag.
        """
        # Always call next hook FIRST
        user32 = ctypes.windll.user32
        result = user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)
        
        # Only process button clicks (ignore mouse movement completely)
        if nCode >= 0 and wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            self._mark_activity(ActivityType.MOUSE_CLICK)
        
        return result
    
    def _keyboard_hook_proc(
        self,
        nCode: int,
        wParam: wintypes.WPARAM,
        lParam: wintypes.LPARAM
    ) -> int:
        """
        Keyboard hook - detects key presses.
        Returns immediately to avoid system lag.
        """
        # Always call next hook FIRST
        user32 = ctypes.windll.user32
        result = user32.CallNextHookEx(self._keyboard_hook, nCode, wParam, lParam)
        
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self._mark_activity(ActivityType.KEYBOARD)
        
        return result
    
    def _hook_thread_func(self) -> None:
        """
        Thread function that installs hooks and runs message pump.
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        # Create callback wrappers
        self._mouse_callback = HOOKPROC(self._mouse_hook_proc)
        self._keyboard_callback = HOOKPROC(self._keyboard_hook_proc)
        
        # Install mouse hook (only for clicks)
        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._mouse_callback,
            0,  # Use 0 for low-level hooks
            0
        )
        
        if not self._mouse_hook:
            logger.error("Failed to install mouse hook")
        else:
            logger.info("Mouse click hook installed")
        
        # Install keyboard hook
        self._keyboard_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._keyboard_callback,
            0,
            0
        )
        
        if not self._keyboard_hook:
            logger.error("Failed to install keyboard hook")
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            return
        else:
            logger.info("Keyboard hook installed")
        
        logger.info("Input hooks installed - monitoring clicks and keyboard only")
        
        # Message pump - required for hooks
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)  # 50ms sleep for better CPU usage
        
        # Cleanup hooks
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
        
        logger.info("Input hooks removed")
    
    def _check_thread_func(self) -> None:
        """
        Thread function that processes activity callbacks and monitors idle state.
        """
        logger.info("Idle check thread started")
        
        while not self._stop_event.is_set():
            # Check for pending activity notification
            if self._activity_pending:
                self._activity_pending = False
                activity_type = None
                
                with self._state_lock:
                    activity_type = self._state.activity_type
                
                # Call activity callback outside of hook thread for safety
                if activity_type and self._on_activity:
                    try:
                        logger.info(f"{activity_type.name} detected - PAUSING automation")
                        self._on_activity(activity_type)
                    except Exception as e:
                        logger.error(f"Error in on_activity callback: {e}")
            
            # Update idle duration and check for idle state
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
                                    logger.info("User idle - RESUMING automation")
                                    self._on_idle()
                                except Exception as e:
                                    logger.error(f"Error in on_idle callback: {e}")
            
            time.sleep(0.1)  # Check every 100ms
        
        logger.info("Idle check thread stopped")
    
    def start(self) -> bool:
        """
        Start idle detection.
        
        Returns:
            True if started successfully
        """
        if self._is_running:
            logger.warning("IdleDetector is already running")
            return False
        
        # Initialize state
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
        
        # Start check thread
        self._check_thread = threading.Thread(
            target=self._check_thread_func,
            name="IdleDetector-Check",
            daemon=True
        )
        self._check_thread.start()
        
        self._is_running = True
        logger.info("IdleDetector started (clicks/keys only)")
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
        
        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=1.0)
        
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
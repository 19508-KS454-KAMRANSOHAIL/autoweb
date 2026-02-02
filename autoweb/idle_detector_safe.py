"""
Safe Idle Detector - NO HOOKS (Polling Only)
============================================

This module detects ONLY mouse clicks and keyboard presses using POLLING.
NO HOOKS are used - this is 100% safe and will NEVER hang the system.

Detection method:
- Polls GetAsyncKeyState for mouse buttons and keyboard keys
- Only triggers on button/key PRESS (not release or hold)
- Mouse movement is completely IGNORED
"""

import ctypes
import threading
import time
import logging
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum, auto

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Virtual key codes for mouse buttons
VK_LBUTTON = 0x01   # Left mouse button
VK_RBUTTON = 0x02   # Right mouse button
VK_MBUTTON = 0x04   # Middle mouse button

# Common keyboard keys to monitor (covers most user activity)
KEYBOARD_KEYS = [
    # Letters A-Z (0x41-0x5A)
    *range(0x41, 0x5B),
    # Numbers 0-9 (0x30-0x39)
    *range(0x30, 0x3A),
    # Function keys F1-F12 (0x70-0x7B)
    *range(0x70, 0x7C),
    # Special keys
    0x08,  # Backspace
    0x09,  # Tab
    0x0D,  # Enter
    0x1B,  # Escape
    0x20,  # Space
    0x25,  # Left arrow
    0x26,  # Up arrow
    0x27,  # Right arrow
    0x28,  # Down arrow
    0x2E,  # Delete
    0x2D,  # Insert
    0x24,  # Home
    0x23,  # End
    0x21,  # Page Up
    0x22,  # Page Down
]


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
    Safe idle detector using POLLING only - NO HOOKS.
    
    Detects ONLY:
    - Mouse button clicks (left, right, middle)
    - Keyboard key presses
    
    Does NOT detect:
    - Mouse movement (completely ignored)
    
    This implementation is 100% safe and will NEVER hang the system.
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
        
        # Thread control
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        
        # Track previous key states to detect NEW presses only
        self._prev_mouse_state = {VK_LBUTTON: False, VK_RBUTTON: False, VK_MBUTTON: False}
        self._prev_key_states = {k: False for k in KEYBOARD_KEYS}
        
        # Idle notification flag
        self._idle_notified = False
        
        # Ignore activity flag (during simulated input)
        self._ignore_activity = False
        self._ignore_lock = threading.Lock()
        
        logger.info(f"IdleDetector initialized with {idle_timeout}s timeout (SAFE polling mode)")
    
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
    
    def _is_key_pressed(self, vk_code: int) -> bool:
        """Check if a key is currently pressed."""
        # GetAsyncKeyState returns negative if key is pressed
        state = ctypes.windll.user32.GetAsyncKeyState(vk_code)
        return (state & 0x8000) != 0
    
    def _check_mouse_clicks(self) -> bool:
        """Check for mouse button clicks. Returns True if click detected."""
        for vk in [VK_LBUTTON, VK_RBUTTON, VK_MBUTTON]:
            is_pressed = self._is_key_pressed(vk)
            was_pressed = self._prev_mouse_state[vk]
            
            # Detect NEW press (wasn't pressed before, is pressed now)
            if is_pressed and not was_pressed:
                self._prev_mouse_state[vk] = True
                return True
            
            self._prev_mouse_state[vk] = is_pressed
        
        return False
    
    def _check_keyboard(self) -> bool:
        """Check for keyboard key presses. Returns True if key press detected."""
        for vk in KEYBOARD_KEYS:
            is_pressed = self._is_key_pressed(vk)
            was_pressed = self._prev_key_states[vk]
            
            # Detect NEW press (wasn't pressed before, is pressed now)
            if is_pressed and not was_pressed:
                self._prev_key_states[vk] = True
                return True
            
            self._prev_key_states[vk] = is_pressed
        
        return False
    
    def _poll_thread_func(self) -> None:
        """Main polling thread - checks for clicks and keyboard presses."""
        logger.info("Polling thread started (NO HOOKS - safe mode)")
        
        while not self._stop_event.is_set():
            try:
                # Check if we should ignore activity
                with self._ignore_lock:
                    if self._ignore_activity:
                        time.sleep(0.05)
                        continue
                
                # Check for mouse clicks (NOT movement)
                mouse_clicked = self._check_mouse_clicks()
                
                # Check for keyboard presses
                key_pressed = self._check_keyboard()
                
                # If activity detected
                if mouse_clicked or key_pressed:
                    activity_type = ActivityType.MOUSE_CLICK if mouse_clicked else ActivityType.KEYBOARD
                    
                    # Update state
                    with self._state_lock:
                        self._state.last_activity_time = time.time()
                        self._state.is_user_active = True
                        self._state.idle_duration = 0.0
                        self._state.activity_type = activity_type
                    
                    self._idle_notified = False
                    
                    # Call activity callback
                    if self._on_activity:
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
                
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
            
            # Poll every 50ms - fast enough to catch clicks, light on CPU
            time.sleep(0.05)
        
        logger.info("Polling thread stopped")
    
    def start(self) -> bool:
        """Start idle detection."""
        if self._is_running:
            logger.warning("IdleDetector is already running")
            return False
        
        # Reset state
        with self._state_lock:
            self._state.last_activity_time = time.time()
            self._state.is_user_active = True
        
        self._idle_notified = False
        self._stop_event.clear()
        
        # Reset key states
        self._prev_mouse_state = {VK_LBUTTON: False, VK_RBUTTON: False, VK_MBUTTON: False}
        self._prev_key_states = {k: False for k in KEYBOARD_KEYS}
        
        # Start polling thread
        self._poll_thread = threading.Thread(
            target=self._poll_thread_func,
            name="IdleDetector-Poll",
            daemon=True
        )
        self._poll_thread.start()
        
        self._is_running = True
        logger.info("IdleDetector started (SAFE polling - NO HOOKS)")
        return True
    
    def stop(self) -> None:
        """Stop idle detection."""
        if not self._is_running:
            return
        
        logger.info("Stopping IdleDetector...")
        self._stop_event.set()
        
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        
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
    print("Click mouse or press keys to test")
    print("Mouse MOVEMENT is ignored!")
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

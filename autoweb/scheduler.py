"""
Scheduler Module
================

This module manages the automation cycle timing and execution logic.
It coordinates the active and idle phases of the automation process.

Automation Cycle:
-----------------
1. ACTIVE PHASE (5 minutes):
   - Random mouse movements
   - Periodic mouse clicks
   - Application/tab switching via keyboard shortcuts
   - Actions occur at randomized intervals

2. IDLE PHASE (2-4 minutes, random):
   - No automation activity
   - Simulates natural user breaks

3. Repeat continuously until stopped

Design Principles:
------------------
- Timer-based execution using threading
- Randomized intervals to avoid fixed patterns
- Observable state for UI updates
- Clean start/stop lifecycle
- Thread-safe operations
"""

import threading
import time
import random
import logging
from enum import Enum, auto
from typing import Callable, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from .window_manager import WindowManager
from .input_simulator import InputSimulator
from .idle_detector_safe import IdleDetector, ActivityType  # Use SAFE polling version (NO HOOKS)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AutomationPhase(Enum):
    """Current phase of the automation cycle."""
    STOPPED = auto()       # Automation not running
    ACTIVE = auto()        # Active phase - performing actions
    IDLE = auto()          # Idle phase - waiting (scheduler idle, not user idle)
    PAUSED = auto()        # Paused due to user activity
    WAITING_IDLE = auto()  # Waiting for user to become idle (120 seconds)


class ActionType(Enum):
    """Types of actions that can be performed during active phase."""
    MOUSE_MOVE = auto()
    MOUSE_CLICK = auto()  # Safe click - won't affect content
    APP_SWITCH = auto()
    TAB_SWITCH = auto()
    SCROLL = auto()       # Scroll action for VS Code and other apps


@dataclass
class SchedulerState:
    """
    Current state of the scheduler.
    
    This dataclass is used to communicate state to the UI.
    It provides a snapshot of the scheduler's current status.
    """
    phase: AutomationPhase = AutomationPhase.STOPPED
    time_remaining: int = 0       # Seconds remaining in current phase
    cycle_count: int = 0          # Number of completed cycles
    current_app: str = ""         # Name of currently active application
    last_action: str = ""         # Description of last action taken
    is_running: bool = False
    next_action_in: int = 0       # Seconds until next action
    total_runtime: int = 300      # Total runtime in seconds (default 5 min)
    runtime_remaining: int = 300  # Seconds remaining until auto-close
    idle_wait_remaining: int = 0  # Seconds until user considered idle (120s countdown)
    is_user_active: bool = False  # Whether user is currently active


@dataclass
class SchedulerConfig:
    """
    Configuration for the automation scheduler.
    
    Attributes:
        active_duration: Duration of active phase in seconds
        idle_min: Minimum idle phase duration in seconds
        idle_max: Maximum idle phase duration in seconds
        action_interval_min: Minimum seconds between actions (scroll, tab, mouse)
        action_interval_max: Maximum seconds between actions
        app_switch_interval: Seconds between app switches (separate from actions)
        click_probability: Probability of performing a click (0-1)
        click_phase_max: Maximum random delay before click (0 to this value)
        total_runtime: Total runtime before auto-close in seconds (default: 5 min)
        user_idle_timeout: Seconds of inactivity before resuming (default: 120s)
    """
    active_duration: int = 300      # 5 minutes
    idle_min: int = 120             # 2 minutes
    idle_max: int = 240             # 4 minutes
    action_interval_min: float = 3.0   # Actions every 3-8 seconds
    action_interval_max: float = 8.0
    app_switch_interval: float = 30.0  # Switch apps every 30 seconds by default
    click_probability: float = 0.10    # Reduced - safe clicks only
    tab_switch_probability: float = 0.20
    scroll_probability: float = 0.25   # Scrolling in VS Code and other apps
    click_phase_max: float = 10.0      # Random delay 0 to this value before clicks
    total_runtime: int = 300           # 5 minutes default
    user_idle_timeout: float = 30.0    # 30 seconds of inactivity before resuming


class AutomationScheduler:
    """
    Manages the automation cycle with active and idle phases.
    
    This class coordinates:
    - Timing of active and idle phases
    - Random action selection and execution
    - State updates for UI observers
    - Clean start/stop lifecycle
    - User activity detection and pause/resume
    - Runtime management with auto-close
    
    Thread Safety:
    The scheduler runs in a separate thread to avoid blocking the UI.
    State updates are protected by a lock to ensure consistency.
    """
    
    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        on_state_change: Optional[Callable[[SchedulerState], None]] = None,
        on_runtime_expired: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the automation scheduler.
        
        Args:
            config: Configuration object (uses defaults if None)
            on_state_change: Callback function called when state changes
            on_runtime_expired: Callback when total runtime is reached
        """
        self.config = config or SchedulerConfig()
        self._on_state_change = on_state_change
        self._on_runtime_expired = on_runtime_expired
        
        # Initialize modules
        self.window_manager = WindowManager()
        self.input_simulator = InputSimulator()
        
        # Initialize idle detector
        self.idle_detector = IdleDetector(
            idle_timeout=self.config.user_idle_timeout,
            on_activity=self._on_user_activity,
            on_idle=self._on_user_idle
        )
        
        # State management
        self._state = SchedulerState()
        self._state_lock = threading.Lock()
        
        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # Set when paused due to user activity
        self._resume_event = threading.Event()  # Set when ready to resume
        
        # Runtime tracking
        self._start_time: Optional[float] = None
        self._paused_time: float = 0.0  # Accumulated pause time
        self._pause_start: Optional[float] = None
        
        # Action weights for random selection (NO app switch - it's on separate timer)
        self._action_weights = {
            ActionType.MOUSE_MOVE: 0.30,       
            ActionType.MOUSE_CLICK: self.config.click_probability,  # Safe clicks
            ActionType.TAB_SWITCH: self.config.tab_switch_probability,  # Switch tabs
            ActionType.SCROLL: self.config.scroll_probability,  # Scrolling
        }
        
        # List of apps where scrolling is enabled
        self._scroll_apps = ["Visual Studio Code", "Code", "VS Code", "Chrome", 
                            "Firefox", "Edge", "Notepad", "Word", "Excel"]
        
        # Apps that support tabs (Ctrl+Tab)
        self._tab_apps = ["Chrome", "Firefox", "Edge", "Visual Studio Code", 
                         "Code", "VS Code", "Notepad++", "Brave"]
        
        # Round-robin tracking for apps
        self._app_cycle_index = 0
        self._known_windows = []  # Cache of windows for round-robin
        self._last_window_refresh = 0.0
        
        # Chrome window tracking
        self._chrome_windows = []
        self._chrome_window_index = 0
        
        # App switch timing (separate from action interval)
        self._last_app_switch_time = 0.0
        
        logger.info("AutomationScheduler initialized")
    
    @property
    def state(self) -> SchedulerState:
        """Get a copy of the current state (thread-safe)."""
        with self._state_lock:
            return SchedulerState(
                phase=self._state.phase,
                time_remaining=self._state.time_remaining,
                cycle_count=self._state.cycle_count,
                current_app=self._state.current_app,
                last_action=self._state.last_action,
                is_running=self._state.is_running,
                next_action_in=self._state.next_action_in,
                total_runtime=self._state.total_runtime,
                runtime_remaining=self._state.runtime_remaining,
                idle_wait_remaining=self._state.idle_wait_remaining,
                is_user_active=self._state.is_user_active
            )
    
    def _update_state(self, **kwargs) -> None:
        """
        Update state and notify observers (thread-safe).
        
        Args:
            **kwargs: State attributes to update
        """
        with self._state_lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
        
        # Notify UI of state change
        if self._on_state_change:
            self._on_state_change(self.state)
    
    def _on_user_activity(self, activity_type: ActivityType) -> None:
        """
        Callback when user activity is detected.
        
        Immediately pauses automation and switches to WAITING_IDLE state.
        
        Args:
            activity_type: Type of activity detected
        """
        if not self._state.is_running:
            return
        
        # Set pause flag
        self._pause_event.set()
        self._resume_event.clear()
        
        # Record pause start time
        if self._pause_start is None:
            self._pause_start = time.time()
        
        # Update state
        self._update_state(
            phase=AutomationPhase.WAITING_IDLE,
            is_user_active=True,
            idle_wait_remaining=int(self.config.user_idle_timeout),
            last_action=f"Paused - {activity_type.name} detected"
        )
        
        logger.info(f"User activity detected ({activity_type.name}) - automation paused")
    
    def _on_user_idle(self) -> None:
        """
        Callback when user becomes idle (after timeout).
        
        Resumes automation.
        """
        if not self._state.is_running:
            return
        
        # Calculate accumulated pause time
        if self._pause_start is not None:
            self._paused_time += time.time() - self._pause_start
            self._pause_start = None
        
        # IMPORTANT: Reset app switch timer on resume
        # This ensures full switch interval from now, not including pause time
        self._last_app_switch_time = time.time()
        
        # Clear pause, set resume
        self._pause_event.clear()
        self._resume_event.set()
        
        # Update state
        self._update_state(
            is_user_active=False,
            idle_wait_remaining=0,
            last_action="Resumed - user idle for 2 minutes"
        )
        
        logger.info("User idle - automation resumed")
    
    def _check_runtime_expired(self) -> bool:
        """
        Check if total runtime has expired.
        
        Returns:
            True if runtime has expired, False otherwise
        """
        if self._start_time is None:
            return False
        
        elapsed = time.time() - self._start_time - self._paused_time
        return elapsed >= self.config.total_runtime
    
    def _get_runtime_remaining(self) -> int:
        """Get seconds remaining in total runtime."""
        if self._start_time is None:
            return self.config.total_runtime
        
        elapsed = time.time() - self._start_time - self._paused_time
        remaining = self.config.total_runtime - elapsed
        return max(0, int(remaining))
    
    def _refresh_window_list(self) -> None:
        """Refresh the list of windows for round-robin cycling."""
        current_time = time.time()
        # Refresh every 5 seconds
        if current_time - self._last_window_refresh > 5.0:
            self._known_windows = self._get_visible_windows()
            self._last_window_refresh = current_time
            
            # Also refresh Chrome windows
            self._chrome_windows = [w for w in self._known_windows 
                                   if "Chrome" in w.title or "Google Chrome" in w.title]
            
            logger.debug(f"Refreshed window list: {len(self._known_windows)} windows, "
                        f"{len(self._chrome_windows)} Chrome windows")
    
    def _get_next_app_round_robin(self) -> Optional[WindowInfo]:
        """
        Get the next app in round-robin order.
        
        Cycles through all visible apps so each gets equal time.
        
        Returns:
            Next WindowInfo to switch to, or None if no windows
        """
        self._refresh_window_list()
        
        if not self._known_windows:
            return None
        
        # Get current window to avoid switching to same one
        current = self.window_manager.get_foreground_window()
        current_hwnd = current.hwnd if current else 0
        
        # Find next different window
        attempts = 0
        while attempts < len(self._known_windows):
            self._app_cycle_index = (self._app_cycle_index + 1) % len(self._known_windows)
            next_window = self._known_windows[self._app_cycle_index]
            
            # Make sure it's different and not minimized
            if (next_window.hwnd != current_hwnd and 
                not self.window_manager.is_window_minimized(next_window.hwnd)):
                return next_window
            
            attempts += 1
        
        return None
    
    def _switch_chrome_window(self) -> Optional[str]:
        """
        Switch to next Chrome window in round-robin order.
        
        Returns:
            Description of action taken, or None if failed
        """
        self._refresh_window_list()
        
        if len(self._chrome_windows) < 2:
            return None
        
        # Get current Chrome window
        current = self.window_manager.get_foreground_window()
        current_hwnd = current.hwnd if current else 0
        
        # Find next Chrome window
        for i in range(len(self._chrome_windows)):
            self._chrome_window_index = (self._chrome_window_index + 1) % len(self._chrome_windows)
            next_chrome = self._chrome_windows[self._chrome_window_index]
            
            if (next_chrome.hwnd != current_hwnd and
                not self.window_manager.is_window_minimized(next_chrome.hwnd)):
                if self.window_manager.switch_to_window(next_chrome.hwnd):
                    return f"Switched Chrome window: {next_chrome.title[:30]}..."
        
        return None
    
    def _switch_tab_in_app(self, app_name: str) -> str:
        """
        Switch tab using Ctrl+Tab in the current app.
        
        Args:
            app_name: Name of current app for logging
        
        Returns:
            Description of action
        """
        self.input_simulator.shortcut_ctrl_tab()
        return f"Switched tab in {app_name[:25]}..."
    
    def _is_chrome(self, title: str) -> bool:
        """Check if window is Chrome."""
        return "Chrome" in title or "Google Chrome" in title
    
    def _is_vscode(self, title: str) -> bool:
        """Check if window is VS Code."""
        return any(x in title for x in ["Visual Studio Code", "Code", "VS Code"])
    
    def _get_visible_windows(self):
        """
        Get only visible (non-minimized) windows.
        
        Returns:
            List of visible WindowInfo objects
        """
        return self.window_manager.get_visible_windows()
    
    def _wait_for_resume_or_stop(self, timeout: float = 0.5) -> bool:
        """
        Wait for resume signal or stop event.
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            True if should continue, False if should stop
        """
        if self._stop_event.is_set():
            return False
        
        if self._pause_event.is_set():
            # Update idle wait countdown
            idle_remaining = int(self.idle_detector.seconds_until_idle)
            self._update_state(
                idle_wait_remaining=idle_remaining,
                runtime_remaining=self._get_runtime_remaining(),
                phase=AutomationPhase.WAITING_IDLE
            )
            
            # Wait for resume or stop - with proper sleep
            while self._pause_event.is_set() and not self._stop_event.is_set():
                if self._check_runtime_expired():
                    return False
                
                idle_remaining = int(self.idle_detector.seconds_until_idle)
                self._update_state(
                    idle_wait_remaining=idle_remaining,
                    runtime_remaining=self._get_runtime_remaining()
                )
                time.sleep(0.5)  # Sleep to avoid tight loop
        
        return not self._stop_event.is_set()
    
    def _select_random_action(self) -> ActionType:
        """
        Select a random action based on configured probabilities.
        
        Uses weighted random selection to choose actions with
        different frequencies.
        
        Returns:
            Selected ActionType
        """
        actions = list(self._action_weights.keys())
        weights = list(self._action_weights.values())
        return random.choices(actions, weights=weights, k=1)[0]
    
    def _execute_action(self, action: ActionType) -> str:
        """
        Execute a single automation action.
        
        Args:
            action: The type of action to execute
        
        Returns:
            Description of the action taken
        """
        # Check if paused before executing
        if self._pause_event.is_set():
            return "Skipped - user active"
        
        # Suppress idle detector during simulated input
        self.idle_detector.suppress_activity()
        
        try:
            # Get current window info for context-aware actions
            current_window = self.window_manager.get_foreground_window()
            current_app = current_window.title if current_window else ""
            is_code_editor = any(app in current_app for app in ["Visual Studio Code", "Code", "VS Code"])
            supports_tabs = any(app in current_app for app in self._tab_apps)
            
            if action == ActionType.MOUSE_MOVE:
                x, y = self.input_simulator.move_mouse_random()
                return f"Mouse moved to ({x}, {y})"
            
            elif action == ActionType.MOUSE_CLICK:
                # SAFE CLICK: Only click on safe areas (title bar, edges)
                # This prevents accidental clicks on code or content
                # Random delay before click (0 to click_phase_max)
                click_delay = random.uniform(0, self.config.click_phase_max)
                if click_delay > 0:
                    # Wait with interruptible sleep
                    for _ in range(int(click_delay)):
                        if self._stop_event.is_set() or self._pause_event.is_set():
                            return "Click cancelled - user active"
                        time.sleep(1)
                    # Sleep remaining fraction
                    remaining = click_delay - int(click_delay)
                    if remaining > 0 and not self._stop_event.is_set() and not self._pause_event.is_set():
                        time.sleep(remaining)
                
                if self._stop_event.is_set() or self._pause_event.is_set():
                    return "Click cancelled - user active"
                
                x, y = self.input_simulator.safe_click()
                return f"Safe click at ({x}, {y}) after {click_delay:.1f}s delay"
            
            elif action == ActionType.TAB_SWITCH:
                # Handle tab switching for Chrome and VS Code
                # NOTE: Only switch TABS within the SAME app, never switch apps/windows
                is_chrome = self._is_chrome(current_app)
                is_vscode = self._is_vscode(current_app)
                
                if is_chrome:
                    # Switch Chrome tabs ONLY (not windows)
                    return self._switch_tab_in_app("Chrome")
                
                elif is_vscode:
                    # Switch VS Code tabs
                    return self._switch_tab_in_app("VS Code")
                
                elif supports_tabs:
                    # Other apps that support tabs
                    return self._switch_tab_in_app(current_app[:20])
                
                else:
                    # No tabs - just do a scroll or mouse move instead
                    if any(app in current_app for app in self._scroll_apps):
                        scroll_desc = self.input_simulator.scroll_sequence()
                        return f"Scrolled {scroll_desc} in {current_app[:20]}..."
                    else:
                        x, y = self.input_simulator.move_mouse_random()
                        return f"Mouse moved to ({x}, {y})"
            
            elif action == ActionType.SCROLL:
                # Scroll in the current application (both up and down)
                is_scrollable = any(app in current_app for app in self._scroll_apps)
                if is_scrollable:
                    # Use scroll sequence for natural up/down scrolling
                    scroll_desc = self.input_simulator.scroll_sequence()
                    return f"Scrolled {scroll_desc} in {current_app[:20]}..."
                else:
                    # Fall back to mouse move if not a scrollable app
                    x, y = self.input_simulator.move_mouse_random()
                    return f"Mouse moved to ({x}, {y})"
            
            return "Unknown action"
            
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return f"Error: {str(e)}"
        finally:
            # Always restore activity detection
            self.idle_detector.restore_activity()
    
    def _execute_app_switch(self) -> str:
        """
        Execute app switch action (on separate timer from other actions).
        
        Returns:
            Description of the action taken
        """
        if self._pause_event.is_set():
            return "App switch skipped - user active"
        
        self.idle_detector.suppress_activity()
        
        try:
            logger.debug("Starting app switch...")
            current_window = self.window_manager.get_foreground_window()
            current_app = current_window.title if current_window else ""
            logger.debug(f"Current app: {current_app[:30]}")
            
            # ROUND-ROBIN: Cycle through all apps so each gets a turn
            # Try multiple times in case some windows are invalid
            max_attempts = 5
            for attempt in range(max_attempts):
                next_app = self._get_next_app_round_robin()
                
                if not next_app:
                    logger.debug("No next app found")
                    return "No other visible windows"
                
                logger.debug(f"Attempt {attempt+1}: Trying to switch to {next_app.title[:30]}")
                
                # Check if it's a Chrome window - maybe switch to different Chrome window
                if self._is_chrome(current_app) and len(self._chrome_windows) > 1:
                    # 50% chance to switch Chrome windows instead of apps
                    if random.random() < 0.5:
                        result = self._switch_chrome_window()
                        if result:
                            time.sleep(0.3)
                            window = self.window_manager.get_foreground_window()
                            if window:
                                self._update_state(current_app=window.title)
                            return result
                
                # Switch to next app in round-robin
                if self.window_manager.switch_to_window(next_app.hwnd):
                    time.sleep(0.3)
                    window = self.window_manager.get_foreground_window()
                    app_name = window.title if window else next_app.title
                    self._update_state(current_app=app_name)
                    
                    # Log which app we switched to
                    app_num = self._app_cycle_index + 1
                    total_apps = len(self._known_windows)
                    return f"🔄 APP SWITCH ({int(self.config.app_switch_interval)}s): App {app_num}/{total_apps}: {app_name[:25]}..."
                else:
                    logger.debug(f"Failed to switch to {next_app.title[:30]}, trying next...")
                    # Force refresh window list for next attempt
                    self._last_window_refresh = 0
            
            return "Could not switch - all windows failed"
            
        except Exception as e:
            logger.error(f"Error in app switch: {e}")
            return f"Error: {str(e)}"
        finally:
            self.idle_detector.restore_activity()
    
    def _active_phase(self) -> None:
        """
        Execute the active phase of the automation cycle.
        
        During active phase:
        - Performs random actions at random intervals
        - Updates countdown timer
        - Continues for configured duration
        - Can be interrupted by stop event or user activity
        """
        duration = self.config.active_duration
        start_time = time.time()
        
        logger.info(f"Starting active phase for {duration} seconds")
        self._update_state(
            phase=AutomationPhase.ACTIVE,
            time_remaining=duration
        )
        
        # Update current app at start
        window = self.window_manager.get_foreground_window()
        if window:
            self._update_state(current_app=window.title)
        
        while not self._stop_event.is_set():
            # Check runtime
            if self._check_runtime_expired():
                return
            
            # Check for user activity and wait if needed
            if not self._wait_for_resume_or_stop():
                return
            
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            
            if remaining <= 0:
                break
            
            self._update_state(
                time_remaining=remaining,
                runtime_remaining=self._get_runtime_remaining(),
                phase=AutomationPhase.ACTIVE
            )
            
            # Calculate next action interval
            interval = random.uniform(
                self.config.action_interval_min,
                self.config.action_interval_max
            )
            
            # Wait with countdown updates
            action_start = time.time()
            while not self._stop_event.is_set() and not self._pause_event.is_set():
                wait_elapsed = time.time() - action_start
                if wait_elapsed >= interval:
                    break
                
                # Check runtime
                if self._check_runtime_expired():
                    return
                    
                # Update next action timer
                next_action_in = int(interval - wait_elapsed)
                self._update_state(
                    next_action_in=next_action_in,
                    runtime_remaining=self._get_runtime_remaining()
                )
                time.sleep(0.1)
            
            # Check if paused during wait
            if self._pause_event.is_set():
                if not self._wait_for_resume_or_stop():
                    return
                # After resume, recalculate phase timing
                continue
            
            if self._stop_event.is_set():
                return
            
            # Check if it's time to switch apps (separate timer)
            time_since_app_switch = time.time() - self._last_app_switch_time
            should_switch_app = time_since_app_switch >= self.config.app_switch_interval
            time_until_switch = int(self.config.app_switch_interval - time_since_app_switch)
            
            # Execute action (only if not paused)
            if not self._pause_event.is_set():
                if should_switch_app:
                    # Time to switch apps!
                    logger.info(f"APP SWITCH TRIGGERED: {time_since_app_switch:.1f}s elapsed (interval: {self.config.app_switch_interval}s)")
                    self._update_state(next_action_in=0)
                    action_desc = self._execute_app_switch()
                    self._last_app_switch_time = time.time()
                    self._update_state(last_action=action_desc)
                    logger.info(f"Action: {action_desc}")
                else:
                    # Regular action (scroll, tab switch, mouse move, click)
                    action = self._select_random_action()
                    self._update_state(next_action_in=0)
                    action_desc = self._execute_action(action)
                    self._update_state(last_action=action_desc)
                    logger.info(f"Action: {action_desc}")
            
            # Update phase time remaining
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            self._update_state(
                time_remaining=remaining,
                runtime_remaining=self._get_runtime_remaining()
            )
        
        logger.info("Active phase completed")
    
    def _idle_phase(self) -> None:
        """
        Execute the idle phase of the automation cycle.
        
        During idle phase:
        - No automation actions are performed
        - Random duration between configured min/max
        - Updates countdown timer
        - Simulates natural user breaks
        """
        # Skip idle phase if both min and max are 0
        if self.config.idle_min == 0 and self.config.idle_max == 0:
            logger.info("Skipping idle phase (duration set to 0)")
            return
        
        duration = random.randint(
            max(1, self.config.idle_min),
            max(1, self.config.idle_max)
        )
        
        logger.info(f"Starting idle phase for {duration} seconds")
        self._update_state(
            phase=AutomationPhase.IDLE,
            time_remaining=duration,
            last_action="Idle - no actions"
        )
        
        start_time = time.time()
        
        while not self._stop_event.is_set():
            # Check runtime
            if self._check_runtime_expired():
                return
            
            # Check for user activity
            if not self._wait_for_resume_or_stop():
                return
            
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            
            if remaining <= 0:
                break
            
            self._update_state(
                time_remaining=remaining,
                runtime_remaining=self._get_runtime_remaining(),
                phase=AutomationPhase.IDLE
            )
            
            # Sleep in small increments for responsive stopping
            time.sleep(0.5)
        
        logger.info("Idle phase completed")
    
    def _automation_loop(self) -> None:
        """
        Main automation loop that runs in a separate thread.
        
        Continuously alternates between active and idle phases
        until the stop event is set or runtime expires.
        """
        logger.info("Automation loop started")
        cycle_count = 0
        
        try:
            while not self._stop_event.is_set():
                # Check runtime at start of each cycle
                if self._check_runtime_expired():
                    logger.info("Runtime expired - stopping automation")
                    break
                
                # Increment cycle count
                cycle_count += 1
                self._update_state(cycle_count=cycle_count)
                
                logger.info(f"=== Starting cycle {cycle_count} ===")
                
                # Active phase
                self._active_phase()
                
                if self._stop_event.is_set() or self._check_runtime_expired():
                    break
                
                # Idle phase
                self._idle_phase()
                
        except Exception as e:
            logger.error(f"Error in automation loop: {e}")
        finally:
            # Check if runtime expired
            runtime_expired = self._check_runtime_expired()
            
            self._update_state(
                phase=AutomationPhase.STOPPED,
                is_running=False,
                time_remaining=0,
                last_action="Stopped" if not runtime_expired else "Runtime expired"
            )
            
            # Stop idle detector
            self.idle_detector.stop()
            
            # Notify if runtime expired
            if runtime_expired and self._on_runtime_expired:
                self._on_runtime_expired()
            
            logger.info("Automation loop ended")
    
    def start(self) -> bool:
        """
        Start the automation scheduler.
        
        Creates a new thread to run the automation loop.
        
        Returns:
            True if started successfully, False if already running
        """
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler is already running")
            return False
        
        # Update idle detector timeout
        self.idle_detector.idle_timeout = self.config.user_idle_timeout
        
        # Clear events
        self._stop_event.clear()
        self._pause_event.clear()
        self._resume_event.set()
        
        # Reset timing
        self._start_time = time.time()
        self._paused_time = 0.0
        self._pause_start = None
        self._last_app_switch_time = time.time()  # Initialize app switch timer
        
        # Update state
        self._update_state(
            is_running=True,
            cycle_count=0,
            last_action="Starting...",
            total_runtime=self.config.total_runtime,
            runtime_remaining=self.config.total_runtime,
            is_user_active=False,
            idle_wait_remaining=0
        )
        
        # Start idle detector
        self.idle_detector.start()
        
        # Start automation thread
        self._thread = threading.Thread(
            target=self._automation_loop,
            name="AutomationThread",
            daemon=True
        )
        self._thread.start()
        
        logger.info("Scheduler started")
        return True
    
    def stop(self) -> bool:
        """
        Stop the automation scheduler.
        
        Sets the stop event and waits for the thread to finish.
        
        Returns:
            True if stopped successfully
        """
        if not self._thread or not self._thread.is_alive():
            logger.warning("Scheduler is not running")
            # Still stop idle detector
            self.idle_detector.stop()
            return False
        
        logger.info("Stopping scheduler...")
        
        # Signal stop
        self._stop_event.set()
        self._pause_event.clear()
        self._resume_event.set()
        
        # Stop idle detector
        self.idle_detector.stop()
        
        # Wait for thread to finish (with timeout)
        self._thread.join(timeout=2.0)
        
        if self._thread.is_alive():
            logger.warning("Thread did not stop gracefully")
        
        self._update_state(
            phase=AutomationPhase.STOPPED,
            is_running=False,
            time_remaining=0,
            last_action="Stopped"
        )
        
        logger.info("Scheduler stopped")
        return True
    
    def is_running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._thread is not None and self._thread.is_alive()


# Example usage and testing
if __name__ == "__main__":
    def state_callback(state: SchedulerState):
        print(f"Phase: {state.phase.name}, "
              f"Time: {state.time_remaining}s, "
              f"Cycle: {state.cycle_count}, "
              f"Action: {state.last_action}")
    
    # Create scheduler with shorter durations for testing
    config = SchedulerConfig(
        active_duration=30,  # 30 seconds for testing
        idle_min=10,
        idle_max=15,
        action_interval_min=2.0,
        action_interval_max=5.0
    )
    
    scheduler = AutomationScheduler(
        config=config,
        on_state_change=state_callback
    )
    
    print("Starting automation (Ctrl+C to stop)...")
    scheduler.start()
    
    try:
        while scheduler.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        scheduler.stop()
    
    print("Done!")

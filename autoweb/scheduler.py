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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AutomationPhase(Enum):
    """Current phase of the automation cycle."""
    STOPPED = auto()    # Automation not running
    ACTIVE = auto()     # Active phase - performing actions
    IDLE = auto()       # Idle phase - waiting


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
    time_remaining: int = 0  # Seconds remaining in current phase
    cycle_count: int = 0     # Number of completed cycles
    current_app: str = ""    # Name of currently active application
    last_action: str = ""    # Description of last action taken
    is_running: bool = False
    next_action_in: int = 0  # Seconds until next action


@dataclass
class SchedulerConfig:
    """
    Configuration for the automation scheduler.
    
    Attributes:
        active_duration: Duration of active phase in seconds
        idle_min: Minimum idle phase duration in seconds
        idle_max: Maximum idle phase duration in seconds
        action_interval_min: Minimum seconds between actions
        action_interval_max: Maximum seconds between actions
        click_probability: Probability of performing a click (0-1)
        app_switch_probability: Probability of switching apps (0-1)
    """
    active_duration: int = 300      # 5 minutes
    idle_min: int = 120             # 2 minutes
    idle_max: int = 240             # 4 minutes
    action_interval_min: float = 3.0
    action_interval_max: float = 10.0
    click_probability: float = 0.10  # Reduced - safe clicks only
    app_switch_probability: float = 0.35  # Increased for better app switching
    tab_switch_probability: float = 0.15
    scroll_probability: float = 0.20  # Scrolling in VS Code and other apps


class AutomationScheduler:
    """
    Manages the automation cycle with active and idle phases.
    
    This class coordinates:
    - Timing of active and idle phases
    - Random action selection and execution
    - State updates for UI observers
    - Clean start/stop lifecycle
    
    Thread Safety:
    The scheduler runs in a separate thread to avoid blocking the UI.
    State updates are protected by a lock to ensure consistency.
    """
    
    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        on_state_change: Optional[Callable[[SchedulerState], None]] = None
    ):
        """
        Initialize the automation scheduler.
        
        Args:
            config: Configuration object (uses defaults if None)
            on_state_change: Callback function called when state changes
        """
        self.config = config or SchedulerConfig()
        self._on_state_change = on_state_change
        
        # Initialize modules
        self.window_manager = WindowManager()
        self.input_simulator = InputSimulator()
        
        # State management
        self._state = SchedulerState()
        self._state_lock = threading.Lock()
        
        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        
        # Action weights for random selection
        self._action_weights = {
            ActionType.MOUSE_MOVE: 0.4,      # Common action
            ActionType.MOUSE_CLICK: self.config.click_probability,  # Safe clicks
            ActionType.APP_SWITCH: self.config.app_switch_probability,
            ActionType.TAB_SWITCH: self.config.tab_switch_probability,
            ActionType.SCROLL: self.config.scroll_probability,  # Scrolling
        }
        
        # List of apps where scrolling is enabled
        self._scroll_apps = ["Visual Studio Code", "Code", "VS Code", "Chrome", 
                            "Firefox", "Edge", "Notepad", "Word", "Excel"]
        
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
                next_action_in=self._state.next_action_in
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
        try:
            # Get current window info for context-aware actions
            current_window = self.window_manager.get_foreground_window()
            current_app = current_window.title if current_window else ""
            is_code_editor = any(app in current_app for app in ["Visual Studio Code", "Code", "VS Code"])
            
            if action == ActionType.MOUSE_MOVE:
                x, y = self.input_simulator.move_mouse_random()
                return f"Mouse moved to ({x}, {y})"
            
            elif action == ActionType.MOUSE_CLICK:
                # SAFE CLICK: Only click on safe areas (title bar, edges)
                # This prevents accidental clicks on code or content
                x, y = self.input_simulator.safe_click()
                return f"Safe click at ({x}, {y}) - edges only"
            
            elif action == ActionType.APP_SWITCH:
                # Use direct window switching instead of Alt+Tab for reliability
                windows = self.window_manager.get_all_windows()
                if len(windows) > 1:
                    # Find a different window to switch to
                    import random
                    other_windows = [w for w in windows if w.hwnd != (current_window.hwnd if current_window else 0)]
                    if other_windows:
                        target = random.choice(other_windows)
                        self.window_manager.switch_to_window(target.hwnd)
                        time.sleep(0.3)
                        # Update current app
                        window = self.window_manager.get_foreground_window()
                        app_name = window.title if window else target.title
                        self._update_state(current_app=app_name)
                        return f"Switched to: {app_name[:30]}..."
                
                # Fallback to Alt+Tab
                self.input_simulator.shortcut_alt_tab()
                time.sleep(0.3)
                window = self.window_manager.get_foreground_window()
                app_name = window.title if window else "Unknown"
                self._update_state(current_app=app_name)
                return f"Alt+Tab to: {app_name[:30]}..."
            
            elif action == ActionType.TAB_SWITCH:
                self.input_simulator.shortcut_ctrl_tab()
                return "Switched tab (Ctrl+Tab)"
            
            elif action == ActionType.SCROLL:
                # Scroll in the current application
                is_scrollable = any(app in current_app for app in self._scroll_apps)
                if is_scrollable:
                    direction = self.input_simulator.scroll_random()
                    return f"Scrolled {direction} in {current_app[:20]}..."
                else:
                    # Fall back to mouse move if not a scrollable app
                    x, y = self.input_simulator.move_mouse_random()
                    return f"Mouse moved to ({x}, {y})"
            
            return "Unknown action"
            
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return f"Error: {str(e)}"
    
    def _active_phase(self) -> None:
        """
        Execute the active phase of the automation cycle.
        
        During active phase:
        - Performs random actions at random intervals
        - Updates countdown timer
        - Continues for configured duration
        - Can be interrupted by stop event
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
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            
            if remaining <= 0:
                break
            
            self._update_state(time_remaining=remaining)
            
            # Calculate next action interval
            interval = random.uniform(
                self.config.action_interval_min,
                self.config.action_interval_max
            )
            
            # Update next action countdown
            action_start = time.time()
            
            # Wait with countdown updates
            while not self._stop_event.is_set():
                wait_elapsed = time.time() - action_start
                if wait_elapsed >= interval:
                    break
                    
                # Update next action timer
                next_action_in = int(interval - wait_elapsed)
                self._update_state(next_action_in=next_action_in)
                time.sleep(0.1)
            
            if self._stop_event.is_set():
                return
            
            # Select and execute random action
            action = self._select_random_action()
            self._update_state(next_action_in=0)  # Action happening now
            action_desc = self._execute_action(action)
            self._update_state(last_action=action_desc)
            
            # Update phase time remaining
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            self._update_state(time_remaining=remaining)
            
            logger.info(f"Action: {action_desc}")
        
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
        duration = random.randint(
            self.config.idle_min,
            self.config.idle_max
        )
        
        logger.info(f"Starting idle phase for {duration} seconds")
        self._update_state(
            phase=AutomationPhase.IDLE,
            time_remaining=duration,
            last_action="Idle - no actions"
        )
        
        start_time = time.time()
        
        while not self._stop_event.is_set():
            elapsed = time.time() - start_time
            remaining = int(duration - elapsed)
            
            if remaining <= 0:
                break
            
            self._update_state(time_remaining=remaining)
            
            # Sleep in small increments for responsive stopping
            time.sleep(0.5)
        
        logger.info("Idle phase completed")
    
    def _automation_loop(self) -> None:
        """
        Main automation loop that runs in a separate thread.
        
        Continuously alternates between active and idle phases
        until the stop event is set.
        """
        logger.info("Automation loop started")
        cycle_count = 0
        
        try:
            while not self._stop_event.is_set():
                # Increment cycle count
                cycle_count += 1
                self._update_state(cycle_count=cycle_count)
                
                logger.info(f"=== Starting cycle {cycle_count} ===")
                
                # Active phase
                self._active_phase()
                
                if self._stop_event.is_set():
                    break
                
                # Idle phase
                self._idle_phase()
                
        except Exception as e:
            logger.error(f"Error in automation loop: {e}")
        finally:
            self._update_state(
                phase=AutomationPhase.STOPPED,
                is_running=False,
                time_remaining=0,
                last_action="Stopped"
            )
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
        
        # Clear stop event
        self._stop_event.clear()
        
        # Update state
        self._update_state(
            is_running=True,
            cycle_count=0,
            last_action="Starting..."
        )
        
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
            return False
        
        logger.info("Stopping scheduler...")
        
        # Signal stop
        self._stop_event.set()
        
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

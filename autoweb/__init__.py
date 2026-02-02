# AutoWeb - Windows Desktop Automation Tool
# For UI Automation and Accessibility Testing Purposes Only
# 
# This package contains modules for:
# - Window management (detecting and switching windows)
# - Input simulation (mouse and keyboard)
# - Scheduling automation cycles
# - Idle detection (clicks/keyboard ONLY - NO mouse movement)

__version__ = "1.2.0"
__author__ = "AutoWeb Team"

from .idle_detector_safe import IdleDetector, ActivityType, IdleState  # SAFE polling (NO HOOKS)
from .window_manager import WindowManager, WindowInfo
from .input_simulator import InputSimulator
from .scheduler import AutomationScheduler, SchedulerState, SchedulerConfig, AutomationPhase
from .ui import AutoWebApp

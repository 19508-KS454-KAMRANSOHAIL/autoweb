"""
Main UI Module
==============

This module provides the graphical user interface for the AutoWeb
automation tool using tkinter.

UI Components:
--------------
- Warning dialog (shown on startup)
- Start/Stop buttons
- Status display (Active/Idle mode)
- Countdown timer
- Current active application display
- Cycle count
- Activity log

Design Principles:
------------------
- Simple and intuitive interface
- Clear visibility of automation state
- Requires user consent before starting
- No background auto-start
- Clean shutdown on window close
- Window becomes transparent after consent
- Win+F12 hotkey to stop automation
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional
import logging
import sys
import ctypes
from ctypes import wintypes
import threading
import subprocess
from datetime import datetime

from .scheduler import AutomationScheduler, SchedulerState, AutomationPhase
from .global_hotkey import GlobalHotkey, MOD_CTRL, MOD_SHIFT, VK_MAP
from .force_logout import ForceLogoutHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Windows API for Hotkeys and Transparency
# ============================================================================

# Windows transparency
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

# Windows display affinity (screen capture blocking)
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _apply_capture_protection(tk_window: tk.Misc, label: str = "window") -> None:
    """Attempt to block screen capture for the given window."""
    try:
        hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id())
        result = ctypes.windll.user32.SetWindowDisplayAffinity(
            hwnd, WDA_EXCLUDEFROMCAPTURE
        )
        if result == 0:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
            logger.warning(
                f"WDA_EXCLUDEFROMCAPTURE not supported for {label}, fell back to WDA_MONITOR"
            )
        else:
            logger.info(f"Screen capture blocking enabled for {label}")
    except Exception as e:
        logger.error(f"Failed to set screen capture protection for {label}: {e}")

# Hotkey registration - Using Ctrl+Shift+Q (easier to press)
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
VK_Q = 0x51  # Q key

# Hotkey: Ctrl+Shift+Q


# ============================================================================
# Color Scheme and Styling
# ============================================================================

class Colors:
    """Application color scheme."""
    BACKGROUND = "#1e1e2e"      # Dark background
    SURFACE = "#2a2a3c"         # Card background
    PRIMARY = "#89b4fa"         # Blue accent
    SUCCESS = "#a6e3a1"         # Green for active
    WARNING = "#fab387"         # Orange for idle
    ERROR = "#f38ba8"           # Red for stopped
    TEXT = "#cdd6f4"            # Light text
    TEXT_DIM = "#6c7086"        # Dimmed text


class Fonts:
    """Application fonts."""
    TITLE = ("Segoe UI", 16, "bold")
    HEADING = ("Segoe UI", 12, "bold")
    BODY = ("Segoe UI", 10)
    MONO = ("Consolas", 10)
    TIMER = ("Segoe UI", 32, "bold")
    STATUS = ("Segoe UI", 14, "bold")


# ============================================================================
# Warning Dialog
# ============================================================================

class ConsentDialog:
    """
    Confirmation dialog that shows user settings before starting.
    NO shortcut info shown here - just settings confirmation.
    """
    
    def __init__(self, parent: tk.Tk, settings: dict, privacy_mode: bool = False):
        """
        Initialize the confirmation dialog.
        
        Args:
            parent: Parent window
            settings: Dictionary with active_min, active_max, idle_min, idle_max, app_switch, total_runtime
        """
        self.parent = parent
        self.settings = settings
        self.confirmed = False
        self.privacy_mode = privacy_mode
    
    def show(self) -> bool:
        """
        Show the confirmation dialog.
        
        Returns:
            True if user confirmed, False otherwise
        """
        dialog = tk.Toplevel(self.parent)
        dialog.title("Confirm Settings")
        dialog.geometry("450x480")  # Much taller dialog to accommodate all content
        dialog.configure(bg=Colors.BACKGROUND)
        dialog.transient(self.parent)
        dialog.grab_set()
        _apply_capture_protection(dialog, "consent dialog")
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 480) // 2
        dialog.geometry(f"450x480+{x}+{y}")
        
        # Title
        title_label = tk.Label(
            dialog,
            text="✓ Confirm Your Settings",
            font=Fonts.TITLE,
            bg=Colors.BACKGROUND,
            fg=Colors.PRIMARY
        )
        title_label.pack(pady=(20, 15))
        
        # Settings display
        settings_frame = tk.Frame(dialog, bg=Colors.SURFACE, padx=20, pady=15)
        settings_frame.pack(fill=tk.X, padx=20, pady=10)
        
        if self.privacy_mode:
            settings_text = """
\u23f1 Active Duration: Hidden
\u23f8 Pause Duration: Hidden
\ud83d\udd04 App Switch: Hidden
\ud83d\uddb1 Auto-Click: Hidden
\u23f1 Total Runtime: Hidden
\ud83d\udd01 Repeat Screens: Hidden
\ud83d\udd11 Shortcut: Hidden
\u26a0 Force Logout: Hidden
\ud83d\udeba Simple Logout: Hidden

The app will PAUSE on mouse clicks or keyboard presses.
Mouse movement is ignored.
Resumes after 30 seconds of inactivity.
"""
        else:
            settings_text = f"""
\u23f1 Active Duration: {self.settings['active_min']}-{self.settings['active_max']}
\u23f8 Pause Duration: {self.settings['idle_min']}-{self.settings['idle_max']}
\ud83d\udd04 App Switch: {self.settings['app_switch']}
\ud83d\uddb1 Auto-Click: {self.settings.get('auto_click', 'Default')}
\u23f1 Total Runtime: {self.settings['total_runtime']}
\ud83d\udd01 Repeat Screens: {self.settings['repeat_screens']}
\ud83d\udd11 Shortcut: {self.settings.get('shortcut', 'Ctrl+Shift+P')}
\u26a0 Force Logout: {self.settings.get('force_logout', 'OFF')}
\ud83d\udeba Simple Logout: {self.settings.get('simple_logout', 'OFF')}

The app will PAUSE on mouse clicks or keyboard presses.
Mouse movement is ignored.
Resumes after 30 seconds of inactivity.
"""
        
        settings_label = tk.Label(
            settings_frame,
            text=settings_text,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            justify=tk.LEFT
        )
        settings_label.pack()
        
        # Buttons - at bottom with enough space
        button_frame = tk.Frame(dialog, bg=Colors.BACKGROUND)
        button_frame.pack(side=tk.BOTTOM, pady=30)  # Pack at bottom
        
        def on_confirm():
            self.confirmed = True
            dialog.destroy()
        
        def on_cancel():
            self.confirmed = False
            dialog.destroy()
        
        confirm_btn = tk.Button(
            button_frame,
            text="START NOW",
            command=on_confirm,
            font=("Segoe UI", 14, "bold"),
            bg=Colors.SUCCESS,
            fg=Colors.BACKGROUND,
            activebackground="#8bc78f",
            padx=40,
            pady=15,
            cursor="hand2",
            relief=tk.RAISED,
            bd=3
        )
        confirm_btn.pack(side=tk.LEFT, padx=15)
        
        cancel_btn = tk.Button(
            button_frame,
            text="✗ Back",
            command=on_cancel,
            font=Fonts.BODY,
            bg=Colors.ERROR,
            fg=Colors.BACKGROUND,
            activebackground="#d97a8f",
            padx=20,
            pady=8,
            cursor="hand2"
        )
        cancel_btn.pack(side=tk.LEFT, padx=10)
        
        # Wait for dialog to close
        self.parent.wait_window(dialog)
        
        return self.confirmed


# ============================================================================
# Main Application Window
# ============================================================================

class AutoWebApp:
    """
    Main application window for AutoWeb automation tool.
    
    Provides a graphical interface for:
    - Starting and stopping automation
    - Monitoring automation status
    - Viewing activity logs
    - Transparent window after consent
    - Win+F12 hotkey to stop automation
    """
    
    # Hotkey ID for Win+F12
    HOTKEY_ID = 1
    DEFAULT_ACTIVE_MIN_SEC = 300
    DEFAULT_ACTIVE_MAX_SEC = 600
    DEFAULT_IDLE_MIN_SEC = 120
    DEFAULT_IDLE_MAX_SEC = 240
    DEFAULT_RUNTIME_SEC = 54000        # 900 minutes
    DEFAULT_APP_SWITCH_SEC = 540       # 9 minutes
    DEFAULT_AUTO_CLICK_MIN_SEC = 60    # 1 minute
    DEFAULT_AUTO_CLICK_MAX_SEC = 240   # 4 minutes (STRICT MAX)
    
    def __init__(self):
        """Initialize the main application window."""
        # Create main window
        self.root = tk.Tk()
        self.root.title("AutoWeb - UI Automation Tool")
        self.root.geometry("600x950")
        self.root.configure(bg=Colors.BACKGROUND)
        self.root.resizable(True, True)
        self.root.minsize(550, 800)
        
        # Keep window always on top
        self.root.attributes('-topmost', True)
        
        # Set window icon (if available)
        try:
            self.root.iconbitmap(default="")
        except:
            pass
        
        # Initialize scheduler with callbacks
        self.scheduler = AutomationScheduler(
            on_state_change=self._on_state_change,
            on_runtime_expired=self._on_runtime_expired,
            on_user_activity_detected=self._on_user_activity_external
        )
        
        # Force logout handler
        self.force_logout_handler = ForceLogoutHandler(
            on_before_logout=self._before_force_logout
        )
        
        # Global pause/resume hotkey (Ctrl+Shift+P)
        self._pause_resume_hotkey = None
        
        # Track consent
        self.consent_given = False
        
        # Hotkey thread control
        self._hotkey_thread = None
        self._hotkey_stop_event = threading.Event()
        
        # Privacy shield (redacts on-screen data)
        self.privacy_mode = tk.BooleanVar(value=True)

        # Force OS logout on user activity
        self.force_logout_var = tk.BooleanVar(value=False)
        
        # Simple logout (app only, not OS)
        self.simple_logout_var = tk.BooleanVar(value=False)

        # Build UI
        self._create_widgets()
        self._apply_privacy_mode()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 600) // 2
        y = (self.root.winfo_screenheight() - 950) // 2
        self.root.geometry(f"600x950+{x}+{y}")

        # Block screen capture for this window (Windows 10+)
        self._set_window_capture_protection()
        
        logger.info("AutoWebApp initialized")

    def _set_privacy_log_placeholder(self) -> None:
        """Show a placeholder in the log when privacy mode is enabled."""
        placeholder = "Privacy Shield enabled. Logs hidden.\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.insert(tk.END, placeholder)
        self.log_text.configure(state=tk.DISABLED)

    def _apply_privacy_mode(self) -> None:
        """Apply redaction settings across the UI."""
        enabled = self.privacy_mode.get()

        # Keep inputs visible even when privacy mode is enabled
        self.active_min_entry.configure(show="")
        self.active_max_entry.configure(show="")
        self.idle_min_entry.configure(show="")
        self.idle_max_entry.configure(show="")
        self.app_switch_entry.configure(show="")
        self.total_runtime_entry.configure(show="")
        self.auto_click_min_entry.configure(show="")
        self.auto_click_max_entry.configure(show="")
        self.shortcut_entry.configure(show="")

        if enabled:
            self.status_label.configure(text="🔒 HIDDEN", fg=Colors.TEXT_DIM)
            self.timer_label.configure(text="--:--", fg=Colors.TEXT_DIM)
            self.runtime_remaining_label.configure(text="--:--", fg=Colors.TEXT_DIM)
            self.next_action_label.configure(text="--", fg=Colors.TEXT_DIM)
            self.cycle_label.configure(text="--", fg=Colors.TEXT_DIM)
            self.app_label.configure(text="Hidden", fg=Colors.TEXT_DIM)
            self.idle_wait_label.configure(text="")
            self._set_privacy_log_placeholder()
        else:
            self._on_state_change(self.scheduler.state)

    def _on_privacy_toggle(self) -> None:
        """Handle privacy shield toggle."""
        self._apply_privacy_mode()
    
    def _set_window_transparency(self, alpha: int = 200):
        """
        Set window transparency level.
        
        Args:
            alpha: Transparency value (0=invisible, 255=opaque)
        """
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            # Get current extended style
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # Add layered window style
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            # Set transparency
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
            logger.info(f"Window transparency set to {alpha}")
        except Exception as e:
            logger.error(f"Failed to set transparency: {e}")

    def _set_window_capture_protection(self):
        """Prevent this window from being captured by most screen capture tools."""
        _apply_capture_protection(self.root, "main window")
    
    def _register_hotkey(self):
        """Register Ctrl+Shift+Q global hotkey to stop automation."""
        def hotkey_listener():
            """Background thread to listen for Ctrl+Shift+Q hotkey."""
            user32 = ctypes.windll.user32
            
            # Register the hotkey (Ctrl+Shift+Q)
            if not user32.RegisterHotKey(None, self.HOTKEY_ID, MOD_CTRL | MOD_SHIFT, VK_Q):
                logger.error("Failed to register Ctrl+Shift+Q hotkey")
                return
            
            logger.info("Ctrl+Shift+Q hotkey registered")
            
            try:
                msg = wintypes.MSG()
                while not self._hotkey_stop_event.is_set():
                    # Check for hotkey message with timeout
                    if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                        if msg.message == 0x0312:  # WM_HOTKEY
                            if msg.wParam == self.HOTKEY_ID:
                                logger.info("Ctrl+Shift+Q hotkey pressed - stopping automation")
                                # Stop automation from main thread
                                self.root.after(0, self._on_hotkey_stop)
                    else:
                        # Sleep briefly to avoid high CPU usage
                        import time
                        time.sleep(0.1)
            finally:
                # Unregister the hotkey
                user32.UnregisterHotKey(None, self.HOTKEY_ID)
                logger.info("Ctrl+Shift+Q hotkey unregistered")
        
        # Start hotkey listener thread
        self._hotkey_stop_event.clear()
        self._hotkey_thread = threading.Thread(target=hotkey_listener, daemon=True)
        self._hotkey_thread.start()
    
    def _unregister_hotkey(self):
        """Stop the hotkey listener thread."""
        if self._hotkey_thread and self._hotkey_thread.is_alive():
            self._hotkey_stop_event.set()
            self._hotkey_thread.join(timeout=1.0)
    
    def _on_hotkey_stop(self):
        """Handle Ctrl+Shift+Q hotkey press - stop and close app."""
        self._log_message("🔑 Ctrl+Shift+Q pressed - stopping and closing")
        # Stop automation if running
        if self.scheduler.is_running():
            self.scheduler.stop()
        # Close the application
        self._on_close()
    
    def _register_pause_resume_hotkey(self):
        """Register the configurable pause/resume global hotkey."""
        shortcut_str = self.shortcut_var.get().strip()
        result = GlobalHotkey.parse_shortcut(shortcut_str)
        
        if result[0] is None:
            # Invalid shortcut, use default Ctrl+Shift+P
            self._log_message(f"⚠️ Invalid shortcut '{shortcut_str}', using Ctrl+Shift+P")
            modifiers = MOD_CTRL | MOD_SHIFT
            vk_code = VK_MAP['P']
        else:
            modifiers, vk_code = result
        
        # Create and start the global hotkey
        self._pause_resume_hotkey = GlobalHotkey(
            on_toggle=self._on_toggle_pause_resume,
            modifiers=modifiers,
            vk_code=vk_code,
            hotkey_id=GlobalHotkey.PAUSE_RESUME_ID
        )
        self._pause_resume_hotkey.start()
        self._log_message(f"🔑 Pause/Resume hotkey: {self._pause_resume_hotkey.shortcut_name}")
    
    def _on_toggle_pause_resume(self):
        """Handle global pause/resume hotkey press."""
        def do_toggle():
            if self.scheduler.is_running():
                is_now_paused = self.scheduler.toggle_pause()
                if is_now_paused:
                    self._log_message("⏸️ Automation PAUSED (hotkey)")
                    # Hide window when paused
                    self.root.withdraw()
                else:
                    self._log_message("▶️ Automation RESUMED (hotkey)")
                    # Also hide window when resumed
                    self.root.withdraw()
        
        # Schedule on main thread (tkinter thread safety)
        self.root.after(0, do_toggle)
    
    def _on_user_activity_external(self, activity_type):
        """Handle user activity detection (for logout options)."""
        if self.force_logout_handler and self.force_logout_handler.enabled:
            self.force_logout_handler.on_user_activity_detected()
        elif self.simple_logout_var.get():
            # Simple logout - close app and lock screen (Win+L)
            self._log_message("🚪 User activity detected - Simple logout: Closing app and locking screen")
            self.root.after(0, self._perform_simple_logout)
    
    def _before_force_logout(self):
        """Cleanup before OS force logout - stop all timers, remove hooks."""
        logger.warning("FORCE LOGOUT: Running pre-logout cleanup...")
        
        # Stop all timers and automation
        if self.scheduler.is_running():
            self.scheduler.stop()
        
        # Unregister all hotkeys
        self._unregister_hotkey()
        if self._pause_resume_hotkey:
            self._pause_resume_hotkey.stop()
        
        # Disable force logout to prevent recursion
        self.force_logout_handler.enabled = False
        
        logger.warning("FORCE LOGOUT: Cleanup complete, proceeding with OS logout")
    
    def _perform_simple_logout(self):
        """Perform simple logout - close app and lock Windows screen (Win+L)."""
        try:
            logger.warning("SIMPLE LOGOUT: Closing app and locking screen...")
            
            # First, close the application cleanly
            self._on_close()
            
            # Then lock the Windows screen (Win+L)
            # This keeps other apps running but locks the screen
            ctypes.windll.user32.LockWorkStation()
            
        except Exception as e:
            logger.error(f"Failed to perform simple logout: {e}")
            # If locking fails, still close the app
            import sys
            sys.exit(0)
    
    def _create_widgets(self) -> None:
        """Create all UI widgets."""
        # Main container
        main_frame = tk.Frame(self.root, bg=Colors.BACKGROUND)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Header
        self._create_header(main_frame)
        
        # Settings panel (timing configuration)
        self._create_settings_panel(main_frame)
        
        # BIG SUBMIT BUTTON - visible at the top
        self._create_submit_button(main_frame)
        
        # Shortcut info
        self._create_shortcut_info(main_frame)
        
        # Status section (for displaying state when running)
        self._create_status_card(main_frame)
        
        # Info cards (cycle count, current app)
        self._create_info_cards(main_frame)
        
        # Activity log (smaller)
        self._create_activity_log(main_frame)
    
    def _create_header(self, parent: tk.Frame) -> None:
        """Create the header section."""
        header_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        # App title
        title_label = tk.Label(
            header_frame,
            text="🤖 AutoWeb",
            font=Fonts.TITLE,
            bg=Colors.BACKGROUND,
            fg=Colors.PRIMARY
        )
        title_label.pack(anchor=tk.W)
        
        # Subtitle
        subtitle_label = tk.Label(
            header_frame,
            text="UI Automation & Accessibility Testing Tool",
            font=Fonts.BODY,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT_DIM
        )
        subtitle_label.pack(anchor=tk.W)

        privacy_frame = tk.Frame(header_frame, bg=Colors.BACKGROUND)
        privacy_frame.pack(anchor=tk.W, pady=(8, 0))

        privacy_toggle = tk.Checkbutton(
            privacy_frame,
            text="🔒 Privacy Shield (redact on-screen data)",
            variable=self.privacy_mode,
            command=self._on_privacy_toggle,
            font=Fonts.BODY,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT_DIM,
            activebackground=Colors.BACKGROUND,
            activeforeground=Colors.TEXT,
            selectcolor=Colors.SURFACE
        )
        privacy_toggle.pack(anchor=tk.W)
    
    def _create_submit_button(self, parent: tk.Frame) -> None:
        """Create the big SUBMIT button."""
        # Submit button frame
        submit_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        submit_frame.pack(fill=tk.X, pady=(10, 10))
        
        self.submit_btn = tk.Button(
            submit_frame,
            text="✓ SUBMIT",
            command=self._on_submit,
            font=("Segoe UI", 16, "bold"),
            bg=Colors.SUCCESS,
            fg=Colors.BACKGROUND,
            activebackground="#8bc78f",
            padx=50,
            pady=15,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.submit_btn.pack(fill=tk.X)
    
    def _create_shortcut_info(self, parent: tk.Frame) -> None:
        """Create shortcut information display."""
        shortcut_frame = tk.Frame(parent, bg=Colors.ERROR, padx=10, pady=8)
        shortcut_frame.pack(fill=tk.X, pady=(5, 10))
        
        shortcut_label = tk.Label(
            shortcut_frame,
            text="🔑 Ctrl+Shift+P = Pause/Resume  |  Ctrl+Shift+Q = Stop & Close",
            font=Fonts.HEADING,
            bg=Colors.ERROR,
            fg=Colors.BACKGROUND
        )
        shortcut_label.pack()
    
    def _create_settings_panel(self, parent: tk.Frame) -> None:
        """Create the settings panel for timing configuration."""
        # Settings frame
        settings_frame = tk.Frame(parent, bg=Colors.SURFACE, padx=15, pady=15)
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Settings title
        settings_title = tk.Label(
            settings_frame,
            text="⚙️ Timing Settings",
            font=Fonts.HEADING,
            bg=Colors.SURFACE,
            fg=Colors.TEXT
        )
        settings_title.pack(anchor=tk.W, pady=(0, 10))
        
        # First row: Active (clicking) duration range
        row1 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row1.pack(fill=tk.X, pady=(0, 10))
        
        active_min_frame = tk.Frame(row1, bg=Colors.SURFACE)
        active_min_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        active_min_label = tk.Label(
            active_min_frame,
            text="▶️ Active Min (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        active_min_label.pack(anchor=tk.W)
        
        self.active_min_var = tk.StringVar(value=self._format_time(self.DEFAULT_ACTIVE_MIN_SEC))
        self.active_min_entry = tk.Entry(
            active_min_frame,
            textvariable=self.active_min_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.active_min_entry.pack(anchor=tk.W, pady=(3, 0))
        
        active_min_note = tk.Label(
            active_min_frame,
            text="Minimum active time",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        active_min_note.pack(anchor=tk.W)
        
        active_max_frame = tk.Frame(row1, bg=Colors.SURFACE)
        active_max_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        active_max_label = tk.Label(
            active_max_frame,
            text="▶️ Active Max (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        active_max_label.pack(anchor=tk.W)
        
        self.active_max_var = tk.StringVar(value=self._format_time(self.DEFAULT_ACTIVE_MAX_SEC))
        self.active_max_entry = tk.Entry(
            active_max_frame,
            textvariable=self.active_max_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.active_max_entry.pack(anchor=tk.W, pady=(3, 0))
        
        active_max_note = tk.Label(
            active_max_frame,
            text="Maximum active time",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        active_max_note.pack(anchor=tk.W)
        
        # Second row: Pause duration range
        row2 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row2.pack(fill=tk.X, pady=(0, 10))
        
        idle_min_frame = tk.Frame(row2, bg=Colors.SURFACE)
        idle_min_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        idle_min_label = tk.Label(
            idle_min_frame,
            text="⏸️ Pause Min (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        idle_min_label.pack(anchor=tk.W)
        
        self.idle_min_var = tk.StringVar(value=self._format_time(self.DEFAULT_IDLE_MIN_SEC))
        self.idle_min_entry = tk.Entry(
            idle_min_frame,
            textvariable=self.idle_min_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.idle_min_entry.pack(anchor=tk.W, pady=(3, 0))
        
        idle_min_note = tk.Label(
            idle_min_frame,
            text="Minimum pause time",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        idle_min_note.pack(anchor=tk.W)
        
        idle_max_frame = tk.Frame(row2, bg=Colors.SURFACE)
        idle_max_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        idle_max_label = tk.Label(
            idle_max_frame,
            text="⏸️ Pause Max (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        idle_max_label.pack(anchor=tk.W)
        
        self.idle_max_var = tk.StringVar(value=self._format_time(self.DEFAULT_IDLE_MAX_SEC))
        self.idle_max_entry = tk.Entry(
            idle_max_frame,
            textvariable=self.idle_max_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.idle_max_entry.pack(anchor=tk.W, pady=(3, 0))
        
        idle_max_note = tk.Label(
            idle_max_frame,
            text="Maximum pause time",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        idle_max_note.pack(anchor=tk.W)
        
        # Third row: App switch interval and total runtime
        row3 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row3.pack(fill=tk.X, pady=(0, 10))
        
        app_switch_frame = tk.Frame(row3, bg=Colors.SURFACE)
        app_switch_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        app_switch_label = tk.Label(
            app_switch_frame,
            text="🔄 App Switch (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        app_switch_label.pack(anchor=tk.W)
        
        self.app_switch_var = tk.StringVar(value=self._format_time(self.DEFAULT_APP_SWITCH_SEC))
        self.app_switch_entry = tk.Entry(
            app_switch_frame,
            textvariable=self.app_switch_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.app_switch_entry.pack(anchor=tk.W, pady=(3, 0))
        
        app_switch_note = tk.Label(
            app_switch_frame,
            text="Time between screen changes",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        app_switch_note.pack(anchor=tk.W)
        
        runtime_frame = tk.Frame(row3, bg=Colors.SURFACE)
        runtime_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        runtime_label = tk.Label(
            runtime_frame,
            text="⏱️ Total Runtime (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        runtime_label.pack(anchor=tk.W)
        
        self.total_runtime_var = tk.StringVar(value=self._format_time(self.DEFAULT_RUNTIME_SEC))
        self.total_runtime_entry = tk.Entry(
            runtime_frame,
            textvariable=self.total_runtime_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.total_runtime_entry.pack(anchor=tk.W, pady=(3, 0))
        
        runtime_note = tk.Label(
            runtime_frame,
            text="App auto-closes when done",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        runtime_note.pack(anchor=tk.W)
        
        # Fourth row: Auto-click interval (Monitask safe)
        row4 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row4.pack(fill=tk.X, pady=(0, 10))
        
        auto_click_min_frame = tk.Frame(row4, bg=Colors.SURFACE)
        auto_click_min_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        auto_click_min_label = tk.Label(
            auto_click_min_frame,
            text="🖱️ Auto-Click Min (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        auto_click_min_label.pack(anchor=tk.W)
        
        self.auto_click_min_var = tk.StringVar(value=self._format_time(self.DEFAULT_AUTO_CLICK_MIN_SEC))
        self.auto_click_min_entry = tk.Entry(
            auto_click_min_frame,
            textvariable=self.auto_click_min_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.auto_click_min_entry.pack(anchor=tk.W, pady=(3, 0))
        
        auto_click_min_note = tk.Label(
            auto_click_min_frame,
            text="Min interval between auto-clicks",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        auto_click_min_note.pack(anchor=tk.W)
        
        auto_click_max_frame = tk.Frame(row4, bg=Colors.SURFACE)
        auto_click_max_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        auto_click_max_label = tk.Label(
            auto_click_max_frame,
            text="🖱️ Auto-Click Max (mm:ss):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        auto_click_max_label.pack(anchor=tk.W)
        
        self.auto_click_max_var = tk.StringVar(value=self._format_time(self.DEFAULT_AUTO_CLICK_MAX_SEC))
        self.auto_click_max_entry = tk.Entry(
            auto_click_max_frame,
            textvariable=self.auto_click_max_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.auto_click_max_entry.pack(anchor=tk.W, pady=(3, 0))
        
        auto_click_max_note = tk.Label(
            auto_click_max_frame,
            text="Max interval (STRICT: ≤ 4 min)",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        auto_click_max_note.pack(anchor=tk.W)
        
        # Fifth row: Global shortcut + Force logout
        row5 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row5.pack(fill=tk.X, pady=(0, 10))
        
        shortcut_config_frame = tk.Frame(row5, bg=Colors.SURFACE)
        shortcut_config_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        shortcut_config_label = tk.Label(
            shortcut_config_frame,
            text="🔑 Pause/Resume Shortcut:",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        shortcut_config_label.pack(anchor=tk.W)
        
        self.shortcut_var = tk.StringVar(value="Ctrl+Shift+P")
        self.shortcut_entry = tk.Entry(
            shortcut_config_frame,
            textvariable=self.shortcut_var,
            font=Fonts.BODY,
            width=16,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.shortcut_entry.pack(anchor=tk.W, pady=(3, 0))
        
        shortcut_config_note = tk.Label(
            shortcut_config_frame,
            text="Global hotkey (e.g. Ctrl+Shift+P)",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        shortcut_config_note.pack(anchor=tk.W)
        
        # Force logout checkbox
        force_logout_frame = tk.Frame(row5, bg=Colors.SURFACE)
        force_logout_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.force_logout_checkbox = tk.Checkbutton(
            force_logout_frame,
            text="⚠️ Force OS Logout\non User Activity",
            variable=self.force_logout_var,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.ERROR,
            activebackground=Colors.SURFACE,
            activeforeground=Colors.ERROR,
            selectcolor=Colors.SURFACE,
            justify=tk.LEFT
        )
        self.force_logout_checkbox.pack(anchor=tk.W, pady=(10, 0))
        
        force_logout_note = tk.Label(
            force_logout_frame,
            text="WARNING: Logs out Windows OS!",
            font=("Segoe UI", 8, "bold"),
            bg=Colors.SURFACE,
            fg=Colors.ERROR
        )
        force_logout_note.pack(anchor=tk.W)
        
        # Add sixth row for simple logout
        row6 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row6.pack(fill=tk.X, pady=(10, 0))
        
        # Simple logout checkbox (app-only close)
        simple_logout_frame = tk.Frame(row6, bg=Colors.SURFACE)
        simple_logout_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.simple_logout_checkbox = tk.Checkbutton(
            simple_logout_frame,
            text="🚪 Simple Logout\n(Logout Windows + Stop App)",
            variable=self.simple_logout_var,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.WARNING,
            activebackground=Colors.SURFACE,
            activeforeground=Colors.WARNING,
            selectcolor=Colors.SURFACE,
            justify=tk.LEFT
        )
        self.simple_logout_checkbox.pack(anchor=tk.W, pady=(10, 0))
        
        simple_logout_note = tk.Label(
            simple_logout_frame,
            text="Logs out Windows system and stops AutoWeb",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        simple_logout_note.pack(anchor=tk.W)
        
        # Reset defaults button
        reset_frame = tk.Frame(settings_frame, bg=Colors.SURFACE)
        reset_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.repeat_screens_var = tk.BooleanVar(value=True)
        self.repeat_checkbox = tk.Checkbutton(
            reset_frame,
            text="Repeat Screen View",
            variable=self.repeat_screens_var,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            activebackground=Colors.SURFACE,
            activeforeground=Colors.TEXT,
            selectcolor=Colors.SURFACE
        )
        self.repeat_checkbox.pack(side=tk.LEFT)

        reset_btn = tk.Button(
            reset_frame,
            text="Reset Defaults",
            command=self._reset_defaults,
            font=Fonts.BODY,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            relief=tk.FLAT,
            cursor="hand2"
        )
        reset_btn.pack(side=tk.RIGHT)
        
        # Tip label
        tip_label = tk.Label(
            settings_frame,
            text="💡 Use mm:ss. Active and pause ranges are randomized each cycle.",
            font=("Segoe UI", 9),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        tip_label.pack(anchor=tk.W, pady=(5, 0))

    def _create_status_card(self, parent: tk.Frame) -> None:
        """Create the main status display card."""
        # Status card frame
        status_card = tk.Frame(
            parent,
            bg=Colors.SURFACE,
            padx=30,
            pady=20
        )
        status_card.pack(fill=tk.X, pady=10)
        
        # Status label (Active/Idle/Stopped)
        self.status_label = tk.Label(
            status_card,
            text="⏹️ STOPPED",
            font=Fonts.STATUS,
            bg=Colors.SURFACE,
            fg=Colors.ERROR
        )
        self.status_label.pack()
        
        # Timer display
        self.timer_label = tk.Label(
            status_card,
            text="00:00",
            font=Fonts.TIMER,
            bg=Colors.SURFACE,
            fg=Colors.TEXT
        )
        self.timer_label.pack(pady=5)
        
        # Time remaining label
        time_desc_label = tk.Label(
            status_card,
            text="Phase Time Remaining",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        time_desc_label.pack()
        
        # Runtime remaining section
        runtime_frame = tk.Frame(status_card, bg=Colors.SURFACE)
        runtime_frame.pack(fill=tk.X, pady=(10, 0))
        
        runtime_title = tk.Label(
            runtime_frame,
            text="⏱️ Total Runtime:",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        runtime_title.pack(side=tk.LEFT)
        
        self.runtime_remaining_label = tk.Label(
            runtime_frame,
            text=self._format_time(self.DEFAULT_RUNTIME_SEC),
            font=("Segoe UI", 14, "bold"),
            bg=Colors.SURFACE,
            fg=Colors.PRIMARY
        )
        self.runtime_remaining_label.pack(side=tk.LEFT, padx=10)
        
        # Idle wait indicator (shows when paused due to user activity)
        self.idle_wait_frame = tk.Frame(status_card, bg=Colors.SURFACE)
        self.idle_wait_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.idle_wait_label = tk.Label(
            self.idle_wait_frame,
            text="",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.WARNING
        )
        self.idle_wait_label.pack()
        
        # Separator
        separator = tk.Frame(status_card, bg=Colors.TEXT_DIM, height=1)
        separator.pack(fill=tk.X, pady=15)
        
        # Next action timer section
        next_action_frame = tk.Frame(status_card, bg=Colors.SURFACE)
        next_action_frame.pack(fill=tk.X)
        
        next_action_title = tk.Label(
            next_action_frame,
            text="⏱️ Next Action In:",
            font=Fonts.HEADING,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        next_action_title.pack(side=tk.LEFT)
        
        self.next_action_label = tk.Label(
            next_action_frame,
            text="--",
            font=("Segoe UI", 16, "bold"),
            bg=Colors.SURFACE,
            fg=Colors.PRIMARY
        )
        self.next_action_label.pack(side=tk.LEFT, padx=10)
        
        self.next_action_seconds = tk.Label(
            next_action_frame,
            text="seconds",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        self.next_action_seconds.pack(side=tk.LEFT)
    
    def _create_info_cards(self, parent: tk.Frame) -> None:
        """Create the info cards row (cycle count, current app)."""
        info_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        info_frame.pack(fill=tk.X, pady=10)
        
        # Cycle count card
        cycle_card = tk.Frame(info_frame, bg=Colors.SURFACE, padx=20, pady=15)
        cycle_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        cycle_title = tk.Label(
            cycle_card,
            text="🔄 Cycles",
            font=Fonts.HEADING,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        cycle_title.pack(anchor=tk.W)
        
        self.cycle_label = tk.Label(
            cycle_card,
            text="0",
            font=("Segoe UI", 24, "bold"),
            bg=Colors.SURFACE,
            fg=Colors.TEXT
        )
        self.cycle_label.pack(anchor=tk.W)
        
        # Current app card
        app_card = tk.Frame(info_frame, bg=Colors.SURFACE, padx=20, pady=15)
        app_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        app_title = tk.Label(
            app_card,
            text="📱 Active Application",
            font=Fonts.HEADING,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        app_title.pack(anchor=tk.W)
        
        self.app_label = tk.Label(
            app_card,
            text="None",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            wraplength=200,
            justify=tk.LEFT
        )
        self.app_label.pack(anchor=tk.W)
    
    def _create_activity_log(self, parent: tk.Frame) -> None:
        """Create the activity log section."""
        log_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Log header
        log_header = tk.Frame(log_frame, bg=Colors.BACKGROUND)
        log_header.pack(fill=tk.X)
        
        log_title = tk.Label(
            log_header,
            text="📋 Activity Log",
            font=Fonts.HEADING,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT
        )
        log_title.pack(side=tk.LEFT)
        
        # Clear button
        clear_btn = tk.Button(
            log_header,
            text="Clear",
            command=self._clear_log,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            relief=tk.FLAT,
            cursor="hand2"
        )
        clear_btn.pack(side=tk.RIGHT)
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            font=Fonts.MONO,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT,
            height=10,
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    
    def _log_message(self, message: str) -> None:
        """
        Add a message to the activity log.
        
        Args:
            message: Message to log
        """
        if self.privacy_mode.get():
            self._set_privacy_log_placeholder()
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted)
        self.log_text.see(tk.END)  # Scroll to bottom
        self.log_text.configure(state=tk.DISABLED)
    
    def _clear_log(self) -> None:
        """Clear the activity log."""
        if self.privacy_mode.get():
            self._set_privacy_log_placeholder()
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def _format_time(self, seconds: int) -> str:
        """
        Format seconds as MM:SS.
        
        Args:
            seconds: Time in seconds
        
        Returns:
            Formatted time string
        """
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"
    
    def _on_state_change(self, state: SchedulerState) -> None:
        """
        Callback when scheduler state changes.
        
        Updates the UI to reflect the new state.
        This is called from the scheduler thread, so we use
        root.after() to safely update the UI.
        
        Args:
            state: New scheduler state
        """
        def update_ui():
            if self.privacy_mode.get():
                self._apply_privacy_mode()
                return
            # Update status label
            if state.phase == AutomationPhase.ACTIVE:
                self.status_label.configure(
                    text="▶️ ACTIVE",
                    fg=Colors.SUCCESS
                )
            elif state.phase == AutomationPhase.IDLE:
                self.status_label.configure(
                    text="💤 IDLE",
                    fg=Colors.WARNING
                )
            elif state.phase == AutomationPhase.WAITING_IDLE:
                self.status_label.configure(
                    text="⏸️ PAUSED",
                    fg=Colors.WARNING
                )
            elif state.phase == AutomationPhase.PAUSED:
                self.status_label.configure(
                    text="⏸️ PAUSED",
                    fg=Colors.WARNING
                )
            else:
                self.status_label.configure(
                    text="⏹️ STOPPED",
                    fg=Colors.ERROR
                )
            
            # Update timer
            self.timer_label.configure(
                text=self._format_time(state.time_remaining)
            )
            
            # Update runtime remaining
            self.runtime_remaining_label.configure(
                text=self._format_time(state.runtime_remaining)
            )
            
            # Update idle wait indicator
            if state.is_user_active and state.idle_wait_remaining > 0:
                self.idle_wait_label.configure(
                    text=f"⏳ User active - resuming in {state.idle_wait_remaining}s",
                    fg=Colors.WARNING
                )
            else:
                self.idle_wait_label.configure(text="")
            
            # Update next action timer
            if state.phase == AutomationPhase.ACTIVE:
                self.next_action_label.configure(
                    text=str(state.next_action_in),
                    fg=Colors.SUCCESS if state.next_action_in <= 2 else Colors.PRIMARY
                )
            elif state.phase == AutomationPhase.IDLE:
                self.next_action_label.configure(text="--", fg=Colors.TEXT_DIM)
            elif state.phase in (AutomationPhase.WAITING_IDLE, AutomationPhase.PAUSED):
                self.next_action_label.configure(text="⏸️", fg=Colors.WARNING)
            else:
                self.next_action_label.configure(text="--", fg=Colors.TEXT_DIM)
            
            # Update cycle count
            self.cycle_label.configure(text=str(state.cycle_count))
            
            # Update current app
            app_text = state.current_app[:40] + "..." if len(state.current_app) > 40 else state.current_app
            self.app_label.configure(text=app_text or "None")
            
            # Log last action (if changed)
            if state.last_action and state.last_action != "Starting...":
                self._log_message(state.last_action)
        
        # Schedule UI update on main thread
        self.root.after(0, update_ui)
    
    def _set_settings_enabled(self, enabled: bool) -> None:
        """Enable or disable settings inputs."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.active_min_entry.configure(state=state)
        self.active_max_entry.configure(state=state)
        self.idle_min_entry.configure(state=state)
        self.idle_max_entry.configure(state=state)
        self.app_switch_entry.configure(state=state)
        self.total_runtime_entry.configure(state=state)
        self.repeat_checkbox.configure(state=state)
        self.auto_click_min_entry.configure(state=state)
        self.auto_click_max_entry.configure(state=state)
        self.shortcut_entry.configure(state=state)
        self.force_logout_checkbox.configure(state=state)
        self.simple_logout_checkbox.configure(state=state)

    def _reset_defaults(self) -> None:
        """Reset timing inputs to default values."""
        self.active_min_var.set(self._format_time(self.DEFAULT_ACTIVE_MIN_SEC))
        self.active_max_var.set(self._format_time(self.DEFAULT_ACTIVE_MAX_SEC))
        self.idle_min_var.set(self._format_time(self.DEFAULT_IDLE_MIN_SEC))
        self.idle_max_var.set(self._format_time(self.DEFAULT_IDLE_MAX_SEC))
        self.app_switch_var.set(self._format_time(self.DEFAULT_APP_SWITCH_SEC))
        self.total_runtime_var.set(self._format_time(self.DEFAULT_RUNTIME_SEC))
        self.repeat_screens_var.set(True)
        self.auto_click_min_var.set(self._format_time(self.DEFAULT_AUTO_CLICK_MIN_SEC))
        self.auto_click_max_var.set(self._format_time(self.DEFAULT_AUTO_CLICK_MAX_SEC))
        self.shortcut_var.set("Ctrl+Shift+P")
        self.force_logout_var.set(False)
        self.simple_logout_var.set(False)
    
    def _on_stop(self) -> None:
        """Handle stop action."""
        if self.scheduler.stop():
            self._log_message("Automation stopped")
            self.submit_btn.configure(state=tk.NORMAL)
            self._set_settings_enabled(True)
            # Show the window again
            self.root.deiconify()
        else:
            self._log_message("Failed to stop automation")
    
    def _on_runtime_expired(self) -> None:
        """Handle runtime expiration - auto-close the application and perform Win+L logout."""
        def close_app():
            self._log_message("⏱️ Runtime expired - closing application and locking screen...")
            
            # Always perform Win+L logout when runtime expires
            self._log_message("🚪 Total runtime complete - performing system logout (Win+L)...")
            # Perform simple logout (close app and lock screen)
            self._perform_simple_logout()
        
        # Schedule on main thread
        self.root.after(0, close_app)
    
    def _on_close(self) -> None:
        """Handle window close event."""
        # Stop automation if running
        if self.scheduler.is_running():
            self.scheduler.stop()
        
        # Unregister hotkeys
        self._unregister_hotkey()
        
        # Stop pause/resume hotkey
        if self._pause_resume_hotkey:
            self._pause_resume_hotkey.stop()
            self._pause_resume_hotkey = None
        
        # Disable force logout
        self.force_logout_handler.enabled = False
        
        # Destroy window
        self.root.destroy()
    
    def run(self) -> None:
        """Start the application main loop."""
        self._log_message("🚀 AutoWeb ready")
        self._log_message("Configure settings and click SUBMIT")
        self._log_message("🔑 Ctrl+Shift+P = Pause/Resume | Ctrl+Shift+Q = Stop")
        self.root.mainloop()
    
    def _on_submit(self) -> None:
        """Handle SUBMIT button click - show confirmation dialog."""
        # Get settings from inputs
        def _parse_time_to_seconds(value: str, default_seconds: int, assume_minutes: bool = True) -> int:
            try:
                text = value.strip()
                if not text:
                    return default_seconds
                if ":" in text:
                    parts = text.split(":")
                    if len(parts) != 2:
                        return default_seconds
                    minutes = int(parts[0])
                    seconds = int(parts[1])
                    if minutes < 0 or seconds < 0:
                        return default_seconds
                    return (minutes * 60) + seconds
                number = float(text)
                if number <= 0:
                    return default_seconds
                if assume_minutes:
                    return int(round(number * 60))
                return int(round(number))
            except ValueError:
                return default_seconds
        
        active_min = _parse_time_to_seconds(
            self.active_min_var.get(),
            self.DEFAULT_ACTIVE_MIN_SEC,
            assume_minutes=True
        )
        active_max = _parse_time_to_seconds(
            self.active_max_var.get(),
            self.DEFAULT_ACTIVE_MAX_SEC,
            assume_minutes=True
        )
        idle_min = _parse_time_to_seconds(
            self.idle_min_var.get(),
            self.DEFAULT_IDLE_MIN_SEC,
            assume_minutes=True
        )
        idle_max = _parse_time_to_seconds(
            self.idle_max_var.get(),
            self.DEFAULT_IDLE_MAX_SEC,
            assume_minutes=True
        )
        app_switch = _parse_time_to_seconds(
            self.app_switch_var.get(),
            self.DEFAULT_APP_SWITCH_SEC,
            assume_minutes=False
        )
        total_runtime = _parse_time_to_seconds(
            self.total_runtime_var.get(),
            self.DEFAULT_RUNTIME_SEC,
            assume_minutes=True
        )

        if active_max < active_min:
            active_min, active_max = active_max, active_min
        if idle_max < idle_min:
            idle_min, idle_max = idle_max, idle_min
        
        active_min_display = self._format_time(active_min)
        active_max_display = self._format_time(active_max)
        idle_min_display = self._format_time(idle_min)
        idle_max_display = self._format_time(idle_max)
        app_switch_display = self._format_time(app_switch)
        total_runtime_display = self._format_time(total_runtime)
        
        # Create settings dict
        # Parse auto-click settings
        auto_click_min = _parse_time_to_seconds(
            self.auto_click_min_var.get(),
            self.DEFAULT_AUTO_CLICK_MIN_SEC,
            assume_minutes=True
        )
        auto_click_max = _parse_time_to_seconds(
            self.auto_click_max_var.get(),
            self.DEFAULT_AUTO_CLICK_MAX_SEC,
            assume_minutes=True
        )
        # Enforce strict 4-minute maximum (240 seconds)
        auto_click_max = min(auto_click_max, 240)
        auto_click_min = min(auto_click_min, auto_click_max)
        auto_click_min_display = self._format_time(auto_click_min)
        auto_click_max_display = self._format_time(auto_click_max)
        
        settings = {
            'active_min': active_min_display,
            'active_max': active_max_display,
            'idle_min': idle_min_display,
            'idle_max': idle_max_display,
            'app_switch': app_switch_display,
            'total_runtime': total_runtime_display,
            'repeat_screens': "Yes" if self.repeat_screens_var.get() else "No",
            'auto_click': f"{auto_click_min_display}-{auto_click_max_display}",
            'force_logout': "ON \u26a0\ufe0f" if self.force_logout_var.get() else "OFF",
            'simple_logout': "ON 🚪" if self.simple_logout_var.get() else "OFF",
            'shortcut': self.shortcut_var.get().strip()
        }
        
        # Show confirmation dialog (no shortcuts shown)
        dialog = ConsentDialog(self.root, settings, privacy_mode=self.privacy_mode.get())
        if not dialog.show():
            return  # User clicked Back
        
        # User confirmed - start automation
        self._log_message(
            "Settings: "
            f"Active {active_min_display}-{active_max_display}, "
            f"Pause {idle_min_display}-{idle_max_display}, "
            f"App Switch {app_switch_display}, "
            f"Auto-Click {auto_click_min_display}-{auto_click_max_display}, "
            f"Total {total_runtime_display}, "
            f"Repeat Screens {'Yes' if self.repeat_screens_var.get() else 'No'}"
        )
        
        # Register hotkey (Ctrl+Shift+Q to stop)
        self._register_hotkey()
        
        # Register pause/resume hotkey (configurable, default Ctrl+Shift+P)
        self._register_pause_resume_hotkey()
        
        # Set up force logout handler
        self.force_logout_handler.enabled = self.force_logout_var.get()
        
        # Apply settings to scheduler
        # Action interval is fast (3-8 seconds) for scroll, tab switch, mouse move
        self.scheduler.config.action_interval_min = 3.0
        self.scheduler.config.action_interval_max = 8.0
        
        self.scheduler.config.active_min = active_min
        self.scheduler.config.active_max = active_max
        self.scheduler.config.idle_min = idle_min
        self.scheduler.config.idle_max = idle_max
        self.scheduler.config.app_switch_interval = app_switch
        self.scheduler.config.total_runtime = total_runtime
        self.scheduler.config.repeat_screens = self.repeat_screens_var.get()
        self.scheduler.config.auto_click_min = auto_click_min
        self.scheduler.config.auto_click_max = auto_click_max
        
        # Disable submit button
        self.submit_btn.configure(state=tk.DISABLED)
        self._set_settings_enabled(False)
        
        # Start automation
        if self.scheduler.start():
            self._log_message("Automation started")
            self._log_message(
                f"Active {active_min_display}-{active_max_display}, "
                f"Pause {idle_min_display}-{idle_max_display}, "
                f"App Switch {app_switch_display}, "
                f"Auto-Click {auto_click_min_display}-{auto_click_max_display}, "
                f"Total {total_runtime_display}"
            )
            self._log_message("PAUSES on clicks/keyboard only")
            if self.force_logout_var.get():
                self._log_message("\u26a0\ufe0f FORCE LOGOUT ON USER ACTIVITY ENABLED")
            elif self.simple_logout_var.get():
                self._log_message("🚪 SIMPLE LOGOUT (Windows system) ON USER ACTIVITY ENABLED")
            
            # Make window INVISIBLE
            self.root.withdraw()  # Hide window completely
        else:
            self._log_message("Failed to start automation")
            self.submit_btn.configure(state=tk.NORMAL)
            self._set_settings_enabled(True)
    
# Entry point for testing
if __name__ == "__main__":
    app = AutoWebApp()
    app.run()

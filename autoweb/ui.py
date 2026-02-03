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
from datetime import datetime

from .scheduler import AutomationScheduler, SchedulerState, AutomationPhase, SchedulerConfig

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
    
    def __init__(self, parent: tk.Tk, settings: dict):
        """
        Initialize the confirmation dialog.
        
        Args:
            parent: Parent window
            settings: Dictionary with switch_interval, click_phase, runtime
        """
        self.parent = parent
        self.settings = settings
        self.confirmed = False
    
    def show(self) -> bool:
        """
        Show the confirmation dialog.
        
        Returns:
            True if user confirmed, False otherwise
        """
        dialog = tk.Toplevel(self.parent)
        dialog.title("Confirm Settings")
        dialog.geometry("450x400")  # Taller dialog
        dialog.configure(bg=Colors.BACKGROUND)
        dialog.transient(self.parent)
        dialog.grab_set()
        _apply_capture_protection(dialog, "consent dialog")
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 450) // 2
        y = (dialog.winfo_screenheight() - 400) // 2
        dialog.geometry(f"450x400+{x}+{y}")
        
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
        
        settings_text = f"""
🔄 Switch Interval: {self.settings['switch_interval']} seconds
🖱️ Click Delay Max: {self.settings['click_phase']} seconds
⏱️ Total Runtime: {self.settings['runtime']} minutes

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
    
    def __init__(self):
        """Initialize the main application window."""
        # Create main window
        self.root = tk.Tk()
        self.root.title("AutoWeb - UI Automation Tool")
        self.root.geometry("550x750")
        self.root.configure(bg=Colors.BACKGROUND)
        self.root.resizable(True, True)
        self.root.minsize(500, 650)
        
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
            on_runtime_expired=self._on_runtime_expired
        )
        
        # Track consent
        self.consent_given = False
        
        # Hotkey thread control
        self._hotkey_thread = None
        self._hotkey_stop_event = threading.Event()
        
        # Build UI
        self._create_widgets()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 550) // 2
        y = (self.root.winfo_screenheight() - 750) // 2
        self.root.geometry(f"550x750+{x}+{y}")

        # Block screen capture for this window (Windows 10+)
        self._set_window_capture_protection()
        
        logger.info("AutoWebApp initialized")
    
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
            text="🔑 Press Ctrl+Shift+Q to STOP & CLOSE anytime",
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
        
        # First row: Switch Interval and Total Runtime
        row1 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row1.pack(fill=tk.X, pady=(0, 10))
        
        # --- Screen Switch Interval Setting ---
        switch_frame = tk.Frame(row1, bg=Colors.SURFACE)
        switch_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        switch_label = tk.Label(
            switch_frame,
            text="🔄 Switch Interval (seconds):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        switch_label.pack(anchor=tk.W)
        
        self.switch_interval_var = tk.StringVar(value="5")  # Default: 5 seconds
        self.switch_interval_entry = tk.Entry(
            switch_frame,
            textvariable=self.switch_interval_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.switch_interval_entry.pack(anchor=tk.W, pady=(3, 0))
        
        switch_note = tk.Label(
            switch_frame,
            text="Time between screen switches",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        switch_note.pack(anchor=tk.W)
        
        # --- Click Phase Time Setting ---
        click_frame = tk.Frame(row1, bg=Colors.SURFACE)
        click_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        click_label = tk.Label(
            click_frame,
            text="🖱️ Click Phase (seconds):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        click_label.pack(anchor=tk.W)
        
        self.click_phase_var = tk.StringVar(value="10")  # Default: max 10 seconds
        self.click_phase_entry = tk.Entry(
            click_frame,
            textvariable=self.click_phase_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.click_phase_entry.pack(anchor=tk.W, pady=(3, 0))
        
        click_note = tk.Label(
            click_frame,
            text="Random delay before clicks",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        click_note.pack(anchor=tk.W)
        
        # Second row: Total Runtime
        row2 = tk.Frame(settings_frame, bg=Colors.SURFACE)
        row2.pack(fill=tk.X, pady=(0, 10))
        
        # --- Total Runtime Setting ---
        runtime_frame = tk.Frame(row2, bg=Colors.SURFACE)
        runtime_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        runtime_label = tk.Label(
            runtime_frame,
            text="⏱️ Total Runtime (minutes):",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        runtime_label.pack(anchor=tk.W)
        
        self.runtime_var = tk.StringVar(value="5")  # Default: 5 minutes
        self.runtime_entry = tk.Entry(
            runtime_frame,
            textvariable=self.runtime_var,
            font=Fonts.BODY,
            width=8,
            bg=Colors.BACKGROUND,
            fg=Colors.TEXT,
            insertbackground=Colors.TEXT,
            relief=tk.FLAT
        )
        self.runtime_entry.pack(anchor=tk.W, pady=(3, 0))
        
        runtime_note = tk.Label(
            runtime_frame,
            text="App auto-closes when done",
            font=("Segoe UI", 8),
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        runtime_note.pack(anchor=tk.W)
        
        # Second row: Active/Idle Phase Settings (hidden - use defaults)
        # Keep variables for backward compatibility
        self.interval_min_var = tk.StringVar(value="3")
        self.interval_max_var = tk.StringVar(value="10")
        self.active_duration_var = tk.StringVar(value="5")
        self.idle_min_var = tk.StringVar(value="2")
        self.idle_max_var = tk.StringVar(value="4")
        
        # Create hidden entries (not displayed but needed for _set_settings_enabled)
        self.interval_min_entry = tk.Entry(settings_frame)
        self.interval_max_entry = tk.Entry(settings_frame)
        self.active_duration_entry = tk.Entry(settings_frame)
        self.idle_min_entry = tk.Entry(settings_frame)
        self.idle_max_entry = tk.Entry(settings_frame)
        
        # Tip label
        tip_label = tk.Label(
            settings_frame,
            text="💡 Set your switch interval and runtime, then click Start.",
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
            text="05:00",
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
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted)
        self.log_text.see(tk.END)  # Scroll to bottom
        self.log_text.configure(state=tk.DISABLED)
    
    def _clear_log(self) -> None:
        """Clear the activity log."""
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
        self.switch_interval_entry.configure(state=state)
        self.click_phase_entry.configure(state=state)
        self.runtime_entry.configure(state=state)
    
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
        """Handle runtime expiration - auto-close the application."""
        def close_app():
            self._log_message("⏱️ Runtime expired - closing application...")
            # Small delay to let the log message appear
            self.root.after(1000, self._on_close)
        
        # Schedule on main thread
        self.root.after(0, close_app)
    
    def _on_close(self) -> None:
        """Handle window close event."""
        # Stop automation if running
        if self.scheduler.is_running():
            self.scheduler.stop()
        
        # Unregister hotkey
        self._unregister_hotkey()
        
        # Destroy window
        self.root.destroy()
    
    def run(self) -> None:
        """Start the application main loop."""
        self._log_message("🚀 AutoWeb ready")
        self._log_message("Configure settings and click SUBMIT")
        self._log_message("🔑 Ctrl+Shift+Q to stop after starting")
        self.root.mainloop()
    
    def _on_submit(self) -> None:
        """Handle SUBMIT button click - show confirmation dialog."""
        # Get settings from inputs
        try:
            switch_interval = float(self.switch_interval_var.get())
            click_phase_max = float(self.click_phase_var.get())
            runtime = float(self.runtime_var.get())
            
            if switch_interval <= 0:
                switch_interval = 5
            if click_phase_max <= 0:
                click_phase_max = 10
            if runtime <= 0:
                runtime = 5
                
        except ValueError:
            switch_interval = 5
            click_phase_max = 10
            runtime = 5
        
        # Create settings dict
        settings = {
            'switch_interval': switch_interval,
            'click_phase': click_phase_max,
            'runtime': runtime
        }
        
        # Show confirmation dialog (no shortcuts shown)
        dialog = ConsentDialog(self.root, settings)
        if not dialog.show():
            return  # User clicked Back
        
        # User confirmed - start automation
        self._log_message(f"Settings: App Switch {switch_interval}s, Click 0-{click_phase_max}s, Runtime {int(runtime)}min")
        
        # Register hotkey (Ctrl+Shift+Q to stop)
        self._register_hotkey()
        
        # Apply settings to scheduler
        total_runtime = int(runtime * 60)  # Convert minutes to seconds
        
        # App switch interval is the user's setting (e.g., 300 seconds)
        self.scheduler.config.app_switch_interval = switch_interval
        
        # Action interval is fast (3-8 seconds) for scroll, tab switch, mouse move
        self.scheduler.config.action_interval_min = 3.0
        self.scheduler.config.action_interval_max = 8.0
        
        self.scheduler.config.click_phase_max = click_phase_max
        self.scheduler.config.active_duration = total_runtime
        self.scheduler.config.idle_min = 0
        self.scheduler.config.idle_max = 0
        self.scheduler.config.total_runtime = total_runtime
        
        # Disable submit button
        self.submit_btn.configure(state=tk.DISABLED)
        self._set_settings_enabled(False)
        
        # Start automation
        if self.scheduler.start():
            self._log_message("Automation started")
            self._log_message(f"Apps switch every {int(switch_interval)} seconds")
            self._log_message("PAUSES on clicks/keyboard only")
            
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

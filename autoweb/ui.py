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
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional
import logging
import sys
from datetime import datetime

from .scheduler import AutomationScheduler, SchedulerState, AutomationPhase, SchedulerConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    Dialog that displays a warning message and requires user consent.
    
    This dialog must be shown before automation can start.
    The user must explicitly agree to the terms.
    """
    
    WARNING_TEXT = """
⚠️  IMPORTANT NOTICE  ⚠️

This tool is for AUTOMATION TESTING and ACCESSIBILITY 
USE CASES ONLY.

This application will:
• Simulate mouse movements and clicks
• Simulate keyboard input
• Switch between open applications
• Run automation cycles until manually stopped

Please ensure you understand and consent to these actions.

By clicking "I Understand & Agree", you confirm that:
1. You are using this tool for legitimate testing purposes
2. You have the authority to run automation on this system
3. You will monitor the automation and stop it if needed
"""
    
    def __init__(self, parent: tk.Tk):
        """
        Initialize the consent dialog.
        
        Args:
            parent: Parent window
        """
        self.parent = parent
        self.consent_given = False
    
    def show(self) -> bool:
        """
        Show the consent dialog and wait for user response.
        
        Returns:
            True if user agreed, False otherwise
        """
        dialog = tk.Toplevel(self.parent)
        dialog.title("⚠️ AutoWeb - User Consent Required")
        dialog.geometry("520x550")
        dialog.configure(bg=Colors.BACKGROUND)
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 520) // 2
        y = (dialog.winfo_screenheight() - 550) // 2
        dialog.geometry(f"520x550+{x}+{y}")
        
        # Warning icon and title
        title_frame = tk.Frame(dialog, bg=Colors.BACKGROUND)
        title_frame.pack(pady=20)
        
        title_label = tk.Label(
            title_frame,
            text="🛡️ AutoWeb - Automation Tool",
            font=Fonts.TITLE,
            bg=Colors.BACKGROUND,
            fg=Colors.WARNING
        )
        title_label.pack()
        
        # Warning text
        text_frame = tk.Frame(dialog, bg=Colors.SURFACE, padx=20, pady=20)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        warning_label = tk.Label(
            text_frame,
            text=self.WARNING_TEXT,
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT,
            justify=tk.LEFT,
            wraplength=420
        )
        warning_label.pack()
        
        # Buttons
        button_frame = tk.Frame(dialog, bg=Colors.BACKGROUND)
        button_frame.pack(pady=20)
        
        def on_agree():
            self.consent_given = True
            dialog.destroy()
        
        def on_decline():
            self.consent_given = False
            dialog.destroy()
        
        agree_btn = tk.Button(
            button_frame,
            text="✓ I Understand & Agree",
            command=on_agree,
            font=Fonts.BODY,
            bg=Colors.SUCCESS,
            fg=Colors.BACKGROUND,
            activebackground="#8bc78f",
            padx=20,
            pady=10,
            cursor="hand2"
        )
        agree_btn.pack(side=tk.LEFT, padx=10)
        
        decline_btn = tk.Button(
            button_frame,
            text="✗ Cancel",
            command=on_decline,
            font=Fonts.BODY,
            bg=Colors.ERROR,
            fg=Colors.BACKGROUND,
            activebackground="#d97a8f",
            padx=20,
            pady=10,
            cursor="hand2"
        )
        decline_btn.pack(side=tk.LEFT, padx=10)
        
        # Wait for dialog to close
        self.parent.wait_window(dialog)
        
        return self.consent_given


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
    """
    
    def __init__(self):
        """Initialize the main application window."""
        # Create main window
        self.root = tk.Tk()
        self.root.title("AutoWeb - UI Automation Tool")
        self.root.geometry("600x700")
        self.root.configure(bg=Colors.BACKGROUND)
        self.root.resizable(True, True)
        self.root.minsize(500, 600)
        
        # Set window icon (if available)
        try:
            self.root.iconbitmap(default="")
        except:
            pass
        
        # Initialize scheduler with callback
        self.scheduler = AutomationScheduler(
            on_state_change=self._on_state_change
        )
        
        # Track consent
        self.consent_given = False
        
        # Build UI
        self._create_widgets()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 600) // 2
        y = (self.root.winfo_screenheight() - 700) // 2
        self.root.geometry(f"600x700+{x}+{y}")
        
        logger.info("AutoWebApp initialized")
    
    def _create_widgets(self) -> None:
        """Create all UI widgets."""
        # Main container
        main_frame = tk.Frame(self.root, bg=Colors.BACKGROUND)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Header
        self._create_header(main_frame)
        
        # Status card
        self._create_status_card(main_frame)
        
        # Info cards row
        self._create_info_cards(main_frame)
        
        # Control buttons
        self._create_controls(main_frame)
        
        # Activity log
        self._create_activity_log(main_frame)
    
    def _create_header(self, parent: tk.Frame) -> None:
        """Create the header section."""
        header_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
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
    
    def _create_status_card(self, parent: tk.Frame) -> None:
        """Create the main status display card."""
        # Status card frame
        status_card = tk.Frame(
            parent,
            bg=Colors.SURFACE,
            padx=30,
            pady=30
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
        self.timer_label.pack(pady=10)
        
        # Time remaining label
        time_desc_label = tk.Label(
            status_card,
            text="Time Remaining",
            font=Fonts.BODY,
            bg=Colors.SURFACE,
            fg=Colors.TEXT_DIM
        )
        time_desc_label.pack()
    
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
    
    def _create_controls(self, parent: tk.Frame) -> None:
        """Create the control buttons."""
        control_frame = tk.Frame(parent, bg=Colors.BACKGROUND)
        control_frame.pack(fill=tk.X, pady=20)
        
        # Start button
        self.start_btn = tk.Button(
            control_frame,
            text="▶️ Start Automation",
            command=self._on_start,
            font=Fonts.HEADING,
            bg=Colors.SUCCESS,
            fg=Colors.BACKGROUND,
            activebackground="#8bc78f",
            padx=30,
            pady=15,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        # Stop button
        self.stop_btn = tk.Button(
            control_frame,
            text="⏹️ Stop",
            command=self._on_stop,
            font=Fonts.HEADING,
            bg=Colors.ERROR,
            fg=Colors.BACKGROUND,
            activebackground="#d97a8f",
            padx=30,
            pady=15,
            cursor="hand2",
            relief=tk.FLAT,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
    
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
            else:
                self.status_label.configure(
                    text="⏹️ STOPPED",
                    fg=Colors.ERROR
                )
            
            # Update timer
            self.timer_label.configure(
                text=self._format_time(state.time_remaining)
            )
            
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
    
    def _on_start(self) -> None:
        """Handle start button click."""
        # Show consent dialog if not already consented
        if not self.consent_given:
            dialog = ConsentDialog(self.root)
            self.consent_given = dialog.show()
            
            if not self.consent_given:
                self._log_message("User declined consent. Automation not started.")
                return
        
        # Start automation
        if self.scheduler.start():
            self._log_message("✅ Automation started")
            self.start_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.NORMAL)
        else:
            self._log_message("❌ Failed to start automation")
    
    def _on_stop(self) -> None:
        """Handle stop button click."""
        if self.scheduler.stop():
            self._log_message("⏹️ Automation stopped")
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
        else:
            self._log_message("❌ Failed to stop automation")
    
    def _on_close(self) -> None:
        """Handle window close event."""
        # Stop automation if running
        if self.scheduler.is_running():
            self.scheduler.stop()
        
        # Destroy window
        self.root.destroy()
    
    def run(self) -> None:
        """Start the application main loop."""
        self._log_message("🚀 AutoWeb started")
        self._log_message("Click 'Start Automation' to begin")
        self.root.mainloop()


# Entry point for testing
if __name__ == "__main__":
    app = AutoWebApp()
    app.run()

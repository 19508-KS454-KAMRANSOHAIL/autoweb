"""
Window Manager Module
=====================

This module provides functionality for detecting and managing application windows
on Windows OS. It uses the pywin32 library to interact with the Windows API.

Key Concepts:
- EnumWindows: Windows API function that iterates through all top-level windows
- GetWindowText: Retrieves the window's title bar text
- SetForegroundWindow: Brings a window to the front and activates it
- HWND (Handle to a Window): A unique identifier for each window

Safety Note:
This module only reads window information and switches focus between existing
windows. It does not modify, close, or manipulate window contents.
"""

import ctypes
from ctypes import wintypes
from typing import List, Tuple, Optional, Callable
from dataclasses import dataclass
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    """
    Data class representing information about a window.
    
    Attributes:
        hwnd: The window handle (unique identifier)
        title: The window's title text
        is_visible: Whether the window is currently visible
        process_name: The name of the process that owns the window (if available)
    """
    hwnd: int
    title: str
    is_visible: bool
    process_name: str = ""


class WindowManager:
    """
    Manages detection and switching of application windows on Windows.
    
    This class provides methods to:
    - Enumerate all open windows
    - Filter windows to show only main application windows
    - Switch focus between windows
    - Get the currently active window
    
    How it works:
    Windows maintains a list of all windows (including invisible ones, child windows,
    and system windows). We use the Windows API through ctypes/pywin32 to:
    1. Enumerate all top-level windows
    2. Filter out invisible/system windows
    3. Allow programmatic focus switching
    """
    
    def __init__(self):
        """Initialize the WindowManager with Windows API references."""
        # Load Windows API functions
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        # Define callback type for EnumWindows
        # WNDENUMPROC is a callback that receives (hwnd, lParam) and returns BOOL
        self.WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM
        )
        
        # Windows to exclude (system windows, background processes)
        self._excluded_titles = [
            "Program Manager",
            "Windows Input Experience",
            "Settings",
            "Microsoft Text Input Application",
            "NVIDIA GeForce Overlay",
            "",  # Empty titles
        ]
        
        logger.info("WindowManager initialized successfully")
    
    def get_all_windows(self) -> List[WindowInfo]:
        """
        Enumerate all visible top-level windows.
        
        How EnumWindows works:
        - EnumWindows iterates through all top-level windows on the desktop
        - For each window, it calls our callback function
        - The callback receives the window handle (hwnd) and can process it
        - We filter for visible windows with titles (main application windows)
        
        Returns:
            List of WindowInfo objects representing each detected window
        """
        windows: List[WindowInfo] = []
        
        def enum_callback(hwnd: int, lParam: int) -> bool:
            """
            Callback function called for each window during enumeration.
            
            Args:
                hwnd: Handle to the current window
                lParam: Application-defined value (unused here)
            
            Returns:
                True to continue enumeration, False to stop
            """
            # Check if window is visible
            # IsWindowVisible returns non-zero if the window is visible
            if not self.user32.IsWindowVisible(hwnd):
                return True  # Continue enumeration
            
            # Get window title length
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True  # Skip windows without titles
            
            # Get window title
            # GetWindowTextW retrieves the text of the window's title bar
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            
            # Skip excluded windows
            if title in self._excluded_titles:
                return True
            
            # Skip windows that are tool windows or have no taskbar presence
            # GWL_EXSTYLE = -20, WS_EX_TOOLWINDOW = 0x00000080
            ex_style = self.user32.GetWindowLongW(hwnd, -20)
            if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
                return True
            
            # Check if window is minimized (IsIconic returns non-zero if minimized)
            is_minimized = self.user32.IsIconic(hwnd)
            if is_minimized:
                return True  # Skip minimized windows
            
            # Create WindowInfo and add to list
            window_info = WindowInfo(
                hwnd=hwnd,
                title=title,
                is_visible=True
            )
            windows.append(window_info)
            
            return True  # Continue enumeration
        
        # Create callback and enumerate windows
        callback = self.WNDENUMPROC(enum_callback)
        self.user32.EnumWindows(callback, 0)
        
        logger.debug(f"Found {len(windows)} windows")
        return windows
    
    def get_foreground_window(self) -> Optional[WindowInfo]:
        """
        Get information about the currently active (foreground) window.
        
        GetForegroundWindow returns the handle to the window that currently
        has keyboard focus and is in the foreground.
        
        Returns:
            WindowInfo for the active window, or None if unavailable
        """
        hwnd = self.user32.GetForegroundWindow()
        
        if not hwnd:
            return None
        
        # Get window title
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return WindowInfo(hwnd=hwnd, title="Unknown", is_visible=True)
        
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        
        return WindowInfo(
            hwnd=hwnd,
            title=buffer.value,
            is_visible=True
        )
    
    def switch_to_window(self, hwnd: int) -> bool:
        """
        Switch focus to a specific window by its handle.
        
        How SetForegroundWindow works:
        - Brings the specified window to the front of the Z-order
        - Activates the window and gives it keyboard focus
        - Does NOT change window state (no restore/minimize)
        
        Args:
            hwnd: The handle of the window to switch to
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if window still exists
            if not self.user32.IsWindow(hwnd):
                logger.debug(f"Window {hwnd} no longer exists")
                return False
            
            # Check if window is minimized - if so, skip it (don't restore)
            if self.user32.IsIconic(hwnd):
                logger.debug(f"Window {hwnd} is minimized - skipping (no restore)")
                return False
            
            # Check if window is visible
            if not self.user32.IsWindowVisible(hwnd):
                logger.debug(f"Window {hwnd} is not visible - skipping")
                return False
            
            # SetForegroundWindow brings the window to the front WITHOUT changing its state
            result = self.user32.SetForegroundWindow(hwnd)
            
            if result:
                logger.info(f"Switched to window with handle {hwnd}")
                return True
            else:
                # Alternative method using AttachThreadInput
                # This attaches our thread's input to the foreground thread
                foreground_hwnd = self.user32.GetForegroundWindow()
                if not foreground_hwnd:
                    return False
                    
                foreground_thread = self.user32.GetWindowThreadProcessId(
                    foreground_hwnd, None
                )
                current_thread = self.kernel32.GetCurrentThreadId()
                
                # Attach threads to share input state
                self.user32.AttachThreadInput(
                    foreground_thread, current_thread, True
                )
                
                # Now try to set foreground window (no restore/minimize)
                self.user32.SetForegroundWindow(hwnd)
                self.user32.SetFocus(hwnd)
                
                # Detach threads
                self.user32.AttachThreadInput(
                    foreground_thread, current_thread, False
                )
                
                logger.info(f"Switched to window {hwnd} using thread attachment")
                return True
                
        except Exception as e:
            logger.error(f"Failed to switch to window {hwnd}: {e}")
            return False
    
    def switch_to_next_window(self) -> Optional[WindowInfo]:
        """
        Switch to the next window in the list of open windows.
        
        This simulates Alt+Tab behavior by cycling through available windows.
        
        Returns:
            WindowInfo of the newly focused window, or None if failed
        """
        windows = self.get_all_windows()
        
        if len(windows) < 2:
            logger.warning("Not enough windows to switch")
            return None
        
        current = self.get_foreground_window()
        if not current:
            # Just switch to the first window
            if self.switch_to_window(windows[0].hwnd):
                return windows[0]
            return None
        
        # Find current window in list and switch to next
        current_index = -1
        for i, window in enumerate(windows):
            if window.hwnd == current.hwnd:
                current_index = i
                break
        
        # Calculate next index (wrap around)
        next_index = (current_index + 1) % len(windows)
        next_window = windows[next_index]
        
        if self.switch_to_window(next_window.hwnd):
            return next_window
        
        return None
    
    def get_window_count(self) -> int:
        """
        Get the count of visible application windows.
        
        Returns:
            Number of detected windows
        """
        return len(self.get_all_windows())
    
    def is_window_minimized(self, hwnd: int) -> bool:
        """
        Check if a window is minimized.
        
        Args:
            hwnd: The window handle to check
        
        Returns:
            True if the window is minimized, False otherwise
        """
        return bool(self.user32.IsIconic(hwnd))
    
    def get_visible_windows(self) -> List[WindowInfo]:
        """
        Get only visible (non-minimized) windows.
        
        This method returns windows that are:
        - Visible on screen
        - Not minimized
        - Main application windows (not tool windows)
        
        Returns:
            List of WindowInfo for visible windows only
        """
        return self.get_all_windows()  # Already filters minimized in get_all_windows
    
    def find_monitask_windows(self) -> List[WindowInfo]:
        """
        Find all MoniTask related windows.
        
        Returns:
            List of MoniTask windows found
        """
        all_windows = self.get_all_windows()
        monitask_windows = []
        
        for window in all_windows:
            title_lower = window.title.lower()
            # Look for various MoniTask window titles
            if any(keyword in title_lower for keyword in [
                'monitask', 'confirmation', 'you\'ve been idle', 
                'do you wish to pause', 'remove this time'
            ]):
                monitask_windows.append(window)
                
        return monitask_windows
    
    def minimize_window(self, hwnd: int) -> bool:
        """
        Minimize a window.
        
        Args:
            hwnd: Window handle to minimize
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # SW_MINIMIZE = 6
            result = self.user32.ShowWindow(hwnd, 6)
            if result:
                logger.info(f"Successfully minimized window {hwnd}")
                return True
            else:
                logger.warning(f"Failed to minimize window {hwnd}")
                return False
        except Exception as e:
            logger.error(f"Error minimizing window {hwnd}: {e}")
            return False
    
    def click_button_by_text(self, hwnd: int, button_text: str) -> bool:
        """
        Find and click a button with specific text in a window.
        
        Args:
            hwnd: Window handle containing the button
            button_text: Text to look for on the button
            
        Returns:
            True if button was found and clicked, False otherwise
        """
        try:
            # Try to find child controls (buttons) in the window
            def enum_child_proc(child_hwnd, lparam):
                try:
                    # Get the text of the child control
                    length = self.user32.GetWindowTextLengthW(child_hwnd)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        self.user32.GetWindowTextW(child_hwnd, buffer, length + 1)
                        child_text = buffer.value
                        
                        # Check if this is the button we're looking for
                        if button_text.lower() in child_text.lower():
                            # Get button position and size
                            rect = wintypes.RECT()
                            if self.user32.GetWindowRect(child_hwnd, ctypes.byref(rect)):
                                # Calculate center of button
                                x = (rect.left + rect.right) // 2
                                y = (rect.top + rect.bottom) // 2
                                
                                # Click the button
                                self._click_at_position(x, y)
                                logger.info(f"Clicked button '{child_text}' at ({x}, {y})")
                                return False  # Stop enumeration
                except Exception as e:
                    logger.debug(f"Error processing child window: {e}")
                    
                return True  # Continue enumeration
            
            # Enumerate child windows to find buttons
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            enum_proc = WNDENUMPROC(enum_child_proc)
            self.user32.EnumChildWindows(hwnd, enum_proc, 0)
            
            return True
            
        except Exception as e:
            logger.error(f"Error clicking button '{button_text}' in window {hwnd}: {e}")
            return False
    
    def _click_at_position(self, x: int, y: int):
        """
        Perform a mouse click at the specified screen coordinates.
        
        Args:
            x: X coordinate
            y: Y coordinate
        """
        # Set cursor position
        self.user32.SetCursorPos(x, y)
        
        # Mouse down
        self.user32.mouse_event(0x0002, x, y, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        
        # Small delay
        import time
        time.sleep(0.1)
        
        # Mouse up  
        self.user32.mouse_event(0x0004, x, y, 0, 0)  # MOUSEEVENTF_LEFTUP


# Example usage and testing
if __name__ == "__main__":
    manager = WindowManager()
    
    print("Detecting open windows...")
    windows = manager.get_all_windows()
    
    for i, window in enumerate(windows, 1):
        print(f"{i}. {window.title} (Handle: {window.hwnd})")
    
    print(f"\nCurrent foreground window: {manager.get_foreground_window()}")

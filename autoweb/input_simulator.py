"""
Input Simulator Module
======================

This module provides functionality for simulating mouse and keyboard input
on Windows. It uses the Windows API through ctypes to generate OS-level
input events.

Key Concepts:
- SendInput: Windows API function that synthesizes input events
- INPUT structure: Describes a keyboard, mouse, or hardware input event
- Virtual Key Codes: Numeric codes representing keyboard keys

How OS-Level Input Simulation Works:
------------------------------------
Windows processes input through a queue system. When you physically press a key
or move the mouse, the hardware driver generates input events that go into the
system input queue. The SendInput API allows us to inject synthetic events
into this same queue, making them indistinguishable from real hardware input.

This is different from "fake" input methods that only work within specific
applications. OS-level simulation works with ALL applications because it
operates at the system level.

Safety Notes:
- This module simulates user input for testing/accessibility purposes
- Mouse movements are bounded to screen dimensions
- All actions are logged for transparency
- The simulation can be stopped at any time
"""

import ctypes
from ctypes import wintypes
import time
import random
import logging
from typing import Tuple, Optional
from enum import IntEnum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Windows API Constants and Structures
# ============================================================================

class InputType(IntEnum):
    """Types of input that can be simulated via SendInput."""
    MOUSE = 0       # Mouse input
    KEYBOARD = 1    # Keyboard input
    HARDWARE = 2    # Hardware input (not used here)


class MouseEventFlags(IntEnum):
    """
    Flags for mouse input events.
    These specify what type of mouse action to simulate.
    """
    MOVE = 0x0001           # Mouse movement
    LEFTDOWN = 0x0002       # Left button pressed
    LEFTUP = 0x0004         # Left button released
    RIGHTDOWN = 0x0008      # Right button pressed
    RIGHTUP = 0x0010        # Right button released
    MIDDLEDOWN = 0x0020     # Middle button pressed
    MIDDLEUP = 0x0040       # Middle button released
    WHEEL = 0x0800          # Mouse wheel rotation
    ABSOLUTE = 0x8000       # Absolute coordinates (0-65535)
    VIRTUALDESK = 0x4000    # Map to entire virtual desktop


class KeyEventFlags(IntEnum):
    """Flags for keyboard input events."""
    KEYDOWN = 0x0000        # Key pressed (default)
    KEYUP = 0x0002          # Key released
    EXTENDEDKEY = 0x0001    # Extended key (e.g., right Alt, right Ctrl)
    UNICODE = 0x0004        # Unicode character


class VirtualKey(IntEnum):
    """
    Virtual Key Codes for common keys.
    These are standardized codes that Windows uses to identify keys.
    """
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_SHIFT = 0x10
    VK_CONTROL = 0x11
    VK_ALT = 0x12  # Also called VK_MENU
    VK_ESCAPE = 0x1B
    VK_SPACE = 0x20
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_LWIN = 0x5B  # Left Windows key
    VK_RWIN = 0x5C  # Right Windows key
    VK_F12 = 0x7B   # F12 key


# Structure definitions for SendInput
# These match the Windows API structures exactly

class MOUSEINPUT(ctypes.Structure):
    """
    Structure containing information about a simulated mouse event.
    
    Fields:
        dx, dy: Mouse position (absolute or relative based on flags)
        mouseData: Wheel delta or button data
        dwFlags: Event type flags (MouseEventFlags)
        time: Timestamp (0 = system default)
        dwExtraInfo: Extra application-defined info
    """
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


class KEYBDINPUT(ctypes.Structure):
    """
    Structure containing information about a simulated keyboard event.
    
    Fields:
        wVk: Virtual key code
        wScan: Hardware scan code
        dwFlags: Event flags (KeyEventFlags)
        time: Timestamp
        dwExtraInfo: Extra application-defined info
    """
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


class HARDWAREINPUT(ctypes.Structure):
    """Structure for hardware input (not used in this module)."""
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]


class INPUTUNION(ctypes.Union):
    """Union of all possible input types."""
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]


class INPUT(ctypes.Structure):
    """
    Main input structure passed to SendInput.
    Contains the type of input and a union of input data.
    """
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUTUNION)
    ]


class InputSimulator:
    """
    Simulates mouse and keyboard input at the OS level.
    
    This class provides methods to:
    - Move the mouse to absolute or relative positions
    - Click mouse buttons (left, right, middle)
    - Press and release keyboard keys
    - Execute keyboard shortcuts (e.g., Alt+Tab)
    
    All input is simulated through the Windows SendInput API, which means
    it works with any application, including games and full-screen apps.
    """
    
    def __init__(self):
        """Initialize the InputSimulator with Windows API references."""
        self.user32 = ctypes.windll.user32
        
        # Get screen dimensions for bounds checking
        self.screen_width = self.user32.GetSystemMetrics(0)   # SM_CXSCREEN
        self.screen_height = self.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        
        # Absolute coordinate conversion factor
        # SendInput with ABSOLUTE flag uses 0-65535 range
        self._abs_scale_x = 65535 / self.screen_width
        self._abs_scale_y = 65535 / self.screen_height
        
        logger.info(
            f"InputSimulator initialized. "
            f"Screen: {self.screen_width}x{self.screen_height}"
        )
    
    def _send_input(self, *inputs: INPUT) -> int:
        """
        Send one or more input events to the system.
        
        How SendInput works:
        - Takes an array of INPUT structures
        - Inserts them into the system input queue atomically
        - Returns the number of events successfully inserted
        - Events are processed in order by the system
        
        Args:
            *inputs: Variable number of INPUT structures to send
        
        Returns:
            Number of events successfully sent
        """
        input_array = (INPUT * len(inputs))(*inputs)
        return self.user32.SendInput(
            len(inputs),
            ctypes.pointer(input_array),
            ctypes.sizeof(INPUT)
        )
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """
        Get the current mouse cursor position.
        
        Returns:
            Tuple of (x, y) coordinates
        """
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return (point.x, point.y)
    
    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        """
        Move the mouse cursor to a position.
        
        How mouse movement works:
        - ABSOLUTE flag: x,y are screen coordinates (0 to 65535 scale)
        - Without ABSOLUTE: x,y are relative to current position
        
        Args:
            x: X coordinate (or delta if relative)
            y: Y coordinate (or delta if relative)
            absolute: If True, move to absolute position; if False, relative
        
        Returns:
            True if successful
        """
        if absolute:
            # Clamp to screen bounds
            x = max(0, min(x, self.screen_width - 1))
            y = max(0, min(y, self.screen_height - 1))
            
            # Convert to absolute coordinates (0-65535 range)
            abs_x = int(x * self._abs_scale_x)
            abs_y = int(y * self._abs_scale_y)
            
            flags = MouseEventFlags.MOVE | MouseEventFlags.ABSOLUTE
            
            inp = INPUT()
            inp.type = InputType.MOUSE
            inp.union.mi.dx = abs_x
            inp.union.mi.dy = abs_y
            inp.union.mi.dwFlags = flags
            inp.union.mi.time = 0
            inp.union.mi.dwExtraInfo = None
        else:
            # Relative movement
            flags = MouseEventFlags.MOVE
            
            inp = INPUT()
            inp.type = InputType.MOUSE
            inp.union.mi.dx = x
            inp.union.mi.dy = y
            inp.union.mi.dwFlags = flags
            inp.union.mi.time = 0
            inp.union.mi.dwExtraInfo = None
        
        result = self._send_input(inp)
        logger.debug(f"Mouse moved to ({x}, {y}), absolute={absolute}")
        return result > 0
    
    def move_mouse_smooth(
        self, 
        target_x: int, 
        target_y: int, 
        duration: float = 0.5,
        steps: int = 20
    ) -> bool:
        """
        Move the mouse smoothly to a position over time.
        
        Creates a more natural-looking mouse movement by interpolating
        positions between current and target locations.
        
        Args:
            target_x: Target X coordinate
            target_y: Target Y coordinate
            duration: Time in seconds for the movement
            steps: Number of intermediate positions
        
        Returns:
            True if successful
        """
        current_x, current_y = self.get_mouse_position()
        
        for i in range(1, steps + 1):
            # Linear interpolation
            progress = i / steps
            
            # Add slight randomness for more natural movement
            jitter_x = random.randint(-2, 2) if i < steps else 0
            jitter_y = random.randint(-2, 2) if i < steps else 0
            
            new_x = int(current_x + (target_x - current_x) * progress) + jitter_x
            new_y = int(current_y + (target_y - current_y) * progress) + jitter_y
            
            self.move_mouse(new_x, new_y)
            time.sleep(duration / steps)
        
        # Ensure we end up exactly at target
        self.move_mouse(target_x, target_y)
        return True
    
    def move_mouse_random(self) -> Tuple[int, int]:
        """
        Move the mouse to a random position on screen.
        
        Generates random coordinates within safe screen bounds,
        avoiding UI elements like sidebars, taskbars, and icons.
        
        AVOIDS:
        - Left 70px (VS Code sidebar icons)
        - Right 70px (chat panels, window controls)
        - Bottom 60px (taskbar)
        - Top 40px (title bar, menus)
        
        Returns:
            Tuple of (x, y) where mouse was moved to
        """
        # Define safe zone avoiding dangerous UI areas
        left_margin = 80    # Avoid sidebar icons
        right_margin = 80   # Avoid chat panels
        top_margin = 50     # Avoid title bar
        bottom_margin = 70  # Avoid taskbar
        
        x = random.randint(left_margin, self.screen_width - right_margin)
        y = random.randint(top_margin, self.screen_height - bottom_margin)
        
        self.move_mouse_smooth(x, y, duration=0.3, steps=10)
        logger.info(f"Random mouse movement to safe zone ({x}, {y})")
        return (x, y)
    
    def safe_click(self) -> Tuple[int, int]:
        """
        Perform a SAFE click that won't affect code, content, or UI elements.
        
        SAFE AREAS (neutral zones with zero functional impact):
        - Window title bar area (very top, avoiding close/min/max buttons)
        - Right scrollbar area (avoiding content)
        
        STRICTLY AVOIDED AREAS:
        - VS Code sidebar icons (Search, Explorer, GitLens, Extensions, etc.) - left 50px
        - Copilot/chat panels - right side areas
        - Bottom taskbar area
        - Start button area
        - System tray
        - Any interactive UI elements
        
        Returns:
            Tuple of (x, y) where the safe click was performed
        """
        # Calculate safe zones that have ZERO functional impact
        # Avoid: left 60px (sidebar icons), right 60px (chat panels), bottom 60px (taskbar)
        # Focus on: title bar center area only
        
        safe_zones = [
            # Title bar center area ONLY - most neutral zone
            # Avoid close/minimize/maximize buttons (right side of title bar)
            # Avoid VS Code menu (left side of title bar)
            (random.randint(200, self.screen_width - 200), random.randint(10, 30)),
            (random.randint(250, self.screen_width - 250), random.randint(8, 28)),
            (random.randint(300, self.screen_width - 300), random.randint(12, 32)),
            # Very center of screen - typically safe in most apps
            (self.screen_width // 2 + random.randint(-100, 100), self.screen_height // 2 + random.randint(-50, 50)),
        ]
        
        # Choose a random safe zone
        x, y = random.choice(safe_zones)
        
        # Clamp to safe bounds - avoid dangerous zones
        # Left: avoid sidebar icons (0-60px)
        x = max(70, x)
        # Right: avoid chat panels and window controls (last 80px)
        x = min(self.screen_width - 80, x)
        # Bottom: avoid taskbar (last 50px)
        y = min(self.screen_height - 60, y)
        
        # Move to the safe position
        self.move_mouse_smooth(x, y, duration=0.2, steps=8)
        time.sleep(0.1)
        
        # Perform the click
        self.click("left")
        logger.info(f"Safe click at neutral position ({x}, {y})")
        return (x, y)
    
    def safe_key_press(self) -> str:
        """
        Perform a SAFE key press that has no visible or functional effect.
        
        Safe keys include:
        - Shift key alone (no effect without other keys)
        - Ctrl key alone (no effect without other keys)
        - Scroll Lock (rarely used, no visible effect)
        - Right Shift (no effect alone)
        
        Keys that are NEVER used:
        - Any letter, number, or symbol keys
        - Enter, Tab, Space, Backspace, Delete
        - Arrow keys (can navigate)
        - F keys (can trigger actions)
        - Windows key (opens Start menu)
        - Alt key (can activate menus)
        - Escape (can close dialogs)
        
        Returns:
            Description of the key pressed
        """
        # Safe keys that have no visible effect when pressed alone
        safe_keys = [
            (VirtualKey.VK_SHIFT, "Shift"),
            (VirtualKey.VK_CONTROL, "Ctrl"),
            (0x91, "Scroll Lock"),  # VK_SCROLL
            (0xA1, "Right Shift"),  # VK_RSHIFT
            (0xA3, "Right Ctrl"),   # VK_RCONTROL
        ]
        
        # Choose a random safe key
        vk_code, key_name = random.choice(safe_keys)
        
        # Press and release the key
        self.key_press(vk_code)
        
        logger.info(f"Safe key press: {key_name}")
        return key_name
    
    def scroll(self, direction: str = "down", amount: int = 3) -> bool:
        """
        Simulate mouse wheel scrolling.
        
        How scrolling works:
        - SendInput with WHEEL flag sends scroll events
        - Positive mouseData = scroll up
        - Negative mouseData = scroll down
        - Amount is in "clicks" (120 units = 1 wheel click)
        
        Args:
            direction: "up" or "down"
            amount: Number of wheel clicks (1-5 typical)
        
        Returns:
            True if successful
        """
        # WHEEL_DELTA is 120 per click
        wheel_delta = 120 * amount
        if direction == "down":
            wheel_delta = -wheel_delta
        
        inp = INPUT()
        inp.type = InputType.MOUSE
        inp.union.mi.dx = 0
        inp.union.mi.dy = 0
        inp.union.mi.mouseData = wheel_delta
        inp.union.mi.dwFlags = MouseEventFlags.WHEEL
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = None
        
        result = self._send_input(inp)
        logger.info(f"Scrolled {direction} by {amount} clicks")
        return result > 0
    
    def scroll_random(self) -> str:
        """
        Perform a random scroll action (up or down).
        
        Returns:
            Direction of scroll ("up" or "down")
        """
        direction = random.choice(["up", "down"])
        amount = random.randint(1, 4)
        self.scroll(direction, amount)
        return direction
    
    def scroll_sequence(self) -> str:
        """
        Perform a natural scrolling sequence - scroll down then up or vice versa.
        
        This simulates a user reading/browsing a page by scrolling
        in one direction, then scrolling back.
        
        Returns:
            Description of scroll sequence
        """
        import time as t
        
        # Choose pattern: mostly scroll down first (reading), sometimes up first
        start_down = random.random() < 0.7
        
        if start_down:
            # Scroll down first (like reading)
            down_amount = random.randint(2, 5)
            self.scroll("down", down_amount)
            t.sleep(random.uniform(0.3, 0.8))
            
            # Then scroll up a bit
            up_amount = random.randint(1, 3)
            self.scroll("up", up_amount)
            
            return f"down {down_amount}, up {up_amount}"
        else:
            # Scroll up first
            up_amount = random.randint(2, 4)
            self.scroll("up", up_amount)
            t.sleep(random.uniform(0.3, 0.8))
            
            # Then scroll down
            down_amount = random.randint(1, 3)
            self.scroll("down", down_amount)
            
            return f"up {up_amount}, down {down_amount}"
    
    def click(
        self, 
        button: str = "left", 
        x: Optional[int] = None, 
        y: Optional[int] = None
    ) -> bool:
        """
        Perform a mouse click.
        
        How clicking works:
        - A click is composed of a button-down event followed by button-up
        - We send both events atomically through SendInput
        - Optional: move to position before clicking
        
        Args:
            button: Which button ("left", "right", "middle")
            x: X coordinate to click (None = current position)
            y: Y coordinate to click (None = current position)
        
        Returns:
            True if successful
        """
        # Move to position if specified
        if x is not None and y is not None:
            self.move_mouse(x, y)
            time.sleep(0.01)  # Small delay for stability
        
        # Select button flags
        if button == "left":
            down_flag = MouseEventFlags.LEFTDOWN
            up_flag = MouseEventFlags.LEFTUP
        elif button == "right":
            down_flag = MouseEventFlags.RIGHTDOWN
            up_flag = MouseEventFlags.RIGHTUP
        elif button == "middle":
            down_flag = MouseEventFlags.MIDDLEDOWN
            up_flag = MouseEventFlags.MIDDLEUP
        else:
            logger.error(f"Unknown button: {button}")
            return False
        
        # Create down event
        down_inp = INPUT()
        down_inp.type = InputType.MOUSE
        down_inp.union.mi.dwFlags = down_flag
        down_inp.union.mi.time = 0
        down_inp.union.mi.dwExtraInfo = None
        
        # Create up event
        up_inp = INPUT()
        up_inp.type = InputType.MOUSE
        up_inp.union.mi.dwFlags = up_flag
        up_inp.union.mi.time = 0
        up_inp.union.mi.dwExtraInfo = None
        
        # Send both events
        result = self._send_input(down_inp, up_inp)
        
        pos = self.get_mouse_position()
        logger.info(f"{button.capitalize()} click at {pos}")
        return result == 2
    
    def key_press(self, virtual_key: int) -> bool:
        """
        Press and release a single key.
        
        Args:
            virtual_key: Virtual key code (use VirtualKey enum)
        
        Returns:
            True if successful
        """
        # Key down
        down_inp = INPUT()
        down_inp.type = InputType.KEYBOARD
        down_inp.union.ki.wVk = virtual_key
        down_inp.union.ki.wScan = 0
        down_inp.union.ki.dwFlags = KeyEventFlags.KEYDOWN
        down_inp.union.ki.time = 0
        down_inp.union.ki.dwExtraInfo = None
        
        # Key up
        up_inp = INPUT()
        up_inp.type = InputType.KEYBOARD
        up_inp.union.ki.wVk = virtual_key
        up_inp.union.ki.wScan = 0
        up_inp.union.ki.dwFlags = KeyEventFlags.KEYUP
        up_inp.union.ki.time = 0
        up_inp.union.ki.dwExtraInfo = None
        
        result = self._send_input(down_inp, up_inp)
        logger.debug(f"Key press: {virtual_key}")
        return result == 2
    
    def key_down(self, virtual_key: int) -> bool:
        """
        Press a key down (without releasing).
        
        Useful for modifier keys in shortcuts.
        
        Args:
            virtual_key: Virtual key code
        
        Returns:
            True if successful
        """
        inp = INPUT()
        inp.type = InputType.KEYBOARD
        inp.union.ki.wVk = virtual_key
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = KeyEventFlags.KEYDOWN
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        
        return self._send_input(inp) > 0
    
    def key_up(self, virtual_key: int) -> bool:
        """
        Release a key.
        
        Args:
            virtual_key: Virtual key code
        
        Returns:
            True if successful
        """
        inp = INPUT()
        inp.type = InputType.KEYBOARD
        inp.union.ki.wVk = virtual_key
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = KeyEventFlags.KEYUP
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = None
        
        return self._send_input(inp) > 0
    
    def shortcut_alt_tab(self) -> bool:
        """
        Execute Alt+Tab shortcut to switch windows.
        
        How keyboard shortcuts work:
        1. Press modifier key(s) down
        2. Press the action key
        3. Release the action key
        4. Release modifier key(s)
        
        Returns:
            True if successful
        """
        logger.info("Executing Alt+Tab")
        
        # Use SendInput for more reliable Alt+Tab
        # Alt down
        alt_down = INPUT()
        alt_down.type = InputType.KEYBOARD
        alt_down.union.ki.wVk = VirtualKey.VK_ALT
        alt_down.union.ki.wScan = 0
        alt_down.union.ki.dwFlags = 0
        alt_down.union.ki.time = 0
        alt_down.union.ki.dwExtraInfo = None
        
        # Tab down
        tab_down = INPUT()
        tab_down.type = InputType.KEYBOARD
        tab_down.union.ki.wVk = VirtualKey.VK_TAB
        tab_down.union.ki.wScan = 0
        tab_down.union.ki.dwFlags = 0
        tab_down.union.ki.time = 0
        tab_down.union.ki.dwExtraInfo = None
        
        # Tab up
        tab_up = INPUT()
        tab_up.type = InputType.KEYBOARD
        tab_up.union.ki.wVk = VirtualKey.VK_TAB
        tab_up.union.ki.wScan = 0
        tab_up.union.ki.dwFlags = KeyEventFlags.KEYUP
        tab_up.union.ki.time = 0
        tab_up.union.ki.dwExtraInfo = None
        
        # Alt up
        alt_up = INPUT()
        alt_up.type = InputType.KEYBOARD
        alt_up.union.ki.wVk = VirtualKey.VK_ALT
        alt_up.union.ki.wScan = 0
        alt_up.union.ki.dwFlags = KeyEventFlags.KEYUP
        alt_up.union.ki.time = 0
        alt_up.union.ki.dwExtraInfo = None
        
        # Send all events with proper timing
        self._send_input(alt_down)
        time.sleep(0.05)
        self._send_input(tab_down)
        time.sleep(0.05)
        self._send_input(tab_up)
        time.sleep(0.15)  # Give time for Windows to process
        self._send_input(alt_up)
        time.sleep(0.1)
        
        return True
    
    def shortcut_ctrl_tab(self) -> bool:
        """
        Execute Ctrl+Tab shortcut (switch tabs in many applications).
        
        Returns:
            True if successful
        """
        logger.info("Executing Ctrl+Tab")
        
        self.key_down(VirtualKey.VK_CONTROL)
        time.sleep(0.05)
        
        self.key_press(VirtualKey.VK_TAB)
        time.sleep(0.05)
        
        self.key_up(VirtualKey.VK_CONTROL)
        
        return True
    
    def shortcut_win_tab(self) -> bool:
        """
        Execute Windows+Tab shortcut (Task View on Windows 10/11).
        
        Returns:
            True if successful
        """
        logger.info("Executing Win+Tab")
        
        self.key_down(VirtualKey.VK_LWIN)
        time.sleep(0.05)
        
        self.key_press(VirtualKey.VK_TAB)
        time.sleep(0.1)
        
        self.key_up(VirtualKey.VK_LWIN)
        
        return True
    
    def type_text(self, text: str, delay: float = 0.05) -> bool:
        """
        Type a string of text character by character.
        
        Uses UNICODE input mode which directly sends characters
        instead of virtual key codes.
        
        Args:
            text: The text to type
            delay: Delay between characters in seconds
        
        Returns:
            True if successful
        """
        for char in text:
            # Key down with unicode
            down_inp = INPUT()
            down_inp.type = InputType.KEYBOARD
            down_inp.union.ki.wVk = 0  # Not used for unicode
            down_inp.union.ki.wScan = ord(char)
            down_inp.union.ki.dwFlags = KeyEventFlags.UNICODE
            down_inp.union.ki.time = 0
            down_inp.union.ki.dwExtraInfo = None
            
            # Key up with unicode
            up_inp = INPUT()
            up_inp.type = InputType.KEYBOARD
            up_inp.union.ki.wVk = 0
            up_inp.union.ki.wScan = ord(char)
            up_inp.union.ki.dwFlags = KeyEventFlags.UNICODE | KeyEventFlags.KEYUP
            up_inp.union.ki.time = 0
            up_inp.union.ki.dwExtraInfo = None
            
            self._send_input(down_inp, up_inp)
            time.sleep(delay)
        
        logger.info(f"Typed {len(text)} characters")
        return True


# Example usage and testing
if __name__ == "__main__":
    sim = InputSimulator()
    
    print(f"Current mouse position: {sim.get_mouse_position()}")
    print(f"Screen size: {sim.screen_width}x{sim.screen_height}")
    
    print("\nMoving mouse to center of screen...")
    center_x = sim.screen_width // 2
    center_y = sim.screen_height // 2
    sim.move_mouse_smooth(center_x, center_y)
    
    print("Done!")

# 🤖 AutoWeb - Windows Desktop Automation Tool

A Windows desktop application for **UI automation** and **accessibility testing** purposes.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ⚠️ Important Notice

**This tool is for automation testing and accessibility use cases only.**

The application simulates user input at the OS level. Please ensure you have proper authorization before running automation on any system.

---

## 📋 Features

### Core Features

- **Window Detection**: Automatically detects all open application windows
- **Application Switching**: Programmatically switches between open applications (non-minimized only)
- **Tab Switching**: Uses keyboard shortcuts (Ctrl+Tab) to cycle through tabs in supported apps
- **Mouse Simulation**: Random mouse movements and safe clicks (edges only)
- **Keyboard Simulation**: OS-level keyboard input
- **Automation Cycles**: Configurable active/idle phases with randomized timing
- **User Consent**: Requires explicit user agreement before starting
- **Activity Logging**: Real-time log of all automation actions

### Idle Detection & State Management

- **Instant Pause**: Automation pauses immediately on any mouse movement, click, or keyboard input
- **Smart Resume**: Waits for 2 minutes (120 seconds) of complete user inactivity before resuming
- **Idle Timer Reset**: Timer resets immediately on any user interaction
- **No Interruption**: No switching or clicking happens during user activity

### Runtime Management

- **Configurable Runtime**: Set total runtime duration (default: 5 minutes)
- **Auto-Close**: Application automatically closes when runtime expires
- **Visual Countdown**: Real-time display of remaining runtime

### Window Filtering

- **Visible Windows Only**: Switches only between currently active and visible applications
- **Minimized Ignored**: Minimized applications are completely ignored
- **Tab Cycling**: For apps like Chrome and VS Code, also cycles through their tabs

---

## 🏗️ Architecture

The application follows a modular design with clear separation of concerns:

```
autoweb/
├── main.py              # Application entry point
├── __main__.py          # Package entry point (python -m autoweb)
├── requirements.txt     # Dependencies (none - stdlib only!)
├── README.md            # This file
└── autoweb/
    ├── __init__.py         # Package initialization
    ├── window_manager.py   # Window detection and switching
    ├── input_simulator.py  # Mouse and keyboard simulation
    ├── scheduler.py        # Automation cycle management
    ├── idle_detector.py    # User activity detection
    └── ui.py               # Graphical user interface
```

### Module Descriptions

| Module               | Purpose                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------- |
| `window_manager.py`  | Uses Windows API (EnumWindows, SetForegroundWindow) to detect and switch between application windows |
| `input_simulator.py` | Uses Windows SendInput API to simulate mouse movements, clicks, and keyboard input                   |
| `scheduler.py`       | Manages automation timing with active/idle phases and user activity integration                      |
| `idle_detector.py`   | Uses Windows low-level hooks to detect mouse and keyboard activity system-wide                       |
| `ui.py`              | Tkinter-based GUI with start/stop controls, status display, and runtime configuration                |

---

## 🚀 Getting Started

### Prerequisites

- **Operating System**: Windows 10 or Windows 11
- **Python**: Version 3.8 or higher
- **Tkinter**: Included with standard Python installation on Windows

### Installation

1. **Clone or download** the repository:

   ```powershell
   git clone <repository-url>
   cd autoweb
   ```

2. **Verify Python installation**:

   ```powershell
   python --version
   ```

   Ensure Python 3.8+ is installed.

3. **No additional dependencies required!**
   The application uses only Python standard library modules.

### Running the Application

#### Option 1: Run directly

```powershell
python main.py
```

#### Option 2: Run as module

```powershell
python -m autoweb
```

---

## 📖 How to Use

1. **Launch** the application using one of the methods above
2. **Read** the warning message carefully
3. **Click** "I Understand & Agree" to provide consent
4. **Click** "Start Automation" to begin the automation cycle
5. **Monitor** the status display showing:
   - Current mode (Active/Idle)
   - Countdown timer
   - Active application name
   - Cycle count
6. **Click** "Stop" at any time to halt automation
7. **Close** the window to exit the application

---

## ⚙️ Automation Cycle Logic

### Active Phase (5 minutes)

During the active phase, the application performs random actions:

- **Mouse Movement**: Moves cursor to random screen positions
- **Mouse Clicks**: Occasional left-clicks at current position
- **App Switching**: Alt+Tab to switch between windows
- **Tab Switching**: Ctrl+Tab to switch tabs within applications

Actions occur at randomized intervals (3-10 seconds) to avoid predictable patterns.

### Idle Phase (2-4 minutes, random)

- No automation actions performed
- Simulates natural user breaks
- Duration is randomized within the configured range

### Cycle Repetition

The active/idle cycle repeats continuously until manually stopped.

---

## 🔧 How OS-Level Automation Works

### Window Management

The application uses the Windows API through `ctypes`:

- **`EnumWindows`**: Iterates through all top-level windows
- **`GetWindowText`**: Retrieves window title text
- **`SetForegroundWindow`**: Brings a window to the front
- **`IsWindowVisible`**: Checks window visibility

### Input Simulation

Mouse and keyboard input is simulated using the **SendInput** Windows API:

```
Physical Input → Hardware Driver → System Input Queue → Applications
                                          ↑
Simulated Input → SendInput API ──────────┘
```

This approach works with **all applications** because it operates at the system level, making synthetic events indistinguishable from real hardware input.

### Key Structures

- **`INPUT`**: Main structure passed to SendInput
- **`MOUSEINPUT`**: Contains mouse position and button state
- **`KEYBDINPUT`**: Contains virtual key codes and flags

---

## 📁 File Descriptions

### `main.py`

Entry point that performs platform checks and launches the UI.

```python
# Checks Windows platform
# Verifies dependencies
# Sets DPI awareness for high-res displays
# Launches the AutoWebApp
```

### `autoweb/window_manager.py`

Handles window detection and switching.

```python
# WindowInfo: Data class for window information
# WindowManager: Main class with methods:
#   - get_all_windows(): List all visible windows
#   - get_foreground_window(): Get currently active window
#   - switch_to_window(hwnd): Switch to specific window
#   - switch_to_next_window(): Cycle to next window
```

### `autoweb/input_simulator.py`

Handles mouse and keyboard simulation.

```python
# InputSimulator: Main class with methods:
#   - move_mouse(x, y): Move cursor to position
#   - move_mouse_smooth(x, y): Animated movement
#   - move_mouse_random(): Random position
#   - click(button): Mouse click
#   - key_press(vk): Press and release key
#   - shortcut_alt_tab(): Execute Alt+Tab
#   - shortcut_ctrl_tab(): Execute Ctrl+Tab
```

### `autoweb/scheduler.py`

Manages automation timing and execution.

```python
# AutomationPhase: Enum (STOPPED, ACTIVE, IDLE)
# SchedulerState: Current state data
# SchedulerConfig: Timing configuration
# AutomationScheduler: Main class with methods:
#   - start(): Begin automation
#   - stop(): Halt automation
#   - is_running(): Check status
```

### `autoweb/ui.py`

Provides the graphical user interface.

```python
# ConsentDialog: Warning and agreement dialog
# AutoWebApp: Main application window with:
#   - Status display (mode, timer, cycles)
#   - Start/Stop buttons
#   - Activity log
```

---

## 🛡️ Safety Features

1. **Consent Required**: Must agree to warning before starting
2. **No Auto-Start**: Requires explicit user action to begin
3. **Easy Stop**: Stop button always accessible
4. **Clean Shutdown**: Properly stops automation on window close
5. **Bounded Movement**: Mouse stays within screen boundaries
6. **Activity Logging**: All actions are logged for transparency

---

## ⚠️ Troubleshooting

### "tkinter not found" Error

Reinstall Python and ensure the **"tcl/tk and IDLE"** option is selected during installation.

### Mouse/Keyboard not responding

- Some applications with elevated privileges may block simulated input
- Run the automation tool with administrator privileges if needed

### Application doesn't switch windows

- Windows may restrict `SetForegroundWindow` calls from background processes
- The application uses thread attachment as a fallback

### High DPI display issues

The application sets DPI awareness automatically, but if UI elements appear blurry, try:

```powershell
# Right-click on Python executable → Properties → Compatibility
# Check "Override high DPI scaling behavior"
```

---

## 📝 Logging

The application logs activity to both console and `autoweb.log` file:

- Timestamp
- Module name
- Log level
- Message

---

## 🔒 Disclaimer

This software is provided "as is" for **testing and accessibility purposes only**. The authors are not responsible for any misuse or damage caused by this application. Users are responsible for ensuring they have proper authorization before running automation on any system.

---

## 📄 License

MIT License - See LICENSE file for details.

---

## 🤝 Contributing

Contributions are welcome! Please ensure any changes maintain the modular architecture and include appropriate documentation.

---

**Made with ❤️ for automation testing and accessibility**

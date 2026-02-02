"""
AutoWeb - Windows Desktop Automation Tool
==========================================

Main entry point for the AutoWeb application.

This application provides UI automation and accessibility testing capabilities
for Windows desktop applications. It requires explicit user consent before
performing any automation actions.

Usage:
    python main.py

Or run as a module:
    python -m autoweb

Features:
- Detect and switch between open application windows
- Simulate mouse movements and clicks
- Simulate keyboard input and shortcuts
- Automated active/idle cycles with randomized timing

IMPORTANT: This tool is for automation testing and accessibility use cases only.
"""

import sys
import logging
import ctypes

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Only console output
    ]
)
logger = logging.getLogger(__name__)


def check_platform():
    """
    Verify that we're running on Windows.
    
    The application uses Windows-specific APIs (user32.dll, kernel32.dll)
    and will not work on other platforms.
    
    Raises:
        SystemExit: If not running on Windows
    """
    if sys.platform != 'win32':
        logger.error(f"This application only runs on Windows. Current platform: {sys.platform}")
        print("❌ Error: AutoWeb requires Windows to run.")
        print("   This application uses Windows-specific APIs for input simulation.")
        sys.exit(1)


def check_dependencies():
    """
    Verify that required dependencies are available.
    
    Checks for:
    - tkinter (UI framework)
    - ctypes (Windows API access)
    
    Returns:
        bool: True if all dependencies are available
    """
    missing = []
    
    # Check tkinter
    try:
        import tkinter
    except ImportError:
        missing.append("tkinter")
    
    # Check ctypes (should always be available in standard Python)
    try:
        import ctypes
    except ImportError:
        missing.append("ctypes")
    
    if missing:
        logger.error(f"Missing dependencies: {', '.join(missing)}")
        print(f"❌ Error: Missing required dependencies: {', '.join(missing)}")
        print("   Please ensure you have a complete Python installation.")
        return False
    
    return True


def set_dpi_awareness():
    """
    Set DPI awareness for better display on high-DPI screens.
    
    Windows 10+ supports per-monitor DPI awareness, which ensures
    the application renders correctly on high-resolution displays.
    """
    try:
        # Try Windows 10+ per-monitor DPI awareness
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        logger.info("Set per-monitor DPI awareness")
    except Exception:
        try:
            # Fallback to Windows 8.1 system DPI awareness
            ctypes.windll.user32.SetProcessDPIAware()
            logger.info("Set system DPI awareness")
        except Exception as e:
            logger.warning(f"Could not set DPI awareness: {e}")


def main():
    """
    Main entry point for the AutoWeb application.
    
    Performs platform and dependency checks, then launches the UI.
    """
    print("=" * 60)
    print("  🤖 AutoWeb - UI Automation & Accessibility Testing Tool")
    print("=" * 60)
    print()
    
    # Platform check
    check_platform()
    
    # Dependency check
    if not check_dependencies():
        sys.exit(1)
    
    # Set DPI awareness for better display
    set_dpi_awareness()
    
    print("✓ Platform: Windows")
    print("✓ Dependencies: OK")
    print()
    print("Starting application...")
    print("-" * 60)
    print()
    
    logger.info("Starting AutoWeb application")
    
    try:
        # Import and run the UI
        from autoweb.ui import AutoWebApp
        
        app = AutoWebApp()
        app.run()
        
    except ImportError as e:
        logger.error(f"Failed to import application modules: {e}")
        print(f"❌ Error: Failed to load application: {e}")
        print("   Make sure all application files are present.")
        sys.exit(1)
        
    except Exception as e:
        logger.exception(f"Application error: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)
    
    logger.info("AutoWeb application closed")
    print()
    print("AutoWeb closed. Goodbye!")


if __name__ == "__main__":
    main()

"""
Application Protection Module
============================

Provides protection against unauthorized termination of the AutoWeb application.
If the application is terminated through any means (Ctrl+C, closing terminal,
closing VS Code, task manager, etc.), the system will automatically lock (Win+L).

This ensures monitoring cannot be bypassed by simply closing the application.

Protection Methods:
- Signal handlers (SIGINT, SIGTERM, SIGBREAK)
- atexit handlers (normal exit, unexpected termination)
- Windows console event handlers (close button, logoff, shutdown)
- Exception handlers (unhandled exceptions)
- Watchdog process monitoring

Safety Notes:
- Uses Windows LockWorkStation API for clean system lock
- Includes emergency unlock mechanism for development/debugging
- Logs all termination attempts for security audit
"""

import atexit
import signal
import ctypes
from ctypes import wintypes
import threading
import time
import logging
import sys
import os
import subprocess
import psutil
from typing import Optional, Callable
import win32gui
import win32con
import win32api

logger = logging.getLogger(__name__)

# Console control event types
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

# Power management constants
WM_POWERBROADCAST = 0x218
PBT_APMQUERYSUSPEND = 0x0000
PBT_APMSUSPEND = 0x0004
PBT_APMQUERYSUSPENDABORT = 0x0002
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016

# Session change constants
WM_WTSSESSION_CHANGE = 0x02B1
WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_CONNECT = 0x3
WTS_REMOTE_DISCONNECT = 0x4
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

class ApplicationProtection:
    """
    Comprehensive protection system that locks the workstation if the
    application is terminated unexpectedly.
    """
    
    def __init__(self, emergency_disable_file: Optional[str] = None):
        """
        Initialize application protection.
        
        Args:
            emergency_disable_file: Path to file that disables protection if exists
                                   (useful for development/debugging)
        """
        self._protection_enabled = False
        self._emergency_disable_file = emergency_disable_file or "disable_protection.txt"
        self._cleanup_functions = []
        self._lock_triggered = False
        self._watchdog_process = None
        self._original_handlers = {}
        self._power_window = None
        self._should_shutdown = False
        self._shutdown_reason = None
        
        logger.info("ApplicationProtection initialized")
    
    def enable_protection(self):
        """
        Enable all protection mechanisms.
        """
        if self._protection_enabled:
            logger.warning("Protection already enabled")
            return
        
        if self._is_emergency_disabled():
            logger.warning(f"Protection disabled by emergency file: {self._emergency_disable_file}")
            return
        
        logger.info("Enabling application protection...")
        
        try:
            # Register exit handlers
            self._setup_exit_handlers()
            
            # Setup signal handlers
            self._setup_signal_handlers()
            
            # Setup Windows console handlers
            self._setup_console_handlers()
            
            # Setup exception handler
            self._setup_exception_handler()
            
            # Setup power management monitoring
            self._setup_power_monitoring()
            
            # Start watchdog process
            self._start_watchdog()
            
            self._protection_enabled = True
            logger.warning("🔒 APPLICATION PROTECTION ENABLED - System will lock if app terminates")
            
        except Exception as e:
            logger.error(f"Failed to enable protection: {e}")
    
    def disable_protection(self):
        """
        Safely disable protection (for normal shutdown).
        """
        if not self._protection_enabled:
            return
        
        logger.info("Disabling application protection...")
        
        # Restore original handlers
        self._restore_original_handlers()
        
        # Stop watchdog
        self._stop_watchdog()
        
        # Cleanup power monitoring window
        self._cleanup_power_monitoring()
        
        # Run cleanup functions
        self._run_cleanup()
        
        self._protection_enabled = False
        logger.info("Application protection disabled")
    
    def add_cleanup_function(self, func: Callable[[], None]):
        """
        Add a function to be called before system lock.
        
        Args:
            func: Function to call during cleanup
        """
        self._cleanup_functions.append(func)
    
    @property
    def should_shutdown(self) -> bool:
        """Check if the application should shutdown."""
        return self._should_shutdown
    
    @property
    def shutdown_reason(self) -> Optional[str]:
        """Get the reason for shutdown."""
        return self._shutdown_reason
    
    def _is_emergency_disabled(self) -> bool:
        """Check if protection is disabled by emergency file."""
        try:
            return os.path.exists(self._emergency_disable_file)
        except Exception:
            return False
    
    def _setup_exit_handlers(self):
        """Setup atexit handlers."""
        atexit.register(self._on_exit)
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for common termination signals."""
        signals_to_handle = []
        
        # Standard signals available on Windows
        if hasattr(signal, 'SIGINT'):
            signals_to_handle.append(signal.SIGINT)  # Ctrl+C
        if hasattr(signal, 'SIGTERM'):
            signals_to_handle.append(signal.SIGTERM)  # Termination request
        if hasattr(signal, 'SIGBREAK'):
            signals_to_handle.append(signal.SIGBREAK)  # Ctrl+Break
        if hasattr(signal, 'SIGABRT'):
            signals_to_handle.append(signal.SIGABRT)  # Abort
        
        for sig in signals_to_handle:
            try:
                # Store original handler
                original = signal.signal(sig, self._signal_handler)
                self._original_handlers[sig] = original
                logger.debug(f"Setup signal handler for {sig}")
            except Exception as e:
                logger.debug(f"Could not setup handler for signal {sig}: {e}")
    
    def _setup_console_handlers(self):
        """Setup Windows console control event handlers."""
        try:
            # Define console handler function
            def console_handler(ctrl_type):
                logger.warning(f"Console control event: {ctrl_type}")
                
                if ctrl_type in [CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT]:
                    self._trigger_protection("Console close/break event")
                    return True  # Handled
                elif ctrl_type in [CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT]:
                    # Stop application when system is shutting down or user is logging off
                    reason = "System shutdown" if ctrl_type == CTRL_SHUTDOWN_EVENT else "User logoff"
                    logger.info(f"{reason} detected - stopping application")
                    self._shutdown_gracefully(reason)
                    return True  # We handled it
                
                return False
            
            # Convert to proper callback type
            HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            self._console_handler = HANDLER_ROUTINE(console_handler)
            
            # Set console control handler
            result = ctypes.windll.kernel32.SetConsoleCtrlHandler(
                self._console_handler, True
            )
            
            if result:
                logger.debug("Console control handler set successfully")
            else:
                logger.warning("Failed to set console control handler")
                
        except Exception as e:
            logger.error(f"Error setting up console handlers: {e}")
    
    def _setup_power_monitoring(self):
        """Setup monitoring for system power events (sleep/hibernate)."""
        try:
            # Create a hidden window to receive power broadcast messages
            self._create_power_window()
        except Exception as e:
            logger.error(f"Error setting up power monitoring: {e}")
    
    def _create_power_window(self):
        """Create a hidden window to receive WM_POWERBROADCAST messages."""
        try:
            # Define window procedure
            def wnd_proc(hwnd, message, w_param, l_param):
                if message == WM_POWERBROADCAST:
                    if w_param == PBT_APMQUERYSUSPEND:
                        logger.info("System preparing to sleep/hibernate - stopping application")
                        self._shutdown_gracefully("System sleep/hibernate")
                        return True
                    elif w_param == PBT_APMSUSPEND:
                        logger.info("System entering sleep/hibernate - stopping application")
                        self._shutdown_gracefully("System sleep/hibernate")
                        return True
                elif message == WM_QUERYENDSESSION:
                    logger.info("System requesting session end - stopping application")
                    self._shutdown_gracefully("Session ending")
                    return True
                elif message == WM_ENDSESSION:
                    if w_param:  # Session is actually ending
                        logger.info("Session ending - stopping application")
                        self._shutdown_gracefully("Session ended")
                    return True
                elif message == WM_WTSSESSION_CHANGE:
                    if w_param == WTS_SESSION_LOCK:
                        logger.info("Workstation locked (Win+L) - stopping application")
                        self._shutdown_gracefully("Workstation locked")
                        return True
                    elif w_param == WTS_SESSION_LOGOFF:
                        logger.info("User session logoff - stopping application")
                        self._shutdown_gracefully("User logoff")
                        return True
                    elif w_param == WTS_CONSOLE_DISCONNECT:
                        logger.info("Console disconnect - stopping application")
                        self._shutdown_gracefully("Console disconnect")
                        return True
                
                return win32gui.DefWindowProc(hwnd, message, w_param, l_param)
            
            # Register window class
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = wnd_proc
            wc.lpszClassName = "AutoWebPowerMonitor"
            wc.hInstance = win32api.GetModuleHandle(None)
            
            class_atom = win32gui.RegisterClass(wc)
            
            # Create window
            self._power_window = win32gui.CreateWindow(
                class_atom,
                "AutoWeb Power Monitor", 
                0,  # No window style (hidden)
                0, 0, 0, 0,  # Position and size
                0, 0,  # Parent and menu
                wc.hInstance,
                None
            )
            
            if self._power_window:
                logger.debug("Power monitoring window created successfully")
                
                # Register for session change notifications
                try:
                    import win32ts
                    win32ts.WTSRegisterSessionNotification(self._power_window, win32ts.NOTIFY_FOR_THIS_SESSION)
                    logger.debug("Registered for session change notifications")
                except Exception as e:
                    logger.warning(f"Could not register for session notifications: {e}")
            else:
                logger.warning("Failed to create power monitoring window")
                
        except Exception as e:
            logger.error(f"Error creating power monitoring window: {e}")
    
    def _shutdown_gracefully(self, reason: str):
        """Shutdown the application gracefully."""
        if self._should_shutdown:
            return  # Already shutting down
            
        self._should_shutdown = True
        self._shutdown_reason = reason
        logger.info(f"Graceful shutdown initiated: {reason}")
        
        # Run cleanup functions
        self._run_cleanup()
        
        # Disable protection
        self.disable_protection()
        
        # Exit the application
        threading.Thread(target=self._delayed_exit, daemon=True).start()
    
    def _delayed_exit(self):
        """Exit the application after a short delay to allow cleanup."""
        time.sleep(0.5)  # Give cleanup time to complete
        logger.info("Application exiting...")
        os._exit(0)  # Force exit
    
    def _setup_exception_handler(self):
        """Setup global exception handler."""
        def exception_handler(exctype, value, tb):
            if not self._lock_triggered:
                logger.error(f"Unhandled exception: {exctype.__name__}: {value}")
                self._trigger_protection("Unhandled exception")
            
            # Call original exception handler
            sys.__excepthook__(exctype, value, tb)
        
        sys.excepthook = exception_handler
    
    def _start_watchdog(self):
        """Start a separate watchdog process to monitor this process."""
        try:
            current_pid = os.getpid()
            current_exe = sys.executable
            current_script = os.path.abspath(__file__)
            
            # Create watchdog script
            watchdog_script = self._create_watchdog_script()
            
            # Start watchdog process
            self._watchdog_process = subprocess.Popen([
                current_exe, watchdog_script, str(current_pid)
            ], creationflags=subprocess.CREATE_NO_WINDOW)
            
            logger.debug(f"Started watchdog process: {self._watchdog_process.pid}")
            
        except Exception as e:
            logger.error(f"Failed to start watchdog: {e}")
    
    def _create_watchdog_script(self) -> str:
        """Create a temporary watchdog script."""
        import tempfile
        
        watchdog_code = '''
import sys
import time
import ctypes
import psutil
import logging

# Configure minimal logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

def lock_workstation():
    """Lock the workstation using Windows API."""
    try:
        result = ctypes.windll.user32.LockWorkStation()
        if result:
            logger.info("Workstation locked successfully")
        else:
            logger.error("Failed to lock workstation")
    except Exception as e:
        logger.error(f"Error locking workstation: {e}")

def main():
    if len(sys.argv) != 2:
        sys.exit(1)
    
    target_pid = int(sys.argv[1])
    
    try:
        # Monitor the target process
        while True:
            try:
                # Check if process exists
                if not psutil.pid_exists(target_pid):
                    logger.warning(f"Target process {target_pid} terminated - locking workstation")
                    lock_workstation()
                    break
                
                # Check if process is still running our application
                proc = psutil.Process(target_pid)
                if not proc.is_running():
                    logger.warning(f"Target process {target_pid} stopped - locking workstation")
                    lock_workstation()
                    break
                    
            except psutil.NoSuchProcess:
                logger.warning(f"Target process {target_pid} not found - locking workstation")
                lock_workstation()
                break
            except psutil.AccessDenied:
                # Process still exists but we can't access it
                pass
            except Exception as e:
                logger.error(f"Error monitoring process: {e}")
                time.sleep(1)
                continue
            
            time.sleep(2)  # Check every 2 seconds
            
    except Exception as e:
        logger.error(f"Watchdog error: {e}")

if __name__ == "__main__":
    main()
'''
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(watchdog_code)
            return f.name
    
    def _stop_watchdog(self):
        """Stop the watchdog process."""
        if self._watchdog_process:
            try:
                self._watchdog_process.terminate()
                self._watchdog_process.wait(timeout=5)
                logger.debug("Watchdog process terminated")
            except Exception as e:
                logger.error(f"Error stopping watchdog: {e}")
                try:
                    self._watchdog_process.kill()
                except Exception:
                    pass
            finally:
                self._watchdog_process = None
    
    def _cleanup_power_monitoring(self):
        """Cleanup power monitoring window."""
        if self._power_window:
            try:
                # Unregister session notifications
                try:
                    import win32ts
                    win32ts.WTSUnRegisterSessionNotification(self._power_window)
                    logger.debug("Unregistered session change notifications")
                except Exception as e:
                    logger.warning(f"Could not unregister session notifications: {e}")
                    
                # Destroy window
                win32gui.DestroyWindow(self._power_window)
                logger.debug("Power monitoring window destroyed")
            except Exception as e:
                logger.error(f"Error destroying power monitoring window: {e}")
            finally:
                self._power_window = None
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.warning(f"Received signal: {signal_name}")
        self._trigger_protection(f"Signal {signal_name}")
    
    def _on_exit(self):
        """Handle normal exit."""
        if self._protection_enabled and not self._lock_triggered:
            logger.warning("Application exiting unexpectedly")
            self._trigger_protection("Unexpected exit")
    
    def _trigger_protection(self, reason: str):
        """Trigger the protection mechanism (lock workstation)."""
        if self._lock_triggered:
            return  # Already triggered
        
        if self._is_emergency_disabled():
            logger.warning(f"Protection triggered but disabled by emergency file: {reason}")
            return
        
        self._lock_triggered = True
        logger.critical(f"🚨 PROTECTION TRIGGERED: {reason} - LOCKING WORKSTATION")
        
        # Run cleanup functions
        self._run_cleanup()
        
        # Lock workstation
        self._lock_workstation()
    
    def _lock_workstation(self):
        """Lock the workstation using Windows API."""
        try:
            # Use LockWorkStation for clean lock
            result = ctypes.windll.user32.LockWorkStation()
            if result:
                logger.info("Workstation locked successfully")
            else:
                logger.error("LockWorkStation failed, trying alternative...")
                # Alternative: Simulate Win+L
                self._simulate_win_l()
        except Exception as e:
            logger.error(f"Error locking workstation: {e}")
            # Fallback to Win+L simulation
            self._simulate_win_l()
    
    def _simulate_win_l(self):
        """Simulate Win+L key combination as fallback."""
        try:
            import time
            user32 = ctypes.windll.user32
            
            # Virtual key codes
            VK_LWIN = 0x5B  # Left Windows key
            VK_L = 0x4C     # L key
            
            # Key event constants
            KEYEVENTF_KEYUP = 0x0002
            
            # Press Win
            user32.keybd_event(VK_LWIN, 0, 0, 0)
            time.sleep(0.1)
            
            # Press L
            user32.keybd_event(VK_L, 0, 0, 0)
            time.sleep(0.1)
            
            # Release L
            user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.1)
            
            # Release Win
            user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
            
            logger.info("Simulated Win+L key combination")
            
        except Exception as e:
            logger.error(f"Failed to simulate Win+L: {e}")
    
    def _run_cleanup(self):
        """Run all registered cleanup functions."""
        for func in self._cleanup_functions:
            try:
                func()
            except Exception as e:
                logger.error(f"Error in cleanup function: {e}")
    
    def _restore_original_handlers(self):
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except Exception as e:
                logger.error(f"Error restoring handler for {sig}: {e}")
        
        self._original_handlers.clear()


# Global protection instance
_protection_instance: Optional[ApplicationProtection] = None


def enable_application_protection(emergency_disable_file: Optional[str] = None) -> ApplicationProtection:
    """
    Enable application protection globally.
    
    Args:
        emergency_disable_file: Path to emergency disable file
        
    Returns:
        ApplicationProtection instance
    """
    global _protection_instance
    
    if _protection_instance is None:
        _protection_instance = ApplicationProtection(emergency_disable_file)
    
    _protection_instance.enable_protection()
    return _protection_instance


def disable_application_protection():
    """Disable application protection globally."""
    global _protection_instance
    
    if _protection_instance:
        _protection_instance.disable_protection()


def add_cleanup_function(func: Callable[[], None]):
    """Add a cleanup function to be called before system lock."""
    global _protection_instance
    
    if _protection_instance:
        _protection_instance.add_cleanup_function(func)


def is_protection_enabled() -> bool:
    """Check if protection is currently enabled."""
    global _protection_instance
    return _protection_instance is not None and _protection_instance._protection_enabled


# Example usage
if __name__ == "__main__":
    # Test the protection system
    protection = enable_application_protection("emergency_disable.txt")
    
    print("Protection enabled. Try to close this with Ctrl+C...")
    print("Create 'emergency_disable.txt' file to bypass protection.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt caught, but protection should still trigger...")
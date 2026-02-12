
"""
AutoWeb Protection Demo
======================

This script demonstrates the application protection system.
Run this to see how the protection works without running the full UI.

Usage:
    python demo_protection.py

To test protection:
1. Run this script
2. Try to close it using Ctrl+C or closing the terminal
3. The system should lock automatically

System Event Handling:
- User logout: Application will stop cleanly
- System shutdown: Application will stop cleanly  
- System sleep/hibernate: Application will stop cleanly
- Workstation lock (Win+L): Application will stop cleanly
- Unexpected termination: System will lock

To disable protection for testing:
    Create a file named "emergency_disable.txt"
"""

import os
import sys
import time
import logging

# Add autoweb to path
sys.path.insert(0, os.path.dirname(__file__))

from autoweb.protection import enable_application_protection, disable_application_protection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("🔒 AutoWeb Protection Demo")
    print("=" * 30)
    print()
    
    print("This demo shows how the protection system works.")
    print("If you close this script unexpectedly, your system will lock.")
    print()
    print("System Events Handled:")
    print("• User logout → Application stops cleanly")
    print("• System shutdown → Application stops cleanly")
    print("• System sleep/hibernate → Application stops cleanly")
    print("• Workstation lock (Win+L) → Application stops cleanly")
    print("• Unexpected termination → System locks")
    print()
    
    # Enable protection
    protection = enable_application_protection("emergency_disable.txt")
    
    print("✅ Protection enabled!")
    print()
    print("Try closing this window or pressing Ctrl+C...")
    print("The system should lock automatically.")
    print()
    print("(To disable protection, create 'emergency_disable.txt' file)")
    print()
    
    try:
        counter = 0
        while True:
            # Check if protection system detected shutdown event
            if protection.should_shutdown:
                print(f"\n\n🛑 Shutdown detected: {protection.shutdown_reason}")
                print("Application stopping cleanly...")
                break
                
            counter += 1
            print(f"Running with protection... {counter:03d}s", end='\r')
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\nCtrl+C pressed - Normal shutdown")
        disable_application_protection()
        print("Protection disabled. Goodbye!")

if __name__ == "__main__":
    main()
"""
Protection Test Script
=====================

This script demonstrates the application protection feature.
When run, it will enable protection and then wait for termination.

If you try to close it with:
- Ctrl+C
- Closing the terminal window
- Killing the process
- Any other termination method

The system will automatically lock (Win+L) unless the emergency disable file exists.

To bypass protection during testing:
1. Create a file named "emergency_disable.txt" in the same directory
2. The protection will be disabled and won't trigger on termination

Usage:
    python test_protection.py
"""

import sys
import os
import time
import logging

# Add the autoweb package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from autoweb.protection import enable_application_protection, disable_application_protection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    print("=" * 60)
    print("  🔒 AutoWeb Protection Test")
    print("=" * 60)
    print()
    
    print("This script tests the application protection system.")
    print("If terminated unexpectedly, the system will lock (Win+L).")
    print()
    print("Emergency bypass:")
    print("  Create 'emergency_disable.txt' file to disable protection")
    print()
    
    # Check if emergency disable exists
    emergency_file = "emergency_disable.txt"
    if os.path.exists(emergency_file):
        print("🟡 EMERGENCY DISABLE DETECTED - Protection will be bypassed!")
        print(f"   Remove '{emergency_file}' to enable protection")
    else:
        print("🔒 PROTECTION WILL BE ENABLED")
        print("   System will lock if this script is terminated")
    
    print()
    print("Starting protection test in 3 seconds...")
    
    for i in range(3, 0, -1):
        print(f"   {i}...")
        time.sleep(1)
    
    print()
    print("🚀 Starting protection test...")
    
    # Enable protection
    protection = enable_application_protection(emergency_file)
    
    print()
    print("✅ Protection enabled!")
    print()
    print("Try to terminate this script using:")
    print("  • Ctrl+C")
    print("  • Closing this terminal window")
    print("  • Task Manager -> End Process")
    print("  • Any other method")
    print()
    print("The system should lock automatically unless emergency file exists.")
    print()
    print("To stop normally: Press Ctrl+C, then press Enter when prompted")
    print("-" * 60)
    
    # Test loop
    counter = 0
    try:
        while True:
            counter += 1
            print(f"Running... ({counter}) - Protection active", end='\r')
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n🟡 Ctrl+C detected!")
        
        # Ask user if they want normal shutdown
        try:
            response = input("Press Enter for NORMAL shutdown (disables protection) or Ctrl+C again for FORCED termination: ")
            
            # If they press Enter, do normal shutdown
            print("\n✅ Normal shutdown - disabling protection...")
            disable_application_protection()
            print("🔓 Protection disabled. Goodbye!")
            
        except KeyboardInterrupt:
            print("\n\n🚨 FORCED TERMINATION - Protection should trigger!")
            # Don't disable protection - let it trigger
            sys.exit(1)
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n🚨 UNEXPECTED ERROR: {e}")
        # Don't disable protection - let it trigger
        sys.exit(1)

if __name__ == "__main__":
    main()
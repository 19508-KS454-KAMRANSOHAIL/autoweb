"""
Test script for shutdown detection functionality
===============================================

This script tests the new logout/sleep/shutdown detection features
without the protection system.

Usage:
    python test_shutdown_detection.py
"""

import os
import sys
import time
import logging

# Add autoweb to path
sys.path.insert(0, os.path.dirname(__file__))

from autoweb.protection import ApplicationProtection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("🔍 Shutdown Detection Test")
    print("=" * 30)
    print()
    
    # Create protection object but don't enable full protection
    protection = ApplicationProtection("test_emergency_disable.txt")
    
    # Only setup power monitoring (not full protection)
    protection._setup_power_monitoring()
    
    print("✅ Power monitoring enabled!")
    print()
    print("Test the following:")
    print("• Try to put your computer to sleep (should detect)")
    print("• Try to log out (should detect)")  
    print("• Try to shut down (should detect)")
    print("• Press Win+L to lock workstation (should detect)")
    print()
    print("Press Ctrl+C to exit normally...")
    print()
    
    try:
        counter = 0
        while True:
            # Check if shutdown was detected
            if protection.should_shutdown:
                print(f"\n\n🛑 DETECTED: {protection.shutdown_reason}")
                print("Application would stop cleanly now!")
                break
                
            counter += 1
            print(f"Monitoring... {counter:03d}s", end='\r')
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\nCtrl+C pressed - Normal exit")
        
    finally:
        # Cleanup
        protection._cleanup_power_monitoring()
        print("Cleanup completed. Goodbye!")

if __name__ == "__main__":
    main()
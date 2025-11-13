#!/usr/bin/env python
"""
Test script for the Auth Debugger TUI screen.

Run this to verify the auth debugger screen works correctly.
"""

from testmcpy.tui.app import TestMCPyApp

if __name__ == "__main__":
    print("Launching testmcpy TUI with Auth Debugger...")
    print("Press 'a' or select 'Auth Debugger' from the menu to access the auth debugger.")
    print("Press 'q' to quit.\n")

    app = TestMCPyApp()
    app.run()

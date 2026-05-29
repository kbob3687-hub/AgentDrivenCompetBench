"""Playwright setup script - fix non-ASCII username path issue.

On Windows, if the username contains non-ASCII characters,
Playwright default browser path may fail to launch.

Solution: Install Playwright browsers to an ASCII-only path.

Usage:
    python scripts/setup_playwright.py
"""

import os
import subprocess
import sys


def main():
    user_home = os.path.expanduser("~")
    has_non_ascii = any(ord(c) > 127 for c in user_home)

    if not has_non_ascii:
        print("[OK] User path is ASCII-only, default Playwright install is fine")
        print("   Run: playwright install chromium")
        return

    print(f"[WARN] User path contains non-ASCII chars: {user_home}")
    print("   Playwright may not handle this path correctly")
    print()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    browsers_path = os.path.join(project_root, ".playwright-browsers")

    print(f"[DIR] Installing Playwright browsers to: {browsers_path}")
    print()

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    print("[...] Installing Chromium browser...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=os.environ,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("[OK] Chromium installed successfully!")
        print()
        print("[NOTE] Add this to your .env file:")
        print(f"   PLAYWRIGHT_BROWSERS_PATH={browsers_path}")
    else:
        print("[FAIL] Installation failed:")
        print(result.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

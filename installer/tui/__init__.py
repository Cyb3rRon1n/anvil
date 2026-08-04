"""
The Textual TUI: a second interface onto the same detect.py/tiers.py/
generate.py engine cli.py already wraps - same manager functions,
driven by screens instead of prompts. Mirrors Vulcan's installer/tui/
shape exactly.
"""

from installer.tui.app import AnvilApp


def run_tui() -> None:

    AnvilApp().run()

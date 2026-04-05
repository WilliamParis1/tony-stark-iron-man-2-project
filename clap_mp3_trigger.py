#!/usr/bin/env python3
"""Show a simple popup button that plays a repo MP3, then closes.

Run:
    python clap_mp3_trigger.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path


def find_mp3_in_repo() -> Path:
    """Find and return the first .mp3 file under this script's folder.

    We keep this small and predictable: sorted recursive search and first result.
    """
    repo_dir = Path(__file__).resolve().parent
    mp3_files = sorted(repo_dir.glob("**/*.mp3"))
    if not mp3_files:
        raise FileNotFoundError("No .mp3 file found in this repository folder.")
    return mp3_files[0]


def launch_mp3_with_default_player(mp3_path: Path) -> None:
    """Open the MP3 in the system's default media player.

    - Windows: os.startfile
    - macOS: open
    - Linux: xdg-open
    """
    mp3_str = str(mp3_path)

    if sys.platform == "win32":
        os.startfile(mp3_str)  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", mp3_str])
        return

    subprocess.Popen(["xdg-open", mp3_str])


def on_play_click(window: tk.Tk, mp3_path: Path) -> None:
    """Handle button click: play MP3 and close popup immediately."""
    launch_mp3_with_default_player(mp3_path)
    window.destroy()


def build_popup(mp3_path: Path) -> tk.Tk:
    """Create and return the popup window with one button."""
    window = tk.Tk()
    window.title("Play MP3")
    window.geometry("360x150")
    window.resizable(False, False)

    label = tk.Label(window, text=f"MP3: {mp3_path.name}")
    label.pack(pady=(20, 12))

    play_button = tk.Button(
        window,
        text="Play MP3",
        width=18,
        command=lambda: on_play_click(window, mp3_path),
    )
    play_button.pack()

    return window


def main() -> int:
    """Entry point: locate mp3, show popup, and run Tkinter event loop."""
    try:
        mp3_path = find_mp3_in_repo()
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    popup = build_popup(mp3_path)
    popup.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

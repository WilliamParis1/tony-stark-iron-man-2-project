#!/usr/bin/env python3
"""Play a repository MP3 file whenever a clap is detected from the microphone.

Usage:
    python clap_mp3_trigger.py
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np


def find_default_mp3() -> Path | None:
    """Return the first mp3 file found beside this script (or subfolders)."""
    script_dir = Path(__file__).resolve().parent
    mp3_files = sorted(script_dir.glob("**/*.mp3"))
    return mp3_files[0] if mp3_files else None


def parse_args() -> argparse.Namespace:
    default_mp3 = find_default_mp3()

    parser = argparse.ArgumentParser(description="Play an MP3 in this repo when you clap.")
    parser.add_argument(
        "--mp3",
        default=str(default_mp3) if default_mp3 else None,
        help="Path to MP3 file to play (defaults to first .mp3 found in this repo).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.25,
        help="Clap peak threshold (0.0-1.0). Lower if claps aren't detected.",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=0.8,
        help="Seconds to ignore new claps after one is detected.",
    )
    parser.add_argument(
        "--samplerate",
        type=int,
        default=44100,
        help="Audio sample rate for microphone input.",
    )
    parser.add_argument(
        "--blocksize",
        type=int,
        default=2048,
        help="Microphone frame size per callback.",
    )
    parser.add_argument(
        "--stdin-trigger",
        action="store_true",
        help="Use Enter key presses as clap triggers (good for github.dev/codespaces).",
    )
    args = parser.parse_args()

    if not args.mp3:
        parser.error(
            "No MP3 file found in this repository. Add an .mp3 file or pass --mp3 /path/to/file.mp3"
        )

    mp3_path = Path(args.mp3).resolve()
    if not mp3_path.exists() or mp3_path.suffix.lower() != ".mp3":
        parser.error(f"Invalid mp3 path: {args.mp3}")

    args.mp3 = str(mp3_path)
    return args


def get_sounddevice_module():
    """Load sounddevice lazily so missing PortAudio shows a clear setup error."""
    try:
        return importlib.import_module("sounddevice")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "sounddevice could not start because PortAudio is missing. "
            "Install system audio libs first (example Ubuntu: sudo apt-get update && "
            "sudo apt-get install -y libportaudio2 portaudio19-dev) then reinstall requirements."
        ) from exc


def _mci_send(command: str) -> None:
    """Send an MCI command on Windows and raise a descriptive error on failure."""
    error_code = ctypes.windll.winmm.mciSendStringW(command, None, 0, 0)
    if error_code != 0:
        buffer = ctypes.create_unicode_buffer(255)
        ctypes.windll.winmm.mciGetErrorStringW(error_code, buffer, 255)
        raise RuntimeError(f"MCI failed for '{command}': {buffer.value}")


def play_mp3(mp3_path: str) -> None:
    """Play mp3 without third-party playback dependencies.

    - On Windows: uses built-in WinMM/MCI (works for mp3).
    - Else: tries ffplay if available.
    """
    if sys.platform == "win32":
        alias = "clap_mp3"
        # Best effort close if previously open.
        try:
            _mci_send(f"close {alias}")
        except RuntimeError:
            pass

        _mci_send(f'open "{mp3_path}" type mpegvideo alias {alias}')
        _mci_send(f"play {alias} from 0")
        return

    ffplay_cmd = f"ffplay -nodisp -autoexit -loglevel quiet {shlex.quote(mp3_path)}"
    subprocess.Popen(ffplay_cmd, shell=True)  # noqa: S602


def start_player(mp3_path: str) -> queue.Queue:
    events: queue.Queue[str] = queue.Queue()

    def worker() -> None:
        while True:
            message = events.get()
            if message == "STOP":
                if sys.platform == "win32":
                    try:
                        _mci_send("close clap_mp3")
                    except RuntimeError:
                        pass
                return
            if message == "PLAY":
                try:
                    play_mp3(mp3_path)
                except Exception as exc:  # noqa: BLE001
                    print(f"Playback error: {exc}", file=sys.stderr)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return events


def run_manual_trigger_loop(player_events: queue.Queue) -> int:
    """Fallback mode for environments with no microphone (e.g., github.dev)."""
    print("Manual mode: press Enter to simulate a clap, type 'q' then Enter to quit.")
    while True:
        try:
            typed = input().strip().lower()
        except EOFError:
            break
        if typed in {"q", "quit", "exit"}:
            break
        player_events.put("PLAY")
    return 0


def find_default_input_device(sd_module) -> int | None:
    """Return an input-capable device index, or None if none exists."""
    devices = sd_module.query_devices()
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            return idx
    return None


def main() -> int:
    args = parse_args()
    player_events = start_player(args.mp3)

    last_trigger_time = 0.0
    backend = "windows-mci" if sys.platform == "win32" else "ffplay"

    print(f"Using MP3: {args.mp3}")
    print(f"Playback backend: {backend}")

    if args.stdin_trigger:
        try:
            return run_manual_trigger_loop(player_events)
        finally:
            player_events.put("STOP")

    try:
        sd = get_sounddevice_module()
    except RuntimeError as exc:
        print(f"{exc}\nSwitching to manual trigger mode automatically.", file=sys.stderr)
        try:
            return run_manual_trigger_loop(player_events)
        finally:
            player_events.put("STOP")

    input_device = find_default_input_device(sd)
    if input_device is None:
        print(
            "No microphone/input audio device is available in this environment. "
            "Switching to manual trigger mode automatically.",
            file=sys.stderr,
        )
        try:
            return run_manual_trigger_loop(player_events)
        finally:
            player_events.put("STOP")

    def callback(indata: np.ndarray, frames: int, cb_time, status) -> None:  # type: ignore[no-untyped-def]
        nonlocal last_trigger_time
        del frames, cb_time
        if status:
            print(f"Input stream status: {status}", file=sys.stderr)

        peak = float(np.max(np.abs(indata)))
        now = time.time()

        if peak >= args.threshold and (now - last_trigger_time) >= args.cooldown:
            last_trigger_time = now
            print(f"Clap detected (peak={peak:.3f}). Playing sound...")
            player_events.put("PLAY")

    print("Listening for claps... Press Ctrl+C to stop.")

    try:
        with sd.InputStream(
            device=input_device,
            channels=1,
            callback=callback,
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            dtype="float32",
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        player_events.put("STOP")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Play a repository MP3 file whenever a clap is detected from the microphone.

Usage:
    python clap_mp3_trigger.py
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import pygame


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


def start_player(mp3_path: str) -> queue.Queue:
    events: queue.Queue[str] = queue.Queue()

    pygame.mixer.init()
    clap_sound = pygame.mixer.Sound(mp3_path)

    def worker() -> None:
        while True:
            message = events.get()
            if message == "STOP":
                pygame.mixer.quit()
                return
            if message == "PLAY":
                try:
                    clap_sound.play()
                except Exception as exc:  # noqa: BLE001
                    print(f"Playback error: {exc}", file=sys.stderr)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return events


def main() -> int:
    args = parse_args()
    player_events = start_player(args.mp3)

    last_trigger_time = 0.0

    print(f"Using MP3: {args.mp3}")

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

#!/usr/bin/env python3
"""Play an MP3 file whenever a clap is detected from the microphone.

Usage:
    python clap_mp3_trigger.py --mp3 /path/to/sound.mp3
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from playsound import playsound


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play an MP3 when you clap.")
    parser.add_argument("--mp3", required=True, help="Path to MP3 file to play")
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
    return parser.parse_args()


def start_player(mp3_path: str) -> queue.Queue:
    events: queue.Queue[str] = queue.Queue()

    def worker() -> None:
        while True:
            message = events.get()
            if message == "STOP":
                return
            if message == "PLAY":
                try:
                    playsound(mp3_path, block=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"Playback error: {exc}", file=sys.stderr)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return events


def main() -> int:
    args = parse_args()
    player_events = start_player(args.mp3)

    last_trigger_time = 0.0

    def callback(indata: np.ndarray, frames: int, cb_time, status) -> None:  # type: ignore[no-untyped-def]
        nonlocal last_trigger_time
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

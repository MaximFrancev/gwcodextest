from __future__ import annotations

import argparse
from pathlib import Path

from gw_emulator import GameAndWatchEmulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prototype Game & Watch (2020) emulator")
    parser.add_argument(
        "--rom",
        type=Path,
        default=None,
        help="Path to a ROM file to load (placed into serial flash).",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="Scale factor for the 320x240 display (default: 2).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emulator = GameAndWatchEmulator(args.rom)
    emulator.run(scale=args.scale)


if __name__ == "__main__":
    main()

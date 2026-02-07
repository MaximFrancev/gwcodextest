import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set
import tkinter as tk


SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240
TARGET_FPS = 30


BUTTON_KEYMAP = {
    "Left": ["Left"],
    "Right": ["Right"],
    "Up": ["Up"],
    "Down": ["Down"],
    "A": ["z", "Z"],
    "B": ["x", "X"],
    "Game": ["g", "G"],
    "Time": ["t", "T"],
    "Pause/Set": ["p", "P"],
    "Power": ["Return"],
}


@dataclass
class RomMetadata:
    name: str
    path: Path
    size: int


class RomLoader:
    def __init__(self, rom_path: Path) -> None:
        self.rom_path = rom_path

    def load(self) -> bytes:
        with self.rom_path.open("rb") as rom_file:
            return rom_file.read()

    def describe(self) -> RomMetadata:
        return RomMetadata(
            name=self.rom_path.stem,
            path=self.rom_path,
            size=self.rom_path.stat().st_size,
        )


class InputState:
    def __init__(self) -> None:
        self.pressed: Set[str] = set()

    def set_button(self, button: str, is_pressed: bool) -> None:
        if is_pressed:
            self.pressed.add(button)
        else:
            self.pressed.discard(button)

    def format_pressed(self) -> str:
        if not self.pressed:
            return "None"
        return ", ".join(sorted(self.pressed))


class RomVisualizer:
    def __init__(self, rom_data: bytes, width: int, height: int) -> None:
        self.rom_data = rom_data
        self.width = width
        self.height = height
        self.length = max(len(rom_data), 1)

    def frame_rows(self, frame_index: int, buttons: Iterable[str]) -> List[str]:
        offset = (frame_index * 97) % self.length
        button_boost = {
            "A": (40, 0, 0),
            "B": (0, 40, 0),
            "Game": (0, 0, 40),
            "Time": (20, 20, 0),
            "Pause/Set": (0, 20, 20),
            "Power": (20, 0, 20),
        }
        boost = [0, 0, 0]
        for button in buttons:
            if button in button_boost:
                b = button_boost[button]
                boost[0] += b[0]
                boost[1] += b[1]
                boost[2] += b[2]
        rows: List[str] = []
        for y in range(self.height):
            row_colors: List[str] = []
            base = (offset + y * self.width * 3) % self.length
            for x in range(self.width):
                idx = (base + x * 3) % self.length
                r = (self.rom_data[idx] + boost[0]) % 256
                g = (self.rom_data[(idx + 1) % self.length] + boost[1]) % 256
                b = (self.rom_data[(idx + 2) % self.length] + boost[2]) % 256
                row_colors.append(f"#{r:02x}{g:02x}{b:02x}")
            rows.append(" ".join(row_colors))
        return rows


class EmulatorApp:
    def __init__(self, rom_data: bytes, metadata: RomMetadata) -> None:
        self.rom_data = rom_data
        self.metadata = metadata
        self.input_state = InputState()
        self.root = tk.Tk()
        self.root.title("Game & Watch (2020) Emulator Prototype")
        self.root.configure(background="#111")
        self.frame_index = 0
        self.last_frame_time = time.monotonic()

        self.header_label = tk.Label(
            self.root,
            text=f"ROM: {metadata.name} ({metadata.size} bytes)",
            fg="#f0f0f0",
            bg="#111",
            font=("Helvetica", 12, "bold"),
        )
        self.header_label.pack(pady=(10, 4))

        self.status_label = tk.Label(
            self.root,
            text="Pressed: None",
            fg="#cfcfcf",
            bg="#111",
            font=("Helvetica", 10),
        )
        self.status_label.pack(pady=(0, 8))

        self.photo = tk.PhotoImage(width=SCREEN_WIDTH, height=SCREEN_HEIGHT)
        self.canvas = tk.Canvas(
            self.root,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            highlightthickness=0,
            bg="#000",
        )
        self.canvas.pack(padx=12, pady=12)
        self.image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        self.visualizer = RomVisualizer(self.rom_data, SCREEN_WIDTH, SCREEN_HEIGHT)

        self.root.bind("<KeyPress>", self.handle_key_press)
        self.root.bind("<KeyRelease>", self.handle_key_release)
        self.root.after(0, self.tick)

    def handle_key_press(self, event: tk.Event) -> None:
        self.update_button_state(event.keysym, True)

    def handle_key_release(self, event: tk.Event) -> None:
        self.update_button_state(event.keysym, False)

    def update_button_state(self, keysym: str, is_pressed: bool) -> None:
        for button, keys in BUTTON_KEYMAP.items():
            if keysym in keys:
                self.input_state.set_button(button, is_pressed)
        self.status_label.configure(
            text=f"Pressed: {self.input_state.format_pressed()}"
        )

    def tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_frame_time
        target_delta = 1 / TARGET_FPS
        if elapsed >= target_delta:
            self.render_frame()
            self.last_frame_time = now
        self.root.after(1, self.tick)

    def render_frame(self) -> None:
        rows = self.visualizer.frame_rows(self.frame_index, self.input_state.pressed)
        for y, row in enumerate(rows):
            self.photo.put(row, to=(0, y))
        self.frame_index += 1

    def run(self) -> None:
        self.root.mainloop()


def find_default_rom(rom_root: Path) -> Path:
    if rom_root.is_file():
        return rom_root

    candidates = list(rom_root.glob("**/*.bin"))
    if not candidates:
        raise FileNotFoundError(
            f"No .bin ROMs found under {rom_root}. Provide a ROM path."
        )

    preferred = [
        path
        for path in candidates
        if path.name in {"internal_flash.bin", "external_flash.bin"}
    ]
    return (preferred or candidates)[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prototype emulator shell for the Game & Watch (2020)."
    )
    parser.add_argument(
        "--rom",
        type=str,
        default=str(Path("roms")),
        help="Path to a ROM .bin file or a directory containing ROMs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rom_path = find_default_rom(Path(args.rom))
    loader = RomLoader(rom_path)
    rom_data = loader.load()
    metadata = loader.describe()

    app = EmulatorApp(rom_data, metadata)
    app.run()


if __name__ == "__main__":
    main()

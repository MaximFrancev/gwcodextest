# Game & Watch (2020) Emulator Prototype

This repository contains a **prototype** emulator shell for the 2020 Game & Watch hardware. It is not a cycle-accurate emulator yet, but it models the memory sizes, loads ROMs into serial flash, and provides a 320x240 window with keyboard input.

## Features

- 320x240 display window (scaled up for visibility).
- Memory map with STM32H7B0 flash banks, SRAM, and serial flash sizing.
- Keyboard-driven input mapping.
- ROM loading into serial flash for quick experimentation.

## Requirements

- Python 3.10+
- `pygame` (see `requirements.txt`)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running

```bash
python main.py --rom roms/your_rom.bin --scale 2
```

If you omit `--rom`, the emulator still runs but with an empty serial flash.

## Controls

| Key | Button |
| --- | --- |
| Arrow keys | D-pad |
| Z | A |
| X | B |
| G | Game |
| T | Time |
| P | Pause/Set |
| Esc | Power/Exit |

## Notes

This is a starting point for the emulator architecture. The display is currently a debug HUD that shows button states, cycles, and the active ROM name. See the `docs/` folder for hardware notes and pinouts.

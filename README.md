# Game & Watch (2020) Emulator Prototype

This repository contains a lightweight Python prototype that provides a **visual shell** for a
Nintendo Game & Watch (2020) emulator. It is *not* a cycle-accurate emulator yet, but it lets you
load ROM dumps, map controller input to the keyboard, and visualize ROM data on a 320×240 screen
surface so you can start experimenting with input handling and display output.

## What this prototype does

- Loads a ROM `.bin` file (or scans the `roms/` directory by default).
- Opens a 320×240 window that acts as the LCD screen.
- Maps Game & Watch buttons to keyboard keys (see below).
- Renders a deterministic color pattern based on ROM bytes, so you have immediate visual feedback
  while wiring up future emulation logic.

## Button mapping

| Game & Watch button | Keyboard |
| --- | --- |
| Left | ← |
| Right | → |
| Up | ↑ |
| Down | ↓ |
| A | Z |
| B | X |
| Game | G |
| Time | T |
| Pause/Set | P |
| Power | Enter |

## Running the prototype

```bash
python emulator.py
```

To load a specific ROM file or directory:

```bash
python emulator.py --rom roms/mario/internal_flash.bin
python emulator.py --rom roms/zelda
```

## Next steps for a real emulator

This shell is a starting point. To move toward a real emulator, you can layer in:

1. ARM Cortex-M7 CPU emulation (instruction decode + execution).
2. Memory map definitions for internal/external flash, SRAM, and peripherals.
3. GPIO input handling (from the keyboard) mapped to STM32 registers.
4. A proper LCD controller implementation that uses real framebuffer data.

The documentation in `docs/` should help map the hardware details as you implement each subsystem.

---

> Note: remember to remove ROMs before any public release to avoid copyright issues.

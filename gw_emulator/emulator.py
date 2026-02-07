from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

import pygame

SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240

BUTTONS = (
    "LEFT",
    "UP",
    "DOWN",
    "RIGHT",
    "A",
    "B",
    "GAME",
    "TIME",
    "PAUSE",
    "POWER",
)

KEY_MAP = {
    pygame.K_LEFT: "LEFT",
    pygame.K_UP: "UP",
    pygame.K_DOWN: "DOWN",
    pygame.K_RIGHT: "RIGHT",
    pygame.K_z: "A",
    pygame.K_x: "B",
    pygame.K_g: "GAME",
    pygame.K_t: "TIME",
    pygame.K_p: "PAUSE",
    pygame.K_ESCAPE: "POWER",
}


@dataclass
class MemoryMap:
    flash_bank_size: int = 256 * 1024
    flash_banks: int = 2
    sram_size: int = 1380 * 1024
    serial_flash_size: int = 1024 * 1024
    flash: bytearray = field(init=False)
    sram: bytearray = field(init=False)
    serial_flash: bytearray = field(init=False)

    def __post_init__(self) -> None:
        self.flash = bytearray(self.flash_bank_size * self.flash_banks)
        self.sram = bytearray(self.sram_size)
        self.serial_flash = bytearray(self.serial_flash_size)


@dataclass
class EmulatorState:
    buttons: Dict[str, bool] = field(default_factory=lambda: {name: False for name in BUTTONS})
    cycles: int = 0
    paused: bool = False
    rom_name: str = "(none)"


class GameAndWatchEmulator:
    def __init__(self, rom_path: Path | None = None) -> None:
        self.memory = MemoryMap()
        self.state = EmulatorState()
        self._load_rom(rom_path)

    def _load_rom(self, rom_path: Path | None) -> None:
        if rom_path is None:
            return
        data = rom_path.read_bytes()
        self.state.rom_name = rom_path.name
        target = self.memory.serial_flash
        target[: len(data)] = data[: len(target)]

    def _update_button(self, button: str, pressed: bool) -> None:
        self.state.buttons[button] = pressed
        if button == "PAUSE" and pressed:
            self.state.paused = not self.state.paused

    def _handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.QUIT:
            return False
        if event.type in (pygame.KEYDOWN, pygame.KEYUP):
            pressed = event.type == pygame.KEYDOWN
            button = KEY_MAP.get(event.key)
            if button:
                if button == "POWER" and pressed:
                    return False
                self._update_button(button, pressed)
        return True

    def _step_cpu(self) -> None:
        if self.state.paused:
            return
        self.state.cycles += 1

    def _render(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        screen.fill((12, 12, 16))
        header = font.render("Game & Watch (2020) Emulator", True, (236, 236, 240))
        screen.blit(header, (10, 10))
        rom_text = font.render(f"ROM: {self.state.rom_name}", True, (180, 200, 255))
        screen.blit(rom_text, (10, 40))
        cycles_text = font.render(f"Cycles: {self.state.cycles}", True, (180, 200, 255))
        screen.blit(cycles_text, (10, 65))

        status = "PAUSED" if self.state.paused else "RUNNING"
        status_text = font.render(f"Status: {status}", True, (255, 200, 120))
        screen.blit(status_text, (10, 90))

        y = 130
        for name in BUTTONS:
            state = "ON" if self.state.buttons[name] else "OFF"
            color = (120, 240, 180) if self.state.buttons[name] else (120, 120, 120)
            text = font.render(f"{name}: {state}", True, color)
            screen.blit(text, (10, y))
            y += 20

    def run(self, scale: int = 2) -> None:
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_WIDTH * scale, SCREEN_HEIGHT * scale))
        pygame.display.set_caption("Game & Watch Emulator (Prototype)")
        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        font = pygame.font.SysFont("Arial", 16)
        clock = pygame.time.Clock()

        running = True
        while running:
            for event in pygame.event.get():
                if not self._handle_event(event):
                    running = False
                    break
            self._step_cpu()
            self._render(surface, font)
            pygame.transform.scale(surface, screen.get_size(), screen)
            pygame.display.flip()
            clock.tick(60)
        pygame.quit()
